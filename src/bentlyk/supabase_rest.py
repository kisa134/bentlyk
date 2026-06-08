"""Supabase REST (PostgREST) backend.

The serverless-friendly path: talk to Supabase over plain HTTPS instead of the
Postgres wire protocol. This sidesteps the connection-pooler hostname and
IPv6 issues entirely — any region, IPv4, no driver. Uses only the standard
library so cold starts stay light.

Implements the same ``MemoryStore`` surface as the SQLite/Postgres stores, plus
a self-model persistence, behind a publishable (anon) key gated by RLS policies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from .memory.base import MemoryItem, MemoryKind, cosine, embed
from .self_model import DynamicState, IdentityCore

_PRUNE_FLOOR = 0.08
_DECAY_PER_DAY = 0.03
_PERMANENT = {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL, MemoryKind.AUTOBIOGRAPHICAL}


class SupabaseRest:
    """MemoryStore over the Supabase PostgREST API."""

    def __init__(self, url: str, key: str, timeout: float = 15.0) -> None:
        # Defensive: a value pasted into a hosting dashboard can arrive wrapped in
        # angle brackets/quotes/spaces (e.g. "<https://x.supabase.co>"), which makes
        # urllib reject the scheme. Strip those so a mangled env can't break us.
        url = url.strip().strip("<>").strip().strip('"').strip("'").strip()
        self._base = url.rstrip("/") + "/rest/v1"
        self._key = key.strip().strip("<>").strip().strip('"').strip("'").strip()
        self._timeout = timeout

    # --- HTTP helper ----------------------------------------------------------
    def _req(self, method: str, path: str, *, params: dict | None = None,
             body: object = None, prefer: str | None = None) -> list:
        q = "?" + urllib.parse.urlencode(params) if params else ""
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(self._base + path + q, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else []
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"supabase REST {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            raise RuntimeError(f"supabase REST unreachable: {exc}") from exc

    # --- writes ---------------------------------------------------------------
    def add(self, item: MemoryItem) -> MemoryItem:
        if not item.embedding:
            item.embedding = embed(item.content)
        self._req(
            "POST", "/memory", params={"on_conflict": "id"}, body=[_to_row(item)],
            prefer="resolution=merge-duplicates,return=minimal",
        )
        return item

    def update(self, item: MemoryItem) -> None:
        self.add(item)

    def forget(self, item_id: str) -> None:
        self._req("DELETE", "/memory", params={"id": f"eq.{item_id}"}, prefer="return=minimal")
        self._req(
            "DELETE", "/memory_links",
            params={"or": f"(src_id.eq.{item_id},dst_id.eq.{item_id})"}, prefer="return=minimal",
        )

    # --- graph (Zettelkasten) -------------------------------------------------
    def add_link(self, src_id: str, dst_id: str, relation: str = "relates") -> None:
        if src_id == dst_id:
            return
        self._req(
            "POST", "/memory_links", params={"on_conflict": "src_id,dst_id,relation"},
            body=[{"src_id": src_id, "dst_id": dst_id, "relation": relation, "created_at": time.time()}],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def neighbors(self, item_ids: list[str], limit: int = 6) -> list[MemoryItem]:
        if not item_ids:
            return []
        idlist = "(" + ",".join(item_ids) + ")"
        rows = self._req("GET", "/memory_links", params={
            "or": f"(src_id.in.{idlist},dst_id.in.{idlist})", "select": "src_id,dst_id",
        })
        others: list[str] = []
        for r in rows:
            for side in (r.get("src_id"), r.get("dst_id")):
                if side and side not in item_ids and side not in others:
                    others.append(side)
        out = [self.get(i) for i in others[:limit]]
        return [m for m in out if m is not None]

    # --- reads ----------------------------------------------------------------
    def get(self, item_id: str) -> MemoryItem | None:
        rows = self._req("GET", "/memory", params={"id": f"eq.{item_id}", "select": "*"})
        return _from_row(rows[0]) if rows else None

    def all(self, kind: MemoryKind | None = None) -> list[MemoryItem]:
        params = {"select": "*", "limit": "1000"}
        if kind is not None:
            params["kind"] = f"eq.{kind.value}"
        return [_from_row(r) for r in self._req("GET", "/memory", params=params)]

    def recent(self, kind: MemoryKind, limit: int = 10) -> list[MemoryItem]:
        params = {
            "select": "*", "kind": f"eq.{kind.value}",
            "order": "created_at.desc", "limit": str(limit),
        }
        return [_from_row(r) for r in self._req("GET", "/memory", params=params)]

    def recent_any(self, limit: int = 50) -> list[MemoryItem]:
        """The newest memories across all contours, chronological — for the live feed."""
        params = {"select": "*", "order": "created_at.desc", "limit": str(limit)}
        return [_from_row(r) for r in self._req("GET", "/memory", params=params)]

    def recall(
        self, query: str, *, kinds: Iterable[MemoryKind] | None = None, limit: int = 8
    ) -> list[MemoryItem]:
        q = embed(query)
        now = time.time()
        items = self.all() if kinds is None else [m for k in kinds for m in self.all(k)]
        scored = sorted(
            (
                (0.6 * cosine(q, it.embedding) + 0.25 * it.salience + 0.15 / (1 + it.age_days(now)), it)
                for it in items
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [it for _, it in scored[:limit]]

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

    def close(self) -> None:  # nothing to close over HTTP
        pass


class SupabaseRestState:
    """Self-model persistence over PostgREST."""

    def __init__(self, url: str, key: str) -> None:
        self._rest = SupabaseRest(url, key)

    def load(self) -> tuple[IdentityCore | None, DynamicState | None]:
        rows = self._rest._req("GET", "/self_model", params={"id": "eq.1", "select": "*"})
        if not rows:
            return None, None
        row = rows[0]
        identity = IdentityCore.from_json(row["identity"]) if row.get("identity") else None
        state = DynamicState.from_json(row["state"]) if row.get("state") else None
        return identity, state

    def save(self, identity: IdentityCore, state: DynamicState) -> None:
        self._rest._req(
            "POST", "/self_model", params={"on_conflict": "id"},
            body=[{
                "id": 1,
                "identity": identity.to_json(),
                "state": state.to_json(),
                "updated_at": time.time(),
            }],
            prefer="resolution=merge-duplicates,return=minimal",
        )


def _to_row(it: MemoryItem) -> dict:
    return {
        "id": it.id,
        "kind": it.kind.value,
        "content": it.content,
        "salience": it.salience,
        "tags": it.tags,
        "created_at": it.created_at,
        "last_used_at": it.last_used_at,
        "use_count": it.use_count,
        "embedding": it.embedding,
    }


def _from_row(r: dict) -> MemoryItem:
    return MemoryItem(
        id=r["id"],
        kind=MemoryKind(r["kind"]),
        content=r["content"],
        salience=r["salience"],
        tags=list(r.get("tags") or []),
        created_at=r["created_at"],
        last_used_at=r["last_used_at"],
        use_count=r["use_count"],
        embedding=list(r.get("embedding") or []),
    )
