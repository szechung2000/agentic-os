# E1 Runtime Adapter Verification

E1 adds a provider-neutral asynchronous runtime boundary for headless Claude Code,
Codex, and agy processes. The deterministic proof uses local fake executables
that emulate each provider's native result shape; it does not require API keys,
network access, or installed provider CLIs.

## Run the proof

```bash
uv run agos eval e1 --workdir /tmp/agentic-os-e1 --candidate working-tree
```

The proof covers:

- the same task through Claude, Codex, and agy adapters;
- explicit pre-start fallback ordering;
- workspace capability enforcement;
- timeout and process lifecycle handling;
- the legacy `Worker`/`TaskResult` bridge and durable trace integrity.

Expected result is `E1 score: 5/5 (100%)`. The proof writes fake executables,
artifacts, an event database, and append-only evaluation history below the
provided workdir.

## Real CLI smoke lane

Real provider execution is opt-in and credential-dependent. The adapters use
these non-interactive entrypoints:

- Claude: `claude -p --output-format json [--model MODEL] -- PROMPT`
- Codex: `codex exec --json --sandbox workspace-write [--model MODEL] -- PROMPT`
- agy: `agy -p --output-format json [--model MODEL] -- PROMPT`

The adapter environment is an explicit allowlist. It never forwards the whole
parent environment and never persists credential values. The installed CLI and
account must be authenticated separately before using this lane.

## Lifecycle and safety

- Every runtime process runs in an explicit validated workspace.
- `cwd` pinning is not treated as a read-only sandbox; adapters must declare an
enforceable workspace capability or startup is rejected.
- Timeout and cancellation terminate the process group, preserve stdout/stderr
as content-addressed artifacts, and emit one terminal runtime outcome.
- Fallback is permitted only before a provider process starts. After a process
has started, failures are terminal for that attempt because side effects may
already exist.
- Provider-native results are normalized into `RuntimeExecutionResult`, then
mapped by `RuntimeWorkerBridge` into the existing `WorkerResult` contract.

## Verification gates

```bash
uv run ruff check .
uv run pytest -q
uv run agos eval e0 --workdir /tmp/agentic-os-e0
uv run agos eval e1 --workdir /tmp/agentic-os-e1
```

`python verify_e0_ac.py` remains a supplemental heuristic source audit, not
the formal E0 acceptance proof.
