# agentic-os

A supervisor/worker agent orchestration layer, living on top of
[agent-memory](https://github.com/szechung2000/agent-memory) as its
long-term semantic + episodic brain. For Simon's Georgia Tech OMSCS
portfolio: this is the agentic OS with a Telegram interface that lets
him talk to the system while he's working or caring for his kids.

## Specification

The formal design is versioned with the repository:

- [Product specification](docs/product-spec.md) — vision, requirements, safety, memory, and v1 success criteria
- [Architecture](docs/architecture.md) — runtime adapters, contracts, memory scopes, skills, approvals, and deployment
- [Roadmap](docs/roadmap.md) — E0–E8 deliverables and acceptance tests
- [Reference architectures](docs/reference-architectures.md) — ideas adopted from DeepSeek Harness and Hermes Agent

## Architecture

```
Telegram / CLI ───► SUPERVISOR ───► WORKER 1 … WORKER N
                       │                 │
                 route → delegate   worker tools
                       │                 │
                 compose reply       └──► agent-memory (semantic/episodic)
```

- **Supervisor** – the only reasoning component. Two modes:
  - *LLM mode*: OpenAI key → bounded tool-calling rounds (ReAct-style), each
    round the model picks a worker tool and we feed its result back.
  - *Rule mode*: fully offline; `remember that X` → memory write, anything
    phrased as a question → memory search, else echo fallback. Used in this
    scaffold for testability and demos.
- **Workers** – dumb-but-reliable capability holders with structured
  task-in / result-out. Each worker owns one tool set.
  - `memory` worker – delegates to agent-memory's `MemoryToolExecutor`
    (tool names: `memory_write`, `memory_search`, `memory_context`).
  - `echo` worker – fallback/general-purpose worker with no external deps.
- **agent-memory** – shared long-term brain: hybrid retrieval, temporal
  reasoning, consolidation, and graded evals. Papers suite currently runs
  at **90%** (L2 100%, L3 60%), multihop 83%, glossary/temporal 100%
  (with latency timing). See its
  [evals README table](https://github.com/szechung2000/agent-memory#showcase-the-capacity-golden-evals).

## Quick start

```bash
uv sync --all-groups
uv pip install -e ".[telegram]"   # optional Telegram extra
uv pip install -e "../agent-memory"  # memory brain
```

## Demo: rule mode (no API keys needed)

Drop into the project root and run:

```bash
export AM_DATABASE_URL="sqlite:////tmp/agos-demo.db"
rm -f /tmp/agos-demo.db
printf "remember that Simon prefers Python and uv for data work\nwhat does Simon prefer for data work?\nhello there\n" | agos chat --memory-db "sqlite:////tmp/agos-demo.db"
```

Expected output (with real agent-memory backend):

```
agentic-os chat (rule mode)
[memory] Remembered.
[memory] From your memory:
- Simon prefers Python and uv for data work
[echo] echo: hello there
```

The first two lines show the memory worker storing and then retrieving
through the real agent-memory pipeline; the third line is the echo
fallback.

## Tests

```bash
python -m pytest tests/
```

7 tests covering routing rules, the remember→recall roundtrip through a
real agent-memory backend, echo fallback, and trace output.

## Telegram

Optional. After `uv pip install -e ".[telegram]"`, set:

- `AGOS_TELEGRAM_BOT_TOKEN` – your bot token
- `AM_OPENAI_API_KEY` – optional: enables the LLM supervisor mode

Then `agos telegram`.

## License

MIT
