---
name: optics-correct
description: >
  Run the correction-as-FEEDBACK loop on an optical bench — surface the proposed fixes, then judge each
  against user intent (refuse / partial / accept) rather than blindly auto-fixing. Use when asked to
  "fix the bench", "what's wrong and correct it", "clean up the alignment/energy", "review for problems
  and fix", or "/optics-correct". Never silently "improve" a bench the user built on purpose.
---

# optics-correct: surface, judge, then apply

Corrections are **advisory feedback**, not commands. A "fault" is often the experiment: a crossed
analyzer IS an extinction measurement, a retro-reflection IS a cat's-eye / Michelson end mirror, an
underfilled figure IS a sub-aperture probe. Blind auto-fix breaks intent. Mirror the physics-honesty
gate: surface the issue, weigh intent, decide.

## Workflow

1. **Get the proposals** — `propose_corrections()`. Each carries: `issue`, `element`, `detail`,
   `severity`, `suggested_fix`, the `tool` that would apply it, **`maybe_intentional_if`**, and
   `fault_confidence` (0..1: genuine fault vs design choice).
2. **Judge each one** — for every proposal, ask *did the user ask for this on purpose?*
   - Read `maybe_intentional_if`. If it holds given the user's stated goal → **REFUSE** (report it,
     change nothing).
   - High `fault_confidence` (e.g. `energy_violation` ~0.9, a config bug) → lean **ACCEPT**.
   - Low `fault_confidence` (e.g. `crossed_polarizer` ~0.3, usually intentional) → lean refuse, or
     **confirm with the user** before touching it.
   - Mixed → **PARTIAL**: apply the safe part, flag the rest.
3. **Apply the accepted ones** — use each proposal's `tool` (align_element / set_param / place_relative
   / design_4f …). Apply one, re-trace, re-check — don't batch blindly.
4. **Re-verify** — `propose_corrections()` / `diagnose()` again; confirm the accepted issues cleared and
   nothing new broke. `inspect_beam` / `inspect_element` to confirm the physics is now right.
5. **Report the judgment** — list what you ACCEPTED (and the measured before/after), what you REFUSED
   (and why it's intentional), and what you left PARTIAL. The reasoning is the deliverable, not just the
   diff.

## Disciplines
- Never auto-apply a low-confidence proposal without confirming intent.
- Each accepted fix that moves an element makes the trace non-byte-identical — say so.
- This is the same honesty you'd want for physics: state assumptions, show the numbers, don't pretend a
  refused issue doesn't exist — surface it so the user decides.
