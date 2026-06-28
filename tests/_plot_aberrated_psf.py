"""Generate docs/img/aberrated-psf-demo.png -- the diffraction PSF aberrated by single Zernike modes.

Two rows x five columns. Columns: ideal, defocus, astigmatism, coma, spherical (each 0.10 waves RMS).
  top row   = the pupil WAVEFRONT W(x,y) in waves (RdBu_r);
  bottom row= the resulting PSF (log-scaled) with its Strehl ratio.
The Strehl collapses the SAME way (Marechal exp(-(2 pi rms)^2) ~ 0.674 at 0.10 waves) regardless of WHICH
mode -- it depends only on the RMS wavefront error -- but the PSF *shape* is the mode's fingerprint:
defocus blurs symmetrically, astigmatism elongates, coma flares one-sided, spherical haloes.
Run:  python3 tests/_plot_aberrated_psf.py
"""
import os, sys, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import wave as W

BG, FG, TX, MU, GR = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a"
N, DPX = 512, 256
AMP = 0.10                                                # waves RMS in the single excited mode
# (label, Noll j)
MODES = [("ideal", None), ("defocus", 4), ("astigmatism", 5), ("coma", 7), ("spherical", 11)]
mask = W.aperture_mask(N, DPX).astype(float)

fig, ax = plt.subplots(2, 5, figsize=(15.6, 6.6))
fig.patch.set_facecolor(BG)
fig.suptitle("Zernike-aberrated diffraction PSF -- Strehl follows Marechal exp(-(2 pi rms)^2), shape is the mode's fingerprint",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)

for col, (label, j) in enumerate(MODES):
    coeffs = [0.0] * 15
    if j is not None:
        coeffs[j - 1] = AMP
    Wf = W.zernike_wavefront(coeffs, N, DPX)             # waves, zero outside the pupil
    psf = W._psf(mask * np.exp(2j * math.pi * Wf))
    psf = psf / psf.max()
    m = W.aberrated_psf(coeffs, 550.0, 8.0, 10.0, n_grid=N, diam_px=DPX)
    # crop the PSF to the bright core for legibility
    c = N // 2
    half = 36
    core = psf[c - half:c + half, c - half:c + half]
    logpsf = np.log10(np.clip(core, 1e-5, 1.0))

    a_top = ax[0, col]
    vis = np.where(mask > 0, Wf, np.nan)
    im_w = a_top.imshow(vis, cmap="RdBu_r", origin="lower", vmin=-0.22, vmax=0.22)
    rms = m["rms_wavefront_waves"]
    a_top.set_title("%s\nRMS = %.3f waves" % (label, rms), color=TX, fontsize=10.5)
    a_top.set_xticks([]); a_top.set_yticks([]); a_top.set_facecolor(BG)

    a_bot = ax[1, col]
    a_bot.imshow(logpsf, cmap="inferno", origin="lower", vmin=-5, vmax=0)
    a_bot.set_title("Strehl = %.3f" % m["strehl"], color=TX, fontsize=10.5)
    a_bot.set_xticks([]); a_bot.set_yticks([]); a_bot.set_facecolor(BG)
    for a_ in (a_top, a_bot):
        for s in a_.spines.values():
            s.set_color(GR)

ax[0, 0].set_ylabel("pupil wavefront", color=MU, fontsize=9.5)
ax[1, 0].set_ylabel("PSF (log10)", color=MU, fontsize=9.5)

fig.text(0.5, 0.025, "Ideal: flat wavefront -> Airy core, Strehl 1. Each aberration is 0.10 waves RMS in ONE Noll "
                     "mode: the Strehl drops to ~0.674 (Marechal) for ALL of them, but the PSF morphology differs -- "
                     "defocus symmetric, astigmatism elongated, coma flared, spherical haloed. Off-trace; live trace byte-identical.",
         color=MU, fontsize=7.8, ha="center")
fig.tight_layout(rect=(0.012, 0.055, 1, 0.93))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/aberrated-psf-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
