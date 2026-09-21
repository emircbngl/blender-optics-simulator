# Blender Optics Simulator

[![CI](https://github.com/emircbngl/blender-optics-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/emircbngl/blender-optics-simulator/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/emircbngl/blender-optics-simulator?label=release&color=brightgreen)](https://github.com/emircbngl/blender-optics-simulator/releases/latest)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Blender 4.2+](https://img.shields.io/badge/Blender-4.2%2B%20%2F%205.x-orange)](https://www.blender.org/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20778997.svg)](https://doi.org/10.5281/zenodo.20778997)

**An optical bench you lay out in Blender, trace with real optics, and can hand to an AI agent.**

Place lasers, mirrors, lenses, waveplates, gratings, crystals and detectors in 3-D. A live engine
traces the beam through them — rays, Gaussian beams, polarization, dispersion — mounts everything on
real opto-mechanics, and renders it in Cycles. The whole optical state is readable and writable over
a localhost MCP bridge, so an agent works from measured geometry instead of guesses.

<p align="center">
  <a href="https://github.com/emircbngl/blender-optics-simulator/raw/main/docs/video/E_optix.mp4"><img src="docs/img/e-optix.gif" width="88%" alt="Sixteen-second tour: a green beam through the add-on's optomechanics, ending on the project title"></a>
</p>

<p align="center"><em>Sixteen seconds, rendered from a scene the add-on built. <a href="https://github.com/emircbngl/blender-optics-simulator/raw/main/docs/video/E_optix.mp4">Full-quality MP4</a>.</em></p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="docs/img/hero-bench-light.png">
    <img src="docs/img/hero-bench-dark.png" width="92%" alt="A Michelson interferometer on a tapped breadboard, built and traced in Blender: kinematic mounts, posts and bases, both arms' beams glowing, rendered in Cycles">
  </picture>
</p>

---

## Install

Requires **Blender 4.2 LTS or newer** (4.2+ / 5.x).

**One-click, keeps itself updated.** Open the
**[install page](https://emircbngl.github.io/blender-optics-simulator/)** and drag the
*“⤓ Drag this into Blender to install”* button onto an open Blender window. That installs the add-on
and subscribes you to updates in one gesture. Turn on *Edit ▸ Preferences ▸ System ▸ Network ▸ Allow
Online Access* first.

**From a zip.** Download `optical_alignment_sim-<version>.zip` from
[Releases](https://github.com/emircbngl/blender-optics-simulator/releases) and use *Edit ▸ Preferences
▸ Add-ons ▸ Install from Disk…*. Updates then come from the add-on's own **Updates** panel.

Open the **Optics** tab in the 3-D viewport sidebar (press `N`).

## Quick start

1. **Setup ▸ Browse Examples…** — pick *Michelson* to get a complete bench.
2. **Simulate ▸ Trace** — press **Live**. Move any part and the beam follows.
3. **Setup ▸ Element** — select an optic and change what it is: focal length, glass, coating,
   wavelength. Expand **More** for the rest.
4. **Place ▸ Mount & Adjustment** — put it on a real mount and turn the knobs, with − / + steps.
5. **Inspect ▸ Optical Report** — read power, polarization, path length and alignment error per
   detector; **Align All** walks the mounts until the beam lands where it should.

Headless, the same thing from Python:

```python
import optics_api                                  # inside Blender: blender -b --python your.py
optics_api.build_example("michelson")              # a full bench in one call
optics_api.set_mount("MI_M_fixed", "KM100")        # put a mirror on a kinematic mount
optics_api.set_dof("MI_M_fixed", "TIP", steps=40)  # turn a knob: the beam walks off
optics_api.align_element("MI_M_fixed")             # and back: 2.51 -> 0.0012 mrad
print(optics_api.inspect_beam("MI_D"))             # power, w(z), polarization, coherence
```

`examples/` holds runnable scripts: [`michelson.py`](examples/michelson.py),
[`mach_zehnder.py`](examples/mach_zehnder.py), [`agent_align.py`](examples/agent_align.py),
[`bell_entanglement.py`](examples/bell_entanglement.py),
[`hong_ou_mandel.py`](examples/hong_ou_mandel.py).

## What it does

- **Traces a real beam.** Ray paths plus Gaussian-beam propagation, Jones/Stokes polarization,
  Fresnel losses, dispersion, nonlinear conversion, interference and wavefront error.
  → [what is modelled, and what is not](docs/OPTICS_SCOPE.md)
- **35 element types, 26 one-click benches.** Mirrors through OPAs, prisms, gratings, crystals,
  spectrometers, adaptive optics. → [element reference](docs/OPTICAL_ELEMENTS.md) ·
  [full feature list](docs/FEATURES.md)
- **Mounts on real hardware.** Kinematic mounts, posts, cage systems, lens tubes and rails, with
  mechanical limits and collision checks. → [hardware](docs/realistic-hardware.md)
- **Measures like a bench.** Detector power and polarization, beam profiles, path length, group
  delay and GDD, spectra, wavefront sensors.
  → [dispersion, cylinders and spectra](docs/DISPERSION_AND_SPECTRA.md)
- **Aligns itself.** Influence-matrix solvers walk the mounts: re-centre a beam, null a tilt, close
  an adaptive-optics loop.
- **Renders what you built.** Cycles/EEVEE with detailed optomechanics, animation renders, and SVG
  schematics. → [how beams are drawn](docs/BEAM_RENDERING.md)

<p align="center">
  <img src="docs/img/agent-align.gif" width="88%" alt="A beam steered by a kinematic mirror lands off the detector centre, then auto-alignment walks the mount until it is re-centred">
</p>

<p align="center"><em>A mirror knocked 2° out of alignment, then one <code>align_element()</code> call: pointing residual 7.02 → 0.0008 mrad. <a href="examples/agent_align.py">examples/agent_align.py</a> reproduces it headlessly.</em></p>

## Drive it with an AI agent

The add-on exposes its full state as JSON over a localhost bridge and ships an MCP server, so an
agent can read the bench and act on it:

```text
get_state()   → every element's pose, ports, mount limits, beam path, detector readings
    ↓ decide
set_param() · place_relative() · set_dof() · align_element() · ao_close_loop() · render()
    ↓ the beam re-traces
get_state()   → read the result, not a guess
```

Start it from **Present ▸ Tools & Integration ▸ Start MCP Bridge**.
→ [agent guide](mcp/AGENT_GUIDE.md) · [MCP server](mcp/README.md) · [tool list](docs/CAPABILITIES.md)

## Physics, honestly

Every push runs the physics: 341 textbook checks (Malus, Fresnel, Snell, the grating equation,
Gaussian ABCD, Zernike orthonormality, energy conservation) plus a 618-check regression suite on both
Blender 4.2 and 5.x. The core formulas were also verified against an external symbolic and numerical
oracle; where that has not been done, the code and the docs say so. Every run builds the same benches
in millimetre and metre scenes and requires the readouts to agree.

What is *not* claimed matters as much: this is a chief-ray engine with wave-optics overlays, not a
full-wave solver. Thin elements carry no thickness, a grating has no blaze-efficiency model, and
anything phenomenological says so where you read it. Model limits are written next to each feature.

→ [scope and limits](docs/OPTICS_SCOPE.md) · [element-by-element provenance](docs/OPTICAL_ELEMENTS.md) ·
[where the data comes from](docs/DATASOURCES.md)

## Documentation

| | |
|---|---|
| [Features, examples, release history](docs/FEATURES.md) | The long version of this page |
| [Capabilities](docs/CAPABILITIES.md) | Every panel, API call and MCP tool |
| [Optical elements](docs/OPTICAL_ELEMENTS.md) | Per-element model, parameters and provenance |
| [Scope](docs/OPTICS_SCOPE.md) | What the engine does and does not simulate |
| [Dispersion, cylindrical lenses, spectra](docs/DISPERSION_AND_SPECTRA.md) | Gratings, white light, group delay, spectrometers |
| [Realistic hardware](docs/realistic-hardware.md) | Mounts, cages, rails and render detail |
| [Beam rendering](docs/BEAM_RENDERING.md) | How baked beams are drawn, and what that is not |
| [Data sources](docs/DATASOURCES.md) | Catalog and material provenance |
| [Agent guide](mcp/AGENT_GUIDE.md) · [MCP server](mcp/README.md) | Driving the bench from outside |
| [CHANGELOG](CHANGELOG.md) | What changed in each release |

## How to cite

A machine-readable [`CITATION.cff`](CITATION.cff) is included, so GitHub shows a **Cite this
repository** button with ready-to-paste APA / BibTeX.

```bibtex
@software{cobanoglu_blender_optics_simulator,
  author  = {Çobanoğlu, Muhammet Emir},
  title   = {Blender Optics Simulator},
  year    = {2026},
  version = {0.31.0},
  doi     = {10.5281/zenodo.20778997},
  license = {GPL-3.0-or-later},
  url     = {https://github.com/emircbngl/blender-optics-simulator}
}
```

The DOI above is the *concept* DOI and always resolves to the latest version; each release also mints
its own version DOI (listed in [`CITATION.cff`](CITATION.cff)).

## License & credits

**GPL-3.0-or-later** — see [`LICENSE`](LICENSE). Vendor CAD and meshes are not included and remain the
property of their owners; this project ships original metadata, procedural geometry and tooling.

**Contributors**

- **Tengfei Ma** — ShanghaiTech University ·
  [ORCID 0009-0008-4556-4682](https://orcid.org/0009-0008-4556-4682) ·
  [@Harca-Yita](https://github.com/Harca-Yita). Reports from a working optical bench in
  [#1](https://github.com/emircbngl/blender-optics-simulator/issues/1) drove wavelength-true beam
  colours and the shutter, the unit-scale work, shaped apertures, reflection at the coated mirror
  face, the Porro prism and polished mirror substrates, the OPA and group-delay work, and the
  groove-oriented grating, cylindrical lens and spectrum detector.

Built in the spirit of Bigweld's maxim from *Robots* (2005) — **"See a need, fill a need."**
