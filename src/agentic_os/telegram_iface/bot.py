"""Telegram interface for the agentic OS (optional extra)."""

from __future__ import annotations

import asyncio
from argparse import Namespace


async def run() -> None:  # pragma: no cover — needs live token
    from telegram.ext import AIORateLimiter, Application, MessageHandler, filters

    from agentic_os.cli import build_production_memory_policy
    from agentic_os.config import get_settings
    from agentic_os.supervisor.supervisor import Supervisor
    from agentic_os.workers.base import default_workers

    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("AGOS_TELEGRAM_BOT_TOKEN not set")

    memory_policy = build_production_memory_policy(
        Namespace(
            memory_event_db="./agentic-os-telegram-memory-events.db",
            memory_user_id=settings.memory_user_id,
            memory_project_id=settings.memory_project_id,
            memory_run_id=settings.memory_run_id,
            memory_task_id=settings.memory_task_id,
            memory_worker_id=settings.memory_worker_id,
        )
    )
    llm = None
    if settings.openai_api_key:
        from openai import OpenAI

        llm = OpenAI(api_key=settings.openai_api_key)

    supervisor = Supervisor(default_workers(memory_policy), llm=llm)

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
if __name__ == "__main__":
    asyncio.run(run())
