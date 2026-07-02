"""nlse.py -- opt-in 1D pulse-propagation layer: the nonlinear Schrodinger equation by the split-step method.

The live engine is lumped + steady-state; field.py adds spatial diffraction. This module adds the TEMPORAL
field the engine lacks: propagation of an optical PULSE envelope A(z,T) down a dispersive + Kerr-nonlinear
fiber by the symmetric split-step Fourier method (Agrawal, Nonlinear Fiber Optics). It is on-demand analysis
like wave.py / field.py / turbulence.py -- it does NOT touch the live ray tracer, so the trace stays
byte-identical. Needs numpy (Blender ships it); matplotlib only for the optional PNG.

Governing equation (loss alpha, GVD beta2, Kerr gamma):
  dA/dz = -(alpha/2) A - i (beta2/2) d^2A/dT^2 + i gamma |A|^2 A
Symmetric split-step: exp(D dz/2) exp(N dz) exp(D dz/2), the linear operator D = i(beta2/2)omega^2 - alpha/2
applied in the Fourier domain (omega = 2 pi f), the Kerr operator N = i gamma |A|^2 applied in time.

Units: T [ps], z [m], beta2 [ps^2/m], gamma [1/(W m)], alpha [1/m], A [sqrt(W)] (|A|^2 = power in W).
Key checks (closed forms physics_verify ok=true): dispersion length L_D = T0^2/|beta2|, nonlinear length
L_NL = 1/(gamma P0), soliton order N^2 = gamma P0 T0^2/|beta2|, soliton period z0 = (pi/2) L_D, fundamental
soliton peak power P1 = |beta2|/(gamma T0^2). The FUNDAMENTAL soliton (N=1) keeps |A(z,T)|^2 invariant
(shape-preserving, only a phase accrues) -- the headline validation in tests/test_validation.py.
"""
from __future__ import annotations

import math

import numpy as np


def sech_pulse(t_ps, t0_ps, p0_W):
    """Fundamental-soliton amplitude A0 = sqrt(P0) sech(T/T0) [sqrt(W)] on the time grid t_ps."""
    return (math.sqrt(p0_W) / np.cosh(np.asarray(t_ps) / t0_ps)).astype(complex)


def gaussian_pulse(t_ps, t0_ps, p0_W):
    """Gaussian amplitude A0 = sqrt(P0) exp(-T^2/(2 T0^2)) [sqrt(W)]."""
    return (math.sqrt(p0_W) * np.exp(-(np.asarray(t_ps) ** 2) / (2.0 * t0_ps ** 2))).astype(complex)


def split_step(A0, dt_ps, dz_m, n_steps, beta2_ps2_per_m, gamma_per_W_per_m, alpha_per_m=0.0):
    """Propagate the pulse envelope A0 over n_steps*dz_m by the symmetric split-step Fourier method.

    Returns the complex envelope A(z,T) at the output. Linear (GVD + loss) half-steps in the Fourier domain,
    the Kerr nonlinearity in the time domain. Energy is conserved when alpha=0."""
    A = np.asarray(A0, dtype=complex).copy()
    n = A.size
    omega = 2.0 * math.pi * np.fft.fftfreq(n, d=dt_ps)          # angular frequency [rad/ps]
    D = 1j * (beta2_ps2_per_m / 2.0) * omega ** 2 - alpha_per_m / 2.0     # linear operator d/dz
    lin_half = np.exp(D * (dz_m / 2.0))
    for _ in range(int(n_steps)):
        A = np.fft.ifft(lin_half * np.fft.fft(A))               # linear half-step
        A = A * np.exp(1j * gamma_per_W_per_m * np.abs(A) ** 2 * dz_m)    # Kerr full-step
        A = np.fft.ifft(lin_half * np.fft.fft(A))               # linear half-step
    return A


def _fwhm_ps(power, t_ps):
    """FWHM of the (single-peak) power profile in ps, by half-max crossings about the peak."""
    p = np.asarray(power)
    pk = p.max()
    if pk <= 0:
        return 0.0
    idx = np.where(p >= 0.5 * pk)[0]
    return float(t_ps[idx[-1]] - t_ps[idx[0]]) if idx.size else 0.0


def pulse_metrics(A, dt_ps, A0=None, png_path=None, t_ps=None):
    """Pulse metrics: peak power, energy, temporal FWHM, RMS spectral width, and (if A0 given) the shape-
    invariance error vs the input |A0|^2 (the soliton test). Returns a JSON-able dict. Pure analysis."""
    A = np.asarray(A, dtype=complex)
    n = A.size
    if t_ps is None:
        t_ps = (np.arange(n) - n // 2) * dt_ps
    power = np.abs(A) ** 2
    energy = float(power.sum() * dt_ps)                          # pJ (W*ps)
    spec = np.abs(np.fft.fftshift(np.fft.fft(A))) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(n, d=dt_ps))             # THz
    sp = spec.sum()
    f0 = float((f * spec).sum() / sp) if sp > 0 else 0.0
    rms_bw = float(math.sqrt(max((f * f * spec).sum() / sp - f0 ** 2, 0.0))) if sp > 0 else 0.0
    out = {
        "ok": True,
        "peak_power_W": round(float(power.max()), 5),
        "energy_pJ": round(energy, 5),
        "fwhm_ps": round(_fwhm_ps(power, t_ps), 5),
        "rms_bandwidth_THz": round(rms_bw, 5),
        "n_grid": n, "dt_ps": dt_ps,
    }
    if A0 is not None:
        p0 = np.abs(np.asarray(A0)) ** 2
        denom = p0.max() or 1.0
        out["shape_invariance_err"] = round(float(np.max(np.abs(power - p0)) / denom), 6)   # 0 for a soliton
    if png_path:
        try:
            _render_pulse(t_ps, power, A0, out, png_path)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def _render_pulse(t_ps, power, A0, meta, png_path):
    try:
        from . import plotting as _plotting
    except ImportError:
        import plotting as _plotting
    plt = _plotting.pyplot()
    if plt is None:
        meta["png_error"] = "matplotlib unavailable (numbers are unaffected)"
        return None
    fig, ax = plt.subplots(figsize=(6, 4))
    if A0 is not None:
        ax.plot(t_ps, np.abs(A0) ** 2, "--", color="#888", label="input |A0|^2")
    ax.plot(t_ps, power, color="#4ea3ff", label="output |A(z)|^2")
    ax.set_xlabel("T [ps]")
    ax.set_ylabel("power [W]")
    ax.set_title("NLSE split-step  peak=%.2f W  FWHM=%.3f ps" % (meta["peak_power_W"], meta["fwhm_ps"]))
    ax.legend(fontsize=8)
    fig.savefig(png_path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
    plt.close(fig)
