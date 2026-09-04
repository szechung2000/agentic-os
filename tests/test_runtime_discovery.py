"""Deterministic availability checks for headless runtime CLIs."""

from __future__ import annotations

from pathlib import Path

from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    RuntimeCapabilities,
    RuntimeCapability,
)
from agentic_os.runtimes.discovery import RuntimeDiscovery, RuntimeProbeSpec


def _fake_executable(tmp_path: Path, body: str) -> str:
    executable = tmp_path / "fake-runtime"
    executable.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    executable.chmod(0o755)
    return str(executable)


def _spec(executable: str) -> RuntimeProbeSpec:
    return RuntimeProbeSpec(
        runtime_name="fake",
        executable=executable,
        capabilities=RuntimeCapabilities(supported=[RuntimeCapability.EXECUTE]),
    )


def test_discovery_classifies_a_missing_executable():
    result = RuntimeDiscovery().discover(_spec("definitely-not-installed-agentic-os"))

    assert not result.available
    assert result.failure is not None
    assert result.failure.code is AvailabilityFailureCode.MISSING


def test_discovery_never_treats_a_version_probe_as_authentication(tmp_path):
    executable = _fake_executable(
        tmp_path,
        'if [ "$1" = "--version" ]; then echo "fake 1.2.3"; exit 0; fi\n'
        'if [ "$1" = "--help" ]; then echo "usage: fake"; exit 0; fi\nexit 2',
    )

    result = RuntimeDiscovery().discover(_spec(executable))

    assert result.version == "1.2.3"
    assert not result.available
    assert result.failure is not None
    assert result.failure.code is AvailabilityFailureCode.AUTH_UNKNOWN


def test_discovery_classifies_only_explicit_auth_errors_as_unauthenticated(tmp_path):
    executable = _fake_executable(
        tmp_path, 'echo "Error: not authenticated; run login" >&2\nexit 1'
    )

    result = RuntimeDiscovery().discover(_spec(executable))

    assert result.failure is not None
    assert result.failure.code is AvailabilityFailureCode.UNAUTHENTICATED


def test_discovery_uses_help_when_version_is_unsupported_and_checks_compatibility(tmp_path):
    executable = _fake_executable(
        tmp_path,
        'if [ "$1" = "--version" ]; then echo "unknown option" >&2; exit 2; fi\n'
        'if [ "$1" = "--help" ]; then echo "other-runtime usage"; exit 0; fi\nexit 2',
    )
    spec = RuntimeProbeSpec(
        runtime_name="fake",
        executable=executable,
        capabilities=RuntimeCapabilities(),
        is_compatible=lambda probe: "fake-runtime" in probe.help_output,
    )

    result = RuntimeDiscovery().discover(spec)

    assert result.failure is not None
    assert result.failure.code is AvailabilityFailureCode.INCOMPATIBLE


def test_discovery_classifies_unusable_probes_as_probe_failed(tmp_path):
    executable = _fake_executable(tmp_path, "exit 2")

    result = RuntimeDiscovery().discover(_spec(executable))

    assert result.failure is not None
    assert result.failure.code is AvailabilityFailureCode.PROBE_FAILED
