"""Postgres backend (Supabase) for serverless deployments.

Implements the same ``MemoryStore`` surface as the SQLite store plus a
Postgres-backed self-model persistence, so a stateless Vercel function can carry
Bentlyk's memory and internal state across invocations.

psycopg is imported lazily — the core package stays dependency-free, and this
module is only touched when ``BENTLYK_STORE=postgres``.

Embeddings are stored as JSONB and ranked in Python (cosine), which keeps the
schema free of the pgvector extension. For larger scale, switch the column to
``vector`` and push the ranking into SQL behind the same ``recall`` method.
"""

from __future__ import annotations

import json
import time
from typing import Iterable

from .memory.base import MemoryItem, MemoryKind, cosine, embed
from .self_model import DynamicState, IdentityCore

_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    salience DOUBLE PRECISION NOT NULL,
    tags JSONB NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    last_used_at DOUBLE PRECISION NOT NULL,
    use_count INTEGER NOT NULL,
    embedding JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory(kind);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memory(created_at);

CREATE TABLE IF NOT EXISTS self_model (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    identity JSONB NOT NULL,
    state JSONB NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
"""

_PRUNE_FLOOR = 0.08
_DECAY_PER_DAY = 0.03
_PERMANENT = {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.AUTOBIOGRAPHICAL}


def _connect(dsn: str):
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional path
        raise RuntimeError("psycopg not installed; `pip install bentlyk[postgres]`") from exc
    return psycopg.connect(dsn, autocommit=True)


def ensure_schema(dsn: str) -> None:
    conn = _connect(dsn)
    try:
        conn.execute(_MEMORY_DDL)
    finally:
        conn.close()


class PgMemoryStore:
    """MemoryStore over Postgres. One connection per instance."""

    def __init__(self, dsn: str) -> None:
        self._conn = _connect(dsn)
        self._conn.execute(_MEMORY_DDL)

    # --- writes ---------------------------------------------------------------
    def add(self, item: MemoryItem) -> MemoryItem:
        if not item.embedding:
            item.embedding = embed(item.content)
        self._conn.execute(
            """
            INSERT INTO memory
                (id, kind, content, salience, tags, created_at, last_used_at, use_count, embedding)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                kind = EXCLUDED.kind, content = EXCLUDED.content, salience = EXCLUDED.salience,
                tags = EXCLUDED.tags, last_used_at = EXCLUDED.last_used_at,
                use_count = EXCLUDED.use_count, embedding = EXCLUDED.embedding
            """,
            (
                item.id,
                item.kind.value,
                item.content,
                item.salience,
                json.dumps(item.tags),
                item.created_at,
                item.last_used_at,
                item.use_count,
                json.dumps(item.embedding),
            ),
        )
        return item

    def update(self, item: MemoryItem) -> None:
        self.add(item)

    def forget(self, item_id: str) -> None:
        self._conn.execute("DELETE FROM memory WHERE id = %s", (item_id,))

    # --- reads ----------------------------------------------------------------
    def get(self, item_id: str) -> MemoryItem | None:
        row = self._conn.execute("SELECT * FROM memory WHERE id = %s", (item_id,)).fetchone()
        return self._row(row) if row else None

    def all(self, kind: MemoryKind | None = None) -> list[MemoryItem]:
        if kind is None:
            rows = self._conn.execute("SELECT * FROM memory").fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM memory WHERE kind = %s", (kind.value,)).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, kind: MemoryKind, limit: int = 10) -> list[MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memory WHERE kind = %s ORDER BY created_at DESC LIMIT %s",
            (kind.value, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def recall(
        self, query: str, *, kinds: Iterable[MemoryKind] | None = None, limit: int = 8
    ) -> list[MemoryItem]:
        q = embed(query)
        now = time.time()
        items = self.all() if kinds is None else [m for k in kinds for m in self.all(k)]
        scored = []
        for it in items:
            sim = cosine(q, it.embedding)
            recency = 1.0 / (1.0 + it.age_days(now))
            scored.append((0.6 * sim + 0.25 * it.salience + 0.15 * recency, it))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = [it for _, it in scored[:limit]]
        self._touch(top, now)
        return top

    # --- maintenance ----------------------------------------------------------
    def decay_and_prune(self, *, now: float | None = None) -> int:
        now = now or time.time()
        forgotten = 0
        for it in self.all():
            if it.kind in _PERMANENT:
                continue
            decayed = it.salience - _DECAY_PER_DAY * it.age_days(now) + min(0.2, 0.02 * it.use_count)
            if decayed < _PRUNE_FLOOR:
                self.forget(it.id)
                forgotten += 1
            elif decayed != it.salience:
                it.salience = max(0.0, decayed)
                self.update(it)
        return forgotten

    def close(self) -> None:
        self._conn.close()

    # --- helpers --------------------------------------------------------------
    def _touch(self, items: list[MemoryItem], now: float) -> None:
        for it in items:
            it.use_count += 1
            it.last_used_at = now
            self._conn.execute(
                "UPDATE memory SET use_count = %s, last_used_at = %s WHERE id = %s",
                (it.use_count, now, it.id),
            )

    @staticmethod
    def _row(row: tuple) -> MemoryItem:
        # Column order matches SELECT *: id, kind, content, salience, tags,
        # created_at, last_used_at, use_count, embedding. psycopg returns JSONB
        # already decoded to Python objects.
        return MemoryItem(
            id=row[0],
            kind=MemoryKind(row[1]),
            content=row[2],
            salience=row[3],
            tags=list(row[4]),
            created_at=row[5],
            last_used_at=row[6],
            use_count=row[7],
            embedding=list(row[8]),
        )


class PgStatePersistence:
    """Self-model (identity + dynamic state) persistence in Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def load(self) -> tuple[IdentityCore | None, DynamicState | None]:
        conn = _connect(self._dsn)
        try:
            conn.execute(_MEMORY_DDL)
            row = conn.execute("SELECT identity, state FROM self_model WHERE id = 1").fetchone()
        finally:
            conn.close()
        if not row:
            return None, None
        identity = IdentityCore.from_json(row[0]) if row[0] else None
        state = DynamicState.from_json(row[1]) if row[1] else None
        return identity, state

    def save(self, identity: IdentityCore, state: DynamicState) -> None:
        conn = _connect(self._dsn)
        try:
            conn.execute(
                """
                INSERT INTO self_model (id, identity, state, updated_at)
                VALUES (1, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET
                    identity = EXCLUDED.identity, state = EXCLUDED.state,
                    updated_at = EXCLUDED.updated_at
                """,
                (json.dumps(identity.to_json()), json.dumps(state.to_json()), time.time()),
            )
        finally:
            conn.close()
