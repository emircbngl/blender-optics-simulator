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
    ('CIRCULATOR',   "Optical Circulator",         "Non-reciprocal N-port cyclic router: Pi -> P(i+1), with a small isolation leak to P(i-1)"),
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
    ('PRISM',        "Dispersing Prism",           "Refractive material-dispersion prism (equilateral / Littrow / Pellin-Broca / Amici); fans a white beam by wavelength"),
    ('SLIT',         "Slit",                       "1-D (anisotropic) aperture: a pair of blades clipping the Gaussian along ONE transverse axis (T = erf(sqrt2 b/w))"),
    ('BEAM_DUMP',    "Beam Dump",                  "Terminal full-absorber (conical light trap); the ray ends here (power -> residual ~1e-3) -- safely dumps a rejected beam"),
    ('KNIFE_EDGE',   "Knife Edge",                 "Half-plane blade on a stage; transmits the beam past the edge (P = 0.5[1-erf(sqrt2(e-xc)/w)]); sweep -> erf profile -> beam radius"),
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
    # Property-group numeric fields do not have a dynamic range, so enforce each preset's
    # published/mechanical limit here instead of allowing an API caller to drive past a stop.
    clamped = min(max(self.current, self.min_val), self.max_val)
    if clamped != self.current:
        self.current = clamped
        return
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


def _iris_regen_update(self, context):
    """The clear aperture changed on an iris/aperture element -> regenerate its multi-leaf BLADE MESH so the
    polygonal opening closes/opens to the new radius, live in the viewport and animatable. The optics are
    untouched: the element's ports + clear_aperture (the values the tracer reads) are NOT changed here -- only
    the visible mesh is rebuilt. So a radius change is byte-identical to a fresh build at that radius, and the
    18 example scenes stay byte-identical (their iris radii never change at build time -> the mesh just rebuilds
    to the same opening). elements_generic.regenerate_iris() is itself re-entrancy- and restricted-context-safe
    (no-ops for non-iris elements, during its own temp build, or when no view_layer is available), so this is
    safe to fire from any context including animation playback and example builds."""
    try:
        from . import elements_generic
        obj = self.id_data                           # the Object owning this clear_aperture (not necessarily active)
        if obj is not None and getattr(obj, "optics", None) and obj.optics.is_optical \
                and obj.optics.element_type == 'APERTURE':
            elements_generic.regenerate_iris(obj)
    except Exception:
        pass


# --- property groups --------------------------------------------------------

class OpticalPort(PropertyGroup):
    name: StringProperty(name="Name", default="IN")
    role: EnumProperty(name="Role", items=PORT_ROLES, default='IN')
    local_position: FloatVectorProperty(
        name="Local Position (mm)", size=3, subtype='XYZ',
        description="Position relative to the element origin in millimeters (default 0, 0, 0)")
    local_normal: FloatVectorProperty(name="Local Normal", size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0))
    clear_aperture: FloatProperty(name="Clear Aperture", default=12.7, min=0.0)


class AdjustmentDOF(PropertyGroup):
    name: StringProperty(name="Name", default="DOF")
    kind: EnumProperty(name="Kind", items=DOF_KINDS, default='TIP')
    axis_local: FloatVectorProperty(name="Axis (local)", size=3, subtype='DIRECTION', default=(1.0, 0.0, 0.0))
    pivot_local: FloatVectorProperty(name="Pivot (local)", size=3, subtype='XYZ', default=(0.0, 0.0, 0.0))
    min_val: FloatProperty(name="Min", default=-4.0)
    max_val: FloatProperty(name="Max", default=4.0)
    current: FloatProperty(
        name="Current", default=0.0, update=_dof_update,
        description="Current adjustment in degrees for rotation or millimeters for translation (default 0)")


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
    element_type: EnumProperty(
        name="Element Type", items=ELEMENT_TYPES, default='NONE',
        description="Optical behavior assigned to the selected object (default None)")

    ports: CollectionProperty(type=OpticalPort)
    ports_index: IntProperty(default=0)

    mount_type: EnumProperty(
        name="Mount Type", items=MOUNT_TYPES, default='FIXED',
        description="Kinematic mount model used by the element (default Fixed)")
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
    rail_family: StringProperty(name="Rail family", default="RLA")
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
    focal_length: FloatProperty(
        name="Focal Length (mm)", default=0.0,
        description="Focal length of the element in millimeters (default 0)")
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
    split_ratio: FloatProperty(
        name="Split Ratio", default=0.5, min=0.0, max=1.0,
        description="Fraction of incident power sent to the reflected path (default 0.5)")
    prism_angle: FloatProperty(name="Prism angle (deg)", default=45.0)
    # The clear aperture (the radius the tracer clips the beam to). On an iris/APERTURE element this is also the
    # LIVE opening: the update callback regenerates the multi-leaf blade mesh so the polygonal opening closes/
    # opens to the new radius (animatable). For every other element type the callback is an immediate no-op, so
    # only the mesh of an iris ever moves -- the optics (ports + this value) are read identically by the tracer.
    clear_aperture: FloatProperty(
        name="Clear Aperture (mm)", default=12.7, min=0.0, update=_iris_regen_update,
        description="Clear aperture radius used for beam clipping in millimeters (default 12.7)")
    reflectivity: FloatProperty(
        name="Reflectivity", default=1.0, min=0.0, max=1.0,
        description="Fraction of incident optical power reflected by the element (default 1.0)")
    # mirror CURVATURE (variant): a curved mirror focuses on reflection with f = R/2 (VERIFIED:
    # spherical-mirror-focal-length, physics_verify 4/4). FLAT = no focal power (the historic behavior).
    mirror_curve: EnumProperty(name="Mirror curvature", default='FLAT',
        items=[('FLAT', "Flat", "Planar fold mirror (no focal power)"),
               ('CONCAVE', "Concave", "Converging: f = +R/2"),
               ('CONVEX', "Convex", "Diverging: f = -R/2")])
    radius_curv: FloatProperty(name="Radius of curvature (mm)", default=0.0, min=0.0)  # |R|; f=R/2
    wavelength: FloatProperty(
        name="Wavelength (nm)", default=632.8, min=1.0,
        description="Vacuum wavelength of the source in nanometers (default 632.8)")
    refractive_index: FloatProperty(name="Refractive index", default=1.5168)
    # A9 ghost back-reflection: an AR-coated transmissive surface reflects ~0.25-0.5% instead of the
    # ~4% of an uncoated air<->glass face. The ghost reflectance is taken from refractive_index when
    # uncoated, or ar_reflectance when ar_coated. Only consulted when scene.optics.model_ghosts is ON.
    ar_coated: BoolProperty(
        name="AR coated", default=False,
        description="Anti-reflection coated surface: the parasitic Fresnel ghost (A9) uses "
                    "ar_reflectance (~0.25%) instead of the uncoated ((n-1)/(n+1))^2 (~4%). "
                    "Only consulted when 'Model ghost reflections' is on")
    ar_reflectance: FloatProperty(
        name="AR reflectance (R)", default=0.0025, min=0.0, max=1.0,
        description="Residual per-surface power reflectance of an AR coating (~0.0025 for a "
                    "broadband AR-V, ~0.001 for a V-coat at the design line). The ghost power "
                    "fraction when ar_coated is on")
    # --- A11 UNIVERSAL coating: a paintable HR/partial reflective coating + neutral absorber on ANY
    # element (generalizes the A9 ghost from a fixed ~4% Fresnel to a controllable, user-set pickoff,
    # and the ATTENUATOR/colored-glass loss to a universal transmittance). Both are DEFAULT-NEUTRAL
    # (R=0, T=1) so an element that doesn't set them traces BYTE-IDENTICAL. The tracer applies them only
    # on the TRANSMISSIVE/generic interaction (LENS/PASSTHROUGH/window + FILTER/ATTENUATOR), NOT on
    # inherently splitting/reflecting types (MIRROR/BS/DICHROIC/GRATING already conserve energy via their
    # own split) -- so the coating is never double-counted. Energy: R(pickoff) + T_onward + A = incident.
    coating_reflectance: FloatProperty(
        name="Coating reflectance (R)", default=0.0, min=0.0, max=1.0,
        description="Universal reflective coating on ANY element's ENTRY face: the fraction R of "
                    "incident power peeled off as a controlled REFLECT pickoff child "
                    "(direction = reflect(ray.dir, entry_normal)); the onward beam is debited to "
                    "(1-R). Turns a plain window into an R%% beam pickoff, or paints an HR/partial "
                    "coating on any transmissive face. 0 (default) -> no pickoff, byte-identical. "
                    "Composes ADDITIVELY with the A9 ghost (total reflected = ghost R + this R) and "
                    "is SKIPPED on mirrors/beamsplitters (they already reflect/split)")
    element_transmittance: FloatProperty(
        name="Element transmittance (T)", default=1.0, min=0.0, max=1.0,
        description="Universal neutral absorber on ANY element: the onward (transmitted) power is "
                    "multiplied by T, so the element absorbs (1-T) of what passes through. "
                    "Generalizes the ATTENUATOR / colored-glass loss to every transmissive element. "
                    "1.0 (default) -> no absorption, byte-identical")
    # --- SURFACE-FIGURE -> WAVEFRONT IMPRINT: when a REFLECTIVE element has this ON, the reflected beam
    # carries the Zernike wavefront error imprinted by the element's ACTUAL MESH surface over the beam
    # footprint (Tier-1 GEOMETRIC OPD = 2*surface-depth deviation, fit to orthonormal Noll Zernikes, in
    # waves), so a downstream wavefront sensor reads the surface figure. DEFAULT OFF -> no imprint -> every
    # scene byte-identical; a FLAT surface imprints ~0. NOT a wave-diffraction calculation.
    imprint_surface: BoolProperty(
        name="Imprint surface figure", default=False,
        description="On a REFLECTIVE element, stamp the wavefront error of this element's ACTUAL MESH "
                    "surface onto the reflected beam (Tier-1 geometric surface-figure -> Zernike OPD, "
                    "waves), so a downstream wavefront sensor reads the surface figure. "
                    "OFF (default) -> no imprint, byte-identical; a flat surface imprints ~0")
    # ZONAL "sensor render" sampling level: the px grid resolution across the footprint diameter used by
    # the on-demand DENSE wavefront map (optics.wfs_zonal_render). Higher px -> finer Nyquist (= px/(2*2w)
    # lp/mm), so high-spatial-frequency figure the 15-mode modal map cannot carry is resolved. Diagnostic
    # only -> never touches the trace -> byte-identical.
    imprint_zonal_px: IntProperty(
        name="Zonal sampling (px)", default=160, min=16, max=512,
        description="Dense sampling level for the zonal wavefront 'sensor render' (grid across the beam "
                    "footprint). Higher -> finer detail (Nyquist = px / (2*footprint)). On-demand only")

    # --- physics-layer parameters (read by the polarization / wavelength engine) ---
    pol_type: EnumProperty(name="Source polarization",
        items=[('LINEAR', "Linear", ""), ('CIRCULAR', "Circular", ""), ('UNPOL', "Unpolarized", "")],
        default='LINEAR')
    pol_angle: FloatProperty(
        name="Polarization Angle (deg)", default=0.0,
        description="Linear polarization angle around the propagation axis in degrees (default 0)")
    handedness: EnumProperty(name="Handedness",
        items=[('RIGHT', "Right", ""), ('LEFT', "Left", "")], default='RIGHT')
    linewidth_nm: FloatProperty(name="Linewidth (nm)", default=0.0, min=0.0)   # 0 -> ideal coherence
    bandwidth_nm: FloatProperty(name="Bandwidth (nm)", default=0.0, min=0.0)   # >0 -> broadband / white-light
    waist_um: FloatProperty(
        name="Beam Waist (µm)", default=500.0, min=0.0,
        description="Gaussian beam waist radius in micrometers (default 500)")
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
    # D3 cosmetic-only groove PROFILE: shapes the ruled surface mesh so a ruled / holographic / echelle
    # grating is recognizable at a glance. The trace reads lines_per_mm (the single source of truth for the
    # grating equation), NOT the mesh -- so every profile is byte-identical (ports unchanged). Mesh-only.
    grating_profile: EnumProperty(name="Groove profile", default='RULED',
        items=[('RULED', "Ruled (blazed sawtooth)", "Asymmetric sawtooth ridges -- the blaze profile"),
               ('HOLOGRAPHIC', "Holographic (sinusoidal)", "Rounded sinusoidal corrugation"),
               ('ECHELLE', "Echelle (coarse steps)", "A few coarse, steeply-tilted steps (staircase)")],
        description="Cosmetic ruling shape only -- line density (lines/mm) drives the trace, not the mesh")
    analyzer: EnumProperty(name="Analyzer",
        items=[('NONE', "None", ""), ('H', "H linear", ""), ('V', "V linear", ""),
               ('D', "Diagonal", ""), ('A', "Anti-diagonal", ""),
               ('RCP', "Right circular", ""), ('LCP', "Left circular", "")],
        default='NONE')
    coating: EnumProperty(name="Mirror coating",
        items=[('DIELECTRIC', "Dielectric (ideal)", ""), ('AL', "Aluminum", ""),
               ('AG', "Silver", ""), ('AU', "Gold", "")], default='DIELECTRIC')
    design_wl: FloatProperty(name="Design wavelength (nm)", default=633.0, min=1.0)  # spec point; 0 would null a waveplate
    # The lens substrate glass — drives its chromatic focal shift f ~ 1/(n(lambda)-1). Default N-BK7
    # matches the prior hardcoded behaviour, so existing scenes trace byte-identical; pick the real
    # glass (e.g. FUSED_SILICA, N-SF11) to get that material's true longitudinal colour.
    lens_glass: EnumProperty(name="Lens glass", default='N-BK7',
        items=[('N-BK7', "N-BK7 (borosilicate crown)", "Vd=64.2; the default workhorse"),
               ('FUSED_SILICA', "Fused silica", "UV-grade, very low dispersion"),
               ('N-SF11', "N-SF11 (dense flint)", "Vd=25.7; high dispersion"),
               ('F2', "F2 (flint)", "Vd=36.4"),
               ('N-F2', "N-F2 (lead-free flint)", "Vd=36.4"),
               ('CaF2', "CaF2 (calcium fluoride)", "Vd=95.0; UV-transmitting low dispersion")])
    # Element temperature for the thermo-optic shift n_eff = n(lambda) + dn/dT*(T-20C). Default 20C is a
    # no-op (dn/dT*0), so existing scenes are byte-identical; raise it to see the focal/index drift.
    temp_C: FloatProperty(name="Temperature (C)", default=20.0, min=-100.0, max=300.0,
        description="Optic temperature; shifts the index via dn/dT (thermo-optic). 20 C = nominal, no shift")
    # Waveplate substrate crystal. NONE = the simple retardance~1/lambda model (byte-identical). Picking a
    # real birefringent crystal multiplies in its true birefringence dispersion d(n_e-n_o)(lambda).
    waveplate_crystal: EnumProperty(name="Waveplate crystal", default='NONE',
        items=[('NONE', "Ideal (1/lambda scaling)", "Retardance ~ design_wl/lambda only; no Delta-n dispersion"),
               ('QUARTZ', "Crystalline quartz", "alpha-SiO2, the standard waveplate material"),
               ('MGF2', "MgF2", "low-order / broadband waveplates"),
               ('CALCITE', "Calcite", "strong birefringence"),
               ('SAPPHIRE', "Sapphire", "Al2O3")])
    # Surface substrate glass for the Fresnel ghost reflectance. NONE = the fixed refractive_index scalar
    # (byte-identical); a glass makes the per-face reflection R wavelength-dependent via sellmeier_n(ray.wl).
    surface_glass: EnumProperty(name="Surface glass", default='NONE',
        items=[('NONE', "Fixed index", "Use the refractive_index scalar (non-dispersive)"),
               ('N-BK7', "N-BK7", ""), ('FUSED_SILICA', "Fused silica", ""), ('N-SF11', "N-SF11", ""),
               ('F2', "F2", ""), ('CaF2', "CaF2", ""), ('N-SF6', "N-SF6", "")])
    # Metal mirror reflectance: OFF = the single ~633nm n,k (byte-identical); ON = wavelength-dependent
    # n,k(lambda) from the Johnson&Christy / Rakic tables (gold's blue->red rise, silver's IR climb).
    dispersive_metal: BoolProperty(name="Dispersive metal", default=False,
        description="Use wavelength-dependent metal n,k(lambda) for the mirror reflectance (J&C / Rakic)")
    # THERMAL LENS (opt-in): an absorbing optic heats up and acts as an induced lens on the beam. OFF or
    # 0 W absorbed -> no effect -> byte-identical. f_th = 2*pi*kappa*w^2/(P_abs*dn/dT) (Tier-1 lumped).
    thermal_lensing: BoolProperty(name="Thermal lensing", default=False,
        description="Model the induced thermal lens of an absorbing optic on the beam (f_th from absorbed power)")
    absorbed_power_W: FloatProperty(name="Absorbed power (W)", default=0.0, min=0.0,
        description="Optical power absorbed by the optic (the heat load that drives the thermal lens)")
    thermal_conductivity: FloatProperty(name="Thermal conductivity (W/mK)", default=1.38, min=0.01,
        description="Substrate thermal conductivity kappa for the thermal-lens estimate (glass ~1.38)")
    cavity_spacing_mm: FloatProperty(name="Cavity spacing (mm)", default=0.05, min=1e-4)
    # C6 fiber-circulator port isolation: the directivity figure in dB. A ray entering port Pi exits the
    # NEXT port P(i+1) at the through transmittance; a SMALL leak goes to the PREVIOUS port P(i-1) at power
    # T * 10^(-isolation_db/10) (physics.db_to_linear). 20 dB -> 1% leak, 30 dB -> 0.1%, 0 dB -> full leak.
    # The device is NON-RECIPROCAL: P1->P2, P2->P3, P3->P1 (a ray into P2 does NOT return to P1).
    isolation_db: FloatProperty(
        name="Isolation (dB)", default=20.0, min=0.0, soft_max=60.0,
        description="Circulator port-to-port isolation (directivity) in dB. The leakage to the PREVIOUS "
                    "port in the cycle is the through power x 10^(-isolation_db/10): 20 dB -> 1%%, 30 dB "
                    "-> 0.1%%, 0 dB -> full leak. Higher = cleaner routing")
    # nonlinear-crystal chi(2) family (C7). Every child wavelength is exact photon-frequency / ENERGY
    # conservation, each oracle-VERIFIED (tests/_verify_nlcrystal.py): SHG lam/2, THG lam/3, SFG/DFG
    # 1/l3=1/l1+-1/l2, OPO pump->signal+idler. SPDC: degenerate signal+idler at 2*lam. NONE: pump dump
    # (the LEGACY behavior the Bell example relies on -- must stay byte-identical, so it is the default).
    nl_process: EnumProperty(name="chi(2) process", default='NONE',
        items=[('NONE', "None (dump)", "Absorb the pump (no conversion)"),
               ('SHG', "SHG (frequency doubling)", "Emit the second harmonic at lambda/2"),
               ('THG', "THG (frequency tripling)", "Emit the third harmonic at lambda/3"),
               ('SFG', "SFG (sum-frequency)", "1/l3 = 1/l1 + 1/l2 (upconversion)"),
               ('DFG', "DFG (difference-frequency)", "1/l3 = 1/l1 - 1/l2 (mid-IR generation)"),
               ('OPO', "OPO (parametric oscillation)", "Pump splits: 1/lp = 1/ls + 1/li"),
               ('SPDC', "SPDC (down-conversion)", "Emit degenerate signal + idler at 2*lambda")])
    nl_efficiency: FloatProperty(name="Conversion efficiency", default=0.4, min=0.0, max=1.0)
    # second input wavelength (nm) for the two-input processes (SFG/DFG) and the seeded OPO signal.
    nl_lambda2_nm: FloatProperty(name="2nd input / signal (nm)", default=532.0, min=1.0)
    # phase-matching realism (C7). The TYPE sets the child polarization (Jones); the SCHEME sets the
    # walk-off (CRITICAL: a transverse offset; NCPM/QPM: ~zero). CRITICAL/NCPM are birefringent;
    # QPM uses a poled grating (PPLN). Material + temperature tune the sinc^2(dk*L/2) phase match.
    phase_matching_type: EnumProperty(name="Phase-matching type", default='TYPE1',
        items=[('TYPE0', "Type-0 (e->ee / o->oo)", "All same polarization (typical PPLN/QPM)"),
               ('TYPE1', "Type-I (o+o->e)", "Both inputs same pol; harmonic orthogonal"),
               ('TYPE2', "Type-II (o+e->e)", "Inputs orthogonal; signal/idler split in pol (entanglement)")])
    pm_scheme: EnumProperty(name="PM scheme", default='CRITICAL',
        items=[('CRITICAL', "Critical (angle-tuned)", "Birefringent at an angle -> spatial WALK-OFF"),
               ('NCPM', "Non-critical (90 deg, T-tuned)", "Propagate along an axis -> ~zero walk-off"),
               ('QPM', "Quasi-phase-matched (poled)", "Periodic poling (PPLN) -> ~zero walk-off")])
    crystal_material: EnumProperty(name="Crystal material", default='BBO',
        items=[('BBO', "BBO (beta-barium borate)", "Broadband UV-Vis chi(2); SHG/SPDC"),
               ('KTP', "KTP", "High-deff green doubler (1064->532)"),
               ('LBO', "LBO", "Low walk-off; NCPM 1064->532 near 148 C"),
               ('PPLN', "PPLN (periodically poled LiNbO3)", "QPM, large deff; OPO/DFG"),
               ('KDP', "KDP", "Classic UV / high-power; lower deff")])
    crystal_temp_C: FloatProperty(name="Crystal temperature (C)", default=25.0)   # oven set-point
    poling_period_um: FloatProperty(name="Poling period (um)", default=6.5, min=0.0)  # QPM grating (PPLN)
    # D3 cosmetic-only: render the PPLN poling-domain stripes as literal alternating slabs (hero) vs a flat
    # tinted band (performance). Mesh-only -- the QPM trace reads poling_period_um, not the stripe mesh.
    ppln_show_stripes: BoolProperty(name="Show poling stripes", default=True,
        description="Grow literal alternating poling-domain slabs on the PPLN slab (cosmetic; trace unchanged)")
    crystal_length_mm: FloatProperty(name="Interaction length (mm)", default=10.0, min=0.01)  # L for sinc^2(dk L/2)
    nl_walkoff_mm: FloatProperty(name="Walk-off offset (mm)", default=0.6, min=0.0)  # CRITICAL transverse offset
    # --- chi(2) TENSOR SOLVER (opt-in; default OFF -> the legacy nl_efficiency*sinc^2 path stays byte-identical).
    #     ON: the conversion efficiency comes from the full Manley-Rowe coupled-wave ODE (pump depletion +
    #     phase mismatch, physics.chi2_solve) driven by deff/length/pump-power, and the CRITICAL walk-off is
    #     DERIVED from the index ellipsoid (replace-when-on) instead of the literal nl_walkoff_mm.
    use_chi2_solver: BoolProperty(name="chi(2) tensor solver", default=False,
        description="Derive conversion efficiency from the Manley-Rowe coupled-wave ODE (depletion + mismatch)")
    nl_pump_power_W: FloatProperty(name="Pump power (W)", default=1.0, min=0.0,
        description="Peak pump power driving the chi(2) solver's depletion (higher -> more conversion)")
    # --- TRUE o/e SPATIAL double refraction (opt-in; default OFF -> byte-identical). When ON, a CRYSTAL or
    #     WAVEPLATE forks the ray into an ordinary + extraordinary beam (the calcite double image / Wollaston-
    #     class split), the e-beam displaced by L*tan(rho) -- see tracer o/e branch + physics.oe_split_geometry.
    oe_split: BoolProperty(name="o/e double refraction", default=False,
        description="Split the ray into ordinary + extraordinary beams (true birefringent double refraction)")
    oe_material: EnumProperty(name="Birefringent material", default='CALCITE',
        items=[('CALCITE', "Calcite (CaCO3)", "Strong negative uniaxial; the classic double-refractor"),
               ('QUARTZ', "Quartz (alpha-SiO2)", "Weak positive uniaxial"),
               ('MGF2', "MgF2", "Weak positive uniaxial; UV-IR"),
               ('SAPPHIRE', "Sapphire (Al2O3)", "Negative uniaxial; UV-IR")])
    oe_axis_deg: FloatProperty(name="Optic-axis cut (deg)", default=45.0, min=0.0, max=90.0,
        description="Angle of the optic axis from the beam (0=along beam, no split; 45=max walk-off)")
    oe_length_mm: FloatProperty(name="Crystal thickness (mm)", default=10.0, min=0.01,
        description="Slab thickness L; the e-beam is displaced by L*tan(walk-off)")
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
    # dispersing prism (C3): refractive material-dispersion family. The tracer refracts the chief ray at the
    # entry face (n(lambda) via sellmeier_n), propagates the glass OPL (n*L), and refracts/TIRs/reflects at the
    # exit face per prism_type. apex_angle_deg = the refracting (apex) angle; equilateral A=60 deg.
    prism_type: EnumProperty(name="Prism type", default='EQUILATERAL',
        items=[('EQUILATERAL', "Equilateral (dispersing)", "Two-surface Snell; spectrum fans, min deviation at A=60 deg"),
               ('LITTROW', "Littrow (autocollimating)", "Refract -> coated back-reflect -> refract; ~2x dispersion, retro"),
               ('PELLIN_BROCA', "Pellin-Broca (constant 90 deg)", "Refract -> internal TIR -> refract; selected lambda always exits at 90 deg"),
               ('AMICI', "Amici (direct-vision)", "Cemented crown/flint; zero net deviation at lambda0, still disperses"),
               # --- C4 beam-ROUTING prisms: fixed products of plane reflections (no dispersion by design;
               # used near a design wavelength). Each fold is geometry.reflect() off an internal mirror face;
               # parity (image handedness) flips once per reflection (odd -> flip, even -> preserve). ---
               ('RIGHT_ANGLE', "Right-angle (90 deg fold)", "1 internal reflection: 90 deg deflection, image handedness FLIPS"),
               ('PENTA', "Penta (constant 90 deg)", "2 reflections: 90 deg deflection INVARIANT under whole-prism tilt, parity PRESERVED"),
               ('DOVE', "Dove (image rotator)", "1 internal reflection, in-line (0 deg deviation); image ROTATES at 2x the prism roll"),
               ('ROOF', "Amici roof (retro + flip)", "2 reflections off a 90 deg roof: retro-ish, parity flip"),
               ('RHOMBOID', "Rhomboid (lateral offset)", "2 parallel reflections: pure LATERAL OFFSET, output exactly PARALLEL to input")])
    apex_angle_deg: FloatProperty(name="Apex angle (deg)", default=60.0, min=1.0, max=170.0,
        description="The prism's refracting (apex) angle; 60 deg for an equilateral dispersing prism")
    prism_glass: EnumProperty(name="Prism glass", default='N-SF11',
        items=[('N-SF11', "N-SF11 (dense flint, high dispersion)", "Vd=25.7; the classic dispersing-prism glass"),
               ('F2', "F2 (flint)", "Vd=36.4"),
               ('N-F2', "N-F2 (lead-free flint)", "Vd=36.4"),
               ('N-BK7', "N-BK7 (borosilicate crown)", "Vd=64.2; low dispersion"),
               ('CaF2', "CaF2 (calcium fluoride)", "Vd=95.0; very low dispersion, UV-transmitting"),
               ('FUSED_SILICA', "Fused silica", "UV-grade low-dispersion")])
    # Amici (direct-vision) flint glass: the second, higher-dispersion element that cancels the crown's
    # net deviation at the design wavelength while the dispersion adds. Only read for prism_type=AMICI.
    prism_glass2: EnumProperty(name="Amici flint glass", default='N-SF11',
        items=[('N-SF11', "N-SF11 (dense flint)", ""), ('F2', "F2 (flint)", ""), ('N-F2', "N-F2 (lead-free flint)", "")])
    prism_design_wl: FloatProperty(name="Prism design wavelength (nm)", default=589.3, min=1.0,
        description="The selected wavelength: Pellin-Broca deviates it by exactly 90 deg; Amici passes it undeviated")
    # routing-prism roll (C4): rolls the prism about its optical (long) axis. For a DOVE prism this is the
    # headline image-rotation drive -- the through image rotates by 2x this roll (theta_img = 2*theta_roll,
    # a pure reduction of the in-plane reflection law). Inert for the other routing/dispersing types.
    prism_roll_deg: FloatProperty(name="Prism roll (deg)", default=0.0,
        description="Roll the prism about its optical axis. For a Dove prism the through-image rotates by 2x this")
    # routing-prism image parity (C4, computed by the tracer): "EVEN" = handedness preserved (even # of
    # internal reflections: penta, rhomboid), "ODD" = flipped (odd #: right-angle, Dove, roof). Output only.
    prism_parity: StringProperty(name="Image parity", default="")
    # --- C5 beam-conditioning apertures: SLIT (1-D erf clip) / BEAM_DUMP (terminal) / KNIFE_EDGE (half-plane) ---
    # All animatable. The tracer scales power by the verified 1-D erf clips (slit_transmission / knife_transmission,
    # physics_verify ok=true 8/8) using the ray's incident Gaussian radius on the CLIPPED axis. BEAM_DUMP carries
    # only a residual leak. slit_angle rolls the slit's clipped axis about the optical axis (0 = clip along local X).
    slit_width: FloatProperty(name="Slit width (mm)", default=2.0, min=0.0,
        description="FULL slit opening (blade gap); the half-width b = slit_width/2. T = erf(sqrt2 * b / w_x) "
                    "clips the Gaussian along the slit axis. 0 -> closed (blocks), large -> fully open")
    slit_angle: FloatProperty(name="Slit angle (deg)", default=0.0,
        description="Roll of the slit's clipped axis about the optical axis (0 = blades clip along local X, "
                    "so the slit is vertical; 90 = clip along local Y)")
    knife_position: FloatProperty(name="Knife position (mm)", default=0.0,
        description="Transverse position of the knife edge on its stage (the clipped axis). Sweeping this "
                    "across the beam traces the erf knife-edge profile P(e) = 0.5[1 - erf(sqrt2 (e - xc)/w)]")
    knife_angle: FloatProperty(name="Knife angle (deg)", default=0.0,
        description="Roll of the knife's cut axis about the optical axis (0 = the blade cuts along local X)")
    beam_dump_residual: FloatProperty(name="Beam-dump residual", default=1.0e-3, min=0.0, max=1.0,
        description="Tiny fraction of power leaking through a conical beam trap (~1e-3); the ray still TERMINATES")
    # D2 cosmetic only: number of overlapping diaphragm leaves on a realistic iris (10-12). Affects ONLY the
    # mesh (the polygonal opening's leaf count); the opening size + ports + clear_aperture are unchanged, so
    # the tracer never reads this -- it is purely a render/look parameter.
    iris_blades: IntProperty(name="Iris leaves", default=12, min=10, max=12,
        description="Number of overlapping wedge leaves forming the iris polygonal opening (cosmetic only; "
                    "the opening size is set by clear_aperture, not this)")
    is_monitor: BoolProperty(default=False)        # live sensor-monitor target (fringe recomputed live)
    sensor_px: IntProperty(name="Sensor resolution (px)", default=256, min=16, max=1024)
    pixel_size_um: FloatProperty(name="Pixel size (um)", default=5.0, min=0.1)
    sensor_exposure: FloatProperty(name="Exposure (0 = ideal)", default=0.0, min=0.0)
    sensor_read_noise: FloatProperty(name="Read noise (counts)", default=5.0, min=0.0)
    sensor_well_depth: FloatProperty(name="Saturation (counts)", default=4000.0, min=1.0)
    # --- detector material / mode / readout topology (C8) ---------------------------------------
    # READOUT overlays on the existing per-segment power/jones/qd -- they never change the beam TRACE.
    # Defaults reproduce today's behavior exactly: Si + biased + gain 1 -> photocurrent overlay only;
    # POINT topology -> the legacy scalar power readout (meas_power) is untouched.
    det_material: EnumProperty(name="Detector material", default='Si',
        items=[('Si', "Silicon (Si)", "Visible + near-IR (190-1100 nm); peak QE ~700-900 nm"),
               ('InGaAs', "InGaAs", "NIR/SWIR telecom (800-1700 nm); peak QE ~1550 nm"),
               ('Ge', "Germanium (Ge)", "Broad NIR/SWIR (600-1800 nm); lower peak QE")],
        description="Photodiode material -> responsivity band R(lambda)=qe(material,lambda)*lambda/1239.8 A/W")
    det_mode: EnumProperty(name="Detector mode", default='biased',
        items=[('biased', "Biased / photovoltaic", "Linear: V = G*R(lambda)*P (the legacy power readout)"),
               ('amplified', "Amplified (transimpedance)", "Linear with extra gain: V = G*R(lambda)*P"),
               ('APD', "Avalanche (APD)", "I = M*R(lambda)*P with excess-noise F(M)=kM+(2-1/M)(1-k)"),
               ('SPAD', "Single-photon (SPAD)", "Photon counting; saturates at high flux (Geiger mode)")],
        description="Readout mode: linear (biased/amplified), avalanche (APD), or photon-counting (SPAD)")
    det_gain: FloatProperty(name="Detector gain (G / M)", default=1.0, min=0.0,
        description="Transimpedance gain G (biased/amplified) or avalanche multiplication M (APD)")
    det_k: FloatProperty(name="APD ionization ratio k", default=0.02, min=0.0, max=1.0,
        description="APD ionization-coefficient ratio for the McIntyre excess-noise F(M) (Si~0.02, InGaAs~0.4, Ge~0.9)")
    det_spad_max: FloatProperty(name="SPAD saturation count", default=1.0e6, min=1.0,
        description="SPAD maximum count rate; the photon-counting readout saturates toward this ceiling")
    readout_topology: EnumProperty(name="Readout topology", default='POINT',
        items=[('POINT', "Point (single-element)", "One active area -> a single scalar power/photocurrent (legacy default)"),
               ('QUADRANT', "Quadrant (4-element)", "Four quadrants -> 2-axis position error Sx=(A+D-B-C)/Sigma, Sy=(A+B-C-D)/Sigma"),
               ('PSD', "Lateral PSD", "Continuous position-sensing detector -> power-weighted centroid (x, y)"),
               ('CAMERA', "Camera (imaging)", "2-D pixel array -> intensity image I(x,y)=Sum|E|^2 (reuses the fringe array)"),
               ('POL_CAMERA', "Polarization camera (DoFP)", "Per-pixel micropolarizer array (0/45/90/135 deg) -> single-shot linear Stokes S0/S1/S2 + DoLP/AoLP")],
        description="Detector READOUT topology: point power, quadrant error, PSD centroid, camera image, or DoFP polarization camera")
    quadrant_gap_mm: FloatProperty(name="Quadrant/PSD gap (mm)", default=0.0, min=0.0,
        description="Dead-gap half-width between quadrant segments (0 = ideal, no gap)")
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
    # C8 readout overlays (computed from the SAME power/jones/qd; the trace is untouched)
    meas_current: FloatProperty(default=-1.0)      # photocurrent/voltage V or I = G*R(lambda)*P readout (-1 = N/A)
    meas_quad_x: FloatProperty(default=0.0)        # quadrant/PSD position-error X signal (normalized)
    meas_quad_y: FloatProperty(default=0.0)        # quadrant/PSD position-error Y signal (normalized)


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
    # How IR / UV beams are DRAWN (viewport, bake and SVG alike). Display only -- the trace is
    # untouched, so switching this never changes a power, a Jones vector or a segment count.
    oob_display: EnumProperty(
        name="Invisible beams",
        description=("How to draw light the eye cannot see (IR above 780 nm, UV below 380 nm). "
                     "Affects the viewport, the baked beams and the SVG export identically"),
        items=[('FALSE_COLOR', "False colour",
                "Dim IR/UV ramp: visible and distinguishable (1064 vs 1550 nm differ), but still "
                "reads as invisible light"),
               ('HIDE',        "Hide",
                "Do not draw them at all -- watch only the 532 nm harmonic without the pump crossing it"),
               ('VIVID',       "Vivid",
                "Full-brightness false colour for figures where the invisible beam is the subject "
                "(explicitly non-physical)")],
        default='FALSE_COLOR')
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
    # B5 adaptive-optics control loop (scene-global; the loop runs ON DEMAND, so these never
    # affect a normal trace). The reconstructor + leaky integrator + Kolmogorov ABERRATOR settings:
    ao_recon: EnumProperty(name="Reconstructor", default='TSVD',
        items=[('TSVD', "Truncated SVD", "R = B+ via SVD, drop singular values below the cutoff (fast, ill-cond-tolerant)"),
               ('DAMPED_TRANSPOSE', "Damped transpose", "R = c*B^T (noise-tolerant; slower, never amplifies null modes)")],
        description="Wavefront reconstructor mapping the WFS residual to a DM command increment")
    ao_leak: FloatProperty(name="Integrator leak", default=0.99, min=0.0, max=1.0,
        description="Forgetting factor in the leaky integrator x_{k+1}=leak*x_k - g*R*w_k (1.0 = pure integrator)")
    ao_loop_gain: FloatProperty(name="AO loop gain", default=0.8, min=0.0, max=2.0,
        description="Closed-loop gain g in x_{k+1}=leak*x_k - g*R*w_k (the reconstructor loop; ~0.8)")
    ao_r0: FloatProperty(name="Fried parameter r0 (mm)", default=60.0, min=1.0, soft_max=400.0,
        description="Atmospheric coherence length; the Kolmogorov aberrator's per-mode variance scales as (D/r0)^(5/3)")
    ao_aperture: FloatProperty(name="Pupil diameter D (mm)", default=25.4, min=0.1,
        description="Pupil diameter the Kolmogorov turbulence variance (D/r0)^(5/3) is reckoned over")
    # alignment thresholds
    ok_pos_mm: FloatProperty(name="OK pos (mm)", default=0.5, min=0.0)
    ok_ang_deg: FloatProperty(name="OK ang (deg)", default=0.2, min=0.0)
    warn_pos_mm: FloatProperty(name="Warn pos (mm)", default=2.0, min=0.0)
    warn_ang_deg: FloatProperty(name="Warn ang (deg)", default=1.0, min=0.0)

    # --- A9 back-reflection / ghost-beam modeling (OPT-IN; default OFF) ---
    # When OFF (the default), the tracer spawns NO ghost children and every existing scene
    # traces BYTE-IDENTICAL to before. When ON, each transmissive face (lens/window/filter/
    # beamsplitter) spawns a low-power Fresnel back-reflection (the "ghost"): power R*ray.power
    # with R=((n1-n2)/(n1+n2))^2 (~4% uncoated, tiny AR-coated), and the transmitted power is
    # debited to (1-R)*ray.power so energy is conserved (R+T=1). Ghosts are gated by ghost_floor
    # + max_ghost_depth so they never recurse into ghosts-of-ghosts and blow the segment budget.
    model_ghosts: BoolProperty(
        name="Model ghost reflections",
        description="Spawn the parasitic ~4% Fresnel back-reflection (a GHOST) at each transmissive "
                    "surface, then detect bad ghosts (back_reflection into a source, ghost on a "
                    "detector). OFF by default so existing scenes trace byte-identical; turn ON to "
                    "study stray light / laser-feedback and verify an isolator clears it",
        default=False)
    ghost_floor: FloatProperty(
        name="Ghost power floor", default=1.0e-3, min=0.0, max=1.0,
        description="A ghost weaker than this fraction of the incident power is not spawned "
                    "(protects the segment budget). ~1e-3 keeps the 4% first ghost, drops the "
                    "0.16% ghost-of-ghost")
    max_ghost_depth: IntProperty(
        name="Max ghost depth", default=2, min=0, max=8,
        description="How many times a ghost may itself spawn another ghost. 2 keeps the primary "
                    "back-reflection and its first re-reflection; deeper ghosts are extinguished "
                    "so the trace stays bounded")


class OpticalDiagnosisCacheItem(PropertyGroup):
    issue: StringProperty(options={'SKIP_SAVE'})
    element: StringProperty(options={'SKIP_SAVE'})
    detail: StringProperty(options={'SKIP_SAVE'})
    severity: StringProperty(options={'SKIP_SAVE'})
    suggested_fix: StringProperty(options={'SKIP_SAVE'})
    tool: StringProperty(options={'SKIP_SAVE'})
    maybe_intentional_if: StringProperty(options={'SKIP_SAVE'})
    fault_confidence: FloatProperty(options={'SKIP_SAVE'})


_classes = (OpticalPort, AdjustmentDOF, MechLink, OpticalElementProps, OpticalSceneProps,
            OpticalDiagnosisCacheItem)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Object.optics = PointerProperty(type=OpticalElementProps)
    bpy.types.Scene.optics = PointerProperty(type=OpticalSceneProps)
    bpy.types.WindowManager.optics_diagnosis_cache = CollectionProperty(
        type=OpticalDiagnosisCacheItem, options={'SKIP_SAVE'})
    bpy.types.WindowManager.optics_diagnosis_bad = IntProperty(options={'SKIP_SAVE'})
    bpy.types.WindowManager.optics_diagnosis_warn = IntProperty(options={'SKIP_SAVE'})
    bpy.types.WindowManager.optics_diagnosis_revision = IntProperty(default=-1, options={'SKIP_SAVE'})
    bpy.types.WindowManager.optics_scene_revision = IntProperty(options={'SKIP_SAVE'})


def unregister():
    for name in ("optics_scene_revision", "optics_diagnosis_revision",
                 "optics_diagnosis_warn", "optics_diagnosis_bad", "optics_diagnosis_cache"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    if hasattr(bpy.types.Scene, "optics"):
        del bpy.types.Scene.optics
    if hasattr(bpy.types.Object, "optics"):
        del bpy.types.Object.optics
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
