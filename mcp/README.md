<!-- mcp-name: io.github.emircbngl/blender-optics-simulator -->

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

The server is a packaged console app — `blender-optics-mcp`. Pick whichever you like:

```bash
# zero-install, one line (recommended) — runs the packaged entry point
uvx blender-optics-mcp                      # once published to PyPI
uvx --from ./mcp blender-optics-mcp         # straight from this repo, no publish needed

# or install it
pipx install blender-optics-mcp             # (PyPI)  /  pipx install ./mcp   (from source)
pip install ./mcp && blender-optics-mcp     # into the current environment

# or just run the single file (needs `pip install "mcp[cli]"`)
OPTICS_BRIDGE_PORT=9765 python3 optics_mcp_server.py
```

Environment:
- `OPTICS_BRIDGE_PORT` — bridge port (default `9765`, must match the add-on preference).
- `OPTICS_BRIDGE_HOST` — default `127.0.0.1`.

## 3. Wire it into an MCP client

With the packaged entry point the client config is a single command — no absolute script path:

```json
{
  "mcpServers": {
    "blender-optics": {
      "command": "uvx",
      "args": ["blender-optics-mcp"],
      "env": { "OPTICS_BRIDGE_PORT": "9765" }
    }
  }
}
```

(`"command": "blender-optics-mcp"` works too once it's installed on your `PATH`; or, from a checkout,
`"command": "uvx", "args": ["--from", "/absolute/path/to/mcp", "blender-optics-mcp"]`.)

## Distribution (MCP Registry / PyPI)

This folder is a self-contained Python distribution:
- [`pyproject.toml`](pyproject.toml) — builds `blender-optics-mcp` (a single-module wheel; depends only
  on `mcp[cli]`). `python -m build` → publish to PyPI with `twine`.
- [`server.json`](server.json) — the [MCP Registry](https://github.com/modelcontextprotocol/registry)
  manifest (namespace `io.github.emircbngl/...`, PyPI package, stdio transport). Publish/validate it
  with the official `mcp-publisher` CLI (it authenticates via GitHub and checks the schema — confirm
  the `$schema` version it expects at submission time, as the registry schema evolves).

## Tools

The server mirrors the add-on's full `optics_api` surface — the bridge auto-derives its allow-list
from `optics_api`'s public functions, so every tool below maps 1:1 to a core API call.

| Tool | What it does |
|------|--------------|
| `get_state` | Full optical state: elements, ports (world pos + normal), mounts/DOFs, beam path, detector report |
| `build_example` | Build `mach_zehnder` / `michelson` / `hong_ou_mandel` / `bell` / `adaptive_optics` / `newton_rings` |
| `trace_beam` | Re-trace the beam path |
| `tag_element` | Mark an object as an optical element (set type) + auto-detect ports |
| `set_mount` | Apply a kinematic-mount preset to an element |
| `set_param` | Set an optical parameter (reflectivity, wavelength, pol_angle, …) |
| `align_element` / `align_all` | Auto-align one element / every element's knobs toward its target |
| `check_mechanics` | Report the worst opto-mechanical limit (post pull-out, cage-rod travel) |
| `add_component` | Spawn a catalog component (or its generic fallback) |
| `swap_part` | Replace an element's mesh from a file, keeping its optical slot |
| `place_relative` | Place an element relative to another (along an axis or its beam), optionally linked |
| `scan` | Sweep OPD / waveplate angle / wavelength → plot PNG + CSV |
| `ao_measure` / `get_wavefront` | Read a wavefront sensor's residual Zernike modes + RMS |
| `ao_command` | Set a deformable mirror's Zernike command (waves) |
| `ao_close_loop` | Close the adaptive-optics loop (sensor → deformable mirror) until the wavefront flattens |
| `bake_beams` / `clear_beams` | Bake the beam path into emission meshes / remove them |
| `render` | Configure or render the scene (EEVEE preview / Cycles final) |
| `export_svg` | Write a top-view SVG schematic of the layout + beam path (publication figures) |
| `beam_profile` | Spot radius w(z) along the beam path: waist, element positions, plot PNG + CSV |

## Notes

- The bridge dispatches every call onto Blender's main thread (bpy is not thread-safe), so
  tools are serialized and safe.
- An interactively-authenticated Blender session is required for live edits; the server
  itself is stateless and reconnects per call.
