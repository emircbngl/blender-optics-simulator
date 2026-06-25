# Tooling taxonomy — MCP tool vs Blender operator vs Claude skill vs hook (vs connector)

Decision record for *where* a capability should live, so the plugin stays consistent and the AI's error rate
drops. Owner decision (2026-06-25): **no Claude connector — invest in optics SKILLS instead.**

## The five surfaces

| Surface | What it is | Runs where | Use it for |
|---|---|---|---|
| **MCP tool** | A function the model calls during a turn; structured args → structured result. Here: `optics_api` functions exposed over the localhost bridge (9765). | The model invokes; executes in Blender via the bridge. | **Atomic, parameterised actions** an agent composes: `get_state`, `set_param`, `place_relative`, `trace_beam`, `zonal_render`, `sensor_capture`. The primitives. |
| **Blender operator** | A `bpy.types.Operator` (a button / `optics.*`). | Inside Blender, by a human (or the model via the operator). | **Human UI** + anything that needs Blender's modal/undo/redraw context. Most operators wrap the same `optics_api` core. |
| **Claude skill** | A model-invoked instruction package (a `SKILL.md` + optional scripts) the model loads when a task matches; encodes a *workflow* + judgement, not a single call. | The model loads + follows; calls MCP tools inside. | **Repeatable multi-step workflows + conventions**: "build + align + render a bench", "diagnose and propose corrections", "read a surface figure". Where the value is *how to sequence + judge*, not a new primitive. |
| **Hook** | A shell command the **harness** runs deterministically on an event (PreToolUse/PostToolUse/Stop/…). The harness runs it, not the model. | Locally, on tool/turn events. | **Guardrails the model must not skip**: e.g. a Stop hook that checks "did you physics_verify the formula you shipped?" or "is the regression green before committing?". Enforcement, not capability. |
| **Connector** | A remote/managed MCP integration (hosted, OAuth, shareable). | Remote. | Distributing an MCP to many users / SaaS. **Not needed here** — the bench is a *local* Blender; a connector adds hosting/ops without new capability. |

## Decisions

1. **Connector → SKILLS.** The real gaps the owner named (AI doesn't know what it can do; can't see results;
   inconsistent usage; no judged auto-fix) are solved by `capabilities()` + `AGENT_GUIDE.md` (done, Phase 0) and
   by **skills** (Phase 2) — not by hosting the MCP remotely. Revisit a connector only if we ever package the
   bench for non-local / multi-user use.

2. **Primitive vs workflow.** New *atomic* capabilities → MCP tools (+ the operator that wraps them for humans).
   New *sequenced/judged workflows* → Claude skills that call those tools. Don't bake a fixed workflow into a
   single mega-tool; keep tools composable and put the sequence in a skill.

3. **Enforcement → hooks.** Discipline that must never be skipped (physics_verify-before-claim, regression-green-
   before-commit, render-per-feature reminder) belongs in harness hooks, not in prose the model may forget.

4. **The AI's eyes are MCP tools, not skills.** `get_state`/`diagnose`/`sensor_capture`/`beam_profile` stay
   primitives the model calls freely; the skill tells it *to* call them first.

## Optics skills (Phase 2.1 — BUILT, `.claude/skills/`)
The connector replacement: model-invoked `/optics-*` workflows that sequence the MCP tools + carry the
disciplines. All check into the repo, so anyone cloning gets them.
- `optics-build` — stand up a bench (example or from components), set params/mounts, verify it traces.
- `optics-align` — auto_align / tilt_null / mode_match with the inspect-first loop + convergence reporting.
- `optics-inspect` — get_state + inspect_beam + inspect_element + sensor_capture/beam_profile → a
  structured, READ-ONLY "what's the bench doing" (the golden rule: inspect, don't guess).
- `optics-correct` — propose_corrections(), weigh user intent, refuse / partial / accept (Phase 1.3 model).
- `optics-sensor-render` — sensor_capture + ao_measure + zonal_render: the honest modal-vs-zonal sensor read.

## Planned hooks (consider in Phase 2.3 / later)
- Stop-hook style: warn if a numeric/physics result was reported without a `physics_verify ok=true` this session
  (the physicist gate, already active project-wide) — keep it.
- Pre-commit: regression-green + extension-build sanity before a push.
