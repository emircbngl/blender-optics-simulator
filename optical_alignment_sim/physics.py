"""Pure optical-physics math: Jones/Stokes polarization, ABCD ray-transfer
matrices, Gaussian-beam q-parameter, and coherence.

No bpy / numpy dependency - plain Python ``complex`` + ``math`` - so it is unit
testable with a bare interpreter (run ``python3 physics.py``) and mirrors the
testable-helper spirit of geometry.py. The tracer (C2-C5) imports these.

Conventions
-----------
* Jones vector ``J = (Ex, Ey)`` - complex amplitudes in the element's local x/y
  (x = horizontal / p-plane, y = vertical / s-plane). Intensity = |Ex|^2+|Ey|^2.
* Angles are **degrees** at the API boundary, converted internally.
* Wavelengths in **nm**, lengths in **mm** (the add-on's unit), matching the tracer.
"""
from __future__ import annotations

import math
import cmath

NM_TO_MM = 1.0e-6


# --- Jones vectors ----------------------------------------------------------

def jones_linear(angle_deg=0.0, amp=1.0):
    """Linear polarization at ``angle_deg`` from local +x."""
    a = math.radians(angle_deg)
    return (complex(amp * math.cos(a)), complex(amp * math.sin(a)))


def jones_circular(handedness='RIGHT', amp=1.0):
    """Circular polarization. RIGHT = (1, i)/sqrt2, LEFT = (1, -i)/sqrt2."""
    s = 1j if str(handedness).upper().startswith('R') else -1j
    n = amp / math.sqrt(2.0)
    return (complex(n), n * s)


def jones_unpolarized(amp=1.0):
    """Representative state for an unpolarized source (DOP is tracked separately;
    a single Jones vector cannot encode true unpolarized light)."""
    return jones_linear(0.0, amp)


def intensity(J):
    return abs(J[0]) ** 2 + abs(J[1]) ** 2


def scale(J, s):
    return (J[0] * s, J[1] * s)


def add(J1, J2):
    return (J1[0] + J2[0], J1[1] + J2[1])


def with_phase(J, phase_rad):
    """Multiply a Jones vector by a global phase e^{i*phase}."""
    p = cmath.exp(1j * phase_rad)
    return (J[0] * p, J[1] * p)


# --- Jones matrices ---------------------------------------------------------

def _matvec(M, J):
    return (M[0][0] * J[0] + M[0][1] * J[1],
            M[1][0] * J[0] + M[1][1] * J[1])


def _matmat(A, B):
    return ((A[0][0] * B[0][0] + A[0][1] * B[1][0], A[0][0] * B[0][1] + A[0][1] * B[1][1]),
            (A[1][0] * B[0][0] + A[1][1] * B[1][0], A[1][0] * B[0][1] + A[1][1] * B[1][1]))


def _rot(theta):
    c, s = math.cos(theta), math.sin(theta)
    return ((complex(c), complex(-s)), (complex(s), complex(c)))


def _rotated(M, angle_deg):
    """R(theta) M R(-theta) - express a matrix rotated to ``angle_deg``."""
    th = math.radians(angle_deg)
    return _matmat(_rot(th), _matmat(M, _rot(-th)))


def M_polarizer(axis_deg=0.0, extinction=1000.0):
    """Linear polarizer transmitting along ``axis_deg``; finite power extinction
    ratio leaks a little of the orthogonal component (amplitude = sqrt(1/ext))."""
    t = math.sqrt(max(0.0, 1.0 / extinction)) if extinction else 0.0
    base = ((complex(1.0), 0j), (0j, complex(t)))
    return _rotated(base, axis_deg)


def M_waveplate(retardance_deg=180.0, fast_axis_deg=0.0):
    """Linear retarder (HWP=180, QWP=90) with fast axis at ``fast_axis_deg``."""
    d = math.radians(retardance_deg)
    base = ((cmath.exp(-1j * d / 2.0), 0j), (0j, cmath.exp(1j * d / 2.0)))
    return _rotated(base, fast_axis_deg)


def M_scalar(amp=1.0):
    """Polarization-preserving amplitude scale (mirror / non-pol splitter leg)."""
    return ((complex(amp), 0j), (0j, complex(amp)))


# Polarizing beam splitter: transmit p (local x), reflect s (local y).
PBS_TRANSMIT = ((complex(1.0), 0j), (0j, 0j))
PBS_REFLECT = ((0j, 0j), (0j, complex(1.0)))


def analyzer_matrix(kind):
    """Detector polarization analyzer -> Jones matrix, or None for 'NONE'."""
    k = str(kind).upper()
    if k in ('NONE', ''):
        return None
    if k in ('H', 'H_LINEAR'):
        return M_polarizer(0.0)
    if k in ('V', 'V_LINEAR'):
        return M_polarizer(90.0)
    if k in ('D', 'DIAGONAL'):
        return M_polarizer(45.0)
    if k in ('A', 'ANTIDIAGONAL'):
        return M_polarizer(-45.0)
    if k == 'RCP':                                   # projector |R><R|, |R>=(1,i)/sqrt2
        return ((complex(0.5), complex(0, -0.5)), (complex(0, 0.5), complex(0.5)))
    if k == 'LCP':                                   # projector |L><L|, |L>=(1,-i)/sqrt2
        return ((complex(0.5), complex(0, 0.5)), (complex(0, -0.5), complex(0.5)))
    return None


def apply(M, J):
    """Apply a Jones matrix to a Jones vector."""
    return _matvec(M, J)


# --- Stokes parameters / polarization state ---------------------------------

def stokes(J):
    """(S0, S1, S2, S3) from a Jones vector."""
    ex, ey = J
    exy = ex * ey.conjugate()
    s0 = abs(ex) ** 2 + abs(ey) ** 2
    s1 = abs(ex) ** 2 - abs(ey) ** 2
    s2 = 2.0 * exy.real
    s3 = -2.0 * exy.imag
    return (s0, s1, s2, s3)


def polarization_state_from_stokes(s0, s1, s2, s3):
    """Polarization summary from a (possibly partial) Stokes vector. DOP < 1 for
    mixed/unpolarized light; the incoherent sum of beams' Stokes is partial."""
    if s0 < 1e-12:
        return {"kind": "none", "azimuth_deg": 0.0, "ellipticity_deg": 0.0, "dop": 0.0}
    spol = math.sqrt(s1 * s1 + s2 * s2 + s3 * s3)               # polarized-intensity (S_pol)
    dop = spol / s0
    azimuth = 0.5 * math.degrees(math.atan2(s2, s1))
    # ellipticity of the POLARIZED fraction -> normalize by S_pol, not S0 (they differ for DOP<1)
    ellipticity = 0.5 * math.degrees(math.asin(max(-1.0, min(1.0, s3 / spol)))) if spol > 1e-12 else 0.0
    frac_circ = abs(s3) / s0
    if dop < 0.3:
        kind = "unpolarized"
    elif frac_circ > 0.9 * dop:
        kind = "circular"
    elif frac_circ < 0.1:
        kind = "linear"
    else:
        kind = "elliptical"
    return {"kind": kind, "azimuth_deg": azimuth, "ellipticity_deg": ellipticity, "dop": dop}


def polarization_state(J):
    """Human-readable polarization summary from a Jones vector."""
    return polarization_state_from_stokes(*stokes(J))


# --- dispersion (Sellmeier n(lambda)) ---------------------------------------

# Sellmeier coefficients (B1,B2,B3,C1,C2,C3; lambda in micron) for common glasses.
# Form: n^2 - 1 = sum_j Bj*L^2/(L^2 - Cj), L = lambda in micron, Cj in micron^2 (Cj = lambda_j^2).
# Each set is the manufacturer/literature datasheet fit and reproduces the published n(lambda) to
# 5 decimals at the standard spectral lines (verified in tests/_verify_prism.py against nd/nC/ne/Vd):
#   N-BK7 / FUSED_SILICA  -- existing, Schott / Malitson 1965.
#   N-SF11  -- Schott dense flint, datasheet fit (nd=1.78472, ne=1.79192, Vd=25.68). Dispersing-prism glass.
#   F2      -- Schott flint, datasheet fit (nd=1.62004, Vd=36.37).
#   N-F2    -- Schott lead-free flint, datasheet fit (nd=1.62005, Vd=36.43).
#   CaF2    -- Malitson 1963, "A Redetermination of Some Optical Properties of Calcium Fluoride",
#              Appl. Opt. 2(11):1103 (nd=1.43385, Vd=94.99); the low-dispersion / UV reference.
# Sources: SCHOTT optical-glass datasheet collection; refractiveindex.info (Malitson 1963 for CaF2).
GLASSES = {
    'N-BK7': (1.03961212, 0.231792344, 1.01046945, 0.00600069867, 0.0200179144, 103.560653),
    'FUSED_SILICA': (0.6961663, 0.4079426, 0.8974794, 0.0046791, 0.0135121, 97.934003),
    'N-SF11': (1.73759695, 0.313747346, 1.89878101, 0.0131887070, 0.0623068142, 155.236290),
    'F2': (1.34533359, 0.209073176, 0.937357162, 0.00997743871, 0.0470450767, 111.886764),
    'N-F2': (1.39757037, 0.159201403, 1.26865430, 0.00995906143, 0.0546931752, 119.248346),
    # CaF2 C-coefficients are the SQUARED resonance wavelengths from Malitson: (0.050263605, 0.1003909, 34.649040) um.
    'CaF2': (0.5675888, 0.4710914, 3.8484723, 0.050263605 ** 2, 0.1003909 ** 2, 34.649040 ** 2),
}


def sellmeier_n(wl_nm, glass='N-BK7'):
    """Refractive index n(lambda) via the Sellmeier equation (lambda in nm)."""
    b1, b2, b3, c1, c2, c3 = GLASSES.get(glass, GLASSES['N-BK7'])
    L2 = (wl_nm * 1.0e-3) ** 2          # lambda^2 in micron^2
    n2 = 1.0 + b1 * L2 / (L2 - c1) + b2 * L2 / (L2 - c2) + b3 * L2 / (L2 - c3)
    # The Sellmeier fit is only valid across its transparency window (~0.3-2.5 um for N-BK7).
    # Below the longest pole it swings (n2<0 between poles, or absurd just past one); clamp to the
    # nearest physical bound so a deep-UV sweep step yields a sane index, not 1.0 or n~30.
    if not (0.0 < n2 < 16.0):           # n in (1, 4): covers all common optical glasses
        return 1.0 if n2 <= 1.0 else 4.0
    return math.sqrt(n2)


# --- prism deviation (two-surface Snell + minimum-deviation relation) --------
# A thin/thick prism of apex angle A, index n: a ray entering at incidence i1 refracts at the first
# face (sin i1 = n sin r1), crosses to the second face where r2 = A - r1, and refracts out
# (n sin r2 = sin i2). The total deviation is delta = i1 + i2 - A. At minimum deviation the path is
# symmetric (i1 = i2, r1 = r2 = A/2) and the classic relation n = sin((A+delta_min)/2)/sin(A/2) holds.
# physics_verify ok=true (tests/_verify_prism.py): the deviation reduces to delta_min at symmetric
# incidence and the min-deviation relation inverts exactly.

def prism_deviation(n, apex_deg, incidence_deg):
    """Total ray deviation (deg) through a prism of index ``n`` and apex angle ``apex_deg`` for a ray
    at first-surface angle of incidence ``incidence_deg``: delta = i1 + i2 - A, with the two-surface
    Snell chain i1->r1->(r2=A-r1)->i2. Returns None if the ray totally-internally-reflects at the exit
    face (no real i2), i.e. the apex is too large for this n / incidence to transmit."""
    A = math.radians(apex_deg)
    i1 = math.radians(incidence_deg)
    s1 = math.sin(i1) / n
    if abs(s1) > 1.0:
        return None
    r1 = math.asin(s1)
    r2 = A - r1
    s2 = n * math.sin(r2)
    if abs(s2) > 1.0:                    # TIR at the exit face -> no transmitted ray
        return None
    i2 = math.asin(s2)
    return math.degrees(i1 + i2 - A)


def prism_min_deviation(n, apex_deg):
    """Minimum deviation (deg) of a prism (index ``n``, apex ``apex_deg``), the symmetric-path value
    delta_min = 2*asin(n*sin(A/2)) - A (the inverse of n_from_min_deviation). Returns None if the
    apex is too large to transmit symmetrically (n*sin(A/2) > 1, total internal reflection)."""
    A = math.radians(apex_deg)
    x = n * math.sin(A / 2.0)
    if abs(x) > 1.0:
        return None
    return math.degrees(2.0 * math.asin(x) - A)


def n_from_min_deviation(delta_min_deg, apex_deg):
    """Refractive index from the measured minimum deviation: n = sin((A+delta_min)/2)/sin(A/2)
    (the prism-spectrometer index formula). Inverse of prism_min_deviation."""
    A = math.radians(apex_deg)
    d = math.radians(delta_min_deg)
    return math.sin((A + d) / 2.0) / math.sin(A / 2.0)


def prism_angular_dispersion(glass, apex_deg, wl_nm, dwl_nm=1.0):
    """Angular dispersion d(delta_min)/d(lambda) in deg/nm at ``wl_nm`` for a prism of ``glass`` at
    minimum deviation: a central finite difference of prism_min_deviation(sellmeier_n(lambda)).
    Negative under normal dispersion (deviation falls as wavelength rises). None near a TIR edge."""
    dm_hi = prism_min_deviation(sellmeier_n(wl_nm + dwl_nm, glass), apex_deg)
    dm_lo = prism_min_deviation(sellmeier_n(wl_nm - dwl_nm, glass), apex_deg)
    if dm_hi is None or dm_lo is None:
        return None
    return (dm_hi - dm_lo) / (2.0 * dwl_nm)


# --- Fresnel reflection (s/p amplitude + phase) -----------------------------

# complex refractive indices of common mirror metals near 633 nm
METALS = {'AL': complex(1.37, 7.62), 'AG': complex(0.14, 3.98), 'AU': complex(0.16, 3.80)}


def fresnel_reflect(n1, n2, theta_i):
    """Amplitude reflection coefficients (rs, rp) at an n1->n2 interface for angle of
    incidence theta_i (radians). n2 may be complex (a metal), giving the reflection
    phase; total internal reflection emerges from the complex cos(theta_t)."""
    ci = math.cos(theta_i)
    si = math.sin(theta_i)
    ct = cmath.sqrt(1.0 - (n1 / n2) ** 2 * si * si)      # cos(theta_t), complex-safe
    rs = (n1 * ci - n2 * ct) / (n1 * ci + n2 * ct)
    rp = (n2 * ci - n1 * ct) / (n2 * ci + n1 * ct)
    return rs, rp


# --- vectorial (3-D) polarization field -------------------------------------
# A field is a complex 3-vector evec = (cx, cy, cz) in world axes, transverse to the
# unit propagation direction. The 2-D Jones (Ex, Ey) lives in a transverse frame; this
# lets reflection at an arbitrarily-oriented mirror use the TRUE plane of incidence
# (exact off-axis Fresnel s/p), instead of assuming the Jones x/y align with s/p.

def _rnorm(v):
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / m, v[1] / m, v[2] / m) if m > 1e-12 else (0.0, 0.0, 1.0)


def _rcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _rdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def transverse_basis(d):
    """Real orthonormal (e1, e2) spanning the plane transverse to unit dir d, e1 x e2 = d.
    Deterministic in d, so collinear beams share a frame (their fields stay comparable)."""
    d = _rnorm(d)
    ref = min(((abs(d[0]), (1.0, 0.0, 0.0)), (abs(d[1]), (0.0, 1.0, 0.0)),
               (abs(d[2]), (0.0, 0.0, 1.0))), key=lambda t: t[0])[1]
    e1 = _rnorm(_rcross(ref, d))
    e2 = _rcross(d, e1)
    return e1, e2


def field_from_jones(J, d):
    """3-D complex field from a 2-D Jones (Ex, Ey) in the transverse basis of dir d."""
    e1, e2 = transverse_basis(d)
    ex, ey = J
    return (ex * e1[0] + ey * e2[0], ex * e1[1] + ey * e2[1], ex * e1[2] + ey * e2[2])


def jones_from_field(evec, d):
    """Project a 3-D complex field onto the transverse basis of dir d -> (Ex, Ey)."""
    e1, e2 = transverse_basis(d)
    ex = evec[0] * e1[0] + evec[1] * e1[1] + evec[2] * e1[2]
    ey = evec[0] * e2[0] + evec[1] * e2[1] + evec[2] * e2[2]
    return (ex, ey)


def reflect_field(evec, d_in, n, rs, rp):
    """Reflect a 3-D field at a surface with unit normal n: decompose into true s (perp to
    the plane of incidence, d x n) and p (in-plane), apply Fresnel rs/rp, and rebuild on
    the reflected direction. Returns (evec_out, d_out)."""
    d_in = _rnorm(d_in)
    n = _rnorm(n)
    dn = _rdot(d_in, n)
    d_out = _rnorm((d_in[0] - 2.0 * dn * n[0], d_in[1] - 2.0 * dn * n[1], d_in[2] - 2.0 * dn * n[2]))
    s_axis = _rcross(d_in, n)
    smag = math.sqrt(_rdot(s_axis, s_axis))
    if smag < 1e-9:                                   # normal incidence -> s/p degenerate
        s_hat = transverse_basis(d_in)[0]
    else:
        s_hat = (s_axis[0] / smag, s_axis[1] / smag, s_axis[2] / smag)
    p_in = _rcross(d_in, s_hat)
    p_out = _rcross(d_out, s_hat)
    es = evec[0] * s_hat[0] + evec[1] * s_hat[1] + evec[2] * s_hat[2]
    ep = evec[0] * p_in[0] + evec[1] * p_in[1] + evec[2] * p_in[2]
    out = (rs * es * s_hat[0] + rp * ep * p_out[0],
           rs * es * s_hat[1] + rp * ep * p_out[1],
           rs * es * s_hat[2] + rp * ep * p_out[2])
    return out, d_out


def refract_dir(d_in, n_surf, n1, n2):
    """Snell refraction of a unit propagation direction at a surface of unit normal ``n_surf``,
    from index n1 into n2 (vector form). Returns the unit refracted direction, or None on total
    internal reflection (sin(theta_t) > 1). The normal is auto-flipped to oppose the incoming ray
    (so the helper is orientation-agnostic: a port normal may point either way through the glass).

    Vector Snell:  d_t = eta*d_in + (eta*c1 - c2)*n,  eta = n1/n2,  c1 = -d.n (>0), c2 = cos(theta_t)."""
    d = _rnorm(d_in)
    nrm = _rnorm(n_surf)
    c1 = -_rdot(d, nrm)
    if c1 < 0.0:                          # normal points along the ray -> flip it to face the ray
        nrm = (-nrm[0], -nrm[1], -nrm[2])
        c1 = -c1
    eta = n1 / n2
    k = 1.0 - eta * eta * (1.0 - c1 * c1)
    if k < 0.0:                           # total internal reflection: no transmitted ray
        return None
    c2 = math.sqrt(k)
    f = eta * c1 - c2
    return _rnorm((eta * d[0] + f * nrm[0], eta * d[1] + f * nrm[1], eta * d[2] + f * nrm[2]))


def refract_field(evec, d_in, d_out, n_surf, ts, tp):
    """Transmit a 3-D field through a refracting surface: decompose into true s (perp to the plane of
    incidence, d_in x n) and p (in-plane), apply the Fresnel AMPLITUDE transmission ts/tp, and rebuild p
    transverse to the refracted direction ``d_out`` (which refract_dir supplies). Mirrors reflect_field /
    redirect_field but for transmission, keeping polarization frame-independent across the interface."""
    d_in = _rnorm(d_in)
    d_out = _rnorm(d_out)
    nrm = _rnorm(n_surf)
    s_hat = _s_hat(d_in, nrm)
    p_in = _rcross(d_in, s_hat)
    p_out = _rcross(d_out, s_hat)
    es = evec[0] * s_hat[0] + evec[1] * s_hat[1] + evec[2] * s_hat[2]
    ep = evec[0] * p_in[0] + evec[1] * p_in[1] + evec[2] * p_in[2]
    return (ts * es * s_hat[0] + tp * ep * p_out[0],
            ts * es * s_hat[1] + tp * ep * p_out[1],
            ts * es * s_hat[2] + tp * ep * p_out[2])


def fresnel_transmit_power(n1, n2, theta_i):
    """Total (s+p, unpolarized-average) Fresnel POWER transmission at an n1->n2 interface for angle of
    incidence ``theta_i`` (radians): T = 1 - (|rs|^2 + |rp|^2)/2. 0 at/beyond the critical angle (TIR).
    Used to weight the prism's transmitted segments through the entry/exit faces via the existing
    fresnel_reflect amplitudes (so the two-surface transmission is energy-consistent)."""
    rs, rp = fresnel_reflect(n1, n2, theta_i)
    Rs = abs(rs) ** 2
    Rp = abs(rp) ** 2
    return max(0.0, 1.0 - 0.5 * (Rs + Rp))


def _s_hat(d_in, n):
    """Unit s-axis (perp to the plane of incidence, d x n); transverse_basis fallback at
    normal incidence where s/p degenerate. Shared by reflect-like field transforms."""
    s_axis = _rcross(d_in, n)
    smag = math.sqrt(_rdot(s_axis, s_axis))
    if smag < 1e-9:
        return transverse_basis(d_in)[0]
    return (s_axis[0] / smag, s_axis[1] / smag, s_axis[2] / smag)


def redirect_field(evec, d_in, d_out, n, rs, rp):
    """Send a 3-D field from d_in to an arbitrary d_out lying in the SAME plane of
    incidence (a grating diffraction order; specular d_out reproduces reflect_field):
    decompose into true s (perp to the plane, d_in x n) and p (in-plane), apply rs/rp,
    rebuild p transverse to d_out. Keeps polarization frame-independent for redirected
    beams instead of rebuilding a 2-D Jones in an arbitrary transverse basis."""
    d_in = _rnorm(d_in)
    d_out = _rnorm(d_out)
    n = _rnorm(n)
    s_hat = _s_hat(d_in, n)
    p_in = _rcross(d_in, s_hat)
    p_out = _rcross(d_out, s_hat)
    es = evec[0] * s_hat[0] + evec[1] * s_hat[1] + evec[2] * s_hat[2]
    ep = evec[0] * p_in[0] + evec[1] * p_in[1] + evec[2] * p_in[2]
    return (rs * es * s_hat[0] + rp * ep * p_out[0],
            rs * es * s_hat[1] + rp * ep * p_out[1],
            rs * es * s_hat[2] + rp * ep * p_out[2])


def pbs_split(evec, d_in, n):
    """Polarizing-beamsplitter split of a 3-D field in the TRUE plane of incidence:
    the s component (field along d_in x n) REFLECTS with the unitary pi/2 phase
    (rs = i), the p component TRANSMITS unchanged. Returns (evec_reflected,
    evec_transmitted). Energy is conserved by construction: |es|^2 + |ep|^2 partitions
    the field. Carrying the split in the 3-D field keeps the relative phase
    frame-independent (platform-robust), mirroring the non-polarizing splitter."""
    ev_r, _d_out = reflect_field(evec, d_in, n, 1j, 0.0)
    s_hat = _s_hat(_rnorm(d_in), _rnorm(n))
    es = evec[0] * s_hat[0] + evec[1] * s_hat[1] + evec[2] * s_hat[2]
    ev_t = (evec[0] - es * s_hat[0], evec[1] - es * s_hat[1], evec[2] - es * s_hat[2])
    return ev_r, ev_t


# --- ABCD ray-transfer matrices + Gaussian beam q-parameter -----------------

def abcd_free(d_mm):
    return ((1.0, float(d_mm)), (0.0, 1.0))


def abcd_lens(f_mm):
    if not f_mm:
        return ((1.0, 0.0), (0.0, 1.0))
    return ((1.0, 0.0), (-1.0 / float(f_mm), 1.0))


def abcd_compose(*mats):
    """Multiply ABCD matrices left-to-right in beam order (last applied first)."""
    A = ((1.0, 0.0), (0.0, 1.0))
    for M in mats:
        a, b = A[0]
        c, d = A[1]
        e, f = M[0]
        g, h = M[1]
        A = ((e * a + f * c, e * b + f * d), (g * a + h * c, g * b + h * d))
    return A


def gaussian_divergence(w0_mm, wavelength_nm, m2=1.0):
    """Far-field (half-angle) divergence of a Gaussian beam with beam-quality M^2 (VERIFIED:
    theta = M2*lambda/(pi*w0), physics_verify ok=true). Reduces EXACTLY to the diffraction-
    limited theta = lambda/(pi*w0) at m2=1. Real waist w0 is kept; M^2 broadens the far field."""
    lam = wavelength_nm * NM_TO_MM
    return m2 * lam / (math.pi * w0_mm)


def beam_parameter_product(wavelength_nm, m2=1.0):
    """Beam-parameter product BPP = w0*theta = M2*lambda/pi (VERIFIED: physics_verify ok=true).
    Units of length*rad (== length, rad being dimensionless). M2=1 -> the diffraction limit."""
    lam = wavelength_nm * NM_TO_MM
    return m2 * lam / math.pi


def q_from_waist(w0_mm, wavelength_nm, m2=1.0):
    """Gaussian beam q at its waist: q = i*zR.

    Diffraction-limited (m2=1): zR = pi*w0^2/lambda.

    For a real beam of quality M^2 (the "times-diffraction-limit" spec) the standard
    embedded-Gaussian model keeps the true waist w0 but scales the Rayleigh range
    zR -> zR/M^2 (equivalently the divergence -> M^2 * lambda/(pi*w0), so the far-field
    w(z) broadens by exactly M^2). At m2=1 this is bit-for-bit the original q."""
    lam = wavelength_nm * NM_TO_MM
    zR = math.pi * w0_mm * w0_mm / lam
    if m2 != 1.0:
        zR /= m2
    return complex(0.0, zR)


def q_propagate(q, M):
    """q' = (A q + B) / (C q + D)."""
    (A, B), (C, D) = M
    return (A * q + B) / (C * q + D)


def beam_radius(q, wavelength_nm):
    """Spot radius w from a q-parameter: 1/q = 1/R - i*lambda/(pi w^2)."""
    lam = wavelength_nm * NM_TO_MM
    inv_imag = (1.0 / q).imag
    if inv_imag >= 0.0:
        return 0.0
    return math.sqrt(-lam / (math.pi * inv_imag))


def beam_radius_m2(q, wavelength_nm, m2=1.0):
    """Physical spot radius of an M^2 beam (B1). The tracer carries the *embedded* Gaussian
    q (waist w0/M, M=sqrt(M2)); the real beam is M times wider at every z (the M^2 invariant
    is a uniform transverse scale preserved by every ABCD operation). So the physical radius
    is w_real = M * beam_radius(q_embedded). At m2=1 this is exactly beam_radius(q) -> the
    existing diffraction-limited path is bit-for-bit unchanged. Far field: w_real(z)/z ->
    M2*lambda/(pi*w0) = gaussian_divergence(w0,lambda,M2) (physics_verify ok=true)."""
    w = beam_radius(q, wavelength_nm)
    return (math.sqrt(m2) * w) if m2 != 1.0 else w


def beam_roc(q):
    """Radius of curvature of the wavefront (inf at a waist)."""
    inv_real = (1.0 / q).real
    return (1.0 / inv_real) if abs(inv_real) > 1e-12 else float('inf')


def gouy_phase(q):
    """Gouy phase psi(z) of a fundamental Gaussian beam, from q = z + i*zR (z measured from
    the waist, zR = Im q > 0): psi = atan2(z, zR) = atan2(Re q, Im q). 0 at the waist,
    -> +-pi/2 in the far field. It is a slowly-varying *piston* (no transverse dependence),
    so within one beam it is invisible, but between two beams of different focal history it
    shifts the interference fringes (the measurable Gouy effect)."""
    return math.atan2(q.real, q.imag)


# --- 1-D aperture clips: slit + knife-edge (C5) -----------------------------
# Siblings of the verified circular-aperture clip _clip_T = 1 - exp(-2 a^2/w^2) (tracer.py): the SAME 1/e^2
# intensity-radius convention I(x) ~ exp(-2 x^2/w^2) (w = 1/e^2 radius), but a ONE-dimensional (anisotropic)
# clip along a single transverse axis. With the substitution u = sqrt(2) x / w the Gaussian's erf scale is
# sqrt(2)/w (sigma = w/2, so x/(sqrt(2) sigma) = sqrt(2) x / w) -- the sqrt(2) is in the NUMERATOR.
# physics_verify ok=true (slit 8/8, knife 8/8, physicist-python:latest) by DIRECT Gaussian integration:
#   slit:  integral_{-b}^{b} I dx / integral_{-inf}^{inf} I dx = erf(sqrt(2) b / w)
#   knife: integral_{e}^{inf} I dx / integral_{-inf}^{inf} I dx = (1/2)[1 - erf(sqrt(2)(e-xc)/w)]
# (NB: the roadmap's slit form erf(b/(sqrt(2) w)) was WRONG -- sqrt(2) in the denominator -- and inconsistent
# with its own knife formula; the oracle + the Gaussian integral confirm sqrt(2)-in-numerator. See physics_learn.)

def slit_transmission(b_mm, w_mm):
    """Power transmission of a 1-D slit of half-width ``b_mm`` (a pair of blades at +/-b) clipping a Gaussian
    of 1/e^2 intensity radius ``w_mm`` ALONG the slit's clipped axis:

        T = erf(sqrt(2) * b / w)      (VERIFIED: physics_verify ok=true 8/8)

    The fraction of a 1-D Gaussian I(x) ~ exp(-2 x^2/w^2) passing through |x| <= b. Monotone in b: T -> 0 as
    the slit closes (b -> 0) and T -> 1 as it opens (b -> inf); the half-power slit is b ~ 0.4769 w. The
    along-axis SIBLING of the circular-aperture clip 1 - exp(-2 a^2/w^2). A degenerate/zero w or b returns 1
    (no Gaussian / no blades -> nothing to clip), matching _clip_T."""
    if w_mm <= 1e-9 or b_mm <= 0.0:
        return 1.0
    return math.erf(math.sqrt(2.0) * b_mm / w_mm)


def knife_transmission(e_mm, xc_mm, w_mm):
    """Power transmitted PAST a knife-edge (half-plane blade) whose edge sits at transverse position ``e_mm``,
    cutting into a Gaussian of 1/e^2 intensity radius ``w_mm`` centered at ``xc_mm`` (the beam chief-ray on the
    clipped axis). The blade transmits the part of the beam with x > e:

        P(e) = (1/2) * [1 - erf(sqrt(2) * (e - xc) / w)]    (VERIFIED: physics_verify ok=true 8/8)

    Sweeping the edge across the beam traces the classic erf knife-edge profile: P = 1/2 at e = xc (the edge
    bisects the beam), P -> 1 as e -> -inf (blade retracted, whole beam passes), P -> 0 as e -> +inf (blade
    fully inserted). A scan.py KNIFE scan fits this curve back to the beam radius w (the 10-90% width). A
    degenerate/zero w returns 1 (no Gaussian to clip)."""
    if w_mm <= 1e-9:
        return 1.0
    return 0.5 * (1.0 - math.erf(math.sqrt(2.0) * (e_mm - xc_mm) / w_mm))


# --- Zernike wavefront (modal adaptive optics) ------------------------------
# Noll-indexed, RMS-normalized Zernike polynomials over the unit disk (j = 1..15:
# piston, tip/tilt, defocus, astigmatism, coma, trefoil, spherical, secondary astig,
# tetrafoil). The AO subsystem carries a coefficient vector (in waves) on each beam: an
# aberrator adds modes, a deformable mirror subtracts them, a wavefront sensor reads them.

_NOLL = {1: (0, 0), 2: (1, 1), 3: (1, -1), 4: (2, 0), 5: (2, -2), 6: (2, 2),
         7: (3, -1), 8: (3, 1), 9: (3, -3), 10: (3, 3), 11: (4, 0),
         12: (4, 2), 13: (4, -2), 14: (4, 4), 15: (4, -4)}
ZERNIKE_NAMES = {1: "piston", 2: "tip", 3: "tilt", 4: "defocus", 5: "astig45",
                 6: "astig0", 7: "comaY", 8: "comaX", 9: "trefoilY", 10: "trefoilX",
                 11: "spherical", 12: "2astig0", 13: "2astig45", 14: "tetra0", 15: "tetra45"}
N_ZERNIKE = 15


def _zernike_radial(n, m, rho):
    m = abs(m)
    s = 0.0
    for k in range((n - m) // 2 + 1):
        num = ((-1) ** k) * math.factorial(n - k)
        den = (math.factorial(k) * math.factorial((n + m) // 2 - k)
               * math.factorial((n - m) // 2 - k))
        s += (num / den) * rho ** (n - 2 * k)
    return s


def zernike(j, rho, theta):
    """Noll-indexed, RMS-normalized Zernike Z_j(rho, theta) on the unit disk."""
    n, m = _NOLL[j]
    norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2.0 * (n + 1))
    ang = math.cos(m * theta) if m >= 0 else math.sin(-m * theta)
    return norm * _zernike_radial(n, m, rho) * ang


def zernike_value(coeffs, rho, theta):
    """Wavefront W(rho, theta) = sum_j coeffs[j-1] * Z_j (coeffs indexed from j=1)."""
    return sum(c * zernike(i + 1, rho, theta) for i, c in enumerate(coeffs) if c)


def wavefront_rms(coeffs):
    """RMS wavefront error over the unit disk. RMS-normalized Zernikes are orthonormal, so
    RMS = sqrt(sum of squares); piston (j=1, index 0) is excluded as it is not an aberration.
    The slice + list-comprehension form is deliberate (measured ~2x over enumerate)."""
    return math.sqrt(sum([c * c for c in coeffs[1:]]))


# --- coherence --------------------------------------------------------------

def coherence_length_mm(wavelength_nm, linewidth_nm):
    """Lc = lambda^2 / d-lambda (0 linewidth -> infinite coherence)."""
    if linewidth_nm is None or linewidth_nm <= 0.0:
        return float('inf')
    lam = wavelength_nm * NM_TO_MM
    return lam * lam / (linewidth_nm * NM_TO_MM)


def cavity_finesse(R):
    """Fabry-Perot finesse from mirror (intensity) reflectivity R."""
    R = max(0.0, min(R, 0.999999))
    return math.pi * math.sqrt(R) / (1.0 - R)


def cavity_fsr_nm(wl_nm, L_mm, n=1.0):
    """Free spectral range in nm: FSR = lambda^2 / (2 n L)."""
    lam_mm = wl_nm * NM_TO_MM
    return (lam_mm * lam_mm / (2.0 * n * L_mm)) / NM_TO_MM


def airy_transmission(wl_nm, L_mm, R, n=1.0, theta=0.0):
    """Fabry-Perot Airy transmission: T = 1/(1 + F sin^2(delta/2)),
    delta = 4 pi n L cos(theta) / lambda, F = 4R/(1-R)^2."""
    R = max(0.0, min(R, 0.999999))
    lam_mm = wl_nm * NM_TO_MM
    if lam_mm <= 0.0:
        return 1.0
    delta = 4.0 * math.pi * n * L_mm * math.cos(theta) / lam_mm
    F = 4.0 * R / (1.0 - R) ** 2
    return 1.0 / (1.0 + F * math.sin(delta / 2.0) ** 2)


def fringe_envelope(opd_mm, Lc_mm):
    """Visibility envelope vs optical path difference (Gaussian coherence decay)."""
    if Lc_mm == float('inf') or Lc_mm >= 1.0e12:
        return 1.0
    if Lc_mm <= 0.0:
        return 0.0
    x = opd_mm / Lc_mm
    return math.exp(-(math.pi * x) ** 2 / 2.0)


def interfere(beams, coherence_mm=float('inf')):
    """Coherently combine beams reaching a detector from one source.

    ``beams`` is a list of (J, opl_mm, wl_nm). Returns (intensity, visibility).
    The field of each beam carries a phase 2*pi*opl/lambda; cross terms are weighted
    by the coherence envelope (OPD vs coherence length) and the polarization overlap,
    so orthogonal polarizations do not interfere and large OPDs wash fringes out.
    Visibility is the fringe contrast of the two strongest beams (-1 if < 2 beams)."""
    n = len(beams)
    if n == 0:
        return 0.0, -1.0
    fields = []
    for (J, opl, wl) in beams:
        lam_mm = wl * NM_TO_MM
        phi = (2.0 * math.pi * opl / lam_mm) if lam_mm > 0.0 else 0.0
        fields.append(with_phase(J, phi))
    total = sum(intensity(F) for F in fields)
    for i in range(n):
        for j in range(i + 1, n):
            g = fringe_envelope(abs(beams[i][1] - beams[j][1]), coherence_mm)
            dot = fields[i][0] * fields[j][0].conjugate() + fields[i][1] * fields[j][1].conjugate()
            total += 2.0 * g * dot.real
    vis = -1.0
    if n >= 2:
        order = sorted(range(n), key=lambda k: intensity(fields[k]), reverse=True)
        a, b = order[0], order[1]
        denom = intensity(fields[a]) + intensity(fields[b])
        g = fringe_envelope(abs(beams[a][1] - beams[b][1]), coherence_mm)
        Ja, Jb = beams[a][0], beams[b][0]
        overlap = abs(Ja[0] * Jb[0].conjugate() + Ja[1] * Jb[1].conjugate())
        vis = (2.0 * g * overlap / denom) if denom > 1e-12 else 0.0
    return total, vis


# --- self-test (closed-form checks) -----------------------------------------

if __name__ == "__main__":
    import sys

    def close(a, b, tol=1e-6):
        return abs(a - b) <= tol

    fails = []

    # Malus: linear @0 through polarizer @theta -> cos^2(theta)
    for th in (0.0, 30.0, 45.0, 60.0, 90.0):
        J = apply(M_polarizer(th, extinction=1e12), jones_linear(0.0))
        if not close(intensity(J), math.cos(math.radians(th)) ** 2, 1e-4):
            fails.append("Malus %g: %.4f != %.4f" % (th, intensity(J), math.cos(math.radians(th)) ** 2))

    # QWP @45 on linear @0 -> circular (|S3|/S0 ~ 1, DOP ~ 1)
    Jc = apply(M_waveplate(90.0, 45.0), jones_linear(0.0))
    ps = polarization_state(Jc)
    if ps["kind"] != "circular":
        fails.append("QWP->circular got %s" % ps["kind"])
    if not close(ps["dop"], 1.0, 1e-6):
        fails.append("QWP DOP %.4f" % ps["dop"])

    # HWP @22.5 rotates linear @0 by 45 deg
    Jh = apply(M_waveplate(180.0, 22.5), jones_linear(0.0))
    if not close(polarization_state(Jh)["azimuth_deg"], 45.0, 1e-3):
        fails.append("HWP rotation %.3f" % polarization_state(Jh)["azimuth_deg"])

    # PBS: H light fully transmits, no reflect
    Jt = apply(PBS_TRANSMIT, jones_linear(0.0))
    Jr = apply(PBS_REFLECT, jones_linear(0.0))
    if not (close(intensity(Jt), 1.0) and close(intensity(Jr), 0.0)):
        fails.append("PBS H: T=%.3f R=%.3f" % (intensity(Jt), intensity(Jr)))

    # PBS: V light fully reflects
    Jt2 = intensity(apply(PBS_TRANSMIT, jones_linear(90.0)))
    Jr2 = intensity(apply(PBS_REFLECT, jones_linear(90.0)))
    if not (close(Jt2, 0.0) and close(Jr2, 1.0)):
        fails.append("PBS V: T=%.3f R=%.3f" % (Jt2, Jr2))

    # Two-beam interference: equal beams in phase -> 4x, out of phase -> 0
    J1 = jones_linear(0.0, 1.0)
    Iin = intensity(add(J1, with_phase(J1, 0.0)))
    Iout = intensity(add(J1, with_phase(J1, math.pi)))
    if not (close(Iin, 4.0) and close(Iout, 0.0, 1e-9)):
        fails.append("interference in=%.3f out=%.3f" % (Iin, Iout))

    # ABCD: collimated beam (waist at lens) focuses at f
    w0, lam, f = 1.0, 632.8, 100.0
    q0 = q_from_waist(w0, lam)
    qf = q_propagate(q_propagate(q0, abcd_lens(f)), abcd_free(f))
    wf = beam_radius(qf, lam)
    w_expected = lam * NM_TO_MM * f / (math.pi * w0)   # diffraction-limited focal spot
    if not close(wf, w_expected, 1e-3):
        fails.append("ABCD focal spot %.5f != %.5f" % (wf, w_expected))

    # Gaussian wavefront (G7): R -> inf at the waist; R(z) = z(1+(zR/z)^2); Gouy 0 at waist,
    # -> +pi/2 far field; far-field divergence w(z) -> w0 z / zR.
    qw = q_from_waist(w0, lam)                          # at the waist
    zR = qw.imag
    if not math.isinf(beam_roc(qw)):
        fails.append("ROC at waist not inf: %.3f" % beam_roc(qw))
    if not close(gouy_phase(qw), 0.0, 1e-9):
        fails.append("Gouy at waist=%.4f" % gouy_phase(qw))
    z = 2.0 * zR                                        # two Rayleigh ranges out
    qz = q_propagate(qw, abcd_free(z))
    if not close(beam_roc(qz), z * (1.0 + (zR / z) ** 2), 1e-6):
        fails.append("ROC(z)=%.4f != %.4f" % (beam_roc(qz), z * (1.0 + (zR / z) ** 2)))
    if not close(gouy_phase(qz), math.atan2(z, zR), 1e-9):
        fails.append("Gouy(z)=%.4f" % gouy_phase(qz))
    if not (gouy_phase(q_propagate(qw, abcd_free(1000.0 * zR))) > 1.56):   # ~pi/2 far field
        fails.append("Gouy far field not ->pi/2")

    # C5 slit + knife erf clips (1-D siblings of the circular 1-exp(-2a^2/w^2); physics_verify ok=true 8/8).
    # slit T = erf(sqrt2 b/w): b=w -> 0.95450, half-power at b~0.4769w; ->1 open, ->0 closed.
    if not close(slit_transmission(1.0, 1.0), 0.9544997361036416, 1e-9):
        fails.append("slit T(b=w)=%.6f" % slit_transmission(1.0, 1.0))
    if not close(slit_transmission(0.5, 1.0), 0.6826894921370861, 1e-9):
        fails.append("slit T(b=0.5w)=%.6f" % slit_transmission(0.5, 1.0))
    if not close(slit_transmission(0.33724487509804085, 1.0), 0.5, 1e-9):    # half-power half-width b/w=erfinv(.5)/sqrt2
        fails.append("slit half-power b/w=%.6f" % slit_transmission(0.33724487509804085, 1.0))
    if not (slit_transmission(20.0, 1.0) > 0.9999999 and slit_transmission(1e-6, 1.0) < 1e-5):
        fails.append("slit open/closed limits")
    # knife P = 0.5(1-erf(sqrt2(e-xc)/w)): 1/2 at e=xc, ->1 e->-inf, ->0 e->+inf; P(e)+P(2xc-e)=1 antisymmetry.
    if not close(knife_transmission(0.0, 0.0, 1.0), 0.5, 1e-12):
        fails.append("knife P(e=xc)=%.6f" % knife_transmission(0.0, 0.0, 1.0))
    if not close(knife_transmission(0.5, 0.0, 1.0), 0.1586552539314570, 1e-9):
        fails.append("knife P(e=0.5w)=%.6f" % knife_transmission(0.5, 0.0, 1.0))
    if not close(knife_transmission(0.5, 0.0, 1.0) + knife_transmission(-0.5, 0.0, 1.0), 1.0, 1e-12):
        fails.append("knife antisymmetry P(e)+P(-e)!=1")
    if not (knife_transmission(-10.0, 0.0, 1.0) > 0.9999999 and knife_transmission(10.0, 0.0, 1.0) < 1e-9):
        fails.append("knife retracted/inserted limits")

    # Coherence: Lc for 632.8nm, 1pm linewidth ~ 0.4 m; envelope ~1 at 0 OPD
    Lc = coherence_length_mm(632.8, 1e-3)
    if not (close(fringe_envelope(0.0, Lc), 1.0) and fringe_envelope(Lc, Lc) < 0.1):
        fails.append("coherence envelope")

    # interference: two equal coherent beams -> OPD 0 gives 4x, OPD lambda/2 gives 0
    b0 = [(jones_linear(0.0, 1.0), 0.0, 633.0), (jones_linear(0.0, 1.0), 0.0, 633.0)]
    I0, V0 = interfere(b0)
    half = 633.0 * NM_TO_MM / 2.0
    b1 = [(jones_linear(0.0, 1.0), 0.0, 633.0), (jones_linear(0.0, 1.0), half, 633.0)]
    I1, _ = interfere(b1)
    if not (close(I0, 4.0, 1e-6) and close(I1, 0.0, 1e-6) and close(V0, 1.0, 1e-6)):
        fails.append("interfere I0=%.3f I_halfwave=%.3f V0=%.3f" % (I0, I1, V0))

    # orthogonal polarizations do not interfere: I = I1+I2, V = 0
    bo = [(jones_linear(0.0, 1.0), 0.0, 633.0), (jones_linear(90.0, 1.0), 0.0, 633.0)]
    Io, Vo = interfere(bo)
    if not (close(Io, 2.0, 1e-6) and close(Vo, 0.0, 1e-6)):
        fails.append("interfere orthogonal Io=%.3f Vo=%.3f" % (Io, Vo))

    # Fresnel: normal incidence |rs|=|rp|=0.2 (glass 4%); Brewster rp~0; metal 45deg s-p phase
    rs0, rp0 = fresnel_reflect(1.0, 1.5, 0.0)
    if not (close(abs(rs0), 0.2, 1e-3) and close(abs(rp0), 0.2, 1e-3)):
        fails.append("fresnel normal |rs|=%.3f |rp|=%.3f" % (abs(rs0), abs(rp0)))
    _rsb, rpB = fresnel_reflect(1.0, 1.5, math.atan(1.5))
    if abs(rpB) > 1e-3:
        fails.append("fresnel Brewster |rp|=%.4f" % abs(rpB))
    rsm, rpm = fresnel_reflect(1.0, METALS['AL'], math.radians(45.0))
    dphi = abs(cmath.phase(rsm) - cmath.phase(rpm))
    if not (abs(rsm) > 0.8 and abs(rpm) > 0.8 and dphi > 0.05):
        fails.append("metal 45deg |rs|=%.2f |rp|=%.2f dphi=%.3f" % (abs(rsm), abs(rpm), dphi))

    # dispersion: N-BK7 d-line n(587.6) ~ 1.5168, and n falls with wavelength
    if not close(sellmeier_n(587.6, 'N-BK7'), 1.5168, 2e-3):
        fails.append("sellmeier n(587.6)=%.4f" % sellmeier_n(587.6, 'N-BK7'))
    if not (sellmeier_n(450.0) > sellmeier_n(650.0)):
        fails.append("sellmeier dispersion sign")
    # new prism glasses reproduce published d-line indices (C3); cross-check vs Schott/Malitson
    for g, nd in (('N-SF11', 1.78472), ('F2', 1.62004), ('N-F2', 1.62005), ('CaF2', 1.43385)):
        if not close(sellmeier_n(587.56, g), nd, 5e-5):
            fails.append("sellmeier %s n_d=%.5f != %.5f" % (g, sellmeier_n(587.56, g), nd))

    # prism deviation: min-deviation relation round-trips, deviation -> delta_min at symmetric incidence
    for (n_test, A) in ((1.5, 60.0), (1.78472, 60.0), (1.62004, 60.0)):
        dmin = prism_min_deviation(n_test, A)
        if not close(n_from_min_deviation(dmin, A), n_test, 1e-9):
            fails.append("prism n_from_min_deviation %g" % n_test)
        # symmetric incidence i1 = (A + dmin)/2 should give exactly dmin
        i_sym = 0.5 * (A + dmin)
        if not close(prism_deviation(n_test, A, i_sym), dmin, 1e-7):
            fails.append("prism_deviation@symmetric %g: %.5f != %.5f"
                         % (n_test, prism_deviation(n_test, A, i_sym), dmin))
        # min deviation is a minimum: off-symmetric incidence deviates MORE
        if not (prism_deviation(n_test, A, i_sym + 8.0) > dmin + 1e-4
                and prism_deviation(n_test, A, i_sym - 8.0) > dmin + 1e-4):
            fails.append("prism delta_min not a minimum %g" % n_test)
    # known closed form: A=60, n=sqrt(2) -> sin((60+dmin)/2)=sqrt2*sin30=1/sqrt2 -> dmin=30 deg
    if not close(prism_min_deviation(math.sqrt(2.0), 60.0), 30.0, 1e-9):
        fails.append("prism dmin(sqrt2,60)=%.5f != 30" % prism_min_deviation(math.sqrt(2.0), 60.0))
    # angular dispersion is NEGATIVE under normal dispersion (deviation falls as lambda rises)
    if not (prism_angular_dispersion('N-SF11', 60.0, 550.0) < 0.0):
        fails.append("prism angular dispersion sign")

    # vector Snell: refract_dir obeys n1 sin t1 = n2 sin t2 and stays in the plane of incidence
    d_in = _rnorm((math.sin(math.radians(30.0)), 0.0, -math.cos(math.radians(30.0))))
    nrm = (0.0, 0.0, 1.0)                                  # air(1.0) -> glass(1.5) at 30 deg incidence
    d_t = refract_dir(d_in, nrm, 1.0, 1.5)
    t2 = math.asin(min(1.0, 1.0 * math.sin(math.radians(30.0)) / 1.5))
    if not (d_t is not None and close(math.acos(-_rdot(d_t, nrm)), t2, 1e-9)):
        fails.append("refract_dir Snell angle")
    # TIR: glass(1.5) -> air(1.0) past the critical angle returns None
    crit = math.degrees(math.asin(1.0 / 1.5))
    d_steep = _rnorm((math.sin(math.radians(crit + 5.0)), 0.0, -math.cos(math.radians(crit + 5.0))))
    if refract_dir(d_steep, (0.0, 0.0, 1.0), 1.5, 1.0) is not None:
        fails.append("refract_dir should TIR past critical angle")

    # Fabry-Perot: T=1 on resonance, small mid-FSR; finesse(R=0.9) ~ 29.8
    Lc_fp = 0.05
    t_res = airy_transmission(500.0, Lc_fp, 0.9)              # 500 nm, L=0.05 -> resonance
    t_anti = airy_transmission(500.0 + cavity_fsr_nm(500.0, Lc_fp) / 2.0, Lc_fp, 0.9)
    if not (close(t_res, 1.0, 1e-3) and t_anti < 0.05):
        fails.append("airy t_res=%.3f t_anti=%.3f" % (t_res, t_anti))
    if not close(cavity_finesse(0.9), math.pi * math.sqrt(0.9) / 0.1, 1e-6):
        fails.append("finesse=%.2f" % cavity_finesse(0.9))

    # --- vectorial (3-D) field ---------------------------------------------
    # jones <-> field round-trips exactly along any direction
    for d in ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (1.0, 1.0, 1.0)):
        J0 = jones_linear(35.0)
        J1 = jones_from_field(field_from_jones(J0, d), d)
        if not (close(J1[0].real, J0[0].real, 1e-9) and close(J1[1].real, J0[1].real, 1e-9)):
            fails.append("field roundtrip %s" % (d,))

    # Brewster: rp ~ 0, so a field with equal s & p reflects fully s-polarized
    n1b, n2b = 1.0, 1.5
    thB = math.atan2(n2b, n1b)
    rsB, rpB = fresnel_reflect(n1b, n2b, thB)
    if abs(rpB) > 1e-6:
        fails.append("Brewster |rp|=%.3g (want 0)" % abs(rpB))
    din = _rnorm((math.sin(thB), 0.0, -math.cos(thB)))   # plane of incidence = x-z
    s_hat = _rnorm(_rcross(din, (0.0, 0.0, 1.0)))         # s along y
    p_in = _rcross(din, s_hat)
    ev = (complex(s_hat[0] + p_in[0]), complex(s_hat[1] + p_in[1]), complex(s_hat[2] + p_in[2]))
    out, _dout = reflect_field(ev, din, (0.0, 0.0, 1.0), rsB, rpB)
    spow = abs(out[0] * s_hat[0] + out[1] * s_hat[1] + out[2] * s_hat[2]) ** 2
    tot = abs(out[0]) ** 2 + abs(out[1]) ** 2 + abs(out[2]) ** 2
    if tot < 1e-12 or spow / tot < 0.999:
        fails.append("Brewster reflection not s-polarized: %.4f" % (spow / max(tot, 1e-12)))

    # a metal mirror at 45 deg has a nonzero s-p phase difference, so it turns linear
    # light elliptical (the headline of exact off-axis Fresnel)
    rs45, rp45 = fresnel_reflect(1.0, METALS['AG'], math.radians(45.0))
    if abs(cmath.phase(rs45) - cmath.phase(rp45)) < 1e-3:
        fails.append("metal 45deg s-p phase ~0 (expected nonzero)")

    # an out-of-plane ideal mirror (rs=1, rp=-1) reflects without changing |field|
    ev2 = field_from_jones(jones_linear(20.0), (0.0, 0.0, 1.0))
    out2, _ = reflect_field(ev2, (0.0, 0.0, 1.0), (0.0, 0.3, 1.0), 1.0, -1.0)
    p_in_tot = abs(ev2[0]) ** 2 + abs(ev2[1]) ** 2 + abs(ev2[2]) ** 2
    p_out_tot = abs(out2[0]) ** 2 + abs(out2[1]) ** 2 + abs(out2[2]) ** 2
    if not close(p_in_tot, p_out_tot, 1e-9):
        fails.append("ideal reflect changed |field|: %.4f -> %.4f" % (p_in_tot, p_out_tot))

    # normal-incidence ideal mirror with rp=-rs preserves the lab-frame field (so two
    # interferometer arms stay co-polarized -> full fringe visibility)
    evn = field_from_jones(jones_linear(25.0), (0.0, 0.0, 1.0))
    outn, _ = reflect_field(evn, (0.0, 0.0, 1.0), (0.0, 0.0, 1.0), 1.0, -1.0)
    ov = abs(sum(outn[i] * evn[i].conjugate() for i in range(3)))
    nn = sum(abs(evn[i]) ** 2 for i in range(3))
    if nn > 1e-12 and abs(ov - nn) / nn > 1e-6:
        fails.append("normal-incidence ideal didn't preserve field: %.4f vs %.4f" % (ov, nn))

    # PBS split in the true plane of incidence: 45-deg fold, d along +x, normal in xy.
    # s = d x n = +z (vertical) reflects with phase i; p (in-plane, -y) transmits.
    dpb = _rnorm((1.0, 0.0, 0.0))
    npb = _rnorm((-1.0, 1.0, 0.0))
    powr = lambda e: sum((c * c.conjugate()).real for c in e)
    rV, tV = pbs_split((0j, 0j, 1.0 + 0j), dpb, npb)
    rH, tH = pbs_split((0j, -1.0 + 0j, 0j), dpb, npb)
    if not (close(powr(rV), 1.0) and close(powr(tV), 0.0)
            and close(powr(rH), 0.0) and close(powr(tH), 1.0)):
        fails.append("pbs_split s/p routing: V r=%.3f t=%.3f  H r=%.3f t=%.3f"
                     % (powr(rV), powr(tV), powr(rH), powr(tH)))
    if not close(cmath.phase(rV[2]), math.pi / 2.0, 1e-9):       # the unitary i on reflection
        fails.append("pbs_split reflect phase %.4f != pi/2" % cmath.phase(rV[2]))
    r45, t45 = pbs_split((0j, complex(-math.sqrt(0.5)), complex(math.sqrt(0.5))), dpb, npb)
    if not (close(powr(r45), 0.5) and close(powr(t45), 0.5)):    # 45 deg -> half/half, energy 1
        fails.append("pbs_split 45deg r=%.3f t=%.3f" % (powr(r45), powr(t45)))

    # redirect_field reproduces reflect_field exactly on the specular direction
    evx = field_from_jones(jones_linear(30.0), (0.0, 0.0, 1.0))
    refl, dofl = reflect_field(evx, (0.0, 0.0, 1.0), (0.0, 0.3, 1.0), 0.9, -0.9)
    red = redirect_field(evx, (0.0, 0.0, 1.0), dofl, (0.0, 0.3, 1.0), 0.9, -0.9)
    if not all(abs(refl[i] - red[i]) < 1e-9 for i in range(3)):
        fails.append("redirect_field != reflect_field on specular")

    # --- Zernike wavefront (adaptive optics) -------------------------------
    if not close(zernike(4, 1.0, 0.0), math.sqrt(3.0), 1e-9):        # defocus at rho=1
        fails.append("Zernike defocus(1)=%.4f" % zernike(4, 1.0, 0.0))
    if not close(zernike(4, 0.0, 0.0), -math.sqrt(3.0), 1e-9):       # defocus at rho=0
        fails.append("Zernike defocus(0)=%.4f" % zernike(4, 0.0, 0.0))
    if not close(zernike(2, 1.0, 0.0), 2.0, 1e-9):                   # tip at rho=1,theta=0
        fails.append("Zernike tip=%.4f" % zernike(2, 1.0, 0.0))
    if not close(zernike(6, 1.0, 0.0), math.sqrt(6.0), 1e-9):        # astig0 at rho=1
        fails.append("Zernike astig0=%.4f" % zernike(6, 1.0, 0.0))
    if not close(zernike(11, 1.0, 0.0), math.sqrt(5.0), 1e-9):       # spherical at rho=1
        fails.append("Zernike spherical=%.4f" % zernike(11, 1.0, 0.0))
    if not close(wavefront_rms([0, 0, 0, 0, 0.3, 0, 0, 0.4]), 0.5, 1e-9):
        fails.append("wavefront_rms != 0.5")

    def _zdot(a, b, N=140):                          # disk-average <Z_a Z_b> ~ delta_ab
        s = c = 0.0
        for ii in range(N):
            for jj in range(N):
                x = (ii + 0.5) / N * 2.0 - 1.0
                y = (jj + 0.5) / N * 2.0 - 1.0
                r = math.hypot(x, y)
                if r > 1.0:
                    continue
                th = math.atan2(y, x)
                s += zernike(a, r, th) * zernike(b, r, th)
                c += 1.0
        return s / c
    if not close(_zdot(4, 4), 1.0, 0.02):
        fails.append("Zernike norm <Z4,Z4>=%.3f" % _zdot(4, 4))
    if abs(_zdot(4, 6)) > 0.02 or abs(_zdot(2, 3)) > 0.02:
        fails.append("Zernike orthogonality")

    if fails:
        print("PHYSICS SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PHYSICS SELFTEST PASSED")
