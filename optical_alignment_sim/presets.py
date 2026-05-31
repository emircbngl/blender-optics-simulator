"""Static data tables. Pure data + tiny helpers, no bpy side effects.

  * PREFIX_RULES   - map an object-name prefix to an optical element type and a
                     canonical set of ports (face axes). Honors the user's
                     existing DHM naming (LASER_, M0_, M_ref_, BS_, ...).
  * MOUNT_LIBRARY  - mount kinematics (pivot / DOF axes / range), seeded from the
                     supplied vendor drawings (Thorlabs KM100CP/M, Edmund 15866).
                     mounts.py merges this with the user's editable JSON library.
"""
from __future__ import annotations

# Port spec tuple: (port_name, role, axis)  with axis in +X/-X/+Y/-Y/+Z/-Z.
# A REFLECT port (for PRISM_MIRROR) is derived: position = local bbox center,
# normal = normalize(IN_normal + OUT_normal).
PREFIX_RULES = [
    ("LASER",    "SOURCE",       [("OUT", "OUT", "-Y")]),
    ("M0",       "PRISM_MIRROR", [("IN", "IN", "+Z"), ("OUT", "OUT", "+Y")]),
    ("M_ref",    "PRISM_MIRROR", [("IN", "IN", "-Y"), ("OUT", "OUT", "-X")]),
    ("M_sam",    "PRISM_MIRROR", [("IN", "IN", "+X"), ("OUT", "OUT", "+Y")]),
    ("M_steer",  "PRISM_MIRROR", [("IN", "IN", "+Z"), ("OUT", "OUT", "+Y")]),
    ("BS",       "BEAMSPLITTER", [("IN_ref", "IN", "+X"),
                                  ("IN_sam", "IN", "-Y"),
                                  ("OUT", "OUT", "+Y")]),
    ("VA",       "ATTENUATOR",   [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("PRM",      "WAVEPLATE",    [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("LCP",      "LENS",         [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("BE",       "LENS",         [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("MO",       "LENS",         [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("TubeLens", "LENS",         [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("CCD",      "DETECTOR",     [("IN", "IN", "+Z")]),
    # --- broad-library additions ---
    ("DM",       "DICHROIC",       [("IN", "IN", "+Z"), ("OUT", "OUT", "+Y")]),
    ("GR",       "GRATING",        [("IN", "IN", "+Z"), ("OUT", "OUT", "+Y")]),
    ("RR",       "RETROREFLECTOR", [("IN", "IN", "+Z"), ("OUT", "OUT", "+Z")]),
    ("POL",      "POLARIZER",      [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("FILT",     "FILTER",         [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("PIN",      "PINHOLE",        [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("ISO",      "ISOLATOR",       [("IN", "IN", "+Z"), ("OUT", "OUT", "-Z")]),
    ("FC",       "FIBER_COLLIMATOR", [("OUT", "OUT", "-Y")]),
    ("PD",       "PHOTODIODE",     [("IN", "IN", "+Z")]),
    ("PM",       "POWER_METER",    [("IN", "IN", "+Z")]),
    # NOTE: a bare "M" rule is intentionally omitted to avoid swallowing MO/M_*.
]


def match_prefix(name: str):
    """Return (element_type, port_specs) for the LONGEST matching name prefix,
    or (None, None). startswith() on the base token means '_PROBLEM_*' suffixes
    do not break matching."""
    best = None
    for prefix, etype, ports in PREFIX_RULES:
        if name.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, etype, ports)
    return (best[1], best[2]) if best else (None, None)


# Mount kinematics seeded from the vendor CAD drawings the user supplied.
# pivot: "OPTIC_CENTER" (center-axis mounts) or a [x,y,z] local vector.
# dof axis in +X/-X/...; range min/max in degrees (rotational) or mm (linear).
# Angular ranges are datasheet/spec values (NOT on the CAD drawing) - confirm.
MOUNT_LIBRARY = {
    "KM100CP/M": {
        "mount_type": "KINEMATIC_2AXIS",
        "pivot": "OPTIC_CENTER",            # Thorlabs "Kinematic Center Axis"
        "optic_diameter_mm": 25.4,
        "clear_aperture_mm": 23.9,
        "optic_seat_depth_mm": 5.1,
        "adjuster_thread": "1/4in-80",
        "mm_per_rev": 25.4 / 80.0,          # 0.3175 mm/rev
        "dofs": [
            {"kind": "TIP",  "axis": "+X", "min": -4.0, "max": 4.0},
            {"kind": "TILT", "axis": "+Y", "min": -4.0, "max": 4.0},
        ],
        "note": "Range +/-4deg is a spec value (not on the drawing) - confirm on thorlabs.com.",
    },
    "EO-15866": {
        "mount_type": "KINEMATIC_2AXIS",
        "pivot": "OPTIC_CENTER",
        "optic_diameter_mm": 25.4,
        "clear_aperture_mm": 23.0,
        "optic_seat_depth_mm": 6.5,
        "dofs": [
            {"kind": "TIP",  "axis": "+X", "min": -4.0, "max": 4.0},   # drawing label: PITCH
            {"kind": "TILT", "axis": "+Y", "min": -4.0, "max": 4.0},   # drawing label: ROLL
        ],
        "note": "Edmund 25/25.4mm E-Series; axes PITCH/ROLL on drawing; range from spec.",
    },
    "KM100": {
        "mount_type": "KINEMATIC_2AXIS",
        "pivot": "OPTIC_CENTER",
        "optic_diameter_mm": 25.4,
        "clear_aperture_mm": 22.3,
        "adjuster_thread": "8-32",
        "dofs": [
            {"kind": "TIP",  "axis": "+X", "min": -4.0, "max": 4.0},
            {"kind": "TILT", "axis": "+Y", "min": -4.0, "max": 4.0},
        ],
        "note": "Thorlabs 1in kinematic mirror mount; angular range is a spec value - confirm.",
    },
    "POLARIS-K1": {
        "mount_type": "KINEMATIC_2AXIS",
        "pivot": "OPTIC_CENTER",
        "optic_diameter_mm": 25.4,
        "clear_aperture_mm": 23.1,
        "adjuster_thread": "100 TPI",
        "mm_per_rev": 25.4 / 100.0,             # 0.254 mm/rev
        "dofs": [
            {"kind": "TIP",  "axis": "+X", "min": -4.0, "max": 4.0},
            {"kind": "TILT", "axis": "+Y", "min": -4.0, "max": 4.0},
        ],
        "note": "Thorlabs Polaris 1in low-drift mount; range is a spec value - confirm.",
    },
    "KS1": {
        "mount_type": "KINEMATIC_2AXIS",
        "pivot": "OPTIC_CENTER",
        "optic_diameter_mm": 25.4,
        "clear_aperture_mm": 22.6,
        "adjuster_thread": "100 TPI",
        "mm_per_rev": 25.4 / 100.0,
        "dofs": [
            {"kind": "TIP",  "axis": "+X", "min": -4.0, "max": 4.0},
            {"kind": "TILT", "axis": "+Y", "min": -4.0, "max": 4.0},
        ],
        "note": "Thorlabs 1in kinematic mount; range is a spec value - confirm.",
    },
}
