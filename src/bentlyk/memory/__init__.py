"""Memory System.

Not a single vector DB but several contours with different write/forget rules:

* ``SHORT_TERM`` — current dialogue, active plan, working variables.
* ``EPISODIC`` — events, decisions, mistakes, promises.
* ``SEMANTIC`` — facts about the world, the person, projects.
* ``PROCEDURAL`` — behaviour scripts, playbooks, skills.
* ``AUTOBIOGRAPHICAL`` — the agent's own history, turning points, self-narrative.

Memory must not only grow but also compress, be re-scored, and be rewritten by
reflection — otherwise the agent becomes noisy and self-contradictory.
"""

from .base import MemoryItem, MemoryKind, configure_embeddings, embeddings_active
from .store import MemoryStore, SqliteMemoryStore, open_store

__all__ = [
    "MemoryItem",
    "MemoryKind",
    "MemoryStore",
    "SqliteMemoryStore",
    "open_store",
    "configure_embeddings",
    "embeddings_active",
]
