"""Stage 05b witness (step D): the real bases under every post holder, measured against the drawings.

Written against the step-C contract BEFORE the geometry exists, so it cannot be fitted to it:

* Every holder BENCH_Holder_<T> stands on exactly one base: a slotted plate BENCH_Base_<T> (BA2/M or
  BA1/M), or a pedestal BENCH_BasePedestal_<T> with its clamping fork BENCH_BaseFork_<T> (BE1/M +
  CF125). The table screw is BENCH_BaseScrew_<T> (+ BENCH_BaseWasher_<T>). The base object carries
  base_part, base_screw_xy, base_seat_mm, base_seat_range_mm, base_angle_deg and base_conflict.
* The post's seat is an interval [floor, screw tip] on a slotted base (the screw's point is unsourced)
  and one point on BE1/M (stud chamfer in TR50/M's countersink, both sourced). The post is drawn at the
  high end.
* Expected values come from docs/mechanics/product-evidence.json (BA2/M 19227 A, BA1/M 19225 A,
  BE1/M 6790 C, CF125 6535 E, PH50/M 23132 B) -- never from optomech or support_bases constants.
* Threshold 0.05 mm, half the drawings' 0.1 mm resolution. Outer surfaces at the circumradius (vertex
  extents). A slot is measured as a stadium: its along-extent minus its across-extent is the distance
  between its end centres whatever its width, so no undimensioned width is ever assumed.
* Not asserted, because no drawing dimensions it: slot widths, counterbore diameters and depths,
  screw heads, washers, the CF125 undercut depth, and the fork's outline inside its 73.8 x 36.3 box.

Every example is built, traced, dressed and traced again: dressing must leave the trace byte-identical.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_support_base_geometry.py
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
from optical_alignment_sim import examples_builtin, optomech, scan

try:                                    # step B; absent on main, where its checks must FAIL, not crash
    from optical_alignment_sim import support_bases
except ImportError:
    support_bases = None

THRESHOLD_MM = 0.05
EPS = 1e-6

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


FACTS = {f["id"]: f for f in
         json.loads((ROOT / "docs/mechanics/product-evidence.json").read_text())["support_facts"]}


def fact(identifier, index=None):
    if identifier not in FACTS:
        return float("nan")             # a missing fact makes every comparison against it FAIL
    value = FACTS[identifier]["value"]
    return float(value[index] if index is not None else value)


BA2_L, BA2_W, BA2_T = (fact("ba2m_dwg_footprint", i) for i in range(3))
BA1_L, BA1_W, BA1_T = (fact("ba1m_dwg_footprint", i) for i in range(3))
BA2_SLOT_PITCH = fact("ba2m_dwg_slot_pitch")
BA2_SLOT_TRAVEL = fact("ba2m_dwg_slot_travel")
BA2_SLOT_EDGE = fact("ba2m_dwg_slot_end_from_edge")
BA2_CB_PITCH = fact("ba2m_dwg_counterbore_pitch")
BA2_CB_COLUMN = fact("ba2m_dwg_counterbore_column")
BA2_CB_COUNT = fact("ba2m_dwg_counterbores")
BA1_SLOT_FROM_END = fact("ba1m_dwg_slot_depth")
BE1_DISC = fact("be1m_dwg_disc")
BE1_DISC_T = fact("be1m_dwg_disc_thickness")
BE1_OVERALL = fact("be1m_dwg_overall")
CF_L, CF_W = fact("cf125_dwg_outline", 0), fact("cf125_dwg_outline", 1)
CF_JAW = fact("cf125_dwg_jaw")
CF_UNDERCUT = fact("cf125_dwg_undercut")
CF_TIP = fact("cf125_dwg_jaw_offset")
CF_SLOT_LEN = fact("cf125_dwg_slot_length")
CF_SLOT_TO_BACK = fact("cf125_dwg_slot_near_to_back")     # near slot end centre -> the fork's back end
PH_FLOOR = fact("ph50m_dwg_length") - fact("ph50m_dwg_bore_depth")
SCREW_L = fact("sh6ms10_length")
M6_MAJOR = 6.0                                   # ISO 261: "M6" names a 6 mm nominal major diameter
SLOT_W = {"BA2/M": fact("ba2m_step_slot_width"), "BA1/M": fact("ba1m_step_slot_width"),
          "CF125": fact("cf125_step_slot_width")}
# Where the post comes to rest, above the board top, as [lo, hi]. On a slotted base the kit's M6 x 10
# stands through PH50/M's through-tapped floor into the bore; its point is unsourced, so the post rests
# somewhere between the floor (lo) and the screw's tip (hi). BE1/M's stud chamfer and TR50/M's
# countersink are both sourced, so there it is one point: cone in cone.
SEAT = {
    "BA2/M": (BA2_T + PH_FLOOR, BA2_T - fact("ba2m_step_material_under_head") + SCREW_L),
    "BA1/M": (BA1_T + PH_FLOOR, BA1_T - fact("ba1m_step_material_under_head") + SCREW_L),
}
BE1_REST = (BE1_DISC_T + fact("be1m_step_stud_proud")
            - (fact("tr50m_step_base_countersink", 0) / 2.0 - fact("be1m_step_stud_end_chamfer")))
SEAT["BE1/M + CF125"] = (BE1_REST, BE1_REST)
BA2_SLOT_HALF = BA2_SLOT_TRAVEL / 2.0
BA1_SLOT_IN = BA1_L / 2.0 - BA1_SLOT_FROM_END
# Along the fork from its tips: jaw centre at 3.8, back end at 73.8, near slot end 43.2 before the back end.
CF_SLOT_NEAR = CF_L - CF_SLOT_TO_BACK - CF_TIP            # from the jaw centre: 26.8
CF_SLOT_FAR = CF_SLOT_NEAR + CF_SLOT_LEN                   # 58.3
# Across a slot the screw's shank may sit anywhere it still fits: (6.731 - 6.0) / 2 = 0.3655 mm either
# side of the centreline. Along it, anywhere between the end centres (the slot's end radius 3.37 > 3.0).
PLAY = {part: (w - M6_MAJOR) / 2.0 for part, w in SLOT_W.items()}

print("[the drawings agree with each other]")
check("BA2/M: 9.1 + 31.8 + 9.1 mm of slot and margins span the 50 mm plate",
      abs(2 * BA2_SLOT_EDGE + BA2_SLOT_TRAVEL - BA2_W) <= THRESHOLD_MM,
      "%.2f vs %.2f" % (2 * BA2_SLOT_EDGE + BA2_SLOT_TRAVEL, BA2_W))
check("BA2/M: the counterbore column is the plate's centreline (37.5 of 75)",
      abs(BA2_CB_COLUMN - BA2_L / 2.0) <= THRESHOLD_MM, (BA2_CB_COLUMN, BA2_L))
check("BE1/M's Ø31.8 disc passes CF125's Ø32.5 undercut", BE1_DISC < CF_UNDERCUT, (BE1_DISC, CF_UNDERCUT))
check("CF125: from its tips 3.8 mm behind the jaw centre, the 73.8 mm fork runs past the far slot end",
      CF_L - CF_TIP > CF_SLOT_FAR, (CF_L - CF_TIP, CF_SLOT_FAR))
# Width-free: a slot whose near end CENTRE lies inside the jaw's radius opens into the jaw even at zero
# width. This caught the first reading of 43.2 as measured from the jaw centre (near end 11.7 < 13.0).
check("CF125: the slot's near end centre (73.8 - 43.2 - 3.8 mm from the jaw centre) lies outside the Ø32.5 undercut",
      CF_SLOT_NEAR > CF_UNDERCUT / 2.0,
      "near end centre %.2f mm, jaw radius %.2f mm, undercut radius %.2f mm"
      % (CF_SLOT_NEAR, CF_JAW / 2.0, CF_UNDERCUT / 2.0))


for part, derived in (("BA2/M", "sh6ms10_into_ph50m_on_ba2m"), ("BA1/M", "sh6ms10_into_ph50m_on_ba1m")):
    lo, hi = SEAT[part]
    check("%s: the seat interval's width is the screw's recorded intrusion into the bore" % part,
          abs((hi - lo) - fact(derived)) <= 1e-6, "%.4f vs %s %.4f" % (hi - lo, derived, fact(derived)))
check("BE1/M: the post's rest above PH50/M's floor is the recorded one",
      abs(BE1_REST - (BE1_DISC_T + PH_FLOOR) - fact("be1m_post_rest_above_ph50m_floor")) <= 1e-6,
      "%.4f vs %.4f" % (BE1_REST - (BE1_DISC_T + PH_FLOOR), fact("be1m_post_rest_above_ph50m_floor")))
reach_fact = [fact("cf125_reach", 0), fact("cf125_reach", 1)]
check("CF125: the recorded reach %s is the drawing's slot, 26.8-58.3 mm from the jaw centre" % reach_fact,
      abs(reach_fact[0] - CF_SLOT_NEAR) <= THRESHOLD_MM and abs(reach_fact[1] - CF_SLOT_FAR) <= THRESHOLD_MM,
      "drawing gives %.2f-%.2f" % (CF_SLOT_NEAR, CF_SLOT_FAR))


# ---- helpers -------------------------------------------------------------------------------------
def world_verts(ob):
    mw = ob.matrix_world if ob is not None else None
    return [mw @ v.co for v in ob.data.vertices] if ob is not None and ob.type == 'MESH' else []


def to_local(points, cx, cy, angle_deg):
    """(u, v, z): u along angle_deg (a plate's length, a fork's axis toward its screw), v across it."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return [((p.x - cx) * c + (p.y - cy) * s, -(p.x - cx) * s + (p.y - cy) * c, p.z) for p in points]


def box_frame(points, angle_deg):
    """Centre and extents of the points in a frame turned by angle_deg (a plate's envelope)."""
    local = to_local(points, 0.0, 0.0, angle_deg)
    us, vs = [p[0] for p in local], [p[1] for p in local]
    cu, cv = (max(us) + min(us)) / 2.0, (max(vs) + min(vs)) / 2.0
    a = math.radians(angle_deg)
    return (cu * math.cos(a) - cv * math.sin(a), cu * math.sin(a) + cv * math.cos(a),
            max(us) - min(us), max(vs) - min(vs))


def stadium(pairs):
    """A slot as a stadium of (along, across) points: its centreline and end centres, width-free.

    The straight walls give the width 2R exactly. Every end-arc vertex lies on a circle of radius R about
    its end centre, so each vertex gives that centre exactly (a wall vertex gives a value on the inner
    side, never past it). Taking the vertex extent minus R instead would fall short by R(1 - cos(pi/n))
    whenever the arc polygon has no vertex on the axis."""
    al, ac = [p[0] for p in pairs], [p[1] for p in pairs]
    line = (max(ac) + min(ac)) / 2.0
    r = (max(ac) - min(ac)) / 2.0
    off = [math.sqrt(max(r * r - (c - line) ** 2, 0.0)) for c in ac]
    return {"line": line, "width": 2.0 * r, "near": min(a + o for a, o in zip(al, off)),
            "far": max(a - o for a, o in zip(al, off))}


def wall_level(points, across):
    """The slot's own wall: of the z levels its vertices sit on, the one where the slot is narrowest
    across. A chamfer or counterbore only ever widens a slot at a face, so this skips both whether a
    mesh has them or not -- and neither is dimensioned, so neither may reach a measurement."""
    levels = {}
    for p in points:
        levels.setdefault(round(p[2], 3), []).append(p)
    return min(levels.values(), key=lambda q: max(x[across] for x in q) - min(x[across] for x in q)) if levels else []


def canonical(value, depth=0):
    """A deterministic text form of a trace: objects by name, numbers by repr, no memory addresses."""
    if depth > 6:
        return "..."
    if isinstance(value, bpy.types.ID):
        return "<%s>" % value.name
    if isinstance(value, (bool, int, float, str)) or value is None:
        return repr(value)
    if isinstance(value, dict):
        return "{" + ",".join("%s:%s" % (k, canonical(value[k], depth + 1)) for k in sorted(value, key=str)) + "}"
    if hasattr(value, "__len__") and hasattr(value, "__getitem__"):
        try:
            return "[" + ",".join(canonical(x, depth + 1) for x in value) + "]"
        except TypeError:
            pass
    slots = getattr(type(value), "__slots__", None) or getattr(value, "__dict__", {}).keys()
    return type(value).__name__ + "(" + ",".join(
        "%s=%s" % (s, canonical(getattr(value, s, None), depth + 1)) for s in slots) + ")"


def trace_text(scene):
    return canonical(list(scan._trace(scene)))


# ---- every example: trace, dress, trace, measure -------------------------------------------------
scene = bpy.context.scene
P = optomech.BENCH_PREFIX
failures = {}                                    # assertion -> offending "example/tag: detail"
measured = {}                                    # assertion -> how many holders it actually looked at


def expect(assertion, ok, where, detail=""):
    measured[assertion] = measured.get(assertion, 0) + 1
    if not ok:
        failures.setdefault(assertion, []).append("%s/%s: %s" % (where[0], where[1], detail))


def near(assertion, value, expected, where):
    expect(assertion, abs(value - expected) <= THRESHOLD_MM, where,
           "%.3f vs drawing %.3f (delta %+.3f)" % (value, expected, value - expected))


trace_changed, holders_total, bases_by_part = [], 0, {}

for kind in examples_builtin.EXAMPLES:
    examples_builtin.build(kind, bpy.context)
    scene.optics.live_enabled = False
    bpy.context.view_layer.update()
    before = trace_text(scene)
    optomech.dress(scene)
    bpy.context.view_layer.update()
    if trace_text(scene) != before:
        trace_changed.append(kind)
    info = optomech.grid_info(scene)
    if info is None:
        continue
    board = info["board_top_z_mm"]
    pitch = info["pitch_mm"]
    x0, y0 = info["origin"]
    grid = (x0, y0, info["cols"], info["rows"], pitch)
    holes = {(round(x0 + i * pitch, 3), round(y0 + j * pitch, 3))
             for i in range(info["cols"]) for j in range(info["rows"])}

    holders = {o.name[len(P + "Holder_"):]: o for o in scene.objects if o.name.startswith(P + "Holder_")}
    holders_total += len(holders)
    axes = {t: (h.matrix_world.translation.x, h.matrix_world.translation.y) for t, h in holders.items()}
    # The exact inputs dress() planned from, obstacles included (rails and periscope parts built first).
    # Holder axes and grid are also checked against what this test measures, so the recorded inputs
    # cannot drift from the scene unnoticed. Objects hold float32 coordinates: at a few hundred mm that is
    # ~3e-5 mm of rounding, so the comparison allows 1e-3 mm -- still 50x under the drawing threshold.
    inputs = getattr(optomech, "base_plan_inputs", lambda sc: None)(scene)
    plans = {}
    if support_bases is not None and inputs is not None:
        plans = support_bases.choose(inputs["holders"], inputs["grid"], obstacles=inputs["obstacles"])
        expect("the recorded plan inputs are this scene's holders and grid",
               set(inputs["holders"]) == set(axes)
               and all(math.hypot(inputs["holders"][t][0] - axes[t][0], inputs["holders"][t][1] - axes[t][1])
                       <= 1e-3 for t in axes)
               and all(abs(float(u) - float(v)) <= 1e-3 for u, v in zip(inputs["grid"], grid)),
               (kind, "*"), "recorded %s / %s vs scene %s" % (sorted(inputs["holders"])[:3], inputs["grid"], grid))

    strays = [o.name for o in scene.objects
              if o.name.startswith((P + "Base_", P + "BasePedestal_"))
              and o.name.split("_", 2)[-1] not in holders]
    expect("no base without a holder", not strays, (kind, "*"), strays)

    for tag, holder in sorted(holders.items()):
        where = (kind, tag)
        plate = scene.objects.get(P + "Base_" + tag)
        pedestal = scene.objects.get(P + "BasePedestal_" + tag)
        fork = scene.objects.get(P + "BaseFork_" + tag)
        screw = scene.objects.get(P + "BaseScrew_" + tag)
        washer = scene.objects.get(P + "BaseWasher_" + tag)
        # The post standing in this holder, found by its axis: cage and tube groups name theirs
        # BENCH_CagePost_<n> / BENCH_TubePost_<n>, not BENCH_Post_<T>.
        post = next((o for o in scene.objects if o.name.startswith(P) and "Post" in o.name
                     and o.type == 'MESH' and o.data.vertices
                     and math.hypot(*(((max(v.x for v in world_verts(o)) + min(v.x for v in world_verts(o))) / 2
                                       - holder.matrix_world.translation.x,
                                       (max(v.y for v in world_verts(o)) + min(v.y for v in world_verts(o))) / 2
                                       - holder.matrix_world.translation.y))) <= THRESHOLD_MM), None)
        base = plate or pedestal
        expect("each holder has exactly one base", (plate is None) != (pedestal is None), where,
               "plate %s, pedestal %s" % (plate is not None, pedestal is not None))
        if base is None:
            continue
        part = base.get("base_part")
        bases_by_part[part] = bases_by_part.get(part, 0) + 1
        expect("base_part is one of BA2/M, BA1/M, BE1/M + CF125",
               part in ("BA2/M", "BA1/M", "BE1/M + CF125"), where, part)
        expect("a pedestal comes with a fork, a plate without one",
               (pedestal is not None) == (fork is not None) == (part == "BE1/M + CF125"), where,
               "pedestal %s, fork %s, part %s" % (pedestal is not None, fork is not None, part))
        try:
            sx, sy = (float(c) for c in base.get("base_screw_xy"))
            angle = float(base.get("base_angle_deg"))
            seat = float(base.get("base_seat_mm"))
            seat_lo, seat_hi = (float(c) for c in base.get("base_seat_range_mm"))
            conflict = bool(base["base_conflict"])
        except (TypeError, KeyError, ValueError) as exc:
            expect("the base carries base_screw_xy, base_angle_deg, base_seat_mm, base_seat_range_mm, base_conflict", False,
                   where, exc)
            continue
        ax, ay = axes[tag]

        # -- the decision is step B's; the geometry must not make a second one
        plan = plans.get(tag)
        expect("base_conflict only where support_bases.choose reports it",
               plan is not None and conflict == bool(plan["conflict"]), where,
               "prop %s, choose %s" % (conflict, None if plan is None else plan["conflict"]))
        expect("base_part and base_screw_xy are the ones support_bases.choose picked",
               plan is not None and plan.get("part") == part and plan.get("screw") is not None
               and math.hypot(plan["screw"][0] - sx, plan["screw"][1] - sy) <= EPS, where,
               "prop %s %s, choose %s" % (part, (sx, sy), None if plan is None else
                                          (plan.get("part"), plan.get("screw"))))

        # -- the table screw: on a real hole, its axis there
        expect("base_screw_xy is a hole of the board grid", (round(sx, 3), round(sy, 3)) in holes, where,
               (sx, sy))
        scv = world_verts(screw)
        expect("the table screw and its washer exist", bool(scv) and washer is not None, where,
               "screw %s, washer %s" % (bool(scv), washer is not None))
        if scv:
            scx = (max(v.x for v in scv) + min(v.x for v in scv)) / 2.0
            scy = (max(v.y for v in scv) + min(v.y for v in scv)) / 2.0
            near("the table screw's axis is at base_screw_xy", math.hypot(scx - sx, scy - sy), 0.0, where)

        # -- heights above the board top
        hv = world_verts(holder)
        pv = world_verts(post)
        lo, hi = SEAT.get(part, (float("nan"), float("nan")))
        near("base_seat_range_mm is the drawings' interval (low end)", seat_lo, lo, where)
        near("base_seat_range_mm is the drawings' interval (high end)", seat_hi, hi, where)
        expect("base_seat_mm is the range's high end", abs(seat - seat_hi) <= EPS, where, (seat, seat_hi))
        near("base_seat_mm is the post's seat from the drawings", seat, hi, where)
        expect("the post exists", bool(pv), where)
        if pv:
            bottom_post = min(v.z for v in pv) - board
            expect("the post bottom lies within base_seat_range_mm",
                   seat_lo - THRESHOLD_MM <= bottom_post <= seat_hi + THRESHOLD_MM, where,
                   "%.3f in [%.3f, %.3f]" % (bottom_post, seat_lo, seat_hi))
            near("the post bottom stands at the seat above the board", bottom_post, hi, where)

        if plate is not None:
            bv = world_verts(plate)
            thickness = BA2_T if part == "BA2/M" else BA1_T
            near("the plate sits on the board", min(v.z for v in bv) - board, 0.0, where)
            near("the plate top is 10 mm above the board", max(v.z for v in bv) - board, thickness, where)
            near("the holder bottom sits on the plate top", min(v.z for v in hv) - board, thickness, where)
            cx, cy, length, width = box_frame(bv, angle)
            local = to_local(bv, cx, cy, angle)
            su, sv = to_local([Vector((sx, sy, 0.0))], cx, cy, angle)[0][:2]
            hu, hv_ = to_local([holder.matrix_world.translation], cx, cy, angle)[0][:2]
            margin = 1.5            # selector only: clear of an edge bevel; every slot starts 5+ mm inside
            inside = [p for p in local if abs(p[0]) < length / 2 - margin and abs(p[1]) < width / 2 - margin]
            if part == "BA2/M":
                near("BA2/M length (envelope)", length, BA2_L, where)
                near("BA2/M width (envelope)", width, BA2_W, where)
                # the slots run ACROSS the length (along v), one each side of the counterbore column
                sides = [[(p[1], p[0]) for p in wall_level([p for p in inside if s * p[0] > BA2_CB_PITCH], 0)]
                         for s in (-1, 1)]
                expect("BA2/M has two slots", all(sides), where)
                if all(sides):
                    slots = [stadium(pts) for pts in sides]
                    near("BA2/M slot centrelines 50.0 apart", slots[1]["line"] - slots[0]["line"],
                         BA2_SLOT_PITCH, where)
                    for st in slots:
                        near("BA2/M slot width 6.731 at the wall", st["width"], SLOT_W["BA2/M"], where)
                        near("BA2/M slot end centres 31.8 apart (width-free)", st["far"] - st["near"],
                             BA2_SLOT_TRAVEL, where)
                        near("BA2/M slot end centres 9.1 in from the edges", st["near"] + width / 2,
                             BA2_SLOT_EDGE, where)
                        near("BA2/M slot end centres 9.1 in from the edges", width / 2 - st["far"],
                             BA2_SLOT_EDGE, where)
                expect("BA2/M screw's shank fits a slot (|u| = 25 +- 0.37, |v| <= 15.9)",
                       abs(abs(su) - BA2_SLOT_PITCH / 2) <= PLAY["BA2/M"] + EPS
                       and abs(sv) <= BA2_SLOT_HALF + THRESHOLD_MM, where, "u %.3f, v %.3f" % (su, sv))
                bores = [p for p in inside if abs(p[0]) < BA2_CB_PITCH]
                if bores:
                    r = (max(p[0] for p in bores) - min(p[0] for p in bores)) / 2.0
                    uc = (max(p[0] for p in bores) + min(p[0] for p in bores)) / 2.0
                    vs = [p[1] for p in bores]
                    near("BA2/M counterbores on the centreline (37.5 from the edge)", uc + length / 2,
                         BA2_CB_COLUMN, where)
                    near("BA2/M counterbore centres 12.5 apart (three equal bores, width-free)",
                         ((max(vs) - min(vs)) - 2 * r) / (BA2_CB_COUNT - 1), BA2_CB_PITCH, where)
                    wide = sorted(p[1] for p in bores if abs(p[0] - uc) > 0.8 * r)
                    groups = (1 + sum(1 for a, b in zip(wide, wide[1:]) if b - a > r)) if wide else 0
                    expect("BA2/M has three counterbores", groups == int(BA2_CB_COUNT), where, groups)
                    mid = (max(vs) + min(vs)) / 2.0
                    near("the holder axis is over a counterbore (where its cap screw goes)",
                         math.hypot(hu - uc, min(abs(hv_ - (mid + k * BA2_CB_PITCH)) for k in (-1, 0, 1))),
                         0.0, where)
                else:
                    expect("BA2/M has three counterbores", False, where, "no counterbore geometry")
            elif part == "BA1/M":
                near("BA1/M length (envelope)", length, BA1_L, where)
                near("BA1/M width (envelope)", width, BA1_W, where)
                # open-ended slots along u: only the inner end is a stadium end; its centre is width-free.
                # 7 mm keeps the centre hole's counterbore out (selector, not a dimension).
                ends = []
                for s in (-1, 1):
                    # Clear of the open mouth at the plate's end, where the edge bevel widens it.
                    pts = wall_level([p for p in local if s * p[0] > 7.0 and abs(p[0]) < length / 2 - margin
                                      and abs(p[1]) < width / 2 - margin], 1)
                    if pts:
                        st = stadium([(s * p[0], p[1]) for p in pts])
                        ends.append((st["near"], st["line"]))
                        near("BA1/M slot width 6.731 at the wall", st["width"], SLOT_W["BA1/M"], where)
                expect("BA1/M has two slots", len(ends) == 2, where, len(ends))
                for inner, line in ends:
                    near("BA1/M slot end centre 20.1 from its end", BA1_L / 2 - inner, BA1_SLOT_FROM_END, where)
                    near("BA1/M slot on the centreline", line, 0.0, where)
                expect("BA1/M screw's shank fits a slot (|v| <= 0.37, 17.4 <= |u| <= 37.5)",
                       abs(sv) <= PLAY["BA1/M"] + EPS and BA1_SLOT_IN - THRESHOLD_MM <= abs(su) <= BA1_L / 2 + EPS,
                       where, "u %.3f, v %.3f" % (su, sv))
                near("the holder axis is over BA1/M's centre hole", math.hypot(hu, hv_), 0.0, where)
        else:
            dv = world_verts(pedestal)
            near("the pedestal sits on the board", min(v.z for v in dv) - board, 0.0, where)
            radial = [math.hypot(v.x - ax, v.y - ay) for v in dv]
            rmax = max(radial)
            near("BE1/M disc diameter (envelope), centred on the holder axis", 2 * rmax, BE1_DISC, where)
            near("BE1/M disc top 4.7 mm above the board",
                 max(v.z for v, r in zip(dv, radial) if r > rmax - 0.5) - board, BE1_DISC_T, where)
            near("BE1/M stud end 12.3 mm above the board", max(v.z for v in dv) - board, BE1_OVERALL, where)
            near("the holder bottom sits on the disc top", min(v.z for v in hv) - board, BE1_DISC_T, where)
            fv = world_verts(fork)
            if fv:
                local = to_local(fv, ax, ay, angle)          # u from the jaw centre toward the screw
                us, vs = [p[0] for p in local], [p[1] for p in local]
                near("CF125 length (envelope)", max(us) - min(us), CF_L, where)
                near("CF125 width (envelope)", max(vs) - min(vs), CF_W, where)
                near("CF125 tips 3.8 mm behind the jaw centre", -min(us), CF_TIP, where)
                fr = [math.hypot(p[0], p[1]) for p in local]
                near("CF125 jaw Ø26.0 about the pedestal axis", 2 * min(fr), CF_JAW, where)
                # Ahead of the jaw centre only: behind it the jaw's straight sides run to the tips at
                # (-3.8, +-13.0), radius 13.54, which is neither the jaw nor the undercut.
                undercut = [r for r, p in zip(fr, local) if p[0] > 0.5 and CF_JAW / 2 + 0.5 < r < CF_UNDERCUT / 2 + 1.5]
                if undercut:
                    near("CF125 undercut Ø32.5 about the pedestal axis", 2 * min(undercut), CF_UNDERCUT, where)
                else:
                    expect("CF125 undercut Ø32.5 about the pedestal axis", False, where, "no undercut geometry")
                edge = 1.5          # selector only: clear of the fork's outer edge bevel
                slot = [(p[0], p[1]) for p in wall_level(
                    [p for p in local if CF_UNDERCUT / 2 + 0.5 < p[0] < max(us) - edge
                     and abs(p[1]) < CF_W / 2 - edge], 1)]
                if slot:
                    st = stadium(slot)
                    near("CF125 slot width 6.731 at the wall", st["width"], SLOT_W["CF125"], where)
                    near("CF125 far slot end centre 58.3 from the jaw centre", st["far"], CF_SLOT_FAR, where)
                    near("CF125 slot end centres 31.5 apart (width-free)", st["far"] - st["near"], CF_SLOT_LEN, where)
                    near("CF125 slot on the fork's centreline", st["line"], 0.0, where)
                else:
                    expect("CF125 far slot end centre 58.3 from the jaw centre", False, where, "no slot geometry")
            else:
                expect("CF125 length (envelope)", False, where, "no fork")
            reach = math.hypot(sx - ax, sy - ay)
            expect("the fork's screw is within 26.8-58.3 mm of the pedestal",
                   CF_SLOT_NEAR - THRESHOLD_MM <= reach <= CF_SLOT_FAR + THRESHOLD_MM, where, "%.3f" % reach)
            su, sv = to_local([Vector((sx, sy, 0.0))], ax, ay, angle)[0][:2]
            expect("the fork's slot holds its screw (base_angle_deg, shank play 0.37)",
                   abs(sv) <= PLAY["CF125"] + EPS and su > 0, where,
                   "u %.3f, v %.3f" % (su, sv))

# ---- verdicts: one line per assertion ------------------------------------------------------------
print("[%d examples, %d holders, bases %s]" % (len(examples_builtin.EXAMPLES), holders_total, bases_by_part))
check("dressing leaves every example's trace byte-identical", not trace_changed, trace_changed)
check("the examples put holders on the bench to measure", holders_total > 0, holders_total)
# An assertion that looked at nothing did not pass. These must each have measured something: the ones
# every holder gets, and those for the two parts step B chooses on the examples (BA2/M, BE1/M + CF125).
# BA1/M's are checked wherever BA1/M is used.
REQUIRED = [
    "no base without a holder", "each holder has exactly one base",
    "the recorded plan inputs are this scene's holders and grid",
    "base_conflict only where support_bases.choose reports it",
    "base_part and base_screw_xy are the ones support_bases.choose picked",
    "base_screw_xy is a hole of the board grid", "the table screw's axis is at base_screw_xy",
    "base_seat_range_mm is the drawings' interval (low end)", "base_seat_range_mm is the drawings' interval (high end)",
    "base_seat_mm is the range's high end", "base_seat_mm is the post's seat from the drawings",
    "the post bottom lies within base_seat_range_mm", "the post bottom stands at the seat above the board",
    "BA2/M slot width 6.731 at the wall", "CF125 slot width 6.731 at the wall",
    "the plate sits on the board", "the plate top is 10 mm above the board",
    "the holder bottom sits on the plate top",
    "BA2/M length (envelope)", "BA2/M width (envelope)", "BA2/M slot centrelines 50.0 apart",
    "BA2/M slot end centres 31.8 apart (width-free)", "BA2/M slot end centres 9.1 in from the edges",
    "BA2/M screw's shank fits a slot (|u| = 25 +- 0.37, |v| <= 15.9)",
    "BA2/M counterbores on the centreline (37.5 from the edge)",
    "BA2/M counterbore centres 12.5 apart (three equal bores, width-free)", "BA2/M has three counterbores",
    "the holder axis is over a counterbore (where its cap screw goes)",
    "the pedestal sits on the board", "BE1/M disc diameter (envelope), centred on the holder axis",
    "BE1/M disc top 4.7 mm above the board", "BE1/M stud end 12.3 mm above the board",
    "the holder bottom sits on the disc top", "CF125 length (envelope)", "CF125 width (envelope)",
    "CF125 tips 3.8 mm behind the jaw centre", "CF125 jaw Ø26.0 about the pedestal axis",
    "CF125 undercut Ø32.5 about the pedestal axis", "CF125 far slot end centre 58.3 from the jaw centre",
    "CF125 slot end centres 31.5 apart (width-free)", "CF125 slot on the fork's centreline",
    "the fork's screw is within 26.8-58.3 mm of the pedestal", "the fork's slot holds its screw (base_angle_deg, shank play 0.37)",
]
for assertion in REQUIRED + sorted(set(measured) - set(REQUIRED)):
    bad = failures.get(assertion, [])
    seen = measured.get(assertion, 0)
    check(assertion, seen > 0 and not bad,
          ("%d measured" % seen) + ("" if not bad else ", %d off: %s" % (len(bad), "; ".join(bad[:3]))))

print("SUPPORT BASE GEOMETRY %s (%d/%d checks, threshold %.2f mm)"
      % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks), THRESHOLD_MM), flush=True)
if not all(checks):
    raise AssertionError("support bases disagree with the drawings")
