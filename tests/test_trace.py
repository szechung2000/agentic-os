"""Trace rendering and recorded replay tests — RED before implementation."""

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind, RunEvent
from agentic_os.core.events import EventStore
from agentic_os.core.trace import TraceService


def call(event_type, span, status, *, parent=None, output_ref=None, component="supervisor"):
    return RunEvent(
        event_type=event_type,
        trace_id="trace_1",
        span_id=span,
        parent_span_id=parent,
        goal_id="goal_1",
        run_id="run_1",
        task_id="task_1",
        component_kind=ComponentKind(component),
        component_name=f"{component}-component",
        operation=f"{component}.run",
        status=status,
        output_ref=output_ref,
    )


def build_trace(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    events = EventStore(tmp_path / "events.db")
    output = artifacts.put(b'{"finding":"recorded result"}', "application/json")
    for item in [
        call("component.call.started", "supervisor", "running"),
        call(
            "component.call.started",
            "worker",
            "running",
            parent="supervisor",
            component="worker",
        ),
        call(
            "component.call.completed",
            "worker",
            "ok",
            parent="supervisor",
            output_ref=output,
            component="worker",
        ),
        call("component.call.completed", "supervisor", "ok"),
    ]:
        events.append(item)
    return TraceService(events, artifacts), output


def test_trace_tree_exposes_parent_child_interactions(tmp_path):
    service, _ = build_trace(tmp_path)
    tree = service.tree("trace_1")
    assert [node.span_id for node in tree] == ["supervisor"]
    assert [node.span_id for node in tree[0].children] == ["worker"]
    assert tree[0].children[0].component_kind == "worker"
    assert tree[0].children[0].status == "ok"


def test_recorded_replay_returns_verified_terminal_artifact(tmp_path):
    service, ref = build_trace(tmp_path)
    replay = service.replay_recorded("trace_1", "worker")
    assert replay.ref.content_hash == ref.content_hash
    assert replay.content == b'{"finding":"recorded result"}'
    assert replay.live_calls == 0


def test_trace_filter_returns_component_events(tmp_path):
    service, _ = build_trace(tmp_path)
    events = service.filter("trace_1", component_name="worker-component")
    assert len(events) == 2
    assert {event.status for event in events} == {"running", "ok"}


def test_trace_integrity_report_is_available(tmp_path):
    service, _ = build_trace(tmp_path)
    report = service.verify("trace_1")
    assert report.ok
    assert report.span_count == 2
