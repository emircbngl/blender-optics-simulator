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

try:
    from . import physics
except ImportError:                     # bare-interpreter self-test: python3 optical_alignment_sim/pathstats.py
    import physics

# Element types whose glass the trace does not follow: a beam that goes THROUGH one has an unmodelled delay and
# GDD unless the element's dispersion is set by hand. A reflection off the front face (REFLECT, GHOST) crosses no
# glass. A cube beamsplitter's reflection happens inside the cube, so any continuation counts for it.
THIN_DISPERSIVE = ('LENS', 'WAVEPLATE', 'POLARIZER', 'FILTER', 'ATTENUATOR', 'ISOLATOR', 'CIRCULATOR', 'PASSTHROUGH',
                   'CAVITY', 'OBJECTIVE', 'CRYSTAL', 'AOM', 'BEAMSPLITTER', 'DICHROIC', 'OPA')
_FRONT_FACE_KINDS = ('REFLECT', 'GHOST')


def _segment_length(seg):
    """Physical length in mm. The tracer stores it as ``length_mm``; p1/p2 are WORLD units, which differ from
    millimetres in a scene that declares its unit scale, so they are only the fallback for hand-built lists."""
    if seg.get("length_mm") is not None:
        return float(seg["length_mm"])
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


def _with_glass_legs(segments, chain):
    """The chain plus each element's traced in-glass legs. The tracer records a prism's or a polished mirror
    substrate's glass legs as children of the arriving segment, beside the ray that leaves the element, so they
    are not on the parent chain; they belong to the route wherever the next chain segment leaves that element."""
    legs_of = {}
    for i, seg in enumerate(segments):
        if seg.get("kind") == "GLASS":
            legs_of.setdefault(seg.get("parent"), []).append(i)
    out = []
    for pos, index in enumerate(chain):
        if segments[index].get("kind") == "GLASS":
            continue                                   # counted with its arrival below
        out.append(index)
        if pos + 1 < len(chain):
            name = segments[index].get("to")
            out.extend(i for i in legs_of.get(index, ()) if segments[i].get("to") == name)
    return out


def _route(segments, chain):
    names = []
    for index in chain:
        seg = segments[index]
        for name in (seg.get("from"), seg.get("to")):
            if name is not None and (not names or names[-1] != name):
                names.append(name)
    return names


def elements_from_objects(objects):
    """{name: {type, dispersion_mode, group_delay_fs, gdd_fs2}} for the optical objects given (duck-typed, so this
    module stays free of bpy)."""
    out = {}
    for obj in objects:
        props = getattr(obj, "optics", None)
        if props is None or not getattr(props, "is_optical", False):
            continue
        out[obj.name] = {"type": props.element_type,
                         "dispersion_mode": getattr(props, "dispersion_mode", 'AUTO'),
                         "group_delay_fs": getattr(props, "user_group_delay_fs", 0.0),
                         "gdd_fs2": getattr(props, "user_gdd_fs2", 0.0)}
    return out


def _dispersion(segments, chain, elements):
    """Group delay (fs) and GDD (fs^2) along one root->leaf chain.

    Free-space segments travel at c (the group index of air is taken as 1, as the phase OPL takes its index as
    1). A traced glass leg (kind GLASS) with a Sellmeier glass contributes L n_g / c and GVD(lambda) L at the
    leg's own wavelength. An element set to USER dispersion adds its hand-set values once per pass. Returns
    (group_delay_fs, gdd_fs2, missing, notes): ``missing`` names what the delay cannot account for, so a
    number with a non-empty ``missing`` is a lower bound on nothing and must not be read as the delay."""
    gd = 0.0
    gdd = 0.0
    missing = []
    notes = []
    elements = elements or {}
    route = _with_glass_legs(segments, chain)
    for pos, index in enumerate(route):
        seg = segments[index]
        length = _segment_length(seg)
        wl = float(seg.get("wavelength", 0.0) or 0.0)
        if seg.get("kind") == "GLASS":
            glass = seg.get("glass")
            if glass is None:
                label = "%s (fixed refractive index, no dispersion model)" % seg.get("to")
                if label not in missing:
                    missing.append(label)
                continue
            n_g = physics.group_index(wl, glass) if wl > 0.0 else None
            gvd = physics.gvd_fs2_per_mm(wl, glass) if wl > 0.0 else None
            if n_g is None or gvd is None:
                label = "%s (%s has no index at %g nm)" % (seg.get("to"), glass, wl)
                if label not in missing:
                    missing.append(label)
                continue
            if not physics.sellmeier_in_range(wl, glass):
                note = "%s: %s extrapolated outside its Sellmeier window at %g nm" % (seg.get("to"), glass, wl)
                if note not in notes:
                    notes.append(note)
            gd += physics.group_delay_fs(length, n_g)
            gdd += gvd * length
        else:
            gd += physics.group_delay_fs(length, 1.0)
        # the element this segment arrives at, and how the beam leaves it
        name = seg.get("to")
        info = elements.get(name)
        if info is None or pos + 1 >= len(route):
            continue
        nxt = segments[route[pos + 1]]
        if info.get("dispersion_mode") == 'USER':
            gd += float(info.get("group_delay_fs", 0.0))
            gdd += float(info.get("gdd_fs2", 0.0))
            continue
        if nxt.get("kind") == "GLASS" and nxt.get("to") == name:
            continue                            # the element's own traced glass legs follow; they are counted there
        passes = nxt.get("kind") not in _FRONT_FACE_KINDS or info.get("type") == 'BEAMSPLITTER'
        if info.get("type") in THIN_DISPERSIVE and passes and name not in missing:
            missing.append(name)
    return gd, gdd, missing, notes


def detector_path_statistics(segments, terminal_names, elements=None):
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
        geometric = sum(_segment_length(segments[index]) for index in _with_glass_legs(segments, chain))
        phase_opl = float(seg.get("opl", geometric))
        gd, gdd, missing, notes = _dispersion(segments, chain, elements)
        complete = elements is not None and not missing
        rows[detector].append({
            "segment_index": leaf_index,
            "source": route[0] if route else None,
            "route": route,
            "wavelength_nm": round(float(seg.get("wavelength", 0.0)), 6),
            "power": float(seg.get("power", 0.0)),
            "geometric_length_mm": round(geometric, 6),
            "phase_opl_mm": round(phase_opl, 6),
            # None unless every glass and element on the route is accounted for
            "group_delay_fs": round(gd, 3) if complete else None,
            "gdd_fs2": round(gdd, 3) if complete else None,
            "dispersion_missing": missing if elements is not None else ["element data not given"],
            "dispersion_notes": notes,
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

    all_arrivals = [a for d in detectors for a in d["arrivals"]]
    return {
        "ok": True,
        "quantity": "phase optical path length; group delay and GDD where every part of the route is modelled",
        "units": "mm (lengths), fs (group delay), fs^2 (GDD)",
        "group_delay_available": bool(all_arrivals) and all(a["group_delay_fs"] is not None for a in all_arrivals),
        "caveat": ("Phase OPL is the tracer's accumulated phase-index path. Group delay and GDD come from the "
                   "Sellmeier glass of each traced glass leg (air at group index 1) plus any element whose "
                   "dispersion is set by hand. A thin lens, window, crystal or other element the trace does not "
                   "follow through glass leaves an arrival's group delay as None and is named in "
                   "dispersion_missing. Material dispersion only: no angular dispersion or geometric "
                   "prism-pair/grating-pair GDD is included."),
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
    assert _out["group_delay_available"] is False              # no element data given
    assert _arrival["group_delay_fs"] is None

    # air only: 22 mm at c; with element data given the route is complete
    _els = {"Mirror": {"type": "MIRROR", "dispersion_mode": "AUTO"}}
    _out = detector_path_statistics(_segs, ["Detector"], _els)
    _arr = _out["detectors"][0]["arrivals"][0]
    assert _out["group_delay_available"] is True
    assert abs(_arr["group_delay_fs"] - 22.0 / physics.C_MM_PER_FS) < 1e-2, _arr
    assert _arr["gdd_fs2"] == 0.0

    # 10 mm of fused silica at 800 nm between two air legs
    # as the tracer records it: the glass leg and the exit ray are both children of the arriving segment
    _g = [
        {"p1": (0, 0, 0), "p2": (5, 0, 0), "from": "L", "to": "P", "kind": "TRANSMIT", "parent": -1,
         "wavelength": 800.0, "opl": 5.0, "length_mm": 5.0},
        {"p1": (5, 0, 0), "p2": (15, 0, 0), "from": "L", "to": "P", "kind": "GLASS", "parent": 0,
         "wavelength": 800.0, "glass": "FUSED_SILICA", "opl": 19.5, "length_mm": 10.0},
        {"p1": (15, 0, 0), "p2": (20, 0, 0), "from": "P", "to": "D", "kind": "TRANSMIT", "parent": 0,
         "wavelength": 800.0, "opl": 24.5, "length_mm": 5.0},
    ]
    _a = detector_path_statistics(_g, ["D"], {"P": {"type": "PRISM", "dispersion_mode": "AUTO"}})["detectors"][0]["arrivals"][0]
    _want = (10.0 + 10.0 * physics.group_index(800.0, "FUSED_SILICA")) / physics.C_MM_PER_FS
    assert abs(_a["group_delay_fs"] - _want) < 1e-2, (_a, _want)
    assert abs(_a["gdd_fs2"] - 10.0 * physics.gvd_fs2_per_mm(800.0, "FUSED_SILICA")) < 1e-2, _a
    assert _a["geometric_length_mm"] == 20.0, _a                    # the glass leg counts toward the route

    # a thin lens on the route: incomplete, named; set by hand: complete and added once
    _l = [dict(_segs[0], to="Lens"), dict(_segs[1], **{"from": "Lens", "kind": "TRANSMIT"})]
    _a = detector_path_statistics(_l, ["Detector"], {"Lens": {"type": "LENS", "dispersion_mode": "AUTO"}})
    assert _a["group_delay_available"] is False and _a["detectors"][0]["arrivals"][0]["dispersion_missing"] == ["Lens"]
    _a = detector_path_statistics(_l, ["Detector"], {"Lens": {"type": "LENS", "dispersion_mode": "USER",
                                                             "group_delay_fs": 100.0, "gdd_fs2": 250.0}})
    _r = _a["detectors"][0]["arrivals"][0]
    assert _a["group_delay_available"] and abs(_r["group_delay_fs"] - (22.0 / physics.C_MM_PER_FS + 100.0)) < 1e-2
    assert _r["gdd_fs2"] == 250.0
    # a fold off a lens's front face (REFLECT) crosses no glass
    _l[1]["kind"] = "REFLECT"
    assert detector_path_statistics(_l, ["Detector"], {"Lens": {"type": "LENS"}})["group_delay_available"] is True
    print("PATHSTATS SELFTEST PASSED")
