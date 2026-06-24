"""Headless verification harness for Wave-3 B5 (ao.py AO reconstructor upgrade).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_ao_recon.py

Proves, in order:
  (A) KOLMOGOROV variance scaling -- the ONE new physical relation, sigma^2 = 1.0299*(D/r0)^(5/3)
      rad^2 (Noll 1976), already physics_verify ok=true (6/6). Here we confirm the IMPLEMENTATION
      obeys it: doubling D/r0 raises the injected phase VARIANCE by exactly 2^(5/3); the first-15-mode
      coefficient sum reproduces the Noll total (~1.003 of the full 1.0299, the rest in modes >15);
      the aberrator is deterministic given (r0, D, seed). Reuses physics.wavefront_rms (verified).
  (B) CLOSED-LOOP GROUND-TRUTH (the real proof): inject a KNOWN aberration (a fixed Zernike vector
      RMS ~0.5 waves, AND an r0-driven Kolmogorov one) -> run the upgraded closed loop -> the residual
      wavefront_rms drops by >5x, monotone toward the floor. Done for BOTH reconstructors: TSVD
      converges fast; DAMPED_TRANSPOSE converges (slower) WITHOUT amplifying noise modes. A separate
      ill-conditioned + measurement-noise demo shows TSVD/damped-transpose stay bounded where a naive
      full inverse blows up.
  (C) BYTE-IDENTICAL: all 18 build_example scenes (incl. adaptive_optics) trace to the SAME seg+ports
      md5 whether or not the B5 reconstructor was imported/run (the loop is on-demand only). Pins:
      mach_zehnder 819b140513c1, michelson 2988d9599234, periscope 7a69a20b58f7.
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
    sys.stdout.flush()
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


# --------------------------------------------------------------------------- #
def test_kolmogorov_scaling():
    """(A) The Kolmogorov ABERRATOR obeys the physics_verified Noll variance law
    sigma^2 = 1.0299*(D/r0)^(5/3): variance scales as (D/r0)^(5/3), the first-15-mode
    sum reproduces the Noll total, and a given (r0,D,seed) is deterministic."""
    print("\n=== (A) KOLMOGOROV variance scaling sigma^2 = 1.0299*(D/r0)^(5/3) [Noll 1976, physics_verify ok 6/6] ===")
    from optical_alignment_sim import ao, physics
    D = 25.4
    # variance (rad^2) = (2*pi*RMS_waves)^2; ratio for r0/2 vs r0 must be 2^(5/3)
    rms30 = physics.wavefront_rms(ao.kolmogorov_aberration(30.0, D, seed=3))
    rms60 = physics.wavefront_rms(ao.kolmogorov_aberration(60.0, D, seed=3))
    var30, var60 = (2 * math.pi * rms30) ** 2, (2 * math.pi * rms60) ** 2
    ratio = var30 / var60
    print("  var(r0=30)=%.5f rad^2   var(r0=60)=%.5f rad^2   ratio=%.5f   expected 2^(5/3)=%.5f"
          % (var30, var60, ratio, 2.0 ** (5.0 / 3.0)))
    check(abs(ratio - 2.0 ** (5.0 / 3.0)) < 1e-4, "A: halving r0 raises the phase variance by 2^(5/3)")

    # the implementation's K (variance / (D/r0)^(5/3)) over the first 15 modes ~ 1.003 (Noll's full
    # 1.0299 minus the >15-mode tail) -> the per-mode weights sum to the verified total
    K_eff = var60 / ((D / 60.0) ** (5.0 / 3.0))
    print("  K_eff (first-15-mode variance / (D/r0)^(5/3)) = %.4f   (Noll total 1.0299; first-15 sum ~1.003)" % K_eff)
    check(1.00 < K_eff < 1.04, "A: first-15-mode variance matches the Noll total to the >15 tail (K~1.003)")
    check(abs(ao.NOLL_KOLM - 1.0299) < 1e-9, "A: the Noll coefficient is the verified 1.0299")

    # determinism: same (r0,D,seed) -> identical vector; different seed -> different realization
    a1 = ao.kolmogorov_aberration(60.0, D, seed=7)
    a2 = ao.kolmogorov_aberration(60.0, D, seed=7)
    a3 = ao.kolmogorov_aberration(60.0, D, seed=8)
    check(a1 == a2, "A: aberrator is deterministic for a fixed (r0, D, seed)")
    check(a1 != a3 and abs(physics.wavefront_rms(a1) - physics.wavefront_rms(a3)) < 1e-9,
          "A: a different seed gives a different realization at the SAME RMS")


# --------------------------------------------------------------------------- #
_AO_SCENE_BUILT = {"done": False}


def _purge_vao():
    """Hard-remove every VAO_ object (+ its mesh) and the OpticsVerify_AO collection. drop_example_object
    only UNLINKS objects outside an OpticsExample_ collection, leaving an orphan datablock that Blender
    then suffixes (VAO_DM.001) on rebuild -- which the trace-by-name would miss. We delete outright."""
    for o in list(bpy.context.scene.objects):
        if o.name.startswith("VAO_"):
            mesh = o.data if o.type == 'MESH' else None
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for c in list(bpy.data.collections):
        if c.name == "OpticsVerify_AO":
            bpy.data.collections.remove(c)
    _AO_SCENE_BUILT["done"] = False


def _ao_scene(modes):
    """The AO bench: laser -> aberrator(modes) -> deformable mirror -> wavefront sensor. Built ONCE
    (mirrors examples_builtin.build_adaptive_optics) then RESET between runs -- zero the DM command,
    rewrite the aberrator's modes -- rather than rebuilt, so Blender never suffixes a duplicate
    datablock (VAO_DM.001) that the trace-by-name then misses. Returns the scene."""
    from optical_alignment_sim import elements_generic as G, physics, tracer
    scene = bpy.context.scene
    if not _AO_SCENE_BUILT["done"]:
        _purge_vao()                                             # hard-remove any leftover VAO_ datablocks
        coll = G.example_collection("OpticsVerify_AO")
        X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
        G.source("VAO_Laser", (-220, 0, 0), X, coll)
        G.aberrator("VAO_Turb", (-90, 0, 0), X, coll, modes=list(modes))
        G.deformable_mirror("VAO_DM", (0, 0, 0), X, Y, coll)     # fold +X -> +Y
        G.wavefront_sensor("VAO_WFS", (0, 160, 0), Y, coll)      # faces the +Y beam
        assert "VAO_Turb" in scene.objects and "VAO_DM" in scene.objects and "VAO_WFS" in scene.objects, \
            "AO scratch scene failed to build with exact names (datablock collision?)"
        _AO_SCENE_BUILT["done"] = True
    # reset to a clean open-loop state with the requested aberration
    m = list(modes) + [0.0] * (physics.N_ZERNIKE - len(modes))
    scene.objects["VAO_Turb"].optics.aberr_spec = m[:physics.N_ZERNIKE]
    scene.objects["VAO_DM"].optics.dm_command = [0.0] * physics.N_ZERNIKE
    scene.objects["VAO_WFS"].optics.wf_rms = 0.0
    tracer.cached_segments = []
    bpy.context.view_layer.update()
    return scene


def _run_recon(modes, method, gain=0.8, leak=0.99, iters=40, label=""):
    from optical_alignment_sim import ao
    scene = _ao_scene(modes)
    res = ao.close_loop_recon(scene, "VAO_WFS", "VAO_DM", gain=gain, leak=leak,
                              method=method, iters=iters)
    h = res["history"]
    mono = all(h[i + 1] <= h[i] + 1e-6 for i in range(len(h) - 1))
    print("  [%s] %-18s RMS %.4f -> %.4f waves  (%.1fx)  iters=%d  converged=%s"
          % (label, method, res["rms_before"], res["rms_after"],
             res["reduction"] if res["reduction"] != float('inf') else 1e9,
             res["iterations"], res["converged"]))
    print("       history:", [round(x, 4) for x in h])
    print("       singular(B):", res["singular"][:6], "..." if len(res["singular"]) > 6 else "")
    return res, mono


def test_closed_loop_groundtruth():
    """(B) Inject a KNOWN aberration -> the B5 closed loop drives the residual RMS down >5x,
    monotone, for BOTH reconstructors, on a fixed vector AND a Kolmogorov r0-driven one."""
    print("\n=== (B) CLOSED-LOOP GROUND-TRUTH: inject known aberration -> RMS drops >5x (both reconstructors) ===")
    from optical_alignment_sim import ao, physics

    # --- a fixed, known Zernike vector, RMS ~0.5 waves (defocus 0.3 + astig 0.3 + coma 0.2) ---
    fixed = [0.0] * physics.N_ZERNIKE
    fixed[3], fixed[5], fixed[7] = 0.3, 0.3, 0.2
    rms0 = physics.wavefront_rms(fixed)
    print("  injected fixed aberration: RMS = %.4f waves (defocus+astig+coma)" % rms0)
    for method in ("TSVD", "DAMPED_TRANSPOSE"):
        res, mono = _run_recon(fixed, method, gain=0.8, leak=0.99, iters=60, label="fixed")
        check(res["ok"] and res["rms_before"] > 0.4, "B: %s starts at the injected ~0.5 RMS" % method)
        check(res["rms_before"] / max(res["rms_after"], 1e-12) > 5.0,
              "B: %s closed loop reduces RMS >5x" % method)
        check(mono, "B: %s residual history monotone non-increasing" % method)

    # --- a Kolmogorov r0-driven aberration (physical turbulence) ---
    kol = ao.kolmogorov_aberration(20.0, 25.4, seed=5)        # strong turbulence (small r0)
    rmsk = physics.wavefront_rms(kol)
    print("\n  injected Kolmogorov turbulence (r0=20 mm, D=25.4 mm): RMS = %.4f waves" % rmsk)
    for method in ("TSVD", "DAMPED_TRANSPOSE"):
        res, mono = _run_recon(kol, method, gain=0.8, leak=0.99, iters=60, label="kolmog")
        check(res["ok"] and res["rms_before"] / max(res["rms_after"], 1e-12) > 5.0,
              "B: %s reduces the Kolmogorov turbulence RMS >5x" % method)
        check(mono, "B: %s Kolmogorov residual history monotone" % method)


def test_noise_tolerance():
    """(B-noise) With an ill-conditioned (near-null) mode AND measurement noise, the TSVD and
    damped-transpose reconstructors stay BOUNDED (drop / damp the bad mode), where a naive full
    inverse amplifies it to a huge command. Pure linear algebra over the verified modes -- run
    standalone (no scene needed) so the noise is injected cleanly."""
    print("\n=== (B-noise) ill-conditioned + measurement noise: TSVD/damped stay bounded, naive inverse blows up ===")
    from optical_alignment_sim import ao
    import numpy as np

    n = 8
    # modal interaction matrix B = -I, but mode index 4 is near-null (tiny singular value)
    B = [[-1.0 if i == k else 0.0 for k in range(n)] for i in range(n)]
    B[4][4] = -1e-4
    aberr = [0.3, 0.2, 0.15, 0.1, 0.05, 0.08, 0.04, 0.02]
    noise = 0.01

    def loop(R, gain):
        x = [0.0] * n
        for it in range(60):
            w = [aberr[i] + sum(B[i][k] * x[k] for k in range(n)) for i in range(n)]
            wn = [w[i] + noise * math.sin(13.0 * it + 7.0 * i) for i in range(n)]  # deterministic noise
            dx = ao._matvec(R, wn)
            x = [0.99 * x[i] - gain * dx[i] for i in range(n)]
        return x

    x_tsvd = loop(ao.reconstructor(B, 'TSVD'), 0.8)
    x_damp = loop(ao.reconstructor(B, 'DAMPED_TRANSPOSE'), 1.0)
    # naive full pseudo-inverse keeps the 1e-4 singular value -> 1e4 gain on the noisy null mode
    Binv = np.linalg.pinv(np.array(B), rcond=1e-12)
    x = [0.0] * n
    for it in range(60):
        w = [aberr[i] + sum(B[i][k] * x[k] for k in range(n)) for i in range(n)]
        wn = [w[i] + noise * math.sin(13.0 * it + 7.0 * i) for i in range(n)]
        dx = Binv @ np.array(wn)
        x = [0.99 * x[i] - 0.8 * dx[i] for i in range(n)]
    print("  null-mode command x[4]:  TSVD=%.4f  DAMPED=%.4f  NAIVE=%.2f" % (x_tsvd[4], x_damp[4], x[4]))
    check(abs(x_tsvd[4]) < 0.05, "B-noise: TSVD drops the ill-conditioned mode (command stays ~0)")
    check(abs(x_damp[4]) < 0.05, "B-noise: damped-transpose does not amplify the null mode")
    check(abs(x[4]) > 5.0, "B-noise: a NAIVE full inverse DOES blow the null mode up (the failure TSVD/damped avoid)")


# --------------------------------------------------------------------------- #
def test_byte_identical():
    print("\n=== (C) BYTE-IDENTICAL: 18 examples, trace + ports md5 (B5 loop is inert until called) ===")
    before = _build_and_hash()
    from optical_alignment_sim import ao
    _ = (ao.close_loop_recon, ao.interaction_matrix, ao.reconstructor, ao.kolmogorov_aberration)
    # actually RUN the reconstructor loop + a Kolmogorov inject on a scratch scene (it MOVES dm_command
    # + aberr_spec on its OWN elements), then rebuild every example: the examples must be untouched.
    _run_recon([0.0, 0.0, 0.0, 0.3, 0.0, 0.3, 0.0, 0.2] + [0.0] * 7, "TSVD", iters=20, label="byteid")
    _purge_vao()        # tear the scratch AO bench fully down so its laser cannot shoot into the re-hashed examples
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
    pins_ok = all(before[k][0].startswith(v) for k, v in pinned.items())
    check(all_ok, "C: all 18 examples trace + ports byte-identical across the B5 loop run")
    check(pins_ok, "C: the three pinned reference hashes (mach_zehnder/michelson/periscope) match")


# --------------------------------------------------------------------------- #
def main():
    _register_addon()
    # byte-identical FIRST, on a clean scene: it builds + hashes the 18 examples, runs the B5
    # loop on a SCRATCH AO scene, then rebuilds + rehashes. If the AO ground-truth tests ran first
    # they would leave a VAO_ laser in the scene whose beam would perturb every example's trace.
    test_byte_identical()
    test_kolmogorov_scaling()
    test_closed_loop_groundtruth()
    test_noise_tolerance()
    print("\n================ SUMMARY ================")
    summary = ("ALL B5 AO-RECONSTRUCTOR VERIFICATION CHECKS PASSED" if not FAILS
               else "FAILED %d check(s): %s" % (len(FAILS), "; ".join(FAILS)))
    print(summary)
    sys.stdout.flush()
    # Blender's headless stdout can drop late prints on a file redirect; mirror the verdict to a
    # /tmp sidecar so the result is recoverable regardless of how stdout was captured (kept out of
    # the repo tree so a verify run never dirties the working tree).
    try:
        with open(os.path.join("/tmp", "oas_verify_ao_recon.result"), "w") as fh:
            fh.write(summary + "\n")
    except OSError:
        pass
    if FAILS:
        sys.exit(1)


if __name__ == "__main__":
    main()
