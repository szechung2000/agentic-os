"""Durable, versioned contracts for orchestration boundaries."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class Contract(BaseModel):
    """Base contract: strict enough for process/durable boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    schema_version: str = "1"


class ArtifactRef(Contract):
    artifact_id: str = Field(default_factory=lambda: _id("artifact"))
    uri: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    media_type: str

    @classmethod
    def from_bytes(cls, content: bytes, media_type: str) -> ArtifactRef:
        digest = hashlib.sha256(content).hexdigest()
        return cls(
            uri=f"artifact://sha256/{digest}",
            content_hash=f"sha256:{digest}",
            size_bytes=len(content),
            media_type=media_type,
        )


class GoalContract(Contract):
    goal_id: str = Field(default_factory=lambda: _id("goal"))
    objective: str = Field(min_length=1)
    non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(min_length=1)
    repositories: list[str] = Field(default_factory=list)
    planning_surface: Literal["github", "google_drive", "local"] = "github"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContextItem(Contract):
    """Model-visible context with reconstructable provenance."""

    summary: str = Field(min_length=1)
    provenance_type: Literal["event", "memory", "skill", "source", "artifact"]
    provenance_id: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^sha256:")


class TaskContract(Contract):
    task_id: str = Field(default_factory=lambda: _id("task"))
    goal_id: str = Field(min_length=1)
    worker_role: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    context_items: list[ContextItem] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    evaluator: str | None = None
    limits: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_self_dependency(self) -> TaskContract:
        if self.task_id in self.dependencies:
            raise ValueError("task cannot depend on itself")
        return self


class WorkerResult(Contract):
    task_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    summary: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    measurements: dict[str, float] = Field(default_factory=dict)
    tests: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    memory_candidates: list[str] = Field(default_factory=list)
    skill_candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def explain_failure(self) -> WorkerResult:
        if self.status in {"failed", "timed_out"} and not self.failures:
            raise ValueError("failed or timed-out result requires failures")
        return self


class EvaluationResult(Contract):
    evaluation_id: str = Field(default_factory=lambda: _id("eval"))
    candidate_id: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    metrics: dict[str, float] = Field(min_length=1)
    regressions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    verdict: Literal["adopt", "reject", "conditional"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class ApprovalRequest(Contract):
    approval_id: str = Field(default_factory=lambda: _id("approval"))
    run_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    targets: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    command_hash: str = Field(pattern=r"^sha256:")
    expires_at: datetime
    approved_at: datetime | None = None
    denied_at: datetime | None = None

    def is_valid(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return self.denied_at is None and current < self.expires_at


class ComponentKind(StrEnum):
    SUPERVISOR = "supervisor"
    WORKER = "worker"
    RUNTIME = "runtime"
    TOOL = "tool"
    MEMORY = "memory"
    SKILL = "skill"
    EVALUATOR = "evaluator"
    INTERFACE = "interface"
    PROJECT_STORE = "project_store"


class RunEvent(Contract):
    event_id: str = Field(default_factory=lambda: _id("evt"))
    event_type: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    goal_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str | None = None
    trial_id: str | None = None
    worker_id: str | None = None
    component_kind: ComponentKind
    component_name: str = Field(min_length=1)
    component_version: str = "dev"
    operation: str = Field(min_length=1)
    actor_id: str | None = None
    recipient_id: str | None = None
    input_ref: ArtifactRef | None = None
    output_ref: ArtifactRef | None = None
    memory_ids: list[str] = Field(default_factory=list)
    skill_versions: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    status: Literal["running", "ok", "failed", "cancelled", "timed_out"]
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def event_status_matches_type(self) -> RunEvent:
        expected = {
            "component.call.started": "running",
            "component.call.completed": "ok",
            "component.call.failed": "failed",
            "component.call.cancelled": "cancelled",
            "component.call.timed_out": "timed_out",
        }.get(self.event_type)
        if expected and self.status != expected:
            raise ValueError(f"{self.event_type} requires status={expected}")
        return self
