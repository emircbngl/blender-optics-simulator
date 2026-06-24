"""Render the A11 UNIVERSAL coating pickoff: a WINDOW configured as a ~30% beam pickoff (Cycles CPU still).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_coating_pickoff.py

A plain glass WINDOW is given coating_reflectance=0.30, so the tracer peels a controlled 30% REFLECT
pickoff off its entry face while the bright primary beam (70%) passes through to the main detector. The
30% pickoff arm folds off to a SECOND detector -- the textbook beam-sampler / pickoff picture. The
coating is the controllable generalization of the A9 ghost (which is a fixed parasitic ~4% Fresnel
reflection); here R is whatever the user paints. EEVEE aborts headless -> Cycles CPU.

Saves to /tmp/coating_pickoff.png AND docs/img/coating-pickoff.png.
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


def _pickoff_material():
    """A dimmer, amber-shifted emission for the 30% pickoff arm -- visibly fainter than the 70% primary."""
    m = bpy.data.materials.get("A11_PICKOFF_BEAM")
    if m:
        return m
    m = bpy.data.materials.new("A11_PICKOFF_BEAM")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.55, 0.06, 1.0)     # amber/gold (clearly off the primary red)
    em.inputs["Strength"].default_value = 38.0                    # dimmer than the primary (90) but clearly visible
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

    # A clean A11 HERO bench: a laser through a TILTED window painted with a 30% reflective coating. The
    # bright 70% primary transmits straight to the main screen; the 30% pickoff peels cleanly off the
    # window's entry face (reflect about the tilted normal) onto a side detector. Default-neutral coating
    # (R=0) would do nothing; here R=0.30 makes the window an explicit beam sampler.
    coll = G.example_collection("OpticsExample_A11Render")
    X = Vector((1, 0, 0))
    G.source("A11_Laser", (-220, 0, 0), X, coll, wavelength=632.8)
    tilt = math.radians(22.0)
    win = G.window("A11_Pickoff", (0, 0, 0), Vector((math.cos(tilt), math.sin(tilt), 0.0)), coll, radius=16.0)
    win.optics.coating_reflectance = 0.30                                # 30% reflective coating
    G.detector("A11_Main", (210, 0, 0), X, coll, size=70.0)              # the bright 70% primary beam
    # the pickoff reflects about the (tilted) entry normal -> folds back-and-down ~44 deg; the second
    # detector sits on that line so the 30% pickoff arm lands on it (a real beam, not a parasitic ghost)
    p_dir = Vector((-math.cos(2 * tilt), -math.sin(2 * tilt), 0.0))
    G.detector("A11_Sampler", tuple(p_dir * 150.0), p_dir, coll, size=56.0)
    bpy.context.view_layer.update()

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # bake the beams to emission tubes, then RE-COLOR the pickoff arm dim/amber so the 30% pickoff reads
    # as clearly fainter than the 70% primary (the bake uses one bright-red material for every segment).
    bake.bake_beams(bpy.context, radius=0.9)
    segs = tracer.cached_segments
    # the pickoff lineage = the REFLECT child whose `from` is the pickoff window, + its descendants.
    is_pick = [s.get("kind") == "REFLECT" and s.get("from") == "A11_Pickoff" for s in segs]
    for i, s in enumerate(segs):
        p = s.get("parent", -1)
        if 0 <= p < len(segs) and is_pick[p]:
            is_pick[i] = True
    # crank the PRIMARY beam emission so it reads bright red against the studio fill (pickoff stays dim)
    pmat = bpy.data.materials.get("OPTICS_BEAM")
    if pmat and pmat.use_nodes:
        for nd in pmat.node_tree.nodes:
            if nd.type == 'EMISSION':
                nd.inputs["Color"].default_value = (1.0, 0.06, 0.03, 1.0)
                nd.inputs["Strength"].default_value = 90.0
    gmat = _pickoff_material()
    bc = bpy.data.collections.get("COL_BEAMS")
    n_pick = 0
    if bc:
        for ob in bc.objects:
            if not ob.name.startswith("BEAM_"):
                continue
            try:
                idx = int(ob.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if 0 <= idx < len(is_pick) and is_pick[idx]:
                if ob.data.materials:
                    ob.data.materials[0] = gmat
                else:
                    ob.data.materials.append(gmat)
                n_pick += 1
    print("recolored %d pickoff beam segment(s) dim/amber" % n_pick)

    # a warm dark optical-bench board under the parts
    b = bmesh.new()
    bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=320.0)
    bm = bpy.data.meshes.new("A11_Bench")
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("A11_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (0, -40, -16)
    bmat = bpy.data.materials.get("A11_BenchMat") or bpy.data.materials.new("A11_BenchMat")
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

    # look at the bench from the -Y FRONT, lower + more head-on, so BOTH the straight primary (left->right)
    # and the pickoff peeling DOWN-and-BACK (-Y) open up against the dark board instead of foreshortening.
    render.set_camera_direction(scene, Vector((0.10, -0.92, 0.36)))
    if scene.camera:
        scene.camera.data.lens = 35.0

    outs = ["/tmp/coating_pickoff.png", os.path.join(REPO, "docs", "img", "coating-pickoff.png")]
    for out in outs:
        scene.render.filepath = out
        scene.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("RENDER_SAVED", out, "%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))


if __name__ == "__main__":
    main()
