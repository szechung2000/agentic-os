"""Deterministic tests for the Claude, Codex, and agy headless adapters.

A single fake executable stands in for all three CLIs: it echoes back the
argv it received, its cwd, and a fixed set of environment variables inside
the structured result envelope the base subprocess lifecycle already knows
how to parse. That lets these tests assert exact command construction,
workspace cwd, and environment isolation without any real network access,
credentials, or provider-specific parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract
from agentic_os.runtimes.agy import AgyAdapter, build_agy_command
from agentic_os.runtimes.base import UnsupportedSteeringError
from agentic_os.runtimes.claude import ClaudeCodeAdapter, build_claude_command
from agentic_os.runtimes.codex import CodexAdapter, build_codex_command
from agentic_os.runtimes.contracts import RuntimeStatus, Workspace

ADAPTER_CLASSES = (ClaudeCodeAdapter, CodexAdapter, AgyAdapter)

_PROBED_ENV_NAMES = (
    "PATH",
    "HOME",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AGY_API_KEY",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "UNRELATED_ENV_VAR",
    "AWS_SECRET_ACCESS_KEY",
)


@pytest.fixture
def fake_cli(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-cli"
    probed = repr(_PROBED_ENV_NAMES)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        f"probed = {probed}\n"
        "print(json.dumps({\n"
        "    'status': 'completed',\n"
        "    'summary': 'ok',\n"
        "    'result': {\n"
        "        'argv': sys.argv[1:],\n"
        "        'cwd': os.getcwd(),\n"
        "        'env': {name: os.environ[name] for name in probed if name in os.environ},\n"
        "    },\n"
        "}))\n"
    )
    executable.chmod(0o755)
    return executable


def _task(objective: str = "summarize the repository") -> TaskContract:
    return TaskContract(goal_id="goal_e1", worker_role="runtime-adapter-test", objective=objective)


def _workspace(tmp_path: Path) -> Workspace:
    approved = tmp_path / "approved"
    root = approved / "workspace"
    root.mkdir(parents=True)
    return Workspace(root=root, approved_root=approved, allow_write=True)


def _artifacts(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


# --- Pure command construction, no subprocess involved -----------------


def test_build_claude_command_with_and_without_model(tmp_path):
    task = _task("explain the bug")
    workspace = _workspace(tmp_path)

    assert build_claude_command(task, workspace, executable="claude") == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--",
        "explain the bug",
    ]
    assert build_claude_command(task, workspace, executable="claude", model="opus") == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        "opus",
        "--",
        "explain the bug",
    ]


def test_build_codex_command_with_and_without_model(tmp_path):
    task = _task("fix the failing test")
    workspace = _workspace(tmp_path)

    assert build_codex_command(task, workspace, executable="codex") == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--",
        "fix the failing test",
    ]
    assert build_codex_command(task, workspace, executable="codex", model="gpt-5-codex") == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--model",
        "gpt-5-codex",
        "--",
        "fix the failing test",
    ]
    for command in (
        build_codex_command(task, workspace),
        build_codex_command(task, workspace, model="gpt-5-codex"),
    ):
        assert "--dangerously-bypass-approvals-and-sandbox" not in command
        assert "--yolo" not in command


def test_build_agy_command_with_and_without_model(tmp_path):
    task = _task("draft release notes")
    workspace = _workspace(tmp_path)

    assert build_agy_command(task, workspace, executable="agy") == [
        "agy",
        "-p",
        "--output-format",
        "json",
        "--",
        "draft release notes",
    ]
    assert build_agy_command(task, workspace, executable="agy", model="agy-large") == [
        "agy",
        "-p",
        "--output-format",
        "json",
        "--model",
        "agy-large",
        "--",
        "draft release notes",
    ]


@pytest.mark.parametrize("builder", [build_claude_command, build_codex_command, build_agy_command])
def test_command_builders_never_enable_dangerous_permission_flags(tmp_path, builder):
    task = _task()
    workspace = _workspace(tmp_path)
    command = builder(task, workspace, model="some-model")

    dangerous_flags = {
        "--dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--yolo",
        "--full-auto",
    }
    assert dangerous_flags.isdisjoint(command)


# --- End-to-end: fake executable through the real subprocess lifecycle --


@pytest.mark.parametrize(
    "adapter_class,expected_flag",
    [(ClaudeCodeAdapter, "-p"), (CodexAdapter, "exec"), (AgyAdapter, "-p")],
)
async def test_adapter_passes_model_and_pins_workspace_cwd(
    tmp_path, fake_cli, adapter_class, expected_flag
):
    workspace = _workspace(tmp_path)
    adapter = adapter_class(
        artifacts=_artifacts(tmp_path), executable=str(fake_cli), model="test-model"
    )

    handle = await adapter.start(_task("do the task"), workspace)
    result = await adapter.result(handle)

    assert result.status is RuntimeStatus.COMPLETED
    assert result.result_data["cwd"] == str(workspace.root)
    assert expected_flag in result.result_data["argv"]
    assert "--model" in result.result_data["argv"]
    assert "test-model" in result.result_data["argv"]
    assert "do the task" in result.result_data["argv"]


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
async def test_adapter_omits_model_flag_when_not_configured(tmp_path, fake_cli, adapter_class):
    adapter = adapter_class(artifacts=_artifacts(tmp_path), executable=str(fake_cli))

    handle = await adapter.start(_task(), _workspace(tmp_path))
    result = await adapter.result(handle)

    assert "--model" not in result.result_data["argv"]


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
async def test_adapter_environment_is_allowlisted_not_inherited(tmp_path, fake_cli, adapter_class):
    fake_source_env = {
        "PATH": "/custom/bin",
        "HOME": "/home/test-user",
        "ANTHROPIC_API_KEY": "sk-ant-should-not-leak-if-unrelated",
        "OPENAI_API_KEY": "sk-should-not-leak-if-unrelated",
        "AGY_API_KEY": "agy-should-not-leak-if-unrelated",
        "UNRELATED_ENV_VAR": "should-never-be-forwarded",
        "AWS_SECRET_ACCESS_KEY": "also-should-never-be-forwarded",
    }
    adapter = adapter_class(
        artifacts=_artifacts(tmp_path), executable=str(fake_cli), env=fake_source_env
    )

    handle = await adapter.start(_task(), _workspace(tmp_path))
    result = await adapter.result(handle)
    child_env = result.result_data["env"]

    assert child_env["PATH"] == "/custom/bin"
    assert child_env["HOME"] == "/home/test-user"
    assert "UNRELATED_ENV_VAR" not in child_env
    assert "AWS_SECRET_ACCESS_KEY" not in child_env


async def test_adapter_environment_defaults_path_when_source_lacks_it(tmp_path, fake_cli):
    adapter = ClaudeCodeAdapter(artifacts=_artifacts(tmp_path), executable=str(fake_cli), env={})

    handle = await adapter.start(_task(), _workspace(tmp_path))
    result = await adapter.result(handle)

    assert result.result_data["env"]["PATH"]


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
async def test_adapters_share_the_same_lifecycle_and_result_boundary(
    tmp_path, fake_cli, adapter_class
):
    adapter = adapter_class(artifacts=_artifacts(tmp_path), executable=str(fake_cli))
    workspace = _workspace(tmp_path)

    handle = await adapter.start(_task("shared boundary check"), workspace)
    events = [event async for event in adapter.events(handle)]
    first = await adapter.result(handle)
    second = await adapter.result(handle)

    assert first is second
    assert first.status is RuntimeStatus.COMPLETED
    assert first.handle.runtime_name == adapter.runtime_name
    assert events[0].event_type.value == "started"
    assert events[-1].event_type.value == "completed"
    assert sum(1 for event in events if event.status is not RuntimeStatus.RUNNING) == 1


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
async def test_steering_is_capability_gated_and_unsupported(tmp_path, fake_cli, adapter_class):
    adapter = adapter_class(artifacts=_artifacts(tmp_path), executable=str(fake_cli))
    handle = await adapter.start(_task(), _workspace(tmp_path))

    with pytest.raises(UnsupportedSteeringError, match="does not support steering"):
        await adapter.steer(handle, "change direction")

    # Confirm the unsupported call above did not disturb normal completion.
    result = await adapter.result(handle)
    assert result.status is RuntimeStatus.COMPLETED


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
async def test_adapter_declares_only_isolated_write_workspace_capability(
    tmp_path, fake_cli, adapter_class
):
    from agentic_os.runtimes.base import WorkspacePolicyError
    from agentic_os.runtimes.contracts import RuntimeCapability

    adapter = adapter_class(artifacts=_artifacts(tmp_path), executable=str(fake_cli))

    assert RuntimeCapability.ISOLATED_WRITE_WORKSPACE in adapter.capabilities.supported
    assert RuntimeCapability.READ_ONLY_WORKSPACE not in adapter.capabilities.supported
    assert RuntimeCapability.STEER not in adapter.capabilities.supported
    assert RuntimeCapability.SESSION_CONTINUATION not in adapter.capabilities.supported

    approved = tmp_path / "ro-approved"
    root = approved / "workspace"
    root.mkdir(parents=True)
    read_only_workspace = Workspace(root=root, approved_root=approved, allow_write=False)

    with pytest.raises(WorkspacePolicyError, match="read_only"):
        await adapter.start(_task(), read_only_workspace)


def test_claude_native_result_envelope_is_normalized(tmp_path):
    adapter = ClaudeCodeAdapter(artifacts=_artifacts(tmp_path), executable="claude")

    parsed = adapter._parse_structured_result(
        b'{"type":"result","subtype":"success","is_error":false,'
        b'"result":"Claude finished","session_id":"session-1"}'
    )

    assert parsed[0] is RuntimeStatus.COMPLETED
    assert parsed[1] == "Claude finished"
    assert parsed[2]["session_id"] == "session-1"


def test_codex_native_jsonl_result_is_normalized(tmp_path):
    adapter = CodexAdapter(artifacts=_artifacts(tmp_path), executable="codex")

    parsed = adapter._parse_structured_result(
        b'{"type":"thread.started","thread_id":"thread-1"}\n'
        b'{"type":"item.completed","item":{"type":"agent_message",'
        b'"text":"Codex finished"}}\n'
    )

    assert parsed[0] is RuntimeStatus.COMPLETED
    assert parsed[1] == "Codex finished"
    assert parsed[2]["session_id"] == "thread-1"


def test_agy_native_result_envelope_is_normalized(tmp_path):
    adapter = AgyAdapter(artifacts=_artifacts(tmp_path), executable="agy")

    parsed = adapter._parse_structured_result(
        b'{"conversation_id":"conversation-1","status":"SUCCESS",'
        b'"response":"agy finished","num_turns":1}'
    )

    assert parsed[0] is RuntimeStatus.COMPLETED
    assert parsed[1] == "agy finished"
    assert parsed[2]["conversation_id"] == "conversation-1"
