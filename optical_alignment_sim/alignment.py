"""Alignment automation.

Two parts:

  * refresh_report(scene) - measures, per element, how far the beam misses its
    IN port (position residual) and how far its outgoing ray points away from the
    next element's IN port (angular residual); writes the results + an OK/WARN/BAD
    state and a viewport color.

  * align_element / align_all - a DOF-constrained steering solve. It only turns
    the element's tip/tilt knobs (within their range) to walk the outgoing beam
    onto the next element's IN port. If the target cannot be reached within the
    knob range, it reports "knob range exhausted - move the post (coarse)".
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from mathutils import Vector

from . import geometry, tracer, mounts, physics

COLOR = {
    'OK':      (0.05, 0.80, 0.12, 1.0),
    'WARN':    (1.00, 0.62, 0.05, 1.0),
    'BAD':     (0.90, 0.05, 0.05, 1.0),
    'UNKNOWN': (0.55, 0.55, 0.55, 1.0),
}


def _first(props, role):
    for p in props.ports:
        if p.role == role:
            return p
    return None


def _trace(scene):
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _seg_in(segs, name):
    return next((s for s in segs if s["to"] == name), None)


def _seg_out(segs, name):
    return next((s for s in segs if s["from"] == name
                 and s["kind"] in ('REFLECT', 'TRANSMIT', 'SPLIT_R', 'SPLIT_T', 'SOURCE')), None)


# --- residuals --------------------------------------------------------------

def compute_residual(scene, segs, obj):
    props = obj.optics
    pos_err = 0.0
    ang_err = 0.0
    nxt = None

    s_in = _seg_in(segs, obj.name)
    ip = _first(props, 'IN')
    if s_in and ip:
        p1 = Vector(s_in["p1"])
        d = (Vector(s_in["p2"]) - p1)
        if d.length > 1e-9:
            in_center = geometry.world_port(obj, ip.local_position)
            pos_err = geometry.perpendicular_distance(in_center, p1, d.normalized())

    s_out = _seg_out(segs, obj.name)
    if s_out and s_out["to"]:
        tgt = scene.objects.get(s_out["to"])
        tin = _first(tgt.optics, 'IN') if tgt else None
        if tgt and tin:
            o1 = Vector(s_out["p1"])
            out_dir = (Vector(s_out["p2"]) - o1)
            desired = (geometry.world_port(tgt, tin.local_position) - o1)
            if out_dir.length > 1e-9 and desired.length > 1e-9:
                c = geometry.clamp(out_dir.normalized().dot(desired.normalized()), -1.0, 1.0)
                ang_err = math.degrees(math.acos(c))
            nxt = tgt.name
    return pos_err, ang_err, nxt


def _state_for(scene, props, pos_err, ang_err):
    o = scene.optics
    if props.mech_state == 'BAD':
        return 'BAD'
    if pos_err <= o.ok_pos_mm and ang_err <= o.ok_ang_deg:
        return 'OK'
    if pos_err <= o.warn_pos_mm and ang_err <= o.warn_ang_deg:
        return 'WARN'
    return 'BAD'


def measure(segs, name, analyzer='NONE'):
    """Return (power, visibility, strongest_segment) at a detector from segments,
    without writing properties (so a scan can call it cheaply). Beams from the same
    source combine coherently; different sources add incoherently; an analyzer (if
    given) projects each field first. power = -1 when no beam reaches the detector."""
    incoming = [s for s in segs if s["to"] == name]
    if not incoming:
        return -1.0, -1.0, None
    M = physics.analyzer_matrix(analyzer)
    groups = {}
    for s in incoming:
        groups.setdefault(s.get("src_id", -1), []).append(s)
    total, vis, strongest, best = 0.0, -1.0, None, -1.0
    for group in groups.values():
        beams = []
        for s in group:
            j = s.get("jones")
            if j:
                J = (complex(j[0], j[1]), complex(j[2], j[3]))
                if M is not None:
                    J = physics.apply(M, J)
            else:
                J = (complex(math.sqrt(max(s.get("power", 0.0), 0.0))), 0j)
            beams.append((J, s.get("opl", 0.0), s.get("wavelength", 632.8)))
            p = physics.intensity(J)
            if p > best:
                best, strongest = p, s
        gI, gV = physics.interfere(beams, group[0].get("coh", float('inf')))
        total += gI
        if gV > vis:
            vis = gV
    return total, vis, strongest


def _measure_detector(props, segs, name):
    """Write a detector's measured power, polarization, fringe visibility, and spot."""
    power, vis, strongest = measure(segs, name, props.analyzer)
    if power < 0.0:
        props.meas_power, props.meas_pol, props.meas_visibility, props.meas_text = -1.0, "", -1.0, ""
        return
    props.meas_power = power
    props.meas_visibility = vis
    j = strongest.get("jones") if strongest else None
    if j:
        ps = physics.polarization_state((complex(j[0], j[1]), complex(j[2], j[3])))
        props.meas_pol = "%s, az %.0f deg, DOP %.2f" % (ps["kind"], ps["azimuth_deg"], ps["dop"])
    else:
        props.meas_pol = ""
    loss = ("  %.1f dB" % (-10.0 * math.log10(power))) if power > 1e-12 else ""
    spot = ("spot w=%.3f mm" % strongest.get("w_mm", 0.0)) if strongest else ""
    props.meas_text = (spot + loss).strip()


def refresh_report(scene):
    segs = tracer.cached_segments if tracer.cached_segments else _trace(scene)
    report = []
    for obj in scene.objects:
        props = getattr(obj, "optics", None)
        if not props or not props.is_optical:
            continue
        if props.element_type in ('SOURCE',):
            props.align_state = 'OK'
            continue
        pos_err, ang_err, nxt = compute_residual(scene, segs, obj)
        props.misalign_pos_mm = pos_err
        props.misalign_ang_deg = ang_err
        state = _state_for(scene, props, pos_err, ang_err)
        props.align_state = state
        if scene.optics.auto_color:
            obj.color = COLOR.get(state, COLOR['UNKNOWN'])
        if props.element_type in tracer.TERMINAL:
            _measure_detector(props, segs, obj.name)
        report.append({"name": obj.name, "type": props.element_type,
                       "pos_err_mm": round(pos_err, 4), "ang_err_deg": round(ang_err, 4),
                       "state": state, "next": nxt, "mech": props.mech_state})
    return report


# --- DOF-constrained steering solve -----------------------------------------

def _miss_vec(scene, obj):
    """2D miss of obj's outgoing ray at the next element's IN plane.
    Returns (e2, target) or (None, None)."""
    segs = _trace(scene)
    s_out = _seg_out(segs, obj.name)
    if not s_out or not s_out["to"]:
        return None, None
    tgt = scene.objects.get(s_out["to"])
    tin = _first(tgt.optics, 'IN') if tgt else None
    if not tgt or not tin:
        return None, None
    Tc = geometry.world_port(tgt, tin.local_position)
    Tn = geometry.world_normal(tgt, tin.local_normal)
    miss = Vector(s_out["p2"]) - Tc
    u = Tn.cross(Vector((0.0, 0.0, 1.0)))
    if u.length < 1e-6:
        u = Tn.cross(Vector((1.0, 0.0, 0.0)))
    u.normalize()
    v = Tn.cross(u).normalized()
    return Vector((miss.dot(u), miss.dot(v))), tgt


def _solve2(J, e):
    a, b = J[0]
    c, d = J[1]
    det = a * d - b * c
    if abs(det) < 1e-9:
        return None
    ex, ey = -e[0], -e[1]
    return [(d * ex - b * ey) / det, (-c * ex + a * ey) / det]


def align_element(scene, obj, iters=8, h=0.5):
    props = obj.optics
    if not props.base_pose_set and len(props.dofs):
        mounts.store_base_matrix(props, obj.matrix_world.copy())
    rdofs = [d for d in props.dofs if d.kind in ('TIP', 'TILT', 'ROT')][:2]
    if not rdofs:
        return {"ok": False, "msg": "no rotational DOFs to steer"}

    e0, tgt = _miss_vec(scene, obj)
    if e0 is None:
        return {"ok": False, "msg": "no downstream target"}
    before = e0.length

    for _ in range(iters):
        e, tgt = _miss_vec(scene, obj)
        if e is None:
            break
        if e.length < 0.02:
            break
        cols = []
        for d in rdofs:
            old = d.current
            probe = geometry.clamp(old + h, d.min_val, d.max_val)
            if abs(probe - old) < 1e-6:                 # pinned at upper limit -> probe downward
                probe = geometry.clamp(old - h, d.min_val, d.max_val)
            step = probe - old
            if abs(step) < 1e-6:                        # DOF fully pinned (min == max)
                cols.append((0.0, 0.0))
                continue
            d.current = probe
            mounts.compose_pose(obj)
            bpy.context.view_layer.update()
            ep, _t = _miss_vec(scene, obj)
            d.current = old
            mounts.compose_pose(obj)
            bpy.context.view_layer.update()
            if ep is None:
                cols.append((0.0, 0.0))
            else:
                cols.append(((ep[0] - e[0]) / step, (ep[1] - e[1]) / step))
        if len(rdofs) == 2:
            J = [[cols[0][0], cols[1][0]], [cols[0][1], cols[1][1]]]
            delta = _solve2(J, (e[0], e[1]))
            if delta is None:        # singular -> gradient descent fallback
                delta = [-0.5 * (cols[0][0] * e[0] + cols[0][1] * e[1]),
                         -0.5 * (cols[1][0] * e[0] + cols[1][1] * e[1])]
            for d, dl in zip(rdofs, delta):
                d.current = geometry.clamp(d.current + dl, d.min_val, d.max_val)
        else:
            g = cols[0]
            denom = g[0] * g[0] + g[1] * g[1]
            stp = -(g[0] * e[0] + g[1] * e[1]) / denom if denom > 1e-9 else 0.0
            rdofs[0].current = geometry.clamp(rdofs[0].current + stp,
                                              rdofs[0].min_val, rdofs[0].max_val)
        mounts.compose_pose(obj)
        bpy.context.view_layer.update()

    e1, tgt = _miss_vec(scene, obj)
    after = e1.length if e1 else None
    clamped = any(d.current <= d.min_val + 1e-4 or d.current >= d.max_val - 1e-4 for d in rdofs)
    out_of_range = bool(after is not None and after > scene.optics.warn_pos_mm and clamped)
    if out_of_range:
        props.align_detail = "knob range exhausted - move the post (coarse placement)"
    else:
        props.align_detail = ""
    return {"ok": True, "before": before, "after": after,
            "clamped": clamped, "out_of_range": out_of_range}


def _path_order(scene):
    segs = _trace(scene)
    order = []
    for s in segs:
        if s["to"] and s["to"] not in order:
            order.append(s["to"])
    return order


def align_all(scene):
    results = []
    for name in _path_order(scene):
        obj = scene.objects.get(name)
        if not obj or not getattr(obj, "optics", None) or not obj.optics.is_optical:
            continue
        if any(d.kind in ('TIP', 'TILT', 'ROT') for d in obj.optics.dofs):
            results.append((name, align_element(scene, obj)))
    return results


# --- operators --------------------------------------------------------------

class OPTICS_OT_refresh_report(Operator):
    bl_idname = "optics.refresh_report"
    bl_label = "Update Report"
    bl_description = "Recompute alignment residuals for every optical element"
    bl_options = {'REGISTER'}

    def execute(self, context):
        tracer.cached_segments = _trace(context.scene)
        report = refresh_report(context.scene)
        worst = max((r["state"] for r in report),
                    key=lambda s: {'OK': 1, 'WARN': 2, 'BAD': 3}.get(s, 0), default='UNKNOWN')
        self.report({'INFO'}, "Report updated for %d elements (worst: %s)" % (len(report), worst))
        return {'FINISHED'}


class OPTICS_OT_align_element(Operator):
    bl_idname = "optics.align_element"
    bl_label = "Align"
    bl_description = "Steer this element's knobs to aim the beam at the next element"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty()

    def execute(self, context):
        scene = context.scene
        obj = scene.objects.get(self.name) if self.name else context.object
        if obj is None:
            self.report({'ERROR'}, "No element")
            return {'CANCELLED'}
        res = align_element(scene, obj)
        tracer.cached_segments = _trace(scene)
        refresh_report(scene)
        tracer._tag_redraw()
        if not res["ok"]:
            self.report({'WARNING'}, "%s: %s" % (obj.name, res["msg"]))
            return {'CANCELLED'}
        if res["out_of_range"]:
            self.report({'WARNING'}, "%s: knob range exhausted - move the post (coarse)" % obj.name)
        else:
            self.report({'INFO'}, "%s aligned: miss %.3f -> %.3f mm"
                        % (obj.name, res["before"] or 0.0, res["after"] or 0.0))
        return {'FINISHED'}


class OPTICS_OT_align_all(Operator):
    bl_idname = "optics.align_all"
    bl_label = "Align All"
    bl_description = "Align every steerable element in beam order, source to detector"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        results = align_all(scene)
        tracer.cached_segments = _trace(scene)
        refresh_report(scene)
        tracer._tag_redraw()
        bad = sum(1 for _n, r in results if r.get("out_of_range"))
        self.report({'INFO'}, "Aligned %d elements (%d need coarse move)" % (len(results), bad))
        return {'FINISHED'}


class OPTICS_OT_power_budget(Operator):
    bl_idname = "optics.power_budget"
    bl_label = "Power Budget"
    bl_description = "Write a per-detector power/loss breakdown + element list to a text block"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        segs = tracer.cached_segments if tracer.cached_segments else _trace(scene)
        dets = [o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical
                and o.optics.element_type in tracer.TERMINAL]
        lines = ["Optical Power Budget (source = 1.0 = 0 dB)", "=" * 44]
        for d in dets:
            power, vis, _s = measure(segs, d.name, d.optics.analyzer)
            if power < 0.0:
                lines.append("\n%s: no beam reaches this detector" % d.name)
                continue
            db = -10.0 * math.log10(power) if power > 1e-12 else float('inf')
            lines.append("\n%s: power %.4f  (%.1f dB loss)%s"
                         % (d.name, power, db, ("  visibility %.2f" % vis) if vis >= 0 else ""))
            chain, cur, guard = [], max((s for s in segs if s["to"] == d.name),
                                        key=lambda x: x["power"]), 0
            while cur is not None and guard < 128:
                chain.append(cur)
                p = cur.get("parent", -1)
                cur = segs[p] if 0 <= p < len(segs) else None
                guard += 1
            for c in reversed(chain):
                lines.append("    %-12s %-9s P=%.4f" % (c.get("from") or "(source)", c["kind"], c["power"]))
        lines.append("\nElements:")
        for o in scene.objects:
            op = getattr(o, "optics", None)
            if op and op.is_optical:
                lines.append("    %-16s %-16s %s"
                             % (o.name, op.element_type, ("%.1f nm" % op.wavelength) if op.is_source else ""))
        text = "\n".join(lines)
        blk = bpy.data.texts.get("OpticsBudget") or bpy.data.texts.new("OpticsBudget")
        blk.clear()
        blk.write(text)
        print(text)
        self.report({'INFO'}, "Power budget -> Text 'OpticsBudget' (%d detectors)" % len(dets))
        return {'FINISHED'}


_classes = (
    OPTICS_OT_refresh_report,
    OPTICS_OT_align_element,
    OPTICS_OT_align_all,
    OPTICS_OT_power_budget,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
