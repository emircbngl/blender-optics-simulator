"""Compose docs/img/feature-board.png — a 'new in v0.10.0' banner tiling the four AI-first / wavefront
feature figures (wfs-defocus, pyramid-wfs, dichroic-edge, die-wavefront). Pure composition of EXISTING
PNGs (no new render), matplotlib only.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(REPO, "docs", "img")
OUT = os.path.join(IMG, "feature-board.png")

tiles = [
    ("wfs-defocus.png", "WFS reads the beam's own curvature defocus"),
    ("pyramid-wfs.png", "Pyramid WFS — a slope sensor (dW/dx, dW/dy)"),
    ("dichroic-edge.png", "Soft-edge dichroic — R(λ) + T(λ) = 1"),
    ("die-wavefront.png", "A die face read as a zonal wavefront"),
]

fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.2))
fig.patch.set_facecolor("#0d0d10")
for ax, (fn, cap) in zip(axes.ravel(), tiles):
    ax.set_facecolor("#0d0d10")
    p = os.path.join(IMG, fn)
    if os.path.exists(p):
        ax.imshow(mpimg.imread(p))
    ax.set_title(cap, color="#e8e8ea", fontsize=11.5, pad=6)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#33343a")

fig.suptitle("New in v0.10.0 — AI-first correctness & wavefront sensing",
             color="#f4f4f6", fontsize=16, fontweight="bold", y=0.985)
fig.text(0.5, 0.012,
         "Every formula machine-verified against the physicist Docker oracle · regression 215 → 357 · "
         "the agent reads numeric ground truth, judges advisory corrections, and is told the phenomena the bench meets.",
         color="#8a8a92", fontsize=8.6, ha="center", va="bottom")
fig.subplots_adjust(left=0.015, right=0.985, top=0.92, bottom=0.05, hspace=0.16, wspace=0.06)
fig.savefig(OUT, dpi=140, facecolor=fig.get_facecolor())
print("SAVED", OUT)
