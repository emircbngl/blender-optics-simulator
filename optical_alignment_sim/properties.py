"""Data model: PropertyGroups attached to objects (and the scene).

Optical semantics live on `bpy.types.Object.optics` so they serialize into the
.blend automatically and survive save/reload. Scene-wide settings live on
`bpy.types.Scene.optics`.
"""
from __future__ import annotations

import bpy
from bpy.props import (
    StringProperty, FloatProperty, IntProperty, BoolProperty,
    EnumProperty, FloatVectorProperty, PointerProperty, CollectionProperty,
)
from bpy.types import PropertyGroup

# --- enums ------------------------------------------------------------------

ELEMENT_TYPES = [
    ('NONE',         "None",                       "Not an optical element"),
    ('SOURCE',       "Source / Laser",             "Beam source"),
    ('MIRROR',       "Mirror",                     "Flat reflective surface"),
    ('PRISM_MIRROR', "Prism Mirror (cage cube)",   "Internal 45deg reflective cube (e.g. KCB1C)"),
    ('BEAMSPLITTER', "Beam Splitter",              "Splits into reflected + transmitted"),
    ('DICHROIC',     "Dichroic Mirror",            "Wavelength-selective splitter (reflect + transmit)"),
    ('GRATING',      "Diffraction Grating",        "Reflective grating (0th-order specular in layout)"),
    ('RETROREFLECTOR', "Retroreflector",           "Corner-cube; returns the beam"),
    ('LENS',         "Lens",                       "Focusing / diverging element"),
    ('WAVEPLATE',    "Waveplate",                  "Polarization element (pass-through)"),
    ('POLARIZER',    "Polarizer",                  "Linear polarizer (pass-through)"),
    ('FILTER',       "Optical Filter",             "Longpass / shortpass / bandpass / ND (pass-through)"),
    ('ATTENUATOR',   "Attenuator",                 "Pass-through attenuator"),
    ('ISOLATOR',     "Optical Isolator",           "One-way pass-through (Faraday isolator)"),
    ('APERTURE',     "Aperture",                   "Beam stop / aperture"),
    ('PINHOLE',      "Pinhole",                    "Spatial-filter pinhole (pass-through)"),
    ('FIBER_COLLIMATOR', "Fiber Collimator",       "Fiber-coupled collimator used as a beam source"),
    ('DETECTOR',     "Detector / Camera",          "Terminates the beam"),
    ('PHOTODIODE',   "Photodiode",                 "Terminates the beam (point detector)"),
    ('POWER_METER',  "Power Meter",                "Terminates the beam (power sensor head)"),
    ('PASSTHROUGH',  "Pass-through",               "Generic transparent element"),
]

PORT_ROLES = [
    ('IN',       "In",       "Beam enters here"),
    ('OUT',      "Out",      "Beam exits here"),
    ('REFLECT',  "Reflect",  "Reflective surface plane"),
    ('TRANSMIT', "Transmit", "Transmissive surface"),
]

MOUNT_TYPES = [
    ('FIXED',           "Fixed",             "No adjustment"),
    ('KINEMATIC_2AXIS', "Kinematic tip/tilt", "Two-axis tip/tilt about a pivot"),
    ('TRANSLATION',     "Translation stage", "Linear X / Y / Z"),
    ('ROTATION',        "Rotation mount",    "Rotation about the optical axis"),
    ('GIMBAL',          "Gimbal",            "Gimbal mount"),
]

DOF_KINDS = [
    ('TIP',     "Tip",         "Rotate about a horizontal axis"),
    ('TILT',    "Tilt",        "Rotate about a vertical axis"),
    ('ROT',     "Rotate",      "Rotate about the optical axis"),
    ('TRANS_X', "Translate X", "Linear travel along X"),
    ('TRANS_Y', "Translate Y", "Linear travel along Y"),
    ('TRANS_Z', "Translate Z", "Linear travel along Z"),
]

ALIGN_STATES = [
    ('UNKNOWN', "Unknown", ""),
    ('OK',      "OK",      ""),
    ('WARN',    "Warn",    ""),
    ('BAD',     "Bad",     ""),
]

MECH_KINDS = [
    ('POST_INSERT', "Post insertion", "Post rod inside a post-holder"),
    ('CAGE_ROD',    "Cage rod",       "Cage rod spanning two components"),
]


# --- update callbacks (defined before the classes that reference them) ------

def _dof_update(self, context):
    """A knob slider changed -> recompose the owning object's pose.
    Deferred import keeps this safe before mounts.py exists (milestone 2)."""
    try:
        from . import mounts
        obj = self.id_data                  # the Object owning this knob (not necessarily active)
        if obj is not None and getattr(obj, "optics", None) and obj.optics.is_optical:
            mounts.compose_pose(obj)
    except Exception:
        pass


def _live_update(self, context):
    """Live-simulation toggle changed -> arm/disarm handlers (milestone 3)."""
    try:
        from . import handlers
        handlers.set_live(self.live_enabled)
    except Exception:
        pass


# --- property groups --------------------------------------------------------

class OpticalPort(PropertyGroup):
    name: StringProperty(name="Name", default="IN")
    role: EnumProperty(name="Role", items=PORT_ROLES, default='IN')
    local_position: FloatVectorProperty(name="Local Position", size=3, subtype='XYZ', unit='LENGTH')
    local_normal: FloatVectorProperty(name="Local Normal", size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0))
    clear_aperture: FloatProperty(name="Clear Aperture", default=12.7, min=0.0)


class AdjustmentDOF(PropertyGroup):
    name: StringProperty(name="Name", default="DOF")
    kind: EnumProperty(name="Kind", items=DOF_KINDS, default='TIP')
    axis_local: FloatVectorProperty(name="Axis (local)", size=3, subtype='DIRECTION', default=(1.0, 0.0, 0.0))
    pivot_local: FloatVectorProperty(name="Pivot (local)", size=3, subtype='XYZ', default=(0.0, 0.0, 0.0))
    min_val: FloatProperty(name="Min", default=-4.0)
    max_val: FloatProperty(name="Max", default=4.0)
    current: FloatProperty(name="Value", default=0.0, update=_dof_update)


class MechLink(PropertyGroup):
    name: StringProperty(name="Name", default="link")
    target: PointerProperty(name="Holder / Neighbor", type=bpy.types.Object)
    kind: EnumProperty(name="Kind", items=MECH_KINDS, default='POST_INSERT')
    insert_min: FloatProperty(name="Min insertion (mm)", default=8.0)
    insert_max: FloatProperty(name="Max insertion (mm)", default=50.0)
    state: StringProperty(name="State", default="UNKNOWN")
    detail: StringProperty(name="Detail", default="")


class OpticalElementProps(PropertyGroup):
    is_optical: BoolProperty(name="Optical element", default=False)
    element_type: EnumProperty(name="Type", items=ELEMENT_TYPES, default='NONE')

    ports: CollectionProperty(type=OpticalPort)
    ports_index: IntProperty(default=0)

    mount_type: EnumProperty(name="Mount", items=MOUNT_TYPES, default='FIXED')
    mount_preset: StringProperty(name="Mount preset", default="")
    base_pose: FloatVectorProperty(
        name="Base pose", size=16,
        default=(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    )
    base_pose_set: BoolProperty(default=False)
    dofs: CollectionProperty(type=AdjustmentDOF)
    dofs_index: IntProperty(default=0)
    mech: CollectionProperty(type=MechLink)

    # optical parameters (geometric v1 uses a subset; rest reserved for Gaussian/ABCD)
    focal_length: FloatProperty(name="Focal length (mm)", default=0.0)
    split_ratio: FloatProperty(name="Reflect fraction", default=0.5, min=0.0, max=1.0)
    prism_angle: FloatProperty(name="Prism angle (deg)", default=45.0)
    clear_aperture: FloatProperty(name="Clear aperture (mm)", default=12.7, min=0.0)
    reflectivity: FloatProperty(name="Reflectivity", default=1.0, min=0.0, max=1.0)
    wavelength: FloatProperty(name="Wavelength (nm)", default=632.8)
    refractive_index: FloatProperty(name="Refractive index", default=1.5168)
    is_source: BoolProperty(default=False)
    is_detector: BoolProperty(default=False)

    # computed (written by alignment.py / mounts.py)
    misalign_pos_mm: FloatProperty(default=0.0)
    misalign_ang_deg: FloatProperty(default=0.0)
    align_state: EnumProperty(items=ALIGN_STATES, default='UNKNOWN')
    mech_state: StringProperty(default="UNKNOWN")
    align_detail: StringProperty(default="")


class OpticalSceneProps(PropertyGroup):
    live_enabled: BoolProperty(name="Live simulation", default=False, update=_live_update)
    trace_mode: EnumProperty(
        name="Trace mode",
        items=[('AUTO', "Auto-follow", "Follow nearest in-port ahead of the beam"),
               ('ORDER', "Explicit order", "Use the ordered element list below")],
        default='AUTO',
    )
    order_csv: StringProperty(name="Order (CSV)", default="")
    max_segments: IntProperty(default=64, min=1, max=1024)
    max_depth: IntProperty(default=12, min=1, max=64)
    line_width: FloatProperty(name="Beam width", default=3.0, min=0.5, max=10.0)
    show_ports: BoolProperty(name="Show ports", default=True)
    auto_color: BoolProperty(name="Auto color by alignment", default=True)
    # alignment thresholds
    ok_pos_mm: FloatProperty(name="OK pos (mm)", default=0.5, min=0.0)
    ok_ang_deg: FloatProperty(name="OK ang (deg)", default=0.2, min=0.0)
    warn_pos_mm: FloatProperty(name="Warn pos (mm)", default=2.0, min=0.0)
    warn_ang_deg: FloatProperty(name="Warn ang (deg)", default=1.0, min=0.0)


_classes = (OpticalPort, AdjustmentDOF, MechLink, OpticalElementProps, OpticalSceneProps)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Object.optics = PointerProperty(type=OpticalElementProps)
    bpy.types.Scene.optics = PointerProperty(type=OpticalSceneProps)


def unregister():
    if hasattr(bpy.types.Scene, "optics"):
        del bpy.types.Scene.optics
    if hasattr(bpy.types.Object, "optics"):
        del bpy.types.Object.optics
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
