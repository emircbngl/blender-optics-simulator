"""Render the C7 KTP green-doubler at work (Cycles CPU still): an infrared 1064 nm pump entering a
chi(2) crystal and a 532 nm GREEN second-harmonic beam leaving the slab, on the dark warm bench.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_c7_nlcrystal.py

The green-doubler bench: a 1064 nm pump (deep red beam) enters a KTP nonlinear crystal phase-matched
for SHG; ~half converts to 532 nm GREEN (lambda/2, energy conservation -- oracle-VERIFIED) while the
residual IR transmits. A 45-deg dichroic peels the green DOWN onto the green detector and passes the
IR straight through. The beams are baked to emission tubes and RE-COLORED by wavelength: deep red for
the 1064 IR, bright green for the 532 harmonic -- so the render literally shows "IR in, green out of
the crystal slab". EEVEE aborts headless -> Cycles CPU per the render rule.

Saves to /tmp/c7_nlcrystal.png AND docs/img/nonlinear-crystal.png.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import bmesh
from mathutils import Vector


def _emission(name, color, strength):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def main():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    from optical_alignment_sim import render, bake, tracer
    import optics_api

    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)

    # the C7 green-doubler example: 1064 IR pump -> KTP SHG crystal (+ oven) -> 532 green out -> dichroic
    optics_api.build_example("green_doubler")
    bpy.context.view_layer.update()

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # bake every beam to an emission tube, then recolor by WAVELENGTH so the render reads physically:
    # 1064 IR -> deep red, 532 SHG -> bright green.
    bake.bake_beams(bpy.context)
    segs = tracer.cached_segments
    ir_mat = _emission("C7_IR_BEAM", (1.0, 0.10, 0.05), 75.0)      # 1064 nm infrared (rendered deep red)
    green_mat = _emission("C7_GREEN_BEAM", (0.10, 1.0, 0.18), 160.0)  # 532 nm second harmonic (green)
    bc = bpy.data.collections.get("COL_BEAMS") or bpy.data.collections.get(bake.BEAM_COLL)
    n_g = n_ir = 0
    if bc:
        for ob in bc.objects:
            if not ob.name.startswith("BEAM_"):
                continue
            try:
                idx = int(ob.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if not (0 <= idx < len(segs)):
                continue
            wl = segs[idx].get("wavelength", 633.0)
            m = green_mat if abs(wl - 532.0) < 5.0 else ir_mat
            if abs(wl - 532.0) < 5.0:
                n_g += 1
            else:
                n_ir += 1
            if ob.data.materials:
                ob.data.materials[0] = m
            else:
                ob.data.materials.append(m)
    print("recolored %d green (532) + %d IR (1064) beam segment(s)" % (n_g, n_ir))

    # a warm dark optical-bench board under the parts
    b = bmesh.new()
    bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=340.0)
    bm = bpy.data.meshes.new("C7_Bench")
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("C7_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (90, -50, -18)
    bmat = bpy.data.materials.get("C7_BenchMat") or bpy.data.materials.new("C7_BenchMat")
    bmat.use_nodes = True
    bn = bmat.node_tree.nodes.get("Principled BSDF")
    if bn:
        bn.inputs["Base Color"].default_value = (0.03, 0.022, 0.017, 1.0)   # warm near-black board
        bn.inputs["Roughness"].default_value = 0.5
        if "Metallic" in bn.inputs:
            bn.inputs["Metallic"].default_value = 0.5
    bench.data.materials.append(bmat)

    render.setup_final(scene)                       # Cycles, realistic materials + studio + warm world
    scene.cycles.device = 'CPU'                     # CPU per the headless render rule (GPU slower on M4)
    scene.cycles.samples = 128
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000

    for o in scene.objects:                          # modest studio fill so the matte parts read but the
        if o.type == 'LIGHT':                         # beams still dominate (don't wash out the emission)
            o.data.energy *= 1.3
    _w, bg = render._world_bg_node(scene)
    if bg and "Strength" in bg.inputs:
        bg.inputs["Strength"].default_value = 0.28      # dim warm world -> the dark bench reads
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.05, 0.04, 0.035, 1.0)

    # look from the -Y FRONT, low + head-on, so BOTH the straight IR (left->right) and the green
    # peeling DOWN off the dichroic open up against the dark board.
    render.set_camera_direction(scene, Vector((0.12, -0.95, 0.24)))
    if scene.camera:
        scene.camera.data.lens = 30.0

    outs = ["/tmp/c7_nlcrystal.png", os.path.join(REPO, "docs", "img", "nonlinear-crystal.png")]
    for out in outs:
        scene.render.filepath = out
        scene.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("RENDER_SAVED", out, "%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))


if __name__ == "__main__":
    main()
