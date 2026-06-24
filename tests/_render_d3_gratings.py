"""Render the D3 grating GROOVE PROFILES + the PPLN poling stripes as a four-up montage (Cycles CPU still).

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_d3_gratings.py

Four parts side by side on the dark warm bench, each surface turned toward the camera under a grazing key
light so the relief reads:
  RULED       -- asymmetric blazed SAWTOOTH ridges.
  HOLOGRAPHIC -- rounded SINUSOIDAL corrugation.
  ECHELLE     -- a few COARSE, steeply-tilted STEPS (staircase).
  PPLN        -- the C7 QPM crystal with alternating poling-domain STRIPES + the oven housing.
The four MUST be visually distinguishable (the D3 verify gate). EEVEE aborts headless -> Cycles CPU.

Saves to /tmp/d3_gratings.png AND docs/img/grating-profiles.png.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
import bmesh
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

    c = G.example_collection("D3_GratingRender")

    # Each grating's ruled (+Z) face is turned UP and toward the camera so the relief catches the grazing
    # key light. grating() orients +Z onto normalize(out_dir-in_dir); choosing out=nrm, in=-nrm -> +Z=nrm.
    # The grooves run along the part's local Y -> a key light from the +X side rakes ACROSS them, throwing
    # the shadows that separate the sawtooth (RULED) from the sinusoid (HOLOGRAPHIC) from the steps (ECHELLE).
    face = Vector((0.10, -0.30, 0.95)).normalized()        # face turned mostly UP toward the -Y/+Z camera
    sz = 26.0
    gap = 40.0
    G.grating("D3_Ruled", (-1.5 * gap, 0, 0), -face, face, c, size=sz,
              lines_per_mm=600.0, order=1, grating_profile='RULED')
    G.grating("D3_Holographic", (-0.5 * gap, 0, 0), -face, face, c, size=sz,
              lines_per_mm=1200.0, order=1, grating_profile='HOLOGRAPHIC')
    G.grating("D3_Echelle", (0.5 * gap, 0, 0), -face, face, c, size=sz,
              lines_per_mm=80.0, order=1, grating_profile='ECHELLE')
    # the PPLN slab: its poling-domain stripes run along the beam axis, so lay that axis horizontal (+X)
    # and stand the striped broad face toward the camera. NO oven here -- the montage shows the four
    # PROFILES (the stripes ARE the PPLN's "profile"); the oven housing is incidental clutter that dwarfed
    # the crystal in the four-up, so it is left off for the comparison (oven=True is still a valid build).
    G.crystal("D3_PPLN", (1.5 * gap, 0, 0), Vector((1, 0, 0)), c, size=sz * 0.85, nl_process='SHG',
              crystal_material='PPLN', phase_matching_type='TYPE0', pm_scheme='QPM',
              poling_period_um=6.5, crystal_length_mm=sz * 0.85, oven=False, ppln_show_stripes=True)

    scene.optics.realistic_optics = True
    scene.optics.bg_preset = 'DARK'

    # a warm dark optical-bench board under the parts
    b = bmesh.new()
    bmesh.ops.create_grid(b, x_segments=1, y_segments=1, size=200.0)
    bm = bpy.data.meshes.new("D3_Bench")
    b.to_mesh(bm); b.free()
    bench = bpy.data.objects.new("D3_Bench", bm)
    scene.collection.objects.link(bench)
    bench.location = (0, 0, -16)
    bmat = bpy.data.materials.get("D3_BenchMat") or bpy.data.materials.new("D3_BenchMat")
    bmat.use_nodes = True
    bn = bmat.node_tree.nodes.get("Principled BSDF")
    if bn:
        bn.inputs["Base Color"].default_value = (0.04, 0.032, 0.026, 1.0)   # warm near-black anodized board
        bn.inputs["Roughness"].default_value = 0.5
        if "Metallic" in bn.inputs:
            bn.inputs["Metallic"].default_value = 0.5
    bench.data.materials.append(bmat)

    render.setup_final(scene)                       # Cycles, realistic materials + studio + warm world
    scene.cycles.device = 'CPU'                     # CPU per the headless render rule (GPU slower on M4)
    scene.cycles.samples = 150
    scene.render.resolution_x = 2000
    scene.render.resolution_y = 760

    # a GRAZING key light raking from the +X SIDE (across the grooves) + low, so the relief throws long
    # shadows -> sawtooth vs sinusoid vs steps all read. A small area keeps the shadows crisp.
    klight = bpy.data.lights.new("D3_Key", 'AREA')
    klight.energy = 140000.0
    klight.size = 28.0
    ko = bpy.data.objects.new("D3_Key", klight)
    scene.collection.objects.link(ko)
    ko.location = (130, -36, 36)                      # low + off to the +X side -> rakes across the grooves
    ko.rotation_euler = (Vector((0, 0, 0)) - ko.location).to_track_quat('-Z', 'Y').to_euler()

    for o in scene.objects:                          # keep the studio fill LOW so the raked shadows survive
        if o.type == 'LIGHT' and o is not ko:
            o.data.energy *= 0.7
    _w, bg = render._world_bg_node(scene)
    if bg and "Strength" in bg.inputs:
        bg.inputs["Strength"].default_value = 0.45
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.05, 0.04, 0.035, 1.0)

    # frame the row from a low oblique -Y/+Z angle so we look ACROSS the ruled faces (the relief reads)
    render.set_camera_direction(scene, Vector((0.06, -0.62, 0.42)))
    if scene.camera:
        scene.camera.data.lens = 52.0

    outs = ["/tmp/d3_gratings.png", os.path.join(REPO, "docs", "img", "grating-profiles.png")]
    for out in outs:
        scene.render.filepath = out
        scene.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("RENDER_SAVED", out, "%dx%d" % (scene.render.resolution_x, scene.render.resolution_y))


if __name__ == "__main__":
    main()
