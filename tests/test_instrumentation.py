"""Instrumentation/provenance/correction behavior — RED before implementation."""

import pytest
from pydantic import ValidationError

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ContextItem, GoalContract
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.core.trace import TraceService
from agentic_os.core.validation import validate_with_correction


def test_context_item_requires_reconstructable_provenance():
    with pytest.raises(ValidationError):
        ContextItem(summary="Important project context", provenance_type="memory", provenance_id="")

    with pytest.raises(ValidationError):
        ContextItem(
            summary="memory provenance without storage details",
            provenance_type="memory",
            provenance_id="memory_42",
            content_hash="sha256:abc",
        )
    item = ContextItem(
        summary="User requires no golden regressions",
        provenance_type="memory",
        provenance_id="memory_42",
        content_hash="sha256:abc",
        memory_namespace="user/user-1",
        memory_kind="semantic",
        memory_metadata={},
        memory_created_at="2026-09-19T00:00:00Z",
    )
    assert item.provenance_id == "memory_42"


def test_bounded_correction_repairs_invalid_contract_once():
    calls = []

    def correct(error, raw):
        calls.append((error, raw))
        return {
            "objective": "Recovered goal",
            "success_metrics": ["validated"],
        }

    result = validate_with_correction(
        GoalContract,
        {"objective": "missing metrics"},
        correct=correct,
        max_corrections=1,
    )
    assert result.success_metrics == ["validated"]
    assert len(calls) == 1


def test_bounded_correction_stops_after_limit():
    calls = 0

    def still_invalid(error, raw):
        nonlocal calls
        calls += 1
        return raw

    with pytest.raises(ValidationError):
        validate_with_correction(
            GoalContract,
            {"objective": "missing metrics"},
            correct=still_invalid,
            max_corrections=1,
        )
    assert calls == 1


def test_component_tracer_emits_start_and_completed(tmp_path):
    store = EventStore(tmp_path / "events.db")
    tracer = ComponentTracer(store)
    with tracer.span(
        trace_id="trace_1",
        goal_id="goal_1",
        run_id="run_1",
        component_kind="worker",
        component_name="research",
        operation="worker.run",
    ):
        pass

    events = store.query(trace_id="trace_1")
    assert [event.event_type for event in events] == [
        "component.call.started",
        "component.call.completed",
    ]
    assert events[0].span_id == events[1].span_id


def test_component_tracer_emits_failed_terminal_on_exception(tmp_path):
    store = EventStore(tmp_path / "events.db")
    tracer = ComponentTracer(store)
    with pytest.raises(RuntimeError, match="prototype failed"):
        with tracer.span(
            trace_id="trace_1",
            goal_id="goal_1",
            run_id="run_1",
            component_kind="worker",
            component_name="coding",
            operation="worker.run",
        ):
            raise RuntimeError("prototype failed")

    events = store.query(trace_id="trace_1")
    assert events[-1].event_type == "component.call.failed"
    assert events[-1].status == "failed"
    assert events[-1].error == {"type": "RuntimeError", "message": "prototype failed"}
    assert store.verify_trace("trace_1").ok


def test_failed_component_preserves_partial_artifact_for_recorded_replay(tmp_path):
    store = EventStore(tmp_path / "events.db")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    partial = artifacts.put(b"partial failed output", "text/plain")
    tracer = ComponentTracer(store)

    with pytest.raises(RuntimeError):
        with tracer.span(
            trace_id="trace_1",
            goal_id="goal_1",
            run_id="run_1",
            component_kind="worker",
            component_name="coding",
            operation="worker.run",
        ) as span:
            span.set_output(partial)
            raise RuntimeError("failed after artifact")

    replay = TraceService(store, artifacts).replay_recorded("trace_1", span.span_id)
    assert replay.content == b"partial failed output"
    assert replay.live_calls == 0
