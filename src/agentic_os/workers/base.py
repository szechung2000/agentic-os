"""Worker agents: each owns a capability and talks to tools.

Workers are deliberately dumb-but-reliable: they receive a structured task,
execute it against their tools, and return structured results. All reasoning
and routing lives in the supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.events import ComponentCancelledError, ComponentTimedOutError
from agentic_os.memory.scoped import MemoryHydrator, MemoryScope, ScopedMemoryPolicy


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


class ScopedMemoryWorker(Worker):
    """Model-visible memory worker with logical operations only.

    It owns no namespace parameter and delegates all authorization, namespace
    derivation, lifecycle checks, IDs, and provenance to ``ScopedMemoryPolicy``.
    """

    name = "memory"
    description = (
        "remember private facts, search scoped context, assemble provenance-bearing context"
    )

    def __init__(
        self,
        policy: ScopedMemoryPolicy,
        tracer=None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        super().__init__(tracer, artifacts)
        self.policy = policy

    async def run(self, task: dict[str, Any]) -> TaskResult:
        if "namespace" in task:
            return TaskResult(self.name, False, "raw namespace is not an accepted memory operation")
        action = task.get("action", "search")
        try:
            if action == "remember":
                result = self._remember(task)
            elif action == "search":
                result = self._context(task)
            elif action == "context":
                result = {"context": self._hydrate(task)}
            elif action == "promote":
                raise PermissionError("workers cannot promote memory to project-shared scope")
            else:
                return TaskResult(self.name, False, f"unknown memory action: {action}")
        except (PermissionError, ValueError) as exc:
            return TaskResult(self.name, False, str(exc))
        output = json_dumps(result)
        return TaskResult(self.name, True, output, details=self._details(result))

    def _remember(self, task: dict[str, Any]) -> dict[str, Any]:
        content = str(task.get("content", "")).strip()
        if not content:
            raise ValueError("remember requires content")
        visibility = task.get("visibility", "private")
        if visibility == "private":
            record = self.policy.write(MemoryScope.WORKER_PRIVATE, content)
        elif visibility == "user":
            record = self.policy.write(MemoryScope.USER, content)
        elif visibility == "run":
            expires_at = task.get("expires_at")
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expires_at is None:
                expires_at = datetime.now(UTC) + timedelta(hours=1)
            if not isinstance(expires_at, datetime):
                raise ValueError("expires_at must be an ISO-8601 timestamp")
            record = self.policy.write_run_event(content, expires_at=expires_at)
        else:
            raise ValueError("visibility must be private, user, or run")
        return {"status": "remembered", "memory": record.model_dump(mode="json"), "id": record.id}

    def _hydrate(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(task.get("query", "")).strip()
        if not query:
            raise ValueError("search/context requires query")
        return [item.model_dump(mode="json") for item in MemoryHydrator(self.policy).hydrate(query)]

    def _context(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        return self._hydrate(task)

    @staticmethod
    def _details(result: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
        if isinstance(result, dict) and "id" in result:
            return {"memory_ids": [result["id"]]}
        values = result.get("context", []) if isinstance(result, dict) else result
        return {"memory_ids": [item["provenance_id"] for item in values]}


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
    memory_policy: ScopedMemoryPolicy | None = None,
    *,
    tracer=None,
    artifacts: ArtifactStore | None = None,
) -> list[Worker]:
    workers: list[Worker] = []
    if memory_policy is not None:
        if not isinstance(memory_policy, ScopedMemoryPolicy):
            raise TypeError("memory_policy must be a ScopedMemoryPolicy")
        workers.append(ScopedMemoryWorker(memory_policy, tracer, artifacts))
    workers.append(EchoWorker(tracer, artifacts))
    return workers


def json_dumps(value: Any) -> str:
    """Local import keeps the worker module's public boundary small."""
    import json

    return json.dumps(value)
