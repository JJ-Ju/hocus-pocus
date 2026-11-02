# Texturing very large architecture at game fidelity: research note

Why the danchi weathering reads low-res, how AAA studios texture very large buildings, and what we
should build. It answers the art director's review: the textures are "very, very low res"; use
tiling with distribution algorithms, UDIM and/or trim sheets, stamps and decals; make it a skill.

Tags: **[C]** consensus or vendor spec · **[P]** one studio's or practitioner's practice ·
**[M]** measured or published data · **[I]** my inference or calculation. Numbers in brackets point
to §12. "(snippet)" marks a claim read only in a search excerpt of a page that refused the fetcher.
The shared web-search budget ran out before the end, so some leads stayed open (§11).

**The building** (the coordinator's numbers, which replace the brief's): ten storeys at 2.8 m;
south and north fronts 81.9 × 36.3 m including the roof stair towers (main slab about 30 m); west
gable 14.9 × 36.3 m. The generator's planes S, N and W cover 6,487 m²; an east gable adds 541 m².

## 0. Verdict

- **None of the studios documented here textures a big building with one unique sheet**
  [P 19, 29, 31, 32; I]. Tiling materials carry the surface at 512–2,048 px/m, trims carry edges
  and joints, decals carry story marks, and low-res masks or vertex colour say where each layer
  goes. A tiling height gives those masks crisp edges at runtime.
- **Our sheet flattens all four into 50 px/m** [M, repo]. At 4K and a 90° FOV, a player 2 m from
  the wall sees 960 px/m, so one 2 cm sheet texel covers about 19 × 19 screen pixels [I].
- **Unique PBR at game density is out.** The south front at 512 px/m is 779 Mpx, about 2 GB as a
  lean BC set; the building at 1,024 px/m is 17–25 GB [I, §7].
- **Recommended** [I]: keep the rule generator as the authority on where weathering goes, but
  export masks at 50 and 25 px/m (about 28 MB per building), a decal list and per-instance data.
  Render them over a shared library of about 110 MB per estate: hex-tiled materials, a trim sheet
  and a decal atlas at 1,024 px/m. Preview with a numpy compositor that runs the same shader maths,
  and gate what ships.
- **We are not starting from zero** [M, repo]. Danchi 1.1 already ships world UVs in metres, a
  vertex-colour bake, 5,228 mesh decals on an atlas and 1,024² tiling sets. The rule generator is
  the better placement brain, and the new stack joins the two.

## 1. Why the current output reads low-res

- `weather_fields.py` works per facade plane at 50 px/m (the south front is 4,095 × 1,815 px), and
  `composite()` lerps every layer into one albedo [M, repo].
- The round-E sets are far denser: formed concrete 1,138 px/m (3.6 m at 4096²), spray macro
  569 px/m (3.6 m at 2048²) and spray detail 1,707 px/m (0.6 m at 1024²). But `material_map()`
  box-resizes each 3.6 m tile to 180 px, so only its 2 cm content reaches the sheet [M, repo].
- The 1:1 review crops show 2 cm pixels, so they look soft even where the rules are right [I].
- `closeup.py` already composes the sheet with the coat set at 1,000 px/m through a height-lerp
  [M, repo]. It is the right idea, but it only makes 1 m previews.
- The distribution felt off partly for a texture reason. The material had one frequency, the 3.6 m
  tile, and the J2 dirt response printed it as a grid [M, round G]. Hex-tiled materials and unique
  masks pull the two apart [I].

## 2. Texel density

**Targets.** Maxon's presets are 1,024, 512 and 256 px/m for first-person, third-person and
top-down games, as examples rather than a standard [C 1]. Beyond Extent gives no numbers, only the
rule that a closer camera needs more [P 2]. The danchi README sets 512 px/m [M, repo]. A Ready at
Dawn artist reported 512 px/m with 1,024² textures on The Order: 1886 (snippet) [P 32].

**What the screen asks for** [I]. One texel per pixel at screen centre needs
W / (2 tan(FOV/2) · d) px/m on a wall at distance d, with W the screen width in pixels:

| Wall distance | 1080p, 90° | 4K, 90° | Carried by |
|---|---|---|---|
| 0.5 m (hand on the wall) | 1,920 | 3,840 | micro layer (1,707–2,048) and trims |
| 1 m | 960 | 1,920 | base 1,024 plus micro |
| 2 m | 480 | 960 | base 1,024 |
| 5 m | 192 | 384 | base at mips; masks begin to show |
| 10 m | 96 | 192 | masks and macro variation |
| 20 m | 48 | 96 | masks at 1:1 (50 px/m) |
| 40 m | 24 | 48 | masks at mip 1; LOD1 |
| 100 m and more | ≤ 10 | ≤ 19 | HLOD or impostor |

So 512 px/m is 1:1 down to 1.9 m at 1080p and 3.75 m at 4K, and 1,024 px/m down to 0.94 m and
1.9 m. At arm's length on a 4K screen the eye wants about 2,000 px/m, which only tiling makes
affordable [I].

**Holding density across a big building.** Tiling surfaces get UVs in metres, and each material
divides by its tile size, so density belongs to the material, not the mesh [C]. Danchi 1.1 already
does this [M, repo]. A trim's target is strip px ÷ element height, scaled at most about 25 % up or
down [P 2]; a decal's is atlas cell px ÷ decal size [I]. Unique data is low on purpose: it places
the layers, and the tiling layers carry the texels [P 29; I]. Check it all with a density map on
the exported mesh, from UV area × texture size² ÷ world area [C].

## 3. Trims for edges, joints and mouldings

- **The Ultimate Trim** (Insomniac, Sunset Overdrive, GDC 2015) standardised a trim layout and a
  normal-map structure. A UV script mapped pieces fast, and a custom shader added variation. The
  goals were production speed, memory and performance [P 4].
- **Bevel strips.** 45° bevels baked along strip edges make a hard 90° edge read as rounded; CG
  Channel calls them fake bevelled edges (snippet) [P 5]. Forum users note the trick is exact only
  on 90° edges (snippet) [P 6].
- **Beyond Extent's rules** (Scot Burns) [P 3]. UVs run past 0–1 along the tiling axis. Strips are
  pixel-snapped (512 down to 16 on a 1,024 sheet), so sheets can swap. Each strip is sized by the
  largest element it serves. A hybrid sheet keeps room for unique bakes, and mesh decals give what
  a trim cannot.

| Feature | Trim treatment [C; I for our sizes in §10.4] |
|---|---|
| Arris (any 90° concrete edge) | bevel strip: 45° normal, chalked edge, chip height for wear |
| Coping, parapet top | top strip, clean and rain-washed variants |
| Slab edge, balcony lip | face strip with the drip-groove lip |
| Drip edge (水切り) | narrow groove strip under the lip |
| Precast and construction joints | groove strip: sealant bead and the dark band beside it |
| Sill | sill strip with a run-off lip |
| Rails, posts, sash profiles | a separate metal trim sheet |

Trims share one material; the weathering masks reach them by planar projection (§10.8) [I].

## 4. Tiling large surfaces, and breaking the tile

- **UV-tiled or triplanar** [C]. UV-tiled costs one sample per map and keeps tangents and
  registration. Triplanar costs three and suits surfaces without good UVs. Our kit has UVs in
  metres, so materials are UV-tiled, and planar facade projection is only for the masks [I].
- **Hex tiling** (Mikkelsen, JCGT 2022) makes three fetches on a hex grid with random offsets and
  rotations, then a variance-preserving blend, with no precomputation. Normals blend as derivatives
  weighted by steepness [C 8]. It is our default for stochastic sets.
- **Stochastic texturing** (Heitz & Neyret 2018) preserves the histogram, but needs a precomputed
  transform and suits only stochastic textures [C 9].
- **Unreal's TextureVariation** function bombs the texture with patches of random scale and
  rotation, at a fixed cost (video description) [P 10].
- **Macro variation** multiplies by low-frequency maps at two or three incommensurate world scales.
  Epic's Starter Content calls it Macro Texture Variation (forum, snippet) [P 11].
- **Detail textures** tile a fine normal and height 4–10× over the base. They must be mean-neutral
  and fade with distance (layering.md) [C].
- **Never hex-tile structured content:** brick, formwork grids, laps, joints [C 9; concrete.md].
  Godot has no built-in anti-tiling, so it needs a custom shader [I].

## 5. Layered materials driven by masks

- **Unreal Material Layers** [C 12]: a stack of layer assets in which the top layer wins. A Layer
  Blend asset makes the mask between two layers, and parameters live per layer in the instance. The
  page gives no cost figures.
- **CryEngine's Blend Layer** (Star Citizen's engine lineage [C]) blends textures within one
  material by vertex alpha and a blend map. It is height-driven, with a falloff for hard edges such
  as rust (snippet) [C 39]. I found no primary source for Star Citizen's own shader.
- **Cyberpunk 2077 (CDPR)** [P 29, 30]. Layering covers almost all models, from a library of tiling
  templates blended at runtime, up to 20 layers per mesh. Each mesh has one hand-painted mask, sparse
  and packed small. Microblends are "a heightmap alpha and normal map used to mask the materials"
  (Krzyścin); they add detail in transitions, so masks stay small. Compute shaders cache visible
  layers in a runtime texture, and Painter used a shader matched to the engine, tone mapper included.
- **The Order: 1886:** 90–95 % tiling materials, up to four runtime layers vertex-blended with
  height maps, and decal projectors for damage, gore and puddles [M/P 32].
- **The Division 2** [M/P 31]: about 450 Designer materials; RGB-mask shaders (rust, dirt, scratches,
  one per channel); a tool, Sidekick, that showed the shader's result while artists painted masks;
  and a grime graph run on modular building pieces from their mesh maps.
- **Others.** Gears of War 4 cooked dozens of layers into textures [P, layering.md]. Naughty Dog's
  Uncharted 4 talk covers moss and wetness shading [C 38]; the TLOU2 slides reportedly describe an
  uber shader over almost every surface (snippet) [P 38]. Their vertex-blend recipe: not found.

**Mask resolution.** No studio publishes mask px/m. Cyberpunk says only that its masks are smaller
than standard asset textures [P 29]. Vertex-blend masks live in vertices, so their resolution is
the vertex spacing, typically decimetres [I]. Either way, the high frequencies come from a tiling
height [I].

**How a low-res mask gets a crisp edge** [C for height-lerp; I for this variant]:
```
h  = tiling micro height, equalised to a uniform 0-1 histogram (once, offline)
a  = mask amount 0-1, bilinear from the 50 or 25 px/m mask
m  = smoothstep(1 - a - w/2, 1 - a + w/2, h)   # w = 0.1-0.3
m  = mix(m, a, fd)                              # fd: 0 near, 1 once the micro has mipped away
```
Because h is equalised, the mean of m over a few cm equals a, so the gate's coverage at 50 px/m
holds up close [I]. Without `fd`, distant transitions turn binary and shimmer (layering.md) [C].

**Vertex colour on dense Nanite meshes.** Nanite meshes carry vertex colours and several UV sets
[C 14], but Mesh Paint cannot paint vertex colour on them. Epic points to Texture Color painting
instead, which is always a virtual texture [C 15]. Instances share vertex data, so instanced kit
pieces cannot carry per-placement colour [C 15; I]. Vertices are also a poor mask store: a 5 cm
grid on the south front is 1.19 M vertices, while its 2 cm mask is a 7.4 Mpx BC7 texture of
7.1 MB [I].

## 6. Decals

- **Unreal** [C 13, 14]. DBuffer decals (the UE5 default) write base colour, world normal and
  roughness; specular and metallic ride on roughness; emissive and AO take extra draws. Cost is
  coverage times material complexity. Mesh decals put a decal material on a mesh, for strips and
  leaks. Nanite meshes receive projected decals but cannot be mesh decals (those need a translucent
  blend mode), so decal meshes stay non-Nanite, as `danchi_decals` already is [M, repo].
- **Godot 4** [C 24]. Decal nodes work in Forward+ and Mobile, not in Compatibility. Forward+
  clusters them with lights and probes: 512 clustered elements in view by default, raiseable. On
  Mobile, "only 8 decals can be applied on each individual Mesh resource". Decals carry albedo,
  normal, ORM and emission, but no height and no custom shader; sorting is by AABB size and distance.
- **So, in Godot** [I], Decal nodes suit a few dozen hero marks. Thousands of building marks must be
  mesh decals with `blend_mix` and `depth_draw_never`, as in danchi 1.1 [M, repo]; they shade
  themselves, so they cannot bend the wall's normal. UE decal materials and Godot mesh-decal
  shaders can both read world position, and so run the wall's edge rule [I].
- **Atlases and counts.** DOOM (2016) applies decals from one atlas in the clustered forward pass,
  up to 256 per cluster [M 33]. The Doom Wiki gives an 8k × 8k atlas and 4,000 decals in view
  (snippet) [M 34], and id Tech 7 expanded the system [P 35]. Danchi 1.1 placed 5,228 decals at
  Typical (0.74 per m² of bounding facade), up to six deep on a parapet; LOD1 kept 945 over 1.5 m²
  [M, repo]. I found no studio that publishes decals per building.
- **Placement.** By hand: The Order's projectors [P 32]. By rule: Embark's Exterior Decals node puts
  edge-softening decals on hard edges, and grout and leak decals along "intersections between
  modules" [P 23]. In engine: UE's PCG is production-ready in 5.7 (snippet) [C 41].
- **Runs, cracks and stains** [I]. Runs (rust, leaks, efflorescence) are strip decals: a head, a body
  that tiles along the run, a tail, so a 4 m run needs no 4 m texture. Cracks follow `CrackSet`
  polylines. Stains and blooms are cells, flipped and scaled; danchi 1.1's 16 streak cells already
  repeat at close range [M, repo].

## 7. UDIM and virtual texturing

**UDIM** is rare for game environments, as far as I found; it suits film, hero characters and
virtual production [I]. Unreal supports UDIMs only as streaming virtual textures [C 16]:
`BaseName.####` files import as one virtual texture, each tile with its own resolution, in
power-of-two sizes. A VT sample costs at least two fetches plus maths, and stacks share up to 8
samples. Tiles carry a 4-texel border, trilinear filtering is stochastic, and pages can pop in.

**Runtime Virtual Texturing** [C 17] renders material output on demand into a cache, projected along
−Z of a rotatable volume, in formats from BC1 to BC3 + BC5 + BC1 (YCoCg). Writers must be static.
It serves terrain blending and costly shading over large areas. Aiming it at a facade is possible
but undocumented [I]; Cyberpunk's runtime layer cache is the same idea in a custom engine [P 29].

**The memory maths** [C 7; I]. BC1 and BC4 cost 0.5 B/px, BC5 and BC7 1 B/px, and mips add a third.
A lean set (BC1 albedo, BC5 normal, BC1 ORM) is 2 B/px; a full set (BC7, BC5, BC7 ORM with height)
is 3 B/px. MB = 2²⁰ bytes.

| Unique PBR | South front | Building (S, N, W) | 4096² UDIM tiles, building |
|---|---|---|---|
| 50 px/m today, albedo only (BC1) | 7.4 Mpx, 5 MB | 16.2 Mpx, 10 MB | 3 |
| 512 px/m, lean | 779 Mpx, 1,982 MB | 1,701 Mpx, 4,325 MB | 120 (8 m tiles) |
| 512 px/m, full | 2,973 MB | 6,487 MB | 120 |
| 1,024 px/m, lean | 3,117 Mpx, 7,928 MB | 6,802 Mpx, 17,298 MB | 460 (4 m tiles) |
| 1,024 px/m, full | 11,892 MB | 25,947 MB | 460 |

Streaming VT keeps only visible pages in VRAM, but disk and patch size stay as above for every
building variant [C 16; I]. id's MegaTexture is the cautionary precedent: id Tech 7 removed it, and
the removal is credited with higher texture fidelity [P 35].

**Godot 4** [C 25, 26; P 28]. The import docs do not mention UDIMs; a community addon exists (v0.2,
Godot 4.2). Use one texture per facade plane, a `Texture2DArray` of equal tiles read through
`sampler2DArray`, or atlases. A per-instance uniform can carry the array index, except under
Compatibility, which needs a `switch`. Mobile and web usually stop at 4096²; the south front at
50 px/m is 4,095 px wide, so it fits.

## 8. Relief and per-instance data

**Nanite tessellation** [C 18; P 18]. A 5.3 tutorial calls it new in 5.3, and the 5.4 release notes
list it as experimental; I could not confirm its 5.7 or 5.8 status. It needs
`r.Nanite.AllowTessellation=1` in the config, `r.Nanite.Tessellation=1`, and the material's
tessellation option and Displacement pin; non-Nanite meshes ignore it. Epic staff (landscape context): keep Displacement
within 0–1; cost scales with magnitude; a dicing rate of 4 is the sweet spot. Godot has no
equivalent [I]. So the coat's 1 mm relief stays in normal maps, and joints (20 × 10 mm) and spalls
(1–4 cm) are geometry from procedural-mesh-damage, or UE-only tessellation [I].

**Per-instance custom data.** Houdini Engine writes `unreal_num_custom_floats` and
`unreal_per_instance_custom_dataX` into the instance buffer, which the vertex shader reads [C 22].
Old forum threads report HISM index problems, with ISM plus Nanite as the fix (snippet) [P 42].
Godot offers MultiMesh `INSTANCE_CUSTOM` (four floats, 16-bit under Compatibility) [C 27] and
per-instance uniforms (at most 16 per shader, no textures) [C 25].

## 9. Case studies

| Project | What is documented | Lesson for us |
|---|---|---|
| City Sample, The Matrix Awakens | Houdini makes a point cloud that a Rule Processor turns into thousands of instances; each building is hundreds of instances; every static mesh is Nanite, with no classic LODs [C 19]. The pack has 24 kits (some coverage says 22), 2,000+ meshes and 2,048–8,192 px textures (snippet) [M 20]. A team artist cites procedural texturing plus asset-specific maps, and procedural grime and colour variation on roofs (snippet) [P 21] | kits, instances and shader-side weathering; no unique facade sheets |
| THE FINALS (Embark) | rule-placed mesh decals at module joins: edge softening, grout, leaks [P 23] | decals by rule at the seams of a kit |
| Marvel's Spider-Man (Insomniac) | Houdini authored ground, buildings, props and impostors [P 37]; the city streamed in 128 m tiles [M 37]; the materials talk is members-only | material details not found |
| Assassin's Creed Unity | a GPU-driven pipeline for many highly modular buildings, with mesh clusters and per-material instance batching [P 36] | facade texturing not public |
| Cyberpunk 2077 | runtime multilayer over sparse per-mesh masks, plus microblends [P 29, 30] | small masks, crisp edges from a tiling height |
| The Division 2 | about 450 materials, RGB-mask shaders, a preview tool [M/P 31] | masks per layer family; preview the real shader |
| The Order: 1886 | 90–95 % tiling, four vertex-blended layers with height, decal projectors [M/P 32] | the closest precedent for our stack |
| DOOM 2016 and Eternal | clustered decals in one atlas; MegaTexture dropped [M/P 33–35] | decals scale; unique texturing does not |
| Houdini to engine | City Sample's rule pipeline [C 19]; Embark's Building Creator [P 23]; SideFX's Titan EVO teaches Copernicus trim sheets with procedural UVs in HDAs for UE5 [C 40] | build the kit, its UVs and its trims in Houdini |

## 10. Recommended architecture for the danchi

All of §10 is my recommendation [I], except where another tag says otherwise.

### 10.1 The stack [I]

| # | Layer | Carrier | Density, size | Holds | Built by |
|---|---|---|---|---|---|
| 1 | Base materials | tiling sets on UVs in metres | 1,024 px/m (2048² over 2 m); formed concrete 569 px/m, registered | coat, formed concrete, soffit lithin, painted steel, aluminium, glass | Copernicus (round E, re-tiled) |
| 2 | Micro and microblends | tiling height, normal, cavity; heights equalised | 1,024–1,707 px/m | coat bumps, run-off rivulets, growth edges | Copernicus |
| 3 | Macro variation | one BC4 noise at two world scales | 1024² at 9.7 m and 31 m | broad tone drift | Copernicus |
| 4 | Trims | trim sheet on kit UVs | 1,024 px/m | arrises, copings, slab edges, drip grooves, joints, sills | Copernicus and kit UVs |
| 5 | Unique masks | facade-space textures, planar projection | 50 and 25 px/m | where each weathering layer is, how much, which dirt colour | `weather_fields.py`, rules unchanged |
| 6 | Decals | mesh decals on one atlas | 1,024 px/m (soft marks ≥ 512) | rust runs, leaks, cracks, efflorescence, spall halos, patches, signs | generator's list, meshes in Houdini |
| 7 | Instance and vertex data | per-instance floats; vertex colour | per piece | facade and layer id, bay tint, repaint id, damage variant; coarse soot on soffits and returns | Houdini |
| 8 | Geometry | kit and damage | — | joints, spalls, chips, bent rails | procedural-mesh-damage |
| 9 | Far LOD | HLOD or impostor bake | 10–50 px/m | the composite at distance | UE HLOD; Labs Impostor Baker |

### 10.2 Unique masks: what stays rule-driven [I]

The rules do not change; only the output does. The masks stay in facade space, sampled by planar
projection from each facade's frame, so instanced kit pieces share meshes. There is one mask set per
depth layer: L0 for the front-most surfaces the generator weathers today, and L1 for the recessed
walls behind balconies and corridors (same rules with the shelter field, at 25 px/m); without L1 a
recessed wall reads the parapet's values. Each surface class reads the channels its own way (steel
reads `M_hi.G` as rust). Discrete marks go to decals (§10.5), baked back into `M_hi` from LOD1 up.

| Texture | Density | Format | R | G | B | A |
|---|---|---|---|---|---|---|
| `M_hi` | 50 px/m (2 cm) | RGBA8 → BC7, linear | dark run-off (streak envelope) | stains, base splash (steel: rust) | growth | light layers: washed, chalking, efflorescence film |
| `M_lo` | 25 px/m (4 cm) | RGBA8 → BC7, linear | soiling film | damp (darker, smoother) | coat tone: laps, clouding passes, repaint, fading (0.5 = none) | edge-wear amount for trims |
| `tint` | 25 px/m | RGB8 → BC1, sRGB | dirt colour: warm, soot, green and yellow families | | | |

| Plane | `M_hi` px | `M_lo`, `tint` px | MB with mips | Power-of-two MB |
|---|---|---|---|---|
| S front | 4,095 × 1,815 | 2,048 × 908 | 13.0 | 14.7 (4096 × 2048) |
| N front | 4,095 × 1,815 | 2,048 × 908 | 13.0 | 14.7 |
| W gable | 745 × 1,815 | 373 × 908 | 2.4 | 3.7 (two gables pack into one 2048²) |
| Building, L0 | | | 28.4 | 33.0 |

L1 adds about 6 MB, and a background variant at 25, 12.5 and 12.5 px/m costs about 7 MB. 50 px/m
stays because the 68 rules and the solver are calibrated there. From 20 m out it is already 1:1 at
1080p (§2); nearer, the microblends supply what the mask lacks.

### 10.3 Tiling detail [I]

| Set | Tile | Texture | Density | Sampling | Note |
|---|---|---|---|---|---|
| Coat base (spray tile) | 2.0 m | 2048² | 1,024 px/m | hex tiling | rebuilt from the 3.6 m macro with stochastic content only; laps, patches and 1.5–4 m clouding passes move to `M_lo` |
| Coat micro | 0.6 m | 1024² | 1,707 px/m | hex tiling | the existing spray detail; height equalised for the edge rule |
| Run-off micro | 0.5 × 2.0 m | 512 × 2048, BC4 | 1,024 px/m | U offset per column, never rotated | rivulets inside streak envelopes |
| Growth micro | 1.0 m | 1024², BC4 | 1,024 px/m | hex tiling | edges of growth and efflorescence |
| Formed concrete | 3.6 m | 2048² (hero 4096²) | 569 (1,138) px/m, plus coat micro | UV-tiled, registered to floors and bays | never hex-tiled; per-panel tint from world position |
| Soffit lithin | 1.0 m | 1024² | 1,024 px/m | hex tiling | |
| Painted steel | 1.0 m | 1024² | 1,024 px/m | hex tiling | rust height in A |
| Macro variation | 9.7 m and 31 m | 1024², BC4 | 106 and 33 px/m | world planar, two scales | incommensurate with 2.8 m storeys and 6 m bays |

### 10.4 Trims

One 2048² sheet at 1,024 px/m, with U tiling every 2.0 m. Strip heights are multiples of 16 px,
which keeps BC blocks and the first mips clean [I].

| Strip | Serves | Element | Height |
|---|---|---|---|
| Bevel × 4 (Ultimate Trim) | every 90° arris on walls, parapets and slab edges | 45° bevel, about 25 mm | 32 px each |
| Coping, clean and washed | parapet and roof tops | 0.18–0.30 m | 320 px × 2 |
| Slab edge, clean and stained | balcony and corridor fronts | 0.15–0.18 m | 192 px × 2 |
| Drip groove (水切り) | under the lip | 15 mm groove | 32 px |
| Joint | precast and construction joints | 20 mm groove, 20 mm band each side | 64 px |
| Sill | window sills | about 0.15 m | 160 px |
| Plinth band | ground floor | 0.45 m | 448 px |
| Hybrid row | unique bits | — | 192 px |

A 1024² metal sheet holds rail tubes, posts and caps, sash and frame extrusions, and gutter and
downpipe bands, with chips and rust height in A. Each bevel strip carries a chip-height pattern. The
trim material reads `M_lo.A` through the facade projection and reveals chips with the edge rule, so
they are crisp without a unique texture. The gate's N rules keep measuring the 50 px/m output [I].

### 10.5 Decals

One 4096² atlas at 1,024 px/m holds 16 m² of decal texture: BC7 colour and opacity, BC5 normal, and
BC4 roughness at 2048² [I].

| Region | Pixels | Cells | Content |
|---|---|---|---|
| A, runs | 2048 × 4096 | 16 strips of 128 × 4096 (0.125 × 4 m): a 0.5 m head, a 3 m tiling body, a 0.5 m tail | rust runs 6, leaks and drips 6, efflorescence runs 4 |
| B, blotches | 2048 × 2048 | 16 cells of 512² (0.5 m) | stains, spall halos, efflorescence blooms, AC drip stains |
| C, cracks | 2048 × 1024 | 32 strips of 2048 × 32 (2 m × 31 mm), tiling along U | hairlines to 2 mm cracks, sealed cracks, injection seats |
| D, edges and patches | 2048 × 1024 | 8 strips of 2048 × 64; 16 cells of 256² | chipped-edge runs, repair patches, small stickers |

| Mark (LOD0, Typical) | Generator source | Budget per building |
|---|---|---|
| Rust runs | below rail posts and rusted lower rail edges (R1, R2) | ≤ 600 |
| Cracks | `CrackSet` polylines, one strip per segment | ≤ 400 |
| Spall halos | one per spall | ≤ 200 |
| Efflorescence | crack ends and slab edges | ≤ 150 |
| Repair patches | patch rectangles | ≤ 100 |
| Hero leaks | coping ends, scuppers, AC drains | ≤ 80 |
| Signs, numbers, graffiti | story | ≤ 20 |
| Total | | ≤ 1,550 (0.24 per m² of bounding facade) |

At most three decals overlap any pixel. LOD1 keeps decals over 1.5 m² and bakes the rest into
`M_hi`, and LOD2 has none [I]. Streak envelopes, stain fields, splash, growth and film stay in masks;
they made up most of danchi 1.1's 5,228 decals [M, repo]. In Unreal, build one non-Nanite mesh per
facade and atlas, with a DBuffer material whose edges follow the facade's micro height. In Godot,
use the same meshes with a custom spatial shader, and Decal nodes only for 50 hero marks or fewer
[I].

### 10.6 UDIM and virtual textures [I]

- **PBR:** no UDIMs and no unique bakes; tiling, trims and decals carry the texels (§7). No RVT.
- **Masks in Unreal:** streamed textures with mips, one per plane. Past about 300 MB of masks per
  estate, switch to streaming virtual textures (or 1024² UDIM tiles of 20.48 m), at two mask
  samples per pixel of at least two fetches each [C 16].
- **Godot:** a `Texture2DArray` (one 4096 × 2048 layer per front, one for both gables) indexed by a
  per-instance uniform, or one material per plane [C 25]. Far LOD: UE HLOD; Labs Impostor Baker.

### 10.7 Memory budgets (MB = 2²⁰ bytes) [I]

| Item | UE5 | Godot 4, Forward+ | Godot 4, Mobile |
|---|---|---|---|
| Shared library, per estate | 110 (BCn, mips stream) | 110 (S3TC, BPTC, RGTC) | 28 (each side halved) |
| Unique masks per building, L0 | 28 (33 padded) | 28 | 7 (25 / 12.5 / 12.5 px/m) |
| Unique masks, L1 | 6 | 6 | 2 |
| Decals | ≤ 1,550 mesh decals | mesh decals; ≤ 50 Decal nodes | mesh decals only |
| Budget per building, unique | ≤ 40 | ≤ 40, planned as resident | ≤ 10 |
| Ten unique buildings | about 450 on disk; the resident share streams | about 450 resident; background blocks use the 7 MB variant | about 120 |

The shared 110 MB: coat base, formed concrete and the concrete trim at 2048² (BC7, BC5, BC7:
16.0 MB each); the decal atlas at 4096² (BC7, BC5: 42.7) and its BC4 roughness at 2048² (2.7); coat
micro 2.7; run-off and growth micro 1.3; soffit lithin, painted steel and metal trim at 1024²
(4.0 each); macro variation 0.7. I could not confirm mip streaming in Godot 4, so its column assumes
everything stays resident [I]. Godot's BPTC import needs Forward+ or Mobile; Compatibility falls
back to S3TC, where BC3 also costs 1 B/px [C 26]. Unique PBR at 512 px/m would be 4,325 MB (§7).

### 10.8 The shader contract, portable to UE and Godot [I]

```
// per pixel on a wall slot. P world position, d camera distance; per instance: facade, layer, bay tint
f    = facade_metres(P, facade[id])                       // x right, y down from the top, metres
base = hex(coat_base,  plane_xy(P) / 2.0)                 // albedo, ORM, normal, height
mic  = hex(coat_micro, plane_xy(P) / 0.6)                 // normal, h_eq, cavity
run  = tex(runoff, f / (0.5, 2.0) + column_offset(f.x))   // never rotated
grow = hex(growth, plane_xy(P) / 1.0)
Mh   = tex(M_hi[layer], f * 50 / size);  Ml = tex(M_lo[layer], f * 25 / size);  T = tex(tint[layer], f * 25 / size)
fd   = saturate((d - 8) / 17)                             // near: micro decides; past 25 m: mask decides
R(a, h, w) = mix(smoothstep(1 - a - w/2, 1 - a + w/2, h), a, fd)
A = base.albedo * macro(P) * bay_tint * (1 + 0.1 * (Ml.b - 0.5))   // tone: laps, repaint, fading
A = mix(A, T * k_film,  R(Ml.r, 1 - mic.h,  0.30))       // film fills the troughs
A = mix(A, T * k_stain, R(Mh.g, 1 - mic.h,  0.15))       // stains, splash
A = mix(A, T * k_run,   R(Mh.r, run.h,      0.20))       // streak bodies follow rivulets
A = mix(A, k_bio,       R(Mh.b, 1 - grow.h, 0.20))       // growth from its own edges
A = mix(A, k_light,     R(Mh.a, mic.h,      0.20))       // washed tops, chalk on the peaks
rough  = base.rough - 0.25 * R(Ml.g, 1 - mic.h, 0.30)    // damp is smoother
normal = rnm(base.n, mic.n * coat_strength)
```

The `k_*` colours and the layer order come from the generator's `COL` table and `composite()`. One
JSON file holds the constants, and the UE material function, the Godot shader and the numpy mirror
all read it.

### 10.9 Offline preview: an engine-mirror compositor [I]

Grow `closeup.py` into `engine_preview.py`. It reads exactly what ships (the 8-bit masks, tiling
sets, trim sheet, decal list and atlas) and `shader_contract.json` (tile sizes, the hex-tiling hash,
w, `fd`, layer order, colours). It writes three things:
1. **1:1 crops at game density:** 1,024 px/m, and 2,048 px/m for hand-on-the-wall views, at fixed
   spots (a joint, open wall, the foot, a balcony lip, a rail). They replace the 50 px/m crops.
2. **Camera views at 2, 10 and 30 m,** filtered to the screen footprint (mip = log2 of texels per
   pixel), under the fixed sun of `lit_preview.py`.
3. **The 50 px/m composite with `fd` = 1,** which the 68 rules measure, so they judge what ships.

Hex tiling, RNM and the edge rule port line for line, with one hash in numpy, HLSL and GLSL. Each
release, one golden crop rendered in Godot (headless) and UE must match numpy (mean ΔE00 ≤ 2).
Precedents: CDPR matched Painter to the engine [P 29]; Massive's Sidekick previewed the real shader
[P 31].

### 10.10 Gate checks for the stack

| Check | Measure | Pass | Basis |
|---|---|---|---|
| T1 texel density | per surface class, from exported UVs and the contract | base 1,024 ±25 % (512 for third person); micro ≥ 1.5× base; trims ±25 %; crisp decals ≥ base, soft ≥ 0.5×; neighbours within 1.25× | [P 2; I] |
| T2 repetition at the tile period | the round-G harmonic detector (G-1) on mirror views at 10 m and 30 m, at each tile period (2.0, 0.6, 3.6 m) and the hex cell | at or below the tile-free controls (4.0–7.9 in round G) | [M, repo; I] |
| T3 mask resolution against distance | the smallest mark per channel; magnification at the closest camera | marks ≥ 3 mask texels; above 4 screen px per mask texel, a channel must pass through the edge rule with a microblend at ≤ 1.5 px per texel; w ≥ 1 microblend texel | [I] |
| T4 coverage kept | mean edge-rule output over 10 cm windows against the mask amount | difference ≤ 0.02 | [I] |
| T5 decal density | decals per m² per facade; overlap per pixel; decals in view at the review cameras; nearest identical repeat | ≤ 0.5 per m²; ≤ 3; Godot Decal nodes ≤ 50; repeat ≥ 6 m | [C 24; M, repo; I] |
| T6 distance stability | albedo mean at the 40 m mip against mip 0 | within 2 % | layering.md |
| T7 memory | sum per building and per estate | unique ≤ 40 MB per building; shared ≤ 128 MB; Godot Mobile textures ≤ 4096 per side | [C 26; I] |
| T8 parity | numpy against the engine golden crop | mean ΔE00 ≤ 2 | [I] |

### 10.11 Order of work [I]

1. Keep the rules. Export `M_hi`, `M_lo` and `tint` per depth layer, beside today's albedo sheet.
2. Re-tile the coat base at 2.0 m; equalise the micro heights; make the run-off and growth micros.
3. Write `shader_contract.json`; build `engine_preview.py` from `closeup.py`; gate its 50 px/m output.
4. Move rust runs, cracks, efflorescence, spall halos and hero leaks to a decal list and atlas.
5. Build the trim sheet and the kit's trim UVs, with bevel strips.
6. Generate the UE material function and the Godot shader from the contract, and check parity.
7. Add T1–T8 to the gate, and the budgets to the asset README.

**For the skill** [I]: a reference (say `procedural-materials/references/texturing-at-scale.md`)
with the split rule (tiling for surfaces, trims for edges, decals for marks, masks for where), the
density table, mask packing, the edge rule, engine decal limits, budget maths and T1–T8.

## 11. What I could not find

- Spider-Man's building materials (the talk is members-only) and AC Unity's facade texturing.
- Star Citizen's layer shader; Hitman (IOI) and The Division 1 building materials; Naughty Dog's
  vertex-blend recipe (the TLOU2 slides are a 152 MB PPTX that I did not open).
- Cyberpunk's mask resolution; any studio's published mask px/m or decals per building; City
  Sample's shader specifics.
- Nanite tessellation's status in UE 5.7 and 5.8; texture streaming in Godot 4; an Epic statement
  on PerInstanceCustomData with Nanite. Polycount, ArtStation, CG Channel, Doom Wiki and the GDC
  schedule refused the fetcher; their claims are marked (snippet).

## 12. Sources

1. Maxon, Cinema 4D help, Texel Density: https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
2. T. Dries, Beyond Extent, Texel Density deep dive: https://www.beyondextent.com/deep-dives/deepdive-texeldensity
3. S. D. Burns, Beyond Extent, Trimsheets deep dive: https://www.beyondextent.com/deep-dives/trimsheets
4. M. Olsen (Insomniac), The Ultimate Trim, GDC 2015: https://gdcvault.com/play/1022323/The-Ultimate-Trim-Texturing-Techniques
5. CG Channel on J. Lazzaro's Ultimate Trim tools (snippet): https://www.cgchannel.com/2019/07/download-justen-lazarros-free-ultimate-trim-texturing-tools
6. Polycount, Ultimate Trim discussions (snippet): https://polycount.com/discussion/comment/2793276 (sources 5 and 6 are search excerpts only)
7. Microsoft, Texture Block Compression in Direct3D 11: https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11
8. M. Mikkelsen, Practical Real-Time Hex-Tiling, JCGT 11(3), 2022: https://jcgt.org/published/0011/03/05/paper.pdf
9. E. Heitz & F. Neyret, HPG 2018: https://eheitzresearch.wordpress.com/722-2/ · T. Deliot, Unity: https://unity.com/blog/engine-platform/procedural-stochastic-texturing-in-unity
10. Texture Variation node, 5-Minute Materials (video description, not watched): https://www.youtube.com/watch?v=yMmUdoAVfOs
11. Unreal forum, Macro Texture Variation (snippet): https://forums.unrealengine.com/t/texture-visible-lines-when-tiling/379361
12. Epic, Using Material Layers: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-material-layers-in-unreal-engine
13. Epic, Decal Materials (DBuffer, mesh decals): https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine
14. Epic, Nanite Virtualized Geometry: https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
15. Epic, Mesh Paint Mode: https://dev.epicgames.com/documentation/en-us/unreal-engine/activating-and-using-mesh-paint-mode-in-unreal-engine
16. Epic, Streaming Virtual Texturing: https://dev.epicgames.com/documentation/en-us/unreal-engine/streaming-virtual-texturing-in-unreal-engine
17. Epic, Runtime Virtual Texturing: https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine
18. Epic, Nanite Tessellation (text not readable by the fetcher; facts via search): https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-tessellation-in-unreal-engine · UE 5.4 release notes: https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5.4-release-notes?application_version=5.4 · 5.3 tutorial: https://dev.epicgames.com/community/learning/tutorials/RBvX/unreal-engine-new-in-unreal-5-3-tessellation-displacement-in-nanite-meshes-tutorial · forum, dicing rate and magnitude (snippet): https://forums.unrealengine.com/t/1296702
19. Epic, City Sample project: https://dev.epicgames.com/documentation/en-us/unreal-engine/city-sample-project-unreal-engine-demonstration
20. CG Channel, City Sample assets (snippet): https://www.cgchannel.com/2022/04/download-epic-games-free-city-sample-assets-for-ue5
21. ArtStation, The Matrix Awakens (snippet): https://zolord.artstation.com/projects/3qZYPm
22. SideFX, Houdini Engine for Unreal, instancing: https://www.sidefx.com/docs/houdini/unreal/instancing.html
23. SideFX and Embark, the procedural buildings of THE FINALS: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
24. Godot, Using decals: https://docs.godotengine.org/en/stable/tutorials/3d/using_decals.html
25. Godot, Shading language: https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html
26. Godot, Importing images: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_images.html
27. Godot, MultiMesh (INSTANCE_CUSTOM): https://docs.godotengine.org/en/stable/classes/class_multimesh.html
28. UDIM Shader Material addon for Godot 4.2: https://github.com/pkmollman/godot-udim-material-addon
29. K. Krzyścin (CDPR), Cyberpunk 2077: a world full of Substance: https://www.adobe.com/products/substance3d/magazine/cyberpunk-2077-a-world-full-of-substance.html
30. RED modding wiki, Multilayered: https://wiki.redmodding.org/cyberpunk-2077-modding/for-mod-creators-theory/materials/multilayered
31. Substance Magazine, The Division 2: https://magazine.substance3d.com/the-division-2-how-to-leverage-the-entire-substance-toolset-for-aaa-game-production/
32. N. Phail-Liff & A. Vitale, The Order: 1886, SIGGRAPH 2015: https://history.siggraph.org/wp-content/uploads/2022/10/2015-Talks-Phail-Liff_Crafting-Victorian-London-The-Environment-Art-and-Material-Pipelines-of-The-Order-1886.pdf · Polycount thread, 512 px/m (snippet, unverified): https://polycount.com/discussion/comment/2258297
33. A. Courrèges, DOOM (2016) graphics study: https://www.adriancourreges.com/blog/2016/09/09/doom-2016-graphics-study/
34. Doom Wiki, id Tech 6 (snippet): https://doomwiki.org/wiki/Id_Tech_6
35. Wikipedia, id Tech 7 (citing GDC 2019 and Digital Foundry): https://en.wikipedia.org/wiki/Id_Tech_7
36. U. Haar & S. Aaltonen, GPU-Driven Rendering Pipelines, SIGGRAPH 2015: https://advances.realtimerendering.com/s2015/index.html
37. Insomniac, look creation of Manhattan, GDC 2019: https://gdcvault.com/play/1026495/-Marvel-s-Spider-Man · D. Santiago, Spider-Man, meet Houdini: https://vimeo.com/326448655 · 128 m tiles: https://blog.playstation.com/?p=204132
38. Naughty Dog, Technical Art of Uncharted 4: https://advances.realtimerendering.com/other/2016/naughty_dog/index.html · SIGGRAPH 2020: https://www.naughtydog.com/blog/naughty_dog_at_siggraph_2020 · Kotaku on the TLOU2 slides (snippet): https://kotaku.com/so-much-work-went-into-the-last-of-us-part-iis-eyes-1845162613
39. CryEngine, Blend Layer (snippet): https://www.cryengine.com/docs/static/engines/cryengine-3/categories/1114113/pages/1048616
40. SideFX, Project Titan EVO: https://www.sidefx.com/titan-evo/
41. Epic, UE 5.7 release notes (snippet): https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-7-release-notes
42. Unreal forum, PerInstanceCustomData and HISM (snippet): https://forums.unrealengine.com/t/perinstancecustomdata-not-working-in-hism/465717

**Repo** ("repo" in the tags): `scripts/weathering/weather_fields.py` (`material_map`, `composite`),
`closeup.py` and `material.py`; `examples/danchi/tex/round_e/*_meta.json`; `examples/danchi/README.md`
(engine notes, decal counts, limits); `docs/redesign/research/weathering-grid-breakup.md` (§1.1, §5);
`.claude/skills/procedural-materials/references/layering.md` and `concrete.md`. The maths scripts
(`tex_maths.py`, `tex_budget.py`) are in the session scratchpad, not in the repo.
