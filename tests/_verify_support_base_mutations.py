"""Wrong-value pass for tests/test_support_base_geometry.py: every assertion must be able to FAIL.

A witness that only ever passes proves nothing. This wraps optomech.dress so that, right after the real
dressing, one deliberate defect is planted (a plate moved 0.1 mm, a slot stretched 1 %, a prop flipped,
a part deleted ...), then runs the witness on hybrid_system -- the one example holding all three base
kinds (BA2/M, BA1/M, BE1/M + CF125), a rail obstacle and a cage post -- and requires the assertion the
defect targets to FAIL. The unmutated run must PASS every check first.

Run: blender -b --factory-startup --python tests/_verify_support_base_mutations.py
"""
import contextlib
import io
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import optical_alignment_sim as addon

addon.register()
addon.register = lambda: None                    # the witness registers again on every exec
from optical_alignment_sim import examples_builtin, optomech

WITNESS = (ROOT / "tests/test_support_base_geometry.py").read_text()
examples_builtin.EXAMPLES = {"hybrid_system": examples_builtin.EXAMPLES["hybrid_system"]}
REAL_DRESS = optomech.dress
REAL_INPUTS = optomech.base_plan_inputs
P = optomech.BENCH_PREFIX
BA2, BA1 = "BA2/M", "BA1/M"


# ---- how to find and bend things --------------------------------------------------------------------
def scene_objects():
    return bpy.context.scene.objects


def objs(prefix):
    return sorted((o for o in scene_objects() if o.name.startswith(P + prefix)), key=lambda o: o.name)


def base_of(part):
    return next(o for o in objs("Base") if o.get("base_part") == part)


def sibling(ob, prefix):
    return scene_objects()[P + prefix + ob.name.split("_", 2)[-1]]


def ped():
    return objs("BasePedestal_")[0]


def fork():
    return sibling(ped(), "BaseFork_")


def axis_of(ob):
    t = sibling(ob, "Holder_").matrix_world.translation
    return (t.x, t.y)


def world(ob):
    return [ob.matrix_world @ v.co for v in ob.data.vertices]


def frame(ob, centre=None):
    """World <-> part-local (u along base_angle_deg, v across), about the part's centre (bbox) or `centre`."""
    carrier = ob if "base_angle_deg" in ob else ped()
    a = math.radians(carrier["base_angle_deg"])
    c, s = math.cos(a), math.sin(a)
    if centre is None:
        w = world(ob)
        us = [p.x * c + p.y * s for p in w]
        vs = [-p.x * s + p.y * c for p in w]
        cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
        centre = (cu * c - cv * s, cu * s + cv * c)
    cx, cy = centre

    def to(p):
        return ((p.x - cx) * c + (p.y - cy) * s, -(p.x - cx) * s + (p.y - cy) * c, p.z)

    def back(u, v, z):
        return Vector((cx + u * c - v * s, cy + u * s + v * c, z))

    return to, back


def bend(ob, select, move, centre=None):
    """Move the vertices `select(u, v, z)` picks to `move(u, v, z)`, in the part's frame."""
    to, back = frame(ob, centre)
    inv = ob.matrix_world.inverted()
    hit = 0
    for vert in ob.data.vertices:
        u, v, z = to(ob.matrix_world @ vert.co)
        if select(u, v, z):
            vert.co = inv @ back(*move(u, v, z))
            hit += 1
    ob.data.update()
    assert hit, "the defect selected no vertices on %s" % ob.name


def drop(ob, select, centre=None):
    to, _ = frame(ob, centre)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    doomed = [v for v in bm.verts if select(*to(ob.matrix_world @ v.co))]
    assert doomed, "the defect selected no vertices on %s" % ob.name
    bmesh.ops.delete(bm, geom=doomed, context='VERTS')
    bm.to_mesh(ob.data)
    bm.free()


def nudge(ob, axis, mm):
    ob.location[axis] += mm


def setprop(ob, key, value):
    ob[key] = value


def remove(ob):
    bpy.data.objects.remove(ob, do_unlink=True)


def at_local(ob, u, v):
    p = frame(ob)[1](u, v, 0.0)
    return [p.x, p.y]


def top_z(ob):
    return max(p.z for p in world(ob))


def bottom_z(ob):
    return min(p.z for p in world(ob))


def first_optic():
    return next(o for o in scene_objects() if getattr(o, "optics", None) and o.optics.is_optical)


def shifted_inputs(scene):
    inp = REAL_INPUTS(scene)
    first = sorted(inp["holders"])[0]
    x, y = inp["holders"][first]
    inp["holders"][first] = (x + 0.01, y)
    return inp


def fk(select, move):                              # fork edits about the jaw (pedestal) centre
    bend(fork(), select, move, centre=axis_of(ped()))


BA2_SLOT = lambda u, v, z: 12.5 < abs(u) < 36 and abs(v) < 23.5
BA2_BORES = lambda u, v, z: abs(u) < 12.5 and abs(v) < 23.5
CF_SLOT = lambda u, v, z: 17.0 < u < 68.0 and abs(v) < 16.0


# ---- the defects: (name, assertion that must FAIL, mutation) -----------------------------------------
MUTATIONS = [
    ("an optic nudged 0.01 mm", "dressing leaves every example's trace byte-identical",
     lambda: nudge(first_optic(), 0, 0.01)),
    ("a holder's base deleted", "each holder has exactly one base", lambda: remove(base_of(BA2))),
    ("a base with no holder", "no base without a holder",
     lambda: bpy.context.scene.collection.objects.link(bpy.data.objects.new(P + "Base_zz", base_of(BA2).data))),
    ("recorded plan inputs off by 0.01 mm", "the recorded plan inputs are this scene's holders and grid",
     lambda: setattr(optomech, "base_plan_inputs", shifted_inputs)),
    ("base_conflict flipped", "base_conflict only where support_bases.choose reports it",
     lambda: setprop(base_of(BA2), "base_conflict", not bool(base_of(BA2)["base_conflict"]))),
    ("screw moved to the next hole", "base_part and base_screw_xy are the ones support_bases.choose picked",
     lambda: setprop(base_of(BA2), "base_screw_xy", [base_of(BA2)["base_screw_xy"][0] + 25.0,
                                                    base_of(BA2)["base_screw_xy"][1]])),
    ("screw 0.3 mm off its hole", "base_screw_xy is a hole of the board grid",
     lambda: setprop(base_of(BA2), "base_screw_xy", [base_of(BA2)["base_screw_xy"][0] + 0.3,
                                                    base_of(BA2)["base_screw_xy"][1]])),
    ("screw object moved 0.1 mm", "the table screw's axis is at base_screw_xy",
     lambda: nudge(sibling(base_of(BA2), "BaseScrew_"), 0, 0.1)),
    ("base_seat_mm + 0.1", "base_seat_mm is the post's seat from the drawings",
     lambda: setprop(base_of(BA2), "base_seat_mm", base_of(BA2)["base_seat_mm"] + 0.1)),
    ("seat range high end + 0.1", "base_seat_range_mm is the drawings' interval (high end)",
     lambda: setprop(base_of(BA2), "base_seat_range_mm", [base_of(BA2)["base_seat_range_mm"][0],
                                                         base_of(BA2)["base_seat_range_mm"][1] + 0.1])),
    ("seat range low end - 0.1", "base_seat_range_mm is the drawings' interval (low end)",
     lambda: setprop(base_of(BA2), "base_seat_range_mm", [base_of(BA2)["base_seat_range_mm"][0] - 0.1,
                                                         base_of(BA2)["base_seat_range_mm"][1]])),
    ("base_seat_mm not the range's high end", "base_seat_mm is the range's high end",
     lambda: setprop(base_of(BA1), "base_seat_mm", base_of(BA1)["base_seat_range_mm"][0])),
    ("a post dropped 1 mm below its range", "the post bottom lies within base_seat_range_mm",
     lambda: nudge(objs("Post_")[0], 2, -1.0)),
    ("a post raised 0.1 mm", "the post bottom stands at the seat above the board",
     lambda: nudge(objs("Post_")[0], 2, 0.1)),
    ("a plate lifted 0.1 mm", "the plate sits on the board", lambda: nudge(base_of(BA2), 2, 0.1)),
    ("a plate 0.1 mm thicker", "the plate top is 10 mm above the board",
     lambda: bend(base_of(BA2), lambda u, v, z: z > top_z(base_of(BA2)) - 1e-3, lambda u, v, z: (u, v, z + 0.1))),
    ("a holder lifted 0.1 mm off its plate", "the holder bottom sits on the plate top",
     lambda: nudge(sibling(base_of(BA2), "Holder_"), 2, 0.1)),
    ("BA2/M 0.1 mm longer", "BA2/M length (envelope)",
     lambda: bend(base_of(BA2), lambda u, v, z: u > 37.0, lambda u, v, z: (u + 0.1, v, z))),
    ("BA2/M 0.1 mm wider", "BA2/M width (envelope)",
     lambda: bend(base_of(BA2), lambda u, v, z: v > 24.5, lambda u, v, z: (u, v + 0.1, z))),
    ("one BA2/M slot 0.1 mm outward", "BA2/M slot centrelines 50.0 apart",
     lambda: bend(base_of(BA2), lambda u, v, z: u > 12.5 and BA2_SLOT(u, v, z), lambda u, v, z: (u + 0.1, v, z))),
    ("BA2/M slots 0.2 mm wider", "BA2/M slot width 6.731 at the wall",
     lambda: bend(base_of(BA2), BA2_SLOT, lambda u, v, z: (math.copysign(25.0, u) + (u - math.copysign(25.0, u)) * 1.03, v, z))),
    ("BA2/M slots 1 % longer", "BA2/M slot end centres 31.8 apart (width-free)",
     lambda: bend(base_of(BA2), BA2_SLOT, lambda u, v, z: (u, v * 1.01, z))),
    ("BA2/M slots shifted 0.1 mm along", "BA2/M slot end centres 9.1 in from the edges",
     lambda: bend(base_of(BA2), BA2_SLOT, lambda u, v, z: (u, v + 0.1, z))),
    ("BA2/M screw 0.5 mm across its slot", "BA2/M screw's shank fits a slot",
     lambda: setprop(base_of(BA2), "base_screw_xy", at_local(base_of(BA2), 25.5, 0.0))),
    ("BA2/M screw beyond its slot run", "BA2/M screw's shank fits a slot",
     lambda: setprop(base_of(BA2), "base_screw_xy", at_local(base_of(BA2), 25.0, 17.0))),
    ("BA2/M counterbores 0.1 mm off the centreline", "BA2/M counterbores on the centreline (37.5 from the edge)",
     lambda: bend(base_of(BA2), BA2_BORES, lambda u, v, z: (u + 0.1, v, z))),
    ("BA2/M counterbores 1 % further apart", "BA2/M counterbore centres 12.5 apart",
     lambda: bend(base_of(BA2), BA2_BORES, lambda u, v, z: (u, v * 1.01, z))),
    ("BA2/M counterbores squeezed together", "BA2/M has three counterbores",
     lambda: bend(base_of(BA2), BA2_BORES, lambda u, v, z: (u, v * 0.3, z))),
    ("a BA2/M slot removed", "BA2/M has two slots",
     lambda: drop(base_of(BA2), lambda u, v, z: u > 12.5 and BA2_SLOT(u, v, z))),
    ("holder 0.1 mm off its counterbore", "the holder axis is over a counterbore",
     lambda: nudge(sibling(base_of(BA2), "Holder_"), 0, 0.1)),
    ("BA1/M 0.1 mm longer", "BA1/M length (envelope)",
     lambda: bend(base_of(BA1), lambda u, v, z: u > 37.0, lambda u, v, z: (u + 0.1, v, z))),
    ("BA1/M 0.1 mm wider", "BA1/M width (envelope)",
     lambda: bend(base_of(BA1), lambda u, v, z: v > 12.0, lambda u, v, z: (u, v + 0.1, z))),
    ("BA1/M slot inner ends 0.1 mm in", "BA1/M slot end centre 20.1 from its end",
     lambda: bend(base_of(BA1), lambda u, v, z: 7.0 < abs(u) < 30.0 and abs(v) < 11.0,
                  lambda u, v, z: (u - math.copysign(0.1, u), v, z))),
    ("BA1/M slots 0.1 mm off centre", "BA1/M slot on the centreline",
     lambda: bend(base_of(BA1), lambda u, v, z: abs(u) > 7.0 and abs(v) < 11.0, lambda u, v, z: (u, v + 0.1, z))),
    ("BA1/M slots 0.2 mm wider", "BA1/M slot width 6.731 at the wall",
     lambda: bend(base_of(BA1), lambda u, v, z: abs(u) > 7.0 and abs(v) < 11.0, lambda u, v, z: (u, v * 1.03, z))),
    ("a BA1/M slot removed", "BA1/M has two slots",
     lambda: drop(base_of(BA1), lambda u, v, z: u > 7.0 and abs(v) < 11.0)),
    ("BA1/M screw 0.5 mm off the slot line", "BA1/M screw's shank fits a slot",
     lambda: setprop(base_of(BA1), "base_screw_xy", at_local(
         base_of(BA1), frame(base_of(BA1))[0](Vector((*base_of(BA1)["base_screw_xy"], 0.0)))[0], 0.5))),
    ("holder 0.1 mm off BA1/M's centre hole", "the holder axis is over BA1/M's centre hole",
     lambda: nudge(sibling(base_of(BA1), "Holder_"), 1, 0.1)),
    ("pedestal lifted 0.1 mm", "the pedestal sits on the board", lambda: nudge(ped(), 2, 0.1)),
    ("BE1/M disc 1 % wider", "BE1/M disc diameter (envelope)",
     lambda: bend(ped(), lambda u, v, z: True, lambda u, v, z: (u * 1.01, v * 1.01, z), centre=axis_of(ped()))),
    ("BE1/M disc top 0.1 mm higher", "BE1/M disc top 4.7 mm above the board",
     lambda: bend(ped(), lambda u, v, z: math.hypot(u, v) > 10.0 and z > bottom_z(ped()) + 1.0,
                  lambda u, v, z: (u, v, z + 0.1), centre=axis_of(ped()))),
    ("BE1/M stud 0.1 mm longer", "BE1/M stud end 12.3 mm above the board",
     lambda: bend(ped(), lambda u, v, z: z > top_z(ped()) - 1e-3, lambda u, v, z: (u, v, z + 0.1),
                  centre=axis_of(ped()))),
    ("holder lifted 0.1 mm off the disc", "the holder bottom sits on the disc top",
     lambda: nudge(sibling(ped(), "Holder_"), 2, 0.1)),
    ("CF125 0.1 mm longer", "CF125 length (envelope)",
     lambda: fk(lambda u, v, z: u > 69.0, lambda u, v, z: (u + 0.1, v, z))),
    ("CF125 0.1 mm wider", "CF125 width (envelope)",
     lambda: fk(lambda u, v, z: v > 17.5, lambda u, v, z: (u, v + 0.1, z))),
    ("CF125 tips 0.1 mm longer", "CF125 tips 3.8 mm behind the jaw centre",
     lambda: fk(lambda u, v, z: u < -3.0, lambda u, v, z: (u - 0.1, v, z))),
    ("CF125 jaw 1 % wider", "CF125 jaw",
     lambda: fk(lambda u, v, z: math.hypot(u, v) < 13.3, lambda u, v, z: (u * 1.01, v * 1.01, z))),
    ("CF125 undercut 1 % wider", "CF125 undercut",
     lambda: fk(lambda u, v, z: u > 0 and abs(math.hypot(u, v) - 16.25) < 0.3, lambda u, v, z: (u * 1.01, v * 1.01, z))),
    ("CF125 slot 0.1 mm further out", "CF125 far slot end centre 58.3 from the jaw centre",
     lambda: fk(CF_SLOT, lambda u, v, z: (u + 0.1, v, z))),
    ("CF125 slot 1 % longer", "CF125 slot end centres 31.5 apart",
     lambda: fk(CF_SLOT, lambda u, v, z: (42.55 + (u - 42.55) * 1.01, v, z))),
    ("CF125 slot 0.2 mm wider", "CF125 slot width 6.731 at the wall",
     lambda: fk(CF_SLOT, lambda u, v, z: (u, v * 1.03, z))),
    ("CF125 slot 0.1 mm off centre", "CF125 slot on the fork's centreline",
     lambda: fk(CF_SLOT, lambda u, v, z: (u, v + 0.1, z))),
    ("fork screw beyond the slot's reach", "the fork's screw is within 26.8-58.3 mm of the pedestal",
     lambda: setprop(ped(), "base_screw_xy",
                     [axis_of(ped())[0] + 60.0 * math.cos(math.radians(ped()["base_angle_deg"])),
                      axis_of(ped())[1] + 60.0 * math.sin(math.radians(ped()["base_angle_deg"]))])),
    ("base_angle_deg 2 degrees off", "the fork's slot holds its screw",
     lambda: setprop(ped(), "base_angle_deg", ped()["base_angle_deg"] + 2.0)),
    ("an unknown base_part", "base_part is one of BA2/M, BA1/M, BE1/M + CF125",
     lambda: setprop(base_of(BA2), "base_part", "BA3/M")),
    ("a fork deleted", "a pedestal comes with a fork, a plate without one", lambda: remove(fork())),
    ("base_seat_mm missing", "the base carries base_screw_xy, base_angle_deg, base_seat_mm, base_seat_range_mm",
     lambda: base_of(BA2).__delitem__("base_seat_mm")),
    ("a post deleted", "the post exists", lambda: remove(objs("Post_")[0])),
    ("a washer deleted", "the table screw and its washer exist", lambda: remove(sibling(base_of(BA2), "BaseWasher_"))),
]


def run(mutation=None):
    def dress(scene, *a, **k):
        n = REAL_DRESS(scene, *a, **k)
        bpy.context.view_layer.update()
        if mutation is not None:
            mutation()
            bpy.context.view_layer.update()
        return n

    optomech.dress = dress
    optomech.base_plan_inputs = REAL_INPUTS
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            exec(compile(WITNESS, "test_support_base_geometry.py", "exec"), {"__name__": "__witness__",
                                                                              "__file__": str(ROOT / "tests/test_support_base_geometry.py")})
        except AssertionError:
            pass
    optomech.dress = REAL_DRESS
    optomech.base_plan_inputs = REAL_INPUTS
    return [line[5:].split(":", 1)[0] for line in out.getvalue().splitlines() if line.startswith("FAIL ")]


baseline = run()
print("baseline (no defect): %s" % ("all PASS" if not baseline else "FAIL %s" % baseline), flush=True)
missed = []
for name, target, mutate in MUTATIONS:
    try:
        failed = run(mutate)
    except Exception as exc:                      # a defect that cannot even be planted is a harness bug
        optomech.dress = REAL_DRESS
        optomech.base_plan_inputs = REAL_INPUTS
        print("ERROR  %-46s %r" % (name, exc), flush=True)
        missed.append(name)
        continue
    caught = any(f.startswith(target) for f in failed)
    print("%s %-46s -> %s  (%d failing)" % ("CAUGHT" if caught else "MISSED", name, target, len(failed)), flush=True)
    if not caught:
        missed.append(name)
        print("       failing instead: %s" % failed, flush=True)

print("MUTATIONS %s (%d/%d caught, baseline %s)" % ("PASS" if not missed and not baseline else "FAIL",
                                                     len(MUTATIONS) - len(missed), len(MUTATIONS),
                                                     "clean" if not baseline else "NOT clean"), flush=True)
if missed or baseline:
    raise AssertionError("defects the witness did not catch: %s" % missed)
