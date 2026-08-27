# Agentic OS Product Specification

**Status:** Draft v0.1  
**Primary user:** Single owner  
**Initial surface:** Telegram and local CLI  
**Runtime:** Local machine or Docker  
**Memory layer:** [agent-memory](https://github.com/szechung2000/agent-memory)

## 1. Vision

Agentic OS turns a high-level objective into an evidence-backed project outcome. The user states the goal and constraints; the system plans the work, researches unknowns, delegates experiments and coding to specialist agents, evaluates competing approaches, reports findings, and maintains the project plan.

It is not merely a chat interface or a wrapper around one coding model. It is a durable orchestration layer over interchangeable headless agent runtimes, persistent memory, reusable skills, project systems, and explicit evaluation loops.

## 2. Reference systems

The design explicitly studies [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) and [Hermes Agent](https://github.com/NousResearch/hermes-agent). DeepSeek Harness informs plugin composition, capability seams, durable event logs, and reconstructable model context. Hermes Agent informs the platform-agnostic agent core, runtime/tool registries, messaging gateway, delegation, progressive skill disclosure, and curated-versus-searchable memory. See [Reference Architectures](reference-architectures.md) for the grounded comparison and adoption boundaries.

## 3. Product principles

1. **Goal-directed, not prompt-directed.** Optimize for the overarching goal and acceptance criteria, not the most recent isolated instruction.
2. **Evidence before commitment.** Research and prototype uncertain approaches before selecting one.
3. **Eval-driven iteration.** Competing attempts are measured against explicit tests, benchmarks, or rubrics.
4. **Interchangeable runtimes.** Claude Code CLI, Codex CLI, and agy CLI are execution backends behind one adapter contract.
5. **Durable context.** agent-memory supplies shared and private, short- and long-term memory.
6. **Skills over repeated improvisation.** Successful procedures become reusable skills available to supervisors and workers.
7. **Autonomous by default, guarded for deletion.** The system may research, create, edit, test, and report autonomously. Remove/delete operations require user approval.
8. **Inspectable execution.** Every plan, delegation, tool call, decision, evaluation, and artifact has a trace.
9. **Local-first and Docker-ready.** A developer can run the complete system locally or in containers without a cloud control plane.

## 4. Primary use case

### Eval-driven project assistant

The user provides an overarching goal such as:

> Improve the L3 answer-synthesis score without regressing existing golden evaluations.

The system:

1. Converts the goal into success metrics, constraints, and a project plan.
2. Retrieves relevant project, user, and experiment memories.
3. Researches applicable methods and records cited findings.
4. Generates several hypotheses.
5. Assigns isolated specialist workers to prototype different hypotheses.
6. Runs a common evaluation suite against each trial.
7. Compares quality, latency, cost, and regressions.
8. Reports findings and recommends a path.
9. On approval where required, implements the winner and opens a GitHub pull request.
10. Updates GitHub/Google Drive planning artifacts and stores durable lessons as memories or skills.

## 5. Functional requirements

### FR-1 Goal intake and project contract

The supervisor shall convert a high-level goal into a durable project contract containing:

- goal and non-goals;
- measurable success criteria;
- constraints and approval policy;
- known assumptions and unresolved questions;
- artifact locations;
- evaluation plan;
- current status and next actions.

The contract is versioned in GitHub by default. Google Drive is an optional mirrored planning surface.

### FR-2 Planning and replanning

The supervisor shall maintain a dependency-aware task graph. It may revise the plan when experiments fail, new evidence appears, or constraints change. Replanning must preserve the original goal and record why the plan changed.

### FR-3 Research

A research specialist shall:

- discover and inspect primary sources;
- attach URLs and citations to claims;
- distinguish evidence from inference;
- summarize applicability to the project;
- store durable findings in shared project memory.

### FR-4 Prototyping and coding

Coding specialists shall run through interchangeable headless CLI adapters:

- Claude Code CLI;
- Codex CLI;
- agy CLI.

Each attempt shall run in an isolated workspace or Git worktree, receive a bounded task contract, and return structured artifacts: changes, tests, metrics, assumptions, failures, and recommended next steps.

### FR-5 Evaluation loop

For uncertain work, the supervisor shall be able to spawn multiple trials and apply a shared evaluator. An evaluator may use deterministic tests, benchmarks, regression suites, latency/cost measurements, or a versioned rubric. The evaluator must not be the same process that produced the candidate when an independent check is practical.

### FR-6 Reporting

The Telegram user shall receive concise progress updates at meaningful milestones—not every tool call—and a final report containing:

- what was attempted;
- evidence and measurements;
- the winning and rejected approaches;
- artifacts and pull-request links;
- unresolved risks;
- recommended next action.

### FR-7 Project management

The system shall support GitHub as the canonical engineering project surface:

- markdown specifications and plans;
- issues/milestones;
- branches, commits, and pull requests;
- CI status and evaluation history.

Google Drive support shall cover human-facing plans, reports, and research documents. The source of truth for each artifact must be declared to avoid two-way conflicts.

### FR-8 Approval policy

Default behavior:

| Operation | Default |
|---|---|
| Read, search, inspect | Autonomous |
| Create files/branches/docs/issues | Autonomous |
| Edit files and run tests | Autonomous |
| Commit/push/open PR | Autonomous within configured repos |
| Send progress/final Telegram messages | Autonomous |
| Remove/delete files, branches, records, projects, or remote resources | **Approval required** |
| Force-push or destructive history rewrite | Treated as delete; **approval required** |

The approval request must identify the exact target, reason, and expected effect. Approval is scoped to that operation and expires after use.

### FR-9 Interfaces

- **Telegram:** primary single-user conversational and approval interface.
- **CLI:** local operations, diagnostics, and headless automation.
- **API:** internal control plane suitable for the Telegram adapter and future interfaces.

### FR-10 Skills

A shared skill library shall be readable by the supervisor and all specialists. Skills include trigger conditions, procedures, commands, pitfalls, and verification steps. Workers may propose new or updated skills after successful non-trivial workflows; the supervisor validates and publishes them.

### FR-11 Agent interaction visibility

The user shall be able to inspect how the supervisor and specialists collaborate. The run view must show:

- the supervisor's goal decomposition and delegation decisions;
- worker identity, runtime adapter, task contract, status, and workspace;
- messages and artifact handoffs between supervisor and workers;
- worker-to-worker communication routed through the supervisor or a durable mailbox;
- evidence, memory, and skill references supplied to each worker;
- evaluator inputs, scores, regressions, and selection rationale;
- retries, steering, cancellation, replanning, and approval pauses;
- timestamps, latency, token/cost data when available, and links to resulting artifacts.

The default presentation is a chronological run timeline with filters by worker, task, event type, and trial. A sequence/dependency view may project the same durable events. Telegram provides concise milestones plus `/status` and `/trace`; a local web view provides the full interaction history. Internal chain-of-thought is neither requested nor exposed—visibility covers explicit task contracts, messages, tool activity, evidence, and decisions.

## 6. Memory requirements

agent-memory is the only memory implementation. Agentic OS owns policy and addressing, not embedding or retrieval internals.

### Memory scopes

| Visibility | Short term | Long term |
|---|---|---|
| Shared project | active goal, plan, open decisions, current evidence | architecture decisions, findings, outcomes, reusable project facts |
| Supervisor-private | orchestration scratchpad, dependency state | planning preferences and orchestration lessons |
| Worker-private | current task context, intermediate attempts | specialist-specific lessons and tool knowledge |
| User | current conversation context | stable user preferences and authorization boundaries |

Short-term memory has explicit TTL or task/session ownership. Long-term memory is durable and must pass a write policy: stable, useful later, and not merely transient progress.

### Memory lifecycle

1. **Hydrate:** retrieve user, project, worker, and relevant skill context before planning.
2. **Record:** append episodic events and trial results during execution.
3. **Reflect:** identify durable facts, decisions, and procedures after milestones.
4. **Consolidate:** promote selected episodic items to semantic memory.
5. **Forget:** delete only after user approval or configured retention-policy approval.

Every memory records namespace, owner, project, task/run, visibility, provenance, timestamp, and optional expiry.

## 7. Non-functional requirements

- **NFR-1 Reproducibility:** each run records runtime adapter, model, prompt/task contract, repository state, tool versions, and evaluator version.
- **NFR-2 Isolation:** concurrent coding trials use separate worktrees or containers.
- **NFR-3 Recoverability:** supervisor state is checkpointed so a restart can resume or clearly fail the run.
- **NFR-4 Bounded autonomy:** configurable time, token, cost, retry, concurrency, and disk limits.
- **NFR-5 Observability and evaluation:** every component invocation emits correlated start/terminal events; traces are replayable, feed interaction views, and support component, integration, and end-to-end evaluations as defined in [Evaluation and Observability](evaluation-observability.md).
- **NFR-6 Security:** secrets are injected at runtime, redacted from traces, and never written to memory or planning artifacts.
- **NFR-7 Portability:** Docker Compose is the supported reproducible deployment; local `uv` execution remains supported.
- **NFR-8 Regression safety:** selected changes cannot merge while required project evaluations regress.

## 8. Out of scope for v1

- Multi-user tenancy or public bot operation.
- Autonomous financial trading or other irreversible real-world actions.
- A new vector database, embedding model, or memory implementation.
- General desktop control unless introduced as a separately permissioned specialist.
- Silent destructive operations.
- Unbounded self-replication or recursive worker spawning.

## 9. Success criteria for v1

1. A user submits a high-level project goal through Telegram.
2. The supervisor creates and persists a project contract and task graph.
3. It researches at least one unknown with citations.
4. It dispatches at least two isolated specialist trials through headless CLI adapters.
5. A common evaluator ranks the trials and detects regressions.
6. It implements the winning approach, verifies it, and opens a GitHub pull request.
7. Progress, agent interactions, and final findings return to Telegram and the inspectable run timeline.
8. Shared and worker-private memories persist across a process restart.
9. A successful workflow can be promoted to the shared skill library.
10. A delete attempt pauses and completes only after single-use Telegram approval.
