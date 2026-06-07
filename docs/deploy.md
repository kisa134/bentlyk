# Deploying Bentlyk (Vercel + Supabase + Telegram)

Bentlyk runs as a set of stateless Vercel serverless functions. All continuity
(memory + self-model) lives in Postgres (Supabase), so each request rebuilds the
agent, loads its state, processes one event, and persists again.

```
Telegram  ──webhook──▶  /api/telegram ─┐
Vercel Cron ──────────▶  /api/cron     ├─▶  Agent.tick()  ──▶  Supabase (Postgres)
browser   ──setup────▶  /api/setup    ─┘                         memory + self_model
```

## 1. Database (Supabase)

Create a Postgres project and grab its **connection pooler** string (Transaction
mode, port `6543`) — serverless needs the pooler, not a direct connection:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

The schema is created automatically on first use (or eagerly via `/api/setup`).

## 2. Vercel project & env vars

Connect the repo to Vercel (this repo already ships `vercel.json`, `api/`, and
`requirements.txt`). Set these environment variables:

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENROUTER_API_KEY` | yes | the reasoner; any OpenRouter model |
| `BENTLYK_MODEL` | no | default `anthropic/claude-3.5-sonnet` |
| `BENTLYK_PG_DSN` | yes | Supabase pooler string (selects postgres store) |
| `TELEGRAM_BOT_TOKEN` | yes | from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | rec. | random string; verifies inbound webhooks |
| `TELEGRAM_ALLOWED_USER_ID` | no | lock to one user; else first chatter is claimed |
| `SETUP_SECRET` | yes | protects `/api/setup` |
| `CRON_SECRET` | no | set by Vercel to auth cron calls |

## 3. Register the Telegram webhook

After the first deploy, hit once:

```
https://<your-deployment>.vercel.app/api/setup?secret=<SETUP_SECRET>
```

This calls Telegram `setWebhook` pointing at `/api/telegram` (with the secret
token) and initializes the DB schema. Then message your bot.

## 4. Aliveness (cron)

`vercel.json` schedules `/api/cron` daily (Hobby plan limit) to emit an idle
tick and run the nightly reflection/sleep pass. For minute-level autonomy,
upgrade the plan or point an external scheduler (e.g. cron-job.org) at
`/api/cron` with the `Authorization: Bearer <CRON_SECRET>` header.

## Notes

- The reasoner uses `urllib` (no SDK), so cold starts stay light; `psycopg` is
  the only function dependency.
- Recall ranks embeddings in Python over JSONB — simple and pgvector-free. For
  scale, switch the `embedding` column to `vector` and push ranking into SQL
  behind the same `recall` method.
- Secrets live only in Vercel env, never in the repo.
