"""Bridge: expose agentic-os workers as OpenAI function-calling tools."""

from __future__ import annotations

import json
from typing import Any

from agentic_os.workers.base import Worker


def build_openai_tools(workers: dict[str, Worker]) -> list[dict[str, Any]]:
    """One tool per worker; the supervisor LLM calls `worker_<name>`."""
    tools = []
    for w in workers.values():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f"worker_{w.name}",
                    "description": w.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": (
                            "worker-specific action (remember/search/context)"
                        ),
                            },
                            "content": {"type": "string"},
                            "query": {"type": "string"},
                        },
                    },
                },
            }
        )
    return tools


def dispatch(workers: dict[str, Worker], name: str, arguments: dict[str, Any]) -> str:
    """Execute a worker_<name> tool call, returning JSON text output."""
    import asyncio

    worker = workers.get(name.replace("worker_", ""))
    if worker is None:
        return json.dumps({"error": f"no such worker: {name}"})
    result = asyncio.get_event_loop().run_until_complete(worker.run(arguments)) if False else None
    # run in existing loop if present
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # called from async context: schedule and block via task
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            result = pool.submit(asyncio.run, worker.run(arguments)).result()
    else:
        result = asyncio.run(worker.run(arguments))
    return json.dumps({"ok": result.ok, "output": result.output})
