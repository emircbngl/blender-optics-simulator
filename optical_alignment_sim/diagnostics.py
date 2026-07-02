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
  A3b optic_bypassed   - a mid-path optic (lens/mirror/BS/waveplate/...) that NO beam
                         segment touches: it was moved/mis-placed off the beam so the
                         path bypasses it entirely (the "I knocked the lens off" case).
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

Wave-3 A10 adds a fringe-disambiguation check (a read-only post-pass, NO new physics):
  A10 pol_mismatch     - at a detector reached by >=2 beams of the SAME source
      coherence_mismatch (same src_id), the fringes are "dead" (low visibility). The sim
      crossed_polarizer  KNOWS why -- it has each beam's Jones vector, OPL and coherence:
                         . the two arms are orthogonally polarized (Jones overlap ~0)
                           -> pol_mismatch (fix: a HWP to rotate one arm);
                         . the arms are co-polarized but OPD > coherence length
                           (fringe_envelope < ~0.1) -> coherence_mismatch (fix: equalize
                           the arm lengths);
                         . a crossed polarizer/analyzer extinguished the light (measure()
                           at the Malus extinction floor) -> crossed_polarizer.
                         Pure REUSE: reads the already-traced jones/opl/coh and calls the
                         oracle-verified physics.interfere / fringe_envelope / Malus
                         (M_polarizer) / Jones-overlap + alignment.measure. No formula is
                         added. A well-aligned interferometer (high overlap AND envelope)
                         emits NOTHING.
"""
from __future__ import annotations

import math

from mathutils import Vector

from . import geometry, tracer, alignment, physics


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
# A3b - bypassed optic (a mid-path element the beam never reaches)
# ---------------------------------------------------------------------------

def _bypassed_optics(scene, segs):
    """A3b: a mid-path OPTIC (lens / mirror / beamsplitter / waveplate / prism / crystal / ...) that no beam
    segment touches -- it has been knocked OUT of the beam path (moved or mis-placed) so the trace bypasses it
    entirely. Distinct from A1 beam_clipped (a near-miss OVER the aperture, the beam still grazes the plane) and
    A3 dark_detector / orphan_source (a TERMINAL or a SOURCE with no light): this is an element the user PLACED to
    act on the beam that the beam never reaches. A hit optic always appears as a segment `to`/`from`; one that is
    bypassed appears in neither. WARN (an optic is occasionally parked off-axis on purpose)."""
    issues = []
    touched = set()
    for s in segs:
        if s.get("to") is not None:
            touched.add(s["to"])
        if s.get("from") is not None:
            touched.add(s["from"])
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if op is None or not op.is_optical:
            continue                                   # mounts / posts / non-optical meshes
        if op.element_type in tracer.TERMINAL or op.is_source or op.element_type in ('SOURCE', 'FIBER_COLLIMATOR'):
            continue                                   # terminals -> dark_detector; sources -> orphan_source (A3)
        if o.name in touched:
            continue                                   # the beam reaches it -> fine
        issues.append(_issue(
            "optic_bypassed", o.name,
            "%s (%s) is in the scene but NO beam reaches it -- the path bypasses it entirely (moved off the "
            "beam / mis-placed?)" % (o.name, op.element_type),
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
# A10 - fringe disambiguation (pol vs coherence vs crossed-polarizer)
# ---------------------------------------------------------------------------

# A10 thresholds (module-level so callers / tests can read them). NONE introduces a new
# formula -- they only set where a REUSED, oracle-verified quantity counts as "dead":
#   * the Jones overlap is the SAME normalized |<Ja|Jb>| physics.interfere uses for its
#     fringe contrast (0 = orthogonal arms, 1 = identical polarization);
#   * the envelope is physics.fringe_envelope(OPD, Lc) (the verified coherence decay);
#   * the extinction floor is the Malus leak of physics.M_polarizer (amp^2 = 1/extinction).
_A10_OVERLAP_DEAD = 0.1      # |<Ja|Jb>| <= this -> arms ~orthogonally polarized (pol_mismatch)
_A10_OVERLAP_LIVE = 0.5      # |<Ja|Jb>| >= this -> co-polarized enough that LOW envelope is the cause
_A10_ENVELOPE_DEAD = 0.1     # fringe_envelope(OPD, Lc) < this -> OPD washed the fringes (coherence_mismatch)
_A10_EXTINCT_FRAC = 0.02     # per-arm analyzed power / raw arriving power <= this -> Malus extinction


def _jones_of(seg):
    """Reconstruct a complex Jones (Ex, Ey) from a segment's stored 4-float jones, or None.
    Mirrors alignment.measure's (re,im,re,im) unpacking exactly -- no new convention."""
    j = seg.get("jones")
    if not j:
        return None
    return (complex(j[0], j[1]), complex(j[2], j[3]))


def _fringe_disambiguation(scene, segs):
    """A10: at every detector reached by >=2 beams of the SAME source, separate the
    physically-distinct causes of a DEAD (low-visibility) fringe.

    The two arms of an interferometer share a `src_id` (a beam keeps its source's id
    through every split), so grouping the incoming segments by src_id -- exactly the
    grouping alignment.measure() uses -- reconstitutes the interfering pair. For each
    same-source group of >=2 beams we read the per-beam Jones / OPL / coherence the
    tracer already stored and classify, REUSING only verified kernels:

      crossed_polarizer  - the detector's analyzer projects EACH arm individually to ~0:
                           the SUM of the per-arm analyzer-projected powers (the incoherent,
                           NON-interfered analyzed power) collapses to the Malus extinction
                           floor relative to the raw arriving power -- a crossed analyzer
                           killed the light arm-by-arm. Reported first (it masks the other
                           two: there is no fringe to disambiguate once the light is gone).
                           Distinguished from a healthy destructive-interference DARK PORT
                           (where each arm passes the analyzer at full power but the two
                           cancel by PHASE): the dark port has HIGH per-arm analyzed power
                           and is silently a healthy null, not a fault. Needs an analyzer to
                           cross -- with analyzer=='NONE' a low power is interference, never
                           a crossed polarizer.
      pol_mismatch       - the normalized Jones overlap |<Ja|Jb>| of the two strongest
                           arms is ~0 (orthogonally polarized): they cannot interfere.
                           This is the SAME overlap physics.interfere weights its cross
                           term by. Fix: a HWP to rotate one arm back parallel.
      coherence_mismatch - the arms ARE co-polarized (overlap high) but the OPD exceeds
                           the coherence length, so physics.fringe_envelope(OPD, Lc) < 0.1
                           washes the fringes out. Fix: equalize the arm lengths.

    A healthy interferometer (high overlap AND high envelope, light not extinguished)
    matches none of these -> emits nothing. READ-ONLY: mutates neither scene nor trace.
    """
    issues = []
    by_name = {o.name: o for o in scene.objects
               if getattr(o, "optics", None) and o.optics.is_optical}
    terminals = [o for o in by_name.values()
                 if o.optics.element_type in tracer.TERMINAL
                 and o.optics.element_type != 'BEAM_DUMP']

    for det in terminals:
        incoming = [s for s in segs if s.get("to") == det.name]
        if len(incoming) < 2:
            continue                                  # one (or no) beam -> no fringe to disambiguate
        # group by source: same-source beams share src_id (set at emission, inherited through
        # every split) -- the same grouping alignment.measure() coheres beams within.
        groups = {}
        for s in incoming:
            groups.setdefault(s.get("src_id", -1), []).append(s)
        for sid, group in groups.items():
            if len(group) < 2:
                continue                              # need >=2 SAME-source beams to interfere

            # the two strongest arms (by stored power) are the interfering pair, mirroring
            # how physics.interfere picks its two beams for the visibility/overlap.
            pair = sorted(group, key=lambda s: s.get("power", 0.0), reverse=True)[:2]
            Ja, Jb = _jones_of(pair[0]), _jones_of(pair[1])
            if Ja is None or Jb is None:
                continue                              # no polarization carried -> nothing to read

            # --- crossed_polarizer (Malus extinction): the analyzer kills each arm
            # INDIVIDUALLY. We must NOT use alignment.measure() here -- that returns the
            # INTERFERED power, which also goes to ~0 at a healthy destructive-interference
            # DARK PORT (the arms cancel by PHASE, not by polarization). Instead sum the
            # per-arm analyzer-projected powers INCOHERENTLY (no cross terms): a crossed
            # analyzer drives this Malus sum to the extinction floor regardless of phase,
            # while a dark fringe keeps it high (each arm passes -> it is a healthy null,
            # not a fault). With analyzer=='NONE' there is nothing to cross, so a low power
            # is interference darkness, never a crossed polarizer.
            analyzer = det.optics.analyzer
            raw_p = sum(physics.intensity(_jones_of(s) or (0j, 0j)) for s in incoming)
            M = physics.analyzer_matrix(analyzer)          # None for 'NONE'
            if M is not None and raw_p > DARK_FLOOR:
                # incoherent sum of every incoming arm's power AFTER the analyzer projection
                analyzed_p = sum(physics.intensity(physics.apply(M, _jones_of(s) or (0j, 0j)))
                                 for s in incoming)
                if 0.0 <= analyzed_p <= _A10_EXTINCT_FRAC * raw_p:
                    issues.append(_issue(
                        "crossed_polarizer", det.name,
                        "%s: a crossed polarizer/analyzer extinguished the beam (per-arm analyzed "
                        "power=%.3g <= %.0f%% of arriving %.3g, Malus floor -- each arm killed "
                        "individually, not an interference null) -- uncross the analyzer/polarizer"
                        % (det.name, analyzed_p, 100.0 * _A10_EXTINCT_FRAC, raw_p),
                        "WARN"))
                    continue                          # the light is gone -> no fringe to classify further

            # --- normalized Jones overlap of the two arms: the SAME |<Ja|Jb>|/sqrt(Ia*Ib)
            # that physics.interfere weights its cross term by (0 = orthogonal, 1 = identical).
            Ia, Ib = physics.intensity(Ja), physics.intensity(Jb)
            if Ia <= 1e-12 or Ib <= 1e-12:
                continue                              # one arm carries no power -> not a fringe fault
            overlap = abs(Ja[0] * Jb[0].conjugate() + Ja[1] * Jb[1].conjugate()) / math.sqrt(Ia * Ib)

            # --- coherence envelope of the pair: physics.fringe_envelope(OPD, Lc) (verified).
            opd = abs(pair[0].get("opl", 0.0) - pair[1].get("opl", 0.0))
            Lc = min(pair[0].get("coh", float('inf')), pair[1].get("coh", float('inf')))
            env = physics.fringe_envelope(opd, Lc)

            if overlap <= _A10_OVERLAP_DEAD:
                issues.append(_issue(
                    "pol_mismatch", det.name,
                    "%s: the two arms are ~orthogonally polarized (Jones overlap=%.3f <= %.2f) so "
                    "they cannot interfere -- fringes dead. fix: insert a HWP to rotate one arm "
                    "back parallel (OPD=%.4f mm, envelope=%.3f rule out coherence)"
                    % (det.name, overlap, _A10_OVERLAP_DEAD, opd, env),
                    "WARN"))
            elif overlap >= _A10_OVERLAP_LIVE and env < _A10_ENVELOPE_DEAD:
                issues.append(_issue(
                    "coherence_mismatch", det.name,
                    "%s: arms co-polarized (Jones overlap=%.3f) but OPD=%.4f mm exceeds the "
                    "coherence length Lc=%.4g mm (fringe_envelope=%.3f < %.2f) -- fringes washed "
                    "out. fix: equalize the arm lengths"
                    % (det.name, overlap, opd, Lc, env, _A10_ENVELOPE_DEAD),
                    "WARN"))
            # else: high overlap AND high envelope -> healthy fringes -> emit nothing.
    return issues


def _beam_underfills_figure(scene, segs):
    """A surface-figure imprint reads ONLY the patch the BEAM covers. If the incident Gaussian footprint
    underfills the figured (imprint_surface) element's actual SURFACE EXTENT, the zonal/modal sensor render
    samples just the central region -- the rest of the figure (the whole object) is never illuminated. WARN +
    recommend a beam expander / collimator (the physical way to grow the beam; raising the source waist is
    not). Read-only; uses the per-segment footprint w_mm (a RADIUS) and the element's mesh bounding extent.

    Both w_mm and clear_aperture are RADII in this codebase (G.mirror sets clear_aperture = size*0.5, and
    _vignetting plugs clear_aperture straight in as the truncation radius a). But clear_aperture is the
    element's CLIP aperture (must exceed the beam or it vignettes) -- NOT the figure size -- so the fill
    test compares the beam radius to the figure's actual transverse extent (~half the mesh bbox)."""
    by_elem = {}
    for s in segs:
        nm = s.get("to")
        if nm is None:
            continue
        E = scene.objects.get(nm)
        if E is None or getattr(E, "optics", None) is None:
            continue
        op = E.optics
        # the trace imprints a figure for a MIRROR / PRISM_MIRROR OR any coated element (coating pickoff),
        # whenever imprint_surface is on (see tracer._spawn_coating / the reflect branches).
        reflects = (op.element_type in ('MIRROR', 'PRISM_MIRROR')
                    or (getattr(op, 'coating_reflectance', 0.0) or 0.0) > 0.0)
        if not (getattr(op, 'imprint_surface', False) and reflects):
            continue
        w = s.get("w_mm", 0.0) or 0.0
        if w <= 1e-6:
            continue
        try:
            fig_r = 0.5 * max(E.dimensions)            # figure transverse extent ~ half the mesh bbox (radius)
        except Exception:
            fig_r = 0.0
        if fig_r <= 1e-6:
            continue
        prev = by_elem.get(nm)                          # worst case = the SMALLEST incident footprint
        if prev is None or w < prev[0]:
            by_elem[nm] = (w, fig_r, E.name)
    issues = []
    for nm, (w, fig_r, ename) in by_elem.items():
        fill = w / fig_r                               # beam RADIUS / figure RADIUS (like-for-like)
        if fill < 0.9:
            issues.append(_issue(
                "beam_underfills_figure", ename,
                "Beam underfills %s's figured surface: footprint radius %.1f mm vs figure radius %.1f mm "
                "(%.0f%%). The surface-figure (zonal/modal) sensor render samples only the central patch; the "
                "rest of the figure is never illuminated. Insert a beam EXPANDER / collimator upstream to grow "
                "the beam to the figure size (raising the source waist alone is not physical)."
                % (ename, w, fig_r, 100.0 * fill),
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
    out += _bypassed_optics(scene, segs)
    out += _energy_budget(scene, segs)
    out += _mount_limit(scene, segs)
    out += _relay_spacing(scene, segs)
    out += _back_reflection_and_ghost_hits(scene, segs)
    out += _fringe_disambiguation(scene, segs)
    out += _beam_underfills_figure(scene, segs)
    return out


# --------------------------------------------------------------------------- #
# Correction-as-FEEDBACK (Phase 1.3): the diagnostics above DETECT problems; this layer
# turns each into an ADVISORY proposal {suggested_fix, tool, maybe_intentional_if,
# fault_confidence} and stops -- it NEVER applies anything. The caller (the AI) weighs the
# proposal against USER INTENT and chooses refuse / partial / accept, exactly as the
# physics-honesty-gate is weighed: surface + judge, never silent auto-fix. The crucial field
# is `maybe_intentional_if` -- many "faults" are deliberate (a knife-edge IS meant to clip; a
# crossed analyzer IS an extinction measurement), so a blind auto-fixer would break the user's
# intent. `fault_confidence` (0..1) encodes how likely the issue is a genuine fault vs a design
# choice (crossed_polarizer low: usually intentional; energy_violation high: almost always a bug).
# --------------------------------------------------------------------------- #

_CORRECTION_SUGGESTIONS = {
    "beam_clipped": {
        "action": "Re-center the beam on the element (align_element / auto_align) or widen the element's clear aperture (set_param).",
        "tool": "align_element",
        "maybe_intentional_if": "the clipping element is a knife-edge, iris, slit, pinhole, or beam-dump -- clipping is its PURPOSE -- or the user is deliberately apodizing / spatial-filtering.",
        "confidence": 0.7},
    "vignetting": {
        "action": "Use a larger-aperture optic, or reduce the beam (a beam reducer / smaller waist) so the Gaussian wings clear the aperture.",
        "tool": "set_param",
        "maybe_intentional_if": "the truncation is a deliberate spatial filter / mode clean-up / soft-edge apodization.",
        "confidence": 0.55},
    "dark_detector": {
        "action": "Steer a beam onto the detector (auto_align), or check for an upstream block / crossed polarizer / closed shutter.",
        "tool": "auto_align",
        "maybe_intentional_if": "the detector is an unused reference port, a dark-port monitor, or the bench is mid-construction.",
        "confidence": 0.6},
    "orphan_source": {
        "action": "Aim the source at the first optic (align_element on the source, or place the first element on its axis).",
        "tool": "align_element",
        "maybe_intentional_if": "the source was just added and the downstream path is not built yet.",
        "confidence": 0.65},
    "optic_bypassed": {
        "action": "Move the optic back onto the beam axis (place_relative / place_on_grid to re-centre it on the path), or align the upstream element so the beam hits it.",
        "tool": "place_relative",
        "maybe_intentional_if": "the optic was deliberately parked off the beam (staged for later, a spare in the scene, or a swappable component not currently in use).",
        "confidence": 0.7},
    "energy_violation": {
        "action": "Check the offending element's energy params: a coating R+T+A must sum to 1, a beamsplitter split_ratio in [0,1], no passive element may create power.",
        "tool": "set_param",
        "maybe_intentional_if": "almost never -- energy non-conservation is a model/config error, not a design choice (no gain media are modeled).",
        "confidence": 0.9},
    "mount_limit": {
        "action": "Coarse-reposition the mount so the alignment DOF has travel (place_relative to recentre), then re-run the aligner.",
        "tool": "place_relative",
        "maybe_intentional_if": "rarely -- usually a real range-exhaustion needing a coarse pre-alignment before the fine solver.",
        "confidence": 0.8},
    "relay_spacing": {
        "action": "Recompute the 4f / telescope spacing (design_4f / design_telescope) and place the lenses at f1+f2.",
        "tool": "design_4f",
        "maybe_intentional_if": "the layout is deliberately non-4f / non-afocal (a finite-conjugate relay or an intentionally defocused setup).",
        "confidence": 0.55},
    "back_reflection": {
        "action": "Add a small tilt to walk the retro-reflection off the source axis (align_element), or insert an isolator.",
        "tool": "align_element",
        "maybe_intentional_if": "the element is a retroreflector / cat's-eye / a Michelson end mirror (retro-reflection is intended), or a cavity is being built.",
        "confidence": 0.6},
    "ghost_on_detector": {
        "action": "Tilt the offending window / uncoated surface a few degrees to walk the ghost off the detector, or add a pickoff / baffle.",
        "tool": "align_element",
        "maybe_intentional_if": "the ghost path IS the measurement (a deliberate Fresnel pickoff / reference reflection).",
        "confidence": 0.65},
    "coherence_mismatch": {
        "action": "Equalize the interferometer arm lengths (place_relative so OPD < Lc), or use a narrower-linewidth source.",
        "tool": "place_relative",
        "maybe_intentional_if": "the user is deliberately operating outside the coherence length (a white-light OPD scan, or measuring incoherent addition).",
        "confidence": 0.6},
    "crossed_polarizer": {
        "action": "Rotate the analyzer or the input polarizer off extinction (set_param the analyzer / fast_axis / polarization angle).",
        "tool": "set_param",
        "maybe_intentional_if": "VERY OFTEN intentional -- crossed polarizers ARE an extinction / dark-field / polarization-contrast measurement. REFUSE unless the user clearly wanted light through.",
        "confidence": 0.3},
    "pol_mismatch": {
        "action": "Insert a HWP (or rotate one arm's polarization) so the two arms are co-polarized and can interfere.",
        "tool": "add_component",
        "maybe_intentional_if": "the orthogonal polarization is deliberate (a polarization interferometer, a which-path eraser, an entanglement setup).",
        "confidence": 0.5},
    "beam_underfills_figure": {
        "action": "Add a beam expander (design a Galilean / Keplerian expander) so the footprint fills the figure under test.",
        "tool": "design_telescope",
        "maybe_intentional_if": "the user is deliberately probing a sub-aperture / a small patch of the figure.",
        "confidence": 0.55},
}


def propose_corrections(scene):
    """ADVISORY correction proposals over the CURRENT trace. Runs the same READ-ONLY diagnostic gates
    as run_diagnostics, then attaches to each issue a SUGGESTED fix + the tool that would apply it + a
    ``maybe_intentional_if`` hint + a ``fault_confidence`` (0..1: how likely a genuine fault vs a
    deliberate design choice). NOTHING is applied -- the caller (the AI) must weigh USER INTENT and
    choose refuse / partial / accept, mirroring the physics-honesty-gate (surface + judge, never silent
    auto-fix). Byte-identical trace. Returns a list of proposal dicts (empty == clean bench)."""
    proposals = []
    for d in run_diagnostics(scene):
        s = _CORRECTION_SUGGESTIONS.get(d["kind"], {})
        proposals.append({
            "issue": d["kind"],
            "element": d.get("element"),
            "detail": d.get("detail"),
            "severity": d.get("severity"),
            "suggested_fix": s.get("action", "no automated suggestion -- inspect this issue manually"),
            "tool": s.get("tool"),
            "maybe_intentional_if": s.get("maybe_intentional_if", "(unknown -- judge from context)"),
            "fault_confidence": s.get("confidence", 0.5),
            "advisory": True,                       # NEVER auto-applied; the AI decides refuse/partial/accept
        })
    return proposals


# --------------------------------------------------------------------------- #
# Automatic optical PHENOMENA (Phase 3.3): the diagnostics above flag PROBLEMS; this flags
# recognized optical PHENOMENA whose geometric/coherence conditions the current trace MEETS --
# two-beam interference, off-axis hologram recording, Fabry-Perot resonance. ADVISORY + READ-ONLY:
# the sim does NOT auto-produce them, it tells the AI/user that the conditions are satisfied (e.g.
# "a reference + object beam cross at 8 deg on the camera -> this records an off-axis hologram, carrier
# fringe spacing Lambda"). Same surface-don't-act stance as diagnose(). The one new physical relation is
# the two-beam fringe spacing Lambda = lambda/(2 sin(theta/2)) (physics_verify ok=true: DIMENSIONAL +
# Lambda(632.8nm, 10deg)=3.63028um + small-angle Lambda->lambda/theta); visibility/overlap/envelope reuse
# verified kernels (physics.intensity / fringe_envelope), exactly as _fringe_disambiguation does.
# --------------------------------------------------------------------------- #

def _seg_dir(seg):
    """Unit incident direction of a segment (p2 - p1 normalized), or None if degenerate."""
    p1, p2 = seg.get("p1"), seg.get("p2")
    if p1 is None or p2 is None:
        return None
    d = [p2[i] - p1[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    return [c / n for c in d] if n > 1e-9 else None


def detect_phenomena(scene):
    """Advisory: the recognized optical PHENOMENA whose conditions the CURRENT trace MEETS. READ-ONLY
    (byte-identical) -- it FLAGS that the geometry/coherence conditions are satisfied, it does not produce
    anything (the same surface-don't-act stance as diagnose / propose_corrections). Returns a list of
    {phenomenon, where, detail, fringe_spacing_mm, crossing_angle_deg, visibility, confidence}.

    Phenomena (first set): two beams of the SAME source (mutually coherent, src_id-grouped like
    _fringe_disambiguation) that reach one detector, co-polarized (Jones overlap high) and within the
    coherence length (fringe_envelope high), INTERFERE -- collinear (crossing angle ~0) gives ordinary
    two-beam fringes; a small NON-zero crossing angle is the OFF-AXIS HOLOGRAM geometry, with carrier
    fringe spacing Lambda = lambda/(2 sin(theta/2))."""
    segs = tracer.cached_segments if tracer.cached_segments else alignment._trace(scene)
    out = []
    by_name = {o.name: o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical}
    terminals = [o for o in by_name.values()
                 if o.optics.element_type in tracer.TERMINAL and o.optics.element_type != 'BEAM_DUMP']
    for det in terminals:
        incoming = [s for s in segs if s.get("to") == det.name]
        if len(incoming) < 2:
            continue
        groups = {}
        for s in incoming:
            groups.setdefault(s.get("src_id", -1), []).append(s)
        for _sid, group in groups.items():
            if len(group) < 2:
                continue
            pair = sorted(group, key=lambda s: s.get("power", 0.0), reverse=True)[:2]
            Ja, Jb = _jones_of(pair[0]), _jones_of(pair[1])
            if Ja is None or Jb is None:
                continue
            Ia, Ib = physics.intensity(Ja), physics.intensity(Jb)
            if Ia <= 1e-12 or Ib <= 1e-12:
                continue
            overlap = abs(Ja[0] * Jb[0].conjugate() + Ja[1] * Jb[1].conjugate()) / math.sqrt(Ia * Ib)
            opd = abs(pair[0].get("opl", 0.0) - pair[1].get("opl", 0.0))
            Lc = min(pair[0].get("coh", float('inf')), pair[1].get("coh", float('inf')))
            env = physics.fringe_envelope(opd, Lc)
            if overlap < 0.3 or env < 0.1:
                continue                                   # orthogonal pol / out-of-coherence -> no fringes
            vis = (2.0 * math.sqrt(Ia * Ib) / (Ia + Ib)) * overlap * env   # two-beam fringe visibility
            d1, d2 = _seg_dir(pair[0]), _seg_dir(pair[1])
            theta = 0.0
            if d1 and d2:
                dot = max(-1.0, min(1.0, sum(d1[i] * d2[i] for i in range(3))))
                theta = math.acos(dot)                     # crossing angle between the two arms (radians)
            wl = pair[0].get("wavelength", 632.8) or 632.8
            if theta < math.radians(0.5):                  # collinear -> ordinary two-beam interference
                out.append({"phenomenon": "two_beam_interference", "where": det.name,
                            "detail": "two mutually-coherent co-polarized beams overlap collinearly at %s -> "
                                      "interference fringes (visibility %.2f, OPD %.4f mm)" % (det.name, vis, opd),
                            "crossing_angle_deg": round(math.degrees(theta), 3),
                            "visibility": round(vis, 3), "confidence": round(min(1.0, vis + 0.1), 2)})
            else:                                          # angled -> off-axis hologram carrier fringes
                Lam = (wl * 1.0e-6) / (2.0 * math.sin(theta / 2.0))    # fringe spacing (mm)
                out.append({"phenomenon": "off_axis_hologram", "where": det.name,
                            "detail": "a reference + object beam cross at %.2f deg on %s -> OFF-AXIS HOLOGRAM "
                                      "geometry; carrier fringe spacing Lambda = lambda/(2 sin(theta/2)) = "
                                      "%.4f mm (visibility %.2f) -- a camera records it when its pixel pitch < "
                                      "Lambda/2" % (math.degrees(theta), det.name, Lam, vis),
                            "crossing_angle_deg": round(math.degrees(theta), 3),
                            "fringe_spacing_mm": round(Lam, 6),    # sub-um at large angles -> nm resolution
                            "visibility": round(vis, 3), "confidence": round(min(1.0, vis + 0.1), 2)})
    # element-conditioned phenomena: a CAVITY is an Airy resonator; a GRATING self-images (Talbot).
    def _wl_at(el_name):
        for s in segs:
            if (s.get("to") == el_name or s.get("from") == el_name) and s.get("wavelength"):
                return s["wavelength"]
        return 632.8
    for el in by_name.values():
        et = el.optics.element_type
        if et == 'CAVITY':
            L, R = float(el.optics.cavity_spacing_mm), float(el.optics.reflectivity)
            wl = _wl_at(el.name)
            out.append({"phenomenon": "fabry_perot_resonance", "where": el.name,
                        "detail": "a Fabry-Perot cavity (L=%.4f mm, R=%.3f) -> Airy transmission resonance; "
                                  "finesse F = pi sqrt(R)/(1-R) = %.2f, FSR = lambda^2/(2 n L)"
                                  % (L, R, physics.cavity_finesse(R)),
                        "cavity_spacing_mm": round(L, 6), "reflectivity": round(R, 4),
                        "wavelength_nm": wl, "confidence": round(min(1.0, R + 0.05), 2)})
        elif et == 'GRATING' and getattr(el.optics, 'lines_per_mm', 0.0) > 0.0:
            d = 1.0 / float(el.optics.lines_per_mm)            # grating period (mm)
            wl = _wl_at(el.name)
            z_t = 2.0 * d ** 2 / (wl * 1.0e-6)
            out.append({"phenomenon": "talbot_self_imaging", "where": el.name,
                        "detail": "a periodic grating (%.0f lines/mm, d=%.5f mm) reproduces its near-field as a "
                                  "self-image at the Talbot distance z_T = 2 d^2/lambda = %.3f mm (and a "
                                  "half-period-shifted copy at z_T/2)" % (el.optics.lines_per_mm, d, z_t),
                        "period_mm": round(d, 6), "talbot_distance_mm": round(z_t, 4),
                        "wavelength_nm": wl, "confidence": 0.9})
    return out


# --------------------------------------------------------------------------- #
# Phenomenon EMERGENCE (Phase 3.3, second half): detect_phenomena() FLAGS that a phenomenon's conditions
# are met; produce_phenomenon() actually PRODUCES it (synthesizes the interferogram / records + reconstructs
# the hologram), reusing the off-trace field/physics kernels. ADVISORY + intent-judged, exactly like
# propose_corrections: the default is a DRY-RUN that says what it WOULD produce + an intent caveat; the AI
# weighs the user's intent and only then re-calls with accept=True. READ-ONLY: never mutates scene/trace.
# --------------------------------------------------------------------------- #

def _coherent_pair_at(scene, det_name):
    """Re-derive the dominant mutually-coherent co-polarized beam pair reaching ``det_name`` + its geometry
    (a focused subset of detect_phenomena's pairing) so produce_phenomenon can emerge it. Returns
    {Ia, Ib, theta_rad, vis, opd_mm, wl_nm} for the highest-power coherent pair, or None."""
    segs = tracer.cached_segments if tracer.cached_segments else alignment._trace(scene)
    incoming = [s for s in segs if s.get("to") == det_name]
    if len(incoming) < 2:
        return None
    groups = {}
    for s in incoming:
        groups.setdefault(s.get("src_id", -1), []).append(s)
    for _sid, group in groups.items():
        if len(group) < 2:
            continue
        pair = sorted(group, key=lambda s: s.get("power", 0.0), reverse=True)[:2]
        Ja, Jb = _jones_of(pair[0]), _jones_of(pair[1])
        if Ja is None or Jb is None:
            continue
        Ia, Ib = physics.intensity(Ja), physics.intensity(Jb)
        if Ia <= 1e-12 or Ib <= 1e-12:
            continue
        overlap = abs(Ja[0] * Jb[0].conjugate() + Ja[1] * Jb[1].conjugate()) / math.sqrt(Ia * Ib)
        opd = abs(pair[0].get("opl", 0.0) - pair[1].get("opl", 0.0))
        Lc = min(pair[0].get("coh", float('inf')), pair[1].get("coh", float('inf')))
        env = physics.fringe_envelope(opd, Lc)
        if overlap < 0.3 or env < 0.1:
            continue
        vis = (2.0 * math.sqrt(Ia * Ib) / (Ia + Ib)) * overlap * env
        d1, d2 = _seg_dir(pair[0]), _seg_dir(pair[1])
        theta = 0.0
        if d1 and d2:
            dot = max(-1.0, min(1.0, sum(d1[i] * d2[i] for i in range(3))))
            theta = math.acos(dot)
        return {"Ia": Ia, "Ib": Ib, "theta_rad": theta, "vis": vis, "opd_mm": opd,
                "wl_nm": pair[0].get("wavelength", 632.8) or 632.8}
    return None


def _peak_freq(mag, freqs):
    """Dominant non-DC frequency of a real spectrum, with parabolic peak interpolation for sub-bin accuracy."""
    import numpy as np
    i = int(np.argmax(mag[1:])) + 1
    if 0 < i < len(mag) - 1:
        a, b, c = mag[i - 1], mag[i], mag[i + 1]
        denom = a - 2.0 * b + c
        off = 0.5 * (a - c) / denom if denom != 0 else 0.0
    else:
        off = 0.0
    df = freqs[1] - freqs[0]
    return freqs[i] + off * df


def _emerge_hologram(theta_rad, vis, wl_nm, nx=1024):
    """Produce the off-axis HOLOGRAM: record the carrier interferogram I(x)=1+vis*cos(2*pi*x/Lambda) of a
    reference + object beam crossing at ``theta_rad``, measure the carrier spacing off the FFT, and RECONSTRUCT
    the object by recovering its crossing angle from the carrier frequency. Returns (metrics, raster_for_png)."""
    import numpy as np
    wl_mm = wl_nm * 1.0e-6                                      # nm -> mm
    alpha = max(1e-9, theta_rad / 2.0)
    Lam = wl_mm / (2.0 * math.sin(alpha))                       # carrier fringe spacing (mm), Goodman Ch.9
    dx = Lam / 10.0
    x = (np.arange(nx) - nx // 2) * dx
    H = 1.0 + vis * np.cos(2.0 * np.pi * x / Lam)               # recorded hologram intensity (normalized)
    fpk = _peak_freq(np.abs(np.fft.rfft(H - H.mean())), np.fft.rfftfreq(nx, d=dx))
    Lam_fft = 1.0 / fpk if fpk > 0 else float('inf')
    theta_rec = 2.0 * math.asin(min(1.0, fpk * wl_mm / 2.0))    # reconstruction: object angle from the carrier
    metrics = {
        "carrier_spacing_mm": round(Lam, 6),
        "carrier_spacing_fft_mm": round(Lam_fft, 6),
        "nyquist_pixel_pitch_mm": round(Lam / 2.0, 6),          # a camera records it when pixel pitch < Lambda/2
        "visibility": round(vis, 4),
        "recovered_crossing_angle_deg": round(math.degrees(theta_rec), 4),
        "oracle": {"quantity": "carrier spacing Lambda = lambda/(2 sin(theta/2))",
                   "computed_mm": round(Lam, 6), "fft_measured_mm": round(Lam_fft, 6),
                   "source": "Goodman, Introduction to Fourier Optics Ch.9; physics_verify ok=true"},
    }
    carrier = 1.0 + vis * np.cos(2.0 * np.pi * np.outer(np.ones(min(nx, 96)), x) / Lam)   # 2D for the PNG
    return metrics, carrier


def _emerge_two_beam(vis, wl_nm, nx=512):
    """Produce the two-beam INTERFEROGRAM: I(phi) = 1 + vis*cos(phi) over two fringe periods as the path
    difference scans (the classic Michelson/two-beam fringe). Returns (metrics, (phi, I) for the PNG)."""
    import numpy as np
    phi = np.linspace(-2.0 * np.pi, 2.0 * np.pi, nx)
    I = 1.0 + vis * np.cos(phi)
    imax, imin = float(I.max()), float(I.min())
    vis_meas = (imax - imin) / (imax + imin) if (imax + imin) > 0 else 0.0
    metrics = {
        "visibility": round(vis, 4),
        "visibility_measured": round(vis_meas, 4),
        "i_max": round(imax, 4), "i_min": round(imin, 4),
        "fringe_period": "one lambda of optical path difference",
        "oracle": {"quantity": "fringe visibility V = (Imax-Imin)/(Imax+Imin)",
                   "computed": round(vis, 4), "measured": round(vis_meas, 4),
                   "source": "Hecht, Optics Ch.9; physics_verify ok=true"},
    }
    return metrics, (phi, I)


def _emerge_fabry_perot(L_mm, R, wl_nm, nx=512):
    """Produce the FABRY-PEROT Airy transmission resonance T(lambda) across +/- one free spectral range from
    the cavity spacing L and mirror reflectivity R (the conditions a CAVITY element already sets). Reuses the
    verified physics.airy_transmission / cavity_finesse / cavity_fsr_nm. Returns (metrics, (wls, T))."""
    import numpy as np
    R = max(0.0, min(R, 0.999999))
    finesse = physics.cavity_finesse(R)
    fsr = physics.cavity_fsr_nm(wl_nm, L_mm, 1.0)
    T_min = ((1.0 - R) / (1.0 + R)) ** 2
    contrast = ((1.0 + R) / (1.0 - R)) ** 2
    wls = wl_nm + np.linspace(-fsr, fsr, nx)                    # one FSR either side of the line
    T = np.array([physics.airy_transmission(float(w), L_mm, R) for w in wls])
    metrics = {
        "finesse": round(finesse, 4), "fsr_nm": round(fsr, 6),
        "T_min": round(T_min, 6), "contrast": round(contrast, 2),
        "T_max_measured": round(float(T.max()), 4), "T_min_measured": round(float(T.min()), 6),
        "oracle": {"quantity": "finesse = pi sqrt(R)/(1-R); T_min = ((1-R)/(1+R))^2; contrast = ((1+R)/(1-R))^2",
                   "finesse": round(finesse, 4), "T_min": round(T_min, 6), "contrast": round(contrast, 2),
                   "source": "Saleh & Teich, Fundamentals of Photonics Ch.10; physics_verify ok=true"},
    }
    return metrics, (wls, T)


def _emerge_talbot(period_mm, wl_nm, nx=256):
    """Produce the TALBOT self-imaging: the grating's periodic near field reproduces itself at z_T = 2 d^2/lambda
    (a half-period-shifted copy at z_T/2, no image at z_T/4). Reuses field.talbot_metrics, the full producer.
    Returns (metrics, None) -- talbot_metrics owns the carpet render."""
    from . import field as _field
    tm = _field.talbot_metrics(period_mm, wl_nm, n_grid=min(int(nx), 512))
    metrics = {
        "talbot_distance_mm": round(tm["talbot_distance_mm"], 4),
        "self_image_corr": round(tm["self_image_corr"], 4),
        "half_talbot_shift_corr": round(tm["half_talbot_shift_corr"], 4),
        "quarter_corr": round(tm["quarter_corr"], 4),
        "oracle": {"quantity": "Talbot distance z_T = 2 d^2/lambda; self-image correlation ~ 1 at z_T",
                   "z_T_mm": round(2.0 * period_mm ** 2 / (wl_nm * 1.0e-6), 4),
                   "self_image_corr": round(tm["self_image_corr"], 4),
                   "source": "Goodman, Introduction to Fourier Optics Ch.4; physics_verify ok=true"},
    }
    return metrics, None


def newton_rings_2d(R_mm, wl_nm=589.3, n_rings=8, field_mm=None, nx=256):
    """Produce the 2-D NEWTON'S-RINGS reflected-intensity pattern of a plano-convex surface (radius of curvature
    R_mm) resting on a flat. The air gap grows quadratically, t(r) = r^2/(2R), so the two reflections (off the
    curved face and the flat) interfere as  I(r) = sin^2(pi r^2 / (lambda R))  -- a central DARK spot (the
    half-wave reflection phase) and dark rings wherever 2t = m*lambda, i.e. at r_m = sqrt(m lambda R) (exactly
    physics.newton_ring_radius, oracle-verified). Off-trace, pure analysis. Returns (metrics, intensity_2d)."""
    import numpy as np
    lam_mm = wl_nm * 1.0e-6
    if field_mm is None:
        field_mm = 2.2 * physics.newton_ring_radius(n_rings, wl_nm, R_mm)        # ~ out to the n_rings-th ring
    ax = np.linspace(-0.5 * field_mm, 0.5 * field_mm, int(nx))
    X, Y = np.meshgrid(ax, ax)
    r2 = X * X + Y * Y
    inten = np.sin(np.pi * r2 / (lam_mm * R_mm)) ** 2
    radii = [physics.newton_ring_radius(m, wl_nm, R_mm) for m in range(int(n_rings) + 1)]
    metrics = {
        "radius_of_curvature_mm": R_mm, "wavelength_nm": wl_nm, "n_rings": int(n_rings),
        "field_mm": round(field_mm, 5), "dark_ring_radii_mm": [round(r, 5) for r in radii],
        "central_intensity": round(float(inten[int(nx) // 2, int(nx) // 2]), 6),   # ~0: the central dark spot
        "oracle": {"quantity": "dark-ring radius r_m = sqrt(m lambda R); I(r) = sin^2(pi r^2/(lambda R))",
                   "r1_mm": round(physics.newton_ring_radius(1, wl_nm, R_mm), 5),
                   "source": "Hecht, Optics Ch.9; physics_verify ok=true (newton-ring-radius)"},
    }
    return metrics, inten


def _render_emergence(kind, raster, meta, png_path):
    """Optional lazy-matplotlib PNG of an emerged phenomenon (mirrors field._render_field: import inside,
    swallow any failure -- the numbers are the product, the PNG is a convenience). Returns path or None."""
    if not png_path or raster is None:
        return None
    try:
        try:
            from . import plotting as _plotting
        except ImportError:
            import plotting as _plotting
        plt = _plotting.pyplot()
        if plt is None:
            raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
        fig, ax = plt.subplots(figsize=(5.4, 3.4))
        fig.patch.set_facecolor("#0d0d10"); ax.set_facecolor("#0d0d10")
        if kind == "hologram":
            ax.imshow(raster, cmap="gray", aspect="auto", origin="lower")
            ax.set_title("off-axis hologram: carrier interferogram", color="#f4f4f6", fontsize=11)
            ax.set_xlabel("x (carrier fringes)", color="#e8e8ea"); ax.set_yticks([])
        elif kind == "fabry_perot":
            wls, T = raster
            ax.plot(wls, T, color="#4a8db0", lw=1.3)
            ax.set_title("Fabry-Perot: Airy transmission T(lambda)", color="#f4f4f6", fontsize=11)
            ax.set_xlabel("wavelength (nm)", color="#e8e8ea"); ax.set_ylabel("T", color="#e8e8ea")
        else:
            phi, I = raster
            ax.plot(phi, I, color="#4a8db0", lw=1.5)
            ax.set_title("two-beam interference: I(OPD)", color="#f4f4f6", fontsize=11)
            ax.set_xlabel("phase (rad, = 2*pi*OPD/lambda)", color="#e8e8ea"); ax.set_ylabel("I (norm)", color="#e8e8ea")
        ax.tick_params(colors="#8a8a92", labelsize=8)
        for s in ax.spines.values():
            s.set_color("#33343a")
        fig.text(0.5, 0.01, meta, color="#8a8a92", fontsize=7.5, ha="center")
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        return png_path
    except Exception:
        return None


def produce_phenomenon(scene, phenomenon=None, where=None, nx=1024, png_path=None, accept=False):
    """ADVISORY emergence: PRODUCE a detected optical phenomenon (the interferogram / recorded + reconstructed
    hologram), off-trace + byte-identical. Two-stage like propose_corrections -- accept=False (default) is a
    DRY-RUN returning what it WOULD produce + an intent caveat (produces nothing); accept=True runs the
    emergence. The AI weighs the user's intent between the two calls (refuse / partial / accept)."""
    detected = detect_phenomena(scene)
    cands = [p for p in detected
             if (phenomenon is None or p["phenomenon"] == phenomenon) and (where is None or p["where"] == where)]
    if not cands:
        return {"ok": False, "error": "no detected phenomenon matches phenomenon=%r where=%r" % (phenomenon, where),
                "available": [{"phenomenon": p["phenomenon"], "where": p["where"]} for p in detected]}
    target = cands[0]
    name, det = target["phenomenon"], target["where"]
    if not accept:
        caveat = {"two_beam_interference": "the detector may be a power meter, not a fringe camera",
                  "off_axis_hologram": "the camera at the crossing may be a power meter, not a hologram plate",
                  "fabry_perot_resonance": "the cavity may be set for a single line, not a swept resonance scan",
                  "talbot_self_imaging": "the grating may be used in far-field diffraction, not near-field Talbot imaging",
                  }.get(name, "confirm this element is meant to produce the phenomenon")
        would = {"off_axis_hologram": "the 2D carrier interferogram + carrier spacing + reconstructed object angle",
                 "two_beam_interference": "the two-beam fringe curve I(OPD) + visibility",
                 "fabry_perot_resonance": "the Airy transmission curve T(lambda) + finesse / FSR / contrast",
                 "talbot_self_imaging": "the Talbot self-image correlation at z_T (and z_T/2, z_T/4)",
                 }.get(name, "the phenomenon's pattern + metrics")
        return {"ok": True, "would_produce": True, "phenomenon": name, "where": det,
                "what_it_would_compute": would, "maybe_not_wanted_if": caveat,
                "confidence": target.get("confidence", 0.0),
                "hint": "judge the user's intent, then re-call produce_phenomenon(accept=True) to emerge it "
                        "(refuse / partial / accept, exactly like propose_corrections)"}
    if name == "fabry_perot_resonance":
        metrics, raster = _emerge_fabry_perot(target["cavity_spacing_mm"], target["reflectivity"],
                                              target["wavelength_nm"], nx=min(int(nx), 512))
        png = _render_emergence("fabry_perot", raster, "finesse=%.1f, FSR=%.4f nm, contrast=%.0f"
                                % (metrics["finesse"], metrics["fsr_nm"], metrics["contrast"]), png_path)
    elif name == "talbot_self_imaging":
        metrics, raster = _emerge_talbot(target["period_mm"], target["wavelength_nm"], nx=min(int(nx), 512))
        png = None                                             # talbot_metrics owns the carpet; no extra render
    else:
        geo = _coherent_pair_at(scene, det)
        if geo is None:
            return {"ok": False, "error": "the coherent pair at %s is no longer resolvable" % det}
        if name == "off_axis_hologram":
            metrics, raster = _emerge_hologram(geo["theta_rad"], geo["vis"], geo["wl_nm"], nx=nx)
            png = _render_emergence("hologram", raster, "Lambda=%.4f um, recovered theta=%.3f deg"
                                    % (metrics["carrier_spacing_mm"] * 1000.0, metrics["recovered_crossing_angle_deg"]), png_path)
        else:
            metrics, raster = _emerge_two_beam(geo["vis"], geo["wl_nm"], nx=min(nx, 512))
            png = _render_emergence("two_beam", raster, "visibility=%.3f" % metrics["visibility"], png_path)
    out = {"ok": True, "phenomenon": name, "where": det, "produced": metrics}
    if png:
        out["png"] = png
    elif png_path:
        out["png_error"] = "matplotlib unavailable (numbers are unaffected)"
    return out
