"""Executable E0 acceptance suite used as reproducible proof."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from agentic_os.core.artifacts import ArtifactStore
from agentic_os.core.contracts import ComponentKind, GoalContract
from agentic_os.core.events import ComponentTracer, EventStore, TraceIntegrityReport
from agentic_os.core.registry import ExtensionKind, ExtensionRegistry
from agentic_os.core.state import RunCoordinator, RunStatus
from agentic_os.core.trace import TraceService
from agentic_os.evals.harness import EvalCase, EvalHistory, EvalRun, EvalSuite


@dataclass(frozen=True)
class E0Proof:
    run: EvalRun
    trace_report: TraceIntegrityReport
    recovered_completed_tasks: set[str]
    recorded_replay_live_calls: int
    replayed_terminal_status: str
    history_path: Path
    trace_id: str
    span_id: str
    event_db: Path
    artifact_root: Path


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def close(self) -> None:
        self.closed = True


def run_e0_proof(root: str | Path, *, candidate: str = "working-tree") -> E0Proof:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    event_db = root_path / "events.db"
    artifact_root = root_path / "artifacts"
    history_path = root_path / "eval-history.jsonl"
    events = EventStore(event_db)
    artifacts = ArtifactStore(artifact_root)

    invalid_rejected = False
    try:
        GoalContract(objective="invalid", success_metrics=[])
    except ValidationError:
        invalid_rejected = True
    goal = GoalContract(
        objective="Prove E0 durable orchestration core",
        success_metrics=["restart recovery", "trace replay", "provider replacement"],
    )

    first = RunCoordinator(events)
    state = first.create(goal)
    first.transition(state.run_id, RunStatus.PLANNING)
    first.checkpoint(state.run_id)
    first.transition(state.run_id, RunStatus.RUNNING)
    first.complete_task(state.run_id, "contracts")

    restarted = RunCoordinator(EventStore(event_db))
    recovered = restarted.load(state.run_id)
    duplicate_prevented = restarted.complete_task(state.run_id, "contracts") is False

    output_ref = artifacts.put(
        b'{"result":"component output replayed from verified artifact"}',
        "application/json",
    )
    tracer = ComponentTracer(events)
    try:
        with tracer.span(
            trace_id=state.trace_id,
            goal_id=goal.goal_id,
            run_id=state.run_id,
            task_id="contracts",
            component_kind="worker",
            component_name="proof-worker",
            operation="worker.prove-failure-replay",
            actor_id="supervisor",
            recipient_id="proof-worker",
        ) as span:
            span.set_output(output_ref)
            raise RuntimeError("intentional proof fixture failure")
    except RuntimeError:
        pass

    covered_kinds: set[ComponentKind] = set()
    for kind in ComponentKind:
        with tracer.span(
            trace_id=state.trace_id,
            goal_id=goal.goal_id,
            run_id=state.run_id,
            component_kind=kind,
            component_name=f"{kind.value}-proof",
            operation="component.coverage-proof",
        ):
            covered_kinds.add(kind)

    trace = TraceService(events, artifacts)
    trace_report = trace.verify(state.trace_id)
    replay = trace.replay_recorded(state.trace_id, span.span_id)
    terminal = next(
        event
        for event in reversed(events.query(trace_id=state.trace_id))
        if event.span_id == span.span_id and event.event_type == "component.call.failed"
    )

    registry = ExtensionRegistry()
    first_provider = _Provider("claude")
    dispose = registry.register(ExtensionKind.RUNTIME, "coding", first_provider)
    before = registry.resolve(ExtensionKind.RUNTIME, "coding").name
    dispose()
    second_provider = _Provider("codex")
    registry.register(ExtensionKind.RUNTIME, "coding", second_provider)
    after = registry.resolve(ExtensionKind.RUNTIME, "coding").name
    provider_replaced = before == "claude" and after == "codex" and first_provider.closed

    suite = EvalSuite(
        name="e0-core",
        version="1",
        cases=[
            EvalCase(
                case_id="contract-validation",
                tags=["contracts"],
                evaluate=lambda: {"passed": invalid_rejected},
            ),
            EvalCase(
                case_id="restart-recovery",
                tags=["state", "durability"],
                evaluate=lambda: {
                    "passed": recovered.status == RunStatus.RUNNING
                    and recovered.completed_tasks == {"contracts"}
                    and duplicate_prevented,
                    "completed_task_count": len(recovered.completed_tasks),
                    "duplicate_prevented": duplicate_prevented,
                },
            ),
            EvalCase(
                case_id="trace-integrity-replay",
                tags=["observability", "replay"],
                evaluate=lambda: {
                    "passed": trace_report.ok
                    and replay.content == artifacts.get(output_ref)
                    and replay.live_calls == 0,
                    "event_count": trace_report.event_count,
                    "span_count": trace_report.span_count,
                    "live_calls": replay.live_calls,
                },
            ),
            EvalCase(
                case_id="component-kind-coverage",
                tags=["observability", "components"],
                evaluate=lambda: {
                    "passed": covered_kinds == set(ComponentKind),
                    "covered": len(covered_kinds),
                    "required": len(ComponentKind),
                },
            ),
            EvalCase(
                case_id="provider-replacement",
                tags=["registry", "plugins"],
                evaluate=lambda: {"passed": provider_replaced},
            ),
        ],
    )
    run = suite.run(candidate=candidate)
    EvalHistory(history_path).append(run)
    return E0Proof(
        run=run,
        trace_report=trace_report,
        recovered_completed_tasks=set(recovered.completed_tasks),
        recorded_replay_live_calls=replay.live_calls,
        replayed_terminal_status=terminal.status,
        history_path=history_path,
        trace_id=state.trace_id,
        span_id=span.span_id,
        event_db=event_db,
        artifact_root=artifact_root,
    )
