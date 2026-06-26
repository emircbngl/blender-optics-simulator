"""Draw docs/img/object-wavefronts.png from /tmp/objwf/*.npy (knight + die zonal wavefronts).

Raw zonal field W(x,y) in waves, diverging colormap, percentile-clipped — the goal is RECOGNISABILITY
(the valid region traces the silhouette; the die pips read as the quincunx). Uses the shared `figstyle`
schema with PER-PANEL colorbars (the knight ~thousands of waves and the die ~tens are on different
scales, so a single shared colorbar would be wrong); each colorbar gets its own reserved slot beside its
panel and the figure is saved tight, so no tick label is clipped and no colorbar crowds the next panel.
"""
import os
import json
import numpy as np
import figstyle as fs

SRC = "/tmp/objwf"
meta = json.load(open(os.path.join(SRC, "meta.json")))
keys = [k for k in ("knight", "die") if os.path.exists(os.path.join(SRC, k + "_field.npy"))]

fig, axes = fs.grid(1, len(keys), w=5.6 * len(keys), h=5.9,
                    title="Zonal wavefront of a real object — aimed at its iconic face")
for ax, key in zip(axes, keys):
    F = np.load(os.path.join(SRC, key + "_field.npy"))
    m = meta[key]
    finite = np.abs(F[np.isfinite(F)])
    vmax = float(np.percentile(finite, 97.0)) if finite.size else 1.0
    cap = "RMS %.0f waves  ·  Ø%.0f mm  ·  valid %.0f%%  ·  %d px" % (
        m["rms_uniform"], m["footprint_mm"], 100.0 * m["hit_frac"], m["px"])
    im = fs.image_panel(ax, F, vmin=-vmax, vmax=vmax, title=m.get("title", key), caption=cap)
    fs.panel_colorbar(fig, ax, im, label="waves")

fs.footer(fig, "The zonal sensor render is a range image of the reflector along the beam: the valid (reflected) "
               "region traces the object's silhouette and the depth relief colours it.  Orientation is everything — "
               "the object's iconic view must face the beam.")
fs.finalize(fig, "docs/img/object-wavefronts.png", has_colorbar=False, right=0.90, wspace=0.32, bottom=0.17)
print("SAVED docs/img/object-wavefronts.png")
