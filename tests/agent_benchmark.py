"""Agent-task benchmark for the Blender Optics Simulator.

Run:
    blender --background --factory-startup --python tests/agent_benchmark.py

Fifteen SEEDED, reproducible bench-recovery tasks (5 families x 3 seeds), each scored
automatically. v1 measures the DETERMINISTIC reference pipeline -- the exact optics_api
calls an agent is instructed to make (see the optics://workflows MCP resources) -- so the
numbers are the engine's reference performance and the CEILING an LLM agent driving the
same tools should reach. The task definitions + scorer are agent-agnostic: point an LLM
at the same {setup, perturb, success-criterion} triples over MCP and score it identically.

Families:
  steer      knock a kinematic mirror's tip/tilt (seeded, +/-2 deg)  -> align_element;
             score the pointing residual (mrad).
  darkport   knock until the detector is DARK -> diagnose must name the dark detector,
             align_element must recover the power.
  ao         seed Kolmogorov turbulence (ao_kolmogorov) -> ao_close_loop; score the
             correctable modal RMS before -> after.
  modematch  solve the single lens that hits a seeded target waist/plane (mode_match)
             and verify the solve by PROPAGATING the input q through it; score coupling.
  bypass     knock a lens clear off the beam (the owner's Newton's-rings case) ->
             diagnose must fire optic_bypassed for the right element; restoring the pose
             must clear it.

Output: a per-task table + per-family {yield, mean +/- sd} + docs/BENCHMARK.md + a JSON
artifact next to it. Deterministic in the seeds (numpy default_rng).
"""
import bpy, sys, os, math, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import numpy as np

import optical_alignment_sim as oas
oas.register()
import optics_api
from optical_alignment_sim import scan, alignment, tracer, mounts, elements_generic as eg
from optical_alignment_sim import diagnostics as diag

sc = bpy.context.scene
SEEDS = (1, 2, 3)
results = []            # {family, seed, success, metric_name, metric, detail}


def _clear():
    for o in list(sc.objects):
        if getattr(o, "optics", None) and o.optics.is_optical:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()


def _knock(obj, tip_deg=0.0, tilt_deg=0.0):
    for d in obj.optics.dofs:
        if d.kind == "TIP":
            d.current = tip_deg
        elif d.kind == "TILT":
            d.current = tilt_deg
    mounts.compose_pose(obj)
    bpy.context.view_layer.update()


def _steer_bench(name_prefix="BM"):
    coll = eg.example_collection("Bench_%s" % name_prefix)
    eg.source("%s_S" % name_prefix, (-120, 0, 0), (1, 0, 0), coll)
    eg.mirror("%s_M" % name_prefix, (0, 0, 0), (1, 0, 0), (0, 1, 0), coll)
    optics_api.set_mount("%s_M" % name_prefix, "KM100")
    eg.detector("%s_D" % name_prefix, (0, 120, 0), (0, 1, 0), coll)
    bpy.context.view_layer.update()
    return sc.objects["%s_M" % name_prefix]


# ---------------------------------------------------------------- family: steer
for seed in SEEDS:
    rng = np.random.default_rng(seed)
    _clear()
    m = _steer_bench()
    tip, tilt = (float(rng.uniform(0.5, 2.0)) * (1 if rng.random() < 0.5 else -1) for _ in range(2))
    _knock(m, tip, tilt)
    res = optics_api.align_element("BM_M")
    ok = bool(res.get("ok")) and res.get("after") is not None and res["after"] < 0.1
    results.append({"family": "steer", "seed": seed, "success": ok,
                    "metric_name": "residual_mrad_after", "metric": round(res.get("after") or -1, 4),
                    "detail": "knock tip=%.2f tilt=%.2f deg; before=%.2f mrad" % (tip, tilt, res.get("before") or -1)})

# ---------------------------------------------------------------- family: darkport
for seed in SEEDS:
    rng = np.random.default_rng(100 + seed)
    _clear()
    m = _steer_bench("DP")
    p_nom, _, _ = alignment.measure(scan._trace(sc), "DP_D", "NONE")
    # knock HARD enough that the tracer drops the ray entirely (truly dark). A fully-dropped beam is
    # OUTSIDE align_element's fine-capture range by construction -- the reference recovery is what a
    # lab tech does and what the dark-port workflow pattern teaches: diagnose (which mount died) ->
    # RE-HOME that mount (set_mount re-applies the preset with all DOFs at 0) -> fine-align.
    _knock(m, float(rng.uniform(3.2, 3.9)), float(rng.uniform(2.0, 3.0)))
    segs = scan._trace(sc)
    tracer.cached_segments = segs
    p_dark, _, _ = alignment.measure(segs, "DP_D", "NONE")
    dk = [d for d in diag.run_diagnostics(sc) if d["kind"] == "dark_detector" and d["element"] == "DP_D"]
    optics_api.reset_mount("DP_M")                        # re-home (DOFs to 0, base pose untouched)
    res = optics_api.align_element("DP_M")                # fine-align from true home
    p_rec, _, _ = alignment.measure(scan._trace(sc), "DP_D", "NONE")
    ok = p_dark < 0 and bool(dk) and p_nom > 0 and p_rec >= 0.99 * p_nom
    results.append({"family": "darkport", "seed": seed, "success": ok,
                    "metric_name": "recovered_power_frac", "metric": round(p_rec / p_nom if p_nom else -1, 4),
                    "detail": "truly_dark=%s dark_detector fired=%s; nominal=%.3f recovered=%.3f"
                              % (p_dark < 0, bool(dk), p_nom, p_rec)})

# ---------------------------------------------------------------- family: ao
for seed in SEEDS:
    _clear()
    optics_api.build_example("adaptive_optics")
    optics_api.ao_kolmogorov("AO_Turbulence", seed=seed)
    rms0 = optics_api.ao_measure("AO_WFS").get("rms_modal", -1)
    optics_api.ao_close_loop("AO_WFS", "AO_DM")
    rms1 = optics_api.ao_measure("AO_WFS").get("rms_modal", -1)
    ok = rms0 > 0.05 and 0 <= rms1 < 0.02 and rms1 < rms0 / 5.0
    results.append({"family": "ao", "seed": seed, "success": ok,
                    "metric_name": "rms_modal_after_waves", "metric": round(rms1, 5),
                    "detail": "rms_modal %.4f -> %.4f waves" % (rms0, rms1)})

# ---------------------------------------------------------------- family: modematch
for seed in SEEDS:
    rng = np.random.default_rng(200 + seed)
    w0_in, s_in, wl = 0.30, 120.0, 632.8
    w0_t = float(rng.uniform(0.05, 0.08))      # seeded inside the solver's FEASIBLE band
    z_t = float(rng.uniform(120.0, 200.0))     # (probed: all four corners have a real-focal solution)
    mm = optics_api.mode_match(w0_in, s_in, w0_t, z_t, wl)
    # the solve is verified by PROPAGATION: mode_match pushes the input q through the solved lens and
    # reports the ACHIEVED waist/plane + the power coupling into the target mode
    ok = bool(mm.get("ok")) and abs(mm.get("achieved_w0", 0) - w0_t) < 1e-6 * max(1.0, w0_t) \
        and mm.get("coupling", 0) >= 0.999
    results.append({"family": "modematch", "seed": seed, "success": ok,
                    "metric_name": "coupling", "metric": round(mm.get("coupling", -1), 6),
                    "detail": "target w0=%.4f mm at z=%.1f -> f=%s achieved_w0=%s"
                              % (w0_t, z_t, round(mm.get("f", -1), 2) if mm.get("ok") else None,
                                 round(mm.get("achieved_w0", -1), 5) if mm.get("ok") else None)})

# ---------------------------------------------------------------- family: bypass
for seed in SEEDS:
    rng = np.random.default_rng(300 + seed)
    _clear()
    optics_api.build_example("newton_rings")
    lens = sc.objects["NR_Lens"]
    home = lens.location.copy()
    # NR_Lens sits in the +Y arm (beam travels +Y at x=80): LATERAL to that beam is +X. (First harness
    # draft knocked along +Y -- ALONG the beam -- and the engine correctly did NOT flag a bypass.)
    dx = float(rng.uniform(20.0, 40.0))
    lens.location = (home[0] + dx, home[1], home[2])
    bpy.context.view_layer.update()
    tracer.cached_segments = scan._trace(sc)
    fired = [d for d in diag.run_diagnostics(sc) if d["kind"] == "optic_bypassed"]
    correct = bool(fired) and all(d["element"] == "NR_Lens" for d in fired)
    lens.location = home
    bpy.context.view_layer.update()
    tracer.cached_segments = scan._trace(sc)
    cleared = not [d for d in diag.run_diagnostics(sc) if d["kind"] == "optic_bypassed"]
    ok = correct and cleared
    results.append({"family": "bypass", "seed": seed, "success": ok,
                    "metric_name": "diagnosis_correct", "metric": 1.0 if ok else 0.0,
                    "detail": "knock dx=%.1f mm; fired-for-NR_Lens=%s cleared-on-restore=%s" % (dx, correct, cleared)})

# ---------------------------------------------------------------- report
fams = {}
for r in results:
    fams.setdefault(r["family"], []).append(r)

lines = ["# Agent-task benchmark (reference pipeline)", "",
         "Reproduce: `blender --background --factory-startup --python tests/agent_benchmark.py`", "",
         "Fifteen seeded bench-recovery tasks, scored automatically. These numbers are the",
         "**deterministic reference pipeline** (the exact `optics_api` calls the",
         "`optics://workflows` patterns instruct an agent to make) — i.e. the ceiling an LLM",
         "agent driving the same tools over MCP should reach. Task definitions + scorer are",
         "agent-agnostic; deterministic in the seeds.", "",
         "| family | tasks | yield | metric | mean ± sd |", "|---|---|---|---|---|"]
print("\n" + "=" * 74)
all_ok = True
for fam, rs in fams.items():
    ys = sum(1 for r in rs if r["success"])
    vals = [r["metric"] for r in rs if r["success"]]
    mean = float(np.mean(vals)) if vals else float("nan")
    sd = float(np.std(vals)) if vals else float("nan")
    all_ok &= (ys == len(rs))
    lines.append("| %s | %d | %d/%d | %s | %.4g ± %.2g |" % (fam, len(rs), ys, len(rs), rs[0]["metric_name"], mean, sd))
    print("  %-10s yield %d/%d   %s = %.4g +/- %.2g" % (fam, ys, len(rs), rs[0]["metric_name"], mean, sd))
lines += ["", "## Per-task results", "", "| family | seed | ok | metric | detail |", "|---|---|---|---|---|"]
for r in results:
    lines.append("| %s | %d | %s | %s | %s |" % (r["family"], r["seed"], "✅" if r["success"] else "❌",
                                                 r["metric"], r["detail"]))
    print("    [%s] %-10s seed=%d  %s=%s  (%s)" % ("PASS" if r["success"] else "FAIL", r["family"],
                                                   r["seed"], r["metric_name"], r["metric"], r["detail"]))
print("=" * 74)

out_md = os.path.join(REPO, "docs", "BENCHMARK.md")
open(out_md, "w").write("\n".join(lines) + "\n")
out_json = os.path.join(REPO, "docs", "benchmark_results.json")
json.dump({"results": results}, open(out_json, "w"), indent=2)
print("wrote %s + %s" % (out_md, out_json))
print("BENCHMARK %s  (%d/%d tasks)" % ("PASS" if all_ok else "PARTIAL",
                                       sum(1 for r in results if r["success"]), len(results)))
sys.exit(0 if all_ok else 1)
