"""Group delay and GDD in path_statistics, on real traced benches (#57).

Expected values are computed here from central differences of physics.sellmeier_n and the traced segments'
own lengths, not from the add-on's group_index / gvd_fs2_per_mm, so the check does not reuse what it tests.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_dispersion.py
"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import elements_generic as eg, optics_api as api, physics, tracer

checks = []
C_MM_FS = 2.99792458e-4


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def ref_ng_gvd(wl_nm, glass):
    """n_g and GVD (fs^2/mm) by central differences of sellmeier_n, lambda in um."""
    h = 0.02                                   # nm
    np_, n0, nm = (physics.sellmeier_n(wl_nm + h, glass), physics.sellmeier_n(wl_nm, glass),
                   physics.sellmeier_n(wl_nm - h, glass))
    x = wl_nm * 1e-3
    d1 = (np_ - nm) / (2 * h) * 1e3
    d2 = (np_ - 2 * n0 + nm) / (h * h) * 1e6
    return n0 - x * d1, (x ** 3 * d2 * 1e-3) / (2 * math.pi * C_MM_FS ** 2)


def arrival(detector):
    res = api.path_statistics(detector)
    row = res["detectors"][0]
    return res, (row["arrivals"][0] if row["arrivals"] else None)


def expected(detector, segs):
    """Walk the traced parent chain to the detector and sum the reference delay and GDD."""
    leaf = next(i for i, s in enumerate(segs) if s["to"] == detector)
    chain = []
    i = leaf
    while i >= 0:
        chain.append(i)
        i = segs[i]["parent"]
    gd = gdd = 0.0
    legs = 0
    for i in chain:
        gd += segs[i]["length_mm"] / C_MM_FS
    # the in-glass legs are children of the segment arriving at the element (beside the exit ray)
    for i in chain[1:]:
        for s in segs:
            if s["kind"] == "GLASS" and s["parent"] == i and s["to"] == segs[i]["to"]:
                ng, gvd = ref_ng_gvd(s["wavelength"], s["glass"])
                gd += s["length_mm"] * ng / C_MM_FS
                gdd += s["length_mm"] * gvd
                legs += 1
    return gd, gdd, legs


scene = bpy.context.scene
scene.optics.live_enabled = False

print("[references: the numerical derivatives agree with values quoted in the literature]")
ng, gvd = ref_ng_gvd(800.0, "FUSED_SILICA")
check("fused silica at 800 nm: n_g ~ 1.4671, GVD ~ 36.2 fs^2/mm", abs(ng - 1.4671) < 5e-4 and abs(gvd - 36.2) < 0.3,
      "n_g %.5f GVD %.3f" % (ng, gvd))

print("[a mirror bench: air only, group delay = geometric length / c, GDD 0]")
clear()
eg.source("S", (-100, 0, 0), (1, 0, 0))
eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0))
eg.detector("D", (0, 120, 0), (0, 1, 0))
bpy.context.view_layer.update()
res, a = arrival("D")
check("air route is complete", res["group_delay_available"] and a["dispersion_missing"] == [], a)
check("air route delay = geometric length / c, GDD 0",
      a["group_delay_fs"] is not None and abs(a["group_delay_fs"] - a["geometric_length_mm"] / C_MM_FS) < 0.01
      and a["gdd_fs2"] == 0.0, a)

print("[a dispersing prism: every traced glass leg adds L n_g / c and L GVD at its wavelength]")
def prism_bench(glass):
    """Source -> prism -> a detector placed 150 mm along the traced exit ray."""
    clear()
    src = eg.source("S", (-120, 0, 0), (1, 0, 0))
    src.optics.wavelength = 800.0
    prism = eg.prism("P", (0, 0, 0), (1, 0, 0), prism_type="EQUILATERAL")
    prism.optics.prism_glass = glass
    bpy.context.view_layer.update()
    segs = tracer.trace_scene(scene)
    exit_seg = next(s for s in segs if s["from"] == "P" and s["kind"] != "GLASS")
    direction = [exit_seg["p2"][k] - exit_seg["p1"][k] for k in range(3)]
    norm = math.sqrt(sum(c * c for c in direction))
    end = [exit_seg["p1"][k] + direction[k] / norm * 150.0 for k in range(3)]
    eg.detector("D", tuple(end), tuple(c / norm for c in direction))
    bpy.context.view_layer.update()
    return tracer.trace_scene(scene)


segs = prism_bench("FUSED_SILICA")
res, a = arrival("D")
want_gd, want_gdd, legs = expected("D", segs)
check("the prism route has traced fused-silica legs", legs >= 1 and all(
    s.get("glass") == "FUSED_SILICA" for s in segs if s["kind"] == "GLASS"), legs)
check("the geometric length includes the glass legs",
      a and abs(a["geometric_length_mm"] - sum(s["length_mm"] for s in segs if s["kind"] == "GLASS")
                - sum(segs[i]["length_mm"] for i in (next(j for j, s in enumerate(segs) if s["to"] == "D"),
                                                     segs[next(j for j, s in enumerate(segs) if s["to"] == "D")]["parent"]))) < 1e-3,
      a)
check("prism route delay = sum of air L/c + glass L n_g/c",
      a and a["group_delay_fs"] is not None and abs(a["group_delay_fs"] - want_gd) < 0.05,
      "%s vs %.3f" % (a and a["group_delay_fs"], want_gd))
check("prism route GDD = sum of glass L GVD (positive at 800 nm)",
      a and a["gdd_fs2"] is not None and abs(a["gdd_fs2"] - want_gdd) < 0.05 and want_gdd > 0,
      "%s vs %.3f" % (a and a["gdd_fs2"], want_gdd))
check("the phase OPL is unchanged by the dispersion bookkeeping",
      abs(a["phase_opl_mm"] - segs[next(i for i, s in enumerate(segs) if s["to"] == "D")]["opl"]) < 1e-6, a)
prism_bench("N-SF11")
res2, a2 = arrival("D")
check("a denser flint prism gives more GDD", a2 and a2["gdd_fs2"] is not None and a2["gdd_fs2"] > a["gdd_fs2"],
      "%s > %s" % (a2 and a2["gdd_fs2"], a["gdd_fs2"]))

print("[a thin lens: not modelled unless set by hand]")
clear()
eg.source("S", (-100, 0, 0), (1, 0, 0))
lens = eg.lens("L", (0, 0, 0), (1, 0, 0), focal=200.0)
eg.detector("D", (100, 0, 0), (1, 0, 0))
bpy.context.view_layer.update()
res, a = arrival("D")
check("a lens on the route leaves the delay unknown and names the lens",
      not res["group_delay_available"] and a["group_delay_fs"] is None and a["dispersion_missing"] == ["L"], a)
opl_auto = a["phase_opl_mm"]
lens.optics.dispersion_mode = "USER"
lens.optics.user_group_delay_fs = 12000.0
lens.optics.user_gdd_fs2 = 180.0
bpy.context.view_layer.update()
res, a = arrival("D")
check("set by hand: complete, the lens's values are added once",
      res["group_delay_available"] and abs(a["group_delay_fs"] - (a["geometric_length_mm"] / C_MM_FS + 12000.0)) < 0.01
      and abs(a["gdd_fs2"] - 180.0) < 1e-9, a)
check("hand-set dispersion does not change the trace",
      abs(a["phase_opl_mm"] - opl_auto) < 1e-9 and a["power"] > 0, (opl_auto, a))

print("[a mirror's polished substrate: a named glass is modelled, a fixed index is not]")
clear()
m = eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0))
m.optics.back_surface = "SECOND_SURFACE"
eg.source("S", (150, 0, 0), (-1, 0, 0))
eg.detector("D", (0, -150, 0), (0, -1, 0))
bpy.context.view_layer.update()
res, a = arrival("D")
check("fixed-index substrate: delay unknown, reason given",
      a is not None and a["group_delay_fs"] is None and any("fixed refractive index" in x for x in a["dispersion_missing"]),
      a)
m.optics.surface_glass = "N-BK7"
bpy.context.view_layer.update()
segs = tracer.trace_scene(scene)
res, a = arrival("D")
want_gd, want_gdd, legs = expected("D", segs)
check("N-BK7 substrate: two glass legs, delay and GDD match the reference",
      a is not None and legs == 2 and a["group_delay_fs"] is not None and abs(a["group_delay_fs"] - want_gd) < 0.05
      and abs(a["gdd_fs2"] - want_gdd) < 0.05,
      "%s vs %.3f / %.3f" % (a, want_gd, want_gdd))

print("[the dispersion fields are in the schema, and absent on detectors]")
from optical_alignment_sim import param_schema
check("lens schema has dispersion_mode", "dispersion_mode" in param_schema.names("LENS"))
check("detector schema has no dispersion fields", "dispersion_mode" not in param_schema.names("DETECTOR"))

print("DISPERSION %s (%d/%d checks)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("dispersion witnesses failed")
