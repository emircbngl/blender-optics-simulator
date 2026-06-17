"""Canonical example setups, built from generic (mesh-free) components.

Geometric-layout fidelity: the tracer draws the correct beam routing so each
builder produces a faithful setup diagram. Wave interference (fringes) and
quantum behavior (HOM dip, Bell coincidences) are a later phase.

All builders place into their own collection and use only elements_generic, so
they run anywhere with no vendor meshes.
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty
from mathutils import Vector

from . import elements_generic as G


def build_mach_zehnder(context):
    """BS1 -> two mirrors -> BS2 -> two detectors."""
    coll = G.example_collection("OpticsExample_MachZehnder")
    L = 200.0
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    G.source("MZ_Laser", (-150, 0, 0), X, coll)
    G.beamsplitter("MZ_BS1", (0, 0, 0), X, Y, coll)
    G.mirror("MZ_M_top", (0, L, 0), Y, X, coll)         # +Y arm -> +X
    G.mirror("MZ_M_bottom", (L, 0, 0), X, Y, coll)      # +X arm -> +Y
    G.beamsplitter("MZ_BS2", (L, L, 0), X, Y, coll)
    G.detector("MZ_D0", (2 * L, L, 0), X, coll)
    G.detector("MZ_D1", (L, 2 * L, 0), Y, coll)
    return "OpticsExample_MachZehnder"


def build_michelson(context):
    """BS -> fixed mirror + translation-stage mirror -> recombine -> detector."""
    coll = G.example_collection("OpticsExample_Michelson")
    L = 180.0
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    G.source("MI_Laser", (-150, 0, 0), X, coll)
    G.beamsplitter("MI_BS", (0, 0, 0), X, Y, coll)
    G.mirror("MI_M_fixed", (0, L, 0), Y, -Y, coll)      # retro-reflect +Y -> -Y
    m_stage = G.mirror("MI_M_stage", (L, 0, 0), X, -X, coll)   # retro +X -> -X
    G.add_translation_dof(m_stage, (1, 0, 0), -20.0, 20.0, 0.0)   # OPD scan knob
    G.detector("MI_D", (0, -L, 0), -Y, coll)
    return "OpticsExample_Michelson"


def build_hong_ou_mandel(context):
    """Two photons into one 50/50 BS -> two detectors (coincidence point)."""
    coll = G.example_collection("OpticsExample_HOM")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    G.source("HOM_PhotonA", (-150, 0, 0), X, coll)
    G.source("HOM_PhotonB", (0, -150, 0), Y, coll)
    G.beamsplitter("HOM_BS", (0, 0, 0), X, Y, coll)
    G.detector("HOM_D1", (150, 0, 0), X, coll)
    G.detector("HOM_D2", (0, 150, 0), Y, coll)
    return "OpticsExample_HOM"


def build_bell_entanglement(context):
    """Pump -> BBO -> signal/idler arms, each HWP + PBS -> H/V detectors."""
    coll = G.example_collection("OpticsExample_Bell")
    X = Vector((1, 0, 0))
    a = math.radians(18.0)
    dS = Vector((math.cos(a), math.sin(a), 0))
    dI = Vector((math.cos(a), -math.sin(a), 0))
    rS = Vector((-dS.y, dS.x, 0))      # +90 deg (signal V output)
    rI = Vector((dI.y, -dI.x, 0))      # -90 deg (idler V output)

    G.source("Bell_Pump", (-200, 0, 0), X, coll, wavelength=405.0)
    G.crystal("Bell_BBO", (0, 0, 0), X, coll)

    # signal arm
    G.source("Bell_S_src", (0, 0, 0), dS, coll, wavelength=810.0, length=18, radius=4)
    # HWP at 22.5 deg (specced at the arm wavelength) rotates the H-polarized source to 45 deg
    # so the PBS splits ~50/50 into BOTH the H and V detectors. With the default 0-deg fast axis
    # a HWP on H light is a no-op and the V-output detectors stay dark.
    G.waveplate("Bell_S_HWP", 60.0 * dS, dS, coll, kind='HWP', fast_axis=22.5, design_wl=810.0)
    G.beamsplitter("Bell_S_PBS", 120.0 * dS, dS, rS, coll, pbs=True)
    G.detector("Bell_S_H", 210.0 * dS, dS, coll)
    G.detector("Bell_S_V", 120.0 * dS + 80.0 * rS, rS, coll)

    # idler arm
    G.source("Bell_I_src", (0, 0, 0), dI, coll, wavelength=810.0, length=18, radius=4)
    G.waveplate("Bell_I_HWP", 60.0 * dI, dI, coll, kind='HWP', fast_axis=22.5, design_wl=810.0)
    G.beamsplitter("Bell_I_PBS", 120.0 * dI, dI, rI, coll, pbs=True)
    G.detector("Bell_I_H", 210.0 * dI, dI, coll)
    G.detector("Bell_I_V", 120.0 * dI + 80.0 * rI, rI, coll)
    return "OpticsExample_Bell"


def build_adaptive_optics(context):
    """Adaptive optics: source -> aberrator (turbulence) -> deformable mirror -> wavefront
    sensor. Run the AO loop (Adaptive Optics panel / optics.ao_close_loop) to drive the
    residual wavefront RMS to zero and watch the sensor's wavefront map flatten."""
    coll = G.example_collection("OpticsExample_AdaptiveOptics")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    G.source("AO_Laser", (-220, 0, 0), X, coll)
    modes = [0.0] * 15
    modes[3] = 0.4     # defocus (Noll j=4)
    modes[5] = 0.3     # astigmatism (j=6)
    modes[7] = 0.25    # coma (j=8)
    G.aberrator("AO_Turbulence", (-90, 0, 0), X, coll, modes=modes)
    G.deformable_mirror("AO_DM", (0, 0, 0), X, Y, coll)     # fold +X -> +Y
    G.wavefront_sensor("AO_WFS", (0, 160, 0), Y, coll)      # faces the +Y beam
    return "OpticsExample_AdaptiveOptics"


def build_newton_rings(context):
    """Newton's rings: a collimated beam in a Mach-Zehnder with a converging LENS in one arm
    and a flat reference in the other. The lensed arm arrives at the detector as a curved
    (near-spherical) wavefront and the reference as a plane wave, so the two interfere as
    concentric ring fringes -- the live showcase of the Gaussian-wavefront fringe model
    (curvature + apodization). The detector sits *before* the lens focus, where the beam is
    still wide but strongly curved, so many rings fit. A common lens would shift both arms'
    curvature equally; only a lens in a *single* arm makes the ring-producing 1/R difference."""
    coll = G.example_collection("OpticsExample_NewtonRings")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    L = 80.0
    src = G.source("NR_Laser", (-110, 0, 0), X, coll)
    src.optics.waist_um = 1500.0                          # wide + collimated -> flat reference
    G.beamsplitter("NR_BS1", (0, 0, 0), X, Y, coll)
    G.mirror("NR_M_ref", (0, L, 0), Y, X, coll)           # reference arm: +Y -> +X (flat)
    G.mirror("NR_M_lens", (L, 0, 0), X, Y, coll)          # lensed arm: +X -> +Y
    G.lens("NR_Lens", (L, L - 18.0, 0), Y, coll, focal=100.0, radius=16.0)   # near BS2, in arm A
    G.beamsplitter("NR_BS2", (L, L, 0), X, Y, coll)
    det = G.detector("NR_D", (L + 40.0, L, 0), X, coll)   # before the lens focus -> rings
    det.optics.pixel_size_um = 4.0                        # zoom the sensor field onto the beam
    return "OpticsExample_NewtonRings"


def build_periscope(context):
    """A periscope: two 45-deg fold mirrors raise the beam OUT of the table plane to a second deck
    and send it on -- the canonical vertical beam-steering build. The beam goes +Y to the lower
    mirror, straight up (+Z) to the upper mirror, then +Y again at the upper deck to the detector.
    Demonstrates an out-of-plane (vertical) fold: the optics live at two beam heights, not one."""
    coll = G.example_collection("OpticsExample_Periscope")
    Y, Z = Vector((0, 1, 0)), Vector((0, 0, 1))
    deck = 90.0
    G.source("PS_Laser", (0, -120, 0), Y, coll)            # shoots +Y on deck 1 (z = 0)
    G.mirror("PS_M_low", (0, 0, 0), Y, Z, coll)            # +Y -> up (+Z)
    G.mirror("PS_M_high", (0, 0, deck), Z, Y, coll)        # up -> +Y on deck 2 (z = deck)
    G.detector("PS_D", (0, 120, deck), Y, coll)            # catches the raised beam
    return "OpticsExample_Periscope"


def _group(elems, system, gid):
    """Tag a collinear run of optics into one support system (cage/tube/rail). Dress Bench then builds
    the shared hardware (4 rods + plates + one post / one barrel + post / a rail + carriers) instead of
    a post under each -- and never moves the optics, so the trace stays identical."""
    for o in elems:
        o.optics.support_system = system
        if system.startswith('CAGE'):
            o.optics.cage_id = gid
        elif system.startswith('TUBE'):
            o.optics.tube_id = gid
        elif system == 'RAIL':
            o.optics.rail_id = gid


def build_cage_system(context):
    """A complete 30 mm CAGE relay (Thorlabs-style): a fibre launcher, a collimating lens, a clean-up
    polarizer and a polarizing beamsplitter all share four ER cage rods + one post; the PBS transmits
    p-pol straight to a 90 deg turning mirror -> camera, and reflects s-pol out the side to a beam dump.
    Dress Bench to see the cage. Showcases an in-line cage subsystem feeding free-space post mounts."""
    coll = G.example_collection("OpticsExample_CageSystem")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    f = G.fiber_collimator("CG_Fiber", (-105, 0, 0), X, coll)
    l1 = G.lens("CG_Collimate", (-55, 0, 0), X, coll, focal=50.0, radius=12.0)
    pol = G.polarizer("CG_CleanPol", (-15, 0, 0), X, coll)
    pbs = G.beamsplitter("CG_PBS", (25, 0, 0), X, Y, coll, pbs=True)
    _group([f, l1, pol, pbs], 'CAGE_30', 'cage_main')          # the 30 mm cage train
    G.mirror("CG_Turn", (95, 0, 0), X, Y, coll)                # transmitted p-pol: +X -> +Y
    G.detector("CG_Cam", (95, 80, 0), Y, coll)
    G.detector("CG_Dump", (25, 70, 0), Y, coll)                # reflected s-pol side port -> dump
    return "OpticsExample_CageSystem"


def build_tube_system(context):
    """A complete SM1 LENS-TUBE imaging stack: a fibre input and two f = 50 mm relay lenses share one
    Ø1.2" lens-tube barrel (a 4f relay), delivering the image to a C-mount camera at the end. Dress
    Bench to see the tube. Showcases an entire in-line system built inside lens tubes (no open posts)."""
    coll = G.example_collection("OpticsExample_TubeSystem")
    X = Vector((1, 0, 0))
    f = G.fiber_collimator("TB_Fiber", (-75, 0, 0), X, coll)
    l1 = G.lens("TB_L1", (-25, 0, 0), X, coll, focal=50.0, radius=12.0)
    l2 = G.lens("TB_L2", (75, 0, 0), X, coll, focal=50.0, radius=12.0)        # 2f = 100 mm relay gap
    _group([f, l1, l2], 'TUBE_SM1', 'tube_relay')              # one SM1 barrel holds the whole relay
    G.detector("TB_Cam", (125, 0, 0), X, coll)                 # image plane (f after L2)
    return "OpticsExample_TubeSystem"


def build_rail_system(context):
    """A complete RAIL beamline: a Galilean beam-expander (diverging f = -25 mm + converging f = +75 mm,
    separation 50 mm -> 3x), an alignment iris and a fold mirror each ride a carrier on ONE dovetail
    rail, so every optic slides along a common track. Dress Bench to see the rail + carriers."""
    coll = G.example_collection("OpticsExample_RailSystem")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    G.source("RL_Laser", (-130, 0, 0), X, coll)
    l1 = G.lens("RL_L1_div", (-40, 0, 0), X, coll, focal=-25.0, radius=10.0)
    iris = G.aperture("RL_Iris", (-12, 0, 0), X, coll, radius=14.0)
    l2 = G.lens("RL_L2_conv", (10, 0, 0), X, coll, focal=75.0, radius=16.0)   # Galilean: sep = 75-25 = 50
    m = G.mirror("RL_Fold", (70, 0, 0), X, Y, coll)            # send the expanded beam off-rail
    _group([l1, iris, l2, m], 'RAIL', 'rail_main')             # all four on one dovetail rail
    G.detector("RL_Cam", (70, 80, 0), Y, coll)
    return "OpticsExample_RailSystem"


def build_hybrid_system(context):
    """A HYBRID bench combining all three systems: a 30 mm CAGE launcher (fibre + collimator + polarizer)
    hands a beam to a free-space POST-mounted 90 deg turning mirror, which feeds a RAIL-mounted analyzer
    train (focusing lens + analyzer polarizer) into a camera. Dress Bench to see cage + post + rail
    on one breadboard -- the showcase of mixing mounting systems."""
    coll = G.example_collection("OpticsExample_HybridSystem")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    f = G.fiber_collimator("HY_Fiber", (-110, 0, 0), X, coll)
    l1 = G.lens("HY_Collimate", (-65, 0, 0), X, coll, focal=45.0, radius=12.0)
    pol = G.polarizer("HY_Pol", (-30, 0, 0), X, coll)
    _group([f, l1, pol], 'CAGE_30', 'hy_cage')                 # CAGE launcher
    G.mirror("HY_Turn", (20, 0, 0), X, Y, coll)                # free-space POST turning mirror: +X -> +Y
    l2 = G.lens("HY_Focus", (20, 60, 0), Y, coll, focal=75.0, radius=14.0)
    an = G.polarizer("HY_Analyzer", (20, 100, 0), Y, coll)
    _group([l2, an], 'RAIL', 'hy_rail')                        # RAIL analyzer train
    G.detector("HY_Cam", (20, 140, 0), Y, coll)
    return "OpticsExample_HybridSystem"


def build_microscope(context):
    """A transmitted-light, infinity-corrected microscope: a lamp + condenser (Koehler) image the
    illumination onto the sample; the OBJECTIVE collimates the sample to infinity space; a TUBE LENS
    forms the image at the camera. Overall lateral magnification M = f_tube / f_obj (oracle-VERIFIED
    microscope-objective-magnification) -- here f_tube = 200 mm, 10x objective -> f_obj = 20 mm."""
    coll = G.example_collection("OpticsExample_Microscope")
    X = Vector((1, 0, 0))
    G.source("MIC_Lamp", (-260, 0, 0), X, coll, wavelength=550.0)            # Koehler illumination
    G.lens("MIC_Condenser", (-180, 0, 0), X, coll, focal=80.0, radius=14.0)  # images the lamp onto the sample
    G.aperture("MIC_Sample", (-100, 0, 0), X, coll, radius=8.0)              # the specimen (object plane)
    G.objective("MIC_Obj", (-80, 0, 0), X, coll, mag=10.0, na=0.25, wd=10.0, correction='INFINITY')
    G.lens("MIC_Tube", (40, 0, 0), X, coll, focal=200.0, radius=16.0)        # tube lens (200 mm -> M = 10x)
    G.detector("MIC_Cam", (240, 0, 0), X, coll, size=26.0)                   # sensor at the image plane
    return "OpticsExample_Microscope"


EXAMPLES = {
    'mach_zehnder': ("Mach-Zehnder Interferometer", build_mach_zehnder),
    'michelson':    ("Michelson Interferometer", build_michelson),
    'hong_ou_mandel': ("Hong-Ou-Mandel", build_hong_ou_mandel),
    'bell':         ("Bell / Entanglement Source", build_bell_entanglement),
    'adaptive_optics': ("Adaptive Optics (WFS + deformable mirror)", build_adaptive_optics),
    'newton_rings': ("Newton's Rings (lens vs flat)", build_newton_rings),
    'periscope':    ("Periscope (vertical beam raise)", build_periscope),
    'cage_system':  ("Cage System (full 30 mm relay)", build_cage_system),
    'tube_system':  ("Lens-Tube System (4f relay -> camera)", build_tube_system),
    'rail_system':  ("Rail System (beam expander beamline)", build_rail_system),
    'hybrid_system': ("Hybrid (cage + post + rail)", build_hybrid_system),
    'microscope':   ("Microscope (infinity-corrected: objective + tube lens)", build_microscope),
}


def _reset_examples():
    """Remove previously-built example collections + baked beams so each example
    is built in isolation (otherwise multiple setups share the trace)."""
    from . import tracer, bake
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsExample_"):
            for o in list(c.objects):
                G.drop_example_object(o)            # frees the mesh + spares user-adopted objects
            bpy.data.collections.remove(c)
    try:
        bake.clear_baked(bpy.context.scene)
    except Exception:
        pass
    try:                                              # drop any realistic-render studio rig + swap
        from . import render
        render.clear_render_style(bpy.context.scene)
    except Exception:
        pass
    tracer.cached_segments = []


def build(kind, context):
    """Reset prior examples, then build the requested one. Returns collection name."""
    if kind not in EXAMPLES:
        raise ValueError("unknown example: %s" % kind)
    _reset_examples()
    return EXAMPLES[kind][1](context)


def _show(context, coll_name):
    """Trace, enable the live overlay, frame the viewport on the new setup, and
    set a render camera (without forcing the viewport into camera view)."""
    from . import tracer, render
    sc = context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 0.001          # 1 unit = 1 mm (add-on convention)
    sc.unit_settings.length_unit = 'MILLIMETERS'
    sc.optics.line_width = 4.0
    tracer.cached_segments = tracer.trace_scene(
        sc, mode=sc.optics.trace_mode,
        max_segments=sc.optics.max_segments, max_depth=sc.optics.max_depth)
    sc.optics.live_enabled = True
    render.set_camera(sc, 'HERO')

    coll = bpy.data.collections.get(coll_name)
    if coll:
        for o in context.view_layer.objects:
            o.select_set(False)
        objs = list(coll.objects)
        for o in objs:
            o.select_set(True)
        if objs:
            context.view_layer.objects.active = objs[0]
    try:
        for w in context.window_manager.windows:
            for ar in w.screen.areas:
                if ar.type != 'VIEW_3D':
                    continue
                ar.spaces.active.shading.type = 'MATERIAL'
                ar.spaces.active.clip_end = max(ar.spaces.active.clip_end, 1.0e5)
                reg = next((r for r in ar.regions if r.type == 'WINDOW'), None)
                if reg and coll and len(coll.objects):
                    with context.temp_override(window=w, area=ar, region=reg):
                        bpy.ops.view3d.view_selected()
                ar.tag_redraw()
    except Exception:
        pass


class OPTICS_OT_build_example(Operator):
    bl_idname = "optics.build_example"
    bl_label = "Build Example Setup"
    bl_description = "Build a canonical optical setup from generic components"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(
        name="Setup",
        items=[(k, v[0], v[0]) for k, v in EXAMPLES.items()],
        default='mach_zehnder',
    )

    def execute(self, context):
        name = build(self.kind, context)
        _show(context, name)
        from . import tracer
        self.report({'INFO'}, "Built %s (%d beam segments)"
                    % (EXAMPLES[self.kind][0], len(tracer.cached_segments)))
        return {'FINISHED'}


_classes = (OPTICS_OT_build_example,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
