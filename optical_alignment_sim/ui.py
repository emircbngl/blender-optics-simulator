"""View3D sidebar panels for the Optics workspace."""
from __future__ import annotations

import os
import bpy
from bpy.types import Panel, UIList


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
        col.prop(props, "focal_length")
        col.prop(props, "split_ratio")
        col.prop(props, "reflectivity")
        col.prop(props, "clear_aperture")
        col.prop(props, "wavelength")
        col.prop(props, "waist_um")
        col.prop(props, "pol_angle")
        col.prop(props, "mount_type")
        for dof in props.dofs:
            unit = "deg" if dof.kind in ('TIP', 'TILT', 'ROT') else "mm"
            col.prop(dof, "current", text="%s Current (%s)" % (dof.kind, unit), slider=True)
        row = col.row(align=True)
        row.operator("optics.tag_element", text="Tag Element", icon='CHECKMARK')
        row.operator("optics.auto_detect_ports", text="Detect Ports", icon='FILE_REFRESH')
        col.operator("optics.normalize_import", text="Normalize Import", icon='MOD_MESHDEFORM')
        if not _advanced_enabled():
            return

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

        pcol = col.column(align=True)
        pcol.label(text="Advanced Parameters")
        et = props.element_type
        if et == 'LENS':
            pcol.prop(props, "lens_type")
            pcol.prop(props, "design_wl", text="Design Wavelength (nm)")
        if et == 'PRISM_MIRROR': pcol.prop(props, "prism_angle")
        if et in ('LENS', 'WAVEPLATE', 'PASSTHROUGH'): pcol.prop(props, "refractive_index")
        if et in ('SOURCE', 'FIBER_COLLIMATOR'):
            pcol.prop(props, "pol_type", text="Source Polarization")
            if props.pol_type == 'CIRCULAR': pcol.prop(props, "handedness")
            pcol.prop(props, "linewidth_nm")
            pcol.prop(props, "bandwidth_nm")
            pcol.prop(props, "m2")
        elif et == 'WAVEPLATE':
            pcol.prop(props, "waveplate_order")
            pcol.prop(props, "retardance_deg")
            pcol.prop(props, "fast_axis_deg")
            pcol.prop(props, "design_wl", text="Design Wavelength (nm)")
        elif et == 'POLARIZER':
            pcol.prop(props, "polarizer_type")
            if props.polarizer_type in ('WOLLASTON', 'ROCHON'): pcol.prop(props, "split_angle_deg")
            pcol.prop(props, "pol_axis_deg")
            pcol.prop(props, "extinction")
        elif et == 'BEAMSPLITTER':
            pcol.prop(props, "bs_form"); pcol.prop(props, "is_pbs")
        elif et == 'DICHROIC':
            pcol.prop(props, "pass_type"); pcol.prop(props, "cut_nm")
        elif et == 'FILTER':
            pcol.prop(props, "filt_type")
            if props.filt_type == 'BP':
                pcol.prop(props, "cut_lo_nm"); pcol.prop(props, "cut_hi_nm")
            elif props.filt_type == 'LP': pcol.prop(props, "cut_lo_nm")
            elif props.filt_type == 'SP': pcol.prop(props, "cut_hi_nm")
            else: pcol.prop(props, "od")
        elif et == 'GRATING':
            pcol.prop(props, "lines_per_mm"); pcol.prop(props, "grating_order")
        elif et == 'ATTENUATOR': pcol.prop(props, "od")
        elif et == 'SHUTTER': pcol.prop(props, "shutter_open", text="Open")
        elif et == 'CAVITY': pcol.prop(props, "cavity_spacing_mm")
        elif et == 'CRYSTAL':
            pcol.prop(props, "nl_process")
            if props.nl_process != 'NONE': pcol.prop(props, "nl_efficiency")
        elif et == 'OBJECTIVE':
            pcol.prop(props, "obj_correction"); pcol.prop(props, "obj_mag")
            pcol.prop(props, "obj_na"); pcol.prop(props, "obj_wd"); pcol.prop(props, "obj_long_wd")
            if props.obj_correction == 'INFINITY': pcol.prop(props, "obj_tube_ref")
            tube_length = {'FINITE_160': 160.0, 'FINITE_195': 195.0}.get(props.obj_correction, props.obj_tube_ref)
            pcol.label(text="f_obj = %.2f mm  (M = f_tube/f_obj)" % (tube_length / max(props.obj_mag, 1e-6)), icon='IMAGE_BACKGROUND')
        elif et == 'AOM':
            pcol.prop(props, "aom_freq_mhz"); pcol.prop(props, "aom_sound_mps"); pcol.prop(props, "aom_efficiency")
            theta = (633e-9 * props.aom_freq_mhz * 1e6 / max(props.aom_sound_mps, 1.0)) * 1e3
            pcol.label(text="Deflection %.2f mrad @633 nm  (+%.0f MHz shift)" % (theta, props.aom_freq_mhz), icon='IMAGE_BACKGROUND')
        elif et in ('DETECTOR', 'PHOTODIODE', 'POWER_METER'):
            pcol.prop(props, "analyzer")
            sbox = pcol.box(); sbox.label(text="Sensor", icon='IMAGE_BACKGROUND')
            srow = sbox.row(align=True)
            srow.prop(props, "sensor_px", text="Resolution")
            srow.prop(props, "pixel_size_um", text="Pitch (µm)")
            sbox.prop(props, "sensor_exposure")
            if props.sensor_exposure > 0.0:
                sbox.prop(props, "sensor_read_noise"); sbox.prop(props, "sensor_well_depth")
        elif et == 'ABERRATOR':
            abx = pcol.box(); abx.label(text="Injected Aberration (waves)", icon='MOD_NOISE')
            abx.prop(props, "aberr_spec", index=3, text="Defocus")
            abx.prop(props, "aberr_spec", index=5, text="Astigmatism")
            abx.prop(props, "aberr_spec", index=7, text="Coma")
            abx.prop(props, "aberr_spec", index=10, text="Spherical")
        elif et == 'WAVEFRONT_SENSOR':
            pcol.label(text="Wavefront RMS: %.3f waves" % props.wf_rms, icon='IMAGE_BACKGROUND')
            zrow = pcol.row(align=True)
            zrow.prop(props, "imprint_zonal_px", text="Zonal Pixels")
            zrow.operator("optics.wfs_zonal_render", text="Sensor Render", icon='IMAGE_BACKGROUND')
        if et in ('MIRROR', 'PRISM_MIRROR'):
            pcol.prop(props, "coating"); pcol.prop(props, "mirror_curve")
            if props.mirror_curve != 'FLAT': pcol.prop(props, "radius_curv")
            ibx = pcol.box(); ibx.prop(props, "imprint_surface")
            ibx.label(text="Surface figure → reflected wavefront", icon='MOD_WAVE')
            zrow = ibx.row(align=True)
            zrow.prop(props, "imprint_zonal_px", text="Zonal Pixels")
            zrow.operator("optics.wfs_zonal_render", text="Sensor Render", icon='IMAGE_BACKGROUND')
        pcol.prop(props, "ar_coated")
        if props.ar_coated:
            pcol.prop(props, "ar_reflectance")
        pcol.prop(props, "coating_reflectance")
        pcol.prop(props, "element_transmittance")


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
            ranges = box.row(align=True)
            ranges.prop(dof, "min_val", text="Range Minimum"); ranges.prop(dof, "max_val", text="Range Maximum")
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
        layout = self.layout; props = context.scene.optics
        layout.prop(props, "trace_mode")
        if props.trace_mode == 'ORDER' and _advanced_enabled(): layout.prop(props, "order_csv")
        if _advanced_enabled():
            col = layout.column(align=True)
            col.prop(props, "line_width")
            col.prop(props, "show_ports")
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
        fresh = wm.optics_diagnosis_revision == wm.optics_scene_revision
        col = layout.column(align=True); col.enabled = fresh
        for index, item in enumerate(wm.optics_diagnosis_cache):
            if not item.suggested_fix:
                continue
            row = col.row(align=True)
            row.label(text=item.suggested_fix,
                      icon='CANCEL' if item.severity == 'BAD' else 'ERROR')
            row.operator("optics.fix_diagnosis", text="Fix…").index = index
        if len(wm.optics_diagnosis_cache) and not fresh:
            layout.label(text="Scene changed — re-run Diagnose", icon='ERROR')


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
        row.operator("optics.bake_beams", text="Bake Beams", icon='OUTLINER_OB_MESH'); row.operator("optics.clear_baked", text="Clear Baked", icon='X')
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
    OPTICS_PT_element, OPTICS_PT_library,
    OPTICS_PT_parts, OPTICS_PT_relative_placement, OPTICS_PT_anchoring, OPTICS_PT_assemble, OPTICS_PT_mount, OPTICS_PT_bench_dressing,
    OPTICS_PT_trace, OPTICS_PT_trace_settings, OPTICS_PT_measurements, OPTICS_PT_adaptive_optics,
    OPTICS_PT_diagnostics, OPTICS_PT_corrections, OPTICS_PT_optical_report,
    OPTICS_PT_render, OPTICS_PT_sequence, OPTICS_PT_export, OPTICS_PT_tools_integration,
)


def register():
    for cls in _classes: bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes): bpy.utils.unregister_class(cls)
