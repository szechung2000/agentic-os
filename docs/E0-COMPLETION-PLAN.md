# E0 Completion — Debate-Based Plan

## Context

The independent reviewer found **blocking issues** preventing E0 acceptance:

1. **Test suite not clean** — `test_contracts.py` expects `context_refs` to be rejected but `TaskContract` accepts them
2. **Instrumentation not integrated** — `ComponentTracer` used only by synthetic E0 proof, not by supervisor/workers/tools
3. **Redaction fails before persistence** — secrets in event `data`, input/output artifacts, metrics persisted verbatim
4. **Checkpoint/event integrity insufficient** — `RunCoordinator.load()` ignores checkpoint `content_hash`; event payloads lack integrity hashes

All must be resolved with passing tests before merge.

---

## Debate: GPT-5.6 (Planner A) vs Sonnet 5 (Planner B)

### GPT-5.6: Task Graph Structure

```
E0-FIX-1: Contract enforcement
  ├─ E0-FIX-1a: Reject raw context_refs in TaskContract (add validator)
  ├─ E0-FIX-1b: Update tests to match stricter contract
  └─ E0-FIX-1c: Verify no downstream breakage

E0-FIX-2: ComponentTracer integration
  ├─ E0-FIX-2a: Wrap Supervisor.handle() with tracer
  ├─ E0-FIX-2b: Wrap Worker.run() with tracer
  ├─ E0-FIX-2c: Wrap tool calls with tracer
  ├─ E0-FIX-2d: Distinguish cancellation/timeout from failure
  └─ E0-FIX-2e: Propagate trace_id/span_id through async boundaries

E0-FIX-3: Redaction at persistence boundary
  ├─ E0-FIX-3a: Add recursive redaction to EventStore.append()
  ├─ E0-FIX-3b: Redact artifact content before ArtifactStore.put()
  ├─ E0-FIX-3c: Verify redaction in trace integrity check
  └─ E0-FIX-3d: Test with multiple secret patterns

E0-FIX-4: Checkpoint & event integrity
  ├─ E0-FIX-4a: Verify checkpoint hash on load (already done for checkpoints)
  ├─ E0-FIX-4b: Add event payload hash + hash chain to run_events
  ├─ E0-FIX-4c: Add verify_events_integrity() for full trace
  └─ E0-FIX-4d: Test tamper detection for both checkpoints and events

E0-FIX-5: Full suite verification
  ├─ E0-FIX-5a: Run all tests clean
  ├─ E0-FIX-5b: Run agos eval e0 with all 5 cases passing
  ├─ E0-FIX-5c: Run recorded replay with live_calls=0 and terminal_status=failed
  └─ E0-FIX-5c: Generate e0-verification.md with updated proof
```

### Sonnet 5: Refined Task Graph

I agree with the structure but **split further** for single-responsibility:

```
E0-FIX-1: Contract enforcement [SEQUENTIAL]
  ├─ 1a: Add TaskContract validator rejecting context_refs
  ├─ 1b: Fix test_contracts.py to expect rejection
  ├─ 1c: Verify all dependent tests pass
  └─ 1c: Verify E0 proof still passes

E0-FIX-2: Tracer integration [PARALLEL-LEAVES]
  ├─ 2a: Add tracer to Supervisor.handle() → emits supervisor spans
  ├─ 2b: Add tracer to Worker.run() → emits worker spans
  ├─ 2c: Add tracer to tool bridge → emits tool spans
  ├─ 2d: Add CancellationError/TimeoutError handling in ComponentTracer
  └─ 2e: Thread trace_id through async contextvars (no manual passing)

E0-FIX-3: Redaction at boundary [SEQUENTIAL]
  ├─ 3a: Recursive redact EventStore.append() event.data + nested fields
  ├─ 3b: Redact ArtifactStore.put() content before hashing
  ├─ 3c: Add secret detection to verify_trace() → fail if unredacted
  └─ 3d: Test with API keys, tokens, passwords, private keys

E0-FIX-4: Integrity hardening [SEQUENTIAL]
  ├─ 4a: Add event.payload_hash + prev_hash chain to run_events
  ├─ 4b: Verify checkpoint hash on load (done — verify with tamper test)
  ├─ 4c: Add EventStore.verify_integrity(trace_id) with full chain check
  └─ 4d: Tamper test: SQLite UPDATE → integrity check fails

E0-FIX-5: Verification gate [SEQUENTIAL]
  ├─ 5a: pytest -q clean (0 failed)
  ├─ 5b: agos eval e0 → 5/5 passing
  ├─ 5c: trace replay → live_calls=0, terminal_status=failed
  └─ 5d: Update e0-verification.md
```

### Consensus

**Sonnet 5's finer granularity wins** — each leaf is testable in isolation, parallel leaves can run simultaneously, and sequential dependencies are explicit. The contextvars approach for trace_id is cleaner than manual threading.

---

## Final Acceptance Criteria (from roadmap.md lines 19-44 + reviewer gaps)

| ID | Criterion | Test Evidence Required |
|---|---|---|
| AC-1 | Process stops mid-run, resumes without duplicate work | `test_run_recovers_checkpoint_plus_later_events`, `test_completed_task_is_idempotent_after_restart` |
| AC-2 | Every component call emits one start + one terminal event | Supervisor, Worker, Tool spans all present in E0 proof trace |
| AC-3 | Broken parent spans, missing terminal, secrets fail integrity | `test_integrity_rejects_missing_terminal_and_broken_parent`, redaction test |
| AC-4 | Failed fixture diagnosed via recorded replay (live_calls=0) | `test_failed_component_preserves_partial_artifact_for_recorded_replay` |
| AC-5 | Invalid worker output rejected with bounded correction | `test_bounded_correction_repairs_invalid_contract_once` |
| AC-6 | Replanning records old/new plan + reason | `test_plan_revision_preserves_versions_and_reason` |
| AC-7 | Provider replacement without consumer branches | Registry test + E0 `provider-replacement` case |
| AC-8 | Model-visible context reconstructable from provenance | `ContextItem` provenance validation + `ContextItem` in E0 proof |
| AC-9 | Reversible registration + cleanup | Registry disposer test |
| AC-10 | Every component kind traceable | E0 `component-kind-coverage` case (9 kinds) |
| AC-11 | **NEW: No test failures** | `pytest -q` → 0 failed |
| AC-12 | **NEW: Tracer on real supervisor/worker calls** | Spans for supervisor, workers, tools in E0 trace |
| AC-13 | **NEW: Redaction before persistence** | Secrets redacted in event data, artifacts, metrics |
| AC-14 | **NEW: Event integrity chain** | Tampered event → integrity check fails |

---

## Constraints

- **No model may verify its own work** — implementer ≠ verifier
- **Tests before code** — TDD for every fix
- **Single-responsibility leaves** — each fix has isolated test
- **Contextvars for trace propagation** — no manual trace_id passing
- **Redaction at boundary** — EventStore.append() and ArtifactStore.put()
- **Event integrity chain** — payload_hash + prev_hash per event
- **5/5 E0 proof passing** — mandatory gate

---

## Test Strategy

| Layer | Tool | Scope |
|---|---|---|
| Unit | pytest | Each leaf fix has dedicated test |
| Integration | pytest | E0 proof runs full stack |
| Contract | pytest | Schema validation, bounded correction |
| Durability | pytest | Restart, checkpoint, tamper detection |
| Observability | CLI + pytest | Trace tree, verify, replay |
| E2E | `agos eval e0` | All 5 cases passing |

---

## Implementer/Verifier Assignment

| Role | Model | Rationale |
|---|---|---|
| Planner A (debate) | GPT-5.6 | Architecture debate done |
| Planner B (debate) | Sonnet 5 | Architecture debate done |
| **Implementer** | **Codex Terra** | Strong at surgical multi-file edits, CLI tooling |
| **Verifier** | **Sonnet 5** | Different model family; strong review discipline |
| **Orchestrator** | **GPT-5** (this session) | Coordinates, debates, gates |

---

## Execution Order

```
Phase 1: E0-FIX-1 (contract) → E0-FIX-2 (tracer) [parallel leaves]
Phase 2: E0-FIX-3 (redaction) → E0-FIX-4 (integrity) [sequential]
Phase 3: E0-FIX-5 (verification gate)
```

Each phase: implementer writes code + tests → verifier reviews → if FAIL, implementer retries (max 2) → if PASS, next phase.

---

## Deliverables

1. Clean test suite (0 failed)
2. `agos eval e0` → 5/5
3. Trace with all 9 component kinds, redaction verified, recorded replay works
4. Updated `docs/e0-verification.md`
5. PR with `[verified]` prefix