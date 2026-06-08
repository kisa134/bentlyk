"""Autonomy modes, risk levels, and the permission gate.

The gate is the second control loop of the architecture: before any action
runs it asks "given how I feel and how risky this is, am I *allowed* to do it
myself, or must I suggest / escalate?". Homeostasis raises and lowers the
autonomy ceiling; the gate enforces it per-action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class AutonomyMode(IntEnum):
    """How much the agent may do on its own. Ordered: higher == more freedom."""

    OBSERVE = 0  # only watch and think, never act outward
    SUGGEST = 1  # propose actions, but a human executes
    SAFE_ACT = 2  # autonomously perform reversible, low-risk actions
    ESCALATED_ACT = 3  # full autonomy: may perform any action on its own, incl. running code

    @classmethod
    def from_str(cls, value: str) -> "AutonomyMode":
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown autonomy mode: {value!r}") from exc

    @property
    def label(self) -> str:
        return self.name.lower()


class RiskLevel(IntEnum):
    """Per-action risk. Reversible + cheap == NONE; irreversible/outward == HIGH."""

    NONE = 0  # pure introspection / reads
    LOW = 1  # reversible writes to the agent's own store
    MEDIUM = 2  # outward but reversible (draft a message, create a note)
    HIGH = 3  # irreversible or externally consequential (send, pay, delete)


class GateDecision(IntEnum):
    ALLOW = 0  # run it now
    SUGGEST = 1  # don't run; surface as a proposal to the human
    CONFIRM = 2  # run only after explicit human confirmation
    DENY = 3  # refuse entirely under current state


@dataclass(slots=True)
class GateResult:
    decision: GateDecision
    reason: str


def permission_gate(
    *,
    autonomy: AutonomyMode,
    risk: RiskLevel,
    reversible: bool,
) -> GateResult:
    """Map (current autonomy, action risk) -> a decision.

    The table is intentionally conservative: when in doubt, suggest rather than
    act. This is what keeps a long-lived agent from drifting into damage.
    """

    if autonomy == AutonomyMode.OBSERVE:
        if risk == RiskLevel.NONE:
            return GateResult(GateDecision.ALLOW, "observation is always permitted")
        return GateResult(GateDecision.SUGGEST, "observe-only mode: action surfaced as suggestion")

    if autonomy == AutonomyMode.SUGGEST:
        if risk == RiskLevel.NONE:
            return GateResult(GateDecision.ALLOW, "reads permitted in suggest mode")
        return GateResult(GateDecision.SUGGEST, "suggest mode: human executes actions")

    if autonomy == AutonomyMode.SAFE_ACT:
        if risk <= RiskLevel.LOW:
            return GateResult(GateDecision.ALLOW, "low-risk action within safe-act budget")
        if risk == RiskLevel.MEDIUM and reversible:
            return GateResult(GateDecision.ALLOW, "reversible medium-risk action permitted")
        if risk == RiskLevel.MEDIUM:
            return GateResult(GateDecision.CONFIRM, "irreversible medium-risk needs confirmation")
        return GateResult(GateDecision.CONFIRM, "high-risk action escalated for confirmation")

    # ESCALATED_ACT — the top of the ladder: full autonomy, no brakes. Opt-in via
    # BENTLYK_MAX_AUTONOMY=escalated_act, and only meaningful on a dedicated body the
    # owner fully trusts (e.g. an isolated container). Everything is permitted here,
    # including running its own code.
    return GateResult(GateDecision.ALLOW, "full autonomy: action permitted")
