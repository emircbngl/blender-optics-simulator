"""Draw docs/img/wfs-defocus.png from /tmp/wfsdf/*.npy (the WFS beam-curvature-defocus fix demo).

3 panels, all the SAME clean (un-aberrated) beam read by the wavefront sensor:
  [BEFORE]  diverging beam, modal channel only  -> flat, RMS=0   (the bug: the sensor ignored R(z))
  [AFTER]   diverging beam, sensor read          -> a real defocus bowl, RMS = the beam's own curvature
  [control] collimated beam, sensor read         -> correctly ~flat (R huge -> a4 ~ 0)
Uses the shared `figstyle` schema, so the colorbar sits in its own reserved margin (never overlaps a
panel) and the captions are never clipped.
"""
import os
import json
import numpy as np
import figstyle as fs

SRC = "/tmp/wfsdf"
meta = json.load(open(os.path.join(SRC, "meta.json")))

panels = [
    ("div_old.npy",  "BEFORE — modal channel only", "#b04a4a",
     "diverging beam  ·  RMS = %.3f waves" % meta["div_old_rms"],
     "the WFS ignored the beam's own R(z):\na clean diverging beam read FLAT"),
    ("div_new.npy",  "AFTER — sensor reads R(z)", "#4a8db0",
     "diverging beam  ·  RMS = %.3f waves" % meta["div_new_rms"],
     "R = %.0f mm,  w = %.2f mm\ndefocus a₄ = w²/(4√3·R·λ) = %.3f"
     % (meta["div_R"], meta["div_w"], meta["div_defocus"])),
    ("coll_new.npy", "control — collimated beam", "#5a8a5a",
     "collimated beam  ·  RMS = %.4f waves" % meta["coll_new_rms"],
     "R = %.1e mm  (huge) → a₄ ≈ 0\nstays correctly flat" % meta["coll_R"]),
]

# one shared symmetric scale so the BEFORE/AFTER magnitude difference is honest
vmax = max(meta["div_new_rms"], 1e-3) * 1.9

fig, axes = fs.grid(1, 3, w=13.6, h=6.0,
                    title="Wavefront sensor now reads the beam's own curvature (defocus), not just the modal aberration")
im = None
for ax, (fn, title, accent, rms_note, sub) in zip(axes, panels):
    field = np.load(os.path.join(SRC, fn))
    im = fs.image_panel(ax, field, vmin=-vmax, vmax=vmax, title=title)
    ax.title.set_color(accent)
    ax.title.set_fontweight("bold")
    for s in ax.spines.values():
        s.set_color(accent)
        s.set_linewidth(1.4)
    ax.text(0.5, -0.05, rms_note, transform=ax.transAxes, color=fs.THEME["fg"], fontsize=10.5,
            va="top", ha="center", fontweight="bold")
    ax.text(0.5, -0.12, sub, transform=ax.transAxes, color=fs.THEME["muted"], fontsize=8.6,
            va="top", ha="center")

fs.shared_colorbar(fig, im, label="wavefront  (waves)")
fs.footer(fig, "OPD of a Gaussian over footprint w_s is W(r)=r²/(2R)  →  Noll defocus  a₄ = w_s²/(4√3·R·λ) waves "
               "(physics_verify ok=true).  A real Shack–Hartmann integrates this; the model read only the modal "
               "channel, so a clean diverging beam reported a wrong flat RMS=0.")
fs.finalize(fig, "docs/img/wfs-defocus.png", bottom=0.20)
print("SAVED docs/img/wfs-defocus.png")
