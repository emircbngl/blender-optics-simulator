"""Iris updates must restore selection without iterating a stale view layer (4.2.3)."""
import os,sys
from pathlib import Path
sys.path.insert(0,os.environ.get('OAS_REVIEW_ROOT',str(Path(__file__).resolve().parents[1])))
import bpy
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as eg
s=bpy.context.scene; s.optics.live_enabled=False
for o in list(bpy.data.objects): bpy.data.objects.remove(o,do_unlink=True)
marker=bpy.data.objects.new('Selection sentinel',None); s.collection.objects.link(marker)
bpy.context.view_layer.update(); marker.select_set(True); bpy.context.view_layer.objects.active=marker
iris=eg.aperture('Iris',(0,0,0),(1,0,0),radius=3.)
bpy.context.view_layer.update()
for o in bpy.context.view_layer.objects: o.select_set(o==marker)
bpy.context.view_layer.objects.active=marker
for radius in (2.,4.,1.):
    iris.optics.clear_aperture=radius
    bpy.context.view_layer.update()
    assert bpy.context.view_layer.objects.active==marker
    assert marker.select_get()
    assert all(abs(p.clear_aperture-radius)<1e-6 for p in iris.optics.ports)
    assert not any(c.name.startswith('OpticsIrisRegen_tmp') for c in bpy.data.collections)
print('IRIS REGEN PASS (3 radius updates, selection preserved)',flush=True)
