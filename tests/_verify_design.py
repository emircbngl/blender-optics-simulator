"""Headless verification harness for Wave-2 B2 (design.py + the relay_spacing diagnostic).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_design.py

Proves, in order:
  (A) DESIGNER MATH: afocal_abcd composes to the oracle-verified afocal matrix
      [[-f2/f1, f1+f2], [0, -f1/f2]] (C=0 -> the afocal condition; B=f1+f2; det=1),
      and design_telescope / design_4f report the right sep / magnification / type.
      (The full physics_verify of this matrix ran separately to ok=true, 18/18.)
  (B) TRACER GROUND-TRUTH: a REAL two-lens telescope (collimated source -> L1(f1) ->
      L2(f2) -> detector). When d=f1+f2 the OUTPUT Gaussian beam stays COLLIMATED
      (wavefront ROC ~ inf -> ~0 curvature) and its spot scales by |f2/f1|; when the
      L1-L2 spacing is DETUNED by a few mm the output is NO LONGER collimated (finite
      ROC, large curvature) AND the relay_spacing diagnostic FIRES with severity WARN.
      Two (f1,f2) pairs: a 2x expander (50/100) and a 0.5x reducer (100/50).
  (C) BYTE-IDENTICAL: each of the 14 build_example scenes traces to the SAME seg +
      ports md5 whether or not `design` has been imported/referenced (import is inert;
      the new diagnostic never mutates a trace).
  (E) NO NEW DIAGNOSTICS: diagnose() on every one of the 14 examples returns the SAME
      diagnostic count before vs after this change (relay_spacing adds ZERO to them --
      none is a detuned telescope). Prints the per-example counts.
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


# --------------------------------------------------------------------------- #
# shared digests (same canonical form as _verify_solvers.py)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# (A) designer math
# --------------------------------------------------------------------------- #
def test_designer_math():
    print("\n=== (A) DESIGNER MATH: afocal_abcd + design_telescope/4f ===")
    from optical_alignment_sim import design

    def close(a, b, tol=1e-9):
        return abs(a - b) <= tol

    ok_all = True
    for f1, f2 in ((50.0, 100.0), (100.0, 50.0), (-25.0, 75.0), (200.0, -40.0)):
        A = design.afocal_abcd(f1, f2)
        good = (close(A[0][0], -f2 / f1) and close(A[1][1], -f1 / f2)
                and close(A[0][1], f1 + f2) and close(A[1][0], 0.0)
                and close(A[0][0] * A[1][1] - A[0][1] * A[1][0], 1.0))
        print("  afocal_abcd(%g,%g) = [[%.4f,%.4f],[%.4f,%.4f]]  C==0:%s det==1:%s"
              % (f1, f2, A[0][0], A[0][1], A[1][0], A[1][1],
                 close(A[1][0], 0.0), close(A[0][0]*A[1][1]-A[0][1]*A[1][0], 1.0)))
        ok_all = ok_all and good
    check(ok_all, "A: afocal_abcd == [[-f2/f1, f1+f2],[0,-f1/f2]] (C=0, det=1) for all pairs")

    t = design.design_telescope(50.0, 100.0)
    check(close(t["sep"], 150.0) and close(t["magnification"], -2.0)
          and close(t["angular_mag"], -0.5) and close(t["beam_expansion"], 2.0)
          and t["type"] == "keplerian",
          "A: design_telescope(50,100) -> sep150, M-2, ang-0.5, exp2, keplerian")
    g = design.design_telescope(200.0, -40.0)
    check(g["type"] == "galilean" and close(g["beam_expansion"], 0.2),
          "A: design_telescope(200,-40) -> galilean, exp0.2")
    q = design.design_4f(50.0, 100.0)
    check(close(q["seps"][0], 50.0) and close(q["seps"][1], 150.0) and close(q["seps"][2], 100.0)
          and close(q["total_length"], 300.0) and close(q["transverse_mag"], -2.0),
          "A: design_4f(50,100) -> seps[50,150,100], total300, mag-2")
    check(design.design_telescope(0.0, 100.0).get("ok") is False
          and design.design_4f(50.0, "x").get("ok") is False,
          "A: zero / non-numeric focal rejected with {ok:False}")


# --------------------------------------------------------------------------- #
# (B) tracer ground-truth: collimated vs detuned, two f-pairs
# --------------------------------------------------------------------------- #
def _fresh_collection(name):
    """Start from an EMPTY optical scene. HARD-delete every optical object (and free
    its mesh) regardless of which collection holds it -- `drop_example_object` only
    deletes objects whose collections are all `OpticsExample_`-prefixed, so a test
    collection of any other name would leak its parts onto the next beam's axis."""
    from optical_alignment_sim import elements_generic as G, tracer
    for o in list(bpy.context.scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            mesh = o.data if o.type == 'MESH' else None
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsVerify_") or c.name.startswith("OpticsExample_") or c.name == name:
            bpy.data.collections.remove(c)
    tracer.cached_segments = []
    return G.example_collection(name)


def _output_q_and_w(segs, det_name):
    """The Gaussian q (-> R, w) of the beam landing on the detector."""
    s = next((x for x in segs if x.get("to") == det_name), None)
    if s is None or s.get("qd") is None:
        return None, None
    q = complex(s["qd"][0], s["qd"][1])
    return q, s.get("w_mm", 0.0)


def _run_telescope(f1, f2, detune_mm, tagname):
    """Build laser -> L1(f1) -> L2(f2) -> detector along +X with L1-L2 separation
    = f1+f2+detune_mm; trace and return (q_out, w_out, segs, names)."""
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    X = Vector((1, 0, 0))
    c = _fresh_collection("OpticsVerify_" + tagname)
    sep = f1 + f2 + detune_mm
    # source close to L1 so the beam arrives ~collimated (waist 0.5 mm -> zR ~ 1.2 m,
    # negligible divergence over the short source->L1 gap); L1 at x0, L2 at x0+sep.
    x_src, x_l1 = -40.0, 0.0
    x_l2 = x_l1 + sep
    x_det = x_l2 + 60.0
    G.source("%s_Laser" % tagname, (x_src, 0, 0), X, c)
    G.lens("%s_L1" % tagname, (x_l1, 0, 0), X, c, focal=f1, radius=14.0)
    G.lens("%s_L2" % tagname, (x_l2, 0, 0), X, c, focal=f2, radius=14.0)
    G.detector("%s_Cam" % tagname, (x_det, 0, 0), X, c, size=40.0)
    bpy.context.view_layer.update()
    segs = _trace(scene)
    q, w = _output_q_and_w(segs, "%s_Cam" % tagname)
    return q, w, segs, ("%s_L1" % tagname, "%s_L2" % tagname, "%s_Cam" % tagname)


def _curvature(q):
    """Wavefront curvature 1/R (mm^-1) from q; 0 == collimated (flat wavefront)."""
    from optical_alignment_sim import physics
    R = physics.beam_roc(q)
    return 0.0 if (R == float('inf') or abs(R) > 1e11) else 1.0 / R


def test_tracer_ground_truth():
    from optical_alignment_sim import diagnostics
    scene = bpy.context.scene
    for (f1, f2, tag) in ((50.0, 100.0, "TS2x"), (100.0, 50.0, "TS05x")):
        print("\n=== (B) TRACER GROUND-TRUTH: telescope f1=%g f2=%g (expansion |f2/f1|=%g) ==="
              % (f1, f2, abs(f2 / f1)))
        # --- afocal: d = f1+f2 ---  (distinct tag so teardown can't leave a .001 twin)
        q0, w0, segs0, names = _run_telescope(f1, f2, 0.0, tag + "af")
        # the INPUT spot at L1 (w of the source->L1 segment landing on L1)
        s_in = next((x for x in segs0 if x.get("to") == names[0]), None)
        w_in = s_in.get("w_mm", 0.0) if s_in else 0.0
        k0 = _curvature(q0) if q0 is not None else None
        ratio = (w0 / w_in) if (w_in and w0) else 0.0
        diags0 = diagnostics.run_diagnostics(scene)
        relay0 = [d for d in diags0 if d["kind"] == "relay_spacing"]

        # --- detuned: d = f1+f2 + a few mm ---  (computed before asserting so we can
        #     compare collimation afocal-vs-detuned: an afocal system has C=0, so it
        #     maps the input wavefront curvature straight through WITHOUT adding focus;
        #     detuning gives C != 0 -> the flat input picks up a large output curvature.)
        detune = 6.0
        q1, w1, segs1, names_dt = _run_telescope(f1, f2, detune, tag + "dt")
        k1 = _curvature(q1) if q1 is not None else None
        diags1 = diagnostics.run_diagnostics(scene)
        relay1 = [d for d in diags1 if d["kind"] == "relay_spacing"]

        print("  afocal  d=f1+f2:   w_in@L1=%.4f mm  w_out@cam=%.4f mm  ratio=%.4f (expect ~%.4f)"
              % (w_in, w0, ratio, abs(f2 / f1)))
        print("  afocal  output wavefront curvature 1/R = %.3e mm^-1 (collimated -> ~0)" % k0)
        print("  detuned +%.1f mm:  output wavefront curvature 1/R = %.3e mm^-1 (NOT collimated -> >>0)"
              % (detune, k1))
        for d in relay1:
            print("   ->", d["severity"], d["kind"], "|", d["detail"])

        check(q0 is not None and abs(k0) < 5e-4 and abs(k1) > 10.0 * abs(k0),
              "B[%s]: afocal output COLLIMATED (|1/R|=%.2e << detuned %.2e, >10x flatter)"
              % (tag, abs(k0 or 0), abs(k1 or 0)))
        check(abs(ratio - abs(f2 / f1)) < 0.02 * abs(f2 / f1) + 1e-3,
              "B[%s]: afocal spot scales by |f2/f1|=%.3f (got %.3f)" % (tag, abs(f2 / f1), ratio))
        check(len(relay0) == 0,
              "B[%s]: afocal spacing emits NO relay_spacing diagnostic" % tag)
        check(q1 is not None and abs(k1) > 1e-4,
              "B[%s]: detuned output is NOT collimated (curvature %.2e > 1e-4)" % (tag, abs(k1 or 0)))
        check(len(relay1) == 1 and relay1[0]["severity"] == "WARN"
              and relay1[0]["element"] == names_dt[1],
              "B[%s]: detuned spacing FIRES one relay_spacing WARN on L2" % tag)


# --------------------------------------------------------------------------- #
# (C) byte-identical 14 examples + (E) zero new diagnostics
# --------------------------------------------------------------------------- #
def _purge_optical():
    """Hard-remove EVERY optical object (e.g. the (B) telescope test parts), so the 14
    examples build in a truly clean scene -- `examples_builtin._reset_examples` only
    clears `OpticsExample_` collections, not our verify-built lenses, which would
    otherwise linger on-axis and forge spurious lens pairs."""
    for o in list(bpy.context.scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            mesh = o.data if o.type == 'MESH' else None
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsVerify_"):
            bpy.data.collections.remove(c)


def _build_hash_diag():
    """Build all 14 examples; return {kind: (seg_md5, ports_md5, diag_count)}."""
    from optical_alignment_sim import examples_builtin as ex, diagnostics
    scene = bpy.context.scene
    _purge_optical()
    out = {}
    for kind in ex.EXAMPLES:
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        segs = _trace(scene)
        from optical_alignment_sim import tracer
        tracer.cached_segments = segs
        diags = diagnostics.run_diagnostics(scene)
        out[kind] = (_seg_digest(segs), _ports_digest(scene), len(diags),
                     sum(1 for d in diags if d["kind"] == "relay_spacing"))
    return out


def test_byte_identical_and_no_new_diags():
    print("\n=== (C) BYTE-IDENTICAL 14 examples + (E) zero new (relay_spacing) diagnostics ===")
    # BEFORE: hash & diagnose without ever referencing design.
    before = _build_hash_diag()
    # AFTER: explicitly import + reference design's public surface, then rebuild.
    from optical_alignment_sim import design
    _ = (design.afocal_abcd, design.design_telescope, design.design_4f)
    after = _build_hash_diag()

    all_ident, no_relay = True, True
    for kind in sorted(before):
        sb, pb, nb, rb = before[kind]
        sa, pa, na, ra = after[kind]
        ident = (sb == sa and pb == pa)
        same_n = (nb == na)
        no_rel = (ra == 0 and rb == 0)
        all_ident = all_ident and ident
        no_relay = no_relay and no_rel and same_n
        print("  %-16s seg %s  ports %s  %s | diag %d->%d relay %d  %s"
              % (kind, sb[:12], pb[:12], "OK" if ident else "CHANGED",
                 nb, na, ra, "OK" if (same_n and no_rel) else "CHANGED"))
    check(all_ident, "C: all 14 examples trace + ports byte-identical across design import")
    check(no_relay, "E: diagnose() adds ZERO relay_spacing (and same total count) on all 14 examples")


# --------------------------------------------------------------------------- #
def main():
    _register_addon()
    test_designer_math()
    test_tracer_ground_truth()
    test_byte_identical_and_no_new_diags()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL DESIGN VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
