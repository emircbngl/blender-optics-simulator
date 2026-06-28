"""Generate docs/img/multiplane-chain-demo.png -- propagate_chain (POPPY-style multi-plane OpticalSystem).

Two panels:
  (a) beam width w(z) marched through an aperture -> lens(f) -> propagate chain: it CONVERGES to a focus at
      z = f then diverges -- the chain reproduces diffraction-limited focusing by stacking the angular-spectrum
      propagator and a lens phase mask.
  (b) the focal-plane intensity |U|^2 at z = f (the focused spot).
Run:  python3 tests/_plot_multiplane_chain.py   (needs numpy + matplotlib + field.py)
"""
import os, sys, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import field as F

BG, FG, TX, MU, GR, AC = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0"
wl, D, f, nN = 632.8, 3.0, 200.0, 512

# (a) w(z) along the aperture->lens(f)->prop chain
zs = np.linspace(0.5 * f, 1.5 * f, 41)
ws = [F.propagate_chain([("aperture", D), ("lens", f), ("prop", float(z))], wl, None, D, nN)["final"]["w_2sigma_mm"]
      for z in zs]

# (b) focal-plane field at z = f
Uf, dxf, _, _ = F._run_chain([("aperture", D), ("lens", f), ("prop", f)], wl, None, D, nN, None, True)
If = np.abs(Uf) ** 2
c = nN // 2
hw = 28                                                       # crop a small window around the focus
crop = If[c - hw:c + hw, c - hw:c + hw]

fig, ax = plt.subplots(1, 2, figsize=(11.0, 4.0))
fig.patch.set_facecolor(BG)
fig.suptitle("propagate_chain -- multi-plane OpticalSystem: aperture -> lens(f=200mm) -> propagate",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)

ax[0].plot(zs, np.array(ws) * 1000.0, color=AC, lw=1.6)
ax[0].axvline(f, color=GR, lw=0.9, ls="--")
ax[0].annotate("focus at z = f = 200 mm", xy=(f, min(ws) * 1000.0), xytext=(f * 1.02, max(ws) * 1000.0 * 0.6),
               color=TX, fontsize=8.6, arrowprops=dict(color=MU, arrowstyle="->", lw=0.8))
ax[0].set_title("(a) beam width through the chain", color=TX, fontsize=11)
ax[0].set_xlabel("axial distance z (mm)", color=TX, fontsize=9.5)
ax[0].set_ylabel("w (um)", color=TX, fontsize=9.5)

ax[1].imshow(crop / (crop.max() or 1.0), cmap="inferno", origin="lower",
             extent=[-hw * dxf * 1000, hw * dxf * 1000, -hw * dxf * 1000, hw * dxf * 1000])
ax[1].set_title("(b) focal-plane intensity at z = f", color=TX, fontsize=11)
ax[1].set_xlabel("x (um)", color=TX, fontsize=9.5); ax[1].set_ylabel("y (um)", color=TX, fontsize=9.5)

for a_ in ax:
    a_.set_facecolor(BG); a_.tick_params(colors=MU, labelsize=8)
    for s in a_.spines.values():
        s.set_color(GR)
fig.text(0.5, 0.01, "Chains the verified angular-spectrum propagator + lens/aperture phase masks. Off-trace; "
                    "near-field/moderate propagation (tight focus / far field -> direct FFT). Validated: "
                    "propagator additivity, focus at z=f, free Gaussian w(z).",
         color=MU, fontsize=7.6, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.94))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/multiplane-chain-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
