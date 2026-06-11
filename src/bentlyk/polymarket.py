"""Polymarket data layer — public read-only APIs (no keys, no wallet).

Three public services power the terminal and the agent's market reading:
  * Gamma  (gamma-api.polymarket.com)   — events, markets, categories, search
  * CLOB   (clob.polymarket.com)        — live prices, midpoints, price history
  * Data   (data-api.polymarket.com)    — positions, trades, holders (by address)

Everything degrades to [] / {} on any error so neither the terminal nor the worker
breaks if Polymarket is unreachable or geo-blocks the host. Stdlib only.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

_CRYPTO = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
_WINDOWS = ["5m", "15m", "1h"]


def _get(url: str, timeout: float = 10.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bentlyk-terminal", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _loads(v, default):
    """Gamma returns some fields as JSON-encoded strings."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return v if v is not None else default


def events(tag: str = "", limit: int = 40, closed: bool = False) -> list[dict]:
    """Active events, optionally filtered by tag slug (e.g. 'sports', 'crypto', 'politics')."""
    q = {"closed": str(closed).lower(), "limit": str(limit), "order": "volume24hr", "ascending": "false"}
    if tag:
        q["tag_slug"] = tag
    rows = _get(f"{GAMMA}/events?{urllib.parse.urlencode(q)}") or []
    out = []
    for e in rows if isinstance(rows, list) else []:
        markets = e.get("markets") or []
        out.append({
            "id": e.get("id"), "title": e.get("title") or e.get("question"),
            "slug": e.get("slug"), "category": (e.get("category") or "").lower(),
            "end": e.get("endDate"), "volume": e.get("volume24hr") or e.get("volume"),
            "markets": [{
                "question": m.get("question"), "slug": m.get("slug"),
                "outcomes": _loads(m.get("outcomes"), []),
                "prices": _loads(m.get("outcomePrices"), []),
                "token_ids": _loads(m.get("clobTokenIds"), []),
                "end": m.get("endDate"),
            } for m in markets][:6],
        })
    return out


def crypto_updown() -> list[dict]:
    """The short-term crypto Up/Down board (BTC/ETH/SOL/… across 5m/15m/1h windows).

    Resolves each market by its deterministic slug for the current window, reads Up/Down
    prices, the window end, and the start ('price to beat') reference where available.
    """
    now = int(time.time())
    board = []
    for asset in _CRYPTO:
        for win in _WINDOWS:
            secs = {"5m": 300, "15m": 900, "1h": 3600}[win]
            start = (now // secs) * secs
            slug = f"{asset}-updown-{win}-{start}"
            m = _get(f"{GAMMA}/markets?slug={slug}")
            m = (m[0] if isinstance(m, list) and m else None)
            if not m:
                continue
            prices = _loads(m.get("outcomePrices"), [])
            outcomes = _loads(m.get("outcomes"), [])
            tokens = _loads(m.get("clobTokenIds"), [])
            board.append({
                "asset": asset.upper(), "window": win, "slug": slug,
                "outcomes": outcomes, "prices": prices, "token_ids": tokens,
                "end": start + secs, "start": start,
                "up_price": _up_price(outcomes, prices),
            })
    return board


def _up_price(outcomes, prices) -> float | None:
    for o, p in zip(outcomes, prices):
        if str(o).lower() in ("up", "yes"):
            try:
                return float(p)
            except Exception:
                return None
    return None


def price_history(token_id: str, interval: str = "1m", points: int = 60) -> list[float]:
    """Recent traded prices for a CLOB token — a sparkline for the terminal chart."""
    data = _get(f"{CLOB}/prices-history?market={token_id}&interval={interval}&fidelity=1")
    pts = (data or {}).get("history") or []
    return [float(p.get("p")) for p in pts[-points:] if p.get("p") is not None]
