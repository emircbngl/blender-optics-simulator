"""Real-mesh component library (Tier 2).

Imports the user's own vendor parts: STL/OBJ natively, STEP/IGES via FreeCAD.
Library entries are metadata only (mesh referenced by filename, resolved against
the user's local `mesh_dir`); no vendor meshes are bundled with the add-on.
"""
from __future__ import annotations

import os
import json
import subprocess

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty, BoolProperty

from . import presets, mounts
from . import operators as _ops
from .prefs import get_prefs

# Built-in component metadata seeded from the user's DHM set. Mesh files are NOT
# shipped; they are resolved by filename against the configured mesh folder.
BUILTIN = {
    "HNL100LB": {"label": "HeNe Laser (HNL100LB)", "vendor": "Thorlabs",
                 "mesh": "HNL100LB.stl", "format": "stl",
                 "name": "LASER_HNL100LB", "element_type": "SOURCE"},
    "KCB1C": {"label": "Corner-Cube Mirror (KCB1C)", "vendor": "Thorlabs",
              "mesh": "KCB1C_M.stl", "format": "stl",
              "name": "M0_KCB1C", "element_type": "PRISM_MIRROR"},
    "C6WR": {"label": "Beamsplitter Combiner (C6WR)", "vendor": "Thorlabs",
             "mesh": "C6WR.stl", "format": "stl",
             "name": "BS_C6WR", "element_type": "BEAMSPLITTER"},
    "VA5": {"label": "Variable Attenuator (VA5-633)", "vendor": "Thorlabs",
            "mesh": "VA5-633_M.stl", "format": "stl",
            "name": "VA5_attenuator", "element_type": "ATTENUATOR"},
    "BE10A": {"label": "Beam Expander (BE10-A)", "vendor": "Thorlabs",
              "mesh": "beam_expander.stl", "format": "stl",
              "name": "BE_expander", "element_type": "LENS"},
    "MO50X": {"label": "Microscope Objective 50x", "vendor": "generic",
              "mesh": "microscope_objective.stl", "format": "stl",
              "name": "MO_objective", "element_type": "LENS"},
    "PRM05": {"label": "Waveplate Mount (PRM05)", "vendor": "Thorlabs",
              "mesh": "PRM05_M.stl", "format": "stl",
              "name": "PRM_waveplate", "element_type": "WAVEPLATE"},
    "KM100CP_M": {"label": "Kinematic Mirror Mount (KM100CP/M)", "vendor": "Thorlabs",
                  "mesh": "KM100CP_M.step", "format": "step",
                  "name": "M_KM100CP", "element_type": "PRISM_MIRROR", "mount": "KM100CP/M"},
}

# Paths are baked into the script because freecadcmd treats file-like CLI args as
# documents to open, not as script argv. STEP/IGES uses Part.insert (NOT openDocument).
_FREECAD_SCRIPT_TEMPLATE = '''
import FreeCAD, Part, MeshPart, os
src = {src}
dst = {dst}
tol = {tol}
doc = FreeCAD.newDocument("conv")
Part.insert(src, doc.Name)
shapes = [o.Shape for o in doc.Objects if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
shape = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=tol, AngularDeflection=0.5)
mesh.write(dst)
'''


# --- paths / library merge --------------------------------------------------

def _mesh_dir():
    p = get_prefs()
    return (p.mesh_dir if p else "") or ""


def _cache_dir():
    try:
        return bpy.utils.extension_path_user(__package__, path="cache", create=True)
    except Exception:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "optics_cache")
        os.makedirs(d, exist_ok=True)
        return d


def _bundled_json():
    # optional library/components.json shipped beside the package
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "library", "components.json")
    return p if os.path.exists(p) else None


def _user_json():
    return os.path.join(_cache_dir(), "components_user.json")


def get_components():
    comps = {k: dict(v) for k, v in BUILTIN.items()}
    for path in (_bundled_json(), _user_json()):
        if path and os.path.exists(path):
            try:
                with open(path, "r") as f:
                    loaded = json.load(f)
                for k, v in loaded.items():
                    if isinstance(v, dict) and isinstance(comps.get(k), dict):
                        comps[k].update(v)            # merge per key (keep mesh/type if omitted)
                    else:
                        comps[k] = v
            except Exception:
                pass
    return comps


# --- mesh import / conversion ----------------------------------------------

def import_mesh(filepath, global_scale=1.0, recenter=True, join=True):
    ext = os.path.splitext(filepath)[1].lower()
    before = set(bpy.data.objects)
    if ext == ".stl":
        try:
            bpy.ops.wm.stl_import(filepath=filepath, global_scale=global_scale)
        except AttributeError:
            bpy.ops.import_mesh.stl(filepath=filepath)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=filepath, global_scale=global_scale)
    else:
        raise RuntimeError("unsupported mesh extension: %s" % ext)
    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        raise RuntimeError("import produced no objects")
    obj = new[0]
    if join and len(new) > 1:
        for o in bpy.data.objects:
            o.select_set(False)
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        obj = bpy.context.view_layer.objects.active
    if recenter:
        for o in bpy.data.objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME', center='BOUNDS')
    return obj


def convert_step(path, tol=None):
    """Convert a STEP/IGES file to STL via FreeCAD; return the STL path (cached)."""
    p = get_prefs()
    fc = (p.freecad_path if p else "") or ""
    if not fc or not os.path.exists(fc):
        raise RuntimeError("FreeCAD not found - set 'FreeCAD command' in add-on preferences")
    tol = tol if tol is not None else (p.convert_tolerance_mm if p else 0.5)
    cache = _cache_dir()
    out = os.path.join(cache, os.path.splitext(os.path.basename(path))[0] + ".stl")
    meta = out + ".src"
    sig = "%d:%d" % (int(os.path.getmtime(path)), os.path.getsize(path))
    if os.path.exists(out) and os.path.exists(meta):
        try:
            with open(meta, "r") as f:
                if f.read().strip() == sig:           # source unchanged since last convert
                    return out
        except Exception:
            pass
    script = os.path.join(cache, "_fc_convert.py")
    with open(script, "w") as f:
        f.write(_FREECAD_SCRIPT_TEMPLATE.format(src=repr(path), dst=repr(out), tol=float(tol)))
    try:
        r = subprocess.run([fc, script], capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("FreeCAD conversion timed out (>300s): %s" % os.path.basename(path))
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("FreeCAD conversion failed (%s): %s"
                           % (r.returncode, r.stderr.decode(errors='ignore')[-300:]))
    with open(meta, "w") as f:
        f.write(sig)
    return out


def resolve_mesh(entry):
    """Find the entry's mesh file (in mesh_dir or absolute) and return an
    importable STL/OBJ path, converting STEP/IGES on the fly."""
    name = entry.get("mesh")
    if not name:
        raise FileNotFoundError("entry has no 'mesh'")
    path = name if os.path.isabs(name) else os.path.join(_mesh_dir(), name)
    if not os.path.exists(path):
        raise FileNotFoundError("mesh '%s' not found (mesh_dir=%s)" % (name, _mesh_dir()))
    if path.lower().endswith((".stl", ".obj")):
        return path
    if path.lower().endswith((".step", ".stp", ".igs", ".iges")):
        return convert_step(path)
    raise RuntimeError("unsupported mesh format: %s" % path)


def add_component(key, location=(0.0, 0.0, 0.0)):
    comps = get_components()
    if key not in comps:
        return None, "unknown component '%s'" % key
    e = comps[key]
    path = resolve_mesh(e)
    obj = import_mesh(path)
    obj.location = location
    if e.get("name"):
        obj.name = e["name"]
    obj.optics.is_optical = True
    if e.get("element_type"):
        obj.optics.element_type = e["element_type"]
    _ops.do_auto_detect(obj)
    if e.get("element_type"):
        obj.optics.element_type = e["element_type"]   # keep explicit type
    if e.get("mount") and e["mount"] in {**presets.MOUNT_LIBRARY, **mounts.get_library()}:
        mounts.apply_preset(obj, e["mount"])
    return obj, "ok"


def save_component(obj, key, label=""):
    """Save the active element's setup as a user library entry (metadata only)."""
    op = obj.optics
    entry = {
        "label": label or key,
        "vendor": "user",
        "mesh": key + ".stl",
        "format": "stl",
        "name": obj.name,
        "element_type": op.element_type,
    }
    if op.mount_preset:
        entry["mount"] = op.mount_preset
    path = _user_json()
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[key] = entry
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


# --- operators --------------------------------------------------------------

_item_cache = []


def _component_items(self, context):
    global _item_cache
    comps = get_components()
    _item_cache = [(k, v.get("label", k), v.get("vendor", "")) for k, v in sorted(comps.items())]
    return _item_cache or [('NONE', "(empty)", "")]


class OPTICS_OT_add_from_library(Operator):
    bl_idname = "optics.add_from_library"
    bl_label = "Add Component from Library"
    bl_description = "Import a library component's mesh and set it up (ports + mount)"
    bl_options = {'REGISTER', 'UNDO'}

    component: EnumProperty(name="Component", items=_component_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            obj, msg = add_component(self.component, location=context.scene.cursor.location.copy())
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if obj is None:
            self.report({'WARNING'}, msg)
            return {'CANCELLED'}
        self.report({'INFO'}, "Added %s (%d ports)" % (obj.name, len(obj.optics.ports)))
        return {'FINISHED'}


class OPTICS_OT_import_mesh(Operator):
    bl_idname = "optics.import_mesh"
    bl_label = "Import Mesh (STL/OBJ/STEP)"
    bl_description = "Import a mesh; STEP/IGES are converted via FreeCAD first"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    auto_tag: BoolProperty(name="Auto-detect ports from name", default=True)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self.filepath
        try:
            if path.lower().endswith((".step", ".stp", ".igs", ".iges")):
                path = convert_step(path)
            obj = import_mesh(path)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if self.auto_tag:
            _ops.do_auto_detect(obj)
        self.report({'INFO'}, "Imported %s" % obj.name)
        return {'FINISHED'}


class OPTICS_OT_convert_step(Operator):
    bl_idname = "optics.convert_step"
    bl_label = "Convert STEP/IGES to STL"
    bl_description = "Convert a STEP/IGES file to STL (via FreeCAD) into the cache"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            out = convert_step(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "Converted -> %s" % out)
        return {'FINISHED'}


class OPTICS_OT_save_to_library(Operator):
    bl_idname = "optics.save_to_library"
    bl_label = "Save Active to Library"
    bl_description = "Save the active element's setup as a user library entry (metadata only)"
    bl_options = {'REGISTER'}

    key: StringProperty(name="Key", default="")
    label: StringProperty(name="Label", default="")

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.optics.is_optical

    def invoke(self, context, event):
        if not self.key:
            self.key = context.object.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.key.strip():
            self.report({'ERROR'}, "Enter a key")
            return {'CANCELLED'}
        path = save_component(context.object, self.key.strip(), self.label.strip())
        self.report({'INFO'}, "Saved '%s' -> %s" % (self.key.strip(), path))
        return {'FINISHED'}


_classes = (
    OPTICS_OT_add_from_library,
    OPTICS_OT_import_mesh,
    OPTICS_OT_convert_step,
    OPTICS_OT_save_to_library,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
