# Contributing to Blender Optics Simulator

Thanks for your interest in improving **Blender Optics Simulator** (`optical_alignment_sim`) — a
Blender add-on for laying out, aligning, simulating and rendering optical benches, with a physics
engine an AI agent can drive over MCP. Contributions of all kinds are welcome: bug reports, feature
ideas, physics validation, documentation, and code.

## Ground rules

- **The physics is verified, not asserted.** Every formula, constant, or numeric result must be
  checked — either against a closed-form textbook answer in `tests/test_validation.py`, or with the
  `physicist` verifier (Docker oracle). Never transcribe a constant "from memory": source it (e.g.
  refractiveindex.info, CC0) and reproduce a published check value. A plausible-but-wrong formula
  (sign error, bad units, hallucinated constant, law used out of regime) should not survive review.
- **The live ray trace stays byte-identical.** Analysis features (field propagation, phenomena,
  diagnostics, GPU, quantum) are **off-trace**: they never touch `tracer.py`. New opt-in behaviour on
  the trace goes behind a `BoolProperty` defaulting `False`, so existing scenes are unaffected. The
  regression suite asserts the segment count + per-field power/Jones/q are unchanged.
- **No vendor CAD, no bundled proprietary assets.** The catalog references public part numbers for
  spec reproduction only; it ships no vendor mesh. See [`docs/DATASOURCES.md`](docs/DATASOURCES.md).

## Development setup

1. Clone the repo. The add-on package is `optical_alignment_sim/`.
2. Run the tests headless (no GUI needed):
   ```bash
   # fast physics self-tests (bare interpreter)
   python3 optical_alignment_sim/physics.py
   python3 optical_alignment_sim/speckle.py
   # full suites (need Blender 4.2+)
   blender --background --factory-startup --python-exit-code 1 --python tests/test_validation.py
   blender --background --factory-startup --python-exit-code 1 --python tests/test_optics.py
   ```
3. `tests/test_validation.py` = closed-form / oracle-verified physics checks.
   `tests/test_optics.py` = the byte-identical regression + pipeline invariants.
4. CI runs both on Blender 4.2.3 (the `blender_version_min`) and 5.x. Both must stay green.

## Submitting a change

1. **Open an issue first** for anything non-trivial, so we can agree on the approach.
2. Branch from `main`. Keep the change focused.
3. Add or extend tests: at least one `test_validation.py` check per new physics behaviour, and a
   `test_optics.py` invariant for anything touching the scene/trace.
4. Run the full suite locally (above) and make sure it is green.
5. Do **not** bump the version, edit `CHANGELOG.md`'s released sections, or touch `CITATION.cff` DOIs
   — releases are cut by the maintainer.
6. Open a PR using the template. Describe *what* changed and *how you verified it* (which checks,
   which oracle results).

## Guarding Blender API compatibility

The bundled Blender docs reflect the *running* build. Any `bpy` API touched at import/register time
must be `getattr`-guarded (or feature-detected) against the **minimum** supported version
(`blender_version_min` in the manifest) — CI on 4.2.3 is the gate, not your dev machine.

## Reporting bugs

Use the issue templates. For a rendering or alignment bug, please include the example/setup, the
Blender version, and — if you can — the output of `diagnose()` / `propose_corrections()` on the
scene.

By contributing you agree your contributions are licensed under the project's **GPL-3.0-or-later**
license.
