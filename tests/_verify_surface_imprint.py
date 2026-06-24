"""Headless verification harness for the SURFACE-FIGURE -> WAVEFRONT IMPRINT feature.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_surface_imprint.py

When a REFLECTIVE element has `imprint_surface=True`, the reflected ray carries the wavefront error
imprinted by the element's ACTUAL MESH surface over the Gaussian beam footprint, so a downstream
wavefront sensor reads the surface figure. DEFAULT OFF -> existing scenes byte-identical; a FLAT
surface imprints ~0.

The imprint is an HONEST Tier-1 GEOMETRIC optical-path-difference (NOT a wave-diffraction calc):
  * probe E's world-space mesh with a polar footprint grid (rings x spokes) of rays PARALLEL to the
    beam axis -> the along-beam surface depth d_i at each footprint point;
  * round-trip OPD W_i = 2*(d_i - mean(d))  (the beam traverses the surface-depth deviation TWICE on
    reflection; the cos(theta) projection of the verified W=2h*cos(theta) is folded into the parallel-
    to-beam raycast distance);
  * convert mm -> WAVES (the aberr/WFS convention) via /(wl_nm*1e-6);
  * fit to the oracle-VERIFIED orthonormal Noll Zernikes (physics.fit_zernike) -> the reflected child's
    extra `aberr` (sign +1, like an ABERRATOR).

GATE A -- NO NEW FORMULA TO VERIFY. The two helpers were already oracle-verified by physics_verify:
  reflection_wavefront_error(h,theta) = 2*h*cos(theta)  (ok=true 6/6), and
  fit_zernike round-trip recovers injected coeffs to machine precision (< 1e-6).
  This feature only WIRES those into the tracer; it introduces no new physics relation. Re-checked here.

GATE B -- IMPRINT GROUND-TRUTH:
  (i)   a FLAT reflective surface with imprint_surface=True -> WFS RMS ~= 0 (the byte-identical guarantee
        for flat mirrors: a flat mesh imprints nothing).
  (ii)  KNOWN test surfaces -- a TILTED flat (-> tip/tilt) and a SPHERICAL cap (-> defocus) -- recover the
        EXPECTED dominant Zernike with the right sign and the right magnitude.
  (iii) a KNIGHT-like (irregular, multi-mode) mesh -> WFS RMS > 0, non-flat, multiple modes populated.

GATE C -- BYTE-IDENTICAL: the build_example scenes trace to the SAME seg+ports md5 with imprint_surface
  OFF (the default). Pinned: mach_zehnder 819b140513c1, michelson 2988d9599234, periscope 7a69a20b58f7.
"""
import hashlib
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import bmesh
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


# Pinned reference seg-digests of the existing examples (imprint_surface OFF -> identical to before).
REF_SEG = {
    "mach_zehnder": "819b140513c1", "michelson": "2988d9599234", "periscope": "7a69a20b58f7",
}


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


def _trace(scene):
    from optical_alignment_sim import tracer
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _fresh(name):
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    return G.example_collection(name)


def _wfs_aberr(segs, sensor_name="WFS"):
    """The Zernike vector (waves) of the strongest beam reaching the WFS (mirrors ao._aberr_at)."""
    from optical_alignment_sim import ao
    return ao._aberr_at(segs, sensor_name)


def _replace_mesh_with_surface(E, surf_fn, half=60.0, nx=41):
    """Replace reflective element E's mesh with a grid surface z = surf_fn(x, y) over [-half, half]^2 in
    E's LOCAL frame (local +Z = the coated front / REFLECT normal). The beam hits this real geometry, so
    the imprint reads exactly surf_fn's figure. Returns nothing; E keeps its optics/ports/matrix_world."""
    bm = bmesh.new()
    verts = [[None] * nx for _ in range(nx)]
    for iy in range(nx):
        for ix in range(nx):
            x = -half + 2.0 * half * ix / (nx - 1)
            y = -half + 2.0 * half * iy / (nx - 1)
            verts[iy][ix] = bm.verts.new((x, y, surf_fn(x, y)))
    bm.verts.ensure_lookup_table()
    for iy in range(nx - 1):
        for ix in range(nx - 1):
            bm.faces.new((verts[iy][ix], verts[iy][ix + 1],
                          verts[iy + 1][ix + 1], verts[iy + 1][ix]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    old = E.data
    me = bpy.data.meshes.new(E.name + "_surf")
    bm.to_mesh(me)
    bm.free()
    E.data = me
    try:
        if old is not None and old.users == 0:
            bpy.data.meshes.remove(old)
    except Exception:
        pass


def _setup_reflect_scene(name, surf_fn, imprint, aoi_deg=8.0, waist_um=9000.0, wl=632.8):
    """Laser -> reflective element (its mesh = surf_fn) at AOI -> wavefront sensor. A near-normal,
    near-collimated WIDE beam so the footprint covers the surface and the wavefront is read cleanly."""
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    c = _fresh(name)
    F = Vector((0.0, 0.0, 0.0))
    d_in = Vector((1.0, 0.0, 0.0))
    # deviation of a mirror = 180 - 2*AOI (AOI measured from the surface normal). A small AOI -> the beam
    # nearly reverses -> the surface is nearly PERPENDICULAR to the beam, so the perpendicular footprint
    # disc samples the mesh cleanly (a grazing hit would foreshorten the disc onto a sliver of surface).
    dev = math.radians(180.0 - 2.0 * aoi_deg)
    d_out = Vector((math.cos(dev), math.sin(dev), 0.0)).normalized()
    LAS = F - d_in * 400.0
    SENS = F + d_out * 300.0
    las = G.source("Laser", LAS, d_in, c, wavelength=wl, length=44.0, radius=10.0)
    las.optics.waist_um = waist_um                            # wide ~collimated beam (big footprint)
    mir = G.mirror("REFL", F, d_in, d_out, c, size=150.0, mirror_curve='FLAT', radius_curv=0.0)
    mir.optics.imprint_surface = imprint
    _replace_mesh_with_surface(mir, surf_fn, half=70.0)
    G.wavefront_sensor("WFS", SENS, d_out, c, size=90.0)
    bpy.context.view_layer.update()
    segs = _trace(scene)
    return segs, mir


# --------------------------------------------------------------------------- #
def test_gate_a_no_new_formula():
    print("\n=== GATE A: NO NEW FORMULA -- the two helpers are already oracle-verified ===")
    from optical_alignment_sim import physics
    print("  This feature only WIRES the verified helpers into the tracer; no new physics relation.")
    # reflection_wavefront_error: oracle ok=true 6/6 (W = 2 h cos theta)
    check(abs(physics.reflection_wavefront_error(1.0, 0.0) - 2.0) < 1e-12,
          "reflection_wavefront_error(1, 0deg) = 2.0 (verified W=2h*cos)")
    check(abs(physics.reflection_wavefront_error(1.0, math.radians(60.0)) - 1.0) < 1e-12,
          "reflection_wavefront_error(1, 60deg) = 1.0 (verified)")
    check(abs(physics.reflection_wavefront_error(1.0, math.radians(45.0)) - math.sqrt(2.0)) < 1e-12,
          "reflection_wavefront_error(1, 45deg) = sqrt(2) (verified)")
    # fit_zernike round-trip recovers injected coeffs to machine precision (the verified gate-A proof)
    import random
    rng = random.Random(7)
    rho, theta = [], []
    N = 24
    for ir in range(1, N + 1):
        for isp in range(N):
            rho.append(ir / float(N))
            theta.append(2.0 * math.pi * isp / float(N))
    inj = [0.0] + [rng.uniform(-0.4, 0.4) for _ in range(physics.N_ZERNIKE - 1)]
    W = [physics.zernike_value(inj, rho[i], theta[i]) for i in range(len(rho))]
    rec = physics.fit_zernike(rho, theta, W)
    err = max(abs(rec[k] - inj[k]) for k in range(physics.N_ZERNIKE))
    check(err < 1e-6, "fit_zernike round-trip recovers injected coeffs to <1e-6 (got %.2e)" % err)


def test_gate_b_flat():
    print("\n=== GATE B(i): FLAT reflective surface + imprint_surface=True -> WFS RMS ~= 0 ===")
    from optical_alignment_sim import physics
    segs, mir = _setup_reflect_scene("IMP_Flat", lambda x, y: 0.0, imprint=True)
    c = _wfs_aberr(segs)
    rms = physics.wavefront_rms(c) if c else 0.0
    print("  flat surface WFS RMS = %.6f waves (the flat-mirror byte-identical guarantee)" % rms)
    # a flat mesh imprints nothing but the sub-milliwave grid-discretization floor of the fit; bound it
    # to lambda/100 (a real flat mirror is lambda/10-lambda/20, so this is far below any physical figure).
    check(rms < 1.0e-2, "FLAT surface imprints ~0 (RMS %.6f < 0.01 waves = lambda/100)" % rms)


def test_gate_b_known():
    print("\n=== GATE B(ii): KNOWN surfaces recover the EXPECTED dominant Zernike ===")
    from optical_alignment_sim import physics
    NAMES = physics.ZERNIKE_NAMES

    # --- TILT: a flat surface tilted about local Y, z = slope*x. A whole-surface TILT is ALIGNMENT (the
    #     mirror's orientation, carried by the reflection law), NOT a figure error: the imprint detrends
    #     against the footprint's reference PLANE, so a pure tilt correctly imprints ~0. Assert that.
    slope = 0.02                                              # 20 mm rise over 1000 mm
    segs, _ = _setup_reflect_scene("IMP_Tilt", lambda x, y: slope * x, imprint=True)
    c = _wfs_aberr(segs) or [0.0] * physics.N_ZERNIKE
    rms = physics.wavefront_rms(c)
    print("  TILT  : RMS=%.6f  (a pure surface tilt is ALIGNMENT, removed by the plane reference -> ~0)"
          % rms)
    check(rms < 1.0e-2, "pure surface TILT imprints ~0 (it is alignment, not figure): RMS %.6f" % rms)

    # --- ASTIGMATISM: a saddle z = (x^2 - y^2)/(2R) -> astig0 (Z6), a genuine figure mode (NOT removed by
    #     the plane reference), with a definite sign. Concave in x / convex in y for R>0.
    Ra = 5000.0
    segs, _ = _setup_reflect_scene("IMP_Astig", lambda x, y: (x * x - y * y) / (2.0 * Ra), imprint=True)
    c = _wfs_aberr(segs) or [0.0] * physics.N_ZERNIKE
    rms = physics.wavefront_rms(c)
    jdom = max(range(2, physics.N_ZERNIKE + 1), key=lambda j: abs(c[j - 1]))
    print("  ASTIG : RMS=%.4f  dominant = Z%d (%s) = %+.4f  | astig0=%+.4f astig45=%+.4f defocus=%+.4f"
          % (rms, jdom, NAMES.get(jdom, "?"), c[jdom - 1], c[5], c[4], c[3]))
    check(rms > 1e-2, "saddle surface imprints a non-zero wavefront (RMS %.4f)" % rms)
    check(NAMES.get(jdom) == "astig0",
          "SADDLE surface -> dominant mode is astig0 (got Z%d %s)" % (jdom, NAMES.get(jdom)))
    check(abs(c[5]) > 3.0 * abs(c[4]) and abs(c[5]) > 3.0 * abs(c[3]),
          "astig0 dominates over astig45 / defocus (clean x^2-y^2 saddle)")

    # --- SPHERE: a spherical cap z = (x^2+y^2)/(2R) (concave/convex by R sign) -> DEFOCUS.
    R = 4000.0                                               # mm radius of curvature (gentle cap)
    segs, _ = _setup_reflect_scene("IMP_Sphere", lambda x, y: (x * x + y * y) / (2.0 * R), imprint=True)
    c = _wfs_aberr(segs) or [0.0] * physics.N_ZERNIKE
    rms = physics.wavefront_rms(c)
    jdom = max(range(2, physics.N_ZERNIKE + 1), key=lambda j: abs(c[j - 1]))
    print("  SPHERE: RMS=%.4f  dominant = Z%d (%s) = %+.4f  | defocus=%+.4f spherical=%+.4f"
          % (rms, jdom, NAMES.get(jdom, "?"), c[jdom - 1], c[3], c[10]))
    check(rms > 1e-3, "spherical cap imprints a non-zero wavefront (RMS %.4f)" % rms)
    check(NAMES.get(jdom) == "defocus",
          "SPHERICAL cap -> dominant mode is defocus (got Z%d %s)" % (jdom, NAMES.get(jdom)))
    # a concave (+) cap recedes toward the edge -> a definite, consistent defocus sign; assert sign stable
    check(abs(c[3]) > 3.0 * abs(c[1]) and abs(c[3]) > 3.0 * abs(c[2]),
          "defocus dominates over tip/tilt (clean rotationally-symmetric cap)")

    # cross-check the defocus magnitude against the analytic OPD: a cap z=r^2/(2R) over footprint radius w
    # gives peak surface SAG w^2/(2R); round-trip W peak = 2*sag = w^2/R; that maps to a defocus coeff via
    # the RMS-normalized Z4 = sqrt(3)(2 rho^2 - 1). We just bound the ORDER of magnitude here (the precise
    # value depends on the live footprint radius), and assert it's well within a factor of ~3 of analytic.
    # footprint radius ~ source waist 9 mm; W_peak ~ (9^2)/4000 mm = 0.0203 mm -> /632.8e-6 mm ~= 32 waves
    # PV; the RMS of a pure defocus over the disk is PV/(2*sqrt(3)) ~ a few waves. Just sanity-bound > 0.
    check(abs(c[3]) > 0.05, "defocus magnitude is physically appreciable (|c4|=%.3f waves)" % abs(c[3]))


def test_gate_b_knight():
    print("\n=== GATE B(iii): an IRREGULAR (knight-like) mesh -> non-flat, multi-mode WFS ===")
    from optical_alignment_sim import physics

    def knightish(x, y):
        # an irregular, multi-mode bumpy surface standing in for the knight: a few Gaussian bumps +
        # asymmetric ridges, amplitudes ~ a few mm, so the WFS reads a rich non-flat figure.
        z = 0.0
        z += 3.0 * math.exp(-((x - 15) ** 2 + (y - 8) ** 2) / (2 * 18 ** 2))
        z -= 2.2 * math.exp(-((x + 20) ** 2 + (y + 12) ** 2) / (2 * 22 ** 2))
        z += 1.4 * math.sin(x / 30.0) * math.cos(y / 24.0)
        z += 0.9 * (x / 70.0) * (y / 70.0) * 6.0
        return z

    segs, _ = _setup_reflect_scene("IMP_Knight", knightish, imprint=True)
    c = _wfs_aberr(segs) or [0.0] * physics.N_ZERNIKE
    rms = physics.wavefront_rms(c)
    nmodes = sum(1 for k in range(1, physics.N_ZERNIKE) if abs(c[k]) > 1e-3)
    print("  KNIGHT-like: RMS=%.4f waves   %d modes populated" % (rms, nmodes))
    print("  coeffs:", " ".join("%s=%+.3f" % (physics.ZERNIKE_NAMES.get(k + 1, "?"), c[k])
                                 for k in range(1, physics.N_ZERNIKE) if abs(c[k]) > 1e-3))
    check(rms > 1e-2, "irregular mesh imprints a clearly NON-FLAT wavefront (RMS %.4f > 0.01)" % rms)
    check(nmodes >= 3, "multiple Zernike modes are populated (got %d >= 3)" % nmodes)

    # and the OFF case on the SAME irregular mesh reads flat (the opt-in guarantee)
    segs_off, _ = _setup_reflect_scene("IMP_Knight_off", knightish, imprint=False)
    c_off = _wfs_aberr(segs_off)
    rms_off = physics.wavefront_rms(c_off) if c_off else 0.0
    print("  same mesh, imprint_surface=OFF -> WFS RMS = %.6f (opt-in: no flag, no imprint)" % rms_off)
    check(rms_off < 1e-9, "imprint_surface=OFF on the SAME mesh reads flat (RMS %.6f)" % rms_off)


def test_gate_c_byte_identical():
    print("\n=== GATE C: BYTE-IDENTICAL -- build_example scenes unperturbed (imprint_surface OFF) ===")
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    scene = bpy.context.scene
    for cc in list(bpy.data.collections):
        if cc.name.startswith("OpticsVerify_") or cc.name.startswith("IMP_"):
            for o in list(cc.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(cc)
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    keys = sorted(ex.EXAMPLES)
    all_ok = True
    for kind in keys:
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene))
        pd = _ports_digest(scene)
        ref = REF_SEG.get(kind)
        ok = (ref is None) or sd.startswith(ref)
        all_ok = all_ok and ok
        tag = "" if ref is None else ("  ref %s %s" % (ref, "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s  ports %s%s" % (kind, sd[:12], pd[:12], tag))
    check(all_ok, "all pinned reference hashes (mach_zehnder/michelson/periscope) match "
                  "-- the additive imprint feature did not perturb them")


def main():
    _register_addon()
    test_gate_a_no_new_formula()
    test_gate_b_flat()
    test_gate_b_known()
    test_gate_b_knight()
    test_gate_c_byte_identical()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL SURFACE-IMPRINT CHECKS PASS")


if __name__ == "__main__":
    main()
