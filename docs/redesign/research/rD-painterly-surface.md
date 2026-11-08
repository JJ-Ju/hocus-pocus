# Round D: painterly surface treatments that ship to an engine

Two optional style layers over the realistic danchi materials. Realistic stays the default.

- **Task 1: a mild brush-stroke layer** for the anime-background profile. It is meant to be
  used with the 0.4 post or without it.
- **Task 2: a "hyper-real painterly" layer** after the concept artist Ruan Jia (阮佳).

Both live in surface space, so they hold under camera moves. Round C's screen-space post swam
under camera moves. A mid-round constraint from the user also applies: the looks are destined
for Unreal or Godot, so nothing may depend on a render pass, AOV compositing or Karma-only
shading. Section 5 says for every effect whether it is baked, needs a vertex attribute or needs
a runtime shader, and gives the Unreal and Godot recipes.

Tags:
- **[S]** a source states it;
- **[S/P]** the artist said it (interview, often translated);
- **[S/2]** secondary (forum, blog, or a search snippet only);
- **[I]** inference or my own observation of images;
- **[D]** measured in round D on the danchi v005 renders.

Scripts are in the session scratchpad under `roundD/` (paths at the end). Every Houdini node and
parm name below was read or run in Houdini 22.0.466.

## 1. Test set-up

- **Scene.** `sk3-out/work/danchi_v005.hiplc` is the hip round C rendered: its husk log names
  the mplay session `danchi_v005`. It was loaded read-only and never saved; the style edits are
  in memory only.
- **Cameras and render.** `cam_hero` and `cam_facade`, Karma CPU, 32 spp, 1280 × 720, with
  beauty, albedo, depth and N AOVs. The renders take 2.5–4.5 min per camera.
- **AOV use.** The AOVs are used only for measuring and for round C's post. The looks
  themselves need none of them.
- **Materials styled.** `conc`, `conc_raw`, `roof` and `steel` in `/obj/danchi/gen/materials`
  and `/obj/estate/b0..b2/materials`, 16 builders in all. Glass, fabric, plants and the rest
  are unchanged.

## 2. Task 1: mild brush-stroke layer

### 2.1 Texture (Copernicus, `build_brush_tex.py strokes`)

- **Tile.** 2048², wrap border, 4 m: about 2 mm per texel. It tiles with a seam difference of
  0.015 against 0.026 between neighbouring pixels [D].
- **Stamp.** A rounded bar (`sdfshape` rect 0.42 × 1.80, roundness 0.35) → `sdftomono` →
  `blur` 110 px for a soft core.
- **Dry edges.** Bristle noise (`fractalnoise`, element 0.9, per-component scale 0.035 × 1) is
  added to the soft core, minus a dryness ramp toward the trailing end, then thresholded 0.36–0.46.
  The sides and the tail break into bristle streaks; the core stays flat.
- **Scatter.** `shapescatter`:
  - 40 × 21 hex grid with jitter 0.95;
  - scale 0.147 in image units: strokes 0.3–0.8 m long and 0.07–0.16 m wide;
  - scale variance 0.35 and angle variance ±5°;
  - depth-sorted over, so strokes paint over each other: 98.6 % coverage [D].
- **Per-stroke values.** `randommono` seeded by the scatter's `id` output, one each for value,
  hue and saturation offsets (−1..1), flat inside each stroke.
- **Height.** Coverage × bristle ridges. The ridges are sampled through the scatter's per-stamp
  `uv` output (`sample`), so they follow each stroke rather than the image.
- **Outputs.** `brush_strokes.exr`, float RGBA: R value, G hue, B saturation offset, A height.
  `brush_strokes_engine.png` is the same in 8-bit linear, RGB = 0.5 + 0.5 × offset.

### 2.2 Material (`apply_painterly.py t1`)

- **Projection in world space.** The dominant normal axis picks the plane:
  - X-facing walls use (z, y);
  - Z-facing walls use (x, y);
  - floors and roofs use (x, z).

  Texture V is the stroke direction, so strokes run vertical on walls.
- **Direction attribute.** A primitive attribute `sdir` = 1 on `slab_edge`, `parapet_bal`,
  `parapet_cor`, `plinth` and `coping` swaps U and V, so strokes run along the slab.
  - A diagnostic render by part showed that the long horizontal bands of this facade are
    `parapet_bal` with a thin `slab_edge`.
  - The recessed `wall_bal` back walls, columns and end walls get vertical strokes.
- **Colour.** Base colour → `mtlxrgbtohsv` → value × (1 ± 0.03), hue ± 4°, saturation × (1 ± 0.05)
  → `mtlxhsvtorgb`.
  - A temperature tilt (R × (1 + 0.010 g), B × (1 − 0.010 g)) makes the per-stroke hue offset
    visible on near-grey concrete: a ±4° HSV rotation does almost nothing at saturation 0.1.
- **Relief and sheen.** A faint relief (`mtlxbump`, 1.5 mm × height, chained after the
  material's stipple bump) and roughness − 0.04 × (height − 0.8). Paint bodies are a touch
  smoother, so strokes catch light slightly.

### 2.3 What it measures [D]

Albedo AOV, styled against the realistic render, same camera, geometry pixels:

| | hero | facade | brief |
|---|---|---|---|
| per-pixel value ratio, std | 1.5 % | 1.4 % | |
| value ratio p5–p95 | 0.980–1.019 | 0.980–1.019 | ±2–4 % |
| ΔL\* std | 0.41 | 0.41 | |
| Lab hue change, p5–p95 (C\* ≥ 4) | −1.2° … +1.1° | −1.6° … +1.4° | ±2–5° |
| Δa\* / Δb\* std | 0.13 / 0.32 | 0.15 / 0.35 | |

- **Hue lands below the brief.** The perceptual hue change is about a third of the HSV setting.
  The surfaces are near grey, and strokes under 2 px average within a pixel at these distances.
  The `t1_x2` variant (±6 % value, ±8° hue, ±10 % saturation) is in the picker to set the
  amplitude by eye.
- **Beauty statistics barely move.** Shadow b\* (+3.4 → +3.4), L\* p1 and the dark and light
  chroma are unchanged. The layer changes texture, not the colour key: it reads as a painted
  surface, not a filter.

## 3. Ruan Jia: what the sources and the pictures say

The research pass found two statements in his own words. Everything else is secondary.
ArtStation, Zhihu and Muddy Colors returned 403 to the fetch tool. I then viewed five of his
ArtStation works in a browser, at pane size only, and describe them below. No artwork was
downloaded, stored or reproduced.

### 3.1 Sourced statements

- **[S/P] Saturated, lifted darks: his signature.** Around 2007, after two to three years of
  experiments, he began adding high-saturation colour to areas that should go fully dark. That
  gives a "whole-image self-glow" (全范围自体发光). Jiemian / 游戏葡萄 interview, 2015-06-03, my
  translation.
- **[S/P] "Every area uses varied colours forming a colour wheel"** (每个地方都用缤纷的色彩形成一个
  色轮). He lifts places that should be fully dark with very saturated colour. ZCOOL interview,
  about 2016, my translation. This is the closest sourced basis for "colour drifting": hue keeps
  rotating inside one region instead of holding one shadow hue.
- **[S/P] Process.** He renders in black and white first, then colours. With more time he renders
  deeper, and detail comes last (ZCOOL; also qingwk). He uses Photoshop with the Massive Black
  brushes and a few defaults, and has no fixed palette. He likes complementary pairs, green with
  red and blue with orange (CG Cookie Q&A, via a 2014 Russian translation on shazoo.ru).
- **[S/P] Detail goes to the focus.** In one portrait he placed eyelashes pixel by pixel and
  spent a week on the eyes. He gave careful thought to the complementary colour on the nose
  wings (qingwk).
- **[S/2] Where the saturated colour sits.** A Zhihu answer, seen as a search snippet only,
  says it sits mainly in shadows. In early work it gathers at the focal point; in later
  naturally lit work it spreads more into local colour and shadow.
- **[S/2] Neutral key light (low reliability).** A 2013 /ic/ thread (snippet) argues his main
  light is near-neutral white, with many desaturated mid-tones, so the saturated accents pop.
  The same thread says core shadows are kept as bright as possible without reaching the light
  values.
- **[S/2] Muted, glazed overall.** A 2011 student blog calls his palette subdued and muted, with
  a glazed look and subtle value shifts. A Medium / GameTextures piece (snippet) says the colours
  look "matte and reflective at once".
- **[S/2] Micro-colour that merges at distance.** A YouTube comment (snippet) says close up the
  textures pack many saturated colours that merge into one colour from afar. /ic/ posters (snippet)
  credit his grain to painting large, 10–15k px, and downscaling.
- **[S/2] "Hard-grainy yet soft" edges** (an /ic/ thread title, snippet).
- **No source gives a number.** No degrees, value percentages or jitter settings appear anywhere.

### 3.2 What the pictures show [I]

Viewed on artstation.com/ruanjia at about 430 px wide.

- **Capital (city of white stone towers).**
  - The shade sides of the white stone go blue-violet to lavender grey, lifted and never dark.
  - Lit planes are near-white and slightly warm.
  - Acid yellow-green grass sits on the lit terraces, with small gold accents.
  - The distance fades to blue-lavender.
  - The stone hue swings from violet-grey high up and in the distance to green-grey near the
    vegetation: a blue → green drift across one material, over about a third of the frame.
- **Damaged temple.**
  - Pale off-white architecture with teal-cyan pockets in the recesses and dusty-rose walls.
  - The foreground rocks are dark warm grey with olive; the tree canopy is yellow-green.
  - The densest detail sits in the central architecture; the distance is a warm-grey haze.
- **Storm Plain.**
  - Near-monochrome warm-grey haze with a cool grey dragon.
  - Small, saturated red accents on the rubble.
  - Contrast concentrates on the central figures; edges are lost in the haze.
- **Lost Land (a character piece).**
  - Silver armour with dense engraved detail: brass edges, blue-green reflections in the silver,
    and red cloth accents (a red/green complement).
  - The background is dark green-black. Character pieces keep deep darks; environment pieces
    lift them.
- **A portrait thumbnail.** A cool teal-green dark background with saturated pink roses; warm
  skin turns pink-red at the shadow transitions.

### 3.3 Rules, made measurable

| # | Rule | Measure (round D) | Target | Basis |
|---|---|---|---|---|
| R1 | Darks keep a saturated colour; never grey or black | C\* of the darkest non-sky quartile ÷ C\* of the brightest | ≥ 1.0 (realistic 0.66–0.89) | [S/P] Jiemian, ZCOOL; numbers [I] |
| R2 | Darks lifted, environment pieces | L\* p1 of the frame | ≥ 12 | [S/2] /ic/; [I] Capital, temple |
| R3 | Hue rotates inside one material ("colour wheel"): a blue ↔ green drift with warm zones | hue angle p5–p95 of the albedo low-passed at 24 px | ≥ 50° spread (realistic 35–37°); features 0.2–0.5 of the object (10–20 m on a 60 m slab) | [S/P] ZCOOL; [I] Capital |
| R4 | Light and dark in contrasting hues: warm-neutral lights, cool shadows | hue of the dark quartile minus hue of the light quartile, beauty, Lab | 60–120° (realistic 30–38°); dark-quartile b\* ≤ 0 | [S/P] lifted saturated darks; [S/2] neutral key; [I] Capital |
| R5 | Complementary accents, small | share of pixels with C\* > 25 opposite the dominant hue | 2–5 % of the frame | [S/P] red/green, blue/orange; [I] Storm Plain, Lost Land |
| R6 | Multi-hue micro detail that merges at distance | std of a\* and b\* of albedo minus a 6 px blur | up ≥ 10 % on the facade, mean-neutral | [S/2] YouTube comment, /ic/; [I] |
| R7 | Detail concentrated at the focus | `frame_critique` detail_density (area holding 80 % of detail energy) | ≤ 0.40 | [S/P] detail last, at the focus; [I] temple |
| R8 | Value structure first: colour shifts must not move values | ΔL\* std of the albedo from the hue layers | ≤ 1 L\* | [S/P] greyscale first |
| R9 | Soft but grainy terminators; hard edges only at accents | not measured | — | [S/2] /ic/ |

## 4. Task 2: "hyper-real painterly" in the material (`apply_painterly.py t2`)

Every low-frequency field is a vertex attribute written by one SOP wrangle (`pd_t2attrs`, run over
vertices, world space). The material only reads them. This is what makes it portable (section 5).

- **Hue drift, R3.** Two world-space fBm fields drive it.
  - n1 at 0.085 /m (about 12 m) mixes blue (0.93, 0.995, 1.09) into green (0.94, 1.035, 0.975).
  - n2 at 0.045 /m (about 20 m) switches in warm zones (1.07, 1.0, 0.90).
  - The multipliers are luminance-neutral, so values stay put (R8): `pd_tint`.
- **Light/dark hue contrast, R1, R2, R4.**
  - **Lifted, saturated darks.** Emission = albedo luminance × a saturated lift colour × 0.04/0.5.
    The colour drifts violet ↔ blue ↔ teal on a third field n3, and soffits (N.y < −0.3) get
    × 1.6 (`pd_liftc`, `pd_lift`). Sunlit walls gain about 5 % from it, sky-lit shadow about
    25 % and occlusion about 75 % [I]. Light, shadow and occlusion therefore separate in hue
    without any lighting-aware shader, through the standard emissive input.
  - **Warm sun-facing faces.** × (1.035, 1.0, 0.955) on faces whose N·L to the sun exceeds 0.
    This is baked for the hip's fixed sun into `pd_tint`; a runtime alternative is given in
    section 5.
  - **Optional key and fill colours.** Warm key (1.0, 0.82, 0.60) and a cold, saturated fill
    (0.50, 0.68, 1.0) × 1.25 (`--keyfill`). This is the engine-native form of the dusk key the
    user picked in round C ("warm light against cold blue shadows").
- **High-frequency painterly detail, R6, R7.** The `detail` texture: 1.5 m tile, two stroke layers
  (0.15 m and 0.06 m strokes, ±9° and ±14° angle jitter).
  - In albedo: value ± 6 %, hue ± 12°, saturation ± 15 % and a temperature tilt ± 3 %.
  - Relief 2 mm and roughness − 0.06 × (height − 0.8).
  - All of it is scaled by `pd_famp`: 1 within 8 m of a focal point at (5, 9, 6), falling to
    0.45 at 32 m and beyond.

### 4.1 What it measures [D]

Beauty, Lab, non-sky geometry pixels. Darkest and brightest quartiles of L\*.

| Frame | dark C\* | light C\* | R1 ratio | dark hue | light hue | R4 split | dark b\* | L\* p1 |
|---|---|---|---|---|---|---|---|---|
| hero, realistic | 6.43 | 7.20 | 0.89 | 134° | 96° | 38° | +3.97 | 6.4 |
| hero, t2 | 7.89 | 8.29 | 0.95 | 167° | 99° | 68° | +0.83 | 6.8 |
| hero, t2 without drift | 7.93 | 5.34 | 1.49 | 169° | 97° | 72° | +0.67 | 6.8 |
| facade, realistic | 5.14 | 7.80 | 0.66 | 126° | 96° | 30° | +3.44 | 8.7 |
| facade, t2 | 6.72 | 7.72 | 0.87 | 197° | 103° | 94° | −0.88 | 9.3 |
| facade, t2 without drift | 6.74 | 6.04 | 1.12 | 201° | 97° | 104° | −1.00 | 9.2 |

Albedo, against the realistic albedo:

| Frame | low-passed hue p5–p95 around its mean | Lab hue change p5–p95 | HF a\*/b\* std (base → t2) | value ratio std |
|---|---|---|---|---|
| hero | 37° (−13 … +24) → **62°** (−27 … +34) | −12° … +29° | 0.77 / 1.20 → 0.82 / 1.36 | 1.6 % |
| facade | 35° (−9 … +26) → **40°** (−22 … +18) | −9° … +26° | 0.66 / 1.14 → 0.69 / 1.28 | 1.5 % |

Reading the tables:
- **Lift without drift meets R1; with the drift it does not.** Without drift, the lift alone
  gives R1 ≥ 1. With the drift, R1 falls back to 0.87–0.95, because the drift and the sun warmth
  add chroma to the lights as well. R1 holds only if the light-side multipliers stay closer to
  neutral. `t2_strong` raises the lift to 0.07.
- **R4 is met** (68–104° against 30–38°), and the dark-quartile b\* turns from yellow to neutral
  or blue.
- **R2 is not met.** L\* p1 stays at 6.8–9.3. The deepest darks here are window glass and
  interiors, which round D does not style; a scene-wide rule needs those materials, or the key
  and fill.
- **R3 is met on the hero (62°) but weak on the facade (40°).** The facade frame mostly holds one
  drift cell. A higher drift frequency, or the strong variant, widens it.
- **R6 moves only slightly**: high-frequency a\* + 5–6 %, b\* + 12–13 %. The 6 cm and 15 cm detail strokes are 1–4 px
  at these distances. The `t2_strong` and `t2_nodetail` pairs show whether the detail reads at all.

`frame_critique.py` results for every picker image are in section 7.

## 5. Shipping to an engine

### 5.1 What each effect needs

| Effect | How it ships | Kind | Data |
|---|---|---|---|
| T1 stroke texture | tiling texture | **baked** (texture) | `brush_strokes_engine.png`, 8-bit linear RGBA |
| T1 world-space projection | runtime world-aligned lookup (tiling kits), or baked into a unique piece's UVs (`bake_piece.py`) | **runtime shader** or **baked** | — |
| T1 stroke direction | per-face flag | **vertex attribute** | COLOR.a = `sdir` |
| T1 and T2 per-stroke HSV maths | material maths | **runtime shader** (cheap ALU), or **baked** into albedo | — |
| T1 and T2 relief and roughness | normal and roughness maps | **baked** (piece), or the runtime tile | `piece_*_normal.png` (16-bit, OpenGL +Y), ORM G |
| T2 hue drift × sun warmth | low-frequency multiplier | **vertex attribute** | COLOR.rgb = 0.5 + (tint − 1) × 2.5 |
| T2 lifted saturated darks | emissive = colour × luminance(albedo) × k | standard **emissive** input; colour from a **vertex attribute**; soffit boost from the normal at runtime | UV2.y = `pd_liftn` |
| T2 detail amplitude (focus) | scalar | **vertex attribute** | UV2.x = `pd_famp` |
| T2 detail texture | tiling texture | **baked** (texture) | `brush_detail_engine.png` |
| Key / fill colours (the "dusk" pick) | light colours | engine lights | directional light colour; skylight or ambient tint |
| True light-dependent hue (warm where lit, cool in cast shadow) | custom lighting | **runtime shader**: Godot `light()`; Unreal needs a workaround (below) | — |
| Distance haze (the user picked stronger haze) | fog | engine fog | Unreal Exponential Height Fog; Godot Environment fog |
| Round C post (bands, painted sky, lines) | — | **does not ship** | screen-space; offline renders only |

The base material's procedural weathering (grime, streaks, rust from primvars) is outside round D.
It is not in the baked set below; see section 8.

### 5.2 Baked golden piece (`bake_piece.py`)

- **Piece.** One balcony bay, floor 3, bay 5: back wall `wall_bal` (38 prims), `slab_edge`
  (18) and a `parapet_bal` strip (2), clipped to the bay's 6 m width. 58 prims, 24.8 m². The
  y filter caught only the parapet's top strip, not its full face; widen it for a full bay.
- **Unwrap.** `uvflatten::3.0` → `uvlayout::3.0` covers 69 % of UV space, at 5.99 m per UV unit:
  2.9 mm texels at 2048².
- **Projection.** A per-vertex `puv` attribute reproduces the shader's world projection, so
  the bake and the runtime agree.
- **Bake.** `rasterizesetup` (space uv) → `rasterizegeo` of `bcd` (prim Cd), `pd_tint`,
  `pd_liftc`, `pd_lift`, `pd_famp`, `puv` and alpha. Then:
  - `function` modulus wraps `puv`, and `sample` reads the stroke texture (one channel at a time,
    see the traps);
  - the same HSV maths as the material, with the `hsv` COP's hue in 0–1;
  - emissive = lift colour × luminance × k;
  - `heighttonormal` at scale = relief ÷ (5.99 m ÷ 2);
  - ORM = (1, roughness, 0);
  - `extrapolateboundaries` pads the islands through `fillarea`.
- **Files.** `piece_t2_albedo.png` (sRGB 8-bit), `piece_t2_normal.png` (raw 16-bit),
  `piece_t2_orm.png` (raw 8-bit), `piece_t2_emissive.png` (sRGB 8-bit) and `piece_t2_mask.png`;
  the same for t1, without emissive.
- **Re-import check.**
  - **Files read back correctly.** OIIO reads them back as 2048², uint8 or uint16. A flat
    normal reads (0.5, 0.5, 1.0) and 100 % of normals have z > 0.95.
  - **Plain material.** It is built from the PNGs only: `mtlximage` → `mtlxstandard_surface`
    `base_color`, `mtlxnormalmap` → `normal`, ORM.g → `specular_roughness`, emissive →
    `emission_color`. It renders like the procedural piece on the same camera.
  - **Albedo AOV difference.** ΔE76 mean 1.61, p50 1.50, p95 3.52, for both t1 and t2. Mean
    L\*a\*b\* is (84.9, −0.8, 8.5) procedural against (84.5, −0.9, 8.2) baked. What remains is
    mostly the unbaked weathering of the base graph.

### 5.3 Vertex data through glTF (`export_engine.py`)

- **Export.** The piece is packed into COLOR_0 (tint delta, sdir) and TEXCOORD_1 (famp, liftn).
  A `/out/gltf` ROP writes it (`usesoppath`, `exportmaterials` 0), giving a 10 kB `.glb`.
- **Re-import.** `gltf::2.0` SOP, then `unpack`.
- **Result.** The 0/5/50/95/100 percentiles of `Cd`, `Alpha`, `uv` and `uv2` match to 4 decimals.
  `sdir` survives as 0/1, and the tint delta spans 0.33–0.72, inside 0–1. glTF re-imports them as
  point attributes, with vertices split at seams.
- **8-bit engines.** The tint is stored as a delta because 8-bit vertex colour (Unreal
  `FColor`) clamps at 1, and the raw tint reaches 1.09.

### 5.4 Godot 4

`roundD/engine/danchi_painterly.gdshader` is a full spatial shader. It was written from the
MaterialX graph and **has not been run in Godot**.

- **Inputs.** COLOR (tint delta, sdir), UV2 (famp, liftn), and the two stroke textures, imported
  as plain linear data with repeat on.
- **World projection.** In `vertex()`, `wpos = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz` and
  `wnrm = mat3(MODEL_MATRIX) * NORMAL`. `surface_uv()` follows the dominant axis and swaps by
  sdir, the same as the MaterialX graph.
- **Colour maths.** `rgb2hsv` and `hsv2rgb` in GLSL; `stroke_mod()` applies value, hue,
  saturation and the temperature tilt.
- **T2.** `ALBEDO *= 1 + (COLOR.rgb − 0.5) × 0.4`. The lift colour is mixed from three uniforms
  by UV2.y, and the soffit boost comes from `wnrm.y`, giving
  `EMISSION = colour × luminance × k`.
- **True light/shadow hue split.** A commented-out `light()` adds it:
  `DIFFUSE_LIGHT += ndl·ATTENUATION·LIGHT_COLOR/π · mix(shadow_cool, key_warm, …)`.
  `ATTENUATION` includes the shadow map, so cast shadows turn cool too. `light()` replaces the
  built-in lighting, so `SPECULAR_LIGHT` has to be written as well.

### 5.5 Unreal Engine 5: node recipe, not built

This recipe was not built or tested in Unreal.

- **Units and axes.** Unreal is Z-up and in centimetres.
  - Use AbsoluteWorldPosition ÷ 100.
  - The wall planes are (Y, Z) for X-facing walls and (X, Z) for Y-facing walls; floors use (X, Y).
  - Import the glTF or FBX with Z-up conversion.
- **Projection.**
  1. VertexNormalWS → Abs → ComponentMask, then two `If` nodes pick the plane as in
     `surface_uv`.
  2. VertexColor.A > 0.5 → swap through a `Lerp` of the two orders.
  3. Divide by 400 cm (strokes) or 150 cm (detail) → TextureSample of `T_Strokes`, with
     Sampler Type Linear Color, sRGB off, Masks compression, wrap.
  4. Offsets = RGB × 2 − 1.
- **HSV.** Use a Custom node with the same HLSL `rgb2hsv` / `hsv2rgb` as the Godot shader.
  The engine's `HueShift` material function also works for hue alone.
  - hue += G × 4/360, saturation × (1 + B × 0.05), value × (1 + R × 0.03).
  - Then multiply by (1 + t, 1, 1 − t), with t = G × 0.01.
- **T2.**
  - BaseColor × (1 + (VertexColor.RGB − 0.5) × 0.4).
  - TexCoord[1].x scales the detail offsets.
  - Emissive Color = Lerp(Lerp(cool, teal, SmoothStep(0.5, 0.85, TexCoord[1].y)), violet,
    1 − SmoothStep(0.1, 0.35, TexCoord[1].y)) × Luminance(BaseColor) × 0.08 ×
    Lerp(1, 1.6, SmoothStep(0.3, 0.8, −VertexNormalWS.z)).
  - With Lumen, emissive also contributes to GI slightly; lower k if shadows go too blue.
- **Relief.** On baked pieces, use the baked normal map. Unreal expects DirectX green, so tick
  *Flip Green Channel* on import of `piece_*_normal.png`.
- **Light-dependent hue.** The default lit model has no custom lighting.
  - Keep the vertex-baked sun warmth.
  - Or set a Material Parameter Collection vector to the directional light's direction from
    Blueprint, and lerp the tint by dot(VertexNormalWS, L). This misses cast shadows.
  - The light colours (warm key, cold sky light) carry the rest, including cast shadows.
- **Haze.** Exponential Height Fog: start about 40 m, full about 650 m, max opacity 0.7,
  inscattering toward the haze colour. This is the engine version of the stronger haze pick.

## 6. Picker images

Folder: `scratchpad/roundD/picker/`. Each pair is `pNN_<cam>_A_<name>.jpg` and
`pNN_<cam>_B_<name>.jpg` for `hero` and `facade`. The images are uncaptioned, 1280 × 720 and
under 400 kB. `pairs.json` lists the pairs and the one variable in each.

| Pair | A | B | The one variable |
|---|---|---|---|
| p01 | base | t1 | task 1 brush layer off / on |
| p02 | t1 | t1_x2 | task 1 amplitude ×1 / ×2 (value 3 → 6 %, hue 4 → 8°, saturation 5 → 10 %, relief 1.5 → 3 mm) |
| p03 | base_post | t1_post | brush layer off / on, both under round C's post (dusk, strength 0.4, haze 0.70) |
| p04 | t1 | t1_post | round C's post off / on, over task 1 (offline only) |
| p05 | t1 | t1_keyfill | light colours: neutral / warm key with a cold blue fill (the engine-native "dusk"), task 1 |
| p06 | base | t2 | task 2 off / on |
| p07 | t2_nodrift | t2 | hue-drift field off / on |
| p08 | t2_nolift | t2 | lifted saturated darks off / on |
| p09 | t2_nodetail | t2 | high-frequency multi-hue detail off / on |
| p10 | t2 | t2_strong | task 2 default / strong: lift 0.04 → 0.07, detail value 6 → 10 %, hue 12 → 20°, saturation 15 → 25 %, focus floor 0.45 → 0.7, drift × 1.5 |
| p11 | t2 | t2_keyfill | light colours: neutral / warm key with a cold fill, task 2 |
| p12 | t1 | t2 | style: anime brush layer / hyper-real painterly |
| p13 | piece_t2_procedural | piece_t2_plain | golden piece: procedural MaterialX / re-imported baked textures (task 2) |
| p14 | piece_t1_procedural | piece_t1_plain | the same for task 1 |
| p01z, p02z | | | 2× crops of p01 and p02 at the near parapets (hero) |
| p06z, p09z | | | 2× crops of p06 and p09 (facade) |

Notes on the pairs:
- **Key and fill change the visible sky.** In `--keyfill` the fill is the dome light, which
  the camera sees, so the sky turns blue as well. An engine's sky is separate from its ambient
  light.
- **Variant measurements [D].**
  - t1_x2: value ratio std 2.3 %, Lab hue p5–p95 −3.3 … +2.7°. That is inside the brief's
    ±2–5°, where t1 at ±1.2–1.6° was not.
  - t2_strong: dark C\* 7.5–8.7, a 69–77° hue split, and a low-passed hue spread of 54° on the
    facade and 101° on the hero. Value ratio std 2.2 %.
  - t2_keyfill: dark-quartile hue 212–238° against light 82–84°, a split of 130–153°. Dark b\*
    is −1.7 / −3.2 and light C\* 11.6–11.9. It is the strongest R4 lever, and it is native to
    every engine.
  - t2_nolift: the dark-quartile hue stays at 128–132° and b\* at +3.6 / +4.3, as in the
    realistic render. The lift alone makes the hue split.
  - t2_nodetail: R6 drops back only from 1.28 to 1.24 b\* std. The detail barely registers at
    these distances.

## 7. frame_critique results

`frame_critique.py` was run unchanged, with Python 3.13 and Pillow (no scipy), on every frame in
both profiles. The JSON files are in `roundD/crit/full` and `roundD/crit/post`. Below, the
painterly profile: status and value, with the `painted_key` metrics (shadow b\*, L\* p1,
3-peak share).

| Frame | value_grouping | painted_key: shadow b\* / L\* p1 / peaks | micro (mean local std) | saturation_budget | detail_density |
|---|---|---|---|---|---|
| base hero | pass 2.57 | warn: +3.8 / 6.9 / 0.48 | 8.7 | pass 0.83 | warn 0.43 |
| t1 hero | pass 2.58 | warn: +3.8 / 6.9 / 0.48 | 7.5 | pass 0.83 | warn 0.43 |
| t1_x2 hero | pass 2.59 | warn: +3.8 / 6.9 / 0.48 | 8.6 | pass 0.84 | warn 0.43 |
| t1_keyfill hero | pass 2.79 | warn: +1.0 / 6.0 / 0.49 | 8.3 | pass 0.51 | warn 0.43 |
| base_post hero | pass 2.22 | warn: −5.6 / 13.7 / 0.47 | 3.5 | pass 0.90 | warn 0.45 |
| t1_post hero | pass 2.30 | warn: −5.6 / 13.7 / 0.47 | 6.9 | pass 0.66 | warn 0.45 |
| t2 hero | pass 2.56 | warn: +0.1 / 7.3 / 0.43 | 8.0 | pass 1.19 | warn 0.43 |
| t2_nodrift hero | pass 2.60 | warn: −0.1 / 7.3 / 0.43 | 7.8 | pass 0.65 | warn 0.43 |
| t2_nolift hero | pass 2.57 | warn: +4.1 / 7.0 / 0.48 | 8.9 | pass 1.20 | warn 0.43 |
| t2_nodetail hero | pass 2.56 | warn: +0.1 / 7.3 / 0.56 | 8.0 | pass 1.23 | warn 0.43 |
| t2_strong hero | pass 2.49 | warn: −0.4 / 7.5 / 0.45 | 7.6 | pass 1.09 | warn 0.43 |
| t2_keyfill hero | pass 2.74 | warn: −2.4 / 6.3 / 0.46 | 7.5 | pass 0.56 | warn 0.43 |
| base facade | info 1.14 | warn: +3.8 / 9.0 / 0.50 | 9.7 | pass 0.91 | fail 0.63 |
| t1 facade | info 1.14 | warn: +3.8 / 9.0 / 0.50 | 9.7 | pass 0.90 | fail 0.63 |
| t2 facade | info 1.11 | warn: −0.6 / 9.7 / 0.58 | 8.9 | pass 1.14 | fail 0.63 |
| t2_strong facade | info 1.30 | warn: −0.5 / 9.8 / 0.58 | 8.5 | pass 0.99 | fail 0.63 |
| t2_keyfill facade | info 1.15 | warn: −2.7 / 8.3 / 0.60 | 8.6 | pass 0.60 | fail 0.63 |
| t1_post facade | info 1.10 | warn: −5.2 / 14.8 / 0.56 | 7.8 | pass 0.68 | fail 0.64 |

Reading the table:
- **Value grouping.** Neither layer harms it (2.49–2.79 on the hero), unlike round C's painted
  sky, which dropped it to 1.07.
- **painted_key.** No surface layer passes it. Only the post reaches cool shadows and a lifted
  black, both with a 3-peak share under 0.58.
  - t2_keyfill comes closest without post: shadow b\* −2.4 / −2.7, which passes the ≤ −2 rule.
  - The black floor (L\* p1 ≥ 12) stays out of reach while glass and interiors are unstyled.
- **micro_uniformity.** The mean local std of 7.5–9.7 is still "photographic grain on a
  painted look" (warn above 7.0). The strokes add structure but do not remove the base
  material's grain. Round C's flattening switch (micro ×0.3) is still needed for a
  painted-flat read.
- **detail_density on the facade.** It fails (0.63) for every variant. That is the
  composition: the facade cam is a full-frame elevation. It is not a material result.
- **The hero detail value is identical across variants** (0.427 for all but the post): the
  layers do not change where detail sits.

## 8. Not verified, and gaps

- **Not run in either engine.** The Godot shader and the Unreal recipe were written from the
  MaterialX graphs. Open questions:
  - whether Godot's glTF importer and shaders treat COLOR as linear data;
  - Unreal's Z-up axis mapping for the projection;
  - the green-channel flip on normal import;
  - Lumen's response to the emissive lift.
- **FBX was not tried.** Only glTF was exported and re-imported, and only in Houdini.
- **The bake covers the base colour plus the round D layer, not the weathering.** The base
  MaterialX graph's procedural weathering (grime, streaks, rust, from primvars and
  `mtlxfractal3d`) is not baked. That is where the residual ΔE of 1.6 between the procedural and
  the plain piece comes from. A full engine path needs that layer baked too, or rebuilt from
  vertex data the way the round D fields are.
- **The world-projected relief is not in the engine shaders.** At runtime the stroke height has
  no normal yet; it needs a world-to-tangent transform. Only the baked piece carries a stroke
  normal map.
- **Vertex-colour resolution.** The parapet and slab-edge prims are up to 6 m long. The drift
  field has 12 m features, so on those faces vertex interpolation is coarse. Subdivide long
  faces at export (about 2 m), or move the drift to a second UV set and a macro texture.
- **Camera-move stability was not rendered as a sequence.** It holds by construction: every
  input is world space or a vertex attribute. Sub-pixel strokes on far blocks can shimmer, and
  should be mip-filtered in an engine; round D did not test this.
- **Ruan Jia numbers are inferred.** Every degree, ratio and spatial scale in 3.3 is mine. The
  sources give directions only. The image observations come from pane-sized views of five works.
- **R1 (shadow chroma ≥ light chroma) and R2 (L\* p1 ≥ 12) are not met with the drift on.** The
  causes are the unstyled glass and interiors and the extra chroma the drift adds to the lights.
- **Task 1 hue lands below the brief.** The Lab hue change is ±1.2–1.6° against ±2–5° asked;
  `t1_x2` is there for that call.
- **Detail density cannot be set on these cameras.** At 1280 px, most 6–15 cm detail strokes are
  1–4 px. Judge `t2` against `t2_nodetail` in the 2× crops.
- **The user's round C picks.** Painted 0.4, deep blue sky, dusk and stronger haze are post
  picks, and the post cannot ship.
  - The post pairs (p03, p04) use dusk, 0.4 and haze 0.70.
  - The engine forms are the key and fill colours (p05, p11), engine fog, and an engine sky
    with a deep zenith.
  - The dusk preset's zenith is already the deep indigo (0.08, 0.09, 0.30), so no separate
    deep-sky setting was used.

## 9. Traps found in Houdini 22.0.466

Every one of these was hit in round D.

| Trap | Fix |
|---|---|
| `shapescatter` `stampscaling` defaults to 1 (Stretch to Tile): each stamp is squeezed into its grid cell, and `scale` changes nothing (measured: the same stroke sizes at scale 0.14 and 0.20) | `stampscaling` 0 (image); `scale` is then the stamp's half-size in image units (stroke length = 2 × scale × shape fraction × res / 2) |
| `randommono` `rangemethod` defaults to 1 (Float Ramp): `min`/`max` are ignored and the values come out 0..1 | `rangemethod` 0 (minmax) |
| `fractalnoise` `elementscalex`/`elementscaley` do nothing until `elementsizetype` is 1 (per component): the bristle noise came out round | set `elementsizetype` 1 |
| `sample` COP with an RGBA texture: `signature` auto fails with "Can't convert RGBA to Mono for tmap". "default" (labelled RGBA) failed too, and "f4", which is not in its menu, is accepted silently and ignored | `channelsplit` the texture and sample each channel with `signature` f1 |
| A File COP has no outputs until `addaovs` is pressed (round C trap, hit again on the stroke EXR) | press `addaovs` |
| `extrapolateboundaries` with the alpha wired into `mask` fails inside its HDA ("monotosdf1/find_boundaries: src is missing") | wire the alpha into `fillarea` |
| `rasterizegeo` `outtype#` tokens are `float`, `vector2`, `vector3`, `vector4`, `int` (labels Mono, UV, RGB, RGBA, ID); "rgb" or "mono" raise "Invalid menu item" | use the tokens; `rasterizesetup` `space` is `uv` (menu pos, uv) |
| The `function` COP (`func` math, `func_math` abs, negative `scale`, `shift`) returned a constant: the scale term was lost. Cause not found | do scale and offset with `blend` (multiply, add) against `constant` layers |
| `hsv` COP `op` to_hsv: hue is 0–1 (pure green reads 0.333), not degrees | hue offset in degrees ÷ 360 |
| `hou.node("/obj").allSubChildren()` does not descend into locked HDAs: the danchi matnets were invisible and 0 materials were styled | `allowEditingOfContents()` on each `sk3::danchi` instance (in memory; never saved), then walk `gen/materials` |
| VEX passes function arguments by reference: modifying a parameter that was fed an expression (`fbm(p * f + off)`) fails with "Read-only expression given for read/write parameter" | declare it `const` and copy it into a local |
| In a vertex-class wrangle, `f@sdir` and `v@Cd` did not fall back to the primitive attributes. They read 0 and a white vertex `Cd`, so the bake projection lost the slab swap and the packed `Alpha` was all 0 | read primitive attributes with `prim(0, "name", @primnum)` |
| The glTF SOP's file parm is `gltffile` (not `filename`). `gltf::2.0` imports packed by default and brings attributes back per point (vertices split), plus a `tangentu` vertex attribute | `unpack` after it; compare distributions, not indices |
| `mtlximage` `signature` menu lists only default and color3, but `vector4` is accepted and works (read back as vector4) | set "vector4", check `eval()` |
| A vertex attribute with `setattribtypeinfo(... "color")` reaches Karma as a color3 primvar, and `mtlxgeompropvalue` color3 reads it | — |
| An 8-bit vertex colour clamps at 1 (Unreal `FColor`); the drift tint reaches 1.09 | store 0.5 + (tint − 1) × 2.5 and decode 1 + (c − 0.5) × 0.4 |
| Overwriting a texture that a running husk reads is unsafe (it happened once with identical content) | rebuild textures between renders |
| A `python -` heredoc in Git Bash started the Windows Store `python` stub and hung | call Houdini's or the user's python by full path |

## 10. Files

All under `C:/Users/jujun/AppData/Local/Temp/claude/C--Users-jujun-DEV-hocus-pocus/d956ad22-ff1d-47a8-a6c1-b1930b7bee4a/scratchpad/roundD/`:

- **Scripts.**
  - `build_brush_tex.py`: the Copernicus stroke and detail textures, in EXR and engine PNG.
  - `apply_painterly.py`: the style layers on the materials, plus the Karma renders.
  - `bake_piece.py`: golden-piece bake, re-import and plain-material render.
  - `export_engine.py`: glTF vertex-data export and re-import check.
  - `measure_painterly.py`: the Lab measurements.
  - `crit_all.py`: frame_critique batch.
  - `assemble_picker.py`: the picker pairs.
  - `run_renders.sh`: the render queue.
  - `hy.sh`: hython from an empty cwd with private prefs.
- **Engine.** `engine/danchi_painterly.gdshader`.
- **Textures.** `tex/brush_{strokes,detail}.exr`, `tex/brush_*_engine.png` and previews.
- **Bakes.** `out/bake/piece_{t1,t2}_{albedo,normal,orm,emissive,mask}.png`;
  `out/engine/piece_t2.glb` and `export_check.txt`.
- **Renders and picker.** `out/full/*.exr|jpg`, `out/post/*.jpg`; `picker/*.jpg` and
  `picker/pairs.json`.
- **Measurements.** `crit/m_*.json` (Lab measurements), `crit/full`, `crit/post` (frame_critique).

## Sources

Ruan Jia:
- Jiemian / 游戏葡萄 interview, 2015-06-03: https://www.jiemian.com/article/295922.html
- ZCOOL interview, about 2016: https://www.zcool.com.cn/article/ZNDA0MTM2.html
- qingwk article quoting it: https://www.qingwk.com/article/detail-10430.html
- CG Cookie Q&A, Russian translation: https://shazoo.ru/2014/09/03/24439/rycari-kisti-ruan-jia
- Zhihu (search snippet only, 403): https://www.zhihu.com/question/54689265
- /ic/ threads (snippets only, 403): https://warosu.org/ic/thread/1562623 · https://warosu.org/ic/thread/2292857 · https://warosu.org/ic/thread/1813556
- Student blog, 2011: http://22-2400.blogspot.com/2011/03/ruan-jia.html
- Medium / GameTextures (snippet): https://medium.com/gametextures/ruan-jia-is-painting-an-intricate-and-magical-world-430f06203a2a
- Muddy Colors, process videos (snippet): https://muddycolors.com/2018/12/ruan-jia-process-videos/
- Bilibili breakdowns (video only, no text reached): https://www.bilibili.com/video/BV1Yh411Y7WU/ · https://www.bilibili.com/video/BV1Mq4y1j7fn · https://www.bilibili.com/video/BV16k4y1A7dZ/
- Works viewed (not stored): https://www.artstation.com/ruanjia · Capital https://www.artstation.com/artwork/rJglAE · Damaged temple https://www.artstation.com/artwork/rlwoBE · Lost Land https://www.artstation.com/artwork/vzAXZA · Storm Plain https://www.artstation.com/artwork/ELrJ24

Engines and Houdini:
- SideFX local help (22.0.466): shapescatter, randommono, sample, rasterizesetup, rasterizegeo, extrapolateboundaries, wrangle, opencl COPs
- Godot 4 spatial shader reference (`light()`, `ATTENUATION`, `EMISSION`, `UV2`, `COLOR`): https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/spatial_shader.html
- Unreal Engine material expressions (VertexColor, TexCoord, AbsoluteWorldPosition, Custom, HueShift) and Exponential Height Fog: https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-materials
- glTF 2.0 vertex attributes (COLOR_0, TEXCOORD_n): https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
