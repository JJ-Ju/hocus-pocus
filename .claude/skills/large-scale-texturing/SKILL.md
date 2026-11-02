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
  `docs/redesign/research/tiling-and-distribution-algorithms.md`.

Companion skills:
- **`procedural-materials`:** authoring the tiling sets, trims and decal atlases in Copernicus; its
  `references/weathering-rules.md` decides where weathering goes.
- **`procedural-assets`:** the kit, its UVs (trim rows, world-scale tiling) and engine export.
- **`procedural-mesh-damage`:** geometry damage; small damage marks go to decals, not geometry.

## The method

1. **Fix the density first.** Pick the base texel density per surface class from the camera (table in
   the reference). Every tiling set, trim and decal is authored to it; masks are not (they only say
   where).
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
7. **Preview in an engine mirror**: a numpy compositor that implements the same maths as the shader,
   on geometry captured at the review density (`crop_capture.py`), so every review image is what
   the engine would show.
8. **Check** (T1-T3 below) and keep the budgets.

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
| T1 density | every detail tile's px/m; the coat's detail | ≥ 1,000 px/m for close-ups (≥ 512 third person) |
| T2 no tile period | correlation coefficient of the high-passed luminance at each tile period, minus its ring median, on open wall at 200 px/m | ≤ 0.15 (plain repeating tiles score about 0.98, hex-tiled about 0.00) |
| T3 amounts kept | the fine composite box-filtered back to the mask density, against the coarse composite, on wall 2 cm or more from other surfaces | mean within 1 ± 0.03; 5th-95th percentile within 0.85-1.15 |
| Budget | unique masks per building; shared library | ≤ 40 MB per building; ≤ 128 MB shared (Godot Mobile: 10 MB, textures ≤ 4096) |
| Parity (release) | numpy mirror against an engine render of the same crop | mean ΔE00 ≤ 2 |

`scripts/weathering/wx_texcheck.py` runs T1-T3 on a weathered build.

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
- Neither shader has been run in an engine on this machine yet: check parity against a numpy crop
  before trusting either.

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

## Scripts

- `scripts/layered_facade.gdshader` — Godot 4 spatial shader: coat, masks, hex tiling, band sampling,
  the edge rule, the growth continuum ramp.
- `scripts/layered_facade_ue.hlsl` — the same functions for an Unreal Custom node.
- In the repo: `scripts/weathering/wx_detail.py` (tileable synthesis by spectrum, equalisation,
  hex tiling with the histogram-preserving blend, band sampling, refinement),
  `scripts/weathering/wx_hires.py` (the engine-mirror compositor), `scripts/weathering/wx_export.py`
  (masks, tint, growth stage, budgets), `scripts/weathering/wx_texcheck.py` (T1-T3), and
  `examples/danchi/weathering/crop_capture.py` (geometry at the review density, hython).
