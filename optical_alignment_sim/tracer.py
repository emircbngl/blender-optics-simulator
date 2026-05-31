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

import math

import bpy
from bpy.types import Operator
from mathutils import Vector

from . import geometry, physics

EPS = 1e-4
EXTEND_MM = 150.0          # how far an escaping ray is drawn

# overlay reads this; handlers write it
cached_segments = []

# Elements whose beam interaction happens at the REFLECT port plane (not the IN plane).
REFLECTIVE = ('MIRROR', 'PRISM_MIRROR', 'BEAMSPLITTER', 'DICHROIC', 'GRATING', 'RETROREFLECTOR')
# Elements that absorb the beam (no outgoing ray).
TERMINAL = ('DETECTOR', 'PHOTODIODE', 'POWER_METER')


class _Ray:
    __slots__ = ('p1', 'dir', 'power', 'depth', 'from_obj', 'wl', 'kind', 'parent',
                 'jones', 'opl', 'q', 'src_id')

    def __init__(self, p1, d, power, depth, from_obj, wl, kind, parent,
                 jones=None, opl=0.0, q=None, src_id=-1):
        self.p1 = p1
        self.dir = d.normalized()
        self.power = power
        self.depth = depth
        self.from_obj = from_obj
        self.wl = wl
        self.kind = kind
        self.parent = parent
        self.jones = jones          # (Ex, Ey) complex Jones vector (polarization)
        self.opl = opl              # optical path length accumulated up to p1 (mm)
        self.q = q                  # Gaussian complex beam parameter
        self.src_id = src_id        # coherence group (which source this ray came from)


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
    seg_len = (p2 - ray.p1).length
    opl = ray.opl + seg_len                      # free-space (air, n~=1) optical path
    lam_mm = ray.wl * 1.0e-6
    phase = (2.0 * math.pi * opl / lam_mm) if lam_mm > 0.0 else 0.0
    j = ray.jones
    return {
        "p1": ray.p1.copy(), "p2": p2.copy(), "kind": ray.kind,
        "from": ray.from_obj.name if ray.from_obj else None,
        "to": to_obj.name if to_obj else None,
        "power": round(ray.power, 4), "wavelength": ray.wl, "parent": ray.parent,
        "jones": [j[0].real, j[0].imag, j[1].real, j[1].imag] if j else None,
        "opl": opl, "phase": phase, "src_id": ray.src_id,
        "w_mm": physics.beam_radius(ray.q, ray.wl) if ray.q else 0.0,
    }


def _child(ray, E, H, d, power, kind, idx, t, jones=None, q=None):
    """Construct a continuation ray, inheriting polarization/coherence state and
    advancing the optical path length by the segment length ``t``."""
    return _Ray(H, d, power, ray.depth + 1, E, ray.wl, kind, idx,
                jones=ray.jones if jones is None else jones,
                opl=ray.opl + t,
                q=ray.q if q is None else q,
                src_id=ray.src_id)


def _transmission(op, wl):
    """Wavelength-dependent power transmission of a filter / attenuator."""
    if op.element_type == 'ATTENUATOR':
        return 10.0 ** (-op.od)
    ft = op.filt_type
    if ft == 'ND':
        return 10.0 ** (-op.od)
    if ft == 'LP':
        return 1.0 if wl >= op.cut_lo_nm else 0.0
    if ft == 'SP':
        return 1.0 if wl <= op.cut_hi_nm else 0.0
    if ft == 'BP':
        return 1.0 if op.cut_lo_nm <= wl <= op.cut_hi_nm else 0.0
    return 1.0


def _diffract(d, n, wl_nm, lines_per_mm, order):
    """Grating equation in the plane of incidence: sin(theta_m) = sin(theta_i) +
    m*lambda/d, d = 1/lines_per_mm. 0th order -> specular; an evanescent order
    (|sin|>1) returns None so the caller can fall back to specular."""
    if order == 0 or lines_per_mm <= 0.0:
        return geometry.reflect(d, n)
    n_in = n if d.dot(n) < 0.0 else -n              # normal facing the incoming ray
    d_t = d - d.dot(n_in) * n_in
    sin_i = d_t.length
    t_hat = (d_t / sin_i) if sin_i > 1e-9 else n_in.orthogonal().normalized()
    sin_m = sin_i + order * (wl_nm * 1.0e-6) * lines_per_mm
    if abs(sin_m) > 1.0:
        return None
    cos_m = math.sqrt(max(0.0, 1.0 - sin_m * sin_m))
    return (sin_m * t_hat + cos_m * n_in).normalized()


def trace_scene(scene, mode='AUTO', max_segments=64, max_depth=12):
    elems = [o for o in scene.objects
             if getattr(o, "optics", None) and o.optics.is_optical]
    order = _order_list(scene)

    stack = []
    sid = 0
    for src in elems:
        if src.optics.element_type in ('SOURCE', 'FIBER_COLLIMATOR') or src.optics.is_source:
            op = _first_out(src.optics)
            if op is None:
                continue
            sp = src.optics
            if sp.pol_type == 'CIRCULAR':
                j = physics.jones_circular(sp.handedness)
            elif sp.pol_type == 'UNPOL':
                j = physics.jones_unpolarized()
            else:
                j = physics.jones_linear(sp.pol_angle)
            q0 = physics.q_from_waist(max(sp.waist_um, 1.0) * 1.0e-3, sp.wavelength)
            stack.append(_Ray(
                geometry.world_port(src, op.local_position),
                geometry.world_normal(src, op.local_normal),
                1.0, 0, src, sp.wavelength, 'SOURCE', -1,
                jones=j, opl=0.0, q=q0, src_id=sid))
            sid += 1

    segments = []
    guard = 0
    while stack and len(segments) < max_segments and guard < max_segments * 8:
        guard += 1
        ray = stack.pop()
        if ray.depth > max_depth or ray.power < 1e-4:    # keep weak beams (e.g. polarizer extinction floor)
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
        op = E.optics
        J = ray.jones
        if et == 'APERTURE':
            stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
            continue
        if et in ('MIRROR', 'PRISM_MIRROR', 'RETROREFLECTOR'):
            nd = geometry.reflect(ray.dir, sn)
            a = math.sqrt(max(op.reflectivity, 0.0))      # ideal: preserve polarization, scale amplitude
            stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t,
                                jones=physics.scale(J, a) if J else None))
        elif et == 'GRATING':
            nd = _diffract(ray.dir, sn, ray.wl, op.lines_per_mm, op.grating_order)
            if nd is None:
                nd = geometry.reflect(ray.dir, sn)         # evanescent order -> specular
            a = math.sqrt(max(op.reflectivity, 0.0))
            stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t,
                                jones=physics.scale(J, a) if J else None))
        elif et == 'DICHROIC':
            transmit = (ray.wl >= op.cut_nm) if op.pass_type == 'LP' else (ray.wl <= op.cut_nm)
            if transmit:
                stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
            else:
                stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power, 'REFLECT', idx, t))
        elif et == 'BEAMSPLITTER':
            if op.is_pbs and J:                            # polarizing: reflect s (y), transmit p (x)
                Jr = physics.apply(physics.PBS_REFLECT, J)
                Jt = physics.apply(physics.PBS_TRANSMIT, J)
                stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn),
                                    physics.intensity(Jr), 'SPLIT_R', idx, t, jones=Jr))
                stack.append(_child(ray, E, H, ray.dir,
                                    physics.intensity(Jt), 'SPLIT_T', idx, t, jones=Jt))
            else:
                r = op.split_ratio
                stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power * r, 'SPLIT_R', idx, t,
                                    jones=physics.scale(J, math.sqrt(r)) if J else None))
                stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - r), 'SPLIT_T', idx, t,
                                    jones=physics.scale(J, math.sqrt(max(1.0 - r, 0.0))) if J else None))
        elif et == 'POLARIZER' and J:
            Jp = physics.apply(physics.M_polarizer(op.pol_axis_deg, op.extinction), J)
            stack.append(_child(ray, E, H, ray.dir, physics.intensity(Jp), 'TRANSMIT', idx, t, jones=Jp))
        elif et == 'WAVEPLATE' and J:
            Jw = physics.apply(physics.M_waveplate(op.retardance_deg, op.fast_axis_deg), J)
            stack.append(_child(ray, E, H, ray.dir, physics.intensity(Jw), 'TRANSMIT', idx, t, jones=Jw))
        elif et in ('FILTER', 'ATTENUATOR'):
            T = _transmission(op, ray.wl)
            stack.append(_child(ray, E, H, ray.dir, ray.power * T, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(max(T, 0.0))) if J else None))
        else:  # LENS / ISOLATOR / PINHOLE / PASSTHROUGH
            stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))

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
