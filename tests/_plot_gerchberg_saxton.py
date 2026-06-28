"""Generate docs/img/gerchberg-saxton-demo.png -- Gerchberg-Saxton phase retrieval / CGH design.

Four panels for a canonical 'ring' (donut) target:
  (a) target far-field amplitude;  (b) achieved far-field after GS;  (c) the recovered source phase mask
  (the computer-generated hologram);  (d) the far-field error vs iteration -- MONOTONE non-increasing (the GS
  guarantee). Run:  python3 tests/_plot_gerchberg_saxton.py
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import field as F

BG, FG, TX, MU, GR, AC = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0"
N, target = 160, "ring"
T, src = F.gs_named_target(target, N)
r = F.gerchberg_saxton(T, src, n_iter=100, seed=0)
# normalized target (same scaling GS uses) for a fair side-by-side
Tn = T * (np.linalg.norm(np.fft.fft2(src)) / (np.linalg.norm(T) or 1.0))

fig, ax = plt.subplots(1, 4, figsize=(15.6, 4.0))
fig.patch.set_facecolor(BG)
fig.suptitle("Gerchberg-Saxton phase retrieval -- design a phase mask whose far-field |FFT| is the target "
             "(target = ring / donut)", color=FG, fontsize=12.5, fontweight="bold", y=0.99)

c = N // 2
hw = 46
def crop(A):
    return A[c - hw:c + hw, c - hw:c + hw]

ax[0].imshow(crop(Tn ** 2), cmap="inferno", origin="lower")
ax[0].set_title("(a) target far-field", color=TX, fontsize=10.5)
ax[1].imshow(crop(r["achieved_amplitude"] ** 2), cmap="inferno", origin="lower")
ax[1].set_title("(b) achieved far-field (corr %.3f)" % r["correlation"], color=TX, fontsize=10.5)
ax[2].imshow(r["source_phase"], cmap="twilight", origin="lower")
ax[2].set_title("(c) recovered phase mask (the CGH)", color=TX, fontsize=10.5)
ax[3].plot(range(1, len(r["errors"]) + 1), r["errors"], color=AC, lw=1.5)
ax[3].set_title("(d) far-field error -- monotone", color=TX, fontsize=10.5)
ax[3].set_xlabel("iteration", color=TX, fontsize=9.5); ax[3].set_ylabel("error", color=TX, fontsize=9.5)
ax[3].set_facecolor(BG); ax[3].tick_params(colors=MU, labelsize=8)
for s in ax[3].spines.values():
    s.set_color(GR)
for a_ in ax[:3]:
    a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor(BG)
    for s in a_.spines.values():
        s.set_color(GR)
fig.text(0.5, 0.015, "The iterative Fourier-transform algorithm: enforce source amplitude -> FFT -> enforce "
                     "target amplitude -> IFFT. The far-field error never increases (GS guarantee). Off-trace; "
                     "live trace byte-identical.", color=MU, fontsize=7.8, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.94))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/gerchberg-saxton-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
