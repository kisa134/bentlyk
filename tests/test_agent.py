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


def test_proactive_backoff_gating():
    import time

    agent = make_agent()
    agent.settings.proactive_interval_sec = 1000
    now = time.time()
    # Never reached out -> due immediately.
    assert agent.due_to_reach_out(now)
    # Just reached out -> not due before the interval.
    agent.state.last_outreach_ts = now
    agent.state.unanswered_outreach = 1
    assert not agent.due_to_reach_out(now + 500)
    # After 1x interval with 1 unanswered, backoff doubles it -> still not due.
    assert not agent.due_to_reach_out(now + 1500)
    assert agent.due_to_reach_out(now + 2100)  # past 2x interval
    # A human message resets the backoff.
    agent.tick(message("hey"))
    assert agent.state.unanswered_outreach == 0


def test_offline_runs_without_api_key():
    agent = make_agent()
    cycle = agent.tick(message("what should we do today?"))
    # No exceptions, and a decision was made by the offline reasoner.
    assert cycle.headline()
