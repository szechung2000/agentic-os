"""SQLite append-only run-event store and trace integrity checks."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ArtifactRef, ComponentKind, RunEvent
from agentic_os.core.redaction import SECRET_PATTERNS, redact_text, redact_value

_TERMINAL_TYPES = {
    "component.call.completed",
    "component.call.failed",
    "component.call.cancelled",
    "component.call.timed_out",
}
_SECRET_PATTERNS = SECRET_PATTERNS


class TraceIntegrityError(ValueError):
    pass


class ComponentCancelledError(Exception):
    """A component stopped before it could produce a normal result."""


class ComponentTimedOutError(TimeoutError):
    """A component exceeded its caller-enforced execution deadline."""


@dataclass(frozen=True)
class TraceIntegrityReport:
    trace_id: str
    event_count: int
    span_count: int
    ok: bool = True


@dataclass
class SpanHandle:
    span_id: str
    output_ref: ArtifactRef | None = None
    metrics: dict[str, float | int | None] | None = None
    artifacts: ArtifactStore | None = None
    terminal_status: str | None = None
    terminal_error: dict[str, str] | None = None

    def set_output(self, ref: ArtifactRef) -> None:
        self.output_ref = ref

    def record_output(self, content: bytes, *, media_type: str) -> ArtifactRef:
        """Persist output through the caller-provided durable artifact store."""
        if self.artifacts is None:
            raise RuntimeError("ComponentTracer requires an ArtifactStore to record output")
        ref = self.artifacts.put(content, media_type)
        self.set_output(ref)
        return ref

    def mark_cancelled(self, message: str = "component cancelled") -> None:
        self.terminal_status = "cancelled"
        self.terminal_error = {"type": "CancellationError", "message": redact_text(message)}

    def mark_timed_out(self, message: str = "component timed out") -> None:
        self.terminal_status = "timed_out"
        self.terminal_error = {"type": "TimeoutError", "message": redact_text(message)}


class ComponentTracer:
    """Guarantees one start and one terminal event around a component call."""

    def __init__(self, store: EventStore, artifacts: ArtifactStore | None = None) -> None:
        self.store = store
        self.artifacts = artifacts

    @contextmanager
    def span(
        self,
        *,
        trace_id: str,
        goal_id: str,
        run_id: str,
        component_kind: ComponentKind | str,
        component_name: str,
        operation: str,
        parent_span_id: str | None = None,
        task_id: str | None = None,
        actor_id: str | None = None,
        recipient_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Iterator[SpanHandle]:
        span_id = f"span_{uuid4().hex}"
        kind = ComponentKind(component_kind)
        common = dict(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            goal_id=goal_id,
            run_id=run_id,
            task_id=task_id,
            component_kind=kind,
            component_name=component_name,
            operation=operation,
            actor_id=actor_id,
            recipient_id=recipient_id,
            data=data or {},
        )
        self.store.append(
            RunEvent(event_type="component.call.started", status="running", **common)
        )
        handle = SpanHandle(span_id=span_id, artifacts=self.artifacts)
        started = time.perf_counter()
        try:
            yield handle
        except BaseException as error:
            self._append_terminal(handle, common, started, error=error)
            raise
        else:
            self._append_terminal(handle, common, started)

    def _append_terminal(
        self,
        handle: SpanHandle,
        common: dict[str, Any],
        started: float,
        *,
        error: BaseException | None = None,
    ) -> None:
        elapsed = (time.perf_counter() - started) * 1000
        metrics = dict(handle.metrics or {})
        metrics.setdefault("latency_ms", round(elapsed, 3))
        status = handle.terminal_status
        terminal_error = handle.terminal_error
        if error is not None:
            if (
                isinstance(error, ComponentCancelledError)
                or type(error).__name__ == "CancellationError"
            ):
                status = "cancelled"
                terminal_error = {"type": "CancellationError", "message": redact_text(str(error))}
            elif isinstance(error, (TimeoutError, ComponentTimedOutError)):
                status = "timed_out"
                terminal_error = {"type": "TimeoutError", "message": redact_text(str(error))}
            else:
                status = "failed"
                terminal_error = {"type": type(error).__name__, "message": redact_text(str(error))}
        if status is None:
            status = "ok"
        event_type = {
            "ok": "component.call.completed",
            "failed": "component.call.failed",
            "cancelled": "component.call.cancelled",
            "timed_out": "component.call.timed_out",
        }[status]
        self.store.append(
            RunEvent(
                event_type=event_type,
                status=status,
                output_ref=handle.output_ref,
                metrics=metrics,
                error=terminal_error,
                **common,
            )
        )


def _redact_dict(obj: Any) -> Any:
    """Recursively redact secrets from dicts, lists, and strings."""
    return redact_value(obj)


def _redact_text(text: str) -> str:
    return redact_text(text)


class EventStore:
    """Append-only event persistence; intentionally exposes no update/delete API."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    event_type TEXT NOT NULL,
                    component_kind TEXT NOT NULL,
                    component_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_trace_seq ON run_events(trace_id, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_run_seq ON run_events(run_id, seq)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    event_seq INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def append(self, event: RunEvent) -> int:
            event = event.model_copy(
                update={
                    "data": _redact_dict(event.data),
                    "error": _redact_dict(event.error),
                    "source_urls": _redact_dict(event.source_urls),
                }
            )
            payload = event.model_dump_json()
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO run_events (
                        event_id, trace_id, run_id, span_id, parent_span_id,
                        event_type, component_kind, component_name, status,
                        occurred_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.trace_id,
                        event.run_id,
                        event.span_id,
                        event.parent_span_id,
                        event.event_type,
                        event.component_kind.value,
                        event.component_name,
                        event.status,
                        event.occurred_at.isoformat(),
                        payload,
                    ),
                )
            return int(cursor.lastrowid)

    def query(
        self,
        *,
        trace_id: str | None = None,
        run_id: str | None = None,
        component_name: str | None = None,
        status: str | None = None,
        task_id: str | None = None,
        after_seq: int = 0,
    ) -> list[RunEvent]:
        clauses: list[str] = ["seq > ?"]
        params: list[str | int] = [after_seq]
        for column, value in (
            ("trace_id", trace_id),
            ("run_id", run_id),
            ("component_name", component_name),
            ("status", status),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        sql = "SELECT payload_json FROM run_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq"
        with self._connect() as conn:
            events = [RunEvent.model_validate_json(row[0]) for row in conn.execute(sql, params)]
        if task_id is not None:
            events = [event for event in events if event.task_id == task_id]
        return events

    def max_seq(self, run_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row[0])

    def save_checkpoint(
        self, run_id: str, *, event_seq: int, content_hash: str, state_json: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_checkpoints (run_id, event_seq, content_hash, state_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    event_seq = excluded.event_seq,
                    content_hash = excluded.content_hash,
                    state_json = excluded.state_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (run_id, event_seq, content_hash, state_json),
            )

    def load_checkpoint(self, run_id: str) -> tuple[int, str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_seq, content_hash, state_json FROM run_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row[0]), str(row[1]), str(row[2])

    def verify_trace(self, trace_id: str) -> TraceIntegrityReport:
        events = self.query(trace_id=trace_id)
        if not events:
            raise TraceIntegrityError(f"trace {trace_id} has no events")

        errors: list[str] = []
        spans: dict[str, list[RunEvent]] = {}
        for event in events:
            if event.event_type.startswith("component.call."):
                spans.setdefault(event.span_id, []).append(event)
            payload = event.model_dump_json()
            if any(pattern.search(payload) for pattern in _SECRET_PATTERNS):
                errors.append(f"secret-like content in event {event.event_id}")

        known_spans = set(spans)
        for span_id, span_events in spans.items():
            starts = [e for e in span_events if e.event_type == "component.call.started"]
            terminals = [e for e in span_events if e.event_type in _TERMINAL_TYPES]
            if len(starts) != 1:
                errors.append(f"span {span_id} requires exactly one start")
            if len(terminals) != 1:
                errors.append(f"span {span_id} missing terminal event")
            parents = {e.parent_span_id for e in span_events if e.parent_span_id}
            for parent in parents:
                if parent not in known_spans:
                    errors.append(f"span {span_id} has unknown parent {parent}")

        if errors:
            raise TraceIntegrityError("; ".join(errors))
        return TraceIntegrityReport(
            trace_id=trace_id,
            event_count=len(events),
            span_count=len(spans),
        )
