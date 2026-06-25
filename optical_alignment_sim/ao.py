"""Adaptive optics: modal (Zernike) wavefront sensing + deformable-mirror correction.

A beam carries a Zernike wavefront-error vector (``tracer._Ray.aberr``, in waves); an
ABERRATOR adds modes (the "turbulence"), a DEFORMABLE_MIRROR subtracts its commanded modes,
and a WAVEFRONT_SENSOR reads the residual. This module renders the sensor's reconstructed
wavefront map (false colour) into the bottom-left monitor window and runs the closed loop
(an integrator controller) that flattens it. The wavefront physics (Zernike basis, RMS) is
in physics.py and is verified against the physicist oracle.
"""
from __future__ import annotations

import math

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty, BoolProperty

from . import physics, tracer, monitor


def _aberr_at(segs, sensor_name):
    """Zernike coeffs (list of 15, waves) of the strongest beam (by power) reaching the named
    sensor, or None if nothing reaches it. The strongest beam wins even when it is unaberrated, so
    a strong flat reference is never shadowed by a weaker aberrated stray; a beam carrying no aberr
    reads as a flat (zero) wavefront."""
    best = None
    for s in segs:
        if s.get("to") == sensor_name:
            if best is None or s.get("power", 0.0) > best[0]:
                best = (s.get("power", 0.0), s.get("aberr"))
    if best is None:
        return None
    return list(best[1]) if best[1] else [0.0] * physics.N_ZERNIKE


def _beam_defocus_coeff(seg, sensor_aperture_mm=0.0):
    """Noll Z4 (defocus) coefficient in WAVES carried by a Gaussian beam's OWN wavefront curvature
    R(z) at the sensor -- the term a real Shack-Hartmann WFS integrates that the modal ``aberr``
    channel alone omits (so a clean diverging/converging beam no longer reads RMS=0).

    A fundamental Gaussian over a footprint of radius w_s has OPD W(r) = r^2/(2R) (R = beam_roc(q)
    at the sensor segment; R>0 diverging, inf at a waist). In pupil coords rho = r/w_s that is a
    pure defocus W = (w_s^2 / (2 R lambda)) rho^2 waves; matching the RMS-normalized Noll defocus
    Z4 = sqrt(3)(2 rho^2 - 1) (whose rho^2 part is 2 sqrt3) gives

        a4 = w_s^2 / (4 sqrt3 R lambda)   [waves]

    physics_verify ok=true (a4(w_s=5mm, R=1000mm, lambda=632.8nm) = 5.70234 waves;
    c2 = 2 sqrt3 a4 = 19.7535; DIMENSIONAL + SANITY-positive). Collimated/waist (R=inf) -> 0.

    w_s is the footprint radius the sensor actually integrates: the beam radius w_mm at the sensor,
    clipped to the clear semi-aperture when the beam OVERFILLS (a finite sensor only sees its
    aperture -- consistent with zonal_wavefront_at_sensor's rho_max=min(1, a/w) clip)."""
    qd = seg.get("qd")
    if not qd:
        return 0.0
    R = physics.beam_roc(complex(qd[0], qd[1]))
    if not math.isfinite(R) or abs(R) < 1e-9:
        return 0.0                                          # collimated / at a waist -> no defocus
    w_s = seg.get("w_mm", 0.0) or 0.0
    if sensor_aperture_mm and sensor_aperture_mm > 0.0:
        w_s = min(w_s, sensor_aperture_mm)                  # overfill: only the aperture is integrated
    if w_s <= 0.0:
        return 0.0
    wl_mm = (seg.get("wavelength", 632.8) or 632.8) * 1e-6
    return w_s * w_s / (4.0 * math.sqrt(3.0) * R * wl_mm)


def _sensor_wavefront(segs, sensor_name, sensor_aperture_mm=0.0):
    """The wavefront a WFS PHYSICALLY reads: the strongest beam's modal ``aberr`` (turbulence / DM /
    surface figure) PLUS that beam's OWN curvature defocus from R(z) (see _beam_defocus_coeff) folded
    into Noll Z4 -- the Z4 a real Shack-Hartmann integrates that the modal channel alone omits, so a
    clean diverging/converging beam no longer reads a (wrong) flat RMS=0.

    Returns ``(coeffs, info)``: ``coeffs`` is the 15-vector (waves) with the beam defocus in Z4;
    ``info`` reports the breakdown (``modal_rms``, ``defocus_waves``, ``beam_roc_mm``, ``w_sensor_mm``)
    and the multi-beam context (``n_beams`` arriving, ``dominant_frac`` of total power -- the read is
    strongest-beam-only, so >1 beam means a weaker arm/stray is being dropped). ``coeffs`` is None if
    NO beam reaches the sensor (a dark WFS is not a flat one).

    NOTE this is the READ side (publish_wavefront / ao_measure). The AO control loop reads the modal
    ``_aberr_at`` channel ONLY (the DM commands modal modes), so its interaction matrix stays
    self-consistent; for a collimated reference the two coincide (defocus ~ 0)."""
    best = None
    total_power = 0.0
    n_beams = 0
    for s in segs:
        if s.get("to") == sensor_name:
            p = s.get("power", 0.0) or 0.0
            total_power += p
            n_beams += 1
            if best is None or p > (best.get("power", 0.0) or 0.0):
                best = s
    if best is None:
        return None, {"n_beams": 0}
    coeffs = list(best.get("aberr")) if best.get("aberr") else [0.0] * physics.N_ZERNIKE
    modal_rms = physics.wavefront_rms(coeffs)
    a4 = _beam_defocus_coeff(best, sensor_aperture_mm)
    if len(coeffs) > 3:
        coeffs[3] += a4                                     # beam curvature -> Noll Z4 (defocus)
    qd = best.get("qd")
    R = physics.beam_roc(complex(qd[0], qd[1])) if qd else float('inf')
    info = {
        "n_beams": n_beams,
        "dominant_frac": ((best.get("power", 0.0) or 0.0) / total_power) if total_power > 0 else 1.0,
        "modal_rms": modal_rms,
        "defocus_waves": a4,
        "beam_roc_mm": R if math.isfinite(R) else None,
        "w_sensor_mm": best.get("w_mm", 0.0) or 0.0,
    }
    return coeffs, info


def _radial_np(n, m, rho):
    import numpy as np
    m = abs(m)
    s = np.zeros_like(rho)
    for k in range((n - m) // 2 + 1):
        num = ((-1) ** k) * math.factorial(n - k)
        den = (math.factorial(k) * math.factorial((n + m) // 2 - k)
               * math.factorial((n - m) // 2 - k))
        s = s + (num / den) * rho ** (n - 2 * k)
    return s


_BASIS_CACHE = {}   # px -> (mask, {j: normalized Z_j basis image}); grid+basis are call-invariant


def _zern_basis(px):
    """Cached unit-disk pupil mask + per-mode normalized Zernike basis images for a px*px grid.
    The grid and each Z_j image are constant across calls, so a wavefront map is just
    sum_j coeff_j * basis_j -- no per-call meshgrid or radial-polynomial recompute."""
    cached = _BASIS_CACHE.get(px)
    if cached is not None:
        return cached
    import numpy as np
    ax = np.linspace(-1.0, 1.0, px)
    xx, yy = np.meshgrid(ax, ax)
    rr = np.sqrt(xx * xx + yy * yy)
    th = np.arctan2(yy, xx)
    basis = {}
    for j, (n, m) in physics._NOLL.items():
        norm = math.sqrt(n + 1) if m == 0 else math.sqrt(2.0 * (n + 1))
        ang = np.cos(m * th) if m >= 0 else np.sin(-m * th)
        basis[j] = norm * _radial_np(n, m, rr) * ang
    cached = (rr <= 1.0, basis)
    _BASIS_CACHE[px] = cached
    return cached


def _modal_field(coeffs, px):
    """The reconstructed wavefront W(x,y)=sum_j a_j Z_j (waves) over a px*px unit-disk grid, plus the
    pupil mask. Shared by wavefront_image and _wavefront_field_stats (cached basis -> a few adds)."""
    import numpy as np
    mask, basis = _zern_basis(px)
    W = np.zeros((px, px))
    for j, c in enumerate(coeffs, start=1):
        if abs(c) < 1e-12 or j not in basis:
            continue
        W += c * basis[j]
    return W, mask


def _wavefront_field_stats(coeffs, px=96):
    """(full_scale, pv) in waves of the reconstructed modal wavefront over the unit disk: full_scale =
    max|W| (the auto colour scale), pv = max - min (peak-to-valley). The static-read caption reports
    these the way the zonal path already does, so the viewer knows what saturated colour means."""
    import numpy as np
    W, mask = _modal_field(coeffs, px)
    wd = W[mask]
    if wd.size == 0:
        return 1.0, 0.0
    return float(np.max(np.abs(wd))), float(np.max(wd) - np.min(wd))


def wavefront_image(coeffs, px=192, vmax=1.0):
    """False-colour RGBA map (HxWx4 float32) of the wavefront W(x,y)=sum_j a_j Z_j over the
    unit disk, on a diverging scale (+-vmax waves): blue (low) -> green (zero) -> red (high).

    ``vmax`` (waves) sets +-full-scale. The FIXED default (1.0) is for the AO loop's before/after
    frames, where a pinned scale must NOT stretch a flattened residual to full contrast (so the
    loop's flattening stays visible). ``vmax=None`` AUTO-scales to the field's max |W|, for a STATIC
    single-shot read (publish_wavefront / the live WFS frame) where there is no before/after context
    and a fixed +-1 would saturate -- a 0.3-wave and a 30-wave map would look identical. The grid +
    the per-mode Zernike basis are cached per px (see _zern_basis), so each call is a few
    scalar-weighted array adds."""
    import numpy as np
    W, mask = _modal_field(coeffs, px)
    if vmax is None:                                       # static read -> auto-scale (zonal-path behaviour)
        wd = W[mask]
        vmax = float(np.max(np.abs(wd))) if wd.size else 1.0
    t = np.clip(0.5 + 0.5 * W / (vmax or 1.0), 0.0, 1.0)   # W=0 -> 0.5 (uniform mid-colour)
    arr = np.empty((px, px, 4), dtype='float32')
    arr[:] = (0.05, 0.05, 0.06, 1.0)                       # outside the pupil
    arr[..., 0] = np.where(mask, t, arr[..., 0])
    arr[..., 1] = np.where(mask, 1.0 - np.abs(2.0 * t - 1.0), arr[..., 1])
    arr[..., 2] = np.where(mask, 1.0 - t, arr[..., 2])
    arr[..., 3] = 1.0
    return arr


# --------------------------------------------------------------------------- #
# PYRAMID wavefront sensor (Phase 3.5): a pyramid WFS measures the local wavefront SLOPE
# (the 4-pupil intensity differences encode dW/dx, dW/dy in the high-modulation regime), where the
# Shack-Hartmann path above reads the modal Zernike vector. From the SAME reconstructed wavefront we
# return the normalized slope maps. NOTE this is a Tier-1 GEOMETRIC model: the chief-ray tracer does NOT
# propagate the pupil-plane field, so this is the gradient a pyramid INTEGRATES, not a diffractive
# 4-pupil image. The defining relation -- for a unit defocus Z4, the x-slope is dZ4/dx = 4*sqrt3*x
# (linear, radial) -- is physics_verify ok=true (DIMENSIONAL + 4*sqrt3 = 6.9282 + slope at x=0.5 = 3.4641).
# --------------------------------------------------------------------------- #

def pyramid_signals(coeffs, px=96):
    """The PYRAMID-WFS signal from a modal wavefront: the normalized SLOPE maps Sx = dW/dx, Sy = dW/dy
    (waves per pupil-radius) over the unit pupil, plus their RMS. A pure DEFOCUS reads a RADIAL slope
    (Sx linear in x: dZ4/dx = 4 sqrt3 x); a TILT reads a UNIFORM slope. Returns {sx, sy (NaN outside the
    pupil), mask, sx_rms, sy_rms, slope_rms}."""
    import numpy as np
    W, mask = _modal_field(coeffs, px)
    dpr = 2.0 / (px - 1)                                   # grid step in pupil-radius units ([-1,1] over px)
    gy, gx = np.gradient(W, dpr)                           # dW/dy (rows), dW/dx (cols)
    sxv, syv = gx[mask], gy[mask]
    sx_rms = float(np.sqrt(np.mean(sxv ** 2))) if sxv.size else 0.0
    sy_rms = float(np.sqrt(np.mean(syv ** 2))) if syv.size else 0.0
    return {"sx": np.where(mask, gx, np.nan), "sy": np.where(mask, gy, np.nan), "mask": mask,
            "sx_rms": sx_rms, "sy_rms": sy_rms, "slope_rms": float(math.hypot(sx_rms, sy_rms))}


def pyramid_slope_image(signals, vmax=None):
    """False-colour RGBA (HxWx4) of a pyramid WFS's slope FIELD: hue = local slope DIRECTION
    atan2(Sy, Sx), value = slope MAGNITUDE |grad W| (auto-scaled, or to ``vmax``). A defocus reads a
    characteristic radial pattern (slope points outward); a tilt reads one uniform colour."""
    import numpy as np
    sx, sy = np.asarray(signals["sx"], dtype=float), np.asarray(signals["sy"], dtype=float)
    mask = signals["mask"]
    mag = np.hypot(np.where(np.isfinite(sx), sx, 0.0), np.where(np.isfinite(sy), sy, 0.0))
    if vmax is None:
        vmax = float(np.nanmax(mag[mask])) if mask.any() else 1.0
    vmax = vmax or 1.0
    hue = (np.arctan2(sy, sx) + math.pi) / (2.0 * math.pi)        # 0..1 slope direction
    val = np.clip(mag / vmax, 0.0, 1.0)
    # HSV (full saturation) -> RGB
    h6 = hue * 6.0
    c = val
    xx = c * (1.0 - np.abs(h6 % 2.0 - 1.0))
    z = np.zeros_like(val)
    seg = h6.astype(int) % 6
    r = np.choose(seg, [c, xx, z, z, xx, c])
    g = np.choose(seg, [xx, c, c, xx, z, z])
    b = np.choose(seg, [z, z, xx, c, c, xx])
    arr = np.empty(sx.shape + (4,), dtype='float32')
    arr[..., 0] = np.where(mask, r, 0.05)
    arr[..., 1] = np.where(mask, g, 0.05)
    arr[..., 2] = np.where(mask, b, 0.06)
    arr[..., 3] = 1.0
    return arr


def publish_wavefront(det, segs):
    """Compute + publish a wavefront sensor's reconstructed map + RMS to the monitor window.

    The reported wavefront is what the sensor PHYSICALLY reads -- the modal aberr PLUS the beam's own
    curvature defocus (see _sensor_wavefront) -- on an AUTO-scaled colour map (a static read has no
    before/after context, so a fixed +-1 scale would saturate and hide magnitude) with the colour
    full-scale, PV, and any multi-beam/defocus context in the caption. A DARK sensor (no beam) clears
    its frame instead of publishing a fake flat RMS=0.000 (a blocked WFS must not read as corrected)."""
    ap = (getattr(det.optics, 'clear_aperture', 0.0) or 0.0) if getattr(det, 'optics', None) else 0.0
    coeffs, info = _sensor_wavefront(segs, det.name, ap)
    if coeffs is None:                                       # nothing reaches the sensor -> clear, don't fake-flat
        monitor.set_frame(det.name, None)
        det.optics.wf_rms = 0.0
        return
    rms = physics.wavefront_rms(coeffs)
    det.optics.wf_rms = rms
    vmax, pv = _wavefront_field_stats(coeffs)
    cap = "wavefront RMS=%.3f  PV=%.3f  full-scale=±%.2f waves" % (rms, pv, vmax or 1.0)
    if abs(info.get("defocus_waves", 0.0)) >= 5e-4:
        cap += " (incl. beam defocus %.3f)" % info["defocus_waves"]
    w_s = info.get("w_sensor_mm", 0.0)
    if ap > 0.0 and w_s > 0.0:                               # fill factor: the modal disc is the unit pupil,
        fill = w_s / ap                                     # so annotate whether the beam under/over-fills it
        if fill > 1.0:
            cap += " [beam overfills aperture → clipped]"
        elif fill < 0.9:
            cap += " [beam fills %.0f%% of aperture]" % (100.0 * fill)
    if info.get("n_beams", 1) > 1:
        cap += " [%d beams, dominant %.0f%%]" % (info["n_beams"], 100.0 * info.get("dominant_frac", 1.0))
    monitor.set_frame(det.name, wavefront_image(coeffs, vmax=vmax), cap)


# --------------------------------------------------------------------------- #
# ZONAL ("sensor render"): a DENSE, raw-field surface-figure wavefront map.
#
# wavefront_image above RE-SUMS 15 Noll Zernikes -- a modal LOW-PASS, correct for
# smooth optics + the AO loop but unable to carry high-spatial-frequency figure.
# The zonal map renders the surface's RAW optical-path field W(x,y) DIRECTLY (sampled
# on a px*px grid via tracer.surface_imprint_field), so mid/high-frequency relief that
# the 15-mode fit smooths away survives, up to the grid's Nyquist limit. It is an
# ON-DEMAND diagnostic: it does NOT touch the trace, so every scene stays byte-identical.
# Same verified physics (W = 2*(depth - reference plane)); the only difference from the
# modal path is NO projection onto 15 modes -- no new optical law.
# --------------------------------------------------------------------------- #

def zonal_wavefront_image(field, vmax=None, bg=(0.05, 0.05, 0.06, 1.0), intensity=None):
    """False-colour RGBA (HxWx4 float32) of a RAW zonal wavefront field W(x,y) in waves (NaN outside the
    pupil / where probes missed), on the SAME diverging blue(low) -> green(zero) -> red(high) scale as
    wavefront_image. ``vmax`` (waves) sets +-full-scale; None -> auto from the field's max |W| (zonal maps
    have a wide dynamic range, so a fixed +-1 would saturate). Unlike wavefront_image (15-mode modal
    re-sum), this maps the field DIRECTLY -- no low-pass. ``intensity`` (the surface_imprint_field beam
    weight, exp(-2*rho^2)) FADES each pixel toward bg by its weight, so the map shows the actual GAUSSIAN
    beam -- bright centre, dim edge -- not a hard top-hat disc (the footprint isn't uniform)."""
    import numpy as np
    F = np.asarray(field, dtype=float)
    valid = ~np.isnan(F)
    if vmax is None:
        vmax = float(np.nanmax(np.abs(F))) if valid.any() else 1.0
    vmax = vmax or 1.0
    t = np.clip(0.5 + 0.5 * np.where(valid, F, 0.0) / vmax, 0.0, 1.0)   # W=0 -> 0.5 (uniform mid-colour)
    h, wd = F.shape
    c0 = np.where(valid, t, bg[0])
    c1 = np.where(valid, 1.0 - np.abs(2.0 * t - 1.0), bg[1])
    c2 = np.where(valid, 1.0 - t, bg[2])
    if intensity is not None:                                # fade the colour toward bg by the beam intensity
        a = np.where(valid & np.isfinite(np.asarray(intensity, dtype=float)),
                     np.clip(np.asarray(intensity, dtype=float), 0.0, 1.0), 0.0)
        c0 = a * c0 + (1.0 - a) * bg[0]
        c1 = a * c1 + (1.0 - a) * bg[1]
        c2 = a * c2 + (1.0 - a) * bg[2]
    arr = np.empty((h, wd, 4), dtype='float32')
    arr[..., 0] = c0
    arr[..., 1] = c1
    arr[..., 2] = c2
    arr[..., 3] = 1.0
    return arr


def zonal_wavefront_at(scene, element_name, segs, px=128, detrend=True, weight='gaussian', rho_max=1.0):
    """On-demand DENSE zonal surface-figure map for a reflective element, reconstructing the incident ray
    (hit point H, direction d, footprint w) from the traced segments -- the "sensor render" entry point.
    Returns tracer.surface_imprint_field(...)'s dict (plus ``element``/``wavelength_nm``) or None if
    nothing reaches the element / it has no usable mesh. Does NOT re-trace or mutate the scene
    (byte-identical) and BYPASSES the 15-mode modal fit, so the map shows real spatial-frequency content.
    ``rho_max`` < 1 clips the figure footprint to the central fraction a downstream aperture (a sensor) lets
    through."""
    import bpy
    from mathutils import Vector
    best = None
    for s in segs:
        if s.get("to") == element_name:
            if best is None or s.get("power", 0.0) > best.get("power", 0.0):
                best = s
    if best is None:
        return None
    E = bpy.data.objects.get(element_name)
    if E is None or best.get("p1") is None or best.get("p2") is None:
        return None
    p1 = Vector(best["p1"])
    p2 = Vector(best["p2"])                                  # segment END = chief-ray hit on the element
    d = p2 - p1                                              # incident direction
    if d.length < 1e-9:
        return None
    w = best.get("w_mm", 0.0) or 0.0
    wl = best.get("wavelength", 632.8) or 632.8
    out = tracer.surface_imprint_field(E, p2, d, w, wl, px=px, detrend=detrend, weight=weight, rho_max=rho_max)
    if out is not None:
        out["element"] = element_name
        out["wavelength_nm"] = wl
    return out


def reflector_feeding(segs, sensor_name):
    """The reflective (imprint-capable) element whose REFLECTED beam reaches ``sensor_name`` -- the ``from``
    of the strongest segment arriving at the sensor, if that element is a MIRROR / PRISM_MIRROR. None if no
    real reflector feeds the sensor (so a 'sensor render' can't pull a wavefront from nothing)."""
    import bpy
    best = None
    for s in segs:
        if s.get("to") == sensor_name and (best is None or s.get("power", 0.0) > best.get("power", 0.0)):
            best = s
    if best is None:
        return None
    E = bpy.data.objects.get(best.get("from") or "")
    if E is not None and getattr(E, "optics", None) and E.optics.element_type in ('MIRROR', 'PRISM_MIRROR'):
        return E.name
    return None


def zonal_wavefront_at_sensor(scene, sensor_name, segs, px=128, detrend=True, weight='gaussian'):
    """The dense ZONAL surface-figure wavefront a WAVEFRONT SENSOR reads: find the reflective element whose
    reflected beam reaches the sensor and render ITS surface figure over the beam footprint -- the honest
    'what the sensor measures'. Returns the field dict (+ ``element`` / ``sensor`` / ``w_sensor_mm`` /
    ``sensor_aperture_mm``) or None if NO reflective element's beam reaches the sensor.

    A FINITE sensor only captures the beam within its clear aperture: a point at the figure footprint radius
    rho (beam radius w_fig) lands at the sensor at radius rho*w_sensor (the beam magnifies transverse position
    by w_sensor/w_fig), so the sensor with semi-aperture a captures only rho <= a/w_sensor of the figure. A
    COLLIMATED beam that fits the sensor keeps the whole figure; a DIVERGING beam that overfills the sensor
    has its outer figure clipped -- the simulation produces the difference, not a manual mask.

    ASSUMES the chief ray lands on the sensor's centre and the aperture is centred on it (the captured region
    is a CENTRED disc rho <= a/w_sensor) -- valid for a nominally on-axis WFS, but a decentred / pointing-error
    beam would clip an OFF-centre region this on-axis model does not capture. If the beam width at the sensor
    is unknown (w_mm not tracked on that segment), ``aperture_applied`` is False and NO clip is applied (the
    whole figure is returned) -- flagged rather than silently treated as a perfect capture."""
    import bpy
    refl = reflector_feeding(segs, sensor_name)
    if refl is None:
        return None
    wfs = bpy.data.objects.get(sensor_name)
    ap = (getattr(wfs.optics, 'clear_aperture', 0.0) or 0.0) if (wfs and getattr(wfs, 'optics', None)) else 0.0
    w_sensor = next((s.get("w_mm", 0.0) for s in segs if s.get("to") == sensor_name), 0.0) or 0.0
    aperture_applied = (ap > 0.0 and w_sensor > 1e-6)
    rho_max = min(1.0, ap / w_sensor) if aperture_applied else 1.0
    out = zonal_wavefront_at(scene, refl, segs, px=px, detrend=detrend, weight=weight, rho_max=rho_max)
    if out is not None:
        out["sensor"] = sensor_name
        out["w_sensor_mm"] = w_sensor
        out["sensor_aperture_mm"] = ap
        out["aperture_applied"] = aperture_applied      # False = beam width at sensor unknown -> clip NOT applied
    return out


# --------------------------------------------------------------------------- #
# B5 - the textbook AO control loop: interaction matrix B, reconstructor R=B+,
#       leaky integrator x_{k+1}=leak*x_k - g*R*w_k, Kolmogorov ABERRATOR(r0).
#
# The reconstructor MATH is plain linear algebra over the ALREADY-oracle-verified
# Zernike modes (physics._NOLL / wavefront_rms): B and R never introduce a new
# optical formula. The ONE new physical relation is the Kolmogorov/Noll turbulence
# variance scaling, sigma^2 = 1.0299*(D/r0)^(5/3) rad^2 (Noll 1976), physics_verify
# ok=true (DIMENSIONAL dimensionless + NUMERIC at D/r0 = 0.5,1,2 + SANITY:positive).
# All of this runs ON DEMAND only (it pokes + re-traces the live scene); a normal
# trace never enters here, so every build_example scene stays byte-identical.
# --------------------------------------------------------------------------- #

# Noll (1976) total residual phase variance over a circular pupil of diameter D for
# Kolmogorov turbulence of Fried parameter r0:  sigma^2 = NOLL_KOLM * (D/r0)^(5/3) rad^2.
NOLL_KOLM = 1.0299
KOLM_EXP = 5.0 / 3.0

# Per-Noll-index residual-variance weights for the LOW-ORDER modes (Noll 1976, Table IV:
# the Delta_j = <residual after correcting j-1 modes> - <after j>, i.e. the variance each mode
# REMOVES, hence the variance it CARRIES). These give turbulence its correct relative spectrum:
# tip/tilt dominate, defocus next, higher orders fall off. Indexed by Noll j (1=piston carries
# none). Values are the standard residual deltas Delta_2..Delta_15 (rad^2 per (D/r0)^(5/3)).
_NOLL_VAR = {
    2: 0.448, 3: 0.448,                       # tip, tilt
    4: 0.0232,                                # defocus
    5: 0.0232, 6: 0.0232,                     # astigmatism
    7: 0.00619, 8: 0.00619,                   # coma
    9: 0.00619, 10: 0.00619,                  # trefoil
    11: 0.00245,                              # spherical
    12: 0.00245, 13: 0.00245,                 # secondary astigmatism
    14: 0.00245, 15: 0.00245,                 # tetrafoil
}


def kolmogorov_aberration(r0_mm, D_mm, n_modes=None, seed=0):
    """Deterministic Kolmogorov/Noll Zernike aberration vector (waves) for a pupil of diameter
    ``D_mm`` under turbulence of Fried parameter ``r0_mm``.

    The TOTAL phase variance over the pupil is the physics_verified Noll relation
        sigma^2 = 1.0299 * (D/r0)^(5/3)   [rad^2]
    and that variance is distributed across the Zernike modes with the Noll residual-variance
    spectrum (_NOLL_VAR): tip/tilt carry the most, higher orders fall off as the well-known
    ~j^(-sqrt3) tail. Each mode's coefficient (in WAVES) is therefore
        a_j = sign_j * sqrt(var_j * (D/r0)^(5/3)) / (2*pi)
    (the /(2*pi) converts the rad RMS to a wave RMS, since 1 wave = 2*pi rad of phase). The
    coefficients are DETERMINISTIC: the sign alternates with a fixed hash of (j, seed), so a
    given (r0, D, seed) always yields the same turbulence frame -- tests are reproducible without
    a real RNG (the headless env forbids one), yet different seeds give different realizations and
    the *variance* obeys the (D/r0)^(5/3) law exactly (so the RMS, = sqrt(variance), scales as
    (D/r0)^(5/6)). Returns a 15-coeff list (piston j=1 = 0)."""
    n = physics.N_ZERNIKE if n_modes is None else min(n_modes, physics.N_ZERNIKE)
    ratio = (max(D_mm, 1e-9) / max(r0_mm, 1e-9)) ** KOLM_EXP     # (D/r0)^(5/3), dimensionless
    coeffs = [0.0] * physics.N_ZERNIKE
    for j in range(2, n + 1):                                    # j=1 piston carries no aberration
        var_rad2 = _NOLL_VAR.get(j, 0.0) * ratio                 # this mode's phase variance [rad^2]
        if var_rad2 <= 0.0:
            continue
        rms_waves = math.sqrt(var_rad2) / (2.0 * math.pi)        # rad RMS -> wave RMS
        # deterministic but mode-varying sign (no RNG): a stable parity of (j*2654435761 ^ seed)
        sign = 1.0 if (((j * 2654435761) ^ (seed * 40503)) >> 3) & 1 else -1.0
        coeffs[j - 1] = sign * rms_waves
    return coeffs


def _np():
    try:
        import numpy as np
        return np
    except Exception:
        return None


def _wfs_response(scene, sensor_name):
    """Re-trace the live scene and read the WFS MODAL residual Zernike vector (waves) via _aberr_at,
    or a flat (zero) vector if nothing reaches the sensor. The single measurement front-end the poke +
    the loop share. This is the DM-correctable modal channel ONLY (turbulence/DM/figure); the static
    read (publish_wavefront / ao_measure) additionally folds in the beam's own curvature defocus via
    _sensor_wavefront, which the DM does not command -- for a collimated reference the two coincide."""
    from . import scan
    tracer.cached_segments = scan._trace(scene)
    c = _aberr_at(tracer.cached_segments, sensor_name)
    return list(c) if c is not None else None


def interaction_matrix(scene, sensor_name, dm_name, poke=0.2, n_modes=None):
    """Build the AO interaction matrix B by POKING each deformable-mirror mode and recording the
    wavefront-sensor modal response: B[:, i] = (w(x + poke*e_i) - w(x)) / poke, exactly the
    finite-difference column build solvers.calibrate_jacobian uses for the steering Jacobian,
    here over the DM's Zernike command channels instead of tip/tilt knobs.

    W = B x is then the WFS-measured wavefront produced by a DM command x. For an ideal modal
    DM (the tracer subtracts dm_command from the aberration) B = -I, but we MEASURE it so any
    real modal cross-talk / un-actuated (null) mode shows up as a small / zero singular value --
    which is precisely what the TSVD reconstructor must drop and the damped-transpose must not
    amplify. Returns (B, w0): B a list of m rows x n cols (m WFS modes, n DM modes), w0 the
    open-loop residual at the current command. Restores the DM command exactly. On-demand only."""
    dm = scene.objects.get(dm_name)
    if dm is None:
        return None, None
    n = physics.N_ZERNIKE if n_modes is None else min(n_modes, physics.N_ZERNIKE)
    base_cmd = list(dm.optics.dm_command)
    w0 = _wfs_response(scene, sensor_name)
    if w0 is None:
        return None, None
    m = len(w0)
    cols = []
    for i in range(n):
        cmd = list(base_cmd)
        cmd[i] = cmd[i] + poke
        dm.optics.dm_command = cmd
        wp = _wfs_response(scene, sensor_name)
        dm.optics.dm_command = list(base_cmd)                    # restore exactly
        if wp is None:
            cols.append([0.0] * m)
            continue
        cols.append([(wp[k] - w0[k]) / poke for k in range(m)])
    # transpose columns -> rows (m x n)
    B = [[cols[i][k] for i in range(n)] for k in range(m)]
    return B, w0


def reconstructor(B, method='TSVD', rcond=1e-3, damping=None):
    """Pseudo-inverse / reconstructor R such that x_correction = R w drives the residual w to zero.

    * 'TSVD'  -> R = B+ via a truncated-SVD pseudoinverse (reuses solvers._pinv_apply's numpy SVD,
      dropping singular values below rcond*sigma_max so an ill-conditioned / near-null mode does
      not blow up). This is the same noise-/rank-tolerant inverse the A7 steering solver uses.
    * 'DAMPED_TRANSPOSE' -> R = c*B^T with c = 1/(sigma_max^2 + lambda) (a damped/steepest-descent
      reconstructor). It NEVER amplifies a small-singular-value mode (its gain on a mode of singular
      value s is c*s <= c*sigma_max < 1), so it is robust to measurement noise on near-null modes --
      it converges more SLOWLY than TSVD but cannot diverge on them.

    Returns R as a list of n rows x m cols (n DM modes, m WFS modes) so x = R w is an n-vector."""
    m = len(B)
    n = len(B[0]) if m else 0
    if m == 0 or n == 0:
        return [[0.0] * m for _ in range(n)]
    np = _np()
    method = str(method).upper()
    if method == 'DAMPED_TRANSPOSE':
        # c scales the transpose so the largest mode's loop gain is < 1 (no null-mode blow-up).
        if np is not None:
            Bm = np.array(B, dtype=float)
            smax = float(np.linalg.svd(Bm, compute_uv=False)[0]) if min(m, n) else 1.0
        else:
            # power-iteration-free bound: largest column 2-norm >= sigma_max / sqrt(n) suffices as a scale
            smax = max((sum(B[k][i] ** 2 for k in range(m)) ** 0.5 for i in range(n)), default=1.0)
        lam = damping if damping is not None else 0.05 * (smax * smax if smax > 0 else 1.0)
        c = 1.0 / (smax * smax + lam) if (smax * smax + lam) > 0 else 0.0
        return [[c * B[k][i] for k in range(m)] for i in range(n)]    # R = c * B^T  (n x m)

    # --- TSVD pseudoinverse R = B+ (drop sigma < rcond*sigma_max) ---
    if np is not None:
        Bm = np.array(B, dtype=float)
        U, s, Vt = np.linalg.svd(Bm, full_matrices=False)
        smax = s[0] if s.size else 0.0
        cut = rcond * smax
        s_inv = np.array([(1.0 / si if si > cut else 0.0) for si in s])
        R = (Vt.T * s_inv) @ U.T                                  # B+ = V S+ U^T  (n x m)
        return [[float(v) for v in row] for row in R]
    # pure-python fallback: column-by-column least-squares solve B x = e_k via solvers._pinv_apply
    from . import solvers
    R = []
    for k in range(m):
        ek = [1.0 if i == k else 0.0 for i in range(m)]
        R.append(solvers._pinv_apply(B, ek, rcond=rcond))        # x solving B x ~= e_k  -> column k of B+
    # R built row-per-WFS-mode (m rows x n cols) -> transpose to n x m
    return [[R[k][i] for k in range(m)] for i in range(n)]


def _matvec(R, w):
    """R (n x m) times w (m) -> n-vector. Plain python so it needs no numpy."""
    return [sum(R[i][k] * w[k] for k in range(len(w))) for i in range(len(R))]


def close_loop_recon(scene, sensor_name, dm_name, gain=0.8, leak=0.99,
                     method='TSVD', iters=30, tol=1.0e-3, poke=0.2, B=None):
    """The textbook AO closed loop (B5): build the interaction matrix B (poke + record), invert it
    to a reconstructor R = B+ (TSVD) or R = c*B^T (damped transpose), then run the LEAKY INTEGRATOR

        x_{k+1} = leak * x_k - gain * R * w_k

    where w_k is the WFS residual Zernike vector at step k and x is the DM command. ``gain`` ~0.8,
    ``leak`` ~0.99 (a slowly-forgetting integrator -> robust to a static reconstructor error /
    drift). Stops when the residual RMS < ``tol`` or a relative plateau is hit or ``iters`` pass.

    Returns a JSON-able report:
      {ok, method, rms_before, rms_after, reduction (rms_before/rms_after), iterations, converged,
       history:[rms0, rms1, ...] (waves, open-loop first, corrected last), n_modes, leak, gain,
       singular:[s0..]}. ON-DEMAND only (it pokes + re-traces); a normal trace is untouched.

    Pass a pre-built ``B`` to reuse an interaction matrix across runs (e.g. inject measurement
    noise into the loop while keeping the same calibration)."""
    dm = scene.objects.get(dm_name)
    wfs = scene.objects.get(sensor_name)
    if dm is None or wfs is None:
        return {"ok": False, "error": "need a wavefront sensor + deformable mirror"}

    if B is None:
        B, _w0 = interaction_matrix(scene, sensor_name, dm_name, poke=poke)
    if B is None:
        return {"ok": False, "error": "no beam between the sensor and the deformable mirror"}
    R = reconstructor(B, method=method)
    n = len(R)

    # singular spectrum of B (diagnostic: TSVD drops the modes below the cutoff)
    singular = []
    np = _np()
    if np is not None and len(B):
        singular = [float(s) for s in np.linalg.svd(np.array(B, dtype=float), compute_uv=False)]

    x = list(dm.optics.dm_command)
    hist = []
    converged = False
    for _ in range(max(1, int(iters))):
        w = _wfs_response(scene, sensor_name)
        if w is None:
            converged = True
            break
        rms = physics.wavefront_rms(w)
        hist.append(rms)
        delta = (hist[-2] - rms) if len(hist) >= 2 else None
        stalled = delta is not None and 0.0 <= delta < 1.0e-4 * max(hist[-2], 1.0e-12)
        if rms < tol or stalled:
            converged = True
            break
        dx = _matvec(R, w)                                       # R * w_k  (n-vector)
        x = [leak * x[i] - gain * dx[i] for i in range(min(len(x), n))] + list(x[n:])
        dm.optics.dm_command = list(x)
    if not converged:                                           # measure the final applied command once
        w = _wfs_response(scene, sensor_name)
        if w is not None:
            hist.append(physics.wavefront_rms(w))
    if hist:
        wfs.optics.wf_rms = hist[-1]
    r_before = hist[0] if hist else 0.0
    r_after = hist[-1] if hist else 0.0
    return {
        "ok": True,
        "method": method,
        "rms_before": round(r_before, 6),
        "rms_after": round(r_after, 6),
        "reduction": round(r_before / r_after, 3) if r_after > 1e-12 else float('inf'),
        "iterations": len(hist) - 1,
        "converged": bool(converged),
        "history": [round(h, 6) for h in hist],
        "n_modes": n,
        "leak": leak,
        "gain": gain,
        "singular": [round(s, 6) for s in singular],
    }


def close_loop(scene, sensor_name, dm_name, gain=0.5, iters=15, tol=1.0e-3):
    """Modal AO integrator: each step trace -> read residual Zernike at the sensor -> accumulate
    the DM command toward it (dm_command += gain*residual) -> repeat until the wavefront is flat
    (residual RMS < tol) or genuinely STALLS (<0.1% relative improvement per step) or `iters` is
    reached. Returns the RMS history (waves), open-loop value first, corrected last. Stops early
    once converged, so a fast loop costs a handful of traces instead of the full `iters`."""
    from . import scan
    wfs = scene.objects.get(sensor_name)
    dm = scene.objects.get(dm_name)
    if wfs is None or dm is None:
        return None
    hist = []
    converged = False
    for _ in range(max(1, int(iters))):
        tracer.cached_segments = scan._trace(scene)
        coeffs = _aberr_at(tracer.cached_segments, sensor_name)
        if coeffs is None:
            converged = True
            break
        rms = physics.wavefront_rms(coeffs)
        hist.append(rms)                                   # this trace already reflects every command applied so far
        # Converge on the absolute residual; stall ONLY on a relative plateau (no real progress).
        # Reusing `tol` for the step-delta declared "converged" far above tol at low gain, because a
        # modal integrator shrinks the residual geometrically (delta ~ gain*residual), so the delta
        # drops below tol while the residual is still ~tol/gain.
        # plateau = tiny but NON-NEGATIVE progress; a negative delta means the residual GREW
        # (divergence) and must keep correcting, not be mistaken for a converged plateau
        delta = (hist[-2] - rms) if len(hist) >= 2 else None
        stalled = delta is not None and 0.0 <= delta < 1.0e-3 * max(hist[-2], 1.0e-12)
        if rms < tol or stalled:
            converged = True
            break
        cmd = list(dm.optics.dm_command)
        for i in range(min(len(cmd), len(coeffs))):
            cmd[i] += gain * coeffs[i]
        dm.optics.dm_command = cmd
    if not converged:                                      # ran out of iters: measure the last applied command once
        tracer.cached_segments = scan._trace(scene)
        final = _aberr_at(tracer.cached_segments, sensor_name)
        if final is not None:
            hist.append(physics.wavefront_rms(final))
    if hist:
        wfs.optics.wf_rms = hist[-1]
    return hist


class OPTICS_OT_ao_close_loop(Operator):
    bl_idname = "optics.ao_close_loop"
    bl_label = "Run AO Loop"
    bl_description = ("Close the adaptive-optics loop: the wavefront sensor measures the residual "
                      "Zernike error and drives the deformable mirror until it flattens")
    bl_options = {'REGISTER', 'UNDO'}

    sensor: StringProperty(name="Wavefront sensor")
    dm: StringProperty(name="Deformable mirror")
    gain: FloatProperty(name="Loop gain", default=0.8, min=0.0, max=2.0)
    iters: IntProperty(name="Iterations", default=30, min=1, max=200)
    use_reconstructor: BoolProperty(name="Use reconstructor (B5)", default=True,
        description="Run the B5 interaction-matrix + reconstructor + leaky-integrator loop; "
                    "off = the legacy modal integrator")
    method: EnumProperty(name="Reconstructor", default='TSVD',
        items=[('TSVD', "Truncated SVD", "R = B+ via SVD (fast, ill-cond-tolerant)"),
               ('DAMPED_TRANSPOSE', "Damped transpose", "R = c*B^T (noise-tolerant, slower)")])
    leak: FloatProperty(name="Integrator leak", default=0.99, min=0.0, max=1.0)

    def invoke(self, context, event):
        scene = context.scene
        if not self.sensor:
            self.sensor = next((o.name for o in scene.objects if getattr(o, "optics", None)
                                and o.optics.element_type == 'WAVEFRONT_SENSOR'), "")
        if not self.dm:
            self.dm = next((o.name for o in scene.objects if getattr(o, "optics", None)
                            and o.optics.element_type == 'DEFORMABLE_MIRROR'), "")
        self.method = scene.optics.ao_recon
        self.leak = scene.optics.ao_leak
        self.gain = scene.optics.ao_loop_gain
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        col = self.layout.column()
        col.prop_search(self, "sensor", context.scene, "objects")
        col.prop_search(self, "dm", context.scene, "objects")
        col.prop(self, "use_reconstructor")
        if self.use_reconstructor:
            col.prop(self, "method")
            col.prop(self, "leak")
        col.prop(self, "gain")
        col.prop(self, "iters")

    def execute(self, context):
        scene = context.scene
        if self.use_reconstructor:
            res = close_loop_recon(scene, self.sensor, self.dm, gain=self.gain, leak=self.leak,
                                   method=self.method, iters=self.iters)
            if not res.get("ok"):
                self.report({'ERROR'}, res.get("error", "AO loop failed"))
                return {'CANCELLED'}
            hist = res["history"]
            msg = ("AO %s loop: RMS %.3f -> %.3f waves (%.1fx) over %d iters"
                   % (self.method, res["rms_before"], res["rms_after"],
                      res["reduction"] if res["reduction"] != float('inf') else 0.0, res["iterations"]))
        else:
            hist = close_loop(scene, self.sensor, self.dm, self.gain, self.iters)
            if not hist:
                self.report({'ERROR'}, "Pick a wavefront sensor + deformable mirror with a beam between them")
                return {'CANCELLED'}
            msg = ("AO loop: RMS %.3f -> %.3f waves over %d iters"
                   % (hist[0], hist[-1], len(hist) - 1))
        from . import scan
        scene.optics.monitor_show = True
        scan.live_fringe_update(scene)
        tracer._tag_redraw()
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class OPTICS_OT_dm_flatten(Operator):
    bl_idname = "optics.dm_flatten"
    bl_label = "Flatten Deformable Mirror"
    bl_description = "Zero the active deformable mirror's command (remove all correction)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.object
        if ob is None or getattr(ob, "optics", None) is None or ob.optics.element_type != 'DEFORMABLE_MIRROR':
            self.report({'ERROR'}, "Select a deformable mirror")
            return {'CANCELLED'}
        ob.optics.dm_command = [0.0] * physics.N_ZERNIKE
        try:
            from . import scan
            tracer.cached_segments = scan._trace(context.scene)
            scan.live_fringe_update(context.scene)
        except Exception:
            pass
        tracer._tag_redraw()
        self.report({'INFO'}, "Flattened %s" % ob.name)
        return {'FINISHED'}


class OPTICS_OT_wfs_zonal_render(Operator):
    bl_idname = "optics.wfs_zonal_render"
    bl_label = "Render Zonal Wavefront Map"
    bl_description = ("Sensor render: sample the ACTIVE reflective element's actual mesh surface densely "
                      "over the beam footprint and write a ZONAL wavefront map (raw optical-path field, "
                      "no 15-mode modal low-pass) so high-spatial-frequency figure is faithful. "
                      "On-demand only -- does not touch the trace")
    bl_options = {'REGISTER'}

    px: IntProperty(name="Sampling level (px)", default=160, min=16, max=512,
                    description="Grid resolution across the footprint diameter; higher -> finer Nyquist")

    def invoke(self, context, event):
        ob = context.object
        if ob is not None and getattr(ob, "optics", None) is not None:
            self.px = getattr(ob.optics, "imprint_zonal_px", self.px)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        self.layout.prop(self, "px")

    def execute(self, context):
        scene = context.scene
        ob = context.object
        et = ob.optics.element_type if (ob is not None and getattr(ob, "optics", None) is not None) else None
        if et not in ('MIRROR', 'PRISM_MIRROR', 'WAVEFRONT_SENSOR'):
            self.report({'ERROR'}, "Select a wavefront sensor (reads the reflected beam) or a reflective mirror")
            return {'CANCELLED'}
        from . import scan
        segs = scan._trace(scene)
        tracer.cached_segments = segs
        wfs = None
        if et == 'WAVEFRONT_SENSOR':
            # render FROM the sensor: the figure of the reflector whose reflected beam reaches it (honest path)
            wfs = ob.name
            refl = reflector_feeding(segs, ob.name)
            if refl is None:
                self.report({'ERROR'}, "No reflective (imprint) element's beam reaches %s -- angle a figured "
                                       "reflector's reflection into it" % ob.name)
                return {'CANCELLED'}
            fld = zonal_wavefront_at(scene, refl, segs, px=int(self.px))
            target = refl
        else:
            target = ob.name
            fld = zonal_wavefront_at(scene, ob.name, segs, px=int(self.px))
            # the sensor this reflector feeds (so the map publishes to the WFS that actually reads it)
            wfs = next((s.get("to") for s in segs if s.get("from") == ob.name
                        and scene.objects.get(s.get("to") or "") is not None
                        and getattr(scene.objects[s["to"]].optics, "element_type", "") == 'WAVEFRONT_SENSOR'), None)
        if fld is None:
            self.report({'ERROR'}, "No beam footprint on %s" % target)
            return {'CANCELLED'}
        try:
            scene.objects[target].optics.imprint_zonal_px = int(self.px)
        except Exception:
            pass
        import numpy as np
        img = np.flipud(zonal_wavefront_image(fld["field"], intensity=fld.get("intensity")))  # bottom-up + beam fade
        h, wd = img.shape[0], img.shape[1]
        bi = bpy.data.images.get("zonal_wavefront") or bpy.data.images.new("zonal_wavefront", wd, h, alpha=True)
        if tuple(bi.size) != (wd, h):
            bpy.data.images.remove(bi)
            bi = bpy.data.images.new("zonal_wavefront", wd, h, alpha=True)
        bi.pixels.foreach_set(img.astype('float32').ravel())
        import os
        out = os.path.join(bpy.app.tempdir or "/tmp", "zonal_wavefront.png")
        bi.filepath_raw = out
        bi.file_format = 'PNG'
        bi.save()
        sens = wfs or "(no sensor reads this reflector)"
        cap = ("ZONAL %s -> %s  RMS=%.3f waves (beam-wtd; %.3f uniform)  PV=%.3f  %dpx  hits=%.0f%%"
               % (target, sens, fld["rms_gauss"], fld["rms_uniform"], fld["pv_waves"], fld["px"],
                  100.0 * fld["hit_frac"]))
        if wfs is not None:                                # publish to the WFS that actually reads this beam
            monitor.set_frame(wfs, zonal_wavefront_image(fld["field"], intensity=fld.get("intensity")), cap)
            scene.optics.monitor_show = True
        tracer._tag_redraw()
        self.report({'INFO'}, cap + "  ->  " + out)
        return {'FINISHED'}


_classes = (OPTICS_OT_ao_close_loop, OPTICS_OT_dm_flatten, OPTICS_OT_wfs_zonal_render)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
