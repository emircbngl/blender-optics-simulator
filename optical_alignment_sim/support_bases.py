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
  fork's slot reaches 26.8-58.3 mm from the pedestal's centre, turning freely around it -- which always
  contains a hole of a 25 mm grid (derived in the inventory, `cf125_reaches_any_hole`). The kit fixes a
  CF125 this way for the one optic it has to place freely.

One table screw per base, as the kit manual does (M6 x 16 + washer through a base slot; M6 x 12 +
washer through the fork). Footprints are kept apart; when nothing fits, the best fork is still placed
and the plan says `conflict: True` rather than pretending.
"""
import math

ON_GRID_MM = 0.05          # half the drawings' 0.1 mm resolution: "on a grid line" means within this
# A slot credits a hole when an M6 shank (6.0 mm major) fits across it there. The slots are 6.731 mm wide
# on BA2/M, BA1/M and CF125 alike (STEP models; ba2m_step_slot_width etc.), so the shank's centre may sit
# (6.731 - 6.0) / 2 off the slot's centreline.
SLOT_W = 6.731
SLOT_REACH = (SLOT_W - 6.0) / 2.0

# Seat = how far above the board the post's bottom ends up. Every base in this chain pushes a threaded
# tip up through PH50/M's 6.8 mm through-tapped floor, into TR50/M's M6 base hole, which opens in a 90 deg
# countersink (Ø6.016 at the face, TR50/M STEP model). On BE1/M the tip is known: its stud ends in a 45 deg
# chamfer, the two cones meet, and the post rests at one decided height. The cap screws' tips are not
# published, so on BA2/M and BA1/M the seat is an INTERVAL between the bore floor and the nominal tip;
# Dress Bench draws the post at the upper bound and records the whole range.
PH_FLOOR = 6.8             # PH50/M: 50 mm body, 43.2 mm bore (drawing 23132 rev B)
BA_THICKNESS = 10.0        # BA2/M 19227 rev A, BA1/M 19225 rev A
BE1_DISC = 4.7             # BE1/M 6790 rev C: Ø31.8 x 4.7 mm disc
BE1_STUD = 7.62            # BE1/M STEP: stud end face 7.62 above the disc (drawing: 12.3 - 4.7 = 7.6)
BE1_STUD_END_R = 2.7457    # BE1/M STEP: 45 deg x 0.254 mm end chamfer on the r 2.9997 stud
TR50_CSINK_R = 3.008       # TR50/M STEP: radius of the base hole's 90 deg countersink at the end face
SH6MS10 = 10.0             # the kit's base-to-holder screw (kit page Table 5.3; Table G10.1: 10 mm shank)
UNDER_HEAD = {'BA2/M': 3.142, 'BA1/M': 2.667}          # material under that screw's head (STEP models)


def seat_range(part):
    """(floor, nominal tip): where a post's bottom rests above the board on this base, on nominal
    dimensions. The upper end is not a bound: the cap screws' length tolerance is not published, so a
    long screw can stand higher. BE1/M's single point assumes TR50/M's base-hole countersink (TR50/M
    STEP model); other TR lengths are assumed to share it."""
    if part == 'BE1/M + CF125':
        # Two coaxial 45 deg cones: the stud's end enters the countersink by the radial gap between them.
        rest = BE1_DISC + BE1_STUD - (TR50_CSINK_R - BE1_STUD_END_R)          # 12.058 = floor + 0.558
        return (rest, rest)
    floor = BA_THICKNESS + PH_FLOOR                                              # 16.8
    tip = (BA_THICKNESS - UNDER_HEAD[part]) + SH6MS10                            # head bears there, shank up
    return (floor, max(floor, tip))                                              # BA2/M 16.858, BA1/M 17.333


SEAT_SLOTTED = seat_range('BA2/M')[1]
SEAT_PEDESTAL = seat_range('BE1/M + CF125')[1]

BA2 = {'part': 'BA2/M', 'length': 75.0, 'width': 50.0, 'slot_u': 25.0, 'slot_half': 15.9,
       'counterbores': (0.0, -12.5, 12.5)}
BA1 = {'part': 'BA1/M', 'length': 75.0, 'width': 25.0, 'slot_in': 17.4, 'slot_out': 37.5}
BE1 = {'part': 'BE1/M', 'disc': 31.8}
# Reach from the jaw centre: near slot end 73.8 - 43.2 - 3.8 = 26.8, far end 26.8 + 31.5 = 58.3 (drawing 6535
# rev E; the 43.2 runs from the near slot end to the fork's back end, not from the jaw).
CF125 = {'part': 'CF125', 'length': 73.8, 'width': 36.3, 'tip': 3.8, 'reach': (26.8, 58.3)}
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


def hull(points):
    """Convex hull of 2-D points (monotone chain), counter-clockwise. Used to turn an already-built part's
    footprint into an obstacle; a hull never under-covers the part."""
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


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
                       'holder_offset': offset, 'seat': seat_range('BA2/M')[1], 'seat_range': seat_range('BA2/M'),
                       'thickness': BA_THICKNESS,
                       'fastener': 'M6 x 16 mm cap screw + M6 washer',
                       'footprint': _rect(centre[0], centre[1], BA2['length'], BA2['width'], angle)}


def _on_segment(p, a, b):
    """Can an M6 screw in the slot from `a` to `b` (its centreline) reach grid hole `p`? Along the slot,
    anywhere between the end centres; across it, within the shank's play SLOT_REACH."""
    ax, ay = a; bx, by = b; px, py = p
    lx, ly = bx - ax, by - ay
    length = math.hypot(lx, ly)
    t = ((px - ax) * lx + (py - ay) * ly) / (length * length)
    if t < -1e-9 or t > 1.0 + 1e-9:
        return False
    return abs((px - ax) * ly - (py - ay) * lx) / length <= SLOT_REACH + 1e-9


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
               'holder_offset': 0.0, 'seat': seat_range('BA1/M')[1], 'seat_range': seat_range('BA1/M'),
               'thickness': BA_THICKNESS,
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
               'reach': r, 'holder_offset': 0.0, 'seat': SEAT_PEDESTAL,
               'seat_range': seat_range('BE1/M + CF125'), 'thickness': BE1_DISC,
               'fastener': 'M6 x 12 mm cap screw + M6 washer', 'footprint': footprint,
               'disc': _disc(x, y, BE1['disc'])}


SEARCH_BUDGET = 20000      # candidate trials before choose() stops looking for a conflict-free set


def _shapes(plan):
    return [plan['footprint']] + ([plan['disc']] if 'disc' in plan else [])


def choose(holders, grid, obstacles=()):
    """holders: {tag: (x, y)}. obstacles: footprints already standing on the board (rails, periscope
    forks), as convex polygons. Returns {tag: plan}. Deterministic: tags in sorted order, candidates in
    the kit's order of preference, each the first whose footprint clears every obstacle, every base
    already chosen and every other holder's body. Where a holder finds no room, the earlier choices are
    revisited (depth-first, same orders), so a holder is reported in conflict only when no set of bases
    fits them all -- or SEARCH_BUDGET trials did not find one."""
    bodies = {tag: _disc(x, y, HOLDER_D) for tag, (x, y) in holders.items()}
    fixed = [list(p) for p in obstacles if len(p) >= 3]
    tags = sorted(holders)
    options = {}
    for tag in tags:
        x, y = holders[tag]
        blocked = fixed + [poly for t, poly in bodies.items() if t != tag]
        options[tag] = [plan for plan in
                        list(_ba2_plans(x, y, grid)) + list(_ba1_plans(x, y, grid)) + list(_fork_plans(x, y, grid))
                        if not any(overlap(s, p) for s in _shapes(plan) for p in blocked)]
    budget = [SEARCH_BUDGET]

    def search(i, placed):
        # Where the first choice fits, this walks straight down and gives the one-pass answer.
        if i == len(tags):
            return {}
        for plan in options[tags[i]]:
            if budget[0] <= 0:
                return None
            budget[0] -= 1
            shapes = _shapes(plan)
            if any(overlap(s, p) for s in shapes for p in placed):
                continue
            rest = search(i + 1, placed + shapes)
            if rest is not None:
                rest[tags[i]] = dict(plan, conflict=False)
                return rest
        return None

    found = search(0, [])
    if found is not None:
        return found
    # No set fits: one pass, and a holder with no room says so rather than pretending.
    placed, plans = list(fixed), {}
    for tag in tags:
        x, y = holders[tag]
        chosen = next((dict(plan, conflict=False) for plan in options[tag]
                       if not any(overlap(s, p) for s in _shapes(plan) for p in placed)), None)
        if chosen is None:
            first = next(iter(_fork_plans(x, y, grid)), None)
            chosen = dict(first, conflict=True) if first else {'part': None, 'conflict': True}
        plans[tag] = chosen
        if chosen.get('footprint'):
            placed.append(chosen['footprint'])
        if chosen.get('disc'):
            placed.append(chosen['disc'])          # the disc reaches 12 mm behind the fork's tips
    return plans
