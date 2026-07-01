# Submitting to the Blender Extensions platform (extensions.blender.org)

This is the owner-gated checklist + prep for listing **Blender Optics Simulator** on
[extensions.blender.org](https://extensions.blender.org) — the #1 discoverability channel for a Blender
add-on. Everything technical below is done; the actual submission (account, upload, agreeing to terms)
is the maintainer's to make.

## Compliance status — ready

| Requirement | Status |
|---|---|
| `blender_manifest.toml` schema 1.0.0 (id, version, name, tagline, maintainer, type) | ✅ |
| GPL-compatible license (`SPDX:GPL-3.0-or-later`) | ✅ |
| `blender_version_min` set (`4.2.0`) | ✅ |
| `[permissions]` declared with justifications (network = localhost MCP bridge; files = mesh import/cache) | ✅ |
| Pure Python — **no bundled binaries** (`.so/.dll/.dylib/.pyd`) or precompiled wheels | ✅ (scanned) |
| **No bundled proprietary / vendor assets** (no `.stl/.obj/.blend`; catalog is public part-numbers only, see `docs/DATASOURCES.md`) | ✅ |
| Built zip is clean — Blender's `extension build` excludes `__pycache__` / `.pyc` / `.DS_Store` | ✅ (verified) |
| `tagline` ≤ 64 chars, no trailing period | ✅ (53) |

## The one real blocker — the self-hosted updater — is resolved

The add-on ships its **own** update channel (a self-hosted GitHub-Pages extension repo + an in-add-on
"Updates" panel that registers that repo and installs from it). That is exactly what the platform's
review guidelines disallow — an extension must **not** register external repositories or install code
from outside the platform; Blender delivers updates for platform-installed extensions itself.

**Resolution (already implemented, single build):** `updater.py` now gates its entire self-update
behaviour on `_platform_managed()` — true when the extension's package is `bl_ext.blender_org.<id>`
(i.e. it was installed *from* extensions.blender.org). When platform-managed:
- `register()` does **not** start the daily-check timer or the apply-on-quit hook,
- the exit hook and `_ensure_repo` never register our external repo,
- the "Updates" panel shows a neutral *"updates via Blender Extensions"* line instead of a Check/Install button.

So **the same zip** works both ways: on the platform → Blender updates it; from GitHub/one-click/disk →
our self-hosted channel + in-add-on updater run as before. No second build to maintain.

> **One assumption to verify at submission time:** the official repo's module id is taken to be
> `blender_org` (the middle field of `bl_ext.blender_org.<id>`). If Blender ever renames it, update the
> single string in `updater.py::_platform_managed()`. Easy to confirm after the first platform install:
> the add-on's `__package__` will show the real module id.

## Listing metadata (draft)

- **Name:** Blender Optics Simulator *(the manifest `name` is currently "Optical Alignment & Simulation" —
  consider aligning it to the product name for the listing; see the naming note below).*
- **Tagline:** Live ray tracing & auto-alignment for optical benches
- **Tags:** `3D View`, `Render`, `Object`
- **Description (long):** An optical bench you lay out in 3-D, trace with a live, physics-verified beam
  engine (ray + Gaussian-q ABCD + Jones/Stokes polarization + wave-optics overlays), mount on real
  opto-mechanics, and render in Cycles — and that an **AI agent can drive over MCP**. Build interferometers,
  telescopes, adaptive-optics loops; auto-align with influence-matrix solvers; `diagnose()` flags problems.
  Physics is checked against textbook answers in CI, not asserted.
- **Permissions rationale (for the reviewer):**
  - *network* — a **localhost-only** socket bridge (127.0.0.1) that lets an external MCP agent drive the
    scene; opt-in (the user starts it), whitelisted to the add-on's own API. No outbound/telemetry.
  - *files* — importing user mesh libraries (STL/OBJ/STEP) and writing converted meshes to the add-on cache.
- **Screenshots/preview:** reuse `docs/img/hero.png`, `docs/img/agent-align.gif`, and a feature render
  (e.g. `docs/img/biaxial-crystals-demo.png` or `speckle-demo.png`).

## Submission steps (maintainer)

1. Log in at <https://extensions.blender.org> with your Blender ID.
2. **Upload** the current release zip (`dist/optical_alignment_sim-<version>.zip`) — it is built by
   `blender --command extension build --source-dir optical_alignment_sim --output-filepath dist/...zip`.
3. Fill the listing (metadata above), add screenshots, pick the license (GPL-3.0-or-later), confirm the
   permissions justifications.
4. Submit for review. Reviewers check the manifest, license, permissions, and that no code is fetched
   from outside the platform — the `_platform_managed()` gate above is what satisfies the last point.
5. On approval, **future releases**: bump the version, rebuild the zip, and upload it as a new version on
   the platform (in addition to the GitHub release, which still feeds the self-hosted channel for
   GitHub/one-click users).

## After listing — keep BOTH channels healthy

- Platform users → updated by Blender from extensions.blender.org.
- GitHub / one-click / disk users → updated by the self-hosted channel + in-add-on updater (unchanged).
- Each release therefore has two publish targets: the **GitHub release** (feeds `docs/index.json`) and the
  **platform version upload**. Keep them on the same version number.
