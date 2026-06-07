"""Reasoner backend.

A thin abstraction over the language model so the loop never imports a vendor
SDK directly. Three implementations:

* :class:`OpenAICompatReasoner` — any OpenAI-compatible chat endpoint
  (OpenRouter by default), over the standard library only — no SDK, so it stays
  light enough for serverless cold starts and lets you pick any model.
* :class:`AnthropicReasoner` — native Claude calls (requires the ``llm`` extra).
* :class:`MockReasoner` — a deterministic, dependency-free stand-in so the whole
  agent runs, and tests pass, fully offline.

Both return plain text; structured callers ask for JSON and parse defensively.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Settings


class ReasonerError(RuntimeError):
    """Raised when a live reasoner call fails (network, auth, bad model)."""


class Reasoner(Protocol):
    def complete(self, *, system: str, prompt: str, max_tokens: int = ...) -> str: ...


class OpenAICompatReasoner:
    """OpenAI-compatible chat completions over urllib (e.g. OpenRouter).

    Dependency-free on purpose: a serverless function can import it without
    pulling a vendor SDK, and any provider/model exposing the OpenAI chat schema
    works by changing ``base_url`` + ``model``.
    """

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # OpenRouter attribution headers (optional, harmless elsewhere).
                "HTTP-Referer": "https://github.com/kisa134/bentlyk",
                "X-Title": "bentlyk",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode(errors="replace")[:500]
            raise ReasonerError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            raise ReasonerError(f"LLM unreachable: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover
            raise ReasonerError(f"unexpected LLM response shape: {data}") from exc


class AnthropicReasoner:
    """Real Claude backend. Imported lazily so the core stays dependency-free."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional path
            raise RuntimeError(
                "anthropic SDK not installed; `pip install bentlyk[llm]` or run offline."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()


class MockReasoner:
    """Deterministic offline reasoner.

    It does not understand language, but it produces well-formed, plausible
    output so every layer above it is exercisable without a network. Where a
    caller requests JSON, it returns valid JSON.
    """

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        low = prompt.lower()
        if "respond with json" in low or "json object" in low:
            return self._json_reply(prompt)
        # A reflective, non-committal natural reply that echoes the situation.
        head = prompt.strip().splitlines()[0] if prompt.strip() else ""
        return (
            "[offline reasoner] I've registered the situation"
            + (f' around "{head[:80]}"' if head else "")
            + ". With a live model I'd reason here; for now I'm staying within bounds "
            "and keeping my state coherent."
        )

    def _json_reply(self, prompt: str) -> str:
        # The planner's prompt embeds "CAUTION: x" and "uncertainty=y"; key off
        # the actual numbers so offline behaviour mirrors the real decision shape.
        low = prompt.lower()
        if "decision" in low and "tool_args" in low:
            uncertainty = _read_float(prompt, "uncertainty=", 0.3)
            caution = _read_float(prompt, "caution:", 0.3)
            if uncertainty > 0.55:
                return json.dumps(
                    {
                        "decision": "ask",
                        "rationale": "offline: goal too uncertain to act on alone",
                        "message": "I'd like a bit more direction before I act on this.",
                        "plan": ["clarify intent"],
                    }
                )
            if caution > 0.5:
                return json.dumps(
                    {
                        "decision": "think",
                        "rationale": "offline: caution high, deliberating before acting",
                        "plan": ["re-read the goal", "retrieve relevant memory"],
                    }
                )
            # Low caution + low uncertainty: take a safe, reversible step.
            return json.dumps(
                {
                    "decision": "act",
                    "rationale": "offline: taking one safe, reversible step",
                    "tool": "reflect",
                    "tool_args": {"note": "advancing the current goal"},
                    "plan": ["take one safe step", "record the outcome"],
                }
            )
        return json.dumps({"ok": True})


def _read_float(text: str, marker: str, default: float) -> float:
    idx = text.lower().find(marker.lower())
    if idx < 0:
        return default
    tail = text[idx + len(marker) :].lstrip()
    num = ""
    for ch in tail:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            break
    try:
        return float(num)
    except ValueError:
        return default


class FallbackReasoner:
    """Try reasoners in order; use the next if one fails (e.g. a bad model slug)."""

    def __init__(self, reasoners: list[Reasoner]) -> None:
        self._reasoners = [r for r in reasoners if r is not None]

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        last: Exception | None = None
        for r in self._reasoners:
            try:
                return r.complete(system=system, prompt=prompt, max_tokens=max_tokens)
            except Exception as exc:  # pragma: no cover - network path
                last = exc
        raise last if last else ReasonerError("no reasoners configured")


def build_reasoner(settings: "Settings", *, model: str | None = None) -> Reasoner:
    """Pick a reasoner from settings. ``model`` overrides (e.g. reason/reflection)."""

    chosen = model or settings.model
    if settings.provider == "openrouter":
        primary = OpenAICompatReasoner(
            api_key=settings.openrouter_api_key, model=chosen, base_url=settings.llm_base_url
        )
        if settings.fallback_model and settings.fallback_model != chosen:
            fallback = OpenAICompatReasoner(
                api_key=settings.openrouter_api_key,
                model=settings.fallback_model,
                base_url=settings.llm_base_url,
            )
            return FallbackReasoner([primary, fallback])
        return primary
    if settings.provider == "anthropic":
        return AnthropicReasoner(api_key=settings.anthropic_api_key, model=chosen)
    return MockReasoner()
