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
    # accent materials (slot 1+): keep their colour in realistic renders (only slot 0 is theme-swapped)
    "subglass":  lambda: _mat("OG_substrate", (0.28, 0.31, 0.37), metal=0.0, rough=0.22),
    "coatbs":    lambda: _mat("OG_coat_bs", (0.55, 0.78, 1.00), metal=0.4, rough=0.10),
    # a PBS shows a vivid, more mirror-like polarizing coating on the diagonal -> clearly NOT a 50/50 BS
    "coatpbs":   lambda: _mat("OG_coat_pbs", (0.90, 0.28, 0.80), metal=0.7, rough=0.04),
    "coatdich":  lambda: _mat("OG_coat_dich", (0.95, 0.55, 0.85), metal=0.4, rough=0.08),
    "sensor":    lambda: _mat("OG_sensor", (0.02, 0.03, 0.07), metal=0.2, rough=0.45),
    "bezel":     lambda: _mat("OG_bezel", (0.48, 0.49, 0.54), metal=0.9, rough=0.30),
    "arrow":     lambda: _mat("OG_arrow", (0.90, 0.90, 0.92), metal=0.5, rough=0.30),
    "index":     lambda: _mat("OG_index", (0.92, 0.86, 0.45), metal=0.3, rough=0.30),
    "laserbody": lambda: _mat("OG_laserbody", (0.12, 0.13, 0.15), metal=0.7, rough=0.35),
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


def _lozenge(name, radius, depth, coll):
    """A smooth biconvex (lens) solid: a UV sphere flattened along the optical (+Z) axis, so it
    reads as real curved glass. Its z-extent is +/-depth/2, matching the inline disc's port
    planes, so swapping it in does not move any port."""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, 0), segments=48, ring_count=24)
    o = bpy.context.active_object
    o.name = name
    o.scale = (1.0, 1.0, (depth * 0.5) / radius)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for p in o.data.polygons:
        p.use_smooth = True
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


# --- procedural optic-mesh helpers ------------------------------------------
# These build realistic optic meshes (curved lenses, real bores, corner-cube facets, ruled grating,
# etc.) as a SINGLE object centred at the origin with +Z as the optical/face axis -- exactly the frame
# the old primitives used -- so each builder can keep its ports + _set_matrix untouched and the tracer
# sees identical inputs (trace stays byte-identical). Accent detail lives in material slot 1+, which the
# realistic-render pass leaves alone (it only theme-swaps slot 0).
import bmesh  # noqa: E402


def _bm_obj(name, bm, coll, smooth=False):
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if smooth:
        for f in bm.faces:
            f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    _link_only(o, coll)
    return o


def _join(o, other):
    """Merge `other` into `o` (single object/mesh), freeing the orphaned datablock."""
    bpy.ops.object.select_all(action='DESELECT')
    other.select_set(True); o.select_set(True)
    bpy.context.view_layer.objects.active = o
    md = other.data
    bpy.ops.object.join()
    if md.users == 0:
        bpy.data.meshes.remove(md)
    return o


def _accent(o, matkey, pred):
    """Append an accent material as a new slot and reassign every face where pred(center, normal)."""
    idx = len(o.data.materials)
    o.data.materials.append(MATS[matkey]())
    for p in o.data.polygons:
        if pred(p.center, p.normal):
            p.material_index = idx
    return idx


def _revolve(name, profile, coll, seg=64, smooth=True):
    """Solid of revolution about +Z from profile=[(r,z),...] whose endpoints sit on the axis."""
    bm = bmesh.new()
    vs = [bm.verts.new((r, 0.0, z)) for (r, z) in profile]
    eds = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
    bmesh.ops.spin(bm, geom=vs + eds, cent=(0, 0, 0), axis=(0, 0, 1), dvec=(0, 0, 0),
                   angle=2.0 * 3.141592653589793, steps=seg, use_duplicate=False)
    return _bm_obj(name, bm, coll, smooth)


def _lens_profile(radius, focal, edge=1.6, lens_type='AUTO'):
    """Half cross-section of a spherical lens, shaped by the lens FORM (variant): the front surface is
    convex (PCX/BCX, or AUTO with focal>=0) or concave (PCV/BCV, or AUTO with focal<0); the back surface
    is curved (bi-) or FLAT (plano- = PCX/PCV). Curvature is a cosmetic spherical cap -- the tracer uses
    the ABCD focal length, not the mesh -- but the form + sign make the variant obvious. Exotic forms
    (meniscus/achromat/ball/...) fall back to the AUTO bi-shape here and get distinct meshes elsewhere."""
    import math
    R = radius; N = 20
    sag = max(0.6, min(2.4, 170.0 / max(abs(focal), 12.0)))
    if lens_type in ('PCX', 'BCX'):
        convex = True
    elif lens_type in ('PCV', 'BCV'):
        convex = False
    else:
        convex = (focal >= 0)                          # AUTO + exotic forms: by the focal sign
    back_flat = lens_type in ('PCX', 'PCV')            # only the plano- forms flatten the back
    if convex:
        zc, ze = edge * 0.5 + sag, edge * 0.5          # convex front: centre bulges out
    else:
        zc, ze = edge * 0.5, edge * 0.5 + sag          # concave front: centre dished in

    def zf(r):
        return ze + (zc - ze) * math.sqrt(max(0.0, 1.0 - (r / R) ** 2))
    front = [(R * i / N, zf(R * i / N)) for i in range(N + 1)]          # curved front, axis -> edge
    if back_flat:
        back = [(R * i / N, -ze) for i in range(N, -1, -1)]            # flat back disc at the rim plane
    else:
        back = [(R * i / N, -zf(R * i / N)) for i in range(N, -1, -1)]  # mirrored curved back
    return front + back


def _cyl_bm(bm, radius, depth, seg=56):
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=radius, radius2=radius, depth=depth)


def _bored_disc(name, radius, depth, bore, coll, seg=56):
    """A disc of `radius`/`depth` with a central through-bore of `bore` (boolean DIFFERENCE)."""
    bm = bmesh.new(); _cyl_bm(bm, radius, depth, seg)
    o = _bm_obj(name, bm, coll)
    cb = bmesh.new(); _cyl_bm(cb, bore, depth + 2.0, max(16, seg // 2))
    cutter = _bm_obj(name + "_bore", cb, coll)
    m = o.modifiers.new("bore", 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = cutter
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)
    cmesh = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cmesh.users == 0:                              # free the orphaned cutter mesh (no .blend bloat)
        bpy.data.meshes.remove(cmesh)
    return o


def _iris(name, r_open, coll, depth=3.6):
    """An iris-diaphragm ring: black housing (outer = opening + 5 mm) with a central opening + a small
    side adjustment lever, so it reads as an aperture stop instead of a solid puck."""
    o = _bored_disc(name, r_open + 5.0, depth, r_open, coll)
    lb = bmesh.new()
    bmesh.ops.create_cube(lb, size=1.0)
    for v in lb.verts:
        v.co = Vector((v.co.x * 8.0, v.co.y * 2.6, v.co.z * 2.0)) + Vector((r_open + 7.0, 0.0, 0.0))
    lev = _bm_obj(name + "_lever", lb, coll)
    return _join(o, lev)


def _corner_cube(name, size, coll):
    """A trihedral corner-cube retroreflector: three facets meeting at a rear apex behind a triangular
    front aperture (the optical/diagonal axis is +Z). Cosmetic -- the tracer returns d_out=-d_in."""
    import math
    h = size * 0.5; depth = size * 0.6
    bm = bmesh.new()
    F = [bm.verts.new((h * math.cos(a), h * math.sin(a), 0.0))
         for a in (math.radians(90), math.radians(210), math.radians(330))]
    apex = bm.verts.new((0.0, 0.0, -depth))
    for i in range(3):
        bm.faces.new((apex, F[i], F[(i + 1) % 3]))
    rim = [bm.verts.new((v.co.x, v.co.y, 1.4)) for v in F]              # short front rim for body
    for i in range(3):
        j = (i + 1) % 3
        bm.faces.new((F[i], F[j], rim[j], rim[i]))
    bm.faces.new((rim[0], rim[1], rim[2]))
    return _bm_obj(name, bm, coll, smooth=False)


def _grooved_plate(name, size, depth, coll, n=34):
    """A reflective grating: a square plate with `n` parallel ruled ridges on its +Z face (a groove
    hint -- real line density is a parameter, not meshable, so this is a visual cue of the ruling)."""
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size, v.co.y * size, v.co.z * depth))
    o = _bm_obj(name, bm, coll)
    for k in range(n):
        x = -size * 0.5 + size * (k + 0.5) / n
        rb = bmesh.new(); bmesh.ops.create_cube(rb, size=1.0)
        for v in rb.verts:
            v.co = (Vector((v.co.x * (size / n * 0.45), v.co.y * size * 0.92, v.co.z * 0.5))
                    + Vector((x, 0.0, depth * 0.5 + 0.22)))
        _join(o, _bm_obj(name + "_r%d" % k, rb, coll))
    return o


def _sensor_box(name, size, depth, coll, active=0.55, lenslets=0):
    """A detector head: a dark body box (slot 0) with a recessed active-area inset on its +Z (sensor)
    face in slot 1. With lenslets>0 the inset carries an NxN micro-lens grid (Shack-Hartmann look)."""
    import math
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size, v.co.y * size, v.co.z * depth))
    o = _bm_obj(name, bm, coll)
    o.data.materials.append(MATS["det"]())               # slot 0: body (caller may overwrite)
    o.data.materials.append(MATS["sensor"]())            # slot 1: active area / lenslets
    a = size * active

    def _add_detail(builder):                            # join a slot-1 sub-mesh by face range
        sub = builder()
        base = len(o.data.polygons); _join(o, sub)
        for p in o.data.polygons[base:]:
            p.material_index = 1

    def _inset():
        ab = bmesh.new(); bmesh.ops.create_cube(ab, size=1.0)
        for v in ab.verts:
            v.co = Vector((v.co.x * a, v.co.y * a, v.co.z * 1.2)) + Vector((0.0, 0.0, depth * 0.5 - 0.3))
        return _bm_obj(name + "_act", ab, coll)
    _add_detail(_inset)

    if lenslets:
        zc = depth * 0.5 + 0.7
        step = (a * 1.6) / lenslets
        for ix in range(lenslets):
            for iy in range(lenslets):
                cx = (ix - (lenslets - 1) / 2.0) * step
                cy = (iy - (lenslets - 1) / 2.0) * step
                if math.hypot(cx, cy) > a * 0.85:
                    continue
                def _ll(cx=cx, cy=cy):
                    lb = bmesh.new()
                    bmesh.ops.create_uvsphere(lb, u_segments=8, v_segments=4, radius=step * 0.42)
                    for v in lb.verts:
                        v.co = Vector((v.co.x, v.co.y, v.co.z * 0.4)) + Vector((cx, cy, zc))
                    return _bm_obj(name + "_ll", lb, coll)
                _add_detail(_ll)
    return o


def _bevel(o, width=0.4, seg=2):
    """Chamfer hard edges (machined-glass/metal look). Applied, so the result is plain mesh."""
    m = o.modifiers.new("bevel", 'BEVEL'); m.width = width; m.segments = seg; m.limit_method = 'ANGLE'
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)
    return o


def _etalon(name, radius, half_gap, coll):
    """A Fabry-Perot etalon: two parallel partial-mirror plates separated by an air gap, held by a thin
    spacer wall at the rim -- the defining two-surface structure (vs. a single solid puck)."""
    a = bmesh.new(); _cyl_bm(a, radius, 1.2)
    o = _bm_obj(name, a, coll)
    for v in o.data.vertices:
        v.co.z += half_gap
    b = bmesh.new(); _cyl_bm(b, radius, 1.2)
    back = _bm_obj(name + "_back", b, coll)
    for v in back.data.vertices:
        v.co.z -= half_gap
    _join(o, back)
    wall = _bored_disc(name + "_wall", radius, 2.0 * half_gap, radius - 1.6, coll)
    return _join(o, wall)


# --- component placement helpers --------------------------------------------

def source(name, loc, direction, coll=None, wavelength=632.8, length=40.0, radius=7.0):
    """A laser/source emitting along `direction` from its front face."""
    o = _disc(name, radius, length, coll)
    # a real laser head: a dark anodized HOUSING (slot 0) with only the front APERTURE glowing -- not a
    # uniformly glowing can. The emission stays on slot 2 (kept by the render pass; only slot 0 swaps).
    o.data.materials.clear(); o.data.materials.append(MATS["laserbody"]())
    bz = _bored_disc(name + "_bezel", radius + 1.5, 3.0, radius * 0.55, coll)   # metal exit bezel (slot 1)
    for v in bz.data.vertices:
        v.co.z += length * 0.5
    bz.data.materials.append(MATS["bezel"]())
    _join(o, bz)
    ap = _disc(name + "_ap", radius * 0.48, 1.6, coll)                          # glowing exit aperture (slot 2)
    for v in ap.data.vertices:
        v.co.z += length * 0.5 + 0.3
    ap.data.materials.append(MATS["laser"]())
    _join(o, ap)
    _tag(o, 'SOURCE', is_source=True, wavelength=wavelength)
    _add_port(o, "OUT", 'OUT', (0, 0, length * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(direction))
    return o


def mirror(name, loc, in_dir, out_dir, coll=None, size=25.0):
    """A flat fold mirror that turns a beam from in_dir to out_dir."""
    n = (Vector(out_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    o = _disc(name, size * 0.5, 6.0, coll)        # Ø1" substrate, 6 mm thick; +Z = coated front face
    _bevel(o, 0.5, 2)
    o.data.materials.clear(); o.data.materials.append(MATS["mirror"]())
    # only the +Z front is the reflective coating; the back + ground edge read as bare glass substrate
    _accent(o, "subglass", lambda c, nrm: nrm.z < 0.55)
    _tag(o, 'MIRROR', clear_aperture=size * 0.5, reflectivity=1.0)
    _add_port(o, "IN", 'IN', (0, 0, 2.0), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(n))     # local +Z (face/REFLECT normal) -> bisector n
    return o


def beamsplitter(name, loc, in_dir, reflect_dir, coll=None, split=0.5, pbs=False, size=25.0,
                 bs_form='CUBE'):
    """A 50/50 (or PBS) beamsplitter: transmits along in_dir, reflects toward reflect_dir. ``bs_form``
    shapes the mesh -- a cemented CUBE (with an internal coated diagonal), a 45 deg PLATE, or a thin
    PELLICLE membrane -- but the ports (and therefore the trace) are identical for all three."""
    if bs_form == 'CUBE':
        o = _cube(name, (size, size, size), coll)
        _bevel(o, 0.8, 1)                            # chamfered cube edges (cemented-prism look)
        o.data.materials.clear(); o.data.materials.append(MATS["pbs" if pbs else "bs"]())
        # the characteristic coated 45-deg diagonal: a thin slab whose normal is the REFLECT direction
        # (-1,1,0)/sqrt2, CLIPPED to the cube interior, then merged in with its OWN tinted coating
        # material (slot 1) so the partial reflector is visibly distinct (PBS vs 50/50 differ by tint).
        _coat = _cube(name + "_coat", (size * 1.55, size * 1.55, 0.5), coll)
        _coat.data.materials.append(MATS["coatpbs" if pbs else "coatbs"]())
        _coat.matrix_world = _z_to(Vector((-1.0, 1.0, 0.0))).to_4x4()
        _clip = _coat.modifiers.new("clip", 'BOOLEAN'); _clip.operation = 'INTERSECT'; _clip.object = o
        bpy.context.view_layer.objects.active = _coat
        bpy.ops.object.modifier_apply(modifier=_clip.name)
        _coatmesh = _coat.data
        bpy.ops.object.select_all(action='DESELECT')
        _coat.select_set(True); o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.join()                        # clipped coating -> cube mesh (coating keeps slot-1 tint)
        if _coatmesh.users == 0:
            bpy.data.meshes.remove(_coatmesh)
    else:
        # PLATE / PELLICLE: a thin coated plate tilted to 45 deg (its normal = the REFLECT direction).
        thick = 0.4 if bs_form == 'PELLICLE' else 2.4
        o = _cube(name, (size * 1.35, size * 1.35, thick), coll)
        o.matrix_world = _z_to(Vector((-1.0, 1.0, 0.0))).to_4x4()          # plate normal -> reflect dir
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)  # bake the 45 deg tilt
        if bs_form != 'PELLICLE':
            _bevel(o, 0.3, 1)
        o.data.materials.clear(); o.data.materials.append(MATS["pbs" if pbs else "bs"]())
        _accent(o, "coatpbs" if pbs else "coatbs",
                lambda c, nrm: (nrm - Vector((-1.0, 1.0, 0.0)).normalized()).length < 0.5)  # coated face
    _tag(o, 'BEAMSPLITTER', split_ratio=split, clear_aperture=size * 0.55, is_pbs=pbs, bs_form=bs_form)
    o.optics.mount_preset = "PBS" if pbs else ""
    h = size * 0.5
    _add_port(o, "IN", 'IN', (-h, 0, 0), (-1, 0, 0), size * 0.55)
    _add_port(o, "OUT", 'OUT', (h, 0, 0), (1, 0, 0), size * 0.55)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), Vector((-1, 1, 0)).normalized(), size * 0.55)
    _set_matrix(o, Vector(loc), _basis(in_dir, reflect_dir))   # +X->in, +Y->reflect
    return o


def detector(name, loc, beam_dir, coll=None, size=22.0):
    """A detector/camera whose sensor faces the incoming beam."""
    o = _sensor_box(name, size, 8.0, coll, active=0.5)    # body + recessed active-area on +Z
    o.data.materials[0] = MATS["det"]()
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


def lens(name, loc, axis, coll=None, focal=100.0, radius=14.0, lens_type='AUTO'):
    depth = 5.0
    # real spherical lens, shaped by the FORM (lens_type): plano-/bi-convex/concave. Curvature is
    # cosmetic (the tracer uses the ABCD focal length), but the form + focal SIGN read correctly.
    o = _revolve(name, _lens_profile(radius, focal, lens_type=lens_type), coll, seg=64, smooth=True)
    o.data.materials.clear(); o.data.materials.append(MATS["lens"]())
    _tag(o, 'LENS', clear_aperture=radius, focal_length=focal, lens_type=lens_type)
    _add_port(o, "IN", 'IN', (0, 0, -depth * 0.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, depth * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))         # optical axis = local +Z -> world axis
    return o


def waveplate(name, loc, axis, coll=None, kind='HWP', fast_axis=0.0, design_wl=None):
    ret = 90.0 if str(kind).upper() == 'QWP' else 180.0      # QWP=90deg, HWP=180deg retardance
    kw = {"retardance_deg": ret, "fast_axis_deg": fast_axis}
    if design_wl is not None:                                # spec the retarder at its arm wavelength
        kw["design_wl"] = design_wl
    o = _inline(name, loc, axis, coll, 'WAVEPLATE', "wp", radius=12.0, depth=3.0, **kw)
    o.optics.mount_preset = kind
    return o


def aperture(name, loc, axis, coll=None, radius=14.0):
    """An iris/aperture stop: a black ring housing with a real central opening + a side lever (ports
    unchanged vs the old solid puck: IN/OUT at +/-depth/2 on the optical axis)."""
    o = _iris(name, radius, coll, depth=3.0)
    o.data.materials.clear(); o.data.materials.append(MATS["ap"]())
    _tag(o, 'APERTURE', clear_aperture=radius)
    _add_port(o, "IN", 'IN', (0, 0, -1.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


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
    """A spatial-filter pinhole: a thin plate with a real tiny central bore (ports unchanged)."""
    o = _bored_disc(name, radius, 2.0, 0.6, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["ap"]())
    _tag(o, 'PINHOLE', clear_aperture=radius)
    _add_port(o, "IN", 'IN', (0, 0, -1.0), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.0), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def isolator(name, loc, axis, coll=None, radius=9.0, length=40.0):
    """A Faraday optical isolator: a barrel with input/output bezels and a raised directional ARROW
    marking the forward (transmission) direction -- the one feature that matters for an isolator."""
    o = _disc(name, radius, length, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["iso"]())
    for sgn in (+1.0, -1.0):                              # input/output aperture bezels
        bz = _bored_disc(name + "_bz%d" % (sgn > 0), radius + 1.2, 2.5, radius * 0.6, coll)
        for v in bz.data.vertices:
            v.co.z += sgn * length * 0.5
        bz.data.materials.append(MATS["bezel"]())
        _join(o, bz)
    ar = bmesh.new()                                     # forward-pointing arrow on the +X flank
    xo, xi = radius + 0.2, radius - 0.8
    tip = ar.verts.new((xo, 0.0, length * 0.24)); bl = ar.verts.new((xo, 4.0, -length * 0.04))
    br = ar.verts.new((xo, -4.0, -length * 0.04))
    tip2 = ar.verts.new((xi, 0.0, length * 0.24)); bl2 = ar.verts.new((xi, 4.0, -length * 0.04))
    br2 = ar.verts.new((xi, -4.0, -length * 0.04))
    ar.faces.new((tip, bl, br)); ar.faces.new((tip2, br2, bl2))
    ar.faces.new((tip, br, br2, tip2)); ar.faces.new((br, bl, bl2, br2)); ar.faces.new((bl, tip, tip2, bl2))
    arrow = _bm_obj(name + "_arr", ar, coll); arrow.data.materials.append(MATS["arrow"]())
    _join(o, arrow)
    _tag(o, 'ISOLATOR', clear_aperture=radius)
    _add_port(o, "IN", 'IN', (0, 0, -length * 0.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, length * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def fiber_collimator(name, loc, direction, coll=None, wavelength=632.8, length=30.0, radius=6.0):
    """A fiber-coupled collimator that launches a beam along `direction` (source-like)."""
    o = _disc(name, radius, length, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["fiber"]())
    # front output bezel + a rear FC connector stub (the defining fiber-input end)
    bz = _bored_disc(name + "_bezel", radius + 1.0, 2.5, radius * 0.5, coll)
    for v in bz.data.vertices:
        v.co.z += length * 0.5
    bz.data.materials.append(MATS["bezel"]())
    _join(o, bz)
    cb = bmesh.new(); _cyl_bm(cb, radius * 0.55, 9.0, 24)
    conn = _bm_obj(name + "_fc", cb, coll)
    for v in conn.data.vertices:
        v.co.z -= length * 0.5 + 4.5
    conn.data.materials.append(MATS["bezel"]())
    _join(o, conn)
    ap = _disc(name + "_ap", radius * 0.45, 1.4, coll)                          # glowing output aperture
    for v in ap.data.vertices:
        v.co.z += length * 0.5 + 0.3
    ap.data.materials.append(MATS["laser"]())
    _join(o, ap)
    _tag(o, 'FIBER_COLLIMATOR', is_source=True, wavelength=wavelength)
    _add_port(o, "OUT", 'OUT', (0, 0, length * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(direction))
    return o


def photodiode(name, loc, beam_dir, coll=None, size=14.0):
    """A point photodiode whose sensor faces the incoming beam; terminates it."""
    o = _sensor_box(name, size, 6.0, coll, active=0.4)   # small round-ish active chip on +Z
    o.data.materials[0] = MATS["det"]()
    _tag(o, 'PHOTODIODE', is_detector=True, clear_aperture=size * 0.5)
    _add_port(o, "IN", 'IN', (0, 0, 3.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
    return o


def power_meter(name, loc, beam_dir, coll=None, size=20.0):
    """A power-meter sensor head facing the incoming beam; terminates it."""
    o = _sensor_box(name, size, 10.0, coll, active=0.62)   # broad thermopile-style active disc
    o.data.materials[0] = MATS["det"]()
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
    _bevel(o, 0.4, 1)
    o.data.materials.clear(); o.data.materials.append(MATS["dichroic"]())
    _accent(o, "coatdich", lambda c, nrm: nrm.z > 0.7)   # the wavelength-selective coated +Z face
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
    o = _grooved_plate(name, size, 5.0, coll)     # ruled ridges on +Z (visible groove hint)
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
    o = _corner_cube(name, size, coll)            # trihedral facets meeting at a rear apex (+Z = axis)
    o.data.materials.clear(); o.data.materials.append(MATS["retro"]())
    _tag(o, 'RETROREFLECTOR', clear_aperture=size * 0.5, reflectivity=0.95)
    _add_port(o, "IN", 'IN', (0, 0, size * 0.4), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-d))    # REFLECT normal anti-parallel to incoming
    return o


def cavity(name, loc, axis, coll=None, spacing_mm=0.05, R=0.9, size=25.0):
    """A Fabry-Perot etalon: two parallel partial-mirror plates + rim spacer (ports unchanged vs the
    old single puck: IN/OUT at +/-4 on the optical axis)."""
    o = _etalon(name, size * 0.5, 2.5, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["bs"]())
    _tag(o, 'CAVITY', clear_aperture=size * 0.5, cavity_spacing_mm=spacing_mm, reflectivity=R)
    _add_port(o, "IN", 'IN', (0, 0, -4.0), (0, 0, -1), size * 0.5)
    _add_port(o, "OUT", 'OUT', (0, 0, 4.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def _pad15(coeffs):
    v = list(coeffs or [])[:15]
    return v + [0.0] * (15 - len(v))


def wavefront_sensor(name, loc, beam_dir, coll=None, size=22.0):
    """A Shack-Hartmann-style modal wavefront sensor; reads the incoming beam's Zernike modes."""
    o = _sensor_box(name, size, 8.0, coll, active=0.62, lenslets=6)   # micro-lens grid on the sensor
    o.data.materials[0] = MATS["det"]()
    _tag(o, 'WAVEFRONT_SENSOR', clear_aperture=size * 0.5)
    _add_port(o, "IN", 'IN', (0, 0, 4.0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))   # IN faces the beam
    return o


def deformable_mirror(name, loc, in_dir, out_dir, coll=None, size=25.0, command=None):
    """A deformable corrector mirror (folds in_dir -> out_dir); subtracts its commanded
    Zernike modes (`command`, in waves) from the wavefront on reflection."""
    n = (Vector(out_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    o = _disc(name, size * 0.5, 4.0, coll)        # round corrector face (Ø1" look)
    _bevel(o, 0.4, 1)
    o.data.materials.clear(); o.data.materials.append(MATS["mirror"]())
    hb = bmesh.new(); _cyl_bm(hb, size * 0.44, 8.0, 40)      # actuator backplane housing
    housing = _bm_obj(name + "_act", hb, coll)
    for v in housing.data.vertices:
        v.co.z -= 6.0
    housing.data.materials.append(MATS["subglass"]())
    _join(o, housing)
    _tag(o, 'DEFORMABLE_MIRROR', clear_aperture=size * 0.5, reflectivity=1.0)
    o.optics.dm_command = _pad15(command)
    _add_port(o, "IN", 'IN', (0, 0, 2.0), (0, 0, 1), size * 0.5)
    _add_port(o, "REFLECT", 'REFLECT', (0, 0, 0), (0, 0, 1), size * 0.5)
    _set_matrix(o, Vector(loc), _z_to(n))     # local +Z (REFLECT normal) -> bisector n
    return o


def aberrator(name, loc, axis, coll=None, modes=None, radius=14.0):
    """An aberrator / 'turbulence' plate that injects a Zernike wavefront error (`modes`, waves)."""
    o = _inline(name, loc, axis, coll, 'ABERRATOR', "wp", radius=radius, depth=3.0)
    o.optics.aberr_spec = _pad15(modes)
    return o


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


def drop_example_object(o):
    """Tear down an example object cleanly: if the user adopted it into a non-example collection,
    just unlink it from the example collection(s); otherwise delete it AND free its mesh datablock
    (do_unlink alone leaves a 0-user orphan mesh that bloats the .blend on every rebuild)."""
    if any(not c.name.startswith("OpticsExample_") for c in o.users_collection):
        for c in list(o.users_collection):
            if c.name.startswith("OpticsExample_"):
                c.objects.unlink(o)
        return
    mesh = o.data if o.type == 'MESH' else None
    bpy.data.objects.remove(o, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def example_collection(name):
    """Fresh collection for an example (removes any prior build of the same name)."""
    c = bpy.data.collections.get(name)
    if c:
        for o in list(c.objects):
            drop_example_object(o)
        bpy.data.collections.remove(c)
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c
