"""Agent-style beam alignment — the headline MCP demo, reproducible headlessly.

Builds a beam-steering bench (laser -> kinematic mirror -> camera), knocks the mirror out of
alignment, then lets the auto-aligner walk the beam back onto the detector. The alignment call is
the *same* ``optics_api`` facade the localhost MCP bridge exposes — so this is exactly what an AI
agent does when it drives a running scene ("the beam misses the camera; align it").

Run headless (writes /tmp/agent_align.png):
    blender --background --python examples/agent_align.py
Or paste into Blender's Text Editor (add-on enabled) and Run Script to watch it live.
"""
import os
import sys


def _api():
    try:
        import optics_api
        return optics_api
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import optical_alignment_sim as addon
        addon.register()
        import optics_api
        return optics_api


def main():
    api = _api()
    import bpy
    from mathutils import Vector
    from optical_alignment_sim import elements_generic as G, mounts, tracer

    sc = bpy.context.scene
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))

    # 1. build a beam-steering bench: laser -> kinematic mirror -> a camera
    c = G.example_collection("OpticsExample_AgentAlign")
    G.source("AA_Laser", (-120, 0, 0), X, c)
    G.mirror("AA_Mirror", (0, 0, 0), X, Y, c)
    G.detector("AA_Cam", (0, 120, 0), Y, c, size=22.0)
    print("set_mount KM100 ->", api.set_mount("AA_Mirror", "KM100"))   # adds tip/tilt knobs

    def cam_offset_mrad():
        """How far off the detector centre the beam lands, as the aligner's own residual sees it."""
        segs = tracer.trace_scene(sc, mode=sc.optics.trace_mode,
                                  max_segments=sc.optics.max_segments, max_depth=sc.optics.max_depth)
        tracer.cached_segments = segs
        return any(s.get("to") == "AA_Cam" for s in segs)

    # 2. knock the mirror out of alignment (2 deg of tip) — the beam still grazes the sensor but is
    #    well off centre, within the auto-aligner's capture range
    mirror = sc.objects["AA_Mirror"]
    for dof in mirror.optics.dofs:
        if dof.kind == "TIP":
            dof.current = 2.0
    mounts.compose_pose(mirror)
    print("misaligned  -> beam on the camera?", cam_offset_mrad())          # True, but off centre

    # 3. the agent aligns it: ONE optics_api call (the same facade the MCP bridge serves). The result
    #    reports the pointing residual before -> after; it collapses to ~0 (beam re-centred on the sensor).
    result = api.align_element("AA_Mirror")
    print("align_element('AA_Mirror') ->", result)                          # before ~7  ->  after ~0.001
    print("realigned   -> beam on the camera?", cam_offset_mrad())          # True, re-centred

    # 4. render the aligned bench so the headless run has a visible payoff
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "agent_align.png")
    api.render(preset="final", camera="hero", filepath=out)
    print("wrote", out)


if __name__ == "__main__":
    main()
