"""Zonal wavefront of a recognisable OBJECT, AIMED CORRECTLY at its iconic face.

The earlier knight wavefront was unrecognisable because the piece's HEIGHT axis ended up along the beam
(the mesh's local +Z becomes the mirror normal), so the footprint sampled cross-sectional SLICES of the
base, not the side profile. Fix: pre-rotate each object so its ICONIC view faces the beam (local +Z):
  * chess KNIGHT (real GitHub model, Bnolin/3D-Chess-Game) -> turn the SIDE PROFILE toward the beam; the
    footprint's valid (non-miss) region then traces the horse silhouette + its side relief.
  * DIE (built to standard: a cube with recessed spherical pips, opposite faces summing to 7) -> turn the
    5-face toward the beam; the recessed pips read as depth dips -> the quincunx pattern.

Dumps W(x,y) (waves) + meta to /tmp/objwf/; the labelled figure is drawn by tests/_plot_object_wavefront.py.

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_object_wavefront.py
"""
import os, sys, math, json
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import bpy, bmesh, numpy as np
from mathutils import Vector

OUT = "/tmp/objwf"
os.makedirs(OUT, exist_ok=True)
KNIGHT = "/tmp/models/knight.obj"

import optical_alignment_sim as addon
try:
    addon.register()
except Exception as e:
    print("register warn:", e)
from optical_alignment_sim import elements_generic as G, ao, physics, scan, tracer

PX = 320


def _wipe():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m, do_unlink=True)


# ---------------------------------------------------------------- DIE (built to standard) ------------
_QUINCUNX = lambda a: [(0, 0), (-a, -a), (-a, a), (a, -a), (a, a)]   # the standard '5' face


def build_die(S=40.0, depth=0.32, pip_r=3.2, nx=121):
    """A die's 5-face as a RELIEF plate: a flat S x S face with 5 recessed circular dimples in the standard
    quincunx. A die's wavefront only ever images ONE face, so this is the physically-identical result for
    'imaging the 5-face' on reflection -- a flat reference with five depth dips -> the quincunx pattern.
    Built as a fine heightmap (no boolean), so it is robust + exactly flat away from the pips. Returns mesh."""
    a = S * 0.22
    pips = _QUINCUNX(a)

    def zf(x, y):
        z = 0.0
        for (px, py) in pips:
            z -= depth * math.exp(-((x - px) ** 2 + (y - py) ** 2) / (pip_r * pip_r))   # smooth recessed dimple
        return z
    b = bmesh.new()
    vv = [[None] * nx for _ in range(nx)]
    for iy in range(nx):
        for ix in range(nx):
            x = -0.5 * S + S * ix / (nx - 1)
            y = -0.5 * S + S * iy / (nx - 1)
            vv[iy][ix] = b.verts.new((x, y, zf(x, y)))
    b.verts.ensure_lookup_table()
    for iy in range(nx - 1):
        for ix in range(nx - 1):
            b.faces.new((vv[iy][ix], vv[iy][ix + 1], vv[iy + 1][ix + 1], vv[iy + 1][ix]))
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    me = bpy.data.meshes.new("die"); b.to_mesh(me); b.free()
    return me


# ---------------------------------------------------------------- KNIGHT (real GitHub OBJ) -----------
def load_knight(path, target_h=90.0, az_deg=90.0):
    """Import the real chess-knight OBJ and ORIENT it SIDE-ON to the beam: its iconic side profile -> the
    mesh local +Z (the face the beam images), its height -> local +Y. Auto-detects the head-protrusion
    (length) axis, then spins ``az_deg`` about the vertical so the horse's SIDE (head/mane/muzzle profile)
    faces the beam (az=90 is the recognisable view; az=0 is the front). Returns mesh data."""
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
    co = [v.co.copy() for v in me.vertices]
    zs = [c.z for c in co]
    z0, z1 = min(zs), max(zs)
    # head region = top 35% by height; the horizontal axis with the larger offset there is the LENGTH
    # (head-protrusion) axis; the other horizontal axis is the FACING (thin) axis -> turn it toward the beam.
    head = [c for c in co if c.z > z0 + 0.65 * (z1 - z0)]
    cx_all = sum(c.x for c in co) / len(co); cy_all = sum(c.y for c in co) / len(co)
    mx = abs(sum(c.x for c in head) / len(head) - cx_all)
    my = abs(sum(c.y for c in head) / len(head) - cy_all)
    facing_is_x = mx < my                                    # smaller head-offset axis = thin/facing axis
    s = target_h / ((z1 - z0) or 1.0)
    out = []
    for c in co:
        # height (orig Z) -> +Y ; length axis -> +X ; facing axis -> +Z (toward the beam)
        if facing_is_x:
            nx, ny, nz = c.y, c.z, c.x                       # facing = X
        else:
            nx, ny, nz = c.x, c.z, c.y                       # facing = Y
        out.append(Vector((nx * s, ny * s, nz * s)))
    # recentre: X-Y on the silhouette centroid, Z surface to ~0
    cx = sum(p.x for p in out) / len(out); cy = sum(p.y for p in out) / len(out); cz = sum(p.z for p in out) / len(out)
    th = math.radians(az_deg); ca, sa = math.cos(th), math.sin(th)
    for i, p in enumerate(out):
        x, y, z = p.x - cx, p.y - cy, p.z - cz
        me.vertices[i].co = Vector((x * ca + z * sa, y, -x * sa + z * ca))   # spin about +Y to face the side
    me.update()
    data = me.copy()
    bpy.data.objects.remove(kn, do_unlink=True)
    return data


def render_case(make_mesh, key, w_target_mm, aoi_deg=8.0):
    """Build laser -> reflector(mesh, imprint) -> WFS with a collimated beam whose footprint radius ~ w_target;
    return meta from the zonal sensor render. ``make_mesh`` is called AFTER the scene wipe (so the mesh it
    builds is not swept away). The field's valid region traces the object silhouette."""
    _wipe()
    mesh_data = make_mesh()
    if mesh_data is None:
        print("  %s: no mesh" % key)
        return None
    sc = bpy.context.scene
    c = G.example_collection("OBJ_" + key)
    F = Vector((0, 0, 0)); d_in = Vector((1, 0, 0))
    dev = math.radians(180.0 - 2.0 * aoi_deg)
    d_out = Vector((math.cos(dev), math.sin(dev), 0.0)).normalized()
    las = G.source("Laser", F - d_in * 500.0, d_in, c, wavelength=632.8, length=44.0, radius=8.0)
    las.optics.waist_um = w_target_mm * 1000.0               # collimated: footprint radius ~ waist (mm)
    refl = G.mirror("REFL", F, d_in, d_out, c, size=max(260.0, 4.0 * w_target_mm), mirror_curve='FLAT')
    old = refl.data; refl.data = mesh_data
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    refl.optics.imprint_surface = True
    refl.optics.clear_aperture = 3.0 * w_target_mm
    G.wavefront_sensor("WFS", F + d_out * 300.0, d_out, c, size=70.0)
    bpy.context.view_layer.update()
    segs = scan._trace(sc)
    tracer.cached_segments = segs
    fld = ao.zonal_wavefront_at(sc, refl.name, segs, px=PX)
    if fld is None:
        print("  %s: zonal returned None (no footprint/mesh)" % key)
        return None
    np.save(os.path.join(OUT, key + "_field.npy"), fld["field"])
    meta = {"rms_gauss": fld["rms_gauss"], "rms_uniform": fld["rms_uniform"], "pv": fld["pv_waves"],
            "footprint_mm": fld["footprint_mm"], "hit_frac": fld["hit_frac"], "px": fld["px"],
            "nyquist_lp_mm": fld["nyquist_lp_mm"]}
    print("  %s: footprint Ø%.0fmm  RMS=%.0f waves  hits=%.0f%%  px=%d"
          % (key, fld["footprint_mm"], fld["rms_uniform"], 100.0 * fld["hit_frac"], fld["px"]))
    return meta


def main():
    meta = {}
    m = render_case(lambda: load_knight(KNIGHT, target_h=90.0), "knight", w_target_mm=62.0)
    if m:
        m["title"] = "Chess knight (real GitHub OBJ) — side profile to the beam"
        meta["knight"] = m
    m = render_case(lambda: build_die(S=40.0), "die", w_target_mm=15.0)   # footprint inside the 40mm face
    if m:
        m["title"] = "Die (built to standard) — 5-face to the beam"
        meta["die"] = m
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=2)
    print("DUMPED", OUT)


if __name__ == "__main__":
    main()
