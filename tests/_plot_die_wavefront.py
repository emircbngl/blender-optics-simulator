import os, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
REPO="/Users/emircbngl/Blender Alignment Plugin"
OUT=os.path.join(REPO,"docs","img","die-wavefront.png")
F=np.load("/tmp/die/field.npy")
inten=np.load("/tmp/die/intensity.npy") if os.path.exists("/tmp/die/intensity.npy") else None
fig,ax=plt.subplots(figsize=(6.4,6.0)); fig.patch.set_facecolor("#0d0d10"); ax.set_facecolor("#0d0d10")
finite=np.abs(F[np.isfinite(F)]); vmax=float(np.percentile(finite,99)) if finite.size else 1.0
alpha=None
if inten is not None:
    a=np.where(np.isfinite(inten),np.clip(inten,0,1),0.0); alpha=np.where(np.isfinite(F),a,0.0)
im=ax.imshow(F,cmap="RdBu_r",vmin=-vmax,vmax=vmax,origin="lower",interpolation="nearest",alpha=alpha)
ax.set_title("Die face read as a zonal wavefront — the 5-pip quincunx",color="#f4f4f6",fontsize=12.5,pad=9)
ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values(): s.set_color("#33343a")
cb=fig.colorbar(im,ax=ax,fraction=0.046,pad=0.03); cb.set_label("wavefront (waves)",color="#b9b9c0",fontsize=8.5)
cb.ax.tick_params(colors="#9a9aa2",labelsize=7.5); cb.outline.set_edgecolor("#33343a")
fig.text(0.5,0.02,"build_example('die') -> a collimated beam reads a die-face relief off the reflector; the dense ZONAL "
         "sensor map (optics_api.zonal_render('DIE_WFS')) shows the 5 recessed pips. Gaussian-beam-weighted footprint "
         "(bright centre, dim edge). swap_part / _die_face_mesh(value=...) for other faces.",
         color="#7a7a82",fontsize=7.2,ha="center",va="bottom",wrap=True)
fig.subplots_adjust(left=0.04,right=0.96,top=0.93,bottom=0.11)
fig.savefig(OUT,dpi=150,facecolor=fig.get_facecolor()); print("SAVED",OUT)
