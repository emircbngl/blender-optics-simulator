"""agent_patterns.py -- named optical-design workflow patterns served as MCP RESOURCES.

Pure data, importable with no dependencies: the MCP server renders these as
``optics://workflows/...`` resources for agents, and the Blender regression suite imports
the same dict to assert every referenced tool still exists in optics_api (a drift check --
a renamed/removed tool fails CI instead of silently rotting the guidance).

Each pattern: intent (when to reach for it), steps (tool-by-tool), gotchas (the mistakes
agents actually make -- distilled from AGENT_GUIDE + the project's own session lessons),
example_scene (a build_example kind to practice on), tools_used (the drift-check list).
"""

PATTERNS = {
    "steer-beam-onto-detector": {
        "intent": "A beam misses (or half-misses) its detector after a knock/misplacement; walk it back "
                  "with the element's own kinematic degrees of freedom.",
        "steps": [
            "get_state() -- find the detector, the steering element (mirror/mount upstream), and the beam path",
            "inspect_beam(detector) -- confirm what actually arrives (power, offset); never guess from the render",
            "align_element(name, target) -- solve that element's TIP/TILT against the target",
            "diagnose() -- confirm no beam_clipped / mount_limit remains; re-run inspect_beam to verify power",
        ],
        "gotchas": [
            "align_element does BEAM-STEERING (small-angle), not gross re-positioning -- a fully bypassed "
            "optic needs place_relative first (diagnose flags it as optic_bypassed)",
            "mount_limit in diagnose() means the DOF range is exhausted: coarse-move with place_relative, THEN align",
        ],
        "example_scene": "michelson",
        "tools_used": ["get_state", "inspect_beam", "align_element", "diagnose", "place_relative"],
    },
    "recover-dark-port": {
        "intent": "A detector reads no light (dark_detector) and you must find WHERE the chain died and fix it.",
        "steps": [
            "diagnose() -- the dark_detector entry names the last element the beam reached (last_reached)",
            "inspect_element(last_reached) -- is it mis-aimed, absorbing, or a crossed polarizer?",
            "propose_corrections() -- read the suggested fix + maybe_intentional_if BEFORE acting",
            "reset_mount(last_reached) -- a FULLY-dropped beam gives the fine-aligner no gradient; re-home "
            "the dead mount first (DOFs to 0, base pose untouched)",
            "align_element(last_reached) -- fine-align from home; then inspect_beam(detector) to verify power",
        ],
        "gotchas": [
            "A dark port can be INTENTIONAL (interferometer dark fringe, unused reference port, beam dump) -- "
            "judge propose_corrections' fault_confidence before 'fixing'",
            "crossed_polarizer has LOW fault confidence (~0.3): usually an extinction measurement, not a bug",
            "Do NOT re-home with set_mount: re-applying a preset re-captures the base from the CURRENT "
            "(knocked) pose -- reset_mount is the one that returns to the true home",
        ],
        "example_scene": "mach_zehnder",
        "tools_used": ["diagnose", "inspect_element", "propose_corrections", "reset_mount", "align_element",
                       "inspect_beam"],
    },
    "null-interferometer-tilt": {
        "intent": "Interference fringes are a stripe pattern (tilt) and you want the flat-phase null "
                  "(or a specific fringe count).",
        "steps": [
            "sensor_capture(detector) or scan(kind='opd') -- see the current fringe state",
            "tilt_null(element, detector) -- drive the tilt DOFs until the fringe gradient nulls",
            "sensor_capture(detector) -- confirm the field went flat (single broad fringe)",
        ],
        "gotchas": [
            "Fringe VISIBILITY dropping toward zero is a coherence/OPD problem (coherence_mismatch in "
            "diagnose), not a tilt problem -- equalize arm lengths instead of tilting",
            "Two arms in ORTHOGONAL polarizations cannot interfere (pol_mismatch): fix polarization, not tilt",
        ],
        "example_scene": "michelson",
        "tools_used": ["sensor_capture", "scan", "tilt_null", "diagnose"],
    },
    "close-adaptive-optics-loop": {
        "intent": "Flatten an aberrated wavefront with the deformable mirror + wavefront sensor.",
        "steps": [
            "ao_measure(sensor) -- read the residual Zernike modes + RMS before touching anything",
            "ao_close_loop(sensor, dm) -- iterate sensor->DM until RMS converges",
            "get_wavefront(sensor) -- report the final modal residual; zonal_render for high-frequency figure",
        ],
        "gotchas": [
            "The WFS modal channel is a 15-Zernike LOW-PASS: high-frequency figure needs zonal_render, "
            "the modal RMS alone can look 'flat' while the surface is not",
            "The WFS also reads the beam's OWN R(z) curvature as defocus -- a clean diverging beam is NOT "
            "an error; reference the loop against a collimated beam",
        ],
        "example_scene": "adaptive_optics",
        "tools_used": ["ao_measure", "ao_close_loop", "get_wavefront", "zonal_render"],
    },
    "mode-match-into-fiber-or-cavity": {
        "intent": "Choose and place the single lens that converts the current Gaussian into a target "
                  "waist at a target plane (fiber face, cavity waist), then verify the coupling.",
        "steps": [
            "inspect_beam(at_the_coupling_plane) -- get the CURRENT waist w0 and its location",
            "mode_match(w0_in, s_in, w0_target, z_target, wavelength_nm) -- pure math: returns focal f + lens position",
            "add_component / place_relative -- place a lens with that focal at the solved distance",
            "coupling_efficiency(w_in, w_target, offset) -- verify eta; iterate placement if below spec",
        ],
        "gotchas": [
            "mode_match returns {ok:False, error} for an UNREACHABLE target -- do not force it; change the "
            "target plane or use a two-lens relay (design_telescope)",
            "eta=1 needs BOTH waist match and zero transverse offset; align first, then judge eta",
        ],
        "example_scene": "cage_system",
        "tools_used": ["inspect_beam", "mode_match", "add_component", "place_relative", "coupling_efficiency",
                       "design_telescope"],
    },
    "build-and-verify-bench": {
        "intent": "Stand up a new bench (or extend one) and PROVE it works before presenting anything.",
        "steps": [
            "build_example(kind) for a canonical start, or add_component + place_relative element by element",
            "trace_beam() -- the live trace is the ground truth, not the viewport",
            "diagnose() -- run the bench-intelligence gates EVERY time you modified the scene",
            "inspect_all() -- the per-element dashboard; then render() only once the gates are clean",
        ],
        "gotchas": [
            "ALWAYS diagnose() after moving/placing optics and BEFORE presenting a render -- a silently "
            "broken bench renders just fine (the optic_bypassed gate exists because of exactly this)",
            "w_mm and clear_aperture are both RADII -- compare like for like when checking clipping",
        ],
        "example_scene": "hybrid_system",
        "tools_used": ["build_example", "add_component", "place_relative", "trace_beam", "diagnose",
                       "inspect_all", "render"],
    },
    "judge-corrections-not-autofix": {
        "intent": "The user asks to 'fix the bench': surface problems and judge each against INTENT "
                  "(refuse / partial / accept) instead of blind auto-fixing.",
        "steps": [
            "propose_corrections() -- each issue arrives with suggested_fix + tool + maybe_intentional_if + fault_confidence",
            "For each: weigh fault_confidence against what the user was building (a knife-edge SHOULD clip)",
            "Apply only the accepted fixes with the suggested tool; re-run diagnose() to confirm",
        ],
        "gotchas": [
            "energy_violation (~0.9 confidence) is almost always a real config bug -- accept",
            "crossed_polarizer (~0.3) is usually a deliberate extinction measurement -- refuse unless the "
            "user clearly wanted light through",
        ],
        "example_scene": "michelson",
        "tools_used": ["propose_corrections", "diagnose"],
    },
    "emerge-phenomenon-deliberately": {
        "intent": "The bench conditions support a named phenomenon (interferogram, hologram, Fabry-Perot "
                  "resonance, Talbot carpet) and you want to produce it -- with consent, not silently.",
        "steps": [
            "detect_phenomena() -- which phenomena do the CURRENT trace conditions support, and where",
            "produce_phenomenon(name, accept=False) -- the dry-run: what WOULD be computed + why it might be unwanted",
            "Judge intent, then produce_phenomenon(name, accept=True) -- returns metrics + optional PNG",
        ],
        "gotchas": [
            "Emergence is an intent-judged act: a camera at a beam crossing may be a power meter, not a "
            "fringe detector -- the dry-run's maybe_not_wanted_if is there to be read",
        ],
        "example_scene": "newton_rings",
        "tools_used": ["detect_phenomena", "produce_phenomenon"],
    },
    "expand-beam-for-large-optic": {
        "intent": "A ~0.5 mm laser must fill a cm-scale optic; build the afocal expander instead of "
                  "unphysically inflating the source waist.",
        "steps": [
            "design_telescope(f1, f2) -- afocal pair: magnification |f2/f1|, spacing f1+f2 (SIGNED for Galilean)",
            "add_component + place_relative -- place the two lenses at the solved spacing on the beam axis",
            "inspect_beam(after_expander) -- verify the expanded w; then illuminate the large optic",
        ],
        "gotchas": [
            "Raising the source waist_um to 'fill' an optic is unphysical and diagnose() warns -- expand "
            "the beam optically",
            "Galilean (negative f1... or f2) keeps the pair SHORT and avoids an internal focus (good for high power)",
        ],
        "example_scene": "rail_system",
        "tools_used": ["design_telescope", "add_component", "place_relative", "inspect_beam", "diagnose"],
    },
    "swap-part-and-revalidate": {
        "intent": "Replace an element's mesh with a real vendor part (STL/OBJ) while keeping its optical "
                  "slot -- and prove the optics did not change.",
        "steps": [
            "get_state() -- record the pre-swap beam path (segment count, detector power)",
            "swap_part(name, filepath) -- the mesh changes, ports/pose/mount/beam role are preserved",
            "trace_beam() + inspect_beam(detector) -- assert the SAME optical numbers as before the swap",
        ],
        "gotchas": [
            "swap_part normalizes mesh orientation -- if the part looks flipped, solve the right "
            "orientation EMPIRICALLY through the swap path (do not pre-rotate the file blindly)",
            "The trace must be identical pre/post swap: meshes are cosmetic, ports are the physics",
        ],
        "example_scene": "michelson",
        "tools_used": ["get_state", "swap_part", "trace_beam", "inspect_beam"],
    },
}


def render_pattern_md(name):
    """One pattern as agent-readable markdown (the per-pattern MCP resource body)."""
    p = PATTERNS[name]
    lines = ["# %s" % name, "", "**When:** %s" % p["intent"], "", "**Steps:**"]
    lines += ["%d. %s" % (i + 1, s) for i, s in enumerate(p["steps"])]
    lines += ["", "**Gotchas:**"] + ["- %s" % g for g in p["gotchas"]]
    lines += ["", "Practice scene: `build_example('%s')`" % p["example_scene"],
              "Tools: " + ", ".join("`%s`" % t for t in p["tools_used"])]
    return "\n".join(lines)


def render_index_md():
    """The workflow-index MCP resource body."""
    lines = ["# Optical-design workflow patterns",
             "", "Read the matching pattern BEFORE multi-step work; each encodes the discipline",
             "(inspect-first, diagnose-before-present, judge-not-autofix) plus the gotchas that bite.", ""]
    for name, p in PATTERNS.items():
        lines.append("- `optics://workflows/%s` — %s" % (name, p["intent"]))
    return "\n".join(lines)
