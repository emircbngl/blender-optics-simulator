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
from optical_alignment_sim import scan, alignment, ao, physics, render

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
check("MZ complementary", (d0 + d1) > 0.9 and min(d0, d1) < 0.2, "D0=%.3f D1=%.3f" % (d0, d1))

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
