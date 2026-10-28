# danchi — procedural 1980s Japanese public housing block (Houdini HDA)

`sk6::danchi::1.0`, library `danchi.hdalc` (Houdini 22.0.466, Indie).

## Brief

- **Subject.** A 1980s corridor-access slab (片廊下型 公団/公営住宅): 4–14 floors, open access
  corridors on the north side, balconies on the south side, stair and lift cores, a rooftop FRP
  water tank on a steel stand, a painted building number on each end wall.
- **Platform and camera.** A third-person or street-level game background building that the
  player walks past but does not enter. Judged at 5–15 m (bay), 30–60 m (facade) and 100–300 m
  (building, skyline). Texel density 512 px/m.
- **Style.** Realistic (photographic). The anime-background look is not built in this version;
  it would be a switchable shading layer on top.
- **Enterable parts.** None. Interiors are faked with layered cards behind the balcony glass.
- **Signature features** (read at distance, in priority order):
  1. a long low slab with strong horizontal bands (balcony fronts and corridor parapets per floor);
  2. the vertical rhythm of balcony partition boards and sliding doors, one bay per flat;
  3. the large painted number on the end wall, plus an accent colour panel;
  4. stair/lift cores breaking the corridor side and rising above the roof as penthouses;
  5. the rooftop water tank on its stand, antennas;
  6. lived-in clutter on the balconies (laundry, futons, AC units) and dirt streaks from sources.

## Contract (metrics)

Units are metres; Y up; the building's long axis is X; balconies face +Z (south), corridors −Z.

| Metric | Default | Range / rule |
|---|---|---|
| Floor-to-floor `H` | 2.8 | 2.7–3.0 |
| Unit bay width `W` | 6.0 | 5.5–7.0, 0.5 steps |
| Core bay width (stair) / (stair + lift) | 3.0 / 5.5 | fixed |
| Unit depth, wall to wall `D` | 8.4 | fixed in v1 |
| Open rail section of a balcony | 0.4 W (rounded to 0.1) | solid parapet over the rest |
| Balcony depth | 1.2 | fixed |
| Corridor width | 1.4 | fixed |
| Slab thickness | 0.18 | balcony slab 0.15 |
| Parapet height (balcony, corridor) | 1.1 above floor | — |
| Plinth (ground-floor level) | 0.45 | — |
| Roof parapet | 0.6 above roof slab | — |
| Sliding door opening (balcony) | 3.4 × 2.0 | sill at floor |
| Balcony window opening | 1.6 × 1.1 | sill 0.9 |
| Unit door (corridor) | 0.85 × 2.0 | steel |
| Kitchen window (corridor) | 1.2 × 0.9 | sill 1.0, grille |
| Wall thickness | 0.18 | — |

- **Pivot.** Facade pieces: bottom-centre of the bay on the outer wall plane, at the floor level.
  Local +Z points out of the building, +X along the facade (to the right seen from outside).
  The corridor side uses the same pieces rotated 180° about Y.
- **Footprint.** A bay piece stays inside x ∈ [−W/2, W/2], y ∈ [0, H]; balcony pieces reach
  z ≤ 1.2, corridor pieces z ≤ 1.4.
- **Joins.** Bays butt at x = ±W/2. The partition board sits on the bay's right edge only
  (shared with the neighbour), so it is never doubled. Parapets and slab edges butt; chips stay
  0.15 m away from bay ends (seam margin).
- **Plan attributes.** `name` (piece), `orient`, `scale`, `id` (stable: floor·1000 + bay·10 +
  side), `floor`, `bay`, `side` (0 balcony, 1 corridor), `unit`, `persona`, `role`.

## Piece list by level

| Level | Pieces |
|---|---|
| L1 | `bal_front` (slab + parapet + rail, damage variants), `bal_wall`, `sash_door`, `bal_window`, `partition`, `cor_front`, `cor_wall`, `steel_door`, `kitchen_win`, `meter_door`, `lamp`, `ac_unit` (3 generations), `laundry`, `futon`, `plant`, `room_back` (interior card set), `downpipe`, `tank`, `antenna` |
| L2 | balcony bay, corridor bay (assembled by the plan) |
| L3 | balcony facade, corridor facade, end walls (generated) |
| L4 | slab + cores + penthouses + roof + tank |
| L5 | seed sheet / estate line-up (evidence only) |

## Budgets (triangles)

| Item | LOD0 | LOD1 | LOD2 |
|---|---|---|---|
| Balcony bay with props | ≤ 3,500 | ≤ 400 | — |
| Corridor bay | ≤ 1,500 | ≤ 250 | — |
| Default building (10 floors × 12 units) | ≤ 700k | ≤ 100k | ≤ 3k |
| Textures | streak/stain atlas 2048×1024, wall/concrete tiling sets 1024² | same | same |

Measured numbers are under "Results".

## De-risk results

See `log.md` (21:12). Labs is not installed; relative material paths do not bind; cut-out
decals, `displayColor` primvars and Japanese text render in Karma.

## Reference

`ref/reference_study.md`: 30 Wikimedia Commons photos (licences listed), counted rules, top-10
cues; `ref/contact_sheet.jpg`. Rules taken into the generator: alternating solid parapet and
white vertical-bar rail (13/15), thin projecting eave below 8 floors (17/25), windowless
gables (15/18), black/navy sans number at 0.4 floor in the top-floor band (11/13), white /
light grey paint (23/30) with one muted accent on about half the blocks, downpipes, antennas.
Kept against the photos because the brief asks for them: open-corridor type at every height
(photos show stair halls on 4–6F walk-ups), a rooftop tank on every block (1 of 25 photos).

## Parameters

Massing (floors 4–14, units 4–24, bay width 5.5–7.0, floor height, roof edge, massing from
seed with ranges), Cores (count or auto, lift auto/never/always), Style (seed, paint scheme,
building number or seeded code, 号棟 suffix, years since repaint), Dressing (props, interior
cards, edge damage, AC share, retrofit lift tower), Weathering (decals, amount, repaint
patches, texture folder), Output (LOD 0/1/2/all, collision).

## Structure (inside the asset)

`build` (SOP): `plan` → `dress` (personas) → `place_kit` (Copy to Points by `name`) with 31
`kit_*` piece subnets merged in `KIT`; `causes` (story hotspots) → `gen_shell` (plinth,
gables, roof, cores, tank, antennas, downpipes, retrofit tower), `number_font` +
`place_number`, `decals`; LOD1 (`lod1_filter`, `place_kit_lod1`, `decals_lod1`), LOD2
(`lod2_shell`); `lod_select` → `grime` → `assign` (scheme colours, patches, absolute
material paths via `opfullpath`) → `uv_world` → `OUT`. `mats`: 16 MaterialX materials.
`collision`: UCX hulls. Source of every wrangle: `work/vex/*.vfl`, build scripts
`work/py/*.py`.

## Results (default: 10 floors × 12 units, seed 1)

| Check | Result |
|---|---|
| Skeleton tiling (5 configurations, gaps/overlaps per floor) | 0 problems |
| Golden piece damage (4 variants) | closed, 0 non-manifold, seams unchanged, flank_runs 0, edge share 0.955–0.997, face_to_edge 0.13–0.37 (two variants above the 0.3 target), 414–2,686 tris |
| Spray-tile micro grain | p90/p10 6.07, CV 0.57, kurtosis 3.6 (below the 5–20 target) |
| Triangles LOD0 / LOD1 / LOD2 | 379,106 / 99,166 / 574 (budgets 700k / 100k / 3k) |
| LOD value match at 170 m | LOD1 −2.4 %, LOD2 −0.2 % (target ±3 %) |
| FBX re-import | triangles identical, 16 / 14 / 3 material slots, 6 `UCX_danchi_NN` hulls |
| Fresh instance from the library | cooks in 1.0 s, 0 errors, materials bind |
| frame_critique (street, building, corridor, bay) | 0 fails on the binding tests; sunlit walls L* 77–80; `reference_match` against the 30 photos warns/fails (render less contrasty and cooler than the photos) |

Evidence (`evidence/`): 00 skeleton sheet, 01 golden piece damage, 02 golden bay (+ grayscale),
03 street view, 04 building view, 05 corridor side, 06 estate at distance, 07 LOD sheet,
08 true-scale seed line-up, 09 9-up seed sheet. Exports in `export/`.

## Limits and what an artist should still do

- Weathering is light: streak decals read up close (rail-post rust, joint runs) but barely at
  facade distance; no mottled grey blotching yet (5 of 29 photos). Raise Weathering Amount, or
  add a facade-scale stain layer.
- Interiors are cards; glass shows them only at short range.
- LOD0 export is unpacked (82 MB FBX); an engine build should instance the kit pieces.
- Engine materials: the MaterialX layers (macro value noise, damp base band, grime lerp) need
  rebuilding in the engine from the exported textures, `Cd` and the `grime` attribute.
- Trees and poles in the evidence scene are simple; the sky is bluer than the reference photos.
- Only the corridor type; a stair-hall walk-up type would cover most 4–6F blocks in the photos.
