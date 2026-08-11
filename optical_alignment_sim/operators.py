"""Milestone-1 operators: tag elements, auto-detect ports, pick a port from a
selected mesh face, and normalize imported vendor CAD.

Port population logic is factored into module functions so the tag operator can
reuse it directly (avoids operator-in-operator context pitfalls).
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty, BoolProperty, FloatProperty, IntProperty

from . import geometry, presets
from .properties import PORT_ROLES

# Which element types count as a source / a (terminal) detector for is_source / is_detector.
# The catalog grew past the two canonical types, so flag the whole family or these flags get
# reset to False on auto-detect and the elements drop out of get_state()'s source/detector lists.
SOURCE_TYPES = {'SOURCE', 'FIBER_COLLIMATOR'}
DETECTOR_TYPES = {'DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR'}


def _store_diagnosis(wm, records):
    cache = wm.optics_diagnosis_cache
    cache.clear()
    ordered = sorted(records, key=lambda item: 0 if item.get("severity") == 'BAD' else 1)
    for record in ordered:
        item = cache.add()
        item.issue = str(record.get("issue", record.get("kind", "")) or "")
        item.element = str(record.get("element", "") or "")
        item.detail = str(record.get("detail", "") or "")
        item.severity = str(record.get("severity", "WARN") or "WARN")
        item.suggested_fix = str(record.get("suggested_fix", "") or "")
        item.tool = str(record.get("tool", "") or "")
        item.maybe_intentional_if = str(record.get("maybe_intentional_if", "") or "")
        item.fault_confidence = float(record.get("fault_confidence", 1.0) or 0.0)
    wm.optics_diagnosis_bad = sum(item.severity == 'BAD' for item in cache)
    wm.optics_diagnosis_warn = sum(item.severity == 'WARN' for item in cache)
    wm.optics_diagnosis_revision = wm.optics_scene_revision


class OPTICS_OT_diagnose(Operator):
    bl_idname = "optics.diagnose"
    bl_label = "Diagnose"
    bl_description = "Trace the scene and cache optical issues. May pause the UI for a few seconds."

    def execute(self, context):
        from . import optics_api
        result = optics_api.diagnose()
        if not result.get("ok"):
            self.report({'ERROR'}, result.get("error", "Diagnosis failed"))
            return {'CANCELLED'}
        _store_diagnosis(context.window_manager, result.get("diagnostics", ()))
        return {'FINISHED'}


class OPTICS_OT_propose_corrections(Operator):
    bl_idname = "optics.propose_corrections"
    bl_label = "Propose Corrections"
    bl_description = "Trace the scene and cache advisory corrections. May pause the UI for a few seconds."

    def execute(self, context):
        from . import optics_api
        result = optics_api.propose_corrections()
        if not result.get("ok"):
            self.report({'ERROR'}, result.get("error", "Correction proposal failed"))
            return {'CANCELLED'}
        _store_diagnosis(context.window_manager, result.get("proposals", ()))
        return {'FINISHED'}


class OPTICS_OT_fix_diagnosis(Operator):
    bl_idname = "optics.fix_diagnosis"
    bl_label = "Fix…"
    bl_description = "Open the suggested correction with the affected element selected"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        if wm.optics_diagnosis_revision != wm.optics_scene_revision:
            cls.poll_message_set("Scene changed — re-run Diagnose")
            return False
        return bool(wm.optics_diagnosis_cache)

    def draw(self, context):
        item = context.window_manager.optics_diagnosis_cache[self.index]
        if item.fault_confidence < 0.5:
            self.layout.label(text="Often intentional: %s" % item.maybe_intentional_if,
                              icon='INFO')
        self.layout.label(text=item.suggested_fix or "Review the affected element.")

    def invoke(self, context, event):
        if self.index < 0 or self.index >= len(context.window_manager.optics_diagnosis_cache):
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        item = context.window_manager.optics_diagnosis_cache[self.index]
        obj = context.scene.objects.get(item.element)
        if obj is not None:
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        if item.tool == 'align_element':
            return bpy.ops.optics.align_element(name=item.element)
        if item.tool == 'auto_align':
            return bpy.ops.optics.auto_align()
        if item.tool == 'place_relative':
            return bpy.ops.optics.place_relative('INVOKE_DEFAULT')
        self.report({'ERROR'}, "No interactive operator is available for tool: %s" % item.tool)
        return {'CANCELLED'}


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
    if etype in ('LENS', 'WAVEPLATE', 'ATTENUATOR', 'SHUTTER', 'PASSTHROUGH',
                 'POLARIZER', 'FILTER', 'ISOLATOR', 'PINHOLE', 'CAVITY'):
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
    if etype == 'WAVEFRONT_SENSOR':
        return [("IN", "IN", minus)]
    if etype == 'DEFORMABLE_MIRROR':
        return [("IN", "IN", "+Z"), ("REFLECT", "REFLECT", "+Z")]
    if etype == 'ABERRATOR':
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
    # The element_type wins over the name prefix: if a user set MIRROR but the name matches a LENS
    # prefix, use the type's default ports, not the lens layout (which builds a bogus REFLECT plane).
    if specs is None or (etype and etype != props.element_type):
        specs = _default_specs_for_type(props.element_type, obj)
    if specs:
        _populate_ports_from_specs(obj, props, specs)
    props.is_source = props.element_type in SOURCE_TYPES
    props.is_detector = props.element_type in DETECTOR_TYPES
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
        props.is_source = props.element_type in SOURCE_TYPES
        props.is_detector = props.element_type in DETECTOR_TYPES
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

        if obj.data and obj.data.users > 1:          # transform_apply rejects multi-user data
            obj.data = obj.data.copy()
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
    OPTICS_OT_diagnose,
    OPTICS_OT_propose_corrections,
    OPTICS_OT_fix_diagnosis,
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
