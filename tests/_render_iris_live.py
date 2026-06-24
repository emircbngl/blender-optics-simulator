"""Acceptance render for the LIVE (animatable) iris: the SAME iris, dialed to three openings, with the
multi-leaf blades visibly CLOSING the polygonal aperture.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_iris_live.py

Builds three irises and -- via the live clear_aperture update= callback (regenerate_iris) -- dials each to a
different opening (wide open 20, mid 14, stopped down 7). They sit in a row, looking down the bore, so the
overlapping matte-black leaves are seen closing the polygon left->right. Saved to /tmp/iris_live.png and
docs/img/iris-closing.png. Cycles CPU only (EEVEE aborts headless).
"""
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

    c = G.example_collection("IrisLiveRender")

    # all three bores look INTO the camera (the +Z face points toward (-Y,+Z)) so the polygonal opening reads;
    # each iris is BUILT at radius 14, then the live callback is fired by setting clear_aperture -> the blades
    # close/open to the target. Wide (20) -> mid (14) -> stopped (7), left to right.
    face = Vector((0.0, -0.62, 0.78))
    specs = [("IrisWide", (-44, 0, 0), 20.0),
             ("IrisMid",  (0, 0, 0),  14.0),
             ("IrisStop", (44, 0, 0),  7.0)]
    irises = []
    for nm, loc, r_target in specs:
        ir = G.aperture(nm, loc, face, c, radius=14.0)     # built at 14...
        ir.optics.clear_aperture = r_target                # ...then DIALED live -> regenerate_iris fires
        irises.append((ir, r_target))
    bpy.context.view_layer.update()
    print("LIVE_OPENINGS", [(nm, round(ir.optics.clear_aperture, 1)) for (ir, _), (nm, _, _) in zip(irises, specs)])

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # a warm dark optical-bench board under the parts
    import bmesh
    bm = bpy.data.meshes.new("ILR_Bench")
    b = bmesh.new(); bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=200.0)
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("ILR_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (0, 0, -16)
    bmat = bpy.data.materials.get("ILR_BenchMat") or bpy.data.materials.new("ILR_BenchMat")
    bmat.use_nodes = True
    bn = bmat.node_tree.nodes.get("Principled BSDF")
    if bn:
        bn.inputs["Base Color"].default_value = (0.045, 0.035, 0.028, 1.0)
        bn.inputs["Roughness"].default_value = 0.45
        if "Metallic" in bn.inputs:
            bn.inputs["Metallic"].default_value = 0.5
    bench.data.materials.append(bmat)

    render.setup_final(scene)
    scene.cycles.device = 'CPU'                     # CPU per the headless render rule (GPU slower on M4)
    scene.cycles.samples = 120
    scene.render.resolution_x = 1800
    scene.render.resolution_y = 720

    for o in scene.objects:                         # brighten the studio so the matte leaves + knurl read
        if o.type == 'LIGHT':
            o.data.energy *= 2.4
    _w, bg = render._world_bg_node(scene)
    if bg and "Strength" in bg.inputs:
        bg.inputs["Strength"].default_value = 0.7
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.05, 0.04, 0.035, 1.0)

    render.set_camera_direction(scene, face)        # look down the bores so the polygons read
    scene.camera.data.lens = 42.0                   # wide enough to hold all three irises in the row

    outs = ["/tmp/iris_live.png", os.path.join(REPO, "docs", "img", "iris-closing.png")]
    os.makedirs(os.path.dirname(outs[1]), exist_ok=True)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = outs[0]
    bpy.ops.render.render(write_still=True)
    import shutil
    shutil.copyfile(outs[0], outs[1])
    for p in outs:
        print("RENDER_SAVED", p, "%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))


if __name__ == "__main__":
    main()
