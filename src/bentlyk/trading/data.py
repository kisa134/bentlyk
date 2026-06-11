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


# A curated universe of liquid pairs. Hardcoded on purpose: fetching ALL exchange
# tickers (load_markets + fetch_tickers) is a huge payload that can hang/OOM a small
# worker. These are fetched one OHLCV call at a time, which is light and bounded.
_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "TRX/USDT", "DOT/USDT", "MATIC/USDT",
    "LTC/USDT", "BCH/USDT", "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT",
    "ATOM/USDT", "FIL/USDT", "INJ/USDT", "SUI/USDT", "TIA/USDT", "SEI/USDT",
]


def top_symbols(name: str = "binance", quote: str = "USDT", limit: int = 24) -> list[str]:
    """A curated, liquid universe — light and safe (no full-exchange ticker dump)."""
    return _UNIVERSE[:limit]


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
