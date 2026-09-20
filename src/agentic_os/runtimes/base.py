"""Provider-neutral asynchronous subprocess lifecycle for runtime adapters.

``SubprocessRuntimeAdapter`` deliberately does not know how to construct a
provider command.  A thin provider adapter supplies ``command_builder`` and
declares only workspace capabilities it can actually enforce.  The common
base owns process lifetime, output capture, result parsing, and termination.

The default structured stdout envelope is exactly one JSON object::

    {"status": "completed", "summary": "short safe summary", "result": {...}}

``status`` is required and must be a terminal ``RuntimeStatus``.  ``result``
is optional but, when present, must be a JSON object.  A zero exit status with
missing or malformed structured output is a failed execution; the adapter
never infers success from an exit code alone.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract
from agentic_os.core.redaction import redact_text, redact_value
from agentic_os.runtimes.contracts import (
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeDiagnostic,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeStatus,
    Workspace,
)

type Command = Sequence[str]
type CommandBuilder = Callable[[TaskContract, Workspace], Command | Awaitable[Command]]

_TERMINAL_STATUSES = frozenset(
    {
        RuntimeStatus.COMPLETED,
        RuntimeStatus.FAILED,
        RuntimeStatus.CANCELLED,
        RuntimeStatus.TIMED_OUT,
        RuntimeStatus.UNAVAILABLE,
    }
)
_DEFAULT_CAPABILITIES = frozenset(
    {
        RuntimeCapability.EXECUTE,
        RuntimeCapability.STREAM_EVENTS,
        RuntimeCapability.STRUCTURED_RESULT,
    }
)


class RuntimeLifecycleError(RuntimeError):
    """Raised when a handle does not belong to this adapter or is invalid."""


class WorkspacePolicyError(RuntimeLifecycleError):
    """Raised before process creation when an adapter cannot enforce a workspace policy."""


class UnsupportedSteeringError(RuntimeLifecycleError):
    """Raised when the runtime has no explicit steering capability."""


@runtime_checkable
class RuntimeAdapter(Protocol):
    """The provider-neutral lifecycle consumed by future routing code."""

    async def start(self, task: TaskContract, workspace: Workspace) -> RuntimeHandle: ...

    async def events(self, handle: RuntimeHandle) -> AsyncIterator[RuntimeEvent]: ...

    async def result(self, handle: RuntimeHandle) -> RuntimeExecutionResult: ...

    async def steer(self, handle: RuntimeHandle, message: str) -> None: ...

    async def stop(self, handle: RuntimeHandle) -> RuntimeExecutionResult: ...


@dataclass
class _RunState:
    handle: RuntimeHandle
    process: asyncio.subprocess.Process
    timeout_seconds: float | None
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    events: list[RuntimeEvent] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    complete: asyncio.Event = field(default_factory=asyncio.Event)
    termination_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_requested: bool = False
    timed_out: bool = False
    output_truncated: bool = False
    completion_task: asyncio.Task[RuntimeExecutionResult] | None = None
    terminal_result: RuntimeExecutionResult | None = None


class SubprocessRuntimeAdapter:
    """Own an async subprocess and expose a safe, idempotent runtime lifecycle.

    ``capabilities`` is a security declaration, not a preference: the caller's
    selected workspace policy must be present or ``start`` fails before the
    command builder runs.  Provider adapters must only declare the read-only
    and isolated-write capabilities when their sandbox or OS integration
    enforces those properties; setting ``cwd`` alone is not an enforcement
    mechanism.
    """

    def __init__(
        self,
        *,
        runtime_name: str,
        artifacts: ArtifactStore,
        command_builder: CommandBuilder,
        capabilities: RuntimeCapabilities | None = None,
        timeout_seconds: float | None = None,
        termination_grace_seconds: float = 1.0,
        max_output_bytes: int = 10 * 1024 * 1024,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not runtime_name:
            raise ValueError("runtime_name must not be empty")
        self.runtime_name = runtime_name
        self.artifacts = artifacts
        self.command_builder = command_builder
        self.capabilities = capabilities or RuntimeCapabilities(supported=_DEFAULT_CAPABILITIES)
        self.timeout_seconds = self._validate_timeout(timeout_seconds)
        if not math.isfinite(termination_grace_seconds) or termination_grace_seconds < 0:
            raise ValueError("termination_grace_seconds must be finite and non-negative")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self.termination_grace_seconds = termination_grace_seconds
        self.max_output_bytes = max_output_bytes
        # Do not inherit a process-wide environment, which may contain secrets.
        self.environment = dict(environment) if environment is not None else {"PATH": os.defpath}
        self._runs: dict[str, _RunState] = {}

    async def start(self, task: TaskContract, workspace: Workspace) -> RuntimeHandle:
        """Validate policy, create a process group, and return a running handle."""
        validated_workspace = self._validate_workspace(workspace)
        command = await self._build_command(task, validated_workspace)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(validated_workspace.root),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.environment,
            **self._process_group_options(),
        )
        handle = RuntimeHandle(
            runtime_name=self.runtime_name,
            workspace_id=validated_workspace.workspace_id,
        )
        state = _RunState(
            handle=handle,
            process=process,
            timeout_seconds=self._timeout_for(task),
        )
        self._runs[handle.handle_id] = state
        self._emit(
            state, RuntimeEventType.STARTED, RuntimeStatus.RUNNING, "runtime process started"
        )
        state.completion_task = asyncio.create_task(
            self._monitor(state), name=f"runtime-monitor-{handle.handle_id}"
        )
        return handle

    async def events(self, handle: RuntimeHandle) -> AsyncIterator[RuntimeEvent]:
        """Replay known events then await new ones through the terminal event."""
        state = self._state_for(handle)
        index = 0
        while True:
            while index < len(state.events):
                event = state.events[index]
                index += 1
                yield event
            if state.complete.is_set():
                return
            await state.changed.wait()
            state.changed.clear()

    async def result(self, handle: RuntimeHandle) -> RuntimeExecutionResult:
        """Wait for and return the one terminal result for ``handle``.

        If a caller cancels its own result wait, the owned subprocess is also
        stopped.  The cancellation is then propagated to the caller.
        """
        state = self._state_for(handle)
        assert state.completion_task is not None
        try:
            return await asyncio.shield(state.completion_task)
        except asyncio.CancelledError:
            await self._terminate(state, timed_out=False)
            raise

    async def steer(self, handle: RuntimeHandle, message: str) -> None:
        """Fail explicitly unless a subclass implements a supported channel."""
        self._state_for(handle)
        if RuntimeCapability.STEER not in self.capabilities.supported:
            raise UnsupportedSteeringError(f"{self.runtime_name} does not support steering")
        await self._steer(handle, message)

    async def stop(self, handle: RuntimeHandle) -> RuntimeExecutionResult:
        """Cancel a running process and return its terminal, idempotent result."""
        state = self._state_for(handle)
        if not state.complete.is_set():
            # Do not let cancellation of the caller interrupt the SIGTERM ->
            # grace period -> SIGKILL -> wait cleanup sequence.
            await asyncio.shield(self._terminate(state, timed_out=False))
        return await self.result(handle)

    async def _steer(self, handle: RuntimeHandle, message: str) -> None:
        del handle, message
        raise UnsupportedSteeringError(f"{self.runtime_name} has no steering implementation")

    def _validate_workspace(self, workspace: Workspace) -> Workspace:
        # Reconstructing the model closes a path/symlink race between the
        # caller's validation and child-process creation.
        validated = Workspace(
            root=workspace.root,
            allow_write=workspace.allow_write,
            approved_root=workspace.approved_root,
            write_policy=workspace.write_policy,
            workspace_id=workspace.workspace_id,
        )
        required_capability = (
            RuntimeCapability.ISOLATED_WRITE_WORKSPACE
            if validated.allow_write
            else RuntimeCapability.READ_ONLY_WORKSPACE
        )
        if required_capability not in self.capabilities.supported:
            raise WorkspacePolicyError(
                f"{self.runtime_name} cannot enforce "
                f"{validated.write_policy.value} workspace policy"
            )
        return validated

    async def _build_command(self, task: TaskContract, workspace: Workspace) -> tuple[str, ...]:
        command = self.command_builder(task, workspace)
        if inspect.isawaitable(command):
            command = await command
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise ValueError("command_builder must return a sequence of executable arguments")
        normalized = tuple(command)
        if not normalized or any(
            not isinstance(argument, str) or not argument for argument in normalized
        ):
            raise ValueError("command_builder returned an invalid command")
        return normalized

    def _timeout_for(self, task: TaskContract) -> float | None:
        task_timeout = task.limits.get("timeout_seconds", self.timeout_seconds)
        return self._validate_timeout(task_timeout)

    @staticmethod
    def _validate_timeout(value: int | float | None) -> float | None:
        if value is None:
            return None
        timeout = float(value)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        return timeout

    @staticmethod
    def _process_group_options() -> dict[str, bool | int]:
        if os.name == "posix":
            return {"start_new_session": True}
        if os.name == "nt":  # pragma: no cover - exercised on Windows.
            return {"creationflags": subprocess_creationflags()}
        return {}

    async def _monitor(self, state: _RunState) -> RuntimeExecutionResult:
        assert state.process.stdout is not None
        assert state.process.stderr is not None
        stdout_reader = asyncio.create_task(
            self._read_stream(state, state.process.stdout, state.stdout)
        )
        stderr_reader = asyncio.create_task(
            self._read_stream(state, state.process.stderr, state.stderr)
        )
        try:
            if state.timeout_seconds is None:
                await state.process.wait()
            else:
                await asyncio.wait_for(state.process.wait(), timeout=state.timeout_seconds)
        except TimeoutError:
            await self._terminate(state, timed_out=True)
        finally:
            await asyncio.gather(stdout_reader, stderr_reader)

        result = self._make_result(state)
        state.terminal_result = result
        state.complete.set()
        self._emit(state, self._terminal_event_type(result.status), result.status, result.summary)
        return result

    async def _read_stream(
        self,
        state: _RunState,
        stream: asyncio.StreamReader,
        captured: bytearray,
    ) -> None:
        event_type = (
            RuntimeEventType.STDOUT if captured is state.stdout else RuntimeEventType.STDERR
        )
        while chunk := await stream.read(64 * 1024):
            remaining = self.max_output_bytes - len(captured)
            if remaining > 0:
                captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                state.output_truncated = True
            self._emit(
                state,
                event_type,
                RuntimeStatus.RUNNING,
                redact_text(chunk.decode("utf-8", errors="replace")),
            )

    async def _terminate(self, state: _RunState, *, timed_out: bool) -> None:
        async with state.termination_lock:
            if state.complete.is_set() or state.process.returncode is not None:
                return
            state.timed_out = state.timed_out or timed_out
            state.stop_requested = state.stop_requested or not timed_out
            self._send_group_signal(state.process, signal.SIGTERM)
            # A process leader may exit before descendants.  Wait the full
            # grace period, then test and force-kill the original process group.
            await asyncio.sleep(self.termination_grace_seconds)
            if self._process_group_exists(state.process):
                self._send_group_signal(state.process, signal.SIGKILL)
            await state.process.wait()

    @staticmethod
    def _send_group_signal(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                return
        else:  # pragma: no cover - Windows fallback has no POSIX process group.
            if process.returncode is not None:
                return
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                return

    @staticmethod
    def _process_group_exists(process: asyncio.subprocess.Process) -> bool:
        if os.name != "posix":  # pragma: no cover - Windows fallback.
            return process.returncode is None
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _make_result(self, state: _RunState) -> RuntimeExecutionResult:
        stdout_ref = self.artifacts.put(bytes(state.stdout), "text/plain; charset=utf-8")
        stderr_ref = self.artifacts.put(bytes(state.stderr), "text/plain; charset=utf-8")
        artifacts = (stdout_ref, stderr_ref)
        diagnostics: list[RuntimeDiagnostic] = []
        if state.output_truncated:
            diagnostics.append(
                RuntimeDiagnostic(
                    code="output_truncated",
                    message="runtime output exceeded the configured capture limit",
                )
            )
        if state.timed_out:
            diagnostics.append(
                RuntimeDiagnostic(
                    code="timeout",
                    message="runtime exceeded its execution deadline",
                    artifact_ref=stdout_ref,
                )
            )
            return self._terminal_result(
                state,
                RuntimeStatus.TIMED_OUT,
                "runtime timed out",
                stdout_ref,
                artifacts,
                diagnostics,
            )
        if state.stop_requested:
            diagnostics.append(
                RuntimeDiagnostic(
                    code="cancelled",
                    message="runtime was stopped before completion",
                    artifact_ref=stdout_ref,
                )
            )
            return self._terminal_result(
                state,
                RuntimeStatus.CANCELLED,
                "runtime cancelled",
                stdout_ref,
                artifacts,
                diagnostics,
            )
        if state.process.returncode != 0:
            diagnostics.append(
                RuntimeDiagnostic(
                    code="exit_code",
                    message=f"runtime exited with code {state.process.returncode}",
                    artifact_ref=stderr_ref,
                )
            )
            return self._terminal_result(
                state,
                RuntimeStatus.FAILED,
                "runtime process failed",
                stdout_ref,
                artifacts,
                diagnostics,
            )

        parsed = self._parse_structured_result(bytes(state.stdout))
        if isinstance(parsed, RuntimeDiagnostic):
            diagnostics.append(parsed.model_copy(update={"artifact_ref": stdout_ref}))
            return self._terminal_result(
                state,
                RuntimeStatus.FAILED,
                "runtime produced no valid structured result",
                stdout_ref,
                artifacts,
                diagnostics,
            )
        status, summary, result_data = parsed
        if status != RuntimeStatus.COMPLETED:
            diagnostics.append(
                RuntimeDiagnostic(
                    code="structured_status",
                    message=f"runtime reported terminal status {status.value}",
                    artifact_ref=stdout_ref,
                )
            )
        return self._terminal_result(
            state, status, summary, stdout_ref, artifacts, diagnostics, result_data=result_data
        )

    def _parse_structured_result(
        self, stdout: bytes
    ) -> tuple[RuntimeStatus, str, dict[str, object]] | RuntimeDiagnostic:
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="stdout did not contain the required JSON result envelope",
            )
        if not isinstance(payload, dict):
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="structured result envelope must be a JSON object",
            )
        try:
            status = RuntimeStatus(payload["status"])
        except (KeyError, ValueError, TypeError):
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="structured result envelope requires a terminal status",
            )
        if status not in _TERMINAL_STATUSES:
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="structured result status must be terminal",
            )
        if status is RuntimeStatus.UNAVAILABLE:
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="a started runtime may not report unavailable",
            )
        summary = payload.get("summary", "")
        result_data = payload.get("result", {})
        if not isinstance(summary, str) or not isinstance(result_data, dict):
            return RuntimeDiagnostic(
                code="structured_result_invalid",
                message="structured result summary and result fields have invalid types",
            )
        return status, redact_text(summary), redact_value(result_data)

    def _terminal_result(
        self,
        state: _RunState,
        status: RuntimeStatus,
        summary: str,
        output_ref,
        artifacts,
        diagnostics: list[RuntimeDiagnostic],
        *,
        result_data: dict[str, object] | None = None,
    ) -> RuntimeExecutionResult:
        # RuntimeExecutionResult requires a diagnostic for every failed,
        # timed-out, and unavailable outcome.  The statuses above all append
        # one before reaching here.
        return RuntimeExecutionResult(
            handle=state.handle.model_copy(update={"status": status}),
            status=status,
            summary=redact_text(summary),
            output_ref=output_ref,
            artifacts=artifacts,
            diagnostics=tuple(diagnostics),
            result_data=result_data or {},
        )

    def _emit(
        self,
        state: _RunState,
        event_type: RuntimeEventType,
        status: RuntimeStatus,
        summary: str,
    ) -> None:
        state.events.append(
            RuntimeEvent(
                handle_id=state.handle.handle_id,
                event_type=event_type,
                status=status,
                summary=redact_text(summary),
            )
        )
        state.changed.set()

    def _state_for(self, handle: RuntimeHandle) -> _RunState:
        try:
            state = self._runs[handle.handle_id]
        except KeyError as error:
            raise RuntimeLifecycleError("runtime handle is not owned by this adapter") from error
        if handle.runtime_name != self.runtime_name:
            raise RuntimeLifecycleError("runtime handle belongs to a different runtime")
        return state

    @staticmethod
    def _terminal_event_type(status: RuntimeStatus) -> RuntimeEventType:
        return {
            RuntimeStatus.COMPLETED: RuntimeEventType.COMPLETED,
            RuntimeStatus.FAILED: RuntimeEventType.FAILED,
            RuntimeStatus.CANCELLED: RuntimeEventType.CANCELLED,
            RuntimeStatus.TIMED_OUT: RuntimeEventType.TIMED_OUT,
            RuntimeStatus.UNAVAILABLE: RuntimeEventType.FAILED,
        }[status]


def build_allowlisted_environment(
    allowed_names: Iterable[str],
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a child-process environment from an explicit name allowlist.

    ``source`` defaults to ``os.environ`` but is never copied wholesale: only
    ``PATH`` (needed to locate the executable) and names in ``allowed_names``
    are forwarded.  Provider adapters use this to keep unrelated secrets in
    the caller's environment out of the child process, traces, and artifacts.
    """
    src = os.environ if source is None else source
    environment = {"PATH": src.get("PATH", os.defpath)}
    for name in allowed_names:
        if name == "PATH":
            continue
        if name in src:
            environment[name] = src[name]
    return environment


def subprocess_creationflags() -> int:
    """Keep the Windows-only constant out of module import on POSIX."""
    import subprocess

    return subprocess.CREATE_NEW_PROCESS_GROUP


# A descriptive alias for callers that prefer the lifecycle-oriented name.
ManagedSubprocessRuntimeAdapter = SubprocessRuntimeAdapter
