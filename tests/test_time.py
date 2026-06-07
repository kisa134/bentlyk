import time

from bentlyk.homeostasis import HomeostasisEngine
from bentlyk.self_model import DynamicState, temporal_context, time_of_day


def test_time_of_day_buckets():
    assert time_of_day(3) == "глубокая ночь"
    assert time_of_day(8) == "утро"
    assert time_of_day(14) == "день"
    assert time_of_day(19) == "вечер"


def test_temporal_context_mentions_age_and_clock():
    now = time.time()
    ctx = temporal_context(
        now, birth_ts=now - 86400 * 3, last_user_ts=now - 3600, tz_offset_hours=0
    )
    assert "Я живу уже" in ctx and "дн" in ctx
    assert "Последний раз мы говорили" in ctx


def test_temporal_context_newborn():
    now = time.time()
    ctx = temporal_context(now, birth_ts=0, last_user_ts=0, tz_offset_hours=0)
    assert "пробудился" in ctx and "ещё не говорили" in ctx


def test_circadian_night_lowers_energy():
    eng = HomeostasisEngine()
    state = DynamicState(energy=0.8, curiosity=0.5)
    # 03:00 local with offset 0 -> deep night.
    night_now = 3 * 3600
    eng.circadian(state, night_now, 0)
    assert state.energy < 0.8
    assert state.curiosity > 0.5


def test_circadian_morning_raises_energy():
    eng = HomeostasisEngine()
    state = DynamicState(energy=0.5)
    morning_now = 8 * 3600
    eng.circadian(state, morning_now, 0)
    assert state.energy > 0.5
