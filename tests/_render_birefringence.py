"""Render docs/img/birefringence-double-refraction-render.png -- a Cycles view of TRUE o/e double refraction.

A single beam enters a calcite block (optic axis cut 45 deg) and exits as TWO spatially-separated parallel
beams (ordinary + extraordinary) -- the textbook double image -- landing as two spots on the screen.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/_render_birefringence.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy

import optical_alignment_sim as addon
try:
    addon.register()
except Exception:
    pass

from optical_alignment_sim import elements_generic as eg, optics_api

scene = bpy.context.scene
for o in list(scene.objects):
    if getattr(o, "optics", None) and o.optics.is_optical:
        bpy.data.objects.remove(o, do_unlink=True)
COLL = bpy.data.collections.new("OE_RENDER")
scene.collection.children.link(COLL)

# a thick calcite block so the L*tan(rho) displacement is visually obvious (~2.2 mm over 20 mm)
s = eg.source("OE_Source", (-60, 0, 0), (1, 0, 0), coll=COLL, wavelength=532.0)
s.optics.pol_type = 'CIRCULAR'
eg.crystal("Calcite", (0, 0, 0), (1, 0, 0), coll=COLL, size=20.0,
           oe_split=True, oe_material='CALCITE', oe_axis_deg=45.0, oe_length_mm=20.0)
eg.detector("Screen", (70, 0, 0), (1, 0, 0), coll=COLL, size=30.0, readout='CAMERA')

bpy.context.view_layer.update()
optics_api.trace_beam()

out = os.path.join(REPO, "docs/img/birefringence-double-refraction-render.png")
res = optics_api.render(preset='preview', camera='HERO', filepath=out)
print("render result:", res)
print("wrote", out if os.path.exists(out) else "(FILE MISSING)")
