"""Thin headless adapter for the Codex CLI (``codex exec``).

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

RUNTIME_NAME = "codex"
DEFAULT_EXECUTABLE = "codex"

# Credentials/config the CLI itself needs to run headlessly. Nothing else is
# ever forwarded from the caller's environment.
DEFAULT_ALLOWED_ENV_VARS: frozenset[str] = frozenset({"HOME", "OPENAI_API_KEY", "CODEX_HOME"})

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


def build_codex_command(
    task: TaskContract,
    workspace: Workspace,
    *,
    executable: str = DEFAULT_EXECUTABLE,
    model: str | None = None,
) -> list[str]:
    """Build an explicit ``codex exec`` argv; never shells out or interpolates.

    ``--sandbox workspace-write`` is passed explicitly so the safe default is
    never left implicit. The dangerous approval-bypass flag
    (``--dangerously-bypass-approvals-and-sandbox`` / ``--yolo``) is never added.
    """
    del workspace  # Placement is carried by subprocess cwd, not the command.
    command = [executable, "exec", "--json", "--sandbox", "workspace-write"]
    if model:
        command += ["--model", model]
    command.append("--")
    command.append(task.objective)
    return command


class CodexAdapter(SubprocessRuntimeAdapter):
    """Headless Codex adapter: ``codex exec --json --sandbox workspace-write <objective>``.

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
        return build_codex_command(task, workspace, executable=self.executable, model=self.model)

    def _parse_structured_result(self, stdout: bytes) -> Any:
        """Normalize Codex's JSONL event stream into one runtime result."""
        shared_result = super()._parse_structured_result(stdout)
        if not isinstance(shared_result, RuntimeDiagnostic):
            return shared_result
        try:
            events = [
                json.loads(line)
                for line in stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
        except (UnicodeDecodeError, json.JSONDecodeError):
            return super()._parse_structured_result(stdout)
        if not events:
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="Codex produced no JSONL events",
            )
        messages: list[str] = []
        session_id = None
        for event in events:
            if not isinstance(event, dict):
                continue
            session_id = session_id or event.get("thread_id") or event.get("session_id")
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") in {"agent_message", "message"}:
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    messages.append(text)
            elif event.get("type") in {"agent_message", "message"}:
                text = event.get("text") or event.get("message")
                if isinstance(text, str):
                    messages.append(text)
        if not messages:
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="Codex JSONL contained no agent message",
            )
        return RuntimeStatus.COMPLETED, messages[-1], {
            "provider_event_count": len(events),
            "session_id": session_id,
        }
