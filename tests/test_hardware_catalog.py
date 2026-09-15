"""Preset metadata must match its actual Blender control and support assignment."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import hardware_catalog as C, elements_generic as G, mounts, geometry, optomech
from tools.inspect_mounts import _clear_scene
for key,p in C.PRODUCTS.items():
    _clear_scene()
    ob=C.build(key,G,mounts)
    bpy.context.view_layer.update()
    assert ob.optics.mount_preset==key
    assert ob.optics.mount_type==p['mount']
    assert ob.optics.support_system==p.get('support','POST')
    expected=3 if p['family']=='XYZ' else 2 if p['family'] in ('XY','KINEMATIC') else 1 if p['family']=='ROTATION' else 0
    assert len(ob.optics.dofs)==expected
    assert ob.optics.is_optical
    if p['family'] in ('XY','XYZ'):
        axes=[tuple(round(v,4) for v in d.axis_local) for d in ob.optics.dofs]
        assert len(set(axes))==len(axes)
    for port in ob.optics.ports:
        assert abs(port.clear_aperture-ob.optics.clear_aperture)<1e-5
    optomech.dress(bpy.context.scene)
    bpy.context.view_layer.update()
    parts=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith('BENCH_')]
    posts=[o for o in parts if 'Post_' in o.name]
    import re
    upper=[o for o in parts if not re.search(r'(Post_|Holder_|Locks_|Lockh_|Base|Foot_|Holes|Breadboard)',o.name)]
    assert posts and upper
    assert min(optomech._mesh_bvh_gap(post,body) for post in posts for body in upper) <= optomech.GAP_TOL, key+' floating mount above post'
    print('PRESET_PASS',key)
print('CATALOG CONTROLS PASS',len(C.PRODUCTS))

_clear_scene()
from mathutils import Vector
ob=G.lens('TooLarge',(0,0,100),Vector((1,0,0)),G.example_collection('FitCheck'),radius=25.4)
previous=ob.optics.mount_preset
ok,msg=mounts.apply_preset(ob,'TUBE_SM05')
assert not ok and 'accepts optics up to' in msg
assert ob.optics.mount_preset==previous
print('INCOMPATIBLE SIZE REJECTED without mutation')
