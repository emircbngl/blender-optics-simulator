"""Optics Simulator - a Blender add-on for simulating and aligning
optical setups (mirrors, lenses, beam splitters, lasers) with a live ray-trace
overlay, kinematic-mount-aware auto-alignment, and a render helper.

Human-first: every feature is driven from the View3D "Optics" sidebar tab.
An optional programmatic API (optics_api) lets Claude drive the same core.

Packaged as a Blender extension (blender_manifest.toml); no bl_info here.
"""
from __future__ import annotations

# Support `Reload Scripts` during development.
if "properties" in locals():
    import importlib
    for _m in ("prefs", "presets", "physics", "geometry", "properties", "operators", "mounts", "tracer",
               "overlay", "monitor", "handlers", "alignment", "solvers", "design", "diagnostics", "scan", "bake", "render", "library",
               "assembly", "ao", "bridge", "elements_generic", "optomech", "examples_builtin", "svg_export", "updater", "ui", "optics_api"):
        if _m in locals():
            importlib.reload(locals()[_m])

import sys

from . import (prefs, presets, physics, geometry, properties, operators, mounts, tracer, overlay,
               monitor, handlers, alignment, solvers, design, diagnostics, scan, bake, render, library, assembly, ao,
               bridge, elements_generic, optomech, examples_builtin, svg_export, updater, ui, optics_api)

# Registration order matters: property groups + pointers first, then the operators, mount
# logic, tracer/overlay/monitor/handlers/alignment/solvers/bake/render, library, assembly, ao, bridge, panels.
_modules = (prefs, properties, operators, mounts, tracer, overlay, monitor,
            handlers, alignment, solvers, design, scan, bake, render, library, assembly, ao, bridge, optomech, examples_builtin, svg_export, updater, ui)


def register():
    for m in _modules:
        m.register()
    # Expose the optional Phase-A API under a stable top-level name so it can be
    # called via execute_blender_code regardless of the installed package id.
    sys.modules["optics_api"] = optics_api


def unregister():
    sys.modules.pop("optics_api", None)
    for m in reversed(_modules):
        m.unregister()
