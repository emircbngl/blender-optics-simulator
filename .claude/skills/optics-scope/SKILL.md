---
name: optics-scope
description: >
  Scope an optical-simulation request honestly — map "can this bench simulate X?" to a tier
  ((a) reproducible now / (b) via wave.py single-plane FFT-PSF / (c) needs an engine we lack), then
  cite the oracle-verified case or name the missing engine + the external tool to use. Use when asked
  "can it simulate …", "is X in scope", "what can/can't this engine do", "do you support FDTD / BPM /
  Monte-Carlo / hologram reconstruction / turbulence / g²", or "/optics-scope". Anti-overclaim only:
  this adds ZERO simulation capability.
---

# optics-scope: route the request, never overclaim

This skill answers "can this bench simulate X?" — it does **not** simulate anything new. Its job is to
place a request in the right tier and back the answer with proof: either the verified case that shows we
do it, or the engine we deliberately lack plus the external tool you'd use. The source of truth is the
vendored case index `docs/OPTICS_SCOPE.md`, mirrored machine-readably in `capabilities()['scope_map']`.

## Workflow

1. **Read the source of truth** — open `docs/OPTICS_SCOPE.md` (the in-repo case index: tier
   definitions, the request→tier table, the oracle-verified whitelist). If the file is absent, fall back
   to `capabilities()['scope_map']`. Do **not** answer from memory — the numbers and the missing-engine
   list live in the file, not in your head.
2. **Classify the request into a tier** — using the table:
   - **(a) reproducible now** — ray/align, Gaussian-`q` (`w(z)`/`M²`/resonator), thin-lens/prism/grating,
     Fresnel/Malus, dispersion/Abbe, thermal lensing (opt-in estimate). The live engine already does it.
   - **(b) via `wave.py`** — a single focal-plane / Fraunhofer PSF `|FFT(pupil·exp(i·2πW))|²`: Airy,
     Strehl, MTF, encircled energy, Maréchal penalty. One plane only — no inter-plane propagation.
   - **(c) needs an engine we lack** — full-wave FDTD/RCWA, multi-plane Fresnel/angular-spectrum/BPM,
     split-step NLSE/solitons, Monte-Carlo tissue transport, digital-hologram reconstruction,
     multi-screen turbulence, quantum statistics (g²/HOM/squeezing).
3. **Back the answer with proof** — for (a)/(b), cite the matching row and, where relevant, the
   oracle-verified case from the whitelist (it's asserted in `tests/test_validation.py`). For (c), state
   plainly that we don't have the engine and name the canonical external tool from the file
   (Meep/Lumerical/Tidy3D, POPPY/diffractio, gnlse, MCML, QuTiP) — "use X for this".
4. **Report the scope verdict** — tier + the cited case *or* the named missing engine. If the request
   spans tiers (e.g. "show the PSF *and* propagate it through turbulence"), split it: (b) for the PSF,
   (c) for the turbulence propagation. Don't average a mixed request into one tier.

## Disciplines
- **Never overclaim a (c) capability.** The modal AO loop here is a 15-Zernike caricature, not
  multi-screen turbulence; a single FFT-PSF is not multi-plane propagation. Name the gap; don't paper a
  (c) request over with an (a)/(b) overlay.
- **Only the whitelist counts as verified.** Numbers in the Obsidian catalog are *book-cited, NOT
  oracle-verified* — never quote them as verified. A value becomes quotable only after it's wired into
  `tests/test_validation.py` and passes the oracle (the file is the count; don't hard-code a number).
- **Degrade gracefully.** Vault unreachable headless → use `docs/OPTICS_SCOPE.md`. Doc absent →
  `capabilities()['scope_map']`. Cite which source you used.
- This skill routes and cites — it does not invent a `can_simulate()` helper or claim a parity test that
  doesn't exist. The proof is the verified case in the suite, not a fabricated check.
