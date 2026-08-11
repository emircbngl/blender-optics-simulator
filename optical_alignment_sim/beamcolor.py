"""Beam colour convention: wavelength -> RGB, for every visualization surface.

ONE source of truth. `bake.py` (render materials), `overlay.py` (viewport) and
`svg_export.py` (schematic figures) all call `wavelength_rgb()` here, so a 589 nm beam
reads the same sodium-yellow while you drag it, when you render it, and in the exported
figure. Before this module each of the three carried its own copy of the curve and they
had drifted apart (different green plateau, different out-of-band handling).

This is a VISUALIZATION convention, not radiometry. Out-of-band light is invisible in
reality, but a black tube reads as "no beam" on a bench you are trying to design, so IR
and UV get a false colour by default -- the standard optics-figure convention (a 1064 nm
pump drawn dark red next to its bright green 532 nm harmonic).

The out-of-band ramp exists because a *constant* out-of-band colour is not enough: an OPO
bench carries 1064 / 1550 / 3394 nm at once, and three identical dark-red lines cannot be
told apart. Colour therefore keeps moving past the band edge (dim, but distinguishable).

bpy-free on purpose, so it self-tests in a bare interpreter:

    python3 optical_alignment_sim/beamcolor.py
"""
from __future__ import annotations

import math

# The human visible band. In-band colour is the curve that shipped in bake.py and is kept
# bit-for-bit: existing scenes must not shift hue because this module appeared.
VISIBLE_MIN_NM = 380.0
VISIBLE_MAX_NM = 780.0

# Ramp ends: the outermost transparency edges in physics.GLASS_RANGE_UM, so the ramp spends
# its whole range on light a bench in this add-on can actually carry. ZnSe reaches 18.2 um
# (Ge's 14 um and the CO2 line at 10.6 um sit inside it); the shortest UV edge is 0.20 um
# (MgF2, crystal quartz). Past these the ramp clamps and colours collapse again -- the very
# failure it exists to prevent -- so widen them before adding a more exotic material. A line
# outside every material's window clamps to the end stop, which is the honest reading: no
# optic in this catalog claims to transmit it.
IR_RAMP_MAX_NM = 18200.0
UV_RAMP_MIN_NM = 200.0

# How an out-of-band beam is drawn. In-band beams ignore this entirely.
OOB_MODES = ('FALSE_COLOR', 'HIDE', 'VIVID')

# Emission strength for the baked beam material: out-of-band glows dimmer so an IR pump
# reads as a dark ember next to its harmonic. VIVID drops that penalty on purpose.
EMISSION_IN_BAND = 25.0
EMISSION_OUT_OF_BAND = 14.0

# FALSE_COLOR ramps. The t=0 stop of each is the constant colour this used to be, so a
# beam sitting just past the band edge does not jump now that the ramp exists.
_IR_STOPS = ((0.0, (0.55, 0.02, 0.02)),      # 780 nm  deep crimson (the legacy constant)
             (0.35, (0.42, 0.16, 0.05)),     # ~2.4 um brick
             (1.0, (0.30, 0.22, 0.18)))      # 18.2 um warm grey
_UV_STOPS = ((0.0, (0.35, 0.08, 0.55)),      # 380 nm  violet (the legacy constant)
             (0.5, (0.18, 0.06, 0.60)),      # 290 nm  deep blue-violet
             (1.0, (0.10, 0.03, 0.45)))      # 200 nm  near-black indigo

# VIVID ramps: full brightness, for figures where the invisible beams still have to be the
# subject. Keeps the warm=IR / cool=UV intuition so the direction is still readable.
_IR_VIVID = ((0.0, (1.0, 0.15, 0.0)),
             (0.5, (1.0, 0.45, 0.0)),
             (1.0, (1.0, 0.85, 0.10)))
_UV_VIVID = ((0.0, (0.65, 0.25, 1.0)),
             (0.5, (0.35, 0.35, 1.0)),
             (1.0, (0.15, 0.75, 1.0)))


def _visible_rgb(w):
    """Visible-band wavelength -> linear RGB (Bruton-style piecewise approximation).

    Unchanged from the curve that shipped in bake.py, including the two shaping choices
    tuned against real laser lines: the flat green plateau (532 nm must READ laser-green)
    and the squared red falloff (633 nm must stay laser-red rather than blooming
    yellow-orange, while 589 nm still reads sodium-yellow)."""
    if w < 440.0:
        r, g, b = (440.0 - w) / 60.0, 0.0, 1.0
    elif w < 490.0:
        r, g, b = 0.0, (w - 440.0) / 50.0, 1.0
    elif w < 510.0:
        r, g, b = 0.0, 1.0, (510.0 - w) / 20.0
    elif w < 545.0:
        r, g, b = 0.0, 1.0, 0.0
    elif w < 580.0:
        r, g, b = (w - 545.0) / 35.0, 1.0, 0.0
    elif w < 645.0:
        r, g, b = 1.0, ((645.0 - w) / 65.0) ** 2, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    # gentle intensity roll-off at the band edges (keeps 633 nm at full brightness)
    if w < 420.0:
        f = 0.3 + 0.7 * (w - 380.0) / 40.0
    elif w > 700.0:
        f = 0.3 + 0.7 * (780.0 - w) / 80.0
    else:
        f = 1.0
    return r * f, g * f, b * f


def _ramp(stops, t):
    """Piecewise-linear interpolation through (position, rgb) stops; t clamped to [0, 1]."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return stops[-1][1]


def is_out_of_band(wl_nm):
    """True if this wavelength is invisible to the eye (and so subject to the OOB mode)."""
    return not (VISIBLE_MIN_NM <= float(wl_nm) <= VISIBLE_MAX_NM)


def wavelength_rgb(wl_nm, mode='FALSE_COLOR'):
    """Wavelength (nm) -> linear RGB in 0..1, or **None** when the beam should not be drawn.

    In-band light ignores `mode` and always gets its true colour. Out-of-band light follows
    the scene's OOB mode:

    - ``FALSE_COLOR`` (default) dim IR/UV ramps -- visible, distinguishable, and still
      legible as "this light is not really visible".
    - ``HIDE`` returns None; the caller drops the beam. Lets you watch only the 532 nm
      harmonic on an SHG bench without the pump crossing it.
    - ``VIVID`` full-brightness false colour, for figures where the invisible beam is the
      point. Explicitly non-physical.

    A None return is the *only* falsy result; callers must test ``is None``, not truthiness
    (black, (0, 0, 0), is a legitimate colour)."""
    w = float(wl_nm)
    if VISIBLE_MIN_NM <= w <= VISIBLE_MAX_NM:
        return _visible_rgb(w)
    if mode == 'HIDE':
        return None
    vivid = (mode == 'VIVID')
    if w > VISIBLE_MAX_NM:
        # log position: IR spans 780 nm -> 14 um, so a linear ramp would squash the whole
        # near-IR (where the benches actually live) into the first few percent
        span = math.log(IR_RAMP_MAX_NM / VISIBLE_MAX_NM)
        t = math.log(max(w, VISIBLE_MAX_NM) / VISIBLE_MAX_NM) / span
        return _ramp(_IR_VIVID if vivid else _IR_STOPS, t)
    t = (VISIBLE_MIN_NM - w) / (VISIBLE_MIN_NM - UV_RAMP_MIN_NM)
    return _ramp(_UV_VIVID if vivid else _UV_STOPS, t)


def emission_strength(wl_nm, mode='FALSE_COLOR'):
    """Emission node strength for the baked beam material (see EMISSION_* above)."""
    if mode == 'VIVID' or not is_out_of_band(wl_nm):
        return EMISSION_IN_BAND
    return EMISSION_OUT_OF_BAND


def wavelength_rgb255(wl_nm, mode='FALSE_COLOR'):
    """As `wavelength_rgb`, quantized to 0-255 ints for SVG/CSS. None stays None."""
    c = wavelength_rgb(wl_nm, mode)
    if c is None:
        return None
    return tuple(int(255 * v) for v in c)


if __name__ == "__main__":
    import sys

    fails = []

    def close(a, b, tol=1e-9):
        return abs(a - b) <= tol

    # --- 1. in-band colour is bit-for-bit the curve that shipped in bake.py -------------
    def _legacy_bake_rgb(w):
        """The pre-refactor bake.wavelength_rgb, transcribed to pin the in-band curve."""
        if w < 380.0:
            r, g, b = 0.35, 0.08, 0.55
        elif w < 440.0:
            r, g, b = (440.0 - w) / 60.0, 0.0, 1.0
        elif w < 490.0:
            r, g, b = 0.0, (w - 440.0) / 50.0, 1.0
        elif w < 510.0:
            r, g, b = 0.0, 1.0, (510.0 - w) / 20.0
        elif w < 545.0:
            r, g, b = 0.0, 1.0, 0.0
        elif w < 580.0:
            r, g, b = (w - 545.0) / 35.0, 1.0, 0.0
        elif w < 645.0:
            r, g, b = 1.0, ((645.0 - w) / 65.0) ** 2, 0.0
        elif w <= 780.0:
            r, g, b = 1.0, 0.0, 0.0
        else:
            r, g, b = 0.55, 0.02, 0.02
        if 380.0 <= w < 420.0:
            f = 0.3 + 0.7 * (w - 380.0) / 40.0
        elif 700.0 < w <= 780.0:
            f = 0.3 + 0.7 * (780.0 - w) / 80.0
        else:
            f = 1.0
        return r * f, g * f, b * f

    w = VISIBLE_MIN_NM
    while w <= VISIBLE_MAX_NM:
        got, want = wavelength_rgb(w), _legacy_bake_rgb(w)
        if not all(close(a, b) for a, b in zip(got, want)):
            fails.append("in-band %.1f nm drifted: %s != legacy %s" % (w, got, want))
            break
        w += 0.5

    # real laser lines must still read as themselves
    if wavelength_rgb(532.0) != (0.0, 1.0, 0.0):
        fails.append("532 nm is not pure laser-green: %s" % (wavelength_rgb(532.0),))
    if not (wavelength_rgb(632.8)[0] == 1.0 and wavelength_rgb(632.8)[1] < 0.05):
        fails.append("632.8 nm is not laser-red: %s" % (wavelength_rgb(632.8),))

    # --- 2. the band edges are continuous with the old constants ------------------------
    for edge, legacy in ((VISIBLE_MAX_NM + 1e-9, (0.55, 0.02, 0.02)),
                         (VISIBLE_MIN_NM - 1e-9, (0.35, 0.08, 0.55))):
        got = wavelength_rgb(edge)
        if not all(close(a, b, 1e-6) for a, b in zip(got, legacy)):
            fails.append("band edge %.1f jumps: %s != legacy constant %s" % (edge, got, legacy))

    # --- 3. the whole point: out-of-band lines are DISTINGUISHABLE ----------------------
    def sep(a, b):
        return max(abs(x - y) for x, y in zip(wavelength_rgb(a), wavelength_rgb(b)))

    # an OPO bench: pump / signal / idler must not collapse to one colour (they used to)
    for a, b in ((1064.0, 1550.0), (1550.0, 3393.4), (1064.0, 3393.4)):
        if sep(a, b) < 0.02:
            fails.append("IR %.0f vs %.0f nm indistinguishable (max channel delta %.4f)"
                         % (a, b, sep(a, b)))
    # Nd:YAG 3rd vs 4th harmonic in the UV
    if sep(354.67, 266.0) < 0.02:
        fails.append("UV 355 vs 266 nm indistinguishable (max channel delta %.4f)"
                     % sep(354.67, 266.0))

    # the ramp must be monotone in the red channel, so "redder = nearer the visible" holds
    ir = [wavelength_rgb(x)[0] for x in (800.0, 1064.0, 1550.0, 3393.4, 10600.0)]
    if any(b > a + 1e-12 for a, b in zip(ir, ir[1:])):
        fails.append("IR red channel is not monotone decreasing: %s" % (ir,))

    # --- 4. modes ----------------------------------------------------------------------
    if wavelength_rgb(1064.0, 'HIDE') is not None:
        fails.append("HIDE did not drop an out-of-band beam")
    if wavelength_rgb(532.0, 'HIDE') is None:
        fails.append("HIDE dropped an IN-band beam (it must only affect IR/UV)")
    for mode in OOB_MODES:                       # in-band is mode-independent
        if wavelength_rgb(632.8, mode) != wavelength_rgb(632.8):
            fails.append("in-band colour changed under mode %s" % mode)
    if not (sum(wavelength_rgb(1064.0, 'VIVID')) > sum(wavelength_rgb(1064.0)) + 0.5):
        fails.append("VIVID is not brighter than FALSE_COLOR at 1064 nm")
    if emission_strength(1064.0) >= emission_strength(532.0):
        fails.append("out-of-band emission is not dimmer than in-band")
    if emission_strength(1064.0, 'VIVID') != EMISSION_IN_BAND:
        fails.append("VIVID did not drop the out-of-band emission penalty")

    # --- 5. range hygiene: every channel stays in gamut, nothing returns NaN ------------
    for mode in OOB_MODES:
        for x in (1.0, 100.0, 200.0, 380.0, 532.0, 780.0, 781.0, 5000.0, 14000.0, 50000.0):
            c = wavelength_rgb(x, mode)
            if c is None:
                continue
            if not all(0.0 <= v <= 1.0 and v == v for v in c):
                fails.append("out of gamut at %.1f nm mode %s: %s" % (x, mode, c))

    if fails:
        print("BEAMCOLOR SELFTEST FAILED:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("BEAMCOLOR SELFTEST PASSED")
