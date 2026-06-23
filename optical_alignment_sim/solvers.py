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
