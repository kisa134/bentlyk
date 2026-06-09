"""FPF deep integration: reliability-weighted recall, attempt signatures, and the
anti-loop guard that forces a reroute when an approach is repeated without progress."""

from __future__ import annotations

from bentlyk.actions import AutonomyMode
from bentlyk.agent import Agent
from bentlyk.config import Settings
from bentlyk.memory import MemoryItem, MemoryKind, open_store
from bentlyk.memory.base import reliability_of


def test_reliability_of_reads_rel_tag():
    assert reliability_of(["rel:9"]) == 1.0
    assert reliability_of(["rel:0"]) == 0.0
    assert reliability_of(["unrelated"]) == 0.5  # neutral for untagged/legacy


def test_step_signature_fingerprints_tool_and_target():
    assert Agent._step_signature("write_program", {"path": "a.py"}) == "write_program:a.py"
    assert Agent._step_signature("web_search", {"query": "x"}) == "web_search:x"
    assert Agent._step_signature(None, None) == "none:"


def test_recall_prefers_higher_reliability_on_equal_content():
    store = open_store("sqlite")
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="cache strategy works",
                         tags=["ep:evidence", "rel:9"]))
    store.add(MemoryItem(kind=MemoryKind.SEMANTIC, content="cache strategy works",
                         tags=["ep:assumption", "rel:1"]))
    top = store.recall("cache strategy", limit=1)[0]
    assert "rel:9" in top.tags


def _fake_reasoner(json_str: str):
    class _R:
        def complete(self, system, prompt, max_tokens=600):
            return json_str
    return _R()


def test_loop_guard_forces_reroute_on_repeated_approach():
    s = Settings.from_env()
    s.max_autonomy = AutonomyMode.ESCALATED_ACT
    agent = Agent(settings=s, store=open_store("sqlite"))
    agent.state.energy = 0.6
    agent._generate_self_goals()
    # two prior identical attempts make the next one a stall
    for _ in range(2):
        agent.store.add(MemoryItem(kind=MemoryKind.EPISODIC, content="prior",
                                   tags=["self_work", "sig:write_program:tools/x.py"]))
    agent.reasoner = _fake_reasoner(
        '{"step":"again","tool":"write_program","args":{"path":"tools/x.py","spec":"again"},'
        '"move":"continue","lesson":"writing is not running","done":false}'
    )
    line = agent.pursue()
    assert "reroute" in line  # forced pivot instead of a silent loop
    # the lesson is stored as evidence, kept apart from plan and run
    lessons = [m for m in agent.store.all(MemoryKind.SEMANTIC) if "lesson" in m.tags]
    assert lessons and reliability_of(lessons[0].tags) > 0.5
