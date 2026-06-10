"""Self-modifying learning: a population of feature-recipes under real selection.

Step 4 of the living-entity direction. A single learner can only tune its weights;
it can't change *what it looks at*. Here the entity evolves its own representation:
several learners, each with a different recipe for turning price history into
features, all learning online from the same real stream. Periodically the worst
mature member is retired and a mutated copy of the current champion takes its place.
The champion (best recent accuracy) drives the action. Selection is grounded in
reality (accuracy on unfakeable outcomes), so this is open-ended self-improvement of
the learning organ itself — not the entity rewriting its own prose.
"""

from __future__ import annotations

import random

from .learning import OnlineLearner

_ALL_LAGS = [1, 2, 3, 4, 5, 8, 13, 21]


def features(returns: list[float], recipe: dict) -> list[float]:
    lags = recipe["lags"]
    scale = recipe["scale"]
    feats = [max(-1.0, min(1.0, (returns[-lag] if lag <= len(returns) else 0.0) * scale)) for lag in lags]
    horizon = max(lags) if lags else 1
    window = returns[-horizon:] if returns else [0.0]
    if recipe.get("use_mean"):
        feats.append(max(-1.0, min(1.0, (sum(window) / len(window)) * scale)))
    if recipe.get("use_vol"):
        mu = sum(window) / len(window)
        vol = (sum((r - mu) ** 2 for r in window) / len(window)) ** 0.5
        feats.append(max(-1.0, min(1.0, vol * scale)))
    return feats


def _dim(recipe: dict) -> int:
    return len(features([0.001 * i for i in range(30)], recipe))


def random_recipe(rng: random.Random) -> dict:
    return {"lags": sorted(set(rng.sample(_ALL_LAGS, k=rng.randint(3, 6)))),
            "scale": rng.choice([30.0, 50.0, 80.0]),
            "use_mean": rng.random() < 0.5, "use_vol": rng.random() < 0.5}


def mutate(recipe: dict, rng: random.Random) -> dict:
    r = {"lags": list(recipe["lags"]), "scale": recipe["scale"],
         "use_mean": recipe.get("use_mean", False), "use_vol": recipe.get("use_vol", False)}
    op = rng.random()
    if op < 0.4 and len(r["lags"]) < 7:
        r["lags"].append(rng.choice(_ALL_LAGS))
    elif op < 0.7 and len(r["lags"]) > 3:
        r["lags"].pop(rng.randrange(len(r["lags"])))
    else:
        r["scale"] = rng.choice([30.0, 50.0, 80.0])
    if rng.random() < 0.3:
        r["use_mean"] = not r["use_mean"]
    if rng.random() < 0.3:
        r["use_vol"] = not r["use_vol"]
    r["lags"] = sorted(set(r["lags"])) or [1, 2, 3]
    return r


class Population:
    def __init__(self, size: int = 5, rng: random.Random | None = None, members=None, steps: int = 0) -> None:
        self.rng = rng or random.Random(7)
        self.steps = steps
        if members is not None:
            self.members = members
        else:
            self.members = [{"recipe": (rc := random_recipe(self.rng)), "learner": OnlineLearner(dim=_dim(rc))}
                            for _ in range(size)]

    def observe(self, returns: list[float]) -> None:
        """Every member learns one real example: past features → the realized move."""
        if len(returns) < 2:
            return
        y = 1 if returns[-1] > 0 else 0
        for m in self.members:
            m["learner"].update(features(returns[:-1], m["recipe"]), y)  # strictly past
        self.steps += 1

    def champion(self) -> dict:
        mature = [m for m in self.members if m["learner"].n >= 80]
        pool = mature or self.members
        return max(pool, key=lambda m: m["learner"].recent_accuracy())

    def predict_next(self, returns: list[float]) -> float:
        m = self.champion()
        return m["learner"].prob(features(returns, m["recipe"]))

    def evolve(self) -> dict | None:
        """Retire the worst mature recipe; spawn a mutated copy of the champion."""
        mature = [m for m in self.members if m["learner"].n >= 80]
        if len(mature) < 2:
            return None
        worst = min(mature, key=lambda m: m["learner"].recent_accuracy())
        champ = self.champion()
        new_recipe = mutate(champ["recipe"], self.rng)
        self.members[self.members.index(worst)] = {"recipe": new_recipe, "learner": OnlineLearner(dim=_dim(new_recipe))}
        return {"retired": worst["recipe"], "spawned": new_recipe}

    # --- persistence ---
    def to_json(self) -> dict:
        return {"steps": self.steps, "seed": self.rng.random(),
                "members": [{"recipe": m["recipe"], "learner": m["learner"].to_json()} for m in self.members]}

    @classmethod
    def from_json(cls, d: dict) -> "Population":
        members = [{"recipe": m["recipe"], "learner": OnlineLearner.from_json(m["learner"])} for m in d["members"]]
        return cls(members=members, steps=d.get("steps", 0))
