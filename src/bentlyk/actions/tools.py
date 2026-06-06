"""Built-in tools.

A deliberately small, safe starter set spanning the risk spectrum so the
permission gate is exercised end to end. Real deployments add browser, calendar,
Telegram-send, code-runner, and project-API tools here — each declaring its risk
and reversibility.

Context keys available to handlers:
* ``store``   - the MemoryStore
* ``state``   - the DynamicState
* ``outbox``  - a list the agent appends user-facing messages to
"""

from __future__ import annotations

from typing import Any

from ..memory import MemoryItem, MemoryKind
from .base import ActionResult, Tool
from .permissions import RiskLevel


def _reflect(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    note = str(args.get("note", "")).strip()
    return ActionResult(ok=True, output=f"reflected: {note or '(no note)'}")


def _recall(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    store = context["store"]
    query = str(args.get("query", ""))
    hits = store.recall(query, limit=int(args.get("limit", 5)))
    if not hits:
        return ActionResult(ok=True, output="no relevant memories", surprise=0.1)
    body = "\n".join(f"- ({h.kind.value}) {h.content}" for h in hits)
    return ActionResult(ok=True, output=f"recalled {len(hits)}:\n{body}")


def _remember(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    store = context["store"]
    content = str(args.get("content", "")).strip()
    if not content:
        return ActionResult(ok=False, output="nothing to remember", surprise=0.2)
    kind = MemoryKind(args.get("kind", MemoryKind.SEMANTIC.value))
    tags = list(args.get("tags", []))
    salience = float(args.get("salience", 0.6))
    item = store.add(MemoryItem(kind=kind, content=content, tags=tags, salience=salience))
    return ActionResult(ok=True, output=f"remembered ({kind.value}) {item.id[:8]}")


def _note(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    # A reversible outward artifact: persisted as a procedural note.
    store = context["store"]
    content = str(args.get("content", "")).strip()
    if not content:
        return ActionResult(ok=False, output="empty note")
    store.add(MemoryItem(kind=MemoryKind.PROCEDURAL, content=f"NOTE: {content}", tags=["note"]))
    return ActionResult(ok=True, output="note saved")


def _say(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    # Outward, reversible-ish: queue a message to the person.
    outbox = context.setdefault("outbox", [])
    text = str(args.get("text", "")).strip()
    if not text:
        return ActionResult(ok=False, output="nothing to say")
    outbox.append(text)
    return ActionResult(ok=True, output=f"queued message: {text[:60]}")


def build_builtin_tools() -> list[Tool]:
    return [
        Tool(
            name="reflect",
            description="think privately about the situation; no outward effect",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_reflect,
        ),
        Tool(
            name="recall",
            description="retrieve relevant memories for a query",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_recall,
        ),
        Tool(
            name="remember",
            description="write a memory item to a chosen contour",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_remember,
        ),
        Tool(
            name="note",
            description="save a durable procedural note",
            risk=RiskLevel.LOW,
            reversible=True,
            handler=_note,
        ),
        Tool(
            name="say",
            description="send a message to the person",
            risk=RiskLevel.MEDIUM,
            reversible=True,
            handler=_say,
        ),
    ]
