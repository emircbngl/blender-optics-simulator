"""Generate docs/img/tem-modes-demo.png -- laser cavity transverse modes (Hermite-Gaussian + Laguerre-Gaussian).

Top row: Hermite-Gaussian TEM_mn intensities -- the rectangular resonator modes, (m+1)(n+1) bright lobes.
Bottom row: the Laguerre-Gaussian donut LG_{0,1} intensity (on-axis null) and its exp(i*phi) PHASE VORTEX
(the 2*pi azimuthal winding = orbital angular momentum l=1), then LG_{0,2} (l=2) intensity + phase.
Run:  python3 tests/_plot_tem_modes.py
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import field as F

BG, FG, TX, MU, GR = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a"
N, W = 256, 0.5

fig, ax = plt.subplots(2, 4, figsize=(14.6, 7.2))
fig.patch.set_facecolor(BG)
fig.suptitle("Laser cavity transverse modes -- Hermite-Gaussian TEM_mn (top) and Laguerre-Gaussian donuts + phase vortices (bottom)",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)

# top row: HG modes
hg = [(0, 0), (1, 0), (1, 1), (2, 1)]
for a_, (m, n) in zip(ax[0], hg):
    U = F.hermite_gaussian(m, n, W, N)
    lobes = F.tem_mode_metrics("HG", m, n, W, N)["n_lobes"]
    a_.imshow(np.abs(U) ** 2, cmap="inferno", origin="lower")
    a_.set_title("HG TEM$_{%d%d}$  (%d lobes)" % (m, n, lobes), color=TX, fontsize=10.5)
    a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor(BG)

# bottom row: LG donut intensities + phase vortices
U1 = F.laguerre_gaussian(0, 1, W, N)
U2 = F.laguerre_gaussian(0, 2, W, N)
w1 = F.tem_mode_metrics("LG", 0, 1, W, N)["oam_winding_turns"]
w2 = F.tem_mode_metrics("LG", 0, 2, W, N)["oam_winding_turns"]
panels = [(np.abs(U1) ** 2, "inferno", "LG$_{0,1}$ donut intensity"),
          (np.angle(U1), "twilight", "LG$_{0,1}$ phase vortex (l=1, %g turn)" % w1),
          (np.abs(U2) ** 2, "inferno", "LG$_{0,2}$ donut intensity"),
          (np.angle(U2), "twilight", "LG$_{0,2}$ phase vortex (l=2, %g turns)" % w2)]
for a_, (img, cmap, title) in zip(ax[1], panels):
    a_.imshow(img, cmap=cmap, origin="lower")
    a_.set_title(title, color=TX, fontsize=10.5)
    a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor(BG)

for row in ax:
    for a_ in row:
        for s in a_.spines.values():
            s.set_color(GR)

fig.text(0.5, 0.02, "HG modes are an orthonormal set ((m+1)(n+1) lobes; second moment grows as 2m+1). The LG donut has an "
                    "on-axis NULL where the exp(i*l*phi) phase winds 2*pi*l around the core -- a screw phase dislocation carrying "
                    "orbital angular momentum l*hbar per photon. Off-trace; live trace byte-identical.",
         color=MU, fontsize=7.8, ha="center")
fig.tight_layout(rect=(0, 0.04, 1, 0.94))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/tem-modes-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
