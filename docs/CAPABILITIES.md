# Capabilities — what the Blender Optics Simulator can do

The canonical map of the plugin's surface. For an AI driving it over MCP, call `optics_api.capabilities()`
(machine-readable) and read `mcp/AGENT_GUIDE.md` (prose). This doc is the complete tree for humans + planning.

Architecture: a **geometric single-ray tracer + analytic overlays**, **property-driven** (each element carries
optics properties; the generic tracer applies the physics — change a property, behaviour changes, no per-scene
code). Every shipped formula is verified against the physicist oracle. Regression: 318 headless checks.

---

## 1. MCP tools / `optics_api` surface (~42, grouped)
*All are remote-callable over the localhost bridge (127.0.0.1:9765) and 1:1 with `optics_api` public functions
(a parity test enforces it). `capabilities()` returns the live grouping.*

- **Read / inspect (the agent's eyes):** `capabilities`, `get_state`, `diagnose`, `propose_corrections`,
  `detect_phenomena`, `inspect_beam`, `inspect_element`, `beam_profile`, `ao_measure`, `get_wavefront`,
  `sensor_capture`, `check_mechanics`, `coupling_efficiency`. (`detect_phenomena` = advisory flag of the
  optical phenomena the trace's conditions meet — interference, off-axis hologram; `inspect_beam` = the beam's optical state at an element —
  power/w/R/M²/divergence/polarization/coherence; `inspect_element` = what an optic does + its live
  incoming/outgoing power by kind.)
  (`propose_corrections` = `diagnose` + a suggested fix / `maybe_intentional_if` / `fault_confidence` per issue —
  ADVISORY, you weigh user intent and choose refuse / partial / accept.)
- **Build / scene:** `build_example`, `add_component`, `tag_element`, `swap_part`, `set_param`, `set_mount`.
- **Design (pure math):** `design_telescope`, `design_4f`, `mode_match`.
- **Place / assemble:** `place_relative`, `make_cage`, `make_tube`, `make_rail`, `place_on_grid`, `place_on_rail`,
  `set_grid`, `dress_bench`.
- **Trace / measure:** `trace_beam`, `scan`, `bake_beams`, `clear_beams`.
- **Path statistics:** `path_statistics` returns each detector arrival's route, geometric length and phase OPL.
  Group delay/GDD are explicitly not modeled.
- **Align (mutates DOFs, on demand):** `align_all`, `align_element`, `auto_align`, `tilt_null`.
- **Adaptive optics + surface figure:** `ao_command`, `ao_close_loop`, `ao_close_loop_recon`, `ao_kolmogorov`,
  `zonal_render`.
- **Render / export:** `render`, `render_sequence`, `export_svg`.

## 2. Blender UI (the human counterpart) — ~60 operators, 9 panels
Operators mirror the MCP tools (tag/ports, mount/DOFs, trace, build_example, swap_part, place_relative,
align_*, scan, fringe_image, power_budget, beam_profile, ao_close_loop, wfs_zonal_render, render_*, export_svg,
bridge_toggle, …). Panels: Element, Mount & Adjustment, Simulation, Alignment Report, Render, Library,
Assembly, Adaptive Optics, Examples.

## 3. Element types (34) — `properties.py` `element_type`
- **Sources:** SOURCE, FIBER_COLLIMATOR.
- **Reflective:** MIRROR, PRISM_MIRROR, BEAMSPLITTER, DICHROIC, GRATING, RETROREFLECTOR, DEFORMABLE_MIRROR.
- **Transmissive:** LENS, WAVEPLATE, POLARIZER, FILTER, ATTENUATOR, ISOLATOR, PASSTHROUGH, CAVITY, OBJECTIVE,
  PRISM, CRYSTAL, AOM, SHUTTER (binary open/closed switch).
- **Apertures / stops:** APERTURE, PINHOLE, SLIT, KNIFE_EDGE, BEAM_DUMP.
- **Detectors / sensing:** DETECTOR, PHOTODIODE, POWER_METER, WAVEFRONT_SENSOR, ABERRATOR, CIRCULATOR.
Catalog (`library.py`): ~60 real vendor parts (Thorlabs HeNe/mirrors/BS/waveplates/filters/iris/PD/mounts);
meshes resolve locally or fall back to a generic mesh-free element.

## 4. Example library (`build_example`, 25 kinds)
Interferometry: mach_zehnder, michelson, dhm. Quantum: hong_ou_mandel, bell, spdc_source, back_reflection,
circulator. Frequency conv.: green_doubler, prism. Conditioning: periscope, beam_router, beam_profiler.
Assembly: cage_system, tube_system, rail_system, hybrid_system. Imaging: microscope, quad_tracker. Active:
aom, newton_rings. Adaptive optics + surface figure: adaptive_optics, **surface_figure / surface_figure_native
/ surface_figure_diverging** (a figured reflector → WFS, read three ways by three beams).

## 5. Physics modelled (verified)
- **Polarization:** Jones vectors + Stokes, polarizer/waveplate/analyzer Jones matrices, Malus extinction, PBS split.
- **Geometric:** Fresnel s/p (dielectric + metal complex index AL/AG/AU), Snell refraction, sequential multi-bounce ray trace.
- **Gaussian beams:** q-parameter ABCD propagation, w(z)/R(z)/Gouy, M², mode-match lens solve, coupling efficiency.
- **Wave-ish overlays:** coherence length + fringe envelope, interference (coherent Jones sum), Fabry-Perot finesse/FSR/Airy,
  Gaussian aperture clip `1-exp(-2a²/w²)`, 15-Noll-Zernike modal AO + dense **zonal** surface-figure wavefront.
- **Surface figure → wavefront:** reflection OPD `W = 2·cos²θ·Δdepth` (oracle ok=true), Gaussian-beam-weighted
  sampling `exp(-2ρ²)`, sensor-aperture capture `rho_max = aperture/w_sensor`.
- **Nonlinear χ²:** SHG/SPDC/THG/SFG/DFG/OPO energy conservation + sinc² phase-matching, temperature tuning.
- **Dispersion:** Sellmeier n(λ) (N-BK7, FUSED_SILICA, N-SF11, F2, N-F2, CaF2), prism deviation/min-deviation/dispersion.
- **Detectors:** QE/responsivity (Si/InGaAs/Ge), APD excess noise, quadrant/lateral-PSD erf signals, slit/knife erf.
- **Adaptive optics:** Kolmogorov/Noll turbulence (Fried r0), interaction-matrix reconstructor (TSVD/damped-transpose), leaky integrator.
- **Bench intelligence (diagnostics, read-only):** beam-clipping, vignetting, dark-detector, orphan-source,
  energy-budget, mount-limit, relay-spacing, back-reflection/ghost, pol/coherence mismatch, parasitic etalon,
  **beam-underfills-figure**.

## 6. Opto-mechanics
Breadboard hole-grid (metric/imperial/custom) + beam-height datum; Ø12.7 posts; kinematic mounts (KM100/KS1
presets, tip/tilt/rot/translation DOFs); cage (16/30/60 mm, shared rods + post), SM lens-tubes (SM05/SM1/SM2),
dovetail rails + carriers; mechanical-limit validation (post insertion, cage-rod travel) + a BVHTree collision gate.

## 7. Materials (current)
Sellmeier n(λ) for 6 glasses; Fresnel reflectivity (dielectric + metal); universal `coating_reflectance` pickoff
+ neutral `element_transmittance` absorber; colored-glass Beer–Lambert (thickness-scaled); dielectric LP/SP/BP
filters with AOI blue-shift; AR-coating ghost reflections.
**Not yet:** editable per-material absorption A(λ) / reflectivity R(λ) curves, custom Sellmeier, surface
roughness/scatter, multilayer-coating design, GDD. (Roadmap Phase 3.1.)

## 8. Scope boundaries (be honest about these)
- Geometric single-ray + analytic overlays — **no full wave diffraction** (no Fresnel patterns; gratings are
  0th-order layout; the WFS modal channel is a 15-Zernike low-pass — the zonal render is the honest companion).
- One source = one wavelength (broadband/white source is deferred — Phase 3.1).
- Surface-figure imprint is a Tier-1 GEOMETRIC OPD, not diffraction; faithful for smooth figures, a caricature for
  high-spatial-frequency relief.

## 9. Driving it as an AI
Read `mcp/AGENT_GUIDE.md`. The loop: `get_state()` → decide → act → re-trace → read again. `diagnose()` is
ADVISORY — weigh user intent before "fixing" (refuse / partial / accept). The trace is byte-identical until an
`align_*`/`ao_*` solver is called.
