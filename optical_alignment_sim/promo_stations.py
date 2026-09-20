"""New promo station hardware, original visual designs, not vendor-certified CAD.
Optical objects/ports stay untouched; only non-optical render components are added.
"""
import math
import bpy
from mathutils import Matrix,Vector
from . import promo_hardware as H


def ring(name,outer,inner,depth,loc,coll,axis=(0,0,1),kind='anodized'):
    ob=H.cylinder(name,outer,depth,loc,coll,kind,axis=axis)
    H.bore(ob,inner,depth+2,loc,coll,axis)
    return ob


def rebuild(coll,optic,oldpost):
    family={'SOURCE':'LaserHead','LENS':'LensCell','PASSTHROUGH':'WindowCell',
            'WAVEPLATE':'RotationMount','POLARIZER':'RotationMount',
            'BEAMSPLITTER':'CubeHousing','DETECTOR':'DetectorHousing'}[optic.optics.element_type]
    before=set(coll.objects)
    et=optic.optics.element_type
    # Gravity-aligned local frame: X right, Y up, Z along optical normal.
    n=optic.matrix_world.to_3x3().col[2].normalized();up=Vector((0,0,1))
    if et=='BEAMSPLITTER':
        frame=optic.matrix_world.copy()
    else:
        right=up.cross(n).normalized()
        frame=Matrix(((right.x,up.x,n.x,optic.location.x),(right.y,up.y,n.y,optic.location.y),
                      (right.z,up.z,n.z,optic.location.z),(0,0,0,1)))
    drop=20
    if et in {'LENS','PASSTHROUGH','WAVEPLATE','POLARIZER'}:
        r=float(optic.optics.clear_aperture)
        rotation=et in {'WAVEPLATE','POLARIZER'}
        outer=r+(8 if rotation else 4)
        ring('NEW_CellBarrel',outer,r+.15,8,(0,0,0),coll)
        # Retaining rings with real spanner slots; aperture left fully open.
        for side in (-1,1):
            ret=ring('NEW_RetainingRing',r+1.6,r-.6,1.5,(0,0,side*4.7),coll,kind='steel')
            for sx in (-1,1):
                H.cut(ret,H.box('spanner_cut',(3,1.2,2),(sx*(r+.6),0,side*4.7),coll,bevel=0))
        drop=outer+5
        H.box('NEW_CellFoot',(12,6,8),(0,-outer-2,0),coll)
        if rotation:
            grip=H.knurled('NEW_RotationGrip',r+4,4,(0,0,6),coll)
            H.bore(grip,r+.1,8,(0,0,6),coll)
            for deg in range(0,360,5):
                a=math.radians(deg);length=2.2 if deg%30==0 else 1
                tick=H.box('NEW_AngleTick',(.18,length,.08),((outer-1.8)*math.sin(a),(outer-1.8)*math.cos(a),4.06),coll,'engraving',0)
                tick.rotation_euler.z=-a
            H.cylinder('NEW_RotationLockShaft',1.4,7,(outer+1,0,0),coll,axis=(1,0,0))
            H.knurled('NEW_RotationLock',3.5,4,(outer+5,0,0),coll,(1,0,0))
            H.label('0',(-.8,outer-5,4.12),coll,2)
        else:
            H.socket_screw('NEW_CellRadialScrew',2,4,(outer-1,0,0),coll,axis=(1,0,0))
        H.label('ROT' if rotation else 'LENS' if et=='LENS' else 'WINDOW',(-5,-outer-2,4.1),coll,1.4)
    elif et=='BEAMSPLITTER':
        body=H.box('NEW_CubeHousing',(38,38,32),(0,0,0),coll,bevel=.5)
        H.cut(body,H.box('cube_pocket',(25.4,25.4,26),(0,0,.3),coll,bevel=0))
        for axis in ((1,0,0),(0,1,0)):
            H.bore(body,11.5,44,(0,0,0),coll,axis)
            for sign in (-1,1):
                pos=Vector(axis)*sign*19
                ring('NEW_CubePort',14,11.5,2,pos,coll,axis)
        lid=H.box('NEW_CubeLid',(38,38,2),(0,0,17),coll,bevel=.35)
        for xx in (-15,15):
            for yy in (-15,15):H.socket_screw('NEW_LidScrew',2,3,(xx,yy,15.8),coll)
        H.label('BS  50:50',(-11,-3,18.05),coll,2.4)
        H.box('NEW_CubeFoot',(16,16,3),(0,0,-17.5),coll)
        drop=19
    elif et=='SOURCE':
        ring('NEW_LaserBarrel',8.5,7.05,40,(0,0,0),coll)
        ring('NEW_LaserBezel',9.5,3.6,3,(0,0,21),coll,kind='steel')
        H.cylinder('NEW_LaserRear',8.5,3,(0,0,-21.5),coll)
        for zz in (-12,10):ring('NEW_LaserClamp',11,8.5,5,(0,0,zz),coll)
        H.box('NEW_LaserSaddle',(18,4,29),(0,-11,0),coll)
        H.box('NEW_LaserFoot',(12,3,12),(0,-14,0),coll)
        for sx in (-1,1):H.socket_screw('NEW_LaserClampBolt',2,4,(sx*9,-6,10),coll,axis=(0,1,0))
        ring('NEW_PowerConnector',3,1.5,6,(0,0,-26),coll,kind='steel')
        H.label('532 nm',(-4,-6,24),coll,1.5)
        drop=15.5
    else:
        # Rear shell around the existing sensor, open front; render-only electronics details.
        side=36 if optic.optics.clear_aperture>=15 else 30
        body=H.box('NEW_DetectorShell',(side,side,28),(0,0,-10),coll,bevel=.8)
        H.cut(body,H.box('sensor_pocket',(side-4,side-4,25),(0,0,-5),coll,bevel=0))
        for xx in (-side/2+4,side/2-4):
            for yy in (-side/2+4,side/2-4):H.socket_screw('NEW_SensorFaceScrew',1.7,3,(xx,yy,2),coll)
        # Rear fin grooves and two connector sockets.
        for xx in range(-8,9,4):H.cut(body,H.box('fin_cut',(1,side-8,1.6),(xx,0,-24),coll,bevel=0))
        ring('NEW_DetectorConnector',3.5,2,5,(8,0,-26),coll,kind='steel')
        H.box('NEW_DataPort',(8,5,3),(-7,0,-25),coll,'dark',.3)
        H.label('CAM' if side==36 else 'MON',(-6,-side/2+3,4.1),coll,2)
        H.box('NEW_DetectorFoot',(14,4,14),(0,-side/2-2,-8),coll)
        drop=side/2+4
    bpy.context.view_layer.update()
    members=set(coll.objects)-before
    for p in members:
        world=frame @ p.matrix_world;p.parent=optic;p.matrix_world=world
        p['promo_part_group']=family;p['oa_owner']=optic.get('oa_owner')
        p['visual_design']='custom; internal fits unverified'
    # Fresh post fits the new housing underside; bottom and holder insertion stay fixed.
    coords=[oldpost.matrix_world @ Vector(v) for v in oldpost.bound_box]
    bottom=min(v.z for v in coords); top=optic.location.z-drop
    center=oldpost.matrix_world.translation
    assert top>bottom+12
    post=H.cylinder('NEW_StationPost',6.35,top-bottom,(center.x,center.y,(top+bottom)/2),coll,'steel')
    H.bore(post,1.6,16,(center.x,center.y,top-8),coll,(1,0,0))
    bpy.context.view_layer.update();world=post.matrix_world.copy();post.parent=optic;post.matrix_world=world
    post['station_post']=True;post['promo_part_group']=family;post['oa_owner']=optic.get('oa_owner')
    optic['promo_station_family']=family
    return family
