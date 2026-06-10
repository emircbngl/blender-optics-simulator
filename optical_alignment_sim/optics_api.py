"""Phase-A programmatic facade (OPTIONAL).

Wraps the same pure-Python core the UI operators use, returning JSON-able dicts.
Not required for human use. When the add-on is enabled, __init__ aliases this
module as the top-level `optics_api`, so Claude can drive the bench through the
existing execute_blender_code socket:

    import optics_api, json
    print(json.dumps(optics_api.get_state()))
"""
from __future__ import annotations

import bpy

from . import tracer, alignment, mounts, geometry
from . import operators as _ops
from . import bake as _bake
from . import render as _render


def _scene():
    return bpy.context.scene


def _beam_path_json(segs):
    return [{
        "from": s["from"], "to": s["to"],
        "p1": [round(x, 3) for x in s["p1"]], "p2": [round(x, 3) for x in s["p2"]],
        "kind": s["kind"], "power": s["power"],
        "wavelength": s["wavelength"], "parent": s["parent"],
    } for s in segs]


def _trace(scene):
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


def get_state():
    """Full optical state: every element's world center, ports (world pos+normal),
    mount/DOF, mechanics, params, misalignment, plus the traced beam path."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    report = alignment.refresh_report(scene)
    rep_by = {r["name"]: r for r in report}

    elements, sources, detectors = [], [], []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        if op.is_source or op.element_type == 'SOURCE':
            sources.append(obj.name)
        if op.is_detector or op.element_type == 'DETECTOR':
            detectors.append(obj.name)
        ports = [{
            "name": p.name, "role": p.role,
            "world_pos": [round(x, 4) for x in geometry.world_port(obj, p.local_position)],
            "world_normal": [round(x, 4) for x in geometry.world_normal(obj, p.local_normal)],
            "clear_aperture": round(p.clear_aperture, 3),
        } for p in op.ports]
        dofs = [{
            "kind": d.kind, "axis": [round(x, 3) for x in d.axis_local],
            "pivot": [round(x, 3) for x in d.pivot_local],
            "min": round(d.min_val, 3), "max": round(d.max_val, 3),
            "current": round(d.current, 4),
        } for d in op.dofs]
        mech = [{"kind": l.kind, "target": l.target.name if l.target else None,
                 "state": l.state, "detail": l.detail} for l in op.mech]
        m = obj.matrix_world
        elements.append({
            "name": obj.name, "type": op.element_type,
            "world_center": [round(x, 4) for x in m.translation],
            "matrix_world": [[round(m[r][c], 6) for c in range(4)] for r in range(4)],
            "ports": ports,
            "mount": {"type": op.mount_type, "preset": op.mount_preset, "dofs": dofs},
            "mech": mech,
            "params": {
                "focal_length": round(op.focal_length, 4), "split_ratio": round(op.split_ratio, 4),
                "prism_angle": round(op.prism_angle, 3), "clear_aperture": round(op.clear_aperture, 3),
                "reflectivity": round(op.reflectivity, 3), "wavelength": round(op.wavelength, 3),
                "refractive_index": round(op.refractive_index, 4),
            },
            "misalignment": {"pos_err_mm": round(op.misalign_pos_mm, 4),
                             "ang_err_deg": round(op.misalign_ang_deg, 4),
                             "state": op.align_state, "detail": op.align_detail},
        })
    return {
        "units": "mm", "scale_length": scene.unit_settings.scale_length,
        "engine_eevee_id": _render.resolve_eevee_id(),
        "elements": elements, "sources": sources, "detectors": detectors,
        "beam_path": _beam_path_json(tracer.cached_segments), "report": report,
    }


def trace_beam(mode=None):
    scene = _scene()
    if mode:
        scene.optics.trace_mode = mode
    tracer.cached_segments = _trace(scene)
    return {"segments": len(tracer.cached_segments),
            "beam_path": _beam_path_json(tracer.cached_segments)}


def tag_element(name, element_type=None, auto_ports=True):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    obj.optics.is_optical = True
    if element_type:
        obj.optics.element_type = element_type
    if auto_ports:
        _ops.do_auto_detect(obj)
    return {"name": name, "type": obj.optics.element_type, "ports": len(obj.optics.ports)}


def set_mount(name, preset):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    ok, msg = mounts.apply_preset(obj, preset)
    return {"ok": ok, "msg": msg}


def align_element(name):
    scene = _scene()
    obj = scene.objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    res = alignment.align_element(scene, obj)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return res


def align_all():
    scene = _scene()
    res = alignment.align_all(scene)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return {"aligned": [{"name": n,
                         **{k: (round(v, 3) if isinstance(v, float) else v)
                            for k, v in r.items()}} for n, r in res]}


def check_mechanics():
    return {"worst": mounts.check_mechanics(_scene())}


def set_param(name, key, value):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    if not hasattr(obj.optics, key):
        return {"error": "no such param: %s" % key}
    # Only scalar/enum params are settable here; refuse pointers (anchor), collections
    # (ports/dofs/mech) and vectors (base_pose) so a remote/API call can't corrupt the
    # element's structure or trip an RNA type error deep in Blender.
    cur = getattr(obj.optics, key)
    if not isinstance(cur, (bool, int, float, str)):
        return {"error": "param '%s' is not a settable scalar" % key}
    try:
        setattr(obj.optics, key, value)
    except Exception as e:
        return {"error": "could not set %s=%r: %s" % (key, value, e)}
    return {"ok": True, "name": name, key: value}


def bake_beams(radius=0.6):
    return {"baked": _bake.bake_beams(bpy.context, radius=radius)}


def clear_beams():
    tracer.cached_segments = []
    return {"cleared": _bake.clear_baked(_scene())}


def render(preset='preview', camera='HERO', filepath=None):
    scene = _scene()
    _bake.ensure_beams(bpy.context)
    _render.set_camera(scene, camera.upper())
    if preset == 'final':
        _render.setup_final(scene)
    else:
        _render.setup_preview(scene)
    if filepath:
        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)
        return {"rendered": filepath, "engine": scene.render.engine}
    return {"configured": preset, "engine": scene.render.engine}


def build_example(kind='mach_zehnder'):
    """Build a canonical setup (mach_zehnder | michelson | hong_ou_mandel | bell)
    from generic components, then trace it."""
    from . import examples_builtin as ex
    if kind not in ex.EXAMPLES:
        return {"error": "unknown example '%s'; choose from %s" % (kind, list(ex.EXAMPLES))}
    name = ex.build(kind, bpy.context)
    res = trace_beam()
    return {"built": kind, "collection": name, "segments": res["segments"]}


def add_component(key, location=(0.0, 0.0, 0.0)):
    """Spawn a catalog component by key (or its generic mesh-free fallback). {name, msg}."""
    from . import library
    obj, msg = library.add_component(key, tuple(location))
    return {"name": obj.name if obj else None, "msg": msg}


def swap_part(name, filepath, refit_ports=False):
    """Replace element `name`'s mesh from an STL/OBJ (or STEP/IGES via FreeCAD), keeping
    its optical slot (ports / pose / mount / beam role). {ok, msg, name}."""
    import os
    from . import assembly
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    try:
        mesh_path, _entry = assembly._importable_path('FILE', "", filepath)
    except Exception as e:
        return {"error": str(e)}
    ok, msg = assembly.swap_mesh_on(obj, mesh_path, refit=refit_ports)
    if ok:
        obj.optics.part_key = os.path.basename(filepath)
        tracer.cached_segments = _trace(_scene())
    return {"ok": ok, "msg": msg, "name": name}


def place_relative(name, reference, axis='BEAM', distance=50.0, link=True, align_rotation=True):
    """Place element `name` a distance (mm) from `reference` along a chosen axis or the
    reference's OUT beam; link=True makes it follow the reference live. {ok, name}."""
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    bpy.context.view_layer.objects.active = obj
    res = bpy.ops.optics.place_relative(reference=reference, axis=axis, distance=distance,
                                        link=link, align_rotation=align_rotation, frame='REFERENCE')
    tracer.cached_segments = _trace(_scene())
    return {"ok": 'FINISHED' in res, "name": name, "reference": reference}


def scan(kind='STAGE', lo=0.0, hi=0.002, steps=120, element=None):
    """Sweep a parameter (STAGE OPD / WAVEPLATE angle / WAVELENGTH); writes a plot PNG +
    CSV to the temp dir and into the sensor window. Set `element` to the swept part."""
    if element:
        obj = _scene().objects.get(element)
        if obj:
            bpy.context.view_layer.objects.active = obj
    res = bpy.ops.optics.scan(kind=kind, lo=lo, hi=hi, steps=steps)
    return {"ok": 'FINISHED' in res, "kind": kind, "steps": steps}


def ao_measure(sensor):
    """Read the residual Zernike wavefront error (waves) at a wavefront sensor. {zernike, rms}."""
    from . import ao, physics
    tracer.cached_segments = _trace(_scene())
    c = ao._aberr_at(tracer.cached_segments, sensor)
    if c is None:
        return {"error": "no beam at wavefront sensor '%s'" % sensor}
    return {"sensor": sensor, "zernike": [round(x, 4) for x in c],
            "rms": round(physics.wavefront_rms(c), 4)}


def get_wavefront(sensor):
    """Alias of ao_measure: a wavefront sensor's reconstructed wavefront (Zernike + RMS)."""
    return ao_measure(sensor)


def ao_command(dm, coeffs):
    """Set a deformable mirror's command (Zernike coeffs, in waves). {ok, dm, command}."""
    obj = _scene().objects.get(dm)
    if not obj:
        return {"error": "object not found: %s" % dm}
    cmd = list(obj.optics.dm_command)
    for i in range(min(len(cmd), len(coeffs))):
        cmd[i] = float(coeffs[i])
    obj.optics.dm_command = cmd
    return {"ok": True, "dm": dm, "command": cmd}


def ao_close_loop(sensor, dm, gain=0.5, iters=15):
    """Close the modal adaptive-optics loop (sensor -> deformable-mirror integrator). Returns
    the RMS history in waves (open-loop first, corrected last)."""
    from . import ao
    hist = ao.close_loop(_scene(), sensor, dm, gain, iters)
    if not hist:
        return {"error": "need a wavefront sensor + deformable mirror with a beam between them"}
    return {"ok": True, "rms_history": [round(x, 4) for x in hist],
            "rms_initial": round(hist[0], 4), "rms_final": round(hist[-1], 4)}


def export_svg(filepath):
    """Export a top-view 2-D vector (SVG) schematic of the optical layout + beam path to filepath
    (a publication figure: element glyphs, port ticks, wavelength-coloured beams). {ok, path, ...}."""
    from . import svg_export
    return svg_export.export_svg(filepath)


def beam_profile(detector="", samples=24):
    """Gaussian spot radius w(z) along the beam path source -> `detector` (or the active/most-lit
    one): waist {z_mm, w_mm}, element positions + clear apertures, sampled z/w arrays, and a plot
    PNG + CSV in the temp dir. The core laser-bench design readout (where is the waist, does the
    mode fit the apertures, mode-matching into a cavity)."""
    from . import scan
    data = scan.beam_profile_plot(_scene(), detector, samples)
    if data is None:
        return {"error": "no Gaussian beam reaches a detector"}
    data["ok"] = True
    return data
