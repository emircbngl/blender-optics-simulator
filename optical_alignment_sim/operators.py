"""Milestone-1 operators: tag elements, auto-detect ports, pick a port from a
selected mesh face, and normalize imported vendor CAD.

Port population logic is factored into module functions so the tag operator can
reuse it directly (avoids operator-in-operator context pitfalls).
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty, BoolProperty, FloatProperty

from . import geometry, presets
from .properties import PORT_ROLES


# --- shared port helpers ----------------------------------------------------

def _add_port(props, name, role, local_pos, local_normal, ca=12.7):
    p = props.ports.add()
    p.name = name
    p.role = role
    p.local_position = local_pos
    p.local_normal = local_normal
    p.clear_aperture = ca
    return p


def _default_specs_for_type(etype, obj):
    """Fallback port specs when the name prefix is unknown, keyed by element type."""
    ax = geometry.longest_axis(obj)
    plus, minus = "+" + ax, "-" + ax
    if etype in ('LENS', 'WAVEPLATE', 'ATTENUATOR', 'PASSTHROUGH',
                 'POLARIZER', 'FILTER', 'ISOLATOR', 'PINHOLE'):
        return [("IN", "IN", minus), ("OUT", "OUT", plus)]
    if etype in ('SOURCE', 'FIBER_COLLIMATOR'):
        return [("OUT", "OUT", plus)]
    if etype in ('DETECTOR', 'PHOTODIODE', 'POWER_METER'):
        return [("IN", "IN", minus)]
    if etype in ('MIRROR', 'PRISM_MIRROR', 'DICHROIC', 'GRATING'):
        return [("IN", "IN", "+Z"), ("OUT", "OUT", "+Y")]
    if etype == 'RETROREFLECTOR':
        return [("IN", "IN", "+Z"), ("OUT", "OUT", "+Z")]
    if etype == 'BEAMSPLITTER':
        return [("IN_ref", "IN", "+X"), ("IN_sam", "IN", "-Y"), ("OUT", "OUT", "+Y")]
    if etype == 'APERTURE':
        return [("IN", "IN", minus), ("OUT", "OUT", plus)]
    return []


def _populate_ports_from_specs(obj, props, port_specs):
    props.ports.clear()
    in_n = out_n = None
    for (_pname, role, axis) in port_specs:
        n = geometry.axis_vector(axis)
        if role == 'IN' and in_n is None:
            in_n = n
        if role == 'OUT' and out_n is None:
            out_n = n
    ca = props.clear_aperture if props.clear_aperture > 0.0 else 12.7
    for (pname, role, axis) in port_specs:
        _add_port(obj.optics, pname, role,
                  geometry.face_center_local(obj, axis),
                  geometry.axis_vector(axis), ca)
    # derive the internal reflective plane for reflective elements
    if props.element_type in ('PRISM_MIRROR', 'MIRROR', 'BEAMSPLITTER',
                              'DICHROIC', 'GRATING', 'RETROREFLECTOR') and in_n is not None and out_n is not None:
        _, _, ctr = geometry.local_bounds(obj)
        rn = in_n + out_n
        rn = rn.normalized() if rn.length > geometry.EPS else geometry.axis_vector("+Z")
        _add_port(props, "REFLECT", 'REFLECT', ctr, rn, ca)


def do_auto_detect(obj):
    """Fill obj.optics.ports from name prefix or element type. Returns port count."""
    props = obj.optics
    props.is_optical = True
    etype, specs = presets.match_prefix(obj.name)
    if props.element_type == 'NONE' and etype:
        props.element_type = etype
    if specs is None:
        specs = _default_specs_for_type(props.element_type, obj)
    if specs:
        _populate_ports_from_specs(obj, props, specs)
    props.is_source = (props.element_type == 'SOURCE')
    props.is_detector = (props.element_type == 'DETECTOR')
    return len(props.ports)


# --- operators --------------------------------------------------------------

class OPTICS_OT_tag_element(Operator):
    bl_idname = "optics.tag_element"
    bl_label = "Tag as Optical Element"
    bl_description = "Mark the active object as an optical element and auto-detect its ports"
    bl_options = {'REGISTER', 'UNDO'}

    auto_ports: BoolProperty(name="Auto-detect ports", default=True)

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        obj = context.object
        props = obj.optics
        props.is_optical = True
        if props.element_type == 'NONE':
            etype, _ = presets.match_prefix(obj.name)
            if etype:
                props.element_type = etype
        props.is_source = (props.element_type == 'SOURCE')
        props.is_detector = (props.element_type == 'DETECTOR')
        if self.auto_ports and len(props.ports) == 0:
            do_auto_detect(obj)
        self.report({'INFO'}, "Tagged '%s' as %s (%d ports)"
                    % (obj.name, props.element_type, len(props.ports)))
        return {'FINISHED'}


class OPTICS_OT_auto_detect_ports(Operator):
    bl_idname = "optics.auto_detect_ports"
    bl_label = "Auto-Detect Ports"
    bl_description = "Populate ports from the object's name prefix or element type"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        n = do_auto_detect(context.object)
        if n == 0:
            self.report({'WARNING'},
                        "No ports detected - set an element type or use 'Add port from face'")
            return {'CANCELLED'}
        self.report({'INFO'}, "Detected %d ports" % n)
        return {'FINISHED'}


class OPTICS_OT_pick_port_from_face(Operator):
    bl_idname = "optics.pick_port_from_face"
    bl_label = "Add Port from Active Face"
    bl_description = ("Create a port from the active/selected mesh face "
                      "(center + normal). Works on any imported mesh")
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="Role", items=PORT_ROLES, default='IN')
    port_name: StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        o = context.object
        return o is not None and o.type == 'MESH'

    def execute(self, context):
        obj = context.object
        center = normal = None

        if obj.mode == 'EDIT':
            import bmesh
            bm = bmesh.from_edit_mesh(obj.data)
            f = bm.faces.active
            if f is None or not f.select:
                sel = [ff for ff in bm.faces if ff.select]
                f = sel[0] if sel else None
            if f is None:
                self.report({'ERROR'}, "Select a face in Edit Mode first")
                return {'CANCELLED'}
            center = f.calc_center_median().copy()
            normal = f.normal.copy()
        else:
            me = obj.data
            idx = me.polygons.active
            if idx is None or idx < 0 or idx >= len(me.polygons):
                self.report({'ERROR'}, "No active face - enter Edit Mode and select one")
                return {'CANCELLED'}
            poly = me.polygons[idx]
            center = poly.center.copy()
            normal = poly.normal.copy()

        props = obj.optics
        props.is_optical = True
        name = self.port_name or self.role
        _add_port(props, name, self.role, center, normal,
                  props.clear_aperture if props.clear_aperture > 0.0 else 12.7)
        props.ports_index = len(props.ports) - 1
        self.report({'INFO'}, "Added port '%s' from face" % name)
        return {'FINISHED'}


class OPTICS_OT_normalize_import(Operator):
    bl_idname = "optics.normalize_import"
    bl_label = "Normalize Imported CAD"
    bl_description = ("Apply rotation & scale, set origin to volume center, and "
                      "sanity-check units against an expected size")
    bl_options = {'REGISTER', 'UNDO'}

    expected_size_mm: FloatProperty(name="Expected size (mm)", default=25.4, min=0.0)
    set_origin_center: BoolProperty(name="Origin to volume center", default=True)

    @classmethod
    def poll(cls, context):
        o = context.object
        return o is not None and o.type == 'MESH'

    def execute(self, context):
        obj = context.object
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in list(context.selected_objects):
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if self.set_origin_center:
            bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')

        mx = max(obj.dimensions)
        if self.expected_size_mm > 0.0:
            ratio = mx / self.expected_size_mm
            if ratio > 100.0:
                self.report({'WARNING'},
                            "Max dim %.1f is ~%.0fx expected %.1fmm - check units (m vs mm)!"
                            % (mx, ratio, self.expected_size_mm))
            elif ratio < 0.01:
                self.report({'WARNING'},
                            "Max dim %.4f is ~%.0fx too small vs %.1fmm - check units!"
                            % (mx, 1.0 / ratio if ratio else 0.0, self.expected_size_mm))
            else:
                self.report({'INFO'}, "Size OK: %.2f vs expected %.1fmm" % (mx, self.expected_size_mm))
        else:
            self.report({'INFO'}, "Applied transforms; max dim %.2f" % mx)
        return {'FINISHED'}


_classes = (
    OPTICS_OT_tag_element,
    OPTICS_OT_auto_detect_ports,
    OPTICS_OT_pick_port_from_face,
    OPTICS_OT_normalize_import,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
