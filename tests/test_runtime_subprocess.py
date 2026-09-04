"""Deterministic subprocess-lifecycle tests using a local fake executable."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract
from agentic_os.runtimes.base import (
    SubprocessRuntimeAdapter,
    UnsupportedSteeringError,
    WorkspacePolicyError,
)
from agentic_os.runtimes.contracts import (
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeEventType,
    RuntimeStatus,
    Workspace,
)


@pytest.fixture
def fake_runtime(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-runtime"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import os\n"
        "import signal\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "mode = sys.argv[1]\n"
        "if mode == 'success':\n"
        "    print(json.dumps({'status': 'completed', 'summary': 'done', "
        "'result': {'cwd': os.getcwd()}}))\n"
        "    print('fake warning', file=sys.stderr)\n"
        "elif mode == 'invalid':\n"
        "    print('ordinary output, not an envelope')\n"
        "elif mode == 'failure':\n"
        "    print('partial stdout', flush=True)\n"
        "    print('partial stderr', file=sys.stderr, flush=True)\n"
        "    raise SystemExit(7)\n"
        "elif mode == 'wait':\n"
        "    print('partial stdout', flush=True)\n"
        "    print('partial stderr', file=sys.stderr, flush=True)\n"
        "    time.sleep(60)\n"
        "elif mode == 'child':\n"
        "    child = subprocess.Popen([sys.executable, '-c', "
        "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
        "    Path = __import__('pathlib').Path\n"
        "    Path(sys.argv[2]).write_text(str(child.pid))\n"
        "    print('partial stdout', flush=True)\n"
        "    time.sleep(60)\n"
    )
    executable.chmod(0o755)
    return executable


def _task(*, timeout_seconds: float | None = None) -> TaskContract:
    limits = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
    return TaskContract(
        goal_id="goal_runtime",
        worker_role="runtime-test",
        objective="run the fake executable",
        limits=limits,
    )


def _workspace(tmp_path: Path, *, allow_write: bool = True) -> Workspace:
    approved = tmp_path / "approved"
    root = approved / "workspace"
    root.mkdir(parents=True)
    return Workspace(root=root, approved_root=approved, allow_write=allow_write)


def _adapter(
    tmp_path: Path,
    executable: Path,
    mode: str,
    *extra_args: str,
    capabilities: set[RuntimeCapability] | None = None,
    timeout_seconds: float | None = None,
) -> SubprocessRuntimeAdapter:
    supported = capabilities or {
        RuntimeCapability.EXECUTE,
        RuntimeCapability.STREAM_EVENTS,
        RuntimeCapability.STRUCTURED_RESULT,
        RuntimeCapability.ISOLATED_WRITE_WORKSPACE,
        RuntimeCapability.READ_ONLY_WORKSPACE,
    }
    return SubprocessRuntimeAdapter(
        runtime_name="fake",
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        command_builder=lambda task, workspace: [str(executable), mode, *extra_args],
        capabilities=RuntimeCapabilities(supported=supported),
        timeout_seconds=timeout_seconds,
        termination_grace_seconds=0.05,
    )


async def test_start_streams_events_and_returns_one_structured_result(tmp_path, fake_runtime):
    workspace = _workspace(tmp_path)
    adapter = _adapter(tmp_path, fake_runtime, "success")

    handle = await adapter.start(_task(), workspace)
    events = [event async for event in adapter.events(handle)]
    first = await adapter.result(handle)
    second = await adapter.result(handle)

    assert first is second
    assert first.status is RuntimeStatus.COMPLETED
    assert first.result_data == {"cwd": str(workspace.root)}
    assert events[0].event_type is RuntimeEventType.STARTED
    assert events[-1].event_type is RuntimeEventType.COMPLETED
    assert {event.event_type for event in events[1:-1]} == {
        RuntimeEventType.STDOUT,
        RuntimeEventType.STDERR,
    }
    assert adapter.artifacts.get(first.output_ref).startswith(b'{"status": "completed"')
    assert adapter.artifacts.get(first.artifacts[1]) == b"fake warning\n"


async def test_invalid_structured_output_never_fabricates_success(tmp_path, fake_runtime):
    adapter = _adapter(tmp_path, fake_runtime, "invalid")
    handle = await adapter.start(_task(), _workspace(tmp_path))

    result = await adapter.result(handle)

    assert result.status is RuntimeStatus.FAILED
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["structured_result_invalid"]
    assert adapter.artifacts.get(result.output_ref) == b"ordinary output, not an envelope\n"


async def test_exit_failure_preserves_partial_stdout_and_stderr(tmp_path, fake_runtime):
    adapter = _adapter(tmp_path, fake_runtime, "failure")
    handle = await adapter.start(_task(), _workspace(tmp_path))

    result = await adapter.result(handle)

    assert result.status is RuntimeStatus.FAILED
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["exit_code"]
    assert adapter.artifacts.get(result.output_ref) == b"partial stdout\n"
    assert adapter.artifacts.get(result.artifacts[1]) == b"partial stderr\n"


async def test_stop_cancels_and_preserves_partial_artifacts(tmp_path, fake_runtime):
    adapter = _adapter(tmp_path, fake_runtime, "wait")
    handle = await adapter.start(_task(), _workspace(tmp_path))
    await asyncio.sleep(0.03)

    result = await adapter.stop(handle)

    assert result.status is RuntimeStatus.CANCELLED
    assert adapter.artifacts.get(result.output_ref) == b"partial stdout\n"
    assert adapter.artifacts.get(result.artifacts[1]) == b"partial stderr\n"


async def test_cancelling_result_wait_stops_the_owned_process(tmp_path, fake_runtime):
    adapter = _adapter(tmp_path, fake_runtime, "wait")
    handle = await adapter.start(_task(), _workspace(tmp_path))
    waiting = asyncio.create_task(adapter.result(handle))
    await asyncio.sleep(0.03)
    waiting.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert (await adapter.result(handle)).status is RuntimeStatus.CANCELLED


async def test_timeout_kills_the_entire_process_group_including_a_child(tmp_path, fake_runtime):
    child_pid_path = tmp_path / "child.pid"
    adapter = _adapter(tmp_path, fake_runtime, "child", str(child_pid_path))
    handle = await adapter.start(_task(timeout_seconds=0.1), _workspace(tmp_path))
    for _ in range(50):
        if child_pid_path.exists():
            break
        await asyncio.sleep(0.01)
    child_pid = int(child_pid_path.read_text())

    result = await adapter.result(handle)

    assert result.status is RuntimeStatus.TIMED_OUT
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["timeout"]
    assert adapter.artifacts.get(result.output_ref) == b"partial stdout\n"
    assert _process_is_gone(child_pid)
    events = [event async for event in adapter.events(handle)]
    assert [event.event_type for event in events if event.status is not RuntimeStatus.RUNNING] == [
        RuntimeEventType.TIMED_OUT
    ]


async def test_workspace_policy_is_checked_before_command_construction(tmp_path, fake_runtime):
    calls = 0

    def command_builder(task, workspace):
        nonlocal calls
        del task, workspace
        calls += 1
        return [str(fake_runtime), "success"]

    adapter = SubprocessRuntimeAdapter(
        runtime_name="fake",
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        command_builder=command_builder,
        capabilities=RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]),
    )

    with pytest.raises(WorkspacePolicyError, match="isolated_write"):
        await adapter.start(_task(), _workspace(tmp_path))

    assert calls == 0


async def test_read_only_workspace_and_unsupported_steering_are_explicit(tmp_path, fake_runtime):
    adapter = _adapter(
        tmp_path,
        fake_runtime,
        "success",
        capabilities={
            RuntimeCapability.EXECUTE,
            RuntimeCapability.STREAM_EVENTS,
            RuntimeCapability.STRUCTURED_RESULT,
            RuntimeCapability.ISOLATED_WRITE_WORKSPACE,
        },
    )

    with pytest.raises(WorkspacePolicyError, match="read_only"):
        await adapter.start(_task(), _workspace(tmp_path, allow_write=False))

    writable = _workspace(tmp_path / "writable")
    handle = await adapter.start(_task(), writable)
    with pytest.raises(UnsupportedSteeringError, match="does not support steering"):
        await adapter.steer(handle, "change direction")
    await adapter.result(handle)


def _process_is_gone(pid: int) -> bool:
    """Treat an already-reaped process or a Linux zombie as fully terminated."""
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists() and ") Z " in stat_path.read_text():
            return True
        time.sleep(0.01)
    return False
