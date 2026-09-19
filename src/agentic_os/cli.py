"""agentic_os CLI: run the Telegram bot or a one-shot rule-mode chat."""

from __future__ import annotations

import argparse
import asyncio
import sys


def build_production_memory_policy(args: argparse.Namespace):
    """Build the only production memory path: HTTP service + scoped policy.

    The arguments are copied into a frozen ``ActorAccessContext`` once at the
    boundary; model-visible tasks can never replace them or supply namespaces.
    """
    from agentic_os.config import get_settings
    from agentic_os.core.contracts import GoalContract
    from agentic_os.core.events import ComponentTracer, EventStore
    from agentic_os.core.state import RunCoordinator, RunStatus
    from agentic_os.memory.scoped import (
        ActorAccessContext,
        ActorKind,
        HttpAgentMemoryStore,
        MemoryTraceContext,
        ScopedMemoryPolicy,
    )

    settings = get_settings()
    context = ActorAccessContext(
        actor_kind=ActorKind.WORKER,
        user_id=args.memory_user_id or settings.memory_user_id,
        project_id=args.memory_project_id or settings.memory_project_id,
        run_id=args.memory_run_id or settings.memory_run_id,
        task_id=args.memory_task_id or settings.memory_task_id,
        worker_id=args.memory_worker_id or settings.memory_worker_id,
    )
    events = EventStore(args.memory_event_db)
    runs = RunCoordinator(events)
    try:
        state = runs.load(context.run_id)
    except KeyError:
        state = runs.create(
            GoalContract(
                goal_id=f"goal-{context.run_id}",
                objective="interactive scoped-memory session",
                success_metrics=["policy-backed memory access"],
            ),
            run_id=context.run_id,
        )
        state = runs.transition(context.run_id, RunStatus.PLANNING)
        state = runs.transition(context.run_id, RunStatus.RUNNING)
    if not runs.is_run_active(context.run_id):
        raise ValueError(f"memory run is not active: {context.run_id}")
    return ScopedMemoryPolicy(
        HttpAgentMemoryStore(settings.memory_url),
        context,
        lifecycle=runs,
        tracer=ComponentTracer(events),
        trace=MemoryTraceContext(
            trace_id=state.trace_id,
            goal_id=state.goal.goal_id,
            run_id=context.run_id,
            task_id=context.task_id,
        ),
    )


def cmd_chat(args: argparse.Namespace) -> int:
    """Offline demo: route stdin lines through the supervisor (rule mode)."""
    from agentic_os.supervisor.supervisor import Supervisor
    from agentic_os.workers.base import default_workers

    memory_policy = None if args.no_memory else build_production_memory_policy(args)

    sup = Supervisor(default_workers(memory_policy))
    print("agentic-os chat (rule mode, ctrl-D to exit)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        outcome = asyncio.run(sup.handle(line))
        print(f"[{outcome.get('routed_to', outcome['mode'])}] {outcome['reply']}")
    return 0


def cmd_telegram(args: argparse.Namespace) -> int:  # pragma: no cover — needs token
    from agentic_os.telegram_iface.bot import run

    asyncio.run(run())
    return 0


def _trace_service(args: argparse.Namespace):
    from agentic_os.core.artifacts import ArtifactStore
    from agentic_os.core.events import EventStore
    from agentic_os.core.trace import TraceService

    return TraceService(EventStore(args.db), ArtifactStore(args.artifacts))


def cmd_trace_tree(args: argparse.Namespace) -> int:
    service = _trace_service(args)

    def render(nodes, depth=0):
        for node in nodes:
            print(
                f"{'  ' * depth}{node.span_id} {node.component_kind}/"
                f"{node.component_name} {node.operation} [{node.status}]"
            )
            render(node.children, depth + 1)

    render(service.tree(args.trace_id))
    return 0


def cmd_trace_verify(args: argparse.Namespace) -> int:
    report = _trace_service(args).verify(args.trace_id)
    print(
        f"trace={report.trace_id} events={report.event_count} "
        f"spans={report.span_count} integrity=ok"
    )
    return 0


def cmd_trace_replay(args: argparse.Namespace) -> int:
    replay = _trace_service(args).replay_recorded(args.trace_id, args.span_id)
    print(replay.content.decode(errors="replace"))
    print(f"content_hash={replay.ref.content_hash} live_calls={replay.live_calls}")
    return 0


def cmd_eval_e0(args: argparse.Namespace) -> int:
    from agentic_os.evals.e0 import run_e0_proof

    proof = run_e0_proof(args.workdir, candidate=args.candidate)
    passed = sum(case.passed for case in proof.run.cases)
    print(f"E0 score: {passed}/{len(proof.run.cases)} ({proof.run.score:.0%})")
    for case in proof.run.cases:
        print(f"- {case.case_id}: {'PASS' if case.passed else 'FAIL'} {case.metrics}")
    print(
        f"trace={proof.trace_id} events={proof.trace_report.event_count} "
        f"spans={proof.trace_report.span_count} integrity=ok"
    )
    print(
        f"recorded_replay_span={proof.span_id} "
        f"terminal_status={proof.replayed_terminal_status} "
        f"live_calls={proof.recorded_replay_live_calls}"
    )
    print(f"event_db={proof.event_db}")
    print(f"artifacts={proof.artifact_root}")
    print(f"eval_history={proof.history_path}")
    return 0 if proof.run.score == 1.0 else 1


def cmd_eval_e1(args: argparse.Namespace) -> int:
    from agentic_os.evals.e1 import run_e1_proof

    proof = run_e1_proof(args.workdir, candidate=args.candidate)
    passed = sum(case.passed for case in proof.run.cases)
    print(f"E1 score: {passed}/{len(proof.run.cases)} ({proof.run.score:.0%})")
    for case in proof.run.cases:
        print(f"- {case.case_id}: {'PASS' if case.passed else 'FAIL'} {case.metrics}")
    print(f"trace={proof.trace_id}")
    print(f"eval_history={proof.history_path}")
    return 0 if proof.run.score == 1.0 else 1


def cmd_eval_e2(args: argparse.Namespace) -> int:
    from agentic_os.evals.e2 import run_e2_proof

    proof = run_e2_proof(args.workdir, candidate=args.candidate)
    passed = sum(case.passed for case in proof.run.cases)
    print(f"E2 score: {passed}/{len(proof.run.cases)} ({proof.run.score:.0%})")
    for case in proof.run.cases:
        print(f"- {case.case_id}: {'PASS' if case.passed else 'FAIL'} {case.metrics}")
    print(f"trace={proof.trace_id}")
    print(f"eval_history={proof.history_path}")
    return 0 if proof.run.score == 1.0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agos", description="agentic OS")
    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="offline rule-mode chat demo")
    p_chat.add_argument("--no-memory", action="store_true")
    p_chat.add_argument("--memory-event-db", default="./agentic-os-memory-events.db")
    p_chat.add_argument("--memory-user-id")
    p_chat.add_argument("--memory-project-id")
    p_chat.add_argument("--memory-run-id")
    p_chat.add_argument("--memory-task-id")
    p_chat.add_argument("--memory-worker-id")
    p_chat.set_defaults(func=cmd_chat)

    p_tg = sub.add_parser("telegram", help="run the Telegram interface")
    p_tg.set_defaults(func=cmd_telegram)

    p_trace = sub.add_parser("trace", help="inspect durable component traces")
    trace_sub = p_trace.add_subparsers(dest="trace_command", required=True)

    def add_trace_storage(parser):
        parser.add_argument("--db", default="./agentic-os-events.db")
        parser.add_argument("--artifacts", default="./agentic-os-artifacts")

    p_tree = trace_sub.add_parser("tree", help="render supervisor/worker span tree")
    p_tree.add_argument("trace_id")
    add_trace_storage(p_tree)
    p_tree.set_defaults(func=cmd_trace_tree)

    p_verify = trace_sub.add_parser("verify", help="verify trace integrity")
    p_verify.add_argument("trace_id")
    add_trace_storage(p_verify)
    p_verify.set_defaults(func=cmd_trace_verify)

    p_replay = trace_sub.add_parser("replay", help="replay recorded output without live calls")
    p_replay.add_argument("trace_id")
    p_replay.add_argument("span_id")
    add_trace_storage(p_replay)
    p_replay.set_defaults(func=cmd_trace_replay)

    p_eval = sub.add_parser("eval", help="run versioned evaluation suites")
    eval_sub = p_eval.add_subparsers(dest="eval_command", required=True)
    p_e0 = eval_sub.add_parser("e0", help="run executable E0 acceptance proof")
    p_e0.add_argument("--workdir", default="./.agos/evals/e0")
    p_e0.add_argument("--candidate", default="working-tree")
    p_e0.set_defaults(func=cmd_eval_e0)
    p_e1 = eval_sub.add_parser("e1", help="run executable E1 runtime-adapter proof")
    p_e1.add_argument("--workdir", default="./.agos/evals/e1")
    p_e1.add_argument("--candidate", default="working-tree")
    p_e1.set_defaults(func=cmd_eval_e1)
    p_e2 = eval_sub.add_parser("e2", help="run executable E2 scoped-memory proof")
    p_e2.add_argument("--workdir", default="./.agos/evals/e2")
    p_e2.add_argument("--candidate", default="working-tree")
    p_e2.set_defaults(func=cmd_eval_e2)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
