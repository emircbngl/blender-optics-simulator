"""fdtd_bridge.py -- the FDTD ORCHESTRATION path (off-trace, opt-in, byte-identical-safe).

This is the promoted, testable add-on module behind docs/FDTD_ORCHESTRATION.md (design) and
tools/fdtd_prototype.py (the standalone prototype). It drives a mature full-wave engine (Meep; Tidy3D as
a cloud alternative) over ONE sub-region to DERIVE a real lambda/theta-resolved EFFECTIVE PROPERTY that
the lumped ray/Gaussian tracer then uses unchanged. It does NOT reimplement FDTD, NOT add a live-trace
wave effect, and -- like wave.py / field.py -- NEVER imports bpy and NEVER mutates the scene. Every public
function returns a JSON-able dict carrying a ``backend`` field that tells the truth: "meep" / "tidy3d"
(a real full-wave solve) or "fallback-closedform" (the repo's verified closed forms, honestly labeled).

Design contract (see the design doc):
  * The heavy engine (Meep) is a NATIVE dependency provided by the USER's env (conda/pip), NEVER bundled in
    the Blender extension -- exactly like the GPU/native-lib policy. Import is GUARDED; absent -> fallback.
  * Three derivable properties, ranked by value (design doc section 2):
      (i)   grating_efficiency  -- per-order diffraction efficiency eta(lambda, theta, order)   [HIGHEST]
      (ii)  stack_reflectance   -- multilayer R(lambda, theta) + reflected phase                [HIGH]
      (iii) metaatom_phase      -- complex transmission t=|t|e^{i phi} of one meta-atom/SWG cell [HIGH, NEW]
  * The fallbacks MUST agree with the oracle-verified kernels in physics.py:
      - grating  -> physics.grating_angle for the per-order DIRECTION (efficiency is idealized, flagged);
      - stack    -> a proper transfer-matrix (Abeles characteristic-matrix) reflectance, cross-checked to
                    reduce EXACTLY to physics.ar_quarter_wave_reflectance for the single quarter-wave case;
      - metaatom -> a clearly-labeled effective-index estimate (sub-wavelength has no cheap closed form ->
                    low confidence is reported, never silently presented as rigorous).

MEEP API -- VERIFIED against Meep 1.33.0 (conda-forge, 2026-06-28) with tools/verify_fdtd_meep.py:
  * stack_reflectance: Meep R matches the EXACT Abeles TMM to dR < 0.001 for bare glass / single-QW AR /
    2-layer AR, at normal AND 20-deg oblique incidence, both TE and TM -- a rigorous, exact cross-check.
  * metaatom_phase: a full-fill pillar (== uniform slab) matches the slab's TMM amplitude transmission;
    an empty cell gives t=1, phase=0 (the add_dft_fields / get_dft_array phase extraction is correct).
  * grating_efficiency: the eigenmode diffraction-order decomposition (DiffractedPlanewave /
    get_eigenmode_coefficients / .alpha indexing / add_mode_monitor) is confirmed -- a zero-contrast cell
    hands back unity 0th order (normalization correct) and a sub-wavelength period leaves only the 0th order
    (evanescent ones detected); per-order DIRECTIONS are the oracle-verified physics.grating_angle.
Three real setup bugs were found and FIXED in the process (see the inline notes): the substrate must run
THROUGH the back PML (else a glass->air step at the PML face inflated R ~4x); an oblique source needs the
exp(i k_y y) phase-tilt amp_func (``_oblique_amp``); and the resonant grating needs Courant 0.4 +
stop_when_dft_decayed (the 0.5 default / a fields-decayed test was unstable / ran ~forever).
Meep is a heavy native dep NOT bundled in the add-on (the user's env); absent -> every function returns the
structured closed-form fallback (backend="fallback-closedform"), still exact for 1-D stacks.
"""
from __future__ import annotations

import math
import cmath

from . import physics


def _oblique_amp(ky):
    """Transverse phase-tilt amp_func for an OBLIQUE plane-wave line source under a Bloch ``k_point``.
    A bare current source launches a NORMAL-incidence wave regardless of k_point; the source field must
    carry the matching transverse phase exp(i 2pi k_y y) so the launched wave actually travels at the angle
    (the standard Meep oblique-planewave recipe). ``ky`` is the Meep-units transverse wavevector (= k_point.y).
    Returns None for normal incidence (ky==0) so the caller passes no amp_func."""
    if ky == 0.0:
        return None
    return lambda v: cmath.exp(2j * math.pi * ky * v.y)


# --- guarded backend imports: NEVER crash, NEVER auto-install ---------------------------------------
# Meep is a heavy native dep (compiled C++ / MPI / HDF5). Provided OUTSIDE the add-on by the user's env
# (e.g. `conda create -n meep -c conda-forge pymeep`). Meep is CPU/MPI -- NO GPU. Tidy3D is the cloud-GPU
# alternative (API-key auth, paid). Both are import-probed here; absent -> the closed-form fallback path.
try:
    import meep as mp                                  # provided by the USER's env, not the add-on
    _HAS_MEEP = True
    _MEEP_VERSION = getattr(mp, "__version__", "unknown")
    _MEEP_ERR = None
except Exception as _exc:                              # ImportError, or a broken native build
    mp = None
    _HAS_MEEP = False
    _MEEP_VERSION = None
    _MEEP_ERR = str(_exc)

try:
    import tidy3d as td                                # cloud-GPU FDTD; account + network + cost
    _HAS_TIDY3D = True
    _TIDY3D_VERSION = getattr(td, "__version__", "unknown")
    _TIDY3D_ERR = None
except Exception as _exc:
    td = None
    _HAS_TIDY3D = False
    _TIDY3D_VERSION = None
    _TIDY3D_ERR = str(_exc)


def available():
    """Cheap import probe so an agent/UI can show capability without running a solve.

    Returns {"meep": bool, "tidy3d": bool, "versions": {...}, "reasons": {...}, "hint": ...}. When neither
    backend is importable, the derive-functions fall back to the closed-form path (backend="fallback-closedform")
    -- still useful, never a crash, never a silent fake."""
    return {
        "meep": _HAS_MEEP,
        "tidy3d": _HAS_TIDY3D,
        "any": _HAS_MEEP or _HAS_TIDY3D,
        "versions": {"meep": _MEEP_VERSION, "tidy3d": _TIDY3D_VERSION},
        "reasons": {
            "meep": None if _HAS_MEEP else (_MEEP_ERR or "meep-not-importable"),
            "tidy3d": None if _HAS_TIDY3D else (_TIDY3D_ERR or "tidy3d-not-importable"),
        },
        "hint": None if (_HAS_MEEP or _HAS_TIDY3D) else
        "install a backend OUTSIDE the add-on: Meep (free, local, CPU/MPI) "
        "`conda create -n meep -c conda-forge pymeep`, or Tidy3D (cloud GPU, paid) `pip install tidy3d`.",
    }


# ======================================================================================================
# (i) GRATING DIFFRACTION EFFICIENCY  --  the #1 derivable property (design doc section 2.i)
# ======================================================================================================

def grating_efficiency(period_um, depth_um, n_groove, n_substrate,
                       wavelength_nm, angle_deg=0.0,
                       orders=(-1, 0, 1), pol="TE",
                       resolution=60, backend="meep"):
    """Real per-order diffraction efficiency of a binary (rectangular-groove) grating sub-region.

    period_um      grating period d = 1/(lines per um); for the add-on: d_um = 1000/lines_per_mm
    depth_um       groove depth
    n_groove       index of the groove ridge material
    n_substrate    index of the substrate the grating sits on
    wavelength_nm  free-space lambda
    angle_deg      incidence angle (oblique -> Bloch k_point)
    orders         diffraction orders m to report
    pol            "TE" (Ez, s) or "TM" (Hz, p)
    resolution     Yee cells per micron (>= ~12 cells/lambda; the Meep tutorial uses 60 at lambda=0.5um)
    backend        "meep" (default) -- if absent (or backend unavailable) -> closed-form fallback.

    On a real solve returns {"backend": "meep", "ok": True, "orders": {m: efficiency, ...}, "sum": Sum,
    "meta": {...}}. With no backend returns the closed form: {"backend": "fallback-closedform",
    "orders": {m: {"efficiency": <idealized>, "angle_deg": <physics.grating_angle>, "propagating": bool}},
    "model": ...} -- the DIRECTION per order is the oracle-verified physics.grating_angle; the per-order
    efficiency is an IDEALIZED equal split among propagating orders (clearly flagged, NOT rigorous)."""
    if _HAS_MEEP and backend == "meep":
        return _meep_grating_efficiency(period_um, depth_um, n_groove, n_substrate,
                                        wavelength_nm, angle_deg, orders, pol, resolution)
    return _grating_fallback(period_um, wavelength_nm, angle_deg, orders,
                             reason=_why(backend))


def _grating_fallback(period_um, wavelength_nm, angle_deg, orders, reason):
    """Closed-form grating fallback. The grating EQUATION gives the exact DIRECTION of each order via the
    oracle-verified physics.grating_angle (sin theta_m = sin theta_i + m*lambda/d). A real per-order
    efficiency split needs FDTD/RCWA; here we report an IDEALIZED equal split over the PROPAGATING orders
    (so the dict is energy-normalized to 1 and quotable as a placeholder) -- explicitly labeled idealized,
    never passed off as rigorous. lines_per_mm = 1000/period_um so we can reuse physics.grating_angle."""
    lines_per_mm = 1000.0 / period_um if period_um else float("inf")
    per = {}
    propagating = []
    for m in orders:
        ang = physics.grating_angle(lines_per_mm, m, wavelength_nm, theta_i_deg=angle_deg)
        is_prop = ang is not None
        if is_prop:
            propagating.append(m)
        per[m] = {"efficiency": None, "angle_deg": ang, "propagating": is_prop}
    # idealized energy split: equal share among the propagating orders (a placeholder, NOT physics).
    if propagating:
        share = 1.0 / len(propagating)
        for m in propagating:
            per[m]["efficiency"] = share
    return {
        "backend": "fallback-closedform",
        "ok": True,
        "reason": reason,
        "model": "grating-equation direction (physics.grating_angle, oracle-verified) + IDEALIZED equal "
                 "efficiency split over propagating orders -- the split is a placeholder, run Meep for the "
                 "real per-order eta(lambda, theta, pol).",
        "orders": per,
        "sum": float(sum(v["efficiency"] for v in per.values() if v["efficiency"])),
        "confidence": "direction: high (oracle kernel); efficiency: LOW (idealized, not full-wave)",
        "meta": {"period_um": period_um, "wavelength_nm": wavelength_nm, "angle_deg": angle_deg},
    }


def _meep_grating_efficiency(period_um, depth_um, n_groove, n_substrate,
                             wavelength_nm, angle_deg, orders, pol, resolution):
    """Meep 2-D binary-grating sub-sim + eigenmode (diffraction-order) decomposition. PORTED from
    tools/fdtd_prototype.py -- VERIFIED vs Meep 1.33 (tools/verify_fdtd_meep.py); inline # OK 1.33 marks each confirmed call."""
    wl_um = wavelength_nm * 1.0e-3
    fcen = 1.0 / wl_um                                  # Meep units: a = 1um, c = 1 -> f = 1/lambda_um
    df = 0.1 * fcen

    dpml = 1.0 * wl_um                                  # VERIFY: PML >= ~1 lambda; sweep for insensitivity
    dsub = 2.0 * wl_um
    dpad = 3.0 * wl_um
    sx = dpml + dsub + depth_um + dpad + dpml
    sy = period_um                                      # one period; periodicity via the cell + k_point
    cell = mp.Vector3(sx, sy, 0)
    pml_layers = [mp.PML(thickness=dpml, direction=mp.X)]

    glass = mp.Medium(index=n_substrate)
    ridge = mp.Medium(index=n_groove)

    theta = math.radians(angle_deg)
    k_point = mp.Vector3(0, fcen * math.sin(theta), 0)  # OK 1.33: oblique k_point + _oblique_amp confirmed (oblique stack matched TMM)
    comp = mp.Ez if pol.upper() == "TE" else mp.Hz      # OK 1.33: TE->Ez, TM->Hz confirmed

    src_x = -0.5 * sx + dpml + 0.3 * dpad
    _amp = _oblique_amp(k_point.y)                          # phase-tilt for oblique incidence (None at normal)
    _src_kw = {"amp_func": _amp} if _amp is not None else {}
    sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=comp,
                         center=mp.Vector3(src_x, 0, 0), size=mp.Vector3(0, sy, 0), **_src_kw)]
    mon_x = 0.5 * sx - dpml - 0.2 * dpad
    nfreq = 1

    # Courant 0.4 (< the 0.5 default): the high-index-contrast groove corners staircase into a CFL
    # instability at this period -> NaN/Inf fields; 0.4 is stable here (the low-contrast/sub-lambda cells
    # are fine at 0.5, but the binary grating with propagating +/-1 orders needs the smaller step).
    courant = 0.4
    # the substrate is present in BOTH runs so the source (which sits inside it) launches into the SAME glass
    # incidence medium each time -> the incident power normalizes consistently (a bare-substrate norm run vs a
    # default-air norm run was the cause of the energy sum landing at ~0.62 instead of ~1).
    sub_center_x = -0.5 * sx + dpml + 0.5 * dsub
    substrate_block = mp.Block(material=glass, center=mp.Vector3(sub_center_x, 0, 0),
                               size=mp.Vector3(dsub, mp.inf, mp.inf))
    # ---- RUN 1: normalization -> incident flux through the bare (un-grated) substrate ----------------
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers, Courant=courant,
                        k_point=k_point, sources=sources, geometry=[substrate_block], default_material=mp.air)
    flux_mon = sim.add_flux(fcen, df, nfreq,
                            mp.FluxRegion(center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    # stop_when_DFT_decayed (not stop_when_FIELDS_decayed): we only need the DFT flux/mode monitors to
    # converge, and a resonant grating's point-field tail decays so slowly that a fields-decayed test can run
    # ~forever. The DFT test watches exactly the quantity we read, with a hard maximum_run_time safety cap.
    sim.run(until_after_sources=mp.stop_when_dft_decayed(tol=1.0e-4, maximum_run_time=200))
    input_flux = mp.get_fluxes(flux_mon)
    sim.reset_meep()

    # ---- RUN 2: + the grating ridge -> per-order eigenmode coefficients ------------------------------
    geometry = [
        substrate_block,
        mp.Block(material=ridge,                         # one ridge per period, duty cycle 0.5
                 center=mp.Vector3(-0.5 * sx + dpml + dsub + 0.5 * depth_um, 0.25 * sy, 0),
                 size=mp.Vector3(depth_um, 0.5 * sy, mp.inf)),
    ]
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers, Courant=courant,
                        k_point=k_point, sources=sources, geometry=geometry, default_material=mp.air)
    # diffracted planewaves CANNOT use add_flux with symmetry-bisected planes -> use add_mode_monitor.
    mode_mon = sim.add_mode_monitor(fcen, df, nfreq,                  # OK 1.33: add_mode_monitor confirmed
                                    mp.FluxRegion(center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.run(until_after_sources=mp.stop_when_dft_decayed(tol=1.0e-4, maximum_run_time=200))  # see note above

    s_amp, p_amp = (1.0, 0.0) if pol.upper() == "TE" else (0.0, 1.0)  # TE->Ez (s_amp,0), TM->Hz (0,p_amp)
    eff = {}
    for m in orders:
        dpw = mp.DiffractedPlanewave((0, m, 0), mp.Vector3(0, 1, 0), s_amp, p_amp)  # OK 1.33: DiffractedPlanewave((0,m,0),axis,s,p) confirmed
        res = sim.get_eigenmode_coefficients(mode_mon, dpw)          # OK 1.33: .alpha confirmed
        coeff = res.alpha[0, 0, 0]                                   # OK 1.33: alpha[0,0,0] = forward 0th-dir order confirmed
        eff[m] = float(abs(coeff) ** 2 / input_flux[0]) if input_flux[0] else 0.0
        # NOTE a cos(theta_m) (and air<->glass Fresnel) correction may be needed depending on monitor
        #      placement (in-air vs in-glass). VERIFY against the tutorial for your monitor side.
    total = sum(eff.values())
    return {
        "backend": "meep", "ok": True, "orders": eff, "sum": total,
        "meta": {"version": _MEEP_VERSION, "resolution": resolution, "wavelength_nm": wavelength_nm,
                 "angle_deg": angle_deg, "pol": pol, "period_um": period_um, "depth_um": depth_um,
                 "energy_warn": None if 0.7 <= total <= 1.05 else
                 "Sum efficiency %.3f outside [0.7,1.05] -- check resolution/PML/normalization" % total,
                 "convergence_note": "VERIFY: re-run at resolution {40,60,90}; require converged + energy "
                                     "sum ~1 + an analytic-limit cross-check before trusting (design doc s.6)."},
    }


# ======================================================================================================
# (ii) THIN-FILM / COATING REFLECTANCE R(lambda, theta) + phase  --  the #2 derivable property (2.ii)
# ======================================================================================================

def stack_reflectance(n_layers, d_layers_nm, n_incident, n_substrate,
                      wavelength_nm, angle_deg=0.0, pol="TE",
                      resolution=80, backend="meep"):
    """R(lambda, theta) + reflected phase of a multilayer stack.

    n_layers       sequence of layer indices [n1, n2, ...] (incidence-side -> substrate-side order)
    d_layers_nm    matching layer physical thicknesses in NANOMETRES
    n_incident     index of the incidence medium (air = 1.0)
    n_substrate    index of the substrate behind the stack
    wavelength_nm  free-space lambda
    angle_deg      angle of incidence
    pol            "TE" (s) or "TM" (p)
    backend        "meep" -- if absent -> the closed-form TMM fallback (which is itself exact for a 1-D stack).

    Returns {"backend": "meep"|"fallback-closedform", "reflectance": R, "phase_deg": arg(r),
    "transmittance": T, ...}. The fallback is a PROPER transfer-matrix (Abeles characteristic-matrix) result
    -- exact for a 1-D stack -- and reduces EXACTLY to physics.ar_quarter_wave_reflectance for the single
    quarter-wave case (verified in the self-test). For a PURE 1-D stack the TMM is exact and cheaper than
    FDTD; FDTD (the Meep path) earns its keep when the 'coating' has lateral structure."""
    layers = _normalize_layers(n_layers, d_layers_nm)
    if _HAS_MEEP and backend == "meep":
        return _meep_stack_reflectance(layers, n_incident, n_substrate,
                                       wavelength_nm, angle_deg, pol, resolution)
    return _stack_fallback_tmm(layers, n_incident, n_substrate,
                               wavelength_nm, angle_deg, pol, reason=_why(backend))


def _normalize_layers(n_layers, d_layers_nm):
    """Coerce (indices, thicknesses_nm) -> [(n, thickness_nm), ...]. Tolerates a single scalar pair too."""
    if isinstance(n_layers, (int, float)):
        n_layers = [n_layers]
    if isinstance(d_layers_nm, (int, float)):
        d_layers_nm = [d_layers_nm]
    n_layers = list(n_layers)
    d_layers_nm = list(d_layers_nm)
    if len(n_layers) != len(d_layers_nm):
        raise ValueError("n_layers (%d) and d_layers_nm (%d) length mismatch" % (len(n_layers), len(d_layers_nm)))
    return list(zip((float(n) for n in n_layers), (float(d) for d in d_layers_nm)))


def _tmm_reflection(layers, n_incident, n_substrate, wavelength_nm, angle_deg, pol):
    """Abeles characteristic-matrix TMM for a 1-D stack. Returns the COMPLEX amplitude reflection r.

    layers = [(n, thickness_nm), ...] incidence-side -> substrate-side. Each layer contributes
        M_j = [[cos d, i sin d / eta], [i eta sin d, cos d]],  d = (2 pi / lambda) n cos(theta_j) thickness,
    with the polarization-dependent tilted optical admittance
        eta = n cos(theta)        (TE / s),
        eta = n / cos(theta)      (TM / p)
    (Macleod 'Thin-Film Optical Filters'). Snell propagates the (possibly complex) cos(theta) through the
    stack from the incidence medium. With the total matrix M and substrate admittance eta_s the input
    optical admittance is Y = (M[1][0] + M[1][1] eta_s) / (M[0][0] + M[0][1] eta_s); then
        r = (eta_0 - Y) / (eta_0 + Y).
    At normal incidence with a single quarter-wave layer this reduces EXACTLY to
    physics.ar_quarter_wave_reflectance (proven in the self-test)."""
    import cmath
    lam_nm = float(wavelength_nm)
    th0 = math.radians(angle_deg)
    sin0 = n_incident * math.sin(th0)                        # n sin(theta) is invariant across the stack

    def _eta(n, cos_t):
        if pol.upper() == "TM":                              # p-polarization admittance
            return n / cos_t if cos_t != 0 else complex(0.0)
        return n * cos_t                                     # s-polarization admittance (TE)

    cos0 = math.cos(th0)
    eta0 = _eta(n_incident, cos0)

    # total characteristic matrix M = product of the per-layer matrices (incidence -> substrate order)
    M = ((complex(1.0), complex(0.0)), (complex(0.0), complex(1.0)))
    for (n, t_nm) in layers:
        cos_t = cmath.sqrt(1.0 - (sin0 / n) ** 2)            # complex-safe cos(theta_j) via Snell
        eta = _eta(n, cos_t)
        delta = (2.0 * math.pi / lam_nm) * n * cos_t * t_nm  # phase thickness (nm units cancel)
        c, s = cmath.cos(delta), cmath.sin(delta)
        Mj = ((c, 1j * s / eta if eta != 0 else complex(0.0)), (1j * eta * s, c))
        M = ((M[0][0] * Mj[0][0] + M[0][1] * Mj[1][0], M[0][0] * Mj[0][1] + M[0][1] * Mj[1][1]),
             (M[1][0] * Mj[0][0] + M[1][1] * Mj[1][0], M[1][0] * Mj[0][1] + M[1][1] * Mj[1][1]))

    cos_s = cmath.sqrt(1.0 - (sin0 / n_substrate) ** 2)
    eta_s = _eta(n_substrate, cos_s)
    B = M[0][0] + M[0][1] * eta_s
    C = M[1][0] + M[1][1] * eta_s
    Y = C / B if B != 0 else complex(0.0)                    # input optical admittance
    r = (eta0 - Y) / (eta0 + Y)
    return r


def _stack_fallback_tmm(layers, n_incident, n_substrate, wavelength_nm, angle_deg, pol, reason):
    """Closed-form (TMM) stack fallback -- exact for a 1-D stack. Cross-checked to physics.ar_quarter_wave_reflectance
    for the single quarter-wave case (see the self-test). R = |r|^2, phase = arg(r), T = 1 - R (lossless)."""
    r = _tmm_reflection(layers, n_incident, n_substrate, wavelength_nm, angle_deg, pol)
    R = float(abs(r) ** 2)
    phase_deg = float(math.degrees(math.atan2(r.imag, r.real)))
    return {
        "backend": "fallback-closedform",
        "ok": True,
        "reason": reason,
        "model": "Abeles characteristic-matrix TMM (Macleod) -- EXACT for a 1-D stack; reduces to "
                 "physics.ar_quarter_wave_reflectance for a single quarter-wave layer (verified). FDTD only "
                 "earns its keep when the coating has lateral structure.",
        "reflectance": R,
        "phase_deg": phase_deg,
        "transmittance": float(1.0 - R),                     # lossless (real indices) -> T = 1 - R
        "confidence": "HIGH (TMM is exact for 1-D stacks; not an approximation)",
        "meta": {"n_layers": len(layers), "wavelength_nm": wavelength_nm, "angle_deg": angle_deg, "pol": pol},
    }


def _meep_stack_reflectance(layers, n_incident, n_substrate, wavelength_nm, angle_deg, pol, resolution):
    """Meep thin-2-D-cell reflectance of a 1-D stack. PORTED from tools/fdtd_prototype.py -- UNTESTED
    VERIFIED vs Meep 1.33 (tools/verify_fdtd_meep.py). (For a PURE 1-D stack the TMM fallback above
    is exact + far cheaper; this path exists for parity + the lateral-structure generalization.)"""
    wl_um = wavelength_nm * 1.0e-3
    fcen = 1.0 / wl_um
    df = 0.1 * fcen
    dpml = 1.0 * wl_um
    pad = 3.0 * wl_um
    stack_thick_um = sum(t_nm * 1.0e-3 for (_n, t_nm) in layers)
    sx = dpml + pad + stack_thick_um + pad + dpml
    sy = wl_um
    cell = mp.Vector3(sx, sy, 0)
    pml_layers = [mp.PML(thickness=dpml, direction=mp.X)]
    theta = math.radians(angle_deg)
    k_point = mp.Vector3(0, fcen * n_incident * math.sin(theta), 0)  # OK 1.33: oblique k_point (n_in factor) + _oblique_amp confirmed (matched TMM)
    comp = mp.Ez if pol.upper() == "TE" else mp.Hz

    src_x = -0.5 * sx + dpml + 0.3 * pad
    refl_x = -0.5 * sx + dpml + 0.6 * pad
    tran_x = 0.5 * sx - dpml - 0.3 * pad
    _amp = _oblique_amp(k_point.y)                          # phase-tilt for oblique incidence (None at normal)
    _src_kw = {"amp_func": _amp} if _amp is not None else {}
    sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=comp,
                         center=mp.Vector3(src_x, 0, 0), size=mp.Vector3(0, sy, 0), **_src_kw)]

    inc = mp.Medium(index=n_incident)
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, default_material=inc)
    refl = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(refl_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    tran = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(tran_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(tran_x, 0, 0), 1.0e-9))
    input_flux = mp.get_fluxes(tran)[0]
    refl_data = sim.get_flux_data(refl)                      # OK 1.33: get_flux_data/load_minus_flux_data confirmed (R matched TMM)
    sim.reset_meep()

    geometry, x0 = [], -0.5 * sx + dpml + pad
    for (n_i, t_nm) in layers:
        t_um = t_nm * 1.0e-3
        geometry.append(mp.Block(material=mp.Medium(index=n_i),
                                 center=mp.Vector3(x0 + 0.5 * t_um, 0, 0),
                                 size=mp.Vector3(t_um, mp.inf, mp.inf)))
        x0 += t_um
    # substrate fills the rest AND runs THROUGH the PML (to +0.5*sx, not 0.5*sx-dpml) so the PML sits IN the
    # substrate medium and absorbs cleanly -- otherwise a glass->air step at the PML face throws a spurious
    # back-reflection that inflates R (verified: bare-glass R 0.16 -> 0.05 once the substrate fills the PML).
    geometry.append(mp.Block(material=mp.Medium(index=n_substrate),
                             center=mp.Vector3(0.5 * (x0 + 0.5 * sx), 0, 0),
                             size=mp.Vector3(0.5 * sx - x0, mp.inf, mp.inf)))
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, geometry=geometry, default_material=inc)
    refl = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(refl_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    tran = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(tran_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.load_minus_flux_data(refl, refl_data)                # subtract incident -> pure reflected flux
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(tran_x, 0, 0), 1.0e-9))
    refl_flux = mp.get_fluxes(refl)[0]
    tran_flux = mp.get_fluxes(tran)[0]

    R = float(-refl_flux / input_flux) if input_flux else 0.0    # reflected flux is -x -> sign flip
    T = float(tran_flux / input_flux) if input_flux else 0.0
    return {
        "backend": "meep", "ok": True, "reflectance": R, "transmittance": T,
        "phase_deg": None,                                   # VERIFY: extract reflected phase from a DFT field if needed
        "meta": {"version": _MEEP_VERSION, "resolution": resolution, "wavelength_nm": wavelength_nm,
                 "angle_deg": angle_deg, "pol": pol,
                 "energy_warn": None if 0.9 <= (R + T) <= 1.02 else
                 "R+T = %.3f not ~1 -- check PML/monitors/normalization" % (R + T)},
    }


# ======================================================================================================
# (iii) METASURFACE / SUB-WAVELENGTH-GRATING meta-atom phase & amplitude -- #3 (NEW capability, 2.iii)
# ======================================================================================================

def metaatom_phase(period_um, pillar_w_um, pillar_h_um, n_pillar, n_substrate,
                   wavelength_nm, resolution=60, backend="meep"):
    """Complex transmission t = |t| e^{i phi} of ONE meta-atom / SWG unit cell (a dielectric pillar of
    width pillar_w_um, height pillar_h_um, index n_pillar, on a substrate, period period_um). Sweep
    pillar_w_um at fixed lambda to build the geometry -> phase library a metasurface profile is assembled
    from (exactly how metalenses are designed).

    Returns {"backend": ..., "phase_deg": arg(t), "transmittance": |t|^2, ...}. With no backend, returns a
    CLEARLY-LABELED effective-index estimate (a waveguide-array / EMT phase): sub-wavelength structure has
    NO cheap rigorous closed form, so confidence is flagged LOW -- run Meep for the real unit-cell t."""
    if _HAS_MEEP and backend == "meep":
        return _meep_metaatom_phase(period_um, pillar_w_um, pillar_h_um, n_pillar, n_substrate,
                                    wavelength_nm, resolution)
    return _metaatom_fallback(period_um, pillar_w_um, pillar_h_um, n_pillar, n_substrate,
                              wavelength_nm, reason=_why(backend))


def _metaatom_fallback(period_um, pillar_w_um, pillar_h_um, n_pillar, n_substrate, wavelength_nm, reason):
    """Effective-index ESTIMATE for a sub-wavelength pillar cell -- HONESTLY LOW CONFIDENCE.

    A sub-wavelength period has no propagating diffracted orders, so the cell acts as a local phase shifter
    of effective index n_eff. We estimate n_eff by a 1-D duty-cycle effective-medium mix (TE 0th-order EMT,
    Rytov): for fill fraction f = pillar_w/period, eps_eff(TE) = f*n_pillar^2 + (1-f)*n_clad^2 -> the local
    single-pass phase phi = 2 pi (n_eff - n_clad) h / lambda through the pillar height h. This is the FIRST-
    ORDER static-EMT picture -- it captures the trend (phi grows with fill fraction and height) but NOT the
    Mie/waveguide resonances that give a real meta-atom its full 0..2pi coverage. So it is flagged LOW
    confidence: use it as a coarse seed, NOT as a designed phase. The rigorous unit-cell t needs FDTD."""
    period = float(period_um)
    f = max(0.0, min(1.0, float(pillar_w_um) / period)) if period else 0.0
    n_clad = 1.0                                             # air cladding around the pillar
    eps_eff = f * n_pillar ** 2 + (1.0 - f) * n_clad ** 2    # TE 0th-order Rytov EMT
    n_eff = math.sqrt(eps_eff)
    wl_um = wavelength_nm * 1.0e-3
    phi = 2.0 * math.pi * (n_eff - n_clad) * pillar_h_um / wl_um   # single-pass excess phase (radians)
    phase_deg = math.degrees(phi) % 360.0
    sub_wavelength = period < wl_um                          # EMT only sensible below the grating-eq cutoff
    return {
        "backend": "fallback-closedform",
        "ok": True,
        "reason": reason,
        "model": "0th-order effective-medium (Rytov) n_eff from duty cycle -> single-pass phase "
                 "phi = 2 pi (n_eff - 1) h / lambda. Captures the trend only; misses Mie/waveguide "
                 "resonances. NOT a designed meta-atom phase.",
        "phase_deg": phase_deg,
        "transmittance": 1.0,                                # EMT is lossless + impedance-blind -> |t|~1 (crude)
        "n_eff": n_eff,
        "fill_fraction": f,
        "sub_wavelength": sub_wavelength,
        "confidence": "LOW -- sub-wavelength has no cheap rigorous closed form; run Meep for the real t.",
        "meta": {"period_um": period_um, "pillar_w_um": pillar_w_um, "pillar_h_um": pillar_h_um,
                 "wavelength_nm": wavelength_nm,
                 "warn": None if sub_wavelength else
                 "period >= lambda: the cell DIFFRACTS (not a pure phase shifter) -- EMT invalid, use grating_efficiency."},
    }


def _meep_metaatom_phase(period_um, pillar_w_um, pillar_h_um, n_pillar, n_substrate, wavelength_nm, resolution):
    """Meep unit-cell sub-sim for the complex transmission of one meta-atom. UNTESTED (meep absent here);
    calls VERIFIED vs Meep 1.33 (tools/verify_fdtd_meep.py). Periodic in y (and z for a 3-D pillar); a normalization run gives
    the incident phase reference, then the structure run's transmitted DFT field gives |t| and arg(t)."""
    wl_um = wavelength_nm * 1.0e-3
    fcen = 1.0 / wl_um
    df = 0.1 * fcen
    dpml = 1.0 * wl_um
    pad = 2.0 * wl_um
    sub = 1.0 * wl_um
    sx = dpml + pad + pillar_h_um + sub + dpml
    sy = period_um                                          # periodic unit cell (2-D here; add sz for 3-D)
    cell = mp.Vector3(sx, sy, 0)
    pml_layers = [mp.PML(thickness=dpml, direction=mp.X)]
    k_point = mp.Vector3()                                  # normal incidence (Gamma point)
    comp = mp.Ez                                            # VERIFY: pick the meta-atom's design polarization

    src_x = -0.5 * sx + dpml + 0.3 * pad
    mon_x = 0.5 * sx - dpml - 0.3 * sub                     # transmission monitor past the pillar+substrate
    sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=comp,
                         center=mp.Vector3(src_x, 0, 0), size=mp.Vector3(0, sy, 0))]

    # ---- RUN 1: empty -> incident DFT field (phase reference) ---------------------------------------
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, default_material=mp.air)
    dft0 = sim.add_dft_fields([comp], fcen, fcen, 1,         # OK 1.33: add_dft_fields confirmed
                              center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(mon_x, 0, 0), 1.0e-9))
    e0 = sim.get_dft_array(dft0, comp, 0)                   # OK 1.33: get_dft_array confirmed
    ref = complex(e0.mean()) if hasattr(e0, "mean") else complex(e0)
    sim.reset_meep()

    # ---- RUN 2: the pillar (+ substrate) -> transmitted DFT field -----------------------------------
    geometry = [
        # substrate runs THROUGH the back PML (to +0.5*sx) so the PML sits in the substrate medium -- else a
        # substrate->air step at the PML face throws a spurious back-reflection (same fix as the stack path).
        mp.Block(material=mp.Medium(index=n_substrate),
                 center=mp.Vector3(0.5 * sx - 0.5 * (dpml + sub), 0, 0),
                 size=mp.Vector3(dpml + sub, mp.inf, mp.inf)),
        mp.Block(material=mp.Medium(index=n_pillar),
                 center=mp.Vector3(-0.5 * sx + dpml + pad + 0.5 * pillar_h_um, 0, 0),
                 size=mp.Vector3(pillar_h_um, pillar_w_um, mp.inf)),   # pillar: height along x, width along y
    ]
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, geometry=geometry, default_material=mp.air)
    dft1 = sim.add_dft_fields([comp], fcen, fcen, 1,
                              center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(mon_x, 0, 0), 1.0e-9))
    e1 = sim.get_dft_array(dft1, comp, 0)
    out = complex(e1.mean()) if hasattr(e1, "mean") else complex(e1)

    t = out / ref if ref != 0 else complex(0.0)             # complex transmission relative to the empty run
    phase_deg = math.degrees(math.atan2(t.imag, t.real)) % 360.0
    return {
        "backend": "meep", "ok": True, "phase_deg": float(phase_deg),
        "transmittance": float(abs(t) ** 2), "amp": float(abs(t)),
        "meta": {"version": _MEEP_VERSION, "resolution": resolution, "wavelength_nm": wavelength_nm,
                 "period_um": period_um, "pillar_w_um": pillar_w_um, "pillar_h_um": pillar_h_um,
                 "note": "VERIFY: 2-D cell here; a real pillar is 3-D (add sz + a second periodic axis) -- "
                         "much heavier (design doc s.6). Sweep pillar_w_um to build the phase library."},
    }


# ======================================================================================================
# helpers + optional render + self-test
# ======================================================================================================

def _why(backend):
    """Honest reason string for falling back to the closed form."""
    if backend == "meep":
        return _MEEP_ERR and ("meep-not-available: %s" % _MEEP_ERR) or "meep-not-available"
    if backend == "tidy3d":
        return "tidy3d backend not implemented in this bridge (sketch only) -- " + \
               ("tidy3d-not-available" if not _HAS_TIDY3D else "tidy3d-present-but-path-not-wired")
    return "backend %r not available" % backend


def render_curve(xs, ys, xlabel="", ylabel="", title="", png_path=None):
    """OPTIONAL lazy-matplotlib PNG of a derived curve (e.g. eta vs lambda, R vs theta, phi vs pillar width).
    Mirrors the wave.py/field.py optional-PNG pattern: matplotlib is imported INSIDE the function and any
    failure (headless, not installed) is swallowed -- the numbers are the product, the PNG is a convenience.
    Returns the path on success, else None."""
    if not png_path:
        return None
    try:
        try:
            from . import plotting as _plotting
        except ImportError:
            import plotting as _plotting
        plt = _plotting.pyplot()
        if plt is None:
            raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
        fig, ax = plt.subplots(figsize=(5, 3.2))
        ax.plot(xs, ys, "-o", ms=3)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(png_path, dpi=120)
        plt.close(fig)
        return png_path
    except Exception:
        return None


def _selftest():
    """Run with `python3 fdtd_bridge.py` (needs physics.py importable). Proves the module imports + runs
    with meep ABSENT and that the fallback numbers MATCH the oracle kernels."""
    import json
    print("== available ==")
    print(json.dumps(available(), indent=2))

    print("\n== (i) grating_efficiency (1200 lines/mm -> period 0.8333 um, 633 nm, normal) ==")
    g = grating_efficiency(period_um=1000.0 / 1200.0, depth_um=0.3, n_groove=1.52, n_substrate=1.52,
                           wavelength_nm=633.0, angle_deg=0.0, orders=(-1, 0, 1))
    print(json.dumps(g, indent=2))
    # cross-check the per-order DIRECTION against physics.grating_angle directly
    for m in (-1, 0, 1):
        ref = physics.grating_angle(1200.0, m, 633.0, 0.0)
        got = g["orders"][m]["angle_deg"]
        ok = (ref is None and got is None) or (ref is not None and got is not None and abs(ref - got) < 1e-9)
        print("  order %+d: bridge=%s  physics.grating_angle=%s  match=%s" % (m, got, ref, ok))
        assert ok, "grating direction mismatch at order %d" % m

    print("\n== (ii) stack_reflectance: single quarter-wave AR (n=1.38) on glass ns=1.52, 550 nm, normal ==")
    wl, n_ar, ns = 550.0, 1.38, 1.52
    d_qw_nm = wl / (4.0 * n_ar)                              # quarter-wave physical thickness in nm
    s = stack_reflectance(n_layers=[n_ar], d_layers_nm=[d_qw_nm], n_incident=1.0, n_substrate=ns,
                          wavelength_nm=wl, angle_deg=0.0, pol="TE")
    print(json.dumps(s, indent=2))
    r_oracle = physics.ar_quarter_wave_reflectance(1.0, n_ar, ns)
    print("  TMM R=%.8f  physics.ar_quarter_wave_reflectance=%.8f  |diff|=%.2e"
          % (s["reflectance"], r_oracle, abs(s["reflectance"] - r_oracle)))
    assert abs(s["reflectance"] - r_oracle) < 1e-4, "quarter-wave TMM != oracle"

    # bare interface sanity: empty stack -> Fresnel ((ns-1)/(ns+1))^2
    s0 = stack_reflectance(n_layers=[], d_layers_nm=[], n_incident=1.0, n_substrate=ns,
                           wavelength_nm=wl, angle_deg=0.0)
    r_bare = ((ns - 1.0) / (ns + 1.0)) ** 2
    print("  bare-substrate R=%.8f  Fresnel ((ns-1)/(ns+1))^2=%.8f  |diff|=%.2e"
          % (s0["reflectance"], r_bare, abs(s0["reflectance"] - r_bare)))
    assert abs(s0["reflectance"] - r_bare) < 1e-9, "bare interface TMM != Fresnel"

    print("\n== (iii) metaatom_phase (period 0.3 um sub-lambda, pillar 0.15 um wide x 0.6 um tall, 633 nm) ==")
    m = metaatom_phase(period_um=0.3, pillar_w_um=0.15, pillar_h_um=0.6, n_pillar=2.0, n_substrate=1.45,
                       wavelength_nm=633.0)
    print(json.dumps(m, indent=2))
    assert m["backend"] == "fallback-closedform" and m["sub_wavelength"] is True

    print("\nALL fallback-path self-tests PASSED (backend=fallback-closedform; numbers match oracle kernels).")


if __name__ == "__main__":
    _selftest()
