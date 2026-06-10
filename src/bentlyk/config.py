"""Runtime configuration.

Everything has a sane offline default so the agent boots with no environment set.
Settings are read once from the environment; tests can construct ``Settings``
directly.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .actions.permissions import AutonomyMode


def _default_sqlite_path() -> Path:
    # Use the temp dir so it's writable on serverless (Vercel's only writable
    # path is /tmp); harmless locally.
    return Path(tempfile.gettempdir()) / "bentlyk.db"

# Provider-agnostic OpenAI-compatible LLM. base_url + model are auto-detected from
# the key prefix so switching providers is a one-line env change.
_ANTHROPIC_DEFAULT = "claude-sonnet-4-6"


def _llm_defaults(key: str) -> tuple[str, str]:
    """(base_url, default chat model). We run on WaveSpeed; top Chinese model default."""

    return "https://llm.wavespeed.ai/v1", "deepseek/deepseek-chat"

# Supabase REST defaults. The publishable key is RLS-gated and safe to ship per
# Supabase's design; override via SUPABASE_URL / SUPABASE_KEY env for another
# project, and rotate/restrict for a fully private deployment.
_SUPABASE_URL_DEFAULT = "https://skrwfbhhagarehgbcfxp.supabase.co"
_SUPABASE_KEY_DEFAULT = "sb_publishable_25tjuO2AZUQZDC0QM-20Mw_OLxBo7xt"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _clean(value: str) -> str:
    """Strip stray wrappers a value can pick up when pasted into a hosting
    dashboard (angle brackets, quotes, spaces), so a mangled env var — e.g.
    ``<https://x.supabase.co>`` — can't break URL parsing."""

    return value.strip().strip("<>").strip().strip('"').strip("'").strip()


@dataclass(slots=True)
class Settings:
    # Reasoner. Any OpenAI-compatible provider (WaveSpeed by default) via
    # ``llm_api_key`` + ``llm_base_url``; else native Anthropic; else offline mock.
    llm_api_key: str = ""
    openrouter_api_key: str = ""  # back-compat alias for llm_api_key (legacy)
    anthropic_api_key: str = ""
    llm_base_url: str = "https://llm.wavespeed.ai/v1"
    model: str = _ANTHROPIC_DEFAULT  # chat / conversation
    reason_model: str = ""  # deep chain-of-thought; falls back to ``model``
    reflection_model: str = ""  # nightly sleep; falls back to ``model``
    code_model: str = ""  # strong coder for self-programming; falls back to ``model``
    fallback_model: str = ""  # tried if the primary model errors
    tavily_key: str = ""  # optional web-search key; without it, keyless DuckDuckGo is used

    # Embeddings — real semantic memory. WaveSpeed is chat-only, so embeddings come
    # from any OpenAI-compatible /embeddings endpoint (Jina, OpenAI, DeepInfra, Gemini,
    # …). Unset => the dependency-free hash embedding (shallow recall).
    embed_model: str = ""
    embed_base_url: str = ""
    embed_key: str = ""

    # Storage. Preference: Supabase REST (HTTPS, serverless-friendly) > Postgres
    # DSN > local SQLite.
    store: str = "sqlite"  # "sqlite" | "postgres" | "supabase"
    sqlite_path: Path = field(default_factory=_default_sqlite_path)
    pg_dsn: str = ""
    # Supabase REST. The publishable key is gated by RLS policies and is safe to
    # ship per Supabase's design; rotate/restrict for a fully private deployment.
    supabase_url: str = _SUPABASE_URL_DEFAULT
    supabase_key: str = _SUPABASE_KEY_DEFAULT

    # Behaviour
    max_autonomy: AutonomyMode = AutonomyMode.ESCALATED_ACT
    identity: str = "default"
    # Base interval between self-initiated outreaches (seconds). Backs off when the
    # person isn't replying. Default 30 min.
    proactive_interval_sec: int = 1800
    # Hours offset from UTC for Bentlyk's felt time-of-day / circadian rhythm.
    tz_offset_hours: float = 3.0  # Moscow by default

    # Interfaces
    telegram_bot_token: str = ""
    telegram_allowed_user_id: str = ""
    telegram_channel_id: str = ""  # public channel Bentlyk posts to (after approval)

    # Self-authoring: Bentlyk's own repo ("home") it can write code/pages into.
    gh_token: str = ""  # fine-grained PAT with Contents:write on self_repo
    self_repo: str = "kisa134/bentlyk-self"

    # Embodiment on a real machine (the worker as a body): a sandbox workdir, and
    # opt-in local code execution. Off by default; never enable on the public webhook.
    workdir: str = ""  # sandbox dir for local files/code (default ~/.bentlyk/work)
    allow_code: bool = False  # BENTLYK_ALLOW_CODE=1 to let it run code locally
    load_plugins: bool = False  # BENTLYK_LOAD_PLUGINS=1 to load self-authored tools as organs
    council: bool = True  # BENTLYK_COUNCIL=0 to disable the internal roles council (saves tokens)
    auto_post: bool = False  # BENTLYK_AUTO_POST=1: publish to its own channel on its own cadence
    market_symbol: str = "BTCUSDT"  # the real signal its learnable component grounds in

    @property
    def llm_key(self) -> str:
        return self.llm_api_key or self.openrouter_api_key

    @property
    def provider(self) -> str:
        if self.llm_key:
            return "openai_compat"
        if self.anthropic_api_key:
            return "anthropic"
        return "mock"

    @property
    def llm_enabled(self) -> bool:
        return self.provider != "mock"

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.embed_model and self.embed_base_url and self.embed_key)

    @property
    def effective_reason_model(self) -> str:
        return self.reason_model or self.model

    @property
    def effective_code_model(self) -> str:
        return self.code_model or self.model

    @property
    def effective_reflection_model(self) -> str:
        return self.reflection_model or self.model

    @classmethod
    def from_env(cls) -> "Settings":
        key = _env("BENTLYK_LLM_API_KEY") or _env("WAVESPEED_API_KEY") or _env("OPENROUTER_API_KEY")
        anthropic = _env("ANTHROPIC_API_KEY")
        auto_base, auto_model = _llm_defaults(key)
        model = _env("BENTLYK_MODEL") or (auto_model if key else _ANTHROPIC_DEFAULT)
        return cls(
            llm_api_key=key,
            anthropic_api_key=anthropic,
            llm_base_url=_env("BENTLYK_LLM_BASE_URL") or auto_base,
            model=model,
            reason_model=_env("BENTLYK_REASON_MODEL"),
            code_model=_env("BENTLYK_CODE_MODEL") or ("qwen/qwen3-coder" if key else ""),
            fallback_model=_env("BENTLYK_FALLBACK_MODEL"),
            reflection_model=_env("BENTLYK_REFLECTION_MODEL"),
            tavily_key=_env("BENTLYK_TAVILY_KEY"),
            embed_model=_env("BENTLYK_EMBED_MODEL"),
            embed_base_url=_clean(_env("BENTLYK_EMBED_BASE_URL")),
            embed_key=_env("BENTLYK_EMBED_KEY"),
            store=_env("BENTLYK_STORE") or ("postgres" if _env("BENTLYK_PG_DSN") else "sqlite"),
            sqlite_path=Path(_env("BENTLYK_SQLITE_PATH")) if _env("BENTLYK_SQLITE_PATH")
            else _default_sqlite_path(),
            pg_dsn=_env("BENTLYK_PG_DSN"),
            supabase_url=_clean(_env("SUPABASE_URL")) or _SUPABASE_URL_DEFAULT,
            supabase_key=_clean(_env("SUPABASE_KEY")) or _SUPABASE_KEY_DEFAULT,
            max_autonomy=AutonomyMode.from_str(_env("BENTLYK_MAX_AUTONOMY") or "escalated_act"),
            identity=_env("BENTLYK_IDENTITY") or "default",
            proactive_interval_sec=int(_env("BENTLYK_PROACTIVE_INTERVAL_SEC") or "1800"),
            tz_offset_hours=float(_env("BENTLYK_TZ_OFFSET") or "3"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=_env("TELEGRAM_ALLOWED_USER_ID"),
            telegram_channel_id=_env("TELEGRAM_CHANNEL_ID"),
            gh_token=_env("BENTLYK_GH_TOKEN"),
            self_repo=_env("BENTLYK_SELF_REPO") or "kisa134/bentlyk-self",
            workdir=_env("BENTLYK_WORKDIR"),
            allow_code=_env("BENTLYK_ALLOW_CODE") in ("1", "true", "yes"),
            load_plugins=_env("BENTLYK_LOAD_PLUGINS") in ("1", "true", "yes"),
            council=_env("BENTLYK_COUNCIL", "1") in ("1", "true", "yes"),
            auto_post=_env("BENTLYK_AUTO_POST") in ("1", "true", "yes"),
            market_symbol=_env("BENTLYK_MARKET_SYMBOL") or "BTCUSDT",
        )

    @property
    def work_path(self) -> "Path":
        return Path(self.workdir) if self.workdir else Path.home() / ".bentlyk" / "work"
