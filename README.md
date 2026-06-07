# bentlyk

A **long-lived autonomous companion agent** — not a chat-bot wrapped around a
prompt, but a durable agent with a stable identity, regulated autonomy, layered
memory, internal drives, and a development cycle through reflection.

> Долгоживущий агент с устойчивой идентичностью, регулируемой автономией,
> многослойной памятью, внутренними drives и циклом развития через рефлексию.

The defining difference from an ordinary agent: a second control loop. A plain
agent runs **goal → plan → act**. bentlyk wraps that in **homeostasis** —
*"what state am I in, and may I act at all?"* — so its autonomy, pace, caution,
and depth of thought shift with experience.

## The eight layers

| # | Layer | What it does |
|---|-------|--------------|
| 1 | **Perception** | Normalizes messages, timers, files, feeds, webhooks into one `Event`. |
| 2 | **Self Model** | Stable `IdentityCore` + moving `DynamicState` (seven internal signals). |
| 3 | **Memory** | Five contours — short-term, episodic, semantic, procedural, autobiographical — that grow, compress, and forget. |
| 4 | **Homeostasis** | Tracks internal signals; regulates autonomy & tempo so the agent doesn't fall apart. |
| 5 | **Goal Engine** | Generates goal candidates from external / internal / aspirational sources and scores them. |
| 6 | **Planner / Reasoner** | Decides **think / ask / act** and decomposes a plan. |
| 7 | **Action Layer** | Tools behind a permission & risk gate keyed to the current autonomy. |
| 8 | **Reflection / Sleep** | Consolidates memory and proposes self-model changes — without acting outward. |

Full design, schemas, and the state machine: [`docs/architecture.md`](docs/architecture.md).

## Quickstart (zero setup, fully offline)

The core runs on the Python standard library — SQLite memory and a deterministic
offline reasoner — so it boots with no API keys and no services.

```bash
pip install -e .

# interactive companion
bentlyk chat

# process a single message
bentlyk run "help me organize my project notes"

# watch autonomous behaviour when idle (drives goals + reflection)
bentlyk tick -n 12
```

In `chat`, control the agent with: `/state`, `/sleep`, `/memory`,
`/autonomy <observe|suggest|safe_act|escalated_act>`, `/quit`.

### Using it as a library

```python
from bentlyk import Agent, message

agent = Agent()           # offline + SQLite by default
agent.boot()
cycle = agent.tick(message("can you summarize what we did yesterday?"))
print(cycle.headline())   # e.g. "ask" / "think" / "act:reflect -> gate=allow"
for reply in cycle.outbox:
    print(reply)
agent.sleep()             # run a reflection/consolidation pass
```

## Going live

Everything is a swappable seam; none of these touch the core loop:

```bash
# Real reasoner via OpenRouter (any model, no SDK — talks over urllib)
export OPENROUTER_API_KEY=sk-or-...
export BENTLYK_MODEL=anthropic/claude-3.5-sonnet   # or any OpenRouter slug
bentlyk chat

# ...or native Claude
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-ant-...

# Postgres memory + persisted self-model (Supabase)
pip install -e ".[postgres]"
export BENTLYK_PG_DSN=postgresql://...   # auto-selects the postgres store
```

When a human message arrives, Bentlyk answers conversationally via the `respond`
path — grounded in its identity, current internal state, and recalled memory —
which is permitted at every autonomy level (talking to your person is risk-free).

### Telegram bot on Vercel

A full serverless deployment (Vercel functions + Supabase + Telegram webhook)
lives in [`api/`](api) and [`vercel.json`](vercel.json). Step-by-step guide:
**[docs/deploy.md](docs/deploy.md)**.

Copy [`.env.example`](.env.example) to `.env` and fill in what you need. Identity
profiles live in [`config/`](config) (`BENTLYK_IDENTITY=<name>`).

## Development

```bash
pip install -e ".[dev]"
pytest          # full suite
ruff check src tests
```

## Layout

```
src/bentlyk/
  events.py        # 1. Perception
  self_model.py    # 2. Self Model (IdentityCore + DynamicState)
  memory/          # 3. Memory System (store, contours, embeddings)
  homeostasis.py   # 4. Homeostasis Engine
  goals.py         # 5. Goal Engine
  planner.py       # 6. Planner / Reasoner
  actions/         # 7. Action Layer (tools + permission gate)
  reflection.py    # 8. Reflection / Sleep
  agent.py         # orchestrator: the main loop
  llm.py           # reasoner backends (Anthropic + offline mock)
  cli.py           # chat / run / tick
  interfaces/      # optional adapters (Telegram)
docs/              # architecture.md, JSON schemas, postgres DDL
config/            # identity profiles
tests/             # pytest suite
```

## Status

First working MVP of the architecture — the full eight-layer loop runs and is
tested end to end. It is intentionally a *skeleton with real bones*: the control
structure (homeostasis, autonomy gating, memory contours, goal scoring,
reflection) is complete and exercised; the reasoner, embeddings, store, and
interfaces are production-swappable behind stable interfaces.
