"""An evolving colony of live paper-trading agents — learning the only honest way.

No backtests, no Sharpe fantasy. Hundreds of tiny traders, each with its own genome
(a policy over live market features), all trade FORWARD on the real stream in paper
money. Their fitness is the equity they actually earn going forward — unfakeable,
walk-forward by construction. A genetic algorithm kills the worst each generation and
breeds the best (crossover + mutation). And every winning trade logs the market
CONTEXT it happened in, so we can mine: under what conditions do wins occur? Those
mined patterns are themselves re-validated forward — luck decays, real edge persists.

This is the AI advantage applied honestly: online learning on real market activity.
Pure stdlib; a few hundred traders cost almost nothing per step.
"""

from __future__ import annotations

import random

FEATURES = ["mom5", "mom20", "last", "zscore", "vol"]
DIM = len(FEATURES)


def features(returns: list[float]) -> list[float]:
    """Compress recent live returns into a fixed, scaled feature vector in ~[-1,1]."""
    def clip(x):
        return max(-1.0, min(1.0, x))
    w20 = returns[-20:] if len(returns) >= 1 else [0.0]
    mu = sum(w20) / len(w20)
    vol = (sum((r - mu) ** 2 for r in w20) / len(w20)) ** 0.5
    last = returns[-1] if returns else 0.0
    return [
        clip(sum(returns[-5:]) * 40),
        clip(sum(w20) * 15),
        clip(last * 120),
        clip((last - mu) / (vol + 1e-9) / 3.0),
        clip(vol * 200),
    ]


class Trader:
    """A genome = weights over features + an entry threshold. Holds a paper wallet."""

    def __init__(self, w=None, thr: float = 0.3, rng: random.Random | None = None) -> None:
        r = rng or random.Random()
        self.w = w if w is not None else [r.uniform(-1, 1) for _ in range(DIM)]
        self.thr = thr
        self.equity = 1.0
        self.pos = 0
        self.last_f: list[float] | None = None
        self.trades = 0
        self.wins = 0

    def step(self, f_now: list[float], r_last: float):
        """Realize the position held since last step, then decide the next one.
        Returns the entry context if the just-closed trade was a winner, else None."""
        won_context = None
        if self.pos != 0:
            pnl = self.pos * r_last
            self.equity *= (1.0 + pnl)
            self.trades += 1
            if pnl > 0:
                self.wins += 1
                won_context = self.last_f
        s = sum(wi * fi for wi, fi in zip(self.w, f_now))
        self.pos = 1 if s > self.thr else (-1 if s < -self.thr else 0)
        self.last_f = f_now
        return won_context


def _breed(a: Trader, b: Trader, rng: random.Random) -> Trader:
    w = [(a.w[i] if rng.random() < 0.5 else b.w[i]) for i in range(DIM)]  # crossover
    for i in range(DIM):
        if rng.random() < 0.25:
            w[i] += rng.gauss(0, 0.3)                                     # mutation
            w[i] = max(-2.0, min(2.0, w[i]))
    thr = (a.thr + b.thr) / 2 + (rng.gauss(0, 0.05) if rng.random() < 0.3 else 0)
    return Trader(w=w, thr=max(0.05, min(0.9, thr)), rng=rng)


class Colony:
    def __init__(self, size: int = 150, rng: random.Random | None = None,
                 traders=None, winners=None, steps: int = 0, gen: int = 0) -> None:
        self.rng = rng or random.Random(11)
        self.steps = steps
        self.gen = gen
        self.traders = traders if traders is not None else [Trader(rng=self.rng) for _ in range(size)]
        self.winners: list[list[float]] = winners or []

    def step(self, returns: list[float]) -> None:
        if len(returns) < 2:
            return
        f = features(returns)
        r_last = returns[-1]
        for t in self.traders:
            ctx = t.step(f, r_last)
            if ctx is not None:
                self.winners.append(ctx)
        if len(self.winners) > 400:
            self.winners = self.winners[-400:]
        self.steps += 1

    def evolve(self, kill_frac: float = 0.4) -> None:
        """Forward selection: rank by equity earned THIS generation, kill the worst,
        breed the best, then reset equity so the next generation is judged fresh."""
        self.traders.sort(key=lambda t: t.equity, reverse=True)
        n = len(self.traders)
        survivors = self.traders[: max(2, int(n * (1 - kill_frac)))]
        elite = survivors[: max(2, n // 5)]
        children = []
        while len(survivors) + len(children) < n:
            a, b = self.rng.choice(elite), self.rng.choice(elite)
            children.append(_breed(a, b, self.rng))
        self.traders = survivors + children
        for t in self.traders:                # fresh forward evaluation next generation
            t.equity = 1.0
        self.gen += 1

    def best(self) -> Trader:
        return max(self.traders, key=lambda t: t.equity)

    def stats(self) -> dict:
        eqs = sorted((t.equity for t in self.traders), reverse=True)
        med = eqs[len(eqs) // 2] if eqs else 1.0
        tw = sum(t.wins for t in self.traders)
        tt = sum(t.trades for t in self.traders)
        return {"pop": len(self.traders), "gen": self.gen, "steps": self.steps,
                "best_equity": round(eqs[0], 4) if eqs else 1.0,
                "median_equity": round(med, 4),
                "winrate": round(tw / tt, 3) if tt else 0.0,
                "winners_logged": len(self.winners),
                "pattern": self.patterns()}

    def patterns(self) -> dict:
        """Mine the market context of winning trades: the average feature vector of wins.
        This is 'under what conditions did successes happen' — itself re-validated forward."""
        if len(self.winners) < 20:
            return {}
        n = len(self.winners)
        centroid = [sum(v[i] for v in self.winners) / n for i in range(DIM)]
        return {FEATURES[i]: round(centroid[i], 3) for i in range(DIM)}

    # --- persistence ---
    def to_json(self) -> dict:
        return {"steps": self.steps, "gen": self.gen,
                "traders": [{"w": [round(x, 4) for x in t.w], "thr": round(t.thr, 4),
                             "equity": round(t.equity, 5), "pos": t.pos,
                             "trades": t.trades, "wins": t.wins} for t in self.traders],
                "winners": [[round(x, 3) for x in v] for v in self.winners[-300:]]}

    @classmethod
    def from_json(cls, d: dict) -> "Colony":
        traders = []
        for td in d.get("traders", []):
            t = Trader(w=td["w"], thr=td["thr"])
            t.equity, t.pos, t.trades, t.wins = td.get("equity", 1.0), td.get("pos", 0), td.get("trades", 0), td.get("wins", 0)
            traders.append(t)
        return cls(traders=traders, winners=d.get("winners", []), steps=d.get("steps", 0), gen=d.get("gen", 0))
