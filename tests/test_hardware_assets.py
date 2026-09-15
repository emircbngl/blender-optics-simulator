"""Verify generated assets: blender -b --python tests/test_hardware_assets.py -- ASSET_DIR"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy, bmesh
import json, hashlib
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import hardware_render as H
root=Path(sys.argv[sys.argv.index('--')+1])
files=sorted(root.glob('*.blend'))
from tools.inspect_mounts import mount_cases
from optical_alignment_sim import elements_generic as G, mounts, optics_api
expected=set(mount_cases(G,mounts,optics_api))
assert {p.stem for p in files} == expected
catalog=json.loads((root/'catalog.json').read_text())
assert catalog['count']==len(expected)
assert {p['name'] for p in catalog['products']}==expected
for item in catalog['products']:
    assert hashlib.sha256((root/item['file']).read_bytes()).hexdigest()==item['sha256']
    assert item['detail_parts']>0
    assert set(item['features'])-{'machined_material'}
    if item['preview']:
        assert (root/item['preview']).is_file()
for path in files:
    with bpy.data.libraries.load(str(path),link=False) as (src,dst):
        dst.collections=[n for n in src.collections if n.startswith('Optomechanics')]
    coll=dst.collections[0]
    bpy.context.scene.collection.children.link(coll)
    detail=[c for c in coll.children if c.get(H.TAG)]
    assert len(detail)==1 and detail[0].hide_viewport
    assert detail[0].objects
    for ob in detail[0].objects:
        assert not ob.optics.is_optical and ob.parent is not None
        assert not ob.hide_render
        assert not ('Breadboard' in ob.name or 'Holes' in ob.name or 'Foot_' in ob.name)
        if ob.type=='MESH' and any(t in ob.get('detail_features','') for t in ('spring','knurl','turned_surface')):
            bm=bmesh.new();bm.from_mesh(ob.data)
            assert all(e.is_manifold for e in bm.edges),ob.name
            bm.free()
    assert any(o.optics.is_optical for o in coll.objects)
    assert not any('Foot_' in o.name for o in coll.all_objects)
    if path.stem.startswith('CAGE'):
        assert sum('CageRod_' in o.name for o in coll.objects)==4
    print('APPEND_PASS',path.stem)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob,do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
print('ASSET ROUNDTRIP PASS %d/%d'%(len(files),len(expected)))
