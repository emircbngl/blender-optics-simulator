"""Stage 03 witness: the compatibility engine decides from stated data, never from a resemblance.

Two kinds of fixture appear here, and they are kept apart on purpose:

* REAL rows carry the source ids and URLs from docs/mechanics/product-evidence.json: the 16 mm cage
  rod at 4 mm, the 60 mm cage plate bore at 6 mm, the KM100 adjuster thread 1/4-80 against the 8-32
  post fastener it is often confused with, and the flip mount's 5 mm screw-penetration caution. Those
  numbers are published nominal values, not mesh-verified dimensions.
* FIXTURE rows are synthetic (manufacturer "FIXTURE", https://example.org/fixture). The stage-01
  inventory has no sourced clearance, insertion or adapter data yet; these exercise the rules without
  pretending to be product data.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_mechanical_compatibility.py
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import (elements_generic as eg, mechanical_catalog as catalog,
                                   mechanical_compatibility as compat, optics_api as api)
from optical_alignment_sim.mechanical_interfaces import new_interface

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


REAL = {
    'cage16': {"url": "https://www.thorlabs.com/catalogpages/V21/169.PDF",
               "locator": "printed page 169; SR rods", "revision": None,
               "checked_on": "2026-09-16", "sha256": None},
    'cage60': {"url": "https://www.thorlabs.com/catalogpages/Obsolete/2023/LCP01T.pdf",
               "locator": "LCP01 and LCP01/M product table", "revision": None,
               "checked_on": "2026-09-16", "sha256": None},
    'km_archive': {"url": "https://www.thorlabs.com/images/Catalog/V19_02_Optomech.pdf",
                   "locator": "printed page 140 KM100/KM200", "revision": None,
                   "checked_on": "2026-09-16", "sha256": None},
    'flip': {"url": "https://punchout.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4110",
             "locator": "Filter Mount with 90 degree Flip; screw penetration caution", "revision": None,
             "checked_on": "2026-09-16", "sha256": None},
}
FIXTURE_SOURCE = {"url": "https://example.org/fixture", "locator": "synthetic test fixture",
                  "revision": None, "checked_on": "2026-09-16", "sha256": None}


def quantity(value, unit='mm', evidence=(), model_error_limit=None):
    return {"value": value, "unit": unit, "evidence": list(evidence),
            "tolerance": None, "model_error_limit": model_error_limit}


def interface(identifier, kind, dimensions=None, thread_data=None):
    item = new_interface(identifier, kind)
    item["dimensions"] = dimensions or {}
    item["thread"] = thread_data
    return item


def thread(standard, gender, major_mm, pitch_mm, evidence, hand='right', form='UN'):
    return {"standard": standard, "gender": gender, "hand": hand, "form": form, "fit_class": None,
            "major_diameter": quantity(major_mm, evidence=evidence),
            "pitch": quantity(pitch_mm, evidence=evidence), "evidence": list(evidence)}


def record(definition_id, sources, interfaces, manufacturer=None, part_number=None):
    rec = catalog.new_record(definition_id, manufacturer=manufacturer, part_number=part_number)
    rec["sources"] = dict(sources)
    rec["interfaces"] = interfaces
    rec["evidence_level"] = 'visual_approximation'
    return catalog.validate(rec)


print("[real evidence: a 16 mm cage rod does not belong in a 60 mm cage plate]")
rod16 = record("SR-rod-16mm", {'cage16': REAL['cage16']},
               [interface("rod", 'shaft', {"diameter": quantity(4.0, evidence=['cage16'])})],
               manufacturer="Thorlabs", part_number="SR2")
plate60 = record("cage-plate-60mm", {'cage60': REAL['cage60']},
                 [interface("rod_bore", 'smooth_bore',
                            {"diameter": quantity(6.0, evidence=['cage60']),
                             "clearance": quantity(0.1, evidence=['cage60'])})],
                 manufacturer="Thorlabs", part_number="LCP01")
res = compat.check(rod16, "rod", plate60, "rod_bore")
check("a 4 mm rod in a 6 mm cage bore is rejected, not called a fit",
      res["verdict"] == 'incompatible'
      and any(r["rule"] == 'bore.fit' and r["result"] == 'incompatible' for r in res["direct"]["rules"]),
      [(r["rule"], r["result"]) for r in res["direct"]["rules"]])
check("the rejection cites its sources", set(res["evidence"]) >= {'cage16', 'cage60'}, res["evidence"])

print("[real evidence: the KM100 adjuster thread is not the 8-32 post fastener]")
adjuster = record("KM100-adjuster", {'km_archive': REAL['km_archive']},
                  [interface("adjuster", 'thread', {"depth": quantity(12.0, evidence=['km_archive'])},
                             thread("1/4-80", 'internal', 6.35, 0.3175, ['km_archive']))],
                  manufacturer="Thorlabs", part_number="KM100")
post_screw = record("8-32-screw", {'km_archive': REAL['km_archive']},
                    [interface("screw", 'thread', {"engagement_max": quantity(6.0, evidence=['km_archive'])},
                               thread("8-32", 'external', 4.166, 0.794, ['km_archive']))],
                    manufacturer="FIXTURE", part_number="FIXTURE-8-32")
res = compat.check(adjuster, "adjuster", post_screw, "screw")
check("8-32 into a 1/4-80 adjuster is incompatible on standard and diameter",
      res["verdict"] == 'incompatible'
      and {r["rule"] for r in res["direct"]["rules"] if r["result"] == 'incompatible'}
      >= {'thread.standard', 'thread.major_diameter'},
      [(r["rule"], r["result"], r["detail"]) for r in res["direct"]["rules"]])

print("[real evidence: the flip mount's 5 mm screw-penetration caution]")
flip_mount = record("TRF90", {'flip': REAL['flip']},
                    [interface("post_hole", 'thread', {"depth": quantity(5.0, evidence=['flip'])},
                               thread("M4", 'internal', 4.0, 0.7, ['flip'], form='M'))],
                    manufacturer="Thorlabs", part_number="TRF90")
long_screw = record("M4x8", {'fixture': FIXTURE_SOURCE},
                    [interface("stud", 'thread', {"engagement_max": quantity(8.0, evidence=['fixture'])},
                               thread("M4", 'external', 4.0, 0.7, ['fixture'], form='M'))],
                    manufacturer="FIXTURE", part_number="FIXTURE-M4x8")
res = compat.check(flip_mount, "post_hole", long_screw, "stud")
check("a screw that reaches past the stated 5 mm penetration bottoms out",
      res["verdict"] == 'incompatible'
      and any(r["rule"] == 'thread.engagement' and r["result"] == 'incompatible'
              for r in res["direct"]["rules"]),
      [r for r in res["direct"]["rules"] if r["rule"] == 'thread.engagement'])

print("[same diameter, different pitch: the classic wrong-standard trap]")
unc = record("quarter-20", {'fixture': FIXTURE_SOURCE},
             [interface("hole", 'thread', {"depth": quantity(10.0, evidence=['fixture'])},
                        thread("1/4-20", 'internal', 6.35, 1.27, ['fixture']))],
             manufacturer="FIXTURE", part_number="FIXTURE-1-4-20")
unf = record("quarter-28", {'fixture': FIXTURE_SOURCE},
             [interface("screw", 'thread', {"engagement_max": quantity(8.0, evidence=['fixture'])},
                        thread("1/4-28", 'external', 6.35, 0.907, ['fixture']))],
             manufacturer="FIXTURE", part_number="FIXTURE-1-4-28")
res = compat.check(unc, "hole", unf, "screw")
check("equal major diameters do not make a thread fit: pitch and standard decide",
      res["verdict"] == 'incompatible'
      and {r["rule"] for r in res["direct"]["rules"] if r["result"] == 'incompatible'}
      >= {'thread.pitch', 'thread.standard'},
      [(r["rule"], r["result"]) for r in res["direct"]["rules"]])

print("[a stated fit passes; a missing field never does]")
post = record("post-12.7", {'fixture': FIXTURE_SOURCE},
              [interface("shaft", 'shaft', {"diameter": quantity(12.70, evidence=['fixture']),
                                            "insertion_max": quantity(20.0, evidence=['fixture'])})],
              manufacturer="FIXTURE", part_number="FIXTURE-POST")
holder = record("holder-12.7", {'fixture': FIXTURE_SOURCE},
                [interface("bore", 'smooth_bore', {"diameter": quantity(12.75, evidence=['fixture']),
                                                   "clearance": quantity(0.10, evidence=['fixture']),
                                                   "insertion_min": quantity(12.0, evidence=['fixture'])})],
                manufacturer="FIXTURE", part_number="FIXTURE-HOLDER")
res = compat.check(post, "shaft", holder, "bore")
check("a post with stated clearance and insertion is compatible",
      res["verdict"] == 'compatible' and res["missing"] == [] and res["evidence"] == ['fixture'], res)

holder_no_clearance = record("holder-unknown", {'fixture': FIXTURE_SOURCE},
                             [interface("bore", 'smooth_bore',
                                        {"diameter": quantity(12.75, evidence=['fixture']),
                                         "insertion_min": quantity(12.0, evidence=['fixture'])})],
                             manufacturer="FIXTURE", part_number="FIXTURE-HOLDER-2")
res = compat.check(post, "shaft", holder_no_clearance, "bore")
check("without a stated clearance the answer is unknown, and it names the field",
      res["verdict"] == 'unknown' and 'clearance' in res["missing"], res["missing"])

bare_holder = record("holder-bare", {'fixture': FIXTURE_SOURCE}, [interface("bore", 'smooth_bore', {})],
                     manufacturer="FIXTURE", part_number="FIXTURE-BARE")
res = compat.check(post, "shaft", bare_holder, "bore")
check("a part that states nothing is unknown, never compatible",
      res["verdict"] == 'unknown' and 'diameter' in res["missing"], res["missing"])

print("[optic seat: thickness decides, and the seat has to state what it takes]")
seat = record("lens-cell", {'fixture': FIXTURE_SOURCE},
              [interface("seat", 'optic_seat',
                         {"optic_thickness_min": quantity(2.0, evidence=['fixture']),
                          "optic_thickness_max": quantity(6.0, evidence=['fixture'])})],
              manufacturer="FIXTURE", part_number="FIXTURE-CELL")
optic = record("optic", {'fixture': FIXTURE_SOURCE}, [interface("face", 'optic_seat', {})],
               manufacturer="FIXTURE", part_number="FIXTURE-OPTIC")
check("an optic inside the stated range fits",
      compat.check(seat, "seat", optic, "face", optic_thickness_mm=3.0)["verdict"] == 'compatible')
check("a thicker optic is rejected",
      compat.check(seat, "seat", optic, "face", optic_thickness_mm=9.0)["verdict"] == 'incompatible')
check("no thickness given means unknown",
      compat.check(seat, "seat", optic, "face")["verdict"] == 'unknown')

print("[pairings schema v1 cannot decide stay unknown]")
rail = record("rail", {'fixture': FIXTURE_SOURCE}, [interface("dovetail", 'dovetail', {})],
              manufacturer="FIXTURE", part_number="FIXTURE-RAIL")
carrier = record("carrier", {'fixture': FIXTURE_SOURCE}, [interface("clamp", 'clamp', {})],
                 manufacturer="FIXTURE", part_number="FIXTURE-CARRIER")
res = compat.check(rail, "dovetail", carrier, "clamp")
check("a dovetail against a clamp is unknown, with the reason given",
      res["verdict"] == 'unknown' and 'dovetail_clamp geometry' in res["missing"], res["missing"])
res = compat.check(rail, "dovetail", post, "shaft")
check("a pairing with no rule is unknown, not incompatible",
      res["verdict"] == 'unknown' and res["direct"]["pair_kind"] is None, res["direct"]["pair_kind"])

print("[adapters: a route is offered only when every hop is compatible on its own evidence]")
metric_stud = record("m4-stud", {'fixture': FIXTURE_SOURCE},
                     [interface("stud", 'thread', {"engagement_max": quantity(4.0, evidence=['fixture'])},
                                thread("M4", 'external', 4.0, 0.7, ['fixture'], form='M'))],
                     manufacturer="FIXTURE", part_number="FIXTURE-M4-STUD")
imperial_base = record("imperial-base", {'fixture': FIXTURE_SOURCE},
                       [interface("hole", 'thread', {"depth": quantity(10.0, evidence=['fixture'])},
                                  thread("8-32", 'internal', 4.166, 0.794, ['fixture']))],
                       manufacturer="FIXTURE", part_number="FIXTURE-BASE")
adapter = record("m4-to-8-32", {'fixture': FIXTURE_SOURCE},
                 [interface("female", 'thread', {"depth": quantity(6.0, evidence=['fixture'])},
                            thread("M4", 'internal', 4.0, 0.7, ['fixture'], form='M')),
                  interface("male", 'thread', {"engagement_max": quantity(6.0, evidence=['fixture'])},
                            thread("8-32", 'external', 4.166, 0.794, ['fixture']))],
                 manufacturer="FIXTURE", part_number="FIXTURE-ADAPTER")
direct = compat.check(metric_stud, "stud", imperial_base, "hole")
check("metric into imperial is incompatible without an adapter", direct["verdict"] == 'incompatible',
      direct["verdict"])
routed = compat.check(metric_stud, "stud", imperial_base, "hole", adapters=[adapter])
check("with the adapter the verdict is adapter_required and names the part",
      routed["verdict"] == 'adapter_required' and len(routed["adapter_chain"]) == 1
      and routed["adapter_chain"][0]["part"]["part_number"] == "FIXTURE-ADAPTER", routed["adapter_chain"])

nameless = catalog.validate(dict(adapter, definition_id="unnamed-adapter",
                                 identity=dict(manufacturer=None, part_number=None, variant=None,
                                               revision=None)))
routed = compat.check(metric_stud, "stud", imperial_base, "hole", adapters=[nameless])
check("an adapter with no product identity is reported as missing identity",
      routed["verdict"] == 'adapter_required' and any('adapter identity' in m for m in routed["missing"]),
      routed["missing"])

loop_a = record("loop-a", {'fixture': FIXTURE_SOURCE},
                [interface("in", 'thread', {"depth": quantity(6.0, evidence=['fixture'])},
                           thread("M4", 'internal', 4.0, 0.7, ['fixture'], form='M')),
                 interface("out", 'thread', {"engagement_max": quantity(4.0, evidence=['fixture'])},
                           thread("M4", 'external', 4.0, 0.7, ['fixture'], form='M'))],
                manufacturer="FIXTURE", part_number="FIXTURE-LOOP-A")
loop_b = catalog.validate(dict(loop_a, definition_id="loop-b",
                               identity=dict(manufacturer="FIXTURE", part_number="FIXTURE-LOOP-B",
                                             variant=None, revision=None)))
routed = compat.check(metric_stud, "stud", imperial_base, "hole", adapters=[loop_a, loop_b], max_chain=3)
check("adapters that only convert M4 to M4 never reach an imperial hole, and the search terminates",
      routed["verdict"] == 'incompatible' and routed["adapter_chain"] == [], routed["adapter_chain"])

print("[the API reads the scene and changes nothing]")
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
scene = bpy.context.scene
scene.optics.live_enabled = False
eg.source("S", (-100, 0, 0), (1, 0, 0))
mirror = eg.mirror("M", (0, 0, 0), (1, 0, 0), (0, 1, 0))
detector = eg.detector("D", (0, 120, 0), (0, 1, 0))
catalog.attach_object(mirror, flip_mount)
catalog.attach_object(detector, long_screw)
bpy.context.view_layer.update()


def digest():
    return [(o.name, tuple(round(c, 6) for c in o.matrix_world.translation), o.mechanics.record_json)
            for o in sorted(scene.objects, key=lambda x: x.name)]


before = digest()
part = api.inspect_part("M")
ifaces = api.list_interfaces("M")
verdict = api.check_compatibility("M", "post_hole", "D", "stud")
check("inspect_part reports the stored identity",
      part.get("ok") and part["identity"]["part_number"] == "TRF90", part.get("identity"))
check("list_interfaces gives millimetres and the evidence behind them",
      ifaces.get("ok") and ifaces["interfaces"][0]["dimensions_mm"]["depth"]["value"] == 5.0
      and ifaces["interfaces"][0]["dimensions_mm"]["depth"]["evidence"] == ['flip'], ifaces.get("interfaces"))
check("check_compatibility through the API repeats the bottoming verdict",
      verdict.get("verdict") == 'incompatible', verdict.get("verdict"))
check("all three calls left the scene untouched", digest() == before)
check("an object without a record says so instead of guessing",
      "error" in api.inspect_part("S") and api.inspect_part("S").get("status") == 'legacy_unmapped',
      api.inspect_part("S"))
check("a missing interface name is an error, not a verdict",
      "error" in api.check_compatibility("M", "nope", "D", "stud"),
      api.check_compatibility("M", "nope", "D", "stud"))

print("[the MCP server exposes the same three tools]")
server = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "mcp", "optics_mcp_server.py")).read()
for name in ("inspect_part", "list_interfaces", "check_compatibility"):
    check("MCP and API both expose %s" % name, hasattr(api, name) and ("def %s(" % name) in server)
caps = api.capabilities()
read_group = caps["tool_groups"]["read / inspect (the AI's eyes -- call these to SEE the bench, never guess)"]
check("capabilities lists the compatibility tools and still reports no assembly engine",
      caps["mechanical_assembly"]["available"] is False
      and caps["mechanical_assembly"]["compatibility_read_tools"] == ["inspect_part", "list_interfaces",
                                                                      "check_compatibility"]
      and all(n in read_group for n in ("inspect_part", "list_interfaces", "check_compatibility")),
      caps["mechanical_assembly"])

print("MECHANICAL COMPATIBILITY %s (%d/%d checks)"
      % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("compatibility witnesses failed")
