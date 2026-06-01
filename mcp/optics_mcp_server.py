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
    # or via uv:  uvx --from mcp mcp run optics_mcp_server.py
"""
from __future__ import annotations

import json
import os
import socket

from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("OPTICS_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPTICS_BRIDGE_PORT", "9765"))

mcp = FastMCP("blender-optics")


def _call(fn, **args):
    """Send one request to the bridge and return its JSON reply (or an error dict)."""
    try:
        with socket.create_connection((HOST, PORT), timeout=60.0) as s:
            s.sendall((json.dumps({"fn": fn, "args": args}) + "\n").encode("utf-8"))
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
    """Build a canonical setup: mach_zehnder | michelson | hong_ou_mandel | bell."""
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
def set_param(name: str, key: str, value: float) -> str:
    """Set an optical parameter (reflectivity, wavelength, pol_angle, ...) on element `name`."""
    return _fmt(_call("set_param", name=name, key=key, value=value))


@mcp.tool()
def add_component(key: str, location: list = [0.0, 0.0, 0.0]) -> str:
    """Spawn a catalog component by key (or its generic mesh-free fallback)."""
    return _fmt(_call("add_component", key=key, location=location))


@mcp.tool()
def swap_part(name: str, filepath: str, refit_ports: bool = False) -> str:
    """Replace element `name`'s mesh from an STL/OBJ (or STEP/IGES) file, keeping its
    optical slot (ports / pose / mount / beam role)."""
    return _fmt(_call("swap_part", name=name, filepath=filepath, refit_ports=refit_ports))


@mcp.tool()
def place_relative(name: str, reference: str, axis: str = "BEAM", distance: float = 50.0,
                   link: bool = True) -> str:
    """Place element `name` a distance (mm) from `reference` along an axis (BEAM / +X / -X /
    +Y / -Y / +Z / -Z); link=True makes it follow the reference live."""
    return _fmt(_call("place_relative", name=name, reference=reference, axis=axis,
                      distance=distance, link=link))


@mcp.tool()
def scan(kind: str = "STAGE", lo: float = 0.0, hi: float = 0.002, steps: int = 120,
         element: str = "") -> str:
    """Sweep a parameter (STAGE OPD / WAVEPLATE angle / WAVELENGTH) and write a plot PNG +
    CSV; `element` names the swept part (e.g. the OPD-stage mirror)."""
    return _fmt(_call("scan", kind=kind, lo=lo, hi=hi, steps=steps,
                      **({"element": element} if element else {})))


@mcp.tool()
def render(preset: str = "preview", camera: str = "HERO", filepath: str = "") -> str:
    """Configure or render the scene. preset: preview | final; camera: HERO/TOP/FRONT/SIDE.
    Pass filepath to write a still."""
    return _fmt(_call("render", preset=preset, camera=camera,
                      **({"filepath": filepath} if filepath else {})))


if __name__ == "__main__":
    mcp.run()
