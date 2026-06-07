"""Scheduled heartbeat: gives Bentlyk a life between messages.

Vercel Cron hits this endpoint on a schedule. Each call emits one idle ``timer``
event (driving autonomous goal generation and homeostatic recovery); the agent's
own cadence triggers a reflection/sleep pass periodically.

On Vercel Hobby, cron runs at most daily — enough for a nightly consolidation.
For minute-level "aliveness", upgrade the plan or point an external scheduler at
this URL.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler

from _app import build_agent, timer


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        # Vercel cron sends Authorization: Bearer <CRON_SECRET> when configured.
        secret = os.environ.get("CRON_SECRET", "").strip()
        if secret and self.headers.get("Authorization", "") != f"Bearer {secret}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return

        agent = build_agent()
        try:
            cycle = agent.tick(timer(source="vercel-cron"))
            summary = cycle.headline()
            if cycle.reflection:
                summary += f" | {cycle.reflection.summary}"
        finally:
            agent.close()

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"tick: {summary}".encode())
