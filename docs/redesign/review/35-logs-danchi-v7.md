# Logs: danchi v7 (round 7, weathering parameters)

Development run 1 of 2 for the building generator (the user chose "two runs, review between").
A nested `claude -p` run (worktree `hp-r7`, branch `danchi/r7-weathering`, merged in 1d4eadc)
took 2 h 18 min and 527 turns, at an API-equivalent cost of $48.88 billed to the subscription. Its brief is the
round-7 brief: parameterise weathering, wear, damage and staining, show them at several values,
and keep everything engine-portable. The asset, README and showcase are in `examples/danchi/`.
The user's review page is "Danchi Weathering Review" (artifact P5Zr94QuaXWwbggyanE99d, collection
`answers`).

## Lead review

**Landed:**
- Asset `hocuspocus::danchi::1.1`, portable from a fresh checkout.
- Macro controls (age, upkeep, grime, exposure, wind, seed), four presets plus Custom, and per-layer
  auto/override for eleven layers.
- Every layer ships as vertex colour, decals on one atlas, geometry or shared textures. The README
  has the Unreal and Godot setups (not run in an engine).
- The checks pass (skeleton, damage, budgets, LOD value match, FBX re-import, fresh instance), and
  frame_critique has no fails on the 42 images.

**Seen in the showcase:**
- Weathering now reads from across the street. The presets step clearly from New to Neglected,
  which fixes the main round-6 fault.
- The grime and stain-field controls have a visible range.
- The streak control barely changes the frame at 24 m. At 1 it adds faint pinstripes, not the
  wide, layered streaks from sills and copings that the photos show.
- Edge damage at 1 is still a few small chips on the slab edges at 10 m.
- Balcony-front stains repeat floor by floor.
- The end wall's dark washes look plausible at 40 m, but bunch into a few blotches.

**Its own weathering-load check** (`showcase/checks/weather_load.md`) against the photos (median):
- soil 1.73 at Typical (2.52);
- mottle 2.4 (2.54);
- vertical streak ratio 3.7 (1.05; photos range 0.6–1.4).

So Typical has the photos' mottle but less soil, and it is about three times as stripy as any
photo. Neglected's soil is 1.86, against 12–14 for the two heavily stained walls.

**Not in this run:**
- The concrete findings of round E (wall surface still the round-6 spray recipe).
- Lot shapes.
- Mansion types.

All three are run 2's brief, after the user's answers on the review page.

**Cost drivers:** two full showcase re-renders (about 40 min) after bugs were found in finished
frames: a decal random-id cascade, and chip halos lost to vertex-colour interpolation. A cheap
1:1 crop render before the full sweep would have caught both.

## log.md

# Danchi round 7 — weathering as parameters — work log

Worktree `C:/Users/jujun/DEV/hp-r7`, branch `danchi/r7-weathering` (clean at 40126e7).
Times are local, 2026-10-27/28.

## Phase 0 — reading

- Read `examples/danchi/README.md`, every build script (`src/py/*.py`) and wrangle (`src/vex/*.vfl`),
  the round-6 log (`sk6-out/log.md`) for its traps, my memory notes (realism baseline, user
  art taste: lighting first, streak variety, 80/20, story-fit damage; engine target: no render post).
- Read `procedural-assets/SKILL.md` and `procedural-materials/references/weather-and-use.md`
  (streak variety rules, height on facade, inside corners, light substrate, exposure weights).
- Found the hard-coded paths: `hlib.py` OUT = `.../sk6-out` (and VEX at `OUT/work/vex`, which in
  the repo is `src/vex`), every script `exec(open(".../sk6-out/work/py/hlib.py"))`,
  `tex_build.py` OUTDIR and `cop_lib.py` from the `hp-r6` worktree, `piece_bal_front.py` SKILL
  from `hp-r6`. The asset's `tex_dir` default is `$HIP/../tex` (only right when the hip is in
  `work/`).
- Looked at the round-6 evidence (`docs/redesign/evidence/danchi-v6/04_building_view.jpg`,
  `02_golden_bay.jpg`) and the reference photos (`refs/img/`, a contact sheet of the 13 end and
  facade photos). Typical 35–50-year blocks (end_01, end_05, end_06, facade_02, weathering_02)
  stay light at distance but carry grey mottling on the end walls, dark runs from the gable top
  edge and under slab edges, a darker top band and base. Round 6 shows none of this at 40 m.

## Setup (23:45)

- `houdini_status` (none) → `houdini_connect {launch: headless}`: Houdini 22.0.466, pid 47684.
  Opened `work/danchi_v006.hiplc`.
- Found: the hip loaded `sk6::danchi::1.0` from `sk6-out/danchi.hdalc`. Repo and sk6-out copies
  have the same md5. Installed `$HIP/../danchi.hdalc`, uninstalled the sk6-out library, saved as
  `work/danchi_v007.hiplc`. Houdini stores library paths in the hip as `$HOME/...`/`$JOB/...`, so
  on another machine a hip needs the library installed once (README).
- Checked the asset's wrangles against `src/vex`: every snippet equals `lib.vfl + "\n" + file`
  (or the file alone for the lib-less ones), so the repo source is the truth.
- Portability edits (step 1): `hlib.py` now derives `ROOT` from a `DANCHI` global or `$HIP/..`,
  with `VEX`, `PY`, `TEXDIR`, `REPO`, `SKILLS`; every script bootstraps hlib through the same rule;
  `pieces.py` reads `piece_bal_front.py` from `PY`; `piece_bal_front.py` and `tex_build.py` take the
  skill scripts from the repo's `.claude/skills` (they pointed at the `hp-r6` worktree).
- Measured: the full asset force-cooks in 24 s; the bal_front damage chain (4 variants: cluster
  mask, edge chips, booleans) costs ~3 s, so edge damage can be a live parameter.

## Plan for the weathering system (engine first)

Everything a viewer sees must survive FBX: vertex colour RGBA, UVs, decal meshes, shared textures.
- **Vertex colour** carries paint × per-bay tint × patches × soot (baked from the grime field),
  rust on rail bases; alpha = grime (walls) or opacity (decals). Gables become a grid of quads so
  vertex gradients have somewhere to live.
- **Decal meshes** (one atlas, alpha only, colour from vertex RGB, opacity = atlas × vertex A):
  streaks of several shapes, facade-scale stain fields from layered blotches, inside-corner grime
  strips, base splash band, biological growth, efflorescence, rust runs/blooms, light worn-edge runs.
- **Geometry**: edge damage variants of the balcony front, driven by the damage controls.
- **Shaders** reduced to what an engine can rebuild in a few nodes: wall = vertex colour × tiling
  cavity × macro-variation texture (same UV, 1/40 scale); decal = vertex RGB, alpha = atlas × vertex A.
  The round-6 procedural damp band and top-floor wash (Karma-only MaterialX noise) move to decals and
  vertex colour.
- One `weather_params` detail wrangle resolves macro controls (or a preset) into every detail value,
  honouring per-detail overrides; every layer reads those detail attributes and the cause field.

## 23:55–00:20 Building the weathering system

- **1.1 definition**: `copyToHDAFile(..., new_name="hocuspocus::danchi::1.1")` into the same
  `danchi.hdalc` (1.0 kept so v001–v006 hips still load); switched the five instances with
  `changeNodeType`; unlocked `/obj/danchi` for editing. Why the rename: `sk6` was the label of
  skill-test round 6; a shipped example wants a stable publisher namespace.
- **Atlas** (`src/py/weather_atlas.py`, numpy + PIL, runs in or out of Houdini):
  `tex/weather_atlas.png` 4096², alpha only, 16 streak cells, 16 blotch cells, 8 strip cells,
  plus `weather_atlas.json` (cell rects, streak fill fractions) and `tex/macro_var.png` (tileable
  1/f value map, 40 m tile, made by inverse FFT so it tiles exactly). Looked at the atlas three
  times: blotches first had hard rock-like rims (softened, `sstep` widths ×3, rim fade), splash
  droplets were blobs (finer noise), and the "vertical" mottle was horizontal — I had the fbm
  stretch axis backwards. ~20 min.
- **weather_params** (`src/vex/weather.vfl`): presets → age/upkeep; years since repaint auto =
  min(age, lerp(24, 7, upkeep)); soiling clock = R + 0.22·(A − R); soiling S, damage D, rust Ru
  as saturating curves × a care factor; per-face driven-rain and lee factors from the wind
  bearing and exposure; every detail value auto or overridden; repaint patch rectangles.
- **Interface** (`src/py/interface.py`): replaced the Weathering tab of the 1.1 definition (the
  tab folders inside the asset have generated names like `f_mass_4`, so `replace("f_weather")`
  failed with "Invalid indices" — found them by label). Preset callback copies age/upkeep into
  the sliders; VEX also resolves presets itself, so headless or engine use without callbacks
  gives the same result. `tex_dir` default is now a Python expression: `tex/` beside the library
  file of the asset's definition.
- **Geometry**: `lib.vfl` gained `gridbox` (box with face grids, shared points); plinth, gables
  and stair towers are gridded (1 m / floor and mid-floor lines) so vertex colour has vertices.
  VEX trap: a function returning an array needs the `function` keyword (`function float[] f()`),
  otherwise "syntax error, unexpected identifier" — the error pointed into `plan` because lib is
  prepended to every wrangle.
- **Decals** (`src/vex/decals.vfl`, rewritten): 9 layers, clipped to faces, cut at repaint
  patches; sources per the skills' rules; stain fields as 3–6 layered blotches emitted against
  every face rect they cross (one stain continues across the parapet bands); chip hotspots of
  the damaged fronts (read from `kit_bal_front/cluster_vN` with `opfullpath`) shed rust and
  efflorescence. Typical: ~4,950 decals.
- **Vertex colour bake** (`src/vex/bake.vfl` + attribdelete/rename): soot field, dust on tops,
  chalking on the south, patch freshness, chip halos, rail/door/stand rust → vertex Cd + Alpha.
  The round-6 `grime` node and the procedural MaterialX layers are gone.
- **Damage**: `kit_bal_front` cluster/chip parms are expressions on `weather_params`
  (`w_dhot`, `w_dsize`, `w_dmg`); `attribtransfer` brings `damage_halo` onto the pieces; the
  dress picks damaged fronts with share = 1.1 × amount (≤ 85 %), worst columns first.
- **Materials**: wall = vertex colour × cavity × macro texture; decal = vertex RGB, opacity =
  atlas × vertex alpha. `upgrade()` in `src/py/weather_upgrade.py` applies all network changes.

## 00:20–00:35 Showcase scene, first renders

- `src/py/showcase.py`: plain ground (`/obj/ground_show`: asphalt, lawn strip, footpath, kerb),
  one camera `/obj/cam_show` + aim, `/out/karma_show` rendering only `/obj/danchi/build` and the
  ground; a 37-shot list keyed one frame per shot (constant keys on the asset parms and camera).
- Slowed down: (1) the ROP's forced objects named the asset subnet (`danchi`), which holds no
  geometry, so the first render had no building — the pattern must name `/obj/danchi/build`;
  (2) the Karma ROP's resolution is `resolutionx/y`; `res_override*` did nothing (renders came
  out 1280×720); (3) CPU Karma at 1280×720/32 spp took 74 s on the facade camera and ~4 min on
  the bay camera (glass + interiors), too slow to iterate — switched the ROP to XPU (RTX 3080 Ti).
- frame_critique on the first facade test (`--view wide --ref facade_*`): 0 fail, 1 warn
  (reference_match EMD L* 14.2: the sky was much darker than the photos' pale skies), sunlit
  walls L* 75.8, verticals lean 3.2°. Fixes: sky dome 0.34 → 0.6 and a desaturated `sky.png`
  (zenith 0.36/0.55/0.85 → 0.56/0.66/0.80); cameras level with a frame shift (`winy`).
- First Typical look at the bay camera: weathering nearly invisible. A median streak landed at
  ~9 % opacity (base 0.25 × st-scaling × median source strength 0.38). Raised the decal base
  opacities ~2×, the source-strength curve (median 0.38 → 0.51), stain layers 0.10–0.45 →
  0.15–0.55, background soot 0.16 → 0.28 × soot.
- My own check (`src/py/weather_load.py`): plain end-wall crops in 6 ordinary photos + 2 heavily
  stained ones, measured after removing the light gradient. Ordinary end walls: soil (P95−P50)
  1.0–3.0 L*, mottle 0.9–3.3 L*, dark share 0–3 %; stained walls: soil 12–14, mottle 9–10,
  dark share ~0.69. Target: New below the ordinary walls, Typical inside them, Neglected toward
  the stained ones.

## 00:30–00:40 Look passes on Typical (XPU, 960×540, 16 spp, ~10–20 s a frame)

- Motion blur smeared frames 2–3: the camera jumps between shot keys and Karma blurs the jump.
  `enablemblur` off on the showcase ROP.
- Pass 2 (wider streaks): runs were 1–3.5 cm wide, ~1 px at 10 m and invisible at 40 m. Widened
  (narrow 3–9 cm, fans 20–40 cm, curtains 0.4–1 m, layered stains 0.5–1.6 m), 30 % of joint runs
  as layered stains, worse columns ×1.5, background stain fields stronger.
- Pass 3: estimate first — streaks darkened ~0.5 % of a parapet's area on average, so no
  distance read was possible. Added a dark band under the parapet lip and a broad layered
  stain on many fronts, rain-wash columns in the vertex soot of gables and towers, more gable
  top-edge sources; gable cause stains hang from their source.
- Pass 4: still faint. Measured the atlas: streak cells averaged alpha 0.12–0.2 (90th pct
  0.2–0.4) because the generator multiplies several soft factors. `normalise()` scales each cell
  so its core sits at 0.9 (blotches 0.88); FILL fractions updated from the json. Cut uniform
  greying (0.36 → 0.18 × soot) — the photos keep light paint with local stains (80/20); greying
  everything read as grey concrete.
- Pass 5: gable runs scale with the wall (median ~1/8 of its height, tail to the base); gable
  causes moved to the upper quarter, so their stains hang from where water enters.
- Checks on the way: skeleton tiling first reported 20/8/28/7/10 "problems" — the round-6 check
  counted prims / 6 (proxy boxes); real wall pieces have 36 faces. Fixed to count instances:
  **0 problems in all 5 configurations**. Damage validation: open 0, non-manifold 0, flank runs
  0 on all four variants; `seam_changed` = 1 on all four (34 → 32 seam points) — the same with
  the round-6 constants, and the seam point *positions* are identical: the clean reference has
  two coincident points that the boolean fuses. Not a regression; reported as is.
- Budgets: LOD1 went to 105,950 (> 100k) with the gridded shell and 2,750 decals. Skipped hidden
  grid faces (gable inner faces, tower backs, plinth bottom), coarsened grid rows to floor lines,
  LOD1 keeps decals > 1.5 m² (and splash > 0.3 m²): LOD0 393,596 / LOD1 99,648 / LOD2 574.

## 00:40–00:50 Lock-in, showcase render, export checks

- Pass 6 (Typical/New/Neglected at the facade camera): a clear progression at 40 m — New crisp
  white, Typical dingy with stained fronts and washes on the end wall, Neglected heavily mottled.
  Gable background stains changed from round blots to tall hanging washes (round blots in
  mid-wall have no source). Sweep camera widened to 24 mm, ~24 m from the gable.
- `hda save /obj/danchi` → `hocuspocus::danchi::1.1`, locked, help text. All instances now use it.
- Showcase: `key_shots(SHOTS)` (37 frames), `/out/karma_show` at 1600×900, 32 spp, XPU, render job
  in the background (~75 s a frame). Effective weather values per frame read from
  `weather_params` with `hou.setFrame` → `showcase/raw/shots.json`.
- FBX: the export wrangle now splits decals into their own mesh per LOD (`danchi_decals`,
  `danchi_LOD1_decals`), since engines want decal geometry as a separate component.
  `export_fbx()` → `export/danchi_lod0/1/2.fbx` + `danchi_collision.fbx` (paths now `$HIP/../export`).
  **Re-import**: LOD0 393,626 tris (2 meshes, 16 material slots), LOD1 99,648 (2 meshes, 14),
  LOD2 574 (1 mesh, 3), collision 6 × `UCX_danchi_00..05`; vertex Cd and Alpha present as vertex
  attributes, decal alpha 0.06–0.9 survives, UVs present. Re-import triangles = the export
  instance's own count (393,626).
- **Fresh instance** from the library: cooks with 0 errors, materials bind inside it,
  `tex_dir` → `examples/danchi/tex`.
- **Damage at the extreme override** (amount 1, size 0.4 m, 4 hotspots): open 0, non-manifold 0
  on all four variants, flank runs 0/0/1/0, 800–4,228 tris per front (golden-piece budget 2.5k
  exceeded only at this extreme). At Typical: 202/304/2,046/1,050 tris, face_to_edge 0.11–0.37.
- Found: `examples/danchi/tex/` was gitignored ("generated textures not committed"), so a fresh
  checkout had no textures and the asset could not render. Changed `.gitignore` to keep the ten
  textures the materials read (16 MB) and ignore Karma's `.rat` caches and intermediate maps.

## 00:50–01:00 Critique, own check, and a lighting correction

- frame_critique on the first finished bay frames (`--view close --ref bay_*`): New, Well kept,
  Typical, Neglected all 0 fail / 0 warn; sunlit walls L* ~78; reference_match EMD L* 8.0–9.6.
  ~40 s per image, so the full set runs in a background batch (`src/py/run_critique.py`).
- Own check (`weather_load.py`) on the facade-camera presets, west end wall crop (projected with
  `toNDC` through the camera: 448,335–522,705 px): the end wall was in **shade** (L* 30–43
  against 55–83 in the photos) and its stain contrast far below the photos — mottle 0.43 / 0.80
  / 0.89 / 1.22 L* for New / Well kept / Typical / Neglected vs 0.9–3.3 on ordinary photo end
  walls and 8.7–9.6 on the stained ones; dark share 0 for every render.
- Why: the sun came from the south-east (round-6 rig, cameras from the SE), but my facade and
  sweep cameras look from the south-west, so the end wall they see was unlit — against the
  brief's "sun on the camera's side". Swung the sun to ry −40 (from the SW, still raking the
  south facade) and scaled stain-field opacity by (0.6 + 0.8 S²) so neglect builds up harder.
  Cancelled the showcase render at 14/37 frames (~8 min lost) to re-render everything with it.

## 01:00–01:10 Final showcase render, LOD value match, re-export

- Low-res check with the sun from the SW (frames 5–8): the end wall is lit; New crisp, Well kept
  faint runs, Typical grey washes from the top edge, Neglected heavy stains. Own check on these:
  end-wall mottle New 0.66 / Well kept 1.10 / Typical 1.55 / Neglected 2.54 L*, soil 1.11 / 1.54 /
  1.87 / 2.97, dark share 0 / 0 / 0.011 / 0.052 (photos: ordinary 0.9–3.3 mottle, stained 8.7–9.6).
- `hda save` (lock), final showcase render started: 37 frames, 1600×900, 32 spp, XPU, ~40 s a frame.
- **LOD value match** (CPU Karma beside the GPU job, `/out/karma_lod`, the round-6 camera at
  170 m, frames 101–103 keyed to LOD 0/1/2, mean linear luminance of the south facade): first
  LOD1 −10.2 %, LOD2 +32.9 % — the new weathering darkens LOD0 and the sun moved, so the round-6
  recess calibration no longer held. (I first measured on a wrongly read crop and got −2.5/+7.5 %;
  the image preview was scaled 1.44×, so my eyeballed pixel box was off. Re-measured on the
  projected box, which was right.) Added `lod1_k`/`lod2_k` albedo factors (spare parms on `bake`):
  1.11 / 0.75 → **LOD1 −0.1 %, LOD2 −0.5 %**.
- Re-exported and re-imported after the change: 393,626 / 99,648 / 574 tris, 16 / 14 / 3 slots,
  decals separate, vertex alpha present, 6 UCX hulls. Fresh instance: 0 errors, 6.1 s.

## 01:10–01:20 Waiting on the render: README, reproducibility, a spot check

- Filled the README Showcase and Limits sections; added the sky note (less saturated than
  round 6) and the LOD sheet; fixed the rebuild commands to run from the repo root.
- `shots.json` had been written by an ad-hoc `houdini_python` snippet; moved it into
  `showcase.py` as `dump_shots()` so the showcase can be rebuilt from the scripts alone.
- Spot check of finished frames: the preset strip reads New → Neglected at both cameras. In the
  sweeps, frame 14 (edge damage 0) has twice the end-wall contrast of its neighbours (s.d. 8.9
  vs ~4.5 grey levels on the same crop) although only the damage amount changes there — to be
  explained before the sheets are made.

## 01:20–01:35 Sweep isolation bug: found, fixed, re-render

- Cause of the frame-14 outlier: `decals.vfl` seeded every decal from one running id (`did++`).
  The chip decals on damaged balcony fronts come early in the script, so the number of damaged
  fronts (edge damage amount) shifted the ids of every later section: corridor side, gables,
  plinth, towers, stain fields. Edge damage 0 gave a different end wall. The same held for
  streaks at 0 (the gable dark-band loop is skipped), splash 0 and growth counts.
- Fix: each section and each gable sub-block starts its own id range (`did = 1000000` for the
  chips, 2M corridor, 3M + 100k·end (+20k…50k per sub-block) gables, 4M plinth, 5M towers,
  6M + 100k·family stain fields). The balcony section keeps its old ids.
- Check (in Houdini, decals per layer: count and sum of positions across the sweep frames):
  edge damage 0/0.5/1 → north and gable decals identical, only the south (chip) decals change;
  streak sweep → only the streak/fringe/band layers change; grime → corner layer; stain sweep →
  only the stain layer. Before the fix north and gable decals differed at every damage value.
- Cancelled the showcase render at 32/37 (~17 min of render lost; the old frames went to the
  scratchpad) and re-rendered all 37: the stains elsewhere changed, so every image had to be
  re-rendered to stay one building.
- Re-ran what the decals touch: budgets at Typical 393,520 / 99,726 / 574 (decals 5,176 / 945 /
  0); Neglected LOD1 99,942, age 60 / upkeep 0.1 LOD1 99,946 (under 100k, thin margin: LOD1
  decals grow with weathering). FBX re-export and re-import: same triangles, meshes
  danchi + danchi_decals, LOD1 + decals, LOD2; 16/14/3 slots; Cd, Alpha, uv; 6 UCX hulls.
  Fresh instance: 0 errors, materials bind, tex_dir → examples/danchi/tex. Skeleton and damage
  checks not re-run: the change is inside the decal wrangle only.
- Slowed me down: I only caught this by looking at a statistic across the sweep frames;
  a by-eye look at the contact sheet would have read it as "edge damage changes the stains".

## 01:35–01:50 Sheets, critique, own check; edge damage shown at 10 m; chip halo fix

- Re-render of 37 frames done (17 min). `showcase_sheets.py` → 37 JPGs (all < 300 KB), sheets,
  manifest. frame_critique over the 37: 0 fails; every bay image passes every test
  (reference_match EMD L* 6.6–9.0); every facade/sweep image warns on reference_match (EMD L*
  15.4–16.3 vs warn 13, fail 19.1). Cause: half the frame is flat sky (sky_share 0.50) and the
  ground is plain, with nothing dark (trees, cars, neighbours): frame contrast 0.56 of the
  photos. Colour (EMD C* ~6.7) passes. Left as is; the brief allows plain ground.
- Own check on the final facade frames: see README (mottle New 0.65 / Well kept 1.11 / Typical
  2.39 / Neglected 3.32 L*; ordinary photo walls 0.9–3.3, median 2.54; stained 8.7–9.6).
- The edge-damage sweep at the sweep camera hardly changes: chips of 3–30 cm are a few pixels
  at 24 m. Added the same sweep at the bay camera (frames 38–42, appended so 1–37 keep their
  numbers) and a reset key after the last shot, so frames 101–103 (LOD check) are back on BASE
  instead of holding the last shot's damage override.
- At 10 m the bay sweep showed parapet soot changing with damage. Decals were identical apart
  from the chip rust/efflorescence (checked prim by prim), so it was the vertex colour: the chip
  halo field reaches 1.5 hotspot radii (up to ~1.3 m) and the bake lifted the whole field toward
  the substrate; and the damaged variants lost slab-edge grime in the boolean/reduce (point mean
  0.14 vs 0.235 on the clean front, some values negative). I first measured "damaged fronts 25 %
  lighter" — that was a per-vertex average, biased to the dense chip areas; area-weighted the
  fronts were equal on average (0.463 vs 0.462), so the defect was local, not overall.
  Fix: `bake.vfl` wears only the inner halo (smooth 0.55–0.95); `weather_upgrade.py` adds
  `eg_vN` wrangles that copy edge_grime from the clean front's surface (xyzdist + primuv).
  After: damaged 0.456 vs clean 0.462 (area-weighted outer face), all bal_front paint 0.380 vs
  0.383. Re-ran `upgrade()` on the instance (idempotent: no errors, lod factors kept), saved.

## 01:50–02:05 The halo as a decal; final asset; final render

- The bay frames with the narrowed halo showed the soot staying put, but also light diagonal
  wedges on the damaged fronts (present before the fix too): vertex colour interpolated along
  the long thin triangles from a chip vertex to the far corners. A round halo cannot live in
  vertex colour on that mesh. Moved it to a decal: one soft WEAR blotch per spall on the face
  (blotch cells 0/1, radius 0.8 × hotspot radius, alpha (0.25 + 0.35 s) × wear ≤ 0.5), and
  removed the halo lift from `bake.vfl`. Bay crops at damage 0 / 0.5 / 1: soot identical,
  chips with light worn blotches, no wedges.
- Area-weighted outer-face vertex colour now damaged 0.446 vs clean 0.462 (the light substrate
  is in the decal). Re-ran `upgrade()` (idempotent), saved the asset (locked).
- Final asset checks: budgets Typical 393,624 / 99,726 / 574 (decals 5,228 / 945 / 0),
  Neglected 462,030 / 99,942, age 60 upkeep 0.1 485,856 / 99,946; FBX export + re-import same
  triangles, 2/2/1 meshes, 16/14/3 slots, Cd/Alpha/uv, 6 UCX; fresh instance 0 errors, 3.9 s;
  damage validation unchanged (closed, 0 non-manifold, flank 0, 202/304/2,046/1,050 tris);
  LOD value match LOD1 +0.6 %, LOD2 +0.4 %.
- Final showcase render started: frames 1–41 (42 rendered just before with the same asset).
- Slowed me down: I misread my own metric (per-vertex vs area-weighted average) and nearly
  reported "damaged fronts 25 % lighter"; the real problem was local and only a 1:1 crop at
  10 m showed it. Two showcase re-renders (~40 min) followed from bugs found by looking at
  finished frames rather than before rendering.

## 02:05–02:20 Final showcase, checks, README; save and quit

- Final render frames 1–41 (11 min) + 42 → `showcase_sheets.py`: 42 JPGs (max 343 KB, all
  < 400 KB), sheets (preset strips ×2, sweep per control incl. the bay edge-damage sweep, a 1:1
  detail sheet per sweep — added because one control's effect is a few pixels at contact-sheet
  scale — sweeps_all, age_upkeep_grid, lod_value_match), manifest.json (42 images with set
  parms, all weathering values and the effective values).
- Gable crop across the edge-damage sweep now constant (s.d. 6.0 at every value; before the id
  fix 8.9 at 0 vs ~4.5 elsewhere). Streak sweep: the end-wall crop hardly changes (runs are thin;
  the broad washes are stain fields and soot) — said so in the README with the detail sheets.
- frame_critique on all 42 (`run_critique.py`, now reuses results newer than their image):
  0 fails; bay images pass everything (EMD L* 6.6–9.0); 33 wide images warn on reference_match
  only (EMD L* 15.3–17.1, warn 13, fail 19.1): sky share 0.45–0.56, plain ground, frame contrast
  0.52–0.65 of the photos; colour EMD 6.6–7.0 passes.
- Own check (final): mottle New 0.65 / Well kept 1.11 / Typical 2.40 / Neglected 3.33 L*
  (ordinary photo walls 0.9–3.31, median 2.54; stained 8.7–9.6); soil low (Typical 1.73 vs photo
  median 2.52); dark share high (0.05/0.09 vs ≤ 0.024); vstreak 1.6–4.0 vs 0.6–1.4. Grid monotonic
  on both axes. Written up in README Results with the full table and caveats.
- README: Results filled (all checks with final numbers), Showcase (cameras, files, sheets,
  what each sweep shows, rebuild commands), Limits (incl. LOD1's thin budget margin). Help text
  in the asset checked (no stale halo text). `.gitignore`: showcase/raw/ ignored (PNG frames and
  per-image critique JSON); the rest of showcase/ (11 MB) is the deliverable.
- hip saved (work/danchi_v007.hiplc), Houdini quit.

## What slowed me down (whole round)

1. Hip loaded the HDA from the old scratch path; asset tab folders have generated names
   (`f_mass_4`), so `replace("f_weather")` failed until I looked them up by label.
2. VEX syntax traps: `float[] f()` needs `function`, functions defined mid-snippet, ambiguous
   `noise()` overloads.
3. Karma ROP details: `objects` forced to a subnet path, `resolutionx/y` vs `res_override*`,
   motion blur smearing keyed shot lists, CPU Karma far too slow (XPU instead).
4. The first weathering was invisible at 40 m (sub-pixel streaks, low alphas, atlas cells that
   averaged 0.12–0.2 alpha) — several look iterations to get Typical to read as 35 years.
5. My first showcase sun was on the far side of the end wall (rig from round 6, cameras moved):
   one cancelled render.
6. Three bugs found only by looking at finished renders, each costing a re-render: the running
   decal id (controls reseeding each other), the vertex-colour chip halo (local fading and
   wedges), and nothing showing in the edge-damage sweep at 24 m. Checking sweeps numerically
   (per-layer decal diffs, crop statistics) before rendering would have saved ~45 min.
7. A misleading metric of my own (per-vertex instead of area-weighted average) almost made me
   report a 25 % brightness error that was not there.
8. Renders: ~6 full or partial showcase renders at 10–20 min each were the bulk of the wall time.
