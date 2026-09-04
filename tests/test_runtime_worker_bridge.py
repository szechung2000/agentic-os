"""Compatibility and trace tests for the typed runtime worker bridge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.runtimes.contracts import (
    RuntimeDiagnostic,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeStatus,
    Workspace,
)
from agentic_os.runtimes.worker_bridge import RuntimeWorkerBridge


@dataclass
class FakeRuntime:
    runtime_name: str
    execution_result: RuntimeExecutionResult

    async def start(self, task, workspace):
        del task, workspace
        return self.execution_result.handle

    async def result(self, handle):
        assert handle.handle_id == self.execution_result.handle.handle_id
        return self.execution_result

    async def events(self, handle):
        del handle
        if False:
            yield

    async def steer(self, handle, message):
        del handle, message
        raise NotImplementedError

    async def stop(self, handle):
        return await self.result(handle)


def _workspace(tmp_path: Path) -> Workspace:
    approved = tmp_path / "approved"
    root = approved / "workspace"
    root.mkdir(parents=True)
    return Workspace(root=root, approved_root=approved, allow_write=True)


def _result(
    tmp_path: Path,
    *,
    status: RuntimeStatus = RuntimeStatus.COMPLETED,
) -> RuntimeExecutionResult:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    output = artifacts.put(b"runtime output", "text/plain")
    diagnostics = ()
    if status is not RuntimeStatus.COMPLETED:
        diagnostics = (
            RuntimeDiagnostic(
                code=status.value,
                message=f"runtime {status.value}",
                artifact_ref=output,
            ),
        )
    return RuntimeExecutionResult(
        handle=RuntimeHandle(runtime_name="fake", workspace_id="workspace-test"),
        status=status,
        summary="runtime summary",
        output_ref=output,
        artifacts=(output,),
        diagnostics=diagnostics,
    )


async def test_bridge_preserves_legacy_supervisor_boundary_and_runtime_trace(tmp_path):
    result = _result(tmp_path)
    runtime = FakeRuntime("fake", result)
    event_store = EventStore(tmp_path / "events.db")
    artifact_store = ArtifactStore(tmp_path / "trace-artifacts")
    bridge = RuntimeWorkerBridge(
        runtime,
        _workspace(tmp_path),
        tracer=ComponentTracer(event_store, artifact_store),
        artifacts=artifact_store,
    )

    legacy = await bridge.run(
        {
            "task_id": "task-1",
            "goal_id": "goal-1",
            "objective": "perform the fixture task",
            "trace_id": "trace-1",
            "run_id": "run-1",
        }
    )

    assert legacy.worker == "runtime"
    assert legacy.ok
    assert legacy.output == "runtime summary"
    assert legacy.details["worker_result"]["status"] == "completed"
    events = event_store.query(trace_id="trace-1")
    assert [event.event_type for event in events] == [
        "component.call.started",
        "component.call.completed",
    ]
    assert events[-1].component_name == "fake"
    assert events[-1].output_ref is not None
    assert events[-1].data["runtime_trace"]["selected_runtime"] == "fake"


@pytest.mark.parametrize(
    ("status", "expected_ok", "expected_worker_status"),
    [
        (RuntimeStatus.CANCELLED, False, "cancelled"),
        (RuntimeStatus.TIMED_OUT, False, "timed_out"),
    ],
)
async def test_bridge_maps_non_success_runtime_statuses(
    tmp_path, status, expected_ok, expected_worker_status
):
    result = _result(tmp_path, status=status)
    bridge = RuntimeWorkerBridge(FakeRuntime("fake", result), _workspace(tmp_path))

    legacy = await bridge.run({"objective": "fixture"})

    assert legacy.ok is expected_ok
    assert legacy.details["worker_result"]["status"] == expected_worker_status
    assert legacy.details["worker_result"]["failures"]


async def test_bridge_rejects_empty_objective_before_start(tmp_path):
    result = _result(tmp_path)
    runtime = FakeRuntime("fake", result)
    bridge = RuntimeWorkerBridge(runtime, _workspace(tmp_path))

    with pytest.raises(ValueError, match="non-empty objective"):
        await bridge.run({"objective": ""})
