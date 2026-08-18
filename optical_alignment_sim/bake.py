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

from . import tracer, beamcolor

BEAM_COLL = "COL_BEAMS"
BEAM_MAT = "OPTICS_BEAM"

# Tube radius for a segment that carries NO Gaussian q. Every source-originated ray does carry
# one (the source floors its waist at 1 um, tracer.py), so this is a safety net, not a control:
# the user-facing knob is the scene's beam_radius_scale, which multiplies the real w(z).
FALLBACK_RADIUS_MM = 0.6

_baked_sig = None       # signature of the segments currently baked (so renders never use a stale bake)


def _scene_scale(scene):
    return float(getattr(scene.optics, "beam_radius_scale", 1.0) or 1.0)


def _segments_sig(segs, oob=None, scale=None):
    """Hash of everything the bake turns into meshes and materials.

    Endpoints are not enough. The tube's SHAPE also follows `kind` (a split-transmitted leg
    is drawn thinner) and the Gaussian taper (`w_mm`/`qd`/`m2`), and its COLOUR follows the
    wavelength and the invisible-beam mode. Signing geometry alone let `ensure_beams` keep a
    stale bake when only the colour had moved: retune a source's wavelength, or switch
    oob_display, and the render still showed the previous tubes because nothing had moved.

    `scale` is in here for the same reason: it resizes every tube while moving nothing, so a
    signature blind to it would render the previous widths."""
    rows = []
    for s in segs:
        rows.append((
            tuple(round(c, 3) for pt in (s["p1"], s["p2"]) for c in pt),
            s.get("kind"), s.get("wavelength"), s.get("m2"),
            round(s.get("w_mm") or 0.0, 6),
            tuple(round(v, 6) for v in (s.get("qd") or ())),
        ))
    return hash((oob, round(float(scale), 6) if scale is not None else None, tuple(rows)))


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


def beam_material(wl_nm=None, mode='FALSE_COLOR'):
    """Per-wavelength emission material (BEAM_MAT for the legacy default, BEAM_MAT_<nm>_<mode>
    otherwise) so a baked bench shows its real colors -- an SHG bench MUST read IR in / green out.

    The colour convention lives in `beamcolor`, shared with the viewport overlay and the SVG
    export. Returns None when `mode` hides this wavelength, so the caller skips the tube."""
    if wl_nm is None:
        name, color, strength = BEAM_MAT, (1.0, 0.08, 0.04, 1.0), 25.0   # legacy default (633-class red)
    else:
        rgb = beamcolor.wavelength_rgb(wl_nm, mode)
        if rgb is None:                                     # HIDE: this beam is not drawn at all
            return None
        # The name IS the cache key, so it must separate everything that separates the colour.
        # The mode belongs in it (the same 1064 nm beam is a different colour under VIVID), and
        # the wavelength has to keep its decimals: rounding to a whole nm collided any two lines
        # that round the same way into one datablock, and the second one then silently rendered
        # in the first one's colour (589.0 and 589.4 nm both key to 589, and differ by 3/255 in
        # green -- the pair test_optics pins).
        name = "%s_%.3f_%s" % (BEAM_MAT, float(wl_nm), mode)
        color = tuple(rgb) + (1.0,)
        strength = beamcolor.emission_strength(wl_nm, mode)
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    em.inputs["Strength"].default_value = strength
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


def _vis_radius(w_mm, kind, scale=1.0):
    """VISIBLE tube radius tracking the REAL 1/e^2 Gaussian radius w(z) -- so the beam you SEE matches the
    footprint the physics actually samples (an expanded beam renders WIDE, covering the whole illuminated
    optic, not a thin stand-in). Floored at 0.3 mm so a focus / thin beam stays a visible neck; NO upper
    clamp, so a beam-expander's wide collimated output is shown at its true size (the old 6 mm cap made a
    Ø20 mm beam look Ø12 mm -- visually under-illuminating an optic the sensor fully reads).

    `scale` multiplies the result: w(z) stays the truth, and a figure that needs fatter beams gets
    them without pretending the beam is physically wider. FALLBACK_RADIUS_MM only covers a segment
    that carries no Gaussian at all."""
    r = max(w_mm, 0.3) if (w_mm and w_mm > 0.0) else FALLBACK_RADIUS_MM
    return r * scale * (0.6 if kind == 'SPLIT_T' else 1.0)


def bake_beams(context, scale=None):
    """Bake the traced beams into meshes. `scale` multiplies every tube's radius (None = the
    scene's beam_radius_scale). It is a display scale on the real w(z), not a radius in mm --
    the old `radius` argument claimed to be one but never reached a Gaussian segment."""
    global _baked_sig
    from . import physics
    scene = context.scene
    if scale is None:
        scale = _scene_scale(scene)
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
    oob = getattr(scene.optics, "oob_display", 'FALSE_COLOR')
    for i, s in enumerate(tracer.cached_segments):
        mat = beam_material(s.get("wavelength"), oob)  # per-segment color: SHG green != pump IR
        if mat is None:                                # hidden by the invisible-beam mode (IR/UV)
            continue
        p1, p2 = Vector(s["p1"]), Vector(s["p2"])
        qd = s.get("qd")
        if qd is not None:                              # taper to the real Gaussian w(z) along the segment
            q2 = complex(qd[0], qd[1]); wl = s.get("wavelength", 633.0)
            m2 = s.get("m2", 1.0)                          # B1: physical radius = sqrt(m2)*beam_radius(q)
            L = (p2 - p1).length
            r1 = _vis_radius(physics.beam_radius_m2(q2 - L, wl, m2), s["kind"], scale)   # w at p1
            r2 = _vis_radius(s.get("w_mm") or physics.beam_radius_m2(q2, wl, m2), s["kind"], scale)  # w at p2
        else:                                           # no Gaussian -> the fallback (thinner for SPLIT_T)
            r1 = r2 = _vis_radius(0.0, s["kind"], scale)
        if _make_taper(context, "BEAM_%02d" % i, p1, p2, r1, r2, mat, coll):
            n += 1
    _baked_sig = _segments_sig(tracer.cached_segments, oob, scale)
    return n


def ensure_beams(context):
    """Make sure baked beams exist AND match what the current scene should draw, before a
    render. Re-bakes when anything the bake depends on has changed since the last one -- the
    beam path, but also the wavelengths, the invisible-beam mode and the width scale, which
    change the tubes without moving them (the old bake would otherwise render stale beams)."""
    scene = context.scene
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
    tracer.cached_segments = segs
    c = bpy.data.collections.get(BEAM_COLL)
    have = c is not None and any(o.name.startswith("BEAM_") for o in c.objects)
    oob = getattr(scene.optics, "oob_display", 'FALSE_COLOR')
    if have and _segments_sig(segs, oob, _scene_scale(scene)) == _baked_sig:
        return len(c.objects)
    return bake_beams(context)


class OPTICS_OT_bake_beams(Operator):
    bl_idname = "optics.bake_beams"
    bl_label = "Bake Beams to Mesh"
    # "(for rendering)" told users the opposite of the truth: these ARE real mesh objects in
    # COL_BEAMS, so they export to glTF/FBX/OBJ like any other geometry. A user who wanted the
    # beams in a slide deck read that parenthetical and concluded the beams were viewport-only.
    bl_description = ("Turn the traced beam path into real mesh objects in COL_BEAMS -- editable, "
                      "renderable, and exported with the rest of the scene")
    bl_options = {'REGISTER', 'UNDO'}

    # A SCALE, not a radius in mm: the tube follows the real w(z), this widens it for a figure.
    # Defaults to 0 meaning "use the scene setting", so the redo panel does not silently
    # override beam_radius_scale every time the operator runs.
    scale: FloatProperty(name="Width scale", default=0.0, min=0.0, max=20.0,
                         description="Multiply the beam tube width (0 = use the scene's Beam width scale)")

    def execute(self, context):
        n = bake_beams(context, scale=(self.scale if self.scale > 0.0 else None))
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
