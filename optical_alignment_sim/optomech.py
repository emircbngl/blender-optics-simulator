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
from mathutils import Vector, Matrix

from . import elements_generic as eg

BENCH_COLL = "COL_BENCH"
BENCH_PREFIX = "BENCH_"


def _bench_mat(name, color, metal, rough):
    return eg._mat(name, color, metal=metal, rough=rough)


_MATS = {
    "post":   lambda: _bench_mat("OB_post", (0.05, 0.05, 0.06), 0.9, 0.35),    # black anodized alu
    "holder": lambda: _bench_mat("OB_holder", (0.10, 0.10, 0.12), 0.85, 0.40),
    "mount":  lambda: _bench_mat("OB_mount", (0.12, 0.12, 0.14), 0.85, 0.45),
    "board":  lambda: _bench_mat("OB_board", (0.10, 0.10, 0.115), 0.35, 0.55),  # dark-grey anodized breadboard
    "hole":   lambda: _bench_mat("OB_hole", (0.012, 0.012, 0.015), 0.7, 0.5),    # tapped-hole counterbore (near-black)
    "clamp":  lambda: _bench_mat("OB_clamp", (0.16, 0.16, 0.18), 0.8, 0.45),     # post-base clamp / pedestal foot
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


def _ring(name, major, minor, mw, coll, matkey="mount"):
    """A mount ring (torus) framing an optic, placed in the optic's transverse plane via mw."""
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, location=(0, 0, 0))
    o = bpy.context.active_object
    o.name = name
    o.matrix_world = mw
    for p in o.data.polygons:
        p.use_smooth = True
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _optical_objects(scene):
    return [o for o in scene.objects
            if getattr(o, "optics", None) and o.optics.is_optical
            and o.optics.element_type not in ('NONE',)]


def _world_zmin(o):
    """Lowest world-space z of an object's bounding box."""
    return min((o.matrix_world @ Vector(c)).z for c in o.bound_box)


# ---------------------------------------------------------------------------
# Breadboard hole grid (mechanically-correct, metric/imperial scene setting)
# ---------------------------------------------------------------------------
# A real breadboard is a regular array of tapped holes on a fixed pitch (metric
# 25 mm / M6, or imperial 1" / 1/4-20).  The grid is BOTH a render feature (the
# hole array) AND a data model: ``grid_info`` exposes origin/pitch/extent and the
# occupied holes so an MCP agent or a human knows exactly where parts can seat.
# Optics are NOT snapped to the grid (that would move them and change the trace) —
# instead each post clamps to the board directly under its optic, the realistic
# post-holder behaviour, while fresh parts can be *placed* on a named hole.

GRID_DEFAULT_MM = 25.0          # metric breadboard pitch (M6)
GRID_IMPERIAL_MM = 25.4         # imperial breadboard pitch (1", 1/4-20)


def bench_pitch(scene):
    """The active grid pitch in mm (scene setting; default metric 25 mm)."""
    op = getattr(scene, "optics", None)
    p = float(getattr(op, "bench_grid_mm", GRID_DEFAULT_MM)) if op else GRID_DEFAULT_MM
    return p if p > 1e-3 else GRID_DEFAULT_MM


def _snap(v, pitch):
    """Nearest grid coordinate to ``v`` for the given pitch (grid aligned to world origin)."""
    return round(v / pitch) * pitch


def grid_info(scene):
    """Return the bench grid as data: pitch, world origin/extent, hole counts, and the
    occupied (col,row) holes nearest each optic. ``None`` when the bench is not dressed.
    This is what makes the layout MCP/human-knowable — see optics_api.get_state()."""
    if not is_dressed(scene):
        return None
    elems = _optical_objects(scene)
    if not elems:
        return None
    pitch = bench_pitch(scene)
    centers = [o.matrix_world.translation for o in elems]
    xs = [c.x for c in centers]; ys = [c.y for c in centers]
    pad = 2.0 * pitch
    x0 = _snap(min(xs) - pad, pitch); x1 = _snap(max(xs) + pad, pitch)
    y0 = _snap(min(ys) - pad, pitch); y1 = _snap(max(ys) + pad, pitch)
    nx = min(int(round((x1 - x0) / pitch)) + 1, 80)
    ny = min(int(round((y1 - y0) / pitch)) + 1, 80)
    occupied = []
    for o, c in zip(elems, centers):
        col = max(0, min(nx - 1, int(round((c.x - x0) / pitch))))
        row = max(0, min(ny - 1, int(round((c.y - y0) / pitch))))
        occupied.append({"element": o.name, "col": col, "row": row,
                         "hole_xy": [round(x0 + col * pitch, 3), round(y0 + row * pitch, 3)],
                         "element_xy": [round(c.x, 3), round(c.y, 3)]})
    return {
        "pitch_mm": round(pitch, 4),
        "standard": "imperial" if abs(pitch - GRID_IMPERIAL_MM) < 0.05 else "metric",
        "thread": "1/4-20" if abs(pitch - GRID_IMPERIAL_MM) < 0.05 else "M6",
        "origin": [round(x0, 3), round(y0, 3)],
        "cols": nx, "rows": ny,
        "extent": [[round(x0, 3), round(y0, 3)], [round(x0 + (nx - 1) * pitch, 3),
                                                  round(y0 + (ny - 1) * pitch, 3)]],
        "occupied": occupied,
    }


def hole_world_xy(scene, col, row):
    """World (x,y) of grid hole (col,row) using the same origin grid_info() reports.
    Returns ``None`` if the bench is not dressed or the hole is out of range."""
    gi = grid_info(scene)
    if gi is None:
        return None
    if not (0 <= col < gi["cols"] and 0 <= row < gi["rows"]):
        return None
    x0, y0 = gi["origin"]
    return (x0 + col * gi["pitch_mm"], y0 + row * gi["pitch_mm"])


def _hole_grid(name, x0, y0, nx, ny, pitch, top_z, coll, hole_r=None):
    """One mesh of counterbore discs at every grid point — the breadboard's tapped-hole array.
    Built in a single bmesh pass (cheap: one mesh, N small discs) and parked a hair above the
    board top so the dark hole material reads as recessed holes."""
    import bmesh
    hole_r = hole_r if hole_r is not None else pitch * 0.17
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for j in range(ny):
        for i in range(nx):
            bmesh.ops.create_circle(
                bm, cap_ends=True, radius=hole_r, segments=10,
                matrix=Matrix.Translation((x0 + i * pitch, y0 + j * pitch, top_z + 0.05)))
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(_MATS["hole"]())
    eg._link_only(o, coll)
    return o


def dress(scene, post_radius=3.0, clearance=55.0):
    """Spawn a hole-grid breadboard under the optics, then a grid-aligned post + pedestal clamp
    under each element and a mount ring framing the optic. The board's hole array sits on the
    active grid pitch (``bench_grid_mm``); optics keep their exact positions (the post clamps to
    the board directly beneath them) so dressing never perturbs the trace. Idempotent: strips any
    prior dressing first. Returns the object count."""
    strip(scene)
    elems = _optical_objects(scene)
    if not elems:
        return 0
    coll = bench_collection(scene)
    pitch = bench_pitch(scene)
    centers = [o.matrix_world.translation for o in elems]
    board_z = min(_world_zmin(o) for o in elems) - clearance
    xs = [c.x for c in centers]; ys = [c.y for c in centers]
    pad = 2.0 * pitch
    # snap the board extent to the grid so every hole lands on an integer grid point
    x0 = _snap(min(xs) - pad, pitch); x1 = _snap(max(xs) + pad, pitch)
    y0 = _snap(min(ys) - pad, pitch); y1 = _snap(max(ys) + pad, pitch)
    nx = min(int(round((x1 - x0) / pitch)) + 1, 80)
    ny = min(int(round((y1 - y0) / pitch)) + 1, 80)
    th = 12.0
    margin = pitch * 0.6  # board overhang past the outermost holes
    _box(BENCH_PREFIX + "Breadboard",
         (x1 - x0 + 2 * margin, y1 - y0 + 2 * margin, th),
         ((x0 + x1) * 0.5, (y0 + y1) * 0.5, board_z - th * 0.5),
         coll, "board")
    _hole_grid(BENCH_PREFIX + "Holes", x0, y0, nx, ny, pitch, board_z, coll)
    n = 2
    for i, o in enumerate(elems):
        p = o.matrix_world.translation
        bottom = _world_zmin(o)
        h = max(bottom - board_z, 1.0)
        # post-holder base: a wider short cylinder bolted to the board (PH-series style), the post
        # slides into it -- mechanically real and reads as opto-mech rather than a bare stick
        hold_h = min(max(h * 0.45, 14.0), 28.0)
        _cyl(BENCH_PREFIX + "Holder_%02d" % i, post_radius * 2.3, hold_h,
             (p.x, p.y, board_z + hold_h * 0.5), coll, "clamp")
        # post rises from the board top to the optic underside, clamped directly beneath the optic
        _cyl(BENCH_PREFIX + "Post_%02d" % i, post_radius, h, (p.x, p.y, bottom - h * 0.5), coll, "post")
        # mount ring framing the optic, in its own transverse plane (orientation from its matrix)
        ca = max(getattr(o.optics, "clear_aperture", 10.0), 6.0)
        mw = Matrix.Translation(p) @ o.matrix_world.to_3x3().to_4x4()
        _ring(BENCH_PREFIX + "Mount_%02d" % i, ca * 1.18, ca * 0.16, mw, coll)
        n += 3
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
