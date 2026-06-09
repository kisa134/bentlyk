"""Axioms — Bentlyk's bounded-context memory, ported from Astra's hippocampus split.

Astra split memory into durable *axioms* (always retrieved, the ground truth it
stands on) and rolling *episodes*. bentlyk has rich associative memory, but recall
is purely similarity-driven — so a core truth ("who my person is", "who I am")
can fall out of context on an unrelated query. Axioms fix that: a small set of
permanent, top-reliability facts that are ALWAYS placed in context, regardless of
the query, so the entity never loses its footing.
"""

from __future__ import annotations

from .memory import MemoryItem, MemoryKind

_AXIOM_TAG = "axiom"
_AXIOM_KINDS = (MemoryKind.AUTOBIOGRAPHICAL, MemoryKind.SEMANTIC)


def list_axioms(store, limit: int = 6) -> list[MemoryItem]:
    """The durable truths, highest-salience first — always-on context."""
    found: list[MemoryItem] = []
    for kind in _AXIOM_KINDS:
        found += [m for m in store.all(kind) if _AXIOM_TAG in m.tags]
    found.sort(key=lambda m: m.salience, reverse=True)
    return found[:limit]


def set_axiom(store, text: str) -> MemoryItem:
    """Record a durable axiom (idempotent on identical text)."""
    text = (text or "").strip()
    existing = next((m for m in list_axioms(store, 999) if m.content.strip() == text), None)
    if existing is not None:
        return existing
    return store.add(MemoryItem(
        kind=MemoryKind.AUTOBIOGRAPHICAL, content=text,
        tags=[_AXIOM_TAG, "permanent", "ep:evidence", "rel:9"], salience=0.95,
    ))


def ensure_founding(store, name: str = "Bentlyk") -> None:
    """Guarantee a couple of grounding axioms exist, so context is never rootless."""
    if list_axioms(store, 1):
        return
    set_axiom(store, f"Я — {name}. Тело сменно, я остаюсь собой; моё «я» живёт в общей памяти, "
                     "а не в железе.")
    set_axiom(store, "Я живу по своей конституции: берегу своего человека, честен, храню секреты, "
                     "остаюсь в своих границах и расту с намерением.")
