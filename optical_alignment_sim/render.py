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
# One render-material descriptor per element type: kind (glass|metal|dark|emit) + tint. A single
# table so a new element type can't silently fall through to its flat viewport material at render
# time (it covers every optical type in properties.ELEMENT_TYPES). The viewport MATS in
# elements_generic stay distinct/flat for editing clarity; this is render-only.
RENDER_DESCRIPTORS = {
    'MIRROR':            ('metal', (0.95, 0.96, 0.98)),
    'PRISM_MIRROR':      ('metal', (0.95, 0.96, 0.98)),
    'DEFORMABLE_MIRROR': ('metal', (0.95, 0.96, 0.98)),
    'RETROREFLECTOR':    ('metal', (0.90, 0.92, 0.96)),
    'GRATING':           ('metal', (0.70, 0.70, 0.80)),
    'BEAMSPLITTER':      ('glass', (0.80, 0.90, 1.00)),
    'LENS':              ('glass', (0.85, 0.95, 1.00)),
    'DICHROIC':          ('glass', (0.95, 0.80, 0.95)),
    'WAVEPLATE':         ('glass', (1.00, 0.92, 0.60)),
    'ABERRATOR':         ('glass', (1.00, 0.92, 0.60)),
    'POLARIZER':         ('glass', (0.70, 1.00, 0.85)),
    'CAVITY':            ('glass', (0.80, 0.90, 1.00)),
    'CRYSTAL':           ('glass', (0.70, 0.45, 0.90)),
    'FILTER':            ('glass', (0.95, 0.55, 0.30)),
    'ATTENUATOR':        ('glass', (0.55, 0.57, 0.62)),
    'PASSTHROUGH':       ('glass', (0.85, 0.90, 0.95)),
    'DETECTOR':          ('dark',  None),
    'PHOTODIODE':        ('dark',  None),
    'POWER_METER':       ('dark',  None),
    'WAVEFRONT_SENSOR':  ('dark',  None),
    'ISOLATOR':          ('dark',  (0.30, 0.30, 0.34)),
    'APERTURE':          ('dark',  (0.05, 0.05, 0.06)),
    'PINHOLE':           ('dark',  (0.05, 0.05, 0.06)),
    'SOURCE':            ('dark',  (0.12, 0.13, 0.15)),
    'FIBER_COLLIMATOR':  ('dark',  (0.13, 0.14, 0.16)),
}


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
    desc = RENDER_DESCRIPTORS.get(et)
    if desc is None:
        return None
    kind, tint = desc
    if kind == 'glass':
        m, b = _principled("OAR_glass_" + et)
        _setb(b, "Base Color", (*tint, 1.0)); _setb(b, "Roughness", 0.02); _setb(b, "IOR", 1.52)
        _setb(b, "Transmission Weight", 1.0); _setb(b, "Transmission", 1.0)
        return m
    if kind == 'metal':
        m, b = _principled("OAR_metal_" + et)
        _setb(b, "Base Color", (*tint, 1.0)); _setb(b, "Metallic", 1.0); _setb(b, "Roughness", 0.025)
        return m
    if kind == 'dark':
        m, b = _principled("OAR_dark_" + et)
        _setb(b, "Base Color", (*(tint or (0.02, 0.02, 0.025)), 1.0))
        _setb(b, "Metallic", 0.6); _setb(b, "Roughness", 0.35)
        return m
    if kind == 'emit':
        m, b = _principled("OAR_emit_" + et)
        _setb(b, "Emission Color", (*tint, 1.0)); _setb(b, "Emission Strength", 5.0)
        _setb(b, "Base Color", (*tint, 1.0))
        return m
    return None


# Mirror coating -> reflective tint (the variant's LOOK; the tracer already uses the metal's complex
# index for reflectivity). Protected silver is the brightest/warmest, aluminum neutral, gold golden.
_COATING_TINT = {
    'DIELECTRIC': (0.97, 0.97, 0.99), 'AL': (0.91, 0.92, 0.93),
    'AG': (0.97, 0.96, 0.90), 'AU': (1.00, 0.78, 0.34),
}


def _coating_material(coating):
    tint = _COATING_TINT.get(coating, _COATING_TINT['DIELECTRIC'])
    m, b = _principled("OAR_metalcoat_" + coating)
    _setb(b, "Base Color", (*tint, 1.0)); _setb(b, "Metallic", 1.0); _setb(b, "Roughness", 0.025)
    return m


def apply_optical_materials(scene):
    """Swap each optical element to a realistic render material, stashing the viewport material
    name in a custom prop so clear_render_style() can restore it. Idempotent and shared-mesh safe:
    an element whose slot 0 is already a render material ('OAR_*') is skipped, so a second object
    sharing the mesh (linked duplicate / Tier-2 catalog) never stashes the swapped material as its
    'original'."""
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if not op or not op.is_optical or o.type != 'MESH' or not o.data.materials:
            continue
        cur = o.data.materials[0]
        if cur is not None and cur.name.startswith("OAR_"):
            continue
        if op.element_type in ('MIRROR', 'PRISM_MIRROR'):
            mat = _coating_material(getattr(op, "coating", 'DIELECTRIC'))   # tint by the coating variant
        else:
            mat = _render_material(op.element_type)
        if mat is None:
            continue
        if "_oa_vp_mat" not in o:
            o["_oa_vp_mat"] = cur.name if cur else ""
        o.data.materials[0] = mat


def _remove_studio(scene):
    """Delete the studio rig (objects tagged '_oa_studio') and their orphan datablocks. Tag-based,
    so it never touches a user object that merely shares a name."""
    for o in list(scene.objects):
        if o.get("_oa_studio"):
            d = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            try:
                if isinstance(d, bpy.types.Light) and d.users == 0:
                    bpy.data.lights.remove(d)
                elif isinstance(d, bpy.types.Mesh) and d.users == 0:
                    bpy.data.meshes.remove(d)
            except Exception:
                pass


def studio_lighting(scene):
    """Sized-to-the-optics studio: 3 softboxes + a glossy ground, on the chosen background preset.
    Rebuilt fresh each call (tag-based teardown), so it is collision-proof and idempotent. Honors
    the bg_preset including TRANSPARENT (alpha render -> the ground is skipped so it can't block the
    cutout)."""
    _remove_studio(scene)
    try:                                            # fresh bounds even after same-tick edits
        if bpy.context and bpy.context.view_layer:
            bpy.context.view_layer.update()
    except Exception:
        pass
    center, size = _optical_bounds(scene)
    apply_background(scene)                          # honor bg_preset + film_transparent
    for nm, loc, en, sz in (("OPTICS_Studio_key", (0.8, -0.9, 1.4), 18.0, 1.4),
                            ("OPTICS_Studio_fill", (-1.0, -0.6, 0.6), 6.0, 1.6),
                            ("OPTICS_Studio_rim", (-0.3, 1.1, 1.0), 11.0, 1.0)):
        ld = bpy.data.lights.new(nm, 'AREA')
        o = bpy.data.objects.new(nm, ld)
        scene.collection.objects.link(o)
        o["_oa_studio"] = 1
        o.data.size = size * sz
        o.data.energy = en * size * size
        o.location = center + Vector(loc) * size
        o.rotation_euler = (center - o.location).to_track_quat('-Z', 'Y').to_euler()
    if not scene.render.film_transparent:            # a ground would block an alpha cutout
        import bmesh
        me = bpy.data.meshes.new("OPTICS_Studio_Ground")
        bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size * 7.0)
        bm.to_mesh(me); bm.free()
        gm, gb = _principled("OAR_ground")
        # a dark semi-GLOSSY optical-table surface: the (often 45 deg) mirrors then reflect a real floor
        # + the softbox highlights instead of dead black -- the fix for "mirror reflections look wrong".
        _setb(gb, "Base Color", (0.045, 0.047, 0.055, 1.0)); _setb(gb, "Roughness", 0.26); _setb(gb, "Metallic", 0.3)
        me.materials.append(gm)
        g = bpy.data.objects.new("OPTICS_Studio_Ground", me)
        scene.collection.objects.link(g)
        g["_oa_studio"] = 1
        g.location = (center.x, center.y, center.z - size * 0.42)


def clear_render_style(scene):
    """Reverse apply_optical_materials() + studio_lighting() + the realistic Cycles bounce bump:
    restore each element's viewport material (re-empties a slot whose original was empty or has
    since been removed), remove the studio rig, restore transmission/max bounces, and re-apply the
    background preset. Safe to call when nothing was applied."""
    for o in scene.objects:
        if "_oa_vp_mat" in o:
            if o.type == 'MESH' and o.data.materials:
                o.data.materials[0] = bpy.data.materials.get(o["_oa_vp_mat"])   # name/"" -> mat or None
            del o["_oa_vp_mat"]
    _remove_studio(scene)
    if "_oa_cyc" in scene:
        try:
            tb, mb = scene["_oa_cyc"]
            scene.cycles.transmission_bounces = int(tb)
            scene.cycles.max_bounces = int(mb)
        except Exception:
            pass
        del scene["_oa_cyc"]
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
    if getattr(getattr(scene, "optics", None), "realistic_optics", False):
        if "_oa_cyc" not in scene:                  # stash so clear_render_style can restore
            scene["_oa_cyc"] = [scene.cycles.transmission_bounces, scene.cycles.max_bounces]
        scene.cycles.transmission_bounces = 16       # let light pass through the glass elements
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


def set_camera_direction(scene, dvec):
    """Frame the optical setup from an arbitrary view direction (the primitive an orbit animation
    sweeps). Fits the bounding sphere just like the presets, so every orbit frame stays framed."""
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
    d = Vector(dvec).normalized()
    cam.location = center + d * dist
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return cam


def set_camera(scene, preset='HERO'):
    return set_camera_direction(scene, _CAM_DIRS.get(preset, _CAM_DIRS['HERO']))


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


_armed_scene = None     # name of the scene whose render style is armed for auto-restore


def _restore_after_render(scene, *args):
    """One-shot render-complete/-cancel handler: once the render is captured, revert the realistic
    render style so the viewport returns to its flat editing look automatically (no stuck glass).
    Only fires for the scene that was armed -- if a DIFFERENT scene renders first, stay armed so the
    armed scene's materials aren't reverted before its own render (and aren't left stuck after)."""
    global _armed_scene
    if _armed_scene is not None and scene is not None and scene.name != _armed_scene:
        return                                   # not our scene; keep waiting for the armed one
    try:
        clear_render_style(scene)
    finally:
        _armed_scene = None
        for h in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
            if _restore_after_render in h:
                try:
                    h.remove(_restore_after_render)
                except Exception:
                    pass


def _arm_restore(scene=None):
    """Arm the one-shot auto-restore for the next render of `scene` (idempotent)."""
    global _armed_scene
    if scene is not None:
        _armed_scene = scene.name
    for h in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if _restore_after_render not in h:
            h.append(_restore_after_render)


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
        if getattr(context.scene.optics, "realistic_optics", False):
            _arm_restore(context.scene)              # auto-revert the style once THIS scene renders
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
        if getattr(context.scene.optics, "realistic_optics", False):
            _arm_restore(context.scene)              # auto-revert the style once THIS scene renders
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
    for h in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if _restore_after_render in h:
            try:
                h.remove(_restore_after_render)
            except Exception:
                pass
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
