"""Headless verification harness for Wave-2 B3 (Gaussian mode-match solver + coupling).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_modematch.py

Proves, in order:
  (A) is the physics_verify of the eta coupling formula -- run SEPARATELY via the
      physicist oracle to ok=true, pass_rate 1.0 (9/9): DIMENSIONAL eta dimensionless,
      NUMERIC eta(w,w,0)==1, the mode-overlap [2 w_in w_t/(w_in^2+w_t^2)]^2 at d=0 for
      two (w_in,w_t) pairs + the w_in<->w_t symmetry, the offset factor exp(-2 d^2/
      (w_in^2+w_t^2)) driving eta down at two offsets, SANITY eta in (0,1]. (Not re-run
      here; the Docker oracle is the gate.)

  (B) SOLVER GROUND-TRUTH (the real proof). For >=2 targets: run mode_match_lens, take the
      returned focal f, propagate the INPUT q THROUGH that lens with the VERIFIED
      q_propagate/abcd_lens/abcd_free, and confirm the output waist (w0, z) hits the target
      (w0_t, z_t) to tolerance. PLUS the inverse sanity: pick an f, propagate to a real
      output (w0_t,z_t), then confirm the solver RECOVERS that same f.

  (C) ETA DROPS with injected offset / mode-mismatch: eta == 1 (matched, d=0) -> < 1
      (w-mismatch) -> monotonically smaller (growing offset), all in (0,1].

  (D) BYTE-IDENTICAL: each of the 14 build_example scenes traces to the SAME seg + ports
      md5 whether or not design's B3 surface (coupling_efficiency / mode_match_lens) is
      imported/referenced (design.py is import-inert; B3 adds only pure functions).
      Reference hashes (from the task): mach_zehnder seg 819b140513c1, michelson seg
      2988d9599234, periscope seg 7a69a20b58f7.
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

# reference seg digests from the task brief (must match byte-for-byte)
REF_SEG = {"mach_zehnder": "819b140513c1", "michelson": "2988d9599234",
           "periscope": "7a69a20b58f7"}


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
# shared digests (same canonical form as _verify_design.py / _verify_solvers.py)
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
# (B) solver ground-truth: solve f, forward-propagate, confirm the waist lands;
#     plus the inverse f-recovery.
# --------------------------------------------------------------------------- #
def _propagate_to_waist(w0_in, s_lens, f, wavelength_nm, m2=1.0):
    """Propagate the input q through free(s_lens).lens(f) and read off the achieved
    waist (w0, distance-to-waist) using ONLY the verified physics primitives -- an
    independent oracle for the solver's own self-reported achieved_*."""
    from optical_alignment_sim import physics
    q_in = physics.q_from_waist(w0_in, wavelength_nm, m2)
    q_at_lens = physics.q_propagate(q_in, physics.abcd_free(s_lens))
    q_out = physics.q_propagate(q_at_lens, physics.abcd_lens(f))
    z_to_waist = -q_out.real
    w0 = physics.beam_radius_m2(complex(0.0, q_out.imag), wavelength_nm, m2)
    return w0, z_to_waist


def test_solver_ground_truth():
    print("\n=== (B) SOLVER GROUND-TRUTH: solve f, forward-propagate the verified q ===")
    from optical_alignment_sim import design

    lam = 1064.0
    # >=2 known targets (each physically reachable): a 2x expander into a far waist, a unit-
    # magnification relay, and a magnifier. We solve, then RE-PROPAGATE independently.
    targets = [
        (0.30, 100.0, 0.10, 200.0),     # demagnify 3x, waist 200 mm out
        (0.20, 100.0, 0.20, 150.0),     # unit magnification (symmetric imaging)
        (0.15, 100.0, 0.45, 250.0),     # magnify 3x
    ]
    for (w0_in, s_in, w0_t, z_t) in targets:
        r = design.mode_match_lens(w0_in, s_in, w0_t, z_t, lam)
        if not check(r.get("ok"), "B: mode_match_lens(w0_in=%.2f, w0_t=%.2f, z_t=%.0f) returns a solution"
                     % (w0_in, w0_t, z_t)):
            continue
        f, s_lens = r["f"], r["s_lens"]
        # INDEPENDENT re-propagation (not the solver's own number)
        w0_prop, z_prop = _propagate_to_waist(w0_in, s_lens, f, lam)
        print("  target w0_t=%.4f z_t=%.3f | solved f=%.4f (f_alt=%s) s_lens=%.4f"
              % (w0_t, z_t, f, ("%.4f" % r["f_alt"]) if r["f_alt"] is not None else "None", s_lens))
        print("    re-propagated through free(s_lens).lens(f):  achieved w0=%.5f  z=%.4f  (coupling=%.6f)"
              % (w0_prop, z_prop, r["coupling"]))
        check(abs(w0_prop - w0_t) < 1e-4 and abs(z_prop - z_t) < 1e-3,
              "B: forward-propagated waist hits target (w0 %.5f~%.5f, z %.4f~%.4f)"
              % (w0_prop, w0_t, z_prop, z_t))
        check(abs(r["achieved_w0"] - w0_prop) < 1e-9 and abs(r["achieved_z"] - z_prop) < 1e-6,
              "B: solver's self-reported achieved_* matches the independent propagation")
        check(abs(r["coupling"] - 1.0) < 1e-6,
              "B: coupling into target mode == 1 on a clean mode-match (got %.6f)" % r["coupling"])

    # --- inverse sanity: pick an f, propagate, recover the SAME f ----------------
    print("\n  -- inverse: pick f, propagate to a real (w0_t,z_t), recover f --")
    f_true, s_true, w0_in = 75.0, 120.0, 0.25
    w0_out, z_out = _propagate_to_waist(w0_in, s_true, f_true, lam)
    rec = design.mode_match_lens(w0_in, s_true, w0_out, z_out, lam)
    recovered = rec.get("ok") and (abs(rec["f"] - f_true) < 1e-3
                                   or (rec.get("f_alt") is not None and abs(rec["f_alt"] - f_true) < 1e-3))
    print("    f_true=%.3f at s=%.1f -> output w0=%.5f z=%.4f ; solver recovered f=%.4f (f_alt=%s)"
          % (f_true, s_true, w0_out, z_out, rec.get("f", float("nan")),
             ("%.4f" % rec["f_alt"]) if rec.get("f_alt") is not None else "None"))
    check(recovered, "B: solver RECOVERS the planted focal f=%.3f from (w0_in,s_in,w0_t,z_t)" % f_true)

    # --- honesty: an UNREACHABLE target returns {ok:False}, no fabricated focal -----
    bad = design.mode_match_lens(0.30, 100.0, 0.10, 80.0, lam)
    check(bad.get("ok") is False,
          "B: unreachable demag target (w0_t=0.10 @ z_t=80) refused with {ok:False}: %s"
          % bad.get("error"))


# --------------------------------------------------------------------------- #
# (C) eta drops correctly with injected offset / mismatch
# --------------------------------------------------------------------------- #
def test_eta_vs_offset():
    print("\n=== (C) ETA drops with mode-mismatch / transverse offset (bounded (0,1]) ===")
    from optical_alignment_sim import design

    e_matched = design.coupling_efficiency(0.5, 0.5, 0.0)
    e_wmis = design.coupling_efficiency(0.5, 0.8, 0.0)            # waist mismatch, on-axis
    offsets = [0.0, 0.1, 0.2, 0.3, 0.5]
    series = [design.coupling_efficiency(0.5, 0.5, d) for d in offsets]

    print("  matched (w=w, d=0):           eta = %.6f" % e_matched)
    print("  waist-mismatched (0.5 vs 0.8): eta = %.6f" % e_wmis)
    print("  offset sweep (w=w=0.5 mm):")
    for d, e in zip(offsets, series):
        print("     d=%.2f mm  eta=%.6f" % (d, e))

    check(abs(e_matched - 1.0) < 1e-12, "C: eta == 1 exactly for matched waists, zero offset")
    check(0.0 < e_wmis < 1.0, "C: waist mismatch drops eta below 1 (%.4f)" % e_wmis)
    monotone = all(series[i] > series[i + 1] for i in range(len(series) - 1))
    check(monotone, "C: eta decreases monotonically with growing offset")
    check(all(0.0 < e <= 1.0 for e in series), "C: eta stays in (0, 1] across the sweep")
    # symmetry in w_in<->w_t
    check(abs(design.coupling_efficiency(0.4, 0.7, 0.2) - design.coupling_efficiency(0.7, 0.4, 0.2)) < 1e-12,
          "C: eta symmetric in w_in <-> w_t")
    # guard
    check(design.coupling_efficiency(0.0, 0.5).get("ok") is False,
          "C: non-physical waist (w<=0) rejected with {ok:False}")


# --------------------------------------------------------------------------- #
# (D) byte-identical 14 examples across design-B3 import
# --------------------------------------------------------------------------- #
def _purge_optical():
    for o in list(bpy.context.scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            mesh = o.data if o.type == 'MESH' else None
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsVerify_"):
            bpy.data.collections.remove(c)


def _build_hashes():
    """Build all 14 examples; return {kind: (seg_md5, ports_md5)}."""
    from optical_alignment_sim import examples_builtin as ex, tracer
    scene = bpy.context.scene
    _purge_optical()
    out = {}
    for kind in ex.EXAMPLES:
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        segs = _trace(scene)
        tracer.cached_segments = segs
        out[kind] = (_seg_digest(segs), _ports_digest(scene))
    return out


def test_byte_identical():
    print("\n=== (D) BYTE-IDENTICAL 14 examples across the B3 (mode-match) import ===")
    # BEFORE: hash without ever referencing design's B3 surface.
    before = _build_hashes()
    # AFTER: explicitly import + reference the B3 public surface, then rebuild.
    from optical_alignment_sim import design
    _ = (design.coupling_efficiency, design.mode_match_lens, design.mode_match_two_lens)
    after = _build_hashes()

    all_ident, refs_ok = True, True
    for kind in sorted(before):
        sb, pb = before[kind]
        sa, pa = after[kind]
        ident = (sb == sa and pb == pa)
        all_ident = all_ident and ident
        ref_note = ""
        if kind in REF_SEG:
            match_ref = sb.startswith(REF_SEG[kind])
            refs_ok = refs_ok and match_ref
            ref_note = "  ref %s %s" % (REF_SEG[kind], "OK" if match_ref else "MISMATCH")
        print("  %-16s seg %s  ports %s  %s%s"
              % (kind, sb[:12], pb[:12], "OK" if ident else "CHANGED", ref_note))
    check(all_ident, "D: all 14 examples trace + ports byte-identical across B3 import")
    check(refs_ok, "D: reference seg hashes (mach_zehnder/michelson/periscope) match the brief")


# --------------------------------------------------------------------------- #
def main():
    _register_addon()
    test_solver_ground_truth()
    test_eta_vs_offset()
    test_byte_identical()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL MODE-MATCH (B3) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
