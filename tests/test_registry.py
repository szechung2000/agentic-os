"""Typed extension-registry tests — RED before implementation."""

import pytest

from agentic_os.core.registry import ExtensionKind, ExtensionRegistry, RuntimePreset


class Provider:
    def __init__(self, name: str):
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True


def test_registration_returns_disposer_and_releases_resource():
    registry = ExtensionRegistry()
    provider = Provider("codex")
    dispose = registry.register(ExtensionKind.RUNTIME, "coding", provider)

    assert registry.resolve(ExtensionKind.RUNTIME, "coding") is provider
    dispose()
    assert provider.closed
    with pytest.raises(KeyError):
        registry.resolve(ExtensionKind.RUNTIME, "coding")


def test_duplicate_registration_is_rejected():
    registry = ExtensionRegistry()
    registry.register(ExtensionKind.RUNTIME, "coding", Provider("claude"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ExtensionKind.RUNTIME, "coding", Provider("codex"))


def test_provider_can_be_replaced_without_consumer_branching():
    registry = ExtensionRegistry()
    first = Provider("claude")
    dispose = registry.register(ExtensionKind.RUNTIME, "coding", first)

    def consumer():
        return registry.resolve(ExtensionKind.RUNTIME, "coding").name

    assert consumer() == "claude"
    dispose()
    registry.register(ExtensionKind.RUNTIME, "coding", Provider("codex"))
    assert consumer() == "codex"


def test_runtime_preset_resolves_typed_capabilities():
    registry = ExtensionRegistry()
    runtime = Provider("codex")
    worker = Provider("coding-worker")
    tools = Provider("repo-tools")
    registry.register(ExtensionKind.RUNTIME, "codex", runtime)
    registry.register(ExtensionKind.WORKER, "coding", worker)
    registry.register(ExtensionKind.TOOL_PROVIDER, "repository", tools)

    preset = RuntimePreset(
        name="coding",
        capabilities={
            ExtensionKind.RUNTIME: "codex",
            ExtensionKind.WORKER: "coding",
            ExtensionKind.TOOL_PROVIDER: "repository",
        },
        policy={"workspace": "worktree", "delete_requires_approval": True},
    )
    resolved = registry.compose(preset)

    assert resolved.capabilities[ExtensionKind.RUNTIME] is runtime
    assert resolved.capabilities[ExtensionKind.WORKER] is worker
    assert resolved.policy["delete_requires_approval"] is True


def test_preset_fails_loud_on_missing_capability():
    registry = ExtensionRegistry()
    preset = RuntimePreset(
        name="broken",
        capabilities={ExtensionKind.RUNTIME: "missing"},
    )
    with pytest.raises(KeyError, match="missing"):
        registry.compose(preset)


def test_runtime_preset_preserves_explicit_runtime_candidate_order():
    registry = ExtensionRegistry()
    first = Provider("first")
    second = Provider("second")
    registry.register(ExtensionKind.RUNTIME, "zeta", first)
    registry.register(ExtensionKind.RUNTIME, "alpha", second)

    resolved = registry.compose(
        RuntimePreset(name="coding", runtime_candidates=("zeta", "alpha"))
    )

    assert resolved.runtime_candidates == (("zeta", first), ("alpha", second))
