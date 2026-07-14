"""Bake the live beam overlay into real emission-cylinder meshes so Cycles/EEVEE
can render the beams (the GPU overlay is viewport-only and invisible to renders).

Beams go into a dedicated COL_BEAMS collection and are named BEAM_##, matching the
user's existing convention. This is the only module that writes mesh datablocks,
and only on explicit request (bake / render).
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import FloatProperty
from mathutils import Vector

from . import tracer

BEAM_COLL = "COL_BEAMS"
BEAM_MAT = "OPTICS_BEAM"

_baked_sig = None       # signature of the segments currently baked (so renders never use a stale bake)


def _segments_sig(segs):
    """Cheap hash of the baked beam geometry (segment endpoints)."""
    return hash(tuple(round(c, 3) for s in segs
                      for pt in (s["p1"], s["p2"]) for c in pt))


def beam_collection(scene):
    c = bpy.data.collections.get(BEAM_COLL)
    if c is None:
        c = bpy.data.collections.new(BEAM_COLL)
    if c.name not in scene.collection.children:     # may exist but be linked to a DIFFERENT scene
        try:
            scene.collection.children.link(c)
        except RuntimeError:
            pass
    return c


def wavelength_rgb(wl_nm):
    """Visible-spectrum wavelength -> linear RGB (Bruton-style piecewise approximation).

    VISUALIZATION convention, not radiometry: out-of-band light is invisible in reality, but a
    black tube reads as "no beam", so IR (>780 nm) renders as a dim deep crimson and UV (<380 nm)
    as a dim violet -- the standard optics-figure convention (e.g. a 1064 nm pump drawn dark red
    next to its bright green 532 nm harmonic)."""
    w = float(wl_nm)
    if w < 380.0:
        r, g, b = 0.35, 0.08, 0.55
    elif w < 440.0:
        r, g, b = (440.0 - w) / 60.0, 0.0, 1.0
    elif w < 490.0:
        r, g, b = 0.0, (w - 440.0) / 50.0, 1.0
    elif w < 510.0:
        r, g, b = 0.0, 1.0, (510.0 - w) / 20.0
    elif w < 545.0:
        r, g, b = 0.0, 1.0, 0.0                  # green plateau: 532 nm must READ laser-green
    elif w < 580.0:
        r, g, b = (w - 545.0) / 35.0, 1.0, 0.0
    elif w < 645.0:
        # squared falloff: 633 nm must stay LASER-red under a bright emission (a linear ramp
        # leaves g=0.19 there, which blooms yellow-orange); 589 nm still reads sodium-yellow
        r, g, b = 1.0, ((645.0 - w) / 65.0) ** 2, 0.0
    elif w <= 780.0:
        r, g, b = 1.0, 0.0, 0.0
    else:
        r, g, b = 0.55, 0.02, 0.02
    # gentle intensity roll-off at the band edges (keeps 633 nm at full brightness)
    if 380.0 <= w < 420.0:
        f = 0.3 + 0.7 * (w - 380.0) / 40.0
        r, g, b = r * f, g * f, b * f
    elif 700.0 < w <= 780.0:
        f = 0.3 + 0.7 * (780.0 - w) / 80.0
        r, g, b = r * f, g * f, b * f
    return r, g, b


def beam_material(wl_nm=None):
    """Per-wavelength emission material (BEAM_MAT for the legacy default, BEAM_MAT_<nm> otherwise)
    so a baked bench shows its real colors -- an SHG bench MUST read IR in / green out."""
    if wl_nm is None:
        name, color = BEAM_MAT, (1.0, 0.08, 0.04, 1.0)      # legacy default (633-class red)
    else:
        name = "%s_%d" % (BEAM_MAT, int(round(wl_nm)))
        r, g, b = wavelength_rgb(wl_nm)
        color = (r, g, b, 1.0)
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    # out-of-band tubes glow dimmer: an IR pump should read as a dark ember next to its harmonic
    em.inputs["Strength"].default_value = 25.0 if (wl_nm is None or 380.0 <= wl_nm <= 780.0) else 14.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def clear_baked(scene):
    # collect BEAM_* both in COL_BEAMS and anywhere in the scene (renamed/moved collections),
    # and free the per-segment Mesh datablock too (do_unlink leaves it a 0-user orphan otherwise)
    targets = {}
    c = bpy.data.collections.get(BEAM_COLL)
    if c:
        for ob in c.objects:
            if ob.name.startswith("BEAM_"):
                targets[ob.name] = ob
    for ob in scene.objects:
        if ob.name.startswith("BEAM_"):
            targets[ob.name] = ob
    n = 0
    for ob in list(targets.values()):
        mesh = ob.data if ob.type == 'MESH' else None
        bpy.data.objects.remove(ob, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        n += 1
    return n


def _make_cylinder(context, name, p1, p2, r, mat, coll):
    d = p2 - p1
    length = d.length
    if length < 1e-6:
        return None
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=length, location=(p1 + p2) * 0.5)
    ob = context.active_object
    ob.name = name
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    for c in list(ob.users_collection):
        if c is not coll:
            c.objects.unlink(ob)
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    return ob


def _make_taper(context, name, p1, p2, r1, r2, mat, coll):
    """A truncated-cone beam segment: radius r1 at p1, r2 at p2 -- so the rendered beam follows the real
    Gaussian w(z) (pinches at a focus, flares after a lens). r1==r2 gives a plain cylinder."""
    d = p2 - p1
    length = d.length
    if length < 1e-6:
        return None
    bpy.ops.mesh.primitive_cone_add(radius1=max(r1, 1e-4), radius2=max(r2, 1e-4), depth=length,
                                    location=(p1 + p2) * 0.5, vertices=24)
    ob = context.active_object
    ob.name = name
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    for c in list(ob.users_collection):
        if c is not coll:
            c.objects.unlink(ob)
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    return ob


def _vis_radius(w_mm, base, kind):
    """VISIBLE tube radius tracking the REAL 1/e^2 Gaussian radius w(z) -- so the beam you SEE matches the
    footprint the physics actually samples (an expanded beam renders WIDE, covering the whole illuminated
    optic, not a thin stand-in). Floored at 0.3 mm so a focus / thin beam stays a visible neck; NO upper
    clamp, so a beam-expander's wide collimated output is shown at its true size (the old 6 mm cap made a
    Ø20 mm beam look Ø12 mm -- visually under-illuminating an optic the sensor fully reads)."""
    r = max(w_mm, 0.3) if (w_mm and w_mm > 0.0) else base
    return r * (0.6 if kind == 'SPLIT_T' else 1.0)


def bake_beams(context, radius=0.6):
    global _baked_sig
    from . import physics
    scene = context.scene
    # always re-trace: baking the current geometry (not a possibly-stale cache from before the
    # last edit, e.g. with live mode off) is the whole point of a fresh bake
    tracer.cached_segments = tracer.trace_scene(
        scene, mode=scene.optics.trace_mode,
        max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    clear_baked(scene)
    coll = beam_collection(scene)
    n = 0
    for i, s in enumerate(tracer.cached_segments):
        mat = beam_material(s.get("wavelength"))     # per-segment color: SHG green != pump IR
        p1, p2 = Vector(s["p1"]), Vector(s["p2"])
        qd = s.get("qd")
        if qd is not None:                              # taper to the real Gaussian w(z) along the segment
            q2 = complex(qd[0], qd[1]); wl = s.get("wavelength", 633.0)
            m2 = s.get("m2", 1.0)                          # B1: physical radius = sqrt(m2)*beam_radius(q)
            L = (p2 - p1).length
            r1 = _vis_radius(physics.beam_radius_m2(q2 - L, wl, m2), radius, s["kind"])   # w at p1
            r2 = _vis_radius(s.get("w_mm") or physics.beam_radius_m2(q2, wl, m2), radius, s["kind"])  # w at p2
        else:                                           # no Gaussian -> constant (thinner for SPLIT_T)
            r1 = r2 = radius * (0.6 if s["kind"] == 'SPLIT_T' else 1.0)
        if _make_taper(context, "BEAM_%02d" % i, p1, p2, r1, r2, mat, coll):
            n += 1
    _baked_sig = _segments_sig(tracer.cached_segments)
    return n


def ensure_beams(context):
    """Make sure baked beams exist AND match the current beam path before a render. Re-bakes
    when the path has changed since the last bake (the old bake would otherwise render stale
    beams over the moved optics)."""
    scene = context.scene
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    tracer.cached_segments = segs
    c = bpy.data.collections.get(BEAM_COLL)
    have = c is not None and any(o.name.startswith("BEAM_") for o in c.objects)
    if have and _segments_sig(segs) == _baked_sig:
        return len(c.objects)
    return bake_beams(context)


class OPTICS_OT_bake_beams(Operator):
    bl_idname = "optics.bake_beams"
    bl_label = "Bake Beams to Mesh"
    bl_description = "Create emission-cylinder meshes from the current beam path (for rendering)"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(name="Beam radius (mm)", default=0.6, min=0.01)

    def execute(self, context):
        n = bake_beams(context, radius=self.radius)
        self.report({'INFO'}, "Baked %d beam segments into '%s'" % (n, BEAM_COLL))
        return {'FINISHED'}


class OPTICS_OT_clear_baked(Operator):
    bl_idname = "optics.clear_baked"
    bl_label = "Clear Baked Beams"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = clear_baked(context.scene)
        self.report({'INFO'}, "Removed %d baked beams" % n)
        return {'FINISHED'}


_classes = (OPTICS_OT_bake_beams, OPTICS_OT_clear_baked)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
