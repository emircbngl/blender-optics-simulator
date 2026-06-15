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

import math

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

# Mechanical standards (mm). A Ø1/2" / Thorlabs-metric post is precision-ground to Ø12.7 mm and
# shares holders across both unit systems, so we use one diameter for both (only the thread label,
# which we don't model as geometry, differs). See docs/OPTOMECH_SYSTEMS_PLAN.md.
POST_RADIUS = 6.35              # Ø12.7 mm optical post (TR/RS 1/2" workhorse)
BOARD_THICKNESS = 12.7          # 1/2" solid breadboard slab
MOUNT_DROP = 15.0               # optical axis -> post top: the mount body bridges this gap
HOLDER_H = 50.0                 # fixed post-holder body length (PH2-class); insertion varies, not the body
BASE_H = 9.0                    # post-holder/base foot thickness on the board
BEAM_HEIGHT_DEFAULT = 100.0     # optical-axis height above the board top (the layout datum)


def bench_pitch(scene):
    """The active grid pitch in mm (scene setting; default metric 25 mm)."""
    op = getattr(scene, "optics", None)
    p = float(getattr(op, "bench_grid_mm", GRID_DEFAULT_MM)) if op else GRID_DEFAULT_MM
    return p if p > 1e-3 else GRID_DEFAULT_MM


def beam_height(scene):
    """The bench beam height in mm (optical axis above the board top; scene datum, default 100)."""
    op = getattr(scene, "optics", None)
    h = float(getattr(op, "beam_height_mm", BEAM_HEIGHT_DEFAULT)) if op else BEAM_HEIGHT_DEFAULT
    return h if h > 1e-3 else BEAM_HEIGHT_DEFAULT


def _thread_hole_r(pitch):
    """Counterbore radius for the breadboard tapped hole, sized to the declared thread:
    M6 clearance ~Ø6.5 (metric grid) / 1/4-20 clearance ~Ø6.8 (imperial grid)."""
    return 3.4 if abs(pitch - GRID_IMPERIAL_MM) < 0.05 else 3.25


def _vertical_chain(scene, elems):
    """The shared vertical datum so dress() geometry and grid_info() data report the SAME numbers.
    Returns (beam_height, ref_axis_z, board_top_z). board_top_z is derived from the beam height and
    a robust reference axis (median optic-centre z), NOT from min(bbox), so it is stable under
    incremental edits — adding one tall optic never moves the table or re-cuts standing posts."""
    bh = beam_height(scene)
    zs = sorted((o.matrix_world.translation.z for o in elems))
    ref_z = zs[len(zs) // 2] if zs else 0.0          # median optic-axis height
    return bh, ref_z, ref_z - bh


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
    bh, ref_z, board_top_z = _vertical_chain(scene, elems)
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
                         "element_xy": [round(c.x, 3), round(c.y, 3)],
                         # the vertical chain (same numbers dress() builds): the other half of the BOM
                         "optic_z_mm": round(c.z, 3),
                         "post_length_mm": round(max(c.z - MOUNT_DROP - board_top_z, 1.0), 2),
                         "post_dia_mm": round(2.0 * POST_RADIUS, 3),
                         "holder_length_mm": round(HOLDER_H, 2),
                         "support_system": getattr(o.optics, "support_system", 'POST')})
    return {
        "pitch_mm": round(pitch, 4),
        "standard": "imperial" if abs(pitch - GRID_IMPERIAL_MM) < 0.05 else "metric",
        "thread": "1/4-20" if abs(pitch - GRID_IMPERIAL_MM) < 0.05 else "M6",
        "beam_height_mm": round(bh, 3),
        "board_top_z_mm": round(board_top_z, 3),
        "board_thickness_mm": round(BOARD_THICKNESS, 3),
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


# ---------------------------------------------------------------------------
# Mount-type-specific geometry (a real bench reads by mount silhouette)
# ---------------------------------------------------------------------------
# A physicist tells a steering mirror (kinematic mount, adjuster screws) from a waveplate
# (rotation collar with a scale) from a lens (threaded retaining ring) from a beamsplitter (cube
# platform) at a glance. dress() used to draw the same torus for all of them; _build_mount() gives
# each its own silhouette, oriented in the optic's own frame so it frames the actual optical face
# (fixing the old beamsplitter "horizontal hoop" bug — a cube gets a platform, not a ring).

_SOURCE_DET = {'SOURCE', 'FIBER_COLLIMATOR', 'DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR'}


def _obox(name, size, mw, off, coll, matkey):
    o = eg._cube(name, Vector(size), coll)
    o.matrix_world = mw @ Matrix.Translation(Vector(off))
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    return o


def _ocyl(name, r, depth, mw, off, coll, matkey, axis='Z'):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=(0, 0, 0), vertices=24)
    o = bpy.context.active_object
    o.name = name
    rot = Matrix.Identity(4)
    if axis == 'X':
        rot = Matrix.Rotation(math.radians(90), 4, 'Y')
    elif axis == 'Y':
        rot = Matrix.Rotation(math.radians(90), 4, 'X')
    o.matrix_world = (mw @ Matrix.Translation(Vector(off))) @ rot
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _build_mount(o, coll, idx):
    """Build the mount silhouette that matches the element's mount/element type, oriented in the
    optic's local frame (local +Z is the optical axis for inline parts; the cube body for splitters).
    Returns the number of objects created. All decoration: no ports, never traced."""
    op = o.optics
    et = op.element_type
    mt = getattr(op, "mount_type", 'FIXED')
    ca = max(getattr(op, "clear_aperture", 10.0), 6.0)
    p = o.matrix_world.translation
    mw = Matrix.Translation(p) @ o.matrix_world.to_3x3().to_4x4()
    pre = BENCH_PREFIX
    nm = "%02d" % idx

    if et in _SOURCE_DET:
        # self-contained body (laser/camera/crystal): a saddle bracket toward the post, no optic ring
        _obox(pre + "Bracket_" + nm, (ca * 1.0, ca * 1.0, 6.0), mw, (0, 0, -ca * 0.9), coll, "clamp")
        return 1
    if et in {'BEAMSPLITTER', 'PRISM_MIRROR'}:
        # cube mount: a platform plate under the cube + a back plate, aligned to the cube faces
        s = ca * 1.25
        _obox(pre + "CubeBase_" + nm, (s, s, 5.0), mw, (0, 0, -s * 0.62), coll, "mount")
        _obox(pre + "CubeBack_" + nm, (s, 5.0, s), mw, (0, -s * 0.62, 0), coll, "mount")
        return 2
    if mt == 'ROTATION' or et in {'WAVEPLATE', 'POLARIZER'}:
        # rotation mount: optic ring + a wider knurled collar + a radial index nub (reads "rotates")
        _ring(pre + "Mount_" + nm, ca * 1.18, ca * 0.16, mw, coll)
        _ocyl(pre + "Collar_" + nm, ca * 1.5, 6.0, mw, (0, 0, 0), coll, "mount")
        _obox(pre + "Index_" + nm, (2.5, 2.5, 4.0), mw, (ca * 1.5, 0, 0), coll, "post")
        return 3
    if mt == 'KINEMATIC_2AXIS' or et == 'MIRROR':
        # kinematic mount: square back-plate behind the optic + retaining ring + two adjuster screws
        plate = ca * 1.5
        _obox(pre + "KMplate_" + nm, (plate, plate, 6.0), mw, (0, 0, -6.0), coll, "mount")
        _ring(pre + "Mount_" + nm, ca * 1.18, ca * 0.16, mw, coll)
        _ocyl(pre + "Adj1_" + nm, 1.6, 11.0, mw, (plate * 0.32, plate * 0.32, -8.5), coll, "post")
        _ocyl(pre + "Adj2_" + nm, 1.6, 11.0, mw, (-plate * 0.32, -plate * 0.32, -8.5), coll, "post")
        return 4
    # threaded lens / filter / window / generic: a retaining ring inside a short lens-cell wall
    _ring(pre + "Mount_" + nm, ca * 1.18, ca * 0.16, mw, coll)
    _ocyl(pre + "Cell_" + nm, ca * 1.28, 5.0, mw, (0, 0, 0), coll, "mount")
    return 2


# ---------------------------------------------------------------------------
# Cage systems (16/30/60 mm): 4 shared rods + a plate per member + one post
# ---------------------------------------------------------------------------
# A cage holds several collinear optics on 4 parallel rods (the rods, not per-element posts, set
# coaxiality), and the whole assembly mounts to the table on one post. Members are grouped by
# (support_system, cage_id). Rod diameter and the square spacing are the published standards.
_CAGE_SPEC = {'CAGE_16': (2.0, 16.0), 'CAGE_30': (3.0, 30.0), 'CAGE_60': (3.0, 60.0)}


def cage_groups(scene):
    """Map (support_system, cage_id) -> [member optics] for every cage-mounted element."""
    groups = {}
    for o in _optical_objects(scene):
        ss = getattr(o.optics, "support_system", 'POST')
        if ss in _CAGE_SPEC:
            groups.setdefault((ss, getattr(o.optics, "cage_id", "") or ""), []).append(o)
    return groups


def _transverse_basis(axis):
    """Two orthonormal vectors spanning the plane transverse to ``axis``."""
    a = axis.normalized()
    up = Vector((0.0, 0.0, 1.0)) if abs(a.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    u = a.cross(up).normalized()
    v = a.cross(u).normalized()
    return u, v


def _cage_axis(members):
    """The shared cage axis: the member-to-member line (collinear assumption), or a lone member's
    optical axis (local +Z)."""
    cs = [m.matrix_world.translation for m in members]
    if len(cs) >= 2 and (cs[-1] - cs[0]).length > 1e-6:
        return (cs[-1] - cs[0]).normalized()
    return (members[0].matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()


def _rod(name, p0, p1, r, coll, matkey):
    """A cylinder spanning p0 -> p1 (a cage rod)."""
    p0 = Vector(p0); p1 = Vector(p1)
    d = p1 - p0
    L = max(d.length, 1e-6)
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=L, location=(0, 0, 0), vertices=16)
    o = bpy.context.active_object
    o.name = name
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    o.matrix_world = Matrix.Translation((p0 + p1) * 0.5) @ q.to_matrix().to_4x4()
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _cage_geom(members):
    """Shared cage geometry (axis, transverse basis, centroid, member projections, rod span) so the
    builder and cage_info() agree."""
    rod_r, sep = _CAGE_SPEC[members[0].optics.support_system]
    axis = _cage_axis(members)
    u, v = _transverse_basis(axis)
    cs = [m.matrix_world.translation for m in members]
    centroid = sum(cs, Vector((0.0, 0.0, 0.0))) / len(cs)
    ts = [(c - centroid).dot(axis) for c in cs]
    margin = sep * 0.9
    return rod_r, sep, axis, u, v, centroid, min(ts) - margin, max(ts) + margin


def _build_cage(scene, members, board_top_z, coll, post_radius, tag):
    """Build one cage: 4 rods on the size-mm square + a plate per member + one centre post."""
    rod_r, sep, axis, u, v, centroid, t0, t1 = _cage_geom(members)
    half = sep * 0.5
    n = 0
    for k, off in enumerate((u * half + v * half, u * half - v * half,
                             -u * half + v * half, -u * half - v * half)):
        base = centroid + off
        _rod("%sCageRod_%s_%d" % (BENCH_PREFIX, tag, k),
             base + axis * t0, base + axis * t1, rod_r, coll, "post")
        n += 1
    # a cage plate at each member (square plate transverse to the axis, framing the optic)
    rot = Matrix(((u.x, v.x, axis.x, 0.0), (u.y, v.y, axis.y, 0.0),
                  (u.z, v.z, axis.z, 0.0), (0.0, 0.0, 0.0, 1.0)))
    for j, m in enumerate(members):
        plate = eg._cube("%sCagePlate_%s_%d" % (BENCH_PREFIX, tag, j),
                         Vector((sep * 1.15, sep * 1.15, 8.9)), coll)
        plate.matrix_world = Matrix.Translation(m.matrix_world.translation) @ rot
        plate.data.materials.clear(); plate.data.materials.append(_MATS["mount"]())
        n += 1
    # one post under the cage centroid, to beam height
    post_top_z = centroid.z - MOUNT_DROP
    h = max(post_top_z - board_top_z, 1.0)
    _cyl("%sCageBase_%s" % (BENCH_PREFIX, tag), post_radius * 2.6, BASE_H,
         (centroid.x, centroid.y, board_top_z + BASE_H * 0.5), coll, "clamp")
    _cyl("%sCageHolder_%s" % (BENCH_PREFIX, tag), post_radius * 1.8, HOLDER_H,
         (centroid.x, centroid.y, board_top_z + BASE_H + HOLDER_H * 0.5), coll, "holder")
    _cyl("%sCagePost_%s" % (BENCH_PREFIX, tag), post_radius, h,
         (centroid.x, centroid.y, board_top_z + h * 0.5), coll, "post")
    return n + 3


def cage_info(scene):
    """Cage assemblies as data for get_state: id, size, rod dia/length/count, axis, members.
    Empty list when the bench is not dressed."""
    if not is_dressed(scene):
        return []
    out = []
    for (ss, cid), members in cage_groups(scene).items():
        rod_r, sep, axis, u, v, centroid, t0, t1 = _cage_geom(members)
        out.append({
            "id": cid or ss.lower(),
            "size_mm": int(sep), "rod_dia_mm": round(2.0 * rod_r, 3), "rod_count": 4,
            "rod_length_mm": round(t1 - t0, 2),
            "axis": [round(axis.x, 4), round(axis.y, 4), round(axis.z, 4)],
            "members": [m.name for m in members],
        })
    return out


def dress(scene, post_radius=POST_RADIUS):
    """Spawn a hole-grid breadboard under the optics, then a beam-height-driven post + post-holder
    base under each element and a mount ring framing the optic. The board top sits one beam height
    (``beam_height_mm``) below the optical axis, so every optic at that height gets an identical
    post length (the holder/mount absorb the small per-element offset) — the real-bench convention.
    The board datum is independent of the optics' bounding boxes, so it is stable under edits.
    Optics keep their exact positions, so dressing never perturbs the trace. Idempotent: strips any
    prior dressing first. Returns the object count."""
    strip(scene)
    elems = _optical_objects(scene)
    if not elems:
        return 0
    coll = bench_collection(scene)
    pitch = bench_pitch(scene)
    bh, ref_z, board_top_z = _vertical_chain(scene, elems)
    centers = [o.matrix_world.translation for o in elems]
    xs = [c.x for c in centers]; ys = [c.y for c in centers]
    pad = 2.0 * pitch
    # snap the board extent to the grid so every hole lands on an integer grid point
    x0 = _snap(min(xs) - pad, pitch); x1 = _snap(max(xs) + pad, pitch)
    y0 = _snap(min(ys) - pad, pitch); y1 = _snap(max(ys) + pad, pitch)
    nx = min(int(round((x1 - x0) / pitch)) + 1, 80)
    ny = min(int(round((y1 - y0) / pitch)) + 1, 80)
    th = BOARD_THICKNESS
    margin = pitch * 0.6  # board overhang past the outermost holes
    _box(BENCH_PREFIX + "Breadboard",
         (x1 - x0 + 2 * margin, y1 - y0 + 2 * margin, th),
         ((x0 + x1) * 0.5, (y0 + y1) * 0.5, board_top_z - th * 0.5),
         coll, "board")
    _hole_grid(BENCH_PREFIX + "Holes", x0, y0, nx, ny, pitch, board_top_z, coll,
               hole_r=_thread_hole_r(pitch))
    n = 2
    # cage-mounted optics ride shared rods + one cage post; everything else gets its own post.
    groups = cage_groups(scene)
    caged = {m.name for members in groups.values() for m in members}
    for i, o in enumerate(elems):
        if o.name in caged:
            continue
        p = o.matrix_world.translation
        # post top sits MOUNT_DROP below the optical axis; post length = beam_height - MOUNT_DROP
        # for any optic at the reference height, so equal-height optics share one standard post.
        post_top_z = p.z - MOUNT_DROP
        h = max(post_top_z - board_top_z, 1.0)
        # base foot bolted to the board (BA-style), then a fixed-length post-holder body; the post
        # slides through and is clamped -- body length is constant, only the insertion varies.
        _cyl(BENCH_PREFIX + "Base_%02d" % i, post_radius * 2.6, BASE_H,
             (p.x, p.y, board_top_z + BASE_H * 0.5), coll, "clamp")
        _cyl(BENCH_PREFIX + "Holder_%02d" % i, post_radius * 1.8, HOLDER_H,
             (p.x, p.y, board_top_z + BASE_H + HOLDER_H * 0.5), coll, "holder")
        _cyl(BENCH_PREFIX + "Post_%02d" % i, post_radius, h,
             (p.x, p.y, board_top_z + h * 0.5), coll, "post")
        # mount silhouette matched to the element/mount type (kinematic / rotation / cube / lens...)
        n += 3 + _build_mount(o, coll, i)
    for gi, members in enumerate(groups.values()):
        n += _build_cage(scene, members, board_top_z, coll, post_radius, "%02d" % gi)
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
