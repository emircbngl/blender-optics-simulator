import os, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
REPO="/Users/emircbngl/Blender Alignment Plugin"; OUT=os.path.join(REPO,"docs","img","pyramid-wfs.png")
sx=np.load("/tmp/pyr/sx.npy"); sy=np.load("/tmp/pyr/sy.npy"); img=np.load("/tmp/pyr/img.npy")
fig,axes=plt.subplots(1,3,figsize=(13.6,4.8)); fig.patch.set_facecolor("#0d0d10")
def panel(ax,F,title,cmap="RdBu_r",rgb=False):
    ax.set_facecolor("#0d0d10")
    if rgb: ax.imshow(F[...,:3],origin="lower",interpolation="nearest")
    else:
        v=np.nanmax(np.abs(F[np.isfinite(F)])) or 1.0
        im=ax.imshow(F,cmap=cmap,vmin=-v,vmax=v,origin="lower",interpolation="nearest")
        cb=fig.colorbar(im,ax=ax,fraction=0.046,pad=0.03); cb.ax.tick_params(colors="#9a9aa2",labelsize=7); cb.outline.set_edgecolor("#33343a")
    ax.set_title(title,color="#e8e8ea",fontsize=11,pad=7); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_color("#33343a")
panel(axes[0],sx,"Sx = dW/dx  (x-slope)")
panel(axes[1],sy,"Sy = dW/dy  (y-slope)")
panel(axes[2],img,"slope FIELD  (hue=direction, value=|grad W|)",rgb=True)
fig.suptitle("Pyramid WFS: a SLOPE sensor — it reads the wavefront gradient, not the modal vector",color="#f4f4f6",fontsize=13,y=0.99)
fig.text(0.5,0.02,"From the same wavefront (defocus+astig+coma) the pyramid reports Sx=dW/dx, Sy=dW/dy (waves per pupil-radius). "
         "A unit defocus reads a RADIAL slope dZ4/dx=4√3·x (physics_verify ok=true). Tier-1 GEOMETRIC: the gradient a pyramid "
         "integrates, not a diffractive 4-pupil image (the chief-ray tracer does not propagate the pupil field).",
         color="#7a7a82",fontsize=7.4,ha="center",va="bottom",wrap=True)
fig.subplots_adjust(left=0.02,right=0.97,top=0.88,bottom=0.13,wspace=0.13)
fig.savefig(OUT,dpi=150,facecolor=fig.get_facecolor()); print("SAVED",OUT)
