from bentlyk.actions.permissions import AutonomyMode
from bentlyk.events import message, timer
from bentlyk.homeostasis import HomeostasisEngine
from bentlyk.self_model import DynamicState


def test_pain_collapses_autonomy_to_observe():
    eng = HomeostasisEngine()
    state = DynamicState(autonomy=AutonomyMode.SAFE_ACT, pain=0.9)
    assert eng.recommend_autonomy(state) == AutonomyMode.OBSERVE


def test_distrust_collapses_autonomy():
    eng = HomeostasisEngine()
    state = DynamicState(autonomy=AutonomyMode.ESCALATED_ACT, distrust=0.8)
    assert eng.recommend_autonomy(state) == AutonomyMode.OBSERVE


def test_autonomy_climbs_at_most_one_notch():
    eng = HomeostasisEngine()
    state = DynamicState(
        autonomy=AutonomyMode.OBSERVE,
        coherence=0.95,
        distrust=0.02,
        pain=0.0,
        energy=1.0,
        recent_successes=10,
    )
    target = eng.recommend_autonomy(state)
    assert target == AutonomyMode.SUGGEST  # only one notch up from OBSERVE


def test_repeated_success_settles_upward_over_time():
    eng = HomeostasisEngine()
    state = DynamicState(autonomy=AutonomyMode.OBSERVE, coherence=0.9, distrust=0.05, energy=0.9)
    for _ in range(6):
        eng.settle(state, success=True)
    assert state.autonomy >= AutonomyMode.SAFE_ACT


def test_failure_increases_pain_and_distrust():
    eng = HomeostasisEngine()
    state = DynamicState()
    before_pain, before_distrust = state.pain, state.distrust
    eng.settle(state, success=False)
    assert state.pain > before_pain
    assert state.distrust > before_distrust
    assert state.recent_failures == 1


def test_message_event_raises_attachment():
    eng = HomeostasisEngine()
    state = DynamicState(attachment=0.5)
    eng.ingest(state, message("hi"))
    assert state.attachment > 0.5


def test_low_energy_signals_rest():
    eng = HomeostasisEngine()
    state = DynamicState(energy=0.1)
    tempo = eng.tempo(state)
    assert tempo.should_rest


def test_timer_ingest_does_not_crash_and_drifts():
    eng = HomeostasisEngine()
    state = DynamicState(energy=0.5)
    eng.ingest(state, timer())
    assert 0.0 <= state.energy <= 1.0
