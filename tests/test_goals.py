from bentlyk.events import message, timer
from bentlyk.goals import GoalCandidate, GoalEngine, GoalSource
from bentlyk.memory import MemoryItem, MemoryKind, SqliteMemoryStore
from bentlyk.self_model import DynamicState


def test_score_formula():
    c = GoalCandidate(
        description="x",
        source=GoalSource.EXTERNAL,
        value_alignment=0.8,
        urgency=0.7,
        attachment=0.5,
        curiosity=0.2,
        risk=0.1,
        uncertainty=0.2,
    )
    assert abs(c.score - (0.8 + 0.7 + 0.5 + 0.2 - 0.1 - 0.2)) < 1e-9


def test_message_event_generates_responsive_goal_and_wins():
    eng = GoalEngine(SqliteMemoryStore(":memory:"))
    state = DynamicState()
    candidates = eng.generate(event=message("can you help me?"), state=state)
    selected = eng.select(candidates)
    assert selected is not None
    assert "respond" in selected.description


def test_internal_imbalance_generates_recovery_goal():
    eng = GoalEngine(SqliteMemoryStore(":memory:"))
    state = DynamicState(pain=0.8, coherence=0.3)
    candidates = eng.generate(event=None, state=state)
    descs = " ".join(c.description for c in candidates)
    assert "recover" in descs or "confusion" in descs


def test_open_promise_becomes_internal_goal():
    store = SqliteMemoryStore(":memory:")
    store.add(MemoryItem(kind=MemoryKind.EPISODIC, content="I will send the report", tags=["promise"]))
    eng = GoalEngine(store)
    candidates = eng.generate(event=timer(), state=DynamicState())
    assert any("promise" in c.description for c in candidates)


def test_always_has_an_aspirational_floor():
    eng = GoalEngine(SqliteMemoryStore(":memory:"))
    candidates = eng.generate(event=None, state=DynamicState(curiosity=0.0, energy=0.0))
    assert any(c.source == GoalSource.ASPIRATIONAL for c in candidates)
