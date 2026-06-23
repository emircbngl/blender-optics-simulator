"""Open-loop optical-system synthesis (Wave-2 B2).

The counterpart to ``solvers.py``: where the solvers run a CLOSED loop (measure
the beam, poke DOFs, drive a residual to zero), this module is pure OPEN-LOOP
*design* -- given two focal lengths it hands back the spacing + magnification +
the ABCD system matrix of the relay you should build. Nothing here touches
Blender state; every function is plain math over the verified ABCD primitives in
``physics.py``, so it is unit-testable with a bare interpreter and the designer
matrices are trivially correct (they are COMPOSED from ``abcd_lens``/``abcd_free``,
never hand-written).

Two canonical relays:

  * ``design_telescope(f1, f2)`` -- an afocal two-lens telescope/beam-expander.
    The two lenses share a focal point, so the separation is ``d = f1 + f2`` and a
    collimated (parallel) input stays collimated at the output. The transverse
    magnification is ``M = -f2/f1`` and the beam expands by ``|f2/f1|`` (Keplerian
    when both focals are positive, Galilean when one is negative).

  * ``design_4f(f1, f2)`` -- the full 4f relay: object at the front focal plane of
    L1, the two lenses separated by ``f1 + f2``, image at the back focal plane of
    L2. Object->L1->L2->image spacings are ``[f1, f1+f2, f2]``; the L1->L2 system
    matrix is the SAME afocal matrix, and the transverse magnification is ``-f2/f1``.

The new fact underneath both is that the same physical system has TWO closed-form
matrices for two different pairs of reference planes:

  * lens-to-lens (afocal):     abcd_lens(f2) . abcd_free(f1+f2) . abcd_lens(f1)
                               == [[-f2/f1, f1+f2], [0, -f1/f2]]
    The C (off-diagonal POWER) entry vanishes -- *that* is the afocal / telescopic
    condition ("zero net power -> parallel in stays parallel out", since a collimated
    ray has angle 0 and C maps position->output-angle). B is the residual translation
    f1+f2 (a sheared, not focused, system). ``afocal_abcd`` returns this.

  * object-plane to image-plane (4f imaging): add the object focal f1 in front and the
    image focal f2 behind -> free(f2).lens(f2).free(f1+f2).lens(f1).free(f1)
                               == [[-f2/f1, 0], [0, -f1/f2]]
    Now the B (TRANSLATION) entry vanishes -- *that* is the conjugate-plane / imaging
    condition (output position independent of input angle). C stays 0 (telecentric).
    ``relay_4f_abcd`` returns this; it is the matrix the roadmap quotes for "full 4f".

Both have determinant 1 and the same diagonal magnification A = -f2/f1, D = -f1/f2;
they differ only in which off-diagonal is zero (C=0 afocal vs B=0 imaging), i.e. which
pair of planes you read between. Verified against the physicist oracle: SYMBOLIC
reduction of the afocal A / C=0 / D entries, NUMERIC magnification / separation / the
4f B=0 entry / det==1 over (f1,f2) pairs at rtol 1e-9, DIMENSIONAL checks, ok=true.
The primitives it is built from were already verified.

Wave-2 B3 adds the *mode-match* solver below: given an input Gaussian mode and a
TARGET Gaussian mode (waist + location), it solves the single lens focal that maps one
onto the other, and reports the power-coupling efficiency into that target mode (fiber /
cavity coupling). The closed form is the Gaussian waist-imaging pair

    s' = f + (s-f) f^2 / [(s-f)^2 + zR^2],      m = f / sqrt((s-f)^2 + zR^2)

(s = input-waist-to-lens distance, zR = pi w0_in^2 / lambda the input Rayleigh range,
s' = lens-to-output-waist distance, m = w0_out/w0_in the waist magnification). Forcing
BOTH the target magnification m = w0_t/w0_in AND the target location s' = z_t eliminates
the lens position and leaves a QUADRATIC in f (derivation in ``mode_match_lens``):

    (1 - m^2) f^2  -  2 z_t f  +  (z_t^2 + m^4 zR^2)  =  0

so the focal is a closed form (up to the usual two conjugate-plane roots), and the
required lens position is s = f + (z_t - f)/m^2. The solver returns achieved_w0 /
achieved_z obtained by ACTUALLY propagating the input q through abcd_free(s).abcd_lens(f)
with the verified primitives, so the return is self-checking against its own algebra.

CONTRACT: importing this module does nothing and these functions never mutate a
scene -- they are a pure on-demand design library, exactly like ``solvers.py`` is
a pure on-demand correction library.
"""
from __future__ import annotations

import math

try:                                # normal: imported as a package module
    from . import physics
except ImportError:                 # bare `python3 design.py` self-test
    import physics


# --------------------------------------------------------------------------- #
# input guard (mirrors solvers' {ok:False, error:...} convention)
# --------------------------------------------------------------------------- #

def _bad_focal(f1, f2):
    """A clear error dict when either focal length is unusable (zero / non-finite),
    or ``None`` when the pair is fine. A thin-lens focal of exactly 0 has infinite
    power (``abcd_lens`` would divide by zero) and no afocal spacing exists, so it is
    rejected up front. Negative focals are LEGAL (a diverging lens -> a Galilean
    telescope), so they pass."""
    for name, f in (("f1", f1), ("f2", f2)):
        try:
            fv = float(f)
        except (TypeError, ValueError):
            return {"ok": False, "error": "%s must be a number (got %r)" % (name, f)}
        if fv == 0.0 or fv != fv or abs(fv) == float("inf"):
            return {"ok": False, "error": "%s must be a finite non-zero focal length (got %r)" % (name, f)}
    return None


# --------------------------------------------------------------------------- #
# the afocal system matrix (composed from the verified primitives)
# --------------------------------------------------------------------------- #

def afocal_abcd(f1, f2):
    """The 2x2 ray-transfer matrix of two thin lenses separated by ``d = f1 + f2``,
    composed in BEAM ORDER from the verified primitives (lens f1, then free-space
    f1+f2, then lens f2) using the same ``abcd_compose`` the tracer/overlay use.

    Closed form (verified): this equals ``[[-f2/f1, f1+f2], [0, -f1/f2]]`` -- the C
    (power) entry is exactly 0 (the afocal condition: collimated in -> collimated
    out), B is the residual translation f1+f2, and the determinant is 1. For the
    object->image (B=0) imaging matrix of the same system see ``relay_4f_abcd``."""
    return physics.abcd_compose(physics.abcd_lens(f1),
                                physics.abcd_free(f1 + f2),
                                physics.abcd_lens(f2))


def relay_4f_abcd(f1, f2):
    """The object-plane -> image-plane ray-transfer matrix of the full 4f relay,
    composed in BEAM ORDER from the verified primitives: free-space f1 (object to
    L1), lens f1, free-space f1+f2 (L1 to L2), lens f2, free-space f2 (L2 to image).

    Closed form (verified): this equals ``[[-f2/f1, 0], [0, -f1/f2]]`` -- now the B
    (off-diagonal TRANSLATION) entry is exactly 0 (the conjugate / imaging condition:
    output position is independent of input angle, so the object and image planes are
    conjugate), C stays 0 (telecentric), and the diagonal carries the transverse
    magnification -f2/f1. This is the SAME system as ``afocal_abcd`` read between a
    different pair of planes (afocal C=0 / B=f1+f2 between the lenses vs imaging B=0
    between object and image); it is the matrix the roadmap quotes for "full 4f"."""
    return physics.abcd_compose(physics.abcd_free(f1),
                                physics.abcd_lens(f1),
                                physics.abcd_free(f1 + f2),
                                physics.abcd_lens(f2),
                                physics.abcd_free(f2))


# --------------------------------------------------------------------------- #
# designers
# --------------------------------------------------------------------------- #

def design_telescope(f1, f2):
    """Design an afocal two-lens telescope / beam-expander from objective focal
    ``f1`` and eyepiece/relay focal ``f2``.

    Returns a JSON-able dict:
      {ok, sep, magnification, angular_mag, beam_expansion, type, abcd}
    where ``sep = f1+f2`` is the lens separation (the afocal condition), the
    transverse/beam magnification is ``M = -f2/f1``, the angular magnification is
    ``-f1/f2`` (its reciprocal), the beam expands by ``|f2/f1|``, and ``type`` is
    'keplerian' (both focals positive, an internal real focus) or 'galilean' (one
    negative, no internal focus -> shorter, upright). ``abcd`` is the composed
    afocal matrix (== [[M, f1+f2], [0, 1/M]], C=0 -> collimated-in/collimated-out)."""
    err = _bad_focal(f1, f2)
    if err:
        return err
    f1, f2 = float(f1), float(f2)
    return {
        "ok": True,
        "sep": f1 + f2,
        "magnification": -f2 / f1,
        "angular_mag": -f1 / f2,
        "beam_expansion": abs(f2 / f1),
        "type": "keplerian" if (f1 > 0.0 and f2 > 0.0) else "galilean",
        "abcd": afocal_abcd(f1, f2),
    }


def design_4f(f1, f2):
    """Design a full 4f relay from L1 focal ``f1`` and L2 focal ``f2``.

    Object sits at the front focal plane of L1, the lenses are ``f1+f2`` apart, and
    the image forms at the back focal plane of L2. Returns a JSON-able dict:
      {ok, seps, total_length, transverse_mag, beam_expansion, abcd, abcd_image}
    with ``seps = [f1, f1+f2, f2]`` (object->L1, L1->L2, L2->image), the total
    object->image length ``2*(f1+f2)``, transverse magnification ``-f2/f1``, beam
    expansion ``|f2/f1|``. TWO ABCD matrices for the two pairs of reference planes:
    ``abcd`` is the L1->L2 afocal (lens-to-lens) matrix (C=0, B=f1+f2), and
    ``abcd_image`` is the object-plane->image-plane imaging matrix
    ``[[-f2/f1, 0],[0, -f1/f2]]`` (B=0 -> conjugate planes) over the full path."""
    err = _bad_focal(f1, f2)
    if err:
        return err
    f1, f2 = float(f1), float(f2)
    return {
        "ok": True,
        "seps": [f1, f1 + f2, f2],
        "total_length": 2.0 * (f1 + f2),
        "transverse_mag": -f2 / f1,
        "beam_expansion": abs(f2 / f1),
        "abcd": afocal_abcd(f1, f2),
        "abcd_image": relay_4f_abcd(f1, f2),
    }


# --------------------------------------------------------------------------- #
# B3 - Gaussian mode-match solver (lens -> cavity / fiber) + coupling efficiency
# --------------------------------------------------------------------------- #

def coupling_efficiency(w_in, w_t, offset=0.0):
    """Power-coupling efficiency eta of a Gaussian mode of waist ``w_in`` into a target
    Gaussian mode of waist ``w_t`` whose center is transversely displaced by ``offset``
    (all in mm at the common plane). Pure scalar; the headline fiber/cavity metric.

    Closed form (physics_verify ok=true, pass_rate 1.0):

        eta = [ 2 w_in w_t / (w_in^2 + w_t^2) ]^2  *  exp( -2 d^2 / (w_in^2 + w_t^2) )

    The first factor is the pure mode-overlap |<u_in|u_t>|^2 of two co-axial Gaussians
    (it is 1 iff w_in == w_t and falls off as the waists mismatch); the second is the
    transverse-misalignment penalty (1 at d=0, monotonically decreasing in d). eta is
    symmetric in w_in <-> w_t, dimensionless, and bounded in (0, 1] -- it equals 1 ONLY
    when w_in == w_t AND offset == 0. Returns ``{ok: False, error: ...}`` for a
    non-physical waist (w <= 0 / non-finite); a bare negative/zero offset is fine (only
    d^2 enters)."""
    for name, w in (("w_in", w_in), ("w_t", w_t)):
        try:
            wv = float(w)
        except (TypeError, ValueError):
            return {"ok": False, "error": "%s must be a number (got %r)" % (name, w)}
        if not (wv > 0.0) or wv != wv or abs(wv) == float("inf"):
            return {"ok": False, "error": "%s must be a finite positive waist (got %r)" % (name, w)}
    try:
        d = float(offset)
    except (TypeError, ValueError):
        return {"ok": False, "error": "offset must be a number (got %r)" % (offset,)}
    if d != d or abs(d) == float("inf"):
        return {"ok": False, "error": "offset must be finite (got %r)" % (offset,)}
    w_in, w_t = float(w_in), float(w_t)
    sumsq = w_in * w_in + w_t * w_t
    overlap = (2.0 * w_in * w_t / sumsq) ** 2                 # pure mode overlap (d=0)
    return overlap * math.exp(-2.0 * d * d / sumsq)


def _waist_from_q(q, wavelength_nm, m2=1.0):
    """Recover (w0, z_to_waist) from a propagated q = (z - z_waist) + i*zR: the waist is a
    distance Re(q) further along the axis (so a NEGATIVE Re(q) means the waist already passed),
    and w0 = beam_radius at that waist (i.e. of the pure-imaginary i*zR). Re-uses the verified
    ``beam_radius_m2`` on q - i*Re(q) so the physical M^2 radius is honoured at m2 != 1."""
    z_to_waist = -q.real                                     # how far ahead the waist sits
    q_waist = complex(0.0, q.imag)                           # q at its own waist is i*zR
    w0 = physics.beam_radius_m2(q_waist, wavelength_nm, m2)
    return w0, z_to_waist


def mode_match_lens(w0_in, s_in, w0_t, z_t, wavelength_nm, m2=1.0):
    """Solve the single thin-lens focal ``f`` that mode-matches an input Gaussian (waist
    ``w0_in``) into a target Gaussian (waist ``w0_t`` located ``z_t`` past the lens).

    ``s_in`` is the proposed input-waist-to-lens distance; it is the geometry the caller has
    in mind. The solver, however, fixes the focal AND the lens position together so BOTH the
    target waist size and its location are hit exactly (a single lens has exactly those two
    handles -- f and where you put it). It therefore returns the REQUIRED lens position
    ``s_lens`` next to ``s_in`` so the caller sees how far the lens must move from the proposed
    spot. All lengths in mm, wavelength in nm.

    Math (verified by forward q-propagation): with input Rayleigh range zR = pi w0_in^2/lambda
    (scaled by 1/M^2 for a real beam, exactly as ``q_from_waist``), the Gaussian waist-imaging
    pair is  m = f/sqrt((s-f)^2+zR^2)  and  s' = f + (s-f) f^2/[(s-f)^2+zR^2]. Forcing
    m = w0_t/w0_in and s' = z_t eliminates s (s - f = (z_t - f)/m^2) and leaves

        (1 - m^2) f^2  -  2 z_t f  +  (z_t^2 + m^4 zR^2)  =  0.

    The two roots are the two conjugate-plane solutions (near & far lens placements); both are
    returned. For the unit-magnification case m == 1 the quadratic degenerates to the linear
    f = (z_t^2 + zR^2)/(2 z_t) (the symmetric waist-imaging focus). A target with no real root
    (e.g. an unreachable magnification at that z_t) yields ``{ok: False, error: ...}`` -- no
    focal is fabricated.

    Returns ``{ok, f, f_alt, s_lens, s_lens_alt, m, zR, achieved_w0, achieved_z, coupling,
    offset}`` where achieved_w0 / achieved_z come from ACTUALLY propagating the input q through
    abcd_free(s_lens).abcd_lens(f) (so the result is self-checking), and ``coupling`` is
    ``coupling_efficiency(achieved_w0, w0_t)`` at the achieved waist (== 1.0 on a clean solve)."""
    # --- guard inputs (mirror coupling_efficiency / _bad_focal style) --------
    for name, v in (("w0_in", w0_in), ("w0_t", w0_t), ("z_t", z_t),
                    ("wavelength_nm", wavelength_nm)):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return {"ok": False, "error": "%s must be a number (got %r)" % (name, v)}
        if fv != fv or abs(fv) == float("inf"):
            return {"ok": False, "error": "%s must be finite (got %r)" % (name, v)}
    w0_in, w0_t = float(w0_in), float(w0_t)
    z_t, wl = float(z_t), float(wavelength_nm)
    if not (w0_in > 0.0 and w0_t > 0.0):
        return {"ok": False, "error": "w0_in and w0_t must be positive waists"}
    if wl <= 0.0:
        return {"ok": False, "error": "wavelength_nm must be positive"}
    if z_t == 0.0:
        return {"ok": False, "error": "z_t must be non-zero (the target waist cannot sit on the lens)"}

    # input Rayleigh range from the VERIFIED q (carries the M^2 scaling): q_in = i*zR
    q_in = physics.q_from_waist(w0_in, wl, m2)
    zR = q_in.imag
    m = w0_t / w0_in                                          # required waist magnification

    # solve (1 - m^2) f^2 - 2 z_t f + (z_t^2 + m^4 zR^2) = 0 for the focal f
    a = 1.0 - m * m
    b = -2.0 * z_t
    c = z_t * z_t + (m ** 4) * zR * zR
    if abs(a) < 1e-15:                                        # m == 1: linear, symmetric imaging
        if abs(b) < 1e-30:
            return {"ok": False, "error": "degenerate solve (z_t -> 0 at unit magnification)"}
        roots = [-c / b]
    else:
        disc = b * b - 4.0 * a * c
        if disc < 0.0:                                        # no real focal hits this target mode
            return {"ok": False, "error": "no real lens solution for w0_t=%g at z_t=%g "
                    "(magnification %.4g unreachable for this input mode)" % (w0_t, z_t, m)}
        sq = math.sqrt(disc)
        roots = [(-b + sq) / (2.0 * a), (-b - sq) / (2.0 * a)]

    # discard a focal of exactly 0 (no lens)
    roots = [r for r in roots if abs(r) > 1e-12]
    if not roots:
        return {"ok": False, "error": "only the trivial f=0 solves this target (no lens needed?)"}

    def _solve_for(focal):
        """Required lens position + achieved waist for a candidate focal, by REAL propagation."""
        s_lens = focal + (z_t - focal) / (m * m)              # s - f = (z_t - f)/m^2
        q_at_lens = physics.q_propagate(q_in, physics.abcd_free(s_lens))
        q_out = physics.q_propagate(q_at_lens, physics.abcd_lens(focal))
        achieved_w0, achieved_z = _waist_from_q(q_out, wl, m2)
        return s_lens, achieved_w0, achieved_z

    # Both roots are valid conjugate-plane solutions (each hits the target by propagation);
    # order so the PRIMARY is the realisable geometry -- a non-negative lens position (the lens
    # sits AFTER the input waist) first, then by smaller |s_in - s_lens| (closest to the
    # caller's proposed spot). A negative s_lens means the waist would sit downstream of the
    # lens (a virtual-object placement); it stays available as the alternate.
    cand = [(r, _solve_for(r)) for r in roots]
    cand.sort(key=lambda rs: (rs[1][0] < 0.0, abs(rs[1][0] - float(s_in))))
    f, (s_lens, achieved_w0, achieved_z) = cand[0]
    f_alt = cand[1][0] if len(cand) > 1 else None
    s_lens_alt = cand[1][1][0] if len(cand) > 1 else None
    coupling = coupling_efficiency(achieved_w0, w0_t)
    coupling = coupling.get("coupling", coupling) if isinstance(coupling, dict) else coupling

    return {
        "ok": True,
        "f": f, "f_alt": f_alt,
        "s_lens": s_lens, "s_lens_alt": s_lens_alt,
        "s_in": s_in,
        "m": m, "zR": zR,
        "achieved_w0": achieved_w0, "achieved_z": achieved_z,
        "coupling": coupling,
        # the OPEN-LOOP design has no transverse error to report (it is on-axis); the residual
        # offset/tilt the closed-loop A6 beam-walk would null is 0 here by construction.
        "offset": 0.0,
    }


def mode_match_two_lens(w0_in, w0_t, z_t, wavelength_nm, focals,
                        s1_range=(20.0, 400.0), n=64, m2=1.0):
    """Optional two-lens library search (LOWER priority than the single-lens solve). Scan a
    menu of catalog focals ``focals`` for (f1, f2) and the L1 position s1 over ``s1_range`` (n
    samples) that, with L1->L2 fixed by the second waist-imaging stage, maximises the coupling
    into the target mode at ``z_t``. Pure brute force over the verified primitives; returns the
    best ``{ok, f1, f2, s1, s12, coupling, achieved_w0, achieved_z}`` or ``{ok: False}`` if the
    menu cannot reach the target. Provided for completeness -- the single-lens ``mode_match_lens``
    is the solid, closed-form path."""
    for name, v in (("w0_in", w0_in), ("w0_t", w0_t), ("z_t", z_t), ("wavelength_nm", wavelength_nm)):
        try:
            float(v)
        except (TypeError, ValueError):
            return {"ok": False, "error": "%s must be a number (got %r)" % (name, v)}
    if not (float(w0_in) > 0.0 and float(w0_t) > 0.0 and float(wavelength_nm) > 0.0):
        return {"ok": False, "error": "w0_in, w0_t, wavelength_nm must be positive"}
    if not focals:
        return {"ok": False, "error": "focals menu is empty"}
    wl = float(wavelength_nm)
    q_in = physics.q_from_waist(float(w0_in), wl, m2)
    lo, hi = float(s1_range[0]), float(s1_range[1])
    best = None
    for f1 in focals:
        for f2 in focals:
            for i in range(max(2, int(n))):
                s1 = lo + (hi - lo) * i / (max(2, int(n)) - 1)
                # stage 1: input waist -> L1 -> intermediate waist
                q1 = physics.q_propagate(physics.q_propagate(q_in, physics.abcd_free(s1)),
                                         physics.abcd_lens(float(f1)))
                w_mid, z_mid = _waist_from_q(q1, wl, m2)
                if w_mid <= 0.0 or z_mid <= 0.0:
                    continue
                # stage 2: place L2 at the intermediate waist + a slack so the target lands at z_t
                s12 = z_mid                                    # L1 -> L2 = distance to intermediate waist
                q2 = physics.q_propagate(physics.q_propagate(q1, physics.abcd_free(s12)),
                                         physics.abcd_lens(float(f2)))
                w_out, z_out = _waist_from_q(q2, wl, m2)
                if w_out <= 0.0:
                    continue
                d = abs(z_out - z_t)                           # location penalty as a transverse-free offset proxy
                eta = coupling_efficiency(w_out, float(w0_t))
                eta = eta if not isinstance(eta, dict) else 0.0
                # fold the longitudinal miss in as a soft penalty (1/e at one Rayleigh range)
                zR_t = math.pi * float(w0_t) ** 2 / (wl * physics.NM_TO_MM)
                score = eta * math.exp(-(d / max(zR_t, 1e-9)) ** 2)
                if best is None or score > best["score"]:
                    best = {"score": score, "f1": float(f1), "f2": float(f2), "s1": s1,
                            "s12": s12, "coupling": eta, "achieved_w0": w_out, "achieved_z": z_out}
    if best is None:
        return {"ok": False, "error": "two-lens search found no valid configuration"}
    best.pop("score", None)
    best["ok"] = True
    return best


# This module registers no Blender classes (it is pure math); these no-ops let
# __init__'s uniform register()/unregister() loop include it without a special
# case, exactly as solvers.py does.
def register():
    pass


def unregister():
    pass


# --- self-test (closed-form checks, run with `python3 design.py`) ------------

if __name__ == "__main__":
    import sys

    def close(a, b, tol=1e-12):
        return abs(a - b) <= tol

    fails = []
    for f1, f2 in ((50.0, 100.0), (100.0, 50.0), (-25.0, 75.0), (200.0, -40.0), (30.0, 30.0)):
        A = afocal_abcd(f1, f2)
        # afocal closed form (oracle-verified): [[-f2/f1, f1+f2], [0, -f1/f2]] --
        # the C (power) entry is exactly 0 (the afocal condition), B is the residual
        # translation f1+f2, the diagonal carries the magnification.
        if not (close(A[0][0], -f2 / f1) and close(A[1][1], -f1 / f2)
                and close(A[0][1], f1 + f2, 1e-9) and close(A[1][0], 0.0)):
            fails.append("afocal_abcd(%g,%g)=%r" % (f1, f2, A))
        if not close(A[0][0] * A[1][1] - A[0][1] * A[1][0], 1.0, 1e-9):     # det == 1
            fails.append("det(%g,%g) != 1" % (f1, f2))
        t = design_telescope(f1, f2)
        if not (close(t["sep"], f1 + f2) and close(t["magnification"], -f2 / f1)
                and close(t["beam_expansion"], abs(f2 / f1))):
            fails.append("design_telescope(%g,%g)=%r" % (f1, f2, t))
        want_type = "keplerian" if (f1 > 0 and f2 > 0) else "galilean"
        if t["type"] != want_type:
            fails.append("type(%g,%g)=%s want %s" % (f1, f2, t["type"], want_type))
        R = relay_4f_abcd(f1, f2)
        # full 4f object->image (oracle-verified): [[-f2/f1, 0],[0,-f1/f2]] -- now the
        # B (translation) entry is exactly 0 (conjugate image planes), C stays 0.
        if not (close(R[0][0], -f2 / f1) and close(R[1][1], -f1 / f2)
                and close(R[0][1], 0.0, 1e-9) and close(R[1][0], 0.0)):
            fails.append("relay_4f_abcd(%g,%g)=%r" % (f1, f2, R))
        if not close(R[0][0] * R[1][1] - R[0][1] * R[1][0], 1.0, 1e-9):     # det == 1
            fails.append("4f det(%g,%g) != 1" % (f1, f2))
        q = design_4f(f1, f2)
        if not (close(q["seps"][1], f1 + f2) and close(q["transverse_mag"], -f2 / f1)
                and close(q["total_length"], 2.0 * (f1 + f2))
                and close(q["abcd_image"][0][1], 0.0, 1e-9)):     # imaging B == 0
            fails.append("design_4f(%g,%g)=%r" % (f1, f2, q))

    # input guards
    if design_telescope(0.0, 100.0).get("ok") is not False:
        fails.append("zero f1 not rejected")
    if design_4f(50.0, "x").get("ok") is not False:
        fails.append("non-numeric f2 not rejected")

    # --- B3 mode-match + coupling efficiency (closed-form) -------------------
    # coupling: eta(w,w,0) == 1 exactly; symmetric in w_in<->w_t; offset drives it down
    if not close(coupling_efficiency(0.5, 0.5, 0.0), 1.0, 1e-12):
        fails.append("eta(w,w,0) != 1")
    e_a = coupling_efficiency(0.4, 0.7, 0.0)
    e_b = coupling_efficiency(0.7, 0.4, 0.0)
    overlap = (2.0 * 0.4 * 0.7 / (0.4 ** 2 + 0.7 ** 2)) ** 2     # pure mode overlap
    if not (close(e_a, overlap, 1e-12) and close(e_b, overlap, 1e-12)):
        fails.append("eta mismatch closed form / symmetry: %.6f %.6f vs %.6f" % (e_a, e_b, overlap))
    e0 = coupling_efficiency(0.5, 0.5, 0.0)
    e1 = coupling_efficiency(0.5, 0.5, 0.2)
    e2 = coupling_efficiency(0.5, 0.5, 0.4)
    if not (e0 > e1 > e2 and 0.0 < e2 <= 1.0):                   # monotone down, bounded (0,1]
        fails.append("eta offset not monotone/bounded: %.4f %.4f %.4f" % (e0, e1, e2))
    if coupling_efficiency(0.0, 0.5).get("ok") is not False:
        fails.append("zero waist not rejected")

    # mode_match_lens: solve f, then confirm the SOLVER's own forward-propagated achieved
    # waist hits (w0_t, z_t) and the self-reported coupling is ~1 (a clean mode-match).
    lam = 1064.0
    for (w_in, w_t, z_t) in ((0.30, 0.10, 200.0), (0.20, 0.20, 150.0), (0.15, 0.45, 250.0)):
        r = mode_match_lens(w_in, 100.0, w_t, z_t, lam)
        if not r.get("ok"):
            fails.append("mode_match_lens(%g,%g,%g) failed: %s" % (w_in, w_t, z_t, r.get("error")))
            continue
        if not (close(r["achieved_w0"], w_t, 1e-4) and close(r["achieved_z"], z_t, 1e-3)):
            fails.append("mode_match achieved (w0=%.5f,z=%.4f) != target (%.5f,%.4f)"
                         % (r["achieved_w0"], r["achieved_z"], w_t, z_t))
        if not close(r["coupling"], 1.0, 1e-6):
            fails.append("mode_match coupling %.6f != 1 (achieved waist != target)" % r["coupling"])
        # unit-magnification closed form: f == (z_t^2 + zR^2)/(2 z_t)
        if abs(w_in - w_t) < 1e-12:
            zR = physics.q_from_waist(w_in, lam).imag
            if not close(r["f"], (z_t * z_t + zR * zR) / (2.0 * z_t), 1e-6):
                fails.append("unit-mag focal closed form: %.4f" % r["f"])

    # inverse sanity: pick an f, propagate to a real output waist, confirm the solver
    # RECOVERS that same f from the resulting (w0_t, z_t).
    f_true, s_true = 75.0, 120.0
    q_in = physics.q_from_waist(0.25, lam)
    q_out = physics.q_propagate(physics.q_propagate(q_in, physics.abcd_free(s_true)),
                                physics.abcd_lens(f_true))
    w_out, z_out = _waist_from_q(q_out, lam)
    rec = mode_match_lens(0.25, s_true, w_out, z_out, lam)
    if not (rec.get("ok") and (close(rec["f"], f_true, 1e-3) or close(rec.get("f_alt") or 1e9, f_true, 1e-3))):
        fails.append("solver did not recover f=%.3f (got f=%.4f f_alt=%s)"
                     % (f_true, rec.get("f", float("nan")), rec.get("f_alt")))

    # no real solution -> {ok:False} (do NOT fabricate a focal). Demagnifying a long-zR input
    # to a tight waist too CLOSE to the lens is unreachable (the focused spot cannot sit inside
    # ~ the Rayleigh-bounded minimum), so the discriminant goes negative.
    if mode_match_lens(0.30, 100.0, 0.10, 80.0, lam).get("ok") is not False:
        fails.append("unreachable demag target not rejected (should have no real focal)")
    if mode_match_lens(0.5, 100.0, -0.1, 100.0, lam).get("ok") is not False:
        fails.append("negative target waist not rejected")

    if fails:
        print("DESIGN SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("DESIGN SELFTEST PASSED")
