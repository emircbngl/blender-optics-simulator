"""Render the A9 back-reflection / ghost beam on the dark warm bench (Cycles CPU still).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_a9_ghost.py

Shows the bright PRIMARY beam passing through an uncoated window to the screen, PLUS the faint ~4%
parasitic Fresnel GHOST peeling back off the window face (clearly dimmer), with the guarding optical
isolator. model_ghosts is turned ON so the ghost child is traced. EEVEE aborts headless -> Cycles CPU.

Saves to /tmp/a9_ghost_render.png AND docs/img/ghost-beam.png.
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import bmesh
from mathutils import Vector


def _ghost_material():
    """A dim, amber-shifted emission for the parasitic ghost beam -- visibly fainter than the primary."""
    m = bpy.data.materials.get("A9_GHOST_BEAM")
    if m:
        return m
    m = bpy.data.materials.new("A9_GHOST_BEAM")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.38, 0.12, 1.0)     # amber (slightly off the primary red)
    em.inputs["Strength"].default_value = 9.0                     # ~6-7x dimmer than the primary (60)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def main():
    import optical_alignment_sim as addon
    try:
        addon.register()
    except Exception:
        pass
    from optical_alignment_sim import elements_generic as G, render, bake, tracer

    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    for o in list(scene.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)

    # A clean A9 HERO bench: a laser through an UNCOATED window TILTED ~22 deg, so the bright primary
    # beam transmits straight to the screen while the faint ~4% Fresnel GHOST peels clearly off the
    # window face onto a side catcher -- the textbook back-reflection picture. model_ghosts ON so the
    # ghost child is traced; a guarding isolator sits between the laser and the window.
    coll = G.example_collection("OpticsExample_A9Render")
    X = Vector((1, 0, 0))
    scene.optics.model_ghosts = True
    G.source("A9R_Laser", (-220, 0, 0), X, coll, wavelength=632.8)
    G.isolator("A9R_Isolator", (-140, 0, 0), X, coll)
    tilt = math.radians(22.0)
    win = G.window("A9R_Window", (0, 0, 0), Vector((math.cos(tilt), math.sin(tilt), 0.0)), coll, radius=16.0)
    win.optics.ar_coated = False
    G.detector("A9R_Screen", (200, 0, 0), X, coll, size=70.0)            # the bright primary beam
    # the ~44-deg-folded ghost runs back-and-down; place the catcher on that line
    g_dir = Vector((-math.cos(2 * tilt), -math.sin(2 * tilt), 0.0))
    G.detector("A9R_Catcher", tuple(g_dir * 150.0), g_dir, coll, size=56.0)
    bpy.context.view_layer.update()
    assert scene.optics.model_ghosts, "the A9 render must enable model_ghosts"

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # bake the beams to emission tubes, then RE-COLOR the ghost legs dim/amber so the ~4% ghost reads
    # as clearly fainter than the primary (the bake uses one bright-red material for every segment).
    bake.bake_beams(bpy.context, radius=0.9)
    segs = tracer.cached_segments
    # crank the PRIMARY beam emission so it reads bright red against the studio fill (the ghost stays dim)
    pmat = bpy.data.materials.get("OPTICS_BEAM")
    if pmat and pmat.use_nodes:
        for nd in pmat.node_tree.nodes:
            if nd.type == 'EMISSION':
                nd.inputs["Color"].default_value = (1.0, 0.05, 0.03, 1.0)
                nd.inputs["Strength"].default_value = 60.0
    gmat = _ghost_material()
    # mark ghost-lineage segments (a GHOST seed + its descendants via the parent tree)
    is_ghost = [s.get("kind") == "GHOST" for s in segs]
    for i, s in enumerate(segs):
        p = s.get("parent", -1)
        if 0 <= p < len(segs) and is_ghost[p]:
            is_ghost[i] = True
    bc = bpy.data.collections.get("COL_BEAMS")
    n_ghost = 0
    if bc:
        for ob in bc.objects:
            if not ob.name.startswith("BEAM_"):
                continue
            try:
                idx = int(ob.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if 0 <= idx < len(is_ghost) and is_ghost[idx]:
                if ob.data.materials:
                    ob.data.materials[0] = gmat
                else:
                    ob.data.materials.append(gmat)
                n_ghost += 1
    print("recolored %d ghost beam segment(s) dim/amber" % n_ghost)

    # a warm dark optical-bench board under the parts
    b = bmesh.new()
    bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=320.0)
    bm = bpy.data.meshes.new("A9_Bench")
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("A9_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (0, -40, -16)
    bmat = bpy.data.materials.get("A9_BenchMat") or bpy.data.materials.new("A9_BenchMat")
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

    # look down onto the bench from above-front-side (dvec = center->camera, so +z is ABOVE, -y is in
    # FRONT of the bench) so the primary beam (left->right) and the ghost peeling back off the window
    # both read against the dark board.
    render.set_camera_direction(scene, Vector((0.22, -0.5, 0.5)))
    if scene.camera:
        scene.camera.data.lens = 40.0

    outs = ["/tmp/a9_ghost_render.png", os.path.join(REPO, "docs", "img", "ghost-beam.png")]
    for out in outs:
        scene.render.filepath = out
        scene.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("RENDER_SAVED", out, "%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))


if __name__ == "__main__":
    main()
