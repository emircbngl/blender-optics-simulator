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
from optical_alignment_sim import scan, alignment, ao, physics, render, handlers, operators, elements_generic, mounts, bridge

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
