"""Market data via ccxt — real history and live candles across many instruments.

Optional dependency: if ccxt isn't installed or the venue is unreachable, every
function degrades to None/{} so the worker never breaks. Runs only on the worker.
"""

from __future__ import annotations


def _exchange(name: str = "binance"):
    try:
        import ccxt  # type: ignore
    except Exception:
        return None
    try:
        ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 15000})
        return ex
    except Exception:
        return None


def top_symbols(name: str = "binance", quote: str = "USDT", limit: int = 30) -> list[str]:
    """The most liquid spot symbols against ``quote`` — a real universe to scan."""
    ex = _exchange(name)
    if ex is None:
        return []
    try:
        ex.load_markets()
        tickers = ex.fetch_tickers()
    except Exception:
        return []
    rows = []
    for sym, t in tickers.items():
        if sym.endswith("/" + quote) and ":" not in sym:
            vol = (t.get("quoteVolume") or 0)
            rows.append((vol, sym))
    rows.sort(reverse=True)
    return [s for _, s in rows[:limit]]


def history(symbols: list[str], timeframe: str = "1h", limit: int = 720,
            name: str = "binance") -> dict[str, list[float]]:
    """symbol -> list of closing prices (oldest→newest). ~720 1h bars ≈ 30 days."""
    ex = _exchange(name)
    if ex is None:
        return {}
    out: dict[str, list[float]] = {}
    for sym in symbols:
        try:
            ohlcv = ex.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
            closes = [float(c[4]) for c in ohlcv if c and c[4]]
            if len(closes) >= 100:
                out[sym] = closes
        except Exception:
            continue
    return out
