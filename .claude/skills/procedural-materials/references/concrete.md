# Concrete: finishes, layer stack, recipes, engine path

Concrete is the main material of a danchi, and it is usually under a coat. This reference says:
- which finish goes on which element;
- how to build each finish so it reads as cast concrete rather than plaster;
- the Copernicus and MaterialX recipes, verified in Houdini 22.0.466;
- how the sets go to an engine.

Read it with:
- [realism.md](realism.md) for clustering and weathering;
- [micro-noise.md](micro-noise.md) for grain statistics;
- [layering.md](layering.md) for height blending.

The full research, with sources, is `docs/redesign/research/rE-concrete.md`. The working
scripts are in `docs/redesign/evidence/concrete/`. *(est.)* marks practice or inference rather
than a published or measured figure.

## Why concrete reads as plaster

Plaster and stucco are hand-applied: one band of isotropic grain, soft edges, even tone, and no
module. Concrete is defined by its mould:
- a grid of panels and ties;
- seams with steps or fins;
- layer lines;
- bug holes clustered toward the top of each lift;
- cloudy tone from panel to panel;
- sharp arrises;
- stains placed by geometry.

A material made only of isotropic noise reads as plaster, however good the noise is.

The danchi renders that read as stucco shared five faults:
- **The grain was the strongest band.** On the v2 close-up the 1.5–4 px band had 10× the
  contrast of the 12–48 px band, and the spectrum rose toward fine scales (slope +0.25). Every
  photographed wall had a falling spectrum (slope −0.1 to −1.5).
- **The grain was stationary.** The local grain strength varied only 7 % across the wall; in
  photos it varies 12–68 %.
- **The grain was too large and too deep.** The v6 recipe used 11–24 mm cells and 3 mm of
  relief, exaggerated 2×.
- **There was no module.** No joints, ties, laps or patches.
- **One finish covered every face.**

## Pick the finish per element

| Element | Finish | Notes |
|---|---|---|
| Walls, parapets, 1970s–80s blocks | repainted 吹付タイル spray tile (multi-layer), flattened bumps softened by 1–3 repaints | the coat set (macro plus detail) |
| Walls, 1960s blocks | render plus paint, or リシン lithin sand spray | rendered walls: no formwork telegraphing; render cracks and patches instead |
| Walls of W-PC (precast) walk-ups | paint or thin coat over steel-form panels | joints at every floor and panel edge, 15–25 mm, sealant overcoated; a dark band beside joints |
| Soffits of balconies, eaves, stair halls | lithin or smooth paint | evenly greyer (no rain washes them); peeling and efflorescence; spalls within 0.2 m of the edge |
| Slab edges, copings, nosings | smooth paint or bare | spalls and rust at rail-post pockets and nosings; patch rectangles |
| Stair cores, retaining walls, plinths, planters | bare formed concrete (打ち放し, ordinary grade) | the formed set |
| Cut faces, spall cavities, chips | bare broken concrete: lighter, cooler, aggregate visible | from the damage mask |
| Hero or architectural walls | 打ち放し, Ando grade | open cone recesses, crisp seams, very even tone |

The stucco look is correct for spray tile and for JIS スタッコ (thick coats) at arm's length,
but only as the detail layer:
- at its true size, about 3–11 mm;
- at its true relief, about 1 mm after repaints *(est.)*;
- with the module, joints, laps and patches on top;
- never on soffits, copings and slab edges as well.

## Scale contract

| Item | Size | Origin |
|---|---|---|
| Konpane formwork panel | 900 × 1800 mm, stood vertically; also 600 × 1800 | JAS form plywood |
| Tie (P-cone) grid | 450 × 600 mm, 6 per panel; 450 × 450 gives 8 | Japanese practice |
| P-cone hole | 30 mm across (30–45 mm); plug about 2 mm recessed on exposed work | manufacturer manual |
| Seam gap, step, fin | 2 mm gap *(est.)*; step ±1–3 mm; fins up to 3–5 mm | DBV T2–T3, ACI SI3–SI4 |
| Placement layer | about 0.5 m; one pour per storey (about 2.96 m) | DBV, AIJ site study |
| Bug holes | 1.5–15 mm; 0.3–1.2 % of the area | ACI SVR, DBV P classes |
| Board form | boards 75–150 mm | practice |
| PC joint | 19–25 mm, sealant half as deep | PCI |
| Crack-control joints | ≤3 m apart, 20 mm deep in a 150–200 mm wall | AIJ via Osaka prefecture |
| Spray-tile bumps | 5–15 mm; coat about 1 mm, peaks 2–4 mm *(est.)* | from JIS coverage rates |
| Roller laps on repaint | about 800 mm | UR specification (snippet) |
| Crack injection seats | every 200–300 mm | practice |

Tile sizes:
- **Formed:** 3.6 × 3.6 m (4 × 2 panels, 8 × 6 ties), at 2048 for game and 4096 for hero.
- **Coat macro:** 3.6 m at 2048.
- **Coat detail:** 0.6 m at 1024 (1700 px/m).

Never hex-tile a formed set: its grid must stay registered to the building.

## The layer stack

1. **Substrate height, in metres:** panel steps, waviness between battens (±0.8 mm at 0.7 m),
   plywood grain broken at each seam, micro sand.
2. **Cast defects, subtracted from height and kept as masks:** seams (fin or paste-loss band),
   tie plugs (conical wall, flat plug face), bug holes, one crack.
3. **Cast colour:**
   - per-panel tone;
   - mottling and hydration clouds;
   - wavy layer lines;
   - vertical bleed streaks;
   - halos around ties;
   - lighter plugs;
   - dark voids;
   - a few runs below ties (lime, rust).
4. **Coat (if any):** a detail set at its true size, whose strength comes from a macro coat mask.
   The macro coat set carries the concrete showing through (panel steps, tie dimples),
   roller-lap and scaffold-lift overlaps, repair patches, and sealed and open cracks.
5. **Weather, in the shader, from one cause field:**
   - world macro value at 5–15 m;
   - streaks from sources (a fringe below a top with no drip, sill ends);
   - sheltered patches;
   - a darker lower wall;
   - a damp base band with a ragged top.

   Dirt fills voids, seams and coat troughs first.
6. **Decals:** hero leaks, spalls, patches, graffiti, joint sealant strips.

## Parameter ranges

| Layer | Height | Colour (relative to base) | Roughness |
|---|---|---|---|
| Panel tone | — | ±3 % in the tile plus ±5 % world tint per panel index (the prototype's ±6 % in the tile still repeated at 9 m) | ±0.03 per panel |
| Panel step | ±1.2 mm, blurred 1.5 mm | — | — |
| Mottle | — | factor 0.22 on a 0.32 m noise (1.7 % std), × panel wear 0.5–1.4 | darker clouds −0.03 |
| Hydration clouds | — | −7 % on about 15 % of the area | — |
| Layer lines | — | −3.5 %, broken up (about half the length) | — |
| Bleed streaks | — | 10 × 200 mm, in zones; factor 0.05 (0.4 % std) was too faint, so try 0.3 *(est.)* | — |
| Seam paste loss | −0.6 mm, 8 mm band | −5 % | +0.06 |
| Fin | +0.8 mm, 2 mm wide | +2 % | — |
| Tie plug | −2 to −10 mm; about 7 % open at −22 mm | plug +3–13 %; hairline ring −18 %; halo −3.5 % | +0.04 |
| Bug holes | depth 0.6 × radius; profile 2t − t² | −40 % inside | +0.14 |
| Crack | −0.4 mm, 1–2 px | −30 % | +0.08 |
| Pores, specks (formed) | — | 4 mm noise, 2.7 % std × a clustered envelope (0.4–1.4) | — |
| Blotches (formed) | — | 3.5 cm noise, 3.8 % std × the same envelope | — |
| Lime run | — | toward (0.46, 0.46, 0.45) at up to 35 % | +0.10 |
| Rust run | — | toward (0.22, 0.11, 0.05) at up to 35 % | — |
| Coat relief (detail) | about 0.9 mm peak to trough, × coat × 0.75 in the shader | trough dirt (0.35 + 0.6 × cause) × cavity × coat | +0.06 × cavity |
| Coat blotches | — | 4 cm noise, 2 % std × a clustered envelope | — |
| Coat telegraphing | panel step ±0.6 mm blurred 4 mm; tie dimple −0.3 mm | — | — |
| Roller laps, lifts | +0.15 mm | −1.2 % | −0.02 |
| Repair patch | smoother (coat 0.45); edge ridge +0.3 mm | +0.8 %, a little warmer: faint, because it repeats with the tile; visible ones go in decals | −0.03 |
| Sealed crack | bead +0.25 mm, 10 mm; seats +0.5 mm every 257 mm | sealant grey at 25 % | −0.10 |

**Read "±x %" as a measured effect, not a factor on the noise range.** `fractalnoise` around
0.5 has a std of only 0.076 (p1–p99 0.31–0.70), and 0.05–0.06 at large element sizes. So a
factor k on (noise − 0.5) gives a std of about 0.076 × k. The result to aim for is the formed
set's base colour, measured as the std of a band-pass, in % of the mean:
- 0.5–2 cm 2.8;
- 2–10 cm 3.6;
- 10–50 cm 2.5;
- 0.5–1.8 m 2.8;
- per-panel means 4.1;
- overall 8.0, with p1–p99 0.24–0.35 linear.

The coat's base colour measured 2.6 % overall and 1.9 % at 2–10 cm, with the macro scales left
to the shader.

Coverage targets:
- **Bug-hole cover:** 0.3–1.2 % (measured 0.57 % at 4096).
- **Patch cover:** about 2 % per 3.6 m tile.
- **Each detail layer:** under about 60 % coverage (Foreman).

## Values

| Material | Base colour, linear | Roughness | Normal |
|---|---|---|---|
| Fresh formed concrete | 0.40–0.55 (0.51 measured) | fresh skin 0.55–0.7 *(est.)* | height in metres, physical slope × 1–1.5 |
| Weathered bare concrete | 0.20–0.35; our formed set 0.26–0.33, mean 0.30 | 0.76–0.85; voids 0.95 | as above |
| Off-white danchi paint (about 2.5Y 8.5/1) | 0.58–0.66; our coat 0.60 | chalked 0.75–0.85; fresh semi-gloss 0.55–0.7 *(est.)* | coat detail through bump at its true relief |
| Wet concrete | albedo −0.2 (solar) | −0.05–0.15 | — |

Colour variation:
- **Hue:** keep hue drift to 1–3° per panel or pour and 2–4° at macro scale, at C\* 1–4.
- **Grey:** cement grey is near neutral. Use a warm grey base (0.305, 0.300, 0.283) and lerp
  0–40 % toward a cool blue-grey (0.272, 0.282, 0.288) in the dark clouds *(est.)*.

## Copernicus recipes (22.0.466)

Helpers and both builders are in `docs/redesign/evidence/concrete/`:
- `cc_lib.py`: a `G` graph class with maths helpers. `G.U(m)` converts metres to image units:
  2 / tile across.
- `build_formed.py`;
- `build_spray.py`.

Run headless with `hython build_formed.py <out> 4096` (about 3 minutes, mostly PNG writing),
or `hython build_spray.py <out> 2048 1024` (under 10 s).

### Formed concrete

| Feature | Nodes and parms |
|---|---|
| Panels and ids | `tilepattern` `patterntype` stackbond, `patternmode` tilecount, `stackbond_rows` 2, `stackbond_cols` 4, `inset` U(0.002); outputs `tiles` 0, `id` 1, `uv` 2 |
| Per-panel randoms | `randommono` with the id in its `seed` input, a different `seed` parm per use, `zeroinvalid` 1 |
| Seam bands | `feather` on `tiles` (`unitdist` U(0.012), `includeborder` 0), then `invert`, then `remap` `op` threshold (`threshold`, `width`) |
| Tie holes | `tilepattern` rows 6, cols 8, `basictype` circle, `scale` 0.030/0.45, `draw` gradient, `gradienttype` radial, `doposjitter` 1, `posjitter` 0.012. Disc = `remap` 0–0.02; wall = `remap` 0–0.35 × depth |
| Layer phase | `ramp` `signature` f1, `rampType` vertical, `cycles` tile/0.6, `method` repeat, then `distort` (input 2 `scale` = fractal noise, `dirtype` coord, `dir` (0, 1), `scale` U(0.06)) |
| Layer lines | min(phase, 1 − phase) with `blend` `mode` min and `invert`, then `remap` 0–0.012, inverted |
| Bug holes | `worleynoise` `elementsize` U(0.010): keep = threshold(density − rand(id)); R = rand(id)^2.5 scaled; t = 1 − `remap`(dist1 / R) (`blend` `mode` divide); profile 2t − t² |
| Grain | `fractalnoise` `elementsizetype` 1, `elementscale` (1, 26), `elementsize` U(0.0035). Break it per panel with `distort` (input 1 `dir` = `channeljoin` `signature` f2 of two panel randoms, `dirtype` coord, `scale` U(0.8)) |
| Crack | `ramp` horizontal through `distort` by fractal noise, then `function` `func` math, `func_math` abs, of (x − x0), then a narrow `remap`; limited by a vertical `ramp` |
| Runs | per-tie pick inside the disc, then `blur`, then `streakblur` `dirtype` coord, `dir` (0, −1), **`bias` 1**, `mode` on; then `distort` sideways; × stretched noise |
| Normal | `heighttonormal` on height in metres, `scale` 1.5 × 2 / tile |
| AO | `heighttoambientocclusion` `heightscale` 2 / tile, `viewradius` U(0.02) |
| Packing | `channeljoin` `signature` f3 (mask: R ties, G voids, B seams); the layer phase in its own file |

### Spray-tile coat

| Feature | Nodes and parms |
|---|---|
| Detail droplets (0.6 m tile) | Three `worleynoise` sizes: 10.5 mm `lattice` hex, `jitter` 0.75; 6.2 mm; 3.4 mm. Each dome 2t − t² × a random height, kept 50–80 %. The big ones are flattened by `clamp` `doupperlimit` 1, `upperlimit` 0.6, then rescaled, and scaled by a spray-pass mask (a fractal at 0.09 m, thresholded) |
| Repaints | lerp with `blur` 0.6 mm at 0.6, then add `blur` 3 mm × 0.45; then grit; then `equalize` `mode` stretch |
| Detail outputs | height (16-bit), normal (physical slope), cavity = stretched (1 − AO), top = threshold 0.72 |
| Macro telegraphing | panels as above, ±0.6 mm, blurred 4 mm; tie discs blurred 4 mm, −0.3 mm |
| Laps and lifts | `ramp` `cycles` 4 (0.9 m) and 3 (1.2 m) horizontal, 2 (1.8 m) vertical, `phase` offsets; `distort` waver; a triangle band; × breakup noise |
| Patches | rectangles from two `ramp`s (horizontal and vertical) thresholded, edges warped by `distort`, then `blur` |
| Coat mask | 0.55–1.05 fractal + 0.12 × laps; 0.3 in patches; written as R of an RGB mask |

### Other finishes *(est.)*

- **Lithin:**
  - a detail set of sand grit (Worley 0.4–1.2 mm, relief 0.2–0.3 mm, kept 60 %), very matte;
  - roughness 0.85–0.92;
  - dirt and streaks show strongly on it.
- **PC panel:**
  - a smooth set with panel-wide tone, sparse small air holes (SVR4 class, about 0.3 %);
  - crazing cells of 12–40 mm faint in colour only;
  - joints as geometry or mesh decals with a dark plasticiser band of 2–5 cm.

## MaterialX in Karma

- **Textures.** `mtlximage` `file`, with `filecolorspace` srgb_texture for base colour and Raw
  for data. Set `signature` vector3 for normal images: the menu lists only default and color3,
  but vector3 is accepted and works.
- **Texture coordinates** in metres from the generator: `mtlxtexcoord` vector2, then
  `mtlxmultiply` vector2FA by 1/tile.
- **Macro normal:** the image into `mtlxnormalmap`.
- **Detail on top:** `mtlxbump` with `height` = detail height × relief (m) × coat, and its
  `normal` input fed by the macro `mtlxnormalmap`. The height is in scene units. This chain
  rendered correctly in Karma CPU.
- **Mask channels:** `mtlxseparate3c` (outr, outg, outb).
- **Per-panel world tint:** `mtlxcellnoise2d` on st / (0.9, 1.8), remapped to 1 ± 0.05. It
  stops the tile's panel tones repeating every 3.6 m.
- **The cause field** (`grime_field` in `render_wall.py`):
  - `mtlxposition` world;
  - `mtlxfractal3d` stretched (9, 0.36, 9) for streaks, through `mtlxsmoothstep`;
  - a fall-off below the wall top;
  - sheltered patches at 0.28 cycles/m;
  - more grime toward the base;
  - a damp band from `mtlxsmoothstep` on world y.

  Dirt is `mtlxmix` toward a soot colour, never a grey multiply.

## Engine path

**Bake:**
- **Base colour:** sRGB 8-bit.
- **ORM:** R AO, G roughness, B metal; raw 8-bit.
- **Normal:** raw 16-bit PNG; the engine compresses it to BC5.
- **Height:** 16-bit, with the range in `*_meta.json`.
- **Masks:** RGB raw.
- **Detail sets:** height, normal and cavity.

**Conventions:**
- **The normal is OpenGL style (+Y up).** Copernicus `heighttonormal` gives G < 0.5 for a slope
  that rises upward. Flip green on import for Unreal; Godot and MaterialX use it as is.
- **Data masks stay RGB, or each goes in its own file.** Karma (OIIO) premultiplies RGB by A
  when it reads an RGBA PNG. Engines read the four channels raw, so an RGBA pack is fine there.

**Runtime shader** (everything the building places):
- streaks from sources;
- the damp band;
- washed tops;
- the lift and joint at each storey;
- per-panel and per-bay tint;
- detail strength from the coat mask.

Cook what never varies per instance into the tiling sets. Unique pieces such as end walls can
bake the whole composite with `rasterizegeo`.

**Unreal:**
- **Base:** TexCoord (metres) ÷ tile, then TextureSample for BaseColor, ORM (Masks, no sRGB) and
  Normal (BC5, flip green).
- **Detail:** TexCoord ÷ 0.6, then the detail normal. Scale its xy by mask.R × 1.5 (ComponentMask
  and Append), then BlendAngleCorrectedNormals onto the macro normal.
- **Dirt:** detail cavity × coat × cause, lerped toward soot.
- **Macro:** WorldPosition × 0.07–0.11 into a noise texture, then Lerp(0.94, 1.06) × BaseColor.
- **Cause and damp:** vertex colour or generator data (R grime, G damp) through HeightLerp
  against the detail height.
- **Per-instance tint:** PerInstanceRandom.
- **Decals:** DBuffer decals for tie holes, leaks and patches (colour, normal, roughness; no AO);
  mesh decals for joint sealant and drip stains.

**Godot 4** (`ShaderMaterial`, spatial):
- **Inputs:** macro albedo (source_color), ORM, normal (hint_normal), mask, detail normal and
  cavity.
- **Normals:** reconstruct z from xy (normal-map imports keep RG only), whiteout-blend
  `normalize(vec3(nM.xy + nD.xy * coat, nM.z * nD.z))`, write `NORMAL_MAP = n * 0.5 + 0.5`.
- **Story:** world macro from `MODEL_MATRIX * VERTEX`; vertex COLOR for grime and damp.
- **Decals** take albedo, normal and ORM but not height. The full shader is in the research
  report.

## Checks

- **Statistics of a plain wall crop** (`analyze_walls.py`; photos in brackets; the prototypes
  in round E reached slope −0.76 and −1.05, fine/broad 1.3 and 0.8):
  - spectrum slope below 0 at 3–48 px (−0.1 to −1.5);
  - fine-band std about 0.8–3 L\*;
  - local-std cv ≥ 0.15 (0.12–0.68);
  - fine-band kurtosis ≥ 4 (3.5–31).

  Pass `frame_critique.py --crop` on the wall, or a wall mask. On the full frame its
  `micro_uniformity` passed the v2 close-up (p90/p10 5.9) while the wall crop was stationary.
- **Coverage, with a `statistics` COP:**
  - bug holes 0.3–1.2 %;
  - ties about 0.26 % (48 × 30 mm on 13 m²);
  - patches about 2 %.
- **Tiling, 3 × 3:** the grid repeats by design. Check that the per-panel world tint hides the
  tone repeat at 30 m.
- **Read at three distances:** 2 m (ties, holes, coat grain), 9 m (panels, laps, streaks, tone),
  30 m (tone and streaks only).

## Traps (verified in 22.0.466)

| Trap | What happens | Do |
|---|---|---|
| `fractalnoise` `elementscale` | ignored at the default `elementsizetype` 0 | set `elementsizetype` 1 (Per-Component Controls) |
| `streakblur` `dirtype` coord, `dir` (0, −1) | smears both ways (centred) | `bias` 1 for downward only (−1 for the other way); `distort` with `streak` is one-sided |
| Image orientation | buffer row 0 is the bottom; y is up | flip when reading with numpy; PNGs are written top-down correctly |
| `tilepattern` circles | stay round in non-square cells at the default `useaspectratio` 0, sized to the smaller side; `useaspectratio` 1 stretches them | leave it off for round ties |
| `tilepattern` `id` outside a shape | an invalid id: `randommono` gives one shared value there (0.98 at seed 14) | `zeroinvalid` 1; choose per element inside the shape, then blur to widen |
| `worleynoise` | `dist1` is in cell units (0–1.1) at any `elementsize`; `id` is int32 (NaN as float) | feed `id` only to `randommono` |
| `cellularnoise` | does have `gap`, `bevel` and `mode` parms (copernicus.md said otherwise before round E) | — |
| `ramp` into `heighttonormal` | "Error while cooking" at the default signature | `signature` f1 |
| `heighttonormal` `scale` | multiplies the slope per image unit; output 0–1 encoded, OpenGL | height in metres × `scale` 2 / tile = physical slope |
| `rop_image` RGBA PNG | the default `pngtga_alpha_multiplication` "premult" (label "Unpremultiply if needed") divides RGB by A | token "unpremult" (label "Raw") for data |
| `mtlximage` on an RGBA PNG in Karma | RGB arrives premultiplied by A | RGB masks; a fourth channel in its own file |
| `file` COP from Python | shows no outputs (AOVs not set up) | read EXRs with OpenImageIO, which ships with hython |
| `karmarendersettings` `resolutiony` | locked (PermissionError) even after `res_mode` manual | keep autoheight and set the camera aperture ratio |
| `sopimport` `path` | a point-class `path` is ignored; a relative prim path "wall" lands under the node's prim | set `path` on prims |
| `phasornoise` `firstrotatepattern` | changed nothing in a gradient test | use stretched `fractalnoise` for directional grain |
| `randommono` `seed` parm with an id input | gives independent streams (correlation about 0) | one seed per use |
| `fractalnoise` spread | std 0.076 (p1–p99 0.31–0.70); less at large sizes (0.048 at 0.3 units). Factors that assume a 0–1 range give walls with almost no meso variation: our first renders had 0.05–0.2 L\* at 2–10 cm, against 0.5–3.5 in photos | scale by the measured spread, or `equalize` stretch first; check the base colour per band |
