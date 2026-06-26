# Changelog

All notable changes to the **Blender Optics Simulator** (`optical_alignment_sim`) are documented
here. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project uses
semantic versioning.

## [0.11.0] — Optics-v2 + AI-first

The first public release since 0.9.1. The big capability expansion: an agent-facing auto-aligner, a full prism / nonlinear-crystal /
aperture / detector / circulator component build-out, an upgraded adaptive-optics loop, a read-only
error-detection layer, and an **AI-first correctness, skills, vision & phenomena** pass. Every new
formula is machine-verified against the physicist Docker oracle before shipping, and every existing
scene traces byte-identical (the port-based data model: behavior reads element properties ×
`matrix_world`, never the mesh). Regression **215 → 357** checks.

### Added — AI agent: correctness, skills, vision & phenomena
- **Correct wavefront-sensor read** — the WFS now folds in the beam's OWN curvature defocus
  `a₄ = w² / (4√3·R·λ)` (oracle-verified), so a clean diverging beam reads its real defocus instead of a
  wrong RMS=0; the static read auto-scales its colour map (with PV / full-scale / fill / multi-beam
  captions) and a dark sensor clears its frame rather than faking a flat wavefront.
- **`propose_corrections()`** (+ MCP) — correction-as-FEEDBACK: `diagnose()` plus a `suggested_fix`,
  `tool`, `maybe_intentional_if`, and `fault_confidence` per issue. Advisory only — the AI weighs user
  intent and chooses refuse / partial / accept (a crossed analyzer may be the experiment, not a fault).
- **`detect_phenomena()`** (+ MCP) — flags the optical PHENOMENA the trace's conditions MEET:
  `two_beam_interference` and `off_axis_hologram` (carrier fringe spacing `Λ = λ/(2 sin(θ/2))`,
  oracle-verified). Advisory + read-only.
- **Vision tools** `inspect_beam(element)` / `inspect_element(name)` (+ MCP) — the beam's full optical
  state (power, `w`, `R(z)`, M², divergence, waist, polarization, coherence) and what an optic does + is
  doing now (role, params, live in/out by kind, throughput). Numeric eyes, not guesses.
- **Pyramid wavefront sensor** `pyramid_wfs(sensor)` (+ MCP) — reads a WFS as a SLOPE sensor
  (`Sx = dW/dx`, `Sy = dW/dy`); a unit defocus reads a radial slope `dZ4/dx = 4√3·x` (oracle-verified).
  Tier-1 geometric (the gradient a pyramid integrates, not a diffractive 4-pupil image).
- **Per-pixel polarization CCD (DoFP)** — `physics.stokes_dofp` reads four micro-analyzers (0/45/90/135°)
  for single-shot linear Stokes (S0/S1/S2 + DoLP/AoLP), exposed as the `POL_CAMERA` detector readout.
- **Soft-edge dichroic** — a finite-slope logistic `R(λ)` (with `T = 1 − R`, energy conserved exactly)
  replaces the hard wavelength step; far from the cut it is byte-identical to the old behaviour.
- **`build_example('die')`** — a recognizable die face (the 5-pip quincunx) read as a zonal wavefront.
- **Five `/optics-*` skills** (`.claude/skills/`: build / align / inspect / correct / sensor-render) —
  repeatable model-invoked workflows that sequence the MCP tools and carry the disciplines.
- **`capabilities()`** self-describing manifest + `mcp/AGENT_GUIDE.md`, `docs/CAPABILITIES.md`,
  `docs/TOOLING.md` — the AI's "what can I do + how + which convention" guide.

### Fixed
- **M² beam quality** persisted past the first optic (it was silently reset to 1.0 one element past any
  source — the m2-reset keyed on the post-propagation `q` instead of the caller's fresh `q`).

### Added — distribution & updates
- **Native in-Blender auto-updates** — a self-hosted static extension repository (served from GitHub
  Pages) with a **one-click drag-to-install link** that installs AND subscribes in one gesture (no repo
  URL to type). Cutting a release now reaches existing users in-Blender.
- **In-add-on updater UX** (`updater.py`) — a throttled online check (a persistent app timer, gated on
  Online Access, at most once a day — not a constant poll); when a newer release exists, a prominent
  **Update available** panel appears at the top of the Optics tab with an **Install** button (stages the
  download); then an **Update Now** button **saves the file and relaunches Blender on the new version with
  the MCP bridge running**; if it isn't pressed, the staged update loads on the next launch (and an
  `exit_pre` hook best-effort stages a detected update on quit). It drives Blender's OWN extension
  operators (`package_install` / the native update panel) — it never overwrites the add-on's files, so the
  extension manager and the on-disk version never diverge. (`tools/build_pages_repo.py` regenerates the
  repo per release.)

### Added — bench intelligence (placement / correction / error detection)
- **Generic auto-aligner** (`optics_api.auto_align` + MCP tool) — a scene-agnostic linearized
  influence-matrix corrector: calibrate ∂y/∂u by poking DOFs + re-tracing, SVD-pseudoinvert, and
  drive the beam onto any reference aperture. Two-mirror beam-walk is the canonical 4-DOF case. The
  steering law (mirror tilt θ → 2θ deflection) is oracle-verified.
- **Read-only diagnostics** (`diagnose()` + MCP) — beam-clipping, vignetting, dark-detector /
  orphan-source, energy-budget audit, mount-limit, relay-spacing, **back-reflection / ghost beams**
  (opt-in Fresnel ghosts at transmissive faces + a `back_reflection` flag an isolator clears),
  **pol- vs coherence-mismatch** fringe disambiguation, and **parasitic-etalon** detection (a wedged
  surface clears it).

### Added — analysis / design methods
- **4f / telescope designer** (`design_telescope` / `design_4f`) — the afocal (C=0) lens-to-lens and the
  object→image (B=0) imaging ABCD matrices, both oracle-verified.
- **Gaussian mode-match q-solver** — the single-lens focal + position that images an input waist onto a
  target, with a power-coupling efficiency η.
- **Interferometer tilt-null solver** — recover the relative wavefront tilt from the fringe image and
  drive the fringes to a single broad null.
- **AO reconstructor upgrade** — interaction matrix + TSVD / damped-transpose reconstructor + leaky
  integrator + a physical Kolmogorov (Fried-`r0`) turbulence aberrator (Noll-1976 variance).
- **Surface-figure → wavefront imprint** (`imprint_surface`, opt-in) — a reflective element samples its
  ACTUAL mesh surface over the beam footprint (BVHTree) and imprints it onto the reflected wavefront as a
  Zernike error a WFS reads (`W = 2·h·cos θ`, oracle-verified; least-squares Zernike fit). Verified on a
  sphere→defocus, saddle→astigmatism, tilt/flat→0. A GEOMETRIC (Tier-1) OPD imprint, NOT wave diffraction;
  the modal reconstruction is a low-pass fit — faithful for smooth optical figures, a caricature for a
  high-spatial-frequency surface. Default off → existing scenes byte-identical.
- **Zonal "sensor render"** (`imprint_zonal_px` + the mirror panel's *Sensor render* button /
  `ao.zonal_wavefront_at`) — an on-demand DENSE wavefront map: it samples the SAME verified field
  (`W = 2·cos²θ·Δdepth`, the chief-AOI-projected reflection OPD — oracle ok=true) on a `px × px` grid and renders it RAW, with NO 15-mode projection, so mid/high-
  spatial-frequency figure (e.g. polishing ripple) the modal map low-passes away survives — up to the grid
  Nyquist `(px-1)/(2·footprint)` (oracle-verified). The footprint is sampled as the actual **Gaussian beam**
  (`I = exp(−2ρ²)`, oracle-verified) — the reference-plane detrend and the RMS are intensity-weighted (what
  the beam senses; the dim 1/e² edge counts less than a top-hat would), and the map fades at the edge to show
  the real beam. Both the beam-weighted and uniform (clear-aperture) RMS are reported. The honest companion
  to the modal imprint: faithful for real optical figures; a knight's relief renders as a geometrically-real
  but optically-meaningless map. On-demand only → the trace stays byte-identical. (See
  `docs/img/zonal-wavefront.png`; and `docs/img/object-wavefronts.png` — a real chess knight + a die,
  recognisable once the object's iconic face is aimed at the beam, since the zonal map is a range image
  of the reflector along the beam: its valid region traces the silhouette and the relief colours it.)
- **Surface-figure wavefront-sensing workflow** — a complete, honest bench: the `surface_figure` example
  (oblique laser → FIGURED reflector → a WAVEFRONT SENSOR that catches the reflected beam) + a sensor-anchored
  render. `optics_api.zonal_render(sensor=…)` (+ MCP tool, + the *Sensor render* button on the WFS panel)
  finds the reflective element whose reflected beam actually reaches that sensor and renders ITS dense figure
  — so the map is what a real sensor measures, not data from nowhere (it errors if no reflector's beam lands
  on the sensor). `swap_part` any mesh onto the reflector to read its figure. The bench is PHYSICALLY
  honest: a real HeNe (~0.5 mm waist) reaches the cm-scale figure through a **Galilean beam EXPANDER**
  (afocal `f1=-5, f2=100`, spacing `f1+f2`, magnification `|f2/f1|=20`, collimated output — oracle ok=true),
  not by cranking the source waist. A new **`beam_underfills_figure` diagnostic** warns when the footprint
  (radius) is < 0.9× the figure's transverse extent — "insert a beam expander / collimator" — so the AI is
  aware the beam must be grown to illuminate the whole object (both `w_mm` and `clear_aperture` are radii).
  The **rendered beam now tracks the real `w(z)`** (the old visualization clamped the tube at 6 mm radius, so
  a Ø20 mm expanded beam looked Ø12 mm — visually under-illuminating an optic the sensor fully reads); the
  beam you SEE now matches the footprint the physics samples.
- **A finite sensor captures only the beam within its aperture** — the WFS no longer swallows the whole beam.
  A figure point at footprint radius ρ lands at the sensor at radius ρ·w_sensor (Gaussian self-similar
  scaling), so a sensor of semi-aperture `a` captures only `rho_max = a/w_sensor` of the figure; the captured
  POWER is `1−exp(−2a²/w²)` (oracle ok=true). So the SAME figured optic reads DIFFERENTLY under three beams,
  and the **simulation produces the difference** (q-propagation + the aperture stop, no manual masking): the
  `surface_figure` / `surface_figure_native` / `surface_figure_diverging` examples — a bare un-expanded beam
  reads a central speck; an expanded COLLIMATED beam fits the sensor and reads the whole figure; an expanded
  NON-collimated (diverging) beam overfills the sensor and reads only its clipped centre (and loses power).
  New `optics_api.sensor_capture(sensor)` (+ MCP tool) reports w@sensor, aperture, captured power/area, and
  whether the clip applied. See `docs/img/surface-figure-3beams.png` (the chess knight, read three ways).
- **AI self-knowledge** — `optics_api.capabilities()` (+ MCP tool, "read me first") returns a self-describing
  manifest: scope, tools grouped by purpose (the read/inspect tools called out as "the agent's eyes"),
  workflows, the example library, and the gotchas. Companion docs `mcp/AGENT_GUIDE.md`, `docs/CAPABILITIES.md`
  (the full tree), `docs/TOOLING.md` (MCP-tool vs operator vs skill vs hook taxonomy). A root `.mcp.json`
  registers the `blender-optics` server so any session connects cleanly.

### Added — components
- **Dispersing prisms** (equilateral / Littrow / Pellin-Broca / Amici) on real Sellmeier glasses
  (N-SF11 / F2 / N-F2 / CaF2) — the first element that geometrically bends the chief ray per wavelength.
- **Beam-routing prisms** (right-angle / penta / Dove / roof / rhomboid) with an image-parity overlay;
  the penta 90° tilt-invariance is a validator invariant.
- **Beam conditioning** — `SLIT`, `BEAM_DUMP`, `KNIFE_EDGE` (a knife scan recovers the beam radius).
- **Nonlinear-crystal family** — THG / SFG / DFG / OPO (energy conservation) + sinc² phase-matching, on
  top of the existing SHG / SPDC.
- **Configurable photodiode** — material (Si / InGaAs / Ge) responsivity, biased / amplified / APD / SPAD
  modes, and quadrant / lateral-PSD / camera readouts (a quadrant recovers an injected beam offset).
- **Fiber circulator** — a non-reciprocal N-port cyclic router (P1→P2→P3) with dB isolation leakage.
- **Universal coatings** — paint ANY element with a controllable reflective `coating_reflectance`
  (a plain window becomes a beam pickoff) and a neutral `element_transmittance` absorber; energy conserved.

### Added — mesh realism
- **Live multi-leaf iris** — the blades actually close (an animatable diaphragm) while the trace stays
  byte-identical.
- **Grating profiles** — ruled (blazed sawtooth), holographic (sinusoid), echelle (staircase); PPLN
  poling-domain stripes + oven housing.
- Larger-optic revolve-segment bump; colored-glass (Beer-Lambert) + soft dielectric-filter edges + M²
  beam-quality physics overlays.

### Notes
- Conversion-efficiency prefactors (nonlinear crystals) and the Kolmogorov dn/dT slope are honest Tier-1
  placeholders — relative / shape, not absolute. Every wavelength relation, ABCD matrix, Fresnel/erf
  factor, and constant is oracle-checked; literature constants (Noll 1.0299, hc/e) are cited, not derived.
- 8 new Cycles renders in `docs/img/`. Internal planning docs are no longer published.

## [0.9.0]

### Added — complete-system showcases
- Four new built-in examples that compose whole mounting subsystems (each `build_example(...)`),
  grounded in real Thorlabs/Newport layouts (multi-agent reference research):
  - **`cage_system`** — a full 30 mm cage relay: fibre launcher → collimating lens → clean-up
    polarizer → PBS share four ER rods + one post; PBS transmits to a 90° turning mirror → camera and
    reflects to a beam dump.
  - **`tube_system`** — an SM1 lens-tube 4f relay (fibre + two f = 50 mm lenses in one Ø1.2″ barrel) →
    C-mount camera.
  - **`rail_system`** — a Galilean beam-expander beamline (diverging + converging lens, iris, fold
    mirror) with every optic on a carrier riding one dovetail rail.
  - **`hybrid_system`** — all three combined: a cage launcher → a free-space post mirror → a
    rail-mounted analyzer train → camera.
- Each dresses trace-identically and passes the geometric validator (regression 164 → 176).

### Fixed — render polish (owner feedback)
- **Laser/source holder** rebuilt: a saddle clamp keyed to the body's real underside + a world-vertical
  stem to the post top — the source no longer floats beside a disconnected post (old bracket sat at
  local −Z = behind a horizontal laser).
- **Mirror reflections** read correctly: a perfect mirror reflects its surroundings, so in a dark world
  it went black. Crisper metal roughness (0.04 → 0.025) + a dark semi-glossy optical-table ground give
  the mirrors a real floor + softbox highlights to reflect.

### Added — element variants & new elements (wired into the catalog)
- **Element variants** across the library, each a parameter that reshapes the mesh + render without
  touching the ports (trace byte-identical): **lens forms** (plano/bi convex/concave), **beamsplitter
  forms** (cube / plate / pellicle), **mirror coatings** (Al/Ag/Au/dielectric), **curved mirrors**
  (concave/convex with radius R; focal power f = R/2 on reflection — oracle-verified), **polarizer
  types** (film / wire-grid / Glan-Thompson/Taylor/Laser / Brewster / **Wollaston** / **Rochon** — the
  prisms split into two orthogonally-polarized beams), and **waveplate orders** (zero / multi / achromatic).
- **Nonlinear crystal** (χ² conversion): **SHG** (emits λ/2) and **SPDC** (degenerate signal + idler at
  2λ) — both relations oracle-verified.
- **Microscope objectives** (finite / infinity-corrected / long-WD): focal power f_obj = f_tube/M
  (oracle-verified), with the DIN magnification colour ring; lenses/objectives apply real ABCD focal power.
- **Acousto-optic modulator (AOM / Bragg cell):** diffracts the +1 order at θ = λ·f_a/v_s and
  frequency-shifts it by f_a — deflection angle, grating period, and shift all oracle-verified.

### Added — examples
- **`microscope`** (infinity-corrected transmitted-light train), **`dhm`** (a vertical, off-axis
  Mach-Zehnder **digital holographic microscope**), and **`aom`** (a shear-mode TeO₂ acousto-optic
  deflector showing the undiffracted 0th order + the deflected +1 order).

### Added — real mesh-interpenetration collision gate
- The bench validator gained an `interpenetration` invariant that consults Blender's true geometry
  (`BVHTree.overlap`) between support clusters — catching mount / holder / base collisions the
  post-distance proxies missed. It surfaced and fixed three latent collisions in shipped examples
  (newton_rings lens ↔ BS2 cube, microscope objective ↔ lens cell, hybrid base ↔ rail).

### Changed
- **Baked beams taper to the real Gaussian w(z)** — a focus shows as a visible waist, expansion as a
  flare — instead of constant-radius tubes.

### Docs
- Honest physics-scope statement (a single-ray geometric tracer with analytic overlays; the core
  formulas are oracle-verified, the broad variant catalog is modeled), a live **auto-alignment GIF** at
  the top of the README, a **`CITATION.cff`** + "How to cite" section, and a value-prop one-liner.

## [0.8.2]

### Fixed — render polish (owner feedback)
- **Laser / fibre sources** now read as real heads: a dark anodized **housing** with only the front
  **exit aperture glowing** (slot 2), instead of a uniformly glowing can.
- **PBS** is now clearly distinguishable from a 50/50 beamsplitter — its polarizing coating shows as a
  vivid, mirror-like magenta diagonal vs. the BS's subtle blue.
- **Periscope** no longer blocks its own mirror: the post-clamp arm stops **behind** the mirror mount
  (a clear-aperture back-off) and the pillar offset grew (30→44 mm), so neither the arm nor the post
  intrudes on the optic face or the beam. All README renders regenerated with these fixes.

## [0.8.1]

### Changed — periscope rebuilt as the real RS99 assembly
- The vertical-fold (periscope) dressing now models the actual **Thorlabs RS99** periscope: a single
  Ø1" post anchored by a **clamping fork**, with each 45° mirror riding a **360° post-clamp collar**
  that reaches back onto the beam axis (plus a side lock knob) — replacing the thin cantilever
  "spider-arm" on a slip-fit holder. The beam still folds up beside the post in clear air; the
  `beam_through_post` validator stays clean and the trace is unchanged.

### Docs
- Regenerated every 3-D README render with the new realistic elements + opto-mech (hero, dressed
  Michelson, Newton's-rings bench, Bell source, cage/tube/rail systems, kinematic-mount closeup) and
  added a **component-library gallery** (`components.png`) plus an **RS99 periscope** showcase render.

## [0.8.0]

### Added — realistic optical-element geometry
- Every optical element mesh was rebuilt from crude disc/cube/box placeholders to real, recognisable
  procedural geometry (own meshes, GPL-clean), while keeping each element's **ports and placement
  byte-identical** so the beam trace through all built-in examples is unchanged:
  - **Lens** is now a true spherical solid of revolution that reflects the focal SIGN — biconvex for a
    converging lens, biconcave for a diverging one — with a finite edge land (was a fixed flattened
    sphere that could only look equi-biconvex). Curvature is cosmetic; the tracer still uses the ABCD
    focal length.
  - **Aperture/iris** is a real ring with a central opening and a side adjustment lever; **pinhole** has
    a real tiny through-bore (both were solid pucks with no hole at all).
  - **Grating** carries ruled groove geometry; **retroreflector** is a trihedral corner-cube (facets
    meeting at a rear apex) instead of a plain block.
  - **Mirror** distinguishes its coated front face from the bare-glass substrate + bevelled edge;
    **beamsplitter** shows its tinted 45° coated diagonal through the glass + chamfered edges (PBS vs
    50/50 differ by coating tint); **dichroic** has a coated front face.
  - **Detector / photodiode / power-meter** have a recessed active-area inset; the **wavefront sensor**
    carries a Shack–Hartmann micro-lens grid; the **Fabry–Pérot cavity** is two parallel plates + rim
    spacer (was a single puck).
  - **Laser / fibre collimator / isolator** are proper barrels with exit bezels, an FC connector stub,
    and a directional forward arrow (isolator); the **deformable mirror** has an actuator backplane.
- Realistic-render materials still theme-swap only mesh slot 0, so accent detail (coatings, sensors,
  grooves, bezels) keeps its colour. Regression grows to 164 checks (lens focal-sign reads in geometry,
  apertures/pinholes pass an axis ray-cast, new meshes are manifold).

## [0.7.0]

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
- **Cage systems — 16 / 30 / 60 mm (Phase 2).** Collinear optics can now be grouped into a real
  cage assembly: four shared rods (Ø4 mm @ 16 mm, Ø6 mm @ 30/60 mm, the published standard) carry a
  cage plate per member and mount on **one** cage post, instead of an individual post per optic.
  New `make_cage(members, size_mm)` (optics_api + MCP) and a per-element `support_system`
  (POST / CAGE_16 / CAGE_30 / CAGE_60 / RAIL) on the data model. `get_state()` gains a top-level
  `cages` block (id, size, rod dia/length/count, axis, members) and each occupied hole reports its
  `support_system`, so an agent knows which optics share rods. Caging never moves the optics →
  trace byte-identical. Regression 119 → 126.
- **Lens-tube systems — SM05 / SM1 / SM2 (Phase 3 / A1).** Collinear in-line optics can be stacked
  into one black-anodized **lens-tube barrel** (a hollow pipe with a retaining ring at each open
  end) on a single post, instead of an individual post each — the real way an SM relay is built.
  New `make_tube(members, thread)` (optics_api + MCP) and `support_system` values
  TUBE_SM05/TUBE_SM1/TUBE_SM2 + a `tube_id`. `get_state()` gains a top-level `tubes` block (id,
  thread, inner/outer Ø, length, axis, members). Optics are not moved → trace byte-identical.
  Regression 126 → 132.
- **Rail systems — dovetail track + carriers (Phase 3 / A2).** Collinear optics can ride one
  **dovetail rail**: a continuous track on the board with a **carrier** under each optic (its post
  rises from the carrier, not the board) — a continuous 1-D mount vs the discrete hole grid. New
  `make_rail(members)` + **`place_on_rail(name, s_mm)`** (slide a part continuously along the rail)
  (optics_api + MCP), `support_system='RAIL'` + `rail_id`, and `get_state()['rails']` (id, family,
  width, length, axis, each carrier's `s_mm`). Trace byte-identical except the deliberate
  place_on_rail. Regression 132 → 140.
- **Board feet + MCP mount-chain data.** The breadboard now stands on **four corner feet** instead
  of floating. `get_state()` exposes each element's `support_system` (POST/CAGE/TUBE/RAIL), its
  `anchor` (the "follows another element" edge from place_relative), and `base_pose_set` — so an
  agent can read the full mounting topology, not just hole occupancy.
- **Headless animation pipeline (`anim.py`, Phase 3 / C1).** New `optics_api.render_sequence(...)`
  (+ MCP tool) renders a **camera-orbit PNG sequence** of the setup and, if `ffmpeg` is on PATH,
  encodes an mp4 — best-effort and reported honestly (`ffmpeg`/`video` fields); the PNG sequence is
  always produced. EEVEE (fast) or Cycles (realistic). A render-only pipeline: it moves the camera
  and writes frames, never touching the optics/ports/tracer. (`render.set_camera_direction` factors
  the framing so every orbit frame stays fit.) The reusable base for the promo video + tutorial.
- **Opto-mech realism pass (owner review).** Post-holders now carry a **side locking thumbscrew**
  and the base foot shows a **cap screw** fastening it to the table (was a bare floating cylinder);
  kinematic mirror mounts are rebuilt KM100-style with a back-plate and **two knurled actuator
  knobs** (shaft + knob) instead of two thin sticks; cage plates are **bored** so the optic shows
  through the aperture and the rods pass through the frame (was a solid slab). Decoration only;
  trace unaffected; regression stays 126/126.
- **Optic seated in the mount + 3-adjuster mount + camera nose (owner review #2).** The round mirror
  now sits **flush in the kinematic mount's bored aperture** (the optic is visibly held, not an empty
  holder face). New **`KINEMATIC_3AXIS`** mount type renders a KS1-style **three-adjuster** mount —
  the two KM100 tip/tilt screws keep their corners and a **third screw is added at a corner** (the
  existing two never move); pick it per element in the Element panel.
  Detectors/cameras gain a **C-mount adapter nose** on the sensor face + a bevelled clamp. Decoration
  only; trace unaffected; regression 126/126.

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
