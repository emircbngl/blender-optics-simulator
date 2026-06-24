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

import math

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
    # C5 beam-conditioning apertures
    "blade":  lambda: _mat("OG_blade", (0.62, 0.64, 0.70), metal=0.95, rough=0.18),   # polished razor blade / slit jaws
    "trap":   lambda: _mat("OG_trap", (0.012, 0.012, 0.015), metal=0.1, rough=0.95),   # matte-black conical beam-trap cavity
    "dumpbody": lambda: _mat("OG_dumpbody", (0.10, 0.10, 0.12), metal=0.6, rough=0.4),  # anodized beam-dump housing
    "pol":    lambda: _mat("OG_polarizer", (0.20, 0.70, 0.55), metal=0.1, rough=0.25),
    "filt":   lambda: _mat("OG_filter", (0.95, 0.45, 0.20), metal=0.0, rough=0.20),
    "iso":    lambda: _mat("OG_isolator", (0.30, 0.30, 0.34), metal=0.8, rough=0.35),
    "dichroic": lambda: _mat("OG_dichroic", (0.80, 0.35, 0.70), metal=0.1, rough=0.12),
    "grating": lambda: _mat("OG_grating", (0.55, 0.45, 0.65), metal=0.9, rough=0.20),
    "retro":  lambda: _mat("OG_retro", (0.75, 0.78, 0.85), metal=1.0, rough=0.10),
    "fiber":  lambda: _mat("OG_fiber", (0.40, 0.42, 0.48), metal=0.85, rough=0.30),
    "prism":  lambda: _mat("OG_prism", (0.70, 0.85, 0.98), metal=0.0, rough=0.05),
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
    # D2 realistic iris / pinhole accents (slot 1+, kept by the render pass)
    "irisblade": lambda: _mat("OG_irisblade", (0.018, 0.018, 0.020), metal=0.15, rough=0.92),  # matte-black diaphragm leaves
    "knurl":     lambda: _mat("OG_knurl", (0.14, 0.15, 0.17), metal=0.85, rough=0.42),          # knurled anodized adjuster ring
    "engrave":   lambda: _mat("OG_engrave", (0.78, 0.80, 0.84), metal=0.6, rough=0.40),         # engraved close-arrow / index marks
    "foil":      lambda: _mat("OG_foil", (0.020, 0.020, 0.024), metal=0.25, rough=0.85),        # blackened precision-bore foil
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


def _seg_for_aperture(diameter_mm):
    """Aperture-aware revolve segment count. Small parts (< Ø1" ~ 24 mm) keep the cheap 64-seg ring;
    a Ø1"+ optic scales smoothly up to seg=192 so its silhouette has no visible facets in a close
    render (~0.4 mm facet at Ø1", vs ~1.2 mm at 64). Geometry-only -- ports/trace are unaffected."""
    if diameter_mm < 24.0:
        return 64
    seg = int(round(96.0 * diameter_mm / 24.0))            # 96 at Ø1", scaling with aperture
    return max(96, min(192, seg))


def _revolve(name, profile, coll, seg=96, smooth=True):
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


def _knurled_ring(name, r_in, r_out, depth, coll, grooves=52):
    """A knurled outer adjuster ring (bored to r_in, outer r_out) centred on +Z, with `grooves` (~40-60)
    axial flutes around the rim. Built from CLOSED solids only -- a bored annular tube base + a ring of
    small radial teeth joined to it -- so the result is a clean manifold mesh (the caller puts it on its
    own material slot). The teeth read as machined knurling around the adjuster ring."""
    n = max(40, min(60, int(grooves)))
    base = _bored_disc(name, r_out, depth, r_in, coll, seg=n * 2)   # manifold annular tube (boolean bore)
    for k in range(n):                                              # a ring of small radial knurl teeth
        a = 2.0 * math.pi * k / n
        tb = bmesh.new(); bmesh.ops.create_cube(tb, size=1.0)
        for v in tb.verts:                                         # a thin tooth sticking out past the rim
            v.co = Vector((v.co.x * 0.55, v.co.y * 0.55, v.co.z * (depth * 0.42)))
        tooth = _bm_obj(name + "_t%d" % k, tb, coll)
        tooth.matrix_world = (Matrix.Rotation(a, 4, Vector((0, 0, 1)))
                              @ Matrix.Translation(Vector((r_out + 0.18, 0.0, 0.0))))
        bpy.ops.object.select_all(action='DESELECT')
        tooth.select_set(True); bpy.context.view_layer.objects.active = tooth
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        _join(base, tooth)
    return base


def _iris_blade(name, r_open, depth, ang, coll, blades=12):
    """One diaphragm leaf: a thin matte-black plate covering an annular sector, its straight INNER edge a
    chord tangent to the circle of radius r_open (so the union of `blades` such chords forms the polygonal
    central opening), overlapping its neighbours. Rolled to azimuth `ang` (rad) about +Z, on the front face."""
    bm = bmesh.new()
    span = (2.0 * math.pi / blades) * 1.7              # overlap neighbours (>1 sector) -> closed polygon
    r_out = r_open + 4.6                               # tuck the leaf root under the ring (past the wider bore)
    a0, a1 = -span * 0.5, span * 0.5
    t = depth * 0.26                                   # thin leaf, thick enough to catch light at the bore lip
    z0 = depth * 0.5 - t                               # leaves sit flush on the FRONT face (read, not in shadow)
    # the inner edge is the CHORD at perpendicular distance r_open from the axis (straight blade edge)
    pin = [(r_open / math.cos(a), a) for a in (a0, a1)]          # chord endpoints at radius r_open/cos
    pout = [(r_out, a0), (r_out, a1)]
    quad = pin + [pout[1], pout[0]]
    low = [bm.verts.new((r * math.cos(a), r * math.sin(a), z0)) for (r, a) in quad]
    high = [bm.verts.new((r * math.cos(a), r * math.sin(a), z0 + t)) for (r, a) in quad]
    bm.faces.new(low)
    bm.faces.new(tuple(reversed(high)))
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((low[i], low[j], high[j], high[i]))
    o = _bm_obj(name, bm, coll, smooth=False)
    o.matrix_world = Matrix.Rotation(ang, 4, Vector((0, 0, 1)))
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return o


def _close_arrow(name, r, depth, coll):
    """A small engraved 'close' arrow (a flat chevron) raised on the iris front face near the rim, the
    direction-of-stop-down hint engraved on a real Thorlabs/Newport iris ring."""
    bm = bmesh.new()
    cx = r + 2.4                                       # on the ring band, just outside the opening
    z = depth * 0.5 + 0.05
    w, h = 1.7, 1.1
    pts = [(cx - w, 0.9), (cx, 0.0), (cx - w, -0.9), (cx - w + 0.5, 0.0)]   # chevron (filled arrowhead)
    vs = [bm.verts.new((x, y, z)) for (x, y) in pts]
    vt = [bm.verts.new((x, y, z + 0.25)) for (x, y) in pts]
    bm.faces.new(vs)
    bm.faces.new(tuple(reversed(vt)))
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((vs[i], vs[j], vt[j], vt[i]))
    # short tail bar of the arrow
    return _bm_obj(name, bm, coll, smooth=False)


def _iris(name, r_open, coll, depth=3.6, blades=12):
    """A realistic multi-leaf iris diaphragm. From the optical axis out:
      slot 0  black housing ring (theme-swapped on render) -- outer = opening + 5 mm, central opening r_open
      slot 1  ``blades`` (10-12) overlapping matte-black wedge LEAVES forming the polygonal central opening,
              whose inner straight edges are chords tangent to the circle of radius r_open (so resizing
              r_open moves every leaf -> the opening tracks the aperture)
      slot 2  a knurled anodized adjuster RING (~52 axial flutes) around the rim
      slot 3  an engraved 'close' arrow on the front face
    Purely cosmetic: the aperture() caller sets the ports (IN/OUT on the optical axis) and clear_aperture =
    r_open, so the tracer is untouched. The accent slots (1-3) are kept by the realistic-render pass."""
    # the metal housing is bored WIDER than r_open so the matte-black LEAVES (inner chord at r_open) overhang
    # the bore lip and form the visible limiting polygon -- exactly how a real iris reads (the leaves, not the
    # ring, are the aperture). The optical opening + ports are r_open, set by the caller (unchanged).
    o = _bored_disc(name, r_open + 5.0, depth, r_open * 1.2, coll)  # slot 0 housing (caller may overwrite)
    o.data.materials.append(MATS["ap"]())                         # slot 0 black housing ring (theme-swapped)

    def _add_slot(builder, matkey):
        sub = builder()
        base = len(o.data.polygons)
        _join(o, sub)
        idx = len(o.data.materials)
        o.data.materials.append(MATS[matkey]())
        for p in o.data.polygons[base:]:
            p.material_index = idx

    nb = max(10, min(12, int(blades)))
    for k in range(nb):                                           # slot 1: the diaphragm leaves
        _add_slot(lambda k=k: _iris_blade(name + "_leaf%d" % k, r_open, depth,
                                          2.0 * math.pi * k / nb, coll, blades=nb), "irisblade")
    _add_slot(lambda: _knurled_ring(name + "_knurl", r_open + 4.7, r_open + 5.0, depth, coll),
              "knurl")                                            # slot 2: knurled adjuster ring
    _add_slot(lambda: _close_arrow(name + "_arrow", r_open, depth, coll), "engrave")   # slot 3: close-arrow
    return o


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


def _prism_triangle_yz(apex_deg, face_mm):
    """Cross-section (in the local Y-Z plane) of a dispersing prism with refracting apex angle ``apex_deg``
    and slant-face length ``face_mm``: apex at the TOP (+Y), base at the bottom, two equal slant faces.
    Returns [(y,z) ...] for apex, base-left (-Z), base-right (+Z). The entry (left) face outward normal is
    (0, sin(A/2), -cos(A/2)) and the exit (right) (0, sin(A/2), +cos(A/2)) -- the frame the tracer refracts
    in (in-glass min-deviation ray along +Z)."""
    A = math.radians(apex_deg)
    zb = face_mm * math.sin(A / 2.0)       # base half-width
    H = face_mm * math.cos(A / 2.0)        # apex height above base
    return [(H * 0.5, 0.0), (-H * 0.5, -zb), (-H * 0.5, zb)]


def _littrow_triangle_yz(apex_deg, face_mm):
    """Cross-section of a Littrow (autocollimating) prism in the local Y-Z plane: a right-triangle whose
    COATED back face is perpendicular to the in-glass +Z ray (normal incidence -> retroreflection) and whose
    entry face is tilted by the refracting angle ``apex_deg`` (alpha). Returns [(y,z) ...] in CCW winding =
    A (top of coated face), B (bottom of coated face), E (far entry vertex). The COATED face (A->B) has
    outward normal (0, 0, +1); the ENTRY face (A->E) has outward normal (0, sin alpha, -cos alpha)."""
    a = math.radians(apex_deg)
    s = face_mm
    h = s * 0.5 * math.sin(a)              # half-height of the coated face
    zc = s * 0.4                           # coated face at z = +zc (perpendicular to the in-glass +Z ray)
    A = (h, zc)
    B = (-h, zc)
    E = (A[0] - s * math.cos(a), A[1] - s * math.sin(a))
    return [A, B, E]


def _tri_prism(name, apex_deg, face_mm, depth_mm, coll):
    """A triangular dispersing prism: the _prism_triangle_yz cross-section extruded along local X by
    ``depth_mm`` (the prism's clear height). +Z is the in-glass optical axis, +Y the apex, X the bar axis."""
    (ya, za), (yl, zl), (yr, zr) = _prism_triangle_yz(apex_deg, face_mm)
    hx = depth_mm * 0.5
    bm = bmesh.new()
    # two triangular end caps at x=-hx and x=+hx, joined into a solid bar
    front = [bm.verts.new((-hx, ya, za)), bm.verts.new((-hx, yl, zl)), bm.verts.new((-hx, yr, zr))]
    back = [bm.verts.new((hx, ya, za)), bm.verts.new((hx, yl, zl)), bm.verts.new((hx, yr, zr))]
    bm.faces.new((front[0], front[2], front[1]))           # -X cap
    bm.faces.new((back[0], back[1], back[2]))              # +X cap
    for i in range(3):                                     # three rectangular side faces (entry/exit/base)
        j = (i + 1) % 3
        bm.faces.new((front[i], front[j], back[j], back[i]))
    return _bm_obj(name, bm, coll, smooth=False)


def _pellin_broca_quad_yz(face_mm):
    """Cross-section of a Pellin-Broca prism (four-sided block, apex angles 90/75/135/60). A beam enters the
    AB face near Brewster, refracts, totally-internally-reflects off the bottom hypotenuse, and exits the BC
    face deviated by a constant 90 deg for the design wavelength. Built in the local Y-Z plane with the same
    +Z optical-axis convention; the mesh is a faithful 4-vertex polygon (TIR fold modelled by the tracer)."""
    s = face_mm
    # A clean P-B silhouette: entry + exit faces at right angles, a long TIR hypotenuse. Coordinates chosen
    # so the entry (left) face outward normal tilts back/-Z and the exit (top/+Z) face tilts forward/+Z.
    return [(0.55 * s, -0.45 * s), (0.55 * s, 0.55 * s), (-0.45 * s, 0.55 * s), (-0.75 * s, -0.45 * s)]


def _amici_quad_yz(face_mm):
    """Cross-section of an Amici (direct-vision) doublet block: a trapezoid that reads as a cemented
    crown+flint pair. Entry face (verts[3]->verts[0]) and exit face (verts[1]->verts[2]) are the outer
    glass-air faces; the cemented crown/flint diagonal runs through the body (modelled by the tracer)."""
    s = face_mm
    return [(0.5 * s, -0.5 * s), (0.5 * s, 0.5 * s), (-0.35 * s, 0.6 * s), (-0.55 * s, -0.5 * s)]


def _quad_prism(name, quad_yz, depth_mm, coll):
    """A four-sided prism bar: the quad_yz cross-section extruded along local X by ``depth_mm``."""
    return _poly_prism(name, quad_yz, depth_mm, coll)


# --- C4 beam-ROUTING prism geometry -----------------------------------------
# A routing prism is a glass solid whose internal interaction is one or more PLANE REFLECTIONS off internal
# mirror faces (geometry.reflect, the verified reflection law), bracketed by the C3 entry/exit Snell. Each
# builder below returns a dict the prism() builder consumes:
#   poly_yz   : the cross-section polygon (Y-Z plane, CCW) extruded along local X -> the cosmetic glass bar
#   d_in_local: the EXTERNAL incoming beam direction in the prism's local frame (so axis = that beam)
#   entry/exit: (position, outward-normal) of the air-glass faces (entry normal faces the incoming beam)
#   folds     : ordered [(name, position, inward-mirror-normal), ...] internal reflecting faces
# Convention: the in-glass chief ray runs along local +Z between folds; +Y is "up", local X is the bar axis.
# Normals are 3-vectors in the X=0 plane. The deflection is a fixed product of reflections (no dispersion).

def _routing_prism_geom(prism_type, face_mm):
    """Local-frame geometry of a C4 routing prism (see the section header). Returns the dict the prism()
    builder turns into a mesh + ports. The chief ray enters the entry face, folds off the listed internal
    faces (geometry.reflect, in order), and exits the exit face -- a fixed product of plane reflections."""
    s = face_mm
    h = s * 0.5
    if prism_type == 'RIGHT_ANGLE':
        # Right-triangle: beam in +Z through the back (entry) face, one 45 deg hypotenuse fold sends it to
        # +Y, out the top (exit) face. 1 reflection -> 90 deg deflection, image handedness FLIPS.
        # Verts (Y,Z): bottom-back B(-h,-h), bottom-front... use a clean right triangle.
        poly = [(-h, -h), (h, -h), (-h, h)]            # right-angle at (-h,-h); hypotenuse from (h,-h)->(-h,h)
        d_in = Vector((0.0, 0.0, 1.0))
        entry = (Vector((0.0, 0.0, -h)), Vector((0.0, 0.0, -1.0)))     # back face, normal -Z (beam enters +Z)
        nfold = Vector((0.0, 1.0, -1.0)).normalized()                 # hypotenuse: reflect(+Z)=+Y
        fold_pt = Vector((0.0, 0.0, 0.0))                             # on the hypotenuse, on the +Z ray
        folds = [("FOLD1", fold_pt, nfold)]
        exit = (Vector((0.0, h, 0.0)), Vector((0.0, 1.0, 0.0)))       # top face, normal +Y (beam exits +Y)
    elif prism_type == 'PENTA':
        # Pentagonal: beam in +Z, two mirror faces at a fixed 45 deg DIHEDRAL fold it to -Y. The 90 deg
        # deflection is INVARIANT under whole-prism tilt about the bar axis (the defining penta property:
        # two mirrors at dihedral beta rotate any in-plane ray by 2*beta = 90 deg). Parity PRESERVED.
        n1 = Vector((0.0, math.cos(math.radians(110.0)), math.sin(math.radians(110.0))))   # face 1 normal
        n2 = Vector((0.0, math.cos(math.radians(155.0)), math.sin(math.radians(155.0))))   # face 2 (dihedral 45)
        d_in = Vector((0.0, 0.0, 1.0))
        entry = (Vector((0.0, 0.0, -h)), Vector((0.0, 0.0, -1.0)))     # entry face normal -Z
        # fold 1 sits on the +Z ray at z=0; the mid ray then runs to fold 2, placed along that mid direction.
        f1 = Vector((0.0, 0.0, 0.0))
        mid = (Vector((0.0, 0.0, 1.0)) - 2.0 * Vector((0.0, 0.0, 1.0)).dot(n1) * n1).normalized()
        f2 = f1 + mid * (s * 0.45)
        folds = [("FOLD1", f1, n1), ("FOLD2", f2, n2)]
        exit = (Vector((0.0, -h, 0.0)), Vector((0.0, -1.0, 0.0)))      # exit face normal -Y (out -Y, 90 deg)
        # pentagon silhouette (Y,Z) enclosing the two fold faces + the entry/exit; cosmetic.
        poly = [(-h, -h), (h * 0.2, -h), (h, -h * 0.2), (h * 0.2, h), (-h, h * 0.2)]
    elif prism_type == 'RHOMBOID':
        # Parallelogram: two PARALLEL 45 deg faces. +Z in -> fold1 (+Z->+Y) -> fold2 (+Y->+Z) -> out +Z.
        # Output is EXACTLY PARALLEL to the input (0 deg deviation); the beam is laterally displaced in +Y by
        # the face separation. 2 parallel reflections -> parity PRESERVED.
        d_in = Vector((0.0, 0.0, 1.0))
        sep = s * 0.7                                                  # lateral offset between the two faces
        n1 = Vector((0.0, 1.0, -1.0)).normalized()                    # reflect(+Z)=+Y
        n2 = Vector((0.0, -1.0, 1.0)).normalized()                    # parallel to n1, reflect(+Y)=+Z
        f1 = Vector((0.0, -sep * 0.5, 0.0))
        f2 = Vector((0.0, sep * 0.5, 0.0))
        folds = [("FOLD1", f1, n1), ("FOLD2", f2, n2)]
        entry = (Vector((0.0, -sep * 0.5, -h)), Vector((0.0, 0.0, -1.0)))   # entry face (lower), normal -Z
        exit = (Vector((0.0, sep * 0.5, h)), Vector((0.0, 0.0, 1.0)))       # exit face (upper), normal +Z
        # parallelogram cross-section: a slanted bar from lower-back to upper-front.
        poly = [(-sep * 0.5 - h * 0.5, -h), (-sep * 0.5 + h * 0.5, -h),
                (sep * 0.5 + h * 0.5, h), (sep * 0.5 - h * 0.5, h)]
    elif prism_type == 'DOVE':
        # Trapezoid: the beam enters the tilted left face, the chief ray runs along +Z inside, TIRs off the
        # long bottom face (normal +Y) -- which leaves the chief-ray DIRECTION +Z (in-line, 0 deg deviation) --
        # and exits the tilted right face. The through image ROTATES at 2x the prism roll (handled by the
        # tracer via prism_roll_deg; geometric 2x-reduction of the in-plane reflection law). 1 reflection.
        d_in = Vector((0.0, 0.0, 1.0))                                # design beam in-line along +Z
        a = math.radians(45.0)
        nE = Vector((0.0, math.sin(a), -math.cos(a)))                 # entry (left) face tilted 45 deg
        nO = Vector((0.0, math.sin(a), math.cos(a)))                  # exit (right) face tilted 45 deg
        entry = (Vector((0.0, h * 0.5, -h)), nE)
        exit = (Vector((0.0, h * 0.5, h)), nO)
        folds = [("FOLD1", Vector((0.0, -h, 0.0)), Vector((0.0, 1.0, 0.0)))]   # long bottom TIR face, normal +Y
        # Dove trapezoid (Y,Z): wide bottom, short top, 45 deg end faces.
        top = s * 0.25
        poly = [(-h, -h), (-h, h), (h, h - (h - top)), (h, -h)]
        # simpler clean trapezoid: bottom long, slanted ends
        poly = [(-h, -h - top), (h, -h), (h, h), (-h, h + top)]
    else:  # ROOF (Amici roof): 90 deg deflect via a 90 deg roof (two faces), retro-ish parity flip + split.
        # Two roof faces symmetric about the Y-Z plane, each 45 deg from the virtual (right-angle) hypotenuse;
        # the chief ray on the ridge reflects off both -> net +Z->+Y (90 deg), 2 reflections.
        d_in = Vector((0.0, 0.0, 1.0))
        n1 = Vector((-1.0, 1.0, -1.0)).normalized()                   # roof face 1 (off-axis in -X)
        n2 = Vector((1.0, 1.0, -1.0)).normalized()                    # roof face 2 (off-axis in +X)
        # normalize the X component to the verified (+-0.707,0.5,-0.5):
        n1 = Vector((-math.sqrt(0.5), 0.5, -0.5)).normalized()
        n2 = Vector((math.sqrt(0.5), 0.5, -0.5)).normalized()
        entry = (Vector((0.0, 0.0, -h)), Vector((0.0, 0.0, -1.0)))
        f1 = Vector((0.0, 0.0, 0.0))
        mid = (Vector((0.0, 0.0, 1.0)) - 2.0 * Vector((0.0, 0.0, 1.0)).dot(n1) * n1).normalized()
        f2 = f1 + mid * (s * 0.2)
        folds = [("FOLD1", f1, n1), ("FOLD2", f2, n2)]
        exit = (Vector((0.0, h, 0.0)), Vector((0.0, 1.0, 0.0)))
        poly = [(-h, -h), (h, -h), (h, 0.0), (-h, h)]                 # right-angle-ish silhouette
    return {"poly": poly, "d_in": d_in, "entry": entry, "exit": exit, "folds": folds}


def _tri_prism_yz(name, tri_yz, depth_mm, coll):
    """A triangular prism bar from an EXPLICIT (y,z) cross-section (e.g. the asymmetric Littrow right-triangle),
    extruded along local X by ``depth_mm``."""
    return _poly_prism(name, tri_yz, depth_mm, coll)


def _poly_prism(name, poly_yz, depth_mm, coll):
    """A prism bar: the convex polygon cross-section ``poly_yz`` (CCW in the Y-Z plane) extruded along local
    X by ``depth_mm``, capped both ends. Shared by the quad / Littrow prism builders."""
    hx = depth_mm * 0.5
    bm = bmesh.new()
    front = [bm.verts.new((-hx, y, z)) for (y, z) in poly_yz]
    back = [bm.verts.new((hx, y, z)) for (y, z) in poly_yz]
    bm.faces.new(tuple(reversed(front)))                  # -X cap
    bm.faces.new(tuple(back))                             # +X cap
    nq = len(poly_yz)
    for i in range(nq):
        j = (i + 1) % nq
        bm.faces.new((front[i], front[j], back[j], back[i]))
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


def _mirror_profile(radius, curve, sag=2.0, thick=6.0):
    """Half cross-section of a curved mirror: a spherical front cap (CONVEX bulges out, CONCAVE dishes
    in) over a flat substrate back. Cosmetic -- the FOCAL power (f=R/2) is applied by the tracer from
    radius_curv -- but it makes a focusing mirror visibly curved."""
    import math
    R = radius; N = 18
    ze = thick * 0.5
    zc = ze + sag if curve == 'CONVEX' else ze - sag
    def zf(r):
        return ze + (zc - ze) * math.sqrt(max(0.0, 1.0 - (r / R) ** 2))
    front = [(R * i / N, zf(R * i / N)) for i in range(N + 1)]          # curved front, axis -> edge
    back = [(R * i / N, -thick * 0.5) for i in range(N, -1, -1)]        # flat substrate back
    return front + back


def mirror(name, loc, in_dir, out_dir, coll=None, size=25.0, mirror_curve='FLAT', radius_curv=0.0):
    """A fold mirror turning a beam from in_dir to out_dir. ``mirror_curve`` (FLAT/CONCAVE/CONVEX) gives
    it a curved face; with radius_curv set, the tracer applies f=R/2 focal power on reflection."""
    n = (Vector(out_dir).normalized() - Vector(in_dir).normalized())
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    if mirror_curve in ('CONCAVE', 'CONVEX'):
        o = _revolve(name, _mirror_profile(size * 0.5, mirror_curve), coll,
                     seg=_seg_for_aperture(size), smooth=True)
    else:
        o = _disc(name, size * 0.5, 6.0, coll)    # Ø1" substrate, 6 mm thick; +Z = coated front face
        _bevel(o, 0.5, 2)
    o.data.materials.clear(); o.data.materials.append(MATS["mirror"]())
    # only the +Z front is the reflective coating; the back + ground edge read as bare glass substrate
    _accent(o, "subglass", lambda c, nrm: nrm.z < 0.55)
    _tag(o, 'MIRROR', clear_aperture=size * 0.5, reflectivity=1.0,
         mirror_curve=mirror_curve, radius_curv=radius_curv)
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
    o = _revolve(name, _lens_profile(radius, focal, lens_type=lens_type), coll,
                 seg=_seg_for_aperture(2.0 * radius), smooth=True)
    o.data.materials.clear(); o.data.materials.append(MATS["lens"]())
    _tag(o, 'LENS', clear_aperture=radius, focal_length=focal, lens_type=lens_type)
    _add_port(o, "IN", 'IN', (0, 0, -depth * 0.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, depth * 0.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))         # optical axis = local +Z -> world axis
    return o


def waveplate(name, loc, axis, coll=None, kind='HWP', fast_axis=0.0, design_wl=None, waveplate_order='ZERO'):
    ret = 90.0 if str(kind).upper() == 'QWP' else 180.0      # QWP=90deg, HWP=180deg retardance
    # the ORDER only sets the mesh thickness cue (zero-order thin, multi/achromatic thicker); the ports
    # stay at +/-1.5 so the Jones interaction plane -- and the trace -- is unchanged.
    depth = {'ZERO': 2.0, 'MULTI': 5.0, 'ACHROMATIC': 5.0}.get(waveplate_order, 3.0)
    o = _disc(name, 12.0, depth, coll)
    o.data.materials.clear(); o.data.materials.append(MATS["wp"]())
    _tag(o, 'WAVEPLATE', clear_aperture=12.0, retardance_deg=ret, fast_axis_deg=fast_axis,
         waveplate_order=waveplate_order)
    if design_wl is not None:                                # spec the retarder at its arm wavelength
        o.optics.design_wl = design_wl
    o.optics.mount_preset = kind
    _add_port(o, "IN", 'IN', (0, 0, -1.5), (0, 0, -1), 12.0)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.5), (0, 0, 1), 12.0)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def aperture(name, loc, axis, coll=None, radius=14.0):
    """An iris/aperture stop: a realistic multi-leaf diaphragm -- a black housing ring, 10-12 matte-black
    wedge LEAVES forming the polygonal opening (tracking ``radius``), a knurled adjuster ring and an
    engraved close-arrow. Ports are unchanged vs the old solid puck: IN/OUT at +/-1.5 on the optical axis,
    clear_aperture = radius -- so the trace is byte-identical. ``iris_blades`` is a per-object cosmetic
    override (10-12); the default 12 reads as a standard iris."""
    blades = 12
    o = _iris(name, radius, coll, depth=3.0, blades=blades)
    o.data.materials[0] = MATS["ap"]()                            # slot 0 housing only (accents 1-3 kept)
    _tag(o, 'APERTURE', clear_aperture=radius)
    o.optics.iris_blades = blades
    _add_port(o, "IN", 'IN', (0, 0, -1.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def crystal(name, loc, beam_dir, coll=None, size=14.0, nl_process='NONE'):
    """A nonlinear (e.g. BBO) crystal block. With nl_process SHG/SPDC it is a real TRANSMISSIVE chi(2)
    element (IN/OUT on the pump axis) and the tracer emits the converted beam(s): SHG at lambda/2, SPDC
    degenerate signal+idler at 2*lambda (both formulas oracle-VERIFIED). With nl_process NONE it stays a
    pump-dump (DETECTOR terminal) -- the legacy behavior the Bell example relies on."""
    o = _cube(name, (size * 0.6, size * 0.6, size), coll)
    o.data.materials.clear(); o.data.materials.append(MATS["bbo"]())
    if nl_process in ('SHG', 'SPDC'):
        _tag(o, 'CRYSTAL', clear_aperture=size, nl_process=nl_process)
        _add_port(o, "IN", 'IN', (0, 0, -size * 0.5), (0, 0, -1), size)
        _add_port(o, "OUT", 'OUT', (0, 0, size * 0.5), (0, 0, 1), size)
        _set_matrix(o, Vector(loc), _z_to(Vector(beam_dir).normalized()))   # +Z = pump propagation
    else:
        _tag(o, 'DETECTOR', clear_aperture=size)
        _add_port(o, "IN", 'IN', (0, 0, size * 0.5), (0, 0, 1), size)
        _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
    return o


# DIN/JIS magnification colour-code ring (the band that identifies an objective at a glance)
_OBJ_RING = {4: (0.80, 0.12, 0.12), 10: (0.95, 0.80, 0.20), 20: (0.25, 0.70, 0.35),
             40: (0.30, 0.50, 0.95), 60: (0.20, 0.80, 0.80), 100: (0.95, 0.95, 0.90)}


def objective(name, loc, axis, coll=None, mag=10.0, na=0.25, wd=10.0, correction='INFINITY', long_wd=False):
    """A microscope objective: a stepped anodized barrel (body -> shoulder -> nose) with the DIN
    magnification colour ring. The OUT (+Z) faces the tube lens, the IN (-Z nose) faces the sample. The
    tracer focuses it with f_obj = f_tube/M (infinity) -- VERIFIED microscope-objective-magnification."""
    R, L = 11.0, 42.0

    def _seg(r1, r2, depth, zoff):
        b = bmesh.new()
        bmesh.ops.create_cone(b, cap_ends=True, segments=40, radius1=r1, radius2=r2, depth=depth)
        ob = _bm_obj(name + "_s", b, coll)
        for v in ob.data.vertices:
            v.co.z += zoff
        return ob

    o = _seg(R, R, L * 0.5, L * 0.25)                      # back body (+Z, toward the tube lens)
    _join(o, _seg(R, R * 0.6, L * 0.30, -L * 0.05))        # shoulder taper
    _join(o, _seg(R * 0.6, R * 0.32, L * 0.22, -L * 0.30))  # nose (toward the sample)
    o.data.materials.clear(); o.data.materials.append(MATS["iso"]())   # dark anodized barrel
    ck = min(_OBJ_RING, key=lambda k: abs(k - mag))        # nearest standard magnification colour
    ring = _bored_disc(name + "_ring", R * 1.03, 3.2, R * 0.72, coll)
    for v in ring.data.vertices:
        v.co.z += -L * 0.02
    ring.data.materials.append(_mat("OG_objring_%d" % ck, _OBJ_RING[ck], metal=0.3, rough=0.4))
    _join(o, ring)
    _tag(o, 'OBJECTIVE', clear_aperture=R, obj_mag=mag, obj_na=na, obj_wd=wd,
         obj_correction=correction, obj_long_wd=long_wd)
    _add_port(o, "IN", 'IN', (0, 0, -L * 0.45), (0, 0, -1), R)     # nose faces the sample
    _add_port(o, "OUT", 'OUT', (0, 0, L * 0.5), (0, 0, 1), R)      # back faces the tube lens
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def aom(name, loc, axis, coll=None, freq_mhz=80.0, sound_mps=4200.0, efficiency=0.85, size=10.0):
    """An acousto-optic modulator (Bragg cell): a clear TeO2-style crystal block with a piezo transducer
    bonded to its -Y face (the acoustic source, launching the index grating along +Y) plus an RF stub. The
    beam passes IN/OUT on -/+Z; the tracer diffracts the +1 order at theta = lambda*f_a/v_s in the Y-Z plane
    and frequency-shifts it by f_a (VERIFIED acousto-optic-bragg-deflection)."""
    import math
    w, h, L = size, size * 1.4, size * 2.2                 # block: tall in Y so the acoustic column fits
    o = _cube(name, (w, h, L), coll)                       # +Z = beam propagation
    _bevel(o, 0.5, 1)
    o.data.materials.clear(); o.data.materials.append(MATS["index"]())     # clear crystal (slot 0; theme-swapped)
    trans = _cube(name + "_xducer", (w * 0.9, 1.6, L * 0.8), coll)          # piezo transducer on the -Y face
    for v in trans.data.vertices:
        v.co.y += -(h * 0.5 + 0.8)
    trans.data.materials.append(_mat("OG_aom_xducer", (0.72, 0.55, 0.20), metal=0.9, rough=0.3))  # gold bond
    _join(o, trans)
    stub = _disc(name + "_rf", 1.8, 5.0, coll)                              # RF coax stub feeding the transducer
    stub.data.transform(Matrix.Rotation(math.radians(90.0), 4, 'X'))       # axis along Y
    for v in stub.data.vertices:
        v.co.y += -(h * 0.5 + 4.0)
    stub.data.materials.append(MATS["iso"]())
    _join(o, stub)
    _tag(o, 'AOM', clear_aperture=w, aom_freq_mhz=freq_mhz, aom_sound_mps=sound_mps, aom_efficiency=efficiency)
    _add_port(o, "IN", 'IN', (0, 0, -L * 0.5), (0, 0, -1), w)
    _add_port(o, "OUT", 'OUT', (0, 0, L * 0.5), (0, 0, 1), w)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def prism(name, loc, axis, coll=None, prism_type='EQUILATERAL', apex_deg=60.0,
          glass='N-SF11', glass2='N-SF11', design_wl=589.3, face_mm=26.0, depth_mm=24.0, roll_deg=0.0):
    """A dispersing prism (C3): a refractive material-dispersion element that fans a white beam into a
    spectrum (each wavelength refracts by a different angle via Snell + the glass's n(lambda)).

    ``axis`` is the INCOMING beam direction. The prism is oriented so the design wavelength enters at the
    symmetric MINIMUM-DEVIATION incidence (the equilateral spectrometer condition); the tracer then refracts
    the chief ray at the entry face, propagates the glass OPL, and refracts (or TIRs / back-reflects) at the
    exit face per ``prism_type``. The local frame keeps the in-glass ray along +Z (apex +Y, bar along X);
    the entry/exit port normals carry the true face geometry so the world trace bends correctly under any
    placement. ``roll_deg`` extra-rolls the prism about its bar axis (off-min-deviation studies)."""
    from . import physics
    A = float(apex_deg)
    n_d = physics.sellmeier_n(design_wl, glass)
    b = math.radians(A / 2.0)

    # --- C4 beam-ROUTING prisms (right-angle / penta / Dove / roof / rhomboid): a glass solid whose internal
    # interaction is a fixed product of PLANE REFLECTIONS (the verified reflection law), not material dispersion.
    # All geometry comes from _routing_prism_geom; the FOLD faces are carried as REFLECT ports the tracer reads. ---
    if prism_type in ('RIGHT_ANGLE', 'PENTA', 'DOVE', 'ROOF', 'RHOMBOID'):
        g = _routing_prism_geom(prism_type, face_mm)
        o = _poly_prism(name, g["poly"], depth_mm, coll)
        o.data.materials.clear(); o.data.materials.append(MATS["prism"]())
        _bevel(o, 0.3, 1)
        in_pos, nE = g["entry"]
        out_pos, nO = g["exit"]
        _tag(o, 'PRISM', clear_aperture=face_mm * 0.5, prism_type=prism_type, apex_angle_deg=A,
             prism_glass=glass, prism_glass2=glass2, prism_design_wl=design_wl, prism_roll_deg=roll_deg)
        _add_port(o, "IN", 'IN', in_pos, nE, face_mm * 0.5)
        _add_port(o, "OUT", 'OUT', out_pos, nO, face_mm * 0.5)
        for (fname, fpos, fnrm) in g["folds"]:             # internal mirror faces (role REFLECT)
            _add_port(o, fname, 'REFLECT', fpos, fnrm, face_mm * 0.5)
        # orient: map the local incoming-beam direction onto the world ``axis`` (so axis = the incoming beam).
        d_in_local = g["d_in"]
        R = Vector(d_in_local).normalized().rotation_difference(Vector(axis).normalized()).to_matrix()
        if roll_deg:                                        # roll about the optical (incoming-beam) axis
            R = R @ Matrix.Rotation(math.radians(roll_deg), 3, Vector(d_in_local).normalized())
        # place so the ENTRY-FACE CENTER lands at ``loc`` (a beam aimed at loc along axis hits the entry face).
        _set_matrix(o, Vector(loc) - (R @ in_pos), R)
        return o

    tir_n = None                                           # Pellin-Broca internal TIR-fold face normal (else unused)
    tir_pos = None
    cem_n = None                                           # Amici cemented crown/flint interface normal (else unused)
    cem_pos = None
    if prism_type == 'PELLIN_BROCA':
        # A constant-90-deg P-B block: ENTRY face tilted +te so the in-glass ray is +Z; a TIR face folds it to
        # +Y; an EXIT face tilted so the net deviation is exactly 90 deg at the design wavelength (and disperses
        # around it). The functional face normals are computed from the design index; the quad mesh is cosmetic.
        te = math.radians(20.0)
        nE = Vector((0.0, math.sin(te), -math.cos(te)))
        d_back0 = physics.refract_dir((0.0, 0.0, -1.0), (nE.x, nE.y, nE.z), n_d, 1.0)
        din0 = Vector((-d_back0[0], -d_back0[1], -d_back0[2])).normalized() if d_back0 else Vector((0, 0, 1))
        dg0 = Vector(physics.refract_dir((din0.x, din0.y, din0.z), (nE.x, nE.y, nE.z), 1.0, n_d))
        tir_n = (dg0 - Vector((0.0, 1.0, 0.0))).normalized()   # folds the in-glass +Z-ish ray to +Y
        nO = Vector((0.0, math.cos(te), math.sin(te)))     # exit face (lets the +Y ray out, net 90 deg)
        o = _quad_prism(name, _pellin_broca_quad_yz(face_mm), depth_mm, coll)
        quad = _pellin_broca_quad_yz(face_mm)
        in_pos = _edge_mid(quad, 3, 0)
        out_pos = _edge_mid(quad, 1, 2)
        tir_pos = _edge_mid(quad, 0, 1)                    # bottom hypotenuse (the TIR-fold face)
    elif prism_type == 'LITTROW':
        # right-triangle Littrow: COATED face (A->B) perpendicular to the in-glass +Z ray (-> retroreflect),
        # ENTRY face (A->E) tilted by the refracting angle A. The IN port is the entry face; the OUT port is
        # the coated back face (the tracer reflects off it and exits back through the entry face).
        o = _tri_prism_yz(name, _littrow_triangle_yz(A, face_mm), depth_mm, coll)
        tri = _littrow_triangle_yz(A, face_mm)
        nE = _edge_outward_normal(tri, 0, 2)              # entry face A->E
        nO = _edge_outward_normal(tri, 0, 1)              # coated face A->B (outward +Z)
        in_pos = _edge_mid(tri, 0, 2)
        out_pos = _edge_mid(tri, 0, 1)
    elif prism_type == 'AMICI':
        # Direct-vision (Amici) crown+flint doublet: 3 interfaces air->crown (entry), crown->flint (cemented
        # diagonal), flint->air (exit). The face tilts are tuned so the DESIGN wavelength exits UNDEVIATED
        # (net deviation ~0) while the spectrum still fans -- the headline direct-vision behaviour. The
        # cemented-interface normal is carried as a 'CEMENT' port (role TRANSMIT) so the tracer chains the two
        # glasses (prism_glass = crown, prism_glass2 = flint). A trapezoid mesh stands in for the doublet.
        te = math.radians(39.0); tc = math.radians(-59.0); tx = math.radians(-10.0)
        nE = Vector((0.0, math.sin(te), -math.cos(te)))
        cem_n = Vector((0.0, math.sin(tc), -math.cos(tc)))
        nO = Vector((0.0, math.sin(tx), -math.cos(tx)))
        o = _quad_prism(name, _amici_quad_yz(face_mm), depth_mm, coll)
        quad = _amici_quad_yz(face_mm)
        in_pos = _edge_mid(quad, 3, 0)
        out_pos = _edge_mid(quad, 1, 2)
        cem_pos = Vector((0.0, 0.0, 0.0))                 # cemented diagonal through the block centre
    else:
        o = _tri_prism(name, A, face_mm, depth_mm, coll)
        nE = Vector((0.0, math.sin(b), -math.cos(b)))      # entry (left) face outward normal
        nO = Vector((0.0, math.sin(b), math.cos(b)))       # exit (right) face outward normal
        tri = _prism_triangle_yz(A, face_mm)
        in_pos = Vector((0.0, (tri[0][0] + tri[1][0]) * 0.5, (tri[0][1] + tri[1][1]) * 0.5))   # entry-face mid
        out_pos = Vector((0.0, (tri[0][0] + tri[2][0]) * 0.5, (tri[0][1] + tri[2][1]) * 0.5))  # exit-face mid
    o.data.materials.clear(); o.data.materials.append(MATS["prism"]())
    _bevel(o, 0.3, 1)

    # local INCOMING beam direction for the design wavelength's design condition.
    if prism_type == 'AMICI':
        # Amici tilts were derived for a local +Z input giving zero net deviation, so the design beam IS +Z.
        d_in_local = Vector((0.0, 0.0, 1.0))
    else:
        # EQUILATERAL / LITTROW / PELLIN_BROCA: the in-glass +Z ray refracts BACKWARD out the entry face to
        # give the external incoming beam landing the design wavelength at min deviation / autocollimation /
        # the 90 deg P-B fold. The chief-ray fan stays exact (each face refraction uses the true world ports).
        d_back = physics.refract_dir((0.0, 0.0, -1.0), (nE.x, nE.y, nE.z), n_d, 1.0)
        if d_back is None:
            d_in_local = Vector((0.0, 0.0, 1.0))           # degenerate fallback (shouldn't happen for real glass)
        else:
            d_in_local = Vector((-d_back[0], -d_back[1], -d_back[2])).normalized()

    _tag(o, 'PRISM', clear_aperture=face_mm * 0.5, prism_type=prism_type, apex_angle_deg=A,
         prism_glass=glass, prism_glass2=glass2, prism_design_wl=design_wl)
    _add_port(o, "IN", 'IN', in_pos, nE, face_mm * 0.5)
    _add_port(o, "OUT", 'OUT', out_pos, nO, face_mm * 0.5)
    if tir_n is not None:                                  # Pellin-Broca internal TIR-fold face (role TRANSMIT)
        _add_port(o, "TIR", 'TRANSMIT', tir_pos if tir_pos is not None else Vector((0, 0, 0)),
                  tir_n, face_mm * 0.5)
    if cem_n is not None:                                  # Amici cemented crown/flint interface (role TRANSMIT)
        _add_port(o, "CEMENT", 'TRANSMIT', cem_pos if cem_pos is not None else Vector((0, 0, 0)),
                  cem_n, face_mm * 0.5)
    # orient: map the local incoming-beam direction onto the world axis (so `axis` = the incoming beam).
    # Optional ``roll_deg`` rolls the prism about its bar axis (local X) for off-min-deviation studies.
    R = Vector(d_in_local).rotation_difference(Vector(axis).normalized()).to_matrix()
    if roll_deg:
        R = R @ Matrix.Rotation(math.radians(roll_deg), 3, Vector((1.0, 0.0, 0.0)))
    # place the prism so its ENTRY-FACE CENTER lands at ``loc`` (not the mesh centroid), so a beam aimed at
    # ``loc`` along ``axis`` always strikes the entry face regardless of prism_type / apex / glass.
    _set_matrix(o, Vector(loc) - (R @ in_pos), R)
    return o


def _edge_outward_normal(quad_yz, i, j):
    """Outward unit normal (as a 3-vector in the X=0 plane) of the edge verts[i]->verts[j] of a Y-Z polygon,
    pointing away from the polygon centroid. Used for the Pellin-Broca quad's entry/exit face ports."""
    cy = sum(p[0] for p in quad_yz) / len(quad_yz)
    cz = sum(p[1] for p in quad_yz) / len(quad_yz)
    (yi, zi), (yj, zj) = quad_yz[i], quad_yz[j]
    dy, dz = yj - yi, zj - zi
    nrm = Vector((0.0, dz, -dy))
    mid = Vector((0.0, (yi + yj) * 0.5, (zi + zj) * 0.5))
    if (mid - Vector((0.0, cy, cz))).dot(nrm) < 0.0:
        nrm = -nrm
    return nrm.normalized()


def _edge_mid(quad_yz, i, j, depth=0.0):
    (yi, zi), (yj, zj) = quad_yz[i], quad_yz[j]
    return Vector((0.0, (yi + yj) * 0.5, (zi + zj) * 0.5))


# --- additional component builders (broad library) --------------------------
# Inline (pass-through) parts reuse `_inline`: a disc with IN/OUT ports on its
# optical axis; the tracer transmits the beam straight through (layout fidelity).

def polarizer(name, loc, axis, coll=None, radius=12.5, polarizer_type='FILM'):
    """A linear polarizer. ``polarizer_type`` shapes the mesh -- a thin film/wire-grid disc, a Glan
    calcite PRISM block (with the cut interface), or a tilted Brewster plate -- but the Jones behavior
    (transmit pol_axis_deg, extinction) and the ports (+/-1.5 on the axis) are identical for all."""
    import math
    pt = polarizer_type
    if pt in ('GLAN_THOMPSON', 'GLAN_TAYLOR', 'GLAN_LASER', 'WOLLASTON', 'ROCHON'):
        L = radius * 1.7                                     # a calcite prism block (the tracer splits Wollaston/Rochon)
        o = _cube(name, (radius * 1.7, radius * 1.7, L), coll)
        _bevel(o, 0.6, 1)
        o.data.materials.clear(); o.data.materials.append(MATS["pol"]())
        seam = _cube(name + "_seam", (radius * 2.6, radius * 2.6, 0.5), coll)  # the diagonal cut/air gap
        seam.data.materials.append(MATS["index"]())
        seam.matrix_world = _z_to(Vector((0.0, 1.0, 1.0))).to_4x4()
        clip = seam.modifiers.new("clip", 'BOOLEAN'); clip.operation = 'INTERSECT'; clip.object = o
        bpy.context.view_layer.objects.active = seam; bpy.ops.object.modifier_apply(modifier=clip.name)
        sm = seam.data
        bpy.ops.object.select_all(action='DESELECT'); seam.select_set(True); o.select_set(True)
        bpy.context.view_layer.objects.active = o; bpy.ops.object.join()
        if sm.users == 0:
            bpy.data.meshes.remove(sm)
    elif pt == 'BREWSTER':
        o = _disc(name, radius, 2.0, coll)
        o.data.transform(Matrix.Rotation(math.radians(32.0), 4, 'Y'))   # tilt the plate; ports stay axial
        o.data.materials.clear(); o.data.materials.append(MATS["pol"]())
    else:                                                   # FILM / WIRE_GRID
        o = _disc(name, radius, 3.0, coll)
        o.data.materials.clear(); o.data.materials.append(MATS["pol"]())
        if pt == 'WIRE_GRID':
            _accent(o, "bezel", lambda c, nrm: nrm.z > 0.7)   # metallic wire-grid front face
    _tag(o, 'POLARIZER', clear_aperture=radius, polarizer_type=pt)
    _add_port(o, "IN", 'IN', (0, 0, -1.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


# Colored-glass (Schott RG/GG/OG/BG) body tints -- saturated, so the slab reads as deep colored
# glass in the viewport AND in a Cycles render (volume-absorbing tint). Keyed by glass_type (C2).
CGLASS_TINT = {
    'RG610': (0.62, 0.02, 0.02), 'RG630': (0.55, 0.02, 0.03),
    'OG550': (0.85, 0.30, 0.02), 'OG590': (0.78, 0.16, 0.02),
    'GG495': (0.92, 0.82, 0.08), 'GG420': (0.95, 0.90, 0.30),
    'BG39':  (0.05, 0.45, 0.55), 'BG40':  (0.05, 0.55, 0.65),
    'VG9':   (0.08, 0.55, 0.12), 'CUSTOM': (0.50, 0.30, 0.55),
}


def _cglass_tint(glass_type):
    return CGLASS_TINT.get(glass_type, CGLASS_TINT['CUSTOM'])


def optical_filter(name, loc, axis, coll=None, radius=12.5,
                   filt_type='BP', cut_lo_nm=600.0, cut_hi_nm=700.0, od=1.0,
                   glass_type='RG610', thickness_mm=3.0, d_ref_mm=3.0, peak_t=0.91):
    """An optical filter (longpass/shortpass/bandpass/ND/colored-glass); transmits per its band.

    For the CGLASS_* (colored-glass, bulk-absorptive) types the body is volume-tinted to the
    Schott glass colour (RG610->deep red, GG495->yellow, BG39->blue-green, ...) so the slab
    reads as a saturated colored window in both the viewport and a Cycles render (C2)."""
    is_cglass = str(filt_type).startswith('CGLASS')
    o = _inline(name, loc, axis, coll, 'FILTER', "filt", radius=radius, depth=3.5,
                filt_type=filt_type, cut_lo_nm=cut_lo_nm, cut_hi_nm=cut_hi_nm, od=od,
                glass_type=glass_type, thickness_mm=thickness_mm, d_ref_mm=d_ref_mm, peak_t=peak_t)
    if is_cglass:
        tint = _cglass_tint(glass_type)
        # saturated body tint (slot 0); a glass-type-keyed material so distinct glasses don't share one
        o.data.materials.clear()
        o.data.materials.append(_mat("OG_cglass_%s" % glass_type, tint, metal=0.0, rough=0.12))
    return o


def _pinhole_foil(name, r_face, depth, bore, coll, seg=56):
    """The blackened precision-foil face of a spatial-filter pinhole: a thin recessed disc (radius r_face)
    carrying the small central through-bore + a shallow conical bore CHAMFER (the funnel a real laser-drilled
    foil has) raised on its front side. Built from CLOSED solids (a bored disc + a chamfer cone-ring) so the
    result is manifold. Returns a single mesh (caller puts it on its own slot)."""
    o = _bored_disc(name, r_face, depth, bore, coll, seg=seg)       # manifold foil disc with the through-bore
    # the bore CHAMFER: a truncated cone (mouth wider than the bore) with its OWN through-bore boolean-cut so
    # the axis stays clear; raised on the front face -> the laser-drilled funnel. Closed solid -> manifold.
    mouth = min(bore * 1.9, r_face * 0.5)
    cb = bmesh.new()
    bmesh.ops.create_cone(cb, cap_ends=True, segments=max(24, seg // 2),
                          radius1=bore + 0.05, radius2=mouth, depth=depth * 0.55)
    cone = _bm_obj(name + "_chamf", cb, coll)
    for v in cone.data.vertices:
        v.co.z += depth * 0.5
    hb = bmesh.new(); _cyl_bm(hb, bore, depth * 2.0, max(16, seg // 2))    # re-open the bore through the cone
    cutter = _bm_obj(name + "_chamfbore", hb, coll)
    for v in cutter.data.vertices:
        v.co.z += depth * 0.5
    m = cone.modifiers.new("bore", 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = cutter
    bpy.context.view_layer.objects.active = cone
    bpy.ops.object.modifier_apply(modifier=m.name)
    cm = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cm.users == 0:
        bpy.data.meshes.remove(cm)
    return _join(o, cone)


def pinhole(name, loc, axis, coll=None, radius=12.5):
    """A spatial-filter pinhole that reads as a real part:
      slot 0  an SM1 housing RING (theme-swapped on render) -- outer = radius, a recessed front well
      slot 1  a recessed BLACKENED-FOIL face (dark matte) carrying the small central bore + a conical bore
              CHAMFER (the laser-drilled funnel)
    Cosmetic only: the ports (IN/OUT on the optical axis) and clear_aperture = radius are unchanged, so the
    tracer's PINHOLE _clip_T branch sees identical inputs."""
    o = _bored_disc(name, radius, 2.0, radius * 0.62, coll)        # slot 0 SM1 housing ring (front well bore)
    o.data.materials.clear(); o.data.materials.append(MATS["ap"]())            # slot 0 housing (theme-swapped)
    base = len(o.data.polygons)
    _join(o, _pinhole_foil(name + "_foil", radius * 0.66, 1.0, 0.6, coll))     # recessed foil + chamfered bore
    o.data.materials.append(MATS["foil"]())                                    # slot 1 blackened foil
    for p in o.data.polygons[base:]:
        p.material_index = 1
    _tag(o, 'PINHOLE', clear_aperture=radius)
    _add_port(o, "IN", 'IN', (0, 0, -1.0), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.0), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), _z_to(axis))
    return o


def slit(name, loc, axis, coll=None, width=2.0, angle=0.0, radius=14.0):
    """A SLIT (1-D aperture): a black housing carrying TWO blades whose gap = ``width`` mm, clipping the beam
    along ONE transverse axis (rolled by ``angle`` deg about the optical axis). The tracer scales the power by
    the VERIFIED slit erf T = erf(sqrt2 * (width/2) / w) along the clipped axis; the path is undeviated.
    IN/OUT on +/- the optical axis, like the other inline apertures (so it chains transparently)."""
    o = _bored_disc(name, radius + 5.0, 3.6, radius, coll)         # black ring housing with a clear central bore
    o.data.materials.clear(); o.data.materials.append(MATS["ap"]())
    half = max(width, 0.0) * 0.5
    jaw_x = radius * 1.05                                          # blade spans the bore; edge sits at +/-half on Y
    for sgn in (+1.0, -1.0):                                       # the two slit jaws (their facing edges define the gap)
        jb = bmesh.new(); bmesh.ops.create_cube(jb, size=1.0)
        for v in jb.verts:                                        # a thin bar; inner edge at y = sgn*half
            v.co = (Vector((v.co.x * jaw_x, v.co.y * (radius), v.co.z * 0.8))
                    + Vector((0.0, sgn * (radius + half), 0.0)))
        jaw = _bm_obj(name + "_jaw%d" % (sgn > 0), jb, coll)
        jaw.data.materials.append(MATS["blade"]())
        _join(o, jaw)
    # roll the whole part so the blades clip along the local-X-rolled axis (matches tracer _clip_axis_world)
    R = _z_to(axis)
    if angle:
        R = R @ Matrix.Rotation(math.radians(angle), 3, Vector((0.0, 0.0, 1.0)))
    _tag(o, 'SLIT', clear_aperture=radius, slit_width=width, slit_angle=angle)
    _add_port(o, "IN", 'IN', (0, 0, -1.8), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.8), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), R)
    return o


def knife_edge(name, loc, axis, coll=None, position=0.0, angle=0.0, radius=14.0):
    """A KNIFE_EDGE: a razor half-plane blade mounted on a translation stage, cutting into the beam from one
    side at transverse ``position`` mm (along the cut axis, rolled by ``angle`` deg). The tracer transmits the
    part of the beam PAST the edge via the VERIFIED knife erf P = 0.5[1 - erf(sqrt2 (e - xc)/w)]; sweeping the
    position traces the classic erf knife-edge profile (a KNIFE scan fits it back to the beam radius w)."""
    o = _disc(name, radius * 0.5, 3.0, coll)                      # a small stage puck behind the blade
    o.data.materials.clear(); o.data.materials.append(MATS["dumpbody"]())
    # the razor: a thin wedge half-plane covering y < position (its straight edge at y = position is the knife edge)
    kb = bmesh.new(); bmesh.ops.create_cube(kb, size=1.0)
    for v in kb.verts:
        # blade spans x in [-radius, radius], y in [-radius, position] (covers one half), z thin near the face
        v.co = (Vector((v.co.x * radius, (v.co.y * 0.5 - 0.5) * (radius + position) + position * 0.5,
                        v.co.z * 0.5)) + Vector((0.0, 0.0, 0.6)))
    blade = _bm_obj(name + "_blade", kb, coll)
    blade.data.materials.append(MATS["blade"]())
    _bevel(blade, 0.15, 1)                                        # honed cutting edge
    _join(o, blade)
    R = _z_to(axis)
    if angle:
        R = R @ Matrix.Rotation(math.radians(angle), 3, Vector((0.0, 0.0, 1.0)))
    _tag(o, 'KNIFE_EDGE', clear_aperture=radius, knife_position=position, knife_angle=angle)
    _add_port(o, "IN", 'IN', (0, 0, -1.5), (0, 0, -1), radius)
    _add_port(o, "OUT", 'OUT', (0, 0, 1.5), (0, 0, 1), radius)
    _set_matrix(o, Vector(loc), R)
    # the stage gives the knife a linear translation knob along its cut axis (the swept DOF)
    return o


def beam_dump(name, loc, beam_dir, coll=None, size=22.0, residual=1.0e-3):
    """A BEAM_DUMP: a conical light trap (matte-black inner cone inside an anodized housing) that TERMINATES
    the beam -- the textbook way to safely absorb a rejected beam (e.g. a PBS reject port). The tracer ends
    the ray here (it is in TERMINAL); ``residual`` is the tiny leak fraction (~1e-3) carried as metadata. The
    cone's apex faces the incoming beam so a real trap's multiple-bounce absorption reads at a glance."""
    o = _disc(name, size * 0.5, size * 0.7, coll)                 # cylindrical housing
    _bevel(o, 0.5, 1)
    o.data.materials.clear(); o.data.materials.append(MATS["dumpbody"]())
    # inner absorbing cone: apex toward the beam (+Z opening), base deep inside -> light bounces & is trapped
    cb = bmesh.new()
    bmesh.ops.create_cone(cb, cap_ends=True, segments=40, radius1=size * 0.42, radius2=0.0,
                          depth=size * 0.6)
    cone = _bm_obj(name + "_cone", cb, coll)
    for v in cone.data.vertices:                                  # apex at +Z (toward the beam), base at -Z
        v.co.z = -v.co.z + size * 0.05
    cone.data.materials.append(MATS["trap"]())
    _join(o, cone)
    _tag(o, 'BEAM_DUMP', clear_aperture=size * 0.5, beam_dump_residual=residual)
    _add_port(o, "IN", 'IN', (0, 0, size * 0.35), (0, 0, 1), size * 0.5)   # opening faces the beam
    _set_matrix(o, Vector(loc), _z_to(-Vector(beam_dir).normalized()))
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
