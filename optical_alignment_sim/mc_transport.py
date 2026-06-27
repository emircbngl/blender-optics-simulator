"""mc_transport.py -- opt-in biomedical-optics layer: Monte-Carlo photon transport in a turbid slab (MCML).

Biomedical optics abandons coherent beams for stochastic radiative transport: photons random-walk through a
scattering + absorbing medium (Wang & Wu; the MCML code of Wang, Jacques & Zheng). This module adds that
stochastic engine -- a vectorized MCML-style Monte-Carlo of photon packets through a homogeneous slab with
Henyey-Greenstein scattering. It is on-demand analysis like wave.py / field.py / nlse.py: it does NOT touch
the live ray tracer, so the trace stays byte-identical. RNG is a SEED-PINNED local Generator
(np.random.default_rng) -- no global state. This is the one genuinely GPU-friendly category (embarrassingly
parallel); the CPU version here is fine for moderate photon counts.

Physics (closed forms physics_verify ok=true this session):
  reduced scattering   mu_s' = mu_s (1 - g)
  total attenuation    mu_t  = mu_a + mu_s
  effective attenuation mu_eff = sqrt(3 mu_a (mu_a + mu_s'))   [diffusion approximation]
  penetration depth    delta = 1/mu_eff
  ballistic (unscattered) transmission   T_ball = exp(-mu_t L)   [Beer-Lambert]
The MC tallies diffuse reflectance R, transmittance T, absorption A (energy-conserving R+T+A=1 at a matched
boundary), the unscattered ballistic transmission (-> Beer-Lambert), and the fluence(depth) whose far-field
log-slope recovers mu_eff (-> the diffusion penetration depth). Validated in tests/test_validation.py.
"""
from __future__ import annotations

import math

import numpy as np


def _hg_costheta(g, xi):
    """Inverse-CDF sample of cos(theta) from the Henyey-Greenstein phase function (anisotropy g)."""
    if abs(g) < 1e-6:
        return 2.0 * xi - 1.0
    t = (1.0 - g * g) / (1.0 - g + 2.0 * g * xi)
    return (1.0 + g * g - t * t) / (2.0 * g)


def _spin(ux, uy, uz, ct, phi):
    """Rotate the unit direction (ux,uy,uz) by polar cos(theta)=ct and azimuth phi (MCML spin formula)."""
    st = np.sqrt(np.clip(1.0 - ct * ct, 0.0, 1.0))
    cp, sp = np.cos(phi), np.sin(phi)
    near = np.abs(uz) > 0.99999
    denom = np.sqrt(np.clip(1.0 - uz * uz, 1e-12, None))
    nx = st * (ux * uz * cp - uy * sp) / denom + ux * ct
    ny = st * (uy * uz * cp + ux * sp) / denom + uy * ct
    nz = -st * cp * denom + uz * ct
    # near the +/-z pole the general formula is singular -> use the simple form
    nx = np.where(near, st * cp, nx)
    ny = np.where(near, st * sp, ny)
    nz = np.where(near, np.sign(uz) * ct, nz)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    return nx / norm, ny / norm, nz / norm


def monte_carlo_slab(mu_a_per_mm, mu_s_per_mm, g, thickness_mm, n_photons=20000, seed=0,
                     n_depth_bins=60, w_min=1.0e-4, max_steps=5000):
    """Vectorized MCML-style Monte-Carlo of n_photons through a homogeneous slab (matched boundary, normal
    pencil-beam incidence). Returns {ok, reflectance, transmittance, absorbed, energy_sum, ballistic_T,
    penetration_depth_mm, mu_eff_fit_per_mm, depth_mm, fluence, n_photons, ...} -- all energy fractions, so
    reflectance + transmittance + absorbed = 1 (energy conservation). Seed-pinned RNG; pure analysis."""
    rng = np.random.default_rng(int(seed))
    n = int(n_photons)
    mu_t = mu_a_per_mm + mu_s_per_mm
    z = np.zeros(n)
    ux = np.zeros(n); uy = np.zeros(n); uz = np.ones(n)
    w = np.ones(n)
    nscat = np.zeros(n, dtype=int)
    alive = np.ones(n, dtype=bool)
    R = T = A = ball_T = 0.0
    dz = thickness_mm / n_depth_bins
    fluence = np.zeros(n_depth_bins)
    for _ in range(int(max_steps)):
        idx = np.where(alive)[0]
        if idx.size == 0:
            break
        s = -np.log(rng.random(idx.size)) / mu_t
        z_new = z[idx] + s * uz[idx]
        lo = z_new < 0.0
        hi = z_new > thickness_mm
        ins = ~(lo | hi)
        if lo.any():
            li = idx[lo]; R += w[li].sum(); alive[li] = False
        if hi.any():
            hidx = idx[hi]; T += w[hidx].sum()
            ball_T += w[hidx[nscat[hidx] == 0]].sum()
            alive[hidx] = False
        ii = idx[ins]
        if ii.size:
            z[ii] = z_new[ins]
            dA = w[ii] * (mu_a_per_mm / mu_t)
            np.add.at(fluence, np.clip((z[ii] / dz).astype(int), 0, n_depth_bins - 1), dA / mu_a_per_mm)
            A += dA.sum()
            w[ii] = w[ii] - dA
            ct = _hg_costheta(g, rng.random(ii.size))
            phi = 2.0 * math.pi * rng.random(ii.size)
            ux[ii], uy[ii], uz[ii] = _spin(ux[ii], uy[ii], uz[ii], ct, phi)
            nscat[ii] += 1
            low = w[ii] < w_min
            if low.any():
                lw = ii[low]
                survive = rng.random(lw.size) < 0.1
                A += w[lw[~survive]].sum()                  # killed packets deposit their remaining weight
                w[lw] = np.where(survive, w[lw] * 10.0, 0.0)
                alive[lw[~survive]] = False
    # any still-alive packets at max_steps: deposit their weight as absorbed (rare; keeps energy conserved)
    A += w[alive].sum()
    R, T, A, ball_T = R / n, T / n, A / n, ball_T / n
    fluence = fluence / n
    depth = (np.arange(n_depth_bins) + 0.5) * dz
    # fit mu_eff from the far-field log-slope of the fluence (diffusion regime: phi ~ exp(-mu_eff z))
    mu_eff_fit = None
    lo_i, hi_i = n_depth_bins // 4, 3 * n_depth_bins // 4
    fl = fluence[lo_i:hi_i]
    if np.all(fl > 0):
        slope = np.polyfit(depth[lo_i:hi_i], np.log(fl), 1)[0]
        mu_eff_fit = float(-slope)
    return {
        "ok": True,
        "reflectance": round(float(R), 5),
        "transmittance": round(float(T), 5),
        "absorbed": round(float(A), 5),
        "energy_sum": round(float(R + T + A), 5),
        "ballistic_T": round(float(ball_T), 6),
        "mu_eff_fit_per_mm": round(mu_eff_fit, 5) if mu_eff_fit else None,
        "penetration_depth_mm": round(1.0 / mu_eff_fit, 4) if mu_eff_fit else None,
        "depth_mm": [round(float(v), 4) for v in depth],
        "fluence": [round(float(v), 6) for v in fluence],
        "n_photons": n, "seed": int(seed),
    }


def diffusion_mu_eff(mu_a_per_mm, mu_s_per_mm, g):
    """Diffusion-approximation effective attenuation mu_eff = sqrt(3 mu_a (mu_a + mu_s')), mu_s'=mu_s(1-g)."""
    mu_sp = mu_s_per_mm * (1.0 - g)
    return math.sqrt(3.0 * mu_a_per_mm * (mu_a_per_mm + mu_sp))
