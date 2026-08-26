"""Supervisor: routes incoming messages to workers, composes replies.

Two modes:
- LLM mode (AM key set): the model plans, picks workers, and writes the reply
- Rule mode (offline demo): keyword routing + deterministic composition so the
  whole system is testable without any API keys
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agentic_os.workers.base import TaskResult, Worker


@dataclass
class Route:
    worker_name: str
    task: dict[str, Any]


REMEMBER_RE = re.compile(r"\bremember(?: that)?\s+(.+)", re.IGNORECASE)
SEARCH_RE = re.compile(r"^(?:what|where|when|who|which|how)\b|\?\s*$", re.IGNORECASE)


def rule_route(text: str) -> Route:
    """Offline router: 'remember ...' -> memory.write; questions -> memory.search;
    everything else -> echo."""
    m = REMEMBER_RE.search(text)
    if m:
        return Route("memory", {"action": "remember", "content": m.group(1).strip()})
    if SEARCH_RE.search(text):
        return Route("memory", {"action": "search", "query": text})
    return Route("echo", {"content": text})


class Supervisor:
    def __init__(
        self,
        workers: list[Worker],
        llm=None,
        model: str = "gpt-4o-mini",
        default_worker: str = "echo",
    ) -> None:
        self.workers = {w.name: w for w in workers}
        self.llm = llm
        self.model = model
        self.default_worker = default_worker
        self.history: list[dict[str, str]] = []

    def _resolve(self, route: Route) -> Worker | None:
        return self.workers.get(route.worker_name) or self.workers.get(self.default_worker)

    async def _run_llm(self, text: str) -> tuple[str, list[TaskResult]]:
        """LLM plans tool calls; bounded rounds like the agent-memory demo."""
        from agentic_os.tools.bridge import build_openai_tools

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": text},
        ]
        task_results: list[TaskResult] = []
        for _ in range(4):
            resp = await self.llm.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=build_openai_tools(self.workers),
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return msg.content or "", task_results
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                worker = self.workers.get(tc.function.name.replace("worker_", ""))
                if worker is None:
                    result = TaskResult(tc.function.name, False, "no such worker")
                else:
                    result = await worker.run(args)
                task_results.append(result)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result.output}
                )
        return "(supervisor gave up after 4 rounds)", task_results

    def _system_prompt(self) -> str:
        descs = "\n".join(f"- {w.name}: {w.description}" for w in self.workers.values())
        return (
            "You are the supervisor of a small agent operating system.\n"
            "Route tasks to worker tools and compose their outputs into a reply.\n"
            f"Available workers:\n{descs}"
        )

    async def handle(self, text: str) -> dict[str, Any]:
        """Main entry: returns reply plus trace of what happened."""
        if self.llm is not None:
            reply, results = await self._run_llm(text)
            return {
                "reply": reply,
                "trace": [r.__dict__ for r in results],
                "mode": "llm",
            }

        # rule mode
        route = rule_route(text)
        worker = self._resolve(route)
        if worker is None:
            return {"reply": "no worker available", "trace": [], "mode": "rule"}
        result = await worker.run(route.task)
        reply = self._compose(route.worker_name, result.output)
        return {
            "reply": reply,
            "trace": [result.__dict__],
            "mode": "rule",
            "routed_to": route.worker_name,
        }

    def _compose(self, worker_name: str, output: str) -> str:
        """Rule-mode composer: light cleanup of worker output."""
        try:
            import json

            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return output
        if isinstance(parsed, dict) and parsed.get("context"):
            block = parsed["context"]
            return f"From your memory:\n{block}" if block != "(no relevant memories)" else (
                "Nothing in memory about that yet."
            )
        if isinstance(parsed, list):  # memory_search hits
            lines = []
            for h in parsed[:3]:
                score = h.get("score", 0)
                lines.append(f"- ({score:.2f}) {h['content'][:140]}")
            return "\n".join(lines) if lines else "Nothing found in memory."
        if isinstance(parsed, dict) and parsed.get("status") == "remembered":
            return "Remembered."
        _ = worker_name
        return output


async def route_and_run(workers: list[Worker], text: str) -> dict[str, Any]:
    """Convenience one-shot for tests/scripts."""
    sup = Supervisor(workers)
    return await sup.handle(text)
