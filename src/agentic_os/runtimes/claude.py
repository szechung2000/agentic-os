"""Thin headless adapter for the Claude Code CLI (``claude -p``).

Command construction is a pure function so it is testable without spawning a
process.  The subprocess lifecycle (capture, timeout, cancellation, result
parsing) lives entirely in :mod:`agentic_os.runtimes.base`.
"""

from __future__ import annotations

import json
from typing import Any

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract
from agentic_os.runtimes.base import SubprocessRuntimeAdapter, build_allowlisted_environment
from agentic_os.runtimes.contracts import (
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeDiagnostic,
    RuntimeStatus,
    Workspace,
)

RUNTIME_NAME = "claude"
DEFAULT_EXECUTABLE = "claude"

# Credentials/config the CLI itself needs to run headlessly. Nothing else is
# ever forwarded from the caller's environment.
DEFAULT_ALLOWED_ENV_VARS: frozenset[str] = frozenset(
    {"HOME", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"}
)

# cwd-pinning (enforced by the base adapter) is the only isolation mechanism
# this adapter provides; it cannot guarantee a read-only sandbox, so it only
# claims the write-capable workspace capability.
CAPABILITIES = RuntimeCapabilities(
    supported=frozenset(
        {
            RuntimeCapability.EXECUTE,
            RuntimeCapability.STREAM_EVENTS,
            RuntimeCapability.STRUCTURED_RESULT,
            RuntimeCapability.ISOLATED_WRITE_WORKSPACE,
        }
    )
)


def build_claude_command(
    task: TaskContract,
    workspace: Workspace,
    *,
    executable: str = DEFAULT_EXECUTABLE,
    model: str | None = None,
) -> list[str]:
    """Build an explicit ``claude -p`` argv; never shells out or interpolates."""
    del workspace  # Placement is carried by subprocess cwd, not the command.
    command = [executable, "-p", "--output-format", "json"]
    if model:
        command += ["--model", model]
    command += ["--", task.objective]
    return command


class ClaudeCodeAdapter(SubprocessRuntimeAdapter):
    """Headless Claude Code adapter: ``claude -p <objective> --output-format json``.

    Steering and session continuation are not implemented, so neither
    capability is declared; callers get an explicit
    :class:`~agentic_os.runtimes.base.UnsupportedSteeringError` rather than a
    silently ignored request.
    """

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        model: str | None = None,
        executable: str = DEFAULT_EXECUTABLE,
        allowed_env_vars: frozenset[str] = DEFAULT_ALLOWED_ENV_VARS,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        termination_grace_seconds: float = 1.0,
    ) -> None:
        self.model = model
        self.executable = executable
        super().__init__(
            runtime_name=RUNTIME_NAME,
            artifacts=artifacts,
            command_builder=self._build_argv,
            capabilities=CAPABILITIES,
            timeout_seconds=timeout_seconds,
            termination_grace_seconds=termination_grace_seconds,
            environment=build_allowlisted_environment(allowed_env_vars, source=env),
        )

    def _build_argv(self, task: TaskContract, workspace: Workspace) -> list[str]:
        return build_claude_command(
            task, workspace, executable=self.executable, model=self.model
        )

    def _parse_structured_result(self, stdout: bytes) -> Any:
        """Normalize Claude's result envelope into the shared runtime shape."""
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return super()._parse_structured_result(stdout)
        if not isinstance(payload, dict) or payload.get("type") != "result":
            return super()._parse_structured_result(stdout)
        if payload.get("is_error") or payload.get("subtype") != "success":
            return RuntimeDiagnostic(
                code="provider_error",
                message="Claude reported an unsuccessful result",
            )
        response = payload.get("result", "")
        if not isinstance(response, str):
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="Claude result field was not text",
            )
        return RuntimeStatus.COMPLETED, response, {
            "provider_result_type": payload.get("type"),
            "provider_subtype": payload.get("subtype"),
            "session_id": payload.get("session_id"),
        }
