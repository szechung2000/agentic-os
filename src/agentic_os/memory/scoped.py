"""Scoped-memory policy, hydration, and agent-memory HTTP adapter.

The backing service stores and recalls records.  This module owns every
Agentic OS namespace decision and never permits callers to submit one.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_os.core.contracts import ComponentKind, ContextItem
from agentic_os.core.events import ComponentTracer

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"


class ActorKind(StrEnum):
    SUPERVISOR = "supervisor"
    WORKER = "worker"


class MemoryKind(StrEnum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT_SHARED = "project_shared"
    SUPERVISOR_PRIVATE = "supervisor_private"
    WORKER_PRIVATE = "worker_private"
    RUN_SHORT_TERM = "run_short_term"


class ActorAccessContext(BaseModel):
    """Immutable validated identity for all memory access decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_kind: ActorKind
    user_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    project_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    run_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    task_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    worker_id: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)

    @model_validator(mode="after")
    def validate_actor_shape(self) -> ActorAccessContext:
        if self.actor_kind is ActorKind.WORKER and not self.worker_id:
            raise ValueError("worker access requires worker_id")
        if self.actor_kind is ActorKind.SUPERVISOR and self.worker_id is not None:
            raise ValueError("supervisor access must not include worker_id")
        return self


class MemoryTraceContext(BaseModel):
    """Trace coordinates supplied by the orchestration layer, never storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str | None = None
    parent_span_id: str | None = None


class MemoryRecord(BaseModel):
    """Transport-neutral representation of agent-memory's service record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: f"memory_{uuid4().hex}", min_length=1)
    kind: MemoryKind = MemoryKind.SEMANTIC
    namespace: str = Field(min_length=1)
    content: str = Field(min_length=1)
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    user_id: str = "local"
    agent_id: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    score: float | None = None


class ScopedMemoryStore(Protocol):
    """The small storage/recall boundary used by scope policy."""

    def write(self, memory: MemoryRecord) -> MemoryRecord: ...

    def recall(self, namespace: str, query: str, k: int) -> list[MemoryRecord]: ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...


class RunLifecycle(Protocol):
    """Durable run-status authority used for short-term memory access."""

    def is_run_active(self, run_id: str) -> bool: ...


class SyncHttpClient(Protocol):
    """Small synchronous HTTP client surface shared by httpx and TestClient."""

    def post(self, url: str, *, json: Any) -> httpx.Response: ...

    def close(self) -> None: ...


class MemoryScopeMapper:
    """Derives the complete canonical namespace set from validated identities."""

    def namespace(self, context: ActorAccessContext, scope: MemoryScope) -> str:
        if not isinstance(scope, MemoryScope):
            raise ValueError("scope must be a MemoryScope, not a raw namespace")
        if scope is MemoryScope.USER:
            return f"user/{context.user_id}"
        if scope is MemoryScope.PROJECT_SHARED:
            return f"project/{context.project_id}/shared"
        if scope is MemoryScope.SUPERVISOR_PRIVATE:
            return f"project/{context.project_id}/supervisor"
        if scope is MemoryScope.WORKER_PRIVATE:
            if not context.worker_id:
                raise ValueError("worker-private scope requires a worker actor")
            return f"project/{context.project_id}/worker/{context.worker_id}"
        if scope is MemoryScope.RUN_SHORT_TERM:
            return f"run/{context.run_id}/short-term"
        raise AssertionError(f"unhandled memory scope: {scope}")


class InMemoryScopedStore:
    """Deterministic test double; policy tests should not need embeddings or credentials."""

    def __init__(self) -> None:
        self._records: dict[str, list[MemoryRecord]] = {}
        self._by_id: dict[str, MemoryRecord] = {}
        self.calls: list[tuple[str, str]] = []

    def write(self, memory: MemoryRecord) -> MemoryRecord:
        self.calls.append(("write", memory.namespace))
        self._records.setdefault(memory.namespace, []).append(memory)
        self._by_id[memory.id] = memory
        return memory

    def recall(self, namespace: str, query: str, k: int) -> list[MemoryRecord]:
        self.calls.append(("recall", namespace))
        return list(self._records.get(namespace, []))[:k]

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._by_id.get(memory_id)


class HttpAgentMemoryStore:
    """HTTP adapter for agent-memory commit 494610f's /remember and /recall API."""

    def __init__(
        self,
        base_url: str,
        *,
        client: SyncHttpClient | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/") + "/", transport=transport, timeout=timeout
        )
        self._owns_client = client is None
        self._records: dict[str, MemoryRecord] = {}

    @classmethod
    def from_settings(
        cls,
        *,
        client: SyncHttpClient | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> HttpAgentMemoryStore:
        return cls(
            os.getenv("AGOS_MEMORY_URL", "http://localhost:8000"),
            client=client,
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def write(self, memory: MemoryRecord) -> MemoryRecord:
        payload = memory.model_dump(
            include={
                "content",
                "kind",
                "namespace",
                "user_id",
                "agent_id",
                "title",
                "metadata",
                "session_id",
            },
            mode="json",
        )
        response = self.client.post("/remember", json=payload)
        response.raise_for_status()
        stored = memory.model_copy(update={"id": response.json()["id"]})
        self._records[stored.id] = stored
        return stored

    def recall(self, namespace: str, query: str, k: int) -> list[MemoryRecord]:
        response = self.client.post(
            "/recall", json={"query": query, "k": k, "namespace": namespace}
        )
        response.raise_for_status()
        records = [MemoryRecord.model_validate(item) for item in response.json()]
        self._records.update({record.id: record for record in records})
        return records

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Return only records returned by this service session.

        The pinned agent-memory API has no get-by-ID endpoint.  Promotions
        therefore require a source record that this adapter actually received
        from the backing service, rather than trusting caller-created data.
        """
        return self._records.get(memory_id)


class ScopedMemoryPolicy:
    """Authorizes logical scopes before invoking any storage operation."""

    def __init__(
        self,
        store: ScopedMemoryStore,
        context: ActorAccessContext,
        *,
        mapper: MemoryScopeMapper | None = None,
        lifecycle: RunLifecycle | None = None,
        tracer: ComponentTracer | None = None,
        trace: MemoryTraceContext | None = None,
    ) -> None:
        if (tracer is None) != (trace is None):
            raise ValueError("tracer and trace context must be supplied together")
        self.store = store
        self.context = context
        self.mapper = mapper or MemoryScopeMapper()
        self.lifecycle = lifecycle
        self.tracer = tracer
        self.trace = trace

    def write(
        self,
        scope: MemoryScope,
        content: str,
        *,
        kind: MemoryKind = MemoryKind.SEMANTIC,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> MemoryRecord:
        self._authorize(scope, operation="write")
        if scope is MemoryScope.RUN_SHORT_TERM:
            raise ValueError("run short-term records must use write_run_event")
        memory = MemoryRecord(
            kind=kind,
            namespace=self.mapper.namespace(self.context, scope),
            content=content,
            title=title,
            metadata=self._owned_metadata(metadata),
            user_id=self.context.user_id,
            agent_id=self._agent_id(),
        )
        return self._traced("memory.write", lambda: self.store.write(memory))

    def write_run_event(
        self,
        content: str,
        *,
        expires_at: datetime,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> MemoryRecord:
        self._authorize(MemoryScope.RUN_SHORT_TERM, operation="write")
        self._require_active_run()
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        event_metadata = dict(metadata or {})
        event_metadata.update(
            {
                "run_id": self.context.run_id,
                "task_id": self.context.task_id,
                "owner_actor_id": self._agent_id(),
                "owner_user_id": self.context.user_id,
                "owner_project_id": self.context.project_id,
                "expires_at": expires_at.astimezone(UTC).isoformat(),
            }
        )
        memory = MemoryRecord(
            kind=MemoryKind.EPISODIC,
            namespace=self.mapper.namespace(self.context, MemoryScope.RUN_SHORT_TERM),
            content=content,
            title=title,
            metadata=event_metadata,
            user_id=self.context.user_id,
            agent_id=self._agent_id(),
            session_id=self.context.run_id,
        )
        return self._traced("memory.write_run_event", lambda: self.store.write(memory))

    def promote_to_shared(
        self,
        source: MemoryRecord,
        *,
        content: str | None = None,
        title: str | None = None,
    ) -> MemoryRecord:
        if self.context.actor_kind is not ActorKind.SUPERVISOR:
            raise PermissionError("only a supervisor or explicitly authorized curator may promote")
        persisted = self.store.get(source.id)
        if persisted is None:
            raise PermissionError("promotion source ID was not returned by the backing store")
        if persisted.namespace != source.namespace or persisted.content != source.content:
            raise PermissionError("promotion source does not match the stored memory ID")
        self._validate_promotion_source(persisted)
        metadata = {
            "source_memory_id": persisted.id,
            "source_namespace": persisted.namespace,
            "source_kind": persisted.kind.value,
            "source_created_at": persisted.created_at.isoformat(),
        }
        return self.write(
            MemoryScope.PROJECT_SHARED,
            content or persisted.content,
            kind=MemoryKind.SEMANTIC,
            metadata=metadata,
            title=title or persisted.title,
        )

    def read(self, scope: MemoryScope, query: str, *, k: int = 10) -> list[MemoryRecord]:
        self._authorize(scope, operation="read")
        if scope is MemoryScope.RUN_SHORT_TERM:
            self._require_active_run()
        namespace = self.mapper.namespace(self.context, scope)
        return self._traced("memory.recall", lambda: self.store.recall(namespace, query, k))

    def hydration_scopes(self) -> tuple[MemoryScope, ...]:
        private = (
            MemoryScope.SUPERVISOR_PRIVATE
            if self.context.actor_kind is ActorKind.SUPERVISOR
            else MemoryScope.WORKER_PRIVATE
        )
        return (
            MemoryScope.PROJECT_SHARED,
            private,
            MemoryScope.USER,
            *((MemoryScope.RUN_SHORT_TERM,) if self._run_is_active() else ()),
        )

    def _authorize(self, scope: MemoryScope, *, operation: str) -> None:
        if not isinstance(scope, MemoryScope):
            raise ValueError("scope must be a MemoryScope, not a raw namespace")
        allowed = {
            ActorKind.SUPERVISOR: {
                MemoryScope.USER,
                MemoryScope.PROJECT_SHARED,
                MemoryScope.SUPERVISOR_PRIVATE,
                MemoryScope.RUN_SHORT_TERM,
            },
            ActorKind.WORKER: {
                MemoryScope.USER,
                MemoryScope.PROJECT_SHARED,
                MemoryScope.WORKER_PRIVATE,
                MemoryScope.RUN_SHORT_TERM,
            },
        }[self.context.actor_kind]
        if scope not in allowed:
            raise PermissionError(f"{self.context.actor_kind} cannot {operation} {scope}")
        if (
            self.context.actor_kind is ActorKind.WORKER
            and scope is MemoryScope.PROJECT_SHARED
            and operation == "write"
        ):
            raise PermissionError("workers may read project-shared memory but cannot write it")

    def _owned_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        owned = dict(metadata or {})
        owned.update(
            {
                "owner_actor_id": self._agent_id(),
                "owner_user_id": self.context.user_id,
                "owner_project_id": self.context.project_id,
                "owner_run_id": self.context.run_id,
                "owner_task_id": self.context.task_id,
            }
        )
        return owned

    def _run_is_active(self) -> bool:
        return self.lifecycle is not None and self.lifecycle.is_run_active(self.context.run_id)

    def _require_active_run(self) -> None:
        if not self._run_is_active():
            raise PermissionError("run short-term memory requires an active durable run")

    def _validate_promotion_source(self, source: MemoryRecord) -> None:
        metadata = source.metadata
        if metadata.get("owner_user_id") != self.context.user_id:
            raise PermissionError("promotion source belongs to another user")
        if metadata.get("owner_project_id") != self.context.project_id:
            raise PermissionError("promotion source belongs to another project")
        run_namespace = self.mapper.namespace(self.context, MemoryScope.RUN_SHORT_TERM)
        if source.namespace == run_namespace:
            if metadata.get("run_id") != self.context.run_id:
                raise PermissionError("promotion run source belongs to another run")
            return
        prefix = f"project/{self.context.project_id}/worker/"
        if source.namespace.startswith(prefix):
            owner = source.namespace.removeprefix(prefix)
            if not owner or metadata.get("owner_actor_id") != owner:
                raise PermissionError("worker-private promotion source has invalid owner metadata")
            return
        if source.namespace == self.mapper.namespace(self.context, MemoryScope.USER):
            return
        if source.namespace == self.mapper.namespace(self.context, MemoryScope.SUPERVISOR_PRIVATE):
            if metadata.get("owner_actor_id") != "supervisor":
                raise PermissionError("supervisor-private source has invalid owner metadata")
            return
        raise PermissionError(
            "promotion source is outside this supervisor's user/project/run scope"
        )

    def _traced(self, operation: str, callback):
        if self.tracer is None or self.trace is None:
            return callback()
        with self.tracer.span(
            trace_id=self.trace.trace_id,
            goal_id=self.trace.goal_id,
            run_id=self.trace.run_id,
            task_id=self.trace.task_id,
            parent_span_id=self.trace.parent_span_id,
            component_kind=ComponentKind.MEMORY,
            component_name="scoped-memory",
            operation=operation,
            actor_id=self._agent_id(),
        ) as span:
            result = callback()
            records = result if isinstance(result, list) else [result]
            span.add_memory_ids(record.id for record in records)
            return result

    def _agent_id(self) -> str:
        return self.context.worker_id or "supervisor"


class MemoryHydrator:
    """Applies deterministic layer priority, expiry filtering, and character budget."""

    def __init__(
        self, policy: ScopedMemoryPolicy, *, character_budget: int = 4000, k: int = 10
    ) -> None:
        if character_budget < 0:
            raise ValueError("character_budget must be non-negative")
        if k < 1:
            raise ValueError("k must be positive")
        self.policy = policy
        self.character_budget = character_budget
        self.k = k

    def hydrate(self, query: str, *, now: datetime | None = None) -> list[ContextItem]:
        current = now or datetime.now(UTC)
        remaining = self.character_budget
        items: list[ContextItem] = []
        for scope in self.policy.hydration_scopes():
            records = self.policy.read(scope, query, k=self.k)
            for memory in records:
                if self._expired(memory, current):
                    continue
                if len(memory.content) > remaining:
                    continue
                items.append(self._to_context_item(memory))
                remaining -= len(memory.content)
        return items

    @staticmethod
    def _expired(memory: MemoryRecord, now: datetime) -> bool:
        expires_at = memory.metadata.get("expires_at")
        if expires_at is None:
            return False
        if not isinstance(expires_at, str):
            return True
        try:
            parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return True
        except ValueError:
            return True
        return parsed <= now

    @staticmethod
    def _to_context_item(memory: MemoryRecord) -> ContextItem:
        return ContextItem(
            summary=memory.content,
            provenance_type="memory",
            provenance_id=memory.id,
            content_hash=f"sha256:{hashlib.sha256(memory.content.encode()).hexdigest()}",
            memory_namespace=memory.namespace,
            memory_kind=memory.kind.value,
            memory_metadata=memory.metadata,
            memory_score=memory.score,
            memory_created_at=memory.created_at,
        )
