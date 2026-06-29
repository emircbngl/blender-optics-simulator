"""Generate docs/img/fienup-phase-retrieval-demo.png -- Fienup HIO phase retrieval (the genuine 'phase problem').

A detector records only the diffraction INTENSITY |FFT(object)|^2 -- the phase is lost. Given that magnitude
plus a real-space SUPPORT mask, Fienup's Hybrid-Input-Output algorithm reconstructs the hidden object.
Four panels (object 'dots'):
  (a) the hidden object (UNKNOWN to the algorithm);
  (b) the measured diffraction intensity |FFT|^2 (log) -- ALL the algorithm is given (+ the support);
  (c) the HIO recovery -- the object reappears (up to the inherent translation + twin ambiguity);
  (d) the Fourier-magnitude error vs iteration: HIO plunges where pure error-reduction (ER) stalls.
Run:  python3 tests/_plot_fienup.py
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import field as F

BG, FG, TX, MU, GR, AC = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0"
N = 128
truth, support = F._fienup_object("dots", N)
measured = np.abs(F._fft2c(truth)) ** 2
hio = F.fienup_phase_retrieval(measured, support, n_iter=300, mode="hio", seed=0)
er = F.fienup_phase_retrieval(measured, support, n_iter=320, mode="er", seed=0)
corr = F._register_corr(hio["recovered"], truth)

fig, ax = plt.subplots(1, 4, figsize=(15.4, 4.0))
fig.patch.set_facecolor(BG)
fig.suptitle("Fienup HIO phase retrieval -- reconstruct a hidden object from its diffraction INTENSITY + a support mask",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)

ax[0].imshow(truth, cmap="inferno", origin="lower")
ax[0].set_title("(a) hidden object", color=TX, fontsize=10.5)
# show the support outline lightly
ys, xs = np.where(support)
ax[0].add_patch(plt.Rectangle((xs.min(), ys.min()), xs.max() - xs.min(), ys.max() - ys.min(),
                              fill=False, edgecolor=AC, lw=0.8, ls="--", alpha=0.7))

dlog = np.log10(np.clip(np.fft.fftshift(measured) / measured.max(), 1e-6, 1.0))
ax[1].imshow(dlog, cmap="magma", origin="lower", vmin=-6, vmax=0)
ax[1].set_title("(b) measured |FFT|^2 (log)\n-- phase is LOST", color=TX, fontsize=10.5)

ax[2].imshow(hio["recovered"], cmap="inferno", origin="lower")
ax[2].set_title("(c) HIO recovery (corr=%.3f)" % corr, color=TX, fontsize=10.5)

ax[3].semilogy(hio["fourier_error"], color=AC, lw=1.6, label="HIO (feedback)")
ax[3].semilogy(er["fourier_error"], color="#c0653a", lw=1.4, ls="--", label="ER (stalls)")
ax[3].set_title("(d) Fourier-magnitude error", color=TX, fontsize=10.5)
ax[3].set_xlabel("iteration", color=MU, fontsize=8.5)
ax[3].set_facecolor(BG)
ax[3].tick_params(colors=MU, labelsize=8)
ax[3].grid(True, color=GR, lw=0.4, alpha=0.5)
leg = ax[3].legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.5, loc="upper right")

for a_ in ax[:3]:
    a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor(BG)
for a_ in ax:
    for s in a_.spines.values():
        s.set_color(GR)

fig.text(0.5, 0.025, "The object plane amplitude is UNKNOWN -- only the support is. HIO's g - beta*g' feedback escapes the "
                     "stagnation pure error-reduction falls into, recovering the object (up to the inherent translation + "
                     "conjugate-twin ambiguity, here broken by the off-centre support). Off-trace; live trace byte-identical.",
         color=MU, fontsize=7.8, ha="center")
fig.tight_layout(rect=(0, 0.055, 1, 0.92))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/fienup-phase-retrieval-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
