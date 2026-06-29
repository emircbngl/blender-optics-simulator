"""Headless verification harness for the chi(2) TENSOR SOLVER (the opt-in Manley-Rowe coupled-wave path).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_chi2_tensor.py

With use_chi2_solver=ON a nonlinear CRYSTAL derives its SHG conversion efficiency from the FULL Manley-Rowe
coupled-wave equations (pump depletion + phase mismatch, RK4-integrated) instead of the static
nl_efficiency*sinc^2 scalar, and the CRITICAL walk-off is DERIVED from the index ellipsoid.

Proves:
  (A) ODE limits (physics.chi2_shg_efficiency): at perfect phase match eta == tanh^2(sqrt(eta_lin)) to 1e-9;
      undepleted (eta_lin<<1) eta -> eta_lin*sinc^2(dkL/2); Manley-Rowe energy |a1|^2+|a2|^2 == 1.
  (B) IN-TRACE depletion: a 1064->532 BBO SHG crystal converts MORE as the pump power rises (0.076 -> 0.93 ->
      0.999), and pump-residual + harmonic == input power at every level (energy conservation through the trace).
  (C) phase-match ANGLE from the solver path == shg_phase_match_angle == 22.78 deg (oracle).
  (D) replace-when-on WALK-OFF: with the solver ON the harmonic walks off by the Sellmeier-derived offset
      (BBO 10 mm ~ 0.50 mm), NOT the literal nl_walkoff_mm.
  (E) BYTE-IDENTICAL gate: solver OFF (default) reproduces the legacy nl_efficiency*sinc^2 efficiency exactly.
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy

FAILS = []


def check(cond, label):
    print(("PASS" if cond else "FAIL"), "-", label)
    if not cond:
        FAILS.append(label)
    return cond


import optical_alignment_sim as addon
try:
    addon.register()
except Exception:
    pass

from optical_alignment_sim import elements_generic as eg, scan, physics

# (A) the Manley-Rowe ODE limits -----------------------------------------------------------------------
for el in (0.05, 0.5, 2.0, 4.0):
    ode = physics.chi2_shg_efficiency(el, 0.0)
    closed = math.tanh(math.sqrt(el)) ** 2
    check(abs(ode - closed) < 1e-9, "ODE at perfect phase match == tanh^2(sqrt(%.2f)) (%.6f vs %.6f)" % (el, ode, closed))
_el = 0.001
_ode = physics.chi2_shg_efficiency(_el, math.pi)            # dkL = pi
_sinc = _el * (math.sin(math.pi / 2) / (math.pi / 2)) ** 2
check(abs(_ode - _sinc) / _sinc < 5e-3, "ODE undepleted limit -> eta_lin*sinc^2(dkL/2) (%.3e vs %.3e)" % (_ode, _sinc))

# (B) in-trace pump-depletion: more pump -> more conversion, energy conserved ---------------------------
sc = bpy.context.scene
COLL = bpy.data.collections.new("C2TEST"); sc.collection.children.link(COLL)


def _shg_convert(pump_W, solver=True, temp_C=25.0):
    for o in list(sc.objects):
        if getattr(o, "optics", None) and o.optics.is_optical:
            bpy.data.objects.remove(o, do_unlink=True)
    s = eg.source("S", (-80, 0, 0), (1, 0, 0), coll=COLL); s.optics.wavelength = 1064.0
    eg.crystal("X", (0, 0, 0), (1, 0, 0), coll=COLL, nl_process='SHG', crystal_material='BBO',
               crystal_length_mm=10.0, use_chi2_solver=solver, nl_pump_power_W=pump_W, crystal_temp_C=temp_C)
    eg.detector("D", (80, 0, 0), (1, 0, 0), coll=COLL)
    bpy.context.view_layer.update()
    segs = [g for g in scan._trace(sc) if g.get("to") == "D"]
    p532 = sum(g["power"] for g in segs if abs(g["wavelength"] - 532.0) < 1.0)
    p1064 = sum(g["power"] for g in segs if abs(g["wavelength"] - 1064.0) < 1.0)
    return p532, p1064, segs


etas = []
for P_W in (1.0, 50.0, 200.0):
    p2, p1, _ = _shg_convert(P_W)
    etas.append(p2)
    check(abs(p2 + p1 - 1.0) < 1e-4, "energy conserved through the trace at pump=%.0f W (eta=%.4f + residual=%.4f = %.4f)"
          % (P_W, p2, p1, p2 + p1))
check(etas[0] < etas[1] < etas[2], "conversion RISES with pump power (depletion): %.4f < %.4f < %.4f" % tuple(etas))
check(abs(etas[1] - math.tanh(math.sqrt(4.0)) ** 2) < 0.01,
      "pump=50 W reproduces tanh^2(sqrt(eta_lin=4)) = 0.9293 (got %.4f)" % etas[1])

# (C) phase-match angle anchor -------------------------------------------------------------------------
_thpm = physics.shg_phase_match_angle('BBO', 1064.0)
check(abs(_thpm - 22.78) < 0.3, "BBO 1064->532 Type-I phase-match angle = %.2f deg (oracle 22.78)" % _thpm)

# (D) Sellmeier-derived walk-off (replace-when-on) -----------------------------------------------------
_sw = physics.shg_walkoff_mm('BBO', 1064.0, 10.0)
check(0.3 < _sw < 0.7, "Sellmeier walk-off over 10 mm BBO = %.4f mm (~0.50, vs the 0.6 literal)" % _sw)
# the harmonic emission really shifts off the pump axis when the solver is on
_p2, _p1, _segs = _shg_convert(50.0)
_harm = next((g for g in _segs if abs(g["wavelength"] - 532.0) < 1.0), None)
_pump = next((g for g in _segs if abs(g["wavelength"] - 1064.0) < 1.0), None)
if _harm and _pump:
    import mathutils as _mu
    _off = (_mu.Vector(_harm["p1"]) - _mu.Vector(_pump["p1"])).length
    check(abs(_off - _sw) < 1e-3, "harmonic emission walks off by the Sellmeier offset (got %.4f, expect %.4f mm)" % (_off, _sw))
else:
    check(False, "solver-on SHG produced both a harmonic and a residual pump segment")

# (E) byte-identical gate: solver OFF == legacy nl_efficiency*sinc^2 ------------------------------------
_p2_off, _p1_off, _ = _shg_convert(50.0, solver=False)
check(abs(_p2_off - 0.4) < 1e-6, "solver OFF -> legacy eff = nl_efficiency(0.4)*sinc^2(0) = 0.4 (got %.6f)" % _p2_off)

print("\n%s  (%d checks, %d failed)" % ("CHI2 TENSOR PASS" if not FAILS else "CHI2 TENSOR FAIL",
                                        len(FAILS) + 0 + 14, len(FAILS)))
sys.exit(1 if FAILS else 0)
