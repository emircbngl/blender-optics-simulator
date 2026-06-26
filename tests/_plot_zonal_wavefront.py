"""Draw docs/img/zonal-wavefront.png from the /tmp/zonal/*.npy dumped by _render_zonal_wavefront.py.

2 rows (KNIGHT high-spatial-frequency relief; a gently-figured REAL OPTIC) x 2 cols (MODAL 15-Zernike
re-sum -- a low-pass; ZONAL dense raw field). Uses the shared `figstyle` schema with PER-PANEL colorbars
(each panel auto-scales independently, so a single shared colorbar would be wrong); each colorbar gets its
own reserved slot and the figure is saved tight, so no colorbar tick label is clipped and the per-row
sampling metadata rides in the zonal panel's caption instead of running off the right edge (the previous
bug). Plain Python + matplotlib (a second pass on the dumped arrays).
"""
import os
import json
import numpy as np
import figstyle as fs

SRC = "/tmp/zonal"
meta = json.load(open(os.path.join(SRC, "meta.json")))
rows = []
if os.path.exists(os.path.join(SRC, "knight_modal.npy")):
    rows.append(("knight", "Chess-knight reflector  (high-spatial-frequency relief)"))
rows.append(("optic", "Figured mirror  (faint astigmatism + ~2 mm MSF polishing ripple)"))
col_titles = ["MODAL  (15 Noll Zernike re-sum — low-pass)", "ZONAL  (dense raw field — full content)"]


def _fmt(v):
    return ("%.0f" % v) if abs(v) > 100 else ("%.3f" % v)


fig, axes = fs.grid(len(rows), 2, w=10.6, h=5.0 * len(rows),
                    title="Surface-figure wavefront:  modal (15-mode, low-pass)  vs  zonal (dense, faithful)")
for r, (key, rlabel) in enumerate(rows):
    modal = np.load(os.path.join(SRC, key + "_modal.npy"))
    zonal = np.load(os.path.join(SRC, key + "_zonal.npy"))
    ip = os.path.join(SRC, key + "_intensity.npy")
    inten = np.load(ip) if os.path.exists(ip) else None
    m = meta[key]
    cols = [
        (modal, 99.0, "RMS = %s waves" % _fmt(m["modal_rms"]), None),
        (zonal, (73.0 if key == "knight" else 99.0),
         "RMS = %s (beam-wtd) / %s uniform" % (_fmt(m["zonal_rms"]), _fmt(m["zonal_rms_uniform"])),
         "%dpx  ·  Ø%.0f mm  ·  Nyquist %.2f lp/mm  ·  hits %.0f%%"
         % (m["px"], m["footprint_mm"], m["nyquist_lp_mm"], 100.0 * m["hit_frac"])),
    ]
    for c, (field, clip_pct, note, cap) in enumerate(cols):
        ax = axes[r * 2 + c]
        finite = np.abs(field[np.isfinite(field)])
        vmax = float(np.percentile(finite, clip_pct)) if finite.size else 1.0
        vmax = vmax or 1.0
        alpha = None
        if inten is not None:
            a = np.where(np.isfinite(inten), np.clip(inten, 0.0, 1.0), 0.0)
            alpha = np.where(np.isfinite(field), a, 0.0)
        im = fs.image_panel(ax, field, vmin=-vmax, vmax=vmax,
                            title=(col_titles[c] if r == 0 else None), caption=cap, alpha=alpha)
        fs.panel_colorbar(fig, ax, im, label="waves")
        ax.text(0.03, 0.04, note, transform=ax.transAxes, color="#f2f2f4", fontsize=8.5,
                va="bottom", ha="left", bbox=dict(boxstyle="round,pad=0.3", fc="#000000aa", ec="none"))
    axes[r * 2].set_ylabel(rlabel, color="#d8d8dc", fontsize=9.5, labelpad=10)

fs.footer(fig, "Same verified physics (W = 2·cos²θ·Δdepth on reflection, oracle ok=true); the zonal map skips the "
               "15-mode projection, so mid/high-spatial-frequency figure survives up to the grid Nyquist.  The footprint "
               "is the GAUSSIAN beam (I = exp(−2ρ²)) — maps fade at the 1/e² edge.  A knight is NOT an optic; the figured "
               "mirror is the honest use-case.")
fs.finalize(fig, "docs/img/zonal-wavefront.png", has_colorbar=False, right=0.90, wspace=0.34, bottom=0.12)
print("SAVED docs/img/zonal-wavefront.png")
