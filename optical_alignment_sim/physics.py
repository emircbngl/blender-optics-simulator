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
    dop = math.sqrt(s1 * s1 + s2 * s2 + s3 * s3) / s0
    azimuth = 0.5 * math.degrees(math.atan2(s2, s1))
    ellipticity = 0.5 * math.degrees(math.asin(max(-1.0, min(1.0, s3 / s0))))
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

# Sellmeier coefficients (B1,B2,B3,C1,C2,C3; lambda in micron) for common glasses
GLASSES = {
    'N-BK7': (1.03961212, 0.231792344, 1.01046945, 0.00600069867, 0.0200179144, 103.560653),
    'FUSED_SILICA': (0.6961663, 0.4079426, 0.8974794, 0.0046791, 0.0135121, 97.934003),
}


def sellmeier_n(wl_nm, glass='N-BK7'):
    """Refractive index n(lambda) via the Sellmeier equation (lambda in nm)."""
    b1, b2, b3, c1, c2, c3 = GLASSES.get(glass, GLASSES['N-BK7'])
    L2 = (wl_nm * 1.0e-3) ** 2          # lambda^2 in micron^2
    n2 = 1.0 + b1 * L2 / (L2 - c1) + b2 * L2 / (L2 - c2) + b3 * L2 / (L2 - c3)
    return math.sqrt(n2) if n2 > 0.0 else 1.0


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


def q_from_waist(w0_mm, wavelength_nm):
    """Gaussian beam q at its waist: q = i*zR, zR = pi*w0^2/lambda."""
    lam = wavelength_nm * NM_TO_MM
    zR = math.pi * w0_mm * w0_mm / lam
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


def beam_roc(q):
    """Radius of curvature of the wavefront (inf at a waist)."""
    inv_real = (1.0 / q).real
    return (1.0 / inv_real) if abs(inv_real) > 1e-12 else float('inf')


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

    # Fabry-Perot: T=1 on resonance, small mid-FSR; finesse(R=0.9) ~ 29.8
    Lc_fp = 0.05
    t_res = airy_transmission(500.0, Lc_fp, 0.9)              # 500 nm, L=0.05 -> resonance
    t_anti = airy_transmission(500.0 + cavity_fsr_nm(500.0, Lc_fp) / 2.0, Lc_fp, 0.9)
    if not (close(t_res, 1.0, 1e-3) and t_anti < 0.05):
        fails.append("airy t_res=%.3f t_anti=%.3f" % (t_res, t_anti))
    if not close(cavity_finesse(0.9), math.pi * math.sqrt(0.9) / 0.1, 1e-6):
        fails.append("finesse=%.2f" % cavity_finesse(0.9))

    if fails:
        print("PHYSICS SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PHYSICS SELFTEST PASSED")
