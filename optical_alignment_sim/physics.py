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
import json
import os

NM_TO_MM = 1.0e-6


# --- Jones vectors ----------------------------------------------------------

def jones_linear(angle_deg=0.0, amp=1.0):
    """Linear polarization at ``angle_deg`` from local +x."""
    a = math.radians(angle_deg)
    return (complex(amp * math.cos(a)), complex(amp * math.sin(a)))


def jones_circular(handedness='RIGHT', amp=1.0):
    """Circular polarization. RIGHT = (1, i)/sqrt2, LEFT = (1, -i)/sqrt2.

    CONVENTION (label, not physics): here RIGHT == (1, i) == Stokes S3 > 0 under the e^{-i w t} time
    convention. Some optics texts (Born & Wolf) call this state LEFT-handed; the choice is a naming
    convention and the labeling is SELF-CONSISTENT throughout this module -- jones_circular, the S3
    sign (stokes), and the RCP/LCP analyzer projectors all agree -- so every intensity / DOP /
    ellipticity is correct regardless. Only cross-check the *name* against a text using the same
    e^{-i w t} convention."""
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


def stokes_dofp(J):
    """Single-shot LINEAR Stokes from a DIVISION-OF-FOCAL-PLANE micropolarizer array -- a per-pixel
    polarization CCD/CMOS (e.g. Sony Polarsens). Four micro-analyzers at 0/45/90/135 deg measure
    I0/I45/I90/I135 (Malus); the linear Stokes are reconstructed EXACTLY (== stokes()'s S0/S1/S2):
        S0 = I0 + I90,  S1 = I0 - I90,  S2 = I45 - I135,
        DoLP = sqrt(S1^2 + S2^2) / S0,  AoLP = 0.5*atan2(S2, S1).
    A DoFP camera reads ONLY the linear Stokes in one shot -- S3 (circular) needs an added retarder, so
    DoLP/AoLP is its native output. Reuses the verified M_polarizer / intensity kernels; the S0/S1/S2
    reconstruction is identical to stokes(J)[:3] (proven in the regression). Returns the four raw
    micro-analyzer intensities + reconstructed {S0, S1, S2, dolp, aolp_deg}."""
    i0 = intensity(apply(M_polarizer(0.0), J))
    i45 = intensity(apply(M_polarizer(45.0), J))
    i90 = intensity(apply(M_polarizer(90.0), J))
    i135 = intensity(apply(M_polarizer(135.0), J))
    s0, s1, s2 = i0 + i90, i0 - i90, i45 - i135
    dolp = (math.sqrt(s1 * s1 + s2 * s2) / s0) if s0 > 1e-15 else 0.0
    aolp = 0.5 * math.degrees(math.atan2(s2, s1))
    return {"I0": i0, "I45": i45, "I90": i90, "I135": i135,
            "S0": s0, "S1": s1, "S2": s2, "dolp": dolp, "aolp_deg": aolp}


# --- Mueller calculus (4x4 real) -- Stokes -> Stokes, the counterpart of the 2x2 Jones matrices above.
# Unlike Jones, Mueller can carry PARTIALLY-polarized / depolarizing light (DOP < 1). Same S3 sign
# convention as stokes(J) (S3 = -2 Im(ex ey*)) -- verified to agree with the Jones path for pure states.

def M_mueller_polarizer(axis_deg=0.0):
    """Ideal linear polarizer as a 4x4 Mueller matrix, transmission axis at ``axis_deg``. Row 0 is
    0.5*[1, cos2t, sin2t, 0] -> Malus's law: a fully-polarized input emerges with I = I0 cos^2(theta_rel)."""
    c = math.cos(2.0 * math.radians(axis_deg))
    s = math.sin(2.0 * math.radians(axis_deg))
    return (
        (0.5, 0.5 * c, 0.5 * s, 0.0),
        (0.5 * c, 0.5 * c * c, 0.5 * c * s, 0.0),
        (0.5 * s, 0.5 * c * s, 0.5 * s * s, 0.0),
        (0.0, 0.0, 0.0, 0.0),
    )


def M_mueller_retarder(retardance_deg=180.0, fast_axis_deg=0.0):
    """Linear retarder (HWP=180, QWP=90) as a 4x4 Mueller matrix, fast axis at ``fast_axis_deg``. A QWP at
    0 deg is [[1,0,0,0],[0,1,0,0],[0,0,0,-1],[0,0,1,0]] and at 45 deg turns horizontal-linear into circular
    (S -> (S0,0,0,-S0)). NB the S3 sign follows this module's stokes(J) convention (S3 = -2 Im(ex ey*)), so a
    Mueller retarder and the Jones M_waveplate produce the SAME output Stokes for pure states (verified) --
    that consistency is kept even though it flips the circular handedness vs some textbook/library tables."""
    c = math.cos(2.0 * math.radians(fast_axis_deg))
    s = math.sin(2.0 * math.radians(fast_axis_deg))
    cd = math.cos(math.radians(retardance_deg))
    sd = -math.sin(math.radians(retardance_deg))      # -sin: match the stokes() S3 = -2 Im convention
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, c * c + s * s * cd, c * s * (1.0 - cd), -s * sd),
        (0.0, c * s * (1.0 - cd), s * s + c * c * cd, c * sd),
        (0.0, s * sd, -c * sd, cd),
    )


def stokes_through(M, S):
    """Apply a 4x4 Mueller matrix ``M`` to a Stokes 4-vector ``S`` -> the output Stokes 4-vector."""
    return tuple(sum(M[i][j] * S[j] for j in range(4)) for i in range(4))


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
    # --- additional catalog glasses (SCHOTT Zemax 2017 fits via refractiveindex.info, CC0) -------------
    'N-SF6': (1.77931763, 0.338149866, 2.08734474, 0.0133714182, 0.0617533621, 174.01759),
    'N-LAK22': (1.14229781, 0.535138441, 1.04088385, 0.00585778594, 0.0198546147, 100.834017),
    'N-SF2': (1.47343127, 0.163681849, 1.36920899, 0.0109019098, 0.0585683687, 127.404933),
    # --- IR / special materials (literature Sellmeier via refractiveindex.info, CC0) -------------------
    'ZnSe': (4.45813734, 0.467216334, 2.89566290, 0.0403446805, 0.15317139, 2221.82237),      # Connolly 1979, 0.54-18.2um
    'GE': (0.4886331, 14.5142535, 0.0091224, 1.393959, 0.1626427, 752.190),                   # Burnett 2016, 2-14um
    'SI': (10.6684293, 0.0030434748, 1.54133408, 0.0909121907, 1.28766017, 1218816.0),        # Salzberg 1957, 1.36-11um
    'BaF2': (0.643356, 0.506762, 3.8261, 0.00333956852, 0.0120297024, 2151.6981),             # Malitson 1964, 0.27-10.3um
    # --- birefringent crystals: ordinary (n_o) + extraordinary (n_e). C3=0 folds Ghosh's constant A
    #     into a third term (lambda^2/(lambda^2-0)=1 -> contributes B3). Used as waveplate/polarizer stock.
    'QUARTZ_O': (1.07044083, 1.10202242, 0.28604141, 1.00585997e-2, 100.0, 0.0),              # alpha-SiO2, Ghosh 1999
    'QUARTZ_E': (1.09509924, 1.15662475, 0.28851804, 1.02101864e-2, 100.0, 0.0),
    'CALCITE_O': (0.96464345, 1.82831454, 0.73358749, 1.94325203e-2, 120.0, 0.0),             # CaCO3, Ghosh 1999
    'CALCITE_E': (0.82427830, 0.14429128, 0.35859695, 1.06689543e-2, 120.0, 0.0),
    'MGF2_O': (0.48755108, 0.39875031, 2.3120353, 0.04338408 ** 2, 0.09461442 ** 2, 23.793604 ** 2),   # Dodge 1984
    'MGF2_E': (0.41344023, 0.50497499, 2.4904862, 0.03684262 ** 2, 0.09076162 ** 2, 23.771995 ** 2),
    'SAPPHIRE_O': (1.4313493, 0.65054713, 5.3414021, 0.0726631 ** 2, 0.1193242 ** 2, 18.028251 ** 2),   # Al2O3, Malitson 1972
    'SAPPHIRE_E': (1.5039759, 0.55069141, 6.5927379, 0.0740288 ** 2, 0.1216529 ** 2, 20.072248 ** 2),
}

# Thermo-optic coefficient dn/dT [1/K], RELATIVE to air, near the d-line at ~20 C. Tier-1 datasheet
# constants (SCHOTT TIE-19; Corning 7980 for fused silica). The absolute-vs-relative and the lambda,T
# dependence are a real ~1e-6/K spread, so these are REPRESENTATIVE, not exact. CaF2 is NEGATIVE (the
# athermalizing material). Materials absent here contribute no thermal shift.
DNDT = {
    'N-BK7': 2.4e-6, 'FUSED_SILICA': 1.0e-5, 'N-SF11': 1.9e-6,
    'F2': 4.4e-6, 'N-F2': 3.5e-6, 'CaF2': -10.6e-6,
}
DNDT_T0_C = 20.0

# Transparency / Sellmeier-fit VALIDITY window (micron) per glass -- the range over which the published fit
# reproduces the measured index. sellmeier_n SILENTLY CLAMPS outside this (so a sweep step stays finite); this
# table lets sellmeier_in_range() flag an out-of-window query as an honesty signal WITHOUT changing the
# (byte-identical) numeric output. Ranges from the same datasheet sources as the Sellmeier coefficients.
GLASS_RANGE_UM = {
    'N-BK7': (0.30, 2.50), 'FUSED_SILICA': (0.21, 3.71), 'N-SF11': (0.37, 2.50), 'F2': (0.32, 2.50),
    'N-F2': (0.33, 2.50), 'CaF2': (0.23, 9.70), 'N-SF6': (0.37, 2.50), 'N-LAK22': (0.33, 2.50),
    'N-SF2': (0.37, 2.50), 'ZnSe': (0.54, 18.2), 'GE': (2.0, 14.0), 'SI': (1.36, 11.0), 'BaF2': (0.27, 10.3),
    'QUARTZ_O': (0.20, 2.05), 'QUARTZ_E': (0.20, 2.05), 'CALCITE_O': (0.20, 2.17), 'CALCITE_E': (0.20, 2.17),
    'MGF2_O': (0.20, 7.0), 'MGF2_E': (0.20, 7.0), 'SAPPHIRE_O': (0.20, 5.5), 'SAPPHIRE_E': (0.20, 5.5),
}


# --- user-extensible glass catalog -----------------------------------------------------------------
# The BUILTIN GLASSES above are always present. A user (or the AI) can ADD glasses without editing code
# by writing a cache/glasses_user.json ({name: [B1,B2,B3,C1,C2,C3]}); they are merged on top at load.
# In a bare interpreter (CI self-test) there is no cache path, so the merge is a no-op -> byte-identical.

def _user_glasses_path():
    """The user glass-catalog JSON in the add-on cache (Blender only; None in bare Python)."""
    try:
        import bpy
        d = bpy.utils.extension_path_user(__package__, path="cache", create=True)
        return os.path.join(d, "glasses_user.json")
    except Exception:
        return None


def _merge_glasses():
    merged = dict(GLASSES)
    p = _user_glasses_path()
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            for name, c in data.items():
                if isinstance(c, (list, tuple)) and len(c) == 6:
                    merged[name] = tuple(float(x) for x in c)
        except (OSError, ValueError, TypeError):
            pass
    return merged


_GLASSES = _merge_glasses()        # the live lookup sellmeier_n reads (BUILTIN + user)


def reload_glasses():
    """Re-read the user catalog into the live lookup. Returns the sorted glass names."""
    global _GLASSES
    _GLASSES = _merge_glasses()
    return sorted(_GLASSES)


def glass_names():
    """All glass names currently available (BUILTIN + any user-added)."""
    return sorted(_GLASSES)


def add_user_glass(name, coeffs):
    """Add/update a user glass: name -> 6 Sellmeier coeffs (B1,B2,B3,C1,C2,C3) into the LIVE lookup
    immediately, AND persist it to the cache JSON when a writable cache exists. Returns True if persisted
    to disk, False if it is in-memory only (bare interpreter / no cache) -- usable either way this session.
    Bad input (not 6 coeffs) returns False without touching the lookup."""
    if not (isinstance(coeffs, (list, tuple)) and len(coeffs) == 6):
        return False
    tup = tuple(float(x) for x in coeffs)
    _GLASSES[name] = tup                        # live immediately, even with no persistence
    p = _user_glasses_path()
    if not p:
        return False
    data = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data[name] = list(tup)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except OSError:
        return False
    return True


def import_glass(name, coefficients, formula=2, ref_wl_nm=587.56, ref_n=None):
    """Add a glass from refractiveindex.info-style Sellmeier coefficients (the robust core of an RII
    importer -- an agent fetches the YAML's `coefficients` + `type`, this does the conversion + sanity
    check + persistence). `coefficients` is the RII list [c0, B1, C1, B2, C2, B3, C3]; formula 1 -> the
    C entries are resonance WAVELENGTHS (we square them to our Cj=lambda_j^2), formula 2 -> already
    squared. Requires c0==0 and <=3 poles (other RII formula types are rejected, not silently fudged).
    If ref_n is given, n(ref_wl) must match within 1e-3 or the conversion is rejected. Persists via
    add_user_glass (Blender only). Returns {ok, name, coeffs, n_at_ref, persisted} or {ok:False, error}."""
    c = list(coefficients)
    if not c or float(c[0]) != 0.0:
        return {"ok": False, "error": "needs a Sellmeier fit with c0=0 (got c0=%s)" % (c[0] if c else None)}
    pairs = c[1:]
    if len(pairs) % 2 != 0 or len(pairs) // 2 > 3 or not pairs:
        return {"ok": False, "error": "need 1-3 (B,C) coefficient pairs, got %d values" % len(pairs)}
    bb, cc = [], []
    for i in range(0, len(pairs), 2):
        bb.append(float(pairs[i]))
        cj = float(pairs[i + 1])
        cc.append(cj * cj if int(formula) == 1 else cj)
    while len(bb) < 3:
        bb.append(0.0)
        cc.append(1.0)                       # a zero-B padding term contributes nothing
    tup = (bb[0], bb[1], bb[2], cc[0], cc[1], cc[2])
    n_ref = None
    if ref_n is not None:
        L2 = (ref_wl_nm * 1.0e-3) ** 2
        try:
            n2 = 1.0 + sum(bb[j] * L2 / (L2 - cc[j]) for j in range(3))
            n_ref = math.sqrt(n2) if n2 > 0.0 else None
        except ZeroDivisionError:
            n_ref = None
        if n_ref is None or abs(n_ref - ref_n) > 1.0e-3:
            return {"ok": False, "error": "n(%.2f)=%s != expected %s -- conversion rejected" % (ref_wl_nm, n_ref, ref_n),
                    "coeffs": tup}
    persisted = add_user_glass(name, tup)
    return {"ok": True, "name": name, "coeffs": tup, "n_at_ref": n_ref, "persisted": persisted}


def sellmeier_n(wl_nm, glass='N-BK7', temp_C=None):
    """Refractive index n(lambda) via the Sellmeier equation (lambda in nm).

    With temp_C given, adds the thermo-optic shift n_eff = n(lambda) + dn/dT*(T - 20 C) using the
    glass's DNDT coefficient (0 if unknown). temp_C=None -> the pure dispersive index (and temp_C=20
    is a no-op since dn/dT*(20-20)=0), so existing scenes are unaffected."""
    b1, b2, b3, c1, c2, c3 = _GLASSES.get(glass, _GLASSES['N-BK7'])
    L2 = (wl_nm * 1.0e-3) ** 2          # lambda^2 in micron^2
    n2 = 1.0 + b1 * L2 / (L2 - c1) + b2 * L2 / (L2 - c2) + b3 * L2 / (L2 - c3)
    # The Sellmeier fit is only valid across its transparency window. Between/under poles it swings
    # (n2<0, or absurd just past one); clamp to the nearest physical bound so an out-of-window sweep
    # step yields a sane index. Upper bound raised to n~5 to admit IR Ge/Si/ZnSe (n_Ge ~ 4.0).
    if not (0.0 < n2 < 25.0):
        n = 1.0 if n2 <= 1.0 else 5.0
    else:
        n = math.sqrt(n2)
    if temp_C is not None:
        n += DNDT.get(glass, 0.0) * (temp_C - DNDT_T0_C)
    return n


def sellmeier_in_range(wl_nm, glass='N-BK7'):
    """True if wl_nm is within the glass's published Sellmeier-fit validity window (GLASS_RANGE_UM). Outside
    it, sellmeier_n still returns a clamped value -- this is the honesty flag that it is an EXTRAPOLATION, not
    a measured index. Unknown glasses (no range on file) return True (no claim either way)."""
    rng = GLASS_RANGE_UM.get(glass)
    if rng is None:
        return True
    lam_um = wl_nm * 1.0e-3
    return rng[0] <= lam_um <= rng[1]


# --- closed-form helpers for textbook validation (pure scalar functions) ----
# Each is the standard relation exposed as a number so it can be checked DIRECTLY
# against a textbook value (and physics_verify'd). Angles in DEGREES at this boundary.

def critical_angle(n1, n2):
    """Total-internal-reflection critical angle theta_c = asin(n2/n1), in degrees.
    None when n2 >= n1 (no TIR going into the denser/equal medium)."""
    if n1 <= 0.0 or n2 >= n1:
        return None
    return math.degrees(math.asin(n2 / n1))


def brewster_angle(n1, n2):
    """Brewster (polarizing) angle theta_B = atan(n2/n1), in degrees (p-reflectance -> 0)."""
    return math.degrees(math.atan(n2 / n1))


# --- uniaxial-crystal optics (the o/e index data lives in GLASSES as *_O / *_E pairs) ----
# These turn the ordinary/extraordinary indices already in the Sellmeier catalog (QUARTZ/CALCITE/MGF2/
# SAPPHIRE _O,_E) into the textbook anisotropic-ray numbers. Pure scalar, angles in DEGREES.

def n_e_theta(n_o, n_e, theta_deg):
    """Extraordinary-ray index of a UNIAXIAL crystal at angle theta from the optic axis, via the index
    ellipsoid:  1/n_e(theta)^2 = cos^2(theta)/n_o^2 + sin^2(theta)/n_e^2.  theta=0 -> n_o (propagation
    ALONG the optic axis sees the ordinary index), theta=90 -> n_e. (Yariv & Yeh, 'Optical Waves in
    Crystals'.) This is the e-ray index used by the walk-off and SHG-phase-match relations below."""
    th = math.radians(theta_deg)
    return 1.0 / math.sqrt(math.cos(th) ** 2 / n_o ** 2 + math.sin(th) ** 2 / n_e ** 2)


def uniaxial_walkoff_angle(n_o, n_e, theta_deg):
    """Double-refraction WALK-OFF angle rho between the extraordinary ray's Poynting vector (energy flow)
    and its wavevector, theta measured from the optic axis (Yariv & Yeh):
        tan(rho) = (n_o^2 - n_e^2) tan(theta) / (n_o^2 + n_e^2 tan^2(theta)).
    Returns rho in degrees; 0 at theta=0 and theta=90, max near theta~45. (Sign: + for n_o>n_e, a positive
    uniaxial walks the other way.) e.g. calcite at 45 deg (n_o=1.6584, n_e=1.4864) -> 6.22 deg."""
    t = math.tan(math.radians(theta_deg))
    return math.degrees(math.atan((n_o ** 2 - n_e ** 2) * t / (n_o ** 2 + n_e ** 2 * t ** 2)))


def oe_split_geometry(d_in, axis, n_o, n_e):
    """Geometry of ORDINARY / EXTRAORDINARY double refraction in a uniaxial crystal. Given the unit
    propagation direction ``d_in`` and the crystal optic axis ``axis`` (unit, world frame), return
    ``(theta_deg, rho_deg, pol_o, pol_e, walk_dir)``:

      - theta_deg : angle of the wave to the optic axis (0 = along the axis -> no splitting).
      - rho_deg   : the extraordinary walk-off angle (``uniaxial_walkoff_angle``); the e-ray's Poynting
                    vector drifts off its wavevector by rho. Inside a slab of thickness L the e-beam emerges
                    laterally displaced by ``L * tan(rho)`` along ``walk_dir`` and PARALLEL to the input (the
                    textbook calcite double image -- the displacement is fixed by L, independent of the screen
                    distance), so the tracer offsets the e-child's emission point rather than tilting it.
      - pol_o     : ordinary polarization, PERPENDICULAR to the principal plane (the plane of d_in and axis).
      - pol_e     : extraordinary polarization, IN the principal plane and transverse to d_in.
      - walk_dir  : the transverse direction (in the principal plane) the e-ray walks toward -- toward the
                    optic-axis projection. (pol_e and walk_dir share the same line; walk_dir fixes the sign.)

    Degenerates gracefully to rho=0 / walk_dir=(0,0,0) when d_in is along the optic axis. Pure geometry; the
    power split onto pol_o / pol_e (Malus on the eigen-axes) is the caller's job from the incident field."""
    d = _rnorm(d_in)
    a = _rnorm(axis)
    ad = _rdot(d, a)
    cos_th = min(1.0, abs(ad))
    theta = math.degrees(math.acos(cos_th))
    rho = uniaxial_walkoff_angle(n_o, n_e, theta)
    oc = _rcross(d, a)                                   # normal to the principal plane (d, a)
    if math.sqrt(oc[0] ** 2 + oc[1] ** 2 + oc[2] ** 2) < 1.0e-9:   # d || a: principal plane undefined
        e1, _e2 = transverse_basis(d)
        return 0.0, 0.0, e1, _e2, (0.0, 0.0, 0.0)
    pol_o = _rnorm(oc)                                   # ordinary: perpendicular to the principal plane
    pol_e = _rnorm(_rcross(pol_o, d))                    # extraordinary: in-plane, transverse to d
    at = (a[0] - ad * d[0], a[1] - ad * d[1], a[2] - ad * d[2])    # transverse component of the optic axis
    walk = pol_e if _rdot(pol_e, at) >= 0.0 else (-pol_e[0], -pol_e[1], -pol_e[2])   # toward the axis
    return theta, rho, pol_o, pol_e, walk


def waveplate_thickness(order, wl_nm, dn):
    """Physical thickness d of a true ZERO-ORDER waveplate giving the requested retardance order at wl_nm,
    from the crystal birefringence dn = |n_e - n_o|:  d = order * lambda / dn  (order = 0.25 quarter-wave,
    0.5 half-wave). Returns mm. e.g. quartz QWP @589.3 nm (dn=0.00910) -> 0.01619 mm = 16.19 um."""
    if dn <= 0.0:
        return float('inf')
    return order * (wl_nm * 1.0e-6) / dn          # wl nm->mm (x1e-6); d in mm


def abbe_number(glass='N-BK7'):
    """Abbe number Vd = (nd-1)/(nF-nC) at the d (587.56), F (486.13), C (656.27 nm) lines."""
    nd = sellmeier_n(587.56, glass)
    nF = sellmeier_n(486.13, glass)
    nC = sellmeier_n(656.27, glass)
    denom = nF - nC
    return (nd - 1.0) / denom if abs(denom) > 1e-12 else float('inf')


def thin_lens_image(f, o):
    """Thin-lens imaging 1/o + 1/i = 1/f. Returns (image_distance i, magnification m = -i/o).
    (None, None) when the object sits at the focus (image at infinity)."""
    inv_i = 1.0 / f - 1.0 / o
    if abs(inv_i) < 1e-12:
        return (None, None)
    i = 1.0 / inv_i
    return (i, -i / o)


def cavity_stability(g1, g2):
    """Two-mirror resonator stability (g_i = 1 - L/R_i). Returns (g1*g2, stable?).
    Stable iff 0 <= g1*g2 <= 1 (Saleh & Teich / Siegman)."""
    g = g1 * g2
    return (g, 0.0 <= g <= 1.0)


def grating_angle(lines_per_mm, m, wl_nm, theta_i_deg=0.0):
    """Diffraction-grating angle: sin(theta_m) = sin(theta_i) + m*lambda/d, d = 1/lines_per_mm.
    Returns the diffracted angle in degrees, or None if the order is evanescent (|sin| > 1)."""
    d_mm = 1.0 / lines_per_mm
    s = math.sin(math.radians(theta_i_deg)) + m * (wl_nm * 1.0e-6) / d_mm   # wl: nm -> mm
    if abs(s) > 1.0:
        return None
    return math.degrees(math.asin(s))


def grating_resolving_power(lines_per_mm, illuminated_mm, m):
    """Grating chromatic resolving power R = m*N (N = total illuminated grooves). Resolvable d-lambda = lambda/R."""
    return m * lines_per_mm * illuminated_mm


def ar_quarter_wave_reflectance(n0, n1, ns):
    """Single quarter-wave AR layer (index n1) on substrate ns in medium n0:
    R = ((n0*ns - n1^2)/(n0*ns + n1^2))^2 (Born & Wolf 1.6.2). Zero when n1 = sqrt(n0*ns)."""
    den = n0 * ns + n1 * n1
    return ((n0 * ns - n1 * n1) / den) ** 2 if den != 0.0 else 0.0


def abcd_surface(n1, n2, R_mm):
    """Refraction at one curved dielectric surface (radius R_mm, sign per the usual lensmaker convention):
    ABCD = [[1, 0], [-(n2-n1)/(n2*R), n1/n2]]. R_mm=0/inf -> a flat interface (no power)."""
    power = 0.0 if (R_mm == 0.0 or R_mm == float('inf')) else (n2 - n1) / (n2 * R_mm)
    return ((1.0, 0.0), (-power, n1 / n2))


def abcd_thick_lens(n, R1_mm, R2_mm, t_mm, n_medium=1.0):
    """ABCD of a thick lens: surf(n_med,n,R1) then free(t) then surf(n,n_med,R2). EFL = -1/C of the result;
    reproduces the thick lensmaker 1/f = (n-1)[1/R1 - 1/R2 + (n-1)t/(n R1 R2)] to machine precision."""
    def _mul(A, B):
        return ((A[0][0] * B[0][0] + A[0][1] * B[1][0], A[0][0] * B[0][1] + A[0][1] * B[1][1]),
                (A[1][0] * B[0][0] + A[1][1] * B[1][0], A[1][0] * B[0][1] + A[1][1] * B[1][1]))
    s1 = abcd_surface(n_medium, n, R1_mm)
    fr = ((1.0, t_mm), (0.0, 1.0))
    s2 = abcd_surface(n, n_medium, R2_mm)
    return _mul(s2, _mul(fr, s1))            # ray order: s1 -> free -> s2


def photon_energy_eV(wl_nm):
    """Photon energy E = hc/lambda in eV (hc/e = 1239.84198 eV*nm)."""
    return 1239.84198 / wl_nm


def fiber_na(n_core, n_clad):
    """Step-index fiber numerical aperture NA = sqrt(n_core^2 - n_clad^2)."""
    return math.sqrt(max(n_core * n_core - n_clad * n_clad, 0.0))


def fiber_v_number(core_radius_um, na, wl_nm):
    """Normalized frequency V = 2*pi*a*NA/lambda (single-mode iff V < 2.405)."""
    return 2.0 * math.pi * core_radius_um * na / (wl_nm * 1.0e-3)    # a um, lambda nm->um


def fiber_num_modes(v):
    """Approximate guided-mode count in a step-index fiber, M ~ V^2/2."""
    return v * v / 2.0


def aom_deflection(wl_nm, f_acoustic_hz, v_sound_mps):
    """Acousto-optic full deflection angle theta = lambda*f/v_s (= 2*Bragg), in radians."""
    return (wl_nm * 1.0e-9) * f_acoustic_hz / v_sound_mps


def pockels_vpi(wl_nm, n0, r_pm_per_V):
    """Longitudinal Pockels half-wave voltage Vpi = lambda/(2*n0^3*r), r in pm/V -> volts."""
    return (wl_nm * 1.0e-9) / (2.0 * n0 ** 3 * r_pm_per_V * 1.0e-12)


# --- thermal / mechanical CLOSED-FORM ESTIMATES (Tier-1; not simulated in the trace) ----------------
# These are honest order-of-magnitude calculators for effects the geometric trace does NOT model: a hot
# optic's thermal lens, clamp/thermal-stress birefringence, and gravity sag. They let the AI ESTIMATE a
# magnitude; the full thermal-field / stress / deflection simulation stays out of scope (not faked).

def thermal_lens_focal_length(p_abs_W, dn_dT, kappa_W_mK, w_mm):
    """Thermal-lens focal length f = 2*pi*kappa*w^2/(P_abs*dn/dT), mm (steady-state Gaussian-heated rod).
    P_abs = absorbed power [W], kappa = thermal conductivity [W/(m.K)], w = beam radius [mm]. ESTIMATE."""
    denom = p_abs_W * dn_dT
    if denom == 0.0:
        return float('inf')
    return 2.0 * math.pi * kappa_W_mK * (w_mm * 1.0e-3) ** 2 / denom * 1.0e3      # m -> mm


def photoelastic_retardance_nm(stress_Pa, stress_optic_C, path_mm):
    """Stress-induced retardance OPD = C*sigma*L (the stress-optic law), nm. C [1/Pa], sigma [Pa], path
    [mm]. ESTIMATE of clamp / thermal-stress birefringence (fused silica C ~ 3.5e-12 /Pa)."""
    return stress_optic_C * stress_Pa * (path_mm * 1.0e-3) * 1.0e9                # m -> nm


def cantilever_sag_nm(mass_kg, length_m, youngs_Pa, area_moment_m4):
    """End-loaded cantilever tip deflection delta = m*g*L^3/(3*E*I), nm (g = 9.81). ESTIMATE of gravity
    sag of a tip mass on a post/arm; second moment I = pi*r^4/4 for a round rod of radius r."""
    if youngs_Pa == 0.0 or area_moment_m4 == 0.0:
        return float('inf')
    return mass_kg * 9.81 * length_m ** 3 / (3.0 * youngs_Pa * area_moment_m4) * 1.0e9   # m -> nm


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


# --- chi(2) nonlinear frequency conversion (energy/photon-frequency conservation) ----
# Every chi(2) child wavelength is fixed by ENERGY conservation on the photon frequencies
# (omega = 2*pi*c/lambda, so 1/lambda is proportional to the photon energy). The relations
# below are pure energy conservation -- index-light, exact, and each oracle-VERIFIED
# (tests/_verify_nlcrystal.py, physics_verify ok=true):
#   SHG  l3 = l1/2           (f3 = 2*f1)                shg-energy-conservation, 4/4
#   THG  l3 = l1/3           (f3 = 3*f1)                thg-energy-conservation, 3/3
#   SFG  1/l3 = 1/l1 + 1/l2  (f3 = f1 + f2)             sfg-energy-conservation, 4/4
#   DFG  1/l3 = 1/l1 - 1/l2  (f3 = f1 - f2)             dfg-energy-conservation, 3/3
#   OPO  1/lp = 1/ls + 1/li  (fp = fs + fi -> idler)    opo-energy-conservation, 3/3
#   SPDC degenerate l3 = 2*l1 (the OPO special case ls=li=2*lp; the inverse of SHG).

def nl_child_wavelength(process, l1, l2=None):
    """The energy-conserving child wavelength (nm) emitted by a chi(2) crystal for a pump at
    ``l1`` (and a second input ``l2`` for the two-input SFG/DFG/OPO processes).

    All relations are exact photon-frequency conservation (oracle-VERIFIED; see the card names
    above). For OPO ``l1`` is the pump lambda_p and ``l2`` the seeded signal lambda_s; the return
    is the idler lambda_i. Returns None when the relation has no positive (physical) solution
    (e.g. DFG/OPO with the inputs swapped so 1/l3 would be <= 0)."""
    p = (process or 'NONE').upper()
    if p == 'SHG':
        return l1 * 0.5                          # f3 = 2 f1   -> l3 = l1/2
    if p == 'THG':
        return l1 / 3.0                          # f3 = 3 f1   -> l3 = l1/3
    if p == 'SPDC':
        return l1 * 2.0                          # degenerate down-conversion (inverse SHG)
    if p == 'SFG':
        if not l2:
            return None
        inv = 1.0 / l1 + 1.0 / l2                # f3 = f1 + f2
        return 1.0 / inv if inv > 0.0 else None
    if p == 'DFG':
        if not l2:
            return None
        inv = 1.0 / l1 - 1.0 / l2                # f3 = f1 - f2 (l1 is the higher-frequency input)
        return 1.0 / inv if inv > 1e-12 else None
    if p == 'OPO':
        if not l2:
            return None
        inv = 1.0 / l1 - 1.0 / l2                # 1/li = 1/lp - 1/ls (l1=pump, l2=signal)
        return 1.0 / inv if inv > 1e-12 else None
    return None


def phase_match_efficiency(dk_per_mm, L_mm):
    """The sinc^2 phase-matching factor sinc^2(dk*L/2) = (sin(x)/x)^2 with x = dk*L/2 -- the
    physically central, temperature-tunable part of the chi(2) conversion efficiency. =1 at
    perfect phase match (dk=0, x->0), first zero at x=pi (dk*L=2*pi). Normalized (un-normalized)
    sinc, numpy-free. Oracle-VERIFIED (phase-match-sinc2-efficiency, 6/6 ok=true)."""
    x = 0.5 * dk_per_mm * L_mm
    if abs(x) < 1e-12:
        return 1.0                               # lim_{x->0} (sin x / x)^2 = 1 (perfect phase match)
    s = math.sin(x) / x
    return s * s


def nl_conversion_efficiency(deff_pm_V, L_mm, P_W, dk_per_mm=0.0,
                             prefactor=2.0e-4, deplete=True):
    """Low-conversion chi(2) efficiency eta ~ deff^2 * L^2 * P * sinc^2(dk*L/2), clamped into the
    pump-depletion regime via tanh^2(sqrt(eta)) when ``deplete`` (so eta never exceeds 1).

    Tier-1 MODELING CHOICE (not an oracle-verified absolute): the sinc^2(dk*L/2) phase-matching
    SHAPE is the verified, physically central factor; ``prefactor`` is a single lumped constant
    (units folded in) chosen so a typical green-doubler lands at a few-percent eta -- it is NOT a
    first-principles 2*omega^2/(n^3 eps0 c^3 A) coefficient. Use it for the relative overlay /
    tuning-curve shape, not an absolute conversion number."""
    eta_lin = prefactor * (deff_pm_V ** 2) * (L_mm ** 2) * P_W * phase_match_efficiency(dk_per_mm, L_mm)
    if not deplete:
        return eta_lin
    return math.tanh(math.sqrt(max(eta_lin, 0.0))) ** 2   # high-conversion: tanh^2(sqrt(eta_lin)) <= 1


def chi2_shg_efficiency(eta_lin, dkL, n_steps=400):
    """SECOND-HARMONIC conversion efficiency from the FULL Manley-Rowe coupled-wave equations, integrated
    (RK4) with pump DEPLETION and an arbitrary phase mismatch -- the rigorous generalization of both
    ``phase_match_efficiency`` (the undepleted sinc^2) and the ``tanh^2`` depletion clamp, valid where neither
    alone is (strong conversion AND off phase match together).

    The slowly-varying coupled equations for SHG (Boyd, *Nonlinear Optics*), in dimensionless form with
    a1 = A_w/A_w(0), a2 = A_2w/A_w(0), s = z/L_NL (1/L_NL = kappa*|A_w(0)|), and delta = Delta_k*L_NL:
        da1/ds = i a1* a2 exp(-i delta s),   da2/ds = i a1^2 exp(+i delta s).
    They conserve power |a1|^2 + |a2|^2 = 1 (Manley-Rowe energy: one 2w photon per two w photons).

    Inputs: ``eta_lin`` = the ON-phase-match UNDEPLETED efficiency (deff^2 L^2 I ...), so the normalized length
    is S = sqrt(eta_lin); ``dkL`` = Delta_k * L (the phase slip over the crystal, = delta*S). Returns
    eta = |a2(S)|^2 in [0,1]. LIMITS (both oracle-checkable): dkL=0 -> tanh^2(sqrt(eta_lin)); eta_lin -> 0
    (undepleted) -> eta_lin * sinc^2(dkL/2). Numpy-free; deterministic."""
    S = math.sqrt(max(eta_lin, 0.0))                 # normalized crystal length L/L_NL
    if S <= 0.0:
        return 0.0
    delta = dkL / S                                  # normalized mismatch Delta_k*L_NL
    ds = S / int(n_steps)

    def _deriv(a1, a2, s):
        e = cmath.exp(-1j * delta * s)
        return (1j * a1.conjugate() * a2 * e, 1j * a1 * a1 * e.conjugate())

    a1, a2 = complex(1.0, 0.0), complex(0.0, 0.0)
    for k in range(int(n_steps)):
        s = k * ds
        k1 = _deriv(a1, a2, s)
        k2 = _deriv(a1 + 0.5 * ds * k1[0], a2 + 0.5 * ds * k1[1], s + 0.5 * ds)
        k3 = _deriv(a1 + 0.5 * ds * k2[0], a2 + 0.5 * ds * k2[1], s + 0.5 * ds)
        k4 = _deriv(a1 + ds * k3[0], a2 + ds * k3[1], s + ds)
        a1 += ds / 6.0 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        a2 += ds / 6.0 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    return min(1.0, abs(a2) ** 2)


def chi2_solve(deff_pm_V, L_mm, P_W, dk_per_mm=0.0, prefactor=2.0e-4, n_steps=400):
    """SHG conversion efficiency via the Manley-Rowe ODE (``chi2_shg_efficiency``). Builds the on-phase-match
    undepleted efficiency eta_lin = prefactor*deff^2*L^2*P (the SAME lumped Tier-1 coefficient as
    ``nl_conversion_efficiency`` -- a relative/shape constant, not a first-principles absolute) and the phase
    slip dkL = dk_per_mm*L_mm, then integrates the depleted+mismatched coupled-wave equations. Returns eta in
    [0,1]: at the phase-matched point (dk=0) eta = tanh^2(sqrt(eta_lin)); detuned it follows the rigorous
    depleted tuning curve (which narrows + pumps-down vs the bare sinc^2)."""
    eta_lin = prefactor * (deff_pm_V ** 2) * (L_mm ** 2) * P_W
    return chi2_shg_efficiency(eta_lin, dk_per_mm * L_mm, n_steps=n_steps)


# Crystal-material catalog: effective nonlinear coefficient deff (pm/V, order-of-magnitude
# literature values) + a SIMPLE LINEAR phase-mismatch temperature model dk(T) ~ dk_dT*(T - T_pm).
# The dk_dT slope is a HONEST PLACEHOLDER (deg-1 per mm) tuned only to give a realistic sinc^2(T)
# tuning-curve WIDTH for the scan -- it is NOT the true Sellmeier-derived dn/dT for each crystal.
NL_CRYSTALS = {
    # name:   (deff pm/V, dk/dT  [mm^-1 K^-1],  phase-matched T [C])
    'BBO':  (2.0, 0.020, 25.0),
    'KTP':  (3.6, 0.015, 25.0),
    'LBO':  (1.2, 0.012, 148.0),     # NCPM 1064->532 near 148 C
    'PPLN': (16.0, 0.030, 100.0),    # QPM, large deff; tight T tuning
    'KDP':  (0.4, 0.010, 25.0),
}


def nl_phase_mismatch_T(crystal_material, temp_C):
    """A simple LINEAR phase-mismatch model dk(T) = dk_dT * (T - T_pm) per mm for the TEMPERATURE
    scan (honestly labeled: the dk_dT slope is a placeholder, not the real dn/dT). dk=0 at the
    crystal's phase-matched temperature, so phase_match_efficiency peaks there and falls off as a
    sinc^2 with symmetric side-lobes -- the physically central tuning-curve shape."""
    _deff, dk_dT, T_pm = NL_CRYSTALS.get((crystal_material or 'BBO').upper(), NL_CRYSTALS['BBO'])
    return dk_dT * (temp_C - T_pm)


# Ordinary + extraordinary Sellmeier for the common NEGATIVE-UNIAXIAL nonlinear crystals, so the SHG
# phase-matching ANGLE can be DERIVED from the index ellipsoid (vs the lumped dk(T) scalar above). Each
# entry is (o-params, e-params) for  n^2(lambda_um) = A + B/(lambda_um^2 - C) - D*lambda_um^2.
NL_CRYSTAL_SELLMEIER = {
    'BBO': ((2.7359, 0.01878, 0.01822, 0.01354), (2.3753, 0.01224, 0.01667, 0.01516)),   # Eimerl 1987
}


def _nl_n2(params, lam_um):
    A, B, C, D = params
    return A + B / (lam_um ** 2 - C) - D * lam_um ** 2


def shg_phase_match_angle(crystal, wl_fund_nm):
    """Type-I SHG critical phase-matching ANGLE theta_pm (degrees from the optic axis) of a negative-uniaxial
    crystal: the extraordinary index of the second harmonic is tuned by angle to equal the ordinary index of
    the fundamental, n_e(theta, 2w) = n_o(w). Solving the index ellipsoid gives
        sin^2(theta_pm) = (1/n_o(w)^2 - 1/n_o(2w)^2) / (1/n_e(2w)^2 - 1/n_o(2w)^2).
    crystal is a key in NL_CRYSTAL_SELLMEIER (e.g. 'BBO'). Returns theta_pm in degrees, or None if the ratio
    falls outside [0,1] (not angle-phase-matchable for that wavelength). e.g. BBO 1064->532 -> 22.78 deg."""
    coeffs = NL_CRYSTAL_SELLMEIER.get((crystal or '').upper())
    if coeffs is None:
        return None
    o, e = coeffs
    lam_w = wl_fund_nm * 1.0e-3                    # fundamental wavelength, micron
    no_w2 = _nl_n2(o, lam_w)                       # n_o(w)^2
    no_2w2 = _nl_n2(o, lam_w / 2.0)               # n_o(2w)^2
    ne_2w2 = _nl_n2(e, lam_w / 2.0)               # n_e(2w)^2
    den = 1.0 / ne_2w2 - 1.0 / no_2w2
    if den == 0.0:
        return None
    s2 = (1.0 / no_w2 - 1.0 / no_2w2) / den
    if not (0.0 <= s2 <= 1.0):
        return None
    return math.degrees(math.asin(math.sqrt(s2)))


def shg_walkoff_mm(crystal, wl_fund_nm, L_mm):
    """Sellmeier-DERIVED spatial walk-off OFFSET (mm) of the extraordinary second harmonic over a crystal of
    length L_mm at the Type-I critical phase-match angle: the e-wave (2w) Poynting drifts off its wavevector by
    rho = uniaxial_walkoff_angle(n_o(2w), n_e(2w), theta_pm), giving a lateral offset L*tan(rho) at the exit.
    The first-principles replacement for the lumped ``nl_walkoff_mm`` literal (used when the chi2 solver is on).
    Returns 0.0 if the crystal has no Sellmeier entry or is not angle-phase-matchable. e.g. BBO 1064->532 over
    10 mm -> ~0.56 mm (rho ~ 3.2 deg)."""
    th = shg_phase_match_angle(crystal, wl_fund_nm)
    coeffs = NL_CRYSTAL_SELLMEIER.get((crystal or '').upper())
    if th is None or coeffs is None:
        return 0.0
    lam_2w = 0.5 * wl_fund_nm * 1.0e-3                 # second-harmonic wavelength, micron
    n_o2 = math.sqrt(_nl_n2(coeffs[0], lam_2w))
    n_e2 = math.sqrt(_nl_n2(coeffs[1], lam_2w))
    rho = uniaxial_walkoff_angle(n_o2, n_e2, th)
    return L_mm * math.tan(math.radians(rho))


# --- Fresnel reflection (s/p amplitude + phase) -----------------------------

# complex refractive indices of common mirror metals near 633 nm
METALS = {'AL': complex(1.37, 7.62), 'AG': complex(0.14, 3.98), 'AU': complex(0.16, 3.80)}

# Tabulated n,k vs wavelength (nm) for a DISPERSIVE mirror reflectance (the single METALS values above
# remain the byte-identical default; dispersion is opt-in per mirror). Ag/Au: Johnson & Christy 1972
# (PRB 6, 4370); Al: Rakic 1998 Brendel-Bormann (Appl. Opt. 37, 5271). Data via refractiveindex.info (CC0).
# NB the single METALS['AG'] understates Ag reflectance ~2% vs J&C; the dispersive path uses the J&C k.
METAL_NK = {
    'AG': [(397.4, 0.05, 2.070), (450.9, 0.04, 2.657), (495.9, 0.05, 3.093), (520.9, 0.05, 3.324),
           (616.8, 0.06, 4.152), (704.5, 0.04, 4.838), (821.1, 0.04, 5.727), (892.0, 0.04, 6.312),
           (984.0, 0.04, 6.992), (1088.0, 0.04, 7.795)],
    'AU': [(397.4, 1.470, 1.952), (450.9, 1.380, 1.914), (495.9, 1.040, 1.833), (520.9, 0.620, 2.081),
           (616.8, 0.210, 3.272), (704.5, 0.130, 4.103), (821.1, 0.160, 5.083), (892.0, 0.170, 5.663),
           (984.0, 0.220, 6.350), (1088.0, 0.270, 7.150)],
    'AL': [(400.0, 0.4658, 4.7119), (450.0, 0.6172, 5.3031), (500.0, 0.7883, 5.8653), (532.0, 0.9017, 6.2092),
           (600.0, 1.1419, 6.9262), (633.0, 1.2685, 7.2840), (700.0, 1.6664, 8.0406), (800.0, 2.6717, 8.2709),
           (900.0, 2.0412, 8.2198), (1000.0, 1.5192, 9.2643), (1064.0, 1.3866, 9.9903), (1100.0, 1.3438, 10.3963)],
}


def metal_nk(metal, wl_nm):
    """Complex index n+ik of a mirror metal at wl_nm, linearly interpolated from the J&C/Rakic table
    (clamped to the table ends outside ~0.4-1.1 um). Falls back to the single METALS value if untabled."""
    tbl = METAL_NK.get(metal)
    if not tbl:
        return METALS.get(metal, METALS['AL'])
    if wl_nm <= tbl[0][0]:
        return complex(tbl[0][1], tbl[0][2])
    if wl_nm >= tbl[-1][0]:
        return complex(tbl[-1][1], tbl[-1][2])
    for i in range(1, len(tbl)):
        if wl_nm <= tbl[i][0]:
            l0, n0, k0 = tbl[i - 1]
            l1, n1, k1 = tbl[i]
            g = (wl_nm - l0) / (l1 - l0)
            return complex(n0 + g * (n1 - n0), k0 + g * (k1 - k0))
    return complex(tbl[-1][1], tbl[-1][2])


def metal_reflectance(metal, wl_nm, aoi_deg=0.0):
    """Mirror-metal power reflectance at wl_nm. Normal incidence R = ((n-1)^2+k^2)/((n+1)^2+k^2);
    at an angle, the unpolarized-average Fresnel power from the complex index."""
    nk = metal_nk(metal, wl_nm)
    if aoi_deg <= 0.0:
        return ((nk.real - 1.0) ** 2 + nk.imag ** 2) / ((nk.real + 1.0) ** 2 + nk.imag ** 2)
    rs, rp = fresnel_reflect(1.0, nk, math.radians(aoi_deg))
    return 0.5 * (abs(rs) ** 2 + abs(rp) ** 2)


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


def surface_reflectance(n1, n2):
    """Normal-incidence single-surface power reflectance R = ((n1-n2)/(n1+n2))^2 -- the
    parasitic Fresnel back-reflection at an n1->n2 transmissive face (A9 ghost beams).
    ~0.04 (4%) at an uncoated air<->glass face (n2=1.5), ~0.0006 for an AR-V coating
    (n2~1.05). This is just |fresnel_reflect|^2 at theta_i=0 (rs=rp=(n1-n2)/(n1+n2) there),
    so it reuses the already-oracle-verified Fresnel kernel rather than hand-rolling it; the
    transmitted power is debited to (1-R)*P so R+T=1 (physics_verify ok=true, 12/12: the
    ghost+transmitted = incident power split). At AOI use fresnel_reflect's angular form;
    this normal-incidence value is the floor."""
    rs, _rp = fresnel_reflect(n1, n2, 0.0)
    return abs(rs) ** 2


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


# --- detector responsivity + readout topology (C8) --------------------------
# A photodiode converts optical power P to a photocurrent I = R(lambda)*P, where the responsivity
#   R(lambda) = qe(material, lambda) * lambda[nm] / 1239.8   (A/W)
# 1239.8 = hc/e in eV*nm, so lambda/1239.8 = E_photon^{-1} in (eV)^{-1}; at unit quantum efficiency
# every absorbed photon yields one electron, giving the ideal R = eta*lambda/1239.8. The clean ratio
# R(lambda)=eta*lambda/1239.8 is oracle-VERIFIED (physics_verify ok=true 5/5: eta=1,lambda=1239.8->1.0
# A/W; lambda=619.9->0.5; eta=0.8,lambda=1550->1.00016; DIMENSIONAL dimensionless ratio*eta). The
# per-material quantum-efficiency band qe(material,lambda) below is a SIMPLE TIER-1 MODELING CHOICE
# (a smooth trapezoidal window over each detector's usable spectral range with a representative peak
# QE), NOT a digitized datasheet curve -- it gives a realistic R(lambda) SHAPE (Si peaks vis/NIR,
# InGaAs/Ge cover NIR/SWIR) for the readout overlay, not an absolute calibrated responsivity.

HC_OVER_E_eVnm = 1239.8                       # hc/e in eV*nm: E_photon[eV] = 1239.8 / lambda[nm]

# Per-material quantum-efficiency band: (lambda_lo, lambda_full_lo, lambda_full_hi, lambda_hi nm, peak_qe).
# QE ramps 0->peak across [lo, full_lo], holds peak across [full_lo, full_hi], ramps peak->0 across
# [full_hi, hi], and is 0 outside [lo, hi]. Ranges are the standard usable windows of each photodiode
# material (Si ~190-1100 nm, InGaAs ~800-1700 nm standard / ext to ~2600, Ge ~600-1800 nm).
DETECTOR_QE = {
    'Si':     (190.0, 500.0, 950.0, 1100.0, 0.90),     # silicon: visible + near-IR, peak ~700-900 nm
    'InGaAs': (800.0, 1100.0, 1650.0, 1700.0, 0.80),   # standard InGaAs: telecom NIR/SWIR
    'Ge':     (600.0, 1100.0, 1550.0, 1800.0, 0.65),   # germanium: broad NIR/SWIR, lower peak QE
}


def detector_qe(material, wl_nm):
    """Quantum efficiency eta in [0, peak] of a photodiode ``material`` at wavelength ``wl_nm`` (nm),
    from the trapezoidal usable-band model in DETECTOR_QE (0 outside the band). TIER-1 SHAPE, not a
    datasheet digitization -- captures which materials respond where (Si vis/NIR, InGaAs/Ge NIR/SWIR)."""
    band = DETECTOR_QE.get(material, DETECTOR_QE['Si'])
    lo, flo, fhi, hi, peak = band
    if wl_nm <= lo or wl_nm >= hi:
        return 0.0
    if wl_nm < flo:
        return peak * (wl_nm - lo) / (flo - lo)
    if wl_nm > fhi:
        return peak * (hi - wl_nm) / (hi - fhi)
    return peak


def responsivity(material, wl_nm):
    """Photodiode responsivity R(lambda) = qe(material, lambda) * lambda[nm] / 1239.8 in A/W
    (amps of photocurrent per watt of optical power). The lambda/1239.8 ratio is the inverse
    photon energy in eV^-1; at unit QE that is the ideal one-electron-per-photon responsivity
    (oracle-VERIFIED clean ratio). qe(material, lambda) bands it to each material's window."""
    return detector_qe(material, wl_nm) * wl_nm / HC_OVER_E_eVnm


def apd_excess_noise(M, k):
    """APD excess-noise factor F(M) = k*M + (2 - 1/M)*(1 - k) (McIntyre), with M the avalanche gain
    and k the ionization-coefficient ratio (k~0.02 Si, ~0.4 InGaAs, ~0.9 Ge). F=2-1/M at k=0 (ideal,
    single-carrier multiplication) and F=M at k=1 (worst case). Oracle-VERIFIED ok=true 6/6
    (M=10,k=0.02->2.062; M=100,k=0.02->3.9502; k=0->1.9; k=1->10; DIMENSIONAL dimensionless)."""
    if M <= 0.0:
        return 1.0
    return k * M + (2.0 - 1.0 / M) * (1.0 - k)


def quadrant_fraction(offset_mm, w_mm):
    """Fraction of a Gaussian beam (1/e^2 intensity radius ``w_mm``, centered ``offset_mm`` from the
    quadrant boundary) lying on the POSITIVE side of one straight gap line:

        f(offset, w) = (1/2) * [1 + erf(sqrt(2) * offset / w)]      (the knife-edge sibling)

    The half-plane fraction of the 1-D marginal Gaussian I(x) ~ exp(-2 x^2/w^2): f=1/2 when the beam is
    centered on the line (offset=0), -> 1 as the beam moves fully onto the positive side, -> 0 fully onto
    the negative side. Same sqrt(2)-in-NUMERATOR erf scale as slit/knife (1/e^2 convention sigma=w/2),
    so it is exactly 1 - knife_transmission(offset, 0, w). A 2-axis quadrant detector multiplies the two
    independent marginal fractions (X-gap and Y-gap) to get each quadrant's power weight. The erf
    decomposition was verified by DIRECT Gaussian integration (erf is not in the oracle sandbox), <1e-6
    vs the integrated Gaussian -- see tests/_verify_detector.py."""
    if w_mm <= 1e-9:
        return 1.0 if offset_mm >= 0.0 else 0.0
    return 0.5 * (1.0 + math.erf(math.sqrt(2.0) * offset_mm / w_mm))


def quadrant_signals(xc_mm, yc_mm, w_mm):
    """Normalized 2-axis position signals (Sx, Sy) of a quadrant detector for a Gaussian beam of 1/e^2
    radius ``w_mm`` whose centroid sits at (xc, yc) relative to the quadrant cross (the gap origin).

    The four quadrant powers are products of the two independent marginal half-plane fractions:
        fx = quadrant_fraction(xc, w)   (fraction with local x > 0)
        fy = quadrant_fraction(yc, w)   (fraction with local y > 0)
        A (+x,+y)=fx*fy   B (-x,+y)=(1-fx)*fy   C (-x,-y)=(1-fx)*(1-fy)   D (+x,-y)=fx*(1-fy)
    The standard difference-over-sum readouts then collapse to the single-axis erf signals:
        Sx = (A + D - B - C)/Sigma = 2*fx - 1 = erf(sqrt2 * xc / w)
        Sy = (A + B - C - D)/Sigma = 2*fy - 1 = erf(sqrt2 * yc / w)
    (Sigma = A+B+C+D = 1.) Each is monotonic in its offset, zero at center, correct sign, and ~linear
    (slope 2*sqrt(2/pi)/w) near center -- a true 2-axis position-error sensor for the A6/A7 solvers."""
    fx = quadrant_fraction(xc_mm, w_mm)
    fy = quadrant_fraction(yc_mm, w_mm)
    A = fx * fy
    B = (1.0 - fx) * fy
    C = (1.0 - fx) * (1.0 - fy)
    D = fx * (1.0 - fy)
    total = A + B + C + D
    if total <= 1e-12:
        return 0.0, 0.0, (A, B, C, D)
    Sx = (A + D - B - C) / total
    Sy = (A + B - C - D) / total
    return Sx, Sy, (A, B, C, D)


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


def reflection_wavefront_error(h, aoi_rad):
    """Wavefront (optical-path) error imprinted on REFLECTION by a surface-height deviation ``h``
    (along the surface normal, relative to a reference plane), at angle of incidence ``aoi_rad``:

        W = 2 * h * cos(theta_i)        (oracle-VERIFIED: physics_verify ok=true, 6/6)

    The factor 2 is because the beam traverses the height deviation TWICE on reflection (in + out);
    cos(theta_i) projects the doubled normal-direction path onto the optical axis. At normal incidence
    (theta=0) W = 2h; at 60 deg W = 2h*0.5 = h; at 45 deg W = 2h*(sqrt2/2) = h*sqrt(2). The phase is
    phi = (2*pi/lambda)*W = (4*pi/lambda)*h*cos(theta_i). DIMENSIONAL: W,h length; theta angle.
    This is the GEOMETRIC (Tier-1) surface-sag -> wavefront imprint -- an optical-path-difference over
    the footprint, NOT a wave-diffraction calculation. The W=2h*cos(theta) relation IS the verified part."""
    return 2.0 * h * math.cos(aoi_rad)


def fit_zernike(rho, theta, W, n_modes=N_ZERNIKE):
    """Least-squares fit of a SAMPLED wavefront to the orthonormal Noll Zernike coefficients.

    Given matched samples (rho_i, theta_i, W_i) over the unit disk, return the coefficient vector
    ``a`` (length ``n_modes``, in the same units as W) minimizing sum_i (W_i - sum_j a_j Z_j(rho_i,theta_i))^2.

    Uses numpy.linalg.lstsq when numpy is available (the tracer runs inside Blender, which ships it),
    with a pure-Python normal-equations + Gaussian-elimination fallback so physics.py stays importable
    by a bare interpreter (its self-test convention). Because the RMS-normalized Zernikes are orthonormal
    over the disk, a clean (noise-free) over-determined sample set recovers the injected coefficients to
    machine precision (round-trip < 1e-6; see the gate-A proof). Samples must be INSIDE the unit disk
    (rho <= 1); the caller normalizes the footprint radius to rho=1 before calling."""
    n = min(len(rho), len(theta), len(W))
    if n == 0:
        return [0.0] * n_modes
    # design matrix A[i][j] = Z_{j+1}(rho_i, theta_i)  (j = 0..n_modes-1 -> Noll j=1..n_modes)
    try:
        import numpy as np
        A = np.empty((n, n_modes), dtype=float)
        for i in range(n):
            r, th = rho[i], theta[i]
            for j in range(n_modes):
                A[i, j] = zernike(j + 1, r, th)
        b = np.asarray(W[:n], dtype=float)
        coeffs, *_ = np.linalg.lstsq(A, b, rcond=None)
        return [float(c) for c in coeffs]
    except Exception:
        pass
    # pure-Python fallback: solve the normal equations (A^T A) x = A^T b by Gaussian elimination.
    rows = [[zernike(j + 1, rho[i], theta[i]) for j in range(n_modes)] for i in range(n)]
    # A^T A (n_modes x n_modes, symmetric) and A^T b (n_modes)
    ata = [[0.0] * n_modes for _ in range(n_modes)]
    atb = [0.0] * n_modes
    for i in range(n):
        ri = rows[i]
        wi = W[i]
        for a in range(n_modes):
            atb[a] += ri[a] * wi
            ra = ri[a]
            row_a = ata[a]
            for bcol in range(a, n_modes):
                row_a[bcol] += ra * ri[bcol]
    for a in range(n_modes):                              # mirror the symmetric upper triangle
        for bcol in range(a):
            ata[a][bcol] = ata[bcol][a]
    # Gaussian elimination with partial pivoting on the augmented [A^T A | A^T b]
    M = [ata[r][:] + [atb[r]] for r in range(n_modes)]
    for col in range(n_modes):
        piv = max(range(col, n_modes), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            continue                                      # singular column -> leave that coeff at 0
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        inv = 1.0 / pv
        for k in range(col, n_modes + 1):
            M[col][k] *= inv
        for r in range(n_modes):
            if r == col:
                continue
            f = M[r][col]
            if f:
                for k in range(col, n_modes + 1):
                    M[r][k] -= f * M[col][k]
    return [M[r][n_modes] for r in range(n_modes)]


# --- coherence --------------------------------------------------------------

def coherence_length_mm(wavelength_nm, linewidth_nm):
    """Lc = lambda^2 / d-lambda (0 linewidth -> infinite coherence)."""
    if linewidth_nm is None or linewidth_nm <= 0.0:
        return float('inf')
    lam = wavelength_nm * NM_TO_MM
    return lam * lam / (linewidth_nm * NM_TO_MM)


def db_to_linear(db):
    """Convert an isolation/attenuation figure in decibels to its linear POWER ratio:
    10^(-db/10). The standard dB->linear for a power quantity. Used by the C6 circulator's
    port-to-port isolation leak (iso=20 dB -> 0.01, 30 dB -> 0.001, 0 dB -> 1.0, 10 dB -> 0.1).
    Dimensionless in, dimensionless out (a pure ratio). physics_verify ok=true."""
    return 10.0 ** (-db / 10.0)


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


def newton_ring_radius(m, wl_nm, R_mm):
    """Newton's-rings DARK-ring radius (reflection) of the m-th ring: r_m = sqrt(m * lambda * R), where R is
    the radius of curvature of the lens against the flat (Hecht). m=0 -> 0 (the central dark spot)."""
    return math.sqrt(max(0.0, m) * (wl_nm * NM_TO_MM) * R_mm)


def fringe_envelope(opd_mm, Lc_mm):
    """Visibility envelope vs optical path difference (Gaussian coherence decay).

    MODELING NOTE: ``exp(-(pi*opd/Lc)^2/2)`` paired with Lc = lambda^2/d-lambda is a SELF-CONSISTENT
    order-of-magnitude pair (visibility ~1 for opd << Lc, washed out for opd >> Lc), NOT the exact
    Fourier transform of a FWHM-d-lambda Gaussian spectrum (that would carry an extra ln2:
    exponent denominator 2*ln2, and the envelope would fall a touch faster). Near zero OPD (the
    alignment/scan regime) the two agree to leading order, and Lc = lambda^2/d-lambda is itself a
    loose definition, so the shipped pair is internally consistent; the difference only bites once
    opd >~ Lc where fringes are already gone."""
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
    # A9 normal-incidence surface reflectance R=((n1-n2)/(n1+n2))^2 (the ghost back-reflection):
    # 4% uncoated air<->glass, tiny for AR-ish; R+T=1 (physics_verify ok=true 12/12)
    if not (close(surface_reflectance(1.0, 1.5), 0.04, 1e-9)
            and close(surface_reflectance(1.0, 1.52), 0.042579994960947345, 1e-9)
            and surface_reflectance(1.0, 1.05) < 1e-3
            and close(1.0 - surface_reflectance(1.0, 1.5), 0.96, 1e-9)):
        fails.append("surface_reflectance R=%.5f (want 0.04)" % surface_reflectance(1.0, 1.5))
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

    # chi(2) nonlinear conversion: every child wavelength is exact energy conservation (C7, each
    # oracle-VERIFIED). SHG 1064->532; THG 1064->354.667; SFG 1064+532->354.667; DFG 1064-1550->3393.4;
    # OPO pump 532 + signal 800 -> idler 1588.06; SPDC degenerate 405->810.
    if not close(nl_child_wavelength('SHG', 1064.0), 532.0, 1e-9):
        fails.append("nl SHG 1064->%.4f != 532" % nl_child_wavelength('SHG', 1064.0))
    if not close(nl_child_wavelength('THG', 1064.0), 1064.0 / 3.0, 1e-9):
        fails.append("nl THG 1064->%.4f" % nl_child_wavelength('THG', 1064.0))
    if not close(nl_child_wavelength('SPDC', 405.0), 810.0, 1e-9):
        fails.append("nl SPDC 405->%.4f != 810" % nl_child_wavelength('SPDC', 405.0))
    if not close(nl_child_wavelength('SFG', 1064.0, 532.0), 354.6666667, 1e-4):
        fails.append("nl SFG 1064+532->%.4f" % nl_child_wavelength('SFG', 1064.0, 532.0))
    # SFG of two equal inputs reduces to SHG (1/l3 = 2/l1 -> l3 = l1/2)
    if not close(nl_child_wavelength('SFG', 1064.0, 1064.0), 532.0, 1e-9):
        fails.append("nl SFG degenerate != SHG")
    if not close(nl_child_wavelength('DFG', 1064.0, 1550.0), 3393.415638, 1e-3):
        fails.append("nl DFG 1064-1550->%.3f" % nl_child_wavelength('DFG', 1064.0, 1550.0))
    if not close(nl_child_wavelength('OPO', 532.0, 800.0), 1588.05970, 1e-3):
        fails.append("nl OPO p532 s800 -> idler %.3f" % nl_child_wavelength('OPO', 532.0, 800.0))
    # OPO energy conservation closes: 1/lp == 1/ls + 1/li
    _li = nl_child_wavelength('OPO', 532.0, 800.0)
    if not close(1.0 / 532.0, 1.0 / 800.0 + 1.0 / _li, 1e-12):
        fails.append("nl OPO energy not conserved")
    # DFG/OPO with inputs that give a non-positive 1/l3 -> None (no physical child)
    if nl_child_wavelength('DFG', 1550.0, 1064.0) is not None:
        fails.append("nl DFG should be None when l1>l2")
    # phase-matching sinc^2: =1 at dk=0, =0 at dk*L=2*pi (x=pi), mid value 0.7080734 at x=1, <=1 always
    if not close(phase_match_efficiency(0.0, 10.0), 1.0, 1e-12):
        fails.append("sinc2 perfect match != 1")
    if not (phase_match_efficiency(2.0 * math.pi / 10.0, 10.0) < 1e-12):
        fails.append("sinc2 first zero != 0")
    if not close(phase_match_efficiency(2.0 / 10.0, 10.0), 0.70807341827357, 1e-9):  # x = dk*L/2 = 1.0
        fails.append("sinc2 mid value")
    # tuning curve peaks at the crystal's phase-matched temperature (dk=0 -> sinc^2=1)
    _Tpm = NL_CRYSTALS['LBO'][2]
    if not (phase_match_efficiency(nl_phase_mismatch_T('LBO', _Tpm), 10.0) > 0.999
            and phase_match_efficiency(nl_phase_mismatch_T('LBO', _Tpm + 30.0), 10.0)
            < phase_match_efficiency(nl_phase_mismatch_T('LBO', _Tpm + 5.0), 10.0)):
        fails.append("nl T-tuning sinc2 does not peak at T_pm")
    # high-conversion eta is bounded by 1 (pump depletion: tanh^2(sqrt(eta_lin)) <= 1)
    if not (nl_conversion_efficiency(16.0, 10.0, 1e6, 0.0) <= 1.0
            and nl_conversion_efficiency(2.0, 5.0, 1.0, 0.0) > 0.0):
        fails.append("nl_conversion_efficiency not in (0,1]")

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

    # reflection wavefront error W = 2 h cos(theta) (oracle-VERIFIED ok=true 6/6):
    # theta=0 -> 2h, theta=60 -> h, theta=45 -> h*sqrt2
    if not close(reflection_wavefront_error(1.0, 0.0), 2.0, 1e-12):
        fails.append("reflection_wavefront_error(h=1,0deg)=%.6f != 2" % reflection_wavefront_error(1.0, 0.0))
    if not close(reflection_wavefront_error(1.0, math.radians(60.0)), 1.0, 1e-12):
        fails.append("reflection_wavefront_error(h=1,60deg)=%.6f != 1" % reflection_wavefront_error(1.0, math.radians(60.0)))
    if not close(reflection_wavefront_error(1.0, math.radians(45.0)), math.sqrt(2.0), 1e-12):
        fails.append("reflection_wavefront_error(h=1,45deg)=%.6f != sqrt2" % reflection_wavefront_error(1.0, math.radians(45.0)))

    # fit_zernike ROUND-TRIP: synthesize a wavefront from a KNOWN coeff vector, sample it, fit,
    # and recover the SAME coefficients to < 1e-6 (gate A). Inject defocus+astig+coma+spherical.
    inj = [0.0] * N_ZERNIKE
    inj[3] = 0.42        # defocus  (j=4)
    inj[5] = -0.31       # astig0   (j=6)
    inj[7] = 0.18        # comaX    (j=8)
    inj[10] = 0.09       # spherical(j=11)
    _rs, _ts, _ws = [], [], []
    _G = 41
    for _i in range(_G):
        for _j in range(_G):
            _x = (_i + 0.5) / _G * 2.0 - 1.0
            _y = (_j + 0.5) / _G * 2.0 - 1.0
            _r = math.hypot(_x, _y)
            if _r > 1.0:
                continue
            _th = math.atan2(_y, _x)
            _rs.append(_r); _ts.append(_th); _ws.append(zernike_value(inj, _r, _th))
    rec = fit_zernike(_rs, _ts, _ws)
    if max(abs(rec[k] - inj[k]) for k in range(N_ZERNIKE)) > 1e-6:
        fails.append("fit_zernike round-trip max err %.2e (want <1e-6)"
                     % max(abs(rec[k] - inj[k]) for k in range(N_ZERNIKE)))

    if fails:
        print("PHYSICS SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PHYSICS SELFTEST PASSED")
