"""Fresh, separately modelled promotional hardware. Nominal dimensions are source-backed;
undimensioned details remain visual estimates, NOT assembly-training certified parts.
No reuse of the previous BENCH mesh or detail-cloning pipeline.
"""
import math
import bpy
from mathutils import Vector, Matrix
from .hardware_render import material


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def finish(ob, name, coll, kind='anodized', bevel=.25):
    ob.name = name
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)
    ob.data.materials.append(material(kind))
    ob.optics.is_optical = False
    ob['promo_fidelity'] = 'nominal dimensions; undimensioned detail estimated'
    if bevel:
        mod = ob.modifiers.new('Machined edge', 'BEVEL'); mod.width = bevel; mod.segments = 3
    for p in ob.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    return ob


def box(name, size, loc, coll, kind='anodized', bevel=.25):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = bpy.context.object; ob.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(ob,name,coll,kind,bevel)


def cylinder(name, radius, depth, loc, coll, kind='steel', axis=(0,0,1), vertices=96, bevel=.15):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    ob=bpy.context.object
    ob.rotation_euler=Vector(axis).to_track_quat('Z','Y').to_euler()
    return finish(ob,name,coll,kind,bevel)


def cut(ob, cutter):
    # Boolean before bevel: machined openings get the same edge treatment as the body.
    m=ob.modifiers.new('Machined opening','BOOLEAN');m.operation='DIFFERENCE';m.object=cutter
    bpy.context.view_layer.objects.active=ob
    if len(ob.modifiers) > 1:
        bpy.ops.object.modifier_move_up(modifier=m.name)
    bpy.ops.object.modifier_apply(modifier=m.name)
    mesh=cutter.data;bpy.data.objects.remove(cutter,do_unlink=True)
    if mesh.users==0:bpy.data.meshes.remove(mesh)


def bore(ob,r,depth,loc,coll,axis=(0,0,1),vertices=96):
    cut(ob,cylinder('cutter',r,depth,loc,coll,axis=axis,vertices=vertices,bevel=0))


def capsule(ob,width,length,depth,loc,coll,axis='Y'):
    x,y,z=loc
    size=(length-width,width,depth) if axis=='X' else (width,length-width,depth)
    cut(ob,box('slot',size,loc,coll,bevel=0))
    for sign in (-1,1):
        d=sign*(length-width)/2
        bore(ob,width/2,depth,(x+d,y,z) if axis=='X' else (x,y+d,z),coll)


def knurled(name,r,depth,loc,coll,axis=(0,0,1)):
    vertices=[];faces=[];segments=96;rings=9
    for k in range(rings):
        for j in range(segments):
            radius=r-(.22 if (j+k)%2 else 0)
            a=j*math.tau/segments
            vertices.append((radius*math.cos(a),radius*math.sin(a),depth*(k/(rings-1)-.5)))
    for k in range(rings-1):
        for j in range(segments):
            a=k*segments+j;b=k*segments+(j+1)%segments
            faces.extend(((a,b,a+segments),(b,b+segments,a+segments)))
    faces.extend((tuple(reversed(range(segments))),tuple((rings-1)*segments+j for j in range(segments))))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    ob=bpy.data.objects.new(name,mesh);coll.objects.link(ob);ob.location=loc
    ob.rotation_euler=Vector(axis).to_track_quat('Z','Y').to_euler()
    return finish(ob,name,coll,'anodized',0)


def thread(name,r,pitch,length,loc,coll,axis=(0,0,1)):
    # Cosmetic crest follows nominal pitch; not a thread contact solver or tolerance model.
    curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='3D'
    curve.bevel_depth=pitch*.16;curve.bevel_resolution=2
    spl=curve.splines.new('POLY');steps=max(48,int(length/pitch*32));spl.points.add(steps)
    for j,p in enumerate(spl.points):
        z=length*j/steps;a=math.tau*z/pitch
        p.co=(r*math.cos(a),r*math.sin(a),z,1)
    ob=bpy.data.objects.new(name,curve);coll.objects.link(ob);ob.location=loc
    ob.rotation_euler=Vector(axis).to_track_quat('Z','Y').to_euler()
    curve.materials.append(material('steel'));ob.optics.is_optical=False
    return ob


def socket_screw(name,r,length,loc,coll,axis=(0,0,1)):
    shaft=cylinder(name+'_shaft',r*.58,length,loc,coll,axis=axis)
    top=Vector(loc)+Vector(axis)*(length*.5+1.8)
    head=cylinder(name+'_head',r,3.6,top,coll,axis=axis)
    bore(head,r*.52,2.2,top+Vector(axis)*1.1,coll,axis,6)
    return shaft,head


def label(text,loc,coll,size=2.2,rotation=(0,0,0)):
    d=bpy.data.curves.new('Etching','FONT');d.body=text;d.size=size;d.extrude=0
    ob=bpy.data.objects.new('Etching_'+text,d);coll.objects.link(ob)
    ob.location=loc;ob.rotation_euler=rotation;d.materials.append(material('engraving'))
    return ob


def post_holder(coll,xy=(0,0),bottom_z=10,bore_depth=43.2):
    """50 mm holder; deeper bore is a labelled custom visual variant, not PH50/M CAD."""
    x,y=xy
    before=set(coll.objects)
    holder=cylinder('NEW_PH50M_body',12.5,50,(x,y,35),coll,'anodized')
    bore(holder,6.4,bore_depth+1,(x,y,60-bore_depth/2+.5),coll) # bottom datum 16.8; open top
    # Estimated lead-in chamfer; preserve the nominal 12.8 mm bore below it.
    bpy.ops.mesh.primitive_cone_add(vertices=96,radius1=6.4,radius2=7.05,
                                    depth=.65,location=(x,y,59.725))
    cut(holder,bpy.context.object)
    bore(holder,3,12,(x,y,12),coll)
    bore(holder,3,15,(x+10,y,50),coll,(1,0,0))
    # Tip terminates at the post surface (x+6.35), rather than entering its solid.
    # Internal spring dimensions are unavailable: do not invent a working spring model.
    tip=cylinder('NEW_HolderPressureTip',1.8,1.5,(x+7.10,y,50),coll,axis=(1,0,0),bevel=.08)
    shaft=cylinder('NEW_HolderLockShaft',2.8,8.65,(x+11.425,y,50),coll,axis=(1,0,0))
    collar=cylinder('NEW_HolderThumbscrewShoulder',4.1,2.2,(x+14,y,50),coll,'anodized',axis=(1,0,0))
    knob=knurled('NEW_HolderThumbscrew',7.25,8,(x+19,y,50),coll,(1,0,0))
    # Blender polygon radius is circumradius; AF5 requires r = 5 / sqrt(3).
    bore(knob,5/math.sqrt(3),4,(x+22,y,50),coll,(1,0,0),6)
    knob['hex_across_flats_mm']=5.0
    knob['nominal_thread']='M6 x 1.0; cosmetic geometry, fit unverified'
    tip['minimum_local_x_mm']=x+6.35
    holder['geometry_revision']='PH50M-visual-r2'
    # Planar top and bottom stay flat; cylindrical wall normals stay smooth.
    for face in holder.data.polygons:
        face.use_smooth=abs(face.normal.z)<.9
    etch=label('PH50 / M' if bore_depth==43.2 else 'POST HOLDER',(x-4,y-12.55,33),coll,2.1,(math.pi/2,0,0))
    members=set(coll.objects)-before
    for obj in members:
        obj.location.z+=bottom_z-10
        obj['promo_part_group']='PH50M'
    holder['target_part']='PH50/M'
    holder['bore_depth_mm']=bore_depth
    holder['variant']='nominal PH50/M' if bore_depth==43.2 else 'custom deeper bore visual variant'
    return holder,members


def support(coll,xy=(0,0),post_top=84.6):
    """BA2/M envelope + PH50/M envelope/bore + TR50/M nominal post.
    Base top datum is 10 mm. Post tip must leave 10..43.2 mm in holder.
    """
    x,y=xy
    before=set(coll.objects)
    insertion=60-(post_top-50)
    if not 10 <= insertion <= 43.2:
        raise ValueError('50 mm post/holder pair cannot reach requested height with specified insertion')
    base=box('NEW_BA2M_body',(50,75,10),(x,y,5),coll)
    for dx in (-16,16):
        capsule(base,6.6,45,12,(x+dx,y,5),coll)
        capsule(base,11,49,5,(x+dx,y,8.5),coll)
    bore(base,3.3,12,(x,y,5),coll)
    bore(base,5.5,5,(x,y,1.5),coll)
    cut(base,box('underside_relief',(34,57,1),(x,y,0),coll,bevel=0))
    # Deliberately separate fasteners and washer seats for assembly/exploded shots.
    for dx in (-16,16):
        cylinder('NEW_BaseWasher',6,1.2,(x+dx,y,7.1),coll)
        socket_screw('NEW_BaseBolt',5,7,(x+dx,y,4),coll)
    base_parts=set(coll.objects)-before
    before=set(coll.objects)
    holder,holder_parts=post_holder(coll,(x,y))
    before=set(coll.objects)
    post=cylinder('NEW_TR50M_body',6.35,50,(x,y,post_top-25),coll,'steel',bevel=.3)
    bore(post,1.6,16,(x,y,post_top-10),coll,(1,0,0))
    bore(post,3,8,(x,y,post_top-48),coll)
    stud=cylinder('NEW_M4_stud',1.65,6,(x,y,post_top+3),coll,'steel',bevel=0)
    thread('NEW_M4_crest',1.85,.7,6,(x,y,post_top),coll)
    post_parts=set(coll.objects)-before
    label('METRIC',(x-9,y-30,10.02),coll,2)
    for members,part in ((base_parts,'BA2M'),(holder_parts,'PH50M'),(post_parts,'TR50M')):
        for obj in members:obj['promo_part_group']=part
    for obj,part in ((base,'BA2/M'),(holder,'PH50/M'),(post,'TR50/M')):
        obj['target_part']=part
        obj['nominal_dimensions_checked']=True
    return base,holder,post


def mirror_mount(coll,optic):
    """Independent E-series 15-866 visual reconstruction. Local +Z is optic normal.
    Source-backed: 43.5 mm envelope, optic height 25.4, CA23, optic25/25.4.
    Plate thickness, adjuster offsets, springs and seat geometry remain estimates.
    """
    before=set(coll.objects)
    for z in (-6,-17):
        plate=box('NEW_EO15866_plate',(43.5,43.5,6),(0,-3.65,z),coll)
        bore(plate,11.5,10,(0,0,z),coll)
        if z==-6:
            bore(plate,12.7,5,(0,0,-3.5),coll)
        for xx,yy in ((-16,-19),(16,12)):
            bore(plate,3.1,10,(xx,yy,z),coll)
    seat=cylinder('NEW_OpticSeat',14,2.5,(0,0,-2),coll,'anodized')
    bore(seat,11.5,4,(0,0,-2),coll)
    box('NEW_PostSeatBridge',(16,4,17),(0,-23.4,-12),coll)
    for xx,yy in ((-16,-19),(16,12)):
        cylinder('NEW_AdjusterBush',4,7,(xx,yy,-20),coll,'aluminium')
        cylinder('NEW_AdjusterShaft',2.65,20,(xx,yy,-18),coll,'steel')
        thread('NEW_AdjusterThread',2.9,.25,7,(xx,yy,-29),coll)
        knob=knurled('NEW_AdjusterKnob',6,7,(xx,yy,-30),coll)
        bore(knob,1.15,4,(xx,yy,-33),coll,vertices=6)
    for xx,yy in ((-16,12),(16,-19)):
        thread('NEW_ReturnSpring',2,1.3,6,(xx,yy,-14),coll)
        for zz in (-14,-8):cylinder('NEW_SpringSeat',2.4,1,(xx,yy,zz),coll,'steel')
    cylinder('NEW_PivotBall',2,5,(-16,12,-12),coll,'steel')
    for xx in (-11,11):
        socket_screw('NEW_FrontFastener',2,3,(xx,10,-1.5),coll)
    label('25.4  /  E-SERIES',(-13,-21,-2.95),coll,1.6)
    bpy.context.view_layer.update()
    normal=optic.matrix_world.to_3x3().col[2].normalized()
    up=Vector((0,0,1)); right=up.cross(normal).normalized()
    frame=Matrix(((right.x,up.x,normal.x,optic.location.x),
                  (right.y,up.y,normal.y,optic.location.y),
                  (right.z,up.z,normal.z,optic.location.z),(0,0,0,1)))
    for ob in set(coll.objects)-before:
        ob['promo_part_group']='EO15866'
        ob.matrix_world=frame @ ob.matrix_world
        mw=ob.matrix_world.copy();ob.parent=optic;ob.matrix_world=mw
    return list(set(coll.objects)-before)


def table_base(coll, holder, grid):
    """Custom slotted base matched to actual grid holes; not a vendor CAD replica."""
    bpy.context.view_layer.update()
    x,y,zc=holder.matrix_world.translation
    z=grid['board_top_z_mm']; height=zc-25-z
    assert 8<=height<=14,height
    pitch=grid['pitch_mm']; x0,y0=grid['origin']
    assert grid['thread']=='M6','This visual fastener set requires the metric scene'
    bx=x0+round((x-x0)/pitch)*pitch
    ys=[y0+math.floor((y-19-y0)/pitch)*pitch,
        y0+math.ceil((y+19-y0)/pitch)*pitch]
    for by in ys:
        assert grid['extent'][0][1]<=by<=grid['extent'][1][1]
    before=set(coll.objects)
    low,high=ys[0]-10,ys[1]+10
    base=box('NEW_TableBase',(48,high-low,height),(x,(low+high)/2,z+height/2),coll,bevel=.6)
    # Bottom relief leaves perimeter lands resting on the table.
    cut(base,box('base_relief',(32,high-low-10,.8),(x,(low+high)/2,z),coll,bevel=0))
    bore(base,3.3,height+2,(x,y,z+height/2),coll)
    bore(base,5.3,6.4,(x,y,z+3),coll)
    # Captive underside holder screw: head sits above the table; tip stays below bore floor.
    head=cylinder('NEW_HolderBaseScrewHead',5,6,(x,y,z+3.2),coll)
    bore(head,5/math.sqrt(3),3,(x,y,z+1),coll,vertices=6)
    cylinder('NEW_HolderBaseScrewShaft',3,height-3.2,(x,y,z+(6.2+height+3)/2),coll,bevel=.05)
    for by in ys:
        # Transverse channels next to the two SHORT edges, not lengthwise grooves.
        capsule(base,6.6,36,height+2,(x,by,z+height/2),coll,axis='X')
        capsule(base,13,42,4.2,(x,by,z+height-1.9),coll,axis='X')
        seat=height-4
        washer=cylinder('NEW_TableWasher',6,1,(bx,by,z+seat+.5),coll,bevel=.08)
        bore(washer,3.3,3,(bx,by,z+seat+.5),coll)
        shaft=cylinder('NEW_TableBoltShaft',3,seat+6,(bx,by,z+(seat-4)/2),coll,bevel=.05)
        shaft['table_fastener']=True
        head=cylinder('NEW_TableBoltHead',5,6,(bx,by,z+seat+4),coll,bevel=.3)
        bore(head,5/math.sqrt(3),4,(bx,by,z+seat+6),coll,vertices=6)
    for face in base.data.polygons:face.use_smooth=False
    label('M6',(x-21,(low+high)/2,z+height+.02),coll,1.6)
    members=set(coll.objects)-before
    bpy.context.view_layer.update()
    for p in members:
        p['promo_part_group']='TableBase'
        p['oa_owner']=holder.parent.get('oa_owner')
        world=p.matrix_world.copy();p.parent=holder.parent;p.matrix_world=world
    base['table_base']=True
    base['slot_axis']='X; parallel to short edges'
    base['assembly_training_verified']=False
    return base,members
