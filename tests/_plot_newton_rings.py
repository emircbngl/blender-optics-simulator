"""Generate docs/img/newton-rings-demo.png -- the 2-D Newton's-rings reflected pattern + radial profile.

Left: the concentric ring intensity I(r)=sin^2(pi r^2/(lambda R)) of a plano-convex surface (R) on a flat --
a central DARK spot and dark rings.  Right: the radial profile with the closed-form dark-ring radii
r_m = sqrt(m lambda R) (physics.newton_ring_radius) marked -- the nulls land exactly on them.
Run:  python3 tests/_plot_newton_rings.py
"""
import os
import sys
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import physics as P  # bpy-free; the same formula diagnostics.newton_rings_2d uses (validated in the Blender suite)

BG, FG, TX, MU, GR, AC = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0"
R_MM, WL, NR = 1000.0, 589.3, 8
ext = 0.5 * (2.2 * P.newton_ring_radius(NR, WL, R_MM))         # field out to ~ the NR-th ring
_ax = np.linspace(-ext, ext, 500)
_X, _Y = np.meshgrid(_ax, _ax)
I = np.sin(np.pi * (_X ** 2 + _Y ** 2) / (WL * 1e-6 * R_MM)) ** 2

fig, ax = plt.subplots(1, 2, figsize=(12.6, 4.8), gridspec_kw={"width_ratios": [1, 1.25]})
fig.patch.set_facecolor(BG)
fig.suptitle("Newton's rings -- plano-convex surface (R=%g mm) on a flat, %g nm: I(r)=sin²(πr²/λR)" % (R_MM, WL),
             color=FG, fontsize=12.0, fontweight="bold", y=0.98)

# (a) the 2D ring pattern
a = ax[0]
a.imshow(I, cmap="gray", origin="lower", extent=(-ext, ext, -ext, ext))
a.set_title("(a) reflected intensity -- central dark spot + rings", color=TX, fontsize=10.5)
a.set_xlabel("mm", color=MU, fontsize=9); a.set_ylabel("mm", color=MU, fontsize=9)
a.tick_params(colors=MU, labelsize=8)

# (b) radial profile with the closed-form dark radii
b = ax[1]
r = np.linspace(0, ext, 600)
prof = np.sin(np.pi * r ** 2 / (WL * 1e-6 * R_MM)) ** 2
b.plot(r, prof, color=AC, lw=1.8)
for m in range(1, NR + 1):
    rm = P.newton_ring_radius(m, WL, R_MM)
    if rm <= ext:
        b.axvline(rm, color="#c0653a", lw=0.8, ls="--", alpha=0.7)
b.axvline(np.nan, color="#c0653a", lw=0.8, ls="--", label="$r_m=\\sqrt{m\\lambda R}$ (closed form)")
b.scatter([0], [0], color="#e0a23a", s=40, zorder=4, label="central dark spot")
b.set_xlabel("radius r (mm)", color=MU, fontsize=9)
b.set_ylabel("reflected intensity", color=MU, fontsize=9)
b.set_title("(b) radial profile -- nulls land on $\\sqrt{m\\lambda R}$", color=TX, fontsize=10.5)
b.set_facecolor(BG); b.tick_params(colors=MU, labelsize=8)
b.grid(True, color=GR, lw=0.4, alpha=0.4)
b.legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.5)
for s in b.spines.values():
    s.set_color(GR)
for s in a.spines.values():
    s.set_color(GR)

fig.text(0.5, 0.015, "The quadratic air gap t(r)=r²/2R makes the two reflections interfere; the half-wave phase on "
                     "reflection at the flat gives the CENTRAL DARK spot, and dark rings fall exactly at r_m=sqrt(mλR). "
                     "Off-trace; live trace byte-identical.", color=MU, fontsize=7.6, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.93))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/newton-rings-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
