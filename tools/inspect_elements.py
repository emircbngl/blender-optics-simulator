"""Per-ELEMENT 3D inspection renders + mesh-health report (companion to inspect_mounts.py).

Each optical element builder renders ALONE (no bench, no dress): 5 close camera angles + a
report.json with mesh statistics (dimensions, vert/face counts, non-manifold edge count). The
element mesh itself is under judgment here -- does a lens read as a lens, a prism as a prism.

Run:  Blender --background --factory-startup --python tools/inspect_elements.py -- <outdir> [case ...]
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy
from mathutils import Vector

VIEWS = [
    ((-1.0, 1.0, -0.45), "01_three_quarter_front"),
    ((1.0, 1.0, -0.45), "02_three_quarter_back"),
    ((0.0, 1.0, -0.08), "03_side"),
    ((-1.0, 0.15, -0.10), "04_axial"),
    ((0.0, 0.35, -1.0), "05_top"),
]


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise RuntimeError("usage: --python tools/inspect_elements.py -- <outdir> [case ...]")
    return argv[0], argv[1:]


def _clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def _bbox(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in objs:
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo.x, lo.y, lo.z = min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)
            hi.x, hi.y, hi.z = max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)
    return lo, hi


def _mesh_health(ob):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    loose_verts = sum(1 for v in bm.verts if not v.link_edges)
    bm.free()
    return {"verts": len(ob.data.vertices), "faces": len(ob.data.polygons),
            "non_manifold_edges": non_manifold, "loose_verts": loose_verts,
            "materials": [m.name if m else None for m in ob.data.materials]}


def _render_case(tag, build, outdir):
    from optical_alignment_sim import render as oa_render
    _clear_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    obj = build()
    bpy.context.view_layer.update()

    case_dir = os.path.join(outdir, tag)
    os.makedirs(case_dir, exist_ok=True)
    objs = [o for o in bpy.data.objects if o.type == 'MESH']
    lo, hi = _bbox(objs)
    center = (lo + hi) * 0.5
    diag = max((hi - lo).length, 25.0)

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
    fill_data.energy = 2.5
    fill = bpy.data.objects.new("InspectFill", fill_data)
    scene.collection.objects.link(fill)
    for direction, vname in VIEWS:
        d = Vector(direction).normalized()
        cam.location = center - d * diag * 1.5
        cam.rotation_euler = (-d).to_track_quat('Z', 'Y').to_euler()
        fill.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = os.path.join(case_dir, vname + ".png")
        bpy.ops.render.render(write_still=True)

    rep = {"case": tag, "bbox_mm": [round(x, 1) for x in (hi - lo)],
           "objects": {o.name: _mesh_health(o) for o in objs}}
    with open(os.path.join(case_dir, "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    print("INSPECT_DONE %s" % tag)
    return rep


def main():
    outdir, only = _args()
    import optical_alignment_sim as addon
    addon.register()
    from optical_alignment_sim import elements_generic as G

    X = Vector((1.0, 0.0, 0.0))
    Y = Vector((0.0, 1.0, 0.0))
    P = (0.0, 0.0, 100.0)

    def _c():
        return G.example_collection("ElemInspect")

    CASES = {
        "source":           lambda: G.source("EL", P, X, _c()),
        "mirror":           lambda: G.mirror("EL", P, X, Y, _c()),
        "beamsplitter":     lambda: G.beamsplitter("EL", P, X, Y, _c()),
        "detector":         lambda: G.detector("EL", P, X, _c()),
        "lens":             lambda: G.lens("EL", P, X, _c(), focal=100.0),
        "window":           lambda: G.window("EL", P, X, _c()),
        "waveplate":        lambda: G.waveplate("EL", P, X, _c()),
        "aperture":         lambda: G.aperture("EL", P, X, _c()),
        "crystal":          lambda: G.crystal("EL", P, X, _c()),
        "objective":        lambda: G.objective("EL", P, X, _c()),
        "aom":              lambda: G.aom("EL", P, X, _c()),
        "prism":            lambda: G.prism("EL", P, X, _c()),
        "polarizer":        lambda: G.polarizer("EL", P, X, _c()),
        "optical_filter":   lambda: G.optical_filter("EL", P, X, _c()),
        "pinhole":          lambda: G.pinhole("EL", P, X, _c()),
        "slit":             lambda: G.slit("EL", P, X, _c()),
        "knife_edge":       lambda: G.knife_edge("EL", P, X, _c()),
        "beam_dump":        lambda: G.beam_dump("EL", P, X, _c()),
        "isolator":         lambda: G.isolator("EL", P, X, _c()),
        "circulator":       lambda: G.circulator("EL", P, X, _c()),
        "fiber_collimator": lambda: G.fiber_collimator("EL", P, X, _c()),
        "photodiode":       lambda: G.photodiode("EL", P, X, _c()),
        "power_meter":      lambda: G.power_meter("EL", P, X, _c()),
        "dichroic":         lambda: G.dichroic("EL", P, X, Y, _c()),
        "grating":          lambda: G.grating("EL", P, X, Y, _c()),
        "retroreflector":   lambda: G.retroreflector("EL", P, X, _c()),
        "cavity":           lambda: G.cavity("EL", P, X, _c()),
        "wavefront_sensor": lambda: G.wavefront_sensor("EL", P, X, _c()),
        "deformable_mirror": lambda: G.deformable_mirror("EL", P, X, Y, _c()),
        "aberrator":        lambda: G.aberrator("EL", P, X, _c()),
    }
    todo = only or list(CASES)
    unknown = [t for t in todo if t not in CASES]
    if unknown:
        raise RuntimeError("unknown case(s): %s" % unknown)
    for tag in todo:
        _render_case(tag, CASES[tag], outdir)
    print("ALL_CASES_DONE %d" % len(todo))


main()
