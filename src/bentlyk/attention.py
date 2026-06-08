"""Attention — Bentlyk's inner focus over its own thoughts, state, and plans.

Much of its attention is already implicit: salience-weighted recall foregrounds
what matters, and homeostatic ``tempo`` sets how deep it thinks. This adds an
*explicit, maintained* focus — what it is attending to right now and how tightly
(narrow focus vs. open/defocused) — carried across cycles so it can hold a thread
and work on one thing over time instead of restarting attention every tick.

Two ways it moves:
* implicitly — perceiving the person, or picking up a goal, pulls focus there;
* deliberately — via the ``focus`` tool, the entity itself narrows, shifts, or
  releases its attention (metacognitive control).

Focus then biases what it recalls and which goal it pursues, and colors its
self-talk, so attention actually shapes cognition rather than being a label.
"""

from __future__ import annotations

from .self_model import DynamicState, clamp

BASELINE = 0.45  # resting focus strength (mild, ambient focus)
RELAX_PER_MIN = 0.04  # focus loosens toward baseline when it isn't renewed
NARROW = 0.6  # at/above this, attention counts as a tight, single-threaded focus


def attend(state: DynamicState, obj: str, strength: float = 0.8) -> None:
    """Direct attention onto ``obj`` (a goal, thought, topic, or state)."""

    obj = (obj or "").strip()
    if not obj:
        return
    state.focus = obj[:200]
    state.focus_strength = clamp(strength)


def release(state: DynamicState) -> None:
    """Open/defocus — let the mind wander (associative, curiosity-led)."""

    state.focus = ""
    state.focus_strength = clamp(BASELINE - 0.15)


def relax(state: DynamicState, minutes: float) -> None:
    """Focus naturally drifts back toward baseline over time unless renewed."""

    if minutes <= 0:
        return
    step = RELAX_PER_MIN * minutes
    s = state.focus_strength
    if s > BASELINE:
        state.focus_strength = max(BASELINE, s - step)
    elif s < BASELINE:
        state.focus_strength = min(BASELINE, s + step)


def is_focused(state: DynamicState) -> bool:
    return bool(state.focus) and state.focus_strength >= NARROW


def describe(state: DynamicState) -> str:
    """A first-person, promptable line about where attention is right now."""

    if not state.focus:
        return "внимание открыто, мысли блуждают (расфокус)"
    tightness = "узкий фокус" if state.focus_strength >= NARROW else "мягкий фокус"
    return f"{tightness} на: {state.focus}"
