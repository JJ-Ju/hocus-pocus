# Surface detail and weathering: professional techniques, and what our map-driven generator lacks

Date: 2026-11-07. Scope: how professional texture, material and technical artists build surface detail and weathering
for game assets. It covers the scale hierarchy, masks from mesh maps, layer stacks, flow, specks and pits, rust on coated
steel, variation and decals, as done in Substance Painter, Designer and Sampler, Houdini 22, Unreal Engine 5 and Godot 4.
It also lists which of these techniques the danchi weathering pipeline (`scripts/weathering/`, rulebook 1.6, commit
fa8d46a) has no equivalent for. It answers the round-I verdict ("the texturing was a big miss") and the user's detail
notes: darker, cooler flecks and pebbles in concrete; more saturation variety; 1 cm pits; paint cracking; chipping and
peeling down to concrete; rust runs down vertical rails; dark old rust beside bright fresh rust; bare metal around rust;
and more dirt and growth in corners, recesses and along top edges. It points to the skills and earlier notes rather than
repeating them.

## Conventions

- Tags: **[C]** consensus, vendor documentation or a standard; **[P]** a named practitioner's practice; **[M]** measured
  data; **[I]** my inference. **[n]** is a source in §13. "(snippet)" means I saw the claim only in a search summary.
  **[M, repo]** is my reading of the code at fa8d46a.
- In §11, "covered" names the file that already holds the point.
- The shared web-search budget (200 calls per turn, for all agents) ran out before the end. Polycount, ArtStation,
  Springer and some Adobe helpx pages refused the fetcher. §12 lists what went unchecked.

## 0. Summary

1. **Pro weathering masks start from baked mesh maps.** Painter's Dirt, Metal Edge Wear and Dripping Rust generators read
   curvature (Edges or Cavities, at seven scale bands), AO, world-space normals and position, times a grunge breakup
   [2]–[5]. Houdini 22 bakes AO, curvature, cavity, thickness, edge and position maps [10] and masks by direction, shadow
   and AO [12][13]. Our generator has none of these at either density: corners, recesses and top edges get only coarse
   `shelter` and inside-corner terms at 50 px/m, and the 1 mm compositor ignores the depth the crop capture already saves
   [M, repo]. This is the main missing technique behind "more dirt and growth in corners, recesses and along the top edges".
2. **Paint is a stack of material sets, each with its own height.** Pro graphs keep substrate, holes, panels, rebar and
   paint as separate parts, build the peel edge as blur-minus-mask and warp the paint into islands [24]; peels lift at
   their edges [33, snippet] and grow from crack networks (Paquette 2002, `r5-wear-simulation.md`). We have no peeling
   layer, only a compositing hook; chips lerp to `old_paint` 85 % of the time; only the breaks have relief [M, repo].
3. **Rust breaks a coat in rings.** The paint loses its bond ahead of the rust front (cathodic delamination [38, snippet];
   swelling, `weathering-rust-water.md` §2), so lifted or lost paint surrounds the rust; ISO 4628-8 grades delamination
   and corrosion separately [37, snippet]. Pro tools give rust its own peel relief and gravity drips [5][9], and one artist
   outlines it with a second threshold for a "bubbling look" [25]. Ours has colour by age but no halo, no exposed metal or
   primer, no relief, and an isotropic detail tile, so runs on uprights read as blotches at 1 mm/px [M, repo].
4. **Flecks and pebbles belong where the cement skin is gone.** Fines under ~150 µm act as pigment; grains over ~500 µm
   "generally don't show on as-struck concrete unless a thin cement layer is removed" [34]. Aggregate is 60–75 % of the
   volume [35, snippet], and run-off removes paste first, then grains [36, snippet]. So flecks are sparse on fresh skin and
   dense on washed faces, worn arrises, splash zones and under lost paint, and pebbles show on breaks. Our coat and bare
   concrete have no fleck or pebble layer, and the coat's grain is still Gaussian (`rE-concrete.md`).
5. **The clean coat varies only in value.** `coat_cloud()` returns a scalar luminance factor [M, repo]. Concrete is "never
   a monotone block colour" [34], and `concrete.md` already asks for 1–3° of hue drift at C\* 1–4 with cooler dark clouds:
   a cheap source of the missing saturation variety.
6. **A later layer should read the composite below it.** Painter's anchor points let generators read the painted height
   (`r5-texture-layering.md` §3); our compositor reveals each layer against its own tile, so dirt cannot fill a peel step,
   a chip floor or rust pits [M, repo].
7. **Decals carry the hero marks and the joins.** Unreal mesh decals update the GBuffer or DBuffer after opaque geometry,
   with no depth and no shadows [16]; Godot decals mask normal and ORM by albedo alpha, allow 512 clustered elements (8
   per mesh on Mobile) and cannot change height [21]. MachineGames ages buildings with layered blends and "geo-decals"
   [32]. Our export makes decals only for rust runs and cracks [M, repo].

## 1. The detail hierarchy and how each scale ships

**Scale decides the carrier.** Becker and Max blend displacement, bump mapping and a BRDF by how much detail a pixel
resolves [23] [C]. Artists build macro, medium and micro from big to small [P]: columns and trims, then frames and
profiles, then cracks, AO and dirt in colour and roughness [29]; or three or four stone sizes over a noise, with a random
mask carried through the graph for per-element colour [30]. Below a pixel, a detail moves from geometry to the normal
map, then to roughness and tone (`layering.md`, Toksvig).

| Scale | Size | Carries | UE5 carrier | Godot 4 carrier | Ours |
|---|---|---|---|---|---|
| Macro | 5–30 m | tone, washing, orientation, upkeep | low-res masks, vertex colour, world noise, per-instance random | the same | covered: 50 px/m layers, presets |
| Meso, large | 0.5–5 m | bays, stains, streak systems, growth fronts | masks revealed against tiling; mesh decals for sourced marks | masks; Decal for hero marks | covered |
| Meso, small | 1–50 cm | dirt in corners and recesses, edge bands, chips, flakes, rust patches, hole clusters | baked AO, cavity and curvature × grunge; distance fields at runtime; geo-decals | baked maps in UV2 or vertex colour; Detail mask; Decal | **partial**: 1 px edge rows, coarse shelter; no AO, cavity or curvature |
| Micro | 0.5–10 mm | grain, pores, flecks, paint film edges, rust flakes | tiling sets at 1,000–2,000 px/m; detail maps | Detail albedo and normal | **partial**: coat set and splats; no flecks, no pores on paint, no peel lips |
| Sub-pixel | under 1 texel at the view | sheen, micro-roughness | roughness (Toksvig) | roughness | covered (`layering.md`) |

- **Neither engine displaces our relief.** Godot's height is a ray-marched illusion with no real geometry [22] [C]. Unreal
  needs Nanite tessellation for real displacement (`r5-texture-layering.md`). So relief under about 5 mm (lips, flakes,
  pits, rust scale) ships as normal, AO and roughness. It must still be authored as height, so that those maps can be
  derived from it [I].
- **Godot's Detail slot** blends a detail albedo and normal through a mask, by Mix, Add, Sub or Mul, on UV2 or
  triplanar [22] [C]. That is the engine-side form of "a mask revealed against detail", for one layer per material [I].

## 2. Mask generators driven by mesh maps

| Tool | Reads | Key controls | Gives |
|---|---|---|---|
| Painter Mask Editor [1] | 2 textures, world-space normal (WSN), position, thickness, curvature, AO, micro height and normal | per input: opacity, blend mode, blur, balance, contrast; curvature in Edges, Cavities or Dual at 7 scale bands; micro-detail AO radius and depth | any combined mask |
| Painter Dirt [2] | curvature, AO, WSN, position, custom grunge | Dirt Level, Dirt Contrast, Grunge Amount and Scale, Edges Masking (by curvature) | dirt in crevices, on edges and on flats |
| Painter Metal Edge Wear [3] | WSN, position, curvature, AO, grunge | Wear Level and Contrast, Grunge Amount and Scale, Edges Smoothness, AO Masking ("keep occluded areas from receiving weathering"), Curvature Weight | edge wear |
| Painter Dripping Rust [5] | curvature, AO, position | Rust Spreading, Spreading Smoothness, Rust Contrast, Drips Intensity (length), Drips Smoothness, Position axis | rust spread with drips under gravity |
| Painter Position and World Space Normals [6][7] | position, WSN | a gradient per axis (Right to Left, Top To Bottom, Front to Back), each with invert and blend mode | ground dirt, dust on faces that look up |
| Sampler Rust [9] | the material, curvature | Rust Spread, Edge Influence, Spread Smoothness, Affect Metal Only, Peel Scale, Peel Normal, Peel Height, Drips Intensity, Orientation and Length | rust with peel relief and drips |
| Houdini Bake Geometry Textures 2.0 [10] | low, high and cage meshes | AO (samples, max distance); curvature (samples, scale, max distance, bias); cavity (samples, max distance, bias); thickness; edge; rounded-edge normal; position; world normal | the maps |
| Curvature COP [11] | a height or normal layer | output Curvature, Convexity or Concavity; Gaussian, mean or principal curvature; kernel size | convex or concave masks at a chosen scale |
| Mask by Feature SOP [12] | geometry | directional, shadow, AO and combined masks; max angle; blur iterations; remap ramp | a point `mask` |
| Labs Physical AO [13] | geometry | modes Physical AO, Valleys, Peaks, Dirt Buildup; neighbourhood radius (also the trace distance); blur iterations and step | AO, concavity, convexity, noisy dirt |
| Labs Edge Damage [14] | geometry | curvature with noise, voxel displacement, mask attribute | eroded edges; also "masks for shading" |

- **The shared recipe** [I, from 1–14]:
  ```
  dirt = levels(a·(1-AO_r) + c·concave_s + u·up(N) + g·grad_y, contrast) × (1 - e·convex_s) × grunge
  wear = levels(k·convex_s × (1 - m·(1-AO_r)) × grunge)
  ```
  - `e` is Painter's Edges Masking and `m` its AO Masking [2][3].
  - The radii come in at least two scales: crevices of 2–10 mm (the micro-detail AO radius [1]) and recesses of 0.1–1 m
    (the max distance of Mask by Feature, Labs Physical AO and the bake [10][12][13]).
- **Gravity terms use position and normal, not UVs.**
  - Dust takes the world normal of faces that look up. Ground dirt and splash take a bottom-up position gradient. Drips
    are a sweep along one position axis [5][6][7] [C].
  - Unreal artists project streak textures world-aligned, so streaks run down whatever the UVs do [18, snippet].
- **Contact grime at runtime.** Unreal's `DistanceToNearestSurface` reads mesh distance fields (it needs them generated,
  and reads about 0 on a shadow-casting surface itself) [19, snippet]; it can drive dirt or moss where meshes meet [I].
  Godot has no equivalent, so contact dirt there must be baked [I].
- **Houdini 22 ships no edge-wear or dirt COP.** Its grunge COPs (Drips, Leaking Streaks, Rust, Rusty Surface, Moisture,
  Mold Spots, Wipe Trails and others) are image-space noises [15] [C]; the masks come from Bake Geometry Textures or SOP
  measures, combined in Copernicus (`maskcombine`) [I]. One user found Labs Edge Damage slow [14, snippet].
- **Curvature fails at module borders** (`rE-concrete.md`, snippet). Measure convexity and AO on the assembled facade,
  not on each kit piece [I].

## 3. Height-blended layering and paint over substrate

**Covered elsewhere:**
- Height blending (R1, R2), the coverage-preserving edge rule, the stack order, and "wear switches whole material sets"
  (`layering.md`; the `large-scale-texturing` SKILL.md).
- The danchi layer stack (`weathering-cracks-edges-damage.md` §5.3), outermost first:
  - on walls: top coat, earlier top coats, spray-tile main coat, sealer, concrete skin (L\* 55–68), then aggregate below
    about 5 mm;
  - on steel: top coat, older colours, primer (red-brown, orange or grey), then rust.

**How pros cut the paint** [P]:
- **Separate parts** (inner concrete, holes, outer panels, rebar, worn paint), each detailed without extracting masks;
  warps break the paint edge and heavy warps make islands; the peel edge is blur minus mask, a "smooth transition of the
  edges going upwards", and the same on cracks near peeled areas makes flakes [24].
- **Peeled shapes** from Voronoi cells distorted by a mosaic node and blurred noise, with a shadow node in the height so
  the paint "seems to peel up at the edges" [33, snippet].
- **One decay slider** drives a cracked-and-peeling wall through custom bevel, high-pass and protrude-from-height nodes [28].
- **Edge wear on its own layer** above the paint, chunkier and placed where hits happen, not on every edge [33, snippet].

**How paint fails** [P, weak secondary 40]:
- Intercoat failure lifts sheets with clean edges off the previous coat, often over a chalky surface.
- Moisture failure goes down to the substrate near water sources, often with efflorescence.
- Danchi top coats chalk to matte within 10–15 years (`rE-concrete.md`), so both should show [I]: older colours where the
  top coat let go, and the main coat or concrete where water got behind it.

**Thicknesses** (`rE-concrete.md`): latex 25–76 µm a coat, elastomeric 300–500 µm, spray tile about 1 mm with peaks of
2–4 mm. At 1 mm/px a paint step is one pixel. It reads through its colour, a normal edge 1–2 px wide and the dirt
caught in it, not through its depth [I].

**A peel recipe for our compositor** [I]. P is the paint coverage at the fine grid (1 where paint remains), and b_r is
a blur of radius r:
```
h_paint = t·P + c·max(P - b_r(P), 0)       # t film thickness; r = 1-3 mm; c = 0.5-1.5 t where flakes lift
dirt   += d0·max(b_r(P) - P, 0)·below       # a dark line 1-2 mm wide on the exposed side, under the edge (gravity)
edge    = P·(P - b_1mm(P)) > 0              # the broken paint edge: +3-6 L*, the paint's unweathered body
```
The revealed layer brings its own albedo, roughness and height: the older coat, the main coat, or the flecked concrete
skin of §5. Later layers (the dirt film, growth) are then revealed against the new composite height (Summary, item 6).

## 4. Flow and direction

**Pro tools:** drips along a chosen position axis with length and smoothness [5], or with orientation and length [9];
leaks from Slope Blur over a band of spots (Foreman, `rE-concrete.md`); world-aligned projection for streaks
[18, snippet]; decals with leaks "in the correct flow direction" and dirt at the edges [31]; leak and edge decals where
modules meet (Embark, `r5-texture-layering.md`).

**Ours is ahead on placement:** sourced streaks, channels, band sampling for rivulets, and rust that flows along the
members and stains the concrete below the feet (`weathering-rules.md` G1, H4–H6, R3–R5; `rust_flow.py`).

**Gaps at 1 mm/px** [M, repo; I]:
- **Isotropic rust detail.** The rust tile is 15 mm and 60 mm blotches plus pits, so a run down a 16 mm baluster reads
  as a smear. Runs need a vertical rust-run tile, band-sampled like `streak`, 2–6 mm across and 60–300 mm along.
- **Wet paths keep the dry roughness.** Where water often runs, rust and dirt should be 0.1–0.3 smoother
  (`r3-believable-textures.md` §1).
- **Water does not part around obstacles** (post feet, bolts, chips) at the fine grid. A flow field taken from the
  capture's depth (down the slope, around bumps) would steer the runs [I].

## 5. Specks, flecks, aggregate, pits and pores

**Physics** [C]: fines under ~150 µm act as pigment and grains over ~500 µm show only where the skin is removed; drier
mixes, longer form contact and damp read darker, and GGBS gives a blue tinge [34]. Aggregate is 60–75 % of the volume
(80–85 % of the mass); fines are under about 5 mm, coarse aggregate typically 9.5–37.5 mm [35, snippet]. On a cut or
broken face each phase's area share equals its volume share (Delesse's principle).

**Pro practice** [P]: pores from Gauss spots through a tile generator, blended add/subtract (snippet); three or four
stone sizes with pixel noise for fines [30]; custom pore generators and subtle hue shifts toward brown, green and blue
(Remedy, `rE-concrete.md`); critiques asking for warm-cool variation, more albedo variation and "more shiny speckles"
[33, snippet]. Scans carry their pores and flecks at 4,096 px/m over 2 × 2 m, one old concrete at 9,752 px/m
[41, snippet].

**Covered:**
- Bug holes are 1.5–15 mm across and cover 0.3–1.2 % of the area. They cluster at the tops of lifts and are darker and
  rougher inside (`concrete.md`; `micro-noise.md`).
- Thin paint makes 2 mm holes more visible (`rE-concrete.md`). The thick spray-tile walls fill the holes, so the user's
  1 cm pits belong on thin-painted and bare elements: soffits, slab edges, stair cores and plinths.

**Proposed set** [I, sizes from the sources above]:

| Feature | Size | Cover | Contrast at full coverage | Where |
|---|---|---|---|---|
| Sand flecks, dark and cool | 0.3–3 mm; lognormal (σ_ln 0.5); N(>d) ∝ d^-1.5 | 0.5–2 % on an as-struck skin; 3–10 % on washed or abraded faces | ΔL\* −10 to −25; Δb\* −1 to −4 | all bare concrete; densest where the skin is washed (tops, windward corners, splash zone) |
| Light flecks | the same | a third of the dark count | ΔL\* +4 to +8 | the same |
| Pebbles | 5–20 mm (a 20–25 mm maximum is usual in building concrete) | 35–45 % of a broken face; a few % of a heavily eroded face | each pebble has its own hue and ±10 % value; the caps show over 20–50 % of their diameter | spall floors, chip floors, worn arrises |
| Bug holes | 2–15 mm; median 4–6 mm | 0.3–1.2 % | −40 % inside; roughness +0.14 (`concrete.md`) | formed concrete, and thin paint over it |

- At 1 mm/px a 0.5 mm grain covers a quarter of a pixel, so coverage alone turns a fleck "faint". The detail tile must
  carry each fleck's full contrast and let coverage do the rest [I].
- A kurtosis target of 5 or more on close-ups of bare concrete (photos measure 3.5–31, `rE-concrete.md`) checks that the
  specks are there.

## 6. Rust on coated steel

**Sequence** (`weathering-rust-water.md` §2): blisters; rust lifts the film (it takes 2–7 times the steel's volume);
flakes come off and expose steel or primer; the rust spreads.

**Under the film:** next to an exposed anode the paint turns cathodic and alkaline and loses its bond ahead of the
visible rust [38, snippet]; ISO 4628-8 measures the delaminated and the corroded widths around a scribe separately
[37, snippet]; filiform corrosion runs as threads under the film, lifting it in worm-like tracks, mostly cosmetic
[39, snippet].

**Pro practice** [P]:
- Rust shapes come from a cloud noise through a threshold. A duplicated rust with an adjusted threshold then outlines
  the first, for the "bubbling look" [25].
- Rust under paint "will bubble and chip it and eventually expose the bare metal", with separate levels for the amount
  of rust and the age of the metal [27, snippet].
- Structure comes before colour: breakup and the link between height and roughness first, then peeling paint, blended
  corrosion stages and dirt [26].
- Sampler's rust has peel scale, peel normal, peel height and drips [9]. Painter's spreads from curvature and AO, and
  drips along an axis [5].

**Colour, covered** (`weathering-rust-water.md` §6; rule R6):
- fresh lepidocrocite L\* ≈ 56; rust on the rails L\* 34–41; old and wet rust L\* 20–28;
- stain heads L\* 30–35 at hue 52–56°; tails L\* 45–50 at hue 68–75°.

**Proposed anatomy at 1 mm/px** [I; widths scaled from rust creep of 0.1–3.5 mm a year, `weathering-rust-water.md` §2]:

| Zone, from the inside out | Width | Albedo | Roughness, metallic | Height |
|---|---|---|---|---|
| Core: old, dense rust | the patch | L\* 28–36, hue 40–55°, C\* 12–20 | 0.85–0.95, 0 | +0.2–0.5 mm of flaking scale |
| Margin: fresh rust | 1–4 mm, on the advancing side and along wet paths | L\* 48–56, hue 55–70°, C\* 28–40 | 0.75–0.85; 0.5–0.7 on wet paths | +0.1 mm |
| Exposed metal or primer | 0.5–3 mm, on 30–70 % of the perimeter | grey steel with an orange haze of flash rust; or red-brown or grey primer | steel 0.35–0.55, 1; primer 0.6–0.8, 0 | minus the paint thickness |
| Blister halo | 2–8 mm | the paint, a little yellower; orange in its cracks | the paint's + 0.05 | domes 1–4 mm across, +0.1–0.3 mm |
| Intact paint | — | — | — | — |

Every patch over about 4 cm then has the old core beside the fresh margin: the user's "darker intense rust beside
brighter fresh wet rust".

## 7. Variation and breakup

- **Per instance.** Unreal has PerInstanceRandom and per-instance custom data on instanced meshes [20] [C]. Godot can use
  vertex colour as albedo, and world triplanar [22] [C]. Per-bay tint and world macro noise are covered (`concrete.md`;
  `large-scale-texturing`).
- **Two materials from one master.** Changing tint, roughness contrast, normal strength, tiling and UV crop was the
  cheapest breakup in a Megascans concrete scene [31] [P].
- **Roughness gets as much variation as colour.** Dopazo's windows start from per-window dirt with macro and micro
  noise, then edge dirt, then top-down and bottom-up gradients [29] [P].
- **Hue and saturation.**
  - Concrete colour varies with the fines, the water content, the forms and damp [34] [C]. Pros shift the hue subtly
    toward brown, green and blue (`rE-concrete.md`).
  - Our clean coat's clouding is a luminance factor only, and the coat tiles are grey [M, repo].
  - The colour tails of a weathered wall come from the colour families: the dirt's b\* shift, growth at C\* 10–26, rust
    at C\* 10–35 (`weathering-rules.md` I1, M2, R6). These are covered; the clean material's chroma is not.

## 8. Decals

**Types** [C]:
- **Projected deferred and DBuffer decals** change base colour, normal and roughness (covered,
  `r5-texture-layering.md`).
- **Unreal mesh decals** apply deferred-decal properties to their own geometry, so they wrap edges; they update the
  GBuffer or DBuffer after opaque geometry with no depth, give no shadows or proper occlusion, and must hug the surface
  (World Position Offset can adjust the offset) [16]. With Nanite the decal geometry goes on a separate non-Nanite mesh
  [17, snippet].
- **Godot decals** work in Forward+ and Mobile only. Albedo alpha masks the normal and ORM maps (Albedo Mix 0 gives
  normal-only marks); they have Normal Fade and Distance Fade, cost by screen coverage first, then count, and take no
  height and no custom shaders [21].

**Where decals go:**
- Decals take the hero 20 % of marks and the joins; tiling plus masks take the rest (covered, `large-scale-texturing`).
- New here: MachineGames' geo-decals [32] and Embark's edge decals both put grime and softening along joins and edges,
  which is where mesh maps would otherwise mark them [P].
- Our `wx_export.decal_list` exports only rust runs (0.08 m or longer) and cracks (0.30 m or longer) [M, repo].

## 9. What reads at each distance

At 1080p with a 90° horizontal field of view, one pixel spans d/960 m at distance d (`texturing-at-scale.md` §2) [I].

| Feature | Size | Spans 2 px at (1080p / 4K) | Below 1 px beyond (1080p / 4K) | Carrier |
|---|---|---|---|---|
| fleck, paint lip, hairline | 1 mm | 0.5 / 1.0 m | 1.0 / 1.9 m | tiling detail; beyond that, tone and roughness |
| grain, small pore | 3 mm | 1.4 / 2.9 m | 2.9 / 5.8 m | tiling detail |
| bug hole, cluster of rust pits | 1 cm | 4.8 / 9.6 m | 9.6 / 19 m | detail + masks |
| chip, flake, rust margin | 3 cm | 14 / 29 m | 29 / 58 m | masks at 50 px/m (1.5 px) + detail |
| rust patch, corner dirt band | 10 cm | 48 / 96 m | 96 / 192 m | masks; mesh-map terms |
| stain, peel patch | 30 cm | 144 / 288 m | — | masks, decals |

- The 1:1 reviews at 1,000 px/m show every row, so every row needs its own carrier [I].
- A feature below a pixel must keep its mean effect. Pits and flecks that average away in the mips must leave their
  darkening and roughness behind (`layering.md`, specular aliasing; check T3) [I].

## 10. What a map-driven generator like ours lacks

1. **Geometry occlusion and curvature.** No AO, cavity, convexity or thickness term at either density. At 50 px/m
   corners get an inside-corner class and a 0.1–0.3 m damp band, recesses a shelter class (`weather_fields.py`:
   `layer_soiling`, the wetness classes). The crop capture saves `depth` and `P`, but `wx_hires.load_capture` reads only
   the class, steel, albedo and N [M, repo].
2. **No interplay between edge masking and AO masking.** Pro generators pull dirt off convex arrises and keep wear out of
   occluded areas [2][3]; our layers are independent masks composited in a fixed order [M, repo].
3. **No layer heights and no height cascade.** At 1 mm/px the height is only the coat relief, the joints and the break
   depth (`wx_hires`); deposits, peels, rust and growth add no relief. Each layer is revealed against its own detail
   tile, never against the composite below it, as Painter's anchor points allow [M, repo].
4. **No paint stack.** `peeling` has amounts by age and a hook in `composite()`, but no layer function builds it.
   `layer_wear` chips lerp to `old_paint` (85 %) or `substrate` × 0.85 (15 %). There is no primer on steel, no main-coat
   or sealer layer, and no paint-film crack network, though the research defines one (`weathering-cracks-edges-damage.md`
   C18) [M, repo].
5. **No rust anatomy.** No delamination ring, exposed metal or primer, blisters, rust relief or vertical rust-run detail.
   Wear, peeling and damage share one isotropic `chip` tile, rust one isotropic `rust` tile (`wx_hires.REFINE`) [M, repo].
6. **No flecks, pebbles or pores.** The coat and the bare concrete have no fleck or pebble layer. `wx_detail.splats`
   already draws clustered lognormal discs for splash specks and rust pits, and could make them [M, repo].
7. **No chroma in the clean coat.** `material.coat_cloud` is monochrome, and the coat sets are grey [M, repo].
8. **Few decal kinds.** Only rust runs and cracks become decals. There are no corner grime strips, peel patches, spalls
   or leaks [M, repo].

## 11. Recommendations for our skills and generator

Ranked. Gate rules go into `scripts/weathering/weather_rules.json`, which `rules_to_md.py` renders into
`procedural-materials/references/weathering-rules.md`. All numbers are [I] until they are calibrated on the photos.

| # | Finding | Why it matters | Concrete change | Skill file | Sources |
|---|---|---|---|---|---|
| 1 | Masks from geometry occlusion and curvature (principle covered in procedural-materials SKILL.md step 5; not in the facade generator) | the user's corners, recesses and top edges; pros start every dirt and wear mask here | **Bake per plane at 50 px/m:** AO at 0.3 m and 1 m max distance, cavity (concave, 2–5 cm kernel), convexity, faces that look up. **At the review density:** height-to-AO and curvature from the capture `depth`, at 2 mm, 1 cm and 5 cm kernels. **Weights:** soiling × (1 + 0.8 (1 − AO₀.₃)^1.5); growth wetness + 0.15 (1 − AO₀.₃). **New rule G7:** mean D within 0.15 m of a concave join (AO₀.₃ < 0.7) over the open wall 0.5–1.5 m away is 1.3–2.5, from E 10 | `weathering-rules.md` (G7); `weather-and-use.md`; large-scale-texturing SKILL.md (mask channels, capture) | [1]–[3], [10]–[13] |
| 2 | Paint as a stack, with a real peeling layer | "chipping and peeling exposing concrete" and "paint cracking" are absent | **Implement `layer_peeling`:** flakes 3–30 mm, area by ISO 4628-5 class (cracks note S14), clustered at water sources and joints. Intercoat failures show the older coat; moisture failures show the main coat or concrete. **Reveal** against a paint-crack cell tile: cells 1–3 mm for a top coat, 4–10 mm for a texture coat, with T-junctions (C18). **Lip and dirt line** by the §3 recipe. Each revealed layer is a full set | `layering.md` (paint stack); `concrete.md` (stack); `weathering-rules.md` (peel rules) | [24], [28], [33], [40]; cracks note §5.3, C18 |
| 3 | Rust in rings, and runs on the uprights | "bare metal around rust", "darker beside brighter rust", "rust streaks down vertical rails" | **Anatomy:** the §6 zones at the fine grid. **Runs:** a vertical rust-run tile, band-sampled, 2–6 × 60–300 mm, wherever rust lies on uprights below joints. **Wet paths:** roughness −0.1 to −0.3. **Rule R7:** at 1 mm/px, a ring of ΔL\* +10 or more against the rust on 30 % or more of the perimeter of each rust patch of 4 cm or more. **Rule R8:** L\* p90 − p10 ≥ 12 inside those patches | `weathering-rules.md` (R7, R8); `micro-noise.md` (rust rows); large-scale-texturing (detail tiles) | [5], [9], [25]–[27], [37], [38] |
| 4 | Flecks, pebbles and pits where the skin is gone | "darker, cooler flecks", "embedded pebbles", "bugholes about 1 cm" | **Tiles:** `fleck` and `pebble` from `wd.splats`, per §5. **Skin-removed mask:** washed × exposure, plus abraded arrises, the splash zone, spall and chip floors, and areas of lost paint. **Bug holes** through thin paint on soffits, slab edges and stair cores. **Rule J3:** fine-band kurtosis ≥ 5 on close-ups of bare concrete | `concrete.md` (parameter rows); `micro-noise.md`; `weathering-rules.md` (J3) | [34]–[36], [41]; `concrete.md`, `rE-concrete.md` |
| 5 | A height cascade between layers | marks sit in the material when dirt fills steps, chip floors and rust pits | **Heights:** each layer adds its own (peel lip, rust scale, deposit thickness, growth cushion). **Reveal:** later layers read the running composite height, not only their own tile | large-scale-texturing SKILL.md (edge rule: a note on composite height); `layering.md` | `r5-texture-layering.md` §3 (anchor points) |
| 6 | Chroma in the clean coat | "more saturation variety" | **RGB clouding:** make `coat_cloud` RGB, using the same fields to shift chroma ±0.4–1.0 C\* and hue ±2–4°. **Dark clouds** lerp up to 40 % toward the cool grey in `concrete.md`. **Repaint patches** step 1–3° of hue. **Rule J1b:** chroma std 0.3–1.2 C\* at 10 cm–2 m on the clean albedo | `concrete.md` (values: covered); `weathering-rules.md` (J1b) | [34]; `concrete.md` |
| 7 | Edge masking and AO masking | dirt on bright arrises and wear in shadowed corners are both signs of a generator | **Masking:** dirt × (1 − e·convex); wear × (1 − m·(1 − AO)). **Keep N5** (the washed arris row). **Strengthen the 2–15 cm band** under tops with no drip, which is where the user's "top edge" dirt sits | `weathering-rules.md` (a note on N5); procedural-mesh-damage `streak_mask` (covered: the 5–15 cm band) | [2], [3] |
| 8 | Decal kinds for joins and hero marks | carries corner and edge dirt into engines that cannot compute it at runtime | **New kinds** in `DECAL_KINDS`: `corner_grime` (strips 10–30 cm wide along concave joins where AO < 0.6), `peel_patch`, `spall` and `leak` (at sill ends). **Unreal:** non-Nanite mesh decals that hug the surface. **Godot:** Decal nodes for up to about 50 hero marks, mesh decals for the rest | large-scale-texturing SKILL.md (Engine hookup); `texturing-at-scale.md` | [16], [17], [21], [32] |
| 9 | A distance table per feature size | says which carrier each detail needs | add the §9 table | large-scale-texturing `texturing-at-scale.md` | §9 |
| — | Height blending, the edge rule, sourced streaks, band sampling, rust by water, per-bay tint, roughness from causes, film modulation | — | covered | `layering.md`; `large-scale-texturing`; `weathering-rules.md`; `r3-believable-textures.md` | — |

## 12. Unchecked

- **Not searched** (budget gone): the Designer mask-generator pages (helpx 403); Painter's AO and Thickness generator
  pages; an official page for Unreal's WorldAlignedBlend; Godot instance uniforms; the rock types of Japanese aggregate
  (andesite against sandstone); the ISO 4628-2 blister classes and the ISO 4628-8 formulas.
- **Could not read:** the Polycount threads and the ArtStation pages of Pascarella and McDermott (403); the Springer
  erosion paper (login); NPS Preservation Brief 10 (PDF saved, no text extractor on this machine); the MachineGames talk
  (abstract only); the Notion notes on Unreal layered materials.
- **No pro source found** for fleck sizes and densities in shipped materials, a measured width of the exposed-metal ring
  around rust, or lip heights in pro peel graphs. The §5 and §6 tables are inference from aggregate grading, creep rates
  and the zones above.
- **Not measured:** chroma of the photo walls (J1b), enrichment in recesses on the photos (G7), kurtosis of bare concrete
  (J3). Each rule needs calibration before it binds. The Fab densities (4,096 and 9,752 px/m) came from a search
  summary; which listing gives which was not checked.

## 13. Sources

1. Adobe, Substance 3D Painter, Mask Editor generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/mask-editor
2. Adobe, Painter, Dirt generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dirt
3. Adobe, Painter, Metal Edge Wear generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/metal-edge-wear
4. Adobe, Painter, Curvature generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/curvature
5. Adobe, Painter, Dripping Rust generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dripping-rust
6. Adobe, Painter, Position generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/position
7. Adobe, Painter, World Space Normals generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/world-space-normals
8. Adobe, Painter, Generators overview — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/generator
9. Adobe, Substance 3D Sampler, Rust filter — https://experienceleague.adobe.com/en/docs/substance-3d-sampler/using/filters/wear-and-finish/rust
10. SideFX, Bake Geometry Textures COP — https://www.sidefx.com/docs/houdini/nodes/cop/bakegeometrytextures.html
11. SideFX, Curvature COP — https://www.sidefx.com/docs/houdini/nodes/cop/curvature.html
12. SideFX, Mask by Feature SOP — https://www.sidefx.com/docs/houdini/nodes/sop/maskbyfeature.html
13. SideFX, Labs Physical Ambient Occlusion 1.1 — https://www.sidefx.com/docs/houdini/nodes/sop/labs--physical_ambient_occlusion-1.1.html
14. SideFX, Labs Edge Damage 1.0 — https://www.sidefx.com/docs/houdini/nodes/sop/labs--edge_damage-1.0.html ; forum, Day 26 (snippet) — https://sidefx.com/forum/topic/95170/
15. SideFX, What's new in Copernicus, Houdini 22 — https://www.sidefx.com/docs/houdini/news/22/copernicus.html
16. Epic, Using Mesh Decals — https://dev.epicgames.com/documentation/en-us/unreal-engine/using-mesh-decals-in-unreal-engine
17. Unreal forum, Mesh decals and Nanite (snippet) — https://forums.unrealengine.com/t/mesh-decals-and-nanite/1359353
18. Unreal forum, world-aligned rain streaks (snippet) — https://forums.unrealengine.com/t/make-texture-always-orient-to-one-direction-rain-streaks/75245 ; https://forums.unrealengine.com/t/streaking-in-world-aligned-material/2712226
19. Epic API, DistanceToNearestSurface; forum on its requirements (snippet) — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UMaterialExpressionDistanceToNea- ; https://forums.unrealengine.com/t/distancetonearestsurface-material-node/37003
20. Epic, PerInstanceCustomData expression (Python API, 5.1) — https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialExpressionPerInstanceCustomData?application_version=5.1
21. Godot, Using decals — https://docs.godotengine.org/en/stable/tutorials/3d/using_decals.html
22. Godot, Standard Material 3D — https://docs.godotengine.org/en/stable/tutorials/3d/standard_material_3d.html
23. Becker & Max, Smooth transitions between bump rendering algorithms, SIGGRAPH 1993 — https://history.siggraph.org/?p=118607
24. Tammekänd, Generating painted old concrete in Substance, 80.lv, 9 April 2018 — https://80.lv/articles/generating-painted-old-concrete-in-substance/
25. Miragliotta, Realistic weathered train exterior in Substance 3D Designer, 80.lv, 22 January 2025 — https://80.lv/articles/realistic-weathered-train-exterior-recreated-with-substance-3d-designer
26. Anquetil (Ubisoft Montpellier), Desirable Patina, 80.lv, 24 September 2026 — https://80.lv/articles/desirable-patina-how-to-make-realistic-rust-in-3d
27. Pascarella, rusted painted metal in Substance Designer (ArtStation; snippet) — https://neilpascarella.artstation.com/projects/xk3x2
28. Taylor, Cracked paint material, 80.lv, 22 August 2018 — https://80.lv/articles/cracked-paint-material-for-substance
29. Dopazo, Procedural materials from big to small, 80.lv, 22 June 2017 — https://80.lv/articles/procedural-materials-from-big-to-small
30. Jacobs, Tips and tricks: material production in Substance, 80.lv, 18 June 2018 — https://80.lv/articles/tips-and-tricks-material-production-in-substance
31. Loginova on Somov, World in concrete: using Megascans materials smartly, 80.lv, 24 July 2019 — https://80.lv/articles/003qxl-world-in-concrete-using-megascans-materials-smartly
32. Katarzis, Tran & Vaz Figueiredo (MachineGames), Aged by Adventure, GDC 2026 (abstract) — https://gdcvault.com/play/1036059/Aged-by-Adventure-CraftingtheTime-Worn
33. Polycount: peeled-paint thread; painted metal over bare metal; concrete and stone critiques (all snippet; which comment says what was not checked) — https://polycount.com/discussion/comment/2217968 ; https://polycount.com/discussion/comment/2598402 ; https://polycount.com/discussion/comment/2117612 ; https://polycount.com/discussion/comment/2341247
34. Heidelberg Materials UK, Colour variation in concrete — https://www.heidelbergmaterials.co.uk/en/ready-mixed-concrete/technical-information/colour-variation
35. FHWA, aggregate share of concrete; NPCA, fine aggregate (snippet) — https://www.fhwa.dot.gov/publications/research/infrastructure/structures/97148/app2.cfm ; https://precast.org/wp-content/uploads/092823_magazine_Inc-May-June-2017.pdf
36. Int. J. Concrete Structures and Materials, rainwater erosion of concrete walls (snippet) — https://link.springer.com/article/10.1007/s40069-016-0177-0
37. ISO 4628-8:2012, delamination and corrosion around a scribe (catalogue; snippet) — https://standards.iteh.ai/catalog/standards/iso/f0a2ea00-5ed8-4c1b-a425-291c7a025786/iso-4628-8-2012
38. Frontiers in Materials 2019, coating delamination at defects (snippet) — https://www.frontiersin.org/articles/10.3389/fmats.2019.00192/epub
39. University of Trento, review of filiform corrosion on organic-coated steel, 2024 (snippet) — https://iris.unitn.it/handle/11572/456352
40. Paint peeling: intercoat against substrate failure (weak secondary guides; snippet) — https://compositepaint.pages.dev/fix/peeling-paint ; https://www.pcimag.com/blogs/14-pci-blog/post/107180-how-to-fix-common-paint-problems-on-historic-buildings
41. Fab, Megascans concrete listings: texel density and scan area (snippet) — https://fab.com/listings/a44f9d31-288d-410e-9194-d9f74b89a609 ; https://www.fab.com/listings/9a58e2ab-22c2-4985-bcfd-fafb19ba323a

Repo files read at fa8d46a: `scripts/weathering/` (`weather_fields.py`, `wx_hires.py`, `wx_detail.py`, `material.py`,
`wx_export.py`, `README.md`), `examples/danchi/weathering/crop_capture.py`, the three skills and their references, and
the research notes named in the text.

## 14. Actions

Statuses as `scripts/research_actions.py` reads them (round J). Numbers are §11's.

| # | Action | Status |
|---|---|---|
| 1 | Corner, recess and top-edge masks from the geometry | done (rules G7 and F5; `weather_fields.plane_zones` finds inside corners and recesses from the capture depth; paint-rust-concrete.md) |
| 1b | AO, cavity and convexity bakes per plane | parked (the depth terms meet G7 and F5; revisit when a kit piece or a new building needs AO-driven masks, or G7 fails on one) |
| 2 | Paint as a stack, with a peeling layer | done (`weather_fields.layer_peeling`; the flake and checking tiles in `wx_hires.py`; rules P1, P2, P3c) |
| 3 | Rust anatomy, runs on the uprights, dark beside bright | done (`rust_flow.py` runs, colour variation and bare metal; `wx_hires.py` anatomy; rules R7, R8, R9, R7c) |
| 3b | Wet paths 0.1-0.3 smoother | parked (no rule weathers roughness yet, audit rank 4; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 4 | Flecks, pebbles and pits where the skin is gone | done (`wx_concrete.py` tiles; rule J3) |
| 5 | A height cascade between layers | parked (paint-rust-concrete.md "Not yet checked"; revisit with the roughness and height carriers, audit rank 4) |
| 6 | Chroma and hue in the clean coat | done (`material.coat_tint`; rule J1b) |
| 7 | The 2-15 cm band under tops | done (rule F5's band) |
| 7b | Dirt off bright arrises, wear out of shadowed corners | parked (with 1b) |
| 8 | Decal kinds for joins and hero marks | parked (needs the engine export; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 9 | A distance table per feature size | done (paint-rust-concrete.md "What reads at each distance") |
