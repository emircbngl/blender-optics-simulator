# Optics Scope — the honest case index

**Verb: scope a simulation request honestly.** Given "can this bench simulate X?", map X to one
of three tiers, then either cite the oracle-verified case that proves we do it, or name the engine
we deliberately lack and the external tool you'd reach for instead. This file adds **zero**
simulation capability — it is a routing/anti-overclaim document. The `/optics-scope` skill drives
it; the machine-readable mirror is `capabilities()['scope_map']` (wired separately by the API).

This file is **vendored into the repo on purpose**: the headless / installed agent cannot reach the
Obsidian vault, so the verified subset must live here. The broad bibliographic catalog lives in the
vault (link at the bottom) and may be unreachable — that's why this file exists.

---

## The three tiers

- **(a) Reproducible NOW** — the live engine already does it: a single geometric ray + the Gaussian-`q`
  (ABCD) channel + analytic closed-form overlays (Jones/Stokes polarization, Fresnel/Snell, Sellmeier
  dispersion, prisms, gratings, cavities, detectors). No new code, no opt-in module. The closed forms
  are physics_verify'd in `tests/test_validation.py`.

- **(b) Reproducible via the opt-in field layer** — an on-demand FFT module (off-trace, byte-identical):
  `wave.py` = a **single** focal-plane / Fraunhofer PSF `|FFT(pupil · exp(i·2πW))|²` (Airy, Strehl, MTF,
  encircled energy, Maréchal penalty); `field.py` = **angular-spectrum free-space propagation** between
  arbitrary planes (`propagate_field`: any `dz`, Gaussian `w(z)` verified, reversible → digital-hologram
  back-propagation, with a `sampling_ok` grid-adequacy flag). A *single* propagation step / single pupil —
  the multi-screen BPM / inter-medium stack is still (c).

- **(c) Needs an engine we DON'T have** — requires a sampled-field / multi-plane / full-wave-Maxwell /
  Monte-Carlo / quantum-statistics engine that this project deliberately does not ship. We flag these
  honestly and name the canonical external tool. We never fake a (c) result with an (a)/(b) overlay.

---

## Request → tier map

| Simulation request | Tier | Tool / case — or the missing engine |
|---|---|---|
| Ray trace, beam steering, walk-the-beam, alignment | **a** | live tracer (`trace_beam`, `align_*`) |
| Gaussian beam `w(z)` / `R(z)` / Gouy / `M²` / beam-parameter product | **a** | Gaussian-`q` ABCD channel — **oracle-verified** |
| Resonator stability `g₁g₂ ∈ [0,1]`, FSR, finesse | **a** | cavity kernels — **oracle-verified** |
| Thin-lens / mirror imaging, Newton's form, thick-lens EFL | **a** | ABCD imaging — **oracle-verified** |
| Prism min-deviation, grating angle / dispersion / resolving power | **a** | prism + grating kernels — **oracle-verified** |
| Fresnel reflectance (normal & at angle), TIR phase, Brewster, AR quarter-wave | **a** | Fresnel kernels — **oracle-verified** |
| Polarization: Malus, waveplates, Jones/Stokes, DOP, ellipticity | **a** | Jones/Stokes overlays — **oracle-verified** |
| Material dispersion `n(λ)`, Abbe `V_d`, chromatic focal shift | **a** | Sellmeier — **oracle-verified** (catalog values `[datasheet]`) |
| Thermo-optic `dn/dT`, thermal-lens `f`, photoelastic retardance, cantilever sag | **a** (opt-in / estimate) | Tier-1 closed-form estimates — **oracle-verified** as *estimates* |
| Airy radius `1.22 λF#`, first-dark-ring | **b** | `wave.psf_metrics` — **oracle-verified** |
| Strehl ratio, Maréchal penalty `S ≈ exp(−(2πσ)²)` | **b** | `wave.psf_metrics` — **oracle-verified** |
| MTF cutoff `1/(λF#)`, encircled energy (83.8 % in 1st ring) | **b** | `wave.psf_metrics` — **oracle-verified** |
| Full-wave FDTD / RCWA (nanophotonics, metasurfaces, gratings as structures) | **c** | **use Meep / Lumerical / Tidy3D** |
| Free-space field propagation, single-plane angular-spectrum (any `dz`) | **b** | `propagate_field` — Gaussian `w(z)` verified, reversible, `sampling_ok` flag |
| Digital-hologram numerical reconstruction (back-propagate a recorded field) | **b** | `propagate_field` with `dz<0` (angular-spectrum back-prop) |
| Multi-plane Fresnel / BPM through varying media (many planes + index) | **c** | **use POPPY / diffractio** (a single step is (b); the multi-plane/BPM stack is not built) |
| Split-step NLSE: soliton / dispersion / SPM (1D pulse) | **b** | `propagate_pulse` — fundamental soliton shape-invariant, oracle-verified |
| Supercontinuum (higher-order dispersion + Raman + self-steepening) | **c** | **use gnlse** (the core NLSE is (b) `propagate_pulse`) |
| Monte-Carlo photon transport in turbid / biological tissue | **b** | `monte_carlo_tissue` — MCML-style; R+T+A=1, Beer-Lambert ballistic, diffusion penetration depth |
| Atmospheric turbulence phase screen + structure function | **b** | `turbulence_screen` — dense Kolmogorov/von-Kármán, FT + subharmonics, D(r)=6.88(r/r₀)^5/3 |
| Multi-screen turbulence inter-plane propagation (split-step stack) | **c** | **use POPPY / diffractio / Schmidt-suite** (a single screen + `propagate_field` is (b)) |
| FDTD / RCWA effective property (grating η, coating R(λ,θ), metasurface) | **b/c** | `fdtd_derive_property` — orchestrates Meep/Tidy3D (closed-form fallback if absent); a LIVE full-wave field stays (c) |
| Quantum photon statistics: `g²`, HOM dip, squeezing | **c** | **use QuTiP** |

> The AO loop in *this* engine corrects the **modal** Zernike channel only (15-Noll low-pass), and the
> WFS read includes the beam's own `R(z)` curvature defocus. That is an (a)/(b)-tier modal caricature —
> it is **not** multi-screen turbulence propagation (that's (c), POPPY/diffractio).

---

## Oracle-verified whitelist (the ONLY numbers you may quote as verified)

Each value below is asserted in `tests/test_validation.py` and physics_verify'd against the Docker
oracle (or marked `[datasheet]` for a manufacturer/literature catalog constant). Quote these freely:

| Quantity | Value | Tier |
|---|---|---|
| Brewster angle, air→glass `n=1.5` | **56.31°** | a |
| Critical angle, glass `n=1.5`→air | **41.81°** | a |
| Prism minimum deviation, `A=60°, n=√2` | **30°** | a |
| Fabry-Perot finesse, `R=0.9` | **29.8** | a |
| Grating angle, 600 ℓ/mm, m=1, 633 nm, normal | **22.32°** | a |
| N-BK7 `n_d` @ 587.56 nm | **1.51680** | a `[datasheet]` |
| N-SF11 `n_d` @ 587.56 nm | **1.78472** | a `[datasheet]` |
| Abbe number `V_d`, N-BK7 | **64.17** | a `[datasheet]` |
| Airy radius | **1.22 λF#** | b |
| Encircled energy within first dark ring | **83.8 %** | b |
| Maréchal Strehl (small-aberration regime) | **`S = exp(−(2πσ)²)`** | b |

**Hard rule:** the broader textbook catalog in the Obsidian vault is **book-cited, NOT
oracle-verified**. Never quote a vault number as verified. A textbook value becomes quotable-as-verified
*only* after it lands in `tests/test_validation.py` and passes the oracle. The file is the count — do
not hard-code "N checks", it drifts every release.

---

## Adding a textbook case to the validation suite

To promote a book-cited number to oracle-verified:

1. **physics_verify the closed form first.** Confirm the formula's units, symbolic form, and a numeric
   instance against the physicist Docker oracle (`/physics-verify` or `mcp__…__physics_verify`). Angles
   are cross-checked in radians, then converted to the kernel's degree convention.
2. **Add a `check(...)` call** to the right section of `tests/test_validation.py`:
   `check(name, physics.<kernel>(...), expected, tol, src)`. Use `src="…; oracle"` for an
   oracle-derived value, or `src="…[datasheet]"` for a manufacturer/literature catalog constant that is
   validated against the published figure rather than oracle-derived.
3. **Run the suite** headless: `blender --background --factory-startup --python tests/test_validation.py`
   — it must report a full pass.
4. Only *then* may the number be cited as verified (and added to the whitelist above).

---

## Full bibliographic catalog (breadth, NOT verified)

For the wide textbook/method survey across all sub-fields — core/foundational, lasers, Fourier,
holography, microscopy, fiber, atmospheric, nonlinear/quantum, nanophotonics/X-ray/biomedical — see the
Obsidian vault hub: `wiki/references/Optics-Textbook-Simulation-Catalog.md` and its eight
`Optics-Sims-*.md` category notes. **Note:** the vault is unreachable from a headless / installed agent
— that is exactly why this in-repo file exists. Treat every number there as **book-cited, not
oracle-verified** until it is wired into `tests/test_validation.py` per the steps above.
