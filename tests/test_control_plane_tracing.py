"""Offline acceptance tests for subscription-agent event capture and export policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.cli import main
from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind, RunEvent
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.observability.langsmith_export import project_spans
from agentic_os.runtimes.contracts import (
    RuntimeEvent,
    RuntimeEventType,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeStatus,
    Workspace,
)
from agentic_os.runtimes.worker_bridge import RuntimeWorkerBridge


class StreamingFixture:
    runtime_name = "fake-codex"

    def __init__(self, result: RuntimeExecutionResult):
        self._result = result

    async def start(self, task, workspace):
        del task, workspace
        return self._result.handle

    async def events(self, handle):
        assert handle.handle_id == self._result.handle.handle_id
        yield RuntimeEvent(
            handle_id=handle.handle_id,
            event_type=RuntimeEventType.STARTED,
            status=RuntimeStatus.RUNNING,
            summary="CLI started",
        )
        yield RuntimeEvent(
            handle_id=handle.handle_id,
            event_type=RuntimeEventType.STDOUT,
            status=RuntimeStatus.RUNNING,
            summary="auth_token=supersecret123 private source code",
        )
        yield RuntimeEvent(
            handle_id=handle.handle_id,
            event_type=RuntimeEventType.COMPLETED,
            status=RuntimeStatus.COMPLETED,
            summary="finished",
        )

    async def result(self, handle):
        assert handle.handle_id == self._result.handle.handle_id
        return self._result

    async def stop(self, handle):
        return await self.result(handle)


def _workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "workspace"
    root.mkdir()
    return Workspace(root=root, allow_write=False)


async def test_runtime_events_are_correlated_without_stdout_leak(tmp_path):
    events = EventStore(tmp_path / "events.db")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    result = RuntimeExecutionResult(
        handle=RuntimeHandle(runtime_name="fake-codex", workspace_id="workspace-fixture"),
        status=RuntimeStatus.COMPLETED,
        summary="done",
    )
    bridge = RuntimeWorkerBridge(
        StreamingFixture(result),
        _workspace(tmp_path),
        tracer=ComponentTracer(events, artifacts),
        artifacts=artifacts,
    )
    outcome = await bridge.run(
        {
            "objective": "implement safely",
            "trace_id": "trace-one",
            "goal_id": "goal-one",
            "run_id": "run-one",
            "task_id": "task-one",
        }
    )
    assert outcome.ok
    records = events.query(trace_id="trace-one")
    assert [record.event_type for record in records] == [
        "component.call.started",
        "runtime.started",
        "runtime.stdout",
        "runtime.completed",
        "component.call.completed",
    ]
    assert all(record.task_id == "task-one" for record in records)
    assert len({record.span_id for record in records}) == 1
    assert events.verify_trace("trace-one").ok
    assert records[2].data == {
        "handle_id": result.handle.handle_id,
        "kind": "stdout",
        "captured_characters": len("auth_token=supersecret123 private source code"),
    }
    assert "supersecret123" not in "\n".join(record.model_dump_json() for record in records)
    spans = project_spans(events, "trace-one")
    assert len(spans) == 1
    assert spans[0].event_counts == {
        "runtime.started": 1,
        "runtime.stdout": 1,
        "runtime.completed": 1,
    }
    assert "private source code" not in repr(spans)


def test_projection_never_exports_arbitrary_payloads(tmp_path):
    store = EventStore(tmp_path / "events.db")
    shared = {
        "trace_id": "trace-two",
        "span_id": "span-a",
        "goal_id": "goal-a",
        "run_id": "run-a",
        "component_kind": ComponentKind.SUPERVISOR,
        "component_name": "planner",
        "operation": "plan",
        "task_id": "task-a",
        "data": {"prompt": "confidential business requirement"},
    }
    store.append(RunEvent(event_type="component.call.started", status="running", **shared))
    store.append(RunEvent(event_type="component.call.completed", status="ok", **shared))
    spans = project_spans(store, "trace-two")
    assert len(spans) == 1
    assert spans[0].component_name == "planner"
    assert "confidential" not in repr(spans)
    assert "prompt" not in repr(spans)


def test_cloud_export_requires_explicit_confirmation(tmp_path, capsys):
    db = tmp_path / "events.db"
    store = EventStore(db)
    common = {
        "trace_id": "trace-locked",
        "span_id": "span-locked",
        "goal_id": "goal-locked",
        "run_id": "run-locked",
        "component_kind": ComponentKind.WORKER,
        "component_name": "worker",
        "operation": "task",
    }
    store.append(RunEvent(event_type="component.call.started", status="running", **common))
    store.append(RunEvent(event_type="component.call.completed", status="ok", **common))
    assert main(["trace", "export-langsmith", "trace-locked", "--db", str(db)]) == 2
    assert "--confirm-upload" in capsys.readouterr().err
    assert len(store.query(trace_id="trace-locked")) == 2
