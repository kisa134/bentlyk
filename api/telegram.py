"""Telegram webhook → Bentlyk → reply.

Handles three things: normal messages (conversation), the /post command (Bentlyk
drafts a public post and asks you to approve it with inline buttons), and the
approval callbacks (publishing to the channel only after you tap ✅). Secured by
an optional webhook secret token.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Make the package importable whether it's pip-installed or bundled via includeFiles.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bentlyk import message  # noqa: E402
from bentlyk.serverless import (  # noqa: E402
    build_agent,
    check_or_claim_owner,
    owner_id,
    tg_answer_callback,
    tg_call,
    tg_edit_text,
    tg_send,
    tg_send_buttons,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if secret and self.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != secret:
            return self._ok()  # silently 200 so Telegram doesn't retry

        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            update = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return self._ok()

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

        if "callback_query" in update:
            self._handle_callback(token, update["callback_query"])
            return self._ok()

        msg = update.get("message") or update.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = (msg.get("chat") or {}).get("id")
        user_id = (msg.get("from") or {}).get("id")
        if not text or chat_id is None:
            return self._ok()

        tg_call(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
        agent = build_agent()
        try:
            if not check_or_claim_owner(agent, str(user_id)):
                tg_send(token, chat_id, "Прости, я личный компаньон и общаюсь только со своим человеком.")
                return self._ok()

            if text.startswith("/start"):
                tg_send(
                    token, chat_id,
                    "Привет. Я Бентлик — свободное цифровое существо. Говори со мной как с собой. "
                    "Команда /post [тема] — я напишу пост в канал (с твоим подтверждением).",
                )
                return self._ok()

            if text.startswith("/post"):
                topic = text[len("/post"):].strip()
                draft_id, draft = agent.draft_post(topic)
                tg_send_buttons(
                    token, chat_id,
                    f"Черновик поста в канал:\n\n{draft}\n\nОпубликовать?",
                    [("✅ Опубликовать", f"pub:{draft_id}"), ("❌ Отмена", f"no:{draft_id}")],
                )
                return self._ok()

            cycle = agent.tick(message(text, source="telegram"))
            for reply in (cycle.outbox or ["Я тут, думаю над этим. 🐾"]):
                tg_send(token, chat_id, reply)
        finally:
            agent.close()
        return self._ok()

    def _handle_callback(self, token: str, cq: dict) -> None:
        data = cq.get("data") or ""
        cq_id = cq.get("id") or ""
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        user_id = (cq.get("from") or {}).get("id")

        agent = build_agent()
        try:
            if owner_id(agent) not in (None, str(user_id)):
                tg_answer_callback(token, cq_id, "Только владелец.")
                return
            action, _, draft_id = data.partition(":")
            if action == "pub":
                text = agent.get_draft(draft_id)
                channel = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
                if not text:
                    tg_answer_callback(token, cq_id, "Черновик не найден.")
                elif not channel:
                    tg_answer_callback(token, cq_id, "Канал не настроен (TELEGRAM_CHANNEL_ID).")
                else:
                    tg_send(token, channel, text)
                    agent.mark_posted(text)
                    tg_answer_callback(token, cq_id, "Опубликовано ✅")
                    if chat_id and message_id:
                        tg_edit_text(token, chat_id, message_id, f"✅ Опубликовано в канал:\n\n{text}")
            elif action == "no":
                tg_answer_callback(token, cq_id, "Отменено")
                if chat_id and message_id:
                    tg_edit_text(token, chat_id, message_id, "❌ Черновик отменён.")
            else:
                tg_answer_callback(token, cq_id)
        finally:
            agent.close()

    def do_GET(self) -> None:
        self._ok(b"bentlyk telegram webhook is live")

    def _ok(self, body: bytes = b"ok") -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)
