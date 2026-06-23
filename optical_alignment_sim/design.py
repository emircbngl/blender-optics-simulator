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

CONTRACT: importing this module does nothing and these functions never mutate a
scene -- they are a pure on-demand design library, exactly like ``solvers.py`` is
a pure on-demand correction library.
"""
from __future__ import annotations

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

    if fails:
        print("DESIGN SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("DESIGN SELFTEST PASSED")
