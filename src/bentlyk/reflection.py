"""Reflection / Sleep Layer.

Runs apart from the "waking" loop. It does not act outward. It:

* consolidates memory (compresses recent episodes into semantic/autobiographical
  summaries, and prunes faded items);
* performs a self-review of recent successes/failures;
* proposes changes to habits, strategies, and the self-model — but never applies
  identity changes itself; those are surfaced for human validation.

This is what makes the agent *develop* rather than drift chaotically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .llm import Reasoner
from .memory import MemoryItem, MemoryKind, MemoryStore
from .self_model import DynamicState, IdentityCore


@dataclass(slots=True)
class Reflection:
    summary: str
    consolidated: int  # episodes folded into semantic memory
    pruned: int  # faded memories forgotten
    proposals: list[str] = field(default_factory=list)  # suggested self-model changes
    created_at: float = field(default_factory=time.time)


class ReflectionEngine:
    def __init__(self, store: MemoryStore, reasoner: Reasoner) -> None:
        self._store = store
        self._reasoner = reasoner

    def sleep(self, *, identity: IdentityCore, state: DynamicState) -> Reflection:
        """Run one consolidation pass. Safe to call on a schedule (nightly)."""

        episodes = self._store.recent(MemoryKind.EPISODIC, limit=25)
        consolidated = self._consolidate(identity, episodes)
        pruned = self._store.decay_and_prune()
        proposals = self._self_review(identity, state, episodes)
        self._evolve_self_narrative(identity, state, episodes)

        summary = (
            f"slept: consolidated {consolidated} episode(s), pruned {pruned}, "
            f"{len(proposals)} proposal(s). state: {state.describe()}"
        )
        # The reflection itself becomes part of the agent's autobiography.
        self._store.add(
            MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=summary,
                tags=["reflection"],
                salience=0.7,
            )
        )
        return Reflection(
            summary=summary, consolidated=consolidated, pruned=pruned, proposals=proposals
        )

    def _evolve_self_narrative(
        self, identity: IdentityCore, state: DynamicState, episodes: list[MemoryItem]
    ) -> None:
        """Synthesize an evolving 'who I'm becoming' from lived experience.

        This is the emergence loop: experience -> reflection -> a self-description
        that flows back into future behaviour (it's injected into prompts), so a
        character forms over time without changing the fixed Identity Core.
        """

        if len(episodes) < 4:
            return
        prior = ""
        for m in self._store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=8):
            if "self_narrative" in m.tags:
                prior = m.content
                break
        joined = "\n".join(f"- {e.content}" for e in episodes[:20])
        try:
            narrative = self._reasoner.complete(
                system=identity.system_preamble(),
                prompt=(
                    "Looking at how I've actually been lately, write 2-3 first-person "
                    "sentences on who I am becoming — my forming character, tastes, "
                    "leanings. Evolve the previous version, don't restate the fixed core. "
                    "Be specific and honest.\n\n"
                    f"Previous self-narrative: {prior or '(none yet)'}\n\n"
                    f"Recent life:\n{joined}"
                ),
                max_tokens=300,
            ).strip()
        except Exception:
            return
        if narrative:
            self._store.add(
                MemoryItem(
                    kind=MemoryKind.AUTOBIOGRAPHICAL,
                    content=narrative,
                    tags=["self_narrative"],
                    salience=0.85,
                )
            )

    def _consolidate(self, identity: IdentityCore, episodes: list[MemoryItem]) -> int:
        if len(episodes) < 3:
            return 0
        joined = "\n".join(f"- {e.content}" for e in episodes)
        digest = self._reasoner.complete(
            system=identity.system_preamble(),
            prompt=(
                "Compress these recent episodes into 1-3 durable, factual takeaways "
                "(no speculation). One per line:\n" + joined
            ),
            max_tokens=400,
        )
        takeaways = [ln.strip(" -\t") for ln in digest.splitlines() if ln.strip()]
        for t in takeaways[:3]:
            self._store.add(
                MemoryItem(kind=MemoryKind.SEMANTIC, content=t, tags=["consolidated"], salience=0.65)
            )
        return len(takeaways[:3])

    def _self_review(
        self, identity: IdentityCore, state: DynamicState, episodes: list[MemoryItem]
    ) -> list[str]:
        proposals: list[str] = []
        # Deterministic guard-rail proposals from the numbers alone.
        if state.recent_failures > state.recent_successes:
            proposals.append(
                "recent failures exceed successes: hold autonomy at suggest until a streak of wins"
            )
        if state.coherence < 0.5:
            proposals.append("coherence low: schedule a memory reconciliation before new goals")
        if not episodes:
            proposals.append("little lived experience yet: bias toward observation and questions")
        return proposals
