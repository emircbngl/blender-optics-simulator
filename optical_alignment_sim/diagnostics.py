"""Bench-intelligence error-detection diagnostics (Wave-1 P0: tasks A1-A5).

This is a *read-only post-pass* over the data the tracer already produces. It NEVER
mutates the trace, the ray path, or any element pose -- it only inspects the flat
segment list (the `parent`-indexed tree) plus the element ports / DOFs that
`alignment.py` and `tracer.py` already expose, and surfaces conditions the engine
currently drops silently.

Every formula here is reused verbatim from an already-oracle-verified kernel
(`tracer._clip_T`'s `1 - exp(-2 a^2/w^2)`, the lossless-BS unitarity that makes the
energy budget close by construction, `alignment.compute_residual`'s angular error).
No new physical law is introduced.

Public entry point:

    run_diagnostics(scene) -> list[dict]

Each dict matches the `{kind, element, detail}` shape `optomech.validate()` already
uses, extended with a `severity` of "BAD" or "WARN":

    {"kind": str, "element": str | None, "detail": str, "severity": "BAD" | "WARN"}

Covered diagnostics:
  A1  beam_clipped     - a ray's geometrically-nearest plane crossing misses the
                         element's clear aperture (off > ca); the tracer silently
                         drops this ray. detail carries miss_mm.
  A2  vignetting       - the Gaussian wings truncate on an aperture-bearing element
                         (mirror / lens / BS): _clip_T < 0.99.
  A3  dark_detector    - a terminal receives no usable beam (measure() <= floor);
      orphan_source      a source whose power reaches no terminal.
  A4  energy_violation - per-node children exceed parent power, or the global budget
                         (leaves + absorbed) does not match the source within eps.
  A5  mount_limit      - the steering a mirror/optic needs (~ang_err, x2 for a
                         mirror) exceeds its TIP/TILT DOF range (max-min).

Wave-2 B2 adds one more (an open-loop DESIGN check, still a read-only post-pass):
  B2  relay_spacing    - two consecutive lenses in beam order, plausibly intended
                         as an afocal relay/telescope (separation within +-25% of
                         f1+f2), but detuned so |d-(f1+f2)| > tol -> the output is
                         no longer collimated (collimation error). Uses only the
                         lens focals + the traced separation; the design math lives
                         in design.py (oracle-verified afocal ABCD).
"""
from __future__ import annotations

import math

from mathutils import Vector

from . import geometry, tracer, alignment


# --- tolerances (module-level so callers / tests can read them) -------------
VIGNETTE_T = 0.99          # A2: flag when Gaussian throughput drops below this
DARK_FLOOR = 1.0e-4        # A3: a terminal below this (or measure()<0) is dark
ENERGY_EPS = 1.0e-3        # A4: per-node + global power-balance tolerance (fraction)
MOUNT_MARGIN_DEG = 0.0     # A5: extra slack beyond the raw DOF range

# Elements that carry a clear aperture the Gaussian beam can vignette on.
_APERTURE_BEARING = ('MIRROR', 'PRISM_MIRROR', 'DEFORMABLE_MIRROR',
                     'LENS', 'OBJECTIVE', 'BEAMSPLITTER', 'DICHROIC')

# A1: a plane crossing is only a meaningful "intended hit" when the ray is not
# grazing the surface (|d.n| above this) -- a near-parallel crossing happens
# billions of mm away and is not a beam walking off an optic, just divergence.
_MIN_COS_INCIDENCE = 0.05    # ~87 deg off-normal; below this the crossing is spurious
_MAX_CLIP_T = 1.0e5          # mm: reject absurd far-plane crossings outright
# A beam walked OFF an optic only if it grazed the edge -- its crossing sits within a
# few aperture widths of the surface center. A crossing far to the side (off >> ca) is
# a beam on an entirely different path (e.g. an unused BS output port escaping past a
# distant optic), NOT a clip. The A1 verify case misses by ~2.8x ca; the false
# positives sit at ~9-20x ca, so this cleanly separates them.
_MAX_MISS_RATIO = 4.0        # off must be <= ca * this to count as a near-miss clip


def _issue(kind, element, detail, severity):
    return {"kind": kind, "element": element, "detail": detail, "severity": severity}


# ---------------------------------------------------------------------------
# A1 - beam clipping (hard miss)
# ---------------------------------------------------------------------------

def _beam_clipped(scene, segs):
    """Surface the rays `tracer._find_next` silently drops because the
    geometrically-nearest plane crossing falls outside the clear aperture.

    Replays the same nearest-plane geometry the tracer uses (`interaction_surface`
    + `_ray_plane`), but separately tracks the nearest crossing IGNORING the
    aperture test. A ray that escapes (`to == None`) yet has a nearer plane
    crossing whose off-axis distance exceeds that element's clear aperture is a
    hard miss -- the beam walked off the optic.
    """
    issues = []
    elems = [o for o in scene.objects
             if getattr(o, "optics", None) and o.optics.is_optical]
    # only escaping segments can hide a dropped-ray clip; a segment that already
    # lands on an element was not dropped.
    for s in segs:
        if s.get("to") is not None:
            continue
        p1 = Vector(s["p1"])
        d = (Vector(s["p2"]) - p1)
        if d.length < 1e-9:
            continue
        d = d.normalized()
        from_name = s.get("from")
        # The geometrically-nearest plane crossing ahead of the ray, ignoring the
        # aperture gate -- the optic the beam WAS heading into. Mirrors the tracer's
        # nearest-crossing selection, but skips grazing/near-parallel crossings (those
        # sit billions of mm away and are not a beam walking off an optic).
        best = None  # (t, element, off, ca)
        for E in elems:
            if E.name == from_name:
                continue
            sp, sn, ca = tracer.interaction_surface(E)
            if sp is None:
                continue
            if abs(d.dot(sn)) < _MIN_COS_INCIDENCE:
                continue                       # grazing -> not an intended hit
            hit = tracer._ray_plane(p1, d, sp, sn)
            if hit is None:
                continue
            H, t = hit
            if t > _MAX_CLIP_T:
                continue                       # absurd far crossing -> divergence, not a clip
            off = (H - sp).length
            if best is None or t < best[0]:
                best = (t, E, off, ca)
        if best is None:
            continue
        t, E, off, ca = best
        # the tracer ACCEPTS a crossing only when off <= ca + 1e-3; the nearest crossing
        # this escaping ray would have hit is OVER aperture -> the tracer silently
        # dropped it. Restrict to a genuine near-miss (the beam grazed the edge, within a
        # few aperture widths) so a beam on a different path that merely crosses a distant
        # optic's plane is not mis-flagged.
        if ca > 0.0 and off > ca * _MAX_MISS_RATIO:
            continue
        if off > max(ca, 0.0) + 1e-3:
            miss = off - ca
            issues.append(_issue(
                "beam_clipped", E.name,
                "beam from %s misses %s clear aperture by miss_mm=%.3f (off=%.3f > ca=%.3f)"
                % (from_name, E.name, miss, off, ca),
                "BAD"))
    return issues


# ---------------------------------------------------------------------------
# A2 - vignetting (partial Gaussian clip)
# ---------------------------------------------------------------------------

def _vignetting(scene, segs):
    """Apply the oracle-verified `_clip_T = 1 - exp(-2 a^2/w^2)` at every
    aperture-bearing element using the per-segment incident beam radius `w_mm`
    and the element's clear aperture. Flag when T < VIGNETTE_T.

    Sanity anchors (already verified): a=w -> T=0.865, a=2w -> T=0.9997.
    """
    issues = []
    by_name = {o.name: o for o in scene.objects
               if getattr(o, "optics", None) and o.optics.is_optical}
    for s in segs:
        to_name = s.get("to")
        if to_name is None:
            continue
        E = by_name.get(to_name)
        if E is None or E.optics.element_type not in _APERTURE_BEARING:
            continue
        w = s.get("w_mm", 0.0)            # incident Gaussian radius at the element plane
        a = E.optics.clear_aperture
        if w <= 1e-9 or a <= 0.0:
            continue                       # no Gaussian / no aperture -> nothing to clip
        T = 1.0 - math.exp(-2.0 * a * a / (w * w))
        if T < VIGNETTE_T:
            sev = "BAD" if T < 0.90 else "WARN"
            issues.append(_issue(
                "vignetting", E.name,
                "Gaussian clip on %s: T=%.4f (w=%.3f mm, clear_aperture a=%.3f mm)"
                % (E.name, T, w, a),
                sev))
    return issues


# ---------------------------------------------------------------------------
# A3 - dark detector / orphan source
# ---------------------------------------------------------------------------

def _last_reached(segs, det_name):
    """Name the last real element the beam reached before it failed to land on the
    dark terminal -- the same parent-chain walk OPTICS_OT_power_budget uses.

    If a (sub-floor) beam still terminates on the detector, walk back from it. If
    NOTHING reaches the detector at all, the beam was mis-pointed: pick the strongest
    *escaping* leaf in the scene (the redirected ray) and report where it last
    interacted -- i.e. the optic the chain died at."""
    incoming = [s for s in segs if s.get("to") == det_name]
    if incoming:
        cur = max(incoming, key=lambda x: x["power"])
    else:
        # no segment lands here -> the beam went elsewhere. The deepest/strongest
        # segment whose `to` is None (escaped) names where the path actually ended.
        leaves = [s for s in segs if s.get("to") is None and s.get("from")]
        cur = max(leaves, key=lambda x: x["power"]) if leaves else None
    last, guard = None, 0
    while cur is not None and guard < 128:
        if cur.get("from"):
            last = cur["from"]
        p = cur.get("parent", -1)
        cur = segs[p] if 0 <= p < len(segs) else None
        guard += 1
    return last


def _dark_and_orphan(scene, segs):
    """A3: promote `measure()`'s silent power<0 sentinel into a `dark_detector`
    flag (and the inverse `orphan_source` for a source whose light reaches no
    terminal). `last_reached` localizes where the chain dies."""
    issues = []
    elems = [o for o in scene.objects
             if getattr(o, "optics", None) and o.optics.is_optical]
    terminals = [o for o in elems if o.optics.element_type in tracer.TERMINAL]
    # a BEAM_DUMP is an ABSORBER, not a measurement detector: it is SUPPOSED to be dark unless it is
    # catching a rejected beam, so a dark beam dump is not a fault (don't flag it as a dark_detector).
    detectors = [o for o in terminals if o.optics.element_type != 'BEAM_DUMP']

    # dark detectors: measure() < 0 (nothing terminates here) or below the floor
    for det in detectors:
        power, _vis, _strong = alignment.measure(segs, det.name, det.optics.analyzer)
        if power < 0.0:
            last = _last_reached(segs, det.name)
            issues.append(_issue(
                "dark_detector", det.name,
                "no beam reaches %s (measure power=-1 sentinel); last element reached=%s"
                % (det.name, last or "(none)"),
                "BAD"))
        elif power < DARK_FLOOR:
            last = _last_reached(segs, det.name)
            issues.append(_issue(
                "dark_detector", det.name,
                "%s reads power=%.3g < floor=%.3g; last element reached=%s"
                % (det.name, power, DARK_FLOOR, last or "(none)"),
                "BAD"))

    # orphan sources: a source whose power reaches NO terminal at all. A segment's
    # src_id ties every descendant back to its source; if no terminal-bound
    # segment carries that src_id, the source is orphaned.
    sources = [o for o in elems
               if o.optics.element_type in ('SOURCE', 'FIBER_COLLIMATOR')
               or o.optics.is_source]
    terminal_names = {o.name for o in terminals}
    reaching_terminal = {s.get("src_id", -1) for s in segs
                         if s.get("to") in terminal_names}
    for src in sources:
        # the src_ids this source emitted = segments whose `from` is this source
        emitted = {s.get("src_id", -1) for s in segs if s.get("from") == src.name}
        if not emitted:
            continue                       # source emitted nothing traceable -> not our concern here
        if emitted.isdisjoint(reaching_terminal):
            issues.append(_issue(
                "orphan_source", src.name,
                "%s emits but its power reaches no terminal (light is lost / escapes)"
                % src.name,
                "WARN"))
    return issues


# ---------------------------------------------------------------------------
# A4 - energy budget audit (per node + global)
# ---------------------------------------------------------------------------

def _energy_budget(scene, segs):
    """A4: power reconciliation over the `parent`-indexed segment tree.

    Per node: sum(child.power) <= parent.power * (1 + eps), else energy_violation.
    Global:   sum(leaf.power) == sum(source.power) within eps, where a leaf is any
              segment with no children (it escaped -> to==None, or it terminated /
              was absorbed). A silently-dropped clipped ray (A1) shows here as a
              budget hole. Lossless-BS unitarity (r = i*sqrt(R)) is already enforced
              in the tracer, so a correct model balances by construction.
    """
    issues = []
    n = len(segs)
    children = [[] for _ in range(n)]
    for i, s in enumerate(segs):
        p = s.get("parent", -1)
        if 0 <= p < n:
            children[p].append(i)

    # per-node conservation: a parent's power must cover the sum of its children. The
    # deficit (parent - children) is the power ABSORBED at that element -- legitimate
    # for a polarizer / filter / ND / isolator / partial aperture (Malus, Beer-Lambert,
    # _clip_T). Only an EXCESS (children > parent, i.e. R+T>1) is unphysical.
    absorbed = 0.0
    for i, s in enumerate(segs):
        kids = children[i]
        if not kids:
            continue
        p_in = s.get("power", 0.0)
        p_out = sum(segs[k].get("power", 0.0) for k in kids)
        absorbed += max(0.0, p_in - p_out)        # power dropped at this element
        if p_out > p_in * (1.0 + ENERGY_EPS) + ENERGY_EPS:
            issues.append(_issue(
                "energy_violation",
                s.get("from") or "(source)",
                "node after %s: children sum %.4f > parent %.4f (kind=%s) -- R+T>1, power created"
                % (s.get("from") or "(source)", p_out, p_in, s.get("kind")),
                "BAD"))

    # global budget: sum(leaf + absorbed) must reconcile with the source power. A leaf
    # is any segment with no children (it escaped to free space or terminated on a
    # detector); `absorbed` is the per-node deficit summed above. A silently-dropped
    # clipped ray (A1) leaves an interaction node with NO children that is NOT a true
    # leaf, so its power is counted neither as a leaf nor as absorbed -> it surfaces
    # here as an unaccounted residual (the budget hole).
    src_power = sum(s.get("power", 0.0) for s in segs if s.get("kind") == 'SOURCE')
    leaf_power = sum(s.get("power", 0.0)
                     for i, s in enumerate(segs) if not children[i])
    if src_power > 1e-9:
        residual = src_power - (leaf_power + absorbed)
        if abs(residual) > ENERGY_EPS * max(src_power, 1.0):
            issues.append(_issue(
                "energy_violation", None,
                "global budget: sources=%.4f vs leaves+absorbed=%.4f "
                "(leaves=%.4f, absorbed=%.4f), unaccounted residual=%.4f"
                % (src_power, leaf_power + absorbed, leaf_power, absorbed, residual),
                "BAD"))
    return issues


# ---------------------------------------------------------------------------
# A5 - mount limit / DOF range exhaustion
# ---------------------------------------------------------------------------

def _mount_limit(scene, segs):
    """A5: pre-emptive reachability check. The steering an element needs to put the
    beam on the next port is ~ its angular residual (`alignment.compute_residual`),
    DOUBLED for a mirror (a tip of theta deflects the reflected ray by 2*theta). If
    that exceeds the element's available TIP/TILT range (max_val - min_val), no knob
    turn can fix it -- the post must move. Flagged BEFORE the solver runs.
    """
    issues = []
    o_props = scene.optics
    for obj in scene.objects:
        props = getattr(obj, "optics", None)
        if not props or not props.is_optical:
            continue
        rdofs = [d for d in props.dofs if d.kind in ('TIP', 'TILT')]
        if not rdofs:
            continue                       # no steering DOFs -> mount-limit is not the diagnosis
        _pos, ang_err, nxt = alignment.compute_residual(scene, segs, obj)
        if nxt is None or ang_err <= 0.0:
            continue
        is_mirror = props.element_type in ('MIRROR', 'PRISM_MIRROR', 'DEFORMABLE_MIRROR')
        required = ang_err * (2.0 if is_mirror else 1.0)
        # available one-sided steering range = the widest single DOF half-range
        # (the solver can drive a DOF from its center out to either limit).
        avail = max((d.max_val - d.min_val) for d in rdofs)
        if required > avail + MOUNT_MARGIN_DEG and ang_err > o_props.warn_ang_deg:
            issues.append(_issue(
                "mount_limit", obj.name,
                "%s needs ~%.2f deg of steering (ang_err=%.2f%s) but DOF range is only "
                "%.2f deg -- reposition the post (coarse)"
                % (obj.name, required, ang_err,
                   ", x2 mirror" if is_mirror else "", avail),
                "BAD"))
    return issues


# ---------------------------------------------------------------------------
# B2 - relay / telescope spacing (afocal de-tuning)
# ---------------------------------------------------------------------------

# B2: how far the traced separation may sit from the ideal afocal d=f1+f2 and still
# be read as an *intended* (merely detuned) relay. A pair further out than this band
# is almost certainly NOT meant to be afocal (e.g. a lens that just focuses onto a
# detector), so flagging it would be a false positive. +-25% cleanly separates a
# detuned telescope (a few mm off, well inside the band) from an unrelated lens pair.
_RELAY_BAND = 0.25           # |d-(f1+f2)| <= band * (f1+f2)  -> plausibly an afocal relay
_RELAY_TOL_FRAC = 0.01       # within the band, flag when |d-(f1+f2)| > max(0.5 mm, 1% of f1+f2)
_RELAY_TOL_FLOOR = 0.5       # mm


def _relay_spacing(scene, segs):
    """B2: flag a two-lens pair that is *plausibly* an afocal relay/telescope (their
    separation sits within +-25% of f1+f2) but is DETUNED off the afocal condition
    d == f1+f2, so a collimated input no longer exits collimated.

    Find consecutive LENS elements in BEAM ORDER with no other powered element
    between them -- exactly the segment whose `from` and `to` are both lenses (the
    tracer emits one transmit segment directly between them, so 'no powered element
    between' is structural). Its `p1->p2` length is the on-axis separation d. With
    focals f1 (upstream) and f2 (downstream): if |d-(f1+f2)| is within the relay band
    but exceeds tol = max(0.5 mm, 1% of f1+f2), emit a WARN on the 2nd lens. Exactly
    afocal -> nothing. Uses only the lens focals + the traced separation; no trace is
    mutated. The collimation/afocal math is design.afocal_abcd (oracle-verified)."""
    issues = []
    by_name = {o.name: o for o in scene.objects
               if getattr(o, "optics", None) and o.optics.is_optical}
    for s in segs:
        a = by_name.get(s.get("from"))
        b = by_name.get(s.get("to"))
        if a is None or b is None:
            continue
        if a.optics.element_type != 'LENS' or b.optics.element_type != 'LENS':
            continue
        f1 = float(a.optics.focal_length)
        f2 = float(b.optics.focal_length)
        ideal = f1 + f2
        if abs(ideal) < 1e-6:                     # f1 == -f2 -> no afocal spacing exists; skip
            continue
        d = (Vector(s["p2"]) - Vector(s["p1"])).length
        err = d - ideal
        if abs(err) > _RELAY_BAND * abs(ideal):   # not plausibly an afocal relay -> not our call
            continue
        tol = max(_RELAY_TOL_FLOOR, _RELAY_TOL_FRAC * abs(ideal))
        if abs(err) > tol:
            issues.append(_issue(
                "relay_spacing", b.name,
                "afocal relay %s->%s detuned: d=%.3f mm, expected f1+f2=%.3f mm "
                "(f1=%.3f, f2=%.3f), off by %.3f mm -> collimation error"
                % (a.name, b.name, d, ideal, f1, f2, err),
                "WARN"))
    return issues


# ---------------------------------------------------------------------------
# A9 - back-reflection / ghost-beam detection
# ---------------------------------------------------------------------------

# A9: how anti-parallel a ghost must run to count as a back-reflection INTO a source -- the
# dangerous laser-feedback case. cos(angle) <= this (i.e. >~155 deg from forward) is "heading
# back the way it came". A ghost peeled off at ~normal incidence returns near-exactly anti-parallel
# (cos ~ -1); a ghost off a tilted face fans away and is harmless, so this cleanly separates them.
_BACKREFLECT_COS = -0.9          # ray.dir . forward <= -0.9  -> ~anti-parallel (within ~25 deg)
_GHOST_KINDS = ('GHOST',)        # the seed kind the tracer tags a parasitic Fresnel reflection with


def _ghost_lineage(segs):
    """Return the set of segment indices that ARE a ghost or DESCEND from one (a ghost that then
    transmits/reflects through more optics keeps its own kind on those legs, so we propagate the
    'ghost' taint down the parent tree). Empty when no ghosts were spawned (model_ghosts OFF)."""
    n = len(segs)
    is_ghost = [False] * n
    # a segment is a ghost seed if its own kind is GHOST
    for i, s in enumerate(segs):
        if s.get("kind") in _GHOST_KINDS:
            is_ghost[i] = True
    # propagate the taint to descendants: a child inherits ghost-ness from its parent. Segments are
    # emitted parent-before-child (the tracer appends the hit segment, then stacks its children, which
    # are traced later -> higher index), so a single forward pass settles the closure.
    for i, s in enumerate(segs):
        p = s.get("parent", -1)
        if 0 <= p < n and is_ghost[p]:
            is_ghost[i] = True
    return {i for i in range(n) if is_ghost[i]}


def _back_reflection_and_ghost_hits(scene, segs):
    """A9: two stray-light faults that only exist once ghosts are modeled.

      back_reflection  - a GHOST (or its descendant) runs ~anti-parallel back into a SOURCE: the
                         classic, damaging laser-feedback case (a window/lens reflecting ~4% straight
                         back into the laser cavity). A correctly-oriented ISOLATOR in the return path
                         EXTINGUISHES the ghost (the tracer's ISOLATOR branch absorbs a backward ray),
                         so this flag CLEARS -- the teachable signal.
      ghost_on_detector - a GHOST (or its descendant) lands on a detector/terminal: a spurious spot /
                         false reading the real beam never put there.

    Read-only: classifies the existing segments by ghost lineage + geometry; mutates nothing.
    """
    issues = []
    ghosts = _ghost_lineage(segs)
    if not ghosts:
        return issues                      # model_ghosts OFF (or no transmissive surface) -> nothing
    by_name = {o.name: o for o in scene.objects
               if getattr(o, "optics", None) and o.optics.is_optical}
    sources = {n for n, o in by_name.items()
               if o.optics.element_type in ('SOURCE', 'FIBER_COLLIMATOR') or o.optics.is_source}

    # back_reflection: a source is NOT a hittable surface (no IN port), so a ghost heading back into
    # the laser ESCAPES (to == None). It is a back-reflection when its line runs ~anti-parallel to a
    # source's emission axis AND passes back through that source's exit aperture -- i.e. the parasitic
    # Fresnel feedback returns into the laser. An ISOLATOR oriented to block the return ABSORBS the
    # backward ghost at the isolator (the tracer's ISOLATOR branch drops a backward ray), so the ghost
    # lineage terminates there (to == isolator, no escaping child) and NO anti-parallel escaping ghost
    # exists -> the flag CLEARS. Removing the isolator lets the ghost escape back -> the flag FIRES.
    flagged_src = set()
    for i in sorted(ghosts):
        s = segs[i]
        if s.get("to") is not None:                 # only an ESCAPING ghost can run back into a source
            continue
        p1 = Vector(s["p1"])
        d = Vector(s["p2"]) - p1
        if d.length < 1e-9:
            continue
        d = d.normalized()
        for sname in sources:
            if sname in flagged_src:
                continue
            src = by_name[sname]
            op = tracer._first_out(src.optics)
            if op is None:
                continue
            fwd = geometry.world_normal(src, op.local_normal)
            if d.dot(fwd) > _BACKREFLECT_COS:        # not running back the way the beam came -> harmless
                continue
            sp = geometry.world_port(src, op.local_position)
            ca = op.clear_aperture or src.optics.clear_aperture or 12.0
            # perpendicular distance from the source exit point to the ghost ray line; within the
            # exit aperture -> the ghost re-enters the laser.
            off = ((sp - p1) - (sp - p1).dot(d) * d).length
            if off <= max(ca, 0.0) + 1.0 and (sp - p1).dot(d) > 0.0:
                issues.append(_issue(
                    "back_reflection", sname,
                    "ghost back-reflection runs anti-parallel into source %s (parasitic Fresnel "
                    "feedback, miss=%.2f mm <= aperture %.2f mm) -- insert/orient an isolator to block it"
                    % (sname, off, ca),
                    "BAD"))
                flagged_src.add(sname)

    # ghost_on_detector: a ghost-lineage segment landing on a detector/terminal -> a spurious spot.
    terminals = {n for n, o in by_name.items() if o.optics.element_type in tracer.TERMINAL
                 and o.optics.element_type != 'BEAM_DUMP'}
    for i in sorted(ghosts):
        s = segs[i]
        to = s.get("to")
        if to in terminals:
            issues.append(_issue(
                "ghost_on_detector", to,
                "a ghost (parasitic reflection, power=%.4g) lands on detector %s -> a spurious spot / "
                "false reading not from the real beam" % (s.get("power", 0.0), to),
                "WARN"))
    return issues


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def run_diagnostics(scene):
    """Run the Wave-1 P0 error-detection gates (A1-A5) over the CURRENT trace and
    return a flat list of {kind, element, detail, severity} dicts (empty == clean).

    READ-ONLY: uses the cached trace if present, otherwise traces once; it never
    mutates the trace, the ray path, or any element pose. The beam trace is
    byte-identical before and after a call.
    """
    segs = tracer.cached_segments if tracer.cached_segments else alignment._trace(scene)
    out = []
    out += _beam_clipped(scene, segs)
    out += _vignetting(scene, segs)
    out += _dark_and_orphan(scene, segs)
    out += _energy_budget(scene, segs)
    out += _mount_limit(scene, segs)
    out += _relay_spacing(scene, segs)
    out += _back_reflection_and_ghost_hits(scene, segs)
    return out
