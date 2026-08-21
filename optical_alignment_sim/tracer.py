"""Sequential geometric ray tracer.

Propagates rays from each SOURCE through the optical elements, reflecting /
refracting / splitting at each interaction surface, until they reach a detector,
escape, or hit the segment/depth budget. The result is a flat list of segment
dicts (the BS tree is encoded via the `parent` index).

The trace reads the *actual* world geometry of each element (via the port world
math in geometry.py), so when a mount is rotated the beam path changes and the
misalignment becomes visible as a broken path - which is exactly what alignment
automation then measures.
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from mathutils import Vector, Matrix

from . import geometry, physics

EPS = 1e-4
EXTEND_MM = 150.0          # how far an escaping ray is drawn

# overlay reads this; handlers write it
cached_segments = []

# Elements whose beam interaction happens at the REFLECT port plane (not the IN plane).
REFLECTIVE = ('MIRROR', 'PRISM_MIRROR', 'BEAMSPLITTER', 'DICHROIC', 'GRATING', 'RETROREFLECTOR',
              'DEFORMABLE_MIRROR')
# Elements that absorb the beam (no outgoing ray). BEAM_DUMP is a conical light trap (C5): the ray ENDS,
# leaving only a tiny residual leak (beam_dump_residual ~1e-3) so the A4 energy budget still balances.
TERMINAL = ('DETECTOR', 'PHOTODIODE', 'POWER_METER', 'WAVEFRONT_SENSOR', 'BEAM_DUMP')


class _Ray:
    __slots__ = ('p1', 'dir', 'power', 'depth', 'from_obj', 'wl', 'kind', 'parent',
                 'jones', 'opl', 'q', 'src_id', 'coh', 'evec', 'aberr', 'm2', 'ghost_depth')

    def __init__(self, p1, d, power, depth, from_obj, wl, kind, parent,
                 jones=None, opl=0.0, q=None, src_id=-1, coh=1.0e12, evec=None, aberr=None,
                 m2=1.0, ghost_depth=0):
        self.p1 = p1
        self.dir = d.normalized()
        self.power = power
        self.depth = depth
        self.from_obj = from_obj
        self.wl = wl
        self.kind = kind
        self.parent = parent
        self.jones = jones          # (Ex, Ey) Jones vector in the dir's transverse frame
        self.opl = opl              # optical path length accumulated up to p1 (mm)
        self.q = q                  # Gaussian complex beam parameter
        self.src_id = src_id        # coherence group (which source this ray came from)
        self.coh = coh              # coherence length (mm) from the source linewidth
        self.evec = evec            # 3-D complex field (vectorial pol), transverse to dir
        self.aberr = aberr          # Zernike wavefront-error coeffs (waves) or None (=flat)
        self.m2 = m2                # beam-quality factor (B1): physical radius = sqrt(m2)*beam_radius(q)
        self.ghost_depth = ghost_depth  # A9: how many parasitic back-reflections deep this ray is


def _find_port(props, role):
    for p in props.ports:
        if p.role == role:
            return p
    return None


def _find_port_named(props, name):
    """Look up a port by NAME (e.g. a routing prism's 'FOLD1'/'FOLD2' internal mirror faces, which all
    share the REFLECT role so a role lookup is ambiguous)."""
    for p in props.ports:
        if p.name == name:
            return p
    return None


def _first_in(props):
    return _find_port(props, 'IN')


def _first_out(props):
    return _find_port(props, 'OUT')


# Millimetres per Blender unit for the trace in progress. The tracer's arithmetic is entirely in
# millimetres, so every POSITION it reads is converted on the way in and the emitted p1/p2 are
# converted back to world units on the way out (the overlay and the bake draw with them). Every
# distance is derived from those positions, so none of them needs converting individually -- there
# is no length site left to forget. Unless the scene declares its units authoritative this is
# exactly 1.0 and every multiplication below is the identity.
_mmpu = 1.0


def _wp(obj, local_position):
    """Port position in MILLIMETRES."""
    return geometry.world_port(obj, local_position) * _mmpu


def _wc(obj):
    """Element centre in MILLIMETRES."""
    return obj.matrix_world.translation * _mmpu


def interaction_surface(obj):
    """Return (point, normal, aperture) of the surface the beam interacts with:
    the REFLECT plane for reflective elements, otherwise the IN port plane."""
    props = obj.optics
    if props.element_type in REFLECTIVE:
        rp = _find_port(props, 'REFLECT')
        if rp:
            return (geometry.world_port(obj, rp.local_position),
                    geometry.world_normal(obj, rp.local_normal),
                    rp.clear_aperture or props.clear_aperture)
    ip = _first_in(props)
    if ip:
        return (geometry.world_port(obj, ip.local_position),
                geometry.world_normal(obj, ip.local_normal),
                ip.clear_aperture or props.clear_aperture)
    return None, None, 0.0


def _circulator_ports(props):
    """The circulator's cyclic port list (P1, P2, P3, ...) in CYCLE ORDER. Every port carries role 'IN'
    (each face both receives and emits a beam -- the routing is non-reciprocal by direction, not by a
    fixed in/out face). Ordered by NAME (P1/P2/P3...) so the cycle Pi -> P(i+1) is unambiguous; the
    builder lays them out on distinct faces, so a ray entering one face is matched to exactly one port."""
    ps = [p for p in props.ports if p.role == 'IN']
    ps.sort(key=lambda p: p.name)
    return ps


def _ray_plane(p0, d, plane_pt, plane_n):
    denom = d.dot(plane_n)
    if abs(denom) < 1e-9:
        return None
    t = (plane_pt - p0).dot(plane_n) / denom
    if t < EPS:
        return None
    return p0 + d * t, t


def _order_list(scene):
    raw = scene.optics.order_csv if getattr(scene, "optics", None) else ""
    return [n.strip() for n in raw.split(",") if n.strip()]


def _find_next(geometry_table, ray, mode, order, order_index, element_by_name):
    """Return (t, element, hit_point, surface_normal) for the nearest interaction
    ahead of the ray, or None."""
    candidates = geometry_table
    if mode == 'ORDER' and order:
        if ray.from_obj is not None and ray.from_obj.name in order_index:
            i = order_index[ray.from_obj.name]
            names = order[i + 1:i + 2]
        else:
            names = order[0:1]
        candidates = ([element_by_name[names[0]]] if names and names[0] in element_by_name else [])

    best = None
    for E, surface, port_surfaces in candidates:
        if E is ray.from_obj:
            continue
        # A CIRCULATOR is an N-port router: a ray may ENTER via any of its port FACES, so every IN port is a
        # candidate interaction surface (not the single IN plane the other elements expose). Test each port
        # plane; the nearest one the ray crosses INTO (traveling against the port's outward normal) is the
        # entry. Reuses the same ray-plane + clear-aperture gate as every other element.
        if E.optics.element_type == 'CIRCULATOR':
            for sp, sn, ca in port_surfaces:
                if ray.dir.dot(sn) >= 0.0:                 # outward normal: only faces the ray enters INTO count
                    continue
                hit = _ray_plane(ray.p1, ray.dir, sp, sn)
                if hit is None:
                    continue
                H, t = hit
                if (H - sp).length <= max(ca, 0.0) + 1e-3:
                    if best is None or t < best[0]:
                        best = (t, E, H, sn)
            continue
        sp, sn, ca = surface
        if sp is None:
            continue
        hit = _ray_plane(ray.p1, ray.dir, sp, sn)
        if hit is None:
            continue
        H, t = hit
        off = (H - sp).length
        if off <= max(ca, 0.0) + 1e-3:
            if best is None or t < best[0]:
                best = (t, E, H, sn)
    return best


def _seg(ray, p2, to_obj, sn=None):
    seg_len = (p2 - ray.p1).length
    opl = ray.opl + seg_len                      # free-space (air, n~=1) optical path
    lam_mm = ray.wl * 1.0e-6
    phase = (2.0 * math.pi * opl / lam_mm) if lam_mm > 0.0 else 0.0
    j = ray.jones
    # At a detector, express the field in the DETECTOR's frame (derived from its surface
    # normal sn, identical for every beam reaching it) rather than each beam's own
    # transverse_basis(dir). transverse_basis is discontinuous in its argument, so two
    # co-polarized beams arriving at slightly different angles would otherwise land in
    # ~90-deg-rotated frames and fail to interfere. A shared frame fixes that.
    if (j is not None and ray.evec is not None and sn is not None
            and to_obj is not None and to_obj.optics.element_type in TERMINAL):
        e1, e2 = physics.transverse_basis(sn)
        ev = ray.evec
        j = (ev[0] * e1[0] + ev[1] * e1[1] + ev[2] * e1[2],
             ev[0] * e2[0] + ev[1] * e2[1] + ev[2] * e2[2])
    qd = physics.q_propagate(ray.q, physics.abcd_free(seg_len)) if ray.q is not None else None
    return {
        "p1": ray.p1 / _mmpu, "p2": p2 / _mmpu, "kind": ray.kind,
        "from": ray.from_obj.name if ray.from_obj else None,
        "to": to_obj.name if to_obj else None,
        "power": round(ray.power, 4), "wavelength": ray.wl, "parent": ray.parent,
        "jones": [j[0].real, j[0].imag, j[1].real, j[1].imag] if j else None,
        "opl": opl, "phase": phase, "src_id": ray.src_id, "coh": ray.coh,
        "w_mm": physics.beam_radius_m2(qd, ray.wl, ray.m2) if qd is not None else 0.0,
        "qd": [qd.real, qd.imag] if qd is not None else None,   # Gaussian q at the hit -> R, w, Gouy
        "m2": ray.m2,                                          # beam quality (B1): w_real = sqrt(m2)*beam_radius(q)
        "aberr": list(ray.aberr) if ray.aberr else None,
    }


def _aberr_combine(base, vec, sign):
    """base (or None=flat) +/- the element's Zernike vector -> a fresh 15-coeff list."""
    out = list(base) if base else [0.0] * physics.N_ZERNIKE
    for i in range(min(len(out), len(vec))):
        out[i] = out[i] + sign * vec[i]
    return out


def _child(ray, E, H, d, power, kind, idx, t, jones=None, q=None, evec=None, aberr=None, wl=None):
    """Construct a continuation ray: carry polarization/coherence, advance the optical
    path length, and propagate the Gaussian beam q through the free space to E (and
    through E's focal power when it is a lens).

    Polarization is kept as a 3-D field `evec` plus its 2-D Jones projection in the new
    direction's transverse frame. An explicit evec (exact 3-D reflection) wins; otherwise
    the field is rebuilt from the 2-D jones, reproducing the prior Jones-only behaviour
    while still carrying a faithful 3-D field for the next reflection."""
    fresh_q = q is not None        # caller passed an explicit q == a CONVERTED beam (CRYSTAL SHG/SPDC,
                                   # a new diffraction-limited m2=1 child). Capture it BEFORE the block
                                   # below reassigns the local q from ray.q -- otherwise a plain
                                   # continuation (q=None) looks "fresh" after propagation and its M^2
                                   # is wrongly reset to 1 one element past the source.
    if q is None:
        q = ray.q
        if q is not None:
            q = physics.q_propagate(q, physics.abcd_free(t))            # free space to the hit point
            if E.optics.element_type == 'LENS' and E.optics.focal_length:
                lg = getattr(E.optics, 'lens_glass', 'N-BK7')    # the lens's real substrate glass
                tC = getattr(E.optics, 'temp_C', 20.0)           # thermo-optic shift (20 C = no-op)
                nd = physics.sellmeier_n(getattr(E.optics, 'design_wl', 633.0), lg, tC)
                nl = physics.sellmeier_n(ray.wl, lg, tC)         # chromatic: f ~ 1/(n-1)
                f_eff = (E.optics.focal_length * (nd - 1.0) / (nl - 1.0)
                         if abs(nl - 1.0) > 1e-6 else E.optics.focal_length)
                q = physics.q_propagate(q, physics.abcd_lens(f_eff))
                # opt-in THERMAL LENS: an absorbing optic adds an induced lens f_th to the beam q
                # (Tier-1 lumped model; default off / 0 W -> byte-identical). w is preserved across a
                # thin lens, so the post-lens q gives the beam radius at the optic.
                p_abs = getattr(E.optics, 'absorbed_power_W', 0.0)
                if getattr(E.optics, 'thermal_lensing', False) and p_abs > 0.0:
                    w_th = physics.beam_radius(q, ray.wl)
                    if w_th > 0.0:
                        f_th = physics.thermal_lens_focal_length(
                            p_abs, physics.DNDT.get(lg, 1.0e-5),
                            getattr(E.optics, 'thermal_conductivity', 1.38), w_th)
                        q = physics.q_propagate(q, physics.abcd_lens(f_th))
            elif E.optics.element_type == 'OBJECTIVE':
                # a microscope objective focuses with f_obj = f_tube / M (VERIFIED
                # microscope-objective-magnification); finite conjugates use the optical tube length.
                tl = {'FINITE_160': 160.0, 'FINITE_195': 195.0}.get(
                    getattr(E.optics, 'obj_correction', 'INFINITY'), getattr(E.optics, 'obj_tube_ref', 200.0))
                f_obj = tl / max(getattr(E.optics, 'obj_mag', 10.0), 1.0e-6)
                q = physics.q_propagate(q, physics.abcd_lens(f_obj))
            else:
                # a CURVED mirror focuses on reflection: f = R/2 (VERIFIED spherical-mirror-focal-length).
                # Achromatic -- NO 1/(n-1) wavelength scaling (a mirror does not disperse, unlike a lens).
                mc = getattr(E.optics, 'mirror_curve', 'FLAT')
                rc = getattr(E.optics, 'radius_curv', 0.0)
                if (E.optics.element_type in ('MIRROR', 'PRISM_MIRROR', 'DEFORMABLE_MIRROR')
                        and mc in ('CONCAVE', 'CONVEX') and rc > 0.0):
                    f_mirror = (rc * 0.5) if mc == 'CONCAVE' else -(rc * 0.5)   # f = +R/2 / -R/2
                    q = physics.q_propagate(q, physics.abcd_lens(f_mirror))
    if evec is not None:
        nev = evec
        nj = physics.jones_from_field(evec, d)
    else:
        nj = ray.jones if jones is None else jones
        nev = physics.field_from_jones(nj, d) if nj is not None else None
    # a converted child (CRYSTAL: SHG/SPDC) passes an explicit fresh q -> it is a new,
    # diffraction-limited beam (m2=1); a plain continuation inherits the parent's m2 (ABCD
    # propagation preserves M^2). Keyed on fresh_q (the ARGUMENT), not the post-propagation
    # local q -- the latter is non-None for every Gaussian continuation, which silently reset M^2.
    child_m2 = 1.0 if fresh_q else ray.m2
    return _Ray(H, d, power, ray.depth + 1, E, (wl if wl is not None else ray.wl), kind, idx,
                jones=nj, opl=ray.opl + t, q=q,
                src_id=ray.src_id, coh=ray.coh, evec=nev,
                aberr=(aberr if aberr is not None else ray.aberr), m2=child_m2,
                ghost_depth=ray.ghost_depth)


def _clip_T(ray, E, t):
    """Gaussian power transmission through the element's clear aperture.

    CIRCULAR (the default, and what every element did before aperture_shape existed) is the round
    stop: T = 1 - exp(-2 a^2/w^2). SQUARE / RECTANGULAR use the separable product of the VERIFIED 1-D
    erf slit kernel (physics.rect_aperture_transmission) -- a square dichroic or BS cube already has a
    square MESH, and only its optical aperture was still the circle inscribed in it, discarding the
    light a real square optic passes at its corners.

    The beam is rotationally symmetric, so the aperture's roll about the optical axis does not enter."""
    if ray.q is None:
        return 1.0
    w = physics.beam_radius_m2(physics.q_propagate(ray.q, physics.abcd_free(t)), ray.wl, ray.m2)
    if w <= 1e-9:
        return 1.0
    a = E.optics.clear_aperture
    # Dispatch on shape FIRST. A zero half-width on a shape the user explicitly chose means the
    # opening has zero area -- it blocks -- and routing that through the kernel is the whole point
    # of rect_aperture_transmission's zero case. Testing `a <= 0` before this returned 1.0 and
    # passed the full beam through a closed stop, and left an axis asymmetry: aperture_half_y = 0
    # blocked while clear_aperture = 0 did not, though the UI allows zero for both.
    shape = getattr(E.optics, 'aperture_shape', 'CIRCULAR')
    if shape == 'SQUARE':
        return physics.rect_aperture_transmission(a, a, w)
    if shape == 'RECTANGULAR':
        return physics.rect_aperture_transmission(a, getattr(E.optics, 'aperture_half_y', a), w)
    # CIRCULAR keeps its historical reading of zero: "no clear aperture configured", so nothing
    # clips. Changing that would alter every existing scene that never set the field, which is a
    # separate decision from giving the new shapes a sane closed state.
    if a <= 0.0:
        return 1.0
    return 1.0 - math.exp(-2.0 * a * a / (w * w))


def _ghost_reflectance(E, ray, sn):
    """A9: the per-surface power reflectance R of a transmissive face -- the fraction that
    becomes the parasitic Fresnel ghost (back-reflection). AR-coated surfaces use the element's
    small ar_reflectance (~0.25%); uncoated air<->glass uses the verified surface_reflectance at
    the LOCAL angle of incidence (fresnel_reflect's unpolarized-average power, with the
    normal-incidence ((n1-n2)/(n1+n2))^2 ~4% as the floor). n2 comes from the element's
    refractive_index (Sellmeier glasses default ~1.5)."""
    op = E.optics
    if getattr(op, 'ar_coated', False):
        return min(max(getattr(op, 'ar_reflectance', 0.0025), 0.0), 1.0)
    sg = getattr(op, 'surface_glass', 'NONE')           # opt-in: dispersive index n2(lambda) at ray.wl
    if sg != 'NONE' and getattr(ray, 'wl', 0.0) > 0.0:
        n2 = max(physics.sellmeier_n(ray.wl, sg), 1.0)
    else:
        n2 = max(getattr(op, 'refractive_index', 1.5168), 1.0)
    aoi = math.acos(min(1.0, abs(ray.dir.dot(sn))))
    if aoi < 1e-6:
        return physics.surface_reflectance(1.0, n2)         # normal-incidence floor
    # off-axis: the unpolarized-average Fresnel power reflection (>= the normal-incidence floor)
    return 1.0 - physics.fresnel_transmit_power(1.0, n2, aoi)


def _spawn_ghost(stack, gcfg, ray, E, H, sn, idx, t):
    """A9: spawn the low-power GHOST (parasitic Fresnel back-reflection) at a transmissive face, and
    return R so the caller can DEBIT the transmitted power to (1-R)*power (energy conserved: R+T=1,
    physics_verify ok=true 12/12). Returns 0.0 -- a no-op -- unless ghost modeling is ON, so a scene
    that didn't ask for ghosts traces byte-identical. The ghost is gated by:
      * the scene toggle model_ghosts (gcfg[0]); OFF -> no ghost, R=0, transmitted power unchanged.
      * ghost-depth < max_ghost_depth (gcfg[2]): a ghost may re-reflect only so many times (no
        ghosts-of-ghosts-forever -> the segment budget is protected).
      * ghost power R*power >= ghost_floor (gcfg[1]): a sub-floor ghost is not worth a segment.
    The ghost direction is the specular reflection of the incident ray off the surface normal sn
    (geometry.reflect), and it carries ghost_depth+1 so its own ghost is gated one level deeper. It
    is a normal REFLECT child, so if it travels backward through an ISOLATOR the existing ISOLATOR
    branch extinguishes it -- which is exactly what clears the back_reflection diagnostic."""
    model_ghosts, ghost_floor, max_ghost_depth = gcfg
    if not model_ghosts:
        return 0.0
    R = _ghost_reflectance(E, ray, sn)
    if R <= 0.0:
        return 0.0
    # debit the transmitted power regardless of whether the ghost segment itself survives the
    # floor/depth gate -- the power physically leaves the transmitted beam either way (it just
    # isn't worth tracing as its own segment below the floor). This keeps R+T=1 exactly.
    if ray.ghost_depth < max_ghost_depth and R * ray.power >= ghost_floor:
        nd = geometry.reflect(ray.dir, sn)
        g = _child(ray, E, H, nd, ray.power * R, 'GHOST', idx, t,
                   jones=physics.scale(ray.jones, math.sqrt(R)) if ray.jones else None)
        g.ghost_depth = ray.ghost_depth + 1
        stack.append(g)
    return R


def _spawn_coating(stack, ray, E, H, sn, idx, t):
    """A11: spawn the explicit USER-SET reflective-coating PICKOFF at a transmissive face, and return R
    (= the element's coating_reflectance) so the caller can DEBIT the onward power. This is the
    controllable generalization of the A9 ghost: instead of a fixed ~4% parasitic Fresnel reflection, R
    is whatever the user painted on coating_reflectance (0..1), so a plain window becomes an R-fraction
    beam pickoff and any face can carry an HR/partial coating.

    Returns 0.0 -- a no-op -- when coating_reflectance is 0 (the default), so an element that didn't ask
    for a coating traces BYTE-IDENTICAL. The pickoff is a normal REFLECT child off the ENTRY-face normal
    sn (geometry.reflect, the same geometry the A9 ghost uses); its power is R*ray.power and the field is
    scaled by sqrt(R). It carries the parent's ghost_depth (it is an explicit beam, not a parasitic one),
    so it is NOT gated by the ghost floor/depth -- a user pickoff always fires. The onward power debit is
    left to the caller so a single (1-Rg-R)*T multiply covers the ghost + coating + absorber together
    (R_ghost + R_coating + T_onward + A = incident, energy conserved, the A4 budget stays balanced)."""
    R = min(max(getattr(E.optics, 'coating_reflectance', 0.0), 0.0), 1.0)
    if R <= 0.0:
        return 0.0
    nd = geometry.reflect(ray.dir, sn)
    # an imprint_surface coating pickoff also carries the entry-face surface figure (opt-in; None when
    # imprint_surface is off -> the pickoff is unchanged). MIRROR is the must; this is the optional extra.
    imp = _surface_imprint_coeffs(E, ray, H, sn, t)
    ab = _aberr_combine(ray.aberr, imp, 1.0) if imp is not None else None
    c = _child(ray, E, H, nd, ray.power * R, 'REFLECT', idx, t,
               jones=physics.scale(ray.jones, math.sqrt(R)) if ray.jones else None, aberr=ab)
    stack.append(c)
    return R


def _w_at(ray, t):
    """Incident Gaussian (1/e^2 intensity) radius at the element plane the ray hits in time t, or 0
    when there is no Gaussian carried on the ray (returns 0 -> the caller treats the clip as a no-op)."""
    if ray.q is None:
        return 0.0
    return physics.beam_radius_m2(physics.q_propagate(ray.q, physics.abcd_free(t)), ray.wl, ray.m2)


# --- SURFACE-FIGURE -> WAVEFRONT IMPRINT (opt-in, gated by op.imprint_surface) -------------------
# Honest Tier-1 GEOMETRIC imprint: a reflective element's ACTUAL mesh surface stamps an optical-path-
# difference (NOT a wave-diffraction calc) onto the reflected beam over its Gaussian footprint, fit to
# the (oracle-verified) orthonormal Noll Zernikes. The reflected child carries that as extra `aberr`
# (waves), so a downstream wavefront sensor reads the element's surface figure. DEFAULT OFF -> no
# imprint -> existing scenes trace byte-identical; a FLAT surface imprints ~0.
_IMPRINT_RINGS = 6                 # polar footprint grid: 6 rings ...
_IMPRINT_SPOKES = 16               # ... x 16 spokes (+ center) = 97 samples inside the disc
_IMPRINT_BACKUP = 50.0             # mm: back the probe ray up along -ray.dir before ray_cast, so it
                                   # starts safely outside the mesh and hits the front surface


def _plane_fit(u, v, z, weights=None):
    """(Weighted) least-squares plane z ~ a0 + au*u + av*v over matched (u,v,z) samples. Returns (a0, au, av).
    Used to detrend the footprint depths against their best-fit reference plane (so a flat-but-tilted
    surface imprints 0). ``weights`` (per-sample, e.g. Gaussian beam intensity) makes the reference plane
    track where the beam actually is; weights=None reproduces the plain unweighted fit EXACTLY (so the modal
    imprint path is byte-identical). Solves the 3x3 normal equations directly (small, always well-conditioned
    for a non-degenerate footprint); falls back to the weighted mean if the system is singular."""
    n = len(z)
    if n == 0:
        return 0.0, 0.0, 0.0
    Suu = Suv = Svv = Su = Sv = Sz = Suz = Svz = Sw = 0.0
    for i in range(n):
        ui, vi, zi = u[i], v[i], z[i]
        wi = weights[i] if weights is not None else 1.0
        Suu += wi * ui * ui; Suv += wi * ui * vi; Svv += wi * vi * vi
        Su += wi * ui; Sv += wi * vi; Sz += wi * zi
        Suz += wi * ui * zi; Svz += wi * vi * zi
        Sw += wi
    # weighted normal equations M [a0, au, av]^T = b, with M symmetric (Sw = sum of weights = n unweighted):
    #   [ Sw  Su  Sv ] [a0]   [ Sz  ]
    #   [ Su  Suu Suv] [au] = [ Suz ]
    #   [ Sv  Suv Svv] [av]   [ Svz ]
    M = [[Sw, Su, Sv], [Su, Suu, Suv], [Sv, Suv, Svv]]
    b = [Sz, Suz, Svz]
    aug = [M[r][:] + [b[r]] for r in range(3)]
    for col in range(3):                                      # Gaussian elimination, partial pivoting
        piv = max(range(col, 3), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-15:
            return Sz / Sw, 0.0, 0.0                           # singular -> just the (weighted) mean (piston)
        aug[col], aug[piv] = aug[piv], aug[col]
        pv = aug[col][col]
        for k in range(col, 4):
            aug[col][k] /= pv
        for r in range(3):
            if r != col and aug[r][col]:
                f = aug[r][col]
                for k in range(col, 4):
                    aug[r][k] -= f * aug[col][k]
    return aug[0][3], aug[1][3], aug[2][3]


def _build_world_bvhtree(E):
    """BVHTree of element E's WORLD-space evaluated mesh (modifiers applied), or None if the mesh is
    missing / empty / unbuildable. Extracted so the MODAL imprint (_surface_imprint_coeffs) and the DENSE
    ZONAL field (surface_imprint_field) probe the byte-identical surface through one code path."""
    try:
        import bmesh
        from mathutils.bvhtree import BVHTree
    except Exception:
        return None
    bm = bmesh.new()
    try:
        try:
            deps = bpy.context.evaluated_depsgraph_get()
            bm.from_object(E, deps)                            # evaluated (modifiers applied)
        except Exception:
            if E.data is None:
                bm.free()
                return None
            bm.from_mesh(E.data)
        if not bm.faces:
            bm.free()
            return None
        bm.transform(Matrix.Scale(_mmpu, 4) @ E.matrix_world if _mmpu != 1.0
                     else E.matrix_world)
        tree = BVHTree.FromBMesh(bm)
    except Exception:
        try:
            bm.free()
        except Exception:
            pass
        return None
    bm.free()
    return tree


def _surface_imprint_coeffs(E, ray, H, sn, t):
    """Zernike wavefront-error coeffs (WAVES, length-15) imprinted on REFLECTION by element E's actual
    mesh surface over the incident Gaussian footprint, or None to skip (no imprint -> byte-identical).

    Algorithm (the verified physics is reused, no new oracle-checked law):
      1. Footprint radius w = _w_at(ray, t); skip if w<=0 (no Gaussian carried).
      2. Build a BVHTree of E's WORLD-space evaluated mesh (the optomech bmesh/BVHTree pattern). Skip if
         the mesh is missing/empty or all probes miss.
      3. Sample a polar grid of points P inside the disc of radius w centered at H, in the plane PERP to
         ray.dir (basis e1,e2 = physics.transverse_basis(ray.dir)). For each P, cast a probe ray PARALLEL
         to ray.dir (from P backed up _IMPRINT_BACKUP along -ray.dir) onto the tree; the along-beam
         distance to the surface, projected onto ray.dir, is the surface depth d_i at that footprint point.
      4. Detrend against the footprint's best-fit REFERENCE PLANE (piston + x/y tilt), not just the mean:
         dd_i = d_i - plane(u_i, v_i). The surface is tilted at the AOI to the probe, so a flat mesh returns
         a linear depth RAMP -- that ramp is the mirror's overall orientation (the fold, already carried by
         geometry.reflect), NOT figure error; removing it makes a flat surface imprint EXACTLY 0. The
         round-trip optical-path error is W_i = 2*dd_i  (the beam traverses the surface-depth deviation
         TWICE on reflection). This along-beam OPD is the direct measure of the same effect the oracle-
         verified reflection_wavefront_error W=2h*cos(theta) describes for a normal-height h: the cos(theta)
         projection is folded into the parallel-to-beam raycast distance (a sloped surface returns a longer
         along-beam d), so 2*dd is the round-trip wavefront error in beam-path mm.
      5. Normalize footprint radius rho=r/w (<=1), theta per sample, coeffs = physics.fit_zernike(...).
         Convert mm -> WAVES (the aberr/WFS convention) via /(wl_nm*1e-6), drop piston, return the vector.

    Robust: returns None (a no-op, no aberr change) on any of: imprint off, w<=0, no/empty mesh, <6
    surviving samples, a degenerate fit (all-zero)."""
    op = E.optics
    if not getattr(op, 'imprint_surface', False):
        return None                                           # default OFF -> byte-identical
    w = _w_at(ray, t)
    if w <= 1e-9:
        return None                                           # no Gaussian footprint -> nothing to sample
    tree = _build_world_bvhtree(E)                            # world-space evaluated mesh (shared helper)
    if tree is None:
        return None

    d = ray.dir.normalized()
    e1v, e2v = physics.transverse_basis((d.x, d.y, d.z))      # disc basis PERP to the beam axis
    e1 = Vector(e1v)
    e2 = Vector(e2v)
    samples = []                                              # (rho, theta, depth_along_beam_mm)
    # polar grid: center + (rings x spokes) inside the unit disc, rho in (0,1]
    grid = [(0.0, 0.0)]
    for ir in range(1, _IMPRINT_RINGS + 1):
        rr = ir / float(_IMPRINT_RINGS)
        for isp in range(_IMPRINT_SPOKES):
            th = 2.0 * math.pi * isp / float(_IMPRINT_SPOKES)
            grid.append((rr, th))
    for rho, theta in grid:
        r = rho * w
        P = H + e1 * (r * math.cos(theta)) + e2 * (r * math.sin(theta))
        origin = P - d * _IMPRINT_BACKUP                      # back up so the probe starts outside the mesh
        loc, nrm, fidx, dist = tree.ray_cast(origin, d)
        if loc is None:
            continue                                          # this footprint point misses the mesh -> drop
        depth = (Vector(loc) - origin).dot(d)                 # along-beam distance to the surface (mm)
        samples.append((rho, theta, depth))
    if len(samples) < 6:
        return None                                           # too few hits to fit -> no imprint

    rho_l = [s[0] for s in samples]
    th_l = [s[1] for s in samples]
    # DETREND against the best-fit REFERENCE PLANE of the footprint, not just the mean depth. The
    # surface is tilted at the angle of incidence relative to the probe (which is parallel to the beam),
    # so a perfectly FLAT mesh returns along-beam depths that vary LINEARLY across the disc -- that ramp
    # is the mirror's overall orientation (the fold geometry, already carried by geometry.reflect), NOT a
    # figure error. Subtracting the least-squares plane (piston + x/y tilt over the footprint coordinates
    # u=rho*cos(theta), v=rho*sin(theta)) removes that ramp, so a flat surface imprints EXACTLY 0 and only
    # the deviation FROM flat (the true surface figure) survives. This is the physically correct reference:
    # tip/tilt of the whole mirror is alignment; figure is departure from the reference plane.
    u_l = [rho_l[i] * math.cos(th_l[i]) for i in range(len(samples))]
    v_l = [rho_l[i] * math.sin(th_l[i]) for i in range(len(samples))]
    z_l = [s[2] for s in samples]
    a0, au, av = _plane_fit(u_l, v_l, z_l)                    # depth ~ a0 + au*u + av*v (reference plane)
    # round-trip OPD in beam-path mm: W = 2*cos^2(theta)*(depth - reference_plane). The probe is PARALLEL to
    # the beam, so its depth deviation for a normal sag h is Delta_z = h/cos(theta) (it OVER-reads by 1/cos at
    # AOI theta); the reflection OPD is 2*h*cos(theta); substituting -> 2*Delta_z*cos^2(theta) (oracle ok=true,
    # grazing limit -> 0). cos^2(theta) = 1/(1+(au/w)^2+(av/w)^2) from the reference-plane slope (chief AOI).
    # A protruding (closer) point has a SMALLER along-beam depth -> negative W (advanced); a recess is positive.
    cos2 = 1.0 / (1.0 + (au / w) ** 2 + (av / w) ** 2)
    W_mm = [2.0 * cos2 * (z_l[i] - (a0 + au * u_l[i] + av * v_l[i])) for i in range(len(samples))]
    lam_mm = ray.wl * 1.0e-6                                  # wavelength in mm (wl is nm)
    if lam_mm <= 0.0:
        return None
    W_waves = [wmm / lam_mm for wmm in W_mm]                  # mm -> waves (the aberr/WFS convention)
    coeffs = physics.fit_zernike(rho_l, th_l, W_waves)
    coeffs[0] = 0.0                                           # drop piston (a constant OPD is no aberration)
    if not any(abs(c) > 1e-12 for c in coeffs):
        return None                                           # flat surface -> ~0 -> skip (byte-identical)
    return coeffs


def surface_imprint_field(E, H, d, w, wl_nm, px=128, detrend=True, weight='gaussian', rho_max=1.0):
    """DENSE ZONAL surface-figure -> wavefront map (NO modal fit). Sample reflective element E's ACTUAL
    world-space mesh over the incident Gaussian footprint on a px*px Cartesian grid and return the RAW
    round-trip optical-path field W(x,y) in WAVES -- the SAME verified physics as the modal imprint
    (W = 2*cos^2(theta)*(depth - reference plane): reflection double-passes the figure AND the parallel-to-
    beam probe over-reads a normal sag h as h/cos(theta), so the standard 2*h*cos(theta) OPD becomes
    2*cos^2(theta)*Delta_z; theta = chief AOI from the reference-plane slope; oracle ok=true), but rendered
    ZONALLY instead of projected onto the 15 Noll Zernikes. The modal path is a 15-mode LOW-PASS of this field;
    the zonal field preserves the surface's mid/high-spatial-frequency figure up to the grid's Nyquist
    limit, which a 15-mode fit cannot represent.

    ON-DEMAND ONLY. This is never called inside trace_scene, so every scene still traces byte-identical;
    it is the engine behind the user-facing "sensor render" (ao.zonal_wavefront_at / the WFS operator).
    Independent of imprint_surface (that flag gates the TRACE-path modal aberr; the zonal map is an
    explicit diagnostic the user requests on any reflective mesh).

    Args:
      E        reflective element object (its world-space mesh IS the optical surface)
      H        chief-ray hit point on E (world; the footprint centre)
      d        incident ray direction (world; normalized internally)
      w        footprint radius (mm; the 1/e^2 Gaussian radius at the hit)
      wl_nm    wavelength (nm) for the mm -> waves conversion
      px       grid resolution across the footprint DIAMETER (the "chosen sampling level"); higher = finer
      detrend  remove the best-fit reference plane (piston + x/y tilt) so a flat/tilted mirror reads ~0
      weight   how the BEAM samples the footprint. 'gaussian' (default): weight every sample by the beam
               intensity I = exp(-2*rho^2) (rho = r/w; oracle-verified), so the RMS and the reference plane
               reflect what the GAUSSIAN beam actually senses -- the dim 1/e^2 EDGE counts far less than the
               bright centre (the footprint is NOT a top-hat). 'uniform': flat top-hat = the clear-aperture
               figure-metrology RMS. (The grid samples the rho<=1 disc either way; only the weighting differs.)

    Returns a dict, or None on failure (no mesh / no footprint / <6 hits):
      field            px*px numpy array of W in waves; NaN OUTSIDE the disc or where a probe MISSES
      mask             px*px bool, True where field is valid
      intensity        px*px Gaussian intensity weight exp(-2*rho^2) (NaN outside) -- for fading the map so
                       it shows the actual beam, not a hard top-hat disc
      rms_waves        RMS per ``weight`` (gaussian = the honest "what the beam senses" RMS)
      rms_uniform      uniform top-hat RMS over the disc (the clear-aperture figure metric)
      rms_gauss        Gaussian-intensity-weighted RMS (what the beam measures); <= rms_uniform for edge-heavy
                       figures (the beam's low-intensity wings carry less of the error)
      weight           the weighting actually used ('gaussian' | 'uniform')
      pv_waves         peak-to-valley over the disc (NOT intensity-weighted -- the full range present)
      hit_frac         valid samples / in-disc grid points (sampling completeness; <1 -> mesh gaps)
      n_hit            number of valid samples
      px               the grid resolution used
      footprint_mm     footprint DIAMETER (2*w) in mm
      nyquist_lp_mm    grid Nyquist spatial frequency (px-1)/(2*footprint_mm) line-pairs/mm. This is the
                       SAMPLING cap; the EFFECTIVE resolvable resolution is min(this, the mesh facet
                       density), so a coarsely-tessellated surface can be mesh-limited below this.
    """
    if w is None or w <= 1e-9 or wl_nm is None or wl_nm <= 0.0 or px < 4:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    tree = _build_world_bvhtree(E)
    if tree is None:
        return None
    d = Vector(d).normalized()
    e1v, e2v = physics.transverse_basis((d.x, d.y, d.z))      # disc basis PERP to the beam axis
    e1 = Vector(e1v)
    e2 = Vector(e2v)
    Hc = Vector(H)
    field = np.full((px, px), np.nan, dtype=float)
    ax = np.linspace(-1.0, 1.0, px)                           # normalized footprint coords u,v in [-1,1]
    # rho_max < 1 = an APERTURE STOP downstream (e.g. a sensor smaller than the beam at it): only the central
    # rho <= rho_max of the figure's footprint is carried THROUGH to / captured by the stop. A diverging beam
    # overfills a sensor (rho_max < 1) so its outer figure is clipped; a collimated beam that fits keeps it all.
    rmax2 = max(1e-6, min(1.0, rho_max)) ** 2
    us = []
    vs = []
    zs = []
    cells = []
    n_in = 0
    for iy in range(px):
        v = float(ax[iy])
        for ix in range(px):
            u = float(ax[ix])
            if u * u + v * v > rmax2:
                continue                                      # outside the captured footprint -> stays NaN
            n_in += 1
            P = Hc + e1 * (u * w) + e2 * (v * w)
            origin = P - d * _IMPRINT_BACKUP                  # back up so the probe starts outside the mesh
            loc, nrm, fidx, dist = tree.ray_cast(origin, d)
            if loc is None:
                continue                                      # this footprint point misses the mesh -> NaN
            depth = (Vector(loc) - origin).dot(d)             # along-beam distance to the surface (mm)
            us.append(u)
            vs.append(v)
            zs.append(depth)
            cells.append((iy, ix))
    # gate on COVERAGE, not a raw count: a dense zonal map over a footprint that barely clips the mesh
    # (a handful of hits) would return a confident-looking RMS over a non-representative sliver. Require
    # both >=6 hits and >=10% of the in-disc grid to land on the surface, else the map is not meaningful.
    if len(zs) < 6 or n_in == 0 or float(len(zs)) / float(n_in) < 0.10:
        return None
    # GAUSSIAN BEAM intensity weight per sample: I = exp(-2*rho^2), rho = r/w (oracle-verified). The beam
    # senses the dim 1/e^2 EDGE far less than the bright centre, so a beam-faithful RMS + reference plane are
    # intensity-weighted (the footprint is a Gaussian, not a top-hat). 'uniform' keeps the flat metrology fit.
    use_gauss = (weight != 'uniform')
    Iw = [math.exp(-2.0 * (us[k] * us[k] + vs[k] * vs[k])) for k in range(len(zs))]
    # DETREND against the footprint's best-fit reference plane (piston + x/y tilt) -- a flat mirror returns a
    # linear depth ramp (its overall fold orientation, already carried by geometry.reflect), NOT figure error;
    # subtracting it makes a flat surface read EXACTLY 0. Intensity-weighted when gaussian (the plane tracks
    # where the beam actually is). Same reference convention as the modal path.
    if detrend:
        a0, au, av = _plane_fit(us, vs, zs, weights=(Iw if use_gauss else None))
    else:
        a0 = au = av = 0.0
    # chief-AOI projection: the parallel-to-beam probe over-reads depth by 1/cos(theta), and the reflection
    # OPD is 2*h*cos(theta), so W = 2*cos^2(theta)*(depth - plane) (see _surface_imprint_coeffs; oracle ok=true).
    cos2 = 1.0 / (1.0 + (au / w) ** 2 + (av / w) ** 2)
    lam_mm = wl_nm * 1.0e-6                                   # wavelength in mm (wl is nm)
    intensity = np.full((px, px), np.nan, dtype=float)
    su = sg = swt = 0.0                                       # uniform sum-sq, gaussian wtd sum-sq, sum-of-wts
    wmin = None
    wmax = None
    for k, (iy, ix) in enumerate(cells):
        # round-trip OPD in beam-path mm -> waves: W = 2*cos^2(theta)*(depth - reference plane). A protruding
        # (closer) point has a SMALLER along-beam depth -> negative W (advanced); a recess is positive.
        wv = 2.0 * cos2 * (zs[k] - (a0 + au * us[k] + av * vs[k])) / lam_mm
        field[iy, ix] = wv
        intensity[iy, ix] = Iw[k]
        su += wv * wv
        sg += Iw[k] * wv * wv
        swt += Iw[k]
        wmin = wv if wmin is None else (wv if wv < wmin else wmin)
        wmax = wv if wmax is None else (wv if wv > wmax else wmax)
    n_hit = len(cells)
    rms_uniform = math.sqrt(su / n_hit)                      # flat top-hat (clear-aperture figure metric)
    rms_gauss = math.sqrt(sg / swt) if swt > 0.0 else rms_uniform   # what the Gaussian beam actually senses
    footprint_mm = 2.0 * w
    return {
        "field": field,
        "mask": ~np.isnan(field),
        "intensity": intensity,
        "rms_waves": rms_gauss if use_gauss else rms_uniform,
        "rms_uniform": rms_uniform,
        "rms_gauss": rms_gauss,
        "weight": 'gaussian' if use_gauss else 'uniform',
        "pv_waves": (wmax - wmin) if (wmax is not None and wmin is not None) else 0.0,
        "hit_frac": float(n_hit) / float(n_in),
        "n_hit": n_hit,
        "px": px,
        "footprint_mm": footprint_mm,
        "rho_max": min(1.0, rho_max),                          # downstream-aperture capture fraction (radius)
        "captured_frac": min(1.0, rho_max) ** 2,               # captured AREA fraction of the figure footprint
        # grid Nyquist: px samples span the diameter with spacing footprint/(px-1), so f_Nyq = (px-1)/(2D)
        # (oracle-verified P_min = 2D/(px-1)). Effective resolution = min(this, mesh facet density).
        "nyquist_lp_mm": (px - 1) / (2.0 * footprint_mm) if footprint_mm > 0.0 else 0.0,
    }


def _clip_axis_world(E, roll_deg):
    """World unit vector of a 1-D aperture's CLIPPED transverse axis: the element's local +X rolled by
    ``roll_deg`` about its optical axis (local +Z), then mapped to world. The slit's blades clip the beam
    along this axis (slit_angle); the knife's edge is perpendicular to it (knife_angle)."""
    r = math.radians(roll_deg)
    ax_local = Vector((math.cos(r), math.sin(r), 0.0))
    return (E.matrix_world.to_3x3() @ ax_local).normalized()


def _oe_axis_world(E, cut_deg):
    """World unit vector of a uniaxial crystal's OPTIC AXIS: the element's local +Z (its optical/propagation
    axis, the same convention _clip_axis_world uses) tilted by the cut angle ``cut_deg`` toward local +X, then
    mapped to world. cut=0 -> axis along the beam (no double refraction); cut=45 -> max walk-off."""
    r = math.radians(cut_deg)
    ax_local = Vector((math.sin(r), 0.0, math.cos(r)))
    return (E.matrix_world.to_3x3() @ ax_local).normalized()


def _slit_T(ray, E, H, t):
    """Power transmission of a 1-D SLIT (a pair of blades at +/-b on the clipped axis) on the ray's incident
    Gaussian: T = erf(sqrt2 * b / w) of the part within |x| <= b, MINUS the chief-ray's offset off the slit
    center (so a beam walking off the slit axis is clipped harder). b = slit_width/2, w the incident radius on
    the clipped axis (the model's Gaussian is circular, so the along-axis radius == w). Reuses the VERIFIED
    physics.slit_transmission. A degenerate (no-Gaussian) ray passes (1.0)."""
    w = _w_at(ray, t)
    if w <= 1e-9:
        return 1.0
    b = max(E.optics.slit_width, 0.0) * 0.5
    axis = _clip_axis_world(E, E.optics.slit_angle)
    center = _wc(E)
    off = abs((H - center).dot(axis))                  # chief-ray offset along the clipped axis (~0 if centered)
    # transmit the band [off - b, off + b]: T = 0.5(erf(sqrt2(off+b)/w) + erf(sqrt2(b-off)/w)). When off=0 this
    # reduces to erf(sqrt2 b/w) (the verified centered slit); off>0 shifts the band off the beam, clipping more.
    return 0.5 * (math.erf(math.sqrt(2.0) * (off + b) / w) + math.erf(math.sqrt(2.0) * (b - off) / w))


def _knife_T(ray, E, H, t):
    """Power transmitted PAST a KNIFE_EDGE on its stage: P = 0.5[1 - erf(sqrt2 (e - xc)/w)], where e is the edge
    position (knife_position) on the cut axis, xc the beam chief-ray position on that axis, and w the incident
    radius. Reuses the VERIFIED physics.knife_transmission. Sweeping e across the beam traces the erf profile a
    KNIFE scan fits back to w. A degenerate (no-Gaussian) ray passes (1.0)."""
    w = _w_at(ray, t)
    if w <= 1e-9:
        return 1.0
    axis = _clip_axis_world(E, E.optics.knife_angle)
    center = _wc(E)
    xc = (H - center).dot(axis)                        # chief-ray position on the cut axis (relative to stage center)
    e = E.optics.knife_position
    return physics.knife_transmission(e, xc, w)


# base-10 absorbance at a Schott catalog "cut" wavelength: internal transmittance tau = 0.5 there
# (the standard lambda_c convention), i.e. A_cut = -log10(0.5).
_A_HALF = math.log10(2.0)                                   # ~0.30103
_A_BLOCK = 4.0                                              # deep-stopband absorbance floor (tau ~ 1e-4)
_LN2 = math.log(2.0)                                        # super-Gaussian flat-top half-max normalization (C1 BP)


def _cglass_absorbance(op, wl):
    """Per-wavelength bulk absorbance A(lambda) [base-10, at the REFERENCE thickness d_ref]
    for a colored-glass (Schott RG/GG/OG/BG) absorptive filter. A ~ 0 in the passband (clear,
    only the peak_t Fresnel/residual loss) and rises to a deep floor across a WIDE, SOFT logistic
    edge -- the signature of a bulk-absorptive glass, distinct from the sharp interference cliff.
    The edge is anchored so A == -log10(0.5) AT the catalog cut wavelength (tau=0.5, the standard
    lambda_c), rising toward A_BLOCK deeper in the stopband. Shaped by the FILTER element's cut
    wavelengths: CGLASS_LP passes long lambda, CGLASS_SP passes short, CGLASS_BP passes a band."""
    ft = op.filt_type
    w = max(getattr(op, 'edge_width_nm', 18.0), 1.0)        # soft-edge scale (nm); ~10x softer than an interference filter

    def edge_block_short(lam, cut):
        # longpass: A high BELOW cut, ~0 ABOVE; logistic shifted so A(cut)=_A_HALF (tau=0.5 at lambda_c)
        x = (cut - lam) / w                                 # >0 in the stopband (lam<cut)
        return _A_BLOCK / (1.0 + math.exp(-x) * (_A_BLOCK / _A_HALF - 1.0))

    def edge_block_long(lam, cut):
        # shortpass: A high ABOVE cut, ~0 BELOW; A(cut)=_A_HALF
        x = (lam - cut) / w                                 # >0 in the stopband (lam>cut)
        return _A_BLOCK / (1.0 + math.exp(-x) * (_A_BLOCK / _A_HALF - 1.0))

    if ft == 'CGLASS_LP':
        return edge_block_short(wl, op.cut_lo_nm)
    if ft == 'CGLASS_SP':
        return edge_block_long(wl, op.cut_hi_nm)
    # CGLASS_BP: absorb on BOTH sides of [cut_lo, cut_hi] -> the larger (more-blocking) edge wins
    return max(edge_block_short(wl, op.cut_lo_nm), edge_block_long(wl, op.cut_hi_nm))


def _aoi_blueshift(lam_c, aoi, n_eff):
    """Angle-of-incidence edge/band BLUE-SHIFT of a thin-film interference filter:
    lambda_c_eff = lambda_c * sqrt(1 - (sin theta / n_eff)^2). A tilted dielectric filter
    sees a shorter effective path through the coating stack, so its cut/center wavelength
    moves to the BLUE with increasing angle. n_eff (~1.85) is the effective coating index.
    physics_verify ok=true (4/4): 550nm @ 60deg, n_eff=1.85 -> 486.0nm (a 12% shift)."""
    s = math.sin(aoi) / max(n_eff, 1e-6)
    return lam_c * math.sqrt(max(0.0, 1.0 - s * s))


def _transmission(op, wl, aoi=0.0):
    """Wavelength-dependent power transmission of a filter / attenuator.

    For the dielectric interference filters (LP/SP/BP) the spectral edges are SOFT
    (finite-slope), bottom out at a finite stopband floor (10^-od_block, never exactly 0),
    and blue-shift with the angle of incidence ``aoi`` (radians) -- see _aoi_blueshift (C1).
    The colored-glass (CGLASS_*) bulk-absorption path (C2) is angle-insensitive and untouched."""
    if op.element_type == 'ATTENUATOR':
        return 10.0 ** (-op.od)
    ft = op.filt_type
    if ft == 'ND':
        return 10.0 ** (-op.od)
    if ft in ('LP', 'SP', 'BP'):
        # Thin-film interference filter: SOFT edges + finite OD floor + AOI blue-shift (C1).
        peak = max(0.0, min(getattr(op, 'peak_t', 0.91), 1.0))    # passband transmission T_peak
        floor = 10.0 ** (-max(getattr(op, 'od_block', 4.0), 0.0))  # finite stopband floor (not 0)
        n_eff = max(getattr(op, 'n_eff', 1.85), 1.0)
        span = peak - floor
        if ft == 'LP':                                            # passes LONG lambda; logistic rising edge
            w = max(getattr(op, 'edge_width', 3.0), 1e-6)
            lc = _aoi_blueshift(op.cut_lo_nm, aoi, n_eff)         # edge blue-shifts with angle
            return floor + span / (1.0 + math.exp(-(wl - lc) / w))
        if ft == 'SP':                                            # passes SHORT lambda; sign-flipped logistic
            w = max(getattr(op, 'edge_width', 3.0), 1e-6)
            lc = _aoi_blueshift(op.cut_hi_nm, aoi, n_eff)
            return floor + span / (1.0 + math.exp((wl - lc) / w))
        # BP: order-3 super-Gaussian flat-top centered at the (blue-shifted) CWL.
        # T(cwl)=peak; T = floor + span/2 at |wl-cwl| = fwhm/2 (the half-max points), since the
        # exponent argument is -ln2 * (2|wl-cwl|/fwhm)^(2*order) -> -ln2 at the FWHM half-width.
        cwl = _aoi_blueshift(getattr(op, 'cwl_nm', 550.0), aoi, n_eff)
        fwhm = max(getattr(op, 'fwhm_nm', 40.0), 1e-6)
        order = 3
        u = 2.0 * (wl - cwl) / fwhm
        return floor + span * math.exp(-_LN2 * (u * u) ** order)
    if ft in ('CGLASS_LP', 'CGLASS_SP', 'CGLASS_BP'):
        # Colored-glass BULK absorption (C2). Beer-Lambert, thickness-scaled by the oracle-VERIFIED
        # Schott TIE-35 power law:  T = peak_t * 10^(-A(lambda) * d / d_ref)
        #   == peak_t * (10^(-A))^(d/d_ref),  i.e. tau(d2) = tau(d1)^(d2/d1).
        # Angle-INSENSITIVE (no AOI edge shift -- that is task C1); the path is undeviated (flat window).
        d = max(getattr(op, 'thickness_mm', 3.0), 1e-6)
        d_ref = max(getattr(op, 'd_ref_mm', 3.0), 1e-6)
        peak = max(0.0, min(getattr(op, 'peak_t', 0.91), 1.0))
        A = _cglass_absorbance(op, wl)
        return peak * 10.0 ** (-A * d / d_ref)
    return 1.0


def _dichroic_reflectance(op, wl, aoi=0.0):
    """Soft-edge dichroic reflectance R(lambda) in [0, 1] for a wavelength-selective mirror. IDEAL
    lossless: the transmitted fraction is T = 1 - R, so energy is conserved exactly (R + T = 1). A
    LONGPASS dichroic transmits long lambda (reflects short); a SHORTPASS transmits short (reflects
    long); the edge is a logistic of width ``edge_width`` (nm) centred at ``cut_nm`` (R(cut) = 0.5), so
    NEAR the cut the beam PARTIALLY reflects AND transmits -- the finite-slope edge a real coating has,
    not an all-or-nothing step (a narrow edge_width recovers the step). A BANDPASS dichroic reflects
    OUTSIDE its passband. The edge SHAPE is a Tier-1 modelling choice (like the interference-filter
    logistics); the physics it must obey -- energy conservation R + T = 1 -- is exact by construction.

    Like the interference filters, the cut wavelength(s) BLUE-SHIFT with the angle of incidence ``aoi``
    (radians): lambda_eff = lambda * sqrt(1 - (sin aoi / n_eff)^2) via _aoi_blueshift -- a 45-deg dichroic
    edge sits ~8% to the blue of its normal-incidence spec (the well-known fluorescence-microscopy gotcha).
    aoi=0 -> no shift (byte-identical at normal incidence)."""
    n_eff = max(getattr(op, 'n_eff', 1.85), 1.0)
    cut_raw = getattr(op, 'cut_nm', 650.0)
    cut = _aoi_blueshift(cut_raw, aoi, n_eff)
    w = max(getattr(op, 'edge_width', 3.0), 1e-6)
    pt = getattr(op, 'pass_type', 'LP')
    if pt == 'SP':                          # transmit short -> reflect long: rising edge
        return 1.0 / (1.0 + math.exp(-(wl - cut) / w))
    if pt == 'BP':                          # reflect OUTSIDE the passband [cut_lo, cut_hi]
        lo = _aoi_blueshift(getattr(op, 'cut_lo_nm', cut_raw - 20.0), aoi, n_eff)
        hi = _aoi_blueshift(getattr(op, 'cut_hi_nm', cut_raw + 20.0), aoi, n_eff)
        t_band = (1.0 / (1.0 + math.exp(-(wl - lo) / w))) * (1.0 / (1.0 + math.exp((wl - hi) / w)))
        return 1.0 - t_band
    return 1.0 / (1.0 + math.exp((wl - cut) / w))   # LP (default): transmit long -> reflect short


def _diffract(d, n, wl_nm, lines_per_mm, order):
    """Grating equation in the plane of incidence: sin(theta_m) = sin(theta_i) +
    m*lambda/d, d = 1/lines_per_mm. 0th order -> specular; an evanescent order
    (|sin|>1) returns None so the caller can fall back to specular."""
    if order == 0 or lines_per_mm <= 0.0:
        return geometry.reflect(d, n)
    n_in = n if d.dot(n) < 0.0 else -n              # normal facing the incoming ray
    d_t = d - d.dot(n_in) * n_in
    sin_i = d_t.length
    t_hat = (d_t / sin_i) if sin_i > 1e-9 else n_in.orthogonal().normalized()
    sin_m = sin_i + order * (wl_nm * 1.0e-6) * lines_per_mm
    if abs(sin_m) > 1.0:
        return None
    cos_m = math.sqrt(max(0.0, 1.0 - sin_m * sin_m))
    return (sin_m * t_hat + cos_m * n_in).normalized()


def _prism_faces(E):
    """World (point, outward-normal) of a prism's entry (IN) and exit (OUT) faces."""
    op = E.optics
    ip, opo = _find_port(op, 'IN'), _find_port(op, 'OUT')
    pin = (_wp(E, ip.local_position), geometry.world_normal(E, ip.local_normal)) if ip else None
    pout = (_wp(E, opo.local_position), geometry.world_normal(E, opo.local_normal)) if opo else None
    return pin, pout


def _glass_seg(ray, p2, E, n_glass, kind):
    """Emit an IN-GLASS segment from ray.p1 to p2 inside element E: the optical path advances by n*L
    (the glass index), and the dict mirrors _seg's schema so bake/overlay/digest treat it uniformly."""
    seg_len = (p2 - ray.p1).length
    opl = ray.opl + n_glass * seg_len            # glass optical path: n * geometric length
    lam_mm = ray.wl * 1.0e-6
    phase = (2.0 * math.pi * opl / lam_mm) if lam_mm > 0.0 else 0.0
    j = ray.jones
    qd = physics.q_propagate(ray.q, physics.abcd_free(seg_len)) if ray.q is not None else None
    return {
        "p1": ray.p1 / _mmpu, "p2": p2 / _mmpu, "kind": kind,
        "from": ray.from_obj.name if ray.from_obj else None,
        "to": E.name if E else None,
        "power": round(ray.power, 4), "wavelength": ray.wl, "parent": ray.parent,
        "jones": [j[0].real, j[0].imag, j[1].real, j[1].imag] if j else None,
        "opl": opl, "phase": phase, "src_id": ray.src_id, "coh": ray.coh,
        "w_mm": physics.beam_radius_m2(qd, ray.wl, ray.m2) if qd is not None else 0.0,
        "qd": [qd.real, qd.imag] if qd is not None else None,
        "m2": ray.m2,
        "aberr": list(ray.aberr) if ray.aberr else None,
    }, opl, qd


def _prism_exit_ray(glass_ray, E, He, d_out, opl_exit, power, parent_idx):
    """Continuation ray leaving a prism's exit face at He along d_out, carrying the accumulated optical path
    (opl_exit, already including the glass n*L legs) and the propagated Gaussian q. Polarization is rebuilt
    on the new direction. from_obj = E so the ray won't immediately re-hit the prism it just left."""
    nj = glass_ray.jones
    nev = physics.field_from_jones(nj, d_out) if nj is not None else None
    return _Ray(He, d_out, power, glass_ray.depth + 1, E, glass_ray.wl, 'TRANSMIT', parent_idx,
                jones=nj, opl=opl_exit, q=glass_ray.q, src_id=glass_ray.src_id, coh=glass_ray.coh,
                evec=nev, m2=glass_ray.m2)


# C4 routing-prism fold faces, in ORDER, by prism_type. Each is a port NAME (role REFLECT) carrying the
# world geometry of one internal mirror face the chief ray reflects off (geometry.reflect). A routing prism
# is thus a fixed PRODUCT of plane reflections + the C3 entry/exit Snell: the number of folds sets the image
# parity (EVEN = handedness preserved, ODD = flipped). corner-cube is the existing RETROREFLECTOR (not here).
_ROUTING_FOLDS = {
    'RIGHT_ANGLE': ('FOLD1',),                  # 1 reflection -> 90 deg, parity FLIP
    'DOVE':        ('FOLD1',),                  # 1 reflection -> in-line; image rotates 2x roll
    'PENTA':       ('FOLD1', 'FOLD2'),          # 2 reflections -> constant 90 deg, tilt-invariant, parity preserved
    'ROOF':        ('FOLD1', 'FOLD2'),          # 2 reflections off a 90 deg roof -> retro-ish, parity flip
    'RHOMBOID':    ('FOLD1', 'FOLD2'),          # 2 PARALLEL reflections -> pure lateral offset, output parallel
}


def _route_fold(glass_ray, E, fold_faces, segments, parent_idx, n_glass):
    """Fold an in-glass ray through a routing prism's internal mirror faces IN ORDER. Each fold is a single
    geometry.reflect() off the face's world normal -- the verified reflection law -- with the segment break
    taken at the face's port-plane crossing; the in-glass OPL advances by n*L per leg (_glass_seg). Returns
    the post-fold in-glass ray (ready for the exit-face Snell refraction), or None if a leg cannot be solved.
    Polarization rides along via reflect_field (ideal-mirror rs=1, rp=-1, like the C3 LITTROW/P-B folds)."""
    ray = glass_ray
    for (fpt, fnrm) in fold_faces:
        hb = _ray_plane(ray.p1, ray.dir, fpt, fnrm)
        Hb = hb[0] if hb is not None else (ray.p1 + ray.dir * 1.0)
        gseg, opl_b, _qd = _glass_seg(ray, Hb, E, n_glass, 'GLASS')
        segments.append(gseg)
        d_fold = geometry.reflect(ray.dir, fnrm)
        if ray.evec is not None:
            ev, _do = physics.reflect_field(ray.evec, ray.dir, fnrm, 1.0, -1.0)
        else:
            ev = None
        ray = _Ray(Hb, d_fold, ray.power, ray.depth + 1, E, ray.wl, 'GLASS', parent_idx,
                   jones=ray.jones, opl=opl_b, q=ray.q, src_id=ray.src_id, coh=ray.coh,
                   evec=ev, m2=ray.m2)
    return ray


def trace_scene(scene, mode='AUTO', max_segments=64, max_depth=12):
    global _mmpu
    _mmpu = geometry.mm_per_unit(scene)   # 1.0 unless the scene declares its units authoritative
    elems = [o for o in scene.objects
             if getattr(o, "optics", None) and o.optics.is_optical]
    order = _order_list(scene)
    order_index = {}
    for i, name in enumerate(order):
        order_index.setdefault(name, i)
    element_by_name = {}
    geometry_table = []
    for E in elems:
        surface = interaction_surface(E)
        if _mmpu != 1.0 and surface[0] is not None:   # the trace works in mm; this helper
            surface = (surface[0] * _mmpu, surface[1], surface[2])   # stays world for diagnostics
        port_surfaces = []
        if E.optics.element_type == 'CIRCULATOR':
            for p in _circulator_ports(E.optics):
                port_surfaces.append((_wp(E, p.local_position),
                                      geometry.world_normal(E, p.local_normal),
                                      p.clear_aperture or E.optics.clear_aperture))
        record = (E, surface, port_surfaces)
        geometry_table.append(record)
        element_by_name.setdefault(E.name, record)

    # A9 ghost back-reflection config (OPT-IN). Default OFF -> gcfg[0] is False -> _spawn_ghost is a
    # no-op everywhere, so every existing scene traces BYTE-IDENTICAL. Only turned on explicitly.
    sopt = getattr(scene, 'optics', None)
    gcfg = (bool(getattr(sopt, 'model_ghosts', False)),
            float(getattr(sopt, 'ghost_floor', 1.0e-3)),
            int(getattr(sopt, 'max_ghost_depth', 2))) if sopt else (False, 1.0e-3, 2)

    stack = []
    sid = 0
    for src in elems:
        if src.optics.element_type in ('SOURCE', 'FIBER_COLLIMATOR') or src.optics.is_source:
            op = _first_out(src.optics)
            if op is None:
                continue
            sp = src.optics
            if sp.pol_type == 'CIRCULAR':
                emit = [(physics.jones_circular(sp.handedness), 1.0)]
            elif sp.pol_type == 'UNPOL':
                # unpolarized = incoherent H + V (half power each), in distinct
                # coherence groups so they never interfere with one another
                emit = [(physics.jones_linear(0.0, math.sqrt(0.5)), 0.5),
                        (physics.jones_linear(90.0, math.sqrt(0.5)), 0.5)]
            else:
                emit = [(physics.jones_linear(sp.pol_angle), 1.0)]
            # spectrum: a single line, or (broadband) a Gaussian-weighted set of
            # mutually-incoherent wavelengths -> a white-light fringe packet
            bw = getattr(sp, 'bandwidth_nm', 0.0)
            if bw > 0.0:
                Nw = 11
                sigma = bw / 2.355
                wls = [sp.wavelength + bw * (i / (Nw - 1) - 0.5) for i in range(Nw)]
                # drop non-physical (<=0) lines FIRST, then normalize over the survivors, so a wide
                # band around a small center wavelength doesn't silently lose the clipped lines'
                # power (the source would emit < its nominal unit power)
                pairs = [(w, math.exp(-0.5 * ((w - sp.wavelength) / sigma) ** 2)) for w in wls if w > 0.0]
                tw = sum(wt for _w, wt in pairs) or 1.0
                spectrum = [(w, wt / tw) for w, wt in pairs]
            else:
                spectrum = [(sp.wavelength, 1.0)]
            P = _wp(src, op.local_position)
            D = geometry.world_normal(src, op.local_normal)
            m2 = max(getattr(sp, 'm2', 1.0), 1.0)
            for wl_i, sw in spectrum:
                # B1 beam quality M^2: emit the EMBEDDED Gaussian q (q_from_waist scales
                # zR -> zR/M2, i.e. an embedded waist w0/M). The ray carries m2 so every
                # *physical* radius is read as sqrt(m2)*beam_radius(q) -> the far-field
                # divergence broadens by exactly M2 = M^2*lambda/(pi*w0). m2=1 -> unchanged.
                q0 = physics.q_from_waist(max(sp.waist_um, 1.0) * 1.0e-3, wl_i, m2)
                coh0 = min(physics.coherence_length_mm(wl_i, sp.linewidth_nm), 1.0e12)
                for jv, pw in emit:
                    js = physics.scale(jv, math.sqrt(sw))
                    stack.append(_Ray(P, D, pw * sw, 0, src, wl_i, 'SOURCE', -1,
                                      jones=js, opl=0.0, q=q0, src_id=sid, coh=coh0,
                                      evec=physics.field_from_jones(js, D), m2=m2))
                    sid += 1

    segments = []
    guard = 0
    while stack and len(segments) < max_segments and guard < max_segments * 8:
        guard += 1
        ray = stack.pop()
        if ray.depth > max_depth or ray.power < 1e-4:    # keep weak beams (e.g. polarizer extinction floor)
            continue

        hit = _find_next(geometry_table, ray, mode, order, order_index, element_by_name)
        if hit is None:
            segments.append(_seg(ray, ray.p1 + ray.dir * EXTEND_MM, None))
            continue

        t, E, H, sn = hit
        idx = len(segments)
        segments.append(_seg(ray, H, E, sn))
        et = E.optics.element_type
        op = E.optics

        if et in ('CRYSTAL', 'WAVEPLATE') and getattr(op, 'oe_split', False):
            # TRUE ordinary/extraordinary SPATIAL double refraction (A-tier birefringence; opt-in, default
            # OFF -> byte-identical for every scene that doesn't set it). One incident ray forks into an
            # ORDINARY child (pol perpendicular to the principal plane, index n_o) and an EXTRAORDINARY child
            # (pol in-plane, walking off by rho). Modeled as a uniaxial SLAB: both exit PARALLEL to the input,
            # the e-beam laterally displaced by L*tan(rho) (the textbook calcite double image -- a FIXED
            # displacement set by the crystal thickness, not the screen distance), so we offset the e-child's
            # emission point rather than tilt it. The o/e power split is Malus on the eigen-axes.
            mat = getattr(op, 'oe_material', 'CALCITE')
            n_o = physics.sellmeier_n(ray.wl, mat + '_O')
            n_e = physics.sellmeier_n(ray.wl, mat + '_E')
            axis_w = _oe_axis_world(E, getattr(op, 'oe_axis_deg', 45.0))
            _theta, rho, pol_o, pol_e, walk = physics.oe_split_geometry(
                (ray.dir.x, ray.dir.y, ray.dir.z), (axis_w.x, axis_w.y, axis_w.z), n_o, n_e)
            ev = ray.evec if ray.evec is not None else (
                physics.field_from_jones(ray.jones, ray.dir) if ray.jones is not None else None)
            if ev is not None:
                Eo = ev[0] * pol_o[0] + ev[1] * pol_o[1] + ev[2] * pol_o[2]     # complex projections
                Ee = ev[0] * pol_e[0] + ev[1] * pol_e[1] + ev[2] * pol_e[2]
                tot = (abs(ev[0]) ** 2 + abs(ev[1]) ** 2 + abs(ev[2]) ** 2) or 1.0
                fo, fe = abs(Eo) ** 2 / tot, abs(Ee) ** 2 / tot
                evec_o = (Eo * pol_o[0], Eo * pol_o[1], Eo * pol_o[2])
                evec_e = (Ee * pol_e[0], Ee * pol_e[1], Ee * pol_e[2])
            else:                                                              # unpolarized -> 50/50, each pol'd
                fo = fe = 0.5
                evec_o = (complex(pol_o[0]), complex(pol_o[1]), complex(pol_o[2]))
                evec_e = (complex(pol_e[0]), complex(pol_e[1]), complex(pol_e[2]))
            L = getattr(op, 'oe_length_mm', 10.0)
            Hoff = H + Vector(walk) * (L * math.tan(math.radians(rho)))         # fixed slab displacement
            stack.append(_child(ray, E, H, ray.dir, ray.power * fo, 'SPLIT_O', idx, t, evec=evec_o))
            stack.append(_child(ray, E, Hoff, ray.dir, ray.power * fe, 'SPLIT_E', idx, t, evec=evec_e))
            continue

        if et == 'CRYSTAL':
            # chi(2) nonlinear family (C7). Every child sits at the ENERGY-conserving wavelength
            # (physics.nl_child_wavelength, each oracle-VERIFIED): SHG lam/2, THG lam/3, SFG/DFG
            # 1/l3=1/l1+-1/l2, OPO pump->signal+idler, SPDC degenerate 2*lam. The residual pump
            # transmits; NONE just dumps the pump (legacy behavior the Bell example relies on).
            proc = getattr(op, 'nl_process', 'NONE')
            l2 = getattr(op, 'nl_lambda2_nm', None)
            pmt = getattr(op, 'phase_matching_type', 'TYPE1')
            scheme = getattr(op, 'pm_scheme', 'CRITICAL')
            # the conversion is gated by the sinc^2(dk*L/2) phase-matching factor (the physically
            # central, temperature-tunable part). At the crystal's phase-matched temperature dk=0 ->
            # sinc^2=1, so the default (T=25 C, BBO T_pm=25 C) leaves the legacy efficiency UNCHANGED
            # -> SHG/SPDC + the Bell pump-dump stay byte-identical. A TEMPERATURE scan rides this curve.
            mat = getattr(op, 'crystal_material', 'BBO')
            L_mm = getattr(op, 'crystal_length_mm', 10.0)
            dk = physics.nl_phase_mismatch_T(mat, getattr(op, 'crystal_temp_C', 25.0))
            pm_eff = physics.phase_match_efficiency(dk, L_mm)
            if getattr(op, 'use_chi2_solver', False):
                # chi(2) TENSOR SOLVER (opt-in): the conversion efficiency from the full Manley-Rowe
                # coupled-wave ODE (pump depletion + phase mismatch), driven by deff / length / pump power
                # -- not the static nl_efficiency scalar. At the phase-matched point this is tanh^2(sqrt(eta_lin)).
                deff = physics.NL_CRYSTALS.get((mat or 'BBO').upper(), physics.NL_CRYSTALS['BBO'])[0]
                eff = physics.chi2_solve(deff, L_mm, getattr(op, 'nl_pump_power_W', 1.0), dk)
            else:
                eff = getattr(op, 'nl_efficiency', 0.4) * pm_eff

            def _q_at(wl_out):
                """Tier-1 MODELING CHOICE (not an oracle-verified law): seed the converted beam with a
                fresh Gaussian waist equal to the pump's spot size at the crystal, at the new wl."""
                if ray.q is None:
                    return None
                qpc = physics.q_propagate(ray.q, physics.abcd_free(t))
                return physics.q_from_waist(
                    max(physics.beam_radius_m2(qpc, ray.wl, ray.m2), 1.0e-3), wl_out)

            # CRITICAL phase matching has spatial WALK-OFF: the extraordinary child drifts off the
            # pump axis by a small transverse offset (NCPM/QPM ~= zero). The drift is along the first
            # transverse basis vector; it does NOT change the wavelength/energy (only the geometry).
            def _emit_pt(walk):
                if walk <= 0.0 or scheme != 'CRITICAL':
                    return H
                u, _v = physics.transverse_basis(ray.dir)
                return H + Vector(u) * walk
            woff = getattr(op, 'nl_walkoff_mm', 0.0)
            if getattr(op, 'use_chi2_solver', False):
                _sw = physics.shg_walkoff_mm(mat, ray.wl, L_mm, pmt)   # replace-when-on: Sellmeier rho (per type)
                if _sw > 0.0:
                    woff = _sw                                     # (else fall back to the literal)

            if proc in ('SHG', 'THG'):
                wco = physics.nl_child_wavelength(proc, ray.wl)
                # child Jones per phase-matching type: TYPE-I harmonic is orthogonal to the (o-pol)
                # pump; TYPE-0 keeps the pump pol; TYPE-II is treated as TYPE-I for the single harmonic.
                hj = (physics.jones_linear(90.0) if (pmt in ('TYPE1', 'TYPE2') and ray.jones)
                      else ray.jones)
                stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eff), 'TRANSMIT', idx, t,
                                    jones=ray.jones))       # residual unconverted pump
                stack.append(_child(ray, E, _emit_pt(woff), ray.dir, ray.power * eff, proc, idx, t,
                                    jones=hj, q=_q_at(wco), wl=wco))
            elif proc in ('SFG', 'DFG'):
                wco = physics.nl_child_wavelength(proc, ray.wl, l2)
                if wco is not None:
                    hj = (physics.jones_linear(90.0) if (pmt in ('TYPE1', 'TYPE2') and ray.jones)
                          else ray.jones)
                    stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eff), 'TRANSMIT', idx, t,
                                        jones=ray.jones))   # residual unconverted pump
                    stack.append(_child(ray, E, _emit_pt(woff), ray.dir, ray.power * eff, proc, idx, t,
                                        jones=hj, q=_q_at(wco), wl=wco))
                else:
                    continue                                 # no physical child -> pump dumped
            elif proc == 'OPO':
                # pump splits into a seeded signal (l2) + the energy-conserving idler.
                wsig = l2
                widl = physics.nl_child_wavelength('OPO', ray.wl, l2)
                if widl is not None and wsig:
                    # TYPE-II: signal/idler in ORTHOGONAL polarizations (the entanglement structure);
                    # TYPE-0/I: parallel. Walk-off separates them transversely (CRITICAL).
                    js = physics.jones_linear(0.0) if ray.jones else None
                    ji = physics.jones_linear(90.0 if pmt == 'TYPE2' else 0.0) if ray.jones else None
                    stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eff), 'TRANSMIT', idx, t,
                                        jones=ray.jones))   # residual unconverted pump
                    stack.append(_child(ray, E, _emit_pt(0.0), ray.dir, ray.power * eff * 0.5, 'SIGNAL',
                                        idx, t, jones=js, q=_q_at(wsig), wl=wsig))
                    stack.append(_child(ray, E, _emit_pt(woff), ray.dir, ray.power * eff * 0.5, 'IDLER',
                                        idx, t, jones=ji, q=_q_at(widl), wl=widl))
                else:
                    continue
            elif proc == 'SPDC':
                wco = physics.nl_child_wavelength('SPDC', ray.wl)   # degenerate 2*lam
                q_conv = _q_at(wco)
                # TYPE-II SPDC: signal o-pol, idler e-pol (the polarization-entangled twin); TYPE-I both same.
                js = physics.jones_linear(0.0) if ray.jones else ray.jones
                ji = physics.jones_linear(90.0 if pmt == 'TYPE2' else 0.0) if ray.jones else ray.jones
                stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eff), 'TRANSMIT', idx, t,
                                    jones=ray.jones))       # residual unconverted pump
                stack.append(_child(ray, E, H, ray.dir, ray.power * eff * 0.5, 'SIGNAL', idx, t,
                                    jones=js, q=q_conv, wl=wco))
                stack.append(_child(ray, E, _emit_pt(woff), ray.dir, ray.power * eff * 0.5, 'IDLER', idx, t,
                                    jones=ji, q=q_conv, wl=wco))
            continue                                         # NONE / unhandled: pump dumped

        if et == 'CIRCULATOR':
            # NON-RECIPROCAL N-port cyclic router (a fiber-optic circulator). A ray entering port Pi EXITS
            # from the NEXT port P(i+1) in the cycle (P1->P2->P3->...->P1). It is non-reciprocal: a ray into
            # P2 exits P3, NOT back to P1 -- the defining property. A small ISOLATION leak goes to the
            # PREVIOUS port P(i-1) at power T * 10^(-isolation_db/10) (physics.db_to_linear, the standard
            # dB->linear). Pol-INDEPENDENT at the ray level: the polarization state is unchanged while its
            # amplitude tracks the power bookkeeping (a real
            # free-space circulator is PBS+Faraday+HWP, but the chief-ray topology just routes ports). This is
            # a pure ROUTING topology over the existing port machinery -- NO new optical formula but the
            # dimensionless isolation ratio. Each child leaves FROM its port's world position along that
            # port's OUTWARD normal (world_port / world_normal), so a rotated mount re-aims every leg.
            # Model the internal route as a straight free-space path of the geometric port-to-port length.
            # It carries OPL and Gaussian propagation, while remaining an idealization of the real
            # PBS/Faraday assembly: no dispersion and n = 1.
            ports = _circulator_ports(op)
            N = len(ports)
            if N >= 2:
                # identify the ENTRY port: the one whose world position is nearest the hit point H (the
                # face the ray actually crossed). _find_next already gated H to a single port's aperture.
                entry = min(range(N), key=lambda k: (_wp(E, ports[k].local_position) - H).length)
                T_thru = min(max(getattr(op, 'element_transmittance', 1.0), 0.0), 1.0)   # universal insertion loss (default 1.0)
                iso_lin = physics.db_to_linear(max(getattr(op, 'isolation_db', 20.0), 0.0))
                nxt = ports[(entry + 1) % N]                # main path -> NEXT port (the cyclic route)
                prv = ports[(entry - 1) % N]                # isolation leak -> PREVIOUS port (non-reciprocity is here)
                # main child: through power from P(i+1) along its outward normal; polarization state unchanged.
                Pn = _wp(E, nxt.local_position)
                Dn = geometry.world_normal(E, nxt.local_normal)
                jn = (ray.jones if T_thru == 1.0 else
                      physics.scale(ray.jones, math.sqrt(T_thru)) if ray.jones else None)
                t_eff = t + (Pn - H).length
                stack.append(_child(ray, E, Pn, Dn, ray.power * T_thru, 'CIRC_OUT', idx, t_eff, jones=jn))
                # isolation child: the small directivity leak from P(i-1). Same energy bookkeeping as the
                # through path scaled by the dB ratio; pol carried unchanged (sqrt for the field amplitude).
                if prv is not nxt and ray.power * T_thru * iso_lin >= 1e-9:
                    Pp = _wp(E, prv.local_position)
                    Dp = geometry.world_normal(E, prv.local_normal)
                    ji = (physics.scale(ray.jones, math.sqrt(iso_lin)) if T_thru == 1.0 and ray.jones else
                          physics.scale(ray.jones, math.sqrt(T_thru * iso_lin)) if ray.jones else None)
                    t_eff = t + (Pp - H).length
                    stack.append(_child(ray, E, Pp, Dp, ray.power * T_thru * iso_lin, 'CIRC_ISO', idx, t_eff,
                                        jones=ji))
            continue

        if et in TERMINAL:
            continue
        J = ray.jones
        if et == 'SHUTTER':
            # An ideal binary bench shutter: OPEN is a lossless, undeviated continuation;
            # CLOSED absorbs the incident ray, so no child is emitted.  This is deliberately
            # state/topology only -- finite extinction and switching time are not modeled.
            if getattr(op, 'shutter_open', True):
                stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
            continue
        if et == 'APERTURE':
            Tc = _clip_T(ray, E, t)
            stack.append(_child(ray, E, H, ray.dir, ray.power * Tc, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(Tc)) if J else None))
            continue
        if et == 'SLIT':
            # 1-D (anisotropic) clip: scale power by the verified slit erf along the clipped axis. The path is
            # undeviated (a slit transmits straight through); only the transmitted POWER changes with the width.
            Tc = _slit_T(ray, E, H, t)
            stack.append(_child(ray, E, H, ray.dir, ray.power * Tc, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(max(Tc, 0.0))) if J else None))
            continue
        if et == 'KNIFE_EDGE':
            # half-plane clip: scale power by the verified knife erf (the part of the beam past the edge). The
            # path is undeviated; sweeping knife_position across the beam gives the erf knife-edge profile.
            Tc = _knife_T(ray, E, H, t)
            stack.append(_child(ray, E, H, ray.dir, ray.power * Tc, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(max(Tc, 0.0))) if J else None))
            continue
        if et == 'RETROREFLECTOR':
            # Corner cube: angle-insensitive retroreflection d_out = -d_in. A flat-mirror
            # reflect would deviate the return beam by 2*theta under tip/tilt -- a real
            # corner cube does not, so a specular model reports misalignment that does not
            # physically exist. Tier-1 polarization: ideal scalar reflectivity (a real cube
            # rotates polarization per sextant; out of scope for the chief-ray model).
            #
            # THIN-ELEMENT IDEALIZATION -- the internal path is deliberately NOT modelled (#30).
            # The beam turns on the REFLECT plane and the trihedral depth costs it nothing. A real
            # corner cube instead runs in to the apex and back out, adding 2*d of geometric path
            # (2*n*d in a solid cube). That term is EXACT, not approximate, and identical for every
            # ray in the aperture -- the constant-path property corner cubes are used for. Verified
            # by tracing three perpendicular mirrors: six entry points, total path 2d to within
            # 1e-9, independent of entry point.
            # It is omitted because the element carries NO depth parameter -- the mesh's apex is a
            # cosmetic proportion (_corner_cube uses size*0.6) and this tracer never reads the mesh,
            # so there is no physical depth here to charge for. Consequence to know: direction and
            # power are right, but OPL through a retroreflector is the thin-element value. In an
            # interferometer the missing 2*d is a constant piston in that arm -- it shifts fringe
            # POSITION without distorting the wavefront. Model the standoff explicitly if it matters.
            nd = (-ray.dir).normalized()
            if ray.evec is not None:
                a = math.sqrt(max(op.reflectivity, 0.0))
                ev = (ray.evec[0] * a, ray.evec[1] * a, ray.evec[2] * a)
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t, evec=ev))
            else:
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t, jones=None))
        elif et in ('MIRROR', 'PRISM_MIRROR'):
            nd = geometry.reflect(ray.dir, sn)
            # SURFACE-FIGURE IMPRINT (opt-in, default off): sample E's actual mesh over the Gaussian
            # footprint and stamp its Zernike surface figure onto the reflected wavefront (sign +1, like
            # an ABERRATOR). None -> no change -> byte-identical; a flat surface -> ~0.
            imp = _surface_imprint_coeffs(E, ray, H, sn, t)
            ab = _aberr_combine(ray.aberr, imp, 1.0) if imp is not None else None
            if ray.evec is not None and getattr(op, 'coating', 'DIELECTRIC') != 'DIELECTRIC':
                # metal mirror: exact s/p Fresnel in the TRUE plane of incidence (d x n),
                # so off-axis reflection rotates azimuth / adds the right s-p phase
                theta = math.acos(min(1.0, abs(ray.dir.dot(sn))))
                mc = (physics.metal_nk(op.coating, ray.wl)        # opt-in dispersive n,k(lambda)
                      if getattr(op, 'dispersive_metal', False) and getattr(ray, 'wl', 0.0) > 0.0
                      else physics.METALS.get(op.coating, physics.METALS['AL']))
                rs, rp = physics.fresnel_reflect(1.0, mc, theta)
                ev, _do = physics.reflect_field(ray.evec, ray.dir, sn, rs, rp)
                pw = sum((c * c.conjugate()).real for c in ev)
                stack.append(_child(ray, E, H, nd, pw, 'REFLECT', idx, t, evec=ev, aberr=ab))
            elif ray.evec is not None:
                # dielectric / ideal mirror: exact 3-D reflection with the Fresnel sign
                # convention rp = -rs (a perfect conductor has rs=-1, rp=+1), so at normal
                # incidence the lab-frame polarization is preserved (both interferometer
                # arms transform identically -> visibility stays 1)
                a = math.sqrt(max(op.reflectivity, 0.0))
                ev, _do = physics.reflect_field(ray.evec, ray.dir, sn, a, -a)
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t, evec=ev, aberr=ab))
            else:
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t, jones=None, aberr=ab))
        elif et == 'GRATING':
            nd = _diffract(ray.dir, sn, ray.wl, op.lines_per_mm, op.grating_order)
            if nd is None:
                nd = geometry.reflect(ray.dir, sn)         # evanescent order -> specular
            a = math.sqrt(max(op.reflectivity, 0.0))
            if ray.evec is not None:
                # carry s/p through the TRUE plane of incidence onto the diffracted
                # direction (frame-robust), instead of rebuilding a 2-D Jones in the
                # new direction's arbitrary transverse basis
                ev = physics.redirect_field(ray.evec, ray.dir, nd, sn, a, -a)
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t, evec=ev))
            else:
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t,
                                    jones=physics.scale(J, a) if J else None))
        elif et == 'AOM':
            # Acousto-optic Bragg cell: a travelling acoustic grating (period Lam = v_s/f_a) diffracts a
            # fraction (efficiency) into the +1 order at the deflection angle theta = lambda/Lam =
            # lambda*f_a/v_s (VERIFIED acousto-optic-bragg-deflection), which is frequency-shifted by +f_a.
            # The undiffracted 0th order passes straight through. The deflection is pure geometry (rotate
            # about the acoustic axis = local Y); a phase grating leaves polarization unchanged, so only the
            # power is split. The optical-frequency shift (~1e-7 of lambda) is below the model's wavelength
            # resolution, so it is carried as the aom_freq_mhz parameter (metadata) rather than as a dlambda.
            f_a = max(getattr(op, 'aom_freq_mhz', 80.0), 0.0) * 1.0e6        # Hz
            v_s = max(getattr(op, 'aom_sound_mps', 4200.0), 1.0)            # m/s
            eta = min(max(getattr(op, 'aom_efficiency', 0.85), 0.0), 1.0)
            theta = (ray.wl * 1.0e-9) * f_a / v_s                          # rad; lambda[m]*f_a/v_s
            # acoustic wave runs along local Y -> the beam (local Z) diffracts in the Y-Z plane, so the
            # deflection is a rotation about local X (perpendicular to that plane).
            ax = (E.matrix_world.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
            d1 = (Matrix.Rotation(theta, 3, ax) @ ray.dir).normalized()    # +1 diffracted order (toward +Y)
            s0, s1 = math.sqrt(max(1.0 - eta, 0.0)), math.sqrt(eta)
            if ray.evec is not None:
                ev0 = (ray.evec[0] * s0, ray.evec[1] * s0, ray.evec[2] * s0)          # 0th: scaled, undeviated
                ev1 = physics.redirect_field(ray.evec, ray.dir, d1, sn, s1, s1)        # +1: isotropic redirect
                stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eta), 'TRANSMIT', idx, t, evec=ev0))
                stack.append(_child(ray, E, H, d1, ray.power * eta, 'AOM_1', idx, t, evec=ev1))
            else:
                stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - eta), 'TRANSMIT', idx, t,
                                    jones=physics.scale(J, s0) if J else None))
                stack.append(_child(ray, E, H, d1, ray.power * eta, 'AOM_1', idx, t,
                                    jones=physics.scale(J, s1) if J else None))
        elif et == 'DICHROIC':
            # SOFT-edge wavelength split: reflect a fraction R(lambda), transmit T = 1 - R (energy
            # conserved exactly). Far from the cut, R saturates to 0 or 1, so the fast paths below are
            # BYTE-IDENTICAL to the old hard-step behaviour; only in the transition band (both ports
            # carry power) does the beam genuinely split -- the finite-slope edge a real coating has.
            Rd = _dichroic_reflectance(op, ray.wl, math.acos(min(1.0, abs(ray.dir.dot(sn)))))
            if Rd <= 1e-9:                                 # full transmit (long lambda for LP)
                stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
            elif Rd >= 1.0 - 1e-9:                         # full reflect (short lambda for LP)
                if ray.evec is not None:
                    # ideal-mirror s/p convention (rp = -rs) in the true plane of incidence,
                    # so the reflected polarization stays frame-robust like MIRROR's path
                    ev, _do = physics.reflect_field(ray.evec, ray.dir, sn, 1.0, -1.0)
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power, 'REFLECT', idx, t, evec=ev))
                else:
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power, 'REFLECT', idx, t))
            else:                                          # transition band -> genuine R/T split
                Td = 1.0 - Rd
                if ray.evec is not None:
                    evt = tuple(c * math.sqrt(Td) for c in ray.evec)
                    stack.append(_child(ray, E, H, ray.dir, ray.power * Td, 'TRANSMIT', idx, t, evec=evt))
                    ev, _do = physics.reflect_field(ray.evec, ray.dir, sn, 1.0, -1.0)
                    ev = tuple(c * math.sqrt(Rd) for c in ev)
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power * Rd, 'REFLECT', idx, t, evec=ev))
                else:
                    stack.append(_child(ray, E, H, ray.dir, ray.power * Td, 'TRANSMIT', idx, t,
                                        jones=physics.scale(J, math.sqrt(Td)) if J else None))
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power * Rd, 'REFLECT', idx, t,
                                        jones=physics.scale(J, math.sqrt(Rd)) if J else None))
        elif et == 'BEAMSPLITTER':
            # A lossless beam splitter is unitary: the reflected field carries a pi/2
            # phase (r = i*sqrt(R)) relative to the transmitted field. This makes the
            # two output ports complementary and conserves energy (e.g. Mach-Zehnder).
            if op.is_pbs and ray.evec is not None:
                # Polarizing split in the TRUE plane of incidence: s (field along d x n)
                # reflects with the unitary pi/2 (rs = i), p transmits. The split lives in
                # the 3-D field, so the phase survives the detector-frame projection and
                # the s/p axes follow the cube's actual orientation -- the same
                # platform-robustness fix the non-PBS branch got (dc78047); the old 2-D
                # PBS_REFLECT/PBS_TRANSMIT acted on the beam-frame x/y, which is both
                # orientation-blind and float-tie-break sensitive across architectures.
                ev_r, ev_t = physics.pbs_split(ray.evec, ray.dir, sn)
                pr = sum((c * c.conjugate()).real for c in ev_r)
                pt = sum((c * c.conjugate()).real for c in ev_t)
                stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), pr, 'SPLIT_R', idx, t, evec=ev_r))
                stack.append(_child(ray, E, H, ray.dir, pt, 'SPLIT_T', idx, t, evec=ev_t))
            elif op.is_pbs and J:                          # no 3-D field: legacy beam-frame Jones split
                Jr = physics.scale(physics.apply(physics.PBS_REFLECT, J), 1j)
                Jt = physics.apply(physics.PBS_TRANSMIT, J)
                stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn),
                                    physics.intensity(Jr), 'SPLIT_R', idx, t, jones=Jr))
                stack.append(_child(ray, E, H, ray.dir,
                                    physics.intensity(Jt), 'SPLIT_T', idx, t, jones=Jt))
            else:
                r = op.split_ratio
                if ray.evec is not None:
                    # Carry the unitary split in the 3-D field, frame-robustly: the reflected field
                    # gets a pi/2 phase (r = i*sqrt(R)) via the physical plane of incidence
                    # (reflect_field, continuous in geometry), the transmitted field a real sqrt(T)
                    # scalar. Keeping the phase in evec -- not only in the 2-D jones -- means it
                    # survives the detector-frame projection in _seg, so the two output ports stay
                    # complementary and energy-conserving on every platform. (A jones-only phase was
                    # rebuilt through transverse_basis, whose axis tie-break is float-sensitive, so
                    # x86-64 vs arm64 could land the Mach-Zehnder on opposite fringes.)
                    sr, st = math.sqrt(max(r, 0.0)), math.sqrt(max(1.0 - r, 0.0))
                    ev_r, _ = physics.reflect_field(ray.evec, ray.dir, sn, 1j * sr, 1j * sr)
                    ev_t = (ray.evec[0] * st, ray.evec[1] * st, ray.evec[2] * st)
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power * r, 'SPLIT_R', idx, t, evec=ev_r))
                    stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - r), 'SPLIT_T', idx, t, evec=ev_t))
                else:
                    stack.append(_child(ray, E, H, geometry.reflect(ray.dir, sn), ray.power * r, 'SPLIT_R', idx, t,
                                        jones=physics.scale(J, 1j * math.sqrt(r)) if J else None))
                    stack.append(_child(ray, E, H, ray.dir, ray.power * (1.0 - r), 'SPLIT_T', idx, t,
                                        jones=physics.scale(J, math.sqrt(max(1.0 - r, 0.0))) if J else None))
        elif et == 'POLARIZER' and J:
            ptype = getattr(op, 'polarizer_type', 'FILM')
            if ptype in ('WOLLASTON', 'ROCHON'):
                # a polarizing PRISM splits the input into TWO orthogonally-polarized beams. The angular
                # separation is a spec parameter (split_angle_deg) and the deflection is pure geometry
                # (rotate the ray about the prism's split axis); the polarization is the existing
                # M_polarizer Jones at orthogonal axes -- no new computed formula here.
                ax = (E.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()   # split axis (local Y)
                half = math.radians(getattr(op, 'split_angle_deg', 20.0)) * 0.5
                Jo = physics.apply(physics.M_polarizer(op.pol_axis_deg, op.extinction), J)
                Je = physics.apply(physics.M_polarizer(op.pol_axis_deg + 90.0, op.extinction), J)
                if ptype == 'WOLLASTON':                       # symmetric +/- half-angle
                    do = (Matrix.Rotation(half, 3, ax) @ ray.dir).normalized()
                    de = (Matrix.Rotation(-half, 3, ax) @ ray.dir).normalized()
                else:                                          # ROCHON: ordinary undeviated, extraordinary deflected
                    do = ray.dir
                    de = (Matrix.Rotation(2.0 * half, 3, ax) @ ray.dir).normalized()
                stack.append(_child(ray, E, H, do, physics.intensity(Jo), 'POL_O', idx, t, jones=Jo))
                stack.append(_child(ray, E, H, de, physics.intensity(Je), 'POL_E', idx, t, jones=Je))
            else:
                Jp = physics.apply(physics.M_polarizer(op.pol_axis_deg, op.extinction), J)
                stack.append(_child(ray, E, H, ray.dir, physics.intensity(Jp), 'TRANSMIT', idx, t, jones=Jp))
        elif et == 'WAVEPLATE' and J:
            ret = op.retardance_deg * (op.design_wl / ray.wl) if ray.wl > 0 else op.retardance_deg
            wc = getattr(op, 'waveplate_crystal', 'NONE')      # opt-in real birefringence dispersion
            if wc != 'NONE' and ray.wl > 0:
                dn_l = physics.sellmeier_n(ray.wl, wc + '_E') - physics.sellmeier_n(ray.wl, wc + '_O')
                dn_d = physics.sellmeier_n(op.design_wl, wc + '_E') - physics.sellmeier_n(op.design_wl, wc + '_O')
                if abs(dn_d) > 1.0e-12:
                    ret *= dn_l / dn_d                          # x Delta_n(lambda)/Delta_n(design_wl)
            Jw = physics.apply(physics.M_waveplate(ret, op.fast_axis_deg), J)   # retardance ~ 1/lambda

            stack.append(_child(ray, E, H, ray.dir, physics.intensity(Jw), 'TRANSMIT', idx, t, jones=Jw))
        elif et in ('FILTER', 'ATTENUATOR'):
            # angle of incidence on the filter face -> dielectric-edge blue-shift (C1).
            # The ray PATH is undeviated (filters transmit straight through); only the
            # transmitted POWER near the edge changes with angle.
            aoi = math.acos(min(1.0, abs(ray.dir.dot(sn))))
            T = _transmission(op, ray.wl, aoi)
            # A9: a Fresnel ghost off the filter's front face; A11: an explicit user-set coating pickoff
            # (coating_reflectance) off the same face + a universal absorber (element_transmittance). The
            # transmitted power is debited by (1-Rg-Rc)*Ta BEFORE the spectral T (the surface reflections
            # are independent of the coating's spectral transmission). All default-neutral -> unchanged.
            Rg = _spawn_ghost(stack, gcfg, ray, E, H, sn, idx, t)
            Rc = _spawn_coating(stack, ray, E, H, sn, idx, t)
            Ta = min(max(getattr(op, 'element_transmittance', 1.0), 0.0), 1.0)
            onward = max(1.0 - Rg - Rc, 0.0) * Ta
            pT = ray.power * onward * T
            stack.append(_child(ray, E, H, ray.dir, pT, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(max(onward * T, 0.0))) if J else None))
        elif et == 'PINHOLE':
            Tc = _clip_T(ray, E, t)
            stack.append(_child(ray, E, H, ray.dir, ray.power * Tc, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(Tc)) if J else None))
        elif et == 'CAVITY':
            # Fabry-Perot etalon: wavelength-dependent Airy transmission
            T = physics.airy_transmission(ray.wl, op.cavity_spacing_mm, op.reflectivity)
            stack.append(_child(ray, E, H, ray.dir, ray.power * T, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(T)) if J else None))
        elif et == 'ISOLATOR':
            # Faraday isolator: passes forward (IN->OUT), blocks back-reflections
            ipo, opo = _find_port(op, 'IN'), _find_port(op, 'OUT')
            fwd = None
            if ipo and opo:
                fwd = _wp(E, opo.local_position) - _wp(E, ipo.local_position)
                fwd = fwd.normalized() if fwd.length > 1e-9 else None
            if fwd is not None and ray.dir.dot(fwd) < 0.0:
                continue                                  # backward -> absorbed
            stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
        elif et == 'ABERRATOR':
            # injects a wavefront error (the "turbulence") onto the beam; pass-through
            ab = _aberr_combine(ray.aberr, list(op.aberr_spec), 1.0)
            stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t, aberr=ab))
        elif et == 'DEFORMABLE_MIRROR':
            # a mirror that SUBTRACTS its commanded Zernike modes from the wavefront
            nd = geometry.reflect(ray.dir, sn)
            ab = _aberr_combine(ray.aberr, list(op.dm_command), -1.0)
            a = math.sqrt(max(op.reflectivity, 0.0))
            if ray.evec is not None:
                ev, _do = physics.reflect_field(ray.evec, ray.dir, sn, a, -a)
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t,
                                    evec=ev, aberr=ab))
            else:
                stack.append(_child(ray, E, H, nd, ray.power * op.reflectivity, 'REFLECT', idx, t,
                                    jones=None, aberr=ab))
        elif et == 'PRISM':
            # Dispersing prism (C3): refract air->glass at the entry face (wavelength-dependent n via
            # sellmeier_n), propagate the in-glass leg (OPL += n*L), then refract glass->air (EQUILATERAL/
            # AMICI), TIR-fold then refract (PELLIN_BROCA), or coated back-reflect then refract back out the
            # entry (LITTROW), at the exit face. Each wavelength bends by a different angle -> the spectrum
            # fans out. Transmission weights use the existing fresnel_reflect; TIR past the critical angle.
            n_g = physics.sellmeier_n(ray.wl, getattr(op, 'prism_glass', 'N-SF11'))
            pin, pout = _prism_faces(E)
            if pout is None:                                  # malformed prism (no exit port): pass straight
                stack.append(_child(ray, E, H, ray.dir, ray.power, 'TRANSMIT', idx, t))
                continue
            entry_n = sn
            # angle of incidence at the entry face (for the Fresnel transmission weight)
            theta_i = math.acos(min(1.0, abs(ray.dir.dot(entry_n))))
            d_glass = physics.refract_dir((ray.dir.x, ray.dir.y, ray.dir.z),
                                          (entry_n.x, entry_n.y, entry_n.z), 1.0, n_g)
            if d_glass is None:                               # TIR at entry (grazing) -> specular reflect off
                nd_r = geometry.reflect(ray.dir, entry_n)
                stack.append(_child(ray, E, H, nd_r, ray.power, 'REFLECT', idx, t, jones=ray.jones))
                continue
            d_glass = Vector(d_glass)
            T_in = physics.fresnel_transmit_power(1.0, n_g, theta_i)
            exit_pt, exit_n = pout
            ex_n = Vector(exit_n)

            # --- entry-refracted in-glass ray ---
            glass_ray = _Ray(H, d_glass, ray.power * T_in, ray.depth + 1, E, ray.wl, 'GLASS', idx,
                             jones=ray.jones, opl=ray.opl + t, q=(physics.q_propagate(ray.q, physics.abcd_free(t))
                             if ray.q is not None else None), src_id=ray.src_id, coh=ray.coh,
                             evec=(physics.field_from_jones(ray.jones, d_glass) if ray.jones else None), m2=ray.m2)

            ptype = getattr(op, 'prism_type', 'EQUILATERAL')
            if ptype == 'PELLIN_BROCA':
                # refract in -> internal TIR off the dedicated fold face (the 'TIR' port, role TRANSMIT) ->
                # refract out the exit face. The design wavelength deviates by a constant 90 deg; off-design
                # wavelengths fan around it. The TIR-face normal carries the world geometry of the fold.
                tirp = _find_port(op, 'TRANSMIT')
                if tirp is None:
                    continue
                tir_n = geometry.world_normal(E, tirp.local_normal)
                # fold the in-glass ray off the TIR face. The face midpoint is the in-glass ray's hit; use the
                # ray-plane intersection through the TIR port position for the segment break.
                tir_pt = _wp(E, tirp.local_position)
                hb = _ray_plane(glass_ray.p1, glass_ray.dir, tir_pt, tir_n)
                Hb = hb[0] if hb is not None else (glass_ray.p1 + glass_ray.dir * 1.0)
                gseg, opl_b, _qd = _glass_seg(glass_ray, Hb, E, n_g, 'GLASS')
                segments.append(gseg)
                d_fold = geometry.reflect(glass_ray.dir, tir_n)    # internal total reflection (the 90 deg fold)
                fold_ray = _Ray(Hb, d_fold, glass_ray.power, glass_ray.depth + 1, E, ray.wl, 'GLASS', idx,
                                jones=ray.jones, opl=opl_b, q=glass_ray.q, src_id=ray.src_id, coh=ray.coh,
                                evec=glass_ray.evec, m2=ray.m2)
                he = _ray_plane(fold_ray.p1, fold_ray.dir, exit_pt, ex_n)
                He = he[0] if he is not None else (fold_ray.p1 + fold_ray.dir * 1.0)
                gseg2, opl_e, _qd2 = _glass_seg(fold_ray, He, E, n_g, 'GLASS')
                segments.append(gseg2)
                theta_e = math.acos(min(1.0, abs(fold_ray.dir.dot(ex_n))))
                d_out = physics.refract_dir((fold_ray.dir.x, fold_ray.dir.y, fold_ray.dir.z),
                                            (ex_n.x, ex_n.y, ex_n.z), n_g, 1.0)
                if d_out is None:
                    continue
                T_out = physics.fresnel_transmit_power(1.0, n_g, math.asin(min(1.0, n_g * math.sin(theta_e))))
                stack.append(_prism_exit_ray(fold_ray, E, He, Vector(d_out), opl_e,
                                             ray.power * T_in * T_out, idx))
            elif ptype == 'LITTROW':
                # refract in -> reflect off the coated BACK (exit) face -> refract back out the ENTRY face
                # (autocollimating, ~2x dispersion). Reflect about the exit face, then exit through entry.
                he = _ray_plane(glass_ray.p1, glass_ray.dir, exit_pt, ex_n)
                if he is None:
                    continue
                He, _te = he
                gseg, opl_e, _qd = _glass_seg(glass_ray, He, E, n_g, 'GLASS')
                segments.append(gseg)
                d_refl = geometry.reflect(glass_ray.dir, ex_n)     # coated back-reflection
                refl_ray = _Ray(He, d_refl, glass_ray.power, glass_ray.depth + 1, E, ray.wl, 'GLASS', idx,
                                jones=ray.jones, opl=opl_e, q=glass_ray.q, src_id=ray.src_id, coh=ray.coh,
                                evec=glass_ray.evec, m2=ray.m2)
                hx = _ray_plane(refl_ray.p1, refl_ray.dir, pin[0], Vector(pin[1]))
                if hx is None:
                    continue
                Hx, _tx = hx
                gseg2, opl_x, _qd2 = _glass_seg(refl_ray, Hx, E, n_g, 'GLASS')
                segments.append(gseg2)
                en = Vector(pin[1])
                theta_x = math.acos(min(1.0, abs(refl_ray.dir.dot(en))))
                d_out = physics.refract_dir((refl_ray.dir.x, refl_ray.dir.y, refl_ray.dir.z),
                                            (en.x, en.y, en.z), n_g, 1.0)
                if d_out is None:
                    continue
                T_out = physics.fresnel_transmit_power(1.0, n_g, math.asin(min(1.0, n_g * math.sin(theta_x))))
                stack.append(_prism_exit_ray(refl_ray, E, Hx, Vector(d_out), opl_x,
                                             ray.power * T_in * T_out, idx))
            elif ptype == 'AMICI':
                # Direct-vision doublet: refract crown (already done into glass_ray with n_g = crown index),
                # refract crown->flint at the cemented interface (the 'CEMENT' port), then flint->air at the
                # exit face. The design wavelength exits ~undeviated; the spectrum still fans (the two glasses'
                # different Abbe numbers mean the deviation cancels but the dispersion does not).
                cemp = _find_port(op, 'TRANSMIT')
                n2 = physics.sellmeier_n(ray.wl, getattr(op, 'prism_glass2', 'N-SF11'))
                if cemp is None:
                    continue
                cem_n = geometry.world_normal(E, cemp.local_normal)
                cem_pt = _wp(E, cemp.local_position)
                hc = _ray_plane(glass_ray.p1, glass_ray.dir, cem_pt, cem_n)
                Hc = hc[0] if hc is not None else (glass_ray.p1 + glass_ray.dir * 1.0)
                gseg, opl_c, _qd = _glass_seg(glass_ray, Hc, E, n_g, 'GLASS')   # crown leg (n_g)
                segments.append(gseg)
                d_flint = physics.refract_dir((glass_ray.dir.x, glass_ray.dir.y, glass_ray.dir.z),
                                              (cem_n.x, cem_n.y, cem_n.z), n_g, n2)   # crown -> flint
                if d_flint is None:
                    continue
                flint_ray = _Ray(Hc, Vector(d_flint), glass_ray.power, glass_ray.depth + 1, E, ray.wl, 'GLASS',
                                 idx, jones=ray.jones, opl=opl_c, q=glass_ray.q, src_id=ray.src_id,
                                 coh=ray.coh, evec=glass_ray.evec, m2=ray.m2)
                he = _ray_plane(flint_ray.p1, flint_ray.dir, exit_pt, ex_n)
                He = he[0] if he is not None else (flint_ray.p1 + flint_ray.dir * 1.0)
                gseg2, opl_e, _qd2 = _glass_seg(flint_ray, He, E, n2, 'GLASS')      # flint leg (n2)
                segments.append(gseg2)
                d_out = physics.refract_dir((flint_ray.dir.x, flint_ray.dir.y, flint_ray.dir.z),
                                            (ex_n.x, ex_n.y, ex_n.z), n2, 1.0)       # flint -> air
                if d_out is None:
                    continue
                stack.append(_prism_exit_ray(flint_ray, E, He, Vector(d_out), opl_e,
                                             ray.power * T_in, idx))
            elif ptype in _ROUTING_FOLDS:
                # C4 beam-ROUTING prism: refract air->glass at the entry face (already in glass_ray), then
                # fold the chief ray off N internal mirror faces (geometry.reflect, the verified reflection
                # law) IN ORDER, then refract glass->air at the exit face. The fold COUNT sets the image
                # parity (EVEN # -> handedness preserved: penta/rhomboid; ODD -> flipped: right-angle/Dove/
                # roof). No dispersion BY DESIGN -- the deflection is a fixed product of plane reflections,
                # so it is wavelength-independent (n(lambda) only shifts the tiny entry/exit refraction).
                folds = []
                ok = True
                for pname in _ROUTING_FOLDS[ptype]:
                    fp = _find_port_named(op, pname)
                    if fp is None:
                        ok = False
                        break
                    folds.append((_wp(E, fp.local_position),
                                  geometry.world_normal(E, fp.local_normal)))
                if not ok:
                    continue
                folded = _route_fold(glass_ray, E, folds, segments, idx, n_g)
                # exit-face Snell glass->air
                he = _ray_plane(folded.p1, folded.dir, exit_pt, ex_n)
                He = he[0] if he is not None else (folded.p1 + folded.dir * 1.0)
                gseg, opl_e, _qd = _glass_seg(folded, He, E, n_g, 'GLASS')
                segments.append(gseg)
                theta_e = math.acos(min(1.0, abs(folded.dir.dot(ex_n))))   # in-glass exit incidence
                d_out = physics.refract_dir((folded.dir.x, folded.dir.y, folded.dir.z),
                                            (ex_n.x, ex_n.y, ex_n.z), n_g, 1.0)
                if d_out is None:                              # TIR at the exit face (over-tilted): dump (Tier-1)
                    continue
                T_out = physics.fresnel_transmit_power(1.0, n_g, math.asin(min(1.0, n_g * math.sin(theta_e))))
                # record the image parity (EVEN folds preserve handedness, ODD flip it). The Amici ROOF is the
                # textbook exception: its two roof faces add a TRANSVERSE (left-right) image flip on top of the
                # 2-reflection deflection, so its net handedness is ODD despite an even fold count (the "roof
                # flips the image" property -- the reason a roof prism is used in erecting systems).
                if ptype == 'ROOF':
                    op.prism_parity = "ODD"
                else:
                    op.prism_parity = "EVEN" if (len(folds) % 2 == 0) else "ODD"
                if ptype == 'DOVE':
                    # the through image rotates at 2x the prism's roll angle: theta_img = 2*theta_roll
                    # (physics_verify ok=true 4/4: DIMENSIONAL + SYMBOLIC solve + NUMERIC 30->60 / 15->30).
                    # A pure reduction of the in-plane reflection law; recorded as metadata (the chief-ray
                    # tracer is single-ray, so image ORIENTATION is not a ray-direction effect, only this).
                    op.meas_text = "image_rotation %.3f deg (2x roll)" % (2.0 * getattr(op, 'prism_roll_deg', 0.0))
                stack.append(_prism_exit_ray(folded, E, He, Vector(d_out),
                                             opl_e, ray.power * T_in * T_out, idx))
            else:
                # EQUILATERAL: refract in -> straight in-glass leg -> refract out the exit face.
                he = _ray_plane(glass_ray.p1, glass_ray.dir, exit_pt, ex_n)
                if he is None:
                    continue
                He, _te = he
                gseg, opl_e, _qd = _glass_seg(glass_ray, He, E, n_g, 'GLASS')
                segments.append(gseg)
                theta_e = math.acos(min(1.0, abs(glass_ray.dir.dot(ex_n))))   # in-glass exit incidence
                d_out = physics.refract_dir((glass_ray.dir.x, glass_ray.dir.y, glass_ray.dir.z),
                                            (ex_n.x, ex_n.y, ex_n.z), n_g, 1.0)
                if d_out is None:                              # TIR at the exit face: fold internally, dump (Tier-1)
                    continue
                T_out = physics.fresnel_transmit_power(1.0, n_g, math.asin(min(1.0, n_g * math.sin(theta_e))))
                stack.append(_prism_exit_ray(glass_ray, E, He, Vector(d_out), opl_e,
                                             ray.power * T_in * T_out, idx))
        else:  # LENS / PASSTHROUGH (the canonical A9 transmissive face: an uncoated window / lens)
            # A9: a low-power parasitic Fresnel ghost peels back off the surface. A11: an explicit
            # user-set reflective coating (coating_reflectance) peels a controlled pickoff off the SAME
            # entry face, and a universal absorber (element_transmittance) attenuates the onward beam.
            # The transmitted beam is debited to (1-Rg-Rc)*Ta so Rg + Rc + T_onward + A = incident (energy
            # conserved). All three default-neutral (Rg=0 with ghosts off, Rc=0, Ta=1) -> power unchanged,
            # so an ordinary window/lens still traces BYTE-IDENTICAL.
            Rg = _spawn_ghost(stack, gcfg, ray, E, H, sn, idx, t)
            Rc = _spawn_coating(stack, ray, E, H, sn, idx, t)
            Ta = min(max(getattr(op, 'element_transmittance', 1.0), 0.0), 1.0)
            onward = max(1.0 - Rg - Rc, 0.0) * Ta
            stack.append(_child(ray, E, H, ray.dir, ray.power * onward, 'TRANSMIT', idx, t,
                                jones=physics.scale(J, math.sqrt(onward)) if J else None))

    return segments


# --- operators --------------------------------------------------------------

def _tag_redraw():
    """Redraw every 3-D viewport. The single implementation reused across the add-on
    (handlers, scan, assembly, properties, bridge) - see those callers."""
    wm = bpy.context.window_manager
    if not wm:
        return
    for w in wm.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()


class OPTICS_OT_trace_now(Operator):
    bl_idname = "optics.trace_now"
    bl_label = "Trace Now"
    bl_description = "Recompute the beam path once and show the overlay"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global cached_segments
        scn = context.scene
        cached_segments = trace_scene(scn, mode=scn.optics.trace_mode,
                                      max_segments=scn.optics.max_segments,
                                      max_depth=scn.optics.max_depth)
        from . import overlay
        overlay.enable()
        _tag_redraw()
        self.report({'INFO'}, "Traced %d segments" % len(cached_segments))
        return {'FINISHED'}


class OPTICS_OT_clear_beams(Operator):
    bl_idname = "optics.clear_beams"
    bl_label = "Clear Beam Overlay"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global cached_segments
        cached_segments = []
        _tag_redraw()
        return {'FINISHED'}


_classes = (OPTICS_OT_trace_now, OPTICS_OT_clear_beams)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
