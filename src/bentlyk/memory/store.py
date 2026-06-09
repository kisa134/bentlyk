"""Memory store.

A SQLite-backed store that holds all memory contours, supports semantic recall
(embedding cosine + recency + salience), and exposes the compression/forgetting
primitives that reflection drives.

The :class:`MemoryStore` protocol is the seam: a Postgres+pgvector
implementation can drop in behind the same interface (see ``docs/architecture.md``).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Protocol

from .base import MemoryItem, MemoryKind, cosine, embed, reliability_of


class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> MemoryItem: ...
    def get(self, item_id: str) -> MemoryItem | None: ...
    def recall(
        self, query: str, *, kinds: Iterable[MemoryKind] | None = ..., limit: int = ...
    ) -> list[MemoryItem]: ...
    def recent(self, kind: MemoryKind, limit: int = ...) -> list[MemoryItem]: ...
    def all(self, kind: MemoryKind | None = ...) -> list[MemoryItem]: ...
    def update(self, item: MemoryItem) -> None: ...
    def forget(self, item_id: str) -> None: ...
    def decay_and_prune(self, *, now: float | None = ...) -> int: ...
    def close(self) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    salience REAL NOT NULL,
    tags TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL,
    use_count INTEGER NOT NULL,
    embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory(kind);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memory(created_at);

CREATE TABLE IF NOT EXISTS memory_links (
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON memory_links(src_id);
CREATE INDEX IF NOT EXISTS idx_links_dst ON memory_links(dst_id);
"""

# Below this effective salience, short-term/episodic memories are pruned.
_PRUNE_FLOOR = 0.08
# Salience decay per day for non-permanent contours.
_DECAY_PER_DAY = 0.03
# Contours that are never auto-pruned (identity-bearing or skill-bearing).
_PERMANENT = {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.AUTOBIOGRAPHICAL}


class SqliteMemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # --- writes ---------------------------------------------------------------
    def add(self, item: MemoryItem) -> MemoryItem:
        if not item.embedding:
            item.embedding = embed(item.content)
        self._conn.execute(
            "INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?,?,?,?,?)",
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
        self._conn.commit()
        return item

    def update(self, item: MemoryItem) -> None:
        self.add(item)

    def forget(self, item_id: str) -> None:
        self._conn.execute("DELETE FROM memory WHERE id = ?", (item_id,))
        self._conn.execute(
            "DELETE FROM memory_links WHERE src_id = ? OR dst_id = ?", (item_id, item_id)
        )
        self._conn.commit()

    # --- graph (Zettelkasten) -------------------------------------------------
    def add_link(self, src_id: str, dst_id: str, relation: str = "relates") -> None:
        if src_id == dst_id:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO memory_links VALUES (?,?,?,?)",
            (src_id, dst_id, relation, time.time()),
        )
        self._conn.commit()

    def neighbors(self, item_ids: list[str], limit: int = 6) -> list[MemoryItem]:
        if not item_ids:
            return []
        marks = ",".join("?" * len(item_ids))
        rows = self._conn.execute(
            f"SELECT dst_id AS other FROM memory_links WHERE src_id IN ({marks}) "
            f"UNION SELECT src_id AS other FROM memory_links WHERE dst_id IN ({marks})",
            (*item_ids, *item_ids),
        ).fetchall()
        ids = [r["other"] for r in rows if r["other"] not in item_ids][:limit]
        out = [self.get(i) for i in ids]
        return [m for m in out if m is not None]

    # --- reads ----------------------------------------------------------------
    def get(self, item_id: str) -> MemoryItem | None:
        row = self._conn.execute("SELECT * FROM memory WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def all(self, kind: MemoryKind | None = None) -> list[MemoryItem]:
        if kind is None:
            rows = self._conn.execute("SELECT * FROM memory").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE kind = ?", (kind.value,)
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def recent(self, kind: MemoryKind, limit: int = 10) -> list[MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memory WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
            (kind.value, limit),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def recall(
        self,
        query: str,
        *,
        kinds: Iterable[MemoryKind] | None = None,
        limit: int = 8,
    ) -> list[MemoryItem]:
        """Rank by a blend of semantic similarity, salience, and recency."""

        q = embed(query)
        now = time.time()
        items = self.all() if kinds is None else self._of_kinds(kinds)

        scored: list[tuple[float, MemoryItem]] = []
        for it in items:
            sim = cosine(q, it.embedding)
            recency = 1.0 / (1.0 + it.age_days(now))
            score = 0.55 * sim + 0.2 * it.salience + 0.12 * recency + 0.13 * reliability_of(it.tags)
            scored.append((score, it))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = [it for _, it in scored[:limit]]
        self._touch(top, now)
        return top

    # --- maintenance (driven by reflection) -----------------------------------
    def decay_and_prune(self, *, now: float | None = None) -> int:
        """Decay salience over time and prune faded, non-permanent memories.

        Returns the number of items forgotten.
        """

        now = now or time.time()
        forgotten = 0
        for it in self.all():
            if it.kind in _PERMANENT:
                continue
            decayed = it.salience - _DECAY_PER_DAY * it.age_days(now)
            # Frequently-used memories resist decay.
            decayed += min(0.2, 0.02 * it.use_count)
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
    def _of_kinds(self, kinds: Iterable[MemoryKind]) -> list[MemoryItem]:
        out: list[MemoryItem] = []
        for k in kinds:
            out.extend(self.all(k))
        return out

    def _touch(self, items: list[MemoryItem], now: float) -> None:
        for it in items:
            it.use_count += 1
            it.last_used_at = now
            self._conn.execute(
                "UPDATE memory SET use_count = ?, last_used_at = ? WHERE id = ?",
                (it.use_count, now, it.id),
            )
        self._conn.commit()


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        kind=MemoryKind(row["kind"]),
        content=row["content"],
        salience=row["salience"],
        tags=json.loads(row["tags"]),
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        use_count=row["use_count"],
        embedding=json.loads(row["embedding"]),
    )


def open_store(store: str, *, sqlite_path: str | Path = ":memory:", pg_dsn: str = "") -> MemoryStore:
    if store == "sqlite":
        return SqliteMemoryStore(sqlite_path)
    if store == "postgres":  # pragma: no cover - needs a live database
        from ..pg import PgMemoryStore

        if not pg_dsn:
            raise ValueError("BENTLYK_PG_DSN is required for the postgres store")
        return PgMemoryStore(pg_dsn)
    raise ValueError(f"unknown store backend: {store!r}")
