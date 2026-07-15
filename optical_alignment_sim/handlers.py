"""Live-simulation plumbing: a depsgraph handler that recomputes the beam path
when the scene changes, with a recursion guard, a debounce timer, and a
transform signature so the addon's own property writes don't cause an infinite
recompute loop.
"""
from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from . import tracer

_recomputing = False
_dirty = False
_last_sig = None
_pending_scene = None       # the scene whose depsgraph update armed the deferred trace

# Physics-affecting INPUT properties the tracer/physics read. They MUST be in the live
# signature so editing e.g. a wavelength or reflectivity re-traces -- without this the live
# overlay/readouts only updated on a transform/knob move. Deliberately EXCLUDES computed
# OUTPUTS (meas_*, wf_rms, misalign_*, align_state/detail, mech_state): hashing those would
# make every trace change the signature and spin an infinite recompute loop.
_SIG_PROPS = (
    "element_type", "is_pbs", "is_source", "is_detector",
    "wavelength", "split_ratio", "reflectivity", "clear_aperture", "focal_length",
    "refractive_index", "pol_type", "pol_angle", "handedness", "linewidth_nm",
    "bandwidth_nm", "waist_um", "retardance_deg", "fast_axis_deg", "pol_axis_deg",
    "extinction", "design_wl", "pass_type", "cut_nm", "filt_type", "cut_lo_nm",
    "cut_hi_nm", "od", "lines_per_mm", "grating_order", "coating", "cavity_spacing_mm",
    "analyzer",
)


def _signature(scene):
    """Cheap hash of optical objects' world transforms + knob values + physics input params.
    Used to skip recompute only when nothing the tracer reads changed."""
    vals = []
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if op and op.is_optical:
            m = o.matrix_world
            vals += [round(m[r][c], 4) for r in range(3) for c in range(4)]   # full rotation + position
            vals += [round(d.current, 4) for d in op.dofs]
            for name in _SIG_PROPS:
                v = getattr(op, name, None)
                vals.append(round(v, 6) if isinstance(v, float) else v)
            vals += [round(x, 6) for x in op.aberr_spec]      # Zernike inject (FloatVectorProperty)
            vals += [round(x, 6) for x in op.dm_command]      # DM correction command
    return hash(tuple(vals))


def _anchor_depth(o):
    """Length of the anchor chain above o, so sorting ascending composes leaders before
    followers (A anchored to B anchored to C resolves in a single pass)."""
    d, cur, seen = 0, o, set()
    while True:
        op = getattr(cur, "optics", None)
        a = getattr(op, "anchor", None) if op else None
        if a is None or a in seen:
            return d
        seen.add(cur)
        cur, d = a, d + 1


def _deferred_trace():
    global _recomputing, _dirty, _last_sig
    _dirty = False
    scene = _pending_scene or bpy.context.scene        # the scene that actually changed, not just the active one
    if scene is None or not getattr(scene, "optics", None):
        return None
    if not scene.optics.live_enabled:                  # live mode was toggled off after this was armed
        return None
    _recomputing = True
    try:
        # Propagate relative placement first: a moved anchor / leader updates its
        # followers BEFORE we snapshot the signature, so the change is detected. Compose
        # in leader-before-follower order so anchor chains (A->B->C) resolve in one pass,
        # and skip entirely when nothing is anchored (keeps the cheap no-op path).
        try:
            from . import mounts
            anchored = [o for o in scene.objects
                        if getattr(o, "optics", None) and o.optics.is_optical
                        and getattr(o.optics, "anchor", None) is not None]
            if anchored:
                anchored.sort(key=_anchor_depth)
                for o in anchored:
                    mounts.compose_pose(o)
        except Exception:
            pass
        sig = _signature(scene)
        if sig == _last_sig:
            return None                 # nothing the tracer reads changed -> no work
        try:
            segs = tracer.trace_scene(
                scene, mode=scene.optics.trace_mode,
                max_segments=scene.optics.max_segments,
                max_depth=scene.optics.max_depth)
        except Exception as e:          # a transient/degenerate trace must not kill the live timer
            print("[optics] live trace error:", e)     # leave _last_sig unchanged -> retried on next edit
            return None
        tracer.cached_segments = segs
        _last_sig = sig                 # commit the signature only AFTER a successful trace
        try:
            from . import alignment
            alignment.refresh_report(scene)
        except Exception:
            pass
        try:
            from . import mounts
            mounts.check_mechanics(scene)
        except Exception:
            pass
        try:
            from . import scan
            scan.live_fringe_update(scene)      # refresh live sensor monitors
        except Exception:
            pass
        tracer._tag_redraw()
    finally:
        _recomputing = False
    return None                          # one-shot timer


@persistent
def on_depsgraph_update(scene, depsgraph=None):
    global _dirty, _pending_scene
    if _recomputing:                     # guard: our own writes must not re-trigger
        return
    if not getattr(scene, "optics", None) or not scene.optics.live_enabled:
        return
    _dirty = True
    _pending_scene = scene               # recompute THIS scene, not whatever is active when the timer fires
    if not bpy.app.timers.is_registered(_deferred_trace):
        bpy.app.timers.register(_deferred_trace, first_interval=0.03)   # debounce


@persistent
def on_diagnosis_revision_update(scene, depsgraph=None):
    """Invalidate cached UI diagnostics without inspecting the dependency graph."""
    for wm in bpy.data.window_managers:
        wm.optics_scene_revision += 1


def set_live(enabled):
    """Arm / disarm the live overlay + recompute handler."""
    global _last_sig
    from . import overlay
    if enabled:
        if on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)
        overlay.enable()
        _last_sig = None
        if not bpy.app.timers.is_registered(_deferred_trace):
            bpy.app.timers.register(_deferred_trace, first_interval=0.0)
    else:
        if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)
        if bpy.app.timers.is_registered(_deferred_trace):   # cancel a pending debounce so it can't
            try:                                             # fire (and mutate the scene) after disable
                bpy.app.timers.unregister(_deferred_trace)
            except Exception:
                pass
        overlay.disable()


@persistent
def on_load_post(*args):
    # bpy.context is unreliable inside load_post; inspect the loaded scenes directly.
    global _last_sig
    _last_sig = None
    want_live = any(getattr(s, "optics", None) and s.optics.live_enabled
                    for s in bpy.data.scenes)
    set_live(want_live)


def register():
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    if on_diagnosis_revision_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_diagnosis_revision_update)


def unregister():
    set_live(False)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    if on_diagnosis_revision_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_diagnosis_revision_update)
    try:
        if bpy.app.timers.is_registered(_deferred_trace):
            bpy.app.timers.unregister(_deferred_trace)
    except Exception:
        pass
