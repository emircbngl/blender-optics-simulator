"""View3D sidebar panels for the Optics workspace."""
from __future__ import annotations

import os
import textwrap
import bpy
from bpy.types import Panel, UIList

from . import param_schema


def _mark_expensive_operators():
    """Keep long-running UI actions explicit before their classes are registered."""
    from . import alignment, optomech, render, tracer
    classes = (
        optomech.OPTICS_OT_dress_bench,
        tracer.OPTICS_OT_trace_now,
        alignment.OPTICS_OT_refresh_report,
        alignment.OPTICS_OT_align_element,
        alignment.OPTICS_OT_align_all,
        alignment.OPTICS_OT_auto_align,
        render.OPTICS_OT_render_preview,
        render.OPTICS_OT_render_final,
    )
    suffix = "May pause the UI for a few seconds."
    for cls in classes:
        if not cls.bl_description.endswith(suffix):
            cls.bl_description = "%s %s" % (cls.bl_description.rstrip(". "), suffix)


_mark_expensive_operators()


def _advanced_enabled():
    from .prefs import get_prefs
    prefs = get_prefs()
    return bool(prefs and prefs.show_advanced)


# Field labels that need units or wording the property name does not carry.
_FIELD_TEXT = {"clear_aperture": "Clear Radius (mm)", "shutter_open": "Open", "pol_type": "Source Polarization",
               "design_wl": "Design Wavelength (nm)"}


def _display_value(props, name):
    value = getattr(props, name)
    rna = props.bl_rna.properties[name]
    if rna.type == 'ENUM':
        item = rna.enum_items.get(value)
        return item.name if item else str(value)
    if isinstance(value, float):
        return "%g" % value
    return str(value)


def _draw_knob(layout, obj, index, dof):
    """One knob: - / slider / +. Each press turns it by the DOF's own step."""
    unit = "deg" if dof.kind in ('TIP', 'TILT', 'ROT') else "mm"
    row = layout.row(align=True)
    op = row.operator("optics.nudge_dof", text="", icon='REMOVE')
    op.name, op.index, op.direction = obj.name, index, -1
    row.prop(dof, "current", text="%s (%s)" % (dof.kind, unit), slider=True)
    op = row.operator("optics.nudge_dof", text="", icon='ADD')
    op.name, op.index, op.direction = obj.name, index, 1


# A proposal can name a perfectly valid MCP/API tool without having a matching modal Blender
# operator. Do not render a clickable Fix button for those records: the old UI let the user click
# through to "No interactive operator" and made an advisory look like an action.
_INTERACTIVE_FIX_TOOLS = frozenset(('align_element', 'auto_align', 'place_relative'))


class OPTICS_UL_ports(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        ico = {'IN': 'IMPORT', 'OUT': 'EXPORT', 'REFLECT': 'MOD_MIRROR',
               'TRANSMIT': 'MOD_TRANSPARENT'}.get(item.role, 'DOT')
        row.label(text="", icon=ico)
        row.prop(item, "name", text="", emboss=False)
        row.label(text=item.role)


class _OpticsPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"


class OPTICS_PT_setup(_OpticsPanel, Panel):
    bl_label = "Setup"
    bl_idname = "OPTICS_PT_setup"
    bl_order = 0
    def draw(self, context):
        self.layout.operator("optics.build_example", text="Browse Examples…", icon='ASSET_MANAGER')
        if len(context.scene.objects) == 0:
            self.layout.label(text="Empty scene — Browse Examples… or add an element.", icon='INFO')


class OPTICS_PT_place(_OpticsPanel, Panel):
    bl_label = "Place"
    bl_idname = "OPTICS_PT_place"
    bl_order = 100
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass


class OPTICS_PT_simulate(_OpticsPanel, Panel):
    bl_label = "Simulate"
    bl_idname = "OPTICS_PT_simulate"
    bl_order = 200
    def draw(self, context): pass


class OPTICS_PT_inspect(_OpticsPanel, Panel):
    bl_label = "Inspect"
    bl_idname = "OPTICS_PT_inspect"
    bl_order = 300
    bl_options = {'DEFAULT_CLOSED'}
    def draw_header(self, context):
        wm = context.window_manager
        if (wm.optics_diagnosis_revision >= 0 and
                wm.optics_diagnosis_revision == wm.optics_scene_revision):
            self.layout.label(text="%d BAD · %d WARN" %
                              (wm.optics_diagnosis_bad, wm.optics_diagnosis_warn))

    def draw(self, context): pass


class OPTICS_PT_present(_OpticsPanel, Panel):
    bl_label = "Present"
    bl_idname = "OPTICS_PT_present"
    bl_order = 400
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass


class OPTICS_PT_element(_OpticsPanel, Panel):
    bl_label = "Element"
    bl_idname = "OPTICS_PT_element"
    bl_parent_id = "OPTICS_PT_setup"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        obj = getattr(context, "object", None)
        if obj is None:
            layout.label(text="Select an object", icon='INFO')
            return
        props = obj.optics
        layout.prop(props, "is_optical")
        col = layout.column()
        col.enabled = props.is_optical
        col.prop(props, "element_type")
        et = props.element_type
        col.use_property_split = True
        col.use_property_decorate = False
        for name in param_schema.visible(props, "essentials"):
            col.prop(props, name, text=_FIELD_TEXT.get(name, ""))
        if et == 'OBJECTIVE':
            tube_length = {'FINITE_160': 160.0, 'FINITE_195': 195.0}.get(props.obj_correction, props.obj_tube_ref)
            col.label(text="f_obj = %.2f mm  (M = f_tube/f_obj)" % (tube_length / max(props.obj_mag, 1e-6)),
                      icon='IMAGE_BACKGROUND')
        elif et == 'AOM':
            theta = (633e-9 * props.aom_freq_mhz * 1e6 / max(props.aom_sound_mps, 1.0)) * 1e3
            col.label(text="Deflection %.2f mrad @633 nm  (+%.0f MHz shift)" % (theta, props.aom_freq_mhz),
                      icon='IMAGE_BACKGROUND')
        elif et == 'WAVEFRONT_SENSOR':
            col.label(text="Wavefront RMS: %.3f waves" % props.wf_rms, icon='IMAGE_BACKGROUND')
        elif et == 'ABERRATOR':
            abx = col.box(); abx.label(text="Injected Aberration (waves)", icon='MOD_NOISE')
            abx.prop(props, "aberr_spec", index=3, text="Defocus")
            abx.prop(props, "aberr_spec", index=5, text="Astigmatism")
            abx.prop(props, "aberr_spec", index=7, text="Coma")
            abx.prop(props, "aberr_spec", index=10, text="Spherical")
        col.prop(props, "mount_type")
        for index, dof in enumerate(props.dofs):
            _draw_knob(col, obj, index, dof)
        row = col.row(align=True)
        row.operator("optics.tag_element", text="Tag Element", icon='CHECKMARK')
        row.operator("optics.auto_detect_ports", text="Detect Ports", icon='FILE_REFRESH')
        if et in ('MIRROR', 'DICHROIC', 'GRATING', 'DEFORMABLE_MIRROR'):
            # where the beam turns decides the path length; a guessed coated face must be easy to correct
            frow = col.row(align=True)
            frow.operator("optics.pick_port_from_face", text="Reflect Face", icon='MOD_MIRROR').role = 'REFLECT'
            if obj.get("optics_reflect_autoplaced"):
                col.label(text="Coated face guessed (largest flat +Z face) — confirm with Reflect Face", icon='ERROR')
        col.operator("optics.normalize_import", text="Normalize Import", icon='MOD_MESHDEFORM')
        if not _advanced_enabled():
            return
        # Advanced hides only technical fields; every physics parameter is in the panel or in More.
        box = col.box()
        box.label(text="Ports", icon='EMPTY_ARROWS')
        box.template_list("OPTICS_UL_ports", "", props, "ports", props, "ports_index", rows=3)
        prow = box.row(align=True)
        op = prow.operator("optics.pick_port_from_face", text="IN Face"); op.role = 'IN'
        op = prow.operator("optics.pick_port_from_face", text="OUT Face"); op.role = 'OUT'
        op = prow.operator("optics.pick_port_from_face", text="Reflect Face"); op.role = 'REFLECT'
        if 0 <= props.ports_index < len(props.ports):
            port = props.ports[props.ports_index]
            pc = box.column(align=True)
            pc.prop(port, "name")
            pc.prop(port, "role")
            pc.prop(port, "local_position", text="Local Position (mm)")
            pc.prop(port, "local_normal")
            pc.prop(port, "clear_aperture", text="Clear Aperture (mm)")


class OPTICS_PT_element_more(_OpticsPanel, Panel):
    """The rest of the selected type's parameters. Collapsed by default; Blender remembers it open."""
    bl_label = "More"
    bl_idname = "OPTICS_PT_element_more"
    bl_parent_id = "OPTICS_PT_element"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.optics.is_optical

    def draw(self, context):
        obj = context.object
        props = obj.optics
        col = self.layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        shown = param_schema.visible(props, "more")
        for name in shown:
            col.prop(props, name, text=_FIELD_TEXT.get(name, ""))
        if "imprint_zonal_px" in shown:
            col.operator("optics.wfs_zonal_render", text="Sensor Render", icon='IMAGE_BACKGROUND')
        info = param_schema.INFO.get(props.element_type, ())
        if info:
            box = col.box()
            box.label(text="Part data (not used by the trace)", icon='INFO')
            for name in info:
                box.label(text="%s: %s" % (props.bl_rna.properties[name].name, _display_value(props, name)))


class OPTICS_PT_library(_OpticsPanel, Panel):
    bl_label = "Component Library"
    bl_idname = "OPTICS_PT_library"
    bl_parent_id = "OPTICS_PT_setup"
    bl_order = 20
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.add_from_library", text="Add from Library", icon='ADD')
        layout.operator("optics.import_mesh", text="Import Mesh", icon='IMPORT')
        row = layout.row(align=True)
        row.operator("optics.convert_step", text="Convert STEP", icon='FILE_CACHE')
        row.operator("optics.save_to_library", text="Save to Library", icon='FILE_TICK')
        from .prefs import get_prefs
        prefs = get_prefs(); box = layout.box()
        if prefs:
            mesh_dir = os.path.basename(prefs.mesh_dir.rstrip("/\\")) if prefs.mesh_dir else ""
            box.label(text="Mesh folder: %s" % (mesh_dir or "(set in Preferences)"), icon='FILE_FOLDER' if mesh_dir else 'ERROR')
            box.label(text="FreeCAD (STEP): %s" % ("ready" if prefs.freecad_path else "not set"),
                      icon='CHECKMARK' if prefs.freecad_path else 'ERROR')
        else: box.label(text="Open Add-on Preferences to set mesh folder", icon='INFO')


class OPTICS_PT_parts(_OpticsPanel, Panel):
    bl_label = "Parts"
    bl_idname = "OPTICS_PT_parts"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 0
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.swap_part", text="Swap Part", icon='FILE_REFRESH')
        layout.label(text="Replaces the mesh while preserving ports, mount, and beam path.")
        obj = getattr(context, "object", None)
        props = getattr(obj, "optics", None) if obj is not None else None
        if props and props.is_optical and props.part_key: layout.label(text="Active part: %s" % props.part_key, icon='MESH_DATA')


class OPTICS_PT_relative_placement(_OpticsPanel, Panel):
    bl_label = "Relative Placement"
    bl_idname = "OPTICS_PT_relative_placement"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 10
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.place_relative_xyz", text="Offset XYZ…", icon='EMPTY_ARROWS')
        layout.operator("optics.place_relative", text="Along Beam / Axis…", icon='TRANSFORM_ORIGINS')
        row = layout.row(align=True)
        row.operator("optics.place_on_grid_dialog", text="Grid…", icon='SNAP_GRID')
        row.operator("optics.place_on_rail_dialog", text="Rail…", icon='TRACKING')


class OPTICS_PT_anchoring(_OpticsPanel, Panel):
    bl_label = "Anchoring"
    bl_idname = "OPTICS_PT_anchoring"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout; row = layout.row(align=True)
        row.operator("optics.create_anchor", text="Create Anchor", icon='EMPTY_AXIS')
        row.operator("optics.clear_anchor", text="Clear Anchor", icon='X')
        obj = getattr(context, "object", None); props = getattr(obj, "optics", None) if obj is not None else None
        if props and props.is_optical and props.anchor is not None: layout.label(text="Anchored to: %s" % props.anchor.name, icon='LINKED')


class OPTICS_PT_assemble(_OpticsPanel, Panel):
    bl_label = "Assemble"
    bl_idname = "OPTICS_PT_assemble"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 30
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass


class OPTICS_PT_mount(_OpticsPanel, Panel):
    bl_label = "Mount & Adjustment"
    bl_idname = "OPTICS_PT_mount"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 40
    def draw(self, context):
        layout = self.layout; obj = getattr(context, "object", None)
        props = getattr(obj, "optics", None) if obj is not None else None
        body = layout.column(); body.enabled = bool(props and props.is_optical)
        if not props or not props.is_optical:
            body.label(text="Select an optical element.", icon='INFO'); return
        row = body.row(align=True)
        row.operator("optics.set_mount_preset", text="Set Mount Preset", icon='PRESET')
        row.operator("optics.save_mount_preset", text="Save Mount Preset", icon='ADD')
        if props.mount_preset: body.label(text="Preset: %s" % props.mount_preset, icon='CHECKMARK')
        row = body.row(align=True)
        row.operator("optics.capture_base_pose", text="Capture Base Pose", icon='EMPTY_AXIS')
        row.operator("optics.zero_dofs", text="Zero DOFs", icon='LOOP_BACK')
        box = body.box(); hdr = box.row(align=True)
        hdr.label(text="Adjustment DOFs (knobs)", icon='CON_ROTLIKE')
        hdr.operator("optics.define_dof", text="Add DOF", icon='ADD')
        hdr.operator("optics.pick_pivot", text="Pick Pivot", icon='PIVOT_CURSOR')
        if len(props.dofs) and not props.base_pose_set: box.label(text="Set coarse pose to activate knobs", icon='ERROR')
        for index, dof in enumerate(props.dofs):
            row = box.row(align=True); row.label(text=dof.kind)
            row.operator("optics.remove_dof", text="", icon='X').index = index
            _draw_knob(box, obj, index, dof)
            ranges = box.row(align=True)
            ranges.prop(dof, "min_val", text="Range Minimum"); ranges.prop(dof, "max_val", text="Range Maximum")
            ranges.prop(dof, "step", text="Step")
        if not _advanced_enabled(): return
        mbox = body.box(); header = mbox.row(align=True)
        header.label(text="Mechanical Limits", icon='CONSTRAINT')
        header.operator("optics.add_mech_link", text="", icon='ADD')
        header.operator("optics.check_mechanics", text="Check Mechanics", icon='CHECKMARK')
        for index, link in enumerate(props.mech):
            link_box = mbox.box(); top = link_box.row(align=True)
            top.prop(link, "kind", text=""); top.operator("optics.remove_mech_link", text="", icon='X').index = index
            link_box.prop_search(link, "target", bpy.data, "objects", text="Compared With")
            ranges = link_box.row(align=True)
            ranges.prop(link, "insert_min", text="Minimum (mm)"); ranges.prop(link, "insert_max", text="Maximum (mm)")
            icon = {'OK': 'CHECKMARK', 'WARN': 'ERROR', 'BAD': 'CANCEL'}.get(link.state, 'QUESTION')
            link_box.label(text=link.detail or link.state, icon=icon)


class OPTICS_PT_bench_dressing(_OpticsPanel, Panel):
    bl_label = "Bench Dressing"
    bl_idname = "OPTICS_PT_bench_dressing"
    bl_parent_id = "OPTICS_PT_place"
    bl_order = 50
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        from . import optomech
        props = context.scene.optics; row = layout.row(align=True)
        row.prop(props, "bench_grid_units", text="Grid")
        if props.bench_grid_units == 'CUSTOM': row.prop(props, "bench_grid_mm", text="Grid Spacing (mm)")
        layout.prop(props, "beam_height_mm", text="Beam Height (mm)")
        layout.operator("optics.dress_bench", icon='SNAP_FACE', text="Strip Bench Dressing" if optomech.is_dressed(context.scene) else "Dress Bench (hole grid + posts)")


class OPTICS_PT_trace(_OpticsPanel, Panel):
    bl_label = "Trace"
    bl_idname = "OPTICS_PT_trace"
    bl_parent_id = "OPTICS_PT_simulate"
    bl_order = 0
    def draw(self, context):
        layout = self.layout; props = context.scene.optics
        layout.prop(props, "live_enabled", text="Live", icon='PAUSE' if props.live_enabled else 'PLAY', toggle=True)
        row = layout.row(align=True)
        row.operator("optics.trace_now", text="Trace Now", icon='TRACKING')
        row.operator("optics.clear_beams", text="Clear Beams", icon='X')


class OPTICS_PT_trace_settings(_OpticsPanel, Panel):
    bl_label = "Trace Settings"
    bl_idname = "OPTICS_PT_trace_settings"
    bl_parent_id = "OPTICS_PT_trace"
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        from . import geometry
        layout = self.layout; props = context.scene.optics
        layout.prop(props, "trace_mode")
        if props.trace_mode == 'ORDER': layout.prop(props, "order_csv")
        if _advanced_enabled():
            col = layout.column(align=True)
            col.prop(props, "line_width")
            col.prop(props, "show_ports")
            col.prop(props, "beam_radius_scale")
            if geometry.unit_scale_mismatch(context.scene):
                warn = col.box().column(align=True)
                if props.scene_units_authoritative:
                    warn.label(text="Working in declared scene units", icon='CHECKMARK')
                    warn.label(text="Opto-mech hardware unsupported here", icon='ERROR')
                else:
                    warn.label(text="Scene is not on the mm convention", icon='ERROR')
                    warn.operator("optics.convert_scene_units", icon='MOD_LENGTH')
                warn.prop(props, "scene_units_authoritative")
            col.prop(props, "oob_display")
            col.prop(props, "auto_color")
            col.prop(props, "max_segments")
            col.prop(props, "max_depth")
            col.prop(props, "model_ghosts")
            if props.model_ghosts:
                col.prop(props, "ghost_floor")
                col.prop(props, "max_ghost_depth")


class OPTICS_PT_measurements(_OpticsPanel, Panel):
    bl_label = "Measurements"
    bl_idname = "OPTICS_PT_measurements"
    bl_parent_id = "OPTICS_PT_simulate"
    bl_order = 10
    def draw(self, context):
        layout = self.layout; row = layout.row(align=True)
        row.operator("optics.scan", text="Scan", icon='FCURVE'); row.operator("optics.fringe_image", text="Fringe Image", icon='IMAGE_DATA'); row.operator("optics.power_budget", text="Power Budget", icon='TEXT')
        row = layout.row(align=True)
        row.operator("optics.beam_profile", text="Beam Profile", icon='IPO_EASE_IN_OUT'); row.operator("optics.quantum", text="Quantum", icon='EXPERIMENTAL')
        box = layout.box(); row = box.row(align=True)
        row.prop(context.scene.optics, "monitor_show", text="Sensor Window (bottom-left)", icon='IMAGE_BACKGROUND', toggle=True)
        row.prop(context.scene.optics, "monitor_size", text="Size (px)")
        box.operator("optics.save_sensor", text="Save Sensor", icon='FILE_TICK')
        from . import alignment, tracer
        for obj in context.scene.objects:
            props = getattr(obj, "optics", None)
            if (props and props.is_optical and
                    props.element_type in ('DETECTOR', 'PHOTODIODE', 'POWER_METER')):
                power, _visibility, _strongest = alignment.measure(
                    tracer.cached_segments, obj.name, props.analyzer)
                if power < 0.0:
                    layout.label(text="No beam reaches %s — run Diagnose." % obj.name,
                                 icon='ERROR')


class OPTICS_PT_adaptive_optics(_OpticsPanel, Panel):
    bl_label = "Adaptive Optics"
    bl_idname = "OPTICS_PT_adaptive_optics"
    bl_parent_id = "OPTICS_PT_simulate"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.ao_close_loop", text="Close AO Loop", icon='MOD_NOISE')
        layout.label(text="Sense wavefront → drive deformable mirror → flatten.")
        obj = getattr(context, "object", None); props = getattr(obj, "optics", None) if obj is not None else None
        if props and props.is_optical:
            if props.element_type == 'WAVEFRONT_SENSOR': layout.label(text="WFS RMS: %.3f waves" % props.wf_rms, icon='IMAGE_BACKGROUND')
            elif props.element_type == 'DEFORMABLE_MIRROR': layout.operator("optics.dm_flatten", text="Flatten DM", icon='MOD_SMOOTH')


class OPTICS_PT_diagnostics(_OpticsPanel, Panel):
    bl_label = "Diagnostics"
    bl_idname = "OPTICS_PT_diagnostics"
    bl_parent_id = "OPTICS_PT_inspect"
    bl_order = 0
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.diagnose", text="Diagnose", icon='VIEWZOOM')
        wm = context.window_manager
        if wm.optics_diagnosis_revision < 0:
            layout.label(text="No diagnosis yet — press Diagnose", icon='INFO')
            return
        fresh = wm.optics_diagnosis_revision == wm.optics_scene_revision
        if fresh and not len(wm.optics_diagnosis_cache):
            layout.label(text="No issues", icon='CHECKMARK')
            return
        col = layout.column(align=True); col.enabled = fresh
        for item in wm.optics_diagnosis_cache:
            col.label(text=item.detail, icon='CANCEL' if item.severity == 'BAD' else 'ERROR')
        if not fresh:
            layout.label(text="Scene changed — re-run Diagnose", icon='ERROR')


class OPTICS_PT_corrections(_OpticsPanel, Panel):
    bl_label = "Corrections"
    bl_idname = "OPTICS_PT_corrections"
    bl_parent_id = "OPTICS_PT_inspect"
    bl_order = 10
    def draw(self, context):
        layout = self.layout
        layout.operator("optics.propose_corrections", text="Propose Corrections", icon='LIGHT')
        wm = context.window_manager
        fresh = wm.optics_correction_revision == wm.optics_scene_revision
        col = layout.column(align=True); col.enabled = fresh
        for index, item in enumerate(wm.optics_correction_cache):
            if not item.suggested_fix:
                continue
            box = col.box()
            box.label(text=item.element or "Bench", icon='CANCEL' if item.severity == 'BAD' else 'ERROR')
            width = max(18, int(getattr(getattr(context, 'region', None), 'width', 320) / 8) - 6)
            for line in textwrap.wrap(item.suggested_fix, width=width):
                box.label(text=line)
            if item.tool in _INTERACTIVE_FIX_TOOLS:
                box.operator("optics.fix_diagnosis", text="Review and Fix…").index = index
            else:
                box.operator("optics.fix_diagnosis", text="Select Element…", icon='RESTRICT_SELECT_OFF').index = index
        if len(wm.optics_correction_cache) and not fresh:
            layout.label(text="Scene changed — re-run Propose Corrections", icon='ERROR')


class OPTICS_PT_optical_report(_OpticsPanel, Panel):
    bl_label = "Optical Report"
    bl_idname = "OPTICS_PT_optical_report"
    bl_parent_id = "OPTICS_PT_inspect"
    bl_order = 20
    _ICON = {'OK': 'CHECKMARK', 'WARN': 'ERROR', 'BAD': 'CANCEL', 'UNKNOWN': 'QUESTION'}
    def draw(self, context):
        from . import pathstats, tracer
        layout = self.layout; scene = context.scene; col = layout.column(align=True)
        terminal_names = [o.name for o in scene.objects
                          if getattr(o, "optics", None) and o.optics.element_type in tracer.TERMINAL
                          and o.optics.element_type != 'BEAM_DUMP']
        path_by_detector = {
            row["detector"]: row for row in
            pathstats.detector_path_statistics(tracer.cached_segments, terminal_names)["detectors"]
        }
        for obj in scene.objects:
            props = getattr(obj, "optics", None)
            if not props or not props.is_optical or props.element_type == 'SOURCE': continue
            box = col.box(); row = box.row(align=True)
            row.label(text=obj.name, icon=self._ICON.get(props.align_state, 'QUESTION'))
            if any(dof.kind in ('TIP', 'TILT', 'ROT') for dof in props.dofs): row.operator("optics.align_element", text="Align Element", icon='CON_TRACKTO').name = obj.name
            box.label(text="Position %.2f mm   Angle %.2f deg" % (props.misalign_pos_mm, props.misalign_ang_deg))
            if props.element_type in ('DETECTOR', 'PHOTODIODE', 'POWER_METER'):
                row = box.row(align=True)
                row.operator("optics.sensor_monitor", text="Live Sensor Window", icon='IMAGE_BACKGROUND').name = obj.name
                row.operator("optics.save_sensor", text="Save Sensor", icon='FILE_TICK').name = obj.name
                if props.meas_power >= 0.0:
                    box.label(text="Power %.3f" % props.meas_power)
                    if props.meas_pol: box.label(text="Polarization: %s" % props.meas_pol)
                    if props.meas_visibility >= 0.0: box.label(text="Visibility %.3f" % props.meas_visibility)
                    if props.meas_text: box.label(text=props.meas_text)
                else:
                    box.label(text="No beam")
            path_row = path_by_detector.get(obj.name)
            if path_row and path_row["arrival_count"]:
                phase_lo, phase_hi = path_row["phase_opl_range_mm"]
                geom_lo, geom_hi = path_row["geometric_length_range_mm"]
                if path_row["arrival_count"] == 1:
                    box.label(text="Phase OPL %.3f mm" % phase_lo, icon='DRIVER_DISTANCE')
                    box.label(text="Geometric path %.3f mm" % geom_lo)
                else:
                    box.label(text="Phase OPL %.3f–%.3f mm (%d arrivals)"
                              % (phase_lo, phase_hi, path_row["arrival_count"]), icon='DRIVER_DISTANCE')
                    box.label(text="Geometric path %.3f–%.3f mm" % (geom_lo, geom_hi))
                box.label(text="Phase OPL only — group delay/GDD not modeled", icon='INFO')
            if props.mech_state not in ('UNKNOWN', 'OK'): box.label(text="Mechanical: %s" % props.mech_state, icon='CONSTRAINT')
            if props.align_detail: box.label(text=props.align_detail, icon='ERROR')
        if _advanced_enabled():
            box = layout.box(); box.label(text="Thresholds"); row = box.row(align=True)
            row.prop(scene.optics, "ok_pos_mm", text="Position OK (mm)"); row.prop(scene.optics, "ok_ang_deg", text="Angle OK (deg)")
            row = box.row(align=True)
            row.prop(scene.optics, "warn_pos_mm", text="Position Warning (mm)"); row.prop(scene.optics, "warn_ang_deg", text="Angle Warning (deg)")


class OPTICS_PT_render(_OpticsPanel, Panel):
    bl_label = "Render"
    bl_idname = "OPTICS_PT_render"
    bl_parent_id = "OPTICS_PT_present"
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout; row = layout.row(align=True)
        row.operator("optics.bake_beams", text="Beams to Mesh", icon='OUTLINER_OB_MESH'); row.operator("optics.clear_baked", text="Clear Baked", icon='X')
        from . import handlers
        if handlers.beams_need_render_lock(context.scene):
            box = layout.box()
            box.label(text="Animated optics: renders keep the baked beams", icon='ERROR')
            box.prop(context.scene.render, "use_lock_interface", text="Lock Interface (re-bake per frame)")
        layout.label(text="Camera"); grid = layout.grid_flow(columns=4, align=True)
        for preset in ('HERO', 'TOP', 'FRONT', 'SIDE'): grid.operator("optics.set_camera", text=preset.title()).preset = preset
        layout.label(text="Background"); layout.prop(context.scene.optics, "bg_preset", text=""); layout.prop(context.scene.optics, "realistic_optics")
        col = layout.column(align=True)
        col.operator("optics.render_preview", text="Render Preview", icon='RENDER_STILL'); col.operator("optics.render_final", text="Render Final", icon='RENDER_RESULT'); col.operator("optics.reset_render_style", text="Reset Render Style", icon='LOOP_BACK')


class OPTICS_PT_sequence(_OpticsPanel, Panel):
    bl_label = "Sequence"
    bl_idname = "OPTICS_PT_sequence"
    bl_parent_id = "OPTICS_PT_present"
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): pass


class OPTICS_PT_export(_OpticsPanel, Panel):
    bl_label = "Export"
    bl_idname = "OPTICS_PT_export"
    bl_parent_id = "OPTICS_PT_present"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context): self.layout.operator("optics.export_svg", text="Export SVG", icon='EXPORT')


class OPTICS_PT_tools_integration(_OpticsPanel, Panel):
    bl_label = "Tools & Integration"
    bl_idname = "OPTICS_PT_tools_integration"
    bl_parent_id = "OPTICS_PT_present"
    bl_order = 900
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        from . import bridge
        running = bridge.is_running(); layout = self.layout
        layout.operator("optics.bridge_toggle", icon='CONSOLE', depress=running, text="Stop MCP Bridge" if running else "Start MCP Bridge")
        layout.label(text="MCP bridge: %s" % bridge.info(), icon='LINKED' if running else 'UNLINKED')


_classes = (
    OPTICS_UL_ports,
    OPTICS_PT_setup, OPTICS_PT_place, OPTICS_PT_simulate, OPTICS_PT_inspect, OPTICS_PT_present,
    OPTICS_PT_element, OPTICS_PT_element_more, OPTICS_PT_library,
    OPTICS_PT_parts, OPTICS_PT_relative_placement, OPTICS_PT_anchoring, OPTICS_PT_assemble, OPTICS_PT_mount, OPTICS_PT_bench_dressing,
    OPTICS_PT_trace, OPTICS_PT_trace_settings, OPTICS_PT_measurements, OPTICS_PT_adaptive_optics,
    OPTICS_PT_diagnostics, OPTICS_PT_corrections, OPTICS_PT_optical_report,
    OPTICS_PT_render, OPTICS_PT_sequence, OPTICS_PT_export, OPTICS_PT_tools_integration,
)


def register():
    for cls in _classes: bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes): bpy.utils.unregister_class(cls)
