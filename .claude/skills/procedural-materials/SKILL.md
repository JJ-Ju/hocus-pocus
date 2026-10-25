---
name: procedural-materials
description: Author detailed procedural materials and textures for game assets in Houdini 22 through the HocusPocus MCP tools, the way senior material artists work in Substance Designer but in Copernicus and MaterialX — reference and real-world scale first, height built large to small, normal/AO/curvature derived from it, colour and roughness driven by masks, a story layer of wear and dirt, tiling, PBR-correct values, trim sheets and decal atlases, baking mesh maps, correct file encoding, and hookup into Karma. Use when an asset needs real materials or texture sets, a trim sheet, a decal or window atlas, or baked maps.
---

# Detailed procedural materials and textures

The method for making materials that hold up close, authored procedurally in Copernicus (COP
networks) and used in MaterialX materials rendered by Karma or exported to an engine. Every
node and parameter name here was checked in Houdini 22.0.466. The graphs in `scripts/` cook
headless and write correct files.

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
     (the default angle mode ignores `dir`).
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
- **Streak and distort direction ignored** unless `dirtype` is coord.
- **Tile-pattern shapes stretch with the cell.** Circles in non-square cells become ellipses;
  compensate with `hscale`/`vscale`.
- **Multi-output nodes:** wire by output index or name (`tilepattern` `id` is output 1;
  `shapescatter` `result`). `hextile` takes the texture in its `textotile` input, not input 0.
- **First cooks are slow** because they include OpenCL compilation (grunge nodes up to about
  3 s at 2K). Later cooks are fast.
- **One licence.** A headless Houdini with an Indie licence can fail to start while a GUI
  Houdini holds the seat; retry, or reuse the running session.
