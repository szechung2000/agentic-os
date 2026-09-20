"""Durable HTTP/ASGI executable proof for E2 scoped-memory hydration."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from agentic_os.core.contracts import GoalContract
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.core.state import RunCoordinator, RunStatus
from agentic_os.evals.harness import EvalCase, EvalHistory, EvalRun, EvalSuite
from agentic_os.memory.scoped import (
    ActorAccessContext,
    ActorKind,
    HttpAgentMemoryStore,
    MemoryHydrator,
    MemoryScope,
    MemoryTraceContext,
    ScopedMemoryPolicy,
)


@contextmanager
def pinned_agent_memory_service(database_url: str) -> Iterator[HttpAgentMemoryStore]:
    """Start a fresh pinned agent-memory ASGI service against ``database_url``."""
    try:
        from agent_memory.api import main as memory_main
        from agent_memory.core import config as memory_config
        from fastapi.testclient import TestClient
    except ImportError as exc:  # pragma: no cover - dependency-free installs
        raise RuntimeError(
            "E2 durable proof requires pinned agent-memory commit 494610f; install it first"
        ) from exc

    previous_url = os.environ.get("AM_DATABASE_URL")
    os.environ["AM_DATABASE_URL"] = database_url
    memory_config.get_settings.cache_clear()
    fresh_app_module = importlib.reload(memory_main)
    try:
        with TestClient(fresh_app_module.app) as client:
            yield HttpAgentMemoryStore("http://testserver", client=client)
    finally:
        # The service keeps a session factory in module globals; reset it and
        # its settings cache before the next fresh-service proof instance.
        fresh_app_module._factory = None
        memory_config.get_settings.cache_clear()
        if previous_url is None:
            os.environ.pop("AM_DATABASE_URL", None)
        else:
            os.environ["AM_DATABASE_URL"] = previous_url


@dataclass(frozen=True)
class E2Proof:
    run: EvalRun
    history_path: Path
    trace_id: str


def run_e2_proof(workdir: str | Path, *, candidate: str = "working-tree") -> E2Proof:
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    proof_id = uuid4().hex[:12]
    goal_id = f"e2-goal-{proof_id}"
    project_id = f"e2-project-{proof_id}"
    run_id = f"e2-run-{proof_id}"
    task_id = f"e2-task-{proof_id}"
    trace_id = f"e2-trace-{proof_id}"
    database_url = f"sqlite:///{root / 'agent-memory.db'}"
    events = EventStore(root / "events.db")
    coordinator = RunCoordinator(events)
    coordinator.create(
        GoalContract(
            goal_id=goal_id, objective="durable scoped recovery", success_metrics=["5/5"]
        ),
        run_id=run_id,
        trace_id=trace_id,
    )
    coordinator.transition(run_id, RunStatus.PLANNING)
    coordinator.transition(run_id, RunStatus.RUNNING)
    trace = MemoryTraceContext(
        trace_id=trace_id, goal_id=goal_id, run_id=run_id, task_id=task_id
    )

    def context(kind: ActorKind, worker_id: str | None = None) -> ActorAccessContext:
        return ActorAccessContext(
            actor_kind=kind,
            user_id="e2-user",
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            worker_id=worker_id,
        )

    with pinned_agent_memory_service(database_url) as store:
        worker_a = ScopedMemoryPolicy(
            store,
            context(ActorKind.WORKER, "worker-a"),
            lifecycle=coordinator,
            tracer=ComponentTracer(events),
            trace=trace,
        )
        worker_b = ScopedMemoryPolicy(
            store, context(ActorKind.WORKER, "worker-b"), lifecycle=coordinator
        )
        supervisor = ScopedMemoryPolicy(store, context(ActorKind.SUPERVISOR), lifecycle=coordinator)
        supervisor.write(MemoryScope.PROJECT_SHARED, "project goal: prove scoped recovery")
        worker_a.write(MemoryScope.WORKER_PRIVATE, "worker A prior trial fact")
        worker_b.write(MemoryScope.WORKER_PRIVATE, "worker B private trial")
        supervisor.write(MemoryScope.SUPERVISOR_PRIVATE, "supervisor only decision")
        supervisor.write(MemoryScope.USER, "user prefers credential-free proofs")
        worker_a.write_run_event(
            "expired run evidence", expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        current = worker_a.write_run_event(
            "current run evidence", expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        # A worker cannot publish shared knowledge. The supervisor promotes a
        # service-returned, same-run record after policy ownership validation.
        promoted = supervisor.promote_to_shared(current, content="promoted project decision")

        hydrated_a = MemoryHydrator(worker_a, character_budget=500).hydrate("proof")
        hydrated_b = MemoryHydrator(worker_b, character_budget=500).hydrate("proof")
        hydrated_supervisor = MemoryHydrator(supervisor, character_budget=500).hydrate("proof")
        budgeted = MemoryHydrator(worker_a, character_budget=45).hydrate("proof")
        a_contents = {item.summary for item in hydrated_a}
        b_contents = {item.summary for item in hydrated_b}
        supervisor_contents = {item.summary for item in hydrated_supervisor}

    def isolation_and_promotion() -> dict:
        return {
            "passed": (
                "promoted project decision" in a_contents
                and "promoted project decision" in b_contents
                and "worker B private trial" not in a_contents
                and "worker A prior trial fact" not in b_contents
                and bool(promoted.metadata["source_memory_id"])
            ),
            "promoted_memory_id": promoted.id,
        }

    def supervisor_private() -> dict:
        return {
            "passed": "supervisor only decision" in supervisor_contents
            and "supervisor only decision" not in a_contents
            and "supervisor only decision" not in b_contents,
        }

    def expiry() -> dict:
        return {
            "passed": "expired run evidence" not in a_contents
            and "current run evidence" in a_contents
            and current.metadata["run_id"] == run_id
            and current.metadata["task_id"] == task_id,
        }

    def budget_and_provenance() -> dict:
        return {
            "passed": sum(len(item.summary) for item in budgeted) <= 45
            and bool(budgeted)
            and all(
                item.provenance_type == "memory"
                and item.provenance_id
                and item.memory_namespace
                and item.memory_metadata is not None
                and item.memory_created_at
                for item in budgeted
            ),
            "characters": sum(len(item.summary) for item in budgeted),
            "items": len(budgeted),
        }

    def restart_and_trace() -> dict:
        # Fresh RunCoordinator, ASGI app, TestClient, HTTP adapter, and policy
        # over one SQLite database—not an in-memory object reuse.
        restarted_runs = RunCoordinator(EventStore(root / "events.db"))
        with pinned_agent_memory_service(database_url) as restarted_store:
            restarted = ScopedMemoryPolicy(
                restarted_store,
                context(ActorKind.WORKER, "worker-a"),
                lifecycle=restarted_runs,
                tracer=ComponentTracer(EventStore(root / "events.db")),
                trace=trace,
            )
            recovered = {item.summary for item in MemoryHydrator(restarted).hydrate("recover")}
        terminal = [event for event in events.query(trace_id=trace_id) if event.status == "ok"]
        return {
            "passed": {
                "project goal: prove scoped recovery",
                "promoted project decision",
                "worker A prior trial fact",
            }
            <= recovered
            and any(current.id in event.memory_ids for event in terminal)
            and events.verify_trace(trace_id).ok,
            "trace_events": len(terminal),
            "recovered": len(recovered),
            "backend": "fresh-agent-memory-asgi-service",
        }

    suite = EvalSuite(
        name="e2-scoped-memory",
        version="2",
        cases=[
            EvalCase(
                "worker-isolation-and-shared-promotion", isolation_and_promotion, ["security"]
            ),
            EvalCase("supervisor-private-visibility", supervisor_private, ["security"]),
            EvalCase("expiry-filtering", expiry, ["ttl", "episodic"]),
            EvalCase("budgeted-provenance-hydration", budget_and_provenance, ["hydration"]),
            EvalCase("restart-recovery-and-tracing", restart_and_trace, ["durability", "trace"]),
        ],
    )
    run = suite.run(candidate=candidate)
    history_path = root / "eval-history.jsonl"
    EvalHistory(history_path).append(run)
    return E2Proof(run=run, history_path=history_path, trace_id=trace_id)
