"""Reproducible review artifacts. Blender --background --python this.py -- OUTDIR."""
import os, sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy
from mathutils import Vector
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import optics_api as api, elements_generic as G, tracer, scan, spectrum

out=Path(sys.argv[sys.argv.index('--')+1]).resolve(); out.mkdir(parents=True,exist_ok=True)

def clear():
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
    tracer.cached_segments=[]

def save_array(arr,name):
    image=bpy.data.images.new(name,arr.shape[1],arr.shape[0],alpha=True)
    image.pixels.foreach_set(arr.reshape(-1)); image.filepath_raw=str(out/name)
    image.file_format='PNG'; image.save(); bpy.data.images.remove(image)

clear()
api.build_example('prism')
api.bake_beams(scale=.5)
bpy.context.scene.optics.realistic_mechanics=False
api.render(preset='final',camera='TOP')
scene=bpy.context.scene
scene.cycles.device='CPU'; scene.cycles.samples=16
scene.render.resolution_x=1000; scene.render.resolution_y=700; scene.render.resolution_percentage=100
camera=scene.camera
camera.location=(-20,-95,500)
camera.rotation_euler=(Vector((-20,-95,0))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO'; camera.data.ortho_scale=390
# Keep the collection and the sensor for the runnable example, but the giant
# detector housing should not hide the fan in its dedicated optical-path view.
bpy.data.objects['PRISM_Screen'].hide_render=True
scene.render.filepath=str(out/'prism-fan.png')
bpy.ops.wm.save_as_mainfile(filepath=str(out/'prism-example.blend'))
bpy.ops.render.render(write_still=True)

clear()
scene.optics.monitor_show=True
scene.unit_settings.system='METRIC'; scene.unit_settings.scale_length=.001
G.source('Source',(0,0,-100),(0,0,1),wavelength=633)
lens=G.lens('Cylindrical_lens',(0,0,0),(0,0,1),focal=100,lens_type='CYLINDRICAL')
det=G.detector('Line_focus',(0,0,101.5),(0,0,1),size=20)
det.optics.sensor_px=512; det.optics.pixel_size_um=2/512*1000
bpy.context.view_layer.update()
segs=tracer.trace_scene(scene,max_segments=128)
tracer.cached_segments=segs
arr,_=scan._fringe_array(det,segs,2,512)
save_array(arr,'cylindrical-line-focus.png')
scan.live_fringe_update(scene)
bpy.context.view_layer.objects.active=det; det.select_set(True)
api.bake_beams()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'cylindrical-example.blend'))
json.dump(api.inspect_beam(det.name),open(out/'cylindrical-readout.json','w'),indent=2)
lens.rotation_euler.z=1.5707963267948966
bpy.context.view_layer.update()
arr,_=scan._fringe_array(det,tracer.trace_scene(scene,max_segments=128),2,512)
save_array(arr,'cylindrical-line-focus-rotated.png')

clear()
G.source('Green_532nm',(0,0,-100),(0,0,1),wavelength=532)
G.source('Red_633nm',(0,0,-100),(0,0,1),wavelength=633)
det=G.detector('Spectrometer',(0,0,0),(0,0,1),size=20)
det.optics.sensor_mode='SPECTRUM'; det.optics.spectrum_resolution_nm=2
bpy.context.view_layer.update()
result=api.detector_spectrum(det.name,str(out/'spectrum.csv'))
save_array(spectrum.image(result,512),'spectrum.png')
tracer.cached_segments=tracer.trace_scene(scene)
scan.live_fringe_update(scene)
bpy.context.view_layer.objects.active=det; det.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'spectrometer-example.blend'))
print('ARTIFACTS',out,flush=True)
