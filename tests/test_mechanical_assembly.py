"""Stage 04a witness: the assembly graph records how parts are joined, and refuses what it cannot know.

Every part here is a FIXTURE: synthetic, manufacturer "FIXTURE", https://example.org/fixture. That is
deliberate. Stage 03 used the real sourced rows to show incompatible pairs, but the stage-01 inventory
still has no sourced pair that mates, so a real `compatible` join cannot be built from evidence yet.
The rules under test -- ownership versus the physical graph, the state order, the locks, the motion
gate, atomicity -- are graph rules and do not depend on the numbers being real. A joint recorded here
is a stated mating, not a measured fit, and this stage places no geometry.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_mechanical_assembly.py
"""
import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import (elements_generic as eg, mechanical_assembly as asm,
                                   mechanical_catalog as catalog, mechanical_interfaces as mi,
                                   optics_api as api, optomech, scan)

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


FIXTURE = {"url": "https://example.org/fixture", "locator": "synthetic stage-04 fixture",
           "revision": None, "checked_on": "2026-09-22", "sha256": None}


def q(value, unit='mm', limit=None):
    return {"value": value, "unit": unit, "evidence": ['fixture'], "tolerance": None,
            "model_error_limit": limit}


def thread(standard, gender, major, pitch, form='M'):
    return {"standard": standard, "gender": gender, "hand": 'right', "form": form, "fit_class": None,
            "major_diameter": q(major), "pitch": q(pitch), "evidence": ['fixture']}


def interface(identifier, kind, dimensions=None, thread_data=None, lock=None):
    item = mi.new_interface(identifier, kind)
    item["dimensions"] = dimensions or {}
    item["thread"] = thread_data
    # Stage 04b will not seat an interface that states no datum, and this file is about the graph, not
    # the geometry -- so every fixture carries a trivial frame at its own origin.
    item["frame"] = {"origin": [0.0, 0.0, 0.0], "unit": 'mm', "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                     "evidence": ['fixture']}
    if lock:
        item["lock"] = {"kind": lock, "state": 'unlocked'}
    return item


def record(definition_id, part_number, interfaces, motions=()):
    rec = catalog.new_record(definition_id, manufacturer="FIXTURE", part_number=part_number)
    rec["sources"] = {'fixture': dict(FIXTURE)}
    rec["interfaces"] = list(interfaces)
    rec["motions"] = list(motions)
    rec["evidence_level"] = 'visual_approximation'
    return catalog.validate(rec)


# A base with an M6 hole, a holder screwed into it whose bore takes a post, a post carrying a mount,
# and a two-plate/two-rod cage: the smallest set that exercises a tree and a closed loop.
BASE = record("fixture:base", "FIXTURE-BASE",
              [interface("hole", 'thread', {"depth": q(10.0)}, thread("M6", 'internal', 6.0, 1.0))])
HOLDER = record("fixture:holder", "FIXTURE-HOLDER",
                [interface("stud", 'thread', {"engagement_max": q(8.0)},
                           thread("M6", 'external', 6.0, 1.0)),
                 interface("bore", 'smooth_bore',
                           {"diameter": q(12.8), "clearance": q(0.2), "insertion_min": q(10.0)},
                           lock='thumbscrew')],
                [dict(id='height', interface_id='bore', kind='translation',
                      minimum=q(0.0), maximum=q(40.0), evidence=['fixture'])])
POST = record("fixture:post", "FIXTURE-POST",
              [interface("shaft", 'shaft', {"diameter": q(12.7), "insertion_max": q(50.0)}),
               interface("top", 'thread', {"depth": q(6.0)}, thread("M4", 'internal', 4.0, 0.7))])
MOUNT = record("fixture:mount", "FIXTURE-MOUNT",
               [interface("post_screw", 'thread', {"engagement_max": q(5.0)},
                          thread("M4", 'external', 4.0, 0.7))],
               [dict(id='tip', interface_id='post_screw', kind='rotation',
                     minimum={"value": -4.0, "unit": 'deg', "evidence": ['fixture'], "tolerance": None,
                              "model_error_limit": None},
                     maximum={"value": 4.0, "unit": 'deg', "evidence": ['fixture'], "tolerance": None,
                              "model_error_limit": None}, evidence=['fixture'])])
BORES = {"diameter": q(6.1), "clearance": q(0.2), "insertion_min": q(4.0)}
PLATE = record("fixture:cage-plate", "FIXTURE-PLATE",
               [interface("bore_1", 'smooth_bore', dict(BORES)),
                interface("bore_2", 'smooth_bore', dict(BORES))])
ROD = record("fixture:cage-rod", "FIXTURE-ROD",
             [interface("end_a", 'shaft', {"diameter": q(6.0), "insertion_max": q(20.0)}),
              interface("end_b", 'shaft', {"diameter": q(6.0), "insertion_max": q(20.0)})])
WRONG = record("fixture:imperial-stud", "FIXTURE-IMPERIAL",
               [interface("stud", 'thread', {"engagement_max": q(8.0)},
                          thread("1/4-20", 'external', 6.35, 1.27, form='UN'))])
NO_CLEARANCE = record("fixture:plain-bore", "FIXTURE-PLAINBORE",
                      [interface("bore", 'smooth_bore', {"diameter": q(12.8)})])
ADAPTER = record("fixture:m6-to-quarter", "FIXTURE-ADAPTER",
                 [interface("male", 'thread', {"engagement_max": q(6.0)},
                            thread("M6", 'external', 6.0, 1.0)),
                  interface("female", 'thread', {"depth": q(9.0)},
                            thread("1/4-20", 'internal', 6.35, 1.27, form='UN'))])

scene = bpy.context.scene
scene.optics.live_enabled = False
# Optical elements so Dress Bench has something to dress; the mechanical parts are plain objects.
eg.source("S", (-100, 0, 0), (1, 0, 0))
eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0))
eg.detector("D", (0, 120, 0), (0, 1, 0))

PARTS = {"P_base": BASE, "P_holder": HOLDER, "P_post": POST, "P_mount": MOUNT,
         "P_plate1": PLATE, "P_plate2": PLATE, "P_rod1": ROD, "P_rod2": ROD,
         "P_wrong": WRONG, "P_plainbore": NO_CLEARANCE, "P_adapter": ADAPTER,
         "BENCH_Probe": BASE}
for name, template in PARTS.items():
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    # Each object gets its OWN instance_id: a copied record is what the graph refuses to address.
    catalog.attach_object(obj, catalog.validate(dict(template, instance_id=name + ":1")))
bpy.context.view_layer.update()


def digest():
    return [(o.name, tuple(round(c, 6) for c in o.matrix_world.translation), o.mechanics.record_json)
            for o in sorted(scene.objects, key=lambda x: x.name)]


scene_before = digest()
trace_before = repr(scan._trace(scene))

print("[the feature flag: nothing is written while manual assembly is off]")
check("capabilities starts with manual assembly off",
      api.capabilities()["mechanical_assembly"]["manual_assembly"] is False)
refused = api.join_parts("P_base", "hole", "P_holder", "stud")
check("a write refuses while the flag is off", "error" in refused and "enable_manual_assembly" in refused["error"],
      refused.get("error"))
check("the graph is still empty", scene.mechanics.graph_json == "", repr(scene.mechanics.graph_json))
check("reading works with the flag off", api.assembly_graph().get("joints") == [])
api.enable_manual_assembly(True)

print("[stage 03 is the gate: only a compatible verdict becomes a joint]")
empty = scene.mechanics.graph_json
bad = api.join_parts("P_base", "hole", "P_wrong", "stud")
check("an incompatible pair is refused with its verdict",
      "error" in bad and bad.get("verdict") == 'incompatible', bad.get("error"))
check("the refusal left the stored graph byte-identical", scene.mechanics.graph_json == empty)
unknown = api.join_parts("P_plainbore", "bore", "P_post", "shaft")
check("an unknown fit is refused and names the missing field",
      "error" in unknown and unknown.get("verdict") == 'unknown' and 'clearance' in unknown.get("missing", []),
      unknown.get("missing"))
routed = api.join_parts("P_base", "hole", "P_wrong", "stud", adapters=["P_adapter"])
check("adapter_required is refused, with the chain and what to do instead",
      "error" in routed and routed.get("verdict") == 'adapter_required'
      and routed["adapter_chain"] and "adapter" in routed.get("remedy", ""), routed.get("remedy"))
check("no refusal wrote anything", scene.mechanics.graph_json == empty)
self_join = api.join_parts("P_post", "shaft", "P_post", "top")
check("a part cannot be joined to itself", "error" in self_join, self_join.get("error"))
bench = api.join_parts("BENCH_Probe", "hole", "P_holder", "stud")
check("automatic bench dressing is not a mechanical part",
      "error" in bench and "Dress Bench" in bench["error"], bench.get("error"))

print("[dry_run decides without writing]")
dry = api.join_parts("P_base", "hole", "P_holder", "stud", dry_run=True)
check("dry_run reports the joint it would make", dry.get("ok") and dry["created"] and dry["dry_run"],
      dry.get("joint"))
check("dry_run wrote nothing", scene.mechanics.graph_json == empty)

print("[the ownership forest]")
j1 = api.join_parts("P_base", "hole", "P_holder", "stud")
check("the first joint is created at aligned",
      j1.get("ok") and j1["created"] and j1["joint"]["state"] == 'aligned', j1.get("joint"))
check("the holder is carried by the base", j1["joint"]["carries"] == 'b')
check("the joint cites the evidence its verdict rested on", j1["compatibility"]["evidence"] == ['fixture'],
      j1["compatibility"])
again = api.join_parts("P_base", "hole", "P_holder", "stud")
check("calling twice does not make a second joint",
      again.get("ok") and again["created"] is False and again["joint"]["id"] == j1["joint"]["id"],
      again.get("note"))
occupied = api.join_parts("P_base", "hole", "P_adapter", "male")
check("one socket holds one joint, even for a pair that would otherwise mate",
      "error" in occupied and "already carries" in occupied["error"], occupied.get("error"))
unruled = api.join_parts("P_base", "hole", "P_rod1", "end_a")
check("a pairing schema v1 has no rule for stays unknown, not incompatible",
      "error" in unruled and unruled.get("verdict") == 'unknown', unruled.get("missing"))
j2 = api.join_parts("P_holder", "bore", "P_post", "shaft")
j3 = api.join_parts("P_post", "top", "P_mount", "post_screw")
graph = api.assembly_graph()
check("three joints form a chain base -> holder -> post -> mount",
      graph["ownership"] == {"P_holder:1": "P_base:1", "P_post:1": "P_holder:1",
                             "P_mount:1": "P_post:1"}, graph["ownership"])
check("no joint in a tree closes a loop", graph["loops"] == [], graph["loops"])

print("[the physical graph keeps the loops the transform tree cannot]")
r1a = api.join_parts("P_plate1", "bore_1", "P_rod1", "end_a")
r1b = api.join_parts("P_plate2", "bore_1", "P_rod1", "end_b")
check("the second plate is carried by the rod, since the rod already has a parent",
      r1b["joint"]["carries"] == 'a', r1b["joint"])
r2a = api.join_parts("P_plate1", "bore_2", "P_rod2", "end_a")
forced = api.join_parts("P_plate2", "bore_2", "P_rod2", "end_b", carries='a')
check("an explicit second parent is refused with the reason",
      "error" in forced and "one parent" in forced["error"] and "carries='none'" in forced.get("remedy", ""),
      forced.get("error"))
r2b = api.join_parts("P_plate2", "bore_2", "P_rod2", "end_b")
check("the loop-closing joint is still recorded, carrying no pose",
      r2b.get("ok") and r2b["joint"]["carries"] is None and r2b["joint"]["closes_loop"] is True,
      r2b.get("note"))
graph = api.assembly_graph()
check("the physical graph reports the loop and the multi-point plate",
      graph["loops"] == [r2b["joint"]["id"]]
      and sum(1 for j in graph["joints"] if "P_plate2" in
              (j["parts"]["a"]["object"], j["parts"]["b"]["object"])) == 2, graph["loops"])
check("the ownership map is still a forest with one parent each",
      len(set(graph["ownership"])) == len(graph["ownership"]) and "P_plate2:1" in graph["ownership"],
      graph["ownership"])
cyclic = {"schema_version": 1, "joints": [
    dict(id='c1', a=dict(instance_id='x', definition_id=None, object=None, interface='i'),
         b=dict(instance_id='y', definition_id=None, object=None, interface='i'),
         state='aligned', carries='b', closes_loop=False, verdict='compatible', evidence=[]),
    dict(id='c2', a=dict(instance_id='y', definition_id=None, object=None, interface='j'),
         b=dict(instance_id='x', definition_id=None, object=None, interface='j'),
         state='aligned', carries='b', closes_loop=True, verdict='compatible', evidence=[])]}
try:
    asm.validate_graph(cyclic)
except mi.SchemaError as exc:
    check("a hand-built ownership cycle cannot even be stored", "cycle" in str(exc), str(exc))
else:
    check("a hand-built ownership cycle cannot even be stored", False)

two_parents = {"schema_version": 1, "joints": [
    dict(id='p1', a=dict(instance_id='x', definition_id=None, object=None, interface='i'),
         b=dict(instance_id='z', definition_id=None, object=None, interface='i'),
         state='aligned', carries='b', closes_loop=False, verdict='compatible', evidence=[]),
    dict(id='p2', a=dict(instance_id='y', definition_id=None, object=None, interface='j'),
         b=dict(instance_id='z', definition_id=None, object=None, interface='j'),
         state='aligned', carries='b', closes_loop=False, verdict='compatible', evidence=[])]}
try:
    asm.validate_graph(two_parents)
except mi.SchemaError as exc:
    check("a hand-built second parent cannot be stored either", "one parent" in str(exc), str(exc))
else:
    check("a hand-built second parent cannot be stored either", False)

print("[the state order: align, seat, fasten, lock -- one step at a time]")
jid = j2["joint"]["id"]
skip = api.set_joint_state(jid, 'fastened')
check("skipping a state is refused and says which one was skipped",
      "error" in skip and "seated" in skip["error"], skip.get("error"))
check("the refused step changed nothing", api.assembly_graph()["joints"][1]["state"] == 'aligned')
shallow = api.set_joint_state(jid, 'seated')
check("seating refuses a depth the bore says is too little",
      "error" in shallow and "insertion_min" in shallow["error"], shallow.get("error"))
seated = api.set_joint_state(jid, 'seated', insertion_mm=10.0)
check("seating is one step", seated.get("ok") and seated["joint"]["state"] == 'seated')
check("and it placed the post on the holder", seated["placed"]["object"] == "P_post",
      seated.get("placed"))
dry_state = api.set_joint_state(jid, 'fastened', dry_run=True)
check("dry_run on a state change writes nothing",
      dry_state.get("ok") and api.assembly_graph()["joints"][1]["state"] == 'seated')
api.set_joint_state(jid, 'fastened')
locked = api.set_joint_state(jid, 'locked')
check("the holder's declared thumbscrew allows a locked state",
      locked.get("ok") and locked["joint"]["state"] == 'locked', locked.get("joint"))
unlockable = api.set_joint_state(j3["joint"]["id"], 'seated')
api.set_joint_state(j3["joint"]["id"], 'fastened')
no_lock = api.set_joint_state(j3["joint"]["id"], 'locked')
check("a pair that declares no lock cannot be locked",
      "error" in no_lock and no_lock.get("missing") == ['interface lock kind'], no_lock.get("error"))

print("[a locked joint refuses the motion it holds]")
motions = api.permitted_motions("P_holder")
height = next(m for m in motions["motions"] if m["motion"] == 'height')
check("the locked bore refuses its own travel",
      height["permitted"] is False and height["joint_state"] == 'locked'
      and height["next_step"] == {"joint": jid, "state": 'fastened'}, height)
check("the stated travel limits come through in millimetres",
      (height["minimum"], height["maximum"]) == (0.0, 40.0), height)
api.set_joint_state(jid, 'fastened')
fastened = next(m for m in api.permitted_motions("P_holder")["motions"] if m["motion"] == 'height')
check("a fastened joint still refuses it, and names the step that frees it",
      fastened["permitted"] is False and fastened["next_step"]["state"] == 'seated', fastened["reason"])
back = api.set_joint_state(jid, 'seated')
check("loosening back to seated needs no insertion: nothing is placed again",
      back.get("ok") and "placed" not in back, back.get("error"))
free = next(m for m in api.permitted_motions("P_holder")["motions"] if m["motion"] == 'height')
check("seated leaves the motion free, because seating is what it is for", free["permitted"] is True,
      free["reason"])
loose = api.permitted_motions("P_mount")["motions"][0]
check("a motion at a fastened interface of another part is judged by its own joint",
      loose["motion"] == 'tip' and loose["permitted"] is False and loose["joint_state"] == 'fastened',
      loose)

print("[a part comes off in the reverse order it went on]")
stuck = api.separate_parts(jid)
check("a seated joint does not come apart; the next step back is named",
      "error" in stuck and stuck["next_step"] == {"joint": jid, "state": 'aligned'}, stuck.get("error"))
api.set_joint_state(j1["joint"]["id"], 'seated')
api.set_joint_state(j1["joint"]["id"], 'fastened')
plan = api.disassembly_plan("P_holder")
check("the plan lists what the holder carries", [c["object"] for c in plan["carries"]] == ["P_post", "P_mount"],
      plan["carries"])
check("releasing the holder opens only the joint to the base, in reverse order",
      plan["release"] == [{"joint": j1["joint"]["id"], "state": 'seated'},
                          {"joint": j1["joint"]["id"], "state": 'aligned'},
                          {"joint": j1["joint"]["id"], "separate": True}], plan["release"])
check("a full disassembly opens the joints above it too, deepest first",
      [s["joint"] for s in plan["full"] if s.get("separate")]
      == [j3["joint"]["id"], j2["joint"]["id"], j1["joint"]["id"]],
      [s for s in plan["full"] if s.get("separate")])
api.set_joint_state(j3["joint"]["id"], 'seated')
api.set_joint_state(j3["joint"]["id"], 'aligned')
gone = api.separate_parts(j3["joint"]["id"])
check("an aligned joint separates", gone.get("ok") and gone["removed"]["id"] == j3["joint"]["id"])
check("the mount is no longer carried", "P_mount:1" not in api.assembly_graph()["ownership"])
check("separating did not delete the object or its record",
      bpy.data.objects.get("P_mount") is not None and bpy.data.objects["P_mount"].mechanics.record_json)

print("[the graph is one undoable property, and it survives save/reload]")
saved = scene.mechanics.graph_json
graph_before = api.assembly_graph()
api.set_joint_state(jid, 'aligned')
check("a state change is visible", api.assembly_graph()["joints"][1]["state"] == 'aligned')
scene.mechanics.graph_json = saved
check("restoring that one string restores the whole graph exactly",
      api.assembly_graph() == graph_before)
print("     note: bpy.ops.ed.undo cannot be polled in --background, so the undo STEP itself is not "
      "exercised here; what is shown is that one operation is one property write on one datablock.")
with tempfile.TemporaryDirectory(prefix='mechanical-assembly-') as directory:
    path = str(Path(directory) / 'assembly.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    scene = bpy.context.scene
    check("the graph survives save/reload byte-for-byte", scene.mechanics.graph_json == saved)
    check("so does the feature flag", scene.mechanics.manual_assembly is True)
    check("and the joints still resolve to their objects",
          api.assembly_graph()["ownership"] == graph_before["ownership"],
          api.assembly_graph()["ownership"])

print("[Dress Bench owns its own objects and leaves the assembly alone]")
optomech.dress(scene)
check("the bench is dressed", optomech.is_dressed(scene))
check("dressing did not touch the graph", scene.mechanics.graph_json == saved)
optomech.strip(scene)
optomech.dress(scene)
check("strip and re-dress keep every joint", api.assembly_graph()["ownership"] == graph_before["ownership"])
check("the dressed bench still carries no manual joint to a BENCH_ object",
      all(not (j["parts"]["a"]["object"] or "").startswith("BENCH_")
          and not (j["parts"]["b"]["object"] or "").startswith("BENCH_")
          for j in api.assembly_graph()["joints"]))
optomech.strip(scene)

check("Dress Bench owns the whole BENCH_ namespace: strip removed the BENCH_-named fixture, which "
      "is exactly why a joint to one is refused", bpy.data.objects.get("BENCH_Probe") is None)

print("[reads answer honestly when the data is gone or broken]")
bpy.data.objects.remove(bpy.data.objects["P_rod2"], do_unlink=True)
dangling = api.assembly_graph()
check("a deleted part leaves a dangling joint, not a silent removal",
      len(dangling["dangling"]) == 2 and all(d["instance_id"] == "P_rod2:1" for d in dangling["dangling"]),
      dangling["dangling"])
broken = scene.mechanics.graph_json
scene.mechanics.graph_json = '{"schema_version":99,"joints":[]}'
unreadable = api.assembly_graph()
check("an unreadable graph is reported, not repaired",
      "error" in unreadable and scene.mechanics.graph_json == '{"schema_version":99,"joints":[]}',
      unreadable.get("error"))
scene.mechanics.graph_json = broken

print("[nothing here is geometry]")
scene.optics.live_enabled = False
def compare(rows, poses):
    # BENCH_Probe is gone (Dress Bench owns that prefix) and P_rod2 was deleted on purpose. Seating
    # MOVES the parts it seats -- that is stage 04b's whole job -- so poses are compared only for the
    # objects no joint touches.
    return [r if poses else (r[0], r[2])
            for r in rows if not r[0].startswith("BENCH_") and r[0] != "P_rod2"]


check("no assembly call changed a record",
      compare(digest(), False) == compare(scene_before, False),
      [(a, b) for a, b in zip(compare(digest(), False), compare(scene_before, False)) if a != b][:2])
optical_now = [d for d in digest() if d[0] in ("S", "M", "D")]
check("and no optical element was moved: the parts that moved are the ones that were seated",
      optical_now == [d for d in scene_before if d[0] in ("S", "M", "D")], optical_now)
check("the optical trace is unchanged", repr(scan._trace(scene)) == trace_before)
caps = api.capabilities()
check("capabilities still reports no assembly engine and says why",
      caps["mechanical_assembly"]["available"] is False
      and caps["mechanical_assembly"]["graph_schema_version"] == 1
      and "No geometry" in caps["mechanical_assembly"]["status"], caps["mechanical_assembly"]["status"])
check("the new calls are listed in the tool groups",
      all(name in caps["tool_groups"]["place / assemble (opto-mechanics)"]
          for name in ("enable_manual_assembly", "join_parts", "set_joint_state", "separate_parts"))
      and all(name in caps["tool_groups"]["read / inspect (the AI's eyes -- call these to SEE the bench, never guess)"]
              for name in ("assembly_graph", "disassembly_plan", "permitted_motions")))

print("[the MCP server exposes the same calls]")
server = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "mcp", "optics_mcp_server.py")).read()
for name in ("enable_manual_assembly", "join_parts", "set_joint_state", "separate_parts",
             "assembly_graph", "disassembly_plan", "permitted_motions"):
    check("MCP and API both expose %s" % name, hasattr(api, name) and ("def %s(" % name) in server)

print("MECHANICAL ASSEMBLY %s (%d/%d checks)"
      % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("assembly witnesses failed")
