"""An evolving colony of live paper-trading agents — learning the only honest way.

No backtests, no Sharpe fantasy. Hundreds of tiny traders, each with its own genome
(a policy over live market features), all trade FORWARD on the real stream in paper
money. Fitness is the equity they actually earn going forward — unfakeable. A genetic
algorithm kills the worst each generation and breeds the best. Every winning trade
logs the market CONTEXT (and direction) it happened in, so patterns() mines "under
what conditions do wins occur"; evolve() then SEEDS new genomes toward that pattern —
the colony searches for the same winning conditions again. The champion's trades and
the colony's equity are logged for the interface. Pure stdlib.
"""

from __future__ import annotations

import random

# Features encode the elementary structure of a price move — the phases the trader's
# own theory names: is the trend ACCELERATING and CONTINUING, or DECELERATING and
# turning over? Each is a real, lookahead-free measurement from the return stream,
# clipped to [-1, 1]. The colony's genetic search learns which combinations precede
# forward profit; we only supply honest structural signal, not a verdict.
#
#   mom_fast  immediate push        — mean of the last 3 bars (where price is going now)
#   mom_slow  established trend      — mean of the last 12 bars (the prevailing direction)
#   accel     curvature             — is the push speeding up (+) or stalling (-)? continuation vs deceleration
#   persist   cleanliness of trend  — net directional agreement of recent bars; high = orderly trend, ~0 = chop
#   pullback  retracement structure — shallow counter-move in trend (+, continuation) vs deep give-back (-, reversal)
#   stretch   exhaustion            — distance from short mean in vol units; extreme = stretched, reversal risk
#   volx      regime                — short vol vs long vol: expansion (+, impulse/breakout) vs compression (-)
FEATURES = ["mom_fast", "mom_slow", "accel", "persist", "pullback", "stretch", "volx"]
DIM = len(FEATURES)


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def features(returns: list[float]) -> list[float]:
    r = returns or [0.0]
    n = len(r)

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    fast = mean(r[-3:])
    slow = mean(r[-12:])
    prev = mean(r[-6:-3]) if n >= 6 else fast          # the push just before the latest one
    accel = fast - prev                                 # curvature: momentum of momentum

    win = r[-10:]                                        # cleanliness of the recent trend
    persist = sum(1 if x > 0 else (-1 if x < 0 else 0) for x in win) / max(1, len(win))

    # Reconstruct the recent price path to read retracement and stretch — structure, not just speed.
    path = [1.0]
    for x in r[-20:]:
        path.append(path[-1] * (1.0 + x))
    hi, lo, last = max(path), min(path), path[-1]
    span = (hi - lo) or 1e-9
    trend_sign = 1.0 if slow > 0 else (-1.0 if slow < 0 else 0.0)
    if trend_sign >= 0:                                 # in an uptrend a shallow dip from the high = continuation
        retr = (hi - last) / span
    else:                                               # in a downtrend a shallow bounce from the low = continuation
        retr = (last - lo) / span
    pullback = trend_sign * (1.0 - 2.0 * retr)          # +: shallow/aligned (continuation)  −: deep give-back (reversal)

    mu = mean(path)
    sd = (sum((p - mu) ** 2 for p in path) / len(path)) ** 0.5
    stretch = (last - mu) / (sd + 1e-9)                 # how far stretched from the mean (exhaustion)

    def vol(xs):
        m = mean(xs)
        return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5 if xs else 0.0

    vshort, vlong = vol(r[-5:]), vol(r[-20:])
    volx = vshort / (vlong + 1e-9) - 1.0                 # >0 expansion (impulse)  <0 compression (coil)

    return [_clip(fast * 200), _clip(slow * 120), _clip(accel * 300),
            _clip(persist), _clip(pullback), _clip(stretch / 3.0), _clip(volx)]


class Trader:
    def __init__(self, w=None, thr: float = 0.3, rng: random.Random | None = None) -> None:
        r = rng or random.Random()
        self.w = w if w is not None else [r.uniform(-1, 1) for _ in range(DIM)]
        self.thr = thr
        self.equity = 1.0
        self.pos = 0
        self.last_f: list[float] | None = None
        self.trades = 0
        self.wins = 0
        self.last_pnl = 0.0
        self.last_dir = 0

    def step(self, f_now: list[float], r_last: float):
        won = None
        realized = self.pos
        if realized != 0:
            pnl = realized * r_last
            self.equity *= (1.0 + pnl)
            self.trades += 1
            self.last_pnl, self.last_dir = pnl, realized
            if pnl > 0:
                self.wins += 1
                won = (self.last_f, realized)
        else:
            self.last_pnl, self.last_dir = 0.0, 0
        s = sum(wi * fi for wi, fi in zip(self.w, f_now))
        self.pos = 1 if s > self.thr else (-1 if s < -self.thr else 0)
        self.last_f = f_now
        return won


def _breed(a: Trader, b: Trader, rng: random.Random) -> Trader:
    w = [(a.w[i] if rng.random() < 0.5 else b.w[i]) for i in range(DIM)]
    for i in range(DIM):
        if rng.random() < 0.25:
            w[i] = max(-2.0, min(2.0, w[i] + rng.gauss(0, 0.3)))
    thr = (a.thr + b.thr) / 2 + (rng.gauss(0, 0.05) if rng.random() < 0.3 else 0)
    return Trader(w=w, thr=max(0.05, min(0.9, thr)), rng=rng)


class Colony:
    def __init__(self, size: int = 150, rng: random.Random | None = None, traders=None,
                 winners=None, steps: int = 0, gen: int = 0, history=None, feed=None) -> None:
        self.rng = rng or random.Random(11)
        self.steps, self.gen = steps, gen
        self.traders = traders if traders is not None else [Trader(rng=self.rng) for _ in range(size)]
        self.winners: list = winners or []        # (context, direction) of winning trades
        self.history: list = history or []         # median equity over time (the curve)
        self.feed: list = feed or []               # champion's recent realized trades

    def step(self, returns: list[float]) -> None:
        if len(returns) < 2:
            return
        f = features(returns)
        r_last = returns[-1]
        for t in self.traders:
            won = t.step(f, r_last)
            if won is not None and won[0] is not None:
                self.winners.append(won)
        self.winners = self.winners[-400:]
        champ = self.best()
        if champ.last_pnl != 0:
            self.feed.append({"g": self.gen, "s": self.steps, "dir": champ.last_dir,
                              "pnl": round(champ.last_pnl * 100, 3)})
            self.feed = self.feed[-40:]
        eqs = sorted((t.equity for t in self.traders), reverse=True)
        self.history.append(round(eqs[len(eqs) // 2], 4) if eqs else 1.0)
        self.history = self.history[-160:]
        self.steps += 1

    def _pattern_seed(self):
        """A genome biased toward the mined winning pattern (centroid × winning direction)."""
        if len(self.winners) < 20:
            return None
        n = len(self.winners)
        centroid = [sum(w[0][i] for w in self.winners) / n for i in range(DIM)]
        avg_dir = sum(w[1] for w in self.winners) / n
        scale = 1.5 if avg_dir >= 0 else -1.5
        return [c * scale for c in centroid]

    def evolve(self, kill_frac: float = 0.4) -> None:
        self.traders.sort(key=lambda t: t.equity, reverse=True)
        n = len(self.traders)
        survivors = self.traders[: max(2, int(n * (1 - kill_frac)))]
        elite = survivors[: max(2, n // 5)]
        seed = self._pattern_seed()
        children = []
        while len(survivors) + len(children) < n:
            if seed is not None and self.rng.random() < 0.3:   # search the winning conditions again
                w = [x * self.rng.uniform(0.4, 1.6) for x in seed]
                children.append(Trader(w=w, thr=self.rng.uniform(0.1, 0.4), rng=self.rng))
            else:
                a, b = self.rng.choice(elite), self.rng.choice(elite)
                children.append(_breed(a, b, self.rng))
        self.traders = survivors + children
        for t in self.traders:
            t.equity = 1.0
        self.gen += 1

    def best(self) -> Trader:
        return max(self.traders, key=lambda t: t.equity)

    def patterns(self) -> dict:
        if len(self.winners) < 20:
            return {}
        n = len(self.winners)
        d = {FEATURES[i]: round(sum(w[0][i] for w in self.winners) / n, 3) for i in range(DIM)}
        d["dir"] = round(sum(w[1] for w in self.winners) / n, 2)
        return d

    def stats(self) -> dict:
        eqs = sorted((t.equity for t in self.traders), reverse=True)
        tw = sum(t.wins for t in self.traders)
        tt = sum(t.trades for t in self.traders)
        b = self.best()
        return {"pop": len(self.traders), "gen": self.gen, "steps": self.steps,
                "best_equity": round(eqs[0], 4) if eqs else 1.0,
                "median_equity": round(eqs[len(eqs) // 2], 4) if eqs else 1.0,
                "winrate": round(tw / tt, 3) if tt else 0.0,
                "winners_logged": len(self.winners),
                "best_genome": {FEATURES[i]: round(b.w[i], 2) for i in range(DIM)},
                "pattern": self.patterns(), "history": self.history[-120:], "feed": self.feed[-20:]}

    def to_json(self) -> dict:
        return {"steps": self.steps, "gen": self.gen, "history": self.history[-160:], "feed": self.feed[-40:],
                "traders": [{"w": [round(x, 4) for x in t.w], "thr": round(t.thr, 4),
                             "equity": round(t.equity, 5), "pos": t.pos, "trades": t.trades, "wins": t.wins,
                             "f": ([round(x, 4) for x in t.last_f] if t.last_f else None)}
                            for t in self.traders],
                "winners": [[[round(x, 3) for x in w[0]], w[1]] for w in self.winners[-300:] if w[0]]}

    @classmethod
    def from_json(cls, d: dict) -> "Colony":
        rng = random.Random()

        def fit(w):
            """Migrate a genome to the current DIM — keep learned weights, neutral-seed new features."""
            w = list(w)
            if len(w) < DIM:
                w = w + [rng.gauss(0, 0.1) for _ in range(DIM - len(w))]
            return w[:DIM]

        traders = []
        for td in d.get("traders", []):
            t = Trader(w=fit(td["w"]), thr=td["thr"])
            t.equity, t.pos, t.trades, t.wins = td.get("equity", 1.0), td.get("pos", 0), td.get("trades", 0), td.get("wins", 0)
            f = td.get("f")
            t.last_f = f if (f and len(f) == DIM) else None    # stale-dim context can't be scored; drop it
            traders.append(t)
        # Winning contexts from an older feature layout would corrupt centroid/seed math — keep only matching-dim ones.
        winners = [(w[0], w[1]) for w in d.get("winners", []) if w[0] and len(w[0]) == DIM]
        return cls(traders=traders, winners=winners, steps=d.get("steps", 0), gen=d.get("gen", 0),
                   history=d.get("history", []), feed=d.get("feed", []))
