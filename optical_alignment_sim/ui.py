"""View3D sidebar UI ("Optics" tab). Milestone 1: element tagging + ports.
Later milestones add Mount, Simulation, Report and Render panels."""
from __future__ import annotations

import os

import bpy
from bpy.types import Panel, UIList


class OPTICS_UL_ports(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        ico = {'IN': 'IMPORT', 'OUT': 'EXPORT', 'REFLECT': 'MOD_MIRROR',
               'TRANSMIT': 'MOD_TRANSPARENT'}.get(item.role, 'DOT')
        row.label(text="", icon=ico)
        row.prop(item, "name", text="", emboss=False)
        row.label(text=item.role)


class OPTICS_PT_tag(Panel):
    bl_label = "Element"
    bl_idname = "OPTICS_PT_tag"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        if obj is None:
            layout.label(text="Select an object", icon='INFO')
            return

        props = obj.optics
        layout.prop(props, "is_optical")

        col = layout.column()
        col.enabled = props.is_optical
        col.prop(props, "element_type")

        row = col.row(align=True)
        row.operator("optics.tag_element", icon='CHECKMARK')
        row.operator("optics.auto_detect_ports", text="", icon='FILE_REFRESH')
        col.operator("optics.normalize_import", icon='MOD_MESHDEFORM')

        # Ports
        box = col.box()
        box.label(text="Ports", icon='EMPTY_ARROWS')
        box.template_list("OPTICS_UL_ports", "", props, "ports", props, "ports_index", rows=3)
        prow = box.row(align=True)
        op = prow.operator("optics.pick_port_from_face", text="+ IN face")
        op.role = 'IN'
        op = prow.operator("optics.pick_port_from_face", text="+ OUT face")
        op.role = 'OUT'
        op = prow.operator("optics.pick_port_from_face", text="+ REFLECT")
        op.role = 'REFLECT'

        if 0 <= props.ports_index < len(props.ports):
            p = props.ports[props.ports_index]
            pc = box.column(align=True)
            pc.prop(p, "name")
            pc.prop(p, "role")
            pc.prop(p, "local_position")
            pc.prop(p, "local_normal")
            pc.prop(p, "clear_aperture")

        # Parameters (only the relevant subset per element type)
        pcol = col.column(align=True)
        pcol.label(text="Parameters")
        et = props.element_type
        if et == 'LENS':
            pcol.prop(props, "focal_length")
            pcol.prop(props, "design_wl")
        if et in ('BEAMSPLITTER', 'DICHROIC'):
            pcol.prop(props, "split_ratio")
        if et == 'PRISM_MIRROR':
            pcol.prop(props, "prism_angle")
        if et in ('MIRROR', 'PRISM_MIRROR', 'BEAMSPLITTER',
                  'DICHROIC', 'GRATING', 'RETROREFLECTOR'):
            pcol.prop(props, "reflectivity")
        if et in ('LENS', 'WAVEPLATE', 'PASSTHROUGH'):
            pcol.prop(props, "refractive_index")
        # physics-layer parameters (per element type)
        if et in ('SOURCE', 'FIBER_COLLIMATOR'):
            pcol.prop(props, "wavelength")
            pcol.prop(props, "pol_type")
            if props.pol_type == 'LINEAR':
                pcol.prop(props, "pol_angle")
            elif props.pol_type == 'CIRCULAR':
                pcol.prop(props, "handedness")
            pcol.prop(props, "linewidth_nm")
            pcol.prop(props, "bandwidth_nm")
            pcol.prop(props, "waist_um")
        elif et == 'WAVEPLATE':
            pcol.prop(props, "retardance_deg")
            pcol.prop(props, "fast_axis_deg")
            pcol.prop(props, "design_wl")
        elif et == 'POLARIZER':
            pcol.prop(props, "pol_axis_deg")
            pcol.prop(props, "extinction")
        elif et == 'BEAMSPLITTER':
            pcol.prop(props, "is_pbs")
        elif et == 'DICHROIC':
            pcol.prop(props, "pass_type")
            pcol.prop(props, "cut_nm")
        elif et == 'FILTER':
            pcol.prop(props, "filt_type")
            if props.filt_type == 'BP':
                pcol.prop(props, "cut_lo_nm")
                pcol.prop(props, "cut_hi_nm")
            elif props.filt_type == 'LP':
                pcol.prop(props, "cut_lo_nm")
            elif props.filt_type == 'SP':
                pcol.prop(props, "cut_hi_nm")
            else:
                pcol.prop(props, "od")
        elif et == 'GRATING':
            pcol.prop(props, "lines_per_mm")
            pcol.prop(props, "grating_order")
        elif et == 'ATTENUATOR':
            pcol.prop(props, "od")
        elif et == 'CAVITY':
            pcol.prop(props, "cavity_spacing_mm")
            pcol.prop(props, "reflectivity")
        elif et in ('DETECTOR', 'PHOTODIODE', 'POWER_METER'):
            pcol.prop(props, "analyzer")
            sbox = pcol.box()
            sbox.label(text="Sensor", icon='IMAGE_BACKGROUND')
            srow = sbox.row(align=True)
            srow.prop(props, "sensor_px", text="Res")
            srow.prop(props, "pixel_size_um", text="Pitch um")
            sbox.prop(props, "sensor_exposure")
            if props.sensor_exposure > 0.0:
                sbox.prop(props, "sensor_read_noise")
                sbox.prop(props, "sensor_well_depth")
        elif et == 'ABERRATOR':
            abx = pcol.box()
            abx.label(text="Injected aberration (waves)", icon='MOD_NOISE')
            abx.prop(props, "aberr_spec", index=3, text="defocus")
            abx.prop(props, "aberr_spec", index=5, text="astigmatism")
            abx.prop(props, "aberr_spec", index=7, text="coma")
            abx.prop(props, "aberr_spec", index=10, text="spherical")
        elif et == 'DEFORMABLE_MIRROR':
            pcol.prop(props, "reflectivity")
            pcol.operator("optics.dm_flatten", icon='MOD_SMOOTH')
        elif et == 'WAVEFRONT_SENSOR':
            pcol.label(text="Wavefront RMS: %.3f waves" % props.wf_rms, icon='IMAGE_BACKGROUND')
            pcol.operator("optics.ao_close_loop", icon='MOD_NOISE')
        if et in ('MIRROR', 'PRISM_MIRROR'):
            pcol.prop(props, "coating")
        pcol.prop(props, "clear_aperture")


class OPTICS_PT_mount(Panel):
    bl_label = "Mount & Adjustment"
    bl_idname = "OPTICS_PT_mount"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.optics.is_optical

    def draw(self, context):
        layout = self.layout
        props = context.object.optics

        layout.prop(props, "mount_type")
        row = layout.row(align=True)
        row.operator("optics.set_mount_preset", icon='PRESET')
        row.operator("optics.save_mount_preset", text="", icon='ADD')
        if props.mount_preset:
            layout.label(text="Preset: %s" % props.mount_preset, icon='CHECKMARK')

        row = layout.row(align=True)
        row.operator("optics.capture_base_pose", icon='EMPTY_AXIS')
        row.operator("optics.zero_dofs", text="", icon='LOOP_BACK')

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Adjustment DOFs (knobs)", icon='CON_ROTLIKE')
        hdr.operator("optics.define_dof", text="", icon='ADD')
        hdr.operator("optics.pick_pivot", text="", icon='PIVOT_CURSOR')
        if len(props.dofs) and not props.base_pose_set:
            box.label(text="Set coarse pose to activate knobs", icon='ERROR')
        for i, d in enumerate(props.dofs):
            unit = "deg" if d.kind in ('TIP', 'TILT', 'ROT') else "mm"
            r = box.row(align=True)
            r.prop(d, "current", text="%s [%s]" % (d.kind, unit), slider=True)
            r.operator("optics.remove_dof", text="", icon='X').index = i
            sub = box.row(align=True)
            sub.label(text="range")
            sub.prop(d, "min_val", text="")
            sub.prop(d, "max_val", text="")

        mbox = layout.box()
        mh = mbox.row(align=True)
        mh.label(text="Mechanical limits", icon='CONSTRAINT')
        mh.operator("optics.add_mech_link", text="", icon='ADD')
        mh.operator("optics.check_mechanics", text="", icon='CHECKMARK')
        for i, link in enumerate(props.mech):
            lb = mbox.box()
            top = lb.row(align=True)
            top.prop(link, "kind", text="")
            top.operator("optics.remove_mech_link", text="", icon='X').index = i
            lb.prop_search(link, "target", bpy.data, "objects", text="vs")
            rr = lb.row(align=True)
            rr.prop(link, "insert_min", text="min")
            rr.prop(link, "insert_max", text="max")
            ico = {'OK': 'CHECKMARK', 'WARN': 'ERROR', 'BAD': 'CANCEL'}.get(link.state, 'QUESTION')
            lb.label(text=link.detail or link.state, icon=ico)


class OPTICS_PT_sim(Panel):
    bl_label = "Simulation"
    bl_idname = "OPTICS_PT_sim"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"

    def draw(self, context):
        layout = self.layout
        sp = context.scene.optics
        layout.prop(sp, "live_enabled",
                    icon='PAUSE' if sp.live_enabled else 'PLAY', toggle=True)
        row = layout.row(align=True)
        row.operator("optics.trace_now", icon='TRACKING')
        row.operator("optics.clear_beams", text="", icon='X')
        layout.prop(sp, "trace_mode")
        if sp.trace_mode == 'ORDER':
            layout.prop(sp, "order_csv")
        col = layout.column(align=True)
        col.prop(sp, "line_width")
        col.prop(sp, "show_ports")
        col.prop(sp, "auto_color")
        sub = layout.column(align=True)
        sub.prop(sp, "max_segments")
        sub.prop(sp, "max_depth")

        from . import bridge
        running = bridge.is_running()
        bbox = layout.box()
        bbox.operator("optics.bridge_toggle", icon='CONSOLE', depress=running,
                      text="Stop MCP Bridge" if running else "Start MCP Bridge")
        bbox.label(text="MCP bridge: %s" % bridge.info(),
                   icon='LINKED' if running else 'UNLINKED')


class OPTICS_PT_report(Panel):
    bl_label = "Alignment Report"
    bl_idname = "OPTICS_PT_report"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"

    _ICON = {'OK': 'CHECKMARK', 'WARN': 'ERROR', 'BAD': 'CANCEL', 'UNKNOWN': 'QUESTION'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row(align=True)
        row.operator("optics.refresh_report", icon='FILE_REFRESH')
        row.operator("optics.align_all", icon='CON_TRACKTO')
        srow = layout.row(align=True)
        srow.operator("optics.scan", icon='FCURVE')
        srow.operator("optics.fringe_image", icon='IMAGE_DATA')
        srow.operator("optics.power_budget", icon='TEXT')
        srow2 = layout.row(align=True)
        srow2.operator("optics.beam_profile", icon='IPO_EASE_IN_OUT')
        srow2.operator("optics.quantum", icon='EXPERIMENTAL')

        wbox = layout.box()
        wr = wbox.row(align=True)
        wr.prop(scene.optics, "monitor_show", text="Sensor window (bottom-left)",
                icon='IMAGE_BACKGROUND', toggle=True)
        wr.prop(scene.optics, "monitor_size", text="px")
        wbox.operator("optics.save_sensor", icon='FILE_TICK')

        col = layout.column(align=True)
        for obj in scene.objects:
            op = getattr(obj, "optics", None)
            if not op or not op.is_optical or op.element_type == 'SOURCE':
                continue
            box = col.box()
            r = box.row(align=True)
            r.label(text=obj.name, icon=self._ICON.get(op.align_state, 'QUESTION'))
            if any(d.kind in ('TIP', 'TILT', 'ROT') for d in op.dofs):
                r.operator("optics.align_element", text="", icon='CON_TRACKTO').name = obj.name
            box.label(text="pos %.2f mm   ang %.2f deg" % (op.misalign_pos_mm, op.misalign_ang_deg))
            if op.element_type in ('DETECTOR', 'PHOTODIODE', 'POWER_METER'):
                mr = box.row(align=True)
                mr.operator("optics.sensor_monitor", text="Live sensor window",
                            icon='IMAGE_BACKGROUND').name = obj.name
                mr.operator("optics.save_sensor", text="", icon='FILE_TICK').name = obj.name
                if op.meas_power >= 0.0:
                    box.label(text="power %.3f" % op.meas_power)
                    if op.meas_pol:
                        box.label(text="pol: %s" % op.meas_pol)
                    if op.meas_visibility >= 0.0:
                        box.label(text="visibility %.3f" % op.meas_visibility)
                    if op.meas_text:
                        box.label(text=op.meas_text)
            if op.mech_state not in ('UNKNOWN', 'OK'):
                box.label(text="mech: %s" % op.mech_state, icon='CONSTRAINT')
            if op.align_detail:
                box.label(text=op.align_detail, icon='ERROR')

        tb = layout.box()
        tb.label(text="Thresholds")
        rr = tb.row(align=True)
        rr.prop(scene.optics, "ok_pos_mm")
        rr.prop(scene.optics, "ok_ang_deg")
        rr = tb.row(align=True)
        rr.prop(scene.optics, "warn_pos_mm")
        rr.prop(scene.optics, "warn_ang_deg")


class OPTICS_PT_render(Panel):
    bl_label = "Render"
    bl_idname = "OPTICS_PT_render"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("optics.bake_beams", icon='OUTLINER_OB_MESH')
        row.operator("optics.clear_baked", text="", icon='X')
        layout.label(text="Camera")
        grid = layout.grid_flow(columns=4, align=True)
        for pr in ('HERO', 'TOP', 'FRONT', 'SIDE'):
            grid.operator("optics.set_camera", text=pr.title()).preset = pr
        layout.label(text="Background")
        layout.prop(context.scene.optics, "bg_preset", text="")
        layout.prop(context.scene.optics, "realistic_optics")
        from . import optomech
        _g = context.scene.optics
        row = layout.row(align=True)
        row.prop(_g, "bench_grid_units", text="Grid")
        if _g.bench_grid_units == 'CUSTOM':
            row.prop(_g, "bench_grid_mm", text="mm")
        layout.prop(_g, "beam_height_mm", text="Beam height (mm)")
        layout.operator("optics.dress_bench", icon='SNAP_FACE',
                        text="Strip Bench Dressing" if optomech.is_dressed(context.scene) else "Dress Bench (hole grid + posts)")
        col = layout.column(align=True)
        col.operator("optics.render_preview", icon='RENDER_STILL')
        col.operator("optics.render_final", icon='RENDER_RESULT')
        col.operator("optics.reset_render_style", icon='LOOP_BACK')
        layout.operator("optics.export_svg", icon='EXPORT')


class OPTICS_PT_examples(Panel):
    bl_label = "Examples"
    bl_idname = "OPTICS_PT_examples"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Canonical setups (generic parts)")
        col = layout.column(align=True)
        col.operator("optics.build_example", text="Mach-Zehnder", icon='MOD_MIRROR').kind = 'mach_zehnder'
        col.operator("optics.build_example", text="Michelson", icon='MOD_MIRROR').kind = 'michelson'
        col.operator("optics.build_example", text="Hong-Ou-Mandel", icon='PARTICLES').kind = 'hong_ou_mandel'
        col.operator("optics.build_example", text="Bell / Entanglement", icon='PARTICLE_DATA').kind = 'bell'
        col.operator("optics.build_example", text="Adaptive Optics", icon='MOD_NOISE').kind = 'adaptive_optics'
        col.operator("optics.build_example", text="Newton's Rings", icon='MESH_CIRCLE').kind = 'newton_rings'


class OPTICS_PT_library(Panel):
    bl_label = "Component Library"
    bl_idname = "OPTICS_PT_library"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("optics.add_from_library", icon='ADD')
        layout.operator("optics.import_mesh", icon='IMPORT')
        row = layout.row(align=True)
        row.operator("optics.convert_step", text="Convert STEP", icon='FILE_CACHE')
        row.operator("optics.save_to_library", text="Save", icon='FILE_TICK')
        from .prefs import get_prefs
        p = get_prefs()
        box = layout.box()
        if p:
            md = os.path.basename(p.mesh_dir.rstrip("/\\")) if p.mesh_dir else ""
            box.label(text="Mesh folder: %s" % (md or "(set in Preferences)"),
                      icon='FILE_FOLDER' if md else 'ERROR')
            box.label(text="FreeCAD (STEP): %s" % ("ready" if p.freecad_path else "not set"),
                      icon='CHECKMARK' if p.freecad_path else 'ERROR')
        else:
            box.label(text="Open Add-on Preferences to set mesh folder", icon='INFO')


class OPTICS_PT_assembly(Panel):
    bl_label = "Assembly & Parts"
    bl_idname = "OPTICS_PT_assembly"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("optics.swap_part", icon='FILE_REFRESH')
        layout.label(text="Fills/replaces the mesh; keeps ports, mount & beam path.")
        ob = context.object
        op = getattr(ob, "optics", None) if ob is not None else None
        if op and op.is_optical and op.part_key:
            layout.label(text="Active part: %s" % op.part_key, icon='MESH_DATA')

        layout.separator()
        layout.label(text="Relative positioning")
        col = layout.column(align=True)
        col.operator("optics.place_relative", icon='TRANSFORM_ORIGINS')
        row = col.row(align=True)
        row.operator("optics.create_anchor", text="Create Anchor", icon='EMPTY_AXIS')
        row.operator("optics.clear_anchor", text="Clear", icon='X')
        if op and op.is_optical and op.anchor is not None:
            layout.label(text="Anchored to: %s" % op.anchor.name, icon='LINKED')


class OPTICS_PT_adaptive_optics(Panel):
    bl_label = "Adaptive Optics"
    bl_idname = "OPTICS_PT_adaptive_optics"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("optics.ao_close_loop", icon='MOD_NOISE')
        layout.label(text="Sense wavefront -> drive deformable mirror -> flatten.")
        ob = context.object
        op = getattr(ob, "optics", None) if ob is not None else None
        if op and op.is_optical:
            if op.element_type == 'WAVEFRONT_SENSOR':
                layout.label(text="WFS RMS: %.3f waves" % op.wf_rms, icon='IMAGE_BACKGROUND')
            elif op.element_type == 'DEFORMABLE_MIRROR':
                layout.operator("optics.dm_flatten", icon='MOD_SMOOTH')


_classes = (
    OPTICS_UL_ports,
    OPTICS_PT_tag,
    OPTICS_PT_mount,
    OPTICS_PT_sim,
    OPTICS_PT_report,
    OPTICS_PT_render,
    OPTICS_PT_library,
    OPTICS_PT_assembly,
    OPTICS_PT_adaptive_optics,
    OPTICS_PT_examples,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
