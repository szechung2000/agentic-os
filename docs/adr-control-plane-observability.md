# ADR: Local-first agent control plane and observability

**Status:** Proposed (PR 1)  
**Scope:** Single-owner, subscription-authenticated coding-agent processes.

## Decisions

1. Preserve `RunCoordinator` and `EventStore` as the run-state and audit authorities.
   Do not add a second workflow database. LangGraph can become a workflow driver
   in a later PR; its state must reconcile with existing durable run events.
2. Treat Claude Code, Codex, and agy as interchangeable **runtime adapters**,
   not direct LangChain model API calls. Native CLI authentication stays local.
3. Capture provider-neutral `runtime.*` event envelopes under the existing
   `ComponentTracer` span. No new database schema is required.
4. Keep CLI stdout/stderr in the existing artifact store. Local event records
   retain only type, correlation identifiers, and character count for streams.
   Explicit progress/status summaries are redacted and capped to 240 characters.
5. Make LangSmith an explicit post-run projection, not a required dependency or
   source of truth. Upload only component identities, run/task identifiers,
   operation, status, output hash, and event counts. No raw prompts, source code,
   memory contents, or stream output are sent by this adapter.
6. The export command requires `--confirm-upload` and a separately installed
   LangSmith SDK with its own tracing credential. It never starts a coding agent
   or changes an existing run result.
7. Live execution must not retry a started mutating CLI after a transport failure;
   stop its process and record the failure before a new attempt is considered.

## Boundary

```text
LangGraph (future) -> RuntimeWorkerBridge -> native CLI adapters
                           |                     |
                           |                     -> existing ArtifactStore
                           v
                    EventStore (SQLite)
                           |
                           +-- local trace CLI (existing)
                           +-- explicit metadata projection -> LangSmith (optional)
```

## Risks and limitations

- This increment captures streamed events only when a bridge has a tracer.
- SDK support for live session steering is not implied by this event capture.
- Local artifact output may contain secrets already emitted by a provider.
  It must be access-controlled separately from sanitized event metadata.
- The LangSmith projection is historical, not a live interactive trace.
- Explicit task contracts and decisions will need additional typed
  events as LangGraph orchestration is introduced.
- CLI subscription access is plan- and provider-policy-dependent. The
  controller is personal, single-user infrastructure, not a token relay.

## Verification

Run `uv run pytest -q`, `uv run ruff check .`, and offline E0/E1/E2 proofs.
All new tests use fake runtime events and make no network or model calls.
