"""Additional generic hardware families; envelopes/travel are design estimates, not vendor specs."""
PRODUCTS = {}
for size, diameter in (('05',12.7),('1',25.4),('2',50.8)):
    for family, element, mount in (('KINEMATIC','MIRROR','KINEMATIC_2AXIS'),
                                   ('ROTATION','WAVEPLATE','ROTATION'),
                                   ('LENS_CELL','LENS','FIXED')):
        if size == '1' and family != 'LENS_CELL':
            continue
        PRODUCTS[family+'_'+size] = dict(family=family,element=element,mount=mount,diameter=diameter)
for key, family, element in (('XY_1','XY','LENS'),('XYZ_1','XYZ','LENS'),
                            ('PRISM_PLATFORM','PLATFORM','PRISM'),('IRIS_1','IRIS','APERTURE')):
    PRODUCTS[key] = dict(family=family,element=element,mount='TRANSLATION' if family in ('XY','XYZ') else 'FIXED',diameter=25.4)
for key, diameter, support in (('CAGE16',12.7,'CAGE_16'),('CAGE60',50.8,'CAGE_60'),
                              ('TUBE_SM05',12.7,'TUBE_SM05'),('TUBE_SM1',25.4,'TUBE_SM1'),
                              ('TUBE_SM2',50.8,'TUBE_SM2')):
    PRODUCTS[key] = dict(family='TUBE' if key.startswith('TUBE') else 'CAGE',element='LENS',mount='FIXED',diameter=diameter,support=support)


def mount_presets():
    presets = {}
    for key, product in PRODUCTS.items():
        f = product['family']
        axes = [('TIP','+X'),('TILT','+Y')] if f == 'KINEMATIC' else [('ROT','+Z')] if f == 'ROTATION' else [('TRANS_'+axis,'+'+axis) for axis in f] if f in ('XY','XYZ') else []
        dofs = [dict(kind=kind,axis=axis,min=0 if f=='ROTATION' else -2.5 if f in ('XY','XYZ') else -4,
                     max=360 if f=='ROTATION' else 2.5 if f in ('XY','XYZ') else 4,
                     step=.1 if f in ('XY','XYZ') else .5) for kind,axis in axes]
        presets[key] = dict(mount_type=product['mount'],pivot='OPTIC_CENTER',
                            optic_diameter_mm=product['diameter'],clear_aperture_mm=product['diameter']*.88,
                            visual_family=f,support_system=product.get('support','POST'),dofs=dofs,
                            note='Generic procedural '+f.lower()+'; dimensions and travel are design estimates, not vendor specifications.')
    return presets


def build(key, G, mounts):
    from mathutils import Vector
    p = PRODUCTS[key]
    c = G.example_collection('Hardware_'+key)
    loc, axis, radius = (0,0,100), Vector((1,0,0)), p['diameter']/2
    if p['element']=='MIRROR':
        ob=G.mirror('HW_'+key,loc,axis,Vector((0,1,0)),c,size=radius*2)
    elif p['element']=='WAVEPLATE':
        ob=G.waveplate('HW_'+key,loc,axis,c)
        # Scale the geometry and ports together through the existing substrate API below.
        from . import geometry
        current=max(v.co.xy.length for v in ob.data.vertices)
        factor=radius/current
        for v in ob.data.vertices:
            v.co.x*=factor; v.co.y*=factor
    elif p['element']=='PRISM':
        ob=G.prism('HW_'+key,loc,axis,c,face_mm=25.4,depth_mm=20)
    elif p['element']=='APERTURE':
        ob=G.aperture('HW_'+key,loc,axis,c,radius=radius*.5)
    else:
        ob=G.lens('HW_'+key,loc,axis,c,radius=radius,focal=150)
    import bpy
    ob.data.update()
    bpy.context.view_layer.update()
    ok,msg=mounts.apply_preset(ob,key)
    if not ok: raise RuntimeError(msg)
    if p['element']=='APERTURE':
        ob.optics.clear_aperture=radius*.5
    for port in ob.optics.ports:
        port.clear_aperture=ob.optics.clear_aperture
    if p.get('support','').startswith('CAGE_'):
        other=G.lens('HW_'+key+'_end',(50,0,100),axis,c,radius=radius,focal=150)
        ok,msg=mounts.apply_preset(other,key)
        if not ok: raise RuntimeError(msg)
        other.optics.cage_id=ob.optics.cage_id
    return ob


def build_cage30(G, mounts):
    from mathutils import Vector
    c=G.example_collection('Hardware_CAGE30')
    first=None
    for i in range(2):
        ob=G.lens('HW_CAGE30_%d'%i,(50*i,0,100),Vector((1,0,0)),c,radius=12.7)
        ob.optics.support_system='CAGE_30'
        ob.optics.cage_id='catalog_cage30'
        first=first or ob
    return first
