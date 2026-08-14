"""Manual verification harness for #18: does the trace measure PHYSICAL millimetres?

Run:
    blender --background --factory-startup --python tests/_verify_unit_equivalence.py

Not part of CI (see AGENTS.md) -- it is expected to FAIL today. It exists to make "a non-mm
scene is a supported way to work" a decidable claim rather than an opinion, and to be the gate
any implementation of #18 has to pass.

WHAT IT CHECKS, AND WHY NOT THE OBVIOUS THING

The obvious test -- build the same bench in a millimetre scene and a metre scene, compare the
traced physics -- PASSES on a codebase where none of this works, and that is worth understanding
before trusting any result here. Feed the same millimetre numbers to the builders in both scenes
and today they are placed as raw Blender units, then read back as millimetres by a tracer that
ignores `scale_length`. Two errors that cancel: the bench in the metre scene is physically a
thousand times too large, yet every number the tracer reports is identical. A test comparing only
those numbers cannot see the bug at all.

So this ties the physics to the WORLD instead. The accumulated optical path length must equal the
distance the beam actually spans, converted to millimetres through the scene's own unit scale.
That cannot be satisfied by two cancelling errors -- it is the property a user means by "my
metre-scale scene works".

    physical_mm = |p2 - p1| * geometry.mm_per_unit(scene)
    assert the running total of physical_mm == segment["opl"]

On the millimetre convention mm_per_unit is exactly 1.0 and this holds today. In any other scene
it fails, and the size of the failure is the size of the lie.
"""
import bpy, sys, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import elements_generic as eg, scan, geometry
from mathutils import Vector


def build_and_trace(scale_length):
    """The same bench, described with the same millimetre arguments, at a given unit scale."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = scale_length
    coll = bpy.data.collections.new("EQ")
    sc.collection.children.link(coll)
    src = eg.source("EQ_S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    src.optics.waist_um = 400.0
    eg.lens("EQ_L", (0.0, 0.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0)
    eg.detector("EQ_D", (250.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    bpy.context.view_layer.update()

    mmpu = geometry.mm_per_unit(sc)
    # The bench must also be the SIZE the millimetre arguments asked for. Without this a change
    # that only fixed the measurement side would pass: a 150-metre bench measured as 150 metres is
    # self-consistent and useless. Source at -150 mm, lens at 0 -> 150 mm apart, in any scene.
    span_mm = ((eg_objs("EQ_L").matrix_world.translation
                - eg_objs("EQ_S").matrix_world.translation).length) * mmpu
    rows = []
    for s in scan._trace(sc):
        p1, p2 = Vector(s["p1"]), Vector(s["p2"])
        rows.append({
            "kind": s["kind"],
            "span_units": (p2 - p1).length,
            "physical_mm": (p2 - p1).length * mmpu,
            "opl": s.get("opl") or 0.0,
            "power": round(s.get("power") or 0.0, 9),
            "w_mm": round(s.get("w_mm") or 0.0, 6),
        })
    return rows, mmpu, span_mm


def eg_objs(name):
    return bpy.data.objects[name]


def report(label, rows, mmpu):
    print("%s   (mm per unit = %g)" % (label, mmpu))
    ok, run = True, 0.0
    for r in rows:
        run += r["physical_mm"]
        agree = abs(run - r["opl"]) < 1e-3
        ok = ok and agree
        print("    %-9s span %10.4f u = %13.4f mm physical | opl %10.4f mm   %s"
              % (r["kind"], r["span_units"], r["physical_mm"], r["opl"],
                 "ok" if agree else "<-- MISMATCH"))
    return ok


mm_rows, mm_f, mm_span = build_and_trace(0.001)
me_rows, me_f, me_span = build_and_trace(1.0)

print("=" * 78)
numbers_match = ([(r["kind"], r["power"], r["opl"], r["w_mm"]) for r in mm_rows]
                 == [(r["kind"], r["power"], r["opl"], r["w_mm"]) for r in me_rows])
print("reported physics numbers identical across the two scenes:", numbers_match)
print("  (this alone proves nothing -- see the module docstring)")
print("-" * 78)
ok_mm = report("millimetre scene", mm_rows, mm_f)
print()
ok_me = report("metre scene     ", me_rows, me_f)
print("-" * 78)
print("millimetre scene -- OPL equals physical distance:", ok_mm)
print("metre scene      -- OPL equals physical distance:", ok_me)
print()
ok_span = abs(mm_span - 150.0) < 1e-3 and abs(me_span - 150.0) < 1e-3
print("source->lens physical spacing (asked for 150 mm):  mm scene %.4f mm | metre scene %.4f mm  %s"
      % (mm_span, me_span, "ok" if ok_span else "<-- WRONG SIZE"))
print()
if ok_mm and ok_me and ok_span:
    print("UNIT EQUIVALENCE PASS -- the trace measures true physical millimetres in both scenes")
    sys.exit(0)
print("UNIT EQUIVALENCE FAIL -- the trace does not measure physical distance in every scene (#18)")
sys.exit(1)
