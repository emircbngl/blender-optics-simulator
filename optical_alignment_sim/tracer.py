"""Sequential geometric ray tracer.

Propagates rays from each SOURCE through the optical elements, reflecting /
refracting / splitting at each interaction surface, until they reach a detector,
escape, or hit the segment/depth budget. The result is a flat list of segment
dicts (the BS tree is encoded via the `parent` index).

The trace reads the *actual* world geometry of each element (via the port world
math in geometry.py), so when a mount is rotated the beam path changes and the
misalignment becomes visible as a broken path - which is exactly what alignment
automation then measures.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from mathutils import Vector

from . import geometry

EPS = 1e-4
EXTEND_MM = 150.0          # how far an escaping ray is drawn

# overlay reads this; handlers write it
cached_segments = []

# Elements whose beam interaction happens at the REFLECT port plane (not the IN plane).
REFLECTIVE = ('MIRROR', 'PRISM_MIRROR', 'BEAMSPLITTER', 'DICHROIC', 'GRATING', 'RETROREFLECTOR')
# Elements that absorb the beam (no outgoing ray).
TERMINAL = ('DETECTOR', 'PHOTODIODE', 'POWER_METER')


class _Ray:
    __slots__ = ('p1', 'dir', 'power', 'depth', 'from_obj', 'wl', 'kind', 'parent')

    def __init__(self, p1, d, power, depth, from_obj, wl, kind, parent):
        self.p1 = p1
        self.dir = d.normalized()
        self.power = power
        self.depth = depth
        self.from_obj = from_obj
        self.wl = wl
        self.kind = kind
        self.parent = parent


def _find_port(props, role):
    for p in props.ports:
        if p.role == role:
            return p
    return None


def _first_in(props):
    return _find_port(props, 'IN')


def _first_out(props):
    return _find_port(props, 'OUT')


def interaction_surface(obj):
    """Return (point, normal, aperture) of the surface the beam interacts with:
    the REFLECT plane for reflective elements, otherwise the IN port plane."""
    props = obj.optics
    if props.element_type in REFLECTIVE:
        rp = _find_port(props, 'REFLECT')
        if rp:
            return (geometry.world_port(obj, rp.local_position),
                    geometry.world_normal(obj, rp.local_normal),
                    rp.clear_aperture or props.clear_aperture)
    ip = _first_in(props)
    if ip:
        return (geometry.world_port(obj, ip.local_position),
                geometry.world_normal(obj, ip.local_normal),
                ip.clear_aperture or props.clear_aperture)
    return None, None, 0.0


def _ray_plane(p0, d, plane_pt, plane_n):
    denom = d.dot(plane_n)
    if abs(denom) < 1e-9:
        return None
    t = (plane_pt - p0).dot(plane_n) / denom
    if t < EPS:
        return None
    return p0 + d * t, t


def _order_list(scene):
    raw = scene.optics.order_csv if getattr(scene, "optics", None) else ""
    return [n.strip() for n in raw.split(",") if n.strip()]


def _find_next(elems, ray, mode, order):
    """Return (t, element, hit_point, surface_normal) for the nearest interaction
    ahead of the ray, or None."""
    candidates = elems
    if mode == 'ORDER' and order:
        if ray.from_obj is not None and ray.from_obj.name in order:
            i = order.index(ray.from_obj.name)
            names = order[i + 1:i + 2]
        else:
            names = order[0:1]
        candidates = [e for e in elems if e.name in names]

    best = None
    for E in candidates:
        if E is ray.from_obj:
            continue
        sp, sn, ca = interaction_surface(E)
        if sp is None:
            continue
        hit = _ray_plane(ray.p1, ray.dir, sp, sn)
        if hit is None:
            continue
        H, t = hit
        off = (H - sp).length
        if off <= max(ca, 0.0) + 1e-3:
            if best is None or t < best[0]:
                best = (t, E, H, sn)
    return best


def _seg(ray, p2, to_obj):
    return {
        "p1": ray.p1.copy(), "p2": p2.copy(), "kind": ray.kind,
        "from": ray.from_obj.name if ray.from_obj else None,
        "to": to_obj.name if to_obj else None,
        "power": round(ray.power, 4), "wavelength": ray.wl, "parent": ray.parent,
    }


def trace_scene(scene, mode='AUTO', max_segments=64, max_depth=12):
    elems = [o for o in scene.objects
             if getattr(o, "optics", None) and o.optics.is_optical]
    order = _order_list(scene)

    stack = []
    for src in elems:
        if src.optics.element_type == 'SOURCE' or src.optics.is_source:
            op = _first_out(src.optics)
            if op is None:
                continue
            stack.append(_Ray(
                geometry.world_port(src, op.local_position),
                geometry.world_normal(src, op.local_normal),
                1.0, 0, src, src.optics.wavelength, 'SOURCE', -1))

    segments = []
    guard = 0
    while stack and len(segments) < max_segments and guard < max_segments * 8:
        guard += 1
        ray = stack.pop()
        if ray.depth > max_depth or ray.power < 1e-3:
            continue

        hit = _find_next(elems, ray, mode, order)
        if hit is None:
            segments.append(_seg(ray, ray.p1 + ray.dir * EXTEND_MM, None))
            continue

        t, E, H, sn = hit
        idx = len(segments)
        segments.append(_seg(ray, H, E))
        et = E.optics.element_type

        if et in TERMINAL:
            continue
        if et == 'APERTURE':
            stack.append(_Ray(H, ray.dir, ray.power, ray.depth + 1, E, ray.wl, 'TRANSMIT', idx))
            continue
        if et in ('MIRROR', 'PRISM_MIRROR', 'GRATING', 'RETROREFLECTOR'):
            nd = geometry.reflect(ray.dir, sn)
            stack.append(_Ray(H, nd, ray.power * E.optics.reflectivity,
                              ray.depth + 1, E, ray.wl, 'REFLECT', idx))
        elif et in ('BEAMSPLITTER', 'DICHROIC'):
            r = E.optics.split_ratio
            stack.append(_Ray(H, geometry.reflect(ray.dir, sn), ray.power * r,
                              ray.depth + 1, E, ray.wl, 'SPLIT_R', idx))
            stack.append(_Ray(H, ray.dir, ray.power * (1.0 - r),
                              ray.depth + 1, E, ray.wl, 'SPLIT_T', idx))
        else:  # LENS / WAVEPLATE / POLARIZER / FILTER / ATTENUATOR / ISOLATOR / PINHOLE / PASSTHROUGH
            stack.append(_Ray(H, ray.dir, ray.power, ray.depth + 1, E, ray.wl, 'TRANSMIT', idx))

    return segments


# --- operators --------------------------------------------------------------

def _tag_redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()


class OPTICS_OT_trace_now(Operator):
    bl_idname = "optics.trace_now"
    bl_label = "Trace Now"
    bl_description = "Recompute the beam path once and show the overlay"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global cached_segments
        scn = context.scene
        cached_segments = trace_scene(scn, mode=scn.optics.trace_mode,
                                      max_segments=scn.optics.max_segments,
                                      max_depth=scn.optics.max_depth)
        from . import overlay
        overlay.enable()
        _tag_redraw()
        self.report({'INFO'}, "Traced %d segments" % len(cached_segments))
        return {'FINISHED'}


class OPTICS_OT_clear_beams(Operator):
    bl_idname = "optics.clear_beams"
    bl_label = "Clear Beam Overlay"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global cached_segments
        cached_segments = []
        _tag_redraw()
        return {'FINISHED'}


_classes = (OPTICS_OT_trace_now, OPTICS_OT_clear_beams)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
