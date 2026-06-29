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
# transparency-window honesty flag: in-window -> True, out-of-window (extrapolated/clamped) -> False
check("Sellmeier in-range: N-BK7 @587nm is within its window (->1)", 1.0 if physics.sellmeier_in_range(587.6, 'N-BK7') else 0.0, 1.0, 1e-9, "GLASS_RANGE_UM; metadata")
check("Sellmeier OUT-of-range: N-BK7 @200nm flagged (->0)", 1.0 if physics.sellmeier_in_range(200.0, 'N-BK7') else 0.0, 0.0, 1e-9, "GLASS_RANGE_UM; metadata")
check("Sellmeier OUT-of-range: Ge @1000nm flagged (range 2-14um) (->0)", 1.0 if physics.sellmeier_in_range(1000.0, 'GE') else 0.0, 0.0, 1e-9, "GLASS_RANGE_UM; metadata")

print("[Uniaxial crystal optics — walk-off / index ellipsoid / waveplate thickness / SHG phase-match]")
# index ellipsoid: n_e(theta) -> n_o along the optic axis (theta=0), -> n_e at theta=90 (calcite o/e)
check("Index ellipsoid n_e(theta=0) = n_o", physics.n_e_theta(1.6584, 1.4864, 0.0), 1.6584, 1e-6, "Yariv&Yeh; oracle")
check("Index ellipsoid n_e(theta=90) = n_e", physics.n_e_theta(1.6584, 1.4864, 90.0), 1.4864, 1e-6, "Yariv&Yeh; oracle")
# double-refraction walk-off angle (calcite, theta=45 deg from the optic axis)
check("Calcite walk-off angle @45deg = 6.224 deg", physics.uniaxial_walkoff_angle(1.6584, 1.4864, 45.0), 6.224, 0.02, "Yariv&Yeh; oracle")
# true zero-order waveplate thickness from the catalog quartz birefringence (Delta_n @589.3 = 0.00910)
_dn_q = physics.sellmeier_n(589.3, 'QUARTZ_E') - physics.sellmeier_n(589.3, 'QUARTZ_O')
check("Quartz QWP thickness = lambda/(4 dn) = 16.19um", physics.waveplate_thickness(0.25, 589.3, _dn_q), 0.01619, 1e-4, "d=m*lambda/dn; oracle")
check("Quartz HWP thickness = lambda/(2 dn) = 32.38um", physics.waveplate_thickness(0.50, 589.3, _dn_q), 0.03238, 1e-4, "d=m*lambda/dn; oracle")
# Type-I SHG critical phase-matching angle from the BBO index ellipsoid (Eimerl 1987 Sellmeier)
check("BBO Type-I SHG phase-match angle 1064->532 = 22.78 deg", physics.shg_phase_match_angle('BBO', 1064.0), 22.78, 0.3, "Boyd/Eimerl87; oracle")
# KDP (Zernike 1964 Sellmeier, refractiveindex.info): indices + the textbook Type-I phase-match angle
check("KDP n_o @1064nm = 1.4938 (Zernike Sellmeier)", math.sqrt(physics._nl_n2(physics.NL_CRYSTAL_SELLMEIER['KDP'][0], 1.064)), 1.4938, 1e-3, "Zernike1964 [datasheet]")
check("KDP n_e @532nm = 1.4705 (Zernike Sellmeier)", math.sqrt(physics._nl_n2(physics.NL_CRYSTAL_SELLMEIER['KDP'][1], 0.532)), 1.4705, 1e-3, "Zernike1964 [datasheet]")
check("KDP Type-I SHG phase-match angle 1064->532 = 41.2 deg", physics.shg_phase_match_angle('KDP', 1064.0), 41.2, 0.3, "textbook; index ellipsoid")
# LiIO3 (Umegaki 1971) + ADP (Zernike 1964): the Type-I 1064->532 angle reproduces the textbook value, which
# validates the sourced Sellmeier coefficients (a wrong coefficient would miss the known angle).
check("LiIO3 n_o @1064nm = 1.857 (Umegaki Sellmeier)", math.sqrt(physics._nl_n2(physics.NL_CRYSTAL_SELLMEIER['LIIO3'][0], 1.064)), 1.857, 1e-3, "Umegaki1971 [datasheet]")
check("LiIO3 Type-I SHG phase-match angle 1064->532 = 30.0 deg", physics.shg_phase_match_angle('LIIO3', 1064.0), 30.0, 0.2, "textbook; index ellipsoid")
check("ADP Type-I SHG phase-match angle 1064->532 = 41.7 deg", physics.shg_phase_match_angle('ADP', 1064.0), 41.7, 0.3, "Zernike1964; index ellipsoid")
# Type-II phase matching (o+e->e): 2*n_e(2w,theta) = n_o(w) + n_e(w,theta). BBO ~32.9 deg (> the 22.78 Type-I).
check("BBO Type-II SHG phase-match angle 1064->532 = 32.9 deg", physics.shg_phase_match_angle_type2('BBO', 1064.0), 32.9, 0.3, "Boyd; index ellipsoid")
check("KDP Type-II SHG phase-match angle 1064->532 ~ 59 deg", physics.shg_phase_match_angle_type2('KDP', 1064.0), 59.1, 0.5, "textbook; index ellipsoid")
check("Type-II angle > Type-I angle (o+e needs a larger cut, BBO)", physics.shg_phase_match_angle_type2('BBO', 1064.0) - physics.shg_phase_match_angle('BBO', 1064.0), 10.06, 0.3, "negative uniaxial; ordering")
# BIAXIAL crystals (KTP, LBO) -- principal-PLANE (XY, theta=90) phase matching reduces to effective-uniaxial.
# The sourced formula-4 Sellmeier (refractiveindex.info) reproduces both indices AND the textbook XY azimuth phi.
check("KTP n_z @1064nm = 1.8297 (Kato2002 formula-4)", math.sqrt(physics._formula4_n2(physics.BIAXIAL_SELLMEIER['KTP'][2], 1.064)), 1.8297, 1e-3, "Kato2002 [datasheet]")
check("LBO n_z @1064nm = 1.6056 (Chen/Hanson formula-4)", math.sqrt(physics._formula4_n2(physics.BIAXIAL_SELLMEIER['LBO'][2], 1.064)), 1.6056, 1e-3, "Chen1989 [datasheet]")
check("KTP Type-II XY-plane SHG phase-match azimuth phi = 23.5 deg", physics.biaxial_shg_phase_match_phi('KTP', 1064.0, 'TYPE2'), 23.5, 0.3, "EKSMA datasheet; index ellipsoid")
check("LBO Type-I XY-plane SHG phase-match azimuth phi = 11.6 deg", physics.biaxial_shg_phase_match_phi('LBO', 1064.0, 'TYPE1'), 11.6, 0.3, "EKSMA datasheet; index ellipsoid")
check("KTP Type-II XY SHG walk-off = 4 mrad (datasheet)", physics.biaxial_shg_walkoff_mrad('KTP', 1064.0, 'TYPE2'), 4.0, 0.6, "EKSMA; double refraction")
check("LBO Type-I XY SHG walk-off = 7 mrad (datasheet)", physics.biaxial_shg_walkoff_mrad('LBO', 1064.0, 'TYPE1'), 7.0, 0.6, "EKSMA; double refraction")
# LBO NON-critical phase matching (X axis, temperature-tuned). HONEST: the CONSTANT datasheet dn/dT model is
# self-consistent (~256 C) but UNDER-predicts the tuning slope -> it does NOT reach the real 148 C NCPM point
# (the wavelength-resolved dn/dT that do are paywalled). We validate the model's self-consistency + the honest gap.
check("LBO NCPM: room-T index mismatch n_y(532)-n_z(1064) = +0.0012 (the temperature-tuned starting point)",
      physics.lbo_index_T('y', 532.0, 20.0) - physics.lbo_index_T('z', 1064.0, 20.0), 0.0012, 5e-5, "Chen Sellmeier; oracle")
check("LBO NCPM constant-dn/dT model is self-consistent (~256 C)", physics.lbo_ncpm_temperature_estimate(1064.0), 256.3, 2.0, "LaserComponents dn/dT; Tier-1 model")
check("LBO NCPM literature constant = 148 C (the real oven set-point, cited not derived)", physics.LBO_NCPM_TEMP_LIT_C, 148.0, 1e-9, "LaserComponents/CASTECH datasheet")
check("LBO NCPM: constant-dn/dT model OVER-predicts vs the 148 C literature (honest gap > 80 C)",
      1.0 if (physics.lbo_ncpm_temperature_estimate(1064.0) - physics.LBO_NCPM_TEMP_LIT_C) > 80.0 else 0.0, 1.0, 1e-9, "documented Tier-1 limitation")

# o/e SPATIAL double refraction geometry (physics.oe_split_geometry): composes the verified ellipsoid +
# walk-off + vector geometry. Calcite cut 45 deg -> rho 6.224 deg; the o/e eigen-pols are orthogonal.
_oth, _orho, _opo, _ope, _owk = physics.oe_split_geometry((0.0, 0.0, 1.0),
    (math.sin(math.radians(45.0)), 0.0, math.cos(math.radians(45.0))), 1.6584, 1.4864)
check("o/e geometry: extraordinary walk-off at 45 deg = 6.224 deg", _orho, 6.224, 0.02, "Yariv&Yeh; oracle")
check("o/e geometry: ordinary & extraordinary polarizations are orthogonal", abs(physics._rdot(_opo, _ope)), 0.0, 1e-9, "double refraction; eigen-axes")
check("o/e geometry: both eigen-pols transverse to the wave (pol_o . d = 0)", abs(physics._rdot(_opo, (0.0, 0.0, 1.0))), 0.0, 1e-9, "transverse field")

# chi(2) TENSOR SOLVER -- the full Manley-Rowe coupled-wave ODE (physics.chi2_shg_efficiency). At perfect
# phase match it equals the depleted closed form tanh^2(sqrt(eta_lin)); undepleted it is eta_lin*sinc^2(dkL/2).
check("Manley-Rowe SHG ODE @phase-match == tanh^2(sqrt(eta_lin=0.5))", physics.chi2_shg_efficiency(0.5, 0.0), math.tanh(math.sqrt(0.5)) ** 2, 1e-6, "Boyd coupled-wave; RK4")
check("Manley-Rowe SHG ODE @phase-match == tanh^2(sqrt(eta_lin=4)) = 0.9293", physics.chi2_shg_efficiency(4.0, 0.0), 0.929349, 1e-5, "Boyd; RK4 vs analytic")
check("Manley-Rowe SHG ODE undepleted limit -> eta_lin*sinc^2(dkL/2)", physics.chi2_shg_efficiency(1e-3, math.pi) / (1e-3 * (math.sin(math.pi / 2) / (math.pi / 2)) ** 2), 1.0, 5e-3, "undepleted SHG; sinc^2")
check("Manley-Rowe SHG ODE energy bound: eta <= 1 (strong drive)", physics.chi2_shg_efficiency(100.0, 0.0), 1.0, 1e-3, "Manley-Rowe; conservation")
# TYPE-II SHG (o+e->e): the 3-wave coupled equations. Balanced (frac_o=0.5) reduces to Type-I at HALF eta_lin;
# an unbalanced pump SATURATES at the weaker polarization (Manley-Rowe cap 2*min(frac_o, 1-frac_o)).
check("Type-II SHG balanced == Type-I at half eta_lin (continuity)", physics.chi2_shg_type2_efficiency(4.0, 0.5), physics.chi2_shg_efficiency(2.0, 0.0), 1e-4, "Boyd; 3-wave RK4")
check("Type-II SHG balanced -> full conversion at strong drive", physics.chi2_shg_type2_efficiency(64.0, 0.5), 1.0, 1e-3, "Manley-Rowe; coupled-wave")
_t2cap = max(physics.chi2_shg_type2_efficiency(s, 0.2) for s in (1.0, 2.0, 4.0, 8.0, 16.0, 32.0))
check("Type-II SHG unbalanced (frac_o=0.2) caps at 2*min = 0.4 (Manley-Rowe)", _t2cap, 0.4, 0.02, "photon-number conservation")
check("Type-II SHG never exceeds the Manley-Rowe cap (frac_o=0.3 -> <= 0.6)", 1.0 if all(physics.chi2_shg_type2_efficiency(s, 0.3) <= 0.6 + 1e-6 for s in (2.0, 8.0, 32.0, 128.0)) else 0.0, 1.0, 1e-9, "Manley-Rowe bound")
# Sellmeier-DERIVED SHG walk-off (replaces the lumped literal when the solver is on): BBO 1064->532 over 10 mm
check("BBO Sellmeier SHG walk-off over 10 mm ~ 0.50 mm (rho ~ 2.87 deg)", physics.shg_walkoff_mm('BBO', 1064.0, 10.0), 0.502, 0.02, "index ellipsoid; oracle")

print("[Mueller calculus + canonical Stokes (py-pol / SymPy / Malus oracles)]")
# Malus's law through an ideal linear analyzer on horizontal-linear input [1,1,0,0]: I/I0 = cos^2(theta)
_Hs = (1.0, 1.0, 0.0, 0.0)
check("Malus I/I0 @30deg = cos^2 = 0.75", physics.stokes_through(physics.M_mueller_polarizer(30.0), _Hs)[0], 0.75, 1e-9, "Malus; oracle")
check("Malus I/I0 @45deg = cos^2 = 0.50", physics.stokes_through(physics.M_mueller_polarizer(45.0), _Hs)[0], 0.50, 1e-9, "Malus; oracle")
check("Malus I/I0 @60deg = cos^2 = 0.25", physics.stokes_through(physics.M_mueller_polarizer(60.0), _Hs)[0], 0.25, 1e-9, "Malus; oracle")
# QWP at 45 deg turns horizontal-linear into CIRCULAR: |S3| = 1, S1 = S2 = 0
_qc = physics.stokes_through(physics.M_mueller_retarder(90.0, 45.0), _Hs)
check("Mueller QWP@45 on H -> circular |S3|=1", abs(_qc[3]), 1.0, 1e-9, "py-pol; Mueller")
check("Mueller QWP@45 on H -> S1=S2=0", abs(_qc[1]) + abs(_qc[2]), 0.0, 1e-9, "py-pol; Mueller")
# Mueller path agrees with the Jones path for a pure state (internal-consistency oracle)
_qj = physics.stokes(physics.apply(physics.M_waveplate(90.0, 45.0), (1 + 0j, 0j)))
check("Mueller QWP == Jones M_waveplate (S3 agree)", _qc[3], _qj[3], 1e-9, "internal consistency")
# HWP at 22.5 deg rotates linear polarization by 45 deg: H -> +45 (S2 = 1)
check("Mueller HWP@22.5 on H -> +45 linear (S2=1)", physics.stokes_through(physics.M_mueller_retarder(180.0, 22.5), _Hs)[2], 1.0, 1e-9, "Mueller HWP")
# canonical Stokes from Jones (SymPy/py-pol vectors): H S1=+1, D S2=+1, R(1,i)/sqrt2 S3=+1
import math as _ma
check("Stokes(H=[1,0]) S1 = +1", physics.stokes((1 + 0j, 0j))[1], 1.0, 1e-9, "SymPy/py-pol; oracle")
check("Stokes(D=[1,1]/sqrt2) S2 = +1", physics.stokes(((1 + 0j) / _ma.sqrt(2), (1 + 0j) / _ma.sqrt(2)))[2], 1.0, 1e-9, "SymPy/py-pol; oracle")
check("Stokes(R=[1,i]/sqrt2) S3 = +1", physics.stokes(((1 + 0j) / _ma.sqrt(2), 1j / _ma.sqrt(2)))[3], 1.0, 1e-9, "SymPy/py-pol; oracle")

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
# AR ghost-curve R(lambda): the V-shaped reflectance of the quarter-wave layer -- min at the design wl, rising away
check("AR(lambda) at design wl == quarter-wave R (MgF2, 550nm)", physics.ar_coating_reflectance(550.0, 550.0, 1.38, 1.52), physics.ar_quarter_wave_reflectance(1.0, 1.38, 1.52), 1e-9, "Airy thin-film; reduces to oracle")
check("AR(lambda) is a V: R(450) > R(550) min (rises off design)", physics.ar_coating_reflectance(450.0, 550.0, 1.38, 1.52) - physics.ar_coating_reflectance(550.0, 550.0, 1.38, 1.52), 0.0036, 1e-3, "Born&Wolf; thin-film")
check("AR(lambda) ideal index -> 0 at design (perfect AR)", physics.ar_coating_reflectance(550.0, 550.0, math.sqrt(1.52), 1.52), 0.0, 1e-9, "Airy thin-film; oracle")

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

print("[Mirror-metal dispersion (Johnson&Christy / Rakic)]")
check("Ag reflectance @633nm (J&C)", physics.metal_reflectance('AG', 633.0), 0.9884, 1e-3, "J&C [datasheet]")
check("Ag reflectance @1064nm (IR climb)", physics.metal_reflectance('AG', 1064.0), 0.9973, 1e-3, "J&C [datasheet]")
check("Al reflectance @633nm (Rakic)", physics.metal_reflectance('AL', 633.0), 0.9128, 1e-3, "Rakic [datasheet]")
check("Au reflectance @450nm (blue, low)", physics.metal_reflectance('AU', 450.0), 0.4082, 2e-3, "J&C [datasheet]")
check("Au reflectance @633nm (red, high)", physics.metal_reflectance('AU', 633.0), 0.9407, 3e-3, "J&C interp")
check("Gold-is-yellow R(633)/R(450)>2", physics.metal_reflectance('AU', 633.0) / physics.metal_reflectance('AU', 450.0), 2.3, 0.4, "J&C trend")

print("[Thermal/mechanical closed-form estimates (Tier-1)]")
check("Thermal-lens f (P=1W,dn/dT=1e-5,k=1.38,w=1mm)", physics.thermal_lens_focal_length(1.0, 1e-5, 1.38, 1.0), 867.085, 0.1, "oracle (estimate)")
check("Photoelastic retardance (1MPa,C=3.5e-12,10mm)", physics.photoelastic_retardance_nm(1e6, 3.5e-12, 10.0), 35.0, 1e-3, "oracle (estimate)")
check("Cantilever sag (0.1kg,0.1m,steel,Ø1in rod)", physics.cantilever_sag_nm(0.1, 0.1, 200e9, 2.04e-8), 80.147, 1e-2, "oracle (estimate)")

print("[Fourier-optics PSF -- the opt-in wave module (PSF=|FFT(pupil)|^2)]")
from optical_alignment_sim import wave
_wm = wave.psf_metrics(550.0, 8.0, 25.4)                    # ideal F/8 circular aperture, 550 nm
check("PSF ideal Strehl = 1", _wm['strehl'], 1.0, 1e-4, "Goodman; FFT")
check("PSF Airy radius = 1.22 lambda F# (um)", _wm['airy_radius_um'], 5.368, 1e-2, "Goodman; oracle")
check("PSF first dark ring ~ Airy radius (um)", _wm['first_zero_um'], 5.368, 0.3, "Goodman; FFT")
check("PSF encircled energy in 1st ring = 83.8%", _wm['encircled_energy_airy'], 0.838, 5e-3, "Born&Wolf; FFT")
check("PSF MTF cutoff = 1/(lambda F#) cyc/mm", _wm['mtf_cutoff_cyc_per_mm'], 227.3, 0.5, "Goodman; oracle")
_wd = wave.psf_metrics(550.0, 8.0, 25.4, W=0.0714 * wave.zernike_defocus(512, 128))
check("PSF Strehl(lambda/14 RMS defocus) ~ Marechal", _wd['strehl'], 0.8177, 0.01, "Marechal; FFT vs oracle")

print("[Zernike-aberrated PSF -- aberrated_psf, any Noll mode; Strehl follows Marechal exp(-(2 pi rms)^2)]")
_ab0 = wave.aberrated_psf([0.0] * 15, 550.0, 8.0, 10.0, n_grid=256, diam_px=128)
check("Aberrated PSF: zero aberration -> Strehl 1", _ab0['strehl'], 1.0, 1e-3, "FFT")
check("Aberrated PSF: zero aberration -> RMS 0", _ab0['rms_wavefront_waves'], 0.0, 1e-6, "definition")
_marechal_005 = math.exp(-(2.0 * math.pi * 0.05) ** 2)      # 0.9060
_marechal_010 = math.exp(-(2.0 * math.pi * 0.10) ** 2)      # 0.6738
_cas = [0.0] * 15; _cas[4] = 0.05                            # Noll Z5 astigmatism, 0.05 waves RMS
_abast = wave.aberrated_psf(_cas, 550.0, 8.0, 10.0, n_grid=256, diam_px=128)
check("Aberrated PSF: astigmatism 0.05 -> RMS = coefficient", _abast['rms_wavefront_waves'], 0.05, 2e-3, "RMS-normalized Noll")
check("Aberrated PSF: astigmatism 0.05 -> Strehl ~ Marechal 0.906", _abast['strehl'], _marechal_005, 0.012, "Marechal; FFT")
_ccm = [0.0] * 15; _ccm[6] = 0.10                            # Noll Z7 coma, 0.10 waves RMS
_abcoma = wave.aberrated_psf(_ccm, 550.0, 8.0, 10.0, n_grid=256, diam_px=128)
check("Aberrated PSF: coma 0.10 -> Strehl ~ Marechal 0.674", _abcoma['strehl'], _marechal_010, 0.02, "Marechal; FFT")
_csph = [0.0] * 15; _csph[10] = 0.05                         # Noll Z11 spherical, 0.05 waves RMS
_absph = wave.aberrated_psf(_csph, 550.0, 8.0, 10.0, n_grid=256, diam_px=128)
check("Aberrated PSF: Strehl depends on RMS not mode (spherical 0.05 == astig 0.05)", _absph['strehl'], _abast['strehl'], 8e-3, "Marechal: Strehl(rms) mode-independent")

print("[Field propagation -- the opt-in angular-spectrum layer (free-space dz, off-trace)]")
from optical_alignment_sim import field
import numpy as _np
_flam, _fw0, _fN = 632.8, 0.30, 256
_fdx = 8.0 * _fw0 / _fN
_fU0 = field.gaussian_field(_fN, _fdx, _fw0)
_fzR = math.pi * _fw0 ** 2 / (_flam * 1e-6)                  # Rayleigh range (mm)
for _fz in (100.0, 300.0, 600.0):
    _fw = field.field_metrics(field.angular_spectrum(_fU0, _fdx, _fz, _flam), _fdx, _flam)["w_2sigma_mm"]
    _fan = _fw0 * math.sqrt(1.0 + (_fz / _fzR) ** 2)         # Gaussian w(z), oracle-verified closed form
    check("AngSpec Gaussian w(z=%dmm)" % _fz, _fw, round(_fan, 5), 5e-3, "Goodman; FFT vs closed form")
_fUf = field.angular_spectrum(_fU0, _fdx, 300.0, _flam)
_fUb = field.angular_spectrum(_fUf, _fdx, -300.0, _flam)     # back-propagate = digital-hologram reconstruction
check("AngSpec round-trip +z/-z recovers U0", float(_np.max(_np.abs(_fUb - _fU0)) / _np.max(_np.abs(_fU0))), 0.0, 1e-5, "reversibility; FFT")
check("AngSpec power conserved P(z)/P(0)", float(_np.sum(_np.abs(_fUf) ** 2) / _np.sum(_np.abs(_fU0) ** 2)), 1.0, 1e-3, "energy; FFT")

print("[Multi-plane field-propagation CHAIN -- propagate_chain (POPPY-style OpticalSystem, chains the propagator)]")
# (1) propagator additivity: the pure angular spectrum composes EXACTLY -- prop(z1)*prop(z2) == prop(z1+z2)
_mc1, _, _, _ = field._run_chain([("prop", 50.0), ("prop", 70.0)], 632.8, 0.5, None, 512, None, False)
_mc2, _, _, _ = field._run_chain([("prop", 120.0)], 632.8, 0.5, None, 512, None, False)
check("Chain: propagator additivity prop(z1)+prop(z2) = prop(z1+z2)", float(_np.abs(_mc1 - _mc2).max()), 0.0, 1e-7, "angular spectrum; exact")
# (2) a CHAINED aperture->lens(f)->prop focuses at z=f (the chain reproduces the validated thin-lens focus)
_mc_wmin, _mc_zf = 1e9, None
for _mcz in _np.linspace(0.6 * 200.0, 1.4 * 200.0, 17):
    _mcw = field.propagate_chain([("aperture", 3.0), ("lens", 200.0), ("prop", float(_mcz))], 632.8, None, 3.0, 512)["final"]["w_2sigma_mm"]
    if _mcw < _mc_wmin:
        _mc_wmin, _mc_zf = _mcw, _mcz
check("Chain: aperture->lens(f)->prop focuses at z=f (200mm)", _mc_zf, 200.0, 12.0, "Goodman; chained")
# (3) a free-space Gaussian marched through the chain reproduces the analytic w(z)
_mc_zR = math.pi * 0.5 ** 2 / (632.8 * 1e-6)
_mc_wch = field.propagate_chain([("prop", 600.0)], 632.8, 0.5, None, 512)["final"]["w_2sigma_mm"]
check("Chain: free Gaussian w(z) = w0 sqrt(1+(z/zR)^2) (z=600mm)", _mc_wch, 0.5 * math.sqrt(1.0 + (600.0 / _mc_zR) ** 2), 0.02, "Saleh&Teich; chained")

print("[Gerchberg-Saxton phase retrieval -- iterative FT algorithm (monotone error, achieved far-field matches target)]")
# feasible target = |FFT(source * exp(i phi_true))| -> GS must recover a phase that reproduces it
_gsN = 128
_gsx = _np.arange(_gsN) - _gsN // 2
_gsX, _gsY = _np.meshgrid(_gsx, _gsx)
_gs_src = (_np.hypot(_gsX, _gsY) <= 40).astype(float)
_gs_phi = math.pi * _np.exp(-(_gsX ** 2 + _gsY ** 2) / (2.0 * 15.0 ** 2))
_gs_T = _np.abs(field._fft2c(_gs_src * _np.exp(1j * _gs_phi)))
_gs = field.gerchberg_saxton(_gs_T, _gs_src, n_iter=80)
check("Gerchberg-Saxton: far-field error is MONOTONE non-increasing (GS guarantee)", 1.0 if _gs["monotone"] else 0.0, 1.0, 1e-9, "GS; algorithmic guarantee")
check("Gerchberg-Saxton: recovers a feasible target (achieved-target correlation > 0.97)", _gs["correlation"], 1.0, 0.03, "phase retrieval; FFT")
check("Gerchberg-Saxton: error decreases (final < 0.4 x initial)", _gs["final_error"] / _gs["errors"][0], 0.0, 0.4, "GS convergence")
# a canonical computer-generated-hologram target (a double spot) is produced with high correlation
_gs2 = field.gerchberg_saxton_design("double", 128, 80)
check("Gerchberg-Saxton: CGH 'double' target produced (correlation > 0.9)", _gs2["correlation"], 1.0, 0.1, "CGH design; FFT")

print("[Fienup phase retrieval -- recover a hidden object from |FFT|^2 + support ALONE (the genuine phase problem)]")
# HIO recovers the unknown object from its diffraction INTENSITY only (correlation invariant to the inherent
# translation + conjugate-twin ambiguities). The off-centre support breaks the twin.
_fp = field.fienup_design("dots", 128, n_iter=300, seed=0)
check("Fienup HIO: recovers a hidden object from |FFT|^2 + support (correlation > 0.95)", _fp["correlation"], 1.0, 0.05, "phase retrieval; HIO")
check("Fienup HIO: Fourier-magnitude error converges (final < 0.01, from ~0.8)", _fp["final_error"], 0.0, 0.01, "CDI; FFT")
check("Fienup HIO: error actually dropped (final < 0.05 x initial)", _fp["final_error"] / _fp["initial_error"], 0.0, 0.05, "HIO convergence")
# HIO escapes the stagnation that pure error-reduction (the GS-analogue here) gets stuck in
_fp_truth, _fp_supp = field._fienup_object("dots", 128)
_fp_meas = _np.abs(field._fft2c(_fp_truth)) ** 2
_fp_hio = field.fienup_phase_retrieval(_fp_meas, _fp_supp, n_iter=300, mode="hio", seed=0)
_fp_er = field.fienup_phase_retrieval(_fp_meas, _fp_supp, n_iter=320, mode="er", seed=0)
check("Fienup HIO escapes the error-reduction stagnation (HIO final error < 0.3 x ER's)", _fp_hio["final_error"] / _fp_er["final_error"], 0.0, 0.3, "Fienup 1982; HIO vs ER")
# seed-pinned: same seed -> same recovery (deterministic, off-trace)
_fp_b = field.fienup_design("dots", 128, n_iter=300, seed=0)
check("Fienup HIO: seed-pinned reproducible (same seed -> same final error)", _fp_b["final_error"], _fp["final_error"], 1e-9, "determinism")

print("[Laser cavity transverse modes -- Hermite-Gaussian TEM_mn / Laguerre-Gaussian donut (orthonormal eigenmodes)]")
# HG modes are an ORTHONORMAL set: <U_mn, U_mn> = 1, <U_mn, U_pq> = 0 for (m,n) != (p,q)
_hg00 = field.hermite_gaussian(0, 0, 0.5, 256)
_hg10 = field.hermite_gaussian(1, 0, 0.5, 256)
_hg01 = field.hermite_gaussian(0, 1, 0.5, 256)
check("HG modes normalized: <TEM00|TEM00> = 1", abs(field._mode_inner(_hg00, _hg00)), 1.0, 1e-9, "cavity eigenmodes; grid")
check("HG modes orthogonal: <TEM00|TEM10> = 0", abs(field._mode_inner(_hg00, _hg10)), 0.0, 1e-6, "Hermite orthogonality; grid")
check("HG modes orthogonal: <TEM10|TEM01> = 0", abs(field._mode_inner(_hg10, _hg01)), 0.0, 1e-6, "Hermite orthogonality; grid")
# the HG_m0 second moment grows as (2m+1): <x^2>_m / <x^2>_0 = 2m+1 (the mode gets wider with order)
_t0 = field.tem_mode_metrics("HG", 0, 0, 0.5, 256)
_t1 = field.tem_mode_metrics("HG", 1, 0, 0.5, 256)
_t2 = field.tem_mode_metrics("HG", 2, 0, 0.5, 256)
check("HG_m0 second moment scales as (2m+1): <x^2>_1/<x^2>_0 = 3", _t1["x2_over_w2"] / _t0["x2_over_w2"], 3.0, 1e-3, "Siegman; oracle")
check("HG_m0 second moment scales as (2m+1): <x^2>_2/<x^2>_0 = 5", _t2["x2_over_w2"] / _t0["x2_over_w2"], 5.0, 1e-3, "Siegman; oracle")
# lobe count = (m+1)(n+1): TEM11 -> 4 bright spots, TEM21 -> 6
check("HG TEM_11 has (1+1)(1+1) = 4 bright lobes", field.tem_mode_metrics("HG", 1, 1, 0.5, 256)["n_lobes"], 4.0, 1e-9, "mode pattern; count")
check("HG TEM_21 has (2+1)(1+1) = 6 bright lobes", field.tem_mode_metrics("HG", 2, 1, 0.5, 256)["n_lobes"], 6.0, 1e-9, "mode pattern; count")
# Laguerre-Gaussian donut LG_{0,1}: on-axis NULL + a 2*pi*l azimuthal phase vortex (orbital angular momentum)
_lg01 = field.tem_mode_metrics("LG", 0, 1, 0.5, 256)
check("LG donut LG_{0,1}: on-axis intensity null (vortex core)", _lg01["on_axis_intensity_frac"], 0.0, 1e-6, "OAM mode; oracle")
check("LG_{0,1} carries OAM: azimuthal phase winds 2*pi*l (l=1 -> 1 turn)", _lg01["oam_winding_turns"], 1.0, 1e-3, "Allen 1992; phase winding")
check("LG_{0,2} carries OAM l=2: phase winds 2 turns", field.tem_mode_metrics("LG", 0, 2, 0.5, 256)["oam_winding_turns"], 2.0, 1e-3, "Allen 1992; phase winding")
# Gouy-phase order = m+n+1 (HG) / 2p+|l|+1 (LG): the mode's extra phase slip through focus
check("HG Gouy order = m+n+1 (TEM_21 -> 4)", field.tem_mode_metrics("HG", 2, 1, 0.5, 256)["gouy_order"], 4.0, 1e-9, "Siegman; oracle")
check("LG Gouy order = 2p+|l|+1 (LG_{1,2} -> 5)", field.tem_mode_metrics("LG", 1, 2, 0.5, 256)["gouy_order"], 5.0, 1e-9, "Siegman; oracle")

print("[4f Fourier spatial filtering -- Abbe-Porter (highpass removes DC, lowpass smooths, phase-contrast)]")
# highpass blocks the zero order -> the DC background is removed (output mean amplitude ~ 0)
_sfhp = field.spatial_filter("grating", "highpass", 0.02)
check("Spatial filter highpass removes the DC background (output mean ~ 0)", _sfhp["output_mean_amp"], 0.0, 1e-3, "Abbe-Porter; FFT")
# lowpass passing only the zero order -> the grating is erased, output is uniform (intensity std ~ 0)
_sflp = field.spatial_filter("grating", "lowpass", 0.008)
check("Spatial filter lowpass (DC only) erases the grating -> uniform (std ~ 0)", _sflp["output_intensity_std"], 0.0, 0.02, "Abbe-Porter; FFT")
# Zernike phase contrast: a PURE-phase object (input intensity std = 0) becomes visible in intensity
_sfpc = field.spatial_filter("phase", "phase_contrast", 0.02)
check("Phase contrast: pure-phase object is invisible in intensity (input std = 0)", _sfpc["input_intensity_std"], 0.0, 1e-9, "Zernike; FFT")
check("Phase contrast makes the phase object VISIBLE in intensity (output std > 0.02)", _sfpc["output_intensity_std"], 0.078, 0.05, "Zernike phase contrast; FFT")

print("[Fraunhofer slit diffraction -- single / double / grating (FFT vs analytic sinc^2 x cos^2)]")
_ss = field.slit_metrics(0.1, n_slits=1, wavelength_nm=632.8, n_grid=8192)            # single slit a=0.1mm
check("Single-slit first min at sin(theta)=lambda/a", _ss["first_min_sin_theta"], _ss["first_min_theory"], 0.05 * _ss["first_min_theory"], "Goodman; FFT vs sinc^2")
check("Single-slit pattern == analytic sinc^2 (rms)", _ss["rms_vs_analytic"], 0.0, 0.02, "Goodman/Voelz; FFT")
_ds = field.slit_metrics(0.1, n_slits=2, sep_mm=0.5, wavelength_nm=632.8, n_grid=8192)  # double slit a=0.1, d=0.5
check("Double-slit fringe (order) spacing = lambda/d", _ds["fringe_spacing_sin_theta"], _ds["fringe_spacing_theory"], 0.03 * _ds["fringe_spacing_theory"], "Young; FFT")
check("Double-slit pattern == analytic sinc^2 x cos^2 (rms)", _ds["rms_vs_analytic"], 0.0, 0.02, "Goodman/Voelz; FFT")
_gr = field.slit_metrics(0.05, n_slits=5, sep_mm=0.2, wavelength_nm=632.8, n_grid=8192)  # 5-slit grating
check("5-slit grating order spacing = lambda/d + matches analytic (rms)", _gr["rms_vs_analytic"], 0.0, 0.02, "grating; FFT vs analytic")

print("[Talbot self-imaging -- a periodic grating reproduces itself at z_T = 2 d^2/lambda (angular spectrum)]")
_tb = field.talbot_metrics(0.1, 632.8, n_periods=16, n_grid=512)                      # d=0.1mm, 632.8nm
check("Talbot distance z_T = 2 d^2 / lambda (mm)", _tb["talbot_distance_mm"], 2.0 * 0.1 ** 2 / (632.8 * 1e-6), 1e-2, "Talbot; oracle")
check("Talbot self-image at z_T (corr ~ 1)", _tb["self_image_corr"], 1.0, 0.15, "Talbot; angular-spectrum FFT")
check("Half-Talbot at z_T/2 is the d/2-shifted grating (corr ~ 1)", _tb["half_talbot_shift_corr"], 1.0, 0.15, "Talbot; FFT")
check("No self-image at z_T/4 (corr ~ 0)", abs(_tb["quarter_corr"]), 0.0, 0.3, "Talbot; FFT")

print("[Fresnel diffraction + foci -- circular-aperture zones, knife-edge, zone-plate, lens, Newton's rings]")
# Fabry-Perot Airy minimum transmission T_min = ((1-R)/(1+R))^2 (resonance dip; delta=pi)
_fpR = 0.9
check("Fabry-Perot Airy T_min = ((1-R)/(1+R))^2 (R=0.9)",
      physics.airy_transmission(632.8, 632.8e-6 / 4.0, _fpR), ((1 - _fpR) / (1 + _fpR)) ** 2, 1e-4, "Hecht; oracle")
# Circular-aperture on-axis Fresnel zones: I_axis/I0 = 4 sin^2(pi N_F/2); odd N_F -> 4 I0, even N_F -> 0
_ca_a, _ca_lam, _ca_N = 0.5, 500.0, 1024
_ca_dx = 2.2 * 2 * _ca_a / _ca_N
_ca_ap = field.circular_aperture(_ca_N, _ca_dx, 2 * _ca_a)
_ca_c = _ca_N // 2
for _nf in (1, 2, 3, 4):
    _ca_z = _ca_a ** 2 / (_ca_lam * 1e-6 * _nf)
    _ca_I = float(_np.abs(field.angular_spectrum(_ca_ap, _ca_dx, _ca_z, _ca_lam)[_ca_c, _ca_c]) ** 2)
    if _nf % 2 == 1:
        check("Circular aperture odd N_F=%d -> I_axis ~ 4 I0" % _nf, _ca_I, 4.0, 0.6, "Hecht/Born&Wolf; FFT zones")
    else:
        check("Circular aperture even N_F=%d -> I_axis ~ 0" % _nf, _ca_I, 0.0, 0.1, "Hecht/Born&Wolf; FFT zones")
# Knife-edge (straight-edge) Fresnel diffraction: I at the geometric edge = 1/4 I0, deep shadow -> 0
_ke_N, _ke_dx = 2048, 0.004
_ke_x = (_np.arange(_ke_N) - _ke_N // 2) * _ke_dx
_ke_U0 = _np.zeros((_ke_N, _ke_N), dtype=complex)
_ke_U0[:, _ke_x >= 0] = 1.0
_ke_U = field.angular_spectrum(_ke_U0, _ke_dx, 300.0, 500.0)
_ke_c = _ke_N // 2
check("Knife-edge: I at the geometric edge = 1/4 I0", float(_np.abs(_ke_U[_ke_c, _ke_c]) ** 2), 0.25, 0.03, "Cornu/Fresnel; FFT")
check("Knife-edge: deep shadow -> 0", float(_np.abs(_ke_U[_ke_c, _ke_c - 250]) ** 2), 0.0, 0.03, "Fresnel; FFT")
# Fresnel zone-plate focuses on axis at z = f = r1^2 / lambda (primary order)
_zp_lam, _zp_f = 500.0, 200.0
_zp_r1 = (_zp_lam * 1e-6 * _zp_f) ** 0.5
_zp_N = 1024
_zp_dx = 20 * _zp_r1 / _zp_N
_zp_x = (_np.arange(_zp_N) - _zp_N // 2) * _zp_dx
_zp_X, _zp_Y = _np.meshgrid(_zp_x, _zp_x)
_zp_r = _np.sqrt(_zp_X ** 2 + _zp_Y ** 2)
_zp_ap = ((_np.sin(_np.pi * _zp_r ** 2 / (_zp_lam * 1e-6 * _zp_f)) > 0) & (_zp_r <= 8 * _zp_r1)).astype(complex)
_zp_c, _zp_best, _zp_pk = _zp_N // 2, None, -1.0
for _zz in _np.linspace(0.6 * _zp_f, 1.4 * _zp_f, 17):
    _zI = float(_np.abs(field.angular_spectrum(_zp_ap, _zp_dx, _zz, _zp_lam)[_zp_c, _zp_c]) ** 2)
    if _zI > _zp_pk:
        _zp_pk, _zp_best = _zI, _zz
check("Zone-plate focus on axis at z = r1^2/lambda (200mm)", _zp_best, _zp_f, 12.0, "Hecht; FFT axial scan")
# Thin-lens (quadratic phase mask) focuses at z = f (2nd-moment waist minimum)
_ln_f, _ln_D, _ln_lam, _ln_N = 300.0, 4.0, 500.0, 1024
_ln_dx = 2.5 * _ln_D / _ln_N
_ln_x = (_np.arange(_ln_N) - _ln_N // 2) * _ln_dx
_ln_X, _ln_Y = _np.meshgrid(_ln_x, _ln_x)
_ln_r2 = _ln_X ** 2 + _ln_Y ** 2
_ln_ap = (_ln_r2 <= (_ln_D / 2) ** 2).astype(complex) * _np.exp(-1j * _np.pi * _ln_r2 / (_ln_lam * 1e-6 * _ln_f))
_ln_best, _ln_wmin = None, 1e9
for _lz in _np.linspace(0.5 * _ln_f, 1.5 * _ln_f, 15):
    _lw = field.field_metrics(field.angular_spectrum(_ln_ap, _ln_dx, _lz, _ln_lam), _ln_dx, _ln_lam)["w_2sigma_mm"]
    if _lw < _ln_wmin:
        _ln_wmin, _ln_best = _lw, _lz
check("Thin-lens (quadratic phase) focuses at z = f (300mm)", _ln_best, _ln_f, 30.0, "Goodman; FFT 2nd-moment scan")
# Newton's rings: m-th DARK ring radius r_m = sqrt(m lambda R) (reflection), central spot dark
check("Newton dark-ring r_10 = sqrt(10 lambda R) (R=10m, 589nm)", physics.newton_ring_radius(10, 589.0, 10000.0), 7.6746, 1e-3, "Hecht; oracle")
check("Newton central dark spot r_0 = 0", physics.newton_ring_radius(0, 589.0, 10000.0), 0.0, 1e-9, "Hecht; oracle")
# the 2-D Newton's-rings producer: central spot DARK, and the intensity nulls at the closed-form dark radii
from optical_alignment_sim import diagnostics as _ndiag
_nrm, _nrI = _ndiag.newton_rings_2d(1000.0, 589.3, n_rings=8, nx=400)
check("Newton 2D: central spot is dark (I(0) ~ 0)", _nrm["central_intensity"], 0.0, 1e-3, "Hecht; sin^2 phase")
# the m=4 dark ring is an intensity null: the radial profile reaches ~0 in a small window around r_4
# (window-min, robust to the half-pixel grid offset -- the null sits exactly at r_4 = sqrt(4 lambda R))
import numpy as _np4
_r4 = physics.newton_ring_radius(4, 589.3, 1000.0)
_field = _nrm["field_mm"]; _nx4 = _nrI.shape[0]
_c4 = (_nx4 - 1) / 2.0                                          # x=0 pixel (linspace centre)
_j4 = _c4 + _r4 / (_field / (_nx4 - 1))                         # pixel index at radius r_4 along +x
_lo, _hi = int(_j4) - 2, int(_j4) + 3
_ring_min = float(_nrI[int(round(_c4)), _lo:_hi].min())
check("Newton 2D: dark ring at r_4 = sqrt(4 lambda R) is an intensity null", _ring_min, 0.0, 0.01, "Hecht; sin^2(pi r^2/(lambda R))")

print("[Phenomenon emergence -- produce_phenomenon: synthesize the interferogram + record/reconstruct a hologram]")
from optical_alignment_sim import diagnostics as _diag
import math as _mh
# off-axis hologram: record the carrier interferogram, measure its spacing off the FFT, reconstruct the angle
_holo, _ = _diag._emerge_hologram(_mh.radians(10.0), 1.0, 632.8, nx=1024)
check("Hologram carrier spacing = lambda/(2 sin(theta/2)) (HeNe@10deg)", _holo["carrier_spacing_mm"] * 1000.0, 3.63028, 1e-3, "Goodman Ch.9; oracle")
check("Hologram FFT-measured carrier ~ theory (produced + measured)", _holo["carrier_spacing_fft_mm"], _holo["carrier_spacing_mm"], 0.02 * _holo["carrier_spacing_mm"], "FFT vs theory")
check("Hologram reconstruction recovers the crossing angle ~10deg", _holo["recovered_crossing_angle_deg"], 10.0, 0.15, "digital holography; FFT")
# two-beam interferogram: visibility V = 2 sqrt(Ia Ib)/(Ia+Ib)
_tb1, _ = _diag._emerge_two_beam(1.0, 632.8, nx=512)
check("Two-beam interferogram visibility V=1 (equal beams)", _tb1["visibility_measured"], 1.0, 1e-6, "Hecht Ch.9; oracle")
_tb2, _ = _diag._emerge_two_beam(0.8, 632.8, nx=512)
check("Two-beam interferogram visibility V=0.8 (4:1 beams)", _tb2["visibility_measured"], 0.8, 1e-6, "Hecht Ch.9; oracle")
# Fabry-Perot resonance: sweep the Airy curve -> finesse / T_min / contrast / FSR (R=0.9, L=10mm)
_fp, _ = _diag._emerge_fabry_perot(10.0, 0.9, 632.8)
check("Fabry-Perot emergence: finesse pi sqrt(R)/(1-R) (R=0.9)", _fp["finesse"], 29.804, 0.01, "Saleh&Teich; oracle")
check("Fabry-Perot emergence: T_min = ((1-R)/(1+R))^2", _fp["T_min"], 0.0027701, 1e-5, "Hecht; oracle")
check("Fabry-Perot emergence: contrast = ((1+R)/(1-R))^2", _fp["contrast"], 361.0, 0.5, "Saleh&Teich; oracle")
check("Fabry-Perot emergence: FSR = lambda^2/(2 n L) (632.8nm, 10mm)", _fp["fsr_nm"], 0.0200218, 1e-5, "Saleh&Teich; oracle")
# Talbot self-imaging: the grating's near field reproduces at z_T = 2 d^2/lambda (d=0.1mm)
_tbz, _ = _diag._emerge_talbot(0.1, 632.8)
check("Talbot emergence: z_T = 2 d^2/lambda (mm)", _tbz["talbot_distance_mm"], 31.6056, 1e-2, "Goodman; oracle")
check("Talbot emergence: self-image correlation ~ 1 at z_T", _tbz["self_image_corr"], 1.0, 0.2, "Goodman; angular-spectrum FFT")

print("[Interference filter / dichroic edge AOI blue-shift -- lambda_c sqrt(1-(sin theta/n_eff)^2)]")
from optical_alignment_sim import tracer as _trc
check("Dichroic/filter edge blue-shift: 650nm @45deg, n_eff=1.85 -> 600.6nm", _trc._aoi_blueshift(650.0, _mh.radians(45.0), 1.85), 600.6, 0.1, "thin-film interference; oracle")
check("Dichroic/filter edge blue-shift: 550nm @60deg, n_eff=1.85 -> 486.0nm", _trc._aoi_blueshift(550.0, _mh.radians(60.0), 1.85), 486.0, 0.1, "thin-film interference; oracle")

print("[Atmospheric turbulence -- dense Kolmogorov phase screen (FT method + subharmonics, off-trace)]")
from optical_alignment_sim import turbulence as _turb
check("Kolmogorov structure constant 6.88 = 2*(24/5*Gamma(6/5))^(5/6)", _turb.STRUCT_CONST, 6.8839, 1e-3, "Schmidt/Noll; oracle (gamma)")
_tN, _tdx, _tr0, _tseps = 256, 6.0, 100.0, [256 // 16, 256 // 8, 256 // 4]
_tDacc = _np.zeros(len(_tseps)); _tDns = _np.zeros(len(_tseps)); _tr = None
for _ts in range(12):                                            # ensemble-average (single-realization D has variance)
    _tsf = _turb.structure_function(_turb.kolmogorov_screen(_tN, _tdx, _tr0, seed=_ts), _tdx, _tseps)
    _tr = _np.array(_tsf["r_mm"]); _tDacc += _np.array(_tsf["D"])
    _tDns += _np.array(_turb.structure_function(_turb.kolmogorov_screen(_tN, _tdx, _tr0, seed=_ts, subharmonics=0), _tdx, _tseps)["D"])
_tDm = _tDacc / 12.0; _tDns /= 12.0
_tDt = _turb.STRUCT_CONST * (_tr / _tr0) ** (5.0 / 3.0)
check("Kolmogorov screen: ensemble D(r) ~ 6.88 (r/r0)^(5/3) (Schmidt structure-fn validation)", float(_np.mean(_tDm / _tDt)), 1.0, 0.25, "Schmidt; FFT vs theory")
check("Kolmogorov screen: structure-function log-log slope ~ 5/3", float(_np.polyfit(_np.log(_tr), _np.log(_tDm), 1)[0]), 5.0 / 3.0, 0.15, "Kolmogorov; FFT")
_tmid = len(_tr) // 2
check("Kolmogorov screen: ensemble r0 back-fit recovers input", float(_tr[_tmid] / (_tDm[_tmid] / _turb.STRUCT_CONST) ** (3.0 / 5.0)), _tr0, 0.2 * _tr0, "Fried r0; FFT")
check("Kolmogorov screen: subharmonics restore the low-frequency tail (D_SH/D_noSH at large r)", float(_tDm[-1] / _tDns[-1]), 2.33, 1.0, "Lane/Schmidt; FFT")

print("[Pulse propagation -- the opt-in split-step NLSE layer (1D temporal field, off-trace)]")
from optical_alignment_sim import nlse as _nl
_qT0, _qb2, _qg, _qP0 = 1.0, -0.02, 0.002, 10.0                 # N=1 fundamental soliton
_qLD = _qT0 ** 2 / abs(_qb2); _qz0 = (math.pi / 2.0) * _qLD
_qN, _qdt = 2048, 0.05
_qt = (_np.arange(_qN) - _qN // 2) * _qdt
_qA0 = _nl.sech_pulse(_qt, _qT0, _qP0)
_qm = _nl.pulse_metrics(_nl.split_step(_qA0, _qdt, 0.1, round(_qz0 / 0.1), _qb2, _qg), _qdt, A0=_qA0, t_ps=_qt)
check("NLSE fundamental soliton (N=1) shape-invariant over z0", _qm["shape_invariance_err"], 0.0, 5e-3, "Agrawal; split-step")
check("NLSE soliton conserves peak power (10 W)", _qm["peak_power_W"], 10.0, 0.05, "Agrawal; split-step")
_qf0 = _nl.pulse_metrics(_nl.gaussian_pulse(_qt, _qT0, _qP0), _qdt, t_ps=_qt)["fwhm_ps"]
_qfz = _nl.pulse_metrics(_nl.split_step(_nl.gaussian_pulse(_qt, _qT0, _qP0), _qdt, 0.1, round(_qLD / 0.1), _qb2, 0.0), _qdt, t_ps=_qt)["fwhm_ps"]
check("NLSE dispersion-only Gaussian broadens by sqrt(2) at z=L_D", _qfz / _qf0, math.sqrt(2), 0.05, "Agrawal; split-step")
_qAs0 = _nl.gaussian_pulse(_qt, _qT0, _qP0)
_qbw0 = _nl.pulse_metrics(_qAs0, _qdt, t_ps=_qt)["rms_bandwidth_THz"]
_qms = _nl.pulse_metrics(_nl.split_step(_qAs0, _qdt, 0.1, round(20 * _qLD / 0.1), 0.0, _qg), _qdt, A0=_qAs0, t_ps=_qt)
check("NLSE SPM-only preserves the temporal |A|^2", _qms["shape_invariance_err"], 0.0, 1e-2, "Agrawal; split-step")
check("NLSE SPM-only broadens the spectrum (bandwidth grows ~17x)", _qms["rms_bandwidth_THz"] / _qbw0, 17.5, 6.0, "Agrawal; split-step")
check("NLSE energy conserved (alpha=0)", _qm["energy_pJ"] / _nl.pulse_metrics(_qA0, _qdt, t_ps=_qt)["energy_pJ"], 1.0, 1e-3, "energy; split-step")

print("[Biomedical optics -- Monte-Carlo photon transport in a turbid slab (MCML-style, off-trace)]")
from optical_alignment_sim import mc_transport as _mc
_cmua, _cmus, _cg = 0.1, 10.0, 0.9
_cmueff = _mc.diffusion_mu_eff(_cmua, _cmus, _cg)
check("MC diffusion mu_eff = sqrt(3 mu_a (mu_a + mu_s'(1-g)))", _cmueff, 0.5745, 1e-3, "Wang&Wu; oracle")
_cma = _mc.monte_carlo_slab(_cmua, _cmus, _cg, 0.5, n_photons=40000, seed=1)            # thin -> ballistic
check("MC energy conserved R+T+A=1 (matched boundary)", _cma["energy_sum"], 1.0, 2e-3, "energy; MCML")
check("MC unscattered ballistic T ~ Beer-Lambert exp(-mu_t L)", _cma["ballistic_T"] / math.exp(-(_cmua + _cmus) * 0.5), 1.0, 0.2, "Beer-Lambert; MCML")
_cmb = _mc.monte_carlo_slab(_cmua, _cmus, _cg, 10.0, n_photons=40000, seed=1)           # thick -> diffusion
check("MC fluence penetration depth recovers diffusion mu_eff", _cmb["mu_eff_fit_per_mm"], _cmueff, 0.1, "diffusion; MCML")
check("MC thick-slab energy conserved R+T+A=1", _cmb["energy_sum"], 1.0, 2e-3, "energy; MCML")

print("[Imaging through turbulence -- multi-screen split-step long-exposure PSF (composes screens + field)]")
_le1 = _turb.long_exposure_psf(48.0, 8.0, 500.0, n_screens=1, n_grid=256, n_realizations=20, seed=0)        # D/r0=6
check("Turbulence long-exposure PSF is seeing-broadened (>>diffraction)", _le1["broadening"], 4.0, 1.6, "Fried seeing; FFT")
check("Turbulence long-exposure seeing FWHM ~ lambda/r0 (finite-grid ~0.5-0.8x ideal)", _le1["seeing_ratio"], 0.6, 0.35, "Fried; FFT (finite-grid deficit)")
_le4 = _turb.long_exposure_psf(48.0, 8.0, 500.0, n_screens=4, spacing_m=2.0, n_grid=256, n_realizations=12, seed=0)
check("Multi-screen split-step propagation conserves energy", _le4["energy_ratio"], 1.0, 1e-3, "angular spectrum; FFT")
_le2 = _turb.long_exposure_psf(48.0, 4.0, 500.0, n_screens=1, n_grid=256, n_realizations=20, seed=0)        # D/r0=12
check("Stronger turbulence (smaller r0) broadens the PSF more (monotone)", _le2["broadening"] - _le1["broadening"], 1.1, 0.8, "Fried; FFT")

print("=" * 60)
n_pass = sum(_checks)
n_total = len(_checks)
if n_pass == n_total:
    print("VALIDATION PASS  (%d/%d textbook checks)" % (n_pass, n_total))
    sys.exit(0)
else:
    print("VALIDATION FAIL  (%d/%d) — %d failed" % (n_pass, n_total, n_total - n_pass))
    sys.exit(1)
