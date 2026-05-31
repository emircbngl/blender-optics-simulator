"""Bake the live beam overlay into real emission-cylinder meshes so Cycles/EEVEE
can render the beams (the GPU overlay is viewport-only and invisible to renders).

Beams go into a dedicated COL_BEAMS collection and are named BEAM_##, matching the
user's existing convention. This is the only module that writes mesh datablocks,
and only on explicit request (bake / render).
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import FloatProperty
from mathutils import Vector

from . import tracer

BEAM_COLL = "COL_BEAMS"
BEAM_MAT = "OPTICS_BEAM"


def beam_collection(scene):
    c = bpy.data.collections.get(BEAM_COLL)
    if c is None:
        c = bpy.data.collections.new(BEAM_COLL)
        scene.collection.children.link(c)
    return c


def beam_material():
    m = bpy.data.materials.get(BEAM_MAT)
    if m:
        return m
    m = bpy.data.materials.new(BEAM_MAT)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.08, 0.04, 1.0)
    em.inputs["Strength"].default_value = 25.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def clear_baked(scene):
    c = bpy.data.collections.get(BEAM_COLL)
    if not c:
        return 0
    n = 0
    for ob in list(c.objects):
        if ob.name.startswith("BEAM_"):
            bpy.data.objects.remove(ob, do_unlink=True)
            n += 1
    return n


def _make_cylinder(context, name, p1, p2, r, mat, coll):
    d = p2 - p1
    length = d.length
    if length < 1e-6:
        return None
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=length, location=(p1 + p2) * 0.5)
    ob = context.active_object
    ob.name = name
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    for c in list(ob.users_collection):
        if c is not coll:
            c.objects.unlink(ob)
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    return ob


def bake_beams(context, radius=0.6):
    scene = context.scene
    if not tracer.cached_segments:
        tracer.cached_segments = tracer.trace_scene(
            scene, mode=scene.optics.trace_mode,
            max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    clear_baked(scene)
    coll = beam_collection(scene)
    mat = beam_material()
    n = 0
    for i, s in enumerate(tracer.cached_segments):
        # thinner for beam-splitter-transmitted branches
        r = radius * (0.6 if s["kind"] == 'SPLIT_T' else 1.0)
        if _make_cylinder(context, "BEAM_%02d" % i, Vector(s["p1"]), Vector(s["p2"]), r, mat, coll):
            n += 1
    return n


def ensure_beams(context):
    """Make sure baked beams exist before a render."""
    c = bpy.data.collections.get(BEAM_COLL)
    if c is None or not any(o.name.startswith("BEAM_") for o in c.objects):
        return bake_beams(context)
    return len(c.objects)


class OPTICS_OT_bake_beams(Operator):
    bl_idname = "optics.bake_beams"
    bl_label = "Bake Beams to Mesh"
    bl_description = "Create emission-cylinder meshes from the current beam path (for rendering)"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name="Beam radius (mm)", default=0.6, min=0.01)

    def execute(self, context):
        n = bake_beams(context, radius=self.radius)
        self.report({'INFO'}, "Baked %d beam segments into '%s'" % (n, BEAM_COLL))
        return {'FINISHED'}


class OPTICS_OT_clear_baked(Operator):
    bl_idname = "optics.clear_baked"
    bl_label = "Clear Baked Beams"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = clear_baked(context.scene)
        self.report({'INFO'}, "Removed %d baked beams" % n)
        return {'FINISHED'}


_classes = (OPTICS_OT_bake_beams, OPTICS_OT_clear_baked)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
