# PRD — E2A Scoped Memory Hydration

## Problem

Agentic OS currently exposes agent-memory through a generic worker. Callers may choose arbitrary namespaces, no policy defines which scopes a worker may read or write, and a restarted supervisor has no bounded way to reconstruct durable project context. This leaves the architecture's E2 memory contract unimplemented even though agent-memory itself is mature.

## Goal

Deliver the first demoable E2 vertical slice: policy-owned namespace mapping, visibility enforcement, and budgeted hydration of durable Agentic OS context from agent-memory.

## Scope

- Typed memory identity/context for user, project, run, supervisor, and worker.
- Deterministic namespace mapping:
  - `user/{user_id}`
  - `project/{project_id}/shared`
  - `project/{project_id}/supervisor`
  - `project/{project_id}/worker/{worker_id}`
  - `run/{run_id}/short-term`
- A policy boundary that derives namespaces; workers cannot submit raw namespaces.
- Explicit read/write permissions by actor and scope; workers can read shared
  memory but only supervisor/explicit curator authority can write or promote it.
- Layered hydration for shared project, actor-private, stable user, and run-short-term memory.
- A deterministic context budget with provenance-bearing `ContextItem` output.
- Episodic short-term writes carrying run/task ownership and expiry metadata.
- A real agent-memory adapter plus an in-memory test double.
- A pinned FastAPI/SQLite proof demonstrating worker isolation, supervisor
  promotion, expiry filtering, and genuine fresh-service restart hydration.

## Non-goals

- LLM reflection or automatic promotion decisions.
- Running the existing agent-memory consolidation job from Agentic OS.
- Redis, distributed coordination, or Docker deployment.
- Prompt summarization or tokenization via a provider API.
- Changes to agent-memory retrieval ranking or golden fixtures.
- UI, Telegram commands, or the dashboard.

## Users

- Supervisor: hydrates shared, supervisor-private, user, and current-run context.
- Worker: hydrates shared, own-private, user, and current-run context.
- Memory curator (later): promotes selected worker/run facts into shared durable memory.

## Requirements

1. Namespace strings are created only by a validated scope mapper.
2. Worker A cannot read or write Worker B's private scope.
3. Shared project facts are visible to supervisor and all project workers.
4. Supervisor-private facts are unavailable to workers.
5. Run-short-term writes are episodic and include run/task ownership plus expiry metadata.
6. Expired short-term memories are excluded during hydration.
7. Hydration order is deterministic and budget bounded.
8. Every hydrated item includes reconstructable memory provenance.
9. A fresh service/store/policy plus a new RunCoordinator over the same durable
   backend reconstructs prior project context.
10. Memory calls emit component traces where a tracer is supplied.

## Acceptance criteria

- Two workers share a promoted project fact but cannot retrieve each other's private facts.
- Supervisor sees supervisor-private facts; workers do not.
- An expired run memory is absent while an unexpired run memory is present.
- Hydration never exceeds its configured character budget and preserves layer priority.
- Returned `ContextItem` values use `provenance_type="memory"` and stable memory IDs.
- A restart test creates a fresh pinned agent-memory ASGI service, TestClient,
  HTTP store, policy, and RunCoordinator over the same SQLite database and
  retrieves the project goal, decision, and prior trial fact.
- `uv run pytest -q`, `uv run ruff check .`, and `git diff --check` pass in agentic-os.
- The full agent-memory test suite and golden eval gate pass without score regression.

## Demo

An executable E2 proof writes a user preference, supervisor-written shared
project decision, two worker-private trial notes, and short-term run evidence.
The supervisor promotes the service-returned run source. It hydrates Worker A,
Worker B, and the supervisor, then starts a fresh service stack and proves
recovery from the same backing store.

## Definition of done

- Production policy and adapter code, not only fixtures.
- Tests map directly to every acceptance criterion.
- Verification document records commands and output.
- The failed Luna review and its remediation are recorded in the discussion and
  verification documents.
- CI includes the pinned agent-memory unit/golden lane; no dependency follows
  floating `main`.
