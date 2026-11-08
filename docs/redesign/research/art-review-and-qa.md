# Art review and QA: how studios catch texel-density misses early

Date: 2026-11-07. Scope: how professional teams review and QA environment art so that a miss like ours is caught
early. For many rounds the danchi's weathering lived in one 50 px/m albedo sheet per facade. No review and no
check caught it, because every review image was an orthographic capture at a fixed density and nobody looked from
a player's camera at game texel density. This note covers review practice, art bibles and metrics sheets,
automated validation, definition-of-done checklists and failure stories. It then proposes a review protocol and
skill changes. It does not repeat r5-meta's critique toolkit (value, squint, saturation, repetition) or the
densities and budgets in `texturing-at-scale.md`.

## Conventions

- Tags: **[C]** consensus, **[P]** a practitioner's or studio's practice, **[M]** measured data (including what I
  read in our repo), **[I]** my inference. **[n]** is a source in §9. "(snippet)" means I saw it only in a search
  summary.
- Repo paths are relative to the repo root. The web-search budget, shared by all agents, ran out near the end. §8
  lists what went unchecked.

## 0. Summary

1. **Every major engine shows the on-screen texel ratio as a view mode.** Unreal's Required Texture Resolution and
   streaming-accuracy modes colour each pixel by missing or extra mips [3]. Its Lightmap Density mode colours
   texels against an ideal and a maximum and draws the texel grid [4]. Unity's Mipmaps mode paints over-sized
   textures red and under-sized ones blue. Unity says the ideal size depends on "the resolution at which the game
   will run" and "how close the camera can get" [1]. Houdini's Labs Texel Density shows blue, green and red against
   a target [16]. Godot 4.7 has no such mode [13], and our reviews used none [M].
2. **Our review pipeline could not have seen the miss.** Every image was an orthographic Karma capture at 50, 200 or
   1,000 px/m, and the page halved the elevations again to 25 px/m. No image used a perspective camera at a game
   FOV or eye height, and nothing moved [M][33]. A 50 px/m sheet viewed at 50 px/m is 1:1 by construction. At 1 m
   on a 4K screen, each of its texels covers about 38 × 38 pixels [I, §6.1].
3. **The miss has a famous precedent.** Rage's unique "megatexture" looked blurry up close. Carmack said a
   higher-resolution page file "didn't help much, because most source textures didn't actually have any more
   detail", and the patch added a "bicubic-upsample+detail texture" option [22]. With id Tech 7, id "completed the
   departure from Megatextures" for instanced geometry and tiled textures, to raise texture fidelity [23]. That is
   the split we now use: masks plus tiling detail.
4. **Stills under one light miss whole classes of defects.** Horizon Forbidden West shipped with shimmering in
   Performance mode [25]. Halo Infinite's 2020 demo was judged flat, and the art director's fix list included
   indirect lighting, material response and level-of-detail transitions [26]. The Last of Us Part I shipped on PC
   with poor textures at Low and Medium [24]. Unreal's own screenshot tests switch off anti-aliasing, motion blur
   and auto-exposure to stay stable [6], so image regression cannot see temporal faults either.
5. **Some bugs exist only on a GPU.** Our hex- and band-tiling shaders sample with implicit derivatives after
   random offsets and rotations per vertex. Mikkelsen's reference code takes ddx/ddy of the un-offset coordinate
   once and calls SampleGrad with rotated derivatives [17]. I expect thin mip seams along the triangle edges in a
   real render, and the numpy mirror cannot show them [I][33]. The samplers for the reveal detail are also not
   anisotropic, so grazing views will blur [M][14].
6. **Asset validation is routine and cheap.** Unreal runs Data Validation on save and from a CI commandlet [5].
   Allar's style guide turns uniform density, powers of two, ≤ 8,192 px, texture groups, UVs, non-overlapping
   lightmap UVs, LODs, collision and scale into rules [7]. Godot's importer exposes normal-map Y, mipmaps, VRAM
   compression and size limits [8], and can import headless [9]. Pyblish and AYON validators cover the DCCs [29].
7. **Metrics sheets and art bibles fix the camera before the art.** The Level Design Book lists player size, eye
   height and FOV, and wants world-aligned grid textures [19]. Riot constrained value and saturation per visual
   layer [20]. Valve asks for Dota 2 items to be judged at the gameplay camera in the in-game preview (snippet)
   [21]. Our brief names a camera and densities, but not each surface's nearest approach or an on-screen limit [M].
8. **The fix is a protocol plus a binding gate:** player-camera views first, at 1:1 screen pixels, each with a
   magnification map and a checker pass; a lighting set; grazing, up and down views; motion clips; an engine render
   every round; a numeric magnification check. Godot 4.7.2 and UE 5.8 are already installed here [M].

## 1. Review practice

### 1.1 In the engine, from the player's camera

- **[C] Judge assets in the target engine, at the player's camera and distances.** Unity ties the right size to
  screen resolution and nearest camera distance [1]. Aras Pranckevičius adds that one view never settles it, since
  the same object is seen near and far, and that the useful reading compares neighbours [2].
- **[P] Studios and vendors check in-game.**
  - Valve wants Dota 2 heroes identifiable "from above during gameplay", with items checked in the in-game preview
    (snippet) [21].
  - Nintendo hires contractors to test outsourced environments in the engine against the art vision, technical
    specs and performance (snippet) [30].
  - An outsourcing vendor's rule is never to approve assets from renders alone (snippet; vendor) [35].
- **[P] Fix the camera early.** The Level Design Book: "finalize the camera height / eye offset as soon as
  possible". Most games use 60–90° horizontal FOV, and blockouts use world-aligned grid or checker textures [19].
- **[I] Use the engine's own camera.** Unreal's FieldOfView is horizontal (snippet) [15]. Godot's Camera3D default
  is 75° vertical with Keep Height, about 107.5° horizontal at 16:9 (snippet) [15]. A wall gets about 27 % fewer
  screen pixels per metre at Godot's default than at 90° horizontal.

### 1.2 Debug views that make density visible

| View | Where | Shows | Catches |
|---|---|---|---|
| Required Texture Resolution; Material Texture Scale and Mesh UV Density Accuracy | UE 5.8 | red ≥ 2 mips missing, yellow 1 missing, white good, cyan 1 extra, green ≥ 2 extra [3] | textures too coarse for this camera |
| Lightmap Density | UE | density against ideal and max settings, with "a grid that maps to the actual lightmap texels" [4] | uneven density; the model for a facade density view |
| Mipmaps draw mode | Unity | red "larger than necessary", blue "could be larger" [1] | the same |
| Coloured-mip overlay | any shader | original colour = 1:1 texel:pixel, red too much, blue too little; overlay sampled at `uv·size/8` so the ideal sits two levels down [2] | per-pixel magnification where no view mode exists (Godot) |
| Labs Texel Density; Labs Grid Texture COP | Houdini 22 | blue below target, green match, red above, on a checkerboard [16] | UV density in the DCC |
| Checker everywhere | any | squares must match across pieces (snippet) [31] | mismatched density, stretching |
| LOD and HLOD Coloration | UE | LOD index per primitive [4] | where switches happen |
| Shader Complexity, Quad Overdraw; Overdraw, Wireframe | UE [4]; Godot [13] | cost per pixel, tiny triangles | over-dense damage geometry, decal stacks |
| Material validation (albedo range, pure metal) | Unity HDRP (snippet) [18] | luminance outside a range | over-bright paint (v4's cream) |

### 1.3 Lighting conditions

- **[P] Look Dev.** Unity's Look Dev compares one asset side by side under several HDRI environments, to tell
  whether the asset or the project's lighting lowers quality (snippet) [18]. Our `surfacing.md` already asks for "a
  ball and a plane under several lights" (covered).
- **[P] Halo Infinite.** Much of the 2020 demo sat in a valley out of the sun (snippet, Digital Foundry) [26].
  There only indirect light and material response carry the image, and both were on the fix list [26]. [I] A
  raking sun is the kindest light; the shaded side and overcast are the tests.
- **[M] Our own case.** The S and N previews of every round before round I had the sun's sign wrong, so they had no
  direct light. Nobody noticed until a 1:1 render [33].
- **[I] Lock exposure in reviews and use the engine's tonemapper,** or adaptation hides value errors. Unreal's
  screenshot tests turn eye adaptation off for the same reason [6].

### 1.4 Stills versus motion

- **[P] What each AA method fixes** (Godot's docs): TAA and FSR2 fix specular and transparency aliasing by
  converging over frames, but blur in motion and can ghost; MSAA only partly fixes specular aliasing; the
  screen-space roughness limiter is on by default; SSAA (3D scale 2.0, i.e. 4×) is the reference [11].
- **[P] LOD popping.** Visibility ranges use hysteresis margins that "prevent LODs from popping back and forth too
  quickly". Fading costs transparent rendering during the transition [12].
- **[I] What stills cannot show:** sparkle; moiré on rails, balusters and window grids; TAA smear; LOD, HLOD and
  decal pops; streaming pop-in; shadow-cascade seams.
- **[P] Clips can be exact.** Godot's Movie Maker renders out of real time at a fixed frame rate, so the output
  does not depend on hardware speed; it can write PNG sequences [10].

### 1.5 Cadence and sign-off

- **[P] KotOR II's passes.** A "blocked" level (temp textures, low-detail geometry), then built and textured with
  first-pass lighting, then polish until an internal ship status, each pass revisiting earlier areas (snippet)
  [27].
- **[P] The Level Design Book** orders blockout, scripting, lighting, then art passes, and warns that "a premature
  art pass locks-in early design mistakes" [19].
- **[I] What we lacked.** Our blockout, refine and detail per level, each with a gate, matches this (covered,
  `procedural-assets`). The missing piece was the sign-off view: each gate judged its level's distance in
  orthographic previews, never from a player.

## 2. Art bibles and metrics documents

| Item | Public example | Ours |
|---|---|---|
| Camera: type, eye height, FOV | Level Design Book: player box, eye height, 60–90° horizontal FOV [19] | Phase 0 names "platform and camera" (partly) |
| Scale and grid | Bethesda kits (already in `metrics-and-kits.md`); world-aligned checkers [19] | covered (0.5/1 m contract) |
| Texel density | Allar 7.2: "all textures within that project should have a consistent density" [7]; an old Marketplace rule, "1 texture tile covers 1m" (snippet) [28]; Maxon's 10.24/5.12/2.56 px/cm presets (snippet) [32] | targets covered; nearest approach and on-screen limit missing |
| Value and saturation by layer | Riot: the background "sits behind everything else", characters are "second in contrast", with graphs of "value saturation constraints for each layer" [20] | covered by `frame_critique.py` bands |
| Read at the gameplay camera | Dota 2 guide (snippet) [21] | partly (per-level distances, orthographic) |
| PBR ranges | Unity: painted non-metal albedo 0.2–0.8 (snippet) [34] | covered (`realism.md`) |
| Wear levels | none public found | covered (rulebook presets New to Derelict) |
| Visual target, beauty corner | MoH Airborne deck (in r5-meta) | covered |

**[I] What our sheet must add.** For each surface class, the nearest approach a player can reach: the base, the
access walkway, a balcony, across the courtyard. Add the screen it is seen on (width and FOV axis). Without these,
a density target has nothing to be checked against.

## 3. Automated validation

**Unreal.**
- **Data Validation:**
  - rules come from `IsDataValid` on a class, or from `UEditorValidatorBase` subclasses in C++, Blueprint or
    Python (Python ones register with `UEditorValidatorSubsystem`);
  - it runs on save by default, from the Content Browser, and in CI as `UnrealEditor-Cmd.exe
    <PROJECT>.uproject -run=DataValidation`;
  - Epic's listed use cases include naming conventions and "space and performance budgets" [5].
- **Screenshot Comparison:** ground-truth images, per-channel tolerances, and local and global error limits, with
  AA, motion blur, SSR, auto-exposure and contact shadows off [6].
- **Allar** (the v2 draft says it is "currently for UE4"):
  - textures: powers of two, uniform density, ≤ 8,192, the right texture group;
  - meshes: UVs, non-overlapping lightmap UVs, LODs, collision, correct scale, clean grid snapping;
  - names: `T_` with `_D`, `_N`, `_R`, `_A`, `_O`, `_M`…, and stacked suffixes for packed maps (`_ERO`);
  - the Linter plugin enforces all of this [7].
- **Fab:** no visual defects; lighting built on all maps; "no errors or consequential warnings"; no z-fighting or
  overlapping polygons (snippet) [28].

**Godot.**
- **Import options:** Godot expects OpenGL-style +Y normal maps, so DirectX-style maps need Normal Map Invert Y.
  A texture used in 3D is reimported with mipmaps and VRAM compression. Roughness > Src Normal limits roughness
  from a normal map and "can help decrease specular aliasing slightly". Size Limit caps dimensions. Mipmaps add about 33 %
  memory [8].
- **Headless import:** `--import` starts the editor, imports and quits (4.2.2 and later; snippet) [9]. [I] Each
  `.import` file is plain text, so CI can lint compression, mipmaps, normal-map Y and size limits.
- **No density debug view:** Godot 4.7 has no texel or mip debug draw [13], and BaseMaterial3D's default filter is
  linear with mipmaps, not anisotropic (snippet) [14]. [I] We need a debug mode in our own shader (§6).

**DCCs.**
- **Houdini:** Labs Texel Density computes density per primitive, can rescale UVs, and visualises against a target
  [16]. Our `damage_validate.vfl` and the weathering gate cover the mesh and mask side [M].
- **Pyblish and AYON:** validators check non-manifold geometry, UV presence, single UV set and UV-set names, and
  Blender lint plugins flag ngons, unapplied scale and interior faces (snippet) [29]. I found no published UV-overlap
  or texel-density validator there.

**What validation cannot do [I].** A validator checks what is declared: sizes, flags, names, authored px/m. Our T1
is one. It confirmed every detail tile is ≥ 1,000 px/m [M][33], but not what a player sees at the nearest approach.
That ratio needs a camera, so it belongs at render time (§6, steps 3 and 5).

## 4. Definition-of-done checklists

- **[P] No real studio publishes one.** I found no public studio checklist for environment assets. The nearest
  published equivalents are Fab's requirements [28], Allar's rules [7], Valve's in-game preview step [21] and
  Unreal's validation on save [5].
- **[P] What vendor checklists add** (snippet) [35]: no overlapping UVs unless intended; consistent density;
  documented units and pivots; labelled LODs with screen-size rules; no material or UV jumps between LODs.
- **[I] What is missing from all of them** is the camera: none says "seen at the nearest approach on the target
  screen". §6.3 is our version.

## 5. Failure stories

| Case | What was missed | Found by | Change |
|---|---|---|---|
| Rage, id Tech 5 (2011) | unique megatexture blurry up close; a higher-res page file did not help because "most source textures didn't actually have any more detail" | players, after launch | patch: "bicubic-upsample+detail texture" [22]; id Tech 7 (2020) left megatextures for tiled textures and instancing [23] |
| Horizon Forbidden West (2022) | shimmering and over-sharpening in Performance mode | players, at launch | 1.07: "several tweaks to vegetation to improve image quality"; still a known issue [25]; Digital Foundry credits 1.16 (snippet) |
| Halo Infinite demo (2020) | flat lighting, "plastic" materials, pop-in (snippet) | the public, from a demo | art director: "the art and visuals weren't at the bar"; fixes listed as "indirect lighting, material response, foliage and tree rendering, clouds, level-of-detail transitions" [26] |
| The Last of Us Part I, PC (2023) | textures at Low and Medium; 8 GB cards pushed to those settings (snippet) | players | 1.0.4.0: "Improved texture fidelity and resolution on in-game Low and Medium settings"; a Texture Streaming Rate setting [24] |
| Danchi (ours, 2026) | one 50 px/m sheet for all weathering; wrong sun sign in S/N previews; swapped triangle weights drawing a lattice | the user (sheet); 1:1 renders (the two bugs) | the `large-scale-texturing` split; this note [33] |

**[I] The pattern:** each defect showed only in a view the reviews did not use. These were close up at game
density, in motion, in another light, or at a lower setting.

## 6. A review protocol for our rounds

### 6.1 Screen density at a player's camera

Screen px per metre at the screen centre, for a wall square to the view: `p = W / (2 tan(HFOV/2) d)` [I]. UE
assumes 90° horizontal; Godot uses its default 75° vertical, Keep Height, 16:9 (107.5° horizontal) [15]. The last
two columns are the magnification `p / t` on UE at 4K: screen pixels per texel along one axis.

| d | UE 1080p | UE 4K | Godot 1080p | Godot 4K | 50 px/m sheet | 1,024 px/m tiling |
|---|---|---|---|---|---|---|
| 0.5 m | 1,920 | 3,840 | 1,408 | 2,815 | 77× | 3.8× |
| 1 m | 960 | 1,920 | 704 | 1,408 | 38× | 1.9× |
| 2 m | 480 | 960 | 352 | 704 | 19× | 0.94× |
| 5 m | 192 | 384 | 141 | 282 | 7.7× | 0.38× |
| 10 m | 96 | 192 | 70 | 141 | 3.8× | — |
| 20 m | 48 | 96 | 35 | 70 | 1.9× | — |
| 50 m | 19 | 38 | 14 | 28 | 0.77× | — |

The sheet reaches 1:1 only at about 19 m (1080p) to 38 m (4K), the distance of the whole-elevation reviews. So the
reviews we ran were the one set of views in which it looked right [I].

### 6.2 The ordered checklist

**A. Before rendering.**
1. **Metrics sheet in the brief.** Engine and FOV axis; screens 1,920 and 3,840 wide; eye height 1.6 m; nearest
   approach per surface class; density per carrier. As starting points [I]: entrance and stair core 0.5 m, access
   walkway walls 0.5–1 m, balcony fronts from the street 5–15 m, the facade across the courtyard 20–40 m.
   *Prevents:* a density target with no distance to check it against (our 512 and 1,024 px/m had none).
2. **Pipeline lint.**
   - Sizes are powers of two, ≤ 4,096 for Godot Mobile.
   - Mips are on, masks are linear (sRGB off), and normals use BC5 or `hint_normal`.
   - Normal-map Y matches each engine (+Y for Godot [8]; −Y for UE, snippet [8]).
   - Wall details filter anisotropically; names follow Allar.
   - Run `godot --headless --import` plus a `.import` lint, and UE `-run=DataValidation` [5][9].

   *Prevents:* silent format faults that look like art problems.
3. **Magnification gate, numbers only.**
   - For every carrier and surface class, `m = p(d_min) / t` on the 4K screen.
   - Fail when a carrier holding visible detail (tiling, trims, sharp decals) has m > 2.
   - Masks may exceed it only where a detail with m ≤ 2 reveals their edges (the edge rule).

   *Prevents:* the baked-sheet miss (m ≈ 38 at 1 m) before any image exists.

**B. Views.** Use a perspective camera at the engine's FOV and 1.6 m eye height. Show views at 1:1 screen pixels as
PNG, cropped and never scaled.

4. **Player views first:** touch (0.5–1 m: base, entrance, stair core), the walkway (2 m), across the path
   (5–10 m), across the courtyard (20–40 m) and a block away (100 m, LOD1). Elevations and orthographic crops follow,
   labelled as diagnostics. *Prevents:* judging a texture at its own density.
5. **A magnification map and a checker pass beside every player view.**
   - The map uses UE's legend: red ≥ 2 mips short, yellow 1, white good, cyan and green extra.
   - In the checker pass, each carrier becomes a checker with one texel per square.
   - Report the share of wall pixels with m > 2.

   *Prevents:* blur read as "soft weathering"; planar projections stretched on returns, soffits and window
   reveals; density jumps between kit pieces.
6. **Angles:**
   - a grazing view down the facade at 10–20°;
   - a view up from the base;
   - a view down from a balcony or the roof onto sills, copings and ledges.

   *Prevents:* tile periods and mip blur that show only foreshortened. It also catches tops and undersides, where
   water and dirt sit, which elevations never show.
7. **Scale cues:** a 1.75 m figure and a door in every player view. *Prevents:* miniature reads, wrong formwork or
   tile pitch.
8. **A matched reference photo** beside each player view: same distance, focal length, height and light.
   *Prevents:* density and scale drifting from reality. The photo counts are covered; matching the camera is new.

**C. Light.**

9. **A lighting set per player view.**
   - design sun (15–35°, raking);
   - overcast (sky only);
   - the shaded front (indirect only);
   - night, if windows matter;
   - a neutral lookdev (uniform sky, grey card).

   Use fixed exposure and the engine's tonemapper. *Prevents:* materials and normals that read only in raking sun;
   Halo's flat shade; adaptation hiding value errors; our wrong-sun previews.

**D. Engine and motion.**

10. **An engine render every round.** Render the golden crop and two player views in Godot 4.7.2 (Forward+) and
    check parity with the mirror (mean ΔE00 ≤ 2). Run UE 5.8 at each release. *Prevents:* derivative seams,
    filtering, compression, sRGB and normal-Y faults that the mirror cannot show.
11. **Motion clips** with Movie Maker, `--write-movie <dir>/f.png --fixed-fps 30` [10]:
    - a 15 s walk along the walkway at 1.4 m/s;
    - a lateral pan along the facade at 5 m;
    - a dolly from 5 to 150 m through every LOD, visibility range and decal fade.

    Metrics [I]:
    - the pan residual (frame t shifted by the known parallax, minus frame t+1, on wall and rail pixels) is at most
      1.5× the same clip's residual at 4× SSAA;
    - mean facade luminance jumps no more than 3 % at any switch.

    *Prevents:* shimmer, moiré on rails, TAA smear, and LOD, HLOD and decal pops.
12. **Quality tiers.** Render the touch and courtyard views again at the lowest texture setting, with Godot's Mobile
    renderer and a 4,096 cap. *Prevents:* "fine on max" (§5, The Last of Us).

**E. Read and sign-off.**

13. **Run `frame_critique.py` on the player views,** not only on elevations. The tests are covered; the new part is
    the input.
14. **Lead the page with the player views, the clips and the gate numbers.** Ask one direct question per view: "Is
    anything blurry, shimmering or popping here?" Elevations and sweeps come after.

### 6.3 Definition of done for a round

Every item must hold. The thresholds are [I] starting points, to calibrate on the user's picks.

- The rulebook gate passes, T1–T3 pass, and the magnification gate passes at every declared nearest approach.
- No player view has more than 5 % of its wall pixels at m > 2.
- Engine parity on the golden crop is mean ΔE00 ≤ 2.
- The motion metrics pass, and LOD value match stays within ±3 % (covered).
- The pipeline lint is clean.
- The page leads with 1:1 player views, and every image says its screen px/m.

## 7. Recommendations for our skills

| # | Finding | Why it matters | Concrete change | Skill file | Sources |
|---|---|---|---|---|---|
| 1 | On-screen magnification is a measurable gate | it is the miss itself | add a check, T0: `m = p(d_min)/t` per carrier and surface class at 4K, fail above 2 for detail carriers; implement in `wx_texcheck.py` | `large-scale-texturing/SKILL.md` (Checks) | [1][3][4][16] |
| 2 | Player-camera views lead every review | a texture viewed at its own density always looks 1:1 | Final review and level gates: perspective views at the engine FOV, 1.6 m eye height, the §6.2 distances, 1:1 at 4K, before elevations; an image at the generator's working density is a diagnostic only | `procedural-assets/SKILL.md` (§9, gates); `large-scale-texturing/SKILL.md` (method step 7) | [1][19][21][33] |
| 3 | Godot has no density debug view | we cannot see magnification in our target engine | add a `debug_mode` uniform: magnification heat map (log2 texels per pixel, per carrier), carrier checker, mip level, mask only, detail only; the same in the HLSL | `large-scale-texturing/scripts/layered_facade.gdshader`, `layered_facade_ue.hlsl` | [2][13][16] |
| 4 | Implicit derivatives after random offsets break mips [I] | seams along hex-cell edges, visible in an engine only | compute dFdx/dFdy of `f` once and use `textureGrad(t, uv, R·df/dx/tile, R·df/dy/tile)` in `hex_g`, `band_g`, `hex_rgb` (`SampleGrad` in HLSL); test on a grazing flat wall | `large-scale-texturing` (scripts; Traps) | [17][33] |
| 5 | The engine must be in the loop | the numpy mirror cannot show filtering, derivatives, compression or format faults | render the golden crop and two player views in Godot every round, with parity ΔE00 ≤ 2 every round (now per release); state that UE 5.8 and Godot 4.7.2 are installed | `large-scale-texturing/SKILL.md` (Engine hookup) | [10][17][33] |
| 6 | Stills hide temporal faults | shimmer, moiré and pops reached players at HFW and Halo | Movie Maker walk, pan and dolly clips; pan residual against 4× SSAA; luminance jump ≤ 3 % at switches; clips on the page | `procedural-assets/SKILL.md` (§7, §9); `large-scale-texturing` (Checks) | [10][11][12][25][26] |
| 7 | One raking sun is the kindest light | flat indirect light and weak normals go unseen | lighting set per view (sun, overcast, shaded side, night, neutral lookdev), with fixed exposure and the engine tonemapper | `procedural-assets/SKILL.md` §9 (partly covered: overcast in `believability.md`) | [6][18][26] |
| 8 | Grazing, up and down views are missing | tile periods, mip blur, and the tops of ledges | add the three views; make the reveal-detail samplers `filter_linear_mipmap_anisotropic` after a cost check | `large-scale-texturing` (method, shader) | [14][33] |
| 9 | Asset lint belongs in CI | silent format errors (normal Y, sRGB masks, mips) look like art faults | `godot --headless --import` plus a `.import` lint; UE `-run=DataValidation` with a Python `EditorValidatorBase`; Allar names | `procedural-assets/references/game-output.md` | [5][7][8][9] |
| 10 | Lower settings are part of the asset | "fine on max" shipped broken | render two views at the lowest texture setting and with Godot Mobile, at a 4,096 cap | `large-scale-texturing` (Budgets; partly covered) | [24] |
| 11 | The metrics sheet needs nearest approach and the screen | the targets must exist before the checks | Phase 0 adds the FOV axis, screen widths, eye height, nearest approach per surface class and density per carrier; the gate reads them | `procedural-assets/SKILL.md` Phase 0 (partly covered); `references/art-direction.md` | [7][19][20][21] |
| 12 | A definition of done per round | passing the rulebook gate is not shippable | adopt §6.3 | `procedural-assets/SKILL.md` §9 | [5][7][28] |
| 13 | Review images must not be scaled | the page halved elevations to 25 px/m at JPEG q88 | crop instead of scaling, use PNG for 1:1 views, label each image's screen px/m | review page builders (`render_review.py`); memory note on comparisons | [33] |
| 14 | Value, squint and read checks | — | covered: `frame_critique.py`, `references/art-direction.md` | — | r5-meta |
| 15 | LOD value match | — | covered: `procedural-assets/SKILL.md` §7 (±3 %) | — | — |
| 16 | An upscaled unique sheet cannot gain detail | — | covered: `large-scale-texturing` (Traps); Rage is the precedent [22][23] | — | [22][23] |

## 8. Unchecked

- **Camera and filter defaults.** UE's CameraComponent default FOV (90 is assumed in §6.1), UE's Advanced Preview
  Scene profiles, Godot's default anisotropic level, and whether BaseMaterial3D still defaults to linear-mipmap in
  4.7 (the snippet was 4.1).
- **Requirement pages I could not read.** The full Fab Technical Requirements (support.fab.com) and the current
  status of the old Marketplace density rule.
- **Pages that came back empty or only as snippets.** The Dota 2 guide (no body text), the Nintendo posting (empty),
  the KotOR II diary, the AYON pages, and Digital Foundry's HFW 1.16 and Halo-valley analyses.
- **Studio material I did not find:** a public art bible with texel density or nearest-approach numbers; a studio
  definition of done for environment assets (Clinton Keith's examples); a GDC talk detailing in-engine review
  cadence (Naughty Dog, Insomniac, Guerrilla). Spider-Man's streaming postmortem, the Sunset Overdrive trim talk,
  Battlefront's lighting validation and Frostbite's validation views were not read.
- **The derivative-seam hypothesis** (§0.5, row 4) is not tested in an engine. It comes from reading our code and
  Mikkelsen's reference.
- **Thresholds.** m ≤ 2, 5 % of wall pixels, 1.5× the SSAA residual and 3 % jumps are uncalibrated starting points.
- **Not covered.** UE's Asset Audit and Size Map docs, and Nanite's visualisation modes.

## 9. Sources

- **[1]** Unity Manual 4.2, View Modes (Mipmaps) — https://docs.unity3d.com/420/Documentation/Manual/ViewModes.html · current (snippet) — https://docs.unity3d.com/Manual/ViewModes.html
- **[2]** A. Pranckevičius, A way to visualize mip levels, 2011-05-03 — https://aras-p.info/blog/2011/05/03/a-way-to-visualize-mip-levels/
- **[3]** Epic, Building Texture Streaming Data (UE 5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/building-texture-streaming-data-in-unreal-engine
- **[4]** Epic, Viewport Modes (UE 5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/viewport-modes-in-unreal-engine
- **[5]** Epic, Data Validation (UE 5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/data-validation-in-unreal-engine · UEditorValidatorBase (snippet) — https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/DataValidation/UEditorValidatorBase
- **[6]** Epic, Screenshot Comparison Tool (UE 5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/screenshot-comparison-tool-in-unreal-engine
- **[7]** Allar, UE style guide, v2 README — https://github.com/Allar/ue5-style-guide/blob/v2/README.md
- **[8]** Godot 4.7, Importing images — https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_images.html · UE −Y convention (snippet) — https://cgaxis.com/which-normal-map-should-i-use-opengl-or-directx/
- **[9]** Godot 4.4, Command line tutorial (snippet) — https://docs.godotengine.org/en/4.4/tutorials/editor/command_line_tutorial.html · PR #90431 (snippet) — https://github.com/godotengine/godot/pull/90431
- **[10]** Godot 4.7, Creating movies — https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html
- **[11]** Godot 4.7, 3D antialiasing — https://docs.godotengine.org/en/stable/tutorials/3d/3d_antialiasing.html
- **[12]** Godot 4.7, Visibility ranges — https://docs.godotengine.org/en/stable/tutorials/3d/visibility_ranges.html
- **[13]** Godot 4.7, Viewport, `DebugDraw` — https://docs.godotengine.org/en/stable/classes/class_viewport.html
- **[14]** Godot 4.1, BaseMaterial3D `texture_filter` (snippet) — https://docs.godotengine.org/en/4.1/classes/class_basematerial3d.html
- **[15]** Godot, Camera3D `fov`, `keep_aspect` (snippet) — https://docs.godotengine.org/en/latest/classes/class_camera3d.html · UE CameraComponent FieldOfView (snippet) — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/Camera/UCameraComponent/FieldOfView?application_version=5.1
- **[16]** SideFX, Labs Texel Density (Houdini 22) — https://www.sidefx.com/docs/houdini/nodes/sop/labs--texel_density.html · Labs Grid Texture COP (snippet) — https://www.sidefx.com/tutorials/sidefx-labs-grid-texture-cop/
- **[17]** Mikkelsen, Practical Real-Time Hex-Tiling, JCGT 11(2), 2022 — https://jcgt.org/published/0011/03/05/paper.pdf · reference code, `hextile-demo/hextiling.h` (read: `ddx(st)`, `SampleGrad` with rotated derivatives) — https://github.com/mmikk/hextile-demo
- **[18]** Unity HDRP, Look Dev (snippet) — https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.5/manual/test-and-debug-materials-in-different-lighting-conditions-look-dev.html · material validation (snippet) — https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@15.0/api/UnityEngine.Rendering.HighDefinition.MaterialDebugSettings.html
- **[19]** The Level Design Book, Metrics — https://book.leveldesignbook.com/process/blockout/metrics · Process — https://book.leveldesignbook.com/process/overview
- **[20]** Riot, Dev Blog: Defining the Rift's Visual Style, 2014-11-08 — https://archive.runeterra.net/na/riot-official/5E5saupc · Updating Summoner's Rift, 2014 (snippet) — https://archive.runeterra.net/na/riot-official/97BoAHLR
- **[21]** Valve, Dota 2 Character Art Guide (snippet) — https://help.steampowered.com/faqs/view/0688-7692-4D5A-1935 · CG Channel, 2012-06-20 (snippet) — https://www.cgchannel.com/2012/06/valve-releases-useful-character-design-guide
- **[22]** Shacknews, Rage PC patch will improve 'blurry' textures, 2011-10-17 — https://www.shacknews.com/article/70635/rage-pc-patch-will-improve-blurry-textures
- **[23]** Wccftech, 2020-05-15 (Marty Stratton on id Tech 7) — https://wccftech.com/next-gen-ssd-tech-could-mean-the-resurgence-of-megatextures-technique-says-splash-damage-vp-of-tech/
- **[24]** VGC, The Last of Us Part I PC patch 1.0.4.0, 2023-04-26 — https://www.videogameschronicle.com/news/new-the-last-of-us-pc-patch-optimises-cpu-and-gpu-use-fixes-crashes-and-more
- **[25]** The FPS Review, HFW patch 1.07, 2022-03-09 — https://www.thefpsreview.com/2022/03/09/horizon-forbidden-wests-latest-patch-improves-graphics-quality-of-vegetation-in-performance-mode · Push Square, 2022-02 (snippet) — https://www.pushsquare.com/news/2022/02/horizon-forbidden-west-ps5-ps4-shimmering-bug-solved
- **[26]** Engadget, 2020-07-31 — https://www.engadget.com/halo-infinite-343-industries-visual-art-style-craig-response-102047314.html · Pure Xbox, 2020-12-09 (Nicolas Bouvier) — https://www.purexbox.com/news/2020/12/343_knows_the_visuals_werent_great_in_halo_infinites_gameplay_demo
- **[27]** GameBanshee, KotOR II designer diary #3 (snippet) — https://gamebanshee.com/ux6
- **[28]** Fab, asset file format and structure requirements (snippet) — https://dev.epicgames.com/documentation/en-us/fab/asset-file-format-and-structure-requirements-in-fab · old Marketplace density rule, quoted on the Unreal forums (snippet) — https://forums.unrealengine.com/t/leniency-on-marketplace-texture-density-guideline/378437
- **[29]** AYON, `ValidateMeshNonManifold` (snippet) — https://docs.ayon.dev/ayon-maya/latest/autoapi/client/ayon_maya/plugins/publish/validate_mesh_non_manifold.html · Pyblish Blender lint (snippet) — https://github.com/hannesdelbeke/pyblish-plugins-blender-lint
- **[30]** 80.lv Jobs, Nintendo environment art review artist (snippet) — https://80.lv/jobs/environment-art-review-artist-contract-nintendo
- **[31]** Polycount, checker texture for consistent density (snippet) — https://polycount.com/discussion/comment/1131873
- **[32]** Maxon, Texel Density (snippet) — https://help.maxon.net/c4d/en-us/Content/html/Texel_Density.html
- **[33]** Repo and project memory: `examples/danchi/weathering/render_review.py` (orthographic shots at 50/200/1,000 px/m; elevations halved; JPEG q88), `elevation_capture.py`, `crop_capture.py`, `scripts/weathering/wx_texcheck.py` (T1 on authored px/m), `.claude/skills/large-scale-texturing/scripts/layered_facade.gdshader` and `layered_facade_ue.hlsl` (implicit-derivative sampling; non-anisotropic reveal details); round-I notes; installed UE 5.8 and Godot 4.7.2
- **[34]** Unity Manual 2020.2, Making believable visuals (snippet) — https://docs.unity3d.com/2020.2/Documentation/Manual/BestPracticeMakingBelievableVisuals5.html
- **[35]** Zatun, outsourcing guide (vendor; snippet) — https://zatun.com/a-step-by-step-guide-to-outsourcing-3d-game-art/ · GeometryOS (vendor; snippet) — https://geometryos-com.pages.dev/blog/what-studios-expect-from-a-shippable-3d-model

## 10. Actions

Statuses as `scripts/research_actions.py` reads them (round J). Numbers are §7's.

| # | Action | Status |
|---|---|---|
| 1 | T0 magnification check at 4K and the engine FOV | done (`wx_texcheck.py` rule_T0, run by `weather_gate.py texture` before any review page; large-scale-texturing SKILL.md Checks) |
| 2 | Player views at 1:1 lead every review | done (`render_player_j.py`; procedural-assets SKILL.md Phase 9; large-scale-texturing method step 7; the round-J page) |
| 3 | Godot `debug_mode` views (magnification, checker, mip, mask, detail) | parked (no shader has rendered in an engine yet; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 4 | `textureGrad` after random offsets | parked (the trap is in large-scale-texturing SKILL.md; the shader change needs an engine render to test; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 5 | Engine render and parity every round | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 6 | Motion clips: walk, pan and dolly | parked (needs the engine; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 7 | A lighting set per view (sun, overcast, shaded, night, lookdev) | parked (procedural-assets SKILL.md Phase 9 lists it; the numpy mirror has one sun; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 8 | Grazing, up and down views | parked (listed in Phase 9; tops and soffits are not in the planes; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 9 | Asset lint in CI (Godot `--import`, UE DataValidation) | parked (spec in procedural-assets game-output.md; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 10 | Two views at the lowest texture setting and Godot Mobile | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 11 | Metrics sheet: FOV, screens, eye height, nearest approach per class | done (procedural-assets SKILL.md Phase 0; `wx_texcheck.T0C` reads the nearest approach per class) |
| 12 | A definition of done per round | done (procedural-assets SKILL.md Phase 9) |
| 13 | Review images cropped, never scaled, PNG, labelled | done (`render_player_j.py`; the round-J page) |
| 14 | Value, squint and read checks | done (covered: `frame_critique.py`, references/art-direction.md) |
| 15 | LOD value match | done (covered: procedural-assets SKILL.md Phase 7) |
| 16 | An upscaled unique sheet cannot gain detail | done (covered: large-scale-texturing Traps) |
