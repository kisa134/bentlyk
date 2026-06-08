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
    assert Settings(llm_api_key="x").provider == "openai_compat"
    assert Settings(openrouter_api_key="x").provider == "openai_compat"  # back-compat alias
    # An OpenAI-compatible key wins when both are set.
    assert Settings(llm_api_key="x", anthropic_api_key="y").provider == "openai_compat"


def test_build_reasoner_picks_openai_compat():
    s = Settings(llm_api_key="wsk_test", model="anthropic/claude-sonnet-4.6")
    r = build_reasoner(s)
    assert isinstance(r, OpenAICompatReasoner)


def test_wavespeed_key_autodetects_base_and_model(monkeypatch):
    monkeypatch.setenv("BENTLYK_LLM_API_KEY", "wsk_live_demo")
    monkeypatch.delenv("BENTLYK_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("BENTLYK_MODEL", raising=False)
    s = Settings.from_env()
    assert s.llm_base_url == "https://llm.wavespeed.ai/v1"
    assert s.model == "deepseek/deepseek-chat"  # top Chinese default
    assert s.provider == "openai_compat"


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
