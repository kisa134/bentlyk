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

# Default chat models per provider. OpenRouter slugs differ from native ones.
_OPENROUTER_DEFAULT = "anthropic/claude-3.5-sonnet"
_ANTHROPIC_DEFAULT = "claude-sonnet-4-6"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(slots=True)
class Settings:
    # Reasoner. Provider is inferred: OpenRouter (OpenAI-compatible) if its key is
    # set, else native Anthropic, else the offline mock.
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    model: str = _ANTHROPIC_DEFAULT
    reflection_model: str = ""  # falls back to ``model`` when empty

    # Storage
    store: str = "sqlite"  # "sqlite" | "postgres"
    sqlite_path: Path = field(default_factory=_default_sqlite_path)
    pg_dsn: str = ""

    # Behaviour
    max_autonomy: AutonomyMode = AutonomyMode.SUGGEST
    identity: str = "default"

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
            model = _OPENROUTER_DEFAULT
        else:
            model = _ANTHROPIC_DEFAULT
        return cls(
            openrouter_api_key=openrouter,
            anthropic_api_key=anthropic,
            llm_base_url=_env("BENTLYK_LLM_BASE_URL") or "https://openrouter.ai/api/v1",
            model=model,
            reflection_model=_env("BENTLYK_REFLECTION_MODEL"),
            store=_env("BENTLYK_STORE") or ("postgres" if _env("BENTLYK_PG_DSN") else "sqlite"),
            sqlite_path=Path(_env("BENTLYK_SQLITE_PATH")) if _env("BENTLYK_SQLITE_PATH")
            else _default_sqlite_path(),
            pg_dsn=_env("BENTLYK_PG_DSN"),
            max_autonomy=AutonomyMode.from_str(_env("BENTLYK_MAX_AUTONOMY") or "suggest"),
            identity=_env("BENTLYK_IDENTITY") or "default",
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=_env("TELEGRAM_ALLOWED_USER_ID"),
        )
