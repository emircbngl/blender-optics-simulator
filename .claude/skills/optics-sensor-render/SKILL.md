---
name: optics-sensor-render
description: >
  Read and render what an optical sensor actually measures in the Blender Optics Simulator — a finite
  sensor's aperture capture, the modal wavefront (Zernike RMS, incl. the beam's own curvature defocus),
  and the dense zonal surface-figure map. Use when asked "what does the sensor / WFS see", "render the
  wavefront", "sensor render", "show the surface figure", "measure the aberration", or
  "/optics-sensor-render".
---

# optics-sensor-render: the honest "what the sensor measures"

A finite sensor does NOT swallow the whole beam, and the modal WFS is a low-pass caricature of the real
figure. This skill reads both the modal and the dense zonal views and names which is which, so the
result is honest.

## Workflow

1. **Aperture capture** — `sensor_capture(sensor)`: the beam radius `w` at the sensor vs its clear
   aperture, the captured power `1 − exp(−2a²/w²)`, the captured figure fraction `ρ_max = a/w`, and
   whether the aperture clip applied. A collimated beam that fits keeps the whole figure; a diverging
   beam that overfills is clipped — the SAME optic reads differently through different beams.
2. **Modal wavefront** — `ao_measure(sensor)` / `get_wavefront(sensor)`: the reconstructed Zernike
   vector + RMS. This now folds in the beam's OWN wavefront curvature R(z) as defocus (a clean diverging
   beam reads its real defocus, not RMS 0), plus `rms_modal` (the DM-correctable part) and `n_beams`.
   It is a **15-Zernike low-pass** — faithful for smooth figures, a caricature for high-frequency relief.
3. **Dense zonal map** — `zonal_render(sensor=…, filepath=…)`: the RAW px×px surface-figure field with
   NO 15-mode projection, so mid/high-spatial-frequency figure survives up to the grid Nyquist. This is
   the honest companion to the modal read; use it to SEE the actual relief. It finds the reflective
   element feeding the sensor and renders ITS figure over the beam footprint (Gaussian-weighted, not
   top-hat) — errors cleanly if no reflected beam lands on the sensor.
4. **Show it** — `render()` a hero view + surface the saved sensor frame so it can be eyeballed.

## Disciplines
- Always NAME the view: "modal (15-Zernike low-pass)" vs "zonal (dense raw field)". They legitimately
  disagree on high-frequency content; that's the point of showing both.
- A finite sensor reads only its aperture — report `ρ_max` / captured power, never imply the whole beam
  was measured.
- The modal AO loop corrects the modal channel; the static read also surfaces the beam's intrinsic
  defocus — for a collimated reference they coincide. Don't conflate the loop residual with the read.
