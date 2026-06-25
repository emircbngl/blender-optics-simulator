"""Dump the WFS reconstructed wavefront field for the beam-curvature-defocus fix demo.

A clean (un-aberrated) Gaussian beam diverging onto a wavefront sensor carries DEFOCUS from its own
wavefront curvature R(z). The modal aberr channel (what the AO loop corrects) is flat, so the OLD WFS
read reported RMS=0 -- physically wrong. The fixed read folds in the beam's Z4 defocus
(a4 = w^2/(4 sqrt3 R lambda), physics_verify ok=true), so the sensor reads the real wavefront a
Shack-Hartmann integrates. This dumps three fields to /tmp/wfsdf/*.npy for _plot_wfs_defocus.py:
  div_old  -- diverging beam, modal channel only (the bug: flat, RMS=0)
  div_new  -- diverging beam, sensor read (modal + beam defocus): a real defocus bowl
  coll_new -- collimated beam, sensor read: correctly ~flat (R huge -> a4 ~ 0)

Run: blender --background --factory-startup --python tests/_render_wfs_defocus.py
"""
import bpy, sys, os, math
import numpy as np
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import scan, ao, physics, elements_generic as IG

OUT = "/tmp/wfsdf"
os.makedirs(OUT, exist_ok=True)
sc = bpy.context.scene
PX = 192


def _field(coeffs):
    """W(x,y) in waves over the unit disk (NaN outside the pupil), as the monitor renders it."""
    W, mask = ao._modal_field(coeffs, PX)
    F = np.where(mask, W, np.nan)
    return F


def _bench(waist_um, name):
    for o in list(sc.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = IG.example_collection(name)
    F = Vector((0.0, 0.0, 0.0)); d_in = Vector((1.0, 0.0, 0.0))
    dev = math.radians(164.0)
    d_out = Vector((math.cos(dev), math.sin(dev), 0.0)).normalized()
    las = IG.source("DF_Laser", F - d_in * 400.0, d_in, c, wavelength=632.8)
    las.optics.waist_um = waist_um
    IG.mirror("DF_M", F, d_in, d_out, c, size=150.0)
    wfs = IG.wavefront_sensor("DF_WFS", F + d_out * 300.0, d_out, c, size=90.0)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    ap = wfs.optics.clear_aperture
    modal = ao._aberr_at(segs, wfs.name) or [0.0] * physics.N_ZERNIKE
    coeffs, info = ao._sensor_wavefront(segs, wfs.name, ap)
    return modal, coeffs, info


# Diverging beam: OLD (modal only) vs NEW (modal + beam defocus)
m_div, c_div, i_div = _bench(500.0, "WFSDF_div")
np.save(os.path.join(OUT, "div_old.npy"), _field(m_div))
np.save(os.path.join(OUT, "div_new.npy"), _field(c_div))
# Collimated beam: NEW read stays ~flat (correct)
m_col, c_col, i_col = _bench(9000.0, "WFSDF_coll")
np.save(os.path.join(OUT, "coll_new.npy"), _field(c_col))

meta = {
    "div_old_rms": float(physics.wavefront_rms(m_div)),
    "div_new_rms": float(physics.wavefront_rms(c_div)),
    "div_defocus": float(i_div["defocus_waves"]),
    "div_R": float(i_div["beam_roc_mm"]) if i_div["beam_roc_mm"] else float("inf"),
    "div_w": float(i_div["w_sensor_mm"]),
    "coll_new_rms": float(physics.wavefront_rms(c_col)),
    "coll_defocus": float(i_col["defocus_waves"]),
    "coll_R": float(i_col["beam_roc_mm"]) if i_col["beam_roc_mm"] else float("inf"),
}
import json
with open(os.path.join(OUT, "meta.json"), "w") as f:
    json.dump(meta, f, indent=2)
print("WFS-DEFOCUS dump:", json.dumps(meta, indent=2))
