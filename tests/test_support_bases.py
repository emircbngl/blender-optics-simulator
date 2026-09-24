"""Stage 05b witness (step B): which real base goes under a post holder, decided before any geometry.

support_bases is pure Python; this checks its decisions against the drawings' numbers directly, not
against its own arithmetic. Every screw has to land on a real grid hole, inside a real slot or within
the fork's real reach.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_support_bases.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import support_bases as sb

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


import json
FACTS = {f["id"]: f for f in json.loads(
    (Path(__file__).resolve().parents[1] / "docs/mechanics/product-evidence.json").read_text())["support_facts"]}
REACH = tuple(FACTS["cf125_reach"]["value"])       # from the inventory, never from support_bases itself
GRID = (0.0, 0.0, 24, 18, 25.0)                 # MB4560/M: 24 x 18 holes on a 25 mm pitch
HOLES = {(round(x, 6), round(y, 6)) for x, y in sb.holes(GRID)}


def local(plan):
    a = math.radians(plan['angle_deg'])
    cx, cy = plan['centre']
    sx, sy = plan['screw']
    return ((sx - cx) * math.cos(a) + (sy - cy) * math.sin(a),
            -(sx - cx) * math.sin(a) + (sy - cy) * math.cos(a))


def on_hole(plan):
    return (round(plan['screw'][0], 6), round(plan['screw'][1], 6)) in HOLES


print("[the numbers come from the drawings]")
check("BA2/M slot run: (50 - 2 x 9.1) / 2 = 15.9 mm either side", abs(sb.BA2['slot_half'] - (50 - 2 * 9.1) / 2) < 1e-9)
check("BA1/M slots open from 37.5 mm in to 75/2 - 20.1 = 17.4 mm", abs(sb.BA1['slot_in'] - (75 / 2 - 20.1)) < 1e-9)
def fv(fid, i=None):
    v = FACTS[fid]["value"]
    return float(v if i is None else v[i])


floor_ph = fv("ph50m_dwg_length") - fv("ph50m_dwg_bore_depth")                  # 6.8
want = {
    'BA2/M': (fv("ba2m_dwg_footprint", 2) + floor_ph,
              fv("ba2m_dwg_footprint", 2) - fv("ba2m_step_material_under_head") + fv("sh6ms10_length")),
    'BA1/M': (fv("ba1m_dwg_footprint", 2) + floor_ph,
              fv("ba1m_dwg_footprint", 2) - fv("ba1m_step_material_under_head") + fv("sh6ms10_length")),
}
# BE1/M: the stud's 45 deg end chamfer sits in TR50/M's 90 deg countersink, so the post rests at one height.
rest = (fv("be1m_dwg_disc_thickness") + fv("be1m_step_stud_proud")
        - (fv("tr50m_step_base_countersink", 0) / 2 - fv("be1m_step_stud_end_chamfer")))
want['BE1/M + CF125'] = (rest, rest)
for part, (lo, hi) in want.items():
    got = sb.seat_range(part)
    check("%s seat interval from the facts: %.3f to %.3f mm" % (part, lo, hi),
          abs(got[0] - lo) < 1e-9 and abs(got[1] - hi) < 1e-9, got)
check("BE1/M: the post rests %.3f mm above the bore floor, as the derived fact says" % (rest - fv("be1m_dwg_disc_thickness") - floor_ph),
      abs(rest - fv("be1m_dwg_disc_thickness") - floor_ph - fv("be1m_post_rest_above_ph50m_floor")) < 1e-9)
check("the slot's shank play comes from the STEP slot width: (6.731 - 6.0) / 2",
      abs(sb.SLOT_REACH - (fv("ba2m_step_slot_width") - 6.0) / 2) < 1e-9 and
      fv("ba2m_step_slot_width") == fv("ba1m_step_slot_width") == fv("cf125_step_slot_width"), sb.SLOT_REACH)

print("[on a grid line: BA2/M, screwed down through a slot]")
one = sb.choose({'a': (250.0, 212.5 - 12.5)}, GRID)['a']
u, v = local(one)
check("a holder on a grid column gets a BA2/M", one['part'] == 'BA2/M' and not one['conflict'], one['part'])
check("its screw is in a slot (within the shank's play of the centreline), inside its run, on a real hole",
      abs(abs(u) - 25.0) <= sb.SLOT_REACH + 1e-9 and abs(v) <= 15.9 + 1e-9 and on_hole(one), (u, v, one['screw']))
check("fastened with the kit's M6 x 16 + washer", one['fastener'] == 'M6 x 16 mm cap screw + M6 washer')

# Every candidate, both orientations, every counterbore: the holder has to stand ON a counterbore.
wrong = []
for plan in sb._ba2_plans(250.0, 200.0, GRID):
    hu, hv = sb.to_local(plan['centre'], math.radians(plan['angle_deg']), 250.0, 200.0)
    if abs(hu) > 1e-9 or abs(hv - plan['holder_offset']) > 1e-9:
        wrong.append((plan['angle_deg'], plan['holder_offset'], round(hu, 3), round(hv, 3)))
check("in every BA2/M candidate the holder stands on the counterbore the plan names", not wrong, wrong)
turned = [p for p in sb._ba2_plans(250.0, 200.0, GRID) if p['angle_deg'] == 90.0 and p['holder_offset'] != 0.0]
check("including a base turned 90 degrees on an off-centre counterbore", len(turned) > 0, len(turned))

print("[off the grid: BE1/M + CF125]")
off = sb.choose({'a': (263.0, 208.0)}, GRID)['a']
r = math.hypot(off['screw'][0] - 263.0, off['screw'][1] - 208.0)
check("a holder on no grid line gets a pedestal and a clamping fork", off['part'] == 'BE1/M + CF125', off['part'])
check("the fork's screw is within its %.1f-%.1f mm reach, on a real hole" % REACH,
      REACH[0] - 1e-9 <= r <= REACH[1] + 1e-9 and on_hole(off), r)
check("support_bases uses the inventory's fork reach", tuple(sb.CF125['reach']) == REACH, sb.CF125['reach'])
check("fastened with the kit's M6 x 12 + washer", off['fastener'] == 'M6 x 12 mm cap screw + M6 washer')
# The inventory's derived claim, checked numerically: anywhere on the board, the fork reaches a hole.
missed = []
for i in range(68):
    for j in range(68):
        x, y = 200.0 + i * 25.0 / 67, 200.0 + j * 25.0 / 67
        if not next(iter(sb._fork_plans(x, y, GRID)), None):
            missed.append((x, y))
check("the fork reaches a hole from every one of 4624 points across a grid cell", not missed, missed[:3])

print("[BA1/M, where BA2/M's 50 mm width would hit a neighbour]")
# Two holders on the same grid row, 50 mm apart along it: BA2/M turned across the row is 50 mm wide
# in the other direction and fits; so crowd them in the row's direction as well.
crowd = {'a': (250.0, 200.0), 'b': (250.0, 237.0), 'c': (250.0, 163.0)}
plans = sb.choose(crowd, GRID)
kinds = sorted(p['part'] for p in plans.values())
check("in a column of holders 37 mm apart, the narrow BA1/M is used", 'BA1/M' in kinds, kinds)
ba1 = next(p for p in plans.values() if p['part'] == 'BA1/M')
u, v = local(ba1)
check("its screw is in the slot (within the shank's play), 17.4-37.5 mm from the centre, on a real hole",
      abs(v) <= sb.SLOT_REACH + 1e-9 and 17.4 - 1e-9 <= abs(u) <= 37.5 + 1e-9 and on_hole(ba1), (u, v))
check("no two chosen footprints overlap",
      not any(sb.overlap(plans[a]['footprint'], plans[b]['footprint'])
              for a in plans for b in plans if a < b))

print("[when nothing fits, it says so]")
tight = {'%d' % k: (250.0 + 9.0 * (k % 3), 200.0 + 9.0 * (k // 3)) for k in range(9)}
tplans = sb.choose(tight, GRID)
check("nine holders 9 mm apart cannot all get a real base, and the plan reports the conflict",
      any(p['conflict'] for p in tplans.values()), sum(p['conflict'] for p in tplans.values()))

print("[the overlap test itself]")
sq = sb._rect(0, 0, 10, 10, 0)
check("touching squares are not overlapping", not sb.overlap(sq, sb._rect(10, 0, 10, 10, 0)))
check("squares 1 mm into each other are", sb.overlap(sq, sb._rect(9, 0, 10, 10, 0)))
check("a rotated square that clears the corner is not",
      not sb.overlap(sq, sb._rect(12.2, 12.2, 10, 10, math.pi / 4)))

print("SUPPORT BASES %s (%d/%d checks)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("support base witnesses failed")
