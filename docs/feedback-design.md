# Cylindrical lenses and spectral readout

Implementation scope approved by the owner on 2026-09-17.

## Cylindrical lens

Promote the existing `LENS.lens_type=CYLINDRICAL` catalog form into a real
one-axis thin lens. Local X is the powered axis; local Y is the cylinder axis.
Object roll rotates both geometry and optical power. Other lens forms retain
their scalar behavior.

On first cylindrical interaction, promote scalar q to a symmetric complex 2×2
Gaussian Q matrix with a transported transverse frame. This retains qx/qy for
aligned axes and off-diagonal coupling for crossed, rotated cylinders. Free
propagation adds distance times the identity; lens power subtracts a real
power matrix from inverse Q. Scalar circular-beam paths remain unchanged.
Segments carry the full matrix, frame and two principal radii; sensor images
use the full elliptical envelope and quadratic phase. A single legacy w is
explicitly the area-equivalent radius, never a claim of a circular spot.

Source grounding: [MIT photonics notes, Gaussian ABCD propagation](https://ocw.mit.edu/courses/6-974-fundamentals-of-photonics-quantum-electronics-spring-2006/bf3bdeb971819ddc9c68719d28bb2745_classnotes.pdf),
[general astigmatic Gaussian matrix formalism](https://arxiv.org/abs/2506.22308).
Paraxial, ideal thin optics only; no thick-cylinder aberrations or high-NA model.
The physics_verify service is unavailable in this session: oracle verification
is **UNVERIFIED**. Numerical regression checks are reported separately.

## Spectral detector

Keep electronic `det_mode` separate from `sensor_mode` (intensity/spectrum).
The spectrum is an ideal wavelength-resolving instrument: group exact arriving
wavelengths, apply analyzer/coherent summation within each wavelength first,
then add different wavelengths incoherently. Instrument resolution is a
Gaussian line-spread FWHM in nm, distinct from wavelength sample spacing.
Use integrated bins and include tails so total received power is conserved.
Return exact simulated lines and the resolution-broadened bins, show a live
plot, and export CSV. Values use the simulator's existing relative-power
convention, not an invented absolute watt calibration. It cannot reconstruct
wavelengths absent from the source's eleven-line broadband sampling.

## Acceptance

One cylinder focuses only one axis; rolling it rotates the image; an orthogonal
pair focuses both axes; arbitrary crossed cylinders remain symmetric and
positive-intensity; circular lens behavior stays unchanged. Verify propagation,
sensor images, aperture handling and mm/metre equivalence.

Two coincident colors remain distinct at fine spectral resolution and merge
at coarse resolution. Check analyzer behavior, source identity, interference,
empty detector, finite-resolution power conservation, live plot and CSV.
