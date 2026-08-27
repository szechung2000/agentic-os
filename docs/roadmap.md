# Agentic OS Roadmap

The roadmap is acceptance-test driven. An epic is complete only when its artifact and end-to-end verification exist; code scaffolds alone do not count.

## Current baseline

Already present as an early scaffold:

- Python package and CLI;
- basic supervisor/worker interface;
- deterministic rule router;
- memory and echo workers;
- Telegram adapter skeleton;
- agent-memory remember/recall demo;
- initial tests and CI.

This scaffold predates the formal specification. Each component must be reconciled with the contracts and boundaries in `product-spec.md` and `architecture.md`.

## E0 — Contracts and durable run state

**Goal:** Replace ad hoc dictionaries with durable, versioned orchestration contracts.

### Deliverables

- Pydantic models for goal, task, worker result, evaluation, artifact, approval, and event.
- Run state machine and append-only event store.
- Checkpoint/restart support.
- Structured trace CLI/API.
- Typed extension registries for runtimes, workers, tools, evaluators, planning surfaces, interfaces, memory policy, and skills.
- Runtime presets that compose registered capabilities without supervisor branches.

### Acceptance tests

- A process can stop mid-run and resume without duplicating completed work.
- Invalid worker output is rejected with a bounded correction attempt.
- Replanning records the old plan, new plan, and reason.
- A test provider replaces an existing capability without changing supervisor code.
- Every model-visible context item is reconstructable from its recorded provenance.
- Unregistering an extension reverses its registrations and releases owned resources.

## E1 — Headless runtime adapters

**Goal:** Execute specialist tasks through interchangeable agent CLIs.

### Deliverables

- `RuntimeAdapter` interface.
- Claude Code CLI adapter.
- Codex CLI adapter.
- agy CLI adapter.
- Capability/availability discovery and routing policy.
- Timeout, cancellation, steering, structured-result, and session-continuation support.

### Acceptance tests

- The same fixture task runs through at least Claude Code and Codex adapters.
- Missing CLI or authentication yields a typed availability failure and fallback.
- A timed-out worker is terminated with partial artifacts preserved.
- Adapter selection and exact runtime/model are recorded in the trace.

## E2 — Memory scopes and lifecycle

**Goal:** Use agent-memory for scoped, durable orchestration context.

### Deliverables

- Namespace mapping for user, project shared, supervisor, worker-private, and run-short-term memory.
- Hydration policy and context-budget allocator.
- Episodic write path, reflection, consolidation, TTL expiry, and provenance.
- Memory visibility enforcement.

### Acceptance tests

- Two workers share promoted project facts but cannot read each other's private memories.
- Short-term run memory expires or archives according to policy.
- A restarted supervisor retrieves the project goal, decisions, and prior trial results.
- Existing agent-memory golden evaluations do not regress.

## E3 — Research and planning

**Goal:** Turn a high-level goal into an evidence-backed executable project.

### Deliverables

- Project-contract builder.
- Dependency-aware plan and replanning loop.
- Research specialist with citation capture.
- GitHub markdown/issue/milestone planning adapter.
- Google Drive report adapter with explicit source-of-truth declaration.

### Acceptance tests

- A vague goal produces measurable success criteria and flagged assumptions.
- A research claim links to extracted source evidence.
- A failed assumption triggers a documented plan revision.
- GitHub plan status and internal task state reconcile idempotently.

## E4 — Trial and evaluation engine

**Goal:** Compare alternative approaches rather than accepting the first plausible implementation.

### Deliverables

- Trial matrix and isolated worktree/container manager.
- Deterministic test/benchmark evaluator.
- Regression gate and baseline comparison.
- Optional versioned rubric evaluator.
- Candidate leaderboard covering quality, latency, cost, and failures.

### Acceptance tests

- At least two specialists attempt different hypotheses against the same contract.
- The evaluator selects the measured winner, not the first finisher.
- A quality gain with a forbidden regression is rejected.
- Negative results are preserved as evidence and available to later runs.

## E5 — Skills library

**Goal:** Make verified procedures reusable across the supervisor and specialists.

### Deliverables

- Skill manifest, filesystem/Git registry, metadata index, and retrieval.
- Three-stage progressive disclosure: metadata index → selected `SKILL.md` → targeted reference files.
- Shared, external, and trusted project-local skill sources with explicit precedence.
- Skill hydration into worker task contracts.
- Proposal, validation, versioning, and publication workflow.
- Compatibility and staleness checks.

### Acceptance tests

- A specialist receives only skills relevant to its task and only loads referenced detail on demand.
- A trusted project-local skill can override a shared skill without modifying the shared source.
- A successful complex workflow proposes a skill with verification steps.
- A stale command fails validation and the skill update is reviewed before publication.
- Both supervisor and specialist workers can use the same shared skill.

## E6 — Telegram and destructive-action approvals

**Goal:** Provide the single-user operating surface with safe autonomous execution.

### Deliverables

- Goal intake and progress/report formatting.
- Meaningful milestone notifications with noise suppression.
- Approval buttons for delete/remove/force-rewrite operations.
- Single-use, expiring, operation-hashed approval tokens.
- `/status`, `/pause`, `/resume`, `/stop`, and run-link commands.
- `/trace` with paginated supervisor/worker interactions and artifact links.
- Local web timeline, task graph, sequence view, and trial comparison sourced from durable run events.

### Acceptance tests

- A delete requested by any worker pauses before reaching the tool layer.
- Approval executes only the displayed operation once.
- Modified or expired operations require new approval.
- Loss of Telegram connectivity never implicitly approves an action.
- A user can trace goal → delegation → worker handoff → evaluation → decision without reading process logs.
- Timeline and sequence views reconstruct the same interaction ordering from the event store.
- Worker messages identify sender, recipient, task, runtime, and referenced artifacts.
- No view exposes private chain-of-thought; it exposes explicit plans, evidence, tool activity, and decision records.

## E7 — Local and Docker deployment

**Goal:** Make the complete system reproducible on a local developer machine and in Docker.

### Deliverables

- Local `uv` setup and diagnostics.
- Dockerfiles and Compose stack.
- Health/readiness endpoints.
- Secret mounts, persistent volumes, migration flow, and backup guidance.
- Dedicated worker runner security profile.

### Acceptance tests

- Fresh local setup passes the flagship demo.
- Fresh Compose setup passes the same demo.
- Restart preserves projects, memories, traces, and pending approvals.
- The coordinator has no unrestricted Docker socket access.

## E8 — Flagship portfolio demo

**Goal:** Demonstrate an eval-driven autonomous project assistant end to end.

### Scenario

1. Submit a high-level repository improvement goal through Telegram.
2. System creates the contract and GitHub plan.
3. Research specialist gathers cited approaches.
4. Supervisor chooses at least two hypotheses.
5. Separate headless runtime workers prototype them in isolated worktrees.
6. Evaluator runs a golden/regression suite and ranks candidates.
7. Supervisor explains the findings and implements the winner.
8. CI-green PR is opened and linked in Telegram.
9. Durable findings go to shared memory; specialist lessons remain private unless promoted.
10. The workflow produces or updates a reusable skill.

### Portfolio acceptance criteria

- Reproducible demo script and fixture repository.
- Video under three minutes showing goal → trials → eval → PR → memory reuse.
- Run trace and architecture diagram linked from README.
- Honest cost, latency, failure, and negative-result reporting.
- A second run demonstrates learning by retrieving prior evidence or using the published skill.

## Suggested execution order

```text
E0 Contracts/state
 → E1 Runtime adapters
 → E2 Memory scopes
 → E3 Research/planning
 → E4 Trial/eval engine
 → E5 Skills
 → E6 Telegram approvals
 → E7 Deployment hardening
 → E8 Flagship demo
```

E2 and E3 may begin after E0 contracts stabilize. E5 can start with a minimal registry while E3/E4 are built. E6's Telegram display work may proceed early, but destructive approval enforcement belongs below workers and depends on E0 contracts.

## Global quality gates

Every epic must maintain:

- lint and unit tests;
- typed contract validation;
- no regression in required project evaluations;
- no destructive action without approval;
- no secrets in logs, memory, or artifacts;
- trace completeness for acceptance scenarios;
- documentation matching the executed behavior.
