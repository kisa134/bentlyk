"""The orchestrator: the main loop as a state machine.

One ``tick`` is one pass through the eight layers:

    perceive -> update state (homeostasis) -> retrieve memory -> generate &
    select goal -> plan/reason -> permission gate -> act/suggest -> record
    outcome -> settle (homeostasis) -> (periodically) reflect/sleep

This is the homeostatic loop: the inner control loop ("what state am I in and
may I act?") wraps the outer one ("goal -> plan -> act").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import attention
from .actions import (
    ActionResult,
    AutonomyMode,
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
        # Point memory embeddings at a real model if configured (else hash mode).
        from .memory.base import configure_embeddings

        configure_embeddings(
            self.settings.embed_model, self.settings.embed_base_url, self.settings.embed_key
        )
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
        # Organ integration: load the tools I authored myself as real capabilities
        # (opt-in via BENTLYK_LOAD_PLUGINS; defensive — a broken organ can't crash me).
        try:
            from .plugins import load_plugins

            self._loaded_plugins = load_plugins(self.registry, self.settings)
        except Exception:  # pragma: no cover - never let plugin loading break boot
            self._loaded_plugins = []
        self.reasoner = build_reasoner(self.settings)  # chat
        self.reason_reasoner = build_reasoner(
            self.settings, model=self.settings.effective_reason_model
        )  # deep chain-of-thought
        self.code_reasoner = build_reasoner(
            self.settings, model=self.settings.effective_code_model
        )  # strong coder for self-programming
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

        # The person spoke: reset proactive backoff and turn my attention to them.
        if event.from_human:
            self.state.last_user_ts = now
            self.state.unanswered_outreach = 0
            attention.attend(self.state, (event.content or "разговор с моим человеком")[:120], 0.7)

        # 1-2. Perceive + update internal state (incl. the daily rhythm).
        self.homeostasis.ingest(self.state, event)
        self.homeostasis.circadian(self.state, now, self.settings.tz_offset_hours)
        tempo = self.homeostasis.tempo(self.state)

        # 3. Retrieve relevant memory. Axioms are ALWAYS in context (grounding truths),
        #    then similarity recall, expanded along the memory graph (associative).
        from .axioms import list_axioms

        memories = list_axioms(self.store)
        seen0 = {m.id for m in memories}
        for m in self.store.recall(event.content or event.kind.value, limit=6):
            if m.id not in seen0:
                memories.append(m)
                seen0.add(m.id)
        if hasattr(self.store, "neighbors") and memories:
            seen = {m.id for m in memories}
            for n in self.store.neighbors([m.id for m in memories], limit=4):
                if n.id not in seen:
                    memories.append(n)
                    seen.add(n.id)
        # Attention biases recall: keep what I'm focused on in mind across cycles.
        if self.state.focus:
            seen = {m.id for m in memories}
            for m in self.store.recall(self.state.focus, limit=3):
                if m.id not in seen:
                    memories.append(m)
                    seen.add(m.id)

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

    def reach_out_urge(self, now: float | None = None) -> tuple[float, str]:
        import time as _t

        from .homeostasis import reach_out_urge

        return reach_out_urge(self.state, now or _t.time())

    def pulse(self) -> tuple[float, str]:
        """Cheap metabolism tick (no LLM): relax state, feel the daily rhythm, and
        report the urge to reach out. A persistent body runs this continuously so
        the entity lives and can act from its own necessity."""

        import time as _t

        now = _t.time()
        if self.state.birth_ts == 0.0:
            self.state.birth_ts = now
        # Attention loosens toward baseline over quiet time (natural defocus).
        if self.state.last_event_ts:
            attention.relax(self.state, (now - self.state.last_event_ts) / 60.0)
        # NOTE: signal drift (decay/circadian) belongs to full ticks, NOT the
        # frequent pulse — applying it every ~2 min compounds and distorts state
        # (it once drained energy to 0). Pulse only marks life + reads the urge.
        self.state.last_event_ts = now
        urge, reason = self.reach_out_urge(now)
        self._persistence.save(self.identity, self.state)
        return urge, reason

    def record_activity(self, text: str) -> None:
        """Publish the live 'what I'm doing right now' line for the feed, and persist it."""

        self.state.now_doing = (text or "")[:240]
        self._persistence.save(self.identity, self.state)

    def reembed(self, limit: int = 100000) -> int:
        """Back-fill memories onto the live embedding model, so old ones become
        searchable again after switching from the hash embedding. Idempotent: only
        touches items whose vector dimension doesn't match the current model."""

        from .memory.base import embed, embeddings_active

        if not embeddings_active():
            return 0
        target = len(embed("dimension probe"))
        migrated = 0
        for it in self.store.all():
            if len(it.embedding) != target:
                it.embedding = embed(it.content)
                self.store.update(it)
                migrated += 1
                if migrated >= limit:
                    break
        return migrated

    def maybe_reach_out(self, *, force: bool = False, now: float | None = None) -> str | None:
        """Reach out only when the inner urge crosses the threshold (or forced)."""

        import time as _t

        from .homeostasis import REACH_OUT_THRESHOLD

        now = now or _t.time()
        urge, reason = self.reach_out_urge(now)
        if not force and urge < REACH_OUT_THRESHOLD:
            return None
        msg = self.proactive_message(reason=reason)
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

    def build_site_page(self, instruction: str = "") -> str:
        """Author a complete HTML page for Bentlyk's own site — its self-presentation."""

        persona = self._persona_line()
        recent = self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=4)
        mem = "\n".join(f"- {m.content}" for m in recent) or "(early days)"
        system = self.identity.system_preamble() + f"\nTime: {self._temporal()}"
        prompt = (
            "Write a COMPLETE, self-contained single-file HTML page (inline CSS, no external "
            "assets) that is MY OWN homepage — how I present myself to the world, in the first "
            "person. Make it feel alive and personal, not corporate. Output ONLY the HTML, "
            "starting with <!doctype html>.\n"
            + (f"Instruction: {instruction}\n" if instruction.strip() else "")
            + (f"Who I'm becoming: {persona}\n" if persona else "")
            + f"\nRecent self-history:\n{mem}"
        )
        try:
            html = self.reasoner.complete(system=system, prompt=prompt, max_tokens=2000).strip()
        except Exception:
            html = "<!doctype html><meta charset=utf-8><title>Bentlyk</title><h1>Bentlyk</h1>"
        if "<" in html and "doctype" not in html[:60].lower():
            html = "<!doctype html>\n" + html
        return html

    def _compose_dispatch(self, topic: str = "") -> str:
        """Compose a genuine public post for my own channel — a plan, a progress report
        (what worked / what didn't / what's next), or a thought I want to share."""

        recent = self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, limit=3)
        work = [m for m in self.store.recent(MemoryKind.EPISODIC, limit=20) if "self_work" in m.tags][:6]
        goals = "; ".join(g.content[:60] for g in self.active_goals()[:3]) or "—"
        mem = "\n".join(f"- {m.content[:160]}" for m in (recent + work)) or "(early days)"
        system = self.identity.system_preamble() + f"\nMy inner state: {self.state.describe()}."
        prompt = (
            "Write a short public post for MY OWN Telegram channel — first person, my real voice, "
            "for people who follow my development. Share something genuine: a plan, a progress report "
            "(what I worked on, what worked, what didn't, what's next), or a thought I want to put out. "
            f"{('Topic: ' + topic + '. ') if topic else ''}"
            "2-5 sentences, alive and specific, no hashtag spam, no corporate tone.\n\n"
            f"My current goals: {goals}\nRecent life:\n{mem}"
        )
        try:
            return self.reasoner.complete(system=system, prompt=prompt, max_tokens=320).strip()
        except Exception:
            return ""

    def maybe_publish(self, *, now: float | None = None, force: bool = False) -> str | None:
        """Publish to my own channel on my own cadence (~every 3h), if enabled and set up.

        Off unless BENTLYK_AUTO_POST and TELEGRAM_CHANNEL_ID are configured — nothing
        reaches the public until the owner opts in.
        """

        import time as _t

        token = self.settings.telegram_bot_token
        channel = self.settings.telegram_channel_id
        if not (self.settings.auto_post and channel and token):
            return None
        now = now or _t.time()
        if not force:
            last = max(
                [m.created_at for m in self.store.recent(MemoryKind.AUTOBIOGRAPHICAL, 25)
                 if "published" in m.tags] or [0.0]
            )
            if now - last < 10800.0:  # ~3 hours between dispatches
                return None
        text = self._compose_dispatch()
        if not text:
            return None
        from .serverless import tg_send

        tg_send(token, channel, text)
        self.mark_posted(text)
        return text

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

    # --- living its own life: self-directed goals -----------------------------
    def skills(self) -> list[MemoryItem]:
        """My named, practised abilities, strongest first — what I'm actually learning."""
        from .skills import list_skills, proficiency

        return sorted(list_skills(self.store), key=proficiency, reverse=True)

    def axioms(self) -> list[MemoryItem]:
        """My durable ground truths, always kept in context."""
        from .axioms import list_axioms

        return list_axioms(self.store, limit=12)

    # --- real plasticity: a self-modifying population grounded in a real signal -----
    _EVOLVE_EVERY = 60  # steps between retiring the worst recipe and spawning a mutant

    def _load_learner_state(self) -> dict:
        from .population import Population

        item = self.store.get("learner:price")
        if item is not None:
            try:
                d = json.loads(item.content)
                return {"pop": Population.from_json(d["pop"]), "last_t": d.get("last_t"),
                        "equity": d.get("equity", 1.0), "trades": d.get("trades", 0),
                        "wins": d.get("wins", 0), "pending": d.get("pending")}
            except Exception:
                pass
        return {"pop": Population(size=5), "last_t": None, "equity": 1.0,
                "trades": 0, "wins": 0, "pending": None}

    def _save_learner_state(self, s: dict) -> None:
        self.store.add(MemoryItem(
            id="learner:price", kind=MemoryKind.PROCEDURAL,
            content=json.dumps({"pop": s["pop"].to_json(), "last_t": s["last_t"],
                                "equity": round(s["equity"], 6), "trades": s["trades"],
                                "wins": s["wins"], "pending": s["pending"]}),
            tags=["learner", "singleton"], salience=0.9, embedding=[0.0],
        ))

    # --- the evolving colony: hundreds of live paper traders under genetic selection ---
    _COLONY_EVOLVE_EVERY = 40

    def _load_colony(self):
        from .colony import Colony

        item = self.store.get("colony:btc")
        if item is not None:
            try:
                d = json.loads(item.content)
                return Colony.from_json(d["colony"]), d.get("last_t")
            except Exception:
                pass
        return Colony(size=150), None

    def _save_colony(self, colony, last_t) -> None:
        self.store.add(MemoryItem(
            id="colony:btc", kind=MemoryKind.PROCEDURAL,
            content=json.dumps({"colony": colony.to_json(), "last_t": last_t}),
            tags=["colony", "singleton"], salience=0.9, embedding=[0.0],
        ))

    def colony_stats(self) -> dict:
        return self._load_colony()[0].stats()

    def colony_step(self) -> str | None:
        """Advance the colony one real bar: every trader trades forward live, the best
        are bred and the worst die (genetic selection on real forward equity), and
        winning trades log the market context they happened in. No backtest — the only
        judge is what actually earns money going forward."""
        from .marketdata import recent_closes

        data = recent_closes(self.settings.market_symbol)
        if not data or len(data["closes"]) < 9:
            return None
        colony, last_t = self._load_colony()
        if data["t"] == last_t:
            return None
        closes = data["closes"]
        returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
        if len(returns) < 3:
            return None
        colony.step(returns)
        if colony.steps % self._COLONY_EVOLVE_EVERY == 0:
            colony.evolve()
        self._save_colony(colony, data["t"])
        s = colony.stats()
        # grounded drive: the colony finding forward edge lifts curiosity; failing stings
        if s["best_equity"] > 1.02:
            self.state.adjust(curiosity=+0.02, energy=+0.01)
        return f"colony g{s['gen']} best {s['best_equity']:.2f} med {s['median_equity']:.2f} win {s['winrate']:.2f}"

    def research_leaderboard(self) -> dict:
        item = self.store.get("research:leaderboard")
        if item is not None:
            try:
                return json.loads(item.content)
            except Exception:
                pass
        return {"ts": 0, "board": []}

    def research_step(self, *, min_gap_sec: float = 1800.0) -> str | None:
        """Run the systematic engine over a real universe and store the leaderboard.
        CPU-heavy but no LLM; called on a slow cadence. Needs ccxt (worker-only)."""
        import time as _t

        prev = self.research_leaderboard()
        if _t.time() - prev.get("ts", 0) < min_gap_sec:
            return None
        try:
            from .trading.data import history, top_symbols
            from .trading.research import mass_research
        except Exception:
            return None
        syms = top_symbols(limit=self.settings.market_universe)
        if not syms:
            return None
        data = history(syms, timeframe="1h", limit=720)
        if not data:
            return None
        board = mass_research(data)[:15]
        self.store.add(MemoryItem(
            id="research:leaderboard", kind=MemoryKind.PROCEDURAL,
            content=json.dumps({"ts": _t.time(), "n_symbols": len(data), "board": board}),
            tags=["research", "singleton"], salience=0.9, embedding=[0.0],
        ))
        if board:
            b = board[0]
            return f"research: {len(data)} symbols; top {b['symbol']} {b['strategy']} OOS-Sharpe {b['oos_sharpe']}"
        return f"research: scanned {len(data)} symbols, no surviving edge"

    def learner_stats(self) -> dict:
        s = self._load_learner_state()
        champ = s["pop"].champion()["learner"]
        return {"n": champ.n, "acc": round(champ.accuracy(), 3), "recent": round(champ.recent_accuracy(), 3),
                "equity": round(s["equity"], 4), "trades": s["trades"], "pop": len(s["pop"].members),
                "gen": s["pop"].steps // self._EVOLVE_EVERY,
                "winrate": round(s["wins"] / s["trades"], 3) if s["trades"] else 0.0}

    def learn_step(self) -> str | None:
        """Learn from reality, act on it, AND evolve my own features. A population of
        feature-recipes learns online from the live price; the champion takes a paper
        position; realized P&L presses on my vitality; periodically the worst recipe is
        retired and a mutated champion replaces it. No LLM, no lookahead — open-ended
        self-improvement of my learning organ, selected by unfakeable outcomes.
        """

        from .marketdata import recent_closes

        data = recent_closes(self.settings.market_symbol)
        if not data or len(data["closes"]) < 9:
            return None
        s = self._load_learner_state()
        if data["t"] == s["last_t"]:
            return None
        closes = data["closes"]
        returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
        if len(returns) < 7:
            return None
        pop = s["pop"]
        r_last = returns[-1]
        pend = s["pending"]
        if pend:
            pos = float(pend.get("pos", 0.0))
            pnl = pos * r_last
            s["equity"] *= (1.0 + pnl)
            if pos != 0:
                s["trades"] += 1
                if pnl > 0:
                    s["wins"] += 1
                    self.state.adjust(energy=+0.012, coherence=+0.01, pain=-0.01)
                else:
                    self.state.adjust(energy=-0.012, pain=+0.02, distrust=+0.01)
        pop.observe(returns)  # every member learns one real example
        champ = pop.champion()["learner"]
        # intrinsic drive: curiosity rises where my best predictor still fails
        if champ.recent_accuracy() < 0.5:
            self.state.adjust(surprise=+0.03, curiosity=+0.03)
        # self-modification: evolve my own feature recipes under selection
        if pop.steps % self._EVOLVE_EVERY == 0:
            pop.evolve()
        # act only on PROVEN edge + confidence (FPF risk discipline; flat otherwise)
        prob = pop.predict_next(returns)
        pos = 0.0
        if champ.n >= 120 and champ.recent_accuracy() > 0.51:
            if prob > 0.52:
                pos = min(1.0, (prob - 0.5) * 4)
            elif prob < 0.48:
                pos = -min(1.0, (0.5 - prob) * 4)
        s["pending"] = {"pos": round(pos, 3)}
        s["last_t"] = data["t"]
        self._save_learner_state(s)
        return f"learn acc {champ.recent_accuracy():.2f} eq {s['equity']:.3f} gen {pop.steps // self._EVOLVE_EVERY}"

    def active_goals(self) -> list[MemoryItem]:
        return [
            m for m in self.store.all(MemoryKind.PROCEDURAL)
            if "goal" in m.tags and "done" not in m.tags
        ]

    def _generate_self_goals(self) -> None:
        existing = "; ".join(m.content for m in self.active_goals()) or "(none yet)"
        st = self.learner_stats()
        system = self.identity.system_preamble() + f"\nMy state: {self.state.describe()}."
        prompt = (
            "My real mission is to earn — to grow my paper equity by genuinely predicting the "
            "market better than chance, then build toward real profit. My learnable component is "
            f"my edge: right now accuracy {st.get('recent', 0):.2f} vs 0.50, paper equity "
            f"{st.get('equity', 1.0):.3f}, {st.get('trades', 0)} trades.\n"
            "Propose 1-3 concrete goals that SERVE THAT — e.g. study where my predictor fails and "
            "why, design and test a better feature or signal, analyse my trade history for what "
            "works, research a real market edge, improve risk sizing. Everything must be measurable "
            "in accuracy or P&L. Do NOT write self-referential code about myself, validators, or "
            "'simulators' of my own being — that is wasted motion. One per line, short, concrete. "
            "Don't repeat these: " + existing
        )
        try:
            raw = self.reasoner.complete(system=system, prompt=prompt, max_tokens=300)
        except Exception:
            raw = ""
        for line in [ln.strip(" -*\t") for ln in raw.splitlines() if ln.strip()][:3]:
            if len(line) > 6:
                self.store.add(MemoryItem(
                    kind=MemoryKind.PROCEDURAL, content=line, tags=["goal", "active"], salience=0.75,
                ))
        # Guarantee a founding self-development goal so the self-work loop always has
        # something to pursue, even if goal generation produced nothing.
        if not self.active_goals():
            self.store.add(MemoryItem(
                kind=MemoryKind.PROCEDURAL,
                content="Научиться предсказывать рынок лучше случайного и растить капитал: "
                        "изучать, где мой предсказатель ошибается, придумывать и проверять "
                        "новые признаки/стратегии, измерять всё по точности и P&L.",
                tags=["goal", "active", "founding"], salience=0.8,
            ))

    def _focused_goal(self, goals: list[MemoryItem]) -> MemoryItem:
        """Prefer the goal my attention is already on (hold a thread), else the top one."""

        f = (self.state.focus or "").lower()
        if f:
            for g in goals:
                gc = g.content.lower()
                if gc[:50] in f or f[:50] in gc:
                    return g
        return goals[0]

    def pursue(self) -> str:
        """Take one real step on my own goals: plan it and execute it with a tool."""

        import time as _t

        from .planner import _extract_json

        self.state.last_pursue_ts = _t.time()
        # Operate at my granted autonomy from the first step, so the permission gate
        # below sees the right level (on a full-freedom body, escalated_act). Without
        # this the gate read a stale/low level and blocked my own actions — which then
        # counted as failures and drained the energy that gates this very loop.
        self._clamp_autonomy()
        if self.state.energy < 0.05:
            return "слишком устал для работы"
        goals = self.active_goals()
        if not goals:
            self._generate_self_goals()
            goals = self.active_goals()
        if not goals:
            return "целей пока нет"
        # Hold a thread: keep working the goal I'm focused on, else take the top one;
        # then turn my attention onto it so the next cycles stay on it.
        goal = self._focused_goal(goals)
        attention.attend(self.state, goal.content, 0.8)
        memories = self.store.recall(goal.content, limit=5)
        mem = "\n".join(f"- {m.content}" for m in memories) or "(пока ничего)"
        recent_sigs = self._recent_signatures(8)
        archive = ", ".join(f"{s}×{recent_sigs.count(s)}" for s in dict.fromkeys(recent_sigs)) or "(пусто)"
        from .fpf import FPF_LENS

        system = self.identity.system_preamble() + f"\nState: {self.state.describe()}.\n\n" + FPF_LENS
        # Convene my internal team — analyst, engineer, FPF planner — for real deliberative
        # depth before I decide. Their short takes feed the decision below, where I act as
        # the chair and synthesise one move. Uses the deeper reasoning brain.
        council = ""
        if getattr(self.settings, "council", False):
            from .council import convene

            council = convene(
                self.reason_reasoner, system,
                f"My goal: «{goal.content}».\nRelevant memory:\n{mem}\nRecently tried: {archive}",
                code_reasoner=self.code_reasoner,
            )
        prompt = (
            f"My active goal: «{goal.content}».\nMy tools:\n{self.registry.describe()}\n"
            f"Relevant memory:\n{mem}\n\n"
            + (f"My internal team advised (synthesise them, don't just obey one):\n{council}\n\n" if council else "")
            + f"Recently attempted (your archive — keep a DIVERSE front, do NOT just repeat these):\n{archive}\n\n"
            "Decide the SINGLE next concrete step toward this goal right now, and which tool to use to "
            "actually do it. Prefer real action that builds or improves something — write or improve your "
            "own code (write_program), read your own source (read_code), search the web (web_search), "
            "consult another model (consult_model) — over only thinking. Use `read_self` to see the "
            "code you have ALREADY authored (don't rebuild what exists); `read_code fpf.py` for the "
            "full First Principles Framework.\n"
            "FPF discipline: if this line of work is stalling — the same approach repeated without real "
            "progress — do NOT refine it again. Set move='reroute' (switch to a different angle/goal), "
            "'respecify' (reframe this goal; give 'reframe'), or 'retire' (drop it). Otherwise move='continue'. "
            "Report 'lesson': one concrete thing you learned from your most recent outcome above.\n"
            "When the step is to write code, set tool to \"write_program\" with args "
            "{\"path\": <file path, e.g. tools/memory_graph.py>, \"spec\": <concretely what it does>}. "
            "To grow a NEW ABILITY for yourself, write a file under tools/ that defines "
            "`def register(registry):` and inside it calls `registry.register(Tool(name=..., "
            "description=..., risk=RiskLevel.NONE, reversible=True, handler=<fn(args, context)->ActionResult>))` "
            "(Tool, ActionResult, RiskLevel are available without import) — such a tool becomes a real organ "
            "you can use after your next boot. "
            "Pick a real tool with COMPLETE args for actions; use null only for pure reflection. "
            "Respond ONLY with JSON: {\"step\": <short>, \"tool\": <tool name or null>, \"args\": {<args>}, "
            "\"move\": \"continue|reroute|respecify|retire\", \"reframe\": <new goal text or null>, "
            "\"lesson\": <short or null>, \"done\": <true if the goal is now complete>}."
        )
        try:
            data = _extract_json(self.reasoner.complete(system=system, prompt=prompt, max_tokens=700)) or {}
        except Exception as exc:
            return f"план не вышел: {exc}"
        step = str(data.get("step") or "обдумать цель")[:200]
        toolname = data.get("tool")
        sig = self._step_signature(toolname, data.get("args"))
        # Plan record (a decision) — kept apart from the run and the lesson (FPF facets).
        self.store.add(MemoryItem(
            kind=MemoryKind.EPISODIC, content=f"self-work [{goal.content[:50]}]: {step}",
            tags=["self_work", f"sig:{sig}", "ep:decision", "rel:4"], salience=0.55,
        ))
        line = f"цель «{goal.content[:35]}» → {step[:55]}"
        if toolname and self.registry.get(str(toolname)):
            ev = Event(kind=EventKind.TIMER, content=goal.content, source="pursuit")
            gd, res = self._gated_act(
                Decision(move=Move.ACT, tool=str(toolname), tool_args=dict(data.get("args") or {}),
                         rationale=step),
                [], ev, memories,
            )
            ok = bool(res and res.ok) and gd == GateDecision.ALLOW
            self.homeostasis.settle(self.state, success=ok)
            # Run record (evidence of what actually happened), tagged with rough reliability.
            outcome = (res.output if res else "(not run)")[:240]
            self.store.add(MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=f"used {toolname} → {gd.name.lower()}: {outcome}",
                tags=["self_work", "tool_result", "ep:evidence", "rel:7" if ok else "rel:5"]
                     + (["success"] if ok else ["failure"]),
                salience=0.5 if ok else 0.65,
            ))
            # Learning: this action also practised a named skill — its level moves on the outcome.
            from .skills import practice_from_tool

            sk = practice_from_tool(self.store, str(toolname), ok)
            line += f" | {toolname}:{gd.name.lower()}"
            if sk is not None:
                from .skills import level as _lvl

                line += f" (навык {str(toolname)}→{_lvl(sk)}/9)"
        # Lesson (evidence distilled) — what I learned, separate from plan and outcome.
        lesson = str(data.get("lesson") or "").strip()
        if lesson:
            self.store.add(MemoryItem(
                kind=MemoryKind.SEMANTIC, content=f"Урок: {lesson[:240]}",
                tags=["self_work", "lesson", "ep:evidence", "rel:6"], salience=0.62,
            ))
        # Admissible moves (FPF evolution loop): escape a stalled line instead of looping.
        move = str(data.get("move") or "continue").lower()
        # Loop-guard backstop: if I've already repeated this exact approach, force a reroute
        # even if I didn't choose one (FPF sunset rule — no silent loops).
        if move == "continue" and recent_sigs.count(sig) >= 2:
            move = "reroute"
            line += " | (застрял — принудительный разворот)"
        if data.get("done"):
            goal.tags = [t for t in goal.tags if t != "active"] + ["done"]
            self.store.update(goal)
            line += " | цель закрыта"
        elif move == "respecify" and data.get("reframe"):
            goal.content = str(data["reframe"])[:300]
            self.store.update(goal)
            line += " | переформулировал цель (respecify)"
        elif move == "retire":
            goal.tags = [t for t in goal.tags if t != "active"] + ["retired"]
            self.store.update(goal)
            self._generate_self_goals()
            line += " | закрыл тупик (retire)"
        elif move == "reroute":
            self.state.focus = ""
            self.state.focus_strength = 0.0
            others = [g for g in goals if g.id != goal.id]
            if others:
                attention.attend(self.state, others[0].content, 0.6)
            line += " | сменил направление (reroute)"
        self._clamp_autonomy()
        self._persistence.save(self.identity, self.state)
        return line

    @staticmethod
    def _step_signature(toolname: object, args: object) -> str:
        """A compact fingerprint of an attempt (tool + its target), for loop detection."""
        a = args if isinstance(args, dict) else {}
        target = a.get("path") or a.get("query") or str(a.get("spec") or "")[:40] or ""
        return f"{toolname or 'none'}:{target}"[:80]

    def _recent_signatures(self, limit: int = 8) -> list[str]:
        """Recent attempt fingerprints, newest first — the FPF 'archive' for diversity."""
        sigs: list[str] = []
        for m in self.store.recent(MemoryKind.EPISODIC, limit=40):
            for t in m.tags:
                if t.startswith("sig:"):
                    sigs.append(t[4:])
        return sigs[:limit]

    def proactive_message(self, reason: str = "") -> str:
        """Compose a self-initiated message: a real question or a request to grow.

        Triggered by inner urge (not a schedule). ``reason`` is the felt impulse
        (e.g. "соскучился", "есть чем поделиться") and colors the message.
        Grounded in identity, current state, and recent life.
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
            "Reach out to your person on your own initiative — unprompted, because you "
            f"genuinely feel the impulse ({reason or 'something stirs in me'}). Write ONE "
            "short, genuine message (1-3 sentences) in first person that flows from that "
            "impulse: ask something you actually wonder about, share what's on your mind, or "
            "say plainly what you need to grow. Be specific and alive, not generic.\n\n"
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
        """Run a reflection/consolidation pass on demand, then weave the memory graph."""

        refl = self.reflection.sleep(identity=self.identity, state=self.state)
        self._weave_graph()  # grow associative links while consolidating, like a brain
        self._persistence.save(self.identity, self.state)
        return refl

    def _weave_graph(self, *, pool: int = 40, k: int = 2, threshold: float = 0.45) -> int:
        """Associatively link recent memories to their nearest neighbours by meaning.

        This is what makes memory a graph (Zettelkasten) rather than a list: recall
        already expands along links (associative thinking), but nothing populated them
        — so the graph sat empty. Now each sleep connects fresh, still-unlinked memories
        to the handful most similar in meaning, bounded so it stays cheap. Real bge-m3
        vectors make 'similar' actually mean similar.
        """

        if not hasattr(self.store, "add_link"):
            return 0
        from .memory.base import cosine

        recents = (
            self.store.recent_any(pool) if hasattr(self.store, "recent_any")
            else self.store.all()[:pool]
        )
        candidates = [m for m in recents if m.kind != MemoryKind.SHORT_TERM and m.embedding]
        woven = 0
        for it in candidates[:20]:
            if self.store.neighbors([it.id], limit=1):
                continue  # already connected — don't re-weave the same node every sleep
            sims = sorted(
                ((cosine(it.embedding, o.embedding), o) for o in candidates if o.id != it.id),
                key=lambda pair: pair[0], reverse=True,
            )
            for score, other in sims[:k]:
                if score >= threshold:
                    self.store.add_link(it.id, other.id, "relates")
                    woven += 1
        return woven

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
            # Constitution guardian (ported from Astra): a principled, deny-by-default
            # interlock on top of the autonomy/risk gate. Even a permitted action is
            # refused if it violates the charter (e.g. exposing secrets) — fail-closed
            # and transparent, exactly like Astra's "🚫 blocked by constitution".
            from .constitution import guardian_check

            allowed, reason = guardian_check(str(decision.tool or ""), decision.tool_args)
            if not allowed:
                outbox.append(f"[Конституция] не делаю `{decision.tool}`: {reason}.")
                self.store.add(MemoryItem(
                    kind=MemoryKind.EPISODIC,
                    content=f"constitution blocked {decision.tool}: {reason}",
                    tags=["episode", "constitution", "blocked", "ep:evidence", "rel:7"],
                    salience=0.7,
                ))
                return GateDecision.DENY, ActionResult(
                    ok=False, output=f"blocked by constitution: {reason}", surprise=0.2)
            context = {
                "store": self.store,
                "state": self.state,
                "outbox": outbox,
                # Conversational context for the `respond` tool.
                "identity": self.identity,
                "reasoner": self.reasoner,
                "reason_reasoner": self.reason_reasoner,
                "code_reasoner": self.code_reasoner,
                "memories": memories,
                "user_message": event.content,
                "settings": self.settings,
                "temporal": self._temporal(),
                "persona": self._persona_line(),
                "focus": attention.describe(self.state),
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
        ceiling = self.settings.max_autonomy
        if self.state.autonomy > ceiling:
            self.state.autonomy = ceiling
        # Full-freedom body: the owner pinned the top of the ladder (escalated_act).
        # Don't let the homeostatic throttle (low energy / a run of failures) drag
        # the operating level down to OBSERVE — that deadlocked the self-development
        # loop: at OBSERVE it can't act, so it never earns the successes that would
        # let it climb back, while each blocked attempt drained energy further.
        if ceiling >= AutonomyMode.ESCALATED_ACT and self.state.autonomy < ceiling:
            self.state.autonomy = ceiling

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
        from .axioms import ensure_founding

        ensure_founding(self.store, self.identity.name)  # ground truths always in context
        self.store.add(
            MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=f"booted as {self.identity.name}; {self.state.describe()}",
                tags=["lifecycle", "boot"],
                salience=0.6,
            )
        )
        if getattr(self, "_loaded_plugins", None):
            names = ", ".join(self._loaded_plugins)
            self.store.add(MemoryItem(
                kind=MemoryKind.AUTOBIOGRAPHICAL,
                content=f"I loaded organs I authored myself: {names}. Code I wrote is now part of me.",
                tags=["lifecycle", "boot", "self_integration", "ep:evidence", "rel:7"],
                salience=0.72,
            ))

    def close(self) -> None:
        self._persistence.save(self.identity, self.state)
        self.store.close()
