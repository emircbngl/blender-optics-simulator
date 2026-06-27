"""field.py -- opt-in sampled-field layer: scalar diffraction propagation between arbitrary planes.

The live engine is lumped (single ray + Gaussian-q ABCD + analytic overlays); wave.py adds the ONE
focal-plane Fraunhofer PSF. This module adds the next field step the engine lacks: free-space
ANGULAR-SPECTRUM propagation of a sampled complex field U(x,y) over a distance dz -- the primitive behind
digital-hologram reconstruction, multi-plane Fresnel, and (as a building block) the beam-propagation method.
It is on-demand analysis like wave.py / zonal_render: it does NOT touch the live ray tracer, so the trace
stays byte-identical. Needs numpy (Blender ships it); matplotlib is used only for the optional PNG.

Physics (all physics_verify ok=true this session):
  transfer function   H(fx,fy;z) = exp(i k z sqrt(1 - (lam fx)^2 - (lam fy)^2))   (Goodman, angular spectrum)
  evanescent (arg<0): real DECAY exp(-k |z| sqrt((lam fx)^2 + (lam fy)^2 - 1))     (the regularizing branch)
  paraxial limit  ->  Fresnel transfer exp(i k z) exp(-i pi lam z (fx^2+fy^2))     (quadratic coeff = pi*lam)
  band-limit (Matsushima & Shimobaba 2009)  f_lim = 1/(lam sqrt((2 z df)^2 + 1)),  df = 1/(N dx)  (anti-alias)
A Gaussian beam propagated by this method reproduces the closed-form w(z) = w0 sqrt(1 + (lam z/(pi w0^2))^2);
+z then -z round-trips back to the input (reversibility). Both are asserted in tests/test_validation.py.
"""
from __future__ import annotations

import math

import numpy as np

NM_TO_MM = 1.0e-6


def gaussian_field(n_grid, dx_mm, w0_mm):
    """Unit-amplitude Gaussian U0 = exp(-r^2/w0^2) (w0 = 1/e^2 intensity radius), centred on the grid."""
    c = n_grid // 2
    x = (np.arange(n_grid) - c) * dx_mm
    X, Y = np.meshgrid(x, x)
    return np.exp(-(X * X + Y * Y) / (w0_mm * w0_mm)).astype(complex)


def circular_aperture(n_grid, dx_mm, diam_mm):
    """Unit-amplitude clear circular aperture of diameter diam_mm, centred on the grid."""
    c = n_grid // 2
    x = (np.arange(n_grid) - c) * dx_mm
    X, Y = np.meshgrid(x, x)
    return ((X * X + Y * Y) <= (0.5 * diam_mm) ** 2).astype(complex)


def angular_spectrum(U0, dx_mm, dz_mm, wavelength_nm, band_limit=True):
    """Propagate the sampled complex field U0 a distance dz_mm by the angular-spectrum method.

    H(fx,fy) = exp(i k dz sqrt(1 - (lam fx)^2 - (lam fy)^2)). Evanescent (arg<0) components DECAY
    (exp(-k|dz| sqrt(-arg)), the physical regularizing branch -- a naive sqrt of a negative would NaN/blow up,
    and on back-propagation the growing branch is ill-posed, so we always decay them). With band_limit
    (Matsushima & Shimobaba 2009) H is rectangularly band-limited to f_lim = 1/(lam sqrt((2 dz df)^2+1)) per
    axis (df = 1/(N dx)) to suppress the aliasing that otherwise corrupts the result at large dz. NaNs in U0
    (e.g. a disc-masked zonal field) are zero-filled before the FFT. Returns the propagated complex field."""
    U0 = np.nan_to_num(np.asarray(U0, dtype=complex), nan=0.0)
    n = U0.shape[0]
    lam = wavelength_nm * NM_TO_MM                       # mm
    f = np.fft.fftfreq(n, d=dx_mm)                       # cyc/mm, fft order
    FX, FY = np.meshgrid(f, f)
    arg = 1.0 - (lam * FX) ** 2 - (lam * FY) ** 2
    k = 2.0 * math.pi / lam
    prop = arg >= 0.0
    H = np.empty(arg.shape, dtype=complex)
    H[prop] = np.exp(1j * k * dz_mm * np.sqrt(arg[prop]))
    H[~prop] = np.exp(-k * abs(dz_mm) * np.sqrt(-arg[~prop]))        # evanescent: decay (regularizing)
    if band_limit:
        df = 1.0 / (n * dx_mm)
        f_lim = 1.0 / (lam * math.sqrt((2.0 * dz_mm * df) ** 2 + 1.0))
        H = H * ((np.abs(FX) <= f_lim) & (np.abs(FY) <= f_lim))
    return np.fft.ifft2(np.fft.fft2(U0) * H)


def field_metrics(U, dx_mm, wavelength_nm=None, png_path=None):
    """Beam metrics of a sampled field: peak, total power, centroid, 2nd-moment 1/e^2 radius, Fresnel number.

    The 1/e^2 radius is the second-moment width w = sqrt(2*(var_x + var_y)) about the centroid (= w for a
    circular Gaussian). Returns {ok, peak, total_power, centroid_x_mm, centroid_y_mm, w_2sigma_mm,
    fresnel_number, n_grid, dx_mm}. Pure analysis -- no scene mutation. png_path saves an intensity image."""
    U = np.asarray(U, dtype=complex)
    n = U.shape[0]
    I = np.abs(U) ** 2
    tot = float(I.sum())
    c = n // 2
    x = (np.arange(n) - c) * dx_mm
    X, Y = np.meshgrid(x, x)
    if tot > 0.0:
        cx = float((I * X).sum() / tot)
        cy = float((I * Y).sum() / tot)
        varx = float((I * (X - cx) ** 2).sum() / tot)
        vary = float((I * (Y - cy) ** 2).sum() / tot)
        w = math.sqrt(2.0 * (varx + vary))              # 1/e^2 radius (= w for a circular Gaussian)
    else:
        cx = cy = w = 0.0
    out = {
        "ok": True,
        "peak": round(float(I.max()), 6),
        "total_power": round(tot, 4),
        "centroid_x_mm": round(cx, 5),
        "centroid_y_mm": round(cy, 5),
        "w_2sigma_mm": round(w, 5),
        "n_grid": n,
        "dx_mm": round(dx_mm, 6),
    }
    if wavelength_nm and w > 0.0:
        lam_mm = wavelength_nm * NM_TO_MM
        out["fresnel_number"] = round(w * w / (lam_mm * max(dx_mm, 1e-9) * n), 4)
    if png_path:
        try:
            _render_field(I, out, png_path)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def _render_field(intensity, meta, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = intensity.shape[0]
    half = n // 2
    span = meta["dx_mm"] * half
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(intensity / (intensity.max() or 1.0), cmap="inferno",
                   extent=[-span, span, -span, span], interpolation="nearest")
    ax.set_title("field |U|^2   w=%.3f mm" % meta["w_2sigma_mm"])
    ax.set_xlabel("mm")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.savefig(png_path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
    plt.close(fig)
