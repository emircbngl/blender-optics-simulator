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


# --- realistic optical materials + studio (render-time, reversible) ----------
# Beam splitters / lenses become glass, mirrors become coated metal, sensors stay dark, and a
# 3-softbox studio + graded world + glossy ground let the glass refract and the coatings reflect.
# The viewport keeps its flat editing colours: the original material is stashed per object and
# restored by clear_render_style().
_GLASS = {'BEAMSPLITTER': (0.80, 0.90, 1.0), 'LENS': (0.85, 0.95, 1.0),
          'DICHROIC': (0.95, 0.80, 0.95), 'WAVEPLATE': (1.0, 0.92, 0.60),
          'POLARIZER': (0.70, 1.0, 0.85), 'CAVITY': (0.80, 0.90, 1.0)}
_METAL = {'MIRROR': (0.95, 0.96, 0.98), 'DEFORMABLE_MIRROR': (0.95, 0.96, 0.98),
          'RETROREFLECTOR': (0.90, 0.92, 0.96), 'GRATING': (0.70, 0.70, 0.80)}
_DARKSET = {'DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR'}
_STUDIO = ("OPTICS_Studio_key", "OPTICS_Studio_fill", "OPTICS_Studio_rim", "OPTICS_Studio_Ground")


def _setb(b, name, val):
    if b is not None and name in b.inputs:
        b.inputs[name].default_value = val


def _principled(name):
    m = bpy.data.materials.get(name)
    if m:
        return m, None
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs[0], out.inputs[0])
    return m, b


def _render_material(et):
    if et in _GLASS:
        m, b = _principled("OAR_glass_" + et)
        _setb(b, "Base Color", (*_GLASS[et], 1.0)); _setb(b, "Roughness", 0.02); _setb(b, "IOR", 1.52)
        _setb(b, "Transmission Weight", 1.0); _setb(b, "Transmission", 1.0)
        return m
    if et in _METAL:
        m, b = _principled("OAR_metal_" + et)
        _setb(b, "Base Color", (*_METAL[et], 1.0)); _setb(b, "Metallic", 1.0); _setb(b, "Roughness", 0.04)
        return m
    if et in _DARKSET:
        m, b = _principled("OAR_dark")
        _setb(b, "Base Color", (0.02, 0.02, 0.025, 1.0)); _setb(b, "Metallic", 0.6); _setb(b, "Roughness", 0.35)
        return m
    return None


def apply_optical_materials(scene):
    """Swap each optical element to a realistic render material, stashing the viewport material
    name in a custom prop so clear_render_style() can restore it."""
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if not op or not op.is_optical or o.type != 'MESH' or not o.data.materials:
            continue
        mat = _render_material(op.element_type)
        if mat is None:
            continue
        if "_oa_vp_mat" not in o:
            o["_oa_vp_mat"] = o.data.materials[0].name if o.data.materials[0] else ""
        o.data.materials[0] = mat


def studio_lighting(scene):
    """Sized-to-the-optics studio: graded dark world, 3 softboxes, glossy ground. Idempotent."""
    center, size = _optical_bounds(scene)
    _w, bg = _world_bg_node(scene)
    _setb(bg, "Color", (0.05, 0.055, 0.07, 1.0))
    if bg is not None and "Strength" in bg.inputs:
        bg.inputs["Strength"].default_value = 0.8
    scene.render.film_transparent = False
    for nm, loc, en, sz in (("OPTICS_Studio_key", (0.8, -0.9, 1.4), 18.0, 1.4),
                            ("OPTICS_Studio_fill", (-1.0, -0.6, 0.6), 6.0, 1.6),
                            ("OPTICS_Studio_rim", (-0.3, 1.1, 1.0), 11.0, 1.0)):
        o = bpy.data.objects.get(nm)
        if o is None or o.type != 'LIGHT':
            ld = bpy.data.lights.new(nm, 'AREA')
            o = bpy.data.objects.new(nm, ld)
            scene.collection.objects.link(o)
        o.data.size = size * sz
        o.data.energy = en * size * size
        o.location = center + Vector(loc) * size
        o.rotation_euler = (center - o.location).to_track_quat('-Z', 'Y').to_euler()
    g = bpy.data.objects.get("OPTICS_Studio_Ground")
    if g is None:
        import bmesh
        me = bpy.data.meshes.new("OPTICS_Studio_Ground")
        bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size * 7.0)
        bm.to_mesh(me); bm.free()
        gm, gb = _principled("OAR_ground")
        _setb(gb, "Base Color", (0.015, 0.015, 0.02, 1.0)); _setb(gb, "Roughness", 0.45); _setb(gb, "Metallic", 0.2)
        me.materials.append(gm)
        g = bpy.data.objects.new("OPTICS_Studio_Ground", me)
        scene.collection.objects.link(g)
    g.location = (center.x, center.y, center.z - size * 0.42)


def clear_render_style(scene):
    """Reverse apply_optical_materials() + studio_lighting(): restore viewport materials and
    remove the studio rig. Safe to call when nothing was applied."""
    for o in scene.objects:
        if "_oa_vp_mat" in o:
            if o.type == 'MESH' and o.data.materials:
                orig = bpy.data.materials.get(o["_oa_vp_mat"])
                if orig:
                    o.data.materials[0] = orig
            del o["_oa_vp_mat"]
    for nm in _STUDIO:
        ob = bpy.data.objects.get(nm)
        if ob:
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
    apply_background(scene)


def _light_and_world(scene):
    """Realistic studio (if optics.realistic_optics) else the simple sun + backdrop."""
    if getattr(getattr(scene, "optics", None), "realistic_optics", False):
        apply_optical_materials(scene)
        studio_lighting(scene)
    else:
        clear_render_style(scene)
        ensure_lighting(scene)
        apply_background(scene)


def setup_preview(scene):
    scene.render.engine = resolve_eevee_id()
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    _light_and_world(scene)
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
    scene.cycles.transmission_bounces = 16          # let light pass through the glass elements
    scene.cycles.max_bounces = max(scene.cycles.max_bounces, 16)
    _light_and_world(scene)
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


class OPTICS_OT_reset_render_style(Operator):
    bl_idname = "optics.reset_render_style"
    bl_label = "Reset Render Style"
    bl_description = ("Restore the flat editing materials and remove the studio lighting + ground "
                      "that a realistic render added")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        clear_render_style(context.scene)
        self.report({'INFO'}, "Restored viewport materials; removed studio rig")
        return {'FINISHED'}


_classes = (
    OPTICS_OT_set_camera,
    OPTICS_OT_render_preview,
    OPTICS_OT_render_final,
    OPTICS_OT_reset_render_style,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
