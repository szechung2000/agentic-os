# E2A verification — scoped memory hydration

## Credential-free acceptance proof

```bash
uv run agos eval e2 --workdir /tmp/agentic-os-e2
```

Expected result: `E2 score: 5/5 (100%)`.

The proof starts the pinned `agent-memory` FastAPI app through a fresh
Starlette `TestClient` over a persistent SQLite database. It needs no
credentials, but it does require agent-memory commit `494610f`; it fails
clearly rather than claiming a restart when that dependency is absent. It verifies:

- Workers may read but cannot write project-shared memory. The supervisor
  promotes a service-returned, same-user/project/current-run source record;
  it validates ID, namespace, and owner metadata before writing shared memory.
- The supervisor sees supervisor-private context; workers do not.
- Expired episodic run memory is filtered, while current run evidence carries
  `run_id`, `task_id`, owner, and `expires_at` metadata.
- Hydration observes a deterministic character budget in shared → actor-private
  → user → current-run order and emits reconstructable `ContextItem` memory
  provenance.
- A fresh `RunCoordinator`, ASGI app, `TestClient`, HTTP store, and policy over
  the same SQLite DB recover the project goal, decision, and prior worker trial.
  This is a service restart, not reuse of `InMemoryScopedStore`; terminal memory
  traces carry returned memory IDs.
- Re-running the proof in the same work directory creates isolated run, project,
  task, goal, and trace IDs while appending to the existing evaluation history.

## Production service lane

E2A's `HttpAgentMemoryStore` follows agent-memory commit `494610f`:

```bash
export AGOS_MEMORY_URL=http://localhost:8000
uv run uvicorn agent_memory.api.main:app
```

The CLI and Telegram entry points construct `ScopedMemoryWorker` over
`HttpAgentMemoryStore(AGOS_MEMORY_URL)`. They freeze validated user, project,
run, task, worker, and worker-actor context before any model-visible action.
Defaults are deliberately safe for one local user only; multi-user callers must
provide their authenticated stable IDs through `AGOS_MEMORY_*` settings or CLI
flags. Short-term read/write/hydration is gated through durable
`RunCoordinator` status: received/planning/running/paused are active, while
completed/failed/cancelled runs are excluded.

The adapter calls `POST /remember` and `POST /recall`, preserving
the service response's memory ID, namespace, metadata, kind, score, and
creation timestamp on recalled records. The Agentic OS policy—not a worker or
HTTP caller—derives namespaces before either call.

The former raw `MemoryWorker`/`MemoryToolExecutor` bridge has been removed from
Agentic OS. `default_workers` accepts only `ScopedMemoryPolicy`, so custom
supervisor construction cannot accidentally reintroduce the namespace bypass.

## Repository checks

```bash
uv run ruff check .
uv run pytest -q
uv run agos eval e0 --workdir /tmp/agentic-os-e0
uv run agos eval e1 --workdir /tmp/agentic-os-e1
uv run agos eval e2 --workdir /tmp/agentic-os-e2
git diff --check
```

## Parent verification evidence

The parent verification record before this remediation was: Agentic OS **129
passed**; E0/E1/E2 **5/5**; agent-memory live HTTP restart passed;
agent-memory **53 passed, 2 skipped**; golden multihop **83**, glossary **100**,
temporal **100**, papers **90**. The Luna review nevertheless failed the prior
candidate because its claimed restart reused an in-memory store and production
paths still used the raw executor. This revision addresses those findings with
the real ASGI tests and proof above; CI now checks out the exact `494610f` ref
and runs its unit plus golden lane, never floating `main`.

## Deferred work

E2A intentionally does not perform physical expiry deletion, reflection-driven
promotion, or tokenizer-backed budgeting. It filters expired records at the
hydration boundary; lifecycle deletion and consolidation remain the backing
service's responsibility.
