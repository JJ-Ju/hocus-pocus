# Metrics and modular kits

How AAA environment teams design the pieces a building generator places. Sources are listed
at the end; where a number is community practice rather than a studio's published figure, it
says so.

## The order of work: contract, skeleton, then quality from the smallest piece up

What studios describe:

- **Bethesda (Skyrim, Fallout 4)** runs kits through phases:
  - concept;
  - proof: placeholder pieces with no mesh detail, to test proportions, footprints and naming;
  - graybox: "functional but ugly" pieces so designers can lay out levels;
  - build-out: finish one piece completely, then make its variants;
  - polish.

  Footprints, pivots and transition metrics are locked early, because changing them later
  breaks every layout built on them.
- **Visual targets and beauty corners:** a small section taken to final quality early, with
  every layer stacked (kit pieces, materials, decals, props, lighting), to set the bar and
  expose cost. Medal of Honor: Airborne called it a visual target; 11 bit studios built a
  beauty corner for The Alters DLC before the modular kit existed.
- **Each level gets its own breakup:** piece variants (Fallout 4's combinable wall damage),
  bay dressing (Sumo Digital's pre-built window and door assemblies), kit mixing and off-grid
  joins at building scale, clutter and decals at scene scale.
- **Procedural generators** (Embark's THE FINALS, Epic's City Sample) place artist-quality
  modules. The generator's output is only as good as the modules.

The synthesis this skill uses:

1. **Contract first, briefly.** Metrics, pivots, footprints and joins are interfaces between
   levels.
2. **A functional skeleton.** Boxes at every level, to prove the contract. It is a test, not
   a phase.
3. **Quality bottom-up.** One golden piece, then a golden bay (the beauty corner), then the
   rest of the kit to that standard. Then each level up gets its own blockout, refine and
   detail pass, judged at its own distance.

**Quality targets:**
- At least three distinct size classes of form (primary, secondary, tertiary).
- About 70% quiet surface to 30% detail; the point is contrast, not the exact ratio.
- One bevel width per kit in world units (for example 1 cm). At 512 px/m that is about
  5 texels, at 1024 px/m about 10.
- A feature must cover several pixels at its farthest important distance, or it moves to the
  normal map or texture.
- Per-piece triangles vary widely. About 2,000 per modular piece was a last-gen guideline;
  current kits average around 1,500 per mesh with LODs; mid-poly hero props reach about 50k.
  Measure against your own budget table.

## Metrics: fix the grid before modelling anything

- Pick one unit and a coarse snap. Bethesda used footprints like 512×512×512 or
  256×256×1024 game units (128 units ≈ one character height ≈ 2 m), with sub-kits as exact
  multiples of each other. Epic's Unreal-era kits used powers of two.
- In metres (community practice): smallest snap 0.5 m, 1 m preferred. Add fill pieces of
  0.25, 0.5 and 0.75 m to close gaps around odd openings instead of making patch pieces.
- Architecture norms (not from a studio source; round to your grid): floor-to-floor
  3.0–3.5 m residential, 4–5 m commercial ground floors, doors about 1 × 2.1–2.2 m.
- Fix door and window opening sizes, wall and floor thickness, and the facade bay width
  before any piece is detailed. Make them generator parameters only if they stay multiples
  of the snap.
- Decide which axes each piece tiles on. Facade walls tile horizontally and stack by floor;
  nothing tiles on all axes.

## Pieces and pivots

- **Footprint rule:** a piece stays inside its footprint box, including negative space.
  Anything that overhangs collides with its neighbour or z-fights.
- **Pivot:** one convention for the whole kit, never changed later. Bottom-centre on the
  facade plane is the common default. SideFX's Labs Building Generator expects modules on the
  YZ plane with the front lower-right corner at the origin and an `@name` attribute.
- **Taxonomy for a facade kit:** wall-mid, window bay, door bay, outer corner, inner corner,
  floor-separating trim or band, cornice, base course or plinth, parapet, roof cap, end
  pieces, and transition ("glue") pieces between styles. Variants are numbered
  (`wall_mid_01`, `wall_mid_02`).
- **Names a person can read.** Bethesda saw a kit go unused because its names were cryptic.
- **Counts for scale:** Skyrim's seven kits from two artists covered 400+ interiors; Fallout
  4's workshop kit was about 500 pieces; City Sample's buildings come from 24 kits and
  2,000+ meshes.
- **Stress-test, not showcase.** Testing a kit only in ideal arrangements proves nothing.
  Test odd widths, inner corners, setbacks, stacking, style transitions.

## Hiding repetition without new geometry

Players notice repeated clutter sooner than repeated architecture, so put most variety in
the detail layer.

- Material swaps on the same mesh (Fallout 4 shared meshes across brick, wallpaper, wood,
  concrete).
- Damage or state variants of a piece (11 wall-hole variants gave 121 combinations).
- Vertex-colour masks plus a procedural noise mask to break up materials (Insomniac's
  Sunset Overdrive trim technique).
- Decals and greebles placed late: stains, vents, signage, pipes.
- Mixing kits and adding a few floating pieces that break the grid.
- Never cover a footprint error with a patch piece. Fix the kit's logic.

## Edges

Real-time assets read as real when their edges catch light. Two accepted approaches:

- **Trim normal bevels:** 90° low-poly edges mapped onto trim strips whose normal map has
  45° bevels baked in (Sunset Overdrive's "Ultimate Trim").
- **Mid-poly:** a one- or two-segment chamfer on every hard edge, with face-weighted custom
  normals and usually no high-poly bake. Re-run the weighted-normal step on every LOD.

## Texel density

Studios rarely publish numbers. Consistency matters more than the absolute value.

| Camera (community figures) | Density |
|---|---|
| Third person, or distant city buildings | ~512 px/m |
| First person, current gen | ~1024 px/m |
| Close first person hero surfaces | 1024–2048 px/m |

Density can drop where the player never gets close (rooftops of tall buildings). Plan trim
strip heights so every strip lands near the target density; equal-height strips are a sign
nobody planned it.

## Interiors behind windows

- **Interior mapping** (Joost van Dongen, 2008) fakes rooms in the window shader by
  ray-casting virtual floors, ceilings and walls, with rooms picked per window from an
  atlas. SimCity (2013) used it, City Sample's window glass uses an interior cubemap, and
  Unreal ships an `InteriorCubemap` function.
- **Real interiors are built only where the player can enter.** AC Unity made about a
  quarter of its buildings enterable; everything else is a shell with faked rooms.

## Mistakes seniors avoid

1. Detailing before the contract and skeleton exist, or detailing only shallowly and late so no
   level ever reaches quality.
2. Sub-kit sizes that are not multiples of each other, tiny snaps, overhanging footprints.
3. Changing pivots or metrics late.
4. Testing only ideal arrangements.
5. Patch pieces instead of fixing the kit.
6. Hero pieces before utility pieces.
7. Cryptic names.
8. Unplanned texel density on trims.
9. Flat compositions with no foreground, midground and background.
10. Nearly coplanar overlapping shells (z-fighting; overdraw under Nanite).

## Sources

- Bethesda kit building, GDC 2013: https://www.slideshare.net/slideshow/gdc2013-kit-buildingfinal/17728576
- Skyrim's modular approach: https://www.gamedeveloper.com/design/skyrim-s-modular-approach-to-level-design
- Fallout 4 modular kits (summary of the GDC 2016 talk): https://dtf.ru/id31295/3788796-modulnyi-dizain-fallout-4 and https://gdcvault.com/play/1022930/-Fallout-4-s-Modular
- Joel Burgess on kits and art fatigue: https://80.lv/articles/building-huge-open-worlds-modularity-kits-art-fatigue
- GTA V art direction: https://mcvuk.com/?p=80936
- Night City: https://80.lv/articles/interview-how-cyberpunk-2077-s-night-city-was-built-almost-entirely-by-hand/ and https://80.lv/articles/making-locations-for-cyberpunk-2077
- City Sample: https://dev.epicgames.com/documentation/en-us/unreal-engine/city-sample-project-unreal-engine-demonstration and https://www.cgchannel.com/2022/04/download-epic-games-free-city-sample-assets-for-ue5
- The Ultimate Trim (Sunset Overdrive), GDC 2015: https://gdcvault.com/play/1022323/The-Ultimate-Trim-Texturing-Techniques
- Mid-poly workflow: https://80.lv/articles/creating-assets-within-the-mid-poly-workflow-in-ue5/
- Nanite content guidance: https://dev.epicgames.com/documentation/en-us/unreal-engine/working-with-naniteenabled-content
- Interior mapping: https://80.lv/articles/interior-mapping-rendering-real-rooms-without-geometry
- Metric snaps and fill pieces (community): https://polycount.com/discussion/238299/building-modular-interiors-question
- Texel density tiers (community): https://www.strayspark.studio/blog/texture-resolution-guide-games-512-1k-2k-4k
- Visual target, Medal of Honor: Airborne: https://www.slideshare.net/slideshow/moh-airborne-adprocess/33254852
- Beauty corner, The Alters DLC: https://80.lv/articles/terraforming-the-alters-last-variable-with-blender-zbrush-ue5
- Breaking down repetition (Sumo Digital): https://80.lv/articles/breaking-down-repetition-in-epic-3d-spaces/
- Sci-fi modular environment (Starbreeze): https://80.lv/articles/making-a-high-quality-sci-fi-modular-environment
- Level Design Book, modular kits and environment art: https://book.leveldesignbook.com/process/blockout/metrics/modular and https://book.leveldesignbook.com/process/env-art
- Neil Blevins, primary, secondary and tertiary shapes: https://steveyang.readthedocs.io/Modeling/123/
