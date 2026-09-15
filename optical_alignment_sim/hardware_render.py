"""Disposable render detail over the existing bench. No optical or kinematic data changes.

Vendor-inspired, original procedural models; see docs/realistic-hardware.md for
sources and the distinction between published features and estimated geometry.
"""
import math
import re
import bpy
from mathutils import Matrix

COLLECTION = 'OAR_Hardware'
TAG = '_oar_hardware'

# Visual profiles reuse the existing mechanical presets and their DOFs.
PROFILES = {
    'KM100': 'anodized', 'KM100CP/M': 'anodized', 'KS1': 'anodized',
    'EO-15866': 'anodized', 'POLARIS-K1': 'steel', 'RSP1': 'anodized',
    'GM100': 'anodized', 'TRF90': 'anodized', 'VC1': 'anodized',
}
from .hardware_catalog import PRODUCTS
PROFILES.update({key: 'anodized' for key in PRODUCTS})


def material(kind):
    name = 'OAR_HW_' + kind
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    colors = {'anodized': (.022, .025, .03), 'steel': (.48, .5, .52),
              'aluminium': (.62, .65, .68), 'board': (.055, .06, .068),
              'engraving': (.72, .74, .73), 'dark': (.008, .009, .011)}
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*colors[kind], 1)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bs = nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value = (*colors[kind], 1)
    bs.inputs['Metallic'].default_value = .85 if kind != 'engraving' else .25
    bs.inputs['Roughness'].default_value = .28 if kind in ('steel', 'aluminium') else .43
    tex = nodes.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = 180
    tex.inputs['Detail'].default_value = 2
    bump = nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .12
    bump.inputs['Distance'].default_value = .008
    links.new(tex.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bs.inputs['Normal'])
    return mat


def _mesh(name, verts, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _lathe(name, rings, segments=128, teeth=0, caps=True):
    verts, faces = [], []
    outer = max(r for r, _ in rings)
    for radius, z in rings:
        for j in range(segments):
            a = math.tau * j / segments
            r = radius - min(.16, radius*.035) * (j % 2) if teeth and radius > outer*.95 else radius
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for k in range(len(rings)-1 if caps else len(rings)):
        for j in range(segments):
            a, b = k*segments+j, k*segments+(j+1)%segments
            nxt = ((k+1) % len(rings))*segments
            faces.append((a, b, nxt+(j+1)%segments, nxt+j))
    if caps:
        faces += [tuple(reversed(range(segments))), tuple((len(rings)-1)*segments+j for j in range(segments))]
    return _mesh(name, verts, faces)


def _spring(name, radius, lo, hi):
    wire = radius * .23
    coil = radius-wire
    steps, sides = 240, 10
    verts, faces = [], []
    for i in range(steps+1):
        a = math.tau * 7 * i/steps
        z = lo+wire + (hi-lo-2*wire)*i/steps
        for j in range(sides):
            b = math.tau*j/sides
            r = coil+wire*math.cos(b)
            verts.append((r*math.cos(a), r*math.sin(a), z+wire*math.sin(b)))
    for i in range(steps):
        for j in range(sides):
            a, b = i*sides+j, i*sides+(j+1)%sides
            faces.append((a,b,b+sides,a+sides))
    faces += [tuple(reversed(range(sides))), tuple(steps*sides+j for j in range(sides))]
    return _mesh(name, verts, faces)


def _child(coll, parent, name, data):
    ob = bpy.data.objects.new('OAR_HW_'+name, data)
    coll.objects.link(ob)
    ob[TAG] = True
    ob.optics.is_optical = False
    ob.parent = parent
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = Matrix.Identity(4)
    # Per-view-layer visibility: hidden in simulation, included in camera renders.
    for layer in bpy.context.scene.view_layers:
        if ob.name in layer.objects:
            ob.hide_set(True, view_layer=layer)
    ob.hide_select = True
    return ob


def _scale(coll, parent, radius, z):
    verts, faces = [], []
    for i in range(180):
        a = math.tau*i/180
        outer = radius-.7
        inner = outer-(2.3 if i%5 == 0 else 1.1)
        n = len(verts)
        for r, da in ((inner,-.0025),(outer,-.0025),(outer,.0025),(inner,.0025)):
            verts.append((r*math.cos(a+da),r*math.sin(a+da),z+.015))
        faces.append((n,n+1,n+2,n+3))
    ticks = _child(coll,parent,'Scale2deg',_mesh('Scale2deg',verts,faces))
    ticks.data.materials.append(material('engraving'))
    for deg in range(0,360,30):
        a = math.radians(deg)
        curve = bpy.data.curves.new('ScaleNumber','FONT')
        curve.body = str(deg)
        curve.size = 1.65
        curve.align_x = 'CENTER'
        curve.align_y = 'CENTER'
        ob = _child(coll,parent,'ScaleNumber',curve)
        ob.location = ((radius-4.5)*math.cos(a),(radius-4.5)*math.sin(a),z+.025)
        ob.rotation_euler.z = a-math.pi/2
        curve.materials.append(material('engraving'))



def _fasteners(coll, parent, coords, cage=False):
    bounds=[(min(v[i] for v in coords),max(v[i] for v in coords)) for i in range(3)]
    axis=min(range(3),key=lambda i:bounds[i][1]-bounds[i][0])
    other=[i for i in range(3) if i!=axis]
    from mathutils import Vector
    rotation=Vector((0,0,1)).rotation_difference(Vector(tuple(1 if i==axis else 0 for i in range(3))))
    for a,b in ((-1,-1),(-1,1),(1,-1),(1,1)):
        loc=[0.,0.,0.]
        loc[axis]=bounds[axis][1]+.1
        for i,sign in zip(other,(a,b)):
            lo,hi=bounds[i]
            loc[i]=(lo+hi)/2+sign*max((hi-lo)/2-3,1)
        if cage:
            loc[other[0]]=0 if a<0 else loc[other[0]]
            loc[other[1]]=loc[other[1]] if a<0 else 0
            if a>0: loc[other[0]]*=b
        mesh=_lathe('SocketHead',[(.65,-.1),(1.4,-.1),(1.4,.5),(.65,.5)],segments=32,caps=False)
        ob=_child(coll,parent,'SocketHead',mesh)
        ob.location=loc
        ob.rotation_mode='QUATERNION';ob.rotation_quaternion=rotation
        mesh.materials.append(material('steel'))
        ob['detail_features']='fastener'


def clear(scene):
    for ob in list(scene.objects):
        if ob.get(TAG):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data and data.users == 0:
                if isinstance(data,bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data,bpy.types.Curve):
                    bpy.data.curves.remove(data)
        elif '_oar_hide_render' in ob:
            ob.hide_render = bool(ob['_oar_hide_render'])
            del ob['_oar_hide_render']
    for coll in list(bpy.data.collections):
        if coll.get(TAG) and not coll.objects:
            bpy.data.collections.remove(coll)
    if scene.get('_oar_auto_bench'):
        del scene['_oar_auto_bench']
        from . import optomech
        optomech.strip(scene)


def _prepare(scene):
    """Create render-only replacements; repeat calls rebuild without accumulating objects."""
    from . import optomech, geometry
    if geometry.mm_per_unit(scene) != 1.0:
        raise ValueError("Detailed hardware requires millimetre scene units; convert the scene to mm first")
    clear(scene)
    if not optomech.is_dressed(scene):
        optomech.dress(scene)
        scene['_oar_auto_bench'] = True
    sources = [o for o in scene.objects if o.name.startswith('BENCH_') and o.type == 'MESH']
    coll = bpy.data.collections.new(COLLECTION)
    coll[TAG] = True
    scene.collection.children.link(coll)
    try:
        for src in sources:
            if src.hide_render:
                continue
            src['_oar_hide_render'] = src.hide_render
            src.hide_render = True
            name = src.name.removeprefix('BENCH_')
            if name.startswith('RSPtick'):
                continue
            mesh = src.data.copy()
            coords = [v.co for v in mesh.vertices]
            if not coords:
                bpy.data.meshes.remove(mesh)
                continue
            r = max(v.xy.length for v in coords)
            lo, hi = min(v.z for v in coords), max(v.z for v in coords)
            knob = bool(re.match(r'A\dk_|Lockh_|XSknob_|GMadjust_|StageKnob\d_|RailLockh_',name))
            spring = bool(re.match(r'S[01]_',name))
            post = bool(re.match(r'(Post|RailPost|TubePost|CagePost)_',name))
            shaft = bool(re.match(r'A\d[sb]_|Locks_|StageMic\d_|RailLocks_|CageRod_|TRFpivot_|GMpivot_[LR]_|VCbolt_[LR]_|Cmount_|CamStem_|PlatformStem_',name))
            ring = name.startswith('RSPring_')
            cell = bool(re.match(r'(RSPhousing|Cell|GMcell|GMyoke|TRFcell|XScell|StageCell|IrisCell|Tube|TubeRetainer|CageRetainer)_',name))
            if knob or spring or post or ring or shaft or cell:
                old = mesh
                if ring or cell:
                    inner = min(v.xy.length for v in coords)
                    mesh = _lathe(name,[(inner,lo),(r*.98,lo),(r,lo+.3),(r,hi-.3),(r*.98,hi),(inner,hi)],segments=256 if ring else 128,teeth=int(ring),caps=False)
                elif spring:
                    mesh = _spring(name,r,lo,hi)
                else:
                    edge = min(.3,(hi-lo)*.1)
                    mesh = _lathe(name,[(r*.94,lo),(r,lo+edge),(r,hi-edge),(r*.94,hi)],teeth=int(knob))
                bpy.data.meshes.remove(old)
            ob = _child(coll,src,name,mesh)
            ob['detail_features'] = 'spring' if spring else 'knurl' if knob or ring else 'turned_surface' if post or shaft or cell else 'machined_material'
            kind = 'anodized'
            original = src.data.materials[0].name if src.data.materials else ''
            if original in ('OB_steel','OB_post'): kind = 'steel'
            if name.startswith('Tube_'): kind = 'anodized'
            elif original == 'OB_alu': kind = 'aluminium'
            elif original == 'OB_board': kind = 'board'
            elif original == 'OB_hole': kind = 'dark'
            if src.parent and getattr(src.parent,'optics',None):
                if PROFILES.get(src.parent.optics.mount_preset) == 'steel' and name.startswith('KM'):
                    kind = 'steel'
            mesh.materials.clear()
            mesh.materials.append(material(kind))
            # Smooth curved surfaces only; preserve machined planar faces and bores.
            for face in mesh.polygons:
                face.use_smooth = spring or name.startswith('KMpivot_') or (len(face.vertices) == 4 and abs(face.normal.z) < .95 and (post or shaft or cell))
            if re.match(r'(KMback|CamBody|Carrier|VCbase|TRFbase|XSbase|StagePlate\d|PrismPlatform|RailFlange|CagePlate)_',name):
                _fasteners(coll,src,coords,cage=name.startswith('CagePlate_'))
                ob['detail_features'] += ',fasteners'
            if name.startswith('RSPring_'):
                _scale(coll,src,r,hi)
            if post and hi-lo > 20:
                # Published TR cross-hole diameter; axial station is a visual estimate.
                bpy.context.view_layer.update()
                ob.hide_set(False)
                optomech._bore_local(ob,ob.matrix_world.copy(),(0,0,hi-7),1.6,2*r+2,axis='X',seg=32)
                ob.hide_set(True)
        bpy.context.view_layer.update()
    except Exception:
        clear(scene)
        raise
    for ob in coll.objects:
        ob.hide_set(True)
    coll.hide_viewport = True
    return len(coll.objects)


def prepare(scene):
    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    try:
        return _prepare(scene)
    finally:
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
        for ob in selected:
            if ob.name in scene.objects:
                ob.select_set(True)
        if active and active.name in scene.objects:
            bpy.context.view_layer.objects.active = active
