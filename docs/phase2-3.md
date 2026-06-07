# Phase 2 & 3 — public voice, persistence, self-publishing

## Phase 2 — Public voice (shipped: Telegram channel with approval)

Bentlyk drafts a post in its own voice and asks you to approve it before anything
goes public — the safe pattern that matches the autonomy ladder.

**Setup (one-time):**
1. Create a Telegram **channel**.
2. Add your bot (`@…`) as an **administrator** of the channel (with "Post messages").
3. Get the channel id (e.g. forward a channel post to `@userinfobot`, or use
   `@<channel_username>`), and set it in Vercel env: `TELEGRAM_CHANNEL_ID`.

**Use:** message the bot `/post <topic>` (or just `/post`). Bentlyk writes a draft
and sends it to you with **✅ Опубликовать / ❌ Отмена**. Tapping ✅ posts it to the
channel; nothing is published without your tap.

### Still to wire (need credentials from you)
- **Twitter/X** — needs X API access (paid) + OAuth keys. Once you have them we add
  a `tweet` tool behind the same approval gate.
- **Public chat / other agents** — add the bot to a group and designate it as a
  public space; Bentlyk replies there. Higher autonomy surface — gated.

## Phase 3 — Persistence, sandbox, self-publishing

### Persistent worker (shipped: `bentlyk worker`)
A continuous loop that lives between messages, reaches out when due (with backoff),
and shares memory/state with the webhook via Supabase. Run it anywhere always-on:

```bash
docker build -t bentlyk .
docker run -e OPENROUTER_API_KEY=… -e SUPABASE_URL=… -e SUPABASE_KEY=… \
           -e TELEGRAM_BOT_TOKEN=… bentlyk
```

Hosts: Fly.io, Railway, Render, or a small VPS. With the worker running you can
drop the GitHub Actions heartbeat (the shared backoff prevents double outreach).

### Still to wire (need provisioning)
- **Code sandbox** — a `run_code` tool against E2B / Modal (needs their API key) so
  Bentlyk can write and execute code safely in isolation.
- **Self-publishing website** — give Bentlyk a dedicated GitHub repo + a token with
  write scope; a `publish_site` tool commits files there and Vercel auto-deploys, so
  Bentlyk builds and presents itself. (Self-modification of its own code stays behind
  a human-reviewed PR.)

> As reach grows, the homeostasis autonomy ladder + permission gate + reflection are
> what keep it safe; every outward/high-risk tool hangs on that gate.
