from bentlyk.actions import default_registry
from bentlyk.goals import GoalCandidate, GoalSource
from bentlyk.homeostasis import HomeostasisEngine
from bentlyk.llm import MockReasoner
from bentlyk.planner import Move, Planner, _extract_json
from bentlyk.self_model import DynamicState, IdentityCore


def make_planner():
    return Planner(MockReasoner(), default_registry())


def test_rest_overrides_to_think():
    eng = HomeostasisEngine()
    state = DynamicState(energy=0.1)
    tempo = eng.tempo(state)
    decision = make_planner().decide(
        identity=IdentityCore(),
        state=state,
        tempo=tempo,
        goal=GoalCandidate(description="do something", source=GoalSource.INTERNAL),
        memories=[],
    )
    assert decision.move == Move.THINK


def test_high_distrust_and_uncertain_goal_asks():
    eng = HomeostasisEngine()
    state = DynamicState(distrust=0.8, energy=0.9)
    tempo = eng.tempo(state)
    decision = make_planner().decide(
        identity=IdentityCore(),
        state=state,
        tempo=tempo,
        goal=GoalCandidate(
            description="ambiguous task", source=GoalSource.EXTERNAL, uncertainty=0.7
        ),
        memories=[],
    )
    assert decision.move == Move.ASK
    assert decision.message


def test_unknown_tool_downgrades_to_think():
    planner = make_planner()
    decision = planner._parse(
        '{"decision": "act", "tool": "launch_missiles", "tool_args": {}}',
        GoalCandidate(description="x", source=GoalSource.INTERNAL),
        tempo=HomeostasisEngine().tempo(DynamicState()),
    )
    assert decision.move == Move.THINK


def test_extract_json_tolerates_prose():
    data = _extract_json('sure! here you go: {"decision": "think"} hope that helps')
    assert data == {"decision": "think"}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("no json here") is None
