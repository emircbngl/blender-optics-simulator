"""Generic, mesh-free optical components (Tier 1).

Builds optical elements from Blender primitives with correct ports, materials,
and orientation so the geometric tracer chains. No vendor meshes required, so the
canonical example setups (Mach-Zehnder, Michelson, HOM, Bell) are fully portable
and runnable by anyone.

Orientation convention: each element has a canonical local frame; placement
helpers rotate the object so its local frame maps onto the requested world
directions. Because ports are stored in local space, world ports follow
matrix_world automatically (the same math the tracer/alignment rely on).
"""
from __future__ import annotations

import bpy
from mathutils import Vector, Matrix

# --- materials --------------------------------------------------------------

def _mat(name, color, metal=0.0, rough=0.3, emit=None, alpha=1.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if emit is not None:
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs[0].default_value = (*emit, 1.0)
        e.inputs[1].default_value = 6.0
        nt.links.new(e.outputs[0], out.inputs[0])
    else:
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        b.inputs["Base Color"].default_value = (*color, alpha)
        b.inputs["Metallic"].default_value = metal
        b.inputs["Roughness"].default_value = rough
        if alpha < 1.0 and "Alpha" in b.inputs:
            b.inputs["Alpha"].default_value = alpha
            if hasattr(m, "blend_method"):           # removed in Blender 4.3+ (EEVEE Next)
                m.blend_method = 'BLEND'
        nt.links.new(b.outputs[0], out.inputs[0])
    return m


# Opaque, distinctly-colored materials so every component is clearly visible in
# both the viewport and renders (glass-style transparency hid parts in Cycles).
MATS = {
    "mirror": lambda: _mat("OG_mirror", (0.85, 0.88, 0.92), metal=1.0, rough=0.05),
    "bs":     lambda: _mat("OG_bs", (0.35, 0.60, 0.95), metal=0.0, rough=0.15),
    "pbs":    lambda: _mat("OG_pbs", (0.55, 0.50, 0.90), metal=0.0, rough=0.15),
    "lens":   lambda: _mat("OG_lens", (0.45, 0.80, 0.95), metal=0.0, rough=0.10),
    "wp":     lambda: _mat("OG_waveplate", (0.95, 0.80, 0.30), metal=0.2, rough=0.30),
    "bbo":    lambda: _mat("OG_bbo", (0.65, 0.30, 0.85), metal=0.2, rough=0.25),
    "laser":  lambda: _mat("OG_laser", (0.7, 0.05, 0.03), emit=(1.0, 0.1, 0.05)),
    "det":    lambda: _mat("OG_detector", (0.04, 0.04, 0.05), metal=0.3, rough=0.8),
    "ap":     lambda: _mat("OG_aperture", (0.06, 0.06, 0.06), metal=0.5, rough=0.6),
    "pol":    lambda: _mat("OG_polarizer", (0.20, 0.70, 0.55), metal=0.1, rough=0.25),
    "filt":   lambda: _mat("OG_filter", (0.95, 0.45, 0.20), metal=0.0, rough=0.20),
    "iso":    lambda: _mat("OG_isolator", (0.30, 0.30, 0.34), metal=0.8, rough=0.35),
    "dichroic": lambda: _mat("OG_dichroic", (0.80, 0.35, 0.70), metal=0.1, rough=0.12),
    "grating": lambda: _mat("OG_grating", (0.55, 0.45, 0.65), metal=0.9, rough=0.20),
    "retro":  lambda: _mat("OG_retro", (0.75, 0.78, 0.85), metal=1.0, rough=0.10),
    "fiber":  lambda: _mat("OG_fiber", (0.40, 0.42, 0.48), metal=0.85, rough=0.30),
}


# --- low-level helpers ------------------------------------------------------

def _link_only(obj, coll):
    if coll is None:
        return
    for c in list(obj.users_collection):
        if c is not coll:
            c.objects.unlink(obj)
    if obj.name not in coll.objects:
        coll.objects.link(obj)


def _cube(name, size, coll):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    o = bpy.context.active_object
    o.name = name
    o.dimensions = size if hasattr(size, "__len__") else (size, size, size)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _link_only(o, coll)
    return o


def _disc(name, radius, depth, coll):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=(0, 0, 0), vertices=48)
    o = bpy.context.active_object
    o.name = name
    _link_only(o, coll)
    return o


def _add_port(obj, nm, role, pos, nrm, ca):
    p = obj.optics.ports.add()
    p.name = nm
    p.role = role
    p.local_position = pos
    p.local_normal = Vector(nrm).normalized()
    p.clear_aperture = ca


def _tag(obj, element_type, **params):
    op = obj.optics
    op.is_optical = True
    op.element_type = element_type
    op.ports.clear()
    for k, v in params.items():
        if hasattr(op, k):
            setattr(op, k, v)


def _set_matrix(obj, loc, rot3=None):
    """Place obj at loc with optional 3x3 world rotation matrix."""
    if rot3 is None:
        obj.matrix_world = Matrix.Translation(loc)
    else:
        obj.matrix_world = Matrix.Translation(loc) @ rot3.to_4x4()


def _basis(x, y):
    """Orthonormal 3x3 mapping local +X->x, +Y->y, +Z->x cross y (columns)."""
    x = Vector(x).normalized()
    y = Vector(y).normalized()
    z = x.cross(y)
    if z.length < 1e-6:
        # x,y parallel; pick an arbitrary perpendicular
        y = x.orthogonal().normalized()
        z = x.cross(y)
    z.normalize()
    y = z.cross(x).normalized()
    return Matrix((x, y, z)).transposed()    # columns = x,y,z


def _z_to(n):
    """3x3 rotation mapping local +Z onto unit vector n."""
    return Vector((0.0, 0.0, 1.0)).rotation_difference(Vector(n).normalized()).to_matrix()


# --- component placement helpers --------------------------------------------

def source(name, loc, direction, coll=None, wavelength=632.8, length=40.0, radius=7.0):
    """A laser/source emitting along `direction` from its front face."""
    o = _disc(name, radius, length, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["laser"]())
    _tag(o, 'SOURCE', is_source=True, wavelength=wavelength)
    _add_port(o, "OUT", 'OUT', (0, 0, length * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(direction))
    return o


def mirror(name, loc, in_dir, out_dir, coll=None, size=25.0):
    """A flat fold mirror that turns a beam from in_dir to out_dir."""
    n = (Vector(out_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    o = _cube(name, (size, size, 4.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["mirror"]())
    _tag(o, 'MIRROR', clear_aperture=size * 0.5, reflectivity=1.0)
    _add_port(o, "IN", 'IN', (0, 0, 2.0), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(n))     # local +Z (face/REFLECT normal) -> bisector n
    return o


def beamsplitter(name, loc, in_dir, reflect_dir, coll=None, split=0.5, pbs=False, size=25.0):
    """50/50 (or PBS) cube: transmits along in_dir, reflects toward reflect_dir."""
    o = _cube(name, (size, size, size), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["pbs" if pbs else "bs"]())
    _tag(o, 'BEAMSPLITTER', split_ratio=split, clear_aperture=size * 0.55, is_pbs=pbs)
    o.optics.mount_preset = "PBS" if pbs else ""
    h = size * 0.5
    _add_port(o, "IN", 'IN', (-h, 0, 0), (-1, 0, 0), size * 0.55)
    _add_port(o, "OUT", 'OUT', (h, 0, 0), (1, 0, 0), size * 0.55)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), Vector((-1, 1, 0)).normalized(), size * 0.55)
    _set_matrix(o, Vector(loc), _basis(in_dir, reflect_dir))   # +X->in, +Y->reflect
    return o


def detector(name, loc, beam_dir, coll=None, size=22.0):
    """A detector/camera whose sensor faces the incoming beam."""
    o = _cube(name, (size, size, 8.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["det"]())
    _tag(o, 'DETECTOR', is_detector=True, clear_aperture=size * 0.5)
    facing = -Vector(beam_dir).normalized()
    _add_port(o, "IN", 'IN', (0, 0, 4.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(facing))   # +Z (IN normal) -> faces the beam
    return o


def _inline(name, loc, axis, coll, element_type, matkey, radius=14.0, depth=6.0, **params):
    o = _disc(name, radius, depth, coll)
    o.data.materials.clear(); o.data.materials.append(MATS[matkey]())
    _tag(o, element_type, clear_aperture=radius, **params)
    _add_port(o, "IN", 'IN', (0, 0, -depth * 0.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, depth * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))     # optical axis = local +Z -> world axis
    return o


def lens(name, loc, axis, coll=None, focal=100.0, radius=14.0):
    return _inline(name, loc, axis, coll, 'LENS', "lens", radius=radius, depth=5.0, focal_length=focal)


def waveplate(name, loc, axis, coll=None, kind='HWP'):
    ret = 90.0 if str(kind).upper() == 'QWP' else 180.0      # QWP=90deg, HWP=180deg retardance
    o = _inline(name, loc, axis, coll, 'WAVEPLATE', "wp", radius=12.0, depth=3.0, retardance_deg=ret)
    o.optics.mount_preset = kind
    return o


def aperture(name, loc, axis, coll=None, radius=14.0):
    return _inline(name, loc, axis, coll, 'APERTURE', "ap", radius=radius, depth=3.0)


def crystal(name, loc, beam_dir, coll=None, size=14.0):
    """A nonlinear crystal (e.g. BBO) shown as a small block; tagged DETECTOR so the
    pump beam terminates on it (signal/idler are emitted by separate sources).
    Its IN face is oriented to face the incoming pump (`beam_dir`)."""
    o = _cube(name, (size * 0.6, size * 0.6, size), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["bbo"]())
    _tag(o, 'DETECTOR', clear_aperture=size)
    _add_port(o, "IN", 'IN', (0, 0, size * 0.5), (0, 0, 1), size)
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
    return o


# --- additional component builders (broad library) --------------------------
# Inline (pass-through) parts reuse `_inline`: a disc with IN/OUT ports on its
# optical axis; the tracer transmits the beam straight through (layout fidelity).

def polarizer(name, loc, axis, coll=None, radius=12.5):
    """A linear polarizer; geometrically a pass-through inline plate."""
    return _inline(name, loc, axis, coll, 'POLARIZER', "pol", radius=radius, depth=3.0)


def optical_filter(name, loc, axis, coll=None, radius=12.5,
                   filt_type='BP', cut_lo_nm=600.0, cut_hi_nm=700.0, od=1.0):
    """An optical filter (longpass/shortpass/bandpass/ND); transmits per its band."""
    return _inline(name, loc, axis, coll, 'FILTER', "filt", radius=radius, depth=3.5,
                   filt_type=filt_type, cut_lo_nm=cut_lo_nm, cut_hi_nm=cut_hi_nm, od=od)


def pinhole(name, loc, axis, coll=None, radius=12.5):
    """A spatial-filter pinhole; the beam passes through the bore."""
    return _inline(name, loc, axis, coll, 'PINHOLE', "ap", radius=radius, depth=2.0)


def isolator(name, loc, axis, coll=None, radius=9.0, length=40.0):
    """A Faraday optical isolator; a tube the beam passes through one way."""
    return _inline(name, loc, axis, coll, 'ISOLATOR', "iso", radius=radius, depth=length)


def fiber_collimator(name, loc, direction, coll=None, wavelength=632.8, length=30.0, radius=6.0):
    """A fiber-coupled collimator that launches a beam along `direction` (source-like)."""
    o = _disc(name, radius, length, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["fiber"]())
    _tag(o, 'FIBER_COLLIMATOR', is_source=True, wavelength=wavelength)
    _add_port(o, "OUT", 'OUT', (0, 0, length * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(direction))
    return o


def photodiode(name, loc, beam_dir, coll=None, size=14.0):
    """A point photodiode whose sensor faces the incoming beam; terminates it."""
    o = _cube(name, (size, size, 6.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["det"]())
    _tag(o, 'PHOTODIODE', is_detector=True, clear_aperture=size * 0.5)
    _add_port(o, "IN", 'IN', (0, 0, 3.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
    return o


def power_meter(name, loc, beam_dir, coll=None, size=20.0):
    """A power-meter sensor head facing the incoming beam; terminates it."""
    o = _cube(name, (size, size, 10.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["det"]())
    _tag(o, 'POWER_METER', is_detector=True, clear_aperture=size * 0.5)
    _add_port(o, "IN", 'IN', (0, 0, 5.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
    return o


def dichroic(name, loc, in_dir, reflect_dir, coll=None, split=0.5, size=25.0,
             pass_type='LP', cut_nm=650.0):
    """A dichroic mirror (plate at 45deg): transmits or reflects by wavelength
    (longpass transmits >= cut_nm, shortpass transmits <= cut_nm)."""
    n = (Vector(reflect_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    o = _cube(name, (size, size, 3.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["dichroic"]())
    _tag(o, 'DICHROIC', split_ratio=split, clear_aperture=size * 0.5, reflectivity=1.0,
         pass_type=pass_type, cut_nm=cut_nm)
    _add_port(o, "IN", 'IN', (0, 0, 1.5), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(n))     # local +Z (REFLECT normal) -> bisector n
    return o


def grating(name, loc, in_dir, out_dir, coll=None, size=25.0, lines_per_mm=1200.0, order=1):
    """A reflective diffraction grating. ``out_dir`` sets the surface orientation
    (the 0th-order/specular direction); the traced ``order`` beam is deflected from
    it by the grating equation."""
    n = (Vector(out_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    o = _cube(name, (size, size, 5.0), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["grating"]())
    _tag(o, 'GRATING', clear_aperture=size * 0.5, reflectivity=0.8,
         lines_per_mm=lines_per_mm, grating_order=order)
    _add_port(o, "IN", 'IN', (0, 0, 2.5), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(n))
    return o


def retroreflector(name, loc, in_dir, coll=None, size=25.0):
    """A corner-cube retroreflector: returns the beam antiparallel to `in_dir`.
    The REFLECT normal is set anti-parallel to the incoming beam so the specular
    reflection sends it straight back."""
    d = Vector(in_dir).normalized()
    o = _cube(name, (size, size, size * 0.8), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["retro"]())
    _tag(o, 'RETROREFLECTOR', clear_aperture=size * 0.5, reflectivity=0.95)
    _add_port(o, "IN", 'IN', (0, 0, size * 0.4), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-d))    # REFLECT normal anti-parallel to incoming
    return o


def cavity(name, loc, axis, coll=None, spacing_mm=0.05, R=0.9, size=25.0):
    """A Fabry-Perot etalon (two partial mirrors); wavelength-dependent Airy transmission."""
    return _inline(name, loc, axis, coll, 'CAVITY', "bs", radius=size * 0.5, depth=8.0,
                   cavity_spacing_mm=spacing_mm, reflectivity=R)


def add_translation_dof(obj, axis_world, mm_min=-25.0, mm_max=25.0, current=0.0):
    """Give an element a linear translation knob (e.g. Michelson OPD stage)."""
    from . import mounts
    op = obj.optics
    if not op.base_pose_set:
        mounts.store_base_matrix(op, obj.matrix_world.copy())
    # express axis in the base/local frame
    B = mounts.base_matrix(op)
    axis_local = B.to_3x3().inverted() @ Vector(axis_world).normalized()
    d = op.dofs.add()
    d.kind = 'TRANS_Z'
    d.name = "stage"
    d.axis_local = axis_local.normalized()
    d.pivot_local = (0, 0, 0)
    d.min_val, d.max_val = mm_min, mm_max
    d.current = current
    op.mount_type = 'TRANSLATION'
    return d


def example_collection(name):
    """Fresh collection for an example (removes any prior build of the same name)."""
    c = bpy.data.collections.get(name)
    if c:
        for o in list(c.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(c)
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c
