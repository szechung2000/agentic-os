"""Explicit, pre-start-only routing for interchangeable runtime adapters."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agentic_os.core.registry import ExtensionKind, ExtensionRegistry
from agentic_os.runtimes.base import RuntimeAdapter
from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    AvailabilityStatus,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeHandle,
)
from agentic_os.runtimes.discovery import RuntimeDiscoverer, RuntimeDiscovery


class PreStartRouteDecision(StrEnum):
    """A route outcome before any candidate process has started."""

    SELECTED = "selected"
    NO_COMPATIBLE_RUNTIME = "no_compatible_runtime"


class RouteFailureCode(StrEnum):
    NO_CANDIDATES = "no_candidates"
    NO_COMPATIBLE_RUNTIME = "no_compatible_runtime"


@dataclass(frozen=True)
class RuntimeRouteFailure:
    code: RouteFailureCode
    message: str


@dataclass(frozen=True)
class RuntimeRouteAttempt:
    runtime_name: str
    availability: RuntimeAvailabilityResult
    start_error: str | None = None


@dataclass(frozen=True)
class PreStartRouteResult:
    """Selection evidence that is valid only until ``start`` returns a handle."""

    decision: PreStartRouteDecision
    runtime_name: str | None
    adapter: RuntimeAdapter | None
    attempts: tuple[RuntimeRouteAttempt, ...]
    failure: RuntimeRouteFailure | None = None
    no_retry_after_start: bool = True


@dataclass(frozen=True)
class StartedRuntime:
    """A successfully started process; this router will never retry its outcome."""

    pre_start: PreStartRouteResult
    adapter: RuntimeAdapter | None
    handle: RuntimeHandle | None


class RuntimeRouter:
    """Select only from caller-specified candidates in caller-specified order."""

    def __init__(
        self,
        *,
        registry: ExtensionRegistry,
        discovery: RuntimeDiscoverer | None = None,
    ) -> None:
        self.registry = registry
        self.discovery = discovery or RuntimeDiscovery()

    def route(
        self,
        *,
        required_capabilities: Iterable[RuntimeCapability],
        preferred_runtime: str | None = None,
        fallback_order: Sequence[str] = (),
    ) -> PreStartRouteResult:
        """Choose an available compatible adapter without creating a process."""
        return self._route(
            required_capabilities=frozenset(required_capabilities),
            candidate_order=self._candidate_order(preferred_runtime, fallback_order),
            prior_attempts=(),
        )

    async def start(
        self,
        *,
        task: Any,
        workspace: Any,
        required_capabilities: Iterable[RuntimeCapability],
        preferred_runtime: str | None = None,
        fallback_order: Sequence[str] = (),
    ) -> StartedRuntime:
        """Start a selected adapter, retrying only a failed process creation.

        A returned handle proves that a child process may have side effects.
        This method intentionally does not await a result or retry later
        execution failures.
        """
        required = frozenset(required_capabilities)
        candidate_order = self._candidate_order(preferred_runtime, fallback_order)
        attempts: tuple[RuntimeRouteAttempt, ...] = ()
        excluded: set[str] = set()

        while True:
            result = self._route(
                required_capabilities=required,
                candidate_order=tuple(name for name in candidate_order if name not in excluded),
                prior_attempts=attempts,
            )
            if result.adapter is None or result.runtime_name is None:
                return StartedRuntime(pre_start=result, adapter=None, handle=None)
            try:
                handle = await result.adapter.start(task, workspace)
            except Exception as error:
                failed_attempt = RuntimeRouteAttempt(
                    runtime_name=result.runtime_name,
                    availability=self._availability_for_attempt(result),
                    start_error=f"{type(error).__name__}: {error}",
                )
                attempts = (*result.attempts[:-1], failed_attempt)
                excluded.add(result.runtime_name)
                continue
            return StartedRuntime(pre_start=result, adapter=result.adapter, handle=handle)

    def _route(
        self,
        *,
        required_capabilities: frozenset[RuntimeCapability],
        candidate_order: tuple[str, ...],
        prior_attempts: tuple[RuntimeRouteAttempt, ...],
    ) -> PreStartRouteResult:
        if not candidate_order:
            return PreStartRouteResult(
                decision=PreStartRouteDecision.NO_COMPATIBLE_RUNTIME,
                runtime_name=None,
                adapter=None,
                attempts=prior_attempts,
                failure=RuntimeRouteFailure(
                    RouteFailureCode.NO_CANDIDATES, "no explicit runtime candidates were supplied"
                ),
            )

        attempts = list(prior_attempts)
        for runtime_name in candidate_order:
            adapter = self._resolve(runtime_name)
            if adapter is None:
                attempts.append(
                    RuntimeRouteAttempt(
                        runtime_name, self._missing_registry_candidate(runtime_name)
                    )
                )
                continue
            capabilities = getattr(adapter, "capabilities", None)
            supports_required = isinstance(
                capabilities, RuntimeCapabilities
            ) and required_capabilities.issubset(capabilities.supported)
            if not supports_required:
                attempts.append(
                    RuntimeRouteAttempt(
                        runtime_name, self._incompatible_capabilities(runtime_name, capabilities)
                    )
                )
                continue
            availability = self.discovery.discover_adapter(adapter)
            attempts.append(RuntimeRouteAttempt(runtime_name, availability))
            if availability.available:
                return PreStartRouteResult(
                    decision=PreStartRouteDecision.SELECTED,
                    runtime_name=runtime_name,
                    adapter=adapter,
                    attempts=tuple(attempts),
                )

        return PreStartRouteResult(
            decision=PreStartRouteDecision.NO_COMPATIBLE_RUNTIME,
            runtime_name=None,
            adapter=None,
            attempts=tuple(attempts),
            failure=RuntimeRouteFailure(
                RouteFailureCode.NO_COMPATIBLE_RUNTIME,
                "no explicit runtime candidate was both available and capability-compatible",
            ),
        )

    def _resolve(self, runtime_name: str) -> RuntimeAdapter | None:
        try:
            adapter = self.registry.resolve(ExtensionKind.RUNTIME, runtime_name)
        except KeyError:
            return None
        return adapter

    @staticmethod
    def _candidate_order(
        preferred_runtime: str | None, fallback_order: Sequence[str]
    ) -> tuple[str, ...]:
        names = ((preferred_runtime,) if preferred_runtime else ()) + tuple(fallback_order)
        return tuple(dict.fromkeys(names))

    @staticmethod
    def _missing_registry_candidate(runtime_name: str) -> RuntimeAvailabilityResult:
        return RuntimeAvailabilityResult(
            runtime_name=runtime_name,
            status=AvailabilityStatus.UNAVAILABLE,
            available=False,
            failure=RuntimeAvailabilityFailure(
                code=AvailabilityFailureCode.MISSING,
                message="runtime candidate is not registered",
            ),
        )

    @staticmethod
    def _incompatible_capabilities(
        runtime_name: str, capabilities: object
    ) -> RuntimeAvailabilityResult:
        reported_capabilities = (
            capabilities if isinstance(capabilities, RuntimeCapabilities) else RuntimeCapabilities()
        )
        return RuntimeAvailabilityResult(
            runtime_name=runtime_name,
            status=AvailabilityStatus.UNAVAILABLE,
            available=False,
            capabilities=reported_capabilities,
            failure=RuntimeAvailabilityFailure(
                code=AvailabilityFailureCode.INCOMPATIBLE,
                message="runtime candidate does not provide the required capabilities",
            ),
        )

    @staticmethod
    def _availability_for_attempt(result: PreStartRouteResult) -> RuntimeAvailabilityResult:
        assert result.attempts
        return result.attempts[-1].availability
