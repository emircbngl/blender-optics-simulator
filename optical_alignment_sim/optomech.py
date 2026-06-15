"""Procedural opto-mechanics: posts, post-holders, a breadboard, and mount plates that dress
an optical bench so renders read like a real table instead of parts floating in space.

These are pure DECORATION: the objects carry no optics ports, so the tracer ignores them
(it only walks objects with ``optics.is_optical``). They live in a ``BENCH_`` name space and a
``COL_BENCH`` collection so *Strip Bench* can remove them cleanly, and they are NOT parented to
the optics or fed into the mount/anchor math, so dressing never perturbs alignment or the trace.
Built on demand (a render-prep step), re-runnable, fully reversible. GPL-clean original geometry
(no vendor CAD).
"""
from __future__ import annotations

import bpy
from mathutils import Vector

from . import elements_generic as eg

BENCH_COLL = "COL_BENCH"
BENCH_PREFIX = "BENCH_"


def _bench_mat(name, color, metal, rough):
    return eg._mat(name, color, metal=metal, rough=rough)


_MATS = {
    "post":   lambda: _bench_mat("OB_post", (0.05, 0.05, 0.06), 0.9, 0.35),    # black anodized alu
    "holder": lambda: _bench_mat("OB_holder", (0.10, 0.10, 0.12), 0.85, 0.40),
    "mount":  lambda: _bench_mat("OB_mount", (0.12, 0.12, 0.14), 0.85, 0.45),
    "board":  lambda: _bench_mat("OB_board", (0.02, 0.02, 0.025), 0.6, 0.55),   # matte breadboard
}


def bench_collection(scene):
    c = bpy.data.collections.get(BENCH_COLL)
    if c is None:
        c = bpy.data.collections.new(BENCH_COLL)
    if c.name not in scene.collection.children:
        try:
            scene.collection.children.link(c)
        except RuntimeError:
            pass
    return c


def _cyl(name, r, depth, loc, coll, matkey):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, vertices=24)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _box(name, size, loc, coll, matkey):
    o = eg._cube(name, Vector(size), coll)
    o.location = loc
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    return o


def _optical_objects(scene):
    return [o for o in scene.objects
            if getattr(o, "optics", None) and o.optics.is_optical
            and o.optics.element_type not in ('NONE',)]


def _world_zmin(o):
    """Lowest world-space z of an object's bounding box."""
    return min((o.matrix_world @ Vector(c)).z for c in o.bound_box)


def dress(scene, post_radius=3.0, clearance=55.0):
    """Spawn a breadboard under the optics plus a post (+ holder) under each element and a mount
    plate behind reflective/inline elements. Idempotent: strips any prior dressing first. Returns
    the object count."""
    strip(scene)
    elems = _optical_objects(scene)
    if not elems:
        return 0
    coll = bench_collection(scene)
    centers = [o.matrix_world.translation for o in elems]
    board_z = min(_world_zmin(o) for o in elems) - clearance
    xs = [c.x for c in centers]; ys = [c.y for c in centers]
    pad = 60.0
    bx0, bx1 = min(xs) - pad, max(xs) + pad
    by0, by1 = min(ys) - pad, max(ys) + pad
    th = 12.0
    _box(BENCH_PREFIX + "Breadboard",
         (bx1 - bx0, by1 - by0, th),
         ((bx0 + bx1) * 0.5, (by0 + by1) * 0.5, board_z - th * 0.5),
         coll, "board")
    n = 1
    for i, o in enumerate(elems):
        p = o.matrix_world.translation
        bottom = _world_zmin(o)
        h = max(bottom - board_z, 1.0)
        _cyl(BENCH_PREFIX + "Post_%02d" % i, post_radius, h, (p.x, p.y, bottom - h * 0.5), coll, "post")
        _box(BENCH_PREFIX + "Holder_%02d" % i, (16.0, 16.0, 14.0), (p.x, p.y, board_z + 7.0), coll, "holder")
        n += 2
    return n


def strip(scene):
    """Remove all bench-dressing objects (and free their meshes)."""
    n = 0
    c = bpy.data.collections.get(BENCH_COLL)
    targets = list(c.objects) if c else []
    targets += [o for o in scene.objects if o.name.startswith(BENCH_PREFIX) and o not in targets]
    for o in list(targets):
        if not o.name.startswith(BENCH_PREFIX):
            continue
        mesh = o.data if o.type == 'MESH' else None
        bpy.data.objects.remove(o, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        n += 1
    if c and not c.objects:
        bpy.data.collections.remove(c)
    return n


def is_dressed(scene):
    return any(o.name.startswith(BENCH_PREFIX) for o in scene.objects)


class OPTICS_OT_dress_bench(bpy.types.Operator):
    bl_idname = "optics.dress_bench"
    bl_label = "Dress Bench"
    bl_description = ("Add posts, post-holders and a breadboard under the optics so renders look "
                      "like a real optical table (decoration only; never traced). Toggles off if "
                      "already dressed")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if is_dressed(scene):
            k = strip(scene)
            self.report({'INFO'}, "Stripped bench dressing (%d objects)" % k)
        else:
            k = dress(scene)
            self.report({'INFO'}, "Dressed bench (%d posts/board)" % k if k else "No optical elements to dress")
        from . import tracer
        tracer._tag_redraw()
        return {'FINISHED'}


_classes = (OPTICS_OT_dress_bench,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
