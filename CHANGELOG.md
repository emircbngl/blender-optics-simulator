# Changelog

All notable changes to the **Blender Optics Simulator** (`optical_alignment_sim`) are documented
here. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project uses
semantic versioning.

## [Unreleased]

### Added — opto-mechanical systems arc (Phase 2.6)
- **Beam-height datum (Phase 0).** The bench now has a single optical-axis-height datum
  (`beam_height_mm`, default 100 mm, a scene setting). *Dress Bench* derives the breadboard plane
  from it (board top one beam height below the axis) and sizes every post so optics at that height
  get the **same standard post length** — the real-bench convention — instead of a bespoke length
  cut from each element's bounding box. The datum is independent of the optics' bounding boxes, so
  adding or removing an optic no longer shifts the table or re-cuts standing posts.
- **Correct opto-mechanical dimensions.** Posts are now the Ø12.7 mm (½″ / Thorlabs-metric) standard
  (were a non-existent Ø6 mm); each post seats in a fixed-length post-holder body on a wider base
  foot (PH/BA-style), and the breadboard counterbores are sized to the declared thread (~Ø6.5 mm M6
  / Ø6.8 mm ¼-20) instead of oversized generic dots.
- **Vertical chain exposed to MCP/agents.** `get_state()['bench']` now reports `beam_height_mm`,
  `board_top_z_mm`, `board_thickness_mm`, and per occupied hole `optic_z_mm`, `post_length_mm`,
  `post_dia_mm`, `holder_length_mm`, `support_system` — the other half of the bill of materials, so
  an agent knows not just *which hole* but *how tall the post* under each optic is.
- Trace-safe: optics are never moved (only the decoration's Z follows the datum), so the beam path
  is byte-identical before/after dressing and across beam-height changes. Regression 104 → 114.
- **Mount-type-specific geometry (Phase 1).** *Dress Bench* now draws a different mount silhouette
  per element/mount type instead of one generic ring: mirrors get a **kinematic back-plate + two
  adjuster screws**, waveplates/polarizers a **knurled rotation collar + index nub**, lenses/filters
  a **threaded retaining ring in a lens cell**, beamsplitters/prism cubes a **cube platform mount**
  (fixing the old bug where a cube was wrapped by a horizontal hoop framing nothing), and
  lasers/cameras/detectors a **bracket** instead of an optic retaining ring clipping their body. A
  physicist now reads the bench by mount silhouette, as on a real table. Still pure decoration,
  oriented in each optic's own frame; trace byte-identical. Regression 114 → 119.

### Added
- **Mechanically-correct breadboard hole grid.** *Dress Bench* now lays the optics on a real
  tapped-hole array on a fixed pitch instead of a blank slab — the board reads like an actual
  optical breadboard. Each optic gets a post seated in a wider post-holder base (PH-style),
  clamped to the board directly beneath it, plus its mount ring. The grid pitch is a scene
  setting: **metric (25 mm / M6, default)** or **imperial (1″ / 1/4-20)**, switchable in the
  Render panel or via MCP `set_grid`.
- **The grid is a data model, not just geometry — MCP/agent-knowable.** `get_state()` now returns
  a `bench` block: pitch, standard/thread, world origin, extent (cols × rows) and the occupied
  holes (which `(col,row)` each optic sits over, with both the hole and the element world XY). So
  an AI agent or a person driving the bench knows exactly where parts can seat and what is already
  placed.
- **`place_on_grid(name, col, row)`** (optics_api + MCP) — grid-aware placement: snap an element
  over a named hole, keeping its height and orientation, for building a layout that lands on the
  grid. (`dress_bench` and `set_grid` are also exposed as first-class MCP tools.)
- Trace-safe by construction: dressing never moves the optics (the post clamps to the board under
  the part), so the beam path is byte-for-byte identical before and after dressing; only the
  deliberate `place_on_grid` moves a part. Regression grows 90 → 104 checks (14 new grid checks).

## [0.5.1]

### Added
- **Mount rings + cube-splitter coating plane.** *Dress Bench* now also frames each optic with a
  mount ring (a torus in the optic's transverse plane), so elements read as held in real mounts;
  and a beamsplitter cube carries its characteristic internal 45° coated diagonal. Both are
  trace-safe (the ring is non-optical decoration; the BS plane is merged into the cube's glass mesh
  with the ports unchanged) and orphan-free (the merged plane's datablock is released). The README
  hero is re-rendered to show the dressed bench with mounts.

## [0.5.0]

### Added
- **Procedural bench dressing.** *Render ▸ Dress Bench* spawns posts + post-holders under each
  element and a breadboard slab below the optics footprint, so a render reads like a real optical
  table instead of parts floating in space. Pure decoration: the objects carry no optics ports, so
  the tracer ignores them; they live in a `BENCH_` name space + `COL_BENCH` collection and are not
  parented or fed into the mount/anchor math, so dressing never perturbs alignment or the trace.
  Toggles dress ↔ strip; fully reversible (frees its meshes). Original GPL-clean geometry — no
  vendor CAD.
- **Real biconvex lens geometry.** A lens is now a smooth curved glass solid (was a flat disc), so
  it reads as real optics under the Cycles glass material; ports are unchanged so the trace is
  byte-identical.

### Fixed
- This release also lands the deep multi-agent bug-sweep (≈30 verified bugs across 11 commits):
  the Bell example's V-output arms (HWP fast axis), live re-trace on physics-parameter edits,
  source/detector family flags, anchor-relative base-pose jumps + anchor-cycle guard, the bridge
  timed-out-job double-apply, a consistent `{error}` shape across `optics_api`, stale baked-beam
  geometry, the AO low-gain/divergence stall criterion, the catalog generic-fallback element
  routing (CAVITY/WFS/DM/FILTER/PBS), GPU-blend restore, the SVG canvas blow-up, multi-scene render
  restore, save-operator IO guards, broadband power renormalization, ellipticity normalization
  (S_pol, oracle-verified), the Sellmeier deep-UV guard, and the detector-fringe shared-mesh
  copy-on-write. See the commit log for the per-fix detail + regression check.

### Verified
- The regression grew from 45 to 90 checks (all green headless on Blender 5.1.1 and on the Linux
  CI), including a bench-dressing invariant: dressing leaves the trace byte-identical, its objects
  are non-optical, and strip removes them all.

## [0.4.0]

### Added
- **Beam-profile plot w(z).** The core laser-bench design readout: the Gaussian spot radius
  sampled continuously along the beam path from the source to a detector, with element positions
  marked on the plot and the waist position/size reported. Built entirely from state the tracer
  already carries (each segment's endpoint q), so there is no new physics: within a free-space
  segment q(z) = q_end − (L − z) and w = `beam_radius(q)`. Answers "where is the waist", "does
  the mode fit the apertures", and "what reaches the cavity" at a glance. Three entry points:
  *Simulation ▸ Beam Profile w(z)* (plots into the sensor window + PNG + CSV),
  `optics_api.beam_profile(detector="", samples=24)` (returns waist, element list, z/w arrays),
  and an MCP `beam_profile` tool.

### Verified
- Regression grew to 45 checks: profile produced end-to-end on the Newton's-rings bench, the
  lens demonstrably focuses (waist ≪ source spot), the profile's endpoint agrees with the
  tracer's carried per-segment beam radius, and the CSV is written.

## [0.3.1]

A bug-fix release driven by a multi-agent audit (every finding adversarially verified against the
code before being accepted).

### Fixed
- **Retroreflector is now a corner cube, not a flat mirror.** `d_out = -d_in` regardless of
  incidence, so tipping a retro on its mount no longer deviates the return beam by 2θ — the
  simulator stops reporting a misalignment a real corner cube would not have.
- **PBS split carried in the 3-D field** (`physics.pbs_split`): s (perpendicular to the true plane
  of incidence, d×n) reflects with the unitary π/2, p transmits. The split now follows the cube's
  actual orientation and survives the detector-frame projection on every platform — the same
  frame-robustness fix the non-polarizing splitter received in 0.3.0. Dichroic reflections and
  grating diffraction orders (`physics.redirect_field`) carry their polarization the same way.
- **The 2-D sensor window now respects coherence.** Beams are grouped by coherence group
  (`src_id`) and intra-group cross terms carry the coherence envelope, mirroring the measured
  visibility: an unpolarized source's H/V halves and a broadband source's spectral lines add in
  intensity, and OPD ≫ L_c washes the window's fringes out instead of showing full contrast that
  contradicts the V≈0 readout.
- **Scan dialog hardening.** Switching the scan kind inside the dialog now re-derives the range
  (previously a Wavelength scan inherited the stage range and swept every source to 0 nm →
  ZeroDivisionError with no restore); the sweep restores parameters in a `finally`; source
  wavelength has a 1 nm floor; broadband spectral lines that cross 0 nm are skipped.
- **Per-detector "Save Sensor" buttons save THEIR detector** (the operator now takes the row's
  detector name instead of resolving to the active/brightest one).
- **CI fails on a mid-run crash**: the headless regression runs with `--python-exit-code 1`
  (without it Blender exits 0 on an unhandled exception, leaving CI green).
- **Bridge timeout is per-request** (default 30 s, extendable to 600 s), so a final Cycles render
  driven over MCP no longer reports a false "timeout" while the render completes anyway; the MCP
  server passes long waits for `render` and `scan`.
- SVG export reports filesystem errors via the operator instead of an uncaught traceback;
  `presets.py` joins the dev Reload-Scripts list; the MCP server docstring's `uvx` one-liner now
  uses the required `mcp[cli]` extra; the MCP `place_relative` tool gained the missing
  `align_rotation` parameter.

### Changed
- **Manifest declares `[permissions]`** (`network` for the localhost bridge, `files` for mesh
  import/conversion) as the Extensions platform requires, plus `website` and `tags`; the stale
  "no network/disk" comment is gone.
- README: CI + license badges, SVG export documented (features, quick start, API list), install
  section leads with the build command (no release zip exists yet).

### Verified
- Regression grew to 41 checks: PBS physical s/p routing + 50/50 energy conservation through a
  true half-wave plate, retroreflector tilt-insensitivity (vs. a flat mirror walking off), and
  white-light packet behaviour in the sensor window (bright at OPD=0, washed out at OPD ≫ L_c).
  `physics.py`'s bare-interpreter self-test covers `pbs_split` (s/p routing, the π/2 phase,
  energy) and `redirect_field` (specular limit ≡ `reflect_field`).

## [0.3.0]

### Added
- **SVG schematic export.** A dependency-free, top-view 2-D vector export of the optical layout +
  beam path — element glyphs sized by clear aperture and coloured by type, port ticks, and beams
  coloured by wavelength (width/opacity by power, dashed for split-transmitted). For publication
  figures: *Render ▸ Export SVG Schematic*, `optics_api.export_svg(filepath)`, and an MCP tool.
- **Continuous integration.** A GitHub Actions workflow downloads Blender (4.2 LTS) and runs the
  physics self-test, `extension validate`, and the headless regression on every push / PR.

### Changed
- **Faster adaptive-optics loop.** `close_loop` stops as soon as the residual RMS is flat (a handful
  of traces instead of the full iteration count) and no longer double-traces or double-computes the
  final RMS. `wavefront_image` caches the grid + per-mode Zernike basis per resolution, so the live
  wavefront map is a few scalar-weighted array adds per redraw.
- **Render materials cover every element type.** A single `RENDER_DESCRIPTORS` table
  (glass / metal / dark / emit + tint) replaces the partial per-family tables, so a new element type
  can no longer render with its flat editing material.

### Fixed
- **Cross-platform beamsplitter unitarity** (caught by the new CI on Linux x86-64). The lossless
  beamsplitter's π/2 reflection phase is now carried in the 3-D field via the physical plane of
  incidence (`reflect_field`) instead of a 2-D Jones re-embedded through the float-sensitive
  `transverse_basis` axis pick. Previously a Mach-Zehnder's complementary outputs could land on
  opposite fringes on x86-64 vs arm64 (both ports bright → energy not conserved on x86-64); now
  they are complementary and energy-conserving on every platform. The regression's MZ check now
  asserts energy conservation (`0.9 < D0+D1 < 1.1`) explicitly.

### Verified
- The consolidated regression grew to 35 checks (AO trace-count drop + wavefront-cache equivalence,
  full render-material coverage, an MCP-vs-`optics_api` drift guard, and SVG well-formedness).

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
