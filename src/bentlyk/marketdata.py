"""Real, verifiable grounding: live market prices (no API key, stdlib only).

The learnable component needs a real stream with checkable outcomes — not the
entity's own text. Price is exactly that: it moves, the next value is ground truth
within a minute, and nobody can fake it. We fetch recent 1-minute closes from a
public endpoint; everything degrades to None on any failure so the worker never
breaks if the network or the venue is unavailable.
"""

from __future__ import annotations

import json
import urllib.request

_SOURCES = [
    # (url builder, parser -> list of [open_time_ms, close_price])
    (lambda s: f"https://api.binance.com/api/v3/klines?symbol={s}&interval=1m&limit=60",
     lambda d: [[int(k[0]), float(k[4])] for k in d]),
    (lambda s: f"https://api.binance.us/api/v3/klines?symbol={s}&interval=1m&limit=60",
     lambda d: [[int(k[0]), float(k[4])] for k in d]),
]


def recent_closes(symbol: str = "BTCUSDT", timeout: float = 8.0) -> dict | None:
    """Return {"t": open_time of the latest CLOSED candle, "closes": [closed closes...]}.

    The still-forming last candle is dropped, so every value is final (no lookahead).
    """
    for build_url, parse in _SOURCES:
        try:
            req = urllib.request.Request(build_url(symbol), headers={"User-Agent": "bentlyk"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                rows = parse(json.loads(resp.read().decode()))
        except Exception:
            continue
        if len(rows) < 10:
            continue
        closed = rows[:-1]  # drop the in-progress candle
        return {"t": closed[-1][0], "closes": [c[1] for c in closed]}
    return None
