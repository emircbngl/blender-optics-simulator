"""Headless verification harness for Wave-3 A10 (pol / coherence fringe disambiguation).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_fringe_disambig.py

A10 separates the physically-distinct causes of a DEAD (low-visibility) interference fringe at a
detector reached by >=2 same-source arms, REUSING only oracle-verified kernels (no new physics):
  pol_mismatch       - the two arms' normalized Jones overlap |<Ja|Jb>| ~ 0 (orthogonally
                       polarized) -> they cannot interfere. Same overlap physics.interfere weights.
  coherence_mismatch - arms co-polarized but OPD > coherence length so physics.fringe_envelope
                       (OPD, Lc) washes the fringes out.
  crossed_polarizer  - the detector's analyzer projects EACH arm individually to the Malus
                       extinction floor (the SUM of the per-arm analyzer-projected powers is ~0).

THE BUG THIS HARNESS GUARDS (root-cause fixed): the original crossed_polarizer test fired when the
INTERFERED measure() power was <= 2% of the arriving power. But a healthy destructive-interference
DARK PORT (a Mach-Zehnder's complementary output) ALSO has near-zero INTERFERED power -- the arms
cancel by PHASE, not by polarization. So a dark fringe was misclassified as a crossed analyzer, and
mach_zehnder + dhm FALSE-FIRED crossed_polarizer. The fix tests the INCOHERENT sum of the per-arm
analyzer-projected powers instead: a crossed analyzer kills each arm individually (sum ~ 0); a dark
fringe keeps each arm passing the analyzer at full power (sum high) and is silently a healthy null.
With analyzer=='NONE' there is nothing to cross, so a low power is interference, never crossed_polarizer.

Proves, in order:
  (A) NO NEW PHYSICS: A10 only reads physics.intensity / the Jones overlap / physics.fringe_envelope /
      physics.M_polarizer (analyzer projection) -- all already oracle-verified. No formula added; the
      thresholds only mark where a REUSED quantity counts as "dead". (Asserted structurally below.)
  (B) NO FALSE POSITIVES (the bug gate): run_diagnostics() on ALL build_example scenes emits ZERO of
      {pol_mismatch, coherence_mismatch, crossed_polarizer}. mach_zehnder + dhm are now CLEAN (0).
  (C) CORRECT FIRING (disambiguation): pol_mismatch fires on an orthogonal-arm scene (and NOT
      coherence_mismatch), and CLEARS when the arm is parallel; coherence_mismatch fires on a
      long-OPD broadband (short-Lc) scene (and NOT pol_mismatch), and CLEARS when OPD<Lc;
      crossed_polarizer fires on a real crossed analyzer (and NOT the others), and CLEARS when
      uncrossed. The crux: a dark port WITH an aligned analyzer present stays SILENT.
  (D) BYTE-IDENTICAL: A10 is read-only -> the existing build_example scenes trace to the SAME
      seg+ports md5 as before. Reference hashes pinned below (mach_zehnder/michelson/periscope).
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
A10 = {"pol_mismatch", "coherence_mismatch", "crossed_polarizer"}


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", label, ("  <- " + detail) if (detail and not cond) else "")
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


# Pinned reference seg-digests (read-only diagnostic -> unchanged from the A9 baseline).
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


def _diag(scene):
    from optical_alignment_sim import tracer, diagnostics
    tracer.cached_segments = _trace(scene)
    return [i for i in diagnostics.run_diagnostics(scene) if i.get("kind") in A10]


def _fresh(name):
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    return G.example_collection(name)


X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))


# --------------------------------------------------------------------------- #
def test_no_new_physics():
    print("\n=== (A) NO NEW PHYSICS: A10 reuses verified kernels only ===")
    from optical_alignment_sim import diagnostics, physics
    src = ""
    fn = getattr(diagnostics, "_fringe_disambiguation")
    import inspect
    src = inspect.getsource(fn)
    # the classifier reads ONLY these already-oracle-verified quantities
    check("uses physics.intensity (verified)", "physics.intensity" in src)
    check("uses physics.fringe_envelope (verified coherence decay)", "physics.fringe_envelope" in src)
    check("uses physics.analyzer_matrix / physics.apply (Malus projection, verified)",
          "physics.analyzer_matrix" in src and "physics.apply" in src)
    check("Jones overlap is the SAME <Ja|Jb> physics.interfere weights (no new formula)",
          "conjugate()" in src and "math.sqrt" in src)
    # every kernel A10 calls exists + behaves as verified (spot-check Malus + envelope here)
    JV = physics.apply(physics.M_polarizer(90.0, extinction=1e12), physics.jones_linear(0.0))
    check("Malus: H light through a crossed (V) analyzer -> ~0 (extinction floor) [I=%.3g]"
          % physics.intensity(JV), physics.intensity(JV) < 1e-9)
    check("fringe_envelope(OPD>>Lc) -> ~0 ; fringe_envelope(0) = 1",
          physics.fringe_envelope(10.0, 0.1) < 1e-3 and abs(physics.fringe_envelope(0.0, 0.1) - 1.0) < 1e-12)
    print("  -> A10 adds NO new formula: it is reuse of intensity + Jones-overlap + fringe_envelope + Malus.")


def test_no_false_positives():
    print("\n=== (B) NO FALSE POSITIVES: every build_example emits ZERO A10 flags ===")
    from optical_alignment_sim import examples_builtin as ex, tracer, diagnostics
    scene = bpy.context.scene
    total = 0
    mz_dhm_clean = True
    for kind in sorted(ex.EXAMPLES):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        tracer.cached_segments = _trace(scene)
        flags = [i for i in diagnostics.run_diagnostics(scene) if i.get("kind") in A10]
        total += len(flags)
        if kind in ("mach_zehnder", "dhm") and flags:
            mz_dhm_clean = False
        tag = "" if not flags else ("  <- " + str([(i["kind"], i["element"]) for i in flags]))
        print("  %-16s A10=%d%s" % (kind, len(flags), tag))
    check("ALL build_example scenes emit ZERO A10 flags (no false positives)", total == 0,
          "total=%d" % total)
    check("mach_zehnder + dhm dark ports are CLEAN (the fixed bug)", mz_dhm_clean)


def _build_mz(hwp_fast=None, analyzer='NONE', bandwidth=0.0):
    """A Mach-Zehnder with an optional HWP in the top arm + an optional detector analyzer.
    Bright port A10MZ_D0, dark port A10MZ_D1. Returns the scene built."""
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    L = 200.0
    # synthetic-scene names are prefixed A10MZ_ so they never collide with the build_example
    # 'MZ_*' names -- a left-over object with a duplicated name would pollute the next trace.
    c = _fresh("A10TEST_MZ")
    src = G.source("A10MZ_L", (-150, 0, 0), X, c)
    src.optics.pol_type = 'LINEAR'
    src.optics.pol_angle = 0.0                                  # H-polarized
    if bandwidth > 0.0:
        src.optics.bandwidth_nm = bandwidth
    G.beamsplitter("A10MZ_BS1", (0, 0, 0), X, Y, c)
    G.mirror("A10MZ_Mtop", (0, L, 0), Y, X, c)                 # top arm: +Y -> +X
    if hwp_fast is not None:
        G.waveplate("A10MZ_HWP", (L * 0.5, L, 0), X, c, kind='HWP', fast_axis=hwp_fast, design_wl=632.8)
    G.mirror("A10MZ_Mbot", (L, 0, 0), X, Y, c)                 # bottom arm: +X -> +Y
    G.beamsplitter("A10MZ_BS2", (L, L, 0), X, Y, c)
    d0 = G.detector("A10MZ_D0", (2 * L, L, 0), X, c)           # bright (through) port
    d1 = G.detector("A10MZ_D1", (L, 2 * L, 0), Y, c)          # dark port
    if analyzer != 'NONE':
        d0.optics.analyzer = analyzer
        d1.optics.analyzer = analyzer
    bpy.context.view_layer.update()
    return scene


def _build_michelson(linewidth_nm=0.0, stage_mm=0.0):
    """A Michelson with a finite source linewidth (-> finite Lc) and a translation-stage arm,
    so the OPD = 2*stage_mm scans across the coherence length. Detector A10MI_D."""
    from optical_alignment_sim import elements_generic as G, mounts
    scene = bpy.context.scene
    L = 180.0
    c = _fresh("A10TEST_MI")
    src = G.source("A10MI_L", (-150, 0, 0), X, c)
    src.optics.pol_type = 'LINEAR'
    src.optics.pol_angle = 0.0
    src.optics.linewidth_nm = linewidth_nm                     # finite linewidth -> finite Lc
    G.beamsplitter("A10MI_BS", (0, 0, 0), X, Y, c)
    G.mirror("A10MI_Mfix", (0, L, 0), Y, -Y, c)              # retro +Y -> -Y (fixed arm)
    mst = G.mirror("A10MI_Mstage", (L, 0, 0), X, -X, c)     # retro +X -> -X (stage arm)
    G.add_translation_dof(mst, (1, 0, 0), -80.0, 80.0, stage_mm)
    mounts.compose_pose(mst)
    G.detector("A10MI_D", (0, -L, 0), -Y, c)
    bpy.context.view_layer.update()
    return scene


def _pair_metrics(scene, det_name):
    """Print + return (overlap, OPD, Lc, env, n_arms) for the strongest same-source pair at det."""
    from optical_alignment_sim import tracer, physics
    segs = tracer.cached_segments or _trace(scene)
    inc = [s for s in segs if s.get("to") == det_name]
    groups = {}
    for s in inc:
        groups.setdefault(s.get("src_id", -1), []).append(s)
    best = None
    for sid, g in groups.items():
        if len(g) < 2:
            continue
        pair = sorted(g, key=lambda s: s.get("power", 0.0), reverse=True)[:2]
        Ja = (complex(pair[0]["jones"][0], pair[0]["jones"][1]),
              complex(pair[0]["jones"][2], pair[0]["jones"][3]))
        Jb = (complex(pair[1]["jones"][0], pair[1]["jones"][1]),
              complex(pair[1]["jones"][2], pair[1]["jones"][3]))
        Ia, Ib = physics.intensity(Ja), physics.intensity(Jb)
        ov = abs(Ja[0] * Jb[0].conjugate() + Ja[1] * Jb[1].conjugate()) / math.sqrt(Ia * Ib) if Ia > 0 and Ib > 0 else 0.0
        opd = abs(pair[0].get("opl", 0.0) - pair[1].get("opl", 0.0))
        Lc = min(pair[0].get("coh", float('inf')), pair[1].get("coh", float('inf')))
        env = physics.fringe_envelope(opd, Lc)
        best = (ov, opd, Lc, env, len(g))
    return best


def test_correct_firing():
    print("\n=== (C) CORRECT FIRING: pol vs coherence vs crossed -- each fires its OWN label + clears ===")
    print("  %-22s %-10s %-9s %-10s %-9s -> %s" % ("scenario", "overlap", "OPD/mm", "Lc/mm", "env", "flag"))

    # --- pol_mismatch: a HWP @45deg rotates the top arm H -> V (orthogonal). Overlap ~ 0. ---
    sc = _build_mz(hwp_fast=45.0)
    flags = _diag(sc)
    m = _pair_metrics(sc, "A10MZ_D1")
    kinds = {i["kind"] for i in flags}
    print("  %-22s %-10.3f %-9.3f %-10.4g %-9.3f -> %s"
          % ("pol (HWP@45, arm->V)", m[0], m[1], m[2], m[3], sorted(kinds)))
    check("pol_mismatch FIRES on the orthogonal-arm scene", "pol_mismatch" in kinds)
    check("  ... and coherence_mismatch does NOT fire (it is a POL fault)", "coherence_mismatch" not in kinds)
    check("  ... and crossed_polarizer does NOT fire (no analyzer)", "crossed_polarizer" not in kinds)
    # clear: HWP @0 is a no-op on H -> both arms H -> overlap ~ 1 -> silent
    sc = _build_mz(hwp_fast=0.0)
    flags = _diag(sc)
    check("pol_mismatch CLEARS when the arm is rotated back parallel (HWP@0)",
          not any(i["kind"] in A10 for i in flags), str([(i["kind"], i["element"]) for i in flags]))

    # --- coherence_mismatch: finite linewidth (short Lc) + a large OPD from the stage. ---
    sc = _build_michelson(linewidth_nm=2.0, stage_mm=40.0)            # OPD = 80 mm >> Lc ~ 0.2 mm
    flags = _diag(sc)
    m = _pair_metrics(sc, "A10MI_D")
    kinds = {i["kind"] for i in flags}
    print("  %-22s %-10.3f %-9.3f %-10.4g %-9.3f -> %s"
          % ("coherence (OPD>>Lc)", m[0], m[1], m[2], m[3], sorted(kinds)))
    check("coherence_mismatch FIRES on the long-OPD broadband scene", "coherence_mismatch" in kinds)
    check("  ... and pol_mismatch does NOT fire (arms ARE co-polarized)", "pol_mismatch" not in kinds)
    check("  ... and crossed_polarizer does NOT fire (no analyzer)", "crossed_polarizer" not in kinds)
    # clear: centre the stage -> OPD 0 << Lc -> envelope = 1 -> silent
    sc = _build_michelson(linewidth_nm=2.0, stage_mm=0.0)
    flags = _diag(sc)
    check("coherence_mismatch CLEARS when OPD < Lc (stage centred, OPD=0)",
          not any(i["kind"] in A10 for i in flags), str([(i["kind"], i["element"]) for i in flags]))

    # --- crossed_polarizer: both arms H, the detector analyzer is V (crossed). ---
    sc = _build_mz(hwp_fast=None, analyzer='V')
    flags = _diag(sc)
    kinds = {i["kind"] for i in flags}
    print("  %-22s %-10s %-9s %-10s %-9s -> %s"
          % ("crossed (arms H, an=V)", "n/a", "n/a", "n/a", "n/a", sorted(kinds)))
    check("crossed_polarizer FIRES on a real crossed analyzer (arms H, analyzer V)",
          "crossed_polarizer" in kinds)
    check("  ... and pol_mismatch / coherence_mismatch do NOT fire",
          "pol_mismatch" not in kinds and "coherence_mismatch" not in kinds)
    # it fires on BOTH the bright and the dark port (every arm is Malus-killed individually)
    xp = {i["element"] for i in flags if i["kind"] == "crossed_polarizer"}
    check("crossed_polarizer fires at both ports (each arm extinguished): %s" % sorted(xp),
          {"A10MZ_D0", "A10MZ_D1"}.issubset(xp))
    # clear: analyzer H (uncrossed, aligned to the H light) -> per-arm analyzed power full -> silent
    sc = _build_mz(hwp_fast=None, analyzer='H')
    flags = _diag(sc)
    check("crossed_polarizer CLEARS when the analyzer is uncrossed (H, aligned to the light)",
          not any(i["kind"] in A10 for i in flags), str([(i["kind"], i["element"]) for i in flags]))

    # --- THE CRUX: a dark port WITH an aligned analyzer present must stay SILENT (healthy null,
    # each arm passes the analyzer; only the INTERFERED power is low -> NOT a crossed polarizer). ---
    sc = _build_mz(hwp_fast=None, analyzer='H')                      # A10MZ_D1 is the destructive dark port
    from optical_alignment_sim import tracer, alignment
    tracer.cached_segments = _trace(sc)
    meas_p, _vis, _s = alignment.measure(tracer.cached_segments, "A10MZ_D1", 'H')
    flags = _diag(sc)
    xp1 = [i for i in flags if i["element"] == "A10MZ_D1" and i["kind"] == "crossed_polarizer"]
    check("CRUX: dark port with an ALIGNED analyzer (interfered power=%.4g ~ 0) does NOT crossed-fire "
          "(per-arm analyzed power is full -> healthy phase null)" % meas_p, len(xp1) == 0)


def test_byte_identical():
    print("\n=== (D) BYTE-IDENTICAL: A10 is read-only -> existing examples trace unchanged ===")
    from optical_alignment_sim import examples_builtin as ex
    scene = bpy.context.scene
    for cc in list(bpy.data.collections):
        if cc.name.startswith("A10_") or cc.name.startswith("OpticsExample_"):
            from optical_alignment_sim import elements_generic as G
            for o in list(cc.objects):
                G.drop_example_object(o)
            try:
                bpy.data.collections.remove(cc)
            except Exception:
                pass
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    all_ok = True
    for kind in sorted(ex.EXAMPLES):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene))
        pd = _ports_digest(scene)
        ref = REF_SEG.get(kind)
        ok = (ref is None) or sd.startswith(ref)
        all_ok = all_ok and ok
        tag = "" if ref is None else ("  ref %s %s" % (ref, "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s  ports %s%s" % (kind, sd[:12], pd[:12], tag))
    check("all pinned reference hashes match -- read-only A10 did not perturb the trace", all_ok)


def main():
    _register_addon()
    test_no_new_physics()
    test_no_false_positives()
    test_correct_firing()
    test_byte_identical()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL A10 FRINGE-DISAMBIGUATION CHECKS PASS")


if __name__ == "__main__":
    main()
