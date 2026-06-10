"""Mass research: run the whole strategy library across a universe and rank by the
out-of-sample result, so only strategies that survive unseen data float to the top.
"""

from __future__ import annotations

from .backtest import walk_forward
from .strategies import REGISTRY


def evaluate(prices: list[float], strategy_name: str) -> dict | None:
    entry = REGISTRY.get(strategy_name)
    if entry is None or len(prices) < 250:
        return None
    strategy, grid = entry
    return walk_forward(prices, strategy, grid)


def mass_research(data: dict[str, list[float]], min_bars: int = 250) -> list[dict]:
    """data: symbol -> price history. Returns a leaderboard sorted by OOS Sharpe."""
    board: list[dict] = []
    for symbol, prices in data.items():
        if len(prices) < min_bars:
            continue
        for name, (strategy, grid) in REGISTRY.items():
            res = walk_forward(prices, strategy, grid)
            if res.get("valid"):
                board.append({
                    "symbol": symbol, "strategy": name,
                    "oos_sharpe": res["oos_sharpe"], "oos_return": res["oos_return"],
                    "oos_trades": res["oos_trades"], "params": res.get("params", {}),
                })
    board.sort(key=lambda r: r["oos_sharpe"], reverse=True)
    return board
