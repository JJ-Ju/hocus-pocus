# danchi — procedural 1980s Japanese public housing block (Houdini HDA)

`hocuspocus::danchi::1.1` (and the round-6 `sk6::danchi::1.0`), library `danchi.hdalc`
(Houdini 22.0.466, Indie). Round 7 made weathering, wear, damage and staining fully parameterised
and engine-ready; see "Version 1.1" and the showcase in `showcase/`.

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
| Textures | weathering atlas 4096² (one channel), macro map 1024², wall/concrete tiling sets 1024² | same | same (no decals) |

Measured numbers are under "Results".

## De-risk results

From the round-6 log (not in the repo). Labs is not installed; relative material paths do not bind; cut-out
decals, `displayColor` primvars and Japanese text render in Karma.

## Reference

`work/ref/reference_study.md` (local, `work/` is not committed): 30 Wikimedia Commons photos
(licences listed), counted rules, top-10 cues; `work/ref/contact_sheet.jpg`. Round 7 also used the
39-photo set in `docs/redesign/evidence/refs/` (`fetch_refs.py`). Rules taken into the generator: alternating solid parapet and
white vertical-bar rail (13/15), thin projecting eave below 8 floors (17/25), windowless
gables (15/18), black/navy sans number at 0.4 floor in the top-floor band (11/13), white /
light grey paint (23/30) with one muted accent on about half the blocks, downpipes, antennas.
Kept against the photos because the brief asks for them: open-corridor type at every height
(photos show stair halls on 4–6F walk-ups), a rooftop tank on every block (1 of 25 photos).

## Using it from a fresh checkout

1. Install the library once: *Assets > Install Asset Library* → `examples/danchi/danchi.hdalc`
   (or add `examples/danchi` to `HOUDINI_OTLSCAN_PATH`). Hip files store library paths as
   `$HOME/...` or `$JOB/...`, so a scene from another machine needs this step.
2. Drop *Danchi Block* (`hocuspocus::danchi::1.1`) into `/obj`. Its **Texture Folder** defaults
   to `tex/` beside the library file it was loaded from (a Python expression on the definition's
   `libraryFilePath()`), so it finds `examples/danchi/tex/` wherever the checkout lives. The
   textures the materials read are committed; the rest of `tex/` is regenerated by the scripts.
3. The build scripts find their files the same way. Run any of them through `houdini_python`
   (or a Python shell in Houdini) with the root set:
   ```python
   DANCHI = "<checkout>/examples/danchi"
   exec(open(DANCHI + "/src/py/build.py").read())
   ```
   Without `DANCHI` they fall back to `$HIP/..` (a hip saved in `examples/danchi/work/`).
   `hlib.py` defines `ROOT`, `VEX` (`src/vex`), `PY` (`src/py`), `TEXDIR` (`tex`) and `SKILLS`
   (the repo's `.claude/skills`, for `cop_lib.py` and the damage VEX).

Rebuild order from scratch: `build.py` (network with proxies) → `pieces.py`, `pieces_l1.py`,
`piece_bal_front.py` (the kit) → `materials.py` → `build.py` again (wires the kit and runs
`weather_upgrade.upgrade()`). Textures: `tex_build.py` in Houdini (Copernicus tiling maps, sky,
and the weathering maps), or `python src/py/weather_atlas.py tex` alone for the atlas and macro
map. Interface: `interface.py` (`weather_folder()`, `upgrade_definition()`).

## Version 1.1: namespace and what changed

`hocuspocus::danchi::1.1` in the same `danchi.hdalc`; `sk6::danchi::1.0` stays in the library so
the round-6 scenes (`work/danchi_v001–v006`) still load. The namespace changed because `sk6` was
the label of a skill-test round (round 6); an example that ships with HocusPocus should carry the
project's name, and the next round would otherwise produce an `sk6` asset made in round 7.

1.1 makes weathering, wear, damage and staining fully parameterised and engine-ready:
- a `weather_params` stage resolves a preset or the macro controls into every detail value;
- 9 decal layers on one alpha atlas, clipped to their faces and cut at repaint patches;
- a vertex-colour bake (soot, dust, chalking, patches, rust) replaces the round-6
  point grime and the Karma-only MaterialX layers (procedural noise, damp band, top wash);
- the balcony-front damage variants follow the Edge Damage controls;
- plinth, gables and stair towers are gridded (1 m columns, floor lines) so vertex colour has
  vertices to vary across; hidden faces are left out;
- decals export as their own mesh per LOD.

## Parameters

Massing (floors 4–14, units 4–24, bay width 5.5–7.0, floor height, roof edge, massing from seed
with ranges), Cores (count or auto, lift auto/never/always), Style (seed, paint scheme, building
number or seeded code, 号棟 suffix), Dressing (props, interior cards, Edge Damage Geometry on/off,
AC share, retrofit lift tower), **Weathering** (below), Output (LOD 0/1/2/all, collision).

### Weathering tab

| Control | Range | Meaning |
|---|---|---|
| Preset | New, Well Kept, Typical, Neglected, Custom | sets Age and Upkeep and makes the repaint cycle automatic; Custom uses the sliders |
| Age (years) | 0–60 | years since construction: concrete damage, edge wear, efflorescence, rust depth |
| Upkeep | 0–1 | maintenance: repaint cycle lerp(24, 7) years, cleaning, repairs; more upkeep also means more visible repaint patches |
| Repaint Cycle from Age and Upkeep / Years Since Repaint | toggle / 0–60 | years since repaint = min(age, lerp(24, 7, upkeep)) when on; soiling restarts at each repaint and older stains ghost through at 22 % |
| Urban Grime | 0–1 | site pollution: soot greying, stain fields |
| Weather Exposure | 0–1 | sheltered → open/coastal: driven rain on windward faces (longer, stronger runs, washed corners), crust on lee faces |
| Prevailing Wind and Rain From | 0–360° | compass bearing (0 N, 90 E, 180 S, 270 W); balconies face south (+Z) |
| Weathering Seed | int | reseeds causes, streaks, stains, patches without changing the building |
| Auto Intensity | 0–2 | scales every auto value (1 = calibrated) |
| Decal Meshes, Texture Folder | | decal layers on/off; `tex/` beside the library |

Grime, exposure, wind and seed belong to the site, so presets leave them alone.

**Presets** (defaults for the site: grime 0.5, exposure 0.6, wind 200°):

| Preset | Age | Upkeep | Years since repaint | Soiling S | Damage D | Streaks | Stain fields | Soot | Edge damage (largest) | Rust | Patches | Efflorescence | Growth | Splash |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| New | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Well Kept | 15 | 0.85 | 9.6 | 0.43 | 0.22 | 0.39 | 0.29 | 0.32 | 0.22 (6.7 cm) | 0.31 | 1 | 0.08 | 0.18 | 0.55 |
| Typical | 35 | 0.5 | 15.5 | 0.80 | 0.56 | 0.72 | 0.61 | 0.60 | 0.56 (15.6 cm) | 0.67 | 2 | 0.44 | 0.57 | 0.84 |
| Neglected | 45 | 0.12 | 22.0 | 1.13 | 0.75 | 1.0 | 0.89 | 0.84 | 0.75 (21.6 cm) | 0.97 | 1 | 0.88 | 1.0 | 1.0 |

**How the macro controls drive the details** (`src/vex/weather.vfl`). With A = age, U = upkeep,
R = years since repaint, G = grime, X = exposure:
- soiling clock Es = R + 0.22 (A − R); care = lerp(1.4, 0.7, U);
  soiling **S** = (1 − e^(−Es/14)) · care; damage **D** = 1 − e^(−A · lerp(1, 0.4, U) / 30);
  corrosion Ru = (1 − e^(−(R + 0.5 (A − R))/25)) · care.
- per face (S, N, W, E): driven rain = (1 − 0.6 X) + 1.5 X · max(0, n·wind), lee = X · max(0, −n·wind).

Each detail folder has **Override** (off = auto). Auto values:

| Detail | Controls (override) | Auto |
|---|---|---|
| Edge Damage | Amount, Largest Size (m), Hotspots per Damaged Front | D; lerp(0.03, 0.30, D^1.3); round(1 + 2.5 D). Share of damaged fronts = 1.1 × amount (≤ 85 %), worst columns first |
| Edge Wear | Amount | 0.25 S + 0.75 D (0 when new): light substrate runs on exposed arrises, worn blotches around chips |
| Streaks | Amount, Density, Length, Long-Run Share, Width, Intensity, Colour Variation, Top-Floor Bias | S (0.75 + 0.25 X); 1; 0.7 + 0.6 X + 0.3 S; 0.05 + 0.1 X; 1; 1; 0.3 + 0.5 S; 0.4 + 0.8 X |
| Stain Fields | Amount, Blotch Size | S (0.5 + 0.5 G) · 1.15 − 0.08; 1 |
| Grime | Soot Darkening, Inside Corners | S (0.3 + 0.9 G); 1.1 S |
| Rust | Amount | Ru |
| Repaint Patches | Patches, Contrast | round(min(A/12, 4) (0.3 + 0.7 U)) when A > R; 0.3 + 0.7 S |
| Efflorescence | Amount | 0.8 (A/45)^1.5 (1.2 − 0.8 U) |
| Biological Growth | Amount | 0.9 S (1.3 − U) |
| Base Splash Band | Amount, Height (m) | 0.2 + 0.8 S (0 when S ≈ 0); 0.3 + 0.4 X |

### What each layer does (the realism rules)

From `procedural-materials/references/weather-and-use.md` and the user's picks:
- **Streaks start at features, never mid-wall**: rail-post pockets (rust), the V-joints at the
  ends of each solid parapet (runs, fans, layered stains), low points along parapet tops at
  irregular spacing with clean gaps, the drip-less corridor parapet tops (fringe), sill ends
  (balcony window, kitchen window, stair-landing windows: V fans), downpipes (a dark line down
  each side), gable and penthouse top edges, and the chips of damaged fronts (rust from the
  spall, efflorescence).
- **Variety per source**: seeded strength (most faint, 20–30 % dominant), power-law lengths
  clipped to the face (gables: median ~1/8 of the wall height, a tail to the base), widths from
  3 cm runs to 1.6 m curtains where water collects (against the partition fin, under leaks),
  colour by cause (soot, damp green-black — more on the north side — rust, pale washed bands
  on the windward gable corner), layered build-up from overlapping runs at 10–60 %.
- **More rain at the top**: strength and count × (1 + bias · (floor/top)^1.5); a dark band under
  the parapet lip and under the roof edge; windward faces × driven rain.
- **80/20 at several scales**: 3–7 cause stories per facade and 1–3 per gable (leak, rust,
  neglect, impact) drive every layer; 1–2 columns of flats in 5 are much worse (×1.5); a faint
  background everywhere so nothing is pristine.
- **Stain fields**: each is 3–6 layered blotches (15–55 % × amount) clipped to every face rect it
  crosses, so one stain continues across the parapet bands; on end walls they hang from the top
  edge or from a cause, never as round blots in mid-wall.
- **Inside corners collect**: grime strips where walls meet floors, soffits, fins and partitions,
  and down the corners between stair towers and the corridor face.
- **Damage fits the age and radiates from a centre**: hotspots from `cluster_mask` (skill
  script) with the largest break at the centre and smaller bites around it; a new block has none,
  a well-kept one small chips (6.7 cm), a typical one spalls to ~16 cm.
- **Light substrate under grime**: chip faces are concrete; a soft worn blotch (decal) around
  each spall; worn-edge runs (half to two thirds of each edge clean) on the parapet top arris,
  slab bottom edge and gable corners. (A vertex-colour halo was tried first: on the long
  triangles of the chipped fronts it smeared into light wedges and cleaned the soot around it.)
- **Base**: a ragged splash band on every ground-level wall, algae on the north base and the
  shaded gable halves, a white tide mark where efflorescence runs.
- **Repaint patches**: rectangles of bays × floors (long faces) or 1 m columns × floors (gables);
  newer paint is cleaner and a few percent off in tone; decals crossing them are cut and fainter.

## Structure (inside the asset)

`build` (SOP): `plan` → **`weather_params`** (presets, macro → detail values, per-face rain and
lee, repaint patches) → `dress` (personas, damaged-front share) and `causes` (story hotspots) →
`place_kit` (Copy to Points by `name`) with 31 `kit_*` piece subnets merged in `KIT`;
`gen_shell` (plinth, gables, roof, cores, tank, antennas, downpipes, retrofit tower; gridded
plinth, gables and towers), `number_font` + `place_number`, **`decals`** (inputs: causes, shell,
dress); LOD1 (`lod1_filter`, `place_kit_lod1`, `decals_lod1` keeps decals > 1.5 m²), LOD2
(`lod2_shell`); `lod_select` → `assign` (scheme colours, per-bay tint, repaint patches with
`fresh`, absolute material paths via `opfullpath`) → `ytop` → **`bake`** (vertex colour) →
`del_prim_cd` → `vcol_to_cd` → `del_vcol` → `uv_world` → `OUT`. `kit_bal_front`: four damage
variants whose hotspot count and break sizes are expressions on `weather_params`, with
`halo_vN` (attribute transfer of `damage_halo`, kept on the pieces as a mask; the bake does not use it) and `eg_vN` (slab-edge grime copied from the clean front, which the boolean would otherwise interpolate away). `mats`: 16 MaterialX materials. `collision`:
UCX hulls. Wrangle sources: `src/vex/*.vfl` (each asset snippet is `lib.vfl` + the file).

## Engine notes (Unreal, Godot)

Everything the weathering does is in data that FBX carries; nothing depends on Karma or on a
render pass.

| Carrier | What it holds |
|---|---|
| Vertex colour RGB (`Cd`, linear) | paint scheme × per-bay tint × repaint patch × baked soot (shelter, lee, band under the roof edge, base, slab-edge line, cause hotspots, neglected flat columns), dust on tops, south-face chalking, rust on rails, doors and the tank stand; decal colour on decals |
| Vertex colour A (`Alpha`) | decal opacity on decal meshes; 1 everywhere else |
| UV 0 (`uv`) | world-space box UVs in metres on walls and props (tile with a scale); atlas UVs on decals |
| Decal meshes (material `decal`) | quads 4–10 mm off their faces: streaks, stain fields, corner grime, splash band, growth, efflorescence, rust runs and blooms, worn-edge runs. LOD1 keeps the large ones (`dlod`), LOD2 none |
| Geometry | chipped balcony fronts (4 damage variants, picked per bay), gridded plinth, gables and towers |
| Shared textures (`tex/`) | `weather_atlas.png` (decal alpha, 4096², one channel), `macro_var.png` (40 m value variation, tiles), `spray_ao.png`, `spray_normal.png` (2 m spray-tile paint), `concrete_*.png` |

Material slots in the FBX are the `mat` names: `paint_ext`, `coping`, `soffit`, `concrete`,
`glass`, `decal`, `steel`, `alu`, `board`, `frp`, `room`, `fabric`, `plastic`, `sign`, `floor`,
`metal`. Only the wall slots (`paint_ext`, `coping`, `soffit`) and `decal` need the graphs below;
the others are vertex colour × constant roughness (`alu`, `metal`: metallic 1).

**Colour space.** `Cd` is linear albedo. Check that your FBX import keeps vertex colours linear
(Unreal's Vertex Color node and Godot's `COLOR` return the stored value). If a pipeline sRGB-encodes
them on import, the walls come out too light: decode with a power of 2.2 after the vertex colour.
Treat `weather_atlas.png`, `macro_var.png` and `spray_ao.png` as linear data (no sRGB).

### Unreal

- **Wall (`M_DanchiWall`, used by `paint_ext`, `coping`, `soffit`).** Opaque, default lit.
  - `TexCoord[0] × 0.5` → Texture Sample `spray_ao` (linear) → R → Lerp(0.95, 1.0) = cavity.
  - `TexCoord[0] × 0.025` → Texture Sample `macro_var` (linear) → R → `saturate((R − 0.25) / 0.5)`
    → Lerp(0.94, 1.06) = macro.
  - Base Color = `VertexColor.RGB × cavity × macro`.
  - Normal = `spray_normal` at `TexCoord[0] × 0.5` (normal map), FlattenNormal to 0.6 (soffit 0.4).
  - Roughness 0.86, Specular 0.4.
- **Decal (`M_DanchiDecal`, slot `decal`).** Best as a mesh decal: Material Domain *Deferred
  Decal*, Decal Blend Mode *Translucent* (DBuffer: Color, Roughness). Base Color =
  `VertexColor.RGB`, Opacity = `weather_atlas(TexCoord[0]).R × VertexColor.A`, Roughness 0.9. The
  quads are already offset 4–10 mm, so they also work as a plain *Translucent* surface material
  (Lighting Mode *Surface ForwardShading*) if mesh decals are not wanted; then sort priority by
  layer is not needed because they never overlap a wall in depth.
- LODs: import `danchi_lod0/1/2.fbx` as LODs of one static mesh, or let Houdini Engine read the
  `lod0/lod1/lod2` groups with LOD = All. Collision: `danchi_collision.fbx` holds `UCX_danchi_NN`
  hulls for the mesh named `danchi`.

### Godot 4

Import the FBX (or convert to glTF); assign these as material overrides on the surfaces.

```glsl
// danchi_wall.gdshader — paint_ext, coping, soffit
shader_type spatial;
uniform sampler2D spray_ao : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D macro_var : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D spray_normal : hint_normal, filter_linear_mipmap, repeat_enable;
uniform float normal_depth = 0.6;   // 0.4 on soffits
void fragment() {
    float cav = mix(0.95, 1.0, texture(spray_ao, UV * 0.5).r);
    float mac = mix(0.94, 1.06, clamp((texture(macro_var, UV * 0.025).r - 0.25) / 0.5, 0.0, 1.0));
    ALBEDO = COLOR.rgb * cav * mac;
    NORMAL_MAP = texture(spray_normal, UV * 0.5).rgb;
    NORMAL_MAP_DEPTH = normal_depth;
    ROUGHNESS = 0.86;
    SPECULAR = 0.4;
}
```

```glsl
// danchi_decal.gdshader — the decal slot
shader_type spatial;
render_mode blend_mix, depth_draw_never, cull_back;
uniform sampler2D weather_atlas : hint_default_black, filter_linear_mipmap;
void fragment() {
    ALBEDO = COLOR.rgb;
    ALPHA = texture(weather_atlas, UV).r * COLOR.a;
    ROUGHNESS = 0.9;
}
```

Every other slot: `ALBEDO = COLOR.rgb;` with its roughness (and `METALLIC = 1.0` for `alu`,
`metal`); `glass` as a transparent material.

## Showcase (`showcase/`)

One building (default: 10 floors × 12 units, seed 1), true scale, plain ground (asphalt, lawn
strip, footpath, kerb), the same light in every image: a distant sun 28° high from the
south-west (on the camera side of the south facade and the west end wall, intensity 0.72) and a
sky dome (`tex/sky.png`, intensity 0.6). Karma XPU, 1600 × 900, 32 samples, no motion blur.
Cameras are level at eye height (1.6 m) with a vertical frame shift, so verticals stay straight:

| Camera | Position → aim | Lens | Shows |
|---|---|---|---|
| `bay` | (6.5, 1.6, 15.5) → (−1, 1.6, 5), shift 0.32 | 28 mm | the golden bay, ~10 m |
| `facade` | (−58, 1.6, 36) → (−22, 1.6, 0), shift 0.36 | 24 mm | the south facade and the west end wall, 37–60 m |
| `sweep` | (−58, 1.6, 22) → (−36, 1.6, 2), shift 0.38 | 24 mm | the west end, ~24 m to the end wall |

Images (uncaptioned JPGs, each under 400 KB):
- `preset_bay_{new,well_kept,typical,neglected}.jpg`, `preset_facade_….jpg`: the preset strip;
- `sweep_{streaks,edge_damage,grime,stain_fields}_{000,025,050,075,100}.jpg`: each main detail
  control with its Override on at 0, 0.25, 0.5, 0.75 and 1, every other layer at its Typical
  auto value, at the `sweep` camera;
- `sweep_edge_damage_bay_{000,…,100}.jpg`: the edge-damage sweep again at the `bay` camera,
  because chips of 3–30 cm are only a few pixels at 24 m;
- `grid_age{10,35,60}_upkeep{090,050,010}.jpg`: Age × Upkeep (Custom preset, automatic repaint).

Contact sheets with labels: `sheets/preset_strip_bay.jpg`, `sheets/preset_strip_facade.jpg`,
`sheets/sweep_<control>.jpg` (and `sweep_edge_damage_bay.jpg`), `sheets/sweep_<control>_detail.jpg`
(the same five values as 1:1 crops: most of what one control changes is a few pixels wide at
contact-sheet scale), `sheets/sweeps_all.jpg`, `sheets/age_upkeep_grid.jpg`.

What the sweeps show: **streaks** add runs at the parapet V-joints, rail posts and sill ends and
thin runs from the end wall's top edge (3–15 cm runs, wider curtains where water collects); the
broad washes on the end wall are stain fields and soot, so this sweep changes the end wall less
than the next ones. **Edge damage** adds chips along the slab and parapet edges with worn blotches
and rust at the spalls (read it at the bay camera). **Grime** greys the whole building from
clean paint (0) to heavy soot (1). **Stain fields** add the layered blotches and hanging washes.
`manifest.json` lists every image with its file, group, camera, label, the parms the shot set,
the full set of weathering parm values, and the effective values `weather_params` resolved for
it (age, upkeep, years since repaint, soiling, streak, stain, soot, damage …), for a comparison
page. `critique.json` holds the frame_critique results per image; `checks/weather_load.*` the
weathering-load check below (table, JSON, and a strip of every crop it measured).

`sheets/lod_value_match.jpg` shows LOD0/1/2 side by side at 170 m (the LOD check below).

The sky (`tex/sky.png`, from `tex_build.py`) is less saturated than in round 6 (horizon
0.84/0.86/0.88, zenith 0.56/0.66/0.80 linear), closer to the hazy blue-grey of the reference
photos; the round-6 idea is kept: sun on the camera's side, sunlit walls around L* 75–92.

Rebuild: `src/py/showcase.py` in Houdini (`setup()`, `key_shots(SHOTS)`, `dump_shots(SHOTS)`,
render `/out/karma_show` frames 1–42), then from the repo root
`python examples/danchi/src/py/showcase_sheets.py examples/danchi examples/danchi/showcase/raw/shots.json`
and `python -I examples/danchi/src/py/run_critique.py .`.

## Results (default: 10 floors × 12 units, seed 1, preset Typical)

| Check | Result |
|---|---|
| Skeleton tiling (5 configurations, gaps/overlaps and piece counts per floor) | 0 problems in all five (`checks.skeleton()`; the counter now counts piece instances — the round-6 version divided prim counts by 6, which only held for the proxy boxes) |
| Golden piece damage, Typical (4 variants) | closed, 0 non-manifold, flank runs 0, edge share 0.90–1.0, face_to_edge 0.11–0.37, 202 / 304 / 2,046 / 1,050 tris |
| Golden piece damage, extreme override (amount 1, 0.4 m, 4 hotspots) | closed, 0 non-manifold, flank runs 0/0/1/0, 800–4,228 tris (above the 2.5k piece budget only at this extreme) |
| Seam check | seam point positions identical to the clean piece; the validator's `seam_changed` flag is 1 on every variant because the clean reference holds 2 coincident points that the boolean fuses (34 → 32), the same with the round-6 settings |
| Triangles LOD0 / LOD1 / LOD2, Typical | 393,624 / 99,726 / 574 (budgets 700k / 100k / 3k); decals 5,228 (10,456 tris) in LOD0, 945 (> 1.5 m²) in LOD1, none in LOD2 |
| Triangles, heaviest settings shown | Neglected 462,030 / 99,942 / 574; age 60, upkeep 0.1: 485,856 / 99,946 / 574. LOD1 stays under 100k but with little margin, because its decal count grows with weathering (2 decals at New, ~1,050 at the heavy end) |
| LOD value match at 170 m (mean facade luminance, Typical) | LOD1 +0.6 %, LOD2 +0.4 % (target ±3 %; before the `lod1_k`/`lod2_k` factors: −10.2 % / +32.9 %) |
| Sweep isolation (decal count and positions per layer, compared across the sweep frames) | each control changes only its own layers: streaks → the streak, fringe and band layers; stain fields → the stain layer; edge damage → the chip rust, efflorescence and worn blotches on the damaged south fronts, with the north side and end walls identical at every value. Found while checking the sweeps: the decals used one running random id, so the number of damaged fronts reseeded every stain after them (the edge-damage-0 frame had a different end wall). Each section now has its own id range |
| FBX re-import | triangles identical (393,624 / 99,726 / 574); meshes `danchi` + `danchi_decals`, `danchi_LOD1` + `danchi_LOD1_decals`, `danchi_LOD2`; 16 / 14 / 3 material slots; vertex Cd and Alpha (decal alpha 0.06–0.9) and UVs present; 6 `UCX_danchi_00..05` hulls |
| Chip halo and grime on damaged fronts | the bake lifted the vertex colour toward the substrate over each hotspot's halo field (up to ~1.3 m) and the boolean interpolated the slab-edge grime away, so at 10 m the soot around chips faded as damage rose, with light wedges along long triangles. Now the worn substrate is a decal blotch per spall and `eg_vN` copies the grime from the clean front. Area-weighted vertex colour (outer face) of damaged fronts 0.446 vs clean 0.462: slightly darker, with the light substrate now only in the decal around each chip (before: 0.463 / 0.462 on average, but faded locally around the chips) |
| Fresh instance from the library | cooks with 0 errors; materials bind inside the instance; Texture Folder resolves to `examples/danchi/tex` |
| frame_critique, all 42 showcase images (`--view close --ref bay_*` for the bay camera, `--view wide --ref facade_* end_*` for the others; `showcase/critique.json`) | **0 fails.** The 9 bay-camera images pass every test (surface L* 71–92, reference_match EMD L* 6.6–9.0). The 33 facade/sweep images warn only on `reference_match`: EMD L* 15.3–17.1 against a warn line of 13 (fail 19.1, the largest spread between the photos themselves). About half of each wide frame is flat sky (sky share 0.45–0.56) and the ground is plain, with none of the dark trees, cars and neighbouring blocks the photos have, so frame contrast is 0.52–0.65 of the photos'; the colour histogram passes (EMD C* 6.6–7.0, warn 10) and surface L* is 65–88 |

### How much weathering does a wall carry? (`src/py/weather_load.py`)

My own check, on the same kind of view in renders and photos: a plain stretch of end wall
(gable) seen from 30–60 m, cropped by hand in 6 ordinary photos (`end_01/02/03/05/06`,
`weathering_02`'s plain end) and 2 heavily stained ones (`weathering_02`'s stained wall,
`weathering_01`'s raw concrete), and projected through the camera on the west end wall in the
facade-camera renders (`toNDC`). The light gradient is removed by a plane fit, the crop is
resampled to 160 px high, then: **soil** = P95 − P50 of L*, **mottle** = s.d. of L*, **dark** =
share more than 8 L* below P95, **vstreak** = mean |∂L/∂x| / mean |∂L/∂y|.

| Wall | L* mean | soil | mottle | dark share | vstreak |
|---|---:|---:|---:|---:|---:|
| photo: end_01_akabanedai_34_end | 55.1 | 3.01 | 2.37 | 0.02 | 0.89 |
| photo: end_02_soshigaya_22_end | 75.1 | 2.72 | 1.77 | 0.0 | 1.4 |
| photo: end_03_nagasawa_2-2_end | 67.8 | 1.04 | 2.71 | 0.024 | 0.91 |
| photo: end_05_naruko_end_b | 82.7 | 1.44 | 0.9 | 0.0 | 0.97 |
| photo: end_06_kita_ward_end | 67.4 | 1.48 | 2.01 | 0.021 | 0.6 |
| photo: weathering_02_saginomiya_stained_end | 67.5 | 2.32 | 3.31 | 0.021 | 1.2 |
| photo: weathering_02_saginomiya_stained_end#stained | 63.4 | 14.29 | 9.63 | 0.686 | 1.13 |
| photo: weathering_01_ogikubo_stained_facade | 56.6 | 11.82 | 8.74 | 0.694 | 1.32 |
| render: New | 86.8 | 1.08 | 0.65 | 0.0 | 1.62 |
| render: Well kept | 79.1 | 1.34 | 1.11 | 0.0 | 2.6 |
| render: Typical | 71.1 | 1.73 | 2.4 | 0.054 | 3.7 |
| render: Neglected | 62.9 | 1.86 | 3.33 | 0.086 | 4.01 |
| render: age 10, upkeep 0.9 | 80.4 | 1.28 | 0.95 | 0.0 | 2.33 |
| render: age 10, upkeep 0.5 | 77.0 | 1.45 | 1.44 | 0.001 | 3.02 |
| render: age 10, upkeep 0.1 | 73.8 | 1.54 | 1.92 | 0.024 | 3.43 |
| render: age 35, upkeep 0.9 | 77.8 | 1.38 | 1.32 | 0.0 | 2.79 |
| render: age 35, upkeep 0.5 | 71.1 | 1.72 | 2.39 | 0.053 | 3.61 |
| render: age 35, upkeep 0.1 | 63.3 | 1.92 | 3.32 | 0.088 | 4.03 |
| render: age 60, upkeep 0.9 | 75.9 | 1.38 | 1.57 | 0.006 | 3.1 |
| render: age 60, upkeep 0.5 | 69.1 | 1.91 | 2.7 | 0.066 | 3.86 |
| render: age 60, upkeep 0.1 | 61.6 | 1.73 | 3.29 | 0.081 | 3.65 |
| **photos, min / median / max** | | 1.04 / 2.52 / 14.29 | 0.9 / 2.54 / 9.63 | 0.0 / 0.02 / 0.694 | 0.6 / 1.05 / 1.4 |

Reading (the crops are in `showcase/checks/weather_load_crops.jpg`):
- **The presets rank in the right order and land where intended on mottle.** New carries less
  than any photo (0.65 against 0.9–3.3 L*). Well kept sits at the clean end (1.11), Typical
  at the median of the ordinary photo end walls (2.40 against 2.54), and Neglected at the
  heavy end of the ordinary walls (3.33 against 3.31). The Age × Upkeep grid rises along
  both axes (age 10: 0.95 / 1.44 / 1.92; age 35: 1.32 / 2.39 / 3.32; age 60: 1.57 / 2.70 /
  3.29), saturating at low upkeep.
- **Soil (P95 − P50) is low.** Typical 1.73 and Neglected 1.86 are inside the photo range
  (1.04–3.01) but below its median (2.52). The rendered wall greys as a whole (mean L* 87 → 63
  from New to Neglected) instead of sinking its typical patch below its cleanest paint.
- **Dark share is too high for Typical and Neglected** (0.05 and 0.09 against 0–0.024 on
  ordinary photo walls). The stain fields put their dark in a few concentrated washes, where
  the photos spread it thinly. They are still far from the stained walls (0.69).
- **Too vertical** (vstreak 1.6–4.0 against 0.6–1.4): see Limits.
- Caveats: six ordinary photos and two stained ones; the photo crops include the faint
  panel joints of PC walls, and the photos have their own exposure and haze. Read the
  numbers as a ranking against the photos, not as a match. By eye at 40 m, Typical reads as an
  aged, repainted-once block, and Neglected as an unkept one, not as raw-concrete decay.

## Limits and what an artist should still do

- **Neglected stops short of the worst photos.** By my own check its end wall carries about a
  third of the mottle of the two heavily stained reference walls (raw concrete and a
  decades-unpainted stair wall). Auto Intensity up to 2, or the overrides, go further; the
  presets were left where a 45-year-old *painted* block sits.
- **End walls are more vertically structured than the photos** (vertical-streak index 1.6–4
  against 0.6–1.4): the rain-wash columns in the vertex soot and the long runs read as
  stripes where real end walls mottle more evenly. A softer, less columnar soot field on gables
  would be the next step.
- **Streak shapes repeat across a facade** at close range: 16 streak cells, flipped and scaled.
  More atlas variants (or a second atlas) would help hero views.
- **Decals are geometry.** ~5,200 quads in LOD0 (10k triangles) and up to six layers stacked
  on a parapet; in an engine use mesh decals (Unreal) or a no-depth-write transparent pass
  (Godot) and expect some overdraw at Neglected.
- **LOD1 sits just under its 100k budget** (99,726 at Typical, 99,946 at age 60 / upkeep 0.1)
  because the large decals it keeps grow with weathering. A larger building or a lower budget
  needs a cap on LOD1 decals (raise the 1.5 m² area threshold in `decals.vfl`, `dlod`).
- **Vertex-colour resolution**: soot gradients live on the piece and grid vertices (bays,
  1 m gable columns, floor lines); finer stains are decals. A baked per-facade mask texture
  would give smoother gradients at the cost of a texture per building variant.
- **Repaint patches** change tone and cleanliness only; no sheen change in the engine material
  (roughness is constant per material).
- **Showcase lighting** is a preview: Karma XPU, sun and sky dome. The engine look depends on
  its own light, exposure and colour pipeline (see the colour-space note).
- From round 6, still true: interiors are cards; LOD0 FBX is unpacked (79 MB), an engine build
  should instance the kit pieces; only the corridor type exists (a stair-hall walk-up type would
  cover most 4–6F blocks); trees and poles in the evidence scene are simple. Lot shapes and new
  building types are the next round.
