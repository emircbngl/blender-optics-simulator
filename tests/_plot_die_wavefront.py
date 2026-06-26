"""Draw docs/img/die-wavefront.png from /tmp/die/*.npy — the die-face zonal wavefront (the 5-pip
quincunx). Uses the shared `figstyle` schema so the colorbar sits in its own reserved margin (its tick
labels are never clipped at the figure edge — the bug the previous hand-rolled layout had)."""
import os
import numpy as np
import figstyle as fs

F = np.load("/tmp/die/field.npy")
inten = np.load("/tmp/die/intensity.npy") if os.path.exists("/tmp/die/intensity.npy") else None
finite = np.abs(F[np.isfinite(F)])
vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
alpha = None
if inten is not None:
    a = np.where(np.isfinite(inten), np.clip(inten, 0.0, 1.0), 0.0)
    alpha = np.where(np.isfinite(F), a, 0.0)

fig, axes = fs.grid(1, 1, w=7.0, h=6.4,
                    title="Die face read as a zonal wavefront — the 5-pip quincunx")
im = fs.image_panel(axes[0], F, vmin=-vmax, vmax=vmax, alpha=alpha)
fs.shared_colorbar(fig, im, label="wavefront  (waves)")
fs.footer(fig, "build_example('die') → a collimated beam reads a die-face relief off the reflector; the dense "
               "ZONAL sensor map (optics_api.zonal_render('DIE_WFS')) shows the 5 recessed pips, Gaussian-beam-"
               "weighted (bright centre, dim edge). swap_part / _die_face_mesh(value=…) for other faces.")
fs.finalize(fig, "docs/img/die-wavefront.png", bottom=0.13)
print("SAVED docs/img/die-wavefront.png")
