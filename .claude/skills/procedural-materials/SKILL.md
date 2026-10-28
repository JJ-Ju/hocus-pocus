---
name: procedural-materials
description: Author detailed procedural materials and textures for game assets in Houdini 22 through the HocusPocus MCP tools, the way senior material artists work in Substance Designer but in Copernicus and MaterialX — reference and real-world scale first, height built large to small, normal/AO/curvature derived from it, colour and roughness driven by masks, a story layer of wear and dirt, tiling, PBR-correct values, trim sheets and decal atlases, baking mesh maps, correct file encoding, and hookup into Karma. Use when an asset needs real materials or texture sets, a trim sheet, a decal or window atlas, or baked maps.
---

# Detailed procedural materials and textures

The method for making materials that hold up close, authored procedurally in Copernicus (COP
networks) and used in MaterialX materials rendered by Karma or exported to an engine. Every
node and parameter name here was checked in Houdini 22.0.466. The graphs in `scripts/` cook
headless and write correct files.

**Read before authoring:**
- [references/realism.md](references/realism.md) for variation, weathering physics and
  clustering;
- [references/weather-and-use.md](references/weather-and-use.md) for where water, wind, sun,
  people and industry act;
- [references/micro-noise.md](references/micro-noise.md) for non-uniform grain, with patterns
  by surface;
- [references/layering.md](references/layering.md) for height blending, the stack order,
  normal blending, packing, and what to bake versus layer in the shader;
- [references/concrete.md](references/concrete.md) for concrete, bare or under a coat: the
  finish per element, the formwork module, the layer stack, recipes and the engine path.

This file only summarises them. Only when the brief asks for a painted or anime-background look,
also read [references/stylisation-anime.md](references/stylisation-anime.md): an optional
profile switched on over the realistic material, with a Copernicus post in
`scripts/build_anime_post.py`.

Companion skills:
- **`procedural-assets`:** where materials sit in a kit or generator, and trims versus tiling
  per piece.
- **`procedural-mesh-damage`:** geometric chips and breaks that the material must answer,
  for example primer or bare concrete inside a chip.

## The method

Senior material artists build every material in the same order.

1. **Reference and scale.**
   - Gather photographs of the real surface, including close-ups of its edges, joints and
     wear.
   - Decide the tile's real-world size before any node. At 512 px/m a 2K tile covers 4 m; at
     1024 px/m it covers 2 m.
   - Size every feature from that: a 1.2 × 0.6 m formwork panel on a 2.4 m tile is half the
     tile wide.
2. **Height first, large to small.** Height is the material's brain. Every other map comes
   from it or from masks made alongside it.
   - *Large forms:* the pattern (panels, bricks, tiles, seams) and per-element variation
     (height, tilt).
   - *Medium forms:* edge wear, waviness, bevels, chips, erosion.
   - *Small forms:* pits, grain, pores. Keep them out until the large and medium forms read.

   Judge each step in grayscale before going on.
3. **Derived maps.** Normal, AO and curvature come from the height (`heighttonormal`,
   `heighttoambientocclusion`, `curvature`). These and the pattern's element ids are the
   masks for everything that follows.
4. **Material definition.**
   - Decide metal or non-metal per area.
   - Base colour and roughness come from masks, never from raw noise.
   - Hue and value variation per element is subtle.
   - Judge colour with roughness held constant, and roughness with colour held black.
   - Roughness deserves as much work as colour: a flat roughness reads fake.
   - Keep AO out of base colour, except a short cavity term if the engine wants it.
5. **Story.** Wear and dirt where they would really happen: stains below fixings and holes,
   leaks running down, paint chipped at edges to the layer beneath, dirt in recesses, polish
   where hands touch. Mask = geometric mask (curvature, AO, height, element edges) × breakup
   noise, then levels. Cap each layer around 60% coverage, and leave quiet areas.
6. **Check.**
   - Tiling, in a 3×3 repeat.
   - Values inside PBR ranges.
   - A grayscale read.
   - A downsampled read at 1/4 and 1/8, which is what survives at distance.
   - A render on a plane and a sphere, then on the real asset, at the camera distances that
     matter.

**What makes a material look procedural**, and how seniors avoid it:
- uniform noise over every surface and every edge;
- the same detail density everywhere;
- one seed across many surfaces;
- an overloaded base pattern whose repetition shows.

Add noise and then pull it back so detail sits only where it belongs. Vary seeds per surface.
Place a few hero elements by hand, and check repetition in a real scene.

## Values

Copernicus works in linear; the sRGB numbers are what land in a PNG.

| Material | Base colour | Roughness | Metallic |
|---|---|---|---|
| Fresh concrete | ~0.51 linear (~189 sRGB); aged darker | 0.75–0.95 | 0 |
| Asphalt | 0.02 fresh to 0.08 worn linear | 0.85–0.95; polished aggregate 0.6–0.75 | 0 |
| Iron, steel | (0.56, 0.57, 0.58) linear | 0.3–0.6 bare | 1 |
| Painted metal | the paint colour | gloss 0.3–0.55, matte 0.6–0.8 | 0 |
| Rust | dark orange-brown | 0.8–0.95 | 0 |
| Brick / mortar | per-brick ramp near 0.3–0.48 red | 0.7–0.9 / 0.85–0.95 | 0 |
| Glazed tile, glass | — | 0.02–0.25; dirt 0.4–0.8 | 0 (glass IOR 1.5) |

Hard limits:
- Non-metal base colour 30–240 sRGB (50 strict).
- Raw metal 180–255 sRGB.
- Metallic close to binary: grey only for dirt or oxidation over metal.
- Dielectric F0 0.04.

Roughness ranges are common artist practice, not measurements. Concrete, asphalt and iron
values are Unreal's measured figures.

## Workflow in Copernicus

1. **Network.** A `copnet` with `setres` and `res1`/`res2` (2048 for a 2K set), `setborder`
   with `border` = wrap for tiling, and `setprecision` with `precision` = b32. All noises tile
   by default (`dotiled`, `tilesize` (2,2)): the image spans −1..1, two units across.
2. **Start from a template, or build.** `scripts/cop_lib.py` has tested starting graphs:
   - `build_concrete_panels`: formwork panels, tie holes, pitting, leaks;
   - `build_painted_steel`: seams, edge rivets, paint chipped to rust;
   - `build_brick`: stretcher bond, per-brick variation, slope-eroded edges, mortar.

   Each also gives `net`, `mk`, `w`, `normal_scale` and `write_map` helpers. Run one with
   `houdini_python`, then refine the graph with `edit` and `inspect`. The templates are
   scaffolds: they get the structure and encoding right, and are too plain to ship as they
   are. Add the macro variation, the second and third detail sizes, and the story layer your
   reference shows.
3. **Height** with patterns, shapes and noises; combine with `blend` (`mode` add, subtract,
   multiply, max, min; the `mask` input or parm is the opacity). Normalise with `equalize`
   (mode stretch).
4. **Derived maps.**
   - **Normal:** `heighttonormal` with `scale` = relief depth (m) ÷ (tile width (m) ÷ 2),
     usually exaggerated 1.5–3×. A scale of 8 on a 2 m tile is far too strong.
   - **AO:** `heighttoambientocclusion` (`heightscale`, `viewradius`).
   - **Curvature:** `curvature`. Check its range with a `statistics` COP and stretch it to 0–1
     (`equalize`) before writing 8-bit.
5. **Masks and colour.**
   - Element ids: `tilepattern`'s `id` output into `randommono` / `randomrgb` (the
     flood-fill-to-random equivalent).
   - Edge bands: `feather` (`unitdist`, `includeborder`).
   - Thresholds: `remap` with `op` threshold.
   - Colour ramps: `monotorgb` with a `ramp`.
   - Composites: `blend` with a mask.
6. **Story layer.**
   - Downward streaks: `streakblur` and `distort` with **`dirtype` = coord and `dir` = (0, −1)**
     (the default angle mode ignores `dir`). `streakblur` also needs **`bias` 1**: at the
     default 0 it smears up as well as down.
   - Grunge set: `grunge_leakingstreaks`, `grunge_drips`, `grunge_rust`,
     `grunge_rustysurface`, `grunge_moisture`, `grunge_moldspots`, `grunge_wipetrails`.
   - Slope blur (eroded edges): `slopedir` into `distort`'s `dir` input (`streak` min).
7. **Write.** `write_map` in `cop_lib.py` applies the rules: base colour with the default
   conversion; normal, packed masks and other RGB data with `colorconversion` = raw; height
   and normal at `size1` = int16. A wrong normal encoding is silent: a flat normal written
   sRGB comes out (188, 188, 255).
8. **Into a material.** Either route works headless and in Karma:
   - **Texture Material Library LOP** (`texturemateriallibrary`). COP nodes inside it wire
     into its `usdmaterial1` by input index: 0 base colour, 1 metalness, 3 roughness,
     12 bump height, 13 normal, 15 opacity. Assign with `assign1` / `geoprims1`.
   - **Material Library with MaterialX:** an `mtlximage` whose `file` is `op:/img/<net>/<null>`
     (Houdini appends `[1]`), wired into `mtlxstandard_surface`. For an engine, use the
     written PNGs instead.

   When reading data maps back with a File COP, set its `colorspace` to raw.
9. **Check** (see the method): tiling at 3×3 (`setvistile`/`vistile` on the network, or a
   `look` of a tiled plane), value ranges (a `statistics` COP),
   grayscale (`mono`), downsampled (`resample`), a Karma render on a plane and a sphere
   (`previewmaterial`, `geotype` sphere or shaderball), then on the asset.

## What makes it read as real

The test renders that looked most CG had one albedo value, one roughness and one texture
across the whole facade, with only the streaks placed. Fixes, in order of effect (numbers in
[references/realism.md](references/realism.md)):

1. **Weather by the physics of water.** Rain first cleans, then soils. The top floors get the
   most rain: open faces there wash paler, and the streaks under top-floor and parapet
   features are the longest and strongest. Lower floors carry more sheltered grime. Inside
   corners collect water and dirt. Streams recur at the same spots: the ends of sills,
   window-base corners, where horizontal meets vertical, below fixtures (longer under bigger
   projections). An old wall shows both dark streaks and pale washed ones, plus a jagged
   rain-shadow dirt line, and a damp splash band at the base. Vary every streak's spacing,
   length, width, intensity and colour, and build large stains from layered opacities
   ("Streak variety" in [references/weather-and-use.md](references/weather-and-use.md)).
2. **Cluster, with a background.** About 80 % of each notable layer sits on 15–25 % of the
   area, at a cluster scale at least as large as the frame. Every layer keeps 10–20 % of its
   strength elsewhere. This holds at the micro scale as much as the macro (item 10). Multiply cause × large clusters × medium × small, then threshold. Check
   it with statistics: about 70–80 % of the facade within ±3 % of the base value.
3. **One cause field for every layer.** Damp, streak, roughness, algae, rust and peeling read
   the same source.
4. **Roughness from causes.** Damp is darker and smoother; dust on top faces is rougher;
   hand contact is polished; a repaint patch differs mostly in sheen.
5. **Albedo variation at three scales:** macro 5–30 m ±6–12 % value, meso per bay ±3–6 %,
   micro ±2–4 %. Fade the sunny side. "Clean" is not flat: a fresh wall still has roller laps,
   batch shifts and dust. Concrete is never one value either.
6. **Dirt is a colour.** Lerp toward soot brown, green-black biofilm or rust orange, never a
   grey multiply.
7. **No visible repeat.** Hex-tile the tiling maps (`mtlxhextiledimage`,
   `mtlxhextilednormalmap`, COP `hextile`), and add a per-bay tint from an id primvar.
8. **Edges first, streaks from sources.** Weather and wear concentrate at arrises and corners.
   Every streak starts at a feature: a sill end, the low point of a top edge, a top with no
   drip, a fixing, the lower lip of a chip. It is full strength at the source, widens and
   fades. Painted steel fails where water sits: rail tops, junctions, post bases, door
   bottoms. Worn and chipped edges read **lighter** than the face around them: the break
   exposes clean concrete or primer, while the face carries soot and grime. That is how
   environment concept art reads edges. Light catching an edge comes from the shader and the
   bevel, never baked into the albedo. See
   [references/weather-and-use.md](references/weather-and-use.md).
9. **Touch and traffic.** Touch points sit at code heights and wear as bands and strips (a
   door's latch edge, a rail's top, one or two lift buttons). Floors wear in lanes from the
   entrances. One or two hot points take most of each layer.
10. **The micro scale clusters too.** Fine grain is Gaussian noise times an amplitude field
    from the causes. It is denser at the top of each pour, sharper at fresh breaks, and
    flattened and dirt-filled where worn. Use clustered scatter with power-law sizes for
    discrete features, and check the 90th/10th percentile spread of local contrast (target
    3–6). See [references/micro-noise.md](references/micro-noise.md) for the per-surface
    catalogue.

## Story on tiling kits: in the shader

A tiling texture repeats wherever the kit repeats, so wear placed by the building itself
(streaks below this ledge, grime at this base) cannot live in it. Keep the material in the
tiling maps and put the story in the shader:
- The generator writes per-face primvars it already knows. In the danchi test these were
  `stop` (the height where water starts on that face), `slen` (streak length), `wexp`
  (exposure) and a lit or occupied flag.
- The shader builds each layer from world position and those primvars. For example, a
  streak is a vertically stretched fractal × a fall-off below `stop` × exposure.
- A low-frequency patch mask over every layer (a fractal at about 0.05–0.1 per metre,
  through `smooth`) keeps whole stretches clean. Without it every ledge streaks the same,
  which is the uniform-detail failure.
- Link each layer's amount to an HDA parm, so weathering is a control and not baked in.
- Read the generator's cause points too. Damage hotspots (`damage_hot`, `damage_halo` from
  the `procedural-mesh-damage` cluster mask) and facade stories (a leak, a neglected flat) as
  primvars let edge wear, grime, streaks and rust sit where the chips and the cause are.

For a unique piece that is unwrapped (not tiling), the same masks can be rasterised into
UV space instead (`rasterizesetup` `space` uv, then `rasterizegeo`), which an engine needs
when its shaders cannot read the primvars.

## Trim sheets, atlases, baking

- **Trim sheet:** `tilepattern` with `useexpr` on and its row expression (`[row_offset]
  [row_height] | [col_width …]`). Use power-of-two row heights; bevel each strip with
  `feather` so 90° geometry edges read rounded. Give each strip its own material through the
  `id` output (`compareblend`, `idtomono`).
- **Decal atlas:**
  - Elements placed with `xform2d` or `crop`.
  - Text with the `font` COP.
  - Markers with `sdfshape` (arrow, cross, chevron).
  - Leaks from grunge × a vertical `ramp`.

  Pad with `extrapolateboundaries` so mips do not bleed black. Pack channels with
  `channeljoin`.
- **Baking mesh maps:** `bakegeometrytextures::2.0` with low, high and optional cage inputs
  from `sopimport`. Turn maps on with its `bake*` toggles and set `tracingmode` (surfacenormal,
  cagemesh, singlemesh). A ROP on a bake output that is not enabled fails with "Could not
  determine source layer sizes".
- **Geometry attributes to UV-space maps:** `rasterizesetup` (`space` uv) then
  `rasterizegeo`, for placement-dependent masks such as streaks below a ledge on a unique
  piece.

Details, the Substance-to-Copernicus node map and per-material recipes are in
[references/copernicus.md](references/copernicus.md).

## Traps

- **RGB data written sRGB.** `rop_image` encodes RGB layers to sRGB by default. Set
  `colorconversion` raw for normals and packed masks.
- **8-bit height bands.** Use `size1` int16 for height and normal.
- **Streak and distort direction ignored** unless `dirtype` is coord; `streakblur` is
  centred (both ways) unless `bias` is 1.
- **`fractalnoise` stretch and spread.** `elementscale` does nothing unless
  `elementsizetype` is 1 (Per-Component Controls). The noise around 0.5 has a std of only
  about 0.076 (p1–p99 0.31–0.70), so a factor written as if it filled 0–1 gives about a
  quarter of the intended variation. Scale by the measured spread, or `equalize` first, and
  measure the result per band.
- **RGBA data masks.** `rop_image`'s default PNG alpha mode (token premult) divides RGB by
  A; write data with the token unpremult (label "Raw"). Karma's `mtlximage` multiplies RGB
  by A when it reads an RGBA PNG, so keep data masks RGB or one per file.
- **Grunge masks saturate at their defaults.** `grunge_rust` and its kin cover large areas
  at the default coverage: rust blotches on every door. Threshold them sparse and check
  coverage with `statistics`: a painted steel door wants a few per cent of rust, not a
  third.
- **SOP `Cd` in MaterialX** arrives as the primvar `displayColor`; `geompropvalue "Cd"`
  reads black in Karma.
- **Tile-pattern circles stay round** in non-square cells at the default `useaspectratio` 0,
  sized to the smaller side; `useaspectratio` 1 stretches them. Outside a shape the `id` is
  invalid, and `randommono` gives all those pixels one shared value unless `zeroinvalid` is 1.
- **Multi-output nodes:** wire by output index or name (`tilepattern` `id` is output 1;
  `shapescatter` `result`). `hextile` takes the texture in its `textotile` input, not input 0.
- **First cooks are slow** because they include OpenCL compilation (grunge nodes up to about
  3 s at 2K). Later cooks are fast.
- **One licence.** A headless Houdini with an Indie licence can fail to start while a GUI
  Houdini holds the seat; retry, or reuse the running session.
