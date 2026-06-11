"""A serverless heartbeat — advance the colony and the learner without the worker.

The Render worker has been unreliable, so this lets the live learning run on Vercel
instead: each hit takes one real learning step (colony + price learner). Both are
gated by the 1-minute candle, so calling this often is self-rate-limited to ~one
advance per minute — the browser on the trading page pings it, and the cron hits it
in the background. The system lives whenever it is watched or scheduled.

    /api/tick
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk.serverless import build_agent  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        out = {"ok": True}
        agent = build_agent()
        try:
            try:
                out["learn"] = agent.learn_step()
            except Exception as exc:
                out["learn_err"] = str(exc)[:120]
            try:
                out["colony"] = agent.colony_step()
            except Exception as exc:
                out["colony_err"] = str(exc)[:120]
            try:
                out["stats"] = agent.colony_stats()
            except Exception:
                pass
        finally:
            agent.close()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(out, default=str).encode())
