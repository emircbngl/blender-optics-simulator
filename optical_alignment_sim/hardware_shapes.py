"""Basic geometry for new generic platform/translation/iris families."""
from mathutils import Matrix, Vector


def support_drop(ob):
    from . import hardware_catalog as catalog
    p=catalog.PRODUCTS.get(ob.optics.mount_preset)
    if not p: return 15.0
    if p['family'] in ('XY','XYZ'): return p['diameter']/2+20
    from . import geometry
    lo,hi,_=geometry.local_bounds(ob)
    radius=max(hi.x-lo.x,hi.y-lo.y)/2
    ca=max(ob.optics.clear_aperture,6.0)
    if p['family']=='LENS_CELL': return ca*1.5-1.0
    if p['family']=='KINEMATIC': return max(ca*1.3,radius*1.3)-.5
    if p['family']=='IRIS': return radius+1.0
    return max(15.0,p['diameter']/2+3)


def build(ob, coll, idx):
    from . import hardware_catalog as catalog, optomech as G, geometry
    spec=catalog.PRODUCTS.get(ob.optics.mount_preset)
    if not spec or spec['family'] not in ('XY','XYZ','PLATFORM','IRIS'):
        return None
    before=len(coll.objects)
    prefix='BENCH_'
    tag='%02d'%idx
    p=ob.matrix_world.translation
    frame=G._gravity_frame(p,ob.matrix_world.to_3x3() @ Vector((0,0,1)))
    lo,hi,_=geometry.local_bounds(ob)
    radius=max(hi.x-lo.x,hi.y-lo.y)/2
    drop=support_drop(ob)
    if spec['family'] in ('XY','XYZ'):
        axes=2 if spec['family']=='XY' else 3
        width=max(40,radius*2+12)
        for i in range(axes+1):
            G._bevel(G._obox(prefix+'StagePlate%d_'%i+tag,(width,3.0,width),frame,
                            (0,-drop+1.5+i*3.5,-width/2-5),coll,'mount'),.5,2)
        for i in range(axes):
            axis=('X','Y','Z')[i]
            off=(width/2+5,-drop+5,-width/2-5) if axis=='X' else (0,-drop+axes*3.5+12,-width/2-5) if axis=='Y' else (0,-drop+8,-width-10)
            G._ocyl(prefix+'StageMic%d_'%i+tag,2.2,12,frame,off,coll,'steel',axis=axis)
            end=Vector(off);end.x+=7 if axis=='X' else 0;end.y+=7 if axis=='Y' else 0;end.z-=7 if axis=='Z' else 0
            G._ocyl(prefix+'StageKnob%d_'%i+tag,3.8,5,frame,end,coll,'steel',axis=axis)
        cell=G._ocyl(prefix+'StageCell_'+tag,radius+4,6,frame,(0,0,-1),coll,'mount')
        G._bore_local(cell,frame,(0,0,-1),radius+.2,12)
        G._bevel(cell,.5,2)
        riser_bottom=-drop+3+axes*3.5
        riser_top=-radius+2
        height=max(riser_top-riser_bottom,2)
        G._bevel(G._obox(prefix+'StageRiser_'+tag,(10,height,7),frame,
                        (0,(riser_bottom+riser_top)/2,-5),coll,'mount'),.5,2)
    elif spec['family']=='PLATFORM':
        corners=[ob.matrix_world@Vector(v) for v in ob.bound_box]
        bottom=min(v.z for v in corners)
        x0,x1=min(v.x for v in corners)-3,max(v.x for v in corners)+3
        y0,y1=min(v.y for v in corners)-3,max(v.y for v in corners)+3
        G._bevel(G._box(prefix+'PrismPlatform_'+tag,(x1-x0,y1-y0,4),((x0+x1)/2,(y0+y1)/2,bottom-2),coll,'mount'),.5,2)
        # Pads grip the lower side edges, clear of the central optical beam.
        for sign in (-1,1):
            x=x0+1 if sign<0 else x1-1
            G._box(prefix+'PrismPad%d_'%sign+tag,(2,y1-y0,3),(x,(y0+y1)/2,bottom+.5),coll,'dark' if 'dark' in G._MATS else 'mount')
        post_top=p.z-drop
        if bottom-4>post_top:
            G._cyl(prefix+'PlatformStem_'+tag,4,bottom-4-post_top,(p.x,p.y,(bottom-4+post_top)/2),coll,'steel')
    else:
        # An iris already has leaf geometry: support its housing without covering its aperture.
        cell=G._ocyl(prefix+'IrisCell_'+tag,radius+2,4,ob.matrix_world,(0,0,-3),coll,'mount')
        G._bore_local(cell,ob.matrix_world,(0,0,-3),radius-.5,12)
        G._bevel(cell,.4,2)
    return len(coll.objects)-before
