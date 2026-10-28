# Layering and mixing materials

How technical artists build and mix layered materials, and how to do the same in Houdini 22.
Distilled from research for review 32 (full report: `docs/redesign/research/r5-texture-layering.md`).
† marks a Houdini node or parm name not yet read in a live session. *(est.)* marks practice or
inference rather than a published figure.

## Height blending is the core operation

A mask blend cross-fades regardless of the surface. A **height blend** follows the relief: sand
fills cracks first, plaster survives on the high points of brick, water pools low. This is the
behaviour of Unreal's HeightLerp, Designer's Height Blend and HDRP Layered Lit's height-based
blend.

**R1: reveal one layer against one height.** For dirt into recesses, chipped paint, moss:

```
t = 1 - a*(1+w)            # a = layer amount 0..1 (cause mask, vertex colour)
m = smoothstep(t, t+w, h)  # h = 0..1 height; use 1-h for things that fill low spots
                           # w = transition width 0.02-0.2; small = sharp
```

At a = 0 nothing shows; at a = 1 the layer covers everything; in between, high h shows first.

**R2: the "max height" trick for two or more layers with their own heights** (Mishkinis):

```
hA' = hA + (1-a)    hB' = hB + a          # bias each height by its weight
ma  = max(hA', hB') - d                   # d = blend depth, about 0.05-0.2
wA  = max(hA' - ma, 0)    wB = max(hB' - ma, 0)
out = (A*wA + B*wB) / (wA + wB)           # same weights for every channel
```

For N layers, wᵢ = max(hᵢ' − maxⱼ hⱼ' + d, 0), normalised. **Equalise every height to 0–1
first** (`equalize`), or one layer always wins.

## Stack order and operators

Build the stack in this order *(est.)*:
1. base;
2. macro variation;
3. variants (repaint, patch);
4. wear, revealing the layer beneath;
5. dirt and a film;
6. decals and hero marks.

- **Wear switches whole material sets** (primer under paint, brick under plaster), not only
  albedo.
- **A global film layer** is a 10–25 % lerp toward warm grey, modulated by the macro mask. It
  pulls a clean, saturated wall toward the real thing *(est.)*.

| Operator | Use for | Never for |
|---|---|---|
| lerp to a colour | dirt, film, rust run, paint over primer | — |
| height blend (R1, R2) | any layer with physical thickness | flat stains on smooth glass |
| multiply | an AO or cavity term if the engine wants it baked | dirt (it reads as shadow) |
| overlay around 0.5 | albedo detail around a mean | large value shifts; MaterialX in Karma (unsupported) |
| max / min | combining heights | colour |
| add | heights, sparse highlights | BSDFs |

## Normals: never lerp them

- Linear and overlay blending flatten both normal maps (Barré-Brisebois & Hill).
- **Reoriented normal mapping (RNM)** keeps detail strength across a tilted base:
  `t = base*(2,2,2)+(-1,-1,0); u = detail*(-2,-2,2)+(1,1,-1); r = normalize(t*dot(t,u) - u*t.z)`.
  Whiteout is `normalize(n1.xy+n2.xy, n1.z*n2.z)`; UDN is cheaper and loses detail on flat bases.
- For several UV sets, triplanar or decals, use Mikkelsen's surface-gradient framework.
- **When baking, avoid normal blending altogether:** blend the heights with R1 or R2 and derive
  one normal from the composite height.

## Roughness, metal, AO, packing

- **Roughness:** blend it with the same mask as albedo.
- **Metal:** use a sharp mask (small w), so grey metallic values appear only in transition
  pixels.
- **AO:** stays its own channel; never multiply it into albedo.
- **ORM packing:** R occlusion, G roughness, B metallic, written raw at 8-bit. Height for runtime
  blending goes in a spare alpha or its own raw map.

## Bake versus shader time

- **Baked composites** cost nothing at runtime, but they are unique per asset and limited in
  texel density.
- **Shader-time layers** keep tiling detail sharp.
- **Studio practice:**
  - The Order: 1886 used "90-95% tiling materials, with up to 4 runtime material layers",
    vertex-blended with height, plus decals.
  - Gears of War 4 composited dozens of layers and cooked them.
  - Embark's THE FINALS puts edge-softening, grout and leak decals where modules meet.
- **Rule:** cook what never varies per instance. Keep 2–4 height-blended runtime layers driven by
  vertex colour or masks, and put the one-off hero marks (leaks, cracks, patches) in decals.

## Engine systems, in brief

- **Unreal Substrate** layers slabs vertically (coats, varnish, wet films) or blends them
  horizontally (dirt). Material Layers blend horizontally only.
- **DBuffer and mesh decals** change base colour, normal and roughness. Mesh decals carry custom
  shapes such as leak strips and grout lines.
- **Runtime Virtual Texturing** blends objects into terrain.
- **Nanite tessellation** turns height into real displacement.
- **Vertex paint with a height blend** is the workhorse for buildings: plaster over brick, damp
  bases, moss.
- **Unity HDRP Layered Lit** has 4 layers with a height-based blend.

## Patterns that do not repeat

- **Per-element variation.** Give each tile or brick a random value, tilt and height offset from
  its id (`tilepattern` `id` → `randommono`), plus wear local to the element.
- **Anti-repetition**, by cost:
  - texture bombing;
  - hex tiling, which handles normals;
  - stochastic histogram-preserving blending (Heitz & Neyret), which suits only stochastic
    textures such as rust, moss and stone, and breaks brick and panels.
- **Streaks are structured, sourced features.** Never hex-tile them. Generate them per source
  (weather-and-use.md) and reveal them with R1 against the micro height. Each streak then breaks
  on the spray-tile mesas, fills the troughs first, and gets an irregular edge.
- **Scale ratios.** Keep about 4–8× between the macro, meso and micro feature sizes, each with
  its own mask. Only the macro layer may be in world space *(est.)*.
- **The "Substance look"** is generator edge wear on every edge and stacked grunge maps. The fix
  is less generator and more placed wear: the cause field and 80/20 clusters.

## Scale and distance

- **Texel density:** 512 px/m for distant work, 1024 px/m for close first-person; be consistent.
- **Detail maps** tile 4–10× over the base and must be mean-neutral: albedo averaging exactly 0.5
  for overlay, normals averaging flat. Otherwise brightness shifts at distance. Fade detail with
  distance and let the macro variation take over.
- **Specular aliasing:** mips average away normal detail, so roughness must rise in those mips.
  Use a Toksvig adjustment (roughness from the shortened averaged normal), or the engine's
  composite.
- **Transition width:** keep `w` at about 2 texels or more at the bake resolution, and widen it
  with distance, or transitions shimmer.

## Houdini 22

| Technique | Copernicus (bake) | MaterialX in Karma (shader) |
|---|---|---|
| R1 reveal | `remap`, `blend` (subtract, add); `remap` threshold with a ramp | `mtlxsmoothstep` (`in`, `low`, `high`), low = 1 − a·(1+w); `a` from `mtlxgeompropvalue` |
| R2 max height | `blend` add and max, then subtract, `clamp`, divide per channel | `mtlxmax`†, `mtlxsubtract`, `mtlxclamp`†, `mtlxdivide`†, `mtlxmix` |
| Mix to a colour | `blend` (mode blend, mask) | `mtlxmix` (`fg`, `bg`, `mix`), `signature` color3 |
| Mask stack | `maskcombine`: ordered layers with blend modes, blur and remap, then contrast, gamma and clamp | `mtlxmultiply`, `mtlxrange` |
| RNM | `combinenormals`, Combine Method Reoriented (also Whiteout, UDN)† | build it in tangent space before `mtlxnormalmap`, from raw images: `mtlxdotproduct`†, `mtlxmultiply`, `mtlxsubtract`, `mtlxnormalize`† |
| Height to normal | `heighttonormal` on the composite height | prefer `mtlxbump` or a baked normal. `mtlxheighttonormal` is a MaterialX convolution node the spec says may not work in ray tracing |
| Overlay detail | `blend` Overlay or SoftLight | do the maths with `mtlxmultiply` and `mtlxadd` around 0.5. SideFX: "The Compositing nodes are not supported by Karma", so not `mtlxoverlay` or `mtlxscreen` |
| Coat, wet film | — | `mtlxlayer`, with a smooth `dielectric_bsdf` on top of the surface BSDF |
| Anti-tiling | `hextile` (`textotile`) | `mtlxhextiledimage`, `mtlxhextilednormalmap` |
| Triplanar | `triplanarhextile` | `mtlxtriplanarprojection`; normals need a whiteout or RNM swizzle per axis |

**R3: a height-blended facade in MaterialX**:
1. Take two `mtlximage` sets (paint, dirty paint), each with base colour, roughness, normal and
   height, reading the data maps raw.
2. a = cause primvar (`mtlxgeompropvalue`) × a macro `mtlxfractal3d` mask.
3. m = R1 on the paint's inverted height, so dirt fills the troughs.
4. `mtlxmix` base colour, roughness and height at m; blend the tangent normals with RNM before
   `mtlxnormalmap`.
5. Optionally, layer a damp film over it with `mtlxlayer`, weighted by a damp mask.

**For an engine,** MaterialX does not travel. Bake:
- each tiling material set, with its height;
- ORM, raw;
- the masks, as vertex colour, a second UV set or a mask texture;
- a note of `w` and `d`, so the engine's height blend can match.

Unique, unwrapped pieces can bake the whole composite with `rasterizegeo`.

## Failure modes

| Failure | Cause | Fix |
|---|---|---|
| Streak stencil | one streak image per coping, soft lerp | streaks per source; R1 reveal against micro height; or mesh decals per source |
| Over-saturated clean wall | no film layer | a 10–25 % film lerp toward warm grey; check saturation in the base colour |
| Uniform micro | every layer shares one micro height | each layer carries its own micro height (fresh crisp, dirty filled, washed exposed), blended with R2 |
| Normal detail fades on slopes | normals lerped or overlaid | RNM, or blend heights and derive once |
| One layer always wins | height ranges differ | `equalize` each height first |
| Aliased transition lines | `w` too small | about 2 texels or more; widen with distance |
| Grey metallic halos | metal blended softly | a sharp metal mask |
| Double AO | AO in albedo and in the engine | AO only in ORM.R |

## Sources

- Barré-Brisebois & Hill, Blending in Detail: https://blog.selfshadow.com/publications/blending-in-detail/
- Mikkelsen, surface-gradient bump mapping (JCGT 2020): https://jcgt.org/published/0009/03/04/paper.pdf
- Phail-Liff & Vitale, The Order: 1886 material pipelines (SIGGRAPH 2015): https://history.siggraph.org/wp-content/uploads/2022/10/2015-Talks-Phail-Liff_Crafting-Victorian-London-The-Environment-Art-and-Material-Pipelines-of-The-Order-1886.pdf
- Mishkinis, advanced terrain texture splatting: https://www.gamedev.net/tutorials/programming/graphics/advanced-terrain-texture-splatting-r3287/
- Adobe, Height Blend and Material Height Blend: https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/material-filters/effects-material/height-blend.html
- Penty & Wong, Gears of War 4 layered materials (SIGGRAPH 2017): https://history.siggraph.org/learning/gears-of-war-4-creating-a-layered-material-system-for-60fps
- Epic, Substrate, Material Layers, decals, RVT: https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine
- Unity, HDRP Layered Lit: https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/layered-lit-material.html
- Drobot, multilayered materials in CoD: IW (SIGGRAPH 2017): https://research.activision.com/publications/archives/practical-multilayered-materials-in-call-of-dutyinfinite-warfare
- Heitz & Neyret, high-performance by-example noise: https://eheitzresearch.wordpress.com/722-2/
- SideFX, Mask Combine, Combine Normals, MtlX Bump, MtlX Layer, MaterialX in Karma: https://www.sidefx.com/docs/houdini/nodes/cop/maskcombine.html · https://www.sidefx.com/docs/houdini/nodes/cop/combinenormals.html · https://www.sidefx.com/docs/houdini/nodes/vop/mtlxbump.html · https://www.sidefx.com/docs/houdini/nodes/vop/mtlxlayer.html · https://www.sidefx.com/docs/houdini/solaris/materialx.html
- Hill, Rock-Solid Shading (Toksvig, LEAN): https://www.selfshadow.com/talks/rock_solid_shading_v1.pdf
- SideFX and Embark, THE FINALS buildings: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
