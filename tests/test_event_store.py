"""Append-only event/artifact store tests — RED before implementation."""

import sqlite3

import pytest

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind, RunEvent
from agentic_os.core.events import EventStore, TraceIntegrityError


def event(kind: str, span: str, *, parent: str | None = None, status: str | None = None):
    suffix = kind.rsplit(".", 1)[-1]
    default_status = {
        "started": "running",
        "completed": "ok",
        "failed": "failed",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
    }[suffix]
    return RunEvent(
        event_type=kind,
        trace_id="trace_1",
        span_id=span,
        parent_span_id=parent,
        goal_id="goal_1",
        run_id="run_1",
        task_id="task_1",
        component_kind=ComponentKind.WORKER,
        component_name="coding",
        operation="worker.run",
        status=status or default_status,
    )


def test_event_store_appends_and_filters_in_order(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.append(event("component.call.started", "span_parent"))
    store.append(event("component.call.started", "span_child", parent="span_parent"))
    store.append(event("component.call.completed", "span_child", parent="span_parent"))
    store.append(event("component.call.completed", "span_parent"))

    events = store.query(trace_id="trace_1", component_name="coding")
    assert [e.event_type for e in events] == [
        "component.call.started",
        "component.call.started",
        "component.call.completed",
        "component.call.completed",
    ]
    assert store.query(status="failed") == []


def test_event_store_rejects_duplicate_event_id(tmp_path):
    store = EventStore(tmp_path / "events.db")
    item = event("component.call.started", "span_1")
    store.append(item)
    with pytest.raises(sqlite3.IntegrityError):
        store.append(item)


def test_integrity_accepts_complete_parent_child_trace(tmp_path):
    store = EventStore(tmp_path / "events.db")
    for item in [
        event("component.call.started", "parent"),
        event("component.call.started", "child", parent="parent"),
        event("component.call.completed", "child", parent="parent"),
        event("component.call.completed", "parent"),
    ]:
        store.append(item)
    report = store.verify_trace("trace_1")
    assert report.ok
    assert report.span_count == 2


def test_integrity_rejects_missing_terminal_and_broken_parent(tmp_path):
    store = EventStore(tmp_path / "events.db")
    store.append(event("component.call.started", "orphan", parent="missing"))
    with pytest.raises(TraceIntegrityError) as exc:
        store.verify_trace("trace_1")
    assert "missing terminal" in str(exc.value)
    assert "unknown parent" in str(exc.value)


def test_integrity_rejects_secret_like_event_payload(tmp_path):
    store = EventStore(tmp_path / "events.db")
    started = event("component.call.started", "span_1")
    # Set secret before append so redaction happens
    started.error = {"debug": "ANTHROPIC_API_KEY=sk-ant-secret123"}
    store.append(started)
    store.append(event("component.call.completed", "span_1"))
    with pytest.raises(TraceIntegrityError, match="secret-like"):
        store.verify_trace("trace_1")


def test_artifact_store_roundtrip_and_deduplicates(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.put(b"same bytes", media_type="text/plain")
    second = store.put(b"same bytes", media_type="text/plain")

    assert first.uri == second.uri
    assert store.get(first) == b"same bytes"
    assert len(list((tmp_path / "artifacts").rglob("*.blob"))) == 1


def test_artifact_store_detects_corruption(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put(b"original", media_type="text/plain")
    path = store.path_for(ref)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.get(ref)
