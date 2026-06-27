#!/usr/bin/env python3
"""fdtd_prototype.py -- STANDALONE Meep orchestration prototype (NOT imported by the add-on).

This is the runnable companion to docs/FDTD_ORCHESTRATION.md. It drives a mature full-wave engine
(Meep) over ONE sub-region to DERIVE a real, lambda/theta-resolved EFFECTIVE PROPERTY that the lumped
ray/Gaussian tracer would then use unchanged. It does NOT reimplement FDTD and does NOT touch the live
tracer or any bpy state.

================================  IMPORTANT -- READ  ================================
UNTESTED: `meep` is NOT installed in the environment this file was written in. The Meep API calls below
are written from the documented Meep Python API:
  * Mode-Decomposition tutorial:  https://meep.readthedocs.io/en/latest/Python_Tutorials/Mode_Decomposition/
  * Example:                       NanoComp/meep  python/examples/binary_grating.py
They MUST be confirmed against the installed Meep version. Every spot that is API-version-sensitive is
marked `# VERIFY:` inline. Do NOT install Meep from this script -- if it is absent, the functions return a
structured {"ok": False, ...} dict and fall back to the lumped closed form.

Distribution note (mirrors the GPU/native-lib policy): Meep is a HEAVY native dependency (compiled C++ /
MPI / HDF5) and is NEVER bundled in the Blender listed extension. The user provides it in their own env
(e.g. `conda create -n meep -c conda-forge pymeep`). Meep is CPU/MPI -- NO GPU. The cloud-GPU alternative
is Tidy3D (`import tidy3d`, API-key auth, paid) -- sketched at the bottom, not implemented here.

Run:  python3 tools/fdtd_prototype.py        # prints capability + a grating + a thin-film demo
"""
from __future__ import annotations

import json
import math

# --- guarded import: NEVER crash, NEVER auto-install --------------------------------------------------
try:
    import meep as mp
    _HAVE_MEEP = True
    _MEEP_VERSION = getattr(mp, "__version__", "unknown")
except Exception as _exc:                      # ImportError, or a broken native build
    mp = None
    _HAVE_MEEP = False
    _MEEP_VERSION = None
    _IMPORT_ERR = str(_exc)


def available():
    """Cheap import probe so an agent/UI can show capability without running a solve."""
    return {
        "ok": _HAVE_MEEP,
        "backend": "meep",
        "version": _MEEP_VERSION,
        "reason": None if _HAVE_MEEP else "meep-not-importable",
        "hint": None if _HAVE_MEEP else
        "install OUTSIDE the add-on, e.g. `conda create -n meep -c conda-forge pymeep`",
    }


# ======================================================================================================
# (i) GRATING DIFFRACTION EFFICIENCY  --  the #1 derivable property (see design doc section 2)
# ======================================================================================================

def fdtd_grating_efficiency(period_um, depth_um, n_groove, n_substrate,
                            wavelength_nm, angle_deg=0.0,
                            orders=(-1, 0, 1), pol="TE",
                            resolution=60):
    """Real per-order diffraction efficiency of a binary (rectangular-groove) grating, via a 2-D Meep
    sub-sim + eigenmode (diffraction-order) decomposition.

    period_um   grating period d = 1/(lines per um); for the add-on: d_um = 1000/lines_per_mm
    depth_um    groove depth
    n_groove    index of the groove ridge material (e.g. the substrate index, or a resist)
    n_substrate index of the substrate the grating sits on
    wavelength_nm  free-space lambda
    angle_deg   incidence angle (oblique -> Bloch k_point)
    orders      diffraction orders m to report
    pol         "TE" (Ez, s) or "TM" (Hz, p)  # VERIFY component<->pol mapping for your convention
    resolution  Yee cells per micron (>= ~12 cells/lambda; tutorial uses 60 at lambda=0.5um)

    Returns {"ok": True, "orders": {m: eff}, "sum": Σeff, "meta": {...}} on success, else the
    structured fallback dict (lumped closed form -- direction only, flat efficiency).
    """
    if not _HAVE_MEEP:
        return _grating_fallback(period_um, wavelength_nm, angle_deg, orders, reason="meep-not-available")

    # ----- units: Meep is dimensionless with a chosen length unit a. Use a = 1 um, so all lengths are in
    #       um and frequency f = a/lambda = 1/lambda_um (c = 1). ------------------------------------------
    wl_um = wavelength_nm * 1.0e-3
    fcen = 1.0 / wl_um                                  # center frequency in Meep units (c=1, a=1um)
    df = 0.1 * fcen                                     # modest bandwidth for a GaussianSource pulse

    # ----- cell geometry: x = propagation (PML both ends), y = periodic (one grating period) ------------
    dpml = 1.0 * wl_um                                  # VERIFY: PML >= ~1 lambda; sweep for insensitivity
    dsub = 2.0 * wl_um                                  # substrate thickness inside the cell
    dpad = 3.0 * wl_um                                  # air padding to the monitors (far enough for modes)
    sx = dpml + dsub + depth_um + dpad + dpml
    sy = period_um                                      # one period; periodicity via the cell + k_point
    cell = mp.Vector3(sx, sy, 0)
    pml_layers = [mp.PML(thickness=dpml, direction=mp.X)]

    glass = mp.Medium(index=n_substrate)
    ridge = mp.Medium(index=n_groove)

    # ----- oblique incidence -> Bloch k_point. For angle theta in the x-y plane, the transverse wavevector
    #       k_y = (n_in) * fcen * sin(theta). Incidence is from the +x side through air (n_in = 1). -------
    theta = math.radians(angle_deg)
    k_point = mp.Vector3(0, fcen * math.sin(theta), 0)   # VERIFY: sign/convention of k_point for oblique

    # ----- source: a planewave line at fixed x, spanning the full y (one period). TE => Ez, TM => Hz. ----
    comp = mp.Ez if pol.upper() == "TE" else mp.Hz       # VERIFY: TE/TM <-> Ez/Hz for your s/p convention
    src_x = -0.5 * sx + dpml + 0.3 * dpad                 # just inside the PML, in air, on the +x-incidence side
    sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df),
                         component=comp,
                         center=mp.Vector3(src_x, 0, 0),
                         size=mp.Vector3(0, sy, 0))]

    mon_x = 0.5 * sx - dpml - 0.2 * dpad                  # transmission monitor in the substrate-side air/glass
    nfreq = 1                                             # single wavelength here; widen for a lambda-curve

    # ---------- RUN 1: normalization (empty, homogeneous) -> incident flux ------------------------------
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources,
                        default_material=mp.air)          # VERIFY: empty cell material for normalization
    # a flux monitor for the source power; mode monitor used in run 2 (diffracted planewaves need add_mode_monitor)
    flux_mon = sim.add_flux(fcen, df, nfreq,
                            mp.FluxRegion(center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(
        50, comp, mp.Vector3(mon_x, 0, 0), 1.0e-9))       # VERIFY: decay point/threshold for clean flux
    input_flux = mp.get_fluxes(flux_mon)                  # list, one per freq
    sim.reset_meep()

    # ---------- RUN 2: the grating structure -> per-order eigenmode coefficients ------------------------
    # substrate block (fills the substrate region) + the periodic groove ridge sitting on top of it.
    sub_center_x = -0.5 * sx + dpml + 0.5 * dsub
    geometry = [
        mp.Block(material=glass, center=mp.Vector3(sub_center_x, 0, 0),
                 size=mp.Vector3(dsub, mp.inf, mp.inf)),
        # one rectangular ridge per period spanning half the period (duty cycle 0.5); periodicity tiles it.
        mp.Block(material=ridge,
                 center=mp.Vector3(-0.5 * sx + dpml + dsub + 0.5 * depth_um, 0.25 * sy, 0),
                 size=mp.Vector3(depth_um, 0.5 * sy, mp.inf)),   # VERIFY: duty cycle / ridge placement
    ]
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, geometry=geometry,
                        default_material=mp.air)
    # diffracted planewaves CANNOT use add_flux with symmetry-bisected planes -> use add_mode_monitor.
    mode_mon = sim.add_mode_monitor(fcen, df, nfreq,
                                    mp.FluxRegion(center=mp.Vector3(mon_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(
        50, comp, mp.Vector3(mon_x, 0, 0), 1.0e-9))

    s_amp, p_amp = (1.0, 0.0) if pol.upper() == "TE" else (0.0, 1.0)   # VERIFY: s/p amplitude assignment
    eff = {}
    for m in orders:
        # a diffracted planewave of order m in the periodic (y) direction; axis = the plane-of-incidence axis.
        dpw = mp.DiffractedPlanewave((0, m, 0), mp.Vector3(0, 1, 0), s_amp, p_amp)  # VERIFY: arg order/semantics
        res = sim.get_eigenmode_coefficients(mode_mon, dpw)             # VERIFY: returns .alpha
        # alpha shape ~ [band, freq, direction]; [0,0,0] = this single planewave, first freq, forward dir.
        coeff = res.alpha[0, 0, 0]                                      # VERIFY: index layout/forward dir
        eff[m] = float(abs(coeff) ** 2 / input_flux[0]) if input_flux[0] else 0.0
        # NOTE: a cos(theta_m) (and air<->glass Fresnel) correction may be needed depending on monitor
        #       placement (in-air vs in-glass). VERIFY against the tutorial for your monitor side.

    total = sum(eff.values())
    return {
        "ok": True,
        "orders": eff,
        "sum": total,                                  # energy check: should approach 1 - absorption
        "meta": {"backend": "meep", "version": _MEEP_VERSION, "resolution": resolution,
                 "wavelength_nm": wavelength_nm, "angle_deg": angle_deg, "pol": pol,
                 "period_um": period_um, "depth_um": depth_um,
                 "energy_warn": None if 0.7 <= total <= 1.05 else
                 "Sum efficiency %.3f outside [0.7,1.05] -- check resolution/PML/normalization" % total},
    }


def _grating_fallback(period_um, wavelength_nm, angle_deg, orders, reason):
    """Lumped closed-form fallback: the grating EQUATION gives the DIRECTION of each order (the verified
    physics.grating_angle), but NOT a real efficiency split. We return the per-order diffraction ANGLE and
    mark efficiency as None ('idealized -- single user order in the live trace'). No FDTD -> honest about it."""
    d_um = period_um
    out_orders = {}
    s_i = math.sin(math.radians(angle_deg))
    for m in orders:
        s_m = s_i + m * (wavelength_nm * 1.0e-3) / d_um   # sin(theta_m) = sin(theta_i) + m*lambda/d
        out_orders[m] = {
            "efficiency": None,                            # NOT derivable without FDTD
            "angle_deg": math.degrees(math.asin(s_m)) if abs(s_m) <= 1.0 else None,  # None = evanescent
        }
    return {"ok": False, "reason": reason, "fallback": {"model": "grating-equation (direction only)",
            "orders": out_orders}}


# ======================================================================================================
# (ii) THIN-FILM / COATING REFLECTANCE R(lambda, theta)  --  the #2 derivable property
# ======================================================================================================

def fdtd_stack_reflectance(layers, wavelength_nm, angle_deg=0.0, pol="TE", resolution=80):
    """R(lambda, theta) of a 1-D multilayer stack `layers` = [(index, thickness_um), ...] via a thin 2-D
    Meep cell: a normalization run (no stack) for incident flux, then a run with the stack; R = reflected
    flux / incident flux. (NB: for a PURE 1-D stack the transfer-matrix method is cheaper and exact -- FDTD
    earns its keep when the 'coating' has lateral structure. This is the cross-check path of the design doc.)

    Returns {"ok": True, "R": ..., "T": ..., "meta": {...}} or the closed-form fallback.
    """
    if not _HAVE_MEEP:
        return _stack_fallback(layers, wavelength_nm, reason="meep-not-available")

    wl_um = wavelength_nm * 1.0e-3
    fcen = 1.0 / wl_um
    df = 0.1 * fcen
    dpml = 1.0 * wl_um
    pad = 3.0 * wl_um
    stack_thick = sum(t for (_n, t) in layers)
    sx = dpml + pad + stack_thick + pad + dpml
    sy = wl_um                                          # transversely uniform; small periodic cell
    cell = mp.Vector3(sx, sy, 0)
    pml_layers = [mp.PML(thickness=dpml, direction=mp.X)]
    theta = math.radians(angle_deg)
    k_point = mp.Vector3(0, fcen * math.sin(theta), 0)  # VERIFY oblique convention
    comp = mp.Ez if pol.upper() == "TE" else mp.Hz

    src_x = -0.5 * sx + dpml + 0.3 * pad
    refl_x = -0.5 * sx + dpml + 0.6 * pad               # REFLECTION monitor: between source and stack
    tran_x = 0.5 * sx - dpml - 0.3 * pad                # TRANSMISSION monitor: past the stack
    sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=comp,
                         center=mp.Vector3(src_x, 0, 0), size=mp.Vector3(0, sy, 0))]

    # --- RUN 1: empty -> incident flux; capture reflected-flux Fourier fields to SUBTRACT in run 2 -------
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, default_material=mp.air)
    refl = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(refl_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    tran = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(tran_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(tran_x, 0, 0), 1.0e-9))
    input_flux = mp.get_fluxes(tran)[0]
    refl_data = sim.get_flux_data(refl)                 # VERIFY: get_flux_data / load_minus_flux_data names
    sim.reset_meep()

    # --- RUN 2: the stack; subtract the run-1 incident field at the reflection monitor to isolate R ------
    geometry, x0 = [], -0.5 * sx + dpml + pad
    for (n_i, t_i) in layers:
        geometry.append(mp.Block(material=mp.Medium(index=n_i),
                                 center=mp.Vector3(x0 + 0.5 * t_i, 0, 0),
                                 size=mp.Vector3(t_i, mp.inf, mp.inf)))
        x0 += t_i
    sim = mp.Simulation(resolution=resolution, cell_size=cell, boundary_layers=pml_layers,
                        k_point=k_point, sources=sources, geometry=geometry, default_material=mp.air)
    refl = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(refl_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    tran = sim.add_flux(fcen, df, 1, mp.FluxRegion(center=mp.Vector3(tran_x, 0, 0), size=mp.Vector3(0, sy, 0)))
    sim.load_minus_flux_data(refl, refl_data)           # subtract incident -> pure reflected flux
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, comp, mp.Vector3(tran_x, 0, 0), 1.0e-9))
    refl_flux = mp.get_fluxes(refl)[0]
    tran_flux = mp.get_fluxes(tran)[0]

    R = float(-refl_flux / input_flux) if input_flux else 0.0   # reflected flux is negative-x -> sign flip
    T = float(tran_flux / input_flux) if input_flux else 0.0
    return {"ok": True, "R": R, "T": T,
            "meta": {"backend": "meep", "version": _MEEP_VERSION, "resolution": resolution,
                     "wavelength_nm": wavelength_nm, "angle_deg": angle_deg, "pol": pol,
                     "energy_warn": None if 0.9 <= (R + T) <= 1.02 else
                     "R+T = %.3f not ~1 -- check PML/monitors/normalization" % (R + T)}}


def _stack_fallback(layers, wavelength_nm, reason):
    """Closed-form fallback for a SINGLE quarter-wave AR layer (the verified physics.ar_quarter_wave_reflectance
    formula, inlined to keep this file standalone). Multilayer stacks need FDTD/TMM -> honestly flagged."""
    R = None
    if len(layers) == 1:
        n1 = layers[0][0]
        n0, ns = 1.0, 1.52                              # air -> layer -> a typical glass substrate
        den = n0 * ns + n1 * n1
        R = ((n0 * ns - n1 * n1) / den) ** 2 if den else 0.0
    return {"ok": False, "reason": reason,
            "fallback": {"model": "single quarter-wave AR (Born&Wolf) -- multilayer needs FDTD/TMM",
                         "R_single_qwl": R}}


# ======================================================================================================
# Tidy3D ALTERNATIVE (cloud-GPU, paid) -- SKETCH ONLY, not implemented. See design doc section 3.
# ======================================================================================================
# import tidy3d as td
# import tidy3d.web as web
# web.configure("<API-KEY>")                                  # API-key auth; account + network required
# sim = td.Simulation(size=..., grid_spec=..., structures=[...], sources=[...],
#                     monitors=[td.DiffractionMonitor(center=..., size=..., freqs=[fcen], name="diff")],
#                     boundary_spec=...)                       # periodic in y, PML in x
# sim_data = web.run(sim, task_name="grating_eff", path="data/sim.hdf5")   # uploads, runs on cloud GPU
# diff = sim_data["diff"]                                     # td.DiffractionData
# eff_m = diff.power[...]  # per-order efficiency  # VERIFY: DiffractionData accessor names per td version
# Pros: real GPU FDTD, no local native build. Cons: paid, network, account. Same bridge API, backend="tidy3d".


# ======================================================================================================
def _demo():
    print("== fdtd_prototype capability probe ==")
    print(json.dumps(available(), indent=2))

    print("\n== (i) grating efficiency: 1200 lines/mm (period 0.8333 um), 633 nm, normal, depth 0.3 um ==")
    g = fdtd_grating_efficiency(period_um=1000.0 / 1200.0, depth_um=0.3,
                                n_groove=1.52, n_substrate=1.52,
                                wavelength_nm=633.0, angle_deg=0.0, orders=(-1, 0, 1))
    print(json.dumps(g, indent=2))

    print("\n== (ii) thin-film: single quarter-wave AR (n=1.38, t=lambda/4n) on glass, 550 nm ==")
    wl, n_ar = 550.0, 1.38
    t_qw = (wl * 1.0e-3) / (4.0 * n_ar)                 # quarter-wave optical thickness in um
    r = fdtd_stack_reflectance(layers=[(n_ar, t_qw)], wavelength_nm=wl, angle_deg=0.0)
    print(json.dumps(r, indent=2))

    if not _HAVE_MEEP:
        print("\n[note] meep absent -> the two demos returned the structured closed-form fallback "
              "(honest, no crash). Install meep OUTSIDE the add-on to get the real full-wave numbers.")


if __name__ == "__main__":
    _demo()
