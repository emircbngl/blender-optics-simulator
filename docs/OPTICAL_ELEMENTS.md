# Optical Elements & Variants — behavior reference

A reference catalog of the **real-world variants** of every optical element type, **what each does to the beam** (its optical behavior), the parameters that define it, real example parts, and **how it maps to (or extends) the add-on's `element_type` + params**. Built from a multi-agent literature/datasheet sweep (Thorlabs / Edmund / RP-Photonics / Wikipedia).

This is the **reference layer** (Phase B). Wiring these variants into the add-on as selectable, trace-and-render-bound options is Phase A. The tracer already encodes each element_type's core behavior (Jones matrices, Fresnel, the grating equation, Airy transmission, ABCD focal power, Zernike); the `Add-on mapping` line for each variant says which existing param covers it and which **new** param it needs.

**8 element categories, 118 variants.** Generated 2026-06-17.

> **Provenance & verification status.** The relations here are standard textbook optics compiled from
> manufacturer datasheets + references (Thorlabs, Edmund, RP-Photonics, Wikipedia) by a research-agent
> sweep. Their verification status against the project's physics oracle (`physicist` plugin) is:
> - **VERIFIED** in the project KB (`physics_lookup`, on sympy 1.14 / pint 0.24 / scipy 1.16): the
>   **thin-lens equation** `1/f = 1/d_o + 1/d_i`, the **grating / double-slit maxima** `d·sin θ = m·λ`
>   (the core of `mλ = d(sin θ_m − sin θ_i)`), and **Snell's law** `n₁ sin θ_i = n₂ sin θ_t`.
> - **GROUNDED** (the KB's verified focal-length / thin-lens concepts reference it as the established
>   relation): the **lensmaker's equation** `1/f = (n−1)(1/R₁ − 1/R₂)`.
> - **UNVERIFIED in this pass** (sourced-standard, not yet run through the oracle): everything else —
>   Jones/Mueller, Fresnel + coating reflectance, Airy/finesse, retardance dispersion, NA = D/2f, f/# = f/D,
>   nonlinear phase-matching, etc. Treat these as reference, not oracle-confirmed.
>
> This document changes **no computed physics** — the add-on's numerical behavior lives in `physics.py` /
> `tracer.py`. When Phase A wires any UNVERIFIED relation into the tracer as real computation, that
> specific formula is **oracle-verified before it ships**.

---

## Lenses

> **Tracer / behavior model:** The tracer should treat LENS as a family selected by ONE new enum lens_type, and keep focal_length(signed)+clear_aperture as the spine. Behaviorally there are only FIVE distinct things a lens does to the beam, and every real variant is a combination of them:

1. SIGN + MAGNITUDE of ABCD power (already implemented as abcd_lens(f)). PCX/BCX/positive-meniscus/asphere/ball/GRIN/Fresnel/achromat = converging f>0; PCV/BCV/negative-meniscus = diverging f<0. For all of these, the existing q = q_propagate(q, abcd_lens(f_eff)) at tracer.py:189-194 is correct. Sign already drives both the ABCD and the cosmetic mesh sag (_lens_profile).

2. CHROMATIC DISPERSION LAW f(wl). The current code applies the SINGLET law f_eff = f*(n_design-1)/(n(wl)-1) to EVERY LENS. This is only right for the simple singlets (PCX, PCV, BCX, BCV, meniscus, ball, Fresnel-ish). It is WRONG for the achromat (must be nearly flat across the design band -> gate the singlet law behind 'if not doublet'), and it is materially different for GRIN (dispersion comes from n0 and gradient, not 1/(n-1)). Add a doublet bool that, when true, holds f_eff~f (optionally a small secondary-spectrum residual) over the design band. Optionally carry Vd/Abbe so the singlet color is quantitative rather than just Sellmeier-scaled.

3. ANISOTROPY (1D vs 2D power). Cylindrical lenses break the rotational symmetry the scalar q assumes -- they apply power on ONE transverse axis only. To model them faithfully the Gaussian state must become astigmatic (separate qx,qy or a rotate->apply-1D-ABCD->rotate), driven by NEW params axis_angle_deg and a rectangular aperture. This is the single biggest structural extension; everything else fits the existing scalar q.

4. NON-IDEAL / ABERRATION CONTENT. A real spherical SINGLET at low f/# carries spherical aberration; an ASPHERE and a GRIN are near-aberration-free; a BALL lens is heavily aberrated unless underfilled; a FRESNEL adds scatter + chromatic blur. Today the LENS is a perfect thin lens (no SA). If/when spherical aberration is added, drive it from lens_type + f/# (= f/clear_aperture): inject it the same way the ABERRATOR injects Zernikes (the project already has aberr_spec / Zernike plumbing and a DEFORMABLE_MIRROR that subtracts them). asphere/GRIN -> zero SA; ball/Fresnel -> large; meniscus/best-form -> reduced. This reuses existing Zernike machinery instead of new math.

5. NON-FOCUSING TRANSFORMS. The AXICON is not a focusing lens at all -- abcd_lens(f) cannot represent it. It needs a radius-dependent inward ray deflection (beta=(n-1)*apex_angle) that produces a Bessel/ring, i.e. a dedicated branch keyed on lens_type=='AXICON' with apex_angle_deg. Similarly a faithful GRIN wants its own ABCD [[cos(gL), sin(gL)/(n0 g)],[-n0 g sin(gL), cos(gL)]] from pitch/length rather than a thin abcd_lens(f); a thick-lens or ball lens with a meaningful BFL=f-D/2 wants a principal-plane / vertex offset so the focus renders at the right z.

Recommended minimal param additions to the LENS optics block: lens_type (EnumProperty: PCX, BCX, PCV, BCV, MENISCUS_POS, MENISCUS_NEG, ACHROMAT, ASPHERE, CYLINDRICAL, BALL, HALF_BALL, GRIN, FRESNEL, AXICON); R1, R2 (signed FloatProperty radii, optional, 0=infinite/derive-from-f); doublet (bool, gates the chromatic law); conic_constant (float, for asphere, also a flag to null SA); axis_angle_deg (float, cylindrical orientation); apex_angle_deg (float, axicon); pitch (float, GRIN); diameter/index where ball & GRIN derive f. Keep focal_length(signed) as the universal fallback so existing scenes and the default 'LENS' (a generic thin lens) keep working unchanged. Dispatch in tracer.py at the existing LENS branch (line 189): default = current abcd_lens(f_eff) with singlet color; ACHROMAT = abcd_lens(f) flat-color; CYLINDRICAL = 1D astigmatic ABCD; GRIN = GRIN ABCD; AXICON = radial-deflection branch. Aperture: keep the Gaussian clip for round optics; cylindricals want a rectangular clip.

#### Plano-convex (PCX)
- **What it is:** One flat surface (R2=inf) and one outward-bulging spherical surface (R1>0). The workhorse converging singlet; the most common 'focus a collimated beam / collimate a point source' lens. Thicker at center than edge.
- **Optical behavior:** Positive (converging) focal length, f>0. Thin-lens power 1/f=(n-1)/R1 since 1/R2=0. Real-image former. Asymmetric, so spherical aberration is minimized by orienting the CONVEX face toward the collimated (more-collimated) side -- splits ray bending over both refractions. Introduces appreciable spherical aberration at low f/# and chromatic aberration (f scales with n(wl)). Maps to a single converging ABCD lens of focal f.
- **Key params:** f>0 (50-1000mm typical for 1in optics), R1 finite (R1=(n-1)f), R2=inf, material N-BK7 (n~1.515, Vd=64) or UVFS (n~1.46), clear_aperture = diameter (Ø1/2in=12.7mm, Ø1in=25.4mm), center thickness CT, edge thickness ET. f/# = f/D, NA=D/(2f).
- **Add-on mapping:** lens_type='PCX'. focal_length>0 already covers ABCD power. NEW: optional R1 (signed radius, mm) so f can be derived from (n-1)/R and so the chromatic law uses the true singlet 1/(n-1) scaling (already implemented). NEW optional orient_convex bool to drive the asymmetric spherical-aberration sign if SA is later modeled. clear_aperture unchanged.
- **Real examples:** Thorlabs LA1805 (N-BK7, Ø1in, f=30mm, R1=15.5mm); LA1399-B (N-BK7, Ø2in, f=175mm, 650-1050nm AR); LA4647 (UVFS, f=100mm); Edmund #63-471. Kits: LSB01-C 14pc, LSB04-B 35pc.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=LA1805 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=112 ; https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=8790

#### Bi-convex / double-convex (BCX)
- **What it is:** Both surfaces bulge outward (R1>0, R2<0), roughly symmetric. Converging singlet used for ~1:1 (finite-conjugate) imaging where object and image distances are similar.
- **Optical behavior:** Positive focal length f>0; 1/f=(n-1)(1/R1 - 1/R2) with R2<0 so both terms add -> shorter f than a PCX of the same radius. Near-symmetric, so it is the best singlet for unit-magnification relay (symmetry cancels coma, distortion, lateral color at 1:1). More spherical aberration than a best-form/asphere at infinite conjugate. Same converging ABCD action as PCX.
- **Key params:** f>0, R1>0 and R2<0 (commonly |R1|=|R2| symmetric, i.e. R2=-R1), N-BK7/UVFS, diameter, CT, ET. For symmetric BCX, R = 2(n-1)f.
- **Add-on mapping:** lens_type='BCX'. focal_length>0 unchanged. NEW: optional R1 and R2 (both signed) for symmetric-vs-asymmetric and to feed thick-lens lensmaker if principal planes are ever added. No change to clear_aperture or to the existing 1/(n-1) chromatic law.
- **Real examples:** Thorlabs LB1471 (N-BK7, Ø1in, f=50mm, R1=-R2=51.5mm); LB1761 (f=25.4mm); Edmund double-convex series. Included in LSB04-B mixed kit.
- **Refs:** https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=8790 ; https://en.wikipedia.org/wiki/Lens

#### Plano-concave (PCV)
- **What it is:** One flat surface and one inward-curving spherical surface (R1<0 or R2>0 depending on orientation). Diverging singlet, thinner at center than edge.
- **Optical behavior:** Negative (diverging) focal length f<0. Spreads a collimated beam, forms a virtual image, increases beam divergence / expands beams (as the negative element of a Galilean expander). Same magnitude chromatic dispersion law as positive singlets but opposite sign of power. Maps to a diverging ABCD lens (negative f). Curved face toward the collimated beam minimizes spherical aberration.
- **Key params:** f<0 (e.g. -25 to -1000mm), one R finite (R=(n-1)f, negative), other R=inf, N-BK7/UVFS, diameter, CT (thin center), ET (thick edge).
- **Add-on mapping:** lens_type='PCV'. focal_length<0 already handled (the mesh builder _lens_profile already flips to a thin-center biconcave cap when focal<0). NEW optional R (signed) only. No new core behavior needed -- negative ABCD power is already correct.
- **Real examples:** Thorlabs LC1715 (N-BK7, Ø1in, f=-50mm); LC1054 (f=-25mm); LD series UVFS. Negative members of LSB04-B.
- **Refs:** https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=8790

#### Bi-concave / double-concave (BCV)
- **What it is:** Both surfaces curve inward (R1<0, R2>0). Symmetric diverging singlet, used to expand beams or shorten an optical path's effective focal length.
- **Optical behavior:** Negative focal length f<0; 1/f=(n-1)(1/R1 - 1/R2) with R1<0,R2>0 so both terms subtract -> stronger divergence than PCV of same |R|. Virtual upright minified image. Symmetric -> good for symmetric beam-diverging tasks. Diverging ABCD action.
- **Key params:** f<0, R1<0 and R2>0 (often symmetric R2=-R1), R=-2(n-1)|f| magnitude, N-BK7/UVFS, diameter, CT, ET.
- **Add-on mapping:** lens_type='BCV'. focal_length<0 unchanged. NEW optional R1,R2 (signed). Mesh already renders thin-center for negative focal. No new tracer behavior.
- **Real examples:** Thorlabs LD1464 (N-BK7, Ø1in, f=-50mm); LD2060 (f=-30mm); Edmund double-concave series.
- **Refs:** https://en.wikipedia.org/wiki/Lens ; https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=8790

#### Positive meniscus (convex-concave, converging)
- **What it is:** Both surfaces curve the same way; convex face steeper than concave face. Net converging. Often paired with another lens to shorten system f without adding spherical aberration; also used as a field-flattener / aberration-balancing element.
- **Optical behavior:** f>0 but weakly converging for its curvatures. 1/f=(n-1)(1/R1-1/R2) with R1>0,R2>0 and R1<R2 (convex side has the SMALLER radius). Minimizes 3rd-order spherical aberration when added to a strong positive lens (the two surfaces of like sign reduce ray-angle change per surface). Orientation: convex toward the source/collimated side. Still a converging ABCD element.
- **Key params:** f>0, R1>0 (small) and R2>0 (large), |R1|<|R2| so positive; N-BK7/UVFS; diameter; CT>ET. Defining feature is two same-sign radii with the convex one steeper.
- **Add-on mapping:** lens_type='MENISCUS_POS'. focal_length>0 captures the ABCD power. NEW: R1,R2 both required here (same sign) because the meniscus identity is the curvature pair, not just f. Optional flag/param to mark it as a low-SA add-on element if a spherical-aberration term is later injected (could feed ABERRATOR-style Zernike with reduced coefficient).
- **Real examples:** Thorlabs N-BK7 Positive Meniscus group (ObjectGroup 130), e.g. LE1234 (f=50mm); UVFS positive meniscus (ObjectGroup 2491). Edmund positive meniscus series.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=130 ; https://www.thorlabs.com/NewGroupPage9_PF.cfm?Guide=10&Category_ID=220&ObjectGroup_ID=2491

#### Negative meniscus (concave-convex, diverging)
- **What it is:** Both surfaces curve the same way; concave face steeper than convex face. Net diverging. Used to diverge light with minimal spherical aberration, as the front element of retrofocus/wide systems, or to balance aberrations of a positive group.
- **Optical behavior:** f<0 (weakly diverging). 1/f=(n-1)(1/R1-1/R2) with both R same sign but concave surface having the GREATER curvature (smaller radius) so net negative. Minimizes spherical aberration when diverging a beam (orient convex surface toward the incoming beam). Diverging ABCD element with a 'soft' power.
- **Key params:** f<0, R1 and R2 same sign, concave radius smaller (steeper); the concave side has greater radius than convex per Thorlabs phrasing for the positive case -- inverted here; N-BK7/UVFS; diameter; CT<ET.
- **Add-on mapping:** lens_type='MENISCUS_NEG'. focal_length<0 captures ABCD power. NEW: R1,R2 (same sign) needed to express the meniscus shape. Like the positive meniscus, optionally flagged as low-SA. No new core tracer math beyond optional SA scaling.
- **Real examples:** Thorlabs Ø1in N-BK7 Negative Meniscus group (navigation guide_id 105 / '1-inch-n-bk7-negative-meniscus-lenses'), e.g. LF1015 (f=-100mm). Edmund negative meniscus series.
- **Refs:** https://www.thorlabs.com/navigation.cfm?guide_id=105 ; https://www.thorlabs.com/1-inch-n-bk7-negative-meniscus-lenses

#### Achromatic doublet (achromat)
- **What it is:** Two cemented elements: a positive low-dispersion crown (e.g. N-BK7, N-BAF10, N-LAK22; Vd>50, n<1.55) bonded to a negative high-dispersion flint (e.g. SF2/SF5/SF6/N-SF10; Vd<50, n>1.55). Single compound lens that behaves as one converging optic with corrected color.
- **Optical behavior:** f>0 (a few negative 'achromatic doublet' diverging versions exist). Brings TWO wavelengths (typically blue F and red C lines) to a common focus, so the focal-length-vs-wavelength curve is nearly FLAT across the design band instead of the 1/(n-1) tilt of a singlet. Also strongly reduces spherical aberration and coma vs a singlet of the same f. THIS IS THE KEY DIVERGENCE FROM THE CURRENT MODEL: the tracer currently applies a singlet chromatic law f_eff=f*(n_d-1)/(n(wl)-1) to every LENS -- for a doublet that law is wrong and must be replaced by an (almost) wavelength-independent f over the design band.
- **Key params:** Effective focal length EFL>0 (signed), design band (A:400-700, B:650-1050, C:1050-1620, AB:400-1100), two glasses + two Vd numbers, three radii (R1 crown-front, R2=R3 cemented, R4 flint-back), diameter, CT. Defining flag: doublet=True (suppresses singlet dispersion law).
- **Add-on mapping:** lens_type='ACHROMAT' (or keep LENS + NEW bool doublet=True). focal_length=EFL (signed) unchanged. NEW param doublet (bool) that switches the chromatic model in tracer.py line 189-194: when set, hold f_eff~f flat across the design band (or apply a small residual secondary-spectrum curve) instead of f*(n_d-1)/(n(wl)-1). Optional NEW: two Abbe numbers Vd_crown, Vd_flint and crown/flint glass keys if a faithful achromat dispersion is wanted. clear_aperture unchanged.
- **Real examples:** Thorlabs AC254-100-A (N-BK7/SF5, Ø1in, EFL=100mm, 400-700nm); AC254-050-A (N-BAF10/N-SF10, EFL=50mm); AC254-200-B (N-LAK22/N-SF10, EFL=200mm, 650-1050nm); AC254-035-B (N-BAF10/N-SF6HT, EFL=35mm). 'AC254'=Ø25.4mm; mounted -ML versions exist.
- **Refs:** https://www.newport.com/n/achromatic-doublet-lenses ; https://en.wikipedia.org/wiki/Doublet_(lens) ; https://www.3doptix.com/catalog/optics/lens/thorlabs/AC254-100-A ; https://www.fiberoptics4sale.com/blogs/wave-optics/achromatic-doublets

#### Aspheric lens (asphere)
- **What it is:** At least one non-spherical surface whose sag follows z(r)=r^2/(R(1+sqrt(1-(1+k)r^2/R^2))) + higher-order A4,A6,... terms, with conic constant k. Single converging element engineered to be diffraction-limited at high NA.
- **Optical behavior:** f>0, converging. The aspheric profile CANCELS spherical aberration so the focus approaches the diffraction limit even at low f/# / high NA -- the regime where a spherical singlet fails badly. Used for laser-diode collimation and fiber coupling (small f, large NA). Conic k: 0=sphere, -1=parabola, between -1 and 0 = ellipse, <-1 = hyperbola; chosen numerically to null SA. Behaves as an ideal thin converging ABCD lens with NEAR-ZERO spherical aberration (i.e. the opposite of a singlet: it should NOT carry the SA term a singlet would).
- **Key params:** f>0 (short, 1.5-20mm typical for collimators), high NA (0.15-0.6), conic constant k, surface coefficients A4..A12, diameter (often Ø few-mm), CT, working distance. Material: molded glass (D-ZK3 etc.) or plastic.
- **Add-on mapping:** lens_type='ASPHERE'. focal_length>0 unchanged. NEW: conic_constant (k) param; primarily a FLAG that tells the tracer to suppress the spherical-aberration contribution (and to keep f exact across aperture) rather than to apply the singlet SA a future model would add. High NA / small clear_aperture already expressible via clear_aperture. Optional A4/A6 coefficients only if a real aspheric sag is rendered.
- **Real examples:** Thorlabs ASL10142 (molded glass asphere); A220/A230/A240 series diode collimators; AL series Ø1in (e.g. AL2520 f=20mm, NA0.54). Edmund precision aspheres. Molded plastic asphere group (ObjectGroup 16).
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3809 ; https://www.thorlabs.com/molded-plastic-aspheres ; https://opg.optica.org/ao/upcoming_pdf.cfm?id=295102

#### Cylindrical lens (plano-convex / plano-concave cylinder)
- **What it is:** Curved along ONE axis only (one cylindrical surface, one plano or second cylindrical). Has optical power in a single meridian; the orthogonal meridian is flat (zero power).
- **Optical behavior:** Focuses a collimated beam to a LINE (PCX cylinder, f>0) or expands along one axis (PCV cylinder, f<0). Used to circularize elliptical laser-diode beams, form light sheets / line foci, and in anamorphic / 1D beam shaping. Power is ANISOTROPIC: f along the powered axis, infinity along the flat axis. This is the key divergence -- the current scalar ABCD f is rotationally symmetric; a cylinder needs power on ONE transverse axis (an astigmatic / cylindrical ABCD, e.g. separate qx and qy).
- **Key params:** f (signed) in the powered meridian, axis_angle (orientation of the powered axis in the transverse plane, deg), R (one radius, other =inf), rectangular aperture (width x height) rather than circular, N-BK7/UVFS/CaF2. Curved surface toward collimated beam to reduce SA.
- **Add-on mapping:** lens_type='CYLINDRICAL'. focal_length signed = powered-meridian f. NEW params: axis_angle_deg (which transverse axis carries the power) and a NEW behavior path in the tracer to apply ABCD power on only one axis (split q into qx,qy or rotate-apply-rotate). NEW optional aperture_w/aperture_h for the rectangular clear aperture instead of the single clear_aperture radius. Largest single extension to the tracer (1D vs 2D power).
- **Real examples:** Thorlabs LJ1695RM (N-BK7 PCX cylinder, f=50mm); LJ1144L1 (UVFS); LK series plano-concave cylinder; UVFS plano-convex cylindrical group (ObjectGroup 135); ZnSe cylinders for IR. Edmund cylindrical series.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=135 ; https://www.thorlabs.com/cylindrical-lenses ; https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=2796

#### Ball lens / half-ball lens
- **What it is:** A full glass sphere (ball) or hemisphere (half-ball). Extremely short-focal-length converging optic for fiber-to-fiber coupling and laser-diode collimation; compact 'drop-in' coupler.
- **Optical behavior:** f>0, strongly converging. EFL f = nD/(4(n-1)) measured from the ball center; BFL = f - D/2 (the working/back focal distance, often very short and sometimes negative -> focus inside or at the surface). Principal planes sit ~at the sphere center. Heavy spherical aberration unless the input beam fills only a small fraction of the sphere, so high-index glass is used to shorten f and let a smaller beam do the work. n choices: UVFS 1.45 (long BFL, easy handling), sapphire 1.76, LASFN9 1.85, cubic zirconia n>2 (shortest f, least aberration). Acts as a converging ABCD lens of that f.
- **Key params:** Diameter D (0.5-10mm), refractive index n -> f=nD/(4(n-1)), BFL=f-D/2, NA, material (BK7/UVFS/sapphire/LASFN9). Half-ball is interchangeable with full ball but mounts flat; its f reference shifts to the flat face.
- **Add-on mapping:** lens_type='BALL' (and 'HALF_BALL'). focal_length>0 = nD/(4(n-1)) (can be auto-derived). NEW: diameter D param and material/index n so f and BFL are computed, plus an is_half flag. Because EFL is from the center, the port/back-focal offset (BFL=f-D/2) is geometrically meaningful -- NEW optional bfl so the focus position renders correctly. clear_aperture~D. Should carry strong spherical aberration unless small-beam (could feed a Zernike SA term).
- **Real examples:** Edmund ball-lens series + ball-lens calculator; Thorlabs sapphire/UVFS ball lenses; LASFN9 coupling balls. Edmund half-ball lenses for endoscopy/sensors.
- **Refs:** https://www.rp-photonics.com/ball_lenses.html ; https://www.edmundoptics.com/knowledge-center/application-notes/optics/understanding-ball-lenses/ ; https://en.wikipedia.org/wiki/Ball_lens

#### GRIN lens (gradient-index rod, SELFOC)
- **What it is:** A flat-faced glass rod whose refractive index varies radially: n(r)=n0(1 - A r^2/2). Rays follow a sinusoidal path inside; focusing is DISTRIBUTED through the volume, not at the surfaces. Specified by 'pitch' (fraction of the sinusoidal period in the rod length).
- **Optical behavior:** Converging, but the action depends on pitch P: 0.25 pitch (quarter-pitch) collimates a point source at the face / behaves like a thin lens one focal length from the object -> the standard fiber collimator. 0.23-0.29 pitch gives a small working distance for fiber pigtailing. Very low on-axis aberration for near-axis objects -> ideal for SM/PM fiber collimation and endoscope relays. Flat faces make it butt-couplable. Effective f set by n0, gradient constant A=sqrt(g), and length; ABCD of a GRIN is [[cos(gL), sin(gL)/(n0 g)],[-n0 g sin(gL), cos(gL)]].
- **Key params:** Pitch P (0.23-0.29 for collimators, 0.25 nominal), diameter (1.0-1.8mm), gradient constant g/A, n0, design wavelength, length L, NA (~0.5), end-face angle (0deg or 8deg for back-reflection). Defining param is pitch, not radii.
- **Add-on mapping:** lens_type='GRIN'. focal_length>0 can stand in for the effective f, but the FAITHFUL model is the GRIN ABCD (cos/sin of g*L) -- so NEW params pitch (or g and length L), n0, and diameter, with a NEW tracer branch that builds the GRIN ABCD instead of abcd_lens(f). Flat-face geometry means no cosmetic curvature (the mesh should be a plain rod, unlike the biconvex cap). Low aberration -> no SA term.
- **Real examples:** Thorlabs GRIN2913 (Ø1.8mm, 0.29 pitch, 0deg, 1300nm); GRIN2906 (820nm); single-wavelength GRIN group (ObjectGroup 1209); SELFOC (NSG) rods; Newport/GRINTECH micro-GRIN.
- **Refs:** https://www.thorlabs.com/item/GRIN2913 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1209 ; https://spie.org/publications/spie-publication-resources/optipedia-free-optics-information/tt48_55_gradient_index_lens

#### Fresnel lens
- **What it is:** A conventional lens collapsed into concentric annular grooves on a thin flat plastic/polymer sheet; each groove is a tiny prism approximating the local slope of the parent lens. Large aperture, very light and thin.
- **Optical behavior:** Converging (f>0; negative Fresnels exist). Approximates a thin lens of focal length f for collimation / light gathering, but with degraded image quality: strong chromatic aberration with broadband light, scatter/diffraction at the groove edges, and geometric distortion. Trade-off: high groove density -> better image, lower density -> better throughput. Used as condensers, solar concentrators, emitter/detector collimators, overhead-projector optics -- NOT precision imaging. To the tracer it is a converging ABCD lens of focal f, optionally flagged as 'low image quality' (extra scatter / chromatic).
- **Key params:** f>0 (often very short relative to a huge aperture -> very low f/#), aperture (can be large, square or round, e.g. 8.85in sheet f=1.77in), groove pitch/density, material PMMA/polycarbonate (n~1.49-1.59), thickness ~1-3mm. Defining feature: large clear_aperture, short f, plastic n.
- **Add-on mapping:** lens_type='FRESNEL'. focal_length>0 + a (typically large) clear_aperture already capture the first-order behavior. NEW optional: groove_density and a low_image_quality flag to drive extra scatter / stronger chromatic spread if modeled. Mesh should be a thin flat disc (no spherical cap). No principal-plane offset (thin).
- **Real examples:** Edmund 42294 (8.85in x 8.85in, f=1.77in); Edmund 2434 (6.7in, f=6in); Edmund 4738 (14in dia, f=24in); Fresnel Technologies / NTKJ sheets.
- **Refs:** https://www.edmundoptics.com/knowledge-center/application-notes/optics/advantages-of-fresnel-lenses/ ; https://www.edmundoptics.com/p/885-x-885-177-focal-length-fresnel-lens/42294/

#### Axicon (conical lens)
- **What it is:** A rotationally symmetric prism: one conical surface + one plano face. Not a focusing lens -- it transforms a collimated input into a Bessel beam / ring rather than a point.
- **Optical behavior:** Deflects every ray by a fixed angle beta toward the axis (beta = (n-1)*alpha for small physical apex/base angle alpha, by Snell's law), so a collimated beam becomes a cone of light. Over the overlap (depth of focus) region behind the axicon it forms a near-non-diffracting BESSEL beam (a bright central core surrounded by rings); far beyond it forms an expanding RING of radius growing linearly with distance. NO single focal point -- this fundamentally does NOT fit the abcd_lens(f) model. Used for laser drilling, corneal surgery, optical trapping, long-DOF illumination. Plano side faces the collimated source.
- **Key params:** Physical apex/base angle alpha (e.g. 0.349 rad), deflection angle beta, ring growth rate, Bessel DOF = R/tan(beta) for input radius R, material UVFS, diameter, center thickness. Defining param is the cone angle, not a focal length.
- **Add-on mapping:** lens_type='AXICON'. focal_length is NOT meaningful -- NEW param apex_angle_deg (or deflection beta). Needs a NEW tracer branch (it is the largest behavioral outlier): instead of an ABCD focal it applies a radius-dependent inward tilt (each ray bent by beta toward axis), producing a ring/Bessel transform rather than a focus. Could be modeled as a phase element / radial deflection on the ray bundle. clear_aperture = diameter.
- **Real examples:** Thorlabs AX2520 (UVFS, Ø1in, alpha=0.349rad / ~20deg physical, CT=9.6mm, 532nm); AX2510-B (10deg, 650-1050nm AR); UVFS axicon group (ObjectGroup 4277); Edmund axicons.
- **Refs:** https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=4277 ; https://www.3doptix.com/catalog/optics/prism/thorlabs/AX2520 ; https://www.edmundoptics.com/knowledge-center/application-notes/lasers/an-in-depth-look-at-axicons/

---

## Mirrors & Coatings

> **Tracer / behavior model:** Model this category along TWO INDEPENDENT axes and the rest falls out cleanly:

AXIS 1 — SURFACE FIGURE (sets geometry + focal power):
- FLAT: today's behavior. d_out = reflect(d_in, n). No focal power. (flat dielectric, all metals as-shipped, D-shaped, cold/hot, DM facesheet).
- CONCAVE / CONVEX SPHERICAL: add focal power on reflection using f = R/2 (VERIFIED, paraxial: phys.libretexts OpenStax Vol.3 §2.3). Concave = converging (f>0), convex = diverging (f<0). This is the #1 missing capability: the tracer only applies ABCD focal power when element_type=='LENS' (tracer.py ~line 189). The clean fix is to let MIRROR carry a signed focal_length (or a NEW mirror_roc_mm with f=R/2) and run the SAME Gaussian-q/ABCD update on the reflected ray. Signed-focal convention already exists for LENS, so concave=+ / convex=- needs no new sign machinery. At finite AOI a sphere adds astigmatism+coma — out of chief-ray scope but worth a note for a future aberration pass.
- OFF-AXIS PARABOLIC: reflect + a FIXED fold by off_axis_deg (NOT the surface-normal reflect) + focal power f=RFL (reflected focal length). Aberration-free on-axis (no spherical aberration; OpenStax/Avantier). NEW params off_axis_deg + rfl_mm.
- D-SHAPED: flat + a HALF-PLANE knife-edge clip (reuse _clip_T as a one-sided edge, NEW edge_offset/axis).
- CORNER-CUBE / retroreflector: already its own RETROREFLECTOR type (d_out=-d_in, AOI-insensitive) — keep separate from mirrors.

AXIS 2 — COATING (sets reflectivity-vs-wavelength-and-angle + polarization-on-reflection), ORTHOGONAL to figure (any coating on any figure):
- METALLIC (AL/AG/AU, plus protected vs enhanced/UV vs bare): ALREADY handled via physics.METALS + fresnel_reflect + reflect_field, which correctly gives s/p amplitude+phase divergence at AOI (so 45deg reflection rotates azimuth / adds ellipticity — good, keep). THE GAP: METALS holds a SINGLE complex (n,k) per metal, so R is flat vs wavelength and WRONG at the band edges — it misses Ag's <400nm UV cutoff, Au's <600nm blue dropoff, and Al's 800-900nm dip. FIX: make METALS a small tabulated n(lambda),k(lambda) (refractiveindex.info: Rakic/McPeak for Al/Ag/Au) and interpolate at ray.wl. Add enum values to distinguish protected vs UV-enhanced Al (band edge differs) and protected vs unprotected Au.
- DIELECTRIC STACK (broadband mirror, laser-line HR, and the cold/hot dichroics): today coating=='DIELECTRIC' = IDEAL scalar (rp=-rs, perfect conductor convention) and is wavelength-flat. Two upgrades: (1) band-gate the reflectivity by ray.wl using a NEW coating_band_lo/hi (reuse the FILTER/DICHROIC band logic) so R drops outside the design band; (2) for 45deg polarization fidelity, a NEW sp_phase_deg so the dielectric branch stops assuming rp=-rs (real dielectric stacks have a design-specific s-p retardance that makes 45deg-incident linear light slightly elliptical). For LIDT/power-budget, an optional lidt param flags damage in the C8 budget.
- COLD / HOT MIRROR: NOT a new physics path — these are DICHROIC in reflection. Cold = pass_type LP (transmit IR / reflect visible), Hot = pass_type SP (transmit visible / reflect IR), cut_nm ~700, AOI 45deg. The existing DICHROIC branch (tracer.py ~374-384) already does exactly this; just add presets/labels.

NET NEW PARAMETERS the add-on needs (minimal set):
1. mirror_roc_mm (or reuse signed focal_length on MIRROR) — curvature/focal power for concave/convex/spherical. [biggest one]
2. off_axis_deg + rfl_mm — off-axis parabola fold + focus.
3. wavelength-tabulated n(lambda),k(lambda) inside physics.METALS — real metal R-vs-wavelength (UV/blue/IR band edges).
4. coating_band_lo_nm / coating_band_hi_nm — band-limit dielectric & laser-line reflectance.
5. New coating enum values: AL_UV (UV-enhanced), AU_BARE (unprotected) — band edges differ from protected.
6. (optional) sp_phase_deg — dielectric s-p retardance for 45deg polarization accuracy; lidt_* — laser-damage flag; edge_offset/axis — D-shaped half-clip.
ALREADY DONE / REUSE AS-IS: metal Fresnel s/p (physics.METALS + reflect_field), DICHROIC reflect/transmit (cold/hot mirrors), DEFORMABLE_MIRROR Zernike subtract, RETROREFLECTOR, ABCD focal machinery (just needs to fire for MIRROR too). The single highest-value change is wiring focal power into the MIRROR branch (f=R/2) so curved mirrors stop being flat.

#### Flat / plane mirror (broadband dielectric, e.g. BB1-E02)
- **What it is:** A planar fused-silica (or BK7/Pyrex) substrate with a stack of alternating high/low index dielectric quarter-wave layers (e.g. TiO2/SiO2). No metal. The dielectric stack gives a high-reflectance band tuned to a design range; outside the band it transmits/passes. This is the workhorse 'turning mirror' for a single laser band.
- **Optical behavior:** Specular reflection d_out = reflect(d_in, n), angle of incidence in = angle out. Power: R is very high (>99% typ, >99.5% over the design band) but band-limited — sharp rolloff at the band edges, so it is NOT broadband the way a metal is. Polarization: dielectric stacks at non-normal AOI split s and p with a design-dependent reflectance and a relative s-p phase shift, so they can introduce ellipticity at 45deg (unlike the ideal rp=-rs the tracer assumes). At normal incidence polarization is preserved. No focal power (flat). The 'look': clean transmissive-glass substrate with a faint colored sheen on the coated face (color = the leak band), back face bare glass.
- **Key params:** design band [lo_nm, hi_nm] (e.g. 400-750), peak reflectance R, design AOI (0deg or 45deg), substrate, surface flatness (lambda/10), s/p phase shift vs AOI (for polarization-accurate Jones).
- **Add-on mapping:** Maps to MIRROR with coating='DIELECTRIC'. Today coating='DIELECTRIC' = ideal scalar reflectivity (rp=-rs, R from the reflectivity float). NEW PARAMS to be real: coating_band_lo_nm / coating_band_hi_nm (so R drops outside band — reuse the FILTER/DICHROIC band logic to gate reflectivity by ray.wl), and design_aoi_deg. For polarization fidelity at 45deg, NEW optional sp_phase_deg (s-p retardance) so the dielectric branch stops assuming the perfect-conductor rp=-rs convention. design_wl already exists and can carry the band center.
- **Real examples:** Thorlabs BB1-E02 (Ø1", 400-750 nm, Ravg>99%, fused silica, lambda/10 @633nm, 10-5 scratch-dig); BB1-E01 (350-400 nm UV), BB1-E03 (750-1100 nm NIR), BB1-E04 (1280-1600 nm). Square: BBSQ20-E02. Edmund #34-281 family. AOI design 0-45deg; substrate 6 mm thick.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=BB1-E02 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=139

#### Dielectric laser-line / high-power laser mirror (e.g. NB1-K08 @1064, BB1-E02 used on-line)
- **What it is:** A narrowband dielectric high-reflector optimized for ONE laser wavelength (and often one AOI, 0deg or 45deg) with R>99.9% and a high laser-damage threshold (LIDT). Used inside/around laser cavities and for steering high-power beams where a metal would burn.
- **Optical behavior:** Same specular geometry as a flat mirror. Distinguishing behavior: extremely high, very narrow-band R (e.g. >99.9% only within +-tens of nm of the design line) and a hard LIDT (J/cm2 pulsed, W/cm above which it damages). At its line, near-lossless; off-line it leaks/transmits strongly (useful as a pickoff). Polarization: as a dielectric stack, s and p differ at 45deg with a defined phase shift; line mirrors are often specified for a given polarization (s-pol HR).
- **Key params:** center wavelength lambda0 (=design line), AOI (0 or 45deg), peak R (>0.999), bandwidth (FWHM of the HR band), LIDT (W/cm2 CW, J/cm2 pulsed), polarization (s/p/unpol design).
- **Add-on mapping:** Maps to MIRROR with coating='DIELECTRIC' + a narrow band. Same machinery as the flat dielectric mirror but with a tight coating_band_lo/hi around design_wl. NEW PARAM lidt_w_cm2 / lidt_j_cm2 would let a power-budget pass flag 'mirror damage' when incident irradiance exceeds it (optional; cosmetic to the chief-ray trace, real for the C8 budget). reflectivity float carries the >0.999 peak.
- **Real examples:** Thorlabs NB1-K08 (1064 nm, 0deg, R>99.9%, LIDT 1 J/cm2 @10ns); BB1-E02 (used as 532/633 turning); high-power Y2 series; Layertec 45deg laser-line HRs. Edmund TECHSPEC laser-line mirrors (355/532/1064). Typ Ø1", 6 mm fused silica.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=139 ; https://www.rp-photonics.com/laser_mirrors.html

#### Protected / enhanced aluminum metallic mirror (PF10-03-G01 protected Al, F01 UV-enhanced Al)
- **What it is:** An aluminum metal film (~few-hundred nm) on glass, capped with a thin protective dielectric (SiO2 for 'protected', a tuned multilayer for 'enhanced'/'UV-enhanced'). The cheapest, most broadband workhorse mirror. UV-enhanced (F01) pushes the band into the UV; protected (G01) is the broad vis-IR standard.
- **Optical behavior:** Specular reflection. Power: broadband but lower R than dielectric — protected Al Ravg>90% from 450 nm to 2 um, >95% from 2-20 um; bare/UV-enhanced Al works 250 nm up but with the characteristic ~800-900 nm dip in Al. Metal Fresnel: R(theta) computed from complex index n+ik, so s and p diverge and rotate azimuth at non-normal AOI (the add-on already does this). Polarization on reflection: introduces a real s-p amplitude AND phase difference (metal is lossy) -> linear in can come out slightly elliptical at 45deg. No focal power (flat). The 'look': mirror-metallic, slightly warm-gray, fully opaque (you see no substrate behind it).
- **Key params:** metal = Al, complex index n+ik(lambda), protective/enhancement layer (sets UV cutoff and the dip), spectral range (250nm-20um), Ravg per band.
- **Add-on mapping:** ALREADY MAPS: MIRROR coating='AL' -> physics.METALS['AL']=complex(1.37,7.62) -> fresnel_reflect -> reflect_field. NEW: METALS is single-wavelength; needs n,k AS A FUNCTION OF lambda (a small tabulated dispersion, e.g. from refractiveindex.info Rakic/McPeak) so the 800-900nm Al dip and UV behavior appear; and a NEW coating enum value 'AL_UV' (F01, UV-enhanced) vs 'AL' (G01, protected) since they differ below 450 nm. Optionally split 'AL_PROT' vs 'AL_BARE'.
- **Real examples:** Thorlabs PF10-03-G01 (Ø1" protected Al, 450nm-20um, Ravg>90% vis / >95% IR, 6mm); PF10-03-F01 (UV-enhanced Al, 250-450nm); CM254-050-G01 (concave Al). Edmund protected-Al #43-401. Newport 5101 series.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=PF10-03-G01 ; https://refractiveindex.info/?shelf=main&book=Al

#### Protected silver metallic mirror (PF10-03-P01)
- **What it is:** A silver film capped with a protective dielectric overcoat (bare silver tarnishes). Highest broadband reflectance in the visible-through-NIR of the common metals, the default 'best general-purpose' mirror.
- **Optical behavior:** Specular reflection. Power: Ravg>97.5% from 450 nm to 2 um, >96% from 2-20 um; sharp UV cutoff — silver reflectance collapses below ~400 nm (a plasma/absorption edge near 320 nm), so it is NOT usable in the UV. Metal Fresnel via Ag complex index. Polarization on reflection: small s-p phase shift at 45deg (Ag is a near-ideal metal in the visible, so phase distortion is modest but nonzero). No focal power. The 'look': bright neutral mirror, opaque, the most 'pure white' metallic of the three.
- **Key params:** metal = Ag, complex index n+ik(lambda) with the <400nm cutoff, spectral range 450nm-20um, Ravg>97.5%.
- **Add-on mapping:** ALREADY MAPS: coating='AG' -> METALS['AG']=complex(0.14,3.98). NEW: same dispersion-table upgrade so the UV cutoff below 400 nm actually appears (today the fixed n,k would over-reflect in the UV). No new enum needed.
- **Real examples:** Thorlabs PF10-03-P01 (Ø1" protected Ag, 450nm-2um Ravg>97.5%, 6mm, lambda/10); PF10-03-P01P (back-side polished, 450nm-20um); CM254-050-P01 (concave Ag, f=50mm); MPD149-P01 (OAP, Ag). Edmund protected-Ag #68-322.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=PF10-03-P01 ; https://refractiveindex.info/?shelf=main&book=Ag

#### Protected / unprotected gold metallic mirror (PF10-03-M01 protected Au, M03 unprotected Au)
- **What it is:** A gold film, optionally with a protective overcoat (M01) or bare (M03, higher R but delicate). The IR mirror of choice — gold's reflectance climbs to >98% in the NIR/MIR and stays flat to 20 um.
- **Optical behavior:** Specular reflection. Power: Ravg>96% (protected) / >97% (unprotected) from 800 nm to 20 um; in the visible gold reflectance drops sharply below ~600 nm (the reason gold looks yellow — it absorbs blue), so it is poor for blue/green. Metal Fresnel via Au complex index. Polarization: s-p phase shift at 45deg, slightly larger than Ag. No focal power. The 'look': unmistakable warm yellow-gold metallic, opaque.
- **Key params:** metal = Au, complex index n+ik(lambda) with the visible (blue) absorption edge, spectral range 800nm-20um (protected) / 700nm-20um (unprotected), Ravg>96-97%.
- **Add-on mapping:** ALREADY MAPS: coating='AU' -> METALS['AU']=complex(0.16,3.80). NEW: dispersion table so the visible blue-green dropoff is correct (fixed n,k over-reflects in the blue); optionally a 'AU_BARE' enum (unprotected, M03) vs 'AU' (protected, M01) since unprotected is ~1% higher and softer. The yellow render tint already follows from the coating enum.
- **Real examples:** Thorlabs PF10-03-M01 (Ø1" protected Au, 800nm-20um, Ravg>96%, 6mm); PF10-03-M03 (unprotected Au, >97% 800nm-20um); MPD149-M01 (OAP, gold, RFL 4"); concave gold CM254-xxx-M01. Edmund protected-gold #46-016.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=PF10-03-M01 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=744

#### Concave spherical mirror (focusing, CM254-050-P01)
- **What it is:** A flat-mirror coating (any of the above) on a concave spherical substrate. Reflects AND focuses — a 'positive element in reflection'. Used to focus or collimate without chromatic aberration (no glass to disperse).
- **Optical behavior:** Specular reflection PLUS converging focal power: f = R/2 (paraxial), R = radius of curvature. ABCD ray-transfer in reflection: a concave mirror has the same focal power as a positive lens of focal length f=R/2. Collimated in -> focuses to the focal point at f; point source at f -> collimated out. Achromatic (f independent of lambda). At finite AOI it shows astigmatism + coma (the off-axis penalty of using a sphere as a fold-and-focus). Polarization/power exactly as its coating. The 'look': a metallic or dielectric face with a visibly dished (concave) surface.
- **Key params:** radius of curvature R (or focal length f=R/2, signed +), clear aperture / diameter, AOI (0 for retro-focus, larger for fold-focus -> astigmatism), coating (sets R-vs-lambda).
- **Add-on mapping:** Maps to MIRROR + REUSE the existing ABCD focal machinery (today only LENS carries focal_length; the tracer's _focal/ABCD path at lines ~179-193 keys on element_type=='LENS'). NEW PARAM mirror_roc_mm (radius of curvature) OR repurpose the existing focal_length on MIRROR with f=R/2, and a NEW tracer rule: when element_type=='MIRROR' and focal_length!=0, apply focal power to the Gaussian q on reflection (sign: concave = converging = positive). clear_aperture already exists. This is the single biggest NEW capability — curvature on mirrors.
- **Real examples:** Thorlabs CM254-050-P01 (Ø1" concave, f=50mm, R=100mm, protected Ag); CM254-025-F01 (f=25mm, UV-Al); CM508-100-P01 (Ø2", f=100mm). Edmund TECHSPEC concave #32-816. Available in P01/G01/F01/M01 coatings.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=CM254-050-P01 ; https://phys.libretexts.org/Bookshelves/University_Physics/University_Physics_(OpenStax)/University_Physics_III_-_Optics_and_Modern_Physics_(OpenStax)/02:_Geometric_Optics_and_Image_Formation/2.03:_Spherical_Mirrors

#### Convex spherical mirror (diverging)
- **What it is:** Flat-mirror coating on a convex spherical substrate. Reflects AND diverges — a 'negative element in reflection'. Expands a beam or forms a virtual image; used as the secondary in Cassegrain-type relays and for beam expansion.
- **Optical behavior:** Specular reflection PLUS diverging focal power: f = -R/2 (negative). Collimated in -> appears to diverge from a virtual focus behind the mirror at |f|. ABCD: same as a negative lens of f=-R/2. Achromatic. Polarization/power per coating. The 'look': a metallic/dielectric face that bulges outward (convex).
- **Key params:** radius of curvature R, focal length f = -R/2 (signed, NEGATIVE), clear aperture, coating.
- **Add-on mapping:** Same as concave: MIRROR with the NEW mirror_roc_mm / signed focal_length, but f negative (diverging). The signed-focal-length convention the add-on already uses for LENS (signed focal_length) carries directly over — concave = +, convex = -. No additional new param beyond the curvature already needed for concave.
- **Real examples:** Thorlabs convex mirrors CM254-050-P01 series have concave; convex offered as e.g. CM254-xxx with negative f / Edmund convex TECHSPEC #43-465. Newport convex SCX series. Coatings P01/G01/M01. R typically 25-500 mm.
- **Refs:** https://www.edmundoptics.com/c/convex-mirrors/619/ ; https://phys.libretexts.org/.../02:_Geometric_Optics_and_Image_Formation/2.03:_Spherical_Mirrors

#### Off-axis parabolic (OAP) mirror (MPD149-P01)
- **What it is:** A section of a parent paraboloid, cut off-axis so the focal point sits OUTSIDE the incoming beam path (no central obscuration). Coated with any metal/dielectric. The gold-standard for diffraction-limited, achromatic focusing/collimation of broadband or ultrafast beams.
- **Optical behavior:** Reflects, folds the beam by the off-axis angle (commonly 90deg), AND focuses with ZERO on-axis spherical aberration (a parabola perfectly images its on-axis focus). Collimated in -> tight achromatic focus at the reflected focal length RFL; point at the focus -> collimated out. Defining length is the RFL (reflected focal length = distance from the off-axis segment to focus), distinct from the parent focal length PFL (RFL = PFL/cos^2(off-axis-angle/2) for 90deg geometry). Off-axis input or misalignment -> coma. Achromatic, no chromatic focal shift. Polarization/power per coating. The 'look': a tilted metallic dish whose focus is off to the side.
- **Key params:** reflected focal length RFL, off-axis angle (15/30/45/90deg), parent focal length PFL, clear aperture, coating. (RFL and the fold angle together define the geometry.)
- **Add-on mapping:** Maps to MIRROR + focal power, BUT needs TWO new things vs a plain curved mirror: (1) the off-axis geometry — the reflected chief ray is NOT the spherical reflect() of the surface normal; it is folded by a fixed off_axis_deg independent of where it hits, and the focus is laterally offset. NEW PARAMS off_axis_deg and rfl_mm (reflected focal length, used as the focal length f=RFL for the Gaussian q). (2) Mark it aberration-free on-axis (no spherical aberration) so a future aberration model does not add any. Geometrically the tracer can treat it as 'reflect + deviate by off_axis_deg + apply focal power RFL'.
- **Real examples:** Thorlabs MPD149-P01 (Ø1", 90deg OAP, protected Ag, RFL=4"=101.6mm); MPD149-M01 (gold); MPD129-P01 (RFL 2"); MPD249-P01 (Ø2"). Edmund TECHSPEC OAP #36-? series; Newport 50338AU. RFL 12.7-635 mm, off-axis 15-90deg.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=MPD149-P01 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=7003

#### D-shaped / half mirror (knife-edge pickoff, e.g. PFD10-03-P01, BBD1-E02)
- **What it is:** A flat mirror cut with one straight (chord) edge to a 'D' shape, mounted on a sharp edge. Geometrically a flat mirror; the special feature is the clean knife edge used to pick off HALF a beam (or steer one of two adjacent beams) while letting the other half pass the edge untouched.
- **Optical behavior:** Specular flat reflection over the D area; the straight edge acts as a hard aperture / beam-stop boundary — rays on one side reflect, rays past the edge pass by. No focal power. Used to combine/separate two parallel beams or to inject/extract a beam near a focus. Power/polarization per coating (usually a standard metal or dielectric). The 'look': a half-disc metallic/dielectric face with one straight edge.
- **Key params:** the chord position (how much of the aperture is reflective), edge orientation, coating, otherwise identical to a flat mirror.
- **Add-on mapping:** Maps to MIRROR (flat) with the geometry of an APERTURE/knife edge on one side. For the chief-ray tracer it behaves like MIRROR; for a half-clipping model it needs the NEW notion of a one-sided clip — reuse the existing _clip_T aperture logic but as a HALF-PLANE edge (NEW param edge_offset_mm + edge_axis) rather than a centered circular aperture. Cosmetically, render a D-cut mesh. No new optical physics beyond the half-plane clip.
- **Real examples:** Thorlabs PFD10-03-P01 (Ø1" D-shaped, protected Ag); BBD1-E02 (Ø1" D-shaped broadband dielectric, 400-750nm); PFD10-03-G01 (protected Al). Edmund D-shaped #47-? series. Knife-edge prism mirrors MRAK25-P01 are the prism cousin.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1126 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=BBD1-E02

#### Cold mirror (reflect visible, transmit IR — FM03)
- **What it is:** A dichroic dielectric mirror (on soda-lime/borosilicate) that REFLECTS the visible band and TRANSMITS the IR/NIR. The 'cold' name = the reflected beam is the visible (cool) light; heat (IR) passes through and away. Used in projectors and illuminators to send visible to the sample while dumping lamp heat.
- **Optical behavior:** Acts as a 45deg fold mirror for visible (reflect >90% across ~400-700 nm) and a window for IR (transmit >80% for ~700-1100+ nm). Effectively a DICHROIC operated in the 'reflect short / transmit long' sense at 45deg AOI. The cut sits at the vis/NIR boundary (~700 nm). Polarization: dielectric-stack s-p split at 45deg. The 'look': a tinted glass plate that mirrors visible but you can see IR-illuminated things through it.
- **Key params:** cut wavelength (~700 nm), reflect band = visible (400-700nm), transmit band = IR, AOI (45deg), R/T levels (>90% / >80%).
- **Add-on mapping:** Maps to DICHROIC with pass_type='LP' (transmit longpass = IR passes, visible reflects), cut_nm ~700. This is EXACTLY the existing DICHROIC branch (transmit if wl>=cut_nm for LP, else reflect) — already implemented. NEW: only a label/preset 'COLD_MIRROR' so it reads as a fold mirror in the UI/library, plus optionally band-limited reflectance (visible R rolls off in the deep blue/UV). No new tracer physics.
- **Real examples:** Thorlabs FM03 / FM03R (Ø1" or 25x36mm visible cold mirror, AOI 45deg, Rvis>90%, Tir>85%, soda-lime); Edmund cold mirror #43-958; Omega Optical cold mirrors. Reflect 420-630nm, transmit 700-1100nm typical.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=897 ; https://en.wikipedia.org/wiki/Cold_mirror

#### Hot mirror (reflect IR, transmit visible — FM02)
- **What it is:** The complement of a cold mirror: a dichroic dielectric that TRANSMITS the visible and REFLECTS the IR/NIR. The 'hot' name = it reflects the heat (IR) away. Used as a heat filter to protect cameras/sensors and to fold IR back into a source.
- **Optical behavior:** Acts as a window for visible (transmit, ~80%) and a 45deg fold mirror for IR (reflect >90% across ~750-1200 nm). A DICHROIC operated 'reflect long / transmit short' at 45deg. Cut ~700 nm. Polarization: dielectric s-p split at 45deg. The 'look': a glass plate you can see through in visible but which mirrors IR.
- **Key params:** cut wavelength (~700 nm), transmit band = visible, reflect band = IR (750-1200nm), AOI (0 or 45deg), R/T levels.
- **Add-on mapping:** Maps to DICHROIC with pass_type='SP' (transmit shortpass = visible passes, IR reflects), cut_nm ~700. Again EXACTLY the existing DICHROIC branch (transmit if wl<=cut_nm for SP, else reflect) — already implemented. NEW: only a preset/label 'HOT_MIRROR'. No new tracer physics.
- **Real examples:** Thorlabs FM02 (Ø1" red hot mirror, AOI 45deg, reflects IR ~750-1200nm, transmits visible, 1mm soda-lime); Edmund hot mirror #43-955; Schott/Omega heat-control filters. Reflect 750-1200nm, transmit 425-675nm typical.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=FM02 ; https://en.wikipedia.org/wiki/Hot_mirror

#### Deformable mirror (DM) — already in add-on
- **What it is:** A flat (or curved) mirror whose reflective membrane/facesheet is pushed by an actuator array to impose a programmable surface shape, correcting wavefront aberrations in adaptive optics. Coating is usually protected silver/gold/aluminum.
- **Optical behavior:** Specular reflection PLUS a commanded wavefront ADD (or subtract): the reflected wavefront picks up 2x the surface deformation (double-pass). Modeled modally as a sum of Zernike coefficients subtracted from the incident aberration. Power/polarization per its (metal) coating. Achromatic. The 'look': a mirror with an actuator grid behind it.
- **Key params:** Zernike command vector (per-mode stroke), number of actuators, stroke (um), coating, aperture.
- **Add-on mapping:** ALREADY MAPS: DEFORMABLE_MIRROR with dm_command = 15 Zernike coeffs, reflectivity, and the tracer subtracts the commanded modes. NEW (optional): give it the same coating enum as MIRROR so its R-vs-lambda is metal-accurate (today it uses scalar reflectivity), and the same curvature option if a curved-DM is wanted. Core behavior is done.
- **Real examples:** Thorlabs DMP40 (40-actuator piezo, protected silver/gold, 15 Zernike modes); Boston Micromachines Multi-DM (140 actuators); ALPAO DM69. Aperture 10-25mm, stroke ~1-30um.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3258

---

## Beamsplitters & Dichroics

> **Tracer / behavior model:** CURRENT STATE (optical_alignment_sim/tracer.py L385-429, physics.pbs_split L313): BEAMSPLITTER is an infinitely-thin ideal surface. Non-PBS does a lossless unitary amplitude split (reflected gets pi/2 phase via reflect_field, R+T=1, no ghost, no lateral offset). PBS reflects s (rs=i) and transmits p in the TRUE plane of incidence -- correct topology but a PERFECT split with no leakage/extinction. DICHROIC (L374-384) is a HARD STEP at cut_nm: transmit one side of the edge, reflect the other with the ideal-mirror convention (rp=-rs). Params today: split_ratio (reflect fraction 0..1), is_pbs bool, pass_type LP/SP, cut_nm.

HOW TO MODEL THE WHOLE CATEGORY ACCURATELY -- additive, behavior-preserving:

1. bs_form enum {CUBE (default), PLATE, PELLICLE, KNIFE_EDGE} on BEAMSPLITTER. CUBE = today's behavior exactly (collinear transmit, 90 deg reflect, single buried surface, no ghost) -> zero-regression default. PLATE adds: (a) transmitted-port LATERAL OFFSET from Snell refraction through thickness t at 45 deg, (b) a weak GHOST child ray off the AR back surface, angularly separated by ~2x wedge, power ~ghost_frac*R, (c) optional small Rs!=Rp split tolerance. PELLICLE = PLATE with thickness->0 and ghost suppressed (offset and ghost both OFF). KNIFE_EDGE = spatial split (see #5).

2. NEW plate/ghost params: plate_thickness_mm, wedge_arcmin, ghost_enable bool, ghost_frac (~0.005-0.02). Gate all of them so they only act when bs_form=='PLATE' (or PBS plate). The transmitted lateral offset is a real GEOMETRY change (new child origin), the ghost is a new low-power REFLECT child -- both are new emissions the stack loop must push.

3. PBS realism: today pbs_split is a perfect s/p separation. Add pbs_extinction_t (default 1000) and pbs_extinction_r (default ~30, intentionally ~30x worse -- the asymmetry is physically real: Tp:Ts>1000:1 transmitted vs only 20-100:1 reflected). Leak a small wrong-polarization fraction into each port instead of an ideal split. Keep the existing true-plane-of-incidence s/p convention (platform-robust) -- just attenuate the cross-pol leakage rather than zeroing it.

4. DICHROIC realism: replace the hard wl>=cut_nm step with a SOFT edge. Add edge_width_nm: near the edge emit BOTH children with complementary fractions following a sigmoid/smoothstep in (wl-cut_nm)/edge_width_nm; far from the edge collapse to today's clean transmit/reflect (zero-regression in the asymptote). Add an AOI-dependent cut-shift coefficient (cut_nm blue-shifts as AOI rises above 45 deg) so off-45 folds move the edge -- matters because the add-on lets users orient the dichroic freely. Optionally band limits so deep out-of-band light isn't cleanly routed either way.

5. KNIFE-EDGE / D-MIRROR is genuinely NEW dispatch, not a parameter tweak. It is a SPATIAL/aperture split: test each ray's hit position against an edge line in the element's clear aperture (reuse the APERTURE/PINHOLE clipping machinery + matrix_world local coords). Reflective side -> REFLECT with MIRROR physics (reflect_field, reflectivity ~1, wavelength- and polarization-independent); open side -> TRANSMIT straight at full power. Implement as element_type='KNIFE_EDGE' (cleanest) or bs_form='KNIFE_EDGE' on a mirror-like splitter, with an edge_offset param locating the edge in the aperture plane and a side flag. No amplitude coatings, no s/p, no wavelength term.

6. ENERGY/loss: existing non-PBS split is exactly unitary (R+T=1). Real splitters lose a few % (absorption/scatter) and plates put a few % into the ghost. An optional loss_frac (so R+T+ghost+loss=1) makes power-budget renders honest without breaking the lossless default (loss_frac=0).

PRIORITY for the tracer: (i) bs_form CUBE/PLATE/PELLICLE with plate lateral-offset + ghost is the highest-value visible add (ghost beams and lateral walk-off are exactly what alignment users chase). (ii) DICHROIC soft edge + AOI shift. (iii) PBS asymmetric extinction. (iv) KNIFE_EDGE new dispatch. All are strictly additive: every default (bs_form=CUBE, edge_width_nm=0, extinction ideal, loss=0) reproduces the current byte-level behavior, so existing CI traces stay green.

#### Non-polarizing PLATE beamsplitter (wedged)
- **What it is:** A single coated glass/UVFS plate (t ~1-8 mm) held at 45 deg AOI. The first surface carries a partially-reflecting dielectric/metallic coating; the second surface is AR-coated and ground with a small wedge (Thorlabs: 30 arcmin) so the residual back-surface reflection (the 'ghost') diverges away from the main reflected beam instead of overlapping it. Splits one input into a reflected + transmitted port by amplitude, nominally polarization-independent.
- **Optical behavior:** Amplitude split into REFLECT (fraction R) + TRANSMIT (fraction T=1-R) at the FIRST surface. The 45 deg reflected beam exits at 90 deg to the input; the transmitted beam continues straight but is LATERALLY SHIFTED by the plate thickness (n,t) and slightly dispersed (chromatic walk-off) because it traverses bulk glass at 45 deg. Real R:T has residual polarization dependence (Rs != Rp at 45 deg; e.g. nominal 50:50 can be ~45:55 for s vs ~55:45 for p). A weak GHOST beam (a few % of R) emerges from the AR back surface, angularly offset by ~2x the wedge.
- **Key params:** split_ratio R (0.5,0.7,0.9,0.3,0.1 -> 50/50,70/30,90/10,30/70,10/90 as R:T), plate thickness t, wedge angle, coating wavelength band, substrate index n (sets transmitted lateral offset + ghost angle).
- **Add-on mapping:** element_type=BEAMSPLITTER, is_pbs=False, split_ratio=R. NEW params needed: bs_form='PLATE'; plate_thickness_mm (drives transmitted-port lateral offset + ghost geometry); wedge_arcmin (ghost angular separation); ghost_enable bool + ghost_frac (~back-surface residual reflectance, ~0.005-0.02) to emit a weak GHOST child ray; optional Rs/Rp polarization-split tolerance for non-ideal NPBS. Tracer currently treats the splitter as an infinitely-thin ideal surface with a single split_ratio and no ghost/offset -- all three (lateral offset, ghost, s/p tolerance) are new behaviors for the plate form.
- **Real examples:** Thorlabs BSW series 50:50 UVFS plates; BSN11 (1in, 10:90 R:T, 700-1100nm, t=5mm), BSS11 (1in, 30:70 R:T, t=5mm), BST series 70:30, BSN10R (25x36mm 10:90, t=1mm), BST18 (2in 70:30, 1.2-1.6um, t=8mm). UVFS broadband coatings 250-450nm / 400-700 / 700-1100 / 1100-1600nm; 30 arcmin back-surface wedge; AR <1% avg.
- **Refs:** https://www.thorlabs.com/beamsplitter-guide ; https://www.thorlabs.com/thorproduct.cfm?partnumber=BSN11 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=BSS11 ; https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=4806

#### Non-polarizing CUBE beamsplitter (cemented)
- **What it is:** Two right-angle prisms cemented at their hypotenuses with a thin partially-reflecting dielectric film at the diagonal interface, forming a glass cube with AR-coated faces. Mechanically robust; the most common lab 50:50.
- **Optical behavior:** Amplitude split R:T at the single internal diagonal. Reflected port exits at 90 deg, transmitted port continues collinear (NO lateral offset and NO real ghost -- the single buried reflecting surface and index-matched cement eliminate the secondary ghost that plates/pellicles fight). Polarization dependence is small but nonzero for 'non-polarizing' coatings. Adds bulk glass path (affects OPL/dispersion in interferometers) but does not displace the transmitted beam.
- **Key params:** split_ratio R (10/90, 30/70, 50/50, 70/30, 90/10), cube edge length, coating band, substrate (N-BK7/UVFS).
- **Add-on mapping:** element_type=BEAMSPLITTER, is_pbs=False, split_ratio=R. NEW param: bs_form='CUBE' (default form). Behaviorally the closest to what the tracer ALREADY does -- collinear transmit, 90 deg reflect, single surface, no ghost -- so bs_form='CUBE' is the no-op/default that needs no new physics. The new params (plate_thickness, wedge, ghost) simply stay disabled for CUBE. Only cube edge length feeds the realistic mesh, not the trace.
- **Real examples:** Thorlabs BS013 (50:50, 1in, 400-700nm), BS038 (10:90 R:T, 10mm, 700-1100nm), BS074 (90:10 R:T, 0.5in, 700-1100nm); CM1-BS013 cage-cube mounted; 5/10/12.7/20/25.4mm sizes; coatings 400-700 / 700-1100 / 1100-1600nm.
- **Refs:** https://www.thorlabs.com/non-polarizing-cube-beamsplitters-400---700-nm ; https://www.3doptix.com/catalog/optics/beam-splitter/thorlabs/BS074 ; https://www.thorlabs.com/beamsplitter-guide

#### PELLICLE beamsplitter
- **What it is:** A nitrocellulose membrane only a few microns thick (~2-5 um) stretched under tension in a metal ring/housing, held at 45 deg. Because the membrane is far thinner than typical coherence-relevant scales for ghost separation, the two surface reflections superimpose.
- **Optical behavior:** Amplitude split R:T like a plate but with essentially ZERO ghost (second-surface reflection overlaps the first) and ZERO chromatic/lateral walk-off in transmission (negligible glass path -> no beam displacement, minimal dispersion). Trade-off: extremely fragile, vibration-sensitive, and the thin film can show weak interference ripple vs wavelength/AOI. Ideal where the transmitted wavefront and beam position must be preserved (autocollimators, broadband 300nm-5um).
- **Key params:** split_ratio R (typ 45:55, 50:50, 33:67, 8:92 depending on model), membrane thickness (~few um), coating/uncoated band.
- **Add-on mapping:** element_type=BEAMSPLITTER, is_pbs=False, split_ratio=R. NEW param: bs_form='PELLICLE'. Distinct behavior the tracer should encode: SUPPRESS the ghost child entirely AND skip the transmitted-port lateral offset (set effective thickness ~0). So bs_form gates the plate's offset/ghost code path OFF. Mesh: a thin tensioned membrane in a ring rather than a slab/cube.
- **Real examples:** Thorlabs BP series pellicles: BP108, BP150, BP145B series; sizes 0.5in/1in/2in; coverage 300nm-5um (multiple coatings, e.g. 45:55 visible, 8:92, 33:67). Edmund Optics pellicle beamsplitters. Membrane ~2um nitrocellulose.
- **Refs:** https://www.thorlabs.com/pellicle-beamsplitters ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=898&pn=BP108 ; https://www.edmundoptics.com/f/pellicle-beamsplitters/12443/

#### POLARIZING beamsplitter CUBE (PBS / MacNeille)
- **What it is:** Two prisms cemented with a multilayer dielectric (MacNeille) coating at the diagonal, designed so each internal interface sits at Brewster's condition for p: p is transmitted, s is reflected. Most common polarization-separation element.
- **Optical behavior:** Splits by POLARIZATION, not amplitude: TRANSMIT = p-polarization (along the true plane of incidence), REFLECT = s-polarization (perpendicular), at 90 deg. Strongly asymmetric purity: transmitted p is very clean (Tp:Ts > 1000:1, up to >2000:1 for laser-line PBS), but reflected s is only ~20:1 to 100:1 pure (leaks some p). Narrower/coating-limited wavelength band; outside band the extinction collapses. For incoming arbitrary polarization, output port powers follow Malus-like projection onto s and p axes set by the cube's physical orientation.
- **Key params:** is_pbs (s-reflect/p-transmit), transmitted extinction Tp:Ts (>1000:1), reflected extinction (~20-100:1), coating band, glass (N-SF1/H-ZF3).
- **Add-on mapping:** element_type=BEAMSPLITTER, is_pbs=True. Already implemented: physics.pbs_split() reflects s (rs=i), transmits p in the true plane of incidence -- correct topology. NEW params to add realism: pbs_extinction_t (default 1000) and pbs_extinction_r (default ~30) so the model leaks a small wrong-polarization fraction into each port instead of an ideal 100% split (today's pbs_split is a perfect s/p separation with NO leakage). bs_form='CUBE'. Reuse the existing 'extinction' float concept but as a SEPARATE pair (transmit vs reflect differ by ~30x in reality).
- **Real examples:** Thorlabs PBS101/PBS121/PBS201/PBS251/PBS252 broadband cubes (420-680, 620-1000, 700-1300, 900-1300, 1200-1600nm); PBS519 (2in 420-680nm); CCM1-PBS25x cage-cube mounted; high-power laser-line PBS25x-xxxHP (Tp:Ts>2000:1). Sizes 5/10/12.7/20/25.4/50.8mm. N-SF1 or H-ZF3.
- **Refs:** https://www.thorlabs.com/broadband-polarizing-beamsplitter-cubes ; https://www.thorlabs.com/high-power-laser-line-polarizing-beamsplitter-cubes ; https://www.rp-photonics.com/thin_film_polarizers.html

#### POLARIZING beamsplitter PLATE (thin-film, 45 deg)
- **What it is:** A single coated plate used at 45 deg AOI (Thorlabs design) -- a plate-form PBS that transmits p and reflects s, but is mounted at a normal 45 deg fold instead of at the steeper Brewster angle of a classic thin-film-polarizer plate. Easier to mount than Brewster-angle plate polarizers.
- **Optical behavior:** Same polarization topology as the PBS cube (transmit p, reflect s) but with the plate's geometric side effects: transmitted p-beam is laterally OFFSET by the glass thickness and the reflected s exits at 90 deg. Higher laser-damage-threshold path option (no cement). Can also carry a weak ghost like any plate. Brewster-angle variants (thin-film polarizers/Brewster plates) achieve near-zero p reflection loss at the specific Brewster AOI rather than 45 deg.
- **Key params:** is_pbs, AOI (45 deg vs Brewster ~56 deg), split p/s extinction, plate thickness, coating band.
- **Add-on mapping:** element_type=BEAMSPLITTER, is_pbs=True, bs_form='PLATE'. Combines the PBS branch (s/p split) WITH the new plate behaviors (transmitted lateral offset + optional ghost). NEW param overlap: reuse plate_thickness_mm + wedge_arcmin from the plate form, plus pbs_extinction_t/_r. Optionally a Brewster flag/AOI param if you want to model true Brewster-plate polarizers (currently the geometry assumes a 45 deg fold).
- **Real examples:** Thorlabs Polarizing Plate Beamsplitters (ObjectGroup 6004, 45 deg AOI design); classic thin-film-polarizer / Brewster-plate polarizers (e.g. high-power Nd:YAG TFPs at ~56 deg); birefringent crystal polarizers (Glan-Taylor) are the higher-extinction cousins.
- **Refs:** https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=6004 ; https://www.thorlabs.com/navigation.cfm?guide_id=2318 ; https://www.rp-photonics.com/thin_film_polarizers.html

#### Variable / fixed SPLIT RATIO families (10/90, 30/70, 50/50, 70/30, 90/10)
- **What it is:** Not a distinct hardware class but the catalog axis cutting across plate and cube non-polarizing splitters: the coating is tuned to a target reflected:transmitted intensity ratio. Quoted as R:T.
- **Optical behavior:** Pure amplitude weighting of the two output ports. 90/10 'pick-off' / 'sampler' taps a small reflected fraction for monitoring while passing most power; 50/50 balances (interferometers); 70/30 / 30/70 bias one arm. Ideal versions are lossless (R+T=1); real ones lose a few % to absorption/scatter and show small s/p imbalance.
- **Key params:** split_ratio = reflected fraction R in {0.1,0.3,0.5,0.7,0.9}; absorption loss; s/p tolerance.
- **Add-on mapping:** element_type=BEAMSPLITTER, split_ratio=R -- ALREADY fully supported by the existing split_ratio float (named 'Reflect fraction', 0..1). No new param strictly required for the ratio itself. OPTIONAL: a small loss_frac (so R+T<1) and an Rs/Rp split tolerance to make non-ideal NPBS realistic; today the split is exactly unitary (R+T=1).
- **Real examples:** Same BSN(10:90)/BSS(30:70)/BST(70:30)/BSW(50:50) plate series and BS0xx cube series above; 'pickoff' 90:10 plates used as power monitors / beam samplers (Thorlabs BSF/beam-sampler family).
- **Refs:** https://www.thorlabs.com/non-polarizing-cube-beamsplitters-400---700-nm ; https://www.thorlabs.com/thorproduct.cfm?partnumber=BSN11

#### DICHROIC mirror -- LONGPASS (LP)
- **What it is:** A multilayer thin-film edge filter on a substrate at 45 deg that splits the spectrum at a cut-on wavelength: REFLECTS short wavelengths, TRANSMITS long wavelengths. The workhorse fluorescence-microscopy beamsplitter (reflects excitation laser, transmits longer-wavelength emission).
- **Optical behavior:** Wavelength-routing splitter: for wl >= cut-on -> TRANSMIT (continues straight); for wl < cut-on -> REFLECT at 90 deg. A real edge is not a hard step -- it has finite edge steepness / transition width (high-perf <5nm, RazorEdge ~0.5% of laser wl) and ripple in pass/stop bands. The cut-on BLUE-shifts as AOI increases (spec'd at 45 deg; using off-45 shifts the edge). Polychromatic/white-light input is physically separated into a transmitted long-pass beam and a reflected short-pass beam.
- **Key params:** pass_type='LP', cut_nm (cut-on), AOI (45 deg nominal), edge steepness/transition width, reflection-band + transmission-band limits.
- **Add-on mapping:** element_type=DICHROIC, pass_type='LP', cut_nm=cut-on. ALREADY implemented as a HARD STEP at cut_nm (transmit if wl>=cut_nm else reflect). NEW params to add realism: edge_width_nm (soft sigmoid edge instead of step -> partial T/R near the edge, both children emitted with complementary fractions); aoi_shift coefficient (cut_nm shifts with incidence angle); optional band limits so far-out-of-band wl is neither cleanly T nor R. The reflect path already uses the ideal-mirror s/p convention -- fine.
- **Real examples:** Thorlabs DMLP series 1in longpass dichroics: DMLP490, DMLP505, DMLP550, DMLP605, DMLP650(T 0.5in), DMLP805, DMLP950, DMLP1000 (number = cut-on nm); Semrock/IDEX BrightLine + RazorEdge dichroics; Chroma fluorescence dichroics. 45 deg AOI, transition typ a few nm to tens of nm.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=DMLP550 ; https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=3313 ; https://www.idex-hs.com/resources/intro-to-optical-filters/intro-to-edge-filters

#### DICHROIC mirror -- SHORTPASS (SP)
- **What it is:** The complementary edge filter: TRANSMITS short wavelengths, REFLECTS long wavelengths, split at a cutoff wavelength, at 45 deg. Used as harmonic separators and to fold IR out of a visible path (or vice versa).
- **Optical behavior:** For wl <= cutoff -> TRANSMIT straight; for wl > cutoff -> REFLECT at 90 deg. Same real-world caveats as LP: finite edge steepness, band ripple, AOI-dependent edge shift. Separates a beam into a transmitted short band + reflected long band.
- **Key params:** pass_type='SP', cut_nm (cutoff), AOI, edge steepness, band limits.
- **Add-on mapping:** element_type=DICHROIC, pass_type='SP', cut_nm=cutoff. ALREADY implemented (transmit if wl<=cut_nm else reflect). Same NEW params as LP: edge_width_nm + aoi_shift to replace the hard step with a realistic soft, angle-dependent edge.
- **Real examples:** Thorlabs DMSP series: DMSP505, DMSP605, DMSP900(/900T 0.5in), DMSP950T, DMSP1000L(2in), DMSP1800L(2in) (number = cutoff nm); harmonic separators (e.g. 532/1064nm) as a high-power SP/LP-mirror special case.
- **Refs:** https://www.thorlabs.com/shortpass-dichroic-mirrors-beamsplitters ; https://www.thorlabs.com/item/DMSP505 ; https://www.rp-photonics.com/dichroic_mirrors.html

#### KNIFE-EDGE / D-SHAPED mirror (geometric beam splitter/combiner)
- **What it is:** Not a coating splitter at all -- a fully reflective mirror with a sharp straight edge (knife-edge right-angle prism with reflective legs, or a D-cut flat mirror). It splits/combines beams by GEOMETRY: the half of the beam landing on the mirror is fully reflected, the other half passes by the edge unobstructed.
- **Optical behavior:** Spatial (aperture) split, wavelength- and polarization-INDEPENDENT and lossless per ray: a ray hitting the reflective side -> 100% REFLECT (90 deg fold); a ray clearing the edge -> passes through untouched. Used to make two beams collinear (combine) or to pick off half a beam, or split one beam aimed at the edge into two. Knife-edge prism puts a precise 90 deg corner between two coated legs for counter-propagating-beam recombination. Introduces diffraction at the sharp edge for the clipped portion.
- **Key params:** edge position/orientation in the aperture plane, reflective coating (metallic/dielectric, broadband), which half reflects.
- **Add-on mapping:** NO current element_type captures the spatial-edge behavior -- BEAMSPLITTER splits every ray amplitude-wise, MIRROR reflects the whole aperture. NEW: either element_type='KNIFE_EDGE'/'D_MIRROR' OR a bs_form='KNIFE_EDGE' variant of MIRROR with an edge_offset param defining the edge line in the clear aperture; rays on the reflective side -> REFLECT (reuse MIRROR's reflect_field, reflectivity~1), rays on the open side -> TRANSMIT straight (clipped, full power). This is a geometry/aperture test (like APERTURE/PINHOLE) gating MIRROR vs pass-through -- genuinely new dispatch logic, not just a parameter.
- **Real examples:** Thorlabs MRAK series knife-edge right-angle prism mirrors (MRAK25-E02 dielectric 400-750nm, MRAK25-G01 prot. aluminum 450nm-20um, MRAK25-P01 prot. silver, MRAK25-M01 prot. gold; 25x25mm legs, N-BK7); D-shaped pick-off mirrors (e.g. Thorlabs PFD/BBD D-mirrors).
- **Refs:** https://www.thorlabs.com/NewGroupPage9.cfm?ObjectGroup_ID=6760 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=MRAK25-E02 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=MRAK25-P01

---

## Waveplates & Polarizers

> **Tracer / behavior model:** Both families are pure Jones-matrix elements in the existing model and need NO new physics machinery for the single-output cases -- the tracer already dispatches WAVEPLATE -> physics.M_waveplate(ret, fast_axis_deg) and POLARIZER -> physics.M_polarizer(pol_axis_deg, extinction), with retardance already scaled chromatically by ret = retardance_deg*(design_wl/ray.wl) at tracer.py:434. So the entire waveplate family (HWP/QWP/FWP, zero/multi-order) is ALREADY representable by choosing retardance_deg in {90,180,360} + fast_axis_deg + design_wl. The model gaps the tracer must close are: (1) CHROMATICITY LAW -- the current ret ~ 1/lambda (1st-order) law is correct ONLY for a true zero-order plate; multi-order and achromatic/Fresnel-rhomb plates disperse very differently, so retardance(lambda) must become a per-variant function selected by a NEW `order` param (0=zero-order/achromatic flat-ish, N>=1 multi-order steep ~ (N+1/2)/lambda). For a true achromatic plate retardance should be held ~constant vs lambda; for a Fresnel rhomb it derives from TIR phase, not birefringence, so it is geometry-not-thickness based but still maps to a near-constant retardance. (2) The WAVEPLATE branch is guarded by `and J` (tracer.py:433) and only carries the 2-D Jones, NOT the 3-D evec field that the PBS/mirror paths now use -- a real tilted plate's fast axis is a lab-frame vector; for correctness on arbitrary orientations the retarder should eventually act on evec like pbs_split does, but for a normal-incidence chief-ray model the 2-D Jones is fine. (3) BEAM-SPLITTING POLARIZERS (Wollaston, Rochon, Senarmont, Nomarski) are the one genuinely new BEHAVIOR: a single element that emits TWO diverging beams with orthogonal linear polarization at a wavelength-dependent separation angle. The tracer has no element that both polarization-decomposes AND angularly deviates from one face; this must reuse the two-child stack-push pattern already used by BEAMSPLITTER/PBS (tracer.py:400-401 pushes SPLIT_R + SPLIT_T children) but with (a) both children TRANSMITTED (not one reflected), (b) each child's direction deviated by +/- (separation/2) about the wedge plane, (c) each child projected onto orthogonal linear Jones states |H> and |V> in the prism frame. Geometric deviation should be applied like a thin-prism/grating deflection in the local frame. Polarizing prisms that REJECT one polarization (Glan-Taylor/Glan-laser via TIR dump, Glan-Foucault) map to the existing single-output POLARIZER with high extinction; only the dual-output prisms need the new split. (4) EXTINCTION already leaks sqrt(1/extinction) of the orthogonal amplitude (physics.M_polarizer at physics.py:85-90) -- correct; just feed real numbers (dichroic sheet ~1e3-1e4, wire-grid ~1e2-1e3 vis to ~1e4 IR, Glan calcite ~1e5). (5) ACCEPTANCE ANGLE is a validity/aperture limit the chief-ray tracer can ignore for the on-axis beam but should store as metadata; if angular spread is ever modeled, narrow-acceptance prisms (Glan-Taylor ~7-10deg half) would vignette. (6) Circular polarizers are COMPOUND (linear polarizer + QWP at 45deg) -- representable today as two stacked elements, or as one element with a NEW composite flag; their Jones is M_qwp(45)*M_pol, and a true commercial circular polarizer is asymmetric (only circularizes one way) which the two-element stack already captures. NET: add `order` (int) and `polarizer_type`/`waveplate_type` enums to select the chromatic-dispersion law and the single-vs-dual-output behavior; the dual-output Wollaston/Rochon family is the only path needing new geometry+two-child emission, modeled on the existing PBS split.

#### Half-wave plate (HWP, lambda/2)
- **What it is:** Birefringent plate giving 180deg retardance between fast and slow axes at the design wavelength. Rotates linear polarization to 2*theta (theta = angle between input pol and fast axis); flips handedness of circular light.
- **Optical behavior:** Linear retarder, retardance=180deg. Jones = rotated diag(exp(-i*pi/2),exp(+i*pi/2)). Linear-in -> linear-out rotated by 2x the fast-axis offset; used to rotate polarization or as a variable rotator on a rotation mount. No power loss, no deviation.
- **Key params:** retardance=180deg, fast_axis_deg, design_wl, order (0 true/compound zero-order vs N multi-order)
- **Add-on mapping:** WAVEPLATE: retardance_deg=180, fast_axis_deg=<angle>, design_wl=<nm>. Maps 1:1 today. NEW param `order` only needed to pick the correct retardance(lambda) dispersion law away from design_wl.
- **Real examples:** Thorlabs WPH10E-633 (zero-order, mounted, Ø1in, 633nm, retardance accuracy <lambda/300); WPMH10M-532 (multi-order, 532nm); WPH05M-808 (Ø1/2in). Quartz/MgF2; clear aperture ~Ø10-22mm.
- **Refs:** https://www.thorlabs.com/choosing-a-wave-plate , https://www.edmundoptics.com/knowledge-center/application-notes/optics/understanding-waveplates/

#### Quarter-wave plate (QWP, lambda/4)
- **What it is:** Birefringent plate giving 90deg retardance. Converts linear at 45deg to fast axis into circular polarization and vice versa; converts circular to linear.
- **Optical behavior:** Linear retarder, retardance=90deg. Jones = rotated diag(exp(-i*pi/4),exp(+i*pi/4)). Linear@45deg -> circular; circular -> linear@+/-45deg. Core element for circular-polarization generation and optical isolators.
- **Key params:** retardance=90deg, fast_axis_deg, design_wl, order
- **Add-on mapping:** WAVEPLATE: retardance_deg=90, fast_axis_deg, design_wl. Maps 1:1 today. `order` selects dispersion law.
- **Real examples:** Thorlabs WPQ10E-633 (zero-order, 633nm); WPMQ10M-1064 (multi-order, 1064nm); WPQ05M-266 (UV). Quartz; Ø10mm CA typical.
- **Refs:** https://www.thorlabs.com/choosing-a-wave-plate , https://www.rp-photonics.com/waveplates.html

#### Full-wave plate (FWP, lambda, first-order)
- **What it is:** Plate giving 360deg (one full wave) retardance at design wavelength -- nominally NO net polarization change at lambda, but strongly wavelength-dependent, so used as a sensitive tint/color compensator and in microscopy (lambda-plate / red-I plate).
- **Optical behavior:** Linear retarder, retardance=360deg. At design_wl it is identity on polarization; off design_wl the residual retardance ~ 360*(design_wl/lambda) reveals birefringence/strain via interference colors. Behavior is identical machinery to HWP/QWP, just retardance=360.
- **Key params:** retardance=360deg, fast_axis_deg, design_wl
- **Add-on mapping:** WAVEPLATE: retardance_deg=360, fast_axis_deg, design_wl. Already representable. The existing chromatic scaling at tracer.py:434 already produces the off-design tint behavior.
- **Real examples:** Edmund / Meadowlark first-order full-wave (lambda) plates; microscopy 'Red I' 530/550nm full-wave compensator plates.
- **Refs:** https://www.edmundoptics.com/knowledge-center/application-notes/optics/understanding-waveplates/ , https://www.rp-photonics.com/waveplates.html

#### Zero-order waveplate (true vs compound)
- **What it is:** A waveplate whose NET retardance is exactly the fractional value (lambda/2 or lambda/4) with no extra full waves. True zero-order = one very thin plate; compound zero-order = two thick multi-order plates with crossed axes whose retardances subtract to the fractional value. Low temperature and wavelength sensitivity.
- **Optical behavior:** Same Jones as HWP/QWP but retardance is nearly FLAT vs wavelength near design (gentle ~1/lambda). This is exactly the dispersion the current tracer assumes (ret = retardance_deg*design_wl/lambda).
- **Key params:** retardance (90/180), fast_axis_deg, design_wl, order=0
- **Add-on mapping:** WAVEPLATE with order=0. The existing ret~1/lambda law IS the zero-order law, so the default tracer behavior is already a zero-order plate. No change needed except labeling order=0.
- **Real examples:** Thorlabs WPH10E-* / WPQ10E-* (compound zero-order quartz); Thorlabs polymer zero-order WPHSM05-* (true zero-order LCP film). Bandwidth tolerant ~+/-tens of nm.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=711 , https://www.rp-photonics.com/waveplates.html

#### Multi-order waveplate (high-order)
- **What it is:** Thick single plate whose optical path difference is (N + fraction) waves, N>=1. Cheaper and more robust mechanically, but retardance is HIGHLY sensitive to wavelength, angle, and temperature because the large N amplifies dispersion.
- **Optical behavior:** Same fractional Jones at design_wl, but retardance(lambda) varies STEEPLY: ret(lambda) = (N + f)*360*design_wl/lambda, so a small dlambda shifts net retardance a lot. The tracer must scale the FULL order count, not just the fractional part, to reproduce the rapid off-design walk-off.
- **Key params:** retardance (fractional), fast_axis_deg, design_wl, order=N (>=1)
- **Add-on mapping:** WAVEPLATE + NEW param `order=N`. Behavior change: tracer.py:434 must compute ret = (order*360 + retardance_deg)*(design_wl/ray.wl) so the steep multi-order dispersion appears, then take effective Jones from the net mod 360.
- **Real examples:** Thorlabs WPMH10M-* (multi-order half-wave), WPMQ10M-* (multi-order quarter-wave). Often N~2-10 at the design line. Quartz.
- **Refs:** https://www.thorlabs.com/choosing-a-wave-plate , https://www.rp-photonics.com/waveplates.html

#### Achromatic waveplate
- **What it is:** Compound plate of two different birefringent materials (e.g. quartz + MgF2) whose dispersions cancel, giving near-constant retardance (lambda/2 or lambda/4) over a broad band (e.g. 400-800nm, 690-1200nm).
- **Optical behavior:** Linear retarder with retardance APPROXIMATELY CONSTANT vs wavelength across its spec band -- the opposite of the current 1/lambda assumption. Jones same form; the dispersion law must be flattened.
- **Key params:** retardance (90/180), fast_axis_deg, design band (lo-hi nm), waveplate_type=ACHROMATIC
- **Add-on mapping:** WAVEPLATE + NEW `waveplate_type=ACHROMATIC` (or order=0 + a 'flat' flag). Behavior change: tracer should HOLD ret = retardance_deg constant over the band instead of scaling by design_wl/lambda. Reuses existing M_waveplate.
- **Real examples:** Thorlabs AHWP05M-600 (achromatic HWP 400-800nm), AQWP05M-600 (achromatic QWP), AQWP05M-1600 (690-1200nm), super-achromatic SAHWP05M-700 (310-1100nm). Ø1/2in CA.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=854 , https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=2193

#### Fresnel rhomb retarder
- **What it is:** A glass parallelepiped (N-BK7) that produces retardance from the s/p PHASE SHIFT at two total internal reflections, NOT from birefringence. Two ~54deg TIR bounces give ~45deg each -> lambda/4 (or a double rhomb -> lambda/2). Quasi-achromatic.
- **Optical behavior:** Acts as a broadband QWP or HWP: retardance nearly flat over 400-1550nm (typ 2% variation). The beam is laterally displaced (it exits parallel but offset) because of the internal zig-zag. Jones is the standard retarder Jones; the NEW behavior vs a plate is the lateral beam offset + near-flat dispersion + no thickness/birefringence parameter.
- **Key params:** retardance (90/180), fast_axis_deg, broadband range, lateral_offset (mm), waveplate_type=FRESNEL_RHOMB
- **Add-on mapping:** WAVEPLATE + NEW `waveplate_type=FRESNEL_RHOMB`: use flat (achromatic) retardance law AND optionally apply a lateral beam displacement child (the chief ray exits offset, not deviated). If lateral offset is ignored it degenerates to an achromatic waveplate; offset needs new geometry like a parallel-plate shift.
- **Real examples:** Thorlabs FR600QM (quarter-wave, 600-1550nm, N-BK7), FR600HM (half-wave), T-FR600QM mounted. Retardance variation ~2% typ over band.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=154 , https://en.wikipedia.org/wiki/Fresnel_rhomb

#### Dichroic film / sheet polarizer (Polaroid)
- **What it is:** Absorptive stretched-polymer film with aligned dichroic molecules (iodine/dye) or nanoparticles; absorbs the field component along the molecular chains, transmits the orthogonal. Cheap, large-area, wide acceptance angle.
- **Optical behavior:** Ideal linear polarizer with MODERATE extinction (~1e3 to 1e4 for nanoparticle 'ColorPol'/sheet; ~1e2-1e3 for economy film). Transmits ~38-45% of unpolarized input. Wide acceptance angle (works in diverging beams). Absorptive (rejected light is dumped as heat, not a second beam).
- **Key params:** pol_axis_deg, extinction (~1e3-1e4), wavelength band
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction=1000..10000. Maps 1:1 to existing M_polarizer (physics.py:85). No new params.
- **Real examples:** Thorlabs LPVISE100-A (film, 400-700nm, ext ~1e3-1e4, Ø1in), LPNIRE100-B (NIR film); Thorlabs/Codixx ColorPol nanoparticle (ext up to 1e5). Polaroid HN-series sheet.
- **Refs:** https://www.thorlabs.us/newgrouppage9.cfm?objectgroup_id=4984 , https://www.fiberoptics4sale.com/blogs/wave-optics/dichroic-and-diffraction-type-polarizers

#### Wire-grid polarizer
- **What it is:** Sub-wavelength array of parallel metal (Al/W) wires on a substrate. Reflects the field parallel to the wires, transmits the perpendicular field. Works from visible through far-IR / THz; the reflected polarization is a usable second beam.
- **Optical behavior:** Linear polarizer; extinction ~1e2-1e3 in visible, up to ~1e4 in IR. Unlike absorptive film it REFLECTS the rejected polarization (can act as a crude polarizing beamsplitter). Very wide angular acceptance and huge bandwidth.
- **Key params:** pol_axis_deg (perp to wires), extinction (band-dependent), wavelength band, reflect_rejected (bool)
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction. Maps to existing M_polarizer for the transmitted beam. NEW optional behavior: to model the reflected rejected beam it would need a second (reflected) child like is_pbs -- otherwise treat as absorptive. Add optional `reflect_rejected` flag reusing the PBS two-child path.
- **Real examples:** Thorlabs WP25M-VIS (visible wire grid, Ø1in), WP25M-IR (IR), Moxtek ProFlux; THz free-standing grids. Ext ~1e2-1e3 vis, ~1e4 IR.
- **Refs:** https://www.thorlabs.us/newgrouppage9.cfm?objectgroup_id=4984 , https://doi.org/10.3390/photonics12111046

#### Glan-Thompson polarizer
- **What it is:** Two cemented calcite prisms; the ordinary ray undergoes TIR at the cement interface and is deflected/absorbed, the extraordinary ray passes through. Cement limits damage threshold but gives wide acceptance angle.
- **Optical behavior:** High-extinction linear polarizer (>1e5). WIDE acceptance angle (~15deg full, long form >26deg) -- usable in converging beams. Single transmitted polarized output; rejected o-ray is dumped sideways (absorbed in blackened housing). Range ~350-2300nm (calcite).
- **Key params:** pol_axis_deg, extinction (~1e5), acceptance_angle (~15-26deg), clear aperture
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction=100000. Maps 1:1 today. acceptance_angle is metadata for a chief-ray tracer (no behavior change). No new params for the on-axis case.
- **Real examples:** Thorlabs GTH10M (Ø10mm CA), GTH5 (Ø5mm); Newport 10GT04; ext >1e5, accept >15deg, 350-2300nm.
- **Refs:** https://www.newport.com/f/glan-thompson-calcite-polarizers , https://artifex-engineering.com/optics/polarization-optics/polarizers/glan-thompson-polarizers/

#### Glan-Taylor polarizer
- **What it is:** Air-spaced calcite Glan prism cut so the ordinary ray hits TIR and is reflected out a side face; extraordinary ray transmits. Air gap raises damage threshold vs Glan-Thompson but narrows acceptance angle.
- **Optical behavior:** High-extinction linear polarizer (~1e5). NARROW acceptance angle (~few deg). Single transmitted output; the rejected o-ray exits a SIDE face at ~90deg (often dumped, but it is a real second beam). Calcite 350-2300nm.
- **Key params:** pol_axis_deg, extinction (~1e5), acceptance_angle (narrow), side-reject port
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction=100000 for the transmitted beam. Maps 1:1. The side-dumped o-ray is normally ignored; if modeled it reuses a PBS-style reflected child. No new params required for transmit-only use.
- **Real examples:** Thorlabs GT10 (Ø10mm CA, ext 1e5), GT10-A/B/C (AR coatings for 350-700/650-1050/1050-1700nm); Newport 10GT04.
- **Refs:** https://www.thorlabs.com/item/GT10 , https://en.wikipedia.org/wiki/Glan%E2%80%93Taylor_prism

#### Glan-laser polarizer
- **What it is:** A Glan-Taylor optimized for high-power lasers: laser-grade calcite, Brewster-cut escape windows on the side faces so the rejected o-ray exits cleanly (avoiding heating), high damage threshold.
- **Optical behavior:** Same as Glan-Taylor: high-extinction (>1e5) single transmitted linear output, narrow acceptance, but with a clean side-exit port for the rejected beam and high LIDT. Often has TWO side ports (escape windows).
- **Key params:** pol_axis_deg, extinction (>1e5), damage threshold, side-escape port(s)
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction=100000. Identical mapping to Glan-Taylor. Damage threshold + escape-window geometry are metadata only. NEW `polarizer_type=GLAN_LASER` would just label it; no behavior change for the transmitted chief ray.
- **Real examples:** Thorlabs GL10 (uncoated Ø10mm), GL10-A (AR 350-700nm), GL5; ext >1e5, high LIDT for pulsed lasers.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=815 , https://en.wikipedia.org/wiki/Glan_prism

#### Wollaston prism (beam-splitting polarizer)
- **What it is:** Two cemented birefringent wedges with orthogonal optic axes. Splits input into TWO diverging beams of orthogonal linear polarization, symmetrically about the input axis.
- **Optical behavior:** DUAL-OUTPUT: emits two transmitted beams at +/- (separation/2), each orthogonally linearly polarized (|H> and |V> in the prism frame). Separation angle is wavelength-dependent and set by wedge angle/material: ~1deg quartz, ~10-20deg calcite/alpha-BBO/YVO4. NEW behavior not in any current single-output element.
- **Key params:** separation_angle_deg (material+wedge), prism_axis_deg (defines the two pol states), wavelength dependence, polarizer_type=WOLLASTON
- **Add-on mapping:** NEW element behavior: NEW `polarizer_type=WOLLASTON` + NEW `separation_angle_deg` (+ reuse pol_axis_deg as the prism reference axis). Tracer must push TWO transmitted children (like PBS at tracer.py:400-401 but both transmitted) deviated by +/- sep/2 in the wedge plane, each projected onto orthogonal linear Jones |H>,|V>. Half power each for unpolarized input.
- **Real examples:** Thorlabs WP10 (calcite, ~20deg sep, Ø10mm); quartz Wollastons ~1-3.5deg; alpha-BBO/YVO4 ~20deg. Used in DIC microscopy and polarimetry.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=917 , https://en.wikipedia.org/wiki/Wollaston_prism

#### Rochon prism (beam-splitting polarizer)
- **What it is:** Two birefringent prisms; the ORDINARY ray passes straight through UNDEVIATED and achromatic, while the extraordinary ray is deflected. Asymmetric split (one beam stays on axis).
- **Optical behavior:** DUAL-OUTPUT but asymmetric: one output (o-ray) is undeviated and dispersion-free, the other (e-ray) is deflected by a wavelength-dependent angle (~half of a comparable Wollaston). Both orthogonally linearly polarized.
- **Key params:** deflection_angle_deg (e-ray only), prism_axis_deg, polarizer_type=ROCHON
- **Add-on mapping:** NEW `polarizer_type=ROCHON`: same two-child machinery as Wollaston but ONE child keeps ray.dir (undeviated, |H>) and the other is deflected by deflection_angle_deg (|V>). Reuses the Wollaston dual-output path with an asymmetric deviation.
- **Real examples:** Thorlabs/other calcite and MgF2 Rochon prisms; quartz Rochon for UV (undeviated beam is achromatic). Senarmont prism is a close variant (e-ray undeviated instead).
- **Refs:** https://en.wikipedia.org/wiki/Wollaston_prism , https://www.findlight.net/optics/polarization-optics/wollaston-polarizers/wollaston-polarizer-rochon-polarizer-wollaston-prism-bbocalciteyvo4quartz

#### Nicol prism (historical)
- **What it is:** The original calcite polarizer: two prisms cemented with Canada balsam; the o-ray hits TIR at the balsam layer and is rejected, the e-ray transmits. Largely obsolete, replaced by Glan types (its exit beam is laterally offset and it has a limited aperture).
- **Optical behavior:** Single transmitted linear output, high extinction (TIR-based). Behaviorally a high-extinction linear polarizer with a small lateral beam shift and narrow acceptance. Functionally identical to Glan-Thompson for the tracer.
- **Key params:** pol_axis_deg, extinction (high), small lateral offset
- **Add-on mapping:** POLARIZER: pol_axis_deg, extinction ~1e4-1e5. Maps 1:1 to existing M_polarizer; treat as a Glan-Thompson. No new params (lateral offset negligible/optional).
- **Real examples:** Vintage Nicol prisms (calcite + Canada balsam); no longer a mainstream Thorlabs/Edmund catalog item -- represented for completeness.
- **Refs:** https://www.rp-photonics.com/polarizers.html , https://en.wikipedia.org/wiki/Nicol_prism

#### Brewster-window / thin-film plate polarizer
- **What it is:** A single plate (or stack/'pile of plates') tilted at Brewster's angle. p-polarization transmits with ~zero reflection loss; s-polarization is partly reflected. Used as a low-loss intracavity polarizer in lasers; thin-film (MacNeille) plate polarizers add dielectric coatings for high extinction.
- **Optical behavior:** Polarizing by Fresnel reflection at Brewster's angle: transmits p strongly, reflects part of s. A single window gives WEAK extinction (~few:1 to ~20:1); a coated thin-film plate polarizer reaches ~1e3-1e4. The reflected s-beam is a real second (deviated) output. This overlaps the existing Fresnel/Brewster physics already in the BEAMSPLITTER/mirror plane-of-incidence code.
- **Key params:** pol_axis_deg (=p in plane of incidence), extinction (low for bare window, high for coated TFP), incidence ~Brewster angle
- **Add-on mapping:** Two options: (a) single-output POLARIZER with pol_axis_deg + modest extinction (bare window ~10, coated TFP ~1e3); or (b) since the tracer already does true plane-of-incidence Fresnel s/p splitting (tracer.py:389-401 pbs_split), model it like an is_pbs BEAMSPLITTER tilted at Brewster's angle to get both the transmitted p and reflected s ports. NEW `polarizer_type=BREWSTER`/`THIN_FILM_PLATE` selects which.
- **Real examples:** Thorlabs thin-film plate polarizers / Brewster windows for CO2 and high-power lasers; LBTEK/Newport TFP for 1064nm (ext ~1e3-1e4); bare Brewster windows in laser cavities.
- **Refs:** https://www.rp-photonics.com/polarizers.html , https://www.edmundoptics.com/knowledge-center/application-notes/optics/polarizer-selection-guide/

#### Circular polarizer
- **What it is:** Compound element: a linear polarizer bonded to a quarter-wave plate with its fast axis at 45deg to the polarizer's transmission axis. Converts unpolarized/linear input to circular (one handedness). Asymmetric -- only one face circularizes.
- **Optical behavior:** Output Jones = M_qwp(45deg) * M_polarizer(axis). Unpolarized in -> circularly polarized out (RCP or LCP per QWP orientation). Reverse direction: blocks the opposite circular handedness (used as anti-reflection/glare filter, ellipsometry, AR display filters). Handedness set by the 45deg sign.
- **Key params:** pol_axis_deg, qwp fast axis = pol_axis +/-45deg, handedness, design_wl
- **Add-on mapping:** Represent as TWO stacked existing elements: POLARIZER(pol_axis_deg) immediately followed by WAVEPLATE(retardance=90, fast_axis=pol_axis+45). No new physics. OR add a NEW composite `polarizer_type=CIRCULAR` convenience element that internally applies M_waveplate(90,axis+45) . M_polarizer(axis,ext) in one Jones product; handedness via +45 vs -45.
- **Real examples:** Thorlabs CP1L/CP1R-series circular polarizers (left/right hand), Edmund circular polarizing film; camera/display AR circular polarizers. Typically film QWP + film LP laminate.
- **Refs:** https://www.thorlabs.com/choosing-a-wave-plate , https://www.fiberoptics4sale.com/blogs/wave-optics/102261126-jones-matrix-calculus

---

## Gratings, Prisms & Retroreflectors

> **Tracer / behavior model:** HOW THE TRACER SHOULD MODEL EACH CATEGORY:

GRATINGS (element_type GRATING): The existing _diffract() in tracer.py (lines 234-248) is correct — it applies sin(theta_m)=sin(theta_i)+m*lambda/d with d=1/lines_per_mm in the true plane of incidence, returns the diffracted direction, and falls back to specular on evanescent (|sin_m|>1) or m=0. GRATING is (correctly) in the REFLECTIVE list. Three gaps to close: (1) EFFICIENCY — every order currently gets flat reflectivity; real ruled/blazed/echelle gratings concentrate energy at the blaze. Add NEW param blaze_wl_nm (or blaze_angle_deg) and weight per-order power by a blaze function so the design order dominates. Ruled-blazed = sharp peak at blaze; holographic-sinusoidal = broad/flat; echelle = high-order peak (driven by the SAME blaze param, just small lines_per_mm + large grating_order). (2) TRANSMISSION gratings (ruled + VPH) are not representable — GRATING is hard-reflective. Add NEW param grating_mode (REFLECTION | TRANSMISSION); in transmission, diffract the order into the FORWARD hemisphere and skip the forced-reflect branch. (3) Polarization s/p efficiency is already partially carried via redirect_field (line 369) — fine for Tier-1.

PRISMS: There is NO general prism behavior; PRISM_MIRROR is a flat 45-deg internal reflector sharing the MIRROR path. Split the real prisms into THREE behavioral buckets and add a NEW param prism_type:
 (a) PURE-FOLD REFLECTORS (right-angle 90/180, pentaprism, Amici roof) -> stay on PRISM_MIRROR / flat-reflect. RIGHT_ANGLE works as-is for 90 deg. PENTA needs a small NEW branch: a FIXED 90-deg deviation that is TILT-INSENSITIVE (do not apply 2*tilt like a single mirror) — analogous to how RETROREFLECTOR is angle-insensitive. AMICI_ROOF = 90-deg fold + (future) transverse left-right image flip. 
 (b) TRANSVERSE-FIELD-ONLY (Dove) -> chief ray is a straight-through no-op; its real effect is rotating the IMAGE/polarization frame by 2*phi. Implement DOVE as a transverse-frame rotation operator on the carried field (like WAVEPLATE rotates polarization), param rotation_deg. Without a transverse-image model it is just a transparent pass.
 (c) REFRACTIVE DEVIATION/DISPERSION (wedge, equilateral dispersing, Pellin-Broca, anamorphic) -> genuinely NEW transmissive behavior the tracer lacks. WEDGE = small fixed bend delta=(n-1)*alpha about the wedge axis (params wedge_angle_deg, clocking, glass n). DISPERSING_EQUILATERAL / PELLIN_BROCA = wavelength-dependent refractive bend via Snell at two tilted faces using a Sellmeier/Abbe dispersion model (params apex_angle_deg, glass, and for Pellin-Broca a design_wl pinned to 90-deg deviation). ANAMORPHIC = 1-D anisotropic beam magnification — requires extending the Gaussian q model to separate qx/qy (astigmatic beam); out of scope until then. KEY: refractive dispersion is NOT the grating equation — it is Snell's law at tilted faces with n(lambda), a new code path.

RETROREFLECTORS (element_type RETROREFLECTOR): The existing branch (tracer.py lines 327-339) is exactly right — ideal angle-insensitive d_out=-d_in with scalar reflectivity, and the code comment already correctly disclaims per-sextant polarization. ALL THREE physical variants (solid TIR cube, hollow cube, cat's-eye) share this chief-ray return, so geometry needs no change. Optional NEW param retro_type (TIR_SOLID | COATED_SOLID | HOLLOW | CATSEYE) only to differentiate (i) polarization: scramble for TIR_SOLID, preserve for HOLLOW/COATED, vs (ii) chromatic dispersion: present for solid, none for hollow, vs (iii) beam-deviation tolerance (3 arcsec TIR / <20 arcsec hollow). CATSEYE additionally focuses-and-recollimates (a LENS+MIRROR ABCD effect on the q-parameter) — only matters if you model the focus; otherwise compose it from existing LENS+MIRROR.

NET NEW PARAMETERS PROPOSED: blaze_wl_nm (or blaze_angle_deg) + grating_mode + grating_profile on GRATING; prism_type (RIGHT_ANGLE/PENTA/AMICI_ROOF/DOVE/WEDGE/DISPERSING_EQUILATERAL/PELLIN_BROCA/ANAMORPHIC) + wedge_angle_deg + apex_angle_deg + a glass/dispersion model + rotation_deg (reuse design_wl for Pellin-Broca/blaze design point) on the prism path; retro_type (+ optional focal_length for cat's-eye) on RETROREFLECTOR. NEW tracer behaviors required: per-order grating efficiency (blaze fn), transmission-grating forward diffraction, tilt-insensitive fixed-angle fold (penta), transverse-frame rotation (Dove), refractive single-wedge deviation, refractive wavelength-dependent dispersion via Snell (equilateral/Pellin-Broca), and anisotropic qx/qy beam scaling (anamorphic, biggest lift).

#### Ruled reflection grating (blazed sawtooth)
- **What it is:** A reflective substrate with mechanically ruled (diamond-cut) parallel sawtooth grooves, usually a master replicated in epoxy onto a coated (Al/Au) blank. The asymmetric sawtooth facet is tilted at the BLAZE ANGLE so most energy concentrates into one non-zero order at the blaze wavelength. e.g. Thorlabs GR25-1205 (1200 l/mm, 500 nm blaze, 25x25 mm), GR13-0605.
- **Optical behavior:** Splits incident light into discrete diffracted orders per the grating equation: sin(theta_m) = sin(theta_i) + m*lambda/d, with d = 1/lines_per_mm. m=0 is specular (no dispersion); |m|>=1 disperses by wavelength. Blaze concentrates efficiency (~70-90% peak) into the design order near blaze_wl; efficiency falls off away from it. Reflective: all orders on the incidence side. Has strong s/p polarization dependence near Littrow.
- **Key params:** lines_per_mm (groove density, ~300-2400), diffraction order m, blaze_angle (or blaze_wavelength), substrate coating (Al/Au), s/p efficiency
- **Add-on mapping:** Maps DIRECTLY to GRATING. Current tracer already implements the grating equation in _diffract() with lines_per_mm + grating_order and falls back to specular on evanescent orders (good). NEW param needed: blaze_wl_nm (or blaze_angle_deg) to scale per-order EFFICIENCY (currently power = flat reflectivity for every order — a blazed grating should weight the blaze order high and others low). Optional: groove_orientation so dispersion plane is defined. The geometry path (REFLECTIVE list) is already correct.
- **Real examples:** Thorlabs GR25-1205 (1200 l/mm, blaze 500 nm, 25x25 mm, Al); GR13-0605 (600 l/mm); Newport 53-* ruled; Mid-IR ruled gratings (Au, blaze 2-12 um). Typical 300-2400 l/mm.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=9026 ; https://en.wikipedia.org/wiki/Diffraction_grating ; https://en.wikipedia.org/wiki/Blazed_grating

#### Holographic reflection grating (sinusoidal)
- **What it is:** Grooves formed by recording an interference fringe pattern in photoresist (then ion-etched / coated), giving a SINUSOIDAL profile rather than a ruled sawtooth. Lower periodic error -> very low stray light / ghosting. e.g. Thorlabs GH25-12U (1200 l/mm holographic).
- **Optical behavior:** Same grating equation and order geometry as ruled. Differences are in the EFFICIENCY envelope: sinusoidal profile -> generally LOWER peak efficiency than a blazed ruled grating but a BROADER usable wavelength range and far less scattered light/ghost lines. Often unpolarized-flat. Not strongly blazed (energy split more evenly between +/-1 orders).
- **Key params:** lines_per_mm, order m, modulation depth (sets efficiency), low stray-light figure
- **Add-on mapping:** Maps to GRATING with the SAME geometry path as ruled. The only behavioral difference vs ruled is the efficiency model: NEW param grating_profile (RULED_BLAZED | HOLOGRAPHIC_SINUSOIDAL) selecting the efficiency envelope (peaked-at-blaze vs broad-flat). If the tracer keeps the chief-ray flat-reflectivity model, ruled and holographic are geometrically identical and only differ once blaze/efficiency is added.
- **Real examples:** Thorlabs GH25-12U / GH25-18V / GH25-24V (1200-2400 l/mm, holographic, Al/Au); Newport holographic. Broad UV-VIS coverage.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=25&pn=GH25-12U ; https://www.rp-photonics.com/diffraction_gratings.html

#### Transmission grating (ruled & Volume Phase Holographic)
- **What it is:** Grooves on a TRANSPARENT substrate; light diffracts in transmission. Two sub-kinds: surface-relief ruled (epoxy on glass, sawtooth) and Volume Phase Holographic (VPH) — a dichromated-gelatin (DCG) layer between two glass plates with a sinusoidal index modulation. e.g. Thorlabs GT25-03 (300 l/mm transmission), VPH transmission gratings.
- **Optical behavior:** Grating equation in TRANSMISSION: the diffracted orders emerge on the far side of the substrate, d*(sin theta_m - sin theta_i) = m*lambda (sign convention transmissive). Zero order = undeviated through-beam; +/-1 disperse. VPH can be blazed by tuning fringe slant/thickness (Bragg condition) for very high efficiency (>90%) in one order over a band. In-line geometry (beam continues forward) unlike reflective gratings.
- **Key params:** lines_per_mm, order m, blaze/Bragg wavelength (VPH), substrate index (sets the in-substrate angles)
- **Add-on mapping:** NOT cleanly covered today — GRATING in the tracer is hard-wired REFLECTIVE (it is in the REFLECTIVE list and _diffract returns a reflected-side direction). NEW param needed: grating_mode (REFLECTION | TRANSMISSION). In TRANSMISSION mode the diffracted child must propagate to the FAR side (forward hemisphere) using the transmission grating equation, and GRATING must be removed from the forced-reflective branch for that mode. Reuses lines_per_mm + grating_order; add blaze_wl_nm for VPH efficiency.
- **Real examples:** Thorlabs GT25-03 (300 l/mm), GT13-06 (600 l/mm) ruled transmission; Thorlabs VPH visible/NIR transmission gratings (DCG, >80-90% peak). 100-2000 l/mm typical.
- **Refs:** https://www.thorlabs.com/NewGroupPage9_PF.cfm?Guide=10&Category_ID=184&ObjectGroup_ID=1123 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=15197

#### Echelle grating
- **What it is:** A coarse, steeply blazed RULED reflection grating: LOW groove density (tens to ~300 l/mm) but VERY HIGH blaze angle (e.g. R2 = 63.43 deg, R4 = 75.96 deg; R-number = tan(blaze angle)). Used at high orders (m = 10s-100s) near Littrow, cross-dispersed for high-resolution spectroscopy.
- **Optical behavior:** Same grating equation but operated at high m and large blaze angle near Littrow (theta_i ~= theta_m, beam returns near on itself). Gives high angular dispersion and resolving power. Each blaze-function peak spans one Free Spectral Range; needs a cross-disperser to separate overlapping orders. Efficiency stays >=40% of blaze-peak across each FSR.
- **Key params:** lines_per_mm (LOW, e.g. 31.6, 79, 316), blaze_angle / R-number, high order m, Littrow angle, free spectral range FSR = lambda/m
- **Add-on mapping:** Maps to GRATING — geometrically identical (same _diffract path), just driven with small lines_per_mm + large grating_order. NEW params to make it physically an echelle: blaze_angle_deg (drives the efficiency peak and the natural Littrow geometry) and ideally an efficiency model so high orders are weighted. No new geometry code — it is the blaze/efficiency model (same NEW blaze param as ruled) that distinguishes it.
- **Real examples:** Newport custom echelle (R2 63.43 deg / R4 75.96 deg; 31.6, 79, 316 l/mm); Richardson/Newport echelles for astro/ICP-OES spectrometers.
- **Refs:** https://www.newport.com/p/custom-echelle-gratings/echelle-diffraction-gratings/ ; https://www.sciencedirect.com/topics/physics-and-astronomy/echelle-gratings

#### Right-angle prism
- **What it is:** 45-45-90 glass prism. Beam enters a leg face and totally-internally-reflects off the hypotenuse. Deviates the beam 90 deg (one TIR off hypotenuse) or 180 deg / Porro retro (enter hypotenuse, two TIR off the legs). e.g. Thorlabs PS908 (N-BK7, 10 mm), PS911.
- **Optical behavior:** Pure DEVIATION by a fixed geometric angle (90 or 180 deg) with NO dispersion (entrance/exit faces normal to the beam). 90-deg use inverts/reverts image handedness like a single mirror; 180-deg (two TIR) acts like a Porro retroreflector returning the beam antiparallel but laterally offset. TIR imparts a polarization phase (s vs p) — not a clean mirror at the relevant angle.
- **Key params:** deviation angle (90 / 180), apex angles (45-45-90), substrate index n (sets TIR validity), entry face
- **Add-on mapping:** Maps to PRISM_MIRROR. The add-on already models PRISM_MIRROR as an internal 45-deg reflective face sharing the MIRROR path (flat reflect) — correct for the 90-deg deviation case. NEW param prism_type=RIGHT_ANGLE would let one PRISM_MIRROR node also express the 180-deg/Porro mode (two reflections -> antiparallel with lateral offset) instead of needing a RETROREFLECTOR. For Tier-1 chief ray the flat-reflect model is adequate; flagging TIR s/p phase as a future polarization refinement.
- **Real examples:** Thorlabs PS908 (N-BK7, 10 mm leg), PS909 (UVFS), PS911 (25.4 mm); Edmund right-angle prisms. KCB1C cage cube already referenced in add-on.
- **Refs:** https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=142 ; https://evidentscientific.com/en/microscope-resource/tutorials/prismsandbeamsplitters/commonprisms

#### Equilateral dispersing prism
- **What it is:** 60-60-60 (or similar apex) solid glass prism used REFRACTIVELY (not by TIR) to angularly disperse white light into a spectrum. e.g. Thorlabs PS863 (F2, equilateral), Edmund dispersing prisms.
- **Optical behavior:** Refracts at two faces; total DEVIATION depends on wavelength via n(lambda), so it ANGULARLY DISPERSES the beam (separates colors). Operated near MINIMUM DEVIATION (symmetric path) where deviation is least sensitive to input angle: delta_min relates n via n = sin((A+delta_min)/2)/sin(A/2), A = apex angle. No order structure (unlike a grating) — a single continuously-bent, wavelength-spread beam.
- **Key params:** apex angle A (~60 deg), Sellmeier index n(lambda) of glass (F2/SF11 high dispersion), input angle (set to minimum deviation)
- **Add-on mapping:** NOT currently representable. PRISM_MIRROR is reflective-only; there is no refractive-dispersing element. Either NEW prism_type=DISPERSING_EQUILATERAL on a new transmissive PRISM behavior, or extend GRATING-style dispersion with a continuous (orderless) refractive bend driven by n(lambda). NEW params: apex_angle_deg, glass/dispersion model (reuse a Sellmeier/Abbe number). This needs a genuinely new refractive-dispersion behavior in the tracer (closest existing math is wavelength-dependent bending, but via Snell at two tilted faces, not the grating equation).
- **Real examples:** Thorlabs PS863 (F2 equilateral), PS853 (N-SF11); Edmund/GlobalSpec equilateral dispersing prisms (25-30 mm).
- **Refs:** https://www.thorlabs.com/navigation.cfm?guide_id=20 ; https://www.globalspec.com/ds/1199/areaspec/spec_equilateral

#### Dove prism (image rotator)
- **What it is:** A truncated right-angle prism (apex removed) with a long flat hypotenuse; light enters a slanted end face, TIRs once off the long face, exits the other end. Must be used in COLLIMATED light. e.g. Thorlabs PS992 mounted Dove prisms.
- **Optical behavior:** Beam direction is UNDEVIATED (in-line) but the IMAGE is inverted/flipped by the single internal reflection; crucially, rotating the prism about the optical axis by angle phi rotates the transmitted IMAGE by 2*phi. Used as a continuous image/field rotator (e.g. in OAM optics, derotators). Chief ray passes straight through (single ray unchanged); the 2x rotation is a transverse-field property.
- **Key params:** prism rotation angle phi (image rotates 2*phi), length/aperture, single TIR, collimated-only
- **Add-on mapping:** Maps weakly to existing types — for a single CHIEF RAY a Dove prism is a straight-through pass with no deviation, so the tracer's ray geometry sees nothing. To model its EFFECT it needs a transverse field/image operator: NEW prism_type=DOVE that applies an image-rotation by 2*phi to the carried field/polarization frame (a rotation of the transverse E-vector basis), analogous to how WAVEPLATE rotates polarization. So: behavior = transverse-frame rotation, not a deviation. NEW params: prism_type=DOVE, rotation_deg (phi). Without a transverse-image model it is just a transparent no-op.
- **Real examples:** Thorlabs PS992 / PS991M mounted Dove prisms (N-BK7); Edmund image rotation prisms.
- **Refs:** https://en.wikipedia.org/wiki/Dove_prism ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=6810 ; https://www.edmundoptics.com/c/image-rotation-prisms/612/

#### Pellin-Broca prism (constant-deviation dispersing)
- **What it is:** A four-sided (90/75/135/60 deg) block that combines refraction + one internal TIR so that ONE selected wavelength always exits at a FIXED 90-deg deviation. Rotating the whole prism changes WHICH wavelength is deviated 90 deg without moving the in/out beams. e.g. Thorlabs ADB-10 (N-BK7), ADBU-10 (UVFS).
- **Optical behavior:** CONSTANT-DEVIATION dispersion: the through wavelength is bent exactly 90 deg; other wavelengths exit at slightly different angles (so it both disperses AND fixes one color's deviation). Used to pick one laser harmonic (e.g. separate 532 from 1064 nm) or compensate GVD, with fixed input/output geometry as you tune by rotating the prism.
- **Key params:** fixed deviation = 90 deg for the selected wavelength, prism rotation -> selected wavelength, glass dispersion n(lambda), apex set (90/75/135/60)
- **Add-on mapping:** NOT currently representable cleanly. It is a dispersing (refractive) element with a fixed 90-deg deviation for one wavelength — a hybrid of DISPERSING prism + 90-deg fold. NEW prism_type=PELLIN_BROCA on the same new refractive-dispersion behavior as the equilateral prism, but with the geometry pinned so the design/selected wavelength deviates 90 deg and others fan around it. NEW params: prism_type=PELLIN_BROCA, design/selected wavelength (reuse design_wl), glass dispersion. Same new refractive-dispersion machinery required.
- **Real examples:** Thorlabs ADB-10 / ADB-20 (N-BK7), ADBU-10 (UVFS, 11 mm); used for laser harmonic separation and pulse-compressor GVD.
- **Refs:** https://en.wikipedia.org/wiki/Pellin%E2%80%93Broca_prism ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3217

#### Amici roof prism
- **What it is:** A right-angle prism whose hypotenuse is replaced by a 90-deg 'roof' (two faces meeting at a precise 90-deg ridge), adding an extra reflection. e.g. Thorlabs roof prisms; used in telescope/microscope erecting systems.
- **Optical behavior:** Deviates the line of sight 90 deg like a right-angle prism, but the roof adds a second reflection that also REVERTS (left-right flips) the image, correcting handedness while inverting 180 deg about the axis. Net: 90-deg fold + non-reversed (erect-corrected) image. The roof edge splits/recombines the wavefront across the ridge (a subtle dual-channel reflection).
- **Key params:** 90-deg deviation, roof ridge tolerance (arcsec — critical for double-image), image reversion/erecting, apex angles
- **Add-on mapping:** Maps to PRISM_MIRROR for the 90-deg deviation (same flat-reflect chief-ray geometry as right-angle). The roof's image-handedness reversal is a transverse-field effect (like Dove's rotation but a mirror-flip). NEW prism_type=AMICI_ROOF flag to: (a) keep the 90-deg fold and (b) apply a left-right field-frame flip. For chief-ray it behaves exactly like the right-angle PRISM_MIRROR; the reversion only matters once a transverse-image model exists.
- **Real examples:** Thorlabs Amici roof prisms; Edmund Amici/roof prisms; common in binocular/telescope erectors.
- **Refs:** https://evidentscientific.com/en/microscope-resource/tutorials/prismsandbeamsplitters/commonprisms ; https://avantierinc.com/resources/knowledge-center/optical-prism-selection-guide/

#### Pentaprism
- **What it is:** Five-faced prism with two reflective faces at 45 deg to each other (often coated, since the angles are beyond TIR). e.g. Thorlabs PS975-class pentaprisms; used in SLR viewfinders, alignment, surveying.
- **Optical behavior:** Deviates the beam EXACTLY 90 deg via two reflections, and because it is an EVEN number of reflections the image is NEITHER inverted NOR reversed (handedness preserved) — and the 90-deg deviation is INDEPENDENT of prism tilt (constant-deviation in the deviation plane), making it a precision square-fold / alignment tool.
- **Key params:** fixed 90-deg deviation (tilt-insensitive), two reflective coated faces, no image inversion, even reflections
- **Add-on mapping:** Maps to PRISM_MIRROR with NEW prism_type=PENTA. Geometrically the chief ray is a clean 90-deg fold (two flat reflections) — the existing flat-reflect MIRROR/PRISM_MIRROR path reproduces the output direction. The valuable distinction is its TILT-INSENSITIVITY: a single MIRROR fold rotates the beam by 2*tilt, but a pentaprism does NOT. So prism_type=PENTA should force a fixed 90-deg deviation about the prism's deviation axis regardless of node tilt (like RETROREFLECTOR is angle-insensitive, but for a 90-deg fold). NEW params: prism_type=PENTA. This needs a small new geometry branch (fixed-angle fold) rather than plain reflect().
- **Real examples:** Thorlabs pentaprisms; Edmund penta prisms; Newport. Used in alignment telescopes and camera viewfinders.
- **Refs:** https://evidentscientific.com/en/microscope-resource/tutorials/prismsandbeamsplitters/commonprisms ; https://www.thorlabs.com/navigation.cfm?guide_id=20

#### Wedge prism (single + Risley pair)
- **What it is:** A thin prism with a small wedge angle alpha between input and output faces. e.g. Thorlabs PS810-series (2-10 deg wedges). A counter-rotating PAIR forms a Risley beam-steering unit.
- **Optical behavior:** Refracts the beam by a small fixed DEVIATION delta ~= (n-1)*alpha (thin-prism approximation), with mild chromatic spread. A single wedge steers the beam a fixed small angle; two independently rotating wedges (Risley pair) steer the beam anywhere within a cone of half-angle up to delta1+delta2. Also used to introduce controlled tilt/lateral shift.
- **Key params:** wedge angle alpha, index n -> deviation delta=(n-1)*alpha, prism rotation (Risley), chromatic dispersion ~ dn/dlambda
- **Add-on mapping:** NOT currently representable. It is a small refractive DEVIATION (not a fold, not a grating). NEW prism_type=WEDGE on a refractive-deviation behavior: deflect the chief ray by delta=(n-1)*alpha about the wedge axis at the chosen clocking angle. NEW params: wedge_angle_deg (alpha), clocking/rotation_deg, glass index/dispersion. Simpler than the full dispersing-prism math (a single fixed small bend), but still a new transmissive-deviation branch the tracer lacks.
- **Real examples:** Thorlabs PS810 (N-BK7, 2 deg), PS811 (5 deg), PS812 (10 deg); Risley scanner pairs; Edmund wedge prisms.
- **Refs:** https://www.rp-photonics.com/prisms.html ; https://www.thorlabs.com/navigation.cfm?guide_id=20

#### Anamorphic prism pair
- **What it is:** A matched pair of prisms (e.g. Thorlabs PS871-B) arranged to expand/compress the beam in ONE transverse axis only — used to circularize the elliptical output of a laser diode.
- **Optical behavior:** Refraction at the tilted faces MAGNIFIES (or compresses) the beam diameter along one axis by a fixed ratio M (typ. 2x-6x) while leaving the orthogonal axis unchanged; net beam direction is kept (anti-symmetric pair) but laterally offset. Turns an elliptical diode beam round. This is a 1-D beam-size transform, not a deviation or dispersion.
- **Key params:** per-prism magnification M (set by apex + index + incidence), pair ratio (e.g. 2x, 3x, 4x), axis of magnification, fixed in/out direction
- **Add-on mapping:** NOT representable in the chief-ray model: it changes BEAM SHAPE (anisotropic 1-D magnification of the Gaussian), not the chief-ray direction. The add-on tracks a Gaussian q-parameter (q_from_waist) that is currently rotationally symmetric. Modeling anamorphic prisms properly needs an ASTIGMATIC/anisotropic beam (separate qx, qy) — a significant extension. NEW prism_type=ANAMORPHIC with mag_ratio + axis, applied as a 1-D scaling of the transverse beam size. Flag as out-of-scope until the beam model supports x/y-asymmetric waists.
- **Real examples:** Thorlabs PS871-B / PS873-B anamorphic prism pairs (2x, 3x, 4x for 405-980 nm diodes); Edmund anamorphic pairs.
- **Refs:** https://www.rp-photonics.com/prisms.html ; https://www.thorlabs.com/navigation.cfm?guide_id=20

#### Solid (glass) corner-cube retroreflector — TIR prism
- **What it is:** A glass cube corner (three mutually perpendicular internal faces) cut from solid glass; uses total internal reflection on the three back faces. e.g. Thorlabs PS975 (N-BK7, 25.4 mm dia, L=22 mm). Backside-coated variants (PS975M-M01B, Au) also exist.
- **Optical behavior:** RETROREFLECTS: returns the beam ANTIPARALLEL to incidence (d_out = -d_in) regardless of cube orientation (angle-insensitive), with a lateral offset. Three reflections preserve direction within ~3 arcsec for TIR prisms. TIR scrambles POLARIZATION (per-sextant phase shifts); backside metal-coated versions limit polarization change to <10 deg. Solid glass adds material absorption + chromatic effects from the entry/exit refraction.
- **Key params:** angle-insensitive d_out=-d_in, beam-deviation tolerance (~3 arcsec TIR), reflectivity, polarization scramble (TIR) vs <10 deg (coated), substrate n + dispersion
- **Add-on mapping:** Maps DIRECTLY to RETROREFLECTOR. The tracer already implements ideal angle-insensitive d_out=-d_in with scalar reflectivity and explicitly notes per-sextant polarization is out of Tier-1 scope — exactly right for this part. NEW (optional) param retro_type (TIR_SOLID | COATED_SOLID | HOLLOW) to (a) choose whether polarization is scrambled/randomized (TIR) vs preserved (hollow/coated) and (b) set the beam-deviation tolerance. No geometry change needed; the optional refinement is a polarization/tolerance flag.
- **Real examples:** Thorlabs PS975 (N-BK7, 25.4 mm, L=22 mm, uncoated), PS975M-A (AR 350-700 nm), PS975M-M01B (Au backside, polarization-preserving <10 deg); Edmund solid corner cubes. Beam deviation <=3 arcsec.
- **Refs:** https://www.thorlabs.com/item/PS975 ; https://www.thorlabs.com/NewGroupPage9_PF.cfm?Guide=10&Category_ID=140&ObjectGroup_ID=145 ; https://www.rp-photonics.com/retroreflectors.html

#### Hollow corner-cube retroreflector (3 first-surface mirrors)
- **What it is:** Three flat first-surface mirrors assembled into a 90-deg corner — air path, no bulk glass. e.g. Thorlabs HRR201-P01 (mounted), replicated hollow lateral-transfer retroreflectors.
- **Optical behavior:** Same angle-insensitive retroreflection d_out = -d_in, but with NO refraction, NO chromatic dispersion, and NO material absorption (air path). Polarization much better preserved than TIR (metal-mirror reflections only). Larger beam-deviation tolerance than precision TIR: typically <20 arcsec (replicated lateral-transfer types <5 arcsec). Lighter; favored for interferometry/metrology and space.
- **Key params:** d_out=-d_in (angle-insensitive), beam deviation (<20 arcsec typical, <5 arcsec premium), mirror reflectivity (metal coating), polarization-preserving, no chromatic dispersion
- **Add-on mapping:** Maps DIRECTLY to RETROREFLECTOR — identical chief-ray behavior to the solid cube (the tracer's d_out=-d_in covers both). Distinction from solid is purely in polarization handling (better preserved) and dispersion (none). NEW (optional) retro_type=HOLLOW selects 'polarization preserved, no chromatic shift' vs the solid-TIR 'scramble'. Geometry unchanged.
- **Real examples:** Thorlabs HRR201-P01 / HRR202 mounted hollow retroreflectors (beam dev <20 arcsec); replicated hollow lateral-transfer (<5 arcsec); Edmund hollow retroreflectors; PLX. NASA-heritage hollow cubes.
- **Refs:** https://www.thorlabs.com/mounted-hollow-retroreflector-mirrors ; https://www.edmundoptics.com/f/hollow-retroreflectors/12301 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=15416

#### Cat's-eye retroreflector
- **What it is:** A lens (or lens+mirror) system: a convex lens with a mirror placed at its focal plane (ideally a parabolic/curved mirror), depth comparable to its aperture. Used in laser trackers (SMRs) and tilt-immune interferometers.
- **Optical behavior:** Retroreflects d_out = -d_in by focusing the incoming beam to a point on the back mirror and re-collimating on return — effectively a focal-length-based retro rather than three flat reflections. Gives wide acceptance angle and is tilt-IMMUNE (mirror-tilt-immunity interferometry). Unlike a corner cube, it inverts the beam through a focus (can flip the wavefront). Performance set by lens focal length / mirror figure.
- **Key params:** d_out=-d_in, focal length (lens), back-mirror figure (flat/parabolic), wide field of view, focuses-then-recollimates (passes through focus)
- **Add-on mapping:** Maps to RETROREFLECTOR for the chief-ray return direction (d_out=-d_in is identical). What it does ADDITIONALLY — focus to the back mirror and re-collimate — is a LENS+MIRROR ABCD effect the simple retro model ignores. NEW (optional) retro_type=CATSEYE plus a focal_length param if you want it to apply the focusing (q-parameter passes through a focus and back), otherwise it is indistinguishable from a corner cube at chief-ray level. Could alternatively be COMPOSED from existing LENS + MIRROR elements one focal length apart.
- **Real examples:** Cat's-eye spherically-mounted retroreflectors (SMRs) for laser trackers (FARO/Leica); tilt-immune interferometer cat's-eyes; patent US5357371 cat-eye arrays.
- **Refs:** https://www.rp-photonics.com/retroreflectors.html ; https://www.meetoptics.com/academy/retroreflectors ; https://www.discovery.researcher.life/article/mirror-tilt-immunity-interferometry-with-a-cat-s-eye-retroreflector/b39857b9a32631838da88ca6c351028d

---

## Filters & Apertures

> **Tracer / behavior model:** HOW THE ADD-ON MODELS THESE TODAY (from optical_alignment_sim/tracer.py + properties.py):
- FILTER: _transmission(op, wl) is an IDEAL STEP. ND -> 10^-od (flat, gray). LP -> T=1 if wl>=cut_lo_nm else 0. SP -> T=1 if wl<=cut_hi_nm else 0. BP -> T=1 if cut_lo_nm<=wl<=cut_hi_nm else 0. There is NO edge steepness, NO finite blocking OD outside the band (it is exactly 0), NO passband insertion loss, NO AOI-dependent blueshift. Jones is scaled by sqrt(T) so polarization survives, power scales by T.
- ATTENUATOR: pure 10^-od, wavelength-flat. This is the natural home for a gray/Inconel ND that is NOT spectrally selective.
- APERTURE and PINHOLE: identical physics -> _clip_T = 1 - exp(-2 a^2 / w^2), a circular Gaussian power clip where a = clear_aperture (a RADIUS in mm) and w = local Gaussian beam radius from the q-parameter. APERTURE is meant as a hard beam-stop/limiter; PINHOLE is the pass-through spatial-filter aperture. Both are CIRCULAR ONLY and aperture-on-axis; there is no clipped-spot diffraction (no Airy regrowth), no off-axis vignetting of the chief ray, no rectangular/slit geometry.
- DICHROIC (separate element_type) is the real wavelength SPLITTER: pass_type LP/SP at cut_nm, transmit one band and specularly reflect the other with the ideal-mirror s/p convention. Edge filters that only TRANSMIT map to FILTER; edge filters used to SPLIT (reflect the rejected band to a second port) map to DICHROIC.

WHAT THE TRACER MUST ADD to model this category accurately (ranked):
1) filt_type='NOTCH' (NEW): a band-REJECT. Invert BP: T = od-floor (10^-od) inside [cut_lo,cut_hi], ~1 outside. Currently impossible -- there is no rejection-band primitive. This is the single biggest gap.
2) Per-band blocking OD instead of hard 0/1: replace the step return values with passband T=10^-(od_pass) (default ~0.05-0.15 insertion loss) and stopband T=10^-(od_block) (e.g. OD4-6). Lets OD actually mean blocking for LP/SP/BP, not just ND.
3) Finite EDGE STEEPNESS (NEW edge_pct or transition_nm): replace the unit step with a smooth roll-off (e.g. logistic/erf over a transition width that is a % of the cut wavelength). Real edges are 0.5-2% of cut wl; the current infinitely-sharp edge over-rejects just inside the band.
4) AOI blueshift (NEW, physics-correct for ALL dielectric/thin-film filters incl. DICHROIC): effective cut shifts to shorter wl as cut_eff = cut * sqrt(1 - (sin(theta)/n_eff)^2). The chief-ray incidence angle is already known at the hit; applying it makes tilt-tuning and accidental-AOI errors visible, which is exactly the alignment failure mode this tool exists to catch.
5) Spectrally-resolved ND (absorptive vs reflective): absorptive ND (Schott NG) is only flat over a stated band and rises/falls outside; reflective Inconel ND is flat UV->IR. Tier-1 can keep flat 10^-od for both; a NEW nd_coating='ABSORPTIVE'|'REFLECTIVE' flag only matters if you later add damage-threshold or band-edge realism.
6) Slit geometry for APERTURE/PINHOLE (NEW aperture_shape='CIRCLE'|'SLIT' + slit_width_mm, slit_height_mm, slit_angle_deg): _clip_T currently bakes in a circle. A slit needs a 1-D Gaussian clip in the across-slit direction: T = erf-style 1-2*Q(...) using the beam's transverse extent projected onto the slit's short axis. Needed for monochromator/spectrometer slits and beam-shaping.
7) Variable/animatable iris+ND: real irises and CV-ND wheels are continuously adjustable. clear_aperture and od are already animatable Float properties, so a motorized iris (diameter sweep) or CV-ND wheel (od sweep) needs NO new tracer code -- only a UI/driver and optionally a rotation->od mapping. Worth a NEW is_variable bool + a min/max range pair for realistic stops, but the BEHAVIOR is already covered.
8) Spatial-filter cleanup (the KT310 use-case): a PINHOLE at a lens focus should output a CLEANER Gaussian (truncate high-spatial-frequency content). The current clip only attenuates power; to model the actual benefit you would reset/clean the q-parameter or flag the downstream beam as 'spatially filtered'. Optional Tier-2.

INVARIANTS TO PRESERVE: keep Jones/evec scaled by sqrt(T) (already done) so all filters are polarization-neutral except where a real one is not (most are; a wire-grid 'ND' is not -- out of scope). clear_aperture stays a RADIUS in mm for circular elements; if slit params are added, document them as full width/height (not half) to avoid the radius/diameter trap. Filters do NOT bend the chief ray (dir unchanged) -- only DICHROIC/edge-split adds a reflected port.

#### Longpass edge filter (interference / thin-film, e.g. Thorlabs FELxxxx)
- **What it is:** A hard dielectric quarter-wave stack on UVFS/Eagle-XG glass that transmits wavelengths ABOVE a cut-on and reflects (not absorbs) those below it. 'Edgepass' family.
- **Optical behavior:** T(wl)~0 below cut-on, rises steeply (edge ~0.5-1% of cut-on wl) to >90-95% above. Out-of-band ODavg>4-6. The cut-on BLUESHIFTS with angle of incidence (~10% drop 0deg->45deg). Rejected band is reflected, so it can double as a coarse dichroic.
- **Key params:** cut-on wavelength (nm); edge steepness (% of cut); passband transmission (%); blocking OD; AOI; clear aperture
- **Add-on mapping:** FILTER, filt_type='LP', cut_lo_nm = cut-on. TODAY: ideal step at cut_lo_nm, T=0/1, od unused for LP. NEW params to be faithful: finite edge_steepness/transition_nm, per-band od_block + od_pass insertion loss, and AOI blueshift of cut_lo_nm. If used to SPLIT the reflected band, model as DICHROIC pass_type='LP' instead.
- **Real examples:** Thorlabs FEL0500/FEL0550/...FEL1500 (cut-on 500-1500nm, Ø25mm, ODavg>4); hard-coated edgepass series (Eagle XG/UVFS). Edmund TechSpec OD4 longpass.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=918 ; https://www.thorlabs.com/hard-coated-edgepass-filters

#### Shortpass edge filter (interference, e.g. Thorlabs FESxxxx)
- **What it is:** Dielectric stack that transmits BELOW a cut-off wavelength and reflects above it. Mirror image of the longpass.
- **Optical behavior:** T~>90% below cut-off, steep edge, ODavg>4 above. Same AOI blueshift of the cut-off. Harder to coat than LP so passbands are narrower in practice.
- **Key params:** cut-off wavelength (nm); edge steepness; passband T; blocking OD; AOI; clear aperture
- **Add-on mapping:** FILTER, filt_type='SP', cut_hi_nm = cut-off. TODAY ideal step. NEW: same three additions as LP (edge steepness, per-band OD, AOI blueshift). Splitting use-case -> DICHROIC pass_type='SP'.
- **Real examples:** Thorlabs FES0500/FES0550/...FES1000; hard-coated shortpass; Semrock BrightLine SP.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=918

#### Bandpass interference filter (multi-cavity thin-film)
- **What it is:** Stacked Fabry-Perot cavities forming a flat-top passband of finite FWHM with steep skirts and deep blocking on both sides. The general spectroscopy/imaging filter.
- **Optical behavior:** Flat-top transmission (>=85% at design wl) over a FWHM window [CWL-FWHM/2, CWL+FWHM/2]; OD>4-6 blocking outside; CWL blueshifts with AOI. Defined by CWL + FWHM, not two independent edges in practice.
- **Key params:** center wavelength (CWL); FWHM bandwidth; peak transmission; blocking OD; edge steepness; AOI; clear aperture
- **Add-on mapping:** FILTER, filt_type='BP', cut_lo_nm = CWL-FWHM/2, cut_hi_nm = CWL+FWHM/2. TODAY ideal flat-top step. NEW: edge steepness, finite od_block outside (currently exactly 0), od_pass peak loss, AOI blueshift. Optionally a CWL+FWHM parametrization that derives cut_lo/hi.
- **Real examples:** Thorlabs FBxxx-xx (e.g. FB550-40: CWL 550nm, FWHM 40nm, Ø25mm); hard-coated UV/VIS bandpass (Ø12.5/25mm); Semrock/Chroma imaging bandpass.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1860

#### Laser-line filter (ultra-narrow bandpass)
- **What it is:** A bandpass with very small FWHM (0.3-10nm) centered on a laser line, to isolate one line / reject ASE, plasma, or ambient light. Soft- or hard-coated.
- **Optical behavior:** Same as bandpass but FWHM ~1nm and tighter CWL tolerance; passband T 40-90%; strong out-of-band blocking. Very AOI-sensitive (small tilt walks it off the line).
- **Key params:** CWL (=laser line); FWHM (~0.3-10nm); peak T; blocking OD; AOI sensitivity; clear aperture
- **Add-on mapping:** FILTER, filt_type='BP' with a narrow cut_lo/cut_hi straddling the laser line. Same NEW needs as bandpass; AOI blueshift especially valuable here because a 1-2deg tilt is enough to kill transmission -- a real alignment failure this tool should surface.
- **Real examples:** Thorlabs FL532-1 (CWL 532+-0.2nm, FWHM 1+-0.2nm, Ø25mm), FL532-10 (FWHM 10nm), FL635-10, FL1064-10.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=FL532-1

#### Notch (band-reject / band-stop) filter
- **What it is:** Dielectric filter that REJECTS a narrow band and transmits everything else -- the inverse of a bandpass. Used to block a laser line in Raman/fluorescence while passing the signal.
- **Optical behavior:** T~>90% everywhere except a deep notch (OD>6, T<0.0001%) over a stop-band; notch center blueshifts with AOI. Rejection is by reflection+destructive interference.
- **Key params:** notch center wavelength; stop-band width; rejection OD (>6); passband T; AOI; clear aperture
- **Add-on mapping:** NO current mapping -- this is a genuine GAP. ADD filt_type='NOTCH' (NEW): T = 10^-od inside [cut_lo_nm,cut_hi_nm], ~1 outside (inverse of the BP branch). Reuses cut_lo/cut_hi/od; needs only the inverted branch in _transmission.
- **Real examples:** Thorlabs NF533-17 (533nm, OD>6), NF808-34, NF...; Semrock StopLine notch; Chroma ZET notch.
- **Refs:** https://www.thorlabs.com/notch-filters

#### Color/colored-glass filter (absorptive longpass or bandpass, Schott)
- **What it is:** Solid ionically/colloidally doped glass (Schott RG/OG/GG/BG series) that absorbs unwanted wavelengths. Cheap, AOI-insensitive, but soft edges and (some) fluoresce.
- **Optical behavior:** Gradual absorption edge (longpass RG/OG/GG: transmit long, absorb short) or broad bandpass (BG40). Edges are SHALLOW (tens of nm), unlike interference filters. No AOI shift (bulk absorption). Some autofluoresce.
- **Key params:** cut-on wavelength (50% point); edge slope (soft); internal transmittance vs thickness; clear aperture
- **Add-on mapping:** FILTER, filt_type='LP' (RG/OG/GG longpass) or 'BP' (BG bandpass). TODAY a sharp step approximates a soft edge poorly. NEW edge_steepness with a LARGE (soft) default distinguishes color-glass from interference filters; an absorptive flag (no AOI blueshift) keeps the cut fixed vs angle. od can carry the deep-block side.
- **Real examples:** Thorlabs FGL530 (OG530, LP 530nm), FGL695 (RG695), FGL9 (RG9, ~721nm), FGB37 (BG40 bandpass 335-610nm); Schott GG/OG/RG; Edmund Schott colored-glass longpass.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=999 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3695&pn=FGB37

#### Dichroic mirror / dichroic beamsplitter (edge filter used at 45deg)
- **What it is:** A thin-film edge filter designed for 45deg incidence: transmits one spectral band and reflects the other to a second port. The workhorse of fluorescence microscopy.
- **Optical behavior:** Two complementary outputs: transmit band T>90%, reflect band R>90%, split at a cut wavelength. Strongly polarization- and AOI-dependent (designed for a specific angle, usually 45deg).
- **Key params:** cut/edge wavelength; transmit-vs-reflect assignment (LP=transmit-long, SP=transmit-short); design AOI (45deg); s/p splitting; clear aperture
- **Add-on mapping:** DICHROIC (already exists), pass_type LP/SP, cut_nm = edge. This is the correct home for any edge filter whose REJECTED band must go to a port, vs FILTER which discards it. NEW (optional): AOI blueshift of cut_nm; a passband/reflectband efficiency <1 instead of perfect T=R=1.
- **Real examples:** Thorlabs DMLP505/DMLP650 (longpass dichroic), DMSP650 (shortpass dichroic), DMxxx; Semrock/Chroma multiband dichroics.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3313

#### Absorptive neutral-density filter (Schott NG glass)
- **What it is:** Spectrally-flat gray glass that ATTENUATES by absorption over a stated band (e.g. 400-650nm). High laser-damage threshold; flat phase front; little back-reflection.
- **Optical behavior:** Flat broadband attenuation T=10^-OD over its design band; outside the band the OD is NOT flat (rises/falls). Absorbs the rejected light (heats), so high damage threshold and no stray reflected beam.
- **Key params:** optical density OD (0.1-4+); design spectral band; flatness; clear aperture
- **Add-on mapping:** FILTER, filt_type='ND', od = OD -> 10^-od (already flat). Equivalently ATTENUATOR (pure 10^-od). NEW (optional) nd_coating='ABSORPTIVE' only to (a) suppress a reflected port and (b) later add band-edge realism + high damage threshold. Behavior already covered for Tier-1.
- **Real examples:** Thorlabs NE10A..NE60A (OD 1.0-6.0, 400-650nm, Schott), NEK01 kit (10 filters OD 0.1-4.0); Thorlabs NENIRxx (NIR absorptive); Schott NG glass.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=266 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=NEK01

#### Reflective / metallic neutral-density filter (Inconel on glass)
- **What it is:** N-BK7 or UVFS with a thin metallic Inconel coating that attenuates mostly by REFLECTION, flat from UV to NIR. Broader spectral flatness than absorptive but creates a reflected (ghost/stray) beam and has a low damage threshold.
- **Optical behavior:** T=10^-OD, very flat UV->IR. Significant fraction is REFLECTED (a real second beam) rather than absorbed; low damage threshold (~0.05 J/cm2 vs ~10 for absorptive). Often wedged to steer the ghost away.
- **Key params:** OD; spectral range (UV-NIR flat); reflected fraction; damage threshold; clear aperture
- **Add-on mapping:** FILTER filt_type='ND' or ATTENUATOR for the transmitted power (10^-od). The DIFFERENTIATOR vs absorptive is the reflected beam: TODAY both discard it. NEW nd_coating='REFLECTIVE' to optionally emit a SPLIT_R port (power*(approx 1-T) minus absorption) like a weak beamsplitter -- matters for stray-light/alignment realism. Otherwise behavior == absorptive in transmission.
- **Real examples:** Thorlabs NDxxA reflective (Inconel/N-BK7), NDUVxxA (UVFS reflective), ND05A..ND40A; Edmund metallic ND.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=119

#### Continuously-variable ND filter / ND wheel (metallic gradient)
- **What it is:** A disc (or linear strip) with an Inconel coating whose thickness varies with angle/position, so rotating/translating it sets OD continuously. Circular wheels cover ~270deg; step wheels give discrete ODs.
- **Optical behavior:** T=10^-OD(theta) where OD ramps continuously (e.g. 0.04-2.0 or 0.04-4.0) with rotation; spectrally flat (metallic). Step-variant gives quantized OD per slot.
- **Key params:** OD range (min..max); rotation/position->OD map; continuous vs stepped; clear aperture; spectral range
- **Add-on mapping:** FILTER filt_type='ND' with od animated/driven. NO new tracer code -- od is already an animatable FloatProperty. NEW (UI/realism only): is_variable bool + od_min/od_max range, and optionally a wheel_angle_deg driving od via a linear/log map, to model a motorized CV-ND and enforce realistic end-stops.
- **Real examples:** Thorlabs NDC-25C-2M/-4M (Ø25mm, OD 0.04-2.0/4.0, continuous, 270deg), NDM2/NDM4 cage CV-ND wheels (OD 0-2/0-4), NDC-100S step wheel; NDL-25 linear.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1393 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=NDM4

#### Linear variable bandpass / edgepass filter (wedge coating)
- **What it is:** A filter whose CWL or cut wavelength varies linearly with POSITION along the substrate -- translate it to tune the spectral band. Used as a cheap monochromator / hyperspectral element.
- **Optical behavior:** At any position it acts as a bandpass (or edge), but cut/CWL = f(x). ODavg>5 out-of-band, >94% in-band. Spatial-spectral coupling: where the beam hits sets the band.
- **Key params:** CWL(x) or cut(x) gradient (nm/mm); FWHM; position; ODavg; clear aperture
- **Add-on mapping:** FILTER filt_type='BP'/'LP'/'SP' with cut_lo/cut_hi (or cut) driven by element X-position. NEW: a linear_gradient (nm/mm) + reference cut so the chief-ray hit position sets the effective band -- this is the only filter where transmission depends on WHERE on the aperture the beam lands.
- **Real examples:** Thorlabs linear variable edgepass (ODavg>5, >94% pass) and linear variable bandpass; Delta/Semrock LVF.
- **Refs:** https://www.thorlabs.com/linear-variable-edgepass-filters

#### Fixed precision pinhole (mounted)
- **What it is:** A laser-drilled circular hole of fixed diameter in a thin stainless/black foil, mounted in a Ø1" cell. The fixed-aperture beam-cleaning / field-stop element.
- **Optical behavior:** Hard circular aperture: passes the central beam, blocks/clips the rest. At a focus it acts as a spatial filter (removes high spatial frequencies). Truncation produces an Airy/diffraction pattern downstream.
- **Key params:** pinhole DIAMETER (e.g. 5-1000um); circular; on-axis; substrate thickness
- **Add-on mapping:** PINHOLE, clear_aperture = pinhole RADIUS in mm (note: real specs give DIAMETER, so halve). _clip_T already gives Gaussian clip. NEW (Tier-2): clipped-beam diffraction / Airy regrowth and spatial-frequency cleanup at a focus -- current model only attenuates power, it does not 'clean' the beam.
- **Real examples:** Thorlabs P5D (5um), P10D (10+-1um), P25D (25+-2um), P50D, P100D...P1000 (Ø1" mounted, stainless); pinhole wheels P10H.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=P25D ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=14350

#### Adjustable iris diaphragm
- **What it is:** A multi-leaf mechanical iris whose circular aperture is continuously adjustable from ~1mm to ~25mm by a lever/ring. The general-purpose variable beam stop / aperture.
- **Optical behavior:** Continuously variable CIRCULAR hard aperture: sets beam diameter, blocks stray light, defines a field/aperture stop. Same clip physics as a pinhole but tunable and larger.
- **Key params:** min..max aperture diameter (e.g. 1-25mm); leaf count (affects polygon edge); circular; centration
- **Add-on mapping:** APERTURE, clear_aperture = current radius (mm), animatable. _clip_T already covers it. NEW (UI/realism): is_variable bool + ca_min/ca_max (e.g. 0.5-12.5mm radius) to model the mechanical travel and end-stops; optional leaf_count purely cosmetic for the mesh.
- **Real examples:** Thorlabs ID25 (Ø1-25mm, 14 leaves, OD 43.7mm, 6.6mm thick), ID12, ID8, SM1D12D (cage iris); Edmund 1-32mm iris.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=ID25 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=206

#### Adjustable slit (mechanical, two-blade)
- **What it is:** Two parallel blades forming a RECTANGULAR slit of continuously variable width (and sometimes height). The 1-D aperture for monochromators, spectrometers, and beam shaping.
- **Optical behavior:** Rectangular/anisotropic aperture: clips in ONE transverse direction (across-slit) and passes the orthogonal direction; produces 1-D (sinc) diffraction. Defines spectral resolution in a monochromator.
- **Key params:** slit WIDTH (0 to ~6mm, continuously variable, ~20um/0.5mm-rev), slit height, slit orientation angle
- **Add-on mapping:** NO faithful mapping today -- APERTURE/PINHOLE are CIRCULAR-only (_clip_T bakes in a 2-D circle). ADD aperture_shape='SLIT' + slit_width_mm, slit_height_mm, slit_angle_deg (NEW). _clip_T must branch to a 1-D Gaussian clip along the slit short axis. Until then it can only be faked as a tiny circular APERTURE.
- **Real examples:** Thorlabs VA100 (0-6mm wide, micrometer, SM05 bore), VA100C/M cage slit; mono entrance/exit slits (fixed width sets).
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1465 ; https://www.thorlabs.com/item/VA100

#### Spatial filter (pinhole at a lens focus, full assembly)
- **What it is:** An aspheric/objective lens focuses a beam through a matched precision pinhole at its focus; a second lens re-collimates. The pinhole rejects high spatial frequencies, yielding a clean Gaussian.
- **Optical behavior:** At the focus the pinhole truncates the focused spot's Airy pattern, BLOCKING high-spatial-frequency noise/structure and outputting a smooth, low-noise Gaussian. Pinhole diameter is matched to the Airy disc (~1.5x). Power loss + beam CLEANUP, not just attenuation.
- **Key params:** pinhole diameter (matched to focal-spot Airy size); input lens f and NA; pinhole-at-focus axial position; recollimation lens
- **Add-on mapping:** Composite: LENS (focusing, focal_length) + PINHOLE (clear_aperture = pinhole radius) at its focus + optional LENS (recollimate). The clip is handled by _clip_T. NEW (Tier-2) to capture the actual BENEFIT: a 'beam cleanup' flag that resets/idealizes the downstream q-parameter / marks the beam spatially filtered, since the current model only removes power and never improves beam quality.
- **Real examples:** Thorlabs KT310/KT311 spatial filter system (SM1Z z-translator + aspheric + pinhole, pinhole sold separately, pairs e.g. C230TMD lens + P10D pinhole).
- **Refs:** https://www.thorlabs.com/thorProduct.cfm?partNumber=KT310

---

## Detectors & Sources

> **Tracer / behavior model:** DETECTORS: the tracer already classifies DETECTOR/PHOTODIODE/POWER_METER/WAVEFRONT_SENSOR as TERMINAL absorbers (no outgoing ray) and writes meas_power; cameras/profilers reuse the scan._fringe_array raster (sensor_px, pixel_size_um, exposure, read_noise, well_depth) and WAVEFRONT_SENSOR reuses ao._aberr_at -> wf_rms. The ONE missing physics across every detector variant is SPECTRAL RESPONSE: add a detector_type (or head_kind) enum that selects a spectral model -- (a) responsivity curve for photodiodes (Si 320-1100 @0.65 A/W; Ge 800-1800 @0.85; InGaAs 800-1700 @1.05; APD/PMT QE-weighted with the same bands), or (b) a FLAT broadband gate for thermal heads (thermopile 0.19-20 um, pyroelectric 0.185-25 um). Implement as new params spec_lo_nm/spec_hi_nm + peak_responsivity_AW/responsivity_peak_nm, and gate meas_power: if ray.wl is outside [spec_lo,spec_hi] report ~0, else scale by the (interpolated) responsivity/QE -> a meas_photocurrent_A. Internal gain (PMT gain, APD M) and bias_mode are ELECTRICAL scale/noise factors with NO effect on the chief-ray power -- store them for labeling/readout but do not multiply the optical power by them. Add a damage_W (CW) / damage_J_cm2 (pulsed) per head with a warn flag when the incident power*aperture exceeds it -- this is a real, currently-missing safety axis (PMT/APD damage at uW; thermopile survives watts). clear_aperture already exists and already truncates the beam (_clip_T / _find_next aperture test) -- set it to each head's true active-area Ø so small InGaAs/APD dies vignette and large thermal discs do not. Pyroelectric/pulsed energy and PMT/APD photon-counting (HOM coincidences) are inherently time/quantum-domain and stay out of the chief-ray tracer -- pyro maps to a flat broadband absorber, photon-counting stays in the separate analytic quantum operator (scan.OPTICS_OT_quantum).

SOURCES: the emission loop already keys on SOURCE/FIBER_COLLIMATOR (or is_source) and reads wavelength, waist_um, pol_type/pol_angle/handedness, linewidth_nm (-> coherence_length_mm), and bandwidth_nm (-> a Gaussian-weighted set of mutually-incoherent lines = white-light packet). The TWO coherence axes the engine already supports are exactly what distinguishes every real source: TEMPORAL coherence = linewidth_nm/bandwidth_nm (HeNe/DFB/fiber/comb tiny -> long coherence; SLD/LED/lamp/supercontinuum large -> short), and SPATIAL coherence ~ waist_um/beam quality (laser/SLD/supercontinuum = small Gaussian waist; LED/lamp = large waist). So NO new physics is needed for sources -- the missing piece is a single NEW source_type enum (HENE, LASER_DIODE/DFB/ECDL, DPSS, FIBER, SLD, LED, LAMP, SUPERCONTINUUM, FREQ_COMB) whose ONLY job is to PRESET wavelength + linewidth_nm + bandwidth_nm + waist_um + pol_type from a real-part table, so users pick 'SLD' rather than hand-tuning bandwidth/waist to get short-temporal/high-spatial coherence. Key preset contrasts the engine already renders correctly: SLD vs LAMP = same broadband bandwidth but SLD keeps a small waist (high spatial coherence) while LAMP uses a large waist; supercontinuum = lamp-wide band + laser-small waist. FIBER_COLLIMATOR must gain waist_um (currently only wavelength) and derive it from focal length + fiber MFD so the collimated beam Ø is physical; its spectral/coherence character is INHERITED from the upstream source. Out-of-scope-but-note: pulsed/peak-power (supercontinuum, comb, pyro detection) and comb mode structure (f_rep, f_ceo) are not representable in a CW chief-ray model; add an emission_mode='CW'/'PULSED' tag + rep_rate_Hz for BOM/labeling and to drive the pyroelectric energy readout, but do not attempt time-domain propagation in the tracer.

#### Si photodiode (unbiased / biased / amplified)
- **What it is:** Silicon p-n or PIN junction. Reverse-bias widens the depletion region (faster, lower capacitance); 'amplified' adds an on-board transimpedance amp that outputs volts. The workhorse visible/NIR point detector.
- **Optical behavior:** Terminal absorber. Records optical power weighted by Si responsivity R(lambda) [A/W], which is ~0 below ~190 nm, rises to a ~0.5-0.65 A/W peak near 900-980 nm, and cuts off past ~1100 nm (bandgap). Outside 320-1100 nm it reads ~zero even with a beam present. Bias/amp do NOT change the optical reading in a ray model -- only bandwidth/saturation, which a chief-ray tracer ignores. So the only beam-facing behavior is: absorb + report power*spectral_gate*responsivity, and clip the beam to the active-area diameter.
- **Key params:** Active area Ø0.4-10 mm (e.g. 75.4 mm2 for PDA100A2), spectral band 320-1100 nm, peak responsivity ~0.65 A/W @970 nm, CW damage threshold (often unspecified for amplified; saturates electrically first), bandwidth (irrelevant to layout).
- **Add-on mapping:** Maps to PHOTODIODE (terminal). Add NEW params: detector_type enum (default 'SI'), spec_lo_nm / spec_hi_nm (320/1100), peak_responsivity_AW (~0.65), responsivity_peak_nm (~970), damage_W. clear_aperture already exists -> set to the active-area diameter so the tracer clips/vignettes. meas_power should be gated: if wl outside [spec_lo,spec_hi] report ~0; optionally scale by responsivity to a meas_photocurrent_A.
- **Real examples:** Thorlabs FDS100 (bare Si PD, Ø3.6 mm, 350-1100 nm); PDA100A2 (Si switchable-gain amplified, 320-1100 nm, 75.4 mm2, 11 MHz); DET36A2; PDA8A2 (fixed-gain biased).
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=3328 ; https://www.montana.edu/ddickensheets/courses/eele482/handouts/PDA100A2-Manual.pdf

#### Ge photodiode (amplified)
- **What it is:** Germanium junction detector. Bridges the Si/InGaAs gap; broad NIR response but high dark current (often TE-cooled).
- **Optical behavior:** Terminal absorber. Responsivity spans ~800-1800 nm, peak ~0.7-0.85 A/W near 1500 nm, dead outside that band. Behaves like the Si PD but with a redshifted spectral window; the only beam-facing difference is the spectral gate.
- **Key params:** Spectral band 800-1800 nm, peak responsivity ~0.85 A/W @1550 nm, active area Ø1-5 mm, higher dark current (noise, not layout).
- **Add-on mapping:** PHOTODIODE with detector_type='GE'; same NEW params as Si but spec_lo/hi = 800/1800, peak_responsivity ~0.85 @1550. No new behavior beyond the spectral gate added for Si.
- **Real examples:** Thorlabs FDG03 (Ge PD, 800-1800 nm, Ø3 mm); PDA30B2 (Ge amplified, 800-1800 nm); Hamamatsu B1919 series.

#### InGaAs photodiode (biased / amplified, switchable-gain)
- **What it is:** Indium-gallium-arsenide PIN detector for telecom/NIR. Standard cutoff ~1700 nm; 'extended' InGaAs reaches ~2600 nm.
- **Optical behavior:** Terminal absorber over 800-1700 nm (extended: 900-2600 nm), peak responsivity ~1.0-1.1 A/W near 1550 nm, blind in the visible. Same absorb-and-report behavior; distinguishing feature is the NIR/SWIR spectral window. Small active areas (Ø0.3-2 mm) make active-area clipping meaningful for unfocused beams.
- **Key params:** Spectral band 800-1700 nm (ext. to 2600), peak responsivity ~1.05 A/W @1550 nm, active area Ø0.3-2.0 mm (3.14 mm2 for PDA20CS2), CW damage threshold, switchable gain 1.5 kV/A-4.75 MV/A.
- **Add-on mapping:** PHOTODIODE with detector_type='INGAAS' (or 'INGAAS_EXT'); NEW: spec_lo/hi=800/1700 (or 900/2600), peak_responsivity ~1.05 @1550. clear_aperture = active-area Ø (often ~1-2 mm, smaller than the beam -> the existing _clip_T aperture truncation already models the vignetting).
- **Real examples:** Thorlabs FGA10 (bare InGaAs, Ø1 mm, 800-1700 nm); PDA20CS2 (InGaAs switchable-gain amplified, 800-1700 nm, Ø2.0 mm/3.14 mm2, 11 MHz-3 kHz); PDA10D2 (fixed-gain); extended: FD05D, PDA10DT-EC (1200-2600 nm).
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=PDA20CS2

#### Biased vs amplified vs unbiased (operating-mode axis)
- **What it is:** Not a sensor material but a wiring/packaging mode applied to any photodiode: photovoltaic (zero-bias, low-noise, slow), photoconductive (reverse-biased, fast), or fully amplified (integrated TIA, volts out).
- **Optical behavior:** ZERO effect on the optical chief-ray reading -- bias/amplification change electrical bandwidth, dark current, and saturation, none of which a geometric/Gaussian tracer represents. The beam is absorbed and power reported identically. Bandwidth only matters for time-resolved (HOM/heterodyne) work, which is out of the chief-ray model's scope.
- **Key params:** bias_mode enum (UNBIASED/BIASED/AMPLIFIED), bandwidth_Hz, transimpedance_gain (electrical-only).
- **Add-on mapping:** Optional cosmetic NEW param bias_mode on PHOTODIODE for labeling/BOM only; NO tracer behavior change. Document that the tracer treats all three identically (chief-ray power).
- **Real examples:** Same parts as above; e.g. FDS100 (unbiased), DET10A2 (biased), PDA100A2 (amplified).

#### CCD camera
- **What it is:** Charge-coupled-device 2-D imager: charge shuttled to a single readout amp. Low read noise, high uniformity, used as a spatial beam/fringe sensor.
- **Optical behavior:** Terminal area sensor. Samples the transverse intensity profile onto a pixel grid (records the 2-D field magnitude^2 across its sensor plane), not just total power. Already modeled by the add-on's fringe/scan path (sensor_px x sensor_px raster with exposure/read-noise/well-depth -> shot + read noise + saturation). Si-based -> ~350-1000 nm spectral window. The defining behavior vs a power meter is that it preserves the spatial pattern (fringes, spot, M^2).
- **Key params:** Pixel pitch (pixel_size_um), sensor resolution (sensor_px), well depth (sensor_well_depth), read noise (sensor_read_noise), exposure (sensor_exposure), spectral band ~350-1000 nm (Si).
- **Add-on mapping:** DETECTOR (terminal) + the existing scan/fringe raster. NEW: sensor_tech enum (CCD/CMOS) and detector_type='SI' spectral gate as above. The camera-noise model already lives in scan._fringe_array; only the spectral window gate is missing.
- **Real examples:** Thorlabs 340xxxx CCD line; PCO pco.edge (sCMOS, but CCD-class imaging); historical Apogee/SBIG astronomy CCDs. (Thorlabs has largely moved to CMOS.)

#### CMOS camera (incl. beam-profiler camera)
- **What it is:** Active-pixel-sensor imager: per-pixel amplifier, rolling/global shutter. Now dominant for beam profiling and machine vision.
- **Optical behavior:** Same terminal area-sensor behavior as CCD -- rasters the transverse intensity to a pixel grid. Differs only in noise statistics (higher read noise historically, but global-shutter sCMOS rivals CCD) and frame rate, neither of which changes the chief-ray pattern. A beam-profiler camera adds a calibrated ND filter wheel (handled as an inline ATTENUATOR/FILTER) and software M^2/centroid fitting.
- **Key params:** Same as CCD: pixel pitch, resolution, well depth, read noise, exposure; Si spectral band 350-1100 nm; built-in ND wheel (OD steps).
- **Add-on mapping:** DETECTOR with sensor_tech='CMOS'. Reuses the entire existing scan/fringe pipeline. NEW only: sensor_tech enum + spectral gate. A profiler's ND wheel is best modeled as a separate inline ATTENUATOR (od) so the existing _transmission path handles it.
- **Real examples:** Thorlabs BC207VIS CMOS beam profiler (350-1100 nm, Ø20 um-Ø7.0 mm beams, 6-position ND wheel, to 1 W); Zelux/Kiralux CMOS cameras; CS165MU.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=BC207VIS

#### Thermopile power-meter head
- **What it is:** Stacked thermocouples on an absorbing disc; measures the temperature rise from absorbed light. Flat, wavelength-independent broadband absorber.
- **Optical behavior:** Terminal absorber. Reports total absorbed power with an almost FLAT spectral response across a huge band (0.19-20 um), unlike a photodiode head. Does not saturate (good for high CW power and pulses). Slow (seconds). For the chief-ray model: absorb, report power with ~unity flat spectral gate over its band, no responsivity roll-off. Large aperture (Ø10-50 mm) so essentially no active-area clipping.
- **Key params:** Spectral band 0.19-20 um (flat), power range mW-100s W, large aperture Ø10-50 mm, very high CW + energy damage threshold, slow time constant.
- **Add-on mapping:** POWER_METER with detector_type='THERMOPILE'. NEW: head_kind enum (PHOTODIODE/THERMOPILE/PYROELECTRIC) drives the spectral model -- THERMOPILE uses a FLAT gate over [spec_lo,spec_hi] (~190-20000 nm) instead of a responsivity curve. clear_aperture = large head Ø.
- **Real examples:** Thorlabs S401C (thermal head, 0.19-20 um, 10 uW-1 W); S302C (0.19-25 um, to 2 W); S322C (to 200 W). Ophir/Gentec thermopile discs.
- **Refs:** https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=3333

#### Photodiode power-meter head
- **What it is:** Calibrated photodiode behind a diffuser/aperture in a sensor head, read by a console (PMxxx). Sensitive (down to nW) but spectrally non-flat -> needs a wavelength-correction setting.
- **Optical behavior:** Terminal absorber. Reports power with the photodiode's responsivity curve, but the console applies a user-entered wavelength correction so the displayed power is accurate at the set lambda. Spectral window Si (400-1100 nm) or InGaAs/Ge for IR heads. Behavior identical to a bare photodiode plus a 'set wavelength' calibration knob. Saturates and has a lower CW damage threshold than a thermopile.
- **Key params:** Spectral band 400-1100 nm (Si head), power range 50 nW-50 mW, active aperture Ø9.5 mm, calibration wavelength setting, modest CW damage threshold.
- **Add-on mapping:** POWER_METER with head_kind='PHOTODIODE' + detector_type='SI'/'GE'/'INGAAS'. NEW: cal_wl_nm (the console's set-wavelength). Spectral gate as for the bare photodiode. This is the variant the existing POWER_METER element most directly already represents -- it just needs the spectral band + cal_wl.
- **Real examples:** Thorlabs S120C (Si photodiode head, 400-1100 nm, 50 nW-50 mW, Ø9.5 mm); S121C (higher power); S122C; S132C (Ge/InGaAs, 700-1800 nm).
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=S120C

#### Pyroelectric energy/power head
- **What it is:** Ferroelectric crystal that outputs a voltage pulse proportional to the rate of temperature change -- responds to CHANGING flux, i.e. pulses.
- **Optical behavior:** Terminal absorber for PULSED light only: reports per-pulse energy (J), not CW power (a CW beam gives no steady signal). Broadband flat (black coating, 0.185-25 um). For a chief-ray DC tracer this is essentially a flat broadband absorber that should report ENERGY given a pulse rep-rate, or be flagged as 'pulsed only'. Damage governed by energy density (J/cm2), not CW W.
- **Key params:** Spectral band 0.185-25 um (flat), energy range uJ-500 mJ, max pulse rate ~Hz-kHz, energy density damage threshold (J/cm2), large aperture Ø11-45 mm.
- **Add-on mapping:** POWER_METER (or PHOTODIODE) with head_kind='PYROELECTRIC'. NEW: measures_energy bool + damage_J_cm2 + pulse-mode flag. Flat spectral gate like the thermopile. The tracer (CW) can't time-resolve pulses, so the honest mapping is: treat it as a flat broadband absorber, report a per-pulse energy if a rep-rate is supplied, else label 'pulsed'.
- **Real examples:** Thorlabs ES120C (pyroelectric, 0.185-25 um, 500 mJ, Ø20 mm, 30 Hz); ES111C (Ø11 mm); ceramic-coated ES220C/ES245C for high damage threshold. Ophir PE series.

#### Photomultiplier tube (PMT)
- **What it is:** Vacuum tube: photocathode + dynode chain. Single-photon-sensitive, gain >1e6-1e7, fast (ns). Used for weak fluorescence, photon counting.
- **Optical behavior:** Terminal absorber with enormous internal gain -- but in a power/chief-ray model the gain is an electrical scale factor, so the optical behavior is just 'absorb + report, gated by the photocathode spectral response'. Photocathode quantum efficiency defines the band (e.g. bialkali 185-900 nm, multialkali to ~900 nm, GaAs to ~1700 nm) and a peak QE ~25-40% near 400 nm. Small active area; easily damaged/saturated by strong light (this is a real damage axis: max anode current / CW power is tiny).
- **Key params:** Spectral band 185-900 nm (bialkali) up to 1700 nm (GaAs cathode), gain 1e6-1e7, peak QE ~25-40%, max rated input power VERY low (saturation/damage), response time ~1.4 ns.
- **Add-on mapping:** DETECTOR or new detector_type='PMT' on PHOTODIODE. NEW: gain (electrical), quantum_efficiency, and a LOW damage_W (saturation). Spectral gate by photocathode band. Optical behavior = terminal absorb with QE-weighted spectral gate; gain is reported, not applied to the chief-ray power.
- **Real examples:** Thorlabs PMTSS2 module (185-900 nm, gain >1e7, 1.4 ns, needs TIA60 amp); PMT1001/PMT2101; Hamamatsu H10721 series.
- **Refs:** https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=2909

#### Avalanche photodiode (APD) / SPAD
- **What it is:** Reverse-biased photodiode run near breakdown so carriers avalanche -> internal gain (M ~10-100 linear APD; SPAD = Geiger-mode single-photon counting). Semiconductor analog of a PMT.
- **Optical behavior:** Terminal absorber with internal multiplication M. Like the PMT, the optical chief-ray behavior is just absorb + QE-weighted spectral gate; M is an electrical/noise factor (excess-noise factor F). Si APD: 400-1000 nm; InGaAs APD: 900-1700 nm. Temperature-stabilized bias keeps M constant. Saturates/damages at low optical power.
- **Key params:** Spectral band 400-1000 nm (Si) / 900-1700 nm (InGaAs), multiplication M ~10-100, active area Ø0.2-1.5 mm, low damage/saturation power, M-stability vs temperature.
- **Add-on mapping:** PHOTODIODE with detector_type='APD_SI'/'APD_INGAAS'. NEW: gain (M), damage_W (low). Same QE-gated terminal absorb as PMT. SPAD/photon-counting (HOM-style coincidences) is beyond the chief-ray tracer -- handled by the separate analytic quantum operator (scan.OPTICS_OT_quantum).
- **Real examples:** Thorlabs APD130A2 (Si APD, temp-compensated M, integrated thermistor); APD410A2; APD440 (InGaAs); Excelitas SPCM single-photon counters.
- **Refs:** https://www.thorlabs.com/free-space-si-avalanche-photodetectors

#### Shack-Hartmann wavefront sensor
- **What it is:** Microlens (lenslet) array in front of a CMOS sensor: each lenslet focuses its sub-aperture to a spot; spot displacement = local wavefront slope -> reconstruct Zernike modes.
- **Optical behavior:** Terminal modal sensor. Does NOT measure power or a pattern -- it measures the WAVEFRONT (Zernike coefficients) of the incident beam. This is exactly what the add-on's WAVEFRONT_SENSOR already does: it reads the ray's accumulated aberr vector and reports wf_rms. Dynamic range and accuracy are set by lenslet pitch / focal length and the number of lenslets across the pupil.
- **Key params:** Lenslet pitch 150 or 300 um, lenslet focal length, number of lenslets (modal resolution), spectral band of the CMOS (~300-1100 nm), max measurable RMS / dynamic range, clear aperture.
- **Add-on mapping:** WAVEFRONT_SENSOR (already terminal, already reads Zernike residual via ao._aberr_at and writes wf_rms). NEW (refinement only): lenslet_pitch_um, n_lenslets, wfs_dynamic_range_waves to bound the reconstructed modes; spectral band gate. Core behavior already correct.
- **Real examples:** Thorlabs WFS40-14AR (CMOS Shack-Hartmann, exchangeable MLA, 150/300 um pitch); WFS30-5C; WFS20. Imagine Optic HASO.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=5287

#### Beam profiler (camera / scanning-slit)
- **What it is:** Measures the transverse intensity distribution to extract beam diameter, centroid, ellipticity, and M^2. Camera-type (2-D CMOS) or scanning-slit/knife-edge (1-D mechanical scan).
- **Optical behavior:** Terminal area sensor that reports the SPATIAL profile, identical in behavior to a CMOS camera for the tracer (raster the transverse |field|^2). The defining outputs (1/e^2 diameter, centroid, M^2) are post-processing of that raster. Scanning-slit type integrates the beam along a moving slit -> 1-D profiles in X and Y; still just a sampling of the same intensity field.
- **Key params:** Spectral band 350-1100 nm (Si camera) / wider for slit-scan with appropriate PD, measurable beam size Ø20 um-Ø7 mm, pixel pitch, built-in ND wheel, damage/power limit (~1 W with ND).
- **Add-on mapping:** DETECTOR (camera profiler) reusing the scan/fringe raster, with a flag profiler=True so the readout reports w_mm/centroid (the tracer already computes Gaussian w_mm per segment). Scanning-slit -> same terminal raster, just a different readout. NEW: sensor_tech, spectral gate, profiler bool.
- **Real examples:** Thorlabs BC207VIS (CMOS camera profiler, 350-1100 nm, Ø20 um-7 mm); BP209 (scanning-slit, two orthogonal slits); BP109.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=BC207VIS

#### HeNe laser (gas)
- **What it is:** Helium-neon gas laser. Highly stable, narrow-linewidth red (632.8 nm) reference source; also 543/594/612/1523 nm lines.
- **Optical behavior:** SOURCE. Emits a single narrow line (632.8 nm), near-ideal temporal coherence (linewidth ~1 GHz -> coherence length ~0.2-0.3 m, or single-mode stabilized to many meters), excellent TEM00 Gaussian beam, linearly (or random) polarized. This is the canonical add-on default (wavelength=632.8). High spatial + temporal coherence -> strong interference fringes.
- **Key params:** Wavelength 632.8 nm (fixed), linewidth ~1.5 GHz (~1.3e-3 nm) -> coherence ~0.2-0.3 m, beam waist ~0.3-0.5 mm, M^2~1, power 0.5-35 mW, linear or random polarization.
- **Add-on mapping:** SOURCE with NEW source_type='HENE'. Sets wavelength=632.8, a SMALL linewidth_nm (~0.0013) -> long coherence via the existing coherence_length_mm path, bandwidth_nm=0, pol_type='LINEAR'. waist_um already exists. NEW source_type can preset linewidth/coherence so the user doesn't hand-tune.
- **Real examples:** Thorlabs HNL100LB (632.8 nm, 1.0 mW, linear); HNL210LB (2.0 mW); HNL150R (random pol). Already in the catalog.
- **Refs:** library.py HNL100LB/HNL210LB entries

#### Laser diode (edge-emitter / collimated module)
- **What it is:** Semiconductor diode laser. Compact, efficient, wavelength set by the bandgap; raw output is astigmatic/elliptical and divergent, so it is usually collimated.
- **Optical behavior:** SOURCE. Single line (e.g. 405/450/635/780/1550 nm) but BROADER linewidth than a HeNe (Fabry-Perot multimode ~nm; DFB/external-cavity ~kHz-MHz). Coherence length ranges from sub-mm (FP multimode) to >100 m (DFB/ECDL). Raw beam is elliptical/astigmatic with high divergence; a 'collimated module' fixes this to a near-Gaussian beam. Linearly polarized. So the key tracer-visible knobs are wavelength + coherence (linewidth) + waist.
- **Key params:** Wavelength (per part, 375-1650 nm), linewidth 1 MHz (DFB) to ~1 nm (FP multimode) -> coherence sub-mm to >100 m, waist/beam Ø (after collimation ~0.5-1 mm), elliptical M^2, linear polarization, power mW-W.
- **Add-on mapping:** SOURCE with source_type='LASER_DIODE' (or 'DFB'/'ECDL' for narrow). Presets wavelength + linewidth_nm (broad for FP, tiny for DFB) -> coherence. NEW optional: beam_ellipticity / astigmatism if the model ever leaves the symmetric-Gaussian assumption (currently single waist_um only).
- **Real examples:** Thorlabs CPS635 (635 nm collimated diode module, 1.2 mW -- already in catalog); L405P20; DFB: DFB1550 (kHz linewidth); ECDL for narrow line.
- **Refs:** library.py CPS635 entry

#### DPSS laser (diode-pumped solid-state)
- **What it is:** Diode-pumped crystal (Nd:YAG/Nd:YVO4) laser, often intracavity-doubled (e.g. 1064 -> 532 nm green). Good beam quality, moderate-to-narrow linewidth.
- **Optical behavior:** SOURCE. Single line at the lasing/doubled wavelength (532, 561, 1064 nm typical), narrow linewidth (single-longitudinal-mode units <1 MHz -> coherence >100 m; multimode units broader). Clean TEM00 Gaussian, linearly polarized, higher power than a bare diode. Tracer-wise: like a HeNe but at the DPSS wavelength with part-dependent coherence.
- **Key params:** Wavelength 532/561/1064 nm (etc.), linewidth <1 MHz (SLM) to GHz (multimode), waist ~0.3-1 mm, M^2~1.1, power mW-W, linear polarization.
- **Add-on mapping:** SOURCE with source_type='DPSS'. Presets wavelength (e.g. 532), small linewidth_nm, linear pol. No new behavior beyond the source_type preset table -- reuses wavelength/waist_um/linewidth.
- **Real examples:** Laser Quantum gem 532; CNI MGL-III-532; Coherent Verdi (532 nm); Thorlabs DJ532 modules.

#### Fiber laser
- **What it is:** Gain in a rare-earth-doped (Yb/Er/Tm) fiber, often FC/APC pigtailed. Excellent beam quality, can be very narrow-linewidth (single-frequency) or broadband (mode-locked).
- **Optical behavior:** SOURCE. Single-frequency fiber lasers have kHz linewidths -> coherence >100 km (effectively ideal). Output is a perfect Gaussian from the fiber mode, typically delivered via a collimator. Tracer-wise: ideal-coherence Gaussian source at 1064/1550 nm; for mode-locked combs see frequency comb below.
- **Key params:** Wavelength 1030-2000 nm (Yb/Er/Tm), linewidth ~kHz (SF) -> coherence >100 km, waist set by output collimator, M^2~1, polarization PM or random, power mW-kW.
- **Add-on mapping:** SOURCE (or FIBER_COLLIMATOR if delivered via fiber) with source_type='FIBER'. linewidth_nm ~0 -> the existing coherence_length_mm clamps to the 1e12 cap (already handled). Reuses wavelength/waist.
- **Real examples:** NKT Koheras BASIK (single-frequency, kHz, 1550 nm); IPG YLR series; Thorlabs fiber laser modules.

#### Superluminescent diode (SLD)
- **What it is:** Amplified spontaneous emission in a diode -- high spatial coherence but LOW temporal coherence (broad spectrum). The standard OCT source.
- **Optical behavior:** SOURCE that is the inverse of a laser on the coherence axis: a Gaussian-quality beam (diffraction-limited, like a laser) but with a WIDE optical bandwidth (tens of nm) -> very short coherence length (~10-50 um). In the tracer this means a near-perfect spatial beam with bandwidth_nm set large (the existing broadband path already discretizes a Gaussian spectrum into mutually-incoherent lines) -> white-light-like fringe packets that decorrelate within microns of path difference. Distinct from a lamp because the SPATIAL coherence stays high.
- **Key params:** Center wavelength 770-1685 nm, 3 dB bandwidth ~tens of nm (e.g. 33-90 nm), coherence length ~5-50 um, diffraction-limited beam, FC/APC pigtail, power mW.
- **Add-on mapping:** SOURCE or FIBER_COLLIMATOR with source_type='SLD'. KEY: set bandwidth_nm large (-> short coherence via the existing broadband spectrum path) BUT keep waist_um small/Gaussian (high spatial coherence). This is exactly the lever that distinguishes SLD from a lamp -- both broadband, but the lamp also has poor spatial coherence (large waist / no defined beam).
- **Real examples:** Thorlabs SLD1550S-A40 (1550 nm, 33 nm BW, 40 mW, FC/APC); S5FC1550S-A2 (benchtop, 90 nm BW); Superlum BroadLighters.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=SLD1550S-A40

#### LED
- **What it is:** Light-emitting diode: spontaneous emission, moderate bandwidth (~20-50 nm), broad emission angle, low spatial coherence. Fiber-coupled or free-space mounted LEDs are common alignment/illumination sources.
- **Optical behavior:** SOURCE with both low temporal coherence (bandwidth ~tens of nm -> coherence ~10-30 um) AND low spatial coherence (extended emitter, large divergence -> no clean Gaussian). For the tracer: broadband (bandwidth_nm set) plus a large waist_um / poor M^2 so it does not form sharp fringes. Effectively a small, somewhat-directional version of the broadband lamp.
- **Key params:** Center wavelength 365-940 nm (per die), bandwidth ~20-50 nm FWHM, coherence ~10-30 um, large emitting area / high divergence (low spatial coherence), unpolarized, power mW-W.
- **Add-on mapping:** SOURCE with source_type='LED'. bandwidth_nm ~tens (broadband path) + LARGE waist_um + pol_type='UNPOL' (existing). NEW spatial_coherence / M2 param would make the 'poor beam' explicit, but a large waist_um approximates it within the symmetric-Gaussian model.
- **Real examples:** Thorlabs M530L4 (530 nm mounted LED, ~33 nm BW); fiber-coupled MxxxFx series; LED1B.

#### Broadband lamp (white-light / arc / filament)
- **What it is:** Thermal or arc lamp (tungsten-halogen, Xe arc, D2): very broad spectrum (hundreds of nm), spatially incoherent extended source. Used for spectroscopy/illumination and white-light interferometry.
- **Optical behavior:** SOURCE with the LOWEST coherence on both axes: huge bandwidth (-> coherence ~1-5 um) and a large incoherent emitting area (no Gaussian beam, fills any aperture). In the tracer: maximal bandwidth_nm (broadband spectral set), very large waist_um, unpolarized -> essentially no spatial interference, white-light fringes only at near-zero path difference.
- **Key params:** Spectral range 200-2500 nm (D2/halogen/Xe), bandwidth hundreds of nm, coherence ~1-5 um, large incoherent source area, unpolarized, radiance-limited.
- **Add-on mapping:** SOURCE with source_type='LAMP'. Maximal bandwidth_nm + very large waist_um + pol_type='UNPOL'. Distinguished from SLD/LED purely by HOW LARGE the bandwidth and waist are (worst spatial+temporal coherence). NEW: a named source_type preset table makes 'lamp vs SLD vs LED' a one-click choice instead of manual bandwidth/waist tuning.
- **Real examples:** Thorlabs SLS201L (stabilized tungsten, 360-2600 nm); SLS204 (Xe); D2 deuterium lamps; Energetiq EQ-99 LDLS.

#### Supercontinuum source
- **What it is:** Pump a photonic-crystal fiber with high-peak-power pulses -> nonlinear spectral broadening to a white-light continuum that is LASER-like (diffraction-limited, high spatial coherence) but spans an octave.
- **Optical behavior:** SOURCE that is broadband (450-2400 nm, even to 4.4 um MIR) yet SPATIALLY coherent like a laser (single transverse mode out of the PCF). So in the tracer: very large bandwidth_nm (short temporal coherence) BUT small Gaussian waist_um (high spatial coherence) -- same coherence signature as an SLD but over a far wider band, and usually pulsed. Often spectrally sliced by a tunable filter (modeled as a downstream FILTER/BP).
- **Key params:** Spectral range 450-2400 nm (vis-NIR) or 1.1-4.4 um (MIR), single transverse mode (M^2~1), pulsed (ps-fs, MHz rep), high spatial coherence + low temporal coherence, watts of total power.
- **Add-on mapping:** SOURCE with source_type='SUPERCONTINUUM'. Large bandwidth_nm + small Gaussian waist_um (the SLD lever, but wider band). Spectral slicing -> add a downstream FILTER (filt_type='BP', cut_lo/hi). NEW source_type preset; pulsed nature is out of chief-ray scope (note in tracer_notes).
- **Real examples:** NKT SuperK COMPACT (450-2400 nm); SuperK FIANIUM; SuperK MIR (1.1-4.4 um); often paired with SuperK SELECT/VARIA tunable filters.
- **Refs:** https://www.nktphotonics.com/products/supercontinuum-white-light-lasers/superk-compact/

#### Frequency comb
- **What it is:** Mode-locked laser whose spectrum is a comb of equally spaced, mutually phase-locked narrow lines (modes). Each tooth is kHz-narrow; the envelope can span an octave.
- **Optical behavior:** SOURCE that is simultaneously broadband (octave envelope) AND ultra-coherent (each tooth kHz, coherence >100 km; the comb as a whole is phase-stable). A chief-ray geometric/Gaussian tracer cannot represent the comb structure or per-tooth phase locking -- it would treat the envelope as a broadband Gaussian (like a supercontinuum) and lose the metrology content. Honest mapping: a coherent broadband Gaussian; the comb-specific physics (f_rep, f_ceo, beat notes) is beyond scope.
- **Key params:** Envelope 500-2200 nm (octave for f-2f), line spacing = f_rep (~100 MHz-10 GHz), per-line linewidth ~kHz, f_ceo offset, diffraction-limited beam, pulsed (fs).
- **Add-on mapping:** SOURCE with source_type='FREQ_COMB'. Modeled as a coherent broadband Gaussian (small waist + moderate bandwidth + long coherence). NEW source_type preset; explicit note that comb-mode structure / f_rep / f_ceo are NOT modeled by the chief-ray tracer (metrology out of scope).
- **Real examples:** Menlo Systems FC1500; Toptica DFC; NIST fiber combs (~22 Hz comb linewidth reported); Thorlabs/Octave Photonics microcombs.
- **Refs:** https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=918079

#### Fiber collimator (FC/APC, FC/PC)
- **What it is:** A lens (aspheric or GRINlens) at the tip of a fiber that converts the diverging fiber-mode output into a collimated free-space beam. FC/APC = 8deg angle-polished ferrule (kills back-reflections); FC/PC = flat polish.
- **Optical behavior:** SOURCE/launcher: re-emits whatever the fiber carries as a clean collimated Gaussian whose waist and divergence are set by the collimator focal length and the fiber mode-field diameter (beam Ø ~ 2*f*MFD/(pi*w_fiber)). The wavelength/coherence/polarization are inherited from the upstream source (laser, SLD, comb). So the collimator itself only sets the WAIST (and clear aperture); the spectral/coherence character comes from the connected source.
- **Key params:** Design wavelength (AR coating band), focal length 2-40 mm (e.g. F810APC f=36.18 mm), output beam Ø (e.g. 7.5 mm), connector FC/APC vs FC/PC, NA, clear aperture.
- **Add-on mapping:** FIBER_COLLIMATOR (already a source type in the tracer). Currently has only wavelength. NEW: waist_um (derive from f + MFD so the output beam Ø is physical) -- the tracer already uses waist_um for SOURCE, so FIBER_COLLIMATOR should expose it too. Optional source_type inherited from upstream. connector type (FC/APC vs FC/PC) is cosmetic/BOM, but APC's no-back-reflection behavior pairs with the ISOLATOR concept.
- **Real examples:** Thorlabs F810APC-635 (FC/APC, 635 nm, f=36.18 mm, 7.5 mm beam -- already in catalog); F220APC-1550; TC18APC-980 (triplet); RC-series reflective collimators.
- **Refs:** library.py F810APC635 entry

---

## Nonlinear Crystals, Isolators, Etalons & Modulators

> **Tracer / behavior model:** HOW THE TRACER SHOULD MODEL THESE FOUR CATEGORIES (chief-ray, segment-spawning architecture as in trace_scene/_step):

1) CRYSTAL (promote from the elements_generic.crystal() DETECTOR hack to a real element_type). It is a beam-SPAWNING element like BEAMSPLITTER, not a terminator. Behavior keyed by a NEW chi2_process enum:
   - SHG/THG/SFG: emit ONE collinear child at out_wl = pump_wl/harmonic_order, power = pump.power * conv_eff; attenuate the through pump by (1 - conv_eff). For Type I rotate the child evec/jones by 90 deg; for Type II weight conv_eff by the input polarization projection onto the (o,e) axes (max at 45 deg). Offset the child laterally by walkoff_deg (chief ray can stay collinear and just carry the walk-off as a displacement annotation).
   - DFG/OPO: emit TWO collinear children (signal_wl, idler_wl) with energy conservation 1/out1 + 1/out2 = 1/pump (in wavenumbers); pump passes ~undepleted.
   - SPDC: emit TWO children on a cone at +/- cone_half_angle off pump.dir, at the down-converted wavelengths, orthogonal pols for Type II (this formalizes bell_entanglement.py / hong_ou_mandel.py). conv_eff ~ 0 for the pump (it passes through).
   Conversion efficiency model: eta = min(1, eta0 * sinc^2(dk*L/2)) where dk is set by phase-match condition; drive dk from pm_angle (critical PM) OR temperature_C (NCPM/QPM) OR poling_period_um (QPM: dk = dk_bulk - 2*pi/Lambda). Keep it a smooth scalar 0..1, no full coupled-wave integration needed at chief-ray fidelity.

2) ISOLATOR (already exists, port-direction gate is the right skeleton). Add: (a) forward beam gets a fixed +45 deg NON-RECIPROCAL polarization rotation on evec/jones; (b) backward beam is NOT hard-absorbed but attenuated by 1/extinction (reuse the extinction param, now sourced from isolation_dB); (c) forward insertion loss <1 via a transmission factor; (d) narrowband: scale isolation by a Lorentzian/Gaussian around design_wl. Crucially the rotation is the same sign in both directions (that non-reciprocity is what a reciprocal Jones waveplate can NOT reproduce -- it must be applied by the isolator handler explicitly, keyed to propagation direction relative to the IN->OUT axis).

3) CAVITY (already correct: physics.airy_transmission(wl, cavity_spacing_mm, reflectivity)). Upgrades: (a) also spawn the complementary REFLECTED beam with power*(1-T) (currently only transmit is emitted -- needed for ring-down / PDH-reflection examples); (b) pass refractive_index into airy_transmission (currently defaults n=1); (c) honor incidence angle via the cos(theta) term already in the formula; (d) optionally expose derived FSR=c/2nL, finesse=pi*sqrt(R)/(1-R), FWHM=FSR/finesse as read-only UI. Etalon vs scanning-FP vs reference-cavity are the SAME handler at different parameter regimes (thin+moderate-R, swept-L, large-L+R~0.9999); confocal geometry just switches FSR to c/4nL. Reference-cavity transverse stability ties into the existing ABCD/Gaussian-q lens machinery via mirror_roc_mm (g = 1 - L/RoC).

4) MODULATOR (NEW element_type) with a NEW modulator_type enum {EOM_PHASE, EOM_AMPLITUDE, POCKELS, AOM, KERR}. Two distinct behavior families:
   - COLLINEAR (POCKELS, EOM_PHASE, EOM_AMPLITUDE, KERR): NO geometric deflection, reuse existing kernels. Pockels/Kerr = voltage-controlled WAVEPLATE: compute retardance_deg from drive_voltage (Pockels: 180*V/Vpi linear; Kerr: ~ kerr_const*L*V^2 quadratic), then apply the EXISTING M_waveplate(retardance_deg, fast_axis_deg). Phase EOM = pure phase on evec/jones (reuse with_phase), power unchanged; sidebands are a frequency-domain annotation only. Amplitude EOM = voltage-controlled attenuator, T = sin^2(pi*V/2Vpi), reuse the FILTER/ATTENUATOR transmission path.
   - DEFLECTING (AOM): reuse the GRATING kernel (_diffract) with a moving-grating period = v_sound/f_RF. Emit a first-order child deflected by theta = order*lambda*f_RF/v_sound, power = power*diff_eff (diff_eff set by RF power), plus the zeroth order straight at power*(1-diff_eff). Tag the first order with a frequency shift delta_f = f_RF (carried as a per-segment annotation for heterodyne/beat-note examples; the chief-ray wavelength itself is unchanged at this fidelity).

GENERAL: all four categories are best modeled as smooth, energy-conserving scalar/Jones transforms plus (for CRYSTAL/AOM/CAVITY-reflection/SPDC) additional spawned child rays -- exactly the same _child()/stack mechanism BEAMSPLITTER and GRATING already use. The only genuinely NEW physics primitives are: (a) a phase-match/conversion-efficiency scalar for CRYSTAL, (b) the non-reciprocal 45-deg rotation for ISOLATOR, and (c) the V->retardance and V->transmission and RF->deflection param maps for MODULATOR -- none require a new wave-propagation engine, just new param-to-existing-kernel adapters. NEW params to add to OpticsProps: chi2_process, pm_type, pm_angle_deg, pm_tuning, temperature_C, poling_period_um, walkoff_deg, conv_eff, cone_half_angle_deg, signal_wl, idler_wl (CRYSTAL); isolation_dB, insertion_loss_dB (ISOLATOR); mirror_roc_mm, cavity_geometry (CAVITY); modulator_type, v_pi, drive_voltage, kerr_const, rf_freq_MHz, sound_velocity_m_s, diff_efficiency, diff_order, mod_freq_MHz (MODULATOR). NEW element_type tags: 'CRYSTAL' and 'MODULATOR' (ISOLATOR and CAVITY already exist).

#### BBO (beta-barium borate) -- Type I SHG / THG crystal
- **What it is:** Negative uniaxial nonlinear crystal, the workhorse for UV/visible second- and third-harmonic generation and for pulsed lasers. Very broad transparency (189 nm to 3.5 um), high damage threshold, large birefringence, but small deff (~2 pm/V) and notable spatial walk-off. Type I means both fundamental photons share one polarization (o+o -> e for negative uniaxial), so e.g. 800 nm o-pol pump -> 400 nm e-pol SHG.
- **Optical behavior:** FREQUENCY: emits a co-propagating new beam at 2*omega (SHG) or 3*omega (THG via cascaded SHG+SFG); intensity scales as I_2w ~ deff^2 L^2 I_w^2 sinc^2(dk L/2). DIRECTION: harmonic exits collinear with pump but the extraordinary wave Poynting vector walks off by rho ~ 3-5 deg (lateral separation = L*tan(rho)). POLARIZATION: Type I rotates the harmonic 90 deg vs the fundamental (o-pol pump -> e-pol harmonic). PHASE: requires phase-matching dk=0 set by crystal cut angle theta_pm and tuned by angle/temperature; bandwidth narrow (acceptance ~ a few nm). Pump is depleted, not absorbed.
- **Key params:** chi2_process = SHG/THG; crystal cut angle theta_pm (deg); phase_match_type = I; pump_wl_in -> harmonic_wl_out (= wl/2 or wl/3); deff (pm/V); length L (mm); walkoff_angle rho (deg); conversion_efficiency eta (fraction); acceptance bandwidth (nm); both polarization in/out.
- **Add-on mapping:** MAP TO NEW element_type 'CRYSTAL' (promote the current elements_generic.crystal() builder out of its DETECTOR hack). Reuse: refractive_index, wavelength (pump), clear_aperture, design_wl (phase-match wl). NEW params: chi2_process EnumProperty {SHG,THG,SFG,DFG,OPO,SPDC,NONE}; pm_type EnumProperty {TYPE_I,TYPE_II}; pm_angle_deg (theta cut); walkoff_deg; conv_eff (0..1). Tracer behavior: spawn a child ray at out_wl = wl/harmonic_order, power = ray.power*conv_eff, direction = ray.dir laterally offset by walkoff (or collinear for the chief ray), and rotate its evec/jones 90 deg for Type I; attenuate the through (pump) beam by (1-conv_eff). This replaces 'terminate on DETECTOR + separate manual signal source'.
- **Real examples:** Thorlabs NLC04: O1in mounted beta-BBO, 0.50 mm thick, Type I SHG, ~1300 nm fundamental -> 650 nm. Thorlabs BBO SHG group (900-1300 nm fund / 450-650 nm SHG), 5x5 mm apertures, 0.5-3 mm thick. Shalom-EO / United Crystals 5x5x0.5 mm Type I. Bandwidth ~189-3500 nm transparency; deff ~ 2.0 pm/V; walk-off ~ 3-5 deg at 800 nm.
- **Refs:** https://www.thorlabs.com/item/NLC04 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=15444 ; https://unitedcrystals.com/BBOProp.html ; https://www.shalomeo.com/Laser-Crystals-and-Components/Nonlinear-Crystals/BBO-Crystals

#### BBO -- SPDC (Type I / Type II) entangled-photon source
- **What it is:** Same beta-BBO crystal pumped with a UV beam (e.g. 405 nm) but run in reverse of SHG: one pump photon spontaneously splits into two longer-wavelength photons (signal + idler) conserving energy and momentum. The add-on's example bell_entanglement.py / hong_ou_mandel.py already model this scenario by hand with separate sources.
- **Optical behavior:** FREQUENCY: pump omega_p -> signal omega_s + idler omega_i with omega_s+omega_i=omega_p (degenerate: each at 2*lambda_pump). DIRECTION: photons emitted on a cone (Type I, two cones for Type II) at a few degrees half-angle off the pump axis -> two correlated output beams, not collinear. POLARIZATION: Type I both photons same pol (orthogonal to pump); Type II signal and idler orthogonal to each other -> polarization-entangled at the cone intersections. PHASE/POWER: pump passes nearly undepleted; pair flux ~ chi2^2 L, extremely weak (single-photon level).
- **Key params:** chi2_process = SPDC; pm_type {I,II}; pump_wl -> signal_wl, idler_wl; emission cone half-angle (deg); pair-generation efficiency; entanglement type (pol).
- **Add-on mapping:** MAP TO 'CRYSTAL' with chi2_process=SPDC. NEW params (beyond SHG set): cone_half_angle_deg; signal_wl / idler_wl (two outputs). Tracer behavior: emit TWO child rays at +/- cone_half_angle off ray.dir, each at the down-converted wavelength, with orthogonal polarizations for Type II. This formalizes what bell_entanglement.py / hong_ou_mandel.py currently fake with hand-placed sources -- the crystal becomes a true 1-in/2-out element.
- **Real examples:** Thorlabs BBO-for-SPDC group (pump 405 nm -> 810 nm pairs), Type I and Type II cut options, 5x5x0.5-3 mm. Newport/Newlight Photonics PABBO. Used in Bell-test and Hong-Ou-Mandel benches.
- **Refs:** https://www.thorlabs.com/bbo-crystals-for-spontaneous-parametric-down-conversion-spdc

#### KTP (potassium titanyl phosphate) -- Type II SHG, OPO
- **What it is:** Biaxial nonlinear crystal, the standard for high-efficiency 1064->532 nm green generation and for near-IR OPOs. Large deff (~3.5 pm/V), high damage threshold, low walk-off, broad temperature/angular acceptance -- much more forgiving than BBO but limited to <~3.5 um and prone to gray-tracking at high green powers. Usually Type II (o+e->e).
- **Optical behavior:** FREQUENCY: 1064 nm + 1064 nm -> 532 nm SHG (or signal/idler for OPO). DIRECTION: near-collinear, small walk-off (~0.2-0.5 deg). POLARIZATION: Type II takes one o + one e fundamental photon -> harmonic polarized along a fixed crystal axis (so a 45-deg-pol input maximizes conversion; this is the polarization-sensitivity the tracer must capture). PHASE: phase-matched at a fixed angle (often 90-deg non-critical for some bands), temperature-tunable; wider acceptance bandwidth than BBO.
- **Key params:** chi2_process=SHG or OPO; pm_type=II; pm_angle/temperature; deff; walkoff_deg (small); conv_eff; input pol must be 45 deg to the o/e axes.
- **Add-on mapping:** MAP TO 'CRYSTAL', chi2_process=SHG, pm_type=TYPE_II. Same NEW param set as BBO-SHG. The Type-II distinction is captured by pm_type plus the evec handling: the tracer should weight conversion by the projection of the input polarization onto the (o,e) axes (max at 45 deg, zero if purely o or e) -- a NEW behavior the Type-I branch doesn't need. Walk-off param near zero.
- **Real examples:** EKSMA KTP-402 / KTP-404 (7x7x9 mm, 90-deg or theta=23.5 deg PM, AR@1064+532, Type II SHG of 1064 nm). Raicol, Cristal Laser KTP. deff ~ 3.2-3.6 pm/V; transparency 350-3500 nm.
- **Refs:** https://www.meetoptics.com/nonlinear-crystals/ktp/s/eksma-optics/p/KTP-402 ; https://eksmaoptics.com/out/media/EKSMA_Optics_KTP_Crystals.pdf

#### LBO (lithium triborate) -- Type I/II SHG & THG, non-critical PM
- **What it is:** Biaxial crystal prized for high-power frequency conversion (industrial green/UV lasers) because of very low walk-off, high damage threshold, and the availability of temperature-tuned non-critical phase matching (NCPM, 90-deg cut -> zero walk-off). Lower deff than KTP/BBO so used with longer crystals or high intensity.
- **Optical behavior:** FREQUENCY: 1064->532 (SHG) and 1064->355 nm (THG, cascaded). DIRECTION: essentially collinear, walk-off ~0 in NCPM mode (its headline advantage). POLARIZATION: Type I or Type II depending on band. PHASE: phase-matching set primarily by temperature (oven, ~25-200 C) rather than angle in NCPM -> a temperature_C tuning parameter rather than an angle. Wide angular acceptance, narrow temperature acceptance.
- **Key params:** chi2_process=SHG/THG; pm_type {I,II}; tuning via temperature_C (NCPM) instead of angle; walkoff_deg ~ 0; deff (~0.8 pm/V); length (often 10-30 mm).
- **Add-on mapping:** MAP TO 'CRYSTAL'. Same as BBO/KTP. NEW param to add for LBO/PPLN specifically: pm_tuning EnumProperty {ANGLE,TEMPERATURE} plus temperature_C FloatProperty, so the phase-match condition (and hence conv_eff vs wavelength) can be driven by temperature instead of pm_angle. walkoff_deg defaults ~0.
- **Real examples:** Thorlabs 'LBO Crystals for Second and Third Harmonic Generation' group (objectgroup_id=16709), AR-coated for 1064/532/355, lengths up to ~15 mm. EKSMA / Cristal Laser LBO. deff ~ 0.8 pm/V; transparency 160-2600 nm.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=16709 ; https://eksmaoptics.com/out/media/Crystals.pdf

#### PPLN (periodically-poled lithium niobate) -- QPM SHG/DFG/OPO
- **What it is:** Ferroelectric crystal engineered with a periodically reversed chi2 domain grating (poling period Lambda ~ 6-35 um) so it achieves QUASI-phase-matching: the periodic sign flip resets the phase slip every coherence length, allowing access to the huge d33 coefficient (~17 pm/V, ~10x bulk-PM crystals) with zero walk-off. MgO-doped to resist photorefractive damage. Tuned by temperature (oven) and by selecting one of several poling periods on the chip.
- **Optical behavior:** FREQUENCY: extremely efficient SHG (e.g. 1064->532, 1550->775), DFG, and singly-resonant OPO (1064 pump -> mid-IR signal+idler tunable 1.4-4+ um). DIRECTION: perfectly collinear, NO walk-off (QPM along the poling axis). POLARIZATION: all interacting waves same polarization (Type 0, e-e-e) -> uses largest d33; polarization preserved. PHASE: QPM condition dk = 2*pi/Lambda; tuned continuously with temperature and discretely by poling period. Mandatory temperature oven.
- **Key params:** chi2_process=SHG/DFG/OPO; pm_type=TYPE_0 (QPM); poling_period_um Lambda; temperature_C; deff (~14-17 pm/V); length (10-50 mm); walkoff=0; for OPO: pump->signal_wl,idler_wl.
- **Add-on mapping:** MAP TO 'CRYSTAL', chi2_process in {SHG,DFG,OPO}. NEW params beyond the bulk-crystal set: poling_period_um FloatProperty; pm_type gains a TYPE_0/QPM enum value; pm_tuning=TEMPERATURE + temperature_C (shared with LBO). OPO/DFG modes reuse the SPDC two-output emission logic (signal+idler) but collinear (cone_half_angle=0). walkoff_deg=0.
- **Real examples:** Thorlabs OPO-4-40 (PPLN chip, multiple poling periods, ~1025 nm SHG, MgO:PPLN), paired with the PV10 crystal oven for temperature tuning; Covesion MSHG/MOPO MgO:PPLN crystals (Lambda 6.5-35 um, 0.5-50 mm). d33 ~ 17 pm/V.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm (PPLN tutorial) ; https://www.yumpu.com/en/document/view/28396747/periodically-poled-lithium-niobate-ppln-tutorial-thorlabs ; https://www.covesion.com

#### KDP / KD*P (potassium dihydrogen phosphate) -- large-aperture SHG/THG & Pockels
- **What it is:** The classic, cheap, large-aperture nonlinear crystal (grown to >30 cm for fusion lasers like NIF). Lower deff and damage threshold than BBO, hygroscopic (needs sealed housing), but uniquely scalable in size. Also the canonical longitudinal Pockels-cell material (KD*P, the deuterated isomorph). Negative uniaxial, Type I or II.
- **Optical behavior:** FREQUENCY: SHG/THG of high-energy Nd:glass/Nd:YAG (1053/1064 -> 527/532, 351/355). DIRECTION: collinear with modest walk-off. POLARIZATION: Type I (o+o->e) or Type II (o+e->e). As a Pockels cell, an applied longitudinal voltage induces birefringence -> acts as a voltage-controlled waveplate (see Pockels entry).
- **Key params:** chi2_process=SHG/THG; pm_type {I,II}; pm_angle; deff (~0.4 pm/V); large clear_aperture (up to >100 mm); hygroscopic housing.
- **Add-on mapping:** MAP TO 'CRYSTAL' for the harmonic role (identical param set to BBO/KTP, just different deff/aperture defaults). For its electro-optic role MAP TO the new MODULATOR type (Pockels variant below). No new params beyond the shared CRYSTAL set; mainly a defaults/material entry.
- **Real examples:** Cleveland Crystals / Coherent KDP & KD*P, apertures 10-100+ mm; NIF/OMEGA frequency-conversion plates. deff(KDP) ~ 0.39 pm/V; transparency 200-1500 nm.
- **Refs:** https://eksmaoptics.com/out/media/Crystals.pdf ; https://www.coherent.com (Cleveland Crystals KDP/KD*P)

#### Faraday optical isolator (free-space, polarization-dependent)
- **What it is:** A one-way valve for light. Built as: input polarizer -> Faraday rotator (TGG or terbium-doped crystal in a strong permanent magnet) -> output polarizer set 45 deg from the input. Forward light passes; any back-reflection is rotated a further 45 deg (non-reciprocal Faraday rotation adds, it does not cancel) and is rejected by the input polarizer. Protects lasers from feedback.
- **Optical behavior:** DIRECTION/POWER: transmits the forward beam (small insertion loss ~0.1-1 dB); blocks the reverse beam with high isolation (typ. 30-40 dB, i.e. extinction ~1e3-1e4). FREQUENCY: unchanged. POLARIZATION: rotates the polarization by +45 deg on every pass regardless of propagation direction (non-reciprocal) -> output is 45-deg-rotated relative to input. This non-reciprocity is the whole point and cannot be modeled by a reciprocal Jones element. Narrowband: rotation = Verdet*B*L is wavelength-dependent, so isolation peaks at the design wl.
- **Key params:** isolation_dB (-> extinction ratio); insertion_loss_dB; design_wl; aperture; faraday_rotation = 45 deg; forward direction (IN->OUT port axis); max power rating; (polarization-independent dual-stage variants also exist for fiber).
- **Add-on mapping:** MAP TO EXISTING 'ISOLATOR'. The tracer already gates on IN->OUT port direction (absorbs backward rays) -- correct first-order behavior. UPGRADES via existing params: reuse extinction (currently polarizer-only) as the finite reverse leakage, and design_wl for the narrowband peak. NEW behavior to add: apply a fixed +45 deg polarization rotation to the forward evec/jones (non-reciprocal), and let a small fraction (1/extinction) of backward light leak through instead of hard-absorbing. NEW param: isolation_dB (maps to extinction), insertion_loss (maps onto a transmission<1).
- **Real examples:** Thorlabs IO-3-1064-HP (1064 nm, O2.7 mm beam, 15 W, ~30+ dB isolation), IO-5-1064-HP (O4.7 mm, 60 W), IO-8-1064-HP (O7 mm, 75 W); IO-3D-1064-VLP low-power. NIR family 690-1080 nm (TGG rotator). Isolation typ. 30-40 dB, insertion loss <0.5-1 dB.
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=IO-3-1064-HP ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4915 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=4914

#### Solid / air-spaced Fabry-Perot etalon (fixed)
- **What it is:** Two parallel partially-reflecting surfaces (a polished glass/fused-silica plate, or an air gap between two coated mirrors) forming a passive multi-beam interferometer. Acts as a periodic wavelength filter / mode selector. Fixed-spacing etalons live inside laser cavities for single-frequency operation and as comb filters.
- **Optical behavior:** FREQUENCY/POWER: wavelength-dependent Airy transmission T(lambda) = 1/(1 + F sin^2(delta/2)), delta = 4*pi*n*L*cos(theta)/lambda, F = 4R/(1-R)^2 -> transmits sharp peaks spaced by the Free Spectral Range FSR = c/(2nL), each peak with width FWHM = FSR/Finesse, Finesse ~ pi*sqrt(R)/(1-R). DIRECTION: collinear transmit + a complementary reflected comb (1-T). PHASE: adds the resonant cavity phase. Tilting (theta) or scanning L shifts the comb.
- **Key params:** cavity spacing L (mm); surface reflectivity R; refractive index n; -> derived FSR, finesse, FWHM resolution; incidence angle theta; design wl.
- **Add-on mapping:** MAP TO EXISTING 'CAVITY'. ALREADY IMPLEMENTED CORRECTLY: tracer calls physics.airy_transmission(ray.wl, op.cavity_spacing_mm, op.reflectivity) -- exactly the Airy formula above, using existing params cavity_spacing_mm and reflectivity. Reuse refractive_index for n (currently airy_transmission defaults n=1). NEW behavior worth adding: also spawn the complementary REFLECTED beam with power*(1-T) (currently only the transmitted port is emitted), and honor incidence angle theta via the cos(theta) term. No new params strictly required; optionally surface FSR/finesse as read-only derived UI.
- **Real examples:** Thorlabs SA200-series scanning Fabry-Perot (confocal, R=50 mm mirrors, FSR 1.5 GHz, finesse >200, 7.5 MHz resolution, Invar spacer) -- the air-spaced/scanning case; solid fused-silica etalons (e.g. Thorlabs SA series plates, LightMachinery custom etalons) for the fixed case. R typ. 0.95-0.999.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=859 ; https://www.thorlabs.com/scanning-fabry-perot-interferometers

#### Scanning Fabry-Perot interferometer / piezo-tuned air-spaced cavity
- **What it is:** Same Airy physics as the fixed etalon, but one mirror is mounted on a piezo so the spacing L is swept, sweeping the transmission comb across the laser line -> a spectrum analyzer that resolves laser mode structure and linewidth. Confocal geometry (mirror RoC = spacing) makes finesse insensitive to alignment.
- **Optical behavior:** Identical Airy transmission, but L(t) is time-dependent -> the transmission peak sweeps in wavelength/frequency, mapping the input spectrum onto a photodiode trace. FSR and finesse as above; confocal FSR = c/(4nL).
- **Key params:** spacing L (swept); R; finesse; FSR; scan range/voltage; confocal vs plane geometry.
- **Add-on mapping:** MAP TO EXISTING 'CAVITY' with cavity_spacing_mm animated (Blender can keyframe/drive the property). NEW optional param: a geometry enum {PLANE, CONFOCAL} that switches FSR = c/2nL vs c/4nL in the derived display. Tracer behavior unchanged (Airy per current frame's spacing). This is a UI/animation layer over the already-correct CAVITY handler.
- **Real examples:** Thorlabs SA200-3B / SA210 series (Invar confocal cavity, piezo-scanned, FSR 1.5 GHz / 10 GHz options, finesse >200/>150). Toptica FPI 100. Coherent/Burleigh scanning FP.
- **Refs:** https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=859

#### High-finesse / reference cavity (two HR mirrors, ABCD-resonant)
- **What it is:** An air-spaced cavity built from two ultra-high-reflectivity mirrors (R>0.9999) on a rigid (ULE/Zerodur) spacer, used as a frequency reference for laser stabilization (Pound-Drever-Hall) or as an enhancement cavity. Finesse 1e4-1e6. Physically the same Airy element as an etalon but in the extreme-R limit with mode-matching (cavity g-parameters) mattering.
- **Optical behavior:** Extremely narrow, widely-spaced transmission resonances (kHz-Hz linewidth). On resonance: builds up huge circulating power and transmits; off resonance: reflects nearly everything. The reflected port carries the PDH error signal phase. Supports transverse modes set by mirror curvature (ABCD/g-parameter stability).
- **Key params:** spacing L; mirror R (->finesse); mirror RoC (for transverse-mode/stability); FSR; linewidth; spacer material/thermal expansion.
- **Add-on mapping:** MAP TO EXISTING 'CAVITY' (same Airy handler, just R-> ~0.9999, large cavity_spacing_mm). NEW params for fidelity: mirror_roc_mm (cavity geometry / stability g = 1-L/R, ties into the existing ABCD/Gaussian q machinery the tracer already has for lenses); optionally a buildup/circulating-power readout. The transmit/reflect split should be spawned (as in the fixed-etalon upgrade). Distinguishes a 'cavity' from a 'thin etalon' mainly by parameter regime, not a new type.
- **Real examples:** Stable Laser Systems / Menlo ULE reference cavities (finesse ~250k-400k, R=0.5-1 m mirrors, 10-25 cm spacers); Thorlabs supermirrors (R>99.999%). Used in optical clocks and PDH locks.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=859 ; https://stablelasers.com

#### Pockels cell (longitudinal/transverse EO -- KD*P, LiNbO3, BBO, RTP)
- **What it is:** A voltage-controlled waveplate. An electro-optic crystal with electrodes; an applied voltage induces a linear (chi2/Pockels) birefringence proportional to V, so the crystal's retardance is electrically tunable from 0 to half-wave. Used with crossed polarizers as a fast (ns) optical shutter / Q-switch / pulse-picker; with QWP bias as an amplitude modulator.
- **Optical behavior:** POLARIZATION/PHASE: acts as a linear retarder whose retardance = pi*(V/Vpi), Vpi = half-wave voltage. At V=Vpi it is a half-wave plate (rotates linear pol 90 deg -> with crossed polarizer, switches transmission ON); at V=0, no retardance (OFF). FREQUENCY: unchanged (pure phase/polarization). DIRECTION: collinear, no deflection. Response is essentially instantaneous (electronic), so it gates/Q-switches.
- **Key params:** modulator_type=POCKELS; Vpi half-wave voltage (V); applied voltage V (-> retardance_deg = 180*V/Vpi); fast-axis orientation; design_wl (Vpi scales with wl); crystal material; extinction with crossed polarizer.
- **Add-on mapping:** MAP TO NEW element_type 'MODULATOR' with modulator_type=POCKELS. Reuse the EXISTING waveplate machinery: it is literally a WAVEPLATE whose retardance_deg is driven by voltage. Reuse retardance_deg, fast_axis_deg, design_wl. NEW params: modulator_type EnumProperty {EOM_PHASE,EOM_AMPLITUDE,POCKELS,AOM,KERR}; v_pi (half-wave voltage); drive_voltage V (a driver maps V -> retardance_deg = 180*V/v_pi). Tracer behavior = existing M_waveplate(retardance_deg, fast_axis_deg) with retardance computed from V. No new physics kernel needed -- only the param-to-retardance mapping.
- **Real examples:** Thorlabs PCT900 (transverse Pockels cell), EO-PC-1064 (KD*P/BBO, 1064 nm). Leysop/Conoptics KD*P Pockels cells, Vpi ~ few kV. BBO/RTP Q-switch cells. Vpi(KD*P) ~ 3-7 kV @ 1064 nm; ns switching.
- **Refs:** https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=6149 ; https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=15957&pn=PCT900

#### Electro-optic modulator (EOM) -- phase & amplitude (LiNbO3, resonant/broadband)
- **What it is:** A waveguide or free-space EO crystal (usually MgO:LiNbO3) driven at RF to impose a controlled phase or amplitude modulation on a transmitted beam. Phase EOM adds a time-varying optical phase (-> generates RF sidebands, used for PDH locking and comb generation). Amplitude EOM = a phase modulator inside a polarization interferometer (crystal between crossed polarizers / a Mach-Zehnder) so phase -> intensity.
- **Optical behavior:** PHASE (phase EOM): adds phi(t) = pi*V(t)/Vpi -> spectrum gains sidebands at +/- the drive frequency (frequency-domain effect; beam direction unchanged, wavelength of carrier unchanged). AMPLITUDE (amp EOM): transmission = sin^2(pi*V/(2*Vpi)) -> voltage-controlled attenuation/intensity modulation. POLARIZATION: phase EOM preserves it; amplitude EOM uses pol optics internally. DIRECTION: collinear, no deflection.
- **Key params:** modulator_type {EOM_PHASE,EOM_AMPLITUDE}; Vpi (half-wave voltage); drive_voltage/depth; modulation frequency; design wl; clear aperture; extinction ratio (amp).
- **Add-on mapping:** MAP TO NEW 'MODULATOR'. Phase EOM: a pure-phase pass-through -> tracer applies a phase to evec/jones (the add-on already carries phase via with_phase / the interference machinery), no power change; sideband generation is a frequency-domain effect mostly out of chief-ray scope (could tag the segment with a modulation-frequency annotation). Amplitude EOM: maps to a voltage-controlled attenuator -> reuse the FILTER/ATTENUATOR transmission path with T = sin^2(pi*V/2Vpi). NEW params: modulator_type, v_pi, drive_voltage, mod_freq_MHz. No deflection, so geometry = inline pass-through.
- **Real examples:** Thorlabs EO-AM-NR-C1 (MgO:LiNbO3 amplitude, 600-900 nm, Vpi ~205 V @633 nm, O2 mm aperture, >10 dB extinction); EO-PM-NR-C1 (phase, same family). Qubig / iXblue (NIR/telecom LiNbO3 waveguide EOMs, Vpi ~1-5 V, GHz bandwidth).
- **Refs:** https://www.thorlabs.com/thorproduct.cfm?partnumber=EO-AM-NR-C1 ; https://www.thorlabs.com/thorproduct.cfm?partnumber=EO-PM-NR-C1 ; https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=2729

#### Acousto-optic modulator / deflector / frequency shifter (AOM/AOD -- TeO2, quartz, fused silica)
- **What it is:** A transparent crystal (TeO2, quartz, fused silica) with a piezo transducer launching an RF acoustic wave that creates a moving refractive-index grating (Bragg cell). An incident beam diffracts off this grating into a first order that is angularly deflected AND frequency-shifted by the RF. Used as a fast intensity modulator (switch the RF), a beam deflector/scanner (sweep the RF), and a frequency shifter (the carrier shifts by the acoustic frequency).
- **Optical behavior:** DIRECTION: first-order beam deflects by theta ~ lambda*f_RF/v_sound (Bragg angle); changing f_RF scans the angle -> a true beam-deflecting element (unlike EOM/Pockels which are collinear). FREQUENCY: the diffracted order is shifted by exactly the RF frequency (omega +/- 2*pi*f_RF) -> used for heterodyne/optical-tweezer detuning. POWER: diffraction efficiency (up to ~90%) is set by RF power, so amplitude-modulating the RF amplitude-modulates the beam -> ns-us switching. The zeroth (undiffracted) order continues straight, attenuated.
- **Key params:** modulator_type=AOM; RF frequency f_RF (MHz, sets deflection & frequency shift); acoustic velocity v_sound; diffraction order; diffraction efficiency (set by RF power); deflection angle theta; material (TeO2/quartz).
- **Add-on mapping:** MAP TO NEW 'MODULATOR' with modulator_type=AOM -- this is the one modulator that needs GEOMETRIC redirection, so it reuses the GRATING machinery, not the waveplate one. Tracer behavior: emit a deflected first-order child ray at theta = order*lambda*f_RF/v_sound off ray.dir (compute like _diffract but with a moving grating period = v_sound/f_RF), power = ray.power*diff_eff, and carry a frequency-shift annotation (wl unchanged at chief-ray resolution but tag delta_f = f_RF for heterodyne examples); pass the zeroth order straight with power*(1-diff_eff). NEW params: modulator_type, rf_freq_MHz, sound_velocity_m_s, diff_efficiency, diff_order. Effectively a voltage/RF-tunable GRATING with a frequency tag.
- **Real examples:** Gooch & Housego TeO2 AOMs (visible-IR), quartz AOMs (UV); Isomet 1205C/1250C; AA Opto-Electronic MT200/MT110; eq photonics AOM 3110-191 (1060 nm), AOM 3200-1214 (440-900 nm). Typical f_RF 80-200 MHz, deflection a few mrad to ~deg, efficiency 70-90%.
- **Refs:** https://www.rp-photonics.com/acousto_optic_modulators.html ; https://www.eqphotonics.de/en/product/aom-3110-191-for-1060nm/ ; https://handwiki.org/wiki/Physics:Acousto-optic_modulator

#### Kerr cell (quadratic electro-optic / Kerr modulator)
- **What it is:** An electro-optic shutter using the quadratic (chi3) Kerr effect in an isotropic medium (historically nitrobenzene, now Kerr-active liquids/glasses) between electrodes. Induced birefringence is proportional to E^2 (voltage squared), unlike the linear Pockels effect. Largely historical for shutters but conceptually the chi3 analog; also underlies optical Kerr lensing/mode-locking.
- **Optical behavior:** POLARIZATION/PHASE: voltage-induced retardance proportional to V^2 (Kerr constant K): delta phi = 2*pi*K*L*E^2. With crossed polarizers acts as a fast voltage-controlled shutter (like a Pockels cell but quadratic response, needs higher V, no specific crystal orientation since isotropic). FREQUENCY/DIRECTION: unchanged, collinear.
- **Key params:** modulator_type=KERR; Kerr constant K; voltage V (-> retardance ~ V^2); cell length L; design wl; isotropic medium.
- **Add-on mapping:** MAP TO NEW 'MODULATOR' with modulator_type=KERR. Same as Pockels (reuses WAVEPLATE/M_waveplate), but the V->retardance_deg mapping is QUADRATIC (retardance ~ kerr_const*L*V^2) instead of linear. NEW param: kerr_const (and reuse drive_voltage). Tracer behavior identical to Pockels otherwise (voltage-controlled retarder, no deflection).
- **Real examples:** Historical Kerr-cell shutters (nitrobenzene, kV drive). Modern relevance: optical Kerr effect in Ti:Sapphire Kerr-lens mode-locking; chi3 in fibers. Few off-the-shelf discrete Kerr cells today (Pockels cells superseded them).
- **Refs:** https://www.rp-photonics.com/kerr_effect.html ; https://en.wikipedia.org/wiki/Kerr_cell

---
