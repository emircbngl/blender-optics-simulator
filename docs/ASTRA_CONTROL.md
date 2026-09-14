# Agent control contract

This add-on is controllable through the same `optics_api` facade used by the MCP bridge. An
agent should call `capabilities()` once after connecting, then use this loop:

```text
get_state() -> inspect_beam()/inspect_element() -> choose an explicit write
set_param()/set_mount()/place_relative()/align_*() -> trace_beam()
-> get_state()/diagnose() -> accept, revise, or report the result
```

`get_state()`, `inspect_beam()`, `inspect_element()`, `diagnose()`, and
`propose_corrections()` are reads. `set_param`, `set_mount`, `place_relative`, and alignment
tools are writes. A correction proposal is advisory feedback; it is never applied implicitly.
The result should be checked with `trace_beam()` or `get_state()` after every write that changes
an optical property or pose.

Distance arguments use millimetres. Raw world positions and matrix translations use Blender world units; multiply them by `get_state()["coordinate_units"]["mm_per_world_unit"]`. Fields ending in `_mm` are physical millimetres. `get_state()` exposes each element's world pose, ports,
mount degrees of freedom, current parameters, and `editable_params` for its element type. This
is the authoritative control surface; the sidebar is a human view over the same state.

The bridge must run inside the open Blender process. Start it from **Optics → Present → Tools &
Integration**. The bridge listens only on localhost and exposes the curated `optics_api` surface.

For safe automation:

1. Never infer a port or beam path from a mesh screenshot when `get_state()` is available.
2. Treat `diagnose()` and `propose_corrections()` as reports. Compare each proposal with the
   intended experiment before applying a tool.
3. After a scene-unit change, a file load, or a keyed frame change, request a fresh state before
   acting. Reads must describe the current scene, not a previous trace cache.
4. Keep the mutation small: one write, one trace/readback, then the next decision.

The machine-readable version of this contract is returned by `capabilities()["control_contract"]`.
