# agentic-os

Supervisor/worker agent orchestration with a Telegram interface, built on [agent-memory](https://github.com/szechung2000/agent-memory) as its long-term brain.

![status](https://github.com/szechung2000/agentic-os/actions/workflows/ci.yml/badge.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Architecture

```
                    ┌────────────────────┐
 Telegram / CLI ──► │    SUPERVISOR      │
                    │  route → delegate  │
                    │  → compose reply   │
                    └─────────┬──────────┘
                              │ routes by capability
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │  memory  │    │   echo   │    │ (future) │
        │  worker  │    │  worker  │    │  workers │
        └────┬─────┘    └──────────┘    └──────────┘
             │ tools: memory_write / search / context
             ▼
      agent-memory service ◄── long-term semantic + episodic memory
```

- **Supervisor** — the only component that reasons. LLM mode (OpenAI key) with bounded tool-calling rounds, or rule mode (offline, zero keys): `remember that X` → memory write; questions → memory search; else fallback.
- **Workers** — dumb-but-reliable capability holders (`memory`, `echo`, more coming). Structured task in, structured result out.
- **agent-memory** — the shared long-term brain: hybrid retrieval, temporal reasoning, consolidation. See its [evals](https://github.com/szechung2000/agent-memory#showcase-the-capacity-golden-evals).

## Run it

```bash
uv sync --all-groups
uv pip install -e ".[telegram]"            # telegram extra optional
uv pip install -e "../agent-memory"        # memory brain (or from git)

# offline chat demo — no API keys needed
agos chat

# with Telegram
export AGOS_TELEGRAM_BOT_TOKEN=...
export AM_OPENAI_API_KEY=...               # optional: full LLM supervisor
agos telegram
```

## Demo session (rule mode)

```
$ agos chat
> remember that Simon prefers Python and uv for data work
[memory] Remembered.
> what does Simon prefer for data work?
[memory] From your memory:
- Simon prefers Python and uv for data work
> hello there
[echo] echo: hello there
```

## Tests

```bash
python -m pytest tests/
```

7 tests cover routing rules, remember→recall roundtrip through a real
agent-memory backend, echo fallback, and trace output.

## License

MIT
