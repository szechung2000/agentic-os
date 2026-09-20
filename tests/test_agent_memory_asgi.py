"""Pinned agent-memory ASGI integration coverage for the E2 boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentic_os.core.contracts import GoalContract
from agentic_os.core.events import EventStore
from agentic_os.core.state import RunCoordinator, RunStatus
from agentic_os.evals.e2 import pinned_agent_memory_service
from agentic_os.memory.scoped import (
    ActorAccessContext,
    ActorKind,
    MemoryHydrator,
    MemoryScope,
    ScopedMemoryPolicy,
)


def _context(kind: ActorKind, worker_id: str | None = None) -> ActorAccessContext:
    return ActorAccessContext(
        actor_kind=kind,
        user_id="asgi-user",
        project_id="asgi-project",
        run_id="asgi-run",
        task_id="asgi-task",
        worker_id=worker_id,
    )


def _active_runs(path) -> RunCoordinator:
    runs = RunCoordinator(EventStore(path))
    runs.create(
        GoalContract(goal_id="asgi-goal", objective="ASGI memory", success_metrics=["pass"]),
        run_id="asgi-run",
    )
    runs.transition("asgi-run", RunStatus.PLANNING)
    runs.transition("asgi-run", RunStatus.RUNNING)
    return runs


def test_pinned_asgi_service_write_recall_isolation_expiry_and_fresh_restart(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'agent-memory.db'}"
    event_path = tmp_path / "events.db"
    runs = _active_runs(event_path)
    with pinned_agent_memory_service(database_url) as store:
        supervisor = ScopedMemoryPolicy(store, _context(ActorKind.SUPERVISOR), lifecycle=runs)
        worker_a = ScopedMemoryPolicy(store, _context(ActorKind.WORKER, "worker-a"), lifecycle=runs)
        worker_b = ScopedMemoryPolicy(store, _context(ActorKind.WORKER, "worker-b"), lifecycle=runs)
        shared = supervisor.write(MemoryScope.PROJECT_SHARED, "durable shared plan")
        private = worker_a.write(MemoryScope.WORKER_PRIVATE, "worker A secret")
        current = worker_a.write_run_event(
            "current evidence", expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        worker_a.write_run_event(
            "expired evidence", expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )

        a_items = MemoryHydrator(worker_a).hydrate("evidence")
        b_items = MemoryHydrator(worker_b).hydrate("secret")
        assert shared.id and private.id and current.id
        assert "worker A secret" in {item.summary for item in a_items}
        assert "worker A secret" not in {item.summary for item in b_items}
        assert "expired evidence" not in {item.summary for item in a_items}
        assert current.id in {item.provenance_id for item in a_items}
        current_item = next(item for item in a_items if item.provenance_id == current.id)
        assert current_item.memory_metadata["run_id"] == "asgi-run"
        assert current_item.memory_namespace == "run/asgi-run/short-term"

    # A different service app/TestClient/store/policy and RunCoordinator sees
    # the durable SQLite data; no InMemoryScopedStore is reused here.
    restarted_runs = RunCoordinator(EventStore(event_path))
    with pinned_agent_memory_service(database_url) as restarted_store:
        restarted_worker = ScopedMemoryPolicy(
            restarted_store, _context(ActorKind.WORKER, "worker-a"), lifecycle=restarted_runs
        )
        recovered = MemoryHydrator(restarted_worker).hydrate("durable evidence")
    recovered_by_id = {item.provenance_id: item for item in recovered}
    assert (
        shared.id in recovered_by_id
        and private.id in recovered_by_id
        and current.id in recovered_by_id
    )
    assert recovered_by_id[private.id].memory_metadata["owner_actor_id"] == "worker-a"
