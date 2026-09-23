"""Stage 04b witness: where a seated part actually goes, and when the stated geometry refuses to close.

The convention under test is stated, not inferred: seating makes the two declared interface frames
coincident and anti-parallel. Any depth past that datum is an explicit `insertion_mm`, checked against
the stated limits; clocking is an explicit angle, because schema v1 carries no clocking datum beyond the
frame's +X. An interface with no frame has no datum and cannot be placed.

Every part here is a labelled FIXTURE (manufacturer "FIXTURE", https://example.org/fixture) with frames
chosen to make the geometry checkable. The stage-01 inventory has no sourced frames at all yet, so a
placement from real product data cannot be built; what is verified is the placement MATH and the
refusals, not any real part's seat.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_mechanical_assembly_geometry.py
"""
import math
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import (elements_generic as eg, mechanical_assembly as asm,
                                   mechanical_catalog as catalog, mechanical_interfaces as mi,
                                   optics_api as api, optomech)

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


FIXTURE = {"url": "https://example.org/fixture", "locator": "synthetic stage-04b fixture",
           "revision": None, "checked_on": "2026-09-22", "sha256": None}


def q(value, unit='mm'):
    return {"value": value, "unit": unit, "evidence": ['fixture'], "tolerance": None,
            "model_error_limit": None}


def frame(origin, quaternion=(1.0, 0.0, 0.0, 0.0)):
    return {"origin": list(origin), "unit": 'mm', "quaternion_wxyz": list(quaternion),
            "evidence": ['fixture']}


def thread(gender):
    return {"standard": "M6", "gender": gender, "hand": 'right', "form": 'M', "fit_class": None,
            "major_diameter": q(6.0), "pitch": q(1.0), "evidence": ['fixture']}


def interface(identifier, kind, dimensions=None, thread_data=None, datum=None):
    item = mi.new_interface(identifier, kind)
    item["dimensions"] = dimensions or {}
    item["thread"] = thread_data
    item["frame"] = datum
    return item


def record(definition_id, part_number, interfaces):
    rec = catalog.new_record(definition_id, manufacturer="FIXTURE", part_number=part_number)
    rec["sources"] = {'fixture': dict(FIXTURE)}
    rec["interfaces"] = list(interfaces)
    rec["evidence_level"] = 'visual_approximation'
    return catalog.validate(rec)


# A base whose socket sits 10 mm above its origin, a post whose foot is 2 mm below its own origin, and
# an optic holder on top of the post. The numbers are chosen so every expected pose is checkable by hand.
SQRT_HALF = math.sqrt(0.5)
DOWN = (0.0, 1.0, 0.0, 0.0)          # pi about X: the frame's +Z points along the part's local -Z
BASE = record("fixture:base", "FIXTURE-BASE",
              [interface("top", 'thread', {"depth": q(12.0)}, thread('internal'), frame((0, 0, 10))),
               # a second socket on the side, its +Z along +X (pi/2 about Y)
               interface("side", 'thread', {"depth": q(12.0)}, thread('internal'),
                         frame((20, 0, 0), (SQRT_HALF, 0.0, SQRT_HALF, 0.0)))])
# Schema v1: a frame's +Z is the OUTWARD connection axis / surface normal. A post's foot therefore
# points DOWN out of the part, which is what makes the post stand upright once the two frames are
# turned to face each other.
POST = record("fixture:post", "FIXTURE-POST",
              [interface("foot", 'thread', {"engagement_max": q(8.0), "insertion_max": q(4.0)},
                         thread('external'), frame((0, 0, -2), DOWN)),
               interface("head", 'thread', {"depth": q(6.0)}, thread('internal'), frame((0, 0, 40)))])
HOLDER = record("fixture:holder", "FIXTURE-HOLDER",
                [interface("stem", 'thread', {"engagement_max": q(5.0)}, thread('external'),
                           frame((0, 0, -3), DOWN))])
NO_DATUM = record("fixture:no-datum", "FIXTURE-NODATUM",
                  [interface("stem", 'thread', {"engagement_max": q(5.0)}, thread('external'), None)])
# Two plates and two rods: the second rod closes a loop, which is measured rather than placed.
BORE = {"diameter": q(6.1), "clearance": q(0.2), "insertion_min": q(4.0)}
PLATE = record("fixture:plate", "FIXTURE-PLATE",
               [interface("bore_1", 'smooth_bore', dict(BORE), None, frame((-15, 0, 0))),
                interface("bore_2", 'smooth_bore', dict(BORE), None, frame((15, 0, 0)))])
ROD = record("fixture:rod", "FIXTURE-ROD",
             [interface("end_a", 'shaft', {"diameter": q(6.0), "insertion_max": q(20.0)}, None,
                        frame((0, 0, 0), DOWN)),
              interface("end_b", 'shaft', {"diameter": q(6.0), "insertion_max": q(20.0)}, None,
                        frame((0, 0, 50)))])
CAGE_INSERTION = 4.0           # the bores state insertion_min 4 mm, so every cage hop is seated that deep

scene = bpy.context.scene
scene.optics.live_enabled = False
mirror = eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0))          # a real optic, seated on real hardware
PARTS = {"G_base": BASE, "G_post": POST, "G_nodatum": NO_DATUM,
         "G_plate1": PLATE, "G_plate2": PLATE, "G_rod1": ROD, "G_rod2": ROD}
objects = {}
for name, template in PARTS.items():
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    catalog.attach_object(obj, catalog.validate(dict(template, instance_id=name + ":1")))
    objects[name] = obj
catalog.attach_object(mirror, catalog.validate(dict(HOLDER, instance_id="M:1")))
objects["G_base"].location = (100.0, 50.0, 0.0)
bpy.context.view_layer.update()
api.enable_manual_assembly(True)


def socket_world(name, interface_id):
    """The world transform of one interface, read back from the scene the same way a bench is measured."""
    obj = bpy.data.objects[name]
    record = catalog.normalized(catalog.read_object(obj)["record"])
    item = next(i for i in record["interfaces"] if i["id"] == interface_id)
    return asm.compose(api._matrix_to_rigid(obj.matrix_world), asm.frame_transform(item["frame"]))


SEAT_TOL_MM = 1e-4       # object matrices are float32; ~1e-6 relative at 100 mm coordinates


def mates(name_a, interface_a, name_b, interface_b):
    a, b = socket_world(name_a, interface_a), socket_world(name_b, interface_b)
    gap = math.dist(a[1], b[1])
    axis = asm._angle_between(asm._axis(a, 2), tuple(-v for v in asm._axis(b, 2)))
    return gap, axis


print("[seating a carrying joint places the part from the two declared frames]")
j_base_post = api.join_parts("G_base", "top", "G_post", "foot")
before = objects["G_post"].matrix_world.translation.copy()
dry = api.set_joint_state(j_base_post["joint"]["id"], 'seated', dry_run=True)
check("dry_run reports the pose it would set", dry.get("ok") and dry["placed"]["object"] == "G_post",
      dry.get("placed"))
check("dry_run moved nothing", objects["G_post"].matrix_world.translation == before)
seated = api.set_joint_state(j_base_post["joint"]["id"], 'seated')
gap, axis = mates("G_base", "top", "G_post", "foot")
check("the two frames end up coincident", gap < SEAT_TOL_MM, gap)
check("and anti-parallel", axis < 1e-4, axis)
check("the post's origin lands where the frames put it: base origin + 10 mm socket + 2 mm foot offset",
      (objects["G_post"].matrix_world.translation - Vector((100.0, 50.0, 12.0))).length < SEAT_TOL_MM,
      tuple(objects["G_post"].matrix_world.translation))
check("the answer says what it did and does not call it a measured seat",
      "declared frames" in seated.get("geometry_note", ""), seated.get("geometry_note"))

print("[the whole sub-assembly rides its support]")
j_post_optic = api.join_parts("G_post", "head", "M", "stem")
api.set_joint_state(j_post_optic["joint"]["id"], 'seated')
gap, axis = mates("G_post", "head", "M", "stem")
check("the optic seats on the post head", gap < SEAT_TOL_MM and axis < 1e-4, (gap, axis))
optic_before = mirror.matrix_world.translation.copy()
objects["G_base"].location = (100.0, 50.0, 25.0)
bpy.context.view_layer.update()
check("moving the base carries the post", abs(objects["G_post"].matrix_world.translation.z - 37.0) < SEAT_TOL_MM,
      objects["G_post"].matrix_world.translation.z)
check("and the optic on top of it, as one body",
      (mirror.matrix_world.translation - (optic_before + Vector((0, 0, 25.0)))).length < SEAT_TOL_MM,
      tuple(mirror.matrix_world.translation))
objects["G_base"].location = (100.0, 50.0, 0.0)
bpy.context.view_layer.update()

print("[insertion and clocking are explicit, and bounded by what the parts state]")
api.set_joint_state(j_base_post["joint"]["id"], 'aligned')
deep = api.set_joint_state(j_base_post["joint"]["id"], 'seated', insertion_mm=3.0)
check("a stated insertion goes that far into the parent, and no further",
      abs(objects["G_post"].matrix_world.translation.z - 9.0) < SEAT_TOL_MM,
      objects["G_post"].matrix_world.translation.z)
check("the placement cites the evidence of the limit it checked", deep.get("evidence") == ['fixture'],
      deep.get("evidence"))
api.set_joint_state(j_base_post["joint"]["id"], 'aligned')
pose_before = objects["G_post"].matrix_world.copy()
too_deep = api.set_joint_state(j_base_post["joint"]["id"], 'seated', insertion_mm=9.0)
check("past the stated insertion_max it is refused, with the number it violated",
      "error" in too_deep and "insertion_max" in too_deep["error"], too_deep.get("error"))
check("the refused seating moved nothing", objects["G_post"].matrix_world == pose_before)
check("and did not record the state either",
      api.assembly_graph()["joints"][0]["state"] == 'aligned')
api.set_joint_state(j_base_post["joint"]["id"], 'seated', clock_deg=90.0)
clocked = socket_world("G_post", "foot")
check("clocking turns the part about the mating axis",
      abs(asm._angle_between(asm._axis(clocked, 0), (1.0, 0.0, 0.0)) - 90.0) < 1e-4,
      asm._angle_between(asm._axis(clocked, 0), (1.0, 0.0, 0.0)))
api.set_joint_state(j_base_post["joint"]["id"], 'aligned')
api.set_joint_state(j_base_post["joint"]["id"], 'seated')

print("[loosening a screw does not move the part]")
api.set_joint_state(j_base_post["joint"]["id"], 'aligned')
api.set_joint_state(j_base_post["joint"]["id"], 'seated', insertion_mm=3.0)
api.set_joint_state(j_base_post["joint"]["id"], 'fastened')
tight = objects["G_post"].matrix_world.copy()
loose = api.set_joint_state(j_base_post["joint"]["id"], 'seated')
check("fastened -> seated leaves the post 3 mm deep, not back at the datum",
      loose.get("ok") and objects["G_post"].matrix_world == tight and "placed" not in loose,
      (loose.get("placed"), tuple(objects["G_post"].matrix_world.translation)))
api.set_joint_state(j_base_post["joint"]["id"], 'aligned')
api.set_joint_state(j_base_post["joint"]["id"], 'seated')

print("[no datum, no placement]")
j_nodatum = api.join_parts("G_base", "side", "G_nodatum", "stem")
check("the joint itself is allowed: the threads do mate", j_nodatum.get("ok"), j_nodatum.get("error"))
pose_before = objects["G_nodatum"].matrix_world.copy()
refused = api.set_joint_state(j_nodatum["joint"]["id"], 'seated')
check("but seating it is refused: the stem states no frame",
      "error" in refused and refused["missing"] == ["frame of interface stem on G_nodatum"],
      refused.get("missing"))
check("nothing moved and the state stayed aligned",
      objects["G_nodatum"].matrix_world == pose_before
      and api.assembly_graph()["joints"][-1]["state"] == 'aligned')

print("[a joint that closes a loop is measured, never placed]")
r1a = api.join_parts("G_plate1", "bore_1", "G_rod1", "end_a")
api.set_joint_state(r1a["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION)
r1b = api.join_parts("G_plate2", "bore_1", "G_rod1", "end_b")
api.set_joint_state(r1b["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION)
r2a = api.join_parts("G_plate1", "bore_2", "G_rod2", "end_a")
api.set_joint_state(r2a["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION)
loop = api.join_parts("G_plate2", "bore_2", "G_rod2", "end_b")
check("the fourth joint carries no pose", loop["joint"]["carries"] is None and loop["joint"]["closes_loop"])
poses = {name: objects[name].matrix_world.copy() for name in ("G_plate1", "G_plate2", "G_rod1", "G_rod2")}
needs_tolerance = api.set_joint_state(loop["joint"]["id"], 'seated',
                                     insertion_mm=CAGE_INSERTION)
check("seating it asks for the tolerance schema v1 does not state",
      "error" in needs_tolerance and needs_tolerance["missing"] == ["tolerance_mm", "tolerance_deg"],
      needs_tolerance.get("missing"))
check("and reports the residual it measured, rather than nothing",
      set(needs_tolerance["residual"]) == {"gap_mm", "axis_deg", "clock_deg"},
      needs_tolerance.get("residual"))
closed = api.set_joint_state(loop["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION,
                            tolerance_mm=1e-3, tolerance_deg=1e-3)
check("with the parts where the other three joints put them, the loop closes",
      closed.get("ok") and closed["residual"]["gap_mm"] < 1e-4, closed.get("residual"))
check("closing the loop moved nothing at all",
      all(objects[name].matrix_world == poses[name] for name in poses))

print("[a loop that does not close is refused, not fudged]")
api.set_joint_state(loop["joint"]["id"], 'aligned')
api.set_joint_state(r2a["joint"]["id"], 'aligned')
objects["G_rod2"].location = objects["G_rod2"].location + Vector((0.0, 4.0, 0.0))
bpy.context.view_layer.update()
poses = {name: objects[name].matrix_world.copy() for name in ("G_plate1", "G_plate2", "G_rod1", "G_rod2")}
unsolvable = api.set_joint_state(loop["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION,
                                tolerance_mm=0.05, tolerance_deg=0.05)
check("the answer says the stated geometry has no consistent pose",
      "error" in unsolvable and unsolvable.get("unsolvable") is True
      and abs(unsolvable["residual"]["gap_mm"] - 4.0) < 1e-6, unsolvable.get("error"))
check("nothing was moved to make it fit",
      all(objects[name].matrix_world == poses[name] for name in poses))
check("and the joint stayed aligned", api.assembly_graph()["joints"][-1]["state"] == 'aligned')
back = api.set_joint_state(r2a["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION)
api.set_joint_state(loop["joint"]["id"], 'seated', insertion_mm=CAGE_INSERTION,
                    tolerance_mm=1e-3, tolerance_deg=1e-3)
check("re-seating the rod puts it back where the frames say, to the micron",
      back.get("ok") and back["placed"]["moved_mm"] > 3.9, back.get("placed"))
check("and the loop agrees again",
      api.assembly_graph()["joints"][-1]["state"] == 'seated')

print("[releasing a part leaves it where it stands]")
where = mirror.matrix_world.copy()
released = api.set_joint_state(j_post_optic["joint"]["id"], 'aligned')
check("the optic is released", released.get("released") == "M", released.get("released"))
check("it did not jump", mirror.matrix_world == where and mirror.parent is None)
api.set_joint_state(j_post_optic["joint"]["id"], 'seated')
check("and re-seating re-parents it", mirror.parent is bpy.data.objects["G_post"])

print("[Dress Bench does not stack a second invented post under a real mount]")
eg.source("S", (-100, 0, 0), (1, 0, 0))
eg.detector("D", (0, 120, 0), (0, 1, 0))
bpy.context.view_layer.update()
optic_pose = mirror.matrix_world.copy()
optomech.dress(scene)
dressed = [o.name for o in scene.objects if o.name.startswith(optomech.BENCH_PREFIX)]
check("the manually mounted optic is skipped", "M" in optomech.manually_mounted(scene),
      sorted(optomech.manually_mounted(scene)))
check("the optics that stand on nothing are still dressed", len(dressed) > 0, len(dressed))
check("dressing did not move the manual assembly",
      mirror.matrix_world == optic_pose and mirror.parent is bpy.data.objects["G_post"])
optomech.strip(scene)
optomech.dress(scene)
check("strip and re-dress keep the placement and the parenting",
      mirror.matrix_world == optic_pose and mirror.parent is bpy.data.objects["G_post"]
      and bpy.data.objects.get("G_post") is not None)
optomech.strip(scene)

print("[save, reload, and the mm-only gate]")
graph_before = api.assembly_graph()
with tempfile.TemporaryDirectory(prefix='assembly-geometry-') as directory:
    path = str(Path(directory) / 'placed.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    scene = bpy.context.scene
    reloaded = bpy.data.objects["M"]
    check("the placement survives save/reload",
          (reloaded.matrix_world.translation - optic_pose.translation).length < SEAT_TOL_MM,
          tuple(reloaded.matrix_world.translation))
    check("so does the parenting", reloaded.parent is bpy.data.objects["G_post"])
    check("and the graph", api.assembly_graph()["ownership"] == graph_before["ownership"])
scene = bpy.context.scene
scene.optics.scene_units_authoritative = True
scene.unit_settings.scale_length = 1.0
metre = api.set_joint_state(api.assembly_graph()["joints"][0]["id"], 'aligned')
check("in a declared metre scene, seating refuses: this hardware is millimetre-only",
      "error" in api.set_joint_state(api.assembly_graph()["joints"][0]["id"], 'seated')
      or "error" in metre, metre.get("error"))
scene.optics.scene_units_authoritative = False

print("[the MCP surface still matches]")
server = open(str(Path(__file__).resolve().parents[1] / "mcp" / "optics_mcp_server.py")).read()
for name in ("clock_deg", "insertion_mm", "tolerance_mm", "tolerance_deg"):
    check("MCP set_joint_state exposes %s" % name, name in server)
caps = api.capabilities()
check("capabilities still says there is no assembly engine and no validated fit",
      caps["mechanical_assembly"]["available"] is False, caps["mechanical_assembly"]["available"])

print("MECHANICAL ASSEMBLY GEOMETRY %s (%d/%d checks)"
      % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("assembly geometry witnesses failed")
