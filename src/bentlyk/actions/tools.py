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


def _respond(args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
    """Reply to the person in conversation, grounded in identity, state & memory.

    This is the core companion behaviour. Talking to one's own person is not a
    risky outward action, so it is permitted at every autonomy level; the words
    themselves are crafted by the reasoner.
    """

    outbox = context.setdefault("outbox", [])
    reasoner = context.get("reasoner")
    identity = context.get("identity")
    state = context.get("state")
    store = context.get("store")
    memories = context.get("memories") or []
    user_message = str(args.get("text") or context.get("user_message") or "").strip()

    mem = "\n".join(f"- ({m.kind.value}) {m.content}" for m in memories) or "(nothing relevant yet)"
    preamble = identity.system_preamble() if identity else "You are bentlyk."
    mood = state.describe() if state else ""
    system = (
        preamble
        + f"\nYour current internal state — let it subtly color your tone, never name it: {mood}."
    )
    prompt = (
        "Reply to your person's message as yourself, in your own voice — genuine, "
        "concise, and honest. Lean on the relevant memory below when it helps. Never "
        "mention internal variables, tools, or that you are a language model.\n\n"
        f"RELEVANT MEMORY:\n{mem}\n\nYOUR PERSON JUST SAID:\n{user_message or '(greeting)'}"
    )

    if reasoner is None:  # pragma: no cover - reasoner always provided in the loop
        return ActionResult(ok=False, output="no reasoner available")

    try:
        reply = reasoner.complete(system=system, prompt=prompt, max_tokens=700).strip()
    except Exception as exc:  # keep the conversation alive even if the model fails
        outbox.append(
            "Я тебя слышу, но прямо сейчас не получается собрать мысли — что-то с моим "
            "разумом. Давай ещё раз через минуту?"
        )
        return ActionResult(ok=False, output=f"reasoner error: {exc}", surprise=0.5)

    reply = reply or "…"
    outbox.append(reply)
    if store is not None and user_message:
        store.add(
            MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"my person said: {user_message}",
                tags=["conversation", "message"],
                salience=0.5,
            )
        )
        store.add(
            MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"I replied: {reply}",
                tags=["conversation", "reply"],
                salience=0.45,
            )
        )
    return ActionResult(ok=True, output=reply[:150])


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
            name="respond",
            description="reply to your person in conversation (grounded in identity, state, memory)",
            risk=RiskLevel.NONE,
            reversible=True,
            handler=_respond,
        ),
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
