---
name: optics-build
description: >
  Build or extend an optical bench in the Blender Optics Simulator — start from a canonical example or
  add and place components, set their parameters and mounts, and verify the result. Use when asked to
  "build a bench", "set up an interferometer / telescope / AO loop", "add a lens/mirror/beamsplitter",
  "assemble a cage/tube/rail system", or "/optics-build".
---

# optics-build: assemble a bench, then verify it

The simulator is **property-driven**: an element's optical behaviour is its parameters × its
`matrix_world`, not a per-scene script. Build by placing the right elements with the right params, then
READ the result back — don't assume it worked.

## Workflow

1. **Orient** — if unfamiliar, `capabilities()` (the self-describing manifest), then `get_state()` to
   see what already exists.
2. **Start from an example when one fits** — `build_example(name)` is the fastest path (mach_zehnder,
   michelson, adaptive_optics, newton_rings, surface_figure, cage/tube/rail/hybrid systems, microscope,
   …). `capabilities()` lists them. Build on top rather than from scratch where possible.
3. **Add + place components** — `add_component(type, …)`, then position with `place_relative` (off
   another element/port), `place_on_grid` (breadboard hole array), or `place_on_rail`. Assemble
   opto-mechanics with `make_cage` / `make_tube` / `make_rail`. Beam height stays on the datum.
4. **Set behaviour** — `set_param(name, key, value)` for optical params (focal_length, split_ratio,
   retardance_deg, reflectivity, waist_um, m2, nl_process, coating …); `set_mount(name, …)` for the
   mechanical mount + DOFs. To swap a vendor mesh, `swap_part`.
5. **Verify (don't assume)** — `inspect_element(name)` on each optic you placed (does it do what you
   intended — the right split, the right focal action?), `get_state()` for the topology, and
   `diagnose()` for clipping / orphan-source / energy problems. Fix placement before moving on.
6. **Show it** — `render()` a hero view (and `export_svg` for a schematic) so the result can be
   eyeballed. For sensing benches, hand off to `/optics-sensor-render`.

## Disciplines
- The trace is **byte-identical** until you run an `align_*` / `ao_*` solver — building + setting params
  is deterministic. Alignment is a separate, explicit step (`/optics-align`).
- To illuminate a cm-scale optic you must add a real beam EXPANDER (afocal spacing `f1+f2` SIGNED,
  magnification `|f2/f1|`) — raising the source waist is unphysical; `diagnose()` warns.
- Both `w_mm` (beam radius) and `clear_aperture` are RADII — compare like-for-like.
