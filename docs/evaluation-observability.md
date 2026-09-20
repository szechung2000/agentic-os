# Evaluation and Observability Specification

## 1. Purpose

Agentic OS needs more than application logs and one final task score. It must answer:

- Which component was called, by whom, and why?
- What validated input did it receive and what output did it return?
- Which runtime, model, tools, skills, memories, and artifacts influenced the result?
- How long did the call take and what did it cost?
- Where did a failed outcome originate: planning, routing, research, retrieval, execution, evaluation, synthesis, or publication?
- Did an architectural or prompt change improve target behavior without regressing other scenarios?

Evaluation and logging therefore share one event vocabulary. Production runs create replayable traces; selected traces become eval fixtures; evaluation results feed routing and planning policy without silently rewriting it.

## 2. Three data products

### 2.1 Run event log

The authoritative append-only record of supervisor, worker, tool, memory, skill, evaluator, interface, and approval activity. It powers restart recovery and the interaction timeline.

### 2.2 Telemetry

Metrics and spans derived from run events for operational diagnosis. OpenTelemetry-compatible export is supported, but the durable run log remains the source of truth.

### 2.3 Evaluation history

Versioned scenarios, candidate outputs, scores, regressions, and experiment decisions. Evaluation history is immutable; corrected evaluator logic produces a new evaluator version rather than rewriting prior scores.

## 3. Correlation model

Every observable operation carries these identifiers when applicable:

```text
trace_id                 complete user goal/run
span_id                  one component invocation
parent_span_id           caller invocation
goal_id                  durable overarching goal
run_id                   one execution of the goal
task_id                  delegated task
parent_task_id           task dependency/decomposition
trial_id                 one competing attempt
worker_id                specialist instance
session_id               runtime CLI session
artifact_ids[]           files, commits, reports, datasets
memory_ids[]             retrieved/written memory records
skill_versions[]         skills supplied to the component
approval_id              destructive-action decision
```

A supervisor → worker → tool → evaluator call chain shares one `trace_id` and uses parent/child spans. Worker-to-worker handoffs also record sender and recipient IDs.

## 4. Component invocation envelope

Every component call emits `component.call.started` and exactly one terminal event: `component.call.completed`, `component.call.failed`, `component.call.cancelled`, or `component.call.timed_out`.

```json
{
  "event_id": "evt_...",
  "event_type": "component.call.completed",
  "occurred_at": "RFC3339 timestamp",
  "trace_id": "trace_...",
  "span_id": "span_...",
  "parent_span_id": "span_...",
  "component": {
    "kind": "supervisor|worker|runtime|tool|memory|skill|evaluator|interface|project_store",
    "name": "codex-adapter",
    "version": "git-sha-or-package-version",
    "instance_id": "worker_..."
  },
  "operation": "runtime.execute_task",
  "actor": {"type": "supervisor", "id": "supervisor_main"},
  "recipient": {"type": "worker", "id": "worker_code_2"},
  "input": {
    "schema_version": "1",
    "summary": "Prototype temporal query decomposition",
    "payload_ref": "artifact://...",
    "content_hash": "sha256:...",
    "redactions": []
  },
  "output": {
    "schema_version": "1",
    "summary": "Candidate completed; 52 tests passed",
    "payload_ref": "artifact://...",
    "content_hash": "sha256:..."
  },
  "runtime": {
    "adapter": "codex-cli",
    "model": "resolved-model-id",
    "session_id": "...",
    "workspace": "worktree-id"
  },
  "context": {
    "memory_ids": [],
    "skill_versions": [],
    "artifact_ids": [],
    "source_urls": []
  },
  "metrics": {
    "latency_ms": 0,
    "queue_ms": 0,
    "input_tokens": null,
    "output_tokens": null,
    "estimated_cost_usd": null,
    "retry_count": 0
  },
  "status": "ok",
  "error": null
}
```

Large inputs and outputs are content-addressed artifacts; the event keeps summaries, hashes, schemas, and references. Secrets and sensitive values are redacted before persistence.

## 5. Required instrumentation by component

| Component | Log at minimum | Evaluate at minimum |
|---|---|---|
| Goal intake | raw user goal reference, parsed contract, clarifications | contract completeness and constraint preservation |
| Planner | plan version, dependencies, assumptions, revisions | task coverage, dependency validity, goal alignment |
| Router | candidate workers/runtimes, features, chosen route, rationale | route success, fallback rate, quality/cost by runtime |
| Research worker | queries, sources, extracts, claims, citations | citation validity, source quality, claim coverage |
| Coding worker | task contract, runtime session, commands, changed artifacts, tests | correctness, regression, maintainability, latency/cost |
| Memory retrieval | query/aspects, namespace filters, candidate IDs/ranks/scores | recall, precision, leakage, temporal correctness, latency |
| Memory write | proposed entry, scope, durability class, provenance | usefulness, duplication, privacy/scope correctness |
| Skill retrieval | metadata candidates, selected versions, loaded references | relevance, unnecessary token load, task success contribution |
| Tool call | validated args hash, permission decision, result/error | success rate, schema validity, safety policy compliance |
| Evaluator | evaluator version, candidate refs, metrics, verdict | agreement with golden labels, stability, bias checks |
| GitHub/Drive | idempotency key, request/result refs, remote IDs | publication correctness and duplicate prevention |
| Telegram | inbound/outbound IDs, delivery result, approval state | delivery reliability and notification usefulness |

## 6. Evaluation hierarchy

### 6.1 Component contract tests

Deterministic tests for schemas, lifecycle, timeouts, cancellation, permission gates, redaction, retries, and idempotency. These are required on every change.

### 6.2 Component golden evaluations

Small versioned datasets for semantic behavior:

- goal → project contract;
- goal/plan → worker routing;
- research brief → grounded claims;
- memory query → expected evidence and namespace isolation;
- task → relevant skills;
- worker result → evaluator verdict;
- events → human-readable timeline.

Each case stores inputs, required/forbidden outcomes, tags, and an optional rubric.

### 6.3 Integration evaluations

Exercise a real chain such as supervisor → runtime adapter → worker → tools → artifacts → evaluator. External services may use recorded/replay fixtures in the default CI lane and live tests in an opt-in lane.

### 6.4 End-to-end project scenarios

Measure whether the complete system reaches a repository-level goal. The flagship scenario requires research, competing trials, a regression gate, PR publication, memory consolidation, skill reuse, and visible interaction traces.

### 6.5 Production shadow evaluations

Completed runs can be re-evaluated offline by a newer evaluator without changing the original verdict. Shadow scores identify evaluator drift and generate candidate golden cases.

## 7. Eval case format

```yaml
id: routing-retrieval-001
suite: runtime-routing
version: 1
input:
  goal: "Improve L3 synthesis without golden regressions"
  constraints:
    local_only: true
expected:
  must_delegate_roles: [research, coding, evaluation]
  must_not_select_runtime: []
  required_artifacts: [hypothesis_matrix, regression_report]
metrics:
  - contract_coverage
  - route_success
  - quality_score
  - latency_ms
  - estimated_cost_usd
tags: [multi-step, eval-driven, coding]
```

Case artifacts are immutable. Dataset changes bump suite versions and preserve comparable historical baselines.

## 8. Metrics

### Outcome metrics

- goal success rate;
- acceptance-criteria pass rate;
- regression-free improvement rate;
- human acceptance/override rate;
- time to verified artifact or PR.

### Orchestration metrics

- plan revisions per run;
- worker success/failure/timeout rates;
- retries and fallback rate;
- parallelism efficiency;
- unnecessary delegations;
- approval wait and denial rate.

### Quality metrics

- research citation coverage and validity;
- test pass and regression counts;
- evaluator agreement and stability;
- memory retrieval recall/precision/leakage;
- skill relevance and context-token overhead.

### Efficiency metrics

- component and end-to-end latency;
- queue time versus execution time;
- tokens and estimated cost by component/runtime;
- cache hit rate;
- artifact and log storage growth.

### Reliability and safety metrics

- restart recovery success;
- duplicate side effects;
- missing terminal events;
- secret-redaction violations;
- destructive-action guard bypass attempts;
- trace completeness.

## 9. Experiment workflow

Every optimization follows:

1. Record the current versioned baseline by suite, case tag, runtime, latency, and cost.
2. Diagnose failures from component spans and artifacts.
3. State a falsifiable hypothesis and expected affected components.
4. Run candidate and baseline on the same cases and environment.
5. Compare target metrics and all regression gates.
6. Adopt, reject, or conditionally route the candidate.
7. Store the result—including negative findings—in evaluation history.
8. Update routing policy only through a reviewed/versioned policy change.

The system must not automatically promote a runtime, prompt, memory policy, or skill solely because it won one noisy run.

## 10. Replay and debugging

The trace tool supports:

```text
agos trace show <run-id>
agos trace tree <run-id>
agos trace component <run-id> <component>
agos trace replay <span-id> --mode recorded|live
agos eval run <suite> [--candidate REF] [--baseline REF]
agos eval compare <run-a> <run-b>
agos eval history [--suite NAME] [--tag TAG]
```

Replay modes:

- `recorded`: use stored external responses and artifacts for deterministic diagnosis;
- `live`: repeat allowed calls in a new run and retain both traces;
- `dry-run`: validate routing, permissions, and schemas without side effects.

Replays never re-execute destructive operations. Publication tools use dry-run or recorded results unless the user explicitly starts a new live run.

## 11. Storage and retention

- Run events: append-only relational/event store, indexed by correlation IDs and timestamp.
- Payloads/artifacts: content-addressed filesystem or object store.
- Metrics: derived tables and optional OpenTelemetry/Prometheus export.
- Evaluation suites/history: Git-versioned definitions plus append-only result records.
- agent-memory: durable semantic/episodic learning, referenced by ID but not used as the authoritative event log.

Retention is configurable by data class. Removing traces, payloads, or evaluation history is a delete operation and requires approval under the product policy.

## 12. Privacy and integrity

- Redact before persistence and before telemetry export.
- Store content hashes to detect artifact or event-payload corruption.
- Record schema, component, runtime, prompt/task, skill, evaluator, and policy versions.
- Treat external source text and worker output as untrusted data.
- Enforce visibility when querying events and memory.
- Do not log hidden chain-of-thought; log explicit plans, hypotheses, task contracts, evidence, decisions, and tool activity.

## 13. v1 observability acceptance criteria

1. Every supervisor, worker, runtime, tool, memory, skill, evaluator, interface, and project-store call emits correlated start and terminal events.
2. A trace reconstructs goal → plan → delegation → component calls → artifacts → evaluation → decision → report.
3. Missing terminal events and broken parent-span references fail an automated trace-integrity check.
4. A user can filter the timeline by worker, component, task, trial, event type, and status.
5. At least one golden suite exists for planning, routing, memory, skills, and interaction rendering.
6. Every PR compares required eval suites to a committed baseline and blocks forbidden regressions.
7. A failed production run can be diagnosed from its trace without reproducing it first.
8. The same trace produces the Telegram summary, web timeline, task graph, and sequence view.
9. Secrets do not appear in persisted events, artifacts, metrics, or agent-memory.
10. Evaluation history records adopted and rejected hypotheses with quality, latency, cost, and regression results.
