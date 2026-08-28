"""Provider-neutral runtime contracts.

Adapters deliberately live elsewhere; importing this package has no CLI or
subprocess side effects.
"""

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
