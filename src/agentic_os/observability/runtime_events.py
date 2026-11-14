"""Persist normalized, privacy-limited runtime event envelopes.

The authoritative event log does not duplicate raw provider output. Outputs stay
in content-addressed artifacts, and cloud exporters only read a metadata projection.
"""

from __future__ import annotations

from agentic_os.core.contracts import ComponentKind, RunEvent
from agentic_os.core.events import EventStore
from agentic_os.core.redaction import redact_text
from agentic_os.runtimes.contracts import RuntimeEvent, RuntimeEventType, RuntimeStatus

_SAFE_SUMMARIES = frozenset(
    {
        RuntimeEventType.STARTED,
        RuntimeEventType.PROGRESS,
        RuntimeEventType.COMPLETED,
        RuntimeEventType.FAILED,
        RuntimeEventType.CANCELLED,
        RuntimeEventType.TIMED_OUT,
    }
)


def record_runtime_event(
    store: EventStore,
    *,
    event: RuntimeEvent,
    trace_id: str,
    goal_id: str,
    run_id: str,
    span_id: str,
    task_id: str,
    worker_id: str,
    runtime_name: str,
) -> int:
    """Write a provider-neutral event linked to its enclosing component span."""
    status = {
        RuntimeStatus.RUNNING: "running",
        RuntimeStatus.COMPLETED: "ok",
        RuntimeStatus.FAILED: "failed",
        RuntimeStatus.CANCELLED: "cancelled",
        RuntimeStatus.TIMED_OUT: "timed_out",
        RuntimeStatus.UNAVAILABLE: "failed",
    }[event.status]
    data = {
        "handle_id": event.handle_id,
        "kind": event.event_type.value,
    }
    if event.event_type in _SAFE_SUMMARIES and event.summary:
        # Redact before truncating so truncation cannot leave a partial credential.
        data["summary"] = redact_text(event.summary)[:240]
    if event.event_type in {RuntimeEventType.STDOUT, RuntimeEventType.STDERR}:
        data["captured_characters"] = len(event.summary or "")
    return store.append(
        RunEvent(
            event_type=f"runtime.{event.event_type.value}",
            status=status,
            trace_id=trace_id,
            span_id=span_id,
            goal_id=goal_id,
            run_id=run_id,
            task_id=task_id,
            worker_id=worker_id,
            component_kind=ComponentKind.RUNTIME,
            component_name=runtime_name,
            operation="runtime.stream",
            output_ref=event.artifact_ref,
            data=data,
        )
    )
