# Rust on balcony rails: water paths, runs and concrete stains

Date: 2026-11-01. For `layer_rust` in `scripts/weathering/weather_fields.py` and rules R1–R2 in `weather_rules.json` (rulebook 1.5).

**The asset.** A 10-storey RC slab block, about 30 m tall and 82 m long. Every storey's balcony slab edge carries a painted steel rail. The kit has two kinds of rail (`examples/danchi/src/py/pieces.py`):
- **Open rail.** 44 mm posts at 1.3 m or less, set in a 100 mm concrete upstand. Top rail 45 × 64 mm at 1.12–1.165 m; bottom rail 30 mm at 0.16–0.19 m; 16 mm balusters at 110 mm. Below the rail, 0.25 m of painted slab edge (upstand and nose) ends in a drip groove 22–35 mm in from the face.
- **Parapet handrail.** 32 mm posts on 90 mm base plates on the parapet top. The top slopes inward 20 mm over 150 mm.
- **Resolution.** At 50 px/m a baluster is under 1 px wide and the top rail about 2 px tall.

**Why.** The art director asked for rust that builds along the top rail, drips, gathers along the bottom rail, runs down the uprights, and streaks the concrete at the posts. It should grow "along the surfaces most affected by water", not radially, and today it is "still too little".

## Conventions

- **Tags.** [C] standard or consensus; [P] a practitioner's observation; [M] measured data; [I] my inference.
- **[M, photo]** is my own reading of a photo this session. Scale comes from a known object, ±30 %. Colours are camera-JPEG sRGB converted to CIELAB D65, ±5 L*.
- **†** marks a source that a helper agent read this session and I did not reopen. I opened all the others.
- **Sn** is source n in §9.
- **Search budget.** The shared web-search budget ran out partway through. §8 lists what was never searched.

## 0. Summary

1. **Water decides where rust starts.** The order is:
   - post feet and anchor pockets, which hold standing water and go wet and dry at the concrete line [P S18, S19];
   - joints and welds, where 50–90 % of attacks start [M S6];
   - the top rail's upper face, as horizontal steel corrodes 2–3× faster than vertical [M S8];
   - the bottom rail, a water and debris trap [I];
   - upright faces last [P S43].
2. **Rust creeps under paint only 0.1–3.5 mm a year per defect,** linearly once it starts [M S13–S15]. At 2 cm/px that is under a pixel a year. Visible growth comes from new sites on the same wet lines, creep along wet arrises, and runs. So it runs along the members, not outward [I].
3. **Runs on vertical faces keep their width or narrow; they do not fan out.** A dark head 1.6–2.6× the tail's width fills the top quarter [M, photo S44c–d]. Below a rusted member, 42 % of the width is stained at 0.1 m and 7 % at 1.0 m [M, photo S44c].
4. **Concrete stains start at post feet and drip points.** In a UK survey, walls under balcony railings were stained on 24 % of buildings and copings under railings on 57 % [M S25†]. Later, rust in the pockets spalls the slab edge's outer corner; patch repairs last 5–10 years [P S20, S19].
5. **Upkeep matters more than age.** Japan repaints rain-exposed steel every 5–7 years, naming balcony rails, and replaces rails at 34–38 years [C S29]. ISO 12944 counts a paint's life up to Ri 3 (1 % rusted) [C S3†, S4†]. Ordinary upkeep therefore keeps rails near Ri 1–3; poor upkeep reaches Ri 4 in about 10 years and Ri 5 in about 20 [I].
6. **Colour** [M, photo]:

   | Where | L* | a* | b* |
   |---|---|---|---|
   | stain heads | 30–35 | +19–20 | +25–29 |
   | stain tails | 45–50 | +7–9 | +25–32 |
   | rust on the rails | 34–41 | +10–11 | +15–18 |

   Wetting darkens concrete by 9–20 L* but dark rust by only 3–5 [M S39†; I from S41†].
7. **Rules.** Eleven generator rules (§7.1) and four gate rules, R3–R6 (§7.2).

## 1. Where corrosion starts

### 1.1 Time of wetness by part

Time of wetness (TOW) counts the hours with RH > 80 % and T > 0 °C. Most outdoor sites are class τ4, with 2,500–5,500 h a year [C S5†]. No source gives TOW per rail part, so the factors below are my estimates. The last column gives the evidence behind each.

| Part | Why it stays wet | TOW vs top rail [I] | Evidence |
|---|---|---|---|
| Post foot, anchor pocket, base plate | water stands in the pocket and hollow posts; wet–dry line at the concrete | 3–5 | guardrail posts rot in two zones: 乾湿を繰り返すコンクリート天端部分 (the wet–dry concrete top) and inside the water-filled pocket [P S18] |
| Rail–upright joint (±3 cm) | weld or crevice holds water; uprights drain the rail's underside | 2–3 | 50–90 % of attacks start at edges and welds [M S6]; about 90 % of bridge girders rusted anywhere are also rusted at the outer girder ends [M S7] |
| Bottom rail, upper face | catches water off the balusters and some top-rail drips; holds dust and leaves; splash from the upstand 6 cm below | 1.5–2 | ISO 12944-3: avoid water and debris traps [C S12†]; 1954 railings rusted worst on horizontal rails and socket feet [P S24†] |
| Top rail, upper face and arrises | horizontal; catches rain; thin paint on arrises; worn by futons, laundry, clips and hands [I] | 1 | horizontal steel corrodes 2–3× faster than vertical on the same wall [M S8]; 9 of 10 Japanese railings were worst on rail tops [P S43] |
| Rail lower arris and underside | drops hang there; not rain-washed, so salt stays | 0.8–1.3 | sheltered steel corrodes 3–5× faster where salt is high [P S9]; at a low-salt site exposed steel corroded more [M S8] |
| Upright faces | vertical, so water sheds fast; rain-washed | 0.3–0.5 | vertical samples corroded least [M S8]; balusters mostly sound [P S43] |

- **BRANZ** measured first-year mild-steel loss on one house [M S8]. Horizontal samples lost 127–245 g/m²·a, 45° samples 107–170, and vertical samples 33–92 (16–31, 14–22 and 4–12 µm/a). In their words, "the horizontal samples showed the highest corrosion".
- **Wind-driven rain.** "Typically, the top corners are most wetted, followed by the top and side edges" [C S31]. In Choi's model of a 40 m tower at a 10 m/s reference wind, the top quarter caught 0.41–0.47 of horizontal rain and the bottom quarter 0.05–0.11; the side strips caught 1.1–1.8× the centre [M S31].
- **What this means here.** A rail sits 75 mm inside the slab edge above, so only rain within 3° of vertical misses it. The top storeys and end bays have the wettest rails [I, geometry].

### 1.2 Coating failure

- **Edges.** Wet paint pulls back from sharp edges as it cures, so the film there is thin: "corrosion mainly initiates at edges and welds" [M S6].
  - Edge retention is the film at an edge as a share of the film on the flat. It was 39 % for a plain sprayed epoxy and 85 % with fibre added; a US Navy specification asks for a 70 % mean [M/C S10†].
  - ISO 8501-3 grade P3 rounds edges to r ≥ 2 mm [C S11†]. A square hollow rail has four long arrises, so its paint fails along lines [I].
- **Welds.** Spatter, porosity and undercut break the film [C S11†]. On girder ends, rust lines up along welds and free edges [M S7†, chapter 3].
- **Fasteners and damage.** Bolts and clamp screws make crevices and leave thin paint on the threads [I]; ISO 12944-3 asks for gaps to be sealed [C S12†]. Dents blister, then rust [M S14†].

### 1.3 Crevices and hollow sections

- **Pockets.** Three things expand in a post pocket and crack the concrete: wet gypsum grout, whose near-neutral pH also stops protecting the steel; frost; and rust on the post or its sleeve. "The concrete around a rail post pocket cracks, then spalls" [P S19].
- **Remedies** [P S19]: fill the pocket fully, crown the grout, add a sealant bead (which needs upkeep), and put weep holes at the base of hollow posts.
- **Hollow posts.** Guardrail posts held rainwater from the pocket, from condensation and from bolt holes; after long service the steel inside had turned to mud [P S18]. Hollow rails leaked at their joints and frost burst the posts [P S22†]. ISO 12944-3 says to seal or drain hollow sections [C S12†].

### 1.4 Ranked by how early they rust

| Rank | Spot | First visible rust after a repaint (C3 site, alkyd) [I] | Numbers |
|---|---|---|---|
| 1 | post feet, pockets, base plates | 1–3 years; old rust is seldom cleaned out, so it returns | two rot zones at guardrail feet [P S18] |
| 2 | rail–upright joints, welds, bolt heads | 2–4 | 50–90 % of attacks [M S6] |
| 3 | top rail, upper arrises and face | 3–5 | 2–3× the vertical rate [M S8] |
| 4 | bottom rail, upper face | 3–6 | water and debris trap [C S12†] |
| 5 | rail lower arrises (drip lines) | 4–7 | sheltered, unwashed [P S9] |
| 6 | upright faces | 7–15, mostly as runs | balusters sound [P S43] |

At Brunswick in the UK, stains were severe 3 years after old rust had been painted over [P S25†]. Rust left under new paint keeps spreading [P S27†].

## 2. How rust spreads

| Measure | Value | Source |
|---|---|---|
| scribe creep, 2 years, marine site (New Jersey) | acrylic 4.3 mm, epoxy 7.0, polyurethane 6.0, zinc-rich about 0.5 | [M S13] |
| how creep grows | "grow linearly with test time after the first detection time" | [M S13] |
| creep, 18–24 months outdoors | calcium-sulfonate alkyd 0.7–1.0 mm; urethane mastic 0.7–6.6 | [M S14†] |
| two-coat alkyd (80 µm), 4 years | ASTM D1654 rating 8–5, about 0.5–5 mm | [M S15†] |
| per side, per year | about 0.1–3.5 mm | [I] |

- **Creep needs water.** In lab tests, wet–dry cycling drove scribe creep most [M S17†]. So creep is fastest along wet lines: arrises, joints and the bottom rail [I].
- **Direction.** Salt builds up at the lower end of vertical scribes [P S16†]. I found no measured ratio of creep below a defect to creep above it. A downward bias is my inference [I].
- **Blisters.** Blisters (ISO 4628-2) come before rust under alkyds and at dents, then fill with rust [M S14†].
- **Swelling.** Per mole of iron, magnetite and hematite take 2.1× the iron's volume, goethite 2.9×, lepidocrocite 3.1× and Fe(OH)₂ 3.7× [I, from mineral densities; the oxides agree with S45†]. Porous, hydrated rust takes up to about 7× [P S27†]. The swelling lifts paint ahead of the visible front and packs crevices [I].
- **At 2 cm/px,** creep moves a front one pixel in 6–20 years. Each control step should therefore add three things, not radial rings: new sites on the same wet line, longer segments along arrises, and runs below [I].

## 3. Runs and drips

- **Where runs form:** rail lower arrises, the feet of uprights where water leaves the steel, joints, and frame corners [P S43; M, photo S44c].
- **Under a rusted grille in Poland,** 4 of 6 streaks start within 4 cm of an upright's foot, and the frame corner gives the longest streak [M, photo S44c].

| Measure | Value | Source |
|---|---|---|
| width at source, single run | 1–4 cm (Japanese railings) | [P S43] |
| width just below a rusted member | 3–9 cm single; 6–31 cm merged | [M, photo S44c] |
| length | 0.3–1.5 m (Japan); 1.2 m or more (Poland, running off the photo) | [P S43; M, photo S44c] |
| share of the width stained below the member | 42 % at 0.1 m, 39 % at 0.2, 31 % at 0.4, 21 % at 0.6, 11 % at 0.8, 7 % at 1.0 | [M, photo S44c] |
| shape on a vertical face | head 1.6–2.6× the tail's width over the top quarter; tail tapers into fingers 1–2 cm wide | [M, photo S44c–d] |
| runs from pipe brackets, Soshigaya | 0.6–0.9 m long, 4–9 cm wide at the top, tapering | [M, photo S44a] |
| drip spacing under a wet horizontal edge | about 24 mm (2π√2 × capillary length 2.7 mm) | [I from S42] |

- **Uprights act as drains.** They carry the water that hangs under the top rail down to the bottom rail and the feet [I].
- **Top-rail drips** leave its lower arrises, 32 mm either side of its centre line, and fall 0.93 m. Most miss the 30 mm bottom rail and land on the upstand top, so they feed the drip curtain on the slab edge too [I, geometry].
- **Runs on steel** reach 5–40 cm below rusted joints. On derelict stairs whole uprights rust, while a newer rail beside them stays white [M, photo S44a].
- **Growth.** A run reaches the end of its path within a few wet seasons, because the water path is fixed. After that it darkens and widens [I]. At Brunswick, stains spread and deepened when repainting was put off [P S25†].

## 4. Rust stains on concrete

- **At post feet** a black-and-rust halo, 5–10 cm across, forms on the concrete [P S43].
- **Shape** [M, photo S44c–d; I for this slab edge]. A halo or fan 5–10 cm in radius forms on the horizontal upstand top. Over the front arris, a head as wide as the halo (10–20 cm). Down the face, a tail 0.3–0.7× the head's width, in fingers. The stain ends at the next joint or edge; the Moscow stains stop at the block joint.
- **Reach.** The path here is short: 0.25 m of face, then 22–35 mm under the nose to the drip groove. A stain gets there within 1–3 years of its foot rusting [I, geometry].
- **Parapet handrail.** The parapet top slopes inward, so stains from the base plates run to the balcony side. The Soshigaya parapets show grey run-off but almost no rust below rusted handrails [M, photo S44a]. At most 30 % of plates should mark the outer face, each for 0.2 m or less [I].
- **How often.** At Brunswick, copings under railings were stained on 57 % of buildings and walls under balcony railings on 24 %. Windward, sea-facing fronts were worst [M S25†].
- **How it forms.** Iron leaves the steel dissolved and nearly colourless. It turns rust-coloured where the water spreads and dries [P S26†]. Fresh stains wash off, but later they set as stable oxide in the pores [C S26†].
- **Rust jacking.**
  - About 15–50 µm of steel loss cracks 20–30 mm of cover, 0.05–0.1 mm wide [M S28, not opened].
  - The commonest balcony failure is "spalling that occurs to the outside corner due to corrosion of the railing post", and patch repairs last 5–10 years [P S20].
  - In one building, post pockets 100 mm wide and deep sat 75–150 mm from the slab edge [M S21†]. In Toronto, slab edges spalled badly around embedded rail plates [P S23†].
- **Timeline here** [I], for a 44 mm post with 30–50 mm of cover in a 100 mm upstand. A hairline crack bleeding rust runs from the post to the face 5–15 years after the foot's seal fails. At 10–25 years, a wedge spall 0.1–0.2 m wide breaks off the outer top corner.

## 5. Progression over the years

| ISO 4628-3 | Ri 0 | Ri 1 | Ri 2 | Ri 3 | Ri 4 | Ri 5 | — |
|---|---|---|---|---|---|---|---|
| rusted area [C S1†] | 0 % | 0.05 % | 0.5 % | 1 % | 8 % | 40–50 % | > 50 % |
| ASTM D610 [C S1†, S2†] | 10 | 9 | 7 | 6 | 4 | 1–2 | 0 |

- **ISO 12944-1** defines durability as the years to the first major repaint: L ≤ 7, M 7–15, H 15–25, VH > 25 [C S3†]. The trigger is usually Ri 3; one paint maker's example is Ri 3 on 10 % of surfaces [P S4†].
- **Japan.** MLIT's 2024 guideline sets 鉄部塗装（雨掛かり部分）, the repainting of rain-exposed steel, at 5–7 years and names balcony rails. Walls are repainted every 12–15 years and rails replaced at 34–38 [C S29]. The guideline covers condominiums; I found no cycle for UR or public rental danchi.
- **UK.** A local Act requires the Brunswick facades and railings to be repainted every fifth year [C S25†]. Social landlords decorate on 7-year cycles, and one says the paint lasts about 5 [P S30†].

By years since the steel was last repainted, at a C3 site with alkyd on hand-cleaned steel [I, anchored on S3, S13, S25, S29, S44a]:

| Years | Grade | What rusts |
|---|---|---|
| 0–2 | Ri 0–1 | painted-over rust at the feet bleeds through |
| 2–4 | Ri 1–2 | feet, joint welds, first spots on the top rail's arrises |
| 4–7 | Ri 2–3 | top-rail segments, bottom-rail joints, first slab-edge stains; the MLIT repaint is due |
| 7–12 | Ri 3–4 | long top-rail segments; a band on the bottom rail; runs 5–15 cm down uprights; stains at most feet |
| 12–20 | Ri 4–5 | most of the top rail, its paint left as islands; the bottom rail; runs 15–40 cm; a drip curtain on the slab edge |
| 20+ | Ri 5 to ASTM 0 | uprights rusted for most of their length; metal lost at the feet; pockets crack and spall |

- **Ordinary upkeep** (repaint every 5–7 years). Faces cycle between Ri 0 and Ri 3, but feet and joints keep their rust under the new paint [P S25†, S27†]. Concrete stains outlive steel repaints until the wall is repainted every 12–15 years [I from S29].
- **Poor upkeep.** Ri 4 at about 10 years and Ri 5 at about 20 [I].
- **Order** [I from §1]: feet and joints first, then the top rail's upper face, the bottom rail, runs down the uprights, and the upright faces last.

## 6. Colour by age and wetness

| Sample | L* | a* | b* | Source |
|---|---|---|---|---|
| lepidocrocite (fresh orange rust), 6.8YR 5.5/8.2 | ≈ 56 | — | — | [M S32†; L* from Munsell value, I] |
| goethite (yellow-brown), 0.4Y 6.0/6.9 | ≈ 61 | ≈ 8 | ≈ 45 | [M S32†, S33†] |
| hematite (red), 1.2YR 3.6/5.2 | ≈ 37 | ≈ 20 | ≈ 16.5 | [M S32†, S33†] |
| akaganeite (chloride rust), 5.2YR 3.8/5.8 | ≈ 39 | — | — | [M S32†] |
| red / yellow iron-oxide pigment | 36–44 / 61–63 | 24–30 / 9–15 | 14–26 / 43–49 | [M S34†, S35†] |
| magnetite pigment (black rust) | 25.5 | 0.8 | 0.4 | [M S35†] |
| weathering-steel patina, Madrid, 3 / 6 / 12–24 months | 33 / 29 / 33 | 15 / 17 / 15 | 24 / 23 / 20 | [M S36†] |
| Soshigaya rails, rust pixels: median (sunlit p90) | 34–41 (58–76) | 10–11 (13–19) | 15–18 (19–30) | [M, photo S44a] |
| Moscow stain heads / tails (on stone, L* 54) | 30–35 / 45–50 | 19–20 / 7–13 | 25–29 / 25–33 | [M, photo S44d] |
| Polish streaks on paint (L* 62): at source / 0.6–0.9 m down | 38 / 49–50 | 6 / 8 | 21 / 30–32 | [M, photo S44c] |
| generator today: `rust` / `rust_bar` | 42.6 / 32.7 | 13.9 / 10.0 | 26.3 / 19.5 | [I, from COL] |

- **Age.** Weathering steel goes from yellowish to brown to blackish brown within 1–2 years [P S37†]. Marine rust starts ochre and turns dull brown [P S38†]. The inner layer is dark grey goethite and magnetite [M S38†], so the oldest rust, at feet and joints, is the darkest [I].
- **Density.** A dense stain head is darker and redder, at hue 52–56°. A thin tail is lighter and yellower, at hue 68–75° [M, photo]. Diluting iron oxide lowers its chroma [M S32†].
- **Wet against dry.** Wet stone darkened by 9–20 L* [M S39†], and wet soil by 1.0–1.7 Munsell value, about 10–17 L* [M S40†]. A thin-film model gives −3.5 to −4.3 L* for dark rust (L* 33) and −8 to −9 for orange rust (L* 50) [I from S41†]. So wet stains lose contrast against wet paint. The atlas is baked, so any wetness belongs in an engine mask [I].

## 7. Rules

### 7.1 Generator rules

1. **Members.** Split `plane["steel"]` into four parts.
   - Rails are horizontal runs ≥ 0.3 m long and ≤ 0.07 m tall; the highest is the top rail.
   - Uprights are vertical runs ≥ 0.15 m. Joints are upright pixels within 0.04 m (2 px) of a rail.
   - Feet are the lowest 0.1 m of uprights standing on paint (`fixings` of kind "post").
2. **Water flow.** Rain on a rail top drains over both arrises and hangs on the lower arris. Uprights carry it down from the rail above, the bottom rail collects it, and the feet pass it to the concrete.
   - Wetness w, with the top-rail face at 1: feet 3.0, joints 2.0, bottom rail 1.8, top rail 1.0 (upper row 1.2, lower row 0.9).
   - On uprights, w is 0.8·exp(−d / 0.15 m) at depth d below a joint, and 0.35 on other faces.
3. **Exposure.** Multiply w by E [I from S31, softened]. By storey, E rises linearly from 0.6 in the bottom quarter to 1.6 in the top quarter. It is ×1.3 on the two end bays, ×1.2 on windward faces and ×0.8 on lee faces. Clamp E to 0.5–2.
4. **Seeds.** Seed every foot and every joint, and the top rail's upper row every 0.2–0.4 m. Each seed starts at t₀ = c / w × U(0.8, 1.25), in units of the clock at which Ri 5 is reached.
   - c is 0.10 at feet, 0.20 at joints, 0.30 on the top rail, 0.35 on the bottom rail, 0.50 at lower arrises and 0.85 on upright faces.
5. **Arrival time.** T(p) = minₛ [t₀(s) + Σ Δℓ / (w·k)], by min-plus sweeps over the steel; the growth layer's arrival-time scans can be reused (`weathering-organic-growth.md` §0.5).
   - k is 1 along rails, 2.5 downward on uprights, 0.3 upward and 3 across a member, so a member's width fills at once. Add ±0.03 noise to break ties.
6. **Control.** Rust at amount a is {T ≤ T\*}, where T\* is the quantile that gives `rust_share(a)`, so R1 holds as now. Each step adds the next band of T: segment ends and the pixels downstream.
   - Drop the isotropic terms (`gfield` at 0.6 m and 8 cm, and the Gaussian edge falloff) from the ordering. Keep noise only as speckle within 0.04 m of the front, and make `low` favour each rail's upper row.
7. **Order targets** (share of each part rusted, open rail). Tune c, k and E to these:

   | Part (share of steel in elevation) | a 0.25 | 0.5 | 0.75 | 1.0 |
   |---|---|---|---|---|
   | feet (1.5 %) | 0.6 | 0.9 | 1.0 | 1.0 |
   | joints (6 %) | 0.3 | 0.5 | 0.75 | 0.95 |
   | top rail (18 %) | 0.12 | 0.28 | 0.55 | 0.85 |
   | bottom rail (12 %) | 0.08 | 0.18 | 0.42 | 0.80 |
   | uprights within 0.3 m below a joint (19 %) | 0 | 0.06 | 0.15 | 0.45 |
   | other upright faces (43 %) | 0 | 0 | 0.02 | 0.12 |
   | total, before the quantile | 6 % | 13 % | 25 % | 46 % |

   The totals sit inside R1's band, and rule 6's quantile trims them to 5/10/20/40 %. On the parapet handrail, plates follow the feet row and the top rail takes the rest [I].
8. **Runs on steel.** From each rusted joint, rust runs down the upright for 0.03 m + 0.5 m × u_joint, where u = (T\* − T) / T\* is the rust's age. Opacity falls from 0.9 to 0.3 along the run, and rust wicks up at most 0.05 m from a foot. All of this comes from rule 5, so no stamps are needed.
9. **Concrete below the open rail**, for each foot with u > 0:
   - head as wide as the upstand-top halo, 2 × (0.05 + 0.05·u) m but at most 0.2 m, over the top quarter;
   - tail 0.3–0.7× the head;
   - length 0.08 m + 0.6 m·u, ending 0.03 m under the nose.
   
   **Drip curtain.** Under rusted stretches of either rail, place streaks every 0.15–0.25 m, 0.02–0.08 m wide. They cover 0.45× the larger rusted share of the two rails at the top of the face, and that cover halves every 0.35–0.5 m downward [M, photo S44c]. So `RUST_EDGE_RUNS` rises from 1.6 to 4–6 per metre at a = 1. Under the parapet handrail, 0–30 % of plates get an outer-face stain of 0.2 m or less.
10. **Colour** by rust age u and wetness w.

    | Where | L* | a* | b* |
    |---|---|---|---|
    | steel, fresh (u < 0.15) | 50–56 | +18–22 | +30–38 |
    | steel, mid (today's `rust`) | 36–44 | +13–17 | +18–26 |
    | steel, old (u > 0.6; `rust_bar`) | 28–34 | +9–12 | +12–18 |
    | steel, old and wet (w ≥ 1.8) | 20–28 | +4–9 | +5–12 |

    - At Ri 4 and above, keep crisp 1–3 cm paint islands on 10–30 % of rust older than u = 0.5 [M, photo S44a].
    - Concrete heads: hue 50–58°, a* +15–20, ΔL* −15 to −24 once u ≥ 0.5. Tails: hue 68–76°, a* +6–10, ΔL* −8 to −14.
11. **Steel clock** (an option for the user).
    - Rust follows S = t_r + 0.1·(age − t_r), with t_r = min(age, 0.665·C_s) and C_s = lerp(30, 6, upkeep) years.
    - S maps log-linearly to a share: 3 → 0.5 %, 6 → 1 %, 10 → 8 %, 20 → 40 %, 30 → 60 %.
    - That gives Kept ≈ 0.7 %, Typical ≈ 3.7 %, Worn ≈ 16 % and Derelict ≈ 41 % of the steel. Today age × the care factor gives 0.3, 4.2, 5.7 and 13.7 %, so the change lands mainly on Worn and Derelict.
    - Jacking stays on age: cracks after 10–15 years of rust at a foot and spalls after 20–25, both added to the damage layer's spall list.

### 7.2 Gate rules (style of R1–R2)

**R3 · metal · Rust follows the water.**
- **Measure.** Rusted steel pixels, as in R1, split by part: feet, joints, rails, uprights within 0.3 m below a top-rail joint, and other upright faces.
- **Pass,** from 0.25:
  - feet rusted ≥ 0.5, and ≥ 0.8 from 0.5;
  - the rails' rusted share at least 3× that of the other upright faces;
  - those faces hold ≤ 10 % of all rust up to 0.75, and ≤ 25 % at 1.0.
- **Origin.** U (round H: "build along the top … gather along the bottom railing … drip down the vertical columns"); L (S6, S8, S18); P (S43).

**R4 · metal · Rust grows along the flow.**
- **Measure.** Between rust steps, the share of new rusted steel pixels that either continue earlier rust on their member or start at a foot or joint. "Continue" means within 0.3 m along a rail, 0.5 m down an upright, or 0.05 m up one. Also the mean length of rusted rail segments.
- **Pass,** per step:
  - at least 70 % of the new pixels qualify;
  - at most 10 % lie more than 0.05 m above earlier rust on an upright;
  - the mean rusted rail segment grows ×1.3 or more, until the rails are 80 % rusted.
- **Origin.** U (round H: grow "along the surfaces most affected by water", not radially); M (S13–S15: creep is only 0.1–3.5 mm a year).

**R5 · metal · Post feet stain the concrete.**
- **Measure.**
  - For each steel foot over painted concrete on the front plane, the rust on the paint below it (L_rust ≥ T2, within ±0.12 m of the post axis): whether it reaches 0.1 m, and its width in the top 0.04 m and in its lowest quarter.
  - The rusted share of the slab-edge width in the top 0.05 m below the rails.
- **Pass:**
  - stained feet: ≥ 25 % at 0.25, 50 % at 0.5, 80 % at 0.75 and 90 % at 1.0;
  - head 1.5–4.5× the post width, and the lowest quarter no wider than the head;
  - slab-edge cover 5–20 % at 0.5 and 20–50 % at 1.0;
  - parapet plates: ≤ 30 % with an outer-face stain, each ≤ 0.2 m.
- **Origin.** U ("streaking on the concrete where the fence posts meet the concrete"); P (S43, S25†); M (photos S44c–d).

**R6 · colour · Rust colour follows age and density.**
- **Measure.**
  - Lab of steel rust: pixels already rusted at the previous step, against new ones.
  - Lab of stains on paint: the head (top quarter of each foot stain) against the tail (the lower half).
- **Pass:**
  - steel rust hue 40–75° and C* 10–35, with the old median L* at least 4 below the new;
  - stain heads hue 48–62°, tails 64–80°, and head L* at least 6 below tail L*.
- **Origin.** M (photos S44a, S44c–d); L (S32, S36).

## 8. What I could not find

- **Measurements:**
  - TOW per rail part;
  - creep below a defect compared with above it, or along an edge compared with across a face;
  - field sizes of runs and stains (the sizes here are my photo readings);
  - instrument Lab of rust stains, and of rust wet and dry;
  - filiform growth on steel.
- **Standards and cycles:**
  - the ISO 4628-2 and 4628-8 tables;
  - coating deterioration curves;
  - the Japan Road Association rust grades;
  - repaint cycles for UR and prefectural rental danchi.
- **Never searched (the budget ran out):** Japanese practitioner pages on rust and 爆裂 at rail feet (手すり根元). S43 stands in for them.
- **Could not read:**
  - UK council-estate photos, because Geograph blocked the helper;
  - the LIXIL and Aron Kasei railing manuals, because their fonts did not decode;
  - S25, which timed out for me, so its numbers are the helper's.

## 9. Sources

1. ISO 4628-3 grades (Inspenet) † — https://inspenet.com/en/articles/rules-for-classifying-degree-of-rusting/
2. ASTM D610 (Micom) † — https://www.micomlab.com/blog/corrosion-testing/astm-d610-test-now-offered-at-micom-laboratories/
3. ISO 12944-1 durability (Jotun) † — https://www.jotun.com/id-en/our-business-areas/energy/power/about/selecting-the-right-system
4. WEG, coatings for industrial maintenance † — https://static.weg.net/medias/downloadcenter/h86/h9a/WEG-coatings-industrial-maintenance-50021180-brochure-en-print.pdf
5. ISO 9223:2012, copy in an Eskom report † — https://www.eskom.co.za/wp-content/uploads/2024/04/Appendix_5.8.E_SO_9223_2012en.pdf
6. Knudsen et al. 2023, root causes of corrosion on painted steel — https://sintef.no/en/publications/publication/2192819
7. NILIM Technical Note 294 (2006), girder-end corrosion: summary chapter — https://www.nilim.go.jp/lab/bcg/siryou/tnn/tnn0294pdf/ks0294015.pdf ; chapter 3 † — https://www.nilim.go.jp/lab/bcg/siryou/tnn/tnn0294pdf/ks0294013.pdf
8. BRANZ, Positional corrosion #2 (2018) — https://www.branz.co.nz/documents/1173/BRANZ-RN-Positional-Corrosion-2.pdf
9. GAA design manual, microclimates — https://designmanual.gaa.com.au/index.php/painting/the-effect-of-microclimates/
10. KTA, edges and coating performance † — https://kta.com/preparation-edges-coating-performance/ ; fibre epoxy data † — https://www.minifibers.com/files/literature/Short-Stuff-in-2K-Epoxy-2pg.pdf
11. ISO 8501-3:2006 sample † — https://cdn.standards.iteh.ai/samples/41021/c61f5fdb603f46b3a0870f17f1fe1d4f/ISO-8501-3-2006.pdf
12. ICorr on ISO 12944-3 design † — https://www.icorr.org/iso12944-steel-structure-design-corrosion/
13. FHWA-RD-03-032, bridge coatings — https://www.fhwa.dot.gov/publications/research/infrastructure/structures/03032/index.cfm
14. FHWA-HRT-11-046 † — https://www.fhwa.dot.gov/publications/research/infrastructure/bridge/11046/003.cfm
15. NILU, alkyd field exposure (snippet) † — https://nilu.brage.unit.no/nilu-xmlui/handle/11250/2717314
16. Kalmar/Volvo scribing standard † — https://www.kalmarglobal.com/492a5c/globalassets/media/262474/262474_20982.0002---Scribing-and-evaluation-of-coated-test-object.pdf
17. University of Virginia thesis, scribe-creep drivers † — https://libraetd.lib.virginia.edu/public_view/ft848q847
18. Shimizu et al., guardrail posts (Nihon University) — https://www.cit.nihon-u.ac.jp/kouendata/No.41/3_doboku/3-007.pdf
19. Construction Specifier, rail post anchorage into concrete — https://www.constructionspecifier.com/design-considerations-for-rail-post-anchorage-into-concrete/3/
20. STRUCTURE, balcony issues in high-rise buildings — https://www.structuremag.org/article/balcony-issues-in-high-rise-buildings/
21. STRUCTURE, strengthening handrail anchorage † — https://www.structuremag.org/article/novel-solution-for-strengthening-handrail-anchorage/
22. Habitat magazine, hollow rails † — https://www.habitatmag.com/layout/set/popup/Archive2/368-July-August-2019/Sometimes-a-10-000-Pound-Beast-Isn-t-So-Scary
23. City of Toronto, balcony report (2022) † — https://www.toronto.ca/legdocs/mmis/2022/sx/comm/communicationfile-145892.pdf
24. Bury Council, Town Hall balcony railings † — https://councildecisions.bury.gov.uk/documents/s24351/8.%20260%20Operations%20Decisions_TH%20Capx%20Balcony%20Railings%20-%20Copy.doc.pdf
25. Brighton & Hove, Brunswick survey † — https://democracy.brighton-hove.gov.uk/documents/s6330/Item%2099%20Appendix%201.pdf
26. FHWA T 5140.22, weathering steel staining † — https://www.fhwa.dot.gov/bridge/t514022.cfm ; dissolved iron (forum) † — https://cr4.globalspec.com/thread/72354/Rust-Stains-on-Cement-Driveways
27. Building Conservation: lead fixing † — https://www.buildingconservation.com/articles/lead-fixing-ironwork/lead-fixing-ironwork.htm ; iron railings † — https://buildingconservation.com/articles/iron-railings/iron-railings.htm
28. Alonso et al. 1998, Materials and Structures (not opened) — https://doi.org/10.1007/BF02480466
29. MLIT, 長期修繕計画作成ガイドライン (2024) — https://www.mlit.go.jp/jutakukentiku/house/content/001747006.pdf
30. Hyde Housing † — https://www.hyde-housing.co.uk/homeowners/s20-notices-our-contracts-and-your-service-charges/major-external-works ; Havering † — https://democracy.havering.gov.uk/documents/s75719/7%20Year%20Decorations%20-%20Cabinet%20Report%20to%20Award%20V3.pdf
31. Blocken & Carmeliet 2004, wind-driven rain review (with Choi's table) — https://aecb.net/wp-content/uploads/2024/11/Blocken_Carmeliet_A-review-of-wind-driven-rain-research-in-building-science-2.pdf
32. Scheinost & Schwertmann 1999, iron oxide colours † — https://literature.wolkersdorfer.info/literature/Color%20Identification%20of%20Iron%20Oxides%20and%20Hydroxysulfates%20Use%20and%20Limitation.pdf
33. Vodyanitskii & Kirillova 2016, Munsell to CIELAB † — https://www.literature.wolkersdorfer.info/literature/Conversion%20of%20Munsell%20color%20coordinates%20to%20Cie-Lab%20system%20Tables%20and%20calculation%20examples.pdf
34. Iron-oxide pigment patents † — https://patents.google.com/patent/EP0911370A1/en ; https://patents.google.com/patent/US6179908B1/en
35. Golden paints, Mars Black and Red Oxide † — https://goldenartistcolors.com/products/heavy-body-acrylic-color-mars-black ; https://goldenartistcolors.com/products/heavy-body-acrylic-color-red-oxide
36. Crespo-Ibáñez et al. 2022, weathering-steel patina † — https://mdpi-res.com/d_attachment/metals/metals-12-00977/article_deploy/metals-12-00977.pdf
37. Nippon Steel, weathering steel † — https://www.nipponsteel.com/en/product/plate/list/04.html
38. Alcántara et al. 2017, marine rust layers † — https://pmc.ncbi.nlm.nih.gov/articles/PMC5506973/
39. Historic England report 43/2024, stone wet and dry † — https://ndownloader.figshare.com/files/53393618
40. Shields et al. 1968, soil colour and moisture † — https://mountainscholar.org/items/994e060d-24af-4679-9534-d42f584d4908/full
41. Lekner & Dorf 1988, darker when wet † — https://www.wgtn.ac.nz/scps/staff/pdf/darkerwhenwet.pdf
42. Wikipedia, capillary length — https://en.wikipedia.org/wiki/Capillary_length
43. Project photo survey of 22 Japanese rails, doors and shutters — `docs/redesign/research/r4-visual-reference.md` §3 (search URLs listed there)
44. Photos read this session (Wikimedia Commons):
    - a. Soshigaya 28, stairs and balconies, CC0 — https://commons.wikimedia.org/wiki/File:Soshigaya_housing_comprex_2025-01-25_Lt12.jpg
    - b. Soshigaya 29–30, CC BY-SA 4.0 — https://commons.wikimedia.org/wiki/File:Soshigaya_housing_comprex_2025-01-25_29,30.jpg
    - c. Siemianowice grille (scale: 0.2 m glass-block pitch), CC BY-SA 4.0 — https://commons.wikimedia.org/wiki/File:Siemianowice_ZHP_okno_i_rdza_2025.jpg
    - d. Moscow, Novospassky Bridge, CC0 — https://commons.wikimedia.org/wiki/File:Moscow,_rust_on_Novospassky_Bridge_June_2022_05.jpg
45. Wikipedia, Pilling–Bedworth ratio † — https://en.wikipedia.org/wiki/Pilling%E2%80%93Bedworth_ratio
