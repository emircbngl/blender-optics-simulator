"""The two-part OPA element (#58): an input end the pump enters and a separately placed output end that emits
the signal and/or idler perpendicular to itself, with a user-set optical path between the two ends.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_opa.py
"""
import os
import sys
import tempfile

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import (bake, diagnostics, elements_generic as eg, handlers, optics_api as api,
                                   param_schema, tracer)

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


scene = bpy.context.scene
scene.optics.live_enabled = False
PUMP, SIGNAL = 800.0, 1300.0
IDLER = 1.0 / (1.0 / PUMP - 1.0 / SIGNAL)
ETA = 0.25


def bench(out_loc=(0.0, 200.0, 50.0), select="BOTH", mode="REPLACE", path=500.0):
    clear()
    src = eg.source("S", (-100, 0, 0), (1, 0, 0))
    src.optics.wavelength = PUMP
    opa = eg.opa("OPA", (0, 0, 0), (1, 0, 0), "OPA_out", out_loc, (1, 0, 0), signal_nm=SIGNAL, efficiency=ETA)
    opa.optics.opa_output_select = select
    opa.optics.opa_path_mode = mode
    opa.optics.opa_path_mm = path
    eg.detector("D", (out_loc[0] + 120.0, out_loc[1], out_loc[2]), (1, 0, 0))
    bpy.context.view_layer.update()
    return opa, tracer.trace_scene(scene)


def power(seg):
    return sum(c * c for c in seg["jones"])


print("[wavelengths and power: signal set by the user, idler from energy conservation, Manley-Rowe split]")
opa, segs = bench()
arrivals = sorted((s for s in segs if s["to"] == "D"), key=lambda s: s["wavelength"])
check("both outputs reach the detector", len(arrivals) == 2, [(s["kind"], s["wavelength"]) for s in arrivals])
if len(arrivals) == 2:
    sig, idl = arrivals
    check("signal at the set wavelength, idler at 1/(1/lp - 1/ls)",
          abs(sig["wavelength"] - SIGNAL) < 1e-6 and abs(idl["wavelength"] - IDLER) < 1e-6,
          (sig["wavelength"], idl["wavelength"], IDLER))
    ps, pi = power(sig), power(idl)
    check("P_s = eta P lp/ls, P_i = eta P lp/li, P_s + P_i = eta P",
          abs(ps - ETA * PUMP / SIGNAL) < 1e-6 and abs(pi - ETA * PUMP / IDLER) < 1e-6 and abs(ps + pi - ETA) < 1e-6,
          (ps, pi))
    check("equal photon rates (P lambda)", abs(ps * SIGNAL - pi * IDLER) < 1e-6, (ps * SIGNAL, pi * IDLER))
check("the residual pump is absorbed: nothing at the pump wavelength leaves either end",
      not any(s["from"] in ("OPA", "OPA_out") and abs(s["wavelength"] - PUMP) < 1e-6 and s["kind"] != "OPA_LINK"
              for s in segs), [(s["from"], s["kind"], s["wavelength"]) for s in segs])
opa.optics.opa_output_select = "SIGNAL"
bpy.context.view_layer.update()
segs = tracer.trace_scene(scene)
check("SIGNAL only: one arrival at the signal wavelength",
      [round(s["wavelength"], 3) for s in segs if s["to"] == "D"] == [SIGNAL], [s["wavelength"] for s in segs if s["to"] == "D"])
opa.optics.opa_output_select = "IDLER"
bpy.context.view_layer.update()
segs = tracer.trace_scene(scene)
check("IDLER only: one arrival at the idler wavelength",
      [round(s["wavelength"], 3) for s in segs if s["to"] == "D"] == [round(IDLER, 3)],
      [s["wavelength"] for s in segs if s["to"] == "D"])

print("[geometry: the output end emits along its own axis from where it is placed]")
opa, segs = bench(out_loc=(40.0, -150.0, 30.0))
out = next((s for s in segs if s["from"] == "OPA_out"), None)
axis = (bpy.data.objects["OPA_out"].matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
d = (Vector(out["p2"]) - Vector(out["p1"])).normalized() if out else Vector((0, 0, 0))
check("emitted along the output end's axis, perpendicular to its face", d.dot(axis) > 1 - 1e-6, (tuple(d), tuple(axis)))
check("emitted from the output end, not from the input end",
      out is not None and (Vector(out["p1"]) - bpy.data.objects["OPA_out"].matrix_world.translation).length < 5.0,
      out and tuple(out["p1"]))

print("[the user-set path: REPLACE ignores the distance between the ends, ADD adds to it]")
L = 500.0


def link_and_arrival(out_loc, mode):
    _o, s = bench(out_loc=out_loc, select="SIGNAL", mode=mode, path=L)
    link = next((x for x in s if x["kind"] == "OPA_LINK"), None)
    into = next(x for x in s if x["to"] == "OPA")
    return link, into, s


for loc in ((0.0, 200.0, 50.0), (300.0, -80.0, 10.0)):
    link, into, s = link_and_arrival(loc, "REPLACE")
    check("REPLACE at %s: the link adds exactly the set path" % (loc,),
          link is not None and abs(link["opl"] - into["opl"] - L) < 1e-6 and abs(link["length_mm"] - L) < 1e-6,
          link and (link["opl"] - into["opl"], link["length_mm"]))
link, into, s = link_and_arrival((300.0, -80.0, 10.0), "ADD")
dist = (Vector(link["p2"]) - Vector(link["p1"])).length if link else 0.0
check("ADD: the link adds the distance between the ends plus the set path",
      link is not None and abs(link["opl"] - into["opl"] - (dist + L)) < 1e-4,
      link and (link["opl"] - into["opl"], dist + L))
arr = next((x for x in s if x["to"] == "D"), None)
check("the detector's phase OPL continues from the link",
      link is not None and arr is not None and abs(arr["opl"] - (link["opl"] + arr["length_mm"])) < 1e-6,
      arr and link and (arr["opl"], link["opl"], arr["length_mm"]))

print("[path statistics, group delay and diagnostics]")
opa, segs = bench(select="SIGNAL")
ps = api.path_statistics("D")["detectors"][0]["arrivals"]
ps = ps[0] if ps else {}
check("the route names both ends", ps.get("route") == ["S", "OPA", "OPA_out", "D"], ps.get("route"))
check("group delay unknown until the OPA's dispersion is set by hand",
      ps.get("group_delay_fs", 0) is None and ps.get("dispersion_missing") == ["OPA"], ps)
opa.optics.dispersion_mode = "USER"
opa.optics.user_group_delay_fs = 5000.0
opa.optics.user_gdd_fs2 = 900.0
bpy.context.view_layer.update()
ps = api.path_statistics("D")["detectors"][0]["arrivals"]
ps = ps[0] if ps else {}
c = 2.99792458e-4
check("with hand-set OPA dispersion: delay = (air + set path)/c + the OPA's own",
      ps.get("group_delay_fs") is not None
      and abs(ps["group_delay_fs"] - (ps["geometric_length_mm"] / c + 5000.0)) < 0.01 and abs(ps["gdd_fs2"] - 900.0) < 1e-9,
      ps)
kinds = [(x["kind"], x["element"]) for x in diagnostics.run_diagnostics(scene)]
check("a working OPA bench raises no energy, bypass, orphan or OPA finding",
      not any(k in ("energy_violation", "optic_bypassed", "orphan_source", "dark_detector", "opa_unusable")
              for k, _e in kinds), kinds)

print("[a declared metre scene reports the same millimetres]")
_o, mm_segs = bench(out_loc=(300.0, -80.0, 10.0), select="SIGNAL", mode="ADD", path=L)
mm_link = next(x for x in mm_segs if x["kind"] == "OPA_LINK")
mm_arr = next(x for x in mm_segs if x["to"] == "D")
scene.unit_settings.scale_length = 1.0
scene.optics.scene_units_authoritative = True
_o, m_segs = bench(out_loc=(300.0, -80.0, 10.0), select="SIGNAL", mode="ADD", path=L)
m_link = next((x for x in m_segs if x["kind"] == "OPA_LINK"), None)
m_arr = next((x for x in m_segs if x["to"] == "D"), None)
check("metre scene: the link length and the detector OPL match the millimetre scene",
      m_link is not None and m_arr is not None and abs(m_link["length_mm"] - mm_link["length_mm"]) < 1e-3
      and abs(m_arr["opl"] - mm_arr["opl"]) < 1e-3, (m_link and m_link["length_mm"], mm_link["length_mm"],
                                                     m_arr and m_arr["opl"], mm_arr["opl"]))
scene.optics.scene_units_authoritative = False
opa, segs = bench(select="SIGNAL")

print("[an OPA that cannot emit says why]")
opa.optics.opa_signal_nm = 700.0                  # shorter than the pump: no idler
bpy.context.view_layer.update()
segs = tracer.trace_scene(scene)
kinds = [(x["kind"], x["element"], x["detail"]) for x in diagnostics.run_diagnostics(scene)]
check("signal shorter than the pump: nothing emitted, diagnose names the OPA",
      not any(s["from"] == "OPA_out" for s in segs) and any(k == "opa_unusable" and e == "OPA" for k, e, _d in kinds),
      kinds)
opa.optics.opa_signal_nm = SIGNAL
opa.optics.opa_output = None
bpy.context.view_layer.update()
segs = tracer.trace_scene(scene)
kinds = [(x["kind"], x["element"], x["detail"]) for x in diagnostics.run_diagnostics(scene)]
check("no output end linked: nothing emitted, diagnose names the OPA",
      not any(s["from"] == "OPA_out" for s in segs) and any(k == "opa_unusable" and e == "OPA" for k, e, _d in kinds),
      kinds)

print("[linking, live signature, save/reload, delete]")
check("set_param links an output end by name", bool(api.set_param("OPA", "opa_output", "OPA_out").get("ok"))
      and opa.optics.opa_output is not None and opa.optics.opa_output.name == "OPA_out")
check("set_param refuses an object that is not an OPA output end",
      "error" in api.set_param("OPA", "opa_output", "D") and opa.optics.opa_output is not None
      and opa.optics.opa_output.name == "OPA_out")
sig1 = handlers._signature(scene)
bpy.data.objects["OPA_out"].location.x += 10.0
bpy.context.view_layer.update()
check("moving the output end changes the live signature", handlers._signature(scene) != sig1)
with tempfile.TemporaryDirectory(prefix="oas-opa-") as tmp:
    path = os.path.join(tmp, "opa.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    scene = bpy.context.scene
    opa = bpy.data.objects["OPA"]
    check("the link survives save and reload",
          opa.optics.opa_output is not None and opa.optics.opa_output.name == "OPA_out")
    bpy.data.objects.remove(bpy.data.objects["OPA_out"], do_unlink=True)
    bpy.context.view_layer.update()
    segs = tracer.trace_scene(scene)
    check("deleting the output end unlinks it and stops the emission",
          opa.optics.opa_output is None and not any(s["kind"] in ("SIGNAL", "IDLER") for s in segs),
          [(s["from"], s["kind"]) for s in segs])

print("[the link is not drawn as a beam; schema and library]")
opa, segs = bench(select="SIGNAL")
bake.bake_beams(bpy.context)
segs = tracer.cached_segments
n_tubes = len([o for o in scene.objects if o.name.startswith("BEAM_")])
check("baking skips the OPA link", n_tubes == len([s for s in segs if s["kind"] != "OPA_LINK"]) and n_tubes < len(segs),
      (n_tubes, [s["kind"] for s in segs]))
check("OPA schema lists the link, wavelengths, efficiency and path",
      all(n in param_schema.names("OPA") for n in ("opa_output", "opa_signal_nm", "opa_output_select", "opa_efficiency",
                                                  "opa_path_mode", "opa_path_mm")))
clear()
made = api.add_component("OPA", location=(0, 0, 0))
made_obj = bpy.data.objects.get(made.get("name", "")) if isinstance(made, dict) else None
check("add_component('OPA') creates a linked input and output end",
      made_obj is not None and made_obj.optics.opa_output is not None, made)

print("OPA %s (%d/%d checks)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("OPA witnesses failed")
