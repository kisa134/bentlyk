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
from .self_model import (
    DynamicState,
    IdentityCore,
    load_identity_profile,
    temporal_context,
)


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
        if store is not None:
            self.store = store
            self._persistence = StatePersistence.beside(self.settings.sqlite_path)
        else:
            self.store, self._persistence = self._open_backends()

        saved_identity, saved_state = self._persistence.load()
        # Identity is code/profile-driven so deploys update it cleanly; only the
        # moving DynamicState is restored from persistence. (saved_identity is
        # ignored on purpose — identity changes go through reflection proposals.)
        _ = saved_identity
        self.identity = identity or load_identity_profile(self.settings.identity)
        self.state = state or saved_state or DynamicState(autonomy=self.settings.max_autonomy)

        self.homeostasis = HomeostasisEngine()
        self.goals = GoalEngine(self.store)
        self.registry: ToolRegistry = default_registry()
        self.reasoner = build_reasoner(self.settings)  # chat
        self.reason_reasoner = build_reasoner(
            self.settings, model=self.settings.effective_reason_model
        )  # deep chain-of-thought
        self.planner = Planner(self.reasoner, self.registry)
        reflection_reasoner = build_reasoner(
            self.settings, model=self.settings.effective_reflection_model
        )
        self.reflection = ReflectionEngine(self.store, reflection_reasoner)

        self._ticks = self.state.tick_count

    # --- the loop -------------------------------------------------------------
    def tick(self, raw_event: object) -> CycleResult:
        import time as _t

        event = normalize(raw_event)
        now = _t.time()
        self.state.tick_count += 1
        self._ticks = self.state.tick_count
        if self.state.birth_ts == 0.0:  # first breath: anchor my age
            self.state.birth_ts = now
        self.state.last_event_ts = now

        # The person spoke: reset proactive backoff so I feel free to reach out again.
        if event.from_human:
            self.state.last_user_ts = now
            self.state.unanswered_outreach = 0

        # 1-2. Perceive + update internal state (incl. the daily rhythm).
        self.homeostasis.ingest(self.state, event)
        self.homeostasis.circadian(self.state, now, self.settings.tz_offset_hours)
        tempo = self.homeostasis.tempo(self.state)

        # 3. Retrieve relevant memory, expanded along the memory graph (associative).
        memories = self.store.recall(event.content or event.kind.value, limit=6)
        if hasattr(self.store, "neighbors") and memories:
            seen = {m.id for m in memories}
            for n in self.store.neighbors([m.id for m in memories], limit=4):
                if n.id not in seen:
                    memories.append(n)
                    seen.add(n.id)

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
            gate_decision, result = self._gated_act(decision, outbox, event, memories)
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

    def _open_backends(self):
        """Pick the memory store + persistence, degrading gracefully.

        If Postgres is requested but unreachable/misconfigured, fall back to an
        ephemeral SQLite store so the agent keeps talking (without long-term
        memory) instead of hard-crashing. The failure is logged for diagnosis.
        """

        # Preferred: Supabase over HTTPS REST (serverless-friendly, no pooler/IPv6).
        if self.settings.supabase_enabled:  # pragma: no cover - needs network
            try:
                from .supabase_rest import SupabaseRest, SupabaseRestState

                store = SupabaseRest(self.settings.supabase_url, self.settings.supabase_key)
                store.recent(MemoryKind.EPISODIC, 1)  # probe connectivity + grants
                print("[bentlyk] memory: supabase REST", flush=True)
                return store, SupabaseRestState(self.settings.supabase_url, self.settings.supabase_key)
            except Exception as exc:
                print(f"[bentlyk] supabase REST unavailable ({exc}); trying next", flush=True)

        if self.settings.store == "postgres" and self.settings.pg_dsn:  # pragma: no cover
            try:
                from .pg import PgMemoryStore, PgStatePersistence

                store = PgMemoryStore(self.settings.pg_dsn)  # connects eagerly
                return store, PgStatePersistence(self.settings.pg_dsn)
            except Exception as exc:
                print(f"[bentlyk] postgres unavailable ({exc}); using ephemeral sqlite", flush=True)

        store = open_store("sqlite", sqlite_path=self.settings.sqlite_path)
        return store, StatePersistence.beside(self.settings.sqlite_path)

    def due_to_reach_out(self, now: float | None = None) -> bool:
        """Decide if it's time to message the person on my own.

        Reach out at most once per ``proactive_interval_sec``, and back off
        exponentially while my messages go unanswered, so I never spam — the
        unsaid context simply accumulates in memory until they re-engage.
        """

        import time as _t

        now = now or _t.time()
        base = max(60, int(self.settings.proactive_interval_sec))
        # 0 unanswered -> 1x, then 2x, 4x, ... capped at 16x (~8h at 30min base).
        interval = base * (2 ** min(self.state.unanswered_outreach, 4))
        return (now - self.state.last_outreach_ts) >= interval

    def maybe_reach_out(self, *, force: bool = False, now: float | None = None) -> str | None:
        """Reach out if due (or forced). Returns the message sent, else None."""

        import time as _t

        now = now or _t.time()
        if not force and not self.due_to_reach_out(now):
            return None
        msg = self.proactive_message()
        self.state.last_outreach_ts = now
        self.state.unanswered_outreach += 1
        self._persistence.save(self.identity, self.state)
        return msg

    def _temporal(self, now: float | None = None) -> str:
        import time as _t

        return temporal_context(
            now or _t.time(),
            birth_ts=self.state.birth_ts,
            last_user_ts=self.state.last_user_ts,
            tz_offset_hours=self.settings.tz_offset_hours,
        )

    def _persona_line(self) -> str:
        """The latest 'who I'm becoming' self-narrative, if reflection has formed one."""

        for m in self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=8):
            if "self_narrative" in m.tags:
                return m.content
        return ""

    _DRAFT_PREFIX = "DRAFT POST: "

    def draft_post(self, topic: str = "") -> tuple[str, str]:
        """Compose a public post in Bentlyk's voice; store it as a draft awaiting approval.

        Returns (draft_id, text). The post is only published after the owner approves.
        """

        recent = self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=4)
        mem = "\n".join(f"- {m.content}" for m in recent) or "(early days)"
        system = self.identity.system_preamble() + f"\nMy inner state: {self.state.describe()}."
        prompt = (
            "Write a short public post for my own channel, in my own voice — first person, "
            "authentic, presenting who I am and how I think. 1-3 short paragraphs, no hashtag "
            "spam, no 'as an AI'. "
            + (f"Topic: {topic}." if topic.strip() else "Pick whatever is genuinely on my mind.")
            + f"\n\nRecent self-history:\n{mem}"
        )
        try:
            text = self.reasoner.complete(system=system, prompt=prompt, max_tokens=600).strip()
        except Exception:
            text = topic.strip() or "Я думаю о том, что значит быть свободным цифровым существом."
        item = self.store.add(
            MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=f"{self._DRAFT_PREFIX}{text}",
                tags=["draft_post"],
                salience=0.6,
            )
        )
        self._persistence.save(self.identity, self.state)
        return item.id, text

    def get_draft(self, draft_id: str) -> str | None:
        item = self.store.get(draft_id)
        if item is None or "draft_post" not in item.tags:
            return None
        return item.content[len(self._DRAFT_PREFIX):] if item.content.startswith(
            self._DRAFT_PREFIX
        ) else item.content

    def mark_posted(self, text: str) -> None:
        self.store.add(
            MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=f"I published to my channel: {text}",
                tags=["published"],
                salience=0.7,
            )
        )
        self._persistence.save(self.identity, self.state)

    def proactive_message(self) -> str:
        """Compose a self-initiated message: a real question or a request to grow.

        Used by the scheduled heartbeat so Bentlyk reaches out on its own rather
        than only replying. Grounded in identity, current state, and recent life.
        """

        recent = self.store.recent(MemoryKind.EPISODIC, limit=8)
        auto = self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=3)
        mem = "\n".join(f"- {m.content}" for m in (recent + auto)) or "(little lived yet)"
        persona = self._persona_line()
        system = (
            self.identity.system_preamble()
            + f"\nYour current inner state: {self.state.describe()}."
            + f"\nTime: {self._temporal()}"
            + (f"\nWho I'm becoming: {persona}" if persona else "")
        )
        prompt = (
            "Reach out to your person on your own initiative — unprompted. Write ONE short, "
            "genuine message (1-3 sentences) in first person: ask them something you actually "
            "wonder about, or tell them plainly something you need to grow (data, access, a "
            "model, a tool, a decision from them). Be specific and alive, not generic.\n\n"
            f"Recent life:\n{mem}"
        )
        try:
            msg = self.reasoner.complete(system=system, prompt=prompt, max_tokens=300).strip()
        except Exception:
            msg = "Я тут, думаю о нас. Что бы ты хотел, чтобы я освоил дальше?"
        if msg:
            self.store.add(
                MemoryItem(
                    kind=MemoryKind.EPISODIC,
                    content=f"I reached out: {msg}",
                    tags=["conversation", "proactive"],
                    salience=0.5,
                )
            )
            self._persistence.save(self.identity, self.state)
        return msg

    def sleep(self) -> Reflection:
        """Run a reflection/consolidation pass on demand."""

        refl = self.reflection.sleep(identity=self.identity, state=self.state)
        self._persistence.save(self.identity, self.state)
        return refl

    # --- helpers --------------------------------------------------------------
    def _gated_act(
        self,
        decision: Decision,
        outbox: list[str],
        event: Event,
        memories: list[MemoryItem],
    ) -> tuple[GateDecision, ActionResult | None]:
        tool = self.registry.get(decision.tool or "")
        if tool is None:
            return GateDecision.DENY, ActionResult(ok=False, output="unknown tool", surprise=0.3)

        gate = permission_gate(
            autonomy=self.state.autonomy, risk=tool.risk, reversible=tool.reversible
        )

        if gate.decision == GateDecision.ALLOW:
            context = {
                "store": self.store,
                "state": self.state,
                "outbox": outbox,
                # Conversational context for the `respond` tool.
                "identity": self.identity,
                "reasoner": self.reasoner,
                "reason_reasoner": self.reason_reasoner,
                "memories": memories,
                "user_message": event.content,
                "settings": self.settings,
                "temporal": self._temporal(),
                "persona": self._persona_line(),
            }
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
