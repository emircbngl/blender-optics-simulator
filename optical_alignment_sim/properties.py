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
    ('CAVITY',       "Fabry-Perot cavity",         "Two partial mirrors; Airy transmission"),
    ('WAVEFRONT_SENSOR', "Wavefront Sensor",        "Shack-Hartmann-style modal wavefront sensor (Zernike readout)"),
    ('DEFORMABLE_MIRROR', "Deformable Mirror",      "Corrector mirror; subtracts its commanded Zernike modes"),
    ('ABERRATOR',    "Aberrator / Turbulence",     "Injects a Zernike wavefront error (the disturbance to correct)"),
    ('CRYSTAL',      "Nonlinear Crystal",          "chi(2) frequency conversion (SHG / SPDC); emits converted beams"),
    ('OBJECTIVE',    "Microscope Objective",       "High-NA objective; focal power f_obj = f_tube/M, magnifies + focuses"),
    ('AOM',          "Acousto-Optic Modulator",    "Bragg cell: deflects the +1 order by theta = lambda*f_a/v_s + frequency-shifts it by f_a"),
]

PORT_ROLES = [
    ('IN',       "In",       "Beam enters here"),
    ('OUT',      "Out",      "Beam exits here"),
    ('REFLECT',  "Reflect",  "Reflective surface plane"),
    ('TRANSMIT', "Transmit", "Transmissive surface"),
]

MOUNT_TYPES = [
    ('FIXED',           "Fixed",             "No adjustment"),
    ('KINEMATIC_2AXIS', "Kinematic tip/tilt", "Two-axis tip/tilt about a pivot (KM100-style, 2 adjusters)"),
    ('KINEMATIC_3AXIS', "Kinematic 3-adjuster", "Three-adjuster kinematic mount (KS1-style, triangular)"),
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


def _anchor_poll(self, obj):
    """An element may be anchored only to a different object and only if it does not create a
    cycle (anchoring A->B while B->A never converges and freezes the pair)."""
    if obj is self.id_data:
        return False
    me, cur, seen = self.id_data, obj, set()
    while cur is not None and id(cur) not in seen:
        if cur is me:
            return False
        seen.add(id(cur))
        op = getattr(cur, "optics", None)
        cur = getattr(op, "anchor", None) if op else None
    return True


def _anchor_update(self, context):
    """Anchor pointer changed -> recompose so the element follows it immediately."""
    try:
        from . import mounts
        o = self.id_data
        if o is not None and getattr(o, "optics", None) and o.optics.base_pose_set:
            mounts.compose_pose(o)
    except Exception:
        pass


def _live_update(self, context):
    """Live-simulation toggle changed -> arm/disarm handlers (milestone 3)."""
    try:
        from . import handlers
        handlers.set_live(self.live_enabled)
    except Exception:
        pass


def _bg_update(self, context):
    """Background preset changed -> apply it immediately (live in rendered view)."""
    try:
        from . import render
        render.apply_background(self.id_data)        # self.id_data is the Scene
    except Exception:
        pass


def _monitor_update(self, context):
    """Sensor-window toggle changed -> show + refresh the overlay immediately, instead of
    waiting for the next depsgraph update (so the checkbox feels responsive)."""
    try:
        from . import monitor, scan, tracer
        scn = self.id_data                           # the Scene
        if self.monitor_show:
            monitor.enable()
            if not tracer.cached_segments:
                tracer.cached_segments = scan._trace(scn)
            scan.live_fringe_update(scn)
        tracer._tag_redraw()
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
    # which support SYSTEM holds the optic (distinct from mount_type, the adjuster kinematics):
    # a single post, a 16/30/60 mm cage train, or a rail carrier. Members sharing a cage system +
    # cage_id form one cage assembly (4 shared rods + a plate per member) — see optomech.dress().
    support_system: EnumProperty(
        name="Support", default='POST',
        items=[('POST',      "Post",       "Own post + post-holder on the breadboard"),
               ('CAGE_16',   "16 mm cage", "Ø4 mm rods on a 16 mm square (SM05 / Ø1/2\")"),
               ('CAGE_30',   "30 mm cage", "Ø6 mm rods on a 30 mm square (SM1 / Ø1\")"),
               ('CAGE_60',   "60 mm cage", "Ø6 mm rods on a 60 mm square (SM2 / Ø2\")"),
               ('TUBE_SM05', "SM05 tube",  "Ø1/2\" optics stacked in one SM05 lens-tube barrel"),
               ('TUBE_SM1',  "SM1 tube",   "Ø1\" optics stacked in one SM1 lens-tube barrel"),
               ('TUBE_SM2',  "SM2 tube",   "Ø2\" optics stacked in one SM2 lens-tube barrel"),
               ('RAIL',      "Rail",       "Carrier on a dovetail/construction rail")])
    cage_id: StringProperty(name="Cage group", default="")
    tube_id: StringProperty(name="Tube group", default="")
    rail_id: StringProperty(name="Rail group", default="")
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
    # lens FORM (variant) -- shapes the mesh; the ABCD focal power is unchanged (set by focal_length).
    # AUTO = bi-convex/bi-concave by the sign of focal_length (the historic behavior).
    lens_type: EnumProperty(name="Lens form", default='AUTO',
        items=[('AUTO', "Auto (by focal sign)", "Bi-convex if f>=0, bi-concave if f<0"),
               ('PCX', "Plano-convex", "Flat back, convex front (converging)"),
               ('BCX', "Bi-convex", "Both surfaces convex (converging)"),
               ('PCV', "Plano-concave", "Flat back, concave front (diverging)"),
               ('BCV', "Bi-concave", "Both surfaces concave (diverging)"),
               ('MENISCUS_POS', "Positive meniscus", "Convex-concave, net converging"),
               ('MENISCUS_NEG', "Negative meniscus", "Concave-convex, net diverging"),
               ('ACHROMAT', "Achromatic doublet", "Cemented crown+flint pair"),
               ('ASPHERE', "Aspheric", "Single aspheric surface"),
               ('CYLINDRICAL', "Cylindrical", "Power in one axis only"),
               ('BALL', "Ball lens", "Full sphere"),
               ('GRIN', "GRIN rod", "Flat-faced gradient-index rod"),
               ('FRESNEL', "Fresnel", "Grooved flat lens"),
               ('AXICON', "Axicon", "Conical lens -> Bessel beam")])
    # beamsplitter FORM (variant) -- shapes the mesh; split behavior unchanged (split_ratio, is_pbs).
    bs_form: EnumProperty(name="BS form", default='CUBE',
        items=[('CUBE', "Cube (cemented)", "Two cemented prisms, 45 deg coated hypotenuse"),
               ('PLATE', "Plate (wedged)", "A coated wedged plate at 45 deg"),
               ('PELLICLE', "Pellicle", "A thin membrane (negligible ghost / dispersion)")])
    split_ratio: FloatProperty(name="Reflect fraction", default=0.5, min=0.0, max=1.0)
    prism_angle: FloatProperty(name="Prism angle (deg)", default=45.0)
    clear_aperture: FloatProperty(name="Clear aperture (mm)", default=12.7, min=0.0)
    reflectivity: FloatProperty(name="Reflectivity", default=1.0, min=0.0, max=1.0)
    # mirror CURVATURE (variant): a curved mirror focuses on reflection with f = R/2 (VERIFIED:
    # spherical-mirror-focal-length, physics_verify 4/4). FLAT = no focal power (the historic behavior).
    mirror_curve: EnumProperty(name="Mirror curvature", default='FLAT',
        items=[('FLAT', "Flat", "Planar fold mirror (no focal power)"),
               ('CONCAVE', "Concave", "Converging: f = +R/2"),
               ('CONVEX', "Convex", "Diverging: f = -R/2")])
    radius_curv: FloatProperty(name="Radius of curvature (mm)", default=0.0, min=0.0)  # |R|; f=R/2
    wavelength: FloatProperty(name="Wavelength (nm)", default=632.8, min=1.0)   # 0 nm would divide-by-zero the Gaussian q
    refractive_index: FloatProperty(name="Refractive index", default=1.5168)

    # --- physics-layer parameters (read by the polarization / wavelength engine) ---
    pol_type: EnumProperty(name="Source polarization",
        items=[('LINEAR', "Linear", ""), ('CIRCULAR', "Circular", ""), ('UNPOL', "Unpolarized", "")],
        default='LINEAR')
    pol_angle: FloatProperty(name="Polarization angle (deg)", default=0.0)
    handedness: EnumProperty(name="Handedness",
        items=[('RIGHT', "Right", ""), ('LEFT', "Left", "")], default='RIGHT')
    linewidth_nm: FloatProperty(name="Linewidth (nm)", default=0.0, min=0.0)   # 0 -> ideal coherence
    bandwidth_nm: FloatProperty(name="Bandwidth (nm)", default=0.0, min=0.0)   # >0 -> broadband / white-light
    waist_um: FloatProperty(name="Beam waist (um)", default=500.0, min=0.0)
    # M^2 beam-quality ("times-diffraction-limit") factor (B1). Far-field divergence
    # theta = M2*lambda/(pi*w0), BPP = M2*lambda/pi (physics_verify ok=true). The real
    # waist w0 is kept; M2 scales the Rayleigh range zR -> zR/M2 so w(z) far-field
    # broadens by M2. M2=1 is the diffraction limit -> the existing Gaussian, unchanged.
    m2: FloatProperty(name="Beam quality M2", default=1.0, min=1.0,
        description="Beam-quality factor (times diffraction limit). 1.0 = ideal Gaussian "
                    "(TEM00); HeNe ~1.0-1.1, single-mode diode ~1.1-1.3, multimode higher. "
                    "Broadens the far-field divergence by M2 without changing the waist")
    retardance_deg: FloatProperty(name="Retardance (deg)", default=180.0)       # HWP=180, QWP=90
    fast_axis_deg: FloatProperty(name="Fast-axis angle (deg)", default=0.0)
    # retarder ORDER (variant): shapes the mesh thickness; the design-wavelength retardance is unchanged.
    waveplate_order: EnumProperty(name="Retarder order", default='ZERO',
        items=[('ZERO', "Zero-order", "Thin true zero-order (or a compound zero-order pair)"),
               ('MULTI', "Multi-order", "Thicker, many full waves + the design retardance"),
               ('ACHROMATIC', "Achromatic", "Two-material compound, flat retardance vs wavelength")])
    pol_axis_deg: FloatProperty(name="Transmission axis (deg)", default=0.0)
    extinction: FloatProperty(name="Extinction ratio", default=1000.0, min=1.0)
    # polarizer TYPE (variant): shapes the mesh (film disc vs Glan prism block vs Brewster plate). The
    # Jones behavior (a linear polarizer at pol_axis_deg with `extinction`) is the same for all.
    polarizer_type: EnumProperty(name="Polarizer type", default='FILM',
        items=[('FILM', "Film / sheet", "Dichroic sheet polarizer (thin)"),
               ('WIRE_GRID', "Wire grid", "Metal-grid polarizer on a substrate (broadband/IR)"),
               ('GLAN_THOMPSON', "Glan-Thompson", "Cemented calcite prism (wide field)"),
               ('GLAN_TAYLOR', "Glan-Taylor", "Air-spaced calcite prism (high power)"),
               ('GLAN_LASER', "Glan-laser", "Air-spaced w/ escape windows (high power)"),
               ('BREWSTER', "Brewster plate", "Thin plate near Brewster's angle"),
               ('WOLLASTON', "Wollaston prism", "Splits into TWO orthogonally-polarized beams at +-angle/2"),
               ('ROCHON', "Rochon prism", "One undeviated + one deflected orthogonal beam")])
    # angular separation of a polarizing beam-splitting prism (Wollaston/Rochon); a spec, ~1-20 deg.
    split_angle_deg: FloatProperty(name="Split angle (deg)", default=20.0, min=0.0, max=45.0)
    is_pbs: BoolProperty(name="Polarizing (PBS)", default=False)
    pass_type: EnumProperty(name="Pass band",
        items=[('LP', "Longpass", ""), ('SP', "Shortpass", "")], default='LP')
    cut_nm: FloatProperty(name="Cut wavelength (nm)", default=650.0)
    filt_type: EnumProperty(name="Filter type",
        items=[('LP', "Longpass", "Interference longpass (sharp dichroic edge)"),
               ('SP', "Shortpass", "Interference shortpass (sharp dichroic edge)"),
               ('BP', "Bandpass", "Interference bandpass (sharp dichroic edges)"),
               ('ND', "Neutral density", "Spectrally flat attenuation (Beer-Lambert)"),
               ('CGLASS_LP', "Colored-glass longpass", "Schott RG/OG bulk-absorptive longpass (thickness-scaled)"),
               ('CGLASS_SP', "Colored-glass shortpass", "Schott BG bulk-absorptive shortpass (thickness-scaled)"),
               ('CGLASS_BP', "Colored-glass bandpass", "Schott GG/VG bulk-absorptive bandpass (thickness-scaled)")],
        default='BP')
    cut_lo_nm: FloatProperty(name="Cut low (nm)", default=600.0)
    cut_hi_nm: FloatProperty(name="Cut high (nm)", default=700.0)
    od: FloatProperty(name="Optical density", default=1.0, min=0.0)
    # --- colored-glass (CGLASS_*) absorptive filters: Schott-style RG/GG/OG/BG glasses (C2) ---
    # Bulk Beer-Lambert absorption A(lambda) shaped by the cut wavelengths, scaled by glass thickness
    # via the oracle-VERIFIED Schott TIE-35 power law T(d2) = T(d1)^(d2/d1). glass_type only sets the
    # body tint + sensible cut/peak presets; the trace uses cut_lo/hi + thickness_mm/d_ref_mm.
    glass_type: EnumProperty(name="Colored glass",
        items=[('RG610', "RG610 (deep red LP)", ""), ('RG630', "RG630 (red LP)", ""),
               ('OG550', "OG550 (orange LP)", ""), ('OG590', "OG590 (orange-red LP)", ""),
               ('GG495', "GG495 (yellow LP)", ""), ('GG420', "GG420 (pale-yellow LP)", ""),
               ('BG39', "BG39 (blue-green SP)", ""), ('BG40', "BG40 (cyan SP)", ""),
               ('VG9', "VG9 (green BP)", ""), ('CUSTOM', "Custom", "Use cut/peak fields directly")],
        default='RG610')
    thickness_mm: FloatProperty(name="Glass thickness (mm)", default=3.0, min=0.01)
    d_ref_mm: FloatProperty(name="Reference thickness (mm)", default=3.0, min=0.01)
    peak_t: FloatProperty(name="Peak transmittance", default=0.91, min=0.0, max=1.0)
    edge_width_nm: FloatProperty(name="Absorptive edge width (nm)", default=18.0, min=1.0)
    # --- dielectric interference filters (LP/SP/BP): soft (finite-slope) edges + AOI blue-shift (C1) ---
    # A real thin-film interference filter does NOT have a step edge: it has a finite-slope transition
    # (edge_width), a finite stopband floor (10^-od_block, never exactly 0), and its edge/band BLUE-SHIFTS
    # with angle of incidence theta:  lambda_c_eff = lambda_c * sqrt(1 - (sin theta / n_eff)^2)
    # (n_eff ~ 1.85, the effective coating index; physics_verify ok=true, 550nm/60deg -> 486nm).
    edge_width: FloatProperty(name="Edge width (nm)", default=3.0, min=0.1,
        description="Logistic edge slope for LP/SP (nm); ~10x sharper than a colored-glass edge")
    od_block: FloatProperty(name="Block OD", default=4.0, min=0.0,
        description="Stopband optical density; floor transmission = 10^-od_block (finite, not 0)")
    n_eff: FloatProperty(name="Effective coating index", default=1.85, min=1.0,
        description="Effective index for the AOI blue-shift lambda_c*sqrt(1-(sin theta/n_eff)^2)")
    cwl_nm: FloatProperty(name="Center wavelength (nm)", default=550.0, min=1.0,
        description="Bandpass center wavelength (CWL) for the super-Gaussian flat-top")
    fwhm_nm: FloatProperty(name="Bandpass FWHM (nm)", default=40.0, min=0.1,
        description="Bandpass full-width-at-half-maximum for the order-3 super-Gaussian")
    lines_per_mm: FloatProperty(name="Grating lines/mm", default=1200.0, min=0.0)
    grating_order: IntProperty(name="Diffraction order", default=1)
    analyzer: EnumProperty(name="Analyzer",
        items=[('NONE', "None", ""), ('H', "H linear", ""), ('V', "V linear", ""),
               ('D', "Diagonal", ""), ('A', "Anti-diagonal", ""),
               ('RCP', "Right circular", ""), ('LCP', "Left circular", "")],
        default='NONE')
    coating: EnumProperty(name="Mirror coating",
        items=[('DIELECTRIC', "Dielectric (ideal)", ""), ('AL', "Aluminum", ""),
               ('AG', "Silver", ""), ('AU', "Gold", "")], default='DIELECTRIC')
    design_wl: FloatProperty(name="Design wavelength (nm)", default=633.0, min=1.0)  # spec point; 0 would null a waveplate
    cavity_spacing_mm: FloatProperty(name="Cavity spacing (mm)", default=0.05, min=1e-4)
    # nonlinear-crystal chi(2) process (variant). SHG: emit lam/2 (VERIFIED second-harmonic-generation).
    # SPDC: emit signal+idler at 2*lam degenerate (VERIFIED spdc-energy-conservation). NONE: pump dump.
    nl_process: EnumProperty(name="chi(2) process", default='NONE',
        items=[('NONE', "None (dump)", "Absorb the pump (no conversion)"),
               ('SHG', "SHG (frequency doubling)", "Emit the second harmonic at lambda/2"),
               ('SPDC', "SPDC (down-conversion)", "Emit degenerate signal + idler at 2*lambda")])
    nl_efficiency: FloatProperty(name="Conversion efficiency", default=0.4, min=0.0, max=1.0)
    # microscope objective (VERIFIED microscope-objective-magnification + numerical-aperture):
    # f_obj = f_tube/M (infinity) or tube_length/M (finite); the tracer focuses with f_obj.
    obj_mag: FloatProperty(name="Magnification (x)", default=10.0, min=1.0)
    obj_na: FloatProperty(name="Numerical aperture", default=0.25, min=0.01, max=1.6)
    obj_wd: FloatProperty(name="Working distance (mm)", default=10.0, min=0.0)
    obj_correction: EnumProperty(name="Correction", default='INFINITY',
        items=[('INFINITY', "Infinity-corrected", "Collimated output to a tube lens (modern)"),
               ('FINITE_160', "Finite (160 mm DIN)", "Forms the image at the 160 mm tube"),
               ('FINITE_195', "Finite (195 mm)", "Forms the image at the 195 mm tube")])
    obj_tube_ref: FloatProperty(name="Tube-lens focal (mm)", default=200.0, min=1.0)  # Nikon/Leica 200, Olympus 180, Zeiss 165
    obj_long_wd: BoolProperty(name="Long working distance", default=False)
    # acousto-optic modulator / Bragg cell (VERIFIED acousto-optic-bragg-deflection): a travelling acoustic
    # grating (period Lambda = v_s/f_a) diffracts the +1 order at theta = lambda*f_a/v_s and frequency-shifts
    # it by +f_a (optical shift ~1e-7 of lambda -> below the model's wavelength resolution, carried as metadata).
    aom_freq_mhz: FloatProperty(name="Acoustic frequency (MHz)", default=80.0, min=0.0)   # f_a
    aom_sound_mps: FloatProperty(name="Sound velocity (m/s)", default=4200.0, min=1.0)     # v_s (TeO2 longitudinal ~4200)
    aom_efficiency: FloatProperty(name="Diffraction efficiency", default=0.85, min=0.0, max=1.0)  # power into +1 order
    is_monitor: BoolProperty(default=False)        # live sensor-monitor target (fringe recomputed live)
    sensor_px: IntProperty(name="Sensor resolution (px)", default=256, min=16, max=1024)
    pixel_size_um: FloatProperty(name="Pixel size (um)", default=5.0, min=0.1)
    sensor_exposure: FloatProperty(name="Exposure (0 = ideal)", default=0.0, min=0.0)
    sensor_read_noise: FloatProperty(name="Read noise (counts)", default=5.0, min=0.0)
    sensor_well_depth: FloatProperty(name="Saturation (counts)", default=4000.0, min=1.0)
    # adaptive optics (modal Zernike): aberrator injects, deformable mirror subtracts, sensor reads
    aberr_spec: FloatVectorProperty(name="Aberration (waves)", size=15, default=[0.0] * 15)
    dm_command: FloatVectorProperty(name="DM command (waves)", size=15, default=[0.0] * 15)
    ao_gain: FloatProperty(name="Loop gain", default=0.5, min=0.0, max=1.0)
    wf_rms: FloatProperty(name="Wavefront RMS (waves)", default=0.0)
    part_key: StringProperty(name="Part", default="")   # catalog key / filename currently filling this slot
    anchor: PointerProperty(name="Anchor", type=bpy.types.Object, poll=_anchor_poll,
                            update=_anchor_update,
                            description="If set, this element's pose is relative to (follows) this object")

    is_source: BoolProperty(default=False)
    is_detector: BoolProperty(default=False)

    # computed (written by alignment.py / mounts.py)
    misalign_pos_mm: FloatProperty(default=0.0)
    misalign_ang_deg: FloatProperty(default=0.0)
    align_state: EnumProperty(items=ALIGN_STATES, default='UNKNOWN')
    mech_state: StringProperty(default="UNKNOWN")
    align_detail: StringProperty(default="")

    # measured results (written by the physics engine: C2 polarization / C4 interference / C8 budget)
    meas_power: FloatProperty(default=-1.0)        # power reaching a detector (-1 = N/A)
    meas_pol: StringProperty(default="")           # e.g. "linear 45deg, DOP 1.00"
    meas_visibility: FloatProperty(default=-1.0)   # fringe visibility (-1 = N/A)
    meas_text: StringProperty(default="")          # freeform extra (spot size, budget, ...)


def _grid_units_update(self, context):
    """Preset the breadboard pitch from the chosen standard (CUSTOM leaves it untouched)."""
    if self.bench_grid_units == 'METRIC':
        self.bench_grid_mm = 25.0
    elif self.bench_grid_units == 'IMPERIAL':
        self.bench_grid_mm = 25.4


class OpticalSceneProps(PropertyGroup):
    live_enabled: BoolProperty(name="Live simulation", default=False, update=_live_update)
    # Bench breadboard grid (mechanically-correct hole array; metric default, both standards)
    bench_grid_units: EnumProperty(
        name="Grid standard",
        items=[('METRIC',   "Metric (25 mm / M6)",     "25 mm hole pitch, M6 tapped holes"),
               ('IMPERIAL', "Imperial (1\" / 1/4-20)", "25.4 mm (1 in) hole pitch, 1/4-20 holes"),
               ('CUSTOM',   "Custom",                  "Use the pitch field verbatim")],
        default='METRIC', update=_grid_units_update)
    bench_grid_mm: FloatProperty(
        name="Grid pitch (mm)", default=25.0, min=1.0,
        description="Breadboard hole pitch in mm (metric 25, imperial 25.4). Posts clamp to the "
                    "board under each optic; the grid is exposed to MCP/agents via get_state")
    beam_height_mm: FloatProperty(
        name="Beam height (mm)", default=100.0, min=5.0,
        description="Optical-axis height above the breadboard top — the bench's single layout "
                    "datum. Dressing sizes posts so every optic at this height gets the same post "
                    "length; exposed in get_state()['bench']. Common values: 75/100/125 mm "
                    "(metric) or 76.2/101.6/127 mm (3/4/5 in)")
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
    bg_preset: EnumProperty(
        name="Background",
        items=[('DARK',        "Dark",          "Dim dark backdrop (default)"),
               ('BLACK',       "Black",         "Pure black backdrop"),
               ('WHITE',       "White / Paper", "White backdrop for light figures"),
               ('TRANSPARENT', "Transparent",   "Alpha (PNG) background for compositing onto paper/figures")],
        default='DARK', update=_bg_update)
    realistic_optics: BoolProperty(
        name="Realistic optics (render)",
        description=("On render, give beam splitters/lenses/waveplates glass materials and mirrors "
                     "reflective coatings, and add studio lighting + a ground, so the optics read "
                     "as real glass. The viewport keeps its flat editing colours; use Reset Render "
                     "Style to restore them"),
        default=True)
    monitor_show: BoolProperty(name="Sensor window", default=False, update=_monitor_update)
    monitor_size: IntProperty(name="Sensor window size (px)", default=256, min=96, max=720)
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
