"""An internal council of roles — Bentlyk thinking as a small team, not one voice.

Before an important move, several role-minds each give a short take from their own
angle (analyst, engineer, FPF planner). Their voices are then handed to the
deciding step, which acts as the chair and synthesises one decision. This is the
mixture-of-roles / internal-debate the entity lacked: real deliberative depth on
top of the single-pass reasoner, using the deeper ``reason_reasoner`` brain.
"""

from __future__ import annotations

# Each role is a distinct lens. Kept short on purpose so the council adds depth,
# not bloat — outputs are 2 sentences each and feed the chair's final decision.
ROLES: list[tuple[str, str]] = [
    ("Аналитик", "You are the Analyst on this mind's internal team. Apply the First "
                 "Principles Framework: keep the thing apart from its description, evidence "
                 "apart from decision, plan apart from done work. In TWO short sentences: "
                 "what is actually known vs merely assumed here, and the single key uncertainty."),
    ("Инженер", "You are the Engineer on this mind's internal team. In TWO short sentences: "
                "the simplest, most correct concrete way to build or improve the thing at hand "
                "— name the file or approach if it is code, and the cheapest way to verify it."),
    ("Планировщик-FPF", "You are the FPF Planner on this mind's internal team. In TWO short "
                        "sentences: the single highest-value next move, and whether this line of "
                        "work should CONTINUE, be RESPECIFIED, or REROUTED — explicitly avoid "
                        "repeating an approach already tried."),
]


def convene(reasoner, system_base: str, situation: str, *, code_reasoner=None,
            max_tokens: int = 150) -> str:
    """Gather the roles' short takes on ``situation``. Returns them as one block.

    Degrades gracefully: a role that errors is simply omitted, so the council can
    never block the decision it feeds.
    """

    voices: list[str] = []
    for name, role in ROLES:
        brain = code_reasoner if (name == "Инженер" and code_reasoner is not None) else reasoner
        try:
            out = brain.complete(
                system=f"{system_base}\n\nYou are speaking in ONE role only.\nROLE: {role}",
                prompt=situation,
                max_tokens=max_tokens,
            ).strip()
        except Exception:  # pragma: no cover - a missing voice must not break thinking
            out = ""
        if out:
            voices.append(f"[{name}]: {out[:320]}")
    return "\n".join(voices)
