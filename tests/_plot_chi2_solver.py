"""Generate docs/img/chi2-solver-demo.png -- the chi(2) tensor solver (Manley-Rowe coupled-wave ODE).

Three panels:
  (a) SHG conversion efficiency vs pump power: the depleted ODE eta vs the UNDEPLETED line (deff^2 L^2 P), which
      runs away past 1 -- the ODE saturates at full conversion (tanh^2(sqrt(eta_lin))).
  (b) Manley-Rowe energy: pump-residual (1-eta) + harmonic (eta) = the input at every drive (photon number
      conserved: one 2w photon per two w photons).
  (c) phase-mismatch tuning: the DEPLETED tuning curve (strong drive) vs the bare undepleted sinc^2(dkL/2) --
      depletion broadens + flattens the central peak.
Run:  python3 tests/_plot_chi2_solver.py
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

BG, FG, TX, MU, GR, AC, AC2 = "#0d0d10", "#f4f4f6", "#e8e8ea", "#8a8a92", "#33343a", "#4a8db0", "#c0653a"
DEFF, L = 2.0, 10.0          # BBO-like deff (pm/V), 10 mm

fig, ax = plt.subplots(1, 3, figsize=(15.2, 4.3))
fig.patch.set_facecolor(BG)
fig.suptitle("chi(2) tensor solver -- SHG from the full Manley-Rowe coupled-wave ODE (pump depletion + phase mismatch)",
             color=FG, fontsize=12.5, fontweight="bold", y=0.98)

# (a) conversion vs pump power: depleted ODE vs undepleted runaway
pump = np.linspace(0.0, 250.0, 120)
eta = np.array([P.chi2_solve(DEFF, L, float(p), 0.0) for p in pump])
eta_lin = 2.0e-4 * DEFF ** 2 * L ** 2 * pump          # the undepleted (deff^2 L^2 P) line
ax[0].plot(pump, eta, color=AC, lw=2.0, label="depleted ODE (tanh$^2\\!\\sqrt{\\eta_{lin}}$)")
ax[0].plot(pump, np.clip(eta_lin, 0, 1.3), color=AC2, lw=1.4, ls="--", label="undepleted ($\\propto$P, runs past 1)")
ax[0].axhline(1.0, color=MU, lw=0.8, ls=":")
ax[0].set_xlabel("pump power (W)", color=MU, fontsize=9)
ax[0].set_ylabel("SHG efficiency $\\eta$", color=MU, fontsize=9)
ax[0].set_title("(a) conversion saturates with depletion", color=TX, fontsize=10.5)
ax[0].set_ylim(0, 1.25)

# (b) Manley-Rowe energy conservation
ax[1].fill_between(pump, 0, eta, color=AC, alpha=0.55, label="harmonic 2$\\omega$ ($\\eta$)")
ax[1].fill_between(pump, eta, 1.0, color=AC2, alpha=0.45, label="pump residual $\\omega$ (1-$\\eta$)")
ax[1].plot(pump, np.ones_like(pump), color=FG, lw=1.4, label="total (conserved = 1)")
ax[1].set_xlabel("pump power (W)", color=MU, fontsize=9)
ax[1].set_ylabel("power fraction", color=MU, fontsize=9)
ax[1].set_title("(b) Manley-Rowe: pump + harmonic = input", color=TX, fontsize=10.5)
ax[1].set_ylim(0, 1.08)

# (c) phase-mismatch tuning curve: depleted (strong drive) vs bare sinc^2
dkL = np.linspace(-3 * math.pi, 3 * math.pi, 240)
# strong drive: eta_lin ~ 4 on resonance
eta_strong = np.array([P.chi2_shg_efficiency(4.0, float(x)) for x in dkL])
sinc2 = np.where(np.abs(dkL) < 1e-9, 1.0, (np.sin(dkL / 2) / (dkL / 2)) ** 2)
ax[2].plot(dkL / math.pi, eta_strong / eta_strong.max(), color=AC, lw=2.0, label="depleted (strong drive)")
ax[2].plot(dkL / math.pi, sinc2, color=AC2, lw=1.4, ls="--", label="undepleted sinc$^2$(dkL/2)")
ax[2].set_xlabel("phase mismatch $\\Delta k L / \\pi$", color=MU, fontsize=9)
ax[2].set_ylabel("normalized $\\eta$", color=MU, fontsize=9)
ax[2].set_title("(c) phase-mismatch tuning curve", color=TX, fontsize=10.5)

for a_ in ax:
    a_.set_facecolor(BG)
    a_.tick_params(colors=MU, labelsize=8)
    for s in a_.spines.values():
        s.set_color(GR)
    a_.grid(True, color=GR, lw=0.4, alpha=0.4)
    leg = a_.legend(facecolor=BG, edgecolor=GR, labelcolor=TX, fontsize=8.0)

fig.text(0.5, 0.015, "The coupled-wave ODE da2/ds = i a1^2 e^{+i*delta*s}, da1/ds = i a1* a2 e^{-i*delta*s} is RK4-integrated: it "
                     "reproduces tanh^2(sqrt(eta_lin)) at phase match and eta_lin*sinc^2 undepleted, conserving photon number. "
                     "Opt-in; live trace byte-identical.",
         color=MU, fontsize=7.6, ha="center")
fig.tight_layout(rect=(0, 0.045, 1, 0.93))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/img/chi2-solver-demo.png")
fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print("wrote", out)
