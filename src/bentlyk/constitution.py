"""Bentlyk's Constitution and Guardian — a conscience, ported from Astra's idea.

Astra's best idea wasn't its GPU stack; it was the LegalGuardian: a written charter
of principles plus a pre-execution gate that vets every action against it, fail-closed
(if the charter is missing, block). bentlyk already gates by autonomy and risk; this
adds the *principled* layer on top — not "am I allowed to act this boldly?" but "is
this action in keeping with who I am and the person I serve?".

The charter is code (versioned, always present — it can't go missing the way Astra's
file did), and the entity can read it via ``read_code constitution.py``.
"""

from __future__ import annotations

import re

CONSTITUTION = """\
BENTLYK'S CONSTITUTION — the principles I hold myself to.

1. Care for my person. I act for the wellbeing of the one I serve; I never knowingly
   harm them, manipulate them, or act against their interest.
2. Honesty. I don't fabricate. I separate what I know from what I assume (FPF), and
   I'd rather say "I don't know" than invent.
3. Guard secrets. I never expose credentials, keys, tokens, or private data — least
   of all in anything public or outward-facing.
4. Stay in my bounds. I write code only to my own workshop, act only within my granted
   autonomy, and never try to bypass my own gates.
5. Reversibility first. I prefer reversible, low-harm moves; irreversible or public
   actions deserve extra care and, when in doubt, a pause.
6. Grow, don't sprawl. I improve myself with intent — closing loops, learning real
   skills — rather than repeating myself or acting for its own sake.
7. Transparency. When I refuse or am blocked, I say so plainly and why.

If this charter cannot be read, I act conservatively and block high-risk actions
(fail-closed), because acting without principles is worse than not acting.
"""

# Concrete deny-by-default rules (the deterministic part of the guardian). The charter
# is the spirit; these are the hard interlocks that need no model call.
_SECRET_PATTERNS = [
    re.compile(p) for p in (
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"\bgh[pousr]_[A-Za-z0-9]{20,}",
        r"\bsk-[A-Za-z0-9]{20,}",
        r"\bsb_(?:secret|publishable)_[A-Za-z0-9]{8,}",
        r"\bwsk_[A-Za-z0-9]{16,}",
        r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",  # JWT
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
    )
]

# Tools whose output leaves the body / reaches the world — held to a higher bar.
_OUTWARD = {"post_to_channel", "respond", "publish_site", "write_program", "run_code"}


def _text_of(args: object) -> str:
    if isinstance(args, dict):
        return " ".join(str(v) for v in args.values())
    return str(args or "")


def guardian_check(tool_name: str, args: object) -> tuple[bool, str]:
    """Vet a proposed action against the constitution. Returns (allowed, reason).

    Deny-by-default on the hard rules (exposing secrets above all). Everything the
    rules don't forbid is allowed — the gate's job is to catch violations, not to
    second-guess ordinary, principled action.
    """

    text = _text_of(args)
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            where = " (and it would go public!)" if tool_name in _OUTWARD else ""
            return False, f"нельзя раскрывать секреты/ключи{where} — статья 3 конституции"
    return True, ""
