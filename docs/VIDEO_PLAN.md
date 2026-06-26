# Showcase video — production plan (v3 refresh)

A **general plugin-showcase film** (not a v0.10.0-only teaser): it shows the whole tool — build on real
opto-mechanics, simulate the light with verified physics, align, sense + correct the wavefront, and let an
AI agent drive the bench — with the v0.10.0 capabilities woven in as enrichment, not the sole subject.

It **refreshes** the existing DARK BENCH film (`docs/img/showcase.mp4`, ~78 s) at **zero new Cycles
render cost**: every act reuses proven `seg_*.mp4` footage and already-rendered PNG/SVG panels; the new
material is **2-D HUD overlays** composited over that footage. Render of the final film is **owner-gated** —
this document + the `v3/` scripts prepare everything so it can be assembled on demand; nothing here renders.

---

## Through-line — two framings (the owner picks the tone)

**A · General (recommended).** *Light, made legible.* The **plugin's breadth** is the star: a complete
optical bench you build, simulate, align, sense, and render — with **verified physics** — that an AI agent
can also drive. The agent is the unifying thread ("a bench that reads its own light") and the climactic
close, not the protagonist of every act.

**B · AI-first (the workflow synthesis).** *A machine that reads its own light and decides.* The **AI agent
is the protagonist**; its READ → JUDGE → ACT → RE-TRACE loop is the spine, and the **JUDGE** beat
(`propose_corrections` → refuse / partial / accept) is the new heart — the one thing v0.10.0 added that
proves the tool is *honest*, not auto-magic.

Both share the **same 6-act spine and the same footage** — only the act-cards and the emphasis differ
(general leads with the optics; AI-first leads with the agent). The card text for each is in the shot list
below (general / AI-first).

---

## Shot list (6 acts, ~84 s, native 30 fps)

| Act | On screen | Reuse | New (2-D only) | Real number (⚠ = re-read live before it goes on screen) |
|---|---|---|---|---|
| **0 · COLD OPEN** — a beam ignites, traces the bench, splits at the BS and recombines (Mach-Zehnder, wonder). | `seg_open.mp4` | `hud_read` typing card: `get_state()` → elements, `inspect_beam("BS")` → one held line | `inspect_beam("BS")` output ⚠ |
| **1 · BUILD** — 30 mm cage snaps rod-by-rod, lens tube threads in, rail carrier slides. | `seg_turn.mp4` | corner counter `215 → 357 checks · CI green`; optional 6-frame `feature-board.png` flash | 215 → 357 (real) |
| **2 · SIMULATE / SENSE** — Gaussian w(z) breathes (lens sweep, optic moves not camera); Newton's rings breathe with their live 2-D fringe panel; `detect_phenomena()` snaps a label; optional dichroic colour-split insert. | `seg_interf.mp4` + `dichroic-edge.png` | `hud_phenomena`: `detect_phenomena()` → `two_beam_interference` (+ `off_axis_hologram`), `Λ = λ/(2 sin θ/2)` under it | `Λ` oracle-verified; w(z)/M² ⚠ |
| **3 · ALIGN / JUDGE** — `propose_corrections()` 3-row verdict (REFUSE a crossed analyzer = the experiment; PARTIAL; ACCEPT a pointing error); the accepted row drives the KM100 turn + beam onto the sensor. | `seg_align.mp4` | `hud_judge`: REFUSE · PARTIAL · ACCEPT card + residual counter held at the floor | 7.0 → 0.001 mrad — match the clip's baked digits ⚠ |
| **4 · WAVEFRONT / AO (climax)** — inject defocus+astig+coma; **two** sensors read the same wavefront — Shack-Hartmann (modal) **and** the new pyramid SLOPE sensor — the WFS folds in the beam's own curvature defocus; the DM cancels it; blurry → sharp; one-frame zonal-quincunx flash. | `seg_ao.mp4` + `wavefront-aberrated/flattened.png` | `hud_dual_sensor`: `pyramid-wfs.png` + `wfs-defocus.png` fly-in; `die-/zonal-wavefront.png` 6-frame flash; RMS counter | RMS 0.559λ → 0.000λ (real); pyramid `dZ4/dx = 4√3·x` (verified); panel sub-numbers live in the PNGs — read off, do not retype ⚠ |
| **5 · AI DRIVES IT (close mirrors open)** — "Align this Michelson" typed; agent runs READ → JUDGE → ACT → RE-TRACE; the bench locks; the beam re-ignites like the cold open. | `seg_michelson.mp4` + `seg_cta.mp4` | `hud_loop`: `ai-loop.svg` draw-on; 1 s `architecture.svg` beat; final number echo | echo the align floor / 0.000λ ⚠ |

**Act-card lines** — *general* / *AI-first*:
0. *"Light, made legible."* / *"Read the bench — never guess the light."*
1. *"Build — real mounts, machine-verified."* / *"Build — the agent assembles."*
2. *"Simulate — and name the phenomenon."* / *"Sense — the agent names it, not just the picture."*
3. *"Align — to under a milliradian."* / *"Judge — a crossed analyzer is the experiment, not a fault."*
4. *"Correct — modal + slope, sensed and cancelled. 0.56λ → 0.00λ."* (both)
5. *"An optical bench an AI agent can drive — with verified physics."* (both)

---

## Reuse (no render) vs new work

**Reuse — existing footage / panels:** `seg_open`, `seg_turn`, `seg_interf` (+ live fringe), `seg_align`
(KM100 + beam-walk), `seg_ao` (cause/residual + RMS HUD), `seg_michelson`, `seg_cta` — all in
`~/blender-optics-promo/`. Panels: `pyramid-wfs.png`, `wfs-defocus.png`, `die-wavefront.png`,
`zonal-wavefront.png`, `dichroic-edge.png`, `feature-board.png`, `ai-loop.svg`, `architecture.svg`,
`wavefront-aberrated/flattened.png`.

**New work — ZERO new Cycles 3-D renders.** The agent's drama is entirely **2-D HUD overlays** (compositor
only). One **one-time engine read** (not a render) captures the real v0.10.0 numbers for the HUDs.

| New asset | What it does | Needs Blender? |
|---|---|---|
| `v3/capture_numbers.py` | runs `inspect_beam` / `beam_profile` / `detect_phenomena` / `ao_measure` / `pyramid_wfs` on the real scenes → `v3/numbers.json` (the HUD source of truth) | **yes** (run after the restart) |
| `v3/hud_read.py` | Act 0 — types `get_state()`/`inspect_beam("BS")` as a coral monospace lower-third → `read_*.png`/clip | no |
| `v3/hud_phenomena.py` | Act 2 — the `detect_phenomena` label + `Λ = λ/(2 sin θ/2)` card | no |
| `v3/hud_judge.py` | Act 3 — the REFUSE/PARTIAL/ACCEPT 3-row verdict card + residual counter (the new heart) | no |
| `v3/hud_dual_sensor.py` | Act 4 — composites `pyramid-wfs.png` + `wfs-defocus.png` fly-in + the zonal flash + the RMS counter | no |
| `v3/hud_loop.py` | Act 5 — draws on `ai-loop.svg` + the `architecture.svg` beat | no |
| `v3/make_cards_v3.sh` | the changed act-cards (Charter serif + coral centre-drawn underline ~1.4× the text) | no |
| `v3/assemble_v3.py` | the build order: overlay each HUD on its `seg_*` clip, insert cards, stitch, then `post_bloom_encode_v2.sh` | no |

---

## Tech spec (carry the proven DARK BENCH v2 pipeline unchanged)

Native **30 fps**, **no** frame interpolation (it caused the stutter). Cycles **motion blur** stays on the
already-keyframed motion (cage assemble, rail slide, KM100 turn, beam walk) — **never speed-ramp a thin
beam** (judder). **Bezier ease** with a held beat on every number. **No horizon** — the warm radial-gradient
dark world is preserved by reusing the existing footage's world. Palette: warm/coral accent (coral
monospace HUD; coral centre-drawn card underline ~1.4× the text length). **Charter serif** act-cards via
`make_cards`. Post = **bloom + vignette + light grain** via `post_bloom_encode_v2.sh`; grain at `alls=3
+crf22 +preset slow` keeps the near-black gradients band-free and the file ~4–9 MB (under GitHub's 100 MB).
1080p, ~768–1024 Cycles samples **only if** a clip is ever re-rendered (not in this refresh).

## Build order (owner-gated render)

1. **Restart Blender** so the running instance loads the synced v0.10.0 add-on; restart the MCP bridge.
2. `v3/capture_numbers.py` → `numbers.json` (the real HUD digits).
3. The five `v3/hud_*.py` → the overlay PNGs/clips (no Blender, fast).
4. `v3/make_cards_v3.sh` → the changed act-cards.
5. `v3/assemble_v3.py` → overlay + stitch + `post_bloom_encode_v2.sh` → `showcase_v3.mp4`.
6. Owner reviews + posts / attaches to the v0.10.0 release (GitHub does not autoplay repo mp4 — a GIF teaser
   or the Release is the venue).

## Risks (from the concept workflow) + mitigations

1. **On-screen numbers drift** from the live build or the clip's own baked HUD → `capture_numbers.py` is the
   single source of truth; for `seg_align`/`seg_ao` (which carry their own baked HUD) match the card to the
   clip's actual digits, never a transcribed value. Every ⚠ above is re-read here, not assumed.
2. **The JUDGE card could imply the engine auto-fixes.** `propose_corrections()` is **advisory** — the card
   must read "the agent *judges*" (REFUSE is shown first, on purpose).
3. **Reused-clip framing vs the new lower-third HUD** → place HUDs in the empty (no-horizon) negative space;
   keep the `post_ai_v2.py` typed-command timing on `seg_michelson`.
