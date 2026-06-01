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

from . import tracer, alignment, geometry

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


def _show_image_in_blender(img):
    """Show a result image inside Blender (one place, and queryable by the add-on/AI):
    reuse an open Image Editor if there is one, else open a new window as an Image
    Editor. Falls back silently in background mode."""
    if img is None:
        return
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'IMAGE_EDITOR':
                    a.spaces.active.image = img
                    region = next((r for r in a.regions if r.type == 'WINDOW'), None)
                    if region:
                        with bpy.context.temp_override(window=w, area=a, region=region):
                            bpy.ops.image.view_all(fit_view=True)
                    a.tag_redraw()
                    return
        bpy.ops.wm.window_new()
        area = bpy.context.window_manager.windows[-1].screen.areas[0]
        area.type = 'IMAGE_EDITOR'
        area.spaces.active.image = img
    except Exception:
        pass


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
        _show_image_in_blender(bpy.data.images.get("optics_scan.png"))
        self.report({'INFO'}, "Scan %s: %d steps -> shown in the Image Editor (+ %s.png/.csv)" % (self.kind, n, base))
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


def _fringe_array(det, segs, size_mm, px, exposure=0.0, read_noise=0.0, well_depth=1.0):
    """2-D interference intensity (RGBA float32) across a detector plane from the beams
    reaching it. Returns (arr, beam_count) or (None, 0). Shared by the one-shot operator
    and the live monitor."""
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
    for s in beams:
        j = s.get("jones")
        d = (Vector(s["p2"]) - Vector(s["p1"]))
        if not j or d.length < 1e-9:
            continue
        d = d.normalized()
        k = 2.0 * np.pi / (s.get("wavelength", 632.8) * 1.0e-6)
        phase = k * (s.get("opl", 0.0) - opl_ref) + (k * d.dot(u)) * uu + (k * d.dot(v)) * vv
        wave = np.exp(1j * phase)
        fx += complex(j[0], j[1]) * wave
        fy += complex(j[2], j[3]) * wave
        used += 1
    if used == 0:
        return None, 0
    inten = np.abs(fx) ** 2 + np.abs(fy) ** 2
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


def live_fringe_update(scene):
    """Recompute + refresh the fringe pattern on every monitored detector. Called from
    the live depsgraph handler so the sensor view updates as optics move."""
    segs = tracer.cached_segments
    if not segs:
        return
    for det in scene.objects:
        op = getattr(det, "optics", None)
        if not op or not op.is_optical or not getattr(op, "is_monitor", False):
            continue
        px = 128
        arr, _used = _fringe_array(det, segs, max(op.clear_aperture * 2.0, 5.0), px)
        if arr is None:
            continue
        img = _fringe_image_for(det, px)
        img.pixels.foreach_set(arr.reshape(-1))
        img.update()
        mname = "OG_fringe_" + det.name
        if not det.data.materials or det.data.materials[0].name != mname:
            _assign_fringe_material(det, img)


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
            ranked = [o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical
                      and o.optics.element_type in tracer.TERMINAL and any(s["to"] == o.name for s in segs)]
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
        _show_image_in_blender(img)
        self.report({'INFO'}, "Fringe image (%d beams) on %s -> shown in the Image Editor" % (used, det.name))
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
            _render_plot(xs, {"coincidence R(tau)": ys}, base + ".png")
            msg = "HOM dip: R(0)=%.3f (V=%.2f), classical floor 0.5" % (ys[n // 2], self.visibility)
        else:
            # CHSH with the singlet correlation E(a,b) = -V*cos(2(a-b)); optimal angles
            # a=0, a'=45, b=22.5, b'=67.5 give |S| = 2*sqrt(2)*V (>2 violates locality).
            def E(a, b):
                return -self.visibility * math.cos(2.0 * math.radians(a - b))
            S = E(0, 22.5) - E(0, 67.5) + E(45, 22.5) + E(45, 67.5)
            xs = [180.0 * i / (n - 1) for i in range(n)]
            ys = [(E(x, 0.0) + 1.0) * 0.5 for x in xs]   # map correlation -1..1 to 0..1 for the plot
            _render_plot(xs, {"correlation (E+1)/2 vs angle": ys}, base + ".png")
            msg = ("Bell CHSH |S|=%.3f (quantum 2sqrt2=2.83, classical <=2) -> %s"
                   % (abs(S), "VIOLATED" if abs(S) > 2.0 else "within classical"))
        with open(base + ".csv", "w") as f:
            f.write("# " + msg + "\nx,y\n")
            for x, y in zip(xs, ys):
                f.write("%.6g,%.6g\n" % (x, y))
        _show_image_in_blender(bpy.data.images.get("optics_quantum.png"))
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def _sensor_camera(scene, det):
    name = "SENSOR_" + det.name
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != 'CAMERA':
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        scene.collection.objects.link(cam)
    c, n, _u, _v = _detector_plane(det)
    size = max(det.optics.clear_aperture * 2.0, 5.0)
    cam.data.lens = 50.0
    dist = size * 1.6
    cam.location = c + n * dist                  # in front of the sensor face, looking back at it
    cam.rotation_euler = (c - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.clip_start = max(0.001, dist * 0.01)
    cam.data.clip_end = dist * 50.0 + 1000.0
    return cam


def _open_camera_window(cam):
    try:
        bpy.ops.wm.window_new()
        area = bpy.context.window_manager.windows[-1].screen.areas[0]
        area.type = 'VIEW_3D'
        sp = area.spaces.active
        sp.use_local_camera = True
        sp.camera = cam
        sp.region_3d.view_perspective = 'CAMERA'
        sp.shading.type = 'MATERIAL'
    except Exception:
        pass


class OPTICS_OT_sensor_monitor(Operator):
    bl_idname = "optics.sensor_monitor"
    bl_label = "Live Sensor Monitor"
    bl_description = ("Place a camera at this detector and open a live window of what it "
                      "records; the fringe pattern updates as the optics move")
    bl_options = {'REGISTER'}

    name: StringProperty()

    def execute(self, context):
        scene = context.scene
        det = scene.objects.get(self.name) if self.name else context.object
        if det is None or det.optics.element_type not in tracer.TERMINAL:
            segs = tracer.cached_segments or _trace(scene)
            cand = [o for o in scene.objects if getattr(o, "optics", None) and o.optics.is_optical
                    and o.optics.element_type in tracer.TERMINAL]
            det = next((o for o in cand if any(s["to"] == o.name for s in segs)), cand[0] if cand else None)
        if det is None:
            self.report({'ERROR'}, "No detector to monitor")
            return {'CANCELLED'}
        det.optics.is_monitor = True
        scene.optics.live_enabled = True             # arm the live handler (drives the fringe)
        tracer.cached_segments = _trace(scene)
        live_fringe_update(scene)
        _open_camera_window(_sensor_camera(scene, det))
        self.report({'INFO'}, "Live sensor monitor on %s (move the optics to watch it update)" % det.name)
        return {'FINISHED'}


_classes = (OPTICS_OT_scan, OPTICS_OT_fringe, OPTICS_OT_quantum, OPTICS_OT_sensor_monitor)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
