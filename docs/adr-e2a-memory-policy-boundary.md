# ADR — Agentic OS Owns Memory Policy; agent-memory Owns Storage

- **Status:** Accepted
- **Date:** 2026-09-19
- **Decision owners:** Agentic OS supervisor

## Context

`agent-memory` already provides semantic/episodic records, namespaces, metadata, embeddings, hybrid recall, consolidation, and golden evaluations. Agentic OS currently forwards generic memory tool payloads, which lets callers choose namespaces directly and cannot enforce the scope model documented in `docs/architecture.md`.

E2 needs strict visibility, deterministic hydration, short-term expiry, and provenance without duplicating retrieval infrastructure.

## Decision

Introduce a policy layer in Agentic OS with three seams:

1. `MemoryScopeMapper` converts validated identities into canonical namespaces.
2. `ScopedMemoryStore` is the minimal storage/recall protocol used by policy code.
3. `MemoryHydrator` applies actor visibility, ordered layers, expiry filtering, and context budgets, returning provenance-bearing `ContextItem` objects.

The concrete adapter uses agent-memory as the backing store. Production CLI and
Telegram build `ScopedMemoryWorker` over `HttpAgentMemoryStore(AGOS_MEMORY_URL)`;
workers and model-visible tool schemas never accept raw namespace strings.
Validated entry IDs are frozen in an actor context before worker execution.

Workers can read project-shared scope but cannot write or promote it. Only the
supervisor (or a future explicit curator authority) can do so, and promotion
requires a source record returned by the backing store with matching ID,
namespace, user/project/run ownership, and agent metadata. Run-short-term
access is authorized only while the injected durable RunCoordinator lifecycle
reports an active run.

Short-term run memories are stored as episodic entries with ownership and `expires_at` metadata. E2A filters expiry during hydration. Physical deletion and consolidation remain agent-memory lifecycle concerns and are deferred.

## Hydration order

1. Shared project memory.
2. Actor-private memory (supervisor or current worker only).
3. Stable user memory.
4. Current run short-term memory.

The first slice uses a deterministic character budget as an offline, dependency-free proxy for prompt tokens. A future tokenizer can implement the same budget protocol.

## Consequences

### Positive

- Visibility rules are centralized and testable.
- Agent-memory remains reusable and provider-neutral.
- Restart recovery follows from the durable backing store and is exercised via
  a fresh pinned FastAPI/TestClient/HTTP-store/policy instance over SQLite.
- Model-visible context carries stable memory provenance.
- The architecture can later add reflection/promotion without changing storage.

### Negative

- Agentic OS needs an adapter richer than the current generic `MemoryToolExecutor` seam because E2 requires IDs, metadata, actor identity, session ownership, and expiry.
- Character budgeting is approximate until a tokenizer-backed implementation lands.
- Multiple ordered recall calls add latency; E2 evaluation must report it.

## Rejected alternatives

### Let workers pass namespace strings

Rejected because it makes private-memory isolation advisory rather than enforced.

### Put Agentic OS visibility logic inside agent-memory

Rejected because user/project/supervisor/worker semantics are orchestration policy, not generic storage semantics.

### Build dashboard D1 first

Rejected for this milestone because it improves presentation but does not advance the flagship cross-project orchestration story.

### Finish optional rerank exposure first

Rejected as the main next milestone because reranking was evaluated at high latency with no score gain and remains appropriately off by default. The existing dirty changes should be handled separately without blocking E2A.

## Follow-ups

- E2B: reflection, candidate promotion, consolidation scheduling, and physical TTL cleanup.
- E2C: token-aware budgeting and trace/evaluation metrics.
- E6: expose memory provenance and lifecycle events in Telegram/timeline views.
