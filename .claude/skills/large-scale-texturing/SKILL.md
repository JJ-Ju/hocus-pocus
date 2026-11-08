---
name: large-scale-texturing
description: Texture very large architecture and environment assets (buildings, estates, walls, bridges, big props) at game fidelity for Unreal Engine 5 and Godot 4 — tiling materials sampled without visible repetition (hex tiling, histogram-preserving blends), trim sheets for edges, joints and mouldings, decals for discrete marks, low-res rule-driven masks revealed against high-res tiling detail (the coverage-preserving edge rule), UDIM and virtual-texture decisions with memory budgets, an engine-mirror preview compositor, and the checks (texel density, no tile period, coarse amounts kept). Use when an asset is too large for unique textures at game texel density, when textures read low-res or blurry up close, when weathering or dirt was baked into one sheet, or when choosing between tiling, trims, decals, masks and UDIMs.
---

# Texturing large architecture at game fidelity

A building is too big for unique texels. The south front of a ten-storey slab block (82 × 36 m) is
about 2 GB of compressed unique PBR texture at 512 px/m, and 17-25 GB for the whole building at
1,024 px/m. Nothing that size ships. So modern pipelines **split** the look:

| What | Carrier | Density | Why |
|---|---|---|---|
| The surface's own material (coat, concrete, brick, paint, metal) | tiling sets, sampled without repetition | 1,024 px/m (first person), 512 px/m (third person, background) | shared, so any density is cheap |
| Edges, joints, sills, copings, drip grooves, mouldings | trim sheets (strips along U) with bevel normals | same as the tiling sets, ±25 % | crisp lines at no unique cost |
| Discrete marks: rust runs, leaks, cracks, salt blooms, spall halos, patches, signs | decals from one atlas | ≥ the base density; soft marks ≥ half | placed by rules, share one texture |
| Where and how much each weathering layer is | low-res unique masks in facade space | 25-50 px/m | a few MB per building |
| Big unique hero surfaces | UDIM or virtual textures | only when the budget allows | rarely worth it for walls |

The masks carry the **story** (this wall's streaks, this foot's splash band); the tiling detail carries
the **look** up close. A mask at 2 cm per texel gets crisp 1 mm edges by being **revealed against the
detail's own height** — the edge rule below — so marks have sharp, natural boundaries without unique
high-res texels. One unique 50 px/m albedo sheet, upscaled, is the failure this skill exists to
prevent: it reads as "very, very low res" at street level, and a reviewer will also judge the
*distribution* wrong, because every mark is a blurry 2 cm blob.

**Read before authoring:**
- [references/texturing-at-scale.md](references/texturing-at-scale.md): densities, budgets, the
  stack per surface class, mask packing, trims, decals, UDIM and virtual textures, engine limits.
- [references/tiling-and-blending.md](references/tiling-and-blending.md): the algorithms with formulas
  and pitfalls — hex tiling, histogram-preserving blends, band sampling for directional detail,
  the edge rule, mask upsampling, mip handling, slope blending, scatter, repetition tests.
- The research behind them: `docs/redesign/research/texturing-at-scale.md` and
  `docs/redesign/research/tiling-and-distribution-algorithms.md`; for delivery and review,
  `texture-and-material-standards.md` (encodings, import settings, mips, streaming, engine limits),
  `art-review-and-qa.md` (player views, magnification, debug views, motion) and
  `surface-detail-techniques.md` (mesh-map masks, paint stacks, rust anatomy, what reads at each
  distance). The index, with each note's open and parked actions: `docs/redesign/research/README.md`.

Companion skills:
- **`procedural-materials`:** authoring the tiling sets, trims and decal atlases in Copernicus; its
  `references/weathering-rules.md` decides where weathering goes.
- **`procedural-assets`:** the kit, its UVs (trim rows, world-scale tiling) and engine export.
- **`procedural-mesh-damage`:** geometry damage; small damage marks go to decals, not geometry.

## The method

1. **Fix the density from the player's camera first.** Write the metrics sheet before any texture:
   the engine and its FOV axis (Unreal 90° horizontal; Godot 75° vertical by default), the screens
   (1,920 and 3,840 px wide), eye height 1.6 m, and the **nearest approach of each surface class**
   (entrances and stair cores about 0.5 m, walkway walls 0.5-1 m, balcony fronts from the street
   5-15 m, a facade across a courtyard 20-40 m). The screen's density there is
   `p = W / (2 tan(HFOV/2) d)`; each detail carrier needs `p / t ≤ 2` (check T0). Every tiling set,
   trim and decal is authored to that density; masks are not (they only say where).
2. **Split every look into the five carriers above.** Ask of each feature: is it the surface (tiling),
   a line (trim), a mark (decal), or an amount over the wall (mask)? A weathering layer is usually a
   mask *plus* a tiling detail it is revealed against.
3. **Build the tiling sets** at the base density, tileable, with an **equalised** height (uniform
   histogram) for every detail a mask will be revealed against. Directional detail (run-off
   rivulets, roller laps) is never rotated.
4. **Sample without repetition.** Hex tiling for stochastic content; the histogram-preserving blend
   where coverage thresholds must stay exact; per-band offsets (blended across bands only) for
   vertical rivulets; a random offset per real panel, with seams under real joints, for structured
   content (formwork, stone).
5. **Reveal masks with the edge rule** (coverage kept, zero stays zero), and fade to the mask alone
   past about 25 m so distant views keep the amounts the masks were tuned to.
6. **Put lines in trims and marks in decals**, placed by the same rules as the masks.
7. **Review the product, from the player's camera.** A numpy mirror compositor (`wx_hires.py`, on
   geometry captured at the review density with `crop_capture.py`) is a stand-in, not the product:
   it hides what the shaders do differently (see Traps). Lead every review with player views at 1:1
   screen pixels (never scaled), each labelled with its renderer (50 px/m sheet, numpy mirror,
   Karma, Godot, Unreal) and its screen px/m; then a magnification map, grazing, up and down views,
   and a lighting set. Render the golden crop in the target engine every round once the shaders
   exist, and keep it within mean ΔE00 2 of the mirror. An image at the texture's own density is a
   diagnostic: a 50 px/m sheet viewed at 50 px/m is 1:1 by construction, which is how the danchi's
   one-sheet texturing passed four review rounds.
8. **Check** (T0-T3 and the lint below, run by the pipeline before any review page) and keep the
   budgets.

## The edge rule (coverage-preserving reveal)

For a mask amount `a` at this pixel, the layer's local opacity `pk` (the mask's smoothed local
maximum) and the detail's equalised height `u` (uniform 0-1):

```
m  = clamp(a / pk, 0, 1)
hw = max(min(w / 2, m, 1 - m), 5e-5)            # the soft edge narrows at m = 0 and 1
c  = pk * clamp((u - (1 - m)) / (2 hw) + 0.5, 0, 1)
c  = lerp(c, a, fd)                             # fd = saturate((distance - 8 m) / 17 m)
```

The mean of `c` over the detail is exactly `a`, and a zero mask stays zero. The rule in
`procedural-materials/references/layering.md`'s older form (`(a - (1 - h)) * k + 0.5`) is biased:
its mean is `a + w(a - ½)`, so a 10 % mask covers 6 %, and a 0 mask still puts specks where `h` is
highest. Films (soot, dust haze) are not revealed but **modulated**, mean kept:
`a * max(1 + k g, 0)` with `g` a Gaussian detail and `k` about 0.4. Mixing the coat's troughs into
`g` (dirt settles in the relief first) is what makes grime sit *in* a textured coat instead of
flattening it.

## Checks

| Check | Measure | Pass |
|---|---|---|
| T0 magnification | screen px per metre at each surface class's nearest approach (4K, the engine's FOV) over each detail carrier's px/m | ≤ 2 for every carrier holding visible detail; masks may exceed it only where a detail reveals their edges (at 1 m on 4K a 50 px/m sheet is 38×) |
| T1 density | every detail tile's px/m; the coat's detail | ≥ 1,000 px/m for close-ups (≥ 512 third person) |
| T2 no tile period | correlation coefficient of the high-passed luminance at each tile period, minus its ring median, on open wall at 200 px/m | ≤ 0.15 (plain repeating tiles score about 0.98, hex-tiled about 0.00) |
| T3 amounts kept | the fine composite box-filtered back to the mask density, against the coarse composite, on wall 2 cm or more from other surfaces | mean within 1 ± 0.03; 5th-95th percentile within 0.85-1.15 |
| Budget | unique masks per building; shared library | ≤ 40 MB per building; ≤ 128 MB shared (Godot Mobile: 10 MB, textures ≤ 4096) |
| Parity (every round, once the shaders exist) | numpy mirror against an engine render of the same golden crop | mean ΔE00 ≤ 2; normal angle ≤ 5° |
| Texture lint (every export) | sides; encodings against the engine import files; albedo percentiles per class; normal Y tag | sides a multiple of 4, a power of two when streamed, ≤ 4,096 for Godot Mobile and web; settings as in the import table below |
| Carriers | every layer the gate measures or the mirror draws | each has a mask channel, a decal kind with an atlas cell, or a trim, or the export fails |

`scripts/weathering/weather_gate.py texture <build>` runs T0-T3 (`wx_texcheck.py`) and the close-up
parts of the material rules; the danchi pipeline (`pipeline_j.py`) runs it on every build and accepts a
build only when it passes. A check nothing runs is advice, not a check. For the danchi, parity, the texture lint's
encoding clauses and the carrier check do not run yet: they are parked until its engine round (the
research index, `docs/redesign/research/README.md`); the export's size lint does run.

## Engine hookup

- **Facade-space masks** are sampled by planar projection: `f = (dot(P - origin, U), dot(P - origin, V))`
  in metres, `uv = f / size`. Instanced kit pieces then share meshes and still read their wall's masks.
- **Unreal 5:** tiling sets as normal textures (BC7/BC5/BC4) with mips; masks as streamed textures,
  switching to streaming virtual textures only past about 300 MB of masks per estate; decals as
  non-Nanite mesh decals (DBuffer) from one atlas; a material function per layer (Custom node:
  `scripts/layered_facade_ue.hlsl`).
- **Godot 4:** the same textures; masks per facade or in a `Texture2DArray`; Decal nodes only for
  about 50 hero marks (512 clustered elements in view; 8 decals per mesh on Mobile), mesh decals
  otherwise; the spatial shader `scripts/layered_facade.gdshader`.
- **Import settings are part of the asset** (engine defaults are wrong for this data: Unreal imports
  a new texture as sRGB BC1/BC3, and Godot puts RGBA masks into DXT5, where three masks share one
  colour line per 4 × 4 block). Write them with the export and check them:

  | Class | Unreal | Godot 4 |
  |---|---|---|
  | weathering masks (RGBA, linear) | BC7, sRGB off, Never Stream or a facade UV1 | VRAM compressed, High Quality (BPTC), sRGB off, Fix Alpha Border off |
  | reveal details (R8, equalised) | uncompressed G8, own mip chain (Leave Existing Mips) | lossless or uncompressed, own mips (DDS) |
  | colour sets (base colour) | BC1/BC7, sRGB on | VRAM compressed, sRGB |
  | normals | BC5, Flip Green on Copernicus (OpenGL Y+) maps | `hint_normal`, as authored (Y+) |
  | ramps (growth stage) | uncompressed, no mips, clamp | lossless, no mips, `repeat_disable` |

- **Unreal streaming cannot follow world-projected lookups:** it assumes UV0 at scale 1 and
  under-streams a texture that repeats every T metres by log2 T mips (about 2 for a 3.6 m coat, 6 for
  an 82 m mask). Write facade coordinates into UV1 at export and sample the masks from it, or keep
  the masks resident (≤ 40 MB per building). Check with the texture-scale accuracy view.
- **Units and axes.** Unreal works in centimetres with Z up: divide world positions by 100 before
  any metre-based term (fade distances, tiling sizes). Godot works in metres with Y up.
- **Colour constants carry their encoding.** Godot converts `source_color` uniforms from sRGB, so a
  linear constant under that hint renders about 10 times too dark (0.094 → 0.009). Linear constants
  take no hint; sRGB ones take it.
- Neither shader had run in an engine by round J (the audit, `docs/redesign/research/research-to-practice-audit.md`
  ranks 1-1d): render the golden crop and check parity before trusting either.

## Traps (found the hard way)

- **One unique sheet at mask density.** Upscaled 50 px/m albedo reads blurry at 1:1, and every mark
  becomes a soft blob. Keep the sheet only as the masks' own preview and as the far-LOD bake.
- **A wrong triangle grid draws the lattice.** In Heitz and Neyret's `TriangleGrid` the skew is
  `(x - y/√3, 2y/√3)` (GLSL's `mat2` is column-major), and the upper triangle's weights are
  `(-z, 1 - f.y, 1 - f.x)` for the vertices `b + (1,1)`, `b + (1,0)`, `b + (0,1)`. Swapping the last
  two (an easy slip when porting) makes every vertex weight jump by up to 0.7 along the triangle
  edges: faint straight seams in a lattice, visible once contrast is stretched. Test it: sample a
  line finely and check that no vertex's summed weight jumps (danchi round I shipped this bug in
  numpy and both shaders until a 1:1 render showed it).
- **Blending heights across hex cells creases the lighting.** Barycentric weights have kinks along
  the triangle edges, so a normal derived from blended heights shows straight seams. Blend slopes
  (or normals as derivatives), rotated with each sample.
- **Mask grain becomes dots.** A mask that carries 2 cm-pixel noise (to look grainy at 50 px/m) turns
  into isolated specks when revealed. Take the local opacity from a smoothed neighbourhood (10 cm),
  blur films slightly before upsampling, and let the detail supply the grain.
- **Coverage thresholds on plain mips are wrong.** A box-filtered detail loses variance, so a 10 %
  layer shrinks to 2 % by mip 2. Re-standardise (re-equalise) every mip level of a reveal detail.
- **Directional detail must not rotate,** and a triangle grid cuts vertical streaks horizontally.
  Offset per vertical band and blend across bands only.
- **Capture conventions.** Check each view's normal sign before lighting a preview (in the danchi
  captures the south front faces +z, the north −z); a wrong sign silently drops the sun and leaves
  the capture's per-pixel normal noise as blocks.
- **Geometry at mask density.** Window frames, rails and balusters upsampled from 2 cm pixels are
  blocky; capture the geometry itself at the review density (`crop_capture.py`).
- **Repetition detectors.** A raw autocorrelation-peak ratio is noisy (plain noise scores 2); use the
  correlation coefficient at the period minus its ring median.
- **Layers on the wrong surface.** Upsample each layer over its own support (wall, steel) and mask it
  to its classes at the fine grid, or wall grime bleeds onto glass and frames.
- **The review image is not the product.** Each danchi round's review images came from a stand-in
  that hid the next defect: the 50 px/m sheet hid texel density; diffuse-only previews hide
  roughness; the numpy mirror (B-spline masks, re-standardised mips, a 10 cm local maximum, the
  generator's float stack) hides the shaders' bilinear masks, plain mips, `pk = 1.6 a` and
  plain-tiled normal. Label each image with its renderer, and compare the mirror with an engine
  render before trusting it.
- **Implicit derivatives after random offsets break mips.** Hex and band tiling offset and rotate
  each sample, so `texture()` takes its derivatives from discontinuous coordinates and picks the
  wrong mip along cell edges: thin seams that only an engine shows. Take `dFdx`/`dFdy` of the
  unoffset coordinate once and sample with `textureGrad` (`SampleGrad` in HLSL), the derivatives
  rotated with the sample (Mikkelsen's reference). Filter reveal details anisotropically.
- **The local opacity must be shipped, not guessed.** The shaders' `pk = clamp(1.6 a, 0.05, 1)`
  turns every 3-62 % mark into a 62.5 % speckle with edges as soft as the mask; export the
  smoothed 10 cm local maximum per channel and read it as `pk`.
- **Sizes that do not compress or stream.** Masks of 4,095 × 1,815 px cannot be block-compressed
  (sides must divide by 4) and Unreal does not stream non-powers of two: pad by edge extension to
  the next power of two and keep the frame in `export.json`.
- **A layer the gate measures but nothing ships.** Peeling, washed streaks, edge wear, breaks and
  black growth were measured and previewed while the export carried none of them; the carrier check
  catches that.
- **Thin members need their own space.** A 16 mm bar is under one pixel of a 50 px/m facade mask, so
  a rust run drawn in the mask faded to a tint by mid-bar, and a check counting the mask's alpha
  passed it (danchi rounds I-J: "still no rust going DOWN the vertical slats"). Draw runs per bar in
  its own coordinates (across 0-1, along in metres), at the fine stage and in the engine (member UVs,
  per-instance values), and check them at the player's 1:1 view.
- **Elevation noise crosses depth steps.** One 2D field over the elevation paints the same flakes on
  a balcony front and on the wall 1.2 m behind it. Split the paint mask at depth steps into surfaces,
  colour the surface graph so neighbours differ, and draw an independent field per colour; clip
  breaks to the surface they start on (rule P4 tests it).
- **Occlusion lines are not arrises.** An edge map that marks every bottom of a surface marks the
  line where a nearer front hides the wall behind it; chips stamped there mirror the front's own
  top arris across the step (danchi: 9-14 % of the edge pixels; breaks 13x likelier across a step).
  Keep a bottom only when the pixel below is farther or empty.
- **Projected masks give hidden surfaces the occluder's values.** A wall behind a railing samples
  the railing's mask values at the same facade coordinates (rust, bare metal, the sheen), seen from
  any angle but straight on. Give steel its own member space, or a back mask layer for hidden walls.

## Scripts

- `scripts/layered_facade.gdshader` — Godot 4 spatial shader: coat, masks, hex tiling, band sampling,
  the edge rule, the growth continuum ramp.
- `scripts/layered_facade_ue.hlsl` — the same functions for an Unreal Custom node.
- In the repo: `scripts/weathering/wx_detail.py` (tileable synthesis by spectrum, equalisation,
  hex tiling with the histogram-preserving blend, band sampling, refinement),
  `scripts/weathering/wx_hires.py` (the engine-mirror compositor), `scripts/weathering/wx_export.py`
  (masks, tint, growth stage, budgets), `scripts/weathering/wx_texcheck.py` (T1-T3), and
  `examples/danchi/weathering/crop_capture.py` (geometry at the review density, hython).
