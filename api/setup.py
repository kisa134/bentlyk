"""One-time setup endpoint: register the Telegram webhook and init the schema.

Visit (GET):  /api/setup?secret=<SETUP_SECRET>

It points Telegram at this deployment's /api/telegram, installs a webhook secret
token, and ensures the Postgres schema exists. Protected by SETUP_SECRET so
randoms can't re-point your bot.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from _app import tg_call


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

        # Best-effort schema init so the first real message doesn't pay for it.
        schema_ok = self._ensure_schema()

        return self._json(
            200,
            {
                "ok": bool(result.get("ok")),
                "webhook_url": webhook_url,
                "telegram": result,
                "schema_initialized": schema_ok,
            },
        )

    def _ensure_schema(self) -> bool:
        dsn = os.environ.get("BENTLYK_PG_DSN", "").strip()
        if not dsn:
            return False
        try:
            from bentlyk.pg import ensure_schema

            ensure_schema(dsn)
            return True
        except Exception:  # pragma: no cover - best effort
            return False

    def _json(self, code: int, body: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode())
