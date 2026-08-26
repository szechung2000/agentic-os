"""agentic_os CLI: run the Telegram bot or a one-shot rule-mode chat."""

from __future__ import annotations

import argparse
import asyncio
import sys


def cmd_chat(args: argparse.Namespace) -> int:
    """Offline demo: route stdin lines through the supervisor (rule mode)."""
    from agentic_os.supervisor.supervisor import Supervisor
    from agentic_os.workers.base import default_workers

    memory_executor = None
    if not args.no_memory:
        try:
            from agent_memory.core.embedding import get_embedder
            from agent_memory.ingest.pipeline import get_repo_for_url
            from agent_memory.tools import MemoryToolExecutor

            repo = get_repo_for_url(args.memory_db)
            memory_executor = MemoryToolExecutor(repo, get_embedder())
        except ImportError:
            print("agent-memory not installed — running without memory worker", file=sys.stderr)

    sup = Supervisor(default_workers(memory_executor))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agos", description="agentic OS")
    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="offline rule-mode chat demo")
    p_chat.add_argument("--no-memory", action="store_true")
    p_chat.add_argument("--memory-db", default="sqlite:///./memory.db")
    p_chat.set_defaults(func=cmd_chat)

    p_tg = sub.add_parser("telegram", help="run the Telegram interface")
    p_tg.set_defaults(func=cmd_telegram)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
