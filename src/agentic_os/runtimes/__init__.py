"""Provider-neutral runtime contracts.

Importing this package has no CLI or subprocess side effects.
"""

from agentic_os.runtimes.agy import AgyAdapter, build_agy_command
from agentic_os.runtimes.base import (
    ManagedSubprocessRuntimeAdapter,
    RuntimeAdapter,
    RuntimeLifecycleError,
    SubprocessRuntimeAdapter,
    UnsupportedSteeringError,
    WorkspacePolicyError,
    build_allowlisted_environment,
)
from agentic_os.runtimes.claude import ClaudeCodeAdapter, build_claude_command
from agentic_os.runtimes.codex import CodexAdapter, build_codex_command
from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    AvailabilityStatus,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeDiagnostic,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeStatus,
    RuntimeTraceFields,
    Workspace,
    WorkspaceWritePolicy,
)
from agentic_os.runtimes.discovery import RuntimeDiscovery, RuntimeProbeOutput, RuntimeProbeSpec
from agentic_os.runtimes.routing import (
    PreStartRouteDecision,
    PreStartRouteResult,
    RouteFailureCode,
    RuntimeRouteAttempt,
    RuntimeRouteFailure,
    RuntimeRouter,
    StartedRuntime,
)
from agentic_os.runtimes.worker_bridge import RuntimeWorkerBridge

__all__ = [
    "AgyAdapter",
    "build_agy_command",
    "ClaudeCodeAdapter",
    "build_claude_command",
    "CodexAdapter",
    "build_codex_command",
    "ManagedSubprocessRuntimeAdapter",
    "RuntimeAdapter",
    "RuntimeLifecycleError",
    "SubprocessRuntimeAdapter",
    "UnsupportedSteeringError",
    "WorkspacePolicyError",
    "build_allowlisted_environment",
    "AvailabilityFailureCode",
    "AvailabilityStatus",
    "RuntimeAvailabilityFailure",
    "RuntimeAvailabilityResult",
    "RuntimeCapabilities",
    "RuntimeCapability",
    "RuntimeDiagnostic",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeExecutionResult",
    "RuntimeHandle",
    "RuntimeStatus",
    "RuntimeTraceFields",
    "Workspace",
    "WorkspaceWritePolicy",
    "RuntimeDiscovery",
    "RuntimeProbeOutput",
    "RuntimeProbeSpec",
    "PreStartRouteDecision",
    "PreStartRouteResult",
    "RouteFailureCode",
    "RuntimeRouteAttempt",
    "RuntimeRouteFailure",
    "RuntimeRouter",
    "StartedRuntime",
    "RuntimeWorkerBridge",
]
