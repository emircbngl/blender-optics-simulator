"""Add-on preferences: where to find component meshes and FreeCAD (for STEP/IGES).

Meshes are kept LOCAL (vendor IP is not bundled). The user points `mesh_dir` at
their own downloaded/converted parts; `freecad_path` enables STEP/IGES import.
"""
from __future__ import annotations

import os
import shutil

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty, FloatProperty


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

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mesh_dir")
        col.prop(self, "freecad_path")
        col.prop(self, "convert_tolerance_mm")
        box = col.box()
        box.label(text="Meshes are loaded locally and are not shipped with the add-on", icon='INFO')
        box.label(text="(Thorlabs / Edmund CAD is their intellectual property).")


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
