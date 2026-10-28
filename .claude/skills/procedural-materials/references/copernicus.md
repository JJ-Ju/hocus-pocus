# Copernicus for material authoring: nodes, mapping, recipes

Verified in Houdini 22.0.466 (383 COP types). Parm names were read from nodes created in a
`copnet` under `/img`.

## Substance Designer to Copernicus

SideFX ships this mapping in its help ("Copernicus for Substance Designer users").

| Substance Designer | Copernicus |
|---|---|
| Tile Generator | `tilepattern` |
| Tile Sampler, Splatter | `shapescatter`, `curvescatter` |
| Shape | `sdfshape` → `sdftomono` |
| Levels, Histogram Scan | `remap` (`op` threshold for Histogram Scan) |
| Auto Levels | `equalize` |
| Directional Blur | `streakblur` |
| Warp | `distort` |
| Slope Blur | `slopedir` → `distort` `dir` input |
| Distance, Bevel | `feather`, `extrapolateboundaries` |
| Flood Fill (+ to Random) | `segmentbyconnectivity`, `tilepattern` `id` → `randommono` / `randomrgb` |
| Ambient Occlusion (HBAO) | `heighttoambientocclusion` |
| Base Material preview | `previewmaterial` |

## Nodes by purpose

**Network defaults** (on `copnet`, also on the Texture Material Library LOP): `setres` +
`res1`/`res2`; `setborder` + `border` (constant, clamp, mirror, wrap); `setprecision` +
`precision` (b16, b32); `setvistile` + `vistile` (preview the tile repeated).

**Patterns and shapes**
- `tilepattern`: outputs `tiles` (mono), `id`, `uv`. Parms `patterntype` (stackbond,
  stretcherbond, flemishbond, englishbond, americanbond, monkbond, herringbone …),
  `patternmode` (tilecount …), `<type>_rows`/`<type>_cols`, `inset`, `basictype`,
  `rect_round`/`rect_roundness`, `draw` (gradient …), `value_mode`/`rotate_mode`/`scale_mode`
  = varying with `*_var` and `*_seed`, `useexpr` + `expr` for trim rows.
- `shapescatter`: inputs include `stamps`, density, angle and scale; parms `stampsx`/`stampsy`,
  `scale`, `scalevariance`, `jitter`, `angle`, `density`, `blend`, `gridtype` (grid, hex),
  `linkstamps`, `dotiled`; output `result`.
- `sdfshape` (`basictype`, `circle_radius` …), `sdfblend` (union, intersect, subtract with
  smooth, round, chamfer), `sdfadjust`, `sdftomono` (`shapevaluemode`), `monotosdf`, `idtosdf`,
  `cellpattern`, `checkerboard`, `weave`, `knit`, `font` (`text`, `fontsize`, `output` mask or
  sdf), `ramp` (`cycles`, `method` repeat or mirror), `uvshape`, `hextile` (texture in
  `textotile`).

**Noise** (all tile by default: `dotiled`, `tilesize` (2,2))
- `fractalnoise`: `noisetype` (torus, perlin, worleyA, worleyB, white, alligator, sparse),
  `elementsize`, `elementsizetype` (1 = per-component; `elementscale` is ignored without it),
  `elementscale`, `oct`, `rough`, `amp`, `center`. Its output around 0.5 has a std of about
  0.076 (p1–p99 0.31–0.70), less at large element sizes.
- `worleynoise` (outputs dist1, dist2, border, center, id; `elementsize`, `jitter`),
  `cellularnoise` (`smoothedge`, `gap`, `bevel`, `mode`), `crystalnoise`, `bubblenoise` (`droop`), `phasornoise`,
  `curlnoise`.

**Grunge** (each has `elementsize`, `seed`, `dotiled`): `grunge_leakingstreaks`,
`grunge_drips` (slowest, ~3 s first cook at 2K), `grunge_rust` (`coverage`),
`grunge_rustysurface`, `grunge_moisture`, `grunge_moldspots`, `grunge_sheets`,
`grunge_wipetrails`, `grunge_layerednoise`, `grunge_galvanizedsteel`.

**Filters and warps:** `blur` (`units` image, pixels, local; `size_pixel`), `distort` (`dir`
input, `scale`, `streak` off, on, min, max, `dirtype`), `streakblur` (`dirtype`, `dir`,
`length`, `bias`: 0 centred, 1 one-sided along `dir`), `slopedir`, `feather` (`direction`, `unitdist`, `includeborder`), `dilateerode`,
`edgedetect`, `sharpen`, `median`, `smoothfill`, `extrapolateboundaries`, `xform2d`, `mirror`,
`crop`, `resample`.

**Levels and maths:** `remap` (`op` remap or threshold, `inputmin`/`inputmax`,
`outputmin`/`outputmax`, `threshold`, `ramp`), `equalize` (`mode` stretch), `clamp`, `invert`,
`quantize`, `function` (`func` trig …), `contrast`, `colorcorrect`, `hsv`, `blend` (`mode`
blend, over, add, subtract, multiply, max, min …; `mask`; `signature` f3 for colour), `average`,
`compareblend`, `maskcombine`, `constant` (`signature` f3, `f3`).

**Derived maps:** `heighttonormal` (`normaltype` signed or offset, `scale`, `kernel`,
`readoutside`), `heighttoambientocclusion` (`heightscale`, `viewradius`, `axiscount`),
`curvature` (`curvaturetype`), `normaltoheight`, `combinenormals`, `convertnormal`.

**Ids and channels:** `segmentbyconnectivity`, `randommono`/`randomrgb` (`seed` input takes
an id layer; `min`, `max`), `idtomono`, `idtorgb`, `statistics`, `channelsplit`,
`channeljoin`, `monotorgb` (`ramp`), `mono`, `layerproperties`.

**Geometry:** `sopimport` (`usesoppath`, `soppath`), `bakegeometrytextures::2.0` (inputs low,
high, cage; `bake*` toggles; `tracingmode`), `bakepreprocess`, `rasterizesetup` (`space` pos
or uv), `rasterizegeo` (inputs `camera_ref`, `geometry`), `rasterizecurves`, `geotolayer::2.0`,
`layertogeo::2.0`.

**Output and materials:** `rop_image` (`coppath` or wired input, `copoutput`,
`colorconversion` ocio, bakeocio or raw, `size1` auto, int8, int16, int32, float16, float32);
`file` (`filename`, `colorspace` ocio or raw); `previewmaterial` (a PBR preview on grid,
sphere, box or shaderball). The `output` COP is a network output, not a file writer.

## Per-material recipes

**Board-formed concrete** (`build_concrete_panels`; the fuller formed and spray-coat recipes
are in [concrete.md](concrete.md)): stackbond panels with a small `inset`
and varying value, 2 px blur on seams; tie holes as a second tilepattern of gradient circles
subtracted; broad `fractalnoise` (elementsize ~0.6) at ~15 %; pitting from `worleynoise`
dist1 → `remap` → `invert`, masked by low-frequency noise; fine grain at ~3 %; leaks by
`streakblur` of the tie holes (downward: coord mode, `bias` 1) max `grunge_leakingstreaks`; colour ramp
0.18–0.52 linear darkened by AO and stains; roughness 0.95 → 0.72 in stains. Add formwork
wood grain with a stretched `fractalnoise` (`elementsizetype` 1, `elementscale` like (1, 0.05)) or `phasornoise`
(not yet tested).

**Painted steel** (`build_painted_steel`): 2×2 panels with blurred seams; rivets as
`sdfshape` circle → `sdftomono` → `shapescatter` stamps, kept near edges by an edge band
(`feather` → `invert` → threshold); chipping = edge band × `grunge_rust` → threshold,
subtracted slightly from height; colour blends paint to rust (or primer) through chips;
roughness up in chips; metal 1 only where bare steel shows. Add per-panel tone variation,
streaks from rivets and seams, and dirt in the seams before shipping.

**Brick** (`build_brick`): stretcher bond with inset joints and rounded rects; per-brick
random from the `id` output; `feather` bevel; slope-blur erosion (`fractalnoise` → `slopedir`
→ `distort` streak min); recessed grainy mortar combined with `blend` max; colour from a
per-brick ramp over mortar grey. Add per-brick colour variation within each brick, chipped
corners, efflorescence and soot bands.

**Tiles:** square stack bond, rounded rects, grout inset; glazed tiles low roughness with a
small per-tile tilt from the id; grout dirt from AO.

**Corrugated metal:** `ramp` (`cycles` N, `method` mirror) or `function` (trig) for the
profile; `grunge_galvanizedsteel` for zinc spangle; `grunge_rust` masked by troughs and a
bottom gradient.

**Glass:** a distance-from-frame mask (`feather`, `extrapolateboundaries`) × `grunge_moisture`
or leaking streaks, raising roughness from ~0.02; keep it subtle.

**Asphalt:** aggregate from small `cellularnoise`/`worleynoise`; cracks from `worleynoise`
border → threshold → `distort`; base 0.02–0.08 linear with lighter stones.

## Checks

- Tiling: `vistile` 3 on the network; numerically, the left/right and top/bottom edge
  difference should not exceed the average neighbouring-pixel difference.
- Ranges: `statistics` on base colour (non-metal 30–240 sRGB, metal 180–255), metallic
  binary.
- Read: grayscale through `mono`; roughness alone on black; `resample` to 1/4 and 1/8 for the
  distance read.
- Render: `previewmaterial` on a sphere or shaderball, then Karma through a Texture Material
  Library LOP, against a human-scale reference and the texel density.

## Sources

- SideFX local help (Houdini 22.0.466): Copernicus for Substance Designer users, Working with
  COPs, Spaces, Normals, Cooking; node pages for distort, feather, heighttonormal,
  bakegeometrytextures 2.0, usdmaterial, texturemateriallibrary
- SideFX, what's new in Houdini 22, look development: https://www.sidefx.com/products/whats-new-in-h22/lookdev/
- SideFX talk, Baking with Copernicus: https://www.sidefx.com/learn/talks/baking-with-copernicus/
- Epic, physically based materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine
- Adobe, The PBR Guide part 2: https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2
- Joshua Lynch, material creation for games: https://80.lv/articles/material-creation-for-games
- Andy Baigent, Substance Designer workflow: https://80.lv/articles/detailed-look-at-substance-designer-workflow
- Benjamin Thomas, materials in Substance Designer: https://80.lv/articles/creating-gorgeous-materials-in-substance-designer
- Daniel Thiger, pattern creation and scattering: https://80.lv/articles/substance-basics-pattern-creation-and-natural-scattering
- Javier Perez: https://adobe.com/products/substance3d/magazine/javier-perez-takes-you-to-space.html
- Brick wall breakdown: https://gamesartist.co.uk/brick-wall
- The Ultimate Trim: https://gdcvault.com/play/1022323/The-Ultimate-Trim-Texturing-Techniques
- Texel density: https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
- Decals: https://80.lv/articles/in-depth-tutorial-creating-custom-decals-for-games
