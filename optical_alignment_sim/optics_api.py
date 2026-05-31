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
    setattr(obj.optics, key, value)
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
    name = ex.EXAMPLES[kind][1](bpy.context)
    res = trace_beam()
    return {"built": kind, "collection": name, "segments": res["segments"]}
