import bpy, sys, os
import numpy as np
REPO="/Users/emircbngl/Blender Alignment Plugin"; sys.path.insert(0,REPO)
import optical_alignment_sim as oas; oas.register()
import optics_api
from optical_alignment_sim import scan, ao, tracer
sc=bpy.context.scene
optics_api.build_example("die")
segs=scan._trace(sc)
hit=[s for s in segs if s.get("to")=="DIE_WFS"]
print("beam reaches DIE_WFS:", len(hit)>0)
fld=ao.zonal_wavefront_at_sensor(sc, "DIE_WFS", segs, px=200)
if fld:
    F=fld["field"]; valid=~np.isnan(F)
    print("zonal field: %dx%d, valid=%.0f%%, PV=%.3f waves"%(F.shape[0],F.shape[1],100*valid.mean(),np.nanmax(F)-np.nanmin(F)))
    os.makedirs("/tmp/die",exist_ok=True)
    np.save("/tmp/die/field.npy", F)
    if fld.get("intensity") is not None: np.save("/tmp/die/intensity.npy", np.asarray(fld["intensity"]))
    print("DUMPED")
else:
    print("zonal render returned None")
