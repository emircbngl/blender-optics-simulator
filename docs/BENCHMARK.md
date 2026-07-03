# Agent-task benchmark (reference pipeline)

Reproduce: `blender --background --factory-startup --python tests/agent_benchmark.py`

Fifteen seeded bench-recovery tasks, scored automatically. These numbers are the
**deterministic reference pipeline** (the exact `optics_api` calls the
`optics://workflows` patterns instruct an agent to make) — i.e. the ceiling an LLM
agent driving the same tools over MCP should reach. Task definitions + scorer are
agent-agnostic; deterministic in the seeds.

| family | tasks | yield | metric | mean ± sd |
|---|---|---|---|---|
| steer | 3 | 3/3 | residual_mrad_after | 0.0003667 ± 0.00017 |
| darkport | 3 | 3/3 | recovered_power_frac | 1 ± 0 |
| ao | 3 | 3/3 | rms_modal_after_waves | 0.0006 ± 0 |
| modematch | 3 | 3/3 | coupling | 1 ± 0 |
| bypass | 3 | 3/3 | diagnosis_correct | 1 ± 0 |

## Per-task results

| family | seed | ok | metric | detail |
|---|---|---|---|---|
| steer | 1 | ✅ | 0.0003 | knock tip=-1.27 tilt=-0.72 deg; before=4.32 mrad |
| steer | 2 | ✅ | 0.0006 | knock tip=0.89 tilt=1.72 deg; before=5.80 mrad |
| steer | 3 | ✅ | 0.0002 | knock tip=0.63 tilt=-1.70 deg; before=7.03 mrad |
| darkport | 1 | ✅ | 1.0 | truly_dark=True dark_detector fired=True; nominal=1.000 recovered=1.000 |
| darkport | 2 | ✅ | 1.0 | truly_dark=True dark_detector fired=True; nominal=1.000 recovered=1.000 |
| darkport | 3 | ✅ | 1.0 | truly_dark=True dark_detector fired=True; nominal=1.000 recovered=1.000 |
| ao | 1 | ✅ | 0.0006 | rms_modal 0.0779 -> 0.0006 waves |
| ao | 2 | ✅ | 0.0006 | rms_modal 0.0779 -> 0.0006 waves |
| ao | 3 | ✅ | 0.0006 | rms_modal 0.0779 -> 0.0006 waves |
| modematch | 1 | ✅ | 1.0 | target w0=0.0797 mm at z=162.9 -> f=142.16 achieved_w0=0.07972 |
| modematch | 2 | ✅ | 1.0 | target w0=0.0604 mm at z=155.5 -> f=135.18 achieved_w0=0.06039 |
| modematch | 3 | ✅ | 1.0 | target w0=0.0734 mm at z=147.5 -> f=130.24 achieved_w0=0.07343 |
| bypass | 1 | ✅ | 1.0 | knock dx=28.0 mm; fired-for-NR_Lens=True cleared-on-restore=True |
| bypass | 2 | ✅ | 1.0 | knock dx=35.2 mm; fired-for-NR_Lens=True cleared-on-restore=True |
| bypass | 3 | ✅ | 1.0 | knock dx=24.3 mm; fired-for-NR_Lens=True cleared-on-restore=True |
