# Weathering rules

Numeric rules for building weathering, checked by `scripts/weathering/weather_gate.py`. A weathered building is accepted only when every binding rule passes; nothing is shown before that. Version: 1.6 (round I).

Numeric rules for building weathering, measured in facade space (metres) on a darkening map D = 1 - Y_weathered / Y_clean. A configuration is accepted only when every binding rule passes. Origins: U = the user's review notes (review 36), P = measured on the reference photos, L = building physics and the soiling literature, C = craft estimate (to recalibrate with picks).

## Measures

- **D**: darkening of albedo luminance against the same surface with no weathering: 0 clean, 0.10 = 10 % darker, negative = lighter
- **D_local**: the weathering's own local contrast: D_local = 1 - (1 - D) / ref, ref = the least weathered 10 cm patch within +-1 m (smoothed), on 4 cm block means. A uniform darkening of a whole wall gives 0 (it reads as a paint colour, not as weathering: the user, review 36); paint tones that differ from element to element do not count either. T1 is below photo noise and material texture, so the amount rules start at T2. Arris rows and the edge layer's pixels are left out (the edge rules N1-N5 measure them).
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
- Origin: U (round F: the grime reads as a grid); roundG/research/grid-breakup.md 5.1-5.2 (tile-free controls 4.0-7.9; round F's soiling 12.8 from the 3.6 m material tile; measured here 13.5-26 on round F's fronts)


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
- Origin: U (round F: derelict at 1.0); L (roundG/research/cracks-edges-damage.md S1: 3.7-9.9 % at 75 years unmaintained); round F reached 0.54 % at 1.0

**K6. Spalls start at edges**

- Measure: spalls 30 mm across or more: share within 150 mm of an arris
- Pass: >= 50 %
- Origin: L (roundG/research/cracks-edges-damage.md S5: corners, slab noses, sills, parapet tops)

**K7. Cracks from hairline to pattern cracks**

- Measure: crack length per m2 of wall (width >= 0.05 mm), of cracks >= 0.3 mm, and the median width, pooled over exposed walls
- Pass: length 0.2-0.6 / 0.5-1.2 / 1.0-2.0 / 1.5-3.5 m per m2 at 0.25 / 0.5 / 0.75 / 1.0; >= 0.3 mm 0.03-0.15 / 0.15-0.4 / 0.3-0.8 / 0.6-1.5; median 0.1-0.2 mm at 0.25 to 0.3-0.6 mm at 1.0 (linear between)
- Origin: U (round F: 'cracks from hairline to pattern cracks'); L (roundG/research/cracks-edges-damage.md C1, C2, C4); round F had about 0 m per m2 (no opening corners reached the crack layer)

**K8. Cracks run mostly vertical**

- Measure: length-weighted crack orientation, pattern cracks left out
- Pass: vertical 40-65 %, diagonal 20-40 %, horizontal 10-25 %
- Origin: L (roundG/research/cracks-edges-damage.md C7)

**K9. Diagonal cracks start at opening corners**

- Measure: share of diagonal crack length within one opening width of an opening corner
- Pass: >= 70 %
- Origin: L (roundG/research/cracks-edges-damage.md C8: 45 deg cracks from window corners)

**K10. Cracks read through what they carry**

- Measure: median delta L* of the 1 px crack line against the wall around it, by width class (repaired cracks left out)
- Pass: hairline (< 0.2 mm) <= 3; 0.2-0.5 mm 3-8; 0.5-1 mm 5-10; >= 1 mm 8-20
- Origin: L (roundG/research/cracks-edges-damage.md C19 and 3.1: at 20 mm/px a crack shows through its halo, not its opening)

**K11. Repaired cracks**

- Measure: share of the length of cracks >= 0.3 mm under a repair stripe
- Pass: 50-90 % at 0.25, 30-60 % at 0.5, 20-50 % at 0.75, 10-40 % at 1.0
- Origin: L (roundG/research/cracks-edges-damage.md C23: U-cut and injected repairs on repainted danchi)


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
- Origin: U (round F: 'weaker growth should have a lighter green or very dull or rusty yellow look'); U (round H: the continuum starts at dark yellow, so the green and yellow family clauses of round G are dropped); L (roundG/research/organic-growth.md O1)

**M2. Severe growth is dark green or rust brown**

- Measure: the darkest growth (growth's own darkening >= 0.55, N, E and W walls; south walls grow moulds, O8): black share (C* < 8); of the rest, C* 10-26, hue 95-135 deg (green) or 40-75 deg (rust), and the darkest quarter's L*; from 2000 pixels
- Pass: black <= 35 %; chroma band >= 75 %; hue band >= 75 %; 25th percentile of L* <= 50
- Origin: U (round F: 'the visibly dark green/rust brown look that severe growth has'); L (roundG/research/organic-growth.md O2)

**M3. Growth sits where water stays**

- Measure: pooled over exposed walls: share of growth (T2+) in damp and wet zones (W2-W3, wetness >= 0.40); the cover of W2-W3 and of the open wall (W0-W1); the share in sunny open wall (W0, < 0.15)
- Pass: while growth covers under 5 %: >= 70 % in W2-W3, from E 18 (Derelict) >= 50 %; beyond that, while W2-W3 are under 80 % covered, their cover >= 3x the open wall's; W0 <= 10 %
- Origin: U (round F: corners, divots, edges, below ledges); L (roundG/research/organic-growth.md O4); U (round I: Derelict growth 'mostly in the same areas' - it spreads past the wet zones)

**M4. Plinth belt**

- Measure: N, E and W walls: mean growth darkening in the bottom 0.3 m over the open wall (wetness < 0.4, not under another ledge or joint) 0.5-1.5 m above the foot; from 2 years of growth
- Pass: >= 3.0
- Origin: L (roundG/research/organic-growth.md O5: belt 5-30 cm, splash zone 30 cm)

**M5. Time unattended adds area grown from the old patches**

- Measure: the growth control's steps: growth area (T2+) ratio, the share of the added darkening on newly covered pixels, the share of old growth kept
- Pass: area x >= 1.25 while W2-W3 are under 85 % covered; new share >= 50 %; kept >= 95 %
- Origin: U (round F: 'algae and mold tend to grow outwards like tendrils or blobs, they don't merely get darker'); L (roundG/research/organic-growth.md O9)

**M6. Ragged fronts, not smooth blobs**

- Measure: growth patches (T2+) of 60 px or more on walls where growth covers 3 % or more: perimeter-area dimension (2 x the slope of log perimeter on log area)
- Pass: 1.10-1.45
- Origin: U ('tendrils or blobs'); L (roundG/research/organic-growth.md O12; box counting misread sparse patches, so the perimeter-area form)

**M7. Onset by wetness class**

- Measure: growth (T2+) cover of each wetness class's area at the build's years unattended (3.1, 5.7, 10, 22 years at growth amounts 0.25-1.0, log-linear between)
- Pass: W3 >= 15 % from 1 year and >= 50 % from 3; W2 >= 10 % from 3 years and >= 30 % from 8; W1 >= 3 % from 8 years; W0 <= 5 % up to 15 years; no class over its ceiling (W0 0.30, W1 0.60, W2 0.90, W3 0.95) + 0.03
- Origin: L (roundG/research/organic-growth.md O11 and 3.3: onset, time scale and ceiling per class from field timings)

**M8. Fronts grow outward**

- Measure: the growth control's steps: new growth (T2+) within 0.3 m of the previous step's growth (front growth) and farther away (new patches); a step from a wall with no growth yet (under 400 px) has no fronts and is not judged
- Pass: front growth >= 70 %; new patches 5-30 %
- Origin: U ('grow outwards'); L (roundG/research/organic-growth.md O10)

**M9. Growth darkens and thickens with age**

- Measure: the growth control's steps: the pixels that were growth (T2+) at the earlier step, at the later step
- Pass: their L* down by 1.0 or more and their growth darkening up by 0.02 or more per step
- Origin: U (round G: 'mold and mildew darken/intensify with age'; round F: 'dark green/rust brown' when severe); L (roundG/research/organic-growth.md O2)


### Edges

**N1. Edges show at 0.25**

- Measure: the edge layer's mean |delta L*| on the 1 px edge row (painted wall)
- Pass: 3-6 at 0.25, 4-8 at 0.5, 6-11 at 0.75, 7-14 at 1.0
- Origin: U (round F: edge wear and discoloration visible at 0.25); L (roundG/research/cracks-edges-damage.md E9 and 5.5: at 20 mm/px visibility comes from the edge row, not a bevel)

**N2. The edge band is broken at 0.25, near continuous at 1.0**

- Measure: share of edge length with the edge layer's |delta L*| >= 2
- Pass: 40-70 % at 0.25 to 85-100 % at 1.0 (linear between)
- Origin: L (roundG/research/cracks-edges-damage.md E8)

**N3. Visible chips**

- Measure: chips 20 mm across or more per m of edge
- Pass: 0.04-0.15 at 0.25 to 0.5-1.5 at 1.0 (linear between)
- Origin: L (roundG/research/cracks-edges-damage.md E6)

**N4. Chips cluster**

- Measure: chip counts in 0.5 m windows along the edges: variance over mean (20 chips or more)
- Pass: >= 1.2
- Origin: L (roundG/research/cracks-edges-damage.md E5)

**N5. Tops lighter, drip edges darker and warmer**

- Measure: the edge layer's mean delta L* on top edges and on drip and lower edges; the b* shift on the drip edges
- Pass: tops lighter (> 0); drip edges darker (< 0) with b* +1 to +4
- Origin: L (roundG/research/cracks-edges-damage.md E9: tops chalked and rain-washed; drip edges dirt)


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

- Measure: rusted steel (colour difference 8 or more against clean, as R1) by part of the steel's geometry: post feet (the lowest 0.1 m of posts standing on paint), joints (uprights within 0.04 m of a rail), rails, uprights within 0.3 m below a rail, and the other upright faces; flat steel panels (doors, pipe-shaft doors: the steel fills 75 % or more of a 0.2 m window) are not railing steel: the rust on them, by where it sits in each panel
- Pass: from rust 0.25: feet rusted >= 50 % (>= 80 % from 0.5); the rails' rusted share >= 3x the other faces'; the other faces hold <= 10 % of all rust up to 0.75 and <= 25 % at 1.0; on panels (200 rusted pixels or more), 60 % or more of the rust in each panel's bottom quarter
- Origin: U (round H: 'Rust would probably build along the top, drip down a little, gather along the bottom railing, and then drip down the vertical columns ... I wouldn't just expect the rust to grow radially around the existing rust between steps, but ... grow along the surfaces most affected by water and following the water's flow'); L (research weathering-rust-water §1: feet and pockets first, then joints and welds where 50-90 % of attacks start (Knudsen 2023), the top rail's face (horizontal steel corrodes 2-3x faster, BRANZ), the bottom rail, upright faces last)

**R4. Rust grows along the flow**

- Measure: the rust control's steps: the new rusted steel at each step that continues earlier rust along its member (0.3 m along a rail, 0.5 m down or 0.05 m up an upright) or starts at a foot or joint; new rust creeping more than 0.05 m above earlier rust on an upright; the mean length of the rusted rail segments
- Pass: per step: >= 70 % continues or starts at a foot or joint; <= 10 % creeps up; the mean rusted rail segment x1.3 or more until the rails are 80 % rusted
- Origin: U (round H: 'Rust would probably build along the top, drip down a little, gather along the bottom railing, and then drip down the vertical columns ... I wouldn't just expect the rust to grow radially around the existing rust between steps, but ... grow along the surfaces most affected by water and following the water's flow'); M (research §2: paint creep is 0.1-3.5 mm a year, under a pixel, so growth is new sites on the same wet lines and longer segments, not rings)

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

## Running the gate

```
python -I weather_gate.py check <config_dir> [--json out.json] [--sweep] [--allow-na]
python -I weather_gate.py series presets <dir_new> <dir_kept> <dir_typical> <dir_worn> <dir_neglected>
python -I weather_gate.py series sweep:<layer> <dir_0> <dir_0.25> <dir_0.5> <dir_0.75> <dir_1>
```

A config folder holds one `<plane>.npz` per facade plane in facade space (row 0 at the top, 50 px/m) with `D`, the `L_<layer>` maps, `cls`, `src`, `edge`, optional `Yc`, `labw`/`labc`, the damage chip list (`dmg_y`, `dmg_x`, `dmg_r`, `dmg_d`), and a `meta.json` with the config (preset, age, upkeep, E, amounts) and each plane's frame (ppm, orient, kind, ground and top rows, storey rows, bay columns and kinds). Exit code 0 only when accepted. `--sweep` judges one step of a control sweep: the amount budgets A0, A1 and B1 are set by the control there, so they are not applied.
