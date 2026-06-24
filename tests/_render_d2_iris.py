"""Render the D2 realistic iris + pinhole on the dark warm bench (Cycles CPU still).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_d2_iris.py

Shows the multi-leaf iris (overlapping matte-black leaves forming the polygonal opening + knurled adjuster
ring + engraved close-arrow), looking slightly down the bore so the polygonal aperture reads, beside a
stopped-down iris and a foil-in-housing pinhole. EEVEE aborts headless -> Cycles CPU only.
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector


def main():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    from optical_alignment_sim import elements_generic as G, render

    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)

    c = G.example_collection("D2_IrisRender")
    Z = Vector((0, 0, 1))

    # The HERO iris faces the camera so we look straight down the bore -> the polygonal multi-leaf opening +
    # the knurled adjuster ring + the engraved close-arrow all read. A stopped-down iris (smaller polygon) and
    # the foil-in-housing pinhole sit behind it for context. The iris +Z face points toward (-Y,+Z)=the camera.
    face = Vector((0.0, -0.62, 0.78))                          # the camera direction the bores look into
    iris_open = G.aperture("D2_IrisOpen", (-20, 4, 2), face, c, radius=16.0)   # hero, wide open
    iris_stop = G.aperture("D2_IrisStop", (24, -10, 0), face, c, radius=7.0)   # stopped down (tighter polygon)
    ph = G.pinhole("D2_Pinhole", (6, -26, -4), face, c, radius=12.5)           # foil pinhole

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # a warm dark optical-bench board under the parts
    bm = bpy.data.meshes.new("D2_Bench")
    import bmesh
    b = bmesh.new(); bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=160.0)
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("D2_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (0, 0, -18)
    bmat = bpy.data.materials.get("D2_BenchMat") or bpy.data.materials.new("D2_BenchMat")
    bmat.use_nodes = True
    bn = bmat.node_tree.nodes.get("Principled BSDF")
    if bn:
        bn.inputs["Base Color"].default_value = (0.045, 0.035, 0.028, 1.0)   # warm near-black anodized board
        bn.inputs["Roughness"].default_value = 0.45
        if "Metallic" in bn.inputs:
            bn.inputs["Metallic"].default_value = 0.5
    bench.data.materials.append(bmat)

    render.setup_final(scene)                       # Cycles, realistic materials + studio + warm world
    scene.cycles.device = 'CPU'                     # CPU per the headless render rule (GPU slower on M4)
    scene.cycles.samples = 110
    scene.render.resolution_x = 1500
    scene.render.resolution_y = 1000

    # brighten: nudge every studio area-light up + warm the world a touch so the matte leaves + knurl read
    for o in scene.objects:
        if o.type == 'LIGHT':
            o.data.energy *= 2.4
    _w, bg = render._world_bg_node(scene)
    if bg and "Strength" in bg.inputs:
        bg.inputs["Strength"].default_value = 0.7
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.05, 0.04, 0.035, 1.0)

    # frame a hero view aligned with the bore axis so we look INTO the iris opening (the polygon reads)
    render.set_camera_direction(scene, Vector((0.0, -0.62, 0.78)))
    scene.camera.data.lens = 56.0                   # the hero iris fills ~2/3 of frame; leaves + ring read
    # pull the camera partway in toward the hero iris (keep the whole part + the others in frame)
    scene.camera.location = scene.camera.location * 0.78 + iris_open.matrix_world.translation * 0.22

    out = "/tmp/d2_iris_render.png"
    scene.render.filepath = out
    scene.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)
    print("RENDER_SAVED", out)


if __name__ == "__main__":
    main()
