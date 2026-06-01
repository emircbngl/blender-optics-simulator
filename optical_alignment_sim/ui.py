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
        if et in ('BEAMSPLITTER', 'DICHROIC'):
            pcol.prop(props, "split_ratio")
        if et == 'PRISM_MIRROR':
            pcol.prop(props, "prism_angle")
        if et in ('MIRROR', 'PRISM_MIRROR', 'BEAMSPLITTER',
                  'DICHROIC', 'GRATING', 'RETROREFLECTOR'):
            pcol.prop(props, "reflectivity")
        if et in ('LENS', 'WAVEPLATE', 'PASSTHROUGH'):
            pcol.prop(props, "refractive_index")
        pcol.prop(props, "clear_aperture")
        pcol.prop(props, "wavelength")


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
        layout.operator("optics.quantum", icon='EXPERIMENTAL')

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
            if op.element_type in ('DETECTOR', 'PHOTODIODE', 'POWER_METER') and op.meas_power >= 0.0:
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
        col = layout.column(align=True)
        col.operator("optics.render_preview", icon='RENDER_STILL')
        col.operator("optics.render_final", icon='RENDER_RESULT')


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


_classes = (
    OPTICS_UL_ports,
    OPTICS_PT_tag,
    OPTICS_PT_mount,
    OPTICS_PT_sim,
    OPTICS_PT_report,
    OPTICS_PT_render,
    OPTICS_PT_library,
    OPTICS_PT_examples,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
