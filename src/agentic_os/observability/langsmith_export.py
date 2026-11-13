"""Opt-in LangSmith projection of verified local component spans.

No free-form prompts, CLI streams, source code, or artifact contents are exported.
The SQLite event log remains the only authoritative history. This module has no
side effects until export_trace is explicitly called.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from agentic_os.core.events import EventStore


@dataclass(frozen=True)
class SafeSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    run_id: str
    task_id: str | None
    component_kind: str
    component_name: str
    operation: str
    status: str
    output_hash: str | None
    event_counts: dict[str, int] = field(default_factory=dict)


def project_spans(store: EventStore, trace_id: str) -> list[SafeSpan]:
    """Build an allowlisted projection; never return arbitrary event payloads."""
    store.verify_trace(trace_id)
    events = store.query(trace_id=trace_id)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    terminal = {}
    for event in events:
        if event.event_type.startswith("runtime."):
            counts[event.span_id][event.event_type] += 1
        if event.event_type.startswith("component.call.") and event.event_type != (
            "component.call.started"
        ):
            terminal[event.span_id] = event
    spans = []
    for start in events:
        if start.event_type != "component.call.started":
            continue
        end = terminal[start.span_id]
        spans.append(
            SafeSpan(
                trace_id=start.trace_id,
                span_id=start.span_id,
                parent_span_id=start.parent_span_id,
                run_id=start.run_id,
                task_id=start.task_id,
                component_kind=start.component_kind.value,
                component_name=start.component_name,
                operation=start.operation,
                status=end.status,
                output_hash=end.output_ref.content_hash if end.output_ref else None,
                event_counts=dict(counts[start.span_id]),
            )
        )
    return spans


def export_trace(
    store: EventStore,
    trace_id: str,
    *,
    project_name: str = "agentic-os",
    confirm_upload: bool = False,
) -> int:
    """Export only after explicit approval. Never mutate local run state."""
    if not confirm_upload:
        raise PermissionError("LangSmith export requires explicit upload confirmation")
    try:
        from langsmith.run_trees import RunTree
    except ImportError as error:
        raise ImportError("install the optional langsmith package first") from error

    spans = project_spans(store, trace_id)
    if not spans:
        return 0

    root = RunTree(
        name="agentic-os.run",
        run_type="chain",
        project_name=project_name,
        inputs={"trace_id": trace_id, "run_id": spans[0].run_id},
    )
    root.post()
    remote_spans = {}
    for span in spans:
        parent = remote_spans.get(span.parent_span_id, root)
        child = parent.create_child(
            name=f"{span.component_kind}.{span.component_name}",
            run_type="tool",
            inputs={
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "task_id": span.task_id,
            },
            metadata={
                "operation": span.operation,
                "run_id": span.run_id,
                "event_counts": span.event_counts,
            },
        )
        child.post()
        remote_spans[span.span_id] = child

    for span in reversed(spans):
        child = remote_spans[span.span_id]
        child.end(
            outputs={
                "status": span.status,
                "output_hash": span.output_hash,
            }
        )
        child.patch()
    root.end(outputs={"component_spans": len(spans)})
    root.patch()
    root.wait()
    return len(spans)
