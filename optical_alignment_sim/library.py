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

# Built-in component metadata: a broad general-purpose optics library (real vendor
# part numbers). Mesh files are NOT shipped; they are resolved by filename against
# the configured mesh folder, and `add_component` falls back to a generic mesh-free
# element when the CAD is absent. This dict is the catalog that ships with the
# add-on; library/components.json mirrors it (and lets users edit/extend it).
BUILTIN = {
    # sources
    "HNL100LB": {"label": "HeNe Laser (HNL100LB)", "vendor": "Thorlabs", "part_number": "HNL100LB", "mesh": "HNL100LB.stl", "format": "stl", "name": "LASER_HNL100LB", "element_type": "SOURCE", "specs": "632.8 nm, 1.0 mW, linearly polarized", "generic": {"wavelength": 632.8}},
    "HNL210LB": {"label": "HeNe Laser (HNL210LB)", "vendor": "Thorlabs", "part_number": "HNL210LB", "mesh": "HNL210LB.stl", "format": "stl", "name": "LASER_HNL210LB", "element_type": "SOURCE", "specs": "632.8 nm, 2.0 mW, linearly polarized", "generic": {"wavelength": 632.8}},
    "CPS635": {"label": "Collimated Laser Diode (CPS635)", "vendor": "Thorlabs", "part_number": "CPS635", "mesh": "CPS635.stl", "format": "stl", "name": "LASER_CPS635", "element_type": "SOURCE", "specs": "635 nm, 1.2 mW collimated module", "generic": {"wavelength": 635.0}},
    "F810APC635": {"label": "FC/APC Fiber Collimator (F810APC-635)", "vendor": "Thorlabs", "part_number": "F810APC-635", "mesh": "F810APC-635.stl", "format": "stl", "name": "FC_F810APC", "element_type": "FIBER_COLLIMATOR", "specs": "635 nm, f=36.18 mm, 7.5 mm beam", "generic": {"wavelength": 635.0}},
    # mirrors
    "PF10_03_P01": {"label": "1in Protected Silver Mirror (PF10-03-P01)", "vendor": "Thorlabs", "part_number": "PF10-03-P01", "mesh": "PF10-03-P01.stl", "format": "stl", "name": "M_PF10_Ag", "element_type": "MIRROR", "mount": "KM100", "specs": "25.4 mm, 450 nm-20 um, Ravg>95%", "generic": {"size": 25.4}},
    "BB1_E02": {"label": "1in Broadband Dielectric Mirror (BB1-E02)", "vendor": "Thorlabs", "part_number": "BB1-E02", "mesh": "BB1-E02.stl", "format": "stl", "name": "M_BB1_E02", "element_type": "MIRROR", "mount": "POLARIS-K1", "specs": "25.4 mm, 400-750 nm, Ravg>99%", "generic": {"size": 25.4}},
    "PF10_03_G01": {"label": "1in Protected Aluminum Mirror (PF10-03-G01)", "vendor": "Thorlabs", "part_number": "PF10-03-G01", "mesh": "PF10-03-G01.stl", "format": "stl", "name": "M_PF10_Al", "element_type": "MIRROR", "mount": "KM100", "specs": "25.4 mm, 450 nm-20 um, Ravg>90%", "generic": {"size": 25.4}},
    "KCB1C": {"label": "Corner-Cube Mirror (KCB1C)", "vendor": "Thorlabs", "part_number": "KCB1C/M", "mesh": "KCB1C_M.stl", "format": "stl", "name": "M0_KCB1C", "element_type": "PRISM_MIRROR", "specs": "30 mm cage cube, right-angle turning mirror"},
    "MRA25_E02": {"label": "1in Right-Angle Prism Mirror (MRA25-E02)", "vendor": "Thorlabs", "part_number": "MRA25-E02", "mesh": "MRA25-E02.stl", "format": "stl", "name": "M0_MRA25", "element_type": "PRISM_MIRROR", "specs": "25 mm right-angle prism, E02 400-750 nm"},
    # beamsplitters
    "C6WR": {"label": "Beamsplitter Combiner (C6WR)", "vendor": "Thorlabs", "part_number": "C6WR", "mesh": "C6WR.stl", "format": "stl", "name": "BS_C6WR", "element_type": "BEAMSPLITTER", "specs": "wedged plate combiner", "generic": {"split": 0.5}},
    "BS013": {"label": "50:50 Non-Pol. Beamsplitter Cube (BS013)", "vendor": "Thorlabs", "part_number": "BS013", "mesh": "BS013.stl", "format": "stl", "name": "BS_BS013", "element_type": "BEAMSPLITTER", "specs": "1in cube, 400-700 nm, 50:50", "generic": {"split": 0.5, "size": 25.4}},
    "PBS251": {"label": "Polarizing Beamsplitter Cube (PBS251)", "vendor": "Thorlabs", "part_number": "PBS251", "mesh": "PBS251.stl", "format": "stl", "name": "BS_PBS251", "element_type": "BEAMSPLITTER", "specs": "1in PBS cube, 420-680 nm", "generic": {"split": 0.5, "size": 25.4, "pbs": True}},
    "BSW10": {"label": "50:50 Plate Beamsplitter (BSW10)", "vendor": "Thorlabs", "part_number": "BSW10", "mesh": "BSW10.stl", "format": "stl", "name": "BS_BSW10", "element_type": "BEAMSPLITTER", "specs": "1in UVFS plate, 400-700 nm, 50:50", "generic": {"split": 0.5, "size": 25.4}},
    # dichroics
    "DMLP650": {"label": "Longpass Dichroic Mirror (DMLP650)", "vendor": "Thorlabs", "part_number": "DMLP650", "mesh": "DMLP650.stl", "format": "stl", "name": "DM_DMLP650", "element_type": "DICHROIC", "mount": "KM100", "specs": "1in, 650 nm cut-on longpass", "generic": {"split": 0.5}},
    "DMSP805": {"label": "Shortpass Dichroic Mirror (DMSP805)", "vendor": "Thorlabs", "part_number": "DMSP805", "mesh": "DMSP805.stl", "format": "stl", "name": "DM_DMSP805", "element_type": "DICHROIC", "mount": "KM100", "specs": "1in, 805 nm cut-off shortpass", "generic": {"split": 0.5}},
    # grating / retroreflector
    "GH13_12V": {"label": "Reflective Diffraction Grating (GH13-12V)", "vendor": "Thorlabs", "part_number": "GH13-12V", "mesh": "GH13-12V.stl", "format": "stl", "name": "GR_GH13", "element_type": "GRATING", "mount": "KM100", "specs": "12.7x12.7 mm, 1200/mm, 500 nm blaze"},
    "PS975M": {"label": "Mounted Retroreflector (PS975M)", "vendor": "Thorlabs", "part_number": "PS975M", "mesh": "PS975M.stl", "format": "stl", "name": "RR_PS975M", "element_type": "RETROREFLECTOR", "specs": "1in solid corner-cube, 350-700 nm"},
    # lenses
    "BE10A": {"label": "Beam Expander (BE10-A)", "vendor": "Thorlabs", "part_number": "BE10-A", "mesh": "beam_expander.stl", "format": "stl", "name": "BE_expander", "element_type": "LENS", "specs": "10X Galilean, 400-650 nm", "generic": {"radius": 14.0}},
    "MO50X": {"label": "Microscope Objective 50x", "vendor": "generic", "part_number": "50X", "mesh": "microscope_objective.stl", "format": "stl", "name": "MO_objective", "element_type": "LENS", "specs": "50x objective", "generic": {"focal": 4.0, "radius": 8.0}},
    "LA1131_A": {"label": "1in Plano-Convex Lens f=50 mm (LA1131-A)", "vendor": "Thorlabs", "part_number": "LA1131-A", "mesh": "LA1131-A.stl", "format": "stl", "name": "LCP_LA1131", "element_type": "LENS", "specs": "N-BK7, f=50 mm, AR 350-700 nm", "generic": {"focal": 50.0, "radius": 12.7}},
    "AC254_100_A": {"label": "1in Achromatic Doublet f=100 mm (AC254-100-A)", "vendor": "Thorlabs", "part_number": "AC254-100-A", "mesh": "AC254-100-A.stl", "format": "stl", "name": "LCP_AC254", "element_type": "LENS", "specs": "f=100 mm, ARC 400-700 nm", "generic": {"focal": 100.0, "radius": 12.7}},
    # waveplates / polarizer
    "PRM05": {"label": "Waveplate Mount (PRM05)", "vendor": "Thorlabs", "part_number": "PRM05", "mesh": "PRM05_M.stl", "format": "stl", "name": "PRM_waveplate", "element_type": "WAVEPLATE", "specs": "1/2in rotation mount"},
    "WPH10M_633": {"label": "1in Zero-Order Half-Wave Plate (WPH10M-633)", "vendor": "Thorlabs", "part_number": "WPH10M-633", "mesh": "WPH10M-633.stl", "format": "stl", "name": "PRM_HWP633", "element_type": "WAVEPLATE", "specs": "633 nm zero-order HWP, SM1 mount", "generic": {"kind": "HWP"}},
    "WPQ10M_633": {"label": "1in Zero-Order Quarter-Wave Plate (WPQ10M-633)", "vendor": "Thorlabs", "part_number": "WPQ10M-633", "mesh": "WPQ10M-633.stl", "format": "stl", "name": "PRM_QWP633", "element_type": "WAVEPLATE", "specs": "633 nm zero-order QWP, SM1 mount", "generic": {"kind": "QWP"}},
    "LPVISE100_A": {"label": "1in Linear Polarizer (LPVISE100-A)", "vendor": "Thorlabs", "part_number": "LPVISE100-A", "mesh": "LPVISE100-A.stl", "format": "stl", "name": "POL_LPVISE", "element_type": "POLARIZER", "specs": "400-700 nm, N-BK7 windows", "generic": {"radius": 12.5}},
    # filters / attenuators
    "FEL0600": {"label": "1in Longpass Filter 600 nm (FEL0600)", "vendor": "Thorlabs", "part_number": "FEL0600", "mesh": "FEL0600.stl", "format": "stl", "name": "FILT_FEL0600", "element_type": "FILTER", "specs": "600 nm cut-on longpass", "generic": {"radius": 12.5, "filt_type": "LP", "cut_lo_nm": 600.0}},
    "FES0700": {"label": "1in Shortpass Filter 700 nm (FES0700)", "vendor": "Thorlabs", "part_number": "FES0700", "mesh": "FES0700.stl", "format": "stl", "name": "FILT_FES0700", "element_type": "FILTER", "specs": "700 nm cut-off shortpass", "generic": {"radius": 12.5, "filt_type": "SP", "cut_hi_nm": 700.0}},
    "FB633_10": {"label": "1in Bandpass Filter 633 nm (FB633-10)", "vendor": "Thorlabs", "part_number": "FB633-10", "mesh": "FB633-10.stl", "format": "stl", "name": "FILT_FB633", "element_type": "FILTER", "specs": "CWL 633 nm, FWHM 10 nm", "generic": {"radius": 12.5, "filt_type": "BP", "cut_lo_nm": 628.0, "cut_hi_nm": 638.0}},
    "NE10A": {"label": "1in Absorptive ND Filter OD 1.0 (NE10A)", "vendor": "Thorlabs", "part_number": "NE10A", "mesh": "NE10A.stl", "format": "stl", "name": "FILT_NE10A", "element_type": "FILTER", "specs": "OD 1.0, 400-650 nm absorptive ND", "generic": {"radius": 12.5, "filt_type": "ND", "od": 1.0}},
    "VA5": {"label": "Variable Attenuator (VA5-633)", "vendor": "Thorlabs", "part_number": "VA5-633", "mesh": "VA5-633_M.stl", "format": "stl", "name": "VA5_attenuator", "element_type": "ATTENUATOR", "specs": "633 nm variable attenuator"},
    "NDC_50C_2M": {"label": "Continuously Variable ND Wheel (NDC-50C-2M)", "vendor": "Thorlabs", "part_number": "NDC-50C-2M", "mesh": "NDC-50C-2M.stl", "format": "stl", "name": "VA_NDC50C", "element_type": "ATTENUATOR", "specs": "OD 0-2.0 reflective ND wheel"},
    # isolator / apertures / pinhole
    "IO_3D_633": {"label": "Free-Space Faraday Isolator (IO-3D-633-PBS)", "vendor": "Thorlabs", "part_number": "IO-3D-633-PBS", "mesh": "IO-3D-633-PBS.stl", "format": "stl", "name": "ISO_IO3D633", "element_type": "ISOLATOR", "specs": "633 nm, 3 mm aperture, PBS-based", "generic": {"radius": 9.0}},
    "ID25": {"label": "25 mm Iris Diaphragm (ID25)", "vendor": "Thorlabs", "part_number": "ID25", "mesh": "ID25.stl", "format": "stl", "name": "AP_ID25", "element_type": "APERTURE", "specs": "1.0-25 mm SM1 iris", "generic": {"radius": 14.0}},
    "SM1D12": {"label": "SM1 Iris Diaphragm (SM1D12)", "vendor": "Thorlabs", "part_number": "SM1D12", "mesh": "SM1D12.stl", "format": "stl", "name": "AP_SM1D12", "element_type": "APERTURE", "specs": "1.0-12 mm SM1-mounted iris", "generic": {"radius": 12.0}},
    "P50K": {"label": "50 um Pinhole (P50K)", "vendor": "Thorlabs", "part_number": "P50K", "mesh": "P50K.stl", "format": "stl", "name": "PIN_P50K", "element_type": "PINHOLE", "specs": "50 um mounted pinhole", "generic": {"radius": 12.5}},
    # detectors
    "PDA100A2": {"label": "Si Amplified Photodetector (PDA100A2)", "vendor": "Thorlabs", "part_number": "PDA100A2", "mesh": "PDA100A2.stl", "format": "stl", "name": "PD_PDA100A2", "element_type": "PHOTODIODE", "specs": "Si, 320-1100 nm, 75.4 mm2, 11 MHz", "generic": {"size": 14.0}},
    "S120C": {"label": "Si Photodiode Power Sensor (S120C)", "vendor": "Thorlabs", "part_number": "S120C", "mesh": "S120C.stl", "format": "stl", "name": "PM_S120C", "element_type": "POWER_METER", "specs": "Si, 400-1100 nm, 50 nW-50 mW", "generic": {"size": 18.0}},
    # mount-centric part (kept from the original DHM seed)
    "KM100CP_M": {"label": "Kinematic Mirror Mount (KM100CP/M)", "vendor": "Thorlabs", "part_number": "KM100CP/M", "mesh": "KM100CP_M.step", "format": "step", "name": "M_KM100CP", "element_type": "PRISM_MIRROR", "mount": "KM100CP/M", "specs": "1in kinematic mount, +/-4deg tip/tilt"},
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
                        base = comps[k]
                        for kk, vv in v.items():
                            # deep-merge the nested 'generic' dict so a JSON entry that omits
                            # (e.g.) filt_type/pbs doesn't wipe the built-in defaults -- only the
                            # leaves it actually specifies override
                            if kk == "generic" and isinstance(vv, dict) and isinstance(base.get("generic"), dict):
                                base["generic"] = {**base["generic"], **vv}
                            else:
                                base[kk] = vv
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


def _generic_fallback(element_type, name, location, hints):
    """Build the matching Tier-1 (mesh-free) element when no vendor mesh is on disk.
    Keeps the whole component catalog usable out of the box; the user can still
    supply the real CAD later. `hints` is the entry's optional 'generic' dict."""
    from . import elements_generic as eg
    h = hints or {}
    loc = location
    DIR = (0.0, -1.0, 0.0)      # default beam travel (matches the LASER convention)
    TURN = (1.0, 0.0, 0.0)      # default 90deg reflect / out direction
    et = element_type
    if et == 'SOURCE':
        return eg.source(name, loc, DIR, wavelength=h.get("wavelength", 632.8))
    if et == 'FIBER_COLLIMATOR':
        return eg.fiber_collimator(name, loc, DIR, wavelength=h.get("wavelength", 632.8))
    if et == 'MIRROR':
        return eg.mirror(name, loc, DIR, TURN, size=h.get("size", 25.0))
    if et == 'PRISM_MIRROR':
        o = eg.mirror(name, loc, DIR, TURN, size=h.get("size", 25.0))
        o.optics.element_type = 'PRISM_MIRROR'
        return o
    if et == 'BEAMSPLITTER':
        return eg.beamsplitter(name, loc, DIR, TURN, split=h.get("split", 0.5),
                               pbs=bool(h.get("pbs", False)), size=h.get("size", 25.0))
    if et == 'DICHROIC':
        return eg.dichroic(name, loc, DIR, TURN, split=h.get("split", 0.5), size=h.get("size", 25.0))
    if et == 'GRATING':
        return eg.grating(name, loc, DIR, TURN, size=h.get("size", 25.0))
    if et == 'RETROREFLECTOR':
        return eg.retroreflector(name, loc, DIR, size=h.get("size", 25.0))
    if et == 'LENS':
        return eg.lens(name, loc, DIR, focal=h.get("focal", 100.0), radius=h.get("radius", 14.0))
    if et == 'WAVEPLATE':
        return eg.waveplate(name, loc, DIR, kind=h.get("kind", 'HWP'))
    if et == 'POLARIZER':
        return eg.polarizer(name, loc, DIR, radius=h.get("radius", 12.5))
    if et == 'FILTER':
        return eg.optical_filter(name, loc, DIR, radius=h.get("radius", 12.5),
                                 filt_type=h.get("filt_type", 'BP'),
                                 cut_lo_nm=h.get("cut_lo_nm", 600.0),
                                 cut_hi_nm=h.get("cut_hi_nm", 700.0), od=h.get("od", 1.0))
    if et == 'ATTENUATOR':
        o = eg.optical_filter(name, loc, DIR, radius=h.get("radius", 12.5))
        o.optics.element_type = 'ATTENUATOR'
        return o
    if et == 'ISOLATOR':
        return eg.isolator(name, loc, DIR, radius=h.get("radius", 9.0))
    if et == 'APERTURE':
        return eg.aperture(name, loc, DIR, radius=h.get("radius", 14.0))
    if et == 'PINHOLE':
        return eg.pinhole(name, loc, DIR, radius=h.get("radius", 12.5))
    if et == 'DETECTOR':
        return eg.detector(name, loc, DIR, size=h.get("size", 22.0))
    if et == 'PHOTODIODE':
        return eg.photodiode(name, loc, DIR, size=h.get("size", 14.0))
    if et == 'POWER_METER':
        return eg.power_meter(name, loc, DIR, size=h.get("size", 20.0))
    if et == 'CAVITY':
        return eg.cavity(name, loc, DIR, spacing_mm=h.get("spacing_mm", 0.05),
                         R=h.get("R", 0.9), size=h.get("size", 25.0))
    if et == 'WAVEFRONT_SENSOR':
        return eg.wavefront_sensor(name, loc, DIR, size=h.get("size", 22.0))
    if et == 'DEFORMABLE_MIRROR':
        return eg.deformable_mirror(name, loc, DIR, TURN, size=h.get("size", 25.0))
    if et == 'ABERRATOR':
        return eg.aberrator(name, loc, DIR, radius=h.get("radius", 14.0))
    if et == 'PASSTHROUGH':                                  # free transmit, NOT an aperture (no clip)
        o = eg.aperture(name, loc, DIR, radius=h.get("radius", 14.0))
        o.optics.element_type = 'PASSTHROUGH'
        return o
    # last resort: a transparent inline placeholder
    return eg.aperture(name, loc, DIR, radius=h.get("radius", 14.0))


def add_component(key, location=(0.0, 0.0, 0.0)):
    comps = get_components()
    if key not in comps:
        return None, "unknown component '%s'" % key
    e = comps[key]
    name = e.get("name") or key
    msg = "ok"
    try:
        path = resolve_mesh(e)
        obj = import_mesh(path)
        obj.location = location
        obj.name = name
        obj.optics.is_optical = True
        if e.get("element_type"):
            obj.optics.element_type = e["element_type"]
        _ops.do_auto_detect(obj)
        if e.get("element_type"):
            obj.optics.element_type = e["element_type"]   # keep explicit type
    except (FileNotFoundError, RuntimeError) as ex:
        # No usable vendor mesh -> fall back to a generic (mesh-free) element instead
        # of failing, so every catalog entry spawns correct optical geometry.
        et = e.get("element_type") or 'PASSTHROUGH'
        obj = _generic_fallback(et, name, location, e.get("generic"))
        if obj is None:
            return None, str(ex)
        msg = "ok (generic placeholder - supply mesh '%s' for real CAD)" % e.get("mesh", "?")
    if e.get("mount") and e["mount"] in {**presets.MOUNT_LIBRARY, **mounts.get_library()}:
        mounts.apply_preset(obj, e["mount"])
    return obj, msg


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
