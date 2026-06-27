"""Phase-A programmatic facade (OPTIONAL).

Wraps the same pure-Python core the UI operators use, returning JSON-able dicts.
Not required for human use. When the add-on is enabled, __init__ aliases this
module as the top-level `optics_api`, so Claude can drive the bench through the
existing execute_blender_code socket:

    import optics_api, json
    print(json.dumps(optics_api.get_state()))
"""
from __future__ import annotations

import math

import bpy

from . import tracer, alignment, mounts, geometry, solvers, design, physics
from . import diagnostics as _diagnostics
from . import optomech as _optomech
from . import operators as _ops
from . import bake as _bake
from . import render as _render


def _scene():
    return bpy.context.scene


def _beam_path_json(segs):
    return [{
        "from": s["from"], "to": s["to"],
        "p1": [round(x, 3) for x in s["p1"]], "p2": [round(x, 3) for x in s["p2"]],
        "kind": s["kind"], "power": s["power"],
        "wavelength": s["wavelength"], "parent": s["parent"],
    } for s in segs]


def _trace(scene):
    return tracer.trace_scene(scene, mode=scene.optics.trace_mode,
                              max_segments=scene.optics.max_segments,
                              max_depth=scene.optics.max_depth)


# curated grouping of the public API (the bridge/MCP surface) -- a tool only listed here is annotated; any
# public optics_api function not listed still works and is appended to "other" so this never goes stale.
_TOOL_GROUPS = {
    "read / inspect (the AI's eyes -- call these to SEE the bench, never guess)": [
        "capabilities", "get_state", "diagnose", "propose_corrections", "detect_phenomena", "inspect_beam",
        "inspect_element", "beam_profile", "ao_measure", "get_wavefront", "sensor_capture",
        "check_mechanics", "coupling_efficiency"],
    "build / scene": [
        "build_example", "add_component", "tag_element", "swap_part", "set_param", "set_mount"],
    "design (pure math, no scene change)": [
        "design_telescope", "design_4f", "mode_match", "optics_calc"],
    "place / assemble (opto-mechanics)": [
        "place_relative", "make_cage", "make_tube", "make_rail", "place_on_grid", "place_on_rail",
        "set_grid", "dress_bench"],
    "trace / measure": ["trace_beam", "scan", "bake_beams", "clear_beams"],
    "align (mutates DOFs -- on demand only)": ["align_all", "align_element", "auto_align", "tilt_null"],
    "adaptive optics + surface figure": [
        "ao_command", "ao_close_loop", "ao_close_loop_recon", "ao_kolmogorov", "zonal_render", "pyramid_wfs"],
    "render / export": ["render", "render_sequence", "export_svg"],
}

_WORKFLOWS = [
    "INSPECT-FIRST loop: get_state() -> decide -> set_param/place_relative/align_* -> the beam re-traces; "
    "read get_state()/diagnose() again. Never act blind -- the read tools are your eyes.",
    "Build a bench: build_example(kind)  (22 canonical setups) OR add_component(key)+place_relative(...).",
    "Align: auto_align(actuators,targets) for beam-walk, tilt_null(detector,mirrors) for interferometer fringes.",
    "Adaptive optics: ao_kolmogorov(aberrator,r0) to inject turbulence -> ao_close_loop_recon(sensor,dm) to flatten.",
    "Surface-figure sensing: build_example('surface_figure'[ _native/_diverging]) -> swap_part a mesh onto "
    "SF_Reflector -> zonal_render(sensor='SF_WFS'); inspect with sensor_capture('SF_WFS').",
    "Diagnose before trusting: diagnose() flags beam-clipping / vignetting / beam-underfills-figure / energy "
    "violations. propose_corrections() goes further -- each issue gets a suggested_fix + tool + a "
    "'maybe_intentional_if' hint + fault_confidence. Both are ADVISORY: weigh user intent, then refuse / "
    "partial / accept (a crossed analyzer or a retro-reflection may be the EXPERIMENT, not a fault).",
]

_GOTCHAS = [
    "Both w_mm (beam radius) and clear_aperture are RADII (G.mirror sets clear_aperture=size*0.5). Compare like-for-like.",
    "A finite sensor captures only the beam WITHIN its aperture (rho_max=aperture/w_sensor); a diverging beam "
    "overfills it -> the outer figure is clipped + power 1-exp(-2a^2/w^2) is lost. See sensor_capture().",
    "To illuminate a cm-scale optic with a real ~0.5 mm laser you MUST add a beam EXPANDER (afocal: spacing "
    "f1+f2 SIGNED, M=|f2/f1|) -- raising the source waist is unphysical. diagnose() warns (beam_underfills_figure).",
    "Physics is PROPERTY-DRIVEN: the generic tracer applies Snell/Fresnel/Sellmeier/ABCD from element properties; "
    "change a property (glass, coating, focal) and behaviour changes -- no per-scene code.",
    "The WFS reads the MODAL 15-Zernike channel (a low-pass caricature for high-frequency figure); the ZONAL "
    "'sensor render' is the honest dense companion. swap_part normalizes mesh orientation (solve it empirically).",
    "The trace is deterministic + byte-identical until an align_*/ao_* solver is explicitly called.",
    "The bridge needs Blender running with the add-on + the Optics bridge started (port 9765).",
]


def capabilities():
    """READ ME FIRST. A self-describing manifest for an AI/agent that just connected to this optics bench over
    MCP: the scope, how it works, the tools grouped by purpose (with the READ/inspect tools called out as
    'your eyes'), the common multi-step workflows, the example library, and the gotchas that bite. Returns a
    JSON-able dict; nothing is mutated. Pair with get_state() (the live scene) and diagnose() (advisories)."""
    import sys
    api = sys.modules.get("optics_api") or sys.modules.get(__name__)
    fns = sorted(n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n, None)))
    grouped = set()
    for v in _TOOL_GROUPS.values():
        grouped.update(v)
    other = [f for f in fns if f not in grouped]
    try:
        from . import examples_builtin as _ex
        examples = sorted(_ex.EXAMPLES.keys())
    except Exception:
        examples = []
    return {
        "scope": "A physics-verified optical bench an AI can BUILD, INSPECT, ALIGN, SENSE and RENDER over MCP. "
                 "Geometric single-ray tracer + analytic overlays: Jones/Stokes polarization, Fresnel/Snell, "
                 "Gaussian-beam q/ABCD, 15-Noll-Zernike adaptive optics, nonlinear chi(2), prisms/Sellmeier, "
                 "gratings, detectors, fiber circulator, and surface-figure imprint + dense zonal wavefront.",
        "how_it_works": "Property-driven: each element carries optics properties; the generic tracer applies the "
                        "physics. Loop = get_state() -> act -> the beam re-traces live. Every formula is oracle-verified.",
        "tool_count": len(fns),
        "tool_groups": _TOOL_GROUPS,
        "other_tools": other,
        "workflows": _WORKFLOWS,
        "examples": examples,
        "gotchas": _GOTCHAS,
        "see_also": "mcp/AGENT_GUIDE.md (full guide), docs/CAPABILITIES.md (the complete tree).",
    }


def get_state():
    """Full optical state: every element's world center, ports (world pos+normal),
    mount/DOF, mechanics, params, misalignment, plus the traced beam path."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    report = alignment.refresh_report(scene)
    rep_by = {r["name"]: r for r in report}

    elements, sources, detectors = [], [], []
    for obj in scene.objects:
        op = getattr(obj, "optics", None)
        if not op or not op.is_optical:
            continue
        if op.is_source or op.element_type == 'SOURCE':
            sources.append(obj.name)
        if op.is_detector or op.element_type == 'DETECTOR':
            detectors.append(obj.name)
        ports = [{
            "name": p.name, "role": p.role,
            "world_pos": [round(x, 4) for x in geometry.world_port(obj, p.local_position)],
            "world_normal": [round(x, 4) for x in geometry.world_normal(obj, p.local_normal)],
            "clear_aperture": round(p.clear_aperture, 3),
        } for p in op.ports]
        dofs = [{
            "kind": d.kind, "axis": [round(x, 3) for x in d.axis_local],
            "pivot": [round(x, 3) for x in d.pivot_local],
            "min": round(d.min_val, 3), "max": round(d.max_val, 3),
            "current": round(d.current, 4),
        } for d in op.dofs]
        mech = [{"kind": l.kind, "target": l.target.name if l.target else None,
                 "state": l.state, "detail": l.detail} for l in op.mech]
        m = obj.matrix_world
        elements.append({
            "name": obj.name, "type": op.element_type,
            "world_center": [round(x, 4) for x in m.translation],
            "matrix_world": [[round(m[r][c], 6) for c in range(4)] for r in range(4)],
            "ports": ports,
            "mount": {"type": op.mount_type, "preset": op.mount_preset, "dofs": dofs,
                      "support_system": getattr(op, "support_system", 'POST')},
            # the one genuine pose-dependency edge: which element this one follows (place_relative)
            "anchor": op.anchor.name if getattr(op, "anchor", None) else None,
            "base_pose_set": bool(getattr(op, "base_pose_set", False)),
            "mech": mech,
            "params": {
                "focal_length": round(op.focal_length, 4), "split_ratio": round(op.split_ratio, 4),
                "prism_angle": round(op.prism_angle, 3), "clear_aperture": round(op.clear_aperture, 3),
                "reflectivity": round(op.reflectivity, 3), "wavelength": round(op.wavelength, 3),
                "refractive_index": round(op.refractive_index, 4),
            },
            "misalignment": {"pos_err_mm": round(op.misalign_pos_mm, 4),
                             "ang_err_deg": round(op.misalign_ang_deg, 4),
                             "state": op.align_state, "detail": op.align_detail},
        })
    return {
        "units": "mm", "scale_length": scene.unit_settings.scale_length,
        "engine_eevee_id": _render.resolve_eevee_id(),
        "elements": elements, "sources": sources, "detectors": detectors,
        "beam_path": _beam_path_json(tracer.cached_segments), "report": report,
        # Bench breadboard grid (pitch/origin/extent + occupied holes) so an MCP agent or a
        # human knows exactly where parts seat. None when the bench is not dressed.
        "bench": _optomech.grid_info(scene),
        # Cage assemblies (16/30/60 mm): which optics share rods, the cage axis + rod length.
        "cages": _optomech.cage_info(scene),
        # Lens-tube assemblies (SM05/SM1/SM2): which optics share a barrel, thread + bore + length.
        "tubes": _optomech.tube_info(scene),
        # Rail assemblies (dovetail): which optics ride one rail, the axis + each carrier's position.
        "rails": _optomech.rail_info(scene),
        # Geometric validation: physical-invariant violations on the dressed bench (mount below its
        # holder, colliding posts). Empty == valid. The agent's programmatic check on the assembly.
        "warnings": _optomech.validate(scene),
        # Wave-1 beam-physics error detection (A1-A5): beam_clipped / vignetting / dark_detector /
        # orphan_source / energy_violation / mount_limit, each {kind, element, detail, severity}.
        # READ-ONLY post-pass over the SAME cached trace above -- the beam path is unaffected.
        "diagnostics": _diagnostics.run_diagnostics(scene),
    }


def trace_beam(mode=None):
    scene = _scene()
    if mode:
        try:
            scene.optics.trace_mode = mode      # EnumProperty: a bad string would raise a TypeError
        except (TypeError, ValueError) as e:
            return {"error": "invalid trace mode '%s': %s" % (mode, e)}
    tracer.cached_segments = _trace(scene)
    return {"segments": len(tracer.cached_segments),
            "beam_path": _beam_path_json(tracer.cached_segments)}


def diagnose():
    """Run the Wave-1 P0 bench-intelligence error-detection gates (A1-A5) over the
    current trace: beam_clipped (hard miss), vignetting (Gaussian wing clip),
    dark_detector / orphan_source, energy_violation (per-node + global budget), and
    mount_limit (DOF range exhaustion). READ-ONLY -- the trace is unaffected.
    Returns {ok, diagnostics:[{kind, element, detail, severity}], counts:{BAD,WARN}}."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    diags = _diagnostics.run_diagnostics(scene)
    bad = sum(1 for d in diags if d.get("severity") == 'BAD')
    warn = sum(1 for d in diags if d.get("severity") == 'WARN')
    return {"ok": True, "diagnostics": diags, "counts": {"BAD": bad, "WARN": warn}}


def propose_corrections():
    """ADVISORY correction proposals over the current trace -- diagnose() that also suggests a FIX for
    each issue, but applies NOTHING. Each proposal carries {issue, element, detail, severity,
    suggested_fix, tool, maybe_intentional_if, fault_confidence, advisory}. The proposals are FEEDBACK,
    not commands: weigh each against USER INTENT (did they ask for this on purpose? -- see
    'maybe_intentional_if') and choose REFUSE (intended), PARTIAL (apply some), or ACCEPT (apply the
    clearly-unintended ones). 'fault_confidence' is how likely the issue is a genuine fault vs a design
    choice (e.g. crossed_polarizer ~0.3 = usually an intentional extinction measurement;
    energy_violation ~0.9 = almost always a config bug). The honest default is to SURFACE, not silently
    fix. READ-ONLY: the trace is byte-identical. {ok, advisory, guidance, proposals, counts}."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    props = _diagnostics.propose_corrections(scene)
    bad = sum(1 for p in props if p.get("severity") == 'BAD')
    warn = sum(1 for p in props if p.get("severity") == 'WARN')
    return {"ok": True, "advisory": True,
            "guidance": ("Proposals are ADVISORY and NOT applied. For each, weigh whether the user "
                         "intended this configuration (see 'maybe_intentional_if'); then ACCEPT (apply "
                         "the clearly-unintended ones), PARTIAL (apply some), or REFUSE (all intended). "
                         "Higher fault_confidence => more likely a genuine fault than a design choice. "
                         "Never auto-apply a low-confidence proposal without confirming intent."),
            "proposals": props, "counts": {"BAD": bad, "WARN": warn}}


def detect_phenomena():
    """ADVISORY: the recognized optical PHENOMENA whose conditions the current trace MEETS -- two-beam
    interference, off-axis hologram recording (carrier fringe spacing Lambda = lambda/(2 sin(theta/2)),
    physics_verify ok=true), and more as added. READ-ONLY: the sim FLAGS that the geometry/coherence
    conditions are satisfied (e.g. "a reference + object beam cross at 8 deg on the camera -> off-axis
    hologram"), it does not auto-produce anything -- the same surface-don't-act stance as diagnose().
    {ok, phenomena:[{phenomenon, where, detail, crossing_angle_deg, fringe_spacing_mm, visibility,
    confidence}], count}."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    phen = _diagnostics.detect_phenomena(scene)
    return {"ok": True, "phenomena": phen, "count": len(phen)}


def design_telescope(f1, f2):
    """Design an afocal two-lens telescope / beam-expander (B2). PURE -- no scene
    mutation. Given objective focal `f1` and eyepiece/relay focal `f2` it returns the
    afocal lens separation and the magnifications:
      {ok, sep: f1+f2, magnification: -f2/f1, angular_mag: -f1/f2,
       beam_expansion: |f2/f1|, type: 'keplerian'|'galilean', abcd}
    where `abcd` is the composed (oracle-verified) afocal system matrix
    [[-f2/f1, f1+f2], [0, -f1/f2]] (C=0 -> a collimated input stays collimated when
    the lenses are placed `sep` apart). Returns {ok:False, error:...} for a zero /
    non-finite focal."""
    return design.design_telescope(f1, f2)


def design_4f(f1, f2):
    """Design a full 4f relay (B2). PURE -- no scene mutation. Object at the front
    focal plane of L1, lenses `f1+f2` apart, image at the back focal plane of L2:
      {ok, seps: [f1, f1+f2, f2], total_length: 2*(f1+f2), transverse_mag: -f2/f1,
       beam_expansion: |f2/f1|, abcd}
    where `abcd` is the L1->L2 afocal system matrix. Returns {ok:False, error:...}
    for a zero / non-finite focal."""
    return design.design_4f(f1, f2)


def mode_match(w0_in, s_in, w0_t, z_t, wavelength_nm, m2=1.0):
    """Solve the single thin-lens that mode-matches a Gaussian (waist `w0_in`, located
    `s_in` mm before the lens) into a target Gaussian (waist `w0_t` at distance `z_t` mm
    past the lens) -- the lens-to-cavity/fiber design solve (B3). PURE -- no scene mutation.

    Returns {ok, f, f_alt, s_lens, s_lens_alt, m, zR, achieved_w0, achieved_z, coupling,
    offset}: `f` is the solved focal (with `f_alt` the conjugate-plane second root), `s_lens`
    the REQUIRED input-waist-to-lens distance, and achieved_w0/achieved_z are obtained by
    actually propagating the input q through the solved lens (so they self-check against
    (w0_t, z_t)). `coupling` is the power-coupling efficiency into the target mode (== 1 on a
    clean solve). Returns {ok:False, error:...} for a non-physical input or an UNREACHABLE
    target (no real focal exists -- e.g. demagnifying too close to the lens); no focal is
    fabricated. All lengths mm, wavelength nm."""
    return design.mode_match_lens(w0_in, s_in, w0_t, z_t, wavelength_nm, m2=m2)


def coupling_efficiency(w_in, w_t, offset=0.0):
    """Power-coupling efficiency eta of a Gaussian mode (waist `w_in`) into a target Gaussian
    mode (waist `w_t`) transversely offset by `offset` (all mm) -- the fiber/cavity coupling
    metric (B3). PURE. eta = [2 w_in w_t/(w_in^2+w_t^2)]^2 * exp(-2 offset^2/(w_in^2+w_t^2)):
    symmetric, dimensionless, bounded (0,1], == 1 only at w_in==w_t and offset==0. Returns the
    scalar eta, or {ok:False, error:...} for a non-physical waist."""
    return design.coupling_efficiency(w_in, w_t, offset)


# --- pure scalar optics calculators, exposed to the AI through one dispatch tool (optics_calc) -------
# A registry so a new physics helper becomes AI-callable by ONE line here -- no extra MCP/bridge edit
# (the bridge auto-allows any public optics_api function). Each entry: name -> (callable, ordered arg
# names, one-line doc). Return values are JSON-able scalars / tuples / dicts.
def _thick_lens_efl(n, R1_mm, R2_mm, t_mm):
    m = physics.abcd_thick_lens(n, R1_mm, R2_mm, t_mm)
    return None if m[1][0] == 0.0 else -1.0 / m[1][0]


_CALCULATORS = {
    "brewster_angle": (physics.brewster_angle, ("n1", "n2"), "Brewster angle atan(n2/n1), deg"),
    "critical_angle": (physics.critical_angle, ("n1", "n2"), "TIR critical angle asin(n2/n1), deg (None if n2>=n1)"),
    "abbe_number": (physics.abbe_number, ("glass",), "Abbe number Vd of a catalog glass name"),
    "sellmeier_n": (physics.sellmeier_n, ("wl_nm", "glass", "temp_C"), "refractive index n(lambda[, T degC])"),
    "thin_lens_image": (physics.thin_lens_image, ("f", "o"), "(image_distance, magnification) for 1/o+1/i=1/f"),
    "thick_lens_efl": (_thick_lens_efl, ("n", "R1_mm", "R2_mm", "t_mm"), "thick-lens effective focal length, mm"),
    "cavity_stability": (physics.cavity_stability, ("g1", "g2"), "(g1*g2, stable?) for a two-mirror cavity"),
    "cavity_finesse": (physics.cavity_finesse, ("R",), "Fabry-Perot finesse pi*sqrt(R)/(1-R)"),
    "cavity_fsr_nm": (physics.cavity_fsr_nm, ("wl_nm", "L_mm", "n"), "Fabry-Perot free spectral range, nm"),
    "grating_angle": (physics.grating_angle, ("lines_per_mm", "m", "wl_nm", "theta_i_deg"), "diffracted order angle, deg"),
    "grating_resolving_power": (physics.grating_resolving_power, ("lines_per_mm", "illuminated_mm", "m"), "R = m*N"),
    "ar_quarter_wave_reflectance": (physics.ar_quarter_wave_reflectance, ("n0", "n1", "ns"), "single quarter-wave AR layer R"),
    "fiber_na": (physics.fiber_na, ("n_core", "n_clad"), "step-index fiber numerical aperture"),
    "fiber_v_number": (physics.fiber_v_number, ("core_radius_um", "na", "wl_nm"), "fiber V (single-mode if < 2.405)"),
    "fiber_num_modes": (physics.fiber_num_modes, ("v",), "approx guided-mode count ~ V^2/2"),
    "aom_deflection": (physics.aom_deflection, ("wl_nm", "f_acoustic_hz", "v_sound_mps"), "acousto-optic deflection, rad"),
    "pockels_vpi": (physics.pockels_vpi, ("wl_nm", "n0", "r_pm_per_V"), "Pockels half-wave voltage, V"),
    "photon_energy_eV": (physics.photon_energy_eV, ("wl_nm",), "photon energy hc/lambda, eV"),
    "coherence_length_mm": (physics.coherence_length_mm, ("wavelength_nm", "linewidth_nm"), "temporal coherence length, mm"),
    "gaussian_divergence": (physics.gaussian_divergence, ("w0_mm", "wavelength_nm", "m2"), "Gaussian far-field half-angle, rad"),
}


def optics_calc(quantity=None, **params):
    """Evaluate a PURE optics calculator (no scene needed) -- the AI's optics formula toolbox: Brewster /
    critical angle, Sellmeier n(lambda[,T]), thin/thick lens, cavity finesse/FSR/stability, grating
    angle/resolving-power, AR coating, fiber NA/V/modes, AOM deflection, Pockels Vpi, photon energy,
    coherence length, Gaussian divergence. Call with NO quantity to list every calculator + its args;
    else pass quantity plus its parameters, e.g. optics_calc('brewster_angle', n1=1.0, n2=1.5).
    Returns {ok, quantity, value, doc} or {ok:False, error, expects}."""
    if not quantity:
        return {"ok": True, "calculators": {k: {"args": list(v[1]), "doc": v[2]} for k, v in sorted(_CALCULATORS.items())}}
    if quantity not in _CALCULATORS:
        return {"ok": False, "error": "unknown quantity '%s'" % quantity, "available": sorted(_CALCULATORS)}
    fn, argnames, doc = _CALCULATORS[quantity]
    try:
        value = fn(**{k: params[k] for k in argnames if k in params})
    except TypeError as exc:
        return {"ok": False, "error": str(exc), "expects": list(argnames), "doc": doc}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": True, "quantity": quantity, "value": value, "doc": doc}


def tag_element(name, element_type=None, auto_ports=True):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    obj.optics.is_optical = True
    if element_type:
        obj.optics.element_type = element_type
    if auto_ports:
        _ops.do_auto_detect(obj)
    return {"name": name, "type": obj.optics.element_type, "ports": len(obj.optics.ports)}


def set_mount(name, preset):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    ok, msg = mounts.apply_preset(obj, preset)
    return {"ok": ok, "msg": msg}


def align_element(name):
    scene = _scene()
    obj = scene.objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    res = alignment.align_element(scene, obj)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return res


def align_all():
    scene = _scene()
    res = alignment.align_all(scene)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return {"aligned": [{"name": n,
                         **{k: (round(v, 3) if isinstance(v, float) else v)
                            for k, v in r.items()}} for n, r in res]}


def auto_align(actuators=None, targets=None, gain=1.0, eps=0.02, max_iters=8):
    """On-demand auto-aligner: the linearized influence-matrix corrector (A6/A7/A8).

    Drives steering DOFs until the beam is centered on the reference apertures.
    GENERIC: with no arguments it auto-picks every kinematic (tip/tilt) element
    and the iris/pinhole/detector planes downstream of them, then walks the beam
    onto them. With arguments it steers exactly what you name:

      * `actuators`: list of element names (use all their tip/tilt/translation
        DOFs) or [name, kind] / [name, [kinds]] pairs to pick specific DOFs.
      * `targets`: list of reference-aperture element names (irises / detectors).

    This MOVES the named DOFs (that is the point) but only when called - a normal
    trace never invokes it. Returns
    {ok, residual_before, residual_after, iterations, converged, history, ...}."""
    scene = _scene()
    res = solvers.auto_align(scene, actuators=actuators, targets=targets,
                             gain=gain, eps=eps, max_iters=max_iters)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return res


def tilt_null(detector=None, mirrors=None, gain=1.0, eps=0.04, max_iters=8, piston_steps=21):
    """Interferometer tilt-null solver (B4): the benchtop "spread the fringes to a single
    null" ritual, automated. Recovers the relative wavefront TILT between two interfering
    arms from the 2-D fringe pattern at `detector` (the fringe spatial frequency fx = tilt/lambda),
    drives the two steering mirror tip/tilt DOFs until the fringe frequency -> 0 (dense
    tilt-fringes collapse to one broad fringe), then runs a 1-DOF piston/OPD search to peak
    the fringe visibility.

    GENERIC: with no arguments it auto-picks the recombination detector (the lit terminal with
    the most interfering beams) and the recombining-arm mirror's tip+tilt. Or name them:
      * `detector`: the recombination detector element name.
      * `mirrors`: steering actuators -- element names / [name, kind] / [name, [kinds]] pairs.

    This MOVES the steering (and piston) DOFs -- only when called; a normal trace never invokes
    it (the 18 examples trace byte-identical until this runs). Returns
    {ok, detector, tilt_before_deg/after_deg, fringe_freq_before/after (cyc/mm),
    fringe_count_before/after, visibility_before/after, iterations, converged, history,
    controls, piston, floor, sensor}."""
    scene = _scene()
    res = solvers.tilt_null(scene, detector=detector, mirrors=mirrors, gain=gain,
                            eps=eps, max_iters=max_iters, piston_steps=piston_steps)
    tracer.cached_segments = _trace(scene)
    alignment.refresh_report(scene)
    return res


def check_mechanics():
    return {"worst": mounts.check_mechanics(_scene())}


def set_param(name, key, value):
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    if not hasattr(obj.optics, key):
        return {"error": "no such param: %s" % key}
    # Only scalar/enum params are settable here; refuse pointers (anchor), collections
    # (ports/dofs/mech) and vectors (base_pose) so a remote/API call can't corrupt the
    # element's structure or trip an RNA type error deep in Blender.
    cur = getattr(obj.optics, key)
    if not isinstance(cur, (bool, int, float, str)):
        return {"error": "param '%s' is not a settable scalar" % key}
    try:
        setattr(obj.optics, key, value)
    except Exception as e:
        return {"error": "could not set %s=%r: %s" % (key, value, e)}
    return {"ok": True, "name": name, key: value}


def bake_beams(radius=0.6):
    return {"baked": _bake.bake_beams(bpy.context, radius=radius)}


def clear_beams():
    tracer.cached_segments = []
    return {"cleared": _bake.clear_baked(_scene())}


def render_sequence(frames=48, motion='ORBIT', out_dir=None, engine='EEVEE',
                    turns=1.0, elevation=0.55, encode='auto', fps=24):
    """Render a camera-orbit PNG sequence of the current setup (headless animation pipeline) and,
    if ffmpeg is present, encode an mp4 (best-effort; the PNG sequence is always produced). Bakes
    the beam first so it shows. Returns {frames, dir, pattern, ffmpeg, video}."""
    from . import anim
    scene = _scene()
    _bake.ensure_beams(bpy.context)
    return anim.render_sequence(scene, frames=frames, motion=motion, out_dir=out_dir,
                                engine=engine, turns=turns, elevation=elevation,
                                encode=encode, fps=fps)


def render(preset='preview', camera='HERO', filepath=None):
    scene = _scene()
    _bake.ensure_beams(bpy.context)
    _render.set_camera(scene, camera.upper())
    if preset == 'final':
        _render.setup_final(scene)
    else:
        _render.setup_preview(scene)
    if filepath:
        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)
        return {"rendered": filepath, "engine": scene.render.engine}
    return {"configured": preset, "engine": scene.render.engine}


def build_example(kind='mach_zehnder'):
    """Build a canonical setup (one of the 14 builders in examples_builtin.EXAMPLES: mach_zehnder,
    michelson, hong_ou_mandel, bell, adaptive_optics, newton_rings, periscope, cage_system, tube_system,
    rail_system, hybrid_system, microscope, dhm, aom) from generic components, then trace it."""
    from . import examples_builtin as ex
    if kind not in ex.EXAMPLES:
        return {"error": "unknown example '%s'; choose from %s" % (kind, list(ex.EXAMPLES))}
    name = ex.build(kind, bpy.context)
    res = trace_beam()
    return {"built": kind, "collection": name, "segments": res["segments"]}


def add_component(key, location=(0.0, 0.0, 0.0)):
    """Spawn a catalog component by key (or its generic mesh-free fallback). {name, msg}."""
    from . import library
    obj, msg = library.add_component(key, tuple(location))
    if obj is None:                             # unknown key -> a real error, not a {name: None} success
        return {"error": msg}
    return {"name": obj.name, "msg": msg}


def swap_part(name, filepath, refit_ports=False):
    """Replace element `name`'s mesh from an STL/OBJ (or STEP/IGES via FreeCAD), keeping
    its optical slot (ports / pose / mount / beam role). {ok, msg, name}."""
    import os
    from . import assembly
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    try:
        mesh_path, _entry = assembly._importable_path('FILE', "", filepath)
    except Exception as e:
        return {"error": str(e)}
    try:                                        # import is the failure-prone step (corrupt/empty file)
        ok, msg = assembly.swap_mesh_on(obj, mesh_path, refit=refit_ports)
    except (RuntimeError, OSError) as e:
        return {"error": "swap failed: %s" % e}
    if ok:
        obj.optics.part_key = os.path.basename(filepath)
        tracer.cached_segments = _trace(_scene())
    return {"ok": ok, "msg": msg, "name": name}


def place_relative(name, reference, axis='BEAM', distance=50.0, link=True, align_rotation=True):
    """Place element `name` a distance (mm) from `reference` along a chosen axis or the
    reference's OUT beam; link=True makes it follow the reference live. {ok, name}."""
    obj = _scene().objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    if not (getattr(obj, "optics", None) and obj.optics.is_optical):
        return {"error": "'%s' is not an optical element (tag it first)" % name}
    if _scene().objects.get(reference) is None:
        return {"error": "reference not found: %s" % reference}
    bpy.context.view_layer.objects.active = obj
    try:
        res = bpy.ops.optics.place_relative(reference=reference, axis=axis, distance=distance,
                                            link=link, align_rotation=align_rotation, frame='REFERENCE')
    except (RuntimeError, TypeError) as e:     # bad axis enum / poll failure -> structured error
        return {"error": "place_relative: %s" % e}
    tracer.cached_segments = _trace(_scene())
    if 'FINISHED' not in res:
        return {"error": "place_relative cancelled (BEAM axis needs an OUT port on the reference?)"}
    return {"ok": True, "name": name, "reference": reference}


def set_grid(pitch_mm=None, standard=None):
    """Set the breadboard hole-grid standard/pitch. `standard` in {METRIC (25 mm/M6),
    IMPERIAL (1"/1/4-20), CUSTOM}; `pitch_mm` sets a custom pitch (implies CUSTOM). Re-dresses
    the bench if it is currently dressed so the new grid takes effect. Returns the active grid."""
    scene = _scene()
    op = scene.optics
    if standard is not None:
        std = str(standard).upper()
        if std not in ('METRIC', 'IMPERIAL', 'CUSTOM'):
            return {"error": "standard must be METRIC, IMPERIAL or CUSTOM (got %r)" % standard}
        op.bench_grid_units = std
    if pitch_mm is not None:
        try:
            p = float(pitch_mm)
        except (TypeError, ValueError):
            return {"error": "pitch_mm must be a number (got %r)" % pitch_mm}
        if p < 1.0:
            return {"error": "pitch_mm must be >= 1.0 mm (got %s)" % pitch_mm}
        op.bench_grid_units = 'CUSTOM'
        op.bench_grid_mm = p
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    return {"ok": True, "standard": op.bench_grid_units, "pitch_mm": round(op.bench_grid_mm, 4),
            "bench": _optomech.grid_info(scene)}


def dress_bench(enable=True):
    """Spawn (enable=True) or remove (enable=False) the procedural breadboard + posts + pedestals
    + mount rings. The grid is then exposed via get_state()['bench']. Trace is unaffected (optics
    are not moved). Returns the object count and the grid."""
    scene = _scene()
    if enable:
        n = _optomech.dress(scene)
        if n == 0:
            return {"error": "no optical elements to dress (build or tag elements first)"}
        return {"ok": True, "dressed": True, "objects": n, "bench": _optomech.grid_info(scene)}
    _optomech.strip(scene)
    return {"ok": True, "dressed": False}


def place_on_grid(name, col, row, link_drop=True):
    """Move optical element `name` so it sits over breadboard hole (col, row), keeping its z
    height and orientation. This is grid-aware placement for building a layout (it DOES move the
    part, so the trace updates). The bench must be dressed first (the grid origin comes from the
    current dressing). Use get_state()['bench'] to read available holes. Returns the new center."""
    scene = _scene()
    obj = scene.objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    if not (getattr(obj, "optics", None) and obj.optics.is_optical):
        return {"error": "'%s' is not an optical element (tag it first)" % name}
    if not _optomech.is_dressed(scene):
        return {"error": "bench is not dressed -- call dress_bench() first so the grid is defined"}
    try:
        col = int(col); row = int(row)
    except (TypeError, ValueError):
        return {"error": "col and row must be integers"}
    xy = _optomech.hole_world_xy(scene, col, row)
    if xy is None:
        gi = _optomech.grid_info(scene)
        return {"error": "hole (%d,%d) out of range 0..%d x 0..%d" % (col, row, gi["cols"] - 1, gi["rows"] - 1)}
    # capture the element's mount base if it has one, then move XY (preserve z + orientation)
    obj.location.x += xy[0] - obj.matrix_world.translation.x
    obj.location.y += xy[1] - obj.matrix_world.translation.y
    bpy.context.view_layer.update()
    if link_drop:
        _optomech.dress(scene)   # re-seat posts/pedestals under the moved part
    tracer.cached_segments = _trace(scene)
    m = obj.matrix_world
    return {"ok": True, "name": name, "hole": [col, row],
            "world_center": [round(x, 4) for x in m.translation]}


def make_cage(members, size_mm=30, cage_id=None):
    """Group collinear optical elements into a cage assembly: they share 4 rods (Ø6 mm on a 30 mm
    square for SM1, etc.) and one cage post instead of an individual post each. `members` is a list
    of element names; `size_mm` in {16, 30, 60}. Re-dresses if the bench is dressed. The cage
    layout is exposed in get_state()['cages']. Does NOT move the optics, so the trace is unchanged."""
    scene = _scene()
    sysmap = {16: 'CAGE_16', 30: 'CAGE_30', 60: 'CAGE_60'}
    try:
        size = int(size_mm)
    except (TypeError, ValueError):
        return {"error": "size_mm must be 16, 30 or 60"}
    if size not in sysmap:
        return {"error": "size_mm must be 16, 30 or 60 (got %s)" % size_mm}
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    cid = cage_id or ("cage_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = sysmap[size]
        o.optics.cage_id = cid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "cage_id": cid, "size_mm": size, "members": [o.name for o in objs],
            "cages": _optomech.cage_info(scene)}


def make_tube(members, thread='SM1', tube_id=None):
    """Stack collinear in-line optics into one SM lens-tube barrel (they share one barrel + one post
    instead of an individual post each). `members` is a list of element names; `thread` in
    {SM05, SM1, SM2} (Ø1/2", Ø1", Ø2" optics). The tube is exposed in get_state()['tubes']. Does NOT
    move the optics, so the trace is unchanged."""
    scene = _scene()
    sysmap = {'SM05': 'TUBE_SM05', 'SM1': 'TUBE_SM1', 'SM2': 'TUBE_SM2'}
    key = str(thread).upper()
    if key not in sysmap:
        return {"error": "thread must be SM05, SM1 or SM2 (got %r)" % thread}
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    tid = tube_id or ("tube_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = sysmap[key]
        o.optics.tube_id = tid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "tube_id": tid, "thread": key, "members": [o.name for o in objs],
            "tubes": _optomech.tube_info(scene)}


def make_rail(members, rail_id=None):
    """Put collinear elements on one dovetail rail: each rides a carrier on the shared rail (instead
    of a bare post on the board), so they translate along one straight track. `members` is a list of
    element names. Exposed in get_state()['rails'] (carrier positions in s_mm). Does NOT move the
    optics, so the trace is unchanged. Use place_on_rail(name, s_mm) to slide one along the rail."""
    scene = _scene()
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    objs = []
    for nm in members:
        o = scene.objects.get(nm)
        if not o or not (getattr(o, "optics", None) and o.optics.is_optical):
            return {"error": "not an optical element: %s" % nm}
        objs.append(o)
    rid = rail_id or ("rail_%s" % objs[0].name)
    for o in objs:
        o.optics.support_system = 'RAIL'
        o.optics.rail_id = rid
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "rail_id": rid, "members": [o.name for o in objs],
            "rails": _optomech.rail_info(scene)}


def place_on_rail(name, s_mm):
    """Slide rail-mounted element `name` to position s_mm along its rail (s=0 at the rail start).
    Moves the optic along the rail axis only, so the trace updates. The element must be on a rail
    (make_rail first). Read get_state()['rails'] for the current carrier positions."""
    scene = _scene()
    o = scene.objects.get(name)
    if not o:
        return {"error": "object not found: %s" % name}
    if getattr(o.optics, "support_system", 'POST') != 'RAIL':
        return {"error": "'%s' is not on a rail (call make_rail first)" % name}
    try:
        s = float(s_mm)
    except (TypeError, ValueError):
        return {"error": "s_mm must be a number"}
    members = _optomech.rail_groups(scene).get(getattr(o.optics, "rail_id", "") or "", [o])
    ax, cxy, ts = _optomech.rail_geom(members)
    start = cxy + ax * min(ts)                       # s = 0 reference
    target = start + ax * s
    cur = o.matrix_world.translation
    o.location.x += target.x - cur.x
    o.location.y += target.y - cur.y
    bpy.context.view_layer.update()
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    m = o.matrix_world
    return {"ok": True, "name": name, "s_mm": round(s, 3),
            "world_center": [round(x, 4) for x in m.translation]}


def scan(kind='STAGE', lo=0.0, hi=0.002, steps=120, element=None):
    """Sweep a parameter (STAGE OPD / WAVEPLATE angle / WAVELENGTH); writes a plot PNG +
    CSV to the temp dir and into the sensor window. Set `element` to the swept part."""
    if element:
        obj = _scene().objects.get(element)
        if obj is None:
            return {"error": "element not found: %s" % element}
        bpy.context.view_layer.objects.active = obj
    try:
        res = bpy.ops.optics.scan(kind=kind, lo=lo, hi=hi, steps=steps)
    except (RuntimeError, TypeError) as e:     # bad kind enum / poll failure -> structured error
        return {"error": "scan: %s" % e}
    if 'FINISHED' not in res:
        return {"error": "scan cancelled (no detectors, or the active element lacks the swept knob?)"}
    return {"ok": True, "kind": kind, "steps": steps}


def ao_measure(sensor):
    """Read the wavefront a sensor PHYSICALLY measures (waves): the modal residual (turbulence / DM /
    surface figure) PLUS the beam's OWN curvature defocus from R(z). A clean diverging/converging beam
    now reads its real defocus instead of a (wrong) flat RMS=0; a collimated beam still reads its modal
    residual only. {zernike, rms, rms_modal, beam_defocus, beam_roc_mm, n_beams[, dominant_frac]} --
    ``rms`` is the total the sensor integrates, ``rms_modal`` the DM-correctable part the AO loop drives
    to zero, ``n_beams`` how many beams reach the sensor (the read is the strongest; >1 means a weaker
    arm/stray is dropped)."""
    from . import ao, physics
    tracer.cached_segments = _trace(_scene())
    wfs = bpy.data.objects.get(sensor)
    ap = (getattr(wfs.optics, 'clear_aperture', 0.0) or 0.0) if (wfs and getattr(wfs, 'optics', None)) else 0.0
    c, info = ao._sensor_wavefront(tracer.cached_segments, sensor, ap)
    if c is None:
        return {"error": "no beam at wavefront sensor '%s'" % sensor}
    out = {"sensor": sensor, "zernike": [round(x, 4) for x in c],
           "rms": round(physics.wavefront_rms(c), 4),
           "rms_modal": round(info.get("modal_rms", 0.0), 4),
           "beam_defocus": round(info.get("defocus_waves", 0.0), 4),
           "n_beams": info.get("n_beams", 1)}
    R = info.get("beam_roc_mm")
    if R is not None:
        out["beam_roc_mm"] = round(R, 1)
    if info.get("n_beams", 1) > 1:
        out["dominant_frac"] = round(info.get("dominant_frac", 1.0), 3)
    return out


def get_wavefront(sensor):
    """Alias of ao_measure: a wavefront sensor's reconstructed wavefront (Zernike + RMS)."""
    return ao_measure(sensor)


def pyramid_wfs(sensor, px=128, filepath=""):
    """Read a wavefront sensor as a PYRAMID WFS: instead of the modal Zernike vector (ao_measure /
    Shack-Hartmann), report the local wavefront SLOPE -- the 4-pupil intensity differences a pyramid
    sensor encodes as Sx = dW/dx, Sy = dW/dy. Reads the same wavefront (modal aberr PLUS the beam's own
    curvature defocus), computes the normalized slope maps, writes a slope-FIELD PNG (hue = slope
    direction, value = magnitude) and publishes it to the sensor's monitor. A pure defocus reads a RADIAL
    slope (dZ4/dx = 4 sqrt3 x, physics_verify ok=true). Tier-1 GEOMETRIC: the chief-ray tracer does not
    propagate the pupil-plane field, so this is the gradient a pyramid INTEGRATES, not a diffractive
    4-pupil image. {sensor, wavefront_rms, slope_x_rms, slope_y_rms, slope_rms, beam_defocus, n_beams, px, png}."""
    import os
    import numpy as np
    from . import ao, monitor, physics
    scene = _scene()
    segs = _trace(scene)
    tracer.cached_segments = segs
    wfs = bpy.data.objects.get(sensor)
    ap = (getattr(wfs.optics, 'clear_aperture', 0.0) or 0.0) if (wfs and getattr(wfs, 'optics', None)) else 0.0
    coeffs, info = ao._sensor_wavefront(segs, sensor, ap)
    if coeffs is None:
        return {"error": "no beam at wavefront sensor '%s'" % sensor}
    px = max(int(px) or 128, 32)
    sig = ao.pyramid_signals(coeffs, px)
    img = np.flipud(ao.pyramid_slope_image(sig))
    h, wd = img.shape[0], img.shape[1]
    bi = bpy.data.images.get("pyramid_slope") or bpy.data.images.new("pyramid_slope", wd, h, alpha=True)
    if tuple(bi.size) != (wd, h):
        bpy.data.images.remove(bi)
        bi = bpy.data.images.new("pyramid_slope", wd, h, alpha=True)
    bi.pixels.foreach_set(img.astype('float32').ravel())
    out = filepath or os.path.join(bpy.app.tempdir or "/tmp", "pyramid_slope.png")
    bi.filepath_raw = out
    bi.file_format = 'PNG'
    bi.save()
    if wfs is not None:
        cap = ("PYRAMID %s  slope RMS=%.4f (Sx %.4f, Sy %.4f) waves/pupil  RMS=%.3f waves"
               % (sensor, sig["slope_rms"], sig["sx_rms"], sig["sy_rms"], physics.wavefront_rms(coeffs)))
        monitor.set_frame(sensor, ao.pyramid_slope_image(sig), cap)
        scene.optics.monitor_show = True
    tracer._tag_redraw()
    return {"sensor": sensor, "wavefront_rms": round(physics.wavefront_rms(coeffs), 4),
            "slope_x_rms": round(sig["sx_rms"], 5), "slope_y_rms": round(sig["sy_rms"], 5),
            "slope_rms": round(sig["slope_rms"], 5), "beam_defocus": round(info.get("defocus_waves", 0.0), 4),
            "n_beams": info.get("n_beams", 1), "px": px, "png": out}


def zonal_render(sensor="", element="", px=0, filepath=""):
    """DENSE ZONAL surface-figure 'sensor render': the raw wavefront map a WAVEFRONT SENSOR reads from the
    reflective element whose reflected beam reaches it (pass ``sensor`` -- the honest path, requires the beam
    to actually land on the WFS), or a named reflective ``element`` directly. Bypasses the 15-mode modal
    low-pass, so high-spatial-frequency figure survives; samples the footprint as the real Gaussian beam.
    Writes a PNG (``filepath`` or Blender tempdir) and publishes the map to the sensor's monitor.
    {element, sensor, rms_gauss, rms_uniform, footprint_mm, hit_frac, nyquist_lp_mm, px, png}."""
    import os
    import numpy as np
    from . import ao, monitor
    scene = _scene()
    segs = _trace(scene)
    tracer.cached_segments = segs
    px = int(px) if px else 0
    if sensor:
        wfs = scene.objects.get(sensor)
        if wfs is None:
            return {"error": "sensor not found: %s" % sensor}
        p = px or int(getattr(wfs.optics, "imprint_zonal_px", 160) or 160)
        fld = ao.zonal_wavefront_at_sensor(scene, sensor, segs, px=p)
        if fld is None:
            return {"error": "no reflective (imprint) element's beam reaches '%s' -- give the laser an angle "
                             "so a figured reflector's reflection lands on the sensor" % sensor}
        elem = fld.get("element")
    elif element:
        E = scene.objects.get(element)
        if E is None or getattr(E, "optics", None) is None or E.optics.element_type not in ('MIRROR', 'PRISM_MIRROR'):
            return {"error": "'%s' is not a reflective mirror element" % element}
        p = px or int(getattr(E.optics, "imprint_zonal_px", 160) or 160)
        fld = ao.zonal_wavefront_at(scene, element, segs, px=p)
        if fld is None:
            return {"error": "no usable beam footprint on '%s'" % element}
        elem = element
        sensor = next((s.get("to") for s in segs if s.get("from") == element
                       and scene.objects.get(s.get("to") or "") is not None
                       and getattr(scene.objects[s["to"]].optics, "element_type", "") == 'WAVEFRONT_SENSOR'), "")
    else:
        return {"error": "pass a 'sensor' (preferred) or a reflective 'element'"}
    img = np.flipud(ao.zonal_wavefront_image(fld["field"], intensity=fld.get("intensity")))
    h, wd = img.shape[0], img.shape[1]
    bi = bpy.data.images.get("zonal_wavefront") or bpy.data.images.new("zonal_wavefront", wd, h, alpha=True)
    if tuple(bi.size) != (wd, h):
        bpy.data.images.remove(bi)
        bi = bpy.data.images.new("zonal_wavefront", wd, h, alpha=True)
    bi.pixels.foreach_set(img.astype('float32').ravel())
    out = filepath or os.path.join(bpy.app.tempdir or "/tmp", "zonal_wavefront.png")
    bi.filepath_raw = out
    bi.file_format = 'PNG'
    bi.save()
    if sensor and scene.objects.get(sensor) is not None:
        cap = ("ZONAL %s -> %s  RMS=%.3f (beam-wtd) / %.3f uniform  %dpx  hits=%.0f%%"
               % (elem, sensor, fld["rms_gauss"], fld["rms_uniform"], fld["px"], 100.0 * fld["hit_frac"]))
        monitor.set_frame(sensor, ao.zonal_wavefront_image(fld["field"], intensity=fld.get("intensity")), cap)
        scene.optics.monitor_show = True
    tracer._tag_redraw()
    return {"element": elem, "sensor": sensor or None, "rms_gauss": round(fld["rms_gauss"], 4),
            "rms_uniform": round(fld["rms_uniform"], 4), "footprint_mm": round(fld["footprint_mm"], 2),
            "hit_frac": round(fld["hit_frac"], 3), "nyquist_lp_mm": round(fld["nyquist_lp_mm"], 3),
            "rho_max": round(fld.get("rho_max", 1.0), 3), "captured_frac": round(fld.get("captured_frac", 1.0), 3),
            "w_sensor_mm": round(fld.get("w_sensor_mm", 0.0), 3), "aperture_applied": fld.get("aperture_applied", True),
            "px": fld["px"], "png": out}


def sensor_capture(sensor):
    """What a wavefront SENSOR actually CAPTURES of the beam reaching it (the sensor does NOT swallow the whole
    beam -- a beam wider than the sensor is truncated at its aperture). Inspection helper: returns the beam
    radius at the sensor, the sensor's clear aperture, the captured POWER fraction (1-exp(-2a^2/w^2), the
    Gaussian beyond the aperture is lost -- oracle-verified clip), the figure-footprint fraction the sensor
    captures (rho_max = aperture/w_sensor, captured_frac = rho_max^2), and the captured zonal figure's RMS /
    hit_frac. A COLLIMATED beam that fits reads the whole figure; a DIVERGING beam that overfills the sensor
    reads only its centre -- the difference is produced by the simulation (q-propagation + this aperture stop).
    {sensor, element, w_sensor_mm, aperture_mm, power_captured, rho_max, captured_frac, rms_gauss, hit_frac, footprint_mm}."""
    import math
    from . import ao
    scene = _scene()
    segs = _trace(scene)
    tracer.cached_segments = segs
    wfs = scene.objects.get(sensor)
    if wfs is None:
        return {"error": "sensor not found: %s" % sensor}
    w_sensor = next((s.get("w_mm", 0.0) for s in segs if s.get("to") == sensor), 0.0) or 0.0
    ap = (getattr(wfs.optics, 'clear_aperture', 0.0) or 0.0) if getattr(wfs, 'optics', None) else 0.0
    power_cap = (1.0 - math.exp(-2.0 * ap * ap / (w_sensor * w_sensor))) if (w_sensor > 1e-6 and ap > 0.0) else 1.0
    res = {"sensor": sensor, "w_sensor_mm": round(w_sensor, 3), "aperture_mm": round(ap, 3),
           "power_captured": round(power_cap, 4)}
    fld = ao.zonal_wavefront_at_sensor(scene, sensor, segs, px=200)
    if fld is not None:
        res.update({"element": fld.get("element"), "rho_max": round(fld.get("rho_max", 1.0), 3),
                    "captured_frac": round(fld.get("captured_frac", 1.0), 3),
                    "aperture_applied": fld.get("aperture_applied", False),
                    "rms_gauss": round(fld["rms_gauss"], 3), "hit_frac": round(fld["hit_frac"], 3),
                    "footprint_mm": round(fld["footprint_mm"], 2)})
        if not fld.get("aperture_applied", False):
            res["note"] = "beam width at sensor unknown -> aperture clip NOT applied (whole figure returned)"
    else:
        res["note"] = "no reflective figure feeds this sensor"
    return res


def ao_command(dm, coeffs):
    """Set a deformable mirror's command (Zernike coeffs, in waves). {ok, dm, command}."""
    obj = _scene().objects.get(dm)
    if not obj:
        return {"error": "object not found: %s" % dm}
    try:
        coeffs = [float(c) for c in coeffs]    # reject non-numeric / non-sequence cleanly
    except (TypeError, ValueError) as e:
        return {"error": "coeffs must be a numeric sequence: %s" % e}
    cmd = list(obj.optics.dm_command)
    for i in range(min(len(cmd), len(coeffs))):
        cmd[i] = coeffs[i]
    obj.optics.dm_command = cmd
    return {"ok": True, "dm": dm, "command": cmd}


def ao_close_loop(sensor, dm, gain=0.5, iters=15):
    """Close the modal adaptive-optics loop (sensor -> deformable-mirror integrator). Returns
    the RMS history in waves (open-loop first, corrected last)."""
    from . import ao
    hist = ao.close_loop(_scene(), sensor, dm, gain, iters)
    if not hist:
        return {"error": "need a wavefront sensor + deformable mirror with a beam between them"}
    return {"ok": True, "rms_history": [round(x, 4) for x in hist],
            "rms_initial": round(hist[0], 4), "rms_final": round(hist[-1], 4)}


def ao_close_loop_recon(sensor, dm, gain=0.8, leak=0.99, method='TSVD', iters=30):
    """B5: close the AO loop with the full reconstructor control structure -- an interaction
    matrix B (poke each DM mode, record the WFS response), a reconstructor R=B+ (``method``:
    'TSVD' truncated-SVD pseudoinverse, or 'DAMPED_TRANSPOSE' noise-tolerant c*B^T), and the
    leaky integrator x_{k+1}=leak*x_k - gain*R*w_k. Returns the convergence report (rms_before/
    after, reduction, history, singular spectrum). On-demand; the trace stays byte-identical."""
    from . import ao
    return ao.close_loop_recon(_scene(), sensor, dm, gain=gain, leak=leak,
                               method=method, iters=iters)


def ao_kolmogorov(aberrator, r0_mm=None, D_mm=None, seed=0):
    """B5: drive an ABERRATOR element's injected wavefront from a PHYSICAL Fried parameter r0
    (the Kolmogorov/Noll turbulence statistics, sigma^2=1.0299*(D/r0)^(5/3) rad^2). Writes the
    deterministic Zernike vector onto ``aberrator``.aberr_spec; smaller r0 = stronger turbulence.
    r0_mm / D_mm default to the scene AO props (ao_r0 / ao_aperture). {ok, r0_mm, D_mm, rms, modes}."""
    from . import ao, physics
    obj = _scene().objects.get(aberrator)
    if not obj:
        return {"error": "object not found: %s" % aberrator}
    sc = _scene()
    r0 = float(r0_mm) if r0_mm is not None else sc.optics.ao_r0
    D = float(D_mm) if D_mm is not None else sc.optics.ao_aperture
    modes = ao.kolmogorov_aberration(r0, D, seed=seed)
    obj.optics.aberr_spec = modes
    return {"ok": True, "aberrator": aberrator, "r0_mm": round(r0, 3), "D_mm": round(D, 3),
            "rms": round(physics.wavefront_rms(modes), 4),
            "modes": [round(m, 4) for m in modes]}


def export_svg(filepath):
    """Export a top-view 2-D vector (SVG) schematic of the optical layout + beam path to filepath
    (a publication figure: element glyphs, port ticks, wavelength-coloured beams). {ok, path, ...}."""
    from . import svg_export
    try:
        return svg_export.export_svg(filepath)
    except (OSError, RuntimeError) as e:        # match the operator's clean error shape
        return {"error": "svg export failed: %s" % e}


_ELEMENT_ROLE = {
    'SOURCE': "emits a Gaussian beam (waist, wavelength, M^2, polarization)",
    'LENS': "focuses / collimates (ABCD thin lens; f scaled chromatically by 1/(n-1))",
    'MIRROR': "reflects (f=R/2 if curved); reflectivity sets throughput",
    'DEFORMABLE_MIRROR': "reflects + applies a commanded Zernike correction",
    'ABERRATOR': "adds a fixed Zernike wavefront error (turbulence)",
    'BEAMSPLITTER': "splits into reflected + transmitted (PBS = by polarization)",
    'WAVEPLATE': "retards one axis (HWP rotates, QWP circularizes)",
    'POLARIZER': "transmits one linear polarization (Malus), blocks the orthogonal",
    'DETECTOR': "absorbs + reports power (terminal)",
    'WAVEFRONT_SENSOR': "reads the incoming wavefront's Zernike modes (terminal)",
    'APERTURE': "clips the beam to a clear aperture (iris / pinhole / slit)",
    'PRISM': "disperses + deviates by refraction (Sellmeier glass)",
    'PRISM_MIRROR': "deviates by TIR (penta / Dove / right-angle)",
    'GRATING': "diffracts into orders (0th-order layout)",
    'CRYSTAL': "nonlinear frequency conversion (SHG / SPDC / OPO / ...)",
    'WINDOW': "transmits (optional AR coating / ghost reflection)",
    'PASSTHROUGH': "transmits through a refractive plate",
    'ISOLATOR': "passes forward, blocks the back-reflection",
    'CIRCULATOR': "routes ports cyclically (non-reciprocal)",
    'BEAM_DUMP': "absorbs the beam (terminal trap)",
}

_PARAMS_BY_TYPE = {
    'SOURCE': ["wavelength", "waist_um", "m2", "linewidth_nm"],
    'LENS': ["focal_length", "lens_type", "clear_aperture", "design_wl"],
    'MIRROR': ["reflectivity", "mirror_curve", "radius_curv", "clear_aperture"],
    'DEFORMABLE_MIRROR': ["reflectivity", "clear_aperture"],
    'BEAMSPLITTER': ["split_ratio", "is_pbs", "bs_form"],
    'WAVEPLATE': ["retardance_deg", "fast_axis_deg"],
    'POLARIZER': ["pol_axis_deg", "polarizer_type"],
    'APERTURE': ["clear_aperture"],
    'PRISM': ["refractive_index", "prism_design_wl", "split_angle_deg"],
    'CRYSTAL': ["nl_process", "nl_efficiency", "poling_period_um", "nl_walkoff_mm"],
    'DETECTOR': ["clear_aperture", "analyzer"],
    'WAVEFRONT_SENSOR': ["clear_aperture"],
    'CIRCULATOR': ["isolation_db", "element_transmittance"],
    'ISOLATOR': ["isolation_db"],
    'PASSTHROUGH': ["refractive_index", "clear_aperture"],
    'WINDOW': ["ar_reflectance", "clear_aperture"],
}


def inspect_beam(element=""):
    """The full OPTICAL STATE of the beam where it reaches ``element`` (or the most-lit element if
    blank) -- the AI's numeric 'eyes' on the beam, so you READ the physics instead of eyeballing a
    render: power, wavelength, Gaussian radius w and wavefront curvature R(z) (collimated / diverging /
    converging), beam quality M^2, far-field divergence + reconstructed waist, polarization (Stokes ->
    kind / azimuth / ellipticity / DOP, all verified kernels), coherence length, and how many beams
    arrive (multi-beam awareness). READ-ONLY -- the trace is byte-identical. {element, power, w_mm,
    R_mm, curvature, m2, divergence_mrad, waist_w0_mm, dist_to_waist_mm, polarization, n_beams, ...}."""
    from . import physics
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    segs = tracer.cached_segments
    target = element
    if not target:
        best0 = max((s for s in segs if s.get("to")), key=lambda s: s.get("power", 0.0), default=None)
        target = best0.get("to") if best0 else ""
    arriving = [s for s in segs if s.get("to") == target]
    if not arriving:
        return {"error": "no beam reaches '%s'" % (target or "any element")}
    total_p = sum(s.get("power", 0.0) or 0.0 for s in arriving)
    best = max(arriving, key=lambda s: s.get("power", 0.0))
    wl = best.get("wavelength", 632.8) or 632.8
    m2 = best.get("m2", 1.0) or 1.0
    out = {
        "element": target,
        "n_beams": len(arriving),
        "dominant_frac": round(((best.get("power", 0.0) or 0.0) / total_p), 3) if total_p > 0 else 1.0,
        "power": round(best.get("power", 0.0) or 0.0, 5),
        "wavelength_nm": round(wl, 3),
        "w_mm": round(best.get("w_mm", 0.0) or 0.0, 5),
        "m2": round(m2, 3),
    }
    qd = best.get("qd")
    if qd:
        q = complex(qd[0], qd[1])
        R = physics.beam_roc(q)
        out["R_mm"] = round(R, 1) if math.isfinite(R) else None
        out["curvature"] = ("collimated" if not math.isfinite(R) else ("diverging" if R > 0 else "converging"))
        zR = q.imag
        if zR > 1e-9:
            w0 = math.sqrt(m2) * math.sqrt(zR * (wl * 1e-6) / math.pi)   # physical waist (M^2-broadened)
            out["waist_w0_mm"] = round(w0, 5)
            out["dist_to_waist_mm"] = round(q.real, 2)                   # >0: past the waist (diverging)
            out["divergence_mrad"] = round(1000.0 * physics.gaussian_divergence(w0, wl, m2), 5)
    coh = best.get("coh", float('inf'))
    out["coherence_length_mm"] = round(coh, 4) if math.isfinite(coh) and coh < 1.0e12 else None  # None = monochromatic
    j = best.get("jones")                       # stored as [Ex.re, Ex.im, Ey.re, Ey.im] (JSON has no complex)
    if j and len(j) >= 4:
        out["polarization"] = physics.polarization_state((complex(j[0], j[1]), complex(j[2], j[3])))
    return out


def inspect_element(name):
    """What an element DOES to the beam + what it is DOING right now -- the AI's numeric 'eyes' on an
    optic. Returns its optical role, the type-relevant params (focal_length, retardance, split_ratio,
    reflectivity, coating, nl_process, ...), and the LIVE trace: incoming power and the OUTGOING children
    by kind (TRANSMIT / REFLECT / SPLIT_R / SHG / ...) with power + wavelength, plus throughput -- so you
    SEE the actual effect (split 50/50, reflected 98%, converted 532 nm at X%, clipped to Y%). READ-ONLY
    -- the trace is byte-identical. {element, type, role, params, incoming_power, outgoing_power,
    throughput, outputs:[...]}."""
    obj = bpy.data.objects.get(name)
    if obj is None or not getattr(obj, "optics", None) or not obj.optics.is_optical:
        return {"error": "no optical element named '%s'" % name}
    op = obj.optics
    et = op.element_type
    params = {}
    for attr in _PARAMS_BY_TYPE.get(et, ["clear_aperture"]):
        v = getattr(op, attr, None)
        if v is None or v == "" or (isinstance(v, float) and abs(v) < 1e-12 and attr not in ("split_ratio",)):
            continue
        params[attr] = round(v, 4) if isinstance(v, float) else v
    coating = getattr(op, "coating", "NONE")
    if coating and coating != "NONE":                          # surface coating (A11): R / T / A budget
        params["coating"] = coating
        params["coating_reflectance"] = round(getattr(op, "coating_reflectance", 0.0), 4)
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    segs = tracer.cached_segments
    incoming = [s for s in segs if s.get("to") == name]
    outgoing = [s for s in segs if s.get("from") == name]
    in_p = sum(s.get("power", 0.0) or 0.0 for s in incoming)
    outputs = [{"kind": s.get("kind"), "to": s.get("to"),
                "power": round(s.get("power", 0.0) or 0.0, 5),
                "wavelength_nm": round(s.get("wavelength", 632.8) or 632.8, 1)}
               for s in sorted(outgoing, key=lambda s: s.get("power", 0.0), reverse=True)]
    out_p = sum(c["power"] for c in outputs)
    res = {
        "element": name, "type": et,
        "role": _ELEMENT_ROLE.get(et, "(optical element)"),
        "params": params,
        "incoming_power": round(in_p, 5),
        "outgoing_power": round(out_p, 5),
        "throughput": round(out_p / in_p, 4) if in_p > 1e-12 else None,
        "outputs": outputs,
    }
    if et == 'DETECTOR' and getattr(op, 'readout_topology', 'POINT') == 'POL_CAMERA' and incoming:
        from . import physics
        best = max(incoming, key=lambda s: s.get("power", 0.0))
        j = best.get("jones")                      # single-shot DoFP linear-Stokes read of the brightest beam
        if j and len(j) >= 4:
            dofp = physics.stokes_dofp((complex(j[0], j[1]), complex(j[2], j[3])))
            res["pol_camera"] = {k: round(v, 5) for k, v in dofp.items()}
            res["role"] = "polarization camera (DoFP): single-shot linear Stokes S0/S1/S2 + DoLP/AoLP"
    return res


def beam_profile(detector="", samples=24):
    """Gaussian spot radius w(z) along the beam path source -> `detector` (or the active/most-lit
    one): waist {z_mm, w_mm}, element positions + clear apertures, sampled z/w arrays, and a plot
    PNG + CSV in the temp dir. The core laser-bench design readout (where is the waist, does the
    mode fit the apertures, mode-matching into a cavity)."""
    from . import scan
    data = scan.beam_profile_plot(_scene(), detector, samples)
    if data is None:
        return {"error": "no Gaussian beam reaches a detector"}
    data["ok"] = True
    return data
