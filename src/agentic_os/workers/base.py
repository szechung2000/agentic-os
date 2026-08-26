"""Worker agents: each owns a capability and talks to tools.

Workers are deliberately dumb-but-reliable: they receive a structured task,
execute it against their tools, and return structured results. All reasoning
and routing lives in the supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class MemoryClientProtocol(Protocol):
    """Subset of the agent-memory client the memory worker needs."""

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


@dataclass
class TaskResult:
    worker: str
    ok: bool
    output: str
    details: dict = field(default_factory=dict)


class Worker:
    """Base: name + tool executor function."""

    name: str = "worker"
    description: str = ""

    async def run(self, task: dict[str, Any]) -> TaskResult:
        raise NotImplementedError


class MemoryWorker(Worker):
    """Delegates to the agent-memory tool executor."""

    name = "memory"
    description = "remember facts, search long-term memory, assemble context"

    def __init__(self, executor: MemoryClientProtocol) -> None:
        self.executor = executor

    async def run(self, task: dict[str, Any]) -> TaskResult:
        action = task.get("action", "search")
        tool = {
            "remember": "memory_write",
            "search": "memory_search",
            "context": "memory_context",
        }.get(action)
        if tool is None:
            return TaskResult(self.name, False, f"unknown memory action: {action}")
        payload = {k: v for k, v in task.items() if k not in ("action", "worker")}
        output = self.executor.execute(tool, payload)
        return TaskResult(self.name, True, output)


class EchoWorker(Worker):
    """Demo/general-purpose fallback: returns the task payload. No external deps."""

    name = "echo"
    description = "general fallback worker for tasks without a specialist"

    async def run(self, task: dict[str, Any]) -> TaskResult:
        content = task.get("content") or task.get("query") or str(task)
        return TaskResult(self.name, True, f"echo: {content}")


def default_workers(memory_executor: MemoryClientProtocol | None = None) -> list[Worker]:
    workers: list[Worker] = []
    if memory_executor is not None:
        workers.append(MemoryWorker(memory_executor))
    workers.append(EchoWorker())
    return workers
