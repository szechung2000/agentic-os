"""Typed runtime boundary contracts — RED before adapter implementation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_os.core.contracts import ArtifactRef
from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeDiagnostic,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeStatus,
    RuntimeTraceFields,
    Workspace,
)


def test_workspace_requires_existing_absolute_non_root_path_within_boundary(tmp_path):
    approved = tmp_path / "approved"
    root = approved / "runtime-workspace"
    root.mkdir(parents=True)

    workspace = Workspace(root=root, allow_write=True, approved_root=approved)

    assert workspace.root == root.resolve()
    assert workspace.allow_write
    with pytest.raises(ValidationError):
        Workspace(root=Path("relative"), allow_write=False)
    with pytest.raises(ValidationError):
        Workspace(root=Path("/"), allow_write=False)
    with pytest.raises(ValidationError):
        Workspace(root=tmp_path, allow_write=False, approved_root=approved)


def test_workspace_rejects_symlink_escape(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    escaped = tmp_path / "outside"
    escaped.mkdir()
    (approved / "escaped").symlink_to(escaped, target_is_directory=True)

    with pytest.raises(ValidationError, match="approved workspace boundary"):
        Workspace(root=approved / "escaped", allow_write=False, approved_root=approved)


def test_runtime_result_requires_diagnostics_for_failed_or_timed_out_results():
    handle = RuntimeHandle(runtime_name="codex")
    with pytest.raises(ValidationError):
        RuntimeExecutionResult(handle=handle, status=RuntimeStatus.TIMED_OUT)

    partial = ArtifactRef.from_bytes(b"partial", "text/plain")
    result = RuntimeExecutionResult(
        handle=handle,
        status=RuntimeStatus.TIMED_OUT,
        diagnostics=[RuntimeDiagnostic(code="deadline", message="process timed out")],
        artifacts=[partial],
    )
    assert result.artifacts == (partial,)


def test_trace_fields_only_admit_safe_fingerprinted_command_metadata():
    trace = RuntimeTraceFields(
        runtime_name="codex",
        cli_version="1.2.3",
        requested_model="o3",
        effective_model="o3",
        session_id="session_1",
        workspace_id="workspace_1",
        command_fingerprint="sha256:abcd1234",
        selected_runtime="codex",
        fallback_rationale="preferred runtime available",
    )
    assert "command" not in trace.model_dump(exclude_none=True)

    with pytest.raises(ValidationError):
        RuntimeTraceFields(
            runtime_name="codex",
            workspace_id="workspace_1",
            selected_runtime="codex",
            command_fingerprint="codex exec --api-key=secret",
        )


def test_capabilities_and_availability_are_typed_and_immutable():
    capabilities = RuntimeCapabilities(
        supported=[RuntimeCapability.EXECUTE, RuntimeCapability.STREAM_EVENTS]
    )
    assert RuntimeCapability.EXECUTE in capabilities.supported
    with pytest.raises(ValidationError):
        RuntimeAvailabilityResult(
            runtime_name="claude", status="unavailable", available=True
        )

    result = RuntimeAvailabilityResult(
        runtime_name="claude",
        status="unavailable",
        available=False,
        failure=RuntimeAvailabilityFailure(
            code=AvailabilityFailureCode.MISSING, message="binary not found"
        ),
    )
    assert result.failure.code is AvailabilityFailureCode.MISSING
