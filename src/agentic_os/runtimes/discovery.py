"""Safe, non-interactive discovery of runtime CLI availability.

Discovery deliberately probes only ``--version`` and ``--help`` with stdin
closed.  Those probes establish that a compatible executable can be invoked;
they do not establish that a provider account is authenticated.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    AvailabilityStatus,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
)

_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?\b")
_EXPLICIT_AUTH_ERROR_RE = re.compile(
    r"\b(?:not\s+authenticated|unauthenticated|authentication\s+required|"
    r"login\s+required|not\s+logged\s+in|please\s+(?:log\s+in|authenticate))\b",
    re.IGNORECASE,
)
_SAFE_PROBE_ENV = {"PATH": os.defpath, "LC_ALL": "C", "LANG": "C"}


@dataclass(frozen=True)
class RuntimeProbeOutput:
    """Internal probe data made available to an optional compatibility check."""

    version_output: str
    help_output: str


@dataclass(frozen=True)
class RuntimeProbeSpec:
    """The provider-specific, side-effect-free facts discovery may inspect."""

    runtime_name: str
    executable: str
    capabilities: RuntimeCapabilities
    is_compatible: Callable[[RuntimeProbeOutput], bool] | None = None

    def __post_init__(self) -> None:
        if not self.runtime_name:
            raise ValueError("runtime_name must not be empty")
        if not self.executable:
            raise ValueError("executable must not be empty")


@dataclass(frozen=True)
class _ProbeResult:
    completed: subprocess.CompletedProcess[str] | None
    error: BaseException | None = None


@runtime_checkable
class RuntimeDiscoverer(Protocol):
    def discover_adapter(self, adapter: object) -> RuntimeAvailabilityResult: ...


class RuntimeDiscovery:
    """Find an executable and classify non-interactive version/help probes."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        which: Callable[[str], str | None] = shutil.which,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._which = which
        self._run = run

    def discover_adapter(self, adapter: object) -> RuntimeAvailabilityResult:
        """Discover an adapter exposing the standard runtime adapter attributes."""
        runtime_name = getattr(adapter, "runtime_name", None)
        executable = getattr(adapter, "executable", None)
        capabilities = getattr(adapter, "capabilities", None)
        if not isinstance(runtime_name, str) or not isinstance(executable, str):
            raise TypeError("runtime adapter must expose runtime_name and executable strings")
        if not isinstance(capabilities, RuntimeCapabilities):
            raise TypeError("runtime adapter must expose RuntimeCapabilities")
        return self.discover(
            RuntimeProbeSpec(
                runtime_name=runtime_name,
                executable=executable,
                capabilities=capabilities,
            )
        )

    def discover(self, spec: RuntimeProbeSpec) -> RuntimeAvailabilityResult:
        resolved = self._which(spec.executable)
        if resolved is None:
            return self._unavailable(
                spec, AvailabilityFailureCode.MISSING, "runtime executable was not found"
            )

        executable = str(Path(resolved))
        version_probe = self._probe(executable, "--version")
        help_probe = self._probe(executable, "--help")
        outputs = RuntimeProbeOutput(
            version_output=self._combined_output(version_probe),
            help_output=self._combined_output(help_probe),
        )

        if self._contains_explicit_auth_error(outputs):
            return self._unavailable(
                spec,
                AvailabilityFailureCode.UNAUTHENTICATED,
                "runtime CLI explicitly reported that authentication is required",
            )

        successful_probe = any(
            probe.completed is not None and probe.completed.returncode == 0
            for probe in (version_probe, help_probe)
        )
        if not successful_probe:
            return self._unavailable(
                spec,
                AvailabilityFailureCode.PROBE_FAILED,
                "runtime version and help probes did not complete successfully",
            )

        if spec.is_compatible is not None and not spec.is_compatible(outputs):
            return self._unavailable(
                spec,
                AvailabilityFailureCode.INCOMPATIBLE,
                "runtime executable did not satisfy the compatibility check",
            )

        # A help/version response is intentionally not treated as an account
        # check.  Do not inspect credentials or initiate a login flow here.
        return self._unavailable(
            spec,
            AvailabilityFailureCode.AUTH_UNKNOWN,
            "runtime executable responded, but authentication was not verified",
            version=self._version_from(version_probe),
        )

    def _probe(self, executable: str, argument: str) -> _ProbeResult:
        try:
            completed = self._run(
                (executable, argument),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                env=dict(_SAFE_PROBE_ENV),
            )
        except (OSError, subprocess.SubprocessError) as error:
            return _ProbeResult(completed=None, error=error)
        return _ProbeResult(completed=completed)

    @staticmethod
    def _combined_output(probe: _ProbeResult) -> str:
        if probe.completed is None:
            return ""
        return f"{probe.completed.stdout}\n{probe.completed.stderr}"

    @staticmethod
    def _version_from(probe: _ProbeResult) -> str | None:
        if probe.completed is None or probe.completed.returncode != 0:
            return None
        match = _VERSION_RE.search(probe.completed.stdout)
        return match.group(0) if match is not None else None

    @staticmethod
    def _contains_explicit_auth_error(outputs: RuntimeProbeOutput) -> bool:
        return bool(
            _EXPLICIT_AUTH_ERROR_RE.search(outputs.version_output)
            or _EXPLICIT_AUTH_ERROR_RE.search(outputs.help_output)
        )

    @staticmethod
    def _unavailable(
        spec: RuntimeProbeSpec,
        code: AvailabilityFailureCode,
        message: str,
        *,
        version: str | None = None,
    ) -> RuntimeAvailabilityResult:
        return RuntimeAvailabilityResult(
            runtime_name=spec.runtime_name,
            status=AvailabilityStatus.UNAVAILABLE,
            available=False,
            version=version,
            capabilities=spec.capabilities,
            failure=RuntimeAvailabilityFailure(code=code, message=message),
        )
