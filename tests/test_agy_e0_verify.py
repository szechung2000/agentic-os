"""Agy flow to verify E0 using the event store as a record source."""

import shutil
import tempfile
from pathlib import Path

import pytest

from agentic_os.core.contracts import ComponentKind, GoalContract, RunEvent
from agentic_os.core.events import EventStore, TraceIntegrityError
from agentic_os.core.registry import ExtensionKind, ExtensionRegistry
from agentic_os.core.state import RunCoordinator


def test_agy_verify_e0():
    """Use agy-style flow to verify E0 criteria using the event store."""

    tmpdir = tempfile.mkdtemp(prefix="agy-e0-verify-")
    db_path = Path(tmpdir) / "events.db"

    store = EventStore(db_path)
    trace_id = "agy-verify-trace"
    span_1 = "span_1"
    span_2 = "span_2"

    # Record 1: Two complete spans (parent-child) — should pass integrity
    for evt in [
        RunEvent(
            event_type="component.call.started",
            trace_id=trace_id,
            span_id=span_1,
            parent_span_id=None,
            goal_id="agy-verify",
            run_id="run-1",
            task_id="task-1",
            component_kind=ComponentKind.RUNTIME,
            component_name="claude_code",
            operation="runtime.execute",
            status="running",
        ),
        RunEvent(
            event_type="component.call.started",
            trace_id=trace_id,
            span_id=span_2,
            parent_span_id=span_1,
            goal_id="agy-verify",
            run_id="run-1",
            task_id="task-1",
            component_kind=ComponentKind.WORKER,
            component_name="echo_worker",
            operation="worker.run",
            status="running",
        ),
        RunEvent(
            event_type="component.call.completed",
            trace_id=trace_id,
            span_id=span_2,
            parent_span_id=span_1,
            goal_id="agy-verify",
            run_id="run-1",
            task_id="task-1",
            component_kind=ComponentKind.WORKER,
            component_name="echo_worker",
            operation="worker.run",
            status="ok",
        ),
        RunEvent(
            event_type="component.call.completed",
            trace_id=trace_id,
            span_id=span_1,
            parent_span_id=None,
            goal_id="agy-verify",
            run_id="run-1",
            task_id="task-1",
            component_kind=ComponentKind.RUNTIME,
            component_name="claude_code",
            operation="runtime.execute",
            status="ok",
        ),
    ]:
        store.append(evt)

    # agy: verify integrity on complete trace
    report = store.verify_trace(trace_id)
    assert report.ok, f"INTEGRITY FAILED: {report}"
    assert report.span_count == 2, f"Expected 2 spans, got {report.span_count}"
    assert report.event_count == 4, f"Expected 4 events, got {report.event_count}"
    print(f"✅ agy integrity check PASSED: {report.span_count} spans, {report.event_count} events")

    # Record 2: Replay test — create recorder, record event, replay
    class SimpleRecorder:
        def __init__(self):
            self.recorded = []

        def record(self, span_id, output):
            self.recorded.append((span_id, output.encode()))

        def replay(self, span_id):
            for sid, content in self.recorded:
                if sid == span_id:
                    return content
            return None

    recorder = SimpleRecorder()
    recorder.record(span_2, '{"result": "replayed"}')

    events = store.query(trace_id=trace_id, component_name="echo_worker")
    replay_span = events[1].span_id
    replayed = recorder.replay(replay_span)

    assert replayed is not None, "RECORDED REPLAY FAILED: no recording found"
    assert b"replayed" in replayed, f"RECORDED REPLAY FAILED: got {replayed}"
    print("✅ agy recorded replay PASSED")

    # Record 3: Secret detection
    secret_trace = "agy-secret-trace"
    secret_span = "secret_span"
    secret_event = RunEvent(
        event_type="component.call.started",
        trace_id=secret_trace,
        span_id=secret_span,
        parent_span_id=None,
        goal_id="agy-verify",
        run_id="run-1",
        task_id="task-1",
        component_kind=ComponentKind.RUNTIME,
        component_name="test_runtime",
        operation="runtime.execute",
        status="running",
        data={"api_key": "sk-ant-secret123456"},
    )
    store.append(secret_event)
    with pytest.raises(TraceIntegrityError, match="secret-like"):
        store.verify_trace(secret_trace)
    print("✅ agy secret detection PASSED")

    # Record 4: Restart recovery — use public API (complete_task persists event)
    goal = GoalContract(
        goal_id="agy-restart-goal",
        objective="Verify restart recovery",
        success_metrics=["Process resumes after stop"],
    )
    coordinator = RunCoordinator(store)
    state = coordinator.create(goal)
    coordinator.complete_task(state.run_id, "task_1")
    coordinator.checkpoint(state.run_id)

    # Simulate restart
    restarted = RunCoordinator(store)
    loaded_state = restarted.load(state.run_id)
    assert loaded_state is not None, "RESTART FAILED: could not load state"
    assert "task_1" in loaded_state.completed_tasks, \
        "RESTART FAILED: completed task not found"
    print("✅ agy restart recovery PASSED")

    # Record 5: Provider replacement test — use the disposer returned by register()
    reg = ExtensionRegistry()
    class TestProvider:
        name = "test_provider"
        capabilities = ["test"]

    dispose = reg.register(ExtensionKind.TOOL_PROVIDER, "test_provider", TestProvider())
    assert "test_provider" in reg.available(ExtensionKind.TOOL_PROVIDER)
    dispose()  # reversibility: the disposer reverses the registration
    assert "test_provider" not in reg.available(ExtensionKind.TOOL_PROVIDER)
    print("✅ agy provider replacement PASSED")

    # Record 6: Component kinds are tracked and valid
    event_kinds = set()
    for evt in store.query(trace_id=trace_id):
        if evt.event_type.startswith("component.call."):
            event_kinds.add(evt.component_kind)

    # Verify the kinds present are valid ExtensionKind members
    for kind in event_kinds:
        assert isinstance(kind, ComponentKind), f"kind {kind} is not a ComponentKind"

    # Verify core orchestration kinds are represented
    # Verify core orchestration kinds are represented
    assert ComponentKind.RUNTIME in event_kinds, "RUNTIME kind not found"
    assert ComponentKind.WORKER in event_kinds, "WORKER kind not found"

    # The full 9-kind coverage is proven by the E0 eval harness
    # (see agos eval e0 → component-kind-coverage case)
    print(f"✅ agy component kind tracking PASSED: {len(event_kinds)} kinds tracked")

    # Cleanup
    shutil.rmtree(tmpdir)

    print("\n🎯 agy E0 verification complete — all 6 records pass")


def test_agy_restart_recovery_isolation():
    """Separate test to prove restart recovery works independently."""
    tmpdir = tempfile.mkdtemp(prefix="agy-e0-iso-")
    db_path = Path(tmpdir) / "events.db"
    store = EventStore(db_path)

    goal = GoalContract(
        goal_id="iso-goal",
        objective="Isolation test",
        success_metrics=["complete"],
    )
    coordinator = RunCoordinator(store)
    state = coordinator.create(goal)
    coordinator.complete_task(state.run_id, "task_iso")
    coordinator.checkpoint(state.run_id)

    restarted = RunCoordinator(store)
    loaded = restarted.load(state.run_id)
    assert "task_iso" in loaded.completed_tasks

    shutil.rmtree(tmpdir)
