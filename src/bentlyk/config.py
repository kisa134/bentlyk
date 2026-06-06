"""Runtime configuration.

Everything has a sane offline default so the agent boots with no environment set.
Settings are read once from the environment; tests can construct ``Settings``
directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .actions.permissions import AutonomyMode


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(slots=True)
class Settings:
    # Reasoner
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"
    reflection_model: str = "claude-opus-4-8"

    # Storage
    store: str = "sqlite"  # "sqlite" | "postgres"
    sqlite_path: Path = field(default_factory=lambda: Path("./bentlyk.db"))
    pg_dsn: str = "postgresql://localhost:5432/bentlyk"

    # Behaviour
    max_autonomy: AutonomyMode = AutonomyMode.SUGGEST
    identity: str = "default"

    # Interfaces
    telegram_bot_token: str = ""
    telegram_allowed_user_id: str = ""

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            model=_env("BENTLYK_MODEL") or "claude-sonnet-4-6",
            reflection_model=_env("BENTLYK_REFLECTION_MODEL") or "claude-opus-4-8",
            store=_env("BENTLYK_STORE") or "sqlite",
            sqlite_path=Path(_env("BENTLYK_SQLITE_PATH") or "./bentlyk.db"),
            pg_dsn=_env("BENTLYK_PG_DSN") or "postgresql://localhost:5432/bentlyk",
            max_autonomy=AutonomyMode.from_str(_env("BENTLYK_MAX_AUTONOMY") or "suggest"),
            identity=_env("BENTLYK_IDENTITY") or "default",
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=_env("TELEGRAM_ALLOWED_USER_ID"),
        )
