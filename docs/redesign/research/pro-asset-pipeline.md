# The professional pipeline for large modular architecture (UE5 and Godot 4)

Date: 2026-11-07. Scope: how AAA and AA environment teams take a large modular architectural asset (a building,
an estate, a kit) from brief to shipped in Unreal Engine 5 and Godot 4. It covers the stages, what each one
delivers, the checks and numbers used at each, where a generator-driven pipeline like ours parts from a
hand-authored one, and what differs in Godot. It follows the round-I verdict that "the texturing was a big miss":
until round I, all weathering lived in one 50 px/m sheet per facade. It does not repeat what the skills and
earlier notes already hold: the metrics contract, kit taxonomy and beauty corners (`metrics-and-kits.md`); the five
texture carriers, densities and budgets (`large-scale-texturing`); ORM packing and normal Y (`surfacing.md`); UCX
naming and Houdini Engine attributes (`game-output.md`).

## Conventions

- Tags: **[C]** consensus or vendor documentation, **[P]** a practitioner's or one studio's practice, **[M]**
  measured data, **[I]** my inference. **[n]** is a source in §6. "(snippet)" means I saw the claim only in a
  search summary.
- Versions: Epic served its UE 5.8 pages; Godot's "stable" docs are 4.7. Godot 4.8 was in dev snapshots
  (dev 5, 2026-09-10).
- Repo facts are from `examples/danchi/README.md`, `examples/danchi/src/py/checks.py` and
  `scripts/weathering/wx_texcheck.py` [41].
- The web-search budget, shared by every agent in this round, ran out before the end. §5 lists what went
  unchecked.

## 1. Summary

1. **Pros write the numbers before the art, and a gate measures each one on what ships.** A studio's spec gives the
   engine and platform, triangle budgets per LOD, texel density, material-slot limits, collision type and naming
   [P, snippet][42]. Our README said "Texel density 512 px/m", but no check measured it on the exported mesh: our
   T1 measures each detail tile's authored density, not the shipped asset [M][41]. A number without a measurement
   is how the miss stayed invisible for several rounds [I].
2. **Studios judge what ships, in the engine.** Epic's tools are made for this: texture-streaming accuracy views
   (white is good, red is 2+ mips missing), Required Texture Resolution, and the Nanite Overdraw and Triangles
   views [C][2][8]. CDPR matched Painter to the engine, and Massive previewed the real shader [P][43]. Our review
   images came from Karma and a numpy mirror; no engine has yet rendered our shaders [M][41].
3. **Procedural studios deliver kits and instances, not unique merged meshes.** City Sample: "Each building in
   the city is made up of hundreds of instances", and "Very little custom geometry is used" [C][4]. The Matrix
   Awakens has 7,000 buildings from thousands of modular pieces (snippet) [M][6]. Embark merges details into the
   building mesh only because destruction needs it; ARC Raiders, with no destruction, instances them [P][17].
   Danchi's LOD0 is one unpacked 79 MB FBX with 16 material slots [M][41].
4. **Material count is the draw-call budget.** Epic: "Ideally, you should have 1 material per mesh", and Nanite
   "uses one draw call per material" [C][3]. Community frame budgets run from about 1,000 draw calls (PS4,
   Switch) to 3,000 (PS5, Series X) and 5,000 (high-end desktop) [P][34]. Nanite's cost grows with shading bins,
   one per unique material (forum) [P][36].
5. **UE5 and Godot 4 need two builds of the same asset.** Nanite means no LOD chain, Opaque and Masked materials
   only (so glass and mesh decals stay non-Nanite), and fewer vertices than triangles [C][1][2][4]. Godot means
   authored LODs and visibility-range HLOD, occluders baked only from MeshInstance3D, automatic instancing only on
   Forward+, and, on Mobile and Compatibility, LightmapGI with UV2 as the only GI [C][24][25][26][27][28]. One plan
   should emit both builds [I].
6. **Generators miss in their own ways.** A generator writes data at the density its rules were tuned at, makes
   unique geometry where instances belong, grows a material slot per feature, renames things on regeneration,
   emits no collision, occluders or UV2 unless told to, and is validated on one seed. Pros answer with generated
   engine products (Embark's collision and occluders, Insomniac's distant LODs) and automated checks [P][17][18].
7. **Small handoff settings fail silently.** Units: Houdini works in metres and UE in centimetres, so FBX imports
   at a uniform scale of 100 [C][15]. Normal Y: Godot expects OpenGL, UE DirectX [C][23]. Vertex colour: Godot's
   docs advise "Is sRGB", but our `Cd` is linear [C][30][M][41]. Non-power-of-two textures may not stream in UE
   (snippet) [P][35]. World-projected sampling is invisible to UE's texture streamer, which falls back to
   "texcoord 0 and a scale of 1" [C][8]. One round-trip test asset catches all five [I].
8. **Godot has no virtual texturing, material layers, anti-tiling or Nanite.** Shader layering is ours to write,
   as it already is. Godot 4.8 dev builds add mip streaming through a "Texture2D Streamed" import type [C][33].

## 2. The pipeline, stage by stage

| Stage | Deliverables | Gate (numbers) |
|---|---|---|
| 0 Brief and spec | art bible, reference counts, visual target; a technical spec per asset family | every spec number has a check that runs on the export |
| 1 Blockout, metrics | metrics table, blockout kit, stress-test map | Stack, Gap, Loopback; scale and axis round trip; watertight inputs |
| 2 Kit and surface plan | piece list with usage; a carrier, density and material per surface class | slots per piece and materials per building within budget |
| 3 Modelling | pieces at LOD0; damage variants | vertex : triangle ≤ 1 (Nanite); no stacked near-coplanar shells; triangles per piece |
| 4 UVs | UV0 for texture, UV1/UV2 for lightmaps where needed | measured density per class within ±25 %; lightmap charts with no overlap and padding |
| 5 Materials, textures | master materials and instances, tiling sets, trims, decals, masks | import settings per map; power-of-two sizes; streaming accuracy white |
| 6 LOD, HLOD | LOD chain or Nanite; HLOD or visibility ranges; impostors | LOD value within 3 %; draw calls at distance |
| 7 Collision, occlusion | hulls or primitives; occluders (Godot) | names per engine; occluders closed and opaque |
| 8 Export, import | FBX, glTF or USD; engine import presets; names | re-import in each engine; names stable from the last export |
| 9 Validation, sign-off | validator report; in-engine captures at gameplay cameras | all gates pass at the heaviest preset and over a seed sweep |

### 2.0 Brief, art bible and technical spec

- **The art side is covered:** brief, counted reference, visual target, art bible (`art-direction.md`,
  `believability.md`).
- **The technical spec.** Outsourcing guides list the engine version and platform, triangle budgets per category
  and per LOD, texel density, a material-slot limit (for example "maximum two"), collision type, LOD count, naming
  and the normal-map convention. Deliveries are checked by tool first, then by hand (snippet) [P][42]. Our brief
  has triangles and texture sizes, but no slot, draw-call or density check [M][41].
- **The renderer decision belongs here.** In Godot it decides decals, GI, instancing and compression (§2.8). In UE,
  Nanite and Lumen decide whether LODs and lightmap UVs exist at all [C][1][27].
- **Texel density.** No studio publishes a standard (snippet) [P][39]. 1,024 px/m (10.24 px/cm) is the common
  current-gen figure, and 512 px/m is usual for third person. Sources mix px/cm and px/m, so state the unit. Screen
  maths gives 960/d px/m at 1080p and 1,920/d at 4K for a 90° FOV at d metres (`texturing-at-scale.md` §2) [I].

### 2.1 Blockout and metrics

- **Stress tests** (Level Design Book): "do NOT just stop at an ideal case" [P][34]. **Stack** checks multi-level
  stacking, with floors that "should NOT be paper thin"; **Gap** checks glue pieces for off-angle joins;
  **Loopback** is named but not explained. Our SKILL Phase 2 already tests odd widths, corners and setbacks [M][41].
- **Watertight input.** Embark requires it, so that interior faces and fracture work [P][17].
- **Scale and axes.** A 1 m Houdini cube is 1 m in Godot ("1 unit being equal to 1 meter") [C][29]. In UE, import
  FBX at a uniform scale of 100 [C][15]. A Framestore supervisor on SideFX's forum advises leaving Houdini's Convert
  Units alone, because it depends on a hip-file setting (snippet) [P][15]. Houdini's FBX exporter handles the Y-up
  to Z-up change, and SideFX recommends the FBX 2018 SDK (snippet) [C][15].
- **Godot's frame.** Right-handed and Y-up; the camera looks down −Z; an oriented asset's front is +Z; on maps,
  +Z is south [C][29]. Danchi's balconies already face +Z, the south [M][41].

### 2.2 Kit plan and surface plan

- **Plan the kit by use.** Decide kit percentages and granularity, then "DO NOT MAKE VARIANTS YET" [P][34]. Usage
  counts show where polish pays; our golden piece covers this [M][41].
- **The surface plan is the step we skipped.** Before texturing, pros name a carrier (tiling, trim, decal, mask or
  unique), a density, a texture set and a material for each surface class. Insomniac standardised one trim layout
  for a whole game; The Order: 1886 used 90–95 % tiling materials [P][43]. Danchi decided its carriers only in
  round I [M][41].
- **The material plan.** A few master materials with instances. Variation goes into data, not new materials: UE's
  Custom Primitive Data (per component) and Per Instance Custom Data (per ISM/HISM instance), which Epic says cut
  draw calls compared with dynamic material instances (snippet) [C][10]; Godot's `INSTANCE_CUSTOM` and instance
  uniforms (`texturing-at-scale.md` §8).

### 2.3 Modelling: high to low, mid-poly, or Nanite

- **Hand pipelines** bake high to low for hero pieces, and use chamfers with weighted normals or trim bevels for
  kits (`metrics-and-kits.md`).
- **Nanite (UE).** Epic recommends it for meshes with many or tiny triangles, many instances, major occluders or
  Virtual Shadow Map casting [C][1]. It takes Opaque and Masked materials only; an unsupported material becomes a
  default material, and mesh decals need translucency, so they cannot be Nanite. World Position Offset must be
  clamped, and a scene holds at most 16 million streamed-in instances [C][1]. In City Sample, every static mesh is
  Nanite and none uses traditional LODs [C][4].
- **Nanite numbers [C][2].** A mesh should have fewer vertices than triangles; 2:1 suggests a problem, 3:1 is fully
  faceted. Closely stacked surfaces near the top surface overdraw: "Layers 10 cm apart can overlap at range". The
  Overdraw view is "the most effective way" to find this.
- **Godot has no Nanite.** Its LOD0 must meet a triangle budget and carry LODs (§2.6). An asset for both engines
  needs a LOD0 at Godot's budget, with UE-only detail (geometric damage, dense bevels) as a branch [I].

### 2.4 UVs and texel density

- **Channels.** UE: UV0 carries texture, and lightmap UVs are generated from channel 0 into a later channel [C][9].
  Godot: UV and UV2; UV2 serves lightmaps, or the detail layer and AO [C][27][30].
- **Lightmap UVs or not.** In UE under Lumen, no: without Lightmass, Epic recommends turning Generate Lightmap UVs
  off [C][1]. In Godot Mobile and Compatibility, yes: LightmapGI and reflection probes are the only GI there, and
  lightmaps bake only in the editor, so they do not suit buildings generated at runtime [C][27].
- **UV2 rules.** Godot [C][27]: faces must not share lightmap pixels; generate on import with Light Baking set to
  Static Lightmaps; texel size defaults to 0.2 m, with 0.5 m or more for large scenes; keep `*.unwrap_cache` in
  version control; a mesh reused at "more than half or twice" its scale loses quality. UE: Min Lightmap Resolution
  sets the chart padding; make it a power of two, "the lowest lightmap resolution that this mesh would ever use"
  [C][9].
- **Measuring density.** Per face, in px/m: √(UV area × texture pixels ÷ world area) [C][43]. In UE, Mesh
  UV Density Accuracy and Material Texture Scale Accuracy show what the streamer believes: red 2+ mips missing,
  yellow 1 missing, white good, cyan 1 extra, green 2+ extra. Required Texture Resolution with
  `r.Streaming.DropMips 2` shows whether the right mips load. When the build cannot identify a texture's texcoord
  and scale, the streamer assumes "texcoord 0 and a scale of 1" [C][8].

### 2.5 Materials and texturing

- **Covered:** the split into tiling, trims, decals and masks, and its densities (`large-scale-texturing`).
- **UE 5.7:** Substrate and PCG are production-ready (snippet) [C][13]. Runtime virtual texturing is for terrain
  blending (`texturing-at-scale.md` §7).
- **Godot:** `StandardMaterial3D` and `ORMMaterial3D` have one Detail layer (a mask with Mix, Add, Sub or Mul, on
  UV1 or UV2), and World Triplanar keeps a texture continuous across separate objects [C][30]. There are no
  material layers, height blends, anti-tiling or virtual textures; those need custom shaders.
- **Import settings that matter [C][23][I]:**

| Map | Unreal 5 | Godot 4 |
|---|---|---|
| Albedo | Default compression, sRGB on | VRAM Compressed (S3TC or BPTC on desktop, ETC2 or ASTC on mobile); `source_color` in shaders |
| Normal | Normalmap (BC5), DirectX Y−; flip green for maps authored in OpenGL [I] | OpenGL Y+; "Normal Map Invert Y" for DirectX maps; RGTC with z rebuilt; `hint_normal` |
| ORM, masks, reveal heights | Masks (sRGB off); single channels as BC4 (the Alpha setting) | linear (no `source_color`); High Quality (BPTC, ASTC) only on Forward+ and Mobile |
| Sizes | pad non-power-of-two sizes for streaming (snippet) [P][35] | power of two "recommended, but is not required"; mobile and web usually ≤ 4,096 |

- **Size traps.** In UE, mips for non-power-of-two textures arrived in 5.1, but streaming wants powers of two, and
  a texture that is neither a power of two nor a multiple of 4 loses compression and mips (snippet) [P][35].
  Danchi's `M_hi` masks are 4,095 × 1,815; pad them to 4,096 × 2,048 (`texturing-at-scale.md` §10.2).
- **Godot details [C][23]:** "Mipmaps > Limit is currently not implemented"; Roughness > Src Normal filters
  roughness from the normal map against specular aliasing.

### 2.6 LODs, HLODs and impostors

- **UE.** Nanite meshes need no LOD chain [C][4]. World Partition HLOD layers [C][7]: Instancing ("ideal for
  imposter meshes"), Merged Mesh, and Simplified Mesh, whose Merge Distance "can close gaps like doors and windows
  in distant geometry". Approximated and Custom types exist, undocumented on that page. HLOD meshes can be Nanite.
  City Sample's quick start builds HLODs for World Partition [C][5].
- **Godot.** Import builds LODs with meshoptimizer and switches at 1 px of error by default ("perceptually
  lossless"); `lod_bias` adjusts it per instance [C][24]. Artist-made LODs use visibility ranges, and Visibility
  Parent builds an HLOD. Fade mode Disabled (hysteresis) is the cheapest; Self and Dependencies force transparency
  while they fade [C][25]. A MultiMesh picks one LOD for all its instances, from its bounding box's nearest point,
  and culls as one node [C][24].
- **Automated distant LODs.** Insomniac's manual distant-LOD process stopped scaling when Spider-Man 2's city
  doubled, so the studio automated it with mesh analysis (GDC 2024; listing only) [P][18].
- **Covered:** LOD value match within 3 % (`procedural-assets` SKILL Phase 7).

### 2.7 Collision and occlusion

- **UE.** UCX hulls are covered (`game-output.md`). City Sample uses custom meshes for collision [C][4]. Embark
  builds collision automatically: each feature node stores a planar proxy, a 2D convex decomposition turns it into
  hulls, adjacent hulls are merged after fracture, and occluders are generated last [P][17].
- **Godot collision** (import suffixes) [C][20]: `-col` makes trimesh collision, "slow but accurate"; `-convcol` a
  convex shape; `-colonly` and `-convcolonly` keep only the collision. The docs advise "try to use a few primitive
  collision shapes".
- **Godot occlusion is not automatic** [C][20][26]. Enable it, then bake an `OccluderInstance3D`. Only
  MeshInstance3D nodes with opaque materials are baked, not MultiMesh, particles or CSG. Large walls work best, and
  the Mobile renderer gains the most. A moving occluder rebuilds its BVH. Scripts can build an `ArrayOccluder3D`
  for procedural content, and the `-occ` and `-occonly` suffixes make occluders from meshes.

### 2.8 Export, import and naming

- **Formats.** UE imports FBX, glTF and USD through Interchange; its USD translator lists static meshes, materials
  and textures (snippet) [C][14]. Godot recommends glTF 2.0, reads FBX through ufbx since 4.3, does not recommend
  FBX2glTF, and needs Blender installed for `.blend` [C][21]. Houdini 22's ROP GLTF 2.0 writes Draco, documents
  no instancing, and does not export `doubleSided` [C][16].
- **Import options.** Godot: Ensure Tangents (MikkTSpace), Generate LODs, Create Shadow Meshes, Light Baking, Apply
  Root Scale [C][22]. UE: Build Nanite; Generate Lightmap UVs off without Lightmass [C][1].
- **The Godot renderer matrix:**

| Feature | Forward+ | Mobile | Compatibility |
|---|---|---|---|
| Decal nodes | yes (512 clustered elements in view, shared with lights and probes) | yes (8 per mesh) | no |
| GI | SDFGI, VoxelGI, LightmapGI, SSIL, probes | LightmapGI, probes | LightmapGI, probes |
| Automatic instancing | yes (opaque or alpha-tested) | no: use MultiMesh | no: use MultiMesh |
| BPTC/ASTC ("High Quality") | yes | yes | no |
| Occlusion-culling gain | smaller (has a depth prepass) | largest | — |

  Sources: [C][23][26][27][28]; decal limits from `texturing-at-scale.md` §6.
- **Vertex colour.** Godot's docs say "Is sRGB should be enabled for most modeling exports", and the `-vcol` suffix
  sets that flag [C][20][30]. Danchi's `Cd` is linear, so following that advice would decode it twice [M][41][I].
  Through Houdini Engine, UE once converted vertex colours wrongly (fixed in Houdini Engine 2.1.1), and the FBX
  importer's vertex-colour option must be set by hand (snippet) [P][38].
- **Naming.** Epic's pattern is `[AssetTypePrefix]_[AssetName]_[Descriptor]_[OptionalVariantLetterOrNumber]`, with
  prefixes such as `SM_`, `M_`, `MI_` and `T_`; it lists no texture suffixes, so `_D`, `_N` and `_ORM` are
  community use [C][11]. Godot uses snake_case files and folders (exported PCKs are case-sensitive), PascalCase
  nodes, and assets kept near the scenes that use them [C][31].
- **Generator handoff traps.** Labs Trim UVs were reported lost on the way into UE in 2025 (snippet) [P][19].
  City Sample's rule processor fails when a point attribute such as `Building_ID` is missing; users call it "so
  many tiny kinks" (snippet) [P][40].

### 2.9 Validation and sign-off

- **Automated.** UE's Data Validation runs `EditorValidatorBase` subclasses (`can_validate_asset`,
  `validate_loaded_asset`); Python validators must register themselves (snippet) [C][12]. A check on the DCC side,
  before export, catches more and earlier [I].
- **Manual, in the engine.** UE: the Nanite Overdraw and Triangles views [C][2], the streaming-accuracy views
  [C][8], and a PBR validation view mode (a post-process material before tone mapping that flags albedo out of
  range) (snippet) [P][37]. Godot: the viewport debug-draw modes, such as overdraw and unshaded [I].
- **Capture.** Godot's Movie Maker renders fixed frames with "perfect frame pacing", also in exported projects:
  `--write-movie shot.png` (the `.png` extension picks the writer), `--fixed-fps`, `--quit-after N` and
  `--resolution`, with the window clamped to the display [C][32].
- **Sign-off.** "Profiling should be the first step of any optimization pass!" [P][34]. Epic: measure instance
  counts, triangles per mesh and material complexity "for any combination of content and hardware" [C][1].

## 3. What a generator-driven pipeline tends to miss

1. **Resolution follows the rule grid, not the camera.** A hand artist paints at the texture's resolution and sees
   it in the engine. A generator writes at whatever density its rules were tuned at (50 px/m), the gates check the
   rules, and nobody counts texels per screen pixel at the closest camera. That was our miss [M][41][I].
2. **Unique geometry by default.** Every output is a fresh mesh, merged for convenience: danchi's LOD0 FBX is
   79 MB unpacked, and its README admits "an engine build should instance the kit pieces" [M][41]. City Sample and
   The Matrix Awakens build from instances [C][4][M][6].
3. **A material slot per feature.** Danchi has 16 slots at LOD0, 14 at LOD1 and 3 at LOD2 [M][41]. With instancing,
   each piece type times each slot is a draw call; under Nanite each unique material is a shading bin
   [C][3][P][36].
4. **Engine products appear only when the code makes them.** A hand checklist asks every asset for collision,
   occluders, UV2, LODs and sockets; a generator emits only what it was written to emit. Danchi has UCX hulls, but
   no Godot collision, occluders or UV2 [M][41]. Embark automated collision and occluders; Insomniac automated
   distant LODs when manual work stopped scaling [P][17][18].
5. **Topology that engines punish.** Unshared vertices raise the vertex-to-triangle ratio [C][2], and coplanar
   shells z-fight. Danchi's decals sit 4–10 mm off the wall, up to six deep on a parapet [M][41]: overdraw and
   sorting cost in Godot, and close stacking near a Nanite wall [C][2][28]. Non-watertight inputs break interiors
   and fracture [P][17].
6. **Unstable identity.** Mesh names, slot names and instance ids can change on regeneration, which breaks engine
   references and overrides [P][40][I]. Embark keeps hand edits as world-space data (covered,
   `generator-architecture.md`).
7. **Validated on one seed and one preset.** Budgets are checked at Typical, but danchi's LOD1 reaches 99,946
   triangles at age 60 and upkeep 0.1, against a 100k cap, because its decals grow with weathering [M][41]. Kit
   artists stress-test the extremes [P][34]; a generator needs that over its preset strip and a seed sweep [I].
8. **An offline renderer as the judge.** Engine limits surface only on import: Nanite's opaque-or-masked rule,
   Godot's decal caps, Mobile's GI, texture streaming [C][1][27]. The numpy mirror shows the shader's maths, not the
   engine's streaming, compression or tone mapping [I].
9. **Projection hides density from the streamer.** Facade masks are sampled by planar projection. When UE's build
   cannot identify a texture's coordinates, its streamer assumes UV0 at scale 1 [C][8], so it may stream the wrong
   mips: "blurry up close" again [I].
10. **Seams between pieces that pick LODs on their own.** Godot picks a LOD per mesh instance, so neighbouring kit
    pieces at different auto-generated LODs may not meet unless their border vertices are locked [I] (§5).

**What pros do differently for procedural buildings:**

- **Generate the boring parts; hand-make the visible modules.** Embark generates slabs, walls, interior faces,
  booleans, decals and hulls, and artists make windows, cornices, railings and roof pieces [P][17].
- **Generate the engine products too:** collision and occluders (Embark), HLOD (City Sample), distant LODs
  (Insomniac), instances from point clouds (City Sample's Rules Processor) [P][5][17][18].
- **Keep iteration short and local.** Embark goes from blockout to a fractured building in about 4–6 minutes per
  change; feature nodes declare dependencies, so a window edit does not recook everything [P][17].
- **Consider engine-side generation.** UE's PCG has shape-grammar nodes (Subdivide Spline and Subdivide Segment)
  for placing kit modules along footprints (snippet) [C][13]. SideFX's Project Titan turns boxes placed in Unreal
  into buildings of instanced modules [P][19].

## 4. Recommendations for our skills

Ranked by how much each would change outcomes. "Covered" rows are kept for completeness.

| # | Finding | Why it matters for us | Concrete change | Skill file | Sources |
|---|---|---|---|---|---|
| 1 | Pros write a technical spec, and gates measure every number in it | Density was a README sentence for several rounds, and carriers were chosen after the miss | Phase 0–1 gate: a `spec.json` with targets (UE 5.7+, Godot 4.7 and its renderer); closest camera per surface class; per class: carrier, density ±25 %, tile period, texture set; budgets: triangles per LOD, ≤ 3 slots per piece, ≤ 8 unique materials per building at LOD0 and ≤ 2 at HLOD [I], texture MB, decals per m², collision type. The validator (#2) reads it | `procedural-assets/SKILL.md` Phases 0–1; `references/metrics-and-kits.md` | [3][34][42][I] |
| 2 | Studios validate every export automatically, at the batch level | Our gates measure the rules and the authored tiles, not the shipped mesh; `checks.reimport()` counts slots and UV presence only | New `scripts/asset_check.py`, run after every export over the preset strip and ≥ 4 seeds. **Fail if:** measured density per class (√(UV area × texture pixels ÷ world area), with world-UV tile sizes from the shader contract) is under 0.5× its target anywhere, or under 90 % of the area within ±25 %; slots or triangles exceed the spec at the heaviest preset; Nanite meshes reach vertex:triangle ≥ 2 (warn above 1); textures are not powers of two; UV1/UV2 overlap or have under 2 texels of padding at the lowest lightmap resolution (when lightmaps are specified); either engine's collision names are missing; mesh or slot names changed with no version bump; or the bounding box differs from the contract by more than 1 cm | `procedural-assets/references/game-output.md`; SKILL Phase 7 gate | [1][2][9][27][35][I] |
| 3 | Judge in the engine from the golden bay on | No engine has rendered our shaders; the parity check is a release item | At the Phase 3–4 gates, import the golden bay into Godot 4.7 (Forward+ and Mobile). Capture fixed cameras at 2, 10 and 30 m, at 1080p and 4K, with Movie Maker (`--write-movie f.png --fixed-fps 1 --quit-after 3`). Compare with the numpy mirror (mean ΔE00 ≤ 2) and review side by side. Add UE when it is installed. The parity check moves from "release" to every round | `procedural-assets/SKILL.md` Phases 0, 3, 4; `large-scale-texturing/SKILL.md` checks | [32][43] (partly covered: `surfacing.md` "in the target renderer early") |
| 4 | Ship kits and instances; merge only for HLOD | A 79 MB merged LOD0 defeats instancing, streaming and draw-call budgets | LOD0 = kit meshes plus an instance list: Houdini Engine instancers, a USD point instancer, or a Godot scene with one MultiMesh per piece type per facade (Mobile, Compatibility) or MeshInstance3D nodes (Forward+). Report instanced against unique triangles; unique connective geometry ≤ 25 % of LOD0 [I]. Fail on a single merged LOD0 | `game-output.md` (stated there, not enforced) | [4][6][17][24][28] |
| 5 | Material count is the draw-call budget | 16 slots at LOD0; each costs per piece type, or per shading bin under Nanite | Budgets from #1. Fold minor slots (`board`, `frp`, `plastic`, `sign`, `fabric`, `room`) into one atlased props material. Vary through per-instance data (Custom Primitive Data, Per Instance Custom Data, Godot `INSTANCE_CUSTOM`), not new materials. Aim for ≤ 50 draw calls per building at LOD0 without Nanite (a 3,000-call frame, 20 buildings taking a third) [I] | `game-output.md`; `procedural-materials/SKILL.md` (material plan) | [3][10][34][36] |
| 6 | UE5 and Godot need two builds of one plan | Nanite rules and Godot's LOD, culling and GI rules conflict | `ue_nanite` build: kit pieces Nanite-on; glass, decals and anything translucent as separate non-Nanite meshes; no LOD chain; HLOD with Instancing near and Simplified Mesh far, with Merge Distance closing windows. `godot` build: authored LOD1 and LOD2 on visibility ranges (fade Disabled, 2–5 m margin [I]); Visibility Parent pointing at a merged building HLOD; one MultiMesh per piece type per facade; Generate LODs off on kit pieces whose edges must meet [I] | `game-output.md` (new section) | [1][2][7][24][25] |
| 7 | In Godot, the renderer decides decals, GI, instancing and compression | Compatibility has no Decal nodes; Mobile has only LightmapGI; only Forward+ auto-instances | Put the renderer matrix (§2.8) in the brief template. The brief names the renderer, and the export follows from it | `game-output.md`; `large-scale-texturing/SKILL.md` "Engine hookup" | [23][26][27][28] |
| 8 | Generate collision and occluders for Godot from the plan | We make UCX only; Godot bakes no occluders from MultiMesh | Export `<building>_col-colonly` boxes per slab tier and balcony line, preferring primitives. Export `<building>_occ-occonly`: closed boxes inset 0.3 m behind each facade [I]. Keep UCX for UE | `game-output.md` | [17][20][26] |
| 9 | Decide on lightmap UVs per target | Godot Mobile and Compatibility have no GI without UV2 | If the spec needs lightmaps: UV2 per kit piece from Houdini (no overlap, ≥ 2 texels of padding at the lowest resolution), or Godot's import unwrap at a 0.5 m texel size for buildings. In UE under Lumen, leave lightmap UVs off | `game-output.md` "UVs" (partly covered) | [1][9][27] |
| 10 | One round-trip test asset catches silent handoff errors | Units, normal Y, vertex-colour space and non-power-of-two textures each fail quietly | A `handoff_test` export each round: a 1 m cube with a +Z arrow, a normal-map bump, an 11-step linear vertex-colour ramp, and a 4,095 × 1,815 texture. Pass: 1.00 m (100 cm in UE), front +Z (south) in Godot, the bump reads raised under a known light, the ramp is within 2/255 in an unlit material, and the texture has mips and streams after padding | `game-output.md`; `surfacing.md` (normal Y covered) | [15][23][29][30][35][38] |
| 11 | UE's streamer cannot see planar-projected masks | Wrong mips bring back blur at the close cameras | Check facade materials in Material Texture Scale Accuracy. Set facade masks to never stream (≤ 40 MB per building), and keep tiling sets on UV0 in metres so the streamer can measure them [I] | `large-scale-texturing/SKILL.md` "Engine hookup" and traps | [8][I] |
| 12 | Sign off with the engine's view modes | Overdraw, density and mip errors are invisible in a beauty render | Phase 9 adds UE's Nanite Overdraw, Mesh UV Density Accuracy (all white), Required Texture Resolution at the closest camera and a PBR validation view; in Godot, overdraw debug-draw on the decal layers and a draw-call count | `procedural-assets/SKILL.md` Phase 9 | [2][8][34][37] |
| 13 | Names and ids stay stable across regenerations | Re-imports and engine references break silently | UE names (`SM_Danchi_BalFront_01`, `MI_…`, `T_…_D/_N/_ORM`); snake_case files for Godot; the validator diffs names against the last export; stable keys such as City Sample's `Building_ID` | `metrics-and-kits.md` (readable names covered); `game-output.md` | [11][31][40] |
| 14 | Contract, stress tests, beauty corner | — | covered | `procedural-assets/SKILL.md` Phases 1–4; `metrics-and-kits.md` | [34] |
| 15 | Five carriers, densities, budgets, decal caps | — | covered | `large-scale-texturing/SKILL.md` and references | — |
| 16 | LOD value match, detail branch after the LOD split, UCX, Houdini Engine LOD groups | — | covered | `procedural-assets/SKILL.md` Phase 7; `game-output.md` | [7] |
| 17 | ORM packing, normal Y, albedo 30–240 sRGB | — | covered | `procedural-assets/references/surfacing.md` | [37] |

## 5. Unchecked

- **Pages not read, or searches cut short by the budget:** Epic's Matrix Awakens spotlight and its Fortnite Nanite
  blog (both 403); the GDC Vault recordings of Insomniac's 2024 talks and Embark's destruction talk. All Matrix
  Awakens figures are from search summaries.
- **Studio practice:** no public building-tool talks from Ubisoft (beyond Wildlands) or Guerrilla, and no published
  studio texel-density, draw-call or texture-memory budgets. The Level Design Book's numbers are community figures.
- **UE:** how Nanite shading bins scale with material instances against parent materials (forum only); whether
  non-power-of-two textures stream in UE 5.x (old forum answers); vertex-colour space on FBX import; the name of
  the "Flip Green Channel" texture setting; the default Min Lightmap Resolution; whether Substrate is on by default
  in new 5.7 projects; the Approximated Mesh HLOD type; whether the Nanite builder locks borders between meshes.
- **Godot and Houdini:** whether Godot's glTF importer converts `COLOR_0` from linear; LightmapGI with MultiMesh
  instances; whether automatic LOD locks open borders at kit seams; Movie Maker under `--headless`; which renderers
  Godot 4.8's texture streaming supports, and when 4.8 ships; whether Houdini 22's glTF ROP writes
  `EXT_mesh_gpu_instancing`, and whether Godot reads it.
- **My own numbers:** the ±25 % band, the 0.5× floor, ≤ 3 slots per piece, ≤ 8 materials per building, ≤ 50 draw
  calls per building, ≤ 25 % unique geometry, the 0.3 m occluder inset and the 2–5 m visibility margin are all
  [I]: starting points to calibrate on the first engine import.

## 6. Sources

1. Epic, Nanite Virtualized Geometry (UE 5.8): https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
2. Epic, Working with Nanite-enabled content: https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-naniteenabled-content
3. Epic, Reducing draw calls in Fortnite (UEFN): https://dev.epicgames.com/documentation/fortnite/reducing-draw-calls-in-fortnite
4. Epic, City Sample project: https://dev.epicgames.com/documentation/en-us/unreal-engine/city-sample-project-unreal-engine-demonstration
5. Epic, City Sample quick start (Houdini, Rules Processor, HLOD): https://dev.epicgames.com/documentation/unreal-engine/city-sample-quick-start-for-generating-a-city-and-freeway-in-unreal-engine-5
6. The Matrix Awakens, 7,000 buildings and 7 million instanced assets (snippet): https://www.unrealengine.com/wakeup · https://www.cgw.com/Press-Center/In-Focus/2021/The-Matrix-Awaits-in-The-Matrix-Awakens-An-Unrea.aspx · talk summary (80.lv, 2022-04-07): https://80.lv/articles/breakdown-creating-the-matrix-awakens-in-houdini-unreal-engine-5
7. Epic, World Partition HLOD: https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine
8. Epic, Building texture streaming data (accuracy view modes): https://dev.epicgames.com/documentation/en-us/unreal-engine/building-texture-streaming-data-in-unreal-engine
9. Epic, Generating lightmap UVs: https://dev.epicgames.com/documentation/en-us/unreal-engine/generating-lightmap-uvs-in-unreal-engine
10. Epic, Storing custom data in materials per primitive (snippet): https://dev.epicgames.com/documentation/en-us/unreal-engine/storing-custom-data-in-unreal-engine-materials-per-primitive
11. Epic, Recommended asset naming conventions: https://dev.epicgames.com/documentation/en-us/unreal-engine/recommended-asset-naming-conventions-in-unreal-engine-projects
12. Epic, EditorValidatorBase, Python API (snippet): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/EditorValidatorBase
13. Epic, Shape grammar with PCG (snippet): https://dev.epicgames.com/documentation/en-us/unreal-engine/using-shape-grammar-with-pcg-in-unreal-engine · UE 5.7 release, PCG and Substrate production-ready (snippet): https://www.awn.com/news/unreal-engine-57-now-available
14. Epic, Importing assets using Interchange (snippet): https://dev.epicgames.com/documentation/unreal-engine/importing-assets-using-interchange-in-unreal-engine
15. SideFX, Houdini Engine for Unreal, FBX (units, axes, FBX 2018) (snippet): https://sidefx.com/docs/houdini/unreal/fbx.html · forum on Convert Units (snippet): https://www.sidefx.com/forum/topic/78210 · https://www.sidefx.com/forum/post/333704
16. SideFX, glTF import and export (Houdini 22): https://www.sidefx.com/docs/houdini/io/gltf.html
17. A. Björkerud (Embark), Making the procedural buildings of THE FINALS, SideFX, 2026-02-11: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/ · 80.lv summary: https://80.lv/articles/how-embark-studios-built-procedural-environments-for-the-finals-using-houdini
18. S. Kircher (Insomniac), Applied Mesh Analysis: Automating Distant-City LODs in Marvel's Spider-Man 2, GDC 2024 (listing, snippet): https://gdcvault.com/play/1034212/Applied-Mesh-Analysis-Automating-Distant · D. Santiago, Procedural Tool Development for Marvel's Spider-Man 2, GDC 2024 (listing): https://gdcvault.com/play/1034803/Technical-Artist-Summit-Procedural-Tool
19. SideFX, Project Titan building tool: https://sidefx.com/tutorials/project-titan-building-tool · Titan EVO (tutorials dated October 2026): https://www.sidefx.com/titan-evo/ · forum, Labs Trim UVs lost through an HDA (2025, snippet): https://www.sidefx.com/forum/post/443166/
20. Godot 4.7, Node type customization (import suffixes): https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html
21. Godot, Available 3D formats: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html
22. Godot, Import configuration: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/import_configuration.html
23. Godot, Importing images: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_images.html
24. Godot, Mesh level of detail: https://docs.godotengine.org/en/stable/tutorials/3d/mesh_lod.html
25. Godot, Visibility ranges (HLOD): https://docs.godotengine.org/en/stable/tutorials/3d/visibility_ranges.html
26. Godot, Occlusion culling: https://docs.godotengine.org/en/stable/tutorials/3d/occlusion_culling.html
27. Godot, Using LightmapGI: https://docs.godotengine.org/en/stable/tutorials/3d/global_illumination/using_lightmap_gi.html · Introduction to global illumination: https://docs.godotengine.org/en/stable/tutorials/3d/global_illumination/introduction_to_global_illumination.html
28. Godot, Optimizing 3D performance: https://docs.godotengine.org/en/stable/tutorials/performance/optimizing_3d_performance.html
29. Godot, Model export considerations: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/model_export_considerations.html · Introduction to 3D: https://docs.godotengine.org/en/stable/tutorials/3d/introduction_to_3d.html
30. Godot, Standard Material 3D and ORM Material 3D: https://docs.godotengine.org/en/stable/tutorials/3d/standard_material_3d.html
31. Godot, Project organization: https://docs.godotengine.org/en/stable/tutorials/best_practices/project_organization.html
32. Godot, Creating movies (Movie Maker): https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html
33. Godot, Dev snapshot 4.8 dev 5 (texture streaming), 2026-09-10: https://godotengine.org/article/dev-snapshot-godot-4-8-dev-5/
34. The Level Design Book, Optimization (draw-call budgets): https://book.leveldesignbook.com/process/env-art/optimization · Modular kits (stress tests): https://book.leveldesignbook.com/process/blockout/metrics/modular
35. Non-power-of-two textures in UE (snippet): https://unreal-garden.com/tutorials/ui-texture-size/ · https://forums.unrealengine.com/t/about-non-power-of-two-texture2d/1667354
36. Nanite shading bins (forum, snippet): https://www.tech-artists.org/t/draw-call-optimization-in-ue5/18217 · https://forums.unrealengine.com/t/nanite-cpu-performance-with-large-open-world-many-materials-even-when-nothing-is-visible/2533778
37. H. Thiessen, a PBR validation view mode for Unreal (snippet): https://haukethiessen.artstation.com/blog/7AwM/tutorial-adding-a-pbr-validation-view-mode-to-unreal
38. SideFX forum, Houdini vertex colours in UE (snippet): https://www.sidefx.com/forum/post/398410 · https://forums.unrealengine.com/t/houdini-export-vertex-color-map-to-unreal-engine-fbx-abc/1254051
39. Texel-density figures (forum and vendor, snippet): https://forums.unrealengine.com/t/texel-density-standards-for-aaa-first-person-shooter-games/1646118
40. City Sample in Houdini, forum (snippet): https://forums.unrealengine.com/t/city-sample-in-houdini-cant-process-and-export/593207?page=4
41. Repo: `examples/danchi/README.md` (brief, budgets, engine notes, results, limits), `examples/danchi/src/py/checks.py` (`reimport()`), `scripts/weathering/wx_texcheck.py` (T1), `.claude/skills/large-scale-texturing/SKILL.md`
42. Outsourcing spec guides (snippet): https://programminginsider.com/what-programmers-should-put-in-a-3d-asset-spec-before-art-is-outsourced/ · https://www.strayspark.studio/blog/game-ready-asset-checklist-blender-2026
43. Repo research: `docs/redesign/research/texturing-at-scale.md` (Insomniac's Ultimate Trim, The Order: 1886, CDPR, Massive, density maths, mask sizes) and `r5-texture-layering.md`

## 7. Actions

Statuses as `scripts/research_actions.py` reads them (round J). Numbers are §4's.

| # | Action | Status |
|---|---|---|
| 1 | A `spec.json` written in Phase 0 and read by the gates | done (procedural-assets SKILL.md Phase 0 and gates) |
| 1b | The danchi's own `spec.json` | parked (written with the validator that reads it; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 2 | `scripts/asset_check.py` over the preset strip and 4 seeds | parked (its failures are specified in game-output.md; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 3 | Judge the golden bay in the engine from Phase 3 | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 4 | Ship kits and instances; fail on a merged LOD0 | parked (stated in game-output.md; enforced by #2; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 5 | Material and draw-call budgets | parked (budgets go in `spec.json`; enforced by #2; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 6 | Two builds from one plan (UE Nanite, Godot) | done (game-output.md, "Two builds from one plan") |
| 6b | The danchi exported as both builds | parked (revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 7 | The Godot renderer named in the brief | done (game-output.md) |
| 8 | Godot `-colonly` and `-occonly` from the plan | done (game-output.md table; the export is parked with 6b) |
| 9 | Lightmap UVs decided per target | done (game-output.md table: off under Lumen, UV2 for LightmapGI) |
| 10 | A `handoff_test` round-trip asset | parked (no export this round; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 11 | Masks and Unreal's streamer (Never Stream, or facade UV1) | done (large-scale-texturing SKILL.md import and streaming; the UE check waits for rank 1) |
| 12 | Sign-off with the engines' view modes | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 13 | Stable names diffed against the last export | parked (part of #2; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 14 | Contract, stress tests, beauty corner | done (covered: procedural-assets SKILL.md Phases 1-4) |
| 15 | Five carriers, densities, budgets, decal caps | done (covered: large-scale-texturing) |
| 16 | LOD value match, LOD groups, UCX | done (covered: procedural-assets Phase 7, game-output.md) |
| 17 | ORM packing, normal Y, albedo 30-240 sRGB | done (covered: procedural-assets references/surfacing.md) |
