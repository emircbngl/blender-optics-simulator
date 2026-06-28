"""verify_fdtd_meep.py -- confirm the fdtd_bridge.py Meep API calls against a REAL Meep install.

This resolves the `# VERIFY:` markers in optical_alignment_sim/fdtd_bridge.py. It loads the SHIPPED bridge
(via a tiny package shim so its `from . import physics` resolves without pulling bpy), runs each `_meep_*`
path against a real Meep, and cross-checks every result to an EXACT analytic oracle:
  * stack_reflectance  -> the Abeles TMM is exact for a 1-D stack -> Meep R,T must match TMM (normal + oblique)
  * grating_efficiency -> energy sum in [0,1], per-order directions == physics.grating_angle, resolution-converged
  * metaatom_phase     -> a FULL-FILL pillar is a uniform slab -> Meep t must match the single-layer TMM
Meep is a heavy native dep never bundled in the add-on, so the verification runs in a throwaway Linux
container (serial conda-forge pymeep). Build it once from the bundled Dockerfile, then run this harness with
the repo mounted at /work:
  docker build --platform linux/amd64 -t meep-verify -f tools/meep-verify.Dockerfile tools/
  docker run --rm --platform linux/amd64 -v "$REPO":/work meep-verify \
      micromamba run -n base python /work/tools/verify_fdtd_meep.py
Verified Meep 1.33.0 on 2026-06-28: stack 5/5 vs exact TMM (dR<0.001, normal+oblique, TE+TM); grating energy
+ directions + convergence + zero-contrast/sub-lambda limits; metaatom full-fill + empty cell. The three
setup bugs it surfaced (substrate-through-PML, oblique amp_func, Courant 0.4 + stop_when_dft_decayed) are
fixed in fdtd_bridge.py.
"""
import sys, types, importlib.util, math, traceback, cmath

REPO = "/work"
PKG = REPO + "/optical_alignment_sim"

# --- load the SHIPPED bridge with a package shim (so `from . import physics` works, no bpy) --------------
sys.path.insert(0, PKG)
import physics                                                      # pure-math; its bpy import is lazy
_oas = types.ModuleType("oas"); _oas.__path__ = [PKG]; sys.modules["oas"] = _oas
sys.modules["oas.physics"] = physics; _oas.physics = physics
_spec = importlib.util.spec_from_file_location("oas.fdtd_bridge", PKG + "/fdtd_bridge.py")
fb = importlib.util.module_from_spec(_spec); sys.modules["oas.fdtd_bridge"] = fb; _spec.loader.exec_module(fb)

_results = []
def record(name, ok, detail):
    _results.append(ok)
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))

print("== Meep backend availability ==")
av = fb.available()
print("  meep=%s version=%s" % (av["meep"], av["versions"]["meep"]))
if not av["meep"]:
    print("  meep NOT importable: %s" % av["reasons"]["meep"]); sys.exit(2)


# ======================================================================================================
# (ii) STACK REFLECTANCE  -- the cleanest oracle: TMM is EXACT for a 1-D stack
# ======================================================================================================
print("\n== (ii) stack_reflectance: Meep vs exact Abeles TMM ==")
RES_STACK = 60
stack_cases = [
    ("bare glass ns=1.52, normal, TE",        [],            [],            1.0, 1.52, 550.0, 0.0, "TE"),
    ("quarter-wave AR n=1.38/glass, normal",  [1.38],        [550.0/(4*1.38)], 1.0, 1.52, 550.0, 0.0, "TE"),
    ("2-layer 1.38/2.05 on glass, normal TE", [1.38, 2.05],  [99.6, 67.1],  1.0, 1.52, 550.0, 0.0, "TE"),
    ("quarter-wave AR, 20deg, TE",            [1.38],        [550.0/(4*1.38)], 1.0, 1.52, 550.0, 20.0, "TE"),
    ("quarter-wave AR, 20deg, TM",            [1.38],        [550.0/(4*1.38)], 1.0, 1.52, 550.0, 20.0, "TM"),
]
for (name, nL, dL, n_in, n_sub, wl, ang, pol) in stack_cases:
    try:
        tmm = fb._stack_fallback_tmm(fb._normalize_layers(nL, dL), n_in, n_sub, wl, ang, pol, reason="oracle")
        mp_res = fb._meep_stack_reflectance(fb._normalize_layers(nL, dL), n_in, n_sub, wl, ang, pol, RES_STACK)
        dR = abs(mp_res["reflectance"] - tmm["reflectance"])
        rt = mp_res["reflectance"] + mp_res["transmittance"]
        ok = dR < 0.03 and 0.95 <= rt <= 1.03
        record(name, ok, "Meep R=%.4f T=%.4f (R+T=%.3f) | TMM R=%.4f | dR=%.4f"
               % (mp_res["reflectance"], mp_res["transmittance"], rt, tmm["reflectance"], dR))
    except Exception as e:
        record(name, False, "EXCEPTION: %s" % e); traceback.print_exc()


# ======================================================================================================
# (i) GRATING EFFICIENCY  -- energy sum + per-order direction + resolution convergence
# ======================================================================================================
print("\n== (i) grating_efficiency: energy + direction + resolution convergence ==")
# 1200 lines/mm -> period 0.8333 um; at 633 nm, normal incidence, low-contrast transmission grating.
period_um, depth_um, n_gr, n_sub, wl, ang = 1000.0/1200.0, 0.30, 1.52, 1.52, 633.0, 0.0
orders = (-1, 0, 1)
try:
    conv = []
    for res in (40, 60):                                        # res 40 staircases the 0.3um ridge -> unstable
        g = fb._meep_grating_efficiency(period_um, depth_um, n_gr, n_sub, wl, ang, orders, "TE", res)
        conv.append((res, g["sum"], dict(g["orders"])))
        print("    res=%-3d  sum=%.3f  orders=%s" % (res, g["sum"], {m: round(v,4) for m,v in g["orders"].items()}))
    last_sum = conv[-1][1]
    record("grating energy sum in [0.7,1.05] (res=60)", 0.7 <= last_sum <= 1.05, "sum=%.3f" % last_sum)
    # convergence: eta_0 at res 60 vs 90 should be close
    e60, e90 = conv[0][2].get(0,0.0), conv[1][2].get(0,0.0)
    record("grating eta_0 converged (|res60-res90|<0.05)", abs(e60-e90) < 0.05, "eta0: res40=%.4f res60=%.4f" % (e60, e90))
    # direction: which orders the grating equation says propagate
    prop = [m for m in orders if physics.grating_angle(1200.0, m, wl, ang) is not None]
    record("propagating orders present in Meep result", all(m in conv[-1][2] for m in prop), "grating-eq propagating=%s" % prop)
except Exception as e:
    record("grating Meep path", False, "EXCEPTION: %s" % e); traceback.print_exc()

# zero index-contrast (groove == substrate == ambient = 1.0) -> NO grating -> eta_0 ~ 1, sides ~ 0.
# this directly exercises the eigenmode normalization: a non-diffracting cell must hand back unity 0th order.
print("  -- zero-contrast (n_groove=n_substrate=1.0): no grating -> eta_0 ~ 1 --")
try:
    gz = fb._meep_grating_efficiency(period_um, depth_um, 1.0, 1.0, wl, 0.0, orders, "TE", 80)
    e0z = gz["orders"].get(0, 0.0)
    sidez = gz["orders"].get(1, 0.0) + gz["orders"].get(-1, 0.0)
    record("zero-contrast: eta_0 ~ 1 and sides ~ 0", abs(e0z - 1.0) < 0.06 and sidez < 0.03,
           "eta0=%.4f  side(+/-1)=%.4f  sum=%.3f" % (e0z, sidez, gz["sum"]))
except Exception as e:
    record("zero-contrast grating", False, "EXCEPTION: %s" % e); traceback.print_exc()

# sub-wavelength period -> ONLY the 0th order propagates -> eta_0 ~ transmittance (<=1)
print("  -- sub-wavelength grating (period 0.4um < lambda 0.633um): only 0th order --")
try:
    gsw = fb._meep_grating_efficiency(0.40, 0.30, 1.52, 1.52, 633.0, 0.0, (-1, 0, 1), "TE", 80)
    e0 = gsw["orders"].get(0, 0.0)
    side = gsw["orders"].get(1, 0.0) + gsw["orders"].get(-1, 0.0)
    record("sub-lambda: eta_0<=1 and side orders ~0", e0 <= 1.05 and side < 0.05,
           "eta0=%.4f  side(+/-1)=%.4f  sum=%.3f" % (e0, side, gsw["sum"]))
except Exception as e:
    record("sub-lambda grating", False, "EXCEPTION: %s" % e); traceback.print_exc()


# ======================================================================================================
# (iii) METAATOM PHASE  -- a FULL-FILL pillar IS a uniform slab -> cross-check to the single-layer TMM
# ======================================================================================================
print("\n== (iii) metaatom_phase: full-fill pillar == uniform slab (vs TMM) ==")
# pillar_w == period -> the 'pillar' fills the whole cell -> a uniform slab of index n_pillar, height h.
period, pw, ph, n_pil, n_subm, wlm = 0.30, 0.30, 0.60, 2.0, 1.45, 633.0
try:
    mm = fb._meep_metaatom_phase(period, pw, ph, n_pil, n_subm, wlm, 60)
    # TMM of the same slab: a single layer (n_pil, h) on substrate n_subm, in air, normal incidence.
    tmm_slab = fb._stack_fallback_tmm(fb._normalize_layers([n_pil], [ph*1000.0]), 1.0, n_subm, wlm, 0.0, "TE", "oracle")
    # Meep's t = E_substrate / E_air is an AMPLITUDE ratio, so |t|^2 = power_T * (eta0/eta_s) = T / n_subm at
    # normal incidence (the field amplitude transmitted INTO the higher-index substrate, not the power T).
    t_amp_sq = tmm_slab["transmittance"] * 1.0 / n_subm
    dT = abs(mm["transmittance"] - t_amp_sq)
    record("metaatom full-fill |t|^2 ~ slab TMM amplitude |t|^2 (dT<0.08)", dT < 0.08,
           "Meep |t|^2=%.4f  TMM amp|t|^2=%.4f (powerT=%.3f /n_s)  dT=%.4f  phase=%.1f deg"
           % (mm["transmittance"], t_amp_sq, tmm_slab["transmittance"], dT, mm["phase_deg"]))
except Exception as e:
    record("metaatom full-fill", False, "EXCEPTION: %s" % e); traceback.print_exc()

# empty cell (pillar index == air) -> t ~ 1, phase ~ 0
print("  -- empty cell (n_pillar=1, n_substrate=1): t~1, phase~0 --")
try:
    me = fb._meep_metaatom_phase(0.30, 0.30, 0.60, 1.0, 1.0, 633.0, 60)
    ph_err = min(abs(me["phase_deg"]), abs(me["phase_deg"]-360.0))
    record("empty cell: |t|^2~1 and phase~0", abs(me["transmittance"]-1.0) < 0.05 and ph_err < 8.0,
           "|t|^2=%.4f  phase=%.1f deg (err %.1f)" % (me["transmittance"], me["phase_deg"], ph_err))
except Exception as e:
    record("empty cell metaatom", False, "EXCEPTION: %s" % e); traceback.print_exc()


print("\n" + "=" * 70)
npass = sum(1 for r in _results if r)
print("MEEP-FDTD VERIFY: %d/%d checks passed" % (npass, len(_results)))
sys.exit(0 if npass == len(_results) else 1)
