"""Regression coverage for runtime-ready durable lifecycle boundaries."""

import pytest

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.core.trace import TraceService
from agentic_os.workers.base import CancellationError, EchoWorker, TimeoutError


@pytest.mark.parametrize(
    ("error", "event_type", "status"),
    [
        (CancellationError("operator cancelled"), "component.call.cancelled", "cancelled"),
        (TimeoutError("runtime timed out"), "component.call.timed_out", "timed_out"),
    ],
)
def test_component_tracer_emits_one_explicit_terminal_for_runtime_stops(
    tmp_path, error, event_type, status
):
    events = EventStore(tmp_path / "events.db")
    tracer = ComponentTracer(events)

    with pytest.raises(type(error)):
        with tracer.span(
            trace_id="trace_runtime",
            goal_id="goal_1",
            run_id="run_1",
            component_kind=ComponentKind.RUNTIME,
            component_name="fake-runtime",
            operation="runtime.execute",
        ):
            raise error

    span_events = events.query(trace_id="trace_runtime")
    terminals = [event for event in span_events if event.event_type != "component.call.started"]
    assert [(event.event_type, event.status) for event in terminals] == [(event_type, status)]
    assert events.verify_trace("trace_runtime").ok


def test_component_tracer_can_mark_a_non_exception_terminal_status(tmp_path):
    events = EventStore(tmp_path / "events.db")
    tracer = ComponentTracer(events)

    with tracer.span(
        trace_id="trace_runtime",
        goal_id="goal_1",
        run_id="run_1",
        component_kind=ComponentKind.RUNTIME,
        component_name="fake-runtime",
        operation="runtime.execute",
    ) as span:
        span.mark_timed_out("runtime exceeded its deadline")

    terminal = events.query(trace_id="trace_runtime")[-1]
    assert terminal.event_type == "component.call.timed_out"
    assert terminal.error == {"type": "TimeoutError", "message": "runtime exceeded its deadline"}


def test_runtime_artifacts_are_durable_and_redacted_before_persistence(tmp_path):
    events = EventStore(tmp_path / "events.db")
    artifacts = ArtifactStore(tmp_path / "durable-artifacts")
    tracer = ComponentTracer(events, artifacts=artifacts)

    with tracer.span(
        trace_id="trace_runtime",
        goal_id="goal_1",
        run_id="run_1",
        component_kind=ComponentKind.RUNTIME,
        component_name="fake-runtime",
        operation="runtime.execute",
        data={"command": "fake --token=runtime-secret-123"},
    ) as span:
        output = span.record_output(
            b'{"stdout":"ok","API_KEY":"runtime-secret-123"}', media_type="application/json"
        )

    terminal = events.query(trace_id="trace_runtime")[-1]
    assert terminal.output_ref == output
    assert b"runtime-secret-123" not in artifacts.get(output)
    assert b"[REDACTED]" in artifacts.get(output)
    assert "runtime-secret-123" not in terminal.model_dump_json()
    assert TraceService(events, artifacts).replay_recorded("trace_runtime", span.span_id).content


def test_artifact_store_rejects_path_traversal_refs(tmp_path):
    artifacts = ArtifactStore(tmp_path / "durable-artifacts")
    ref = artifacts.put(b"safe", "text/plain")
    ref.content_hash = "sha256:../../outside"

    with pytest.raises(ValueError, match="invalid artifact content hash"):
        artifacts.path_for(ref)


async def test_worker_uses_the_tracers_caller_provided_durable_artifact_store(tmp_path):
    events = EventStore(tmp_path / "events.db")
    artifacts = ArtifactStore(tmp_path / "durable-artifacts")
    tracer = ComponentTracer(events, artifacts=artifacts)

    result = await EchoWorker(tracer=tracer).run({"content": "durable worker output"})

    terminal = events.query(trace_id="unknown")[-1]
    assert result.ok
    assert terminal.output_ref is not None
    assert artifacts.get(terminal.output_ref) == b"echo: durable worker output"
