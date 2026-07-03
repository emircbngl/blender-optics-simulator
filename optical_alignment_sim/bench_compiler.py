"""bench_compiler.py -- a declarative bench spec compiled into optics_api/elements_generic calls.

The missing "design language" layer for agents: instead of hand-sequencing 15+ builder calls
(the main remaining hallucination surface in multi-step builds), an agent submits ONE
declarative spec (a dict; JSON always works -- MCP args are JSON -- and YAML is accepted when
PyYAML is importable) and the compiler validates it FULLY before touching the scene:

    {"name": "my_bench",
     "elements": [
       {"name": "SRC", "type": "source",       "at": [-150, 0, 0], "direction": [1, 0, 0],
        "params": {"wavelength": 632.8}},
       {"name": "BS",  "type": "beamsplitter", "at": [0, 0, 0],   "direction": [1, 0, 0],
        "out": [0, 1, 0]},
       {"name": "M1",  "type": "mirror",       "after": {"of": "BS", "along": [0, 1, 0], "distance": 180},
        "direction": [0, 1, 0], "out": [0, -1, 0]},
       {"name": "D",   "type": "detector",     "at": [0, -180, 0], "direction": [0, -1, 0]}],
     "mounts": {"M1": "KINEMATIC"}}

Placement is absolute (``at``) or relative (``after``: the referenced EARLIER element's position
plus ``distance`` along ``along`` -- or along the reference's own primary direction when ``along``
is omitted). Dual-port elements (mirror / beamsplitter / grating) take ``direction`` (incoming)
plus ``out`` (reflected/outgoing). ``params`` are validated against the REAL builder signature via
introspection -- an unknown parameter fails compilation with the list of valid ones, so a
hallucinated kwarg is caught before anything is built. Compilation is all-or-nothing: the scene is
only touched after the whole spec validates. After building, the bench is traced and diagnosed.

v1 scope (honest): the 18 generic element builders below; kinematic-mount presets via ``mounts``.
NOT in v1: custom DOF ranges, cage/tube/rail assembly, per-element support systems -- use the
explicit optics_api calls for those (see optics://workflows).
"""
from __future__ import annotations

import inspect
import json
import math

from . import elements_generic as eg

# type -> (builder, direction-argument names). SINGLE-dir builders map spec `direction` onto the
# named arg; DUAL builders map `direction` -> first (incoming) and `out` -> second (outgoing).
_TYPES = {
    "source":           ("source", ("direction",)),
    "detector":         ("detector", ("beam_dir",)),
    "mirror":           ("mirror", ("in_dir", "out_dir")),
    "beamsplitter":     ("beamsplitter", ("in_dir", "reflect_dir")),
    "grating":          ("grating", ("in_dir", "out_dir")),
    "lens":             ("lens", ("axis",)),
    "window":           ("window", ("axis",)),
    "waveplate":        ("waveplate", ("axis",)),
    "aperture":         ("aperture", ("axis",)),
    "objective":        ("objective", ("axis",)),
    "prism":            ("prism", ("axis",)),
    "polarizer":        ("polarizer", ("axis",)),
    "pinhole":          ("pinhole", ("axis",)),
    "slit":             ("slit", ("axis",)),
    "knife_edge":       ("knife_edge", ("axis",)),
    "isolator":         ("isolator", ("axis",)),
    "crystal":          ("crystal", ("beam_dir",)),
    "fiber_collimator": ("fiber_collimator", ("direction",)),
}


def _err(msg):
    return {"ok": False, "error": msg}


def _vec(v, what, elem, nonzero=False):
    if (not isinstance(v, (list, tuple))) or len(v) != 3:
        raise ValueError("%s of '%s' must be a 3-vector [x, y, z], got %r" % (what, elem, v))
    try:
        out = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        raise ValueError("%s of '%s' must contain numbers, got %r" % (what, elem, v))
    if not all(math.isfinite(x) for x in out):
        # JSON happily parses Infinity/NaN -- they must never reach the geometry
        raise ValueError("%s of '%s' must be finite (no NaN/Infinity), got %r" % (what, elem, v))
    if nonzero and (out[0] ** 2 + out[1] ** 2 + out[2] ** 2) < 1e-24:
        raise ValueError("%s of '%s' must be a non-zero vector" % (what, elem))
    return out


def _valid_params(fn):
    """The builder's real keyword surface (introspected, so it can never drift from the code)."""
    sig = inspect.signature(fn)
    skip = {"name", "loc", "coll", "direction", "beam_dir", "in_dir", "out_dir", "reflect_dir", "axis"}
    return sorted(p.name for p in sig.parameters.values() if p.name not in skip)


def parse_spec(spec):
    """Accept a dict, a JSON string, or (when PyYAML is importable) a YAML string."""
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        try:
            return json.loads(spec)
        except ValueError:
            pass
        try:
            import yaml
        except ImportError:
            raise ValueError("spec string is not valid JSON, and PyYAML is not available for YAML "
                             "-- send the spec as JSON (agents: pass a plain dict)")
        out = yaml.safe_load(spec)
        if not isinstance(out, dict):
            raise ValueError("YAML spec must parse to a mapping")
        return out
    raise ValueError("spec must be a dict or a JSON/YAML string")


def compile_spec(spec):
    """Validate the WHOLE spec and return the build plan [(builder_fn, name, loc, dir_kwargs, params)].
    Raises ValueError with an actionable message (including the valid options) on any problem;
    nothing is built here, so a bad spec never half-mutates the scene."""
    spec = parse_spec(spec)
    elements = spec.get("elements")
    if not elements or not isinstance(elements, list):
        raise ValueError("spec needs a non-empty 'elements' list")
    plan = []
    positions = {}          # name -> (loc, primary_dir), for `after` references
    seen = set()
    for i, e in enumerate(elements):
        name = e.get("name")
        etype = e.get("type")
        if not name or not isinstance(name, str):
            raise ValueError("element %d has no 'name'" % i)
        if name in seen:
            raise ValueError("duplicate element name '%s'" % name)
        seen.add(name)
        if etype not in _TYPES:
            raise ValueError("element '%s': unknown type '%s'; valid types: %s"
                             % (name, etype, ", ".join(sorted(_TYPES))))
        builder_name, dir_args = _TYPES[etype]
        builder = getattr(eg, builder_name)
        # --- position: absolute `at` or relative `after`
        if ("at" in e) == ("after" in e):
            raise ValueError("element '%s': give exactly one of 'at' or 'after'" % name)
        if "at" in e:
            loc = _vec(e["at"], "'at'", name)
        else:
            a = e["after"]
            if not isinstance(a, dict):
                raise ValueError("element '%s': 'after' must be a dict {of, along?, distance?}, got %r"
                                 % (name, a))
            ref = a.get("of")
            if not isinstance(ref, str) or ref not in positions:
                raise ValueError("element '%s': 'after.of' must name an EARLIER element; %r is not "
                                 "one of %s" % (name, ref, sorted(positions) or "(none yet)"))
            ref_loc, ref_dir = positions[ref]
            along = _vec(a["along"], "'after.along'", name, nonzero=True) if "along" in a else ref_dir
            try:
                dist = float(a.get("distance", 0.0))
            except (TypeError, ValueError):
                raise ValueError("element '%s': 'after.distance' must be a number, got %r"
                                 % (name, a.get("distance")))
            if not math.isfinite(dist):
                raise ValueError("element '%s': 'after.distance' must be finite" % name)
            n = (along[0] ** 2 + along[1] ** 2 + along[2] ** 2) ** 0.5
            loc = tuple(ref_loc[k] + dist * along[k] / n for k in range(3))
        # --- directions (must be non-zero: a zero axis crashes the builders' basis math)
        if "direction" not in e:
            raise ValueError("element '%s' (%s): needs 'direction' (the beam/optical axis)" % (name, etype))
        d_in = _vec(e["direction"], "'direction'", name, nonzero=True)
        dir_kwargs = {dir_args[0]: d_in}
        if len(dir_args) == 2:
            if "out" not in e:
                raise ValueError("element '%s' (%s): dual-port type needs 'out' (the reflected/outgoing "
                                 "direction) in addition to 'direction'" % (name, etype))
            dir_kwargs[dir_args[1]] = _vec(e["out"], "'out'", name, nonzero=True)
        elif "out" in e:
            raise ValueError("element '%s' (%s): 'out' is only for dual-port types (mirror/beamsplitter/"
                             "grating)" % (name, etype))
        # --- params, validated against the real builder signature
        params = e.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("element '%s' (%s): 'params' must be a dict of keyword arguments, got %r"
                             % (name, etype, params))
        valid = _valid_params(builder)
        unknown = sorted(set(params) - set(valid))
        if unknown:
            raise ValueError("element '%s' (%s): unknown param(s) %s; valid params for %s: %s"
                             % (name, etype, unknown, etype, ", ".join(valid)))
        plan.append((builder, name, loc, dir_kwargs, dict(params)))
        positions[name] = (loc, d_in)
    # --- mounts: reference check AND preset check, both at compile time -- a bad preset must
    # fail here, not after half the bench has already been built
    mounts = spec.get("mounts") or {}
    if not isinstance(mounts, dict):
        raise ValueError("'mounts' must be a dict {element_name: preset}, got %r" % (mounts,))
    bad = sorted(set(mounts) - seen)
    if bad:
        raise ValueError("'mounts' references unknown element(s): %s" % bad)
    from . import presets
    valid_presets = set(presets.MOUNT_LIBRARY)
    for mname, preset in mounts.items():
        if preset not in valid_presets:
            raise ValueError("mount for '%s': unknown preset %r; valid presets: %s"
                             % (mname, preset, ", ".join(sorted(valid_presets))))
    return plan, mounts, spec.get("name") or "bench"


def build(spec):
    """Compile + BUILD the spec into a new collection, then trace + diagnose. Returns
    {ok, built, collection, elements, segments, diagnostics_counts} or {ok:False, error}.

    NOTE (replace semantics, by design): building a spec whose ``name`` matches an existing
    bench REMOVES that previous "Bench_<name>" collection first -- same contract as
    ``build_example``. Re-submitting a spec therefore rebuilds the bench, it does not
    duplicate it; use a different ``name`` to keep both.

    If any builder or mount fails mid-build, everything created so far (objects + the new
    collection) is removed before the error returns -- the scene is never left half-built.
    The pre-existing same-name bench that was replaced is NOT restored (it was removed up
    front); the error message says so when that applies."""
    try:
        plan, mounts, bench_name = compile_spec(spec)
    except ValueError as e:
        return _err(str(e))
    import bpy
    from . import scan, tracer, diagnostics
    coll_name = "Bench_%s" % bench_name
    replaced = coll_name in bpy.data.collections
    coll = eg.example_collection(coll_name)
    built = []
    failing = "?"
    try:
        for builder, name, loc, dir_kwargs, params in plan:
            failing = name
            builder(name, loc, coll=coll, **dir_kwargs, **params)
            built.append(name)
        if mounts:
            from . import optics_api
            for name, preset in mounts.items():
                failing = name
                res = optics_api.set_mount(name, preset)
                if isinstance(res, dict) and res.get("error"):
                    raise RuntimeError("set_mount('%s', '%s'): %s" % (name, preset, res["error"]))
    except Exception as e:
        # all-or-nothing at build time too: tear down whatever this call created
        try:
            for obj in list(coll.all_objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(coll)
        except Exception:
            pass
        msg = "build failed at element '%s': %s: %s" % (failing, type(e).__name__, e)
        if replaced:
            msg += " (note: the previous '%s' collection was already replaced and is not restored)" % coll_name
        return _err(msg)
    bpy.context.view_layer.update()
    segs = scan._trace(bpy.context.scene)
    tracer.cached_segments = segs
    diags = diagnostics.run_diagnostics(bpy.context.scene)
    counts = {"BAD": sum(1 for d in diags if d.get("severity") == "BAD"),
              "WARN": sum(1 for d in diags if d.get("severity") == "WARN")}
    return {"ok": True, "built": built, "collection": coll.name,
            "elements": len(built), "segments": len(segs), "diagnostics_counts": counts,
            "diagnostics": diags if (counts["BAD"] or counts["WARN"]) else []}
