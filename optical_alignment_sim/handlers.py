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
_rendering = False          # a render job is running (render_init .. render_complete / render_cancel)
_revision_sig = None        # live signature behind the current optics_scene_revision

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
    "analyzer", "shutter_open", "aperture_shape", "aperture_half_y", "back_surface",
    # These are inputs too. Leaving them out makes a live/API read look successful while
    # the trace still represents the previous scene (M² was the most visible example).
    "m2", "crystal_material", "crystal_length_mm", "crystal_temp_C", "nl_process",
    "nl_efficiency", "nl_lambda2_nm", "poling_period_um", "nl_walkoff_mm",
    "phase_matching_type", "pm_scheme", "use_chi2_solver", "nl_pump_power_W",
    "oe_split", "oe_material", "oe_axis_deg", "oe_length_mm", "sensor_px",
    "pixel_size_um", "sensor_exposure", "sensor_read_noise", "sensor_well_depth",
)


def _signature(scene):
    """Cheap hash of optical objects' world transforms + knob values + physics input params.
    Used to skip recompute only when nothing the tracer reads changed."""
    from . import param_schema
    vals = [scene.as_pointer()]
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if op and op.is_optical:
            # Names are part of the public state: a detector rename changes every segment's
            # `to` field even when its geometry is identical.
            vals.append(o.name)
            for port in op.ports:
                vals.extend((port.name, port.role, tuple(port.local_position),
                             tuple(port.local_normal), port.clear_aperture))
            m = o.matrix_world
            vals += [float(m[r][c]) for r in range(3) for c in range(4)]   # full rotation + position
            vals += [round(d.current, 4) for d in op.dofs]
            for name in sorted(set(_SIG_PROPS) | set(param_schema.names(op.element_type))):
                v = getattr(op, name, None)
                vals.append(tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)
            vals += [round(x, 6) for x in op.aberr_spec]      # Zernike inject (FloatVectorProperty)
            vals += [round(x, 6) for x in op.dm_command]      # DM correction command
    # Unit interpretation lives on the scene, not on an element. Include it in the same
    # digest so changing the declaration cannot leave a millimetre readout backed by an old
    # metre-scale trace.
    sop = getattr(scene, "optics", None)
    vals += [
        bool(getattr(sop, "scene_units_authoritative", False)),
        round(float(getattr(scene.unit_settings, "scale_length", 1.0)), 9),
        getattr(scene.unit_settings, "length_unit", ""),
    ]
    if sop:
        vals.extend((sop.trace_mode, sop.order_csv, sop.max_segments, sop.max_depth,
                     sop.model_ghosts, sop.ghost_floor, sop.max_ghost_depth))
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
            tracer.cached_segments = []
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
    """Invalidate cached UI diagnostics without inspecting the dependency graph: only a change
    the tracer reads (the live signature) makes Diagnose and Corrections out of date, so selecting
    an object, or Fix… selecting the affected element, leaves them current."""
    global _revision_sig
    try:
        sig = _signature(scene) if getattr(scene, "optics", None) else None
    except Exception:
        sig = None                      # cannot tell what changed: treat it as a change
    if sig is None or sig != _revision_sig:
        _revision_sig = sig
        for wm in bpy.data.window_managers:
            wm.optics_scene_revision += 1
    # With Live disabled there is no deferred trace to refresh the shared cache. Dropping a
    # stale one makes read buttons (Power Budget, sensor panels, and API consumers) fail closed
    # instead of presenting a previous scene as current. During a live trace `_recomputing`
    # protects the freshly written cache from this invalidation callback.
    baking = False
    try:
        from . import bake
        baking = bool(getattr(bake, "_baking", False))
    except Exception:
        pass
    if not _recomputing and not baking and not getattr(getattr(scene, "optics", None), "live_enabled", False):
        _drop_stale_cache(scene, sig)


def _drop_stale_cache(scene, sig_now=None):
    """Drop the cache only when an input it was traced from changed. Selecting an object or
    any other update the tracer does not read keeps an explicit Trace Now on screen; a cache
    without a recorded signature (copied or filtered) cannot be vouched for and is dropped."""
    segs = tracer.cached_segments
    if not segs:
        return
    sig = getattr(segs, "scene_sig", None)
    if sig is None or sig != (sig_now if sig_now is not None else _signature(scene)):
        tracer.cached_segments = []


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
def on_frame_change(scene, depsgraph=None):
    """Keep keyed optical properties/poses and the live cache in lockstep.

    Blender's frame changes do not necessarily produce an optical-property update, so a keyed
    shutter or mirror can otherwise leave the overlay and readouts on frame 1 while the mesh is
    visibly on frame N. A frame is an explicit state boundary: force one fresh trace here.
    """
    global _last_sig, _pending_scene
    if scene is None or not getattr(scene, "optics", None):
        return
    if _rendering and _render_writes_unsafe(scene):
        return
    _pending_scene = scene
    _last_sig = None
    if scene.optics.live_enabled:
        _deferred_trace()
    else:
        _drop_stale_cache(scene)


def _is_background():
    return bpy.app.background


def _render_writes_unsafe(scene):
    """While rendering, Blender runs frame_change and render handlers on one thread and draws the
    viewport from another; a handler changing data the viewport reads can crash Blender unless
    Render > Lock Interface is on (bpy.app.handlers, "Note on Altering Data"). A background render
    has no viewport to race."""
    return not _is_background() and not scene.render.use_lock_interface


def beams_need_render_lock(scene):
    """Baked beams on a bench with animated optics, rendered with the interface unlocked: the render
    keeps the beams as baked, so the Render panel says so before the user renders. Only an action on
    an optical object counts (drivers, constraints and animated parents are not inspected)."""
    if not _render_writes_unsafe(scene):
        return False
    if not any(o.name.startswith("BEAM_") for o in scene.objects):
        return False
    return any(o.animation_data is not None and o.animation_data.action is not None
               for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical)


@persistent
def on_render_init(scene, *args):
    global _rendering
    _rendering = True
    if (scene is not None and _render_writes_unsafe(scene)
            and any(o.name.startswith("BEAM_") for o in scene.objects)):
        print("[optics] Render > Lock Interface is off: beams stay as baked for this render. "
              "Turn Lock Interface on to re-bake them per frame, or bake the frame first.")


@persistent
def on_render_done(scene, *args):
    global _rendering
    _rendering = False


@persistent
def on_render_pre(scene, depsgraph=None):
    """Rebuild renderable beam meshes for the frame Blender is about to render."""
    if scene is None or not getattr(scene, "optics", None):
        return
    if not any(o.name.startswith("BEAM_") for o in scene.objects):
        return
    if _render_writes_unsafe(scene):
        return
    # bake.ensure_beams is context-based. Blender normally renders the active scene,
    # but a queued multi-scene render can call this callback for another scene; skip in
    # that case rather than baking the active scene's beams into the wrong file.
    if getattr(bpy.context, "scene", None) is not scene:
        return
    # ensure_beams re-traces and compares the bake signature, so animation renders cannot
    # reuse frame-1 tubes after a keyed shutter/mirror change.
    try:
        from . import bake
        bake.ensure_beams(bpy.context)
    except Exception as exc:
        print("[optics] render beam bake error:", exc)


@persistent
def on_load_post(*args):
    # bpy.context is unreliable inside load_post; inspect the loaded scenes directly.
    global _last_sig, _pending_scene, _dirty
    _last_sig = None
    _pending_scene = None
    _dirty = False
    # RNA pointers from the previous .blend are invalid after a load. Never let a timer
    # dereference one; the next explicit/live trace repopulates the cache for the new file.
    tracer.cached_segments = []
    try:
        from . import bake
        bake._baked_sig = None
        bake._baked_scale = None
        bake._baking = False
    except Exception:
        pass
    want_live = any(getattr(s, "optics", None) and s.optics.live_enabled
                    for s in bpy.data.scenes)
    set_live(want_live)


def register():
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    if on_diagnosis_revision_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_diagnosis_revision_update)
    if on_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(on_frame_change)
    if on_render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(on_render_pre)
    if on_render_init not in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.append(on_render_init)
    for done in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if on_render_done not in done:
            done.append(on_render_done)


def unregister():
    set_live(False)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    if on_diagnosis_revision_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_diagnosis_revision_update)
    if on_frame_change in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(on_frame_change)
    if on_render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(on_render_pre)
    if on_render_init in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.remove(on_render_init)
    for done in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if on_render_done in done:
            done.remove(on_render_done)
    try:
        if bpy.app.timers.is_registered(_deferred_trace):
            bpy.app.timers.unregister(_deferred_trace)
    except Exception:
        pass
