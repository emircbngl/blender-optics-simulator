"""Generate docs/img/biaxial-crystals-demo.png -- KTP/LBO principal-plane (XY) SHG phase-match tuning.

Left: the XY-plane phase-match azimuth phi vs the fundamental wavelength, for KTP (Type-II) and LBO (Type-I),
each annotated at the canonical 1064->532 cut (KTP 23.5 deg, LBO 11.6 deg) that the sourced Sellmeier reproduces.
Right: the three principal indices n_x < n_y < n_z of each crystal across the band -- the dispersion the phase
matching rides on. Run:  python3 tests/_plot_biaxial.py
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

BG, FG, TX, MU, GR = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a"
KTP_C, LBO_C = "#4a8db0", "#e0a23a"

fig, ax = plt.subplots(1, 2, figsize=(13.6, 4.6))
fig.patch.set_facecolor(BG)
fig.suptitle("Biaxial nonlinear crystals -- KTP / LBO XY-plane (theta=90) SHG phase matching, from sourced 3-axis Sellmeier",
             color=FG, fontsize=12.0, fontweight="bold", y=0.98)

# (a) phase-match azimuth phi vs fundamental wavelength
a = ax[0]
wl = np.linspace(900.0, 1300.0, 90)
ktp_phi = [P.biaxial_shg_phase_match_phi('KTP', float(w), 'TYPE2') for w in wl]
lbo_phi = [P.biaxial_shg_phase_match_phi('LBO', float(w), 'TYPE1') for w in wl]
a.plot([w for w, p in zip(wl, ktp_phi) if p is not None], [p for p in ktp_phi if p is not None],
        color=KTP_C, lw=2.2, label="KTP Type-II")
a.plot([w for w, p in zip(wl, lbo_phi) if p is not None], [p for p in lbo_phi if p is not None],
        color=LBO_C, lw=2.2, label="LBO Type-I")
a.scatter([1064], [P.biaxial_shg_phase_match_phi('KTP', 1064.0, 'TYPE2')], color=KTP_C, s=70, zorder=4,
          edgecolors=FG, linewidths=1.0)
a.scatter([1064], [P.biaxial_shg_phase_match_phi('LBO', 1064.0, 'TYPE1')], color=LBO_C, s=70, zorder=4,
          edgecolors=FG, linewidths=1.0)
a.annotate("KTP 1064->532: phi=23.5 deg (lit 23.5)", (1064, 23.58), color=KTP_C, fontsize=8.2,
           xytext=(1075, 27), arrowprops=dict(arrowstyle="->", color=KTP_C, lw=0.8))
a.annotate("LBO 1064->532: phi=11.8 deg (lit 11.6)", (1064, 11.76), color=LBO_C, fontsize=8.2,
           xytext=(1075, 8), arrowprops=dict(arrowstyle="->", color=LBO_C, lw=0.8))
a.set_xlabel("fundamental wavelength (nm)", color=MU, fontsize=9)
a.set_ylabel("phase-match azimuth phi (deg)", color=MU, fontsize=9)
a.set_title("(a) XY-plane phase-match tuning curve", color=TX, fontsize=10.5)

# (b) principal indices across the band
b = ax[1]
wl2 = np.linspace(450.0, 1300.0, 120)
for cr, col in (('KTP', KTP_C), ('LBO', LBO_C)):
    cs = P.BIAXIAL_SELLMEIER[cr]
    for k, ls in zip(range(3), ('-', '--', ':')):
        n = [math.sqrt(P._formula4_n2(cs[k], float(w) * 1e-3)) for w in wl2]
        b.plot(wl2, n, color=col, lw=1.6, ls=ls,
               label=("%s n_%s" % (cr, ['x', 'y', 'z'][k])) if True else None)
b.set_xlabel("wavelength (nm)", color=MU, fontsize=9)
b.set_ylabel("principal index n", color=MU, fontsize=9)
b.set_title("(b) principal indices n_x < n_y < n_z (the dispersion)", color=TX, fontsize=10.5)

for a_ in ax:
    a_.set_facecolor(BG)
    a_.tick_params(colors=MU, labelsize=8)
    for s in a_.spines.values():
        s.set_color(GR)
    a_.grid(True, color=GR, lw=0.4, alpha=0.4)
    a_.legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.0, ncol=2 if a_ is b else 1)

fig.text(0.5, 0.015, "In the XY principal plane the biaxial problem reduces to effective-uniaxial: the Z-polarized wave sees "
                     "the fixed n_z, the in-plane wave a phi-tuned index between n_y and n_x. The sourced refractiveindex.info "
                     "Sellmeier reproduces the textbook cuts. Off-trace; live trace byte-identical.",
         color=MU, fontsize=7.5, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.93))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/biaxial-crystals-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
