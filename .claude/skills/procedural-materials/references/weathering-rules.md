# Weathering rules

Numeric rules for building weathering, checked by `scripts/weathering/weather_gate.py`. A weathered building is accepted only when every binding rule passes; nothing is shown before that. Version: 1.2 (round F).

Numeric rules for building weathering, measured in facade space (metres) on a darkening map D = 1 - Y_weathered / Y_clean. A configuration is accepted only when every binding rule passes. Origins: U = the user's review notes (review 36), P = measured on the reference photos, L = building physics and the soiling literature, C = craft estimate (to recalibrate with picks).

## Measures

- **D**: darkening of albedo luminance against the same surface with no weathering: 0 clean, 0.10 = 10 % darker, negative = lighter
- **D_local**: the weathering's own local contrast: D_local = 1 - (1 - D) / ref, ref = the least weathered 10 cm patch within +-1 m (smoothed), on 4 cm block means. A uniform darkening of a whole wall gives 0 (it reads as a paint colour, not as weathering: the user, review 36); paint tones that differ from element to element do not count either. T1 is below photo noise and material texture, so the amount rules start at T2.
- **Opacity tiers** (lower bounds of D or D_local): T1 trace >= 0.02, T2 faint >= 0.05, T3 light >= 0.10, T4 medium >= 0.18, T5 heavy >= 0.30, T6 very heavy >= 0.45. each tier is about 1.6-2x the one below; T1 is near the threshold of seeing on a pale wall (about 1 L*), T4 is a clear stain, T6 a black crust
- **Scale levels**: S1 16-32 m, S2 8-16 m, S3 4-8 m, S4 2-4 m, S5 1-2 m, S6 0.5-1 m, S7 0.25-0.5 m, S8 0.125-0.25 m. Groups: macro S1-S3, mid S4-S5, micro S6-S8. under 12.5 cm is the material's own texture (grain, pores, coat bumps): the material set and the tiling detail, checked by J rules on close crops
- **Soiling clock E**: repaint cycle lerp(24, 7, upkeep) years; years since repaint min(age, cycle); E = years_since_repaint + 0.22 * (age - years_since_repaint). old stains ghost through new paint at 22 %; damage, rust depth, cracks and efflorescence follow age, not E
- **Planes**: exposed painted faces visible in elevation: front plane (parapets, slab edges), the walls above the parapets, end walls (gables), the plinth; soffits and recesses are sheltered planes
- **Layers**: soiling, streaks, stains, base, bio, rust, efflorescence, washed, fading, repaint, wear, damage, peeling, cracks

## Presets

| Preset | Age | Upkeep | E | Anchor |
|---|---|---|---|---|
| New | 0 | 1 | 0 |  |
| Kept | 15 | 0.85 | 10.75 | U: round-7 'Light' picked at 10 m and 40 m for a moderately maintained block |
| Typical (default) | 35 | 0.9 | 14.5 | U: grid pick, 35 years, upkeep 0.9, as the default for the game's streets |
| Worn | 35 | 0.5 | 19.8 | U: round-7 'Medium' 'if we're pushing it for a more dystopian world' |
| Neglected | 45 | 0.12 | 27.1 | U: round-7 Neglected 'not heavy enough': more varied wear, growth and algae, no clean sections or edges |

## Amount tables

Tone (A0), mean D on the exposed painted walls, by E: E 0: 0.00-0.02; E 10.75: 0.12-0.28; E 14.5: 0.15-0.32; E 19.8: 0.22-0.42; E 27.1: 0.30-0.56.

Coverage (A1), share of the exposed painted wall at or above each tier of D_local, by E:

| Tier | E 0 | E 10.75 | E 14.5 | E 19.8 | E 27.1 |
|---|---|---|---|---|---|
| T2+ | 0-0.16 | 0.3-0.62 | 0.35-0.68 | 0.5-0.82 | 0.7-0.96 |
| T3+ | 0-0.05 | 0.1-0.3 | 0.15-0.38 | 0.3-0.56 | 0.55-0.86 |
| T4+ | 0-0.035 | 0.03-0.1 | 0.05-0.14 | 0.12-0.26 | 0.3-0.6 |
| T5+ | 0-0.025 | 0.008-0.04 | 0.015-0.06 | 0.035-0.11 | 0.12-0.35 |
| T6+ | 0-0.006 | 0-0.012 | 0.002-0.02 | 0.004-0.035 | 0.04-0.2 |

A1: share of the exposed painted wall at or above each tier of D_local (T2+ ... T6+), by preset; interpolate in E. Anchors: U, round-7 'Light' (picked for a moderately kept block) measured T3+ 0.16, T4+ 0.057, T5+ 0.025; P, ordinary photo walls median T3+ 0.52, T4+ 0.09, T5+ 0.034 (range 0.08-0.66, 0.05-0.25, 0.02-0.12), heavily stained walls T3+ 0.88-0.98, T4+ 0.63-0.96; U, round-7 Neglected (0.49, 0.24, 0.087) was 'not heavy enough'. The New band allows the material's own variation. Round F: re-measured with D_local on the weathering alone; round-7 'Light' then reads 0.35 / 0.13 / 0.041 / 0.011 / 0.001 (inside Kept), round-7 'Medium' 0.64 / 0.44 / 0.17 / 0.039 / 0.004 (Worn's T5+ and T6+ lower bounds moved to 0.035 and 0.004 to hold it), round-7 Neglected 0.76 / 0.52 / 0.25 / 0.072 / 0.011 (still below Neglected: 'not heavy enough').

## Rules

Origins: U the user's review notes, P measured on the reference photos, L building physics and the soiling literature, C a craft estimate (recalibrate with picks).

### Amount

**A0. Overall greying follows age and upkeep**

- Measure: mean D against clean on all exposed painted planes (area-weighted)
- Pass: inside the 'tone' band at the config's E
- Origin: U+C

**A1. Marks cover more of the wall, at more intensities, with age and neglect**

- Measure: share of exposed painted wall at each tier of D_local (T2+ ... T6+), area-weighted
- Pass: every tier inside its 'coverage' band at the config's E
- Origin: U+P

**A2. No clean sections**

- Measure: D_local cell means on 4 m cells (S3) per plane
- Pass: P10 cell >= 0.30 x mean, and min cell >= 0.15 x mean, when E >= 10; >= 0.40 / 0.25 when E >= 25
- Origin: U ('that middle section has virtually no wear or stain')

**A3. Edges carry weathering too**

- Measure: mean D_local in the outer 1 m bands of each plane (both vertical ends, and the 1 m under the wall top) over the plane mean
- Pass: >= 0.6 when E >= 10
- Origin: U ('the edge areas also have no staining')

**A4. Presets order at every tier**

- Measure: composite tier coverage across the presets new < kept < typical < worn < neglected
- Pass: strictly increasing at T1+..T5+ (ties allowed only where both are below 0.001)
- Origin: C


### Opacity

**B1. A range of opacities, more faint than heavy while the wall is kept**

- Measure: shares of the exposed painted wall in each D_local tier band T2..T6
- Pass: when E >= 10: at least 4 tiers each hold >= 1 % of the wall, and no tier holds more than 60 % of the stained area (T2+), 70 % when E < 12; when 10 <= E <= 20 the share falls from T3 upward (each ratio <= 0.9)
- Origin: U ('It's also levels like opacities and concentrations'); P (heavy photo walls shift to the dark tiers, so the falling rule stops at E 20)

**B2. Large marks have an inner pattern**

- Measure: connected marks of D_local >= T3 with equivalent diameter >= 0.5 m: coefficient of variation of D_local inside, and the number of tiers spanned
- Pass: median CV >= 0.30 and >= 60 % of them span >= 3 tiers (reach T5); marks >= 2 m: median CV >= 0.40, 10th percentile >= 0.33, none under 0.25 (when E >= 25: 0.33, 0.25, 0.20)
- Origin: U ('large blotches need inner patterns and varying intensity'); P (recalibrated on D_local of the photo walls, round F: ordinary walls 9 of 14 marks >= 0.5 m span >= 3 tiers, median CV about 0.35, marks >= 2 m CV 0.35-0.68; heavy walls 0.25-0.58)

**B3. No flat tint**

- Measure: share of the stained footprint (D >= T1) whose local std over 20 cm is below 0.005
- Pass: <= 0.05 for the composite and for the soiling layer
- Origin: U ('looks like you're just changing the base color'); P (photos: 0.00)


### Scale

**C1. Energy at every scale level**

- Measure: std of the composite's difference-of-Gaussian band per level (S2-S8 that fit the plane)
- Pass: every level >= 0.004 when E >= 10, and max/min over S3-S8 <= 3.0
- Origin: U ('micro, mid, and macro... EIGHT levels of scale'); P (photo walls: flat to rising band std, max/min 1.3-2.6)

**C2. Each areal layer spans macro, mid and micro**

- Measure: per layer (soiling, stains, base, bio): levels whose band std >= 15 % of the layer's largest band
- Pass: at least one level in each group (macro, mid, micro) and >= 5 levels in all
- Origin: U

**C3. More small marks than large**

- Measure: count of connected marks per level at D >= T2, per layer (streaks, stains, bio, damage)
- Pass: count(S_k+1) >= 1.5 x count(S_k) for every level k with count >= 10, down to S7
- Origin: C (power-law sizes)


### Clustering

**D1. 80/20 at several scales, with a background**

- Measure: share of the summed D_local held by the top 20 % of cells, on 4 m and 2 m cells, per plane; streak and stain layers on their own maps
- Pass: composite in [0.28, 0.60]; streak and stain layers in [0.40, 0.85] on planes where the layer covers >= 3 % at T2+
- Origin: U ('the 80/20 applies at various levels, and it isn't necessarily as simple as on/off'); P (photo walls 0.26-0.35 on 1 m cells against a local reference)


### Coherence

**E1. Variety without jumping all over**

- Measure: per storey-bay cells of D_local on each plane, storeys only (the roof parapet or coping band above the top slab and the ground storey's splash zone are systematic and have their own rules, A3/F1 and F3): lag-1 correlation of neighbours (storey to storey, bay to bay), and the P90 of the storey-to-storey difference over the P90-P10 spread; bay to bay compares neighbouring bays of the same kind (unit next to unit)
- Pass: rho floor-to-floor >= 0.30, rho bay-to-bay >= 0.20, jump <= 0.80
- Origin: U ('too much of a difference between that upper floor and the one immediately under it'); P (photos: rho 0.1-0.9, jump 0.3-0.8)


### Gradients

**F1. Top more intense than the middle**

- Measure: mean D of the streak + stain layers in the top 20 % of each wall's height over the 30-70 % band
- Pass: >= 1.30 (composite >= 1.10)
- Origin: U ('I'd expect the ones near the top to be more intense'); L (driven rain peaks at the top); P (photo walls median 1.4)

**F2. Each run is darkest at its source**

- Measure: streak and stain marks taller than 0.5 m: mean D of the top third over the bottom third
- Pass: median >= 1.25
- Origin: L (run-off deposits most near its source); U

**F3. Darker base**

- Measure: mean D in the bottom 1 m of each wall over the wall mean
- Pass: >= 1.30 when E >= 8
- Origin: P (photo walls 1.3-2.0); L (splash, damp, soil)

**F4. North and damp faces grow more**

- Measure: bio layer coverage at T2+ on north-facing planes over south-facing
- Pass: >= 1.5 when bio is present
- Origin: L


### Placement

**G1. Streaks start at a feature**

- Measure: share of streak marks whose top lies within 0.15 m below a source pixel (ledge drip line, sill end, opening corner, fixing, joint, chip, top edge)
- Pass: >= 0.95
- Origin: P (review 31: every streak in 17 photos starts at a feature); L

**G2. Stains are dark on every material**

- Measure: on dark substrates (plinth, bare concrete; clean Y < 0.30): share of pixels lighter than the clean surface by more than T2, and lightening marks taller than 0.3 m
- Pass: <= 0.02 and none; passes when the building has no dark substrate
- Origin: U ('I'd expect stains to be dark somewhat independently of the materials')

**G3. Lightening is rare and specific**

- Measure: share of each plane lighter than clean by more than T1 (washed, worn, efflorescence, fading, repaint)
- Pass: <= 0.25 x the plane's share at T1+ darkening
- Origin: C; L (white washing is a late-life feature, 2 of 23 photos)

**G4. Algae sits where water stays**

- Measure: share of the algae layer's darkening in the wet zone: the bottom 1.5 m, within 0.8 m below a water source (tops, sill ends, corner heads, fixings, joints, stain and streak marks), or in a joint
- Pass: >= 60 % wherever algae covers >= 0.2 % of a plane at T2+
- Origin: U ('growth and algae/mold stains from the water'); L (algae needs standing or running water; it starts at the foot, under drips and in joints)


### Separability

**H1. The wall is not striped**

- Measure: composite anisotropy gx/gy of the S5-S8 bands
- Pass: in [0.40, 1.80]
- Origin: P (photo walls 0.5-1.6; round-7 renders 2.6-4.0)

**H2. Streaks read as streaks, stains as stains**

- Measure: anisotropy of the streak layer's S7-S8 bands; of the stain layer's S4-S6 bands
- Pass: streaks >= 2.0; stains in [0.5, 2.0]
- Origin: U ('the big blotches blend a little too well with the long streaks'); C, calibrated on synthetic marks: a single 1 m x 3 cm streak measures 1.69 / 2.34 / 3.23 at S6 / S7 / S8, a 0.4 m drip 1.14 / 1.51 / 2.13, a fringe of drips 0.43 / 0.80 / 1.29, stains about 1.5

**H3. Streak cores show through stains**

- Measure: where streak cores (streak layer >= T3) lie inside stains (stain layer >= T2): composite D at the core minus the mean over a 15-30 cm ring
- Pass: median >= 0.03
- Origin: U


### Colour

**I1. Dirt shifts colour like real dirt**

- Measure: soiling, streak and stain pixels at T3+ against clean: shift in b* (yellow-blue) and |a*| per 0.1 of D (bio and rust exempt)
- Pass: b* shift in [-0.30, +0.80] per 0.1 D and |a*| <= 1.0 per 0.1 D
- Origin: P (photo stains on painted walls: b* -0.26 to +0.67 and a* -0.9 to +0.2 per 0.1 D; a grey multiply gives about -0.16)

**I2. More kinds of discolouration with neglect**

- Measure: number of layers covering >= 0.3 % of the wall at T2+ (or, for lightening layers, lighter than T1)
- Pass: >= 3 at E >= 10, >= 5 at E >= 19, >= 7 at E >= 25 (soiling, streaks, stains, base, bio, rust, efflorescence, washed, fading, repaint, peeling, cracks)
- Origin: U ('more varied wear, discoloration beyond just staining, growth and algae/mold stains')


### Material

**J1. The material is not uniform or smooth**

- Measure: the clean material at the two resolutions the asset carries: relative std of the luminance band-pass at 10-50 cm and 0.5-2 m on each plane's clean albedo (50 px/m, the baked atlas), and at 0.5-2 cm and 2-10 cm on 1 m close-ups at 1 mm/px under the preview light (the coat set as the shader samples it); relief: RMS slope of the close-up height at 1-10 mm
- Pass: each band in [1.2 %, 5 %] on every plane and close-up; relief RMS slope >= 2 degrees
- Origin: U ('Concrete isn't uniform like this. And it's not smooth like this'); P (round E photo walls 1.9-3.6 %)

**J2. Weathering follows the material**

- Measure: (a) correlation of the soiling layer with the material response (coat strength, laps, coat thickness, joints) in the 4-50 cm band on the painted walls; (b) mean soiling in the joints over the wall within 15 cm of them; (c) on each close-up, mean soiling in the deepest 20 % of the coat's cavities over the shallowest 50 %
- Pass: (a) >= 0.25 pixel-weighted over the planes, (b) >= 1.3 where joints exist and E >= 10, (c) >= 1.3; when E >= 5
- Origin: U ('the basic texture of the material... also informs the wear and tearing patterns, stains and streaks, biological growth...')


### Damage

**K1. Damage at many sizes, more levels with more damage**

- Measure: damage marks (chips, spalls) counted per level S4-S8 and below
- Pass: the largest damage level present reaches S8 at amount 0.25, S7 at 0.5, S6 at 0.75, S5 at 1.0; from that level down to S8 the geometric mean count ratio per level is in [2, 6] and no step is below 1.3 (levels with >= 3 marks)
- Origin: U ('micro, mid, and macro levels... EIGHT levels of scale')

**K2. Each step of the damage control shows**

- Measure: damaged area and count between amount steps of 0.25
- Pass: area x >= 1.6 and count x >= 1.5 per step
- Origin: U ('they all look of a similar size of breaking, same distribution, and same overall amount')

**K3. Edges first, clustered around a centre**

- Measure: share of chips centred within 10 cm of an exposed edge; share of chip area inside hotspot clusters (the rest is background chipping); chip size against distance from its hotspot centre, within each hotspot (median over hotspots with 6 or more satellites)
- Pass: >= 0.80; 0.70-0.90; Spearman rho <= -0.3
- Origin: L; U (round B: damage radiates from a centre)

**K4. Breaks are sharp, rough and recessed**

- Measure: on the break coverage map, radial profiles (16 rays) across the outline of every break of 3 px radius or more, plane cuts left out: the width of the 0.9 to 0.1 ramp; inside breaks of 4 cm radius and up, the relative std of the albedo's 1.5 px high-pass; their median depth
- Pass: median ramp <= 2 px (4 cm at 50 px/m); texture >= 0.035; depth 0.8-4.5 cm
- Origin: L (a fracture edge is sharp at millimetre scale; a spall goes to the cover concrete, 2-4 cm, and shows aggregate); lead review, round F: at amount 0.75 the large breaks read as soft smudges (ramp 4.25 px, no depth)


### Controls

**L1. A control widens coverage, not only opacity**

- Measure: per detail control, between sweep steps of 0.25: the layer's coverage at T2+ and at its top tier
- Pass: each step widens the layer's coverage by >= 1.25x at its intensity frontier, the lowest tier covering under half the wall at the step below; and the intensity rises at least once per two steps: the top tier reached moves up, the frontier moves up, or the share of the layer's area at T4+ grows by >= 10 % (not for damage: breaks are full contrast at any amount, K2 checks its steps). A step 'has some' of a layer at 0.2 % of the wall, or for damage at any break area: breaks are discrete
- Origin: U ('The intensity should not only increase the opacity, but also the amount of surface covered by various levels of intensity')

**L2. Each step is visible**

- Measure: between sweep steps: share of the plane where |delta D| >= 0.01, and mean |delta D| there
- Pass: each step changes >= 2 % of a plane by >= 0.01 (or half the layer's own T2+ area if that is smaller), with a mean change >= 0.02
- Origin: U ('I can't see a difference')

## Revisions

Each change to a rule after it was first written, with the evidence for it.

- **B2**: span share 0.90 -> 0.60; marks >= 2 m CV >= 0.35, >= 0.25 when E >= 25. Recalibrated on D_local of the photo walls after B2 moved to D_local (9 of 14 marks span >= 3 tiers; heavy walls CV 0.25-0.58).
- **E1**: storeys only. The first measurement counted the 0.6 m roof coping band and the splash zone as storeys; their steps are systematic and governed by A3/F1 and F3, not the storey-to-storey variety the rule is about.
- **A0**: 0.002 tolerance at the lower bound. A fresh wall measured -0.00001.
- **C2 C3 F2 G1 H2 I1**: pass on a fresh building (no weathering layers). Nothing to measure.
- **H2**: streak levels S6-S7 -> S7-S8, threshold 2.5 -> 2.0. At S6-S7 only runs of 2 m and more reach 2.5 (synthetic test), which a 1.1 m balcony parapet cannot hold; at S7-S8 a 1 m streak gives 2.3-3.2 and a fringe of drips 0.8-1.3, so the rule still separates runs from drips and from stains (about 1.5).
- **C3**: ratio test only where a level holds >= 10 marks (was 3). With 3 marks the next level's count has a Poisson 95 % range of about 1-9 around 4.5, so a perfect power law failed about 4 times in 10; the failures seen were S3-S4 counts of 3-10.
- **E1**: bay to bay over neighbouring bays of the same kind. A stair tower next to a unit bay differs by construction (corner strips, its own stains), which is not the storey-to-storey jumping the rule is about.
- **K3**: edge share counts chip centres instead of area. A spall 0.7 m across reaches past 10 cm from its edge by construction; the rule is about where breaks start.
- **B1**: largest tier share <= 0.70 when E < 12 (0.60 above). On the ordinary photo walls the faint tier holds 24-76 % of the stained area, the lightest walls the most; 0.60 was a craft number.
- **K1**: ratio test from the level due at the amount downward. A few marks above the due level are merged chip clusters or tail outliers; at 0.3, five such marks against 93 at S8 failed a test meant for the distribution below the largest break.
- **D_local (A1, A2, A3, B1, B2, D1, E1)**: measured on 1 - D, not on the weathered albedo. On the real facade, paint tones that differ between elements counted as stains (the clean round-7 building scored 1.9 % at T5+); the rules are about weathering.
- **A1 Worn**: T5+ lower bound 0.04 -> 0.035, T6+ 0.008 -> 0.004. Round-7 'Medium' (the user: acceptable 'for a more dystopian world') measures 0.039 and 0.004 under the corrected D_local.
- **A3**: top band = the 1 m under the wall top. A penthouse above the roof was taken as the top edge.
- **G2**: passes when there is no dark substrate. Nothing to check is not missing data.
- **K1**: geometric mean ratio over the levels in [2, 6], each step >= 1.3 (was every adjacent pair in [2, 6]). Single levels carry about 15 % count noise from merging and caps; the pairwise window rejected power laws by chance, the mean keeps the slope and the step floor still catches a flattening.
- **J1**: measured at both resolutions: 10 cm-2 m on the planes' clean albedo, 5 mm-10 cm and relief on 1 mm/px close-ups under the preview light. The photo values it was set from were measured on lit photographs, and the 50 px/m planes cannot resolve bands under 4 cm; the coat set (round E) left its macro scales to the shader, so the planes now carry the shader's coat clouding and joints.
- **J2**: three parts: soiling against the material response at 4-50 cm, dirt in the joints, dirt in the coat's troughs at close range. The first version named a cavity map that only exists at close range; the material also shows at the scales the atlas carries (coat thickness, laps, joints).
- **G4**: new rule. A neglected north front (R50) passed every rule with algae blotches spread evenly over all storeys like camouflage; the rules did not say that algae follows water.
- **B2**: marks >= 2 m: median >= 0.40, 10th percentile >= 0.33, floor 0.25 (was: every one >= 0.35); heavy walls 0.33, 0.25, 0.20 (was every one >= 0.25). 0.35 was the smallest of the five big marks on the ordinary photo walls (0.35, 0.44, 0.44, 0.47, 0.68); a building carries 20-66 such marks, so its smallest falls under the photos' smallest by chance alone and the clause tightened with every mark. Builds that failed it had big-mark medians of 0.46-0.55 and 94-96 % of marks at 0.35 or more, against the photos' median of 0.44.
- **gate (sweeps)**: at a sweep step where the control sets a layer to 0, rules that find nothing of that layer to measure pass as not applicable (they reported n/a, which counts as a failure). Streaks at 0 have no streak to place, so G1 cannot apply; the step is still checked by every other rule.
- **L2**: step floor: 2 % of a plane, or half the layer's own area if smaller (was 2 % always). A sparse layer's first step (streaks 0 -> 0.25) added hundreds of runs on 1.5 % of the wall and failed the absolute floor.
- **L1**: coverage widens at the intensity frontier, the lowest tier under half the wall (was T2+); the intensity rise is counted once per two steps and may show as the top tier, the frontier, or the share of the layer at T4+ moving up (was: the top tier twice); not for damage. The soiling film covers the whole wall at T2+ at any amount (A2 asks for it), so T2+ could not widen; chips are full contrast at once; a sparse layer reaches T6 at its first step, so its top tier could not rise twice. The user's point was the area at each level of intensity: grime widens at T4+ 0.36 -> 0.70 -> 0.89 per step, stains' share at T4+ grows 0.19 -> 0.38 -> 0.51 -> 0.59.
- **K4**: new: breaks have a sharp outline, a rough exposed floor and depth. The round-F damage sweep passed every rule while its large breaks were soft blobs (a falloff over half the radius) and its sub-pixel chips a row of equal 1 px dots. Under K4 the generator draws breaks as jagged polygons stretched along their edge with a 1 px edge, recessed 1-4 cm, sub-pixel chips as area coverage.
- **K3**: size against distance measured within each hotspot (median rho), was pooled over all. Hotspot sizes now follow a power law (references: most hotspots are runs of 0.5-3 cm bites, a few are shell breaks); pooled, a big hotspot's large far satellites against a small one's small near ones make a between-hotspot trend (rho -0.25 to -0.29) that hides the decline inside each (-0.74 to -0.81).
- **L1**: for damage a step has some of the layer at any break area (was 0.2 % of the wall). Realistic chipping is sparse: at amount 0.25 the breaks cover 0.04 % of the facade (1.5 m2 on the building) and grow x3.6, x2.4, x2.2 per step (K2); the 0.2 % floor was set for continuous layers.

## Running the gate

```
python -I weather_gate.py check <config_dir> [--json out.json] [--sweep] [--allow-na]
python -I weather_gate.py series presets <dir_new> <dir_kept> <dir_typical> <dir_worn> <dir_neglected>
python -I weather_gate.py series sweep:<layer> <dir_0> <dir_0.25> <dir_0.5> <dir_0.75> <dir_1>
```

A config folder holds one `<plane>.npz` per facade plane in facade space (row 0 at the top, 50 px/m) with `D`, the `L_<layer>` maps, `cls`, `src`, `edge`, optional `Yc`, `labw`/`labc`, the damage chip list (`dmg_y`, `dmg_x`, `dmg_r`, `dmg_d`), and a `meta.json` with the config (preset, age, upkeep, E, amounts) and each plane's frame (ppm, orient, kind, ground and top rows, storey rows, bay columns and kinds). Exit code 0 only when accepted. `--sweep` judges one step of a control sweep: the amount budgets A0, A1 and B1 are set by the control there, so they are not applied.
