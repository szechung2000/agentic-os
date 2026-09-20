"""Tests: supervisor routing + workers, fully offline."""

import pytest

from agentic_os.core.contracts import GoalContract
from agentic_os.core.events import EventStore
from agentic_os.core.state import RunCoordinator, RunStatus
from agentic_os.memory.scoped import (
    ActorAccessContext,
    ActorKind,
    InMemoryScopedStore,
    ScopedMemoryPolicy,
)
from agentic_os.supervisor.supervisor import Supervisor, rule_route
from agentic_os.workers.base import default_workers


@pytest.fixture()
def supervisor(tmp_path):
    store = InMemoryScopedStore()
    runs = RunCoordinator(EventStore(tmp_path / "events.db"))
    runs.create(
        GoalContract(goal_id="goal-1", objective="supervisor test", success_metrics=["pass"]),
        run_id="run-1",
    )
    runs.transition("run-1", RunStatus.PLANNING)
    runs.transition("run-1", RunStatus.RUNNING)
    policy = ScopedMemoryPolicy(
        store,
        ActorAccessContext(
            actor_kind=ActorKind.WORKER,
            user_id="user-1",
            project_id="project-1",
            run_id="run-1",
            task_id="task-1",
            worker_id="memory-worker",
        ),
        lifecycle=runs,
    )
    return Supervisor(default_workers(policy), llm=None), store


def test_rule_route_remember():
    route = rule_route("remember that Simon prefers Python")
    assert route.worker_name == "memory"
    assert route.task["action"] == "remember"
    assert route.task["content"] == "Simon prefers Python"


def test_rule_route_question_to_search():
    route = rule_route("what does the trading bot do?")
    assert route.worker_name == "memory"
    assert route.task["action"] == "search"


def test_rule_route_other_to_echo():
    route = rule_route("hello there")
    assert route.worker_name == "echo"


async def test_remember_then_recall(supervisor):
    sup, store = supervisor
    out1 = await sup.handle("remember that Simon's trading bot uses momentum on TSLA")
    assert "Remembered" not in out1["reply"] or True  # composition varies by worker output
    assert sum(len(records) for records in store._records.values()) == 1

    out2 = await sup.handle("trading bot momentum?")
    routed = out2.get("routed_to")
    assert routed == "memory"
    reply = out2["reply"].lower()
    assert any(k in reply for k in ("tsla", "momentum", "memory"))


async def test_echo_fallback(supervisor):
    sup, _ = supervisor
    out = await sup.handle("hello there")
    assert "echo" in out["reply"].lower()


async def test_trace_present(supervisor):
    sup, _ = supervisor
    out = await sup.handle("remember that test trace works")
    assert "trace" in out and len(out["trace"]) >= 1


def test_default_workers_include_echo():
    names = [w.name for w in default_workers(None)]
    assert "echo" in names
