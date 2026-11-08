# Research round 5: texture layering, mixing and pattern practice

How technical artists build and mix layered materials, what modern engines can do with layers, and how to do the same in Houdini 22. **[S]** = sourced (numbered sources at the end). **[I]** = inferred or common practice. **†** = a Houdini node or parm name that was not read in a live 22.0 session. This round did not touch Houdini, because a test session holds it.

## 0. Why danchi v4 reads wrong, in layering terms

From `danchi-v4/02_golden_bay_close.jpg`:
- **Stencil streaks:** the same soft drip comb under every coping, laid over the wall instead of revealed through its height. [I]
- **Saturated, clean walls:** no film layer pulls the paint toward grey; dirt exists only in streaks. [I]
- **Uniform micro:** all layers share one micro height, so blending never changes the grain. [I]

Fixes: sections 1, 4 and 7.

## 1. Layering and mixing

### 1.1 Height blending is the core operation
A mask lerp cross-fades regardless of the surface; a **height blend** follows the relief: sand fills cracks first, plaster survives on brick high points, water pools low. [S 4, 12, 13] In Mishkinis's comparison images (viewed in the browser) the height-blended sand sits between the cobbles and traces each stone's outline; the linear version is a muddy halo.

**Recipe R1: single-height reveal.** Use this for a layer revealed against one height: dirt into recesses, chipped paint, moss.

```
t = 1 - a*(1+w)                 # a = layer amount 0..1 (paint, vertex colour, cause mask)
m = smoothstep(t, t+w, h)       # h = 0..1 height that decides who wins first
                                # (use 1-h_base for things that fill low spots)
                                # w = transition width 0.02-0.2 (small = sharp)
```

a = 0 gives none, a = 1 full cover, and high h appears first in between. This is the behaviour of Unreal's HeightLerp and of Designer's Height Blend (Height Offset, Contrast, balanced or bottom-priority mode). [S 12, 5; formula I]

**Recipe R2: the "max height" trick** for two or more layers that each have their own height (Mishkinis). [S 4]

```
hA' = hA + (1-a)     hB' = hB + a              # bias each height by its weight
ma  = max(hA', hB') - d                        # d = blend depth, ~0.05-0.2 (article uses 0.2)
wA  = max(hA' - ma, 0)   wB = max(hB' - ma, 0)
out = (A*wA + B*wB) / (wA + wB)                # apply the same weights to every channel
```

For N layers, wᵢ = max(hᵢ' − maxⱼ hⱼ' + d, 0), normalised [I]. HDRP Layered Lit's "Use Height Based Blend" with a world-unit Height Transition is the engine form [S 9, 10]. Equalise every height to the same range first, or one layer always wins. [I]

### 1.2 The standard stack order
> base → macro variation → variants (repaint, patch) → wear (reveals the layer beneath) → dirt and film → decals and hero marks. [I, consistent with S 3, 11, 14]

- **Base** comes from a library. The Order: 1886 used three tiers: "scientific" templates, crafted common tiling materials, then leaf materials that inherited or were composited from the common tier. [S 3]
- **Wear switches whole material sets** (primer under paint, brick under plaster), not only albedo. [I]
- **A global film layer** (a 10–25 % lerp toward warm grey, modulated by the macro mask) desaturates the whole facade, which v4 lacks. Dirt lerps to its colour (realism.md). [I]

### 1.3 Choosing the blend operator
| Operator | Use for | Never for |
|---|---|---|
| lerp to a colour (mix) | dirt, film, rust run, paint over primer | — |
| height blend (R1/R2) | any layer with physical thickness | flat stains on smooth glass |
| multiply | AO or cavity terms, if the engine needs one baked; transmission-like tints | dirt (reads as shadow) |
| overlay / soft light, 0.5 neutral | detail albedo variation around a mean | large value shifts; Karma MaterialX (unsupported, see 6) |
| max / min | combining heights (fill, erode) | colour |
| add | heights, sparse highlights | BSDFs (not energy conserving [S 19]) |

[I except where cited]

### 1.4 Normals: never lerp them
- **Linear blending flattens both inputs.** In Barré-Brisebois and Hill's comparison (viewed in the browser), the linearly blended cone looks washed out, and its detail weakens wherever the base tilts. "Linear and Overlay blending have no redeeming value" for detail normals (Barré-Brisebois & Hill). [S 1]
- **The options, by cost and quality:** [S 1]
  - **UDN:** `normalize(n1.xy+n2.xy, n1.z)`. The cheapest. It loses detail on flat bases.
  - **Whiteout:** `normalize(n1.xy+n2.xy, n1.z*n2.z)`.
  - **RNM:** `t = base*(2,2,2)+(-1,-1,0); u = detail*(-2,-2,2)+(1,1,-1); r = normalize(t*dot(t,u) - u*t.z)`. The best at keeping detail strength across a tilted base, at similar cost.
- **Blending normals across several UV sets, triplanar or decals:** use Mikkelsen's surface-gradient framework. It sums the surface gradients and resolves once. [S 2]
- **When you are baking, avoid normal blending altogether.** Blend the heights (R1/R2), then derive one normal from the composite height. Use RNM only for normal-map sources that have no height. [I]

### 1.5 Roughness, metal, AO and packing
- **Roughness.** Blend perceptual roughness with the same mask as albedo. Damp, polish and dust each move it (realism.md). [I]
- **Metal.** Keep it binary. Use the sharp (small w) mask for metal, so grey metallic values appear only in transition pixels. [I; Unreal limits, S 20]
- **AO** stays its own channel, because engines apply it to indirect light. Keep it out of albedo (SKILL.md).
- **Cavity.** CoD: WWII generated cavity maps automatically from every normal map. [S 15]
- **ORM packing:** R = occlusion, G = roughness, B = metallic. This is glTF's layout, and Unreal's common practice. Write it raw (linear) at 8-bit. [S 21]
- **Height for runtime blending** goes in a spare alpha or a separate map, written raw. [I]

### 1.6 Texture-time versus shader-time layering
- **Baked composites** cost nothing at runtime but are unique per asset and limited in texel density. **Shader-time layers** keep tiling detail sharp at ALU and sample cost: Painter's Dynamic Material Layering mixes materials "inside a shader instead of into a single texture" (4 materials, 3 masks). [S 6]
- The Order: 1886 used "90-95% tiling materials, with up to 4 runtime material layers", vertex-blended with height maps, plus decal projectors [S 3]. Gears of War 4 stacked dozens of materials and cooked them for 60 fps [S 7].
- **Rule:** cook what never varies per instance; keep 2–4 height-blended runtime layers driven by vertex colour or masks. [I]

## 2. Modern engine material systems

- **Unreal Substrate** [S 8]: slabs of matter combined by Vertical Layer (coats, varnish, wet films), Horizontal Blend, Coverage Weight, Select and Add (implausible; avoid). Default budget 80 bytes per pixel; over budget, "parameter blending" merges slabs. Material Layers blend horizontally only. Dirt = horizontal blend; water or lacquer = vertical layer.
- **Material Layers and Layer Blends.** A stack of Material Attributes, each with its own blend asset. The top layer wins. Base materials stay simple, and layers are reused across materials. [S 11]
- **DBuffer and mesh decals.** They change base colour, normal and roughness (with roughness come specular and metallic) before the base pass. Emissive and AO are handled separately. Mesh decals carry custom shapes such as leak strips and grout lines. [S 20]
  - Embark's procedural buildings use "Edge Softening Decals" and grout and leak decals "along the intersections between modules". [S 16]
  - That suits danchi: put a leak decal per coping source, rather than streaks in the tiling texture. [I]
- **RVT.** Terrain and its decals render into a shading cache that mesh materials can sample, for blending objects into the ground. It stores base colour, normal, roughness, specular and world height. Use static mobility only. [S 17]
- **Nanite tessellation.** Height drives real displacement; use the material's displacement magnitude and do not multiply in the graph (reported artifacts). Its version-to-version stability varies. [S 18, community; I]
- **Vertex paint plus height.** The workhorse for buildings: plaster over brick, damp bases, moss. Feed vertex colour into R1/R2, and remap it so painted areas reach full coverage. [S 3, 13]
- **Unity HDRP Layered Lit.** 4 layers. The main layer can pass albedo, normal and height to the layers above. Height-based blend has a world-unit transition, and one bug report says the slider does nothing in some 6000.x versions. [S 9, 10]
- **Studios:** Ready at Dawn (tiered library, vertex plus height layers, decals) [S 3]; The Coalition (cooked stack) [S 7]; Infinity Ward (physically layered BRDFs with thickness and absorption at 60 Hz) [S 14]; Sledgehammer (gloss from normal length, cavity) [S 15]; Naughty Dog (moss and wetness shading) [S 22]; Insomniac (Designer-driven pipeline) [S 23]; id Tech 7 (multi-PBR compositing, heavy decals) [S 24, secondary]. No primary layering talk was found for Guerrilla, Remedy or Ubisoft buildings.

## 3. Technical-artist authoring workflows

- **Substance Designer** [S 5, 25, 26]: height first with one normal from it, colour planned with the masks, sub-graphs per section, large to small (node map in copernicus.md). **Material Height Blend** blends whole PBR sets (Height Offset, Contrast, albedo matching).
- **Painter** [S 27]: anchor points expose a layer's height or normal, and generators read them through Micro Height and Micro Normal inputs, so wear reacts to painted detail. This is "masks read the current composite", not the base bake.
- **Quixel Mixer** [S 28]: per-layer height blending (Blend Radius; Invert to rise from below or descend from above); curvature read from the underlying mix.
- **Reuse in Houdini** [I]: one COP subnet or HDA per material, outputting a named cable (base colour, roughness, metal, normal, height) with seed, scale and wear exposed: the equivalent of a Designer graph or Material Function. R2 then blends every channel of two cables with one set of weights.

## 4. Pattern design

- **Per-element variation.** Each tile or brick gets random value, tilt and height offset from its id (tilepattern `id` → `randommono`), plus element-local wear. Without it, repetition shows. [S existing; I]
- **Anti-repetition, by cost:**
  - **Texture bombing:** random stamps placed per grid cell. [S 29]
  - **Hex tiling:** Mikkelsen, cheap, and it handles normals (realism.md).
  - **Stochastic histogram-preserving blending (Heitz & Neyret):** three samples on a triangle grid with variance-preserving mixing. It suits only stochastic textures such as rust, moss and stone. It breaks structured ones like brick and panels. [S 30, 31]
  - In the Unity comparison (viewed in the browser), the tiled jar shows a clear diagonal grid of identical blotches, and the stochastic side has no motif while keeping its contrast.
- **The streak fix for danchi.** A streak is a structured, sourced feature, so do not hex-tile it. Generate it per source, from source points with seeded strength and power-law lengths (weather-and-use.md), and reveal it with R1 against the micro height. The streak then breaks on the spray-tile mesas and fills the troughs first. Its edges become irregular, and no two sources match. [I]
- **Anisotropic and structured patterns.** Use `phasornoise` with a direction field for brushed metal, trowel arcs and formwork grain. Cracks are nested Worley with T-junctions (micro-noise.md).
- **Scale ratios.** Keep about 4–8× between the macro, meso and micro feature sizes, each with its own mask, so no scale fills another's gap. Only the macro layer may be world-space. [I]
- **Avoiding the "Substance look".** Critics name generator edge wear as "very visible" and unnatural, wear "too generic and evenly spread", and stacks of grunge maps. The fix is less generator, more placed wear, and noise-broken curvature. [S 32] Our cause field and 80/20 rules are the systematic version.

## 5. Scale, resolution and distance

- **Texel density.** 512 px/m is a floor for distant work; 1024 px/m is the common close first-person figure. Secondary sources disagree; consistency matters more than the number. [S 33]
- **Detail maps.**
  - A high-frequency albedo and normal, tiled 4–10× over the base [I]. Unreal's Detail Texturing function exposes the scale. [S 34]
  - Make the detail mean-neutral: albedo detail averages exactly 0.5 for overlay, and the normal detail averages flat. A biased detail map changes the brightness at distance. [I]
  - Fade the detail by `PixelDepth` (Unreal) or by distance, and replace it with macro variation. [S 34; I]
- **Specular aliasing.** Mips average away normal detail, so roughness must rise in those mips: Toksvig (roughness from the shortened averaged normal; never renormalise per mip), LEAN/CLEAN (stored variance), Unreal Composite Texture (normal roughness into a channel), CoD: WWII (gloss from normal length), geometric specular AA (Kaplanyan 2016; Tokuyoshi & Kaplanyan 2021). [S 15, 35, 36, 37]
- **For our bakes:** write roughness mips with a Toksvig-adjusted roughness, or let the engine's composite do it. For Karma, keep normal detail amplitude moderate at the shot distance. [I]
- **At distance**, R1 on a mipped height softens by itself; a very sharp w shimmers, so widen it with distance. [I]

## 6. Houdini 22 translation

| Technique | Copernicus (bake) | MaterialX in Karma (shader time) |
|---|---|---|
| R1 height reveal | `remap`, then `blend` (subtract, add); `remap` threshold with a ramp for smoothstep | `mtlxsmoothstep` (`in`, `low`, `high`) with low = `mtlxsubtract`(1, a·(1+w)); a from `mtlxgeompropvalue` |
| R2 max height | `blend` add and max, then subtract, `clamp` and divide per channel | `mtlxmax`†, `mtlxsubtract`, `mtlxclamp`†, `mtlxdivide`†, `mtlxmix` |
| Mix to a colour | `blend` (mode blend, mask) | `mtlxmix` (`fg`, `bg`, `mix`); set `signature` to color3 [S 38] |
| Mask stack | **`maskcombine`** (new in 22): ordered layers with per-layer blend mode, blur and remap ramp, then Mask Contrast, Amplitude, Gamma and Clamp [S 39] | a chain of `mtlxmultiply` and `mtlxrange` (`gamma`, `doclamp`) |
| RNM | **`combinenormals`** with Combine Method = Reoriented (also Whiteout and UDN), Normal Type Offset for map files [S 40]; parm tokens † | build it in tangent space *before* `mtlxnormalmap`: unpack the images (raw vector3, ×2−1), then `mtlxdotproduct`†, `mtlxmultiply`, `mtlxsubtract`, `mtlxnormalize`†. `mtlxnormalmap` unpacks and transforms to world, so blend before it |
| Height to normal | `heighttonormal` on the *composite* height | `mtlxheighttonormal` (`in`, `scale`) sits in MaterialX's convolution section, "may not be implementable in ray tracing" [S 19]; Karma behaviour unverified. Prefer `mtlxbump` (Height, Scale) [S 41] or a baked normal |
| Overlay detail | `blend` Overlay or SoftLight | **avoid** `mtlxoverlay` and `mtlxscreen`: "The Compositing nodes are not supported by Karma" [S 42]. Do the maths: `mtlxmultiply` and `mtlxadd`, around 0.5 |
| Coat or wet film | — | `mtlxlayer` (top = `dielectric_bsdf`, `generalized_schlick_bsdf`, `sheen_bsdf` or thin film; base = BSDF) [S 19, 43], or `mtlxopen_pbr_surface` coat inputs |
| Anti-tiling | `hextile` (`textotile`) | `mtlxhextiledimage`, `mtlxhextilednormalmap` (`tiling`, `rotationrange`, `falloffcontrast`) [S 44] |
| Triplanar | `triplanarhextile` | `mtlxtriplanarprojection` (`filex`/`y`/`z`, `blend`) [S 44]. Normals need a whiteout or RNM swizzle per axis [I] |

**Recipe R3: a two-material height-blended facade in MaterialX, with Karma as the reference.** [I]
1. Two `mtlximage` sets (paint, dirty paint), each with base colour, roughness, normal and height. Read data as raw.
2. a = cause primvar (`mtlxgeompropvalue`) × macro `mtlxfractal3d` mask.
3. m = R1 using the paint's height, inverted so dirt fills the troughs.
4. Blend base colour, roughness and height with `mtlxmix` at m. Blend the tangent normals with RNM before `mtlxnormalmap`.
5. Optionally, a wet film as `mtlxlayer` of a smooth `dielectric_bsdf` over the surface BSDF, weighted by a damp mask.

**For an engine**, MaterialX does not travel. Bake: [I]
- each tiling material set, with height in alpha or a separate raw map;
- ORM, raw;
- the masks as vertex colour, UV2 or a mask texture (the v4 run already does this);
- a note of the blend parameters (w, d) so the engine's HeightLerp or Layered Lit can reproduce them.

Unique, unwrapped pieces can bake the whole composite through `rasterizegeo` instead.

## 7. Failure modes and fixes

| Failure | Cause | Fix |
|---|---|---|
| Streak stencil (v4) | one streak image per coping; a soft lerp | streaks per source with seeded strength and length; R1 reveal against micro height; or mesh decals per source [I, S 16] |
| Over-saturated clean wall (v4) | no film layer; dirt only in features | a global film lerp of 10–25 % toward warm grey, modulated by macro; check saturation in the base colour statistics [I] |
| Uniform micro (v4) | every layer shares one micro height | each layer carries its own micro height (fresh crisp, dirty filled, washed exposed); blend the heights with R2 [I] |
| Normal detail fades or bends on slopes | normals lerped, or overlay | RNM, or blend heights and derive once [S 1] |
| One layer always wins the height blend | height ranges differ | `equalize` each height to 0–1 before blending [I] |
| Hard, aliased transition lines | w too small; sharp contrast at distance | w ≥ about 2 texels at the bake resolution; widen w with distance [I] |
| Grey metallic halos | metal blended softly | a sharp mask for metal; check that metallic is binary [I] |
| Double AO | AO multiplied into albedo and applied by the engine | AO only in ORM.R [I] |
| "Substance look" | generator wear everywhere; grunge stacking | the cause field, 80/20 clusters, placed hero marks [S 32] |

## Sources

1. Barré-Brisebois & Hill, Blending in Detail (RNM; viewed in the browser): https://blog.selfshadow.com/publications/blending-in-detail/
2. Mikkelsen, Surface Gradient-Based Bump Mapping Framework, JCGT 2020: https://jcgt.org/published/0009/03/04/paper.pdf
3. Phail-Liff & Vitale, The Order: 1886 material pipelines, SIGGRAPH 2015: https://history.siggraph.org/wp-content/uploads/2022/10/2015-Talks-Phail-Liff_Crafting-Victorian-London-The-Environment-Art-and-Material-Pipelines-of-The-Order-1886.pdf
4. Mishkinis, Advanced Terrain Texture Splatting (viewed in the browser): https://www.gamedev.net/tutorials/programming/graphics/advanced-terrain-texture-splatting-r3287/
5. Adobe, Height Blend and Material Height Blend nodes: https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/material-filters/effects-material/height-blend.html
6. Adobe, Dynamic Material Layering: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/dynamic-material-layering
7. Penty & Wong, Gears of War 4 layered materials, SIGGRAPH 2017: https://history.siggraph.org/learning/gears-of-war-4-creating-a-layered-material-system-for-60fps
8. Epic, Overview of Substrate materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine
9. Unity, HDRP Layered Lit: https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/layered-lit-material.html
10. Unity issue tracker, Height Transition: https://issuetracker.unity3d.com/issues/height-transition-in-hdrp-layered-lit-shader-is-not-accessible
11. Epic, Material Layers: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-material-layers-in-unreal-engine
12. Epic, Math Hall (HeightLerp, UE 4.26): https://docs.unrealengine.com/4.26/en-US/Resources/ContentExamples/MathHall
13. Polycount, vertex colour height-blend remap: https://polycount.com/discussion/comment/1834253
14. Drobot, Multilayered Materials in CoD: IW, SIGGRAPH 2017: https://research.activision.com/publications/archives/practical-multilayered-materials-in-call-of-dutyinfinite-warfare
15. Chan, Material Advances in Call of Duty: WWII, SIGGRAPH 2018: https://research.activision.com/publications/archives/material-advances-in-call-of-dutywwii
16. SideFX and Embark, procedural buildings of THE FINALS: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
17. Epic, Runtime Virtual Texturing: https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine
18. Unreal issue UE-370671, displacement magnitude: https://issues.unrealengine.com/issue/UE-370671
19. MaterialX PBR and standard node specifications: https://github.com/AcademySoftwareFoundation/MaterialX/tree/main/documents/Specification
20. Epic, decal materials and DBuffer: https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine
21. glTF ORM packing (Blender exporter docs): https://docs.blender.org/manual/en/4.1/addons/import_export/scene_gltf2.html
22. Brinck & Maximov, The Technical Art of Uncharted 4: https://advances.realtimerendering.com/other/2016/naughty_dog
23. McAuliffe, Mullen & Benno, Marvel's Spider-Man art, GDC 2019: https://gdcvault.com/play/1026495/-Marvel-s-Spider-Man
24. id Tech 7 analysis (80.lv): https://80.lv/articles/using-id-tech-7-doom-eternal-analysis
25. Margot Casiro (Ubisoft), heightmap-first Designer: https://80.lv/articles/001agt-learning-substance-designer-heightmap-basecolor-masks
26. Dan McCabe, G-Shock in Designer (sub-graph assets): https://80.lv/articles/creating-a-g-shock-watch-in-substance-designer
27. Substance Painter, Anchor Points and References: https://magazine.substance3d.com/substance-painter-introducing-anchor-points-and-references/
28. Quixel Mixer, blending: https://docs.quixel.com/mixer/1/en/topic/blending.html
29. Glanville, Texture Bombing, GPU Gems ch. 20: https://developer.nvidia.com/gpugems/gpugems/part-iii-materials/chapter-20-texture-bombing
30. Heitz & Neyret, High-Performance By-Example Noise, HPG 2018: https://eheitzresearch.wordpress.com/722-2/
31. Deliot, Procedural Stochastic Texturing in Unity (viewed in the browser): https://unity.com/blog/engine-platform/procedural-stochastic-texturing-in-unity
32. 80.lv, 10 tips for Substance Painter and Designer, and Polycount critiques: https://80.lv/articles/10-tips-for-substance-painter-and-substance-designer · https://polycount.com/discussion/comment/2716897/
33. Texel density guides: https://rebusfarm.net/blog/texel-density-basics-every-artist-should-know
34. Epic, Depth expressions (PixelDepth): https://dev.epicgames.com/documentation/unreal-engine/depth-material-expressions-in-unreal-engine
35. Hill, Rock-Solid Shading (Toksvig, LEAN): https://www.selfshadow.com/talks/rock_solid_shading_v1.pdf · Olano & Baker, LEAN Mapping: https://www.cse.chalmers.se/edu/year/2011/course/TDA361/Advanced%20Computer%20Graphics/LEANMapping.pdf
36. Epic, Composite Texture: https://docs.unrealengine.com/4.26/en-US/RenderingAndGraphics/Textures/Composite
37. Kaplanyan et al., Filtering Distributions of Normals, HPG 2016: https://research.nvidia.com/sites/default/files/pubs/2016-06_Filtering-Distributions-of/NDFFiltering.pdf · Tokuyoshi & Kaplanyan, JCGT 2021: https://www.jcgt.org/published/0010/02/02/paper-lowres.pdf
38. Repo: docs/redesign/review/31-logs-danchi-v3.md (`mtlxmix` driven by a primvar in Karma) and 26-neo-tower-dogfood.md (`signature`)
39. SideFX, Mask Combine COP: https://www.sidefx.com/docs/houdini/nodes/cop/maskcombine.html
40. SideFX, Combine Normals COP: https://www.sidefx.com/docs/houdini/nodes/cop/combinenormals.html
41. SideFX, MtlX Bump: https://www.sidefx.com/docs/houdini/nodes/vop/mtlxbump.html
42. SideFX, MaterialX in Solaris and Karma (Limitations): https://www.sidefx.com/docs/houdini/solaris/materialx.html
43. SideFX, MtlX Layer: https://www.sidefx.com/docs/houdini/nodes/vop/mtlxlayer.html
44. SideFX, VOP node index (MtlX nodes, 22.0): https://www.sidefx.com/docs/houdini/nodes/vop/index.html
