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


def _signature(scene):
    """Cheap hash of optical objects' world transforms + knob values. Used to
    skip recompute when only our own (non-transform) props changed."""
    vals = []
    for o in scene.objects:
        op = getattr(o, "optics", None)
        if op and op.is_optical:
            m = o.matrix_world
            vals += [round(m[0][3], 4), round(m[1][3], 4), round(m[2][3], 4),
                     round(m[0][0], 4), round(m[1][0], 4), round(m[2][1], 4), round(m[2][2], 4)]
            vals += [round(d.current, 4) for d in op.dofs]
    return hash(tuple(vals))


def _tag_redraw():
    wm = bpy.context.window_manager
    if not wm:
        return
    for w in wm.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()


def _deferred_trace():
    global _recomputing, _dirty, _last_sig
    _dirty = False
    scene = bpy.context.scene
    if scene is None or not getattr(scene, "optics", None):
        return None
    sig = _signature(scene)
    if sig == _last_sig:
        return None                     # nothing geometric changed -> no work
    _last_sig = sig
    _recomputing = True
    try:
        tracer.cached_segments = tracer.trace_scene(
            scene, mode=scene.optics.trace_mode,
            max_segments=scene.optics.max_segments,
            max_depth=scene.optics.max_depth)
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
        _tag_redraw()
    finally:
        _recomputing = False
    return None                          # one-shot timer


@persistent
def on_depsgraph_update(scene, depsgraph=None):
    global _dirty
    if _recomputing:                     # guard: our own writes must not re-trigger
        return
    if not getattr(scene, "optics", None) or not scene.optics.live_enabled:
        return
    _dirty = True
    if not bpy.app.timers.is_registered(_deferred_trace):
        bpy.app.timers.register(_deferred_trace, first_interval=0.03)   # debounce


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
        overlay.disable()


@persistent
def on_load_post(*args):
    scene = bpy.context.scene
    if getattr(scene, "optics", None) and scene.optics.live_enabled:
        set_live(True)


def register():
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    set_live(False)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    try:
        if bpy.app.timers.is_registered(_deferred_trace):
            bpy.app.timers.unregister(_deferred_trace)
    except Exception:
        pass
