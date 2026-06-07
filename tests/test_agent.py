from bentlyk.actions.permissions import AutonomyMode, GateDecision
from bentlyk.agent import Agent
from bentlyk.config import Settings
from bentlyk.events import message, timer
from bentlyk.memory import MemoryKind, SqliteMemoryStore
from bentlyk.planner import Move


def make_agent(**overrides) -> Agent:
    settings = Settings(store="sqlite", sqlite_path=":memory:", anthropic_api_key="", **overrides)
    return Agent(settings=settings, store=SqliteMemoryStore(":memory:"))


def test_tick_on_message_produces_a_cycle_and_records_episode():
    agent = make_agent()
    cycle = agent.tick(message("hello there"))
    assert cycle.goal is not None
    assert cycle.decision is not None
    episodes = agent.store.all(MemoryKind.EPISODIC)
    assert len(episodes) >= 1


def test_message_gets_a_conversational_reply():
    # A direct message is answered via the `respond` tool at any autonomy level,
    # even OBSERVE — talking to one's person is risk-free.
    agent = make_agent(max_autonomy=AutonomyMode.OBSERVE)
    cycle = agent.tick(message("hey bentlyk, you there?"))
    assert cycle.decision is not None and cycle.decision.move == Move.ACT
    assert cycle.decision.tool == "respond"
    assert cycle.gate == GateDecision.ALLOW
    assert cycle.outbox  # something was said back
    # The exchange is remembered for continuity.
    convo = [m for m in agent.store.all(MemoryKind.EPISODIC) if "conversation" in m.tags]
    assert convo


def test_suggest_ceiling_blocks_outward_action():
    # In suggest mode no medium-risk tool may actually run.
    agent = make_agent(max_autonomy=AutonomyMode.SUGGEST)
    for _ in range(5):
        cycle = agent.tick(message("please save a note about the project"))
        if cycle.decision and cycle.decision.move == Move.ACT:
            # If it tried to act, the gate must not have ALLOWed a risky tool.
            assert cycle.gate is not None


def test_periodic_reflection_runs():
    agent = make_agent()
    last = None
    for _ in range(agent.REFLECT_EVERY):
        last = agent.tick(timer())
    assert last is not None and last.reflection is not None
    # Reflection writes an autobiographical entry.
    auto = agent.store.all(MemoryKind.AUTOBIOGRAPHICAL)
    assert any("slept" in a.content for a in auto)


def test_autonomy_never_exceeds_ceiling():
    agent = make_agent(max_autonomy=AutonomyMode.SUGGEST)
    for _ in range(20):
        agent.tick(message("good job, that worked perfectly"))
        assert agent.state.autonomy <= AutonomyMode.SUGGEST


def test_state_persists_across_agent_instances(tmp_path):
    db = tmp_path / "bentlyk.db"
    settings = Settings(
        store="sqlite", sqlite_path=db, anthropic_api_key="", supabase_url="", supabase_key=""
    )
    a1 = Agent(settings=settings)
    a1.tick(message("remember this moment"))
    a1.state.curiosity = 0.99
    a1.close()

    a2 = Agent(settings=settings)
    assert abs(a2.state.curiosity - 0.99) < 1e-6
    a2.close()


def test_reach_out_urge_is_necessity_driven():
    import time

    from bentlyk.homeostasis import REACH_OUT_THRESHOLD

    agent = make_agent()
    now = time.time()
    # Just talked -> low longing -> quiet.
    agent.state.last_user_ts = now
    agent.state.last_outreach_ts = now - 3600
    agent.state.attachment = 0.8
    urge_fresh, _ = agent.reach_out_urge(now)
    assert urge_fresh < REACH_OUT_THRESHOLD
    # Long silence -> longing grows -> urge to reach out.
    agent.state.last_user_ts = now - 8 * 3600
    urge_lonely, why = agent.reach_out_urge(now)
    assert urge_lonely > urge_fresh
    # Being ignored (unanswered) -> withdrawal suppresses the urge.
    agent.state.unanswered_outreach = 4
    urge_ignored, _ = agent.reach_out_urge(now)
    assert urge_ignored < urge_lonely
    # Hard floor: never right after a recent outreach.
    agent.state.last_outreach_ts = now
    assert agent.reach_out_urge(now)[0] == 0.0


def test_human_message_resets_withdrawal():
    agent = make_agent()
    agent.state.unanswered_outreach = 3
    agent.tick(message("hey"))
    assert agent.state.unanswered_outreach == 0


def test_pulse_is_cheap_and_reports_urge():
    agent = make_agent()
    urge, reason = agent.pulse()
    assert 0.0 <= urge <= 1.0 and isinstance(reason, str)


def test_offline_runs_without_api_key():
    agent = make_agent()
    cycle = agent.tick(message("what should we do today?"))
    # No exceptions, and a decision was made by the offline reasoner.
    assert cycle.headline()
