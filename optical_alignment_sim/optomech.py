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
    "steel":  lambda: _bench_mat("OB_steel", (0.55, 0.55, 0.58), 1.0, 0.28),     # bright screws / springs / adjusters
    "alu":    lambda: _bench_mat("OB_alu", (0.78, 0.78, 0.80), 1.0, 0.34),       # bare 6061 aluminium (LMR lens mounts)
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
# which we don't model as geometry, differs).
POST_RADIUS = 6.35              # Ø12.7 mm optical post (TR 1/2" workhorse)
POST_RADIUS_TALL = 12.5         # Ø25 mm (1") RS-series pillar — stiffer, for tall/raised mounts
PILLAR_OVER_MM = 130.0          # above this post length, use the fatter Ø1" pillar (stiffness ∝ d⁴)
VERTICAL_STACK_MM = 25.0        # optics this far apart in z at one xy => a vertical beam runs between
                                # them; the pillar must be OFFSET so it doesn't sit in the beam path
PILLAR_OFFSET = 44.0            # how far to push a vertical-fold (RS99 periscope) pillar off the beam
                                # axis: enough that the post + clamp clear the optic so neither blocks it
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
    Returns (beam_height, ref_axis_z, board_top_z). The board sits one beam height below the LOWEST
    optic, so even the lowest optic clears its post-holder (a median datum let a low optic in a
    multi-deck/periscope layout fall below the holder top). Single-height benches are unaffected
    (lowest == all == one beam height up, equal posts)."""
    bh = beam_height(scene)
    zs = [o.matrix_world.translation.z for o in elems]
    ref_z = min(zs) if zs else 0.0                   # lowest optic-axis height
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


def _bevel(o, width=0.5, segments=2):
    """Round the hard edges of a part so it reads as machined metal, not a CAD block. Applies a
    Bevel modifier (angle-limited) and bakes it in. Returns the object."""
    m = o.modifiers.new("bev", 'BEVEL')
    m.width = width; m.segments = segments
    m.limit_method = 'ANGLE'; m.angle_limit = math.radians(35)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)
    return o


def _diff(obj, cutter):
    """Boolean-subtract ``cutter`` from ``obj`` and free the cutter (the _bored_plate idiom, shared)."""
    m = obj.modifiers.new("cut", 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = cutter
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=m.name)
    cm = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cm.users == 0:
        bpy.data.meshes.remove(cm)


def _bore(obj, loc, r, depth, seg=24):
    """Subtract a vertical cylindrical hole of radius ``r`` / ``depth`` centred at world ``loc``."""
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, vertices=seg)
    _diff(obj, bpy.context.active_object)


def _bore_local(obj, mw, off, r, depth, axis='Z', seg=24):
    """Subtract a cylindrical hole along a LOCAL axis of frame ``mw`` (for ports/cage bores cut into
    a housing in the optic's own frame)."""
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=(0, 0, 0), vertices=seg)
    cut = bpy.context.active_object
    rot = Matrix.Identity(4)
    if axis == 'X':
        rot = Matrix.Rotation(math.radians(90), 4, 'Y')
    elif axis == 'Y':
        rot = Matrix.Rotation(math.radians(90), 4, 'X')
    cut.matrix_world = (mw @ Matrix.Translation(Vector(off))) @ rot
    _diff(obj, cut)


def _bore_grid(board, x0, y0, nx, ny, pitch, top_z, hole_r, depth=2.6):
    """Bore the tapped-hole array into the board as real recessed pockets (one merged cutter of N
    cylinders → a single boolean), so holes cast interior shadow instead of reading as painted dots.
    Capped for cost: above the cap the board keeps its flat-disc holes. Returns True if it bored."""
    import bmesh
    if nx * ny > 900:
        return False
    me = bpy.data.meshes.new(BENCH_PREFIX + "_holecut")
    bm = bmesh.new()
    for j in range(ny):
        for i in range(nx):
            bmesh.ops.create_cone(bm, cap_ends=True, segments=10,
                                  radius1=hole_r, radius2=hole_r, depth=depth + 2.0,
                                  matrix=Matrix.Translation((x0 + i * pitch, y0 + j * pitch,
                                                             top_z - depth * 0.5 + 1.0)))
    bm.to_mesh(me); bm.free()
    cut = bpy.data.objects.new(BENCH_PREFIX + "_holecut", me)
    bpy.context.scene.collection.objects.link(cut)
    _diff(board, cut)
    return True


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

    if et in {'DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR'}:
        # camera/detector: a cuboid body housing BEHIND the sensor (local -Z) + a C-mount barrel on
        # the FRONT (beam side, local +Z) + a vertical stem down to the post top (world-vertical), so
        # it reads as a real camera bolted to its post -- not a flat plate stuck to a bracket.
        _bevel(_obox(pre + "CamBody_" + nm, (ca * 1.7, ca * 1.7, ca * 1.5), mw, (0, 0, -ca * 0.78), coll, "mount"), 1.2, 2)
        _bevel(_ocyl(pre + "Cmount_" + nm, ca * 0.6, ca * 0.95, mw, (0, 0, ca * 0.72), coll, "clamp"), 0.7, 2)
        top_z = p.z - MOUNT_DROP                     # the post top dress() leaves under the optic
        cam_bot = p.z - ca * 0.85                    # camera body underside (world)
        if cam_bot - top_z > 0.5:
            _bevel(_cyl(pre + "CamStem_" + nm, 3.0, cam_bot - top_z,
                        (p.x, p.y, (top_z + cam_bot) * 0.5), coll, "mount"), 0.5, 1)
        return 3
    if et in _SOURCE_DET:
        # source/laser/collimator: a saddle clamp cradling the (often horizontal) body from BELOW + a
        # WORLD-vertical stem down to the post top -- so it is actually held by its post, not a bracket
        # floating beside it. (The old bracket sat at local -Z, which for a horizontal laser is BEHIND
        # the body.) The saddle top is keyed off the body's REAL world underside, not clear_aperture.
        body_bottom = min((o.matrix_world @ Vector(c)).z for c in o.bound_box)
        top_z = p.z - MOUNT_DROP                          # the post top dress() leaves under the optic
        sh = 6.0
        saddle_z = body_bottom + 1.0 - sh * 0.5            # saddle top ~1 mm into the body underside
        _bevel(_box(pre + "Saddle_" + nm, (ca * 1.6, ca * 1.2, sh), (p.x, p.y, saddle_z), coll, "clamp"), 0.8, 2)
        sb = saddle_z - sh * 0.5
        if sb - top_z > 0.5:
            _bevel(_cyl(pre + "Stem_" + nm, 4.0, sb - top_z, (p.x, p.y, (top_z + sb) * 0.5), coll, "mount"), 0.5, 1)
        return 2
    if et in {'BEAMSPLITTER', 'PRISM_MIRROR'}:
        # 30 mm cage-cube housing: a closed block the beam TUNNELS through, with large SM1 port
        # apertures on the beam faces (so the cube optic shows through) + four cage-rod bores at the
        # corners on the 30 mm square -- a precision cube mount, not a homemade tray.
        s = ca * 2.6
        body = eg._cube(pre + "CubeBody_" + nm, Vector((s, s, s)), coll)
        body.matrix_world = mw
        body.data.materials.clear(); body.data.materials.append(_MATS["mount"]())
        ap = max(ca * 0.95, 6.0)
        _bore_local(body, mw, (0, 0, 0), ap, s * 2.0, axis='X')      # IN/OUT optical port through the cube
        _bore_local(body, mw, (0, 0, 0), ap, s * 2.0, axis='Y')      # REFLECT port (side face)
        cg = 15.0                                                     # 30 mm cage-rod square
        for oy in (-cg, cg):
            for oz in (-cg, cg):
                _bore_local(body, mw, (0.0, oy, oz), 2.0, s * 2.0, axis='X')
        _bevel(body, 1.0, 2)
        return 1
    if mt == 'ROTATION' or et in {'WAVEPLATE', 'POLARIZER'}:
        # RSP rotation mount: a squat fixed housing + a rotating inner ring nested in front with a
        # visible SEAM between them (the "this rotates" cue), both bored for the optic, plus a small
        # recessed top setscrew socket -- not a donut-on-a-tube with a proud nub.
        body = _ocyl(pre + "RSPhousing_" + nm, max(ca * 1.05, 9.0), 13.0, mw, (0, 0, -1.0), coll, "mount")
        _bore_local(body, mw, (0, 0, 0), ca * 1.0, 30.0, axis='Z')
        _bevel(body, 0.6, 2)
        ring = _ocyl(pre + "RSPring_" + nm, ca * 0.92, 7.0, mw, (0, 0, 4.0), coll, "mount")    # rotating front ring
        _bore_local(ring, mw, (0, 0, 4.0), ca * 0.78, 14.0, axis='Z')
        _bevel(ring, 0.5, 2)
        _ocyl(pre + "RSPset_" + nm, 1.3, 5.0, mw, (0.0, ca * 0.95, 4.0), coll, "hole", axis='Y')  # recessed setscrew
        return 3
    if mt in ('KINEMATIC_2AXIS', 'KINEMATIC_3AXIS', 'GIMBAL') or et == 'MIRROR':
        # KM100/KS1-style kinematic mount: TWIN same-outline plates floating on a visible air gap;
        # the round optic seats flush in the bored front plate; long fine adjuster screws project out
        # the BACK through bushings to a knurled knob; a fixed pivot ball sits at the third corner
        # (the asymmetric 3-point that makes it "kinematic"); standoff springs bridge the gap.
        plate = ca * 2.6
        hp = plate * 0.5
        _bevel(_bored_plate(pre + "KMplate_" + nm, plate, 6.0, ca * 0.95,
                            mw @ Matrix.Translation((0.0, 0.0, -1.0)), coll, "mount"), 0.7, 2)
        _bevel(_obox(pre + "KMback_" + nm, (plate, plate, 7.0), mw, (0, 0, -14.0), coll, "mount"), 0.7, 2)
        # the two actuators act on PERPENDICULAR edges (one drives tilt, one drives pan) -- bottom-
        # centre + right-centre -- pivoting about the OPPOSITE (top-left) corner. They are not on a
        # diagonal. The 3-adjuster (KS1) variant adds a third on the remaining (left) edge.
        e = hp * 0.72
        adj = [("A0", (0.0, -e)), ("A1", (e, 0.0))]
        if mt in ('KINEMATIC_3AXIS', 'GIMBAL'):
            adj.append(("A2", (-e, 0.0)))
        pivot = (-hp * 0.6, hp * 0.6)        # top-left, opposite the bottom+right actuators
        for an, (sx, sy) in adj:
            _ocyl(pre + an + "s_" + nm, 1.5, 34.0, mw, (sx, sy, -16.0), coll, "steel")              # long shaft, out the back
            _ocyl(pre + an + "b_" + nm, 3.2, 5.0, mw, (sx, sy, -14.0), coll, "mount")               # bushing at the rear plate
            _bevel(_ocyl(pre + an + "k_" + nm, 4.2, 6.0, mw, (sx, sy, -33.0), coll, "steel"), 0.9, 2)  # rear knurled knob
        bpy.ops.mesh.primitive_uv_sphere_add(radius=2.2, location=(0.0, 0.0, 0.0))
        _pv = bpy.context.active_object; _pv.name = pre + "KMpivot_" + nm
        _pv.matrix_world = mw @ Matrix.Translation((pivot[0], pivot[1], -8.0))
        _pv.data.materials.clear(); _pv.data.materials.append(_MATS["steel"]())
        eg._link_only(_pv, coll)
        # two standoff springs bridging the gap, set in from the actuator edges
        for an, (sx, sy) in (("S0", (e * 0.5, -e * 0.5)), ("S1", (-e * 0.5, e * 0.5))):
            _ocyl(pre + an + "_" + nm, 1.4, 8.0, mw, (sx, sy, -7.5), coll, "steel")
        return 5 + 3 * len(adj)
    # threaded lens mount (LMR): a substantial BARE-ALUMINIUM cell (the LMR signature is bright 6061,
    # not black anodize), bored for the optic, with a thin retaining ring near the front face.
    body = _ocyl(pre + "Cell_" + nm, ca * 1.5, 12.0, mw, (0, 0, 0), coll, "alu")
    _bore_local(body, mw, (0, 0, 0), ca * 1.0, 26.0, axis='Z')
    _bevel(body, 0.6, 2)
    _ring(pre + "Mount_" + nm, ca * 1.05, ca * 0.08, mw @ Matrix.Translation((0.0, 0.0, 3.0)), coll, "alu")
    return 2


def _post_holder(tag, x, y, board_top_z, post_radius, coll):
    """The vertical support under one optic: a base foot bolted to the board (a cap-screw head shows
    it is fastened, not floating) + a fixed-length post-holder body with a side locking thumbscrew
    (the post slides in and is clamped). The post itself is built by the caller. Returns the count."""
    hr = post_radius * 1.8
    foot, foot_h = 26.0, 12.0
    # rectangular pedestal foot (real PH foot is a chunky block, not a thin disc), bolted DOWN
    # through a counterbored clearance hole (no proud bolt head)
    ft = eg._cube(BENCH_PREFIX + "Base_" + tag, Vector((foot, foot, foot_h)), coll)
    ft.location = (x, y, board_top_z + foot_h * 0.5)
    ft.data.materials.clear(); ft.data.materials.append(_MATS["clamp"]())
    _bore(ft, (x, y, board_top_z + foot_h * 0.5), 3.4, foot_h * 2.5)                  # clearance through-hole
    _bore(ft, (x, y, board_top_z + foot_h - 1.0), 5.6, 4.0)                           # counterbore on the top face
    _bevel(ft, 1.0, 2)
    # bored, slit post-holder tube (a split-tube clamp, not a solid peg): the post slides into the bore
    z_body = board_top_z + foot_h + HOLDER_H * 0.5
    body = _cyl(BENCH_PREFIX + "Holder_" + tag, hr, HOLDER_H, (x, y, z_body), coll, "holder")
    _bore(body, (x, y, z_body + 4.0), post_radius + 0.25, HOLDER_H)                   # coaxial bore, open top
    slit = eg._cube(BENCH_PREFIX + "_slit_" + tag, Vector((1.6, hr * 2.3, HOLDER_H * 0.86)), coll)
    slit.location = (x + hr * 0.55, y, z_body + HOLDER_H * 0.07)
    _diff(body, slit)
    _bevel(body, 0.6, 1)
    # side locking thumbscrew (shaft + knurled head) crossing the slit, clamping the post
    mw = Matrix.Translation((x, y, board_top_z + foot_h + HOLDER_H * 0.70))
    _ocyl(BENCH_PREFIX + "Locks_" + tag, post_radius * 0.3, post_radius * 1.1,
          mw, (hr + post_radius * 0.4, 0.0, 0.0), coll, "steel", axis='X')
    _bevel(_ocyl(BENCH_PREFIX + "Lockh_" + tag, post_radius * 0.7, post_radius * 0.7,
                 mw, (hr + post_radius * 1.05, 0.0, 0.0), coll, "steel", axis='X'), 0.45, 2)
    return 4


def _clamp_fork(tag, x, y, board_top_z, post_radius, coll, away):
    """A clamping fork (Thorlabs CF175 style) anchoring a periscope pillar to the table: a flat slotted
    bar bolted DOWN, extending outboard (along `away` = unit (dx,dy) from beam toward post), with a
    collar gripping the post base. Stiffer than a slip-fit holder -- the real RS99 periscope base."""
    fh = 11.0
    ax, ay = away
    L, W = 64.0, 30.0
    cx = x + ax * (L * 0.5 - post_radius)
    cy = y + ay * (L * 0.5 - post_radius)
    dims = (L, W, fh) if abs(ax) >= abs(ay) else (W, L, fh)
    plate = eg._cube(BENCH_PREFIX + "Fork_" + tag, Vector(dims), coll)
    plate.location = (cx, cy, board_top_z + fh * 0.5)
    plate.data.materials.clear(); plate.data.materials.append(_MATS["clamp"]())
    for t in (0.45, 0.78):                                   # two bolt-down counterbores along the bar
        bx, by = x + ax * (L * t), y + ay * (L * t)
        _bore(plate, (bx, by, board_top_z + fh * 0.5), 3.4, fh * 2.5)
        _bore(plate, (bx, by, board_top_z + fh - 1.0), 5.6, 4.0)
    _bevel(plate, 1.0, 1)
    collar = _cyl(BENCH_PREFIX + "ForkCollar_" + tag, post_radius + 5.0, fh + 12.0,
                  (x, y, board_top_z + (fh + 12.0) * 0.5), coll, "clamp")
    _bevel(collar, 1.0, 1)
    return 2


def _periscope_clamp(tag, ox, oy, pr, tx, ty, z, coll, optic_r=12.5):
    """One RS99 mirror unit: a 360deg post-clamp COLLAR gripping the Ø1" post at this mirror's height +
    a short stout arm that reaches only to the BACK of the mirror mount (it stops ``optic_r`` short of
    the optic centre, so it never crosses the beam at the mirror). A side lock knob shows the clamp is
    fastened to the post."""
    col = _cyl(BENCH_PREFIX + "Clamp_" + tag, pr + 5.0, 18.0, (ox, oy, z), coll, "mount")
    _bevel(col, 0.8, 1)
    dx, dy = tx - ox, ty - oy
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / d, dy / d                                  # unit vector post -> mirror (toward beam)
    start = (ox + ux * pr, oy + uy * pr, z)                 # collar/post edge on the beam side
    back = optic_r + 3.0                                     # stop this far BEHIND the mirror centre
    end = (tx - ux * back, ty - uy * back, z)               # mount back, never the optic face/beam
    if (d - pr - back) > 1.0:                                # only if there is room for a real arm
        _bevel(_rod(BENCH_PREFIX + "Arm_" + tag, start, end, 7.0, coll, "mount", seg=20), 0.6, 1)
    # side locking thumbscrew on the collar, on the far side from the beam (radial)
    axis = 'X' if abs(ux) >= abs(uy) else 'Y'
    s = -1.0 if (ux + uy) >= 0 else 1.0                      # point away from the beam
    mw = Matrix.Translation((ox - ux * (pr + 4.0), oy - uy * (pr + 4.0), z))
    _bevel(_ocyl(BENCH_PREFIX + "Clamplock_" + tag, pr * 0.34, pr * 0.5, mw,
                 (s * abs(ux) * 2.0, s * abs(uy) * 2.0, 0.0), coll, "steel", axis=axis), 0.4, 1)
    return 3


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


def _rod(name, p0, p1, r, coll, matkey, seg=16):
    """A cylinder spanning p0 -> p1 (a cage rod / tube barrel). ``seg`` = radial segments (bump it
    for a big smooth barrel; 16 is plenty for a thin rod)."""
    p0 = Vector(p0); p1 = Vector(p1)
    d = p1 - p0
    L = max(d.length, 1e-6)
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=L, location=(0, 0, 0), vertices=seg)
    o = bpy.context.active_object
    o.name = name
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    o.matrix_world = Matrix.Translation((p0 + p1) * 0.5) @ q.to_matrix().to_4x4()
    o.data.materials.clear(); o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _extrude_profile(name, prof, p0, p1, perp, coll, matkey):
    """Build a constant cross-section bar by extruding a 2-D profile along p0->p1. ``prof`` is a list
    of (s, h): s = offset along ``perp`` (across the bar), h = height above p0's plane (world +Z).
    Used for the dovetail rail (an undercut ridge) and its grooved carrier — real machined profiles,
    not boxes."""
    import bmesh
    p0 = Vector(p0); p1 = Vector(p1); perp = Vector(perp).normalized()
    up = Vector((0.0, 0.0, 1.0))
    axis = p1 - p0
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    base = [bm.verts.new(p0 + perp * s + up * h) for (s, h) in prof]
    face = bm.faces.new(base)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    bmesh.ops.translate(bm, verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)],
                        vec=axis)
    bm.normal_update()
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    o.data.materials.append(_MATS[matkey]())
    eg._link_only(o, coll)
    return o


def _bored_plate(name, side, thick, bore_r, mw, coll, matkey):
    """A square cage plate with a central bore along its thin (axis) direction, so the optic shows
    through it instead of being hidden behind a solid slab. Oriented by ``mw`` (local +Z = axis)."""
    plate = eg._cube(name, Vector((side, side, thick)), coll)
    plate.matrix_world = mw
    bpy.ops.mesh.primitive_cylinder_add(radius=bore_r, depth=thick * 3.0, location=(0, 0, 0), vertices=24)
    bore = bpy.context.active_object
    bore.matrix_world = mw
    m = plate.modifiers.new("bore", 'BOOLEAN')
    m.operation = 'DIFFERENCE'; m.object = bore   # default solver (enum names vary across 4.2/5.x)
    bpy.context.view_layer.objects.active = plate
    bpy.ops.object.modifier_apply(modifier=m.name)
    _bm = bore.data
    bpy.data.objects.remove(bore, do_unlink=True)
    if _bm.users == 0:
        bpy.data.meshes.remove(_bm)
    plate.data.materials.clear(); plate.data.materials.append(_MATS[matkey]())
    return plate


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
    # a bored cage plate at each member: square frame transverse to the axis with a central
    # aperture so the optic shows through (a real cage plate, not a solid slab). Rods pass through
    # the frame material at the corners.
    rot = Matrix(((u.x, v.x, axis.x, 0.0), (u.y, v.y, axis.y, 0.0),
                  (u.z, v.z, axis.z, 0.0), (0.0, 0.0, 0.0, 1.0)))
    for j, m in enumerate(members):
        ca = max(getattr(m.optics, "clear_aperture", 10.0), 6.0)
        _bored_plate("%sCagePlate_%s_%d" % (BENCH_PREFIX, tag, j),
                     sep * 1.3, 8.9, ca, Matrix.Translation(m.matrix_world.translation) @ rot,
                     coll, "mount")
        n += 1
    # one post under the cage centroid, to beam height (foot + holder + thumbscrew + post)
    post_top_z = centroid.z - MOUNT_DROP
    h = max(post_top_z - board_top_z, 1.0)
    nh = _post_holder("cage_" + tag, centroid.x, centroid.y, board_top_z, post_radius, coll)
    _cyl("%sCagePost_%s" % (BENCH_PREFIX, tag), post_radius, h,
         (centroid.x, centroid.y, board_top_z + h * 0.5), coll, "post")
    return n + nh + 1


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


# ---------------------------------------------------------------------------
# Lens-tube systems (SM05 / SM1 / SM2): one barrel holds an in-line optic stack
# ---------------------------------------------------------------------------
# An SM lens tube is a black-anodized threaded barrel; several in-line optics drop into the bore and
# the whole stack mounts once. Members are grouped by (support_system, tube_id); they share one
# barrel + one post instead of an individual post each. (thread, major Ø, optic-seat bore Ø) in mm.
_TUBE_SPEC = {'TUBE_SM05': ('SM05', 13.59, 12.7), 'TUBE_SM1': ('SM1', 26.29, 25.4),
              'TUBE_SM2': ('SM2', 51.69, 50.8)}


def tube_groups(scene):
    """Map (support_system, tube_id) -> [member optics] for every tube-mounted element."""
    groups = {}
    for o in _optical_objects(scene):
        ss = getattr(o.optics, "support_system", 'POST')
        if ss in _TUBE_SPEC:
            groups.setdefault((ss, getattr(o.optics, "tube_id", "") or ""), []).append(o)
    return groups


def _tube_geom(members):
    """Shared tube geometry (thread, diameters, axis, centroid, end projections) for builder + info."""
    name, major, bore = _TUBE_SPEC[members[0].optics.support_system]
    axis = _cage_axis(members)
    cs = [m.matrix_world.translation for m in members]
    centroid = sum(cs, Vector((0.0, 0.0, 0.0))) / len(cs)
    ts = [(c - centroid).dot(axis) for c in cs]
    margin = max(major * 0.45, 8.0)
    return name, major, bore, axis, centroid, min(ts) - margin, max(ts) + margin


def _build_tube(scene, members, board_top_z, coll, post_radius, tag):
    """One lens-tube barrel: a hollow black-anodized pipe spanning the members + a retaining ring at
    each end, on one post. Optics sit inside the bore and show at the open ends."""
    name, major, bore, axis, centroid, t0, t1 = _tube_geom(members)
    od = major + 4.0
    p0 = centroid + axis * t0
    p1 = centroid + axis * t1
    barrel = _rod("%sTube_%s" % (BENCH_PREFIX, tag), p0, p1, od * 0.5, coll, "post", seg=56)
    inner = _rod("%sTubebore_%s" % (BENCH_PREFIX, tag), p0 - axis * 3.0, p1 + axis * 3.0, bore * 0.5, coll, "post", seg=56)
    m = barrel.modifiers.new("bore", 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = inner
    bpy.context.view_layer.objects.active = barrel
    bpy.ops.object.modifier_apply(modifier=m.name)
    _im = inner.data
    bpy.data.objects.remove(inner, do_unlink=True)
    if _im.users == 0:
        bpy.data.meshes.remove(_im)
    _bevel(barrel, 0.6, 1)
    # (no proud end ring: a real SM retaining ring seats flush *inside* the bore against the optic;
    # a collar sticking out of the mouth just reads as a mystery part, so the barrel ends open.)
    # one post under the barrel centroid, to beam height
    post_top_z = centroid.z - MOUNT_DROP
    h = max(post_top_z - board_top_z, 1.0)
    nh = _post_holder("tube_" + tag, centroid.x, centroid.y, board_top_z, post_radius, coll)
    _cyl("%sTubePost_%s" % (BENCH_PREFIX, tag), post_radius, h,
         (centroid.x, centroid.y, board_top_z + h * 0.5), coll, "post")
    return 3 + nh + 1


def tube_info(scene):
    """Lens-tube assemblies as data for get_state: id, thread, inner Ø, length, axis, members."""
    if not is_dressed(scene):
        return []
    out = []
    for (ss, tid), members in tube_groups(scene).items():
        name, major, bore, axis, centroid, t0, t1 = _tube_geom(members)
        out.append({
            "id": tid or ss.lower(), "thread": name,
            "inner_dia_mm": round(bore, 3), "outer_dia_mm": round(major + 4.0, 3),
            "length_mm": round(t1 - t0, 2),
            "axis": [round(axis.x, 4), round(axis.y, 4), round(axis.z, 4)],
            "members": [m.name for m in members],
        })
    return out


# ---------------------------------------------------------------------------
# Rail systems (RLA dovetail): a continuous track + a carrier + post under each member
# ---------------------------------------------------------------------------
RAIL_W = 19.1   # RLA dovetail rail width (mm)
RAIL_H = 13.0


def rail_groups(scene):
    """Map rail_id -> [member optics] for every rail-mounted element."""
    groups = {}
    for o in _optical_objects(scene):
        if getattr(o.optics, "support_system", 'POST') == 'RAIL':
            groups.setdefault(getattr(o.optics, "rail_id", "") or "", []).append(o)
    return groups


def _rail_axis_xy(members):
    """The rail direction in the board plane (the members' XY line)."""
    cs = [m.matrix_world.translation for m in members]
    if len(cs) >= 2:
        d = Vector((cs[-1].x - cs[0].x, cs[-1].y - cs[0].y, 0.0))
        if d.length > 1e-6:
            return d.normalized()
    return Vector((1.0, 0.0, 0.0))


def rail_geom(members):
    """(axis_xy, centroid_xy, projections) shared by the builder, info and place_on_rail."""
    ax = _rail_axis_xy(members)
    cs = [m.matrix_world.translation for m in members]
    cxy = sum((Vector((c.x, c.y, 0.0)) for c in cs), Vector((0.0, 0.0, 0.0))) / len(cs)
    ts = [(Vector((c.x, c.y, 0.0)) - cxy).dot(ax) for c in cs]
    return ax, cxy, ts


def _build_rail(scene, members, board_top_z, coll, post_radius, tag):
    """A dovetail rail on the board along the members' line, a carrier under each member, and its
    post rising from the carrier to the optic + the member's mount silhouette."""
    ax, cxy, ts = rail_geom(members)
    perp = Vector((-ax.y, ax.x, 0.0))
    margin = 28.0
    half = 0.5 * (max(ts) - min(ts)) + margin
    mid = Vector((cxy.x, cxy.y, board_top_z)) + ax * (0.5 * (max(ts) + min(ts)))
    hw = RAIL_W * 0.5    # 9.55
    # RLA-style dovetail bar: a narrow base neck flaring to a WIDER top (the overhang the carrier
    # hooks under) so a carrier can slide along but not lift off.
    rail_prof = [(-7.0, 0.0), (7.0, 0.0), (7.0, 2.5), (hw, 4.5),
                 (hw, 9.5), (-hw, 9.5), (-hw, 4.5), (-7.0, 2.5)]
    rail = _extrude_profile(BENCH_PREFIX + "Rail_" + tag, rail_prof,
                            mid - ax * half, mid + ax * half, perp, coll, "holder")
    _bevel(rail, 0.5, 1)
    n = 1
    carrier_top = board_top_z + 18.0
    cl = 12.0   # carrier half-length along the rail axis
    # carrier: a chunky block that WRAPS the rail (a dovetail groove hooking under the overhang) with
    # a top post seat -- and a front locking thumbscrew that clamps it to the rail (the missing screw).
    car_prof = [(-13.0, 0.0), (-13.0, 18.0), (13.0, 18.0), (13.0, 0.0),
                (7.5, 0.0), (7.5, 2.0), (10.05, 4.0), (10.05, 10.0),
                (-10.05, 10.0), (-10.05, 4.0), (-7.5, 2.0), (-7.5, 0.0)]
    for i, m in enumerate(members):
        c = m.matrix_world.translation
        t = (Vector((c.x, c.y, 0.0)) - cxy).dot(ax)
        cc = Vector((cxy.x, cxy.y, board_top_z)) + ax * t
        _bevel(_extrude_profile(BENCH_PREFIX + "Carrier_%s_%d" % (tag, i), car_prof,
                                cc - ax * cl, cc + ax * cl, perp, coll, "clamp"), 0.6, 1)
        # front locking thumbscrew (shaft + knurled knob) clamping the carrier to the rail
        sp = Vector((cc.x, cc.y, board_top_z + 10.0)) + perp * 12.5
        _rod(BENCH_PREFIX + "RailLocks_%s_%d" % (tag, i), sp, sp + perp * 6.0, 1.6, coll, "post")
        _bevel(_rod(BENCH_PREFIX + "RailLockh_%s_%d" % (tag, i), sp + perp * 6.0, sp + perp * 10.0,
                    3.4, coll, "mount", seg=20), 0.6, 1)
        post_top_z = c.z - MOUNT_DROP
        h = max(post_top_z - carrier_top, 1.0)
        _cyl(BENCH_PREFIX + "RailPost_%s_%d" % (tag, i), post_radius, h,
             (c.x, c.y, carrier_top + h * 0.5), coll, "post")
        n += 4 + _build_mount(m, coll, 100 + i)   # 100+ avoids name clash with the free-loop indices
    return n


def rail_info(scene):
    """Rail assemblies as data for get_state: id, family, width, length, axis, carriers (element + s)."""
    if not is_dressed(scene):
        return []
    out = []
    for rid, members in rail_groups(scene).items():
        ax, cxy, ts = rail_geom(members)
        tmin = min(ts)
        out.append({
            "id": rid or "rail", "family": "RLA", "width_mm": RAIL_W,
            "length_mm": round((max(ts) - min(ts)) + 56.0, 2),
            "axis": [round(ax.x, 4), round(ax.y, 4), 0.0],
            "carriers": [{"element": m.name, "s_mm": round(t - tmin, 2)} for m, t in zip(members, ts)],
        })
    return out


def validate(scene):
    """Geometric sanity check on the dressed bench -- the programmatic 'eyes' on the assembly AND a
    hard constraint gate, since a render can't be trusted to catch a physically-absurd config. Returns
    a list of {kind, element, detail} invariant violations (empty list == valid):
      - mount_below_holder: a post-mounted optic sits at/under its post-holder top (the mount would be
        BELOW the thing holding it -- absurd; caught the periscope lower-mirror bug)
      - post_overlap: two support posts/pillars collide (coaxial / overlapping supports)
      - beam_through_post: a support post sits on a vertical beam axis
      - interpenetration: ANY two parts from different support clusters actually interpenetrate -- a real
        Blender mesh-overlap (BVHTree) check, so it catches mount/holder/base/optic collisions the cheap
        post-distance proxies above miss (e.g. two mounts placed too close so their bodies pass through).
    Use it after dress() (regression gate + get_state['warnings']) to KNOW the geometry is valid."""
    # the penta-prism deflection AND parasitic-etalon invariants are pure BEAM-physics properties (a trace /
    # port-geometry post-pass), independent of bench DRESSING -- run them even on an undressed bench so a
    # broken routing-prism fold or an accidental Fabry-Perot is always caught.
    if not is_dressed(scene):
        return _penta_deflection_issues(scene) + _parasitic_etalon_issues(scene)
    elems = _optical_objects(scene)
    if not elems:
        return _penta_deflection_issues(scene) + _parasitic_etalon_issues(scene)
    _bh, _ref, board_top_z = _vertical_chain(scene, elems)
    holder_top = board_top_z + BASE_H + HOLDER_H
    grouped = set()
    for members in (list(cage_groups(scene).values()) + list(tube_groups(scene).values())
                    + list(rail_groups(scene).values())):
        grouped.update(m.name for m in members)
    issues = []
    # 1. every POST-mounted optic must clear its holder top (mount above the holder, not inside/below)
    for o in elems:
        if o.name in grouped:
            continue                                  # cage/tube/rail mount differently
        z = o.matrix_world.translation.z
        if z < holder_top - 1.0:
            issues.append({"kind": "mount_below_holder", "element": o.name,
                           "detail": "optic z=%.1f below holder top %.1f" % (z, holder_top)})
    # 2. no two support posts/pillars collide -- compare against EACH post's real radius (read from its
    #    bounding box), not a fixed Ø1/2" guess, so a Ø1" pillar or a fat cage rod is judged correctly.
    posts = [ob for ob in scene.objects
             if any(ob.name.startswith(BENCH_PREFIX + p)
                    for p in ("Post_", "CagePost_", "TubePost_"))]
    def _r(ob):                                          # post radius from its (axis-aligned) footprint
        d = ob.dimensions
        return max(d.x, d.y) * 0.5
    for a in range(len(posts)):
        for b in range(a + 1, len(posts)):
            pa, pb = posts[a].matrix_world.translation, posts[b].matrix_world.translation
            dist = ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5
            clear = 1.1 * (_r(posts[a]) + _r(posts[b]))  # touching radii + 10% breathing room
            if dist < clear:
                issues.append({"kind": "post_overlap",
                               "element": "%s | %s" % (posts[a].name, posts[b].name),
                               "detail": "posts %.1f mm apart, need >=%.1f (collision)" % (dist, clear)})
    # 3. a vertical beam (two optics at one xy, different z) must run through clear air, not through a
    #    support post: a coaxial post would sit IN the beam. Caught the periscope pillar-in-beam bug.
    for i in range(len(elems)):
        for j in range(i + 1, len(elems)):
            a = elems[i].matrix_world.translation
            b = elems[j].matrix_world.translation
            if ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 >= 8.0:
                continue                                  # not stacked -> no vertical leg between them
            if abs(a.z - b.z) <= VERTICAL_STACK_MM:
                continue
            z0, z1 = sorted((a.z, b.z))
            for p in posts:
                t = p.matrix_world.translation
                if ((a.x - t.x) ** 2 + (a.y - t.y) ** 2) ** 0.5 >= _r(p):
                    continue                              # post is off the beam axis -> clear
                pz0 = t.z - p.dimensions.z * 0.5
                pz1 = t.z + p.dimensions.z * 0.5
                if min(z1, pz1) - max(z0, pz0) > 2.0:     # post body overlaps the vertical beam span
                    issues.append({"kind": "beam_through_post", "element": p.name,
                                   "detail": "post on vertical beam axis (%.0f,%.0f) z[%.0f..%.0f]"
                                             % (a.x, a.y, z0, z1)})
                    break
    # 4. real mesh-level collision: any two parts from DIFFERENT support clusters that interpenetrate
    issues += _interpenetration_issues(scene)
    # 5. penta-prism deflection invariant: a penta prism MUST deflect the beam by exactly 90 deg, and that
    #    deflection is INVARIANT under whole-prism tilt (its defining property -- two mirrors at a fixed 45 deg
    #    dihedral rotate any in-plane ray by 2*45 = 90 deg). If a penta in the scene is traced at anything but
    #    90 deg, its fold geometry is broken -- flag it (the routing-prism analogue of the periscope invariants).
    issues += _penta_deflection_issues(scene)
    # 6. parasitic-etalon invariant: any two DISTINCT flat partial-reflector plates whose faces sit
    #    near-parallel across an air gap form an ACCIDENTAL Fabry-Perot the user didn't design -- flag it.
    issues += _parasitic_etalon_issues(scene)
    return issues


# --- A11: parasitic (accidental) Fabry-Perot etalon detection ----------------
# An UNWANTED etalon forms when two near-parallel partial reflectors face each other across a gap (two
# uncoated windows, or a stray flat downstream of another). It imprints a spectral ripple (FSR) the user
# never designed -- distinct from the intentional CAVITY element. A11 ONLY finds the geometry (a parallel
# pair + the spacing L) and feeds L + R into the ALREADY-VERIFIED Fabry-Perot kernels
# physics.cavity_fsr_nm (FSR = lambda^2/(2 n L)) and physics.cavity_finesse (F = pi*sqrt(R)/(1-R)) -- it
# introduces NO new formula (both are __main__ self-tested in physics.py; see C12). A WEDGED surface
# (normals tilted past PARALLEL_TOL_DEG, e.g. a 30-arcmin wedge) breaks the parallel test, so the flag
# auto-clears -- exactly how a real bench KILLS etalon fringes with wedged windows.

# Flat transmissive partial reflectors: a plane glass plate whose front/back faces back-reflect a Fresnel
# ghost (R>0). LENS is deliberately EXCLUDED -- a lens has CURVED faces (no flat-flat etalon) and relay
# lenses are intentional; CAVITY is excluded too (its two mirrors are the DESIGNED Fabry-Perot, not a
# parasite). These mirror the tracer's A9 ghost-bearing transmissive faces (LENS/PASSTHROUGH/FILTER/
# ATTENUATOR), minus the curved LENS.
PARASITIC_PLATE_TYPES = ('PASSTHROUGH', 'FILTER', 'ATTENUATOR')
PARALLEL_TOL_DEG = 0.5        # normals within this of parallel/anti-parallel -> an etalon pair


def _plate_reflectance(op):
    """Per-face power reflectance R of a flat transmissive plate (the parasitic Fresnel back-reflection),
    reusing the SAME A9 kernel the tracer debits with: ar_reflectance when AR-coated, else the verified
    physics.surface_reflectance(1, n) normal-incidence floor (~0.04 for uncoated air<->glass)."""
    from . import physics
    if getattr(op, 'ar_coated', False):
        return min(max(getattr(op, 'ar_reflectance', 0.0025), 0.0), 1.0)
    n2 = max(getattr(op, 'refractive_index', 1.5168), 1.0)
    return physics.surface_reflectance(1.0, n2)


def _parasitic_etalon_issues(scene, tol_deg=PARALLEL_TOL_DEG):
    """Flag accidental Fabry-Perot etalons: every PAIR of DISTINCT flat partial-reflector plates whose
    optical-axis faces are parallel/anti-parallel within ``tol_deg`` AND both have R>0. For such a pair the
    gap L is the spacing between the two plates measured ALONG the shared normal (the projection of the
    center-to-center vector onto the normal); the flagged ripple is fsr_nm = cavity_fsr_nm(lambda, L, n=1)
    and finesse = cavity_finesse(sqrt(R1*R2)) (the effective two-mirror reflectance) -- BOTH reused as-is,
    no new physics. Read-only (a port-geometry post-pass on world normals/positions via matrix_world).

    A WEDGE / tilt past ``tol_deg`` between the two plates breaks the parallel test, so the flag clears --
    the real-bench trick for killing etalon fringes. The intentional CAVITY element is NOT a candidate, so
    its designed Fabry-Perot is never double-flagged. The thick-plate SELF-etalon (one plate's own two
    faces) is treated as the element's intentional substrate, not a parasite -- A11 fires only on an
    ACCIDENTAL pairing of two SEPARATE plates."""
    from . import physics, geometry
    plates = [o for o in _optical_objects(scene)
              if getattr(o.optics, 'element_type', '') in PARASITIC_PLATE_TYPES]
    if len(plates) < 2:
        return []
    wl = float(getattr(scene.optics, 'wavelength', 632.8) or 632.8)
    # one representative flat face per plate: its IN port (world center + world normal). The plate's faces
    # are parallel to each other, so the IN normal is the plate's surface orientation.
    faces = []
    for o in plates:
        op = o.optics
        ip = _find_optics_port(op, 'IN')
        if ip is None:
            continue
        R = _plate_reflectance(op)
        if R <= 0.0:
            continue
        center = geometry.world_port(o, ip.local_position)
        nrm = geometry.world_normal(o, ip.local_normal)
        faces.append((o, center, nrm, R))
    out = []
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            oi, ci, ni, Ri = faces[i]
            oj, cj, nj, Rj = faces[j]
            cosang = max(-1.0, min(1.0, ni.dot(nj)))
            ang = math.degrees(math.acos(abs(cosang)))        # 0 deg == parallel OR anti-parallel
            if ang > tol_deg:
                continue                                       # wedged/tilted pair -> not an etalon
            # gap L = |center-to-center vector projected onto the shared (averaged) normal|
            sep = cj - ci
            L = abs(sep.dot(ni.normalized()))
            if L <= 1e-6:
                continue                                       # coincident faces -> no cavity
            L_mm = L
            Reff = math.sqrt(max(Ri * Rj, 0.0))                # effective two-mirror reflectance
            fsr = physics.cavity_fsr_nm(wl, L_mm, 1.0)         # REUSE verified FSR (air gap, n=1)
            fin = physics.cavity_finesse(Reff)                 # REUSE verified finesse
            out.append({"kind": "parasitic_etalon",
                        "element": "%s | %s" % (oi.name, oj.name),
                        "detail": ("accidental Fabry-Perot: %s & %s near-parallel (%.3f deg) %.2f mm apart "
                                   "-> spectral ripple FSR=%.4f nm, finesse=%.2f (R_eff=%.4f). "
                                   "Wedge/tilt one plate >%.2f deg to kill it."
                                   % (oi.name, oj.name, ang, L_mm, fsr, fin, Reff, tol_deg)),
                        "fsr_nm": fsr, "finesse": fin, "gap_mm": L_mm,
                        "angle_deg": ang, "severity": "WARN"})
    return out


def _find_optics_port(op, role):
    """First port of ``op`` with the given role (a thin local helper so optomech doesn't import the
    tracer's _find_port just for the etalon port lookup)."""
    for p in op.ports:
        if p.role == role:
            return p
    return None


def _penta_deflection_issues(scene, tol_deg=1e-2):
    """For every PENTA routing prism in the scene, trace the chief ray through it and assert the input->output
    deflection is 90 deg (the penta invariant). Returns {kind:'penta_deflection'} issues for any that deviate.
    Read-only (a trace post-pass); the deflection is a fixed product of the verified reflection law."""
    import math
    from mathutils import Vector
    from . import tracer
    pentas = [o for o in _optical_objects(scene)
              if getattr(o.optics, 'element_type', '') == 'PRISM'
              and getattr(o.optics, 'prism_type', '') == 'PENTA']
    if not pentas:
        return []
    try:
        segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                                  max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    except Exception:
        return []
    out = []
    for p in pentas:
        ins = [s for s in segs if s.get("to") == p.name]
        exs = [s for s in segs if s.get("from") == p.name and s.get("kind") == "TRANSMIT"]
        if not ins or not exs:
            continue
        din = (Vector(ins[0]["p2"]) - Vector(ins[0]["p1"]))
        dout = (Vector(exs[-1]["p2"]) - Vector(exs[-1]["p1"]))
        if din.length < 1e-9 or dout.length < 1e-9:
            continue
        defl = math.degrees(math.acos(max(-1.0, min(1.0, din.normalized().dot(dout.normalized())))))
        if abs(defl - 90.0) > tol_deg:
            out.append({"kind": "penta_deflection", "element": p.name,
                        "detail": "penta deflects %.4f deg (must be 90 deg; fold geometry broken)" % defl})
    return out


def validate_all(scene):
    """validate() (geometric/mechanical invariants on the dressed bench) PLUS the
    Wave-1 beam-physics error-detection diagnostics (diagnostics.run_diagnostics:
    beam_clipped / vignetting / dark_detector / orphan_source / energy_violation /
    mount_limit). Additive: validate() itself is unchanged (still the hard geometric
    gate), this is the clearly-named adjacent call that surfaces both layers at once.

    Returns {"geometry": [...], "beam": [...]} where each list is the usual
    {kind, element, detail} dicts (the beam list also carries a `severity`). The
    beam diagnostics are pure READ-ONLY post-passes over the trace -- they never move
    the geometry or change the ray path."""
    from . import diagnostics
    return {"geometry": validate(scene), "beam": diagnostics.run_diagnostics(scene)}


def _own_new(coll, before, owner, optics=()):
    """Tag every bench object created since the `before` snapshot (and the given member optics) with a
    support-cluster `owner` id. The interpenetration check treats one cluster's parts (a post + its
    holder + its mount; a periscope's shared pillar + both clamps; a cage's rods + plates + members) as
    designed-to-touch, and only flags collisions BETWEEN clusters. The shared breadboard / feet / holes
    stay untagged (owner == None) so nothing is flagged for resting on the board."""
    for o in coll.objects:
        if o not in before:
            o["oa_owner"] = owner
    for o in optics:
        o["oa_owner"] = owner


def _interpenetration_issues(scene, min_faces=2):
    """Real mesh-level collision check using Blender's true geometry (mathutils BVHTree.overlap), not a
    distance proxy. Builds a BVH tree per owned mesh (bench hardware + optics, each carrying its
    `oa_owner` support-cluster tag) and reports each pair of DIFFERENT clusters whose meshes actually
    interpenetrate. Same-cluster contact is designed and skipped; the untagged board/feet/holes are
    skipped. Deduped per cluster-pair so one collision is one issue. This is what makes the validator
    actually 'block' on a collision the post-distance checks above never see."""
    import bmesh
    from mathutils.bvhtree import BVHTree
    try:
        deps = bpy.context.evaluated_depsgraph_get()
    except Exception:
        return []
    trees = []
    for o in scene.objects:
        if o.type != 'MESH' or o.get("oa_owner") is None or o.name.startswith("BEAM_"):
            continue
        bm = bmesh.new()
        try:
            bm.from_object(o, deps)
        except Exception:
            bm.free(); continue
        if bm.faces:
            bm.transform(o.matrix_world)
            trees.append((o.name, o["oa_owner"], BVHTree.FromBMesh(bm)))
        bm.free()
    issues, seen = [], set()
    for i in range(len(trees)):
        na, oa, ta = trees[i]
        for j in range(i + 1, len(trees)):
            nb, ob, tb = trees[j]
            if oa == ob:
                continue                                  # same support cluster -> designed to touch
            key = tuple(sorted((str(oa), str(ob))))
            if key in seen:
                continue
            ov = ta.overlap(tb)
            if len(ov) >= min_faces:
                seen.add(key)
                issues.append({"kind": "interpenetration",
                               "element": "%s | %s" % (na, nb),
                               "detail": "meshes interpenetrate (%d face hits; clusters %s / %s)"
                                         % (len(ov), oa, ob)})
    return issues


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
    for o in elems:                                  # clear any stale support-cluster tag from a prior dress
        if "oa_owner" in o:
            del o["oa_owner"]
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
    board = _box(BENCH_PREFIX + "Breadboard",
                 (x1 - x0 + 2 * margin, y1 - y0 + 2 * margin, th),
                 ((x0 + x1) * 0.5, (y0 + y1) * 0.5, board_top_z - th * 0.5),
                 coll, "board")
    # bore real recessed holes into the board; the dark hole discs then sit at the pocket FLOOR so
    # each hole reads as a shadowed recess, not a painted dot (falls back to flat discs above the cap)
    bored = _bore_grid(board, x0, y0, nx, ny, pitch, board_top_z, _thread_hole_r(pitch))
    _hole_grid(BENCH_PREFIX + "Holes", x0, y0, nx, ny, pitch,
               board_top_z - 2.45 if bored else board_top_z, coll, hole_r=_thread_hole_r(pitch))
    # four feet so the breadboard sits on a surface instead of floating in the void
    cxb = (x0 + x1) * 0.5; cyb = (y0 + y1) * 0.5
    fx = (x1 - x0) * 0.5 + margin - pitch * 0.5
    fy = (y1 - y0) * 0.5 + margin - pitch * 0.5
    foot_h = 20.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            _bevel(_cyl(BENCH_PREFIX + "Foot_%d%d" % (sx > 0, sy > 0), pitch * 0.34, foot_h,
                        (cxb + sx * fx, cyb + sy * fy, board_top_z - th - foot_h * 0.5 + 0.5),
                        coll, "post"), 1.2, 1)
    n = 6
    # cage-mounted optics ride shared rods + one cage post; tube-mounted optics share one barrel +
    # one post; everything else gets its own post.
    groups = cage_groups(scene)
    tubes = tube_groups(scene)
    rails = rail_groups(scene)
    grouped = {m.name for members in groups.values() for m in members}
    grouped |= {m.name for members in tubes.values() for m in members}
    grouped |= {m.name for members in rails.values() for m in members}
    # Group free optics by their board (x,y): optics STACKED at the same xy (e.g. a periscope's two
    # fold mirrors) share ONE pillar to the tallest one, instead of two coaxial posts colliding.
    stacks = {}
    for i, o in enumerate(elems):
        if o.name in grouped:
            continue
        p = o.matrix_world.translation
        stacks.setdefault((round(p.x / 3.0), round(p.y / 3.0)), []).append((i, o))
    for members in stacks.values():
        before = set(coll.objects)                       # snapshot -> tag this cluster's new hardware below
        members.sort(key=lambda io: io[1].matrix_world.translation.z)
        i_top, o_top = members[-1]                       # the highest optic sets the pillar height
        pt = o_top.matrix_world.translation
        zlo = members[0][1].matrix_world.translation.z
        vfold = (pt.z - zlo) > VERTICAL_STACK_MM         # >1 deck at one xy => a vertical beam runs
        if vfold:
            # Vertical fold (periscope): a beam travels UP the shared xy between the decks. A post on
            # that axis would sit IN the beam -- so the pillar is pushed PILLAR_OFFSET off-axis (out of
            # the fold plane) and each mirror mount cantilevers back onto the beam on a short arm. This
            # is the real periscope assembly; a coaxial post here is a (render-invisible) blocked beam.
            # offset perpendicular to the in-plane beam legs: the horizontal beams leave this stack
            # toward the other optics, so push the pillar across that axis. Spread of the other optics
            # in x vs y tells us which way the legs run (periscope: source+detector along Y -> push X).
            others = [e.matrix_world.translation for e in elems
                      if ((e.matrix_world.translation.x - pt.x) ** 2
                          + (e.matrix_world.translation.y - pt.y) ** 2) ** 0.5 > 8.0]
            sx = sum(abs(o.x - pt.x) for o in others)
            sy = sum(abs(o.y - pt.y) for o in others)
            dirx, diry = (1.0, 0.0) if sy >= sx else (0.0, 1.0)
            ox, oy = pt.x + dirx * PILLAR_OFFSET, pt.y + diry * PILLAR_OFFSET
            h = max(pt.z - board_top_z, 1.0)             # one Ø1" post reaches up to the top deck
            # RS99 periscope: a clamping fork anchors the single Ø1" post; each mirror rides a post-clamp
            # collar that reaches back onto the beam axis (NOT a thin spider-arm on a slip-fit holder).
            nf = _clamp_fork("%02d" % i_top, ox, oy, board_top_z, POST_RADIUS_TALL, coll, (dirx, diry))
            _cyl(BENCH_PREFIX + "Post_%02d" % i_top, POST_RADIUS_TALL, h,
                 (ox, oy, board_top_z + h * 0.5), coll, "post")
            n += nf + 1
            for i, o in members:
                op = o.matrix_world.translation
                opr = getattr(o.optics, "clear_aperture", 0.0) or 12.5
                n += _periscope_clamp("%02d" % i, ox, oy, POST_RADIUS_TALL, op.x, op.y, op.z, coll, opr)
                n += _build_mount(o, coll, i)
        else:
            h = max((pt.z - MOUNT_DROP) - board_top_z, 1.0)
            # a tall/raised mount (high optic) rides a fatter Ø1" pillar, not a thin Ø1/2" stick --
            # the real bench move for stiffness; short mounts keep the Ø1/2" post.
            pr = POST_RADIUS_TALL if h > PILLAR_OVER_MM else post_radius
            # one base foot + post-holder + pillar (post top under the optic)
            nh = _post_holder("%02d" % i_top, pt.x, pt.y, board_top_z, pr, coll)
            _cyl(BENCH_PREFIX + "Post_%02d" % i_top, pr, h,
                 (pt.x, pt.y, board_top_z + h * 0.5), coll, "post")
            n += nh + 1
            for i, o in members:                         # each optic in the stack gets its own mount
                n += _build_mount(o, coll, i)
        _own_new(coll, before, "stk%02d" % i_top, [o for _i, o in members])
    for gi, members in enumerate(groups.values()):
        before = set(coll.objects)
        n += _build_cage(scene, members, board_top_z, coll, post_radius, "%02d" % gi)
        _own_new(coll, before, "cage%02d" % gi, members)
    for ti, members in enumerate(tubes.values()):
        before = set(coll.objects)
        n += _build_tube(scene, members, board_top_z, coll, post_radius, "%02d" % ti)
        _own_new(coll, before, "tube%02d" % ti, members)
    for ri, members in enumerate(rails.values()):
        before = set(coll.objects)
        n += _build_rail(scene, members, board_top_z, coll, post_radius, "%02d" % ri)
        _own_new(coll, before, "rail%02d" % ri, members)
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
