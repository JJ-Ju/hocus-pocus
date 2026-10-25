# Surfacing: materials, textures and weathering

How material and environment artists surface modular architecture, and how to do it in
Houdini 22 (Copernicus, Karma, MaterialX). Tags: **[C]** consensus or a vendor spec,
**[P]** one artist's practice, **[I]** inference. Sources at the end.

## Fix the target before painting anything

- **PBR value ranges [C, Adobe PBR guide]:** dielectric base colour 30–240 sRGB (50+ is the
  strict floor); raw metal 180–255 sRGB; metallic is close to binary. Worn or dirty metal is
  done with the mask, not with mid-grey metallic values. Base colour is sRGB, everything
  else linear.
- **Packing [C, glTF 2.0 and engines]:** ORM, with R = occlusion, G = roughness, B = metal,
  linear. Put the mask that matters most in G, which compresses best.
- **Normal map Y [C]:** Unreal expects DirectX (Y−); glTF, Unity, Blender, Houdini and
  Karma expect OpenGL (Y+). Houdini's Bake Geometry Textures COP has a Normal Y Direction
  parameter. A wrong Y is a silent error: check with a known bump under a raking light.
- **Texel density [C that it is consistent; numbers vary]:** about 512 px/m for third person
  or distant city buildings, about 1024 px/m for first-person street level. Labs Texel
  Density measures it.

## UVs: trims for strips, tiling for big surfaces

- **Trim sheets [C]:** strips tile along U; strip heights are powers of two (on a 1024
  sheet: 512, 256, 128, 64, 32, 16 px) so strips of equal height swap between material sets;
  each strip is as tall as the largest element it covers; no strip under about 16 px [P];
  1–2 px margins, under-fill rather than bleed. The bottom row can hold unique elements.
- **Normal bevels in the trim [C]:** 45° bevels baked along strip edges make 90° low-poly
  edges read as rounded (Insomniac's "Ultimate Trim", Sunset Overdrive).
- **Geometry side:** straighten shells into rectangles, map each piece's role to a strip
  (cornice → cornice strip, sill → sill strip), let shells run past 0–1 along the tiling
  axis. Labs Trim Texture assigns a trim id per strip.
- **Large surfaces:** world-scale tiling UVs (continuous across modules), or
  world-aligned/triplanar projection in the shader. Break tiling at distance with a macro
  variation layer or stochastic tiling.
- **About 80% of a modular scene** can be trims plus tiling materials [P]; unique bakes are
  for heroes.

## Detail hierarchy: macro, meso, micro

- **Macro:** large value and hue shifts across a facade or between panels. This is all that
  survives at distance once mips drop the rest. A wall with only micro grime reads flat grey
  at 50 m. [C concept; I on the distance claim]
- **Meso:** panels, bricks, seams, cracks.
- **Micro:** pores, grain, pitting, mostly in normal and roughness.

Build materials from large forms to small, and judge each level at the distance it matters.

## Layer order

1. Base material per surface class (concrete, panel paint, glass, metal, trim).
2. Macro value and hue variation per facade or panel (often per instance).
3. Edge wear: convex curvature × noise breakup; worn edges slightly glossier.
4. Cavity and corner dirt: AO and concave curvature.
5. Up-facing deposits: world normal up × noise.
6. Gravity streaks below sills, ledge ends and mullions.
7. Splash and grime band at the base.
8. Sun bleaching on exposed faces.
9. Rust bleed and efflorescence from their sources.
10. Decals: stains, signage, markings, graffiti, at story points.

**Mask recipe [C]:** geometric mask (curvature, AO, gradient, facing) × noise breakup, then
levels and contrast. Never raw noise alone. Cap each detail layer at roughly 60% coverage and
mask or warp it against the layers beneath [P].

## Weathering follows water

From the Precast/Prestressed Concrete Institute's weathering notes [C]:

- Dirt settles fastest on up-facing and rough surfaces. Rain run-off cleans the top of the
  building and carries dirt lower down.
- Top corners of the windward face get the most rain (corners can get 20–30× the facade
  centre). Run-off concentrates at outside corners, columns and the inside corners of
  projections.
- Glass sheds water fast into streams along mullions and glass edges, so streaks run down
  mullions and over the sill or spandrel below.
- Water runs along undersides; drips keep soffits clean. Projections of 300 mm or more throw
  water clear of the wall.
- Where water reaches the zone sheltered from driving rain it soaks in and leaves a zigzag
  dirt line.
- New buildings show dark dirt streaks first; later, cleaner "white-washed" streaks appear
  against darkened surroundings.
- Smooth, light surfaces show streaks most; textured ones collect more dirt but hide it.
  Sunny walls dry faster and collect less dirt.
- Flat parapet tops wash dirt down the face.

Also [C, trade sources]: efflorescence leaves white salt deposits where water leaves masonry;
rust bleeds downward from iron fixtures and a small source stains a long way; paint chalks and
bleaches on sun-facing walls, less under overhangs.

## Driving weathering from geometry in Houdini [I]

| Attribute | Compute | Drives |
|---|---|---|
| `up` | `dot(N, {0,1,0})` | Deposits on ledges and sills |
| `ledge_src` | Up-facing prims whose neighbour below is a wall | Streak emitters |
| `streak` | From each emitter, walk down the wall plane, fading with distance, broken with noise; extra emitters at sill ends and mullions | Gravity streaks |
| `hgt` | Height above ground | Splash band (about 0.3–1 m), damp, moss |
| `occ` | Labs Physical Ambient Occlusion | Corners and recesses |
| `corner` | Distance to concave edges | Inside-corner grime |
| `expo` | `dot(N, sun_dir)`, windward direction | Bleaching; washed windward corners |
| `rust_src` | Points at metal fixtures | Short rust streaks |

Bake or rasterize them depending on the asset:

- **Unique textures:** Rasterize Setup COP (Space = UVs) then Rasterize Geometry COP writes
  point or vertex attributes into UV-space layers. Extrapolate with Adjacency pads seams.
- **Shared trims and tiling materials:** world placement differs per instance, so keep these
  masks as vertex colour or per-instance data and blend in the shader. Tiling textures cannot
  carry placement-dependent grime.

## Bake what belongs to the mesh, compute what belongs to the world

- **Bake [C]:** normals, AO, curvature, edge, cavity, thickness, from high to low or from the
  mesh itself. Houdini 22: **Bake Geometry Textures COP 2.0** (tangent and world normals,
  rounded-edge normal, AO, curvature, edge, cavity, thickness, height, custom attributes;
  surface-normal, cage or single-mesh tracing; piece matching by `name`; Normal Y Direction;
  MikkT tangents). Labs Maps Baker is deprecated (removed in Houdini 23). **Karma Texture
  Baker LOP** bakes lit and procedural MaterialX results to textures.
- **Bake hygiene [C]:** split UVs at hard edges, triangulate first, cage just past the high
  poly, 16-bit for height and AO to avoid banding, details under 1 px will not bake.
- **Compute live or per instance:** world-up masks, height above ground, macro hue, lit
  windows.

## Copernicus nodes worth knowing (Houdini 22)

Curvature, Height to Ambient Occlusion, Edge Detect, Triplanar and Triplanar Hex Tile,
Streak Blur, and the grunge set: Grunge Leaking Streaks (SideFX suggests it for water-damaged
walls), Grunge Drips, Rust, Rusty Surface, Moisture, Mold Spots, Wipe Trails. Texture
Material Library LOP wires COP outputs into Solaris materials; MaterialX image nodes read COP
outputs with an `op:` path.

## Windows and night

- **Interior mapping [C]:** a window shader ray-casts virtual floor, ceiling and walls and
  picks a room per window from an atlas. Furniture reads flat; fine for background.
- **Lit windows [P, City Sample]:** a fraction of windows off, per-window brightness
  variation, warm or cool tint. Drive emission from a per-window random value thresholded by
  an occupancy parameter, and light whole floors or office zones together so the pattern
  reads as rooms, not noise.
- **Per-instance variation [C]:** write hue, grime amount and occupancy as per-instance data
  from Houdini.

## Stylised 1980s–90s anime backgrounds

- **Medium [C]:** poster colour or gouache, foreground on separate cels for parallax.
- **Window size with depth [C, Akira backgrounds]:** painters drew windows about 3 mm in the
  foreground, about ½ mm in the middle ground, a dot or line in the distance. Apply it as
  LOD-driven simplification of the window pattern.
- **Scale cues [P]:** tiny detail in rear layers and a low building or a figure for scale.
- **Night [P]:** blue and violet ambient, dry-brush glows around lights, neon reflected in
  wet ground.
- **Translate to shading [I]:** quantise values into 3–5 flat bands per material, use a few
  large hand-shaped stains instead of noise grime, a limited palette (cool shadow, warm
  light), dark silhouettes against the sky, sparse warm window clusters at night.
- No primary source documents Evangelion's background technique; treat any claim about it as
  observation of the films.

## Mistakes and checks

Mistakes [C/P]: uniform detail that reads as generated; raw grunge dropped into albedo or
roughness; dirt where water cannot put it, or an evenly dirty facade; mid-grey metallic for
wear; albedo outside 30–240 sRGB; density mismatched between neighbours; tiling visible at
distance.

Checks seniors run:

- A grayscale render (value structure) and a squint test.
- The asset at gameplay distance, and with a forced low mip.
- A ball and a plane under several lights before trusting a material [P].
- Albedo range, texel density map, normal Y with a known bump.
- The material in the target renderer early, not only in the authoring tool.

## Sources

- SideFX: Bake Geometry Textures COP https://www.sidefx.com/docs/houdini/nodes/cop/bakegeometrytextures.html · Houdini 22 Copernicus https://www.sidefx.com/docs/houdini/news/22/copernicus.html · COP index https://www.sidefx.com/docs/houdini/nodes/cop/index.html · Grunge Leaking Streaks https://www.sidefx.com/docs/houdini/nodes/cop/grunge_leakingstreaks.html · Rasterize Setup https://www.sidefx.com/docs/houdini/nodes/cop/rasterizesetup.html · Rasterize Geometry https://www.sidefx.com/docs/houdini/nodes/cop/rasterizegeo.html · Labs Maps Baker https://www.sidefx.com/docs/houdini/nodes/sop/labs--maps_baker-5.0.html · Labs Trim Texture https://www.sidefx.com/docs/houdini/nodes/sop/labs--trim_texture.html · Karma baking https://www.sidefx.com/tutorials/how-to-bake-textures-in-karma/ · MaterialX in Solaris https://www.sidefx.com/docs/houdini/solaris/materialx.html
- Adobe PBR guide part 2: https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2 · Mask Builder: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/mask-builder · Dirt: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dirt
- glTF 2.0: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html · Unreal texture compression: https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-compression-settings?application_version=4.27 · Marmoset baking: https://marmoset.co/posts/toolbag-baking-tutorial/ · Maxon texel density: https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
- Trims: The Ultimate Trim https://gdcvault.com/play/1022323/The-Ultimate-Trim-Texturing-Techniques · Beyond Extent trim sheets https://www.beyondextent.com/deep-dives/trimsheets
- Artists: Mark Foreman https://80.lv/articles/building-materials-in-substance-designer-with-mark-foreman · Charlie Foreman https://80.lv/articles/001agt-002mrs-tips-and-storytelling-in-substance-designer · Mudra Roy https://80.lv/articles/combining-workflows-to-create-weathered-rusty-building · Clara Tan https://80.lv/articles/the-workflow-behind-an-abandoned-bar-modular-environment
- Interiors and windows: https://80.lv/articles/interior-mapping-rendering-real-rooms-without-geometry · City Sample lit windows https://www.versluis.com/2025/10/how-to-change-the-distribution-of-lit-windows-in-epics-city-sample-project/
- Building science: PCI Designer's Notebook, Weathering https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf · Efflorescence https://www.gobrick.com/media/file/efflorescence-prevention-and-control.pdf · Rust staining https://prosoco.com/how-to-remove-rust-from-concrete/ · Coatings and sun https://insights.basf.com/home/article/read/summer-rays-a-year-in-the-life-of-architectural-exterior-coatings-part-3
- Anime backgrounds: Stefan Riekeles https://www.stirworld.com/think-books-and-movies-stefan-riekeles-on-anime-architecture-and-neo-tokyo-s-layered-dystopian-urbanscape · Akira cut 955 https://www.riekeles.com/shop/p/akira-cut-no-955-poster · https://blog.alltheanime.com/anime-architecture/
