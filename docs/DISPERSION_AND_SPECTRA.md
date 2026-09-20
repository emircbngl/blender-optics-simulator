# Dispersion, cylindrical lenses and spectral detectors

## Find a component

**Add Component from Library** opens a searchable list, sorted by the displayed
name. Sizes follow the component name, for example **Protected Silver Mirror
1 in (PF10-03-P01)**. Part identifiers are unchanged. User catalog labels are
preserved. Tooltips include element type, vendor and specifications.

## White-light prism

Use **Examples → Dispersing Prism Spectrometer**, or
`optics_api.build_example('prism')`. It sets the source center to 550 nm and its
bandwidth to 220 nm. A fresh source otherwise has zero bandwidth and emits one
wavelength; changing coherence linewidth alone does not create a rainbow.

**Bandwidth (nm)** now appears directly in the Element panel. The library also
contains **White light source (broadband)**. Positive bandwidth creates eleven
mutually incoherent, Gaussian-weighted samples over the center ± bandwidth/2
interval. This is a sampled spectrum, not a continuous solar or lamp spectrum.
Existing library lasers remain monochromatic by default.

## Reflective diffraction gratings

Grooves run along the element's **local Y**; for a standard local +Z face,
positive-order dispersion points along **local X**. Roll the object about its
normal to change the ruling orientation. The tracer preserves the direction
component along the grooves, so oblique/conical incidence is supported too.

An inaccessible order now terminates at the grating; it no longer becomes an
undispersed mirror beam. The Element panel flags this when a current trace is
available, and the beam-path API reports `non_propagating_grating_order`.
Order zero (or zero groove density) still gives specular reflection.

Existing grating scenes can change: re-trace them and check order sign and
object roll. Flat user-specified order efficiency remains an approximation;
this is not a blaze-efficiency, transmission-grating or grating-anamorphism model.

The direction model is grounded in [MKS, Diffraction Grating Handbook,
§2.2, equation 2-3](https://www.newport.com/mam/celum/celum_assets/np/resources/MKS_Diffraction_Grating_Handbook.pdf).
Automated source-based numerical tests cover signed order, normal and near-normal
incidence, 45° incidence, conical incidence, roll and evanescent cutoffs.
The separate `physics_verify` oracle was unavailable during implementation;
its verification status for these changes is **UNVERIFIED**.

## Cylindrical lens

Choose **Cylindrical Lens f=100 mm** from the library, or set a Lens's **Lens
form** to **Cylindrical**. Local X is the powered direction; local Y is the
cylinder axis. Roll the object to rotate the line focus. Negative focal length
diverges in the powered direction. Other forms retain the spherical thin-lens
model. Changing form on an existing object changes its optical behavior; add a
new library component to obtain the corresponding cylinder-shaped mesh.

The tracer carries both transverse Gaussian dimensions, including coupling from
arbitrarily crossed cylinders. The sensor image, beam-profile plot/CSV, baked
beam envelope, aperture/slit/knife power and modal wavefront readout use this
state. `inspect_beam` returns the full `gaussian` matrix/frame and
`principal_radii_mm`; `w_mm` is only the area-equivalent radius. An astigmatic
beam has no single scalar waist or radius of curvature, so scalar-only readouts
are omitted. The two principal radii are sorted, not permanently labelled X/Y.

This is a paraxial thin-lens Gaussian model around the existing chief ray.
No thick-cylinder aberrations, high-NA focusing or re-fitted modes after strong
aperture clipping are claimed. Existing nonlinear conversion/OPA models still
initialize their converted output as a circular Gaussian. Thermal-lens estimates
use the area-equivalent radius. Zonal surface-figure diagnostics still use a
circular footprint; modal WFS curvature includes defocus and astigmatism.
See the [design and source notes](feedback-design.md) for the matrix convention.

## Intensity versus wavelength resolution

The ordinary sensor image uses a fixed intensity tint: RGB = I × (1, 0.5, 0.45).
Its pink/red color is **not** a wavelength measurement. Beam-path overlays and
rendered ray tubes use wavelength colors; wavefront sensors use a separate
wavefront map. These are different displays.

Choose **Spectrometer (wavelength-resolving detector)** from the library, or set
a camera/photodiode/power meter's **Sensor output → Spectrum**. The live sensor
window then shows optical power density versus wavelength. The caption gives
the wavelength span, instrument FWHM and total relative power. **Save Sensor**
saves the plot PNG; **Save Spectrum CSV** saves integrated bins and density.
The API/MCP call is `detector_spectrum(detector='Spectrum', filepath='...csv')`.

**Resolution FWHM (nm)** controls a Gaussian instrument line-spread function.
It broadens/merges the sampled arriving lines without inventing new source
frequencies. Exact simulated lines are also returned by the API. Finite plotting
tails are normalized to retain total power. The grid is capped at 8192 bins;
`sampling_limited` warns when an exceptionally wide band cannot display the
requested resolution. Empty sensors return an empty spectrum and zero power.

The analyzer is applied before binning; its existing finite extinction is
retained. Coherent paths interfere within a wavelength; different wavelengths
add in power. This is an **ideal optical spectrum in relative power units**,
independent of the detector's electronics mode/gain. It does not simulate a
manufacturer's spectrometer sensitivity, read noise, wavelength calibration or
Raman scattering. Coincident incoming wavelengths can be resolved even when
they hit the same spatial pixel.
