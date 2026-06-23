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
from . import diagnostics as _diagnostics
from . import optomech as _optomech
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
            "mount": {"type": op.mount_type, "preset": op.mount_preset, "dofs": dofs,
                      "support_system": getattr(op, "support_system", 'POST')},
            # the one genuine pose-dependency edge: which element this one follows (place_relative)
            "anchor": op.anchor.name if getattr(op, "anchor", None) else None,
            "base_pose_set": bool(getattr(op, "base_pose_set", False)),
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
        # Bench breadboard grid (pitch/origin/extent + occupied holes) so an MCP agent or a
        # human knows exactly where parts seat. None when the bench is not dressed.
        "bench": _optomech.grid_info(scene),
        # Cage assemblies (16/30/60 mm): which optics share rods, the cage axis + rod length.
        "cages": _optomech.cage_info(scene),
        # Lens-tube assemblies (SM05/SM1/SM2): which optics share a barrel, thread + bore + length.
        "tubes": _optomech.tube_info(scene),
        # Rail assemblies (dovetail): which optics ride one rail, the axis + each carrier's position.
        "rails": _optomech.rail_info(scene),
        # Geometric validation: physical-invariant violations on the dressed bench (mount below its
        # holder, colliding posts). Empty == valid. The agent's programmatic check on the assembly.
        "warnings": _optomech.validate(scene),
        # Wave-1 beam-physics error detection (A1-A5): beam_clipped / vignetting / dark_detector /
        # orphan_source / energy_violation / mount_limit, each {kind, element, detail, severity}.
        # READ-ONLY post-pass over the SAME cached trace above -- the beam path is unaffected.
        "diagnostics": _diagnostics.run_diagnostics(scene),
    }


def trace_beam(mode=None):
    scene = _scene()
    if mode:
        try:
            scene.optics.trace_mode = mode      # EnumProperty: a bad string would raise a TypeError
        except (TypeError, ValueError) as e:
            return {"error": "invalid trace mode '%s': %s" % (mode, e)}
    tracer.cached_segments = _trace(scene)
    return {"segments": len(tracer.cached_segments),
            "beam_path": _beam_path_json(tracer.cached_segments)}


def diagnose():
    """Run the Wave-1 P0 bench-intelligence error-detection gates (A1-A5) over the
    current trace: beam_clipped (hard miss), vignetting (Gaussian wing clip),
    dark_detector / orphan_source, energy_violation (per-node + global budget), and
    mount_limit (DOF range exhaustion). READ-ONLY -- the trace is unaffected.
    Returns {ok, diagnostics:[{kind, element, detail, severity}], counts:{BAD,WARN}}."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    diags = _diagnostics.run_diagnostics(scene)
    bad = sum(1 for d in diags if d.get("severity") == 'BAD')
    warn = sum(1 for d in diags if d.get("severity") == 'WARN')
    return {"ok": True, "diagnostics": diags, "counts": {"BAD": bad, "WARN": warn}}


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


def render_sequence(frames=48, motion='ORBIT', out_dir=None, engine='EEVEE',
                    turns=1.0, elevation=0.55, encode='auto', fps=24):
    """Render a camera-orbit PNG sequence of the current setup (headless animation pipeline) and,
    if ffmpeg is present, encode an mp4 (best-effort; the PNG sequence is always produced). Bakes
    the beam first so it shows. Returns {frames, dir, pattern, ffmpeg, video}."""
    from . import anim
    scene = _scene()
    _bake.ensure_beams(bpy.context)
    return anim.render_sequence(scene, frames=frames, motion=motion, out_dir=out_dir,
                                engine=engine, turns=turns, elevation=elevation,
                                encode=encode, fps=fps)


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
    """Build a canonical setup (one of the 14 builders in examples_builtin.EXAMPLES: mach_zehnder,
    michelson, hong_ou_mandel, bell, adaptive_optics, newton_rings, periscope, cage_system, tube_system,
    rail_system, hybrid_system, microscope, dhm, aom) from generic components, then trace it."""
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
    if obj is None:                             # unknown key -> a real error, not a {name: None} success
        return {"error": msg}
    return {"name": obj.name, "msg": msg}


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
    try:                                        # import is the failure-prone step (corrupt/empty file)
        ok, msg = assembly.swap_mesh_on(obj, mesh_path, refit=refit_ports)
    except (RuntimeError, OSError) as e:
        return {"error": "swap failed: %s" % e}
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
    if not (getattr(obj, "optics", None) and obj.optics.is_optical):
        return {"error": "'%s' is not an optical element (tag it first)" % name}
    if _scene().objects.get(reference) is None:
        return {"error": "reference not found: %s" % reference}
    bpy.context.view_layer.objects.active = obj
    try:
        res = bpy.ops.optics.place_relative(reference=reference, axis=axis, distance=distance,
                                            link=link, align_rotation=align_rotation, frame='REFERENCE')
    except (RuntimeError, TypeError) as e:     # bad axis enum / poll failure -> structured error
        return {"error": "place_relative: %s" % e}
    tracer.cached_segments = _trace(_scene())
    if 'FINISHED' not in res:
        return {"error": "place_relative cancelled (BEAM axis needs an OUT port on the reference?)"}
    return {"ok": True, "name": name, "reference": reference}


def set_grid(pitch_mm=None, standard=None):
    """Set the breadboard hole-grid standard/pitch. `standard` in {METRIC (25 mm/M6),
    IMPERIAL (1"/1/4-20), CUSTOM}; `pitch_mm` sets a custom pitch (implies CUSTOM). Re-dresses
    the bench if it is currently dressed so the new grid takes effect. Returns the active grid."""
    scene = _scene()
    op = scene.optics
    if standard is not None:
        std = str(standard).upper()
        if std not in ('METRIC', 'IMPERIAL', 'CUSTOM'):
            return {"error": "standard must be METRIC, IMPERIAL or CUSTOM (got %r)" % standard}
        op.bench_grid_units = std
    if pitch_mm is not None:
        try:
            p = float(pitch_mm)
        except (TypeError, ValueError):
            return {"error": "pitch_mm must be a number (got %r)" % pitch_mm}
        if p < 1.0:
            return {"error": "pitch_mm must be >= 1.0 mm (got %s)" % pitch_mm}
        op.bench_grid_units = 'CUSTOM'
        op.bench_grid_mm = p
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    return {"ok": True, "standard": op.bench_grid_units, "pitch_mm": round(op.bench_grid_mm, 4),
            "bench": _optomech.grid_info(scene)}


def dress_bench(enable=True):
    """Spawn (enable=True) or remove (enable=False) the procedural breadboard + posts + pedestals
    + mount rings. The grid is then exposed via get_state()['bench']. Trace is unaffected (optics
    are not moved). Returns the object count and the grid."""
    scene = _scene()
    if enable:
        n = _optomech.dress(scene)
        if n == 0:
            return {"error": "no optical elements to dress (build or tag elements first)"}
        return {"ok": True, "dressed": True, "objects": n, "bench": _optomech.grid_info(scene)}
    _optomech.strip(scene)
    return {"ok": True, "dressed": False}


def place_on_grid(name, col, row, link_drop=True):
    """Move optical element `name` so it sits over breadboard hole (col, row), keeping its z
    height and orientation. This is grid-aware placement for building a layout (it DOES move the
    part, so the trace updates). The bench must be dressed first (the grid origin comes from the
    current dressing). Use get_state()['bench'] to read available holes. Returns the new center."""
    scene = _scene()
    obj = scene.objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    if not (getattr(obj, "optics", None) and obj.optics.is_optical):
        return {"error": "'%s' is not an optical element (tag it first)" % name}
    if not _optomech.is_dressed(scene):
        return {"error": "bench is not dressed -- call dress_bench() first so the grid is defined"}
    try:
        col = int(col); row = int(row)
    except (TypeError, ValueError):
        return {"error": "col and row must be integers"}
    xy = _optomech.hole_world_xy(scene, col, row)
    if xy is None:
        gi = _optomech.grid_info(scene)
        return {"error": "hole (%d,%d) out of range 0..%d x 0..%d" % (col, row, gi["cols"] - 1, gi["rows"] - 1)}
    # capture the element's mount base if it has one, then move XY (preserve z + orientation)
    obj.location.x += xy[0] - obj.matrix_world.translation.x
    obj.location.y += xy[1] - obj.matrix_world.translation.y
    bpy.context.view_layer.update()
    if link_drop:
        _optomech.dress(scene)   # re-seat posts/pedestals under the moved part
    tracer.cached_segments = _trace(scene)
    m = obj.matrix_world
    return {"ok": True, "name": name, "hole": [col, row],
            "world_center": [round(x, 4) for x in m.translation]}


def make_cage(members, size_mm=30, cage_id=None):
    """Group collinear optical elements into a cage assembly: they share 4 rods (Ø6 mm on a 30 mm
    square for SM1, etc.) and one cage post instead of an individual post each. `members` is a list
    of element names; `size_mm` in {16, 30, 60}. Re-dresses if the bench is dressed. The cage
    layout is exposed in get_state()['cages']. Does NOT move the optics, so the trace is unchanged."""
    scene = _scene()
    sysmap = {16: 'CAGE_16', 30: 'CAGE_30', 60: 'CAGE_60'}
    try:
        size = int(size_mm)
    except (TypeError, ValueError):
        return {"error": "size_mm must be 16, 30 or 60"}
    if size not in sysmap:
        return {"error": "size_mm must be 16, 30 or 60 (got %s)" % size_mm}
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    cid = cage_id or ("cage_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = sysmap[size]
        o.optics.cage_id = cid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "cage_id": cid, "size_mm": size, "members": [o.name for o in objs],
            "cages": _optomech.cage_info(scene)}


def make_tube(members, thread='SM1', tube_id=None):
    """Stack collinear in-line optics into one SM lens-tube barrel (they share one barrel + one post
    instead of an individual post each). `members` is a list of element names; `thread` in
    {SM05, SM1, SM2} (Ø1/2", Ø1", Ø2" optics). The tube is exposed in get_state()['tubes']. Does NOT
    move the optics, so the trace is unchanged."""
    scene = _scene()
    sysmap = {'SM05': 'TUBE_SM05', 'SM1': 'TUBE_SM1', 'SM2': 'TUBE_SM2'}
    key = str(thread).upper()
    if key not in sysmap:
        return {"error": "thread must be SM05, SM1 or SM2 (got %r)" % thread}
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    tid = tube_id or ("tube_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = sysmap[key]
        o.optics.tube_id = tid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "tube_id": tid, "thread": key, "members": [o.name for o in objs],
            "tubes": _optomech.tube_info(scene)}


def make_rail(members, rail_id=None):
    """Put collinear elements on one dovetail rail: each rides a carrier on the shared rail (instead
    of a bare post on the board), so they translate along one straight track. `members` is a list of
    element names. Exposed in get_state()['rails'] (carrier positions in s_mm). Does NOT move the
    optics, so the trace is unchanged. Use place_on_rail(name, s_mm) to slide one along the rail."""
    scene = _scene()
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    rid = rail_id or ("rail_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = 'RAIL'
        o.optics.rail_id = rid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "rail_id": rid, "members": [o.name for o in objs],
            "rails": _optomech.rail_info(scene)}


def place_on_rail(name, s_mm):
    """Slide rail-mounted element `name` to position s_mm along its rail (s=0 at the rail start).
    Moves the optic along the rail axis only, so the trace updates. The element must be on a rail
    (make_rail first). Read get_state()['rails'] for the current carrier positions."""
    scene = _scene()
    o = scene.objects.get(name)
    if not o:
        return {"error": "object not found: %s" % name}
    if getattr(o.optics, "support_system", 'POST') != 'RAIL':
        return {"error": "'%s' is not on a rail (call make_rail first)" % name}
    try:
        s = float(s_mm)
    except (TypeError, ValueError):
        return {"error": "s_mm must be a number"}
    members = _optomech.rail_groups(scene).get(getattr(o.optics, "rail_id", "") or "", [o])
    ax, cxy, ts = _optomech.rail_geom(members)
    start = cxy + ax * min(ts)                       # s = 0 reference
    target = start + ax * s
    cur = o.matrix_world.translation
    o.location.x += target.x - cur.x
    o.location.y += target.y - cur.y
    bpy.context.view_layer.update()
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    m = o.matrix_world
    return {"ok": True, "name": name, "s_mm": round(s, 3),
            "world_center": [round(x, 4) for x in m.translation]}


def scan(kind='STAGE', lo=0.0, hi=0.002, steps=120, element=None):
    """Sweep a parameter (STAGE OPD / WAVEPLATE angle / WAVELENGTH); writes a plot PNG +
    CSV to the temp dir and into the sensor window. Set `element` to the swept part."""
    if element:
        obj = _scene().objects.get(element)
        if obj is None:
            return {"error": "element not found: %s" % element}
        bpy.context.view_layer.objects.active = obj
    try:
        res = bpy.ops.optics.scan(kind=kind, lo=lo, hi=hi, steps=steps)
    except (RuntimeError, TypeError) as e:     # bad kind enum / poll failure -> structured error
        return {"error": "scan: %s" % e}
    if 'FINISHED' not in res:
        return {"error": "scan cancelled (no detectors, or the active element lacks the swept knob?)"}
    return {"ok": True, "kind": kind, "steps": steps}


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
    try:
        coeffs = [float(c) for c in coeffs]    # reject non-numeric / non-sequence cleanly
    except (TypeError, ValueError) as e:
        return {"error": "coeffs must be a numeric sequence: %s" % e}
    cmd = list(obj.optics.dm_command)
    for i in range(min(len(cmd), len(coeffs))):
        cmd[i] = coeffs[i]
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
    try:
        return svg_export.export_svg(filepath)
    except (OSError, RuntimeError) as e:        # match the operator's clean error shape
        return {"error": "svg export failed: %s" % e}


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
