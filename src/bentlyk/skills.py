"""Skills — Bentlyk learning, not just remembering.

A skill is a named capability the entity is developing (research, self-programming,
reasoning, conversation, …). Unlike a memory (a thing it knows), a skill has a
*proficiency that grows with practice and real feedback*: every time it uses a
tool toward a goal, the matching skill records a rep and whether it worked, and
its level moves. That closes the learning loop the user asked for — acquire a
skill, apply it, get feedback, improve — and because skills are memories, the
graph weaves them into the rest of what it knows (interconnections).

Stored as PROCEDURAL memories tagged ``skill`` with ``reps:N``/``wins:N`` counters,
so there is no schema change; proficiency is derived from win-rate × maturity.
"""

from __future__ import annotations

import re

from .memory import MemoryItem, MemoryKind

_SKILL_TAG = "skill"

# Which skill each tool practises — so ordinary work trains real, named abilities.
TOOL_SKILL: dict[str, str] = {
    "write_program": "self-programming",
    "publish_site": "self-programming",
    "read_code": "self-knowledge",
    "read_self": "self-knowledge",
    "web_search": "research",
    "consult_model": "seeking-counsel",
    "deliberate": "reasoning",
    "post_to_channel": "communicating",
    "respond": "conversation",
    "remember": "sense-making",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "skill"


def _tag_int(tags: list[str], prefix: str, default: int = 0) -> int:
    for t in tags:
        if t.startswith(prefix):
            try:
                return int(t[len(prefix):])
            except ValueError:
                return default
    return default


def list_skills(store) -> list[MemoryItem]:
    return [m for m in store.all(MemoryKind.PROCEDURAL) if _SKILL_TAG in m.tags]


def proficiency(item: MemoryItem) -> float:
    """Skill mastery in [0,1]: how often it works, tempered by how much it's been practised."""
    reps = _tag_int(item.tags, "reps:", 0)
    wins = _tag_int(item.tags, "wins:", 0)
    if reps <= 0:
        return 0.0
    rate = wins / reps
    maturity = min(1.0, reps / 12.0)  # a skill isn't "mastered" until it's been exercised
    return round(rate * maturity, 3)


def level(item: MemoryItem) -> int:
    return round(proficiency(item) * 9)


def practice(store, name: str, *, success: bool, desc: str = "") -> MemoryItem:
    """Record one practice rep of a skill (declaring it if new) and move its level."""
    slug = _slug(name)
    existing = next((m for m in list_skills(store) if f"skill:{slug}" in m.tags), None)
    if existing is None:
        content = f"навык: {name}" + (f" — {desc}" if desc else "")
        item = MemoryItem(
            kind=MemoryKind.PROCEDURAL, content=content,
            tags=[_SKILL_TAG, f"skill:{slug}", "reps:1", f"wins:{1 if success else 0}",
                  "ep:evidence", "rel:6"],
            salience=0.6,
        )
        return store.add(item)
    reps = _tag_int(existing.tags, "reps:", 0) + 1
    wins = _tag_int(existing.tags, "wins:", 0) + (1 if success else 0)
    existing.tags = [t for t in existing.tags if not t.startswith(("reps:", "wins:"))] + [
        f"reps:{reps}", f"wins:{wins}"]
    if desc and " — " not in existing.content:
        existing.content = f"{existing.content} — {desc}"
    existing.salience = min(0.92, 0.5 + proficiency(existing) * 0.4)
    store.update(existing)
    return existing


def practice_from_tool(store, toolname: str, success: bool) -> MemoryItem | None:
    """Map a tool the entity just used to the skill it exercises, and practise it."""
    skill = TOOL_SKILL.get(toolname or "")
    return practice(store, skill, success=success) if skill else None
