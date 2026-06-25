---
name: optics-inspect
description: >
  Inspect what an optical bench is actually doing — a structured, READ-ONLY numeric sweep of the
  Blender Optics Simulator scene (topology, per-element beam state, per-optic behaviour, sensor reads).
  Use when asked "what is this bench doing", "inspect the beam", "report the optical state", "is the
  beam aligned", "what does this detector see", or "/optics-inspect". The golden rule: never GUESS what
  the beam is doing — READ it.
---

# optics-inspect: read the bench, don't guess

The bench has eyes. Use them. This skill produces a faithful, read-only picture of the optical state
via the `blender-optics` MCP tools. Every tool here is byte-identical (it never mutates the trace).

## Workflow

1. **Topology** — `get_state()`: every element, type, pose, ports, mount/DOFs, and the live beam path.
   This is the map (what is connected to what), not the physics.
2. **Beam state at the key elements** — `inspect_beam(element)` for the source, each optic, and the
   detector/sensor: power, wavelength, Gaussian `w` + curvature `R(z)` (collimated / diverging /
   converging), `M²`, far-field divergence + reconstructed waist, polarization (kind / azimuth /
   ellipticity / DOP), coherence length, and how many beams arrive. Blank element → the most-lit one.
3. **What each optic does** — `inspect_element(name)` for every optic: its role, the type-relevant
   params (focal_length / retardance / split_ratio / reflectivity / coating / nl_process …), and the
   LIVE incoming/outgoing power by kind (SPLIT_R/SPLIT_T/REFLECT/SHG/…) with throughput. This is where
   you SEE the effect (split 50/50, reflected 98 %, converted 532 nm, clipped to Y %).
4. **Sensors** — `sensor_capture(sensor)` (beam-vs-aperture, captured power & figure fraction, whether
   the aperture clip applied) and `ao_measure(sensor)` (the wavefront RMS + Zernike, now including the
   beam's own curvature defocus). For surface figure, `beam_profile(detector)` gives `w(z)`.
5. **Problems** — `diagnose()` for advisory issues; escalate to `/optics-correct` only if asked.
6. **Summarize** — report the numbers, name the units, and state what the bench IS doing (not what it
   should do). If a value is surprising, say so; don't paper over it.

## Disciplines
- READ-ONLY: this skill changes nothing. The trace stays byte-identical.
- Honesty: the modal WFS is a 15-Zernike low-pass; the zonal render is the dense companion — name which
  you're reading. A finite sensor reads only what its aperture admits.
- Don't assert; cite the tool output. "`inspect_beam(D1)` → power 0.48, w 1.2 mm, diverging R≈2.9 m".
