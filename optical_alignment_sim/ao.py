"""Adaptive optics: modal (Zernike) wavefront sensing + deformable-mirror correction.

A beam carries a Zernike wavefront-error vector (``tracer._Ray.aberr``, in waves); an
ABERRATOR adds modes (the "turbulence"), a DEFORMABLE_MIRROR subtracts its commanded modes,
and a WAVEFRONT_SENSOR reads the residual. This module renders the sensor's reconstructed
wavefront map (false colour) into the bottom-left monitor window and runs the closed loop
(an integrator controller) that flattens it. The wavefront physics (Zernike basis, RMS) is
in physics.py and is verified against the physicist oracle.
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, FloatProperty, IntProperty

from . import physics, tracer, monitor


def _aberr_at(segs, sensor_name):
    """Zernike coeffs (list of 15, waves) of the strongest beam (by power) reaching the named
    sensor, or None if nothing reaches it. The strongest beam wins even when it is unaberrated, so
    a strong flat reference is never shadowed by a weaker aberrated stray; a beam carrying no aberr
    reads as a flat (zero) wavefront."""
    best = None
    for s in segs:
        if s.get("to") == sensor_name:
            if best is None or s.get("power", 0.0) > best[0]:
                best = (s.get("power", 0.0), s.get("aberr"))
    if best is None:
        return None
    return list(best[1]) if best[1] else [0.0] * physics.N_ZERNIKE


def _radial_np(n, m, rho):
    import numpy as np
    m = abs(m)
    s = np.zeros_like(rho)
    for k in range((n - m) // 2 + 1):
        num = ((-1) ** k) * math.factorial(n - k)
        den = (math.factorial(k) * math.factorial((n + m) // 2 - k)
               * math.factorial((n - m) // 2 - k))
        s = s + (num / den) * rho ** (n - 2 * k)
    return s


_BASIS_CACHE = {}   # px -> (mask, {j: normalized Z_j basis image}); grid+basis are call-invariant


def _zern_basis(px):
    """Cached unit-disk pupil mask + per-mode normalized Zernike basis images for a px*px grid.
    The grid and each Z_j image are constant across calls, so a wavefront map is just
    sum_j coeff_j * basis_j -- no per-call meshgrid or radial-polynomial recompute."""
    cached = _BASIS_CACHE.get(px)
    if cached is not None:
        return cached
    import numpy as np
    ax = np.linspace(-1.0, 1.0, px)
    xx, yy = np.meshgrid(ax, ax)
    rr = np.sqrt(xx * xx + yy * yy)
    th = np.arctan2(yy, xx)
    basis = {}
    for j, (n, m) in physics._NOLL.items():
        norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2.0 * (n + 1))
        ang = np.cos(m * th) if m >= 0 else np.sin(-m * th)
        basis[j] = norm * _radial_np(n, m, rr) * ang
    cached = (rr <= 1.0, basis)
    _BASIS_CACHE[px] = cached
    return cached


def wavefront_image(coeffs, px=192, vmax=1.0):
    """False-colour RGBA map (HxWx4 float32) of the wavefront W(x,y)=sum_j a_j Z_j over the
    unit disk, on a FIXED diverging scale (+-vmax waves): blue (low) -> green (zero) -> red
    (high). The fixed scale is deliberate - a corrected (flat) wavefront shows a uniform
    mid-colour and a large aberration shows full colour, so the loop's flattening is visible
    (per-frame auto-scaling would stretch even a ~0 residual to full contrast). The grid + the
    per-mode Zernike basis are cached per px (see _zern_basis), so each call is a few
    scalar-weighted array adds."""
    import numpy as np
    mask, basis = _zern_basis(px)
    W = np.zeros((px, px))
    for j, c in enumerate(coeffs, start=1):
        if abs(c) < 1e-12 or j not in basis:
            continue
        W += c * basis[j]
    t = np.clip(0.5 + 0.5 * W / (vmax or 1.0), 0.0, 1.0)   # W=0 -> 0.5 (uniform mid-colour)
    arr = np.empty((px, px, 4), dtype='float32')
    arr[:] = (0.05, 0.05, 0.06, 1.0)                       # outside the pupil
    arr[..., 0] = np.where(mask, t, arr[..., 0])
    arr[..., 1] = np.where(mask, 1.0 - np.abs(2.0 * t - 1.0), arr[..., 1])
    arr[..., 2] = np.where(mask, 1.0 - t, arr[..., 2])
    arr[..., 3] = 1.0
    return arr


def publish_wavefront(det, segs):
    """Compute + publish a wavefront sensor's reconstructed map + RMS to the monitor window."""
    coeffs = _aberr_at(segs, det.name) or [0.0] * physics.N_ZERNIKE
    det.optics.wf_rms = physics.wavefront_rms(coeffs)
    monitor.set_frame(det.name, wavefront_image(coeffs),
                      "wavefront RMS=%.3f waves" % det.optics.wf_rms)


def close_loop(scene, sensor_name, dm_name, gain=0.5, iters=15, tol=1.0e-3):
    """Modal AO integrator: each step trace -> read residual Zernike at the sensor -> accumulate
    the DM command toward it (dm_command += gain*residual) -> repeat until the wavefront is flat
    (residual RMS < tol) or genuinely STALLS (<0.1% relative improvement per step) or `iters` is
    reached. Returns the RMS history (waves), open-loop value first, corrected last. Stops early
    once converged, so a fast loop costs a handful of traces instead of the full `iters`."""
    from . import scan
    wfs = scene.objects.get(sensor_name)
    dm = scene.objects.get(dm_name)
    if wfs is None or dm is None:
        return None
    hist = []
    converged = False
    for _ in range(max(1, int(iters))):
        tracer.cached_segments = scan._trace(scene)
        coeffs = _aberr_at(tracer.cached_segments, sensor_name)
        if coeffs is None:
            converged = True
            break
        rms = physics.wavefront_rms(coeffs)
        hist.append(rms)                                   # this trace already reflects every command applied so far
        # Converge on the absolute residual; stall ONLY on a relative plateau (no real progress).
        # Reusing `tol` for the step-delta declared "converged" far above tol at low gain, because a
        # modal integrator shrinks the residual geometrically (delta ~ gain*residual), so the delta
        # drops below tol while the residual is still ~tol/gain.
        stalled = len(hist) >= 2 and (hist[-2] - rms) < 1.0e-3 * max(hist[-2], 1.0e-12)
        if rms < tol or stalled:
            converged = True
            break
        cmd = list(dm.optics.dm_command)
        for i in range(min(len(cmd), len(coeffs))):
            cmd[i] += gain * coeffs[i]
        dm.optics.dm_command = cmd
    if not converged:                                      # ran out of iters: measure the last applied command once
        tracer.cached_segments = scan._trace(scene)
        final = _aberr_at(tracer.cached_segments, sensor_name)
        if final is not None:
            hist.append(physics.wavefront_rms(final))
    if hist:
        wfs.optics.wf_rms = hist[-1]
    return hist


class OPTICS_OT_ao_close_loop(Operator):
    bl_idname = "optics.ao_close_loop"
    bl_label = "Run AO Loop"
    bl_description = ("Close the adaptive-optics loop: the wavefront sensor measures the residual "
                      "Zernike error and drives the deformable mirror until it flattens")
    bl_options = {'REGISTER', 'UNDO'}

    sensor: StringProperty(name="Wavefront sensor")
    dm: StringProperty(name="Deformable mirror")
    gain: FloatProperty(name="Loop gain", default=0.5, min=0.0, max=1.0)
    iters: IntProperty(name="Iterations", default=15, min=1, max=200)

    def invoke(self, context, event):
        scene = context.scene
        if not self.sensor:
            self.sensor = next((o.name for o in scene.objects if getattr(o, "optics", None)
                                and o.optics.element_type == 'WAVEFRONT_SENSOR'), "")
        if not self.dm:
            self.dm = next((o.name for o in scene.objects if getattr(o, "optics", None)
                            and o.optics.element_type == 'DEFORMABLE_MIRROR'), "")
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        col = self.layout.column()
        col.prop_search(self, "sensor", context.scene, "objects")
        col.prop_search(self, "dm", context.scene, "objects")
        col.prop(self, "gain")
        col.prop(self, "iters")

    def execute(self, context):
        scene = context.scene
        hist = close_loop(scene, self.sensor, self.dm, self.gain, self.iters)
        if not hist:
            self.report({'ERROR'}, "Pick a wavefront sensor + deformable mirror with a beam between them")
            return {'CANCELLED'}
        from . import scan
        scene.optics.monitor_show = True
        scan.live_fringe_update(scene)
        tracer._tag_redraw()
        self.report({'INFO'}, "AO loop: RMS %.3f -> %.3f waves over %d iters"
                    % (hist[0], hist[-1], len(hist) - 1))
        return {'FINISHED'}


class OPTICS_OT_dm_flatten(Operator):
    bl_idname = "optics.dm_flatten"
    bl_label = "Flatten Deformable Mirror"
    bl_description = "Zero the active deformable mirror's command (remove all correction)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.object
        if ob is None or getattr(ob, "optics", None) is None or ob.optics.element_type != 'DEFORMABLE_MIRROR':
            self.report({'ERROR'}, "Select a deformable mirror")
            return {'CANCELLED'}
        ob.optics.dm_command = [0.0] * physics.N_ZERNIKE
        try:
            from . import scan
            tracer.cached_segments = scan._trace(context.scene)
            scan.live_fringe_update(context.scene)
        except Exception:
            pass
        tracer._tag_redraw()
        self.report({'INFO'}, "Flattened %s" % ob.name)
        return {'FINISHED'}


_classes = (OPTICS_OT_ao_close_loop, OPTICS_OT_dm_flatten)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
