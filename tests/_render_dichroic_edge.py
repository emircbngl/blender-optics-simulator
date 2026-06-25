import bpy, sys, json, os
REPO="/Users/emircbngl/Blender Alignment Plugin"; sys.path.insert(0,REPO)
import optical_alignment_sim as oas; oas.register()
from optical_alignment_sim import scan, elements_generic as eg
from mathutils import Vector
sc=bpy.context.scene
OUT="/tmp/dich"; os.makedirs(OUT,exist_ok=True)
rows=[]
for i in range(61):
    wl=560.0+ (740.0-560.0)*i/60.0
    for o in list(sc.objects):
        if getattr(getattr(o,"optics",None),"is_optical",False): bpy.data.objects.remove(o,do_unlink=True)
    c=eg.example_collection("DS"); X=Vector((1,0,0)); Y=Vector((0,1,0))
    eg.source("S",(-100,0,0),X,c,wavelength=wl)
    d=eg.dichroic("DI",(0,0,0),X,Y,c,cut_nm=650.0,pass_type='LP'); d.optics.edge_width=10.0
    eg.detector("DT",(100,0,0),X,c); eg.detector("DR",(0,100,0),Y,c)
    bpy.context.view_layer.update()
    s=scan._trace(sc); dn=d.name
    T=sum(x["power"] for x in s if x.get("from")==dn and x.get("kind")=="TRANSMIT")
    R=sum(x["power"] for x in s if x.get("from")==dn and x.get("kind")=="REFLECT")
    rows.append([wl,T,R])
    for o in list(c.objects): eg.drop_example_object(o)
    bpy.data.collections.remove(c)
json.dump({"cut":650.0,"edge_width":10.0,"rows":rows}, open(OUT+"/sweep.json","w"))
print("DUMPED",len(rows),"rows; at cut: T=%.3f R=%.3f"%(rows[30][1],rows[30][2]))
