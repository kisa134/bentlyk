"""A real learnable component — the first part of Bentlyk that actually CHANGES itself.

Everything else is a frozen LLM riffing over a notepad: the weights never move, so
the system can remember but never *become*. This is different. It is a small online
classifier (logistic regression trained by stochastic gradient descent) whose weights
genuinely update from each real outcome it sees. Pure stdlib, no GPU — it runs in the
worker and its state persists, so its learning accumulates across the entity's whole
life, not just one process.

It is deliberately falsifiable: on a stream with real structure its accuracy must rise
above chance; on pure noise it must stay at ~0.5. If it can't do that, the plasticity is
fake and we should know. ``selftest()`` checks exactly this.
"""

from __future__ import annotations

import json
import math


def _sigmoid(z: float) -> float:
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


class OnlineLearner:
    """Online logistic regression. predict() then update() = learn from one real example."""

    def __init__(self, dim: int = 6, lr: float = 0.08) -> None:
        self.dim = dim
        self.lr = lr
        self.w = [0.0] * dim
        self.b = 0.0
        self.n = 0          # total examples ever seen
        self.correct = 0    # lifetime correct predictions
        self.recent: list[int] = []  # rolling window of hits (for current skill, not lifetime)

    # --- inference ---
    def _z(self, x: list[float]) -> float:
        return self.b + sum(wi * xi for wi, xi in zip(self.w, x))

    def prob(self, x: list[float]) -> float:
        return _sigmoid(self._z(x))

    def predict(self, x: list[float]) -> int:
        return 1 if self.prob(x) >= 0.5 else 0

    # --- learning (the weights actually move here) ---
    def update(self, x: list[float], y: int) -> int:
        """Predict, score, then take a gradient step toward the truth. Returns hit (0/1)."""
        p = self.prob(x)
        hit = int((1 if p >= 0.5 else 0) == y)
        self.n += 1
        self.correct += hit
        self.recent.append(hit)
        if len(self.recent) > 200:
            self.recent = self.recent[-200:]
        err = y - p  # logistic gradient
        for i in range(self.dim):
            self.w[i] += self.lr * err * x[i]
        self.b += self.lr * err
        return hit

    # --- honest metrics ---
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    def recent_accuracy(self) -> float:
        return sum(self.recent) / len(self.recent) if self.recent else 0.0

    # --- persistence (so learning survives restarts = real continuity) ---
    def to_json(self) -> str:
        return json.dumps({"dim": self.dim, "lr": self.lr, "w": self.w, "b": self.b,
                           "n": self.n, "correct": self.correct, "recent": self.recent})

    @classmethod
    def from_json(cls, s: str) -> "OnlineLearner":
        d = json.loads(s)
        o = cls(dim=d["dim"], lr=d.get("lr", 0.08))
        o.w = d["w"]; o.b = d["b"]; o.n = d["n"]; o.correct = d["correct"]; o.recent = d.get("recent", [])
        return o


def features_from_returns(returns: list[float], dim: int = 6, scale: float = 50.0) -> list[float]:
    """Turn the last ``dim`` price returns into a feature vector (clipped, scaled)."""
    window = returns[-dim:]
    while len(window) < dim:
        window = [0.0] + window
    return [max(-1.0, min(1.0, r * scale)) for r in window]


def selftest() -> dict:
    """Prove the learning is real: it must learn structure and must NOT 'learn' noise."""
    import random
    random.seed(1)
    # 1) a learnable rule: y = 1 iff a hidden weighted sum of features is positive
    truth = [0.9, -0.7, 0.5, 0.0, 0.3, -0.4]
    L = OnlineLearner(dim=6, lr=0.1)
    for _ in range(4000):
        x = [random.uniform(-1, 1) for _ in range(6)]
        y = 1 if sum(t * xi for t, xi in zip(truth, x)) > 0 else 0
        L.update(x, y)
    learned = L.recent_accuracy()
    # 2) pure noise: label independent of features — must stay near chance
    Ln = OnlineLearner(dim=6, lr=0.1)
    for _ in range(4000):
        x = [random.uniform(-1, 1) for _ in range(6)]
        Ln.update(x, random.randint(0, 1))
    noise = Ln.recent_accuracy()
    return {"structure_acc": round(learned, 3), "noise_acc": round(noise, 3),
            "real_learning": learned > 0.8 and abs(noise - 0.5) < 0.12}
