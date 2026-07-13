"""Per-mount 3D inspection renders + numeric gap analysis.

One mount per mini-bench, 5 CLOSE camera angles each, plus a report.json with per-part
nearest-neighbour gaps (floating-part detector). Wide showcase shots hide per-mount structural
errors (lesson learned twice now) -- this tool exists so every mount is judged ALONE, up close,
from multiple directions, by a human eye plus numbers.

Run:  Blender --background --factory-startup --python tools/inspect_mounts.py -- <outdir> [case ...]
With no case names, all cases render. Case list: see CASES below.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector

VIEWS = [  # direction the camera LOOKS ALONG (world), name
    ((-1.0, 1.0, -0.45), "01_three_quarter_front"),
    ((1.0, 1.0, -0.45), "02_three_quarter_back"),
    ((0.0, 1.0, -0.08), "03_side"),
    ((-1.0, 0.15, -0.10), "04_axial"),
    ((0.0, 0.35, -1.0), "05_top"),
]


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise RuntimeError("usage: --python tools/inspect_mounts.py -- <outdir> [case ...]")
    return argv[0], argv[1:]


def _clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def _cluster_objects():
    """Everything that belongs to the mount cluster: all meshes except the breadboard."""
    out = []
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        if "Breadboard" in ob.name:
            continue
        out.append(ob)
    return out


def _bbox(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in objs:
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo.x, lo.y, lo.z = min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)
            hi.x, hi.y, hi.z = max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)
    return lo, hi


def _gap_report(objs):
    """Per part: 0.0 if its faces OVERLAP another part's (true contact/intersection, same test the
    collision gate uses), else the min vertex->surface distance in BOTH directions. Vertex-only
    sampling ALONE is a false-positive machine for long parts -- a cylinder's vertices sit at the
    two end caps, so a rod threaded through a plate 'measured' 22.5 mm of gap."""
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    trees = {}
    for ob in objs:
        if abs(ob.matrix_world.determinant()) < 1e-12:
            continue
        try:
            # world-space tree so overlap() compares real poses
            bm_verts = [ob.matrix_world @ v.co for v in ob.data.vertices]
            polys = [tuple(p.vertices) for p in ob.data.polygons]
            trees[ob.name] = BVHTree.FromPolygons(bm_verts, polys)
        except Exception:
            pass

    def vmin(a, b):
        verts = a.data.vertices
        step = max(1, len(verts) // 120)
        tree = trees[b.name]
        best = None
        for i in range(0, len(verts), step):
            w = a.matrix_world @ verts[i].co
            hit = tree.find_nearest(w)
            if hit and hit[0] is not None:
                d = (hit[0] - w).length
                if best is None or d < best:
                    best = d
        return best

    report = {}
    for ob in objs:
        if ob.name not in trees:
            report[ob.name] = {"min_gap_mm": None, "nearest": None, "DEGENERATE_MATRIX": True}
            continue
        best, best_other = None, None
        for other in objs:
            if other is ob or other.name not in trees:
                continue
            if trees[ob.name].overlap(trees[other.name]):
                best, best_other = 0.0, other.name
                break
            cands = [d for d in (vmin(ob, other), vmin(other, ob)) if d is not None]
            if cands:
                d = min(cands)
                if best is None or d < best:
                    best, best_other = d, other.name
        report[ob.name] = {"min_gap_mm": round(best, 3) if best is not None else None,
                           "nearest": best_other}
    return report


def _render_case(tag, build, outdir):
    from optical_alignment_sim import optomech, render as oa_render
    _clear_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    build()                                            # creates element(s) + presets
    bpy.context.view_layer.update()
    optomech.dress(scene)
    bpy.context.view_layer.update()

    case_dir = os.path.join(outdir, tag)
    os.makedirs(case_dir, exist_ok=True)
    objs = _cluster_objects()
    # frame the MOUNT, not the whole chain: board/post/holder dominate the bbox and shrink the
    # part under judgment to a smudge (the side view keeps the full chain for context)
    chain = ("Post", "Holder", "Base", "Foot", "Holes", "Lockh", "Locks")
    mount_objs = [o for o in objs if not any(k in o.name for k in chain)] or objs
    lo, hi = _bbox(mount_objs)
    center = (lo + hi) * 0.5
    diag = max((hi - lo).length, 40.0)
    lo_all, hi_all = _bbox(objs)
    center_all = (lo_all + hi_all) * 0.5
    diag_all = (hi_all - lo_all).length

    cam_data = bpy.data.cameras.new("InspectCam")
    cam = bpy.data.objects.new("InspectCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam_data.lens = 55.0
    cam_data.clip_end = 10000.0

    oa_render.setup_final(scene)
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'

    fill_data = bpy.data.lights.new("InspectFill", 'SUN')
    fill_data.energy = 2.0
    fill = bpy.data.objects.new("InspectFill", fill_data)
    scene.collection.objects.link(fill)
    for direction, vname in VIEWS:
        d = Vector(direction).normalized()
        if vname == "03_side":                 # the one wide view: whole support chain in frame
            cam.location = center_all - d * diag_all * 1.05
        else:
            cam.location = center - d * diag * 1.35
        cam.rotation_euler = (-d).to_track_quat('Z', 'Y').to_euler()
        # headlight-style fill so every view is judgeable, not a silhouette
        fill.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = os.path.join(case_dir, vname + ".png")
        bpy.ops.render.render(write_still=True)

    rep = {"case": tag, "n_parts": len(objs), "bbox_mm": [round(x, 1) for x in (hi - lo)],
           "parts": _gap_report(objs)}
    with open(os.path.join(case_dir, "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    print("INSPECT_DONE %s parts=%d" % (tag, len(objs)))
    return rep


def main():
    outdir, only = _args()
    import optical_alignment_sim as addon
    addon.register()
    from optical_alignment_sim import elements_generic as G, mounts, optics_api

    X = Vector((1.0, 0.0, 0.0))
    Y = Vector((0.0, 1.0, 0.0))
    Z = 100.0

    def _coll():
        return G.example_collection("MountInspect")

    def _preset(ob, preset):
        ok, msg = mounts.apply_preset(ob, preset)
        if not ok:
            raise RuntimeError("%s: %s" % (preset, msg))
        return ob

    CASES = {
        "KM100":      lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'KM100'),
        "KM100CPM":   lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'KM100CP/M'),
        "KS1":        lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'KS1'),
        "POLARIS":    lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'POLARIS-K1'),
        "EO15866":    lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'EO-15866'),
        "GM100":      lambda: _preset(G.mirror("MI_M", (0, 0, Z), X, Y, _coll()), 'GM100'),
        "RSP1":       lambda: _preset(G.waveplate("MI_WP", (0, 0, Z), X, _coll()), 'RSP1'),
        "TRF90_0":    lambda: _preset(G.window("MI_W", (0, 0, Z), X, _coll(), radius=12.0), 'TRF90'),
        "TRF90_90":   lambda: (lambda ob: (setattr(ob.optics.dofs[0], 'current', 90.0), ob)[1])(
                          _preset(G.window("MI_W", (0, 0, Z), X, _coll(), radius=12.0), 'TRF90')),
        "VC1":        lambda: _preset(G.source("MI_L", (0, 0, Z), X, _coll(), radius=12.7), 'VC1'),
        "LMR":        lambda: G.lens("MI_LENS", (0, 0, Z), X, _coll(), focal=150.0),
        "CAMERA":     lambda: G.detector("MI_CAM", (0, 0, Z), X, _coll(), size=35.0),
        "SOURCE":     lambda: G.source("MI_SRC", (0, 0, Z), X, _coll(), radius=12.7),
        "XSTAGE":     lambda: (lambda ob: (setattr(ob.optics, 'mount_type', 'TRANSLATION'), ob)[1])(
                          G.lens("MI_XS", (0, 0, Z), X, _coll(), focal=100.0)),
        "CAGE30":     lambda: (lambda ob: (setattr(ob.optics, 'support_system', 'CAGE_30'),
                                           setattr(ob.optics, 'cage_id', 'insp'), ob)[1])(
                          G.lens("MI_CL", (0, 0, Z), X, _coll(), focal=150.0)),
        "RAIL_RLA":   lambda: (lambda ob: (optics_api.make_rail([ob.name], rail_id='insp_rla'), ob)[1])(
                          G.lens("MI_RL", (0, 0, Z), X, _coll(), focal=200.0)),
        "RAIL_X95":   lambda: (lambda ob: (optics_api.make_rail([ob.name], rail_id='insp_x95',
                                                                family='X95'), ob)[1])(
                          G.lens("MI_XL", (0, 0, Z), X, _coll(), focal=250.0)),
    }

    todo = only or list(CASES)
    unknown = [t for t in todo if t not in CASES]
    if unknown:
        raise RuntimeError("unknown case(s): %s; valid: %s" % (unknown, ", ".join(CASES)))
    for tag in todo:
        _render_case(tag, CASES[tag], outdir)
    print("ALL_CASES_DONE %d" % len(todo))


main()
