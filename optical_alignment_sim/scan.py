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

from bpy.props import BoolProperty, StringProperty

from . import tracer, alignment, geometry, monitor

SCAN_ITEMS = [
    ('STAGE', "OPD stage (mm)", "Sweep the active element's translation knob"),
    ('WAVEPLATE', "Waveplate angle (deg)", "Sweep the active waveplate's fast-axis angle"),
    ('WAVELENGTH', "Wavelength (nm)", "Sweep every source's wavelength"),
]


def _detectors(scene):
    return [o for o in scene.objects
            if getattr(o, "optics", None) and o.optics.is_optical
            and o.optics.element_type in tracer.TERMINAL]


def _lit_detectors(scene, segs):
    """Terminal detectors currently receiving at least one beam (the candidate set the
    monitor, the fringe operator, and detector auto-resolution all share)."""
    hit = {s["to"] for s in segs}
    return [d for d in _detectors(scene) if d.name in hit]


def _trace(scene):
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def _render_plot(xs, series, out_path, W=720, H=440, title=""):
    """Rasterize line plots of {label: y-values} vs xs to an RGBA PNG and return
    the Blender image. Pure numpy - dark background, grid, colored polylines.
    The same array is published to the bottom-left monitor overlay."""
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
    # arr is built bottom-up (row 0 = bottom), matching both Image datablocks and
    # GPUTexture data layout, so the overlay shows it the same way up as the PNG.
    monitor.set_frame("__plot__", arr, title)
    return img


def _show_monitor(context):
    """Turn on + redraw the bottom-left sensor/plot overlay window."""
    monitor.enable()
    if getattr(context.scene, "optics", None):
        context.scene.optics.monitor_show = True
    tracer._tag_redraw()


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
        _render_plot(xs, series, base + ".png", title="Scan: %s" % self.kind)
        with open(base + ".csv", "w") as f:
            f.write("x," + ",".join(series.keys()) + "\n")
            for i, x in enumerate(xs):
                f.write(("%.6g," % x) + ",".join("%.6g" % series[k][i] for k in series) + "\n")
        _show_monitor(context)
        self.report({'INFO'}, "Scan %s: %d steps -> bottom-left window (+ %s.png/.csv)" % (self.kind, n, base))
        return {'FINISHED'}


def _detector_plane(det):
    """(center, normal, u_hat, v_hat) of a detector's IN face in world space."""
    from mathutils import Vector
    ip = next((p for p in det.optics.ports if p.role == 'IN'), None)
    if ip is not None:
        c = geometry.world_port(det, ip.local_position)
        n = geometry.world_normal(det, ip.local_normal)
    else:
        c = det.matrix_world.translation.copy()
        n = (det.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    u = n.cross(Vector((0, 0, 1)))
    if u.length < 1e-6:
        u = n.cross(Vector((1, 0, 0)))
    u.normalize()
    v = n.cross(u).normalized()
    return c, n, u, v


def _assign_fringe_material(det, img):
    m = bpy.data.materials.get("OG_fringe_" + det.name) or bpy.data.materials.new("OG_fringe_" + det.name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[1].default_value = 2.0
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])
    det.data.materials.clear()
    det.data.materials.append(m)


def _fringe_array(det, segs, size_mm, px, exposure=0.0, read_noise=0.0, well_depth=1.0,
                  norm='self'):
    """2-D interference intensity (RGBA float32) across a detector plane from the beams
    reaching it. Returns (arr, beam_count) or (None, 0). Shared by the one-shot operator
    and the live monitor.

    norm='self' rescales to the frame's own max (best spatial contrast - for the saved
    fringe image); norm='peak' rescales to the fully-constructive maximum so ABSOLUTE
    brightness is faithful (a dark fringe looks dark) - what the live sensor window wants.
    """
    import numpy as np
    from mathutils import Vector
    beams = [s for s in segs if s["to"] == det.name]
    if not beams:
        return None, 0
    _c, _n, u, v = _detector_plane(det)
    half = size_mm * 0.5
    ax = np.linspace(-half, half, px)
    uu, vv = np.meshgrid(ax, ax)
    fx = np.zeros((px, px), dtype=complex)
    fy = np.zeros((px, px), dtype=complex)
    opl_ref = beams[0].get("opl", 0.0)
    used = 0
    amp_sum = 0.0
    for s in beams:
        j = s.get("jones")
        d = (Vector(s["p2"]) - Vector(s["p1"]))
        if not j or d.length < 1e-9:
            continue
        d = d.normalized()
        k = 2.0 * np.pi / (s.get("wavelength", 632.8) * 1.0e-6)
        phase = k * (s.get("opl", 0.0) - opl_ref) + (k * d.dot(u)) * uu + (k * d.dot(v)) * vv
        wave = np.exp(1j * phase)
        jx, jy = complex(j[0], j[1]), complex(j[2], j[3])
        fx += jx * wave
        fy += jy * wave
        amp_sum += (abs(jx) ** 2 + abs(jy) ** 2) ** 0.5     # max coherent amplitude
        used += 1
    if used == 0:
        return None, 0
    inten = np.abs(fx) ** 2 + np.abs(fy) ** 2
    if norm == 'peak' and amp_sum > 1e-12:
        inten = np.clip(inten / (amp_sum ** 2), 0.0, 1.0)   # absolute: constructive=1, dark=0
    else:
        mx = float(inten.max())
        if mx > 1e-12:
            inten = inten / mx
    if exposure > 0.0:                                   # camera model: shot + read noise + saturation
        sig = inten * exposure
        sig = sig + np.sqrt(np.maximum(sig, 0.0)) * np.random.standard_normal(sig.shape)
        sig = sig + read_noise * np.random.standard_normal(sig.shape)
        inten = np.clip(sig, 0.0, well_depth) / well_depth
    arr = np.empty((px, px, 4), dtype='float32')
    arr[..., 0] = inten
    arr[..., 1] = inten * 0.5
    arr[..., 2] = inten * 0.45
    arr[..., 3] = 1.0
    return arr, used


def _fringe_image_for(det, px):
    """Get/create the per-detector fringe image datablock at resolution px."""
    name = "OG_fringe_" + det.name
    img = bpy.data.images.get(name)
    if img is None or tuple(img.size) != (px, px):
        if img:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(name, px, px, alpha=True)
    return img


def _sensor_field_mm(op):
    """Physical sensor extent in mm = resolution x pixel pitch (falls back to aperture)."""
    px = int(getattr(op, "sensor_px", 256))
    pitch_um = float(getattr(op, "pixel_size_um", 5.0))
    field = px * pitch_um * 1.0e-3
    if field <= 1.0e-6:
        field = max(getattr(op, "clear_aperture", 5.0) * 2.0, 5.0)
    return field, px


def _monitor_targets(scene, segs):
    """Detectors whose recorded pattern belongs in the sensor window: the UNION of every
    terminal currently receiving a beam (so the scene "Sensor window" toggle just works and
    the active/lit detector always has a frame) plus any explicitly `is_monitor`-flagged
    detector. A flag never starves the others, so one stale flag can't hijack the window."""
    out = _lit_detectors(scene, segs)
    for d in _detectors(scene):
        if getattr(d.optics, "is_monitor", False) and d not in out:
            out.append(d)
    return out


def live_fringe_update(scene):
    """Recompute each monitored detector's recorded pattern and publish it to the bottom-left
    sensor window. Called from the live depsgraph handler (updates as optics move) and when
    the window is toggled on. Render-independent (the overlay is a viewport draw handler)."""
    sp = getattr(scene, "optics", None)
    if not sp or not getattr(sp, "monitor_show", False):
        return
    segs = tracer.cached_segments
    if not segs:
        return
    keep = set()
    for det in _monitor_targets(scene, segs):
        op = det.optics
        field, px = _sensor_field_mm(op)
        # Live preview is the IDEAL field (no camera noise) so it doesn't flicker / re-roll
        # random noise on every redraw; the camera model (exposure/read-noise/saturation)
        # is applied by Save Sensor Image and the one-shot Detector Fringe Image instead.
        arr, _used = _fringe_array(det, segs, field, px, 0.0, 0.0, 4000.0, norm='peak')
        if arr is None:
            continue
        p, vis, _s = alignment.measure(segs, det.name, op.analyzer)
        txt = "P=%.3f" % p + ("  V=%.2f" % vis if vis >= 0.0 else "") + ("  %dpx @ %.1fum" % (px, op.pixel_size_um))
        monitor.set_frame(det.name, arr, txt)
        keep.add(det.name)
    for name in monitor.frame_names():            # drop stale detector frames (no beam now)
        if name != "__plot__" and name not in keep:
            monitor.set_frame(name, None)


class OPTICS_OT_fringe(Operator):
    bl_idname = "optics.fringe_image"
    bl_label = "Detector Fringe Image"
    bl_description = ("Synthesize the 2-D interference pattern across a detector plane "
                      "(beam tilt -> straight fringes) into an image")
    bl_options = {'REGISTER'}

    size_mm: FloatProperty(name="Detector size (mm)", default=10.0, min=0.1)
    px: IntProperty(name="Resolution (px)", default=256, min=32, max=1024)
    to_material: BoolProperty(name="Show on detector (render)", default=True)
    exposure: FloatProperty(name="Exposure (peak counts, 0 = ideal)", default=0.0, min=0.0)
    read_noise: FloatProperty(name="Read noise (counts)", default=5.0, min=0.0)
    well_depth: FloatProperty(name="Saturation (counts)", default=4000.0, min=1.0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import os
        import tempfile
        scene = context.scene
        segs = tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                                  max_segments=scene.optics.max_segments, max_depth=scene.optics.max_depth)
        det = context.object
        if det is None or det.optics.element_type not in tracer.TERMINAL or not [s for s in segs if s["to"] == det.name]:
            ranked = _lit_detectors(scene, segs)
            if not ranked:
                self.report({'ERROR'}, "No detector with an incoming beam")
                return {'CANCELLED'}
            det = max(ranked, key=lambda o: len([s for s in segs if s["to"] == o.name]))
        arr, used = _fringe_array(det, segs, self.size_mm, self.px,
                                  self.exposure, self.read_noise, self.well_depth)
        if arr is None:
            self.report({'ERROR'}, "No interfering beams at the detector")
            return {'CANCELLED'}
        out = os.path.join(tempfile.gettempdir(), "optics_fringe.png")
        old = bpy.data.images.get("optics_fringe.png")
        if old:
            bpy.data.images.remove(old)
        img = bpy.data.images.new("optics_fringe.png", self.px, self.px, alpha=True)
        img.pixels.foreach_set(arr.reshape(-1))
        img.filepath_raw = out
        img.file_format = 'PNG'
        img.save()
        if self.to_material:
            _assign_fringe_material(det, img)
        # Align the detector's live-window params to this operator's so that when the
        # window refreshes (via the monitor_show toggle) it reproduces the same field of
        # view / resolution rather than overwriting it with a differently-scaled image.
        det.optics.sensor_px = self.px
        if self.px > 0:
            det.optics.pixel_size_um = self.size_mm * 1000.0 / self.px
        monitor.set_frame(det.name, arr, "fringe  (%d beams)" % used)
        _show_monitor(context)
        self.report({'INFO'}, "Fringe image (%d beams) on %s -> bottom-left window (+ %s)" % (used, det.name, out))
        return {'FINISHED'}


class OPTICS_OT_quantum(Operator):
    bl_idname = "optics.quantum"
    bl_label = "Quantum Readout (analytic)"
    bl_description = ("Analytic two-photon readout for the named quantum examples: "
                      "Hong-Ou-Mandel coincidence dip or Bell CHSH curve (not a full QM engine)")
    bl_options = {'REGISTER'}

    kind: EnumProperty(name="Setup",
                       items=[('HOM', "Hong-Ou-Mandel dip", "Coincidences vs delay"),
                              ('BELL', "Bell CHSH", "Correlation vs analyzer angle")],
                       default='HOM')
    visibility: FloatProperty(name="Visibility", default=1.0, min=0.0, max=1.0)
    steps: IntProperty(name="Steps", default=200, min=10, max=2000)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import os
        import tempfile
        import math
        base = os.path.join(tempfile.gettempdir(), "optics_quantum")
        n = max(self.steps, 10)
        if self.kind == 'HOM':
            # two-photon coincidence rate vs delay (units of coherence time): dips to
            # 0 at tau=0 for indistinguishable photons, classical floor 0.5.
            xs = [-5.0 + 10.0 * i / (n - 1) for i in range(n)]
            ys = [0.5 * (1.0 - self.visibility * math.exp(-(x * x))) for x in xs]
            _render_plot(xs, {"coincidence R(tau)": ys}, base + ".png", title="HOM dip")
            msg = "HOM dip: R(0)=%.3f (V=%.2f), classical floor 0.5" % (ys[n // 2], self.visibility)
        else:
            # CHSH with the singlet correlation E(a,b) = -V*cos(2(a-b)); optimal angles
            # a=0, a'=45, b=22.5, b'=67.5 give |S| = 2*sqrt(2)*V (>2 violates locality).
            def E(a, b):
                return -self.visibility * math.cos(2.0 * math.radians(a - b))
            S = E(0, 22.5) - E(0, 67.5) + E(45, 22.5) + E(45, 67.5)
            xs = [180.0 * i / (n - 1) for i in range(n)]
            ys = [(E(x, 0.0) + 1.0) * 0.5 for x in xs]   # map correlation -1..1 to 0..1 for the plot
            _render_plot(xs, {"correlation (E+1)/2 vs angle": ys}, base + ".png", title="Bell CHSH")
            msg = ("Bell CHSH |S|=%.3f (quantum 2sqrt2=2.83, classical <=2) -> %s"
                   % (abs(S), "VIOLATED" if abs(S) > 2.0 else "within classical"))
        with open(base + ".csv", "w") as f:
            f.write("# " + msg + "\nx,y\n")
            for x, y in zip(xs, ys):
                f.write("%.6g,%.6g\n" % (x, y))
        _show_monitor(context)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def _resolve_detector(scene, name):
    """The named detector, else the active object if it's a terminal, else the
    terminal currently receiving the most beams."""
    det = scene.objects.get(name) if name else None
    if det is None:
        ob = bpy.context.object
        if ob is not None and getattr(ob, "optics", None) and ob.optics.is_optical \
                and ob.optics.element_type in tracer.TERMINAL:
            det = ob
    if det is None:
        segs = tracer.cached_segments or _trace(scene)
        lit = _lit_detectors(scene, segs)
        cand = _detectors(scene)
        det = lit[0] if lit else (cand[0] if cand else None)
    return det


class OPTICS_OT_sensor_monitor(Operator):
    bl_idname = "optics.sensor_monitor"
    bl_label = "Live Sensor Window"
    bl_description = ("Show what this detector RECORDS (its 2-D intensity / fringe pattern) "
                      "in a live framed window docked to the viewport's bottom-left corner. "
                      "Updates as the optics move; never appears in a render")
    bl_options = {'REGISTER'}

    name: StringProperty()

    def execute(self, context):
        scene = context.scene
        det = _resolve_detector(scene, self.name)
        if det is None:
            self.report({'ERROR'}, "No detector to monitor")
            return {'CANCELLED'}
        det.optics.is_monitor = True
        context.view_layer.objects.active = det      # so the overlay shows this sensor
        scene.optics.live_enabled = True             # arm the live handler (drives the fringe)
        tracer.cached_segments = _trace(scene)
        live_fringe_update(scene)
        _show_monitor(context)
        self.report({'INFO'}, "Live sensor window on %s (bottom-left; updates as the optics move)" % det.name)
        return {'FINISHED'}


class OPTICS_OT_save_sensor(Operator):
    bl_idname = "optics.save_sensor"
    bl_label = "Save Sensor Image"
    bl_description = "Save the active sensor's currently recorded pattern to a PNG (render-independent)"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', default="//sensor.png")
    filter_glob: StringProperty(default="*.png", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        det = _resolve_detector(scene, "")
        if det is None:
            self.report({'ERROR'}, "Select a detector / sensor")
            return {'CANCELLED'}
        op = det.optics
        field, px = _sensor_field_mm(op)
        segs = tracer.cached_segments or _trace(scene)
        arr, _used = _fringe_array(det, segs, field, px,
                                   getattr(op, "sensor_exposure", 0.0),
                                   getattr(op, "sensor_read_noise", 0.0),
                                   getattr(op, "sensor_well_depth", 4000.0), norm='peak')
        if arr is None:
            self.report({'ERROR'}, "No beam at the sensor")
            return {'CANCELLED'}
        img = bpy.data.images.new("optics_sensor_save", px, px, alpha=True)
        try:
            img.pixels.foreach_set(arr.reshape(-1))
            img.filepath_raw = bpy.path.abspath(self.filepath)
            img.file_format = 'PNG'
            img.save()
        finally:
            bpy.data.images.remove(img)
        self.report({'INFO'}, "Saved %s sensor image -> %s" % (det.name, self.filepath))
        return {'FINISHED'}


_classes = (OPTICS_OT_scan, OPTICS_OT_fringe, OPTICS_OT_quantum,
            OPTICS_OT_sensor_monitor, OPTICS_OT_save_sensor)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
