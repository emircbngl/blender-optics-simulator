"""Render detail must preserve simulation state and restore visibility, including failures."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bpy
from mathutils import Vector
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G, mounts, optomech, hardware_render as H, render, optics_api
s = bpy.context.scene
c = G.example_collection('HardwareTest')
m = G.mirror('HW_Mirror',(0,0,100),Vector((1,0,0)),Vector((0,1,0)),c)
w = G.waveplate('HW_Rotation',(80,0,100),Vector((1,0,0)),c)
assert mounts.apply_preset(m,'KM100')[0]
assert mounts.apply_preset(w,'RSP1')[0]
G.source('HW_Source',(-100,0,100),Vector((1,0,0)),c)
G.detector('HW_Detector',(0,100,100),Vector((0,1,0)),c)
bpy.context.view_layer.update()
pose = [tuple(v) for v in m.matrix_world]
verts = [tuple(v.co) for v in m.data.vertices]
optomech.dress(s)
base = {o.name:(o.data, o.hide_render) for o in s.objects if o.name.startswith('BENCH_')}
# A deliberately hidden part must never be resurrected by render prep or cleanup.
hidden = next(o for o in s.objects if o.name.startswith('BENCH_BaseScrew'))
hidden.hide_render = True
base[hidden.name] = (hidden.data,True)
bpy.context.view_layer.objects.active=m
before_trace = optics_api.trace_beam()
assert before_trace["segments"] > 0
n = H.prepare(s)
assert optics_api.trace_beam() == before_trace
assert n > len(base)
assert bpy.context.view_layer.objects.active == m
assert all(o.hide_get() and not o.optics.is_optical for o in s.objects if o.get(H.TAG))
assert any('Scale2deg' in o.name for o in s.objects)
assert any('S0_' in o.name and len(o.data.vertices)>2000 for o in s.objects if o.get(H.TAG))
assert not any(o.parent == hidden for o in s.objects if o.get(H.TAG))
assert pose == [tuple(v) for v in m.matrix_world]
assert verts == [tuple(v.co) for v in m.data.vertices]
assert all(s.objects[name].data == data for name,(data,_) in base.items())
count = len(bpy.data.meshes)
assert H.prepare(s) == n
assert len(bpy.data.meshes) == count
H.clear(s)
assert not any(o.get(H.TAG) for o in s.objects)
assert all(s.objects[name].hide_render == visibility for name,(_,visibility) in base.items())
# Preparation failure restores all original visibility.
original_material = H.material
def fail_material(kind):
    raise RuntimeError('injected preparation failure')
H.material = fail_material
try:
    try:
        H.prepare(s)
        raise AssertionError('expected failure')
    except RuntimeError as exc:
        assert 'injected' in str(exc)
finally:
    H.material = original_material
assert not any(o.get(H.TAG) for o in s.objects)
assert all(s.objects[name].hide_render == visibility for name,(_,visibility) in base.items())
# Render settings expose the detailed layer and reset removes it.
render.setup_final(s)
from mathutils import Vector
bottom=min((o.matrix_world@Vector(c)).z for o in s.objects if o.type=='MESH' and o.name.startswith('BENCH_') for c in o.bound_box)
assert s.objects['OPTICS_Studio_Ground'].location.z < bottom
assert any(o.get(H.TAG) for o in s.objects)
render.clear_render_style(s)
assert not any(o.get(H.TAG) for o in s.objects)
# Automatic dressing is temporary too.
optomech.strip(s)
H.prepare(s)
assert optomech.is_dressed(s)
H.clear(s)
assert not optomech.is_dressed(s)
# Removing a dressed scene cleans dependent children rather than leaving orphans.
optomech.dress(s)
H.prepare(s)
optomech.strip(s)
assert not any(o.get(H.TAG) for o in s.objects)
print('HARDWARE RENDER PASS: geometry, visibility, idempotence, cleanup, optical isolation')
