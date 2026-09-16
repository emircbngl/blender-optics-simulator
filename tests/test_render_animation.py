"""An animation render re-bakes the beams for every frame, through Blender's real render pipeline.

The handler tests in test_agent_control.py call on_render_pre directly; this one renders. A shutter keyed
open on frame 1 and closed on frame 2 must show the beam past it on frame 1 and not on frame 2.

Run: blender -b --factory-startup --python-exit-code 1 --python tests/test_render_animation.py
"""
import os
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import optical_alignment_sim as addon

addon.register()
from optical_alignment_sim import bake, elements_generic as eg

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail), flush=True)


scene = bpy.context.scene
scene.optics.live_enabled = False
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
eg.source("Src", (-60, 0, 0), (1, 0, 0))
shutter = eg._inline("Shut", (0, 0, 0), (1, 0, 0), None, "SHUTTER", "wp")
shutter.optics.shutter_open = True
shutter.optics.keyframe_insert(data_path="shutter_open", frame=1)
shutter.optics.shutter_open = False
shutter.optics.keyframe_insert(data_path="shutter_open", frame=2)
scene.frame_start, scene.frame_end = 1, 2
scene.optics.beam_radius_scale = 8.0
scene.frame_set(1)
bake.ensure_beams(bpy.context)
baked = sorted(o.name for o in scene.objects if o.name.startswith("BEAM_"))

# Look at the downstream half of the bench (x > 0) only, where the beam exists exactly while the shutter is open.
shutter.hide_render = True
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = (50, -120, 0)   # sees x = 7..93 mm: only the beam past the shutter
cam.rotation_euler = (1.5707963, 0.0, 0.0)
cam.data.lens = 50
scene.render.engine = "CYCLES"
scene.cycles.samples = 4
scene.cycles.device = "CPU"
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 96, 48, 100
scene.render.image_settings.file_format = "PNG"
scene.render.use_lock_interface = True

seen = {}


def _post(sc, *args):
    seen[sc.frame_current] = (sc.objects["Shut"].optics.shutter_open,
                              sorted(o.name for o in sc.objects if o.name.startswith("BEAM_")))


bpy.app.handlers.render_post.append(_post)
with tempfile.TemporaryDirectory(prefix="oas-anim-") as out:
    scene.render.filepath = os.path.join(out, "f_")
    bpy.ops.render.render(animation=True)
    bpy.app.handlers.render_post.remove(_post)

    def brightness(frame):
        img = bpy.data.images.load(os.path.join(out, "f_%04d.png" % frame))
        px = list(img.pixels)
        bpy.data.images.remove(img)
        return max(px[i] + px[i + 1] + px[i + 2] for i in range(0, len(px), 4))

    b1, b2 = brightness(1), brightness(2)

check("the bench bakes a beam past the shutter on frame 1", len(baked) >= 2, baked)
check("frame 2 of the render sees the shutter keyed closed", seen.get(2, (True,))[0] is False, seen)
check("frame 2 of the render has fewer beam meshes than frame 1",
      2 in seen and 1 in seen and len(seen[2][1]) < len(seen[1][1]), seen)
check("the rendered frame 1 shows the beam and frame 2 does not", b1 > 0.5 and b2 < 0.5 * b1,
      "max rgb sum frame1 %.3f frame2 %.3f" % (b1, b2))
print("RENDER ANIMATION %s (%d/%d checks)" % ("PASS" if all(checks) else "FAIL", sum(checks), len(checks)), flush=True)
if not all(checks):
    raise AssertionError("render animation witnesses failed")
