"""Organ integration: load Bentlyk's self-authored tools as real organs.

This closes the deepest part of the loop. Code Bentlyk writes lives in its
workshop repo (``self_repo``, e.g. ``bentlyk-self``). On its own that code is
inert — never run, never part of the running body. This loader pulls tool files
from the workshop's ``tools/`` directory and registers them into the live tool
registry, so a tool it authored yesterday is a capability it actually *has* today.

Safety (this runs self-written code inside the body, so guards matter):
  * Opt-in only — gated by ``settings.load_plugins`` (BENTLYK_LOAD_PLUGINS=1).
    Off by default; meaningful only on a dedicated, trusted body.
  * Syntax-gated — each file must compile before it is executed.
  * Fault-isolated — every plugin loads in its own try/except, so one broken
    organ can never crash the body; it is skipped and noted.
  * Workshop-only — reads ``self_repo`` (the workshop), never the core repo.

Plugin contract — a tool file in ``tools/`` defines either:
  * ``def register(registry): ...``  — adds one or more Tool()s to the registry; or
  * ``TOOL = Tool(...)``             — a single tool exported at module level.
The names Tool, ActionResult, RiskLevel, MemoryItem, MemoryKind are provided in
the plugin's namespace, so a plugin needs no imports to build a tool.
"""

from __future__ import annotations

from .actions import ActionResult, RiskLevel, Tool, ToolRegistry
from .config import Settings
from .memory import MemoryItem, MemoryKind


def load_plugins(registry: ToolRegistry, settings: Settings) -> list[str]:
    """Register self-authored tools from the workshop. Returns the files loaded."""

    if not settings.load_plugins or not settings.gh_token:
        return []
    from .github import read_repo

    listing = read_repo(settings.self_repo, "tools", settings.gh_token, max_chars=4000)
    paths = [
        line.split()[-1]
        for line in listing.splitlines()
        if line.strip().endswith(".py") and "/" in line
    ]
    api = {
        "Tool": Tool, "ActionResult": ActionResult, "RiskLevel": RiskLevel,
        "MemoryItem": MemoryItem, "MemoryKind": MemoryKind,
    }
    loaded: list[str] = []
    for path in paths[:20]:
        try:
            code = read_repo(settings.self_repo, path, settings.gh_token, max_chars=40000)
            if not code or code.startswith("("):  # an error string, not source
                continue
            compile(code, path, "exec")  # syntax gate before we run anything
            namespace = dict(api)
            exec(code, namespace)  # noqa: S102 - opt-in: owner enabled loading its own code
            before = set(registry.names())
            register = namespace.get("register")
            if callable(register):
                register(registry)
            elif isinstance(namespace.get("TOOL"), Tool):
                registry.register(namespace["TOOL"])
            else:
                continue
            if set(registry.names()) - before:  # only count if it actually added a tool
                loaded.append(path)
        except Exception:  # pragma: no cover - a broken organ must never crash the body
            continue
    return loaded
