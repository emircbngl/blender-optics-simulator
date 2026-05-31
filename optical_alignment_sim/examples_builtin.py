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
    G.waveplate("Bell_S_HWP", 60.0 * dS, dS, coll, kind='HWP')
    G.beamsplitter("Bell_S_PBS", 120.0 * dS, dS, rS, coll, pbs=True)
    G.detector("Bell_S_H", 210.0 * dS, dS, coll)
    G.detector("Bell_S_V", 120.0 * dS + 80.0 * rS, rS, coll)

    # idler arm
    G.source("Bell_I_src", (0, 0, 0), dI, coll, wavelength=810.0, length=18, radius=4)
    G.waveplate("Bell_I_HWP", 60.0 * dI, dI, coll, kind='HWP')
    G.beamsplitter("Bell_I_PBS", 120.0 * dI, dI, rI, coll, pbs=True)
    G.detector("Bell_I_H", 210.0 * dI, dI, coll)
    G.detector("Bell_I_V", 120.0 * dI + 80.0 * rI, rI, coll)
    return "OpticsExample_Bell"


EXAMPLES = {
    'mach_zehnder': ("Mach-Zehnder Interferometer", build_mach_zehnder),
    'michelson':    ("Michelson Interferometer", build_michelson),
    'hong_ou_mandel': ("Hong-Ou-Mandel", build_hong_ou_mandel),
    'bell':         ("Bell / Entanglement Source", build_bell_entanglement),
}


def _reset_examples():
    """Remove previously-built example collections + baked beams so each example
    is built in isolation (otherwise multiple setups share the trace)."""
    from . import tracer, bake
    for c in list(bpy.data.collections):
        if c.name.startswith("OpticsExample_"):
            for o in list(c.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    try:
        bake.clear_baked(bpy.context.scene)
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
