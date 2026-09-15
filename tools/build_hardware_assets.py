"""Export reusable Blender asset collections with live optics and render-only hardware.
Usage: blender -b --factory-startup --python tools/build_hardware_assets.py -- OUTPUT_DIR
"""
import os
import sys
import json
import hashlib
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bpy
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G, mounts, optics_api, optomech, hardware_render as H
from tools.inspect_mounts import mount_cases
out = sys.argv[sys.argv.index('--')+1]
os.makedirs(out,exist_ok=True)
only=set(sys.argv[sys.argv.index('--only')+1].split(',')) if '--only' in sys.argv else None
cases=mount_cases(G,mounts,optics_api)
if only and not only <= set(cases): raise ValueError('Unknown product in --only')
entries=[]
if only:
    with open(os.path.join(out,'catalog.json')) as f:
        entries=[entry for entry in json.load(f)['products'] if entry['name'] not in only]
render_previews="--render" in sys.argv
for name, build in cases.items():
    if only and name not in only: continue
    H.clear(bpy.context.scene)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob,do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    scene = bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene.unit_settings.scale_length=.001
    build()
    bpy.context.view_layer.update()
    optomech.dress(scene)
    H.prepare(scene)
    asset = bpy.data.collections.new('Optomechanics • '+name)
    scene.collection.children.link(asset)
    # A reusable component excludes the shared breadboard and camera/studio.
    for detail in list(scene.collection.children):
        if detail.get(H.TAG):
            asset.children.link(detail)
    for ob in list(scene.objects):
        if ob.get(H.TAG):
            continue
        if 'Breadboard' in ob.name or 'Holes' in ob.name or 'Foot_' in ob.name:
            continue
        asset.objects.link(ob)
    for detail in asset.children:
        for ob in list(detail.objects):
            if 'Breadboard' in ob.name or 'Holes' in ob.name or 'Foot_' in ob.name:
                bpy.data.objects.remove(ob,do_unlink=True)
    for ob in scene.objects:
        if ob.type=='MESH' and not ob.get(H.TAG) and ob.name not in asset.objects:
            ob.hide_render=True
    asset.asset_mark()
    asset.asset_data.description='Procedural '+name+' assembly. Basic simulation geometry + render detail. Optical controls require Optics Simulator. Dimensions partly estimated; see realistic-hardware.md.'
    asset.asset_data.author='Optics Simulator'
    asset.asset_data.tags.new('Optomechanics')
    asset.asset_data.tags.new(name)
    preview=None
    if render_previews:
        from mathutils import Vector
        from optical_alignment_sim import render
        from tools.inspect_mounts import _bbox
        lo,hi=_bbox([o for o in asset.objects if o.type=='MESH'])
        center=(lo+hi)*.5
        direction=Vector((1,-1,.6)).normalized()
        data=bpy.data.cameras.new('CatalogCamera')
        camera=bpy.data.objects.new('CatalogCamera',data)
        scene.collection.objects.link(camera)
        camera.location=center+direction*(hi-lo).length*2
        camera.rotation_euler=(-direction).to_track_quat('-Z','Y').to_euler()
        data.type='ORTHO'; data.ortho_scale=max((hi-lo).length*1.15,40)
        scene.camera=camera
        scene.render.engine='CYCLES';scene.cycles.device='CPU'
        scene.cycles.samples=24;scene.cycles.use_denoising=True
        scene.render.resolution_x=480;scene.render.resolution_y=480
        scene.render.resolution_percentage=100
        scene.render.image_settings.file_format='PNG'
        bpy.context.view_layer.update()
        from bpy_extras.object_utils import world_to_camera_view
        for part in asset.objects:
            if part.type=='MESH':
                for corner in part.bound_box:
                    point=world_to_camera_view(scene,camera,part.matrix_world@Vector(corner))
                    assert .01 < point.x < .99 and .01 < point.y < .99, (name,part.name,tuple(point))
        render.apply_optical_materials(scene);render.studio_lighting(scene)
        preview=name+'.png'
        scene.render.filepath=os.path.join(out,preview)
        bpy.ops.render.render(write_still=True)
        # Restore optics only; retain the render-only mechanics in the exported collection.
        for ob in asset.objects:
            if '_oa_vp_mat' in ob:
                if ob.type=='MESH' and ob.data.materials:
                    ob.data.materials[0]=bpy.data.materials.get(ob['_oa_vp_mat'])
                del ob['_oa_vp_mat']
        with bpy.context.temp_override(id=asset):
            bpy.ops.ed.lib_id_load_custom_preview(filepath=scene.render.filepath)
    filename=name+'.blend'
    bpy.data.libraries.write(os.path.join(out,filename),{asset},fake_user=True,compress=True)
    entries.append(dict(name=name,file=filename,preview=preview,
                        sha256=hashlib.sha256(open(os.path.join(out,filename),'rb').read()).hexdigest(),
                        basic_parts=len(asset.objects),detail_parts=sum(len(c.objects) for c in asset.children),
                        features=sorted({feature for c in asset.children for ob in c.objects
                                         for feature in ob.get('detail_features','machined_material').split(',')})))
    print('ASSET_SAVED',name,flush=True)
entries.sort(key=lambda item:list(cases).index(item['name']))
with open(os.path.join(out,'catalog.json'),'w') as f:
    json.dump(dict(count=len(entries),products=entries),f,indent=2)
print('HARDWARE_ASSETS_COMPLETE',len(entries),flush=True)
