---
name: optics-align
description: >
  Align an optical bench in the Blender Optics Simulator — steer the beam onto its target, recover a
  dark port, or null an interferometric tilt using the influence-matrix solvers. Use when asked to
  "align the bench", "get the beam on the detector", "walk the beam", "null the tilt / fringes",
  "maximize coupling", or "/optics-align".
---

# optics-align: close the loop onto the target

Alignment solvers MUTATE the trace (the bench moves) — unlike inspect/build's read-only steps. That is
expected; always report what moved and by how much.

## Workflow

1. **See the miss first** — `inspect_beam(target)` (is there power on target? where is it landing?) and
   `diagnose()` (beam_clipped / dark_detector / mount_limit). Quantify the error before solving.
2. **Pick the solver:**
   - **Gross steering onto a target** — `auto_align(...)` (the generic influence-matrix aligner: it
     calibrates a Jacobian over the available knobs and drives the beam onto the target element) or
     `align_element(name, target)` for a single steering mirror.
   - **Interferometric tilt / fringe null** — `tilt_null(...)` (drives the inter-arm tilt to zero so the
     fringes go null/flat).
   - **Mode-matching into a cavity/fiber** — `mode_match` (q-solver) + check `coupling_efficiency`.
3. **Re-verify** — re-trace and confirm with `inspect_beam(target)` (power recovered, beam centred) and
   `diagnose()` (the gate that fired is now clear). For a coupling task, read `coupling_efficiency`.
4. **Report** — what moved (element, DOF, amount), the before/after metric (power, tilt, η), and any
   `mount_limit` you hit (a DOF ran out of travel → coarse-reposition first, then re-solve).

## Disciplines
- A solver makes the trace **no longer byte-identical** — that's the point of aligning; say so.
- If `diagnose()` shows `mount_limit`, the DOF is range-exhausted: coarse-reposition the mount
  (`place_relative`) to recentre its travel, THEN re-run the fine solver.
- A "dark" port may be a healthy destructive-interference null, not a miss — check `inspect_beam`
  (per-arm power high, they cancel by phase) before "fixing" it. When in doubt, `/optics-correct`.
