"""Bridge typed runtime execution into the legacy Worker/TaskResult boundary."""

from __future__ import annotations

import json
from typing import Any, Literal, cast
from uuid import uuid4

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract, WorkerResult
from agentic_os.core.events import ComponentTracer
from agentic_os.runtimes.base import RuntimeAdapter
from agentic_os.runtimes.contracts import (
    RuntimeExecutionResult,
    RuntimeStatus,
    RuntimeTraceFields,
    Workspace,
)
from agentic_os.workers.base import TaskResult, Worker


class RuntimeWorkerBridge(Worker):
    """Expose one runtime adapter as an existing supervisor worker.

    The bridge deliberately preserves ``Supervisor.handle`` and ``TaskResult``
    semantics while making the runtime boundary typed and durable. Provider
    selection belongs outside this class; the bridge receives one selected
    adapter and one explicitly approved workspace.
    """

    def __init__(
        self,
        adapter: RuntimeAdapter,
        workspace: Workspace,
        *,
        worker_name: str = "runtime",
        worker_id: str = "runtime-worker",
        tracer: ComponentTracer | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        super().__init__(tracer=tracer, artifacts=artifacts)
        self.adapter = adapter
        self.runtime_name = str(getattr(adapter, "runtime_name", type(adapter).__name__))
        self.workspace = workspace
        self.name = worker_name
        self.worker_id = worker_id
        self.description = f"headless {self.runtime_name} runtime worker"

    async def run(self, task: dict[str, Any]) -> TaskResult:
        contract = self._task_contract(task)
        trace_id = str(task.get("trace_id", f"trace_{contract.task_id}"))
        goal_id = contract.goal_id
        run_id = str(task.get("run_id", f"run_{contract.task_id}"))
        span_context = {
            "trace_id": trace_id,
            "goal_id": goal_id,
            "run_id": run_id,
            "task_id": contract.task_id,
            "component_kind": "runtime",
            "component_name": self.runtime_name,
            "operation": "runtime.execute",
            "data": {
                "runtime_name": self.runtime_name,
                "workspace_id": self.workspace.workspace_id,
                "worker_id": self.worker_id,
            },
        }

        if self.tracer is None:
            result = await self._execute(contract)
        else:
            with self.tracer.span(**span_context) as span:
                result = await self._execute(contract)
                trace = self._trace_fields(result)
                span_context["data"]["runtime_trace"] = trace.model_dump(mode="json")
                span.terminal_status = self._span_status(result.status)
                if result.output_ref is not None:
                    span.set_output(result.output_ref)

        return self._legacy_result(contract, result)

    async def _execute(self, contract: TaskContract) -> RuntimeExecutionResult:
        handle = await self.adapter.start(contract, self.workspace)
        return await self.adapter.result(handle)

    def _task_contract(self, task: dict[str, Any]) -> TaskContract:
        objective = task.get("objective") or task.get("content") or task.get("query")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("runtime task requires a non-empty objective")
        limits = task.get("limits", {})
        if not isinstance(limits, dict):
            raise ValueError("runtime task limits must be a mapping")
        return TaskContract(
            task_id=str(task.get("task_id", f"task_{uuid4().hex}")),
            goal_id=str(task.get("goal_id", "runtime-goal")),
            worker_role=str(task.get("worker_role", self.name)),
            objective=objective,
            dependencies=[str(item) for item in task.get("dependencies", [])],
            allowed_tools=[str(item) for item in task.get("allowed_tools", [])],
            expected_artifacts=[str(item) for item in task.get("expected_artifacts", [])],
            evaluator=task.get("evaluator"),
            limits=limits,
        )

    def _trace_fields(self, result: RuntimeExecutionResult) -> RuntimeTraceFields:
        if result.trace is not None:
            return result.trace
        return RuntimeTraceFields(
            runtime_name=self.runtime_name,
            runtime_version=None,
            cli_version=None,
            requested_model=None,
            effective_model=None,
            session_id=result.handle.session_id,
            workspace_id=self.workspace.workspace_id or "unknown",
            selected_runtime=self.runtime_name,
            fallback_rationale=None,
        )

    @staticmethod
    def _span_status(status: RuntimeStatus) -> str:
        return {
            RuntimeStatus.COMPLETED: "ok",
            RuntimeStatus.FAILED: "failed",
            RuntimeStatus.CANCELLED: "cancelled",
            RuntimeStatus.TIMED_OUT: "timed_out",
            RuntimeStatus.UNAVAILABLE: "failed",
        }[status]

    def _legacy_result(self, contract: TaskContract, result: RuntimeExecutionResult) -> TaskResult:
        failures = [diagnostic.message for diagnostic in result.diagnostics]
        worker_result = WorkerResult(
            task_id=contract.task_id,
            worker_id=self.worker_id,
            status=self._worker_status(result.status),
            summary=result.summary,
            artifacts=list(result.artifacts),
            evidence=[result.summary] if result.summary else [],
            tests=self._string_list(result.result_data.get("tests")),
            assumptions=self._string_list(result.result_data.get("assumptions")),
            failures=failures,
            recommendations=self._string_list(result.result_data.get("recommendations")),
        )
        details = {
            "worker_result": json.loads(worker_result.model_dump_json()),
            "runtime_result": json.loads(result.model_dump_json()),
        }
        return TaskResult(
            worker=self.name,
            ok=worker_result.status == "completed",
            output=result.summary,
            details=details,
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list | tuple):
            return []
        return [str(item) for item in value]

    @staticmethod
    def _worker_status(
        status: RuntimeStatus,
    ) -> Literal["completed", "failed", "cancelled", "timed_out"]:
        return cast(
            Literal["completed", "failed", "cancelled", "timed_out"],
            {
                RuntimeStatus.COMPLETED: "completed",
                RuntimeStatus.FAILED: "failed",
                RuntimeStatus.CANCELLED: "cancelled",
                RuntimeStatus.TIMED_OUT: "timed_out",
                RuntimeStatus.UNAVAILABLE: "failed",
            }[status],
        )
