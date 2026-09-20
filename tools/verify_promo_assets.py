"""Reload exported promo scene/assets in Blender and verify delivery invariants."""
import sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import optics_api
out=Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.open_mainfile(filepath=str(out/'promo-mach-zehnder.blend'))
assert sum(o.optics.is_optical for o in bpy.context.scene.objects)==13
assert optics_api.diagnose()['counts']['BAD']==0
parts=[o for o in bpy.context.scene.objects if o.name.startswith('NEW_')]
assert parts and all(not o.optics.is_optical for o in parts)
assert all(o.hide_get() and not o.hide_render for o in parts)
from mathutils import Vector
assert len([o for o in parts if o.get('target_part')=='PH50/M'])==13
assert not any(o.name.startswith(('OAR_HW_Holder_','OAR_HW_Locks_','OAR_HW_Lockh_')) and not o.hide_render for o in bpy.context.scene.objects)
for holder in [o for o in parts if o.get('target_part')=='PH50/M']:
 assert holder.get('geometry_revision')=='PH50M-visual-r2'
 origin=holder.matrix_world.translation
 family=[o for o in parts if o.parent is holder.parent]
 post=next((o for o in family if o.get('target_part')=='TR50/M'),None)
 if post is None:
  post=next(o for o in parts if o.get('station_post') and o.parent is holder.parent)
 bottom=min((post.matrix_world @ Vector(v)).z for v in post.bound_box)
 assert bottom>=origin.z+25-holder['bore_depth_mm']-1e-4
 post_right=max((post.matrix_world @ Vector(v)).x for v in post.bound_box)
 for prefix in ('NEW_HolderLockShaft','NEW_HolderPressureTip'):
  obj=next(o for o in family if o.name.startswith(prefix))
  left=min((obj.matrix_world @ Vector(v)).x for v in obj.bound_box)
  assert left>=post_right-1e-4,(prefix,left,post_right)
 knob=next(o for o in family if o.name.startswith('NEW_HolderThumbscrew') and 'Shoulder' not in o.name)
 assert knob['hex_across_flats_mm']==5
 # Hexagon at the socket mouth: measure its edges, not the assigned custom property.
 rim=[v.co for v in knob.data.vertices if abs(v.co.z-4)<1e-4 and 2.8<v.co.xy.length<3.0]
 assert len(rim)==6,len(rim)
 import math
 rim.sort(key=lambda v:math.atan2(v.y,v.x))
 distances=[]
 for a,b in zip(rim,rim[1:]+rim[:1]):
  distances.append(abs(a.x*b.y-a.y*b.x)/(a.xy-b.xy).length)
 assert all(abs(2*d-5)<1e-4 for d in distances),distances
print('HOLDER R2 PASS: no shaft/post penetration; measured 5 mm hex socket')
from optical_alignment_sim import optomech
grid=optomech.grid_info(bpy.context.scene)
bases=[o for o in parts if o.get('table_base')]
bolts=[o for o in parts if o.get('table_fastener')]
assert len(bases)==13 and len(bolts)==26
assert not any(o.name.startswith(('OAR_HW_Base_','OAR_HW_BaseTab_','OAR_HW_BaseBolt_')) and not o.hide_render for o in bpy.context.scene.objects)
for bolt in bolts:
 pos=bolt.matrix_world.translation
 for i in (0,1):
  q=(pos[i]-grid['origin'][i])/grid['pitch_mm']
  assert abs(q-round(q))<1e-4,(bolt.name,q)
 assert min((bolt.matrix_world @ Vector(v)).z for v in bolt.bound_box)<grid['board_top_z_mm']
 base=next(o for o in bases if o.parent is bolt.parent)
 inv=base.matrix_world.inverted()
 start=inv @ Vector((pos.x,pos.y,grid['board_top_z_mm']+30))
 direction=inv.to_3x3() @ Vector((0,0,-1))
 assert not base.ray_cast(start,direction,distance=50)[0],('bolt blocked by base',bolt.name)
 # Both lateral sample points must be open: channels run along the short edge.
 for offset in (-14,14):
  sample=inv @ Vector((base.matrix_world.translation.x+offset,pos.y,grid['board_top_z_mm']+30))
  assert not base.ray_cast(sample,direction,distance=50)[0],('short-edge channel blocked',base.name,offset)
for base in bases:
 floor=min((base.matrix_world @ Vector(v)).z for v in base.bound_box)
 assert abs(floor-grid['board_top_z_mm'])<1e-4
 holder=next(o for o in parts if o.get('target_part')=='PH50/M' and o.parent is base.parent)
 top=max((base.matrix_world @ Vector(v)).z for v in base.bound_box)
 assert abs(top-(holder.matrix_world.translation.z-25))<1e-4
for i,a in enumerate(bases):
 av=[a.matrix_world @ Vector(v) for v in a.bound_box]
 for b in bases[i+1:]:
  bv=[b.matrix_world @ Vector(v) for v in b.bound_box]
  overlap=[min(max(v[k] for v in av),max(v[k] for v in bv))-max(min(v[k] for v in av),min(v[k] for v in bv)) for k in (0,1)]
  assert min(overlap)<=1e-4,('table bases overlap',a.name,b.name,overlap)
print('TABLE BASE PASS: 13 bases, 26 grid-aligned bolts, holder/base/table contact datums')

assert sum(bool(o.get('promo_station_family')) for o in bpy.context.scene.objects)==11
assert not any(o.name.startswith('OAR_HW_') and o.parent and o.parent.get('oa_owner') and not o.hide_render for o in bpy.context.scene.objects)
from optical_alignment_sim import scan
from mathutils.bvhtree import BVHTree
deps=bpy.context.evaluated_depsgraph_get()
new_families={'LaserHead','LensCell','WindowCell','RotationMount','CubeHousing','DetectorHousing'}
segments=scan._trace(bpy.context.scene)
for part in parts:
 if part.type!='MESH' or part.get('promo_part_group') not in new_families:continue
 # Hidden viewport objects remain render participants; original mesh includes applied bores.
 verts=[part.matrix_world @ v.co for v in part.data.vertices]
 tree=BVHTree.FromPolygons(verts,[tuple(p.vertices) for p in part.data.polygons])
 for segment in segments:
  start=Vector(segment['p1']);end=Vector(segment['p2']);delta=end-start
  if delta.length<.02:continue
  hit=tree.ray_cast(start+delta.normalized()*.01,delta.normalized(),delta.length-.02)
  assert hit[0] is None,('new housing blocks traced center ray',part.name,tuple(hit[0]))
print('STATIONS PASS: 11 replaced, old render hardware hidden, center-ray openings clear')

for name in ('part-LaserHead','part-LensCell','part-RotationMount','part-CubeHousing','part-WindowCell','part-DetectorHousing','new-mirror-assembly','part-TableBase','part-PH50M','part-TR50M','part-EO15866'):
 with bpy.data.libraries.load(str(out/(name+'.blend')),link=False) as (source,target):
  target.collections=source.collections
 assert target.collections and any(c.asset_data for c in target.collections)
 objects={o for c in target.collections for o in c.all_objects}
 assert objects,name
 if name.startswith('part-'):
  assert all(not o.optics.is_optical and o.parent is None for o in objects),name
 if name=='part-PH50M':
  assert any(o.type=='FONT' and o.data.body=='PH50 / M' for o in objects)
 print('RELOAD PASS',name,len(objects))
print('PROMO DELIVERY PASS: scene, simple viewport, detailed render, eleven asset libraries')
