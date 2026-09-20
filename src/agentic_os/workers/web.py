from __future__ import annotations

import json
from typing import Any

from agentic_os.workers.base import TaskResult, Worker


class WebSearchWorker(Worker):
    name = "web"
    description = "search the live web for current information"

    def __init__(self, fetcher):
        self.fetcher = fetcher  # pluggable: httpx or stub

    async def run(self, task: dict[str, Any]) -> TaskResult:
        query = str(task.get("query") or "").strip()
        if not query:
            return TaskResult(self.name, False, "query is required")
        top_n = int(task.get("top_n", 3))
        results = self.fetcher.search(query, top_n=top_n)
        payload = {"query": query, "results": results}
        return TaskResult(self.name, True, json.dumps(payload))
