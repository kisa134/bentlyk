"""Bentlyk's systematic trading research engine (worker-only).

Pure-stdlib analytics (strategies, backtest, walk-forward, mass research) plus an
optional ccxt-backed data layer. Nothing here is imported by the lightweight Vercel
functions — it lives on the always-on worker, which can carry the ccxt dependency.
"""

from .backtest import backtest, walk_forward
from .research import evaluate, mass_research
from .strategies import REGISTRY

__all__ = ["backtest", "walk_forward", "evaluate", "mass_research", "REGISTRY"]
