"""Telegram interface for the agentic OS (optional extra)."""

from __future__ import annotations

import asyncio
import os


async def run() -> None:  # pragma: no cover — needs live token
    from telegram.ext import AIORateLimiter, Application, MessageHandler, filters

    from agentic_os.config import get_settings
    from agentic_os.supervisor.supervisor import Supervisor
    from agentic_os.workers.base import default_workers

    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("AGOS_TELEGRAM_BOT_TOKEN not set")

    memory_executor = _build_memory_executor()
    llm = None
    if settings.openai_api_key:
        from openai import OpenAI

        llm = OpenAI(api_key=settings.openai_api_key)

    supervisor = Supervisor(default_workers(memory_executor), llm=llm)

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .rate_limiter(AIORateLimiter())
        .build()
    )

    async def on_message(update, context) -> None:
        if not update.message or not update.message.text:
            return
        outcome = await supervisor.handle(update.message.text)
        await update.message.reply_text(outcome["reply"][:4000])

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    print("agentic-os listening on Telegram…")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()


def _build_memory_executor():
    """Wire the memory worker to a local agent-memory repo (in-process)."""
    try:
        from agent_memory.core.embedding import get_embedder
        from agent_memory.ingest.pipeline import get_repo_for_url
        from agent_memory.tools import MemoryToolExecutor
    except ImportError:
        print("agent-memory not installed — running without the memory worker")
        return None

    db_url = f"sqlite:///{os.path.expanduser('~')}/.agentic-os/memory.db"
    repo = get_repo_for_url(db_url)
    return MemoryToolExecutor(repo, get_embedder())


if __name__ == "__main__":
    asyncio.run(run())
