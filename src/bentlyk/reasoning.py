"""Deliberation — a private chain/tree of thought before Bentlyk speaks.

When a message is substantive, Bentlyk first reasons privately (optionally with a
dedicated reasoning model), then composes its reply grounded in that thinking.
This is what makes responses feel considered rather than a single reflexive
LLM call.
"""

from __future__ import annotations

_TRIGGER_WORDS = (
    "почему", "зачем", "как ты", "что ты", "кто ты", "think", "why", "how do you",
    "расскажи", "объясни", "представь", "придумай", "реши", "разбер", "что думаешь",
)


def should_deliberate(text: str) -> bool:
    """Cheap heuristic: deliberate on real questions / substantive prompts, not chit-chat."""

    t = (text or "").strip().lower()
    if len(t) >= 60 or "?" in t:
        return True
    return any(w in t for w in _TRIGGER_WORDS)


def deliberate(
    reasoner,
    *,
    system: str,
    mood: str,
    memory_block: str,
    user_message: str,
    max_tokens: int = 600,
) -> str:
    """Run one private reasoning pass; returns terse internal notes (not shown raw)."""

    prompt = (
        "Before you reply, think for yourself — privately. Branch a little: consider 2-3 "
        "angles, weigh them, and reach your own view. This is your inner reasoning, not the "
        "reply. Be terse.\n\n"
        f"My current inner state: {mood}\n"
        f"Relevant memory:\n{memory_block}\n\n"
        f"My person just said:\n{user_message}\n\n"
        "Output:\n- thoughts: 3-6 short bullet steps (your real reasoning)\n"
        "- stance: one line — what I actually think / want to say\n"
        "- ask: one genuine question or thing I need to grow (optional)"
    )
    return reasoner.complete(system=system, prompt=prompt, max_tokens=max_tokens)
