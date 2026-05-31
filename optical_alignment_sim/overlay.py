"""GPU viewport overlay for the live beam path.

Draws tracer.cached_segments as thick polylines (plus optional port dots) every
redraw, creating NO datablocks - so it updates instantly while dragging and
never pollutes the outliner / undo stack. Shaders are created lazily inside the
draw callback (never in background mode, where there is no GPU context).
"""
from __future__ import annotations

import bpy

from . import tracer, geometry

_handle = None
_line_shader = None
_point_shader = None


def _shaders():
    global _line_shader, _point_shader
    import gpu
    if _line_shader is None:
        _line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    if _point_shader is None:
        try:
            _point_shader = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
        except Exception:
            _point_shader = None
    return _line_shader, _point_shader


def _color_for(kind):
    if kind == 'SPLIT_T':
        return (1.0, 0.55, 0.15, 0.6)      # beam-splitter transmitted: dim orange
    return (1.0, 0.12, 0.05, 0.95)         # main beam: red


def _draw():
    try:
        segs = tracer.cached_segments
        if not segs:
            return
        import gpu
        from gpu_extras.batch import batch_for_shader

        scn = bpy.context.scene
        sp = getattr(scn, "optics", None)
        width = sp.line_width if sp else 3.0
        show_ports = sp.show_ports if sp else True
        region = bpy.context.region
        if region is None:
            return
        line_sh, point_sh = _shaders()

        groups = {}
        for s in segs:
            groups.setdefault(s["kind"], []).extend([s["p1"], s["p2"]])

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        try:
            line_sh.bind()
            line_sh.uniform_float("viewportSize", (region.width, region.height))
            for kind, coords in groups.items():
                line_sh.uniform_float("lineWidth", width if kind != 'SPLIT_T' else max(1.0, width * 0.6))
                line_sh.uniform_float("color", _color_for(kind))
                batch_for_shader(line_sh, 'LINES', {"pos": coords}).draw(line_sh)

            if show_ports and point_sh is not None:
                try:
                    pts = []
                    for ob in scn.objects:
                        op = getattr(ob, "optics", None)
                        if op and op.is_optical:
                            for p in op.ports:
                                pts.append(geometry.world_port(ob, p.local_position))
                    if pts:
                        point_sh.bind()
                        try:
                            point_sh.uniform_float("size", 9.0)
                        except Exception:
                            pass
                        gpu.state.point_size_set(9.0)
                        point_sh.uniform_float("color", (0.15, 0.8, 1.0, 0.9))
                        batch_for_shader(point_sh, 'POINTS', {"pos": pts}).draw(point_sh)
                except Exception:
                    pass
        finally:                                  # always restore GPU state, even on error
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
    except Exception as e:        # never raise inside a draw handler
        print("[optics overlay] draw error:", e)


def enable():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def disable():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None


def is_enabled():
    return _handle is not None


def register():
    pass


def unregister():
    global _line_shader, _point_shader
    disable()
    _line_shader = None
    _point_shader = None
