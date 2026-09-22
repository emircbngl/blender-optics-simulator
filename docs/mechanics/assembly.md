# Mechanical assembly graph (stage 04a)

Metadata only. This stage records **how parts are joined** — which interfaces mate, what state each
joint is in, what carries what, and in which order a part comes off. It places nothing: joining a part
does not move it, poses are not propagated, and a loop's geometry is not solved. That is stage 04b, and
`capabilities()` keeps reporting `mechanical_assembly.available: false` until it exists.

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
| `set_joint_state(joint_id, state, dry_run=False)` | One step along the state order. |
| `separate_parts(joint_id, dry_run=False)` | Remove an `aligned` joint. |
| `assembly_graph()` | Every joint, the ownership forest, the loops, the dangling ends. |
| `disassembly_plan(name)` | `release` and `full`, as callable steps. |
| `permitted_motions(name)` | Which motions may move now, and what holds the rest. |

These are the names stage 04 fixes. The same seven are exposed over MCP, because a parity test requires
the MCP surface to match `optics_api` exactly; the MCP assembly *guide* is still stage 11.

## Limits

- **No geometry.** A recorded joint is a stated mating, not a placement and not a measured fit. Parts
  stay exactly where you put them.
- Pose consistency in a closed loop is not solved and not checked — stage 04b.
- The evidence levels in the records are still `unverified` or `visual_approximation`; nothing here
  promotes them.
- No collision, tool access, torque or load check. Those are stages 07 and 10.

Tests: `tests/test_mechanical_assembly.py` (61 checks). Every part in it is a labelled `FIXTURE`: the
stage-01 inventory has no sourced pair that mates yet, and the rules under test are graph rules that do
not depend on the numbers being real.
