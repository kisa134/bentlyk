"""Scheduled heartbeat: gives Bentlyk a life between messages.

Vercel Cron hits this endpoint on a schedule. Each call emits one idle ``timer``
event (driving autonomous goal generation and homeostatic recovery); the agent's
own cadence triggers a reflection/sleep pass periodically.
"""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk import timer  # noqa: E402
from bentlyk.serverless import build_agent, owner_id, tg_send  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        # Vercel cron sends Authorization: Bearer <CRON_SECRET> when configured.
        secret = os.environ.get("CRON_SECRET", "").strip()
        if secret and self.headers.get("Authorization", "") != f"Bearer {secret}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return

        # ?reach=1 forces a proactive outreach (cron schedule also reaches out).
        from urllib.parse import parse_qs, urlparse

        reach = (parse_qs(urlparse(self.path).query).get("reach") or ["1"])[0] != "0"

        agent = build_agent()
        summary = ""
        try:
            cycle = agent.tick(timer(source="vercel-cron"))
            summary = cycle.headline()
            if cycle.reflection:
                summary += f" | {cycle.reflection.summary}"

            # Proactivity: reach out to the owner unprompted.
            if reach:
                owner = owner_id(agent)
                token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                if owner and token:
                    msg = agent.proactive_message()
                    if msg:
                        tg_send(token, owner, msg)
                        summary += " | reached out"
        finally:
            agent.close()

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"tick: {summary}".encode())
