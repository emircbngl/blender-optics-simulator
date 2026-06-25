import bpy, sys, os
import numpy as np
REPO="/Users/emircbngl/Blender Alignment Plugin"; sys.path.insert(0,REPO)
import optical_alignment_sim as oas; oas.register()
from optical_alignment_sim import ao
co=[0.0]*15; co[3]=0.8; co[5]=0.4; co[7]=0.25   # defocus + astig + coma
s=ao.pyramid_signals(co, 200)
img=ao.pyramid_slope_image(s)
os.makedirs("/tmp/pyr",exist_ok=True)
np.save("/tmp/pyr/sx.npy", s["sx"]); np.save("/tmp/pyr/sy.npy", s["sy"]); np.save("/tmp/pyr/img.npy", img)
np.save("/tmp/pyr/mask.npy", s["mask"])
print("DUMPED slope_rms=%.3f sx_rms=%.3f sy_rms=%.3f"%(s["slope_rms"],s["sx_rms"],s["sy_rms"]))
