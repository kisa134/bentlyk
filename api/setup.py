"""One-time setup endpoint: register the Telegram webhook and init the schema.

Visit (GET):  /api/setup?secret=<SETUP_SECRET>

It points Telegram at this deployment's /api/telegram, installs a webhook secret
token, and ensures the Postgres schema exists. Protected by SETUP_SECRET.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.serverless import tg_call  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        setup_secret = os.environ.get("SETUP_SECRET", "").strip()
        given = (query.get("secret") or [""])[0]
        if not setup_secret or given != setup_secret:
            return self._json(403, {"ok": False, "error": "bad or missing setup secret"})

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return self._json(500, {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"})

        host = self.headers.get("host", "")
        webhook_url = f"https://{host}/api/telegram"
        webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

        payload: dict = {"url": webhook_url, "drop_pending_updates": True}
        if webhook_secret:
            payload["secret_token"] = webhook_secret
        result = tg_call(token, "setWebhook", payload)

        schema_ok, db_error = self._ensure_schema()
        llm_ok, llm_model, llm_error = self._probe_llm()

        return self._json(
            200,
            {
                "ok": bool(result.get("ok")),
                "webhook_url": webhook_url,
                "telegram": result,
                "schema_initialized": schema_ok,
                "db_dsn_present": bool(os.environ.get("BENTLYK_PG_DSN", "").strip()),
                "db_error": db_error,
                "llm_ok": llm_ok,
                "llm_model": llm_model,
                "llm_error": llm_error,
            },
        )

    def _probe_llm(self) -> tuple[bool, str, str | None]:
        try:
            from bentlyk.config import Settings
            from bentlyk.llm import build_reasoner

            settings = Settings.from_env()
            reasoner = build_reasoner(settings)
            reply = reasoner.complete(
                system="You are a healthcheck.", prompt="Reply with the single word: ok", max_tokens=8
            )
            return True, settings.model, (reply or "")[:40]
        except Exception as exc:
            from bentlyk.config import Settings

            return False, Settings.from_env().model, f"{type(exc).__name__}: {exc}"

    def _ensure_schema(self) -> tuple[bool, str | None]:
        dsn = os.environ.get("BENTLYK_PG_DSN", "").strip()
        if not dsn:
            return False, "BENTLYK_PG_DSN is empty"
        try:
            from bentlyk.pg import ensure_schema

            ensure_schema(dsn)
            return True, None
        except Exception as exc:  # surfaced (behind SETUP_SECRET) to diagnose connectivity
            return False, f"{type(exc).__name__}: {exc}"

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode())
