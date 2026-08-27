# Agentic OS Architecture

This architecture is informed by [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) and [Hermes Agent](https://github.com/NousResearch/hermes-agent). See [Reference Architectures](reference-architectures.md) for the source-grounded mapping of adopted ideas, adaptations, and deliberate non-goals.

## 1. System context

```text
                         ┌───────────────────────────────┐
                         │          Telegram user        │
                         └───────────────┬───────────────┘
                                         │ goals, approvals, reports
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AGENTIC OS                                     │
│                                                                             │
│  ┌──────────────┐   ┌───────────────────────────────────────────────────┐  │
│  │ Telegram/API │──►│ Supervisor / durable run coordinator              │  │
│  └──────────────┘   │ plan · route · checkpoint · compare · report      │  │
│                     └───────────┬───────────────────────┬───────────────┘  │
│                                 │ task contracts        │ eval contracts    │
│          ┌──────────────────────┼───────────────────────┼──────────────┐    │
│          ▼                      ▼                       ▼              ▼    │
│   Research worker       Coding workers          Evaluator       PM worker  │
│                         isolated trials                         GitHub/Drive │
│          │                      │                       │              │    │
│          └──────────────────────┴───────────┬───────────┴──────────────┘    │
│                                             │                               │
│                 ┌───────────────────────────┼───────────────────────────┐   │
│                 ▼                           ▼                           ▼   │
│          Runtime adapters             Skill library              Event log │
│    Claude Code · Codex · agy       shared, versioned            checkpoints│
└───────────────────────────┬───────────────────────┬─────────────────────────┘
                            │                       │
                            ▼                       ▼
                  ┌───────────────────┐   ┌─────────────────────┐
                  │   agent-memory    │   │ GitHub / Drive / Web│
                  │ shared + private  │   │ project systems     │
                  └───────────────────┘   └─────────────────────┘
```

## 2. Architectural decisions

### ADR-1: Durable coordinator, ephemeral workers

The supervisor is a durable state machine. Worker processes are disposable. A worker receives a complete task contract and returns a structured result; it does not own the project plan.

This preserves restartability and makes runtime providers interchangeable.

### ADR-2: Runtime adapters, not provider-specific orchestration

The core depends on a `RuntimeAdapter` contract rather than Claude/Codex/agy APIs:

```python
class RuntimeAdapter(Protocol):
    async def start(self, task: TaskContract, workspace: Workspace) -> RunHandle: ...
    async def events(self, handle: RunHandle) -> AsyncIterator[RuntimeEvent]: ...
    async def steer(self, handle: RunHandle, message: str) -> None: ...
    async def stop(self, handle: RunHandle) -> RunResult: ...
```

Each adapter owns command construction, structured-output parsing, environment setup, timeout handling, cancellation, and provider-specific session continuation.

Initial adapters:

- `ClaudeCodeAdapter`: non-interactive/headless Claude Code CLI.
- `CodexAdapter`: non-interactive Codex CLI.
- `AgyAdapter`: agy CLI with the same task/result boundary.

Provider selection uses capability requirements, historical evals, availability, cost policy, and optional user preference. It is not hardcoded to one model.

### ADR-3: Structured contracts at every boundary

#### Goal contract

```text
goal_id, objective, non_goals, constraints, success_metrics,
approval_policy, repositories, planning_surface, budget, created_at
```

#### Task contract

```text
task_id, goal_id, worker_role, objective, context_refs, workspace,
allowed_tools, expected_artifacts, evaluator, limits, dependencies
```

#### Worker result

```text
status, summary, artifacts, evidence, measurements, tests,
assumptions, failures, recommendations, memory_candidates, skill_candidates
```

#### Evaluation result

```text
candidate_id, evaluator_version, metrics, regressions, evidence,
verdict, confidence, limitations
```

Free-form text may accompany contracts, but orchestration decisions use validated structured fields.

### ADR-4: agent-memory provides storage; Agentic OS provides memory policy

Agentic OS maps its scope model to agent-memory namespaces:

```text
user/{user_id}
project/{project_id}/shared
project/{project_id}/supervisor
project/{project_id}/worker/{worker_role_or_id}
run/{run_id}/short-term
```

Short-term entries carry run/task ownership and expiry. Long-term writes require a post-run reflection decision. Retrieval hydrates context in layers:

1. goal contract and current task;
2. shared project memory;
3. worker-private memory;
4. stable user preferences;
5. relevant skills;
6. recent episodic evidence.

Workers cannot read another worker's private namespace unless the supervisor explicitly grants a reference. Worker results intended for collaboration are promoted to shared project memory.

### ADR-5: Skills are versioned artifacts

Skills live in a filesystem/Git-backed library and have:

- trigger and applicability;
- numbered procedure;
- required tools and permissions;
- failure modes and pitfalls;
- verification steps;
- provenance and version.

The supervisor indexes skill metadata; agent-memory may index skill content for retrieval, but Git remains the source of truth. Specialists can propose skill changes, while the supervisor runs validation before publishing.

### ADR-6: Trial isolation and neutral evaluation

Each coding/prototyping trial gets:

- a separate Git worktree or container;
- a read-only copy of the goal and evaluator contract;
- its own short-term memory namespace;
- bounded runtime and resource limits;
- no access to sibling intermediate output unless a later synthesis round permits it.

An evaluator executes after candidate generation. Deterministic project tests take precedence over model judgments. LLM-as-judge is allowed only with a versioned rubric and must retain evidence.

### ADR-7: Event-sourced run trace

The coordinator appends events such as:

```text
goal.accepted
plan.created / plan.revised
worker.started / worker.progress / worker.completed / worker.failed
eval.started / eval.completed
decision.recorded
approval.requested / approval.granted / approval.denied
artifact.created
memory.proposed / memory.committed
skill.proposed / skill.published
run.completed / run.failed / run.cancelled
```

The current run state is reconstructed from events plus periodic checkpoints. Telegram updates are projections of significant events.

### ADR-8: Typed extension registry and capability seams

Inspired by DeepSeek Harness's plugin composition and Hermes Agent's provider/tool registries, Agentic OS uses typed extension points instead of adding provider-specific branches to the supervisor. The initial registries are:

```text
runtime_adapters
worker_roles
tool_providers
evaluators
planning_surfaces
interfaces
memory_policies
skill_providers
```

A complete capability defines: protocol, provider lifecycle, consumer, validated configuration, emitted events, permission needs, and failure semantics. Registrations return a disposer so tests, profiles, and process shutdown can unwind effects deterministically.

Named runtime presets compose extensions and policy for common modes:

- `local`: local CLIs, local worktrees, SQLite-compatible agent-memory;
- `docker`: container worker runner, Postgres/pgvector, Redis coordination;
- `research`: web/research tools, read-only project access by default;
- `coding`: repository tools, worktree isolation, tests, GitHub publication.

Model-visible context has a strict provenance invariant: every prompt item must be reconstructable from a run event, memory ID, skill version, source URL, or artifact reference.

## 3. Supervisor lifecycle

```text
RECEIVE_GOAL
  → HYDRATE_CONTEXT
  → DEFINE_CONTRACT
  → PLAN
  → [RESEARCH ↔ REPLAN]
  → SPAWN_TRIALS
  → EVALUATE
  → SELECT_OR_ESCALATE
  → IMPLEMENT
  → VERIFY
  → PUBLISH
  → REFLECT_AND_CONSOLIDATE
  → REPORT
```

A state may pause for user input or destructive-operation approval. Failed workers may retry under policy; repeated failures trigger replanning rather than infinite retries.

## 4. Worker roles

### Research specialist

Searches, extracts, compares, cites, and produces a research brief. It cannot silently convert speculation into a project decision.

### Coding/prototype specialist

Works in an isolated repository state through one runtime adapter. It must execute tests or report why execution is blocked.

### Evaluation specialist

Builds or applies golden cases, regression tests, benchmarks, or rubrics. It compares candidates using the same contract.

### Project-management specialist

Maintains plans, issues, milestones, PR status, and Drive reports. It does not select technical winners; it records supervisor decisions.

### Memory curator

Evaluates proposed memories for scope, durability, provenance, duplication, and confidentiality before committing long-term entries.

### Skill curator

Turns successful procedures into validated, shared skills and updates stale skills when verified workflows change.

## 5. Approval subsystem

A `DestructiveActionGuard` sits below workers, so model instructions cannot bypass it. Before executing delete/remove/force-rewrite operations it emits an approval request:

```text
approval_id, run_id, actor, operation, targets, reason,
impact, reversible, expires_at, command_hash
```

Telegram presents Approve/Deny. Approval is bound to the operation hash, targets, and expiry; changed commands require a new approval. Denial is recorded and causes replanning or a non-destructive alternative.

## 6. Deployment

### Local process mode

- `agentic-os` coordinator/API
- Telegram polling adapter
- local runtime CLIs
- agent-memory configured with SQLite or Postgres
- local filesystem skills and worktrees

### Docker Compose mode

Recommended services:

```text
agentic-os-api
agentic-os-telegram
agent-memory-api
postgres + pgvector
redis (queue, leases, short-lived coordination)
worker-runner pool
```

Runtime credentials mount as secrets. Docker socket access is not granted to the coordinator by default; worker isolation uses a dedicated runner with an explicit allowlist.

## 7. Failure handling

- **Coordinator restart:** resume from last checkpoint and reconcile live worker processes.
- **Worker timeout:** stop, preserve partial artifacts, evaluate salvageability, then retry or replan.
- **Provider unavailable:** route to another compatible runtime adapter if policy permits.
- **Evaluation regression:** reject candidate and preserve measurements as negative evidence.
- **Memory unavailable:** continue only for stateless-safe tasks; otherwise pause with a clear failure.
- **GitHub/Drive unavailable:** retain local artifacts and retry publication idempotently.
- **Telegram unavailable:** continue bounded active work; queue milestone reports and approvals, but never execute pending destructive actions.

## 8. Interaction observability

Agent collaboration is projected from the durable run-event stream rather than collected in a separate debug log. This keeps the UI, Telegram summaries, restart recovery, and evaluations consistent.

### Interaction event envelope

```text
event_id, run_id, goal_id, task_id, parent_task_id,
actor_type, actor_id, recipient_type, recipient_id,
event_type, timestamp, summary, payload_ref,
artifact_refs, memory_refs, skill_refs, runtime, metrics
```

Relevant event types include:

```text
supervisor.plan.created
supervisor.task.delegated
worker.started
worker.message.sent
worker.artifact.published
worker.progress
worker.completed
worker.failed
supervisor.worker.steered
evaluator.candidate.scored
supervisor.decision.recorded
approval.requested
```

Workers do not communicate through hidden process-local channels. A direct worker handoff is either mediated by the supervisor or appended to a durable mailbox/event stream with an explicit sender, recipient, task, and artifact reference.

### Views

- **Timeline:** chronological events with expandable task contracts, messages, tool calls, and artifacts.
- **Task graph:** goal → tasks → trials → evaluations → selected implementation.
- **Sequence view:** supervisor/worker lifelines and handoffs generated from the same events.
- **Trial comparison:** candidates, runtime/model, metrics, regressions, evidence, and verdict.
- **Telegram:** milestone summaries, `/status`, and paginated `/trace`; destructive approvals remain actionable messages.

The UI exposes explicit reasoning products—plans, hypotheses, evidence, evaluations, and decision records—but does not expose private chain-of-thought.

## 9. Security boundaries

- Secrets are never placed in prompts unless a tool requires them and the adapter supports secret-safe injection.
- Workers receive least-privilege credentials and repository scopes.
- Shell commands, changed files, network targets, and approvals appear in traces.
- External content is untrusted data, not instructions.
- Memory visibility is enforced before retrieval, not filtered after prompt assembly.
- All subprocesses have wall-clock, output-size, retry, and descendant-process limits.
