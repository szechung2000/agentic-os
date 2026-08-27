"""Trace querying, interaction-tree projection, integrity, and recorded replay."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ArtifactRef, RunEvent
from agentic_os.core.events import EventStore, TraceIntegrityReport


@dataclass
class TraceNode:
    span_id: str
    parent_span_id: str | None
    component_kind: str
    component_name: str
    operation: str
    status: str
    children: list[TraceNode] = field(default_factory=list)


@dataclass(frozen=True)
class RecordedReplay:
    trace_id: str
    span_id: str
    ref: ArtifactRef
    content: bytes
    live_calls: int = 0


class TraceService:
    def __init__(self, events: EventStore, artifacts: ArtifactStore) -> None:
        self.events = events
        self.artifacts = artifacts

    def filter(
        self,
        trace_id: str,
        *,
        component_name: str | None = None,
        status: str | None = None,
        task_id: str | None = None,
    ) -> list[RunEvent]:
        return self.events.query(
            trace_id=trace_id,
            component_name=component_name,
            status=status,
            task_id=task_id,
        )

    def verify(self, trace_id: str) -> TraceIntegrityReport:
        return self.events.verify_trace(trace_id)

    def tree(self, trace_id: str) -> list[TraceNode]:
        events = self.events.query(trace_id=trace_id)
        nodes: dict[str, TraceNode] = {}
        order: list[str] = []
        for event in events:
            if not event.event_type.startswith("component.call."):
                continue
            if event.span_id not in nodes:
                nodes[event.span_id] = TraceNode(
                    span_id=event.span_id,
                    parent_span_id=event.parent_span_id,
                    component_kind=event.component_kind.value,
                    component_name=event.component_name,
                    operation=event.operation,
                    status=event.status,
                )
                order.append(event.span_id)
            else:
                nodes[event.span_id].status = event.status

        roots: list[TraceNode] = []
        for span_id in order:
            node = nodes[span_id]
            if node.parent_span_id and node.parent_span_id in nodes:
                nodes[node.parent_span_id].children.append(node)
            else:
                roots.append(node)
        return roots

    def replay_recorded(self, trace_id: str, span_id: str) -> RecordedReplay:
        events = self.events.query(trace_id=trace_id)
        terminal = next(
            (
                event
                for event in reversed(events)
                if event.span_id == span_id
                and event.event_type
                in {
                    "component.call.completed",
                    "component.call.failed",
                    "component.call.cancelled",
                    "component.call.timed_out",
                }
            ),
            None,
        )
        if terminal is None:
            raise KeyError(f"no terminal event for span: {span_id}")
        if terminal.output_ref is None:
            raise KeyError(f"span has no recorded output artifact: {span_id}")
        return RecordedReplay(
            trace_id=trace_id,
            span_id=span_id,
            ref=terminal.output_ref,
            content=self.artifacts.get(terminal.output_ref),
        )
