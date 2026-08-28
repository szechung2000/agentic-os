"""Worker agents: each owns a capability and talks to tools.

Workers are deliberately dumb-but-reliable: they receive a structured task,
execute it against their tools, and return structured results. All reasoning
and routing lives in the supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.events import ComponentCancelledError, ComponentTimedOutError


class MemoryClientProtocol(Protocol):
    """Subset of the agent-memory client the memory worker needs."""

    def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


@dataclass
class TaskResult:
    worker: str
    ok: bool
    output: str
    details: dict = field(default_factory=dict)


class CancellationError(ComponentCancelledError):
    """Raised when a component call is cancelled."""


class TimeoutError(ComponentTimedOutError):
    """Raised when a component call times out."""


class Worker:
    """Base: name + tool executor function."""

    name: str = "worker"
    description: str = ""

    def __init__(self, tracer=None, artifacts: ArtifactStore | None = None) -> None:
        self.tracer = tracer
        self.artifacts = artifacts or getattr(tracer, "artifacts", None)

    def _create_output_ref(self, output: str):
        """Persist trace output only when the caller supplied a durable store."""
        if self.artifacts is None:
            return None
        return self.artifacts.put(output.encode(), "application/json")

    async def run(self, task: dict[str, Any]) -> TaskResult:
        raise NotImplementedError


class MemoryWorker(Worker):
    """Delegates to the agent-memory tool executor."""

    name = "memory"
    description = "remember facts, search long-term memory, assemble context"

    def __init__(
        self,
        executor: MemoryClientProtocol,
        tracer=None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        super().__init__(tracer, artifacts)
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
        if self.tracer:
            with self.tracer.span(
                trace_id=task.get("trace_id", "unknown"),
                goal_id=task.get("goal_id", "memory"),
                run_id=task.get("run_id", "memory-run"),
                component_kind="worker",
                component_name=self.name,
                operation=f"worker.{self.name}.run",
            ) as span:
                output = self.executor.execute(tool, payload)
                output_ref = self._create_output_ref(output)
                if output_ref is not None:
                    span.set_output(output_ref)
        else:
            output = self.executor.execute(tool, payload)
        return TaskResult(self.name, True, output)

class EchoWorker(Worker):
    """Demo/general-purpose fallback: returns the task payload. No external deps."""

    name = "echo"
    description = "general fallback worker for tasks without a specialist"

    def __init__(self, tracer=None, artifacts: ArtifactStore | None = None) -> None:
        super().__init__(tracer, artifacts)

    async def run(self, task: dict[str, Any]) -> TaskResult:
        content = task.get("content") or task.get("query") or str(task)
        if self.tracer:
            with self.tracer.span(
                trace_id=task.get("trace_id", "unknown"),
                goal_id=task.get("goal_id", "echo"),
                run_id=task.get("run_id", "echo-run"),
                component_kind="worker",
                component_name=self.name,
                operation=f"worker.{self.name}.run",
            ) as span:
                output = f"echo: {content}"
                output_ref = self._create_output_ref(output)
                if output_ref is not None:
                    span.set_output(output_ref)
        else:
            output = f"echo: {content}"
        return TaskResult(self.name, True, output)

def default_workers(
    memory_executor: MemoryClientProtocol | None = None,
    tracer=None,
    artifacts: ArtifactStore | None = None,
) -> list[Worker]:
    workers: list[Worker] = []
    if memory_executor is not None:
        workers.append(MemoryWorker(memory_executor, tracer, artifacts))
    workers.append(EchoWorker(tracer, artifacts))
    return workers
