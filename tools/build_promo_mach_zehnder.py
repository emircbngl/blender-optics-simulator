"""Fresh promotional parts plus extended MZ scene; no full film render.
Blender --background --factory-startup --python this.py -- OUTPUT
"""
import sys,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import bpy
from mathutils import Vector
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G,optics_api,optomech,mounts,render,bake,scan
from optical_alignment_sim import promo_hardware as H
out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True,exist_ok=True)
for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=.001
coll=G.example_collection('Promo_Extended_Mach_Zehnder');X=Vector((1,0,0));Y=Vector((0,1,0));z=100
laser=G.source('PROMO_Laser',(-380,0,z),X,coll,wavelength=532,radius=7)
l1=G.lens('PROMO_Expander_Negative',(-290,0,z),X,coll,focal=-25,radius=12.7)
l2=G.lens('PROMO_Expander_Positive',(-240,0,z),X,coll,focal=75,radius=12.7)
wp=G.waveplate('PROMO_HalfWave',(-160,0,z),X,coll,fast_axis=0,design_wl=532)
pol=G.polarizer('PROMO_InputPolarizer',(-80,0,z),X,coll)
bs1=G.beamsplitter('PROMO_Splitter',(0,0,z),X,Y,coll)
mirror1=G.mirror('PROMO_ObjectFold',(0,260,z),Y,X,coll,size=25.4)
sample=G.window('PROMO_Sample',(110,260,z),X,coll,radius=12.7,thickness=2)
mirror2=G.mirror('PROMO_ReferenceFold',(320,0,z),X,Y,coll,size=25.4)
reference=G.window('PROMO_ReferencePlate',(320,110,z),Y,coll,radius=12.7,thickness=2)
bs2=G.beamsplitter('PROMO_Recombiner',(320,260,z),X,Y,coll)
cam=G.detector('PROMO_Camera',(500,260,z),X,coll,size=30)
monitor=G.detector('PROMO_SecondOutput',(320,410,z),Y,coll,size=24)
for ob,key in ((wp,'RSP1'),(pol,'RSP1'),(mirror1,'EO-15866'),(mirror2,'EO-15866')):
 ok,msg=mounts.apply_preset(ob,key);assert ok,msg
# Source-backed range applied only to the new promo scene, not silently to existing user scenes.
for ob in (mirror1,mirror2):
 for dof in ob.optics.dofs:
  if dof.kind in {'TIP','TILT'}:dof.min_val=-3.5;dof.max_val=3.5
# Dress and prepare the older supporting stations before introducing independent new assemblies.
bpy.context.view_layer.update();optomech.dress(scene)
trace_before=scan._trace(scene)
scene.optics.beam_radius_scale=.35  # Display-only thin beam overlay, not a physical waist change.
bake.bake_beams(bpy.context)
render.setup_final(scene)
newcoll=H.collection('PROMO_New_Hardware')
for ob in (mirror1,mirror2):
 owner=ob.get('oa_owner')
 for part in list(bpy.data.objects):
  if part is not ob and (part.get('oa_owner')==owner or (part.parent and part.parent.get('oa_owner')==owner)) and part.name.startswith(('BENCH_','OAR_HW_')):
   part.hide_render=True;part.hide_set(True)
 normal=ob.matrix_world.to_3x3().col[2].normalized()
 center=ob.location-normal*12
 before=set(newcoll.objects)
 H.support(newcoll,(center.x,center.y),post_top=74.6)
 bpy.context.view_layer.update()
 for p in set(newcoll.objects)-before:
  world=p.matrix_world.copy();p.parent=ob;p.matrix_world=world
 H.mirror_mount(newcoll,ob)
# Replace every remaining station's holder, retaining its existing base and post datums.
replacement_count=0
mirror_owners={mirror1.get('oa_owner'),mirror2.get('oa_owner')}
for old in list(scene.objects):
 if not old.name.startswith('BENCH_Holder_') or old.get('oa_owner') in mirror_owners:continue
 owner=old.get('oa_owner'); center=old.matrix_world.translation.copy()
 holder,members=H.post_holder(newcoll,(center.x,center.y),bottom_z=center.z-25,bore_depth=46)
 bpy.context.view_layer.update()
 for p in members:
  world=p.matrix_world.copy();p.parent=old.parent;p.matrix_world=world
  p['oa_owner']=owner
 for p in list(scene.objects):
  src=p.parent if p.name.startswith('OAR_HW_') else p
  if src and src.get('oa_owner')==owner and src.name.startswith(('BENCH_Holder_','BENCH_Locks_','BENCH_Lockh_')):
   p.hide_render=True
 replacement_count+=1
bpy.context.view_layer.update()
assert replacement_count==11,('uncovered holder stations',replacement_count)
assert len([p for p in newcoll.objects if p.get('target_part')=='PH50/M'])==13
# All 13 table attachments now follow real grid-hole coordinates.
for p in list(newcoll.objects):
 if p.get('promo_part_group')=='BA2M' or p.name.startswith('Etching_METRIC'):
  bpy.data.objects.remove(p,do_unlink=True)
for p in list(scene.objects):
 src=p.parent if p.name.startswith('OAR_HW_') else p
 if src and src.name.startswith(('BENCH_Base_','BENCH_BaseTab_','BENCH_BaseBolt_')):
  p.hide_render=True
for holder in list(newcoll.objects):
 if holder.get('target_part')=='PH50/M':H.table_base(newcoll,holder,optomech.grid_info(scene))
bpy.context.view_layer.update()
assert len([p for p in newcoll.objects if p.get('table_base')])==13
from optical_alignment_sim import promo_stations
station_inventory={}
for optic in (laser,l1,l2,wp,pol,bs1,sample,reference,bs2,cam,monitor):
 oldpost=next(p for p in scene.objects if p.name.startswith('BENCH_Post_') and p.parent is optic)
 station_inventory[optic.name]=promo_stations.rebuild(newcoll,optic,oldpost)
 for p in list(scene.objects):
  src=p.parent if p.name.startswith('OAR_HW_') else p
  if src and src.get('oa_owner')==optic.get('oa_owner') and src.name.startswith('BENCH_'):
   p.hide_render=True
bpy.context.view_layer.update()
assert repr(scan._trace(scene))==repr(trace_before),'new hardware altered optical trace'
# Nominal body checks independent of generation parameters, prior to export.
checks=[]
for part in newcoll.objects:
 if part.get('target_part'):
  expected={'BA2/M':(50,75,10),'PH50/M':(25,25,50),'TR50/M':(12.7,12.7,50)}[part['target_part']]
  coords=[v.co for v in part.data.vertices]
  measured=tuple(max(v[i] for v in coords)-min(v[i] for v in coords) for i in range(3))
  assert all(abs(a-b)<.01 for a,b in zip(measured,expected)),(part.name,measured,expected)
  checks.append(dict(part=part['target_part'],measured_mm=measured,expected_mm=expected))
report=dict(scene='Extended Mach-Zehnder visual prototype',optical_elements=13,segments=len(trace_before),
            updated_holder_stations=13, updated_table_bases=13, rebuilt_stations=station_inventory,
            new_hardware_objects=len(newcoll.objects),nominal_envelope_checks=checks,
            optical_trace_unchanged=True,assembly_training_verified=False,
            estimated_details=['slot locations/counterbores','post cross-hole location','mount internal geometry','springs','surface finish'],
            physics_oracle='unavailable in this session; existing tracer used, no independent validation of whole demo',
            diagnostics=optics_api.diagnose())
assert report['diagnostics']['counts']['BAD']==0,report['diagnostics']
(out/'report.json').write_text(json.dumps(report,indent=2,default=str))
scene.cycles.samples=48;scene.cycles.use_denoising=True;scene.cycles.device='CPU'
scene.render.resolution_x=1280;scene.render.resolution_y=800;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
render.set_camera_direction(scene,Vector((.45,-.75,.8)))
scene.camera.data.lens=48
# Closer framing than generic bounding sphere while retaining breadboard corners.
center=Vector((55,180,35));scene.camera.location=center+Vector((.45,-.75,.8)).normalized()*1450
scene.camera.rotation_euler=(center-scene.camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=str(out/'01_setup.png');bpy.ops.render.render(write_still=True)
# Close view of the new fold station; same scene and light, actual optic remains seated.
focus=mirror2.location+Vector((0,0,-40))
scene.camera.location=focus+Vector((180,-250,150))*1.25;scene.camera.data.lens=65
scene.camera.rotation_euler=(focus-scene.camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=str(out/'02_mount_detail.png');bpy.ops.render.render(write_still=True)
saved_camera=scene.camera.matrix_world.copy()
focus=Vector((-180,0,75));scene.camera.location=focus+Vector((240,-310,190));scene.camera.data.lens=43
scene.camera.rotation_euler=(focus-scene.camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=str(out/'03_new_stations.png');bpy.ops.render.render(write_still=True)
scene.camera.matrix_world=saved_camera;scene.camera.data.lens=65
# Save the finished camera/render scene; new parts remain editable individual objects.
# Keep modelling/simulation responsive; detailed hardware remains enabled for rendering.
for p in newcoll.objects:p.hide_set(True)
for p in bpy.data.objects:
 if p.name.startswith('BENCH_') and p.get('oa_owner') in {mirror1.get('oa_owner'),mirror2.get('oa_owner')}:
  p.hide_set(False)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'promo-mach-zehnder.blend'))
# Independent asset collection for one new mount/support assembly, without other optical stations.
asset=bpy.data.collections.new('PROMO_New_Mirror_Assembly');scene.collection.children.link(asset)
asset.objects.link(mirror2)
for p in newcoll.objects:
 if p.parent is mirror2:asset.objects.link(p)
asset.asset_mark();asset.asset_data.description='Fresh nominal-dimension visual prototype; not verified manufacturing CAD or assembly training.'
bpy.data.libraries.write(str(out/'new-mirror-assembly.blend'),{asset},fake_user=True)
# Export independent editable parts at a local datum; copies cannot move the scene's optics.
for group in ('TableBase','PH50M','TR50M','EO15866'):
 partcoll=bpy.data.collections.new('PROMO_'+group)
 members=[p for p in newcoll.objects if p.parent is mirror2 and p.get('promo_part_group')==group]
 assert members,group
 origin=mirror2.location.copy() if group=='EO15866' else next(p for p in members if p.get('target_part') or p.get('table_base')).matrix_world.translation.copy()
 for p in members:
  copy=p.copy();copy.data=p.data.copy();world=p.matrix_world.copy()
  copy.parent=None;partcoll.objects.link(copy);copy.matrix_world=world;copy.location-=origin
 partcoll.asset_mark();partcoll.asset_data.description='Visual prototype: nominal envelope checked; fit and internal geometry unverified.'
 bpy.data.libraries.write(str(out/('part-'+group+'.blend')),{partcoll},fake_user=True)
# One reusable library for each newly rebuilt station family.
for optic in (laser,l1,wp,bs1,sample,cam):
 family=optic['promo_station_family'];asset=bpy.data.collections.new('PROMO_'+family)
 for part in newcoll.objects:
  if part.parent is optic and part.get('promo_part_group')==family:
   copy=part.copy();copy.data=part.data.copy();world=part.matrix_world.copy()
   copy.parent=None;asset.objects.link(copy);copy.matrix_world=world;copy.location-=optic.location
 asset.asset_mark();asset.asset_data.description='Original visual hardware design; no optical behavior or verified mechanical fit.'
 bpy.data.libraries.write(str(out/('part-'+family+'.blend')),{asset},fake_user=True)
print('PROMO BUILD PASS',json.dumps({k:v for k,v in report.items() if k!='diagnostics'}),flush=True)
