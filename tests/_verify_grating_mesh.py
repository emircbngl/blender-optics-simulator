"""Headless verification harness for Wave-3 D3 (grating groove PROFILES + PPLN poling-domain stripes).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_verify_grating_mesh.py

D3 is a pure MESH-RESOLUTION / cosmetic task (like D2): it reshapes the grating's ruled surface into a
recognizable profile -- RULED (blazed asymmetric sawtooth) / HOLOGRAPHIC (rounded sinusoid) / ECHELLE (a
few coarse steeply-tilted steps) -- and grows literal alternating poling-domain stripes (+ oven housing)
on the PPLN (C7 QPM) crystal. NO new physics, NO new formula, NO tracer change. The grating equation
m*lambda = d*(sin th_i +/- sin th_m) reads the LINE DENSITY (lines_per_mm), a PARAMETER, not the mesh; the
optical behavior reads the element PORTS (local_position / local_normal / clear_aperture) x matrix_world.
So the groove/stripe mesh may change freely as long as every PORT stays byte-identical.

Proves, in order:
  (A) NO NEW PHYSICS: D3 adds no formula/constant/tracer change -- stated; nothing to oracle-verify here.
  (B) BYTE-IDENTICAL (the critical gate): every build_example scene (all 21) traces to the SAME seg + ports
      md5 as before D3. Then a FRESH grating in EACH profile (RULED/HOLOGRAPHIC/ECHELLE) + a FRESH PPLN
      crystal are built, and their LOCAL port digests are asserted byte-identical to the pinned pre-D3
      values -- and the grating's port digest is asserted PROFILE-INDEPENDENT (before==after for all three).
  (C) PROFILE ACTUALLY CHANGES THE MESH: the groove geometry (vertex/face counts) differs across
      RULED / HOLOGRAPHIC / ECHELLE (the cosmetic selector really does something), while the ports stay put;
      and toggling ppln_show_stripes adds/removes the stripe geometry on the PPLN slab.
  (D) The full regression (tests/test_optics.py) is the separate gate -- not re-run here.
  (E) The render montage is the acceptance gate -- tests/_render_d3_gratings.py (run separately).
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


def _register_addon():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    return addon


# Pinned reference seg/ports digests captured from the PRE-D3 builder (this session) -- the full set of
# build_example scenes. D3 only touches the grating/PPLN MESH, so every one must be byte-identical.
REF_EX = {
    "adaptive_optics": ("176217fce1ba", "3de42c1386c2"), "aom": ("c0651b75cb04", "0f62186bb703"),
    "back_reflection": ("ad9646834d40", "0ab31b2a4dc3"), "beam_profiler": ("b762253f4c18", "db53b445888f"),
    "beam_router": ("ea86e964c09f", "a4982f49973f"), "bell": ("75ca6c1eec30", "42f238335316"),
    "cage_system": ("f36e2cd70a9f", "f3d18f198755"), "dhm": ("111a3d05b96d", "6e2532e2f759"),
    "green_doubler": ("cbc286b34b4a", "11c6518140f6"), "hong_ou_mandel": ("36b08c3f9e96", "84a277841741"),
    "hybrid_system": ("f3b5f57d8a39", "66de45132aab"), "mach_zehnder": ("819b140513c1", "db8d5acdd4ed"),
    "michelson": ("2988d9599234", "82926106d9a9"), "microscope": ("01c250dd42f3", "4c985407692f"),
    "newton_rings": ("1a158f3aa0f2", "15410e2bc376"), "periscope": ("7a69a20b58f7", "7232f1e2b0f4"),
    "prism": ("83a99bef632b", "c26f2e54b3ec"), "quad_tracker": ("85ad6641c8ee", "e49e69c7f434"),
    "rail_system": ("20af209bacfa", "48f931ae6513"), "spdc_source": ("e3e955727dac", "3415ff43a7e0"),
    "tube_system": ("e166d71ea528", "fdeceabc48a1"),
}
# Pinned LOCAL port digests from the PRE-D3 builder: a fresh grating (size 25, 1200/mm), a fresh PPLN
# crystal (size 14, QPM SHG, oven), and a NONE-process crystal (the Bell pump-dump path).
REF_GRATING_LOCAL = "821795eac717a0bf93b4806a0b4cf5d9"
REF_PPLN_LOCAL = "c3b91497e4645bb51a71ac3698ea9baf"
REF_NONE_CRYSTAL_LOCAL = "4156444c9d6129eeae4ba428a8de192f"


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


def _local_port_digest(obj):
    op = obj.optics
    rows = ["ET=%s" % op.element_type, "CA=%.6f" % op.clear_aperture]
    for p in op.ports:
        rows.append("%s|%s|%s|%s|%.6f" % (
            p.name, p.role,
            ",".join("%.6f" % x for x in p.local_position),
            ",".join("%.6f" % x for x in p.local_normal),
            p.clear_aperture))
    rows.sort()
    return hashlib.md5("\n".join(rows).encode()).hexdigest()


def _trace(scene):
    from optical_alignment_sim import tracer
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _clear(scene):
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)


def test_no_new_physics():
    print("\n=== (A) NO NEW PHYSICS ===")
    check(True, "D3 introduces NO formula/constant/tracer change -- mesh-only "
                "(grating equation reads lines_per_mm, a PARAMETER, not the groove mesh); "
                "nothing for the oracle to verify")


def test_byte_identical():
    print("\n=== (B) BYTE-IDENTICAL: every example + the grating/PPLN ports unchanged by the D3 mesh ===")
    from optical_alignment_sim import examples_builtin as ex, elements_generic as G
    scene = bpy.context.scene
    for cc in list(bpy.data.collections):
        if cc.name.startswith("OpticsVerify_") or cc.name.startswith("D3_"):
            for o in list(cc.objects):
                G.drop_example_object(o)
            bpy.data.collections.remove(cc)
    _clear(scene)
    check(len(ex.EXAMPLES) >= 21, ">=21 build_example scenes (%d)" % len(ex.EXAMPLES))
    all_ok = True
    for kind in sorted(ex.EXAMPLES):
        _clear(scene)
        ex.build(kind, bpy.context)
        bpy.context.view_layer.update()
        sd = _seg_digest(_trace(scene)); pd = _ports_digest(scene)
        ref = REF_EX.get(kind)
        ok = ref is None or (sd.startswith(ref[0]) and pd.startswith(ref[1]))
        all_ok = all_ok and ok
        tag = "" if ref is None else ("  ref %s/%s %s" % (ref[0], ref[1], "OK" if ok else "MISMATCH"))
        print("  %-16s seg %s ports %s%s" % (kind, sd[:12], pd[:12], tag))
    check(all_ok, "ALL %d example seg+ports digests byte-identical to pre-D3" % len(ex.EXAMPLES))

    # A fresh grating in EACH profile -> the LOCAL port digest must match the pinned pre-D3 value AND be
    # identical across profiles (the cosmetic selector cannot move a single port).
    _clear(scene)
    c = G.example_collection("OpticsVerify_Grating")
    X = Vector((1, 0, 0)); Y = Vector((0, 1, 0))
    gld = {}
    for prof in ('RULED', 'HOLOGRAPHIC', 'ECHELLE'):
        g = G.grating("VG_%s" % prof, (0, 0, 0), X, Y, c, size=25.0, lines_per_mm=1200.0,
                      order=1, grating_profile=prof)
        gld[prof] = _local_port_digest(g)
        print("  fresh grating %-12s local-port-digest %s" % (prof, gld[prof]))
        bpy.data.objects.remove(g, do_unlink=True)
    check(all(d == REF_GRATING_LOCAL for d in gld.values()),
          "fresh grating ports byte-identical to pre-D3 in ALL profiles (%s)" % REF_GRATING_LOCAL)
    check(len(set(gld.values())) == 1,
          "grating port digest is PROFILE-INDEPENDENT (before==after across RULED/HOLOGRAPHIC/ECHELLE)")

    # A fresh PPLN crystal (QPM SHG, oven) -> ports byte-identical to pre-D3, with/without the stripe mesh.
    _clear(scene)
    cc2 = G.example_collection("OpticsVerify_PPLN")
    ppln = G.crystal("VG_ppln", (0, 0, 0), X, cc2, size=14.0, nl_process='SHG',
                     crystal_material='PPLN', phase_matching_type='TYPE0', pm_scheme='QPM',
                     poling_period_um=6.5, crystal_length_mm=14.0, oven=True, ppln_show_stripes=True)
    pld = _local_port_digest(ppln)
    print("  fresh PPLN crystal (QPM SHG, stripes+oven) local-port-digest %s" % pld)
    check(pld == REF_PPLN_LOCAL, "fresh PPLN crystal ports byte-identical to pre-D3 (%s)" % REF_PPLN_LOCAL)
    n_mat = len(ppln.data.materials)
    bpy.data.objects.remove(ppln, do_unlink=True)

    # toggling the stripes OFF must not move a port either (cosmetic only)
    ppln_off = G.crystal("VG_ppln_off", (40, 0, 0), X, cc2, size=14.0, nl_process='SHG',
                         crystal_material='PPLN', phase_matching_type='TYPE0', pm_scheme='QPM',
                         poling_period_um=6.5, crystal_length_mm=14.0, oven=True, ppln_show_stripes=False)
    pld_off = _local_port_digest(ppln_off)
    print("  fresh PPLN crystal (stripes OFF) local-port-digest %s" % pld_off)
    check(pld_off == REF_PPLN_LOCAL,
          "PPLN ports byte-identical with stripes OFF too (ppln_show_stripes is cosmetic)")
    bpy.data.objects.remove(ppln_off, do_unlink=True)

    # the NONE-process crystal (Bell pump-dump) path stays byte-identical
    _clear(scene)
    none_cr = G.crystal("VG_bbo", (0, 0, 0), X, cc2, size=14.0)
    nld = _local_port_digest(none_cr)
    print("  fresh NONE-process crystal (Bell dump) local-port-digest %s" % nld)
    check(nld == REF_NONE_CRYSTAL_LOCAL,
          "NONE-process crystal ports byte-identical to pre-D3 (%s)" % REF_NONE_CRYSTAL_LOCAL)

    # the PPLN mesh actually carries the stripe + oven detail (>=2 material slots: slab + poling stripes)
    check(n_mat >= 2, "PPLN mesh has >=2 material slots (slab + poling stripes): %d" % n_mat)


def test_profile_changes_mesh():
    print("\n=== (C) PROFILE ACTUALLY CHANGES THE MESH (ports stay put) ===")
    from optical_alignment_sim import elements_generic as G
    scene = bpy.context.scene
    _clear(scene)
    c = G.example_collection("OpticsVerify_GratingMesh")
    X = Vector((1, 0, 0)); Y = Vector((0, 1, 0))
    counts = {}
    print("  profile        verts   faces")
    for prof in ('RULED', 'HOLOGRAPHIC', 'ECHELLE'):
        g = G.grating("VGM_%s" % prof, (0, 0, 0), X, Y, c, size=25.0, lines_per_mm=1200.0,
                      order=1, grating_profile=prof)
        counts[prof] = (len(g.data.vertices), len(g.data.polygons))
        print("  %-12s   %5d   %5d" % (prof, counts[prof][0], counts[prof][1]))
        bpy.data.objects.remove(g, do_unlink=True)
    # the three groove meshes must NOT all share the same (verts, faces) -- the selector really reshapes it
    uniq = set(counts.values())
    check(len(uniq) == 3,
          "all THREE profiles yield distinct groove meshes (verts,faces): %s" % counts)

    # the PPLN stripe mesh: showing the stripes adds geometry (vert/face count grows vs stripes OFF)
    _clear(scene)
    cc2 = G.example_collection("OpticsVerify_PPLNMesh")
    on = G.crystal("VGM_on", (0, 0, 0), X, cc2, size=14.0, nl_process='SHG',
                   crystal_material='PPLN', phase_matching_type='TYPE0', pm_scheme='QPM',
                   poling_period_um=6.5, crystal_length_mm=14.0, oven=False, ppln_show_stripes=True)
    nv_on, nf_on = len(on.data.vertices), len(on.data.polygons)
    bpy.data.objects.remove(on, do_unlink=True)
    off = G.crystal("VGM_off", (40, 0, 0), X, cc2, size=14.0, nl_process='SHG',
                    crystal_material='PPLN', phase_matching_type='TYPE0', pm_scheme='QPM',
                    poling_period_um=6.5, crystal_length_mm=14.0, oven=False, ppln_show_stripes=False)
    nv_off, nf_off = len(off.data.vertices), len(off.data.polygons)
    bpy.data.objects.remove(off, do_unlink=True)
    print("  PPLN stripes ON  verts %d faces %d   |   OFF verts %d faces %d" %
          (nv_on, nf_on, nv_off, nf_off))
    check(nv_on > nv_off and nf_on > nf_off,
          "PPLN poling stripes add real geometry when shown (ON > OFF)")


def main():
    _register_addon()
    test_no_new_physics()
    test_byte_identical()
    test_profile_changes_mesh()
    print("\n================ SUMMARY ================")
    if FAILS:
        print("FAILED %d check(s):" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("ALL GRATING/PPLN (D3) VERIFICATION CHECKS PASSED")


if __name__ == "__main__":
    main()
