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
from optical_alignment_sim import scan, alignment, ao, physics, render, handlers, operators, elements_generic, mounts, bridge, tracer

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
for kind in ("mach_zehnder", "michelson", "hong_ou_mandel", "bell", "adaptive_optics", "newton_rings"):
    r = optics_api.build_example(kind)
    check("build %s" % kind, isinstance(r, dict) and r.get("segments", 0) >= 1, str(r))

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
# Sellmeier stays physical in the deep UV (was returning 1.0 or n~9 between poles)
check("sellmeier UV index stays physical", all(1.0 <= physics.sellmeier_n(w) <= 4.0 for w in (60.0, 78.0, 100.0, 142.0)))
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
check("beamsplitter gets a cube platform (not a hoop)", _has("CubeBase"))
check("sources/detectors get a bracket, not an optic ring", _has("Bracket"))
# the beamsplitter must NOT be wrapped by a torus Mount ring (the old horizontal-hoop bug)
_bs = next((o for o in sc.objects if getattr(o.optics, "is_optical", False) and o.optics.element_type == 'BEAMSPLITTER'), None)
if _bs is not None:
    _bi = [o.name for o in sc.objects if getattr(o.optics, "is_optical", False) and o.optics.element_type not in ('NONE',)].index(_bs.name)
    check("no Mount ring on the beamsplitter", not _has("Mount_%02d" % _bi), _bs.name)
optomech.strip(sc)

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
