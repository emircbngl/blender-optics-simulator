"""Assembly & parts - fill or replace the *mesh* of an optical element while keeping its
optical *slot* (element_type, ports, mount, base_pose, DOFs, beam role), individually or in
bulk.

The optical state lives on ``obj.optics`` and is independent of ``obj.data`` (the mesh), so
swapping ``obj.data`` dresses a generic skeleton with real vendor CAD or your own imported
meshes and leaves the simulation - ports, world normals, beam path - intact. By default the
slot is preserved; tick *Refit ports* to re-derive ports from the new geometry. (G3 adds
relative positioning / anchors on top of this.)
"""
from __future__ import annotations

import os

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty, BoolProperty, FloatProperty
from mathutils import Vector, Matrix

from . import library, mounts, presets, geometry, operators as _ops

_ENUM_CACHE = []        # keep dynamic-enum item strings alive (Blender requirement)


def _retrace(context):
    """Recompute the live beam + redraw after a structural change."""
    try:
        from . import tracer
        sp = context.scene.optics
        tracer.cached_segments = tracer.trace_scene(
            context.scene, mode=sp.trace_mode,
            max_segments=sp.max_segments, max_depth=sp.max_depth)
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()
    except Exception:
        pass


def _importable_path(source, key, filepath):
    """Resolve a catalog key or a file path to an importable STL/OBJ path (STEP/IGES via
    FreeCAD). Returns (path, entry_or_None)."""
    if source == 'CATALOG':
        entry = library.get_components().get(key)
        if not entry:
            raise RuntimeError("unknown component '%s'" % key)
        return library.resolve_mesh(entry), entry
    path = bpy.path.abspath(filepath or "")
    if not path or not os.path.exists(path):
        raise FileNotFoundError("file not found: %s" % (filepath or "(empty)"))
    low = path.lower()
    if low.endswith((".stl", ".obj")):
        return path, None
    if low.endswith((".step", ".stp", ".igs", ".iges")):
        return library.convert_step(path), None
    raise RuntimeError("unsupported file (use STL/OBJ or STEP/IGES): %s" % path)


def _assign_mesh_data(obj, new_data, refit=False):
    """Point obj at new_data, GC the orphaned old mesh, optionally re-derive ports."""
    if obj is None or obj.type != 'MESH':
        return False
    old = obj.data
    obj.data = new_data
    if old is not None and old is not new_data and old.users == 0:
        bpy.data.meshes.remove(old)
    if refit:
        _ops.do_auto_detect(obj)
    return True


def swap_mesh_on(obj, mesh_path, refit=False):
    """Replace obj's mesh with the mesh at mesh_path (single import). Returns (ok, msg)."""
    temp = library.import_mesh(mesh_path, recenter=True)
    if temp is None or temp.type != 'MESH' or temp.data is None:
        if temp is not None:
            bpy.data.objects.remove(temp, do_unlink=True)
        return False, "import produced no mesh"
    data = temp.data
    bpy.data.objects.remove(temp, do_unlink=True)        # data now lives on... nothing yet
    ok = _assign_mesh_data(obj, data, refit=refit)
    if not ok and data.users == 0:
        bpy.data.meshes.remove(data)
    return ok, ("ok" if ok else "%s is not a mesh element" % (obj.name if obj else "?"))


def _targets(context, scope, prefix):
    scene = context.scene
    active = context.object
    opticals = [o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical
                and o.type == 'MESH']
    if scope == 'ACTIVE':
        return [active] if active in opticals else []
    if scope == 'SELECTED':
        return [o for o in context.selected_objects if o in opticals]
    if active is None or active not in opticals:
        return []
    if scope == 'SAME_TYPE':
        return [o for o in opticals if o.optics.element_type == active.optics.element_type]
    if scope == 'SAME_MOUNT':
        return [o for o in opticals if o.optics.mount_preset == active.optics.mount_preset]
    if scope == 'NAME_PREFIX':
        p = prefix or active.name.rstrip("0123456789._- ")
        return [o for o in opticals if o.name.startswith(p)]
    return []


def _component_items(self, context):
    _ENUM_CACHE.clear()
    try:
        for k, e in sorted(library.get_components().items(),
                           key=lambda kv: kv[1].get("label", kv[0])):
            _ENUM_CACHE.append((k, e.get("label", k), e.get("specs", "") or k))
    except Exception:
        pass
    if not _ENUM_CACHE:
        _ENUM_CACHE.append(('NONE', "(no catalog)", ""))
    return _ENUM_CACHE


class OPTICS_OT_swap_part(Operator):
    bl_idname = "optics.swap_part"
    bl_label = "Swap / Fill Part"
    bl_description = ("Fill or replace the mesh of optical element(s) from the catalog or a file, "
                      "keeping the optical slot (ports, mount, pose, beam path). Works on one "
                      "element or in bulk")
    bl_options = {'REGISTER', 'UNDO'}

    source: EnumProperty(name="Source",
                         items=[('CATALOG', "Catalog", "A built-in / library component"),
                                ('FILE', "File", "An STL/OBJ file (or STEP/IGES via FreeCAD)")],
                         default='CATALOG')
    component: EnumProperty(name="Component", items=_component_items)
    filepath: StringProperty(name="File", subtype='FILE_PATH', default="")
    refit_ports: BoolProperty(
        name="Refit ports to new mesh", default=False,
        description="Re-derive ports from the new geometry (off = keep the slot's existing ports/pose)")
    apply_mount: BoolProperty(
        name="Apply catalog mount", default=False,
        description="Re-apply the catalog part's kinematic mount (resets base pose + knobs)")
    scope: EnumProperty(
        name="Apply to",
        items=[('ACTIVE', "Active only", "Just the active element"),
               ('SELECTED', "Selected", "All selected optical mesh elements"),
               ('SAME_TYPE', "Same type", "All elements of the active's element type"),
               ('SAME_MOUNT', "Same mount", "All elements sharing the active's mount preset"),
               ('NAME_PREFIX', "Name prefix", "All elements whose name starts with the prefix")],
        default='ACTIVE')
    prefix: StringProperty(name="Prefix", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "source", expand=True)
        if self.source == 'CATALOG':
            col.prop(self, "component")
            col.prop(self, "apply_mount")
        else:
            col.prop(self, "filepath")
        col.prop(self, "refit_ports")
        col.separator()
        col.prop(self, "scope")
        if self.scope == 'NAME_PREFIX':
            col.prop(self, "prefix")

    def execute(self, context):
        targets = _targets(context, self.scope, self.prefix)
        if not targets:
            self.report({'ERROR'}, "No target optical mesh element for scope '%s'" % self.scope)
            return {'CANCELLED'}

        # Obtain the source mesh ONCE: import the real file, or - for a CATALOG part whose
        # vendor mesh isn't on disk - fall back to the generic placeholder (like Add
        # Component), so the swap still works without downloaded CAD. Then share the mesh
        # data across all targets (identical parts).
        entry = None
        used_generic = False
        try:
            mesh_path, entry = _importable_path(self.source, self.component, self.filepath)
            src = library.import_mesh(mesh_path, recenter=True)
        except (FileNotFoundError, RuntimeError) as ex:
            if self.source != 'CATALOG':
                self.report({'ERROR'}, str(ex))
                return {'CANCELLED'}
            entry = library.get_components().get(self.component) or {}
            et = entry.get("element_type") or 'PASSTHROUGH'
            src = library._generic_fallback(et, "_swap_src", (0.0, 0.0, 0.0), entry.get("generic"))
            used_generic = True
        if src is None or src.type != 'MESH' or src.data is None:
            if src is not None:
                bpy.data.objects.remove(src, do_unlink=True)
            self.report({'ERROR'}, "could not obtain a mesh for the swap")
            return {'CANCELLED'}
        new_data = src.data
        bpy.data.objects.remove(src, do_unlink=True)

        part_key = (self.component if self.source == 'CATALOG'
                    else os.path.basename(bpy.path.abspath(self.filepath)))
        mount_key = entry.get("mount") if (entry and self.apply_mount) else None
        mount_ok = mount_key in {**presets.MOUNT_LIBRARY, **mounts.get_library()} if mount_key else False

        done = 0
        for obj in targets:
            if not _assign_mesh_data(obj, new_data, refit=self.refit_ports):
                self.report({'WARNING'}, "%s is not a mesh element - skipped" % obj.name)
                continue
            obj.optics.part_key = part_key
            if mount_ok:
                mounts.apply_preset(obj, mount_key)
            elif obj.optics.base_pose_set:
                mounts.compose_pose(obj)
            done += 1

        if new_data.users == 0:                          # nothing took it (all skipped)
            bpy.data.meshes.remove(new_data)

        _retrace(context)
        self.report({'INFO'}, "Swapped %d element(s) -> %s%s%s"
                    % (done, part_key, "  (+mount)" if mount_ok else "",
                       "  (generic placeholder; set the mesh folder in Preferences for real CAD)"
                       if used_generic else ""))
        return {'FINISHED'}


class OPTICS_OT_place_relative(Operator):
    bl_idname = "optics.place_relative"
    bl_label = "Place Relative"
    bl_description = ("Place the active element a set distance from a reference along a chosen "
                      "axis (or the reference's beam); optionally link it to follow the reference")
    bl_options = {'REGISTER', 'UNDO'}

    reference: StringProperty(name="Reference")
    axis: EnumProperty(
        name="Direction",
        items=[('BEAM', "Reference beam (OUT)", "Along the reference's OUT-port normal"),
               ('+X', "+X", ""), ('-X', "-X", ""), ('+Y', "+Y", ""),
               ('-Y', "-Y", ""), ('+Z', "+Z", ""), ('-Z', "-Z", "")],
        default='BEAM')
    frame: EnumProperty(name="Axis frame",
                        items=[('REFERENCE', "Reference", ""), ('WORLD', "World", "")],
                        default='REFERENCE')
    distance: FloatProperty(name="Distance (mm)", default=50.0)
    align_rotation: BoolProperty(name="Match reference orientation", default=True)
    link: BoolProperty(name="Link (follow the reference live)", default=True)

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and getattr(ob, "optics", None) and ob.optics.is_optical

    def invoke(self, context, event):
        sel = [o for o in context.selected_objects if o is not context.object
               and getattr(o, "optics", None) and o.optics.is_optical]
        if sel:
            self.reference = sel[0].name
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        col = self.layout.column()
        col.prop_search(self, "reference", context.scene, "objects")
        col.prop(self, "axis")
        if self.axis != 'BEAM':
            col.prop(self, "frame")
        col.prop(self, "distance")
        col.prop(self, "align_rotation")
        col.prop(self, "link")

    def execute(self, context):
        act = context.object
        ref = context.scene.objects.get(self.reference)
        if ref is None or ref is act:
            self.report({'ERROR'}, "Pick a reference object (not the active one)")
            return {'CANCELLED'}
        if self.axis == 'BEAM':
            rop = getattr(ref, "optics", None)
            out = next((p for p in rop.ports if p.role == 'OUT'), None) if rop else None
            if out is None:
                self.report({'ERROR'}, "Reference has no OUT port for BEAM placement")
                return {'CANCELLED'}
            origin = geometry.world_port(ref, out.local_position)
            direction = geometry.world_normal(ref, out.local_normal)
        else:
            unit = geometry.axis_vector(self.axis)
            direction = ((ref.matrix_world.to_3x3() @ unit).normalized()
                         if self.frame == 'REFERENCE' else Vector(unit))
            origin = ref.matrix_world.translation.copy()
        target = origin + direction * self.distance
        _, _, scl = act.matrix_world.decompose()
        rot = (ref.matrix_world.to_quaternion() if self.align_rotation
               else act.matrix_world.to_quaternion())
        Mw = Matrix.LocRotScale(target, rot, scl)
        mounts.store_base_matrix(act.optics, Mw)
        if self.link:
            mounts.set_anchor(act, ref)               # re-base into ref frame + live follow
            how = "linked to %s" % ref.name
        else:
            act.optics.anchor = None
            mounts.compose_pose(act)
            how = "one-shot"
        _retrace(context)
        self.report({'INFO'}, "Placed %s %.1f mm from %s along %s (%s)"
                    % (act.name, self.distance, ref.name, self.axis, how))
        return {'FINISHED'}


class OPTICS_OT_create_anchor(Operator):
    bl_idname = "optics.create_anchor"
    bl_label = "Create Assembly Anchor"
    bl_description = ("Create an Empty at the selection centroid and anchor all selected optical "
                      "elements to it - move the Empty to move the whole assembly as one")
    bl_options = {'REGISTER', 'UNDO'}

    at_cursor: BoolProperty(name="At 3D cursor", default=False)

    @classmethod
    def poll(cls, context):
        return any(getattr(o, "optics", None) and o.optics.is_optical
                   for o in context.selected_objects)

    def execute(self, context):
        sel = [o for o in context.selected_objects
               if getattr(o, "optics", None) and o.optics.is_optical]
        if not sel:
            self.report({'ERROR'}, "Select optical elements first")
            return {'CANCELLED'}
        loc = (context.scene.cursor.location.copy() if self.at_cursor
               else sum((o.matrix_world.translation for o in sel), Vector()) / len(sel))
        empty = bpy.data.objects.new("OpticsAnchor", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 20.0
        empty.location = loc
        context.scene.collection.objects.link(empty)
        context.view_layer.update()
        n = sum(1 for o in sel if mounts.set_anchor(o, empty))
        context.view_layer.objects.active = empty
        _retrace(context)
        self.report({'INFO'}, "Anchored %d element(s) to %s - move it to move the assembly"
                    % (n, empty.name))
        return {'FINISHED'}


class OPTICS_OT_clear_anchor(Operator):
    bl_idname = "optics.clear_anchor"
    bl_label = "Clear Anchor"
    bl_description = "Detach the selected optical elements from their anchor (bake pose to world)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(getattr(o, "optics", None) and o.optics.is_optical
                   and getattr(o.optics, "anchor", None) is not None
                   for o in context.selected_objects)

    def execute(self, context):
        n = 0
        for o in context.selected_objects:
            op = getattr(o, "optics", None)
            if op and op.is_optical and op.anchor is not None and mounts.clear_anchor(o):
                n += 1
        _retrace(context)
        self.report({'INFO'}, "Cleared anchor on %d element(s)" % n)
        return {'FINISHED'}


_classes = (OPTICS_OT_swap_part, OPTICS_OT_place_relative,
            OPTICS_OT_create_anchor, OPTICS_OT_clear_anchor)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
