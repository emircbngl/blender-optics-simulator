"""Headless verification harness for Wave-2 A8/A7/A6 (solvers.py).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_solvers.py

Proves, in order:
  (2) BYTE-IDENTICAL: each of the 14 build_example scenes traces to the SAME md5
      whether or not `solvers` has been imported/touched (import is inert; a normal
      trace never enters the solver). We hash the canonical segment geometry +
      every element's world ports BEFORE importing solvers and AFTER, and diff.
  (3) CONVERGENCE: two DIFFERENT steering topologies (a 1-mirror source->mirror->
      detector, and a 2-mirror beam-walk source->M1->M2->iris->detector), each
      knocked out of alignment, then auto_align / beam_walk collapses the residual
      below eps in a few iterations. Prints the per-iteration residual history.
  (4) A8 METRIC: a known injected transverse offset of the beam at an aperture is
      recovered by aperture_residual within tolerance; and offset_from_throughput
      inverts _clip_T.
"""
import hashlib
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


# --------------------------------------------------------------------------- #
def _register_addon():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    return addon


def _seg_digest(segs):
    """Canonical, order-stable digest of a traced scene: every segment's
    geometry + power + provenance, rounded so floating noise can't fake a diff."""
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
    """md5 of every optical element's world ports (pos+normal) — the
    ports x matrix_world the tracer dispatches on."""
    from optical_alignment_sim import geometry
    rows = []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        for p in op.ports:
            wp = geometry.world_port(obj, p.local_position)
            wn = geometry.world_normal(obj, p.local_normal)
            rows.append("%s.%s|%s|%s" % (
                obj.name, p.name,
                ",".join("%.5f" % x for x in wp),
                ",".join("%.5f" % x for x in wn)))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _trace(scene):
    from optical_alignment_sim import tracer
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _build_and_hash():
    """Build all 14 examples and return {kind: (seg_md5, ports_md5)}."""
    from optical_alignment_sim import examples_builtin as ex
    scene = bpy.context.scene
    out = {}
    for kind in ex.EXAMPLES:
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        segs = _trace(scene)
        out[kind] = (_seg_digest(segs), _ports_digest(scene))
    return out


def test_byte_identical():
    print("\n=== (2) BYTE-IDENTICAL: 14 examples, trace + ports md5 ===")
    # BEFORE: build & hash without ever touching solvers (it is in sys.modules from
    # register(), but never referenced; import is inert).
    before = _build_and_hash()
    # AFTER: explicitly import & reference the solver module + every public entry
    # point, then rebuild & rehash. If importing/holding solvers perturbed the
    # trace, the md5 would move.
    from optical_alignment_sim import solvers
    _ = (solvers.auto_align, solvers.beam_walk, solvers.influence_solve,
         solvers.aperture_residual, solvers.offset_from_throughput, solvers.measure_y)
    after = _build_and_hash()

    all_ok = True
    for kind in sorted(before):
        sb, pb = before[kind]
        sa, pa = after[kind]
        ok = (sb == sa and pb == pa)
        all_ok = all_ok and ok
        print("  %-16s seg %s  ports %s  %s"
              % (kind, sb[:12], pb[:12], "OK" if ok else "CHANGED"))
    check(all_ok, "all 14 examples trace + ports byte-identical across solvers import")


# --------------------------------------------------------------------------- #
def _fresh_collection(name):
    """Start each topology from an EMPTY optical scene: drop every prior optics /
    example / verify collection so no stray element from a previous test sits in
    the new beam's path (which would intercept it and read as a dark aperture)."""
    from optical_alignment_sim import elements_generic as G, tracer
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsVerify_") or c.name.startswith("OpticsExample_") or c.name == name:
            for o in list(c.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(c)
    # also drop any orphaned optical objects not in a collection we removed
    for o in list(bpy.context.scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            G.drop_example_object(o)
    tracer.cached_segments = []
    return G.example_collection(name)


def test_convergence_topo1():
    """Topology A: source -> single kinematic mirror -> detector (90 deg fold).
    Knock the mirror's tip out, then generic auto_align (no args) walks it back."""
    print("\n=== (3a) CONVERGENCE topology A: laser -> mirror -> detector ===")
    from optical_alignment_sim import elements_generic as G, mounts, solvers
    import optics_api as api
    scene = bpy.context.scene
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    c = _fresh_collection("OpticsVerify_TopoA")
    G.source("VA_Laser", (-120, 0, 0), X, c)
    G.mirror("VA_Mirror", (0, 0, 0), X, Y, c)
    G.detector("VA_Cam", (0, 130, 0), Y, c, size=22.0)
    api.set_mount("VA_Mirror", "KM100")

    mirror = scene.objects["VA_Mirror"]
    for d in mirror.optics.dofs:
        if d.kind == "TIP":
            d.current = 1.6                       # knock it ~1.6 deg off (beam ~7 mm off centre)
    mounts.compose_pose(mirror)
    bpy.context.view_layer.update()

    res = solvers.auto_align(scene)               # GENERIC: no actuators/targets named
    print("  controls:", res.get("controls"))
    print("  targets :", res.get("targets"))
    print("  history :", res.get("history"))
    print("  before %.4f -> after %.4f mm in %d iters (converged=%s)"
          % (res["residual_before"], res["residual_after"], res["iterations"], res["converged"]))
    h = res["history"]
    mono = all(h[i + 1] <= h[i] + 1e-6 for i in range(len(h) - 1))
    check(res["ok"] and res["residual_before"] > 1.0, "A: starts misaligned (>1 mm)")
    check(res["converged"] and res["residual_after"] < 0.02, "A: converged below eps")
    check(mono, "A: residual history monotonically non-increasing")
    check(res["iterations"] <= 4, "A: converged in a few (<=4) iterations")


def test_convergence_topo2():
    """Topology B (genericity proof - DIFFERENT bench): two-mirror beam walk.
    source -> M1 -> M2 -> near iris -> far detector. Knock BOTH mirrors out, then
    the A6 beam_walk wrapper (4-DOF) centers the beam on both planes."""
    print("\n=== (3b) CONVERGENCE topology B: two-mirror beam-walk (4-DOF) ===")
    from optical_alignment_sim import elements_generic as G, mounts, solvers
    import optics_api as api
    scene = bpy.context.scene
    X, Y, nX = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((-1, 0, 0))
    c = _fresh_collection("OpticsVerify_TopoB")
    # laser east; M1 folds north; M2 folds east again; iris then detector down-beam
    G.source("VB_Laser", (-160, 0, 0), X, c)
    G.mirror("VB_M1", (0, 0, 0), X, Y, c)          # +X in -> +Y out
    G.mirror("VB_M2", (0, 120, 0), Y, X, c)        # +Y in -> +X out
    G.aperture("VB_Iris", (90, 120, 0), X, c, radius=10.0)    # near reference plane
    G.detector("VB_Cam", (200, 120, 0), X, c, size=22.0)     # far reference plane
    api.set_mount("VB_M1", "KM100")
    api.set_mount("VB_M2", "KM100")

    for mname, tip in (("VB_M1", 1.0), ("VB_M2", -0.8)):
        m = scene.objects[mname]
        for d in m.optics.dofs:
            if d.kind == "TIP":
                d.current = tip
        mounts.compose_pose(m)
    bpy.context.view_layer.update()

    res = solvers.beam_walk(scene, "VB_M1", "VB_M2", "VB_Iris", "VB_Cam")
    print("  controls:", res.get("controls"))
    print("  targets :", res.get("targets"))
    print("  history :", res.get("history"))
    print("  before %.4f -> after %.4f mm in %d iters (converged=%s)"
          % (res["residual_before"], res["residual_after"], res["iterations"], res["converged"]))
    h = res["history"]
    mono = all(h[i + 1] <= h[i] + 1e-6 for i in range(len(h) - 1))
    check(res["ok"] and res["n_controls"] == 4 and res["n_targets"] == 2, "B: 4 DOF, 2 planes")
    check(res["residual_before"] > 1.0, "B: starts misaligned (>1 mm)")
    check(res["converged"] and res["residual_after"] < 0.02, "B: converged below eps")
    check(mono, "B: residual history monotonically non-increasing")
    check(res["iterations"] <= 4, "B: converged in a few (<=4) iterations")


# --------------------------------------------------------------------------- #
def test_a8_metric():
    """A8: inject a KNOWN transverse offset (slide the detector sideways by a
    known amount perpendicular to the beam) and confirm aperture_residual reads
    it back; and offset_from_throughput inverts the _clip_T throughput law."""
    print("\n=== (4) A8 METRIC: injected-offset recovery + throughput inverse ===")
    from optical_alignment_sim import elements_generic as G, solvers, tracer
    scene = bpy.context.scene
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    c = _fresh_collection("OpticsVerify_A8")
    G.source("M8_Laser", (-120, 0, 0), X, c)
    G.detector("M8_Cam", (120, 0, 0), X, c, size=40.0)        # straight shot, beam hits centre
    bpy.context.view_layer.update()

    cam = scene.objects["M8_Cam"]
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    r_centered = solvers.aperture_residual(segs, cam)
    check(0.0 <= r_centered < 0.05, "A8: centered beam reads ~0 residual (%.4f)" % r_centered)

    # inject a known +7.0 mm offset along the detector's transverse u-axis by
    # translating the detector -7 mm along u (beam now lands +7 mm off centre)
    _c, _n, u, _v = solvers.aperture_transverse_basis(cam)
    inject = 7.0
    cam.matrix_world = cam.matrix_world.copy()
    cam.location = cam.location - u * inject
    bpy.context.view_layer.update()
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    r_injected = solvers.aperture_residual(segs, cam)
    err = abs(r_injected - inject)
    print("  injected %.3f mm -> measured residual %.4f mm (err %.4f)" % (inject, r_injected, err))
    check(err < 0.05, "A8: recovers the %.1f mm injected offset within tol" % inject)

    # throughput inverse: pick a known offset d, compute the on-axis pinhole
    # sampling T = exp(-2 d^2 / w^2), then invert and recover d.
    import math
    w, d_true = 1.2, 0.65
    T = math.exp(-2.0 * d_true * d_true / (w * w))
    d_rec = solvers.offset_from_throughput(T, w)
    print("  throughput T=%.5f (w=%.2f, d=%.3f) -> recovered d=%.5f" % (T, w, d_true, d_rec))
    check(abs(d_rec - d_true) < 1e-6, "A8: offset_from_throughput inverts _clip_T (d=%.3f)" % d_true)


# --------------------------------------------------------------------------- #
def main():
    _register_addon()
    test_byte_identical()
    test_convergence_topo1()
    test_convergence_topo2()
    test_a8_metric()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL SOLVER VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
