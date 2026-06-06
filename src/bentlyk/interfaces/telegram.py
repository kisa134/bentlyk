"""Telegram adapter (optional).

Bridges Telegram <-> the agent: each message becomes an Event, each cycle's
outbox is sent back. Requires the ``telegram`` extra and a bot token.

    pip install bentlyk[telegram]
    TELEGRAM_BOT_TOKEN=... TELEGRAM_ALLOWED_USER_ID=... bentlyk-telegram

Kept thin on purpose; it only does perception-in / action-out, never reasoning.
"""

from __future__ import annotations

from ..agent import Agent
from ..config import Settings
from ..events import message


def run(settings: Settings | None = None) -> int:  # pragma: no cover - needs network + extra
    settings = settings or Settings.from_env()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise SystemExit("install the telegram extra: pip install bentlyk[telegram]") from exc

    agent = Agent(settings=settings)
    agent.boot()
    allowed = settings.telegram_allowed_user_id

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if allowed and str(update.effective_user.id) != allowed:
            return
        cycle = agent.tick(message(update.message.text, source="telegram"))
        replies = cycle.outbox or [f"({cycle.headline()})"]
        for reply in replies:
            await update.message.reply_text(reply)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
