"""Stage 05a-2 witness: the real post and post holder, joined and taken apart through the engine.

The records come from mechanical_library, which is built from the vendor drawings. This checks four
things, in this order:
1. every value in a record equals the inventory fact it cites, so the two copies cannot drift;
2. stage 03 decides the real pairs the way the vendor's own statements do -- a TR50/M fits, a Ø12 mm
   TR50/M-JP fits too (the vendor says so), a Ø25 mm RS2P/M pillar does not go in;
3. stage 04 seats the post where the frames say, and that is the SAME place Dress Bench puts it, so
   the records and the generated geometry meet at one interface;
4. the stated limits bite: too shallow for the thumbscrew's ball, too deep for the bore, a locked
   thumbscrew holds the post, and the parts come apart in reverse order.

A seated post is a stated mating, not a measured fit: the drawings state no tolerances.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_support_assembly.py
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import (elements_generic as eg, mechanical_catalog as catalog,
                                   mechanical_compatibility as compat, mechanical_library as library,
                                   optics_api as api, optomech)

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


FACTS = {f["id"]: f for f in
         json.loads((ROOT / "docs/mechanics/product-evidence.json").read_text())["support_facts"]}

print("[1. the records say what the inventory says]")
records = {p: library.record(p) for p in library.parts()}
check("every library record passes schema v1", all(catalog.validate(r) for r in records.values()),
      library.parts())
check("two calls make two parts, not one duplicated record",
      library.record("TR50/M")["instance_id"] != library.record("TR50/M")["instance_id"])


def value_at(record, path):
    if path.startswith("motion:"):
        motion_id, field = path[len("motion:"):].split(".")
        return next(m for m in record["motions"] if m["id"] == motion_id)[field]["value"]
    interface_id, rest = path.split(".", 1)
    item = next(i for i in record["interfaces"] if i["id"] == interface_id)
    if rest == "frame.z":
        return item["frame"]["origin"][2]
    return item["dimensions"][rest]["value"]


drift = [(part, path, fact_id, value_at(records[part], path), FACTS[fact_id]["value"])
         for part, path, fact_id in library.PROVENANCE
         if abs(value_at(records[part], path) - float(FACTS[fact_id]["value"])) > 1e-9]
check("all %d provenance entries match their inventory facts" % len(library.PROVENANCE), not drift, drift)
derived = sorted({fact_id for _p, _path, fact_id in library.PROVENANCE
                  if FACTS[fact_id]["verification"] == "derived_from_published_nominals"})
check("the derived values are the ones the library says are derived",
      derived == ["ph50m_min_insertion_lower_bound", "ph_series_allowed_gap_lower_bound"], derived)
check("nothing claims more than 'unverified'",
      all(r["evidence_level"] == "unverified" for r in records.values()))
check("drawing sources pin the exact file that was read",
      all(len(s["sha256"] or "") == 64 for r in records.values() for sid, s in r["sources"].items()
          if sid.endswith("_drawing")))

print("[2. stage 03 agrees with the vendor]")
holder = catalog.normalized(records["PH50/M"])


def verdict(post):
    return compat.check(holder, "bore", catalog.normalized(records[post]), "shaft")


tr = verdict("TR50/M")
check("TR50/M fits PH50/M", tr["verdict"] == "compatible",
      [(r["rule"], r["result"], r["detail"]) for r in tr["direct"]["rules"]])
jp = verdict("TR50/M-JP")
check("a Ø12 mm TR50/M-JP fits too, as the vendor states", jp["verdict"] == "compatible",
      [(r["rule"], r["detail"]) for r in jp["direct"]["rules"]])
rs = verdict("RS2P/M")
check("a Ø25 mm RS2P/M pillar does not go in",
      rs["verdict"] == "incompatible" and any(r["rule"] == "bore.diameter" and r["result"] == "incompatible"
                                               for r in rs["direct"]["rules"]),
      [(r["rule"], r["detail"]) for r in rs["direct"]["rules"] if r["result"] == "incompatible"])
check("each verdict cites the drawings behind it",
      {"ph50m_drawing", "tr50m_drawing"} <= set(tr["evidence"]), tr["evidence"])

print("[3. seated where the frames say -- and where Dress Bench puts it]")
scene = bpy.context.scene
scene.optics.live_enabled = False
objects = {}
for name, part in (("PH", "PH50/M"), ("TR", "TR50/M"), ("RS", "RS2P/M")):
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    catalog.attach_object(obj, records[part])
    objects[name] = obj
objects["TR"].location = (80.0, 0.0, 0.0)
objects["RS"].location = (-80.0, 0.0, 0.0)
bpy.context.view_layer.update()
api.enable_manual_assembly(True)
empty = scene.mechanics.graph_json
wrong = api.join_parts("PH", "bore", "RS", "shaft")
check("joining the pillar is refused with the reason, and nothing is written",
      "error" in wrong and wrong.get("verdict") == "incompatible" and scene.mechanics.graph_json == empty,
      wrong.get("error"))
joined = api.join_parts("PH", "bore", "TR", "shaft")
jid = joined["joint"]["id"]
check("the real pair joins, the post carried by the holder",
      joined.get("ok") and joined["joint"]["carries"] == "b", joined.get("joint"))
shallow = api.set_joint_state(jid, "seated", insertion_mm=10.0)
check("10 mm is refused: the thumbscrew's ball would meet no post",
      "error" in shallow and "insertion_min" in shallow["error"], shallow.get("error"))
deep = api.set_joint_state(jid, "seated", insertion_mm=45.0)
check("45 mm is refused: the bore is 43.2 mm deep",
      "error" in deep and "insertion_max" in deep["error"], deep.get("error"))
before = objects["TR"].matrix_world.copy()
check("neither refusal moved the post", objects["TR"].matrix_world == before)
seated = api.set_joint_state(jid, "seated", insertion_mm=43.2)
post = objects["TR"].matrix_world
check("fully inserted, the post stands on the bore floor 6.8 mm above the holder's bottom",
      (post.translation - Vector((0.0, 0.0, 6.8))).length < 1e-4, tuple(post.translation))
check("upright and on the holder's axis",
      (post.to_3x3() @ Vector((0, 0, 1)) - Vector((0, 0, 1))).length < 1e-6, post.to_3x3())

# Dress Bench builds the same pair procedurally. Its post has to meet its holder at the same place.
eg.source("S", (-300, 0, 100), (1, 0, 0))
eg.mirror("M", (-200, 0, 100), (1, 0, 0), (0, 1, 0))
eg.detector("D", (-200, 120, 100), (0, 1, 0))
bpy.context.view_layer.update()
optomech.dress(scene)
bpy.context.view_layer.update()
dress_holder = sorted((o for o in scene.objects if o.name.startswith("BENCH_Holder_")), key=lambda o: o.name)[0]
tag = dress_holder.name[len("BENCH_Holder_"):]
dress_post = scene.objects["BENCH_Post_" + tag]
dress_seat = (min((dress_post.matrix_world @ v.co).z for v in dress_post.data.vertices)
              - min((dress_holder.matrix_world @ v.co).z for v in dress_holder.data.vertices))
record_seat = post.translation.z - objects["PH"].matrix_world.translation.z
check("the record-seated post and Dress Bench's post meet their holders at the same height",
      abs(dress_seat - record_seat) < 1e-4, "Dress Bench %.4f mm, records %.4f mm" % (dress_seat, record_seat))
optomech.strip(scene)

print("[4. the thumbscrew holds, and the parts come off in reverse]")
free = api.permitted_motions("PH")["motions"][0]
check("seated, the post can still slide along its 12.7-43.2 mm range",
      free["permitted"] and (free["minimum"], free["maximum"]) == (12.7, 43.2), free)
api.set_joint_state(jid, "fastened")
held = api.permitted_motions("PH")["motions"][0]
check("with the thumbscrew tightened it cannot", held["permitted"] is False, held["reason"])
locked = api.set_joint_state(jid, "locked")
check("the holder declares a hex-locking thumbscrew, so it can be locked",
      locked.get("ok") and locked["joint"]["state"] == "locked", locked.get("error"))
stuck = api.separate_parts(jid)
check("a locked post does not come out; the next step is named",
      "error" in stuck and stuck["next_step"] == {"joint": jid, "state": "fastened"}, stuck.get("error"))
plan = api.disassembly_plan("PH")
check("the plan walks it back: unlock, loosen, unseat, separate",
      [s.get("state") or ("separate" if s.get("separate") else None) for s in plan["full"]]
      == ["fastened", "seated", "aligned", "separate"], plan["full"])
api.set_joint_state(jid, "fastened")
where = objects["TR"].matrix_world.copy()
loosened = api.set_joint_state(jid, "seated")
check("loosening the thumbscrew leaves the post exactly where it was",
      loosened.get("ok") and objects["TR"].matrix_world == where and "placed" not in loosened,
      loosened.get("error") or loosened.get("placed"))
api.set_joint_state(jid, "aligned")
gone = api.separate_parts(jid)
check("walked back, it separates", gone.get("ok"), gone.get("error"))
check("released where it stood, still upright", objects["TR"].parent is None
      and (objects["TR"].matrix_world.translation - Vector((0.0, 0.0, 6.8))).length < 1e-4)

print("SUPPORT ASSEMBLY %s (%d/%d checks)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)),
      flush=True)
if not all(checks):
    raise AssertionError("support assembly witnesses failed")
