"""Build and render the opto-mechanics showcase with Cycles CPU.

Run with Blender's ``--python`` switch and pass an output directory after ``--``.
The scene deliberately uses the public element, mount, rail and bench APIs; it is
therefore also a compact executable integration check for the new hardware.
"""
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector


def _outdir():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        raise RuntimeError("usage: --python tools/render_optomech_showcase.py -- <outdir>")
    os.makedirs(args[0], exist_ok=True)
    return args[0]


def _label(text, loc):
    bpy.ops.object.text_add(location=loc, rotation=(0.0, 0.0, 0.0))
    ob = bpy.context.active_object
    ob.name = "SHOWCASE_LABEL_" + text
    ob.data.body = text
    ob.data.align_x = 'CENTER'
    ob.data.size = 10.0
    ob.data.extrude = 0.25
    return ob


def _camera(scene, direction, path):
    from optical_alignment_sim import render
    render.set_camera_direction(scene, Vector(direction))
    scene.camera.data.lens = 43.0
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    import optical_alignment_sim as addon
    addon.register()
    from optical_alignment_sim import elements_generic as G, optics_api, optomech, mounts, bake, render, tracer

    outdir = _outdir()
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    coll = G.example_collection("OptomechShowcase")
    xaxis = Vector((1.0, 0.0, 0.0))
    yaxis = Vector((0.0, 1.0, 0.0))
    z = 100.0

    # Inline transparent chain: each optic centre lies exactly on one horizontal beam datum.
    laser = G.source("SC_Laser_VC1", (-330, 0, z), xaxis, coll, radius=12.7)
    wp = G.waveplate("SC_Waveplate_RSP1", (-250, 0, z), xaxis, coll)
    flip_in = G.window("SC_Filter_TRF90_In", (-165, 0, z), xaxis, coll, radius=12.0)
    lens = G.lens("SC_Lens_LMR_Cage", (-70, 0, z), xaxis, coll, focal=150.0)
    rail_lens = G.lens("SC_Lens_RLA", (15, 0, z), xaxis, coll, focal=200.0)
    km = G.mirror("SC_KM100_Fold", (105, 0, z), xaxis, yaxis, coll)
    gm = G.mirror("SC_GM100_Gimbal", (105, 120, z), yaxis, xaxis, coll)
    det = G.detector("SC_Camera", (235, 120, z), xaxis, coll, size=35.0)
    for ob, preset in ((laser, 'VC1'), (wp, 'RSP1'), (flip_in, 'TRF90'),
                       (km, 'KM100'), (gm, 'GM100')):
        ok, msg = mounts.apply_preset(ob, preset)
        if not ok:
            raise RuntimeError(msg)
    # 30 mm cage segment and default RLA carrier use the same support mechanisms exposed to users.
    lens.optics.support_system = 'CAGE_30'; lens.optics.cage_id = 'showcase_cage'
    optics_api.make_rail([rail_lens.name], rail_id='showcase_rla')

    # Side-by-side mechanical comparisons, intentionally outside the traced path.
    flip_out = G.window("SC_Filter_TRF90_Out", (-150, -105, z), xaxis, coll, radius=12.0)
    ks1 = G.mirror("SC_KS1_Parked", (-35, -105, z), xaxis, Vector((0, 1, 0)), coll)
    x95 = G.lens("SC_X95_Carrier", (105, -105, z + 105), xaxis, coll, focal=250.0)
    for ob, preset in ((flip_out, 'TRF90'), (ks1, 'KS1')):
        ok, msg = mounts.apply_preset(ob, preset)
        if not ok:
            raise RuntimeError(msg)
    flip_out.optics.dofs[0].current = 90.0
    optics_api.make_rail([x95.name], rail_id='showcase_x95', family='X95')

    for text, x, y in (("LASER VC1", -330, -32), ("RSP1", -250, -32),
                       ("TRF90 IN", -165, -32), ("LMR + CAGE", -70, -32),
                       ("RLA LENS", 15, -32), ("KM100 FOLD", 105, -32),
                       ("GM100 FOLD", 105, 88), ("CAMERA", 235, 88),
                       ("TRF90 OUT", -150, -142), ("KS1", -35, -142), ("X95", 105, -142)):
        _label(text, (x, y, 1.0))

    bpy.context.view_layer.update()
    optomech.dress(scene)
    # These are deliberate parked mechanical comparison assemblies, rather than elements of the
    # functioning beam chain. Their already-built hardware remains visible and parented, while the
    # diagnostics correctly do not classify intentional off-axis display parts as bypassed optics.
    for ob in (flip_out, ks1, x95):
        ob.optics.is_optical = False
    trace = optics_api.trace_beam()
    diagnosis = optics_api.diagnose()
    valid = optomech.validate_all(scene)
    issues = valid['geometry'] + valid['beam']
    bad = diagnosis['counts']['BAD']
    if bad or issues:
        raise RuntimeError("showcase gate failed: bad=%d validate=%s" % (bad, issues))

    bake.bake_beams(bpy.context)
    render.setup_final(scene)
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 960
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    _camera(scene, (0.55, -0.72, 0.55), os.path.join(outdir, '01_three_quarter.png'))
    _camera(scene, (0.0, 0.0, 1.0), os.path.join(outdir, '02_top.png'))
    _camera(scene, (0.0, -1.0, 0.16), os.path.join(outdir, '03_side.png'))
    _camera(scene, (0.20, -0.90, 0.34), os.path.join(outdir, '04_closeup_gimbal_flip.png'))

    inline = [laser, wp, flip_in, lens, rail_lens, km, gm, det]
    print(json.dumps({"stations": 11, "segments": trace['segments'], "bad": 0,
                      "validate_issues": 0,
                      "inline_center_z": [round(o.matrix_world.translation.z, 4) for o in inline]}))


if __name__ == '__main__':
    main()
