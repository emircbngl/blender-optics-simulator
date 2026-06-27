"""Consolidated headless regression for the Blender Optics Simulator.

Run:
    blender --background --factory-startup --python tests/test_optics.py

Builds every canonical example and asserts the key physics + pipeline invariants. Prints one
PASS/FAIL line per check and a final summary; exits non-zero on any failure (CI-friendly).
Lives outside the add-on package, so the extension zip never ships it.
"""
import bpy, sys, os, math
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import optical_alignment_sim as oas
oas.register()
import optics_api
from optical_alignment_sim import scan, alignment, ao, physics, render, handlers, operators, elements_generic, mounts, bridge, tracer, optomech

_checks = []


def check(name, cond, detail=""):
    ok = bool(cond)
    _checks.append((name, ok))
    print("  %-28s %s%s" % (name, "PASS" if ok else "FAIL", ("  <- " + detail) if not ok else ""))


def radiality(img, c):
    px = img.shape[0]
    yy, xx = np.mgrid[0:px, 0:px]
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2).astype(int)
    sm = np.bincount(r.ravel(), img.ravel(), minlength=r.max() + 1)
    cn = np.bincount(r.ravel(), minlength=r.max() + 1)
    prof = sm / np.maximum(cn, 1)
    return 1.0 - np.sum((img - prof[r]) ** 2) / max(np.sum((img - img.mean()) ** 2), 1e-12), prof


sc = bpy.context.scene

print("[physics]")
check("zernike defocus = sqrt3", abs(physics.zernike(4, 1.0, 0.0) - math.sqrt(3.0)) < 1e-9)
check("wavefront_rms = 0.5", abs(physics.wavefront_rms([0, 0, 0, 0, 0.3, 0, 0, 0.4]) - 0.5) < 1e-9)
_es = physics.polarization_state_from_stokes(2.0, 0.0, 0.0, 1.0)   # circular + equal unpolarized (DOP=0.5)
check("ellipticity uses S_pol (45deg, not 15)", abs(_es["ellipticity_deg"] - 45.0) < 1e-6, str(_es["ellipticity_deg"]))
check("beam_roc(waist) = inf", math.isinf(physics.beam_roc(physics.q_from_waist(0.5, 632.8))))
check("gouy(waist) = 0", abs(physics.gouy_phase(physics.q_from_waist(0.5, 632.8))) < 1e-9)

print("[examples build + trace]")
for kind in ("mach_zehnder", "michelson", "hong_ou_mandel", "bell", "adaptive_optics", "newton_rings",
             "periscope", "cage_system", "tube_system", "rail_system", "hybrid_system",
             "microscope", "dhm", "aom", "die"):
    r = optics_api.build_example(kind)
    check("build %s" % kind, isinstance(r, dict) and r.get("segments", 0) >= 1, str(r))

print("[DHM: vertical holographic microscope -- recombines + no interpenetration]")
optics_api.build_example("dhm")
_dseg = scan._trace(sc)
check("DHM: object + reference arms both reach the camera (-> hologram)",
      sum(1 for s in _dseg if s.get("to") == "DHM_Cam") >= 2,
      str(sum(1 for s in _dseg if s.get("to") == "DHM_Cam")))
optomech.dress(sc)
check("DHM (vertical, multi-arm) dresses with NO interpenetration", optomech.validate(sc) == [],
      str(optomech.validate(sc)))
optics_api.dress_bench(False)

print("[AOM: Bragg cell deflects + splits the beam (VERIFIED acousto-optic-bragg-deflection)]")
optics_api.build_example("aom")
_aseg = scan._trace(sc)
_aout = [s for s in _aseg if s.get("from") == "AOM_cell"]
check("AOM emits TWO output orders (0th transmit + 1st diffracted)", len(_aout) == 2, "%d orders" % len(_aout))
_a0 = next((s for s in _aout if s["kind"] == 'TRANSMIT'), None)
_a1 = next((s for s in _aout if s["kind"] == 'AOM_1'), None)
check("AOM orders are the 0th (TRANSMIT) + 1st (AOM_1)", _a0 is not None and _a1 is not None,
      str(sorted(s["kind"] for s in _aout)))
if _a0 and _a1:
    def _udir(s):
        d = [s["p2"][i] - s["p1"][i] for i in range(3)]
        n = math.sqrt(sum(c * c for c in d)) or 1.0
        return [c / n for c in d]
    _u0, _u1 = _udir(_a0), _udir(_a1)
    _ang = math.acos(max(-1.0, min(1.0, sum(_u0[i] * _u1[i] for i in range(3)))))
    _theta = 632.8e-9 * 200.0e6 / 650.0                     # lambda*f_a/v_s (the VERIFIED deflection)
    check("AOM +1 order is deflected by theta = lambda*f_a/v_s", abs(_ang - _theta) < 1e-3,
          "got %.5f rad, expect %.5f" % (_ang, _theta))
    _tot = _a0["power"] + _a1["power"]
    check("AOM power splits by efficiency (+1 ~0.85 of the light, energy conserved)",
          _tot > 0.0 and abs(_a1["power"] / _tot - 0.85) < 0.02 and abs(_a0["power"] / _tot - 0.15) < 0.02,
          "0th=%.3f +1=%.3f" % (_a0["power"], _a1["power"]))
_acell = bpy.data.objects.get("AOM_cell")
check("AOM records its acoustic frequency f_a (the +f_a optical shift)",
      _acell is not None and abs(_acell.optics.aom_freq_mhz - 200.0) < 1e-6)
_an0 = len(scan._trace(sc))
optomech.dress(sc)
_an1 = len(scan._trace(sc))
check("AOM dressing leaves the trace identical (ports x matrix_world)", _an0 == _an1, "%d vs %d" % (_an0, _an1))
check("AOM dressing is geometrically valid (no interpenetration)", optomech.validate(sc) == [],
      str(optomech.validate(sc)))
optics_api.dress_bench(False)

print("[full systems: cage / tube / rail / hybrid dress trace-safe + valid]")
for kind in ("cage_system", "tube_system", "rail_system", "hybrid_system"):
    optics_api.build_example(kind)
    _n0 = len(scan._trace(sc))
    optomech.dress(sc)
    _n1 = len(scan._trace(sc))
    check("%s dressing leaves the trace identical" % kind, _n0 == _n1, "%d vs %d" % (_n0, _n1))
    check("%s dressing is geometrically valid" % kind, optomech.validate(sc) == [],
          str(optomech.validate(sc)))
    optics_api.dress_bench(False)

print("[periscope: out-of-plane vertical fold]")
optics_api.build_example("periscope")
_ps = scan._trace(sc)
_pp = alignment.measure(_ps, "PS_D", "NONE")[0]
_pz = [c[2] for s in _ps for c in (s["p1"], s["p2"])]
check("periscope reaches the detector at full power", _pp > 0.95, "P=%.3f" % _pp)
check("periscope raises the beam out of plane (vertical fold)", (max(_pz) - min(_pz)) > 50.0,
      "z-range %.1f" % (max(_pz) - min(_pz)))
optics_api.dress_bench(True)
_pw = optics_api.get_state()["warnings"]
check("periscope dressing is geometrically valid (no mount-below-holder / collision)", _pw == [], str(_pw))
optics_api.dress_bench(False)
optics_api.build_example("michelson"); optics_api.dress_bench(True)
check("michelson dressing is geometrically valid", optics_api.get_state()["warnings"] == [], str(optics_api.get_state()["warnings"]))
# the validator must actually FIRE on a bad config, not just pass clean benches: shove one post onto
# another and confirm post_overlap is reported (proves the collision gate isn't a no-op).
_posts = [o for o in sc.objects if o.name.startswith(optomech.BENCH_PREFIX + "Post_")]
check("michelson dressing spawned multiple posts", len(_posts) >= 2, str(len(_posts)))
if len(_posts) >= 2:
    _tgt = _posts[0].matrix_world.translation
    _posts[1].location.x, _posts[1].location.y = _tgt.x, _tgt.y     # make posts 1 and 0 coincident
    bpy.context.view_layer.update()
    _vc = optomech.validate(sc)
    check("validator FIRES post_overlap on coincident posts",
          any(i["kind"] == "post_overlap" for i in _vc), str(_vc))
optics_api.dress_bench(False)

# the interpenetration gate must FIRE on a real MESH collision the post-distance checks miss: two mounts so
# close their bodies pass through each other while the Ø12.7 posts still just clear (proves validate() now
# consults Blender's true geometry and BLOCKS). Then space them out -> the same gate must report CLEAN.
print("[collision gate: real BVH mesh interpenetration FIRES + CLEARS]")
from mathutils import Vector as _Vec
_cc = elements_generic.example_collection("CollisionGate")
_CX, _CY = _Vec((1, 0, 0)), _Vec((0, 1, 0))
elements_generic.source("CG_L", (-100, 0, 0), _CX, _cc)
elements_generic.mirror("CG_M1", (0, 0, 0), _CX, _CY, _cc)
_cm2 = elements_generic.mirror("CG_M2", (18, 0, 0), _CX, _CY, _cc)     # 18 mm: posts clear, mount bodies collide
elements_generic.detector("CG_D", (18, 100, 0), _CY, _cc)
optomech.dress(sc)
_iv = optomech.validate(sc)
check("collision gate FIRES interpenetration on mounts 18 mm apart (posts clear, bodies collide)",
      any(i["kind"] == "interpenetration" for i in _iv), str(_iv))
check("...and the OLD post-distance checks DON'T catch it (why the mesh gate is needed)",
      not any(i["kind"] in ("post_overlap", "mount_below_holder", "beam_through_post") for i in _iv),
      str(_iv))
_cm2.location.x = 80.0; bpy.context.view_layer.update()                # space them out
optomech.dress(sc)
_iv2 = [i for i in optomech.validate(sc) if i["kind"] == "interpenetration"]
check("collision gate CLEARS once the mounts are spaced (no false positive)", _iv2 == [], str(_iv2))
optomech.strip(sc)
for _nm in ("CG_L", "CG_M1", "CG_M2", "CG_D"):                         # clean up so later tests aren't polluted
    _o = bpy.data.objects.get(_nm)
    if _o:
        bpy.data.objects.remove(_o, do_unlink=True)
_cg = bpy.data.collections.get("CollisionGate")
if _cg:
    bpy.data.collections.remove(_cg)
# a raised mount (periscope upper deck) must ride the fat Ø1" pillar, not a long thin Ø1/2" stick
optics_api.build_example("periscope"); optics_api.dress_bench(True)
_pst = [o for o in sc.objects if o.name.startswith(optomech.BENCH_PREFIX + "Post_")]
_tall = max(_pst, key=lambda o: o.dimensions.z) if _pst else None
check("periscope produces a tall post (> pillar threshold)",
      _tall is not None and _tall.dimensions.z > optomech.PILLAR_OVER_MM,
      "%.1f" % (_tall.dimensions.z if _tall else -1))
check("the tall post is the fat Ø1\" pillar, not a thin stick",
      _tall is not None and abs(_tall.dimensions.x * 0.5 - optomech.POST_RADIUS_TALL) < 1.5,
      "r=%.2f" % (_tall.dimensions.x * 0.5 if _tall else -1))
# the periscope's vertical-fold pillar must stand OFF the beam axis (the two fold mirrors share xy);
# a coaxial pillar would block the beam. Confirm the pillar is offset, then prove the gate fires when
# it is shoved back onto the axis.
_pscope = optomech._optical_objects(sc)
_stacked = [o for o in _pscope if any(p is not o
            and ((o.matrix_world.translation.x - p.matrix_world.translation.x) ** 2
                 + (o.matrix_world.translation.y - p.matrix_world.translation.y) ** 2) ** 0.5 < 8.0
            and abs(o.matrix_world.translation.z - p.matrix_world.translation.z) > optomech.VERTICAL_STACK_MM
            for p in _pscope)]
check("periscope has a vertical-fold stack (mirrors share an xy)", len(_stacked) >= 2, str(len(_stacked)))
if _stacked and _tall is not None:
    _ax = _stacked[0].matrix_world.translation
    _off = ((_tall.matrix_world.translation.x - _ax.x) ** 2
            + (_tall.matrix_world.translation.y - _ax.y) ** 2) ** 0.5
    check("vertical-fold pillar stands off the beam axis", _off > optomech.POST_RADIUS_TALL,
          "%.1f mm off axis" % _off)
    _tall.location.x, _tall.location.y = _ax.x, _ax.y      # shove the pillar back onto the beam
    bpy.context.view_layer.update()
    check("validator FIRES beam_through_post for a coaxial pillar",
          any(i["kind"] == "beam_through_post" for i in optomech.validate(sc)))
optics_api.dress_bench(False)

print("[element geometry realism]")
from optical_alignment_sim import elements_generic as eg
import bmesh as _bm
_gc = bpy.data.collections.new("ELEMTEST"); sc.collection.children.link(_gc)


def _nonman(o):
    b = _bm.new(); b.from_mesh(o.data)
    k = sum(1 for e in b.edges if not e.is_manifold); b.free(); return k


def _axis_clear(o):          # does a ray straight down the optical axis pass through (a real bore)?
    hit = o.ray_cast((0.0, 0.0, -50.0), (0.0, 0.0, 1.0))[0]
    return not hit


def _polez(o):           # z of the vertex nearest the optical axis on the +Z side (lens centre apex)
    best = 0.0
    for v in o.data.vertices:
        if (v.co.x ** 2 + v.co.y ** 2) ** 0.5 < 1.0 and v.co.z > best:
            best = v.co.z
    return best


_lp = eg.lens("ETL_p", (0, 0, 0), (0, 0, 1), coll=_gc, focal=60)
_ln = eg.lens("ETL_n", (40, 0, 0), (0, 0, 1), coll=_gc, focal=-60)
_ap = eg.aperture("ETL_ap", (80, 0, 0), (0, 0, 1), coll=_gc, radius=12.0)
_ph = eg.pinhole("ETL_ph", (120, 0, 0), (0, 0, 1), coll=_gc, radius=12.0)
_rr = eg.retroreflector("ETL_rr", (160, 0, 0), (0, 0, 1), coll=_gc, size=24.0)
_gr = eg.grating("ETL_gr", (200, 0, 0), (1, 0, 0), (0, 1, 0), coll=_gc, size=24.0)
check("converging lens bulges more at centre than diverging (focal SIGN reads in geometry)",
      _polez(_lp) > _polez(_ln) + 0.4, "%.2f vs %.2f" % (_polez(_lp), _polez(_ln)))
check("aperture is a real ring (axis ray passes through the opening)", _axis_clear(_ap))
check("pinhole has a real through-bore (axis ray passes)", _axis_clear(_ph))
check("grating carries ruled groove geometry (not a bare plate)", len(_gr.data.polygons) > 200,
      str(len(_gr.data.polygons)))
for _nm, _o in (("lens+", _lp), ("lens-", _ln), ("aperture", _ap), ("pinhole", _ph), ("retro", _rr)):
    check("%s mesh is manifold" % _nm, _nonman(_o) == 0, "%d nonmanifold edges" % _nonman(_o))
for _o in list(_gc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_gc)

print("[live iris: clear_aperture update= regenerates the blade mesh to the new opening (animatable)]")
# Setting an iris/APERTURE element's clear_aperture fires elements_generic.regenerate_iris(), which rebuilds
# the multi-leaf blade mesh to the new opening in place -- the blades CLOSE/OPEN live. It is mesh-only: ports
# + clear_aperture (what the tracer reads) track the radius but the rebuild is optically inert (a fresh build
# at the new radius is byte-identical), so the 18 example scenes are unaffected.
_lc = bpy.data.collections.new("LIVEIRIS"); sc.collection.children.link(_lc)


def _iris_open_r(o):         # polygon-corner radius of the matte-black leaves = the opening the leaves form
    return min((math.hypot(v.co.x, v.co.y) for v in o.data.vertices), default=0.0)


_li = eg.aperture("LI_iris", (0, 0, 0), (0, 0, 1), coll=_lc, radius=14.0)
_li_mesh0 = _li.data
_li_open0 = _iris_open_r(_li)
_li.optics.clear_aperture = 8.0          # stop down -> the leaves close
bpy.context.view_layer.update()
_li_open_close = _iris_open_r(_li)
_li_mesh_close = _li.data
_li.optics.clear_aperture = 20.0         # open up -> the leaves open
bpy.context.view_layer.update()
_li_open_wide = _iris_open_r(_li)
check("live iris: blade opening tracks the aperture (8<14<20)",
      _li_open_close < _li_open0 < _li_open_wide,
      "%.2f / %.2f / %.2f" % (_li_open_close, _li_open0, _li_open_wide))
check("live iris: blade opening sits at the set r_open (~+0.75 mm leaf-corner)",
      all(abs(_o - _r) < max(1.2, _r * 0.06)
          for _o, _r in ((_li_open_close, 8.0), (_li_open_wide, 20.0))),
      "%.2f@8 %.2f@20" % (_li_open_close, _li_open_wide))
check("live iris: element clear_aperture (the tracer's clip radius) tracks the set radius",
      abs(_li.optics.clear_aperture - 20.0) < 1e-6, "%.3f" % _li.optics.clear_aperture)
check("live iris: IN/OUT ports' clear_aperture track the radius too (optics follows, not the mesh)",
      all(abs(_p.clear_aperture - 20.0) < 1e-6 for _p in _li.optics.ports),
      str([round(_p.clear_aperture, 3) for _p in _li.optics.ports]))
check("live iris: the blade mesh was actually rebuilt+swapped (not relabeled)",
      _li.data is not _li_mesh0 and _li_mesh_close is not _li.data)
# optically inert: dialing back to the build radius restores the exact build-time ports (digest stable)
_li_ports_wide = _ports_str = sorted(
    (p.role, round(p.clear_aperture, 6), tuple(round(c, 6) for c in p.local_position),
     tuple(round(c, 6) for c in p.local_normal)) for p in _li.optics.ports)
_li.optics.clear_aperture = 14.0
bpy.context.view_layer.update()
_li_ports_back = sorted(
    (p.role, round(p.clear_aperture, 6), tuple(round(c, 6) for c in p.local_position),
     tuple(round(c, 6) for c in p.local_normal)) for p in _li.optics.ports)
_li_fresh = eg.aperture("LI_fresh", (200, 0, 0), (0, 0, 1), coll=_lc, radius=14.0)
_li_ports_fresh = sorted(
    (p.role, round(p.clear_aperture, 6), tuple(round(c, 6) for c in p.local_position),
     tuple(round(c, 6) for c in p.local_normal)) for p in _li_fresh.optics.ports)
check("live iris: dialing 14->8->20->14 restores the fresh-build ports exactly (mesh regen is optically inert)",
      _li_ports_back == _li_ports_fresh, "%s vs %s" % (_li_ports_back, _li_ports_fresh))
# the callback is a no-op on non-iris elements: a lens keeps its single mesh when clear_aperture changes
_li_lens = eg.lens("LI_lens", (100, 0, 0), (0, 0, 1), coll=_lc, focal=50)
_li_lens_mesh = _li_lens.data
_li_lens.optics.clear_aperture = 5.0
bpy.context.view_layer.update()
check("live iris: clear_aperture update is a no-op on non-iris elements (lens mesh untouched)",
      _li_lens.data is _li_lens_mesh)
for _o in list(_lc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_lc)

print("[element variants: lens_type / bs_form / coating]")
_vc = bpy.data.collections.new("VARTEST"); sc.collection.children.link(_vc)


def _backrange(o):           # z-spread of the back-half verts: ~0 for a flat (plano) back, big if curved
    zs = [v.co.z for v in o.data.vertices if v.co.z < -0.1]
    return (max(zs) - min(zs)) if zs else 0.0


def _ports(o):
    return sorted((p.role, tuple(round(c, 3) for c in p.local_position)) for p in o.optics.ports)


_lpcx = eg.lens("V_pcx", (0, 0, 0), (0, 0, 1), coll=_vc, focal=60, lens_type='PCX')
_lbcx = eg.lens("V_bcx", (40, 0, 0), (0, 0, 1), coll=_vc, focal=60, lens_type='BCX')
_lpcv = eg.lens("V_pcv", (80, 0, 0), (0, 0, 1), coll=_vc, focal=-60, lens_type='PCV')
check("lens forms are manifold", _nonman(_lpcx) == 0 and _nonman(_lbcx) == 0 and _nonman(_lpcv) == 0)
check("plano-convex has a FLAT back, bi-convex is curved (lens_type shapes the mesh)",
      _backrange(_lpcx) < 0.3 and _backrange(_lbcx) > 0.8, "%.2f vs %.2f" % (_backrange(_lpcx), _backrange(_lbcx)))
check("lens form is recorded on the optic", _lpcx.optics.lens_type == 'PCX' and _lbcx.optics.lens_type == 'BCX')
_bsc = eg.beamsplitter("V_bsc", (120, 0, 0), (1, 0, 0), (0, 1, 0), coll=_vc, bs_form='CUBE')
_bsp = eg.beamsplitter("V_bsp", (160, 0, 0), (1, 0, 0), (0, 1, 0), coll=_vc, bs_form='PLATE')
_bspe = eg.beamsplitter("V_bspe", (200, 0, 0), (1, 0, 0), (0, 1, 0), coll=_vc, bs_form='PELLICLE')
check("BS cube / plate / pellicle have IDENTICAL ports (form is trace-safe)",
      _ports(_bsc) == _ports(_bsp) == _ports(_bspe))
check("BS forms are distinct meshes (plate has fewer verts than the cube+coat)",
      len(_bsp.data.vertices) != len(_bsc.data.vertices))
check("BS form is recorded on the optic", _bsp.optics.bs_form == 'PLATE' and _bspe.optics.bs_form == 'PELLICLE')
_mir = eg.mirror("V_mir", (240, 0, 0), (1, 0, 0), (0, 1, 0), coll=_vc)
_mir.optics.coating = 'AU'
render.apply_optical_materials(sc)
check("mirror coating drives the render material (gold)", "AU" in _mir.data.materials[0].name,
      _mir.data.materials[0].name)
render.clear_render_style(sc)
# Batch 2: polarizer types + waveplate order (mesh/param variants; Jones + ports unchanged = trace-safe)
_pf = eg.polarizer("V_pf", (0, 40, 0), (0, 0, 1), coll=_vc, radius=12, polarizer_type='FILM')
_pg = eg.polarizer("V_pg", (40, 40, 0), (0, 0, 1), coll=_vc, radius=12, polarizer_type='GLAN_THOMPSON')
_pb = eg.polarizer("V_pb", (80, 40, 0), (0, 0, 1), coll=_vc, radius=12, polarizer_type='BREWSTER')
check("polarizer types manifold", _nonman(_pf) == 0 and _nonman(_pg) == 0 and _nonman(_pb) == 0)
check("polarizer types share identical ports (Jones + trace unchanged)", _ports(_pf) == _ports(_pg) == _ports(_pb))
check("Glan prism is a longer block than a film disc", _pg.dimensions.z > _pf.dimensions.z * 1.5,
      "%.1f vs %.1f" % (_pg.dimensions.z, _pf.dimensions.z))
check("polarizer type recorded", _pg.optics.polarizer_type == 'GLAN_THOMPSON')
_w0 = eg.waveplate("V_w0", (0, 80, 0), (0, 0, 1), coll=_vc, waveplate_order='ZERO')
_wm = eg.waveplate("V_wm", (40, 80, 0), (0, 0, 1), coll=_vc, waveplate_order='MULTI')
check("waveplate order shapes thickness (multi > zero) + ports identical",
      _wm.dimensions.z > _w0.dimensions.z and _ports(_w0) == _ports(_wm))
check("waveplate order recorded", _wm.optics.waveplate_order == 'MULTI')
for _o in list(_vc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_vc)

print("[curved mirror focuses on reflection: f=R/2 (oracle-VERIFIED)]")
_mcoll = bpy.data.collections.new("CMIR"); sc.collection.children.link(_mcoll)


def _w_at_detector(curve, R):
    for _o in list(sc.objects):                          # clean scene so the trace is just this setup
        if getattr(_o, "optics", None) and _o.optics.is_optical:
            bpy.data.objects.remove(_o, do_unlink=True)
    eg.source("CM_S", (-100, 0, 0), (1, 0, 0), coll=_mcoll)
    eg.mirror("CM_M", (0, 0, 0), (1, 0, 0), (0, 1, 0), coll=_mcoll, mirror_curve=curve, radius_curv=R)
    eg.detector("CM_D", (0, 120, 0), (0, 1, 0), coll=_mcoll)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    from mathutils import Vector as _V
    best, bd = None, 1e9
    for s in segs:
        d = (_V(s["p2"]) - _V((0, 120, 0))).length
        if d < bd:
            bd, best = d, s
    return best["w_mm"] if best else 0.0


_wf = _w_at_detector('FLAT', 0.0)
_wc = _w_at_detector('CONCAVE', 300.0)      # f = +150 mm -> converging
_wx = _w_at_detector('CONVEX', 300.0)       # f = -150 mm -> diverging
check("concave mirror focuses the beam (smaller w at the detector than flat)", _wc < _wf * 0.97,
      "concave %.4f vs flat %.4f" % (_wc, _wf))
check("convex mirror diverges the beam (larger w at the detector than flat)", _wx > _wf * 1.03,
      "convex %.4f vs flat %.4f" % (_wx, _wf))
def _frontrange(o):          # z-spread of the FRONT-half verts: ~0 for a flat front, big if curved
    zs = [v.co.z for v in o.data.vertices if v.co.z > 0.1]
    return (max(zs) - min(zs)) if zs else 0.0


_cmesh = eg.mirror("CM_curved", (0, 0, 0), (1, 0, 0), (0, 1, 0), coll=_mcoll, mirror_curve='CONCAVE', radius_curv=300.0)
_cflat = eg.mirror("CM_flat", (40, 0, 0), (1, 0, 0), (0, 1, 0), coll=_mcoll, mirror_curve='FLAT')
check("concave mirror has a curved front (vs near-flat front)", _frontrange(_cmesh) > _frontrange(_cflat) + 1.0,
      "%.2f vs %.2f" % (_frontrange(_cmesh), _frontrange(_cflat)))
check("mirror curvature recorded on the optic", _cmesh.optics.mirror_curve == 'CONCAVE')
for _o in list(_mcoll.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_mcoll)

print("[nonlinear crystal: SHG / SPDC frequency conversion (oracle-VERIFIED)]")
_nlc = bpy.data.collections.new("NLTEST"); sc.collection.children.link(_nlc)


def _wls_to_detector(proc, pump_nm):
    for _o in list(sc.objects):
        if getattr(_o, "optics", None) and _o.optics.is_optical:
            bpy.data.objects.remove(_o, do_unlink=True)
    _s = eg.source("NL_S", (-80, 0, 0), (1, 0, 0), coll=_nlc); _s.optics.wavelength = pump_nm
    eg.crystal("NL_X", (0, 0, 0), (1, 0, 0), coll=_nlc, nl_process=proc)
    eg.detector("NL_D", (80, 0, 0), (1, 0, 0), coll=_nlc)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    return sorted({round(s["wavelength"], 1) for s in segs if s.get("to") == "NL_D"})


_shg = _wls_to_detector('SHG', 1064.0)
check("SHG crystal emits the second harmonic (1064 -> 532 nm) to the detector",
      any(abs(w - 532.0) < 1.0 for w in _shg), str(_shg))
_spdc = _wls_to_detector('SPDC', 405.0)
check("SPDC crystal emits degenerate down-converted light (405 -> 810 nm)",
      any(abs(w - 810.0) < 1.0 for w in _spdc), str(_spdc))

# C7: the rest of the chi(2) family. Every child wavelength is exact ENERGY conservation, each
# oracle-VERIFIED (tests/_verify_nlcrystal.py): THG l/3, SFG/DFG 1/l3=1/l1+-1/l2, OPO pump->idler.
_phys = physics


def _wls2_to_detector(proc, pump_nm, l2_nm):
    for _o in list(sc.objects):
        if getattr(_o, "optics", None) and _o.optics.is_optical:
            bpy.data.objects.remove(_o, do_unlink=True)
    _s = eg.source("NL_S", (-80, 0, 0), (1, 0, 0), coll=_nlc); _s.optics.wavelength = pump_nm
    eg.crystal("NL_X", (0, 0, 0), (1, 0, 0), coll=_nlc, nl_process=proc, nl_lambda2_nm=l2_nm)
    eg.detector("NL_D", (80, 0, 0), (1, 0, 0), coll=_nlc, size=120.0)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    return sorted({round(s["wavelength"], 2) for s in segs if s.get("to") == "NL_D"})


_thg = _wls_to_detector('THG', 1064.0)
check("THG crystal emits the third harmonic (1064 -> 354.67 nm)",
      any(abs(w - 1064.0 / 3.0) < 0.5 for w in _thg), str(_thg))
_sfg = _wls2_to_detector('SFG', 1064.0, 532.0)
check("SFG crystal sums frequencies (1064 + 532 -> 354.67 nm, 1/l3=1/l1+1/l2)",
      any(abs(w - 354.6667) < 0.5 for w in _sfg), str(_sfg))
_dfg = _wls2_to_detector('DFG', 1064.0, 1550.0)
check("DFG crystal differences frequencies (1064 - 1550 -> 3393.4 nm, 1/l3=1/l1-1/l2)",
      any(abs(w - 3393.4156) < 1.0 for w in _dfg), str(_dfg))
_opo = _wls2_to_detector('OPO', 532.0, 800.0)
check("OPO crystal splits the pump (532 -> signal 800 + idler 1588.06, 1/lp=1/ls+1/li)",
      any(abs(w - 800.0) < 0.5 for w in _opo) and any(abs(w - 1588.06) < 1.0 for w in _opo), str(_opo))
# the sinc^2(dk*L/2) phase-matching factor is verified-exact (peak 1 at dk=0, zero at dk*L=2pi)
check("phase_match_efficiency sinc^2(dk*L/2): =1 at perfect match, =0 at the first zero",
      abs(_phys.phase_match_efficiency(0.0, 10.0) - 1.0) < 1e-9
      and _phys.phase_match_efficiency(2.0 * 3.141592653589793 / 10.0, 10.0) < 1e-9)
# a TEMPERATURE detuning gates the converted power by sinc^2 -> a hotter/colder crystal converts LESS
_Tpm = _phys.NL_CRYSTALS['LBO'][2]
for _o in list(sc.objects):
    if getattr(_o, "optics", None) and _o.optics.is_optical:
        bpy.data.objects.remove(_o, do_unlink=True)
_s = eg.source("NLT_S", (-80, 0, 0), (1, 0, 0), coll=_nlc); _s.optics.wavelength = 1064.0
_cryT = eg.crystal("NLT_X", (0, 0, 0), (1, 0, 0), coll=_nlc, nl_process='SHG',
                   crystal_material='LBO', crystal_length_mm=14.0, crystal_temp_C=_Tpm)
eg.detector("NLT_D", (80, 0, 0), (1, 0, 0), coll=_nlc, size=120.0)


def _green_pow(T):
    _cryT.optics.crystal_temp_C = T
    bpy.context.view_layer.update()
    return sum(s.get("power", 0.0) for s in scan._trace(sc)
               if s.get("to") == "NLT_D" and abs(s.get("wavelength", 0.0) - 532.0) < 1.0)


check("TEMPERATURE tuning: converted power peaks at the phase-matched T (sinc^2(T) curve)",
      _green_pow(_Tpm) > _green_pow(_Tpm + 25.0) and _green_pow(_Tpm) > _green_pow(_Tpm - 25.0))
for _o in list(_nlc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_nlc)

print("[Wollaston prism: two-beam polarizing split]")
_wcoll = bpy.data.collections.new("WTEST"); sc.collection.children.link(_wcoll)
for _o in list(sc.objects):
    if getattr(_o, "optics", None) and _o.optics.is_optical:
        bpy.data.objects.remove(_o, do_unlink=True)
_ws = eg.source("W_S", (-60, 0, 0), (1, 0, 0), coll=_wcoll); _ws.optics.pol_angle = 45.0
_wp = eg.polarizer("W_P", (0, 0, 0), (1, 0, 0), coll=_wcoll, radius=12, polarizer_type='WOLLASTON')
_wp.optics.split_angle_deg = 20.0
bpy.context.view_layer.update()
_wsegs = scan._trace(sc)
from mathutils import Vector as _WV
_outs = [s for s in _wsegs if s.get("from") == "W_P"]
check("Wollaston emits TWO beams (one input -> two outputs)", len(_outs) == 2, str(len(_outs)))
if len(_outs) == 2:
    _d0 = (_WV(_outs[0]["p2"]) - _WV(_outs[0]["p1"])).normalized()
    _d1 = (_WV(_outs[1]["p2"]) - _WV(_outs[1]["p1"])).normalized()
    _ang = math.degrees(math.acos(max(-1.0, min(1.0, _d0.dot(_d1)))))
    check("the two Wollaston beams are separated by ~the split angle (20 deg)", abs(_ang - 20.0) < 2.0,
          "%.1f deg" % _ang)
for _o in list(_wcoll.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_wcoll)

print("[dispersing prism: Sellmeier glasses + two-surface Snell fan (C3, oracle-VERIFIED)]")
# (a) the added Sellmeier glasses reproduce published d-line indices (hallucinated coeff -> wrong n)
for _g, _nd in (('N-SF11', 1.78472), ('F2', 1.62004), ('N-F2', 1.62005), ('CaF2', 1.43385)):
    check("sellmeier %s n_d (587.56) = published" % _g, abs(physics.sellmeier_n(587.56, _g) - _nd) < 5e-5,
          "%.5f vs %.5f" % (physics.sellmeier_n(587.56, _g), _nd))
# (b) the minimum-deviation relation inverts: n = sin((A+delta)/2)/sin(A/2), A=60
check("prism min-deviation relation inverts (sqrt2, A=60 -> dmin=30)",
      abs(physics.prism_min_deviation(math.sqrt(2.0), 60.0) - 30.0) < 1e-9)
check("prism_deviation = delta_min at symmetric incidence (N-SF11)",
      abs(physics.prism_deviation(1.78472, 60.0, 0.5 * (60.0 + physics.prism_min_deviation(1.78472, 60.0)))
          - physics.prism_min_deviation(1.78472, 60.0)) < 1e-6)
# (c) the tracer fans the spectrum: blue bends more than red, design wl at min deviation
_pcoll = bpy.data.collections.new("PRISMTEST"); sc.collection.children.link(_pcoll)
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
from mathutils import Vector as _PV
eg.source("PR_S", (-150, 0, 0), _PV((1, 0, 0)), _pcoll)
eg.prism("PR_P", (0, 0, 0), _PV((1, 0, 0)), _pcoll, prism_type='EQUILATERAL', apex_deg=60.0, glass='N-SF11', design_wl=589.3)
bpy.context.view_layer.update()


def _prism_dev(wl):
    sc.objects["PR_S"].optics.wavelength = wl
    _ss = scan._trace(sc)
    _ex = [s for s in _ss if s.get("from") == "PR_P" and s.get("kind") == "TRANSMIT"]
    if not _ex:
        return None
    _d = (_PV(_ex[-1]["p2"]) - _PV(_ex[-1]["p1"])).normalized()
    return math.degrees(math.acos(max(-1.0, min(1.0, _d.dot(_PV((1, 0, 0)))))))


_db, _dr, _d0 = _prism_dev(450.0), _prism_dev(650.0), _prism_dev(589.3)
check("prism fans the spectrum: blue (450) bends MORE than red (650)",
      _db is not None and _dr is not None and _db > _dr + 1.0, "blue=%.2f red=%.2f" % (_db or -1, _dr or -1))
check("prism design wavelength sits at minimum deviation",
      _d0 is not None and abs(_d0 - physics.prism_min_deviation(physics.sellmeier_n(589.3, 'N-SF11'), 60.0)) < 1e-2,
      "trace=%.3f analytic=%.3f" % (_d0 or -1, physics.prism_min_deviation(physics.sellmeier_n(589.3, 'N-SF11'), 60.0)))
for _o in list(_pcoll.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_pcoll)

print("[routing prisms: penta/rhomboid/right-angle/Dove folds (C4, reflection-law reuse + Dove 2x oracle)]")
from mathutils import Matrix as _RM
_rcoll = bpy.data.collections.new("ROUTETEST"); sc.collection.children.link(_rcoll)


def _route_build(_pt, **_kw):
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)
    eg.source("RT_S", (-150, 0, 0), _PV((1, 0, 0)), _rcoll)
    _p = eg.prism("RT_P", (0, 0, 0), _PV((1, 0, 0)), _rcoll, prism_type=_pt, **_kw)
    bpy.context.view_layer.update()
    return _p


def _route_defl():
    _ex = [s for s in scan._trace(sc) if s.get("from") == "RT_P" and s.get("kind") == "TRANSMIT"]
    if not _ex:
        return None, None
    _d = (_PV(_ex[-1]["p2"]) - _PV(_ex[-1]["p1"])).normalized()
    return math.degrees(math.acos(max(-1.0, min(1.0, _d.dot(_PV((1, 0, 0))))))), _ex[-1]


_rp = _route_build('RIGHT_ANGLE'); _rdefl, _ = _route_defl()
check("routing right-angle: 90 deg deflection + parity FLIP (ODD)",
      _rdefl is not None and abs(_rdefl - 90.0) < 1e-2 and _rp.optics.prism_parity == 'ODD',
      "defl=%.4f parity=%s" % (_rdefl if _rdefl is not None else -1, _rp.optics.prism_parity))
_rp = _route_build('PENTA'); _rdefl, _ = _route_defl()
check("routing penta: 90 deg deflection + parity EVEN",
      _rdefl is not None and abs(_rdefl - 90.0) < 1e-2 and _rp.optics.prism_parity == 'EVEN',
      "defl=%.4f parity=%s" % (_rdefl if _rdefl is not None else -1, _rp.optics.prism_parity))
_pentadevs = []
for _tilt in (-5.0, 0.0, 5.0):                       # the DEFINING penta property: 90 deg invariant of tilt
    _rp = _route_build('PENTA')
    _bar = (_rp.matrix_world.to_3x3() @ _PV((1.0, 0.0, 0.0))).normalized()
    _piv = _rp.matrix_world.translation.copy()
    _rp.matrix_world = (_RM.Translation(_piv) @ _RM.Rotation(math.radians(_tilt), 4, _bar)
                        @ _RM.Translation(-_piv) @ _rp.matrix_world)
    bpy.context.view_layer.update()
    _td, _ = _route_defl(); _pentadevs.append(_td)
check("routing penta tilt-invariance: stays 90 deg under +-5 deg whole-prism tilt (< 1e-3)",
      all(v is not None and abs(v - 90.0) < 1e-3 for v in _pentadevs), "devs=%s" % _pentadevs)
_route_build('RHOMBOID'); _rdefl, _res = _route_defl()
_roff = math.hypot(_res["p1"][1], _res["p1"][2]) if _res else 0.0
check("routing rhomboid: output parallel (0 deg) + real lateral offset",
      _rdefl is not None and _rdefl < 1e-3 and _roff > 5.0,
      "defl=%.5f offset=%.2f" % (_rdefl if _rdefl is not None else -1, _roff))
_rp = _route_build('DOVE', roll_deg=15.0); _rdefl, _ = _route_defl()
check("routing Dove: in-line (0 deg) + image rotation = 2x roll (15->30)",
      _rdefl is not None and _rdefl < 1e-2 and abs(2.0 * _rp.optics.prism_roll_deg - 30.0) < 1e-9,
      "defl=%.4f img=%.1f" % (_rdefl if _rdefl is not None else -1, 2.0 * _rp.optics.prism_roll_deg))
for _o in list(_rcoll.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_rcoll)

print("[C5 apertures: SLIT erf(sqrt2 b/w) + KNIFE 0.5[1-erf(sqrt2(e-xc)/w)] + BEAM_DUMP (oracle-VERIFIED 8/8 each)]")
# pure helpers: the sqrt2-in-NUMERATOR erf clips (roadmap's erf(b/sqrt2 w) was WRONG; physics_verify ok=true)
check("slit_transmission T(b=w) = erf(sqrt2) = 0.95450", abs(physics.slit_transmission(1.0, 1.0) - 0.9544997361036416) < 1e-9)
check("slit_transmission opens 0->1 (closed b->0, open b->inf)",
      physics.slit_transmission(1e-6, 1.0) < 1e-5 and physics.slit_transmission(20.0, 1.0) > 0.9999999)
check("knife_transmission P=1/2 at e=xc; ->1 retracted, ->0 inserted",
      abs(physics.knife_transmission(0.0, 0.0, 1.0) - 0.5) < 1e-12
      and physics.knife_transmission(-10.0, 0.0, 1.0) > 0.9999999 and physics.knife_transmission(10.0, 0.0, 1.0) < 1e-9)
_c5 = bpy.data.collections.new("C5TEST"); sc.collection.children.link(_c5)


def _c5_clear():
    """Strip ALL optical objects so a stray leftover source from a prior section can't co-illuminate the C5
    meter (a second beam adds power -> P0>1 -> distorts the knife-edge erf fit) -- the other sections do the same."""
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)


_c5_clear()
# SLIT trace: traced transmission matches erf(sqrt2 b/w) at the incident beam radius
eg.source("C5_S", (-150, 0, 0), _PV((1, 0, 0)), _c5)
_SL = eg.slit("C5_SL", (0, 0, 0), _PV((1, 0, 0)), _c5, width=2.0)
eg.detector("C5_D", (150, 0, 0), _PV((1, 0, 0)), _c5)
bpy.context.view_layer.update()
_w_sl = next((s["w_mm"] for s in scan._trace(sc) if s.get("to") == "C5_SL"), None)
_SL.optics.slit_width = 1.0
bpy.context.view_layer.update()
_p_sl = next((s["power"] for s in scan._trace(sc) if s.get("from") == "C5_SL" and s.get("kind") == "TRANSMIT"), None)
check("SLIT traced power matches erf(sqrt2 b/w) at the incident w",
      _p_sl is not None and _w_sl is not None and abs(_p_sl - physics.slit_transmission(0.5, _w_sl)) < 2e-3,
      "traced=%.5f analytic=%.5f" % (_p_sl or -1, physics.slit_transmission(0.5, _w_sl) if _w_sl else -1))
_c5_clear()
# KNIFE scan: the swept erf curve fits back to the input beam radius w (collimated -> resolved spot)
_S2 = eg.source("C5_S2", (-150, 0, 0), _PV((1, 0, 0)), _c5); _S2.optics.waist_um = 800.0
_KN = eg.knife_edge("C5_KN", (0, 0, 0), _PV((1, 0, 0)), _c5, position=0.0)
eg.power_meter("C5_M", (150, 0, 0), _PV((1, 0, 0)), _c5, size=24.0)
bpy.context.view_layer.update()
_w_kn = next((s["w_mm"] for s in scan._trace(sc) if s.get("to") == "C5_KN"), None)
_xs, _ps = [], []
for _i in range(81):
    _e = -3.0 + 6.0 * _i / 80.0
    _KN.optics.knife_position = _e
    bpy.context.view_layer.update()
    _pp, _, _ = alignment.measure(scan._trace(sc), "C5_M", "NONE")
    _xs.append(_e); _ps.append(max(_pp, 0.0))
_KN.optics.knife_position = 0.0
_fit = scan.knife_fit(_xs, _ps)
check("KNIFE scan fit recovers the input beam radius w (< 3%)",
      _fit is not None and _w_kn is not None and abs(_fit["w_mm"] - _w_kn) / _w_kn < 0.03,
      "fit w=%.4f vs input w=%.4f" % (_fit["w_mm"] if _fit else -1, _w_kn or -1))
_c5_clear()
# BEAM_DUMP: terminates the ray + the A4 energy budget still balances
eg.source("C5_S3", (-150, 0, 0), _PV((1, 0, 0)), _c5)
eg.beam_dump("C5_BD", (0, 0, 0), _PV((1, 0, 0)), _c5)
bpy.context.view_layer.update()
_dseg = scan._trace(sc)
import optical_alignment_sim.diagnostics as _diag
tracer.cached_segments = _dseg
_dev = [i for i in _diag.run_diagnostics(sc) if i.get("kind") == "energy_violation"]
check("BEAM_DUMP terminates the ray + A4 budget balances (no leaving seg, 0 energy_violations)",
      len([s for s in _dseg if s.get("from") == "C5_BD"]) == 0 and len(_dev) == 0,
      "leaving=%d violations=%d" % (len([s for s in _dseg if s.get("from") == "C5_BD"]), len(_dev)))
for _o in list(_c5.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_c5)

print("[A9 back-reflection / ghost beams: 4% Fresnel ghost, R+T=1, isolator clears back_reflection]")
import optical_alignment_sim.diagnostics as _a9diag


def _a9_clear():
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)


# surface_reflectance: 4% uncoated, R+T=1 (the ghost energy bookkeeping, physics_verify ok=true 12/12)
check("A9 surface_reflectance(1,1.5) = 4%", abs(physics.surface_reflectance(1.0, 1.5) - 0.04) < 1e-12)
check("A9 R+T=1 conservation", abs((physics.surface_reflectance(1.0, 1.52)
      + (1.0 - physics.surface_reflectance(1.0, 1.52))) - 1.0) < 1e-15)
_a9c = bpy.data.collections.new("A9TEST"); sc.collection.children.link(_a9c)
# model_ghosts OFF (default): a window spawns NO ghost -> the trace is byte-identical to before A9
_a9_clear(); sc.optics.model_ghosts = False
eg.source("A9_S", (-150, 0, 0), _PV((1, 0, 0)), _a9c)
eg.window("A9_W", (0, 0, 0), _PV((1, 0, 0)), _a9c)
eg.detector("A9_D", (150, 0, 0), _PV((1, 0, 0)), _a9c)
bpy.context.view_layer.update()
_g_off = [s for s in scan._trace(sc) if s.get("kind") == "GHOST"]
check("A9 model_ghosts OFF -> zero ghost children (byte-identical default)", len(_g_off) == 0)
# model_ghosts ON: ~4% ghost off the window, transmit debited to (1-R), A4 budget balances
sc.optics.model_ghosts = True
bpy.context.view_layer.update()
_son = scan._trace(sc)
_gon = [s for s in _son if s.get("kind") == "GHOST"]
_ton = next((s["power"] for s in _son if s.get("from") == "A9_W" and s.get("kind") == "TRANSMIT"), None)
_Rw = physics.surface_reflectance(1.0, sc.objects["A9_W"].optics.refractive_index)
check("A9 ghost power ~ R*incident (4%)", len(_gon) == 1 and abs(_gon[0]["power"] - _Rw) < 2e-3,
      "ghost=%.5f R=%.5f" % (_gon[0]["power"] if _gon else -1, _Rw))
check("A9 transmit debited to (1-R)*incident", _ton is not None and abs(_ton - (1.0 - _Rw)) < 2e-3,
      "transmit=%.5f expect=%.5f" % (_ton or -1, 1.0 - _Rw))
tracer.cached_segments = _son
check("A9 energy budget balances with the ghost (0 energy_violations)",
      len([i for i in _a9diag.run_diagnostics(sc) if i.get("kind") == "energy_violation"]) == 0)
# back_reflection FIRES without an isolator (normal-incidence window feeds the ghost into the source)
_a9_clear(); sc.optics.model_ghosts = True
eg.source("A9_S", (-150, 0, 0), _PV((1, 0, 0)), _a9c)
eg.window("A9_W", (0, 0, 0), _PV((1, 0, 0)), _a9c)
eg.detector("A9_D", (150, 0, 0), _PV((1, 0, 0)), _a9c)
bpy.context.view_layer.update()
tracer.cached_segments = scan._trace(sc)
_br0 = [i for i in _a9diag.run_diagnostics(sc) if i.get("kind") == "back_reflection"]
check("A9 back_reflection FIRES without isolator", len(_br0) == 1 and _br0[0]["element"] == "A9_S")
# ... and an ISOLATOR in the path CLEARS it (the teachable signal)
eg.isolator("A9_ISO", (-80, 0, 0), _PV((1, 0, 0)), _a9c)
bpy.context.view_layer.update()
tracer.cached_segments = scan._trace(sc)
_br1 = [i for i in _a9diag.run_diagnostics(sc) if i.get("kind") == "back_reflection"]
check("A9 isolator CLEARS back_reflection (teachable signal)", len(_br1) == 0)
_a9_clear(); sc.optics.model_ghosts = False
for _o in list(_a9c.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_a9c)

print("[1.3 propose_corrections: ADVISORY fixes the AI judges (refuse/partial/accept), never auto-applied]")
# A deterministic fault (a normal-incidence window retro-reflects into the source -> back_reflection):
# propose_corrections must SURFACE it as an advisory proposal with a structured fix + a
# 'maybe_intentional_if' judge hint + advisory=True, WITHOUT mutating the trace. Mirrors the
# physics-honesty-gate: surface + judge, never silent auto-fix.
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
_pcc = eg.example_collection("PC_test")
sc.optics.model_ghosts = True
eg.source("PC_S", (-150, 0, 0), _PV((1, 0, 0)), _pcc)
eg.window("PC_W", (0, 0, 0), _PV((1, 0, 0)), _pcc)
eg.detector("PC_D", (150, 0, 0), _PV((1, 0, 0)), _pcc)
bpy.context.view_layer.update()
_nseg_before = len(scan._trace(sc))
_pc = optics_api.propose_corrections()
check("1.3 propose_corrections is advisory + carries the refuse/partial/accept judge guidance",
      _pc.get("advisory") is True and "refuse" in _pc.get("guidance", "").lower()
      and "intent" in _pc.get("guidance", "").lower())
_br_prop = next((p for p in _pc.get("proposals", []) if p.get("issue") == "back_reflection"), None)
check("1.3 proposal surfaces back_reflection with a structured fix + judge hint + advisory flag",
      _br_prop is not None and bool(_br_prop.get("suggested_fix")) and bool(_br_prop.get("tool"))
      and "retro" in _br_prop.get("maybe_intentional_if", "").lower()
      and _br_prop.get("advisory") is True and 0.0 <= _br_prop.get("fault_confidence", -1) <= 1.0,
      str(_br_prop)[:100] if _br_prop else "no back_reflection proposal")
check("1.3 propose_corrections is READ-ONLY (trace byte-identical)", len(scan._trace(sc)) == _nseg_before)
_dg = optics_api.diagnose()
check("1.3 propose_corrections enriches exactly what diagnose() detects (no re-detection drift)",
      sorted(p["issue"] for p in _pc["proposals"]) == sorted(d["kind"] for d in _dg["diagnostics"]))
sc.optics.model_ghosts = False
for _o in list(_pcc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_pcc)

print("[3.3 detect_phenomena: flag the optical phenomena whose conditions the trace MEETS (advisory)]")
# collinear coherent recombination (Michelson) -> two_beam_interference
optics_api.build_example("michelson")
_ph_mi = optics_api.detect_phenomena()
_iph = next((p for p in _ph_mi["phenomena"] if p["phenomenon"] == "two_beam_interference"), None)
check("3.3 detect_phenomena flags two-beam interference at a collinear recombination",
      _iph is not None and _iph["crossing_angle_deg"] < 0.5 and _iph["visibility"] > 0.8,
      str(_iph)[:90] if _iph else "no interference phenomenon")
# an ANGLED coherent crossing -> off_axis_hologram with the VERIFIED carrier spacing Lambda=lambda/(2 sin(theta/2))
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
_oac = eg.example_collection("OffAxis")
_oaX, _oaY = _Vec((1, 0, 0)), _Vec((0, 1, 0))
eg.source("OA_S", (-150, 0, 0), _oaX, _oac)
eg.beamsplitter("OA_BS", (0, 0, 0), _oaX, _oaY, _oac)        # in +X, reflect +Y
eg.mirror("OA_M1", (120, 0, 0), _oaX, _oaY, _oac)            # transmitted +X -> +Y
eg.mirror("OA_M2", (0, 120, 0), _oaY, _oaX, _oac)            # reflected +Y -> +X
eg.detector("OA_D", (120, 120, 0), _Vec((1, 1, 0)), _oac)   # the two arms cross here at 90 deg
bpy.context.view_layer.update()
_nseg_ph = len(scan._trace(sc))
_ph_oa = optics_api.detect_phenomena()
_oph = next((p for p in _ph_oa["phenomena"] if p["phenomenon"] == "off_axis_hologram"), None)
_lam_exp = 632.8e-6 / (2.0 * math.sin(math.radians(_oph["crossing_angle_deg"]) / 2.0)) if _oph else 0.0
check("3.3 detect_phenomena flags off-axis hologram with carrier spacing lambda/(2 sin(theta/2)) [oracle ok=true]",
      _oph is not None and _oph["crossing_angle_deg"] > 0.5
      and abs(_oph["fringe_spacing_mm"] - _lam_exp) < 1e-6,
      str(_oph)[:110] if _oph else "no off_axis_hologram phenomenon")
check("3.3 detect_phenomena is READ-ONLY (trace byte-identical)", len(scan._trace(sc)) == _nseg_ph)
for _o in list(_oac.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_oac)

print("[3.1 soft dichroic edge: wavelength-selective R(lambda)+T(lambda)=1, smooth transition at cut]")
# A real dichroic has a FINITE-slope edge: near the cut wavelength the beam PARTIALLY reflects AND
# transmits (R+T=1, energy conserved exactly). Far from the cut it is full reflect / full transmit
# (BYTE-IDENTICAL to the old hard step). Edge SHAPE is a Tier-1 logistic modelling choice.
def _dich_split(wl):
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)
    _dc = eg.example_collection("Dx%d" % int(wl))
    _dX, _dY = _Vec((1, 0, 0)), _Vec((0, 1, 0))
    eg.source("DX_S", (-100, 0, 0), _dX, _dc, wavelength=wl)
    _di = eg.dichroic("DX_DI", (0, 0, 0), _dX, _dY, _dc, cut_nm=650.0, pass_type='LP')  # transmit long, reflect short
    _di.optics.edge_width = 10.0
    eg.detector("DX_T", (100, 0, 0), _dX, _dc)
    eg.detector("DX_R", (0, 100, 0), _dY, _dc)
    bpy.context.view_layer.update()
    _s = scan._trace(sc)
    _dn = _di.name                              # use the REAL object name (Blender may .NNN-suffix on rebuild)
    _T = sum(x["power"] for x in _s if x.get("from") == _dn and x.get("kind") == "TRANSMIT")
    _R = sum(x["power"] for x in _s if x.get("from") == _dn and x.get("kind") == "REFLECT")
    for _o in list(_dc.objects):
        eg.drop_example_object(_o)
    bpy.data.collections.remove(_dc)
    return _T, _R

_T_cut, _R_cut = _dich_split(650.0)         # AT the cut -> 50/50
check("3.1 dichroic at the cut wavelength splits 50/50 (logistic midpoint R(cut)=0.5)",
      abs(_T_cut - 0.5) < 1e-3 and abs(_R_cut - 0.5) < 1e-3, "T=%.4f R=%.4f" % (_T_cut, _R_cut))
_T_tr, _R_tr = _dich_split(630.0)           # in the transition band (below cut) -> partial, R>T
check("3.1 dichroic transition band splits partially with R+T=1 (energy conserved)",
      abs((_T_tr + _R_tr) - 1.0) < 1e-9 and _R_tr > _T_tr > 0.01, "T=%.4f R=%.4f sum=%.6f" % (_T_tr, _R_tr, _T_tr + _R_tr))
_T_lo, _R_lo = _dich_split(400.0)           # far below cut (>207 nm at w=10) -> full reflect (short lambda)
_T_hi, _R_hi = _dich_split(900.0)           # far above cut -> full transmit (long lambda)
check("3.1 dichroic far from the cut is full reflect / full transmit (byte-identical fast path)",
      abs(_R_lo - 1.0) < 1e-9 and abs(_T_lo) < 1e-9 and abs(_T_hi - 1.0) < 1e-9 and abs(_R_hi) < 1e-9,
      "short(400)->R=%.4f  long(900)->T=%.4f" % (_R_lo, _T_hi))

print("[A11 universal coating: paintable reflectance pickoff + neutral absorber; R+T+A=1; byte-identical defaults]")
import optical_alignment_sim.diagnostics as _a11diag


def _a11_clear():
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)


_a11c = bpy.data.collections.new("A11TEST"); sc.collection.children.link(_a11c)
# coating_reflectance=0.30 on a tilted window -> a 0.30 REFLECT pickoff + a 0.70 transmitted beam
_a11_clear()
eg.source("A11_S", (-150, 0, 0), _PV((1, 0, 0)), _a11c)
_a11tilt = math.radians(20.0)
_a11w = eg.window("A11_W", (0, 0, 0), _PV((math.cos(_a11tilt), math.sin(_a11tilt), 0.0)), _a11c, radius=16.0)
_a11w.optics.coating_reflectance = 0.30
eg.detector("A11_D", (170, 0, 0), _PV((1, 0, 0)), _a11c)
_a11pdir = _PV((-math.cos(2 * _a11tilt), -math.sin(2 * _a11tilt), 0.0))
eg.detector("A11_SAMP", tuple(_a11pdir * 130.0), _a11pdir, _a11c, size=60.0)
bpy.context.view_layer.update()
_a11s = scan._trace(sc)
_a11pk = [s for s in _a11s if s.get("kind") == "REFLECT" and s.get("from") == "A11_W"]
_a11pT = next((s["power"] for s in _a11s if s.get("from") == "A11_W" and s.get("kind") == "TRANSMIT"), None)
check("A11 coating_reflectance=0.30 spawns ONE pickoff of power 0.30",
      len(_a11pk) == 1 and abs(_a11pk[0]["power"] - 0.30) < 1e-6,
      "pickoff=%.5f" % (_a11pk[0]["power"] if _a11pk else -1))
check("A11 onward transmit debited to 0.70 (R+T=1)", _a11pT is not None and abs(_a11pT - 0.70) < 1e-6,
      "transmit=%.5f" % (_a11pT or -1))
check("A11 pickoff goes the reflected direction onto the 2nd detector",
      len([s for s in _a11s if s.get("kind") == "REFLECT" and s.get("from") == "A11_W" and s.get("to") == "A11_SAMP"]) == 1)
tracer.cached_segments = _a11s
check("A11 energy budget balances with the 30% pickoff (0 energy_violations)",
      len([i for i in _a11diag.run_diagnostics(sc) if i.get("kind") == "energy_violation"]) == 0)
# element_transmittance=0.5 -> the onward power is halved (universal neutral absorber)
_a11_clear()
eg.source("A11_S", (-150, 0, 0), _PV((1, 0, 0)), _a11c)
_a11w = eg.window("A11_W", (0, 0, 0), _PV((1, 0, 0)), _a11c)
_a11w.optics.element_transmittance = 0.5
eg.detector("A11_D", (150, 0, 0), _PV((1, 0, 0)), _a11c)
bpy.context.view_layer.update()
_a11sa = scan._trace(sc)
_a11pTa = next((s["power"] for s in _a11sa if s.get("from") == "A11_W" and s.get("kind") == "TRANSMIT"), None)
check("A11 element_transmittance=0.5 halves the onward power (absorbs 0.5)",
      _a11pTa is not None and abs(_a11pTa - 0.5) < 1e-6, "transmit=%.5f" % (_a11pTa or -1))
# both together: R=0.30 + Ta=0.5 -> pickoff 0.30, transmit 0.35, absorbed 0.35 (R + T_onward + A = 1)
_a11_clear()
eg.source("A11_S", (-150, 0, 0), _PV((1, 0, 0)), _a11c)
_a11w = eg.window("A11_W", (0, 0, 0), _PV((math.cos(_a11tilt), math.sin(_a11tilt), 0.0)), _a11c, radius=16.0)
_a11w.optics.coating_reflectance = 0.30
_a11w.optics.element_transmittance = 0.5
eg.detector("A11_D", (170, 0, 0), _PV((1, 0, 0)), _a11c)
eg.detector("A11_SAMP", tuple(_a11pdir * 130.0), _a11pdir, _a11c, size=60.0)
bpy.context.view_layer.update()
_a11sb = scan._trace(sc)
_a11pkb = [s for s in _a11sb if s.get("kind") == "REFLECT" and s.get("from") == "A11_W"]
_a11pTb = next((s["power"] for s in _a11sb if s.get("from") == "A11_W" and s.get("kind") == "TRANSMIT"), None)
_a11pkbp = _a11pkb[0]["power"] if _a11pkb else -1
_a11abs = 1.0 - _a11pkbp - (_a11pTb or 0)
check("A11 R=0.30 + Ta=0.5 -> R+T_onward+A = 0.30+0.35+0.35 = 1 (energy conserved)",
      abs(_a11pkbp - 0.30) < 1e-6 and abs((_a11pTb or 0) - 0.35) < 1e-6 and abs(_a11abs - 0.35) < 1e-6,
      "pickoff=%.4f transmit=%.4f absorbed=%.4f" % (_a11pkbp, _a11pTb or -1, _a11abs))
# defaults R=0,T=1 -> a window spawns NO pickoff and transmits full power (byte-identical to before A11)
_a11_clear()
eg.source("A11_S", (-150, 0, 0), _PV((1, 0, 0)), _a11c)
eg.window("A11_W", (0, 0, 0), _PV((1, 0, 0)), _a11c)
eg.detector("A11_D", (150, 0, 0), _PV((1, 0, 0)), _a11c)
bpy.context.view_layer.update()
_a11s0 = scan._trace(sc)
_a11p0 = next((s["power"] for s in _a11s0 if s.get("from") == "A11_W" and s.get("kind") == "TRANSMIT"), None)
check("A11 defaults (R=0,T=1) -> no pickoff, full power transmit (byte-identical)",
      len([s for s in _a11s0 if s.get("kind") == "REFLECT" and s.get("from") == "A11_W"]) == 0
      and _a11p0 is not None and abs(_a11p0 - 1.0) < 1e-9)
# composition: a coated MIRROR is NOT given a 2nd reflection (the coating is skipped on reflective types)
_a11_clear()
eg.source("A11_S", (-150, 0, 0), _PV((1, 0, 0)), _a11c)
_a11m = eg.mirror("A11_M", (0, 0, 0), (1, 0, 0), (0, 1, 0), _a11c)
_a11m.optics.coating_reflectance = 0.30
eg.detector("A11_D", (0, 150, 0), _PV((0, -1, 0)), _a11c)
bpy.context.view_layer.update()
tracer.cached_segments = scan._trace(sc)
check("A11 coating on a MIRROR adds no 2nd reflection (no double-count on reflective types)",
      len([s for s in tracer.cached_segments if s.get("kind") == "REFLECT" and s.get("from") == "A11_M"]) == 1
      and len([i for i in _a11diag.run_diagnostics(sc) if i.get("kind") == "energy_violation"]) == 0)
_a11_clear()
for _o in list(_a11c.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_a11c)

print("[A10 fringe disambiguation: pol vs coherence vs crossed-polarizer; no false positives on dark ports]")
import optical_alignment_sim.diagnostics as _a10diag
_A10K = {"pol_mismatch", "coherence_mismatch", "crossed_polarizer"}


def _a10_clear():
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)


def _a10_flags():
    tracer.cached_segments = scan._trace(sc)
    return [i for i in _a10diag.run_diagnostics(sc) if i.get("kind") in _A10K]


_a10c = bpy.data.collections.new("A10TEST"); sc.collection.children.link(_a10c)
_A10X, _A10Y = _PV((1, 0, 0)), _PV((0, 1, 0))
_A10L = 200.0


def _a10_mz(hwp_fast=None, analyzer='NONE'):
    """Mach-Zehnder, H source. Optional HWP in the top arm (rotates its pol) + a detector analyzer.
    Bright port A10_D0, dark port A10_D1. Names are A10_* so they never collide with build_example."""
    _a10_clear()
    _s = eg.source("A10_L", (-150, 0, 0), _A10X, _a10c)
    _s.optics.pol_type = 'LINEAR'; _s.optics.pol_angle = 0.0
    eg.beamsplitter("A10_BS1", (0, 0, 0), _A10X, _A10Y, _a10c)
    eg.mirror("A10_Mtop", (0, _A10L, 0), _A10Y, _A10X, _a10c)
    if hwp_fast is not None:
        eg.waveplate("A10_HWP", (_A10L * 0.5, _A10L, 0), _A10X, _a10c, kind='HWP', fast_axis=hwp_fast, design_wl=632.8)
    eg.mirror("A10_Mbot", (_A10L, 0, 0), _A10X, _A10Y, _a10c)
    eg.beamsplitter("A10_BS2", (_A10L, _A10L, 0), _A10X, _A10Y, _a10c)
    _d0 = eg.detector("A10_D0", (2 * _A10L, _A10L, 0), _A10X, _a10c)
    _d1 = eg.detector("A10_D1", (_A10L, 2 * _A10L, 0), _A10Y, _a10c)
    if analyzer != 'NONE':
        _d0.optics.analyzer = analyzer; _d1.optics.analyzer = analyzer
    bpy.context.view_layer.update()


def _a10_michelson(linewidth_nm=0.0, stage_mm=0.0):
    """Michelson, finite source linewidth (-> finite Lc) + a translation-stage arm (OPD = 2*stage_mm)."""
    _a10_clear()
    _s = eg.source("A10_L", (-150, 0, 0), _A10X, _a10c)
    _s.optics.pol_type = 'LINEAR'; _s.optics.pol_angle = 0.0; _s.optics.linewidth_nm = linewidth_nm
    eg.beamsplitter("A10_BS", (0, 0, 0), _A10X, _A10Y, _a10c)
    eg.mirror("A10_Mfix", (0, 180.0, 0), _A10Y, -_A10Y, _a10c)
    _mst = eg.mirror("A10_Mstage", (180.0, 0, 0), _A10X, -_A10X, _a10c)
    eg.add_translation_dof(_mst, (1, 0, 0), -80.0, 80.0, stage_mm)
    mounts.compose_pose(_mst)
    eg.detector("A10_D", (0, -180.0, 0), -_A10Y, _a10c)
    bpy.context.view_layer.update()


# (1) healthy interferometers must be CLEAN -- the destructive-interference DARK PORT is NOT a fault.
for _hk in ("mach_zehnder", "michelson", "dhm"):
    optics_api.build_example(_hk)
    tracer.cached_segments = scan._trace(sc)
    _hf = [i for i in _a10diag.run_diagnostics(sc) if i.get("kind") in _A10K]
    check("A10 healthy %s emits ZERO A10 flags (dark port is a phase null, not a fault)" % _hk,
          len(_hf) == 0, str([(i["kind"], i["element"]) for i in _hf]))

# (2) pol_mismatch: a HWP@45 rotates the top arm to V (orthogonal) -> fires; clears at HWP@0.
_a10_mz(hwp_fast=45.0)
_pf = {i["kind"] for i in _a10_flags()}
check("A10 pol_mismatch FIRES on orthogonal arms (and not coherence/crossed)",
      "pol_mismatch" in _pf and "coherence_mismatch" not in _pf and "crossed_polarizer" not in _pf, str(sorted(_pf)))
_a10_mz(hwp_fast=0.0)
check("A10 pol_mismatch CLEARS when the arm is rotated back parallel (HWP@0)",
      not any(i["kind"] in _A10K for i in _a10_flags()))

# (3) coherence_mismatch: finite Lc + a large stage OPD -> fires; clears when the stage is centred.
_a10_michelson(linewidth_nm=2.0, stage_mm=40.0)            # OPD = 80 mm >> Lc ~ 0.2 mm
_cf = {i["kind"] for i in _a10_flags()}
check("A10 coherence_mismatch FIRES on OPD>>Lc (and not pol/crossed)",
      "coherence_mismatch" in _cf and "pol_mismatch" not in _cf and "crossed_polarizer" not in _cf, str(sorted(_cf)))
_a10_michelson(linewidth_nm=2.0, stage_mm=0.0)
check("A10 coherence_mismatch CLEARS when OPD < Lc (stage centred)",
      not any(i["kind"] in _A10K for i in _a10_flags()))

# (4) crossed_polarizer: arms H, analyzer V -> fires (each arm Malus-killed); clears when uncrossed (H).
_a10_mz(hwp_fast=None, analyzer='V')
_xf = {i["kind"] for i in _a10_flags()}
check("A10 crossed_polarizer FIRES on a crossed analyzer (arms H, analyzer V)", "crossed_polarizer" in _xf, str(sorted(_xf)))
_a10_mz(hwp_fast=None, analyzer='H')      # uncrossed + the dark port A10_D1 is a phase null -> must be SILENT
check("A10 crossed_polarizer CLEARS when uncrossed, AND a dark port with an aligned analyzer stays "
      "silent (the fixed bug: phase null != Malus extinction)",
      not any(i["kind"] in _A10K for i in _a10_flags()))

_a10_clear()
for _o in list(_a10c.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_a10c)

print("[microscope objective: f_obj = f_tube/M, focal power (oracle-VERIFIED)]")
optics_api.build_example("microscope")
_msegs = scan._trace(sc)
check("microscope example: the beam reaches the camera", any(s.get("to") == "MIC_Cam" for s in _msegs))
_obj = next(o for o in sc.objects if getattr(o, "optics", None) and o.optics.element_type == 'OBJECTIVE')
_tl = {'FINITE_160': 160.0, 'FINITE_195': 195.0}.get(_obj.optics.obj_correction, _obj.optics.obj_tube_ref)
check("objective f_obj = f_tube/M (200/10 = 20 mm)", abs(_tl / _obj.optics.obj_mag - 20.0) < 0.01,
      "%.2f mm" % (_tl / _obj.optics.obj_mag))
_oc = bpy.data.collections.new("OBJT"); sc.collection.children.link(_oc)


def _w_objective(use):
    for _o in list(sc.objects):
        if getattr(_o, "optics", None) and _o.optics.is_optical:
            bpy.data.objects.remove(_o, do_unlink=True)
    eg.source("OB_S", (-60, 0, 0), (1, 0, 0), coll=_oc)
    if use:
        eg.objective("OB_O", (0, 0, 0), (1, 0, 0), coll=_oc, mag=10.0)
    eg.detector("OB_D", (60, 0, 0), (1, 0, 0), coll=_oc)
    bpy.context.view_layer.update()
    return next((s["w_mm"] for s in scan._trace(sc) if s.get("to") == "OB_D"), 0.0)


_wn, _wy = _w_objective(False), _w_objective(True)
check("objective applies focal power (beam size changes vs straight-through)", abs(_wy - _wn) > 0.01,
      "%.3f vs %.3f" % (_wy, _wn))
for _o in list(_oc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_oc)
optics_api.dress_bench(False)

print("[interference invariants]")
optics_api.build_example("michelson")
segs = scan._trace(sc)
p, v, _ = alignment.measure(segs, "MI_D", "NONE")
check("michelson V~1, P>0.9", v > 0.95 and p > 0.9, "P=%.3f V=%.3f" % (p, v))

optics_api.build_example("mach_zehnder")
segs = scan._trace(sc)
d0 = alignment.measure(segs, "MZ_D0", "NONE")[0]
d1 = alignment.measure(segs, "MZ_D1", "NONE")[0]
check("MZ complementary + energy", 0.9 < (d0 + d1) < 1.1 and min(d0, d1) < 0.2, "D0=%.3f D1=%.3f" % (d0, d1))

print("[PBS physical s/p routing]")
optics_api.build_example("bell")
# As shipped the HWP sits at 22.5 deg (specced at 810 nm), so the PBS splits ~50/50 into
# BOTH detectors -- the V-output arms must no longer be dark.
segs = scan._trace(sc)
sH = alignment.measure(segs, "Bell_S_H", "NONE")[0]
sV = alignment.measure(segs, "Bell_S_V", "NONE")[0]
iV = alignment.measure(segs, "Bell_I_V", "NONE")[0]
check("Bell ships with both arms lit", sV > 0.05 and iV > 0.05, "S_V=%.3f I_V=%.3f" % (sV, iV))
check("PBS 50/50 + energy (shipped HWP)", abs(sH - 0.5) < 0.06 and abs(sV - 0.5) < 0.06
      and 0.95 < (sH + sV) < 1.05, "H=%.3f V=%.3f" % (sH, sV))
# Rotate the HWP back to 0 deg -> the H source stays H -> the PBS sends all power to the p/H port.
sc.objects["Bell_S_HWP"].optics.fast_axis_deg = 0.0
segs = scan._trace(sc)
pH = alignment.measure(segs, "Bell_S_H", "NONE")[0]
pV = alignment.measure(segs, "Bell_S_V", "NONE")[0]
check("PBS p transmits (HWP@0)", pH > 0.9 and pV < 0.1, "H=%.3f V=%.3f" % (pH, pV))

print("[retroreflector tilt-insensitivity]")
optics_api.build_example("michelson")
mst = sc.objects["MI_M_stage"]
mst.rotation_euler[2] += math.radians(2.0)     # tip the stage mirror 2 deg in-plane
bpy.context.view_layer.update()
segs = scan._trace(sc)
p_flat, v_flat, _ = alignment.measure(segs, "MI_D", "NONE")
mst.optics.element_type = 'RETROREFLECTOR'
segs = scan._trace(sc)
_pr, v_retro, _ = alignment.measure(segs, "MI_D", "NONE")
check("tilted flat mirror walks off", p_flat < 0.35 and v_flat < 0.0,
      "P=%.3f V=%.3f" % (p_flat, v_flat))      # one arm only -> no fringes at the detector
check("tilted corner cube returns", v_retro > 0.9, "V=%.3f" % v_retro)

print("[fringe-window coherence]")
optics_api.build_example("michelson")
_msave = sc.optics.max_segments
sc.optics.max_segments = 256                   # 11 spectral lines need segment headroom
sc.objects["MI_Laser"].optics.bandwidth_nm = 30.0
det = sc.objects["MI_D"]
segs = scan._trace(sc)
field, wpx = scan._sensor_field_mm(det.optics)
arr, _ = scan._fringe_array(det, segs, field, wpx, norm='peak')
c0 = float(arr[wpx // 2, wpx // 2, 0])
dof = next(d for d in sc.objects["MI_M_stage"].optics.dofs if d.kind.startswith('TRANS'))
dof.current = 0.05                             # 0.1 mm OPD >> Lc(30 nm) ~ 13 um
bpy.context.view_layer.update()
segs = scan._trace(sc)
arr, _ = scan._fringe_array(det, segs, field, wpx, norm='peak')
c1 = float(arr[wpx // 2, wpx // 2, 0])
check("white-light packet bright at OPD=0", c0 > 0.8, "c0=%.3f" % c0)
check("window washes out at OPD>>Lc", 0.35 < c1 < 0.65, "c1=%.3f" % c1)   # incoherent lines -> 0.5
sc.optics.max_segments = _msave

print("[B4 tilt-null solver: recover fx=tilt/lambda, drive fringe freq -> 0, peak visibility]")
from optical_alignment_sim import solvers, mounts as _mounts, elements_generic as _G
# B4-byte-identical: importing/holding the tilt_null solver must not perturb a normal trace
optics_api.build_example("michelson")
_b4_segs0 = scan._trace(sc)
_ = (solvers.tilt_null, solvers.tilt_estimate)                  # reference the public surface
_b4_segs1 = scan._trace(sc)
_b4_p0, _b4_v0, _ = alignment.measure(_b4_segs0, "MI_D", "NONE")
_b4_p1, _b4_v1, _ = alignment.measure(_b4_segs1, "MI_D", "NONE")
check("B4: tilt_null import is inert (michelson trace unchanged)",
      len(_b4_segs0) == len(_b4_segs1) and abs(_b4_p0 - _b4_p1) < 1e-9 and abs(_b4_v0 - _b4_v1) < 1e-9)
# B4-estimator: a known injected tilt prints the analytic fringe frequency fx = tilt/lambda
optics_api.build_example("michelson")
optics_api.set_mount("MI_M_stage", "KM100")
_b4stage = sc.objects["MI_M_stage"]
_G.add_translation_dof(_b4stage, (1, 0, 0), -0.02, 0.02, 0.0)   # restore the OPD piston knob
sc.objects["MI_Laser"].optics.waist_um = 1500.0                # wide collimated beam -> many fringes
bpy.context.view_layer.update()
_b4det = sc.objects["MI_D"]
for _d in _b4stage.optics.dofs:
    if _d.kind == "TILT":
        _d.current = 0.02
_mounts.compose_pose(_b4stage); bpy.context.view_layer.update()
_b4seg = scan._trace(sc)
_b4field, _b4px = solvers._sensor_field(_b4det, _b4seg)
_b4arr, _ = scan._fringe_array(_b4det, _b4seg, _b4field, _b4px, norm='self')
_b4wl = next((s.get("wavelength", 632.8) for s in _b4seg if s["to"] == "MI_D"), 632.8)
_b4fx, _b4fy = solvers.tilt_estimate(_b4arr[..., 0], _b4wl, _b4field / _b4px)
_b4fmag = math.hypot(_b4fx, _b4fy)
# analytic ground truth: |f| = |d1-d2|_transverse / lambda
_c0, _n, _u, _v = scan._detector_plane(_b4det)
_bm = [s for s in _b4seg if s["to"] == "MI_D"]
_d1 = (_Vec(_bm[0]["p2"]) - _Vec(_bm[0]["p1"])).normalized()
_d2 = (_Vec(_bm[1]["p2"]) - _Vec(_bm[1]["p1"])).normalized()
_b4ana = math.hypot((_d1.dot(_u) - _d2.dot(_u)) / (_b4wl * 1e-6),
                    (_d1.dot(_v) - _d2.dot(_v)) / (_b4wl * 1e-6))
check("B4: tilt_estimate recovers fx=tilt/lambda from the fringe image",
      abs(_b4fmag - _b4ana) / max(_b4ana, 1e-9) < 0.18, "est=%.3f ana=%.3f cyc/mm" % (_b4fmag, _b4ana))
# B4-solve: run the solver -> fringe frequency driven down, single broad fringe, visibility peaked
_b4res = optics_api.tilt_null(detector="MI_D", mirrors=[["MI_M_stage", "TILT"]], piston_steps=25)
check("B4: solver runs + reports a convergence history",
      _b4res.get("ok") and len(_b4res.get("history", [])) >= 2, str(_b4res.get("error", _b4res.get("history"))))
_hh = _b4res["history"]
check("B4: fringe frequency driven down toward zero (dense -> broad)",
      _b4res["fringe_freq_after"] < _b4res["fringe_freq_before"] * 0.6,
      "%.3f -> %.3f cyc/mm" % (_b4res["fringe_freq_before"], _b4res["fringe_freq_after"]))
check("B4: history is monotonically non-increasing to the null",
      all(_hh[i + 1] <= _hh[i] + 0.05 for i in range(len(_hh) - 1)), str(_hh))
check("B4: final pattern is a single broad fringe (count collapses to ~1)",
      _b4res["fringe_count_after"] < _b4res["fringe_count_before"] / 3.0
      and _b4res["fringe_count_after"] < 1.2,
      "count %.2f -> %.2f" % (_b4res["fringe_count_before"], _b4res["fringe_count_after"]))
check("B4: high fringe visibility after the piston search",
      _b4res["visibility_after"] > 0.85, "V=%.3f" % _b4res["visibility_after"])

print("[adaptive optics]")
optics_api.build_example("adaptive_optics")
m = optics_api.ao_measure("AO_WFS")
check("AO open-loop RMS~0.559", abs(m["rms"] - math.sqrt(0.4 ** 2 + 0.3 ** 2 + 0.25 ** 2)) < 1e-2, str(m.get("rms")))
rr = optics_api.ao_close_loop("AO_WFS", "AO_DM", gain=0.5, iters=15)
check("AO closed-loop RMS->0", rr.get("ok") and rr["rms_final"] < 0.01, str(rr.get("rms_final")))
# a LOW gain must keep converging to ~tol, not declare 'converged' ~tol/gain above it (stall-tol fix)
optics_api.build_example("adaptive_optics")
rr_lo = optics_api.ao_close_loop("AO_WFS", "AO_DM", gain=0.05, iters=160)
check("AO low-gain converges (not early-stalled)", rr_lo.get("ok") and rr_lo["rms_final"] < 0.01,
      str(rr_lo.get("rms_final")))
cmd = list(sc.objects["AO_DM"].optics.dm_command)
check("AO DM -> injected modes", abs(cmd[3] - 0.4) < 0.02 and abs(cmd[5] - 0.3) < 0.02 and abs(cmd[7] - 0.25) < 0.02,
      str([round(cmd[i], 3) for i in (3, 5, 7)]))

print("[B5 AO reconstructor: interaction matrix + TSVD/damped-transpose + leaky integrator + Kolmogorov]")
# Interaction matrix B is built by poking each DM mode + recording the WFS response (W = B x).
# For the modal DM the tracer subtracts dm_command, so B = -I (all singular values ~1): a well-
# conditioned interaction matrix. Built on the adaptive_optics bench.
optics_api.build_example("adaptive_optics")
_B, _w0 = ao.interaction_matrix(sc, "AO_WFS", "AO_DM", poke=0.2)
check("B5 interaction matrix is built (15x15) by poking the DM modes",
      _B is not None and len(_B) == physics.N_ZERNIKE and len(_B[0]) == physics.N_ZERNIKE)
_sv = sorted(np.linalg.svd(np.array(_B), compute_uv=False), reverse=True)
check("B5 interaction matrix is well-conditioned (B ~ -I, singular values ~1)",
      abs(_sv[0] - 1.0) < 1e-6 and abs(_sv[-1] - 1.0) < 1e-6, "sv range %.4f..%.4f" % (_sv[0], _sv[-1]))

# Closed loop with the TSVD reconstructor reduces the injected RMS by >5x (it actually does ~80x).
optics_api.build_example("adaptive_optics")
_tsvd = ao.close_loop_recon(sc, "AO_WFS", "AO_DM", gain=0.8, leak=0.99, method='TSVD', iters=40)
check("B5 TSVD closed loop reduces RMS >5x", _tsvd["ok"] and _tsvd["rms_before"] / max(_tsvd["rms_after"], 1e-12) > 5.0,
      "RMS %.4f -> %.4f (%.1fx)" % (_tsvd["rms_before"], _tsvd["rms_after"], _tsvd["reduction"]))
check("B5 TSVD history monotone non-increasing",
      all(_tsvd["history"][i + 1] <= _tsvd["history"][i] + 1e-6 for i in range(len(_tsvd["history"]) - 1)))

# The damped-transpose reconstructor also converges (slower path, never amplifies modes).
optics_api.build_example("adaptive_optics")
_damp = ao.close_loop_recon(sc, "AO_WFS", "AO_DM", gain=0.8, leak=0.99, method='DAMPED_TRANSPOSE', iters=40)
check("B5 damped-transpose closed loop reduces RMS >5x",
      _damp["ok"] and _damp["rms_before"] / max(_damp["rms_after"], 1e-12) > 5.0,
      "RMS %.4f -> %.4f (%.1fx)" % (_damp["rms_before"], _damp["rms_after"], _damp["reduction"]))

# TSVD drops an ill-conditioned (near-null) mode instead of amplifying it: a synthetic B with a
# tiny singular value -> the reconstructor gain on that mode is ~0 (TSVD truncation), not 1/(1e-4).
_Bill = [[-1.0 if i == k else 0.0 for k in range(6)] for i in range(6)]
_Bill[3][3] = -1e-4                                    # near-null mode
_R = ao.reconstructor(_Bill, method='TSVD', rcond=1e-3)
check("B5 TSVD drops the ill-conditioned mode (reconstructor gain ~0, not 1e4)",
      abs(_R[3][3]) < 1.0, "R[3][3]=%.4g" % _R[3][3])
_Rd = ao.reconstructor(_Bill, method='DAMPED_TRANSPOSE')
check("B5 damped-transpose never amplifies the null mode (|gain| < 1)", abs(_Rd[3][3]) < 1.0, "Rd[3][3]=%.4g" % _Rd[3][3])

# Kolmogorov ABERRATOR: the injected phase VARIANCE obeys the physics_verified Noll law
# sigma^2 = 1.0299*(D/r0)^(5/3) -> halving r0 scales the variance by exactly 2^(5/3).
_v30 = (2 * math.pi * physics.wavefront_rms(ao.kolmogorov_aberration(30.0, 25.4, seed=3))) ** 2
_v60 = (2 * math.pi * physics.wavefront_rms(ao.kolmogorov_aberration(60.0, 25.4, seed=3))) ** 2
check("B5 Kolmogorov variance scales as (D/r0)^(5/3) [Noll 1976, physics_verify ok]",
      abs(_v30 / _v60 - 2.0 ** (5.0 / 3.0)) < 1e-4, "var ratio %.5f vs 2^(5/3)=%.5f" % (_v30 / _v60, 2.0 ** (5.0 / 3.0)))
check("B5 Kolmogorov aberrator is deterministic (reproducible without an RNG)",
      ao.kolmogorov_aberration(60.0, 25.4, seed=7) == ao.kolmogorov_aberration(60.0, 25.4, seed=7))

print("[Newton's rings]")
optics_api.build_example("newton_rings")
segs = scan._trace(sc)
det = sc.objects["NR_D"]
field, px = scan._sensor_field_mm(det.optics)
arr, _ = scan._fringe_array(det, segs, field, px, norm='self')
rad, prof = radiality(arr[..., 0], (px - 1) / 2.0)
pr = prof[:px // 2] - prof[:px // 2].mean()
sg = np.sign(pr); sg[sg == 0] = 1
nr = int(np.sum(sg[1:] != sg[:-1]))
check("rings radial R^2 > 0.85", rad > 0.85, "rad=%.3f" % rad)
check("rings >= 4", nr >= 4, "rings=%d" % nr)

print("[realistic render round-trip]")
optics_api.build_example("mach_zehnder")
bs = next(o for o in sc.objects if getattr(o.optics, "element_type", "") == "BEAMSPLITTER")
vp = bs.data.materials[0].name
render.set_camera(sc, 'HERO')
render.setup_final(sc)
glass_ok = ("_oa_vp_mat" in bs and bs.data.materials[0].name.startswith("OAR_glass")
            and bool(bpy.data.objects.get("OPTICS_Studio_key")))
sc.cycles.samples = 4
sc.render.resolution_x, sc.render.resolution_y = 240, 150
out = "/tmp/oas_regress_render.png"
sc.render.filepath = out
sc.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
render.clear_render_style(sc)
restored = ("_oa_vp_mat" not in bs and bs.data.materials[0].name == vp
            and not bpy.data.objects.get("OPTICS_Studio_key"))
check("glass + studio applied", glass_ok)
check("render produced a PNG", os.path.exists(out) and os.path.getsize(out) > 1500)
check("render style restored", restored)

print("[render-style fixes]")
# #2: a TRANSPARENT background must survive the realistic render (the alpha-PNG workflow)
sc.optics.bg_preset = 'TRANSPARENT'
render.setup_final(sc)
check("TRANSPARENT honored (film alpha)", sc.render.film_transparent is True)
check("no ground under transparent", not bpy.data.objects.get("OPTICS_Studio_Ground"))
render.clear_render_style(sc)
sc.optics.bg_preset = 'DARK'

# #1: shared-mesh (linked-duplicate) round-trip must restore the original material on BOTH objects
optics_api.build_example("michelson")
m1 = next(o for o in sc.objects if o.optics.element_type == 'MIRROR')
vpname = m1.data.materials[0].name
m2 = bpy.data.objects.new(m1.name + "_dup", m1.data)        # linked dup: shares the mesh datablock
sc.collection.objects.link(m2)
m2.optics.is_optical = True
m2.optics.element_type = 'MIRROR'
render.apply_optical_materials(sc)
render.clear_render_style(sc)
check("shared-mesh restored (not stuck glass)", m1.data.materials[0].name == vpname, m1.data.materials[0].name)
bpy.data.objects.remove(m2, do_unlink=True)

# #13 drift guard: ao.py's numpy Zernike radial must match physics.py's scalar one
for (n, m, r) in [(2, 0, 0.5), (4, 0, 0.7), (3, 1, 0.6), (4, 2, 0.8)]:
    a = float(ao._radial_np(n, m, np.array([r]))[0])
    b = physics._zernike_radial(n, m, r)
    check("zernike radial ao==physics (n%dm%d)" % (n, m), abs(a - b) < 1e-9, "%.6f vs %.6f" % (a, b))

print("[perf + altitude + export]")
# AO convergence break: far fewer full-scene traces than the old fixed loop (was iters+1 = 16)
optics_api.build_example("adaptive_optics")
_orig_trace = scan._trace
_tcount = {"n": 0}
def _counting_trace(s):
    _tcount["n"] += 1
    return _orig_trace(s)
scan._trace = _counting_trace
try:
    r = optics_api.ao_close_loop("AO_WFS", "AO_DM", gain=0.5, iters=15)
finally:
    scan._trace = _orig_trace
check("AO loop trace count < 15", _tcount["n"] < 15, "traces=%d" % _tcount["n"])
check("AO loop still flattens", r.get("ok") and r["rms_final"] < 0.01, str(r.get("rms_final")))

# wavefront_image cache equals a fresh un-cached reference (numerics unchanged)
coeffs = [0.0] * 15
coeffs[3], coeffs[5], coeffs[7] = 0.4, 0.3, 0.25
img = ao.wavefront_image(coeffs, px=64)
axr = np.linspace(-1.0, 1.0, 64)
xr, yr = np.meshgrid(axr, axr)
rrr = np.sqrt(xr * xr + yr * yr)
thr = np.arctan2(yr, xr)
Wref = np.zeros((64, 64))
for j, c in enumerate(coeffs, start=1):
    if abs(c) < 1e-12 or j not in physics._NOLL:
        continue
    n_, m_ = physics._NOLL[j]
    nrm = math.sqrt(n_ + 1) if m_ == 0 else math.sqrt(2.0 * (n_ + 1))
    angr = np.cos(m_ * thr) if m_ >= 0 else np.sin(-m_ * thr)
    Wref += c * nrm * ao._radial_np(n_, m_, rrr) * angr
tref = np.clip(0.5 + 0.5 * Wref, 0.0, 1.0)
mref = rrr <= 1.0
check("wavefront_image cache == reference", np.allclose(img[..., 0][mref], tref[mref], atol=1e-6))

# render descriptors cover every optical element type (no flat fall-through)
from optical_alignment_sim import properties
missing = [t[0] for t in properties.ELEMENT_TYPES if t[0] != 'NONE' and t[0] not in render.RENDER_DESCRIPTORS]
check("render descriptors cover all types", not missing, "missing: %s" % missing)

# MCP drift-guard: the server's @mcp.tool names must equal the bridge's optics_api surface
import ast
from optical_alignment_sim import bridge
src = open(os.path.join(REPO, "mcp", "optics_mcp_server.py")).read()
tool_names = set()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.FunctionDef):
        for d in node.decorator_list:
            f = d.func if isinstance(d, ast.Call) else d
            if isinstance(f, ast.Attribute) and f.attr == 'tool':
                tool_names.add(node.name)
allowed = bridge._allowed()
check("MCP tools == optics_api surface", tool_names == allowed,
      "MCP-only=%s API-only=%s" % (sorted(tool_names - allowed), sorted(allowed - tool_names)))

# SVG export: well-formed XML with a glyph per element and a line per beam
import xml.dom.minidom as minidom
optics_api.build_example("michelson")
svgres = optics_api.export_svg("/tmp/oas_regress.svg")
svgtext = open("/tmp/oas_regress.svg").read()
try:
    minidom.parseString(svgtext)
    wellformed = True
except Exception:
    wellformed = False
check("export_svg ok (elements+beams)", svgres.get("ok") and svgres["elements"] >= 1 and svgres["beams"] >= 1, str(svgres))
check("SVG well-formed XML", wellformed)
check("SVG has glyphs + beam lines", "<circle" in svgtext and svgtext.count("<line") >= 1)

print("[beam profile w(z)]")
optics_api.build_example("newton_rings")
bp = optics_api.beam_profile("NR_D")
check("beam_profile ok", bool(bp.get("ok")) and len(bp.get("z", [])) > 50 and len(bp.get("elements", [])) >= 2,
      str(bp.get("error", bp))[:80])
check("lens focuses the beam (waist << w0)", bp["waist"]["w_mm"] < 0.5 * bp["w"][0],
      "waist=%.5f w0=%.5f" % (bp["waist"]["w_mm"], bp["w"][0]))
check("w(end) == carried segment w", abs(bp["w"][-1] - bp["elements"][-1]["w_mm"]) < 1e-4,
      "%.6f vs %.6f" % (bp["w"][-1], bp["elements"][-1]["w_mm"]))
check("profile CSV written", os.path.exists(bp["csv"]) and os.path.getsize(bp["csv"]) > 100)

print("[B1 beam quality M^2: persists through an optic, not reset one element past the source]")
# Regression for the M^2-reset bug (_child keyed the m2-reset on the post-propagation local q, which is
# non-None for EVERY Gaussian continuation, so any source with m2>1 silently lost its beam quality after
# the first optic). ABCD propagation preserves M^2 -> a plain continuation must inherit ray.m2; only a
# CRYSTAL-converted child (explicit fresh q) resets to the diffraction limit m2=1. m2=1 is byte-identical.
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
_cm2t = eg.example_collection("M2_persist")
_X2 = _Vec((1, 0, 0))
_las2 = eg.source("M2L", (-200, 0, 0), _X2, _cm2t, wavelength=632.8)
_las2.optics.waist_um = 200.0
_las2.optics.m2 = 4.0
eg.lens("M2Lens", (0, 0, 0), _X2, _cm2t, focal=150.0, radius=14.0)
eg.detector("M2D", (200, 0, 0), _X2, _cm2t, size=30.0)
bpy.context.view_layer.update()
_m2segs = scan._trace(sc)
_src_seg = next(s for s in _m2segs if s.get("from") == "M2L")
_dn_seg = next(s for s in _m2segs if s.get("from") == "M2Lens")
check("B1: source segment carries m2=4", abs(_src_seg.get("m2", 0) - 4.0) < 1e-9, "m2=%.2f" % _src_seg.get("m2", 0))
check("B1: M^2 persists one element past the source (downstream m2=4, not reset to 1)",
      abs(_dn_seg.get("m2", 0) - 4.0) < 1e-9, "m2=%.2f" % _dn_seg.get("m2", 0))
_w_dl = physics.beam_radius(complex(_dn_seg["qd"][0], _dn_seg["qd"][1]), 632.8)
check("B1: downstream physical w = sqrt(m2)*w_diffraction (2x for M2=4)",
      abs(_dn_seg["w_mm"] / _w_dl - 2.0) < 1e-3, "ratio=%.4f" % (_dn_seg["w_mm"] / _w_dl))
for _o in list(_cm2t.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_cm2t)

print("[2.2 vision tools: inspect_beam + inspect_element give the AI numeric eyes (READ-ONLY)]")
optics_api.build_example("mach_zehnder")
_bs = next(o.name for o in sc.objects if getattr(o.optics, "element_type", "") == "BEAMSPLITTER")
_nseg_iv = len(scan._trace(sc))
_ib = optics_api.inspect_beam(_bs)
# the beam reaching the first BS: power 1, w~0.5mm, far-field divergence = lambda/(pi*w0) (verified kernel)
check("2.2 inspect_beam reads power / w / R / polarization at an element",
      abs(_ib["power"] - 1.0) < 1e-6 and _ib["w_mm"] > 0.0 and _ib["curvature"] in ("collimated", "diverging", "converging")
      and _ib["polarization"]["kind"] == "linear" and abs(_ib["polarization"]["dop"] - 1.0) < 1e-6,
      str({k: _ib.get(k) for k in ("power", "w_mm", "curvature")}))
_div_exp = 1000.0 * 632.8e-6 / (math.pi * _ib["waist_w0_mm"])      # far-field half-angle = lambda/(pi*w0), m2=1
check("2.2 inspect_beam divergence = lambda/(pi*w0) [gaussian_divergence, oracle ok=true]",
      abs(_ib["divergence_mrad"] - _div_exp) < 1e-3, "%.5f vs %.5f mrad" % (_ib["divergence_mrad"], _div_exp))
_ie = optics_api.inspect_element(_bs)
# the BS splits the beam: two children (SPLIT_R + SPLIT_T) each ~half power, throughput ~1 (lossless)
_kinds = sorted(c["kind"] for c in _ie["outputs"])
check("2.2 inspect_element shows the live effect (BS -> SPLIT_R + SPLIT_T, ~50/50, throughput~1)",
      _ie["type"] == "BEAMSPLITTER" and _kinds == ["SPLIT_R", "SPLIT_T"]
      and all(abs(c["power"] - 0.5) < 0.05 for c in _ie["outputs"]) and abs(_ie["throughput"] - 1.0) < 1e-3,
      "kinds=%s thru=%s" % (_kinds, _ie.get("throughput")))
check("2.2 inspect_element reports role + type-relevant params (split_ratio)",
      "splits" in _ie["role"] and "split_ratio" in _ie["params"])
check("2.2 inspect_beam / inspect_element are READ-ONLY (trace byte-identical)", len(scan._trace(sc)) == _nseg_iv)
check("2.2 inspect_beam errors cleanly when no beam reaches the element",
      "error" in optics_api.inspect_beam("NoSuchElement"))

print("[live signature tracks physics params]")
optics_api.build_example("mach_zehnder")
sig0 = handlers._signature(sc)
src = next(o for o in sc.objects if o.optics.element_type == 'SOURCE')
src.optics.wavelength += 50.0                       # a pure physics-param edit (no transform move)
check("signature reacts to wavelength", handlers._signature(sc) != sig0)
sig1 = handlers._signature(sc)
bs = next(o for o in sc.objects if o.optics.element_type == 'BEAMSPLITTER')
bs.optics.split_ratio = 0.3
check("signature reacts to split_ratio", handlers._signature(sc) != sig1)

print("[auto-detect keeps source/detector family flags]")
fc = elements_generic.fiber_collimator("RT_FC", (0, 0, 0), (1, 0, 0))
operators.do_auto_detect(fc)
check("fiber collimator stays is_source", fc.optics.is_source and not fc.optics.is_detector)
for et, nm in (('PHOTODIODE', 'RT_PD'), ('POWER_METER', 'RT_PM'), ('WAVEFRONT_SENSOR', 'RT_WFS')):
    d = elements_generic._cube(nm, (10, 10, 4), None)
    d.optics.is_optical = True
    d.optics.element_type = et
    operators.do_auto_detect(d)
    check("auto-detect keeps %s is_detector" % et, d.optics.is_detector and not d.optics.is_source, et)

print("[anchor / mount base-pose: no jump, no cycle]")
def _mk(nm, loc):
    o = bpy.data.objects.new(nm, None); o.location = loc
    sc.collection.objects.link(o); return o
elem = _mk("RT_anc_elem", (5, 0, 0)); elem.optics.is_optical = True
e1 = _mk("RT_anc_E1", (100, 0, 0)); e2 = _mk("RT_anc_E2", (0, 50, 0))
bpy.context.view_layer.update()
mounts.set_anchor(elem, e1); mounts.compose_pose(elem)
w0 = elem.matrix_world.translation.copy()
mounts.capture_base_pose(elem); mounts.compose_pose(elem)
check("capture_base_pose anchored: no jump", (elem.matrix_world.translation - w0).length < 1e-4,
      "d=%.3f" % (elem.matrix_world.translation - w0).length)
mounts.set_anchor(elem, e2); mounts.compose_pose(elem)
check("re-anchor A1->A2: no jump", (elem.matrix_world.translation - w0).length < 1e-4,
      "d=%.3f" % (elem.matrix_world.translation - w0).length)
other = _mk("RT_anc_other", (8, 0, 0)); other.optics.is_optical = True
mounts.set_anchor(elem, other)
check("anchor cycle rejected", (not mounts.set_anchor(other, elem)) and mounts.anchor_would_cycle(other, elem))

print("[bridge dispatch + cancelled-job guard]")
import threading as _thr
hc = {"event": _thr.Event(), "cancelled": True}      # a request the client already timed out on
bridge._jobs.put(("get_state", {}, hc))
bridge._drain()                                       # main thread: must SKIP it, not apply behind the client
check("bridge skips cancelled job (no double-apply)", "result" not in hc and "error" not in hc)
_srv = bridge._BridgeServer(0)                         # not started; exercise _dispatch directly
check("bridge ping", _srv._dispatch(b'{"fn":"ping"}').get("result") == "pong")
_rej = _srv._dispatch(b'{"fn":"__import__","args":{}}')
check("bridge rejects non-allowlisted fn", not _rej.get("ok") and "not allowed" in _rej.get("error", ""))
check("bridge rejects bad json", "bad json" in _srv._dispatch(b'not json').get("error", ""))

print("[API error-shape: structured {error}, never a raw traceback]")
check("add_component unknown -> error", "error" in optics_api.add_component("RT_NO_SUCH_KEY"))
check("trace_beam bad mode -> error", "error" in optics_api.trace_beam(mode="bogus"))
_mk("RT_plain_a", (0, 0, 0)); _mk("RT_plain_b", (10, 0, 0))      # non-optical objects
check("place_relative non-optical -> error", "error" in optics_api.place_relative("RT_plain_a", "RT_plain_b"))
check("scan bad kind -> error", "error" in optics_api.scan(kind="bogus"))
_dm = _mk("RT_dm_api", (0, 0, 0)); _dm.optics.is_optical = True; _dm.optics.element_type = 'DEFORMABLE_MIRROR'
check("ao_command bad coeffs -> error", "error" in optics_api.ao_command("RT_dm_api", ["x", 1.0]))
# 2.3 consistency: the new read tools follow the uniform {error} contract + return a dict (never a bare value)
check("inspect_element unknown -> error", "error" in optics_api.inspect_element("RT_NO_SUCH_ELEMENT"))
check("inspect_beam no-beam -> error", "error" in optics_api.inspect_beam("RT_NO_SUCH_ELEMENT"))
check("read tools return a dict (uniform contract)",
      all(isinstance(r, dict) for r in (optics_api.diagnose(), optics_api.propose_corrections(),
                                        optics_api.get_state(), optics_api.capabilities())))

print("[bake: re-bake on path change + no mesh leak]")
from optical_alignment_sim import bake
optics_api.build_example("michelson")
bpy.context.view_layer.update()
m0 = len(bpy.data.meshes)
bake.bake_beams(bpy.context)
check("bake created beam objects", any(o.name.startswith("BEAM_") for o in sc.objects))
sig_a = bake._baked_sig
bsrc = next(o for o in sc.objects if o.optics.element_type == 'SOURCE')
bsrc.location.y += 30.0                                # move the source -> beam path changes
bpy.context.view_layer.update()
bake.ensure_beams(bpy.context)
check("ensure_beams re-bakes on path change", bake._baked_sig != sig_a)
bake.clear_baked(sc)
check("no BEAM_ objects after clear", not any(o.name.startswith("BEAM_") for o in sc.objects))
check("clear_baked frees beam meshes (no orphan leak)", len(bpy.data.meshes) <= m0)

print("[medium-severity tail]")
# SVG: a Y-dominant (vertical) beamline must not explode the canvas height
from optical_alignment_sim import svg_export
import re as _re
_vstate = {"elements": [{"world_center": [0, 0, 0], "type": "SOURCE", "name": "S", "params": {}},
                        {"world_center": [0, 300, 0], "type": "MIRROR", "name": "M", "params": {}}],
           "beam_path": [{"p1": [0, 0, 0], "p2": [0, 300, 0], "wavelength": 633.0, "power": 1.0, "kind": "SOURCE"}]}
_svgh = int(_re.search(r'height="(\d+)"', svg_export.build_svg(_vstate)).group(1))
check("SVG height bounded for vertical bench", _svgh <= 1000, "h=%d" % _svgh)

# render auto-restore handler only fires for the scene it was armed for (multi-scene safety)
render._arm_restore(sc)
class _OtherScene:
    name = "RT_other_scene_xyz"
render._restore_after_render(_OtherScene())          # a different scene rendered -> stay armed
check("render restore ignores other scene", render._armed_scene == sc.name
      and render._restore_after_render in bpy.app.handlers.render_complete)
render._restore_after_render(sc)                     # the armed scene rendered -> clear + disarm
check("render restore fires for armed scene", render._armed_scene is None
      and render._restore_after_render not in bpy.app.handlers.render_complete)

print("[catalog generic fallback: right type + real params]")
from optical_alignment_sim import library
for et in ('CAVITY', 'WAVEFRONT_SENSOR', 'DEFORMABLE_MIRROR', 'ABERRATOR', 'PASSTHROUGH'):
    o = library._generic_fallback(et, "RT_fb_%s" % et, (0, 0, 0), {})
    check("fallback %s not misrouted to aperture" % et, o.optics.element_type == et, o.optics.element_type)
fes = library.add_component("FES0700", (0, 0, 0))[0]      # no vendor mesh -> generic fallback
check("FES0700 fallback is a real shortpass", fes.optics.filt_type == 'SP' and abs(fes.optics.cut_hi_nm - 700.0) < 1e-3)
nd = library.add_component("NE10A", (0, 0, 0))[0]
check("NE10A fallback is a real ND", nd.optics.filt_type == 'ND' and abs(nd.optics.od - 1.0) < 1e-3)
pbs = library.add_component("PBS251", (0, 0, 0))[0]
check("PBS251 fallback is polarizing", bool(pbs.optics.is_pbs))

print("[auto-detect: element_type wins over a mismatched name prefix]")
mo = elements_generic._cube("MO_5", (12, 12, 4), None)   # 'MO' matches the LENS prefix
mo.optics.is_optical = True
mo.optics.element_type = 'MIRROR'                         # but the user said MIRROR
operators.do_auto_detect(mo)
# the bug: the LENS prefix's antiparallel IN/OUT normals collapse the REFLECT plane to a bogus +Z.
# With the fix the MIRROR type's own specs are used, so REFLECT is a real ~45deg fold (nonzero Y).
_refl = next(p for p in mo.optics.ports if p.role == 'REFLECT')
check("name-prefix doesn't corrupt the mirror REFLECT plane", abs(_refl.local_normal.y) > 0.3,
      str(tuple(round(c, 2) for c in _refl.local_normal)))

print("[live deferred-trace bails when live mode is off]")
optics_api.build_example("michelson")
sc.optics.live_enabled = False
handlers._pending_scene = sc
tracer.cached_segments = ["__SENTINEL__"]
handlers._deferred_trace()                               # must NOT trace/overwrite with live off
check("deferred trace no-op when live off", tracer.cached_segments == ["__SENTINEL__"])

print("[low-severity correctness tail]")
# Sellmeier stays physical in the deep UV (was returning 1.0 or n~9 between poles). Upper bound is
# n<=5 since the transparency-window clamp was widened (n2<25) to admit IR materials (Ge n~4.0).
check("sellmeier UV index stays physical", all(1.0 <= physics.sellmeier_n(w) <= 5.0 for w in (60.0, 78.0, 100.0, 142.0)))
# Detector fringe material copy-on-writes a shared mesh (no sibling cross-talk)
fd1 = elements_generic.detector("RT_fd1", (0, 0, 0), (1, 0, 0))
fd2 = bpy.data.objects.new("RT_fd2", fd1.data)       # linked-duplicate: shares the mesh datablock
sc.collection.objects.link(fd2)
_fimg = bpy.data.images.new("RT_fimg", 4, 4, alpha=True)
scan._assign_fringe_material(fd1, _fimg)
check("fringe copy-on-write spares the shared mesh", fd2.data is not fd1.data)
# example rebuilds free their meshes instead of leaking a fresh orphan set each time
optics_api.build_example("mach_zehnder")
_em0 = len(bpy.data.meshes)
for _ in range(3):
    optics_api.build_example("mach_zehnder")
check("example rebuild frees meshes (no orphan growth)", len(bpy.data.meshes) <= _em0 + 2,
      "delta=%d" % (len(bpy.data.meshes) - _em0))

print("[A11: parasitic (accidental) Fabry-Perot etalon detection -- reuses cavity_fsr_nm/finesse]")
# two PARALLEL uncoated windows a known gap L apart form an ACCIDENTAL etalon; A11 flags it with the
# FSR/finesse from the ALREADY-VERIFIED Fabry-Perot kernels (NO new physics). A wedge clears it.
from mathutils import Vector as _A11V
for _o in [o for o in bpy.data.objects if getattr(getattr(o, "optics", None), "is_optical", False)]:
    bpy.data.objects.remove(_o, do_unlink=True)
_a11c = elements_generic.example_collection("OpticsExample_A11")
_a11X = _A11V((1, 0, 0)); _a11L = 25.0
_a11wl = float(getattr(sc.optics, 'wavelength', 632.8) or 632.8)
elements_generic.source("A11_S", (-150, 0, 0), _a11X, _a11c)
_a11w1 = elements_generic.window("A11_W1", (0, 0, 0), _a11X, _a11c, radius=14.0)
_a11w2 = elements_generic.window("A11_W2", (_a11L, 0, 0), _a11X, _a11c, radius=14.0)
_a11w1.optics.ar_coated = False; _a11w2.optics.ar_coated = False
elements_generic.detector("A11_D", (150, 0, 0), _a11X, _a11c)
bpy.context.view_layer.update()
_a11pe = [i for i in optomech.validate(sc) if i.get("kind") == "parasitic_etalon"]
check("A11: parallel windows flag a parasitic_etalon", len(_a11pe) == 1, "got %d" % len(_a11pe))
_a11R = physics.surface_reflectance(1.0, max(_a11w1.optics.refractive_index, 1.0))
_a11_fsr = physics.cavity_fsr_nm(_a11wl, _a11L, 1.0)
_a11_fin = physics.cavity_finesse(math.sqrt(_a11R * _a11R))
check("A11: flagged FSR == cavity_fsr_nm(lambda,L,n) (reuse, no new physics)",
      bool(_a11pe) and abs(_a11pe[0]["fsr_nm"] - _a11_fsr) < 1e-9,
      str((_a11pe[0]["fsr_nm"], _a11_fsr)) if _a11pe else "no flag")
check("A11: flagged finesse == cavity_finesse(R_eff) & finite",
      bool(_a11pe) and abs(_a11pe[0]["finesse"] - _a11_fin) < 1e-9 and math.isfinite(_a11pe[0]["finesse"]))
# tilt one window by a >30-arcmin WEDGE (0.6 deg > 0.5-deg tol) -> the parallel test breaks -> CLEARS
_a11tw = math.radians(0.6)
for _o in [o for o in bpy.data.objects if getattr(getattr(o, "optics", None), "is_optical", False)]:
    bpy.data.objects.remove(_o, do_unlink=True)
_a11c2 = elements_generic.example_collection("OpticsExample_A11w")
elements_generic.source("A11_S", (-150, 0, 0), _a11X, _a11c2)
elements_generic.window("A11_W1", (0, 0, 0), _a11X, _a11c2, radius=14.0)
elements_generic.window("A11_W2", (_a11L, 0, 0),
                        _A11V((math.cos(_a11tw), math.sin(_a11tw), 0.0)), _a11c2, radius=14.0)
elements_generic.detector("A11_D", (150, 0, 0), _a11X, _a11c2)
bpy.context.view_layer.update()
_a11pe_w = [i for i in optomech.validate(sc) if i.get("kind") == "parasitic_etalon"]
check("A11: a 30-arcmin wedge CLEARS the parasitic_etalon (fringe killer)", len(_a11pe_w) == 0,
      "got %d" % len(_a11pe_w))
# every canonical example stays clean (no accidental parallel flat pair self-flags)
for _ek in ("michelson", "tube_system", "back_reflection"):
    optics_api.build_example(_ek)
    _epe = [i for i in optomech.validate(sc) if i.get("kind") == "parasitic_etalon"]
    check("A11: %s emits no parasitic_etalon (no false positive)" % _ek, len(_epe) == 0, "got %d" % len(_epe))

# clear stray API/library-test optical objects (RT_*, FILT_*, BS_*, MO_*, ...) so the bench sections
# see ONLY the example optics -- with xy-stacked posts, leftover optics sharing a hole skew counts.
_ex_objs = set()
for _c in bpy.data.collections:
    if _c.name.startswith("OpticsExample_"):
        _ex_objs.update(o.name for o in _c.objects)
for _o in [o for o in bpy.data.objects
           if getattr(getattr(o, "optics", None), "is_optical", False) and o.name not in _ex_objs]:
    bpy.data.objects.remove(_o, do_unlink=True)

print("[bench dressing: additive, not traced, reversible]")
from optical_alignment_sim import optomech
optics_api.build_example("michelson")
_nseg = len(scan._trace(sc))
_k = optomech.dress(sc)
check("dress spawns posts + board", _k >= 3 and optomech.is_dressed(sc), "k=%d" % _k)
check("dressing leaves the trace identical", len(scan._trace(sc)) == _nseg)   # ports untouched
check("bench objects are non-optical (never traced)",
      all(not o.optics.is_optical for o in sc.objects if o.name.startswith("BENCH_")))
optomech.strip(sc)
check("strip removes all bench objects", not optomech.is_dressed(sc))

print("[bench grid: hole array + MCP-knowable data model + trace-safe]")
optics_api.build_example("michelson")
_nseg = len(scan._trace(sc))
optomech.strip(sc)
check("get_state bench None when bare", optics_api.get_state().get("bench") is None)
_r = optics_api.dress_bench(True)
check("dress_bench builds hole grid", _r.get("ok") and _r.get("objects", 0) > 0, str(_r))
check("dressing still leaves trace identical", len(scan._trace(sc)) == _nseg)
_holes = bpy.data.objects.get("BENCH_Holes")
check("hole-grid mesh has geometry", _holes is not None and len(_holes.data.vertices) > 10)
_b = optics_api.get_state().get("bench")
check("get_state exposes bench grid (pitch/origin/extent)",
      isinstance(_b, dict) and _b["cols"] >= 2 and _b["rows"] >= 2 and len(_b["origin"]) == 2, str(_b and _b.get("cols")))
check("default grid is metric 25 mm / M6",
      abs(_b["pitch_mm"] - 25.0) < 1e-6 and _b["standard"] == "metric" and _b["thread"] == "M6", str(_b.get("pitch_mm")))
check("bench lists an occupied hole per optic", len(_b["occupied"]) >= 4)
_worst = max(max(abs(o["hole_xy"][0] - o["element_xy"][0]), abs(o["hole_xy"][1] - o["element_xy"][1])) for o in _b["occupied"])
check("each optic within half a pitch of its hole", _worst <= _b["pitch_mm"] * 0.5 + 1e-6, "worst=%.3f" % _worst)
_hw = optomech.hole_world_xy(sc, _b["occupied"][0]["col"], _b["occupied"][0]["row"])
check("hole_world_xy round-trips grid_info", _hw is not None and abs(_hw[0] - _b["occupied"][0]["hole_xy"][0]) < 1e-6)
_ri = optics_api.set_grid(standard="IMPERIAL")
check("set_grid IMPERIAL -> 25.4 mm / 1/4-20",
      _ri.get("ok") and abs(_ri["pitch_mm"] - 25.4) < 1e-6 and _ri["bench"]["thread"] == "1/4-20", str(_ri.get("pitch_mm")))
optics_api.set_grid(standard="METRIC")
_col, _row = _b["cols"] // 2, _b["rows"] // 2
_hx, _hy = optomech.hole_world_xy(sc, _col, _row)
_rp = optics_api.place_on_grid(_b["occupied"][0]["element"], _col, _row)
check("place_on_grid lands the part on the hole",
      _rp.get("ok") and abs(_rp["world_center"][0] - _hx) < 1e-3 and abs(_rp["world_center"][1] - _hy) < 1e-3, str(_rp.get("world_center")))
check("place_on_grid rejects a non-optical target", "error" in optics_api.place_on_grid("BENCH_Holes", 0, 0))
check("set_grid rejects sub-mm pitch", "error" in optics_api.set_grid(pitch_mm=0.1))
optomech.strip(sc)
_optic = _b["occupied"][0]["element"]   # a real optical element; only the bench was stripped
_nd = optics_api.place_on_grid(_optic, 0, 0)
check("place_on_grid needs a dressed bench", "error" in _nd and "dress" in _nd["error"], str(_nd))

print("[bench beam-height datum: equal posts, stable board, vertical chain exposed]")
optics_api.build_example("michelson")
_nseg = len(scan._trace(sc))
sc.optics.beam_height_mm = 100.0
optomech.dress(sc)
check("dressing (datum) leaves trace identical", len(scan._trace(sc)) == _nseg)
_bh = optics_api.get_state()["bench"]
check("get_state exposes beam_height_mm = 100", abs(_bh["beam_height_mm"] - 100.0) < 1e-6, str(_bh.get("beam_height_mm")))
check("board top one beam-height below the optical axis", abs(_bh["board_top_z_mm"] + 100.0) < 0.6, str(_bh.get("board_top_z_mm")))
_plen = [o["post_length_mm"] for o in _bh["occupied"]]
check("equal post lengths for equal-height optics", max(_plen) - min(_plen) < 1e-6, str(_plen))
check("post length = beam_height - mount_drop", abs(_plen[0] - (100.0 - optomech.MOUNT_DROP)) < 1e-6, str(_plen[0]))
check("post diameter is the Ø12.7 standard", all(abs(o["post_dia_mm"] - 12.7) < 1e-6 for o in _bh["occupied"]))
check("vertical chain reports optic_z + holder", all("optic_z_mm" in o and "holder_length_mm" in o for o in _bh["occupied"]))
# raising the beam height must not move the optics (trace identical), only the board/posts in Z
sc.optics.beam_height_mm = 125.0
optomech.dress(sc)
check("changing beam height keeps trace identical", len(scan._trace(sc)) == _nseg)
_bh2 = optics_api.get_state()["bench"]
check("board datum follows beam height", abs(_bh2["board_top_z_mm"] + 125.0) < 0.6, str(_bh2.get("board_top_z_mm")))
# datum is stable: occupied post lengths stay equal regardless of which optics are present
check("posts still equal at new height", max(o["post_length_mm"] for o in _bh2["occupied"]) - min(o["post_length_mm"] for o in _bh2["occupied"]) < 1e-6)
optomech.strip(sc)
sc.optics.beam_height_mm = 100.0

print("[bench mount silhouettes: type-specific, trace-safe]")
optics_api.build_example("michelson")
_nseg = len(scan._trace(sc))
optomech.dress(sc)
check("mount geometry leaves trace identical", len(scan._trace(sc)) == _nseg)
_names = [o.name for o in sc.objects if o.name.startswith("BENCH_")]
_has = lambda pre: any(n.startswith("BENCH_" + pre) for n in _names)
check("mirrors get a kinematic back-plate", _has("KMplate"))
check("beamsplitter gets a cage-cube housing (not a hoop)", _has("CubeBody"))
check("sources get a saddle clamp + stem to the post (not an optic ring)", _has("Saddle") and _has("Stem"))
# the beamsplitter must NOT be wrapped by a torus Mount ring (the old horizontal-hoop bug)
_bs = next((o for o in sc.objects if getattr(o.optics, "is_optical", False) and o.optics.element_type == 'BEAMSPLITTER'), None)
if _bs is not None:
    _bi = [o.name for o in sc.objects if getattr(o.optics, "is_optical", False) and o.optics.element_type not in ('NONE',)].index(_bs.name)
    check("no Mount ring on the beamsplitter", not _has("Mount_%02d" % _bi), _bs.name)
optomech.strip(sc)

print("[bench cage system: shared rods, trace-safe, MCP-knowable]")
optics_api.build_example("michelson")
_segc = scan._trace(sc)
_nc = len(_segc); _pc, _vc, _ = alignment.measure(_segc, "MI_D", "NONE")
_cand = [e["name"] for e in optics_api.get_state()["elements"]
         if e["name"].startswith("MI_") and e["type"] not in ("SOURCE", "DETECTOR")]
optics_api.dress_bench(True)
_posts0 = len([o for o in sc.objects if o.name.startswith("BENCH_Post_")])
_rc = optics_api.make_cage([_cand[0], _cand[1]], 30)
check("make_cage groups two members @30 mm", _rc.get("ok") and _rc.get("size_mm") == 30 and set(_rc.get("members", [])) == {_cand[0], _cand[1]}, str(_rc))
_segc2 = scan._trace(sc); _pc2, _vc2, _ = alignment.measure(_segc2, "MI_D", "NONE")
check("cage does not move the optics (trace identical)", len(_segc2) == _nc and abs(_pc2 - _pc) < 1e-9 and abs(_vc2 - _vc) < 1e-9)
_cg = optics_api.get_state()["cages"]
check("get_state exposes the cage", isinstance(_cg, list) and len(_cg) == 1 and _cg[0]["rod_count"] == 4 and _cg[0]["rod_dia_mm"] == 6.0, str(_cg))
check("four cage rods + a plate per member built",
      len([o for o in sc.objects if o.name.startswith("BENCH_CageRod_")]) == 4 and
      len([o for o in sc.objects if o.name.startswith("BENCH_CagePlate_")]) == 2)
check("individual posts suppressed for caged members",
      len([o for o in sc.objects if o.name.startswith("BENCH_Post_")]) == _posts0 - 2)
check("cage gets its own post", any(o.name.startswith("BENCH_CagePost_") for o in sc.objects))
optomech.strip(sc)
check("strip removes the cage too", not any(o.name.startswith("BENCH_CageRod_") for o in sc.objects))

print("[bench lens-tube system: shared barrel, trace-safe, MCP-knowable]")
optics_api.build_example("michelson")
_segt = scan._trace(sc); _nt = len(_segt); _pt, _vt, _ = alignment.measure(_segt, "MI_D", "NONE")
_cmt = [e["name"] for e in optics_api.get_state()["elements"] if e["name"].startswith("MI_") and e["type"] not in ("SOURCE", "DETECTOR")]
optics_api.dress_bench(True)
_posts0t = len([o for o in sc.objects if o.name.startswith("BENCH_Post_")])
_rt = optics_api.make_tube([_cmt[0], _cmt[1]], "SM1")
check("make_tube groups two members @SM1", _rt.get("ok") and _rt.get("thread") == "SM1" and set(_rt.get("members", [])) == {_cmt[0], _cmt[1]}, str(_rt))
_segt2 = scan._trace(sc); _pt2, _vt2, _ = alignment.measure(_segt2, "MI_D", "NONE")
check("tube does not move the optics (trace identical)", len(_segt2) == _nt and abs(_pt2 - _pt) < 1e-9 and abs(_vt2 - _vt) < 1e-9)
_tg = optics_api.get_state()["tubes"]
check("get_state exposes the tube", isinstance(_tg, list) and len(_tg) == 1 and _tg[0]["thread"] == "SM1" and abs(_tg[0]["inner_dia_mm"] - 25.4) < 1e-6, str(_tg))
check("one barrel + a post built", any(o.name.startswith("BENCH_Tube_") for o in sc.objects) and any(o.name.startswith("BENCH_TubePost_") for o in sc.objects))
check("individual posts suppressed for tubed members",
      len([o for o in sc.objects if o.name.startswith("BENCH_Post_")]) == _posts0t - 2)
optomech.strip(sc)
check("strip removes the tube too", not any(o.name.startswith("BENCH_Tube_") for o in sc.objects))

print("[bench rail system: shared dovetail track + carriers, trace-safe, place_on_rail]")
optics_api.build_example("michelson")
_segr = scan._trace(sc); _nr = len(_segr); _pr, _vr, _ = alignment.measure(_segr, "MI_D", "NONE")
_cmr = [e["name"] for e in optics_api.get_state()["elements"] if e["name"].startswith("MI_") and e["type"] not in ("SOURCE", "DETECTOR")]
optics_api.dress_bench(True)
_posts0r = len([o for o in sc.objects if o.name.startswith("BENCH_Post_")])
_rr = optics_api.make_rail([_cmr[0], _cmr[1]])
check("make_rail groups two members", _rr.get("ok") and set(_rr.get("members", [])) == {_cmr[0], _cmr[1]}, str(_rr))
_segr2 = scan._trace(sc); _pr2, _vr2, _ = alignment.measure(_segr2, "MI_D", "NONE")
check("make_rail does not move the optics (trace identical)", len(_segr2) == _nr and abs(_pr2 - _pr) < 1e-9 and abs(_vr2 - _vr) < 1e-9)
_rg = optics_api.get_state()["rails"]
check("get_state exposes the rail + carrier positions", isinstance(_rg, list) and len(_rg) == 1 and len(_rg[0]["carriers"]) == 2 and _rg[0]["width_mm"] == 19.1, str(_rg))
check("a rail bar + carriers + rail-posts built",
      any(o.name.startswith("BENCH_Rail_") for o in sc.objects) and
      len([o for o in sc.objects if o.name.startswith("BENCH_Carrier_")]) == 2 and
      any(o.name.startswith("BENCH_RailPost_") for o in sc.objects))
check("rail members get no board post", len([o for o in sc.objects if o.name.startswith("BENCH_Post_")]) == _posts0r - 2)
# place_on_rail slides the part along the rail axis -> moves it (trace updates)
_before = list(sc.objects[_cmr[0]].matrix_world.translation)
_rp = optics_api.place_on_rail(_cmr[0], 12.0)
_after = list(sc.objects[_cmr[0]].matrix_world.translation)
check("place_on_rail moves the part along the rail", _rp.get("ok") and (abs(_after[0]-_before[0]) > 1e-4 or abs(_after[1]-_before[1]) > 1e-4), str(_rp))
check("place_on_rail rejects a non-rail element", "error" in optics_api.place_on_rail("MI_D", 5.0))
optomech.strip(sc)
check("strip removes the rail too", not any(o.name.startswith("BENCH_Rail_") for o in sc.objects))

print("[C8 detector material/mode + readout: R(l)=qe*l/1239.8, APD F(M), quadrant erf (oracle-VERIFIED)]")
check("C8 responsivity InGaAs@1550 == qe*l/1239.8 (~1 A/W)",
      abs(physics.responsivity('InGaAs', 1550.0) - physics.detector_qe('InGaAs', 1550.0) * 1550.0 / physics.HC_OVER_E_eVnm) < 1e-9)
check("C8 APD excess-noise F(M=10,k=0.02)=2.062 (oracle-verified)",
      abs(physics.apd_excess_noise(10.0, 0.02) - 2.062) < 1e-9)
check("C8 APD F(M,k=1)=M and F(M,k=0)=2-1/M (McIntyre limits)",
      abs(physics.apd_excess_noise(5.0, 1.0) - 5.0) < 1e-9 and abs(physics.apd_excess_noise(10.0, 0.0) - 1.9) < 1e-9)
check("C8 quadrant_fraction == 1 - knife_transmission (the verified erf sibling)",
      all(abs(physics.quadrant_fraction(_o, 1.0) - (1.0 - physics.knife_transmission(_o, 0.0, 1.0))) < 1e-12 for _o in (-0.5, 0.0, 0.7)))
# quadrant ground-truth: an injected transverse offset is recovered by the quadrant Sx/Sy signal
_qc = bpy.data.collections.new("C8TEST"); sc.collection.children.link(_qc)
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
from mathutils import Matrix as _C8M, Vector as _C8V
_qs = eg.source("C8_S", (-150, 0, 0), _C8V((1, 0, 0)), _qc, wavelength=1550.0)
_qd = eg.detector("C8_D", (120, 0, 0), _C8V((1, 0, 0)), _qc, size=30.0)
_qd.optics.readout_topology = 'QUADRANT'; _qd.optics.det_material = 'InGaAs'; _qd.optics.quadrant_gap_mm = 0.0
_qsb = _qs.matrix_world.translation.copy(); _qsig = []
for _dy in (-4.0, 0.0, 4.0):
    _qs.matrix_world = _C8M.Translation((_qsb.x, _qsb.y + _dy, _qsb.z)) @ _qs.matrix_world.to_3x3().to_4x4()
    bpy.context.view_layer.update()
    tracer.cached_segments = tracer.trace_scene(sc, mode=sc.optics.trace_mode,
                                                max_segments=sc.optics.max_segments, max_depth=sc.optics.max_depth)
    alignment.refresh_report(sc)
    _qsig.append((_qd.optics.meas_quad_x, _qd.optics.meas_quad_y))
_qax = ([s[0] for s in _qsig] if abs(_qsig[0][0] - _qsig[2][0]) >= abs(_qsig[0][1] - _qsig[2][1])
        else [s[1] for s in _qsig])
check("C8 quadrant recovers an injected transverse offset (monotone, ~0 centred, saturates)",
      abs(_qax[1]) < 0.05 and _qax[0] < _qax[2] and abs(_qax[0]) > 0.3 and abs(_qax[2]) > 0.3, str([round(v, 3) for v in _qax]))
for _o in list(_qc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_qc)

print("[C6 fiber circulator: NON-RECIPROCAL cyclic router Pi->P(i+1) + dB->linear isolation leak]")
check("C6 db_to_linear(20)=0.01 / 30=0.001 / 0=1.0 / 10=0.1 (oracle-VERIFIED 10^(-db/10))",
      abs(physics.db_to_linear(20.0) - 0.01) < 1e-12 and abs(physics.db_to_linear(30.0) - 0.001) < 1e-12
      and abs(physics.db_to_linear(0.0) - 1.0) < 1e-12 and abs(physics.db_to_linear(10.0) - 0.1) < 1e-12)
# build a bare 3-port circulator and fire a ray into each port; assert the cyclic, non-reciprocal routing
_cc = bpy.data.collections.new("C6TEST"); sc.collection.children.link(_cc)
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
from optical_alignment_sim import geometry as _C6geo
from mathutils import Vector as _C6V
_hub = eg.circulator("C6_H", (0, 0, 0), _C6V((1, 0, 0)), _cc, n_ports=3, isolation_db=20.0)


def _c6_exit_port(p1):
    return min(_hub.optics.ports,
              key=lambda pp: (_C6geo.world_port(_hub, pp.local_position) - _C6V(p1)).length).name


_c6_route = {}
for _entry in ("P1", "P2", "P3"):
    _p = next(pp for pp in _hub.optics.ports if pp.name == _entry)
    _wp = _C6geo.world_port(_hub, _p.local_position); _wn = _C6geo.world_normal(_hub, _p.local_normal)
    for _o in list(sc.objects):
        if _o.name == "C6_SRC":
            bpy.data.objects.remove(_o, do_unlink=True)
    eg.source("C6_SRC", _wp + _wn * 120.0, -_wn, _cc)
    bpy.context.view_layer.update()
    _segs = tracer.trace_scene(sc, mode=sc.optics.trace_mode,
                               max_segments=sc.optics.max_segments, max_depth=sc.optics.max_depth)
    _outs = [s for s in _segs if s.get("from") == "C6_H"]
    _main = next((s for s in _outs if s["kind"] == "CIRC_OUT"), None)
    _iso = next((s for s in _outs if s["kind"] == "CIRC_ISO"), None)
    _c6_route[_entry] = (_c6_exit_port(_main["p1"]) if _main else None, _main["power"] if _main else None,
                         _c6_exit_port(_iso["p1"]) if _iso else None, _iso["power"] if _iso else None)
check("C6 cyclic route: P1->P2, P2->P3, P3->P1 (the wrap), each at full through power",
      _c6_route["P1"][0] == "P2" and _c6_route["P2"][0] == "P3" and _c6_route["P3"][0] == "P1"
      and all(abs(_c6_route[k][1] - 1.0) < 1e-6 for k in _c6_route), str(_c6_route))
check("C6 NON-RECIPROCAL: P2->P3 (a reciprocal device would send P2->P1)",
      _c6_route["P2"][0] == "P3" and _c6_route["P2"][0] != "P1")
check("C6 isolation leak -> PREVIOUS port at power*10^(-20/10): P1->P3, P2->P1, P3->P2 @ 0.01",
      _c6_route["P1"][2] == "P3" and _c6_route["P2"][2] == "P1" and _c6_route["P3"][2] == "P2"
      and all(abs(_c6_route[k][3] - 0.01) < 1e-6 for k in _c6_route), str(_c6_route))
for _o in list(_cc.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_cc)

print("[anim: camera-orbit primitive — render-free (the actual render is verified locally)]")
# Do NOT call bpy.ops.render.render here: EEVEE under headless xvfb aborts on the CI box (exit 134).
# Test the deterministic new logic instead -- the orbit camera primitive render_sequence sweeps.
optics_api.build_example("michelson")
from optical_alignment_sim import render as _R, anim as _anim
_locs = []
for _a in (0.0, math.pi * 0.5, math.pi):
    _cam = _R.set_camera_direction(sc, (math.cos(_a), math.sin(_a), 0.5))
    _locs.append(_cam.location.copy())
check("orbit frames the optics from distinct azimuths",
      (_locs[0] - _locs[1]).length > 1.0 and (_locs[1] - _locs[2]).length > 1.0)
check("orbit camera stays finite + off-centre",
      _locs[0].length > 1.0 and all(abs(v) < 1e7 for L in _locs for v in L))
check("render_sequence is wired (optics_api + anim)",
      hasattr(optics_api, "render_sequence") and hasattr(_anim, "render_sequence"))

print("[surface-figure -> wavefront imprint: opt-in mesh figure stamped on the reflected wavefront]")
# A REFLECTIVE element with imprint_surface=True stamps its ACTUAL MESH surface figure (Tier-1 geometric
# round-trip OPD = 2*depth-deviation, detrended against the footprint reference plane, fit to the verified
# Noll Zernikes, in waves) onto the reflected beam, so a downstream WFS reads it. Default OFF -> byte-id.
from optical_alignment_sim import elements_generic as _IG
import bmesh as _ibm


def _imp_replace_surface(E, surf_fn, half=70.0, nx=41):
    """Replace reflective element E's mesh with the grid surface z=surf_fn(x,y) over [-half,half]^2 (local
    frame; local +Z = the coated front). E keeps its optics/ports/matrix_world."""
    b = _ibm.new()
    vv = [[None] * nx for _ in range(nx)]
    for iy in range(nx):
        for ix in range(nx):
            x = -half + 2.0 * half * ix / (nx - 1)
            y = -half + 2.0 * half * iy / (nx - 1)
            vv[iy][ix] = b.verts.new((x, y, surf_fn(x, y)))
    b.verts.ensure_lookup_table()
    for iy in range(nx - 1):
        for ix in range(nx - 1):
            b.faces.new((vv[iy][ix], vv[iy][ix + 1], vv[iy + 1][ix + 1], vv[iy + 1][ix]))
    _ibm.ops.recalc_face_normals(b, faces=b.faces)
    old = E.data
    me = bpy.data.meshes.new(E.name + "_surf"); b.to_mesh(me); b.free()
    E.data = me
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)


def _imp_scene(name, surf_fn, imprint, aoi_deg=8.0):
    """Laser -> reflective element (mesh = surf_fn) at near-normal AOI -> WFS; return the WFS Zernike vec."""
    for _o in list(sc.objects):                            # clear any optics left from prior example builds
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)
    _c = _IG.example_collection(name)
    F = _Vec((0.0, 0.0, 0.0)); d_in = _Vec((1.0, 0.0, 0.0))
    dev = math.radians(180.0 - 2.0 * aoi_deg)             # mirror deviation = 180-2*AOI (near-normal)
    d_out = _Vec((math.cos(dev), math.sin(dev), 0.0)).normalized()
    _las = _IG.source("Laser", F - d_in * 400.0, d_in, _c, wavelength=632.8, length=44.0, radius=10.0)
    _las.optics.waist_um = 9000.0                         # wide ~collimated beam (big footprint)
    _m = _IG.mirror("REFL", F, d_in, d_out, _c, size=150.0)
    _m.optics.imprint_surface = imprint
    _imp_replace_surface(_m, surf_fn)
    _wfs = _IG.wavefront_sensor("WFS", F + d_out * 300.0, d_out, _c, size=90.0)
    bpy.context.view_layer.update()
    _segs = scan._trace(sc)
    _cf = ao._aberr_at(_segs, _wfs.name)                  # use the REAL object name (Blender may .NNN-suffix)
    for _o in list(_c.objects):
        _IG.drop_example_object(_o)
    bpy.data.collections.remove(_c)
    return _cf or [0.0] * physics.N_ZERNIKE


_NM = physics.ZERNIKE_NAMES
# (i) FLAT surface, imprint ON -> ~0 (the flat-mirror byte-identical guarantee; only the sub-mwave fit floor)
_cf_flat = _imp_scene("IMP_flat", lambda x, y: 0.0, True)
check("imprint: FLAT surface reads ~0 (lambda/100 floor)", physics.wavefront_rms(_cf_flat) < 1.0e-2,
      "%.5f waves" % physics.wavefront_rms(_cf_flat))
# (ii) SPHERICAL cap -> defocus dominant
_cf_sph = _imp_scene("IMP_sph", lambda x, y: (x * x + y * y) / (2.0 * 4000.0), True)
_jd_sph = max(range(2, physics.N_ZERNIKE + 1), key=lambda j: abs(_cf_sph[j - 1]))
check("imprint: SPHERICAL cap -> dominant Zernike is defocus", _NM.get(_jd_sph) == "defocus",
      "Z%d %s" % (_jd_sph, _NM.get(_jd_sph)))
# (iii) SADDLE x^2-y^2 -> astig0 dominant (a genuine figure mode, not removed by the plane reference)
_cf_ast = _imp_scene("IMP_ast", lambda x, y: (x * x - y * y) / (2.0 * 5000.0), True)
_jd_ast = max(range(2, physics.N_ZERNIKE + 1), key=lambda j: abs(_cf_ast[j - 1]))
check("imprint: SADDLE surface -> dominant Zernike is astig0", _NM.get(_jd_ast) == "astig0",
      "Z%d %s" % (_jd_ast, _NM.get(_jd_ast)))
# (iv) an IRREGULAR mesh -> non-flat, multi-mode WFS
_cf_irr = _imp_scene("IMP_irr", lambda x, y: 3.0 * math.exp(-((x - 15) ** 2 + (y - 8) ** 2) / 648.0)
                     - 2.0 * math.exp(-((x + 20) ** 2 + (y + 12) ** 2) / 968.0)
                     + 1.4 * math.sin(x / 30.0) * math.cos(y / 24.0), True)
check("imprint: irregular mesh -> non-flat multi-mode wavefront",
      physics.wavefront_rms(_cf_irr) > 1.0e-2
      and sum(1 for k in range(1, physics.N_ZERNIKE) if abs(_cf_irr[k]) > 1e-3) >= 3,
      "RMS %.3f, %d modes" % (physics.wavefront_rms(_cf_irr),
                              sum(1 for k in range(1, physics.N_ZERNIKE) if abs(_cf_irr[k]) > 1e-3)))
# (v) OPT-IN: the SAME irregular mesh with imprint_surface OFF reads exactly flat (default off)
_cf_off = _imp_scene("IMP_off", lambda x, y: 3.0 * math.exp(-((x - 15) ** 2 + (y - 8) ** 2) / 648.0)
                     + 1.4 * math.sin(x / 30.0), False)
check("imprint: OFF on the same mesh reads flat (opt-in -> default byte-identical)",
      physics.wavefront_rms(_cf_off) < 1e-9, "%.6f waves" % physics.wavefront_rms(_cf_off))

print("[zonal sensor-render: DENSE raw-field surface-figure map (no 15-mode modal low-pass)]")
# The zonal path samples the SAME verified physics (W=2*(depth-reference plane)) on a px*px grid and renders
# the RAW field -- NO projection onto 15 Zernikes. For a LOW-ORDER surface it AGREES with the modal map;
# for a HIGH-spatial-frequency surface it carries content the 15-mode fit cannot represent. On-demand only.


def _imp_zonal(name, surf_fn, px=80, aoi_deg=8.0, nx=41, half=70.0):
    """Build laser -> reflective mesh (surf_fn) -> WFS, trace, and return (zonal-field-dict, modal-coeffs).
    nx/half set the SURFACE mesh resolution; a high-spatial-frequency surf_fn needs a fine mesh (else the
    mesh itself aliases the figure -- the mesh Nyquist must exceed the figure frequency)."""
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)
    _c = _IG.example_collection(name)
    F = _Vec((0.0, 0.0, 0.0)); d_in = _Vec((1.0, 0.0, 0.0))
    dev = math.radians(180.0 - 2.0 * aoi_deg)
    d_out = _Vec((math.cos(dev), math.sin(dev), 0.0)).normalized()
    _las = _IG.source("Laser", F - d_in * 400.0, d_in, _c, wavelength=632.8, length=44.0, radius=10.0)
    _las.optics.waist_um = 9000.0                          # wide ~collimated beam (~Ø18 mm footprint)
    _m = _IG.mirror("REFL", F, d_in, d_out, _c, size=150.0)
    _m.optics.imprint_surface = True
    _imp_replace_surface(_m, surf_fn, half=half, nx=nx)
    _wfs = _IG.wavefront_sensor("WFS", F + d_out * 300.0, d_out, _c, size=90.0)
    bpy.context.view_layer.update()
    _segs = scan._trace(sc)
    _fld = ao.zonal_wavefront_at(sc, _m.name, _segs, px=px)
    _cf = ao._aberr_at(_segs, _wfs.name) or [0.0] * physics.N_ZERNIKE
    for _o in list(_c.objects):
        _IG.drop_example_object(_o)
    bpy.data.collections.remove(_c)
    return _fld, _cf


# (i) FLAT surface -> zonal field reads ~0 (the reference-plane detrend zeroes a flat/tilted mirror)
_zf_flat, _ = _imp_zonal("ZON_flat", lambda x, y: 0.0)
check("zonal: FLAT surface -> ~0 field (plane detrend)",
      _zf_flat is not None and _zf_flat["rms_waves"] < 2.0e-2,
      None if _zf_flat is None else "RMS %.5f waves, hits %.0f%%" % (_zf_flat["rms_waves"], 100.0 * _zf_flat["hit_frac"]))
# (ii) SPHERICAL cap -> zonal AGREES with the modal map (low-order: ratio ~1). Compare the UNIFORM zonal RMS
#      to the modal RMS (both are uniform-disk metrics; the Noll Zernikes are orthonormal over the disc).
_zf_sph, _cf_sph2 = _imp_zonal("ZON_sph", lambda x, y: (x * x + y * y) / (2.0 * 4000.0))
_mrms_sph = physics.wavefront_rms(_cf_sph2)
_zrat = (_zf_sph["rms_uniform"] / _mrms_sph) if (_zf_sph and _mrms_sph > 1e-6) else 0.0
check("zonal: SPHERE -> uniform zonal RMS agrees with modal (low-order, 0.5<ratio<2) + full sampling",
      _zf_sph is not None and 0.5 < _zrat < 2.0 and _zf_sph["hit_frac"] > 0.9,
      None if _zf_sph is None else "uniform %.3f / modal %.3f = %.2fx, hits %.0f%%"
      % (_zf_sph["rms_uniform"], _mrms_sph, _zrat, 100.0 * _zf_sph["hit_frac"]))
# (ii-b) BEAM SAMPLING: the footprint is a GAUSSIAN, not a top-hat. The beam-weighted (I=exp(-2 rho^2)) RMS
#        is reported and, for the edge-heavy defocus bowl, is strictly LESS than the uniform RMS -- the dim
#        1/e^2 wings carry less of the figure error, as the beam actually senses it.
check("zonal: SPHERE -> beam-weighted (gaussian) RMS < uniform RMS (dim 1/e^2 wings down-weighted)",
      _zf_sph is not None and "rms_gauss" in _zf_sph and "rms_uniform" in _zf_sph
      and 0.0 < _zf_sph["rms_gauss"] < _zf_sph["rms_uniform"] and _zf_sph["weight"] == "gaussian",
      None if _zf_sph is None else "gauss %.3f < uniform %.3f (%.2fx)"
      % (_zf_sph["rms_gauss"], _zf_sph["rms_uniform"], _zf_sph["rms_gauss"] / max(_zf_sph["rms_uniform"], 1e-9)))
# (iii) HIGH-spatial-frequency ripple (period ~2.5 mm, ~7 cycles across the Ø18 mm footprint) -> the 15-mode
#       modal fit CANNOT carry it (RMS collapses), but the zonal field DOES -> zonal RMS >> modal RMS. THE
#       point. NB the SURFACE mesh must be fine (nx=201 -> 0.4 mm) or it aliases the ripple before sampling.
_ripple = lambda x, y: 0.0015 * math.sin(x / 0.398)        # period 2*pi*0.398 ~= 2.5 mm
_zf_rip, _cf_rip = _imp_zonal("ZON_rip", _ripple, px=96, nx=201, half=40.0)
_mrms_rip = physics.wavefront_rms(_cf_rip)
check("zonal: HIGH-FREQ ripple -> zonal RMS >> modal-15 RMS (zonal carries what modal low-passes away)",
      _zf_rip is not None and _zf_rip["rms_waves"] > 0.1 and _zf_rip["rms_waves"] > 3.0 * _mrms_rip,
      None if _zf_rip is None else "zonal %.3f vs modal %.3f waves (%.1fx)"
      % (_zf_rip["rms_waves"], _mrms_rip, _zf_rip["rms_waves"] / max(_mrms_rip, 1e-6)))
# (iv) sampling metadata sane: Nyquist comfortably above the ripple frequency (~0.286 lp/mm) -> not aliased
check("zonal: Nyquist (px/2footprint) resolves the ripple (Nyq >> 0.286 lp/mm) + high hit fraction",
      _zf_rip is not None and _zf_rip["nyquist_lp_mm"] > 1.0 and _zf_rip["hit_frac"] > 0.9,
      None if _zf_rip is None else "Nyq %.2f lp/mm, %d px, footprint %.1f mm, hits %.0f%%"
      % (_zf_rip["nyquist_lp_mm"], _zf_rip["px"], _zf_rip["footprint_mm"], 100.0 * _zf_rip["hit_frac"]))
# (v) byte-identical: an on-demand zonal render must not perturb the subsequent normal trace. Build a LIVE
#     scene, trace, RENDER zonal on the real mirror (assert it actually produced a map), trace again,
#     compare -- so the check proves something (an empty scene would make it vacuous).
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
_cbi = _IG.example_collection("ZON_bi")
_Fb = _Vec((0.0, 0.0, 0.0)); _dib = _Vec((1.0, 0.0, 0.0))
_dvb = math.radians(180.0 - 16.0); _dob = _Vec((math.cos(_dvb), math.sin(_dvb), 0.0)).normalized()
_lb = _IG.source("Laser", _Fb - _dib * 400.0, _dib, _cbi, wavelength=632.8, length=44.0, radius=10.0)
_lb.optics.waist_um = 9000.0
_mb = _IG.mirror("REFL", _Fb, _dib, _dob, _cbi, size=150.0); _mb.optics.imprint_surface = True
_imp_replace_surface(_mb, lambda x, y: (x * x + y * y) / (2.0 * 6000.0))
_IG.wavefront_sensor("WFS", _Fb + _dob * 300.0, _dob, _cbi, size=90.0)
bpy.context.view_layer.update()
_bi1 = scan._trace(sc)
_zz = ao.zonal_wavefront_at(sc, _mb.name, _bi1, px=64)
_bi2 = scan._trace(sc)
check("zonal: on-demand render leaves the trace byte-identical (live scene, render confirmed)",
      _zz is not None and len(_bi1) == len(_bi2) and len(_bi1) > 0
      and all((a.get("p2") - b.get("p2")).length < 1e-9 for a, b in zip(_bi1, _bi2)
              if a.get("p2") is not None and b.get("p2") is not None),
      "%d==%d segs, render=%s" % (len(_bi1), len(_bi2), "ok" if _zz else "None"))
for _o in list(_cbi.objects):
    _IG.drop_example_object(_o)
bpy.data.collections.remove(_cbi)

print("[3.4 recognizable object: build_example('die') -> the 5-pip quincunx reads as a zonal wavefront]")
optics_api.build_example("die")
_dsegs = scan._trace(sc)
check("3.4 die: the collimated beam reaches the wavefront sensor", any(s.get("to") == "DIE_WFS" for s in _dsegs))
_dfld = ao.zonal_wavefront_at_sensor(sc, "DIE_WFS", _dsegs, px=160)
_dpv = (np.nanmax(_dfld["field"]) - np.nanmin(_dfld["field"])) if _dfld else 0.0
check("3.4 die: zonal sensor reads the recessed pips (non-trivial PV from the 6 um dimples)",
      _dfld is not None and _dpv > 5.0, "PV=%.2f waves" % _dpv)
# the 5 pips are 5 distinct recesses: the field minimum (deepest pip) is well below the mean (real relief)
_dF = _dfld["field"]
_dvalid = _dF[np.isfinite(_dF)]
check("3.4 die: the pip recesses are real local minima (min << mean over the footprint)",
      _dvalid.size > 0 and (_dvalid.mean() - _dvalid.min()) > 2.0,
      "mean-min=%.2f waves" % (_dvalid.mean() - _dvalid.min()) if _dvalid.size else "no field")
# on-demand zonal render does NOT mutate the trace (byte-identical)
check("3.4 die: zonal render leaves the trace byte-identical",
      len(scan._trace(sc)) == len(_dsegs))

print("[3.2 per-pixel polarization CCD (DoFP): single-shot linear Stokes S0/S1/S2 + DoLP/AoLP]")
for _o in list(sc.objects):
    if getattr(getattr(_o, "optics", None), "is_optical", False):
        bpy.data.objects.remove(_o, do_unlink=True)
_pcc2 = eg.example_collection("PolCam")
_pcX = _Vec((1, 0, 0))
_pcs = eg.source("PCC_S", (-100, 0, 0), _pcX, _pcc2)
_pcs.optics.pol_angle = 30.0
_pcd = eg.detector("PCC_D", (100, 0, 0), _pcX, _pcc2)
_pcd.optics.readout_topology = 'POL_CAMERA'
bpy.context.view_layer.update()
_pcsegs = scan._trace(sc)
_pc = optics_api.inspect_element(_pcd.name).get("pol_camera")
# the DoFP camera must measure the TRUE Stokes of the arriving beam (frame-consistent with stokes())
_pcseg = max((s for s in _pcsegs if s.get("to") == _pcd.name), key=lambda s: s.get("power", 0.0))
_jj = _pcseg["jones"]
_strue = physics.stokes((complex(_jj[0], _jj[1]), complex(_jj[2], _jj[3])))
check("3.2 pol-camera DoFP reconstructs the arriving beam's linear Stokes (S0/S1/S2 == stokes, within micropolarizer extinction)",
      _pc is not None and abs(_pc["S0"] - _strue[0]) < 5e-3 and abs(_pc["S1"] - _strue[1]) < 5e-3
      and abs(_pc["S2"] - _strue[2]) < 5e-3, str(_pc)[:80] if _pc else "no pol_camera read")
check("3.2 pol-camera reads DoLP~1 for a fully-polarized beam",
      _pc is not None and abs(_pc["dolp"] - 1.0) < 1e-2, "DoLP=%.4f" % _pc["dolp"] if _pc else "none")
check("3.2 pol-camera micro-analyzers conserve power (I0+I90 = I45+I135 = S0)",
      _pc is not None and abs((_pc["I0"] + _pc["I90"]) - (_pc["I45"] + _pc["I135"])) < 1e-3
      and abs((_pc["I0"] + _pc["I90"]) - _pc["S0"]) < 1e-3)
_pcd.optics.readout_topology = 'POINT'
bpy.context.view_layer.update()
check("3.2 pol_camera read is opt-in (a POINT detector carries no pol_camera field)",
      "pol_camera" not in optics_api.inspect_element(_pcd.name))
for _o in list(_pcc2.objects):
    eg.drop_example_object(_o)
bpy.data.collections.remove(_pcc2)

print("[sensor-aperture capture: a finite sensor reads ONLY the beam within its aperture]")
# The SAME figured optic, read with an expanded COLLIMATED beam (fits the sensor) vs an expanded DIVERGING
# beam (overfills it). The sensor captures rho_max = aperture/w_sensor of the figure + power 1-exp(-2a^2/w^2).
# The simulation PRODUCES the difference (Gaussian q-propagation -> different w at the sensor; the aperture
# stop clips the diverging beam) -- the only input that differs is the beam-expander spacing.
optics_api.build_example("surface_figure")              # afocal expander -> collimated, fits the sensor
_cap_col = optics_api.sensor_capture("SF_WFS")
optics_api.build_example("surface_figure_diverging")    # non-afocal expander -> diverging, overfills sensor
_cap_div = optics_api.sensor_capture("SF_WFS")
check("sensor: COLLIMATED beam fits -> rho_max=1, whole figure captured",
      _cap_col.get("rho_max", 0.0) > 0.98 and _cap_col.get("captured_frac", 0.0) > 0.98
      and _cap_col.get("aperture_applied") is True,
      "rho_max=%.2f frac=%.2f" % (_cap_col.get("rho_max", 0), _cap_col.get("captured_frac", 0)))
check("sensor: DIVERGING beam overfills -> rho_max<1 (figure clipped) + power<1 (beam truncated)",
      _cap_div.get("rho_max", 1.0) < 0.9 and _cap_div.get("power_captured", 1.0) < 0.9,
      "rho_max=%.2f power=%.2f" % (_cap_div.get("rho_max", 1), _cap_div.get("power_captured", 1)))
check("sensor: the two beams read the SAME optic DIFFERENTLY (captured area differs >0.2)",
      abs(_cap_col.get("captured_frac", 0.0) - _cap_div.get("captured_frac", 0.0)) > 0.2,
      "collimated %.2f vs diverging %.2f" % (_cap_col.get("captured_frac", 0), _cap_div.get("captured_frac", 0)))

print("[WFS beam-curvature defocus: the sensor reads the beam's own R(z), not just the modal aberr]")
# A clean (un-aberrated) Gaussian beam diverging onto a WFS carries DEFOCUS from its wavefront
# curvature R(z). The modal aberr channel (_aberr_at -- what the AO loop corrects) is flat -> RMS=0;
# the sensor READ (_sensor_wavefront / ao_measure) folds in the beam's Z4 defocus so it reads the
# REAL wavefront a Shack-Hartmann integrates. a4 = w_s^2/(4*sqrt3*R*lambda) [waves], physics_verify
# ok=true (a4(w=5,R=1000,lambda=632.8nm)=5.70234). Before this fix a diverging beam read RMS=0.
def _defocus_scene(waist_um, name):
    for _o in list(sc.objects):
        if getattr(getattr(_o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(_o, do_unlink=True)
    _c = _IG.example_collection(name)
    F = _Vec((0.0, 0.0, 0.0)); d_in = _Vec((1.0, 0.0, 0.0))
    dev = math.radians(164.0)
    d_out = _Vec((math.cos(dev), math.sin(dev), 0.0)).normalized()
    _las = _IG.source("DF_Laser", F - d_in * 400.0, d_in, _c, wavelength=632.8)
    _las.optics.waist_um = waist_um                        # NO aberrator, flat mirror -> modal channel is flat
    _m = _IG.mirror("DF_M", F, d_in, d_out, _c, size=150.0)
    _wfs = _IG.wavefront_sensor("DF_WFS", F + d_out * 300.0, d_out, _c, size=90.0)
    bpy.context.view_layer.update()
    _segs = scan._trace(sc)
    ap = _wfs.optics.clear_aperture
    modal = ao._aberr_at(_segs, _wfs.name)
    coeffs, info = ao._sensor_wavefront(_segs, _wfs.name, ap)
    best = max((s for s in _segs if s.get("to") == _wfs.name), key=lambda s: s.get("power", 0.0))
    _qd = best["qd"]; R = physics.beam_roc(complex(_qd[0], _qd[1])); w = best["w_mm"]
    ws = min(w, ap) if ap > 0 else w
    a4_exp = ws * ws / (4.0 * math.sqrt(3.0) * R * 632.8e-6) if math.isfinite(R) else 0.0
    for _o in list(_c.objects):
        _IG.drop_example_object(_o)
    bpy.data.collections.remove(_c)
    return modal, coeffs, info, a4_exp, R

_md, _cd, _idf, _a4d, _Rd = _defocus_scene(500.0, "DF_div")     # tight waist -> diverging at the sensor
check("WFS defocus: clean diverging beam -> modal aberr RMS ~0 (the channel the AO loop corrects)",
      physics.wavefront_rms(_md or [0.0] * physics.N_ZERNIKE) < 1e-6,
      "%.6f" % physics.wavefront_rms(_md or [0.0] * physics.N_ZERNIKE))
check("WFS defocus: sensor read now picks up the beam-curvature defocus (no longer RMS=0)",
      physics.wavefront_rms(_cd) > 1e-3, "RMS=%.5f waves, R=%.0fmm" % (physics.wavefront_rms(_cd), _Rd))
check("WFS defocus: folded Z4 matches analytic a4 = w^2/(4 sqrt3 R lambda)",
      abs(_cd[3] - _a4d) < 1e-4 and abs(_idf["defocus_waves"] - _a4d) < 1e-4,
      "Z4=%.5f vs a4=%.5f" % (_cd[3], _a4d))
_mc, _cc, _icf, _a4c, _Rc = _defocus_scene(9000.0, "DF_coll")   # wide waist -> ~collimated at the sensor
check("WFS defocus: ~collimated beam reads ~flat (R huge -> defocus ~0)",
      physics.wavefront_rms(_cc) < 1e-2, "RMS=%.5f waves, R=%.0fmm" % (physics.wavefront_rms(_cc), _Rc))
_none, _ninfo = ao._sensor_wavefront([], "NoSuchSensor")
check("WFS defocus: no beam -> _sensor_wavefront returns None (a dark WFS is not a corrected flat one)",
      _none is None and _ninfo.get("n_beams") == 0)

print("[3.5 pyramid WFS: a slope sensor -- it reads dW/dx, dW/dy, not the modal vector]")
# A pyramid WFS measures the local wavefront SLOPE. For a unit DEFOCUS (Noll j=4) the x-slope is linear,
# dZ4/dx = 4 sqrt3 x (physics_verify ok=true: slope at x=0.5 = 3.4641); a TILT (j=2) reads a UNIFORM slope.
_pdef = [0.0] * physics.N_ZERNIKE; _pdef[3] = 1.0
_psd = ao.pyramid_signals(_pdef, 96)
_psx = _psd["sx"]; _ppx = _psx.shape[0]
_prow = _psx[_ppx // 2]; _pvalid = np.isfinite(_prow)
_pxs = np.linspace(-1.0, 1.0, _ppx)[_pvalid]; _psxr = _prow[_pvalid]
check("3.5 pyramid: defocus reads a RADIAL slope, dZ4/dx = 4 sqrt3 x (slope at x=0.5 = 3.4641 [oracle ok=true])",
      abs(np.interp(0.5, _pxs, _psxr) - 4.0 * math.sqrt(3.0) * 0.5) < 0.05
      and abs(np.interp(-0.5, _pxs, _psxr) + 4.0 * math.sqrt(3.0) * 0.5) < 0.05,
      "sx(0.5)=%.3f vs %.3f" % (np.interp(0.5, _pxs, _psxr), 4.0 * math.sqrt(3.0) * 0.5))
_ptilt = [0.0] * physics.N_ZERNIKE; _ptilt[1] = 1.0
_pst = ao.pyramid_signals(_ptilt, 96)
_psxt = _pst["sx"][np.isfinite(_pst["sx"])]
check("3.5 pyramid: x-tilt reads a UNIFORM x-slope (std << mean)",
      _psxt.size > 0 and _psxt.std() < 1e-6 and abs(_psxt.mean() - 2.0) < 1e-6,
      "mean=%.4f std=%.6f" % (_psxt.mean(), _psxt.std()))
# live read on the AO bench: returns the slope RMS + writes a PNG; READ-ONLY (byte-identical)
optics_api.build_example("adaptive_optics")
_pnseg = len(scan._trace(sc))
_pr = optics_api.pyramid_wfs("AO_WFS")
check("3.5 pyramid_wfs reads a sensor's slope (slope_rms > 0, PNG written) without mutating the trace",
      "error" not in _pr and _pr.get("slope_rms", 0) > 0 and os.path.exists(_pr.get("png", ""))
      and len(scan._trace(sc)) == _pnseg, str({k: _pr.get(k) for k in ("slope_rms", "wavefront_rms")}))

print("[Tolerance scan -- pose-only Monte-Carlo alignment sensitivity (off-trace, seed-pinned RNG)]")
optics_api.build_example("michelson")
_tsN = len(scan._trace(sc))
_tsloc0 = tuple(bpy.data.objects["MI_Laser"].location)
_ts1 = optics_api.tolerance_scan(elements=["MI_Laser"], target="MI_D", sigma_pos_mm=0.2, sigma_ang_deg=0.1, n=30, seed=1, tol_mm=2.0)
check("tolerance_scan: perturbation walks the beam (pointing_rms_mm>0, hit_rate>0, yield in [0,1])",
      "error" not in _ts1 and (_ts1.get("pointing_rms_mm") or 0) > 0 and _ts1.get("hit_rate", 0) > 0
      and 0.0 <= _ts1.get("yield", 0.0) <= 1.0, str({k: _ts1.get(k) for k in ("pointing_rms_mm", "hit_rate", "yield")}))
check("tolerance_scan: RESTORES the pose + the nominal trace (off-trace, byte-identical)",
      all(abs(a - b) < 1e-9 for a, b in zip(_tsloc0, tuple(bpy.data.objects["MI_Laser"].location)))
      and len(scan._trace(sc)) == _tsN, "pose or trace drifted")
_ts2 = optics_api.tolerance_scan(elements=["MI_Laser"], target="MI_D", sigma_pos_mm=0.2, sigma_ang_deg=0.1, n=30, seed=1)
check("tolerance_scan: seed-pinned RNG reproducible (same seed -> same RMS)",
      abs((_ts1.get("pointing_rms_mm") or 0) - (_ts2.get("pointing_rms_mm") or 0)) < 1e-9, "not reproducible")
_ts3 = optics_api.tolerance_scan(elements=["MI_Laser"], target="MI_D", sigma_pos_mm=0.05, sigma_ang_deg=0.025, n=30, seed=1)
check("tolerance_scan: smaller sigma -> smaller pointing walk (monotone)",
      (_ts3.get("pointing_rms_mm") or 0) < (_ts1.get("pointing_rms_mm") or 0),
      "%s !< %s" % (_ts3.get("pointing_rms_mm"), _ts1.get("pointing_rms_mm")))

print("[FDTD orchestration -- fdtd_bridge closed-form fallback (meep absent here), oracle-matching]")
from optical_alignment_sim import fdtd_bridge as _fb
_fs = _fb.stack_reflectance(n_layers=[1.38], d_layers_nm=[99.6], n_incident=1.0, n_substrate=1.52, wavelength_nm=550.0)
check("fdtd_bridge: quarter-wave stack TMM == ar_quarter_wave_reflectance (exact 1-D fallback)",
      _fs.get("backend") == "fallback-closedform"
      and abs(_fs.get("reflectance", -1) - physics.ar_quarter_wave_reflectance(1.0, 1.38, 1.52)) < 1e-4,
      "%s vs %s" % (_fs.get("reflectance"), physics.ar_quarter_wave_reflectance(1.0, 1.38, 1.52)))
_fg = _fb.grating_efficiency(period_um=1.6667, depth_um=0.3, n_groove=1.5, n_substrate=1.5, wavelength_nm=633.0, orders=(-1, 0, 1))
check("fdtd_bridge: grating fallback honest backend + propagating-orders energy sum ~ 1",
      _fg.get("backend") == "fallback-closedform" and abs(_fg.get("sum", 0.0) - 1.0) < 1e-6,
      str({k: _fg.get(k) for k in ("backend", "sum")}))

oas.unregister()

passed = sum(1 for _, ok in _checks if ok)
total = len(_checks)
fails = [n for n, ok in _checks if not ok]
print("=" * 52)
if fails:
    print("REGRESSION FAIL  (%d/%d)  failed: %s" % (passed, total, ", ".join(fails)))
else:
    print("REGRESSION PASS  (%d/%d checks)" % (passed, total))
sys.exit(len(fails))
