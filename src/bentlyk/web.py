"""Web access for Bentlyk: search + page fetch (standard library only).

Search is provider-independent: keyless DuckDuckGo by default, or Tavily if a key
is configured — no dependency on the LLM provider. Page fetch is a guarded urllib
GET that strips HTML to text. Both degrade to a readable error string instead of
raising, so a web hiccup never breaks the loop.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request


def web_search(
    query: str, *, tavily_key: str = "", max_results: int = 5, timeout: float = 15.0
) -> str:
    """Provider-independent web search. Tavily if a key is set, else keyless DuckDuckGo."""

    query = (query or "").strip()
    if not query:
        return "(empty query)"
    try:
        if tavily_key:
            return _tavily(query, tavily_key, max_results, timeout)
        return _duckduckgo(query, max_results, timeout)
    except Exception as exc:  # pragma: no cover - network
        return f"(web search failed: {exc})"


def _tavily(query: str, key: str, max_results: int, timeout: float) -> str:
    body = json.dumps({
        "api_key": key, "query": query, "max_results": max_results,
        "include_answer": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    out = (data.get("answer") or "").strip()
    for r in (data.get("results") or [])[:max_results]:
        out += f"\n- {r.get('title', '')}: {(r.get('content') or '')[:200]} ({r.get('url', '')})"
    return out.strip() or "(no results)"


_DDG_RESULT = re.compile(
    r'result__a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'result__snippet[^>]*>(?P<snip>.*?)</a>',
    re.S | re.I,
)


def _duckduckgo(query: str, max_results: int, timeout: float) -> str:
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bentlyk)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    out = []
    for m in _DDG_RESULT.finditer(raw):
        href = html.unescape(m.group("url"))
        # DDG wraps links: //duckduckgo.com/l/?uddg=<encoded real url>
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        title = _ANYTAG.sub("", html.unescape(m.group("title"))).strip()
        snip = _ANYTAG.sub("", html.unescape(m.group("snip"))).strip()
        out.append(f"- {title}: {snip[:200]} ({href})")
        if len(out) >= max_results:
            break
    return "\n".join(out) if out else "(no results)"


def fetch_url(url: str, *, timeout: float = 15.0, max_chars: int = 6000) -> str:
    """GET a public URL and return readable text. Blocks local/internal targets."""

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "(refused: only http/https URLs)"
    if _is_internal(parsed.hostname):
        return "(refused: internal/private address)"
    req = urllib.request.Request(url, headers={"User-Agent": "bentlyk/1.0 (+https://bentlyk.vercel.app)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
        return f"(fetch failed: {exc})"
    if "html" in ctype or raw.lstrip().lower().startswith("<!doctype html") or "<html" in raw[:500].lower():
        raw = _html_to_text(raw)
    return raw.strip()[:max_chars] or "(empty page)"


def _is_internal(hostname: str) -> bool:
    if hostname in ("localhost",) or hostname.endswith(".local"):
        return True
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError):  # pragma: no cover - resolution failure
        return False
    return False


_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANYTAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n\s*\n\s*\n+")


def _html_to_text(raw: str) -> str:
    raw = _TAG.sub(" ", raw)
    raw = _ANYTAG.sub(" ", raw)
    raw = html.unescape(raw)
    raw = "\n".join(line.strip() for line in raw.splitlines())
    return _WS.sub("\n\n", raw)
