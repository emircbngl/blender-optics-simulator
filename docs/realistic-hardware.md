# Realistic optomechanics

The simulator keeps its existing basic bench geometry and mount controls. Render preparation
adds a separate, viewport-disabled `OAR_Hardware` collection. Its objects follow the basic parts,
carry no optical behavior, and replace those parts only in camera renders. The original meshes,
poses, apertures and DOFs are unchanged. Reset Render Style and completed/cancelled UI renders
remove the detail and restore each part's prior render visibility. Sequence rendering also cleans
up on success or failure. A bench created automatically for rendering is removed afterward.

## Use

1. Select an optical element and apply the existing Mount preset (KM100, RSP1, etc.).
2. Use Dress Bench if you want to see its basic support assembly while simulating.
3. In Render, enable **Realistic optics (render)** and **Detailed hardware (render)**.
4. Choose EEVEE Preview or Cycles Final. Hardware is built automatically if needed.

The detail profiles reuse KM100, KM100CP/M, KS1, EO-15866, POLARIS-K1, RSP1, GM100,
TRF90 and VC1. Generic lens cells, cameras, sources, translation stages, cage and rail
assemblies inherit the material treatment. Kinematic mounts receive coil springs and knurled
adjusters; RSP rings receive knurling, 2-degree marks and 30-degree number labels; posts receive
smooth steel surfaces and a cross hole. POLARIS plate material differs from anodized mounts.

Detailed hardware uses the existing millimetre bench convention. Convert an explicitly metre-scaled scene to mm before render preparation.

## Asset library

Run inside Blender:

```sh
blender --background --factory-startup --python-exit-code 1 \
  --python tools/build_hardware_assets.py -- /path/to/asset-library
```

Add that output folder in Blender Preferences > File Paths > Asset Libraries. The 33 collections
can be appended from the Asset Browser. They include basic optics/mount data and a viewport-hidden
render-detail subcollection; a shared breadboard is excluded. Use **Append**, with the add-on
enabled, when you need editable optics and mount controls. The procedural generator is the source
of truth; generated .blend assets need not be committed to the add-on package.

## Sources and model limits

These are original, vendor-inspired visual models, **not manufacturing CAD or verified dimensional
replicas**. Mount envelopes and most support geometry remain estimates where no drawing was
validated. Coil count, wire size, knurl depth, text sizes and surface roughness are visual choices,
not measured specifications. No vendor CAD or brand logos are copied. Visual details do not
introduce collision geometry into the optical tracer or change tolerances.

**The Ø12.7 mm post and its post holder are the exception.** Their critical dimensions follow
Thorlabs drawings TR50/M 0331 rev J and PH50/M 23132 rev B (read 2026-09-22; see
[mechanics/product-evidence.md](mechanics/product-evidence.md)): a Ø25 × 50 mm holder with a closed wall
and a Ø12.8 × 43.2 mm bore, the thumbscrew axis 12.7 mm below the top with a Ø14.5 mm knob standing
10 mm proud, and the post's Ø3.2 mm cross-hole 10.2 mm below its top. `tests/test_support_geometry.py`
measures the shipped Dress Bench and render meshes against those drawing values at 0.05 mm — half
the drawings' 0.1 mm resolution. The drawings are stamped *for information only* and state no
tolerances, so this is agreement with a nominal, not a fit. The foot under the holder is still a
visual stand-in for the base, and the thumbscrew's neck/knob split and neck radius are not
dimensioned on the drawing.

Reference material checked 2026-09-15:

- [Thorlabs continuous rotation mounts](https://www.thorlabs.com/NewGroupPage9_PF.cfm?ObjectGroup_ID=246):
  RSP1 accepts 1-inch optics; a knurled rim and 2-degree scale motivate the ring detail.
- [Thorlabs optical posts](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=1266&pn=TR75%2FM-JP-P5):
  stainless steel construction and a 3.2 mm transverse hole motivate the post material and cross hole;
  the cross-hole station now comes from drawing 0331 rev J.
- [Thorlabs POLARIS-K1 catalog](https://www.thorlabs.com/catalogpages/obsolete/2023/POLARIS-K1.pdf):
  stainless steel front/back plates motivate the distinct POLARIS material.

## Verification

`tests/test_hardware_render.py` checks preservation of basic geometry and optical pose, inactive
optics on render details, viewport hiding, previously hidden parts, repeated preparation without
mesh growth, cleanup, automatic dressing and render/reset integration. `tools/inspect_mounts.py`
provides five camera views per mount. The existing units regression must also pass.

## Expanded catalog (33 assets)

All 17 original assets are rebuilt using the same detail pipeline as the 16 additions.
New generic families: KINEMATIC_05/2, ROTATION_05/2, LENS_CELL_05/1/2, XY_1, XYZ_1,
PRISM_PLATFORM, IRIS_1, CAGE16/60 and TUBE_SM05/SM1/SM2. Generic travel limits are
design estimates. Support selection is included in those presets; it is not a separate manual step.

Cage rods, rail locks/posts, tube barrels/retainers, gimbal pivots, flip hinges, camera mounts
and the new platform bodies now receive turned surfaces or fasteners in addition to materials.
Use `--render` after the asset output directory to also generate a thumbnail for every product
and embed it in the Blender asset. `catalog.json` records SHA-256, part counts and detail features;
`tests/test_hardware_assets.py -- DIRECTORY` checks catalog completeness and reloads every file.

Additional reference: [Thorlabs cage system standards](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=179&partnumber=CP1LD56)
describes the 16/30/60 mm families and their nominal half/one/two-inch optics.
[Thorlabs lens tubes](https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_ID=3383)
describes the SM2 family. Our model geometry and platform travel remain approximate.

The expanded catalog excludes shared breadboard feet from individual assets. Cage assets contain two
plates and four rods. Oversized optics are rejected before a generic preset changes any state.
The studio ground is placed below the complete bench, and every generated thumbnail checks all
component bounds against the camera frame. Support tests explicitly check post-to-mount contact,
not merely proximity between parts of an otherwise floating subgroup.

## Mechanical assembly training roadmap

The existing visual assets are not yet verified assembly-training models. The [product evidence inventory](mechanics/product-evidence.md) covers all 33 presets, selected real-product targets, subpart roles, source conflicts and missing dimensional evidence. Machine-readable records are in [product-evidence.json](mechanics/product-evidence.json); no runtime compatibility claims are made from this inventory. The sequential implementation status is tracked in [the assembly plan](../plans/optomechanical-assembly.md).
