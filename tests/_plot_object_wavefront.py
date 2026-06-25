"""Draw docs/img/object-wavefronts.png from /tmp/objwf/*.npy (knight + die zonal wavefronts).

Raw zonal field W(x,y) in waves, diverging colormap, percentile-clipped. NO intensity fade here -- the goal
is RECOGNISABILITY (the valid region traces the silhouette; the die pips read as the quincunx), so the full
footprint is shown. Plain Python + matplotlib (not in Blender).
"""
import os, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/objwf"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "img", "object-wavefronts.png")
meta = json.load(open(os.path.join(SRC, "meta.json")))
keys = [k for k in ("knight", "die") if os.path.exists(os.path.join(SRC, k + "_field.npy"))]

fig, axes = plt.subplots(1, len(keys), figsize=(5.0 * len(keys), 5.4))
if len(keys) == 1:
    axes = [axes]
fig.patch.set_facecolor("#0d0d10")

for ax, key in zip(axes, keys):
    F = np.load(os.path.join(SRC, key + "_field.npy"))
    m = meta[key]
    ax.set_facecolor("#0d0d10")
    finite = np.abs(F[np.isfinite(F)])
    vmax = float(np.percentile(finite, 97.0)) if finite.size else 1.0
    vmax = vmax or 1.0
    im = ax.imshow(F, cmap="RdBu_r", vmin=-vmax, vmax=vmax, origin="lower", interpolation="nearest")
    ax.set_title(m.get("title", key), color="#e8e8ea", fontsize=11, pad=8)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#33343a")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label("wavefront (waves)", color="#b9b9c0", fontsize=8)
    cb.ax.tick_params(colors="#9a9aa2", labelsize=7)
    cb.outline.set_edgecolor("#33343a")
    ax.text(0.03, 0.04, "RMS %.0f waves · Ø%.0f mm\nvalid %.0f%% · %d px"
            % (m["rms_uniform"], m["footprint_mm"], 100.0 * m["hit_frac"], m["px"]),
            transform=ax.transAxes, color="#f2f2f4", fontsize=8.5, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="#000000aa", ec="none"))

fig.suptitle("Zonal wavefront of a real object — aimed at its iconic face",
             color="#f4f4f6", fontsize=13, y=0.99)
fig.text(0.5, 0.015,
         "The zonal sensor render is a range image of the reflector along the beam: the valid (reflected) "
         "region traces the object's silhouette and the depth relief colours it.  Orientation is everything — "
         "the object's iconic view must face the beam (we previously sampled cross-sections of the base).",
         color="#7a7a82", fontsize=7.4, ha="center", va="bottom", wrap=True)
fig.subplots_adjust(left=0.04, right=0.93, top=0.90, bottom=0.10, wspace=0.12)
fig.savefig(OUT, dpi=150, facecolor=fig.get_facecolor())
print("SAVED", OUT)
