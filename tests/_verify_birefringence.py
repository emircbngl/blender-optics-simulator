"""Headless verification harness for TRUE o/e SPATIAL double refraction (the opt-in birefringence A-tier).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_birefringence.py

A uniaxial CRYSTAL with oe_split=ON forks one incident ray into an ORDINARY beam (pol perpendicular to the
principal plane, index n_o) and an EXTRAORDINARY beam (pol in-plane, walking off by rho). Modeled as a slab:
both exit PARALLEL to the input, the e-beam displaced laterally by L*tan(rho) -- the textbook calcite double
image, a FIXED displacement set by the crystal thickness.

Proves:
  (A) a calcite crystal (cut 45 deg, L=10 mm) at 633 nm emits TWO beams to the detector (SPLIT_O + SPLIT_E),
      transversely separated by L*tan(6.224 deg) = 1.0906 mm (the closed-form double-image displacement).
  (B) ENERGY conservation: P_o + P_e == P_in (lossless eigen-axis split).
  (C) the two beams are ORTHOGONALLY polarized (o . e* ~ 0) -- the defining property of double refraction.
  (D) NON-DIVERGENCE sanity: optic axis ALONG the beam (cut 0) -> rho 0 -> the two beams re-converge
      (displacement -> 0): the split only appears off-axis.
  (E) WAVELENGTH unchanged (passive birefringence does not convert).
  (F) physics_verify anchor: calcite walk-off at 45 deg == 6.224 deg (the oracle the displacement rides on).
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector

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

sc = bpy.context.scene
COLL = bpy.data.collections.new("OETEST")
sc.collection.children.link(COLL)


def _trace_oe(cut_deg, L_mm=10.0, mat='CALCITE', wl=633.0):
    for o in list(sc.objects):
        if getattr(o, "optics", None) and o.optics.is_optical:
            bpy.data.objects.remove(o, do_unlink=True)
    s = eg.source("OE_S", (-80, 0, 0), (1, 0, 0), coll=COLL, wavelength=wl)
    s.optics.pol_type = 'CIRCULAR'      # equal projection on ANY two orthogonal eigen-axes -> both o & e lit
    x = eg.crystal("OE_X", (0, 0, 0), (1, 0, 0), coll=COLL,
                   oe_split=True, oe_material=mat, oe_axis_deg=cut_deg, oe_length_mm=L_mm)
    eg.detector("OE_D", (80, 0, 0), (1, 0, 0), coll=COLL)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    at_det = [s for s in segs if s.get("to") == "OE_D"]
    return at_det, segs


# (A) calcite double refraction: two beams, separated by L*tan(rho) -------------------------------------
det, _all = _trace_oe(45.0, L_mm=10.0)
kinds = sorted(s.get("kind") for s in det)
o_seg = next((s for s in det if s.get("kind") == "SPLIT_O"), None)
e_seg = next((s for s in det if s.get("kind") == "SPLIT_E"), None)
check(o_seg is not None and e_seg is not None,
      "calcite emits BOTH an ordinary and an extraordinary beam to the detector (kinds=%s)" % kinds)

if o_seg and e_seg:
    p_o, p_e = Vector(o_seg["p2"]), Vector(e_seg["p2"])
    beam = Vector((1.0, 0.0, 0.0))
    sep_vec = (p_e - p_o)
    sep_transverse = (sep_vec - sep_vec.dot(beam) * beam).length          # transverse component
    n_o = physics.sellmeier_n(633.0, 'CALCITE_O')
    n_e = physics.sellmeier_n(633.0, 'CALCITE_E')
    rho = physics.uniaxial_walkoff_angle(n_o, n_e, 45.0)
    expect = 10.0 * math.tan(math.radians(rho))
    check(abs(sep_transverse - expect) < 1e-3,
          "e-beam displaced by L*tan(rho) = %.4f mm (got %.4f, rho=%.3f deg)" % (expect, sep_transverse, rho))

    # (B) energy conservation: P_o + P_e == P_in (the source emits unit power) -----------------------
    psum = o_seg["power"] + e_seg["power"]
    check(abs(psum - 1.0) < 1e-4, "energy conserved: P_o + P_e = %.6f (== P_in 1.0)" % psum)

    # (C) orthogonal polarization: o . e* ~ 0 --------------------------------------------------------
    jo, je = o_seg["jones"], e_seg["jones"]
    co = (complex(jo[0], jo[1]), complex(jo[2], jo[3]))
    ce = (complex(je[0], je[1]), complex(je[2], je[3]))
    no = math.hypot(abs(co[0]), abs(co[1])) or 1.0
    ne = math.hypot(abs(ce[0]), abs(ce[1])) or 1.0
    overlap = abs(co[0] * ce[0].conjugate() + co[1] * ce[1].conjugate()) / (no * ne)
    check(overlap < 1e-3, "ordinary and extraordinary beams are ORTHOGONALLY polarized (overlap=%.2e)" % overlap)

    # (E) wavelength unchanged (passive) -------------------------------------------------------------
    check(abs(o_seg["wavelength"] - 633.0) < 1e-6 and abs(e_seg["wavelength"] - 633.0) < 1e-6,
          "both beams keep the pump wavelength 633 nm (passive birefringence, no conversion)")

# (D) non-divergence when the optic axis is ALONG the beam (cut 0) --------------------------------------
det0, _ = _trace_oe(0.0, L_mm=10.0)
o0 = next((s for s in det0 if s.get("kind") == "SPLIT_O"), None)
e0 = next((s for s in det0 if s.get("kind") == "SPLIT_E"), None)
if o0 and e0:
    sep0 = (Vector(e0["p2"]) - Vector(o0["p2"])).length
    check(sep0 < 1e-6, "optic axis along the beam (cut 0) -> rho 0 -> beams re-converge (sep=%.2e mm)" % sep0)
else:
    check(False, "cut-0 case still produces two beams")

# (F) physics_verify anchor: calcite walk-off at 45 deg = 6.224 deg ------------------------------------
_n_o = physics.sellmeier_n(633.0, 'CALCITE_O')
_n_e = physics.sellmeier_n(633.0, 'CALCITE_E')
_rho45 = physics.uniaxial_walkoff_angle(_n_o, _n_e, 45.0)
check(abs(_rho45 - 6.224) < 0.05, "calcite walk-off at 45 deg = %.3f deg (oracle 6.224)" % _rho45)

print("\n%s  (%d checks, %d failed)" % ("OE BIREFRINGENCE PASS" if not FAILS else "OE BIREFRINGENCE FAIL",
                                        6, len(FAILS)))
sys.exit(1 if FAILS else 0)
