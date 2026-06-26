"""Draw docs/img/pyramid-wfs.png from /tmp/pyr/*.npy — the pyramid WFS slope maps. Uses the shared
`figstyle` schema with PER-PANEL colorbars (Sx and Sy are on different scales, so a single shared colorbar
would be wrong); the third panel is the RGB slope field (no colorbar)."""
import os
import numpy as np
import figstyle as fs

sx = np.load("/tmp/pyr/sx.npy")
sy = np.load("/tmp/pyr/sy.npy")
img = np.load("/tmp/pyr/img.npy")

fig, axes = fs.grid(1, 3, w=13.6, h=5.3,
                    title="Pyramid WFS: a SLOPE sensor — it reads the wavefront gradient, not the modal vector")
for ax, (F, title) in zip(axes[:2], [(sx, "Sx = dW/dx  (x-slope)"), (sy, "Sy = dW/dy  (y-slope)")]):
    v = float(np.nanmax(np.abs(F[np.isfinite(F)]))) or 1.0
    im = fs.image_panel(ax, F, vmin=-v, vmax=v, title=title)
    fs.panel_colorbar(fig, ax, im, label="waves/pupil")
fs.image_panel(axes[2], img, rgb=True, title="slope FIELD  (hue = direction, value = |grad W|)")

fs.footer(fig, "From the same wavefront (defocus+astig+coma) the pyramid reports Sx=dW/dx, Sy=dW/dy (waves per "
               "pupil-radius). A unit defocus reads a RADIAL slope dZ4/dx=4√3·x (physics_verify ok=true). Tier-1 "
               "GEOMETRIC: the gradient a pyramid integrates, not a diffractive 4-pupil image.")
fs.finalize(fig, "docs/img/pyramid-wfs.png", has_colorbar=False, right=0.955, wspace=0.20, bottom=0.13)
print("SAVED docs/img/pyramid-wfs.png")
