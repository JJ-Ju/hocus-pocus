# Texturing at scale: densities, carriers, budgets, engines

Distilled from `docs/redesign/research/texturing-at-scale.md` (sources there) and the danchi round I
(2026-11). Tags: **[C]** consensus or vendor spec, **[P]** one practitioner, **[M]** measured, **[I]**
inference.

## Texel density

| Camera | Base density | Note |
|---|---|---|
| First person, street level | 1,024 px/m (10.24 px/cm) [C] | the industry's common target |
| Third person | 512 px/m [C] | |
| Background blocks | 256 px/m or a far-LOD bake | |
| Micro detail (coat bumps, pores) | ≥ 1.5 × base [P] | |
| Masks (where weathering is) | 25-50 px/m [I] | the edge rule makes them crisp up close |

At 4K and 2 m from a wall, one 50 px/m texel covers about 19 × 19 screen pixels [M]: a mask is never
the visible detail, only the decision of where it goes.

## Memory: why not unique textures

| Plan for an 82 × 36 m facade | Pixels | Compressed with mips |
|---|---|---|
| Unique PBR at 512 px/m (colour, normal, ORM) | 42k × 18.6k | about 2 GB [M] |
| The whole ten-storey building at 1,024 px/m | — | 17-25 GB, 460 UDIM tiles of 4096² [M] |
| Masks M_hi (50 px/m RGBA), M_lo and tint (25 px/m) | 4096 × 1814 | about 13 MB per front, 28 MB per building [M] |
| Shared library per estate (tiling sets, trims, decal atlas) | — | about 110 MB [I] |

Budget: ≤ 40 MB unique per building (10 MB on Godot Mobile), ≤ 128 MB shared.

## The stack per wall

1. **Base tiling set** (coat, formed concrete, brick): albedo, normal, ORM, height; hex-tiled. Formed
   concrete and other structured finishes are registered to the real panels (offset per panel,
   seams on joints), never hex-tiled.
2. **Micro set** (relief, cavity), equalised for the edge rule.
3. **Macro variation**: one noise at two world scales (about 10 m and 30 m), incommensurate with the
   storey and bay pitch, for tone drift.
4. **Trims** for every arris, coping, slab edge, drip groove, joint (20 mm groove with 20 mm bands),
   sill and plinth, with 45° bevel strips (Insomniac's "Ultimate Trim"); strip heights multiples of
   16 px.
5. **Masks** in facade space (planar projection), packed:

   | Texture | Density | R | G | B | A |
   |---|---|---|---|---|---|
   | M_hi | 50 px/m | run-off (streak envelope) | stains, ground band (steel: rust) | growth | light layers (efflorescence, washed) |
   | M_lo | 25 px/m | soiling film | damp (roughness) | coat tone (0.5 = none) | edge wear (for trims) |
   | tint | 25 px/m | dirt colour (RGB, sRGB) | | | |
   | stage | 25 px/m | growth stage on its colour ramp | | | |

   Recessed walls behind balconies need their own mask layer, or they read the parapet's values.
6. **Decals** from one 4096² atlas at 1,024 px/m: rust and leak runs (head, tiling body, tail), stains
   and halos, crack strips (tiling along U), edge-chip runs and patches. Budget about 0.25 decals per
   m² of facade, at most three overlapping; LOD1 bakes the small ones into the masks.
7. **Geometry and per-instance data**: real joints, spalls and chips (procedural-mesh-damage); bay
   tint, repaint id and damage variant as per-instance values.
8. **Far LOD**: the composite baked at 10-50 px/m (UE HLOD, Labs Impostor Baker).

## Weathering layers: mask plus the detail it is revealed against

| Layer | Detail field | How |
|---|---|---|
| Soiling film | grime noise + the coat's troughs | modulated (mean kept), not revealed |
| Run-off streaks | vertical rivulets, offset per band | revealed, w ≈ 0.55 |
| Stains, ground splash | blotch field, splash specks | revealed, w ≈ 0.45-0.6 |
| Growth | colony splats in clusters + the troughs | revealed, w ≈ 0.3; colour from the stage ramp |
| Rust on steel | blotches + pits | revealed, w ≈ 0.25 |
| Efflorescence | crystalline speckle on the peaks | revealed, w ≈ 0.3 |
| Edge wear, chips | fractal edge noise | revealed, w ≈ 0.1 |

## Engines

- **Unreal 5:** BC7 colour, BC5 normal, BC4 single channels, mips streamed. Nanite meshes cannot be
  mesh decals, so decals are separate non-Nanite meshes with a DBuffer material [C]. Runtime
  virtual texturing is for terrain blending, not walls. Streaming virtual textures with UDIM tiles
  only when masks pass about 300 MB per estate [I]. Nanite displacement (5.3+) can carry relief, but
  the tiling normal is enough for walls.
- **Godot 4:** no UDIMs; masks per facade or in a `Texture2DArray`. Decal nodes are clustered (512
  elements in view with lights and probes; 8 per mesh on Mobile), so only about 50 hero marks use
  them and the rest are mesh decals with a custom shader [C]. BPTC needs Forward+ or Mobile.
- Write one constants file (tile sizes, cells, widths, colours, the hash) that the numpy mirror and
  both shaders read, and check parity on one golden crop per release (mean ΔE00 ≤ 2).

## Case notes

- **Cyberpunk 2077:** many tiling layers over small unique masks, revealed at runtime; the art team
  matched Substance Painter's preview to the engine [P].
- **The Order: 1886:** layered materials with masks and per-layer detail; compositing at runtime
  [P].
- **City Sample / The Matrix Awakens:** buildings from instanced kit pieces with trims and tiling
  sets under Nanite; variation per instance [P].
- **danchi 1.1 (this repo):** 5,228 decals for streaks, stains and growth; the round-I split moves
  envelopes to masks and keeps decals for discrete marks [M].

Not found: how Insomniac's Spider-Man, Assassin's Creed Unity or Star Citizen texture building
walls, Naughty Dog's vertex-blend formula, any studio's published mask density or decal count per
building.
