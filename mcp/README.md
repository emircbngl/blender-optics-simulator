# Blender Optics — dedicated MCP server

A standalone [MCP](https://modelcontextprotocol.io) server that lets an MCP client
(e.g. Claude Desktop / Claude Code) drive a **running** Blender Optics Simulator scene:
build canonical setups, read the full optical state (ports, world normals, beam path,
detector readings), align, swap parts, position elements relative to one another, scan,
and render.

It talks to the add-on through a tiny **localhost socket bridge** built into the add-on
(`optical_alignment_sim/bridge.py`), so it works against the live Blender you already
have open — no headless re-launch, no file round-trips.

```
MCP client  ──stdio──▶  optics_mcp_server.py  ──TCP 127.0.0.1:9765──▶  Blender add-on bridge ──▶ optics_api
```

## 1. Start the bridge in Blender

In the running Blender: **View3D ▸ Sidebar (N) ▸ Optics ▸ Simulation ▸ Start MCP Bridge**.
The status line shows `MCP bridge: 127.0.0.1:9765 (live)`. (Or tick *Auto-start bridge* in
the add-on preferences to start it on load. Change the port there if 9765 is taken.)

Only the add-on's whitelisted `optics_api` functions are reachable, and the socket binds to
`127.0.0.1` only.

## 2. Run the MCP server

Requires the [`mcp`](https://pypi.org/project/mcp/) Python SDK.

```bash
# with uv (recommended)
uv run --with mcp python optics_mcp_server.py

# or plain python
pip install mcp
OPTICS_BRIDGE_PORT=9765 python3 optics_mcp_server.py
```

Environment:
- `OPTICS_BRIDGE_PORT` — bridge port (default `9765`, must match the add-on preference).
- `OPTICS_BRIDGE_HOST` — default `127.0.0.1`.

## 3. Wire it into an MCP client

Claude Desktop / Claude Code config (`claude_desktop_config.json` or your `mcp` settings):

```json
{
  "mcpServers": {
    "blender-optics": {
      "command": "uv",
      "args": ["run", "--with", "mcp", "python",
               "/absolute/path/to/mcp/optics_mcp_server.py"],
      "env": { "OPTICS_BRIDGE_PORT": "9765" }
    }
  }
}
```

(Plain `python3 /absolute/path/to/mcp/optics_mcp_server.py` works too if `mcp` is installed
in that interpreter.)

## Tools

| Tool | What it does |
|------|--------------|
| `get_state` | Full optical state: elements, ports (world pos + normal), mounts/DOFs, beam path, detector report |
| `build_example` | Build `mach_zehnder` / `michelson` / `hong_ou_mandel` / `bell` |
| `trace_beam` | Re-trace the beam path |
| `align_all` | Auto-align every element's knobs toward its target |
| `set_mount` | Apply a kinematic-mount preset to an element |
| `set_param` | Set an optical parameter (reflectivity, wavelength, pol_angle, …) |
| `add_component` | Spawn a catalog component (or its generic fallback) |
| `swap_part` | Replace an element's mesh from a file, keeping its optical slot |
| `place_relative` | Place an element relative to another (along an axis or its beam), optionally linked |
| `scan` | Sweep OPD / waveplate angle / wavelength → plot PNG + CSV |
| `render` | Configure or render the scene (EEVEE preview / Cycles final) |

## Notes

- The bridge dispatches every call onto Blender's main thread (bpy is not thread-safe), so
  tools are serialized and safe.
- An interactively-authenticated Blender session is required for live edits; the server
  itself is stateless and reconnects per call.
