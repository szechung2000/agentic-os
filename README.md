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
- [Evaluation and observability](docs/evaluation-observability.md) — component-call traces, replay, golden suites, metrics, and regression gates
- [E0 verification](docs/e0-verification.md) — executable acceptance proof, commands, artifacts, and criterion-to-test mapping
- [E2 verification](docs/e2-verification.md) — scoped-memory security, hydration, restart, and trace proof

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
  - `memory` worker – a policy-backed `ScopedMemoryWorker` over the
    agent-memory HTTP service. It accepts logical remember/search/context
    operations only; raw namespaces are never model-visible.
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
export AGOS_MEMORY_URL="http://localhost:8000"
uv run uvicorn agent_memory.api.main:app &
printf "remember that Simon prefers Python and uv for data work\nwhat does Simon prefer for data work?\nhello there\n" | agos chat
```

Expected output (with real agent-memory backend):

```
agentic-os chat (rule mode)
[memory] Remembered.
[memory] From your memory:
- Simon prefers Python and uv for data work
[echo] echo: hello there
```

The first two lines show the scoped worker storing and retrieving through the
real agent-memory HTTP service; the third line is the echo fallback. The
process is intentionally single-user by default (`local-user`,
`default-project`, `interactive-run`, `interactive-task`, `memory-worker`).
For an authenticated or multi-project deployment, provide stable validated
`AGOS_MEMORY_USER_ID`, `AGOS_MEMORY_PROJECT_ID`, `AGOS_MEMORY_RUN_ID`,
`AGOS_MEMORY_TASK_ID`, and `AGOS_MEMORY_WORKER_ID` values (or the matching
CLI flags) at the entry point; they are frozen before worker/model execution.

## E1: headless runtime adapter demo

E1 provides interchangeable headless runtime adapters for Claude Code, Codex,
and agy. Run the deterministic demo without API keys, network access, or the
real provider CLIs:

```bash
uv run agos eval e1 --workdir /tmp/agentic-os-e1
```

The proof exercises native-shaped provider output parsing, explicit fallback,
workspace policy checks, timeout handling, partial artifacts, runtime trace
metadata, and compatibility with the existing worker boundary. See
[`docs/e1-verification.md`](docs/e1-verification.md) for the opt-in real CLI
lane and safety constraints.

## E2A: scoped-memory hydration demo

E2A adds a policy-owned memory boundary over the agent-memory HTTP service.
Workers request logical scopes rather than namespaces; the policy derives
canonical namespaces and prevents cross-worker and supervisor-private reads.
Run the durable proof against the pinned agent-memory FastAPI application and
a persistent SQLite database:

```bash
uv run agos eval e2 --workdir /tmp/agentic-os-e2
```

The production adapter reads `AGOS_MEMORY_URL` (default
`http://localhost:8000`) and targets agent-memory commit `494610f`'s
`/remember` and `/recall` contract. See
[`docs/e2-verification.md`](docs/e2-verification.md) for lifecycle and restart
details.

## Tests

```bash
python -m pytest tests/
```

The suite covers routing, scoped-worker policy/authority, durable lifecycle
gating, real pinned-ASGI write/recall/private-isolation/expiry behavior, fresh
service restart, provenance, and trace output.

## Telegram

Optional. After `uv pip install -e ".[telegram]"`, set:

- `AGOS_TELEGRAM_BOT_TOKEN` – your bot token
- `AM_OPENAI_API_KEY` – optional: enables the LLM supervisor mode

Then `agos telegram`.

## License

MIT
