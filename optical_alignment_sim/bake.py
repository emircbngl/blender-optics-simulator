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

_baked_sig = None       # signature of the segments currently baked (so renders never use a stale bake)


def _segments_sig(segs):
    """Cheap hash of the baked beam geometry (segment endpoints)."""
    return hash(tuple(round(c, 3) for s in segs
                      for pt in (s["p1"], s["p2"]) for c in pt))


def beam_collection(scene):
    c = bpy.data.collections.get(BEAM_COLL)
    if c is None:
        c = bpy.data.collections.new(BEAM_COLL)
    if c.name not in scene.collection.children:     # may exist but be linked to a DIFFERENT scene
        try:
            scene.collection.children.link(c)
        except RuntimeError:
            pass
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
    # collect BEAM_* both in COL_BEAMS and anywhere in the scene (renamed/moved collections),
    # and free the per-segment Mesh datablock too (do_unlink leaves it a 0-user orphan otherwise)
    targets = {}
    c = bpy.data.collections.get(BEAM_COLL)
    if c:
        for ob in c.objects:
            if ob.name.startswith("BEAM_"):
                targets[ob.name] = ob
    for ob in scene.objects:
        if ob.name.startswith("BEAM_"):
            targets[ob.name] = ob
    n = 0
    for ob in list(targets.values()):
        mesh = ob.data if ob.type == 'MESH' else None
        bpy.data.objects.remove(ob, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
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
    global _baked_sig
    scene = context.scene
    # always re-trace: baking the current geometry (not a possibly-stale cache from before the
    # last edit, e.g. with live mode off) is the whole point of a fresh bake
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
    _baked_sig = _segments_sig(tracer.cached_segments)
    return n


def ensure_beams(context):
    """Make sure baked beams exist AND match the current beam path before a render. Re-bakes
    when the path has changed since the last bake (the old bake would otherwise render stale
    beams over the moved optics)."""
    scene = context.scene
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    tracer.cached_segments = segs
    c = bpy.data.collections.get(BEAM_COLL)
    have = c is not None and any(o.name.startswith("BEAM_") for o in c.objects)
    if have and _segments_sig(segs) == _baked_sig:
        return len(c.objects)
    return bake_beams(context)


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
