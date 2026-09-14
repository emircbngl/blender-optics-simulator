"""Milestone-1 operators: tag elements, auto-detect ports, pick a port from a
selected mesh face, and normalize imported vendor CAD.

Port population logic is factored into module functions so the tag operator can
reuse it directly (avoids operator-in-operator context pitfalls).
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty, BoolProperty, FloatProperty, IntProperty
from mathutils import Vector

from . import geometry, presets
from .properties import PORT_ROLES

# Which element types count as a source / a (terminal) detector for is_source / is_detector.
# The catalog grew past the two canonical types, so flag the whole family or these flags get
# reset to False on auto-detect and the elements drop out of get_state()'s source/detector lists.
SOURCE_TYPES = {'SOURCE', 'FIBER_COLLIMATOR'}
DETECTOR_TYPES = {'DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR'}


def _fill_cache(cache, records):
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


def _store_diagnosis(wm, records):
    cache = wm.optics_diagnosis_cache
    _fill_cache(cache, records)
    wm.optics_diagnosis_bad = sum(item.severity == 'BAD' for item in cache)
    wm.optics_diagnosis_warn = sum(item.severity == 'WARN' for item in cache)
    wm.optics_diagnosis_revision = wm.optics_scene_revision


def _store_corrections(wm, records):
    _fill_cache(wm.optics_correction_cache, records)
    wm.optics_correction_revision = wm.optics_scene_revision


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
        _store_corrections(context.window_manager, result.get("proposals", ()))
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
        if wm.optics_correction_revision != wm.optics_scene_revision:
            cls.poll_message_set("Scene changed — re-run Propose Corrections")
            return False
        return bool(wm.optics_correction_cache)

    def draw(self, context):
        item = context.window_manager.optics_correction_cache[self.index]
        if item.fault_confidence < 0.5:
            self.layout.label(text="Often intentional: %s" % item.maybe_intentional_if,
                              icon='INFO')
        self.layout.label(text=item.suggested_fix or "Review the affected element.")

    def invoke(self, context, event):
        if self.index < 0 or self.index >= len(context.window_manager.optics_correction_cache):
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        item = context.window_manager.optics_correction_cache[self.index]
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
        if obj is not None:
            self.report({'INFO'}, "Selected %s — adjust its settings in Setup > Element" % obj.name)
            return {'FINISHED'}
        self.report({'INFO'}, item.suggested_fix or "Review the bench settings")
        return {'FINISHED'}


# --- shared port helpers ----------------------------------------------------

def _add_port(props, name, role, local_pos, local_normal, ca=12.7):
    p = props.ports.add()
    p.name = name
    p.role = role
    p.local_position = local_pos
    p.local_normal = local_normal
    p.clear_aperture = ca
    return p


# Front-surface optics: the beam turns ON a coated face (the builders put IN and REFLECT on it, #25/#29), not on an
# internal plane. PRISM_MIRROR / BEAMSPLITTER cubes and the corner cube keep their internal-plane layout.
FLAT_REFLECTIVE = ('MIRROR', 'DICHROIC', 'GRATING', 'DEFORMABLE_MIRROR')
AUTOPLACED_KEY = "optics_reflect_autoplaced"


def _largest_flat_face(obj):
    """(center, normal) in local space of the largest coplanar group of mesh faces, preferring faces that look
    along local +Z (the convention every builder and the port presets use for the optical face). Falls back to
    the largest flat group facing any way; None for a mesh with no faces."""
    me = getattr(obj, "data", None)
    polys = getattr(me, "polygons", None)
    if not polys:
        return None
    groups = {}
    for p in polys:
        n = p.normal
        if n.length < 1e-9 or p.area <= 0.0:
            continue
        key = (round(n.x, 3), round(n.y, 3), round(n.z, 3), round(p.center.dot(n), 3))
        g = groups.setdefault(key, [0.0, Vector((0.0, 0.0, 0.0)), n.copy()])
        g[0] += p.area
        g[1] += p.center * p.area
    if not groups:
        return None
    facing_z = {k: g for k, g in groups.items() if g[2].z > 0.999}
    pool = facing_z or groups
    area, weighted, n = max(pool.values(), key=lambda g: g[0])
    return weighted / area, n.normalized()


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
    # These supported element types used to return an empty list for an unrecognised
    # imported mesh. Give an agent a safe, explicit axial fallback instead of reporting
    # "finished" with a stale/empty port set. Special builder geometry can still be
    # corrected by selecting a face and using the visible port picker.
    if etype in ('OBJECTIVE', 'AOM', 'PRISM', 'SLIT', 'KNIFE_EDGE'):
        return [("IN", "IN", minus), ("OUT", "OUT", plus)]
    if etype == 'BEAM_DUMP':
        return [("IN", "IN", minus)]
    if etype == 'CIRCULATOR':
        return [("P1", "IN", "+X"), ("P2", "IN", "+Y"), ("P3", "IN", "-X")]
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
    if props.element_type in FLAT_REFLECTIVE and (etype is None or etype == props.element_type):
        face = _largest_flat_face(obj)
        if face is not None:
            center, normal = face
            props.ports.clear()
            ca = props.clear_aperture if props.clear_aperture > 0.0 else 12.7
            _add_port(props, "IN", 'IN', center, normal, ca)             # the beam enters where it turns
            _add_port(props, "REFLECT", 'REFLECT', center, normal, ca)
            obj[AUTOPLACED_KEY] = True                                   # a guess until the user confirms it
            specs = None
    if specs:
        _populate_ports_from_specs(obj, props, specs)
    props.is_source = props.element_type in SOURCE_TYPES
    props.is_detector = props.element_type in DETECTOR_TYPES
    return len(props.ports)


# --- operators --------------------------------------------------------------

def _addon_owned(obj):
    """True for geometry this add-on authored, which is ALREADY in millimetres.

    Optical elements carry is_optical; bench hardware and baked beams live in their own
    collections and carry the oa_owner tag; mount parts are parented to their optic and follow
    it. Converting a scene must not touch any of them -- they are the reference the user's own
    models are being brought into."""
    from . import optomech, bake
    op = getattr(obj, "optics", None)
    if op is not None and op.is_optical:
        return True
    if "oa_owner" in obj:
        return True
    owned_colls = {optomech.BENCH_COLL, bake.BEAM_COLL}
    return any(c.name in owned_colls for c in obj.users_collection)


def _scale_transform_fcurves(obj, factor):
    """Scale an object's location / scale keyframes by ``factor`` -- otherwise the first frame change replays
    the unscaled keys and undoes the conversion. Blender 4.4+ keeps F-curves in a slotted action's channelbag
    (5.x removed Action.fcurves); 4.2 still has Action.fcurves."""
    ad = getattr(obj, "animation_data", None)
    action = getattr(ad, "action", None) if ad else None
    if action is None:
        return
    fcurves = None
    try:
        from bpy_extras import anim_utils
        if hasattr(anim_utils, "action_get_channelbag_for_slot"):
            bag = anim_utils.action_get_channelbag_for_slot(action, getattr(ad, "action_slot", None))
            fcurves = bag.fcurves if bag is not None else None
    except (ImportError, AttributeError, TypeError):
        fcurves = None
    if fcurves is None:
        fcurves = getattr(action, "fcurves", ())
    for fc in fcurves:
        if fc.data_path in ("location", "scale"):
            for kp in fc.keyframe_points:
                kp.co.y *= factor
                kp.handle_left.y *= factor
                kp.handle_right.y *= factor
            fc.update()


def convert_scene_to_mm(scene):
    """Put the scene on the add-on's millimetre convention WITHOUT resizing anything physically.

    The add-on measures in millimetres and cannot be told otherwise -- the tracer reads world
    coordinates as mm unconditionally. Rather than leave the user rescaling every imported part by
    hand, this brings their scene to the optics: it sets Unit Scale to 0.001 and multiplies their
    own objects by the same factor, so a 2 m model stays 2 m long and an optic added afterwards
    lands at its true size beside it.

    Only unparented objects are scaled -- children inherit their parent's transform, and scaling
    both would square the factor. Add-on geometry is left alone (see _addon_owned): it is already
    mm-authored, which is exactly what the scene is being converted to.

    Returns {ok, factor, scaled, skipped, was_scale_length, msg}."""
    us = scene.unit_settings
    was = float(us.scale_length)
    factor = was / geometry.ADDON_SCALE_LENGTH
    # Ask the SAME question the warning asks. Blender stores scale_length as float32, so writing
    # 0.001 reads back 0.0010000000474974513 -- a tolerance tight enough to call that "different"
    # makes this operation non-idempotent, and pressing the button twice would scale the scene
    # again by 1.0000000475. Sharing one predicate also stops the warning and its fix from ever
    # disagreeing about whether a scene needs converting.
    if geometry.unit_scale_mismatch(scene) is None:
        return {"ok": True, "factor": 1.0, "scaled": 0, "skipped": 0, "was_scale_length": was,
                "msg": "scene already on the millimetre convention"}
    # A scene that DECLARED its units already holds the add-on's geometry at physical size (the builders
    # divide by mm-per-unit), so it is not mm-authored and must scale with everything else -- skipping it
    # shrank a declared bench a thousandfold and read its 326 mm path as 0.326.
    declared = geometry.mm_per_unit(scene) != 1.0
    scaled = skipped = 0
    for obj in scene.objects:
        if obj.parent is not None:            # children ride their parent's transform
            continue
        if _addon_owned(obj) and not declared:
            skipped += 1
            continue
        obj.scale = tuple(s * factor for s in obj.scale)
        obj.location = tuple(c * factor for c in obj.location)
        _scale_transform_fcurves(obj, factor)
        scaled += 1
    us.system = 'METRIC'
    us.scale_length = geometry.ADDON_SCALE_LENGTH
    us.length_unit = 'MILLIMETERS'
    return {"ok": True, "factor": factor, "scaled": scaled, "skipped": skipped,
            "was_scale_length": was,
            "msg": "unit scale %g -> %g; scaled %d of your objects by %g, left %d add-on objects alone"
                   % (was, geometry.ADDON_SCALE_LENGTH, scaled, factor, skipped)}


class OPTICS_OT_convert_scene_units(Operator):
    bl_idname = "optics.convert_scene_units"
    bl_label = "Convert Scene to Millimetres"
    bl_description = ("Set Unit Scale to 0.001 and scale your own objects to match, so they keep "
                      "their physical size and optical components land at their true size")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        res = convert_scene_to_mm(context.scene)
        self.report({'INFO'}, res["msg"])
        return {'FINISHED'}


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
        obj = context.object
        n = do_auto_detect(obj)
        if n == 0:
            self.report({'WARNING'},
                        "No ports detected - set an element type or pick faces with IN Face / Reflect Face")
            return {'CANCELLED'}
        if obj.get(AUTOPLACED_KEY):
            self.report({'WARNING'}, "Detected %d ports. The reflecting surface was put on the largest flat face "
                        "facing +Z -- confirm it is the coated face, or select that face and press Reflect Face" % n)
        else:
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
        ca = props.clear_aperture if props.clear_aperture > 0.0 else 12.7
        # Re-picking a face REPLACES the port of that name: appending left the auto-detected one first in the
        # list, and the tracer reads the first REFLECT/IN it finds, so the user's choice silently did nothing.
        existing = next((i for i, p in enumerate(props.ports) if p.name == name), None)
        if existing is not None:
            port = props.ports[existing]
            port.role, port.local_position, port.local_normal = self.role, center, normal
            props.ports_index = existing
        else:
            _add_port(props, name, self.role, center, normal, ca)
            props.ports_index = len(props.ports) - 1
        if self.role == 'REFLECT' and props.element_type in FLAT_REFLECTIVE:
            for p in props.ports:                                       # front-surface: IN sits on the same face
                if p.role == 'IN':
                    p.local_position, p.local_normal = center, normal
            if AUTOPLACED_KEY in obj:
                del obj[AUTOPLACED_KEY]
        self.report({'INFO'}, "%s port '%s' from face" % ("Moved" if existing is not None else "Added", name))
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

        # Applying rotation/scale and moving the origin changes the object's local frame.
        # Optical ports are stored in that frame, so snapshot their WORLD geometry and
        # re-express it after the normalization. Without this, the visible mesh stayed put
        # while IN/OUT/REFLECT planes jumped (and their normals rotated) on the next trace.
        port_world = []
        props = getattr(obj, "optics", None)
        if props is not None:
            M0 = obj.matrix_world.copy()
            for p in props.ports:
                wp = M0 @ Vector(p.local_position)
                wn = M0.to_3x3() @ Vector(p.local_normal)
                port_world.append((p, wp, wn))

        if obj.data and obj.data.users > 1:          # transform_apply rejects multi-user data
            obj.data = obj.data.copy()
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if self.set_origin_center:
            bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')

        if port_world:
            inv = obj.matrix_world.inverted()
            inv3 = obj.matrix_world.to_3x3().inverted()
            for p, wp, wn in port_world:
                p.local_position = inv @ wp
                local_n = inv3 @ wn
                if local_n.length > 1.0e-12:
                    p.local_normal = local_n.normalized()

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


# --- Design: pure solves and the tolerance scan, from the UI ------------------------------------------

def _show_design(context, lines):
    context.window_manager.optics_design_result = "\n".join(lines)


class _DesignSolve:
    """A pure design calculator: the dialog shows the answer as the inputs change; OK keeps it in the panel.
    Nothing in the scene changes."""
    bl_options = {'REGISTER'}

    def solve(self):
        raise NotImplementedError

    def lines(self, res):
        raise NotImplementedError

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def check(self, context):
        return True                          # redraw the live answer whenever an input changes

    def draw(self, context):
        layout = self.layout
        for name in self.__annotations__:
            layout.prop(self, name)
        res = self.solve()
        box = layout.box()
        for line in (self.lines(res) if res.get("ok") else [res.get("error", "no solution")]):
            box.label(text=line)

    def execute(self, context):
        res = self.solve()
        if not res.get("ok"):
            _show_design(context, [res.get("error", "no solution")])
            self.report({'WARNING'}, res.get("error", "no solution"))
            return {'CANCELLED'}
        _show_design(context, self.lines(res))
        return {'FINISHED'}


class OPTICS_OT_design_telescope(_DesignSolve, Operator):
    bl_idname = "optics.design_telescope"
    bl_label = "Telescope / Beam Expander"
    bl_description = "Afocal two-lens telescope: lens separation and magnification from two focal lengths"

    f1: FloatProperty(name="f1 (mm)", default=50.0)
    f2: FloatProperty(name="f2 (mm)", default=200.0)

    def solve(self):
        from . import optics_api
        return optics_api.design_telescope(self.f1, self.f2)

    def lines(self, res):
        return ["Telescope (%s): lenses %.2f mm apart" % (res["type"], res["sep"]),
                "Magnification %.4g   beam expansion %.4gx" % (res["magnification"], res["beam_expansion"])]


class OPTICS_OT_design_4f(_DesignSolve, Operator):
    bl_idname = "optics.design_4f"
    bl_label = "4f Relay"
    bl_description = "4f relay: object, lens and image spacings and magnification from two focal lengths"

    f1: FloatProperty(name="f1 (mm)", default=100.0)
    f2: FloatProperty(name="f2 (mm)", default=100.0)

    def solve(self):
        from . import optics_api
        return optics_api.design_4f(self.f1, self.f2)

    def lines(self, res):
        a, b, c = res["seps"]
        return ["4f relay: %.2f | %.2f | %.2f mm (total %.2f mm)" % (a, b, c, res["total_length"]),
                "Transverse magnification %.4g" % res["transverse_mag"]]


class OPTICS_OT_mode_match(_DesignSolve, Operator):
    bl_idname = "optics.mode_match"
    bl_label = "Mode Match"
    bl_description = ("Single thin lens that images an input Gaussian waist onto a target waist "
                      "(fiber or cavity coupling); lengths in mm, wavelength in nm")

    w0_in: FloatProperty(name="Input waist (mm)", default=0.3, min=0.0)
    s_in: FloatProperty(name="Input waist to lens (mm)", default=100.0)
    w0_t: FloatProperty(name="Target waist (mm)", default=0.3, min=0.0)
    z_t: FloatProperty(name="Lens to target waist (mm)", default=100.0)
    wavelength_nm: FloatProperty(name="Wavelength (nm)", default=632.8, min=0.0)
    m2: FloatProperty(name="M²", default=1.0, min=1.0)

    def solve(self):
        from . import optics_api
        return optics_api.mode_match(self.w0_in, self.s_in, self.w0_t, self.z_t, self.wavelength_nm, m2=self.m2)

    def lines(self, res):
        return ["Lens f = %.1f mm, input waist %.1f mm before it" % (res["f"], res["s_lens"]),
                "Achieved waist %.4g mm at %.1f mm, coupling %.4f" % (res["achieved_w0"], res["achieved_z"],
                                                                     res["coupling"])]


def _detector_items(self, context):
    from . import tracer
    scene = getattr(context, "scene", None) or bpy.context.scene
    names = sorted(o.name for o in scene.objects
                   if getattr(o, "optics", None) and o.optics.is_optical and o.optics.element_type in tracer.TERMINAL)
    return [(n, n, "") for n in names] or [('', "(no detector)", "")]


class OPTICS_OT_tolerance_scan(Operator):
    bl_idname = "optics.tolerance_scan"
    bl_label = "Tolerance Scan"
    bl_description = ("Monte-Carlo alignment tolerance: perturb the selected elements' poses and report how far "
                      "the beam walks at the target. Poses and the trace are restored afterwards")
    bl_options = {'REGISTER'}

    target: EnumProperty(name="Target", items=_detector_items)
    sigma_pos_mm: FloatProperty(name="Position sigma (mm)", default=0.1, min=0.0)
    sigma_ang_deg: FloatProperty(name="Angle sigma (deg, per axis)", default=0.05, min=0.0)
    n: IntProperty(name="Samples", default=200, min=1, max=100000)
    seed: IntProperty(name="Seed", default=0)
    tol_mm: FloatProperty(name="Yield tolerance (mm, 0 = off)", default=0.0, min=0.0)

    @staticmethod
    def _members(context):
        return [o.name for o in getattr(context, "selected_objects", ())
                if getattr(o, "optics", None) and o.optics.is_optical]

    @classmethod
    def poll(cls, context):
        if not cls._members(context):
            cls.poll_message_set("Select the elements to perturb")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        from . import optics_api
        res = optics_api.tolerance_scan(self._members(context), target=self.target,
                                        sigma_pos_mm=self.sigma_pos_mm, sigma_ang_deg=self.sigma_ang_deg,
                                        n=self.n, seed=self.seed, tol_mm=self.tol_mm or None)
        if not res.get("ok"):
            _show_design(context, [res.get("error", "tolerance scan failed")])
            self.report({'WARNING'}, res.get("error", "tolerance scan failed"))
            return {'CANCELLED'}
        rms = res.get("pointing_rms_mm")
        lines = ["Tolerance at %s, %d samples: hit rate %.3f" % (self.target, res["n"], res["hit_rate"])]
        if rms is not None:
            lines.append("Walk RMS %.4g mm, p95 %.4g mm, max %.4g mm"
                         % (rms, res["pointing_p95_mm"], res["pointing_max_mm"]))
        if "yield" in res:
            lines.append("Yield within %.3g mm: %.3f" % (res["tol_mm"], res["yield"]))
        _show_design(context, lines)
        return {'FINISHED'}


_classes = (
    OPTICS_OT_design_telescope,
    OPTICS_OT_design_4f,
    OPTICS_OT_mode_match,
    OPTICS_OT_tolerance_scan,
    OPTICS_OT_diagnose,
    OPTICS_OT_propose_corrections,
    OPTICS_OT_fix_diagnosis,
    OPTICS_OT_tag_element,
    OPTICS_OT_auto_detect_ports,
    OPTICS_OT_pick_port_from_face,
    OPTICS_OT_normalize_import,
    OPTICS_OT_convert_scene_units,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
