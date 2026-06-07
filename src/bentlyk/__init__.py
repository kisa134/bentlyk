"""bentlyk — a long-lived homeostatic companion agent.

A durable autonomous agent with a stable identity, regulated autonomy, layered
memory, internal drives, and a development cycle through reflection.

The eight layers:
    1. Perception        (events)
    2. Self Model        (self_model)
    3. Memory System     (memory)
    4. Homeostasis       (homeostasis)
    5. Goal Engine       (goals)
    6. Planner/Reasoner  (planner)
    7. Action Layer      (actions)
    8. Reflection/Sleep  (reflection)

wired together by :class:`bentlyk.agent.Agent`.
"""

from .agent import Agent, CycleResult
from .config import Settings
from .events import Event, EventKind, message, system, timer
from .self_model import DynamicState, IdentityCore

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "CycleResult",
    "Settings",
    "Event",
    "EventKind",
    "message",
    "timer",
    "system",
    "IdentityCore",
    "DynamicState",
    "__version__",
]
