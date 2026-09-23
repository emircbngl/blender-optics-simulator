# Mechanical assembly graph (stage 04)

Stage 04a records **how parts are joined** — which interfaces mate, what state each joint is in, what
carries what, and in which order a part comes off. Stage 04b adds **where a seated part goes**: seating
a joint places the carried part from the two declared frames and parents it, so the whole sub-assembly
rides its support.

What is still not claimed: `capabilities()` keeps reporting `mechanical_assembly.available: false`. A
placement is only as good as the frames in the record, the evidence levels are untouched, and nothing
here checks collision, tool access, torque or load.

Manual assembly is off by default. `enable_manual_assembly(True)` turns writing on for the scene; with
it off the assembly calls refuse to write, and the optical bench, Dress Bench and renders behave exactly
as before. Turning it back off does not delete a graph that was already recorded.

## Two graphs, on purpose

| | |
|---|---|
| **Physical graph** | Every joint. It may fork, bind one part at several points, and close a loop — four cage rods through two plates do exactly that. Loops are recorded and reported in `loops`. |
| **Transform-ownership forest** | The subset of joints that carry a part's pose. One parent per part, no cycles, enforced on every write. |

`carries` decides which of the two a joint belongs to:

- `None` (default) — the part named second is mounted onto the part named first when that is possible.
  When it is not (the part already has a parent, or the proposed parent sits inside its own
  sub-assembly), the joint is still recorded, as a physical joint that carries no pose, and the answer
  says why.
- `'a'` / `'b'` — that side must be carried. Refused with the reason if it would mean a second parent or
  a cycle; the refusal names `carries='none'` as the alternative.
- `'none'` — record the joint without carrying a pose.

## The gate: only a compatible verdict becomes a joint

A joint is a claim that two interfaces mate, so `join_parts` runs the stage-03 check first and refuses
anything else, with the verdict, the missing fields and what to do instead:

| Verdict | What happens |
|---|---|
| `compatible` | The joint is created at state `aligned`, carrying the source ids the verdict rested on. |
| `adapter_required` | Refused, with the chain: insert the adapter as its own two joints. |
| `unknown` | Refused, and `missing` names the field. A pairing schema v1 has no rule for is `unknown`, not `incompatible`. |
| `incompatible` | Refused. |

Also refused: a part joined to itself, a socket that already holds a joint (one interface, one joint), a
part whose `instance_id` is shared with another object (a duplicated Blender object copies the record,
and the graph addresses parts by `instance_id`), and any object in the `BENCH_` namespace — Dress Bench
owns those and rebuilds them, and `optomech.strip()` deletes anything named that way.

## States

`aligned` → `seated` → `fastened` → `locked`, and one step back at a time. Skipping a state is refused,
so the order a part goes on and comes off is always explicit. `locked` additionally requires one of the
two interfaces to declare a `lock.kind`; without that the data does not support the state.

`separate_parts` only takes apart an `aligned` joint. Anything else is refused with the next step back,
and the record is removed without deleting the object or its mechanical record.

## What a joint holds

`permitted_motions(part)` judges each declared mechanical motion by the joint on its interface:

| Joint state | The interface's own motion |
|---|---|
| no joint | free — nothing is attached there |
| `aligned`, `seated` | free — seating is what the motion is for |
| `fastened` | refused, with the step that frees it (`seated`) |
| `locked` | refused until the lock is opened (`fastened`) |

These are the mechanical motions from the part's record. They are not the optical mount DOFs that
`set_dof` turns, and no torque, friction or collision is modelled.

## Coming apart

`disassembly_plan(part)` answers in the order the steps must happen:

- `release` — only the joints that cross the boundary of the sub-assembly the part carries, so it lifts
  off as a unit with whatever it holds. Each joint is walked back state by state, then separated.
- `full` — that sub-assembly taken apart as well, deepest joint first, which is the order a bench is
  stripped in.

## Seating: where a part actually goes (04b)

The convention is **stated, not inferred**: seating makes the two declared interface frames *coincident
and anti-parallel* — the child's local `+Z`, which schema v1 calls the connection axis and surface
normal, turns to face the parent's. That means a part's outward normal has to point out of the part: a
post's foot frame points down, so the post stands up once the frames face each other.

Nothing else is read out of the data:

| Input | Rule |
|---|---|
| `insertion_mm` | Explicit depth past the frame datum, positive = into the parent (along the parent socket's `−Z`). Checked against the stated `insertion_min` / `insertion_max` on either interface; unstated limits are not invented, and the answer cites the evidence of the limits it did check. |
| `clock_deg` | Explicit rotation about the mating axis. Schema v1 carries no clocking datum beyond the frame's own `+X`, so there is nothing to infer. |
| a `null` frame | No datum, no placement. The answer is a refusal naming the field — the same rule as stage 03. |

Seating parents the carried part to its support with `matrix_parent_inverse`, so moving the support
moves the whole sub-assembly as one body. Going back to `aligned` releases the part **where it stands**;
it does not teleport home.

**Only the forward step places.** `aligned → seated` is where geometry happens. Coming back to `seated`
from `fastened` is loosening the screw: the part stays exactly where it is, and no insertion or clocking
is asked for again. (Until 2026-09-23 the backward step re-ran the placement at insertion 0, which
either moved the part back to its datum or, on a bore with a stated minimum insertion, refused to let
the screw be loosened at all.)

### A joint that closes a loop is measured, not placed

Both of its parts already have a pose, so seating it moves nothing and instead asks whether the stated
geometry actually closes: the gap in millimetres, the axis error and the clocking error against where
seating *would* put the second interface, with this joint's own clock and insertion.

Schema v1 states no tolerance for a frame, so **you name one** — `tolerance_mm` and `tolerance_deg`.
Without them the answer is a refusal that reports the residual it measured. Over the tolerance, it
refuses with the numbers and `unsolvable: true`: with those frames the loop has no consistent pose, and
nothing is nudged to make it fit.

### Dress Bench and manual assembly

Dress Bench decorates optics that stand on nothing. An optic seated on a recorded mount already has a
support, so `dress()` skips it — otherwise it would stack a second invented post under a real one.
Strip and re-dress leave manual placements and their parenting untouched, and the `BENCH_` namespace
stays Dress Bench's alone.

Opto-mechanics is millimetre-only, so seating is refused in a scene that has declared its unit scale
authoritative and non-millimetre — the same gate `check_mechanics` uses.

## Storage, atomicity and undo

The whole graph is one JSON string on `Scene.mechanics.graph_json`, validated completely before a single
property write. A refusal therefore cannot leave half a joint, and one operation is one undo step on one
datablock. `dry_run=True` returns the same decision and writes nothing.

Parts are addressed by their record's `instance_id`, so a renamed object keeps its joints and a deleted
one is reported in `dangling` rather than quietly dropped. An unreadable or future graph version is
reported and left byte-for-byte intact; nothing is migrated on read.

## The calls

| API | What it does |
|---|---|
| `enable_manual_assembly(enable=True)` | The feature flag for this scene. |
| `join_parts(a, interface_a, b, interface_b, carries=None, adapters=None, optic_thickness_mm=None, max_chain=2, dry_run=False)` | Record one joint at `aligned`. |
| `set_joint_state(joint_id, state, clock_deg=0.0, insertion_mm=0.0, tolerance_mm=None, tolerance_deg=None, dry_run=False)` | One step along the state order; seating is where placement (or the loop measurement) happens. |
| `separate_parts(joint_id, dry_run=False)` | Remove an `aligned` joint. |
| `assembly_graph()` | Every joint, the ownership forest, the loops, the dangling ends. |
| `disassembly_plan(name)` | `release` and `full`, as callable steps. |
| `permitted_motions(name)` | Which motions may move now, and what holds the rest. |

These are the names stage 04 fixes. The same seven are exposed over MCP, because a parity test requires
the MCP surface to match `optics_api` exactly; the MCP assembly *guide* is still stage 11.

## Limits

- **A placement is not a fit.** It puts the part where the declared frames say; it is not a measurement,
  a tolerance stack or a claim that the real parts go together. A `compatible` verdict behind it is a
  data statement.
- **Only as good as the frames.** The stage-01 inventory has no sourced interface frames at all yet, so
  no real part can be placed from evidence today. An interface without a frame is refused, which is the
  intended behaviour, not a gap to work around.
- A closed loop is *checked* against a tolerance you name, not solved: there is no constraint solver
  here, and an over-constrained loop is reported as unsolvable rather than relaxed.
- The evidence levels in the records are still `unverified` or `visual_approximation`; nothing here
  promotes them.
- No collision, tool access, torque, friction or load check. Those are stages 07 and 10.

Tests: `tests/test_mechanical_assembly.py` (73 checks, the graph and its gates),
`tests/test_mechanical_assembly_geometry.py` (45 checks, the placement math and its refusals) and
`tests/test_support_assembly.py` (26 checks, a real TR50/M post in a real PH50/M holder, from their
drawings — see [product-evidence.md](product-evidence.md)). Every
part in both is a labelled `FIXTURE`: the inventory has no sourced pair that mates and no sourced frame,
and the rules under test do not depend on the numbers being real.
