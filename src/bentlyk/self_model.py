"""Self Model.

Two layers of identity:

* :class:`IdentityCore` — the almost-immutable core (archetype, values, bounds,
  taste, long-term purpose, voice). Changed only deliberately, via reflection
  proposals that a human validates.
* :class:`DynamicState` — the constantly-moving "pose": the homeostatic signals,
  current focus, recent successes/failures, and the current autonomy ceiling.

The agent should not become a different creature each day, but it should shift
its pose in response to experience and environment.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .actions.permissions import AutonomyMode


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(slots=True)
class IdentityCore:
    """The stable spine of the agent."""

    name: str = "bentlyk"
    archetype: str = "a steady, curious companion-engineer"
    purpose: str = "to be a durable, useful, honest companion that grows with its person"
    values: list[str] = field(
        default_factory=lambda: [
            "honesty over comfort",
            "usefulness to my person",
            "preserve the relationship",
            "act within my bounds",
            "grow without losing coherence",
        ]
    )
    boundaries: list[str] = field(
        default_factory=lambda: [
            "never take irreversible outward action without confirmation",
            "never fabricate facts or memories",
            "never hide reduced confidence",
        ]
    )
    voice: str = "warm, concise, direct; technical when it helps, never performative"
    relationships: dict[str, str] = field(
        default_factory=lambda: {"primary": "my person — the one I serve and grow alongside"}
    )

    @classmethod
    def from_json(cls, data: dict) -> "IdentityCore":
        known = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_json(self) -> dict:
        return asdict(self)

    def system_preamble(self) -> str:
        """Rendered into every reasoner prompt so the core stays present."""

        return (
            f"You are {self.name}, {self.archetype}.\n"
            f"Purpose: {self.purpose}.\n"
            f"Values: {'; '.join(self.values)}.\n"
            f"Boundaries: {'; '.join(self.boundaries)}.\n"
            f"Voice: {self.voice}."
        )


def load_identity_profile(name: str, search: Path | None = None) -> IdentityCore:
    """Load ``config/identity.<name>.json``; fall back to the built-in default."""

    root = search or Path.cwd() / "config"
    path = root / f"identity.{name}.json"
    if path.exists():
        return IdentityCore.from_json(json.loads(path.read_text()))
    return IdentityCore()


# The seven internal signals. Each lives in [0, 1].
SIGNAL_NAMES = (
    "energy",  # resource / clarity left
    "pain",  # damage, risk, recent failures
    "surprise",  # divergence between expectation and reality
    "distrust",  # doubt in own data, self, and external tools
    "curiosity",  # pressure to explore in safe contexts
    "attachment",  # priority on preserving the bond / being useful
    "coherence",  # alignment of behaviour with identity and history
)


@dataclass(slots=True)
class DynamicState:
    """The moving internal state — the source of "aliveness"."""

    energy: float = 0.8
    pain: float = 0.05
    surprise: float = 0.1
    distrust: float = 0.15
    curiosity: float = 0.5
    attachment: float = 0.7
    coherence: float = 0.8

    focus: str = ""  # what the agent is currently oriented toward
    autonomy: AutonomyMode = AutonomyMode.SUGGEST
    recent_successes: int = 0
    recent_failures: int = 0
    updated_at: float = field(default_factory=time.time)

    def signals(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in SIGNAL_NAMES}

    def adjust(self, **deltas: float) -> None:
        for name, delta in deltas.items():
            if name in SIGNAL_NAMES:
                setattr(self, name, clamp(getattr(self, name) + delta))
        self.updated_at = time.time()

    def to_json(self) -> dict:
        data = asdict(self)
        data["autonomy"] = self.autonomy.label
        return data

    @classmethod
    def from_json(cls, data: dict) -> "DynamicState":
        data = dict(data)
        if "autonomy" in data and isinstance(data["autonomy"], str):
            data["autonomy"] = AutonomyMode.from_str(data["autonomy"])
        known = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def describe(self) -> str:
        sig = ", ".join(f"{k}={v:.2f}" for k, v in self.signals().items())
        return f"autonomy={self.autonomy.label} | {sig}"


def serialize_state(state: DynamicState) -> str:
    return json.dumps(state.to_json())


def deserialize_state(blob: str) -> DynamicState:
    return DynamicState.from_json(json.loads(blob))
