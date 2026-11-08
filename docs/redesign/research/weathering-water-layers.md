# Water, deposits and growth on panel facades: research note (round I)

Date: 2026-11-01. For `scripts/weathering/weather_fields.py` and the rulebook (1.5).

**The block.** A 10-storey RC slab, about 30 m tall and 82 m long. Floors are 2.8 m apart and bays 6 m wide. Walls are precast or formed, with vertical and horizontal joints and grooves. Maps are at 50 px/m (1 px = 2 cm).

**What prompted it.** The AD's review of the presets made six points:
- Organic colours flip between presets.
- Water staining should be its own layer, with growth coming out of it.
- Streaks and the foot band gain intensity, but not area.
- Streaks belong in the vertical joints, with light face streaks from the grooves.
- Derelict lacks spread.
- Kept's darker stains are a little too dark.

**Builds on, without repeating:** the bio note (`weathering-organic-growth.md`), `r3-believable-textures.md`, `r4-weather.md`, the concrete note (`rE-concrete.md`), the damage note (`weathering-cracks-edges-damage.md`) and the layering note (`r5-texture-layering.md`).

**Tags.** [C] consensus (standards, reviews, textbook physics). [P] a practitioner's observation, or mine on photos. [M] measured data. [I] my inference. Numbers in tags point to the sources in §9.

**Limits.** The shared web-search budget ran out partway through; §8 lists what stayed unread. Most per-preset numbers are [I]: they are targets, to be calibrated with picks.

## 0. Summary

1. **Three layers in causal order, each its own map.** Water (where and how long the wall is wet) comes from geometry and age. Deposits (dust, soot, soil) are moved by water. Growth needs water, is fed by deposits, and takes time.
2. **One colour continuum per mark, set by the mark's own age.** It runs: faint yellow tint, dark yellow, olive and dark green, muddy olive-brown, reddish mud. The wettest cores end brown-black. A mark's branch is fixed at birth, and its L* never rises.
3. **Biology agrees: yellow first, green when established, brown-black when old.** Red belongs only to *Trentepohlia*. The "dark" in dark yellow comes from the deposit under a young film.
4. **Vertical joints carry the streaks.** Faces get only thin streaks, from groove overflow points. PCI agrees: vertical recesses gather run-off and hold dirt, and horizontal ribs spread stains.
5. **Area must grow by ×1.3–2 per preset step, not only darken.** Width grows as paint ages (rivulet width ∝ contact angle^(−3/4)). Length grows with deposits (logarithmic), then with growth (sigmoid). The foot band climbs.
6. **Derelict at 40–50 years.** The whole wall is darkened, with streaks under every horizontal element and most joints lit. Growth covers 20–40% of shaded walls, and the foot band reaches about 1 m.
7. **The generator today has four problems.** Mark families sit in cells whose thresholds slide with the clock. From Kept to Derelict, channels widen only ×1.33 and the foot band rises only ×1.32. Derelict's growth clock is 7.1 years. The solver dims Derelict's marks to a gain of 0.47.
8. **Gate rules V1–V5 (§7)** check growth from water, colour identity, joints over faces, area per step, and Kept against Derelict.

## 1. The causal layer stack

### 1.1 The three layers

| Layer | Made by | Where | Looks like | Clock | Tags |
|---|---|---|---|---|---|
| Water | run-off, splash, leaks, damp | joints, below sources, the foot, damp shade | darker when wet; tide rims; washed cores; efflorescence | geometry and age (sealant, paint) | [C 2, 15, 17] |
| Deposits | dry deposition of dust, soot and soil, carried and dropped by water | upward and rough faces, path margins and ends, the foot | near-neutral warm darkening; streaks; splash band | soiling clock E | [C 2] [P 3] |
| Growth | algae, cyanobacteria, fungi; later moss and lichen | where water stays and deposits feed it | tint, then film, then crust (§2) | years unattended, t_bio | [C 1]; bio note |

### 1.2 How each layer comes from the ones before

**Water**
- Run-off on smooth surfaces breaks into streams that recur at the same places every rain (r3) [C 2].
- Water moving sideways gathers at vertical recesses [C 2].
- At a panel's bottom edge, water slows and drops its dirt [C 2].
- A drying film leaves its load at the rim, where evaporation is fastest: the coffee-ring effect [C 17]. On walls this gives the tide line, and salts left at a damp edge make a mark that outlasts the damp [P 15].
- Efflorescence and lime runs are water products at joints and cracks (damage note) [C].
- Wetting lowers concrete albedo by about 0.23 (concrete note, A48) [M]. That change is transient, so it belongs in the runtime shader [I].

**Deposits**
- Dust and soot settle fairly evenly at first, faster on upward and coarse faces. Run-off then moves them [C 2].
- Japanese 雨筋よごれ (rain-streak) studies trace a streak to dirt on a coping top, which rain suspends and spills over the edge [P 3].
- So deposits come in two parts. One is a dry film everywhere, driven by E. The other is dirt carried along water paths and dropped at their margins and ends (dirt washing). Late in life, the busiest paths wash clean (white washing; r3) [C 2].
- In Japanese tests, a higher water contact angle gave stronger streaks, with a significant correlation [M 3].

**Growth**
- Bioreceptivity is primary on fresh material, secondary after weathering, and tertiary after cleaning [C 1].
- Its external factors are surface deposits (dust, organic particulates, pollutants, guano, dead biomass) and position (angle, aspect, height above ground) [C 1].
- So growth needs water to start, and grows faster and thicker where deposits feed it [I from C 1].
- Growth holds water and traps dust, so the damp zone and the deposits widen around it [I].
- Biocides in a repaint protect for at most about 5 years (bio note) [C].

### 1.3 What the generator should compute from what

All steps are [I].
1. **Water path Wp.** It comes from age, not E: vertical joints, groove overflow points, sill ends, slab drip lines and failed-sealant crossings.
2. **Time of wetness Wt.** Blur Wp 0.1–0.3 m sideways and 0.3–1.5 m downward, then add splash, shelter and orientation. Wt replaces streak opacity as the input of `bio_wetness`.
3. **Water marks from Wt:** tide rims, washed cores, and efflorescence that grows with age.
4. **Deposits Dp** = E × receptivity, redistributed by Wp: dirt washing at path margins and ends, and white washing in the cores from E 12.
5. **Growth.** Rate ∝ Wt² × (0.5 + Dp / mean Dp), with the deposit factor capped at 2. Its time is t_bio.
6. **Colour.** Each organic mark takes its own age's colour on the continuum (§2.4–2.5).

### 1.4 Order in an engine material stack

| Order | Layer | Baked or runtime | Albedo | Roughness | Height |
|---|---|---|---|---|---|
| 0 | Base: paint or concrete, coat | baked, plus tiling detail | clean | 0.75–0.85 chalked paint (concrete note) | coat relief |
| 1 | Fading, repaint ghosts | baked | lighter, greyer | — | — |
| 2 | Water marks: tide rims, washed cores, sealant bands | baked | rims T2–T3 darker; cores T1–T2 lighter | — | — |
| 3 | Deposits: film, run-off dirt, splash soil | baked | darker, near-neutral warm (I1) | +0.03–0.05 | fills coat cavities |
| 4 | Growth: biofilm by age; moss and lichen | baked; wet tint at runtime | continuum colour (§2.4) | films 0.75–0.90 dry (bio note) | moss and lichen only |
| 5 | Efflorescence, lime runs | baked | white, L* 80–92 (damage note) | high | slight |
| 6 | Rust runs | baked | orange-brown | — | — |
| 7 | Damage, chips, spalls | baked; cuts layers 2–6 | substrate | — | yes |
| 8 | Rain wetness | runtime | porous parts darker, by Wt × rain | lower in wet cores | — |

- Growth sits over deposits because it binds and hides them. Efflorescence blooms over both, and breaks cut every weathering layer [I].
- In Unreal Substrate the rain film is a vertical layer, while dirt and growth are horizontal blends (layering note) [C]. In Godot, a ShaderMaterial reads the masks of §6, rule 11 [I].

### 1.5 Where the generator mixes the layers today

This is from reading the code, not from measuring it.
- **Water marks carry organic colour.** Streak, stain and foot-band marks take green or yellow from family cells (`family_cells`, `dirt_patch`).
- **Dirt places the growth, not water.** `bio_wetness` reads streak and stain opacity as wetness.
- **Green jumps to black on streak paths.** The ink stripes in `layer_bio` turn old growth there toward `bio_Cy` (L* 28).
- **Fix.** Keep water marks and deposits on the dirt palette (I1). Take organic colour only from the growth layer, placed by Wt and Dp.

## 2. The colour continuum of organic staining

### 2.1 What biology says

| Group | Pigment | Colour | When and where | Tag |
|---|---|---|---|---|
| Green algae | chlorophyll | yellow-green tint first; green when established; olive and darker with density | months to years; wet paths, the foot | [M 21] |
| *Trentepohlia* | carotenoids | orange to rust-red; red-brown with dirt | concrete, shaded humid sites (bio note) | [M] (bio note) |
| Cyanobacteria | scytonemin sheath (yellow-brown) | grey to brown-black | the wettest and the sunniest paths | [M 6] |
| Melanised fungi | melanin | black specks and patches that stay after biocide | sunny or dusty faces (bio note) | [C] |
| Lichens | various | grey-green or yellow-orange rosettes | late, on dry exposed tops; 1–6 px dots (bio note) | [C] |
| Old biofilm with soil | mixed | muddy brown | the foot, joints | [I from C 1, 7] |

- A review of facade biofilms names green, black, red and brown spots, from photosynthetic pigments, carotenoids and scytonemin [C 7].
- On the National Museum of the American Indian, dark staining matched the scytonemin of cyanobacteria, and the stone itself was unchanged [M 6].
- One paper's title links phototroph colour to physiological state; I saw only its catalogue record [C 20].

### 2.2 Where biology agrees with the AD's continuum

- **Yellow first: yes.** Greening shows first as a b* rise; the visibility threshold on granite is Δb* +0.59 [M 21].
- **Dark yellow: art direction.** Young films are pale; the darkness comes from the deposit under them [I].
- **Dark green next: yes.** These are established algal films [M 21].
- **Reddish or muddy last: partly.** Old films go brown-black from scytonemin, melanin and trapped soil [M 6, C 7]. Red belongs to *Trentepohlia*, a different organism, on shaded concrete [C]. A reddish lean on every old mark is art direction [I].
- **Lichen yellow and grey: real, but late, small and on dry tops.** They are not a stage of the wet continuum (bio note §3.7) [C].
- **Deposits.** Japan's accelerated soiling powder per test is 0.0135 g yellow ochre, 0.0045 g Kanto loam, 0.001 g carbon black and 0.001 g silica [C 3]. Deposition raised limestone chroma mostly in b* [M 9], and diesel organics may oxidise to brown [P 8].
- **Field dirt stays near neutral.** Our photo walls measured b* −0.26 to +0.67 per 0.1 D (rule I1) [M]. So deposits stay within I1, and growth carries the yellow [I].

### 2.3 Measured colour data that exists

- **Greening on granite** [M 21]: threshold Δb* +0.59 or ΔL* −4.37; established ΔL* −6.1, Δa* −3.4, Δb* +9.8 (bio note).
- **A biofilm-forming cyanobacterium in culture:** hue 129–147° (bio note) [M].
- **Japanese test paints** [M 3]: L* 75.6–76.3, a* −0.9 to −1.5, b* +6.8 to +7.9, close to danchi off-white. Contact angles are 73–95° for ordinary paints, 49–59° for most anti-soiling paints, and 17° for one.
- **Not found:** measured Lab of *Trentepohlia*, lichens, black crusts or mud on facades (§8).

### 2.4 Continuum anchors

Full-strength mark cores on light warm paint (L* 80, a* 1, b* 7). All values are [I], anchored on §2.2–2.3 and bio note §1.3. sRGB is D65, computed this session.

| s | Stage | Mark age (yr) | L* | a* | b* | C* | h° | sRGB |
|---|---|---|---|---|---|---|---|---|
| 0 | first tint | 0–1 | 74 | 1 | 15 | 15 | 86 | #C3B49B |
| 1 | dark yellow | 1–3 | 62 | 2 | 24 | 24 | 85 | #A9936B |
| 2 | olive green | 3–8 | 52 | −8 | 20 | 22 | 112 | #7B7F59 |
| 3 | dark green | 8–15 | 42 | −7 | 14 | 16 | 117 | #61664C |
| 4 | muddy olive-brown | 15–25 | 37 | 1 | 13 | 13 | 86 | #615642 |
| 5 | reddish mud | 25+ | 32 | 7 | 11 | 13 | 58 | #5C473A |
| 6 | crust core (wettest only) | 25+ | 26 | 2 | 4 | 5 | 63 | #433C38 |
| R1 | rust branch (*Trentepohlia*) | 2–8 | 50 | 14 | 26 | 30 | 62 | #9B6D4B |
| R2 | rust branch, dirtier | 8–20 | 40 | 12 | 17 | 21 | 55 | #7A5643 |

How to use the anchors [I]:
- The rust branch runs s1 → R1 → R2 → s5. Adjacent anchors differ by at most 31° in hue and 12 in L*.
- Interpolate in Lab or OKLab along the polyline. Never go straight from yellow to rust through high chroma.
- Composite each pixel as paint, then deposit, then growth, each by its alpha.
- s0–s1 sit at Δb* +3.7 to +4.4 per 0.1 D, inside M1.
- s4 (86°) falls between M2's green and rust hue bands (§7).

### 2.5 The identity rule

All steps are [I].
1. Each organic mark gets an id, a birth time T_b and a rate k = 1 + 2·Wt. T_b comes from the onset of its water path and from the arrival map.
2. Its position is s = clip(k·(t_bio − T_b) / 4 years, 0, 6).
3. Its branch, green or rust, is drawn once from a hash of the id. The rust share is 10–20% on bare concrete and shaded humid paint, and 0–5% elsewhere.
4. Across presets only t_bio changes, so s rises, L* falls and the branch never changes.
5. Marks differ in T_b, so young yellow marks sit beside older green ones at any preset (I4 holds).
6. Target s per preset: Kept ≤ 1 for most marks; Typical ≤ 2; Worn ≤ 3–4; Derelict up to 5–6 in the wettest cores.
7. A water mark without growth keeps the dirt palette (I1). When growth arrives, the composite moves from grey-brown toward s1. It never gets lighter.

### 2.6 Why the current presets flip

- **How a cell picks its family.** `family_cells` draws one random u per cell. The cell is green if u < pg and yellow if u < pg + 0.07, where pg = (0.16 + 0.30·damp + 0.12·shelter) × (0.7 + 0.5·age).
- **The threshold rises with the clock.** On open wall, pg is 0.112 at Kept, 0.138 at Typical, 0.168 at Worn and 0.192 at Derelict. A cell at u = 0.19 is plain dirt at Kept, yellow at Typical and Worn, and green at Derelict.
- **The families are far apart.** A plain streak is L* 30, C* 8. `film_y` is L* 72, C* 36. `film_g_old` is L* 32, C* 23, hue 140°, at ×1.75 opacity.
- **The result.** One streak goes dark grey-brown, then a lighter saturated yellow, then near-black blue-green. That is the AD's "dark gray, then turns yellow, then blackish" [I].
- **Fix.** Draw each mark's family once, with no dependence on E. Move its colour by mark age along §2.4.
- **Kept.** The ×1.40 and ×1.45 family opacity boosts apply even at age 0, which adds to its too-dark stains [I].

## 3. Streaks on panel facades

### 3.1 Vertical joints are the channels

- PCI: "Weathering patterns are determined by the shape and smoothness of the units and joints" [C 2]. It calls joints particularly vulnerable [C 2].
- Water moving sideways or diagonally concentrates at vertical recesses [C 2].
- Vertical ribs and flutes stop run-off spreading sideways, and dirt collects in the hollows [C 2].
- A recess at least as deep as it is wide hides its streak in shadow [C 2]. Danchi PC joints are 19–25 mm wide, with sealant about half as deep (concrete note). So the recess is shallower than it is wide, and the streak shows [I].
- A Japanese survey found rain streaks on 234 of 8,776 buildings (2.7%). It lists joints among the sources, and notes that crack-inducing joints hold dirt [M 4].
- Catchment grows downward: each storey's horizontal joint feeds the vertical joints at its ends and crossings. Width ∝ Q^(1/4), so ten storeys widen a channel ×1.8 at most, or ×1.2–1.5 after evaporation and absorption [I from C 14].

### 3.2 Horizontal grooves and drips feed the faces

- Horizontal ribs spread stains rather than prevent them [C 2].
- A groove or horizontal joint holds water and dirt along its lip. It spills at its low points, at its ends and at joint crossings (r4 §2) [C 2].
- So face streaks start at overflow points and fade within a storey. They stay light because each drains only one panel's width of face [I].
- Water slows at a panel's bottom edge and drops its dirt [C 2]. Expect a faint, darker lip 2–6 cm tall above each horizontal joint [I].
- A drip groove under a slab or coping keeps the wall below clean. Without one, a dirty band and streaks form below (r3, r4) [C 2].

### 3.3 How sealant joints weather

- Ordinary sealants degrade under UV and need repair about every 10 years [P 12].
- Silicone oils bleed into concrete panels, leaving bands on both sides of a joint [P 11]. A band is dark where it catches dust and light where it repels water.
- Japanese makers list two such stains [P 13]: water-repellent staining from silicone oil (撥水汚染), and dust caught by plasticiser bleed (ブリード). ASTM C1248 tests for the early exudation stain [C 18].
- Plasticiser also bleeds into paint over sealant and darkens it (damage note) [P].

- **Likely sequence for a danchi joint** [I]:
  - 0–10 years: a clean joint, with faint dirt on its lips.
  - 10–15 years: bleed bands 10–30 mm wide on each side; the sealant chalks.
  - 15–25 years, unrepaired: the sealant cracks and debonds, so the joint stays damp, growth lines form, and efflorescence gathers at its feet.
  - 25+ years: the open joint shows as a dark line, with growth, lime runs and connector rust.
  - A reseal resets the sealant, but not the stains in the panel edges.

### 3.4 What the photos show

- **Hashima Block 65** (RC flats, abandoned 1974) [P 24]. A dark band runs along every corridor slab edge, with streaks hanging below at intervals. Rust runs follow the column lines. The walls are mottled grey and greener on the lower floors; only the rain-exposed slab fronts are paler. The photo is HDR-processed, so contrast is exaggerated.
- **Pripyat, a nine-storey block** [P 25]: grey mottling over all the render, dark washes from balcony slab ends, and dark slab undersides. There is little colour in this continental climate.
- **Matsuo mine flats** (Iwate, high and snowy; about 50 years abandoned) [P 22, 23]: whole facades are grey-brown. Dark vertical bands run from the parapets and between window columns, merged into curtains. A greenish cast sits low on the gable, near plants.
- **Sendagaya housing**, a kept block [P 26]: clean beige walls, with faint grey streaks on the gable only.
- **Gap:** I found no close photo of a Japanese precast-panel danchi showing joint streaks (§8).

### 3.5 Proposed joint and face marks by preset

All values are [I], from §3.1–3.4 and §4.

| Measure | Kept | Typical | Worn | Derelict |
|---|---|---|---|---|
| Vertical joints with a T2+ streak over ≥ 1 storey | 10–20% | 25–40% | 45–65% | 75–95% |
| Longest joint streak (storeys of 10) | 1–2 | 3–5 | 6–8 | 8–10 |
| Joint band width, T3+ core (m) | 0.03–0.06 | 0.06–0.12 | 0.10–0.20 | 0.15–0.40 |
| Joint band core tier | T2–T3 | T3–T4 | T4–T5 | T4–T6 |
| Face-streak sources per m of groove | 0.1–0.3 | 0.3–0.6 | 0.5–1.0 | 0.8–1.5 |
| Face-streak width (m) | 0.01–0.03 | 0.015–0.04 | 0.02–0.06 | 0.03–0.08 |
| Face-streak length below the groove (m) | 0.2–0.6 | 0.3–1.0 | 0.5–1.5 | 0.8–2.5 |
| Face-streak tier | T2 | T2–T3 | T2–T3 | T3, cores T4 |
| Share of streak D in joint bands (±0.15 m) | ≥ 0.70 | ≥ 0.60 | ≥ 0.55 | ≥ 0.50 |

## 4. How marks grow in area with age

### 4.1 What widens, what lengthens, what only darkens

| Mark | Lengthens | Widens | Darkens | Why | Tag |
|---|---|---|---|---|---|
| Joint channel | yes: deposits, then growth, fill the path | ×3–6 | yes | path fixed by geometry; aged paint wets wider; growth fronts | [I from C 2, 14] |
| Face streak | a little | ×1.5–2.5 | a little | more sources as edges chip and paint chalks | [I] |
| Stain | slowly (log) | slowly | yes, by layering | each wetting adds a rim; leaks add events | [C 17] [I] |
| Foot band | upward ×3–4 | — | yes | splash, salts, growth, plants | [P 15, 16] [I] |
| Growth patch | yes | yes | yes | nucleation, fronts, merging | [M] (bio note) |
| Soiling film | — | already everywhere | yes | dry deposition | [C 2] |
| Efflorescence | yes | — | lighter | more leaks with age | [I] |

### 4.2 Length

- Carried dirt falls off with distance: deposit ∝ E·exp(−x/λ). A run is visible to L_vis = λ·ln(E/E*), where E* is the clock at first visibility [I].
- With E* = 3 and λ = 3 m, L_vis is 1.9 m at Kept, 3.8 m at Typical, 4.7 m at Worn and 5.7 m at Derelict. Deposits alone grow only logarithmically [I].
- Growth then lights the rest of the path. A joint is wet along its full height, so growth there follows the class curves, not the dirt load. By Derelict, sealant failure makes every joint a full-height wet line [I from bio note, P 12].
- Exposure tests show how fast a path appears [M 5]. Some streaks show within about 3 days, and 15 of 23 panels were streaked by 3 months. ΔL ≥ 2 was judged noticeable, and ΔL < 1 nearly invisible.

### 4.3 Width

- A thin rivulet on a vertical wall has half-width a = (105 ν Q / (4 g β³))^(1/4). This is Duffy and Moffatt's result, restated in [14]. So width ∝ Q^(1/4)·β^(−3/4), for flow Q and contact angle β [C 14].
- Fresh test paints had β of 73–95° [M 3]. Chalking and dirt lower β, but I found no field values [I].
- If β falls from 80° to 50°, width grows ×1.4; to 40°, ×1.7. The small-angle law is rough at these angles [I].
- Doubling the catchment (failed sealant, chipped drips) adds ×1.19. Growth fronts then spread into the damp margin at 3–10 cm a year (bio note, W2) [I].
- Together, from Kept to Derelict: joint bands ×3–6, face streaks ×1.5–2.5 [I].

### 4.4 The foot band

- Rain splash can throw soil about 0.6 m up and 1.5 m out [P 16]. The European splash zone is 0.3 m (bio note) [C].
- Rising damp leaves a salt tide mark, rarely above 1.5 m. In one study, rise grew about ×7 from year 1 to year 100 (Mason, secondhand) [P 15]. That is about t^0.42 [I].
- Growth climbs up from the belt where plants shade the foot, as at Matsuo and Hashima [P 22, 24].

Proposed T2+ top of the band, as a median along the wall [I]. Fingers are at downpipes, corners and plants.

| Preset | Median top (m) | Fingers (m) |
|---|---|---|
| Kept | 0.20–0.35 | to 0.5 |
| Typical | 0.30–0.50 | to 0.8 |
| Worn | 0.45–0.80 | to 1.2 |
| Derelict | 0.70–1.20 | 1.5–2.0 |

That is ×3–4 in height from Kept to Derelict, against ×1.3 now [I].

### 4.5 Stains

- Each wetting leaves a rim at its drying front [C 17]. Events differ in extent, so a stain is the union of its rims. Its edge grows with the largest event, roughly as the log of the event count [I].
- So a stain fed by one source darkens far faster than it spreads. Its area jumps when the source grows: a failed joint crossing, a cracked sill, a blocked scupper [I].
- Proposed: stain area ×1.3–1.6 per preset step, half of it from new sources [I].

### 4.6 Growth

Keep the bio note's class curves. The problem is the growth clock [I].

| Preset | Years since repaint R | t_bio, painted (R − 3) | t_bio, joints and bare concrete | N-wall growth T2+ | Generator's t_bio now |
|---|---|---|---|---|---|
| Kept | 4.7 | 1.7 | about 8 | about 2.5% | 1.6 |
| Typical | 5.8 | 2.8 | about 8 | about 5% | 3.1 |
| Worn | 10.3 | 7.3 | about 15 | about 17% | 4.5 |
| Derelict | 14.6 | 11.6 | 30+ | about 28% | 7.1 |

- **Inputs.** R comes from `clock()`. The 3 years are the biocide's protection (bio note §3.6). A repaint does not reset joints or bare concrete, and sealant is renewed about every 10 years at best [P 12]. The t_bio values are [I].
- **Growth shares.** N-wall growth comes from the class curves, with W3 at 4%, W2 at 14% and W1 at 75% of the wall. S walls get about a quarter of it (bio note) [I].
- **Per decade unattended.** At t_bio of 10, 20, 30 and 40 years, the same curves give about 24%, 48%, 60% and 63% on N walls. After the first decade, most of the gain is on shaded open wall (W1), which caps near 60% [I, computed].
- **Result.** The generator's Derelict growth equals the Worn target.

### 4.7 The generator against these targets

| Quantity | Now, Kept to Derelict | Target, Kept to Derelict | See |
|---|---|---|---|
| Channel width | ×1.33 (1 + 0.8 × streak amount) | ×3–6 | §4.3 |
| Main channel reach | 0.70 to 0.93 of the wall | 0.1–0.2 to 0.8–1.0 | §4.2 |
| Main channel opacity before the solver | 0.15 to 0.21 | cores T2–T3 to T4–T6 | §3.5 |
| Foot band height | ×1.32 (amplitude ×4.8) | ×3–4 (amplitude ×2–3) | §4.4 |
| Growth clock | 1.6 to 7.1 years | 1.7 to 11.6 years; joints to 30+ | §4.6 |
| Accent gain at Derelict | 0.47 | ≥ 0.7, with the budget spent on area | §5.3 |

## 5. The derelict end

### 5.1 Coverage at 40–50 years without upkeep

Estimates from the photos (§3.4) and from §4. None is measured.

| Measure | Estimate | Note |
|---|---|---|
| Wall darker than clean (D ≥ T1) | 95–100% | no clean wall remains [P 22–25] |
| Wall at T2+ D_local | 65–85% | the dark background lowers local contrast [I] |
| Wall at T3+ D_local | 35–50% | [I] |
| Storey-bay cells (2.8 × 6 m) with a T3+ mark | ≥ 85% | marks under every slab edge and joint [P 24] |
| Vertical marks at T3+ | 20–35% of the wall | curtains between window columns [P 22] |
| Growth T2+ on N, E and W walls | 20–40% | mostly lower storeys and joints [P 22, 24]; §4.6 |
| Growth T2+ on S walls | 5–10% | a quarter of N (bio note) |
| Foot band T2+ top | 0.7–1.2 m; fingers 1.5–2 m | §4.4 |
| Lighter rain-washed areas | 3–10% | exposed slab fronts, windward corners [P 24] |

Matsuo and Hashima are ruins in harsh climates, with structural decay. They bound the top end; they are not the target [I].

### 5.2 How soiled zones spread beyond the wet spots

1. Once the sealant fails, every vertical joint becomes a channel (§3.3) [I].
2. Face streaks multiply as edges chip and drips fail, because chips become sources (r4) [C].
3. Neighbouring streak margins merge into curtains below grooves and between window columns [P 22].
4. Growth leaves the wet zones. Once the biocide is spent, shaded open wall (W1) colonises with fronts of 1–3 cm a year (bio note), up to 15–30% [I].
5. The foot band climbs with damp, salts and plants (§4.4) [I].
6. With no washing, dry deposition darkens the whole background, so single marks read as one field [C 2].
7. Leaks at failed joint crossings add stains that spread down a storey or two [I].

### 5.3 Derelict against the rulebook

- At E 19.8, A1 allows T2+ 0.42–0.78 and T3+ 0.20–0.45. Photos of ruins sit near the E 27.1 bands (T2+ 0.70–0.96) [M rulebook] [P].
- Derelict should sit in the upper half of its bands, at T2+ 0.65–0.78 and T3+ 0.35–0.45. T5+ and T6+ stay in their bands, so the extra budget buys area at T2–T4 [I].
- The solver now lowers Derelict's accent gain to 0.47 to hold T6+ (rulebook revisions), which lightens every mark. Better: cap the cores, and widen and multiply the marks [I].

## 6. Generator rules

All numbers are [I] unless a rule cites a section.

1. **Water first, from geometry and age, not E.** Weight Wp: vertical joints 1.0, failed-sealant crossings 0.8 (from sealant age 15), sill ends 0.6, slab edges without drips 0.5, groove overflow points 0.25 (low points, ends, within 0.1 m of crossings). Wt = max(splash, Wp blurred 0.1–0.3 m sideways and 0.3–1.5 m down, shelter damp) × orientation, as now. Export Wt.
2. **Water marks from Wt.** Tide rims 1–3 cm wide at T2–T3, on the dry side of the Wt 0.4 and 0.7 contours. Washed cores T1–T2 lighter where Wp ≥ 0.8 and E ≥ 12. Efflorescence at joint feet and crossings from age 15.
3. **Deposits from E, redistributed by Wp.** +30–80% at path margins (0.05–0.2 m beside a channel) and at path ends, including the 0.1 m above each horizontal joint. −20–55% in channel cores after E 12. Colour within I1.
4. **Growth.** Rate ∝ Wt² × clip(0.5 + Dp / mean Dp, 0.5, 2). t_bio = max(0, R − 3) on painted wall, and min(age, sealant age) in joints and on bare concrete. No growth where Wt < 0.15 before 10 years.
5. **Colour by mark age.** Follow the §2.4 polyline, with the branch fixed per mark id; L* never rises between presets. Remove the family thresholds that depend on E, and the ×1.40–1.75 opacity boosts.
6. **Joints against faces.** Put 60–70% of the streak budget on vertical joints. Face streaks start only at groove overflow points, at no more than 0.35× the joint channel's opacity at the same height. Counts and widths follow §3.5.
7. **Channel width.** Use w0 × (1 + 0.5(k − 1))^(1/4) for k storeys of catchment. Multiply by a paint-age factor of 1.0, 1.25, 1.5 and 1.8 from Kept to Derelict, and add the growth margin from rule 4.
8. **Area per preset step.** Streak and stain T2+ area ×1.3–1.6. Growth ×1.5–3 while W2–W3 is under 85% covered. Foot-band top +0.1–0.4 m. At least half of each step's added D falls on newly covered pixels.
9. **Derelict.** Keep the accent gain at 0.7 or more. Meet T6+ by capping cores beyond T6 at 3% of the wall, not by dimming every mark.
10. **Kept.** Marks stay at s ≤ 1. No mark core goes beyond T4, except at T5 on at most 0.3% of the wall.
11. **Engine masks.** One RGBA8 per plane in facade UV: R = Wt, G = Dp, B = growth density, A = growth age s/6. A second mask holds efflorescence, rust and washed cores. Bake albedo, roughness and normal from these; the shader adds rain wetness from R.

## 7. Proposed gate rules

These follow the rulebook format.
- **Water marks** are deposit-layer pixels at T2+ where Wt ≥ 0.40.
- **Organic marks** are connected growth regions at T2+.
- **Matching across presets** uses the mark id, or IoU ≥ 0.5 at T2+.

**V1. Growth grows out of water and deposits** (layering)
- Measure: (a) the share of water-mark area with growth at T2+; (b) the share of growth T2+ on a water mark or within 0.1 m of one.
- Pass: (a) rises every step, within Kept 0.05–0.25, Typical 0.15–0.40, Worn 0.40–0.80, Derelict 0.60–0.95; (b) ≥ 0.85 up to Worn, ≥ 0.60 at Derelict.
- Origin: U (round I: "one is a growth from the other"); L [1, 2]; C (the bands come from the bio note's class curves).

**V2. A mark keeps its colour identity** (colour)
- Measure: for organic marks matched across consecutive presets, the T3+ core's mean Lab; its position s (nearest point on the §2.4 polyline or rust branch); its ΔE00 from that polyline.
- Pass:
  - For ≥ 98% of marks, s never falls and L* rises by at most 1.0.
  - No mark moves from green back to yellow, or from mud back to green.
  - ΔE00 ≤ 8 for ≥ 85% of organic-mark pixels.
- There is no cap on each step, since a wet mark may pass several anchors at once. Staying on the polyline keeps it continuous.
- Origin: U (round I: "keep it on a continuum"); L (yellowing, then greening, then darkening [21]; scytonemin browning [6]); C.

**V3. Joints carry the streaks; faces stay light** (placement)
- Measure, on planes with vertical joints, with sill-end streaks counted apart: (a) the share of the streak layer's summed D within 0.15 m of a vertical joint; (b) the mean streak D on the faces over that in the joint bands; (c) the share of face streaks 0.3 m or taller whose top lies within 0.15 m below a groove, joint or sill.
- Pass: (a) per §3.5, ≥ 0.70 at Kept falling to ≥ 0.50 at Derelict; (b) ≤ 0.35; (c) ≥ 0.90. Face streaks at T4+ cover ≤ 0.5% of the face up to Typical.
- Origin: U (round I); L (vertical recesses gather run-off and dirt, horizontal ribs spread stains [2]; joints hold dirt [4]); C.

**V4. Each preset step adds area** (time; extends L1 to the presets)
- Measure, between consecutive presets, for streaks, stains, the foot band and growth: the T2+ area ratio; the share of added summed D on new pixels; the median core width of matched joint channels; the foot band's median T2+ top.
- Pass:
  - Streak and stain area grows ×1.3 or more per step.
  - Growth area grows ×1.5 or more per step while W2–W3 is under 85% covered.
  - The new-pixel share is ≥ 0.5.
  - Channel width grows ×1.15 or more per step, and ×1.8 or more from Kept to Derelict.
  - The foot band stays in the §4.4 bands and rises ≥ 0.1 m per step.
- Origin: U (round I: "surface area", "placement and coverage"; round F L1); L (rivulet law [14], rising damp [15], growth kinetics in the bio note); C.

**V5. Kept stays light; Derelict spreads** (amount)
- Measure at Kept: the wall share at D_local T5+ from marks, and the 99th percentile of mark D_local.
- Measure at Derelict: storey-bay cells with a T3+ mark; the share of T3+ area outside W2–W3; growth T2+ on N walls.
- Pass at Kept: T5+ ≤ 0.3% and P99 ≤ 0.30.
- Pass at Derelict: cells ≥ 85%, the outside share ≥ 35%, N growth ≥ 20%.
- Origin: U (round I: Kept's "darker stains look a little too dark"; Derelict "mostly in the same areas"); P (§5.1); C.

**Knock-on revisions**
- **M2:** add a mud band (hue 55–95°, C* 8–16, L* ≤ 45), or stage s4 fails.
- **I4 and I5:** both leave growth out, so with neutral water marks they find no organic colour. Measure I4 on marks plus growth, or replace it with V2; M9 already covers I5.
- **A1:** with the AD's agreement, raise Derelict's T2+ and T3+ lower bounds to 0.60 and 0.32 (§5.3).

## 8. What I could not find

- **Joint and sealant bands.** No measured widths for joint streaks or sealant bleed bands; §3.5 is [I].
- **Facade colours.** No measured Lab or sRGB for *Trentepohlia*, lichens, black crusts or muddy biofilm on facades. Only the greening shifts [21] and culture hues exist.
- **Streak growth over time.** No time series of streak length or width. Exposure tests give visibility and ΔL only [5].
- **Soiled area by building age.** No Japanese survey of soiled-area share by age; only incidence by building count [4].
- **Contact angles of chalked paint.** None found. The ×1.4–1.7 width factor assumes a fall from 80° to 40–50°.
- **Primary sources for three figures.** The splash heights (Ellison) [16], the ×7 rising-damp factor (Mason) [15] and Escadeillas Part 2's coverage data [19] are all secondhand.
- **Unread once the budget ran out.** Lagarde's wet-surface measurements (404), the Grossi 2008 full text (certificate error) and the facade-biofilm review entry (403).
- **Photos.** No close photo of a Japanese precast-panel danchi with joint streaks on Commons. Hashima, Pripyat and Matsuo differ from our block in climate and structure.

## 9. Sources

How each source was used:
- Read in full text or PDF: 1, 2, 3, 11, 12, 14.
- From a search summary, abstract or record only: 4–10, 13, 15, 16, 18–21.
- Not read (paywalled textbook physics): 17.
- Photos viewed on Wikimedia Commons: 22–26.

1. Sanmartín, Miller, Prieto, Viles 2021, "Revisiting and reanalysing the concept of bioreceptivity 25 years on", *Sci. Total Environ.* 770: https://minerva.usc.gal/entities/publication/d437eb77-2cd7-4dfe-ab61-b9d50ad9aa14 (PDF: https://minerva.usc.gal/bitstreams/372a20ec-57ff-4fdb-9684-fedc695d29ea/download)
2. PCI, Designer's Notebook DN-29, Weathering: https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf
3. 林怡伶, 永井香織, 松井勇 2011, 建築外装材料の雨筋よごれの評価 −促進試験の結果− (Nihon Univ. CIT, 44th meeting): https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.44/pdf/4-8.pdf
4. Nihon Univ. CIT, rain-streak field surveys. Incidence (2010): https://www.cit.nihon-u.ac.jp/kouendata/No.43/4_kenchiku/4-004.pdf ; source classes (2011): https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.44/pdf/4-9.pdf
5. Nihon Univ. CIT, rain-streak exposure tests (which report gives which figure is unconfirmed): https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.48/pdf/4-32.pdf ; https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.58/pdf/4-42.pdf
6. Cappitelli et al., "Cyanobacteria cause black staining of the National Museum of the American Indian Building, Washington D.C., USA": https://air.unimi.it/handle/2434/173212
7. Encyclopedia entry on facade biofilms and their pigments: https://encyclopedia.pub/entry/3579
8. Grossi, Brimblecombe 2008, "Past and future colouring patterns of historic stone buildings", *Materiales de Construcción*: https://materconstrucc.revistas.csic.es/index.php/materconstrucc/article/view/81
9. Grossi, Brimblecombe, Esbert, Alonso 2007, "Color changes in architectural limestones from pollution and cleaning", *Color Res. Appl.*: https://ueaeprints.uea.ac.uk/id/eprint/25076/
10. Brimblecombe, Grossi 2005, "Aesthetic thresholds and blackening of stone buildings": https://ueaeprints.uea.ac.uk/id/eprint/26507/ ; acceptability of soiling patterns (EGU 2005): https://meetings.copernicus.org/www.cosis.net/abstracts/EGU05/01792/EGU05-J-01792.pdf
11. Prosoco, Guide to common masonry stains (silicone sealant bleed): https://prosoco.com/app/uploads/2018/11/guide-to-common-masonry-stains-pamphlet.pdf
12. Hokkaido Research Organization, sealant-less ceramic cladding (sealant repair about every 10 years): https://www.hro.or.jp/upload/23427/28.pdf
13. Sika Japan, modified-silicone sealant catalogue (silicone-oil and plasticiser staining): https://jpn.sika.com/dam/dms/jp01/l/catalog_ms1nb_lm.pdf
14. Wilson, Duffy, thin rivulet on a vertical substrate (restates Duffy and Moffatt 1995): https://www.iscst.com/wp-content/uploads/2015/06/WilsonDuffy.pdf
15. Safeguard Europe, rising damp and mortar properties (Mason): https://safeguardeurope.com/whitepapers/rising-damp-in-masonry-walls-and-the-importance-of-mortar-properties ; Building Conservation, rising damp and tide marks: https://buildingconservation.com/articles/risingdamp/risingdamp.htm
16. Splash erosion heights (study guide, low authority): https://open-exam-prep.com/study-guides/cpesc/soil-erosion-mechanics-types/water-erosion-mechanics
17. Deegan et al. 1997, "Capillary flow as the cause of ring stains from dried liquid drops", *Nature* 389: https://www.nature.com/articles/39827
18. ASTM C1248, staining of porous substrates by joint sealants: https://store.astm.org/c1248-22.html
19. Escadeillas et al. 2009, biological stain growth on concrete walls, Part 2, *Mater. Struct.*: https://link.springer.com/article/10.1617/s11527-008-9433-3
20. Prieto, Rivas, Silva 2002, "Rapid quantification of phototrophic microorganisms and their physiological state through their colour", *Biofouling* 18: https://portalcientifico.uvigo.gal/documentos/5d95a3ce2999525d7e9515b0
21. Sanmartín et al. 2012, greening on granite buildings (bio note S1): https://minerva.usc.gal/entities/publication/6772f545-d7d5-4de3-873c-e5fbf5002846
22. Photo: Matsuo Mine apartment complex in 2024: https://commons.wikimedia.org/wiki/File:Matsuo_Mine_apartment_complex_in_2024.jpg
23. Photo: Ruins of apartment buildings of Matsuo Mine, 2023: https://commons.wikimedia.org/wiki/File:Ruins_of_apartment_buildings_of_Matsuo_Mine_20231014.jpg
24. Photo: Block 65 on Hashima Island: https://commons.wikimedia.org/wiki/File:Block_65_on_Hashima_Island.jpg
25. Photo: Apartment building, Pripyat: https://commons.wikimedia.org/wiki/File:Apartment_building_Pripyat_hnapel_001.jpg
26. Photo: 千駄ヶ谷住宅 (Sendagaya housing): https://commons.wikimedia.org/wiki/File:%E5%8D%83%E9%A7%84%E3%83%B6%E8%B0%B7%E4%BD%8F%E5%AE%85.jpg
