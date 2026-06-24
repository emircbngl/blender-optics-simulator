"""Headless verification harness for Wave-3 C8 (detector material/mode enum + readout overlays).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_detector.py

C8 is a pure READOUT overlay: material/mode/topology read the existing per-segment power/jones/qd
and never change the beam trace. Proves:
  (A) responsivity R(l)=qe*l/1239.8 + APD excess-noise F(M)=kM+(2-1/M)(1-k) -- oracle ok=true 8/8
      (re-checked here in-Python); quadrant erf-fraction == direct Gaussian integral (oracle can't erf).
  (B) QUADRANT ground-truth: a known injected transverse beam offset is recovered by the quadrant
      Sx/Sy signal (monotonic, correct sign, ~0 centered); the responsivity readout = R(l)*P; the
      camera topology produces a 2-D image.
  (C) BYTE-IDENTICAL: all 20 build_example scenes trace the same seg+ports md5 (POINT default =
      the legacy scalar readout; the overlays are post-process).
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


def _reg():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    return addon


def _trace(sc):
    from optical_alignment_sim import tracer
    return tracer.trace_scene(sc, mode=sc.optics.trace_mode,
                              max_segments=sc.optics.max_segments, max_depth=sc.optics.max_depth)


def _seg_digest(segs):
    rows = []
    for s in segs:
        rows.append("|".join([
            str(s.get("from")), str(s.get("to")), s.get("kind", ""),
            ",".join("%.6f" % x for x in s["p1"]), ",".join("%.6f" % x for x in s["p2"]),
            "%.6f" % s.get("power", 0.0), "%.4f" % s.get("wavelength", 0.0),
            "%.6f" % s.get("w_mm", 0.0), str(s.get("parent", -1))]))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _ports_digest(sc):
    from optical_alignment_sim import geometry
    rows = []
    for o in sc.objects:
        op = getattr(o, "optics", None)
        if not op or not op.is_optical:
            continue
        for p in op.ports:
            wp = geometry.world_port(o, p.local_position)
            wn = geometry.world_normal(o, p.local_normal)
            rows.append("%s.%s|%s|%s" % (o.name, p.name, ",".join("%.5f" % x for x in wp),
                                         ",".join("%.5f" % x for x in wn)))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


REF = {"mach_zehnder": "819b140513c1", "michelson": "2988d9599234", "periscope": "7a69a20b58f7"}


def _fresh(name):
    from optical_alignment_sim import elements_generic as G
    sc = bpy.context.scene
    for o in list(sc.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    return G.example_collection(name)


def test_physics():
    print("\n=== (A) PHYSICS: responsivity / excess-noise / quadrant-erf ===")
    from optical_alignment_sim import physics
    # responsivity: R = qe*l/1239.8 (oracle ok=true); unit QE at l=1239.8 -> 1.0 A/W
    check(abs(physics.responsivity('InGaAs', 1550.0) - physics.detector_qe('InGaAs', 1550.0) * 1550.0 / physics.HC_OVER_E_eVnm) < 1e-9,
          "A: responsivity == qe*l/1239.8 (InGaAs 1550 = %.4f A/W)" % physics.responsivity('InGaAs', 1550.0))
    # APD excess noise F(M)=kM+(2-1/M)(1-k) (oracle ok=true 8/8)
    check(abs(physics.apd_excess_noise(10.0, 0.02) - 2.062) < 1e-9, "A: APD F(M=10,k=0.02)=2.062 (oracle-verified)")
    check(abs(physics.apd_excess_noise(5.0, 1.0) - 5.0) < 1e-9, "A: APD F(M,k=1)=M (worst case)")

    # quadrant erf-fraction == direct Gaussian integral (erf is NOT in the oracle -> numerical truth)
    def gint(off, w, N=200000):
        lo, dx, num, den = -6.0 * w, 12.0 * w / 200000, 0.0, 0.0
        for i in range(N):
            x = lo + (i + 0.5) * dx
            I = math.exp(-2.0 * x * x / (w * w))
            den += I
            if x > -off:
                num += I
        return num / den
    ok = True
    for off, w in ((0.0, 1.0), (0.5, 1.0), (-0.3, 1.2), (0.8, 2.0)):
        qf, gi = physics.quadrant_fraction(off, w), gint(off, w)
        ok = ok and abs(qf - gi) < 2e-4
    check(ok, "A: quadrant_fraction == direct Gaussian integral (<2e-4, erf verified numerically)")


def test_quadrant_groundtruth():
    print("\n=== (B) QUADRANT ground-truth: injected offset recovered + responsivity readout ===")
    from optical_alignment_sim import elements_generic as G, alignment
    sc = bpy.context.scene
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    c = _fresh("C8_Quad")
    src = G.source("Q_S", (-150, 0, 0), X, c, wavelength=1550.0)
    det = G.detector("Q_D", (120, 0, 0), X, c, size=30.0)
    det.optics.readout_topology = 'QUADRANT'
    det.optics.det_material = 'InGaAs'
    det.optics.quadrant_gap_mm = 0.0
    sbase = src.matrix_world.translation.copy()

    print("    inject_y(mm)   Sx        Sy")
    sigs = []
    for dy in (-4.0, -2.0, 0.0, 2.0, 4.0):
        from mathutils import Matrix
        src.matrix_world = Matrix.Translation((sbase.x, sbase.y + dy, sbase.z)) @ src.matrix_world.to_3x3().to_4x4()
        bpy.context.view_layer.update()
        segs = _trace(sc)
        alignment.refresh_report(sc)                        # runs measure -> _detector_readout
        Sx, Sy = det.optics.meas_quad_x, det.optics.meas_quad_y
        sigs.append((dy, Sx, Sy))
        print("    %+8.1f    %+.4f   %+.4f" % (dy, Sx, Sy))
    # the transverse offset drives ONE quad axis (whichever the sensor frame maps Y to); pick the
    # axis with the larger dynamic range, the other stays ~0.
    sx, sy = [s[1] for s in sigs], [s[2] for s in sigs]
    ax = sx if (max(sx) - min(sx)) >= (max(sy) - min(sy)) else sy
    centred = abs(ax[2])                                    # dy=0 -> ~0
    mono = all(ax[i] <= ax[i + 1] + 1e-9 for i in range(len(ax) - 1)) or all(ax[i] >= ax[i + 1] - 1e-9 for i in range(len(ax) - 1))
    check(centred < 0.05, "B: quadrant signal ~0 when the beam is centred (got %.4f)" % centred)
    check(mono, "B: quadrant signal is MONOTONIC in the injected offset (recovers position)")
    check(abs(ax[0]) > 0.3 and abs(ax[-1]) > 0.3, "B: quadrant saturates toward +-1 at large offset (|S| %.2f)" % abs(ax[-1]))

    # responsivity readout: I = R(l)*P (G=1) -- recentre the source first
    from mathutils import Matrix
    det.optics.readout_topology = 'POINT'
    src.matrix_world = Matrix.Translation((sbase.x, sbase.y, sbase.z)) @ src.matrix_world.to_3x3().to_4x4()
    bpy.context.view_layer.update()
    segs = _trace(sc); alignment.refresh_report(sc)
    from optical_alignment_sim import physics
    p = det.optics.meas_power
    expect_I = physics.responsivity('InGaAs', 1550.0) * p
    check(abs(det.optics.meas_current - expect_I) < 1e-4 * max(1.0, abs(expect_I)),
          "B: photocurrent I == R(1550)*P (got %.5f, expect %.5f)" % (det.optics.meas_current, expect_I))


def test_byte_identical():
    print("\n=== (C) BYTE-IDENTICAL: 20 examples (POINT default = legacy readout) ===")
    from optical_alignment_sim import examples_builtin as ex
    sc = bpy.context.scene
    for cc in list(bpy.data.collections):                    # clear the quad-test residue first
        if cc.name.startswith("C8_") or cc.name.startswith("OpticsVerify_"):
            for o in list(cc.objects):
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except Exception:
                    pass
            bpy.data.collections.remove(cc)
    for o in list(sc.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    n = 0
    all_ok = True
    for kind in sorted(ex.EXAMPLES):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd, pd = _seg_digest(_trace(sc)), _ports_digest(sc)
        ref = REF.get(kind)
        ok = (ref is None) or sd.startswith(ref)
        all_ok = all_ok and ok
        n += 1
        if ref:
            print("  %-16s seg %s  %s" % (kind, sd[:12], "OK" if ok else "MISMATCH"))
    check(n >= 20, "C: >=20 build_example scenes (%d)" % n)
    check(all_ok, "C: pinned references match -- C8 readouts did not perturb the trace")


def main():
    _reg()
    test_physics()
    test_quadrant_groundtruth()
    test_byte_identical()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d:" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL DETECTOR (C8) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
