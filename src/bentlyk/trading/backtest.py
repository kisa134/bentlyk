"""Backtest engine + walk-forward validation.

A signal series is turned into an equity curve and honest metrics (Sharpe, max
drawdown, win-rate, trades), charging a fee on every position change. Walk-forward
is the anti-self-deception core: parameters are chosen on in-sample data and scored
ONLY on the following out-of-sample slice, so a strategy that merely overfits the
past scores zero where it counts.
"""

from __future__ import annotations

import math


def returns_from_prices(prices: list[float]) -> list[float]:
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1]]


def backtest(signals: list[int], prices: list[float], fee: float = 0.0006,
             periods_per_year: int = 365 * 24) -> dict:
    """signals[i] is the position held over the return prices[i]->prices[i+1]."""
    n = min(len(signals), len(prices) - 1)
    strat_returns: list[float] = []
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    wins = trades = 0
    prev_pos = 0
    exposure = 0
    for i in range(n):
        pos = signals[i]
        r = prices[i + 1] / prices[i] - 1.0 if prices[i] else 0.0
        cost = fee * abs(pos - prev_pos)
        pr = pos * r - cost
        strat_returns.append(pr)
        equity *= (1.0 + pr)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        if pos != prev_pos and pos != 0:
            trades += 1
        if pos != 0:
            exposure += 1
            if pr > 0:
                wins += 1
        prev_pos = pos
    m = len(strat_returns)
    mean = sum(strat_returns) / m if m else 0.0
    var = sum((x - mean) ** 2 for x in strat_returns) / m if m else 0.0
    sd = var ** 0.5
    sharpe = (mean / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0
    return {
        "total_return": round(equity - 1.0, 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(wins / exposure, 3) if exposure else 0.0,
        "trades": trades,
        "exposure": round(exposure / m, 3) if m else 0.0,
        "bars": m,
    }


def walk_forward(prices: list[float], strategy, param_grid: list[dict],
                 folds: int = 4, fee: float = 0.0006) -> dict:
    """Choose params on each in-sample block, score on the next out-of-sample block,
    and aggregate the OUT-OF-SAMPLE results. This is the number that matters."""
    n = len(prices)
    if n < 200 or folds < 2:
        return {"oos_sharpe": 0.0, "oos_return": 0.0, "oos_trades": 0, "valid": False}
    block = n // (folds + 1)
    oos_returns_concat: list[float] = []
    oos_trades = 0
    chosen = []
    for k in range(folds):
        tr_end = block * (k + 1)
        te_end = min(block * (k + 2), n)
        train = prices[:tr_end]
        test = prices[tr_end - 1:te_end]  # overlap one bar so signals align with first test return
        # pick best params on training by in-sample Sharpe
        best, best_sh = None, -1e9
        for p in param_grid:
            res = backtest(strategy(train, p), train, fee)
            if res["sharpe"] > best_sh:
                best_sh, best = res["sharpe"], p
        if best is None:
            continue
        chosen.append(best)
        # score chosen params on the unseen test block
        sig = strategy(test, best)
        res = backtest(sig, test, fee)
        oos_trades += res["trades"]
        # rebuild the per-bar OOS returns to compute an aggregate Sharpe honestly
        for i in range(min(len(sig), len(test) - 1)):
            r = test[i + 1] / test[i] - 1.0 if test[i] else 0.0
            oos_returns_concat.append(sig[i] * r)
    m = len(oos_returns_concat)
    if m == 0:
        return {"oos_sharpe": 0.0, "oos_return": 0.0, "oos_trades": 0, "valid": False}
    mean = sum(oos_returns_concat) / m
    sd = (sum((x - mean) ** 2 for x in oos_returns_concat) / m) ** 0.5
    sharpe = (mean / sd * math.sqrt(365 * 24)) if sd > 0 else 0.0
    eq = 1.0
    for r in oos_returns_concat:
        eq *= (1.0 + r)
    return {"oos_sharpe": round(sharpe, 3), "oos_return": round(eq - 1.0, 4),
            "oos_trades": oos_trades, "valid": True, "params": chosen[-1] if chosen else {}}
