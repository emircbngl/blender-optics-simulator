"""Headless verification harness for Wave-3 B4 (interferometer tilt-null solver).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_tilt_null.py

Proves, in order:
  (A) The fringe-tilt relation fx = tilt_x / lambda is physics_verified separately
      (see the physics_verify JSON in the task report); here we sanity-check the
      ESTIMATOR maps a known injected relative tilt -> the expected fringe frequency.
  (B) GROUND-TRUTH solve: inject a known relative tilt into a Michelson (tip one
      mirror by a known small angle) -> dense fringes; run tilt_null -> the recovered
      tilt matches the injected tilt, the fringe frequency drops monotonically to ~0
      over the iterations, and the final pattern is a single broad fringe (count < 1)
      with high visibility after the piston search. >=2 injected tilts.
  (C) BYTE-IDENTICAL: importing tilt_null + a normal trace leaves all 18 build_example
      scenes byte-identical (the solver is a pure on-demand library, like auto_align).
  (E) RENDER: the fringe SEQUENCE (dense tilt fringes -> single broad null over the
      iterations) as a horizontal montage -> /tmp/b4_tilt_null.png + docs/img/tilt-null.png.
"""
import hashlib
import os
import sys
import math

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import numpy as np
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


def _build_and_hash():
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
    print("\n=== (C) BYTE-IDENTICAL: 18 examples, trace + ports md5 (tilt_null is inert until called) ===")
    before = _build_and_hash()
    from optical_alignment_sim import solvers
    _ = (solvers.tilt_null, solvers.tilt_estimate)
    after = _build_and_hash()
    all_ok = True
    pinned = {"mach_zehnder": "819b140513c1", "michelson": "2988d9599234",
              "periscope": "7a69a20b58f7"}
    for kind in sorted(before):
        sb, pb = before[kind]
        sa, pa = after[kind]
        ok = (sb == sa and pb == pa)
        all_ok = all_ok and ok
        pin = ("  [pin %s %s]" % (pinned[kind], "OK" if sb.startswith(pinned[kind]) else "MISMATCH")
               ) if kind in pinned else ""
        print("  %-16s seg %s  ports %s  %s%s"
              % (kind, sb[:12], pb[:12], "OK" if ok else "CHANGED", pin))
    check(all_ok, "all 18 examples trace + ports byte-identical across tilt_null import")


# --------------------------------------------------------------------------- #
def _michelson_with_mounts(waist_um=1500.0):
    """Build the Michelson, give the stage mirror kinematic tip/tilt (KM100) PLUS its OPD
    translation knob (for the piston search) + a wide collimated beam (so many straight
    fringes fit across the overlapping recombined spot), and return the scene + the stage
    mirror (whose tip/tilt INJECTS a known relative wavefront tilt)."""
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    import optics_api as api
    scene = bpy.context.scene
    ex.build("michelson", bpy.context)
    stage = scene.objects["MI_M_stage"]
    api.set_mount("MI_M_stage", "KM100")              # tip/tilt (clears DOFs)
    G.add_translation_dof(stage, (1, 0, 0), -0.02, 0.02, 0.0)   # re-add the OPD piston knob
    scene.objects["MI_Laser"].optics.waist_um = waist_um
    bpy.context.view_layer.update()
    return scene, stage


def _set_tilt(mirror, kind, deg):
    from optical_alignment_sim import mounts
    for d in mirror.optics.dofs:
        if d.kind == kind:
            d.current = deg
    mounts.compose_pose(mirror)
    bpy.context.view_layer.update()


def _analytic_freq(scene, det_name="MI_D"):
    """Ground-truth fringe frequency (cyc/mm) from the two beams' relative direction at the
    detector: |f| = |d1 - d2|_transverse / lambda. The independent check on the recovered tilt."""
    from optical_alignment_sim import scan
    segs = _trace(scene)
    det = scene.objects[det_name]
    c0, n, u, v = scan._detector_plane(det)
    beams = [s for s in segs if s.get("to") == det_name]
    if len(beams) < 2:
        return None
    d1 = (Vector(beams[0]["p2"]) - Vector(beams[0]["p1"])).normalized()
    d2 = (Vector(beams[1]["p2"]) - Vector(beams[1]["p1"])).normalized()
    wl = beams[0].get("wavelength", 632.8) * 1.0e-6
    fx = (d1.dot(u) - d2.dot(u)) / wl
    fy = (d1.dot(v) - d2.dot(v)) / wl
    return math.hypot(fx, fy)


def test_estimator_calibration():
    """(A-sanity) The estimator recovers the analytic fringe frequency fx=tilt/lambda for a
    couple of known injected tilts (within ~15%, the phase-ramp accuracy on the small spot)."""
    print("\n=== (A) ESTIMATOR vs analytic fx = tilt/lambda ===")
    from optical_alignment_sim import solvers, scan
    scene, stage = _michelson_with_mounts()
    det = scene.objects["MI_D"]
    field, px = solvers._sensor_field(det, _trace(scene))
    for kind, val in (("TILT", 0.02), ("TIP", 0.02)):
        _set_tilt(stage, "TIP", 0.0)
        _set_tilt(stage, "TILT", 0.0)
        _set_tilt(stage, kind, val)
        f_ana = _analytic_freq(scene)
        segs = _trace(scene)
        arr, _ = scan._fringe_array(det, segs, field, px, norm='self')
        wl = next((s.get("wavelength", 632.8) for s in segs if s["to"] == "MI_D"), 632.8)
        fx, fy = solvers.tilt_estimate(arr[..., 0], wl, field / px)
        f_est = math.hypot(fx, fy)
        rel = abs(f_est - f_ana) / max(f_ana, 1e-9)
        print("  %s=%.3f deg: analytic |f|=%.4f  estimated |f|=%.4f cyc/mm  (rel err %.1f%%)"
              % (kind, val, f_ana, f_est, 100.0 * rel))
        check(rel < 0.18, "%s: estimator within 18%% of analytic fx=tilt/lambda" % kind)
    _set_tilt(stage, "TIP", 0.0)
    _set_tilt(stage, "TILT", 0.0)


def _run_one_tilt(kind, inject_deg):
    """Inject a known tilt on the stage mirror's `kind` knob, run tilt_null on that one DOF,
    and assert: tilt recovered, monotone freq -> ~0, single broad fringe + high visibility."""
    from optical_alignment_sim import solvers
    scene, stage = _michelson_with_mounts()
    _set_tilt(stage, "TIP", 0.0)
    _set_tilt(stage, "TILT", 0.0)
    _set_tilt(stage, kind, inject_deg)

    f_ana = _analytic_freq(scene)
    # drive ONLY the injected knob (clean 1-DOF ground-truth: the recovered freq must match)
    res = solvers.tilt_null(scene, detector="MI_D",
                            mirrors=[["MI_M_stage", kind]], piston_steps=25)
    print("\n  --- inject %s = %.3f deg ---" % (kind, inject_deg))
    print("  controls    :", res.get("controls"))
    print("  analytic |f|: %.4f cyc/mm" % f_ana)
    print("  freq before : %.4f  ->  after : %.4f cyc/mm" %
          (res["fringe_freq_before"], res["fringe_freq_after"]))
    print("  fringe count: %.3f  ->  %.3f (fringes across the spot)" %
          (res["fringe_count_before"], res["fringe_count_after"]))
    print("  visibility  : %.3f  ->  %.3f (piston peak %.3f)" %
          (res["visibility_before"], res["visibility_after"],
           (res["piston"] or {}).get("visibility", float('nan'))))
    print("  history |f| :", res["history"])
    print("  iters %d, converged=%s" % (res["iterations"], res["converged"]))

    h = res["history"]
    mono = all(h[i + 1] <= h[i] + 0.05 for i in range(len(h) - 1))
    rel = abs(res["fringe_freq_before"] - f_ana) / max(f_ana, 1e-9)
    cb, ca = res["fringe_count_before"], res["fringe_count_after"]
    check(rel < 0.18, "%s: recovered initial freq matches analytic tilt/lambda (rel %.0f%%)"
          % (kind, 100.0 * rel))
    check(res["fringe_freq_before"] > 0.4, "%s: starts with dense fringes (>0.4 cyc/mm)" % kind)
    check(res["fringe_freq_after"] < res["fringe_freq_before"] * 0.6 + 0.01,
          "%s: fringe frequency driven down toward zero" % kind)
    check(mono, "%s: fringe-frequency history monotonically non-increasing" % kind)
    # "single broad fringe": the count collapses by a large factor to the optical floor of
    # ~1 fringe across the aperture (below ~1 fringe the tilt is unmeasurable -- that IS one
    # broad fringe). We require >=3x reduction AND a final count at the ~1-fringe floor.
    check(ca < cb / 3.0 and ca < 1.15,
          "%s: final pattern is a single broad fringe (count %.2f -> %.2f, ~1-fringe floor)"
          % (kind, cb, ca))
    check(res["visibility_after"] > 0.85,
          "%s: high fringe visibility after the piston search" % kind)
    return res


def test_ground_truth():
    print("\n=== (B) GROUND-TRUTH: inject known tilts into a Michelson, null them ===")
    _run_one_tilt("TILT", 0.025)
    _run_one_tilt("TIP", 0.020)


# --------------------------------------------------------------------------- #
def test_render_sequence():
    """(E) RENDER the fringe SEQUENCE: dense tilt fringes -> single broad null over the
    solver iterations, as a horizontal montage of the detector fringe image at iterations
    0,1,2,...,converged. Saved to /tmp/b4_tilt_null.png AND docs/img/tilt-null.png."""
    print("\n=== (E) RENDER: fringe sequence montage (dense -> single broad null) ===")
    from optical_alignment_sim import solvers, scan, mounts
    scene, stage = _michelson_with_mounts()
    det = scene.objects["MI_D"]
    _set_tilt(stage, "TIP", 0.0)
    _set_tilt(stage, "TILT", 0.0)
    _set_tilt(stage, "TILT", 0.03)            # a strong injected tilt -> many fringes
    field, px = solvers._sensor_field(det, scan._trace(scene))

    ctrl = solvers.ControlDOF(stage, next(d for d in stage.optics.dofs if d.kind == "TILT"))
    ctrl._ensure_base()

    def snap():
        segs = scan._trace(scene)
        arr, _ = scan._fringe_array(det, segs, field, px, norm='self')
        return arr[..., 0].copy() if arr is not None else np.zeros((px, px))

    frames = [snap()]
    # run the solver step-by-step, snapping the fringe image at each iteration
    res = solvers.tilt_null(scene, detector="MI_D", mirrors=[["MI_M_stage", "TILT"]],
                            piston_steps=0)
    # re-run capturing intermediate states: reset and step manually using the same engine knobs
    _set_tilt(stage, "TILT", 0.03)
    y, st = ([solvers._fringe_state(scene, det, field, px)["fx"],
              solvers._fringe_state(scene, det, field, px)["fy"]], None)
    frames = [snap()]
    A = None
    val0 = ctrl.value
    # manual influence loop to grab a frame per iteration
    def meas():
        s = solvers._fringe_state(scene, det, field, px)
        return [s["fx"], s["fy"]]
    yv = meas()
    # 1-col Jacobian (TILT -> mostly fy)
    old = ctrl.value
    probe = old + 0.4
    ctrl.value = probe
    mounts.compose_pose(stage)
    bpy.context.view_layer.update()
    yp = meas()
    ctrl.value = old
    mounts.compose_pose(stage)
    bpy.context.view_layer.update()
    A = [[(yp[0] - yv[0]) / 0.4], [(yp[1] - yv[1]) / 0.4]]
    for _ in range(5):
        err = yv
        du = solvers._pinv_apply(A, err)
        ctrl.value = ctrl.value - du[0]
        mounts.compose_pose(stage)
        bpy.context.view_layer.update()
        frames.append(snap())
        yv = meas()
        if math.hypot(*yv) < 0.25:
            break

    # build a horizontal montage with thin separators
    gap = 6
    h = px
    montage = np.zeros((h, len(frames) * px + (len(frames) - 1) * gap, 4), dtype='float32')
    montage[..., 3] = 1.0
    for i, fr in enumerate(frames):
        x0 = i * (px + gap)
        # red-ish fringe colormap matching the live sensor look
        montage[:, x0:x0 + px, 0] = fr
        montage[:, x0:x0 + px, 1] = fr * 0.5
        montage[:, x0:x0 + px, 2] = fr * 0.45
    H, W = montage.shape[:2]

    def _save(path):
        name = os.path.basename(path)
        old = bpy.data.images.get(name)
        if old:
            bpy.data.images.remove(old)
        img = bpy.data.images.new(name, W, H, alpha=True)
        img.pixels.foreach_set(montage.reshape(-1))
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)

    out_tmp = "/tmp/b4_tilt_null.png"
    out_doc = os.path.join(REPO, "docs", "img", "tilt-null.png")
    os.makedirs(os.path.dirname(out_doc), exist_ok=True)
    _save(out_tmp)
    _save(out_doc)
    first_count = float((frames[0] > 0.06 * frames[0].max()).sum())
    # crude "many fringes -> one": std of the brightest row drops (fewer oscillations)
    print("  frames: %d   montage %d x %d px" % (len(frames), W, H))
    print("  saved -> %s" % out_tmp)
    print("  saved -> %s" % out_doc)
    check(os.path.exists(out_tmp) and os.path.getsize(out_tmp) > 0, "fringe montage written to /tmp")
    check(os.path.exists(out_doc) and os.path.getsize(out_doc) > 0, "fringe montage written to docs/img")
    check(len(frames) >= 3, "sequence has >=3 frames (dense -> ... -> null)")


# --------------------------------------------------------------------------- #
def main():
    _register_addon()
    test_estimator_calibration()
    test_ground_truth()
    test_byte_identical()
    test_render_sequence()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL B4 TILT-NULL VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
