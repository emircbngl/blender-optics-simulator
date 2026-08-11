"""Dependency-free 2-D vector (SVG) schematic export of the optical layout + beam path.

A top-view (world XY) schematic for publication figures: element glyphs sized by clear aperture and
coloured by type, short port ticks (position + normal), and the traced beam path coloured by
wavelength (width + opacity by power, dashed for split-transmitted beams). Built entirely from
optics_api.get_state(), so it needs no extra dependencies and matches what the tracer computes.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from . import beamcolor


# per-type glyph fill (loosely mirrors the viewport material families)
_TYPE_FILL = {
    'MIRROR': '#dfe3ea', 'PRISM_MIRROR': '#dfe3ea', 'DEFORMABLE_MIRROR': '#dfe3ea',
    'RETROREFLECTOR': '#cfd6e0', 'GRATING': '#b3b0c7',
    'BEAMSPLITTER': '#5b9bf0', 'DICHROIC': '#cc5bb0', 'LENS': '#73cdf2',
    'WAVEPLATE': '#f2cc4d', 'ABERRATOR': '#f2cc4d', 'POLARIZER': '#33b389',
    'CAVITY': '#5b9bf0', 'FILTER': '#f27330', 'ATTENUATOR': '#8f9298',
    'SHUTTER': '#34343a',
    'SOURCE': '#e21810', 'FIBER_COLLIMATOR': '#6a6f78',
    'DETECTOR': '#26282e', 'PHOTODIODE': '#26282e', 'POWER_METER': '#26282e',
    'WAVEFRONT_SENSOR': '#26282e', 'ISOLATOR': '#4d4d55',
    'APERTURE': '#1a1a20', 'PINHOLE': '#1a1a20', 'PASSTHROUGH': '#cdd2da',
}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(state, width=900, margin=64, oob='FALSE_COLOR'):
    """Return an SVG document string for the optical state (optics_api.get_state() shape).

    `oob` is the scene's invisible-beam mode (see `beamcolor`): it decides how IR/UV beams are
    coloured here, identically to the viewport and the bake. Under 'HIDE' they are omitted."""
    elems = state.get("elements", [])
    beams = state.get("beam_path", [])
    pts = [(e["world_center"][0], e["world_center"][1]) for e in elems]
    for s in beams:
        pts.append((s["p1"][0], s["p1"][1]))
        pts.append((s["p2"][0], s["p2"][1]))
    if not pts:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="120">'
                '<text x="20" y="60" fill="#888" font-family="sans-serif">'
                'No optical elements</text></svg>' % width)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    span_x = max(max(xs) - minx, 1.0)
    span_y = max(max(ys) - miny, 1.0)
    # fit BOTH axes: scaling off X alone made a Y-dominant (vertical) beamline explode the canvas
    # to ~200k px tall (span_x collapses to the 1.0 floor). Cap the height to a square-ish budget.
    max_h = width
    scale = min((width - 2 * margin) / span_x, (max_h - 2 * margin) / span_y)
    height = int(span_y * scale + 2 * margin)

    def X(x):
        return margin + (x - minx) * scale

    def Y(y):
        return height - margin - (y - miny) * scale          # world +Y up -> SVG up

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
           'font-family="sans-serif">' % (width, height, width, height),
           '<rect width="100%%" height="100%%" fill="#0d0e12"/>']
    for s in beams:                                          # beam path
        rgb = beamcolor.wavelength_rgb255(s.get("wavelength", 632.8), oob)
        if rgb is None:                                      # hidden by the invisible-beam mode
            continue
        x1, y1, x2, y2 = X(s["p1"][0]), Y(s["p1"][1]), X(s["p2"][0]), Y(s["p2"][1])
        r, g, b = rgb
        p = max(min(float(s.get("power", 1.0)), 1.0), 0.0)
        dash = ' stroke-dasharray="5,4"' if s.get("kind") == 'SPLIT_T' else ''
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="rgb(%d,%d,%d)" '
                   'stroke-width="%.2f" stroke-opacity="%.2f"%s/>'
                   % (x1, y1, x2, y2, r, g, b, 0.8 + 2.6 * p, 0.35 + 0.6 * p, dash))
    for e in elems:                                          # element glyphs + port ticks + labels
        cx, cy = X(e["world_center"][0]), Y(e["world_center"][1])
        ap = float(e.get("params", {}).get("clear_aperture", 6.0)) or 6.0
        rad = max(ap * scale, 4.0)
        for port in e.get("ports", []):
            wp, wn = port["world_pos"], port["world_normal"]
            px0, py0 = X(wp[0]), Y(wp[1])
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#7a8088" '
                       'stroke-width="1"/>' % (px0, py0, px0 + wn[0] * 10.0, py0 - wn[1] * 10.0))
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="#000" stroke-width="0.8"/>'
                   % (cx, cy, rad, _TYPE_FILL.get(e["type"], '#cdd2da')))
        out.append('<text x="%.1f" y="%.1f" fill="#c8ccd2" font-size="11" text-anchor="middle">%s</text>'
                   % (cx, cy - rad - 4.0, _esc(e["name"])))
    out.append('</svg>')
    return "\n".join(out)


def export_svg(filepath):
    """Write a top-view SVG schematic of the current scene to filepath. {ok, path, elements, beams}."""
    from . import optics_api
    state = optics_api.get_state()
    oob = getattr(bpy.context.scene.optics, "oob_display", 'FALSE_COLOR')
    path = bpy.path.abspath(filepath) if str(filepath).startswith("//") else filepath
    with open(path, "w") as f:
        f.write(build_svg(state, oob=oob))
    return {"ok": True, "path": path, "elements": len(state.get("elements", [])),
            "beams": len(state.get("beam_path", []))}


class OPTICS_OT_export_svg(Operator):
    bl_idname = "optics.export_svg"
    bl_label = "Export SVG Schematic"
    bl_description = "Export a top-view 2-D vector (SVG) schematic of the optical layout + beam path"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', default="//optics_schematic.svg")
    filter_glob: StringProperty(default="*.svg", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            res = export_svg(self.filepath)
        except (OSError, RuntimeError) as e:
            self.report({'ERROR'}, "SVG export failed: %s" % e)
            return {'CANCELLED'}
        self.report({'INFO'}, "Exported SVG: %d elements, %d beams -> %s"
                    % (res["elements"], res["beams"], res["path"]))
        return {'FINISHED'}


_classes = (OPTICS_OT_export_svg,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
