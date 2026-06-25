"""Draw docs/img/dichroic-edge.png from /tmp/dich/sweep.json (the soft dichroic-edge demo).

The TRACED reflected/transmitted power vs wavelength through a longpass dichroic (cut 650 nm): a real
coating has a FINITE-slope edge, so near the cut the beam PARTIALLY reflects AND transmits, with
R + T = 1 (energy conserved exactly). The dashed line is the old all-or-nothing HARD step. Plain Python
+ matplotlib (a second pass on the dumped trace data).
"""
import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SRC = "/tmp/dich/sweep.json"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "img", "dichroic-edge.png")

d = json.load(open(SRC))
cut = d["cut"]
rows = np.array(d["rows"])
wl, T, R = rows[:, 0], rows[:, 1], rows[:, 2]

fig, ax = plt.subplots(figsize=(9.0, 5.2))
fig.patch.set_facecolor("#0d0d10")
ax.set_facecolor("#0d0d10")

ax.plot(wl, R, color="#5b8bf0", lw=2.6, label="R(λ) reflected  (short λ)")
ax.plot(wl, T, color="#e0683c", lw=2.6, label="T(λ) transmitted  (long λ)")
ax.plot(wl, R + T, color="#7a7a82", lw=1.2, ls=":", label="R + T = 1  (energy conserved)")
# old hard step (all-or-nothing) for contrast
step = np.where(wl < cut, 1.0, 0.0)
ax.plot(wl, step, color="#55585f", lw=1.3, ls="--", label="old hard step (R)")

ax.axvline(cut, color="#9a9aa2", lw=1.0, ls="-", alpha=0.5)
ax.annotate("cut λ = %.0f nm\nR = T = 0.5" % cut, xy=(cut, 0.5), xytext=(cut + 14, 0.62),
            color="#f2f2f4", fontsize=9.5,
            arrowprops=dict(arrowstyle="->", color="#9a9aa2"))

ax.set_xlabel("wavelength λ (nm)", color="#c8c8ce", fontsize=10)
ax.set_ylabel("power fraction", color="#c8c8ce", fontsize=10)
ax.set_title("Soft-edge dichroic: wavelength-selective R(λ) + T(λ) = 1 (traced)",
             color="#f4f4f6", fontsize=13, pad=10)
ax.set_ylim(-0.03, 1.08)
ax.tick_params(colors="#9a9aa2", labelsize=8.5)
for s in ax.spines.values():
    s.set_color("#33343a")
leg = ax.legend(loc="center left", fontsize=8.6, framealpha=0.0, labelcolor="#d8d8dc")
fig.text(0.5, 0.005,
         "A longpass dichroic transmits long λ, reflects short λ; the edge is a logistic of width "
         "edge_width centred at the cut (a Tier-1 modelling choice). Near the cut the beam PARTIALLY "
         "splits — the finite-slope edge a real coating has, not the all-or-nothing step (dashed). "
         "Far from the cut it saturates to full reflect / transmit (byte-identical to the old step).",
         color="#7a7a82", fontsize=7.6, ha="center", va="bottom", wrap=True)
fig.subplots_adjust(left=0.08, right=0.97, top=0.91, bottom=0.16)
fig.savefig(OUT, dpi=150, facecolor=fig.get_facecolor())
print("SAVED", OUT)
