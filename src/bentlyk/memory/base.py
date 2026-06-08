"""Memory item model and the embedding helper."""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from enum import Enum


class MemoryKind(str, Enum):
    SHORT_TERM = "short_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    AUTOBIOGRAPHICAL = "autobiographical"


@dataclass(slots=True)
class MemoryItem:
    kind: MemoryKind
    content: str
    salience: float = 0.5  # importance in [0,1]; drives retention and recall
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    use_count: int = 0
    embedding: list[float] = field(default_factory=list)

    def age_days(self, now: float | None = None) -> float:
        return ((now or time.time()) - self.created_at) / 86400.0


# --- Embeddings ---------------------------------------------------------------
# Two modes, same signature so the rest of the system never changes:
# * default — a dependency-free, deterministic hashing embedding (works offline,
#   but only matches on shared tokens, so semantic recall is shallow);
# * configured — a real model over any OpenAI-compatible ``/embeddings`` endpoint
#   (set via ``configure_embeddings``). On any error it falls back to the hash, so
#   memory never breaks. cosine() tolerates a dimension mismatch (returns 0), so old
#   hash-embedded memories and new real ones coexist until back-filled (``reembed``).

_DIM = 256

# Real-embedding config (set at startup from Settings); empty => hash mode.
_EMBED_MODEL = ""
_EMBED_BASE_URL = ""
_EMBED_KEY = ""
_CACHE: dict[str, list[float]] = {}
_CACHE_MAX = 4096


def configure_embeddings(model: str = "", base_url: str = "", key: str = "") -> None:
    """Point ``embed`` at a real OpenAI-compatible embeddings endpoint (or clear it)."""

    global _EMBED_MODEL, _EMBED_BASE_URL, _EMBED_KEY
    _EMBED_MODEL = (model or "").strip()
    _EMBED_BASE_URL = (base_url or "").strip().rstrip("/")
    _EMBED_KEY = (key or "").strip()
    _CACHE.clear()


def embeddings_active() -> bool:
    return bool(_EMBED_MODEL and _EMBED_BASE_URL and _EMBED_KEY)


def embed(text: str) -> list[float]:
    if embeddings_active():
        ck = text[:512]
        cached = _CACHE.get(ck)
        if cached is not None:
            return cached
        try:
            vec = _remote_embed(text)
            if len(_CACHE) < _CACHE_MAX:
                _CACHE[ck] = vec
            return vec
        except Exception:  # pragma: no cover - network; degrade, never break
            return _hash_embed(text)
    return _hash_embed(text)


def _remote_embed(text: str, timeout: float = 20.0) -> list[float]:
    body = json.dumps({"model": _EMBED_MODEL, "input": text[:8000]}).encode()
    req = urllib.request.Request(
        _EMBED_BASE_URL + "/embeddings", data=body, method="POST",
        headers={"Authorization": f"Bearer {_EMBED_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    vec = [float(x) for x in data["data"][0]["embedding"]]
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec  # unit-norm so cosine == dot


def _stable_hash(token: str) -> int:
    # hashlib (not built-in hash()) so embeddings are stable across processes,
    # which is what makes long-term recall survive restarts.
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for token in _tokenize(text):
        h = _stable_hash(token)
        vec[h % _DIM] += 1.0
        vec[(h >> 8) % _DIM] += 0.5  # a second bucket reduces collisions
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot))  # both are unit vectors


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]
