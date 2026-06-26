"""Add-on preferences: where to find component meshes and FreeCAD (for STEP/IGES).

Meshes are kept LOCAL (vendor IP is not bundled). The user points `mesh_dir` at
their own downloaded/converted parts; `freecad_path` enables STEP/IGES import.
"""
from __future__ import annotations

import os
import shutil

import bpy
from bpy.types import AddonPreferences, Operator
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty

# Native in-Blender update channel (see docs/ + tools/build_pages_repo.py). The add-on
# updates from this self-hosted static repository — NOT by overwriting its own files.
UPDATE_REPO_URL = "https://emircbngl.github.io/blender-optics-simulator/index.json"
UPDATE_REPO_NAME = "Blender Optics Simulator"
UPDATE_REPO_MODULE = "optics_sim_updates"


def _auto_freecad():
    candidates = [
        "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd",
        "/Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which("freecadcmd") or shutil.which("FreeCADCmd") or ""


def _default_mesh_dir():
    d = os.path.expanduser("~/Documents/Claude Projects/3D şema/blender_workspace/stl")
    return d if os.path.isdir(d) else ""


def _addon_version():
    try:
        p = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("version"):
                    return s.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def _find_update_repo(prefs):
    target = UPDATE_REPO_URL.rstrip("/")
    for r in prefs.extensions.repos:
        if (r.remote_url or "").rstrip("/") == target:
            return r
    return None


class OPTICS_OT_check_updates(Operator):
    """Subscribe to the update repository, refresh it, and open Blender's update panel.

    This drives Blender's OWN extension operators — it never overwrites the add-on's
    files, so the extension manager and the on-disk version never diverge."""
    bl_idname = "optics.check_updates"
    bl_label = "Check for Updates"

    def execute(self, context):
        if not bpy.app.online_access:
            self.report({'WARNING'},
                        "Turn on Allow Online Access (Preferences ▸ System ▸ Network), then check again.")
            try:
                bpy.ops.extensions.userpref_show_online('INVOKE_DEFAULT')
            except (RuntimeError, AttributeError):
                pass
            return {'CANCELLED'}

        prefs = context.preferences
        repo = _find_update_repo(prefs)
        if repo is None:
            try:
                repo = prefs.extensions.repos.new(
                    name=UPDATE_REPO_NAME, module=UPDATE_REPO_MODULE,
                    remote_url=UPDATE_REPO_URL, source='USER')
            except (RuntimeError, ValueError) as exc:
                self.report({'ERROR'}, "Could not add the update repository: %s" % exc)
                return {'CANCELLED'}
            repo.use_remote_url = True
            repo.enabled = True
            repo.use_sync_on_startup = True
            self.report({'INFO'}, "Subscribed to the update repository.")
        else:
            repo.use_sync_on_startup = True

        try:
            bpy.ops.extensions.repo_sync_all(use_active_only=False)
        except RuntimeError as exc:
            self.report({'WARNING'}, "Could not refresh the repository: %s" % exc)

        # Hand off to Blender's own update panel — the user confirms the install there
        # (registry-safe; we never swap files ourselves).
        for op in ("userpref_show_for_update", "userpref_show_online"):
            try:
                getattr(bpy.ops.extensions, op)('INVOKE_DEFAULT')
                break
            except (RuntimeError, AttributeError):
                continue
        return {'FINISHED'}


class OpticsAddonPrefs(AddonPreferences):
    bl_idname = __package__        # full package id (e.g. bl_ext.user_default.optical_alignment_sim)

    mesh_dir: StringProperty(
        name="Component mesh folder", subtype='DIR_PATH', default=_default_mesh_dir(),
        description="Local folder containing component meshes (STL/OBJ). Vendor meshes are not bundled")
    freecad_path: StringProperty(
        name="FreeCAD command", subtype='FILE_PATH', default=_auto_freecad(),
        description="Path to freecadcmd / FreeCADCmd, used to convert STEP/IGES to mesh")
    convert_tolerance_mm: FloatProperty(
        name="STEP tessellation (mm)", default=0.5, min=0.01, max=5.0,
        description="Linear deflection for STEP/IGES tessellation; smaller = finer mesh")
    bridge_port: IntProperty(
        name="MCP bridge port", default=9765, min=1024, max=65535,
        description="Localhost TCP port for the MCP bridge (an external MCP server connects here)")
    bridge_autostart: BoolProperty(
        name="Auto-start bridge", default=False,
        description="Start the localhost MCP bridge automatically when the add-on loads")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mesh_dir")
        col.prop(self, "freecad_path")
        col.prop(self, "convert_tolerance_mm")
        box = col.box()
        box.label(text="Meshes are loaded locally and are not shipped with the add-on", icon='INFO')
        box.label(text="(Thorlabs / Edmund CAD is their intellectual property).")
        bb = col.box()
        bb.label(text="MCP bridge (localhost only)", icon='CONSOLE')
        row = bb.row(align=True)
        row.prop(self, "bridge_port")
        row.prop(self, "bridge_autostart")
        up = col.box()
        up.label(text="Updates  ·  installed v%s" % _addon_version(), icon='FILE_REFRESH')
        up.operator("optics.check_updates", icon='URL')
        subscribed = _find_update_repo(context.preferences) is not None
        up.label(text="Subscribed — updates arrive in-Blender." if subscribed
                 else "Subscribes to in-Blender updates (no zip downloads).", icon='INFO')


def get_prefs():
    """Return add-on preferences, or None when running outside the add-on
    (e.g. headless dev imports via sys.path)."""
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


_classes = (OPTICS_OT_check_updates, OpticsAddonPrefs)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
