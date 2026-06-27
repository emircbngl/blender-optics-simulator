# FDTD Orchestration — full-wave for the nanostructure, lumped for the bench

**Status: DESIGN ONLY.** No live-tracer code is wired by this document. It describes an *opt-in,
off-trace* module (`fdtd_bridge.py`, proposed) plus a standalone prototype (`tools/fdtd_prototype.py`)
that drives a mature FDTD engine (Meep; Tidy3D as a cloud alternative) over a **single sub-region** to
**derive a real, λ/θ-resolved effective property** that the existing lumped ray/Gaussian tracer then uses
unchanged. It does **not** add a live-trace wave effect. Read `docs/OPTICS_SCOPE.md` first — full-wave
FDTD/RCWA is a **tier-(c)** request there ("use Meep / Lumerical / Tidy3D"); this module is the honest,
*orchestrated* way to satisfy a subset of (c) without shipping a Maxwell solver.

---

## 1. The thesis — orchestrate, don't reimplement

3-D FDTD is **memory-bound** (a Yee grid at ~20 cells/λ over even a few cubic wavelengths is millions of
cells × 6 field components × many timesteps) and **already solved** by mature, GPU-accelerated, peer-used
tools (Meep, Lumerical FDTD, Tidy3D, the RCWA crowd). Re-implementing a Maxwell time-stepper inside a
Blender add-on would be slow, unvalidated, and redundant. So we **do not**.

Instead we **orchestrate**: an AI agent (or a user) points the module at **one element** — a grating, a
coating stack, a metasurface cell — and the module builds a **small** full-wave sub-simulation of *just
that nanostructure*, runs the external engine, and extracts a **figure of merit as a function of λ and θ**:

- grating **diffraction efficiency** η(λ, θ, order),
- multilayer/coating **reflectance** R(λ, θ) (and transmitted/reflected **phase**),
- metasurface / sub-wavelength-grating **effective phase & amplitude** vs cell geometry,
- (stretch) photonic-crystal / waveguide **mode** index & loss.

That curve/table is then **cached on the element as an effective property**, and the **lumped tracer reads
it like any other property** (the way it already reads `lines_per_mm`, `ar_reflectance`,
`split_ratio`, the Sellmeier index, …). The expensive physics happens **once, off-trace**; the live trace
stays a fast chief-ray + Gaussian-`q` walk and remains **byte-identical** when the property is absent.

This is **standard multi-scale optics**: full-wave (rigorous Maxwell) for the **nanostructure** whose
feature size is ~λ, ray/lumped for the **system** (the bench is metres of free space + cm-scale optics
where the geometric + Gaussian channel is exact). It maps cleanly onto this project's two pillars:

- **property-driven trace** — the tracer already turns *every* element behaviour into a stored number/
  table it reads at the surface (`physics.py` kernels feeding `properties.py` fields). An FDTD-derived
  efficiency/reflectance/phase is *just another such property*, only its provenance is a full-wave solve
  instead of a closed form.
- **AI-drivable identity** — the agent decides *when* the lumped approximation is not good enough for a
  given element and calls the sub-sim to replace it with a real number, then keeps simulating the bench.

> **What this is NOT.** It is **not** a live full-wave field on the bench, **not** beam propagation
> between planes, **not** a replacement for `wave.py`'s single-plane PSF. It is a **derived constitutive
> property** of one element, precomputed and tabulated. The honest tier in `OPTICS_SCOPE.md` is
> unchanged: a *live* FDTD field is still (c). What moves is that the *lumped coefficients* an element
> uses can now be **rigorous** instead of idealized, for the three structures below.

---

## 2. The three highest-value derivable properties (ranked)

Ranked by **(value of the upgrade) × (how wrong the current lumped model can be) × (how cheaply FDTD
delivers it)**. All three are 2-D-tractable (seconds–minutes), which is why they rank above genuinely
3-D problems (full vector metalens, 3-D photonic crystal) that need far more compute.

### (i) Grating diffraction efficiency η(λ, θ, order) — **HIGHEST VALUE**

- **What we model NOW.** `tracer.py::_diffract` (≈ line 879) applies *only the grating equation*
  `sin θ_m = sin θ_i + m·λ·(lines/mm)` (the kernel `physics.grating_angle`, oracle-verified) to get the
  **direction** of each order, then puts **all** the diffracted power into the single user-chosen
  `grating_order` scaled by a flat `reflectivity` (`tracer.py` ≈ line 1241–1254). There is **no real
  efficiency split between orders** and **no λ/θ/polarization dependence** of that split — `lines_per_mm`
  and `grating_order` are the only inputs (`properties.py` 432–433). The angle is right; the **power per
  order is idealized** (a single scalar, blaze/groove-shape-independent, polarization-blind).
- **What FDTD adds.** The **real η of every propagating order** as a function of λ, incidence angle θ, and
  polarization (TE/TM) — i.e. the actual energy split a ruled/blazed/sinusoidal groove of a given depth
  and material produces, including the strong TE-vs-TM difference and the Rayleigh-anomaly wiggles that no
  closed form captures. This is the textbook RCWA/FDTD result (Meep's `binary_grating.py`).
- **Feedback path.** Cache a table `η[order](λ, θ_in, pol)` (a small JSON curve set) on the GRATING
  element. The tracer's GRATING branch already *spawns a child per order direction*; instead of
  `ray.power * op.reflectivity` into one order, it reads `η[order]` at the ray's (λ, θ, pol) and can spawn
  **multiple** order-children with physically-correct power. (Live-trace integration is the main dev's
  job; this doc only produces the table.)

### (ii) Thin-film / coating reflectance R(λ, θ) + phase — **HIGH VALUE**

- **What we model NOW.** Several disconnected approximations, each a deliberate Tier-1 caricature:
  - AR coatings: a **single fixed scalar** `ar_reflectance` (default 0.25 %, `properties.py` 299–303),
    used flat for the Fresnel ghost (`tracer.py::_ghost_reflectance` ≈ 301). The *closed form*
    `physics.ar_quarter_wave_reflectance` exists but is a **single quarter-wave layer** only — no
    multilayer stack, no λ/θ curve fed into the trace.
  - Dichroics / interference filters: an **analytic soft-edge** `_dichroic_reflectance` /
    `_filter_*` (`tracer.py` ≈ 803, 857) — a super-Gaussian/`tanh` edge with a hand-tuned `n_eff≈1.85`
    blue-shift vs angle. A **shape**, not the real stack.
  - Metal mirrors: this one is **already rigorous** — exact s/p Fresnel from tabulated complex `n+ik`
    (`physics.fresnel_reflect` + `metal_nk`, J&C/Rakic data; `tracer.py` ≈ 1220–1230). FDTD would only
    *confirm* a single interface, so metals are **NOT** a priority target — listed for honesty.
- **What FDTD adds.** The **real R(λ, θ) and the reflected/transmitted phase of an arbitrary multilayer
  stack** (a true V-coat, a broadband AR-V, a 30-layer notch/dichroic), including the angle-shift and the
  ripple a real design has — replacing both the flat `ar_reflectance` scalar and the hand-tuned dichroic
  edge with the actual coating curve. (For pure 1-D stacks the transfer-matrix method is even cheaper than
  FDTD and is the right tool; FDTD earns its keep when the "coating" has lateral structure — see (iii).)
- **Feedback path.** Cache `R(λ, θ)` (+ phase) as a curve on the element; the tracer reads it where it
  currently reads the flat `ar_reflectance` / the `_dichroic_reflectance` shape.

### (iii) Metasurface / sub-wavelength-grating effective phase & amplitude — **HIGH VALUE, NEW CAPABILITY**

- **What we model NOW.** **Nothing rigorous.** Sub-wavelength structure is below the grating equation's
  validity (no propagating diffracted orders → the structure acts as an *effective medium / local phase
  shifter*, which `_diffract` does not model). A metalens/metasurface today can only be faked as an
  ordinary lens or a flat phase plate. This is a genuine **(c) gap** in `OPTICS_SCOPE.md`.
- **What FDTD adds.** The **local complex transmission `t = |t|·e^{iφ}` of one meta-atom / SWG period** as
  a function of its geometry (pillar diameter, duty cycle) and λ — the unit-cell library from which a
  metasurface phase profile is built. This is exactly how metalenses are designed (a swept unit-cell FDTD
  giving the φ-vs-geometry map).
- **Feedback path.** Cache the **(geometry → φ, |t|) library**; an element can then carry a *programmed
  phase profile* the tracer applies as an effective thin phase element (a generalized-Snell local
  deflection / focusing). This is the largest *new* capability of the three — but also the one whose
  *live-trace consumption* needs the most new tracer code, so it ships behind (i)/(ii).

**Ranking rationale:** (i) is #1 — gratings are already on the bench, the current model is most visibly
idealized (all power in one order), and Meep's grating recipe is the most battle-tested. (ii) is #2 —
high value, but pure-stack reflectance has a cheaper rigorous alternative (TMM), so FDTD's unique value is
narrower. (iii) is #3 by *readiness* (most new consumer-side code) despite being the biggest capability
jump.

---

## 3. Meep integration — the realistic story

**Recommended engine: [Meep](https://meep.readthedocs.io)** (NanoComp/MIT). Open-source (GNU GPL),
`import meep as mp`, MPI-parallel, on PyPI/conda — but a **heavy native dependency** (compiled C++ core,
MPI, HDF5, libctl). GPU: **Meep is CPU/MPI; it has no production GPU backend** as of this writing — speed
comes from MPI across cores, not a GPU. Be honest about that in any caption.

### Distribution rule — Meep lives OUTSIDE the extension

Meep is treated **exactly like the GPU/native libraries already are**: it is **NOT bundled** in the
Blender *listed extension*. Reasons, same as the existing native-dep policy:

- **native build + MPI + HDF5** — not pip-pure, not wheel-portable across the platforms Blender ships to;
- **size** — far past a sane extension payload;
- **distribution hygiene** — the extension stays self-contained and reproducible.

So the module **degrades gracefully**:

```python
try:
    import meep as mp          # provided by the USER's env (conda/pip), not the add-on
    _HAVE_MEEP = True
except Exception:
    _HAVE_MEEP = False
```

- `meep` importable → run the sub-sim, return the real curve.
- `meep` **not** importable → return a **clear, structured message** (`{"ok": False, "reason":
  "meep-not-available", "hint": "...", "fallback": <closed-form>}`) **and fall back to the existing
  lumped closed form** (`physics.grating_angle` direction with the flat `reflectivity`,
  `physics.ar_quarter_wave_reflectance`, etc.). Never a crash, never a silent fake.

The user installs Meep **outside** the extension, e.g. `conda create -n meep -c conda-forge pymeep` (or
`pymeep-parallel` for MPI), and points the add-on at that interpreter (subprocess) — *or* the bridge runs
as a standalone CLI (`tools/fdtd_prototype.py`) the agent invokes. The **add-on never imports Meep into
Blender's own Python**; it shells out / reads a cached JSON. This keeps Blender's process clean and the
extension installable everywhere.

### Tidy3D alternative — cloud GPU, no local build

[**Tidy3D**](https://www.flexcompute.com/tidy3d/) (Flexcompute) is the alternative for users **without a
local Meep**:

- `import tidy3d as td; import tidy3d.web as web; web.configure("<API-KEY>")` — **API-key auth**;
- **no local native build** — the heavy solve runs on **Flexcompute's cloud GPUs** (genuinely
  GPU-accelerated FDTD, unlike Meep); you submit a `td.Simulation`, `sim_data = web.run(sim,
  task_name=..., path="data/sim.hdf5")`, and read results back;
- diffraction efficiency via `td.DiffractionMonitor` → `DiffractionData` (it computes per-order
  amplitudes/efficiency by a periodic near-to-far transform, RCWA-validated);
- **paid** (credit-metered cloud), and it **requires network + an account** — so it cannot be a default.

**Recommendation:** make Meep the **primary, default** backend (free, local, reproducible, no account)
and Tidy3D an **opt-in `backend="tidy3d"`** for users who lack a local Meep build and accept cloud + cost.
Same bridge API, two backends behind one interface. GPU status, stated honestly: **Meep = CPU/MPI (no
GPU); Tidy3D = cloud GPU (paid).**

---

## 4. Module / API design — `fdtd_bridge.py` (off-trace, opt-in, byte-identical-safe)

Mirror the **`wave.py` / zonal-render boundary**: a module of **pure functions** that take plain numbers,
build a sub-sim, run the external engine, extract the figure, and return a **JSON-able dict** (a
curve/table). It **never imports `bpy`** at module top, **never mutates the scene**, and is **only called
on demand** — so the live trace is untouched and stays byte-identical (the property is *precomputed*; the
trace merely *reads* it later, exactly like `lines_per_mm`).

### Core pure functions (the bridge)

```python
# fdtd_bridge.py  —  no bpy, no scene mutation; returns JSON-able dicts.

def fdtd_grating_efficiency(period_um, depth_um, n_groove, n_substrate,
                            wavelength_nm, angle_deg=0.0,
                            orders=(-1, 0, 1), pol="TE",
                            resolution=60, backend="meep"):
    """Real diffraction efficiency per order for a binary/ruled grating sub-region.
    Returns {"ok": True, "orders": {m: eff, ...}, "sum": Σeff, "meta": {...}}
    or {"ok": False, "reason": "meep-not-available", "fallback": {...}}.

    Meep recipe (see tools/fdtd_prototype.py for the runnable version):
      1. cell = PML(x) + glass substrate + air superstrate; PERIODIC in y (period_um).
      2. planewave source (GaussianSource over a band, or single fcen) at angle_deg
         -> set sim.k_point for oblique incidence (Bloch phase).
      3. NORMALIZATION run: empty homogeneous cell -> input_flux = mp.get_fluxes(mon).
      4. STRUCTURE run: add the groove (mp.Block of n_groove, height depth_um).
      5. mode_mon = sim.add_mode_monitor(fcen, df, nfreq, FluxRegion(...)).
      6. for m in orders:  res = sim.get_eigenmode_coefficients(
             mode_mon, mp.DiffractedPlanewave((0, m, 0), mp.Vector3(0,1,0), s, p))
         eff[m] = |res.alpha[0,0,0]|**2 / input_flux[0]   (× cosθ_m correction)
      7. energy check: Σ_m eff[m] (+ R orders) should ≈ 1 - absorption.
    """

def fdtd_stack_reflectance(layers, wavelength_nm, angle_deg=0.0,
                           pol="TE", resolution=80, backend="meep"):
    """R(λ,θ) + reflected phase of a multilayer stack `layers`=[(n, thickness_um), ...].
    1-D stack -> a thin 2-D Meep cell (or TMM for pure stacks). Returns
    {"ok": True, "R": ..., "phase_deg": ..., "T": ...} (energy R+T+A≈1 checked)."""

def fdtd_metaatom_phase(period_um, pillar_um, height_um, n_pillar, n_substrate,
                        wavelength_nm, resolution=60, backend="meep"):
    """Complex transmission of ONE meta-atom / SWG period: returns
    {"ok": True, "amp": |t|, "phase_deg": arg(t)}. Sweep `pillar_um` to build the
    geometry -> phase library a metasurface profile is assembled from."""

def available(backend="meep"):
    """{"ok": bool, "backend": ..., "version": ...|None, "reason": ...|None} —
    cheap import probe so the agent/UI can show capability without running a solve."""
```

Each returns a **dict that JSON-serializes** (numbers + small lists), so the result is cacheable to disk
and quotable by the agent. On `not _HAVE_MEEP`, every function returns the structured
`{"ok": False, "reason": "meep-not-available", "fallback": <closed-form value>}` — the **same shape**, so
callers branch on `ok`, never on an exception.

### Optics-API wrapper (SKETCH — not wired; the main dev integrates)

```python
# optics_api.py (sketch only — DO NOT WIRE here). Caches the FDTD result as an
# effective property on the element so the LIVE TRACE stays untouched + byte-identical.

def derive_grating_efficiency(elem_name, wavelengths_nm, angles_deg=(0.0,),
                              orders=(-1, 0, 1), backend="meep"):
    """AI-callable: run fdtd_bridge over a (λ, θ) grid for one GRATING element and
    CACHE the resulting η-table as an effective property. The trace then READS it.

      op = <element>.optics
      period_um = 1000.0 / op.lines_per_mm                 # lines/mm -> period
      table = {}
      for wl in wavelengths_nm:
          for th in angles_deg:
              r = fdtd_bridge.fdtd_grating_efficiency(
                      period_um, op.groove_depth_um, op.n_groove, op.refractive_index,
                      wl, th, orders=orders, backend=backend)
              if not r["ok"]:
                  return r                                 # surface the honest failure
              table[(wl, th)] = r["orders"]
      # write-back as an EFFECTIVE PROPERTY (precomputed; trace just reads it):
      op["fdtd_eff_table"] = json.dumps(table)             # ID-prop JSON blob on the elem
      op["fdtd_eff_provenance"] = "meep r<ver>; res=...; sum_check=..."
      return {"ok": True, "cached_on": elem_name, "table": table}
    """
```

Write-back is a **custom ID-property JSON blob** (`op["fdtd_eff_table"]`), not a new `PropertyGroup`
field — so it's purely additive, optional, and absent-by-default. The trace's GRATING branch *would*
(main-dev change) look for `op.get("fdtd_eff_table")` and, **only if present**, interpolate η at the ray's
(λ, θ) to weight the per-order children; **absent → today's exact path → byte-identical.** That invariant
is the whole point: the bridge **derives** a property; it never **runs inside** the trace.

---

## 5. Prototype — `tools/fdtd_prototype.py`

A **standalone** script (not imported by the add-on) with **one real Meep simulation**: a **2-D binary
grating efficiency** sub-sim plus a 1-D **thin-film reflectance** check, with the genuine `import meep as
mp` API calls (source, geometry, flux/mode monitors, `run`, `get_eigenmode_coefficients`,
`mp.DiffractedPlanewave`). The `meep` import is **guarded**; if Meep is absent the script prints the
documented recipe and the closed-form fallback instead of crashing. See the file header note: **untested —
meep not present in this environment; API written per the Meep docs (Mode-Decomposition tutorial +
`binary_grating.py`).**

---

## 6. Honest limits + the verification-needed list

**This is a DERIVED property, not a live-trace effect.** The bench trace never becomes a full-wave
simulation; one element's *coefficients* become rigorous. Everything in `OPTICS_SCOPE.md` about live
full-wave being tier-(c) still holds.

**Runtime.** A 2-D grating or 1-D stack run is **seconds to a few minutes** on a few CPU cores
(Meep is MPI/CPU, no GPU). A full **3-D** vector metasurface/metalens cell or a 3-D photonic crystal is
**much** heavier (minutes–hours, real RAM) — keep the shipped targets **2-D / 1-D**; flag 3-D as
"possible but expensive, verify resource budget first." Tidy3D moves the 3-D solve to cloud GPU at
monetary cost.

**Convergence — the non-negotiable checks before trusting any number:**

1. **Resolution sweep.** Re-run at e.g. `resolution` ∈ {40, 60, 90} cells/μm (≈ 12–18+ cells/λ at 0.5 μm;
   the Meep tutorial uses 60). The figure must be **converged** (change < a stated tolerance) — an
   under-resolved FDTD grating efficiency is just wrong. **Report the resolution and the convergence
   delta with every cached value.**
2. **Energy conservation.** Σ(reflected orders) + Σ(transmitted orders) + absorption must ≈ 1. A sum that
   strays from 1 (beyond a tolerance) means the monitors/PML/normalization are wrong — **reject the run.**
3. **Analytic-limit cross-check.** Validate against a case with a known answer before trusting novel ones:
   - thin/shallow grating → first-order efficiency vs the scalar thin-grating limit;
   - 1-D stack → Meep R(λ,θ) vs the **transfer-matrix** result and vs `physics.ar_quarter_wave_reflectance`
     for a single quarter-wave layer (already in the repo — a free oracle);
   - single dielectric interface → vs `physics.fresnel_reflect`.
   These mirror the repo's existing discipline (`tests/test_validation.py` + physics_verify): **a derived
   FDTD number is only quotable once it has passed a resolution sweep, an energy check, and an
   analytic-limit comparison** — the same bar as promoting a textbook value to the oracle whitelist.
4. **PML / cell-size adequacy.** Too-thin PML or too-small air gaps leak/reflect and corrupt the flux —
   check insensitivity to PML thickness and cell padding.
5. **Polarization & oblique incidence.** TE vs TM differ strongly for gratings; the `k_point`/Bloch phase
   must match the requested `angle_deg`. Verify the normalization run uses the **same** `k_point`.

**Unverified API details to confirm against the installed Meep version (flag every one):**

- `mp.DiffractedPlanewave((0, m, 0), mp.Vector3(0,1,0), s, p)` argument order/semantics and that it pairs
  with **`add_mode_monitor`** (NOT `add_flux`) for diffracted orders — docs say diffracted planewaves
  can't use symmetry-bisected `add_flux` monitors.
- `get_eigenmode_coefficients(...).alpha` indexing `[band, freq, dir]` — confirm shape; the `±` direction
  index that selects forward vs backward.
- The **cosθ_m** (and air→glass Fresnel) correction the tutorial applies to transmitted-order efficiency —
  confirm whether it's needed for the chosen monitor placement (in-air vs in-glass).
- `mp.stop_when_fields_decayed(...)` thresholds for clean convergence of the flux.
- `k_point` sign/convention for oblique incidence and the matching source `amplitude`/Bloch phase.
- Tidy3D path: `td.DiffractionMonitor` order indexing and `DiffractionData` field names (`amps`,
  efficiency accessor) — confirm against the installed `tidy3d` version.

**Bottom line.** Meep (default, free, CPU/MPI) or Tidy3D (opt-in, cloud GPU, paid) derives a rigorous
η(λ,θ,order) / R(λ,θ) / metasurface-φ for **one** element; the bridge returns it as a JSON curve; the
optics-API caches it as an effective property; the lumped tracer reads it and stays byte-identical when
it's absent. Honest framing throughout: **multi-scale, derived-property, off-trace — not a live
full-wave bench.**

---

*Sources for the engine APIs cited here:* Meep docs — Mode-Decomposition tutorial and
`python/examples/binary_grating.py` (NanoComp/meep); Tidy3D docs — `DiffractionMonitor` / `DiffractionData`
and the WebAPI `web.run` / grating-efficiency example (Flexcompute). API specifics are flagged
**unverified** above and must be confirmed against the installed engine versions.
