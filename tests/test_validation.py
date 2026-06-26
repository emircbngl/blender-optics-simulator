"""Textbook-validation suite — reproduce canonical optics-textbook problems and assert our kernels
match the known closed-form / datasheet answers.

Every CLOSED-FORM expected value below is physics_verify ok=true against the physicist Docker oracle
(angles cross-checked in radians, then converted to the kernel's degree convention); values marked
[datasheet] are manufacturer/literature constants (SCHOTT/Malitson) validated against the published
catalog figure, not oracle-derivable. This is the "be sure it's correct" gate — separate from
test_optics.py (which pins pipeline/byte-identical behavior).

Run:  blender --background --factory-startup --python tests/test_validation.py
Lives outside the add-on package, so the extension zip never ships it.
"""
import bpy, sys, os, math

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import physics, design

_checks = []


def check(name, got, expected, tol, src):
    ok = (got is not None) and abs(got - expected) <= tol
    _checks.append(ok)
    shown = float('nan') if got is None else got
    print("  [%s] %-52s got %.6g  expect %.6g (+/-%.2g)  (%s)"
          % ("PASS" if ok else "FAIL", name, shown, expected, tol, src))


print("=" * 60)
print("[Interface & prism — geometric optics]")
check("Brewster air->glass n=1.5 (atan 1.5)", physics.brewster_angle(1.0, 1.5), 56.30993, 1e-3, "Hecht; oracle")
check("Critical glass n=1.5->air (asin 1/1.5)", physics.critical_angle(1.5, 1.0), 41.81031, 1e-3, "Hecht; oracle")
check("Critical: none when n2>=n1", 1.0 if physics.critical_angle(1.0, 1.5) is None else 0.0, 1.0, 0.0, "definition")
check("Fresnel normal-incidence R, n=1.5", physics.surface_reflectance(1.0, 1.5), 0.04, 1e-4, "Hecht; oracle")
check("Prism min deviation A=60,n=sqrt2", physics.prism_min_deviation(math.sqrt(2.0), 60.0), 30.0, 1e-3, "Pedrotti; oracle")

print("[Material dispersion — Sellmeier n(lambda)]")
check("n_d N-BK7 @587.56nm", physics.sellmeier_n(587.56, 'N-BK7'), 1.51680, 5e-5, "SCHOTT [datasheet]")
check("n_d N-SF11 @587.56nm", physics.sellmeier_n(587.56, 'N-SF11'), 1.78472, 5e-5, "SCHOTT [datasheet]")
check("n_d CaF2 @587.56nm", physics.sellmeier_n(587.56, 'CaF2'), 1.43385, 5e-5, "Malitson1963 [datasheet]")
check("Abbe number Vd N-BK7", physics.abbe_number('N-BK7'), 64.17, 0.15, "SCHOTT [datasheet]")


def fc_focal_shift(glass, f=100.0):
    """Longitudinal chromatic focal shift f_C - f_F using f_eff = f*(n_d-1)/(n_lambda-1)."""
    nd = physics.sellmeier_n(587.56, glass)
    nF = physics.sellmeier_n(486.13, glass)
    nC = physics.sellmeier_n(656.27, glass)
    return f * (nd - 1.0) / (nC - 1.0) - f * (nd - 1.0) / (nF - 1.0)


bk7_shift = fc_focal_shift('N-BK7')
sf11_shift = fc_focal_shift('N-SF11')
check("Lens F->C chromatic shift, N-BK7 f=100mm", bk7_shift, 1.55, 0.15, "Hecht ballpark ~1.5mm")
check("lens_glass works: N-SF11/N-BK7 shift ratio ~Vd ratio 2.5", sf11_shift / bk7_shift, 2.5, 0.6, "Vd 64.2/25.7")

print("[Gaussian beam — ABCD]")
zR = physics.q_from_waist(1.0, 632.8).imag
check("Rayleigh range zR=pi w0^2/lambda (w0=1mm,632.8nm)", zR, 4964.59, 1.0, "Saleh&Teich; oracle")
q = physics.q_from_waist(1.0, 632.8)
q = physics.q_propagate(q, physics.abcd_lens(100.0))
q = physics.q_propagate(q, physics.abcd_free(100.0))
check("Gaussian focal spot w=lambda f/(pi w0)", physics.beam_radius(q, 632.8), 0.0201426, 1e-5, "Saleh&Teich; oracle")
check("Far-field divergence lambda/(pi w0) (1mm,1064nm,rad)", physics.gaussian_divergence(1.0, 1064.0, 1.0), 3.38682e-4, 1e-7, "Siegman; oracle")

print("[Cavity, grating, designers, polarization]")
check("Fabry-Perot finesse pi sqrt(R)/(1-R), R=0.9", physics.cavity_finesse(0.9), 29.804, 1e-2, "Saleh&Teich; oracle")
check("Grating 600 l/mm m=1 633nm normal", physics.grating_angle(600.0, 1, 633.0, 0.0), 22.3214, 1e-3, "Hecht; oracle")
tel = design.design_telescope(200.0, 40.0)
check("Telescope angular mag |f1/f2| (200,40)", abs(tel["angular_mag"]), 5.0, 1e-6, "afocal; oracle")
exp = design.design_telescope(25.0, 200.0)
check("Beam-expander mag |f2/f1| (25,200)", exp["beam_expansion"], 8.0, 1e-6, "afocal; oracle")
f4 = design.design_4f(100.0, 200.0)
check("4f relay transverse mag -f2/f1 (100,200)", f4["transverse_mag"], -2.0, 1e-6, "Fourier optics; oracle")
img_i, img_m = physics.thin_lens_image(100.0, 150.0)
check("Thin-lens image distance 1/o+1/i=1/f (f=100,o=150)", img_i, 300.0, 1e-6, "Hecht; oracle")
check("Thin-lens magnification m=-i/o", img_m, -2.0, 1e-6, "Hecht; oracle")
g_stab, stable = physics.cavity_stability(0.5, 0.5)
check("Cavity stable g1g2=0.25 in [0,1]", 1.0 if stable else 0.0, 1.0, 0.0, "Siegman; definition")
_, unstable = physics.cavity_stability(2.0, 2.0)
check("Cavity unstable g1g2=4 outside [0,1]", 0.0 if unstable else 1.0, 1.0, 0.0, "Siegman; definition")
malus = physics.intensity(physics.apply(physics.M_polarizer(45.0, extinction=1.0e6), physics.jones_linear(0.0)))
check("Malus law I=cos^2(45deg)", malus, 0.5, 1e-3, "Hecht; oracle")

print("=" * 60)
n_pass = sum(_checks)
n_total = len(_checks)
if n_pass == n_total:
    print("VALIDATION PASS  (%d/%d textbook checks)" % (n_pass, n_total))
    sys.exit(0)
else:
    print("VALIDATION FAIL  (%d/%d) — %d failed" % (n_pass, n_total, n_total - n_pass))
    sys.exit(1)
