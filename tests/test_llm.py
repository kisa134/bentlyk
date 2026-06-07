from bentlyk.actions import default_registry
from bentlyk.config import Settings
from bentlyk.llm import (
    MockReasoner,
    OpenAICompatReasoner,
    ReasonerError,
    build_reasoner,
)


def test_provider_inference():
    assert Settings().provider == "mock"
    assert Settings(anthropic_api_key="x").provider == "anthropic"
    assert Settings(openrouter_api_key="x").provider == "openrouter"
    # OpenRouter wins when both are set (OpenAI-compatible path is preferred).
    assert Settings(openrouter_api_key="x", anthropic_api_key="y").provider == "openrouter"


def test_build_reasoner_picks_openrouter():
    s = Settings(openrouter_api_key="sk-or-test", model="anthropic/claude-3.5-sonnet")
    r = build_reasoner(s)
    assert isinstance(r, OpenAICompatReasoner)


def test_build_reasoner_offline_default():
    assert isinstance(build_reasoner(Settings()), MockReasoner)


def test_reflection_model_falls_back_to_model():
    s = Settings(openrouter_api_key="x", model="m1")
    assert s.effective_reflection_model == "m1"
    s2 = Settings(openrouter_api_key="x", model="m1", reflection_model="m2")
    assert s2.effective_reflection_model == "m2"


class _FailingReasoner:
    def complete(self, *, system, prompt, max_tokens=1024):
        raise ReasonerError("boom")


def test_respond_tool_survives_reasoner_failure():
    # The companion must keep talking even if the model errors.
    reg = default_registry()
    respond = reg.get("respond")
    outbox: list[str] = []
    ctx = {"outbox": outbox, "reasoner": _FailingReasoner(), "user_message": "hi"}
    result = respond.run({}, ctx)
    assert result.ok is False
    assert outbox  # a graceful fallback was still sent
