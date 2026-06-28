"""Generate docs/img/phenomenon-emergence-demo.png -- the condition->emergence board.

detect_phenomena FLAGS that a phenomenon's conditions are met; produce_phenomenon EMERGES it. Three panels:
  (a) off-axis HOLOGRAM: the recorded carrier interferogram I(x)=1+V cos(2 pi x/Lambda), Lambda=lambda/(2 sin(theta/2))
  (b) RECONSTRUCTION: the hologram's FFT -- the carrier peak recovers the object beam's crossing angle
  (c) two-beam INTERFERENCE: the fringe curve I(OPD) and its visibility V
Run:  python3 tests/_plot_phenomenon_emergence.py   (needs numpy + matplotlib)
"""
import os, sys, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optical_alignment_sim"))
import physics as P

BG, FG, TX, MU, GR, AC = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0"
wl_nm, theta_deg, vis = 632.8, 10.0, 1.0
wl_mm = wl_nm * 1e-6
alpha = math.radians(theta_deg) / 2.0
Lam = wl_mm / (2.0 * math.sin(alpha))                     # carrier spacing (mm)
nx = 1024
dx = Lam / 10.0
x = (np.arange(nx) - nx // 2) * dx
H = 1.0 + vis * np.cos(2.0 * np.pi * x / Lam)             # recorded hologram intensity

fig, ax = plt.subplots(1, 4, figsize=(17.2, 3.9))
fig.patch.set_facecolor(BG)
fig.suptitle("Phenomenon emergence -- detect_phenomena FLAGS the condition, produce_phenomenon PRODUCES it",
             color=FG, fontsize=13.5, fontweight="bold", y=0.99)

# (a) hologram carrier interferogram (2D)
carrier2d = np.tile(H, (110, 1))
ax[0].imshow(carrier2d[:, nx // 2 - 120:nx // 2 + 120], cmap="gray", aspect="auto", origin="lower")
ax[0].set_title("(a) off-axis hologram: carrier interferogram", color=TX, fontsize=11)
ax[0].set_xlabel("x  (Lambda = lambda/(2 sin(theta/2)) = %.3f um)" % (Lam * 1000.0), color=TX, fontsize=9.5)
ax[0].set_yticks([])

# (b) reconstruction: FFT carrier peak -> recovered crossing angle
F = np.abs(np.fft.rfft(H - H.mean())); fr = np.fft.rfftfreq(nx, d=dx)
i = int(np.argmax(F[1:])) + 1
a, b, c = F[i - 1], F[i], F[i + 1]
off = 0.5 * (a - c) / (a - 2 * b + c)
fpk = fr[i] + off * (fr[1] - fr[0])
theta_rec = math.degrees(2.0 * math.asin(min(1.0, fpk * wl_mm / 2.0)))
ax[1].plot(fr, F / F.max(), color=AC, lw=1.3)
ax[1].axvline(1.0 / Lam, color=GR, lw=0.9, ls="--")
ax[1].annotate("carrier peak\n-> object angle\n%.2f deg (in %.0f)" % (theta_rec, theta_deg),
               xy=(1.0 / Lam, 1.0), xytext=(1.0 / Lam * 0.30, 0.65), color=TX, fontsize=8.4,
               arrowprops=dict(color=MU, arrowstyle="->", lw=0.8))
ax[1].set_xlim(0, 1.0 / Lam * 1.8)
ax[1].set_title("(b) reconstruction: hologram FFT", color=TX, fontsize=11)
ax[1].set_xlabel("spatial frequency (cycles/mm)", color=TX, fontsize=9.5)
ax[1].set_ylabel("|FFT| (norm)", color=TX, fontsize=9.5)

# (c) two-beam interference fringe curve
phi = np.linspace(-2 * np.pi, 2 * np.pi, 512)
for v, col, lab in ((1.0, AC, "V=1.0 (equal)"), (0.5, "#b06a4a", "V=0.5 (4.7:1)")):
    ax[2].plot(phi / np.pi, 1.0 + v * np.cos(phi), color=col, lw=1.5, label=lab)
ax[2].set_title("(c) two-beam interference: I(OPD)", color=TX, fontsize=11)
ax[2].set_xlabel("optical path difference  (lambda)", color=TX, fontsize=9.5)
ax[2].set_ylabel("I (norm)", color=TX, fontsize=9.5)
ax[2].legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.2, loc="upper right")

# (d) Fabry-Perot Airy resonance T(lambda) -- from a CAVITY element
R, L = 0.9, 10.0
fsr = P.cavity_fsr_nm(wl_nm, L, 1.0)
wls = wl_nm + np.linspace(-1.5 * fsr, 1.5 * fsr, 2000)
Tfp = np.array([P.airy_transmission(float(w), L, R) for w in wls])
ax[3].plot(wls - wl_nm, Tfp, color=AC, lw=1.0)
ax[3].set_title("(d) Fabry-Perot: Airy transmission T(lambda)", color=TX, fontsize=11)
ax[3].set_xlabel("detuning (nm)  -- FSR=%.4f nm" % fsr, color=TX, fontsize=9.5)
ax[3].set_ylabel("T", color=TX, fontsize=9.5)
ax[3].annotate("finesse %.1f\ncontrast %.0f" % (P.cavity_finesse(R), ((1 + R) / (1 - R)) ** 2),
               xy=(0.04, 0.74), xycoords="axes fraction", color=TX, fontsize=8.4)

for a_ in ax:
    a_.set_facecolor(BG); a_.tick_params(colors=MU, labelsize=8)
    for s in a_.spines.values():
        s.set_color(GR)
fig.text(0.5, 0.015, "Advisory + intent-judged: produce_phenomenon(accept=False) is a dry-run with an intent "
                     "caveat; accept=True emerges the pattern. Off-trace; live trace byte-identical.",
         color=MU, fontsize=8.0, ha="center")
fig.tight_layout(rect=(0, 0.05, 1, 0.95))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/phenomenon-emergence-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
