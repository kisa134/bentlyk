"""Tools, actions, and the registry.

A :class:`Tool` is a capability the agent can invoke. Each declares its risk and
reversibility so the permission gate can reason about it *before* it runs. An
:class:`Action` is a concrete invocation; an :class:`ActionResult` is its
outcome (with a ``surprise`` signal fed back into homeostasis).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .permissions import RiskLevel


@dataclass(slots=True)
class Action:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ActionResult:
    ok: bool
    output: str
    surprise: float = 0.0  # how much the outcome diverged from expectation, [0,1]


# A tool handler receives the action args and a context dict (store, state, ...).
ToolHandler = Callable[[dict[str, Any], dict[str, Any]], ActionResult]


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    risk: RiskLevel
    reversible: bool
    handler: ToolHandler

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> ActionResult:
        return self.handler(args, context)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        return "\n".join(
            f"- {t.name} (risk={t.risk.name.lower()}, "
            f"{'reversible' if t.reversible else 'irreversible'}): {t.description}"
            for t in self._tools.values()
        )


def default_registry() -> ToolRegistry:
    """Built-in tool set. Import here to avoid a circular import at module load."""

    from .tools import build_builtin_tools

    reg = ToolRegistry()
    for tool in build_builtin_tools():
        reg.register(tool)
    return reg
