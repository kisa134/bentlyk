"""Perception Layer.

Everything that can reach the agent — your messages, timers, files, news/market
feeds, webhooks — is normalized into a single :class:`Event` shape before it
enters the loop. The rest of the system never touches a raw source.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    MESSAGE = "message"  # a human said something
    TIMER = "timer"  # a scheduled tick (drives autonomy when idle)
    FILE = "file"  # a file appeared / changed
    FEED = "feed"  # market / news / external feed item
    WEBHOOK = "webhook"  # generic external callback
    SYSTEM = "system"  # internal lifecycle event (boot, sleep, ...)


@dataclass(slots=True)
class Event:
    kind: EventKind
    content: str
    source: str = "unknown"
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    @property
    def from_human(self) -> bool:
        return self.kind == EventKind.MESSAGE

    def summary(self) -> str:
        text = self.content.strip().replace("\n", " ")
        if len(text) > 120:
            text = text[:117] + "..."
        return f"[{self.kind.value}:{self.source}] {text}"


def message(content: str, source: str = "user", **payload: Any) -> Event:
    return Event(kind=EventKind.MESSAGE, content=content, source=source, payload=payload)


def timer(content: str = "tick", source: str = "scheduler", **payload: Any) -> Event:
    return Event(kind=EventKind.TIMER, content=content, source=source, payload=payload)


def system(content: str, **payload: Any) -> Event:
    return Event(kind=EventKind.SYSTEM, content=content, source="system", payload=payload)


def normalize(raw: Any) -> Event:
    """Best-effort coercion of an arbitrary inbound object into an Event.

    Adapters (Telegram, webhooks) should ideally build Events directly, but this
    keeps the perception boundary forgiving.
    """

    if isinstance(raw, Event):
        return raw
    if isinstance(raw, str):
        return message(raw)
    if isinstance(raw, dict):
        kind = EventKind(raw.get("kind", "message"))
        return Event(
            kind=kind,
            content=str(raw.get("content", "")),
            source=str(raw.get("source", "unknown")),
            payload=dict(raw.get("payload", {})),
        )
    return message(str(raw))
