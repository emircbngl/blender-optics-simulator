"""Add-on preferences: where to find component meshes and FreeCAD (for STEP/IGES).

Meshes are kept LOCAL (vendor IP is not bundled). The user points `mesh_dir` at
their own downloaded/converted parts; `freecad_path` enables STEP/IGES import.
"""
from __future__ import annotations

import os
import shutil

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty, FloatProperty, IntProperty, BoolProperty


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
    """Vendor meshes are not bundled, so there is no location we can sensibly guess.

    Honour ``OPTICS_MESH_DIR`` when it points at a real folder — that keeps a
    one-machine convenience out of the source — and otherwise leave the field blank
    for the user to fill in from the add-on preferences.
    """
    d = os.environ.get("OPTICS_MESH_DIR", "")
    return d if d and os.path.isdir(d) else ""


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
    bridge_token: StringProperty(
        name="MCP bridge token", default="",
        description=("Secret capability required by an external MCP client. Leave blank once to "
                     "generate a strong token, then set OPTICS_BRIDGE_TOKEN to the same value."))
    show_advanced: BoolProperty(
        name="Show Advanced Controls", default=False,
        description="Show specialized optical, sensor, mechanical, and drawing controls (default off)")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mesh_dir")
        col.prop(self, "freecad_path")
        col.prop(self, "convert_tolerance_mm")
        col.prop(self, "show_advanced")
        box = col.box()
        box.label(text="Meshes are loaded locally and are not shipped with the add-on", icon='INFO')
        box.label(text="(Thorlabs / Edmund CAD is their intellectual property).")
        bb = col.box()
        bb.label(text="MCP bridge (localhost only)", icon='CONSOLE')
        row = bb.row(align=True)
        row.prop(self, "bridge_port")
        row.prop(self, "bridge_autostart")
        bb.prop(self, "bridge_token")
        bb.label(text="Set the same value in OPTICS_BRIDGE_TOKEN for the MCP client.", icon='LOCKED')
        up = col.box()
        up.label(text="Updates", icon='FILE_REFRESH')
        from . import updater
        updater.draw_update_box(up, context)


def get_prefs():
    """Return add-on preferences, or None when running outside the add-on
    (e.g. headless dev imports via sys.path)."""
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


_classes = (OpticsAddonPrefs,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
