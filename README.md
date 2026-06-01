# Optical Alignment & Simulation — Blender Add-on

A Blender 4.2+/5.x add-on for **building, simulating and aligning optical setups**
(mirrors, beam splitters, lenses, waveplates, lasers, detectors). It traces the
beam path live in the viewport, models real kinematic-mount adjustment within
physical limits, auto-aligns components, and renders publication-quality figures.

Human-first: every feature is driven from the **View3D ▸ Sidebar ▸ Optics** tab.
An optional Python API (`optics_api`) lets an agent (e.g. Claude via the Blender
MCP) drive the same core.

> Status: geometric layout **plus a physics layer** — polarization (Jones), classical
> interference (fringes / visibility), wavelength-selective optics, Gaussian-beam (ABCD)
> spot sizes, a power budget, and analytic readouts for the quantum examples.

## Features

- **Optical data model** — every element carries its ports (entry/exit/reflective
  surfaces) as world-space position **and normal**, so the true optical geometry is
  always recoverable (origin offsets and rotations no longer hide it).
- **Live beam tracer** — sequential geometric ray tracing (reflection, refraction
  direction, beam splitting) drawn as a GPU overlay that updates as you drag parts.
- **Kinematic mounts** — rig a static mesh with the tip/tilt/rotation/translation
  knobs it's missing, each with a real range; auto-align drives only the knobs and
  tells you "move the post" when a target is out of range.
- **Opto-mechanical limits** — warns when a post rod pulls out of its holder or a
  cage rod leaves its bore.
- **Alignment report** — per-element position/angle residuals with OK/Warn/Bad
  states and color feedback.
- **Render helper** — one-click EEVEE preview / Cycles final with beam baking and
  camera presets.
- **Canonical examples** — one-click Mach-Zehnder, Michelson, Hong-Ou-Mandel and
  Bell/entanglement setups, built from generic (mesh-free) components.
- **Component library** — a broad built-in catalog of real vendor parts (mirrors,
  beam splitters, lenses, waveplates, polarizers, filters, dichroics, gratings,
  retroreflectors, isolators, detectors, …) addressable by part number. Import your
  own vendor CAD (STL/OBJ natively, STEP/IGES via FreeCAD), or let an entry fall
  back to generic mesh-free geometry when the CAD isn't on disk. Save your own
  setups as reusable entries.
- **Polarization (Jones)** — sources emit a polarization state; polarizers (Malus),
  waveplates (HWP/QWP) and polarizing beam splitters transform it; detectors report
  power, polarization (azimuth / DOP) and honor an optional analyzer.
- **Interference** — beams from one source recombine coherently (optical path length →
  phase) with a coherence envelope from the source linewidth; detectors report fringe
  visibility (Michelson / Mach-Zehnder fringes, complementary MZ outputs).
- **Wavelength optics** — dichroics route by cut wavelength, filters pass their band
  (longpass / shortpass / bandpass / ND), gratings diffract by the grating equation.
- **Gaussian beams (ABCD)** — q-parameter propagation through free space and lenses;
  per-segment spot size and Gaussian aperture clipping.
- **Scan, plots & budget** — sweep an OPD stage / waveplate angle / wavelength and plot
  each detector's response (interferogram, Malus curve, spectrum) to PNG + CSV;
  synthesize the 2-D fringe pattern on a detector; write a per-detector power/loss budget.
- **Quantum readouts (analytic)** — Hong-Ou-Mandel dip and Bell CHSH (|S| = 2√2) for the
  named examples (analytic, not a full quantum engine).
- **Render backgrounds** — Dark / Black / White-paper / Transparent (alpha PNG) presets.

## Install

1. Download `optical_alignment_sim-<version>.zip` (or build it, see below).
2. In Blender: **drag the zip onto the window**, or *Edit ▸ Preferences ▸ Add-ons ▸
   Install from Disk…* and pick the zip.
3. Open the **Optics** tab in the 3D viewport sidebar (press `N`).

Build the zip yourself:

```bash
blender --command extension build --source-dir optical_alignment_sim --output-dir .
blender --command extension validate optical_alignment_sim
```

## Quick start

- **Examples ▸** pick *Mach-Zehnder* (or any of the four) to spawn a full setup with
  the live beam overlay.
- **Element** — select an object, *Tag as Optical Element*, *Auto-Detect Ports* (by
  name) or *Add Port from Face* (for arbitrary meshes); *Normalize Imported CAD*
  fixes units/scale.
- **Mount & Adjustment** — *Apply Mount Preset* (e.g. KM100CP/M), *Set Coarse Pose*,
  then drive the tip/tilt knobs.
- **Simulation** — toggle *Live simulation*; the beam updates as you move parts.
- **Alignment Report** — *Update Report* / *Align* / *Align All*.
- **Render** — *Bake Beams to Mesh*, pick a camera preset and a **Background** preset
  (Dark / Black / White / Transparent), *EEVEE Preview* / *Cycles Final*.
- **Analysis** — set source polarization and waveplate/polarizer angles, then use
  *Scan + Plot* (interferogram / Malus / spectrum), *Detector Fringe Image*,
  *Power Budget*, and *Quantum Readout* (HOM dip / Bell CHSH).

## Component library & meshes

Vendor 3D models (Thorlabs, Edmund, …) are **not bundled** — they are the vendors'
intellectual property. The add-on ships only metadata (element type, port geometry,
mount parameters). To use real parts:

1. Download the CAD from the vendor and put the meshes in a folder.
2. Set that folder as **Component mesh folder** in the add-on preferences.
3. STL/OBJ import directly. For STEP/IGES, set the **FreeCAD command**
   (`freecadcmd` / `FreeCADCmd`) in preferences — the add-on converts on import.
   Standalone conversion: see `tools/freecad_convert.py`.

The built-in catalog (~40 real vendor parts — lasers, mirrors, prism/corner-cube
mirrors, beam splitters, dichroics, gratings, retroreflectors, lenses, waveplates,
polarizers, filters, attenuators, isolators, apertures, pinholes, fiber collimators,
photodiodes and power-meter heads) references meshes by filename. Supply the vendor
CAD to use the real geometry; without it, **Add Component** still spawns a correct
generic (mesh-free) element, so every catalog entry is usable immediately.

## Examples (scripts)

`examples/` contains standalone builders that run with or without the add-on
installed:

```bash
blender --background --python examples/mach_zehnder.py
```

## Optional Python / agent API

With the add-on enabled, `optics_api` is importable inside Blender:

```python
import optics_api, json
print(json.dumps(optics_api.get_state()))          # full optical state (ports, normals, beam path)
optics_api.build_example("michelson")
optics_api.align_all()
optics_api.render(preset="final", camera="hero", filepath="/tmp/figure.png")
```

## Roadmap

- Full Stokes/Mueller partial polarization; Fresnel amplitude+phase; dispersion n(λ)
- White-light (broadband) fringes; detector-as-camera noise / exposure
- CAD-assisted DOF extraction from STEP geometry + datasheets
- POV-Ray / Asymptote export for publication figures
- Dedicated MCP server wrapping `optics_api`

## License

GPL-3.0-or-later. See `LICENSE`.

Vendor CAD/meshes are not included and remain the property of their respective
owners. This project ships only original metadata and tooling.
