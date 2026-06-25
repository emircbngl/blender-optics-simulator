"""Draw docs/img/wfs-defocus.png from /tmp/wfsdf/*.npy (the WFS beam-curvature-defocus fix demo).

3 panels, all the SAME clean (un-aberrated) beam read by the wavefront sensor:
  [BEFORE]  diverging beam, modal channel only  -> flat, RMS=0   (the bug: the sensor ignored R(z))
  [AFTER]   diverging beam, sensor read          -> a real defocus bowl, RMS = the beam's own curvature
  [check]   collimated beam, sensor read         -> correctly ~flat (R huge -> a4 ~ 0)
The middle panel is what a real Shack-Hartmann WFS measures; the left is what the model used to report.
Plain Python + matplotlib (run as a second pass on the dumped arrays).
"""
import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/wfsdf"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "img", "wfs-defocus.png")

meta = json.load(open(os.path.join(SRC, "meta.json")))

panels = [
    ("div_old.npy",  "BEFORE — modal channel only",
     "diverging beam  ·  RMS = %.3f waves" % meta["div_old_rms"],
     "the WFS ignored the beam's own R(z):\na clean diverging beam read FLAT", "#b04a4a"),
    ("div_new.npy",  "AFTER — sensor reads R(z)",
     "diverging beam  ·  RMS = %.3f waves" % meta["div_new_rms"],
     "R = %.0f mm,  w = %.2f mm\ndefocus a₄ = w²/(4√3·R·λ) = %.3f"
     % (meta["div_R"], meta["div_w"], meta["div_defocus"]), "#4a8db0"),
    ("coll_new.npy", "control — collimated beam",
     "collimated beam  ·  RMS = %.4f waves" % meta["coll_new_rms"],
     "R = %.1e mm  (huge) → a₄ ≈ 0\nstays correctly flat" % meta["coll_R"], "#5a8a5a"),
]

fig, axes = plt.subplots(1, 3, figsize=(13.6, 5.0))
fig.patch.set_facecolor("#0d0d10")

# one SHARED symmetric colour scale across all panels so the BEFORE/AFTER magnitude difference is honest
# (a per-panel auto-scale would make the flat RMS=0 map look as colourful as the defocus bowl).
vmax = max(meta["div_new_rms"], 1e-3) * 1.9

for ax, (fn, title, rms_note, sub, accent) in zip(axes, panels):
    field = np.load(os.path.join(SRC, fn))
    ax.set_facecolor("#0d0d10")
    im = ax.imshow(field, cmap="RdBu_r", vmin=-vmax, vmax=vmax, origin="lower", interpolation="nearest")
    ax.set_title(title, color=accent, fontsize=12, pad=8, fontweight="bold")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(accent); s.set_linewidth(1.4)
    ax.text(0.5, -0.06, rms_note, transform=ax.transAxes, color="#f2f2f4", fontsize=10.5,
            va="top", ha="center", fontweight="bold")
    ax.text(0.5, -0.135, sub, transform=ax.transAxes, color="#9a9aa2", fontsize=8.6,
            va="top", ha="center")

cb = fig.colorbar(im, ax=axes, fraction=0.026, pad=0.02)
cb.set_label("wavefront  (waves)", color="#b9b9c0", fontsize=9)
cb.ax.tick_params(colors="#9a9aa2", labelsize=8)
cb.outline.set_edgecolor("#33343a")

fig.suptitle("Wavefront sensor now reads the beam's own curvature (defocus), not just the modal aberration",
             color="#f4f4f6", fontsize=13.5, y=0.985, x=0.46)
fig.text(0.46, 0.018,
         "OPD of a Gaussian over footprint w_s is W(r)=r²/(2R)  →  Noll defocus  a₄ = w_s²/(4√3·R·λ) waves "
         "(physics_verify ok=true).  A real Shack–Hartmann integrates this; the model read only the modal channel, "
         "so a clean diverging beam reported a wrong flat RMS=0.  The AO loop still corrects the modal channel.",
         color="#7a7a82", fontsize=8.2, ha="center", va="bottom", wrap=True)
fig.subplots_adjust(left=0.02, right=0.90, top=0.88, bottom=0.22, wspace=0.08)
fig.savefig(OUT, dpi=150, facecolor=fig.get_facecolor())
print("SAVED", OUT)
