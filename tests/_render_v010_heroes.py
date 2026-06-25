"""DEFERRED hero renders for the v0.10.0 feature set — READY TO RUN, not executed in this cycle.

The owner asked to PREPARE every visual option but hold the Cycles renders for now ("şimdilik render
alma"). This script sets up three photorealistic hero benches for the new features and renders them with
the same studio look as docs/img/hero.png. Run it when you want the renders:

    blender --background --factory-startup --python tests/_render_v010_heroes.py

It writes docs/img/die-hero.png, docs/img/dichroic-hero.png, docs/img/polcam-hero.png. These are NOT
referenced by the README yet — wire them in (or swap them against the matplotlib feature plots) after you
have eye-approved them. Cycles on the M4 GPU is slow and can stall on sleep/contention, so render one at a
time if needed (comment out the others).
"""
import bpy, sys, os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import optical_alignment_sim as oas
oas.register()
import optics_api
from optical_alignment_sim import elements_generic as eg
from mathutils import Vector

IMG = os.path.join(REPO, "docs", "img")
SAMPLES = 96            # bump to 256+ for a final; 96 is a fast preview-quality hero
RES = (1280, 720)


def _render(filepath):
    optics_api.bake_beams()
    optics_api.render(preset="final", camera="HERO", filepath=filepath)
    print("RENDERED", filepath)


def hero_die():
    optics_api.build_example("die")                 # collimated beam -> die-face reflector -> WFS
    _render(os.path.join(IMG, "die-hero.png"))


def hero_dichroic():
    sc = bpy.context.scene
    for o in list(sc.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = eg.example_collection("DichroicHero")
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    s = eg.source("DH_S", (-150, 0, 0), X, c, wavelength=520.0)   # green -> reflects on a 650 LP dichroic
    s.optics.bandwidth_nm = 240.0                                  # broadband so the split shows by colour
    d = eg.dichroic("DH_DI", (0, 0, 0), X, Y, c, cut_nm=650.0, pass_type='LP')
    d.optics.edge_width = 25.0
    eg.detector("DH_T", (150, 0, 0), X, c)                         # long-λ transmitted
    eg.detector("DH_R", (0, 150, 0), Y, c)                         # short-λ reflected
    bpy.context.view_layer.update()
    _render(os.path.join(IMG, "dichroic-hero.png"))


def hero_polcam():
    sc = bpy.context.scene
    for o in list(sc.objects):
        if getattr(getattr(o, "optics", None), "is_optical", False):
            bpy.data.objects.remove(o, do_unlink=True)
    c = eg.example_collection("PolCamHero")
    X = Vector((1, 0, 0))
    s = eg.source("PCH_S", (-150, 0, 0), X, c)
    s.optics.pol_angle = 30.0
    eg.waveplate("PCH_QWP", (-20, 0, 0), X, c)                     # make it elliptical for a richer DoLP/AoLP
    d = eg.detector("PCH_CAM", (150, 0, 0), X, c, size=30.0)
    d.optics.readout_topology = 'POL_CAMERA'
    bpy.context.view_layer.update()
    _render(os.path.join(IMG, "polcam-hero.png"))


if __name__ == "__main__":
    bpy.context.scene.cycles.samples = SAMPLES
    bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = RES
    hero_die()
    hero_dichroic()
    hero_polcam()
    print("DONE — 3 hero renders in docs/img/ (die-hero, dichroic-hero, polcam-hero)")
