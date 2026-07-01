<!-- Thanks for contributing! Please read CONTRIBUTING.md if you haven't. -->

## What this changes

<!-- A short description of the change and the motivation. Link the issue it closes. -->

Closes #

## How it was verified

<!-- REQUIRED. How do we know it's correct? -->

- [ ] New / extended `tests/test_validation.py` checks (physics vs closed form / oracle)
- [ ] `tests/test_optics.py` invariant (for anything touching the scene or trace)
- [ ] Full suite green locally on Blender 4.2+ (`test_validation.py` + `test_optics.py`)
- [ ] For new physics: an oracle/textbook value it reproduces — which one? →

## Trace integrity

- [ ] The live ray trace is **byte-identical** (analysis is off-trace, or new trace behaviour is a
      `BoolProperty` defaulting `False`)

## Checklist

- [ ] No version bump / no `CHANGELOG` released-section edits / no `CITATION.cff` DOI changes (the
      maintainer cuts releases)
- [ ] No vendor CAD / proprietary assets added; new material constants are sourced (see
      `docs/DATASOURCES.md`)
- [ ] Any newer `bpy` API touched at import/register time is guarded against `blender_version_min`
