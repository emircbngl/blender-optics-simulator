# Beam rendering: a path display, not an opaque rod

Baked beams use soft emission-only volumes. Their material has no opaque surface,
absorption or scattering shader, so it does not hide the bench like a solid green
cylinder. Wavelength colors and the out-of-band display modes still come from
`beamcolor.py`; the mesh envelope still comes from the tracer's beam data.

This is an illustrative display of the computed path, **not** a calibrated
simulation of visible-air scattering. The radial fade and emission gain are
presentation choices. No optical position, port, wavelength, polarization, power,
Gaussian propagation parameter, aperture calculation or detector result is changed.

The fix is shared by **Bake Beams**, render preparation and `ensure_beams`.
Re-baking an old file upgrades its generated opaque materials in place. Generated
material caches include the appearance version and declared unit scale; metre and
millimetre scenes use equivalent emission per physical length. Repeated preparation
reuses the materials instead of adding duplicate shader graphs.

Existing custom materials are not a supported migration target. The generated
`OPTICS_BEAM*` materials are managed by the add-on; use a separate material if you
want to maintain a hand-edited appearance. Export formats that do not support Blender
volume shaders keep the mesh geometry but may not reproduce its rendered appearance.

The change is covered by `tests/test_beam_appearance.py` (legacy file migration,
material reuse, wavelength/OOB behavior, complete trace equality and metre/mm
semantics), the existing unit suite and the main optics regression suite.
