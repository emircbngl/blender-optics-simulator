"""Generate docs/img/birefringence-demo.png -- TRUE o/e double refraction (the slab geometry the tracer emits).

Left: the beam path -- one beam enters the calcite, two PARALLEL beams (ordinary + extraordinary) leave,
separated by L*tan(rho) (the tracer's verified output; tests/_verify_birefringence.py asserts the displacement
matches this to 1e-3 mm).
Right: the screen face -- the two spots of the double image, the o-beam on-axis, the e-beam walked off.
Run:  python3 tests/_plot_birefringence.py
"""
import os
import sys
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import physics as P

# scene layout (mm), beam along +x: source -> calcite slab [-L/2, +L/2] -> screen
X_SRC, X_SCREEN, L, CUT = -60.0, 70.0, 20.0, 45.0
n_o = P.sellmeier_n(532.0, 'CALCITE_O')
n_e = P.sellmeier_n(532.0, 'CALCITE_E')
rho = P.uniaxial_walkoff_angle(n_o, n_e, CUT)         # extraordinary walk-off (verified 6.224deg @589, ~6.19 @532)
disp = L * math.tan(math.radians(rho))                # the fixed slab displacement L*tan(rho)

BG, FG, TX, MU, GR, ACo, ACe = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0", "#e0a23a"
fig, ax = plt.subplots(1, 2, figsize=(13.4, 4.6), gridspec_kw={"width_ratios": [2.4, 1]})
fig.patch.set_facecolor(BG)
fig.suptitle("True o/e double refraction -- calcite (cut %g deg, %g mm): one beam in, two parallel beams out (rho=%.2f deg)"
             % (CUT, L, rho), color=FG, fontsize=12.0, fontweight="bold", y=0.98)

# (a) beam path in the (propagation, walk) plane
a = ax[0]
a.axvspan(-0.5 * L, 0.5 * L, color="#3a4a6a", alpha=0.30)                 # the calcite slab
a.plot([X_SRC, -0.5 * L], [0, 0], color=FG, lw=2.4)                       # input beam -> crystal
a.plot([0.5 * L, X_SCREEN], [0, 0], color=ACo, lw=2.4, label="ordinary (n$_o$=%.4f, undeviated)" % n_o)
a.plot([0.5 * L, X_SCREEN], [disp, disp], color=ACe, lw=2.4,
       label="extraordinary (n$_e$=%.4f, walked off)" % n_e)
a.plot([-0.5 * L, 0.5 * L], [0, disp], color=ACe, lw=1.6, ls=(0, (3, 2)), alpha=0.8)   # walk inside the slab
a.plot([-0.5 * L, 0.5 * L], [0, 0], color=ACo, lw=1.6, ls=(0, (3, 2)), alpha=0.8)
a.annotate("calcite", (0.0, disp + 0.9), color="#9ab", ha="center", fontsize=9)
a.annotate("", xy=(X_SCREEN - 2, disp), xytext=(X_SCREEN - 2, 0),
           arrowprops=dict(arrowstyle="<->", color=MU, lw=1.0))
a.text(X_SCREEN - 5, 0.5 * disp, "L·tan$\\rho$\n=%.2f mm" % disp, color=TX, fontsize=8.5, ha="right", va="center")
a.set_xlabel("propagation (mm)", color=MU, fontsize=9)
a.set_ylabel("walk-off transverse (mm)", color=MU, fontsize=9)
a.set_ylim(-3.5, disp + 3.5)
a.set_title("(a) beam path -- the e-beam emerges PARALLEL but displaced", color=TX, fontsize=10.5)

# (b) the screen face -- two spots
b = ax[1]
b.scatter([0], [0], s=460, color=ACo, edgecolors=FG, linewidths=1.2, label="ordinary", zorder=3)
b.scatter([0], [disp], s=460, color=ACe, edgecolors=FG, linewidths=1.2, label="extraordinary", zorder=3)
b.set_xlim(-6, 6)
b.set_ylim(-4, disp + 4)
b.set_title("(b) the double image on the screen", color=TX, fontsize=10.5)
b.set_xlabel("screen x (mm)", color=MU, fontsize=9)
b.set_ylabel("screen y (mm)", color=MU, fontsize=9)

for a_ in ax:
    a_.set_facecolor(BG)
    a_.tick_params(colors=MU, labelsize=8)
    for sp in a_.spines.values():
        sp.set_color(GR)
    a_.grid(True, color=GR, lw=0.4, alpha=0.4)
    a_.legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.3, loc="upper left")

fig.text(0.5, 0.015, "Circular input -> the crystal projects it onto two orthogonal eigen-polarizations: the ordinary ray "
                     "(straight) and the extraordinary ray (walks off by rho inside the slab, emerges parallel but displaced "
                     "by L*tan(rho)). Energy conserved, beams orthogonally polarized. Opt-in; live trace byte-identical.",
         color=MU, fontsize=7.5, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.93))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/birefringence-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out, "| rho=%.3f deg, displacement=%.3f mm" % (rho, disp))
