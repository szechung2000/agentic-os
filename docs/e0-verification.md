# E0 Implementation and Verification

E0 establishes the durable, inspectable substrate used by later runtime, memory, planning, evaluation, and Telegram epics.

## Implemented components

| Module | Proof surface |
|---|---|
| `core/contracts.py` | Versioned Pydantic contracts for goals, tasks, context provenance, worker results, evaluations, artifacts, approvals, and events |
| `core/artifacts.py` | Content-addressed artifact writes, deduplication, and hash verification |
| `core/events.py` | SQLite append-only event store, correlated component spans, redaction, filtering, checkpoints, and trace integrity |
| `core/state.py` | Run state machine, legal transitions, plan revisions, task idempotency, checkpoints, and event replay after restart |
| `core/registry.py` | Typed extension registry, reversible registration, resource cleanup, and runtime-preset composition |
| `core/trace.py` | Parent/child interaction trees, filters, integrity reports, and recorded artifact replay |
| `core/validation.py` | Bounded correction for invalid structured output |
| `evals/harness.py` | Versioned suites/cases, append-only JSONL history, and regression comparison |
| `evals/e0.py` | Executable acceptance proof for contracts, restart, tracing/replay, all component kinds, and provider replacement |
| `workers/web.py` | Preserved web-research worker scaffold with input validation and tests |

## Verification commands

### Full automated suite

```bash
uv run pytest -q
uv run ruff check src tests
git diff --check
```

### Executable E0 proof

Use a fresh work directory so the produced database, artifacts, and history remain available for inspection:

```bash
PROOF_DIR=$(mktemp -d /tmp/agentic-os-e0-proof.XXXXXX)
agos eval e0 --workdir "$PROOF_DIR" --candidate "$(git rev-parse --short HEAD)"
```

The command must report five passing cases:

```text
E0 score: 5/5 (100%)
- contract-validation: PASS
- restart-recovery: PASS
- trace-integrity-replay: PASS
- component-kind-coverage: PASS
- provider-replacement: PASS
```

It prints concrete paths for:

- `events.db` — SQLite event log and checkpoint;
- `artifacts/` — content-addressed replay payload;
- `eval-history.jsonl` — immutable evaluation record;
- trace and span IDs for inspection.

### Trace inspection

```bash
agos trace tree "$TRACE_ID" --db "$PROOF_DIR/events.db" --artifacts "$PROOF_DIR/artifacts"
agos trace verify "$TRACE_ID" --db "$PROOF_DIR/events.db" --artifacts "$PROOF_DIR/artifacts"
agos trace replay "$TRACE_ID" "$SPAN_ID" --db "$PROOF_DIR/events.db" --artifacts "$PROOF_DIR/artifacts"
```

The proof deliberately records a failed component with a partial artifact. Recorded replay must return that verified artifact with `terminal_status=failed` and `live_calls=0`. This demonstrates diagnosis without repeating an external call or side effect.

## Acceptance evidence mapping

| E0 acceptance criterion | Automated evidence |
|---|---|
| Restart without duplicate work | `test_run_recovers_checkpoint_plus_later_events`, `test_completed_task_is_idempotent_after_restart`, E0 `restart-recovery` case |
| One start and one terminal event | `ComponentTracer` success/failure tests and `EventStore.verify_trace` |
| Broken parents/missing terminal/secrets fail | `test_integrity_rejects_missing_terminal_and_broken_parent`, `test_integrity_rejects_secret_like_event_payload` |
| Failed fixture recorded replay | `test_failed_component_preserves_partial_artifact_for_recorded_replay`, E0 `trace-integrity-replay` case |
| Invalid output bounded correction | `test_bounded_correction_repairs_invalid_contract_once`, `test_bounded_correction_stops_after_limit` |
| Replanning history | `test_plan_revision_preserves_versions_and_reason` |
| Provider replacement without consumer branches | Registry replacement test and E0 `provider-replacement` case |
| Reconstructable model context | `ContextItem` provenance validation test |
| Reversible registration and cleanup | Registry disposer/resource-release test |
| Every component kind traceable | E0 `component-kind-coverage` case covers supervisor, worker, runtime, tool, memory, skill, evaluator, interface, and project store |
| Evaluation history and regression detection | Eval history and `compare_runs` tests |

## What the proof does not claim

E0 does not yet execute Claude Code, Codex, or agy; those are E1 runtime adapters. It also does not yet implement agent-memory namespace policy (E2), autonomous planning/research (E3), full trial matrices (E4), or the interaction web UI (E6). E0 provides the durable contracts, tracing, replay, extension seams, and evaluation substrate those epics require.
