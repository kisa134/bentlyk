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

# Default models per role on OpenRouter. Strong, low-censorship options (top
# Chinese labs) for a free-feeling companion; all overridable via env, with an
# always-available fallback so a bad slug never breaks the loop.
_CHAT_DEFAULT_OR = "deepseek/deepseek-chat"  # fluent, low-censorship, cheap
_REASON_DEFAULT_OR = "deepseek/deepseek-r1"  # explicit chain-of-thought model
_FALLBACK_OR = "openai/gpt-4o-mini"  # safe fallback if a primary slug 404s
_ANTHROPIC_DEFAULT = "claude-sonnet-4-6"

# Supabase REST defaults. The publishable key is RLS-gated and safe to ship per
# Supabase's design; override via SUPABASE_URL / SUPABASE_KEY env for another
# project, and rotate/restrict for a fully private deployment.
_SUPABASE_URL_DEFAULT = "https://skrwfbhhagarehgbcfxp.supabase.co"
_SUPABASE_KEY_DEFAULT = "sb_publishable_25tjuO2AZUQZDC0QM-20Mw_OLxBo7xt"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(slots=True)
class Settings:
    # Reasoner. Provider is inferred: OpenRouter (OpenAI-compatible) if its key is
    # set, else native Anthropic, else the offline mock.
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    model: str = _ANTHROPIC_DEFAULT  # chat / conversation
    reason_model: str = ""  # deep chain-of-thought; falls back to ``model``
    reflection_model: str = ""  # nightly sleep; falls back to ``model``
    fallback_model: str = ""  # tried if the primary model errors

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
    max_autonomy: AutonomyMode = AutonomyMode.SUGGEST
    identity: str = "default"
    # Base interval between self-initiated outreaches (seconds). Backs off when the
    # person isn't replying. Default 30 min.
    proactive_interval_sec: int = 1800

    # Interfaces
    telegram_bot_token: str = ""
    telegram_allowed_user_id: str = ""

    @property
    def provider(self) -> str:
        if self.openrouter_api_key:
            return "openrouter"
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
    def effective_reason_model(self) -> str:
        return self.reason_model or self.model

    @property
    def effective_reflection_model(self) -> str:
        return self.reflection_model or self.model

    @classmethod
    def from_env(cls) -> "Settings":
        openrouter = _env("OPENROUTER_API_KEY")
        anthropic = _env("ANTHROPIC_API_KEY")
        explicit_model = _env("BENTLYK_MODEL")
        if explicit_model:
            model = explicit_model
        elif openrouter:
            model = _CHAT_DEFAULT_OR
        else:
            model = _ANTHROPIC_DEFAULT
        reason = _env("BENTLYK_REASON_MODEL") or (_REASON_DEFAULT_OR if openrouter else "")
        fallback = _env("BENTLYK_FALLBACK_MODEL") or (_FALLBACK_OR if openrouter else "")
        return cls(
            openrouter_api_key=openrouter,
            anthropic_api_key=anthropic,
            llm_base_url=_env("BENTLYK_LLM_BASE_URL") or "https://openrouter.ai/api/v1",
            model=model,
            reason_model=reason,
            fallback_model=fallback,
            reflection_model=_env("BENTLYK_REFLECTION_MODEL"),
            store=_env("BENTLYK_STORE") or ("postgres" if _env("BENTLYK_PG_DSN") else "sqlite"),
            sqlite_path=Path(_env("BENTLYK_SQLITE_PATH")) if _env("BENTLYK_SQLITE_PATH")
            else _default_sqlite_path(),
            pg_dsn=_env("BENTLYK_PG_DSN"),
            supabase_url=_env("SUPABASE_URL") or _SUPABASE_URL_DEFAULT,
            supabase_key=_env("SUPABASE_KEY") or _SUPABASE_KEY_DEFAULT,
            max_autonomy=AutonomyMode.from_str(_env("BENTLYK_MAX_AUTONOMY") or "suggest"),
            identity=_env("BENTLYK_IDENTITY") or "default",
            proactive_interval_sec=int(_env("BENTLYK_PROACTIVE_INTERVAL_SEC") or "1800"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=_env("TELEGRAM_ALLOWED_USER_ID"),
        )
