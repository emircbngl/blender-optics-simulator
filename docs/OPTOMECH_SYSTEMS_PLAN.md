# Opto-Mechanical Mounting Systems — Standards Reference & Build Plan

> Durable design note produced from a 50-agent research + adversarial gap-audit workflow
> (run `wf_d67cbbc9-12c`). Goal: reproduce **every** real opto-mechanical mounting system
> (cage / lens-tube / rail / post / optic-mount / vertical-periscope) **procedurally and
> GPL-clean** — original geometry to the *functional* published dimensions, never vendor CAD —
> in **both metric and imperial**, so a physicist's real bench maps 1:1 onto ours and the layout
> is fully MCP/agent-knowable.

Scene convention: `1 BU = 1 mm` (scene scale 0.001), so a mm value below is the Blender dimension.
**IP boundary:** functional dimensions (thread pitch, rod spacing, ¼-20) are not copyrightable; we
model to them with our own meshes. We never bundle vendor STEP/STL. Vendor part numbers below are
cited only to identify the *standard*, not to copy a model.

---

## 1. Standards reference (functional dimensions)

Confidence tags: values without a tag are HIGH-confidence (published). `~` or **NEEDS-CONFIRMATION**
= treat as approximate / expose as an adjustable parameter, never bake a guessed decimal as spec.

### Lens tubes / SM threads (all 40 TPI, pitch 0.635 mm)
| Thread | Major Ø | Retaining-ring CA | Optic | Cage companion |
|---|---|---|---|---|
| SM05 | 0.535″ (13.59 mm) | SM05RR ≈ Ø11.2 mm | Ø½″ (12.7) | 16 mm cage |
| SM1  | 1.035″ (26.29 mm) | SM1RR Ø22.86 mm | Ø1″ (25.4) | 30 mm cage |
| SM2  | 2.035″ (51.69 mm) | SM2RR Ø48.3 mm | Ø2″ (50.8) | 60 mm cage |
| SM1.5 / SM3 | 1.535″-40 / 3.035″-40 | — | Ø1.5″ / Ø3″ | — |
| RMS | 0.800″-36 | — | objective | — |

- **Lens-tube ladder** `SMxLyy`: suffix `yy` = internal thread depth in 0.1″ (L05 = 12.7 mm,
  L10 = 25.4, L15 = 38.1, L20 = 50.8, L30 = 76.2). Total OAL adds a small lip — **NEEDS-CONFIRMATION**.
- **Air gap** in a tube = tube length − optic thickness − **SM1S spacer-ring** length (spacers set the gap).
- Step adapters bridge sizes (SM05↔SM1, SM1↔SM2); couplers (SM1T, jam-nut SM1NT) join tubes.

### Cage systems
| Cage | Plate bore | Rod Ø | Rod separation (square) | Corner tap |
|---|---|---|---|---|
| 16 mm | SM05 | Ø4 mm (ER) | 16.0 mm | 4-40 |
| 30 mm | SM1 | Ø6 mm (ER) | 30.0 mm | 4-40 |
| 60 mm | SM2 | Ø6 mm (ER) | 60.0 mm | — |

- Cage plate ≈ 8.9 mm thick (CP33), 4 corner rod through-bores + side M4 locking setscrews.
- Cage cube: 30 mm body, SM1 ports on faces, internal 45° seat → fold/split at the cube center;
  KCB1 = kinematic right-angle cube (±4° tip/tilt). The rods, not per-element alignment, hold coaxiality.

### Rails & carriers
| Rail | Cross-section | Key dims | Use |
|---|---|---|---|
| RLA dovetail | width 0.75″ = 19.1 mm | hole pitch 25.0/25.4 mm; end taps 8-32/M4; engraved 1 mm; lengths 75–600 mm; **flank angle unpublished** | carriers slide for 1-D positioning |
| RC1/RC2 carrier | — | RC1 L=25.4, RC2 L=50.8 / W=25.4 mm; top ¼-20/M6; spring-plunger preload | rides the 19.1 mm dovetail |
| XT34 / XT66 | 34 / 66 mm square | 4-sided dovetail; M3 end taps; lengths 100–1000 mm | rigid frames / vertical masts |
| XT95 | 95 mm | **2 T-slots/face, 46.0 mm spacing**; 50.8 mm clearance slots; M6 (XT95N6 T-nut); 8 wing taps | heavy gantries |
| Newport X95 / X48 | 95 / 47.5 mm cruciform | 4 ribs (~10 mm), 4 dovetail faces; carriers 50/80/120 mm | heavy interferometer arms |

### Posts / holders / pedestals / bases / clamps
| Part | Key dims |
|---|---|
| **Ø½″ post (TR)** | Ø12.7 mm; bottom ¼-20, top 8-32 stud; lengths 0.75–12″ |
| **Ø12 mm metric post** | *actually Ø12.7 mm* (shares holders); M6 bottom, M4 top; 30–300 mm. True-Ø12.0 lines exist (other vendors) |
| **Ø1″ post (RS)** | Ø25.0 mm (not 25.4); both ends 8-32 or ¼-20; 25–300 mm; ~16× the bending stiffness of Ø½″ |
| **Post-holder (PH)** | bore **Ø12.7 mm slip-fit** (NOT threaded; thumbscrew clamps); heights 25–150 mm; base 1× ¼-20/M6 |
| **Pedestal (RS-P)** | Ø1″ (also Ø1.5″=38.1); top 8-32/¼-20; 12.5–155 mm; clamped by a **fork** (no post-in-holder slip joint → stiffer) |
| **Clamping fork (PF/CF)** | PF175 slot ≈ 54 mm for ¼-20; sized to pedestal foot |
| **Base (BA1/BA2)** | 2 slotted holes + central tap; footprints **NEEDS-CONFIRMATION** |
| **Right-angle clamp (RA90)** | two ⟂ Ø12.7 mm bores + setscrews; swivel/offset variants for periscope legs |
| **Fasteners** | SHCS ¼-20 / M6 (posts, bases) and 8-32 / M4 (small taps) — the only thing touching the table |

### Optic mounts (→ element `mount_preset`; alignment lives in the DOF list, not the mesh)
| Mount | mount_type | DOFs | Key dims |
|---|---|---|---|
| **Kinematic mirror (KM100)** | KINEMATIC_2AXIS | TIP+TILT ±4° | optic Ø25.4, CA 24 mm; **¼″-80 adjusters (0.3175 mm/rev)** |
| Precision kinematic (KS1/KS1T) | KINEMATIC_2AXIS | TIP+TILT ±4° | 3-point; KS1T = SM1 front bore. *3rd screw is not a 3rd axis* |
| **Threaded lens mount (LMR)** | FIXED | 0 | LMR1 CA 22.86/SM1; LMR05 SM05; LMR2 SM2 |
| Fixed mirror mount (FMP) | FIXED | 0 | nylon setscrew vs front flange |
| **Rotation mount (RSP)** | ROTATION | 1 ROT 0–360° about beam axis | SM1 rotating bore; 2° graduations; lock setscrew |
| V-clamp | FIXED | 0 | 90° V (45° half-angle), self-centers any cylinder OD |
| **30 mm cage cube** | FIXED (cube) / KINEMATIC (KCB1) | 0 / TIP+TILT ±4° | Ø6 rods @ 30 mm, SM1 ports, beam through center |

### Vertical / stages
| Part | Key dims |
|---|---|
| **Periscope (RS99)** | two 45° Ø1″ mirrors on a Ø1″ post; separation ≈ 25–69 mm = height gain; top unit 360°+±4°, bottom 360° rot |
| Right-angle fold | mirror face 45° → 90° out-of-plane fold; pair = periscope |
| Vertical translator | ~13 mm Z travel, lead-screw |
| Linear stage (PT1/XR25) | 25 mm travel; 10 µm/1 mil grads; 0.5 mm/rev (XR25); 4×4 tap grid; dowel-pin stackable |
| Rotation stage (RP01) | Ø2″ platform; 360°; 2° grads; setscrew lock |

### Beam-height convention — THE primary layout invariant
Pick **one** beam height (table top → optical axis) for the whole bench, so every mount lands its
optic center there and a 3-D alignment problem collapses to 2-D. Canonical values (commit to one
unit system — do not equate 100 mm with 4″):
- Imperial: **3″ = 76.2 mm**, **4″ = 101.6 mm**, **5″ = 127.0 mm**.
- Metric (round): **75 / 100 / 125 mm**.
Lower = stiffer/less jitter; higher = hand clearance. Fine-trim is done with **washers/spacers +
clamping collars**, not by machining a unique post.

### Coupling rules (don't allow nonexistent combos)
- Thread ↔ pitch are coupled: **M6 ↔ 25.0 mm grid**, **¼-20 ↔ 25.4 mm grid**. Never M6 on a 25.4 board.
- Three *different* joint types, each with its own check semantics:
  1. optic ↔ mount = **threaded** (SMxx 40 TPI),
  2. post ↔ post-holder = **slip-fit + setscrew** (clamp depth),
  3. holder/base ↔ table = **bolted** (cap screw through slot/counterbore into a tapped hole).
- Clearance vs tap-drill vs counterbore are different Ø: ¼-20 clearance ≈ Ø6.8–7.1, M6 ≈ Ø6.6;
  the *visible* breadboard feature is the counterbore (~Ø6–7), not Ø8.5.
- **Table vs breadboard:** breadboard = solid tapped plate; optical table = honeycomb core + sealed
  holes + optional pneumatic isolation legs. Different vibration/drift story.

---

## 2. Confirmed gaps in the current add-on (28 real, severity-grouped)

### Medium (effective top priority)
1. **No beam-height datum anywhere** — nothing fixes optical-axis Z; level layouts are accidental
   (`z=0` hard-codes in `examples_builtin.py`). `properties.py`/`optomech.py`/`optics_api.py`.
2. **Every mount draws the same torus** (`optomech.py:224-226`) — kinematic/threaded/rotation/fixed
   are byte-identical; `dress()` ignores `mount_type`/`element_type` though the data model carries it.
3. **Cage system is a phantom** (`mounts.py:270-280`) — `CAGE_ROD` advertised in 3 places, never
   built; the check uses raw center-distance, not rod insertion; no rod/cage data exists.
4. **Lens tubes entirely absent** (`elements_generic.py`) — only catalog strings; in-line stacks
   render as N independent posts instead of one shared barrel.
5. **get_state()/grid_info() are 2-D only** (`optics_api.py:97`, `optomech.py:139-148`) — no z, no
   assemblies, no travel; `CAGE_ROD` detail is just a distance string.
6. **grid_info() drops the vertical chain** — `dress()` computes board_z/post-h/holder-h but none
   reach the agent; `(col,row)` is only half the BOM.
7. **`mech` links never populated by any builder** (`optics_api.py:70`) — only the manual operator
   adds a (target-less) link, so `check_mechanics()` always returns UNKNOWN on built/dressed scenes.
8. **No support-system discriminator** (`properties.py:53-59`) — `MOUNT_TYPES` is adjuster
   kinematics, not POST vs CAGE vs RAIL; `dress()` posts everything.
9. **`anchor` not exposed in get_state** — the one genuine "B follows A" pose edge is invisible.
10. **Auto-dressed posts aren't the checked POST_INSERT object** — post overshoots holder by design,
    never linked, so the realism check is dead on dressed scenes.

### Low (realism / correctness)
11. Posts sized from per-element bbox bottom → optics at one beam height get different post lengths.
12. Post-holder height tracks the bespoke post (real PH is a fixed-length catalog part).
13. Re-dressing recomputes `board_z` from current min → adding one tall optic moves the table & re-cuts every post.
14. Mount ring mis-oriented for BS/dichroic/grating (torus axis from raw matrix → horizontal hoop around a cube waist).
15. Rotation optics (waveplate/polarizer) show no rotation collar — look like a fixed window.
16. Rails/carriers/dovetails completely missing — everything snaps to discrete holes, no continuous track.
17. No vertical mounting / periscope / riser — single board plane, posts straight down only.
18. **Post Ø6 mm is not a real standard** (`post_radius=3.0`) — should be Ø12.7 (imperial) / Ø12 (metric).
19. Hole counterbore radius `pitch*0.17` → Ø8.5 mm holes labelled M6/¼-20 (should be ~Ø6–6.5).
20. No pedestal/base under the holder — holder cylinder floats on the board.
21. Posts seat between holes — holder base at un-snapped optic xy, not over a tapped hole.
22. Breadboard floats — no table/legs/feet; also no mounting-hole-free border at the edge.
23. Holes are flat zero-depth discs 0.05 mm *proud* of the board (z-fight / sticker look).
24. Out-of-plane optics get a wrong vertical post (need L-clamp; tall runs need a pillar post, not a 3 mm stick).
25. `dress()` rings lasers/cameras/crystals — sources/detectors get an optic retaining ring clipping their body.
26–28. Dressing hardware has no data link back to its optic (only iteration order); holder conflates body+base;
    counterbore material called "counterbore" but geometry is a flat cap.

### Critic corrections folded in
- SM05RR CA ≈ Ø11.2 mm is **published** (not a gap). 30 mm cage rod separation = **30.0 mm**; 16 mm cage = Ø4 mm @ 16 mm.
- PH bore is **slip-fit Ø12.7**, not threaded → POST_INSERT = slip depth. Three joint types (above).
- Beam height: **4″ = 101.6 mm**, not 100 mm — commit to one unit system.
- Pedestal is a single rigid stem clamped by a fork (no slip joint) — don't model it as a short post.
- Also real but lower priority: cable/fiber tie-downs, washers/spacers/collars, adjuster pitch (¼-80),
  tube spacer rings (SM1S), swivel post clamps, breadboard edge border, post material (steel vs Al).

**Trace-safety invariant for the whole model:** all of this is decoration in `COL_BENCH` with
`is_optical=False`, never parented into the optics' `base_pose`/`anchor`/DOF math. The tracer walks
only `is_optical` objects, so `get_state()['beam_path']` and `['report']` must be **byte-identical**
before/after any dressing change on every BUILTIN example. (The periscope is the one exception: it is
an *optical* element whose ports DO enter the trace — only its decorative mechanics stay in COL_BENCH.)

---

## 3. Unified mechanical / data model (the attachment chain)

```
optic ──attaches to──> MOUNT ──seats in──> SYSTEM ──fixes to──> BREADBOARD
  │           │                   │                      │
  │   mount_type (KINEMATIC_2AXIS POST | CAGE_30/60 |    hole(col,row) on pitch grid
  │    /ROTATION/FIXED/…)         RAIL                   (or rail s_mm, continuous)
  │   + DOFs (the adjustability)  post+holder+base /
  │   pivot = OPTIC_CENTER        4 rods+plates /
  │                               rail+carrier(s)
  optic center at z = beam_height_mm   ← the single layout invariant
```

`get_state()` is extended so an agent can both READ and BUILD: top-level `beam_height_mm`, and
`bench` gains the vertical chain per occupied hole (`support_system`, `post_length_mm`, `post_dia_mm`,
`holder_length_mm`, `post_insertion_mm`, `optic_z_mm`, `board_top_z_mm`, `board_thickness_mm`); new
top-level `cages` / `tubes` / `rails` / `decks`; per element a `mount_chain` tree
(`mount → system → post → holder → base → board_hole → optic_z`) plus `anchor` / `base_pose_set`, and
`mech` links populated with real `state`/`detail` (post slip depth, rod engagement).

---

## 4. Phased build plan (each phase = one shippable commit + regression check + render)

- **Phase 0 — Beam-height datum + correct post/hole dimensions.** *(value highest, risk low)*
  `properties.py` (`beam_height_mm` + presets, `bench_grid_units`-coupled), `optomech.py`
  (datum-driven `board_z`; post Ø from units → 12.7/12.0; standard-length snap; constant holder;
  `hole_r` from thread; pedestal base; snap holder base to a hole; recess holes), `optics_api.py`
  (beam height + vertical chain into `grid_info`/`get_state`), `examples_builtin.py` (centers at
  `beam_height_mm`). Invariant: posts/board move in Z only; optic XYZ + ports unchanged → identical trace.
- **Phase 1 — Mount-type-specific geometry + populated mech links.** `MOUNT_DESCRIPTORS` keyed by
  mount/element type (kinematic plate+adjusters, rotation knurled collar, threaded ring, fixed cup;
  port-normal-derived frame for BS/dichroic; skip ring for sources/detectors; seed POST_INSERT link +
  `obj['bench_optic']`). `check_mechanics()` returns OK (not UNKNOWN) on dressed scenes.
- **Phase 2 — Cage system.** `support_system` enum + `CageAssembly` (16/30/60, rods, members);
  emit 4 rods + plates on the cage square for collinear members; rewrite CAGE_ROD check (project plate
  centers on rod axis, insertion ∈ [0, rod_length] for all 4 rods); `get_state()['cages']`.
- **Phase 3 — Lens tubes.** `LensTube` (SM05/SM1/SM2, inner Ø, length, members+seat, spacer rings);
  one barrel spanning a collinear chain, suppress per-member posts; `get_state()['tubes']`.
- **Phase 4 — Rails / carriers / dovetails.** `Rail` (axis, start hole, length, family RLA/XT66/XT95,
  carriers `s_mm`); profile+extrude rail under collinear elements; `place_on_rail(name, s_mm)` API;
  rail-travel check; `dovetail_angle`/`t_slot_throat` exposed as flagged-approximate params.
- **Phase 5 — Vertical / periscope.** Periscope element (two 45° folds on a shared post, separation
  25–69 mm), riser/vertical-breadboard, deck list; L-clamp for out-of-plane beams; pillar-post radius;
  z in `grid_info`. The periscope's folds DO enter the trace; its mechanics don't.
- **Phase 6 — Full MCP `mount_chain` + `anchor` exposure.** Pure read-side: assemble per-element
  `mount_chain`, add `anchor`/`base_pose_set`, `list_assemblies()` wrapper.

Verify every phase in **headless worktree Blender** (per MEMORY.md), never the live install; CI must
stay green; physics untouched (decoration only).

## 5. Open decisions for the owner
1. Default beam height + default standard (metric 75/100/125 vs imperial 76.2/101.6/127; flips post Ø, thread, pitch).
2. System build order (cage → tube → rail → periscope by value/risk — or jump rails/periscope ahead?).
3. Auto-detect cage/tube/rail membership from collinear anchored elements, or explicit grouping only.
4. Standard-length post snapping set (imperial inch vs metric mm vs follow `bench_grid_units`).
5. Dovetail flank angle & T-slot throat as flagged-adjustable params (unpublished) — confirm.
6. Periscope as a single two-fold optical element vs a true two-mount sub-assembly.
7. Whether to badge NEEDS-CONFIRMATION dimensions in the UI vs docs-only.
