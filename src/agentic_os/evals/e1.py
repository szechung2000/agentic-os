"""Credential-free executable proof for E1 runtime adapters."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import TaskContract
from agentic_os.core.events import ComponentTracer, EventStore
from agentic_os.core.registry import ExtensionKind, ExtensionRegistry
from agentic_os.evals.harness import EvalCase, EvalHistory, EvalRun, EvalSuite
from agentic_os.runtimes.agy import AgyAdapter
from agentic_os.runtimes.base import SubprocessRuntimeAdapter, WorkspacePolicyError
from agentic_os.runtimes.claude import ClaudeCodeAdapter
from agentic_os.runtimes.codex import CodexAdapter
from agentic_os.runtimes.contracts import (
    AvailabilityFailureCode,
    AvailabilityStatus,
    RuntimeAvailabilityFailure,
    RuntimeAvailabilityResult,
    RuntimeCapabilities,
    RuntimeCapability,
    RuntimeStatus,
    Workspace,
)
from agentic_os.runtimes.routing import RuntimeRouter
from agentic_os.runtimes.worker_bridge import RuntimeWorkerBridge


@dataclass(frozen=True)
class E1Proof:
    run: EvalRun
    history_path: Path
    trace_id: str


def run_e1_proof(workdir: str | Path, *, candidate: str = "working-tree") -> E1Proof:
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    artifact_store = ArtifactStore(root / "artifacts")
    adapters = {
        "claude": ClaudeCodeAdapter(
            artifacts=artifact_store,
            executable=str(_fake_cli(root / "fake-claude.py", "claude")),
        ),
        "codex": CodexAdapter(
            artifacts=artifact_store,
            executable=str(_fake_cli(root / "fake-codex.py", "codex")),
        ),
        "agy": AgyAdapter(
            artifacts=artifact_store,
            executable=str(_fake_cli(root / "fake-agy.py", "agy")),
        ),
    }
    workspace = Workspace(root=root / "workspace", approved_root=root, allow_write=True)
    task = TaskContract(
        goal_id="e1-goal",
        worker_role="runtime-proof",
        objective="complete the E1 fixture task",
    )

    def cross_adapter() -> dict:
        async def run() -> dict:
            results = {}
            for name, adapter in adapters.items():
                handle = await adapter.start(task, workspace)
                results[name] = (await adapter.result(handle)).status is RuntimeStatus.COMPLETED
            return {"passed": all(results.values()), "adapters": results}

        return asyncio.run(run())

    def fallback() -> dict:
        registry = ExtensionRegistry()
        first = adapters["claude"]
        second = adapters["codex"]
        registry.register(ExtensionKind.RUNTIME, "claude", first)
        registry.register(ExtensionKind.RUNTIME, "codex", second)
        unavailable = RuntimeAvailabilityResult(
            runtime_name="claude",
            status=AvailabilityStatus.UNAVAILABLE,
            available=False,
            failure=RuntimeAvailabilityFailure(
                code=AvailabilityFailureCode.MISSING, message="fixture unavailable"
            ),
        )
        available = RuntimeAvailabilityResult(
            runtime_name="codex",
            status=AvailabilityStatus.AVAILABLE,
            available=True,
            capabilities=second.capabilities,
        )

        class Discovery:
            def discover_adapter(self, adapter):
                return {"claude": unavailable, "codex": available}[adapter.runtime_name]

        selected = RuntimeRouter(registry=registry, discovery=Discovery()).route(
            required_capabilities=[RuntimeCapability.EXECUTE],
            fallback_order=["claude", "codex"],
        )
        return {
            "passed": selected.runtime_name == "codex"
            and [attempt.runtime_name for attempt in selected.attempts] == ["claude", "codex"],
            "selected": selected.runtime_name,
        }

    def workspace_policy() -> dict:
        restricted = SubprocessRuntimeAdapter(
            runtime_name="restricted",
            artifacts=artifact_store,
            command_builder=lambda _task, _workspace: [sys.executable, "-c", ""],
            capabilities=RuntimeCapabilities(
                supported=frozenset([RuntimeCapability.EXECUTE])
            ),
        )

        async def run() -> bool:
            try:
                await restricted.start(task, workspace)
            except WorkspacePolicyError:
                return True
            return False

        return {"passed": asyncio.run(run())}

    def timeout() -> dict:
        slow = SubprocessRuntimeAdapter(
            runtime_name="slow",
            artifacts=artifact_store,
            command_builder=lambda _task, _workspace: [
                sys.executable,
                "-c",
                "import time; print('partial', flush=True); time.sleep(5)",
            ],
            capabilities=RuntimeCapabilities(
                supported=frozenset(
                    [
                        RuntimeCapability.EXECUTE,
                        RuntimeCapability.STREAM_EVENTS,
                        RuntimeCapability.STRUCTURED_RESULT,
                        RuntimeCapability.ISOLATED_WRITE_WORKSPACE,
                    ]
                )
            ),
        )

        async def run() -> bool:
            handle = await slow.start(
                task.model_copy(update={"limits": {"timeout_seconds": 0.05}}), workspace
            )
            return (await slow.result(handle)).status is RuntimeStatus.TIMED_OUT

        return {"passed": asyncio.run(run())}

    def bridge_trace() -> dict:
        event_store = EventStore(root / "events.db")
        tracer = ComponentTracer(event_store, artifact_store)
        bridge = RuntimeWorkerBridge(
            adapters["agy"], workspace, tracer=tracer, artifacts=artifact_store
        )

        async def run() -> str:
            result = await bridge.run(
                {
                    "task_id": "e1-task",
                    "goal_id": "e1-goal",
                    "run_id": "e1-run",
                    "trace_id": "e1-trace",
                    "objective": "complete the bridge fixture",
                }
            )
            assert result.ok
            report = event_store.verify_trace("e1-trace")
            assert report.ok
            return "e1-trace"

        return {"passed": True, "trace_id": asyncio.run(run())}

    suite = EvalSuite(
        name="e1-runtime-adapters",
        version="1",
        cases=[
            EvalCase("same-boundary", cross_adapter, ["adapters", "structured-result"]),
            EvalCase("pre-start-fallback", fallback, ["routing", "fallback"]),
            EvalCase("workspace-policy", workspace_policy, ["security", "workspace"]),
            EvalCase("timeout-preserves-lifecycle", timeout, ["timeout", "artifacts"]),
            EvalCase("bridge-trace", bridge_trace, ["bridge", "trace"]),
        ],
    )
    run = suite.run(candidate=candidate)
    history_path = root / "eval-history.jsonl"
    EvalHistory(history_path).append(run)
    return E1Proof(run=run, history_path=history_path, trace_id="e1-trace")


def _fake_cli(path: Path, kind: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f'''#!{sys.executable}
import json
import sys
kind = {kind!r}
if len(sys.argv) > 1 and sys.argv[1] in {{"--version", "--help"}}:
    print("fake-" + kind + (" 1.0.0" if sys.argv[1] == "--version" else " usage"))
    raise SystemExit(0)
if kind == "claude":
    payload = {{
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "fixture complete",
        "session_id": "claude-session",
    }}
    print(json.dumps(payload))
elif kind == "codex":
    print(json.dumps({{"type": "thread.started", "thread_id": "codex-session"}}))
    payload = {{
        "type": "item.completed",
        "item": {{"type": "agent_message", "text": "fixture complete"}},
    }}
    print(json.dumps(payload))
else:
    payload = {{
        "conversation_id": "agy-session",
        "status": "SUCCESS",
        "response": "fixture complete",
        "num_turns": 1,
    }}
    print(json.dumps(payload))
'''
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    (path.parent / "workspace").mkdir(parents=True, exist_ok=True)
    return path
