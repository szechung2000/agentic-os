"""Pre-start-only runtime selection and fallback tests."""

from __future__ import annotations

from dataclasses import dataclass

from agentic_os.core.registry import ExtensionKind, ExtensionRegistry
from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    AvailabilityStatus,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeHandle,
)
from agentic_os.runtimes.routing import (
    PreStartRouteDecision,
    RuntimeRouter,
)


@dataclass
class FakeAdapter:
    runtime_name: str
    capabilities: RuntimeCapabilities
    start_error: Exception | None = None
    starts: int = 0

    async def start(self, task, workspace):
        del task, workspace
        self.starts += 1
        if self.start_error is not None:
            raise self.start_error
        return RuntimeHandle(runtime_name=self.runtime_name)


class FakeDiscovery:
    def __init__(self, results):
        self.results = results

    def discover_adapter(self, adapter):
        return self.results[adapter.runtime_name]


def _available(name: str) -> RuntimeAvailabilityResult:
    return RuntimeAvailabilityResult(
        runtime_name=name,
        status=AvailabilityStatus.AVAILABLE,
        available=True,
        capabilities=RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]),
    )


def _unavailable(name: str) -> RuntimeAvailabilityResult:
    return RuntimeAvailabilityResult(
        runtime_name=name,
        status=AvailabilityStatus.UNAVAILABLE,
        available=False,
        failure=RuntimeAvailabilityFailure(
            code=AvailabilityFailureCode.MISSING, message="not installed"
        ),
    )


def _router(*adapters: FakeAdapter) -> RuntimeRouter:
    registry = ExtensionRegistry()
    for adapter in adapters:
        registry.register(ExtensionKind.RUNTIME, adapter.runtime_name, adapter)
    return RuntimeRouter(
        registry=registry,
        discovery=FakeDiscovery(
            {
                adapter.runtime_name: _available(adapter.runtime_name)
                for adapter in adapters
            }
        ),
    )


def test_router_uses_preferred_then_explicit_fallback_not_alphabetical_order():
    alpha = FakeAdapter("alpha", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    zeta = FakeAdapter("zeta", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    router = _router(alpha, zeta)

    result = router.route(
        required_capabilities=[RuntimeCapability.EXECUTE],
        preferred_runtime="zeta",
        fallback_order=["alpha"],
    )

    assert result.decision is PreStartRouteDecision.SELECTED
    assert result.runtime_name == "zeta"
    assert [attempt.runtime_name for attempt in result.attempts] == ["zeta"]


def test_router_skips_unavailable_and_incapable_candidates_in_explicit_order():
    first = FakeAdapter("first", RuntimeCapabilities(supported=[]))
    second = FakeAdapter("second", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    router = _router(first, second)
    router.discovery.results["second"] = _unavailable("second")

    result = router.route(
        required_capabilities=[RuntimeCapability.EXECUTE],
        fallback_order=["first", "second"],
    )

    assert result.decision is PreStartRouteDecision.NO_COMPATIBLE_RUNTIME
    assert [attempt.runtime_name for attempt in result.attempts] == ["first", "second"]
    assert result.attempts[0].availability.failure is not None
    assert result.attempts[0].availability.failure.code is AvailabilityFailureCode.INCOMPATIBLE
    assert result.failure is not None


async def test_router_falls_back_only_when_start_fails_before_a_handle_exists():
    first = FakeAdapter(
        "first", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]), OSError("cannot spawn")
    )
    second = FakeAdapter("second", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    router = _router(first, second)

    started = await router.start(
        task=object(),
        workspace=object(),
        required_capabilities=[RuntimeCapability.EXECUTE],
        fallback_order=["first", "second"],
    )

    assert started.handle is not None
    assert started.adapter is second
    assert started.pre_start.runtime_name == "second"
    assert [attempt.runtime_name for attempt in started.pre_start.attempts] == ["first", "second"]


async def test_router_does_not_retry_after_a_process_has_started():
    first = FakeAdapter("first", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    second = FakeAdapter("second", RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]))
    router = _router(first, second)

    started = await router.start(
        task=object(),
        workspace=object(),
        required_capabilities=[RuntimeCapability.EXECUTE],
        fallback_order=["first", "second"],
    )

    assert started.handle is not None
    assert started.pre_start.no_retry_after_start
    assert first.starts == 1
    assert second.starts == 0


def test_router_requires_an_explicit_candidate_order():
    router = _router(FakeAdapter("first", RuntimeCapabilities()))

    result = router.route(required_capabilities=[])

    assert result.decision is PreStartRouteDecision.NO_COMPATIBLE_RUNTIME
    assert result.failure is not None
    assert result.failure.code == "no_candidates"
