"""Memory item model and the embedding helper."""

from __future__ import annotations

import hashlib
import math
import time
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
# A dependency-free, deterministic hashing embedding so semantic recall works
# offline. Swap ``embed`` for a real model (e.g. Voyage / OpenAI) in production;
# the rest of the system only depends on this signature.

_DIM = 256


def _stable_hash(token: str) -> int:
    # hashlib (not built-in hash()) so embeddings are stable across processes,
    # which is what makes long-term recall survive restarts.
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")


def embed(text: str) -> list[float]:
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
