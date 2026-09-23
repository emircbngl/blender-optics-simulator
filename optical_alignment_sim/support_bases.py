"""Stage 05b: which real base goes under each post holder, and where its table screw goes.

Pure Python, no bpy: optomech builds the geometry from what this decides. Every dimension comes from a
Thorlabs drawing recorded in docs/mechanics/product-evidence.json; what a drawing does not dimension is
not used to decide anything.

The choice follows the EDU-SPEB2/M kit the chain was taken from:

* **BA2/M** (75 x 50 x 10 mm) where a grid line allows it. Its two slots are 50 mm apart and run 31.8 mm
  between end centres (9.1 mm in from each edge); the holder takes one of three counterbores 12.5 mm
  apart. A slot's WIDTH is not dimensioned, so a slot is only credited with reaching a hole that lies on
  its centreline -- the holder has to stand on a grid line across the slots.
* **BA1/M** (75 x 25 x 10 mm) where BA2/M would collide. Holder at the centre; its two slots are open at
  the ends and run in to 20.1 mm from each end. Same rule: only on a grid line.
* **BE1/M + CF125** everywhere else. The pedestal disc (Ø31.8 x 4.7 mm) sits under the holder and the
  fork's slot reaches 11.7-43.2 mm from the pedestal's centre, turning freely around it -- which always
  contains a hole of a 25 mm grid (derived in the inventory, `cf125_reaches_any_hole`). The kit fixes a
  CF125 this way for the one optic it has to place freely.

One table screw per base, as the kit manual does (M6 x 16 + washer through a base slot; M6 x 12 +
washer through the fork). Footprints are kept apart; when nothing fits, the best fork is still placed
and the plan says `conflict: True` rather than pretending.
"""
import math

ON_GRID_MM = 0.05          # half the drawings' 0.1 mm resolution: "on a grid line" means within this

# Seat = how far above the board the post's bottom ends up.
PH_FLOOR = 6.8             # PH50/M: 50 mm body, 43.2 mm bore (drawing 23132 rev B)
BA_THICKNESS = 10.0        # BA2/M 19227 rev A, BA1/M 19225 rev A
BE1_DISC = 4.7             # BE1/M 6790 rev C: Ø31.8 x 4.7 mm disc
BE1_STUD = 7.6             # 12.3 overall - 4.7 disc; 0.8 mm longer than PH50/M's floor
SEAT_SLOTTED = BA_THICKNESS + PH_FLOOR                 # 16.8: the post stands on the bore floor
SEAT_PEDESTAL = BE1_DISC + BE1_STUD                    # 12.3: the post stands on the stud's tip

BA2 = {'part': 'BA2/M', 'length': 75.0, 'width': 50.0, 'slot_u': 25.0, 'slot_half': 15.9,
       'counterbores': (0.0, -12.5, 12.5)}
BA1 = {'part': 'BA1/M', 'length': 75.0, 'width': 25.0, 'slot_in': 17.4, 'slot_out': 37.5}
BE1 = {'part': 'BE1/M', 'disc': 31.8}
CF125 = {'part': 'CF125', 'length': 73.8, 'width': 36.3, 'tip': 3.8, 'reach': (11.7, 43.2)}
HOLDER_D = 25.0            # PH50/M body


def on_line(value, origin, pitch):
    k = round((value - origin) / pitch)
    return abs(value - (origin + k * pitch)) <= ON_GRID_MM


def holes(grid):
    x0, y0, nx, ny, pitch = grid
    for i in range(nx):
        for j in range(ny):
            yield (x0 + i * pitch, y0 + j * pitch)


def _rect(cx, cy, length, width, angle):
    """Corners of a length x width rectangle centred at (cx, cy), its length along `angle` (radians)."""
    c, s = math.cos(angle), math.sin(angle)
    hl, hw = length / 2.0, width / 2.0
    return [(cx + c * u - s * v, cy + s * u + c * v) for u, v in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw))]


def _disc(cx, cy, d):
    """A disc as a 16-gon that encloses it, so an overlap test on it never misses a real overlap."""
    r = d / 2.0 / math.cos(math.pi / 16)
    return [(cx + r * math.cos(2 * math.pi * k / 16), cy + r * math.sin(2 * math.pi * k / 16)) for k in range(16)]


def overlap(a, b, clearance=0.0):
    """Separating-axis test for two convex polygons; `clearance` shrinks nothing and invents nothing --
    touching counts as apart only when the gap is at least `clearance` (0 by default)."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
            ax, ay = y1 - y2, x2 - x1
            norm = math.hypot(ax, ay)
            if norm == 0.0:
                continue
            ax, ay = ax / norm, ay / norm
            pa = [x * ax + y * ay for x, y in a]
            pb = [x * ax + y * ay for x, y in b]
            if max(pa) + clearance <= min(pb) or max(pb) + clearance <= min(pa):
                return False
    return True


def to_world(centre, angle, u, v):
    """Base-local (u along the length, v across it) to world, for a base turned by `angle` radians."""
    c, s = math.cos(angle), math.sin(angle)
    return (centre[0] + c * u - s * v, centre[1] + s * u + c * v)


def to_local(centre, angle, x, y):
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = x - centre[0], y - centre[1]
    return (c * dx + s * dy, -s * dx + c * dy)


def _ba2_plans(x, y, grid):
    x0, y0, _nx, _ny, pitch = grid
    for angle in (0.0, math.pi / 2):
        for offset in BA2['counterbores']:
            # The holder stands on the counterbore at local (0, offset); that fixes the base's centre.
            ox, oy = to_world((0.0, 0.0), angle, 0.0, offset)
            centre = (x - ox, y - oy)
            for side in (-1.0, 1.0):
                # The slot's centreline runs along v at u = side * 25, from v = -15.9 to +15.9.
                a = to_world(centre, angle, side * BA2['slot_u'], -BA2['slot_half'])
                b = to_world(centre, angle, side * BA2['slot_u'], BA2['slot_half'])
                hits = [h for h in holes(grid)
                        if _on_segment(h, a, b)]
                if not hits:
                    continue
                hit = min(hits, key=lambda h: (abs(to_local(centre, angle, *h)[1]), h))
                yield {'part': 'BA2/M', 'angle_deg': math.degrees(angle), 'centre': centre, 'screw': hit,
                       'holder_offset': offset, 'seat': SEAT_SLOTTED, 'thickness': BA_THICKNESS,
                       'fastener': 'M6 x 16 mm cap screw + M6 washer',
                       'footprint': _rect(centre[0], centre[1], BA2['length'], BA2['width'], angle)}


def _on_segment(p, a, b):
    """Is grid hole `p` on the straight slot centreline from `a` to `b` (within ON_GRID_MM)? A slot's
    width is not dimensioned, so only its centreline is credited."""
    ax, ay = a; bx, by = b; px, py = p
    lx, ly = bx - ax, by - ay
    length = math.hypot(lx, ly)
    t = ((px - ax) * lx + (py - ay) * ly) / (length * length)
    if t < -1e-9 or t > 1.0 + 1e-9:
        return False
    return abs((px - ax) * ly - (py - ay) * lx) / length <= ON_GRID_MM


def _ba1_plans(x, y, grid):
    for angle in (0.0, math.pi / 2):
        centre = (x, y)                                  # the holder stands on BA1/M's centre hole
        hits = []
        for side in (-1.0, 1.0):
            a = to_world(centre, angle, side * BA1['slot_in'], 0.0)
            b = to_world(centre, angle, side * BA1['slot_out'], 0.0)
            hits += [h for h in holes(grid) if _on_segment(h, a, b)]
        if not hits:
            continue
        hit = min(hits, key=lambda h: (abs(to_local(centre, angle, *h)[0]), h))   # deepest: most washer support
        yield {'part': 'BA1/M', 'angle_deg': math.degrees(angle), 'centre': centre, 'screw': hit,
               'holder_offset': 0.0, 'seat': SEAT_SLOTTED, 'thickness': BA_THICKNESS,
               'fastener': 'M6 x 16 mm cap screw + M6 washer',
               'footprint': _rect(x, y, BA1['length'], BA1['width'], angle)}


def _fork_plans(x, y, grid):
    lo, hi = CF125['reach']
    x0, y0, nx, ny, pitch = grid
    options = []
    for hx, hy in holes(grid):
        r = math.hypot(hx - x, hy - y)
        if lo - 1e-9 <= r <= hi + 1e-9:
            options.append((r, math.atan2(hy - y, hx - x) % (2 * math.pi), hx, hy))
    for r, angle, hx, hy in sorted(options):
        # The fork runs from 3.8 mm behind the pedestal's centre (its tips) to 70.0 mm ahead of it.
        mid = (CF125['length'] / 2.0) - CF125['tip']
        cx, cy = x + math.cos(angle) * mid, y + math.sin(angle) * mid
        footprint = _rect(cx, cy, CF125['length'], CF125['width'], angle)
        yield {'part': 'BE1/M + CF125', 'angle_deg': math.degrees(angle), 'centre': (x, y), 'screw': (hx, hy),
               'reach': r, 'holder_offset': 0.0, 'seat': SEAT_PEDESTAL, 'thickness': BE1_DISC,
               'fastener': 'M6 x 12 mm cap screw + M6 washer', 'footprint': footprint,
               'disc': _disc(x, y, BE1['disc'])}


def choose(holders, grid):
    """holders: {tag: (x, y)}. Returns {tag: plan}. Deterministic: tags in sorted order, candidates in
    the kit's order of preference, the first whose footprint clears everything already placed and every
    other holder's body."""
    bodies = {tag: _disc(x, y, HOLDER_D) for tag, (x, y) in holders.items()}
    placed, plans = [], {}
    for tag in sorted(holders):
        x, y = holders[tag]
        others = [poly for t, poly in bodies.items() if t != tag]
        chosen = None
        for plan in list(_ba2_plans(x, y, grid)) + list(_ba1_plans(x, y, grid)) + list(_fork_plans(x, y, grid)):
            shapes = [plan['footprint']] + ([plan['disc']] if 'disc' in plan else [])
            if any(overlap(s, p) for s in shapes for p in placed + others):
                continue
            chosen = dict(plan, conflict=False)
            break
        if chosen is None:
            first = next(iter(_fork_plans(x, y, grid)), None)
            chosen = dict(first, conflict=True) if first else {'part': None, 'conflict': True}
        plans[tag] = chosen
        if chosen.get('footprint'):
            placed.append(chosen['footprint'])
        if chosen.get('disc'):
            placed.append(chosen['disc'])          # the disc reaches 12 mm behind the fork's tips
    return plans
