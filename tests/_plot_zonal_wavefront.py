"""Draw docs/img/zonal-wavefront.png from the /tmp/zonal/*.npy dumped by _render_zonal_wavefront.py.

2 rows (KNIGHT high-spatial-frequency relief; a gently-figured REAL OPTIC) x 2 cols (MODAL 15-Zernike
re-sum -- a low-pass; ZONAL dense raw field). Each panel: a diverging wavefront map (waves) with its own
symmetric colour scale + colorbar + RMS, so the modal->zonal difference reads. Plain Python + matplotlib
(not available inside Blender), so it runs as a second pass on the dumped arrays.
"""
import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/zonal"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "img", "zonal-wavefront.png")

meta = json.load(open(os.path.join(SRC, "meta.json")))
rows = []
if os.path.exists(os.path.join(SRC, "knight_modal.npy")):
    rows.append(("knight", "Chess-knight reflector  (high-spatial-frequency relief)"))
rows.append(("optic", "Figured mirror  (faint astigmatism + ~2 mm MSF polishing ripple)"))

fig, axes = plt.subplots(len(rows), 2, figsize=(9.4, 4.7 * len(rows)))
if len(rows) == 1:
    axes = axes.reshape(1, 2)
fig.patch.set_facecolor("#0d0d10")

col_titles = ["MODAL  (15 Noll Zernike re-sum — low-pass)", "ZONAL  (dense raw field — full spatial content)"]


def _panel(ax, field, title, rms_note, cbar_label, clip_pct=99.0, intensity=None):
    ax.set_facecolor("#0d0d10")
    finite = np.abs(field[np.isfinite(field)])
    # robust symmetric scale: clip to the clip_pct percentile so a few extreme outliers (a knight's deep
    # recesses) don't wash out the relief. The RMS annotation is still the FULL-field value (honest).
    full = float(np.nanmax(finite)) if finite.size else 1.0
    vmax = float(np.percentile(finite, clip_pct)) if finite.size else 1.0
    vmax = vmax or 1.0
    # FADE the map by the Gaussian beam intensity (alpha) so it shows the actual beam -- bright centre, dim
    # 1/e^2 edge -- not a hard top-hat disc. The faded pixels blend into the dark panel background.
    alpha = None
    if intensity is not None:
        a = np.where(np.isfinite(intensity), np.clip(intensity, 0.0, 1.0), 0.0)
        alpha = np.where(np.isfinite(field), a, 0.0)
    im = ax.imshow(field, cmap="RdBu_r", vmin=-vmax, vmax=vmax, origin="lower",
                   interpolation="nearest", alpha=alpha)
    ax.set_title(title, color="#e8e8ea", fontsize=11, pad=7)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#33343a")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label(cbar_label, color="#b9b9c0", fontsize=8)
    cb.ax.tick_params(colors="#9a9aa2", labelsize=7)
    cb.outline.set_edgecolor("#33343a")
    note = rms_note
    if clip_pct < 99.0 and full > 2.0 * vmax:                 # heavily clipped -> say so (honest)
        note += "\nscale clipped ±%.0f (full ±%.0f)" % (vmax, full)
    ax.text(0.03, 0.04, note, transform=ax.transAxes, color="#f2f2f4",
            fontsize=9, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="#000000aa", ec="none"))


def _fmt(v):
    return ("%.0f" % v) if abs(v) > 100 else ("%.3f" % v)


for r, (key, rlabel) in enumerate(rows):
    modal = np.load(os.path.join(SRC, key + "_modal.npy"))
    zonal = np.load(os.path.join(SRC, key + "_zonal.npy"))
    inten = np.load(os.path.join(SRC, key + "_intensity.npy")) if os.path.exists(
        os.path.join(SRC, key + "_intensity.npy")) else None
    m = meta[key]
    mr = "RMS = %s waves" % _fmt(m["modal_rms"])
    # zonal RMS now beam-weighted (what the Gaussian beam senses) + the uniform clear-aperture figure
    zr = "RMS = %s waves  (beam-weighted)\n%s uniform" % (_fmt(m["zonal_rms"]), _fmt(m["zonal_rms_uniform"]))
    # the knight's OPD is extreme-tailed (PV ~1.7e5 waves) -> clip its zonal map hard so the surface relief
    # reads; a real optic is well-behaved (no clip needed).
    z_clip = 73.0 if key == "knight" else 99.0
    _panel(axes[r][0], modal, (col_titles[0] if r == 0 else ""), mr, "waves", intensity=inten)
    _panel(axes[r][1], zonal, (col_titles[1] if r == 0 else ""), zr, "waves", clip_pct=z_clip, intensity=inten)
    axes[r][0].set_ylabel(rlabel, color="#d8d8dc", fontsize=10, labelpad=12)
    # row footnote: sampling metadata
    axes[r][1].text(1.30, 0.5, "%dpx  ·  Ø%.0f mm\nNyquist %.2f lp/mm\nhits %.0f%%"
                    % (m["px"], m["footprint_mm"], m["nyquist_lp_mm"], 100.0 * m["hit_frac"]),
                    transform=axes[r][1].transAxes, color="#8a8a92", fontsize=7.5, va="center", ha="left")

fig.suptitle("Surface-figure wavefront:  modal (15-mode, low-pass)  vs  zonal (dense, faithful)",
             color="#f4f4f6", fontsize=12.5, y=0.995)
fig.text(0.5, 0.008,
         "Same verified physics (W = 2·cos²θ·Δdepth on reflection, oracle ok=true); the zonal map skips the 15-mode projection, "
         "so mid/high-spatial-frequency figure survives up to the grid Nyquist.  The footprint is sampled as "
         "the GAUSSIAN beam (I = exp(−2ρ²)) — maps fade at the dim 1/e² edge and the RMS is beam-weighted "
         "(what the beam senses), not a top-hat.  A knight is NOT an optic — its map is geometrically real "
         "but optically meaningless; the figured mirror is the honest use-case.",
         color="#7a7a82", fontsize=7.2, ha="center", va="bottom", wrap=True)
fig.subplots_adjust(left=0.06, right=0.90, top=0.93, bottom=0.07, hspace=0.13, wspace=0.05)
fig.savefig(OUT, dpi=145, facecolor=fig.get_facecolor())
print("SAVED", OUT)
