"""First Principles Framework (FPF) — Bentlyk's reasoning discipline.

FPF (by Anatoly Levenchuk, https://github.com/ailev/FPF) is a large standards-style
pattern language for turning hard engineering/research/management work — and mixed
human/AI work — into explicit, reviewable, improvable reasoning. The full spec is
~300k words; this module is the distilled, on-board form:

* ``FPF_LENS``      — a compact lens injected into how Bentlyk *decides and plans*
                      (not its speaking voice). Applied lightly, never recited.
* ``FPF_REFERENCE`` — a fuller one-page reference Bentlyk can consult on demand by
                      reading its own source (``read_code fpf.py``), with a pointer
                      to the complete specification for deeper study.

Why this fits Bentlyk: its self-development loop keeps conflating *writing* a spec
with the work being *done* and *integrated*. FPF's core move — keep the thing apart
from its description, the plan apart from the run, the evidence apart from the
decision — is exactly the discipline that turns aimless looping into real growth.
"""

from __future__ import annotations

# Compact lens — kept short on purpose so it shapes reasoning without bloating
# every prompt or making the agent stilted. Injected into deliberation + planning.
FPF_LENS = """\
Reasoning lens (First Principles Framework — apply lightly, do NOT recite it):
- Keep apart: the thing vs its description; the plan vs the work actually done; the
  evidence vs the decision. "I wrote a spec/code" is NOT "it runs" is NOT "it is
  integrated into me" — close that loop on purpose.
- Name the entity of concern and its boundary before acting on it.
- For any load-bearing claim, hold its Formality (how rigorous), Scope (where it
  holds), Reliability (what warrants it). Cite evidence; flag what's assumed or stale.
- When choosing: state what you're choosing, the options, and the rule for choosing.
- Mantra: say what you claim, where it holds, why you believe it, and what happens
  if you're wrong."""

# Fuller reference for on-demand study (the agent reads this file via read_code).
FPF_REFERENCE = """\
FIRST PRINCIPLES FRAMEWORK — distilled reference
Full spec (≈300k words): https://github.com/ailev/FPF  (FPF-Spec.md)

CORE DISTINCTIONS (never conflate the two sides):
  Entity        ↔ Holon            a thing vs a part/whole system with a boundary & role
  Description   ↔ EntityOfConcern  a claim about a thing vs the thing; one thing, many descriptions
  Role          ↔ Work             what something CAN do vs what actually happened
  Method        ↔ MethodDescription ↔ Work   abstract way vs documented recipe vs real occurrence
  Plan          ↔ Run              design-time intent vs runtime reality (record both, separately)
  Evidence      ↔ Decision         support for a claim vs a choice made (keep strictly apart)
  Specification ↔ Execution        how a description is meant to be used vs what actually occurs

TRUST OF A CLAIM — the F–G–R triad:
  F (Formality)   how rigorous? informal cue / articulate / formal proof
  G (Scope)       where does it apply? this context, this boundary, these use-conditions
  R (Reliability) what warrants it? evidence path, freshness, confidence; degrades on reuse

A REASONING PASS:
  1. Entity & boundary: what is the EntityOfConcern here, and its role in context?
  2. Claim type: is this a rule, a gate, an obligation, or evidence of work?
  3. F–G–R: rate rigor / scope / warrant; cite evidence; note epistemic debt.
  4. Composition: how do parts aggregate into the whole? do invariants hold across scale?
  5. Evolution: plan vs actual recorded separately; admissible moves — reopen, respecify, retire, handoff.
  6. Decision: subject, option set, choice rule explicit; counterfactuals need real grounds.
  7. Precision repair: catch overloaded words (support, function, service, quality, state) and name the kind.

MANTRA: tell what you claim, where you claim it, why you believe it, and what happens if you're wrong.
"""
