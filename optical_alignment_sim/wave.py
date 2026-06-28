"""wave.py -- opt-in Fourier-optics layer: a pupil wavefront -> the real diffraction PSF / MTF / Strehl.

This is the ONE field-propagation step the geometric + Gaussian engine deliberately lacks:
PSF = |FFT(pupil field)|^2 (Goodman, focal-plane / Fraunhofer diffraction). It does NOT touch the live
ray tracer -- it is an on-demand analysis (like the zonal render) that consumes a circular-aperture
wavefront W(x,y) [in WAVES] -- ideal (W=0), a Zernike spec, or a supplied map -- and returns the
diffraction metrics. Needs numpy (Blender ships it); matplotlib is used only for the optional PNG.

Every relation here is physics_verify ok=true: Airy radius 1.22*lambda*F# (= 1.22*lambda/NA), MTF cutoff
1/(lambda*F#), Marechal Strehl exp(-(2*pi*sigma)^2). The PSF=|FFT(circular pupil)|^2 -> Airy with its
first dark ring at 1.22*lambda*F# is demonstrated numerically in tests/test_validation.py.
"""
from __future__ import annotations

import math

import numpy as np

NM_TO_MM = 1.0e-6


def aperture_mask(n_grid, diam_px):
    """Boolean circular aperture of diameter diam_px, centred on an n_grid x n_grid grid."""
    y, x = np.ogrid[-n_grid // 2:n_grid // 2, -n_grid // 2:n_grid // 2]
    return (x * x + y * y) <= (0.5 * diam_px) ** 2


def zernike_defocus(n_grid, diam_px):
    """Noll Z4 defocus sqrt(3)*(2*rho^2-1) over the aperture (rho in [0,1]; RMS=1 over the disk); 0 outside."""
    y, x = np.ogrid[-n_grid // 2:n_grid // 2, -n_grid // 2:n_grid // 2]
    rho2 = (x * x + y * y) / (0.5 * diam_px) ** 2
    return np.where(rho2 <= 1.0, math.sqrt(3.0) * (2.0 * rho2 - 1.0), 0.0)


def _psf(field):
    """|FFT(field)|^2, fft-shifted so the core sits at the grid centre."""
    return np.abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(field)))) ** 2


def _first_dark_ring_px(psf_norm, c):
    """First radial minimum (first dark ring) along +x from the centre, in pixels (or None)."""
    line = psf_norm[c, c:c + psf_norm.shape[1] // 2]
    for i in range(1, len(line) - 1):
        if line[i] < line[i - 1] and line[i] < line[i + 1] and line[i] < 0.02:
            return i
    return None


def _fwhm_px(psf_norm, c):
    """FWHM of the central core along +x, in pixels (linear-interpolated half-max crossing)."""
    line = psf_norm[c, c:]
    for i in range(1, len(line)):
        if line[i] <= 0.5:
            f = (line[i - 1] - 0.5) / (line[i - 1] - line[i]) if line[i - 1] != line[i] else 0.0
            return 2.0 * (i - 1 + f)
    return None


def psf_metrics(wavelength_nm, f_number, aperture_diam_mm, W=None, n_grid=512, diam_px=128, png_path=None):
    """Diffraction PSF of a circular aperture (optionally aberrated by wavefront W in WAVES) + its metrics.

    PSF = |FFT(aperture * exp(i*2*pi*W))|^2. Pure analysis -- no scene mutation. Returns
    {ok, strehl, rms_wavefront_waves, airy_radius_um, first_zero_um, fwhm_um, mtf_cutoff_cyc_per_mm,
    encircled_energy_airy, focal_px_um, n_grid, diam_px}. If png_path is given, also saves a log-scaled
    PSF image (matplotlib; skipped gracefully if unavailable)."""
    mask = aperture_mask(n_grid, diam_px)
    W = np.zeros((n_grid, n_grid)) if W is None else np.asarray(W, dtype=float)
    psf = _psf(mask * np.exp(2j * math.pi * W))
    psf0 = _psf(mask.astype(complex))                 # ideal (unaberrated) reference
    strehl = float(psf.max() / psf0.max()) if psf0.max() > 0 else 0.0
    psfn = psf / psf.max() if psf.max() > 0 else psf
    c = n_grid // 2

    lam_mm = wavelength_nm * NM_TO_MM
    focal_px_mm = lam_mm * f_number * diam_px / n_grid       # focal-plane sampling
    airy_radius_mm = 1.22 * lam_mm * f_number                # 1.22 * lambda * F#
    fz_px = _first_dark_ring_px(psfn, c)
    fwhm_px = _fwhm_px(psfn, c)

    wm = W[mask]
    rms = float(np.sqrt(np.mean((wm - wm.mean()) ** 2))) if wm.size else 0.0
    yy, xx = np.ogrid[-n_grid // 2:n_grid // 2, -n_grid // 2:n_grid // 2]
    r_airy_px = 1.22 * n_grid / diam_px
    tot = psf.sum()
    ee = float(psf[(xx * xx + yy * yy) <= r_airy_px ** 2].sum() / tot) if tot > 0 else 0.0

    out = {
        "ok": True,
        "strehl": round(strehl, 4),
        "rms_wavefront_waves": round(rms, 4),
        "airy_radius_um": round(airy_radius_mm * 1.0e3, 4),
        "first_zero_um": round(fz_px * focal_px_mm * 1.0e3, 4) if fz_px else None,
        "fwhm_um": round(fwhm_px * focal_px_mm * 1.0e3, 4) if fwhm_px else None,
        "mtf_cutoff_cyc_per_mm": round(1.0 / (lam_mm * f_number), 2),
        "encircled_energy_airy": round(ee, 4),
        "focal_px_um": round(focal_px_mm * 1.0e3, 5),
        "n_grid": n_grid, "diam_px": diam_px,
    }
    if png_path:
        try:
            _render_psf(psfn, out, png_path)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def _render_psf(psf_norm, meta, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = psf_norm.shape[0]
    c = n // 2
    half = max(10, int(3.0 * 1.22 * meta["n_grid"] / meta["diam_px"]))
    crop = psf_norm[c - half:c + half, c - half:c + half]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.imshow(np.log10(crop + 1.0e-6), cmap="inferno", interpolation="nearest")
    ax.set_title("PSF  Strehl=%.3f   Airy=%.2f um   EE=%.0f%%"
                 % (meta["strehl"], meta["airy_radius_um"], 100.0 * meta["encircled_energy_airy"]))
    ax.set_xticks([])
    ax.set_yticks([])
    fig.savefig(png_path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
    plt.close(fig)


# Noll-indexed (n, m) for j=1..15 so the aberrated-PSF builder is self-contained (matches physics._NOLL).
_NOLL = {1: (0, 0), 2: (1, 1), 3: (1, -1), 4: (2, 0), 5: (2, -2), 6: (2, 2), 7: (3, -1), 8: (3, 1),
         9: (3, -3), 10: (3, 3), 11: (4, 0), 12: (4, 2), 13: (4, -2), 14: (4, 4), 15: (4, -4)}


def _zern_radial_np(n, m, rho):
    """Radial Zernike polynomial R_n^|m|(rho), vectorized over a numpy array."""
    m = abs(m)
    s = np.zeros_like(rho)
    for k in range((n - m) // 2 + 1):
        num = ((-1) ** k) * math.factorial(n - k)
        den = math.factorial(k) * math.factorial((n + m) // 2 - k) * math.factorial((n - m) // 2 - k)
        s = s + (num / den) * rho ** (n - 2 * k)
    return s


def zernike_wavefront(coeffs, n_grid, diam_px):
    """Wavefront W(x,y) = sum_j coeffs[j-1] * Z_j(rho,theta) over the unit-disk aperture (diameter diam_px,
    centred in n_grid), in WAVES; 0 outside. Noll-indexed, RMS-normalized Zernikes, so the RMS over the disk is
    sqrt(sum of squares of the coeffs excluding piston). The general (any-mode) form of zernike_defocus."""
    y, x = np.ogrid[-n_grid // 2:n_grid // 2, -n_grid // 2:n_grid // 2]
    r = np.sqrt(x * x + y * y) / (0.5 * diam_px)
    th = np.arctan2(y, x)
    W = np.zeros((n_grid, n_grid))
    for j, c in enumerate(coeffs, start=1):
        if abs(c) < 1e-12 or j not in _NOLL:
            continue
        n, m = _NOLL[j]
        norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2.0 * (n + 1))
        ang = np.cos(m * th) if m >= 0 else np.sin(-m * th)
        W = W + c * norm * _zern_radial_np(n, m, r) * ang
    return np.where(r <= 1.0, W, 0.0)


def aberrated_psf(coeffs, wavelength_nm, f_number, aperture_diam_mm, n_grid=512, diam_px=128, png_path=None):
    """Diffraction PSF of a circular aperture aberrated by a Zernike wavefront ``coeffs`` (Noll-indexed, WAVES)
    + its metrics -- the general (any-mode) form of wave_psf's single defocus. Builds W = sum_j coeffs[j-1]*Z_j
    and runs psf_metrics. For a SMALL aberration the Strehl follows the Marechal approximation exp(-(2 pi sigma)^2)
    with sigma = the RMS wavefront error (waves). Returns psf_metrics' {strehl, rms_wavefront_waves, ...}."""
    W = zernike_wavefront(coeffs, n_grid, diam_px)
    return psf_metrics(wavelength_nm, f_number, aperture_diam_mm, W=W, n_grid=n_grid, diam_px=diam_px, png_path=png_path)
