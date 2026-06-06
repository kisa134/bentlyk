"""Reasoner backend.

A thin abstraction over the language model so the loop never imports a vendor
SDK directly. Two implementations:

* :class:`AnthropicReasoner` — real Claude calls (requires the ``llm`` extra and
  an API key).
* :class:`MockReasoner` — a deterministic, dependency-free stand-in so the whole
  agent runs, and tests pass, fully offline.

Both return plain text; structured callers ask for JSON and parse defensively.
"""

from __future__ import annotations

import json
from typing import Protocol


class Reasoner(Protocol):
    def complete(self, *, system: str, prompt: str, max_tokens: int = ...) -> str: ...


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


def build_reasoner(*, api_key: str, model: str) -> Reasoner:
    if api_key:
        return AnthropicReasoner(api_key=api_key, model=model)
    return MockReasoner()
