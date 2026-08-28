"""Provider-neutral runtime contracts.

Importing this package has no CLI or subprocess side effects.
"""

from agentic_os.runtimes.base import (
    ManagedSubprocessRuntimeAdapter,
    RuntimeAdapter,
    RuntimeLifecycleError,
    SubprocessRuntimeAdapter,
    UnsupportedSteeringError,
    WorkspacePolicyError,
)
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

__all__ = [
    "ManagedSubprocessRuntimeAdapter",
    "RuntimeAdapter",
    "RuntimeLifecycleError",
    "SubprocessRuntimeAdapter",
    "UnsupportedSteeringError",
    "WorkspacePolicyError",
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
]
