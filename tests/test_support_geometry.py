"""Stage 05a witness: the shipped post and post holder, measured against the vendor drawings.

What is compared, and how, was fixed BEFORE measuring (the plan forbids loosening a threshold after
seeing the mesh):

* Expected values come from docs/mechanics/product-evidence.json -- the facts read off Thorlabs
  drawings TR50/M 0331 rev J and PH50/M 23132 rev B -- and never from optomech's own constants, so
  the generator cannot agree with itself.
* Threshold: 0.05 mm, half the 0.1 mm resolution the drawings are dimensioned to. A model inside it
  cannot be told apart from the drawing; one outside it can.
* Method: meshes are polygons, so each surface is measured the way a mating part meets it -- an
  outer surface at its circumradius (the envelope), a bore at its inradius (the clear passage, from
  the wall faces' planes), axial stations from vertex extents.

This checks geometry only. The drawings are stamped FOR INFORMATION ONLY and state no tolerances, so
agreement here is agreement with a nominal, not a fit.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_support_geometry.py
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import elements_generic as eg, hardware_render, optomech

THRESHOLD_MM = 0.05

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


FACTS = {f["id"]: f for f in
         json.loads((ROOT / "docs/mechanics/product-evidence.json").read_text())["support_facts"]}


def fact(identifier):
    return float(FACTS[identifier]["value"])


def near(name, measured, fact_id, expected=None):
    expected = fact(fact_id) if expected is None else expected
    delta = measured - expected
    check("%s: %.3f mm against the drawing's %.3f mm" % (name, measured, expected),
          abs(delta) <= THRESHOLD_MM, "delta %+.3f mm, fact %s" % (delta, fact_id))


# ---- the smallest bench that gets one standard post + holder from Dress Bench ----------------------
scene = bpy.context.scene
scene.optics.live_enabled = False
eg.source("S", (-100, 0, 100), (1, 0, 0))
eg.mirror("M", (0, 0, 100), (1, 0, 0), (0, 1, 0))
eg.detector("D", (0, 120, 100), (0, 1, 0))
bpy.context.view_layer.update()
optomech.dress(scene)
bpy.context.view_layer.update()


def world_verts(ob):
    return [ob.matrix_world @ v.co for v in ob.data.vertices]


def one(prefix):
    found = sorted((o for o in scene.objects if o.name.startswith(optomech.BENCH_PREFIX + prefix)),
                   key=lambda o: o.name)
    assert found, "Dress Bench built no %s" % prefix
    return found[0]


holder = one("Holder_")
tag = holder.name[len(optomech.BENCH_PREFIX + "Holder_"):]
post = scene.objects[optomech.BENCH_PREFIX + "Post_" + tag]
knob = scene.objects[optomech.BENCH_PREFIX + "Lockh_" + tag]
axis = holder.matrix_world.translation.xy.copy()


def radial(p):
    return (p.xy - axis).length


def measure_holder(ob, label, knob_z):
    verts = world_verts(ob)
    top, bottom = max(v.z for v in verts), min(v.z for v in verts)
    outer = max(radial(v) for v in verts)
    near(label + " outer diameter (envelope)", 2 * outer, "ph50m_dwg_outer_diameter")
    near(label + " body length", top - bottom, "ph50m_dwg_length")
    # The bore's clear passage: the smallest distance from the axis to an inward wall face's plane.
    mw = ob.matrix_world
    normal_matrix = mw.to_3x3().inverted().transposed()
    wall, floors = [], []
    for face in ob.data.polygons:
        n = (normal_matrix @ face.normal).normalized()
        c = mw @ face.center
        outward = (c.xy - axis)
        # A bore wall face looks straight back at the axis. Slit sides and the thumbscrew hole look
        # sideways or up/down, so they are excluded instead of being mistaken for the bore.
        if (radial(c) < outer - 1.0 and abs(n.z) < 0.05 and c.z > bottom + 1.0
                and outward.length > 1e-6 and n.xy.length > 1e-6
                and outward.normalized().dot(n.xy.normalized()) < -0.99):
            wall.append(abs(outward.dot(n.xy.normalized())))
        if abs(n.z - 1.0) < 1e-3 and radial(c) < outer - 1.0 and bottom + 0.1 < c.z < top - 0.1:
            floors.append(c.z)
    bore_in = min(wall)
    near(label + " bore diameter (clear passage)", 2 * bore_in, "ph50m_dwg_bore_diameter")
    floor = min(floors)
    near(label + " bore depth", top - floor, "ph50m_dwg_bore_depth")
    # A closed wall: a bored cylinder has vertical faces only on the bore and on the outer surface, so
    # any vertical face whose centre sits inside the wall band is a cut through the wall -- whatever
    # its orientation. (A boolean cut leaves its vertices on the two surfaces, so vertices cannot see
    # it; its faces can.) Checked below the thumbscrew hole, the one cut the drawing does show.
    inside = 0
    for face in ob.data.polygons:
        n = (normal_matrix @ face.normal).normalized()
        c = mw @ face.center
        if (bottom + 1.0 < c.z < knob_z - 5.0 and abs(n.z) < 0.05
                and bore_in + 0.3 < radial(c) < outer - 0.3):
            inside += 1
    check(label + " has a closed wall, as the drawing shows (no through-slit)", inside == 0,
          "%d faces inside the wall" % inside)
    return {"top": top, "bottom": bottom, "outer": outer, "bore_in": bore_in, "floor": floor}


print("[Dress Bench: the PH50/M holder]")
h = measure_holder(holder, "holder", knob.matrix_world.translation.z)

print("[Dress Bench: the thumbscrew]")
knob_world = world_verts(knob)
station = h["top"] - knob.matrix_world.translation.z
near("thumbscrew axis below the top face", station, "ph50m_dwg_thumbscrew_offset")
local = [v.co for v in knob.data.vertices]                 # the knob's own axis is its local Z
near("thumbscrew knob diameter", 2 * max(Vector((v.x, v.y)).length for v in local),
     "ph50m_dwg_thumbscrew_head")
# Along the knob's own axis, from the holder's axis outward -- not the largest radial distance, which
# would count the knob's off-axis rim and overstate how far it stands proud.
toward = (knob.matrix_world.translation.xy - axis).normalized()
near("thumbscrew protrusion beyond the body wall",
     max((v.xy - axis).dot(toward) for v in knob_world) - h["outer"], "ph50m_dwg_thumbscrew_protrusion")

knob_axis = [(v.xy - axis).dot(toward) for v in knob_world]
near("thumbscrew knob length (TS6H/M)", max(knob_axis) - min(knob_axis), "ts6hm_dwg_knob_length")
screw = scene.objects[optomech.BENCH_PREFIX + "Locks_" + tag]
thread_end = min((v.xy - axis).dot(toward) for v in world_verts(screw))
near("thumbscrew thread end, where TS6H/M's 16.1 mm reaches from the knob face",
     thread_end, "ts6hm_dwg_length_to_thread_end",
     expected=fact("ph50m_dwg_outer_diameter") / 2 + fact("ph50m_dwg_thumbscrew_protrusion")
     - fact("ts6hm_dwg_length_to_thread_end"))

print("[the drawings agree with each other]")
# Two drawings, read separately: PH50/M's wall and knob, and TS6H/M's length to the thread end. If they
# were read right, the thread end lands exactly on the bore wall.
landing = (fact("ph50m_dwg_outer_diameter") / 2 + fact("ph50m_dwg_thumbscrew_protrusion")
           - fact("ts6hm_dwg_length_to_thread_end"))
check("TS6H/M's thread end lands on PH50/M's bore wall (%.2f mm from the axis)" % landing,
      abs(landing - fact("ph50m_dwg_bore_diameter") / 2) <= THRESHOLD_MM,
      "bore wall at %.2f mm" % (fact("ph50m_dwg_bore_diameter") / 2))
check("both drawings give the same Ø14.5 mm knob",
      fact("ts6hm_dwg_knob_diameter") == fact("ph50m_dwg_thumbscrew_head"))

print("[Dress Bench: the TR50/M post in that holder]")
post_verts = world_verts(post)
post_r = max(radial(v) for v in post_verts)
near("post diameter (envelope)", 2 * post_r, "tr50m_dwg_outer_diameter")
check("the post passes the bore: envelope inside the clear passage", post_r < h["bore_in"],
      "post %.4f mm, bore %.4f mm (radius)" % (post_r, h["bore_in"]))
# The post rests on or above the bore floor, within the interval its base records (stage 05b): the tip
# the base pushes up through PH50/M's through-tapped floor can hold it up, never let it sink.
base = next(o for o in scene.objects if o.name in (optomech.BENCH_PREFIX + "Base_" + tag,
                                                   optomech.BENCH_PREFIX + "BasePedestal_" + tag))
board = scene.objects[optomech.BENCH_PREFIX + "Breadboard"]
board_top = max((board.matrix_world @ v.co).z for v in board.data.vertices)
lo, hi = base["base_seat_range_mm"]
post_bottom = min(v.z for v in post_verts) - board_top
check("the post stands in its base's seat interval (%.3f-%.3f mm above the board), not below the bore floor" % (lo, hi),
      lo - THRESHOLD_MM <= post_bottom <= hi + THRESHOLD_MM and
      lo >= (h["floor"] - board_top) - THRESHOLD_MM,
      "post bottom %.3f mm, bore floor %.3f mm" % (post_bottom, h["floor"] - board_top))

print("[render detail: the same interfaces]")
hardware_render.prepare(scene)
bpy.context.view_layer.update()
render_holder = next(o for o in scene.objects if o.name == "OAR_HW_Holder_" + tag)
r = measure_holder(render_holder, "render holder", knob.matrix_world.translation.z)
check("render and Dress Bench holders meet the post at the same bore",
      abs(r["bore_in"] - h["bore_in"]) <= 1e-6 and abs(r["floor"] - h["floor"]) <= 1e-6,
      (r["bore_in"], h["bore_in"]))
render_post = next(o for o in scene.objects if o.name == "OAR_HW_Post_" + tag)
rp = world_verts(render_post)
render_r = max(radial(v) for v in rp)
check("the render post also passes the bore", render_r < h["bore_in"], (render_r, h["bore_in"]))
# The render post is a lathe with rings only at its two ends, so every vertex well away from the ends
# was made by the cross-hole boolean: they are the hole's rim on the post surface.
post_top, post_bottom = max(v.z for v in rp), min(v.z for v in rp)
hole = [v for v in rp if post_bottom + 1.0 < v.z < post_top - 1.0]
centre = (max(v.z for v in hole) + min(v.z for v in hole)) / 2 if hole else float("nan")
near("render post cross-hole centre below the top face", post_top - centre, "tr50m_dwg_side_bore_offset")
if hole:
    near("render post cross-hole diameter", max(v.z for v in hole) - min(v.z for v in hole),
         "tr50m_dwg_side_bore")

print("SUPPORT GEOMETRY %s (%d/%d checks, threshold %.2f mm)"
      % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks), THRESHOLD_MM), flush=True)
if not all(checks):
    raise AssertionError("support geometry disagrees with the drawings")
