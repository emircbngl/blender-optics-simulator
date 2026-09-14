"""Unit equivalence: a declared metre scene must read the same physics as a millimetre scene.

Run:
    blender --background --factory-startup --python-exit-code 1 --python tests/test_units.py

The tracer has been unit-aware since #18/#23: in a scene that DECLARES its unit scale
(`scene.optics.scene_units_authoritative`) it converts world units to millimetres at the boundary,
and the element builders place millimetre arguments at their physical size. Everything around the
tracer was not. In a declared metre scene the path statistics came out 0.326 where the bench is
326 mm, a 1 mm lens decentre read as 0.001 mm and "OK", place_relative(100 mm) moved a part 100 m,
and a baked beam was 1000x too wide.

So this builds the SAME PHYSICAL bench twice -- once in a declared millimetre scene, once in a
declared metre scene -- and requires every user-visible output to agree in millimetres. The tracer's
own OPL and beam radius are included as controls: they already agree, and if they ever stop agreeing
every other row is meaningless.

Opto-mechanical hardware (breadboard, posts, rails) is refused in declared non-mm scenes by design
(optics_api._hardware_unsupported_here); that refusal is checked, not the hardware.
"""
import bpy, sys, os, math, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import optics_api as api, elements_generic as eg, geometry, tracer, alignment, mounts
from mathutils import Vector

_checks = []


def check(name, ok, detail=""):
    _checks.append((name, bool(ok)))
    print("  %-78s %s%s" % (name, "PASS" if ok else "FAIL", ("  <- " + detail) if not ok else ""))


def fresh(scale_length, name="UNITS"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = scale_length
    sc.optics.scene_units_authoritative = True
    coll = bpy.data.collections.new(name)
    sc.collection.children.link(coll)
    return sc, coll


def fold_bench(sl):
    sc, coll = fresh(sl)
    s = eg.source("S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    s.optics.waist_um = 400.0
    eg.mirror("M", (0.0, 0.0, 0.0), Vector((1, 0, 0)), Vector((0, 1, 0)), coll)
    eg.detector("D", (0.0, 200.0, 0.0), Vector((0, 1, 0)), coll)
    bpy.context.view_layer.update()
    return sc


def outputs(sl):
    """Every user-visible number on a set of small benches, in millimetres, for one unit scale."""
    out = {}
    sc = fold_bench(sl)
    mmpu = geometry.mm_per_unit(sc)
    segs = api._trace(sc)
    at_d = [x for x in segs if x["to"] == "D"][0]
    out["control: tracer OPL at D (mm)"] = at_d["opl"]
    out["control: tracer w at D (mm)"] = at_d["w_mm"]
    arr = api.path_statistics("D")["detectors"][0]["arrivals"][0]
    out["path_statistics geometric_length_mm"] = arr["geometric_length_mm"]
    out["path_statistics phase_opl_mm"] = arr["phase_opl_mm"]
    ib = api.inspect_beam("D")
    for k in ("w_mm", "R_mm", "dist_to_waist_mm", "waist_w0_mm"):
        out["inspect_beam %s" % k] = ib.get(k)
    bp = api.beam_profile("D")
    print("  (beam_profile keys: %s)" % sorted(bp.keys()))
    out["beam_profile element z_mm"] = [e.get("z_mm") for e in bp.get("elements", [])]
    api.bake_beams()
    bpy.context.view_layer.update()
    tube = bpy.data.objects.get("BEAM_01")
    zs = [(tube.matrix_world @ Vector(c)).z for c in tube.bound_box] if tube else [0.0]
    out["baked beam tube radius (physical mm)"] = 0.5 * (max(zs) - min(zs)) * mmpu
    api.clear_beams()
    D = bpy.data.objects["D"]
    D.location.x += 5.0 / mmpu
    bpy.context.view_layer.update()
    tracer.cached_segments = api._trace(sc)
    alignment.refresh_report(sc)
    out["report misalign_pos_mm, detector moved 5 mm"] = D.optics.misalign_pos_mm
    out["report align_state, detector moved 5 mm"] = D.optics.align_state
    D.location.x -= 5.0 / mmpu
    bpy.context.view_layer.update()
    ts = api.tolerance_scan(elements=["M"], target="D", sigma_pos_mm=0.1, sigma_ang_deg=0.0, n=20, seed=3)
    out["tolerance_scan pointing_rms_mm"] = ts.get("pointing_rms_mm")
    out["tolerance_scan hit_rate"] = ts.get("hit_rate")
    out["dress_bench refused in a non-mm declared scene"] = ("error" in api.dress_bench(True)) if mmpu != 1.0 else True

    # placement: a lens 100 mm along the source beam
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    s = eg.source("S", (0.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    L = eg.lens("L", (30.0, 0.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0)
    bpy.context.view_layer.update()
    api.place_relative("L", "S", axis='BEAM', distance=100.0, link=False)
    bpy.context.view_layer.update()
    outp = next(p for p in s.optics.ports if p.role == 'OUT')
    out["place_relative(distance=100 mm) -> physical mm"] = (
        L.matrix_world.translation - geometry.world_port(s, outp.local_position)).length * mmpu

    # a translation knob documented in millimetres
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    eg.source("S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    L = eg.lens("L", (0.0, 0.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0)
    bpy.context.view_layer.update()
    p0 = L.matrix_world.translation.copy()
    mounts.store_base_matrix(L.optics, L.matrix_world.copy())
    L.optics.base_pose_set = True
    dof = L.optics.dofs.add(); dof.kind = 'TRANS_Y'; dof.name = 'TRANS_Y'
    dof.axis_local = (0.0, 1.0, 0.0); dof.min_val = -4.0; dof.max_val = 4.0
    dof.current = 1.0
    mounts.compose_pose(L)
    bpy.context.view_layer.update()
    out["translation knob current=1.0 -> physical mm"] = (L.matrix_world.translation - p0).length * mmpu

    # diagnose: a hard miss and a detuned relay
    sc, coll = fresh(sl)
    s = eg.source("S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll); s.optics.waist_um = 400.0
    eg.lens("L", (0.0, 16.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0, radius=14.0)
    bpy.context.view_layer.update()
    out["diagnose beam_clipped count (16 mm off an r=14 lens)"] = sum(
        1 for x in api.diagnose()["diagnostics"] if x["kind"] == "beam_clipped")
    sc, coll = fresh(sl)
    s = eg.source("S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll); s.optics.waist_um = 1000.0
    eg.lens("L1", (0.0, 0.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0)
    eg.lens("L2", (205.0, 0.0, 0.0), Vector((1, 0, 0)), coll, focal=100.0)
    eg.detector("D", (400.0, 0.0, 0.0), Vector((1, 0, 0)), coll)
    bpy.context.view_layer.update()
    out["diagnose relay_spacing count (4f relay detuned 5 mm)"] = sum(
        1 for x in api.diagnose()["diagnostics"] if x["kind"] == "relay_spacing")

    # a vendor mesh from disk: a 25.4 mm x 6 mm disc written as ASCII STL, mm-authored like vendor CAD
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    stl = os.path.join(tempfile.gettempdir(), "oas_units_disc.stl")
    _write_disc_stl(stl, 12.7, 6.0)
    from optical_alignment_sim import library
    library.BUILTIN["UNITS_TEST_DISC"] = {"label": "t", "vendor": "t", "mesh": stl, "format": "stl",
                                          "name": "M_TEST", "element_type": "MIRROR"}
    library._catalog_cache = None; library._catalog_cache_key = None
    r = api.add_component("UNITS_TEST_DISC", location=(0.0, 50.0, 0.0))
    o = bpy.data.objects.get(r.get("name", ""))
    bpy.context.view_layer.update()
    out["add_component vendor STL: largest dimension (physical mm)"] = (max(o.dimensions) * mmpu) if o else None
    out["add_component vendor STL: location y (physical mm)"] = (o.matrix_world.translation.y * mmpu) if o else None
    out["add_component raises no unit-mismatch warning when the scene declared its units"] = "warning" not in r

    # the Build Example operator
    sc, coll = fresh(sl)
    out["optics_api.build_example raises no unit-mismatch warning in a declared scene"] = (
        "warning" not in api.build_example("michelson"))
    sc, coll = fresh(sl)
    bpy.ops.optics.build_example(kind='michelson')
    segs = api._trace(sc)
    out["build_example(michelson) operator: first segment OPL mm"] = segs[0]["opl"] if segs else None
    out["build_example keeps the declaration consistent (mm_per_unit unchanged)"] = (
        abs(geometry.mm_per_unit(sc) - (1000.0 * sl)) < 1e-6)

    # the fringe image on a detector the beams hit OFF its centre (the ring centre follows the hit point)
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    api.build_example("michelson")
    det = bpy.data.objects["MI_D"]
    det.location.x += 2.0 / mmpu
    bpy.context.view_layer.update()
    from optical_alignment_sim import scan as _scan
    import numpy as _np
    _arr, _nb = _scan._fringe_array(det, api._trace(sc), 6.0, 64)
    if _arr is not None:
        _I = _np.asarray(_arr)[..., 0] if _np.asarray(_arr).ndim == 3 else _np.asarray(_arr)
        _yy, _xx = _np.mgrid[0:_I.shape[0], 0:_I.shape[1]]
        _tot = float(_I.sum()) or 1.0
        out["fringe image (michelson, detector 2 mm off the hit): centroid px"] = [
            round(float((_I * _xx).sum() / _tot), 3), round(float((_I * _yy).sum() / _tot), 3)]
    else:
        out["fringe image (michelson, detector 2 mm off the hit): centroid px"] = None

    # the alignment solver's aperture miss on an iris 0.3 mm off the beam
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    eg.source("S", (-150.0, 0.0, 0.0), Vector((1, 0, 0)), coll).optics.waist_um = 400.0
    _iris = eg.aperture("A", (0.0, 0.0, 0.0), Vector((1, 0, 0)), coll, radius=5.0)
    bpy.context.view_layer.update()
    _iris.location.y += 0.3 / mmpu
    bpy.context.view_layer.update()
    from optical_alignment_sim import solvers as _solvers
    out["solver aperture_residual, iris 0.3 mm off (mm)"] = _solvers.aperture_residual(api._trace(sc), _iris)

    # the zonal surface-imprint render reads the mirror's figure over the beam footprint
    sc, coll = fresh(sl)
    mmpu = geometry.mm_per_unit(sc)
    api.build_example("surface_figure")
    for _o in sc.objects:          # off the origin (where world units and mm coincide) and ACROSS the beam: a shift
        if _o.parent is None:      # along it leaves a probe fired down the beam hitting the same spot either way
            _o.location += Vector((250.0, 250.0, 40.0)) / mmpu
    bpy.context.view_layer.update()
    _z = api.zonal_render(sensor="SF_WFS", px=48, filepath=os.path.join(tempfile.gettempdir(), "oas_units_zonal_%g.png" % sl))
    out["zonal_render footprint_mm"] = _z.get("footprint_mm")
    out["zonal_render rms_gauss (waves)"] = _z.get("rms_gauss")
    out["zonal_render hit_frac"] = _z.get("hit_frac")

    # convert_scene_to_mm must not change the physics of a bench that already declared its units
    sc = fold_bench(sl)
    before = [x["opl"] for x in api._trace(sc) if x["to"] == "D"]
    api.convert_scene_to_mm()
    bpy.context.view_layer.update()
    after = [x["opl"] for x in api._trace(sc) if x["to"] == "D"]
    # relative 1e-6: a metre scene holds positions in float32, which leaves ~3e-5 mm on a 326 mm path
    out["convert_scene_to_mm keeps OPL at D"] = (bool(before) and bool(after)
                                                 and abs(before[0] - after[0]) <= 1e-6 * max(1.0, abs(before[0])))
    return out


def _write_disc_stl(path, r, t, n=48):
    tri = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0, p1 = (r * math.cos(a0), r * math.sin(a0)), (r * math.cos(a1), r * math.sin(a1))
        for z, flip in ((t / 2, False), (-t / 2, True)):
            f = [(0.0, 0.0, z), (p0[0], p0[1], z), (p1[0], p1[1], z)]
            tri.append(f[::-1] if flip else f)
        tri.append([(p0[0], p0[1], -t / 2), (p1[0], p1[1], -t / 2), (p1[0], p1[1], t / 2)])
        tri.append([(p0[0], p0[1], -t / 2), (p1[0], p1[1], t / 2), (p0[0], p0[1], t / 2)])
    with open(path, "w") as fh:
        fh.write("solid disc\n")
        for f in tri:
            fh.write(" facet normal 0 0 0\n  outer loop\n")
            for v in f:
                fh.write("   vertex %f %f %f\n" % v)
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid disc\n")


def _same(a, b, rel=1e-4, absol=1e-6):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y, rel, absol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or a is None or b is None:
        return a == b
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


print("[unit equivalence: declared millimetre scene vs declared metre scene, same physical bench]")
mm = outputs(0.001)
m = outputs(1.0)
# A metre scene stores the imprinted mirror's vertices in float32 at ~1e-2 world units; resampled in mm that is
# worth ~2e-4 of a 2-wave surface RMS. Wider than the default, still 1000x under the unit error it guards.
_REL = {"zonal_render rms_gauss (waves)": 1e-3}
for key in mm:
    check(key, _same(mm[key], m.get(key), rel=_REL.get(key, 1e-4)), "mm scene %r vs metre scene %r" % (mm[key], m.get(key)))

print("[convert_scene_to_mm scales keyframes with the objects]")
# Before: a metre scene with an animated object read 2.0 m right after converting and 0.002 m after one frame
# change, because the location keys were never scaled and the next frame replayed them.
sc, coll = fresh(1.0)
sc.optics.scene_units_authoritative = False            # the intended use: an undeclared metre scene
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(2.0, 0.0, 0.0))
_cube = bpy.context.active_object
sc.frame_set(1); _cube.keyframe_insert("location", frame=1)
_cube.location = (3.0, 0.0, 0.0); _cube.keyframe_insert("location", frame=20)
sc.frame_set(1)
api.convert_scene_to_mm()
sc.frame_set(2); sc.frame_set(1)
bpy.context.view_layer.update()
_x_m = _cube.matrix_world.translation.x * sc.unit_settings.scale_length
check("an animated object is still 2.0 m away after converting and changing frame", abs(_x_m - 2.0) < 1e-4,
      "%.6f m" % _x_m)

oas.unregister()
passed = sum(1 for _, ok in _checks if ok)
fails = [n for n, ok in _checks if not ok]
print("=" * 60)
if fails:
    print("UNITS FAIL  (%d/%d)  failed: %s" % (passed, len(_checks), ", ".join(fails)))
else:
    print("UNITS PASS  (%d/%d checks)" % (passed, len(_checks)))
sys.exit(len(fails))
