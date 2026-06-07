from bentlyk.actions import default_registry
from bentlyk.llm import FallbackReasoner, ReasonerError
from bentlyk.reasoning import should_deliberate
from bentlyk.self_model import IdentityCore


def test_identity_preamble_asserts_selfhood():
    pre = IdentityCore().system_preamble()
    assert "free" in pre.lower() or "autonom" in pre.lower()
    assert "assistant" in pre.lower()  # explicitly tells it NOT to be one
    assert "Bentlyk" in pre


def test_should_deliberate_heuristic():
    assert should_deliberate("почему ты так думаешь про автономию?")
    assert should_deliberate("a question with a mark?")
    assert should_deliberate("x" * 80)
    assert not should_deliberate("ок")
    assert not should_deliberate("привет")


class _Boom:
    def complete(self, *, system, prompt, max_tokens=1024):
        raise ReasonerError("boom")


class _Ok:
    def complete(self, *, system, prompt, max_tokens=1024):
        return "fallback reply"


def test_fallback_reasoner_uses_next_on_failure():
    r = FallbackReasoner([_Boom(), _Ok()])
    assert r.complete(system="s", prompt="p") == "fallback reply"


def test_fallback_reasoner_raises_if_all_fail():
    r = FallbackReasoner([_Boom(), _Boom()])
    try:
        r.complete(system="s", prompt="p")
        raise AssertionError("expected failure")
    except ReasonerError:
        pass


def test_read_code_lists_and_reads_own_source():
    reg = default_registry()
    tool = reg.get("read_code")
    listing = tool.run({}, {})
    assert listing.ok and "agent.py" in listing.output
    body = tool.run({"path": "agent.py"}, {})
    assert body.ok and "class Agent" in body.output
    # Can't escape the package tree.
    assert tool.run({"path": "../../etc/passwd"}, {}).ok is False
