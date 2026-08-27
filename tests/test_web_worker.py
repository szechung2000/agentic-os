"""Web research worker scaffold tests."""

import json

from agentic_os.workers.web import WebSearchWorker


class Fetcher:
    def __init__(self):
        self.calls = []

    def search(self, query, *, top_n):
        self.calls.append((query, top_n))
        return [{"title": "Source", "url": "https://example.com"}]


async def test_web_worker_returns_structured_search_results():
    fetcher = Fetcher()
    result = await WebSearchWorker(fetcher).run({"query": "agent evals", "top_n": 2})
    payload = json.loads(result.output)
    assert result.ok
    assert payload["query"] == "agent evals"
    assert payload["results"][0]["url"] == "https://example.com"
    assert fetcher.calls == [("agent evals", 2)]


async def test_web_worker_rejects_empty_query_without_calling_fetcher():
    fetcher = Fetcher()
    result = await WebSearchWorker(fetcher).run({"query": ""})
    assert not result.ok
    assert "query is required" in result.output
    assert fetcher.calls == []
