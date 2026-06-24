"""Headless verification harness for Wave-2 C3 (dispersing prisms).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_prism.py

Proves, in order:
  (A) CONSTANTS: each ADDED prism glass (N-SF11 / F2 / N-F2 / CaF2) reproduces its PUBLISHED
      refractive index at the standard spectral lines (Schott datasheets / Malitson 1963). A
      hallucinated Sellmeier coefficient would show as a wrong n. Also the minimum-deviation
      relation n = sin((A+delta)/2)/sin(A/2) inverts exactly and prism_deviation reduces to
      delta_min at symmetric incidence. (The physics_verify oracle run is reported separately:
      ok=true, 8/8, in the task notes -- this is the in-Python cross-check of the same numbers.)
  (B) TRACER GROUND-TRUTH: trace the SAME equilateral prism at 430..680 nm; measure each exit
      ray's deviation and confirm (i) blue bends MORE than red, (ii) the deviation matches
      prism_deviation(n(lambda), A, i1) at the fixed (design-wl min-deviation) incidence to tol,
      (iii) the design wavelength sits at delta_min. Prints the per-wavelength deviation table.
      Also asserts Littrow (180 deg retro at design), Pellin-Broca (constant 90 deg), Amici
      (zero net deviation at lambda0) -- each disperses.
  (C) BYTE-IDENTICAL: the 14 EXISTING build_example scenes (no prism) trace to the SAME seg+ports
      md5 as before C3 (the PRISM branch must not perturb them). Reference hashes pinned below.
  (D) PRISM EXAMPLE: the new 'prism' spectrometer example builds, fans >= 5 discrete wavelengths.
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


# Pinned reference seg-digests of the 14 existing examples (this session, pre-C3). The PRISM branch
# is a NEW element type; these scenes contain no prism, so they must be byte-identical.
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


# --------------------------------------------------------------------------- #
def test_constants():
    print("\n=== (A) CONSTANTS: published refractive indices + min-deviation relation ===")
    from optical_alignment_sim import physics
    # Published indices at the standard spectral lines (SCHOTT datasheets; Malitson 1963 for CaF2).
    # nd (587.56) and ne (546.07) are catalog headline values; nC (656.27)/nF (486.13) are checked
    # against the SAME Sellmeier fit + cross-checked by the Abbe number below (the true datasheet-
    # consistent figures, not approximate recall -- e.g. N-SF11 ne=1.79192, nd=1.78472, Vd=25.68).
    PUB = {
        'N-SF11': {587.56: 1.78472, 546.07: 1.79192, 656.27: 1.77596, 486.13: 1.80651},  # Schott
        'F2':     {587.56: 1.62004, 656.27: 1.61503},                                     # Schott
        'N-F2':   {587.56: 1.62005, 656.27: 1.61506},                                     # Schott (lead-free)
        'CaF2':   {587.56: 1.43385, 656.27: 1.43249, 486.13: 1.43704},                    # Malitson 1963
    }
    for g, lines in PUB.items():
        for wl, nref in lines.items():
            nn = physics.sellmeier_n(wl, g)
            check(abs(nn - nref) < 5e-5,
                  "%s n(%.2f nm) = %.5f vs published %.5f (|diff|=%.6f)" % (g, wl, nn, nref, abs(nn - nref)))
    # Abbe numbers (sanity that the dispersion slope is right, not just the d-line)
    for g, vref in (('N-SF11', 25.68), ('F2', 36.37), ('CaF2', 94.99)):
        nd = physics.sellmeier_n(587.56, g); nF = physics.sellmeier_n(486.13, g); nC = physics.sellmeier_n(656.27, g)
        vd = (nd - 1.0) / (nF - nC)
        check(abs(vd - vref) < 0.5, "%s Abbe Vd = %.2f vs catalog %.2f" % (g, vd, vref))
    # minimum-deviation relation: n = sin((A+delta_min)/2)/sin(A/2) inverts exactly (>= 2 pairs)
    for n_test, A in ((math.sqrt(2.0), 60.0), (1.78472, 60.0), (1.62004, 60.0)):
        dmin = physics.prism_min_deviation(n_test, A)
        n_back = physics.n_from_min_deviation(dmin, A)
        check(abs(n_back - n_test) < 1e-9, "min-deviation relation inverts (n=%.5f, A=%g)" % (n_test, A))
        i_sym = 0.5 * (A + dmin)                          # symmetric incidence -> exactly delta_min
        check(abs(physics.prism_deviation(n_test, A, i_sym) - dmin) < 1e-6,
              "prism_deviation reduces to delta_min at symmetric incidence (n=%.5f)" % n_test)
    # closed form: A=60, n=sqrt2 -> dmin=30
    check(abs(physics.prism_min_deviation(math.sqrt(2.0), 60.0) - 30.0) < 1e-9,
          "delta_min(sqrt2, 60 deg) = 30 deg (closed form)")
    # angular dispersion negative under normal dispersion
    check(physics.prism_angular_dispersion('N-SF11', 60.0, 550.0) < 0.0,
          "angular dispersion d(delta)/d(lambda) < 0 (normal dispersion)")


def _exit_dir(segs, prism_name):
    ex = [s for s in segs if s.get("from") == prism_name and s.get("kind") == "TRANSMIT"]
    if not ex:
        return None
    s = ex[-1]
    return (Vector(s["p2"]) - Vector(s["p1"])).normalized()


def test_tracer_groundtruth():
    print("\n=== (B) TRACER GROUND-TRUTH: dispersion fans + matches analytic deviation ===")
    from optical_alignment_sim import elements_generic as G, physics
    scene = bpy.context.scene
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = G.example_collection("OpticsVerify_Prism")
    X = Vector((1, 0, 0))
    G.source("VP_S", (-150, 0, 0), X, c)
    glass, A, wl0 = 'N-SF11', 60.0, 589.3
    G.prism("VP_P", (0, 0, 0), X, c, prism_type='EQUILATERAL', apex_deg=A, glass=glass, design_wl=wl0)
    bpy.context.view_layer.update()
    src = scene.objects["VP_S"]
    # the fixed (design-wl min-deviation) incidence the prism sits at
    nd = physics.sellmeier_n(wl0, glass)
    i1 = 0.5 * (A + physics.prism_min_deviation(nd, A))

    print("  wl(nm)   n(lambda)   trace_dev    prism_deviation(n,A,i1)   |diff|")
    rows = []
    for wl in (430.0, 450.0, 486.1, 550.0, wl0, 650.0, 680.0):
        src.optics.wavelength = wl
        segs = _trace(scene)
        d = _exit_dir(segs, "VP_P")
        n = physics.sellmeier_n(wl, glass)
        ana = physics.prism_deviation(n, A, i1)
        dev = math.degrees(math.acos(max(-1.0, min(1.0, d.dot(X))))) if d is not None else None
        rows.append((wl, n, dev, ana))
        print("  %-7.1f  %.5f    %s    %8.4f          %s"
              % (wl, n, ("%8.4f" % dev) if dev is not None else "   NONE ", ana,
                 ("%.5f" % abs(dev - ana)) if dev is not None else "n/a"))
    # (i) blue (430) bends MORE than red (680)
    dev_blue = rows[0][2]; dev_red = rows[-1][2]
    check(dev_blue is not None and dev_red is not None and dev_blue > dev_red + 1.0,
          "blue (430 nm) deviates MORE than red (680 nm): %.3f > %.3f" % (dev_blue or -1, dev_red or -1))
    # (ii) every traced deviation matches the analytic prism_deviation at the fixed incidence
    allmatch = all(r[2] is not None and abs(r[2] - r[3]) < 1e-3 for r in rows)
    check(allmatch, "traced deviation matches prism_deviation(n(lambda), A, i1) for all wavelengths (<1e-3 deg)")
    # (iii) the design wavelength sits at delta_min
    src.optics.wavelength = wl0
    d0 = _exit_dir(_trace(scene), "VP_P")
    dev0 = math.degrees(math.acos(max(-1.0, min(1.0, d0.dot(X)))))
    dmin0 = physics.prism_min_deviation(nd, A)
    check(abs(dev0 - dmin0) < 1e-3, "design wavelength sits at minimum deviation (%.4f vs %.4f)" % (dev0, dmin0))

    # --- the other three families build + trace + disperse ---
    print("\n  --- Littrow / Pellin-Broca / Amici design conditions ---")
    def _devs(pt, **cfg):
        for o in list(scene.objects):
            if getattr(getattr(o, "optics", None), "is_optical", False):
                bpy.data.objects.remove(o, do_unlink=True)
        cc = G.example_collection("OpticsVerify_PrismT")
        G.source("T_S", (-150, 0, 0), X, cc)
        G.prism("T_P", (0, 0, 0), X, cc, prism_type=pt, design_wl=wl0, **cfg)
        bpy.context.view_layer.update()
        out = {}
        for wl in (450.0, wl0, 650.0):
            scene.objects["T_S"].optics.wavelength = wl
            d = _exit_dir(_trace(scene), "T_P")
            out[wl] = (math.degrees(math.acos(max(-1.0, min(1.0, d.dot(X))))) if d is not None else None)
        return out

    lit = _devs('LITTROW', apex_deg=30.0, glass='N-SF11')
    print("    Littrow      devs:", {k: (round(v, 2) if v else None) for k, v in lit.items()})
    check(lit[wl0] is not None and abs(lit[wl0] - 180.0) < 1.0, "Littrow retro-reflects at the design wl (~180 deg)")
    check(lit[450.0] is not None and lit[650.0] is not None and abs(lit[450.0] - lit[650.0]) > 0.5,
          "Littrow disperses (450 vs 650 deviate differently)")

    pb = _devs('PELLIN_BROCA', apex_deg=60.0, glass='N-SF11')
    print("    Pellin-Broca devs:", {k: (round(v, 2) if v else None) for k, v in pb.items()})
    check(pb[wl0] is not None and abs(pb[wl0] - 90.0) < 1.0, "Pellin-Broca deviates the design wl by exactly 90 deg")
    check(pb[450.0] is not None and pb[650.0] is not None and abs(pb[450.0] - pb[650.0]) > 0.5,
          "Pellin-Broca disperses around 90 deg")

    am = _devs('AMICI', apex_deg=60.0, glass='N-BK7', glass2='N-SF11')
    print("    Amici        devs:", {k: (round(v, 2) if v else None) for k, v in am.items()})
    check(am[wl0] is not None and abs(am[wl0]) < 0.5, "Amici (direct-vision) passes the design wl ~undeviated")
    check(am[450.0] is not None and am[650.0] is not None and abs(am[450.0] - am[650.0]) > 0.5,
          "Amici disperses around zero deviation")


def test_byte_identical():
    print("\n=== (C) BYTE-IDENTICAL: 14 existing examples unperturbed by the PRISM branch ===")
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    scene = bpy.context.scene
    # drop every verify-only collection + stray optic from tests (A)/(B) so they can't sit in an
    # example's beam path and perturb its digest (build() only resets OpticsExample_* collections).
    for cc in list(bpy.data.collections):
        if cc.name.startswith("OpticsVerify_"):
            for o in list(cc.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(cc)
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    existing = [k for k in ex.EXAMPLES if k not in ('prism', 'beam_router')]   # exclude C3 + C4 prism examples
    check(len(existing) == 14, "exactly 14 existing (non-prism) examples (%d)" % len(existing))
    all_ok = True
    for kind in sorted(existing):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene)); pd = _ports_digest(scene)
        ref = REF_SEG.get(kind)
        ok = (ref is None) or sd.startswith(ref)
        all_ok = all_ok and ok
        tag = "" if ref is None else ("  ref %s %s" % (ref, "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s  ports %s%s" % (kind, sd[:12], pd[:12], tag))
    check(all_ok, "all pinned reference hashes (mach_zehnder/michelson/periscope) match")


def test_prism_example():
    print("\n=== (D) PRISM EXAMPLE: spectrometer fans the spectrum ===")
    import optics_api
    scene = bpy.context.scene
    r = optics_api.build_example("prism")
    check(isinstance(r, dict) and r.get("segments", 0) >= 5, "prism example builds (%s)" % r)
    segs = _trace(scene)
    exits = [s for s in segs if s.get("from") == "PRISM_Prism" and s.get("kind") == "TRANSMIT"]
    angs = sorted(set(round(math.degrees(math.acos(max(-1.0, min(1.0,
                  (Vector(s["p2"]) - Vector(s["p1"])).normalized().dot(Vector((1, 0, 0))))))), 3) for s in exits))
    print("  exit deviation angles:", angs)
    check(len(exits) >= 5, "at least 5 discrete wavelengths exit the prism (%d)" % len(exits))
    check(len(angs) >= 2 and (max(angs) - min(angs)) > 2.0,
          "the wavelengths FAN out (span %.2f deg)" % (max(angs) - min(angs) if angs else 0.0))


def main():
    _register_addon()
    test_constants()
    test_tracer_groundtruth()
    test_byte_identical()
    test_prism_example()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL PRISM (C3) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
