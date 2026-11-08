# Weathering rules

Numeric rules for building weathering, checked by `scripts/weathering/weather_gate.py`. A weathered building is accepted only when every binding rule passes; nothing is shown before that. Version: 1.8 (round K).

Numeric rules for building weathering, measured in facade space (metres) on a darkening map D = 1 - Y_weathered / Y_clean. A configuration is accepted only when every binding rule passes. Origins: U = the user's review notes (review 36), P = measured on the reference photos, L = building physics and the soiling literature, C = craft estimate (to recalibrate with picks).

## Measures

- **D**: darkening of albedo luminance against the same surface with no weathering: 0 clean, 0.10 = 10 % darker, negative = lighter
- **D_local**: the weathering's own local contrast: D_local = 1 - (1 - D) / ref, ref = the least weathered 10 cm patch within +-1 m (smoothed), on 4 cm block means. A uniform darkening of a whole wall gives 0 (it reads as a paint colour, not as weathering: the user, review 36); paint tones that differ from element to element do not count either. T1 is below photo noise and material texture, so the amount rules start at T2. Arris rows and the edge layer's pixels are left out (the edge rules N1-N5 measure them), and so are the peeling layer's (P1-P3 measure them).
- **Opacity tiers** (lower bounds of D or D_local): T1 trace >= 0.02, T2 faint >= 0.05, T3 light >= 0.10, T4 medium >= 0.18, T5 heavy >= 0.30, T6 very heavy >= 0.45. each tier is about 1.6-2x the one below; T1 is near the threshold of seeing on a pale wall (about 1 L*), T4 is a clear stain, T6 a black crust
- **Scale levels**: S1 16-32 m, S2 8-16 m, S3 4-8 m, S4 2-4 m, S5 1-2 m, S6 0.5-1 m, S7 0.25-0.5 m, S8 0.125-0.25 m. Groups: macro S1-S3, mid S4-S5, micro S6-S8. under 12.5 cm is the material's own texture (grain, pores, coat bumps): the material set and the tiling detail, checked by J rules on close crops
- **Soiling clock E**: repaint cycle lerp(24, 7, upkeep) years; years since repaint min(age, 0.665 * cycle); E = years_since_repaint + 0.17 * (age - years_since_repaint). a building is on average two-thirds of the way through its repaint cycle, and 17 % of the dirt survives each repaint. Round H: rounds F and G both had the user pick the next-cleaner preset as the 35-year default; the old clock (the cycle's end, 22 % kept) made every age one level too weathered. Damage, cracks, rust, efflorescence, edges and fading follow age, not E
- **Planes**: exposed painted faces visible in elevation: front plane (parapets, slab edges), the walls above the parapets, end walls (gables), the plinth; soffits and recesses are sheltered planes
- **Layers**: soiling, streaks, stains, base, bio, rust, efflorescence, washed, fading, repaint, wear, damage, peeling, cracks

## Presets

| Preset | Age | Upkeep | E | Anchor |
|---|---|---|---|---|
| New | 0 | 1 | 0 |  |
| Kept | 10 | 1 | 5.56 | U (round G): 'something between New and Kept, which will become the new kept' |
| Typical (default) | 35 | 0.9 | 10.75 | U (round G): round G's Kept picked as the default street block on the front and at 1:1; 'the current Kept becomes Typical' |
| Worn | 35 | 0.5 | 14.5 | U (round G): 'current Typical becomes Worn' |
| Derelict | 45 | 0.12 | 19.77 | U (round G): 'Worn currently is probably more like derelict levels of weathering... Worn becomes Derelict' |

## Amount tables

Tone (A0), mean D on the exposed painted walls, by E: E 0: 0.00-0.02; E 5.56: 0.04-0.10; E 10.75: 0.08-0.18; E 14.5: 0.13-0.26; E 19.8: 0.22-0.42; E 27.1: 0.30-0.56.

Coverage (A1), share of the exposed painted wall at or above each tier of D_local, by E:

| Tier | E 0 | E 5.56 | E 10.75 | E 14.5 | E 19.8 | E 27.1 |
|---|---|---|---|---|---|---|
| T2+ | 0-0.16 | 0.08-0.26 | 0.18-0.4 | 0.3-0.62 | 0.5-0.85 | 0.7-0.96 |
| T3+ | 0-0.05 | 0.02-0.1 | 0.05-0.18 | 0.1-0.3 | 0.28-0.55 | 0.55-0.86 |
| T4+ | 0-0.035 | 0.004-0.03 | 0.012-0.06 | 0.03-0.1 | 0.1-0.26 | 0.3-0.6 |
| T5+ | 0-0.025 | 0.001-0.01 | 0.003-0.02 | 0.008-0.04 | 0.03-0.1 | 0.12-0.35 |
| T6+ | 0-0.006 | 0-0.003 | 0-0.006 | 0-0.012 | 0.006-0.04 | 0.04-0.2 |

A1: share of the exposed painted wall at or above each tier of D_local (T2+ ... T6+), by preset; interpolate in E. Anchors: U, round-7 'Light' (picked for a moderately kept block) measured T3+ 0.16, T4+ 0.057, T5+ 0.025; P, ordinary photo walls median T3+ 0.52, T4+ 0.09, T5+ 0.034 (range 0.08-0.66, 0.05-0.25, 0.02-0.12), heavily stained walls T3+ 0.88-0.98, T4+ 0.63-0.96; U, round-7 Neglected (0.49, 0.24, 0.087) was 'not heavy enough'. The New band allows the material's own variation. Round F: re-measured with D_local on the weathering alone; round-7 'Light' then reads 0.35 / 0.13 / 0.041 / 0.011 / 0.001 (inside Kept), round-7 'Medium' 0.64 / 0.44 / 0.17 / 0.039 / 0.004 (Worn's T5+ and T6+ lower bounds moved to 0.035 and 0.004 to hold it), round-7 Neglected 0.76 / 0.52 / 0.25 / 0.072 / 0.011 (still below Neglected: 'not heavy enough'). Round G: the user picked the Kept image as the default street block (35 years, upkeep 0.9) on the front and on the 1:1 top floors, so Typical takes Kept's round-F bands; Kept is about 0.6x; Worn between Typical and Neglected; Neglected unchanged ('about right'). Round H: as the tone, the presets moved onto these anchors through the clock (the user's rename); the bands did not change. Round I: an explicit Kept anchor (E 5.56) with lighter dark tiers (T4+ 0.004-0.030, T5+ 0.001-0.010, T6+ <= 0.003; the user: Kept 'a tiny bit too dirty, namely the darker stains look a little too dark'), and Derelict (E 19.8) raised to T2+ 0.50-0.85, T3+ 0.28-0.55, T4+ 0.10-0.26, T5+ 0.03-0.10, T6+ 0.006-0.04 ('Still looks too light ... the amount or spread of wear/weather/organic growth/damage').

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

- Measure: composite tier coverage across the presets new < kept < typical < worn < derelict; and the ground band: base excess (bottom 1 m over the wall mean, minus 1) per preset, as steps over its New-to-Derelict range
- Pass: strictly increasing at T1+..T5+ (ties allowed only where both are below 0.001); ground band steps <= 0.45 of the range, the New-to-Kept step <= 0.30
- Origin: C; U (round F: 'the jumps between the steps for the ground level could be more subtle')

**A5. Seeds of a preset read as the same age**

- Measure: the seeds of one preset: tone (A0), T3+ and T4+ of D_local, and the film contrast the solver used
- Pass: each within its tolerance of the seeds' mean: tone 4 %, T3+ 7 %, T4+ 8 %, film contrast 2 %
- Origin: U (round G: 'Seed 1 looks stronger, 2 and 3 look a little closer'; seed 1 measured T3+ 0.205 and T4+ 0.086 against 0.185-0.191 and 0.071-0.079, film contrast 0.69 against 0.61 and 0.50)

**A6. The presets step evenly**

- Measure: tone (A0) steps from New up the preset ladder
- Pass: largest step over the smallest <= 2.2, every step > 0
- Origin: U (round G: 'Yes, even steps' for a ladder measuring 1.9); C (the margin)


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

- Measure: mean D of the dirt (damage, cracks, crack repairs and edges left out) in the bottom 1 m of each wall over the wall mean
- Pass: >= 1.15 when 8 <= E < 13; >= 1.30 when E >= 13
- Origin: P (photo walls 1.3-2.0); L (splash, damp, soil); U (round F: the ground band should come in gently)

**F4. North and damp faces grow more**

- Measure: bio layer coverage at T2+ on north-facing planes over south-facing
- Pass: >= 1.5 when bio is present
- Origin: L


### Placement

**G1. Streaks start at a feature**

- Measure: share of streak marks whose top lies within 0.15 m below a source pixel (ledge and slab drip line, the drip edge under copings and roof props, horizontal joints and grooves, joint crossings, sill end, opening corner, fixing, joint, chip, top edge)
- Pass: >= 0.95
- Origin: P (review 31: every streak in 17 photos starts at a feature); L; U (round I: 'coming down from the horizontal grooves')

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

**G5. Seam crossings collect a little more**

- Measure: where a horizontal and a vertical joint cross: mean D on the joint pixels within 4 cm of the crossing over the joint pixels 0.2-0.6 m from it, per plane
- Pass: in [1.15, 2.0] wherever the streak amount is 0.2 or more
- Origin: U (round F: 'the intersecting corners where seams cross could use a little more. Just a tiny adjustment, don't overdo it'); L (water meets and pauses where joints cross); round F measured 1.02-1.07

**G6. No accidental lattice**

- Measure: per plane, axis and map (soiling, stains, streaks, base, growth, D) on painted wall: the edge-energy profile's periodogram over its running median; the harmonic sum over the first 8 harmonics for periods of 16-600 px, the building's own rhythm (floor pitch, twice it, bay pitch, the 1.8 m scaffold lift, the peaks of the wall's feature map with its joints) left out; a layer is scanned on an axis only where it spans a third of it
- Pass: the largest harmonic sum <= 9
- Origin: U (round F: the grime reads as a grid); docs/redesign/research/weathering-grid-breakup.md 5.1-5.2 (tile-free controls 4.0-7.9; round F's soiling 12.8 from the 3.6 m material tile; measured here 13.5-26 on round F's fronts)


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

**H4. Long streaks, some near the whole height**

- Measure: per wall of 3 storeys or more: the longest vertical run of the streak layer at T2+ (gaps under 0.6 m bridged: slabs, windows) as a share of the wall height; distinct runs of 3 m or more per 25 m of width
- Pass: reach >= 0.35 + 0.40 x the streak amount; runs >= 1 + 3.5 x the amount per 25 m; from amount 0.25
- Origin: U (round F: 'more long vertical streaks', 'some near-whole building long streaks', 'some areas channel water more than others'); round F reached 0.22-0.61 of the wall with 0.6-3.6 runs per 25 m

**H5. Some streaks much darker (layering)**

- Measure: streak-layer marks 0.3 m tall or more: the 90th percentile of their mean D over the median
- Pass: >= 1.8 (20 marks or more, from amount 0.25)
- Origin: U (round F: 'get darker (just some of them, not all, remember layering)'); round F measured 1.41-1.47; C (1.8)

**H6. Streaks gather in the vertical lines**

- Measure: streak pixels at T2+ on paint: the share within 0.3 m of a vertical joint, a bay division or a wall's end (from streak amount 0.15)
- Pass: >= 40 %
- Origin: U (round H: 'streaking will probably be most severe along the panel lines going down. They're natural channels where water gathers'); L (research weathering-water-layers V3; PCI: vertical recesses gather run-off)


### Colour

**I1. Dirt shifts colour like real dirt**

- Measure: soiling, streak and stain pixels at T3+ against clean: shift in b* (yellow-blue) and |a*| per 0.1 of D (bio and rust exempt)
- Pass: b* shift in [-0.30, +0.80] per 0.1 D and |a*| <= 1.0 per 0.1 D
- Origin: P (photo stains on painted walls: b* -0.26 to +0.67 and a* -0.9 to +0.2 per 0.1 D; a grey multiply gives about -0.16)

**I2. More kinds of discolouration with neglect**

- Measure: number of layers covering >= 0.3 % of the wall at T2+ (or, for lightening layers, lighter than T1)
- Pass: >= 3 at E >= 10, >= 5 at E >= 19, >= 7 at E >= 25 (soiling, streaks, stains, base, bio, rust, efflorescence, washed, fading, repaint, peeling, cracks)
- Origin: U ('more varied wear, discoloration beyond just staining, growth and algae/mold stains')

**I3. Weathering varies in colour like the reference walls**

- Measure: weathered pixels (D_local >= T3 on 4 cm blocks, growth and rust left out) on painted wall: the spread of their Lab shift against clean, the share shifted by 1.5 or more, and the spread between marks of 0.5 m or more, per wall; from E 10
- Pass: spread 0.9-4.0; non-neutral share 0.12-0.80; mark-to-mark spread >= 0.2 where there are three marks or more
- Origin: U (round F: more colour variety, calibrated on the photos); P (five ordinary photo walls: spread 1.2-3.9 over a clean-wall noise of 0.65-0.99, so 1.0-3.8 above noise; non-neutral 0.21-0.75 over a noise of 0-0.13; marks 0.2-0.84); round F's builds 0.24-0.89

**I4. Organic marks at different stages sit side by side**

- Measure: growth pixels on paint (growth at T1+) against clean, by the hue of their shift: the yellow stage (60-100 deg, b* +3 or more), the green stage (100-180 deg, a* -1 or less), the red-muddy stage (15-60 deg, a* +1.5 or more); from E 8
- Pass: yellow and green each >= 5 %; from E 18 the red-muddy stage too
- Origin: U (round H: 'keep it on a continuum, dark yellow to dark green to reddish/muddy'; round G: 'Not blended smoothly, but coexisting'); L (research weathering-water-layers: yellow first, green, then brown-black; red only with Trentepohlia)

**I5. A place's organic colour only moves forward**

- Measure: between successive presets, the pixels with growth in both, staged as in I4: the share that goes back a stage; and the growth pixels' mean L* shift
- Pass: 8 % or fewer go back; from each preset at E 8 or more to the next, the mean L* shift falls by 1.0 or more
- Origin: U (round H: 'the colors of the organic staining are flipping between levels ... a streak that looks dark gray, then turns yellow, then blackish'; round G: 'mold and mildew darken/intensify with age')

**I6. Water and dirt marks keep the dirt palette**

- Measure: streak, stain and ground-band pixels at T2+ on paint, growth and rust left out: the share in the green stage (as I4)
- Pass: <= 3 %
- Origin: U (round H: 'make sure that the pure water staining isn't necessarily the same layer as the organic staining ... one is a growth from the other. Layering, remember layering')


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

- Measure: share of chips centred within 10 cm of an exposed edge; share of chip area inside hotspot clusters (the rest is background chipping); chip size against distance from its hotspot centre, within each hotspot (median over hotspots with 6 or more satellites) (edge-damage clusters and background chips; delamination spalls follow K5 and K6)
- Pass: >= 0.80; 0.70-0.90; Spearman rho <= -0.3
- Origin: L; U (round B: damage radiates from a centre)

**K4. Breaks are sharp, rough and recessed**

- Measure: on the break coverage map, radial profiles (16 rays) across the outline of every break of 3 px radius or more, plane cuts left out: the width of the 0.9 to 0.1 ramp; inside breaks of 4 cm radius and up, the relative std of the albedo's 1.5 px high-pass; their median depth
- Pass: median ramp <= 2 px (4 cm at 50 px/m); texture >= 0.035; depth 0.8-4.5 cm
- Origin: L (a fracture edge is sharp at millimetre scale; a spall goes to the cover concrete, 2-4 cm, and shows aggregate); lead review, round F: at amount 0.75 the large breaks read as soft smudges (ramp 4.25 px, no depth)

**K5. Spalled area by amount**

- Measure: share of the wall (paint and concrete) under a break (coverage >= 0.5)
- Pass: 0.01-0.1 % at 0.25, 0.1-0.5 % at 0.5, 0.5-3 % at 0.75, 3-10 % at 1.0 (linear between)
- Origin: U (round F: derelict at 1.0); L (docs/redesign/research/weathering-cracks-edges-damage.md S1: 3.7-9.9 % at 75 years unmaintained); round F reached 0.54 % at 1.0

**K6. Spalls start at edges**

- Measure: spalls 30 mm across or more: share within 150 mm of an arris
- Pass: >= 50 %
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md S5: corners, slab noses, sills, parapet tops)

**K7. Cracks from hairline to pattern cracks**

- Measure: crack length per m2 of wall (width >= 0.05 mm), of cracks >= 0.3 mm, and the median width, pooled over exposed walls
- Pass: length 0.2-0.6 / 0.5-1.2 / 1.0-2.0 / 1.5-3.5 m per m2 at 0.25 / 0.5 / 0.75 / 1.0; >= 0.3 mm 0.03-0.15 / 0.15-0.4 / 0.3-0.8 / 0.6-1.5; median 0.1-0.2 mm at 0.25 to 0.3-0.6 mm at 1.0 (linear between)
- Origin: U (round F: 'cracks from hairline to pattern cracks'); L (docs/redesign/research/weathering-cracks-edges-damage.md C1, C2, C4); round F had about 0 m per m2 (no opening corners reached the crack layer)

**K8. Cracks run mostly vertical**

- Measure: length-weighted crack orientation, pattern cracks left out
- Pass: vertical 40-65 %, diagonal 20-40 %, horizontal 10-25 %
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md C7)

**K9. Diagonal cracks start at opening corners**

- Measure: share of diagonal crack length within one opening width of an opening corner
- Pass: >= 70 %
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md C8: 45 deg cracks from window corners)

**K10. Cracks read through what they carry**

- Measure: median delta L* of the 1 px crack line against the wall around it, by width class (repaired cracks left out)
- Pass: hairline (< 0.2 mm) <= 3; 0.2-0.5 mm 3-8; 0.5-1 mm 5-10; >= 1 mm 8-20
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md C19 and 3.1: at 20 mm/px a crack shows through its halo, not its opening)

**K11. Repaired cracks**

- Measure: share of the length of cracks >= 0.3 mm under a repair stripe
- Pass: 50-90 % at 0.25, 30-60 % at 0.5, 20-50 % at 0.75, 10-40 % at 1.0
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md C23: U-cut and injected repairs on repainted danchi)


### Controls

**L1. A control widens coverage, not only opacity**

- Measure: per detail control, between sweep steps of 0.25: the layer's coverage at T2+ and at its top tier
- Pass: each step widens the layer's coverage by >= 1.25x at its intensity frontier, the lowest tier covering under half the wall at the step below; and the intensity rises at least once per two steps: the top tier reached moves up, the frontier moves up, or the share of the layer's area at T4+ grows by >= 10 % (not for damage or rust: breaks and rust on the steel are full contrast at any amount; K2 and R2 check their steps). A step 'has some' of a layer at 0.2 % of the wall, or for damage at any break area: breaks are discrete
- Origin: U ('The intensity should not only increase the opacity, but also the amount of surface covered by various levels of intensity')

**L2. Each step is visible**

- Measure: between sweep steps: share of the plane where |delta D| >= 0.01, and mean |delta D| there
- Pass: each step changes >= 2 % of a plane by >= 0.01 (or half the layer's own T2+ area if that is smaller), with a mean change >= 0.02
- Origin: U ('I can't see a difference')

**L3. Each step of a control looks as big as the last**

- Measure: per detail control over its steps above 0 (not damage, which K2 checks): the ratio between steps of the layer's mean D, and of its coverage at the frontier tier (the lowest tier under half the wall at the first step shown), while that coverage is under half the wall
- Pass: largest ratio over smallest: <= 1.5 for the mean, <= 1.4 for the coverage
- Origin: U (round F: stains 'the jump to 0.5 is pretty strong, but the jump to 0.75 and 1 feel smaller'; grime 'maybe 0.4 to 0.5 the jump is smaller than 0.3 to 0.4'); round F's stain sweep measured 1.88 and 1.71

**L4. The control's top step is strong**

- Measure: at a sweep's last step (1.0): the layer's share of the exposed walls at T2+ and at T4+
- Pass: streaks: >= 0.035 at T2+ and >= 0.012 at T4+
- Origin: U (round F: 'Even the last is too weak... 1.00/100% should be more intense'); round F's 1.0 measured 0.023 and 0.008

**L5. Marks grow in area with age**

- Measure: over the presets from Kept: the streak area at T2+ (m2) and the ground band's median height (the highest row of the ground-band layer at T1+, per column)
- Pass: each step: streak area x 1.15 or more, the ground band 5 cm or more higher
- Origin: U (round H: 'the increases in ... streaking and ground level wear/staining aren't expanding/increase size and surface area ... the bottom level dirt is getting more intense, but not really seeing a whole lot more of it'); L (research weathering-water-layers V4: x 1.3-1.6 area per step)


### Growth

**M1. Light growth is a tint, not grey**

- Measure: growth pixels at T2-T3 (growth making most of the darkening) against clean: b* shift per 0.1 of D; the share in the dirt band (b* <= +0.8)
- Pass: b* +2.5 to +7.0 per 0.1 D; dirt band <= 10 %
- Origin: U (round F: 'weaker growth should have a lighter green or very dull or rusty yellow look'); U (round H: the continuum starts at dark yellow, so the green and yellow family clauses of round G are dropped); L (docs/redesign/research/weathering-organic-growth.md O1)

**M2. Severe growth is dark green or rust brown**

- Measure: the darkest growth (growth's own darkening >= 0.55, N, E and W walls; south walls grow moulds, O8): black share (C* < 8); of the rest, C* 10-26, hue 95-135 deg (green) or 40-75 deg (rust), and the darkest quarter's L*; from 2000 pixels
- Pass: black <= 35 %; chroma band >= 75 %; hue band >= 75 %; 25th percentile of L* <= 50
- Origin: U (round F: 'the visibly dark green/rust brown look that severe growth has'); L (docs/redesign/research/weathering-organic-growth.md O2)

**M3. Growth sits where water stays**

- Measure: pooled over exposed walls: share of growth (T2+) in damp and wet zones (W2-W3, wetness >= 0.40); the cover of W2-W3 and of the open wall (W0-W1); the share in sunny open wall (W0, < 0.15)
- Pass: while growth covers under 5 %: >= 70 % in W2-W3, from E 18 (Derelict) >= 50 %; beyond that, while W2-W3 are under 80 % covered, their cover >= 3x the open wall's; W0 <= 10 %
- Origin: U (round F: corners, divots, edges, below ledges); L (docs/redesign/research/weathering-organic-growth.md O4); U (round I: Derelict growth 'mostly in the same areas' - it spreads past the wet zones)

**M4. Plinth belt**

- Measure: N, E and W walls: mean growth darkening in the bottom 0.3 m over the open wall (wetness < 0.4, not under another ledge or joint) 0.5-1.5 m above the foot; from 2 years of growth
- Pass: >= 3.0
- Origin: L (docs/redesign/research/weathering-organic-growth.md O5: belt 5-30 cm, splash zone 30 cm)

**M5. Time unattended adds area grown from the old patches**

- Measure: the growth control's steps: growth area (T2+) ratio, the share of the added darkening on newly covered pixels, the share of old growth kept
- Pass: area x >= 1.25 while W2-W3 are under 85 % covered; new share >= 50 %; kept >= 95 %
- Origin: U (round F: 'algae and mold tend to grow outwards like tendrils or blobs, they don't merely get darker'); L (docs/redesign/research/weathering-organic-growth.md O9)

**M6. Ragged fronts, not smooth blobs**

- Measure: growth patches (T2+) of 60 px or more on walls where growth covers 3 % or more: perimeter-area dimension (2 x the slope of log perimeter on log area)
- Pass: 1.10-1.45
- Origin: U ('tendrils or blobs'); L (docs/redesign/research/weathering-organic-growth.md O12; box counting misread sparse patches, so the perimeter-area form)

**M7. Onset by wetness class**

- Measure: growth (T2+) cover of each wetness class's area at the build's years unattended (3.1, 5.7, 10, 22 years at growth amounts 0.25-1.0, log-linear between)
- Pass: W3 >= 15 % from 1 year and >= 50 % from 3; W2 >= 10 % from 3 years and >= 30 % from 8; W1 >= 3 % from 8 years; W0 <= 5 % up to 15 years; no class over its ceiling (W0 0.30, W1 0.60, W2 0.90, W3 0.95) + 0.03
- Origin: L (docs/redesign/research/weathering-organic-growth.md O11 and 3.3: onset, time scale and ceiling per class from field timings)

**M8. Fronts grow outward**

- Measure: the growth control's steps: new growth (T2+) within 0.3 m of the previous step's growth (front growth) and farther away (new patches); a step from a wall with no growth yet (under 400 px) has no fronts and is not judged
- Pass: front growth >= 70 %; new patches 5-30 %
- Origin: U ('grow outwards'); L (docs/redesign/research/weathering-organic-growth.md O10)

**M9. Growth darkens and thickens with age**

- Measure: the growth control's steps: the pixels that were growth (T2+) at the earlier step, at the later step
- Pass: their L* down by 1.0 or more and their growth darkening up by 0.02 or more per step
- Origin: U (round G: 'mold and mildew darken/intensify with age'; round F: 'dark green/rust brown' when severe); L (docs/redesign/research/weathering-organic-growth.md O2)


### Edges

**N1. Edges show at 0.25**

- Measure: the edge layer's mean |delta L*| on the 1 px edge row (painted wall)
- Pass: 3-6 at 0.25, 4-8 at 0.5, 6-11 at 0.75, 7-14 at 1.0
- Origin: U (round F: edge wear and discoloration visible at 0.25); L (docs/redesign/research/weathering-cracks-edges-damage.md E9 and 5.5: at 20 mm/px visibility comes from the edge row, not a bevel)

**N2. The edge band is broken at 0.25, near continuous at 1.0**

- Measure: share of edge length with the edge layer's |delta L*| >= 2
- Pass: 40-70 % at 0.25 to 85-100 % at 1.0 (linear between)
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md E8)

**N3. Visible chips**

- Measure: chips 20 mm across or more per m of edge
- Pass: 0.04-0.15 at 0.25 to 0.5-1.5 at 1.0 (linear between)
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md E6)

**N4. Chips cluster**

- Measure: chip counts in 0.5 m windows along the edges: variance over mean (20 chips or more)
- Pass: >= 1.2
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md E5)

**N5. Tops lighter, drip edges darker and warmer**

- Measure: the edge layer's mean delta L* on top edges and on drip and lower edges; the b* shift on the drip edges
- Pass: tops lighter (> 0); drip edges darker (< 0) with b* +1 to +4
- Origin: L (docs/redesign/research/weathering-cracks-edges-damage.md E9: tops chalked and rain-washed; drip edges dirt)


### Metal

**R1. Rust on steel by grade**

- Measure: the share of the railing steel (rails, posts, balusters; not aluminium sashes, and not flat steel panels such as doors, which R3 judges) where rust shows, a colour difference of 8 or more against clean (dE76; the rails' paint is darker than rust in places), against the rust amount
- Pass: within 0.5-2x the grade share: 5 % at 0.25 (Ri3-4), 10 % at 0.5 (Ri4), 20 % at 0.75 (Ri4-5), 40 % at 1.0 (Ri5), log-linear between; under 0.1 only an upper limit
- Origin: U (round G: 'High rust side looks a little weak'); L (ISO 4628-3 rust grades: Ri3 1 %, Ri4 8 %, Ri5 40-50 %)

**R2. Each rust step shows**

- Measure: the rust control's steps: rusted share of the railing steel (as R1), the steel's mean colour difference against clean, and the rust area on the paint below
- Pass: per step: share x 1.5 or more (or +10 points), mean colour difference x 1.5 or more (or +2), paint area grows
- Origin: U (round G: 'the rust growth needs to be stronger between steps too')

**R3. Rust follows the water**

- Measure: rusted steel (colour difference 8 or more against clean, as R1) by part of the steel's geometry: post feet (the lowest 0.1 m of posts standing on paint), joints (uprights within 0.04 m of a rail), rails, uprights within 0.3 m below a rail, and the other upright faces; flat steel panels (doors, pipe-shaft doors: the steel fills 75 % or more of a 0.2 m window) are not railing steel: the rust on them, by where it sits in each panel; Ts: each joint under the top rail together with the rail's underside corners beside it (the corners where the rail meets the bar), one T each; a T is rusted when any of its pixels is
- Pass: from rust 0.2 (Typical's 0.23 included): Ts rusted >= 60 % (>= 85 % from 0.5). From rust 0.25: feet rusted >= 40 % (>= 80 % from 0.5); the rails' rusted share >= 3x the other faces'; the other faces hold <= 10 % of all rust up to 0.75 and <= 25 % at 1.0; on panels (200 rusted pixels or more), 60 % or more of the rust in each panel's bottom quarter
- Origin: U (round H: 'Rust would probably build along the top, drip down a little, gather along the bottom railing, and then drip down the vertical columns ... I wouldn't just expect the rust to grow radially around the existing rust between steps, but ... grow along the surfaces most affected by water and following the water's flow'); L (research weathering-rust-water §1: feet and pockets first, then joints and welds where 50-90 % of attacks start (Knudsen 2023), the top rail's face (horizontal steel corrodes 2-3x faster, BRANZ), the bottom rail, upright faces last); U (round J, rust at 0.25: 'the underside corners, like the corners of the "T" should be where rust gathers first from water pooling, rather than the top. The top would probably advance more with advanced wearing ... the rust would be like TrTrTrTr'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.4: edges and welds hold 50-90 % of corrosion starts, weld toes get 50-70 % of the flat film; paint's contact angle (70-78 deg) is over the 45 deg Concus-Finn limit of a 90 deg corner, so drops sit in the corner and it dries last); C (shares)

**R4. Rust grows along the flow**

- Measure: the rust control's steps: the new rusted steel at each step that continues earlier rust along its member (0.3 m along a rail, 0.5 m down or 0.05 m up an upright) or starts at a foot or joint (a T counts with the rail's underside corners beside it, as R3 counts it); new rust creeping more than 0.05 m above earlier rust on an upright; the mean length of the rusted rail segments
- Pass: per step: >= 70 % continues or starts at a foot or joint; <= 10 % creeps up; the mean rusted rail segment x1.3 or more until the rails are 80 % rusted
- Origin: U (round H: 'Rust would probably build along the top, drip down a little, gather along the bottom railing, and then drip down the vertical columns ... I wouldn't just expect the rust to grow radially around the existing rust between steps, but ... grow along the surfaces most affected by water and following the water's flow'); M (research §2: paint creep is 0.1-3.5 mm a year, under a pixel, so growth is new sites on the same wet lines and longer segments, not rings); U (round J: the Ts' underside corners are 'where rust gathers first ... the rust would be like TrTrTrTr')

**R5. Post feet stain the concrete**

- Measure: per post foot over paint: rust on the paint below (T2+, within 0.12 m of the post axis) reaching 0.1 m; its width in the top 0.04 m (the head) against the post width and its lowest quarter; the slab-edge face below the rails (found through the gap under the bottom rail) rusted in its top 0.05 m; parapet plates
- Pass: stained feet >= 25 / 50 / 80 / 90 % at rust 0.25 / 0.5 / 0.75 / 1.0; head 1.5-4.5x the post width (median), the lowest quarter no wider than the head for >= 80 %; slab-edge cover 5-20 % at 0.5 and 20-50 % at 1.0; parapet plates: <= 30 % stained, each <= 0.2 m
- Origin: U (round H: 'I'd also expect streaking on the concrete where the fence posts meet the concrete, following water and rain'); P (research §4: a halo 5-10 cm at the foot; copings under railings stained on 57 % of buildings in the Brunswick survey); M (photos: runs keep their width or narrow, the head 1.6-2.6x the tail)


### Colour

**R6. Rust colour follows age and density**

- Measure: rusted steel: median hue and chroma; between the rust control's steps, the median L* of rust already there against the new; stains below the feet: the head (top quarter) against the tail (lower half)
- Pass: steel hue 40-75 deg, C* 10-35; old rust >= 4 L* darker than new (series); stain heads hue 48-62, tails 64-80, head L* >= 6 below the tail
- Origin: M (research §6: fresh lepidocrocite L* about 56, weathering-steel patina 29-33, photo stains: heads L* 30-35 at 52-56 deg, tails 45-50 at 68-75 deg; diluting iron oxide lowers its chroma)


### Texture

**T0. Detail holds at the player's nearest approach**

- Measure: magnification: screen pixels per metre at each surface class's nearest approach (p = W / (2 tan(HFOV/2) d), Unreal's 90 deg horizontal FOV on a 3,840 px screen; walls and railings 1.0 m) over each detail carrier's pixels per metre. The 50 px/m masks are reported, not judged: the detail reveals their edges
- Pass: <= 2 screen pixels per texel for every detail carrier (wx_texcheck, run by weather_gate.py texture before any review page)
- Origin: U (round I: the texturing miss, 'a big miss'); L (docs/redesign/research/art-review-and-qa.md §6.1-6.2: studios check on-screen magnification at the player's camera; Epic's texel-density and mip views)

**T1. Detail at game texel density**

- Measure: the detail tiles each layer is revealed against, and the coat: pixels per metre
- Pass: detail tiles >= 1,000 px/m; the coat's detail >= 1,000 px/m; review close-ups at 1,000 px/m
- Origin: U (round H: 'these textures are very, very low res'); L (research texturing-at-scale §2: 512-1,024 px/m street level)

**T2. No tile period shows**

- Measure: on a 200 px/m composite of open wall (plain wall, no openings, frames or fixings), high-passed at 5 cm: the luminance correlation coefficient at each tile's period (along x and y) less the median of its ring at that radius
- Pass: <= 0.15 at every tile period (plainly repeating tiles score about 0.98, hex-tiled detail about 0)
- Origin: U (round H: 'tiling with distribution algorithms to avoid the grid pattern'); L (research tiling-and-distribution-algorithms)

**T3. The fine composite keeps the coarse amounts**

- Measure: the fine composite box-filtered back to 50 px/m against the build's own albedo, over walls 2 cm or more from another surface: luminance ratio
- Pass: mean within 1 +- 0.03; 5th and 95th percentiles within 0.85-1.15
- Origin: I (the 68 rules measure the 50 px/m maps; the detail must not change what they measured)


### Peeling

**P1. Coatings fail in the standard amounts and kinds**

- Measure: painted walls by preset: the flaked share of the painted wall (the peeling layer's alpha, ISO 4628-5 quantity); the share of the flaked area that reaches the concrete (type b; the rest shows an older coat, type a)
- Pass: Kept 0 (<= 0.02 %); Typical <= 0.1 %; Worn 0.3-1 %; Derelict 3-15 %; type b <= 25 % at Worn, 30-60 % at Derelict (checked once the flaked share is 0.1 % or more)
- Origin: U (round I: 'if this is a painted or coated surface, then paint cracks, chipping, and peeling exposing the concrete below'); L (docs/redesign/research/coatings-concrete-corrosion.md §2: ISO 4628-5:2022 classes 0.1/0.3/1/3/15 %; NILIM TN 1182: the multilayer finish's top coat peels before the main coat reaches the concrete); C (the mapping to presets)

**P2. Coatings fail where water stays**

- Measure: the flaked area (alpha-weighted) in the zones where water gets behind the coat: within 0.3 m below tops (sills, upstands, parapets), along drip lines and slab noses (0.1 m), within 0.15 m of cracks and joints, 0-0.5 m below the rails, the splash zone 0-0.5 m above the foot; the rest is the open wall. Soffits are not in the planes' paint mask
- Pass: from Worn: >= 65 % of the flaking in the zones; the open wall holds <= 20 % of it at Worn and <= 35 % at Derelict
- Origin: L (docs/redesign/research/coatings-concrete-corrosion.md §2: NILIM public-housing survey, Nippon Paint: tops where water stays, NPS Brief 10: protected areas and water behind the coat; the foot's rising damp is the classic cause on masonry); C

**P3. Flakes are crisp, layered and sized like flakes**

- Measure: at 1 mm/px (wx_texcheck, the foot of the south front): the mean 0.9-0.1 width across flake outlines (pixels between 0.1 and 0.9 per outline pixel); the area-weighted flake size; type-b flakes' L* and C*; type-a flakes' L* and a*b* against the paint 3-8 mm out, past the lip
- Pass: ramp <= 1.5 px; typical flakes 3-30 mm at Worn, 10 mm and up at Derelict (ISO 4628-5 size classes); type b L* 55-68 and C* <= 4; type a 2-10 L* lighter than the paint round it, or a hue step away (a*b* 2 or more apart, L* within 10)
- Origin: U (round I: 'paint cracks, chipping, and peeling exposing the concrete below'); L (docs/redesign/research/coatings-concrete-corrosion.md §2: ISO 4628-5 sizes and types, the multilayer failure order; NPS Brief 10); P (r4-visual-reference: crisp curled flakes in layers); C


### Metal

**R7. The coating breaks before the steel rusts**

- Measure: railing steel at 50 px/m: bare metal (the bare-steel layer) as a share of the steel by preset, and the share of it at the hand zone (the top rail), the joints or next to rust. At 1 mm/px (wx_texcheck, the rails close-up): for rust patches of 2 cm or more with 1 cm or more of edge on painted steel, the share of that edge with exposed metal or lifted paint (a rim cannot form on the member's outline); at 1:1 (the rails close-up), the exposed metal's colour: the median L*, a*, b* of its albedo
- Pass: bare metal 0.05-0.5 % of the steel at Typical, 0.3-2 % at Worn and Derelict, >= 60 % of it at the hand zone, joints or rust; on a rust sweep entry the share follows the control and only the placement clause binds; close-up: from rust 0.5, >= 50 % of patches have a rim on >= 30 % of their perimeter, and the exposed metal in them tarnished: median L* 38-48, a* 0 to +4, b* +2 to +8 (50 px or more)
- Origin: U (round I: 'work in exposed metal here both around the edges of the rust and some exposed metal in general. Safe to assume it didn't just rust directly through the white enamel or coating right?'); L (docs/redesign/research/coatings-concrete-corrosion.md §3: edges, welds and thin peaks fail first; rust creeps under the film; docs/redesign/research/surface-detail-techniques.md §6: exposed metal or primer on 30-70 % of a patch's perimeter); C (shares); U (round J, the rails at arm's length: 'Should be a little darker, tarnished/worn'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.5: oxide over the metal, 60-80 % of it; L* 38-48, against round J's 55)

**R8. Rust runs down the bars**

- Measure: for each rusted T with 0.3 m or more of bar below it, the run on that bar from the T's lower end to the bottom rail or the foot (the run layer's alpha >= 0.12, about dE 5 on white paint; 1-2 px holes in the steel mask inside the member are crossed): its length as a share of the bar, whether it reaches 3 cm, the colour difference against clean paint in its top quarter over its lowest quarter; for bars whose run comes within 0.12 m of the bottom rail, whether there is a collar in the 5 cm above the rail
- Pass: from rust 0.2 (the 0.25 bands below it): runs >= 3 cm below 40 / 70 / 85 / 90 / 90 % of rusted Ts at rust 0.25 / 0.5 / 0.6 / 0.75 / 1.0 (Derelict is 0.61); the median run 2-30 / 30-75 / 75-100 / 80-100 / 85-100 % of its bar (linear between); from rust 0.5, runs reaching 80 % of their bar >= 5 / 45 / 60 / 75 % at 0.5 / 0.6 / 0.75 / 1.0; head >= 1.3x the tail; a collar on >= 50 % of the bars whose run reaches the bottom rail (10 such bars or more). The runs are their own layer, so R1-R3 count corrosion only
- Origin: U (round J: 'The vertical slats/posts are still too rust free. The rust for derelict should be running all the way down or almost al the way down'; 'There's still no rust going DOWN the vertical slats'); U (round I: 'If the water continually drips down the vertical rails you would think there would be vertical streaks of rust'); P (rust note S43, S44a: runs below joints, whole uprights at derelict); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.3: member-wide for 2-5 cm under the joint, then a stripe down the face with tide lines, ending in a drip or a collar; docs/redesign/research/coatings-concrete-corrosion.md §3: the uprights drain the top rail); C (shares)


### Colour

**R9. Dark old rust and bright new rust side by side**

- Measure: rusted steel from rust 0.5: the share in a dark class (L* <= 32) and a bright class (L* >= 46 and C* >= 30), where each sits (dark: where water stays: feet, joints, the bottom rail, rail tops and, from round K, the rails' drip line, the Ts' underside corners and the first 0.1 m of each bar below a T; bright: within 2 cm of a rust front), and the L* spread (p90 - p10) of all rust
- Pass: dark 15-40 %, >= 60 % of it at those parts; bright 8-25 %, >= 60 % of it at fronts; L* spread >= 14
- Origin: U (round I: 'mix in some areas of darker intense rusting, and slightly brighter new wet rust'); L (rust note §6: fresh lepidocrocite L* about 56, old 28-34, magnetite 25.5; thick rust has an ochre outer and a dark inner layer, docs/redesign/research/coatings-concrete-corrosion.md §3); C; U (round J: the Ts' underside corners are 'where rust gathers first from water pooling'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.3-1.4: a dense collar under each joint, drops hanging under the rail)


### Gradients

**F5. Derelict's top band and top corners carry the most**

- Measure: exposed walls: mean D (arris rows left out) in the band 0.05-0.6 m under the wall top and in the top corners (within 1.5 m of a wall end and of the top), each over the wall mean; growth T2+ cover in the top corners over the rest of the wall; the share of the top edge (within 5 cm) where the coat is peeled
- Pass: from E 18: band >= 1.4x; corners 1.6-3x; corner growth >= 2x; top edge peeled on 15-50 % at Derelict and <= 5 % at Typical
- Origin: U (round I, Derelict: 'Top edge and the top corners need a little bit more attention'); L (docs/redesign/research/coatings-concrete-corrosion.md §4: PCI DN-29, the top corners are the wettest part of a facade, up to 20-30x the face centre's rain; the top quarter takes 41-47 % of the driving rain; tops where water stays whiten and blister; corners carbonate 1.2-2x faster); C


### Placement

**G7. Inside corners and recesses collect a little more**

- Measure: mean D in 0.1-0.4 m strips beside inside-corner lines (a nearer wall beside, at one depth) over the same rows' wall 0.6-1.5 m away, on planes where the strip and that wall each cover 1 m2 or more, and in 0.55-0.7 m (no outline); recess faces (0.3 m or more behind the nearest wall around) over the open wall, where both are large; from E 14, growth T2+ cover in the bottom 1 m of the corner strips and the bottom 0.3 m of recess faces above each floor line over the open wall
- Pass: from E 10: corners 1.15-1.6x (Derelict 1.25-2.0x), <= 1.1x at 0.55-0.7 m; recess faces 1.1-1.5x; corner and recess bottoms' growth >= 2x from E 14
- Origin: U (round I, Derelict: 'the corners and recesses could use a tiny bit more growth and dirt build up'); L (docs/redesign/research/coatings-concrete-corrosion.md §4: PCI DN-29, run-off concentrates at inside corners; set-backs are not rain-washed; NPS: protected areas are not rinsed; organic note W2); L (docs/redesign/research/surface-detail-techniques.md §2: masks from occlusion and corners, as Painter's and Houdini's mesh-map generators); C


### Material

**J1b. The clean coat's colour drifts, not only its value**

- Measure: std of C* band-passed at 10 cm-2 m on each plane's clean albedo (painted walls)
- Pass: 0.3-1.2 on every plane
- Origin: U (round I: 'more variety in saturation'); L (docs/redesign/research/surface-detail-techniques.md §7: the clean coat varied in value only; concrete is never a monotone block colour, hue drift 1-3 deg at C* 1-4); C

**J3. Concrete has voids, aggregate shadows and its own chroma**

- Measure: the texture stage's concrete (wx_concrete tiles at 1 mm/px): the cast face's void share, voids per m2 from 5 mm and from 10 mm, the largest; aggregate shadows (1 L* or more darker than their surroundings, voids left out); the clean concrete's C* median and p10-p90 spread; through the spray coat: open voids under 2 mm and dimples from 5 mm per m2
- Pass: voids 0.3-2 %; 30-150 per m2 from 5 mm and 5-40 from 10 mm; the largest <= 25 mm; shadows 2-8 %; C* median <= 4 with spread >= 1.5; the coat: no open voids under 2 mm and 2-60 dimples per m2 from 5 mm
- Origin: U (round I: 'Small spots of unevenly mixed concrete, or flecks even, of darker cooler areas or pebbles embedded in it. Very faint but noticeable ... look into pitting ... small pits like 1cm wide'); L (docs/redesign/research/coatings-concrete-corrosion.md §1: JCI 2019 test panels 1.25-1.82 % voids, up to 6.5 mm deep; ACI: bugholes up to 25 mm, mostly 15 mm or less; aggregate transparency spots 5-25 mm; filler and spray tile hide voids under 3 mm); C (counts, shadow cover)


### Metal

**R8c. Runs read at the player's distance**

- Measure: the player's view of a railing at 1 m (the review's touch_rails window on the S front, 1,920 px/m: 4K at 90 deg): for each bar (30 cm or more of steel), the rows from the T down where the run (alpha >= 0.3) differs from the clean paint by dE >= 15 over 2 mm or more of the bar's width, gaps under 1 cm crossed: the bars whose run reads for 3 cm or more, the run's length as a share of its bar (the median over the bars with one), the head's dE (its top 3 cm), the run's hue
- Pass: from rust 0.2: runs read on >= 30 / 60 / 80 / 85 / 85 % of the bars at rust 0.25 / 0.5 / 0.6 / 0.75 / 1.0, the median reading run >= 2 / 25 / 55 / 70 / 80 % of its bar (linear between); head dE >= 30; hue 50-80 deg (orange-brown to ochre, never pink)
- Origin: U (round J, the rails at arm's length: 'There's still no rust going DOWN the vertical slats. Not sure what I'm failign to communicate to you, I've explained it half a dozen times already'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.1: at 50 px/m a 16 mm bar is 0.8 px, so a run that passes there can be invisible at 1:1; a stain reads from about dE 15 over 2 mm); C (shares)

**R10. Rails rust along the drip line, then the face, then the top**

- Measure: the top rails of railing panels (rails with a T, within 0.1 m of one): the rusted share (as R1) of the rail's lowest pixel row at 50 px/m (the drip line under it, 2 cm), its middle rows (the face) and its upper row (the top)
- Pass: from rust 0.2: the drip line >= 35 / 60 / 75 / 90 % at rust 0.25 / 0.5 / 0.75 / 1.0 (linear between, the 0.25 band below it); the face >= 10 % from 0.75 and >= 50 % at 1.0; the top <= 10 % up to 0.75
- Origin: U (round J: 'needs more horizontal rusting on the horizontal rails'; 'the horizontal railing needs more horizontal rusting growth between steps'; 'The top would probably advance more with advanced wearing'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.4: rails grow by new failures along the wet lines beside each joint, the underside and lower arris first, then up the front face; the top face has the thickest film and is rain-washed); C (the research's lower-arris bands 8-20 / 30-50 / 60-80 / >= 90 %, raised at 0.25 and 0.5 because the drip-line row at 50 px/m is 2 cm, not 8 mm)

**R11. Dense dark scale carries a rough sheen, in the material**

- Measure: railing steel's rust (as R1, panels left out): the sheen mask (alpha >= 0.5; exported as M_hi.A on steel) as a share of it; the share of the sheen in the dark class (albedo L* <= 32) and at the wet parts (feet, joints, the bottom rail, the rails' upper rows); the share of rusted steel whose albedo has b* < 0
- Pass: none below rust 0.5 (<= 0.1 %); <= 4 % at 0.55, 2-8 % at 0.75, 4-15 % at 1.0 (linear between); >= 90 % of it dark and >= 60 % at the wet parts (50 sheen pixels or more); <= 0.5 % of rusted steel with b* < 0. The sheen is the material's: F0 0.04 -> 0.08 (UE Specular 0.5 -> 1.0; Godot SPECULAR 0.5 -> 0.71) and roughness -> 0.55 under the mask, never blue in the albedo
- Origin: U (after round J: 'look into some subtle touches of blue rusting on the rust ... some parts actually develop a rough blue sheen on the darker rust surfaces. Although that may be better off as a material shader in unreal or whatever game engine inherits these'); L (docs/redesign/research/rust-blue-sheen.md §1-2: compact goethite, magnetite and hematite reflect 13-31 % at normal incidence against about 4 % for paint and loose rust, so dense scale mirrors the blue sky; magnetite forms under thick, wet rust); I (§5: split-sum sky arithmetic); P (the note's photo references); C (shares)


### Peeling

**P4. Flakes and breaks stay on their surface**

- Measure: pixel pairs across a depth step of 3 cm or more on painted wall (4-neighbours, both painted, at 50 px/m): how often a flaked pixel's neighbour across the step is flaked (the paint failure's alpha >= 0.3), over how often any pixel beside a step is; the same for breaks (the damage alpha >= 0.5)
- Pass: the ratio <= 2 for flakes and for breaks (30 flaked or broken pairs or more), or not significantly above it: a ratio over 2 fails when that many coincidences would arise by chance under 1 % of the time at 2x the side's rate (Poisson); independent patterns read about 1, one pattern run across the step far more
- Origin: U (round J, the 2 m view: 'the same chipping pattern is clearly being applied to the front of the balcony as it is to the wall behind it, even though there's probably 1-2m of distance between them. Makes no sense'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §2.1-2.2: pros key patterns to 3D position or the object; a 2D elevation field crosses the 1.2-1.4 m step from a balcony front to the wall behind); I


### Edges

**N6. Grooves and their lips are respected**

- Measure: the player's view of the north walkway's panel joint at 1 m (1,920 px/m; a 20 mm groove found from the capture depth): the flaked or chipped share of the lips (4 mm outside the groove's edges), the groove floor and the open face (3 cm or more from a groove); the share of the joint's length with a crack along the floor
- Pass: from Typical: the lips >= 3x the open face (and >= 4 %); the floor <= 0.6x the open face + 2 points; a crack along >= 30 % of the joint at Worn and >= 60 % at Derelict; New and Kept: the crack on <= 10 %
- Origin: U (round J, the north walkway at arm's length: 'The chipping should respect the channel. It probably wouldn't chip the same way as the raised surface. Either more or less. Also, I'd expect some more chipping along the edges of the channel ... that difference in topology/depth needs to be respected'); L (docs/redesign/research/member-rust-and-geometry-aware-wear.md §2.3: paint pulls back to 50-70 % of the flat film at edges and lips take the knocks, 3-8x the open face's chips; paint over a moving joint cracks along it, 20-40 % of its length at Typical, 50-80 % at Worn, >= 80 % at Derelict); C

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
- **A0, A1 (tone and coverage tables)**: Typical takes Kept's round-F bands; Kept about 0.6x; Worn between Typical and Neglected; Neglected unchanged. Round F: asked which image is the default street block (35 years, upkeep 0.9), the user picked Kept on the south front and on the 1:1 top floors; Neglected was 'about right'.
- **F3**: 1.15 below E 13 (was 1.30 from E 8). Round F: 'the first jump from New to Kept has some excessive wear and ground level staining'; the photo walls (1.3-2.0) are older walls.
- **A4**: adds the ground band's steps across the presets. Round F: 'the jumps between the steps for the ground level could be more subtle'.
- **G5, H4, H5, L4**: new: seam crossings, long streaks and channels, a darker subset of streaks, a strong top step. Round-F review of the streaks ('even the last is too weak', 'more long vertical streaks', 'near-whole building long streaks', 'attention to intersecting corners'); every threshold sits between round F's measured values and the new generator's.
- **L3**: new: even steps. Round F: the stain control's jumps shrank (x2.7, x1.8, x1.6 at T2+); the stain amount now adds sites on a perceptual curve (x2.8, x2.5, x2.4).
- **M1-M8**: new family: organic growth. Round-F review of the growth (dark green and rust brown when severe, light green or dull yellow when weak, grows outward); bands from the growth research (O1-O12).
- **N1-N5**: new family: edges. Round-F review: edge wear and discoloration visible at 0.25, as its own rule set; bands from the edges research (E5-E9).
- **K5-K11**: new: spalled area, spall placement, crack density and widths, orientation, corner cracks, visibility, repairs. Round-F review: cracks from hairline to pattern cracks, spalls exposing aggregate, derelict at 1.0; bands from the damage research (S1, S5, C1-C23).
- **I3**: new: colour variety. Round-F review: more colour variety, calibrated on the photo walls.
- **G6**: new: no accidental lattice. Round-F review: the grime read as a grid; the 3.6 m material tile printed into the dirt.
- **G1**: sources include the slab drip lines. The rule names ledge drip lines; the source map lacked them, so channel streaks below slabs counted as unsourced.
- **K3**: measured on edge-damage clusters. Delamination spalls (round G) are spread by K5/K6, not clustered round a hotspot.
- **F3**: measured on the dirt. At damage 1.0 spalls and cracks cover the whole wall and lift its mean; the rule is about splash and ground dirt.
- **D_local**: arris rows and the edge layer left out. A chalked 1 px top arris raised the 'brightest 10 cm patch' reference, so every pixel near an edge read darker (T2+ 0.43 to 0.89 on one build).
- **clock**: years since repaint 0.665 x the cycle (was the full cycle); 17 % kept (was 22 %). Round-G review: Kept picked as the 35-year default again, and 'the current Kept becomes Typical, current Typical becomes Worn, Worn becomes Derelict, and a milder level of wear becomes Kept'; the fit puts the three presets on the old anchors within 0.04 E.
- **presets**: kept 10 years at upkeep 1.0 (E 5.56, halfway); neglected renamed derelict; worn and typical unchanged in age and upkeep. The user's rename; Kept halfway keeps the tone steps even (A6).
- **A4**: order new < kept < typical < worn < derelict. The rename.
- **A5**: new: seeds read as the same age. Round-G review: seed 1 looked stronger; the seeds' film contrast differed by 0.50-0.69.
- **A6**: new: even preset steps. Round-G review called its ladder even; the new Kept must not crowd Typical.
- **I4**: new: dark green and yellow mark families. Round-G review of the dirt colour.
- **I5**: new: green marks darken with age. Round-G review: mould and mildew darken with age.
- **M3**: beyond 5 % cover: W2-W3 cover >= 3x the open wall's (was a 50 % share of the growth). The share could not hold where wet zones are 5.6 % of the wall: at 10 years M7's onsets put 12 % on the shaded open wall (round G's growth 0.75: W2-W3 share 0.35, cover ratio 9).
- **M8**: not judged from a wall with no growth yet. A front needs growth to grow from; round G failed its step from 0 on this.
- **M9**: new: growth darkens and thickens with age. Round-G review.
- **R1**: new family metal: rust by grade on steel. Round-G review: rust too little; round G's 0.25-8 % of the metal over 0.25-0.75.
- **R2**: new: each rust step shows. Round-G review: rust growth stronger between steps.
- **growth control**: years at 0.25-1.0: 3.1, 5.7, 10, 22 (were 3.7, 5.9, 10.2, 22); shaded open wall (W1) onset 3.5 years (was 3.0); colonies keep arriving up to 0.6 of a class's time scale after its onset (was 0). Emulated round-H growth sweep: M8 needs 5 % new patches per step (round G 3-5 %), M3 needs 70 % of young growth in W2-W3 (68 % at 5.9 years on the lighter Typical), L3 even steps (1.41 before, 1.30 after); M5, M7 and M9 kept.
- **L1**: the intensity clause (the top tier, the frontier or the T4+ share rising once per two steps) is waived for rust, as for damage; R2 checks rust's steps. Round-H rust sweep: rust on the steel reaches T6 from its first step and T4+ is 85-90 % of it at every step, so its intensity cannot rise; its coverage still widens 1.9x per step (L1's widening clause holds).
- **R2**: the steel's mean colour difference must rise x 1.5 or more (or +2) per step; was +2 only. Round-H rust sweep: the even schedule (5, 10, 20, 40 % of the steel) doubles the share and the mean colour difference at every step (1.07, 2.22, 4.68, 10.25) but adds only +1.15 at the first; a schedule steep enough for +2 there (5, 16, 32, 58 %) broke L3's even steps (ratios 2.99, 1.93, 1.75). The share clause already reads 'x 1.5 or +10 points'.
- **soiling film (light load)**: under the Worn clock (E 14.5) the coat's texture and the dust grain keep their absolute strength: their relative amplitude x (14.5 / E), capped at 2 (Kept 2.0, Typical 1.35); the joints as before. Round-H Kept (E 5.6) failed B3 with 26 % of its soiling layer flat at 20 cm (17 % of D): a light film scaled from Typical's pattern was too even. A stronger grain alone fixed B3 but dropped J2 to 0.219, since grain is not the material; with the coat too, the rebuilt Kept has B3 0.011 (D) and 0.023 (soiling) and J2 0.297. The coat's micro-relief fills with dirt first and shows through a film until it is Worn-thick, which also lifts Typical's marginal J2 (seed 1 rebuilt: 0.256 to 0.291).
- **solver (heavy presets)**: from clock E 19 the mark-gain search may go down to 0.45 (0.6 elsewhere). Round-H Derelict failed A1 with T6+ 0.0314 against 0.0299 at the 0.6 floor; its darkest tier is mostly soiling, growth and the ground band, so the marks give way (rebuilt at a gain of 0.47: T6+ 0.0290, every rule passing).
- **splash zone**: the soiling's foot boost gets a ragged reach, a texture that follows the coat and varies along the wall (heavier stretches, log amplitude 0.8), and a dark core in the bottom 25 cm with soil-splash specks, applied after the tone's saturation; all of it fades out from clock E 12 to 20. Round-H B2: at the Typical clock the large (>= 2 m) marks are mostly foot bands, smooth because the boost was an exponential fade compressed by the saturation (inner CV 0.34-0.40; seed 1 passed at 0.414, seeds 2 and 3 failed at 0.377 and 0.385, grime 0.2 and 0.3 at 0.398; round G's Kept at the same clock 0.419). A grainy texture over the whole zone lifted seed 2's north front to 0.449 but cost J2 0.02; the coat texture, the along-wall variation and a grainy core only: 0.432 with J2 unchanged. Rebuilt Typical seed 1: 0.414 to 0.463; seeds 2 and 3 pass B2 (0.432, 0.414). Fading it out keeps Derelict's darkest tier (A1 T6+) in its band.
- **colour cells (heavy streaking)**: above streak amount 0.5 the cells' opacity boost and colour for streaks fade toward the plain dirt, to 0.35 at 1.0; every preset and the sweeps' lower steps are unchanged. Round-H streak sweep: 0.75 and 1.0 failed I3 (gable colour spread 4.18 and 4.7 against the photo walls' 4.0) because the cells' boost (about 1.5x at Typical) multiplied many overlapping streaks; gable after 3.29 and 2.88. Rebuilt, 0.75 passes every rule; 1.0 still fails C3 and H1 (striped: heavy streaks dominate the lighter Typical).
- **A1, A0 (Kept, Derelict)**: an explicit Kept anchor at E 5.56 with lighter dark tiers; Derelict's bands and tone raised. Round-H review: Kept 'a tiny bit too dirty, namely the darker stains look a little too dark'; Derelict 'Still looks too light ... the amount or spread'. The solver held Derelict's mark gain at its 0.45 floor to stay inside the old T6+ band (research weathering-water-layers: spend the budget on area).
- **G1**: horizontal joints and grooves count as sources. Round-H review: panel streaks come 'from the horizontal grooves'; the floor lines and construction joints are drip features.
- **H6 (new)**: streaks gather in the vertical lines. Round-H review: 'streaking will probably be most severe along the panel lines going down'.
- **I4, I5 (rewritten), I6 (new)**: organic colour lives in the growth layer on one continuum (light tint, dark yellow, olive, dark green, muddy, reddish-muddy) by local age; water and dirt marks keep the dirt palette; a place only moves forward along the continuum. Round-H review: colours 'flipping between levels', 'keep it on a continuum', water staining and organic growth as separate layers ('one is a growth from the other'). The flips came from the colour cells' odds rising with the soiling clock (research weathering-water-layers §2).
- **L5 (new)**: marks grow in area with age. Round-H review: streaks and the ground band 'aren't expanding/increase size and surface area'. The solver's accent gain scaled the streak amount, so Worn's effective amount (0.26) fell below Typical's (0.30); from round I the amount sets the extent and the gain only the opacity.
- **M1**: the green and yellow family clauses dropped; the tint and dirt-band clauses kept. Round I: young growth is a light yellow tint first, then dark yellow, then green (the user's continuum).
- **M3**: from E 18, 50 % of growth in W2-W3 while cover is under 5 %. Round-H review: Derelict's growth is 'mostly in the same areas'; research: north-wall growth spreads from about 2.5 % to 28 %.
- **R3, R4 (new)**: rust follows the water on the rails and runs on the concrete below. Round-H review of the rails ('gather along the bottom railing ... drip down the vertical columns ... streaking on the concrete where the fence posts meet the concrete').
- **T1-T3 (new)**: the texture stage: detail at game texel density, no tile period, coarse amounts kept. Round-H review: 'these textures are very, very low res ... tiling with distribution algorithms ... trimsheets, stamps and decals'; research texturing-at-scale and tiling-and-distribution-algorithms.
- **R3, R4 (rewritten), R5, R6 (new)**: the first round-I rust pair (wetness enrichment 1.8x, two concrete runs per 10 m) is replaced by the research's four rules: rust by part of the steel, growth along the members between steps, stains below the post feet with a head and a narrower tail, and colour by age and density. The round-H rust answer asked for the topic to be researched ('Research this rust topic more'); docs/redesign/research/weathering-rust-water.md §7.2. The old R3 passed on rust that sat mostly on upright faces (40 % of all rust on them in the first round-I smoke build, Worn); the new R3 fails it.
- **R1, R2, R3 (railing steel; panels)**: R1 and R2 count the railing steel R1 always named (rails, posts); flat steel panels are their own class, and R3 adds a clause for them: their rust sits in each panel's bottom quarter. Round I builds: the north front's steel is 74 % flat panels (the units' steel doors and pipe-shaft doors under the corridor slab), which held about half of all rust when every plane had to reach the same share. The generator now runs one rust clock for the building: sheltered doors rust 0.5-5 % while the south rails reach the grade (research weathering-rust-water §1: exposure and time of wetness decide).
- **T2 (text)**: the text now names the measure the gate and the large-scale-texturing skill use: the correlation coefficient's excess over its ring median, at most 0.15 (the text read 'over the median ... <= 1.5'). The text and the check disagreed; the check is the stricter reading (a ratio of 1.5 would let a visible repeat through), so the text follows the check.
- **T2, T3 (north window)**: the north front's open-wall check window moved to plain wall (x 2580-2780, y 730-930 at 50 px/m, 99.99 % wall). The old window (x 1260-1460, y 400-600) was 21 % windows, a downpipe and meter boxes repeating every storey; their spacing scored as a tile period (New: 0.16 at the coat detail's 0.6 m, 0.18 at the stain tile's 2.05 m, while the south front's plain window scored 0.001-0.012), against the rule's 'open wall'.
- **P1, P2, R7, R8, R9, F5, G7, J1b, J3**: new rules (round J). The user's round-I notes on rust, concrete, coatings and Derelict's top edge, corners and recesses; bands from the research round (docs/redesign/research/coatings-concrete-corrosion.md, docs/redesign/research/surface-detail-techniques.md), estimates tagged C.
- **P1**: the research draft's third clause (>= 70 % of flaking near cracked or blistered coat) left out. The generator draws the checked film around its own flakes, so the clause would hold by construction; where the flaking sits is P2's measure.
- **P2**: the splash zone at the foot (0-0.5 m) added to the draft's zones; the soffit clause dropped. Rising damp at the foot is the classic cause of paint failure on masonry and the generator puts flaking there; the planes' paint mask holds no soffits.
- **R7**: the draft's 'rust at defects >= 85 %' clause not adopted at 50 px/m. Railing members are 1-2 px wide at 50 px/m, so every steel pixel lies within 2 cm of an arris; the rims are measured at 1 mm/px instead.
- **R3**: its cap on rust on other upright faces counts corrosion only. The runs down the uprights (R8) are their own layer (rust_run), so the cap no longer blocks the vertical streaks the user asked for (research docs/redesign/research/coatings-concrete-corrosion.md §3).
- **L5**: recorded: adopted at streak area x 1.15 and the ground band +5 cm, weaker than the water-layers note's V4 (x 1.3, +0.1 m). The round-I presets passed the user's review at this strength ('Yes, both grow'); the audit (research-to-practice-audit.md rank 6) found no record of the choice.
- **H6**: recorded: adopted at 0.3 m and 40 %, weaker than the note's V3 (0.15 m, 50-70 %). No reason was recorded in round I; the user's round-I review raised no issue with where streaks run. Kept, pending a pick; the audit asked for the record.
- **I5**: recorded: 8 % may go back, against the note's 2 %. No reason was recorded in round I; kept pending a pick, recorded at the audit's request.
- **A1**: recorded: Derelict T2+ 0.50 and T3+ 0.28, against the note's 0.60 and 0.32; Kept T5+ up to 1 %, against 0.3 %. The user's round-I Derelict note asked for more at the top edge, top corners, corners and recesses, which F5 and G7 now carry, not for an overall raise; the bands stay pending a pick, recorded at the audit's request.
- **all**: the 22 citations of roundG/research/*.md (a scratchpad path) now name the repo files docs/redesign/research/weathering-*.md. The audit (research-to-practice-audit.md rank 28): a citation must resolve in the repo.
- **G7**: the corner ratio is measured only where the strip and the far wall each cover 1 m2 or more on a plane (was 50 px, 0.02 m2). Round J test builds: the W gable's only inside corner is the side of a 0.1 m recess beside a pipe chase, measured on 144 px (0.06 m2) of strip in rows 300-450; its ratio read 0.87 at Worn and 1.07 at Derelict, noise from one stretch of wall. The fronts measure 29-46 m2 of strip each and are unchanged.
- **P3**: at 1 mm/px, type-a flakes are compared with the paint 3-8 mm out from the flake, past the 1.5 mm lip (was 0-4 mm). Round J test (J13 Derelict): the 0-4 mm ring held the lip, the broken edge's clean body that the renderer brightens by 6 % as P3's own lip feature, so the check compared the older coat with the lip rather than with the weathered coat round it (type-a dL read -2.2).
- **T0, P3**: added to the rulebook as written texture-check rules (they already bound builds through wx_texcheck). A rule that binds must be in the rulebook the review page and weathering-rules.md show.
- **G7**: recess bottoms are the bottom 0.3 m of a recess face above its floor line (was: the 0.3 m above any wall pixel with a nearer surface below it), in the gate and the generator alike. Round J tests: a nearer surface below is usually a parapet hiding the wall, not the junction where water stands; on Worn's north front 16,969 of 27,292 severe-growth pixels sat along the walkway parapet lines (L* p25 51.3), a band of growth the wall does not have there.
- **P3**: the ramp is the mean 0.9-0.1 width, pixels between 0.1 and 0.9 per outline pixel (was 0.8 over the median central-difference gradient). One partial pixel between full values gives a central difference of 0.5, so any anti-aliased step read 1.6 px and no crisp edge could meet 1.5 px: round J's edge widths 0.10, 0.05 and 0.02 all read 1.6.
- **P3**: type a also passes as a hue step away (a*b* 2 or more apart, L* within 10). The research's own clause (docs/redesign/research/coatings-concrete-corrosion.md §2: an older coat 2-10 L* lighter, or a hue step away); the check had dropped the alternative. The danchi's older coat is now a pale cream under the white.
- **R7**: on a rust sweep entry (rust overridden on Typical) the share band does not bind; the placement clause does. The bands are per preset, and a sweep entry is a Typical build whose rust the control sets (0-1.0), so Typical's 0.5 % cap would reject every step above it; the amount budgets A0, A1 and B1 are set aside for every sweep for the same reason.
- **D_local (A1, A2, A3, B1, B2, D1, E1)**: the peeling layer's pixels are left out, as the edge layer's are (P1-P3 measure them); in the gate and in the solver's coverage alike, for every preset. Round J's first Derelict build failed A1 alone, T6+ 0.045 against 0.040; the peeling layer touched 28 % of its T6+ blocks. Exposed concrete (L* 64) under the white coat reads D_local about 0.5, T6 by its darkness (T6 is defined as a black crust), and P1's ISO 4628-5 amounts put 0.9-9 % of Derelict's wall there (3-15 % flaked, 30-60 % of it concrete) against A1's T6+ cap of 4 %, so the two rules counted the same pixels and could not both pass at P1's upper end. A1's bands were set on the user's picks in rounds F-I, with the peeling layer off (on from round J). Left out, the same build reads T2+..T6+ 0.716 / 0.398 / 0.189 / 0.085 / 0.036 (0.719 / 0.402 / 0.192 / 0.086 / 0.037 leaving out only pixels at least half flake). A flake lighter than the clean coat no longer moves the reference either (round J's type-a trap).
- **R8**: measured from the joint's lower end, over 1-2 px holes in the steel mask inside the member; joints with under 5 cm of upright below them left out. Pipeline 98 rejected rust 0.75 and 1.0 on R8 (median 0.12 and 0.26 m, runs below 76 and 79 % of joints). At rust 1.0, of the 1,002 rusted top joints counted as having no 5 cm run, 410 stopped on the joint's own unrusted lower pixels (a run of 0) and 530 on a 1-2 px hole in the captured steel inside the upright (the weld; the generator's run flows through it); 47 hang over a stub. With the run measured as the rule text says, the same generator reads rust 0.5 / 0.614 / 0.75 / 1.0: below 0.79 / 0.92 / 0.98 / 1.00, median 0.08 / 0.12 / 0.20 / 0.48 m, stained 0.059 / 0.107 / 0.210 / 0.575 (unchanged), emulated from the real planes (_emu_r8.py; it reproduces the gate's old numbers to 1-5 joints).
- **R7 (close-up rims)**: the perimeter counted only where a patch borders painted steel; patches with under 1 cm of such edge left out. Heavy rust spans whole members, so most of a patch's edge is the member's outline against the wall, where no rim can form: 29 / 26 / 20 % of the edge borders paint at rust 0.5 / 0.75 / 1.0 (33 % at Derelict). On the painted edge the rims are there at 0.5, 0.75 and Derelict (patches with a rim 1.00 / 0.90 / 1.00, against 0.73 / 0.45 / 0.59 on the whole edge) and missing at 1.0 (0.32 against 0.04): rust 1.0 still fails.
- **texture checks (T0-T3, P3, R7c)**: run on the Karma crop captures where they exist, as the review renders are. The pipeline ran them on the 50 px/m geometry upsampled, while the page shows the captures; T0-T3 and P3 read the same either way (Typical and Derelict compared), R7c moved (Derelict 0.62 -> 0.59, rust 0.75 0.50 -> 0.45 on the whole edge).
- **R3**: a T clause (Ts rusted >= 60 % from rust 0.2, >= 85 % from 0.5); feet >= 40 % at the first step (was 50 %). The user's round-J rust pick ('TrTrTrTr': the Ts' underside corners first, the top later); Ts are 5.2 % of the railing steel, and with them first the feet come second at 0.25. pipeline 101: Ts rusted 85 % at Typical (rust 0.228), 91 % at rust 0.25, 100 % at Derelict; feet 44 % at 0.25 (need 40 %).
- **R7**: the close-up checks the exposed metal's colour (L* 38-48, a* 0 to +4, b* +2 to +8). The user's round-J note on the rails at arm's length ('a little darker, tarnished/worn'); round J's bare metal was L* 55. pipeline 101: the exposed metal at 1 mm/px reads L* 42.1 / 41.7 / 41.3 at rust 0.5 / 0.75 / 1.0.
- **R8**: runs measured as a share of the bar below each rusted T, from rust 0.2, at the run layer's alpha >= 0.12 (was 0.06), with Derelict's anchor at a median of 75 % of the bar. Round J's bands asked a median run of 0.15-0.4 m at rust 0.75 (16-43 % of a 0.93 m bar) and counted alpha 0.06, about dE 1-5 on white paint, a tint the user could not see ('still no rust going DOWN the vertical slats'); the user asked for Derelict's runs 'all the way down or almost'. pipeline 101: runs below 70 % / 98 % / 100 % of rusted Ts at Typical / Worn / Derelict, median 4 % / 11 % / 82 % of the bar; 52 % of Derelict's runs reach 80 % of their bar.
- **R8**: the reach-80 clause starts at rust 0.5 (its ramp from 0 at 0.25 is dropped). The clause carries the user's Derelict note ('running all the way down or almost'); its linear ramp from 0 at 0.25 to 5 % at 0.5 asked 1 % at Worn's rust 0.3, where no user note or research figure sets one. Pipeline 99's Worn read runs below 97.6 % of rusted Ts and a median of 11.5 % of the bar, inside both bands, and failed on that 1 %: with runs varying per bar about a 15 % median (lognormal 0.35), 80 % lies 4.7 sigma out. pipeline 101's Worn: median 11 % of the bar, none reaching 80 %; it passes with the clause from 0.5.
- **R9**: its wet parts follow round K's water: the rails' drip line, the Ts' underside corners and the first 0.1 m of each bar below a T added. The first round-K test build (rust 1.0) failed R9 alone on the place clause, 49.9 % of the dark class at round J's wet parts: of the rest, 15,195 px sat on bars, 79 % of them within 0.1 m below a T (the dense collar), 5,422 on the top rail's drip line and 3,452 in the Ts' underside corners, where the user's round-J note puts the water; counted as wet parts, 86.8 %. The dark class itself (28.9 %) and the bright clauses did not move. pipeline 101: dark 96 % / 92 % / 85 % at the wet parts at rust 0.5 / Derelict / 1.0.
- **P4**: a ratio over 2 fails only when significant (Poisson, 1 %); no floor on the count. The fixed round-K generator read 2.65x at Typical from 4 coincidences where 3.0 are allowed at 2x (a 35 % chance), while round J's layers read 64 where 7 were allowed (P about 0) and Derelict's 12.95x (5,610 where 868 were allowed); a floor of 5 expected coincidences, tried first, passed that 64-against-7 case, so it was dropped.
- **P4 (generator)**: breaks and edge wear only on arrises: a bottom whose pixel below is a nearer surface is an occlusion line, not an arris; spall risk from the pixel's own surface's arrises. The first round-K test build failed P4 on breaks, 18.27x: the planes' edges counted the line where a balcony front hides the wall behind it (22,001 of the S front's 256,819 edge pixels, 27,589 of the N front's 190,873; median step 1.19 m), so chips were stamped on the hidden wall right above the front's own top arris, and the 0.15 m spall risk spread across the step. Recomputed on the same builds: Typical 2.65x, round J's Derelict 12.95x to 0.96x. pipeline 101: Derelict's flakes 1.12x and breaks 0.98x across a step; Typical's breaks 2.11x from 4 coincidences (P 0.5239).
- **R11 (generator)**: the sheen only on the darkest scale (dark weight 0.70 -> 0.90, was from 0.5). The first test build put 39 % of the sheen at L* 33-37: over white paint (L* 86) a dark weight under about 0.7 leaves the paint showing through the 0.92-0.98 rust alpha, so R11's dark clause (>= 90 %) read 60.9 %. pipeline 101: the sheen 2.2 % / 4.9 % / 9.8 % of the railing's rust at Derelict / 0.75 / 1.0, 100 % / 100 % / 100 % of it dark.
- **R7 (generator)**: exposed metal opaque where the coat is gone (was 90 % over the paint). The first test build's metal read L* 48.6 against R7's 38-48: 10 % of the white paint lifted L* 43 tarnish to about 50. pipeline 101: the exposed metal at 1 mm/px reads L* 42.1 / 41.7 / 41.3 at rust 0.5 / 0.75 / 1.0.
- **N6 (generator)**: lip chips raised (0.02 + 0.25 x wear -> 0.05 + 0.35 x wear) and the floor crack set to the research's table (years since repaint 3 -> 12, up to 85 % of the joint). The first test build chipped 2.05 % of Typical's lips against N6's 4 %; the crack followed (4 -> 12 years, up to 70 %), 9 / 62 / 70 % at Typical / Worn / Derelict against the research's 20-40 / 50-80 / >= 80 %, now about 20 / 77 / 85 %. pipeline 101: lips 8.3 % / 14.3 % / 44.8 % chipped or flaked at Typical / Worn / Derelict; the crack along 19 % / 93 % / 94 % of the joint.
- **R8c, R10, R11, P4, N6**: new rules (round K). The user's round-J notes on the rails (runs at arm's length, the rails' horizontal growth), the walkway (patterns across a depth step, the groove) and the blue sheen after round J; bands from the research round (docs/redesign/research/member-rust-and-geometry-aware-wear.md, docs/redesign/research/rust-blue-sheen.md), estimates tagged C.
- **R8c, R10, R11, P4, N6**: the research notes' rule ids renumbered for the rulebook. Docs/redesign/research/member-rust-and-geometry-aware-wear.md proposed R10 (runs at 1:1), R11 (Ts first), R12 (rails), R13 (tarnished metal); they are R8c, R3's T clause, R10 and R7's close-up clause here. docs/redesign/research/rust-blue-sheen.md's R10 (the sheen's amount and place) is R11; its R11 (F0 and roughness, never albedo) is R11's b* clause and the export contract, its material-ball clause unchecked until an engine look.
- **R10**: the research's growth clause (each step >= 1.5x the last until 80 %) carried by the rising bands. The drip-line bands rise 35 / 60 / 75 / 90 % step by step, which a sweep entry passes only by growing along the rail; R4's series clauses already ask new rust to continue earlier rust along its member.
- **N6**: the research's floor-darkening clause (5-15 L* at Worn and Derelict) not adopted yet. The floor's dirt follows the local soiling in the fine stage (30 % of the soiling's darkening, deepest at the floor's centre); a fixed 5-15 L* needs the user's look first.
- **R1 (recorded)**: the rust control's rusted share raised to 6.5 / 12 / 22 / 40 % of the steel at 0.25 / 0.5 / 0.75 / 1.0 (1.3 / 1.2 / 1.1 / 1x the grade; R1 allows 0.5-2x). Ts are 5.2 % of the railing steel, so at the grade's 5 % the T clause (60 % of them) and the drip line alone would take nearly all of 0.25's share, leaving little for the feet. pipeline 101: rusted 6.2 % / 11.6 % / 21.3 % / 38.8 % of the railing steel at rust 0.25 / 0.5 / 0.75 / 1.0.
- **R9 (generator)**: dark scale opaque at last, and its coverage held to a share of the rusted steel: 13 / 18 / 22 % at rust 0.5 / 0.75 / 1.0, none below 0.4. Round J's fix that makes thick old scale opaque (J13) never took effect: rust_flow.layer() and weather_fields.layer_rust() both returned the rust alpha clipped at 0.92, so over white paint (L* 86) L* 25 scale read about L* 37, and 27 % of Derelict's sheen sat on rust that did not read dark (R11 73 %). With the scale opaque, round J's weights put 55 % of Derelict's rust (71 % at rust 1.0) in R9's dark class against 15-40 %, and the noise thresholds barely moved it (the best, 40 % at 0.614, 53 % at 1.0): the scale's coverage is now cut by quantile, as the sheen's is; plain old rust over the darker paints adds about 20 points. Emulated on pipeline 99's Derelict (the steel's albedo replayed exactly, checked against the build: 35.1 % against its 35.6 %): 33.7 / 34.3 / 33.9 % dark at rust 0.5 / 0.614 / 1.0. Built (pipeline 101): dark 34.0 % / 35.3 % / 35.3 % / 35.0 % at rust 0.5 / Derelict / 0.75 / 1.0.
- **R11 (generator)**: the sheen only on opaque scale, its share cut over the railing's rusted steel (alpha 0.25 or more, panels left out), as R11 counts it. Cut over all rust (doors and faint fronts included), the generator's 10 % at rust 1.0 read 16.5 % of R1's railing rust, over R11's 15 %; emulated, 2.3 / 5.0 / 9.9 % at rust 0.614 / 0.75 / 1.0, all of it in the dark class. pipeline 101: the sheen 2.2 % / 4.9 % / 9.8 % of the railing's rust at Derelict / 0.75 / 1.0, 100 % / 100 % / 100 % of it dark.
- **K5, B1 (generator)**: the chips' hotspot count from the edges' full length, as calibrated; hotspots, satellites and background chips sit on arrises only. Pipeline 99's Typical and every rust step failed K5 (spalled 0.028 % against its 0.029 % floor, round J 0.033 %) and Typical failed B1 (its T5 tier 0.85 % against 1 %, round J 1.00 %) once the occlusion lines stopped taking chips: the count followed the shorter edge. pipeline 101: spalled 0.031 % / 0.156 % / 1.29 % at Typical / Worn / Derelict; Typical's B1 tiers [0.1889, 0.087, 0.0326, 0.0107, 0.005].
- **F5 (generator)**: from E 18, a wall's top edge flaked on at most 40 % of its length (the score within 5 cm of the top lowered, fading out by 15 cm). Pipeline 99's Derelict failed F5 on the west gable alone, its top edge 63.8 % flaked against 50 %: with round J's plane-wide noise it read 49.3 %, so round K's per-surface noise moved it, and a short gable top with few other wet zones on its plane takes a large part of the plane's flaking budget. Capped: the gable 40.3 %, the fronts unchanged (29.7 and 38.1 %), P1's flaked share and P2's zones unchanged. pipeline 101's Derelict: top edges W_gable 40.3 %, S_front 29.7 %, N_front 38.1 %.
- **N1-N5**: the edge rules measure arrises: the edge mask without occlusion lines (a bottom whose pixel below is a nearer surface). The generator draws edge wear on arrises only (round K); the occlusion lines (9-14 % of the fronts' edge pixels) diluted the measures: pipeline 99's Derelict read N2's continuity 0.564 against its 0.582 floor; on arrises 0.633, round J's value; N1, N3-N5 pass on Typical, Worn and Derelict. pipeline 101's Derelict: continuity 0.633.
- **R4**: new rust starts at a joint when it is in a T as R3 counts it (the joint with the rail's underside corners beside it). Round J dropped rust 0 from its sweep by hand: R4 failed the step from no rust, 'a rule question'. Measured on pipeline 99's rust 0 -> 0.25 (_k_r4first.py): 41.8 % of the new rust in the feet and joint masks against 70 %, and 34.9 % more in the Ts' underside corners, where the user's round-J note puts the first rust ('TrTrTrTr'); 98.8 % of it at a T, a foot, the rail within 0.3 m of a T or the bar 0.5 m below one. R4 predates round K's T corners, which R3 counts as part of each T: with them, 76.7 %. pipeline 101's rust series (0 / 0.25 / 0.5 / 0.75 / 1): R4 passes, continuing or starting at a foot or T 76 % / 86 % / 76 % / 72 % step by step.
- **R4 (generator)**: the bottom rail's wetness at the research's 1.8 (was 1.5). Pipeline 99's rust sweep, emulated (_k_emu_r4.py, the builds' R4 to 0.005): between rust 0.5 and 0.75 the rails' mean rusted segment grew 1.25x against R4's 1.3x, the user's 'horizontal rusting growth between steps'. The bottom rail's joints start then, one per bar, and about 1,400 of them stayed spots of 2-8 px instead of spreading along the rail that collects the bars' water; the research's water table (docs/redesign/research/weathering-rust-water.md §7.1) gives the bottom rail 1.8 against the top rail's face at 1, and round I's code had 1.5. pipeline 101's rust series: the rails' mean rusted run 11 cm / 17 cm / 23 cm / 45 cm at rust 0.25 / 0.5 / 0.75 / 1 (R4 asks x1.3 a step until 80 % rusted).
- **B1 (solver)**: the solver's last check also trades accent for film (film x1.2-1.6 with accent x0.93-0.81) when its point fails. Pipelines 99 and 100's Typical failed B1 alone: T5 held 0.85 % of the wall against 1 % (T5+ 1.37 %, T6+ 0.51 %), with T6+ near the solver's A1 limit, so more marks could not add T5 without adding T6. Round J's Typical had more film and less accent (film 0.62, accent 1.34 against 0.44 and 1.55) and T5 at exactly 1.00 %; attributed by layer, the soiling made 43 % of round J's T5 blocks and 32 % of round K's. The fallback moved film or accent alone. Worn's and Derelict's fourth bands (2.1 and 4.9 %) leave their search unchanged. pipeline 101's Typical: B1's bands [0.1889, 0.087, 0.0326, 0.0107, 0.005] (four at 1 % or more), at film 0.71 and accent 1.25.
- **R10**: the face clause binds from rust 0.75, as its text says (the gate had ramped it in from 0.5). Pipeline 99's Derelict (rust 0.614) failed R10 alone, its face 3.2 % rusted against the 4.6 % the ramp asked; the research's table keeps the front face's rust within the drip line's 2 cm row up to about 0.6 (docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.4) .

## Running the gate

```
python -I weather_gate.py check <config_dir> [--json out.json] [--sweep] [--allow-na]
python -I weather_gate.py series presets <dir_new> <dir_kept> <dir_typical> <dir_worn> <dir_neglected>
python -I weather_gate.py series sweep:<layer> <dir_0> <dir_0.25> <dir_0.5> <dir_0.75> <dir_1>
```

A config folder holds one `<plane>.npz` per facade plane in facade space (row 0 at the top, 50 px/m) with `D`, the `L_<layer>` maps, `cls`, `src`, `edge`, optional `Yc`, `labw`/`labc`, the damage chip list (`dmg_y`, `dmg_x`, `dmg_r`, `dmg_d`), and a `meta.json` with the config (preset, age, upkeep, E, amounts) and each plane's frame (ppm, orient, kind, ground and top rows, storey rows, bay columns and kinds). Exit code 0 only when accepted. `--sweep` judges one step of a control sweep: the amount budgets A0, A1 and B1 are set by the control there, so they are not applied.
