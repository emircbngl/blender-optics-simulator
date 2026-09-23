# Mechanical compatibility (stage 03)

Read-only. The engine answers one question — *can these two interfaces mate?* — from the data each part
states about itself, and nothing else. It does not move, create or modify anything in the scene.

## Verdicts

| Verdict | Meaning |
|---|---|
| `compatible` | Every rule that applies passed, and each one cited at least one source. |
| `incompatible` | A rule failed on stated values: wrong standard, wrong size, a screw that bottoms out. |
| `unknown` | Something the rule needed is not stated. The answer names the field in `missing`. |
| `adapter_required` | The direct fit fails, but the supplied parts contain a route where every hop is compatible. |

**A missing value is never a pass.** A verdict of `compatible` requires evidence: if no rule cited a
source, the answer is `unknown`, not a fit. Two equal diameters, a shared family name, or meshes that do
not visibly collide are not compatibility.

## What each pairing checks

| Interfaces | Rules |
|---|---|
| `thread` + `thread` | Opposite genders; identical standard, hand and form; major diameter and pitch equal within the parts' own declared `model_error_limit` (no default tolerance); the male side's reach against the female side's depth, so a screw that bottoms out is rejected. |
| `smooth_bore` + `shaft` | The shaft has to enter the bore; the gap has to be within the bore's stated `clearance` (without a stated clearance the fit is `unknown`, because a gap alone says nothing); the bore's `insertion_min` against what the shaft can offer. |
| `optic_seat` + optic | The optic thickness you pass in against the seat's stated `optic_thickness_min` / `optic_thickness_max`. |
| `hole_pattern` + `hole_pattern` | `rod_spacing` and hole `diameter` equal within the declared limits. |
| `dovetail` + `clamp`, `plane` + `plane` | `unknown`: schema v1 carries no profile or seating datum, so the fit cannot be decided from the data. |
| anything else | `unknown` with "no rule for X against Y", not `incompatible`. |

Values are normalised to millimetres and degrees before comparison; the stored record keeps its original
units. A gap is compared with the stated clearance allowing `REPRESENTATION_MM` = 1e-9 mm: stated
decimals live in binary floating point, and 12.8 − 12.0 is 0.8000000000000007, which used to reject a
0.8 mm gap against a 0.8 mm clearance. That allowance is round-off only, not a tolerance.

## Adapters

`check_compatibility(..., adapters=[...])` searches the supplied parts breadth-first, so the shortest
chain wins. Each part is used at most once per chain, which is what stops A→B→A loops; `max_chain`
(default 2) bounds the depth. Every hop must be `compatible` on its own evidence — an `unknown` hop is
never accepted as a route.

An adapter without a manufacturer and part number still appears in the chain, but `missing` then contains
`adapter identity (manufacturer and part number)`: the data shows a route exists, and naming a product
that has not been identified would be a guess.

## The three calls

| API | MCP | What it does |
|---|---|---|
| `optics_api.inspect_part(name)` | `inspect_part` | The stored identity: manufacturer, part number, sources, interface and motion ids, evidence level. |
| `optics_api.list_interfaces(name)` | `list_interfaces` | Each interface in mm/deg: kind, thread labels, stated dimensions, and the source id behind every one. A value the product data does not state comes back as `null`. |
| `optics_api.check_compatibility(a, interface_a, b, interface_b, adapters=None, optic_thickness_mm=None, max_chain=2)` | `check_compatibility` | The verdict, the rule-by-rule reasoning, the sources used, what was missing, and any adapter chain. |

These are the names stage 03 fixes; the plan listed them as candidates.

## Limits

- **This is a data check, not a tested fit.** A `compatible` verdict says the stated values agree. It is
  not a measurement, a tolerance stack, or a claim that the real parts thread together.
- The evidence levels in the records are still `unverified` or `visual_approximation`; stage 03 does not
  promote them.
- Manufacturing tolerance is not modelled. `model_error_limit` is a model's own allowance, written by
  whoever entered the data; it is not a fit class.
- No assembly order, collision or tool-access check: those are stages 04 and 10. `capabilities()`
  continues to report `mechanical_assembly.available: false`.
- The inventory itself still has gaps (clearance, insertion depth, adapter products). Those show up as
  `unknown` verdicts naming the field, which is the intended behaviour, not a bug to work around.

Tests: `tests/test_mechanical_compatibility.py` (27 checks). Real rows use the sourced facts from
[`product-evidence.json`](product-evidence.json); rows marked `FIXTURE` are synthetic and exist because
the inventory has no sourced data for that rule yet.
