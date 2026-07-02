"""speckle.py -- opt-in off-trace producer: fully-developed laser speckle from a diffuse scatterer.

When a COHERENT beam illuminates a rough surface (height variations >> lambda), every illuminated point
re-radiates with a uniform random phase in [-pi, pi]. The fields from all points sum at an observation
plane with random relative phases, and by the central-limit theorem the resulting complex amplitude is a
circular Gaussian -- so the intensity I = |U|^2 obeys the negative-exponential law and the grainy pattern
called SPECKLE emerges. This module produces it from first principles (a random-phase circular diffuser
propagated by field.angular_spectrum) and reports its textbook statistics.

Like field.py / wave.py / turbulence.py this is on-demand analysis: it NEVER touches the live ray tracer,
so the trace stays byte-identical. Needs numpy (Blender ships it); matplotlib is used only for the PNG.

Physics (statistics physics_verify ok=true; Goodman, *Speckle Phenomena in Optics*, 2007):
  intensity PDF        P(I) = (1/<I>) exp(-I/<I>)            (negative exponential; mean=<I>, var=<I>^2)
  contrast             C = sigma_I / <I> = 1                  (fully-developed speckle)   [verified]
  P(I > <I>)           = exp(-1) = 0.368                      (survival at the mean)
  N-frame averaging    C_N = 1/sqrt(N)                        (N independent speckle patterns)  [verified]
  mean speckle size    d ~ lambda z / D                       (illuminated-diffuser diameter D, distance z;
                                                               van Cittert-Zernike -- the speckle correlation
                                                               width is the diffraction spot of the aperture)
The contrast = 1 and C_N = 1/sqrt(N) relations are oracle-verified from the exponential-PDF moments
(E[I]=<I>, E[I^2]=2<I>^2 -> sigma/<I>=1; the average of N i.i.d. exponentials has var <I>^2/N). The
exponential PDF, the e^-1 survival, and the lambda z/D size law are confirmed numerically in _selftest().
"""
from __future__ import annotations

import math

import numpy as np

try:                                    # package import; falls back to a bare script run for the self-test
    from . import field
except ImportError:                     # pragma: no cover - only when run as `python3 .../speckle.py`
    import field

NM_TO_MM = 1.0e-6


def speckle_field(n_grid=512, dx_mm=0.02, diam_mm=1.0, dz_mm=300.0, wavelength_nm=632.8, seed=0):
    """The complex field at the observation plane: a circular diffuser of diameter `diam_mm` carrying a
    uniform random phase in [-pi, pi], propagated `dz_mm` by the angular-spectrum method. Deterministic in
    `seed` (numpy default_rng, platform-stable)."""
    rng = np.random.default_rng(int(seed))
    ap = field.circular_aperture(n_grid, dx_mm, diam_mm)
    phase = rng.uniform(-math.pi, math.pi, (n_grid, n_grid))
    return field.angular_spectrum(ap * np.exp(1j * phase), dx_mm, dz_mm, wavelength_nm)


def speckle_intensity(n_grid=512, dx_mm=0.02, diam_mm=1.0, dz_mm=300.0, wavelength_nm=632.8, seed=0):
    """|speckle_field|^2 -- the observable speckle intensity pattern."""
    U = speckle_field(n_grid, dx_mm, diam_mm, dz_mm, wavelength_nm, seed)
    return np.abs(U) ** 2


def _central(A, frac):
    n = A.shape[0]
    h = max(1, int(n * frac / 2))
    c = n // 2
    return A[c - h:c + h, c - h:c + h]


def speckle_contrast(I, frac=0.5):
    """Speckle contrast C = sigma_I / <I> over the central `frac` window (where the diffracted envelope is
    flat). C -> 1 for fully-developed speckle."""
    w = _central(np.asarray(I, dtype=float), frac)
    m = float(w.mean())
    return float(w.std() / m) if m > 0.0 else 0.0


def speckle_size_mm(I, dx_mm, frac=0.5):
    """Mean speckle size: the half-width-at-half-max of the intensity-fluctuation autocorrelation over the
    central window, i.e. its full width at half max (a horizontal cut). Returns (size_mm, size_px)."""
    w = _central(np.asarray(I, dtype=float), frac)
    w = w - w.mean()
    F = np.fft.fft2(w)
    ac = np.fft.fftshift(np.abs(np.fft.ifft2(F * np.conj(F))).real)
    pk = ac.max()
    if pk <= 0.0:
        return 0.0, 0.0
    ac /= pk
    n = ac.shape[0]
    cy = n // 2
    row = ac[cy, :]
    half = float(cy)
    for i in range(cy + 1, n):
        if row[i] < 0.5:                                # linear interp to the 0.5 crossing
            half = (i - 1) + (0.5 - row[i - 1]) / (row[i] - row[i - 1]) if row[i] != row[i - 1] else float(i)
            break
    fwhm_px = 2.0 * (half - cy)
    return fwhm_px * dx_mm, fwhm_px


def speckle_metrics(n_grid=512, dx_mm=0.02, diam_mm=1.0, dz_mm=300.0, wavelength_nm=632.8,
                    seed=0, n_avg=1, frac=0.5, png_path=None):
    """Produce a speckle pattern (averaging `n_avg` independent frames) and report its statistics against
    the verified textbook laws. Returns (metrics, intensity_raster)."""
    n_avg = max(1, int(n_avg))
    acc = None
    for k in range(n_avg):
        Ik = speckle_intensity(n_grid, dx_mm, diam_mm, dz_mm, wavelength_nm, int(seed) + k)
        acc = Ik if acc is None else acc + Ik
    I = acc / n_avg
    w = _central(I, frac)
    mu = float(w.mean())
    C = speckle_contrast(I, frac)
    size_mm, size_px = speckle_size_mm(I, dx_mm, frac)
    pred_size = wavelength_nm * NM_TO_MM * dz_mm / diam_mm
    metrics = {
        "contrast": round(C, 4),
        "predicted_contrast": round(1.0 / math.sqrt(n_avg), 4),
        "var_over_mean2": round(float(w.var() / (mu * mu)) if mu > 0 else 0.0, 4),
        "frac_above_mean": round(float(np.mean(w > mu)), 4),
        "speckle_size_mm": round(size_mm, 5),
        "predicted_speckle_size_mm": round(pred_size, 5),
        "n_avg": n_avg,
        "mean_intensity": float(mu),
        "oracle": ("fully-developed speckle: contrast sigma_I/<I>=1 (negative-exponential PDF "
                   "P(I)=exp(-I/<I>)/<I> -> P(I><I>)=e^-1=0.368); N-frame average C_N=1/sqrt(N); mean "
                   "speckle size ~ lambda*z/D. physics_verify ok=true (contrast + N-averaging)."),
    }
    if png_path:
        metrics_png = _render_speckle(I, dx_mm, metrics, png_path)
        if metrics_png:
            metrics["png"] = metrics_png
    return metrics, I


def _render_speckle(I, dx_mm, metrics, png_path):
    """A 2-panel figure: the speckle pattern + its intensity histogram against the exponential PDF."""
    try:
        try:
            from . import plotting as _plotting
        except ImportError:
            import plotting as _plotting
        plt = _plotting.pyplot()
        if plt is None:
            raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
    except Exception:
        return None
    w = _central(I, 0.5)
    mu = float(w.mean()) or 1.0
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(11.0, 5.2))
    fig.patch.set_facecolor("#0d0f12")
    for ax in (ax0, ax1):
        ax.set_facecolor("#0d0f12")
    ax0.imshow(w, cmap="inferno", origin="lower", interpolation="nearest")
    ax0.set_xticks([]); ax0.set_yticks([])
    ax0.set_title("Fully-developed speckle", color="#e8e8ea", fontsize=12)
    ax0.set_xlabel("contrast C = %.3f  (theory 1.0 for N=%d)" % (metrics["contrast"], metrics["n_avg"]),
                   color="#9aa0a6", fontsize=9)
    flat = (w / mu).ravel()
    ax1.hist(flat, bins=60, range=(0, 6), density=True, color="#5b8def", alpha=0.8, label="speckle histogram")
    x = np.linspace(0, 6, 200)
    ax1.plot(x, np.exp(-x), color="#ff7a59", lw=2.0, label=r"$P(I)=e^{-I/\langle I\rangle}/\langle I\rangle$")
    ax1.set_xlabel(r"$I/\langle I\rangle$", color="#9aa0a6", fontsize=10)
    ax1.set_ylabel("probability density", color="#9aa0a6", fontsize=9)
    ax1.set_title("Negative-exponential intensity PDF", color="#e8e8ea", fontsize=12)
    ax1.tick_params(colors="#9aa0a6", labelsize=8)
    for s in ax1.spines.values():
        s.set_color("#2a2e35")
    leg = ax1.legend(facecolor="#15181d", edgecolor="#2a2e35", labelcolor="#cfd3d8", fontsize=9)
    fig.suptitle("Laser speckle  —  speckle size %.4f mm vs λz/D %.4f mm"
                 % (metrics["speckle_size_mm"], metrics["predicted_speckle_size_mm"]),
                 color="#e8e8ea", fontsize=13, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(png_path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return png_path


def _selftest():
    """Confirm the textbook speckle statistics numerically (the integral-based facts the oracle cannot do
    symbolically). Raises AssertionError on any deviation."""
    fails = []
    wl = 632.8
    # 1. single-frame contrast ~ 1 + exponential-PDF moments (var = mean^2) + survival e^-1
    m, I = speckle_metrics(512, 0.02, 1.0, 300.0, wl, seed=1, n_avg=1)
    if not (0.9 <= m["contrast"] <= 1.1):
        fails.append("contrast %.3f not ~1" % m["contrast"])
    if not (0.9 <= m["var_over_mean2"] <= 1.1):
        fails.append("var/mean^2 %.3f not ~1 (exponential PDF)" % m["var_over_mean2"])
    if not (0.33 <= m["frac_above_mean"] <= 0.40):
        fails.append("P(I>mean) %.3f not ~e^-1=0.368" % m["frac_above_mean"])
    # 2. speckle size ~ lambda z / D (within 15%)
    if not (0.85 <= m["speckle_size_mm"] / m["predicted_speckle_size_mm"] <= 1.15):
        fails.append("speckle size %.4f vs lam z/D %.4f off >15%%"
                     % (m["speckle_size_mm"], m["predicted_speckle_size_mm"]))
    # 3. size scaling: doubling z doubles the size; doubling D halves it
    mz, _ = speckle_metrics(512, 0.02, 1.0, 600.0, wl, seed=1)
    md, _ = speckle_metrics(512, 0.02, 2.0, 300.0, wl, seed=1)
    if not (1.7 <= mz["speckle_size_mm"] / m["speckle_size_mm"] <= 2.3):
        fails.append("size does not scale ~linearly with z")
    if not (0.4 <= md["speckle_size_mm"] / m["speckle_size_mm"] <= 0.6):
        fails.append("size does not scale ~1/D")
    # 4. N-frame averaging suppresses contrast as 1/sqrt(N)
    m16, _ = speckle_metrics(512, 0.02, 1.0, 300.0, wl, seed=100, n_avg=16)
    if not (0.20 <= m16["contrast"] <= 0.31):
        fails.append("N=16 contrast %.3f not ~1/4=0.25" % m16["contrast"])
    if fails:
        raise AssertionError("speckle selftest FAILED: " + "; ".join(fails))
    print("SPECKLE SELFTEST PASSED  (C=%.3f, size %.4f/%.4f mm, var/mean^2=%.3f, P(I>mu)=%.3f, N16 C=%.3f)"
          % (m["contrast"], m["speckle_size_mm"], m["predicted_speckle_size_mm"],
             m["var_over_mean2"], m["frac_above_mean"], m16["contrast"]))


if __name__ == "__main__":
    _selftest()
