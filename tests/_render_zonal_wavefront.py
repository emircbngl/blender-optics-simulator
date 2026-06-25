"""DUMP the data for the ZONAL-vs-MODAL surface-figure comparison figure.

Two reflective scenes, each read two ways at the SAME px grid:
  (1) KNIGHT      -- the real Staunton-knight OBJ as the optical surface (high-spatial-frequency relief);
  (2) REAL OPTIC  -- a gently figured mirror: a little defocus + a ~3 mm mid-spatial-frequency polishing
                     ripple (the HONEST use-case -- a real optic whose ripple the 15-mode WFS smooths away).

For each, the MODAL map = the 15 Noll Zernikes re-summed (ao.wavefront_image's field; a low-pass) and the
ZONAL map = tracer.surface_imprint_field's RAW dense field. Both are dumped (W in waves, NaN outside the
pupil) to /tmp/zonal/*.npy + meta.json; the labelled figure is drawn by tests/_plot_zonal_wavefront.py
(matplotlib, which is not in Blender's Python).

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_zonal_wavefront.py
"""
import os
import sys
import math
import json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import bmesh
import numpy as np
from mathutils import Vector

OUT = "/tmp/zonal"
os.makedirs(OUT, exist_ok=True)
KNIGHT_OBJ = "/tmp/knight_wf/knight_bnolin.obj"

import optical_alignment_sim as addon
try:
    addon.register()
except Exception as e:
    print("register warn:", e)
from optical_alignment_sim import elements_generic as G, ao, physics, scan, tracer

PX = 256


def _clean():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _modal_field(coeffs, px=PX):
    """15-mode modal reconstruction W(x,y) in waves on a px grid, NaN outside the unit disc (the LOW-PASS
    map the WFS publishes). Uses ao's cached Zernike basis so it matches wavefront_image exactly."""
    mask, basis = ao._zern_basis(px)
    W = np.zeros((px, px))
    for j, c in enumerate(coeffs, start=1):
        if j in basis and abs(c) > 1e-12:
            W += c * basis[j]
    return np.where(mask, W, np.nan)


def _import_knight(path, height_mm=120.0):
    if not os.path.exists(path):
        return None
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.obj_import(filepath=path)
    except Exception:
        try:
            bpy.ops.import_scene.obj(filepath=path)
        except Exception:
            return None
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not new:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for o in new:
        o.select_set(True)
    bpy.context.view_layer.objects.active = new[0]
    if len(new) > 1:
        bpy.ops.object.join()
    kn = bpy.context.active_object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    me = kn.data
    zs = [v.co.z for v in me.vertices]
    h0 = (max(zs) - min(zs)) or 1.0
    s = height_mm / h0
    for v in me.vertices:
        v.co *= s
    zs = [v.co.z for v in me.vertices]; xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    cx = (min(xs) + max(xs)) * 0.5; cy = (min(ys) + max(ys)) * 0.5; cz = min(zs)
    for v in me.vertices:
        v.co.x -= cx; v.co.y -= cy; v.co.z -= cz
    me.update()
    return kn


def _grid_mesh(surf_fn, half, nx, name):
    b = bmesh.new()
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
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    me = bpy.data.meshes.new(name); b.to_mesh(me); b.free()
    return me


def _read_case(mesh, aoi_deg, waist_um, expander):
    """Build laser (-> optional expander) -> reflector(mesh) -> WFS; return (modal_field, zonal_dict)."""
    _clean()
    scene = bpy.context.scene
    coll = G.example_collection("ZonalCase")
    F = Vector((0.0, 0.0, 0.0)); d_in = Vector((1.0, 0.0, 0.0))
    dev = math.radians(180.0 - 2.0 * aoi_deg)
    d_out = Vector((math.cos(dev), math.sin(dev), 0.0)).normalized()
    las = G.source("Laser", F - d_in * 600.0, d_in, coll, wavelength=632.8, length=44.0, radius=6.0)
    las.optics.waist_um = waist_um
    if expander:
        G.lens("BE_div", F - d_in * 475.0, d_in, coll, focal=-25.0, radius=9.0, lens_type='AUTO')
        G.lens("BE_conv", F - d_in * 300.0, d_in, coll, focal=200.0, radius=24.0, lens_type='AUTO')
    refl = G.mirror("REFL", F, d_in, d_out, coll, size=220.0, mirror_curve='FLAT')
    old = refl.data
    refl.data = mesh
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    refl.optics.imprint_surface = True
    refl.optics.clear_aperture = 130.0
    G.wavefront_sensor("WFS", F + d_out * 300.0, d_out, coll, size=70.0)
    bpy.context.view_layer.update()
    segs = scan._trace(scene)
    tracer.cached_segments = segs
    coeffs = ao._aberr_at(segs, "WFS") or [0.0] * physics.N_ZERNIKE
    fld = ao.zonal_wavefront_at(scene, refl.name, segs, px=PX)
    return _modal_field(coeffs), fld, physics.wavefront_rms(coeffs)


def main():
    meta = {}

    # (1) the real knight -- high-spatial-frequency relief
    kn = _import_knight(KNIGHT_OBJ, height_mm=120.0)
    if kn is not None:
        kmesh = kn.data.copy()
        bpy.data.objects.remove(kn, do_unlink=True)
        m_modal, m_zonal, m_mrms = _read_case(kmesh, aoi_deg=8.0, waist_um=2500.0, expander=True)
        np.save(os.path.join(OUT, "knight_modal.npy"), m_modal)
        np.save(os.path.join(OUT, "knight_zonal.npy"), m_zonal["field"])
        meta["knight"] = {"modal_rms": m_mrms, "zonal_rms": m_zonal["rms_waves"],
                          "zonal_pv": m_zonal["pv_waves"], "footprint_mm": m_zonal["footprint_mm"],
                          "nyquist_lp_mm": m_zonal["nyquist_lp_mm"], "hit_frac": m_zonal["hit_frac"],
                          "px": m_zonal["px"], "source": "real Staunton knight OBJ"}
        print("KNIGHT modal RMS=%.3f  zonal RMS=%.1f waves" % (m_mrms, m_zonal["rms_waves"]))

    # (2) a real optic, MSF-dominant: a faint low-order residual (astigmatism) the 15-mode WFS happily
    #     reports + a DOMINANT mid-spatial-frequency polishing ripple (~2 mm quasi-periodic tool marks)
    #     that 15 Zernikes CANNOT represent. The modal map shows only the smooth astigmatism ("looks fine");
    #     the zonal sensor render reveals the MSF ripple the modal readout is blind to. lambda-scale figure.
    def real_optic(x, y):
        astig = 0.00040 * (x * x - y * y) / 90.0
        msf = (0.00110 * math.sin(x / 0.34) * math.cos(y / 0.40)        # ~2.1 x 2.5 mm cross-hatch
               + 0.00070 * math.sin((x + y) / 0.30))                    # ~1.9 mm diagonal tool marks
        return astig + msf
    omesh = _grid_mesh(real_optic, half=40.0, nx=281, name="RealOpticSurf")
    o_modal, o_zonal, o_mrms = _read_case(omesh, aoi_deg=8.0, waist_um=9000.0, expander=False)
    np.save(os.path.join(OUT, "optic_modal.npy"), o_modal)
    np.save(os.path.join(OUT, "optic_zonal.npy"), o_zonal["field"])
    meta["optic"] = {"modal_rms": o_mrms, "zonal_rms": o_zonal["rms_waves"],
                     "zonal_pv": o_zonal["pv_waves"], "footprint_mm": o_zonal["footprint_mm"],
                     "nyquist_lp_mm": o_zonal["nyquist_lp_mm"], "hit_frac": o_zonal["hit_frac"],
                     "px": o_zonal["px"], "source": "figured mirror: faint astigmatism + ~2 mm MSF ripple"}
    print("OPTIC  modal RMS=%.3f  zonal RMS=%.3f waves" % (o_mrms, o_zonal["rms_waves"]))

    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=2)
    print("DUMPED", OUT)


if __name__ == "__main__":
    main()
