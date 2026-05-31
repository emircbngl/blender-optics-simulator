"""Render helper: one-click EEVEE preview / Cycles final with the user's
settings, plus camera presets. Resolves the EEVEE engine id at runtime
(Blender 5.x: 'BLENDER_EEVEE'; 4.2-4.4: 'BLENDER_EEVEE_NEXT').
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty
from mathutils import Vector

from . import bake


def resolve_eevee_id():
    try:
        ids = {e.identifier for e in
               bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    except Exception:
        ids = set()
    for cand in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
        if cand in ids:
            return cand
    return 'BLENDER_EEVEE'


def _world_bg_node(scene):
    """Return (world, background-shader-node), creating an OPTICS_World if none.
    Robust to renamed/custom node trees (falls back to the World Output's surface)."""
    w = scene.world
    if w is None:
        w = bpy.data.worlds.new("OPTICS_World")
        scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg is None:
        out = next((n for n in w.node_tree.nodes if n.type == 'OUTPUT_WORLD'), None)
        if out and out.inputs[0].is_linked:
            bg = out.inputs[0].links[0].from_node
    return w, bg


# Backdrop presets for renders. TRANSPARENT sets film_transparent so the render
# is an alpha PNG to composite onto paper/figures/slides.
_BG = {
    'DARK':        {"color": (0.02, 0.02, 0.03, 1.0), "strength": 0.4, "transparent": False},
    'BLACK':       {"color": (0.0, 0.0, 0.0, 1.0),    "strength": 1.0, "transparent": False},
    'WHITE':       {"color": (1.0, 1.0, 1.0, 1.0),    "strength": 1.0, "transparent": False},
    'TRANSPARENT': {"color": (0.02, 0.02, 0.03, 1.0), "strength": 0.3, "transparent": True},
}


def apply_background(scene, preset=None):
    """Set the world backdrop colour/strength + film transparency from a named
    preset (or scene.optics.bg_preset). An explicit choice is applied as-is."""
    preset = preset or getattr(getattr(scene, "optics", None), "bg_preset", 'DARK')
    cfg = _BG.get(preset, _BG['DARK'])
    _w, bg = _world_bg_node(scene)
    if bg and "Strength" in bg.inputs:
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = cfg["color"]
        bg.inputs["Strength"].default_value = cfg["strength"]
    scene.render.film_transparent = cfg["transparent"]


def ensure_lighting(scene):
    """Add a default sun if the scene has none, so a one-click render is not black.
    The world backdrop itself is set separately by apply_background()."""
    if not any(o.type == 'LIGHT' for o in scene.objects):
        ld = bpy.data.lights.new("OPTICS_Sun", 'SUN')
        ld.energy = 3.0
        sun = bpy.data.objects.new("OPTICS_Sun", ld)
        scene.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(52), math.radians(8), math.radians(40))


def setup_preview(scene):
    scene.render.engine = resolve_eevee_id()
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    ensure_lighting(scene)
    apply_background(scene)
    return scene.render.engine


def setup_final(scene):
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    try:
        scene.view_settings.view_transform = 'Filmic'
    except Exception:
        pass
    ensure_lighting(scene)
    apply_background(scene)
    return scene.render.engine


def _optical_bounds(scene):
    mn = Vector((1e18, 1e18, 1e18))
    mx = -mn
    found = False
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if op and op.is_optical:
            found = True
            for c in o.bound_box:
                w = o.matrix_world @ Vector(c)
                for i in range(3):
                    mn[i] = min(mn[i], w[i])
                    mx[i] = max(mx[i], w[i])
    if not found:
        return Vector((0, 0, 0)), 10.0
    return (mn + mx) * 0.5, max((mx - mn).length, 1.0)


_CAM_DIRS = {
    'HERO':  Vector((1.0, -1.0, 0.6)),
    'TOP':   Vector((0.0, 0.0, 1.0)),
    'FRONT': Vector((0.0, -1.0, 0.0)),
    'SIDE':  Vector((1.0, 0.0, 0.0)),
}


def set_camera(scene, preset='HERO'):
    cam = scene.camera
    if cam is None or cam.type != 'CAMERA':
        cdata = bpy.data.cameras.new("OPTICS_CAM")
        cam = bpy.data.objects.new("OPTICS_CAM", cdata)
        scene.collection.objects.link(cam)
        scene.camera = cam
    center, size = _optical_bounds(scene)
    cam.data.type = 'PERSP'
    cam.data.lens = 35.0
    radius = max(size * 0.5, 1.0)
    dist = radius / math.tan(cam.data.angle * 0.5) * 1.3 + radius   # fit bounding sphere
    cam.data.clip_start = max(0.01, radius * 0.001)
    cam.data.clip_end = (dist + size) * 4.0                          # don't clip the setup
    d = _CAM_DIRS.get(preset, _CAM_DIRS['HERO']).normalized()
    cam.location = center + d * dist
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return cam


class OPTICS_OT_set_camera(Operator):
    bl_idname = "optics.set_camera"
    bl_label = "Camera Preset"
    bl_description = "Frame the optical setup from a preset angle"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(items=[('HERO', "Hero", ""), ('TOP', "Top", ""),
                                ('FRONT', "Front", ""), ('SIDE', "Side", "")],
                         default='HERO')

    def execute(self, context):
        set_camera(context.scene, self.preset)
        self.report({'INFO'}, "Camera set: %s" % self.preset)
        return {'FINISHED'}


class OPTICS_OT_render_preview(Operator):
    bl_idname = "optics.render_preview"
    bl_label = "EEVEE Preview"
    bl_description = "Bake beams, switch to EEVEE, and render"
    bl_options = {'REGISTER'}

    def execute(self, context):
        bake.ensure_beams(context)
        eng = setup_preview(context.scene)
        if context.scene.camera is None:
            set_camera(context.scene, 'HERO')
        self.report({'INFO'}, "EEVEE (%s) ready - rendering" % eng)
        bpy.ops.render.render('INVOKE_DEFAULT')
        return {'FINISHED'}


class OPTICS_OT_render_final(Operator):
    bl_idname = "optics.render_final"
    bl_label = "Cycles Final"
    bl_description = "Bake beams, switch to Cycles (64 spp, denoise, Filmic), and render"
    bl_options = {'REGISTER'}

    def execute(self, context):
        bake.ensure_beams(context)
        setup_final(context.scene)
        if context.scene.camera is None:
            set_camera(context.scene, 'HERO')
        self.report({'INFO'}, "Cycles final ready - rendering")
        bpy.ops.render.render('INVOKE_DEFAULT')
        return {'FINISHED'}


_classes = (
    OPTICS_OT_set_camera,
    OPTICS_OT_render_preview,
    OPTICS_OT_render_final,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
