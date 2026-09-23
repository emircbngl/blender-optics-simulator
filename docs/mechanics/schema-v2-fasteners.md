# Schema v2 design note: fastened joints

**Status: design only. No code, no schema change yet.** Owner decision 2026-09-23: add a fastened-joint
type in schema v2, design note first. This note is the thing to review before any of it is built.

## The problem, stated with the real chain

Schema v1 joins **two interfaces**. A screw joint joins **three or more parts**:

```
   M6 x 10 cap screw          head seats on BA2/M's counterbore floor
        │                     shank passes THROUGH that floor
   ┌────┴────┐  BA2/M         thread engages PH50/M's M6 tap, which runs THROUGH a 6.8 mm floor
   └────┬────┘                into the bore where the post stands
   ┌────┴────┐  PH50/M
```

How far the screw engages is not a property of any one part:

    engagement = screw length − Σ thickness of everything it clamps

In v1 the only place to put a screw's reach is `engagement_max` on its thread, which can only hold the
**whole length**. Stage 03 then compares 10 mm with PH50/M's 6.8 mm tap and says *bottoms out* — a
false `incompatible` for the vendor's own procedure. Today that pairing is avoided in the tests rather
than answered. That is the gap this closes.

## What v2 adds

### 1. Dimensions

| Dimension | On | Meaning |
|---|---|---|
| `length` | screw | length under the head, the ISO convention for cap screws |
| `head_diameter`, `head_height` | screw | what has to fit a counterbore |
| `grip` | a clamped interface | material the shank passes through at this interface (a counterbore floor, a slot's plate, a washer) |
| `clearance_diameter` | a clamped interface | the hole or slot width the shank must pass |

Every one of them is a v1-style quantity: value or `null`, unit, evidence, no invented tolerance.

### 2. Interface kinds

`counterbore` (a head seat plus a clearance through its floor), `clearance` (a plain through hole or
slot), `head` (a screw's under-head face). `thread`, `smooth_bore` and the rest are unchanged.

### 3. A joint type in the assembly graph

```
fastener: {
  id, screw: instance_id,
  head_on:  (instance_id, interface)         # a counterbore, or a clearance with a washer under the head
  through: [(instance_id, interface), ...]   # every clamped layer, in order from the head
  into:     (instance_id, interface)         # the tap
  carries:  None | instance_id | 'none'      # which clamped part rides which, as for stage 04a joints
  state:    aligned | seated | fastened | locked
}
```

A fastener occupies every socket it names — one counterbore, one screw. The screw carries no pose of
its own. **Which part carries which is not implied by where the head and the thread are**: base →
holder has the head in the base and the thread in the holder, and the base carries the holder; base →
table has the head on the base and the thread in the *table*, and the table must not ride the base. So
`carries` is explicit, with stage 04a's semantics: None lets the ownership forest decide, a named part
is refused if it would mean a second parent or a cycle, `'none'` records a physical joint only.

## The rule

With `L` = screw length, `g_i` = each layer's grip, `d` = tap depth:

| Check | Verdict |
|---|---|
| the shank passes every layer: `clearance_diameter_i ≥ major diameter` | incompatible if not |
| the head fits the counterbore: `head_diameter ≤ counterbore diameter` | incompatible if not |
| thread: stage 03's thread rule, unchanged (standard, hand, form, diameter, pitch) | as today |
| does not bottom out: `L − Σ g_i ≤ d` | incompatible if not |
| engages enough: `L − Σ g_i ≥ engagement_min` of the tap | incompatible if not |

**Missing values are never a pass.** Any `null` makes the check it feeds `unknown` and names the field,
exactly as in stage 03.

### Bounds, not just values

The chain already has a value that is only a bound: BA2/M's counterbore floor is not dimensioned, but
the vendor's procedure implies it is **at least 3.2 mm** (`ba2m_counterbore_floor_min`). v2 lets a
quantity carry `minimum` / `maximum` instead of a value, and the rule does interval arithmetic:

    engagement ≤ 10 − 3.2 = 6.8 ≤ 6.8 (tap depth)   →  does not bottom out: compatible
    engagement ≥ ?  (no upper bound on the floor)    →  engages enough: unknown, `grip` named

That is the honest answer for the real base joint today: provably not bottoming, not provably enough
thread. No midpoint is ever taken.

## Migration

- Records: `schema_version: 2`. Every v1 record is a valid v2 record; nothing in it changes meaning.
  Reading a v1 record never rewrites it. `migrate(record)` is an **explicit** operation that only bumps
  the version and reports what it touched (nothing, for v1 content). v1 code refuses v2 records, as
  schema v1 already refuses unknown versions.
- Graph: `GRAPH_VERSION 2` adds a `fasteners` list next to `joints`. A v1 graph reads as v2 with no
  fasteners. The same one-string, one-write atomicity holds.
- Existing tests keep their v1 fixtures and must pass unchanged — that is the witness that v1 meaning
  did not move.

## What stays out

Torque, preload, friction, thread stripping, washer compression, head-to-counterbore concentricity.
None of them is sourced for any part here, and a fastened joint is a geometric claim, not a strength
claim.

## What it will not close by itself

Even with v2, the chain's screw joints stay partly `unknown` until these are sourced: the BA2/M
counterbore depth (drawing 19227 does not give it), the kit screws' head dimensions and washer
thickness (the kit manual gives sizes only), and MB4560/M's tap depth (drawing 6282 gives neither a
depth nor THRU). v2 makes those gaps **named** instead of producing a false verdict.

## Test plan (for the implementing PR)

1. The base joint as the vendor assembles it: M6 × 10 through BA2/M into PH50/M → *does not bottom
   out* from the 3.2 mm bound; *engages enough* unknown, `grip` named. The v1 answer (*bottoms out*)
   is the witness that fails on today's code.
2. A screw that is too long for the same stack is incompatible on bottoming.
3. A shank wider than a clearance, and a head wider than a counterbore, are incompatible.
4. A missing grip, length or depth is `unknown` and named — never a pass.
5. A fastener's sockets are occupied; a second screw in the same counterbore is refused.
6. v1 records and graphs load unchanged; `migrate` is explicit and reports; v1 suites pass as-is.
7. Save/reload, dry_run and one-write atomicity for fastener joints, as for stage 04 joints.
