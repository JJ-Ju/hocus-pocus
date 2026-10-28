# rE: realistic concrete textures in 3D

2026-10-28. This is a research spike on one material: concrete, the dominant surface of the
1960s–80s danchi generator. In several test rounds the walls read as stucco or plaster. Of the
v2 close-up the user said: "I expected something more like concrete."

The report has two parts:
- **Part 1** covers the craft independent of the tool: real concrete, its features and their
  sizes, how texture artists build it, values, and why it reads as plaster.
- **Part 2** translates that into Houdini 22 (Copernicus, MaterialX, Karma) and a game engine.
  It covers two prototype texture sets, rendered and compared with photographs, and the node and
  parm traps verified in 22.0.466.

The distilled skill reference is `.claude/skills/procedural-materials/references/concrete.md`.
Scripts and previews are in `docs/redesign/evidence/concrete/`.

**Tags.**
- **[S: key]** is a sourced number. The key points into the source list at the end:
  - A: construction and materials;
  - B: Japanese practice;
  - C: CG craft.
- **[I]** is my inference or arithmetic.
- **[I, measured]** is a number measured in this round, from our renders or the reference
  photos. The scripts that produce it are named alongside.
- **(snippet)** means a research agent saw the number only in a search-engine summary.
  **(secondary)** means it came from a copy that is not the publisher's, or from another
  author's summary. Treat both as weaker evidence.

Three research agents gathered the sources with web search, on construction, on Japanese
practice and on CG craft. I read the danchi photos and the renders myself, and I ran all the
Houdini work. Two primary sources were behind paywalls: ACI 347.3R-13 and the PCI architectural
precast manual. Their numbers come from unofficial copies or reviews and are marked as such.

---

## Summary

### Why our walls read as stucco

The v2 and v6 walls have five problems, listed below. Together: the wrong texture, at the wrong
scale, applied the wrong way, with none of the logic that makes a wall read as cast.

1. **The grain is the loudest thing on the wall.** On a plain wall crop of the v2 close-up, the
   1.5–4 px band carries 10× the contrast of the 12–48 px band. Its amplitude spectrum rises
   toward fine scales: the slope over 3–48 px is +0.25. Every real danchi wall crop measured had
   a falling spectrum, with slopes from −0.12 to −1.45 (median −0.37). Grain-to-form ratios ran
   0.4–2.9 [I, measured: `analyze_walls.py`, 11 crops].
   - **Stucco is a single dominant band of isotropic grain.**
   - **Concrete is dominated by larger forms:** panels, lifts, mottling, stains. Its grain is
     faint (see "Spectral targets" in §1.3).
2. **The grain is stationary and Gaussian.** On the v2 parapet the local grain strength varied
   by 7 % across the crop (coefficient of variation 0.07), with kurtosis 2.9. Photographed walls
   gave 0.12–0.68 (median 0.31) and kurtosis 3.5–31 (median 7.8) [I, measured]. Real coats are
   thicker in some places and thinner in others, and they carry specks, pits and crack lines.
   Those make heavy tails.
3. **Its scale and relief are too large.** The v6 spray-tile recipe used:
   - mesa cells of 11 and 24 mm (`examples/danchi/src/py/tex_build.py`);
   - 3 mm of relief, with the normal exaggerated 2× when it was made and then scaled by 0.6 in
     the shader.

   After two or three repaints, real spray tile has bumps of about 5–15 mm. Its average coat is
   about 1 mm and its peaks 2–4 mm [I from coverage rates, S: B1]. Repaints round and fill the
   relief [S: B29, B30; I]. The danchi in our photo set are 40–60 years old and repainted, so
   their texture is gentle [S: B3, B31; I].
4. **The concrete logic is missing.** These things are what make a coated wall read as a coated
   *concrete* wall, and none of them were in the renders:
   - the formwork panel grid and tie plugs that telegraph through paint [S: A10];
   - PC or construction joints and their sealant [S: B15];
   - floor-line construction joints [S: A24 (snippet)];
   - repair patches;
   - sealed crack lines with injection seats every 200–300 mm [S: B6, B42 (snippet)];
   - roller laps of about 800 mm from repaints [S: B43 (snippet)];
   - soffits, slab edges and copings in different finishes from the wall [S: B2].

   The v6 spray covered every face in one grain. A trowel or spray texture with no module is,
   by definition, plaster [S: C30, C57; I].
5. **Colour and roughness were flat.**
   - **Colour:** the base colour was one albedo per face, with only ±6 % world noise (v6
     `materials.py`).
   - **Roughness:** a constant 0.86.
   - **Reference:** real walls carry per-panel and per-pour tone, laps, patches, dirt held in
     the troughs, and a roughness that follows those causes [S: A26, A11, C44].
   - **A Copernicus trap makes it worse.** `fractalnoise` around 0.5 has a std of only 0.076.
     Albedo factors written as if the noise filled 0–1 give about a quarter of the intended
     variation. That is how our own first pass came out with 2–10 cm variation 10× quieter than
     the photographs (§2.5, §2.7 trap 22) [I, measured].

### When the stucco look is correct

It is correct, but only as one layer.
- **Japanese standards really do contain stucco.** JIS A 6909 names a *thick* finish family
  スタッコ (stucco), sprayed or scraped. Its 複層 (multi-layer) family, 吹付タイル ("spray
  tile"), is a raised bump pattern, often flattened (凸部処理) [S: B1, B26, B27].
- **They were common on danchi.**
  - 1960s blocks: render plus paint, or cement or resin リシン (lithin, a sand-textured thin
    coat).
  - 1970s–80s blocks: spray tile.
  - Most blocks have since been recoated with a flexible micro-elastic coat that keeps or
    softens the old pattern [S: B2, B4, B27].

  So at arm's length a danchi wall *should* show a sprayed texture.
- **What makes it wrong in our renders** is not the existence of grain but four things:
  - its amplitude and scale;
  - its uniformity;
  - its being the only signal;
  - its being on every face.

  The v3 close-up the user liked had the balance about right: fine grain at 1.5 L\*, about
  2.4 L\* of larger-form variation, and a slope near 0 [I, measured]. It still lacked joints,
  patches and laps.

### What fixes it

Build every concrete or coated wall in this order. The skill reference has the recipes.
1. **Choose the finish per element** (§1.1, table 1).
2. **Lay out the module first:** panels, ties, lifts, joints.
3. **Add the cast logic in the macro tiling set:**
   - per-panel tone;
   - layer lines;
   - clustered bug holes;
   - seams with fins or paste loss;
   - tie plugs;
   - one crack;
   - a few runs.
4. **Put coating grain in a separate detail set,** at its true size and relief, with its
   strength driven by a macro "coat" mask.
5. **Drive colour and roughness from the same masks.** Dirt sits in the coat's troughs and in
   bug holes, lighter mortar in plugs, smoother paint in patches and laps.
6. **Put the building's story in the shader:** world macro value, damp base, streaks from
   sources. Hero marks go in decals.

The two prototypes in Part 2 do this.
- **Bare formed concrete.** A 3.6 m tile at 4096 px, with konpane panels, a P-cone grid,
  clustered bug holes, layer lines, a crack and runs.
- **Repainted spray tile on concrete.** A 3.6 m macro set at 2048 px plus a 0.6 m detail set at
  1024 px. It has panel and tie telegraphing, laps, patches, a sealed crack and a hairline.

Both were rendered on a wall in Karma, next to the round-6 recipes in the same rig (§2.5). The
results:
- **Spectral slope:** `frame_critique.py` measured +0.45 and +0.51 on the round-6 spray. The new
  coat measured −0.37 and −0.48, the formed set −0.69 to −0.88. Natural images sit at −0.85 to
  −1.5.
- **Crop statistics:** on wall crops, both new sets now sit inside the range of the eleven photo
  crops for spectrum slope and grain-to-form ratio.
- **What is left:** their grain amplitude and heavy-tailed specks are still at or below the low
  end of the photographs. Weathering, specks and decals have to supply that, not a stronger
  grain.

---

## Part 1: the craft, independent of the tool

### 1.1 Real concrete first

#### Finishes, and which danchi element carries which

**Table 1. Finishes and how each reads.**

| Finish | Where on a 1960s–80s danchi | What defines its read | Key sizes |
|---|---|---|---|
| **Bare cast-in-place on plywood (打ち放し, ordinary grade)** | Stair cores and their soffits, retaining walls, plinths, the inside of spalls, many end walls of utility blocks, site walls. Rarely whole facades: early UR walls were rendered and sprayed [S: A31, B2] | Module grid of panels and ties; seams with steps or fins; layer lines; bug holes clustered toward lift tops; cloudy panel-to-panel tone; vertical bleed and sand streaks; tie-hole halos | Panels 900 × 1800 mm konpane, also 600 × 1800 [S: B22, A13]. Ties at 450 or 600 mm, 6–8 per panel [S: B17, A17]. P-cone 30–45 mm, plugs about 2 mm recessed on exposed work [S: A15, B19]. One pour per storey, about 2.96 m [S: A14] |
| **Architectural 打ち放し (Ando style)** | Not on danchi; a reference point | The same grid made perfect: 6 ties per 900 × 1800 panel in 2 × 3, open cone recesses, crisp seams, very uniform tone [S: C51, A16] | Ando 900 × 1800 with 6 ties [S: C51] |
| **Board-formed (杉板本実)** | Rare on danchi; some entrance walls and planters | Boards 75–150 mm wide with grain, knots and fins between boards; each board a slightly different depth and tone [S: A20, C52] | Boards 8–12 cm, about 105 × 24 mm stock [S: A20] |
| **Steel-form, precast (PC) panels** | Wall-type precast (W-PC) walk-ups from about 1965, the 1970s SPH standard designs (about 120,000 units); balcony parapets and spandrels [S: B7, B8] | Smooth, often slightly glossy skin; uniform tone within a panel but visible panel-to-panel steps; air holes on vertical-cast returns; crazing on as-cast faces; regular joints with sealant [S: A44, A25] | PC joints 19–25 mm, sealant depth about half the width [S: A43]; one Sendai sheet prices 20 × 10 mm (snippet) [S: B14]. Crazing cells up to about 40 mm [S: A25] |
| **Painted concrete (thin film)** | Soffits, corridor walls, stair halls, repainted parapets | Everything in the concrete telegraphs: paint is 25–150 µm, while bug holes are 2–15 mm. Thin light paint makes 2 mm holes *more* visible [S: A46, A10] | Latex 25–76 µm a coat; elastomeric 300–500 µm [S: A46, A47] |
| **リシン (lithin, 薄付け thin coat)** | 1960s walls; soffits (軒裏) throughout [S: B2] | Fine sand-grit matte, almost no relief at 5 m; reads as a speckled, very matte paint; streaks and dirt show strongly | 1.0–1.2 kg/m² [S: B1]; grit about 0.3–1.5 mm [I] |
| **吹付タイル (spray tile, 複層 multi-layer)** | 1970s–80s walls and parapets [S: B2, B4] | Bumps 5–15 mm, often flattened (凸部処理), craters, a glossy or semi-gloss topcoat that chalks to matte [S: B26, B1; I] | Base ≥0.7 + pattern ≥0.8 kg/m²; tile gun with a 6–8 mm nozzle [S: B1, B28]; about 1 mm average, peaks 2–4 mm [I] |
| **スタッコ (stucco, 厚付け thick coat)** | Some 1960s–70s walls | Coarse sprayed or scraped relief, 5–10 mm [I]. Here the stucco read is correct | Main coat ≥1.5–3.0 kg/m² [S: B1] |
| **可とう形改修塗材 (micro-elastic repaint)** | Most repainted danchi since about 2000 [S: B2, B27] | Keeps or rebuilds the old pattern, softened. Applied by roller in なみがた (wave), smooth or ゆず肌 (citrus-peel); laps and patches show [S: B29, B30] | Repaint every 12–15 years [S: B31]; first repairs at 10–15 years [S: B4] |

**The danchi rule [I].** The building is concrete; almost everything you see is a coat on it.
- **The coat contributes:** grain, gloss and chalking.
- **The concrete contributes:**
  - geometry and joints;
  - formwork telegraphing, where the coat is applied directly (from the late 1970s; earlier
    walls had about 20 mm of render first [S: A31, A32]);
  - cracks, spalls, efflorescence and the repairs to all of them.

  Bare concrete appears in stairs, soffits, plinths, retaining walls, spall cavities and the
  cut faces of damage.

**Bare vs painted, visually [I from the sources above and the photo set].**

| Property | Bare formed concrete | Painted or sprayed concrete |
|---|---|---|
| Value | 0.20–0.40 linear when weathered; 0.40–0.55 fresh [S: C1, C3, C4, A48] | The paint's albedo: 0.55–0.68 linear for off-white [I from Munsell V 8–8.8, S: B33] |
| Hue | Near neutral; cement, sand and water/cement ratio shift it a few degrees warm (sand) or cool (blue-grey paste) [S: A26, C6] | The paint's hue, low chroma (Tokyo base colours mostly C ≤ 1–2 at V ≥ 8.5) [S: B34]; repaint campaigns differ by a hue step |
| Variation | Cloudy: per pour, per panel, per layer; lighter with form reuse; darker clouds where paste is dense [S: A2, A12, A14] | Low-contrast: laps, patches, scaffold lifts, chalking; dirt in the coat's troughs |
| Micro relief | Smooth skin with pores, sand streaks and grain transfer; erodes to sand on washed faces [S: A6, A37] | The coat's pattern, softened by repaints |
| Roughness | Gloss falls with each form reuse; weathered skin is matte [S: A14] | Fresh semi-gloss topcoat, chalking to matte in 10–15 years [S: B1, B4] |
| Story | Efflorescence, rust from ties and shallow bars, biofilm, washing streaks | The same, plus peeling, blistering and repainted ghost rectangles |

#### Features, sizes and frequencies

**Table 2. Features of formed concrete.**

| Feature | Size | Frequency, coverage | Where | Visual | Sources |
|---|---|---|---|---|---|
| **Bug holes (blowholes, surface voids)** | Usually ≤15 mm across [S: A6, C46]; holes over 10 mm made good [S: A10]; under 10 mm hemispherical [S: micro-noise.md] | Void ratio SVR1–SVR4: ≤1.2, 1.0, 0.6, 0.3 % of a 610 mm frame, largest 19, 16, 9.5, 6 mm [S: A2, A3 (secondary)]. DBV P1–P4: ≤1.2, 0.9, 0.6, 0.3 % of a 500 × 500 mm field, counting pores of 2–15 mm [S: A11]. Measured walls 0.4–3 % [S: A3]. Two frames 300 mm apart can fall in the best and worst class [S: A4] | Upper part of vertical lifts; under inclined forms; impermeable forms; past the vibrator's reach [S: A6, A2]. 10× denser in the top 30–40 cm of a pour in one photo study [S: micro-noise.md] | Dark pits with sharp rims, sizes power-law; patches of holes next to bare areas | A2–A6, A10, A11 |
| **Tie holes (P-cone)** | 30–45 mm across, 25–70 mm deep cone [S: A15]; US cones 25 mm [S: A21] | Grid of 450 × 600 or 600 × 600 mm [S: B17, A17]; 6 or 8 per 900 × 1800 panel | On the panel grid, about 150 mm in from edges [S: A17] | A mortar plug about 2 mm recessed, lighter and finer, with a hairline ring [S: B19; I]. Absorbent facings leave a circular shadow around each tie [S: A2] | A2, A15, A17, B19 |
| **Panel seams, offsets and fins** | Offsets 25/13/6/3 mm by class SI1–SI4 [S: A2]; DBV paste leaks ≤20 × 10, ≤10 × 5 and ≤3 mm for T1–T3, fins ≤5 and ≤3 mm [S: A11] | Every panel edge | Vertical every 900 mm, horizontal every 1800 mm on konpane | Thin lines with a step; dark sand-streaked lines where paste leaked; raised fins elsewhere | A2, A11 |
| **Layer lines** | One line per placed layer, about 0.5 m [S: A12] | Every layer, faint | Horizontal, wavy (concrete is placed in heaps) [I] | A dark horizontal line, plus colour change and voids along the boundary [S: A6] | A6, A12 |
| **Cold and construction joints** | ≥20 mm wide, 10 mm deep grooves at floors (snippet) [S: A24]; offsets CJ1–CJ4 25/13/6/3 mm [S: A2] | One per storey pour | At floor levels | A groove or line with honeycomb or colour change; grey mortar runs below it if not washed off [S: A6, A11; I] | A2, A6, A24 |
| **Honeycombing** | 50–300 mm patches [S: micro-noise.md, I] | Rare | Congested rebar, joint leaks, lift bases [S: A6] | Stony, paste-poor cavities showing aggregate | A6 |
| **Laitance, sand streaks** | Vertical streaks | Occasional | Where bleed water ran up the form face [S: A6] | Paler, sandy, rougher vertical streaks | A6 |
| **Formwork imprint and grain** | Grain relief well under 1 mm on plywood [I]; board liners 8–19 mm deep (architectural, exaggerated) [S: C52] | Every panel; fades with coated faces | Grain along the panel's long side | Rough lumber and CDX transfer grain and wood-sugar staining, 2–3 reuses; MDO slight grain, 5–10; HDO none, 10–20; steel none, 100+ [S: A2]. Gloss falls and brightness spread rises with reuse [S: A14] | A2, A14, A18 |
| **Colour variation between pours** | Panel or pour scale | Every pour | Different placements, form absorbency, release agent, water/cement ratio | A w/c change of ±0.02 shows on dark concrete [S: A12]. Lower surface w/c is darker; more hydration and slag cement are lighter [S: A26]. FT2 allows "large, even light/dark variation"; FT3 only slight clouding [S: A11]. L\* standard deviation ≤1.0 counts as very good [S: A53 (snippet)] | A11, A12, A26 |
| **Patching and repairs** | Spot to 0.25 m² and up [S: B6] | Holes over about 10 mm [S: A10]; spalls ≥0.01 m² repaired urgently [S: A31] | Tie holes, spalls at slab edges, nosings and rail posts [S: B6] | Smoother, slightly different-coloured rectangles. Polymer mortars dry darker (secondary) [S: A51]. "Repair marks stand out" [S: B6] | A10, A31, A51, B6 |
| **Carbonation** | 25–50 mm after 50–66 years; 0–7 mm behind about 19 mm of render [S: B32] | Everywhere | Deepest where bare and dry | Not visible without indicator [I]. It causes the spalls: worst on balcony and stair soffits within 200 mm of the edge; cover there averaged 13.6 mm [S: A32] | A32, B32 |
| **Efflorescence and leaching** | Thin bands and drips; lime stalactites about 1 cm a year (snippet) [S: A35] | Rare, at water paths | Cracks, joints, soffits, below tie holes and drains | White, rough, low saturation; invisible on white concrete and strong on dark [S: A12] | A12, A35, A36 |
| **Cracks** | Crazing cells ≤40 mm [S: A25]; wall shrinkage cracks 1.5–3 m apart, a third to two-thirds of the height (snippet) [S: A28]; widths 0.05–0.4 mm [S: A27] | Repair thresholds: 0.2–1 mm injected, ≥1 mm U-cut [S: A31, B6] | From opening corners [S: A29]; control joints ≤3 m [S: B13] | Dark hairlines that dirt fills; repaired ones as sealed lines with port dots | A25, A27–A29, B6, B13 |
| **Dampness, wet/dry boundaries** | Wetting lowers albedo by 0.23 on average [S: A48] | Base splash zone at least 15 cm [S: A41]; rain-exposed walls held 1.1–5.2 % moisture, north and east higher [S: A32] | Base, below sills and joints, north faces | Darker, smoother, ragged-edged fronts; algae where it stays wet | A32, A41, A48 |
| **Stains and soiling** | Run-off film about 0.25 mm, ≤0.9 m/min [S: A37] | Streams recur at the same places | Ends of sills, horizontal and vertical junctions, below fixings [S: A37] | Dark "dirt washing" when new, pale "white washing" later [S: A37]. Coloured concretes fell from about L\* 90 to 63–72 in 24 months of biofilm [S: A40] | A37, A40 |

### 1.2 How artists build it, tool by tool

**Substance Designer.** These are the named breakdowns with concrete-specific techniques.
- **Remedy, *Control*.**
  - About 50 concrete materials, about 75 % of the tileables, authored at a 4 × 4 m world
    scale.
  - Small custom generators for pores, cracks, micro-roughness and peeling.
  - Height built large to small from a 0.5 grey base, with one height-to-normal at the end.
  - A "wood veins" generator for board-formed concrete.
  - Many subtle hue shifts toward brown, green and blue from cement and gravel.
  - An albedo range check [S: C6].
- **Mark Foreman (CD Projekt RED).**
  - Keep any one detail layer to no more than about 60 % of the surface.
  - Keep a finished plain concrete as a "seed" for new concretes.
  - Mask or warp every new layer by the existing height.
  - Wood grain from anisotropic noise blurred and blended at 0.06.
  - Leaks from Slope Blur in Max mode with a linear gradient, seeded from a band of spots
    [S: C21, C22].
- **Charlie Foreman (ex-Naughty Dog).** Build from the inside out: wood, concrete, wire. Each
  component gets its own branch and is merged by Height Blend over the full 0–1 range. Colour is
  blocked with flat colours, then masked by AO, normal and curvature [S: C23].
- **Curt C. Smith, Daniel Swing, Rosen Kazlachev: cracks.**
  - Cells, Fractal Sum, Directional Warp and Edge Detect, limited by grunge.
  - A second Slope Blur at 0.02 for thin sharp edges.
  - Flood Fill to Gradient for a random angle per piece [S: C18, C19, C24].
- **Enrico Tammekänd: painted old concrete.**
  - Separate layers: inner concrete, holes, 2 × 3 outer panels, rebar, paint.
  - A raised lip at paint edges from blur minus mask.
  - Heavy warp so the paint breaks into islands.
  - "Break it off more" cured his too-uniform paint [S: C20].
- **Adam Crespi, architectural course.**
  - 4 × 8 ft form panels in a 4 × 2 layout.
  - Tie patterns referenced to Ando, Kahn and Hadid.
  - Bug holes subtracted from the height [S: C25].
- **Massive (*The Division 2*).** About 450 materials. Shaders read RGB masks for rust, dirt
  and scratches [S: C11].

**Substance Painter.**
- **Anchor points** let a painted height drive generators [S: C28].
- **Curvature edge wear fails on modular wall borders,** which have no curvature. Use position
  or gradient masks there (snippet) [S: C57].
- **Studios keep Painter for unique props** and Designer for tileables [S: C6, C7, C11].

**Photoshop.**
- **Photo-sourcing:** offset by 50 %, then clone and heal the seams [S: C29].
- **High pass:** a large-radius high pass on mid-grey strips low-frequency lighting before
  tiling [S: C29]. It also strips the real mottling, so concrete needs that back as a separate
  macro layer [I, S: C44].

**Blender.**
- **Critique:** a node concrete built from noise, Voronoi and Musgrave "looks like a stucco
  application" because of its fine lines (Blender Artists) [S: C30].
- **Musgrave** was merged into Noise Texture in 4.1 [S: C31].
- **Displacement:** 0.02–0.05 with adaptive subdivision is one tutorial's figure for formwork
  [S: C53].

**Scans (Megascans, Poly Haven, Unity, DICE).**
- **Capture:**
  - cross-polarised flash;
  - about 300 photos per 2 m²;
  - a colour chart in the plane of the surface;
  - white balance from the grey patch;
  - 16-bit output [S: C15].
- **Lighting:** Quixel captures under controlled light so it needs no destructive delighting,
  and ships 2 × 2 m surfaces [S: C16].
- **Repetition:** a 1–2 m scan repeats on a 4–8 m concrete wall; repetition is the main problem
  (snippet) [S: C57].
- **Combining scans with procedural detail:**
  - adjust scans into PBR range;
  - check them against a PBR checker that runs the same in the engine;
  - layer in-engine by height and painted masks [S: C7].

**Unreal layering.**
- **The Order: 1886 (Ready at Dawn):** a tiered library, 90–95 % tiling materials, up to 4
  vertex-blended height-aware runtime layers, and runtime decals [S: C8].
- **Gears of War 4:** layers cooked offline for 60 fps [S: C10].
- **A concrete wall breakdown (Brynielsson):**
  - clean and damaged tiling concretes blended by HeightLerp and vertex paint;
  - decals for dirt, cracks and moss [S: C26].
- **DBuffer decals** write base colour, normal and roughness, not AO [S: C33].
- **Detail texturing** costs 2+ samples [S: C34].
- **WorldAlignedTexture** needs WorldAlignedNormal [S: C35].
- **THE FINALS** (Embark) places edge-softening, grout and leak decals where modules meet
  [S: C12].

### 1.3 Noise and pattern recipes

**Table 3. Which noise builds which feature.**

| Feature | Scale | Basis | Orientation | Clustering |
|---|---|---|---|---|
| Panel grid | 0.9 × 1.8 m | tile generator, per-tile random value and height | — | per panel |
| Tie holes | 30 mm on 450 × 600 | tile pattern of circles, conical profile, per-hole depth | — | a few open, a few with runs |
| Bug holes | 1.5–12 mm | Poisson cells (Worley) kept where random < density; radius power-law; profile 2t − t² | none | density = floor + cause × cluster, the cause being the top of each layer |
| Layer lines | every 0.5–0.6 m | sawtooth ramp warped by 1.4 m noise; a line where the sawtooth wraps | horizontal, wavy | broken up by noise |
| Mottling, clouds | 0.07–0.6 m | fBm at 2–3 sizes, thresholded clouds | none | amplitude by panel wear |
| Bleed, sand streaks | 10 × 200 mm | fBm stretched 18× vertically | vertical | in zones |
| Plywood grain | 3–4 mm × 90 mm | fBm stretched 26× along the panel, shifted per panel so it breaks at seams | along the long side | strength per panel |
| Spray tile | 3–11 mm blobs | Worley domes, two or three size modes, hex lattice for the big ones, flattened, blurred for repaints | none | spray-pass noise at 0.1 m |
| Cracks | hairline, 1–2 px | a warped line (ramp + distance), or Worley borders with T-junctions | by cause | from corners and openings |
| Runs below sources | 2–4 cm wide, 0.15–0.3 m long | one-sided streak blur, tapered, wavering, broken up | down | per source |

- **Directional noise for formwork.** Stretch fBm along the board or veneer direction and break
  it at every seam: grain must stop at board edges, and adjacent boards differ in depth and
  offset [S: C22, C6; I]. Foreman blends a blurred anisotropic noise at 0.06 [S: C22].
- **Cluster, not uniform grain.** Use cause × large cluster × medium × small, then threshold;
  80 % of a layer on 15–25 % of the area; a 10–20 % floor elsewhere [S: realism.md]. Detail
  layers stay under about 60 % coverage [S: C21].

**Spectral targets.**
- **Natural images** have an amplitude-spectrum slope of about −1 [S: frame_critique.py
  sources, Field 1987]. Our photo crops measured −0.12 to −1.45 at 3–48 px [I, measured].
  Renders with dominant grain measured +0.06 to +0.61 [I, measured].
- **Concrete micro-roughness** is self-affine below a roll-off near 2 mm: the height power
  spectrum falls with slope about −3.8, a Hurst exponent of about 0.9 (one measured surface)
  [S: C45]. Each finer octave should then carry about 2^−0.9 ≈ 0.54× the height amplitude of
  the one above [I]. At game texel density (about 1–2 mm per texel) that band is at or below
  one texel. What a texture can show is the discrete structure: holes, seams, grain, aggregate
  and mottling [I, S: C45].

### 1.4 Layer stack and blending

The order is base, macro, variants, wear, dirt and film, then decals [S: layering.md]. For
concrete specifically [I]:
1. **Substrate height:** panels, steps, waviness, grain, micro.
2. **Cast defects:** seams, fins, ties, bug holes, crack. These are subtracted from height and
   reused as masks.
3. **Cast colour:** per-panel tone, clouds, layer lines, bleed streaks, halos, plugs.
4. **Coat,** if any: its own height (the detail set) and colour, with a coat-thickness mask.
5. **Weather, in the shader:** world macro value, damp base, washed tops, streaks from sources.
6. **Hero decals:** leaks, spalls, patches, graffiti.

The blending rules:
- **Height blend** layers with physical thickness. Dirt fills low first; plaster survives on
  highs.
- **Use the R1 reveal** `t = 1 − a(1 + w); m = smoothstep(t, t + w, h)`, or the max-height trick
  for two or more layers [S: layering.md, C37].
- **Masks:**
  - AO and cavity for dirt in voids and coat troughs;
  - curvature for chips and edge wear (on unique pieces only, not modular borders [S: C57]);
  - world height for the damp band and lifts;
  - position and primvars from the generator for streak sources [S: SKILL.md].
- **Scans plus procedural:** use the scan for the base albedo and micro, and procedural masks for
  the logic (joints, ties, lifts). Layer by height, never by plain lerp [S: C7, C8; I].

### 1.5 Colour

**Table 4. Concrete colour values.**

| State | Linear | sRGB 8-bit | Source |
|---|---|---|---|
| Fresh concrete, measured through a polariser | 0.51 | about 189 | [S: C1] |
| Concrete (physicallybased.info, citing Lagarde) | 0.51 | about 189 | [S: C2] |
| New concrete | 0.55 | about 196 | [S: C3] |
| New traditional concrete | 0.40–0.55 | 170–196 | [S: C4] |
| Aged concrete | 0.20–0.30 | 124–149 | [S: C4] |
| White cement concrete | 0.70–0.80 | 216–230 | [S: C4] |
| Smooth lab mixes, solar reflectance | 0.41–0.77 (mean 0.59) | — | [S: A48] (solar, not visible) |
| Grey mixes, formed bottom face | 0.25–0.41 | — | [S: A48] |
| Danchi off-white paint, about 2.5Y 8.5/1 | 0.58–0.66 | 200–212 | [I from Munsell, S: B34] |

How each cause moves the albedo:
- **Exposure changes** (solar, [S: A48]):
  - weathering −0.06;
  - soiling −0.05;
  - abrasion −0.19;
  - wetting −0.23;
  - hydration +0.08.
- **Fresh concrete** is dark and glossy at stripping and lightens within about a week [S: A16].
- **Slag cement** is lighter [S: A50 (snippet), A26].

**Warm and cool, and how much hue drift is realistic.**
- **What drives it:** the cement colour and the sand. Dark sands darken as the paste erodes
  [S: A37]. Remedy shifts subtly toward brown, green and blue [S: C6].
- **Within one wall:** keep hue drift to about 1–3° per panel or pour and 2–4° at macro scale.
  Chroma stays very low (C\* 1–4) [S: realism.md (est.); I]. Our formed prototype lerps 0–40 %
  toward a blue-grey (0.272, 0.282, 0.288) in the dark clouds, against a warm grey (0.305,
  0.300, 0.283) base. That is a hue spread of about 20–30° at C\* of only about 1.5–3 [I].
- **Value variation,** measured on the final formed base colour as the std of a band-pass, in %
  of the mean [I, measured]:
  - 0.5–2 cm 2.8;
  - 2–10 cm 3.6;
  - 10–50 cm 2.5;
  - 0.5–1.8 m 2.8;
  - per-panel means 4.1;
  - overall 8.0;
  - p1–p99 0.24–0.35 linear around 0.30.

  The world macro value adds ±6 % at 5–15 m in the shader. Colour uniformity class FT2 allows
  that much [S: A11]. This is a target worth stating as measured bands: `fractalnoise` factors
  mislead, because the noise's std is only 0.076 (§2.7, trap 22).

### 1.6 Roughness and normal

**Roughness.**
- **Calibrated data is sparse and inconsistent:**
  - 0.5 [S: C2];
  - 0.50–0.74 from a forum chart [S: C57];
  - 0.75–0.95 dry from a weak source [S: C65].
- **Gloss measurements:**
  - concrete cast against coated plywood measured 31–35 gloss units at 60° on first use, and
    12–14 by the fourth use on site [S: A14];
  - the lab mix with a water/cement ratio of 0.30 measured about 74 [S: A14];
  - gloss was lowest at the bottom of each lift [S: A14].
- **Guidance [I]:**
  - fresh formed skin about 0.55–0.7;
  - weathered formed face 0.75–0.85;
  - sand streaks, paste loss and abrasion 0.85–0.95;
  - bug-hole interiors 0.95;
  - damp −0.05–0.15;
  - paint: chalked 0.75–0.85, fresh semi-gloss 0.55–0.7, sealant beads −0.1.

  Keep a within-material spread of about ±0.05–0.1, driven by causes, not noise [S: C44,
  realism.md].
- **Our prototypes:** formed p1–p99 0.76–0.85, spray 0.74–0.81 [I, measured].

**Normal and height.**
- **There are no calibrated normal-strength numbers.** Critiques name "normal too strong" and
  "normal pushed to compensate for lighting" [S: C57].
- **Derive the normal from height in metres** at the physical slope, × 1.0–1.5 [I]. Real
  depths:
  - tie recesses 2–25 mm;
  - panel steps up to 3–13 mm by class (we use ±1.2 mm);
  - bug holes up to about 13 mm deep (the ACI patching threshold);
  - board grain 1–3 mm;
  - spray tile about 1 mm average after repaints [S: A2, C46, C52; I].
- **Our v6 spray** used 3 mm of relief × 2 at derivation × 0.6 in the shader. That is an
  effective 3.6 mm on 11–24 mm cells, about 4× the 0.9 mm used for a repainted coat here [I, from
  `tex_build.py` and `materials.py`].

### 1.7 Why concrete reads as plaster

The collected critiques say:
- "looks like a stucco application" for a fine-lined procedural concrete [S: C30];
- too much high-frequency detail [S: C57];
- soft blobby edges and soft cracks read as mud [S: C57];
- a single hue reads as cardboard [S: C44];
- missing macro variation is the main cause of fake concrete [S: C44];
- normal too strong [S: C57].

The synthesis [I, from S: C57, C44, C30]:
- **Plaster** is a trowel or spray band of isotropic grain, soft edges and even tone.
- **Concrete** is defined by the mould: a periodic grid, anisotropic grain, ties, sharp arrises
  and chips, clustered holes, lifts, and geometry-aware staining.
- A material with only isotropic noise reads as plaster at any noise quality.

The grain statistics behind the summary were measured on plain wall crops with
`analyze_walls.py`. The JSON is `wall_grain_stats.json`, under
`docs/redesign/evidence/concrete/`. Columns:
- **slope:** amplitude-spectrum slope at 3–48 px;
- **fine/broad:** std of the 1.5–4 px band over the 12–48 px band;
- **grain:** fine-band std in L\*;
- **kurt:** fine-band kurtosis;
- **cv:** coefficient of variation of the local fine-band std;
- **aniso:** x/y gradient energy of the fine band.

**Table 5. Grain statistics of wall crops** [I, measured]:

| Crop | slope | fine/broad | grain L\* | kurt | cv | aniso |
|---|---:|---:|---:|---:|---:|---:|
| v2 close-up, spray parapet | **+0.25** | **10.4** | **4.8** | **2.9** | **0.07** | 0.86 |
| v6 bay, spray parapet | +0.37 | 0.93 | 2.7 | 21 | 0.90 | 0.80 |
| v6 bay, parapet 2 | +0.61 | 1.32 | 1.4 | 72 | 0.69 | 0.86 |
| v3 close-up, parapet (liked) | +0.06 | 0.62 | 1.5 | 5.8 | 0.23 | 1.00 |
| photo bay_02, sprayed back wall | −0.22 | 2.49 | 1.7 | 7.8 | 0.31 | 0.95 |
| photo bay_02, sprayed wall 2 | −0.32 | 1.46 | 0.8 | 3.5 | 0.12 | 0.89 |
| photo bay_01, balcony parapet | −0.12 | 2.93 | 3.1 | 18 | 0.68 | 0.36 |
| photo weathering_07, painted wall | −0.37 | 1.56 | 1.1 | 11 | 0.27 | 0.98 |
| photo weathering_02, end wall with joints | −0.75 | 1.45 | 0.8 | 31 | 0.56 | 1.06 |
| photo weathering_01, bare stained concrete | −1.45 | 0.41 | 1.4 | 5.5 | 0.29 | 1.10 |
| photo weathering_03, bare box | −1.15 | 0.60 | 0.9 | 5.8 | 0.37 | 1.07 |

Caveats:
- The crops are small (110–520 px).
- Their scales differ: about 1.5–6 mm per pixel.
- JPEG compression removes some fine grain from the photos.
- The v6 figures include sun-shadow edges.

The robust signal is two-sided:
- **Where the renders sit:** the fine-to-broad slope is at or above 0.
- **Where every photo sits:** the slope is below 0.

The v2 close-up is also an outlier on all the other columns.

**Table 6. Diagnostic: why it reads as plaster** (the reference repeats this as a checklist).

| Symptom | Cause | Fix |
|---|---|---|
| Even bumpy grain everywhere | one isotropic band dominates; spectrum flat or rising | macro forms first; grain amplitude 0.5–1.5 L\*; check the slope is negative |
| Bumps visible from 10 m | blob size or relief too large; normal exaggerated | true sizes (3–11 mm, about 1 mm relief); normal at the physical slope × 1–1.5 |
| Stationary grain | one amplitude across the wall | a coat or wear mask modulating the detail; cv ≥ 0.2 |
| No module | no panels, ties, joints or lifts | lay out the grid; telegraph it through coats |
| One tone per face | no per-panel or per-pour colour | per-panel ±4–6 %, clouds, layer lines, laps, patches |
| Constant roughness | roughness as one value | roughness from the same masks; ±0.05–0.1 |
| Soft V-groove seams | seams made by blurring an inset tile | 2 mm gaps with a 1–1.5 mm step or a fin; dark paste-loss bands |
| Same grain on every face | one material for walls, soffits, copings and edges | soffits lithin or smooth paint; copings and slab edges smooth or bare; walls spray |
| Dirt as grey multiply | — | lerp toward soot, biofilm or rust colours; dirt fills coat troughs and voids |
| Even bug holes | uniform scatter | clustered at lift tops, power-law sizes, 0.3–1.2 % cover |

### 1.8 Texel density and tiling at game scale

- **Texel density.** 512 px/m for distant work, 1024 px/m for close first-person [S: C41]. The
  danchi contract is 512 px/m (`examples/danchi/README.md`). Control authored its
  architectural tileables at 4 × 4 m [S: C6].
- **Tiling breakup:**
  - macro masks at several scales multiplied into albedo and roughness [S: C66, C44];
  - detail maps tiling 4–10× over the base and mean-neutral [S: layering.md];
  - hex tiling (Mikkelsen; free Unreal, Houdini and Godot ports) [S: C38];
  - height-lerped vertex layers [S: C8, C26].

  **Never hex-tile a formwork set:** its grid must stay registered to the building [I].
- **Decals** carry tie holes, leaks, cracks, spall rims, patches and grout at module joins
  [S: C8, C12, C26, C33]. Godot decals take albedo, normal and ORM but not height; Forward+
  clusters 512 elements by default [S: C39].
- **Vertex colour or masks** for 2–4 runtime layers [S: C8, C11].
- **How many sets:** Control had about 50 concretes [S: C6]. For one danchi estate I would use
  3–5 base concretes and coats, 1–2 concrete trims, and a decal atlas, all from one seed graph
  [I, S: C21].

---

## Part 2: the same in Houdini 22

All the work below ran headless in hython 22.0.466 (Indie):
- from an empty working directory;
- with a fresh `HOUDINI_USER_PREF_DIR` under the round-E scratch folder;
- without touching the running Houdini sessions or the HocusPocus tools.

The scripts are in `docs/redesign/evidence/concrete/`:

| Script | Runs in | Does |
|---|---|---|
| `cc_lib.py` | hython (exec'd) | the `G` graph class: copnet with res, wrap and b32; `U(m)` metres to image units; maths helpers (add, sub, mul, div, min, max, lerp, scale, remap, thr, pw, absval, blur_m, rand, fractal); `arr` and `stats` readback through `CopNode.layer().allBufferElements()`; `write` with the right encoding |
| `build_formed.py` | hython | bare formed concrete, 3.6 m tile, `hython build_formed.py <out> 4096` (169 s, of which 80 s is PNG writing) |
| `build_spray.py` | hython | spray-tile coat: macro 3.6 m at 2048 and detail 0.6 m at 1024 (under 10 s) |
| `render_wall.py` | hython | Karma CPU render of one set on a 14.4 × 5.4 m wall with MaterialX materials, writes EXR and .npy |
| `tonemap.py` | python 3 | fixed-exposure filmic tone map to JPG under 400 KB, captions and pairs |
| `make_sheet.py` | python 3 | contact sheet of a set: maps, a full-resolution crop, a grazing-lit crop, a 3 × 3 repeat |
| `analyze_walls.py` | python 3 | the grain statistics of Table 5 |

The PNGs (about 140 MB at these sizes) stay out of the repo. Regenerate them with the build
scripts:

```
hython build_formed.py <tex> 4096
hython build_spray.py <tex> 2048 1024
hython render_wall.py <tex> <out> formed|spray|v6spray|v6concrete close|bay|graze overcast|sun 1280 48
python tonemap.py <out>/<frame>.npy <frame>.jpg --exposure 1.7     # 2.2 for sun
python analyze_walls.py <refs_dir> <out> "label=<render.jpg>:x0,y0,x1,y1" ...
```

Run hython from an empty working directory with a fresh `HOUDINI_USER_PREF_DIR`. A
`types.py` in the working directory crashes hython.

### 2.1 Architecture

**One graph per set.** Each set is one `copnet` with these network defaults:
- `setres` with `res1`/`res2`;
- `setborder` with `border` wrap, so every noise and shape tiles;
- `setprecision` with `precision` b32.

**Heights in metres.**
- **Build:** height is built in metres throughout, so the normal can use the physical slope
  (`heighttonormal` `scale` = 2 / tile × exaggeration).
- **Normalise:** only at the end, with the range written to `*_meta.json`.
- **AO:** `heighttoambientocclusion` uses `heightscale` 2 / tile on the same metric height.

**The masks are the material's outputs too.**
- **Formed:** R tie discs, G voids, B seam band; the placement-layer phase in its own file.
- **Coat:** R coat thickness (detail strength), G repair patch, B cracks and sealant bead; the
  lap and lift overlap in its own file.

  These are what the runtime shader reads to put dirt in voids, seams and troughs, and to
  modulate the detail.
- **Why RGB:** RGB, not RGBA, because of two alpha traps (§2.7).

**Per-element randomness** comes from `tilepattern` or `worleynoise` ids through `randommono`,
with its `seed` input wired to the id and a different `seed` parm for each use. The streams are
independent: correlation −0.04 between seeds 0 and 17 [I, measured].

### 2.2 Prototype A: bare formed concrete

The graph is `build_formed.py`, with 249 COP nodes: the helpers make one node per operation.
Each step is a Part-1 feature at its real-world size.

1. **Panels.** `tilepattern` stackbond 2 rows × 4 cols: 900 × 1800 mm konpane, `inset`
   U(2 mm).
   - **Per-panel randoms from the id:** height offset ±1, tone, wear, grain strength, grain
     offsets.
   - **Seam band:** `feather` (`unitdist` U(12 mm)) inverted.
   - **Seam character:** a coarse breakup picks, per stretch of seam, either a fin (+0.8 mm,
     about 2 mm) or a paste-loss band (−0.6 mm, about 8 mm, darker and rougher).
2. **Ties.** `tilepattern` 6 × 8 (450 × 600 mm) circles, `scale` 0.030/0.45 (30 mm), drawn as a
   radial gradient with 1.2 % position jitter.
   - **Shape:** disc = remap 0–0.02; conical wall = remap 0–0.35.
   - **Depth:** 2–10 mm (power 1.6, most shallow). About 7 % are open at 22 mm.
   - **Colour:** plugs lighter by 3–13 %, with a hairline ring −18 %.
   - **Halos** −3.5 % (70 % of ties) or +2 % (10 %). They are made inside the disc, then
     blurred 35 mm, so the per-tie choice survives (§2.7, invalid ids).
3. **Placement layers.**
   - **Phase:** a vertical `ramp` with `cycles` 6 (0.6 m) and `method` repeat, warped ±60 mm by
     a 1.4 m noise through `distort`.
   - **Line:** min(phase, 1 − phase) < 0.012, broken up by noise, at −3.5 % value.
   - **Bug-hole cause:** phase².
4. **Bug holes.**
   - **Cells:** `worleynoise` with 10 mm cells.
   - **Density:** floor 0.010 + phase² × cluster × broad zones (0.06–0.28) + cluster × 0.04. The
     cluster is a 0.22 m fractal thresholded at 0.6; the broad zones a 0.6 m fractal.
   - **Keep:** threshold(density − rand(id)).
   - **Radius:** (0.08 + 0.34 × rand^2.5) × (0.8–1.35 by cluster) cells, so 1.6–12 mm.
   - **Rims:** irregular, from a 1.2 mm distort of `dist1`.
   - **Profile:** 2t − t², with depth 0.6 × radius.
   - **Result:** 0.57 % void cover at 4096, within SVR2–SVR3 [I, measured].
5. **Crack.** A horizontal ramp warped by a 0.25 m fractal (5 octaves). |x − 0.612| < 0.8 mm
   gives the line, limited to 8–95 % of the height and broken by noise: −0.4 mm, −30 % value,
   +0.08 roughness.
6. **Relief.**
   - **Grain:** a 3.5 mm fractal stretched 26× vertically (`elementsizetype` 1), offset per
     panel by a `distort` whose `dir` input is a `channeljoin` f2 of two panel randoms, so it
     breaks at every seam. ±0.15 mm × the panel's grain strength.
   - **Waviness:** ±0.8 mm at 0.7 m.
   - **Micro sand:** ±0.06 mm, doubled in sandy zones.
   - **Panel steps:** ±1.2 mm, blurred 1.5 mm.
7. **Colour value** (relative):
   - panel ±6 %;
   - mottle: factor 0.22 on a 0.32 m noise (1.7 % std) × wear;
   - clouds −7 %;
   - marbling: factor 0.04 (0.3 % std);
   - vertical bleed streaks: factor 0.05 (0.4 % std), too faint to see;
   - panel frame darkening −3.5 % (some edges);
   - layer lines −3.5 %;
   - paste loss −5 %, fin +2 %;
   - halos, plugs and ring as above;
   - voids −40 %, crack −30 %;
   - sand +2.5 %;
   - pores and specks at 4 mm and blotches at 3.5 cm, × a clustered envelope (0.4–1.4). These
     use factors of 0.35 and 0.5 on a `fractalnoise` whose std is only 0.076, so they add 2.7 %
     and 3.8 % std (§2.7, trap 22);
   - × AO remapped to 0.82–1.

   The factors are multipliers on the noise, not its range. The measured result per scale band
   is in the results table below.

   Then × a warm grey (0.305, 0.300, 0.283), lerped 0–40 % toward blue-grey (0.272, 0.282,
   0.288) in the dark clouds.
8. **Runs.** About 8 % of ties carry lime, toward (0.46, 0.46, 0.45) at up to 35 %, and about
   4 % carry rust, toward (0.22, 0.11, 0.05).
   - **Pick:** in the disc, then a 12 mm blur.
   - **Streak:** `streakblur` `dir` (0, −1), `bias` 1, `mode` on, 0.30 or 0.18 m long.
   - **Shape:** a 12 mm sideways waver through `distort`; × a 4×-stretched breakup.
9. **Roughness.**
   - base 0.77–0.83 by panel wear;
   - sand +0.06, paste loss +0.06;
   - dark clouds −0.04;
   - voids +0.14, plugs +0.04;
   - lime +0.10, crack +0.08.

**Results** (`formed_meta.json`) [I, measured]:

| Measure | Value |
|---|---|
| Height | −21.9 to +2.1 mm; p1–p99 −0.19 to +1.43 mm |
| Base colour | mean 0.300 linear (about sRGB 149); p1–p99 0.241–0.352; std 8.0 % |
| Base colour by band (std of a band-pass, % of mean) | 0.5–2 cm 2.8; 2–10 cm 3.6; 10–50 cm 2.5; 0.5–1.8 m 2.8; per-panel means 4.1 |
| Roughness | mean 0.796; p1–p99 0.762–0.850 |
| Void cover | 0.57 % |
| Tie cover | 0.20 % |
| Texel density | 1138 px/m at 4096; use 2048 (569 px/m) plus decals for game |

The wall in the render reads as formed concrete: panels, plugs, clustered holes, grain and a
crack (§2.5).

### 2.3 Prototype B: a repainted spray-tile wall that reads correctly

**Detail set** (`spraydetail`, 0.6 m at 1024, 1707 px/m):
- **Droplets,** in three Worley sizes:
  - 10.5 mm hex lattice, `jitter` 0.75, radius 0.40–0.70 cells, kept 80 %;
  - 6.2 mm, kept 55 %;
  - 3.4 mm, kept 50 %.

  Each droplet is a 2t − t² dome with a random height.
- **Flattening:** the big ones are capped at 0.6 (`clamp` `doupperlimit`), the 凸部処理 head-cut,
  and scaled by a spray-pass mask (0.09 m fractal, thresholded). Where a pass laid more
  material, droplets merge into plateaus; elsewhere small droplets sit on the base coat.
- **Two or three repaints:**
  - a 0.6 mm blur lerped in at 0.6;
  - plus 0.45 × a 3 mm blur, which part-fills the troughs.
- **Finish:** grit ±0.03; `equalize` stretch; relief 0.9 mm.
- **Outputs:**
  - height and normal at the physical slope;
  - cavity = stretched (1 − AO), mean 0.12;
  - top = height > 0.72, 4 % cover after repaint softening.

**Macro set** (`spraymacro`, 3.6 m at 2048):
- **Telegraphing from the concrete,** for a coat applied directly, from the late 1970s:
  - panel steps ±0.6 mm, blurred 4 mm by the coat;
  - tie dimples −0.3 mm.
- **Waviness:** ±1.2 mm at 0.7 m.
- **Repaint laps and lifts:**
  - roller laps every 0.9 m and 1.2 m (two campaigns) and scaffold lifts every 1.8 m;
  - each a 2–3.5 cm overlap band, wavered and broken by noise;
  - +0.15 mm, −1.2 % value, −0.02 roughness, +0.12 coat.
- **Repair patches:** two, 0.42 × 0.30 m and 0.26 × 0.62 m. Each is a rectangle from two ramps,
  warped edges, an edge ridge +0.3 mm, coat 0.45 (smoother), +0.8 % value, slightly warmer,
  −0.03 roughness.
- **Sealed crack:** a 10 mm bead +0.25 mm (blurred 2 mm) with injection seats every 257 mm
  (+0.5 mm, about 20 mm), and a sealant grey at 25 %.
- **Hairline:** an open hairline crack −0.2 mm, −25 % value.
- **Coat thickness:** 0.45–1.02 (mean 0.80), from a 0.3 m fractal, laps and patches.
- **Colour:** ivory (0.60, 0.585, 0.545) linear, about 2.5Y 8.5/1, varied by:
  - coat thickness;
  - 4 cm chalk and dirt blotches (factor 0.27, 2 % std) in a clustered envelope.

  The measured base colour (mean 0.585) has a std of 2.6 %:
  - 0.5–2 cm: 0.9 %;
  - 2–10 cm: 1.9 %;
  - 10–50 cm: 0.5 %;
  - 0.5–1.8 m: 0.1 %. The macro scale is left to the shader.
- **Roughness:** 0.78 ± 0.02 (chalked semi-gloss), and −0.10 on the bead.

Patch cover is 2.2 % [I, measured].

**The shader joins them** (§2.4):
- the detail normal goes on top of the macro normal through `mtlxbump`, at its true relief ×
  coat × 0.75 (`detail_k`);
- dirt goes into the detail's cavities: k = cavity × coat × (0.35 + 0.6 × cause);
- roughness gets +0.06 × cavity.

**What makes it read correctly** [I, from the renders in §2.5]:
- **The grain is the true size and depth,** and its strength varies with the coat and the dirt.
- **The concrete still shows:** panel lines and tie dimples catch raking light.
- **The repaint history shows:** laps, patches and a sealed crack.
- **The colour carries the weather:** dirt in the troughs where the cause field is high, a
  streak fringe below the top, a damp base.

  Under raking sun the coat is visibly bumpy, as real spray tile is. Under overcast it reads as
  a fine matte speckle, as in the bay_02 photo.

### 2.4 MaterialX for Karma

The materials are built by `render_wall.py` with `voptoolutils._setupMtlXBuilderSubnet` inside a
`materiallibrary` LOP. They are assigned with `assignmaterial` (`primpattern1`,
`matspecpath1`).

- **Coordinates.** The wall's `uv` is written in metres (`v@uv = set(@P.x + 7.2, @P.y, 0)`) and
  arrives as `st`. From it: `mtlxtexcoord` vector2, then `mtlxmultiply` vector2FA by 1/tile.
- **Images.** `mtlximage` `file`, `filecolorspace` srgb_texture for base colour and Raw for
  data. `signature` color3 for colour and masks, vector3 for normals: the menu lists only
  default and color3, but vector3 is accepted.
- **Normals.**
  - macro: the image into `mtlxnormalmap`;
  - coat detail: `mtlxbump` (`height` = detail height × 0.0009 m × coat, `normal` = the macro
    `mtlxnormalmap`).

  This bump chain rendered as expected in Karma CPU: the detail appeared exactly where the
  coat mask was high, which is how the alpha trap below was found.
- **Masks.** `mtlxseparate3c` (outr, outg, outb).
- **Per-panel world tint** (formed): `mtlxcellnoise2d` on `st` / (0.9, 1.8) (`mtlxdivide`
  vector2), remapped to 0.95–1.05. It stops the tile's panel tones repeating every 3.6 m.
- **Cause field** (`grime_field`):
  - **Streaks:** `mtlxposition` world through `mtlxfractal3d` stretched (9, 0.36, 9) and
    `mtlxsmoothstep` 0.02–0.32 gives streaks.
  - **Fall-off below the top:** they fade below the wall top over 0.3–2.5 m, with the reach
    varied by a 1.3 m noise.
  - **Clean stretches:** × a 0.16 cycles/m patch mask, so whole stretches stay clean.
  - **Max of:** these streaks; sheltered patches at 0.28 cycles/m (× 0.6); and a lower-wall
    gradient (× 0.35).
- **Weather.**
  - world macro value ±4–6 % at 0.11 cycles/m;
  - `mtlxmix` toward a soot colour by the cause field (formed (0.12, 0.115, 0.10) × 0.35; coat
    (0.20, 0.19, 0.165) × 0.18);
  - a damp band whose ragged front is 0.3–0.85 m up and 0.2 m wide, at 25–35 %, with −0.10
    roughness.
- **The round-6 recipes** (`v6spray`, `v6concrete`) get exactly the same story in the shader,
  so the comparison isolates the texture.

Karma parms used:
- `karmarendersettings`: `engine` cpu, `pathtracedsamples` and `samplesperpixel` 48,
  `resolutionx` 1280, autoheight from the camera's 16:9 aperture, `camera`, `picture`;
- `usdrender_rop` `execute`;
- `camera`: `tx`…`rz`, `focalLength` 35, `horizontalAperture` 36;
- `domelight::3.0`: `xn__inputsintensity_i0a`, `xn__inputscolor_ztar`/`g`/`b`;
- `distantlight::2.0`: the same names plus `xn__inputsangle_zta`.

Lighting:
- **Overcast:** dome 1.0, bluish white.
- **Low sun:** sun 3.2 at 38° elevation and about 70° off the wall normal, plus dome 0.32.

A render took 30–100 s at 1280 × 720 and 48 samples.

### 2.5 Previews, and comparison with the photos

**Images.** The previews are in `docs/redesign/evidence/concrete/`: 1280 × 720 JPGs, all under
400 KB. They share a fixed exposure per lighting setup (overcast × 1.7, low sun × 2.2) and the
same curve. The `v6` and `cop_lib` frames use the round-6 maps in the same rig, with the same
shader story, so the comparison isolates the texture.

| File | Shows |
|---|---|
| `01_formed_maps.jpg` | formed set: base colour, height, normal, roughness, masks, AO, a full-resolution crop, a grazing-lit crop, 3 × 3 repeat |
| `02_spray_maps.jpg` | coat macro set (same panels) and detail set (height, normal) |
| `03_formed_close_overcast.jpg` | formed concrete at 2.4 m, overcast |
| `04_formed_graze_sun.jpg` | formed concrete along the wall, low raking sun |
| `05_formed_bay_overcast.jpg` | formed at 9 m with the shader story: per-panel world tint, top fringe, sheltered patches, damp base |
| `06_spray_close_overcast.jpg` | repainted spray tile at 2.4 m, overcast |
| `07_spray_close_sun.jpg` | the same, low sun |
| `08_spray_bay_sun.jpg` | coat at 9 m, low sun, with the shader story |
| `09_compare_close_sun_v6spray_vs_new.jpg` | round-6 spray recipe vs the new coat, same rig |
| `10_compare_close_overcast_coplib_vs_formed.jpg` | `cop_lib.build_concrete_panels` vs the new formed set |
| `11_compare_bay_overcast_v6spray_vs_new.jpg` | both coats at 9 m |
| `12_formed_close_sun.jpg` | formed at 2.4 m, low sun |
| `13_spray_graze_sun.jpg` | coat along the wall, low sun, before the meso-albedo pass (§2.2, item 7) |
| `wall_grain_stats.json` | the numbers of Table 5 plus the new renders |

**What the frames show [I].**
- **The formed set reads as formed concrete at every distance.**
  - **Close:** konpane rectangles with 2 mm seams, P-cone plugs with a crescent of shadow,
    clustered bug holes, a vertical hairline, faint vertical grain, and cloudy mottling.
  - **At 9 m:** the per-panel world tint turns the panels into the checker of slightly
    different pours seen on real walls (weathering_03's bare box, weathering_01's facade), and
    the tile no longer repeats.
  - **Against `cop_lib`:** its panels look like tiles or plaster boards, with soft V-groove
    seams about 20 mm wide on 1.2 × 0.6 m panels and uniform pitting.
- **The coat reads as a painted wall on concrete,** not as stucco.
  - **Overcast:** a matte off-white with fine speckle, with panel lines and tie dimples barely
    showing, as on bay_02's back wall.
  - **Low sun:** a visible but small bump and the telegraphed panel steps.
  - **Against the round-6 spray in the same light:** that grain is about 2× larger and much
    deeper, and is the only thing on the wall. This is the stucco read the user objected to.
- **Still wrong:**
  - **Damp band:** too blobby and too even along the wall. It is a placeholder for the
    generator's damp primvar.
  - **Fringe:** without geometry it is the only source of streaks. Real walls take their
    streaks from sills, slab edges and fixings (`weather-and-use.md`).
  - **Formed bleed streaks:** too faint to see.
  - **Tile repeat at 9 m:** in `05` the tile's own per-panel tones (±6 %) still repeat every
    7.2 m in places, through the world tint (±5 %). Halve the tile's share (±3 %) and let the
    world tint carry the rest [I].
  - **Overall:** both walls are cleaner than the 40–60-year-old walls in the photo set, which
    carry biofilm, repaint ghosts and rust.

**Grain statistics of plain wall crops** (`analyze_walls.py`; photos from Table 5) [I, measured]:

| Crop (400 × 190 px at 2.4 m, about 2 mm/px) | slope | fine/broad | grain L\* | broad L\* | kurt | cv |
|---|---:|---:|---:|---:|---:|---:|
| round-6 spray, same rig, overcast | −0.04 | 5.6 | 0.44 | 0.08 | 4.3 | 0.30 |
| round-6 spray, same rig, low sun | −0.04 | 5.7 | 1.17 | 0.20 | 5.0 | 0.35 |
| new coat, first pass (r3), overcast | +0.13 | 7.2 | 0.37 | 0.05 | 3.1 | 0.15 |
| **new coat, final, overcast** | **−0.76** | **1.3** | 0.39 | 0.30 | 3.1 | 0.15 |
| **new coat, final, low sun** | **−0.33** | **2.9** | 0.91 | 0.31 | 3.1 | 0.16 |
| `cop_lib` concrete, overcast | −1.24 | 0.77 | 1.80 | 2.34 | 18 | 0.70 |
| **new formed, final, overcast** | **−1.05** | **0.82** | 0.40 | 0.49 | 64 | 0.44 |
| photos, coated walls (5) | −0.12 to −0.75 | 1.5–2.9 | 0.8–3.1 | 0.5–1.1 | 3.5–31 | 0.12–0.68 |
| photos, bare concrete (2) | −1.15, −1.45 | 0.41, 0.60 | 0.85, 1.42 | 1.42, 3.51 | 5.5, 5.8 | 0.29, 0.37 |

What the table says:
- **Shape.** The first pass of the coat had the stucco signature: a rising spectrum and
  fine/broad 7. Its 2–10 cm band was 10× too quiet.

  The reason was not the grain but a scaling trap. The albedo noise factors assumed a 0–1
  range, and `fractalnoise` has a std of 0.076 (§2.7, trap 22).

  After scaling by the real spread, both sets sit inside the range of all eleven photo crops for
  slope and fine/broad.
- **Amplitude.** Both are at or below the low end of the photographs: grain 0.4–0.9 L\*
  against 0.8–3.1. Two reasons:
  - at 2 mm/px the coat's 1 mm cavities average out in the pixel;
  - the prototypes carry no weathering in these crops.

  The missing contrast belongs to the story layer and decals, not to a stronger grain.
- **Kurtosis.** The coat's kurtosis is still Gaussian (3.1, against 3.5–31). Real coats have
  specks, pinholes and dirt dots. A sparse speck layer is the next step [I]. The formed set's
  64 comes from its bug holes.

**`frame_critique.py --view close --ref` bay and weathering photos** (full frames) [I, measured]:

| Frame | spectral_slope (target −1.5 to −0.85) | detail_density, area for 80 % | micro_uniformity | reference_match EMD |
|---|---:|---:|---|---:|
| round-6 spray, close, low sun | **+0.51** (info) | 0.58 pass | pass (p90/p10 5.7) | 25.3 fail |
| round-6 spray, close, overcast | **+0.45** (info) | 0.59 warn | n/a | 26.4 fail |
| new coat, close, overcast | −0.48 (info) | 0.68 warn | n/a | 26.2 fail |
| new coat, close, low sun | −0.37 (info) | 0.69 warn | n/a | 26.3 fail |
| new coat, 9 m, low sun | −0.63 (info) | 0.62 warn | n/a | 26.3 fail |
| new formed, close, overcast | −0.69 (info) | 0.70 fail | n/a | 22.3 fail |
| new formed, along the wall, sun | −0.70 (info) | 0.67 warn | n/a | 21.9 fail |
| new formed, 9 m, overcast | −0.88 **pass** | 0.69 warn | pass (5.7) | 21.1 fail |

How to read it:
- **spectral_slope** separates the stucco frames (+0.45 to +0.51) from the new ones (−0.37 to
  −0.88). The formed wall at 9 m reaches the natural-image band.
- **reference_match and camera fail** on every swatch frame by construction. A single wall
  with no sky, windows or clutter cannot match the value histogram of the photos. These tests
  are for scene frames.
- **detail_density** warns because detail covers the whole swatch. On a real facade the
  openings, rails and soffits make the rest areas.
- **micro_uniformity** passes the round-6 stucco frame (p90/p10 5.7). On the v2 close-up it
  passed at 5.9, and on its wall crop it reports n/a while `spectral_slope` reads +0.60.

  The tool needs a wall mask or `--crop` and a slope check to catch the stucco read. That is a
  suggestion for `frame_critique.py`; the file was not edited here.

### 2.6 Engine path

**What to bake, and how.** These are written by `cc_lib.G.write`; encodings verified in
22.0.466.

| Map | Encoding | Unreal import | Godot import |
|---|---|---|---|
| base colour | sRGB 8-bit PNG (OCIO default) | Default (BC1/BC7), sRGB on | Albedo, sRGB |
| ORM (R AO, G roughness, B metal) | raw 8-bit RGB | Masks (no sRGB) | ORM, linear |
| normal | raw 16-bit RGB, OpenGL (+Y) | Normalmap (BC5), **Flip Green Channel on** | Normal Map, no flip |
| height | raw 16-bit mono, the range in `*_meta.json` | Grayscale or HDR (G16), sRGB off | linear (Lossless) |
| masks | raw 8-bit **RGB** (a fourth channel in its own file) | Masks | linear |
| detail height, normal, cavity | as above | as above | as above |

**Bake versus runtime.**
- **Bake (the tiling sets):** everything that does not depend on where the piece sits:
  - the cast or coat material;
  - per-panel tone inside the tile;
  - seams, ties, holes, layer lines;
  - laps;
  - faint patches and cracks.
- **Runtime shader (the building's story):**
  - world macro value;
  - per-panel or per-bay tint from world or instance indices;
  - the storey lift and its joint at each floor;
  - streak fringes and sill-end streaks from the generator's primvars or vertex colours;
  - sheltered patches;
  - the damp base;
  - the detail strength from the coat mask, and dirt in the detail's cavities.
- **Decals (one-off hero marks):** leaks, spalls with their rims, repaired-crack lines,
  patches, graffiti and buffs, and the dark plasticiser band beside PC joints.

Patches baked into a tiling set repeat every tile and read as a pattern at 9 m. This was
measured in our first bay render, where two 0.3–0.6 m patches repeated on a 3.6 m grid. Keep
them faint in the tile and put the visible ones in decals [I, measured].

**Unreal (UE 5) material for the coated wall** [I, built from S: C32–C35, C37; untested]:

```
UV_m      = TexCoord[0]                      // generator writes UVs in metres (or world XY/ZY)
macroUV   = UV_m / 3.6 ;  detailUV = UV_m / 0.6
Base      = TextureSample(T_SprayMacro_BC, macroUV)                  // sRGB
ORM       = TextureSample(T_SprayMacro_ORM, macroUV)                 // Masks
Mask      = TextureSample(T_SprayMacro_Mask, macroUV)                // R coat, G patch, B crack
Coat      = Mask.r * 1.5 * DetailStrength                            // 0.75 default
NmMacro   = TextureSample(T_SprayMacro_N, macroUV)                   // BC5, green flipped on import
NmDet     = TextureSample(T_SprayDetail_N, detailUV)
NmDet     = Append(NmDet.rg * Coat, NmDet.b)                          // flatten by the coat mask
Normal    = BlendAngleCorrectedNormals(NmMacro, NmDet)               // RNM
Cav       = TextureSample(T_SprayDetail_Cavity, detailUV).r
Cause     = VertexColor.r  (or a generator mask / RVT)               // grime cause, 0..1
Base      = Base * (1 - Cav * Coat * (0.35 + 0.6 * Cause))           // dirt in troughs
Macro     = Lerp(0.96, 1.04, TextureSample(T_Noise, WorldPosition.xz * 0.07 + WorldPosition.y * 0.05).r)
Base      = Lerp(Base * Macro, SootColor, Cause * 0.18)
Damp      = VertexColor.g  (or 1 - smoothstep(top, top - 0.12, AbsoluteWorldPosition.z - GroundZ))
Base      = Lerp(Base, DampColor, Damp * 0.25) ; Roughness = ORM.g + Cav * 0.06 - Damp * 0.10
BaseColor = Base * PerInstanceRandom-driven HueShift (±1-2 deg) ; AO = ORM.r
```

- **Formed concrete:** the same graph without the detail set. Add a per-panel tint,
  `Lerp(0.95, 1.05, Hash(floor(UV_m / float2(0.9, 1.8))))`. Use HeightLerp against the formed
  height to put dirt into voids and seams first.
- **Decals:** a Deferred Decal material, DBuffer Translucent Color, Normal, Roughness.
- **Joint sealant strips:** mesh decals.

**Godot 4 spatial shader for the coated wall** [I, written from S: C39, C40; untested]:

```glsl
shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

uniform sampler2D macro_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D macro_orm : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D macro_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D macro_mask : hint_default_black, filter_linear_mipmap, repeat_enable;
uniform sampler2D detail_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D detail_cavity : hint_default_black, filter_linear_mipmap, repeat_enable;
uniform sampler2D world_noise : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform float macro_tile_m = 3.6;
uniform float detail_tile_m = 0.6;
uniform float detail_strength = 0.75;
uniform vec3 soot = vec3(0.20, 0.19, 0.165);
uniform vec3 damp_col = vec3(0.13, 0.125, 0.11);

varying vec3 wpos;
void vertex() { wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }

vec3 unpack_xy(vec4 t) {               // normal-map imports keep RG only: rebuild z
    vec2 xy = t.rg * 2.0 - 1.0;
    return vec3(xy, sqrt(max(0.0, 1.0 - dot(xy, xy))));
}

void fragment() {
    vec2 uvM = UV / macro_tile_m;      // UV in metres, written by the generator
    vec2 uvD = UV / detail_tile_m;
    vec3 base = texture(macro_albedo, uvM).rgb;
    vec3 orm = texture(macro_orm, uvM).rgb;
    vec3 msk = texture(macro_mask, uvM).rgb;
    float coat = msk.r * 1.5 * detail_strength;
    float cav = texture(detail_cavity, uvD).r;
    float cause = COLOR.r;             // grime cause from the generator
    float damp = COLOR.g;              // damp band from the generator
    base *= 1.0 - cav * coat * (0.35 + 0.6 * cause);
    float macro = mix(0.96, 1.04, texture(world_noise, wpos.xz * 0.07 + vec2(0.0, wpos.y * 0.05)).r);
    base = mix(base * macro, soot, cause * 0.18);
    base = mix(base, damp_col, damp * 0.25);
    vec3 nM = unpack_xy(texture(macro_normal, uvM));
    vec3 nD = unpack_xy(texture(detail_normal, uvD));
    vec3 n = normalize(vec3(nM.xy + nD.xy * coat, nM.z * nD.z));   // whiteout blend
    ALBEDO = base;
    ROUGHNESS = clamp(orm.g + cav * 0.06 - damp * 0.10, 0.0, 1.0);
    AO = orm.r;
    NORMAL_MAP = n * 0.5 + 0.5;
}
```

- **Decals:** use Godot `Decal` nodes for leaks, patches and tie holes on hero walls. They take
  albedo, normal, ORM and emission, but not height. Forward+ clusters 512 elements by default;
  Mobile allows 8 decals per mesh [S: C39].
- **StandardMaterial3D** can do the formed set alone, with Detail (mask, albedo, normal) and
  UV1 world triplanar. Its detail blend, however, cannot be driven by a macro mask channel
  [S: C40].

### 2.7 Verified node and parm traps (22.0.466)

Every type and parm used was read first. `scratchpad/roundE/scripts/dump_types.py` dumped
inputs, outputs, parm names, defaults and menus for 78 COP and 41 MaterialX VOP types (and 17 LOP types in `probe_lop.py`) from
`hou.nodeType(category, name).parmTemplateGroup()` on nodes created in `/img` and `/mat`. The
behaviours below were then tested with small probe graphs (`probe*.py`). Items 1, 2, 4, 5, 8, 13, 14
and 22 contradict or extend the existing skill text.

1. **`fractalnoise` `elementscale` is ignored** at the default `elementsizetype` 0. Measured:
   with (1, 8), |d/dx| = |d/dy| = 0.012; with `elementsizetype` 1, |d/dy| fell to 0.0019. The
   menu item's label is "Per-Component Controls". `copernicus.md` suggests a stretched noise with
   `elementscale` like (1, 0.05), which does nothing as written.
2. **`streakblur` is centred.** With `dirtype` coord and `dir` (0, −1), the default `bias` 0
   smears both up and down: a dot at rows 231–280 spread to rows 167–344. `bias` 1 gives
   downward only (103–280); `bias` −1 upward only. `distort` with `streak` is one-sided. The
   `tie_leaks` node in `cop_lib.build_concrete_panels` uses the default bias, so its "leaks" run
   upward too.
3. **Buffer row 0 is the image bottom** (y up), so flip when reading layers into numpy. PNGs are
   written the right way up.
   - **Normal convention:** `heighttonormal` is OpenGL (+Y). Height rising toward +y gives
     G = 0.276 < 0.5. Flip green for Unreal.
4. **`tilepattern` circles stay round** in non-square cells at the default `useaspectratio` 0.
   They are sized to the smaller cell side: 30 × 31 px in a 64 × 85 cell, 32 × 32 in 128 × 64.
   `useaspectratio` 1 stretches them (30 × 41, 64 × 32). The SKILL.md trap "circles in
   non-square cells become ellipses" applies only with `useaspectratio` on.
5. **`tilepattern` `id` is invalid outside a shape,** and `randommono` gives every such pixel
   one shared value, seed-dependent: the image mean was 0.98 at seed 14, 0.95 at seed 10, 0.08
   at seed 6. Anything widened from a shape by blur then inherits that value. In our first
   build, lime runs appeared under *every* tie.

   Fix: `zeroinvalid` 1. Make per-element choices inside the shape, then blur. Inside the shape
   the randoms are well distributed: 48 ties gave mean 0.38–0.55, std 0.26–0.29 across ten
   seeds.
6. **`worleynoise`.**
   - `dist1` is in cell units (0–1.12) at any `elementsize`;
   - `dist2` reaches 1.37;
   - `border` is in image units (0–0.048);
   - `center` is 2-channel;
   - `id` is int32 and reads as NaN or inf if viewed as float. Feed it only to `randommono`.
7. **`randommono` `seed`.** The `seed` parm with an id in the `seed` input gives independent
   streams (correlation −0.04). `time` also changes the stream.
8. **`cellularnoise` has `gap`, `gap_relative`, `bevel`, `bevel_relative`, `bevelramp` and
   `mode`** (absolute, relative). `copernicus.md` says it has no gap or bevel parms in 22.0.466.
9. **A `ramp` at its default signature makes `heighttonormal` fail** with "Error while cooking".
   Set `signature` f1. Ramp `method` repeat with `cycles` N and `phase` gives a tiling
   sawtooth.
10. **`heighttonormal` `scale`** multiplies the slope per image unit. A 0–1 ramp across the
    image (0.5 per unit) at `scale` 1 gave (−0.447, 0, 0.894). The output is 0–1 encoded.
    Physical scale = 2 / tile with height in metres.
11. **`blend` maths.** The `mask` parm is the opacity of every mode. With bg 0.2, fg 0.5 and
    mask 0.4:
    - add 0.40;
    - multiply 0.16;
    - subtract 0.0;
    - blend 0.32;
    - max 0.32.

    So `blend` max with a mask lerps toward the max. `divide` works (0.3/0.6 = 0.5).
12. **`remap` and `function`.** `remap` `op` threshold has a `width` for a soft step, centred on
    the threshold. `remap` `method` extend gives an unclamped linear map. In `function`:
    - `func` math with `func_math` modulus applies `scale` first ((0.3 × 7) mod 1 = 0.1);
    - `shift` is added;
    - `func` pow with `func_pow` powx uses `exponent`;
    - `func_math` abs gives the absolute value.
13. **`rop_image` alpha for PNG and TGA.** The default `pngtga_alpha_multiplication` token is
    "premult", labelled "Unpremultiply if needed": it divides RGB by A. A test with RGB 0.5 and
    A 0.1/0.5/0.9 wrote 255/251/139. The token "unpremult", labelled "Raw", writes 128. The
    tokens and labels are inverted. Use "unpremult" for packed data. `cc_lib.write` now does.
14. **Karma's texture reader premultiplies.** `mtlximage` on an RGBA PNG returns RGB × A. A raw
    coat mask with laps in A rendered the coat only inside the laps. Keep data masks RGB-only,
    or put each channel in its own file. Engines read RGBA raw, so an RGBA ORM-plus-height pack
    is fine there but not in Karma.
15. **`channeljoin` needs an explicit `signature`** (f1, f2, f3, f4, …). Use f2 for a vector to
    `distort` `dir`, and f3 for RGB masks.
16. **A `file` COP created from Python** shows no outputs or layers (`outputNames()` empty)
    until its AOVs are set up. Read EXRs with OpenImageIO
    (`OpenImageIO.ImageBuf(path).get_pixels()`), which hython ships.
17. **`karmarendersettings` `resolutiony` is locked** (`hou.PermissionError`) even after
    `res_mode` manual (menu: manual, autowidth, autoheight). Leave autoheight; the height
    follows the camera's `verticalAperture`.
18. **`sopimport` paths.**
    - a point-class `path` is ignored (the mesh became `/walls/mesh_0`);
    - a prim-class relative path "wall" becomes `/walls/wall`;
    - an absolute "/ground" becomes `/ground`.
19. **`mtlximage` `signature`:** the menu lists only default and color3, but vector3 is
    accepted and works for normal maps.
20. **`mtlxbump`'s `normal` input** takes a `mtlxnormalmap` output, so a detail height bumps on
    top of a macro normal map in Karma CPU (rendered).
21. **`phasornoise` `firstrotatepattern`** changed nothing in a gradient-energy test at 0 and 90.
    Stretched `fractalnoise` was used for all directional grain.
22. **`fractalnoise` (`amp` 0.5, `center` 0.5) has a std of only about 0.076,** with p1–p99 of
    0.31–0.70, at any octave count. At large element sizes the tiled domain holds few features
    and the std falls: 0.060 at 0.2 units, 0.048 at 0.3. So 0.3 × (noise − 0.5) moves a value by
    about 2 % std, not 15 %. Thresholds near 0.6 select about 10 % of the area at small sizes
    and almost nothing at large ones.

    Our first renders measured 0.05–0.2 L\* in the 12–48 px band where photographs have 0.5–3.5.
    Scaling by the real spread fixed it. Use `equalize` (stretch) when a 0–1 mask is meant.

23. **COP cooks are fast and writes are slow.** A 4096 fractal cooked in 0.17 s and the whole
    formed graph in under 90 s. Writing seven 4096 PNGs, including 16-bit normal and height,
    took 80 s; the 16-bit normal alone is 75 MB.

### 2.8 What remains unverified

- **Engine shaders.** The Unreal graph and the Godot shader in §2.6 were written from the docs
  and were not compiled or run.
- **Engine imports.** BC5 import of the 16-bit normals, and Godot's RG-only normal
  reconstruction in a custom shader, were not tested.
- **Untested nodes.** `hextile`, `triplanarhextile`, `mtlxhextiledimage` and
  `combinenormals`: parms read, not used.
- **`phasornoise`:** its rotation parms and output beyond the one test.
- **Real-world sizes inferred, not sourced:**
  - spray-tile bump and lithin grain sizes;
  - the coat's relief after repaints;
  - the halo strength around ties;
  - layer-line waviness;
  - the 2 mm seam gap;
  - plywood grain relief.

  The Japanese standard (JIS A 6909) was unreachable during the research.
- **ACI 347.3R classes** come from an unofficial copy whose tables extracted partly scrambled,
  cross-checked against one review. No "CSV1–9" or "CSA" scale exists in ACI. The ASCC photo
  scale is P2–P5.
- **Grain statistics** come from 11 small crops at different scales, with JPEG loss on the
  photos. They show a direction, not a calibrated target.
- **The comparison with photos is by eye** plus `frame_critique.py` and the crop statistics. No
  A/B pick by the user has been made on these previews.
- **Not built here:**
  - a lithin set;
  - a PC-panel set;
  - a board-formed set;
  - geometric joints, drips and copings on the test wall. A plain wall cannot spawn sill-end
    streaks.

---

## Sources

The research agents opened these pages on 2026-10-27 and 28.
- **(snippet):** only a search summary was seen.
- **(unofficial copy):** not the publisher's copy.
- **(paywalled):** the publisher's text was not read.

### A. Construction and materials

- A1 ACI 347.3R-13, Guide to Formed Concrete Surfaces, preview (the body is paywalled): https://www.concrete.org/Portals/0/Files/PDF/Previews/347.3R-13_PREVIEW.pdf
- A2 ACI 347.3R-13 (unofficial copy; tables partly scrambled in extraction): https://pdfcoffee.com/aci-3473r-13-guide-to-formed-concrete-surfaces-pdf-pdf-free.html
- A3 Malisch and Brown, review abstract: https://www.concrete.org/publications/internationalconcreteabstractsportal/m/details/id/51722463 ; CRC-93 report: https://www.acifoundation.org/Portals/12/Files/PDFs/CRC-93_Guide-to-Formed-Concrete-Surfaces.pdf
- A4 Borgerson and Vogt, ACI SP-338: https://www.concrete.org/publications/internationalconcreteabstractsportal.aspx?m=details&i=51724725
- A5 ASCC Position Statement 8, bugholes: https://cecoconcrete.com/content/Resources/ASCC%20Position%20Statements/ASCC%20PS%238%20Bugholes%20in%20formed%20concrete%20CI.ACI.pdf
- A6 ACI 309.2R-98, placement defects (unofficial copy): https://www.slideshare.net/slideshow/aci-3092-r-98/162839815
- A7 ACI 309.2R-15 preview: https://www.concrete.org/Portals/0/Files/PDF/Previews/309_2R_15_preview.pdf
- A9 CIB Report 24 record: https://trid.trb.org/View/54468
- A10 Concrete Society, CAS Advisory Data Sheet 15: https://www.milbank.co.uk/app/uploads/2022/08/CAS-Advisory-Data-Sheet-15.pdf
- A11 Heidelberg Materials, DBV/VDZ Merkblatt Sichtbeton tables: https://www.heidelbergmaterials.de/system/files/2026-02/HM_Sichtbeton_Klassen_Anforderungen_Brosch%C3%BCre_1.pdf
- A12 Dyckerhoff, Sichtbeton mit Dyckerhoff WEISS (2016): https://www.dyckerhoff.com/documents/209745/678472/Fachaufsatz+2016+-+Sichtbeton+mit+Dyckerhoff+WEISS.pdf/6c0064b1-8d88-8f4c-9535-43ff71c60ecd
- A13 Konpane sizes: https://gaiheki-katorihome.com/konpanesunpouicadenokikakuerabikata.html
- A14 Aramaki et al. 2021, form reuse, gloss and brightness (AIJ): https://www.jstage.jst.go.jp/article/aijt/27/65/27_58/_pdf
- A15 P-cone dimensions: https://n-tekkou.com/product/pcone/
- A16 hm+architects, exposed concrete practice: https://hm-a.jp/architectural-concrete-finish-03/
- A17 Tie pitch (Q&A and blog): https://question.realestate.yahoo.co.jp/knowledge/chiebukuro/detail/14294495024/ ; http://sherpa-net.blogspot.com/2017/03/blog-post_24.html
- A18 APA Plyform: https://www.apawood.org/engineered-wood-products/plywood-osb/concrete-plyforms/
- A19 Japanese form reuse surveys: https://www.rinya.maff.go.jp/j/press/mokusan/pdf/090728-05.pdf
- A20 Board formwork: https://www.baustoffshop.de/infothek/schalbretter/ ; https://www.baunetzwissen.de/gerueste-und-schalungen/fachwissen/wand--deckenschalungen/brettschalung-10319324
- A21 Snap-tie cones: https://www.ocm-inc.com/shop/snap-ties-and-accessories/concrete-snap-tie-cone-plug/stconeplug/
- A23 Max Frank, tie points in exposed concrete: https://www.maxfrank.com/us-en/news/news-list/2310-spannstellen-in-sichtbeton-gestalten.php
- A24 Japanese joints; MLIT crack guide: https://wiple-service.com/column/joint-types-waterproofing-methods/ ; https://www.skr.mlit.go.jp/etc/hibiwaretebiki.pdf
- A25 NRMCA CIP 3, crazing: https://www.nrmca.org/wp-content/uploads/2021/01/03pr.pdf
- A26 NRMCA CIP 23, discolouration: https://www.concreteanswers.org/CIPs/CIP23.htm
- A27 ACI 224R crack widths (secondary): https://ascconline.org/Portals/ASCC/Files/Position%20Statements/PS-33_CracksInStructuralConcrete_09-11_Web_SC.pdf
- A28 Wall crack spacing (snippet): https://www.researchgate.net/publication/245573078_Shrinkage_and_Cracking_of_the_Reinforced_Concrete_Walls
- A29 JCI, cracks at openings: https://www.data.jci-net.or.jp/data_pdf/35/035-01-1079.pdf
- A31 Tanuma 2020, UR maintenance: https://www.jstage.jst.go.jp/article/coj/58/5/58_376/_pdf/-char/en
- A32 Tanuma and Sugiyama 2017, 53-year survey of a 1963 danchi: https://www.jstage.jst.go.jp/article/aijt/23/53/23_37/_pdf
- A35 Concrete stalactites (snippet): https://edu.rsc.org/opinion/concrete-stalactites/2020991.article
- A36 Efflorescence: https://www.mc-bauchemie.com/mcpedia/efflorescence-in-concrete
- A37 PCI Designer's Notebook DN-29, Weathering: https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf
- A38 Blocken et al., rain run-off review: https://www.urbanphysics.net/2013_BAE_Runoff_Review__Preprint.pdf
- A40 Coloured concrete and biofilm: https://www.sciencedirect.com/science/article/pii/S2352710223001973
- A41 Splash-water zone: https://hauraton.com/en-int/application-areas/flat-roofs-and-facades
- A42 PCI, architectural precast FAQ: https://www.pci.org/GCPCI/GCPCI/Technical_Resources/FAQs/Architectural-Precast.aspx
- A43 PCI manual §4.7, joints: https://static1.squarespace.com/static/5c52339c50a54f520b657793/t/5c60748c0d929794cf57d1ff/1549825166700/PCI+Joint+Specification.pdf
- A44 APA, architectural precast colour and finish guide: https://www.archprecast.org/assets/GuidesSpecs/Color%20and%20Finish%20Guide.pdf
- A45 Sealant staining: https://prosoco.com/app/uploads/2018/11/guide-to-common-masonry-stains-pamphlet.pdf
- A46 KTA, coatings on exterior concrete walls: https://kta.com/kta-university/exterior-concrete-walls-coatings/
- A47 Elastomeric data sheet: https://dciflooring.com/wp-content/uploads/2014/09/Sherwin_Williams_Sherlastic_A5-200_PDS.pdf
- A48 Levinson and Akbari, LBNL-48334, solar reflectance of concrete: https://19january2021snapshot.epa.gov/sites/static/files/2014-08/documents/reflectance_chap12.pdf ; https://bies.lbl.gov/publications/effects-composition-and-exposure
- A50 PCA SN2982, albedo of cements (snippet): http://www2.cement.org/DVD021.02/code/reports/SN2982.pdf
- A51 Patch colour matching: https://www.concreteconstruction.net/how-to/color-matching-patches_o
- A53 SCC colour uniformity (snippet): https://orbilu.uni.lu/bitstream/10993/23595/1/PhD-Symposium%20KL.pdf

### B. Japanese practice

- B1 BRI (kenken), finish coatings: durability, carbonation ratios, public spec patterns and coverage: https://www.kenken.go.jp/japanese/contents/publications/data/145/2.pdf
- B2 NILIM, finish-coating chronology 1960–2015 and compatibility: https://www.nilim.go.jp/lab/bcg/siryou/tnn/tnn1182pdf/ks1182_06.pdf
- B3 NILIM, public housing stock by age: https://www.nilim.go.jp/lab/bcg/siryou/kpr/prn0062pdf/kp006217.pdf
- B4 NILIM, survey of public housing finishes and defects: https://www.nilim.go.jp/lab/bcg/siryou/kpr/prn0062pdf/kp006218.pdf
- B5 NILIM, service lives: https://www.nilim.go.jp/lab/bcg/siryou/kpr/prn0062pdf/kp006219.pdf
- B6 NILIM, defects and repair methods in public housing: https://www.nilim.go.jp/lab/bcg/siryou/kpr/prn0062pdf/kp006220.pdf
- B7 MLIT, WPC housing R&D: https://www.mlit.go.jp/chosahokoku/h22giken/program/kadai/pdf/ippan/ippan2-07.pdf
- B8 Nishiyama, Precast Concrete Construction in Japan: https://www.cni.it/images/eventi/2022/22.pdf
- B9 UR, standard designs and modules: https://www.ur-net.go.jp/rd_portal/archive/lrmhph000001t9d7-att/p14-p15.pdf
- B13 Osaka Prefecture, design note on crack-control joints: https://www.pref.osaka.lg.jp/documents/35034/12_dai2busekkeihozyosiryo_1.pdf
- B14 Sendai, PC joint quantities (snippet): https://www.city.sendai.jp/kojikeyaku/jigyosha/keyaku/kekka/h25konsaru/documents/toorisitugi3.pdf
- B15 Joint sealant in public housing (J-STAGE): https://www.jstage.jst.go.jp/article/finex/2018/0/2018_145/_article/-char/ja
- B17 Tie pitch: https://kentikusi.jp/dr/blog/8331/
- B18 Formwork and stripping practice: https://www.denen-arch.com/post/8878
- B19 Nihon Kasei, P-cone hole filling manual: https://www.nihonkasei.co.jp/cms/NS/images/topics/2015/Pコン穴充てん施工マニュアル.pdf
- B22 Shimane Prefecture, form plywood: https://www.pref.shimane.lg.jp/infra/kouji/kouji_info/kanbatsu_kouzou/hinokikawakugouban.html
- B26 Finish-materials association, pattern names: https://nsk-web.org/tozai-moyo/
- B27 Finish-materials association, Q&A: https://nsk-web.org/qa/
- B28 Tile-gun application data: https://www.paint-city.com/imgdb/webman_file/20-1.pdf
- B29 SK Kaken, Soft Surf SG: https://www.paint-city.com/pdf/softsurf_sg.pdf
- B30 Nippon Paint, Perfect Filler: https://www.paint-city.com/pdf/np30142.pdf
- B31 MLIT, long-term repair guideline (2021): https://www.mlit.go.jp/report/press/content/001425184.pdf
- B32 JCI 2024, carbonation of 1957–71 buildings: https://www.data.jci-net.or.jp/data_pdf/46/046-01-2157.pdf
- B33 Arakawa ward, colour standard: https://www.city.arakawa.tokyo.jp/documents/3209/sikisai64_1.pdf
- B34 Tokyo landscape colour guideline: https://www.toshiseibi.metro.tokyo.lg.jp/kenchiku/keikan/tokyo_color_guideline_01.pdf
- B42 Low-pressure epoxy injection spacing (snippet): https://www.kobe-u.ac.jp/documents/info/public-info/purchase/pfi/requirements/final/data-09.pdf
- B43 Kikusui spec to UR maintenance specification, lap width (snippet; 403): https://kikusui-chem.co.jp/download/view/pdf/spec_id/1877

### C. CG craft

- C1 Epic, physically based materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine
- C2 Physically Based database: https://physicallybased.info/
- C3 Lagarde, feeding a physically based shading model: https://seblagarde.wordpress.com/2011/08/17/feeding-a-physical-based-lighting-mode/
- C4 Studio 397, albedo values: https://docs.studio-397.com/x/EgBDAg
- C5 Adobe, The PBR Guide part 2: https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2
- C6 Adobe, Control's brutalist material library: https://www.adobe.com/products/substance3d/magazine/control-how-one-senior-environment-artist-created-entire-brutalist-material-library.html
- C7 80.lv, Remedy's Substance use in Alan Wake 2: https://80.lv/articles/remedy-s-use-of-substance-3d-in-environment-art-of-alan-wake-2/
- C8 Phail-Liff and Vitale, The Order: 1886 (SIGGRAPH 2015): https://history.siggraph.org/wp-content/uploads/2022/10/2015-Talks-Phail-Liff_Crafting-Victorian-London-The-Environment-Art-and-Material-Pipelines-of-The-Order-1886.pdf
- C10 Gears of War 4 layered materials: https://history.siggraph.org/learning/gears-of-war-4-creating-a-layered-material-system-for-60fps
- C11 The Division 2 and Substance: https://magazine.substance3d.com/the-division-2-how-to-leverage-the-entire-substance-toolset-for-aaa-game-production/
- C12 SideFX and Embark, THE FINALS buildings: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
- C14 Unity photogrammetry workflow: https://create.unity3d.com/get-ready-for-photogrammetry
- C15 Poly Haven, scanning: https://blog.polyhaven.com/?p=977
- C16 80.lv, Quixel scanning: https://80.lv/articles/quixel-megascans-scanning-materials-for-games-film
- C18 80.lv, concrete floor in Substance Designer (Curt C. Smith): https://80.lv/articles/concrete-floor-in-substance-designer
- C19 80.lv, concrete and cracks (Daniel Swing): https://80.lv/articles/generating-concrete-and-cracks-in-substance-designer
- C20 80.lv, painted old concrete (Enrico Tammekänd): https://80.lv/articles/generating-painted-old-concrete-in-substance/
- C21 80.lv, Mark Foreman: https://80.lv/articles/building-materials-in-substance-designer-with-mark-foreman
- C22 Adobe, Mark Foreman's tips: https://www.adobe.com/learn/substance-3d-designer/web/mark-foreman-s-substance-3d-designer-tips-and-tricks
- C23 80.lv, layered alley wall (Charlie Foreman): https://80.lv/articles/creating-a-layered-alley-wall-in-substance-designer
- C24 80.lv, improving cracks (Rosen Kazlachev): https://80.lv/articles/breakdown-improving-cracks-on-your-3d-materials-in-substance-3d
- C25 Adam Crespi, Substance Designer for architectural visualization: https://www.linkedin.com/learning/substance-designer-for-architectural-visualization-2/establishing-a-form-tie-pattern
- C26 80.lv, Asian fortress in Unreal (Leo Brynielsson): https://80.lv/articles/building-the-asian-fortress-with-unreal
- C28 Substance Painter anchor points: https://magazine.substance3d.com/substance-painter-introducing-anchor-points-and-references/
- C29 The power of the high pass filter: https://gamedeveloper.com/art/the-power-of-the-high-pass-filter
- C30 Blender Artists, procedural concrete critique: https://blenderartists.org/t/procedural-concrete-texture/679611
- C31 Blender 4.1 Musgrave merge: https://projects.blender.org/blender/blender/pulls/111187
- C32 Epic, material layers: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-material-layers-in-unreal-engine
- C33 Epic, decal materials: https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine
- C34 Epic, detail textures: https://dev.epicgames.com/documentation/en-us/unreal-engine/adding-detail-textures-to-unreal-engine-materials
- C35 WorldAlignedTexture: https://80.lv/articles/ue5-triplanar-deep-dive-from-worldalignedtexture-to-high-quality-normals-part-1/
- C36 Epic, runtime virtual texturing: https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine
- C37 Epic, landscape height blend: https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-material-expressions-in-unreal-engine
- C38 Mikkelsen, hex tiling (JCGT 2022): https://jcgt.org/published/0011/03/05/paper.pdf ; Godot port: https://godotshaders.com/shader/stochastic-hex-tiling-mikkelsens-adaptation/
- C39 Godot, decals: https://docs.godotengine.org/en/stable/tutorials/3d/using_decals.html
- C40 Godot, StandardMaterial3D: https://docs.godotengine.org/en/stable/tutorials/3d/standard_material_3d.html
- C41 Maxon, texel density: https://help.maxon.net/c4d/2027/en-us/Content/html/Texel_Density.html.md
- C43 The Ultimate Trim (GDC): https://gdcvault.com/play/1022323/The-Ultimate-Trim-Texturing-Techniques
- C44 CraftPBR, seamless concrete guide: https://craftpbr.com/guides/seamless-concrete-texture
- C45 Persson et al., surface roughness of concrete (arXiv): https://arxiv.org/html/2507.18782v3
- C46 Giatec, bugholes: https://giatecscientific.com/education/bugholes-in-concrete
- C50 Rybczynski, the form-tie detail: https://www.witoldrybczynski.com/architecture/the-form-tie-detail/
- C51 Tadao Ando facade design; PERI Langen Foundation: https://www.studiomatrx.org/guides/tadao-ando-facade-design ; https://peri.pt/projects/langen-foundation.html
- C52 Spec Formliners, board liners: https://specformliners.com/barnwood
- C53 3dtextures, formwork texture notes: https://3dtextures.me/2026/04/02/concrete-wall-formwork-016-free-seamless-pbr-texture/
- C57 Polycount critique threads (search excerpts; the pages returned 403): https://polycount.com/discussion/comment/2636854 ; https://polycount.com/discussion/comment/2620699 ; https://polycount.com/discussion/116831/udk-stylized-lab-scene ; https://polycount.com/discussion/156558/critiques-on-a-texture ; https://polycount.com/discussion/comment/2498906/ ; https://polycount.com/discussion/comment/2774208
- C65 Roughness map guide (low quality): https://www.tripo3d.ai/blog/roughness-map
- C66 Macro variation in Unreal landscapes: https://versluis.com/2023/05/how-to-use-macro-variations-for-unreal-engine-landscape-materials

### Internal

- `.claude/skills/procedural-materials/SKILL.md` and its references: `realism.md`,
  `micro-noise.md`, `layering.md`, `copernicus.md`, `weather-and-use.md`.
- `docs/redesign/research/rR-reference-photos.md` and `docs/redesign/evidence/refs/manifest.json`.
  These are the 39 photos, with licences and authors. The photos are not reproduced in this
  round's JPGs.
- `examples/danchi/src/py/tex_build.py` and `materials.py`, the round-6 spray and concrete
  recipes that were compared here.
