# Logs: danchi v6 (round 6)

The round-6 agent's own log and README, copied verbatim from the run folder. Evidence is in `docs/redesign/evidence/danchi-v6/`.

## log.md

## Danchi generator — work log

Times are local (EDT), 2026-10-27.

### 21:00 Phase 0 — reading

- Loaded the `procedural-assets` skill. Read, in order: hocuspocus-recipes, believability,
  art-direction, metrics-and-kits, generator-architecture, surfacing, game-output,
  critique_questions; then the companion skills `procedural-mesh-damage` (SKILL.md, causes.md)
  and `procedural-materials` (SKILL.md, realism, layering, weather-and-use, micro-noise).
  Why: the skill's table says these are required before phase 0, 3, 4 and 6.
- Read my memory notes: realism is the baseline (anime look optional), the user weights lighting
  first (sunlit camera-facing walls L* 85–96) and streak variety most.
- Slowed down: about 15 minutes of reading (~3,600 lines of references) before any Houdini work.
- 21:11 Made `sk6-out/{work,evidence,tex,ref,export}`. numpy 2.5.2 and PIL 12.3.0 are present
  for `frame_critique.py`.
- 21:11 Started a background research agent to collect and count 20–30 Wikimedia Commons danchi
  photos (`ref/reference_study.md`, `ref/contact_sheet.jpg`). Why: the skill asks for counted
  photo rules before building; delegating it let me de-risk Houdini at the same time.
- 21:11 `houdini_status` (nothing running) → `houdini_connect {launch: headless}`: Houdini
  22.0.466, pid 31436. Saved `work/danchi_v001.hiplc` at once.

### 21:12 Phase 0 — de-risk (checks run)

- Node types (python `hou.nodeType` sweep): present — copytopoints::2.0, font, polyreduce::2.0,
  convexdecomposition, boolean::2.0, lsystem, polybevel::3.0, sweep::2.0, remesh::2.0, rop_fbx,
  voronoifracture, rbdmaterialfracture, all MaterialX nodes needed (mtlxseparate3c, not
  mtlxseparate3), COP nodes (fractalnoise, worleynoise, shapescatter, streakblur, rasterize*,
  bakegeometrytextures::2.0). **Missing: all SideFX Labs** (lod_create, impostor, trim_texture) →
  LODs and impostors must be built by hand.
- Karma test scene (`work/py/derisk.py`, render `work/derisk_01.jpg`): a subnet (the future
  HDA) holding a geo and a matnet with three MaterialX builder materials.
  - **Relative `shop_materialpath` ("../mats/wall") silently binds nothing** — Karma fell back to
    displayColor. Absolute paths (`/obj/derisk/mats/wall`) bind. Decision: inside the asset,
    build the path with `opfullpath()` so a renamed/moved instance keeps its materials.
  - `mtlxgeompropvalue` reading `displayColor` (from prim `Cd`) works.
  - Cut-out opacity on `mtlxstandard_surface` works (float → `mtlxconvert` floatcolor3 →
    `opacity`), so mesh decals with alpha are viable for streaks and stains.
  - Font SOP with "SideFX WenQuanYi Zen Hei" renders 3号棟 correctly.
  - Exposure: sun 1.0 + sky 0.4 over-exposes an albedo-0.7 wall; calibrate later (skill: sun
    ~0.85, sky ~0.35).
- Slowed down: `mtlxconvert` lists only "default" in its signature menu; the real token
  (`floatcolor3`) came from `inspect {what: type}` parm names.

### 21:14 Phase 1 — contract

- Wrote `README.md`: brief (third-person/street game background, realistic, not enterable,
  512 px/m), six signature features, metrics table (H 2.8, W 6.0, D 8.4, balcony 1.2, corridor
  1.4, parapets 1.1, plinth 0.45 …), pivot convention (bay bottom-centre on the outer wall
  plane, +Z out; corridor side = same piece rotated 180°), joins (partition only on a bay's
  right edge so it is never doubled; 0.15 m chip margin at bay ends), piece list by level,
  triangle budgets.

### 21:16 Phase 2 — functional skeleton

- Wrote the generator as small stages, code in files (`work/vex/*.vfl`, `work/py/build.py`):
  `plan` (detail wrangle: bay sequence of units + core bays, one point per bay/floor/side with
  `id`, `floor`, `bay`, `side`, `btype`, `unit`, `persona`, `colneglect`, `orient`), `dress`
  (each bay point emits its piece points), one SOP subnet per kit piece (`kit_<name>`, proxy box
  for now) merged into `KIT`, `place_kit` (Copy to Points 2.0, piece attribute `name`, unpacked),
  `gen_shell` (plinth, gables, roof, parapets, core towers, penthouses, tank).
- Asset interface built on the subnet `/obj/danchi` with tab folders (Massing, Cores, Style,
  Dressing, Weathering, Output), ranges and help.
- Check: `check_skeleton.py` — per floor, the balcony-side wall pieces must tile [x0, x1] with
  no gap or overlap, and counts of unit walls and core walls must match the plan. Ran on five
  configurations (default 10F×12U; min 4F×4U W5.5; max 14F×24U W7.0 3 cores; 7F×9U W6.5 1 core
  lift forced; 5F×13U 3 cores no lift): **0 problems in all five**.
- Gate image: `evidence/00_skeleton_sheet.jpg` (default S and N, min, max). Hip `danchi_v002`.
- Slowed down: Copy to Points' "apply attributes" defaults to points, so per-piece attributes
  were not on prims (the check crashed on a missing prim attribute) — set `applyto1` = prims.

### 21:22 Phase 3 — golden piece: balcony front (slab + parapet)

- Chose `bal_front` as the golden piece: it is the most-seen piece (every bay, every floor,
  the facade's horizontal bands) and where streaks and chips start.
- Forms (`work/vex/bal_front_profile.vfl`): a (z, y) profile extruded along X — primary slab +
  parapet; secondary sloped parapet top, drip groove 13 mm wide 22 mm in, construction-joint
  groove at floor level; tertiary 12 mm chamfers and a 20 mm sealant V-joint at each bay end
  (10 mm per side so neighbours make it). Edge strategy for the kit: chamfer + area-weighted
  normals, cusp 25°.
- Check: face winding came out inverted; found with a signed-volume test (outward faces must
  give a negative sum with Houdini's clockwise winding). Fixed in the profile and in the
  shared `addbox` helper (the skeleton shell was inward-facing too).
- Textures (`work/py/tex_build.py`): spray-tile paint height/normal/AO in Copernicus (mesas
  in two sizes, flat-topped, amplitude envelope), concrete via `cop_lib.build_concrete_panels`,
  streak/stain decal atlas (8 cells) and the sky gradient with numpy (precise control of
  power-law runs and layered opacity). Check on the spray height: p90/p10 of local std 6.07,
  CV 0.57 (pass), kurtosis 3.64 (below the 5–20 target: noted, not fixed).
- Materials (`work/py/materials.py`): 16 MaterialX materials; colour, roughness and metal
  come from prim primvars written by the generator; the wall shader adds world macro value
  noise (±6 %), spray cavity, a grime lerp toward soot, a ragged damp base band and a top-floor
  wash, plus the spray-tile normal.
- Lighting rig for every gate: distant sun 28° up, 40° off the balcony facade normal on the
  camera side; textured sky dome visible to camera. First render clipped (frame_critique
  `value_range` FAIL, L* 99.8) → sun 0.45, sky 0.28.
- Damage (skill scripts `cluster_mask`, `chip_points_edge`, `cutter_shape`, `damage_validate`,
  `damage_measure`): 4 seeded variants (1–3 hotspots each) + a clean v0; 40 % of bays use v0.
  - First pass: 146–285 cutters, 5.5k–15.5k triangles, face_to_edge 0.54–0.76 (fail).
  - Thinned background chips/pits, bite floor 8 mm (invisible below that at bay distance),
    triangulate → seam points as hard points → polyreduce 55 %.
  - Final: open 0, non-manifold 0, seam_changed 0, flank_runs 0, edge_area_share
    0.955–0.997, face_to_edge 0.13–0.21 on v3/v4 but 0.36–0.37 on v1/v2 (target ≤ 0.3, near
    miss), 414 / 648 / 2,686 / 1,294 triangles (v3 above the 2.5k budget by 7 %).
  - Slowed down: polyreduce at 35 % moved seam points and made a non-manifold edge;
    reducing triangles (divide first) with seam points as hard points fixed both.
- Gate image `evidence/01_golden_piece_damage_closeup.jpg`: small bites along the arrises,
  fitting a repainted 40-year-old block; no large isolated chunks.

### 21:41 Phase 4–5 — golden bay and the rest of the kit

- 31 kit pieces as their own SOP subnets (`work/py/pieces.py`, LOD1 stand-ins in
  `pieces_l1.py`): balcony wall with openings, 2-panel aluminium sliding door and window in 3
  sash states (60 % closed, 30 % part open, 10 % open), partition board in an aluminium frame
  with its escape label, end fin, handrail + drain pipe + laundry hangers, interior card set
  (back wall 3.6 m deep, floor, ceiling, furniture masses, lace + folded drapes with closure
  by persona), AC outdoor units in 3 generations (floor-standing or wall-hung, duct cover),
  laundry (towels over the pole, shirts on hangers, sock rings; clustered with gaps), futon
  over the rail, pots with leaf cards; corridor wall, steel door (lever, number plate, mail
  slot), meter-box doors with louvres, frosted kitchen window with an aluminium grille,
  corridor lamp + water heater; core walls and landings.
- Personas per flat (tidy, family, gardener, elderly, vacant) choose props, curtains and sash
  state together; one hero balcony per facade.
- 21:50 The reference agent finished (`ref/reference_study.md`, 30 photos). Its counts changed
  the build:
  - parapets: solid concrete over part of the bay alternating with **white vertical-bar steel
    rails** (13 of 15) → `bal_front` now covers the solid part only and a new `bal_open` piece
    (slab, 10 cm upstand, white balustrade) fills the rest; rails white everywhere;
  - roof: thin projecting eave on 17 of 25 → eave below 8 floors, flush parapet above (Roof
    Edge parm);
  - gables windowless (15 of 18); number in black/navy sans at 0.4 floor height in the
    top-floor band, offset to one edge half the time, no 号棟, block codes like "A-43"
    (4 of 13) → `number_points.vfl`, numtext in the plan; "Add 号棟" kept as an option, off;
  - paint mostly white/off-white/light grey (23 of 30) → scheme weights; one muted accent on
    about half the blocks at the plinth, slab-edge stripes, roof fascia or towers;
  - downpipes at gable corners and along the corridor face, antennas, poles and wires in the
    evidence scene; the rooftop tank kept because the brief asks for it (rare in photos: 1
    of 25).
- Checks: golden bay render `work/bay_01.jpg` → laundry read as bunting (even spacing,
  saturated) and rails were dark brown → rewrote laundry (clusters, gaps, 1 in 12
  saturated) and made rails white; `bay_02`, `decal_01..04`, `facade_01..02`.
- Slowed down:
  - **decals did not render**: `primvertex()` returns nothing for a prim created in the same
    wrangle, so every decal UV was (0,0). Found by printing the decal UVs; fixed with
    prim-relative `setvertexattrib(0, "uv", pr, i, …)`. ~10 min.
  - VEX: a function that assigns to its own parameter fails when called with an expression
    ("read-only"), and `foreach` over an inline `array()` and `lerp(..., rand())` are
    ambiguous — each cost a cook/fix cycle.
  - Twice a shell heredoc edit of a Python file broke string quoting (`\n` inside a string,
    escaped triple quotes). The recipes warn about heredocs; after that I used the Edit tool.
  - The 2 m spray-tile cavity map showed as a repeating blotch on the 30 m gable at distance
    (`work/north_01.jpg`) → cavity amplitude 14 % → 5 %, normal strength 0.6.

### 22:00 Phase 6 — weathering, facade and building

- One cause field: `causes.vfl` writes 3–7 stories per facade and 1–3 per gable (leak,
  rust, neglect, impact; power-law strengths). Both the streak decals (`decals.vfl`) and the
  point grime (`grime.vfl`) read it.
- Streak decals (1,405 for the default block): rail-post rust runs, runs at the parapet
  V-joints, faint background drips at irregular spacing (power-law gaps), layered leak
  stains, a fringe under the drip-less corridor parapet tops, gable runs/curtains from the
  top edge, a pale washed band at a corner (age > 10), mould under the eave where a neglect
  cause sits. Top floors ×1.6; lengths power-law and clipped to the face they run on.
- Point grime: the dark line along slab edges and soffits (from `edge_grime` set by the
  front pieces), darker corridor back wall, cause hotspots.
- History: build (paint scheme, number), repaint patches (1–3 rectangles of bays × floors
  per facade, ±2–5 % value), retrofit generations (3 AC generations, optional retrofit lift
  tower), decay (rust, stains, chips).
- Exposure: sun 0.45→0.6→0.72, sky 0.28→0.34 so the sunlit walls sit near L* 80 without
  clipping (user preference L* 85–96; all frames pass `value_range`).

### 22:12 Phase 7 — LODs, collision, export

- LOD1 from undamaged sources (dress filter): no props, interior → one dark card, damage
  variants → plain fronts, light piece stand-ins, decals with strength ≥ 0.45 only.
  First LOD1 was 257k triangles (budget 100k): measured per piece (balustrade bars, grilles,
  hardware) and made stand-ins → 99,166.
- LOD2: banded shell. Value match at 170 m (`work/lod*.png`, mean facade luminance):
  LOD1 −2.4 %; LOD2 first +33 % (an unhandled colour key fell back to white), then −9.9 % at
  recess factor 0.4, then −0.2 % at 0.64 (interpolated). Sheet `evidence/07_lod_compare.jpg`.
- Triangles (default 10F × 12U): LOD0 379,106, LOD1 99,166, LOD2 574.
- Collision: 6 convex boxes `UCX_danchi_00..05` (slab, 2 towers, 2 penthouses, tank) in a
  separate `collision` object.
- FBX: `export/danchi_lod0..2.fbx`, `danchi_collision.fbx`. **Re-imported** with
  `hou.hipFile.importFBX`: 379,106 / 99,166 / 574 triangles (match), 16 / 14 / 3 material
  slots, 6 UCX meshes; LOD0's mesh renamed `danchi` so `UCX_danchi_NN` pairs with it.
  LOD0 FBX is 82 MB because it is unpacked; an engine would want the kit as instances.

### 22:20 Phase 8 — package

- `hda create` → `sk6::danchi::1.0` in `danchi.hdalc`; help text; inputs 0; locked.
- Retrofit Lift Tower was a promoted parm with no implementation → implemented it (steel
  frame, glass, bridges per floor) instead of shipping a dead control. Removed the "Pack Kit
  Instances" toggle for the same reason.
- Check: a fresh instance from the saved library cooked in 1.0 s with 0 errors, and its
  shop_materialpaths point into its own `mats` (the `opfullpath` fix survives renaming).

### 22:22 Phase 9 — presentation and final review

- Context scene (`work/vex/context.vfl`, evidence only, not in the asset): asphalt with
  patches and lines, kerbs, footpath, lawn, green mesh fence, utility poles with sagging
  wires and a transformer, trees (trunk, branches, leaf-card clusters), parking bays, a bike
  shelter; three more asset instances as neighbouring blocks.
- First street render: leaf cards too big ("paper"), left half an empty plane → smaller
  denser leaves, blocks across the road. Cameras levelled (look-at at eye height + window
  shift) so verticals stay straight.
- frame_critique (binding tests) on the evidence: street, building, corridor side, golden bay
  — 0 fails, 0 warns; sunlit walls L* 77–80. With `--ref ref/photos/*.jpg`: reference_match
  warns on street (EMD L* 11.4) and building (9.8), fails on the corridor side (18.6) and the
  bay close-up (20.1; a wall close-up against whole-scene photos is not like-for-like). The
  street metrics say the render has 0.79× the photos' contrast and a cool hue shift (the
  deep-blue sky). Not fixed.
- `--pair` golden bay before/after (same camera): value grouping 1.48 → 2.08, L* 67.7 → 79.9.
- Seed sheet via one Karma ROP job (seed = $F, frames 1–9, ~5 min in a child process while I
  exported FBX): massing varies 5–14 floors and 6–16 units, eave vs parapet, tank and cores;
  `--grid` most similar pair dE 0.2 (both white schemes): paint variety is low at distance,
  as in the photos. True-scale line-up of 5 seeds on shared ground.
- Gate images saved as they were made; all evidence JPGs under 400 KB (largest 310 KB).
- Hip saved as `work/danchi_v006.hiplc` with the scene reset to defaults.

### What slowed me down (summary)

1. Reading ~3,600 lines of skill references before starting (required, ~15 min).
2. Silent failures that needed a probe to find: relative material paths binding nothing;
   decal UVs all zero (`primvertex` on a new prim); Copy to Points applying attributes to
   points; inverted face winding; an unhandled colour key falling back to white on LOD2.
3. VEX strictness (read-only function parameters, ambiguous `lerp`/`rand`/inline arrays).
4. Shell-heredoc edits corrupting Python quoting (twice).
5. Karma final renders of the full scene take 2–3 min each with four blocks and trees; I moved
   the seed sheet to a background ROP job and rendered LOD checks at 960×540.
6. A display-flag change did not remove objects from Karma renders; moved them away instead.
- 22:55 Saved `work/danchi_v006.hiplc`, then `houdini_connect {quit: true}` (exited).

## README.md

## danchi — procedural 1980s Japanese public housing block (Houdini HDA)

`sk6::danchi::1.0`, library `danchi.hdalc` (Houdini 22.0.466, Indie).

### Brief

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

### Contract (metrics)

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

### Piece list by level

| Level | Pieces |
|---|---|
| L1 | `bal_front` (slab + parapet + rail, damage variants), `bal_wall`, `sash_door`, `bal_window`, `partition`, `cor_front`, `cor_wall`, `steel_door`, `kitchen_win`, `meter_door`, `lamp`, `ac_unit` (3 generations), `laundry`, `futon`, `plant`, `room_back` (interior card set), `downpipe`, `tank`, `antenna` |
| L2 | balcony bay, corridor bay (assembled by the plan) |
| L3 | balcony facade, corridor facade, end walls (generated) |
| L4 | slab + cores + penthouses + roof + tank |
| L5 | seed sheet / estate line-up (evidence only) |

### Budgets (triangles)

| Item | LOD0 | LOD1 | LOD2 |
|---|---|---|---|
| Balcony bay with props | ≤ 3,500 | ≤ 400 | — |
| Corridor bay | ≤ 1,500 | ≤ 250 | — |
| Default building (10 floors × 12 units) | ≤ 700k | ≤ 100k | ≤ 3k |
| Textures | streak/stain atlas 2048×1024, wall/concrete tiling sets 1024² | same | same |

Measured numbers are under "Results".

### De-risk results

See `log.md` (21:12). Labs is not installed; relative material paths do not bind; cut-out
decals, `displayColor` primvars and Japanese text render in Karma.

### Reference

`ref/reference_study.md`: 30 Wikimedia Commons photos (licences listed), counted rules, top-10
cues; `ref/contact_sheet.jpg`. Rules taken into the generator: alternating solid parapet and
white vertical-bar rail (13/15), thin projecting eave below 8 floors (17/25), windowless
gables (15/18), black/navy sans number at 0.4 floor in the top-floor band (11/13), white /
light grey paint (23/30) with one muted accent on about half the blocks, downpipes, antennas.
Kept against the photos because the brief asks for them: open-corridor type at every height
(photos show stair halls on 4–6F walk-ups), a rooftop tank on every block (1 of 25 photos).

### Parameters

Massing (floors 4–14, units 4–24, bay width 5.5–7.0, floor height, roof edge, massing from
seed with ranges), Cores (count or auto, lift auto/never/always), Style (seed, paint scheme,
building number or seeded code, 号棟 suffix, years since repaint), Dressing (props, interior
cards, edge damage, AC share, retrofit lift tower), Weathering (decals, amount, repaint
patches, texture folder), Output (LOD 0/1/2/all, collision).

### Structure (inside the asset)

`build` (SOP): `plan` → `dress` (personas) → `place_kit` (Copy to Points by `name`) with 31
`kit_*` piece subnets merged in `KIT`; `causes` (story hotspots) → `gen_shell` (plinth,
gables, roof, cores, tank, antennas, downpipes, retrofit tower), `number_font` +
`place_number`, `decals`; LOD1 (`lod1_filter`, `place_kit_lod1`, `decals_lod1`), LOD2
(`lod2_shell`); `lod_select` → `grime` → `assign` (scheme colours, patches, absolute
material paths via `opfullpath`) → `uv_world` → `OUT`. `mats`: 16 MaterialX materials.
`collision`: UCX hulls. Source of every wrangle: `work/vex/*.vfl`, build scripts
`work/py/*.py`.

### Results (default: 10 floors × 12 units, seed 1)

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

### Limits and what an artist should still do

- Weathering is light: streak decals read up close (rail-post rust, joint runs) but barely at
  facade distance; no mottled grey blotching yet (5 of 29 photos). Raise Weathering Amount, or
  add a facade-scale stain layer.
- Interiors are cards; glass shows them only at short range.
- LOD0 export is unpacked (82 MB FBX); an engine build should instance the kit pieces.
- Engine materials: the MaterialX layers (macro value noise, damp base band, grime lerp) need
  rebuilding in the engine from the exported textures, `Cd` and the `grime` attribute.
- Trees and poles in the evidence scene are simple; the sky is bluer than the reference photos.
- Only the corridor type; a stair-hall walk-up type would cover most 4–6F blocks in the photos.
