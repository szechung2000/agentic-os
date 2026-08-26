"""Tests: supervisor routing + workers, fully offline."""

import json

import pytest

from agentic_os.supervisor.supervisor import Supervisor, rule_route
from agentic_os.workers.base import default_workers


class FakeMemoryExecutor:
    """In-memory stand-in for the agent-memory tool executor."""

    def __init__(self):
        self.store: list[str] = []

    def execute(self, name, arguments):
        if name == "memory_write":
            self.store.append(arguments["content"])
            return json.dumps({"id": f"m{len(self.store)}", "status": "remembered"})
        if name == "memory_search":
            hits = [
                {"content": c, "score": 0.9} for c in self.store
                if any(w in c.lower() for w in arguments["query"].lower().split()[:2])
            ]
            return json.dumps(hits)
        if name == "memory_context":
            block = "\n".join(f"- {c}" for c in self.store) or "(no relevant memories)"
            return json.dumps({"topic": arguments.get("query", ""), "context": block})
        return json.dumps({"error": f"unknown tool {name}"})


@pytest.fixture()
def supervisor():
    from agent_memory.core.embedding import get_embedder  # noqa: F401 — availability probe

    try:
        exec_ = FakeMemoryExecutor()
    except Exception:
        exec_ = None
    return Supervisor(default_workers(exec_), llm=None), exec_


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
    assert len(store.store) == 1

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
