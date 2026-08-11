"""Read-only path statistics over the tracer's flat parent-indexed segment tree.

The tracer already accumulates ``segment["opl"]`` to the segment endpoint.  This
module only exposes that stored quantity and reconstructs each route; it does not
introduce another propagation model.  The value is deliberately named
``phase_opl_mm``.  Group index, group delay and GDD are not represented by the
current tracer, so an ultrafast time-of-flight value must not be inferred from it.

No bpy import: the tree walk has a bare-interpreter self-test at the bottom.
"""
from __future__ import annotations

import math


def _segment_length(seg):
    p1, p2 = seg.get("p1"), seg.get("p2")
    if p1 is None or p2 is None or len(p1) != 3 or len(p2) != 3:
        return 0.0
    return math.sqrt(sum((float(p2[i]) - float(p1[i])) ** 2 for i in range(3)))


def _chain_indices(segments, leaf_index):
    """Return a root->leaf chain, stopping safely on malformed/cyclic parents."""
    chain = []
    seen = set()
    index = leaf_index
    while isinstance(index, int) and 0 <= index < len(segments) and index not in seen:
        seen.add(index)
        chain.append(index)
        index = segments[index].get("parent", -1)
    chain.reverse()
    return chain


def _route(segments, chain):
    names = []
    for index in chain:
        seg = segments[index]
        for name in (seg.get("from"), seg.get("to")):
            if name is not None and (not names or names[-1] != name):
                names.append(name)
    return names


def detector_path_statistics(segments, terminal_names):
    """Summarize every traced arrival at the requested terminal object names.

    Returns one row per terminal, including terminals with no arrival.  A detector
    can receive several branches/wavelengths, so each arrival stays separate rather
    than being collapsed into one misleading "total".
    """
    segments = list(segments or [])
    names = sorted({str(name) for name in (terminal_names or [])})
    rows = {name: [] for name in names}

    for leaf_index, seg in enumerate(segments):
        detector = seg.get("to")
        if detector not in rows:
            continue
        chain = _chain_indices(segments, leaf_index)
        route = _route(segments, chain)
        geometric = sum(_segment_length(segments[index]) for index in chain)
        phase_opl = float(seg.get("opl", geometric))
        rows[detector].append({
            "segment_index": leaf_index,
            "source": route[0] if route else None,
            "route": route,
            "wavelength_nm": round(float(seg.get("wavelength", 0.0)), 6),
            "power": float(seg.get("power", 0.0)),
            "geometric_length_mm": round(geometric, 6),
            "phase_opl_mm": round(phase_opl, 6),
        })

    detectors = []
    for name in names:
        arrivals = sorted(rows[name], key=lambda row: (row["phase_opl_mm"], row["segment_index"]))
        if arrivals:
            phase_values = [arrival["phase_opl_mm"] for arrival in arrivals]
            geometric_values = [arrival["geometric_length_mm"] for arrival in arrivals]
            phase_range = [min(phase_values), max(phase_values)]
            geometric_range = [min(geometric_values), max(geometric_values)]
        else:
            phase_range = geometric_range = None
        detectors.append({
            "detector": name,
            "arrival_count": len(arrivals),
            "phase_opl_range_mm": phase_range,
            "geometric_length_range_mm": geometric_range,
            "arrivals": arrivals,
        })

    return {
        "ok": True,
        "quantity": "phase optical path length",
        "units": "mm",
        "group_delay_available": False,
        "caveat": ("Phase OPL is the tracer's accumulated phase-index path. "
                   "Group index, group delay and GDD are not modeled."),
        "detectors": detectors,
    }


if __name__ == "__main__":
    _segs = [
        {"p1": (0, 0, 0), "p2": (10, 0, 0), "from": "Laser", "to": "Mirror",
         "parent": -1, "opl": 10.0, "wavelength": 800.0, "power": 1.0},
        {"p1": (10, 0, 0), "p2": (10, 12, 0), "from": "Mirror", "to": "Detector",
         "parent": 0, "opl": 25.0, "wavelength": 800.0, "power": 1.0},
    ]
    _out = detector_path_statistics(_segs, ["Detector", "DarkDetector"])
    _arrival = _out["detectors"][1]["arrivals"][0]
    assert _arrival["route"] == ["Laser", "Mirror", "Detector"]
    assert _arrival["geometric_length_mm"] == 22.0
    assert _arrival["phase_opl_mm"] == 25.0
    assert _out["detectors"][0]["arrival_count"] == 0
    assert _out["group_delay_available"] is False
    print("PATHSTATS SELFTEST PASSED")
