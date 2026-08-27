"""Typed, reversible extension registry and runtime preset composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtensionKind(StrEnum):
    RUNTIME = "runtime"
    WORKER = "worker"
    TOOL_PROVIDER = "tool_provider"
    EVALUATOR = "evaluator"
    PLANNING_SURFACE = "planning_surface"
    INTERFACE = "interface"
    MEMORY_POLICY = "memory_policy"
    SKILL_PROVIDER = "skill_provider"


class RuntimePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    capabilities: dict[ExtensionKind, str]
    policy: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedPreset:
    name: str
    capabilities: dict[ExtensionKind, Any]
    policy: dict[str, Any]


class ExtensionRegistry:
    """Registry whose registrations are effects reversed by their disposer."""

    def __init__(self) -> None:
        self._providers: dict[tuple[ExtensionKind, str], Any] = {}

    def register(
        self,
        kind: ExtensionKind,
        name: str,
        provider: Any,
        *,
        cleanup: Callable[[], None] | None = None,
    ) -> Callable[[], None]:
        key = (kind, name)
        if key in self._providers:
            raise ValueError(f"{kind.value}/{name} already registered")
        self._providers[key] = provider
        disposed = False

        def dispose() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            registered = self._providers.pop(key, None)
            if registered is None:
                return
            if cleanup is not None:
                cleanup()
            elif callable(getattr(registered, "close", None)):
                registered.close()

        return dispose

    def resolve(self, kind: ExtensionKind, name: str) -> Any:
        key = (kind, name)
        if key not in self._providers:
            raise KeyError(f"missing {kind.value} capability: {name}")
        return self._providers[key]

    def compose(self, preset: RuntimePreset) -> ResolvedPreset:
        capabilities = {
            kind: self.resolve(kind, name) for kind, name in preset.capabilities.items()
        }
        return ResolvedPreset(
            name=preset.name,
            capabilities=capabilities,
            policy=dict(preset.policy),
        )

    def available(self, kind: ExtensionKind) -> tuple[str, ...]:
        names = (
            name for registered_kind, name in self._providers if registered_kind == kind
        )
        return tuple(sorted(names))
