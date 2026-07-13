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
import os
import tempfile

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
        "capabilities", "get_state", "diagnose", "propose_corrections", "detect_phenomena", "produce_phenomenon",
        "inspect_beam", "inspect_element", "inspect_all", "beam_profile", "ao_measure", "get_wavefront", "sensor_capture",
        "check_mechanics", "coupling_efficiency", "material_tables"],
    "build / scene": [
        "build_example", "build_bench", "add_component", "tag_element", "swap_part", "set_param", "set_mount",
        "import_glass", "fdtd_derive_property"],
    "design (pure math, no scene change)": [
        "design_telescope", "design_4f", "mode_match", "optics_calc", "wave_psf", "aberrated_psf",
        "propagate_field", "propagate_chain", "gerchberg_saxton", "fienup_phase_retrieval", "spatial_filter",
        "tem_mode", "newton_rings", "quantum_stats", "gpu_status", "propagate_pulse", "slit_diffraction",
        "talbot_effect", "speckle_pattern", "caustic_pattern"],
    "place / assemble (opto-mechanics)": [
        "place_relative", "make_cage", "make_tube", "make_rail", "place_on_grid", "place_on_rail",
        "set_grid", "dress_bench"],
    "trace / measure": ["trace_beam", "scan", "bake_beams", "clear_beams", "tolerance_scan", "monte_carlo_tissue"],
    "align (mutates DOFs -- on demand only)": ["align_all", "align_element", "auto_align", "tilt_null",
                                               "reset_mount"],
    "adaptive optics + surface figure": [
        "ao_command", "ao_close_loop", "ao_close_loop_recon", "ao_kolmogorov", "zonal_render", "pyramid_wfs",
        "turbulence_screen", "propagate_turbulent"],
    "render / export": ["render", "render_sequence", "export_svg", "export_report"],
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

# Machine-readable scope map: which simulation requests are (a) reproducible now / (b) via the opt-in field
# layer / (c) need an engine we deliberately lack. Mirrors docs/OPTICS_SCOPE.md (the /optics-scope skill's
# source of truth). Anti-overclaim: name the gap + the external tool, never fake a (c) with an (a)/(b) overlay.
_SCOPE = {
    "tiers": {
        "a": "reproducible NOW: single ray + Gaussian-q (ABCD) + analytic overlays (Snell/Fresnel/Sellmeier/"
             "gratings/Jones-Stokes/cavities); oracle-verified in tests/test_validation.py.",
        "b": "opt-in field layer (off-trace, on-demand): wave.py = ONE focal-plane Fraunhofer PSF "
             "|FFT(pupil*exp(2j*pi*W))|^2 (Airy/Strehl/MTF/encircled-energy); field.py = angular-spectrum "
             "propagation between planes (propagate_field: free-space dz, digital-hologram back-prop).",
        "c": "NOT shipped: full-wave Maxwell (FDTD/RCWA), split-step NLSE, Monte-Carlo transport, quantum "
             "statistics -- name the external tool, never fake with an (a)/(b) overlay.",
    },
    "request_to_tier": {
        "ray/align/beam-walk; Gaussian w(z)/M2/resonator; lens/prism/grating/Fresnel/Malus/dispersion": "a",
        "Airy/Strehl/MTF/encircled-energy PSF": "b: wave_psf",
        "single/double/N-slit Fraunhofer diffraction (sinc^2, Young fringes, grating orders)": "b: slit_diffraction (FFT vs analytic sinc^2 x cos^2, oracle-verified)",
        "Talbot self-imaging of a periodic grating (z_T = 2 d^2/lambda)": "b: talbot_effect (angular-spectrum; self-image at z_T, d/2-shifted at z_T/2)",
        "free-space field propagation / multi-plane Fresnel / digital-hologram reconstruction": "b: propagate_field (angular spectrum)",
        "fully-developed laser speckle from a diffuser (contrast=1, exponential PDF, lambda*z/D grain)": "b: speckle_pattern (random-phase diffuser + angular spectrum; contrast + 1/sqrt(N) averaging oracle-verified)",
        "geometric caustic / coffee-cup nephroid (ray-density envelope, cusp at the focus)": "b: caustic_pattern (catacaustic of a circle; nephroid envelope + cusp at R/2 oracle-verified; ray-density piles on it ~20x)",
        "full-wave FDTD/RCWA, metasurface/nanophotonics": "c: Meep / Lumerical / Tidy3D -- ORCHESTRATED via fdtd_derive_property (runs the engine if present, else a closed-form fallback: grating dir=grating_angle, stack=exact TMM, metaatom=low-conf EMT) cached as an effective property; live trace byte-identical. Still tier (c): a LIVE full-wave field is not shipped.",
        "split-step NLSE: soliton / dispersion / SPM (1D pulse)": "b: propagate_pulse (split-step Fourier; fundamental soliton is shape-invariant, oracle-verified)",
        "supercontinuum (higher-order dispersion + Raman + self-steepening)": "c: gnlse (the core NLSE is (b) propagate_pulse; the generalized-NLSE terms are not built)",
        "Monte-Carlo tissue / turbid-medium photon transport": "b: monte_carlo_tissue (MCML-style slab; R+T+A=1, Beer-Lambert ballistic, diffusion penetration depth; CPU here, GPU-friendly if scaled)",
        "atmospheric turbulence phase screen + structure function": "b: turbulence_screen (dense Kolmogorov/von-Karman screen, FT + subharmonics; D(r)=6.88(r/r0)^5/3; modal ao_kolmogorov is a 15-Zernike caricature, this is the dense field)",
        "multi-screen turbulence inter-plane propagation + long-exposure seeing PSF": "b: propagate_turbulent (multi-screen split-step, angular-spectrum between Kolmogorov screens; energy-conserving; seeing-broadened PSF ~ lambda/r0, finite-grid ~0.7x ideal)",
        "quantum statistics g2 / HOM / squeezing": "c: QuTiP",
    },
    "source_of_truth": "docs/OPTICS_SCOPE.md (vendored case index) + tests/test_validation.py (the oracle-verified "
                       "suite). Obsidian textbook-catalog numbers are book-cited, NOT oracle-verified.",
    "rule": "Never overclaim a (c): name the gap + the external tool. The /optics-scope skill routes this.",
}


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
        "scope_map": _SCOPE,
        "see_also": "mcp/AGENT_GUIDE.md (full guide), docs/CAPABILITIES.md (the complete tree), "
                    "docs/OPTICS_SCOPE.md + the /optics-scope skill (can-it-simulate-X routing).",
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
    dark_detector / orphan_source, optic_bypassed (a placed optic the beam never reaches --
    moved/mis-placed off the path), energy_violation (per-node + global budget), and
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


def produce_phenomenon(phenomenon=None, where=None, nx=1024, png=False, accept=False):
    """ADVISORY emergence -- PRODUCE a phenomenon detect_phenomena flagged (the interferogram, or the
    recorded + reconstructed off-axis hologram), off-trace + byte-identical. Two-stage like
    propose_corrections: accept=False (default) is a DRY-RUN returning {would_produce, what_it_would_compute,
    maybe_not_wanted_if} and produces NOTHING; the AI weighs the user's intent (refuse / partial / accept) and
    only then re-calls with accept=True to get the actual {produced:{...metrics, oracle...}, png}. ``png=True``
    writes a PNG of the emerged pattern. The owner principle: if a phenomenon's conditions are MET it can be
    produced -- but NOT silently; emergence is an intent-judged act. Never mutates the scene/trace."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    png_path = os.path.join(tempfile.gettempdir(), "optics_phenomenon.png") if png else None
    return _diagnostics.produce_phenomenon(scene, phenomenon=phenomenon, where=where, nx=int(nx),
                                           png_path=png_path, accept=bool(accept))


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
    "newton_ring_radius": (physics.newton_ring_radius, ("m", "wl_nm", "R_mm"), "Newton dark-ring radius sqrt(m*lambda*R), mm"),
    "n_e_theta": (physics.n_e_theta, ("n_o", "n_e", "theta_deg"), "uniaxial extraordinary index n_e(theta) from the index ellipsoid"),
    "uniaxial_walkoff_angle": (physics.uniaxial_walkoff_angle, ("n_o", "n_e", "theta_deg"), "birefringent double-refraction walk-off angle, deg"),
    "waveplate_thickness": (physics.waveplate_thickness, ("order", "wl_nm", "dn"), "zero-order waveplate thickness d=order*lambda/dn, mm"),
    "shg_phase_match_angle": (physics.shg_phase_match_angle, ("crystal", "wl_fund_nm"), "Type-I SHG phase-match angle theta_pm, deg (e.g. BBO 1064->532 ~22.8)"),
    "shg_phase_match_angle_type2": (physics.shg_phase_match_angle_type2, ("crystal", "wl_fund_nm"), "Type-II SHG phase-match angle, deg (o+e->e; e.g. BBO 1064->532 ~32.9)"),
    "biaxial_shg_phase_match_phi": (physics.biaxial_shg_phase_match_phi, ("crystal", "wl_fund_nm", "pm_type"), "BIAXIAL XY-plane (theta=90) SHG phase-match azimuth phi, deg (KTP Type-II ~23.5; LBO Type-I ~11.6)"),
    "biaxial_shg_walkoff_mrad": (physics.biaxial_shg_walkoff_mrad, ("crystal", "wl_fund_nm", "pm_type"), "BIAXIAL XY-plane SHG spatial walk-off, mrad (KTP Type-II ~4; LBO Type-I ~7)"),
    "ir_material_index": (physics.ir_material_index, ("material", "wl_nm"), "refractive index of an IR/LWIR material (AS2S3, AGCL, ZNS) at wl_nm; e.g. AS2S3 @10um = 2.38"),
    "ar_coating_reflectance": (physics.ar_coating_reflectance, ("wl_nm", "design_wl_nm", "n1", "ns"), "single-layer quarter-wave AR reflectance R(lambda) -- the V-shaped ghost curve (min at design wl, e.g. MgF2/crown 1.26% at 550nm)"),
    "lbo_ncpm_temperature_estimate": (physics.lbo_ncpm_temperature_estimate, ("wl_fund_nm",), "LBO Type-I NCPM temperature (X-axis, zero walk-off) from CONSTANT datasheet dn/dT, deg C. CAVEAT: model ~256C; the REAL value is 148C (constant dn/dT under-predict the slope; lambda-resolved Tang/Kato paywalled)"),
    "shg_walkoff_mm": (physics.shg_walkoff_mm, ("crystal", "wl_fund_nm", "L_mm"), "Sellmeier-derived SHG spatial walk-off offset L*tan(rho), mm (BBO 1064->532, 10mm ~0.50)"),
    "chi2_shg_efficiency": (physics.chi2_solve, ("deff_pm_V", "L_mm", "P_W", "dk_per_mm"), "SHG efficiency from the Manley-Rowe coupled-wave ODE (depletion+mismatch); tanh^2(sqrt(eta_lin)) at phase match"),
    "chi2_shg_type2_efficiency": (physics.chi2_shg_type2_efficiency, ("eta_lin", "frac_o"), "Type-II SHG (o+e->e) efficiency from the 3-wave coupled equations; balanced=Type-I at half eta_lin, unbalanced caps at 2*min(frac_o,1-frac_o) (Manley-Rowe)"),
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
    "metal_reflectance": (physics.metal_reflectance, ("metal", "wl_nm", "aoi_deg"), "mirror-metal power reflectance R(lambda); metal AL/AG/AU"),
    "thermal_lens_focal_length": (physics.thermal_lens_focal_length, ("p_abs_W", "dn_dT", "kappa_W_mK", "w_mm"), "thermal-lens focal length, mm (Tier-1 estimate)"),
    "photoelastic_retardance_nm": (physics.photoelastic_retardance_nm, ("stress_Pa", "stress_optic_C", "path_mm"), "stress birefringence retardance, nm (estimate)"),
    "cantilever_sag_nm": (physics.cantilever_sag_nm, ("mass_kg", "length_m", "youngs_Pa", "area_moment_m4"), "gravity sag of a tip mass, nm (estimate)"),
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


def import_glass(name, coefficients, formula=2, ref_wl_nm=587.56, ref_n=None):
    """Add a glass to the user catalog from refractiveindex.info Sellmeier coefficients (an agent fetches
    the RII `coefficients` list + `type` then calls this). formula 1 -> the C entries are resonance
    wavelengths (squared here to our Cj=lambda_j^2); formula 2 -> already squared; c0 must be 0; pass
    ref_n to validate the conversion against a known index. Persists so sellmeier_n and the glass enums
    then see the new name. Returns {ok, name, coeffs, n_at_ref, persisted} or {ok:False, error}."""
    return physics.import_glass(name, coefficients, formula=formula, ref_wl_nm=ref_wl_nm, ref_n=ref_n)


def material_tables():
    """Machine-readable MATERIAL/REFERENCE tables for agents (also served as the MCP resource
    optics://tables/materials) -- so an agent stops re-deriving 'which glasses exist' or 'what does
    Noll j=7 mean' from prose. Everything is computed LIVE from physics.py's sourced data (the same
    oracle-checked Sellmeier code the tracer uses; provenance in docs/DATASOURCES.md):
      glasses: {name: {n_d (at 587.56 nm), dndt_per_C?, range_um?}}
      nl_crystals: {name: {deff_pm_per_V, dk_dT_per_mm_K, pm_temp_C, has_sellmeier_oe}}
      biaxial / ir_materials / metals_nk / detector_qe: name lists (+ QE window for detectors)
      zernike_noll: {j: name} for the modal wavefront channel (j=1..15).
    READ-ONLY; no scene access."""
    glasses = {}
    for g in physics.glass_names():
        entry = {"n_d": round(physics.sellmeier_n(587.56, g), 6)}
        if g in physics.DNDT:
            entry["dndt_per_C"] = physics.DNDT[g]
        if g in physics.GLASS_RANGE_UM:
            entry["range_um"] = list(physics.GLASS_RANGE_UM[g])
        glasses[g] = entry
    nl = {}
    for name, (deff, dkdt, tpm) in physics.NL_CRYSTALS.items():
        nl[name] = {"deff_pm_per_V": deff, "dk_dT_per_mm_K": dkdt, "pm_temp_C": tpm,
                    "has_sellmeier_oe": name in physics.NL_CRYSTAL_SELLMEIER}
    return {
        "ok": True,
        "glasses": glasses,
        "nl_crystals": nl,
        "biaxial_crystals": sorted(physics.BIAXIAL_SELLMEIER),
        "ir_materials": sorted(physics.IR_MATERIALS),
        "metals_nk": sorted(physics.METAL_NK),
        "detector_qe": {k: ({"window_nm": [v[0], v[3]], "peak_qe": v[4]} if len(v) >= 5 else {})
                        for k, v in physics.DETECTOR_QE.items()},
        "zernike_noll": dict(physics.ZERNIKE_NAMES),
        "provenance": "sourced constants; see docs/DATASOURCES.md (refractiveindex.info CC0 + cited datasheets)",
    }


def _wave_args_error(wavelength_nm=None, n_grid=None, n_grid_max=4096, **positives):
    """Shared input validation for the off-trace field/wave producers. These are MCP-reachable, so an
    agent can pass garbage: wavelength_nm=0 used to raise ZeroDivisionError, and an unbounded n_grid
    allocates O(n^2) FFT arrays and OOM-kills Blender (verified: n_grid=1e6 -> exit 137). Returns an
    {error} dict to hand straight back, or None when the args are fine. Extra keyword args are checked
    strictly-positive when not None (pass e.g. w0_mm=w0_mm, f_number=f_number)."""
    # every comparison/conversion below can itself raise on non-numeric garbage ("abc", [1,2],
    # NaN-strings...) -- that must come back as an {error} dict too, never as an exception
    try:
        if wavelength_nm is not None and not (wavelength_nm > 0):
            return {"error": "wavelength_nm must be positive (nm)"}
        if n_grid is not None and not (8 <= int(n_grid) <= n_grid_max):
            return {"error": "n_grid must be in 8..%d (large FFT grids exhaust memory)" % n_grid_max}
        for name, val in positives.items():
            if val is not None and not (val > 0):
                return {"error": "%s must be positive" % name}
    except (TypeError, ValueError) as e:
        return {"error": "non-numeric argument: %s" % e}
    return None


def wave_psf(wavelength_nm, f_number, aperture_diam_mm, defocus_waves=0.0, n_grid=512, png=False):
    """Fourier-optics diffraction PSF of a circular aperture (PSF = |FFT(pupil*exp(i*2*pi*W))|^2) -- the
    OPT-IN wave layer, separate from the live ray trace (which is geometric + Gaussian and cannot diffract).
    Returns {strehl, airy_radius_um, first_zero_um, fwhm_um, mtf_cutoff_cyc_per_mm, encircled_energy_airy,
    ...}. `defocus_waves` adds RMS Noll-Z4 defocus (a quick aberration knob; Strehl then matches Marechal
    exp(-(2*pi*rms)^2)). png=True saves a log-scaled PSF image and returns its path."""
    bad = _wave_args_error(wavelength_nm, n_grid, f_number=f_number, aperture_diam_mm=aperture_diam_mm)
    if bad:
        return bad
    from . import wave
    diam_px = max(32, n_grid // 4)
    W = (defocus_waves * wave.zernike_defocus(n_grid, diam_px)) if defocus_waves else None
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_psf.png")
    return wave.psf_metrics(wavelength_nm, f_number, aperture_diam_mm, W=W,
                            n_grid=n_grid, diam_px=diam_px, png_path=png_path)


_ZMODE = {"defocus": 4, "astigmatism": 5, "coma": 7, "trefoil": 9, "spherical": 11}


def aberrated_psf(mode="spherical", amplitude_waves=0.1, zernike_waves=None,
                  wavelength_nm=550.0, f_number=8.0, aperture_diam_mm=10.0, n_grid=512, png=False):
    """Diffraction PSF aberrated by a ZERNIKE wavefront -- the general (any-mode) form of wave_psf's defocus
    knob. Either a single named ``mode`` in {defocus, astigmatism, coma, trefoil, spherical} at
    ``amplitude_waves`` RMS, OR a full Noll-indexed ``zernike_waves`` list (j=1..15, in waves; index 0 = Z1
    piston). Returns {strehl, rms_wavefront_waves, airy_radius_um, first_zero_um, fwhm_um, ...}; for a SMALL
    aberration the Strehl follows Marechal exp(-(2*pi*rms)^2). png=True saves the PSF. Off-trace; byte-identical.
    E.g. aberrated_psf('astigmatism', 0.05) -> strehl ~ 0.906."""
    bad = _wave_args_error(wavelength_nm, n_grid, f_number=f_number, aperture_diam_mm=aperture_diam_mm)
    if bad:
        return bad
    from . import wave
    if zernike_waves is not None:
        coeffs = [float(c) for c in zernike_waves]
    else:
        j = _ZMODE.get((mode or "").lower())
        if j is None:
            return {"error": "mode must be one of %s, or pass zernike_waves" % ", ".join(sorted(_ZMODE))}
        coeffs = [0.0] * 15
        coeffs[j - 1] = float(amplitude_waves)
    diam_px = max(64, n_grid // 2)
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_aberrated_psf.png")
    out = wave.aberrated_psf(coeffs, wavelength_nm, f_number, aperture_diam_mm,
                             n_grid=int(n_grid), diam_px=int(diam_px), png_path=png_path)
    out["mode"] = mode if zernike_waves is None else "custom"
    return out


def export_report(filepath=None, title="Optical Bench Report", with_render=False):
    """Bundle the WHOLE-BENCH analysis into ONE self-contained HTML spec sheet -- the 'show me everything'
    command. Binds the existing read tools: the topology/summary (get_state), the per-element inspection
    dashboard (inspect_all), the diagnostics (diagnose), and the beam profile (beam_profile, its plot embedded),
    plus an optional Cycles/EEVEE render (with_render=True). Pure HTML, no external deps, images inlined as base64
    so the file is portable. Returns {ok, path, n_elements, n_issues}. READ-ONLY; the live trace is byte-identical."""
    import os
    import html as _html
    import base64
    import tempfile

    def _img_tag(path, cap=""):
        try:
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            return ('<figure><img src="data:image/png;base64,%s"/>'
                    '<figcaption>%s</figcaption></figure>' % (b64, _html.escape(cap)))
        except Exception:
            return ""

    state = get_state() or {}
    dash = inspect_all() or {}
    diag = diagnose() or {}
    prof = beam_profile() if any(True for _o in _scene().objects
                                 if getattr(_o, "optics", None) and getattr(_o.optics, "is_optical", False)) else {}
    rows = dash.get("elements", [])
    issues = diag.get("issues") or diag.get("problems") or []
    parts = ["<!doctype html><meta charset=utf-8><title>%s</title>" % _html.escape(title),
             "<style>body{background:#0d0d10;color:#e8e8ea;font:14px/1.5 system-ui,sans-serif;margin:0;padding:28px}"
             "h1{color:#f4f4f6}h2{color:#4a8db0;border-bottom:1px solid #33343a;padding-bottom:4px;margin-top:28px}"
             "table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{border:1px solid #33343a;padding:5px 8px;text-align:left}"
             "th{background:#1a1b1f;color:#9ab}tr:nth-child(even){background:#141519}.bad{color:#e0653a}.ok{color:#5ab07a}"
             "figure{margin:14px 0}img{max-width:100%;border:1px solid #33343a;border-radius:4px}"
             "figcaption{color:#8a8a92;font-size:11px}.muted{color:#8a8a92}</style>"]
    parts.append("<h1>%s</h1>" % _html.escape(title))
    parts.append('<p class=muted>Blender Optics Simulator &mdash; off-trace analysis report. '
                 '%d optical elements, %d diagnostic note(s).</p>' % (len(rows), len(issues)))

    parts.append("<h2>Per-element inspection</h2><table><tr><th>Element</th><th>Type</th><th>Role</th>"
                 "<th>In power</th><th>Throughput</th><th>w (mm)</th><th>Curvature</th><th>M&sup2;</th>"
                 "<th>Pol</th><th>Outputs</th></tr>")
    for r in rows:
        outs = r.get("outputs") or []
        okind = ", ".join("%s %.3g" % (o.get("kind", "?"), o.get("power", 0.0)) for o in outs) if outs else "&mdash;"
        parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                     "<td>%s</td><td>%s</td><td>%s</td></tr>" % tuple(_html.escape(str(x)) for x in (
                         r.get("name"), r.get("type"), r.get("role") or "", r.get("in_power"), r.get("throughput"),
                         r.get("w_mm"), r.get("curvature") or "", r.get("m2"), r.get("polarization") or "", okind)))
    parts.append("</table>")

    if issues:
        parts.append("<h2>Diagnostics</h2><table><tr><th>Severity</th><th>Issue</th><th>Where</th></tr>")
        for it in issues:
            sev = str(it.get("severity", it.get("state", "")))
            cls = "bad" if sev in ("BAD", "WARN", "high", "medium") else "ok"
            parts.append("<tr><td class=%s>%s</td><td>%s</td><td>%s</td></tr>" % (
                cls, _html.escape(sev), _html.escape(str(it.get("issue", it.get("problem", it.get("kind", ""))))),
                _html.escape(str(it.get("where", it.get("element", ""))))))
        parts.append("</table>")
    else:
        parts.append("<h2>Diagnostics</h2><p class=ok>No issues flagged.</p>")

    if isinstance(prof, dict) and prof.get("ok"):
        w = prof.get("waist", {})
        parts.append("<h2>Beam profile</h2><p>Waist w&#8320; = %s mm at z = %s mm.</p>" % (
            _html.escape(str(w.get("w_mm"))), _html.escape(str(w.get("z_mm")))))
        if prof.get("png"):
            parts.append(_img_tag(prof["png"], "Gaussian spot radius w(z) along the beam path"))

    if with_render:
        try:
            rp = os.path.join(tempfile.gettempdir(), "optics_report_render.png")
            render(filepath=rp)
            parts.append("<h2>Scene render</h2>" + _img_tag(rp, "Cycles/EEVEE view of the bench"))
        except Exception as exc:
            parts.append("<p class=muted>(render skipped: %s)</p>" % _html.escape(str(exc)))

    out = filepath or os.path.join(tempfile.gettempdir(), "optics_report.html")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": out, "n_elements": len(rows), "n_issues": len(issues)}


def gpu_status(enable=None):
    """Report (or set) the OPT-IN GPU backend for the off-trace FFT field engine. `enable`=None reports;
    'auto'/'cupy'/'mlx' turns it on (needs the library + hardware -- owner-run); 'off' reverts to NumPy.
    Returns {ok, active_backend, available:{cupy,mlx}, default_dtype, note}. The NumPy default is byte-identical
    to the CPU path; complex128 on GPU matches the oracle exactly, complex64 is the fast path (~1e-6 deviation
    -- the angular-spectrum H phase is kept in float64 regardless). This module is off-trace; the live ray trace
    is unaffected."""
    from . import gpu
    if enable is not None:
        if str(enable).lower() in ("off", "false", "0", "none"):
            gpu.disable()
        else:
            gpu.enable("auto" if str(enable).lower() in ("on", "true", "1", "auto") else str(enable))
    out = gpu.info()
    out["ok"] = True
    return out


def quantum_stats(observable="g2", state="coherent", n=1, indistinguishability=1.0, squeeze_db=10.0, heralded=True):
    """QUANTUM photon-statistics observables (off-trace; verified analytic core + a QuTiP scaffold for the full
    state). `observable`: 'g2' (g^(2)(0) of `state` in {coherent=1, thermal=2, single_photon=0, fock n=1-1/n}),
    'hom' (Hong-Ou-Mandel two-photon dip at `indistinguishability`), 'squeezing' (squeezed-quadrature variance
    at `squeeze_db`, sub-shot-noise), 'spdc' (the chi2 down-conversion source g2: heralded single photon -> 0,
    a single arm -> 2 thermal), 'full_state' (the QuTiP-backed many-mode state; closed-form fallback if qutip is
    absent). Off-trace; the live ray trace is byte-identical."""
    from . import quantum as _qm
    obs = (observable or "g2").lower()
    if obs == "g2":
        return {"ok": True, "observable": "g2", "state": state, "g2_zero": _qm.g2_zero(state, int(n))}
    if obs == "hom":
        return {"ok": True, "observable": "hom", **_qm.hom_dip(float(indistinguishability))}
    if obs == "squeezing":
        return {"ok": True, "observable": "squeezing", **_qm.squeezing_variance(float(squeeze_db))}
    if obs == "spdc":
        return {"ok": True, "observable": "spdc", **_qm.spdc_g2(bool(heralded))}
    if obs == "full_state":
        return _qm.quantum_state_observables("squeezed_vacuum", float(squeeze_db))
    return {"error": "observable must be one of: g2, hom, squeezing, spdc, full_state"}


def propagate_field(wavelength_nm, w0_mm=None, aperture_mm=None, dz_mm=0.0, n_grid=256, dx_mm=None, png=False):
    """Free-space ANGULAR-SPECTRUM propagation of a sampled scalar field over dz_mm -- the opt-in field layer,
    separate from the live geometric+Gaussian trace (which cannot diffract BETWEEN planes). Source: a Gaussian
    waist `w0_mm` OR a clear circular `aperture_mm`. Auto-sizes the grid pitch (dx_mm ~ 8x the source / n_grid)
    unless given. Returns the propagated beam metrics {w_2sigma_mm, peak, total_power, centroid_*, fresnel_number,
    dz_mm, w_analytic_mm}; png=True saves an intensity image. The propagator reproduces the Gaussian w(z) closed
    form (compare w_2sigma_mm vs w_analytic_mm) and is reversible (+dz then -dz). On-demand analysis -- the live
    trace is untouched + byte-identical. This is the primitive behind digital-hologram reconstruction and
    multi-plane Fresnel; full-wave (FDTD) and split-step (NLSE) stay out of scope (see capabilities()['scope_map'])."""
    bad = _wave_args_error(wavelength_nm, n_grid, w0_mm=w0_mm, aperture_mm=aperture_mm, dx_mm=dx_mm)
    if bad:
        return bad
    import math
    from . import field
    n_grid = int(n_grid)
    src = w0_mm or (0.5 * aperture_mm if aperture_mm else None)
    if not src:
        return {"error": "give a Gaussian w0_mm or a circular aperture_mm source"}
    lam_mm = wavelength_nm * 1.0e-6
    zR = math.pi * w0_mm * w0_mm / lam_mm if w0_mm else None
    if dx_mm is None:
        # size the grid to hold the PROPAGATED beam (not just the source), else it aliases at large dz
        if w0_mm:
            span = 8.0 * max(w0_mm, w0_mm * math.sqrt(1.0 + (dz_mm / zR) ** 2))
        else:
            span = 8.0 * (0.5 * aperture_mm + abs(dz_mm) * lam_mm / max(aperture_mm, 1.0e-6))
        dx_mm = span / n_grid
    if w0_mm:
        U0 = field.gaussian_field(n_grid, dx_mm, w0_mm)
    else:
        U0 = field.circular_aperture(n_grid, dx_mm, aperture_mm)
    U = field.angular_spectrum(U0, dx_mm, dz_mm, wavelength_nm)
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_field.png")
    out = field.field_metrics(U, dx_mm, wavelength_nm, png_path=png_path)
    out["dz_mm"] = dz_mm
    half = 0.5 * dx_mm * n_grid
    out["grid_halfwidth_mm"] = round(half, 3)
    out["sampling_ok"] = bool(out["w_2sigma_mm"] < 0.45 * half)   # beam fits w/ margin; else raise n_grid / dx_mm
    if w0_mm:
        out["w_analytic_mm"] = round(w0_mm * math.sqrt(1.0 + (dz_mm / zR) ** 2), 5)
    return out


def propagate_chain(steps, wavelength_nm=632.8, w0_mm=None, aperture_mm=None, n_grid=512, dx_mm=None, png=False):
    """March a complex field through a SEQUENCE of optical planes -- the POPPY-style multi-plane OpticalSystem
    that CHAINS the single-step angular-spectrum propagator (which `propagate_field` runs once). `steps` is a
    list of [kind, value]: ["prop", dz_mm] free-space propagation, ["aperture", D_mm] hard circular aperture,
    ["lens", f_mm] thin lens (phase exp(-i pi r^2/(lam f))). Source: a Gaussian (w0_mm) or a uniform field
    clipped by aperture_mm. e.g. an aperture->lens(f)->prop(f) chain focuses at z=f. Returns {ok, final
    (field_metrics of the last plane), z_total_mm, trace:[per-step z/w/peak/power]}. Off-trace / byte-identical.
    NEAR-field / moderate propagation only -- a tight focus or Fraunhofer far field is better via direct FFT
    (wave_psf / slit_diffraction): the anti-alias band-limit degrades far-field null spacing."""
    bad = _wave_args_error(wavelength_nm, n_grid, w0_mm=w0_mm, aperture_mm=aperture_mm, dx_mm=dx_mm)
    if bad:
        return bad
    if not steps:
        return {"error": "give a non-empty steps list, e.g. [['aperture',3.0],['lens',200.0],['prop',200.0]]"}
    if not (w0_mm or aperture_mm):
        return {"error": "give a Gaussian w0_mm or a circular aperture_mm source"}
    from . import field
    try:
        norm = [(str(s[0]), float(s[1])) for s in steps]
    except Exception:
        return {"error": "each step must be [kind, value]; kind in {prop, aperture, lens}"}
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_chain.png")
    try:
        return field.propagate_chain(norm, wavelength_nm=wavelength_nm, w0_mm=w0_mm, aperture_mm=aperture_mm,
                                     n_grid=int(n_grid), dx_mm=dx_mm, png_path=png_path)
    except ValueError as exc:
        return {"error": str(exc)}


def gerchberg_saxton(target="ring", n_grid=128, n_iter=60, seed=0, png=False):
    """Gerchberg-Saxton phase retrieval / CGH design -- the iterative Fourier-transform algorithm. Finds a
    source-plane PHASE whose far-field |FFT| matches a target pattern, iterating amplitude constraints in the
    source and far-field planes; the far-field error is MONOTONE NON-INCREASING (the GS guarantee). `target` in
    {ring, double, tophat, spot} (canonical beam-shaping / CGH patterns over a circular source). Returns {ok,
    target, correlation (achieved-vs-target, 0..1), final_error, initial_error, monotone, n_iter}. png=True
    saves the achieved far-field + the recovered phase mask. Off-trace; live trace byte-identical."""
    bad = _wave_args_error(None, n_grid, n_iter=n_iter)
    if bad:
        return bad
    if target not in ("ring", "double", "tophat", "spot"):
        return {"error": "target must be one of: ring, double, tophat, spot"}
    from . import field
    T, src = field.gs_named_target(target, int(n_grid))
    r = field.gerchberg_saxton(T, src, n_iter=int(n_iter), seed=int(seed))
    out = {"ok": True, "target": target, "correlation": r["correlation"], "final_error": r["final_error"],
           "initial_error": round(r["errors"][0], 6) if r["errors"] else None,
           "monotone": r["monotone"], "n_iter": r["n_iter"]}
    if png:
        try:
            import os
            import tempfile
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.4))
            fig.patch.set_facecolor("#0d0d10")
            ax[0].imshow(r["achieved_amplitude"] ** 2, cmap="inferno", origin="lower")
            ax[0].set_title("achieved far-field (target=%s)" % target, color="#f4f4f6", fontsize=10)
            ax[1].imshow(r["source_phase"], cmap="twilight", origin="lower")
            ax[1].set_title("recovered phase mask", color="#f4f4f6", fontsize=10)
            for a_ in ax:
                a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor("#0d0d10")
            png_path = os.path.join(tempfile.gettempdir(), "optics_gs.png")
            fig.tight_layout()
            fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
            plt.close(fig)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def fienup_phase_retrieval(obj="dots", n_grid=128, n_iter=300, beta=0.9, seed=0, png=False):
    """Fienup HIO phase retrieval -- recover a hidden REAL, non-negative object from its diffraction INTENSITY
    (|FFT|^2) ALONE plus a real-space SUPPORT mask: the genuine 'phase problem' of coherent diffractive imaging
    / crystallography. Where Gerchberg-Saxton knows the amplitude in BOTH planes (CGH design), here the object
    is UNKNOWN -- only its support is given. The Hybrid-Input-Output feedback (beta ~ 0.9) escapes the
    stagnation / twin-image traps that pure error-reduction falls into. `obj` in {dots, ell, tri} (canonical
    asymmetric objects in an off-centre support that breaks the conjugate twin). Returns {ok, obj, correlation
    (recovered-vs-truth, INVARIANT to the inherent translation + twin ambiguities, 0..1), final_error,
    initial_error, n_iter, support_frac}. png=True saves truth / recovered / Fourier-error curve. Off-trace;
    live trace byte-identical."""
    bad = _wave_args_error(None, n_grid, n_iter=n_iter, beta=beta)
    if bad:
        return bad
    if obj not in ("dots", "ell", "tri"):
        return {"error": "obj must be one of: dots, ell, tri"}
    from . import field
    out = field.fienup_design(obj, n_grid=int(n_grid), n_iter=int(n_iter), beta=float(beta), seed=int(seed))
    if png:
        try:
            import os
            import tempfile
            import numpy as _np
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            truth, support = field._fienup_object(obj, int(n_grid))
            measured = _np.abs(field._fft2c(truth)) ** 2
            r = field.fienup_phase_retrieval(measured, support, n_iter=int(n_iter), beta=float(beta), seed=int(seed))
            fig, ax = plt.subplots(1, 3, figsize=(10.6, 3.4))
            fig.patch.set_facecolor("#0d0d10")
            ax[0].imshow(truth, cmap="inferno", origin="lower")
            ax[0].set_title("hidden object (obj=%s)" % obj, color="#f4f4f6", fontsize=10)
            ax[1].imshow(r["recovered"], cmap="inferno", origin="lower")
            ax[1].set_title("HIO recovery (corr=%.3f)" % out["correlation"], color="#f4f4f6", fontsize=10)
            ax[2].semilogy(r["fourier_error"], color="#4a8db0")
            ax[2].set_title("Fourier-magnitude error", color="#f4f4f6", fontsize=10)
            ax[2].set_facecolor("#0d0d10")
            ax[2].tick_params(colors="#8a8a92")
            for a_ in ax[:2]:
                a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor("#0d0d10")
            png_path = os.path.join(tempfile.gettempdir(), "optics_fienup.png")
            fig.tight_layout()
            fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
            plt.close(fig)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def spatial_filter(obj="grating", kind="lowpass", cutoff_frac=0.15, n_grid=256, png=False):
    """4f FOURIER-PLANE spatial filtering (the Abbe-Porter experiment / coherent optical image processing).
    FFTs a canonical object, applies a Fourier-plane mask, and IFFTs back. obj in {grating, edge, phase};
    kind in {lowpass (smooths / removes fine detail), highpass (edge enhancement / removes the DC background),
    phase_contrast (Zernike: a pi/2 dot on the zero order makes a PURE-PHASE object visible in intensity)}.
    Returns {ok, obj, kind, input_intensity_std, output_intensity_std, output_mean_amp, contrast_ratio};
    png=True saves the input vs filtered image. Off-trace; live trace byte-identical."""
    bad = _wave_args_error(None, n_grid, cutoff_frac=cutoff_frac)
    if bad:
        return bad
    if obj not in ("grating", "edge", "phase"):
        return {"error": "obj must be one of: grating, edge, phase"}
    if kind not in ("lowpass", "highpass", "phase_contrast"):
        return {"error": "kind must be one of: lowpass, highpass, phase_contrast"}
    from . import field
    out = field.spatial_filter(obj=obj, kind=kind, cutoff_frac=float(cutoff_frac), n_grid=int(n_grid))
    if png:
        try:
            import os
            import tempfile
            import numpy as _np
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            U = field._filter_object(obj, int(n_grid))
            V = field.fourier_filter(U, kind, float(cutoff_frac))
            fig, ax = plt.subplots(1, 2, figsize=(7.0, 3.4))
            fig.patch.set_facecolor("#0d0d10")
            ax[0].imshow(_np.abs(U) ** 2, cmap="gray", origin="lower")
            ax[0].set_title("input intensity (%s)" % obj, color="#f4f4f6", fontsize=10)
            ax[1].imshow(_np.abs(V) ** 2, cmap="gray", origin="lower")
            ax[1].set_title("%s filtered" % kind, color="#f4f4f6", fontsize=10)
            for a_ in ax:
                a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor("#0d0d10")
            png_path = os.path.join(tempfile.gettempdir(), "optics_spatial_filter.png")
            fig.tight_layout()
            fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
            plt.close(fig)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def tem_mode(family="HG", i=1, j=0, w_mm=0.5, n_grid=256, png=False):
    """Laser cavity TRANSVERSE mode pattern -- the TEM_mn / donut shapes a resonator supports. family in {HG
    (Hermite-Gaussian TEM_ij, rectangular: (i+1)(j+1) bright lobes), LG (Laguerre-Gaussian LG_{p=i, l=j},
    cylindrical: a DONUT with an on-axis null + an exp(i l phi) phase vortex carrying orbital angular momentum
    l*hbar when l!=0)}. Returns {ok, family, indices, n_lobes, gouy_order (the mode's extra Gouy phase factor:
    i+j+1 for HG, 2p+|l|+1 for LG), on_axis_intensity_frac, x2_over_w2 (= (2i+1)/4 for HG_i0), oam_winding_turns
    (LG)}. png=True saves the intensity (+ the phase vortex for LG). Off-trace; live trace byte-identical."""
    bad = _wave_args_error(None, n_grid, w_mm=w_mm)
    if bad:
        return bad
    if (family or "HG").upper() not in ("HG", "LG"):
        return {"error": "family must be HG (Hermite-Gaussian) or LG (Laguerre-Gaussian)"}
    from . import field
    out = field.tem_mode_metrics(family, int(i), int(j), float(w_mm), n_grid=int(n_grid))
    if png:
        try:
            import os
            import tempfile
            import numpy as _np
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            U = field.tem_mode(family, int(i), int(j), float(w_mm), n_grid=int(n_grid))
            fam = (family or "HG").upper()
            ncol = 2 if fam == "LG" else 1
            fig, ax = plt.subplots(1, ncol, figsize=(3.6 * ncol, 3.5), squeeze=False)
            fig.patch.set_facecolor("#0d0d10")
            ax[0][0].imshow(_np.abs(U) ** 2, cmap="inferno", origin="lower")
            ax[0][0].set_title("%s_%d%d intensity (%d lobes)" % (fam, i, j, out["n_lobes"]), color="#f4f4f6", fontsize=10)
            if fam == "LG":
                ax[0][1].imshow(_np.angle(U), cmap="twilight", origin="lower")
                ax[0][1].set_title("phase vortex (l=%d, %g turns)" % (j, out.get("oam_winding_turns", 0)),
                                   color="#f4f4f6", fontsize=10)
            for a_ in ax[0]:
                a_.set_xticks([]); a_.set_yticks([]); a_.set_facecolor("#0d0d10")
            png_path = os.path.join(tempfile.gettempdir(), "optics_tem_mode.png")
            fig.tight_layout()
            fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
            plt.close(fig)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def newton_rings(radius_of_curvature_mm=1000.0, wavelength_nm=589.3, n_rings=8, n_grid=256, png=False):
    """The 2-D NEWTON'S-RINGS reflected pattern of a plano-convex surface (radius of curvature R) on a flat: the
    quadratic air gap makes the two reflections interfere as I(r)=sin^2(pi r^2/(lambda R)) -- a central DARK spot
    + dark rings at r_m = sqrt(m lambda R). Returns {ok, radius_of_curvature_mm, wavelength_nm, n_rings, field_mm,
    dark_ring_radii_mm, central_intensity (~0), oracle}. png=True saves the ring image. Off-trace; byte-identical."""
    bad = _wave_args_error(wavelength_nm, n_grid, radius_of_curvature_mm=radius_of_curvature_mm)
    if bad:
        return bad
    out, raster = _diagnostics.newton_rings_2d(float(radius_of_curvature_mm), float(wavelength_nm),
                                               n_rings=int(n_rings), nx=int(n_grid))
    if png:
        try:
            import os
            import tempfile
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            fig, ax = plt.subplots(figsize=(4.0, 4.0))
            fig.patch.set_facecolor("#0d0d10")
            ext = 0.5 * out["field_mm"]
            ax.imshow(raster, cmap="gray", origin="lower", extent=(-ext, ext, -ext, ext))
            ax.set_title("Newton's rings (R=%g mm, %g nm)" % (radius_of_curvature_mm, wavelength_nm),
                         color="#f4f4f6", fontsize=10)
            ax.set_xlabel("mm", color="#8a8a92", fontsize=8); ax.tick_params(colors="#8a8a92", labelsize=7)
            ax.set_facecolor("#0d0d10")
            png_path = os.path.join(tempfile.gettempdir(), "optics_newton_rings.png")
            fig.tight_layout()
            fig.savefig(png_path, dpi=120, facecolor=fig.get_facecolor())
            plt.close(fig)
            out["png"] = png_path
        except Exception as exc:
            out["png_error"] = str(exc)
    return out


def speckle_pattern(diam_mm=1.0, dz_mm=300.0, wavelength_nm=632.8, n_grid=512, dx_mm=0.02,
                    n_avg=1, seed=0, png=False):
    """Fully-developed LASER SPECKLE from a diffuse scatterer: a coherent beam illuminating a rough surface
    (diameter `diam_mm`) picks up a uniform random phase, and after `dz_mm` of propagation the intensity is a
    grainy speckle pattern. Off-trace + byte-identical (the live geometric trace has no diffuser/speckle). Returns
    {ok, contrast (sigma_I/<I> -> 1 for one frame), predicted_contrast (1/sqrt(n_avg)), var_over_mean2 (-> 1, the
    exponential-PDF signature), frac_above_mean (-> e^-1=0.368), speckle_size_mm, predicted_speckle_size_mm
    (lambda*z/D), n_avg, oracle}. `n_avg`>1 averages independent frames -> contrast falls as 1/sqrt(N) (the
    speckle-suppression law). png=True saves the pattern + its intensity histogram vs the exponential PDF."""
    bad = _wave_args_error(None, n_grid, dx_mm=dx_mm)
    if bad:
        return bad
    if diam_mm <= 0 or dz_mm <= 0 or wavelength_nm <= 0:
        return {"error": "diam_mm, dz_mm, wavelength_nm must be positive"}
    from . import speckle as _speckle
    png_path = os.path.join(tempfile.gettempdir(), "optics_speckle.png") if png else None
    metrics, _ = _speckle.speckle_metrics(int(n_grid), float(dx_mm), float(diam_mm), float(dz_mm),
                                          float(wavelength_nm), seed=int(seed), n_avg=int(n_avg),
                                          png_path=png_path)
    metrics["ok"] = True
    return metrics


def caustic_pattern(mirror_radius_mm=10.0, n_rays=1400, n_grid=400, png=False):
    """The coffee-cup CAUSTIC: parallel rays reflecting off the concave inner wall of a circular mirror
    (radius `mirror_radius_mm`) pile up on a NEPHROID -- the bright cusped curve seen in a coffee mug. Traced
    from first principles (reflect a fan of rays, accumulate the ray-density) and reported against the exact
    analytic envelope. Off-trace + byte-identical. Returns {ok, caustic_type ('nephroid'), cusp_distance_mm
    (= R/2, the mirror paraxial focus), mirror_focal_mm, density_on_envelope_ratio (caustic brightness vs
    background, >>1), brightest_point_mm (~the cusp), n_rays, oracle}. png=True saves the ray-density image with
    the analytic nephroid + the mirror circle overlaid."""
    bad = _wave_args_error(None, n_grid, n_rays=n_rays)
    if bad:
        return bad
    if mirror_radius_mm <= 0:
        return {"error": "mirror_radius_mm must be positive"}
    from . import caustic as _caustic
    png_path = os.path.join(tempfile.gettempdir(), "optics_caustic.png") if png else None
    metrics, _ = _caustic.caustic_metrics(float(mirror_radius_mm), n_rays=int(n_rays), n_grid=int(n_grid),
                                          png_path=png_path)
    metrics["ok"] = True
    return metrics


def slit_diffraction(width_um=100.0, n_slits=1, sep_um=0.0, wavelength_nm=632.8, n_grid=4096, png=False):
    """Single / double / N-slit FRAUNHOFER diffraction by FFT, validated against the textbook closed forms --
    the opt-in field layer (the geometric trace only CLIPS a beam at a slit; it cannot diffract). `n_slits`=1 ->
    single slit (sinc^2, first diffraction min at sin(theta)=lambda/width); 2 -> Young's double slit (the sinc^2
    envelope x cos^2, fringes spaced lambda/sep); N -> a coarse grating (sharp orders at sin(theta)=m*lambda/sep).
    Returns {rms_vs_analytic, first_min_sin_theta/first_min_theory (single), fringe_spacing_sin_theta/
    fringe_spacing_theory (multi), ...}: the measured pattern matches the analytic sinc^2 (x cos^2) to
    rms_vs_analytic (~1e-3). Off-trace; the live trace is byte-identical. E.g.
    slit_diffraction(100, 2, sep_um=500) -> double slit, fringes at lambda/d under a lambda/a envelope."""
    bad = _wave_args_error(wavelength_nm, n_grid, n_grid_max=8192, width_um=width_um)  # 1-D grid: higher cap
    if bad:
        return bad
    from . import field
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_slit.png")
    return field.slit_metrics(width_um * 1.0e-3, n_slits=int(n_slits), sep_mm=sep_um * 1.0e-3,
                              wavelength_nm=wavelength_nm, n_grid=int(n_grid), png_path=png_path)


def talbot_effect(period_um=100.0, wavelength_nm=632.8, n_periods=16, n_grid=512, png=False):
    """TALBOT self-imaging of a periodic grating via angular-spectrum propagation -- the opt-in field layer. A
    grating reproduces ITSELF at the Talbot distance `z_T = 2*period^2/lambda`, a HALF-PERIOD-SHIFTED copy at
    z_T/2, and no image at z_T/4. Returns {talbot_distance_mm, self_image_corr (~1 at z_T),
    half_talbot_shift_corr (~1 at z_T/2 vs a d/2 shift), quarter_corr (~0)} -- the self-image proves
    z_T=2 d^2/lambda. png=True saves the Talbot carpet (intensity vs x,z). Off-trace; live trace byte-identical."""
    bad = _wave_args_error(wavelength_nm, n_grid, period_um=period_um)
    if bad:
        return bad
    from . import field
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_talbot.png")
    return field.talbot_metrics(period_um * 1.0e-3, wavelength_nm, n_periods=int(n_periods),
                                n_grid=int(n_grid), png_path=png_path)


def turbulence_screen(n_grid=256, dx_mm=4.0, r0_mm=100.0, L0_mm=None, l0_mm=None, seed=0, subharmonics=3, png=False):
    """Generate a DENSE 2D Kolmogorov/von-Karman atmospheric PHASE SCREEN [radians] (FT method + sub-harmonics)
    and validate it against theory -- the off-trace turbulence layer the MODAL AO channel (`ao_kolmogorov`, a
    15-Zernike caricature) cannot represent. `r0_mm` = Fried parameter; `L0_mm`/`l0_mm` = von-Karman outer/inner
    scales (default = pure Kolmogorov). Returns {rms_rad, r_mm, D_meas, D_theory, ratio_mid, r0_fit_mm, ...}:
    the measured structure function tracks 6.88 (r/r0)^(5/3) (the validation Schmidt 2010 performs; subharmonics
    restore the low-frequency tail). Seed-pinned local RNG; the live trace is untouched + byte-identical. Feed
    the screen to propagate_field for a single-screen seeing/speckle PSF. The FULL multi-screen split-step
    inter-plane propagation is still out of scope (see capabilities()['scope_map'])."""
    from . import turbulence
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_turbulence.png")
    scr = turbulence.kolmogorov_screen(n_grid, dx_mm, r0_mm, L0_mm=L0_mm, l0_mm=l0_mm,
                                       seed=seed, subharmonics=subharmonics)
    return turbulence.screen_metrics(scr, dx_mm, r0_mm, png_path=png_path)


def propagate_turbulent(aperture_mm=60.0, r0_mm=10.0, wavelength_nm=500.0, n_screens=1, spacing_m=0.0,
                        n_grid=256, n_realizations=30, seed=0, png=False):
    """Image a plane wave through atmospheric turbulence and average the PSF -- the long-exposure 'seeing'
    analysis (composes `turbulence_screen` + `propagate_field`, both oracle-validated). `n_screens`=1 = the
    pupil-phase model; `n_screens`>1 with `spacing_m`>0 = the MULTI-SCREEN SPLIT-STEP (angular-spectrum between
    screens, adding scintillation). Returns {strehl_long, fwhm_long_rad, fwhm_diffraction_rad, broadening,
    seeing_ratio, energy_ratio}: the PSF is seeing-broadened toward lambda/r0 (>> the diffraction limit) and
    the propagation conserves energy. Off-trace, seed-pinned RNG; live trace byte-identical. NOTE: a finite FFT
    grid truncates the largest turbulence scales -> the long-exposure FWHM lands ~0.7x the ideal seeing
    lambda/r0 (a known FFT-phase-screen limitation, reduced by a bigger grid or a von-Karman outer scale)."""
    bad = _wave_args_error(wavelength_nm, n_grid, aperture_mm=aperture_mm, r0_mm=r0_mm)
    if bad:
        return bad
    from . import turbulence
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_turbulent_psf.png")
    return turbulence.long_exposure_psf(aperture_mm, r0_mm, wavelength_nm, n_screens=n_screens,
                                        spacing_m=spacing_m, n_grid=n_grid, n_realizations=n_realizations,
                                        seed=seed, png_path=png_path)


def propagate_pulse(t0_ps=1.0, p0_W=10.0, beta2_ps2_per_m=-0.02, gamma_per_W_per_m=0.002, length_m=None,
                    shape="sech", alpha_per_m=0.0, n_grid=2048, t_window_ps=None, n_steps=None, png=False):
    """Propagate an optical PULSE down a dispersive + Kerr-nonlinear fiber by the split-step NLSE -- the opt-in
    TEMPORAL-field layer, separate from the live steady-state trace (which has no time axis). `shape`='sech'
    (soliton) or 'gaussian'. The DEFAULTS give the fundamental soliton (N=1: T0=1ps, beta2=-0.02 ps^2/m,
    gamma=0.002 /W/m, P0=10W); `length_m` defaults to one soliton period z0=(pi/2)*L_D. Returns the pulse
    metrics {peak_power_W, energy_pJ, fwhm_ps, rms_bandwidth_THz, shape_invariance_err (~0 for a soliton),
    soliton_order_N, L_D_m, length_m}. On-demand analysis -- the live trace is untouched + byte-identical.
    Full supercontinuum (higher-order dispersion + Raman + self-steepening) is out of scope (scope_map)."""
    bad = _wave_args_error(None, n_grid, n_grid_max=65536, t0_ps=t0_ps)  # 1-D temporal grid: higher cap
    if bad:
        return bad
    import math
    import numpy as np
    from . import nlse
    LD = t0_ps ** 2 / abs(beta2_ps2_per_m) if beta2_ps2_per_m else float("inf")
    if length_m is None:
        length_m = (math.pi / 2.0) * LD if math.isfinite(LD) else 1.0
    if t_window_ps is None:
        t_window_ps = 100.0 * t0_ps
    n_grid = int(n_grid)
    dt = t_window_ps / n_grid
    t = (np.arange(n_grid) - n_grid // 2) * dt
    if n_steps is None:
        n_steps = max(100, int(length_m / (LD / 500.0))) if math.isfinite(LD) else 300
    dz = length_m / n_steps
    A0 = nlse.sech_pulse(t, t0_ps, p0_W) if shape == "sech" else nlse.gaussian_pulse(t, t0_ps, p0_W)
    png_path = None
    if png:
        import os
        import tempfile
        png_path = os.path.join(tempfile.gettempdir(), "optics_pulse.png")
    A = nlse.split_step(A0, dt, dz, n_steps, beta2_ps2_per_m, gamma_per_W_per_m, alpha_per_m)
    out = nlse.pulse_metrics(A, dt, A0=A0, t_ps=t, png_path=png_path)
    n2 = gamma_per_W_per_m * p0_W * t0_ps ** 2 / abs(beta2_ps2_per_m) if beta2_ps2_per_m else 0.0
    out["soliton_order_N"] = round(math.sqrt(n2), 4) if n2 > 0 else None
    out["L_D_m"] = round(LD, 4) if math.isfinite(LD) else None
    out["length_m"] = round(length_m, 4)
    out["n_steps"] = int(n_steps)
    return out


def monte_carlo_tissue(mu_a_per_mm=0.1, mu_s_per_mm=10.0, g=0.9, thickness_mm=10.0, n_photons=20000,
                       seed=0, png=False):
    """Monte-Carlo photon transport (MCML-style) through a homogeneous turbid SLAB -- the opt-in biomedical-optics
    layer (stochastic radiative transport, separate from the coherent ray/field trace). Returns the energy budget
    {reflectance, transmittance, absorbed, energy_sum} (R+T+A=1 at a matched boundary), the unscattered
    `ballistic_T` (-> Beer-Lambert exp(-mu_t L)), and the fluence(depth) whose far-field log-slope gives
    `penetration_depth_mm` (-> the diffusion mu_eff = sqrt(3 mu_a (mu_a+mu_s'))). Seed-pinned RNG; live trace
    byte-identical. The one genuinely GPU-friendly category (the CPU version here is fine for moderate n_photons)."""
    from . import mc_transport
    res = mc_transport.monte_carlo_slab(mu_a_per_mm, mu_s_per_mm, g, thickness_mm, n_photons=n_photons, seed=seed)
    res["diffusion_mu_eff_per_mm"] = round(mc_transport.diffusion_mu_eff(mu_a_per_mm, mu_s_per_mm, g), 5)
    if png:
        try:
            import os
            import tempfile
            import numpy as np
            try:
                from . import plotting as _plotting
            except ImportError:
                import plotting as _plotting
            plt = _plotting.pyplot()
            if plt is None:
                raise ImportError("matplotlib unavailable (plots need the GitHub build or a matplotlib install)")
            path = os.path.join(tempfile.gettempdir(), "optics_mc_tissue.png")
            d = np.asarray(res["depth_mm"]); fl = np.asarray(res["fluence"])
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.semilogy(d, np.maximum(fl, 1e-9), color="#ff6b4e", label="MC fluence")
            ax.semilogy(d, fl[0] * np.exp(-res["diffusion_mu_eff_per_mm"] * (d - d[0])), "--",
                        color="#888", label="diffusion exp(-mu_eff z)")
            ax.set_xlabel("depth [mm]"); ax.set_ylabel("fluence [a.u.]")
            ax.set_title("MCML slab  R=%.3f T=%.3f A=%.3f  delta=%.2fmm"
                         % (res["reflectance"], res["transmittance"], res["absorbed"], res["penetration_depth_mm"] or 0))
            ax.legend(fontsize=8)
            fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="#0d0d10")
            plt.close(fig)
            res["png"] = path
        except Exception as exc:
            res["png_error"] = str(exc)
    return res


def tolerance_scan(elements=None, target="", sigma_pos_mm=0.1, sigma_ang_deg=0.05, n=200, seed=0, tol_mm=None):
    """Monte-Carlo ALIGNMENT-tolerance sweep: perturb the pose (position + orientation) of `elements` by
    Gaussian setup errors (`sigma_pos_mm` / `sigma_ang_deg`), re-trace `n` times, and report how far the beam
    walks at `target` -- the pointing-stability statistics (RMS / 95th-pct / max landing displacement, mm).
    POSE-ONLY (kinematic DOFs); NOT glass/coating/figure tolerancing (that needs the full-wave / lens-design
    tools -- see capabilities()['scope_map']). Uses a SEED-PINNED local RNG (np.random.default_rng, no global
    state) and RESTORES every pose + the nominal trace afterwards, so it is off-trace + off the byte-identical
    digest. `tol_mm` adds a yield (fraction of samples landing within tol_mm). Returns {ok, n, hit_rate,
    pointing_rms_mm, pointing_mean_mm, pointing_p95_mm, pointing_max_mm, yield?} plus the echoed context
    (elements, target, sigma_pos_mm, sigma_ang_deg, seed)."""
    import math
    import numpy as np
    scene = _scene()
    names = list(elements) if isinstance(elements, (list, tuple)) else ([elements] if elements else None)
    if not names:
        return {"error": "give element name(s) to perturb (a list or a single name)"}
    objs = [scene.objects.get(nm) for nm in names]
    missing = [nm for nm, ob in zip(names, objs) if ob is None]
    if missing:
        return {"error": "element(s) not found: %s" % missing}
    if not target:
        return {"error": "give a 'target' element to measure the beam arrival at"}

    def _arrival(segs):
        hits = [s for s in segs if s.get("to") == target]
        return [float(c) for c in hits[-1]["p2"]] if hits else None

    p0 = _arrival(_trace(scene))
    if p0 is None:
        return {"error": "no beam reaches target '%s' in the nominal trace" % target}
    saved = [(ob, tuple(ob.location), tuple(ob.rotation_euler)) for ob in objs]
    rng = np.random.default_rng(int(seed))
    d2r = math.pi / 180.0
    walks = []
    try:
        for _ in range(int(n)):
            for ob, loc, rot in saved:
                ob.location = (loc[0] + rng.normal(0.0, sigma_pos_mm),
                               loc[1] + rng.normal(0.0, sigma_pos_mm),
                               loc[2] + rng.normal(0.0, sigma_pos_mm))
                ob.rotation_euler = (rot[0] + rng.normal(0.0, sigma_ang_deg * d2r),
                                     rot[1] + rng.normal(0.0, sigma_ang_deg * d2r),
                                     rot[2] + rng.normal(0.0, sigma_ang_deg * d2r))
            bpy.context.view_layer.update()
            p = _arrival(_trace(scene))
            if p is not None:
                walks.append(math.sqrt(sum((p[i] - p0[i]) ** 2 for i in range(3))))
    finally:
        for ob, loc, rot in saved:
            ob.location = loc
            ob.rotation_euler = rot
        bpy.context.view_layer.update()
        tracer.cached_segments = _trace(scene)

    n = int(n)
    w = np.asarray(walks, dtype=float) if walks else np.zeros(0)
    out = {
        "ok": True, "elements": names, "target": target,
        "sigma_pos_mm": sigma_pos_mm, "sigma_ang_deg": sigma_ang_deg, "n": n, "seed": int(seed),
        "hit_rate": round(len(walks) / n, 4) if n else 0.0,
        "pointing_rms_mm": round(float(np.sqrt(np.mean(w ** 2))), 5) if w.size else None,
        "pointing_mean_mm": round(float(w.mean()), 5) if w.size else None,
        "pointing_p95_mm": round(float(np.percentile(w, 95)), 5) if w.size else None,
        "pointing_max_mm": round(float(w.max()), 5) if w.size else None,
    }
    if tol_mm is not None and w.size:
        out["tol_mm"] = tol_mm
        out["yield"] = round(float(np.mean(w <= tol_mm)), 4)
    return out


def fdtd_derive_property(element, kind, backend="meep", **params):
    """ORCHESTRATE a full-wave sub-sim (Meep; Tidy3D as a cloud alt) to DERIVE a rigorous effective property
    for ONE element, then CACHE the JSON result as a custom ID-property on the element. The LIVE TRACE stays
    byte-identical -- the property is PRECOMPUTED here (the trace only reads `op.get('fdtd_<kind>')` if/when
    that path is wired; absent -> today's exact lumped path). If the backend is not importable, returns the
    closed-form FALLBACK (backend='fallback-closedform': grating direction == physics.grating_angle; multilayer
    == exact Abeles TMM, == ar_quarter_wave_reflectance for a quarter-wave; metaatom == low-confidence EMT) --
    never faking a Meep result. `kind` in {'grating_efficiency','stack_reflectance','metaatom_phase'}.
    This is tier (c) 'orchestrate Meep/Tidy3D' in capabilities()['scope_map'] -- a LIVE full-wave field is not
    shipped; this derives a property the lumped engine can then use."""
    import json
    from . import fdtd_bridge
    obj = _scene().objects.get(element) if isinstance(element, str) else element
    if obj is None or not getattr(obj, "optics", None):
        return {"error": "element %r not found / not optical" % element}
    op = obj.optics
    if kind == "grating_efficiency":
        period_um = params.pop("period_um", None)
        if period_um is None:
            lpm = getattr(op, "lines_per_mm", 0.0)
            if not lpm:
                return {"error": "element has no lines_per_mm; pass period_um=..."}
            period_um = 1000.0 / lpm                              # lines/mm -> period (um)
        params.setdefault("depth_um", float(op.get("groove_depth_um", 0.3)))
        params.setdefault("n_groove", float(op.get("n_groove", getattr(op, "refractive_index", 1.5))))
        params.setdefault("n_substrate", float(getattr(op, "refractive_index", 1.5)))
        result = fdtd_bridge.grating_efficiency(period_um=period_um, backend=backend, **params)
    elif kind == "stack_reflectance":
        params.setdefault("n_incident", 1.0)
        params.setdefault("n_substrate", float(getattr(op, "refractive_index", 1.52)))
        result = fdtd_bridge.stack_reflectance(backend=backend, **params)
    elif kind == "metaatom_phase":
        params.setdefault("n_substrate", float(getattr(op, "refractive_index", 1.45)))
        result = fdtd_bridge.metaatom_phase(backend=backend, **params)
    else:
        return {"error": "unknown kind %r (use grating_efficiency / stack_reflectance / metaatom_phase)" % kind}
    op["fdtd_%s" % kind] = json.dumps(result)
    op["fdtd_%s_provenance" % kind] = "%s; backend=%s" % (kind, result.get("backend"))
    return {"ok": True, "cached_on": getattr(obj, "name", str(element)),
            "kind": kind, "backend": result.get("backend"), "result": result}


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


def reset_mount(name):
    """RE-HOME a mount: zero every adjustment DOF (tip/tilt/rotation/translation knobs back to their
    home position) WITHOUT touching the stored base pose -- the lab move for a knob wound so far off
    that the beam is lost and the fine-aligner is blind (a fully-dropped beam gives align_element no
    gradient). The dark-port recovery pattern is: diagnose() names the dead mount -> reset_mount(it)
    -> align_element(it). (set_mount re-APPLIES a preset, which re-captures the base from the CURRENT
    -- possibly knocked -- pose; reset_mount is the one that returns to the true home.)
    Returns {ok, name, zeroed (how many DOFs), segments}."""
    scene = _scene()
    obj = scene.objects.get(name)
    if not obj:
        return {"error": "object not found: %s" % name}
    props = getattr(obj, "optics", None)
    if props is None or not props.is_optical:
        return {"error": "'%s' is not an optical element" % name}
    if not len(props.dofs):
        return {"error": "'%s' has no adjustment DOFs (no mount preset applied)" % name}
    n = 0
    for d in props.dofs:
        if d.current != 0.0:
            n += 1
        d.current = 0.0
    mounts.compose_pose(obj)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "name": name, "zeroed": n, "segments": len(tracer.cached_segments)}


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


def build_bench(spec):
    """Compile a DECLARATIVE bench spec (dict; JSON string; YAML when PyYAML exists) into a full built +
    traced + diagnosed bench -- the one-call alternative to hand-sequencing many add_component/
    place_relative calls. Spec: {name, elements: [{name, type, at:[x,y,z] | after:{of, along?, distance},
    direction:[..], out?:[..] (dual-port mirror/beamsplitter/grating), params:{...}}], mounts?:{name:preset}}.
    Compilation is ALL-OR-NOTHING: the whole spec validates (types, placement references, params checked
    against the real builder signatures -- unknown entries fail with the valid list) BEFORE anything is
    built, so a bad spec never half-mutates the scene. 18 element types; see the optics://workflows
    resources + capabilities(). Returns {ok, built, collection, elements, segments, diagnostics_counts}."""
    from . import bench_compiler
    return bench_compiler.build(spec)


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


def make_rail(members, rail_id=None, family='RLA'):
    """Put collinear elements on one dovetail rail: each rides a carrier on the shared rail (instead
    of a bare post on the board), so they translate along one straight track. `members` is a list of
    element names. Exposed in get_state()['rails'] (carrier positions in s_mm). Does NOT move the
    optics, so the trace is unchanged. `family` is RLA (default) or X95. Use place_on_rail(name,
    s_mm) to slide one along the rail."""
    scene = _scene()
    if not isinstance(members, (list, tuple)) or len(members) < 1:
        return {"error": "members must be a non-empty list of element names"}
    if family not in ('RLA', 'X95'):
        return {"error": "unknown rail family %r (use RLA or X95)" % family}
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
        o.optics.rail_family = family
    if _optomech.is_dressed(scene):
        _optomech.dress(scene)
    tracer.cached_segments = _trace(scene)
    return {"ok": True, "rail_id": rid, "family": family, "members": [o.name for o in objs],
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
    'WAVEPLATE': ["retardance_deg", "fast_axis_deg", "design_wl", "waveplate_crystal", "waveplate_order"],
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


def inspect_all():
    """The whole-bench INSPECTION DASHBOARD -- one call that chains inspect_beam (the beam state where it
    arrives) + inspect_element (what the optic does to it) for EVERY optical element, instead of N separate
    inspect calls. Each row: {name, type, role, in_power, throughput, w_mm, R_mm, curvature, m2,
    divergence_mrad, polarization, n_beams, outputs}. Plus a bench summary {n_elements, worst_diagnostic,
    issues}. The AI's single-glance numeric overview of the entire scene. READ-ONLY -- byte-identical."""
    scene = _scene()
    tracer.cached_segments = _trace(scene)
    elems = [o for o in scene.objects if getattr(o, "optics", None) and getattr(o.optics, "is_optical", False)]
    rows = []
    for o in elems:
        nm = o.name
        be = inspect_beam(nm)
        el = inspect_element(nm)
        if not isinstance(be, dict):
            be = {}
        if not isinstance(el, dict):
            el = {}
        pol = be.get("polarization")
        rows.append({
            "name": nm, "type": el.get("type"), "role": el.get("role"),
            "in_power": el.get("incoming_power"), "throughput": el.get("throughput"),
            "w_mm": be.get("w_mm"), "R_mm": be.get("R_mm"), "curvature": be.get("curvature"),
            "m2": be.get("m2"), "divergence_mrad": be.get("divergence_mrad"),
            "polarization": pol.get("kind") if isinstance(pol, dict) else pol,
            "n_beams": be.get("n_beams"), "outputs": el.get("outputs"),
        })
    diag = diagnose()
    issues = diag.get("issues") if isinstance(diag, dict) else None
    worst = None
    if issues:
        order = {"BAD": 3, "WARN": 2, "OK": 1}
        worst = max(issues, key=lambda i: order.get(i.get("severity", i.get("state", "")), 0), default=None)
    return {"ok": True, "n_elements": len(rows), "elements": rows,
            "worst_diagnostic": worst, "issues": issues}


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
