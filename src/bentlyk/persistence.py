"""Tiny sidecar persistence for the self-model.

Memory lives in the MemoryStore; the dynamic state and any identity overrides
live in a small JSON sidecar next to the SQLite file. With an in-memory store
persistence is a no-op so tests stay hermetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from .self_model import DynamicState, IdentityCore


class StatePersistence:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    @classmethod
    def beside(cls, sqlite_path: str | Path) -> "StatePersistence":
        p = Path(sqlite_path)
        if str(p) in (":memory:", ""):
            return cls(None)
        return cls(p.with_suffix(".state.json"))

    def load(self) -> tuple[IdentityCore | None, DynamicState | None]:
        if not self.path or not self.path.exists():
            return None, None
        data = json.loads(self.path.read_text())
        identity = IdentityCore.from_json(data["identity"]) if data.get("identity") else None
        state = DynamicState.from_json(data["state"]) if data.get("state") else None
        return identity, state

    def save(self, identity: IdentityCore, state: DynamicState) -> None:
        if not self.path:
            return
        self.path.write_text(
            json.dumps({"identity": identity.to_json(), "state": state.to_json()}, indent=2)
        )
