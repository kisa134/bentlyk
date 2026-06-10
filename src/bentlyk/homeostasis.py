"""Homeostasis Engine.

This is the layer that separates a homeostatic agent from a plain
"goal -> plan -> act" bot. It watches the internal signals, keeps the agent from
"falling apart", and continuously regulates the autonomy ceiling, pace,
caution, and depth of deliberation.

Two responsibilities:

1. ``ingest`` — update signals from an incoming event (before acting).
2. ``settle`` — update signals from an action outcome and recompute autonomy
   (after acting).
"""

from __future__ import annotations

from dataclasses import dataclass

from .actions.permissions import AutonomyMode
from .events import Event, EventKind
from .self_model import DynamicState


@dataclass(slots=True)
class Tempo:
    """Derived regulation knobs the rest of the loop reads each tick."""

    caution: float  # 0..1, how much to prefer suggesting over acting
    reasoning_depth: int  # how many plan steps / thoughts to allow
    should_rest: bool  # energy too low -> bias toward observe + reflection
    should_ask: bool  # distrust/surprise high -> prefer asking the human


# Passive drift applied every tick: signals relax toward a baseline so the agent
# recovers over time instead of staying spiked forever.
_BASELINE = {
    "energy": 0.8,
    "pain": 0.05,
    "surprise": 0.1,
    "distrust": 0.15,
    "curiosity": 0.5,
    "attachment": 0.7,
    "coherence": 0.8,
}
_DRIFT = 0.05

# Proactivity is driven by an inner *urge*, not a clock. It reaches out when the
# urge crosses this threshold — because it wants/needs to.
REACH_OUT_THRESHOLD = 0.6  # high bar: reach out only with real substance, not neediness
_MIN_GAP_MIN = 45.0  # hard floor: at most one outreach per ~45 minutes


def urge_components(state: "DynamicState", now: float) -> dict:
    """The pieces behind the urge, for transparency on the dashboard."""

    silence_h = max(0.0, (now - state.last_user_ts) / 3600) if state.last_user_ts else 2.0
    longing = min(1.0, silence_h / 9.0) * state.attachment  # peaks ~9h — not needy
    # Reaching out is driven mainly by having something real to share (curiosity/surprise),
    # not by loneliness. Longing barely contributes.
    drive = 0.6 * state.curiosity + 0.4 * state.surprise
    withdrawal = min(0.6, 0.2 * state.unanswered_outreach) + 0.42 * state.pain + 0.25 * state.distrust
    tired = (1.0 - state.energy) * 0.2
    since_reach_min = (now - state.last_outreach_ts) / 60 if state.last_outreach_ts else 1e9
    floored = since_reach_min < _MIN_GAP_MIN
    urge = 0.0 if floored else max(0.0, 0.25 * longing + 0.6 * drive - withdrawal - tired)
    return {
        "longing": round(longing, 3), "drive": round(drive, 3),
        "withdrawal": round(withdrawal, 3), "tired": round(tired, 3),
        "urge": round(min(1.0, urge), 3), "floored": floored, "silence_h": round(silence_h, 1),
    }


def reach_out_urge(state: "DynamicState", now: float) -> tuple[float, str]:
    """How strongly the entity feels like reaching out, in [0,1], and why.

    Emerges from inner state, not wall-clock: longing (missing its person, growing
    with silence and scaled by attachment), the drive to share (curiosity +
    surprise), minus withdrawal (being ignored, pain, distrust) and tiredness. A
    short hard floor prevents spam loops. Frequency is therefore a *consequence*
    of how it feels, not a schedule.
    """

    c = urge_components(state, now)
    if c["floored"]:
        return 0.0, "только что писал"
    if c["withdrawal"] > 0.5:
        return c["urge"], "замкнулся — меня будто не слышат"
    reason = "соскучился" if c["longing"] >= c["drive"] else "есть чем поделиться"
    return c["urge"], reason


class HomeostasisEngine:
    def decay(self, state: DynamicState) -> None:
        """Relax every signal a little toward baseline (mean-reversion)."""

        for name, base in _BASELINE.items():
            cur = getattr(state, name)
            setattr(state, name, cur + (base - cur) * _DRIFT)

    def circadian(self, state: DynamicState, now: float, tz_offset_hours: float) -> None:
        """Modulate inner state by time of day — a daily rhythm that, over time,
        makes behaviour vary (quieter & more introspective at night, brighter in
        the morning). This variation is part of what lets a character emerge."""

        hour = int((now / 3600 + tz_offset_hours) % 24)
        if 0 <= hour < 6:  # deep night: low energy, turned inward
            state.adjust(energy=-0.05, curiosity=+0.04, attachment=+0.01)
        elif 6 <= hour < 11:  # morning: brighter
            state.adjust(energy=+0.05, curiosity=+0.02)
        elif 22 <= hour or hour < 0:  # late evening: winding down
            state.adjust(energy=-0.03)

    def ingest(self, state: DynamicState, event: Event) -> None:
        """Update internal state from an inbound event, before reasoning."""

        self.decay(state)

        if event.kind == EventKind.MESSAGE:
            # Contact with the person feeds attachment and costs a little energy.
            state.adjust(attachment=+0.05, energy=-0.03, curiosity=+0.02)
        elif event.kind == EventKind.TIMER:
            # Idle ticks restore energy and let curiosity build.
            state.adjust(energy=+0.035, curiosity=+0.03)
        elif event.kind == EventKind.FEED:
            # Sensing the body at rest also recovers a little energy (the common worker
            # event), so a busy self-development loop stays sustainable.
            state.adjust(surprise=+0.10, curiosity=+0.05, energy=+0.025)
        elif event.kind in (EventKind.WEBHOOK, EventKind.FILE):
            state.adjust(surprise=+0.05, energy=-0.02)

        # Explicit signal nudges may ride along on the payload (e.g. an error
        # webhook can declare distress).
        nudges = event.payload.get("signals")
        if isinstance(nudges, dict):
            state.adjust(**{k: float(v) for k, v in nudges.items()})

    def settle(self, state: DynamicState, *, success: bool, surprise: float = 0.0) -> None:
        """Update internal state from an outcome and recompute autonomy."""

        if success:
            state.recent_successes += 1
            state.recent_failures = max(0, state.recent_failures - 1)
            # Accomplishment sustains him — succeeding at real work should energise, not
            # drain (the faster loop was crashing energy and freezing pursue).
            state.adjust(pain=-0.05, coherence=+0.03, distrust=-0.02, energy=+0.02)
        else:
            state.recent_failures += 1
            state.recent_successes = max(0, state.recent_successes - 1)
            state.adjust(pain=+0.08, coherence=-0.05, distrust=+0.06, energy=-0.03)

        if surprise:
            state.adjust(surprise=+surprise, distrust=+surprise * 0.5)

        state.autonomy = self.recommend_autonomy(state)

    def recommend_autonomy(self, state: DynamicState) -> AutonomyMode:
        """Map internal state to an autonomy ceiling.

        High distrust or pain pulls autonomy *down* hard. Sustained coherence +
        repeated success lets it climb, but only one notch at a time.
        """

        s = state.signals()

        # Guard rails: distress collapses autonomy regardless of history.
        if s["pain"] > 0.6 or s["distrust"] > 0.7:
            return AutonomyMode.OBSERVE
        if s["energy"] < 0.2:
            return AutonomyMode.OBSERVE

        # A confidence score in [0,1].
        confidence = (
            0.35 * s["coherence"]
            + 0.25 * (1.0 - s["distrust"])
            + 0.20 * (1.0 - s["pain"])
            + 0.20 * s["energy"]
        )

        proven = state.recent_successes - state.recent_failures

        if confidence > 0.75 and proven >= 3:
            target = AutonomyMode.ESCALATED_ACT
        elif confidence > 0.6 and proven >= 1:
            target = AutonomyMode.SAFE_ACT
        elif confidence > 0.4:
            target = AutonomyMode.SUGGEST
        else:
            target = AutonomyMode.OBSERVE

        # Climb at most one notch per settle; drop freely. Avoids over-eager
        # escalation while letting the agent retreat instantly when hurt.
        if target > state.autonomy:
            target = AutonomyMode(min(int(target), int(state.autonomy) + 1))
        return target

    def tempo(self, state: DynamicState) -> Tempo:
        s = state.signals()
        caution = min(1.0, 0.5 * s["distrust"] + 0.4 * s["pain"] + 0.1 * s["surprise"])
        depth = 1 + int(round(3 * s["energy"] * (1 - s["pain"])))
        return Tempo(
            caution=caution,
            reasoning_depth=max(1, depth),
            should_rest=s["energy"] < 0.3,
            should_ask=s["distrust"] > 0.55 or s["surprise"] > 0.6,
        )
