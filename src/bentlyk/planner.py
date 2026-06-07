"""Planner / Reasoner.

Given the selected goal, current state, retrieved memory, and the tool catalog,
the planner decides one of three moves:

* ``think``  — deliberate further internally (no outward effect);
* ``ask``    — ask the person (when uncertainty/distrust is high);
* ``act``    — propose a concrete tool invocation.

It also decomposes the goal into a short plan. The reasoner backend (real Claude
or the offline mock) is consulted, but the planner also enforces hard rules from
homeostasis so a misbehaving model can't push past the agent's caution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .actions import ToolRegistry
from .goals import GoalCandidate
from .homeostasis import Tempo
from .llm import Reasoner
from .memory import MemoryItem
from .self_model import DynamicState, IdentityCore


class Move(str, Enum):
    THINK = "think"
    ASK = "ask"
    ACT = "act"


@dataclass(slots=True)
class Decision:
    move: Move
    rationale: str = ""
    plan: list[str] = field(default_factory=list)
    tool: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    message: str = ""  # text for ASK, or a spoken THINK summary


class Planner:
    def __init__(self, reasoner: Reasoner, registry: ToolRegistry) -> None:
        self._reasoner = reasoner
        self._registry = registry

    def decide(
        self,
        *,
        identity: IdentityCore,
        state: DynamicState,
        tempo: Tempo,
        goal: GoalCandidate,
        memories: list[MemoryItem],
    ) -> Decision:
        # Hard homeostatic overrides come first — these are not the model's call.
        if tempo.should_ask and goal.uncertainty > 0.4:
            return Decision(
                move=Move.ASK,
                rationale="distrust/surprise high and goal is uncertain: ask the person",
                message=self._clarifying_question(goal),
            )

        # A direct message from the person is answered conversationally. Replying
        # to one's own person is the baseline behaviour, so it bypasses the rest
        # override (the reply itself can acknowledge low energy) and is gated as a
        # risk-free action.
        if goal.is_conversational:
            return Decision(
                move=Move.ACT,
                tool="respond",
                rationale="reply to my person",
            )

        if tempo.should_rest:
            return Decision(
                move=Move.THINK,
                rationale="energy low: resting and consolidating instead of acting",
                plan=["lower exertion", "let reflection consolidate later"],
            )

        raw = self._reasoner.complete(
            system=identity.system_preamble(),
            prompt=self._prompt(state, tempo, goal, memories),
            max_tokens=600,
        )
        decision = self._parse(raw, goal, tempo)
        return decision

    # --- prompt + parsing -----------------------------------------------------
    def _prompt(
        self,
        state: DynamicState,
        tempo: Tempo,
        goal: GoalCandidate,
        memories: list[MemoryItem],
    ) -> str:
        mem = "\n".join(f"- ({m.kind.value}) {m.content}" for m in memories) or "(none)"
        return (
            "Decide your next move toward the goal. Respond with a JSON object with keys: "
            '"decision" (one of think|ask|act), "rationale", "tool" (tool name or null), '
            '"tool_args" (object), "plan" (array of <=' + str(tempo.reasoning_depth) + " short "
            'steps), "message" (text if asking).\n\n'
            f"GOAL: {goal.description} (score={goal.score:.2f}, uncertainty={goal.uncertainty:.2f})\n"
            f"INTERNAL STATE: {state.describe()}\n"
            f"CAUTION: {tempo.caution:.2f} (higher means prefer think/ask over act)\n"
            f"TOOLS:\n{self._registry.describe()}\n\n"
            f"RELEVANT MEMORY:\n{mem}\n"
        )

    def _parse(self, raw: str, goal: GoalCandidate, tempo: Tempo) -> Decision:
        data = _extract_json(raw)
        if not data:
            # Couldn't parse: default to the safest useful move.
            return Decision(
                move=Move.THINK,
                rationale="reasoner output unparseable; defaulting to deliberation",
                plan=["re-read the goal", "retry with a smaller step"],
            )

        move = _coerce_move(str(data.get("decision", "think")))
        tool = data.get("tool") or None
        tool_args = data.get("tool_args") or {}
        plan = [str(s) for s in (data.get("plan") or [])][: tempo.reasoning_depth]
        rationale = str(data.get("rationale", ""))
        message = str(data.get("message", ""))

        # Validate the proposed tool exists; otherwise downgrade to THINK.
        if move == Move.ACT:
            if not tool or self._registry.get(str(tool)) is None:
                return Decision(
                    move=Move.THINK,
                    rationale=f"proposed unknown tool {tool!r}; deliberating instead",
                    plan=plan,
                )
        return Decision(
            move=move,
            rationale=rationale,
            plan=plan,
            tool=str(tool) if tool else None,
            tool_args=dict(tool_args),
            message=message,
        )

    def _clarifying_question(self, goal: GoalCandidate) -> str:
        return (
            f"I'm not confident enough to act on this on my own yet: "
            f"\"{goal.description}\". How would you like me to proceed?"
        )


def _coerce_move(value: str) -> Move:
    value = value.strip().lower()
    for m in Move:
        if m.value == value:
            return m
    return Move.THINK


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Tolerate prose around the JSON object.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
