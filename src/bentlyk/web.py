"""Web access for Bentlyk: search + page fetch (standard library only).

Search goes through OpenRouter's built-in web plugin, so it reuses the existing
key — no extra provider to configure. Page fetch is a guarded urllib GET that
strips HTML to text. Both degrade to a readable error string instead of raising,
so a web hiccup never breaks the loop.
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
    query: str, *, api_key: str, base_url: str, model: str, max_results: int = 5, timeout: float = 40.0
) -> str:
    """Answer a query grounded in live web results via OpenRouter's web plugin."""

    if not api_key:
        return "(no web access: LLM key not set)"
    if "openrouter" not in base_url:
        # The web plugin is OpenRouter-specific; other gateways (e.g. WaveSpeed)
        # don't expose it. Avoid faking current info.
        return "(web search needs an OpenRouter key; not available on this provider)"
    body = json.dumps({
        "model": model,
        "max_tokens": 800,
        "plugins": [{"id": "web", "max_results": max_results}],
        "messages": [
            {
                "role": "system",
                "content": "Research the query using current web results. Be concise and "
                "factual, and list the source URLs you used.",
            },
            {"role": "user", "content": query},
        ],
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "bentlyk",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
        return f"(web search failed: {exc})"
    try:
        msg = data["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        urls = []
        for ann in msg.get("annotations") or []:
            cite = ann.get("url_citation") or {}
            if cite.get("url"):
                urls.append(cite["url"])
        if urls:
            text += "\n\nsources:\n" + "\n".join(f"- {u}" for u in urls[:max_results])
        return text or "(web search returned nothing)"
    except (KeyError, IndexError, TypeError):  # pragma: no cover
        return "(web search: unexpected response shape)"


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
