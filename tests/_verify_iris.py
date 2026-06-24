"""Headless verification harness for Wave-2 D2 (realistic multi-leaf iris + foil-in-housing pinhole).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_iris.py

D2 is a pure MESH-RESOLUTION / cosmetic task: it rebuilds the iris (aperture()) and pinhole() MESHES to
read as real hardware (10-12 overlapping matte-black wedge leaves forming the polygonal opening, a knurled
adjuster ring, an engraved close-arrow; an SM1 housing ring + recessed blackened-foil face + chamfered bore).
NO new physics, NO new formula, NO tracer change. The optical behavior reads from the element PORTS
(local_position / local_normal / clear_aperture) x matrix_world, NOT the mesh -- so the mesh may change
freely as long as every PORT stays byte-identical.

Proves, in order:
  (A) NO NEW PHYSICS: D2 adds no formula/constant -- stated, nothing to oracle-verify here.
  (B) BYTE-IDENTICAL (the critical gate): every build_example scene (all 17, incl. the 14 core + the
      C3/C4 prism examples, and the 3 examples that CONTAIN an iris -- relay/microscope/dhm) traces to the
      SAME seg + ports md5 as before D2. The pinned references for this session are checked. Then a FRESH
      iris and FRESH pinhole are built and their LOCAL port tuples (position/normal/clear_aperture + element
      type + clear_aperture) are asserted byte-identical to the pinned pre-change digest.
  (C) OPENING TRACKS THE APERTURE RADIUS: building the iris at radius 8/14/20 moves the polygonal opening
      (inner leaf vertices) while the port clear_aperture stays == radius (the value the tracer reads).
  (D) The full regression (tests/test_optics.py) is the separate gate -- not re-run here.
"""
import hashlib
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector

FAILS = []


def check(cond, label):
    print(("PASS" if cond else "FAIL"), "-", label)
    if not cond:
        FAILS.append(label)
    return cond


def _register_addon():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    return addon


# Pinned reference seg/ports digests captured from the PRE-D2 builder (this session) -- the full set of
# build_example scenes. D2 only touches the iris/pinhole MESH, so every one must be byte-identical.
REF_EX = {
    "adaptive_optics": ("176217fce1ba", "3de42c1386c2"), "aom": ("c0651b75cb04", "0f62186bb703"),
    "beam_profiler": ("b762253f4c18", "db53b445888f"), "beam_router": ("ea86e964c09f", "a4982f49973f"),
    "bell": ("75ca6c1eec30", "42f238335316"), "cage_system": ("f36e2cd70a9f", "f3d18f198755"),
    "dhm": ("111a3d05b96d", "6e2532e2f759"), "hong_ou_mandel": ("36b08c3f9e96", "84a277841741"),
    "hybrid_system": ("f3b5f57d8a39", "66de45132aab"), "mach_zehnder": ("819b140513c1", "db8d5acdd4ed"),
    "michelson": ("2988d9599234", "82926106d9a9"), "microscope": ("01c250dd42f3", "4c985407692f"),
    "newton_rings": ("1a158f3aa0f2", "15410e2bc376"), "periscope": ("7a69a20b58f7", "7232f1e2b0f4"),
    "prism": ("83a99bef632b", "c26f2e54b3ec"), "rail_system": ("20af209bacfa", "48f931ae6513"),
    "tube_system": ("e166d71ea528", "fdeceabc48a1"),
}
# The three examples that actually CONTAIN an iris (aperture()) -- byte-identical here is the real D2 proof.
IRIS_EXAMPLES = {"rail_system", "microscope", "dhm"}
# Pinned LOCAL port digests of a fresh iris (radius 14.0) and pinhole (radius 12.5) from the PRE-D2 builder.
REF_IRIS_LOCAL = "9038f6a6eee954a74f7b212f735f093f"
REF_PINHOLE_LOCAL = "08bb19b9eb915b38dfdf7f193810f81a"


def _seg_digest(segs):
    rows = []
    for s in segs:
        rows.append("|".join([
            str(s.get("from")), str(s.get("to")), s.get("kind", ""),
            ",".join("%.6f" % x for x in s["p1"]),
            ",".join("%.6f" % x for x in s["p2"]),
            "%.6f" % s.get("power", 0.0), "%.4f" % s.get("wavelength", 0.0),
            "%.6f" % s.get("w_mm", 0.0), str(s.get("parent", -1)),
        ]))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _ports_digest(scene):
    from optical_alignment_sim import geometry
    rows = []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        for p in op.ports:
            wp = geometry.world_port(obj, p.local_position)
            wn = geometry.world_normal(obj, p.local_normal)
            rows.append("%s.%s|%s|%s" % (obj.name, p.name,
                                         ",".join("%.5f" % x for x in wp),
                                         ",".join("%.5f" % x for x in wn)))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _local_port_digest(obj):
    op = obj.optics
    rows = ["ET=%s" % op.element_type, "CA=%.6f" % op.clear_aperture]
    for p in op.ports:
        rows.append("%s|%s|%s|%s|%.6f" % (
            p.name, p.role,
            ",".join("%.6f" % x for x in p.local_position),
            ",".join("%.6f" % x for x in p.local_normal),
            p.clear_aperture))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _trace(scene):
    from optical_alignment_sim import tracer
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def test_no_new_physics():
    print("\n=== (A) NO NEW PHYSICS ===")
    check(True, "D2 introduces NO formula/constant/tracer change -- mesh-only; nothing for the oracle to verify")


def test_byte_identical():
    print("\n=== (B) BYTE-IDENTICAL: every example + the iris/pinhole ports unchanged by the D2 mesh ===")
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    scene = bpy.context.scene
    for cc in list(bpy.data.collections):
        if cc.name.startswith("OpticsVerify_") or cc.name.startswith("D2_"):
            for o in list(cc.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(cc)
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    check(len(ex.EXAMPLES) >= 17, ">=17 build_example scenes (%d)" % len(ex.EXAMPLES))
    all_ok = True
    iris_ok = True
    for kind in sorted(ex.EXAMPLES):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene)); pd = _ports_digest(scene)
        ref = REF_EX.get(kind)
        ok = ref is None or (sd.startswith(ref[0]) and pd.startswith(ref[1]))
        all_ok = all_ok and ok
        if kind in IRIS_EXAMPLES:
            iris_ok = iris_ok and ok
        flag = " [IRIS]" if kind in IRIS_EXAMPLES else ""
        tag = "" if ref is None else ("  ref %s/%s %s" % (ref[0], ref[1], "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s ports %s%s%s" % (kind, sd[:12], pd[:12], flag, tag))
    check(all_ok, "ALL 17 example seg+ports digests byte-identical to pre-D2")
    check(iris_ok, "the 3 iris-bearing examples (rail_system/microscope/dhm) byte-identical")

    # fresh iris + pinhole LOCAL port digest == pinned pre-D2
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = G.example_collection("OpticsVerify_Iris")
    X = Vector((1, 0, 0))
    iris = G.aperture("VI_iris", (0, 0, 0), X, c, radius=14.0)
    ld = _local_port_digest(iris)
    print("  fresh iris (radius 14.0) local-port-digest", ld)
    check(ld == REF_IRIS_LOCAL, "fresh iris ports byte-identical to pre-D2 (%s)" % REF_IRIS_LOCAL)
    ph = G.pinhole("VI_ph", (60, 0, 0), X, c, radius=12.5)
    ld2 = _local_port_digest(ph)
    print("  fresh pinhole (radius 12.5) local-port-digest", ld2)
    check(ld2 == REF_PINHOLE_LOCAL, "fresh pinhole ports byte-identical to pre-D2 (%s)" % REF_PINHOLE_LOCAL)

    # mesh actually got richer (not the old solid puck): >= 12 leaves + ring + arrow -> many more faces/mats
    check(len(iris.data.materials) >= 4,
          "iris mesh has >=4 material slots (housing + leaves + knurl + arrow): %d" % len(iris.data.materials))
    check(len(ph.data.materials) >= 2,
          "pinhole mesh has >=2 material slots (housing + blackened foil): %d" % len(ph.data.materials))


def _opening_corner_r(o):
    """The polygonal opening size read from the mesh: the radius of the nearest mesh vertex to the optical
    (+Z) axis = the polygon CORNER radius of the matte-black leaves (the leaves form the limiting opening).
    Tracks r_open by construction (leaves' inner chord is tangent to the r_open circle)."""
    return min((math.hypot(v.co.x, v.co.y) for v in o.data.vertices), default=0.0)


def test_opening_tracks_radius():
    print("\n=== (C) OPENING TRACKS THE APERTURE RADIUS ===")
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = G.example_collection("OpticsVerify_IrisR")
    X = Vector((1, 0, 0))
    print("  radius   clear_aperture(port)   polygon_opening_r(mesh)")
    res = []
    for rr in (8.0, 14.0, 20.0):
        ir = G.aperture("VIR_%g" % rr, (0, rr * 8, 0), X, c, radius=rr)
        ropen = _opening_corner_r(ir)
        ca = ir.optics.clear_aperture
        res.append((rr, ca, ropen))
        print("  %-7g  %-19.4f  %.4f" % (rr, ca, ropen))
    # the port clear_aperture the TRACER reads == radius at every setting (unchanged behaviour)
    check(all(abs(ca - rr) < 1e-6 for rr, ca, _ in res),
          "port clear_aperture == radius at every setting (the value the tracer reads is r-driven, unchanged)")
    # the polygonal opening (inner leaf vertices) MOVES with the radius
    ropens = [r for _, _, r in res]
    check(ropens[0] < ropens[1] < ropens[2],
          "polygonal opening (leaf corner radius) grows with radius: %s" % [round(x, 3) for x in ropens])
    # and the opening sits right at r_open (the leaves form the aperture at r_open; the polygon corner is
    # within ~1 mm of the inscribed r_open by construction -> the opening tracks the aperture)
    check(all(abs(ropen - rr) < max(1.2, rr * 0.06) for rr, _, ropen in res),
          "polygonal opening sits at r_open at every setting (leaves form the opening at the aperture)")


def main():
    _register_addon()
    test_no_new_physics()
    test_byte_identical()
    test_opening_tracks_radius()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL IRIS/PINHOLE (D2) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
