"""Attention: explicit, maintained focus + the metacontrol tool + self-work loop."""

from bentlyk import attention
from bentlyk.actions.tools import build_builtin_tools
from bentlyk.agent import Agent
from bentlyk.config import Settings
from bentlyk.self_model import DynamicState


def _tool(name):
    return next(t for t in build_builtin_tools() if t.name == name)


def test_attend_relax_release():
    s = DynamicState()
    attention.attend(s, "improve my memory graph", 0.9)
    assert s.focus.startswith("improve") and s.focus_strength == 0.9
    assert attention.is_focused(s)
    attention.relax(s, minutes=20)  # loosens toward baseline over time
    assert attention.BASELINE <= s.focus_strength < 0.9
    attention.release(s)
    assert s.focus == "" and not attention.is_focused(s)


def test_describe_open_vs_focused():
    s = DynamicState()
    assert "расфокус" in attention.describe(s)
    attention.attend(s, "цель X", 0.8)
    assert "цель X" in attention.describe(s)


def test_focus_tool_directs_and_releases():
    s = DynamicState()
    ctx = {"state": s}
    r = _tool("focus").run({"on": "writing my own code", "strength": 0.85}, ctx)
    assert r.ok and s.focus == "writing my own code" and s.focus_strength == 0.85
    r = _tool("focus").run({"release": True}, ctx)
    assert r.ok and s.focus == ""


def test_pursue_stamps_time_and_guarantees_a_goal(tmp_path):
    # Offline (mock reasoner). The self-development loop must always have a goal and
    # must record when it last ran, so it can fire on a time cadence across restarts.
    s = Settings(sqlite_path=tmp_path / "b.db", supabase_url="", supabase_key="")
    agent = Agent(settings=s)
    try:
        assert agent.state.last_pursue_ts == 0.0
        agent.pursue()
        assert agent.state.last_pursue_ts > 0.0
        assert agent.active_goals()  # founding self-development goal is guaranteed
        assert agent.state.focus  # attention landed on the goal it pursued
    finally:
        agent.close()
