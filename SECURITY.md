# Security Policy

## Supported versions

Security fixes land on the latest release. Please always run the newest version — the add-on
auto-updates (see "Install & stay updated" in the README).

| Version | Supported |
| ------- | --------- |
| latest release | ✅ |
| older releases | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's **[Security Advisories](https://github.com/emircbngl/blender-optics-simulator/security/advisories/new)**
("Report a vulnerability"), or by email to **emircbngl@gmail.com**. Please include:

- a description of the issue and its impact,
- steps to reproduce (a minimal `.blend` or script if possible),
- the add-on version and your Blender version.

You can expect an acknowledgement within a few days. Once a fix is available it will ship in a
release and be credited (unless you prefer to remain anonymous).

## Scope notes

This is a Blender add-on and an MCP server. The most relevant surfaces are:

- **The MCP server** (`mcp/optics_mcp_server.py`) — it bridges an AI agent to a running Blender.
  Only run it against a Blender instance you control, and be mindful that any client you connect can
  drive the scene.
- **`swap_part` / mesh import** — importing untrusted STL/OBJ/STEP files runs mesh code; treat
  third-party mesh files as you would any untrusted input.
- The add-on executes only local `bpy`/NumPy code; it does not phone home except the once-a-day
  update check against the project's own GitHub-Pages `index.json`.
