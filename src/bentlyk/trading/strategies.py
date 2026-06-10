"""Strategy library — each strategy maps a price history to a position series.

A strategy(prices, params) returns signals: a list aligned with prices where
signals[i] in {-1, 0, +1} is the position to HOLD for the return from i to i+1,
decided using ONLY prices[:i+1] (no lookahead — this is enforced by construction).
Pure stdlib so it is fully testable and cheap to run en masse on the worker.
"""

from __future__ import annotations

import math

Signals = list[int]


def _sma(prices: list[float], n: int, i: int) -> float:
    lo = max(0, i - n + 1)
    w = prices[lo:i + 1]
    return sum(w) / len(w)


def ma_cross(prices: list[float], params: dict) -> Signals:
    fast, slow = int(params.get("fast", 10)), int(params.get("slow", 30))
    sig = [0] * len(prices)
    for i in range(len(prices)):
        if i < slow:
            continue
        sig[i] = 1 if _sma(prices, fast, i) > _sma(prices, slow, i) else -1
    return sig


def momentum(prices: list[float], params: dict) -> Signals:
    lb = int(params.get("lookback", 20))
    sig = [0] * len(prices)
    for i in range(lb, len(prices)):
        sig[i] = 1 if prices[i] > prices[i - lb] else -1
    return sig


def mean_revert(prices: list[float], params: dict) -> Signals:
    lb = int(params.get("lookback", 20))
    z = float(params.get("z", 1.0))
    sig = [0] * len(prices)
    for i in range(lb, len(prices)):
        w = prices[i - lb + 1:i + 1]
        mu = sum(w) / len(w)
        sd = (sum((x - mu) ** 2 for x in w) / len(w)) ** 0.5
        if sd <= 0:
            continue
        zi = (prices[i] - mu) / sd
        sig[i] = -1 if zi > z else (1 if zi < -z else 0)  # fade extremes
    return sig


def breakout(prices: list[float], params: dict) -> Signals:
    lb = int(params.get("lookback", 20))
    sig = [0] * len(prices)
    for i in range(lb, len(prices)):
        w = prices[i - lb:i]  # window BEFORE today
        hi, lo = max(w), min(w)
        sig[i] = 1 if prices[i] >= hi else (-1 if prices[i] <= lo else sig[i - 1])
    return sig


def pairs_spread(prices_a: list[float], prices_b: list[float], params: dict) -> Signals:
    """Trade convergence of a normalized spread between two correlated series.
    Returns a signal on A (the inverse applies to B)."""
    lb = int(params.get("lookback", 30))
    z = float(params.get("z", 1.2))
    n = min(len(prices_a), len(prices_b))
    la = [math.log(p) for p in prices_a[:n]]
    lb_ = [math.log(p) for p in prices_b[:n]]
    spread = [la[i] - lb_[i] for i in range(n)]
    sig = [0] * n
    for i in range(lb, n):
        w = spread[i - lb + 1:i + 1]
        mu = sum(w) / len(w)
        sd = (sum((x - mu) ** 2 for x in w) / len(w)) ** 0.5
        if sd <= 0:
            continue
        zi = (spread[i] - mu) / sd
        sig[i] = -1 if zi > z else (1 if zi < -z else 0)  # spread wide → expect convergence
    return sig


# Single-instrument strategies with sane parameter grids for the mass search.
REGISTRY: dict[str, tuple] = {
    "ma_cross": (ma_cross, [{"fast": f, "slow": s} for f in (5, 10, 20) for s in (30, 50, 100) if f < s]),
    "momentum": (momentum, [{"lookback": lb} for lb in (10, 20, 40, 80)]),
    "mean_revert": (mean_revert, [{"lookback": lb, "z": z} for lb in (10, 20, 40) for z in (1.0, 1.5, 2.0)]),
    "breakout": (breakout, [{"lookback": lb} for lb in (10, 20, 55)]),
}
