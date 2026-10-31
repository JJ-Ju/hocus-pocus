# Organic growth on danchi facades: research note for the weathering generator (round G)

Date: 2026-10-30. Scope: algae, cyanobacteria, moulds, lichens and mosses on repainted spray-tile coat over RC and on bare formed concrete (plinths, stair cores), in humid temperate Japan. The output is albedo, height and roughness maps in facade space at 50 px/m (1 px = 2 cm), baked for Unreal and Godot.

What prompted it (AD review, their words): severe growth should have a "dark green/rust brown look", weak growth "a lighter green or very dull or rusty yellow look". Growth collects in corners, divots, edges and below ledges. Strength should mean time unattended, and growth spreads "like tendrils or blobs" instead of only getting darker.

## Conventions

- **[S n]**: a source states it. n is the link number in §8, and I read the page or PDF text myself.
- **[S/2 n]**: secondary. A forum, blog, trade page, or something I saw only as a search snippet or abstract summary.
- **[I]**: my inference or estimate.
- **[I-m]**: something I measured this session on synthetic numpy masks on this machine. These are not photo measurements.
- Rulebook vocabulary follows `scripts/weathering/weather_rules.json` 1.2:
  - D: darkening of albedo luminance against clean.
  - T1–T6: tiers at D = 0.02 / 0.05 / 0.10 / 0.18 / 0.30 / 0.45.
  - S1–S8: scale levels, where S8 = 12.5–25 cm.
  - E: the soiling clock.
  - Rule origins: U = user, P = photos, L = literature, C = craft estimate.
- **t_bio** means years since growth was last reset (see §3.6). This is the "time unattended" the AD asks for.
- Search budget: the web-search budget, shared across agents, ran out near the end. A few planned searches did not run: multi-year roof weathering (Gladis & Schumann), the bioreceptivity review (Miller), and field patch-coverage series. §7 lists what is missing.

---

## 0. Summary

1. **Colour depends on the growth's age at each pixel, not on the global amount.**
   - Early greening shows first as a *yellowing* (b* up), then greening (a* down), then darkening (L* down). On a granite facade the threshold of visibility was Δb* +0.59, Δa* −0.41, or ΔL* −4.37 [S 1].
   - Established greening on damp, shaded run-off areas averaged ΔL* −6.1, Δa* −3.4, Δb* +9.8 [S 1].
   - Per 0.1 of D that is about **Δb* +4.4 to +5.5 and Δa* −1.5 to −1.9** [I, computed from S 1]. Dirt shifts colour by only −0.3 to +0.8 b* per 0.1 D (rule I1, P), so young growth sits about 6× further toward yellow-green than dirt does.
   - Severe growth is dark and moderately chromatic. Dark green or olive comes from algae, cyanobacteria and dirt. Dark red to rust-brown comes from *Trentepohlia*, which grows mainly on concrete [S 2, S 13]. Grey-black "ink stripes" (*Tintenstriche*) form under broken gutters and downpipes [S 2].
2. **Growth is nucleation plus outward growth plus merging (Avrami kinetics).**
   - Lab coverage follows a sigmoid X = 1 − exp(−k(t − t_l)^4): spots appear at a rising rate, grow radially at a constant rate, then merge [S 3].
   - Lab numbers: latency 4.6 days, radial growth ≈178 µm/day, more than 50% cover after about 16 days, under twice-daily spraying [S 3].
   - In the field, growth on damp, shaded run-off zones began after 80–129 days and became visible at about 178 days [S 1]. The same paper cites about 1 year to first greening on porous concrete and 2–5 years to intense greening [S 1]. New ETICS facades showed green-to-red stains 1–4 years after renovation, and these grew denser over three years [S 4].
3. **Where it grows is set by how long water stays.**
   - The wall foot and corners carry a 5–15 cm green belt [S 2], inside a 30 cm splash zone [S 11].
   - Broken downpipes and gutters give black stripes and patches [S 2, S 10].
   - North faces are worst, and algae preferred very rough render [S 4, S 5].
   - Gables without windows colonise evenly. Facades with windows colonise mainly between windows, and less directly above and below them because the sill sheds water away [S 4].
   - South faces carry dark moulds rather than green algae [S 5].
4. **Outline and size statistics** (no facade data found; synthetic calibration only):
   - Box-counting dimension over 4 cm–1.28 m: smooth blobs score 0.97–1.02, organic nucleation-and-growth fronts 1.14–1.31 [I-m]. Proposed pass band [1.12, 1.35].
   - Patch areas are heavy-tailed. Synthetic nucleation-and-growth gives a CCDF slope of about −0.46 [I-m]; critical percolation gives −1.05 (τ = 187/91) [S 17]; biocrust patch sizes are often lognormal [S 16]. Proposed slope band [−1.1, −0.4].
5. **Generating it in numpy.**
   - The best fit for cost and look is an arrival-time (first-passage) field from nuclei on a cost map built from wetness, with pixel noise and cheaper downward steps. Growth at time t is {T ≤ t}, so it is nested by construction. Local age t − T drives density and colour.
   - One sweep of four vectorised min-plus scans costs 0.14 s on a 60 × 15 m plane (2.25 Mpx); 12–20 sweeps are needed [I-m].
   - Gray-Scott costs 20 ms per iteration and needs thousands of iterations; it gives one regular wavelength. DLA in numpy is far too slow (2.6 s for a 700 px cluster) and looks too lacy for algae. Keep both for lichen rosettes in close-up atlases [I-m, S 7].
6. **Fifteen proposed rules (O1–O15)** are in §5. They cover colour by severity, wet-zone share, plinth belt, corners/joints/divots, sources, orientation, coverage-not-darkness over time, outward fronts, onset by wetness class, outline roughness, patch sizes, inner gradient/rim/satellites, organism mix, and material maps.

---

## 1. Organisms and how they look

### 1.1 Who grows on these walls

**Green algae.** On 71 French facades the most frequent were *Klebsormidium flaccidum* (55% of samples), *Trebouxia* spp. (49%), *Stichococcus bacillaris* (46%), *Chlorosarcinopsis minor* (28%) and *Chlorella* cf. *mirabilis* (27%) [S 15]. In an Irish city the main groups were [S 2]:
- *Desmococcus olivaceus*: light-green growths.
- Prasiolales (*Rosenvingiella*, *Prasiola*): light to dark green belts at wall feet and corners.
- *Trebouxia*/*Apatococcus*: pale-green powdery layers on bark.

**Trentepohlia** (orange to rust; Japanese スミレモ):
- Its orange-to-red colour comes from very high carotenoid-to-chlorophyll ratios: 15.9 (*T. jolithus*), 7.8 (*T. aurea*), 6.6 (*T. umbrina*). The *T. jolithus* sample came from a harbour concrete wall. The three species tolerated 5–40 °C, with photosynthesis best at 20–35 °C. After desiccation, two recovered fully and *T. aurea* about 50% [S 13].
- In Galway, *T. iolithus* formed dark red growths, mainly on concrete walls, painted or not, at any height and orientation [S 2]. *T. umbrina* formed brownish-red growths 1–2 m up on north-facing limestone [S 2].
- In Japan the genus is reported on concrete and limestone, with eight species recorded [S/2 41].

**Cyanobacteria** (grey to black, blue-black, sometimes purple or red):
- The Galway "blue-green assemblage" was grey or black and the most widespread of all, present on every weathered wall at heights from a few cm to many metres, facing all directions [S 2].
- The colour comes from coloured colony sheaths [S 2]:
  - *Gloeocapsa alpina*: purple, most intense on the light-facing side.
  - *G. magma*: golden-brown.
  - *G. chroococcoides*: grey.
  - *G. sanguinea*: red-orange.
- One biofilm-forming *Nostoc* strain could be steered in culture between hue 129° and 147°, yellow-green to blue-green, by light and nutrients. On surfaces, stone cyanobacteria give greenish-yellow, bluish-green or pinkish-orange tints [S 14].
- In France the main ones were *Cyanosarcina* (28%), *Chroococcus* (21%), *Gloeocapsa sanguinea* (15%), *Calothrix* (21%), *Leptolyngbya* (18%) and *Phormidium* (13%) [S 15].

**Moulds and black fungi:**
- They appear as spots or patches that can spread into a furry grey, green, brown or black layer, on paint and where dust collects [S 10].
- On a Swedish test house, moulds (*Cladosporium*) grew mostly on the south side and algae on the north. The authors credit the dark pigment that protects the mould from sun [S 5].
- On Brazilian fibre cement, visible dark spots after 5 years were linked mainly to phototrophs, especially cyanobacteria [S/2 52].

**Lichens:**
- Leathery crusts, usually orange, green, grey or black [S 10]. They often do well on south-facing surfaces in the UK [S 10].
- Crustose lichens grow less than 1 mm a year, fruticose lichens up to 20 mm a year [S 7]. Measured crustose radial rates are 0.44–3.0 mm/yr across several genera and 1.1–2.0 mm/yr in English Midlands sites [S 8].

**Mosses:**
- Green cushions of spiky tufts, brown when dry, found where salts, soil and dirt have collected [S 10].
- *Tortula muralis* forms patches at most about 1 cm tall; *Grimmia* forms round cushions [S/2 27].
- Japanese concrete species include ハマキゴケ (*Hyophila propagulifera*), recorded on the north wall of a 44-year-old concrete building [S/2 46], and ギンゴケ (*Bryum argenteum*), which tolerates sun and drought on roofs and pavement edges [S/2 47].

### 1.2 Look by stage

Colours are estimates [I] anchored on S 1, S 2, S 10, S 13 and S 14. Each stage is described wet / dry.

**Green algae film** (*Klebsormidium*, *Desmococcus*, *Chlorella*, *Stichococcus*):
- Early (months): an even yellow-green to dull-yellow tint with no clear edge. It is a density of mm-size colonies, below pixel size.
- Established (1–5 yr): light-to-mid green patches with dotted edges, green belts at the wall foot, and green lines along joints. Wet: vivid, slimy green [S 10]. Dry: grey-olive or yellow-grey; at times it seems to disappear [S 5].
- Severe (5–20 yr): dark green to olive, mixed with dirt and with cyanobacteria in the wettest cores. Wet: dark, glossy, slimy. Dry: dark olive-brown.

**Trentepohlia:**
- Early: rusty-yellow or orange tint on concrete and shaded humid paint.
- Established: orange-rust to dark red crustose growth [S 2]. Wet: deeper red-brown. Dry: stays orange; the pigment is stable.
- Severe: rust-brown, mixed with green and black.

**Cyanobacteria:**
- Early: grey bloom or speckle.
- Established: grey to black crust; patches and vertical stripes under leaks [S 2]. Wet: blue-black, glossy, slimy. Dry: matte brown-black; purple tint on the sun side [S 2].
- Severe: thick black crusts and ink stripes [S 2].

**Moulds and black fungi:**
- Early: tiny dark specks of 1–3 mm.
- Established: grey-black spots and patches, often on sunnier or more polluted faces [S 5, S 10]. Wet: little change. Dry: the same.
- Severe: dense black speckle fields and furry layers [S 10].

**Lichens:**
- Early (lag years): nothing visible.
- Established: discrete grey-green, orange or black rosettes and crusts of 1–5 cm. Wet: greener, brighter. Dry: greyer; very hard to wet [S 10].
- Severe: overlapping rosettes on copings and bare concrete.

**Mosses:**
- Early: green fuzz in joints and on ledges.
- Established: cushions and carpets of 5–20 mm. Wet: bright green. Dry: olive-brown [S 10]; *Bryum* turns silvery.
- Severe: continuous carpets on ledges and parapet tops, plus wall feet.

### 1.3 Colour anchors

All values are [I] estimates, built from:
- the Sanmartín shifts [S 1];
- the descriptions in S 2, S 10, S 13 and S 14;
- a light warm-grey spray-tile paint, taken as clean, at L* 80, a* 1, b* 7.

D is luminance darkening against that paint. sRGB values assume D65 and were computed this session.

| Anchor | L* | a* | b* | C* | h° | sRGB hex | D vs paint |
|---|---|---|---|---|---|---|---|
| Clean spray-tile paint (reference) | 80 | 1 | 7 | 7 | 82 | #CEC5B9 | 0.00 |
| Bare formed concrete (reference) | 62 | 0.5 | 4 | 4 | 83 | #9A958F | 0.46 |
| G1 first greening, just visible | 77 | −1.5 | 11 | 11 | 98 | #C4BEAA | 0.09 |
| G2 young light-green film | 72 | −5 | 16 | 17 | 107 | #B3B293 | 0.23 |
| G2y dull or rusty-yellow young growth | 71 | 2 | 19 | 19 | 84 | #BFAB8B | 0.26 |
| G3 established green, damp | 60 | −9 | 20 | 22 | 114 | #8E946D | 0.50 |
| G4 severe dark green / olive | 42 | −7 | 15 | 17 | 115 | #61664A | 0.78 |
| G4r severe rust-brown (*Trentepohlia* + dirt) | 40 | 10 | 17 | 20 | 60 | #775843 | 0.80 |
| Tr fresh *Trentepohlia* orange-rust on concrete | 52 | 20 | 30 | 36 | 56 | #AA6E49 | 0.64 |
| Cy cyanobacterial ink stripe / crust, dry | 28 | 1 | 3 | 3 | 72 | #46413E | 0.90 |
| Fu black fungal speckle core | 24 | 0 | 2 | 2 | 90 | #3A3936 | 0.93 |
| Mo moss cushion, damp | 42 | −15 | 28 | 32 | 118 | #5A6933 | 0.78 |
| Md moss cushion, dry (olive-brown) | 50 | −1 | 20 | 20 | 93 | #827655 | 0.68 |
| Lg grey-green lichen | 66 | −4 | 9 | 10 | 114 | #A0A290 | 0.38 |
| Lo orange lichen (*Xanthoria*/*Caloplaca* type) | 64 | 20 | 52 | 56 | 69 | #D38C3C | 0.42 |

How to read the table:
- **Light growth is a hue shift.** G1 and G2 carry Δb* about +4 per 0.1 D, which matches S 1. Weak growth reads as tint, not dirt. Its hue sits at 85–110°: dull yellow to yellow-green.
- **Severe growth is a darkening that keeps some chroma.** C* stays at 15–22 for G4 and G4r. This separates "dark green / rust brown" from dirt and from black crust, which has C* < 8.
- **On bare concrete the absolute severe colours stay much the same.** The crusts are opaque. Light growth shows as the same b* and a* shifts, at a lower D, because concrete is darker [I].

Wet versus dry, for a baked map [I]:
- Use an "average humid, overcast" state. Wet algae are about 3–8 L* darker, 20–40% more chromatic and glossier. Dry algae are 3–8 L* lighter, 30–50% less chromatic, and their hue drifts toward 90° (yellow-olive).
- If the engine has a wetness parameter, export a `bio_wet` mask so the shader can darken and smooth bio pixels when it rains.

Seasonality: growth was most visible in spring and especially autumn, and at times disappeared in summer and winter [S 5]. On a Japanese roof, black stripes rose in autumn [S 26]. A baked texture should use the autumn look [I].

### 1.4 Succession

- Biofouling generally starts with phototrophs (algae and cyanobacteria), which condition the surface for heterotrophs [S 1].
- Algae and cyanobacteria make up most of the early-succession diversity: over 200 taxa, with fungi next [S/2 28].
- Activity thresholds: facade algae are active from 68% to 100% RH, fungi from about 73% RH upward [S/2 28]. On a Japanese roof study, algae were assumed to grow at 0–40 °C and to die above 40 °C [S 26].
- Ladder for the generator [I]:
  1. Young yellow-green or rusty-yellow tint (G1, G2y).
  2. Green film and belts (G2, G3).
  3. Dark olive with dirt, plus black cyanobacteria in permanently wet cores (G4, Cy).
  4. *Trentepohlia* rust where the substrate is concrete and the site humid and shaded (Tr, G4r).
  5. Moss on ledges, joints and wall feet, where dirt and soil have collected (Mo, Md).
  6. Lichen dots on copings, bare concrete and sunnier faces after a lag (Lg, Lo).

---

## 2. Where it grows on a building

### 2.1 Evidence

**Wall foot / splash zone:**
- The prasiolalean belt always sat at ground level or no higher than 10–15 cm. A *Rosenvingiella* green belt 5–10 cm high ran several metres along the bases of north-facing concrete walls [S 2].
- *Desmococcus* grew on the basal 20–30 cm of poles and trees, more on their north sides [S 2].
- The facade zone starts 30 cm above ground. The plinth zone spans 30 cm above to 20 cm below ground, and its above-ground part is the splash zone. Continuously damp plinths quickly grow algae and fungi [S 11].
- A missing skirting at a small roof made rain splash onto the facade and rise higher, which caused strong local growth [S 4].

**Inside corners:**
- The Prasiolales belt grew at the bases of many walls *and corners* in humid places [S 2].
- No study gave a corner width. Estimate: a band 10–40 cm wide each side of a re-entrant corner [I].

**Orientation:**
- Growth was mainly on north sides, which dry least in the sun [S 4]. Algae grew mostly north and moulds south [S 5].
- Fraunhofer's experience: north and west facades are most affected, especially with trees nearby [S 12].
- On ETICS blocks 1–6 years old, growth was mostly north, sometimes west, and worse with greenery within 10 m [S/2 32]. Northern facades in Granada showed discolouration and lichen and mould [S/2 33].
- Caution: the Galician study plots faced south but were shaded by neighbouring buildings and kept damp by run-off, and they still greened within 6 months [S 1]. Shade and wetness matter more than the compass label [I].

**Run-off paths and streaks:**
- Damp from run-off was the setting for the fastest greening [S 1]. Where gutters and downpipes were broken, thick black crusts formed as patches or irregular vertical stripes (*Tintenstriche*) [S 2].
- On rock, ink-stripe communities sit where surface water flows again and again [S/2 42]. Localised algal growth can point to leaking pipes or gutters [S 10].

**Windows and sills:**
- With windows, growth sat mostly *between* windows and less or not at all directly above and below them. The sill sheds the water, and the run between window rows is shorter [S 4].
- A patent describes areas below sills with long dripping as problem spots, and calls the stains uneven streaks and blotches on uneven substrates [S/2 35].
- So: under a sill with a working drip there is little growth; at sill ends and failed drips there is a lot [I].

**Gable walls without openings:**
- Colonised evenly over the whole surface; such walls catch rain, spores and dust [S 4].

**Rough or porous patches:**
- Coarse-grained, sharp-grained render strongly favours growth [S 4]. Algae preferred very rough surfaces; moulds also grew on smoother ones [S 5].
- In accelerated tests, roughness and pH mattered and porosity mattered less [S/2 39]. Algal growth rose with the porosity of the mortar [S/2 40].
- Water uptake above 1 kg/m² in 24 h favoured growth even with biocide [S/2 49].

**Joints:**
- No measurement found. Joints stay wet, so expect lines 1–3 cm wide along them, and the upper lip of horizontal joints wetter [I].

**Thermal effects:**
- Fastener heads on insulated render stayed free of growth ("white dots"). They are 1–2 K warmer at night, giving about 11% lower surface RH [S 6].
- Red facades ran about 20% RH drier than white ones [S 6].
- On RC danchi walls, warmer slab edges and columns in winter may ghost the structure faintly [I].

**Downpipes and AC condensate:**
- Downpipes: see run-off above [S 2]. A household AC sheds about 0.5–2 L of condensate per hour in cooling [S/2 31].
- On danchi the condensate usually reaches balcony floors and leaves through scuppers or drain pipes. Expect a permanently wet line below each outlet in summer [I].

**Parapet tops, copings, ledges:**
- Mosses need collected soil and dirt [S 10]. Lichens sit on accessible surfaces sheltered from wind gusts and rain flow [S 7] and do well on south faces [S 10].
- *Bryum argenteum* tolerates sun and drought on roofs [S/2 47].

**Neighbouring buildings:**
- High wind-driven-rain exposure makes facades more prone to algae [S/2 50]. Shade from neighbours keeps walls damp [S 1, S 4].

**Share of facade affected:**
- No survey gives area shares by age. The usable scale is the mould index for stone-based materials: 1 some growth, 2 over 10%, 3 over 50%, 4 over 50% but under 100%, 5 full coverage [S 9]. ASTM D3274 rates disfigurement against non-linear photo references [S/2 51].

### 2.2 Wetness classes for a danchi facade

All values are [I], built from §2.1.

**W3 wet** (wet most of the rainy season):
- Where:
  - splash band 0–0.3 m above ground, densest in 0–0.15 m;
  - 0–1.5 m below leaking downpipe joints, balcony scupper outlets and AC drain lines;
  - sill ends without drips;
  - the bottoms of inside corners;
  - under broken copings.
- Share of a plane: 2–6%.
- Growth types: green belts, black ink stripes, *Trentepohlia* on concrete.

**W2 damp** (wet for days after rain, slow to dry):
- Where:
  - run-off paths under tops and slab-edge fronts;
  - 0.3–1.0 m above the splash band;
  - re-entrant corners, 0.1–0.4 m each side;
  - horizontal and vertical joints;
  - chips, spalls and rough repairs;
  - north and east faces under balcony soffit edges without drips;
  - open stair cores.
- Share of a plane: 8–20%.
- Growth types: green-to-olive patches and fingers, moss in joints.

**W1 shaded open wall** (N/E/W faces, or any face shaded by neighbours):
- Where: the rest of the plane.
- Share of a plane: 60–85% of N/E/W planes.
- Growth types: sparse speckle and patches after years, interfenestral bands.

**W0 sunny open wall** (S faces, unshaded):
- Where: the rest of the plane.
- Share: most of S planes.
- Growth types: dark mould speckle, lichen dots on bare concrete; little green.

Sheltered zones, directly under sills or slabs that have working drips, sit below their neighbours and the generator should keep them low [S 4]. Copings and ledge tops are horizontal; they show in elevation only as their outer edge, with moss and lichen and run-off below.

---

## 3. How it grows over time

### 3.1 Nucleation, growth and merging: lab data

Set-up of the lab study [S 3]:
- Render on cement, carbonated to pH ≈ 9, Ra = 150 µm.
- Samples inclined at 45°, sprayed with a *K. flaccidum* suspension for 90 min every 12 h, 12 h light.
- Scanned daily at 600 dpi.

Findings [S 3]:
- Coverage followed a sigmoid, modelled with Avrami's law as two processes:
  - attachment of new spots, at a rate rising as a power q of time since latency, taken as q = 1;
  - 2D growth of each spot at a constant radial rate.
- So X(t) = 1 − exp(−2 k_g k_c² (t − t_l)^(q+3) / ((q+1)(q+2)(q+3))), with exponent 4 for q = 1.
- Fitted values: t_l = 4.63 days, k_c = 178.1 (µm/day; the "µ" is lost in the PDF text), k_g = 2.55×10⁻⁸ in the printed units.
- After about 16 days coverage passed 50%, and merging made new spots hard to count.

Check [I]: with k_g read as spots per µm² per day², the model gives X ≈ 0.68 at day 16 and a mean nucleus spacing below 1 mm. The printed numbers are consistent once read that way.

What this means for the generator [I]:
- Growth has three parts: new spots keep appearing (more over time), each spot spreads outward at a fairly constant rate, and spots merge.
- Darkness inside a merged patch comes from age and density, not from a global opacity.

### 3.2 Field timings

- **Damp, shaded run-off zones on a granite facade (mild, wet Galicia):** after brushing clean, recolonisation started at 80–129 days and was visible at about 178 days [S 1].
- **Porous concrete walls:** about 1 year to first visible greening, 2–5 years to intense greening [S 1, citing Escadeillas 2007].
- **New ETICS, north faces (Ostrava):** green-to-red stains 1–4 years after renovation, denser and wider between 2013 and 2016 [S 4].
- **Swedish rendered facades:** discolouration a few years after construction [S 5].
- **Japanese cold-region roof:** black algal stripes 4 months after cleaning on the north-east side, mostly on NE and NW, rising in autumn [S 26].
- **Biocide coatings:** none of 33 render, paint and biocide combinations protected for more than five years in a Fraunhofer weathering test. Biocides leach out over time [S 12].
- **Repaint cycle:** a Japanese long-term repair model gives 12–15 years for exterior wall repainting [S/2 29]. The rulebook clock uses lerp(24, 7, upkeep) years.
- **Climate:** Tokyo gets about 1,598 mm of rain a year (1991–2020) [S/2 30], comparable to Galicia. The Galician timings are a reasonable anchor for Japanese north and shaded faces [I].

### 3.3 Proposed coverage curves by wetness class

All values are [I], calibrated to §3.2 and to be replaced by photo picks.

Use X(t_bio) = X_max · (1 − exp(−((t_bio − t_l)/τ)^n)) for t_bio > t_l, with n = 2. The lab's n = 4 assumes a nucleation rate rising from zero. In the field, spores are everywhere from the start and growth is intermittent, which is closer to site saturation, n = 2 in 2D [I].

| Class | t_l (yr) | τ (yr) | X_max | X at 1 yr | 3 yr | 8 yr | 15 yr | 25 yr |
|---|---|---|---|---|---|---|---|---|
| W3 wet | 0.3 | 1.5 | 0.95 | 0.19 | 0.91 | 0.95 | 0.95 | 0.95 |
| W2 damp | 1.0 | 5 | 0.90 | 0 | 0.13 | 0.77 | 0.90 | 0.90 |
| W1 shaded open | 3 | 15 | 0.60 | 0 | 0 | 0.06 | 0.28 | 0.53 |
| W0 sunny open | 6 | 40 | 0.30 | 0 | 0 | 0.001 | 0.015 | 0.06 |

X is the T2+ coverage of that class's area.

Bio clock per preset [I]: t_bio = years since repaint − 3 years of biocide. That gives about 6.6 (kept), 5.7 (typical), 12.5 (worn) and 19 (neglected) years, from the rulebook's cycle formula.

Whole-plane bio T2+ on N faces then comes to roughly:
- kept and typical: 5–15%;
- worn: 15–35%;
- neglected: 30–60%.

S faces come to about a quarter of that [C].

### 3.4 Shape: fronts, fingers, satellites, edges, inner gradient

**Where it starts:**
- In pores, rough grains and water tracks [S 4, S 5].
- On spray-tile coat, colonies begin in the low points of the texture relief, so close-ups should correlate bio density with cavity [I].

**Fronts:**
- Lab spots grow radially and merge [S 3].
- At facade scale (2 cm/px), estimated front speeds [I]:
  - W3: 10–30 cm/yr;
  - W2: 3–10 cm/yr;
  - W1: 1–3 cm/yr;
  - W0: under 1 cm/yr.
- No field radial rate for algal patches was found (§7).

**Fingers and tendrils:**
- Water films and rivulets carry cells and keep paths wet, so growth runs faster downward and along joints.
- Run-off-fed patches are vertical, 3–20 cm wide and 0.3–3 m long. Plinth belts are horizontal, with upward fingers at splash points and corners [I].
- On rock, ink stripes follow repeated surface flow [S/2 42].

**Satellites:**
- Nucleation never stops [S 3], so dotted fringes of small colonies surround big patches [I].
- The current bio layer already stamps 1–12 cm dots at margins. That is right in spirit, but the dots should be nuclei that later grow and merge [I].

**Edges:**
- No measurement found. Estimates [I]:
  - algae films: 10–90% ramp of 2–10 cm, plus speckle;
  - cyanobacterial crusts, lichens and moss: crisp, 1–2 cm or less at 50 px/m;
  - moulds: spotty.

**Inner gradient:**
- Older parts are denser and darker; edges are young and lighter [I, from S 1 and S 3].
- Under sources, the wettest core is darkest: often at the drip point and where water pools at the bottom [I].

### 3.5 Patch-size distributions and outline dimension

**Facade data:** none found.

**Analogues:**
- Critical 2D percolation: cluster sizes n_s ∝ s^(−τ) with τ = 187/91 ≈ 2.055, so the CCDF slope is ≈ −1.05. Cluster dimension is 91/48 [S 17]. Hull dimension is 7/4 and the accessible perimeter 4/3 [S/2 37].
- Dryland vegetation patch sizes were reported as power laws, truncated under stress [S/2 38].
- Biocrust patches (mosses and lichens) were lognormal in 53% of cases and power law in 39% [S 16]. Aggregation plus mortality gives a power law with an exponential cut-off [S/2 44].
- Lichens returned to heavy-tailed patch sizes late in succession [S/2 45].

**Growth-model references:**
- 2D DLA: D ≈ 1.71 [S 18]. Bacterial colonies under nutrient-poor, hard-agar conditions: D = 1.73 ± 0.02. Colonies can also grow compact Eden-like, branched or ring-like, depending on nutrient and agar [S/2 36].
- Eden growth: clusters grow by random accumulation on the boundary and form a surface fractal [S 20]. Its front is in the KPZ class: α = 1/2, β = 1/3 [S 19].

**Synthetic calibration [I-m]:** 1024² masks at 15% cover. D_box is the slope of boundary boxes over box sizes 2–64 px (4 cm–1.28 m).

| Mask | D_box |
|---|---|
| Blurred-noise blobs | 0.97 |
| Thresholded fBm, H = 0.9 | 1.08 |
| Thresholded fBm, H = 0.7 | 1.19 |
| Thresholded fBm, H = 0.5 | 1.31 |
| Eden, uniform | 1.14 |
| Eden, on lognormal susceptibility | 1.16 |
| First passage, smooth cost | 0.98–1.02 (needs pixel noise) |
| First passage, cost with i.i.d. noise | 1.22 |
| Nucleation-and-growth, 5% cover | 1.04 |
| Nucleation-and-growth, 15% cover | 1.17 |
| Nucleation-and-growth, 30% cover | 1.23 |
| Nucleation-and-growth, 50% cover | 1.29 |

The same nucleation-and-growth run gave a patch-area CCDF slope of −0.45 to −0.47 (≥ 4 px). Its largest/median patch ratio rose from 100 at 5% cover to 7,000 at 50%.

### 3.6 What resets growth

- **Washing or brushing with water:** short reset only. Visible greening returned in about 6 months on damp sites [S 1].
- **Biocide washes:** kill growth, but the black pigment of fungi can stay as a stain [S/2 53]. Dead dark crusts ghost until scrubbed or painted over [I].
- **Repaint with biocidal coat:** full reset of growth. Protection lasts at most about 5 years [S 12], then regrowth follows the class curves.
- **Japanese repaint cycle:** 12–15 years [S/2 29].

Generator rule of thumb [I]:
- t_bio = max(0, years_since_repaint − 3).
- Upkeep washing removes young growth (local age under about 1 year) but leaves crust stains at 30–60% strength.

### 3.7 Lichens and mosses: timescales

**Lichens:**
- There is a lag phase before colonisation [S 8]. Radial rates are 0.5–3 mm/yr in temperate Europe [S 8], under 1 mm/yr for most crustose species [S 7]. A foliose lichen grew faster at moister sites [S/2 57].
- After 20 years unattended, rosettes are 2–12 cm across [I, from those rates]. At 50 px/m that is 1–6 px dots, so lichen is mainly close-up detail.

**Mosses:**
- Natural colonisation of concrete takes years. On north and south concrete, *T. muralis* kept the most cover, but as thin carpets [S/2 27].
- Indoor carpets reached 15–16 mm thick and over 50% cover in 12 weeks, but only with daily watering [S/2 27].
- Estimate [I]: visible moss in joints and on ledges after 8–15 years unattended, with cushions 5–20 mm high.

---

## 4. Procedural generation

### 4.1 Methods others use

**Dorsey, Pedersen & Hanrahan 1996, "Flow and changes in appearance":**
- Water as particles ("drops") moved by gravity, friction, wind and roughness, with coupled absorption, dissolution and sedimentation, producing washes and stains on complex geometry [S 23].
- Look: streaks, washes, deposits.
- Cost: particle simulation on meshes.
- For us: the flow logic is the basis of the existing streak, flow and G1 sources. Use it to build the run-off wetness map.

**Desbenoit, Galin & Akkouche 2004, lichen growth:**
- Spores seeded by accessibility or painting. An Open DLA is constrained by environment maps E = min(indirect light, direct light, moisture) and an aggregation probability that depends on neighbour count. Clusters stop at each other and at unfavourable zones. Geometry comes from instancing an atlas of lichen models by age [S 7].
- Look: dendritic to compact rosettes, competing patches.
- Cost: 54–2,400 particles took 1–483 s on 2004 hardware [S 7].
- For us: good for lichen stamp atlases in close-ups. Too slow and too lacy for facade-scale algae.

**Chen et al. 2005, γ-ton tracing:**
- Aging particles traced like photons; the recorded transport drives texture and geometry changes, such as stain bleeding [S 24]. A conference wrap-up says it suits stains and moss growth that flow out from a source [S/2 56].
- Look: source-driven stains.
- Cost: ray-traced.
- For us: same idea as source halos.

**Kider, Raja & Badler 2011, fruit decay:**
- Reaction-diffusion growth patterns of fungus and bacteria, limited by nutrients [S/2 43].
- Look: spreading infection rings.
- Cost: RD iterations.
- For us: the concept fits, but RD has a fixed wavelength.

**Eden or stochastic dilation:**
- Material accumulates at random on the boundary [S 20]. Rough-edged blobs, D_box ≈ 1.14–1.16 [I-m].
- Cost: 8 ms per step on 2.25 Mpx [I-m].
- For us: good for roughening fronts.

**DLA:**
- Random walkers stick on contact [S 18].
- Look: lace, D ≈ 1.71.
- Cost: parallel numpy DLA on 512² took 2.6 s for a 694 px cluster [I-m].
- For us: lichen atlas only.

**Reaction-diffusion (Gray-Scott):**
- Look: spots, stripes and labyrinths at one wavelength [I].
- Cost: 20 ms per iteration on 2.25 Mpx, thousands needed [I-m]. Houdini 22 Copernicus has a two-chemical RD block. It is resolution-sensitive: doubling resolution needs about 4× the substeps [S 21].
- For us: lichen areolae and moss cushion textures at close-up scale, not the macro layout.

**Thresholded noise (percolation-like):**
- Look: outline D ≈ 2 − H for fBm; nested in time if the threshold falls monotonically [I-m].
- Cost: one FFT octave is 87 ms [I-m].
- For us: cheap, but fronts do not grow *from* sources; wetness must be built into the field.

**First passage / arrival time (fast sweeping):**
- Arrival time T from nuclei over cost 1/speed. Growth at t is {T ≤ t}, nested; local age is t − T [I].
- Look: fronts that advance from seeds and sources, fingers along cheap paths. D_box ≈ 1.22 with pixel noise [I-m].
- Cost: 0.14 s per four-direction sweep on 2.25 Mpx; 12–20 sweeps [I-m].
- For us: **recommended macro driver.**

**Substance Painter Dirt / Mask Editor:**
- Built from baked position, curvature, AO and world-space normal; dirt goes to crevices and edges, with grunge variation [S 22]. Slope Blur adds organic edge detail [S/2 55].
- Look: cavity- and edge-driven masks.
- For us: same as our wetness inputs; it does not model time.

**Houdini growth and infection solvers:**
- Solver SOP spread masks that grow from seeds with noise and an immunity attribute [S/2 54].
- Look: fronts on meshes.
- For us: equivalent to arrival time on points.

### 4.2 Recommended numpy pipeline per plane

All design choices here are [I]; costs are measured [I-m].

1. **Wetness W and class map** from fields the generator already has. Rough guide:

   W = max(
   - splash = exp(−h/0.12 m) on N/E/W, half that on S;
   - run-off below sources (from G1 sources, decaying over 0.3–1.5 m down-slope, cut at working drips);
   - corner_prox × 0.8;
   - joints × 0.7;
   - chips × 0.6;
   - shelter × 0.3 × north )

   × orientation (N 1.0, E 0.7, W 0.6, S 0.3).

   Threshold this into W0–W3.
2. **Nuclei:**
   - Poisson density ∝ W² × (1 + cavity) × roughness.
   - Birth times b = t_max·√u, so the nucleation rate rises with t, as in [S 3].
   - Add extra satellite nuclei 0.1–0.3 m outside every front.
3. **Arrival time T:**
   - Fast-sweeping min-plus scans from nuclei (T = b), with cost c = exp(σ_g·g + σ_w·ξ) / v(W). Here g is a correlated field, ξ is i.i.d. pixel noise with σ_w ≈ 0.8–1.0, and v comes from the class speeds in §3.4.
   - Step costs: downward × 0.4, upward × 2, along joints × 0.5.
   - About 2–3 s per plane [I-m].
4. **Local age** A = max(0, t_bio − T). Then:
   - density ρ = 1 − exp(−A/τ_ρ);
   - stage colour from the §1.3 ladder, by A, W, substrate and orientation;
   - compose in linear RGB: paint·(1 − αρ) + organism·αρ.

   Young pixels get G1/G2/G2y. Pixels older than 3–8 years get G3, then G4 or G4r. W3 pixels under leaks get Cy. S faces get Fu speckle instead of green.
5. **Speckle:**
   - At small A, multiply ρ by thresholded 1–3 px noise, giving colonies and satellites.
   - Optionally add 20–50 Eden steps of 8 ms each for front roughness.
6. **Subtypes:**
   - Moss: on ledge-top, joint, plinth-top and coping-edge pixels after A > 8 years.
   - Lichen: dots on copings and bare concrete after A > 6–10 years, sized from 0.5–3 mm/yr radial growth.
   - *Trentepohlia*: on concrete, or shaded humid paint, after A > 3 years.
7. **Height and roughness maps:** see O15.

### 4.3 The current bio layer against these findings

Source: `weather_fields.py` `layer_bio`, read only. Lab values were computed this session [I].

- **Colours are too dark for light growth, with no yellow or rust family.**
  - Core "bio" is L* 24.8, a* −7.7, b* 8.0 (h 134°).
  - Margin "bio_algae" is L* 35.8, a* −10.2, b* 16.3 (h 122°).
  - Thin growth therefore reads as a transparent dark-olive veil, not the G1/G2/G2y tints.
- **Coverage expands, but each step also darkens.** Coverage is a quantile of a static damp × lognormal field (share q grows with amount), but α ∝ amount^0.6 makes every step darker too.
- **Patches have soft edges and no front.** The smoothstep threshold gives soft edges, and fronts never advance from sources or nuclei.
- **Not yet measured.** O1, O9 and O12 have not been run on the current layer; running them would confirm or reject the above.

---

## 5. Proposed rules (O series)

Format: measure / pass band / origin, in rulebook vocabulary, with evidence tags.

"Bio pixels" means pixels where the bio layer's contribution is at least the stated tier of D_local. Wetness classes are those of §2.2; the generator should export the class map so the gate can read it.

The suggested binding status follows each rule. "Advisory" means: calibrate on reference photos (P) first.

**O1. Light growth is tinted, not grey** (colour)
- Measure: bio pixels at T2–T3 against clean, as Δb* and Δa* per 0.1 of D. Do it the same way as rule I1.
- Pass:
  - Δb* in [+2.5, +7.0] per 0.1 D.
  - Green family: Δa* in [−3.0, −0.4] per 0.1 D.
  - A rusty or dull-yellow family (Δa* in [+0.3, +2.5], Δb* ≥ +3.0) holds 15–45% of light-tier bio pixels.
  - At most 5% of light-tier bio pixels fall inside the dirt band of I1 (Δb* ≤ +0.8).
- Origin: L (Sanmartín: +4.4 to +5.5 b* and −1.5 to −1.9 a* per 0.1 D [S 1]); U ("lighter green or very dull or rusty yellow").
- Status: binding.

**O2. Severe growth is dark green and rust brown** (colour)
- Measure: bio pixels at T5+ on pale paint, using absolute L*, C*ab and hue.
- Pass:
  - L* 28–50 and C* 10–26 for at least 70% of them.
  - Hue in [95°, 135°] (green family) or [45°, 75°] (rust family).
  - At E ≥ 20, each family holds at least 15% wherever the plane has bare concrete or W2–W3 zones.
  - Near-neutral black (C* < 8) is at most 30% overall, but at least 50% of T5+ bio pixels inside ink-stripe zones (W3 below leaks).
- Origin: U ("dark green/rust brown"); L (dark red *Trentepohlia*, grey-black crusts under leaks [S 2], carotenoid ratios [S 13]); C (the Lab numbers, §1.3).
- Status: advisory until P calibration.

**O3. Colour follows local age** (colour)
- Measure: for bio patches of 0.3 m or more, compare the rim band (outer 4 cm) with the core (distance-to-edge in the top 40%).
- Pass:
  - Mean L* of the core is at least 12 below the rim.
  - Mean hue of rim pixels is in [80°, 115°], with C* ≥ 9.
  - For at least 70% of patches, the rank correlation of L* with distance-to-edge is ≤ −0.3.
- Origin: L (b* first, then a*, then L* [S 1]); U ("grow outwards", weaker growth lighter); C.
- Status: advisory.

**O4. Growth sits where water stays** (placement; refines G4)
- Measure: share of bio T2+ area by wetness class.
- Pass:
  - At least 70% in W2–W3 while bio covers under 5% of the plane.
  - At least 50% while it covers 5–20%.
  - W0 never holds more than 10% of bio T2+ area.
- Origin: U ("corners, divots, edges, below ledges"); L ([S 1, S 2, S 4, S 11]).
- Status: binding.

**O5. Plinth belt** (placement)
- Measure: on N/E/W planes with ground contact:
  - mean bio D in 0–0.30 m over mean bio D in 0.5–1.5 m;
  - the belt-top height, where bio T2+ cover first drops below 50% going up, sampled every 0.5 m along the wall.
- Pass:
  - Ratio ≥ 3.0 once t_bio ≥ 2 years.
  - Median belt-top 0.05–0.30 m.
  - Belt-top standard deviation 0.03–0.12 m (a ragged top).
  - At least one upward finger above 0.3 m per 5 m of wall, at corners or splash points.
- Origin: L (belt 5–10 cm, never above 10–15 cm; *Desmococcus* 20–30 cm [S 2]; splash zone 30 cm [S 11]); C.
- Status: binding for the ratio, advisory for the ragged top.

**O6. Corners, joints and divots** (placement)
- Measure: bio T2+ coverage, compared at the same height band, in three places:
  - within 0.3 m of re-entrant vertical corners, against open wall 1–2 m away;
  - on joint pixels, against open wall;
  - on chip and spall pixels from the damage layer, against open wall.
- Pass:
  - Corners ≥ 2.0×.
  - Joints ≥ 2.0×.
  - Chips ≥ 1.5×, at E ≥ 15.
- Origin: U ("corners, divots, edges"); L (corners [S 2]; coarse and rough render [S 4, S 5]); C.
- Status: binding for corners, advisory for the rest.

**O7. Sources make vertical growth; sheltered zones stay clean** (placement)
- Measure:
  - Persistent sources (leaky downpipe joints, scupper and AC drain outlets, sill ends without drips, broken copings): share with bio T2+ within 0.5 m below them.
  - The vertical-to-horizontal extent ratio of the bio patches fed by those sources.
  - Bio D directly under sills with drips, against the interfenestral wall at the same height.
- Pass:
  - At least 80% of sources show bio once t_bio ≥ 2 years.
  - Median extent ratio ≥ 2.0; widths 3–20 cm; lengths 0.3–3 m.
  - At broken downpipes after t_bio ≥ 5 years, at least 50% of the patch is ink-stripe black (C* < 8).
  - Under sills with drips, at most 0.5× the interfenestral wall.
- Origin: L (*Tintenstriche* at broken gutters and downpipes [S 2]; leaking pipes [S 10]; interfenestral pattern and less growth under sills [S 4]); C.
- Status: binding.

**O8. Orientation and light** (gradients; with F4)
- Measure:
  - Bio T2+ coverage on N planes over S planes (F4).
  - Median C* of bio T3+ on S planes over N planes.
  - S-plane bio T2+ coverage at E ≤ 15.
- Pass:
  - Coverage N/S ≥ 1.5, the existing F4. Raise it to ≥ 2.0 for the green family.
  - C* ratio S/N ≤ 0.6: south growth is mould-dark, not green.
  - S-plane coverage ≤ 5%.
- Origin: L (algae north, moulds south [S 5]; north faces [S 4]; north and west [S 12]); C.
- Status: binding for the ratio, advisory for chroma.

**O9. Time unattended adds coverage, not darkness** (time; with L1)
- Measure: between sweep steps of t_bio (+25% each step, or 2-year steps from 1 to 25 years):
  - the change in bio T2+ area;
  - the share of the added summed D that comes from pixels newly at T2+;
  - nestedness: the share of T2+ pixels at step k still T2+ at step k+1.
- Pass:
  - Area ×1.25 or more per step while W2–W3 cover is below 85%.
  - At least 50% of the added D from new pixels.
  - Nestedness ≥ 0.95.
  - Mean D of already-covered pixels still rises, by ≥ 0.01 per step, because they mature.
- Origin: U ("strength should basically equate to time unattended... grow outwards"); L (nucleation-and-growth kinetics [S 3]).
- Status: binding.

**O10. Fronts grow outward** (time)
- Measure: for each step of O9, new T2+ area split into two parts:
  - within 0.3 m of the previous step's T2+ mask (front growth);
  - farther away (new nuclei).
- Pass:
  - Front growth at least 70% of the new area.
  - New nuclei 5–30%.
- Origin: U ("tendrils or blobs"); L (attachment plus growth, nucleation rising with time [S 3]); C.
- Status: binding.

**O11. Onset by wetness class** (time calibration)
- Measure: bio T2+ coverage of each class's area at set values of t_bio.
- Pass:
  - W3 ≥ 15% at 1 year and ≥ 50% at 3 years.
  - W2 ≥ 10% at 3 years and ≥ 30% at 8 years.
  - W1 ≥ 3% at 8 years.
  - W0 ≤ 5% at 15 years.
  - No class above its X_max in §3.3.
- Origin: L (visible at about 0.5 year on damp shaded sites [S 1]; 1 year and 2–5 years on concrete [S 1]; 1–4 years [S 4]); C (the class curves).
- Status: advisory until P calibration.

**O12. Organic outline** (morphology)
- Measure: box-counting dimension of the bio T2+ outline, with box sizes 2, 4, 8, 16, 32 and 64 px (4 cm–1.28 m), on planes where bio covers at least 3%.
- Pass: D_box in [1.12, 1.35].
  - Smooth blobs score 0.97–1.02 and fail.
  - DLA lace (about 1.6–1.7 and up) fails.
- Origin: U ("tendrils or blobs, they don't merely get darker"); C (synthetic calibration: nucleation-and-growth 1.17–1.29, Eden 1.14–1.16, fBm H 0.7 = 1.19 [I-m]).
- Status: binding once checked on 3–5 photo walls with visible algae.

**O13. Many small patches, a few large** (morphology; consistent with C3)
- Measure: bio T2+ connected components of at least 4 px (16 cm²), using the existing `label()`:
  - the log-log slope of the area CCDF;
  - the largest-to-median area ratio.
- Pass:
  - Slope in [−1.1, −0.4].
  - Largest/median ≥ 50 when there are at least 30 components.
- Origin: L (percolation τ = 2.055, slope −1.05 [S 17]; heavy-tailed or lognormal biocrust patches [S 16]); C (synthetic −0.46 [I-m]).
- Status: advisory.

**O14. Rim, satellites and inner gradient** (morphology)
- Measure: for bio patches of 0.3 m or more:
  - mean D of the core (top 40% of distance-to-edge) over the rim (outer 4 cm);
  - the rim ramp, as the 10–90% rise along 16 rays across the outline, reusing the K4 profile code;
  - T2+ cover in a 0–0.2 m band outside the patch, against a 0.4–0.6 m band.
- Pass:
  - Core/rim ≥ 1.5.
  - Ramp 1–5 px for algae films, ≤ 1.5 px for ink-stripe, lichen and moss subtypes.
  - Outer band 5–35% cover and at least 2× the far band.
- Origin: U; C.
- Status: advisory.

**O15. Organism mix and material maps** (material)
- Measure:
  - The number of bio subtypes (green film, black crust or mould, *Trentepohlia*, moss, lichen) each covering at least 0.2% of the wall.
  - Where moss and lichen pixels sit.
  - Height and roughness of bio pixels.
- Pass:
  - Mix: at least 3 subtypes at E ≥ 20.
  - Moss: at least 90% of moss pixels within 5 cm of a ledge top, joint, coping edge or the ground.
  - Lichen: at least 80% of lichen pixels on bare concrete, copings or top bands; lichen dots 1–6 px at E ≥ 15.
  - Height: algae and cyanobacteria films ≤ 0.3 mm (no height signal); lichens ≤ 2 mm; moss cushions 5–20 mm.
  - Roughness, baked at the average state: films 0.75–0.90, crusts 0.60–0.85, moss 0.90–1.0, lichen 0.85–0.95.
  - Bio colour and density in close-ups correlate with coat cavity at ρ ≥ 0.3.
- Origin: L (mosses on collected dirt and soil, lichens south and orange/grey, algae slimy when wet [S 10]; lichen rates [S 7, S 8]; *T. muralis* about 1 cm and 15–16 mm carpets [S/2 27]; rough render [S 4, S 5]); C.
- Status: advisory.

Notes on fit with existing rules:
- O4 tightens G4, and O8 extends F4.
- O9 is L1 specialised to bio.
- O13 must agree with C3's count growth per level.
- I1 keeps bio exempt; O1 and O2 take over its colour checks.

---

## 6. Calibration plan (turning C and I into P)

1. **Colour.** From the reference photos already used for I1 and A1, crop algae on pale paint and on concrete, light and heavy. Measure Lab against a clean neighbour. Use the results to replace the O1, O2 and O3 bands and the §1.3 anchors.
2. **Outline and size.** Segment green, rust and black growth on 3–5 photo walls with visible algae. Measure D_box over 4 cm–1.28 m and the CCDF slope. This sets O12 and O13; my bands rest on synthetic masks only.
3. **Placement.** On the photo walls, label wall foot, corners, sources, sills and joints. Measure coverage ratios for O5, O6 and O7.
4. **Time.** Ask the AD to pick, as with round 7, on a t_bio sweep of 1, 3, 8, 15 and 25 years on one plane. That anchors O11 and the §3.3 curves to taste (U).

---

## 7. What I could not find

- **Measured Lab or sRGB of real facade growth.** Covers *Trentepohlia*, black crusts, moss and lichen on walls. Only the greening shifts on granite [S 1] and the culture hues of cyanobacteria [S 14] were found; everything in §1.3 beyond those is an estimate.
- **Patch-size distributions or exponents for facade biofilm.** Also the fractal dimension of algal patch outlines. Only ecology and percolation analogues were found, plus my synthetic calibration.
- **Field radial growth rates of algal or mould patches on facades** (mm or cm per year). Lab data [S 3] and lichen data [S 7, S 8] exist; the facade front speeds in §3.4 are estimates.
- **Facade surveys giving area shares by age and orientation.**
  - Only qualitative north and west findings [S 4, S 5, S 12].
  - The mould-index coverage tiers [S 9].
  - A Japanese rain-streak survey with 2.7% incidence of streak stains, whose table labels I could not read [S/2 48].
- **Heights and widths of growth below ledges and sills, and inside corners.** No numbers beyond the foot belt (5–15 cm, 20–30 cm [S 2]) and the 30 cm splash zone [S 11].
- **Japan-specific studies.**
  - Danchi or UR biological growth surveys.
  - AC-condensate staining.
  - Official UR repaint cycles. Only the MLIT 12–15-year model was seen, as a snippet [S/2 29].
- **Time to visible growth on dry, sunny walls.** Only estimates.
- **Papers not retrieved:**
  - Multi-year roof weathering (Gladis & Schumann).
  - The Miller bioreceptivity review.
  - Kéfi and Scanlon exponents.
  - The Fraunhofer RH thresholds: blocked, snippet only.
  - The Kider and Chen full texts.
  - The Lund PhD thesis PDF (403).

---

## 8. Sources

Read in full text or on the abstract page (tag S):

1. Sanmartín, Vázquez-Nion, Silva, Prieto 2012, "Spectrophotometric color measurement for early detection and monitoring of greening on granite buildings", *Biofouling* 28(3): https://minerva.usc.gal/entities/publication/6772f545-d7d5-4de3-873c-e5fbf5002846 (PDF: https://minerva.usc.gal/bitstreams/3d05f4d0-a481-4094-b19a-556ab5bc3662/download)
2. Rindi & Guiry 2003, "Composition and distribution of subaerial algal assemblages in Galway City, western Ireland", *Cryptogamie Algologie* 24(3): https://sciencepress.mnhn.fr/sites/default/files/articles/pdf/cryptogamie-algologie2003v24f3a19.pdf
3. Hortemel, Zaghloul, Govin, Debayle 2024, "Characterization of the algal colonization of mortar surfaces using image analysis", *Image Anal Stereol* 43: https://ias-iss.org/ojs/IAS/article/view/3165
4. Kučeríková, Kubečková, Kubečková 2016, "Development of microbiological vegetation on facades of thermally insulated houses" (AECE-16): https://download.atlantis-press.com/article/25870132.pdf
5. Johansson 2011, *Biological growth on rendered façades* (PhD, Lund): https://www.lunduniversity.lu.se/lup/publication/03f68734-3706-438b-967d-41c4afdfc6f7
6. Johansson 2006, *Biological growth on mineral façades* (licentiate, Lund): https://lup.lub.lu.se/record/633710
7. Desbenoit, Galin, Akkouche 2004, "Simulating and modeling lichen growth", Eurographics: https://perso.liris.cnrs.fr/egalin/Articles/2004-lichen.pdf
8. Armstrong & Bradwell 2010, "Growth of crustose lichens: a review", *Geografiska Annaler A*: https://nora.nerc.ac.uk/id/eprint/10283/
9. Krus, Seidler, Sedlbauer 2010, "Comparative evaluation of the predictions of two established mold growth models" (Buildings XI): https://web.ornl.gov/sci/buildings/conf-archive/2010%20B11%20papers/229_Krus.pdf
10. Ibstock Brick, Technical Information Sheet 8, "Algae, lichen and mould growths" (2004, trade sheet): https://inspectapedia.com/exterior/Algae-lichen-and-mould-growths.pdf
11. Caparol, Capatect Sockel brochure (trade): https://www.caparol.de/caparol_pim_import/caparol_de/broschueren/pdfs/300730_CAP-25066_BRO_Capatect_Sockel.pdf
12. DETAIL, "Research and practice: algae growth on ETICS – a problem without a solution?": https://www.detail.de/en/article/research-and-practice-algae-growth-on-etics-a-problem-without-a-solution-1327
13. "Terrestrial *Trentepohlia* sp. … strong desiccation tolerance and broad light and temperature adaptation" (2023): https://pmc.ncbi.nlm.nih.gov/articles/PMC10590310/
14. Prieto, Vázquez-Nion, Silva, Sanmartín 2018, "Shaping colour changes in a biofilm-forming cyanobacterium…", *Algal Research* 33: https://minerva.usc.gal/entities/publication/4e5ede66-45cf-4487-bbbe-60b03015f202
15. Barberousse et al. 2006, "Diversity of algae and cyanobacteria growing on building façades in France", *Algological Studies* 120: https://www.schweizerbart.de/papers/algol_stud/detail/120/74727/Diversity_of_algae_and_cyanobacteria_growing_on_bu
16. Bowker & Maestre 2012, "Inferring local competition intensity from patch size distributions: a test using biological soil crusts", *Oikos*: http://www.usgs.gov/publications/inferring-local-competition-intensity-patch-size-distributions-a-test-using-biological
17. Wikipedia, "Percolation critical exponents": https://en.wikipedia.org/wiki/Percolation_critical_exponents
18. Wikipedia, "Diffusion-limited aggregation": https://en.wikipedia.org/wiki/Diffusion-limited_aggregation
19. Wikipedia, "Kardar–Parisi–Zhang equation": https://en.wikipedia.org/wiki/Kardar%E2%80%93Parisi%E2%80%93Zhang_equation
20. Wikipedia, "Eden growth model": https://en.wikipedia.org/wiki/Eden_growth_model
21. SideFX, Houdini 22 Copernicus "Reaction-Diffusion": https://www.sidefx.com/docs/houdini/copernicus/reaction_diffusion.html
22. Adobe, Substance 3D Painter "Dirt" generator: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dirt
23. Dorsey, Pedersen, Hanrahan 1996, "Flow and changes in appearance" (SIGGRAPH abstract): https://history.siggraph.org/?p=117020
24. Chen et al. 2005, "Visual simulation of weathering by γ-ton tracing" (SIGGRAPH abstract): https://history.siggraph.org/?p=113957
25. Wikipedia, "Gloeocapsa magma": https://en.wikipedia.org/wiki/Gloeocapsa_magma
26. Nakajima et al. 2020, soiling by airborne algae on a residence roof in a cold region of Japan: https://www.scipedia.com/public/Nakajima_et_al_2020b

Secondary or snippet only (tag S/2):

27. Botany One on Veeger, Ottelé, Jonkers 2026, *Ecological Engineering* 223 (moss on bioreceptive concrete): https://www.botany.one/from-concrete-jungles-to-living-carpets-how-moss-on-bioreceptive-concrete-can-transform-our-cities/ ; *T. muralis* height from https://earthstar.blog/2021/01/26/common-wall-mosses/ (snippet)
28. Fraunhofer publica, "Early colonisation of modern building surfaces" (blocked, snippet): https://publica.fraunhofer.de/entities/publication/3b978f83-cc0f-4e14-9b64-87bd80c56861
29. MLIT long-term repair plan guideline, wall repaint 12–15 years (snippet; PDF text not extractable): https://www.mlit.go.jp/jutakukentiku/house/content/001481779.pdf
30. Tokyo normals 1991–2020 (JMA data reprocessed): https://weather.time-j.net/stations/jp/tokyo/
31. AC condensate 0.5–2 L/h (consumer pages, snippet), e.g. https://lifestyle.assist-all.co.jp/?p=41031
32. TalTech survey of ETICS apartment blocks in Tallinn (snippet): https://digikogu.taltech.ee/en/Download/18eac19c-a9cf-4c9a-b23d-a50535bf3f6f
33. Granada, deterioration patterns by orientation, 144 facades (snippet): https://digibug.ugr.es/handle/10481/111062
34. Brazil, 34-month paint exposure, *J Coat Technol Res* (snippet): https://link.springer.com/article/10.1007/s11998-011-9350-1
35. US patent 8703166, "Systems and methods for reducing microbial growth" (snippet): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8703166
36. Matsushita & Fujikawa 1990, *Physica A* 168 (snippet): https://ideas.repec.org/a/eee/phsmap/v168y1990i1p498-506.html
37. Percolation hull 7/4 and external perimeter 4/3 (snippet): https://arxiv.org/pdf/cond-mat/0210106
38. Kéfi et al. 2007 and Scanlon et al. 2007, *Nature* 449 (abstracts): https://ideas.repec.org/a/nat/nature/v449y2007i7159d10.1038_nature06111.html ; https://ideas.repec.org/a/nat/nature/v449y2007i7159d10.1038_nature06060.html
39. Tran et al. 2012, mortar characteristics and *K. flaccidum* biofouling (snippet): https://hal.archives-ouvertes.fr/hal-00680295
40. Dubosc, Escadeillas, Blanc 2001, *Cem Concr Res* 31 (snippet): https://hal.archives-ouvertes.fr/hal-02160788
41. Hiroshima University digital museum, スミレモ (snippet): https://www.digital-museum.hiroshima-u.ac.jp/~main/index.php/Trentepohlia_bosseae_var_samoensis
42. Eawag, Tintenstrich communities (snippet): https://www.eawag.ch/de/abteilung/uchem/projekte/cyanolichen
43. Kider, Raja, Badler 2011, "Fruit senescence and decay simulation" (abstract summary): https://diglib.eg.org/handle/10.1111/v30i2pp257-266
44. Irvine, Bull, Keeling 2016, *Theor Popul Biol* 108 (snippet): https://ideas.repec.org/a/eee/thpobi/v108y2016icp70-74.html
45. Sun et al. 2025, biocrust patch-size dynamics (preprint, snippet): https://www.biorxiv.org/content/10.1101/2025.06.10.658851.full.pdf
46. Nihon University, Marui et al., moss on campus concrete walls (snippet): https://www.cit.nihon-u.ac.jp/kouendata/No.39/4_kenchiku/4-001.pdf
47. Gunma Museum of Natural History report 2015, roof mosses (snippet): https://www.gmnh.pref.gunma.jp/wp-content/uploads/report2015_30.pdf
48. Ohnishi, Matsui, Yuasa 2010, field survey of stains from flowing rain water (labels not extractable): https://www.cit.nihon-u.ac.jp/kouendata/No.43/4_kenchiku/4-004.pdf
49. LNEC / Parracha et al., ETICS natural ageing and biological colonisation (snippet): https://repositorio.lnec.pt/handle/123456789/1016953
50. UCL Discovery 2025, wind-driven rain and algal growth on ETICS (snippet): https://discovery.ucl.ac.uk/id/eprint/10217417
51. ASTM D3274-09(2021) (store page snippet): https://store.astm.org/d3274-09r21.html
52. Tanaca et al. 2011, fibre cement discoloration in Brazil (snippet): https://repositorio.usp.br/item/002140682
53. Wall-painting biodeterioration, persistent black pigment (snippet): https://repositorio.ucp.pt/entities/publication/17ce98f0-db5b-411e-90b9-4093e872ea05
54. Houdini growth and infection solver tutorials (snippet): https://www.sidefx.com/tutorials/a-point-based-growth-solver/ ; https://entagma.com/?p=872
55. Substance Designer Slope Blur tutorial (snippet): https://origin-www.lynda.com/Substance-Designer-tutorials/Adding-detail-Slope-Blur-node/761922/5013736-4.html
56. SIGGRAPH 2005 wrap-up, γ-tons for stains and moss (snippet): https://gamedeveloper.com/game-platforms/feature-technical-event-wrap-up-siggraph-2005-
57. Fortuna & Tretiach 2018, *Xanthoria parietina* growth and site moisture (snippet): https://agris.fao.org/search/fr/records/65df722763b8185d9cacefcf

Measurements made this session [I-m] were in-memory numpy runs on this machine, with no files written:
- Planes of 750 × 3000 px (2.25 Mpx): one FFT octave 87 ms, one Eden step 8 ms, one Gray-Scott iteration 20 ms, one min-plus sweep 137 ms.
- Parallel DLA on 512² with 20k walkers for 4,000 steps: 2.6 s for a 694 px cluster.
- Outline and patch statistics on 1024² synthetic masks, as in §3.5.
