"""Validated, provider-neutral contracts at the runtime boundary.

These models intentionally represent durable references and safe summaries,
never executable command text, inherited environments, or provider secrets.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentic_os.core.contracts import ArtifactRef
from agentic_os.core.redaction import SECRET_PATTERNS


class RuntimeContract(BaseModel):
    """Immutable, strict base for values exchanged with runtime adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1"

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def reject_secret_values(cls, value: Any) -> Any:
        if _contains_secret(value):
            raise ValueError("runtime contracts may not contain secret values")
        return value


class RuntimeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"


class WorkspaceWritePolicy(StrEnum):
    READ_ONLY = "read_only"
    ISOLATED_WRITE = "isolated_write"


class Workspace(RuntimeContract):
    """A resolved directory the caller has explicitly approved for a runtime."""

    root: Path
    allow_write: bool
    approved_root: Path | None = None
    write_policy: WorkspaceWritePolicy | None = None
    workspace_id: str | None = None

    @model_validator(mode="after")
    def validate_workspace(self) -> Workspace:
        if not self.root.is_absolute():
            raise ValueError("workspace root must be an absolute path")
        if not self.root.exists() or not self.root.is_dir():
            raise ValueError("workspace root must be an existing directory")
        resolved_root = self.root.resolve(strict=True)
        if resolved_root == Path(resolved_root.anchor):
            raise ValueError("workspace root may not be the filesystem root")

        if self.approved_root is None:
            resolved_boundary = resolved_root
        else:
            if not self.approved_root.is_absolute():
                raise ValueError("approved workspace boundary must be an absolute path")
            if not self.approved_root.exists() or not self.approved_root.is_dir():
                raise ValueError("approved workspace boundary must be an existing directory")
            resolved_boundary = self.approved_root.resolve(strict=True)
            if resolved_boundary == Path(resolved_boundary.anchor):
                raise ValueError("approved workspace boundary may not be the filesystem root")
            if not resolved_root.is_relative_to(resolved_boundary):
                raise ValueError("workspace root escapes the approved workspace boundary")

        expected_policy = (
            WorkspaceWritePolicy.ISOLATED_WRITE
            if self.allow_write
            else WorkspaceWritePolicy.READ_ONLY
        )
        if self.write_policy is not None and self.write_policy != expected_policy:
            raise ValueError("workspace write policy must match allow_write")

        root_digest = hashlib.sha256(str(resolved_root).encode()).hexdigest()
        workspace_id = self.workspace_id or f"workspace_{root_digest[:16]}"
        object.__setattr__(self, "root", resolved_root)
        object.__setattr__(self, "approved_root", resolved_boundary)
        object.__setattr__(self, "write_policy", expected_policy)
        object.__setattr__(self, "workspace_id", workspace_id)
        return self


class RuntimeCapability(StrEnum):
    EXECUTE = "execute"
    STREAM_EVENTS = "stream_events"
    STEER = "steer"
    SESSION_CONTINUATION = "session_continuation"
    READ_ONLY_WORKSPACE = "read_only_workspace"
    ISOLATED_WRITE_WORKSPACE = "isolated_write_workspace"
    STRUCTURED_RESULT = "structured_result"


class RuntimeCapabilities(RuntimeContract):
    supported: frozenset[RuntimeCapability] = Field(default_factory=frozenset)


class RuntimeEventType(StrEnum):
    STARTED = "started"
    STDOUT = "stdout"
    STDERR = "stderr"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RuntimeHandle(RuntimeContract):
    handle_id: str = Field(default_factory=lambda: f"runtime_{uuid4().hex}")
    runtime_name: str = Field(min_length=1)
    status: RuntimeStatus = RuntimeStatus.RUNNING
    session_id: str | None = None
    workspace_id: str | None = None


class RuntimeDiagnostic(RuntimeContract):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifact_ref: ArtifactRef | None = None


class RuntimeEvent(RuntimeContract):
    handle_id: str = Field(min_length=1)
    event_type: RuntimeEventType
    status: RuntimeStatus
    summary: str | None = None
    artifact_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def terminal_status_matches_type(self) -> RuntimeEvent:
        expected = {
            RuntimeEventType.STARTED: RuntimeStatus.RUNNING,
            RuntimeEventType.COMPLETED: RuntimeStatus.COMPLETED,
            RuntimeEventType.FAILED: RuntimeStatus.FAILED,
            RuntimeEventType.CANCELLED: RuntimeStatus.CANCELLED,
            RuntimeEventType.TIMED_OUT: RuntimeStatus.TIMED_OUT,
        }.get(self.event_type)
        if expected is not None and self.status != expected:
            raise ValueError(f"{self.event_type} requires status={expected}")
        return self


class AvailabilityFailureCode(StrEnum):
    MISSING = "missing"
    AUTH_UNKNOWN = "auth_unknown"
    UNAUTHENTICATED = "unauthenticated"
    INCOMPATIBLE = "incompatible"
    PROBE_FAILED = "probe_failed"


class RuntimeAvailabilityFailure(RuntimeContract):
    code: AvailabilityFailureCode
    message: str = Field(min_length=1)
    diagnostic: str | None = None


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class RuntimeAvailabilityResult(RuntimeContract):
    runtime_name: str = Field(min_length=1)
    status: AvailabilityStatus
    available: bool
    version: str | None = None
    capabilities: RuntimeCapabilities = Field(default_factory=RuntimeCapabilities)
    failure: RuntimeAvailabilityFailure | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> RuntimeAvailabilityResult:
        if self.status == AvailabilityStatus.AVAILABLE:
            if not self.available or self.failure is not None:
                raise ValueError("available runtime may not carry an availability failure")
        elif self.available or self.failure is None:
            raise ValueError("unavailable runtime requires a typed failure")
        return self


class RuntimeTraceFields(RuntimeContract):
    """Safe trace metadata: command identity is a fingerprint, never text."""

    runtime_name: str = Field(min_length=1)
    runtime_version: str | None = None
    cli_version: str | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    session_id: str | None = None
    workspace_id: str = Field(min_length=1)
    command_fingerprint: str | None = Field(default=None, pattern=r"^sha256:[a-zA-Z0-9_-]+$")
    selected_runtime: str = Field(min_length=1)
    fallback_rationale: str | None = None


class RuntimeExecutionResult(RuntimeContract):
    """One terminal runtime outcome with replayable artifact references."""

    handle: RuntimeHandle
    status: RuntimeStatus
    summary: str = ""
    output_ref: ArtifactRef | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()
    trace: RuntimeTraceFields | None = None
    result_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def terminal_result_has_required_diagnostics(self) -> RuntimeExecutionResult:
        if self.status == RuntimeStatus.RUNNING:
            raise ValueError("runtime execution result must be terminal")
        if self.status in {
            RuntimeStatus.FAILED,
            RuntimeStatus.TIMED_OUT,
            RuntimeStatus.UNAVAILABLE,
        } and not self.diagnostics:
            raise ValueError("failed, timed-out, or unavailable result requires diagnostics")
        return self


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_secret(key) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    return False
