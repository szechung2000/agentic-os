# Model-agnostic Control Plane Roadmap

Incremental plan based on the existing Agentic OS E0-E2 implementation.
Do not duplicate runtime adapters, the event database, or the evaluation harness.

| PR | Deliverable | Exit criteria |
|---|---|---|
| **1: Tracing** | Persist sanitized CLI event envelopes and opt-in LangSmith metadata export | One local worker run has correlated component/runtime events, trace integrity passes, offline tests pass |
| 2: LangGraph | Plan/delegate/review workflow using runtime adapter registry | Swap orchestrator between Codex and Claude with no model API keys, replay avoids duplicate side effects |
| 3: Control API | FastAPI run, approval, cancel, resume and SSE endpoints, isolated Git worktrees | Cancellation/approval tests, event replay cursor, bounded worker permissions |
| 4: Dashboard | React task graph, event timeline, stream viewer, approvals | View and intervene in a live deterministic test run |
| 5: Reliability | Golden tests, failure injection, GitHub PR publication gates | Safe restart, no unauthorized merge or destructive changes |

## Constraints

- One owner, local WSL2 first, existing CLI subscription authentication.
- SQLite and the existing artifact store remain the starting durable backend.
- Cloud export is off unless explicitly requested, with metadata only.
- No new Redis, Celery, Kubernetes, vector database, or independent scheduler.
- No automatic merge or destructive Git action.
- Native adapters may lack some operations (e.g. interactive steering). Reject
  unsupported capabilities instead of fabricating a common feature.
- LangSmith is a trace viewer; approvals and execution remain control-plane responsibilities.

## PR 1 acceptance checklist

- [x] Retain E0/E1/E2 contracts and tests.
- [x] Map all received runtime lifecycle events to a shared event type.
- [x] Link runtime events to the enclosing component span, task, and run.
- [x] Do not copy CLI stdout/stderr into the event log or cloud projection.
- [x] Export remains off without explicit user confirmation.
- [x] No additional model API dependency.
- [ ] GitHub CI confirms the tests and lint checks.
- [ ] Live CLI smoke test with separately authenticated subscriptions (manual, later).

## Decisions deferred

LangGraph checkpoint strategy, PostgreSQL migration threshold, LangSmith
sampling/retention, remote worker isolation, and React deployment are deferred
until executable evidence requires them.
