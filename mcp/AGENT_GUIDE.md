# Agent Guide — driving the optical bench over MCP

You are connected to a **physics-verified optical bench in Blender**. You can build it, inspect it, align it,
sense wavefronts, and render it — all programmatically. **Call `capabilities()` first** for the machine-readable
manifest (tool groups, workflows, gotchas); this file is the prose companion.

## The golden rule: INSPECT, don't guess
The bench has eyes — use them. Never assert what the beam is doing; **read it**:
- `get_state()` — every element, its ports, params, mount/DOFs, and the live traced beam path.
- `diagnose()` — advisory problems (beam clipped, vignetting, beam-underfills-figure, energy violations).
- `beam_profile(detector)` — the Gaussian spot radius w(z) along the beam.
- `ao_measure(sensor)` / `get_wavefront(sensor)` — the wavefront RMS + Zernike vector at a sensor.
- `sensor_capture(sensor)` — what a sensor ACTUALLY captures: beam radius vs aperture, captured power & figure
  fraction, whether the aperture clip applied. (A finite sensor does NOT swallow the whole beam.)
- `zonal_render(sensor=…)` — a dense raw surface-figure wavefront map (the honest companion to the modal WFS).

The loop is: **`get_state()` → decide → act (`set_param`/`place_relative`/`align_*`/…) → the beam re-traces →
read again.** The trace is deterministic and byte-identical until you explicitly call an `align_*`/`ao_*` solver.

## Corrections are ADVISORY — weigh user intent, then refuse / partial / accept
`diagnose()` flags what looks wrong; **`propose_corrections()`** goes further — each issue comes with a
`suggested_fix`, the `tool` that would apply it, a **`maybe_intentional_if`** hint (when this "fault" is actually
a deliberate design choice), and a `fault_confidence` 0..1 (genuine fault vs design choice). They are **not**
auto-applied. Before "fixing", ask: **did the user ask for this on purpose?** A beam that overfills a sensor, an
underfilled figure, a crossed analyzer (an extinction measurement!), a retro-reflection (a cat's-eye / Michelson
end mirror), or a deliberately-misaligned bench may be *intended*. Read `maybe_intentional_if`, weigh the user's
stated goal and the data, then choose:
- **refuse** — the condition is intentional/desired (its `maybe_intentional_if` holds); report it, don't change it.
- **partial** — apply the safe part of the fix, flag the rest for the user.
- **accept** — apply the correction (and say what you changed and why).
Low `fault_confidence` (e.g. `crossed_polarizer` ~0.3) → lean toward refuse/confirm; high (e.g. `energy_violation`
~0.9, a config bug) → lean toward accept. Mirror the same honesty you'd want: state assumptions, show the numbers,
don't silently "improve" the bench. This is the physics-honesty-gate pattern applied to bench corrections.

## Physics honesty
Every shipped formula in this plugin is verified against the physicist oracle. When you state a result, it is
backed by `physics_verify`-checked math — but **you** should still inspect outputs and report uncertainty
honestly. The bench is a GEOMETRIC single-ray tracer with analytic Gaussian/Zernike/Fresnel overlays — it is
not a full wave-diffraction solver (no Fresnel diffraction patterns, no real grating orders beyond layout, the
WFS modal channel is a 15-Zernike low-pass). Say so when it matters.

## Tool groups (see `capabilities()` for the live list)
- **read / inspect** — your eyes (above).
- **build / scene** — `build_example`, `add_component`, `tag_element`, `swap_part`, `set_param`, `set_mount`.
- **design (pure math)** — `design_telescope`, `design_4f`, `mode_match` (no scene change).
- **place / assemble** — `place_relative`, `make_cage/tube/rail`, `place_on_grid/rail`, `set_grid`, `dress_bench`.
- **trace / measure** — `trace_beam`, `scan`, `bake_beams`, `clear_beams`.
- **align (mutates DOFs)** — `align_all`, `align_element`, `auto_align`, `tilt_null` — on demand only.
- **adaptive optics + surface figure** — `ao_command`, `ao_close_loop(_recon)`, `ao_kolmogorov`, `zonal_render`.
- **render / export** — `render`, `render_sequence`, `export_svg`.

## Gotchas that bite (read these)
1. `w_mm` and `clear_aperture` are both **radii** (a mirror's clear_aperture = size/2). Compare like-for-like.
2. A finite sensor captures only `rho_max = aperture/w_sensor` of the figure; a diverging beam overfills it and
   the outer figure is clipped + power `1-exp(-2a²/w²)` is lost. Use `sensor_capture()` to see it.
3. To illuminate a cm-scale optic with a real ~0.5 mm laser you must add a beam **expander** (afocal: spacing
   `f1+f2` SIGNED, magnification `|f2/f1|`). Raising the source waist is unphysical; `diagnose()` warns.
4. Physics is **property-driven** — change an element's glass/coating/focal and behaviour changes; no per-scene code.
5. The WFS image is the **modal** 15-Zernike channel (low-pass); for high-frequency figure use the **zonal** render.
6. `swap_part` normalizes mesh orientation — solve the right orientation empirically through the actual swap path.

## Connection
The MCP server (`mcp/optics_mcp_server.py`) talks to a localhost socket bridge the Blender add-on opens on
**127.0.0.1:9765**. Requirements: Blender running, the add-on enabled, and **View3D ▸ Sidebar ▸ Optics ▸
Simulation ▸ Start MCP Bridge**. Each call is one JSON request `{"fn": <name>, "args": {…}}`.
