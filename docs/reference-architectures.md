# Reference Architectures

Agentic OS is informed by two active open-source agent systems: DeepSeek Harness and Hermes Agent. They are references, not dependencies or templates to copy wholesale. This project retains its own product boundary: a single-user, eval-driven project orchestrator over interchangeable headless coding agents, with `agent-memory` as its dedicated shared/private memory layer.

## DeepSeek Harness

DeepSeek Harness describes itself as an open-source agent harness built around the principle that “everything is a plugin.”[1] Its architecture treats model adapters, tools, persistence, sandboxing, approval policy, the session log, and the agent loop as replaceable contributions composed through a shared plugin context.[2]

The most relevant patterns are:

- **Plugin composition.** Profiles and ordered bundles compose a runtime without modifying a privileged core.[2]
- **Durable event log.** Session events are durable facts, while live agent and capability events govern in-flight work.[2]
- **Model-visible means logged.** Anything supplied to a model must be reconstructable from the session log.[2]
- **Capability seams.** A replaceable capability is designed as service definition, provider, and consumer rather than as an implementation-only abstraction.[2]
- **Scoped tools and guarded execution.** The tool registry and execution pipeline are explicit capabilities rather than incidental functions inside the loop.[2]
- **Headless composition.** DeepSeek Harness documents both web and headless profile compositions.[2]

### Adoption in Agentic OS

Agentic OS adopts the principles, but applies them to a smaller Python system:

| DeepSeek Harness idea | Agentic OS decision |
|---|---|
| Everything is a plugin | Extension points for runtime adapters, workers, tools, evaluators, planning surfaces, memory policy, and interfaces |
| Durable session event log | Event-sourced run log plus checkpoints |
| Model-visible means logged | Every prompt/context reference and worker task contract is reproducible from the run trace |
| Capability seam | Protocol + provider registration + consumer for each replaceable subsystem |
| Profiles/bundles | Local/Docker runtime profiles and versioned capability presets |
| Scoped registration | Per-project and per-worker capability/skill scopes |

Agentic OS will not adopt Cordis or DeepSeek Harness's TypeScript package topology in v1. The objective is to preserve the architectural properties—replaceability, reversibility, durable events, and explicit seams—without importing a substantially larger framework.

## Hermes Agent

Hermes Agent exposes one agent core through CLI, messaging gateways, ACP, batch, and API surfaces, while platform-specific behavior remains in entry points.[4] Its architecture includes provider resolution, a central tool registry, multiple execution backends, session persistence, messaging adapters, plugins, cron, delegation, memory providers, and context engines.[3][4]

The most relevant patterns are:

- **Platform-agnostic core.** CLI, gateway, ACP, and API routes share the same agent loop.[4]
- **Provider/runtime resolution.** Provider and model selection is centralized rather than duplicated across surfaces.[4]
- **Tool registry and toolsets.** Tools are discovered centrally and grouped into capability sets.[4]
- **Messaging gateway.** Platform adapters handle authorization, session routing, and delivery around the shared agent.[4]
- **Interruptibility and observable execution.** Tool calls are surfaced and model/tool execution can be cancelled.[4]
- **Progressively disclosed skills.** Skill metadata is indexed first, full instructions load only when relevant, and detailed references load on demand.[5]
- **Project-local and shared skills.** Hermes supports local, external, and project-scoped skill directories with explicit trust and precedence.[5]
- **Curated versus searchable history.** Hermes distinguishes bounded, always-present curated memory from on-demand search across durable sessions.[6]
- **External memory providers.** Its architecture treats deeper semantic memory as a pluggable provider rather than forcing all memory into prompt-resident files.[6]

### Adoption in Agentic OS

| Hermes Agent idea | Agentic OS decision |
|---|---|
| One core, many surfaces | One durable supervisor used by Telegram, CLI, and API adapters |
| Provider resolution | One runtime router across Claude Code CLI, Codex CLI, and agy CLI |
| Toolsets | Capability presets constrain each specialist to least-privilege tools |
| Delegation | Structured specialist task/result contracts and isolated worker lifecycles |
| Progressive skill disclosure | Skill index → full `SKILL.md` → targeted reference files |
| Project-local skills | Repository skills override shared skills only for trusted projects |
| Curated memory + session search | agent-memory semantic facts plus episodic run/event retrieval |
| Gateway authorization | Single-user Telegram allowlist and operation-scoped approvals |
| Cron/background work | Durable scheduled goals and resumable project runs in a later epic |

Agentic OS does not intend to reproduce Hermes Agent's broad messaging-platform matrix, built-in model-provider matrix, or complete general-purpose tool catalog. Telegram is the v1 surface, and the main novelty remains multi-runtime project orchestration with explicit trial/evaluation loops.

## Combined design direction

The resulting design combines complementary strengths:

```text
DeepSeek Harness                         Hermes Agent
----------------                         ------------
plugin composition                       one core, many surfaces
capability seams                         provider/tool registries
reversible effects                       interruptible execution
model-visible ⇔ logged                    messaging gateway + sessions
headless profile                         progressive skills + memory providers
          \                                   /
           \                                 /
            ─────── Agentic OS ─────────────
                    durable supervisor
                    specialist CLI runtimes
                    isolated parallel trials
                    neutral evaluations
                    agent-memory scopes
                    Telegram approvals
```

### Concrete architecture changes

The current specification is strengthened with these requirements:

1. **Extension registry:** workers, runtime adapters, evaluators, tools, planning surfaces, interfaces, and memory-policy components register through typed extension points.
2. **Capability completeness:** each replaceable capability documents its protocol, provider lifecycle, consumer, configuration, events, and failure semantics.
3. **Model-context provenance:** every item delivered to a supervisor or specialist records the originating event, memory ID, skill version, source URL, or artifact reference.
4. **Skill progressive disclosure:** task routing first sees metadata; only selected skill bodies and references enter a worker contract.
5. **Runtime presets:** named profiles compose adapters, toolsets, approval policy, memory scopes, and limits for local, Docker, research, and coding modes.
6. **Reference conformance tests:** architecture tests verify that new providers can replace existing ones without changing supervisor logic, model-visible inputs are trace-reconstructable, and platform adapters do not contain planning logic.

## What remains unique to Agentic OS

- The supervisor manages a durable project contract and overarching goal rather than only a conversation turn.
- Claude Code, Codex, and agy are specialist runtimes invoked as headless agents, not merely model API providers.
- Multiple specialists perform controlled trials against a shared evaluator.
- The system preserves negative results and uses them for future runtime/hypothesis selection.
- `agent-memory` provides explicit shared, supervisor-private, worker-private, short-term, and long-term namespaces.
- GitHub and Google Drive are project-planning and publication systems, not only tools invoked inside chat.
- Delete/remove/force-rewrite actions require operation-bound user approval.

## Sources

[1] https://github.com/deepseek-ai/deepseek-harness — DeepSeek Harness
[2] https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/architecture.md — DeepSeek Harness Architecture
[3] https://github.com/NousResearch/hermes-agent — Hermes Agent
[4] https://hermes-agent.nousresearch.com/docs/developer-guide/architecture — Hermes Agent Architecture
[5] https://hermes-agent.nousresearch.com/docs/user-guide/features/skills — Hermes Agent Skills System
[6] https://hermes-agent.nousresearch.com/docs/user-guide/features/memory — Hermes Agent Persistent Memory
