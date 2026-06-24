"""Linearized influence-matrix corrector family (Wave-2 A8 / A7 / A6).

This module is the *agent-facing auto-aligner* — the same corrector the promo
teased. It is GENERIC and SCENE-AGNOSTIC: nothing here is hardcoded to one
bench. Given a list of control DOFs (the tip/tilt/translation knobs of some
actuator elements) and a list of reference apertures, it measures how far the
beam misses each aperture, calibrates the Jacobian by poking each DOF and
re-tracing, and drives the knobs until the beam is centered.

Three layers, smallest first:

  * A8 - the *measurement*. ``aperture_residual`` is the perpendicular miss
    distance of the beam at one reference aperture plane; ``measure_y`` stacks
    those over several apertures into the vector ``y`` the solvers consume.
    ``offset_from_throughput`` recovers a beam offset from a pinhole throughput
    reading, ``d = w * sqrt(-0.5 * ln T)`` (the algebraic inverse of the
    verified ``tracer._clip_T`` on-axis sampling).

  * A7 - the *engine*. ``influence_solve`` runs the closed loop for ANY set of
    control DOFs and ANY measurement vector: calibrate ``A = dy/du`` column by
    column (poke each DOF by a small delta, re-trace, finite-difference),
    pseudo-invert ``A`` (numpy least-squares / truncated-SVD, or a pure-python
    normal-equations fallback), and iterate
    ``u_{k+1} = u_k - g * A_pinv (y_k - y_target)`` to an epsilon. Returns the
    residual before/after, the step count, convergence flag, and the full
    per-iteration residual history.

  * A6 - the *canonical application*. ``beam_walk`` is the 4-DOF two-mirror walk
    (M1 tip/tilt set position at a near iris, M2 tip/tilt set angle at a far
    iris): a thin wrapper that picks those four DOFs + the two apertures and
    calls ``influence_solve``.

The only new physical law underneath all of this is the steering Jacobian
scale: a mirror tilted by theta deflects the reflected ray by 2*theta. That
"2*theta" law was verified against the physicist oracle (DIMENSIONAL + NUMERIC
at rtol 1e-9 + SANITY, 5/5) before this shipped. Every other kernel reused here
(``compute_residual``, ports x matrix_world, ``_clip_T``, the ABCD trace) was
already verified.

CONTRACT: the solvers MOVE DOFs (that is their whole job) but are only invoked
ON DEMAND. Importing this module does nothing; a normal ``trace_scene`` never
calls in here. So every build_example scene traces byte-identical until someone
calls ``auto_align`` / ``beam_walk`` / ``influence_solve``.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from . import geometry, tracer, mounts, alignment

try:                                            # numpy ships with Blender's python (2.x)
    import numpy as _np
except Exception:                               # ... but never assume it; pure-python fallback below
    _np = None


# Element types that legitimately define a reference axis / success plane for
# centering: an iris/aperture/pinhole stop, or any detector-class terminal.
APERTURE_TYPES = ('APERTURE', 'PINHOLE')
REFERENCE_TYPES = APERTURE_TYPES + tracer.TERMINAL          # + DETECTOR/PHOTODIODE/POWER_METER/WFS
STEER_KINDS = ('TIP', 'TILT', 'ROT', 'TRANS_X', 'TRANS_Y', 'TRANS_Z')


# --------------------------------------------------------------------------- #
# A8 - centering metric / objective (the measurement vector y)
# --------------------------------------------------------------------------- #

def _ray_to(segs, name):
    """The segment that lands on element `name` (the chief ray reaching it)."""
    return next((s for s in segs if s.get("to") == name), None)


def aperture_transverse_basis(obj):
    """A right-handed (u, v) basis spanning element `obj`'s aperture plane, from
    its IN-port world normal. The same construction `alignment._miss_vec` uses,
    lifted here so the metric is reusable without a downstream target."""
    ip = alignment._first(obj.optics, 'IN')
    if ip is None:
        n = geometry.world_normal(obj, (0.0, 0.0, 1.0))
        c = obj.matrix_world.translation.copy()
    else:
        n = geometry.world_normal(obj, ip.local_normal)
        c = geometry.world_port(obj, ip.local_position)
    u = n.cross(Vector((0.0, 0.0, 1.0)))
    if u.length < 1e-6:
        u = n.cross(Vector((1.0, 0.0, 0.0)))
    u.normalize()
    v = n.cross(u).normalized()
    return c, n, u, v


def _ray_plane_hit(p1, p2, plane_c, plane_n):
    """World point where the ray (p1 -> through p2) crosses the aperture plane
    (point plane_c, normal plane_n), or None if (near-)parallel."""
    d = (p2 - p1)
    if d.length < 1e-9:
        return None
    d = d.normalized()
    denom = d.dot(plane_n)
    if abs(denom) < 1e-6:
        return None
    t = (plane_c - p1).dot(plane_n) / denom
    return p1 + d * t


def _crossing_for(segs, obj, plane_c, plane_n):
    """Find the chief ray's crossing of `obj`'s aperture plane EVEN WHEN the ray
    walked off the clear aperture (the tracer then drops the `to==obj` segment).

    Preferred: the segment the tracer recorded as landing on obj (p2 is the exact
    hit). Fallback: of all forward segments whose extension crosses the plane in
    front of them, pick the one whose crossing is closest to the aperture center
    (the chief ray that was aimed at it). This makes the metric smooth and always
    defined - no sentinel - so a DOF poke that nudges the beam off the sensor edge
    still produces a finite, differentiable miss (the §3.1 plane-crossing idea)."""
    s = _ray_to(segs, obj.name)
    if s is not None:
        return Vector(s["p2"])
    best, best_d = None, None
    for s in segs:
        p1, p2 = Vector(s["p1"]), Vector(s["p2"])
        hit = _ray_plane_hit(p1, p2, plane_c, plane_n)
        if hit is None:
            continue
        d = (p2 - p1)
        if d.length < 1e-9:
            continue
        # the crossing must be ahead of the segment's launch (t >= -segment length),
        # i.e. the ray is heading toward (not away from) the plane
        if (hit - p1).dot(d) < -1e-6 * d.length:
            continue
        off = (hit - plane_c).length
        if best is None or off < best_d:
            best, best_d = hit, off
    return best


def aperture_miss(segs, obj):
    """2-D miss of the beam at `obj`'s aperture plane, in the aperture (u, v)
    basis, in mm. Returns Vector((du, dv)), or None only when NO ray is heading
    toward the plane at all (a truly dark aperture).

    The miss is the in-plane component of (crossing - aperture_center). When the
    tracer recorded a `to==obj` segment, its `p2` is the exact ray->aperture
    intersection; otherwise the crossing is recovered analytically (smooth, no
    sentinel) so the Jacobian stays well-conditioned even when a poke walks the
    beam off the sensor edge."""
    c, n, u, v = aperture_transverse_basis(obj)
    hit = _crossing_for(segs, obj, c, n)
    if hit is None:
        return None
    miss = hit - c
    return Vector((miss.dot(u), miss.dot(v)))


def aperture_residual(segs, obj):
    """Scalar perpendicular miss distance (mm) of the beam at `obj` (A8 residual
    r_i). |aperture_miss|; -1.0 when no beam reaches the plane (dark)."""
    m = aperture_miss(segs, obj)
    return -1.0 if m is None else m.length


def offset_from_throughput(T, w_mm):
    """Recover a beam-center offset `d` (mm) from a pinhole throughput reading T,
    the sibling of the verified `tracer._clip_T`.

    For a small on-axis pinhole the sampled fraction of a Gaussian whose center
    sits a distance d off the hole is T ~ exp(-2 d^2 / w^2); inverting,
        d = w * sqrt(-0.5 * ln T).
    T=1 -> d=0 (centered); T->0 -> d->inf (fully missed). Returns None for a
    non-physical reading (T<=0 or T>1) or a degenerate spot (w<=0)."""
    if w_mm is None or w_mm <= 0.0:
        return None
    if T is None or T <= 0.0 or T > 1.0:
        return None
    if T >= 1.0:
        return 0.0
    return w_mm * math.sqrt(-0.5 * math.log(T))


def measure_y(segs, apertures, missing=1.0e6):
    """Stack the per-aperture (du, dv) misses into the flat measurement vector y
    the solvers consume: y = [du_0, dv_0, du_1, dv_1, ...] in mm. An aperture the
    beam misses entirely contributes a large finite `missing` sentinel on each
    axis so the solver still drives toward it (rather than dropping the row)."""
    y = []
    for obj in apertures:
        m = aperture_miss(segs, obj)
        if m is None:
            y.extend((missing, missing))
        else:
            y.extend((m[0], m[1]))
    return y


# --------------------------------------------------------------------------- #
# small linear-algebra layer (numpy if present, pure-python fallback)
# --------------------------------------------------------------------------- #

def _pinv_apply(A, b, rcond=1e-6):
    """Solve `A x ~= b` in the least-squares / minimum-norm sense and return x.

    A is a list of rows (m x n), b a length-m list. With numpy: a truncated-SVD
    pseudoinverse (drops singular values below rcond * sigma_max -> noise- and
    rank-tolerant for redundant sensors or surplus DOFs). Without numpy: the
    normal equations (A^T A) x = A^T b solved by Gaussian elimination, with a
    Tikhonov ridge for conditioning."""
    m = len(A)
    n = len(A[0]) if m else 0
    if m == 0 or n == 0:
        return [0.0] * n

    if _np is not None:
        Am = _np.array(A, dtype=float)
        bm = _np.array(b, dtype=float)
        U, s, Vt = _np.linalg.svd(Am, full_matrices=False)
        smax = s[0] if s.size else 0.0
        cut = rcond * smax
        s_inv = _np.array([(1.0 / si if si > cut else 0.0) for si in s])
        x = Vt.T @ (s_inv * (U.T @ bm))
        return [float(v) for v in x]

    # --- pure python: ridge-regularized normal equations ---------------------
    AtA = [[sum(A[k][i] * A[k][j] for k in range(m)) for j in range(n)] for i in range(n)]
    Atb = [sum(A[k][i] * b[k] for k in range(m)) for i in range(n)]
    diag = max((AtA[i][i] for i in range(n)), default=1.0)
    ridge = 1e-9 * (diag if diag > 0.0 else 1.0)
    for i in range(n):
        AtA[i][i] += ridge
    return _gauss_solve(AtA, Atb)


def _gauss_solve(M, b):
    """Gaussian elimination with partial pivoting for a small square system."""
    n = len(b)
    A = [row[:] + [b[i]] for i, row in enumerate(M)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-15:
            continue
        A[col], A[piv] = A[piv], A[col]
        pv = A[col][col]
        for j in range(col, n + 1):
            A[col][j] /= pv
        for r in range(n):
            if r != col and abs(A[r][col]) > 0.0:
                f = A[r][col]
                for j in range(col, n + 1):
                    A[r][j] -= f * A[col][j]
    return [A[i][n] for i in range(n)]


def _residual_norm(y, y_target):
    return math.sqrt(sum((a - b) * (a - b) for a, b in zip(y, y_target)))


# --------------------------------------------------------------------------- #
# A7 - generic closed-loop influence-matrix engine
# --------------------------------------------------------------------------- #

class ControlDOF:
    """A single steerable knob: (object, the AdjustmentDOF, label). Reads/writes
    `dof.current` and re-composes the owner's pose on every move - exactly what
    `alignment.align_element` does for its 2-DOF solve, generalized to N."""

    __slots__ = ("obj", "dof", "label")

    def __init__(self, obj, dof, label=None):
        self.obj = obj
        self.dof = dof
        self.label = label or "%s.%s" % (obj.name, dof.kind)

    @property
    def value(self):
        return self.dof.current

    @value.setter
    def value(self, v):
        self.dof.current = geometry.clamp(v, self.dof.min_val, self.dof.max_val)

    def _ensure_base(self):
        if not self.obj.optics.base_pose_set and len(self.obj.optics.dofs):
            mounts.store_base_matrix(self.obj.optics, self.obj.matrix_world.copy())


def resolve_controls(scene, actuators):
    """Turn a spec into a flat list of ControlDOF. `actuators` accepts:
      * a list of ControlDOF (passed through), or
      * a list of element names -> all that element's steering DOFs, or
      * a list of (name, kind) / (name, [kinds]) -> only those DOFs.
    Order is preserved (M1 tip, M1 tilt, M2 tip, M2 tilt ...)."""
    out = []
    for spec in actuators:
        if isinstance(spec, ControlDOF):
            out.append(spec)
            continue
        if isinstance(spec, (tuple, list)):
            name, want = spec[0], spec[1]
            kinds = (want,) if isinstance(want, str) else tuple(want)
        else:
            name, kinds = spec, STEER_KINDS
        obj = scene.objects.get(name)
        if not obj or not getattr(obj, "optics", None):
            continue
        for d in obj.optics.dofs:
            if d.kind in kinds:
                out.append(ControlDOF(obj, d))
    return out


def resolve_apertures(scene, targets):
    """Turn `targets` (list of names or objects) into a list of reference
    objects (irises / detectors)."""
    out = []
    for t in targets:
        obj = t if not isinstance(t, str) else scene.objects.get(t)
        if obj is not None and getattr(obj, "optics", None):
            out.append(obj)
    return out


def _retrace(scene):
    segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)
    tracer.cached_segments = segs
    return segs


def _apply(controls):
    """Recompose every controlled object's pose from its DOFs, then refresh the
    dependency graph so matrix_world (which the tracer reads) is current."""
    for c in {id(c.obj): c for c in controls}.values():
        mounts.compose_pose(c.obj)
    bpy.context.view_layer.update()


def calibrate_jacobian(scene, controls, apertures, y0, delta=0.5):
    """Finite-difference Jacobian A[:,j] = (y(u+delta_j) - y(u)) / delta_j by
    poking each control DOF and re-tracing (central column build). Returns A as
    a list of rows (len(y) x len(controls))."""
    m = len(y0)
    cols = []
    for c in controls:
        old = c.value
        step = delta
        probe = geometry.clamp(old + step, c.dof.min_val, c.dof.max_val)
        if abs(probe - old) < 1e-9:                 # pinned at the top -> poke downward
            probe = geometry.clamp(old - step, c.dof.min_val, c.dof.max_val)
        step = probe - old
        if abs(step) < 1e-9:                        # DOF fully pinned (min == max)
            cols.append([0.0] * m)
            continue
        c.value = probe
        _apply(controls)
        yp = measure_y(_retrace(scene), apertures)
        c.value = old                               # restore exactly
        _apply(controls)
        cols.append([(yp[i] - y0[i]) / step for i in range(m)])
    # transpose columns -> rows
    return [[cols[j][i] for j in range(len(controls))] for i in range(m)]


def influence_solve(scene, actuators, targets=None, y_target=None,
                    gain=1.0, eps=0.02, max_iters=8, delta=0.5, recalibrate=False):
    """Generic closed-loop influence-matrix corrector (A7).

    Drives the control DOFs `actuators` until the measurement vector y (the
    stacked per-aperture misses at `targets`) reaches `y_target` (default: all
    zeros = beam centered on every reference) within `eps` mm, or `max_iters`
    pass. The control law is u <- u - gain * A_pinv (y - y_target); A is
    calibrated once (or every iteration if `recalibrate`).

    Returns a JSON-able dict:
      {ok, residual_before, residual_after, iterations, converged,
       history:[r0, r1, ...], n_controls, n_targets, controls:[labels]}.
    """
    controls = resolve_controls(scene, actuators)
    if not controls:
        return {"ok": False, "error": "no controllable DOFs resolved"}
    for c in controls:
        c._ensure_base()

    if targets is None:
        apertures = auto_targets(scene, controls)
    else:
        apertures = resolve_apertures(scene, targets)
    if not apertures:
        return {"ok": False, "error": "no reference apertures resolved"}

    segs = _retrace(scene)
    y = measure_y(segs, apertures)
    if y_target is None:
        y_target = [0.0] * len(y)
    elif len(y_target) != len(y):
        return {"ok": False, "error": "y_target length %d != measurement length %d"
                % (len(y_target), len(y))}

    r0 = _residual_norm(y, y_target)
    history = [round(r0, 6)]

    A = calibrate_jacobian(scene, controls, apertures, y, delta=delta)

    converged = r0 <= eps
    it = 0
    while it < max_iters and not converged:
        it += 1
        if recalibrate and it > 1:
            A = calibrate_jacobian(scene, controls, apertures, y, delta=delta)
        err = [y[i] - y_target[i] for i in range(len(y))]
        du = _pinv_apply(A, err)
        for c, step in zip(controls, du):
            c.value = c.value - gain * step
        _apply(controls)
        y = measure_y(_retrace(scene), apertures)
        r = _residual_norm(y, y_target)
        history.append(round(r, 6))
        if r <= eps:
            converged = True
        # divergence guard: if a step made it much worse and we are not centered,
        # halve the effective gain for the rest of the run (line-search lite).
        elif r > history[-2] * 2.0 and gain > 0.05:
            gain *= 0.5

    r_after = _residual_norm(measure_y(_retrace(scene), apertures), y_target)
    return {
        "ok": True,
        "residual_before": round(r0, 6),
        "residual_after": round(r_after, 6),
        "iterations": it,
        "converged": bool(converged),
        "history": history,
        "n_controls": len(controls),
        "n_targets": len(apertures),
        "controls": [c.label for c in controls],
        "targets": [a.name for a in apertures],
    }


# --------------------------------------------------------------------------- #
# B4 - interferometer tilt-null solver (fringe-frequency measurement)
# --------------------------------------------------------------------------- #
# The benchtop ritual "spread the fringes to a single null": two interfering arms
# whose wavefronts differ by a relative TILT print a dense straight-fringe pattern,
# I(x,y) = I1 + I2 + 2*sqrt(I1 I2) cos(k (OPD0 + tilt_x x + tilt_y y)), k = 2pi/lambda.
# The fringe spatial frequency along an axis is fx = tilt_x / lambda (cycles per mm);
# nulling the tilt drives (fx,fy) -> 0, i.e. a single broad fringe. We:
#   (1) recover (fx,fy) from the 2-D fringe image (scan._fringe_array) by a phase-ramp
#       fit (per-axis analytic-signal lag-one phase -- unbiased near zero, robust to the
#       Gaussian spot envelope after a high-pass), then
#   (2) drive the two steering tip/tilt DOFs with the SAME influence-matrix engine the
#       aperture solvers use, but with y = [fx, fy] and y_target = [0, 0], until |f| -> 0,
#   (3) run a 1-DOF piston (OPD translation) search to peak the fringe visibility.
#
# The fringe kernel (physics.interfere) and the 2-D fringe array (scan._fringe_array)
# are reused verbatim; the ONE new relation, fx = tilt_x / lambda, is physics_verified.


def _hilbert_axis(x, axis):
    """1-D analytic signal of a real array along `axis` (the discrete Hilbert transform:
    double the positive-frequency half-spectrum, zero the negative). Used to read the
    fringe carrier's local phase ramp without a scipy dependency."""
    n = x.shape[axis]
    Xf = _np.fft.fft(x, axis=axis)
    h = _np.zeros(n)
    if n % 2 == 0:
        h[0] = h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[0] = 1.0
        h[1:(n + 1) // 2] = 2.0
    shape = [1, 1]
    shape[axis] = n
    return _np.fft.ifft(Xf * h.reshape(shape), axis=axis)


def _boxblur(a, k):
    """Separable moving-average blur (radius k) via cumulative sums -- the smooth Gaussian
    spot envelope estimate we subtract to high-pass the fringes (no scipy)."""
    c = _np.cumsum(_np.pad(a, ((k, k), (0, 0)), mode='edge'), axis=0)
    a = (c[2 * k:] - c[:-2 * k]) / (2.0 * k)
    c = _np.cumsum(_np.pad(a, ((0, 0), (k, k)), mode='edge'), axis=1)
    return (c[:, 2 * k:] - c[:, :-2 * k]) / (2.0 * k)


def tilt_estimate(fringe_image, wavelength_nm, pixel_pitch_mm, floor=0.06):
    """Recover the fringe spatial frequency (fx, fy) in CYCLES PER MM from a 2-D fringe
    intensity image, i.e. the relative wavefront tilt via fx = tilt_x / lambda (the
    physics_verified B4 relation -- here returned as the directly measurable frequency).

    `fringe_image` is a 2-D float array (the intensity channel of scan._fringe_array, rows
    index the detector v-axis, columns the u-axis). `pixel_pitch_mm` is the physical pixel
    pitch (sensor field / resolution). Method: mask to the lit spot, subtract a blurred
    copy to remove the Gaussian envelope, then for EACH axis build the 1-D analytic signal
    and read the power-weighted lag-one phase -> the mean carrier frequency along that axis
    (an unbiased phase-ramp fit, far more robust than a single 2-D FFT peak when the spot
    envelope dominates the spectrum). Returns (fx, fy) cyc/mm; (0, 0) for an unlit frame.

    `wavelength_nm` is accepted so a caller can convert back to an angular tilt
    tilt_x = fx * lambda (radians) if desired; the frequency itself is wavelength-free."""
    if _np is None:
        return 0.0, 0.0
    img = _np.asarray(fringe_image, dtype=float)
    if img.ndim != 2 or img.size == 0:
        return 0.0, 0.0
    px = img.shape[0]
    mx = float(img.max())
    if mx <= 1e-12:
        return 0.0, 0.0
    mask = img > floor * mx
    if int(mask.sum()) < 25:
        return 0.0, 0.0
    k = max(3, px // 10)
    hp = (img - _boxblur(img, k)) * mask
    pitch = pixel_pitch_mm if pixel_pitch_mm > 1e-12 else 1.0

    def axis_freq(axis):
        z = _hilbert_axis(hp, axis)
        if axis == 0:                                # rows -> v carrier (fy)
            prod = z[1:, :] * _np.conj(z[:-1, :])
            w = mask[1:, :] & mask[:-1, :]
        else:                                        # cols -> u carrier (fx)
            prod = z[:, 1:] * _np.conj(z[:, :-1])
            w = mask[:, 1:] & mask[:, :-1]
        s = (prod * w).sum()
        ph = float(_np.angle(s)) if abs(s) > 1e-20 else 0.0
        return ph / (2.0 * math.pi * pitch)

    return axis_freq(1), axis_freq(0)


# the detector element-types that carry a recordable fringe pattern (TERMINALs minus the
# wavefront sensor, which records a Zernike map, and the beam dump, which records nothing).
def _fringe_detectors(scene):
    out = []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if op and op.is_optical and op.element_type in tracer.TERMINAL \
                and op.element_type not in ('WAVEFRONT_SENSOR', 'BEAM_DUMP'):
            out.append(obj)
    return out


def _resolve_fringe_detector(scene, detector, segs):
    """The named detector, else the lit terminal receiving the most (>=2) interfering beams."""
    if detector is not None:
        obj = detector if not isinstance(detector, str) else scene.objects.get(detector)
        if obj is not None and getattr(obj, "optics", None):
            return obj
    best, best_n = None, 1
    for d in _fringe_detectors(scene):
        n = sum(1 for s in segs if s.get("to") == d.name)
        if n > best_n:
            best, best_n = d, n
    return best


def _sensor_field(det, segs=None):
    """(field_mm, px) for the tilt-null sensor. The field MUST span the recombined spot (a
    few beam radii) so the straight tilt-fringes are sampled across the overlap region -- the
    detector's tiny default photodiode field (e.g. 1.28 mm) crops the beam and corrupts the
    fringe-frequency scale. We size the field to ~6x the beam radius reaching the detector
    (clamped into [4, 20] mm), at a fixed 192 px so the pixel pitch is a clean field/px."""
    px = 192
    w = 0.0
    if segs is not None:
        ws = [s.get("w_mm", 0.0) for s in segs if s.get("to") == det.name]
        w = max(ws) if ws else 0.0
    if w <= 1e-6:
        w = max(getattr(det.optics, "clear_aperture", 0.0) * 0.12, 0.6)
    field = max(4.0, min(6.0 * w, 20.0))
    return field, px


def _fringe_state(scene, det, field_mm, px, ref_extent_mm=None):
    """Trace, synthesize the detector fringe image, and read (fx, fy, |f|, visibility,
    fringe_count, image). The single measurement front-end the tilt-null loop calls.

    `ref_extent_mm` is the aperture width the fringe count is reckoned over (the recombined
    beam diameter): fringe_count = |f| * ref_extent. Passing a FIXED reference keeps the count
    comparable across iterations (the lit-spot mask widens as the fringes broaden, which would
    otherwise inflate the count); when omitted the current lit-spot extent is used."""
    from . import scan as _scan
    segs = _retrace(scene)
    res = _scan._fringe_array(det, segs, field_mm, px, norm='self')
    arr = res[0] if isinstance(res, tuple) else res
    beams = [s for s in segs if s.get("to") == det.name]
    wl = beams[0].get("wavelength", 632.8) if beams else 632.8
    if arr is None:
        return {"fx": 0.0, "fy": 0.0, "fmag": 0.0, "visibility": -1.0,
                "fringe_count": 0.0, "image": None, "n_beams": len(beams),
                "lit_extent": 0.0}
    inten = arr[..., 0]
    pitch = field_mm / px
    fx, fy = tilt_estimate(inten, wl, pitch)
    fmag = math.hypot(fx, fy)
    _p, vis, _s = alignment.measure(segs, det.name, det.optics.analyzer)
    lit = 0.0
    if _np is not None:
        mask = inten > 0.06 * float(inten.max() or 1.0)
        if mask.any():
            ys, xs = _np.where(mask)
            lit = max((xs.max() - xs.min()), (ys.max() - ys.min())) * pitch
    else:
        lit = field_mm
    extent = ref_extent_mm if ref_extent_mm else lit
    return {"fx": fx, "fy": fy, "fmag": fmag, "visibility": float(vis),
            "fringe_count": fmag * float(extent), "image": inten,
            "n_beams": len(beams), "lit_extent": float(lit)}


def _auto_tilt_actuators(scene, det, segs):
    """Pick the two steering DOFs to null the tilt: the tip+tilt of the LAST steerable
    mirror on the beam path that reaches `det` (the recombining-arm mirror -- tilting it
    walks the recombined wavefront's tilt with minimal beam walk-off). Falls back to the
    nearest steerable element upstream of the detector."""
    order = _beam_order(scene, segs)
    rank = {n: i for i, n in enumerate(order)}
    det_rank = rank.get(det.name, len(order))
    cand = []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        if op.element_type != 'MIRROR':
            continue
        if not any(d.kind in ('TIP', 'TILT') for d in op.dofs):
            continue
        r = rank.get(obj.name, -1)
        if r < det_rank:
            cand.append((r, obj))
    if not cand:
        return []
    cand.sort(key=lambda t: t[0])
    obj = cand[-1][1]                                 # closest steerable mirror upstream of det
    return [ControlDOF(obj, d) for d in obj.optics.dofs if d.kind in ('TIP', 'TILT')]


def _piston_dof(scene, det, segs):
    """The OPD translation knob: a TRANS_* DOF on an element in one interfering arm reaching
    `det` (the Michelson stage mirror). Returns a ControlDOF or None."""
    names = {s.get("from") for s in segs if s.get("to") == det.name}
    # walk the parent chain so upstream arm elements (the stage mirror) are included
    for s in list(segs):
        if s.get("to") == det.name:
            cur = s
            guard = 0
            while cur is not None and guard < 64:
                if cur.get("from"):
                    names.add(cur.get("from"))
                p = cur.get("parent", -1)
                cur = segs[p] if (p is not None and 0 <= p < len(segs)) else None
                guard += 1
    for name in names:
        obj = scene.objects.get(name) if name else None
        op = getattr(obj, "optics", None) if obj else None
        if not op:
            continue
        for d in op.dofs:
            if d.kind.startswith('TRANS'):
                return ControlDOF(obj, d)
    return None


def tilt_null(scene, detector=None, mirrors=None, gain=1.0, eps=0.04,
              max_iters=8, delta=0.4, piston_steps=21):
    """Interferometer tilt-null solver (B4): drive the relative wavefront tilt between two
    interfering arms to zero (dense fringes -> one broad fringe), then a 1-DOF piston search
    sets the visibility. ON-DEMAND only (it MOVES DOFs); a normal trace never enters here.

    Reads the 2-D fringe image at `detector` (scan._fringe_array), estimates the fringe
    frequency (fx, fy) = tilt/lambda (tilt_estimate), and drives the two steering tip/tilt
    DOFs with the influence-matrix engine (calibrate dy/du by poking + re-tracing, then
    u <- u - gain*A_pinv*(y - 0)) until |f| -> 0. Finally sweeps the OPD/piston DOF to peak
    the fringe visibility.

      * `detector`: the recombination detector (name/object); auto-picked (the lit terminal
        with the most interfering beams) when omitted.
      * `mirrors`: the steering actuators -- names / [name, kind] pairs / ControlDOF, as
        resolve_controls accepts; auto-picked (the recombining-arm mirror's tip+tilt) when
        omitted.

    Returns {ok, detector, tilt_before/after (deg), fringe_freq_before/after (cyc/mm),
    fringe_count_before/after, visibility_before/after, iterations, converged, history,
    controls, piston}. `history` is the per-iteration |f| (cyc/mm), monotone to the null."""
    if _np is None:
        return {"ok": False, "error": "tilt_null requires numpy (the fringe FFT)"}
    segs = _retrace(scene)
    det = _resolve_fringe_detector(scene, detector, segs)
    if det is None:
        return {"ok": False, "error": "no fringe detector with interfering beams found"}

    if mirrors is None:
        controls = _auto_tilt_actuators(scene, det, segs)
    else:
        controls = resolve_controls(scene, mirrors)
        controls = [c for c in controls if c.dof.kind in ('TIP', 'TILT')]
    if not controls:
        return {"ok": False, "error": "no tip/tilt steering DOFs resolved to null the tilt"}
    for c in controls:
        c._ensure_base()

    field_mm, px = _sensor_field(det, segs)
    wl = next((s.get("wavelength", 632.8) for s in segs if s.get("to") == det.name), 632.8)
    lam_mm = wl * 1.0e-6
    # reference aperture for the fringe count = the recombined beam diameter (2w) at the
    # detector, so "count = |f| * diameter" is comparable across iterations (the lit spot
    # widens as the fringes broaden, which would otherwise inflate a spot-mask count).
    w_det = max((s.get("w_mm", 0.0) for s in segs if s.get("to") == det.name), default=0.0)
    ref_extent = 2.0 * w_det if w_det > 1e-6 else field_mm

    def state():
        return _fringe_state(scene, det, field_mm, px, ref_extent)

    st0 = state()
    if st0["n_beams"] < 2:
        return {"ok": False, "error": "detector '%s' has < 2 interfering beams (no fringes)"
                % det.name}
    r0 = st0["fmag"]
    history = [round(r0, 6)]

    # The single-frame fringe frequency is UNSIGNED -- a real intensity image cannot tell
    # +tilt from -tilt (cos is even), so |f|(u) is a V-shaped well with its minimum at the
    # null. A linear influence-matrix inverse would not know which way is downhill across the
    # V; instead we Gauss-Newton-descend |f| directly: finite-difference d|f|/du with a SMALL
    # poke, step toward the floor along -grad, and line-search-backtrack so a step never makes
    # the fringes denser. The floor (~one fringe across the aperture) is the optical null:
    # below one fringe the tilt is unmeasurable, which IS "a single broad fringe".
    floor = max(eps, 0.85 / ref_extent if ref_extent > 1e-6 else eps)   # cyc/mm at <1 fringe
    poke = min(delta, 0.05)

    def fmag_now():
        return state()["fmag"]

    converged = r0 <= floor
    it = 0
    while it < max_iters and not converged:
        it += 1
        f0 = fmag_now()
        base = [c.value for c in controls]
        grad = []
        for j, c in enumerate(controls):
            old = c.value
            probe = geometry.clamp(old + poke, c.dof.min_val, c.dof.max_val)
            if abs(probe - old) < 1e-9:
                probe = geometry.clamp(old - poke, c.dof.min_val, c.dof.max_val)
            step = probe - old
            c.value = probe
            _apply(controls)
            fp = fmag_now()
            c.value = old
            _apply(controls)
            grad.append((fp - f0) / step if abs(step) > 1e-12 else 0.0)
        gnorm2 = sum(g * g for g in grad)
        if gnorm2 < 1e-12:
            break
        # Gauss-Newton step to drive f0 -> floor along the gradient of |f|
        scale = gain * (f0 - floor) / gnorm2
        improved = False
        for frac in (1.0, 0.5, 0.25, 0.1):
            for c, b, g in zip(controls, base, grad):
                c.value = geometry.clamp(b - frac * scale * g, c.dof.min_val, c.dof.max_val)
            _apply(controls)
            f1 = fmag_now()
            if f1 < f0 - 1e-4:
                improved = True
                break
        if not improved:                               # restore + stop (at the well bottom)
            for c, b in zip(controls, base):
                c.value = b
            _apply(controls)
            history.append(round(f0, 6))
            break
        history.append(round(f1, 6))
        if f1 <= floor:
            converged = True

    # --- 1-DOF piston / OPD search: peak the fringe visibility on the now-broad fringe ----
    piston_info = None
    st_mid = state()
    vis_before_piston = st_mid["visibility"]
    pist = _piston_dof(scene, det, segs)
    if pist is not None and piston_steps and piston_steps > 1:
        pist._ensure_base()
        lo, hi = pist.dof.min_val, pist.dof.max_val
        # search a +-2-wavelength window about the current OPD (fine enough to cross a fringe)
        span = min(max(hi - lo, 0.0), 4.0 * lam_mm) or (4.0 * lam_mm)
        base_x = pist.value
        best_v, best_x = -2.0, base_x
        for i in range(piston_steps):
            x = geometry.clamp(base_x - 0.5 * span + span * i / (piston_steps - 1), lo, hi)
            pist.value = x
            _apply([pist])
            sv = state()["visibility"]
            if sv > best_v:
                best_v, best_x = sv, x
        pist.value = best_x
        _apply([pist])
        piston_info = {"dof": pist.label, "set_mm": round(best_x, 6),
                       "visibility": round(best_v, 4)}

    st_after = state()
    # tilt magnitude (radians/deg) = fringe freq (cyc/mm) * lambda (mm/cyc)
    tilt_before_deg = math.degrees(r0 * lam_mm)
    tilt_after_deg = math.degrees(st_after["fmag"] * lam_mm)
    return {
        "ok": True,
        "detector": det.name,
        "tilt_before_deg": round(tilt_before_deg, 8),
        "tilt_after_deg": round(tilt_after_deg, 8),
        "fringe_freq_before": round(r0, 6),
        "fringe_freq_after": round(st_after["fmag"], 6),
        "fringe_count_before": round(st0["fringe_count"], 4),
        "fringe_count_after": round(st_after["fringe_count"], 4),
        "visibility_before": round(st0["visibility"], 4),
        "visibility_after": round(st_after["visibility"], 4),
        "visibility_before_piston": round(vis_before_piston, 4),
        "iterations": it,
        # nulled <=> at the ~1-fringe optical floor: |f| reached the floor OR the fringe count
        # collapsed to ~1 across the aperture (a single broad fringe; sub-fringe tilt is
        # unmeasurable from one intensity frame).
        "converged": bool(converged or st_after["fringe_count"] < 1.15),
        "history": history,
        "controls": [c.label for c in controls],
        "piston": piston_info,
        "floor": round(floor, 6),
        "sensor": {"field_mm": round(field_mm, 4), "px": px, "ref_extent_mm": round(ref_extent, 4)},
    }


# --------------------------------------------------------------------------- #
# auto-pick helpers (genericity: works on ANY setup when args are omitted)
# --------------------------------------------------------------------------- #

def _beam_order(scene, segs=None):
    """Element names in the order the beam reaches them (source -> ... -> end)."""
    segs = segs if segs is not None else _retrace(scene)
    order = []
    for s in segs:
        for end in (s.get("from"), s.get("to")):
            if end and end not in order:
                order.append(end)
    return order


def auto_actuators(scene):
    """Auto-pick the kinematic steering DOFs of every element that carries tip/
    tilt knobs, in beam order. This is the generic actuator set for `auto_align`
    when the caller does not name actuators."""
    order = _beam_order(scene)
    rank = {n: i for i, n in enumerate(order)}
    steerable = []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        if any(d.kind in ('TIP', 'TILT') for d in op.dofs):
            steerable.append(obj)
    steerable.sort(key=lambda o: rank.get(o.name, 1e9))
    controls = []
    for obj in steerable:
        for d in obj.optics.dofs:
            if d.kind in ('TIP', 'TILT'):
                controls.append(ControlDOF(obj, d))
    return controls


def auto_targets(scene, controls=None):
    """Auto-pick reference apertures: every iris/pinhole/detector DOWNSTREAM of
    the last actuator, in beam order. Falls back to all references if none are
    found downstream (e.g. the actuators sit after the only detector)."""
    segs = _retrace(scene)
    order = _beam_order(scene, segs)
    rank = {n: i for i, n in enumerate(order)}
    last_act = -1
    if controls:
        last_act = max((rank.get(c.obj.name, -1) for c in controls), default=-1)
    refs, refs_down = [], []
    for name in order:
        obj = scene.objects.get(name)
        op = getattr(obj, "optics", None) if obj else None
        if not op or not op.is_optical:
            continue
        if op.element_type in REFERENCE_TYPES:
            refs.append(obj)
            if rank.get(name, -1) > last_act:
                refs_down.append(obj)
    return refs_down or refs


# --------------------------------------------------------------------------- #
# A6 - two-mirror beam walk (the canonical 4-DOF application of A7)
# --------------------------------------------------------------------------- #

def beam_walk(scene, m1, m2, near, far, gain=1.0, eps=0.02, max_iters=8):
    """Canonical two-mirror beam walk: actuators = [M1 tip, M1 tilt, M2 tip,
    M2 tilt], targets = [near iris, far iris]. A thin wrapper that picks those
    four DOFs and the two apertures and calls the generic A7 engine. M1 (upstream)
    predominantly sets beam POSITION at the near plane; M2 (downstream) sets
    ANGLE at the far plane - the 4x4 Jacobian couples them and the solver inverts
    the coupling in one shot in the noise-free tracer (gain=1)."""
    actuators = [(m1, ('TIP', 'TILT')), (m2, ('TIP', 'TILT'))]
    return influence_solve(scene, actuators, targets=[near, far],
                           gain=gain, eps=eps, max_iters=max_iters)


# --------------------------------------------------------------------------- #
# top-level entry point (mirrors what optics_api.auto_align exposes)
# --------------------------------------------------------------------------- #

def auto_align(scene, actuators=None, targets=None, gain=1.0, eps=0.02, max_iters=8):
    """Generic on-demand auto-aligner. With no args it auto-picks the kinematic
    steering DOFs and the downstream reference apertures and walks the beam onto
    them; with args it steers exactly the named actuators onto the named targets.
    Returns the influence_solve report (ok/residual_before/after/iterations/
    converged/history)."""
    if actuators is None:
        controls = auto_actuators(scene)
        if not controls:
            return {"ok": False, "error": "no steerable (tip/tilt) elements found"}
        actuators = controls
    return influence_solve(scene, actuators, targets=targets,
                           gain=gain, eps=eps, max_iters=max_iters)


# This module registers no Blender classes by itself (the operator lives in
# `operators.py` to keep registration centralized); these no-ops let __init__'s
# uniform register()/unregister() loop include it without a special case.
def register():
    pass


def unregister():
    pass
