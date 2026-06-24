"""DEMO: surface-figure -> wavefront imprint, the chess-knight reflector.

Laser -> 4 cm beam expander -> chess-knight REFLECTOR (its ACTUAL MESH is the optical surface,
imprint_surface=True) @ near-normal AOI -> wavefront sensor 30 cm later. The plugin's tracer samples
the knight mesh over the Gaussian footprint and stamps its surface figure onto the reflected wavefront,
so the WFS reads a NON-FLAT map showing the knight's surface (vs the original flat-disc demo, which read
RMS ~0 off a planar stand-in reflector).

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_demo_surface_imprint.py

Writes:  /tmp/knight_wf/wavefront_map_fixed.png   (the plugin's false-colour WFS map, now structured)
         docs/img/surface-imprint.png             (the doc figure)
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
from mathutils import Vector

OUT = "/tmp/knight_wf"
os.makedirs(OUT, exist_ok=True)
KNIGHT_OBJ = os.path.join(OUT, "knight_bnolin.obj")           # real Staunton knight (CC); falls back if absent

import optical_alignment_sim as addon
try:
    addon.register()
except Exception as e:
    print("register warn:", e)
import optics_api
from optical_alignment_sim import elements_generic as G, ao, physics, scan, tracer


def _clean():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _import_knight_mesh(path, height_mm=170.0):
    """Import the Staunton-knight OBJ, scale to height_mm, recentre (base->z=0, XY centred), join to one
    object, and RETURN the joined object (we steal its mesh for the optical reflector). None if absent."""
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
    kn.name = "ChessKnightRaw"
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


def _procedural_knight_surface(half=80.0, nx=121):
    """Fallback when the OBJ is absent: a knight-SILHOUETTE relief surface z=f(x,y) -- a few sculpted
    Gaussian ridges (muzzle, mane, jaw) so the WFS still reads a recognisably irregular, multi-mode figure.
    Returns a mesh datablock in the LOCAL frame (local +Z = the coated front; +Z relief = toward the beam)."""
    def f(x, y):
        z = 0.0
        z += 7.0 * math.exp(-(((x - 8) / 30.0) ** 2 + ((y + 5) / 42.0) ** 2))      # the head/jaw mass
        z += 4.0 * math.exp(-(((x - 30) / 16.0) ** 2 + ((y - 6) / 14.0) ** 2))     # the muzzle bump
        z -= 3.0 * math.exp(-(((x + 18) / 18.0) ** 2 + ((y - 18) / 30.0) ** 2))    # the mane recess
        z += 2.4 * math.exp(-(((x - 2) / 10.0) ** 2 + ((y + 30) / 16.0) ** 2))     # the throat
        z += 1.2 * math.sin(x / 22.0) * math.cos(y / 26.0)                          # surface ripple
        return z
    bm = bmesh.new()
    vv = [[None] * nx for _ in range(nx)]
    for iy in range(nx):
        for ix in range(nx):
            x = -half + 2.0 * half * ix / (nx - 1)
            y = -half + 2.0 * half * iy / (nx - 1)
            vv[iy][ix] = bm.verts.new((x, y, f(x, y)))
    bm.verts.ensure_lookup_table()
    for iy in range(nx - 1):
        for ix in range(nx - 1):
            bm.faces.new((vv[iy][ix], vv[iy][ix + 1], vv[iy + 1][ix + 1], vv[iy + 1][ix]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("KnightRelief")
    bm.to_mesh(me); bm.free()
    return me


def main():
    _clean()
    scene = bpy.context.scene
    coll = G.example_collection("KnightWavefront")

    # --- optical chain: laser -> Galilean expander -> knight reflector (near-normal) -> WFS ---
    F = Vector((0.0, 0.0, 0.0))
    d_in = Vector((1.0, 0.0, 0.0))
    aoi_deg = 8.0
    dev = math.radians(180.0 - 2.0 * aoi_deg)                 # mirror deviation = 180-2*AOI (near-normal)
    d_out = Vector((math.cos(dev), math.sin(dev), 0.0)).normalized()
    L2 = F - d_in * 300.0                                     # expander output, 30 cm before the knight
    L1 = F - d_in * 475.0
    LAS = F - d_in * 600.0
    SENS = F + d_out * 300.0                                  # 30 cm after the knight

    las = G.source("Laser", LAS, d_in, coll, wavelength=632.8, length=44.0, radius=6.0)
    las.optics.waist_um = 2500.0                             # x8 expander -> ~20 mm radius footprint
    G.lens("BE_div", L1, d_in, coll, focal=-25.0, radius=9.0, lens_type='AUTO')
    G.lens("BE_conv", L2, d_in, coll, focal=200.0, radius=24.0, lens_type='AUTO')

    # the knight is the REFLECTIVE element; steal a real knight mesh (or the procedural relief) as its
    # optical surface, scaled so the ~Ø40 mm footprint reads a rich patch of the figure.
    knight_obj = _import_knight_mesh(KNIGHT_OBJ, height_mm=120.0)
    if knight_obj is not None:
        knight_mesh = knight_obj.data.copy()                 # copy so the source object can be deleted
        bpy.data.objects.remove(knight_obj, do_unlink=True)
        src = "real Staunton knight OBJ"
    else:
        knight_mesh = _procedural_knight_surface()
        src = "procedural knight-relief surface (OBJ absent)"
    print("knight surface source:", src)

    knight = G.mirror("Knight", F, d_in, d_out, coll, size=200.0, mirror_curve='FLAT')
    old = knight.data
    knight.data = knight_mesh                                 # the knight mesh IS the optical surface
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    knight.optics.imprint_surface = True                     # <-- the feature: stamp the mesh figure
    knight.optics.clear_aperture = 110.0                     # let the wide footprint land on the mesh

    G.wavefront_sensor("WFS", SENS, d_out, coll, size=70.0)

    # --- trace + read the wavefront ---
    bpy.context.view_layer.update()
    segs = scan._trace(scene)
    tracer.cached_segments = segs
    coeffs = ao._aberr_at(segs, "WFS") or [0.0] * physics.N_ZERNIKE
    rms = physics.wavefront_rms(coeffs)
    wfs_w = next((s.get("w_mm") for s in segs if s.get("to") == "WFS"), 0.0)
    print("=== knight wavefront ===")
    print("  footprint radius at WFS  : %.2f mm" % (wfs_w or 0.0))
    print("  reconstructed RMS        : %.4f waves  (FLAT-disc demo read ~0)" % rms)
    print("  Zernike coeffs (waves)   :")
    for k in range(1, physics.N_ZERNIKE):
        if abs(coeffs[k]) > 1e-3:
            print("    %-10s = %+.4f" % (physics.ZERNIKE_NAMES.get(k + 1, "?"), coeffs[k]))
    json.dump({"rms": rms, "zernike": coeffs, "source": src, "wfs_w_mm": wfs_w},
              open(os.path.join(OUT, "sim_fixed.json"), "w"), indent=2)

    if rms <= 1e-3:
        print("WARN: wavefront is flat (RMS %.4f) -- the imprint did not populate; check the footprint/mesh" % rms)

    # --- save the plugin's false-colour WFS map (now structured, not a flat disc) ---
    import numpy as np
    vmax = max(0.5, rms * 1.4)
    img = ao.wavefront_image(coeffs, px=256, vmax=vmax)
    img = np.flipud(img)                                     # Blender pixels are bottom-up
    bi = bpy.data.images.new("wfmap_fixed", 256, 256, alpha=True)
    bi.pixels.foreach_set(img.astype('float32').ravel())
    fixed_path = os.path.join(OUT, "wavefront_map_fixed.png")
    bi.filepath_raw = fixed_path; bi.file_format = 'PNG'; bi.save()
    print("saved", fixed_path, "(256x256)  RMS=%.4f waves  vmax=%.3f" % (rms, vmax))

    # --- doc figure: a larger 512px false-colour map (matplotlib is not in Blender's Python, so render
    #     it straight from the plugin's wavefront_image -> a Blender image datablock; no extra deps). ---
    doc_path = os.path.join(REPO, "docs", "img", "surface-imprint.png")
    big = np.flipud(ao.wavefront_image(coeffs, px=512, vmax=vmax))
    bd = bpy.data.images.new("wfmap_doc", 512, 512, alpha=True)
    bd.pixels.foreach_set(big.astype('float32').ravel())
    bd.filepath_raw = doc_path; bd.file_format = 'PNG'; bd.save()
    print("saved", doc_path, "(512x512)")

    print("DONE")


if __name__ == "__main__":
    main()
