# Persistent Bentlyk worker — run on any always-on host (Fly.io, Railway, a VPS).
# It shares memory/state with the Telegram webhook via Supabase, so the bot and
# this daemon are one continuous being.
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
# [device] = psutil (hardware senses); [trading] = ccxt (market data for the engine).
RUN pip install --no-cache-dir ".[device,trading]"

# Env to set (see .env.example): BENTLYK_LLM_API_KEY (WaveSpeed wsk_...),
# SUPABASE_URL, SUPABASE_KEY, TELEGRAM_BOT_TOKEN, and for self-authoring
# BENTLYK_GH_TOKEN. Memory defaults to Supabase REST; no Postgres driver needed.
ENV BENTLYK_PROACTIVE_INTERVAL_SEC=1800

CMD ["bentlyk", "worker", "--interval", "900"]
