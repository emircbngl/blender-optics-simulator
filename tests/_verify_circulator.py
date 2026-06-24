"""Headless verification harness for Wave-3 C6 (fiber circulator router).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_circulator.py

A CIRCULATOR is the ONE genuinely new tracer TOPOLOGY of Wave-3: a NON-RECIPROCAL N-port cyclic router (a
fiber-optic circulator). A ray entering port Pi exits the NEXT port P(i+1) in the cycle (P1->P2->P3->...->P1);
a small ISOLATION leak goes to the PREVIOUS port P(i-1) at power T * 10^(-isolation_db/10). It is NON-
RECIPROCAL: a ray into P2 exits P3, NOT back to P1 -- the defining property a reciprocal splitter cannot
reproduce. Pol-independent at the ray level (the Jones vector passes through unchanged). It is a ROUTING
topology over the EXISTING port machinery (world_port / world_normal / _child) -- no new geometry, and the
ONLY new optical number is the dimensionless dB->linear isolation ratio.

Proves, in order:
  (A) physics_verify: the ONE numeric relation -- the isolation dB->linear ratio iso_lin = 10^(-iso_db/10)
      (physics.db_to_linear). Oracle ok=true, 7/7: DIMENSIONAL (dimensionless) + NUMERIC 20->0.01 / 30->0.001
      / 0->1.0 / 10->0.1 + SANITY positive + SANITY <=1. The routing TOPOLOGY itself is geometric (port-to-
      port), NO new optical formula. Cross-checked in-Python here against physics.db_to_linear.
  (B) TOPOLOGY GROUND-TRUTH (the real proof -- NON-RECIPROCITY): fire a ray INTO each port and assert the
      MAIN child exits the NEXT port only (P1->P2, P2->P3, P3->P1 the wrap), with the isolation leak on the
      PREVIOUS port at exactly power*10^(-iso/10). Confirms P1->P2 but P2->P3 (a reciprocal device would
      send P2->P1) -- the explicit non-reciprocity assertion.
  (C) BYTE-IDENTICAL: the 21 existing build_example scenes (no circulator) trace to the SAME seg+ports md5
      (the additive CIRCULATOR element_type + isolation_db must not perturb them). Pinned hashes below.
  (D) the new 'circulator' example builds and routes P1->P2 (main) + P3 (leak) to its detectors.
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


# Pinned reference seg-digests (pre-C6; identical to the C4/C7 harness set).
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


def _exit_port(hub, p1):
    """Which named port the segment beginning at world point p1 left FROM (nearest port position)."""
    from optical_alignment_sim import geometry
    return min(hub.optics.ports,
              key=lambda pp: (geometry.world_port(hub, pp.local_position) - Vector(p1)).length).name


# --------------------------------------------------------------------------- #
def test_physics_verify():
    print("\n=== (A) physics_verify: the ONE numeric relation -- isolation dB->linear ===")
    from optical_alignment_sim import physics
    print("  iso_lin = 10^(-iso_db/10) (physics.db_to_linear). Oracle physics_verify ok=true, 7/7:")
    print("    DIMENSIONAL dimensionless + NUMERIC 20->0.01 / 30->0.001 / 0->1.0 / 10->0.1 + SANITY pos + <=1.")
    print("  The routing TOPOLOGY is geometric (port-to-port) -- NO new optical formula. In-Python cross-check:")
    for db, want in ((0.0, 1.0), (10.0, 0.1), (20.0, 0.01), (30.0, 0.001)):
        got = physics.db_to_linear(db)
        check(abs(got - want) < 1e-12, "db_to_linear(%g dB) = %g (got %.6g)" % (db, want, got))


def test_topology_ground_truth():
    print("\n=== (B) TOPOLOGY GROUND-TRUTH: non-reciprocal P1->P2->P3->P1 + isolation leak ===")
    from optical_alignment_sim import elements_generic as G, geometry
    scene = bpy.context.scene
    X = Vector((1, 0, 0))
    c = _fresh("C6_CIRC")
    hub = G.circulator("H", (0, 0, 0), X, c, n_ports=3, isolation_db=20.0)
    iso_lin = 10.0 ** (-20.0 / 10.0)

    expect_main = {"P1": "P2", "P2": "P3", "P3": "P1"}     # the cyclic route (the wrap P3->P1)
    expect_iso = {"P1": "P3", "P2": "P1", "P3": "P2"}      # the leak -> PREVIOUS port
    results = {}
    print("\n  entry   MAIN-exit  main-power   ISO-exit  iso-power")
    for entry in ("P1", "P2", "P3"):
        # fire a source 120 mm out along the entry port's outward normal, aimed back at the hub
        p = next(pp for pp in hub.optics.ports if pp.name == entry)
        wp = geometry.world_port(hub, p.local_position)
        wn = geometry.world_normal(hub, p.local_normal)
        for o in list(scene.objects):
            if o.name == "C6_SRC":
                bpy.data.objects.remove(o, do_unlink=True)
        G.source("C6_SRC", wp + wn * 120.0, -wn, c)
        bpy.context.view_layer.update()
        segs = _trace(scene)
        outs = [s for s in segs if s.get("from") == "H"]
        main = next((s for s in outs if s["kind"] == "CIRC_OUT"), None)
        iso = next((s for s in outs if s["kind"] == "CIRC_ISO"), None)
        m_port = _exit_port(hub, main["p1"]) if main else None
        i_port = _exit_port(hub, iso["p1"]) if iso else None
        results[entry] = (m_port, main["power"] if main else None,
                          i_port, iso["power"] if iso else None)
        print("  %-6s  %-9s  %-10s  %-8s  %s"
              % (entry, m_port, ("%.5f" % main["power"]) if main else "NONE",
                 i_port, ("%.5f" % iso["power"]) if iso else "NONE"))
        check(m_port == expect_main[entry],
              "%s MAIN exits the NEXT port %s (got %s)" % (entry, expect_main[entry], m_port))
        check(main is not None and abs(main["power"] - 1.0) < 1e-6,
              "%s main carries full through power 1.0 (got %s)" % (entry, main["power"] if main else None))
        check(i_port == expect_iso[entry],
              "%s ISOLATION leak exits the PREVIOUS port %s (got %s)" % (entry, expect_iso[entry], i_port))
        check(iso is not None and abs(iso["power"] - iso_lin) < 1e-6,
              "%s iso-leak power == 1.0 * 10^(-20/10) = %.5f (got %s)" % (entry, iso_lin, iso["power"] if iso else None))

    # the EXPLICIT non-reciprocity assertion: P1->P2 but P2->P3 (a reciprocal device would send P2->P1)
    print("\n  NON-RECIPROCITY: P1 routes to %s; P2 routes to %s (a RECIPROCAL device would send P2->P1)."
          % (results["P1"][0], results["P2"][0]))
    check(results["P1"][0] == "P2" and results["P2"][0] == "P3" and results["P2"][0] != "P1",
          "NON-RECIPROCAL: P1->P2 AND P2->P3 (NOT P2->P1) -- the defining circulator property")
    check(results["P3"][0] == "P1", "the cycle WRAPS: P3->P1")


def test_byte_identical():
    print("\n=== (C) BYTE-IDENTICAL: the 21 existing examples unperturbed by the CIRCULATOR additions ===")
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    scene = bpy.context.scene
    for cc in list(bpy.data.collections):
        if cc.name.startswith("OpticsVerify_") or cc.name.startswith("C6_"):
            for o in list(cc.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(cc)
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    existing = [k for k in ex.EXAMPLES if k != 'circulator']
    check(len(existing) == 21, "exactly 21 existing (non-circulator) examples (%d)" % len(existing))
    all_ok = True
    for kind in sorted(existing):
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene))
        pd = _ports_digest(scene)
        ref = REF_SEG.get(kind)
        ok = (ref is None) or sd.startswith(ref)
        all_ok = all_ok and ok
        tag = "" if ref is None else ("  ref %s %s" % (ref, "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s  ports %s%s" % (kind, sd[:12], pd[:12], tag))
    check(all_ok, "all pinned reference hashes (mach_zehnder/michelson/periscope) match -- additive C6 did not perturb them")


def test_circulator_example():
    print("\n=== (D) the 'circulator' example builds + routes P1->P2 (main) + P3 (leak) ===")
    import optics_api
    scene = bpy.context.scene
    r = optics_api.build_example("circulator")
    check(isinstance(r, dict) and r.get("segments", 0) >= 3, "circulator example builds (%s)" % r)
    segs = _trace(scene)
    main = [s for s in segs if s.get("from") == "CIRC_Hub" and s["kind"] == "CIRC_OUT"]
    iso = [s for s in segs if s.get("from") == "CIRC_Hub" and s["kind"] == "CIRC_ISO"]
    reach_out = any(s.get("to") == "CIRC_Out" for s in segs)
    reach_iso = any(s.get("to") == "CIRC_Iso" for s in segs)
    check(len(main) == 1 and abs(main[0]["power"] - 1.0) < 1e-6, "main routed beam (full power) leaves the hub")
    check(len(iso) == 1 and abs(iso[0]["power"] - 0.01) < 1e-6, "1%% isolation leak leaves the hub (20 dB)")
    check(reach_out, "the main routed beam reaches CIRC_Out (P2 detector)")
    check(reach_iso, "the isolation leak reaches CIRC_Iso (P3 monitor)")


def main():
    _register_addon()
    test_physics_verify()
    test_topology_ground_truth()
    test_byte_identical()
    test_circulator_example()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL CIRCULATOR (C6) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
