"""Draw docs/img/dichroic-edge.png from /tmp/dich/sweep.json (the soft dichroic-edge demo).

The TRACED reflected/transmitted power vs wavelength through a longpass dichroic (cut 650 nm): a real
coating has a FINITE-slope edge, so near the cut the beam PARTIALLY reflects AND transmits, with
R + T = 1 (energy conserved exactly). The dashed line is the old all-or-nothing HARD step. A LINE plot
(no colorbar) — it borrows the shared `figstyle` theme + footer + reserved-margin save for consistency.
"""
import os
import json
import numpy as np
import figstyle as fs

SRC = "/tmp/dich/sweep.json"
d = json.load(open(SRC))
cut = d["cut"]
rows = np.array(d["rows"])
wl, T, R = rows[:, 0], rows[:, 1], rows[:, 2]

fig, axes = fs.grid(1, 1, w=9.2, h=5.4,
                    title="Soft-edge dichroic: wavelength-selective R(λ) + T(λ) = 1 (traced)")
ax = axes[0]                                            # a line plot uses the themed axes directly
ax.plot(wl, R, color="#5b8bf0", lw=2.6, label="R(λ) reflected  (short λ)")
ax.plot(wl, T, color="#e0683c", lw=2.6, label="T(λ) transmitted  (long λ)")
ax.plot(wl, R + T, color=fs.THEME["muted"], lw=1.2, ls=":", label="R + T = 1  (energy conserved)")
ax.plot(wl, np.where(wl < cut, 1.0, 0.0), color="#55585f", lw=1.3, ls="--", label="old hard step (R)")
ax.axvline(cut, color="#9a9aa2", lw=1.0, ls="-", alpha=0.5)
ax.annotate("cut λ = %.0f nm\nR = T = 0.5" % cut, xy=(cut, 0.5), xytext=(cut + 14, 0.62),
            color=fs.THEME["fg"], fontsize=9.5, arrowprops=dict(arrowstyle="->", color="#9a9aa2"))
ax.set_xlabel("wavelength λ (nm)", color="#c8c8ce", fontsize=10)
ax.set_ylabel("power fraction", color="#c8c8ce", fontsize=10)
ax.set_ylim(-0.03, 1.08)
ax.tick_params(colors=fs.THEME["muted"], labelsize=8.5)
for s in ax.spines.values():
    s.set_color(fs.THEME["grid"])
ax.legend(loc="center left", fontsize=8.6, framealpha=0.0, labelcolor="#d8d8dc")

fs.footer(fig, "A longpass dichroic transmits long λ, reflects short λ; the edge is a logistic of width edge_width "
               "centred at the cut (a Tier-1 modelling choice). Near the cut the beam PARTIALLY splits — the finite-"
               "slope edge a real coating has, not the all-or-nothing step (dashed). Far from the cut it saturates to "
               "full reflect / transmit (byte-identical to the old step).")
fs.finalize(fig, "docs/img/dichroic-edge.png", has_colorbar=False, left=0.085, bottom=0.16)
print("SAVED docs/img/dichroic-edge.png")
