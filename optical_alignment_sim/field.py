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


def talbot_grating(n_grid, dx_mm, period_mm, duty=0.5):
    """1-D Ronchi amplitude grating: period_mm, `duty` clear fraction, uniform in y, on an n_grid x n_grid
    complex array (1 in the clear bars, 0 in the opaque bars)."""
    x = np.arange(n_grid) * dx_mm
    row = (np.mod(x, period_mm) < duty * period_mm).astype(float)
    return np.tile(row, (n_grid, 1)).astype(complex)


def talbot_metrics(period_mm, wavelength_nm, n_periods=16, n_grid=512, png_path=None):
    """Talbot self-imaging: propagate a periodic grating by the angular spectrum and confirm it reproduces
    itself at the Talbot distance z_T = 2*period^2/lambda (with a HALF-PERIOD-SHIFTED copy at z_T/2, and no
    image at z_T/4). The grid spans an integer number of periods so the FFT periodicity matches the grating.
    Returns {talbot_distance_mm, self_image_corr (~1 at z_T), half_talbot_shift_corr (~1 at z_T/2 vs a d/2
    shift), quarter_corr (~0 at z_T/4)} -- the self-image is the proof that z_T = 2 d^2/lambda. Off-trace."""
    lam_mm = wavelength_nm * NM_TO_MM
    z_t = 2.0 * period_mm ** 2 / lam_mm
    n = int(n_grid)
    dx_mm = period_mm * n_periods / n                          # integer periods -> exact FFT periodicity
    U0 = talbot_grating(n, dx_mm, period_mm)
    row0 = np.abs(U0[n // 2]) ** 2
    shift = int(round(0.5 * period_mm / dx_mm))

    def _corr(a, b):
        a = a - a.mean(); b = b - b.mean()
        den = math.sqrt(float(np.sum(a * a) * np.sum(b * b)))
        return float(np.sum(a * b) / den) if den > 0 else 0.0

    def _row(frac):
        u = angular_spectrum(U0, dx_mm, frac * z_t, wavelength_nm, band_limit=False)
        return np.abs(u[n // 2]) ** 2

    out = {
        "ok": True,
        "period_mm": period_mm, "wavelength_nm": wavelength_nm,
        "talbot_distance_mm": round(z_t, 4),
        "self_image_corr": round(_corr(_row(1.0), row0), 4),                 # z_T  -> ~1 (self-image)
        "half_talbot_shift_corr": round(_corr(_row(0.5), np.roll(row0, shift)), 4),  # z_T/2 -> ~1 vs d/2 shift
        "quarter_corr": round(_corr(_row(0.25), row0), 4),                   # z_T/4 -> ~0 (sub-image)
        "n_periods": int(n_periods), "n_grid": n,
    }
    if png_path:
        try:
            _render_talbot(U0, dx_mm, z_t, period_mm, wavelength_nm, n, out, png_path)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def _render_talbot(U0, dx_mm, z_t, period_mm, wavelength_nm, n, meta, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    nz = 240
    zz = np.linspace(0.0, 2.0 * z_t, nz)
    carpet = np.empty((nz, n))
    for i, z in enumerate(zz):
        u = U0 if z == 0 else angular_spectrum(U0, dx_mm, z, wavelength_nm, band_limit=False)
        carpet[i] = np.abs(u[n // 2]) ** 2
    xspan = 0.5 * n * dx_mm
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    ax.imshow(carpet, cmap="inferno", aspect="auto", origin="lower",
              extent=[-xspan, xspan, 0, 2.0 * z_t])
    for k in (0.5, 1.0, 1.5, 2.0):
        ax.axhline(k * z_t, color="#5cc0ff", lw=0.7, ls=":")
    ax.set_xlim(-5 * period_mm, 5 * period_mm)
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("propagation z [mm]")
    ax.set_title("Talbot carpet  d=%g mm  z_T=%.1f mm  (self-image corr %.2f)"
                 % (period_mm, z_t, meta["self_image_corr"]), color="#e0e0e0", fontsize=10)
    fig.savefig(png_path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
    plt.close(fig)


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


def _lens_phase(n_grid, dx_mm, focal_mm, wavelength_nm):
    """Thin-lens quadratic phase mask exp(-i pi r^2 / (lambda f)) (converging for f>0)."""
    c = n_grid // 2
    x = (np.arange(n_grid) - c) * dx_mm
    X, Y = np.meshgrid(x, x)
    lam_mm = wavelength_nm * NM_TO_MM
    return np.exp(-1j * np.pi * (X * X + Y * Y) / (lam_mm * focal_mm))


def _run_chain(steps, wavelength_nm, w0_mm, aperture_mm, n_grid, dx_mm, band_limit):
    """Core multi-plane marcher -> (U_final, dx_mm, z_total, trace). Returns the raw field (for field-level
    checks like propagator additivity); propagate_chain() wraps it into JSON-able metrics."""
    src_extent = max(w0_mm or 0.0, (aperture_mm or 0.0) * 0.5) or 1.0
    if dx_mm is None:
        dx_mm = 2.5 * src_extent * 2.0 / n_grid              # span ~2.5x the source diameter
    if w0_mm:
        U = gaussian_field(n_grid, dx_mm, w0_mm)
    elif aperture_mm:
        U = circular_aperture(n_grid, dx_mm, aperture_mm).astype(complex)
    else:
        U = np.ones((n_grid, n_grid), dtype=complex)
    z, trace = 0.0, []
    for (kind, val) in steps:
        k = str(kind).lower()
        if k in ("prop", "propagate", "p"):
            U = angular_spectrum(U, dx_mm, float(val), wavelength_nm, band_limit=band_limit); z += float(val)
        elif k in ("aperture", "ap", "a"):
            U = U * circular_aperture(n_grid, dx_mm, float(val))
        elif k in ("lens", "l"):
            U = U * _lens_phase(n_grid, dx_mm, float(val), wavelength_nm)
        else:
            raise ValueError("unknown step kind %r (use prop/aperture/lens)" % (kind,))
        I = np.abs(U) ** 2
        trace.append({"step": k, "value": float(val), "z_mm": round(z, 4),
                      "peak": round(float(I.max()), 6), "power": round(float(I.sum()), 4)})
    return U, dx_mm, z, trace


def propagate_chain(steps, wavelength_nm=632.8, w0_mm=None, aperture_mm=None,
                    n_grid=512, dx_mm=None, band_limit=True, png_path=None):
    """March a complex field through a SEQUENCE of optical steps -- the POPPY-style multi-plane OpticalSystem
    that CHAINS the single-step angular_spectrum propagator (which alone cannot march a field through a
    sequence). Each step is (kind, value):
        ("prop", dz_mm)     free-space angular-spectrum propagation by dz (mm)
        ("aperture", D_mm)  hard circular aperture, diameter D (mm)
        ("lens", f_mm)      ideal thin lens, phase exp(-i pi r^2 / (lambda f))
    The source is a Gaussian beam (w0_mm) OR a uniform field clipped by a circular aperture (aperture_mm). The
    grid auto-sizes to ~2.5x the source diameter unless dx_mm is given. Returns {ok, final (field_metrics of the
    last plane), z_total_mm, trace:[per-step z/w/peak/power]}. Off-trace; the live ray-trace is byte-identical.
    NB this layer is for NEAR-field / moderate propagation; a tight focus or a Fraunhofer-distance far field is
    better via direct FFT (wave_psf / slit_metrics) -- the anti-alias band-limit degrades far-field nulls."""
    U, dx_mm, z, trace = _run_chain(steps, wavelength_nm, w0_mm, aperture_mm, n_grid, dx_mm, band_limit)
    fm = field_metrics(U, dx_mm, wavelength_nm, png_path=png_path)
    return {"ok": True, "final": fm, "z_total_mm": round(z, 4), "n_steps": len(steps),
            "dx_mm": round(dx_mm, 6), "trace": trace}


def _fft2c(U):
    """Centred 2-D forward FFT (fftshift wrap), matching slit/talbot convention."""
    return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(U)))


def _ifft2c(U):
    return np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(U)))


def gerchberg_saxton(target_amplitude, source_amplitude, n_iter=60, seed=0):
    """Gerchberg-Saxton phase retrieval / CGH design -- the iterative Fourier-transform algorithm: find a
    SOURCE-plane phase whose far-field |FFT| matches ``target_amplitude``, given the ``source_amplitude``. Each
    iteration enforces the source amplitude -> FFT to the far field -> enforce the target amplitude -> IFFT
    back, keeping the phase at each step. The far-field amplitude error is MONOTONE NON-INCREASING (the GS
    convergence guarantee). Off-trace; seed-pinned local RNG for the initial random phase. Returns {ok,
    source_phase (2D), achieved_amplitude (2D), errors (per-iter), final_error, correlation, monotone}."""
    target_amplitude = np.asarray(target_amplitude, dtype=float)
    source_amplitude = np.asarray(source_amplitude, dtype=float)
    # scale the target to the source's far-field energy (Parseval: ||far|| = ||fft2(source)|| for ANY source
    # phase) so the amplitude error measures SHAPE mismatch, not an arbitrary target-vs-source energy offset.
    far_norm = float(np.linalg.norm(np.fft.fft2(source_amplitude)))
    target_amplitude = target_amplitude * (far_norm / (float(np.linalg.norm(target_amplitude)) or 1.0))
    rng = np.random.default_rng(int(seed))
    U = source_amplitude * np.exp(1j * rng.uniform(-np.pi, np.pi, source_amplitude.shape))
    Tn = far_norm or 1.0
    errs = []
    for _ in range(int(n_iter)):
        Far = _fft2c(U)
        errs.append(float(np.linalg.norm(target_amplitude - np.abs(Far)) / Tn))
        Far = target_amplitude * np.exp(1j * np.angle(Far))     # enforce the target far-field amplitude
        U = source_amplitude * np.exp(1j * np.angle(_ifft2c(Far)))  # back, enforce the source amplitude
    phase = np.angle(U)
    achieved = np.abs(_fft2c(source_amplitude * np.exp(1j * phase)))
    corr = float(np.sum(achieved * target_amplitude) / ((np.linalg.norm(achieved) or 1.0) * Tn))
    mono = all(errs[i + 1] <= errs[i] + 1e-9 for i in range(len(errs) - 1))
    return {"ok": True, "source_phase": phase, "achieved_amplitude": achieved, "errors": errs,
            "final_error": round(errs[-1], 6) if errs else None, "correlation": round(corr, 5),
            "monotone": bool(mono), "n_iter": int(n_iter)}


def gs_named_target(name, n_grid):
    """Build a canonical far-field TARGET amplitude (for beam-shaping / CGH GS demos) + a circular source
    aperture amplitude. name in {spot, ring, double, tophat}. Returns (target_amp, source_amp)."""
    c = n_grid // 2
    x = np.arange(n_grid) - c
    X, Y = np.meshgrid(x, x)
    R = np.sqrt(X * X + Y * Y)
    src = (R <= 0.32 * n_grid).astype(float)                    # circular source aperture
    s = 0.16 * n_grid
    nm = (name or "ring").lower()
    if nm == "spot":
        T = np.exp(-(R ** 2) / (2.0 * (0.03 * n_grid) ** 2))
    elif nm == "double":
        d = 0.12 * n_grid
        T = np.exp(-((X - d) ** 2 + Y ** 2) / (2 * (0.03 * n_grid) ** 2)) + \
            np.exp(-((X + d) ** 2 + Y ** 2) / (2 * (0.03 * n_grid) ** 2))
    elif nm == "tophat":
        T = (R <= s).astype(float)
    else:                                                       # ring / annulus
        T = np.exp(-((R - s) ** 2) / (2.0 * (0.03 * n_grid) ** 2))
    return T, src


def gerchberg_saxton_design(target="ring", n_grid=128, n_iter=60, seed=0):
    """Run GS on a named canonical target -> JSON-able convergence metrics (no big arrays). Returns
    {ok, target, correlation, final_error, initial_error, monotone, n_iter}."""
    T, src = gs_named_target(target, n_grid)
    r = gerchberg_saxton(T, src, n_iter=n_iter, seed=seed)
    return {"ok": True, "target": target, "correlation": r["correlation"], "final_error": r["final_error"],
            "initial_error": round(r["errors"][0], 6) if r["errors"] else None,
            "monotone": r["monotone"], "n_iter": r["n_iter"]}


def fienup_phase_retrieval(measured_intensity, support, n_iter=300, beta=0.9, mode="hio", seed=0,
                           er_polish=20):
    """Fienup phase retrieval -- recover a REAL, NON-NEGATIVE object from its Fourier-magnitude (the diffraction
    INTENSITY) ALONE, given a real-space SUPPORT mask. This is the genuine 'phase problem' of coherent
    diffractive imaging / crystallography: ``measured_intensity = |FFT(object)|^2`` is all a detector records --
    the phase is lost -- and the object is reconstructed from magnitude + the support (and reality + positivity)
    constraints. Where Gerchberg-Saxton knows the amplitude in BOTH planes (CGH design), here the object-plane
    amplitude is UNKNOWN; only its support is.

    ``mode='hio'`` is the Hybrid-Input-Output update: outside the support (or where negative) it does NOT zero
    the estimate but drives it with ``g - beta*g'`` feedback -- this is what escapes the stagnation/twin-image
    traps that pure error-reduction (``mode='er'``, the Gerchberg-Saxton analogue here) falls into. A short
    ``er_polish`` tail of error-reduction cleans the final magnitude. Off-trace; seed-pinned local RNG for the
    initial random Fourier phase. Returns {ok, recovered (2D real), fourier_error (per-iter), final_error,
    initial_error, support_frac}."""
    F_mag = np.sqrt(np.maximum(np.asarray(measured_intensity, dtype=float), 0.0))
    support = np.asarray(support).astype(bool)
    Tn = float(np.linalg.norm(F_mag)) or 1.0
    rng = np.random.default_rng(int(seed))
    g = np.real(_ifft2c(F_mag * np.exp(1j * rng.uniform(-np.pi, np.pi, F_mag.shape))))
    errs = []
    g_est = np.where(support, np.maximum(g, 0.0), 0.0)
    total = int(n_iter) + int(er_polish)
    for k in range(total):
        G = _fft2c(g)
        gp = np.real(_ifft2c(F_mag * np.exp(1j * np.angle(G))))     # Fourier-magnitude + reality projection
        viol = (~support) | (gp < 0.0)                              # outside support OR negative
        # the support-constrained estimate (the 'shadow' error-reduction object): this -- NOT the raw HIO
        # feedback iterate, which deliberately carries energy outside the support -- is the actual reconstruction,
        # and its Fourier-magnitude residual is the honest monotone-ish convergence metric (the literature's R_F).
        g_est = np.where(viol, 0.0, gp)
        errs.append(float(np.linalg.norm(F_mag - np.abs(_fft2c(g_est))) / Tn))
        if (mode == "er") or (k >= int(n_iter)):                    # ER for mode='er' and for the polish tail
            g = g_est
        else:                                                       # HIO feedback (off-support / negative driven)
            g = np.where(viol, g - beta * gp, gp)
    recovered = g_est
    return {"ok": True, "recovered": recovered, "fourier_error": errs,
            "final_error": round(errs[-1], 6) if errs else None,
            "initial_error": round(errs[0], 6) if errs else None,
            "support_frac": round(float(support.mean()), 4)}


def _fienup_object(name, n_grid):
    """Build a canonical REAL, non-negative test object + an OFF-CENTRE support mask (the off-centre placement
    breaks the conjugate twin-image ambiguity -- the twin falls outside the support). name in {dots, ell, tri}.
    Returns (object, support)."""
    n = int(n_grid)
    y = np.arange(n)[:, None]
    x = np.arange(n)[None, :]
    # off-centre support box in the (+,+) quadrant so the point-reflected twin lands outside it
    r0, r1 = int(0.50 * n), int(0.86 * n)
    c0, c1 = int(0.50 * n), int(0.86 * n)
    support = np.zeros((n, n), dtype=bool)
    support[r0:r1, c0:c1] = True
    obj = np.zeros((n, n), dtype=float)
    s = 0.018 * n
    nm = (name or "dots").lower()

    def blob(cy, cx, amp):
        return amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2.0 * s * s)))

    if nm == "ell":                                                 # an asymmetric 'L'
        ry = np.linspace(r0 + 0.10 * n, r1 - 0.06 * n, 7)
        for cy in ry:
            obj += blob(cy, c0 + 0.10 * n, 1.0)
        rx = np.linspace(c0 + 0.10 * n, c1 - 0.06 * n, 5)
        for cx in rx:
            obj += blob(r1 - 0.06 * n, cx, 1.0)
    elif nm == "tri":                                               # three corners of a triangle
        obj += blob(r0 + 0.08 * n, c0 + 0.08 * n, 1.0)
        obj += blob(r1 - 0.08 * n, c0 + 0.10 * n, 0.7)
        obj += blob(r0 + 0.20 * n, c1 - 0.08 * n, 0.85)
    else:                                                           # dots: 3 unequal blobs, asymmetric layout
        obj += blob(r0 + 0.10 * n, c0 + 0.09 * n, 1.0)
        obj += blob(r0 + 0.22 * n, c0 + 0.20 * n, 0.6)
        obj += blob(r0 + 0.12 * n, c0 + 0.26 * n, 0.85)
    return obj, support


def _register_corr(rec, truth):
    """Correlation of a recovery against the truth, INVARIANT to the unavoidable phase-retrieval AMBIGUITIES:
    a TRANSLATION (a centred-FFT magnitude is shift-invariant, so the object can sit anywhere in its support)
    and the conjugate TWIN (point reflection). Returns the peak normalized cross-correlation over all shifts,
    maximized over {as-is, point-reflected} -- i.e. how well the recovered object matches the truth once the
    free shift/flip is removed."""
    def _xc(a, b):
        a = a - a.mean()
        b = b - b.mean()
        na = float(np.linalg.norm(a)) or 1.0
        nb = float(np.linalg.norm(b)) or 1.0
        cc = np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))).real
        return float(cc.max() / (na * nb))
    return max(_xc(rec, truth), _xc(rec, truth[::-1, ::-1]))


def fienup_design(obj="dots", n_grid=128, n_iter=300, beta=0.9, seed=0):
    """Run Fienup HIO on a named canonical object -> JSON-able recovery metrics (no big arrays). Forms the
    object's diffraction intensity |FFT(obj)|^2, hands the algorithm ONLY that magnitude + the support, and
    reports how well the hidden object is recovered. ``correlation`` allows the conjugate twin ambiguity.
    Returns {ok, obj, correlation, final_error, initial_error, n_iter, support_frac}."""
    truth, support = _fienup_object(obj, n_grid)
    measured = np.abs(_fft2c(truth)) ** 2
    r = fienup_phase_retrieval(measured, support, n_iter=n_iter, beta=beta, seed=seed)
    corr = _register_corr(r["recovered"], truth)
    return {"ok": True, "obj": obj, "correlation": round(corr, 5), "final_error": r["final_error"],
            "initial_error": r["initial_error"], "n_iter": int(n_iter), "support_frac": r["support_frac"]}


def fourier_filter(U, kind="lowpass", cutoff_frac=0.15, phase_shift_deg=90.0):
    """4f FOURIER-PLANE spatial filter (Abbe-Porter): FFT the field, multiply by a Fourier-plane mask, IFFT
    back. ``kind``: 'lowpass' passes |f| <= cutoff_frac (smooths / removes fine detail), 'highpass' blocks it
    (edge enhancement / removes the DC background), 'phase_contrast' puts ``phase_shift_deg`` on the zero-order
    only (Zernike phase contrast: makes a PURE-PHASE object visible in intensity). cutoff_frac is the cutoff
    radius as a fraction of the grid. Off-trace; live trace byte-identical. Returns the filtered complex field."""
    U = np.asarray(U, dtype=complex)
    n = U.shape[0]
    c = n // 2
    F = _fft2c(U)
    x = np.arange(n) - c
    X, Y = np.meshgrid(x, x)
    R = np.hypot(X, Y)
    rc = cutoff_frac * n
    if kind == "lowpass":
        M = (R <= rc).astype(complex)
    elif kind == "highpass":
        M = (R > rc).astype(complex)
    elif kind == "phase_contrast":
        M = np.ones_like(R, dtype=complex)
        M[R <= max(rc, 1.5)] = np.exp(1j * math.radians(phase_shift_deg))
    else:
        M = np.ones_like(R, dtype=complex)
    return _ifft2c(F * M)


def _filter_object(name, n_grid):
    """A canonical test object for Fourier filtering: 'grating' (square-wave), 'edge' (half-plane step),
    'phase' (a weak pure-phase bump -- uniform intensity, invisible without phase contrast)."""
    c = n_grid // 2
    x = np.arange(n_grid) - c
    X, Y = np.meshgrid(x, x)
    nm = (name or "grating").lower()
    if nm == "edge":
        return (X >= 0).astype(complex)
    if nm == "phase":
        return np.exp(1j * 0.3 * (np.hypot(X, Y) < 0.3 * n_grid)).astype(complex)
    return (np.sign(np.sin(2.0 * np.pi * X / (0.08 * n_grid))) * 0.5 + 0.5).astype(complex)


def spatial_filter(obj="grating", kind="lowpass", cutoff_frac=0.15, n_grid=256):
    """4f Fourier spatial filtering on a canonical object -> JSON-able metrics. obj in {grating, edge, phase};
    kind in {lowpass, highpass, phase_contrast}. Returns {ok, obj, kind, input_intensity_std,
    output_intensity_std, output_mean_amp, contrast_ratio}."""
    U = _filter_object(obj, int(n_grid))
    V = fourier_filter(U, kind, cutoff_frac)
    Iin = np.abs(U) ** 2
    Iout = np.abs(V) ** 2
    return {"ok": True, "obj": obj, "kind": kind,
            "input_intensity_std": round(float(np.std(Iin)), 5),
            "output_intensity_std": round(float(np.std(Iout)), 5),
            "output_mean_amp": round(float(np.abs(V.mean())), 5),
            "contrast_ratio": round(float(np.std(Iout) / (np.std(Iin) + 1e-9)), 4)}


# --- laser cavity transverse modes (Hermite-Gaussian / Laguerre-Gaussian, the TEM_mn / donut patterns) -------
def _gen_laguerre(p, alpha, x):
    """Generalized Laguerre L_p^alpha(x) by its explicit finite sum (no scipy): sum_k (-1)^k C(p+alpha, p-k) x^k/k!.
    p, alpha are non-negative integers here (radial index p, |azimuthal| alpha=|l|)."""
    p = int(p)
    out = np.zeros_like(np.asarray(x, dtype=float))
    for k in range(p + 1):
        # binomial C(p+alpha, p-k) for integer args
        from math import comb, factorial
        out = out + ((-1) ** k) * comb(p + int(alpha), p - k) * np.power(x, k) / factorial(k)
    return out


def hermite_gaussian(m, n, w_mm, n_grid=256, dx_mm=None):
    """Hermite-Gaussian transverse cavity mode TEM_mn at the waist -- the rectangular-symmetry laser mode:
    U_mn(x,y) = H_m(sqrt2 x/w) H_n(sqrt2 y/w) exp(-(x^2+y^2)/w^2), grid-normalized to unit power. m nodal lines
    in x, n in y -> (m+1)(n+1) bright lobes. Returns the complex field (numpy)."""
    from numpy.polynomial.hermite import hermval
    n_grid = int(n_grid)
    if dx_mm is None:
        dx_mm = 8.0 * float(w_mm) / n_grid
    c = n_grid // 2
    ax = (np.arange(n_grid) - c) * dx_mm
    X, Y = np.meshgrid(ax, ax)
    w = float(w_mm)
    Hm = hermval(np.sqrt(2.0) * X / w, [0] * int(m) + [1])
    Hn = hermval(np.sqrt(2.0) * Y / w, [0] * int(n) + [1])
    U = (Hm * Hn * np.exp(-(X * X + Y * Y) / (w * w))).astype(complex)
    U = U / (np.sqrt(np.sum(np.abs(U) ** 2)) or 1.0)            # grid L2-normalize -> <U,U> = 1
    return U


def laguerre_gaussian(p, l, w_mm, n_grid=256, dx_mm=None):
    """Laguerre-Gaussian transverse cavity mode LG_{p,l} at the waist -- the cylindrical laser mode carrying
    orbital angular momentum l*hbar: U ∝ (sqrt2 r/w)^|l| L_p^|l|(2r^2/w^2) exp(-r^2/w^2) exp(i l phi). For p=0,
    l!=0 it is the DONUT mode (on-axis null + an exp(i l phi) phase vortex). Grid-normalized to unit power.
    Returns the complex field (numpy)."""
    n_grid = int(n_grid)
    if dx_mm is None:
        dx_mm = 8.0 * float(w_mm) / n_grid
    c = n_grid // 2
    ax = (np.arange(n_grid) - c) * dx_mm
    X, Y = np.meshgrid(ax, ax)
    w = float(w_mm)
    R = np.hypot(X, Y)
    PHI = np.arctan2(Y, X)
    al = abs(int(l))
    rho2 = 2.0 * R * R / (w * w)
    U = (np.power(np.sqrt(2.0) * R / w, al) * _gen_laguerre(p, al, rho2)
         * np.exp(-(R * R) / (w * w)) * np.exp(1j * int(l) * PHI))
    U = U / (np.sqrt(np.sum(np.abs(U) ** 2)) or 1.0)
    return U


def _mode_inner(A, B):
    """Discrete inner product <A,B> of two grid fields (already L2-normalized): sum(conj(A)*B)."""
    return complex(np.sum(np.conj(A) * B))


def _count_lobes(I, thresh_frac=0.18):
    """Count bright lobes = connected components of {I > thresh_frac*max} via a tiny flood fill (4-neighbour)."""
    mask = I > (thresh_frac * I.max())
    seen = np.zeros_like(mask, dtype=bool)
    n = 0
    rows, cols = mask.shape
    for i0 in range(rows):
        for j0 in range(cols):
            if mask[i0, j0] and not seen[i0, j0]:
                n += 1
                stack = [(i0, j0)]
                seen[i0, j0] = True
                while stack:
                    i, j = stack.pop()
                    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        a, b = i + di, j + dj
                        if 0 <= a < rows and 0 <= b < cols and mask[a, b] and not seen[a, b]:
                            seen[a, b] = True
                            stack.append((a, b))
    return n


def tem_mode(family="HG", i=1, j=0, w_mm=0.5, n_grid=256, dx_mm=None):
    """Build a named laser cavity transverse mode field. family in {HG (Hermite-Gaussian TEM_ij), LG
    (Laguerre-Gaussian LG_{p=i, l=j})}. Returns the complex field (numpy)."""
    if (family or "HG").upper() == "LG":
        return laguerre_gaussian(i, j, w_mm, n_grid=n_grid, dx_mm=dx_mm)
    return hermite_gaussian(i, j, w_mm, n_grid=n_grid, dx_mm=dx_mm)


def tem_mode_metrics(family="HG", i=1, j=0, w_mm=0.5, n_grid=256, dx_mm=None):
    """Laser cavity transverse mode -> JSON-able metrics. For HG TEM_ij: (i+1)(j+1) lobes, Gouy order i+j+1,
    second-moment <x^2> = (2 i + 1) w^2/4. For LG_{p=i, l=j}: a donut (on-axis null) when l!=0, with an
    exp(i l phi) phase vortex (azimuthal winding 2 pi l) and Gouy order 2 p + |l| + 1. Returns {ok, family,
    indices, n_lobes, gouy_order, on_axis_intensity_frac, x2_over_w2, oam_winding_turns (LG)}."""
    n_grid = int(n_grid)
    if dx_mm is None:
        dx_mm = 8.0 * float(w_mm) / n_grid
    fam = (family or "HG").upper()
    U = tem_mode(fam, i, j, w_mm, n_grid=n_grid, dx_mm=dx_mm)
    I = np.abs(U) ** 2
    c = n_grid // 2
    ax = (np.arange(n_grid) - c) * dx_mm
    X, _Y = np.meshgrid(ax, ax)
    x2 = float(np.sum(I * X * X))                              # <x^2> (I is unit-power normalized)
    out = {"ok": True, "family": fam, "indices": [int(i), int(j)],
           "n_lobes": int(_count_lobes(I)),
           "on_axis_intensity_frac": round(float(I[c, c] / (I.max() or 1.0)), 5),
           "x2_over_w2": round(x2 / (float(w_mm) ** 2), 5)}
    if fam == "LG":
        out["gouy_order"] = 2 * int(i) + abs(int(j)) + 1
        # azimuthal phase winding around a ring at r ~ w: total turns = l
        ring = max(2, int(0.5 * float(w_mm) / dx_mm))
        ph = []
        for t in np.linspace(0, 2 * np.pi, 73)[:-1]:
            ii = int(round(c + ring * np.sin(t)))
            jj = int(round(c + ring * np.cos(t)))
            ph.append(np.angle(U[ii, jj]))
        dwind = np.diff(np.unwrap(ph + [ph[0]]))
        out["oam_winding_turns"] = round(float(np.sum(dwind) / (2 * np.pi)), 3)
    else:
        out["gouy_order"] = int(i) + int(j) + 1
    return out
