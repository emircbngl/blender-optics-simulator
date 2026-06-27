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
import bpy, sys, os, math, cmath

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

print("[Material breadth — extended catalog (refractiveindex.info, CC0)]")
check("Quartz n_o @587.6 (Ghosh99)", physics.sellmeier_n(587.6, 'QUARTZ_O'), 1.54428, 5e-4, "RII [datasheet]")
check("Quartz birefringence n_e-n_o (+uniaxial)",
      physics.sellmeier_n(587.6, 'QUARTZ_E') - physics.sellmeier_n(587.6, 'QUARTZ_O'), 0.00910, 5e-4, "Ghosh99 [datasheet]")
check("Sapphire n_o @587.6", physics.sellmeier_n(587.6, 'SAPPHIRE_O'), 1.76817, 5e-4, "Malitson72 [datasheet]")
check("N-SF6 n_d @587.6", physics.sellmeier_n(587.6, 'N-SF6'), 1.80518, 5e-4, "SCHOTT [datasheet]")
check("BaF2 n @587.6", physics.sellmeier_n(587.6, 'BaF2'), 1.47448, 5e-4, "Malitson64 [datasheet]")
check("ZnSe n @10.6um (CO2 laser line)", physics.sellmeier_n(10600.0, 'ZnSe'), 2.4028, 2e-3, "Connolly79 [datasheet]")
check("Ge n @10um (IR; tests clamp window)", physics.sellmeier_n(10000.0, 'GE'), 4.0040, 3e-3, "Burnett16 [datasheet]")

print("[Thermo-optic dn/dT — n_eff = n(lambda) + dn/dT*(T-20C)]")
check("Fused silica dn/dT +100K shift", physics.sellmeier_n(587.6, 'FUSED_SILICA', 120.0) - physics.sellmeier_n(587.6, 'FUSED_SILICA'),
      1.0e-3, 1e-9, "Corning7980; oracle")
check("CaF2 NEGATIVE dn/dT +100K shift", physics.sellmeier_n(587.6, 'CaF2', 120.0) - physics.sellmeier_n(587.6, 'CaF2'),
      -1.06e-3, 1e-9, "Daimon02; oracle")
check("dn/dT at 20C is a no-op (byte-identical)", physics.sellmeier_n(587.6, 'N-BK7', 20.0) - physics.sellmeier_n(587.6, 'N-BK7'),
      0.0, 0.0, "byte-identical")

print("[More textbook closed forms]")
_d = physics.refract_dir((math.cos(math.radians(30.0)), math.sin(math.radians(30.0)), 0.0), (-1.0, 0.0, 0.0), 1.0, 1.5)
_th2 = math.degrees(math.asin(abs(_d[1]))) if _d else None
check("Snell refraction 30deg, air->n=1.5", _th2, 19.4712, 1e-2, "Hecht; oracle")
check("Coherence length Na 589.3nm dl=0.6nm", physics.coherence_length_mm(589.3, 0.6), 0.5788, 1e-3, "Hecht; oracle")
check("Coherence length HeNe 632.8 dl=0.002nm", physics.coherence_length_mm(632.8, 0.002), 200.22, 0.5, "Hecht; oracle")
check("Fabry-Perot FSR 632.8nm L=10mm (nm)", physics.cavity_fsr_nm(632.8, 10.0, 1.0), 0.020022, 1e-5, "Saleh&Teich; oracle")
_qwp = physics.stokes(physics.apply(physics.M_waveplate(90.0, 45.0), physics.jones_linear(0.0)))
check("QWP linear->circular |S3|=1", abs(_qwp[3]), 1.0, 1e-3, "Hecht; oracle")
_hwp = physics.apply(physics.M_waveplate(180.0, 22.5), physics.jones_linear(0.0))
check("HWP rotates 0->45deg (analyzer@45 passes)", physics.intensity(physics.apply(physics.M_polarizer(45.0, 1.0e6), _hwp)),
      1.0, 1e-3, "Hecht; oracle")
check("HWP rotated beam blocked by analyzer@135", physics.intensity(physics.apply(physics.M_polarizer(135.0, 1.0e6), _hwp)),
      0.0, 1e-3, "Hecht; oracle")

print("[Mirrors & lenses (Hecht/Pedrotti scan)]")
_im_cc, _m_cc = physics.thin_lens_image(10.0, 30.0)       # concave mirror f=R/2=10
check("Concave mirror image (R=20,o=30)", _im_cc, 15.0, 1e-6, "Pedrotti; oracle")
check("Concave mirror magnification", _m_cc, -0.5, 1e-6, "Pedrotti; oracle")
_im_cx, _m_cx = physics.thin_lens_image(-10.0, 30.0)      # convex mirror f=-10
check("Convex mirror image (virtual)", _im_cx, -7.5, 1e-6, "Pedrotti; oracle")
_iN, _mN = physics.thin_lens_image(100.0, 150.0)
check("Newton's form x*x'=f^2 (f=100)", (150.0 - 100.0) * (_iN - 100.0), 10000.0, 1e-3, "Hecht; oracle")
_Mtl = physics.abcd_thick_lens(1.5, 50.0, -50.0, 10.0)
check("Thick-lens EFL=-1/C (n=1.5,R=+/-50,t=10)", -1.0 / _Mtl[1][0], 51.7241, 1e-2, "Pedrotti; oracle")

print("[Fresnel at angle + AR coating (Born&Wolf scan)]")
_rs, _rp = physics.fresnel_reflect(1.0, 1.5, math.radians(45.0))
check("Fresnel 45deg air->glass Rs", abs(_rs) ** 2, 0.092013, 1e-5, "Hecht; oracle")
check("Fresnel 45deg air->glass Rp", abs(_rp) ** 2, 0.008466, 1e-5, "Hecht; oracle")
_ts, _tp = physics.fresnel_reflect(1.5, 1.0, math.radians(45.0))   # TIR (past 41.81deg)
check("TIR |rs|=1 (n=1.5->air, 45deg)", abs(_ts), 1.0, 1e-6, "Born&Wolf; oracle")
check("TIR s-p relative phase (deg)", abs(math.degrees(cmath.phase(_tp) - cmath.phase(_ts))), 36.8699, 1e-2, "Born&Wolf; oracle")
check("AR quarter-wave R (MgF2 on crown)", physics.ar_quarter_wave_reflectance(1.0, 1.38, 1.52), 0.012601, 1e-5, "Born&Wolf; oracle")
check("AR ideal n1=sqrt(n0 ns) -> R=0", physics.ar_quarter_wave_reflectance(1.0, math.sqrt(1.52), 1.52), 0.0, 1e-9, "Born&Wolf; oracle")

print("[Gaussian beam w(z)/R(z)/Gouy + M^2 (Saleh&Teich/Siegman scan)]")
_zR = physics.q_from_waist(1.0, 632.8).imag
_qz = physics.q_propagate(physics.q_from_waist(1.0, 632.8), physics.abcd_free(_zR))
check("Gaussian w(zR)=sqrt2*w0", physics.beam_radius(_qz, 632.8), math.sqrt(2.0), 1e-4, "Saleh&Teich; oracle")
check("Gaussian R(zR)=2*zR", physics.beam_roc(_qz), 2.0 * _zR, 1.0, "Saleh&Teich; oracle")
check("Gouy phase at zR = 45deg", math.degrees(physics.gouy_phase(_qz)), 45.0, 1e-3, "Saleh&Teich; oracle")
check("M^2=1.3 divergence (w0=0.5,1064nm)", physics.gaussian_divergence(0.5, 1064.0, 1.3), 8.80572e-4, 1e-8, "Siegman; oracle")
check("M^2=1.3 beam-parameter product", physics.beam_parameter_product(1064.0, 1.3), 4.40286e-4, 1e-8, "Siegman; oracle")

print("[Polarization states (Born&Wolf/Collett scan)]")
_qwp30 = physics.polarization_state(physics.apply(physics.M_waveplate(90.0, 30.0), physics.jones_linear(0.0)))
check("QWP@30deg ellipticity", _qwp30["ellipticity_deg"], -30.0, 1e-2, "Collett; oracle")
check("QWP@30deg DOP=1", _qwp30["dop"], 1.0, 1e-6, "Collett; oracle")
_hwp2 = physics.polarization_state(physics.apply(physics.M_waveplate(90.0, 45.0),
        physics.apply(physics.M_waveplate(90.0, 45.0), physics.jones_linear(0.0))))
check("Two QWP@45 = HWP -> azimuth 90deg", abs(_hwp2["azimuth_deg"]), 90.0, 1e-2, "Collett; oracle")
check("Partial polarization DOP (S=2,1,0,0)", physics.polarization_state_from_stokes(2.0, 1.0, 0.0, 0.0)["dop"], 0.5, 1e-6, "Collett; oracle")
check("Partial polarization DOP 3:1 (S=4,3,0,0)", physics.polarization_state_from_stokes(4.0, 3.0, 0.0, 0.0)["dop"], 0.75, 1e-6, "Collett; oracle")

print("[Grating / fiber / EO / photon (multi-scan)]")
check("Grating resolving power R=mN (600/mm,25mm)", physics.grating_resolving_power(600.0, 25.0, 1), 15000.0, 1.0, "Hecht; oracle")
_thm = math.radians(physics.grating_angle(600.0, 1, 633.0, 0.0))
check("Grating angular dispersion 1/(d cos) rad/nm", 1.0 / ((1.0e6 / 600.0) * math.cos(_thm)), 6.4868e-4, 1e-7, "Hecht; oracle")
_na = physics.fiber_na(1.46, 1.457)
check("Fiber NA=sqrt(n1^2-n2^2)", _na, 0.0935468, 1e-5, "Saleh&Teich; oracle")
check("Fiber V-number 2pi a NA/lambda", physics.fiber_v_number(25.0, _na, 850.0), 17.2874, 1e-2, "Saleh&Teich; oracle")
check("Fiber mode count ~V^2/2", physics.fiber_num_modes(physics.fiber_v_number(25.0, _na, 850.0)), 149.4, 1.0, "Saleh&Teich; oracle")
check("AOM deflection lambda*f/v (632.8,200MHz,650)", physics.aom_deflection(632.8, 200.0e6, 650.0), 0.194708, 1e-5, "Saleh&Teich; oracle")
check("Pockels Vpi KDP (546nm,n=1.51,r=10.6)", physics.pockels_vpi(546.0, 1.51, 10.6), 7480.42, 1.0, "Saleh&Teich; oracle")
check("Photon energy hc/lambda (532nm, eV)", physics.photon_energy_eV(532.0), 2.33053, 1e-4, "Saleh&Teich; oracle")
_Ii, _Vi = physics.interfere([(physics.jones_linear(0.0, 1.0), 0.0, 633.0), (physics.jones_linear(0.0, 0.5), 0.0, 633.0)])
check("Two-beam visibility (I1=1,I2=0.25)", _Vi, 0.8, 1e-3, "Born&Wolf; oracle")

print("[Independent golden: SCHOTT/Malitson table values at non-d-line]")
check("N-BK7 nF @486.13nm (SCHOTT table)", physics.sellmeier_n(486.13, 'N-BK7'), 1.52238, 5e-5, "SCHOTT [datasheet]")
check("N-BK7 nC @656.27nm (SCHOTT table)", physics.sellmeier_n(656.27, 'N-BK7'), 1.51432, 5e-5, "SCHOTT [datasheet]")
check("N-BK7 @1060nm (SCHOTT table)", physics.sellmeier_n(1060.0, 'N-BK7'), 1.50669, 5e-5, "SCHOTT [datasheet]")
check("Fused silica @1064nm (Malitson)", physics.sellmeier_n(1064.0, 'FUSED_SILICA'), 1.449631, 5e-5, "Malitson [datasheet]")
check("CaF2 @1064nm (Malitson)", physics.sellmeier_n(1064.0, 'CaF2'), 1.428478, 5e-5, "Malitson [datasheet]")

print("=" * 60)
n_pass = sum(_checks)
n_total = len(_checks)
if n_pass == n_total:
    print("VALIDATION PASS  (%d/%d textbook checks)" % (n_pass, n_total))
    sys.exit(0)
else:
    print("VALIDATION FAIL  (%d/%d) — %d failed" % (n_pass, n_total, n_total - n_pass))
    sys.exit(1)
