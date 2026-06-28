"""Generate docs/img/spatial-filter-demo.png -- 4f Fourier-plane spatial filtering (Abbe-Porter + Zernike).

Four panels:
  (a) a square-grating object;  (b) LOWPASS (pass only low spatial frequencies -> the grating smooths/erases);
  (c) HIGHPASS (block the zero order -> the uniform DC background is removed, only edges/fringes remain);
  (d) a pure-PHASE object that is INVISIBLE in intensity, made visible by Zernike PHASE CONTRAST (pi/2 dot on
      the zero order). Run:  python3 tests/_plot_spatial_filter.py
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import field as F

BG, FG, TX, MU, GR = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a"
N = 256
grating = F._filter_object("grating", N)
lp = F.fourier_filter(grating, "lowpass", 0.06)
hp = F.fourier_filter(grating, "highpass", 0.02)
phase = F._filter_object("phase", N)
pc = F.fourier_filter(phase, "phase_contrast", 0.02)

fig, ax = plt.subplots(1, 4, figsize=(15.2, 4.0))
fig.patch.set_facecolor(BG)
fig.suptitle("4f Fourier-plane spatial filtering -- Abbe-Porter (lowpass / highpass) + Zernike phase contrast",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)
panels = [(np.abs(grating) ** 2, "(a) grating object"),
          (np.abs(lp) ** 2, "(b) lowpass -> smoothed"),
          (np.abs(hp) ** 2, "(c) highpass -> DC removed"),
          (np.abs(pc) ** 2, "(d) phase object -> phase contrast")]
for a_, (img, title) in zip(ax, panels):
    a_.imshow(img, cmap="gray", origin="lower")
    a_.set_title(title, color=TX, fontsize=10.5)
    a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor(BG)
    for s in a_.spines.values():
        s.set_color(GR)
fig.text(0.5, 0.02, "FFT the object -> mask the Fourier plane -> IFFT. The pure-phase object (d) has UNIFORM "
                    "intensity until the pi/2 zero-order dot converts phase to amplitude (Zernike phase-contrast "
                    "microscopy). Off-trace; live trace byte-identical.", color=MU, fontsize=7.8, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.94))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/spatial-filter-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
