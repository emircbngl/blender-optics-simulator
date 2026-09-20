"""Render appearance must never alter optical results, geometry or unit semantics."""
import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import elements_generic as G,bake,scan,beamcolor,geometry
checks=0
def check(condition,message):
    global checks
    assert condition,message
    checks+=1

def contract(material):
    out=next(n for n in material.node_tree.nodes if n.type=='OUTPUT_MATERIAL')
    check(not out.inputs['Surface'].is_linked,'beam must not have an opaque surface')
    check(out.inputs['Volume'].is_linked,'beam emission must be a volume')
    check(not any(n.type in {'VOLUME_ABSORPTION','VOLUME_SCATTER','PRINCIPLED_VOLUME'} for n in material.node_tree.nodes),'display must not absorb or occlude the bench')

bpy.ops.wm.read_factory_settings(use_empty=True)
s=bpy.context.scene
# Opening an older file must migrate its cached solid material in-place.
legacy=bpy.data.materials.new('OPTICS_BEAM_532.000_FALSE_COLOR');legacy.use_nodes=True
em=legacy.node_tree.nodes.new('ShaderNodeEmission')
out=next(n for n in legacy.node_tree.nodes if n.type=='OUTPUT_MATERIAL')
legacy.node_tree.links.new(em.outputs[0],out.inputs['Surface'])
mat=bake.beam_material(532)
check(mat==legacy,'legacy users must receive the fix without recreating their material slots')
contract(mat)
node_count=len(mat.node_tree.nodes)
check(bake.beam_material(532)==mat and len(mat.node_tree.nodes)==node_count,'material reuse must be idempotent')
check(bake.beam_material(1064,'HIDE') is None,'hidden IR must remain hidden')
for wl in (405,532,589.0,589.4,632.8,1064):
    mat=bake.beam_material(wl)
    rgb=tuple(mat.node_tree.nodes['Emission'].inputs['Color'].default_value)[:3]
    check(all(abs(a-b)<1e-6 for a,b in zip(rgb,beamcolor.wavelength_rgb(wl))),'wavelength convention must remain unchanged')

# Same physical scene in two unit systems: no changes to path, power, q, phase,
# polarization, geometry or ports when baking/upgrading/ensuring the render beams.
for scale in (.001,1.0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s=bpy.context.scene;s.unit_settings.system='METRIC';s.unit_settings.scale_length=scale
    s.optics.scene_units_authoritative=True
    c=G.example_collection('appearance')
    source=G.source('S',(-100,0,0),(1,0,0),c,wavelength=532)
    G.lens('L',(0,0,0),(1,0,0),c,focal=100)
    G.detector('D',(120,0,0),(1,0,0),c)
    bpy.context.view_layer.update()
    optics=[o for o in s.objects if o.optics.is_optical]
    meshes={o.name:[tuple(v.co) for v in o.data.vertices] for o in optics}
    matrices={o.name:[tuple(r) for r in o.matrix_world] for o in optics}
    before=repr(scan._trace(s))
    check(bake.bake_beams(bpy.context)>0,'a real traced bench must bake')
    check(repr(scan._trace(s))==before,'full trace must be identical after appearance bake')
    check(meshes=={o.name:[tuple(v.co) for v in o.data.vertices] for o in optics},'optical mesh geometry changed')
    check(matrices=={o.name:[tuple(r) for r in o.matrix_world] for o in optics},'optical matrices changed')
    tube=next(o for o in s.objects if o.name.startswith('BEAM_'))
    mat=tube.data.materials[0];contract(mat)
    coeff=mat.node_tree.nodes['Display emission per world unit'].inputs[1].default_value
    check(abs(coeff/geometry.mm_per_unit(s)-2.0)<1e-5,'emission per physical length depends on unit scale')
    if scale==.001:
        # Simulate a still-cached old shader: ensure_beams must not early-return.
        del mat['oab_beam_material_version']
        old_pointer=tube.as_pointer()
        bake.ensure_beams(bpy.context)
        tube=next(o for o in s.objects if o.name.startswith('BEAM_'))
        contract(tube.data.materials[0])
        check(tube.data.materials[0].get('oab_beam_material_version')==bake.BEAM_MATERIAL_VERSION,'ensure did not upgrade legacy material')
    check(repr(scan._trace(s))==before,'ensure changed simulation output')
print(f'BEAM APPEARANCE PASS ({checks} checks): transparent volume, legacy upgrade, wavelength and simulation invariance, units')
