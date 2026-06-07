"""Telegram webhook → Bentlyk → reply.

Receives a Telegram update, runs one agent cycle on the message, and sends back
whatever Bentlyk decided to say. Secured by an optional webhook secret token
(set when registering the webhook in api/setup.py).
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from _app import build_agent, check_or_claim_owner, message, tg_send


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        # Verify the request really comes from Telegram (if a secret is set).
        secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if secret:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if got != secret:
                return self._ok()  # silently 200 so Telegram doesn't retry

        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            update = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return self._ok()

        msg = update.get("message") or update.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        user_id = (msg.get("from") or {}).get("id")

        if not text or chat_id is None:
            return self._ok()

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        agent = build_agent()
        try:
            if not check_or_claim_owner(agent, str(user_id)):
                tg_send(token, chat_id, "Прости, я личный компаньон и общаюсь только со своим человеком.")
                return self._ok()

            if text.startswith("/start"):
                tg_send(
                    token,
                    chat_id,
                    "Привет. Я Бентлик — твой долгоживущий компаньон. "
                    "Просто говори со мной как с собой; я буду помнить и расти.",
                )
                return self._ok()

            cycle = agent.tick(message(text, source="telegram"))
            replies = cycle.outbox or [_fallback(cycle)]
            for reply in replies:
                tg_send(token, chat_id, reply)
        finally:
            agent.close()

        return self._ok()

    def do_GET(self) -> None:
        self._ok(b"bentlyk telegram webhook is live")

    def _ok(self, body: bytes = b"ok") -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def _fallback(cycle) -> str:
    # The agent chose not to speak (e.g. it deliberated). Surface a light cue.
    return "Я тут, думаю над этим. 🐾"
