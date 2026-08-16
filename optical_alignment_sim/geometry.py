"""Pure geometry / optics helpers.

No bpy class registration lives here. Functions take Blender objects plus
port-like data (anything with .local_position / .local_normal, or raw sequences)
and return mathutils types. This module is the single source of truth for the
world-space port math that fixes the original "Claude can't see mirror
centers/normals" problem:

    world_pos    = obj.matrix_world @ local_position
    world_normal = (obj.matrix_world.to_3x3() @ local_normal).normalized()

Because local ports are measured relative to the same origin the matrix uses,
this is correct regardless of where the object origin sits (center-of-volume,
a mounting datum, etc.).
"""
from __future__ import annotations

import math
from mathutils import Vector

EPS = 1e-6

# --- unit convention --------------------------------------------------------
# The whole measurement layer reads world coordinates AS MILLIMETRES. That is not a display
# preference: `scale_length` is consulted nowhere in tracer / solvers / alignment /
# diagnostics, so a bench traced at scale_length=1.0 yields a byte-identical trace to the
# same bench at 0.001 -- the numbers are simply reinterpreted as metres by Blender's UI
# while the physics still calls them millimetres.
#
# The consequence is silent and large: a 1" optic is 25.4 units wide, which reads as 25.4 m
# in a metre-scale scene. Rescaling the OBJECT would desynchronise it from the physics (a
# 150 mm arm becomes 0.15 units -> the tracer reads 0.15 mm), so the add-on does not guess.
# It detects the mismatch and says so.
ADDON_SCALE_LENGTH = 0.001          # 1 Blender unit == 1 mm


def mm_per_unit(scene):
    """How many millimetres one Blender unit spans in this scene. Exactly 1.0 on the mm convention.

    The single conversion factor between the scene's units and the millimetres the physics is
    written in. `scale_length` is metres-per-unit, so mm-per-unit is that times 1000: a metre scene
    gives 1000, and the add-on's own 0.001 gives exactly 1 -- which is what keeps the millimetre
    case bit-for-bit unchanged everywhere this is applied.

    It returns 1.0 unless the scene has DECLARED that its unit scale is authoritative, and that
    guard is the load-bearing part. Blender's factory scale_length is 1.0 and this add-on has never
    set it, so a scene reading 1.0 is overwhelmingly one where nobody touched units rather than a
    metre-scale scene. Keying off scale_length alone reinterprets every one of those -- including
    every bench this project's own tests build -- and shrinks it by a thousand. That was measured:
    it broke 20 existing behaviours, one of them a periscope whose vertical fold came out 0.1
    instead of 100. Intent is declared here, never inferred."""
    opt = getattr(scene, "optics", None)
    if not getattr(opt, "scene_units_authoritative", False):
        return 1.0
    sl = getattr(getattr(scene, "unit_settings", None), "scale_length", ADDON_SCALE_LENGTH)
    if not sl or sl <= 0.0:
        return 1.0
    mmpu = float(sl) * 1000.0
    # Snap to exactly 1.0 inside float32 noise. Blender stores scale_length as float32, so writing
    # 0.001 reads back 0.0010000000474974513 and this would return 1.0000000475 -- enough to send a
    # DECLARED millimetre scene down the conversion path and stop it being byte-identical, for a
    # difference that is pure storage precision. Same trap as the scene converter's idempotence.
    return 1.0 if abs(mmpu - 1.0) < 1e-6 else mmpu


def unit_scale_mismatch(scene):
    """None when the scene matches the add-on's mm convention, else a one-line explanation.

    Callers that place geometry should surface this rather than silently dropping a 25 m
    lens into a metre-scale scene."""
    sl = getattr(getattr(scene, "unit_settings", None), "scale_length", ADDON_SCALE_LENGTH)
    if sl is None or abs(sl - ADDON_SCALE_LENGTH) <= 1e-9:
        return None
    factor = sl / ADDON_SCALE_LENGTH
    return ("scene unit scale is %g, but this add-on measures in millimetres (scale_length %g). "
            "Components are built at 1 unit = 1 mm, so they read %gx too large here, and the "
            "trace still treats every distance as mm. Set Scene > Units > Unit Scale to %g and "
            "scale your own models by %g on the way in."
            % (sl, ADDON_SCALE_LENGTH, factor, ADDON_SCALE_LENGTH, factor))

# --- axis helpers -----------------------------------------------------------

# face/axis label -> (component index, sign)
AXES = {
    "+X": (0, 1.0), "-X": (0, -1.0),
    "+Y": (1, 1.0), "-Y": (1, -1.0),
    "+Z": (2, 1.0), "-Z": (2, -1.0),
}


def to_vec(seq) -> Vector:
    return Vector((float(seq[0]), float(seq[1]), float(seq[2])))


def axis_vector(axis: str) -> Vector:
    idx, sign = AXES[axis]
    v = Vector((0.0, 0.0, 0.0))
    v[idx] = sign
    return v


# --- world-space port math (the core fix) -----------------------------------

def world_port(obj, local_position) -> Vector:
    """World-space position of a port given its local position."""
    return obj.matrix_world @ to_vec(local_position)


def world_normal(obj, local_normal) -> Vector:
    """World-space unit normal of a port given its local normal."""
    n = obj.matrix_world.to_3x3() @ to_vec(local_normal)
    if n.length < EPS:
        return Vector((0.0, 0.0, 1.0))
    return n.normalized()


# --- ray optics -------------------------------------------------------------

def reflect(d: Vector, n: Vector) -> Vector:
    """Reflect direction d about surface normal n. Returns a unit vector."""
    n = n.normalized()
    r = d - 2.0 * d.dot(n) * n
    return r.normalized() if r.length > EPS else d.normalized()


def refract_dir(d: Vector, n: Vector, n1: float, n2: float):
    """Snell's law in vector form. Returns refracted unit direction, or None on
    total internal reflection."""
    d = d.normalized()
    n = n.normalized()
    cosi = -d.dot(n)
    if cosi < 0.0:                 # ray exits the medium: flip normal AND swap indices
        n = -n
        cosi = -d.dot(n)
        n1, n2 = n2, n1
    eta = n1 / n2 if n2 != 0.0 else 1.0
    k = 1.0 - eta * eta * (1.0 - cosi * cosi)
    if k < 0.0:
        return None               # total internal reflection
    return (eta * d + (eta * cosi - math.sqrt(k)) * n).normalized()


# --- bounding-box derived ports (for auto-detect, robust to origin offset) ---

def local_bounds(obj):
    """Return (min, max, center) of the object's local-space bounding box."""
    bb = [Vector(c) for c in obj.bound_box]
    mn = Vector((min(c.x for c in bb), min(c.y for c in bb), min(c.z for c in bb)))
    mx = Vector((max(c.x for c in bb), max(c.y for c in bb), max(c.z for c in bb)))
    return mn, mx, (mn + mx) * 0.5


def face_center_local(obj, axis: str) -> Vector:
    """Local-space center of the bbox face on the given axis (e.g. '+Z').

    Robust to off-center origins: starts from the bbox center and pushes out to
    the face plane along the requested axis.
    """
    mn, mx, ctr = local_bounds(obj)
    idx, sign = AXES[axis]
    p = ctr.copy()
    p[idx] = mx[idx] if sign > 0.0 else mn[idx]
    return p


def longest_axis(obj) -> str:
    """Return 'X' / 'Y' / 'Z' for the longest local dimension (optical axis guess)."""
    mn, mx, _ = local_bounds(obj)
    dims = mx - mn
    idx = max(range(3), key=lambda i: dims[i])
    return ("X", "Y", "Z")[idx]


def perpendicular_distance(point: Vector, line_origin: Vector, line_dir: Vector) -> float:
    """Distance from `point` to the infinite line (origin, unit dir)."""
    d = line_dir.normalized()
    v = point - line_origin
    return (v - v.dot(d) * d).length


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
