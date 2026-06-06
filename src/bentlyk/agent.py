"""The orchestrator: the main loop as a state machine.

One ``tick`` is one pass through the eight layers:

    perceive -> update state (homeostasis) -> retrieve memory -> generate &
    select goal -> plan/reason -> permission gate -> act/suggest -> record
    outcome -> settle (homeostasis) -> (periodically) reflect/sleep

This is the homeostatic loop: the inner control loop ("what state am I in and
may I act?") wraps the outer one ("goal -> plan -> act").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .actions import (
    ActionResult,
    GateDecision,
    ToolRegistry,
    default_registry,
    permission_gate,
)
from .config import Settings
from .events import Event, EventKind, normalize
from .goals import GoalCandidate, GoalEngine
from .homeostasis import HomeostasisEngine
from .llm import build_reasoner
from .memory import MemoryItem, MemoryKind, MemoryStore, open_store
from .persistence import StatePersistence
from .planner import Decision, Move, Planner
from .reflection import Reflection, ReflectionEngine
from .self_model import DynamicState, IdentityCore, load_identity_profile


@dataclass(slots=True)
class CycleResult:
    event: Event
    goal: GoalCandidate | None
    decision: Decision | None
    gate: GateDecision | None
    result: ActionResult | None
    outbox: list[str] = field(default_factory=list)
    reflection: Reflection | None = None

    def headline(self) -> str:
        if self.decision is None:
            return "idle (no actionable goal)"
        move = self.decision.move.value
        if self.decision.move == Move.ACT and self.gate is not None:
            return f"{move}:{self.decision.tool} -> gate={self.gate.name.lower()}"
        return move


class Agent:
    """A long-lived companion agent. Drive it by feeding events to ``tick``."""

    REFLECT_EVERY = 10  # ticks between automatic sleep passes

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: MemoryStore | None = None,
        identity: IdentityCore | None = None,
        state: DynamicState | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.store = store or open_store(
            self.settings.store, sqlite_path=self.settings.sqlite_path, pg_dsn=self.settings.pg_dsn
        )
        self._persistence = StatePersistence.beside(self.settings.sqlite_path)

        saved_identity, saved_state = self._persistence.load()
        # Precedence: explicit arg > persisted > named profile > built-in default.
        self.identity = (
            identity or saved_identity or load_identity_profile(self.settings.identity)
        )
        self.state = state or saved_state or DynamicState(autonomy=self.settings.max_autonomy)

        self.homeostasis = HomeostasisEngine()
        self.goals = GoalEngine(self.store)
        self.registry: ToolRegistry = default_registry()
        reasoner = build_reasoner(api_key=self.settings.anthropic_api_key, model=self.settings.model)
        self.planner = Planner(reasoner, self.registry)
        reflection_reasoner = build_reasoner(
            api_key=self.settings.anthropic_api_key, model=self.settings.reflection_model
        )
        self.reflection = ReflectionEngine(self.store, reflection_reasoner)

        self._ticks = 0

    # --- the loop -------------------------------------------------------------
    def tick(self, raw_event: object) -> CycleResult:
        event = normalize(raw_event)
        self._ticks += 1

        # 1-2. Perceive + update internal state.
        self.homeostasis.ingest(self.state, event)
        tempo = self.homeostasis.tempo(self.state)

        # 3. Retrieve relevant memory.
        memories = self.store.recall(event.content or event.kind.value, limit=6)

        # 4-5. Generate and select a goal; cap autonomy by the configured ceiling.
        candidates = self.goals.generate(event=event, state=self.state)
        goal = self.goals.select(candidates)
        self._clamp_autonomy()

        outbox: list[str] = []
        if goal is None:
            self._record_episode(event, "no actionable goal selected", success=True)
            self.homeostasis.settle(self.state, success=True)
            return self._finish(CycleResult(event, None, None, None, None, outbox))

        # 6. Plan / reason.
        decision = self.planner.decide(
            identity=self.identity,
            state=self.state,
            tempo=tempo,
            goal=goal,
            memories=memories,
        )

        gate_decision: GateDecision | None = None
        result: ActionResult | None = None

        if decision.move == Move.ASK:
            outbox.append(decision.message or "Could you clarify how you'd like me to proceed?")
            self._record_episode(event, f"asked: {decision.message}", success=True)
            self.homeostasis.settle(self.state, success=True)

        elif decision.move == Move.THINK:
            thought = decision.rationale or "deliberated internally"
            self._record_episode(event, f"thought: {thought}", success=True)
            self.homeostasis.settle(self.state, success=True)

        else:  # Move.ACT
            gate_decision, result = self._gated_act(decision, outbox)
            success = bool(result and result.ok) and gate_decision == GateDecision.ALLOW
            surprise = result.surprise if result else 0.2
            self._record_episode(
                event,
                f"act {decision.tool}: gate={gate_decision.name.lower()} "
                f"result={(result.output if result else 'not run')[:120]}",
                success=success,
            )
            self.homeostasis.settle(self.state, success=success, surprise=surprise)

        cycle = CycleResult(event, goal, decision, gate_decision, result, outbox)

        # 10. Periodic reflection/sleep.
        if self._ticks % self.REFLECT_EVERY == 0:
            cycle.reflection = self.sleep()

        return self._finish(cycle)

    def sleep(self) -> Reflection:
        """Run a reflection/consolidation pass on demand."""

        refl = self.reflection.sleep(identity=self.identity, state=self.state)
        self._persistence.save(self.identity, self.state)
        return refl

    # --- helpers --------------------------------------------------------------
    def _gated_act(
        self, decision: Decision, outbox: list[str]
    ) -> tuple[GateDecision, ActionResult | None]:
        tool = self.registry.get(decision.tool or "")
        if tool is None:
            return GateDecision.DENY, ActionResult(ok=False, output="unknown tool", surprise=0.3)

        gate = permission_gate(
            autonomy=self.state.autonomy, risk=tool.risk, reversible=tool.reversible
        )

        if gate.decision == GateDecision.ALLOW:
            context = {"store": self.store, "state": self.state, "outbox": outbox}
            result = tool.run(decision.tool_args, context)
            return gate.decision, result

        if gate.decision in (GateDecision.SUGGEST, GateDecision.CONFIRM):
            verb = "Suggesting" if gate.decision == GateDecision.SUGGEST else "Requesting approval"
            outbox.append(
                f"[{verb}] I would run `{decision.tool}` "
                f"({decision.rationale or 'to advance the goal'}). Reason gate: {gate.reason}."
            )
            return gate.decision, None

        outbox.append(f"[Declined] I won't run `{decision.tool}` right now: {gate.reason}.")
        return gate.decision, None

    def _clamp_autonomy(self) -> None:
        if self.state.autonomy > self.settings.max_autonomy:
            self.state.autonomy = self.settings.max_autonomy

    def _record_episode(self, event: Event, outcome: str, *, success: bool) -> None:
        tags = ["episode"] + (["success"] if success else ["failure"])
        if event.kind == EventKind.MESSAGE:
            tags.append("message")
        self.store.add(
            MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"{event.summary()} => {outcome}",
                tags=tags,
                salience=0.55 if success else 0.7,
            )
        )

    def _finish(self, cycle: CycleResult) -> CycleResult:
        # settle() may have raised autonomy; enforce the configured ceiling last.
        self._clamp_autonomy()
        self._persistence.save(self.identity, self.state)
        return cycle

    # --- lifecycle ------------------------------------------------------------
    def boot(self) -> None:
        self.store.add(
            MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=f"booted as {self.identity.name}; {self.state.describe()}",
                tags=["lifecycle", "boot"],
                salience=0.6,
            )
        )

    def close(self) -> None:
        self._persistence.save(self.identity, self.state)
        self.store.close()
