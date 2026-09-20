# E1 Headless Runtime Adapters Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Execute specialist tasks through interchangeable Claude Code, Codex, and agy headless CLIs while preserving structured results, lifecycle control, isolation, and durable trace evidence.

**Architecture:** Add a provider-neutral asynchronous `RuntimeAdapter` protocol and typed runtime models at the core boundary. Implement a shared subprocess lifecycle base for command construction, stdout/stderr capture, timeout/cancellation, partial-artifact preservation, and structured-result parsing; keep CLI-specific behavior in thin Claude, Codex, and agy adapters. Add capability discovery and selection policy without hardcoding a provider into the supervisor, and record adapter/model/availability decisions through existing runtime spans.

**Tech Stack:** Python 3.11+, asyncio subprocesses, Pydantic v2 contracts, SQLite event/tracing layer, pytest/pytest-asyncio, Ruff, local fake executables for deterministic tests.

---

## Scope and constraints

- Work from `origin/main`, which contains merged E0 (`6924cf7`).
- No API keys are needed for the default test lane. Real CLI smoke tests should be opt-in and skipped when credentials or binaries are unavailable.
- Do not expose chain-of-thought. Persist explicit status, summaries, artifacts, diagnostics, and structured results only.
- Do not let adapters own project planning or silently mutate the caller's worktree.
- Every adapter receives an explicit validated `Workspace`; write-capable execution must use an enforceable isolated workspace policy, not merely a subprocess `cwd`.
- Preserve existing E0 behavior and the 55-test baseline; no regression in `uv run ruff check .`, `uv run pytest -q`, or `uv run agos eval e0 --workdir <fresh-dir>`.

## Proposed file layout

- Create `src/agentic_os/runtimes/__init__.py`
- Create `src/agentic_os/runtimes/contracts.py` — `Workspace`, runtime handles, events, capabilities, availability failures, trace fields, and structured execution result models.
- Create `src/agentic_os/runtimes/base.py` — `RuntimeAdapter` protocol and shared async subprocess lifecycle implementation.
- Create `src/agentic_os/runtimes/claude.py` — Claude Code headless adapter.
- Create `src/agentic_os/runtimes/codex.py` — Codex headless adapter.
- Create `src/agentic_os/runtimes/agy.py` — agy headless adapter.
- Create `src/agentic_os/runtimes/discovery.py` — executable/auth/capability discovery and typed availability results.
- Create `src/agentic_os/runtimes/routing.py` — capability-based adapter selection and fallback policy.
- Create `src/agentic_os/runtimes/worker_bridge.py` — `RuntimeWorkerBridge` adapting typed runtime execution to the legacy `Worker`/`TaskResult` supervisor boundary.
- Modify `src/agentic_os/core/contracts.py` only if existing `TaskContract`/`WorkerResult` fields need a backward-compatible runtime reference.
- Modify `src/agentic_os/core/registry.py` to register/resolve runtime adapters through `ExtensionKind.RUNTIME`.
- Modify `src/agentic_os/supervisor/supervisor.py` to dispatch through the selected adapter without provider-specific branches.
- Modify `src/agentic_os/core/events.py`/trace integration to include runtime name, version, model, command metadata (redacted), and workspace identifiers.
- Create focused tests under `tests/test_runtime_contracts.py`, `tests/test_runtime_subprocess.py`, `tests/test_runtime_adapters.py`, `tests/test_runtime_discovery.py`, and `tests/test_runtime_routing.py`.
- Add a short E1 verification document under `docs/e1-verification.md` and update `docs/roadmap.md` only after acceptance tests pass.

## Implementation tasks

### Task 0: Harden E0 lifecycle and artifact boundaries for runtime execution

- Write regression tests proving cancellation and timeout produce `component.call.cancelled` and `component.call.timed_out`, respectively, with exactly one terminal event.
- Extend `ComponentTracer` or add an equivalent explicit terminal-status API without changing existing success/failure behavior.
- Ensure runtime output artifacts are written to the caller-provided durable `ArtifactStore`, not a temporary directory that disappears after the worker returns.
- Add tests proving runtime metadata is redacted before persistence and that sensitive environment values never enter event payloads or artifacts.
- Run the new focused tests and the complete E0 acceptance proof: `uv run agos eval e0 --workdir <fresh-dir>`.
- Commit: `fix: harden E0 lifecycle boundaries for runtimes`.

### Task 1: Define typed runtime boundary contracts

- Write failing tests for `Workspace`, runtime handles, runtime events, structured execution results, capability sets, typed availability failures, and `RuntimeTraceFields`.
- Define immutable/validated Pydantic models with explicit statuses: running, completed, failed, cancelled, timed_out, unavailable.
- Define `Workspace(root, allow_write)` with an existing resolved absolute root, symlink-escape checks, and an explicit isolation/write policy. Do not permit `/`, an unvalidated caller cwd, or a path outside the approved workspace boundary.
- Define `RuntimeTraceFields` with runtime/CLI version, requested/effective model, session ID, workspace ID, command fingerprint, selected runtime, and fallback rationale; it must contain no raw command or secret values.
- Ensure failed and timed-out results carry diagnostic failures and may carry partial artifact references.
- Ensure no raw secrets or unrestricted command text is serialized into durable events.
- Run the focused contract tests, then the existing contract tests.
- Commit: `feat: add E1 runtime boundary contracts`.

### Task 2: Add the `RuntimeAdapter` protocol and subprocess lifecycle

- Write tests using a temporary fake executable for start, event streaming, result retrieval, stop, cancellation, timeout, exit-code failure, stdout/stderr capture, partial-output preservation, workspace enforcement, and steering.
- Implement async process ownership with explicit process groups where supported, bounded termination escalation, and cleanup in all terminal paths.
- Implement `start(task, workspace)`, `events(handle)`, `result(handle)`, `steer(handle, message)`, and `stop(handle)` with a clear handle state machine. `result()` must be idempotent and return the one terminal `RuntimeExecutionResult`.
- Pin every child process to the validated workspace root, reject path/symlink escapes, and reject `allow_write=False` unless the adapter can enforce read-only behavior through its sandbox/OS mechanism.
- Add structured-result parsing from a documented JSON envelope, with unstructured fallback diagnostics rather than fabricated success.
- Preserve stdout/stderr as content-addressed artifacts when a process fails or times out.
- Test that a fake process spawning a child is fully terminated during timeout/cancellation and that the corresponding runtime span has one terminal status.
- Run focused subprocess tests and the full E0 suite.
- Commit: `feat: add managed runtime subprocess lifecycle`.

### Task 3: Implement Claude, Codex, and agy command adapters

- Write adapter tests against fake executables that assert exact argument construction, working directory, explicit environment allowlists, model selection, and structured output handling for Claude, Codex, and agy.
- Implement thin command builders for `claude -p`, `codex exec`, and `agy -p`, keeping the common lifecycle in the base adapter.
- Add provider-specific flags for non-interactive output, bounded execution, and model selection without enabling dangerous permissions by default.
- Make steering/session continuation explicit capabilities; return a typed unsupported-operation result where a CLI cannot provide it rather than pretending it succeeded.
- Forward only an explicit common/per-runtime environment allowlist; never inherit `os.environ` wholesale. Test that unrelated injected secrets are absent from child environments, traces, and artifacts.
- Ensure command metadata is redacted before tracing and that API keys are never included in event payloads.
- Test supported and unsupported steering and session continuation paths; unsupported operations must not create a process or claim delivery.
- Run adapter tests and all existing tests.
- Commit: `feat: add Claude Codex and agy runtime adapters`.

### Task 4: Add availability discovery and fallback routing

- Write tests for missing executable, executable present with unknown authentication, explicit CLI authentication failure, executable/version discovery, unsupported capability, and ordered fallback.
- Implement discovery using executable lookup plus safe version/help probes; classify results as available, missing, `auth_unknown`, unauthenticated only for an explicit CLI auth error, incompatible, or probe_failed.
- Keep authentication checks non-invasive and avoid interactive login flows in headless mode.
- Implement routing by required capabilities, optional preferred runtime, availability, and an explicit ordered fallback list. Registry iteration and alphabetical sorting must never determine fallback order. Return a typed failure if no compatible adapter exists.
- Permit fallback only for pre-start availability failures or a failure to create the subprocess. Once a process has started, do not silently retry after timeout, cancellation, malformed output, exit failure, or ambiguous provider failure because side effects may exist; record the no-retry decision.
- Register adapters via `ExtensionRegistry` and compose them through a runtime preset with ordered runtime candidates rather than supervisor conditionals.
- Run discovery/routing tests and the full suite.
- Commit: `feat: add runtime discovery and fallback routing`.

### Task 5: Integrate runtime execution with supervisor and durable traces

- Add `RuntimeWorkerBridge` as the explicit integration point from the typed `TaskContract`/`RuntimeExecutionResult` boundary to the existing `Worker`/`TaskResult` supervisor interface; preserve `Supervisor.handle()` and existing E0 behavior.
- Write an end-to-end fixture test that submits one task through Claude, Codex, and agy fake adapters using the same typed contract and asserts normalized results.
- Define and test status mapping: `completed → completed`, `failed/unavailable → failed`, `cancelled → cancelled`, and `timed_out → timed_out`. Preserve all structured result fields; expose only a safe summary as legacy `TaskResult.output` and put serialized `WorkerResult` in `TaskResult.details`.
- Add typed runtime identity, selected model, workspace, lifecycle status, session ID, command fingerprint, and fallback reason to the existing component trace data. Adapter-internal events aggregate into one runtime span with exactly one start and one terminal event.
- Verify a timed-out worker terminates its process tree, preserves replayable partial artifacts, and emits exactly one `timed_out` terminal runtime span. Verify cancellation analogously.
- Verify pre-start availability fallback records both the failed candidate and selected fallback, while post-start failures record an explicit no-retry decision.
- Run the E1 acceptance fixture plus `uv run agos eval e0 --workdir <fresh-dir>`.
- Commit: `feat: integrate runtimes with supervisor tracing`.

### Task 6: Add documentation and verification evidence

- Document local setup, fake-runtime tests, optional real CLI smoke tests, supported environment variables, timeout/cancellation semantics, and security boundaries in `docs/e1-verification.md`.
- Update README usage only for commands that are verified locally; clearly label real-provider tests as opt-in and credential-dependent.
- Add deterministic `uv run agos eval e1 --workdir <fresh-dir>` following the E0 proof pattern. It must cover fake-adapter execution, pre-start fallback, workspace enforcement, cancellation/timeout, traceability, partial-artifact replay, and legacy bridge compatibility.
- Run `uv run ruff check .`, `uv run pytest -q`, `uv run agos eval e0 --workdir <fresh-dir>`, `uv run agos eval e1 --workdir <fresh-dir>`, and retain `python verify_e0_ac.py` only as an optional heuristic diagnostic.
- Review `git diff --check`, inspect the complete diff, and confirm no credentials or generated artifacts are committed.
- Commit: `docs: document E1 runtime adapter verification`.

## Acceptance checklist

- [ ] Same fixture task executes through Claude and Codex adapters using the same typed boundary.
- [ ] agy adapter is implemented and covered by the same lifecycle/contract matrix.
- [ ] Missing CLI/authentication produces typed availability failure and fallback.
- [ ] Timeout/cancellation terminates the complete process tree and preserves replayable partial artifacts.
- [ ] Steering and session continuation are capability-gated and explicit.
- [ ] Adapter selection, exact runtime, model, session, workspace, command fingerprint, fallback decision, and outcome are traceable.
- [ ] Runtime execution uses a validated workspace with enforceable write/read-only isolation.
- [ ] Runtime execution emits exactly one start and one terminal span, including cancellation and timeout.
- [ ] Supervisor compatibility is provided by `RuntimeWorkerBridge` without changing E0 `handle()` semantics.
- [ ] No API key is required for deterministic CI tests.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run pytest -q` passes with E0 tests unchanged/passing.
- [ ] E0 acceptance proof remains green.
- [ ] `agos eval e1` passes in the credential-free deterministic lane.

## Risks and decisions to revisit

- CLI output formats can change across versions; pin only parsing assumptions, record tool versions, and keep probes tolerant.
- Process-group termination differs across Linux/WSL; tests must cover graceful termination followed by forced kill and verify child-process death.
- Steering semantics differ between CLIs; do not expose a false common guarantee.
- Real authentication discovery may be unreliable without consuming a task; classify unknown auth as unavailable with actionable diagnostics.
- `cwd` alone does not enforce write isolation; adapters must use a provider/OS sandbox or reject a read-only/write policy they cannot guarantee.
- Existing E0 tracing currently maps all exceptions to failure; cancellation/timeout terminal statuses must be implemented before runtime integration.
- Fallback after process start can duplicate side effects; the no-retry boundary is mandatory even when a provider reports an authentication or parse error late.
