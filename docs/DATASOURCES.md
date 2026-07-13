# Data sources & provenance

This add-on is a *physics* simulator: every material constant, dispersion formula, and component spec it ships
is a **public, citable reference**, used so the user can reproduce real optics in simulation. Nothing here is
proprietary vendor data, and **no vendor CAD/mesh is bundled**. This file documents where each dataset comes
from, so a result is traceable to its source.

## IP / trademark

- **Vendor names and part numbers** (Thorlabs, Edmund Optics, Newport, EKSMA, CASTECH, …) appear only as
  **nominative references** — to identify a real part whose *published optical specs* a user wants to reproduce,
  the way a journal paper cites the part it used. The add-on is **not affiliated with, endorsed by, or sponsored
  by** any vendor. All trademarks are the property of their respective owners.
- **No vendor CAD/mesh ships.** The component catalog (`library.py` / `library/components.json`) stores
  *metadata only* (part number, vendor, published spec, a mesh *filename*). The `.stl`/`.obj`/`.step` geometry is
  the **user's own**, resolved from their configured local mesh folder; when it is absent, `add_component` builds
  a generic, mesh-free element from the part's published specs. Opto-mechanical geometry that the add-on *does*
  generate (mounts, posts, cages, the RS99-style periscope) is **original, parameterized from public functional
  dimensions** (bore Ø, beam height, cage spacing) — not copied vendor CAD.

## Optical materials (refractive index)

| Dataset | Source | Where |
|---|---|---|
| Optical-glass Sellmeier (N-BK7, N-SF11, F2, CaF2, fused silica, …) | SCHOTT / Corning datasheets; Malitson (fused silica, CaF2) | `physics.py` `SELLMEIER` |
| IR materials (ZnSe, Ge, Si, BaF2) | refractiveindex.info (CC0): Connolly 1979, Burnett 2016, Salzberg 1957, Malitson 1964 | `physics.py` `SELLMEIER` |
| Birefringent o/e (quartz, calcite, MgF2, sapphire) | Ghosh 1999, Dodge 1984, Malitson 1972 (via refractiveindex.info) | `physics.py` `SELLMEIER` |
| More optical glasses (N-PK51, N-LASF9, N-SF66, S-FPL51) | SCHOTT Zemax 2017 / OHARA 2017 (via refractiveindex.info); validated by published n_d/V_d | `physics.py` `SELLMEIER` |
| LWIR / IR materials (As2S3, AgCl, ZnS) | Rodney 1958, Tilton 1950, Debenham 1984 (via refractiveindex.info); validated by n at 10 µm | `physics.py` `IR_MATERIALS` |
| Metal n,k (Ag, Al, Au) | Johnson & Christy; Rakić | `physics.py` `METAL_NK` |
| Thermo-optic dn/dT | SCHOTT TIE-19; Corning 7980; LaserComponents/CASTECH (LBO) | `physics.py` `DNDT`, `LBO_DNDT` |

## Nonlinear crystals

| Crystal | Sellmeier source | Where |
|---|---|---|
| BBO (uniaxial) | Eimerl 1987 | `physics.py` `NL_CRYSTAL_SELLMEIER` |
| KDP, ADP (uniaxial) | Zernike 1964 (refractiveindex.info) | `physics.py` `NL_CRYSTAL_SELLMEIER` |
| LiIO3 (uniaxial) | Umegaki 1971 (refractiveindex.info) | `physics.py` `NL_CRYSTAL_SELLMEIER` |
| CLBO (uniaxial, UV) | Sasaki 2003 (refractiveindex.info); 1064→532 ≈ 29.2°, 532→266 ≈ 61.4° | `physics.py` `NL_CRYSTAL_SELLMEIER` |
| AgGaS2 (uniaxial, mid-IR) | Kato 1996/97 (refractiveindex.info); CO2-SHG ≈ 68.6° (dispersion-set-dependent) | `physics.py` `NL_CRYSTAL_SELLMEIER` |
| KTP (biaxial) | Kato & Takaoka, Appl. Opt. 41, 5040 (2002) | `physics.py` `BIAXIAL_SELLMEIER` |
| LBO (biaxial) | Chen 1989 / Hanson-Dick 1991 (refractiveindex.info) | `physics.py` `BIAXIAL_SELLMEIER` |
| d_eff / phase-mismatch dk(T) | order-of-magnitude literature; honest Tier-1 placeholders (labeled in-code) | `physics.py` `NL_CRYSTALS` |

**Honest limitations (labeled in code):** `NL_CRYSTALS` dk_dT slopes are tuning-curve-shape placeholders, not
first-principles dn/dT; the LBO NCPM temperature from the *constant* datasheet dn/dT lands ~256 °C vs the real
148 °C (the wavelength-resolved coefficients that reproduce 148 °C are paywalled — see `lbo_ncpm_temperature_estimate`).

## Components & opto-mechanics

- **Component catalog** (`library.py`): real vendor part numbers + published specs, as above (nominative
  reference; no CAD bundled).
- **Opto-mechanical standards** (`optomech.py`): functional dimensions (Ø12.7 mm posts, 25 mm hole grid, 30 mm
  cage spacing, beam-height datum) from public datasheets; the geometry is original and parameterized.
- **New mount/rail references**: Thorlabs RSP1 product page (Ø1 in rotation mount and continuous rotation); Thorlabs
  GM100 product family and Newport U100 product family (gimbal mechanism silhouette); Thorlabs VC1 product page
  (V-clamp application). GM100 ±4°, TRF90 pivot/arm dimensions, VC1 generated dimensions, and X95 95 mm profile
  dimensions are explicitly marked **ESTIMATE** in `presets.py`/`optomech.py` where no source dimension is shipped.

## Verification

Every formula the engine relies on is checked against a textbook closed form in `tests/test_validation.py`
(the oracle gate) and, for the load-bearing ones, against the `physicist` Docker oracle (`physics_verify`,
ok=true). See `docs/OPTICS_SCOPE.md` for the tier-a/b/c scope map.
