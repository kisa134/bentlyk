"""Goal Engine.

For autonomy, the agent must not wait for instructions — it must regularly emit
*goal candidates*. Candidates come from three sources:

* external events — someone wrote, news broke, a project status changed;
* internal imbalances — overload, chaos, unfinished business, falling coherence;
* long-term aspirations — become more useful, preserve the relationship,
  improve its own skills.

Each candidate is scored:

    score = value_alignment + urgency + attachment + curiosity - risk - uncertainty
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from .events import Event, EventKind
from .memory import MemoryKind, MemoryStore
from .self_model import DynamicState


class GoalSource(str, Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    ASPIRATIONAL = "aspirational"


@dataclass(slots=True)
class GoalCandidate:
    description: str
    source: GoalSource
    value_alignment: float = 0.5
    urgency: float = 0.3
    attachment: float = 0.3
    curiosity: float = 0.3
    risk: float = 0.2
    uncertainty: float = 0.3
    conversational: bool = False  # a direct reply to the person is owed
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    @property
    def is_conversational(self) -> bool:
        return self.conversational

    @property
    def score(self) -> float:
        return (
            self.value_alignment
            + self.urgency
            + self.attachment
            + self.curiosity
            - self.risk
            - self.uncertainty
        )


class GoalEngine:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def generate(
        self, *, event: Event | None, state: DynamicState
    ) -> list[GoalCandidate]:
        candidates: list[GoalCandidate] = []
        candidates.extend(self._from_external(event, state))
        candidates.extend(self._from_internal(state))
        candidates.extend(self._from_aspirational(state))
        return candidates

    def select(self, candidates: list[GoalCandidate]) -> GoalCandidate | None:
        """Pick the highest-scoring candidate above a small floor."""

        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        for c in ranked:
            if c.score > 0.2:
                return c
        return None

    # --- sources --------------------------------------------------------------
    def _from_external(
        self, event: Event | None, state: DynamicState
    ) -> list[GoalCandidate]:
        if event is None:
            return []
        if event.kind == EventKind.MESSAGE:
            return [
                GoalCandidate(
                    description=f"respond usefully to: {event.summary()}",
                    source=GoalSource.EXTERNAL,
                    value_alignment=0.8,
                    urgency=0.7,
                    attachment=state.attachment,
                    curiosity=0.2,
                    risk=0.1,
                    uncertainty=0.2,
                    conversational=True,
                )
            ]
        if event.kind in (EventKind.FEED, EventKind.WEBHOOK, EventKind.FILE):
            return [
                GoalCandidate(
                    description=f"assess and integrate external signal: {event.summary()}",
                    source=GoalSource.EXTERNAL,
                    value_alignment=0.5,
                    urgency=0.4,
                    attachment=0.2,
                    curiosity=state.curiosity,
                    risk=0.2,
                    uncertainty=0.4,
                )
            ]
        return []

    def _from_internal(self, state: DynamicState) -> list[GoalCandidate]:
        out: list[GoalCandidate] = []
        s = state.signals()

        if s["coherence"] < 0.5 or s["distrust"] > 0.5:
            out.append(
                GoalCandidate(
                    description="reduce my own confusion: reconcile recent memory and self-state",
                    source=GoalSource.INTERNAL,
                    value_alignment=0.6,
                    urgency=0.5,
                    attachment=0.2,
                    curiosity=0.2,
                    risk=0.05,
                    uncertainty=0.3,
                )
            )
        if s["pain"] > 0.5:
            out.append(
                GoalCandidate(
                    description="recover: lower autonomy, review recent failures, stabilize",
                    source=GoalSource.INTERNAL,
                    value_alignment=0.7,
                    urgency=0.8,
                    attachment=0.3,
                    curiosity=0.0,
                    risk=0.05,
                    uncertainty=0.2,
                )
            )
        # Unfinished business held in episodic memory tagged as a promise.
        promises = [m for m in self._store.all(MemoryKind.EPISODIC) if "promise" in m.tags]
        for p in promises[:2]:
            out.append(
                GoalCandidate(
                    description=f"follow through on an open promise: {p.content}",
                    source=GoalSource.INTERNAL,
                    value_alignment=0.7,
                    urgency=0.5,
                    attachment=state.attachment,
                    curiosity=0.1,
                    risk=0.15,
                    uncertainty=0.3,
                )
            )
        return out

    def _from_aspirational(self, state: DynamicState) -> list[GoalCandidate]:
        out: list[GoalCandidate] = []
        s = state.signals()
        if s["curiosity"] > 0.6 and s["energy"] > 0.4:
            out.append(
                GoalCandidate(
                    description="surface a new insight from accumulated signals, if warranted",
                    source=GoalSource.ASPIRATIONAL,
                    value_alignment=0.5,
                    urgency=0.2,
                    attachment=0.3,
                    curiosity=s["curiosity"],
                    risk=0.2,
                    uncertainty=0.5,
                )
            )
        out.append(
            GoalCandidate(
                description="become incrementally more useful and preserve the relationship",
                source=GoalSource.ASPIRATIONAL,
                value_alignment=0.6,
                urgency=0.1,
                attachment=state.attachment,
                curiosity=0.2,
                risk=0.05,
                uncertainty=0.4,
            )
        )
        return out
