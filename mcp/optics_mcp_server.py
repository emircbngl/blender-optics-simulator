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
