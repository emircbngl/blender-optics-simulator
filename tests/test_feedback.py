"""Harca-Yita feedback regressions; run in Blender with --python-exit-code 1.

Direction expectations: MKS Diffraction Grating Handbook, 8th ed., §2.2,
eq. 2-3 (conical diffraction). These are source-grounded numerical tests,
not physics_verify oracle results.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bpy
from mathutils import Vector, Matrix
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G, tracer, library, param_schema
from optical_alignment_sim import optics_api

checks = []
def check(label, condition):
    checks.append(bool(condition))
    print(('PASS ' if condition else 'FAIL ') + label, flush=True)

def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

def trace_grating(d, roll=0, order=1, density=600, scale=1):
    clear()
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = scale / 1000
    d = Vector(d).normalized()
    G.source('Green', -100*d, d, wavelength=532)
    G.source('Red', -100*d, d, wavelength=633)
    # Surface normal +Z, ruling +Y before roll; coordinates are physical mm.
    gr = G.grating('Grating', (0,0,0), (0,0,-1), (0,0,1),
                   lines_per_mm=density, order=order)
    gr.matrix_world = Matrix.Rotation(roll, 4, 'Z')
    gr.scale = (1/scale,)*3
    bpy.context.view_layer.update()
    segs = tracer.trace_scene(sc, max_segments=128)
    out = {s['wavelength']: (s['p2']-s['p1']).normalized()
           for s in segs if s.get('from') == 'Grating'}
    print('DIRECTIONS', tuple(d), 'roll', roll, 'order', order,
          {wl: tuple(v) for wl,v in out.items()}, flush=True)
    return out

for label, d, roll in [('normal', (0,0,-1), 0),
                        ('near normal', (1e-7,0,-1), 0),
                        ('45 deg', (-1,0,-1), 0),
                        ('conical', (-.3,.4,-math.sqrt(.75)), 0),
                        ('rolled', (0,0,-1), math.pi/2)]:
    out = trace_grating(d, roll)
    direction = Vector(d).normalized()
    across = Vector((math.cos(roll), math.sin(roll), 0))
    along = Vector((-math.sin(roll), math.cos(roll), 0))
    for wl in (532.,633.):
        v = out.get(wl)
        check(label + ' signed grating equation ' + str(wl), v is not None and
              abs(v.dot(across) - (direction.dot(across)+wl*1e-6*600)) < 2e-6)
        check(label + ' groove momentum ' + str(wl), v is not None and
              abs(v.dot(along)-direction.dot(along)) < 2e-6)
    check(label + ' separates wavelengths', len(out)==2 and out[532.].angle(out[633.]) > .01)

out = trace_grating((1,0,-1), density=1200)
check('evanescent order does not silently become a mirror', not out)
out = trace_grating((-.3,.4,-math.sqrt(.75)), order=0)
check('zero order remains specular', len(out)==2 and
      all((v-Vector((-.3,.4,math.sqrt(.75)))).length < 2e-6 for v in out.values()))
out = trace_grating((0,0,-1), order=-1)
check('negative order has negative signed dispersion', len(out)==2 and all(v.x < 0 for v in out.values()))
out = trace_grating((0,0,-1), scale=1000)
check('metre scene same direction', len(out)==2 and abs(out[633.].x-.3798) < 2e-6)

clear()
bpy.context.scene.unit_settings.scale_length = .001
optics_api.build_example('prism')
segs = tracer.trace_scene(bpy.context.scene, max_segments=256)
fan = {s['wavelength']: (s['p2']-s['p1']).normalized() for s in segs
       if s.get('from') == 'PRISM_Prism' and s.get('kind') != 'GLASS'}
check('prism example emits eleven wavelengths', len(fan)==11)
check('prism example visibly fans light', len(fan)>1 and max(v.angle(w) for v in fan.values() for w in fan.values()) > .02)
check('UI example entry builds successfully', bpy.ops.optics.build_example(kind='prism') == {'FINISHED'})

items = library._component_items(None, None)
labels = [i[1].casefold() for i in items]
check('library sorted by displayed name', labels == sorted(labels))
check('library search uses component property', getattr(library.OPTICS_OT_add_from_library, 'bl_property', None)=='component')
check('source bandwidth visible in essentials', 'bandwidth_nm' in [n for n,c in param_schema.SCHEMA['SOURCE']['essentials']])
clear()
obj, msg = library.add_component('WHITE_LIGHT')
check('broadband library source exists and emits multiple lines', obj is not None and obj.optics.bandwidth_nm > 0 and
      len({s['wavelength'] for s in tracer.trace_scene(bpy.context.scene, max_segments=128)}) == 11)

print('FEEDBACK %s (%d/%d checks)' % ('PASS' if all(checks) else 'FAIL', sum(checks), len(checks)), flush=True)
if not all(checks):
    raise SystemExit(1)
