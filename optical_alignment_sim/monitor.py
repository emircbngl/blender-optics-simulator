"""Live sensor "window" - a framed GPU overlay docked to the 3D viewport's bottom-left
corner.

It is drawn every redraw from the latest sensor / plot array (a module buffer), so it is
always live, can't be broken by mouse navigation, and - being a viewport draw handler -
NEVER appears in an F12 / EEVEE / Cycles render. Same family as overlay.py (the beam
overlay). No new editor/window type (Blender Python can't register one); this picture-in-
picture panel is the robust, render-independent stand-in.
"""
from __future__ import annotations

import bpy

_handle = None
_frames = {}        # name -> {"arr": np.ndarray HxWx4, "w", "h", "text", "ver"}
_tex_cache = {}     # name -> (ver, GPUTexture)
_ver = 0


def set_frame(name, arr, text=""):
    """Publish the latest frame for `name` (arr = HxWx4 float32, or None to clear)."""
    global _ver
    if arr is None:
        _frames.pop(name, None)
        _tex_cache.pop(name, None)
        return
    _ver += 1
    _frames[name] = {"arr": arr, "w": int(arr.shape[1]), "h": int(arr.shape[0]),
                     "text": text, "ver": _ver}


def has_frames():
    return bool(_frames)


def _pick(context):
    ob = getattr(context, "active_object", None)
    if ob is not None and getattr(ob, "optics", None) and ob.name in _frames:
        return ob.name
    if "__plot__" in _frames:
        return "__plot__"
    return next(iter(_frames), None)


def _rect(x0, y0, x1, y1, color):
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(sh, 'TRI_FAN', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _draw():
    try:
        scn = bpy.context.scene
        sp = getattr(scn, "optics", None)
        if not sp or not getattr(sp, "monitor_show", False) or not _frames:
            return
        region = bpy.context.region
        if region is None:
            return
        name = _pick(bpy.context)
        fr = _frames.get(name)
        if not fr:
            return

        import gpu
        from gpu_extras.batch import batch_for_shader

        cached = _tex_cache.get(name)
        if not cached or cached[0] != fr["ver"]:
            flat = fr["arr"].reshape(-1)
            buf = gpu.types.Buffer('FLOAT', fr["w"] * fr["h"] * 4, flat)
            tex = gpu.types.GPUTexture((fr["w"], fr["h"]), format='RGBA32F', data=buf)
            _tex_cache[name] = (fr["ver"], tex)
        else:
            tex = cached[1]

        S = max(96, int(getattr(sp, "monitor_size", 256)))
        m, title_h, pad = 16, 18, 6
        x0, y0, x1, y1 = m, m, m + S, m + S

        gpu.state.blend_set('ALPHA')
        b = 2
        _rect(x0 - pad - b, y0 - pad - b, x1 + pad + b, y1 + title_h + pad + b,
              (0.40, 0.44, 0.52, 0.95))                                                 # light border
        _rect(x0 - pad, y0 - pad, x1 + pad, y1 + title_h + pad, (0.07, 0.07, 0.09, 0.92))  # panel bg
        sh = gpu.shader.from_builtin('IMAGE')
        batch = batch_for_shader(sh, 'TRI_FAN',
                                 {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                  "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]})
        sh.bind()
        sh.uniform_sampler("image", tex)
        batch.draw(sh)
        gpu.state.blend_set('NONE')

        import blf
        fid = 0
        title = "Plot" if name == "__plot__" else ("Sensor: %s" % name)
        try:
            blf.size(fid, 12)
        except TypeError:
            blf.size(fid, 12, 72)
        blf.color(fid, 0.92, 0.92, 0.95, 1.0)
        blf.position(fid, x0, y1 + 4, 0)
        blf.draw(fid, title)
        if fr.get("text"):
            try:
                blf.size(fid, 11)
            except TypeError:
                blf.size(fid, 11, 72)
            blf.color(fid, 0.7, 0.85, 1.0, 1.0)
            blf.position(fid, x0, y0 - 14, 0)
            blf.draw(fid, fr["text"])
    except Exception as e:                       # never raise inside a draw handler
        print("[optics monitor] draw error:", e)


def enable():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')


def disable():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None


def register():
    # Always arm the draw handler; _draw early-returns when monitor_show is off or there
    # are no frames, so it is free until used - and it survives addon/file reloads
    # (no need to re-run the operator to get the window back).
    enable()


def unregister():
    disable()
    _frames.clear()
    _tex_cache.clear()
