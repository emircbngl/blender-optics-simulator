#!/usr/bin/env python3
"""Dedicated MCP server for the Blender Optics Simulator.

It wraps the add-on's ``optics_api`` over the localhost socket bridge shipped in the
add-on (``optical_alignment_sim/bridge.py``). Start the bridge inside the running
Blender — **Optics ▸ Simulation ▸ Start MCP Bridge** (or enable *Auto-start bridge* in
the add-on preferences) — then run this server from your MCP client.

Each tool opens a short-lived TCP connection to ``127.0.0.1:<port>``, sends one JSON
line ``{"fn", "args"}``, and returns the bridge's ``{"ok", "result"|"error"}`` reply.
Only the add-on's whitelisted optics_api functions are reachable; the socket is bound to
localhost.

Run:
    OPTICS_BRIDGE_PORT=9765 python3 optics_mcp_server.py
    # or via uv:  uvx --from "mcp[cli]" mcp run optics_mcp_server.py
    # (the `mcp` console script needs the [cli] extra; bare `mcp` lacks typer)
"""
from __future__ import annotations

import json
import os
import socket

from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("OPTICS_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPTICS_BRIDGE_PORT", "9765"))

mcp = FastMCP("blender-optics")


def _call(fn, _wait=60.0, **args):
    """Send one request to the bridge and return its JSON reply (or an error dict).
    `_wait` raises the socket timeout AND asks the bridge to hold the main-thread job
    that long (long operations: a final Cycles render, a large scan)."""
    try:
        req = {"fn": fn, "args": args}
        if _wait > 60.0:
            req["timeout"] = _wait - 10.0
        with socket.create_connection((HOST, PORT), timeout=_wait) as s:
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8").strip())
    except ConnectionRefusedError:
        return {"ok": False, "error": "bridge not reachable at %s:%d - start it in Blender "
                "(Optics > Simulation > Start MCP Bridge)" % (HOST, PORT)}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def _fmt(reply):
    return json.dumps(reply.get("result") if reply.get("ok") else reply, indent=2, default=str)


@mcp.tool()
def capabilities() -> str:
    """READ ME FIRST. Self-describing manifest for an agent that just connected: the scope, how the bench works,
    the tools grouped by purpose (the READ/inspect tools are 'your eyes' — call them, never guess), the common
    workflows, the example library, and the gotchas that bite. Nothing is mutated. Pair with get_state() (the
    live scene) and diagnose() (advisory corrections you weigh against user intent before acting)."""
    return _fmt(_call("capabilities"))


@mcp.tool()
def get_state() -> str:
    """Full optical state: every element's world center, ports (world position + normal),
    mount/DOFs, mechanics, params, misalignment, plus the traced beam path."""
    return _fmt(_call("get_state"))


@mcp.tool()
def build_example(kind: str = "michelson") -> str:
    """Build a canonical setup: mach_zehnder | michelson | hong_ou_mandel | bell |
    adaptive_optics | newton_rings."""
    return _fmt(_call("build_example", kind=kind))


@mcp.tool()
def trace_beam(mode: str = "") -> str:
    """Re-trace the beam path. mode: '' = current, or AUTO / ORDER."""
    return _fmt(_call("trace_beam", **({"mode": mode} if mode else {})))


@mcp.tool()
def diagnose() -> str:
    """Run the bench-intelligence error-detection gates over the current trace:
    beam_clipped (hard miss), vignetting (Gaussian wing clip), dark_detector /
    orphan_source, energy_violation (per-node + global power budget), and mount_limit
    (DOF range exhausted). READ-ONLY -- the beam trace is unaffected. Returns the
    diagnostics list ({kind, element, detail, severity}) + BAD/WARN counts."""
    return _fmt(_call("diagnose"))


@mcp.tool()
def propose_corrections() -> str:
    """ADVISORY correction proposals: diagnose() that also suggests a FIX for each issue, but applies
    NOTHING. Each proposal carries {issue, element, detail, severity, suggested_fix, tool,
    maybe_intentional_if, fault_confidence, advisory}. These are FEEDBACK, not commands -- weigh each
    against USER INTENT (did they ask for this on purpose? -- see 'maybe_intentional_if') and choose
    REFUSE / PARTIAL / ACCEPT. fault_confidence is how likely a genuine fault vs a design choice
    (crossed_polarizer ~0.3 = usually an intentional extinction; energy_violation ~0.9 = config bug).
    The honest default is to SURFACE, not silently fix. READ-ONLY -- the trace is byte-identical."""
    return _fmt(_call("propose_corrections"))


@mcp.tool()
def inspect_beam(element: str = "") -> str:
    """The full OPTICAL STATE of the beam where it reaches `element` (or the most-lit element if blank)
    -- the AI's numeric eyes on the beam, so you READ the physics instead of eyeballing a render:
    power, wavelength, Gaussian radius w + wavefront curvature R(z) (collimated/diverging/converging),
    beam quality M^2, far-field divergence + reconstructed waist, polarization (Stokes -> kind / azimuth
    / ellipticity / DOP), coherence length, and how many beams arrive. READ-ONLY -- byte-identical."""
    return _fmt(_call("inspect_beam", element=element))


@mcp.tool()
def inspect_element(name: str) -> str:
    """What an element DOES to the beam + what it is DOING right now: its optical role, the type-relevant
    params (focal_length, retardance, split_ratio, reflectivity, coating, nl_process, ...), and the LIVE
    trace -- incoming power and the OUTGOING children by kind (TRANSMIT / REFLECT / SPLIT_R / SHG / ...)
    with power + wavelength + throughput, so you SEE the actual effect (split 50/50, reflected 98%,
    converted 532 nm, clipped to Y%). READ-ONLY -- the trace is byte-identical."""
    return _fmt(_call("inspect_element", name=name))


@mcp.tool()
def detect_phenomena() -> str:
    """ADVISORY: the recognized optical PHENOMENA whose conditions the current trace MEETS -- two-beam
    interference, off-axis hologram recording (carrier fringe spacing Lambda = lambda/(2 sin(theta/2))),
    and more as added. READ-ONLY: the sim FLAGS that the geometry/coherence conditions are satisfied
    (e.g. "a reference + object beam cross at 8 deg on the camera -> off-axis hologram"); it does not
    auto-produce anything (the same surface-don't-act stance as diagnose). {ok, phenomena, count}."""
    return _fmt(_call("detect_phenomena"))


@mcp.tool()
def design_telescope(f1: float, f2: float) -> str:
    """Design an afocal two-lens telescope / beam-expander (PURE -- no scene mutation).
    Given objective focal f1 and eyepiece/relay focal f2, returns the afocal lens
    separation sep=f1+f2, the transverse magnification -f2/f1, the angular
    magnification -f1/f2, the beam expansion |f2/f1|, the type (keplerian if both
    focals positive, else galilean), and the composed afocal ABCD matrix
    [[-f2/f1, f1+f2], [0, -f1/f2]] (C=0 -> a collimated input exits collimated when the
    lenses are sep apart). Verified against the physics oracle."""
    return _fmt(_call("design_telescope", f1=f1, f2=f2))


@mcp.tool()
def optics_calc(quantity: str = "", params: dict = None) -> str:
    """Pure optics formula calculator -- no scene needed. Covers Brewster / critical angle, Sellmeier
    n(lambda[,T]), thin- & thick-lens, cavity finesse / FSR / stability, grating angle / resolving power,
    AR quarter-wave coating, fiber NA / V / mode-count, AOM deflection, Pockels Vpi, photon energy,
    coherence length, Gaussian divergence. Call with quantity="" to LIST every calculator and its
    arguments; otherwise pass the quantity plus its parameters in `params`, e.g.
    optics_calc("brewster_angle", {"n1": 1.0, "n2": 1.5}) or
    optics_calc("sellmeier_n", {"wl_nm": 633, "glass": "N-SF11"})."""
    return _fmt(_call("optics_calc", quantity=quantity, **(params or {})))


@mcp.tool()
def import_glass(name: str, coefficients: list, formula: int = 2,
                 ref_wl_nm: float = 587.56, ref_n: float = None) -> str:
    """Add a glass to the user catalog from refractiveindex.info Sellmeier coefficients. Fetch the RII
    YAML's `coefficients` ([c0, B1, C1, B2, C2, B3, C3]) and `type` (formula 1 or 2), then call this:
    formula 1 -> the C entries are resonance wavelengths (squared automatically); formula 2 -> already
    squared. c0 must be 0; up to 3 poles. Pass ref_n (the published index at ref_wl_nm) to validate the
    conversion before it is accepted. After import, sellmeier_n('<name>', ...) and the glass dropdowns
    see it. E.g. import_glass("MY-N-SF6", [0, 1.77931763, 0.0133714182, 0.338149866, 0.0617533621,
    2.08734474, 174.01759], 2, 587.56, 1.80518)."""
    return _fmt(_call("import_glass", name=name, coefficients=coefficients, formula=formula,
                      ref_wl_nm=ref_wl_nm, ref_n=ref_n))


@mcp.tool()
def wave_psf(wavelength_nm: float, f_number: float, aperture_diam_mm: float,
            defocus_waves: float = 0.0, n_grid: int = 512, png: bool = False) -> str:
    """Real diffraction PSF of a circular aperture via Fourier optics (PSF = |FFT(pupil*exp(i*2*pi*W))|^2)
    -- the OPT-IN wave layer. The live ray + Gaussian trace cannot diffract; this can. Returns Strehl,
    Airy radius (1.22*lambda*F#), first dark ring, FWHM, MTF cutoff (1/(lambda*F#)), and the encircled
    energy in the first ring (83.8% when ideal). `defocus_waves` adds RMS Noll-Z4 defocus (Strehl then
    matches the Marechal exp(-(2*pi*rms)^2)). png=True saves a log-scaled PSF image. E.g.
    wave_psf(550, 8, 25.4) -> Strehl 1, Airy 5.37 um; wave_psf(550, 8, 25.4, defocus_waves=0.0714) -> Strehl ~0.82."""
    return _fmt(_call("wave_psf", wavelength_nm=wavelength_nm, f_number=f_number,
                      aperture_diam_mm=aperture_diam_mm, defocus_waves=defocus_waves, n_grid=n_grid, png=png))


@mcp.tool()
def propagate_field(wavelength_nm: float, w0_mm: float = None, aperture_mm: float = None,
                    dz_mm: float = 0.0, n_grid: int = 256, dx_mm: float = None, png: bool = False) -> str:
    """Free-space ANGULAR-SPECTRUM propagation of a sampled scalar field over dz_mm -- the OPT-IN field layer,
    separate from the live geometric+Gaussian trace (which cannot diffract BETWEEN planes). Source: a Gaussian
    waist `w0_mm` OR a clear circular `aperture_mm`. Returns the propagated beam metrics (w_2sigma_mm, peak,
    total_power, centroid, fresnel_number, w_analytic_mm); png=True saves an intensity image. Reproduces the
    Gaussian w(z) closed form and is reversible (+dz then -dz = digital-hologram back-propagation). The primitive
    behind multi-plane Fresnel; FDTD/NLSE stay out of scope (see capabilities()['scope_map']). E.g.
    propagate_field(632.8, w0_mm=0.3, dz_mm=300) -> w_2sigma ~ w_analytic ~ 0.361 mm."""
    return _fmt(_call("propagate_field", wavelength_nm=wavelength_nm, w0_mm=w0_mm, aperture_mm=aperture_mm,
                      dz_mm=dz_mm, n_grid=n_grid, dx_mm=dx_mm, png=png))


@mcp.tool()
def design_4f(f1: float, f2: float) -> str:
    """Design a full 4f relay (PURE -- no scene mutation). Object at the front focal
    plane of L1, lenses f1+f2 apart, image at the back focal plane of L2. Returns the
    object->L1->L2->image spacings seps=[f1, f1+f2, f2], the total length 2*(f1+f2),
    the transverse magnification -f2/f1, the beam expansion |f2/f1|, and the L1->L2
    afocal ABCD matrix. Verified against the physics oracle."""
    return _fmt(_call("design_4f", f1=f1, f2=f2))


@mcp.tool()
def mode_match(w0_in: float, s_in: float, w0_t: float, z_t: float,
               wavelength_nm: float, m2: float = 1.0) -> str:
    """Solve the single thin lens that mode-matches a Gaussian beam into a target mode --
    the lens-to-cavity/fiber design solve (B3, PURE -- no scene mutation). Inputs: input
    waist w0_in (mm) located s_in mm before the lens, target waist w0_t (mm) at distance z_t
    mm past the lens, wavelength_nm, and optional beam quality m2. Returns the solved focal f
    (and the conjugate-plane second root f_alt), the REQUIRED lens position s_lens, the waist
    magnification m, the input Rayleigh range zR, the achieved_w0 / achieved_z obtained by
    actually propagating the input q through the solved lens (self-checking against the
    target), and the power-coupling efficiency `coupling` into the target mode (== 1 on a
    clean solve). Returns {ok:False, error:...} for a non-physical input or an UNREACHABLE
    target (no real focal -- e.g. demagnifying too close to the lens); no focal is fabricated.
    Verified by forward q-propagation against the physics oracle."""
    return _fmt(_call("mode_match", w0_in=w0_in, s_in=s_in, w0_t=w0_t, z_t=z_t,
                      wavelength_nm=wavelength_nm, m2=m2))


@mcp.tool()
def coupling_efficiency(w_in: float, w_t: float, offset: float = 0.0) -> str:
    """Power-coupling efficiency eta of a Gaussian mode (waist w_in, mm) into a target
    Gaussian mode (waist w_t, mm) transversely offset by `offset` mm -- the fiber/cavity
    coupling metric (B3, PURE). eta = [2 w_in w_t/(w_in^2+w_t^2)]^2 * exp(-2 offset^2/
    (w_in^2+w_t^2)): symmetric, dimensionless, bounded (0,1], and == 1 only when w_in==w_t
    and offset==0. Returns the scalar eta, or {ok:False, error:...} for a non-physical waist.
    The coupling formula is verified against the physics oracle (pass_rate 1.0)."""
    return _fmt(_call("coupling_efficiency", w_in=w_in, w_t=w_t, offset=offset))


@mcp.tool()
def align_all() -> str:
    """Auto-align every element's kinematic knobs toward its target detector."""
    return _fmt(_call("align_all"))


@mcp.tool()
def set_mount(name: str, preset: str) -> str:
    """Apply a kinematic-mount preset (e.g. KM100CP/M) to element `name`."""
    return _fmt(_call("set_mount", name=name, preset=preset))


@mcp.tool()
def set_param(name: str, key: str, value: float | int | str | bool) -> str:
    """Set an optical parameter on element `name`. Accepts numbers (reflectivity, wavelength,
    pol_angle, ...), strings (element_type, analyzer, pol_type, coating, ...), or booleans
    (is_pbs, ...) -- optics_api.set_param takes any scalar; a float-only type blocked the rest."""
    return _fmt(_call("set_param", name=name, key=key, value=value))


@mcp.tool()
def add_component(key: str, location: list = None) -> str:
    """Spawn a catalog component by key (or its generic mesh-free fallback)."""
    return _fmt(_call("add_component", key=key, location=location or [0.0, 0.0, 0.0]))


@mcp.tool()
def swap_part(name: str, filepath: str, refit_ports: bool = False) -> str:
    """Replace element `name`'s mesh from an STL/OBJ (or STEP/IGES) file, keeping its
    optical slot (ports / pose / mount / beam role)."""
    return _fmt(_call("swap_part", name=name, filepath=filepath, refit_ports=refit_ports))


@mcp.tool()
def place_relative(name: str, reference: str, axis: str = "BEAM", distance: float = 50.0,
                   link: bool = True, align_rotation: bool = True) -> str:
    """Place element `name` a distance (mm) from `reference` along an axis (BEAM / +X / -X /
    +Y / -Y / +Z / -Z); link=True makes it follow the reference live; align_rotation=False
    keeps the element's current rotation instead of snapping it to the reference."""
    return _fmt(_call("place_relative", name=name, reference=reference, axis=axis,
                      distance=distance, link=link, align_rotation=align_rotation))


@mcp.tool()
def scan(kind: str = "STAGE", lo: float = 0.0, hi: float = 0.002, steps: int = 120,
         element: str = "") -> str:
    """Sweep a parameter (STAGE OPD / WAVEPLATE angle / WAVELENGTH) and write a plot PNG +
    CSV; `element` names the swept part (e.g. the OPD-stage mirror)."""
    return _fmt(_call("scan", _wait=300.0, kind=kind, lo=lo, hi=hi, steps=steps,
                      **({"element": element} if element else {})))


@mcp.tool()
def beam_profile(detector: str = "", samples: int = 24) -> str:
    """Gaussian spot radius w(z) along the beam path source -> detector: waist position/size,
    element positions + clear apertures, plus a plot PNG + CSV."""
    return _fmt(_call("beam_profile", detector=detector, samples=samples))


@mcp.tool()
def render(preset: str = "preview", camera: str = "HERO", filepath: str = "") -> str:
    """Configure or render the scene. preset: preview | final; camera: HERO/TOP/FRONT/SIDE.
    Pass filepath to write a still."""
    return _fmt(_call("render", _wait=600.0, preset=preset, camera=camera,
                      **({"filepath": filepath} if filepath else {})))


@mcp.tool()
def render_sequence(frames: int = 48, motion: str = "ORBIT", out_dir: str = "",
                    engine: str = "EEVEE", turns: float = 1.0, encode: str = "auto") -> str:
    """Render a camera-orbit PNG sequence of the current setup (headless animation pipeline) and,
    if ffmpeg is present, encode an mp4 (best-effort; the PNG sequence is always produced).
    engine: EEVEE (fast) | CYCLES (realistic). Returns {frames, dir, pattern, ffmpeg, video}."""
    return _fmt(_call("render_sequence", _wait=900.0, frames=frames, motion=motion,
                      engine=engine, turns=turns, encode=encode,
                      **({"out_dir": out_dir} if out_dir else {})))


@mcp.tool()
def tag_element(name: str, element_type: str = "", auto_ports: bool = True) -> str:
    """Mark object `name` as an optical element (optionally set its type) and auto-detect ports."""
    args = {"name": name, "auto_ports": auto_ports}
    if element_type:
        args["element_type"] = element_type
    return _fmt(_call("tag_element", **args))


@mcp.tool()
def align_element(name: str) -> str:
    """Auto-align one element's kinematic knobs toward its target, then re-trace."""
    return _fmt(_call("align_element", name=name))


@mcp.tool()
def auto_align(actuators: list = None, targets: list = None,
               gain: float = 1.0, eps: float = 0.02, max_iters: int = 8) -> str:
    """On-demand auto-aligner: the closed-loop influence-matrix corrector (the same
    AI/auto-align the promo teased). Drives steering knobs until the beam is centered
    on the reference apertures, by calibrating dy/du (poke each DOF, re-trace) and
    iterating u <- u - gain*A_pinv(y - y_target) to eps.

    GENERIC: with no args it auto-picks every kinematic (tip/tilt) element and the
    iris/pinhole/detector planes downstream of them. Or name what to steer:
      * actuators: list of element names (uses their tip/tilt DOFs), or
        [name, kind] / [name, [kinds]] pairs to pick specific DOFs.
      * targets: list of reference-aperture element names (irises / detectors).

    Returns {ok, residual_before, residual_after, iterations, converged, history}.
    This MOVES DOFs - only call it when you actually want to align (it is never run
    during a normal trace)."""
    args = {"gain": gain, "eps": eps, "max_iters": max_iters}
    if actuators:
        args["actuators"] = actuators
    if targets:
        args["targets"] = targets
    return _fmt(_call("auto_align", _wait=300.0, **args))


@mcp.tool()
def tilt_null(detector: str = "", mirrors: list = None,
              gain: float = 1.0, eps: float = 0.04, max_iters: int = 8,
              piston_steps: int = 21) -> str:
    """Interferometer tilt-null solver (B4): automate the benchtop "spread the fringes to a
    single null". It reads the 2-D fringe pattern at the recombination detector, recovers the
    relative wavefront TILT between the two interfering arms (the fringe spatial frequency
    fx = tilt/lambda, cycles/mm), drives the two steering mirror tip/tilt DOFs until the fringe
    frequency -> 0 (dense tilt-fringes collapse to one broad fringe), then runs a 1-DOF piston
    (OPD) search to peak the fringe visibility.

    GENERIC: with no args it auto-picks the detector (the lit terminal with the most interfering
    beams) and the recombining-arm mirror's tip+tilt. Or name them:
      * detector: the recombination detector element name.
      * mirrors: steering actuators -- element names, or [name, kind] / [name, [kinds]] pairs.

    A single intensity frame cannot tell +tilt from -tilt (cos is even), so the solver descends
    the (V-shaped) fringe frequency to its ~1-fringe optical floor -- below one fringe across
    the aperture the tilt is unmeasurable, which IS a single broad fringe. This MOVES the
    steering + piston DOFs (only when called; a normal trace never enters it). Returns
    {ok, detector, tilt_before_deg/after_deg, fringe_freq_before/after, fringe_count_before/after,
    visibility_before/after, iterations, converged, history, controls, piston}."""
    args = {"gain": gain, "eps": eps, "max_iters": max_iters, "piston_steps": piston_steps}
    if detector:
        args["detector"] = detector
    if mirrors:
        args["mirrors"] = mirrors
    return _fmt(_call("tilt_null", _wait=300.0, **args))


@mcp.tool()
def check_mechanics() -> str:
    """Report the worst opto-mechanical limit (post pull-out, cage-rod travel, ...)."""
    return _fmt(_call("check_mechanics"))


@mcp.tool()
def bake_beams(radius: float = 0.6) -> str:
    """Bake the traced beam path into emission-cylinder meshes (for rendering)."""
    return _fmt(_call("bake_beams", radius=radius))


@mcp.tool()
def clear_beams() -> str:
    """Remove all baked beam geometry."""
    return _fmt(_call("clear_beams"))


# --- adaptive optics (modal Zernike: wavefront sensor + deformable mirror) ----
@mcp.tool()
def ao_measure(sensor: str) -> str:
    """Read the residual Zernike wavefront error (waves) at a wavefront sensor. {zernike, rms}."""
    return _fmt(_call("ao_measure", sensor=sensor))


@mcp.tool()
def get_wavefront(sensor: str) -> str:
    """Alias of ao_measure: a wavefront sensor's reconstructed wavefront (Zernike + RMS)."""
    return _fmt(_call("get_wavefront", sensor=sensor))


@mcp.tool()
def zonal_render(sensor: str = "", element: str = "", px: int = 0, filepath: str = "") -> str:
    """Dense ZONAL surface-figure 'sensor render': the raw wavefront map a WAVEFRONT SENSOR reads from the
    reflective element whose reflected beam reaches it (pass `sensor` -- requires the beam to land on the WFS),
    or a named reflective `element` directly. Bypasses the 15-mode modal low-pass; writes a PNG and publishes
    the map to the sensor. Use the 'surface_figure' example for a ready bench (oblique laser -> figured
    reflector -> WFS); swap_part any mesh onto the reflector to read its figure."""
    return _fmt(_call("zonal_render", sensor=sensor, element=element, px=px, filepath=filepath))


@mcp.tool()
def pyramid_wfs(sensor: str, px: int = 128, filepath: str = "") -> str:
    """Read a wavefront sensor as a PYRAMID WFS: instead of the modal Zernike vector (ao_measure /
    Shack-Hartmann), report the local wavefront SLOPE -- the 4-pupil intensity differences a pyramid sensor
    encodes as Sx = dW/dx, Sy = dW/dy. Reads the same wavefront (modal aberr + the beam's own curvature
    defocus), writes a slope-FIELD PNG (hue = slope direction, value = magnitude) + publishes it to the
    sensor. A pure defocus reads a RADIAL slope. Tier-1 GEOMETRIC (the gradient a pyramid integrates, not a
    diffractive 4-pupil image). {sensor, wavefront_rms, slope_x_rms, slope_y_rms, slope_rms, ...}."""
    return _fmt(_call("pyramid_wfs", sensor=sensor, px=px, filepath=filepath))


@mcp.tool()
def sensor_capture(sensor: str) -> str:
    """What a wavefront SENSOR actually CAPTURES of the beam reaching it (it does NOT swallow the whole beam --
    a beam wider than the sensor is truncated at its aperture). Returns the beam radius at the sensor, the
    clear aperture, the captured POWER fraction, the figure-footprint fraction captured (rho_max), and the
    captured zonal figure RMS / hit_frac. A collimated beam that fits reads the whole figure; a diverging beam
    that overfills reads only its centre — the difference is produced by the simulation."""
    return _fmt(_call("sensor_capture", sensor=sensor))


@mcp.tool()
def ao_command(dm: str, coeffs: list) -> str:
    """Set a deformable mirror's command (Zernike coefficients, in waves)."""
    return _fmt(_call("ao_command", dm=dm, coeffs=coeffs))


@mcp.tool()
def ao_close_loop(sensor: str, dm: str, gain: float = 0.5, iters: int = 15) -> str:
    """Close the modal adaptive-optics loop (wavefront sensor -> deformable-mirror integrator)
    until the residual wavefront RMS flattens. Returns the RMS history (open-loop first,
    corrected last)."""
    return _fmt(_call("ao_close_loop", sensor=sensor, dm=dm, gain=gain, iters=iters))


@mcp.tool()
def ao_close_loop_recon(sensor: str, dm: str, gain: float = 0.8, leak: float = 0.99,
                        method: str = 'TSVD', iters: int = 30) -> str:
    """B5: close the AO loop with the full reconstructor control structure -- an interaction
    matrix B (poke each DM mode, record the wavefront-sensor response), a reconstructor R=B+
    (method='TSVD' truncated-SVD pseudoinverse, or 'DAMPED_TRANSPOSE' noise-tolerant c*B^T), and
    the leaky integrator x_{k+1}=leak*x_k - gain*R*w_k. Returns {rms_before, rms_after, reduction,
    history, singular spectrum}. TSVD converges fast; damped-transpose is slower but never amplifies
    ill-conditioned/noise modes."""
    return _fmt(_call("ao_close_loop_recon", sensor=sensor, dm=dm, gain=gain, leak=leak,
                      method=method, iters=iters))


@mcp.tool()
def ao_kolmogorov(aberrator: str, r0_mm: float = None, D_mm: float = None, seed: int = 0) -> str:
    """B5: drive an ABERRATOR element's injected wavefront from a PHYSICAL Fried parameter r0
    (Kolmogorov/Noll turbulence statistics, sigma^2=1.0299*(D/r0)^(5/3) rad^2). Smaller r0 =
    stronger turbulence. r0_mm / D_mm default to the scene AO props. {ok, r0_mm, D_mm, rms, modes}."""
    args = {"aberrator": aberrator, "seed": seed}
    if r0_mm is not None:
        args["r0_mm"] = r0_mm
    if D_mm is not None:
        args["D_mm"] = D_mm
    return _fmt(_call("ao_kolmogorov", **args))


@mcp.tool()
def export_svg(filepath: str) -> str:
    """Export a top-view 2-D vector (SVG) schematic of the optical layout + beam path to filepath
    (element glyphs, port ticks, wavelength-coloured beams) -- a dependency-free publication figure."""
    return _fmt(_call("export_svg", filepath=filepath))


@mcp.tool()
def dress_bench(enable: bool = True) -> str:
    """Spawn (enable=True) or remove (enable=False) the procedural opto-mechanics: a hole-grid
    breadboard, a post + pedestal under each optic, and a mount ring framing it. Optics are NOT
    moved, so the trace is unchanged. After dressing, get_state()['bench'] reports the grid
    (pitch, origin, extent) and the occupied holes -- read that to know where parts can seat."""
    return _fmt(_call("dress_bench", enable=enable))


@mcp.tool()
def set_grid(standard: str = "", pitch_mm: float = 0.0) -> str:
    """Set the breadboard hole-grid standard. standard in {METRIC (25 mm/M6), IMPERIAL (1"/1/4-20),
    CUSTOM}; pitch_mm sets a custom pitch in mm (implies CUSTOM). Default is metric. Re-dresses the
    bench if dressed. Returns the active grid (also visible in get_state()['bench'])."""
    args = {}
    if standard:
        args["standard"] = standard
    if pitch_mm and pitch_mm > 0.0:
        args["pitch_mm"] = pitch_mm
    return _fmt(_call("set_grid", **args))


@mcp.tool()
def place_on_grid(name: str, col: int, row: int) -> str:
    """Move optical element `name` over breadboard hole (col, row), keeping its height and
    orientation -- grid-aware placement for building a layout. The bench must be dressed first
    (call dress_bench). Read get_state()['bench'] for grid extent (cols x rows) and occupied
    holes. Unlike dress_bench this DOES move the part, so the trace updates."""
    return _fmt(_call("place_on_grid", name=name, col=col, row=row))


@mcp.tool()
def make_cage(members: list, size_mm: int = 30, cage_id: str = "") -> str:
    """Group collinear optical elements into a cage assembly: they share 4 rods (e.g. Ø6 mm on a
    30 mm square for SM1/Ø1") and one cage post instead of an individual post each. `members` is a
    list of element names; `size_mm` in {16, 30, 60} (companion optic Ø1/2"/Ø1"/Ø2"). The cage is
    reported in get_state()['cages']. Optics are not moved, so the trace is unchanged."""
    return _fmt(_call("make_cage", members=members, size_mm=size_mm, cage_id=cage_id or None))


@mcp.tool()
def make_tube(members: list, thread: str = "SM1", tube_id: str = "") -> str:
    """Stack collinear in-line optics into one SM lens-tube barrel (they share one barrel + one post
    instead of an individual post each). `members` is a list of element names; `thread` in
    {SM05, SM1, SM2} (Ø1/2", Ø1", Ø2"). Reported in get_state()['tubes']. Optics are not moved, so
    the trace is unchanged."""
    return _fmt(_call("make_tube", members=members, thread=thread, tube_id=tube_id or None))


@mcp.tool()
def make_rail(members: list, rail_id: str = "") -> str:
    """Put collinear elements on one dovetail rail: each rides a carrier on the shared rail instead
    of a bare post, so they translate along one straight track. `members` is a list of element names.
    Reported in get_state()['rails'] (carrier s_mm). Optics are not moved -> trace unchanged."""
    return _fmt(_call("make_rail", members=members, rail_id=rail_id or None))


@mcp.tool()
def place_on_rail(name: str, s_mm: float) -> str:
    """Slide rail-mounted element `name` to position s_mm along its rail (s=0 at the rail start).
    Moves the optic along the rail axis only, so the trace updates. The element must be on a rail
    (call make_rail first)."""
    return _fmt(_call("place_on_rail", name=name, s_mm=s_mm))


if __name__ == "__main__":
    mcp.run()
