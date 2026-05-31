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
    if cosi < 0.0:                 # ray hits the back face: flip the normal
        n = -n
        cosi = -d.dot(n)
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
