"""Parameter-scan operator.

Sweeps one degree of freedom - an OPD translation knob, a waveplate's fast-axis
angle, or the source wavelength - re-traces at each step, and plots every
detector's response (interferogram / Malus curve / spectrum) to a PNG rasterized
with numpy (no matplotlib dependency) plus a CSV. This is the primary way to
*see* the polarization / interference / wavelength physics.
"""
from __future__ import annotations

import os
import tempfile

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, IntProperty, FloatProperty

from . import tracer, alignment

SCAN_ITEMS = [
    ('STAGE', "OPD stage (mm)", "Sweep the active element's translation knob"),
    ('WAVEPLATE', "Waveplate angle (deg)", "Sweep the active waveplate's fast-axis angle"),
    ('WAVELENGTH', "Wavelength (nm)", "Sweep every source's wavelength"),
]


def _detectors(scene):
    return [o for o in scene.objects
            if getattr(o, "optics", None) and o.optics.is_optical
            and o.optics.element_type in tracer.TERMINAL]


def _trace(scene):
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _render_plot(xs, series, out_path, W=720, H=440):
    """Rasterize line plots of {label: y-values} vs xs to an RGBA PNG and return
    the Blender image. Pure numpy - dark background, grid, colored polylines."""
    import numpy as np
    arr = np.empty((H, W, 4), dtype='float32')
    arr[:] = (0.08, 0.08, 0.10, 1.0)
    ml, mr, mb, mt = 64, 16, 40, 20
    pw, ph = W - ml - mr, H - mb - mt
    for i in range(5):                                   # grid
        gx, gy = ml + int(pw * i / 4), mb + int(ph * i / 4)
        arr[mb:mb + ph, gx, :3] = 0.18
        arr[gy, ml:ml + pw, :3] = 0.18
    arr[mb:mb + ph, ml, :3] = 0.5                        # axes
    arr[mb, ml:ml + pw, :3] = 0.5
    xmin, xmax = min(xs), max(xs)
    ys_all = [v for s in series.values() for v in s if v is not None and v >= 0.0]
    ymin, ymax = (min(ys_all), max(ys_all)) if ys_all else (0.0, 1.0)
    if ymax - ymin < 1e-9:
        ymax = ymin + 1.0

    def px(x):
        return ml + int(pw * (x - xmin) / (xmax - xmin)) if xmax > xmin else ml

    def py(y):
        return mb + int(ph * (y - ymin) / (ymax - ymin))

    colors = [(1.0, 0.35, 0.2), (0.3, 0.8, 1.0), (0.5, 1.0, 0.45), (1.0, 0.85, 0.25), (0.8, 0.45, 1.0)]

    def line(x0, y0, x1, y1, c):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for k in range(n + 1):
            x = int(round(x0 + (x1 - x0) * k / n))
            y = int(round(y0 + (y1 - y0) * k / n))
            if 0 <= x < W and 0 <= y < H:
                arr[y, x, :3] = c

    for ci, (label, yv) in enumerate(series.items()):
        c = colors[ci % len(colors)]
        pts = [(px(xs[i]), py(yv[i])) for i in range(len(xs)) if yv[i] is not None and yv[i] >= 0.0]
        for i in range(1, len(pts)):
            line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], c)

    name = os.path.basename(out_path)
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, W, H, alpha=True)
    img.pixels.foreach_set(arr.reshape(-1))
    img.filepath_raw = out_path
    img.file_format = 'PNG'
    img.save()
    return img


class OPTICS_OT_scan(Operator):
    bl_idname = "optics.scan"
    bl_label = "Scan + Plot"
    bl_description = ("Sweep a parameter and plot every detector's response "
                      "(interferogram / Malus curve / spectrum) to a PNG + CSV")
    bl_options = {'REGISTER'}

    kind: EnumProperty(name="Scan", items=SCAN_ITEMS, default='STAGE')
    lo: FloatProperty(name="From", default=0.0)
    hi: FloatProperty(name="To", default=0.002)
    steps: IntProperty(name="Steps", default=120, min=2, max=2000)

    def invoke(self, context, event):
        self.lo, self.hi = {'WAVEPLATE': (0.0, 180.0),
                            'WAVELENGTH': (400.0, 700.0)}.get(self.kind, (0.0, 0.002))
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scene = context.scene
        obj = context.object
        dets = _detectors(scene)
        if not dets:
            self.report({'ERROR'}, "No detectors in the scene")
            return {'CANCELLED'}

        restore = []
        if self.kind == 'STAGE':
            dof = next((d for d in obj.optics.dofs if d.kind.startswith('TRANS')), None) if obj else None
            if dof is None:
                self.report({'ERROR'}, "Select the element with a translation knob")
                return {'CANCELLED'}
            orig = dof.current
            restore.append(lambda: setattr(dof, 'current', orig))

            def sweep_set(x):
                dof.current = x
        elif self.kind == 'WAVEPLATE':
            if obj is None or obj.optics.element_type != 'WAVEPLATE':
                self.report({'ERROR'}, "Select a waveplate")
                return {'CANCELLED'}
            orig = obj.optics.fast_axis_deg
            restore.append(lambda: setattr(obj.optics, 'fast_axis_deg', orig))

            def sweep_set(x):
                obj.optics.fast_axis_deg = x
        else:  # WAVELENGTH
            srcs = [o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical
                    and (o.optics.is_source or o.optics.element_type in ('SOURCE', 'FIBER_COLLIMATOR'))]
            if not srcs:
                self.report({'ERROR'}, "No sources to tune")
                return {'CANCELLED'}
            saved = [(o, o.optics.wavelength) for o in srcs]
            restore.append(lambda: [setattr(o.optics, 'wavelength', w) for o, w in saved])

            def sweep_set(x):
                for o in srcs:
                    o.optics.wavelength = x

        xs = []
        series = {d.name: [] for d in dets}
        n = max(self.steps, 2)
        for i in range(n):
            x = self.lo + (self.hi - self.lo) * i / (n - 1)
            sweep_set(x)
            context.view_layer.update()
            segs = _trace(scene)
            xs.append(x)
            for d in dets:
                p, _v, _s = alignment.measure(segs, d.name, d.optics.analyzer)
                series[d.name].append(p if p >= 0.0 else 0.0)
        for fn in restore:
            fn()
        context.view_layer.update()
        tracer.cached_segments = _trace(scene)

        base = os.path.join(tempfile.gettempdir(), "optics_scan")
        _render_plot(xs, series, base + ".png")
        with open(base + ".csv", "w") as f:
            f.write("x," + ",".join(series.keys()) + "\n")
            for i, x in enumerate(xs):
                f.write(("%.6g," % x) + ",".join("%.6g" % series[k][i] for k in series) + "\n")
        self.report({'INFO'}, "Scan %s: %d steps -> %s.png / .csv" % (self.kind, n, base))
        return {'FINISHED'}


_classes = (OPTICS_OT_scan,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
