"""Shared bootstrap for the Vercel serverless functions.

Each Vercel function is stateless and short-lived, so Bentlyk's continuity lives
entirely in Postgres (Supabase): on every request we rebuild the Agent, which
loads its self-model and memory from the database, processes one event, and
persists again.

This module also holds the tiny Telegram HTTP client (urllib, no SDK) and the
owner-claim logic that keeps the bot private to one person.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# Make the src-layout package importable from within the api/ functions.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from bentlyk import Agent, message, timer  # noqa: E402
from bentlyk.memory import MemoryItem, MemoryKind  # noqa: E402

TELEGRAM_API = "https://api.telegram.org"


def build_agent() -> Agent:
    """Construct an Agent from the environment (Postgres-backed in production)."""

    return Agent()


# --- Telegram client ----------------------------------------------------------
def tg_call(token: str, method: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{TELEGRAM_API}/bot{token}/{method}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": exc.read().decode(errors="replace")[:300]}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}


def tg_send(token: str, chat_id: int | str, text: str) -> None:
    # Telegram caps messages at 4096 chars; split safely.
    for chunk in _chunks(text, 4000):
        tg_call(token, "sendMessage", {"chat_id": chat_id, "text": chunk})


def _chunks(text: str, size: int) -> list[str]:
    text = text or "…"
    return [text[i : i + size] for i in range(0, len(text), size)]


# --- owner gate ---------------------------------------------------------------
_OWNER_TAG = "owner"


def owner_id(agent: Agent) -> str | None:
    for m in agent.store.all(MemoryKind.SEMANTIC):
        if _OWNER_TAG in m.tags and m.content.startswith("owner:"):
            return m.content.split(":", 1)[1].strip()
    return None


def check_or_claim_owner(agent: Agent, user_id: str) -> bool:
    """Return True if this user may talk to Bentlyk.

    Priority: an explicit TELEGRAM_ALLOWED_USER_ID env always wins. Otherwise the
    first person to message claims ownership and is remembered; everyone else is
    politely refused.
    """

    allowed = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if allowed:
        return str(user_id) == allowed

    current = owner_id(agent)
    if current is None:
        agent.store.add(
            MemoryItem(
                kind=MemoryKind.SEMANTIC,
                content=f"owner:{user_id}",
                tags=[_OWNER_TAG],
                salience=1.0,
            )
        )
        return True
    return current == str(user_id)


__all__ = [
    "Agent",
    "build_agent",
    "message",
    "timer",
    "tg_call",
    "tg_send",
    "check_or_claim_owner",
    "owner_id",
]
