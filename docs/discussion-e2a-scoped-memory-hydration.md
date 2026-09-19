# Discussion — E2A Scoped Memory Hydration

## Inputs

- `agent-memory` E1-E6, reranking/multihop/evals, and keyed upsert are merged.
- The second-brain MVP already consumes agent-memory's keyed-upsert contract.
- Agentic OS E0 durable core and E1 runtime adapters are merged.
- Agentic OS roadmap identifies E2 memory scopes and lifecycle as the next epic.
- Local `agent-memory/main` has protected, uncommitted rerank-surface edits; E2A must not touch them.

## Supervisor assessment

The highest-leverage next step is not another isolated retrieval feature. It is the first cross-project slice that proves agent-memory acts as the durable, policy-controlled brain for multiple specialist agents.

The initial slice should implement namespace derivation, visibility enforcement, bounded hydration, provenance, expiry filtering, and restart recovery. Reflection/consolidation automation remains a separate slice because combining it now would hide the security and hydration boundary inside a large change.

## Alternatives considered

1. **Finish rerank exposure:** small and useful cleanup, but the reranker had no score gain and roughly 8x latency. It should remain optional and be completed separately from the dirty worktree.
2. **Dashboard D1:** portfolio polish and useful operations visibility, but mostly presents data already available and does not unlock autonomous workflows.
3. **Agentic OS E2A:** proves the key architectural claim—shared plus private durable memory across agents—and directly connects the two portfolio repositories.

## Architecture council

Luna's review failed the first E2A candidate: the policy unit tests were real,
but production CLI/Telegram still built raw `MemoryToolExecutor`, workers could
write shared memory, and the restart proof reused `InMemoryScopedStore`. Luna
recommended a policy-backed worker, supervisor-only promotion, durable
RunCoordinator lifecycle checks, and a pinned live-ASGI restart gate.

Terra's remediation follows that recommendation: production now uses
`ScopedMemoryWorker` + `HttpAgentMemoryStore(AGOS_MEMORY_URL)` with frozen,
validated entry context; the raw executor bridge has been removed. Shared
writes/promotions require supervisor authority and verify source ID, namespace,
user/project/run ownership, and agent metadata. A fresh app/TestClient/store/
policy and a new RunCoordinator recover from the same SQLite DB; terminal run
states cannot read, write, or hydrate short-term memory. `ContextItem` now
requires storage provenance fields for memory context.

## Proposed reconciliation

Adopt the scoped boundary only with the live pinned-service gate. The pinned
agent-memory API has no get-by-ID endpoint, so promotion accepts only a source
record actually returned by the current service adapter; arbitrary fabricated
records are rejected. A future service get-by-ID endpoint can remove that
session-cache limitation without weakening policy validation.

## Verification policy

- Strict TDD for production behavior.
- Implementer cannot be the sole verifier.
- Existing agent-memory golden scores may not regress.
- Missing or malformed reviewer output is a failure, not approval.

## Parent verification evidence

Before the remediation, the parent verification record was Agentic OS **129
passed**, E0/E1/E2 **5/5**, and real live agent-memory HTTP restart passed;
agent-memory reported **53 passed, 2 skipped**, and golden evidence was
multihop **83**, glossary **100**, temporal **100**, papers **90**. The failed
Luna review correctly rejected that candidate despite those aggregate numbers,
because it did not exercise the claimed durable production boundary. This
revision retains those parent results as historical evidence and adds the
independent pinned ASGI integration/proof and CI lane.

A second Luna review rejected a deprecated raw-worker compatibility path and a
golden lane that used the hash fallback without enforcing score thresholds.
The final candidate removes that compatibility path entirely. Its pinned CI
lane installs `local-embeddings` and fails unless multihop/glossary/temporal/
papers remain at least 83/100/100/90.

The final independent Luna gate returned **PASS** with no blockers. It verified
135 Agentic OS tests, E0/E1 at 5/5, repeatable E2 at 5/5 with a fresh ASGI
backend, the pinned agent-memory suite at 53 passed/2 skipped, and BGE golden
scores of 83/100/100/90. The reviewer confirmed the worktree status was
unchanged by verification.
