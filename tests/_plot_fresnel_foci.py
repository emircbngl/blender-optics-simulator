"""Generate docs/img/fresnel-foci-demo.png -- the Fresnel-diffraction + focusing example board.

Four textbook setups, each reproduced LIVE by the off-trace angular-spectrum field engine and checked
against the closed form in tests/test_validation.py:
  (a) circular-aperture on-axis Fresnel zones   I_axis/I0 = 4 sin^2(pi N_F/2)   (odd N_F -> 4, even -> 0)
  (b) straight-edge (knife-edge) Fresnel pattern  I(edge) = 1/4 I0 + Cornu overshoot fringes
  (c) Fresnel zone-plate axial focus            on-axis peak at z = f = r1^2/lambda
  (d) thin-lens (quadratic-phase) axial waist   2nd-moment minimum at z = f
Run:  blender --background --factory-startup --python tests/_plot_fresnel_foci.py
(only needs numpy + the field module; no scene -- runs under plain python3 too.)
"""
import os, sys
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                   # figstyle
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "optical_alignment_sim"))
import figstyle as fs
import field as F

T = fs.THEME
fig, ax = fs.grid(2, 2, w=12.2, h=8.0,
                  title="Fresnel diffraction & focusing -- field engine vs textbook closed forms",
                  subtitle="off-trace angular-spectrum FFT  -- every marked value is an oracle check in test_validation.py")

# (a) circular-aperture on-axis Fresnel zones -----------------------------------------------------------
a, lam, N = 0.5, 500.0, 1024
dx = 2.2 * 2 * a / N
ap = F.circular_aperture(N, dx, 2 * a); c = N // 2
nfs = np.array([0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5])
I_fft = np.array([float(np.abs(F.angular_spectrum(ap, dx, a ** 2 / (lam * 1e-6 * nf), lam)[c, c]) ** 2) for nf in nfs])
nf_th = np.linspace(0.3, 5.2, 400)
ax[0].plot(nf_th, 4 * np.sin(np.pi * nf_th / 2) ** 2, color=T["muted"], lw=1.4, label="4 sin$^2$($\\pi N_F$/2)  (theory)")
ax[0].plot(nfs, I_fft, "o", color=T["accent"], ms=6, label="angular-spectrum FFT")
ax[0].axhline(4.0, color=T["grid"], lw=0.8, ls=":")
ax[0].set_title("(a) circular aperture: on-axis Fresnel zones", color=T["text"], fontsize=11.5)
ax[0].set_xlabel("Fresnel number  $N_F = a^2/\\lambda z$", color=T["text"], fontsize=9.5)
ax[0].set_ylabel("$I_{axis}/I_0$", color=T["text"], fontsize=9.5)
ax[0].legend(facecolor=T["bg"], edgecolor=T["grid"], labelcolor=T["text"], fontsize=8.4, loc="upper right")

# (b) knife-edge (straight-edge) Fresnel pattern --------------------------------------------------------
kN, kdx = 2048, 0.004
kx = (np.arange(kN) - kN // 2) * kdx
U0 = np.zeros((kN, kN), dtype=complex); U0[:, kx >= 0] = 1.0
kI = np.abs(F.angular_spectrum(U0, kdx, 300.0, 500.0)[kN // 2, :]) ** 2
m = np.abs(kx) <= 6.0
ax[1].plot(kx[m], kI[m], color=T["accent"], lw=1.3)
ax[1].axvline(0.0, color=T["grid"], lw=0.8, ls=":")
ax[1].plot([0.0], [kI[kN // 2]], "o", color=T["fg"], ms=6)
ax[1].annotate("I = 0.25 $I_0$ at the edge", xy=(0.0, kI[kN // 2]), xytext=(1.0, 0.55),
               color=T["text"], fontsize=8.6, arrowprops=dict(color=T["muted"], arrowstyle="->", lw=0.8))
ax[1].set_title("(b) straight-edge (knife-edge) Fresnel pattern", color=T["text"], fontsize=11.5)
ax[1].set_xlabel("transverse position  x (mm)  -- edge at x=0", color=T["text"], fontsize=9.5)
ax[1].set_ylabel("$I/I_0$", color=T["text"], fontsize=9.5)

# (c) zone-plate axial focus ----------------------------------------------------------------------------
zlam, zf = 500.0, 200.0
zr1 = (zlam * 1e-6 * zf) ** 0.5; zN = 1024; zdx = 20 * zr1 / zN
zx = (np.arange(zN) - zN // 2) * zdx; zX, zY = np.meshgrid(zx, zx); zr = np.sqrt(zX ** 2 + zY ** 2)
zap = ((np.sin(np.pi * zr ** 2 / (zlam * 1e-6 * zf)) > 0) & (zr <= 8 * zr1)).astype(complex)
zz = np.linspace(0.6 * zf, 1.4 * zf, 41)
zI = np.array([float(np.abs(F.angular_spectrum(zap, zdx, z, zlam)[zN // 2, zN // 2]) ** 2) for z in zz])
ax[2].plot(zz, zI / zI.max(), color=T["accent"], lw=1.4)
ax[2].axvline(zf, color=T["grid"], lw=0.9, ls="--")
ax[2].annotate("z = f = $r_1^2/\\lambda$ = 200 mm", xy=(zf, 1.0), xytext=(zf * 0.62, 0.78),
               color=T["text"], fontsize=8.6, arrowprops=dict(color=T["muted"], arrowstyle="->", lw=0.8))
ax[2].set_title("(c) Fresnel zone-plate: on-axis focus", color=T["text"], fontsize=11.5)
ax[2].set_xlabel("axial distance  z (mm)", color=T["text"], fontsize=9.5)
ax[2].set_ylabel("on-axis intensity (norm.)", color=T["text"], fontsize=9.5)

# (d) thin-lens axial waist -----------------------------------------------------------------------------
lf, lD, llam, lN = 300.0, 4.0, 500.0, 1024
ldx = 2.5 * lD / lN
lx = (np.arange(lN) - lN // 2) * ldx; lX, lY = np.meshgrid(lx, lx); lr2 = lX ** 2 + lY ** 2
lap = (lr2 <= (lD / 2) ** 2).astype(complex) * np.exp(-1j * np.pi * lr2 / (llam * 1e-6 * lf))
lz = np.linspace(0.5 * lf, 1.5 * lf, 41)
lw = np.array([F.field_metrics(F.angular_spectrum(lap, ldx, z, llam), ldx, llam)["w_2sigma_mm"] for z in lz])
ax[3].plot(lz, lw, color=T["accent"], lw=1.4)
ax[3].axvline(lf, color=T["grid"], lw=0.9, ls="--")
ax[3].annotate("waist minimum at z = f = 300 mm", xy=(lf, lw.min()), xytext=(lf * 1.02, lw.max() * 0.7),
               color=T["text"], fontsize=8.6, arrowprops=dict(color=T["muted"], arrowstyle="->", lw=0.8))
ax[3].set_title("(d) thin-lens (quadratic phase): axial waist", color=T["text"], fontsize=11.5)
ax[3].set_xlabel("axial distance  z (mm)", color=T["text"], fontsize=9.5)
ax[3].set_ylabel("$w_{2\\sigma}$ (mm)", color=T["text"], fontsize=9.5)

for a_ in ax:
    a_.tick_params(colors=T["muted"], labelsize=8)
    for s in a_.spines.values():
        s.set_color(T["grid"])

fs.footer(fig, "Each panel is the angular-spectrum FFT field engine reproducing a Hecht / Born & Wolf / Goodman "
               "closed form to oracle tolerance -- not a fit, a first-principles propagation.")
fs._LAYOUT["hspace"] = 0.42                                  # two stacked rows of titled line plots need room
out = fs.finalize(fig, "docs/img/fresnel-foci-demo.png", has_colorbar=False, has_footer=True,
                  bottom=0.10, top=0.87, wspace=0.22, right=0.965, left=0.07)
print("wrote", out)
