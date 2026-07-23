"""Mesh-health gate: every element mesh + every dressed mount cluster, render-free.

Born from the 2026-07-14 mount audit: wide showcase renders can hide a mount whose base
floats clear off the board. The numeric part of that audit lives here so it runs in CI on
every push:

  * ELEMENTS -- all builder cases from tools/inspect_elements.py, built bare: zero
    non-manifold-edge REGRESSIONS and zero loose vertices per mesh.
  * MOUNTS -- all dressed cases from tools/inspect_mounts.py: no degenerate part matrices,
    and every hardware part in contact with its cluster (BVH face-overlap or a vertex gap
    below GAP_TOL). Bench furniture (Foot_*, Holes) legitimately sits apart and is exempt.

No renders here (headless EEVEE aborts in CI; Cycles is minutes/frame) -- close-up render inspection stays
a release-time step with the two inspect tools. This gate only proves nothing REGRESSED
structurally.

Run:  Blender --background --factory-startup --python-exit-code 1 --python tests/test_mesh_health.py
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy

FURNITURE = ("Foot_", "Holes")


def _load_tool(relpath, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


IE = _load_tool(os.path.join("tools", "inspect_elements.py"), "oa_inspect_elements")
IM = _load_tool(os.path.join("tools", "inspect_mounts.py"), "oa_inspect_mounts")

import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G, mounts, optics_api, optomech

fails = []


def _scene_units():
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    return scene


# ---- leg 1: bare element meshes -------------------------------------------------------
n_meshes = 0
for tag, build in IE.element_cases(G).items():
    IE._clear_scene()
    _scene_units()
    build()
    bpy.context.view_layer.update()
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        h = IE._mesh_health(ob)
        n_meshes += 1
        if h["loose_verts"]:
            fails.append("element %s / %s: %d loose verts" % (tag, ob.name, h["loose_verts"]))
        if h["non_manifold_edges"]:
            fails.append("element %s / %s: %d non-manifold edges (baseline is 0 for every "
                         "element)" % (tag, ob.name, h["non_manifold_edges"]))
print("elements: %d meshes checked" % n_meshes)

# ---- leg 2: dressed mount clusters ----------------------------------------------------
n_parts = 0
for tag, build in IM.mount_cases(G, mounts, optics_api).items():
    IM._clear_scene()
    scene = _scene_units()
    build()
    bpy.context.view_layer.update()
    optomech.dress(scene)
    bpy.context.view_layer.update()
    report = IM._gap_report(IM._cluster_objects())
    for name, h in report.items():
        n_parts += 1
        if h.get("DEGENERATE_MATRIX"):
            fails.append("mount %s / %s: DEGENERATE matrix" % (tag, name))
            continue
        gap = h.get("min_gap_mm")
        if gap is None:
            continue                       # single-part cluster: nothing to be adjacent to
        if any(k in name for k in FURNITURE):
            continue                       # bench furniture legitimately sits apart
        if gap > optomech.GAP_TOL:
            fails.append("mount %s / %s: floating, min gap %.2f mm to %s (tol %.1f)"
                         % (tag, name, gap, h.get("nearest"), optomech.GAP_TOL))
print("mounts: %d parts checked" % n_parts)

if fails:
    for f in fails:
        print("FAIL " + f)
    raise SystemExit("MESH HEALTH FAIL (%d)" % len(fails))
print("MESH HEALTH PASS  (%d element meshes, %d mount parts)" % (n_meshes, n_parts))
