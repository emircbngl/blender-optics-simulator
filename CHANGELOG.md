# Changelog

All notable changes to the **Blender Optics Simulator** (`optical_alignment_sim`) are documented
here. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project uses
semantic versioning.

## [0.2.0]

### Added
- **Adaptive optics (modal Zernike).** A wavefront sensor + deformable mirror + closed-loop
  integrator: an aberrator injects Zernike modes, the sensor reads the residual and shows the
  reconstructed wavefront map in the sensor window, and **Run AO Loop** drives the residual RMS to
  zero (`optics_api.ao_measure` / `ao_command` / `ao_close_loop`).
- **Gaussian-wavefront fringes.** Each beam's carried complex `q`-parameter now renders into the
  fringe pattern — wavefront curvature `+k·ρ²/(2R)`, Gouy phase, and `exp(−ρ²/w²)` apodization —
  plus an oblique-detector `cos θ` factor. A collimated beam reduces exactly to the old straight
  fringes; two beams of differing curvature give curved / concentric (ring) fringes.
- **Newton's-rings example.** A lens-vs-flat near-focus interferometer that paints concentric
  rings in the sensor window — the live showcase of the Gaussian-wavefront model.
- **Realistic-optics render mode.** One-click *Cycles Final* gives beam splitters / lenses glass
  materials and mirrors reflective coatings, with a studio rig (softboxes + graded world + ground).
  Reversible: the viewport keeps its flat editing colours and **Reset Render Style** restores them.
- **Exact vectorial (3-D) polarization** for Fresnel reflection at an arbitrary mirror tilt
  (true s/p decomposition; fixes a frame-discontinuity that zeroed visibility for some tilts).
- **Dedicated MCP server + socket bridge.** An AI agent can drive a *running* scene; the bridge
  auto-derives its allow-list from `optics_api`, and the server mirrors the full surface
  (build / align / swap / position / scan / render / adaptive optics).
- **Swappable parts** (catalog or file, single or bulk by type/mount/prefix) and **relative
  positioning & assemblies** (anchors + live "B follows A" links).
- **Live sensor window** — a docked picture-in-picture of what a detector records (2-D fringe /
  intensity / wavefront map), render-independent and savable to PNG.
- A comprehensive README with a regenerated, add-on-produced visual gallery + a `CHANGELOG`.

### Fixed
- Realistic-render reversibility hardened (max-effort code review): shared-mesh / linked-duplicate
  elements no longer lose their original material on reset; an empty or since-removed material
  restores cleanly instead of sticking as glass; the studio rig is torn down by tag (never a
  same-named user object); the TRANSPARENT background preset is honored under realistic optics
  (alpha PNG, ground skipped); Cycles transmission/max bounces are stashed and restored; the style
  auto-reverts after the render completes (and the Reset button is always available). A wavefront
  sensor's Save/Detector-Fringe now records its wavefront map, not a meaningless interference
  image; `ao._aberr_at` picks the strongest beam by power (a flat reference is no longer shadowed
  by a weak aberrated stray); building an example clears any leftover studio rig.

### Verified
- All physics formulas checked against an external symbolic + numerical oracle (`physics_verify`):
  Zernike basis + RMS, Gaussian ROC / Gouy, curvature phase, obliquity — on top of the existing
  polarization / interference / dispersion / Fresnel / cavity layers. A consolidated headless
  regression (`tests/test_optics.py`) builds all six examples and asserts the key invariants.

## [0.1.0]
- Initial release: explicit **port data model** (world position + normal), a live **GPU beam
  tracer**, **kinematic mounts + auto-alignment**, opto-mechanical limit checks, a **38-part vendor
  catalog** with generic mesh-free fallbacks, the **physics engine** (polarization, interference,
  wavelength-selective optics, Gaussian beams, white-light packets, detector camera model,
  isolators, Fabry-Pérot, analytic quantum), the analysis tools (Scan + Plot / Detector Fringe
  Image / Power Budget / Quantum Readout), and the **render helper** with background presets.
