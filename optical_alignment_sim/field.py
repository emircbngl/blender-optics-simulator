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


def slit_aperture(n_grid, dx_mm, width_mm, n_slits=1, sep_mm=0.0):
    """1-D transmission aperture: `n_slits` clear slits of width `width_mm`, centre-to-centre separation
    `sep_mm`, symmetric about the grid centre. n_slits=1 -> single slit; 2 -> Young's double slit; N -> a
    coarse grating. Returns a length-n_grid float array (1 inside a slit, 0 outside)."""
    x = (np.arange(n_grid) - n_grid // 2) * dx_mm
    a = np.zeros(n_grid)
    offsets = (np.arange(n_slits) - (n_slits - 1) / 2.0) * sep_mm
    for o in offsets:
        a[np.abs(x - o) <= 0.5 * width_mm] = 1.0
    return a


def fraunhofer_diffraction(aperture_1d, dx_mm, wavelength_nm):
    """Far-field (Fraunhofer) diffraction pattern of a 1-D aperture: I(theta) = |FT{aperture}|^2, with the
    angle axis sin(theta) = lambda * f (f = spatial frequency). Returns (sin_theta, I_normalised). This is the
    textbook recipe (Goodman; Voelz, Computational Fourier Optics): a single slit -> sinc^2 with its first
    zero at sin(theta) = lambda/a; a double slit -> the same sinc^2 ENVELOPE times cos^2(pi d sin(theta)/lambda),
    fringes spaced lambda/d. Off-trace, pure analysis."""
    a = np.asarray(aperture_1d, dtype=complex)
    n = a.size
    spec = np.fft.fftshift(np.fft.fft(np.fft.ifftshift(a)))
    inten = np.abs(spec) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(n, d=dx_mm))                # cyc/length
    sin_theta = (wavelength_nm * NM_TO_MM) * f
    peak = inten.max()
    return sin_theta, (inten / peak if peak > 0 else inten)


def slit_metrics(width_mm, n_slits=1, sep_mm=0.0, wavelength_nm=632.8, n_grid=4096, dx_mm=None, png_path=None):
    """Simulate single/double/N-slit Fraunhofer diffraction by FFT and validate it against the closed forms.

    Returns {ok, first_min_sin_theta, first_min_theory (=lambda/a), fringe_spacing_sin_theta,
    fringe_spacing_theory (=lambda/d), rms_vs_analytic, ...}: the measured first diffraction minimum matches
    lambda/width, the double-slit fringe spacing matches lambda/sep, and the whole FFT pattern matches the
    analytic sinc^2 (x cos^2) to rms_vs_analytic. Pure analysis; off-trace."""
    lam_mm = wavelength_nm * NM_TO_MM
    if dx_mm is None:
        dx_mm = width_mm / 48.0                                    # ~48 samples across the narrowest slit (edge-sampling bias ~1/48)
    n_grid = int(n_grid)
    ap = slit_aperture(n_grid, dx_mm, width_mm, n_slits=n_slits, sep_mm=sep_mm)
    st, I = fraunhofer_diffraction(ap, dx_mm, wavelength_nm)
    # analytic: sinc^2(pi a sinT/lam) * (sin(N pi d sinT/lam)/(N sin(pi d sinT/lam)))^2  (N-slit grating factor)
    beta = np.pi * width_mm * st / lam_mm
    env = np.where(np.abs(beta) < 1e-9, 1.0, (np.sin(beta) / np.where(beta == 0, 1, beta)) ** 2)
    if n_slits > 1:
        gamma = np.pi * sep_mm * st / lam_mm
        num = np.sin(n_slits * gamma)
        den = n_slits * np.sin(gamma)
        grating = np.where(np.abs(np.sin(gamma)) < 1e-9, 1.0, (num / np.where(den == 0, 1, den)) ** 2)
        analytic = env * grating
    else:
        analytic = env
    rms = float(np.sqrt(np.mean((I - analytic) ** 2)))
    c = n_grid // 2
    pos, Ipos = st[c:], I[c:]
    out = {
        "ok": True,
        "width_mm": width_mm, "n_slits": int(n_slits), "sep_mm": sep_mm, "wavelength_nm": wavelength_nm,
        "rms_vs_analytic": round(rms, 5),
        "n_grid": n_grid, "dx_mm": round(dx_mm, 6),
    }
    if n_slits == 1:
        # first DIFFRACTION minimum at sin(theta)=lambda/a -- the deepest dip in (0, 1.6*lambda/a]
        w = np.where((pos > 0) & (pos <= 1.6 * lam_mm / width_mm))[0]
        out["first_min_sin_theta"] = round(float(pos[w[np.argmin(Ipos[w])]]), 7) if w.size else None
        out["first_min_theory"] = round(lam_mm / width_mm, 7)                       # lambda / slit-width
    else:
        out["fringe_spacing_theory"] = round(lam_mm / sep_mm, 7)                    # lambda / slit-separation (grating eqn)
        out["envelope_first_min_theory"] = round(lam_mm / width_mm, 7)
        # measured principal-maximum (order) spacing: the first interference peak after the centre
        pk = [c + i for i in range(2, len(Ipos) - 1)
              if Ipos[i] > Ipos[i - 1] and Ipos[i] > Ipos[i + 1] and Ipos[i] > 0.25]
        if pk:
            out["fringe_spacing_sin_theta"] = round(float(abs(st[pk[0]] - st[c])), 7)
    if png_path:
        try:
            _render_slit(st, I, analytic, out, png_path)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def _render_slit(sin_theta, I, analytic, meta, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lim = 6.0 * (meta["first_min_theory"] or 0.01)
    m = np.abs(sin_theta) <= lim
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(sin_theta[m] * 1e3, analytic[m], "--", color="#888", lw=1.3, label="analytic sinc²(·cos²)")
    ax.plot(sin_theta[m] * 1e3, I[m], color="#4ea3ff", lw=1.6, label="FFT simulation")
    title = "%d-slit Fraunhofer  width=%g mm" % (meta["n_slits"], meta["width_mm"])
    if meta["n_slits"] > 1:
        title += ", sep=%g mm" % meta["sep_mm"]
    ax.set_title("%s   (rms vs analytic = %.1e)" % (title, meta["rms_vs_analytic"]))
    ax.set_xlabel("sin θ  (×10⁻³)")
    ax.set_ylabel("normalised intensity")
    ax.legend(fontsize=8)
    fig.savefig(png_path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
    plt.close(fig)


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
