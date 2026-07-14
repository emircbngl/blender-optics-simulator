"""Mount kinematics + opto-mechanical limits.

The core idea: a vendor mesh is static, so we *rig* it with the adjustability it
lacks. Each element stores a `base_pose` (coarse placement, knobs at zero) plus a
set of AdjustmentDOF "knobs" (tip / tilt / rotate / translate, each with a range).
The live world pose is recomputed from base_pose + the current knob values, so:

  * coarse placement (bolting the post to the table) = editing base_pose
  * fine alignment (turning the knobs)               = editing dof.current

`check_mechanics` flags rod/pedestal travel problems (post pulling out of a
holder, cage rod leaving its bore).
"""
from __future__ import annotations

import os
import json
import math

import bpy
from bpy.types import Operator
from bpy.props import (EnumProperty, StringProperty, FloatProperty, IntProperty)
from mathutils import Matrix, Vector

from . import geometry, presets

AXIS_ITEMS = [(a, a, "") for a in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")]


# --- base pose <-> matrix ----------------------------------------------------

def base_matrix(props) -> Matrix:
    f = props.base_pose
    return Matrix((f[0:4], f[4:8], f[8:12], f[12:16]))


def store_base_matrix(props, M: Matrix):
    props.base_pose = [M[r][c] for r in range(4) for c in range(4)]
    props.base_pose_set = True


def _effective_base(props) -> Matrix:
    """The element's base pose in WORLD space: base_pose is anchor-relative when an anchor is
    set, so fold the anchor's world matrix back in (compose_pose / dof_world map through this)."""
    B = base_matrix(props)
    anchor = getattr(props, "anchor", None)
    if anchor is not None and anchor is not props.id_data:
        B = anchor.matrix_world @ B
    return B


def store_world_base(props, world_matrix: Matrix):
    """Store a WORLD-space pose as base_pose, re-expressed into the anchor's frame when anchored.
    base_pose is contractually anchor-relative whenever props.anchor is set, so storing a raw
    world matrix on an anchored element makes compose_pose double-apply the anchor (element jumps)."""
    anchor = getattr(props, "anchor", None)
    if anchor is not None and anchor is not props.id_data:
        world_matrix = anchor.matrix_world.inverted() @ world_matrix
    store_base_matrix(props, world_matrix)


def anchor_would_cycle(obj, anchor) -> bool:
    """True if anchoring obj -> anchor would create a cycle (anchor's chain reaches obj)."""
    cur, seen = anchor, set()
    while cur is not None and id(cur) not in seen:
        if cur is obj:
            return True
        seen.add(id(cur))
        op = getattr(cur, "optics", None)
        cur = getattr(op, "anchor", None) if op else None
    return False


def dof_world(B: Matrix, dof):
    """World-space pivot point and unit axis for a DOF, in the base frame B."""
    pivot_w = B @ Vector(dof.pivot_local)
    axis_w = B.to_3x3() @ Vector(dof.axis_local)
    if axis_w.length < 1e-9:
        axis_w = Vector((0.0, 0.0, 1.0))
    return pivot_w, axis_w.normalized()


def compose_pose(obj):
    """Recompute obj.matrix_world from base_pose + current DOF values.

    If the element has an `anchor`, its base_pose is stored *in the anchor's frame*,
    so the world base = anchor.matrix_world @ base_pose - moving the anchor moves the
    element (relative positioning / assembly group / live "B follows A" link)."""
    props = obj.optics
    if not props.base_pose_set:
        return
    B = base_matrix(props)
    anchor = getattr(props, "anchor", None)
    if anchor is not None and anchor is not obj:
        B = anchor.matrix_world @ B
    pose = B.copy()
    # Apply rotations first (about the base pivot), then translations, so the two
    # act as independent base-frame knobs - a later rotation must not rotate an
    # earlier translation vector.
    ordered = ([d for d in props.dofs if d.kind in ('TIP', 'TILT', 'ROT')] +
               [d for d in props.dofs if d.kind not in ('TIP', 'TILT', 'ROT')])
    for dof in ordered:
        pivot_w, axis_w = dof_world(B, dof)
        if dof.kind in ('TIP', 'TILT', 'ROT'):
            R = Matrix.Rotation(math.radians(dof.current), 4, axis_w)
            T = Matrix.Translation(pivot_w)
            M = T @ R @ T.inverted()
        else:  # TRANS_*
            M = Matrix.Translation(axis_w * dof.current)
        pose = M @ pose
    obj.matrix_world = pose


def capture_base_pose(obj):
    """Re-baseline: treat the current pose (with knobs zeroed) as the new base."""
    props = obj.optics
    props.base_pose_set = False           # make _dof_update compose a no-op
    for d in props.dofs:
        d.current = 0.0
    store_world_base(props, obj.matrix_world.copy())   # anchor-aware (no jump on anchored elements)


def set_anchor(obj, anchor):
    """Attach obj to an anchor so its pose follows the anchor. base_pose is re-expressed
    in the anchor's frame so the element does not jump. Returns True on success."""
    props = obj.optics
    if anchor is None or anchor is obj:
        return False
    if anchor_would_cycle(obj, anchor):              # reject A->B->A (would never converge)
        return False
    if not props.base_pose_set:
        store_base_matrix(props, obj.matrix_world.copy())
    Bw = _effective_base(props)                      # current WORLD base (folds any EXISTING anchor)
    rel = anchor.matrix_world.inverted() @ Bw        # express it in the NEW anchor's frame
    store_base_matrix(props, rel)
    props.anchor = anchor
    compose_pose(obj)
    return True


def clear_anchor(obj):
    """Detach obj from its anchor, baking the current relative base back into world."""
    props = obj.optics
    anchor = getattr(props, "anchor", None)
    if anchor is None:
        return False
    Bw = anchor.matrix_world @ base_matrix(props)    # relative base -> world base
    store_base_matrix(props, Bw)
    props.anchor = None
    compose_pose(obj)
    return True


# --- mount preset library (seed + user JSON) --------------------------------

def _user_lib_path():
    try:
        d = bpy.utils.extension_path_user(__package__, path="library", create=True)
    except Exception:
        d = bpy.utils.user_resource('CONFIG', path="optical_alignment_sim", create=True)
    return os.path.join(d, "mounts.json")


def get_library():
    lib = {k: dict(v) for k, v in presets.MOUNT_LIBRARY.items()}
    p = _user_lib_path()
    if os.path.exists(p):
        try:
            with open(p, "r") as f:
                user_lib = json.load(f)
            if not isinstance(user_lib, dict):
                raise TypeError("mount library root must be a JSON object")
            lib.update(user_lib)
        except Exception as exc:
            detail = str(exc).replace("\r", " ").replace("\n", " ")
            print("Optics Simulator: warning: could not load mount library %s: %s" % (p, detail))
    return lib


def _axis_label(vec):
    best, dot = "+Z", -2.0
    for a in ("+X", "-X", "+Y", "-Y", "+Z", "-Z"):
        d = Vector(vec).normalized().dot(geometry.axis_vector(a))
        if d > dot:
            best, dot = a, d
    return best


def serialize_mount(obj):
    props = obj.optics
    return {
        "mount_type": props.mount_type,
        "pivot": "OPTIC_CENTER",
        "clear_aperture_mm": props.clear_aperture,
        "dofs": [{"kind": d.kind, "axis": _axis_label(d.axis_local),
                  "min": d.min_val, "max": d.max_val} for d in props.dofs],
    }


def save_preset(key, data):
    p = _user_lib_path()
    user = {}
    if os.path.exists(p):
        try:
            with open(p, "r") as f:
                user = json.load(f)
        except Exception:
            user = {}
    user[key] = data
    with open(p, "w") as f:
        json.dump(user, f, indent=2)
    return p


def apply_preset(obj, key):
    data = get_library().get(key)
    if not data:
        return False, "preset '%s' not found" % key
    props = obj.optics
    props.base_pose_set = False
    props.mount_preset = key
    props.mount_type = data.get("mount_type", 'KINEMATIC_2AXIS')
    ca = data.get("clear_aperture_mm")
    if ca:
        # the catalog value is a DIAMETER (vendor CA spec); props.clear_aperture is a RADIUS
        # everywhere in the engine (sensor capture, dressing proportions). Storing the diameter
        # here made every preset-dressed mount render twice too big and bored its housing away.
        props.clear_aperture = ca * 0.5
    _, _, ctr = geometry.local_bounds(obj)
    piv = data.get("pivot", "OPTIC_CENTER")
    if piv == "OPTIC_CENTER":
        pivot_local = ctr
    elif isinstance(piv, (list, tuple)) and len(piv) == 2 and piv[0] == "BELOW":
        # WORLD-semantic pivot: d mm straight DOWN from the optic centre, whatever the element's
        # local basis. Local bases come from a minimal rotation, so WHICH local axis points down
        # depends on the beam direction -- a static local pivot cannot express "below" for every
        # orientation, and a flip-mount hinge genuinely is "below" in gravity terms.
        R = obj.matrix_world.to_3x3()
        pivot_local = ctr + R.inverted() @ Vector((0.0, 0.0, -float(piv[1])))
    else:
        pivot_local = Vector(piv)
    props.dofs.clear()
    for d in data.get("dofs", []):
        nd = props.dofs.add()
        nd.kind = d.get("kind", 'TIP')
        nd.name = d.get("kind", "DOF")
        ax = d.get("axis", "+X")
        if ax == "WORLD_HPERP":
            # WORLD-semantic axis: horizontal and perpendicular to the beam (a flip-mount hinge),
            # resolved into the element's local frame at preset-apply time.
            R = obj.matrix_world.to_3x3()
            beam = (R @ Vector((0.0, 0.0, 1.0))).normalized()
            hax = Vector((0.0, 0.0, 1.0)).cross(beam)
            if hax.length < 1e-6:
                hax = Vector((1.0, 0.0, 0.0))
            nd.axis_local = R.inverted() @ hax.normalized()
        else:
            nd.axis_local = geometry.axis_vector(ax)
        nd.pivot_local = pivot_local
        nd.min_val = d.get("min", -4.0)
        nd.max_val = d.get("max", 4.0)
        nd.current = 0.0
    store_world_base(props, obj.matrix_world.copy())   # anchor-aware: don't double-apply an anchor
    return True, "applied '%s' (%d DOFs)" % (key, len(props.dofs))


# --- opto-mechanical limit checks -------------------------------------------

def _world_bounds(obj):
    cs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mn = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
    mx = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
    return mn, mx


def check_object_mech(obj):
    props = obj.optics
    for link in props.mech:
        tgt = link.target
        if tgt is None:
            link.state, link.detail = 'UNKNOWN', "no target set"
            continue
        if link.kind == 'POST_INSERT':
            a_mn, a_mx = _world_bounds(obj)
            b_mn, b_mx = _world_bounds(tgt)
            # insertion axis = the post's longest world dimension (not assumed +Z)
            ax = max(range(3), key=lambda i: (a_mx - a_mn)[i])
            overlap = min(a_mx[ax], b_mx[ax]) - max(a_mn[ax], b_mn[ax])
            link.detail = "insertion ~%.1fmm (%s)" % (overlap, "XYZ"[ax])
            if overlap < link.insert_min:
                link.state = 'BAD'
                link.detail += " < min (rod pulling out of holder)"
            elif overlap > link.insert_max:
                link.state = 'WARN'
                link.detail += " > max (bottomed out / collision)"
            else:
                link.state = 'OK'
        else:  # CAGE_ROD
            d = (obj.matrix_world.translation - tgt.matrix_world.translation).length
            link.detail = "separation ~%.1fmm" % d
            if d > link.insert_max:
                link.state = 'BAD'
                link.detail += " > rod span (rod out of bore)"
            elif d < link.insert_min:
                link.state = 'WARN'
                link.detail += " < min (over-inserted)"
            else:
                link.state = 'OK'
    states = [l.state for l in props.mech]
    props.mech_state = ('BAD' if 'BAD' in states else
                        'WARN' if 'WARN' in states else
                        'OK' if states else 'UNKNOWN')
    return props.mech_state


def check_mechanics(scene):
    worst = 'UNKNOWN'
    rank = {'UNKNOWN': 0, 'OK': 1, 'WARN': 2, 'BAD': 3}
    for obj in scene.objects:
        if getattr(obj, "optics", None) and obj.optics.is_optical and len(obj.optics.mech):
            s = check_object_mech(obj)
            if rank[s] > rank[worst]:
                worst = s
    return worst


# --- dynamic enum for preset picker -----------------------------------------

_preset_items_cache = []


def _preset_items(self, context):
    global _preset_items_cache
    keys = sorted(get_library().keys())
    _preset_items_cache = [(k, k, "") for k in keys] if keys else [('NONE', "(no presets)", "")]
    return _preset_items_cache


# --- operators --------------------------------------------------------------

class OPTICS_OT_set_mount_preset(Operator):
    bl_idname = "optics.set_mount_preset"
    bl_label = "Apply Mount Preset"
    bl_description = "Apply a mount preset (pivot, DOF axes, ranges) from the library"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Preset", items=_preset_items)

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        ok, msg = apply_preset(context.object, self.preset)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'} if ok else {'CANCELLED'}


class OPTICS_OT_capture_base_pose(Operator):
    bl_idname = "optics.capture_base_pose"
    bl_label = "Set Coarse Pose (zero knobs)"
    bl_description = "Treat the current placement as the base pose and reset all knobs to zero"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        capture_base_pose(context.object)
        self.report({'INFO'}, "Base pose captured; knobs zeroed")
        return {'FINISHED'}


class OPTICS_OT_define_dof(Operator):
    bl_idname = "optics.define_dof"
    bl_label = "Add Adjustment DOF"
    bl_description = "Add an adjustment degree of freedom (knob) to this mount"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name="Kind",
                       items=[('TIP', "Tip", ""), ('TILT', "Tilt", ""), ('ROT', "Rotate", ""),
                              ('TRANS_X', "Translate X", ""), ('TRANS_Y', "Translate Y", ""),
                              ('TRANS_Z', "Translate Z", "")],
                       default='TIP')
    axis: EnumProperty(name="Axis", items=AXIS_ITEMS, default='+X')
    min_val: FloatProperty(name="Min", default=-4.0)
    max_val: FloatProperty(name="Max", default=4.0)

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.object
        props = obj.optics
        props.is_optical = True
        if not props.base_pose_set:
            store_base_matrix(props, obj.matrix_world.copy())
        _, _, ctr = geometry.local_bounds(obj)
        d = props.dofs.add()
        d.kind = self.kind
        d.name = self.kind
        d.axis_local = geometry.axis_vector(self.axis)
        d.pivot_local = ctr
        d.min_val, d.max_val = self.min_val, self.max_val
        d.current = 0.0
        props.dofs_index = len(props.dofs) - 1
        if props.mount_type == 'FIXED':
            props.mount_type = 'KINEMATIC_2AXIS' if self.kind in ('TIP', 'TILT', 'ROT') else 'TRANSLATION'
        return {'FINISHED'}


class OPTICS_OT_remove_dof(Operator):
    bl_idname = "optics.remove_dof"
    bl_label = "Remove DOF"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.object.optics.dofs)

    def execute(self, context):
        props = context.object.optics
        i = self.index if self.index >= 0 else props.dofs_index
        if 0 <= i < len(props.dofs):
            props.dofs.remove(i)
            props.dofs_index = min(i, len(props.dofs) - 1)
            compose_pose(context.object)
        return {'FINISHED'}


class OPTICS_OT_zero_dofs(Operator):
    bl_idname = "optics.zero_dofs"
    bl_label = "Zero Knobs"
    bl_description = "Reset all knob values to zero"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.object.optics.dofs)

    def execute(self, context):
        for d in context.object.optics.dofs:
            d.current = 0.0
        compose_pose(context.object)
        return {'FINISHED'}


class OPTICS_OT_pick_pivot(Operator):
    bl_idname = "optics.pick_pivot"
    bl_label = "Set Pivot"
    bl_description = "Set the rotational pivot for all DOFs from a chosen source"
    bl_options = {'REGISTER', 'UNDO'}

    source: EnumProperty(
        name="From",
        items=[('OPTIC_CENTER', "Optic center", "Bounding-box center"),
               ('CURSOR', "3D cursor", ""),
               ('ORIGIN', "Object origin", ""),
               ('SELECTED_VERT', "Active vertex (Edit Mode)", "")],
        default='OPTIC_CENTER')

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.object.optics.dofs)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.object
        props = obj.optics
        # effective WORLD base (folds the anchor frame); compose_pose maps pivot_local through
        # the same effective base, so a world point must invert through it, not the stored base
        B = _effective_base(props) if props.base_pose_set else obj.matrix_world.copy()
        if self.source == 'OPTIC_CENTER':
            _, _, ctr = geometry.local_bounds(obj)
            pivot_local = ctr
        elif self.source == 'CURSOR':
            pivot_local = B.inverted() @ context.scene.cursor.location.copy()
        elif self.source == 'ORIGIN':
            pivot_local = B.inverted() @ obj.matrix_world.translation.copy()
        else:  # SELECTED_VERT
            if obj.mode != 'EDIT':
                self.report({'ERROR'}, "Enter Edit Mode and select a vertex")
                return {'CANCELLED'}
            import bmesh
            bm = bmesh.from_edit_mesh(obj.data)
            v = bm.select_history.active if bm.select_history else None
            if v is None:
                sel = [vv for vv in bm.verts if vv.select]
                v = sel[0] if sel else None
            if v is None:
                self.report({'ERROR'}, "No selected vertex")
                return {'CANCELLED'}
            # vertex coord is local already; convert through base for consistency
            world_v = obj.matrix_world @ v.co.copy()
            pivot_local = B.inverted() @ world_v
        for d in props.dofs:
            if d.kind in ('TIP', 'TILT', 'ROT'):
                d.pivot_local = pivot_local
        compose_pose(obj)
        self.report({'INFO'}, "Pivot set from %s" % self.source)
        return {'FINISHED'}


class OPTICS_OT_save_mount_preset(Operator):
    bl_idname = "optics.save_mount_preset"
    bl_label = "Save Mount as Preset"
    bl_description = "Save this object's mount (pivot/DOF/range) to the user library"
    bl_options = {'REGISTER'}

    key: StringProperty(name="Preset name", default="")

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.object.optics.dofs)

    def invoke(self, context, event):
        if not self.key:
            self.key = context.object.optics.mount_preset or context.object.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.key.strip():
            self.report({'ERROR'}, "Enter a preset name")
            return {'CANCELLED'}
        try:
            path = save_preset(self.key.strip(), serialize_mount(context.object))
        except OSError as e:                        # read-only profile dir / full disk -> clean report
            self.report({'ERROR'}, "Could not write mount preset: %s" % e)
            return {'CANCELLED'}
        context.object.optics.mount_preset = self.key.strip()
        self.report({'INFO'}, "Saved preset '%s' -> %s" % (self.key.strip(), path))
        return {'FINISHED'}


class OPTICS_OT_add_mech_link(Operator):
    bl_idname = "optics.add_mech_link"
    bl_label = "Add Mechanical Link"
    bl_description = "Add a post-insertion / cage-rod travel check against another object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        props = context.object.optics
        props.is_optical = True
        link = props.mech.add()
        link.name = "link %d" % len(props.mech)
        return {'FINISHED'}


class OPTICS_OT_remove_mech_link(Operator):
    bl_idname = "optics.remove_mech_link"
    bl_label = "Remove Mechanical Link"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.object.optics.mech)

    def execute(self, context):
        props = context.object.optics
        i = self.index if self.index >= 0 else len(props.mech) - 1
        if 0 <= i < len(props.mech):
            props.mech.remove(i)
        return {'FINISHED'}


class OPTICS_OT_check_mechanics(Operator):
    bl_idname = "optics.check_mechanics"
    bl_label = "Check Mechanics"
    bl_description = "Evaluate all rod/pedestal travel limits in the scene"
    bl_options = {'REGISTER'}

    def execute(self, context):
        worst = check_mechanics(context.scene)
        self.report({'INFO'}, "Mechanics: %s" % worst)
        return {'FINISHED'}


_classes = (
    OPTICS_OT_set_mount_preset,
    OPTICS_OT_capture_base_pose,
    OPTICS_OT_define_dof,
    OPTICS_OT_remove_dof,
    OPTICS_OT_zero_dofs,
    OPTICS_OT_pick_pivot,
    OPTICS_OT_save_mount_preset,
    OPTICS_OT_add_mech_link,
    OPTICS_OT_remove_mech_link,
    OPTICS_OT_check_mechanics,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
