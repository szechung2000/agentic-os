"""E2A scoped-memory policy tests — written before the implementation."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from agentic_os.core.contracts import GoalContract
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.core.state import RunCoordinator, RunStatus
from agentic_os.memory.scoped import (
    ActorAccessContext,
    ActorKind,
    HttpAgentMemoryStore,
    InMemoryScopedStore,
    MemoryHydrator,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryScopeMapper,
    MemoryTraceContext,
    ScopedMemoryPolicy,
)
from agentic_os.workers.base import ScopedMemoryWorker


def worker(worker_id: str, *, run_id: str = "run-1", task_id: str = "task-1") -> ActorAccessContext:
    return ActorAccessContext(
        actor_kind=ActorKind.WORKER,
        user_id="user-1",
        project_id="project-1",
        run_id=run_id,
        task_id=task_id,
        worker_id=worker_id,
    )


def supervisor() -> ActorAccessContext:
    return ActorAccessContext(
        actor_kind=ActorKind.SUPERVISOR,
        user_id="user-1",
        project_id="project-1",
        run_id="run-1",
        task_id="task-1",
    )


def active_lifecycle(tmp_path, run_id: str = "run-1"):
    coordinator = RunCoordinator(EventStore(tmp_path / "run-events.db"))
    coordinator.create(
        GoalContract(goal_id="goal-1", objective="memory test", success_metrics=["pass"]),
        run_id=run_id,
    )
    coordinator.transition(run_id, RunStatus.PLANNING)
    coordinator.transition(run_id, RunStatus.RUNNING)
    return coordinator


def test_scope_mapper_is_canonical_and_context_is_immutable():
    context = worker("worker-a")
    mapper = MemoryScopeMapper()

    assert mapper.namespace(context, MemoryScope.USER) == "user/user-1"
    assert mapper.namespace(context, MemoryScope.PROJECT_SHARED) == "project/project-1/shared"
    assert (
        mapper.namespace(context, MemoryScope.WORKER_PRIVATE) == "project/project-1/worker/worker-a"
    )
    assert mapper.namespace(context, MemoryScope.RUN_SHORT_TERM) == "run/run-1/short-term"
    with pytest.raises(ValidationError):
        ActorAccessContext(
            actor_kind=ActorKind.WORKER,
            user_id="user/escape",
            project_id="project-1",
            run_id="run-1",
            task_id="task-1",
            worker_id="worker-a",
        )
    with pytest.raises(ValidationError):
        ActorAccessContext(
            actor_kind=ActorKind.SUPERVISOR,
            user_id="user-1",
            project_id="project-1",
            run_id="run-1",
            task_id="task-1",
            worker_id="not-permitted",
        )
    with pytest.raises(ValidationError):
        context.worker_id = "worker-b"


def test_production_builder_uses_http_scoped_worker_and_validated_entry_context(tmp_path):
    from agentic_os.cli import build_production_memory_policy
    from agentic_os.workers.base import default_workers

    policy = build_production_memory_policy(
        Namespace(
            memory_event_db=str(tmp_path / "events.db"),
            memory_user_id="single-user",
            memory_project_id="project-1",
            memory_run_id="run-1",
            memory_task_id="task-1",
            memory_worker_id="worker-a",
        )
    )
    assert isinstance(default_workers(policy)[0], ScopedMemoryWorker)
    assert policy.context.model_dump(mode="json") == {
        "actor_kind": "worker",
        "user_id": "single-user",
        "project_id": "project-1",
        "run_id": "run-1",
        "task_id": "task-1",
        "worker_id": "worker-a",
    }


def test_policy_authorizes_before_backend_and_never_accepts_raw_namespace():
    store = InMemoryScopedStore()
    policy = ScopedMemoryPolicy(store, worker("worker-a"))

    with pytest.raises(PermissionError):
        policy.write(MemoryScope.SUPERVISOR_PRIVATE, "not allowed")
    with pytest.raises(PermissionError):
        policy.read(MemoryScope.SUPERVISOR_PRIVATE, "not allowed")
    with pytest.raises(ValueError):
        policy.write("project/project-1/worker/worker-b", "bypass attempt")  # type: ignore[arg-type]
    assert store.calls == []


@pytest.mark.asyncio
async def test_scoped_worker_exposes_logical_operations_and_never_raw_namespaces(tmp_path):
    policy = ScopedMemoryPolicy(
        InMemoryScopedStore(), worker("worker-a"), lifecycle=active_lifecycle(tmp_path)
    )
    memory_worker = ScopedMemoryWorker(policy)

    remembered = await memory_worker.run({"action": "remember", "content": "private fact"})
    assert remembered.ok
    assert json.loads(remembered.output)["id"]

    context = await memory_worker.run({"action": "context", "query": "fact"})
    item = json.loads(context.output)["context"][0]
    assert item["provenance_type"] == "memory"
    assert item["provenance_id"]

    rejected = await memory_worker.run(
        {"action": "remember", "content": "escape", "namespace": "project/other/shared"}
    )
    assert not rejected.ok and "namespace" in rejected.output


def test_worker_cannot_write_or_promote_shared_and_supervisor_validates_source(tmp_path):
    store = InMemoryScopedStore()
    coordinator = active_lifecycle(tmp_path)
    worker_policy = ScopedMemoryPolicy(store, worker("worker-a"), lifecycle=coordinator)
    supervisor_policy = ScopedMemoryPolicy(store, supervisor(), lifecycle=coordinator)
    source = worker_policy.write_run_event(
        "candidate", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )

    with pytest.raises(PermissionError):
        worker_policy.write(MemoryScope.PROJECT_SHARED, "not permitted")
    with pytest.raises(PermissionError):
        worker_policy.promote_to_shared(source)

    promoted = supervisor_policy.promote_to_shared(source)
    assert promoted.metadata["source_memory_id"] == source.id
    forged = source.model_copy(update={"namespace": "project/other/worker/worker-a"})
    with pytest.raises(PermissionError):
        supervisor_policy.promote_to_shared(forged)


def test_run_memory_is_gated_by_durable_lifecycle_after_restart(tmp_path):
    events = EventStore(tmp_path / "run-events.db")
    first = RunCoordinator(events)
    first.create(
        GoalContract(goal_id="goal-1", objective="memory test", success_metrics=["pass"]),
        run_id="run-1",
    )
    first.transition("run-1", RunStatus.PLANNING)
    first.transition("run-1", RunStatus.RUNNING)
    policy = ScopedMemoryPolicy(InMemoryScopedStore(), worker("worker-a"), lifecycle=first)
    policy.write_run_event("active", expires_at=datetime.now(UTC) + timedelta(hours=1))

    restarted = RunCoordinator(EventStore(tmp_path / "run-events.db"))
    restarted.transition("run-1", RunStatus.COMPLETED)
    guarded = ScopedMemoryPolicy(policy.store, worker("worker-a"), lifecycle=restarted)
    assert MemoryHydrator(guarded).hydrate("active") == []
    with pytest.raises(PermissionError):
        guarded.write_run_event("late", expires_at=datetime.now(UTC) + timedelta(hours=1))


def test_private_isolation_shared_user_and_run_visibility(tmp_path):
    store = InMemoryScopedStore()
    lifecycle = active_lifecycle(tmp_path)
    worker_a = ScopedMemoryPolicy(store, worker("worker-a"), lifecycle=lifecycle)
    worker_b = ScopedMemoryPolicy(store, worker("worker-b"), lifecycle=lifecycle)
    sup = ScopedMemoryPolicy(store, supervisor(), lifecycle=lifecycle)

    sup.write(MemoryScope.PROJECT_SHARED, "shared decision")
    worker_a.write(MemoryScope.WORKER_PRIVATE, "worker A trial")
    worker_b.write(MemoryScope.WORKER_PRIVATE, "worker B trial")
    sup.write(MemoryScope.SUPERVISOR_PRIVATE, "supervisor only")
    sup.write(MemoryScope.USER, "prefers precise reports")
    worker_a.write_run_event("run evidence", expires_at=datetime.now(UTC) + timedelta(hours=1))

    a_contents = [item.summary for item in MemoryHydrator(worker_a).hydrate("project")]
    b_contents = [item.summary for item in MemoryHydrator(worker_b).hydrate("project")]
    sup_contents = [item.summary for item in MemoryHydrator(sup).hydrate("project")]
    assert {"shared decision", "worker A trial", "prefers precise reports", "run evidence"} <= set(
        a_contents
    )
    assert "worker B trial" not in a_contents and "supervisor only" not in a_contents
    assert "worker A trial" not in b_contents and "supervisor only" not in b_contents
    assert "supervisor only" in sup_contents


def test_hydration_is_layer_ordered_budgeted_and_has_reconstructable_provenance(tmp_path):
    store = InMemoryScopedStore()
    lifecycle = active_lifecycle(tmp_path)
    policy = ScopedMemoryPolicy(store, worker("worker-a"), lifecycle=lifecycle)
    ScopedMemoryPolicy(store, supervisor(), lifecycle=lifecycle).write(
        MemoryScope.PROJECT_SHARED, "shared"
    )
    policy.write(MemoryScope.WORKER_PRIVATE, "private")
    policy.write(MemoryScope.USER, "user")
    policy.write_run_event("run", expires_at=datetime.now(UTC) + timedelta(hours=1))

    items = MemoryHydrator(policy, character_budget=len("sharedprivateuser")).hydrate("anything")

    assert [item.summary for item in items] == ["shared", "private", "user"]
    assert sum(len(item.summary) for item in items) <= len("sharedprivateuser")
    assert all(item.provenance_type == "memory" and item.provenance_id for item in items)
    assert all(
        item.memory_namespace and item.memory_kind and item.memory_created_at for item in items
    )


def test_run_events_expire_and_promotion_preserves_source_provenance(tmp_path):
    store = InMemoryScopedStore()
    lifecycle = active_lifecycle(tmp_path)
    policy = ScopedMemoryPolicy(store, worker("worker-a"), lifecycle=lifecycle)
    expired = policy.write_run_event("expired", expires_at=datetime.now(UTC) - timedelta(seconds=1))
    current = policy.write_run_event("current", expires_at=datetime.now(UTC) + timedelta(hours=1))

    contents = [item.summary for item in MemoryHydrator(policy).hydrate("run")]
    assert "expired" not in contents and "current" in contents
    assert expired.metadata["run_id"] == "run-1"
    assert expired.metadata["task_id"] == "task-1"
    assert expired.kind is MemoryKind.EPISODIC

    promoted = ScopedMemoryPolicy(store, supervisor(), lifecycle=lifecycle).promote_to_shared(
        current
    )
    assert promoted.namespace == "project/project-1/shared"
    assert promoted.metadata["source_memory_id"] == current.id
    assert promoted.metadata["source_namespace"] == current.namespace


def test_memory_operations_trace_returned_memory_ids(tmp_path):
    store = InMemoryScopedStore()
    events = EventStore(tmp_path / "events.db")
    policy = ScopedMemoryPolicy(
        store,
        supervisor(),
        lifecycle=active_lifecycle(tmp_path),
        tracer=ComponentTracer(events),
        trace=MemoryTraceContext(
            trace_id="trace-1", goal_id="goal-1", run_id="run-1", task_id="task-1"
        ),
    )
    memory = policy.write(MemoryScope.PROJECT_SHARED, "traced")
    policy.read(MemoryScope.PROJECT_SHARED, "traced")

    terminal = [event for event in events.query(trace_id="trace-1") if event.status == "ok"]
    assert all(event.component_kind.value == "memory" for event in terminal)
    assert memory.id in terminal[0].memory_ids
    assert memory.id in terminal[1].memory_ids
    assert events.verify_trace("trace-1").ok


def test_http_adapter_uses_agos_memory_url_and_preserves_service_fields(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/remember":
            return httpx.Response(200, json={"id": "memory-http-1"})
        return httpx.Response(
            200,
            json=[
                {
                    "id": "memory-http-1",
                    "kind": "episodic",
                    "namespace": "run/run-1/short-term",
                    "title": "trial",
                    "content": "service fact",
                    "metadata": {"task_id": "task-1"},
                    "created_at": "2026-09-19T00:00:00+00:00",
                    "score": 0.75,
                }
            ],
        )

    monkeypatch.setenv("AGOS_MEMORY_URL", "http://memory.test/")
    store = HttpAgentMemoryStore.from_settings(transport=httpx.MockTransport(handler))
    written = store.write(
        MemoryRecord(
            id="ignored",
            kind=MemoryKind.EPISODIC,
            namespace="run/run-1/short-term",
            content="service fact",
            metadata={"task_id": "task-1"},
        )
    )
    recalled = store.recall("run/run-1/short-term", "service", 3)

    assert written.id == "memory-http-1"
    assert recalled[0].id == "memory-http-1"
    assert recalled[0].metadata == {"task_id": "task-1"}
    assert recalled[0].kind is MemoryKind.EPISODIC and recalled[0].score == 0.75
    assert recalled[0].created_at == datetime(2026, 9, 19, tzinfo=UTC)
    assert seen[0].url == httpx.URL("http://memory.test/remember")
    assert json.loads(seen[0].content)["namespace"] == "run/run-1/short-term"


def test_http_adapter_retains_mocked_service_error_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, json={"detail": "unavailable"})

    store = HttpAgentMemoryStore("http://memory.test", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        store.recall("user/user-1", "fact", 1)
