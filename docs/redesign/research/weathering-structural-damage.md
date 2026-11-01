# Structural damage on aged danchi — research note (round H)

Prepared 2026-11-01 for the damage control. It follows the art director's review of the round-G damage sweep (0 to 1).

It builds on the round-G note `weathering-cracks-edges-damage.md` ("rG" below), the K rules in `scripts/weathering/weather_rules.json`, and the `procedural-mesh-damage` skill. It does not repeat them. Where rG already has a number, this note cites it as rG §x or rG-Xn and goes further.

- **Subject:** 1960s–80s five-storey RC walk-up slab blocks: painted walls, balcony slabs, steel rails, stair towers.
- **Texture scales:** facade space at 50 px/m (20 mm/px), plus 1 mm/px close-ups. Both are baked for Unreal and Godot.
- **Geometry:** damage geometry is planned next in Houdini 22.
- **Asset metrics used here** (`examples/danchi/README.md`):

  | Metric | Value |
  |---|---|
  | Floor-to-floor height h_s | 2.8 m |
  | Unit bay width W | 6.0 m |
  | Balcony window | 1.6 × 1.1 m, sill at 0.9 m |
  | Sliding door | 3.4 × 2.0 m |
  | Parapet | 1.1 m |
  | Wall | 0.18 m |
  | Slab | 0.18 m (balcony slab 0.15 m) |
  | Seam margin for chips | 0.15 m from bay ends |

**What the art director asked, condensed**
1. The low half of the sweep is fine; the high half needs work.
2. Edge wear at 0.5 and 0.75 is too subtle, and no chunks are missing.
3. High damage needs "longer structural cracks and less of the cracking webbing".
4. Serious cracks should come with surface "missing/fallen off".
5. Cracks at 2× are "too faint".
6. Look into crack simulation, and into pre-cracked meshes that cache simulated damage, for destructible assets.
7. "Damage might need special attention all on its own."

**Tags**

| Tag | Meaning |
|---|---|
| **[S n]** | Source n states it (§8). |
| **[S/2 n]** | Secondary: a search snippet, forum, blog, or a value quoted by another paper. |
| **[I]** | My inference, estimate or derivation. |
| **I←n** | An estimate anchored on source n. |
| **rG-Xn** | Source Xn in the round-G note's §10. |

In §8, ✓ marks pages I read myself in this session. **h** marks pages read by a helper research pass in this session; it reported the link and the number, and I did not re-read them. Unmarked entries come from search snippets or reference lists.

**Coverage**
- **Well covered:**
  - damage-class ladders (JBDPA, quick inspection, EMS-98, FEMA 306, BRE 251, ACI 201.1R)
  - restrained-wall cracking, and corrosion failure modes
  - a Japanese public-housing survey sheet with numeric grades
  - Houdini, Unreal and Godot destruction tooling, and the fracture-algorithm literature
- **Thin:**
  - crack lengths on real danchi relative to storey height (no survey found; derived from mechanics and the asset's metrics)
  - spall sizes at balcony slab noses
  - Chaos performance budgets
- **Prototype:** I ran a small numpy version of the recommended crack algorithm in the scratchpad, not in the repo, to measure its cost and failure modes (§3.5).

---

## 1. The numbers that matter most

**Every damage ladder moves up by width and lost surface, never by more fine cracks**

| Ladder | Heavy end of the ladder | Source |
|---|---|---|
| JBDPA member damage class (RC columns and walls) | I ≤0.2 mm · II 0.2–1 mm · III 1–2 mm with slight cover spalling · IV >2 mm, marked spalling, bars exposed · V bars buckled, core concrete falling out | [S 3, S 4] |
| Quick inspection (応急危険度判定), RC and wall-type RC | III about 2 mm, very slight peeling · IV many ≥2 mm cracks, heavy peeling, bars largely exposed · V bars buckled or broken, concrete crushed along the failure plane | [S 5] |
| EMS-98, RC buildings | G3: cover spalls, bars buckle · G4: large cracks with crushing, bars fracture | [S 8] |
| FEMA 306 | "Heavy" given for spalling, bar buckling or significant cracking (coupling-beam example) | [S 6, S 7] |
| ACI 201.1R, via USACE EM 1110-2-2002 | cracks fine <1 mm / medium 1–2 mm / wide >2 mm; small spall ≤20 mm deep and ≤150 mm across; large spall >20 mm deep and >150 mm | [S 2] |

None of them grades a building as worse because it has more fine cracks. Fine networks belong to the low end: shrinkage and coatings [I].

**Long cracks: restrained walls**
- Walls restrained at their base crack in through cracks that run the full height of the lift, about one wall height apart [S 1].
- EN 1992 bounds the spacing at 1.3 × wall height for walls with little horizontal steel [S 1].
- The width peaks at 0.4–0.6 of the lift height. Just above the base it is about 60% of the peak [S 1].
- Cracks start as short separate pieces that later join into longer, wider cracks [S 1].
- They run near vertical, inclined near the wall ends. Openings start wide diagonal cracks at their top outer corners [S 1].
- Inducer joints at ≤3 m spacing with ≥20% section loss collect at least 70–80% of the cracks [S 13].
- **On this danchi** [I←S 1, metrics]:
  - solid-wall shrinkage cracks 2.2–2.8 m long (0.8–1.0 h_s), 2.8–3.6 m apart, about 2 per 6 m bay
  - spandrel cracks between stacked windows about 1.7 m (0.6 h_s)

**How much cracking real blocks carry**
- **Five Japanese RC apartment blocks** (high-rise, 15–21 years old) [S 12]:
  - 0.5–2.5 m of crack per m² of member surface, mostly under 0.3 mm
  - defects of ≥50 × 50 × 10 mm at 0.1–0.4 per m², worst 4–8 per m²
- **Otaru municipal public-housing survey sheet:** the worst grade, all for cracks ≥0.2 mm [S 15]:

  | Feature | Worst grade |
  |---|---|
  | Cracks along bars | ≥8 m per 100 m² |
  | Cracks around openings | ≥10 m per 10 openings |
  | Map cracking | ≥30% of the face |
  | Other cracks | ≥20 m per 100 m² |
  | Spalling and delamination from bar corrosion | ≥20% of the face |

- **What this means for K7** [I]: its 1.0 band (1.5–3.5 m/m²) asks for more crack length than these sheets treat as the worst case. The generator reaches the band with webbing (§2.6).

**Missing surface**
- **Sequence:** a crack forms over the bar, then the concrete delaminates along the bar mat, then it spalls. A rectangular crack pattern traces the bars underneath [S 2].
- **Bar spacing decides the failure** [S 16]:
  - bars widely spaced relative to cover: corner spalls
  - bars closely spaced: lateral cracks join into a delamination plane
- **45° cracks** run from the bar to the surface when bar spacing is more than 6 bar diameters, or cover is less than 3 bar diameters [S/2 17].
- **1 mm** is the "severe cracking" limit used in corrosion reliability models [S/2 18].
- **Shime tower, unmaintained 75 years:** flakes 5–10 cm across; 3.7–9.9% of each face spalled [rG-J25].

**Structural action on wall-type danchi**
- **Earthquakes:**
  - In Kumamoto 2016, 15 wall-type RC blocks of 3–4 storeys showed no structural damage on external survey [S 10].
  - UR's guideline says wall-type blocks came through many past earthquakes almost undamaged [S 11].
- **Believable structural cracks on a derelict danchi** [I←S 10, S 11, S 14]:
  - settlement cracks stepping diagonally through window corners
  - corrosion lines along slab noses and corners
  - old shrinkage cracks that widened and linked across slab lines
  - earthquake damage, as a story option only
- **Settlement:**
  - Angular distortion of 1/500 is the usual no-crack design limit; 1/150 marks structural damage [S/2 19].
  - A 1966 school on reclaimed ground, with about 1/200 over its end spans, had marked wall shear cracks up to about 2 mm [S 14].

**Algorithms and tools**
- **Best fit for the numpy generator:** a stress-field tracer in the style of Paquette et al. 2002 [S 40]:
  - start where stress/strength peaks
  - grow perpendicular to the largest principal stress σ1
  - stop below a lower strength
  - relax the stress around each new crack
- **Prototype:** it ran in 0.8–1.2 s per 60 × 14 m facade in plain numpy [I, measured §3.5].
- **Unreal:** Houdini Engine outputs Chaos Geometry Collections from packed pieces. `unreal_gc_piece` is the cluster level and `unreal_gc_cluster` the cluster index [S 74].
- **Godot:** no destruction system. Jolt physics has been built in since 4.4 and has been the default for new 3D projects since 4.6 [S 85, S 86].

---

## 2. Long structural cracks versus webbing (topic A)

### 2.1 What "heavy damage" means in the ladders

| Ladder | Low | Middle | High | Source |
|---|---|---|---|---|
| JBDPA member class, set by the widest residual crack | I: <0.2 mm, hard to see | II: 0.2–1 mm, clearly visible | III: 1–2 mm, slight spalling · IV: >2 mm, marked spalling, bars exposed · V: bars buckled or lost bond, core concrete out, visible deformation | [S 3, S 4] |
| JBDPA capacity factor η, shear members | 0.95 (I) | 0.6 (II) | 0.3 (III), 0 (IV, V) | [S 3] |
| Quick inspection | — | III: about 2 mm, very slight peeling | IV: many ≥2 mm, heavy peeling, bars largely exposed · V: bars buckled, concrete crushed and slipped, sashes bent | [S 5] |
| EMS-98 (RC) | G1: hairline cracks in plaster and infill | G2: cracks in columns, beams and structural walls; cladding and plaster fall | G3: cover spalls, bars buckle; single infill panels fail · G4: large cracks with crushing, bar fracture · G5: collapse | [S 8] |
| FEMA 306 | Insignificant: properties essentially unchanged | Moderate: shear cracks, no buckling or major spalling | Heavy: spalling, bar buckling, significant cracking; λ (stiffness / strength / deformation) 0.4 / 0.5 / 0.8 | [S 6, S 7] |
| ACI 201.1R, via USACE | fine <1 mm | medium 1–2 mm | wide >2 mm; large spall >20 mm deep and >150 mm | [S 2] |
| BRE Digest 251 (masonry houses) | 0–2: ≤5 mm, cosmetic | 3: 5–15 mm, serviceability | 4: 15–25 mm · 5: >25 mm, stability | [S 9; S/2 9 for widths] |
| MLIT, AIJ (Noguchi), Hashima corrosion grades | rust-free cracks <0.3 mm | rust-stained cracks, cracks along bars | delamination along bars, exposed bars, section loss (Hashima IV: bars largely exposed; V: concrete behind the bars lost) | [rG §4.4] |
| Otaru public-housing sheet | maintenance only (score <10) | partial repair (10–30) | large repair (≥30), or any single item at its limit | [S 15] |

What the ladders agree on [I]:
1. Each step up is wider cracks, lost cover, then exposed or buckled bars.
2. No ladder steps up by adding fine cracks.
3. JBDPA III–IV is where spalls join the cracks. That is our 0.75–1.0.
4. BRE widths are for masonry houses on moving foundations. For RC, the same visual severity comes at roughly a tenth of the width: 2 mm is already JBDPA IV [S/2 9; I].

### 2.2 Crack types on an aged slab block, with numbers

Lengths are given in storey heights (h_s = 2.8 m) and bay widths (W = 6 m).

**A. Drying shrinkage in restrained lifts (the main long, regular crack)**
- **Where** [rG §2.2 A]:
  - solid end walls, and solid panels between corridor openings
  - parapets and balcony fronts
  - spandrels between stacked windows
- **Length** [S 1; I for the danchi values]:
  - A long wall (L/H ≫ 2) cracks over the full lift height. Danchi walls are cast storey by storey [rG §2.2 E], so each lift is a restrained wall.
  - Solid walls: 0.8–1.0 h_s (2.2–2.8 m).
  - Spandrels: about 0.6 h_s (1.7 m: sill at 0.9 m above the floor, plus 0.8 m of wall above the lower window's head).
  - Parapets: about 1.1 m.
- **Width:**
  - Along the crack: it peaks at 0.4–0.6 of the lift height, is about 0.6 × the peak at the base, and tapers to the tip [S 1].
  - Measured shrinkage strain in a 1966 RC building: about 150 × 10⁻⁶ in beams and 200 × 10⁻⁶ in slabs [S 14]. With restraint R ≈ 0.5 and 3 m spacing, w ≈ R·ε·s ≈ 0.26 mm. That sits on the AIJ outdoor limit of 0.3 mm [I].
  - Maintained: 0.05–0.3 mm. Derelict: 0.5–1.5 mm, where the bars across the crack corrode and the crack works with the seasons [I←rG §2.2].
- **Spacing:**
  - About 1 × wall height in the test walls that cracked early; at most 1.3 × wall height under EN 1992 [S 1].
  - 1.5–6 m [rG-W3]. ACI 224R suggests wall joints at 1–3 × wall height [S/2 21].
  - Danchi: 2.8–3.6 m, i.e. 1.7–2.1 per bay on solid walls [I].
- **Orientation:** near vertical; inclined near wall ends [S 1].
- **Branching:**
  - Few branches. Short pieces join into one crack [S 1].
  - Free ends, or T-junctions into slab lines and openings [rG §2.2 A].
- **Frequency:**
  - Inducer joints at ≤3 m collect 70–80% of the cracks [S 13].
  - 1960s–70s walls mostly lack them, so the cracks fall mid-panel [rG §2.2 A].
- **At high damage** [I]:
  - The same lines become wider, with chipped lips, a dirt halo, and efflorescence at slab lines.
  - On end walls and at stair-tower junctions, some link across slab lines into lines several storeys long.

**B. Re-entrant corner cracks at openings**
- **Where:** cracks under almost all windows, more conspicuous at lower windows. Diagonal cracks at the four corners of nearly every floor; a V pattern at end bays [rG-J29].
- **Length:**
  - Maintained: 0.3–1.0 × opening width, i.e. 0.5–1.6 m for the 1.6 m window [rG §2.2 B].
  - High damage: they reach the next free edge, the slab line or the opening below (about 0.6 h_s). In settlement cases they chain through openings (C below) [I].
- **Width:**
  - Widest at the corner, tapering away. The test walls' wide diagonal cracks started at the opening's top outer corner [S 1].
  - 0.1–0.5 mm maintained; 1–3 mm derelict, once the corner bars corrode [I].
- **Stress:** the stress at a 90° re-entrant corner is singular, σ ∝ r^−0.46 (Williams' wedge solution; exponent λ ≈ 0.5445 for the L-shaped corner) [S/2 20].
- **Angle:** 45 ± 15° near the corner, turning vertical beyond about 0.3–0.5 opening widths [rG §2.2 B; prototype §3.5].
- **Branching:** one main crack per corner. Reinforcement spreads it into finer cracks further from the opening [rG-J30].

**C. Settlement and shear cracks (the long diagonal family)**
- **Mechanics** [I, from the strain field]:
  - In a distorting zone the principal tension runs along the diagonal that lengthens. Cracks form across it, at about 45°, and rise toward the part that settles.
  - A sagging middle gives cracks rising toward the middle from both sides. Settling ends give cracks rising toward the ends.
- **Path through openings** [I; prototype §3.5]:
  - The crack runs from window corner to window corner across spandrels and piers, because corners concentrate stress (B).
  - So a chain crosses 2–5 storeys (5.6–14 m) and 0.5–2 bays, made of segments of about 1.4–2 m each.
- **Thresholds:**
  - 1/500 is the no-crack design limit and 1/150 marks structural damage [S/2 19].
  - In a 1966 school on reclaimed ground, about 1/200 over the five end spans partly yielded the frame. Walls with doorways showed marked shear cracks; the widths drawn run from 0.04 to 2.0 mm [S 14].
- **Width** [I]:
  - Largest where the distortion is largest.
  - Model: w ≈ 0.3·β·h_p, with β the angular distortion and h_p the panel height. This gives about 2 mm at β = 1/200 on a 1.4 m spandrel, matching [S 14].
- **Shear from earthquakes:**
  - X-cracks in spandrels (壁梁) and short piers, graded by the JBDPA widths [S 3].
  - Wall-type blocks rarely get them [S 10, S 11]. Use them as a story option at 1.0 only.
- **Stair-step cracks:** block masonry only (site boundary walls, ブロック塀), not RC walls [I].
- **Frequency:** rare on danchi built on firm ground. Use as a story option for one block, or one end, on reclaimed land [I].

**D. Corrosion cracks along bars, with delamination and spalls**
- **Where:** slab noses, parapet tops, external corners, under windows. Over a bar grid they form a rectangular pattern [S 2; rG §2.2 D].
- **Length** [I]:
  - Maintained: spots of 0.2–1 m.
  - Neglected: runs of 0.5–3 m along slab noses.
  - Derelict: 50–100% of a nose (3–6 m per bay), and storey-long lines at external corners (0.5–1 h_s).
- **Width:**
  - Under 0.05 mm at first [rG §2.2 D]. 1 mm is the "severe cracking" limit state [S/2 18].
  - Spalling usually starts at about 0.5–1.5 mm [rG §4.1].
- **Spacing:** the bar pitch, D10–D13 bars at 200–300 mm [rG §4.2]. Parallel cracks at that pitch outline plates [I←S 2].
- **Failure mode by geometry:**
  - Corner spalls when bars are widely spaced relative to cover. A delamination plane when they are close [S 16].
  - 45° cracks from bar to surface when spacing is more than 6D or cover is under 3D [S/2 17].
- **Frequency:**
  - The Otaru sheet grades cracks along bars at none / >0–5 / 5–8 / ≥8 m per 100 m² [S 15].
  - In MLIT's survey of old blocks, grade 3 (delamination along bars, or exposed bars) was found at 18.2% of 903 points [rG-J15].

**E. Joint lines: construction joints, cold joints, slab edges**
- **Construction joints:** a horizontal joint at every floor. Joints carbonate quickly and count as high-risk for repair [rG-J8, J3].
- **Length** [rG §2.2 E; I]:
  - An open joint crack runs along the floor line for 0.5–2 bays (3–12 m).
  - Cold joints are wavy, at 0–30°, within one lift; 0–1 per storey per 10 m.
- **Balcony slabs:**
  - In one block only the balcony slabs cracked, at 0.5 m/m². Upper-floor balcony slabs of another reached 1.0–1.5 m/m² after the 2011 earthquake [S 12].
  - Also: a crack at the slab root along the wall line, and a corrosion strip along the nose [rG §2.2 F].
- **Width:** 0.1–0.5 mm, with efflorescence and leak trails [rG §3.3].

**F. Map cracking (the "webbing")**
- **Classes:**
  - AASHTO: cells 0.3–0.9 m is moderate; under 0.3 m is heavy [rG-W7].
  - FHWA ASR area classes: <5 / 5–25 / >25% [rG-W5].
  - Otaru grades map-cracked area at <3 / 3–10 / 10–30 / ≥30% of the face [S 15].
- **On painted danchi walls:** rare. It is mostly a coating and crazing feature, seen at close range [rG §2.2 G–H].
- **Rule:** at facade scale this is the webbing the art director wants less of. Keep it under 3% of the wall unless an ASR story is chosen [I←S 15].

**Summary by type**

| Type | Length | Width, maintained → derelict | Spacing | Orientation | Branching | Frequency on old blocks |
|---|---|---|---|---|---|---|
| A. Shrinkage in lifts | 0.8–1.0 h_s on solid walls; 0.6 h_s in spandrels; links across slabs at 1.0 | 0.05–0.3 → 0.5–1.5 mm; peak at 0.4–0.6 of the lift | 1–1.3 × lift height (2.8–3.6 m) | vertical; inclined at wall ends | few; T at slabs and openings | most solid panels; under almost all windows |
| B. Opening corners | 0.3–1.0 × opening width → to the next slab or opening | 0.1–0.5 → 1–3 mm; widest at the corner | one per corner | 45 ± 15°, then vertical | one main crack, fans out | most windows on every floor |
| C. Settlement and shear | chains of 2–5 storeys, 0.5–2 bays | about 0.3·β·h_p: 0.2 → 2–10 mm | parallel sets in the shear zone | ±45°, rising toward the settled part | few; parallel sets | rare: a story option |
| D. Along bars | spots of 0.2–1 m → nose runs of 3–6 m, corner lines 0.5–1 h_s | <0.05 → 1–3 mm; spalls from about 0.5–1.5 mm | bar pitch 0.2–0.3 m | along bars: horizontal at noses, vertical at corners | grid; outlines plates | 18% of MLIT points at grade 3; Otaru ≥8 m/100 m² is the worst grade |
| E. Joints and slab edges | 0.5–2 bays along floor lines | 0.1–0.5 mm | each floor | horizontal (cold joints 0–30°) | few | common at floor lines and balconies |
| F. Map | patches of 1–5 m; cells 0.3–0.9 m | 0.1–1 mm (ASR to 5–10 mm) | cell size | isotropic | network, Y and T | rare on danchi: under 3% of the face |

### 2.3 How often each type occurs on old blocks

- **Japanese surveys of old RC buildings:**
  - 1957, 30+ buildings: cracks under almost all windows, diagonals at the corners of nearly every floor, V patterns at end bays, an inverted V near the top [rG-J29].
  - Five apartment blocks, 15–21 years old: 0.5–2.5 m/m², mostly under 0.3 mm. Cracks concentrated in balcony slabs and in beam–column panel zones [S 12].
- **Shares by type:** no survey gives them for danchi. The Otaru sheet's thresholds show what the authority expects as "worst": per 100 m², 8 m along bars, 20 m of other cracks, and 10 m around every 10 openings. That is about 0.3–0.5 m/m² of ≥0.2 mm cracks in total [S 15; I for the sum].
- **Estimated length shares of ≥0.2 mm cracks** [I←rG §2.3, S 12, S 15]. The 1.0 column assumes the settlement story is on; without it, its share goes to A and D.

  | Type | 0.25 | 0.5 | 0.75 | 1.0 |
  |---|---|---|---|---|
  | A shrinkage | 35–50% | 30–45% | 25–40% | 20–35% |
  | B corners | 30–45% | 25–40% | 20–30% | 15–25% |
  | C settlement or shear | 0 | 0–5% | 5–20% | 10–30% |
  | D along bars | 5–10% | 10–20% | 15–25% | 15–30% |
  | E joints | 5–10% | 5–10% | 5–10% | 5–10% |
  | F map | ≤5% | ≤5% | ≤5% | ≤5% |

### 2.4 Serious cracking goes with missing surface

**When surface starts to go**
- Corrosion: a crack over the bar, delamination along the bar mat, then a spall [S 2].
- Structural cracks: JBDPA III (1–2 mm) brings slight spalling; IV (>2 mm) brings marked spalling and exposed bars [S 3, S 4].
- Corrosion cracks: 1 mm is the severe limit [S/2 18]; spalls usually start between 0.5 and 1.5 mm [rG §4.1].

**Five kinds of loss**

| Kind | Trigger | Size | Depth | Shape | Where | Source |
|---|---|---|---|---|---|---|
| 1. Lip spalls along wide cracks | w ≥1 mm (JBDPA III); marked at w ≥2 mm (IV) | 10–50 mm across the crack, 20–150 mm along it; on 5–25% of 1–2 mm crack length and 25–60% of ≥2 mm length | 5–20 mm (MLIT Level 2 depth) | Chipped, alternating sides; the crack stays visible inside | Every serious crack, more on lower floors and wet faces | [I←S 3, S 4; rG-J1] |
| 2. Cover strips over a bar | Crack along the bar at w ≥0.5–1.5 mm, cover <25 mm | Across the bar about 2(c + D/2), i.e. 50–90 mm for cover 20–35 mm and D10–D13; along the bar 0.1–1 m (aspect 1.5–4) | Cover plus bar: 30–50 mm; flat floor at bar depth, bar exposed | Strip with two 45° flanks | Slab noses, corners, parapet tops, under sills | [I←S/2 17; rG §4.2; S 2] |
| 3. Delaminated plates | Two or more parallel bar-line cracks close together; bars close relative to cover | 0.05–1 m² (2–5 bar pitches each way) | At the bar layer, 20–40 mm | Flat-backed plate outlined by bar-line cracks; before falling, hollow-sounding with a 0.5–3 mm bulge | Soffits, slab noses, walls with low cover | [S 16; S 2; rG S10; I] |
| 4. Corner chunks | A corner bar corroding from two faces; a structural crack meeting an arris | Legs 2–4 × cover (50–150 mm) at 0.5, up to 0.2–0.5 m at 1.0 | To and behind the corner bar, 30–80 mm | Wedge bounded by two cracks at about 45°; corner bar exposed over 0.2–1 m | External corners of the building, stair towers, balcony slab corners | [S 16; skill causes.md; I] |
| 5. Slab-nose loss | Corrosion of nose and bottom bars; drip groove thins the cover | 0.3–2 m runs at 1.0 | 30–60 mm; bars exposed and bowed outward 5–30 mm | Run of strips merging into a missing nose | Balcony and corridor slab edges | [rG §4.2, S8; I] |

**Counts and areas**
- Defects of ≥50 × 50 × 10 mm [S 12]:
  - 0.1–0.2 per m² typical; balcony slabs 0.2–0.4 per m²
  - worst 4–8 per m², in low-floor panel zones
- Spalled area share by amount: K5 (rG S1), from 0.01–0.1% at 0.25 to 3–10% at 1.0.
- Bars are exposed only where cover is under 25 mm [rG-J25], at 2–6 m of bar per m² of spalled area [rG S8].
- **Hidden delamination:** it is often 2–3 × the visible spall [skill causes.md]. I could not re-find the primary source this session.

### 2.5 Condition ladder: high damage is a few long cracks with spalls along them

All bands are [I], anchored on the sources named in the row heads. "Chain" means crack segments linked through T-junctions, openings and slab lines (§3.4). "Storey" means h_s = 2.8 m.

| a_D | Real analogue | Widest crack | Longest chain | Chains ≥1 storey per 100 m² | Share of ≥0.2 mm length in chains ≥1 storey | Webbing ÷ structural length | Surface loss along cracks | Spalled area (K5) | Largest single loss | Exposed bar (m/m² of wall) | Geometry |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | New, or just through a large repair [rG-J10] | ≤0.1 mm, sealed | — | 0 | — | — | none | 0 | — | 0 | intact |
| 0.25 | Aged, maintained: JBDPA I, MLIT L1–2, Otaru "maintenance" [S 3, S 15] | 0.2–0.5 mm | 0.5–1 storey (corners, spandrels) | 0–0.5 | any | ≤2 (hairlines allowed) | none; edge chips only | 0.01–0.1% | ≤0.15 m | 0 | intact, plus chips |
| 0.5 | Neglected: JBDPA II, rust-stained (MLIT L3), Otaru "partial repair" [S 3, rG-J1] | 0.5–1 mm | ≥1 storey | 0.5–2 | ≥0.2 | ≤1 | cover strips at noses and corners; first corner chunks | 0.1–0.5% | 0.15–0.4 m | 0.002–0.03 | damaged variants on 10–30% of bays |
| 0.75 | Vacant, unsafe: JBDPA III; fails the MLIT spall-risk test; Hashima III [S 3, rG-J15, J24] | 1–2 mm (to 3 mm on story cracks) | ≥2 storeys | 1–4 | ≥0.4 | ≤0.5 | lip spalls on 5–25% of 1–2 mm length; the first plates fall | 0.5–3% | 0.4–1.0 m | 0.01–0.18 | damaged variants on 30–60% of bays; corner chunks |
| 1.0 | Derelict: JBDPA IV (V locally), Hashima IV–V, Shime [S 3, rG-J24, J25] | 3–10 mm (10–25 mm locally on story cracks) | ≥3 storeys | 2–6 | ≥0.5 | ≤0.3 | lip spalls on 25–60% of ≥2 mm length; plates gone in runs | 3–10% | 1–2.5 m | 0.06–0.6 | destroyed sections; missing nose runs with bars hanging |

For one 60 × 14 m front of about 650 m² of wall, 1.0 means [I]:
- 13–39 crack chains of a storey or longer
- widest cracks 3–10 mm
- 20–65 m² of missing surface, the largest patch 1–2.5 m across
- 40–390 m of exposed bar

### 2.6 What this means for the current generator

These points come from reading `layer_cracks` and `layer_damage` in `scripts/weathering/weather_fields.py`. The interpretation is [I].
- **Webbing:** K7 rewards total crack length (1.5–3.5 m/m² at 1.0). Pattern cracks, recursive splits of patches, start at amount 0.35 and grow with it. That is the webbing.
- **Faint lines:** the median width of the primary cracks is 0.10 + 0.45·a mm. At 20 mm/px the line opacity is 0.10·(w/0.2)^0.7, capped at 0.75. A 0.55 mm crack therefore draws at about 0.2 opacity: "too faint".
- **Short cracks:** corner cracks are capped at 2.5 m, and panel cracks at their storey band. So nothing reads as a multi-storey structural line.
- **No loss beside cracks:** delamination spalls are placed by edge proximity, a bar-line pattern and the cause field, independent of the crack paths. Serious cracks therefore have no missing surface beside them.
- **Fix:**
  - At 0.5 and above, take length from long chains instead of webbing.
  - Let the widest crack follow the JBDPA classes.
  - Couple spalls to the crack graph.
  - The algorithm is in §3.4; the rules in §6.

---

## 3. Algorithms that generate crack patterns (topic B)

Fit codes:
- **(a)** practical in numpy on a 3000 × 1500 px facade raster, in seconds to a minute (possibly on a 10 cm grid of 600 × 300 cells)
- **(b)** practical in Houdini VEX or SOPs
- **(c)** needs a dedicated solver or GPU

All fit judgments are [I].

### 3.1 Physically based

| Method | Patterns it produces | Reported cost | Fit | Source |
|---|---|---|---|---|
| LEFM with FEM and local remeshing (O'Brien & Hodgins 1999) | Cracks split nodes on a plane perpendicular to the largest eigenvector of a "separation tensor". Few cracks at high toughness, networks and shattering from strong impacts. One element per step; sharp turns cause spurious cracks. | 75–6,667 min per simulated second on a 195 MHz SGI (1999) | (c). The useful idea (crack ⟂ σ1) carries over to tracing. | [S 23] |
| Ductile FEM fracture (O'Brien, Bargteil & Hodgins 2002) | Adds plasticity to the 1999 method | not checked | (c) | [S/2 24] |
| Smeared vs discrete crack FEM for concrete; crack tracking | Smeared: diffuse damage bands. Discrete or tracked: single clean cracks at low cost. | — | (a) only as a coarse static solve; heavy without scipy | [S/2 25] |
| XFEM (Moës, Dolbow & Belytschko 1999; graphics: Kaufmann 2009, Koschier 2017, Chitalu 2020) | A few dominant cracks cut through elements without remeshing; paths from stress-intensity or tangential-stress criteria | one sparse solve per crack increment | (a) feasible, but heavy to write; (c) in 3D | [S 26; S/2 27] |
| Phase-field fracture (Bourdin–Francfort–Marigo; Miehe 2010; Wu's PF-CZM 2017) | Nucleation, branching and merging emerge with no crack tracking; T-junctions from sequential cracking; cracks are bands of width about ℓ | Element ≤ ℓ/2 to ℓ/5; staggered solves per load step. For one strength, PF-CZM needed ℓ = 3 mm where AT2 needed 72 mm. | (c); (a) only on a coarse grid, minutes to hours, then skeletonise | [S/2 28; S 16] |
| Phase-field corrosion cracking (Korec et al. 2023) | Cracks between bars and from bar to nearest face. Corner spalls when bars are widely spaced relative to cover; delamination when close. The final pattern is set by geometry, not by heterogeneity. | COMSOL, 0.1 mm elements at the bar, 0.6 mm elsewhere; no runtime given | (c) as a solver; its rule is directly usable in (a) | [S 16] |
| Thin-film fracture and debonding (León Baldelli et al. 2014) | Crack-plus-peeling networks in a film | not checked | (a) coarse, for paint flaking; gives networks, not structural cracks | [S/2 29] |
| Peridynamics (Silling 2000; Levine 2014; Chen 2018) | Bonds break at a critical stretch; branchy, noisy cracks | thousands of explicit steps | (a) only coarse; (c) in 3D | [S 30] |
| Random fuse and lattice models (de Arcangelis 1985; Schlangen & van Mier 1992; Grassl & Davies 2011) | Weak disorder gives one rough dominant crack; strong disorder gives diffuse damage. Lattices give tortuous macrocracks with branching and bridging. | one sparse linear solve per broken element | (a) on a coarse grid, burning elements in batches; (b) RBD glue networks are the analogue | [S/2 31] |
| Spring networks (Norton 1991; Hirota et al. 1998, 2000) | A broken spring is a crack; surface contraction gives mud-like T networks; lattice artefacts | not reported | (a) vectorised relaxation | [S/2 32] |
| MPM with continuum damage (CD-MPM, Wolper 2019; AnisoMPM 2020) | Dynamic fragmentation, many pieces; anisotropic damage for wood | examples up to 7.8 M particles | (c); Houdini's MPM solver offline | [S/2 33] |
| Boundary elements (Hahn & Wojtan 2015, 2016; Zhu, Bridson & Greif 2015) | Quasi-static, stress-intensity-driven: a few clean dominant cracks. The 2016 approximation has no branching. | 216–1,328 s per scene for 60–1,099 fragments; 10–35× faster than full BEM (22 min against 13 h) | (c); offline pre-fracture with the open-source FractureRB | [S 34; S/2 35] |

### 3.2 Graphics and procedural

| Method | Patterns it produces | Reported cost | Fit | Source |
|---|---|---|---|---|
| Iben & O'Brien 2006/2009 | A heuristic stress field on a mesh, evolved over time; user parameters give mud, glaze and glass patterns, and set long versus short propagation | timings not checked | (a) a natural port; (b) trace in VEX | [S/2 36; rG-G6] |
| Desbenoit, Galin & Akkouche 2005; Martinet et al. 2004 | Authored crack graphs with cross-section profiles, mapped onto a mesh, swept into a crack volume and carved by Boolean. A few long cracks are easy; growth can be animated. | most template patterns took under 5 min to author | (b) closest to curve → sweep → Boolean in Houdini; (a) for the graph | [S 37] |
| Gobron & Chiba 2001 | Cellular automata on surfaces; semi-physical, controllable; concrete, ceramic, mud, glaze | 10⁵–10⁶ cells, 20 min to hours (2001) | (a) vectorised rules | [S/2 38] |
| Paquette, Poulin & Drettakis 2001, "Surface aging by impacts" (GI 2001, not 2002) | Dents and impact wear, not cracks | hundreds of impacts in seconds | (a) as height stamps (edge chips) | [S/2 39] |
| Paquette, Poulin & Drettakis 2002, paint cracking and peeling | A grid of stress, strength and adhesion. Start in the cell with the highest stress/strength ratio once it passes Sb; grow perpendicular to the maximum stress while it stays above Sc (e.g. Sb = 1.5·Sc); stop below Sc or at another crack, giving a T; relax stress over a distance Dr; width from relaxation. | Wall: 3 min for 30 cracks on 30 k cells (400 MHz, 2002). Door: 75 min for 200 cracks. About 80% of the time is relaxation. | **(a) best fit**: about 1 s here (§3.5); (b) feasible | [S 40] |
| Mould 2005, image-guided fracture | Voronoi regions on a noisy pixel graph by Dijkstra; borders are cracks and follow a guide image; multi-level hierarchy; width grows with distance from the seed | 1000 × 1000 px in about 4.7 s on a 1.8 GHz Pentium | (a) on a 10 cm grid with a heap Dijkstra (seconds, [I]); (b) Find Shortest Path SOP | [S 41] |
| Voronoi fracture (Raghavachary 2002) and recursive tessellations | Y-junction cells of even size; no long cracks unless seeded | trivial | (a); (b) Voronoi Fracture SOP | [S/2 42; rG-G9] |
| Growth vs tessellation generators (Tarasevich et al. 2025, 2026) | Growth reproduces right-angle T-junctions; tessellations match side counts | cheap | (a) | [rG-G9, G10] |
| Valette et al. 2008 | Voxel shrinkage volume for drying soil | not checked | (a)/(c) | [rG-G7] |
| Glondu et al. 2012 | Fits a physically based fracture model to statistics measured from a photo; a user study picks the perceived statistics | interactive preview | (a) the idea: fit our parameters to danchi photo statistics | [S/2 44] |
| Federl & Prusinkiewicz 2004 | FEM on growing two-layer surfaces (bark, mud); cracks above a principal-stress threshold, perpendicular to it | not checked | (a) | [S/2 45] |
| Survey: Muguercia, Bosch & Patow 2014 | Groups methods by approach; the geometric group controls fragment size and shape without the physics | — | — | [S/2 46] |

### 3.3 What decides long dominant cracks versus a network

1. **The load.** One dominant load with stress concentrators gives a few long cracks: restraint of a lift, settlement, rust expansion along a bar, openings. Even shrinkage of a thin layer on a stiff substrate gives networks, with cell size about 3–5 × the layer thickness [rG §7.2].
2. **Start strength versus propagation strength, and the stress shadow** [I←S 40]:
   - A low Sc relative to Sb, and a long relaxation distance Dr, give a few long cracks.
   - A high Sc and a short Dr give dense networks.
3. **Order.** Growing cracks one at a time gives T-junctions; tessellations give Y-junctions [rG-G10].
4. **Consequence** [I]: the same tracer can produce either. So the damage amount should drive the loads (more structure), not the number of seeds (more lines).

### 3.4 Recommendation 1: an analytic stress field and a stress-shadow tracer

Everything in this subsection is [I] unless a source is marked. Fields live on a 10 cm grid; paths are traced at 2 cm.

**Inputs per plane (facade space)**
- **Masks:** wall, openings, slab lines, joints, free edges (building ends, expansion joints), parapets, slab noses.
- **Bar grid:** pitch 0.2–0.3 m both ways.
- **Cover field c(u, v):** mean 22–27 mm, SD 8–10 mm, thinner at noses, drip grooves and external corners [rG §4.1].
- **Strength:** f = 1 + 0.15·n(5 m) + 0.07·n(0.5 m), two noise octaves, × 0.9 on slab and joint lines.

**Load cases.** Each is a 2×2 stress tensor in units of the mean tensile strength; they are summed.
1. **Restrained shrinkage, per lift:**
   - σ_xx = s_sh · R(h) · (1 − e^(−d_free/ℓ)).
   - R(h) = 1 − 0.45·h/h_s, with h the height above the lift's base. CIRIA C766's restraint also falls with height above 0.1 L [S 1].
   - d_free is the horizontal distance to the nearest opening or free edge, and ℓ ≈ 0.6 m (shear lag).
   - Result: vertical cracks in spandrels and solid walls; piers between windows carry less.
2. **Opening corners:**
   - σ_c = s_sh · K_c · (r₀/(r + r₀))^0.455, with tension across the 45° line running away from the opening.
   - r₀ ≈ 0.08 m; reach ≤1 m; only in the quadrant away from the opening [I←S/2 20].
3. **Top storey:** roof-slab expansion near each end gives diagonal tension decaying as e^(−d_end/4 m). This makes the inverted V of rG-J29.
4. **Settlement (story option):**
   - Shear τ_xy ∝ s′(u), the slope of a sag or hog profile.
   - Cracks at ±45° step through window corners.
   - Scale β with the amount: 1/500 at onset to 1/150–1/100 at 1.0 [S/2 19; S 14].
5. **Corrosion (no stress solve):**
   - Crack lines on the bar grid where the carbonation depth X = k·√t reaches the cover c. t is the time since the coating failed [rG §4.1].
   - Width by Vidal's relation [rG-J35].
   - Spall mode by bar spacing over cover: corner spall when wide, delamination when close [S 16].
6. **Earthquake (story option):** shear in spandrels and short piers, giving X pairs [S 3, S 10].

**Tracing, after Paquette et al. 2002 [S 40]**
1. Start in the cell with the largest σ1/f, once it reaches Sb.
2. Grow both ways perpendicular to σ1, in 2 cm steps, with persistence 0.8 toward the field direction and 0.12 rad of noise per step.
3. Stop when:
   - σ1/f drops below Sc, with Sb = 1.5·Sc [S 40]
   - the crack reaches an opening or another crack (a T-junction)
   - it reaches a slab line, unless it is driven hard (σ1/f ≥1.35 at its start)
4. After each crack, multiply the stress by (1 − e^(−d/Dr)) around it.
   - Shrinkage: Dr ≈ 1–1.5 m, which sets the spacing near 1–1.3 h_s.
   - Settlement: Dr ≈ 2–3 m, so a few chains win.
   - Corrosion: Dr ≈ 0.3–0.6 m, the bar pitch.

**Chains**
- Link segments end to end through openings, slab lines and T-junctions: the next segment must start within 0.3 m and turn by no more than 30°.
- Each chain gets an id. "Long structural crack" is measured on chains (§6), because a settlement staircase through five window corners is one crack to the eye.

**Widths**
- **Shrinkage:** w = s_local · R · ε_eff, with ε_eff = 100–250 × 10⁻⁶ [I←S 14].
- **Settlement:** w = 0.3·β·h_p.
- **Corrosion:** Vidal's relation.
- **Profile along a crack:**
  - lift cracks peak at 0.4–0.6 of the lift height [S 1]
  - corner cracks peak at the corner [S 1]
  - tips taper to zero over the last 10–25% [rG C5]
- **Cap by amount:** the widest crack follows the ladder in §2.5.

**Amount and nesting**
- The amount drives the loads and the clock: shrinkage strain, settlement β, corrosion years. It also lowers Sc slightly. It never adds seeds for a web.
- As in round G, draw everything at amount 1 in a fixed order. Each feature stores `amount_on`, and a lower amount keeps a subset. So each step keeps the previous step's damage and grows it.

**Spalls from the graph (texture and geometry use the same list)**
- **Lip spalls** along w ≥1 mm: shares in §2.4 row 1.
- **Cover strips** along corrosion lines where c <25 mm.
- **Plates** where two or more parallel corrosion lines lie within 3 bar pitches.
- **Corner chunks** where a chain meets an external corner or a slab nose.
- **Slab-nose runs.**
- Each spall gets an `amount_on` later than its crack's.

### 3.5 Prototype measurements (scratchpad, not in the repo)

**Setup** (all [I], measured here)
- A synthetic 60 × 14.1 m front: five 2.7 m storeys, a 0.6 m parapet, 1.6 × 1.3 m windows at 3 m pitch, 4 m solid end bays, about 660 m² of wall.
- Load cases 1–3, plus settlement from amount 0.5 in version 2.
- numpy and PIL only; the field on a 10 cm grid, paths at 2 cm.
- Script: `C:\Users\jujun\AppData\Local\Temp\claude\C--Users-jujun-DEV-hocus-pocus\d956ad22-ff1d-47a8-a6c1-b1930b7bee4a\scratchpad\sd-proto\sd_proto2.py`.

| Version | a | Cracks | Total length | ρ (m/m² wall) | Median / p90 / max segment | Share of length in segments ≥1 storey | Time |
|---|---|---|---|---|---|---|---|
| v1: no slab stops, weak noise | 0.25 | 47 | 65 m | 0.10 | 1.38 / 1.92 / 2.76 m | 0.04 | 1.12 s |
| v1 | 0.5 | 64 | 103 m | 0.16 | 1.49 / 2.38 / 5.30 m | 0.16 | 0.86 s |
| v1 | 0.75 | 82 | 158 m | 0.24 | 1.52 / 2.42 / 14.3 m | 0.33 | 0.94 s |
| v1 | 1.0 | 90 | 196 m | 0.29 | 1.54 / 3.59 / 14.3 m | 0.44 | 1.02 s |
| v2: slab stops, noise 0.12 rad per step, corner reach 1 m, settlement | 0.25 | 40 | 44 m | 0.07 | 0.94 / 1.46 / 2.58 m | 0.00 | 1.14 s |
| v2 | 0.5 | 59 | 76 m | 0.11 | 1.10 / 1.60 / 4.26 m | 0.09 | 0.82 s |
| v2 | 0.75 | 82 | 129 m | 0.19 | 1.16 / 2.70 / 4.60 m | 0.21 | 0.76 s |
| v2 | 1.0 | 105 | 175 m | 0.26 | 1.46 / 2.50 / 14.5 m | 0.15 | 0.90 s |

**What the images showed**
- At 0.5: short cracks under sills and at window corners, a thermal diagonal at the top end bay, and a few verticals. That is the 1957 survey's picture [rG-J29].
- At 1.0, version 2: settlement cracks step diagonally from window corner to window corner over three to five storeys, plus one 14.5 m vertical crack in a solid end bay. This reads as structural.
- Its segment share fell to 0.15 because each staircase is cut into storey-long segments at the openings. **Long-crack rules must count chains, not segments.**

**Failure modes found, and their fixes**
1. **Ruler-straight lines.** With a uniform σ1 direction and weak noise, cracks ran dead straight across all storeys. A noise of 0.12 rad per 2 cm step, with persistence 0.8, fixed it; the target tortuosity is 1.03–1.15 [rG C14].
2. **Bracket-shaped spandrel cracks.** Symmetric corner fields at both ends bent spandrel cracks into "( )". Shortening the reach to 1 m helped. Better: make one corner per opening dominant, after the 1957 V pattern.
3. **Every bay alike.** Under settlement, every spandrel cracked in parallel. Vary the settlement field by bay and lengthen Dr for settlement so that a few chains win.
4. **Bounds bug.** Negative indices briefly drew false full-height lines. Keep the gate's check that no crack crosses an opening [rG C16].
5. **Density.** The structural layer alone gives 0.07–0.26 m/m². Hairlines and short shrinkage cracks at low widths would add perhaps 0.3–0.6 m/m². That is inside the survey range [S 12] without any webbing.

### 3.6 Recommendation 2: authored chains and an optional coarse solve

- **Hero and authored cracks:** route a chain between chosen points with noise-weighted shortest paths, as in Mould 2005 [S 41]. Examples: a settlement staircase from a chosen corner, or a crack the level designer wants.
  - In numpy, a heap Dijkstra on the 10 cm grid (about 84 k cells for this front) should take seconds [I, not measured].
  - In Houdini, use Find Shortest Path on a remeshed wall.
  - This is the control Desbenoit et al. offer, with graphs drawn by hand [S 37].
- **Irregular walls:** if the analytic fields prove too crude (stair towers, irregular openings), solve one coarse plane-stress problem with a shrinkage strain on the 10 cm grid. Use matrix-free conjugate gradients in numpy, since scipy is not in the environment. Then trace on that field [I, not measured].
- **Not worth it for textures:** phase-field, peridynamics, MPM and BEM. They buy physical fidelity we cannot see at 2 cm/px, at 10²–10⁵ × the cost (§3.1). They remain references for the geometry side (§4.5).

---

## 4. Pre-fractured and destructible assets, and caching simulated damage (topic C)

### 4.1 Houdini 19.5–22

Doc pages are the current 22.0 set unless noted.

| Node or feature | What it does | Key controls | Version | Source |
|---|---|---|---|---|
| RBD Material Fracture 4.0 (`rbdmaterialfracture`) | Fractures by material: Concrete, Glass, Wood, Metal, Custom | **Concrete:** Fracture Level, Fracture Ratio, scatter from a fog volume; Chipping (Enable, Ratio, Corner Ratio, Corner Depth, Directional Noise); Edge Detail (Detail Size, Noise Height, Element Size, Lacunarity); Interior Detail (Noise Amplitude). **Constraints:** Primary Strength, Level Multiplier, Chipping Strength, Strength Variance, switch to soft constraint when broken. **Glass:** radial and concentric cracks. **Custom:** cutting geometry with inside, interior-seam and exterior-seam groups. | 4.0 since 22.0; flat and curved glass modes in H20; metal bending and tearing in H22 | [S 56, S 57, S 59] |
| Voronoi Fracture 3.0 | Cells around input points; interior surfaces, inside and outside groups, piece names | Cut Plane Offset, Create Interior Surfaces, Name Attribute | 3.0 since 22.0. H22's Voronoi Split uses Clip 2.0, which SideFX calls significantly faster. | [S 60, S 57] |
| Boolean Fracture | Fractures with **cutting surfaces**; outputs pieces **and** constraint geometry; interior and exterior seam groups. No noise of its own (use RBD Interior Detail). | — | since 17.0 | [S 61] |
| RBD Interior Detail | Subdivides and displaces interior faces by depth or an SDF | Detail Size, noise, depth method, clamp to depth | since 17.0 | [S 62] |
| Edge Fracture | Cuts along existing edges with curves as guides: thin surfaces such as glass panes and partition boards | Initial Pieces, Point Cost Attribute | since 17.0 | [S 63] |
| VDB Fracture | Cuts level-set VDBs with closed cutters | — | since 12.5 | [S 64] |
| RBD Constraint Properties | Glue, soft and hard constraints. Glue: Strength (−1 never breaks), Strength Variance, Half-Life, Propagation Rate and Iterations. Soft: stiffness, damping, plasticity. | Geometry Attribute Transfer scales parms by attributes painted on the geometry. H22 can paint constraint behaviour as attributes on the source geometry. | since 17.0 | [S 65, S 57] |
| Glue Constraint Relationship DOP, Constraint Network DOP | Strength is the glue bond's strength. Hits accumulate impulse that decays with the half-life; Bullet only. Primitive attributes override constraint properties, and float attributes multiply them. Broken constraints go to the group `broken`; `next_constraint_name` switches glue to soft on break. | Strength's units are not stated. That it is an impulse threshold is implied, not stated. | — | [S 66, S 67] |
| RBD Constraints from Rules / Lines / Curves; Connected / Disconnected Faces; RBD Cluster; RBD Configure; RBD Bullet Solver (SOP); RBD I/O | Build constraints; detect separation; cluster pieces; pack and set attributes; simulate in SOPs; pack, save and reload fractured geometry | — | — | [S 68] |
| H20–H21 additions | H20: sticky collisions, RBD Group Constraints, Cone Twist properties, min activation impulse. H21: RBD Car Fracture; overlap memory −20–30%; first frame about 20% faster. | — | H20, H21 | [S 59, S 58] |

**Measured in this repo** (H22.0.466, `procedural-mesh-damage/references/techniques.md`) [S 77]:
- RBD Material Fracture, concrete: 25 pieces in 1.9 s; with chipping and edge detail, 52 pieces and 20,650 triangles.
- Subtracting chosen pieces from the reference gives a closed piece. Deleting pieces and fusing the rest gave 8,763 non-manifold edges.
- Voronoi Fracture, 30 cells: 0.02 s.

### 4.2 Caching and export to games

- **File Cache 2.0:** versioned `.bgeo.sc` caches [S 69]. **RBD I/O** packs and caches fractured geometry [S 68].
- **Labs RBD to FBX 3.0:** a packed RBD sim becomes a bone-animated FBX with a flat hierarchy, converted to centimetres [S 72]. A forum fix says it writes an empty file unless RBD Configure sits before the Bullet solver [S/2 72].
- **Labs Vertex Animation Textures 3.1** [S 73]:
  - modes for soft bodies, **rigid bodies**, remeshing, particles and bones
  - shaders ship for Unreal (a Labs content plugin per UE version) and Unity; Godot is not supported
  - rigid mode needs point angular velocity `w` and 4–6 UV channels
  - textures well over 4096 px can glitch in Unreal; HDR EXR is recommended
- **Other Labs tools** [S 68]:
  - Destruction Cleanup: removes redundant geometry and fixes normals before export
  - RBD Edge Strip: polystrips on fracture edges
  - Inside Face UVs
  - Static Fracture Export: splits a static fracture into object-level containers
- **Houdini Engine for Unreal to Chaos Geometry Collections** [S 74 ✓]:
  - Pieces are packed primitives with primitive int `unreal_gc_piece`, the cluster level. 0 means off; levels must be contiguous.
  - `unreal_gc_cluster` is the cluster index within a level. `unreal_gc_name` splits the output into several collections.
  - Pack with `name_gc`, because RBD nodes overwrite `name`.
  - Detail attributes: `unreal_gc_clustering_damage_threshold`, collision type, implicit type (box, sphere, capsule, level set, convex) and mass. UE5 adds a connection type and size-specific collision arrays.
  - Full control of the hierarchy is not supported. Needs UE 4.26+ with Chaos.
- **FBX, Alembic and glTF:**
  - The Filmbox FBX ROP exists as a SOP; how it writes packed pieces was not verified [S 70].
  - The output-level ROPs are named "Filmbox FBX" and "Alembic" [S 70]. An Alembic sim can go to Unreal as a Geometry Cache; I did not verify that import path this session [?].
  - The glTF ROP exports packed primitives and instances, and writes the `name` attribute of packed prims [S/2 71]. Use it for Godot.
- **HoudiniNiagara:** reads point caches into Niagara. Its README targets UE 5.4, and a 5.7 branch exists; there is no rigid-piece workflow [S 75].
- **Tutorials:**
  - SideFX's "Realtime Destruction Techniques" (2025): a low-res RBD drives a high-poly mesh, with VAT for varying piece counts [S/2 76].
  - "Destruction FX for Realtime": building fracture to VAT [S/2 76].

### 4.3 Unreal Engine 5: Chaos Destruction

- **Geometry Collection:** the container for pieces and their simulation properties, built from static meshes [S 78].
  - Clustering uses a connection graph with a strain per link. Impacts or fields above the strain break links [S 78].
- **Fracture Mode** (Shift+6), **Generate → New** from selected static meshes [S 79, S 80]:
  - Tools: Uniform, Cluster, Radial, Planar, Slice, Brick (experimental), Mesh, Custom.
  - Options: noise, grout, chance to fracture. Each fracture adds a level.
  - So pieces cut in Houdini and imported as separate meshes can be turned into a collection. Whether their levels survive, rather than being rebuilt, is not stated [S 80; ?].
- **Properties** (Python API, 5.7) [S 81]:
  - clustering and damage: `enable_clustering`, `max_cluster_level`, `damage_threshold` (one per level), `use_size_specific_damage_threshold`, `damage_model`, `damage_propagation_data`
  - removal: `remove_on_max_sleep`, `maximum_sleep_time`, `removal_duration`
  - rendering: `enable_nanite`, `root_proxy_data` (a static-mesh stand-in until the first break), `strip_render_data_on_cook` (for the ISM pool)
  - authoring: `dataflow_asset`
- **Chaos Cache Manager** (plugin ChaosCaching, marked Experimental) [S 82]:
  - records a destruction sim to a Cache Collection and plays it back, starting from BeginPlay or a trigger
  - its start time is exposed to Sequencer
  - a packaged-build bug with Nanite collections was fixed in May 2025 [S/2 83]
- **Budgets:** no Epic numbers found.
  - Community practice: fracture into fewer pieces, spawn small debris as Niagara particles from break events, and remove pieces on sleep [S/2 84].
  - Proposed starting budget [I, to measure]:
    - 30–150 leaf pieces per bay-sized collection, 2–3 levels
    - convex collision on large pieces, boxes or spheres on debris
    - a root proxy until the first break
    - remove on sleep after 5–15 s

### 4.4 Godot 4.x

- **No built-in destruction or fracture.** I found no official statement either way; a university project states it has none [S/2 93].
- **Jolt:**
  - built in since 4.4, marked experimental [S 85]
  - the default for new 3D projects from 4.6, no longer experimental; existing projects keep their settings [S 86 ✓]
  - enabled under Physics › 3D › Physics Engine [S 87]
  - the older godot-jolt extension is in maintenance mode [S 88]
  - body limit setting `max_bodies`, default 10,240 [S/2 88]
- **Pre-fractured swap:** Jummit's Destruction add-on puts a Destruction node on the intact object, points `Fragmented` at a pre-fractured scene, and calls `destroy()` [S 89].
  - Its shards come from Blender's Cell Fracture. Our pieces can come from Houdini through the glTF ROP instead.
- **Runtime fracture add-ons:**
  - VoronoiShatter: Voronoi fracture of convex and concave meshes at runtime; Godot 4.6, MIT [S 90]
  - ShatterKit: paid, Godot 4.7+ [S/2 91]
- **VAT:** no official support. The community Godot_VAT3 port provides SideFX VAT3 soft, rigid, remesh and particle shaders, with a Godot preset for the Labs ROP [S 92].

### 4.5 Research on precomputed and realtime fracture: what each buys a game pipeline

| Work | What it does | Cost | What it buys us | Source |
|---|---|---|---|---|
| Sellán et al., "Breaking Good: Fracture Modes for Realtime Destruction" (arXiv 2111.05249; ACM TOG) | Precomputes the k lowest-energy fracture modes of a shape by a sparsity-regularised eigenproblem on a tet cage. At runtime, one projection of the impact picks which faults open. Non-convex pieces follow structurally weak zones; 10–500 pieces. Brittle only; no crack propagation or secondary fracture. | 0.63–11.6 s per mode (about 6–116 s per shape) on a 2020 laptop; **1–2 ms per impact** at runtime on CPU | Impact-dependent breaking from one precomputed table per piece type. Needs a runtime that activates precut pieces, which Chaos clusters approximate. | [S 48] |
| Breaking Bad dataset (NeurIPS 2022) | Over 1 M fractured objects from 10 k shapes, made with fracture modes | — | Training data, not a runtime method | [S 49] |
| Müller, Chentanez & Kim 2013, volumetric approximate convex decompositions | Real-time fracture of large objects by clipping convex pieces against impact-aligned patterns | not verified | Variety without per-object pre-fracture; needs a custom runtime with convex splitting, which stock Chaos and Godot lack | [S/2 50] |
| Schvartzman & Otaduy 2014 | Fracture surfaces from high-dimensional Voronoi diagrams, at interactive rates | not verified | Faster physically guided pre-fracture variants | [S/2 51] |
| Hahn & Wojtan 2015, 2016 | Boundary-element brittle fracture; the 2016 approximation is 10–35× faster | minutes to hours offline | High-quality offline pre-fracture variants; code available | [S 34] |
| Parker & O'Brien 2009 | Runtime corotational FEM with "splinters"; shipped in Star Wars: The Force Unleashed | not verified | Proof that runtime FEM ships, but it needs middleware | [S/2 52] |
| Su, Schroeder & Fedkiw 2009 | "Prescores" space once: a stored fracture pattern is moved to the impact and intersected with the body | a 25-piece break at an average 22 fps on one 3 GHz core (2009) | Bake a few impact-centred pattern variants per piece type and pick at runtime | [S 53] |
| Bao, Hong, Teran & Fedkiw 2007 | Quasi-static stress solve at impact for rigid bodies | offline | Plausible crack placement for pre-fracture | [S/2 54] |
| DeepFracture (Huang & Kanai, 2023/2025) | A per-shape network trained on BEM runs maps an impact to fragments | faster than simulation | Per-shape training; not needed for us | [S/2 55] |
| Production examples | The Finals (Embark, GDC 2024): server-side environmental destruction. Rainbow Six Siege (GDC 2016): RealBlast. | — | Context only; the talks were not read | [S/2 94, 95] |

**What fits this project** [I]
- **Game-side behaviour:** precut damage states (intact, damaged, destroyed) as mesh swaps, plus Chaos collections for the few objects that must break at runtime.
- **Set-piece collapses:** cache them in Houdini and play them back (Chaos Cache Manager, VAT, or bones).
- **Research methods** (fracture modes, BEM) are optional offline generators for better piece shapes. They are not runtime systems we need.

---

## 5. Recommended pipeline (topic D)

### 5.1 One crack graph drives both sides

The numpy generator writes one graph per building. Coordinates are facade metres on the same planes as the rasters, with u along the wall and v down from the top, as in the round-G rasters. Houdini reads the same file. All of this is [I].

```json
{
 "version": 1, "units": "m", "ppm": 50, "seed": 1234,
 "planes": [{"id": "front_S", "origin": [0, 14.6, 0], "u": [1, 0, 0], "v": [0, -1, 0], "n": [0, 0, 1],
             "size": [60.0, 14.6]}],
 "bars": {"pitch": [0.25, 0.25], "dia_mm": 13, "cover_field": "cover_front_S.npy"},
 "cracks": [{"id": 17, "plane": "front_S", "kind": "shrinkage|corner|settlement|shear|corrosion|joint|map|hairline",
             "gen": 1, "chain": 4, "amount_on": 0.42, "ends": ["T:12", "free"],
             "pts": [[12.30, 8.41], [12.31, 8.43]], "w_mm": [0.6, 0.7], "depth_mm": [40, 40]}],
 "spalls": [{"id": 5, "plane": "front_S", "crack": 17, "kind": "lip|cover|plate|corner|nose",
             "amount_on": 0.63, "outline": [[12.2, 8.5], [12.4, 8.5], [12.4, 8.6]], "depth_mm": 35,
             "bars": [[[12.20, 8.55], [12.45, 8.55]]]}]
}
```

- **One source of truth.** Rasters (albedo, height, masks) are drawn from the graph. Geometry cuts are built from the same polylines and outlines. Neither side invents damage the other cannot see.
- **Nesting.** A damage state at amount a keeps the features with `amount_on` ≤ a. The 0.5 variant's spalls are therefore a subset of the 0.75 variant's, as K2 and the round-G nesting expect.
- **Gate.** The gate measures chains, widths and spall coupling from the graph (§6), and cross-checks them against the rasters.

### 5.2 Texture side (numpy generator)

1. **Graph:** run the tracer of §3.4. Keep round G's hairlines for amounts up to 0.5 and for close-ups. Drop facade-scale pattern cracks, except under an ASR story.
2. **How a structural crack reads at 20 mm/px.** A 0.3 mm crack is sub-pixel, and even a 3 mm crack alone shifts the pixel by only about 4 L* [rG §3.1]. So draw what the crack carries:
   - **Dirt and wet halo:** 2–6 mm each side, darker below the crack [rG §3.2].
   - **Lip spalls (w ≥1 mm):** 10–50 mm pieces of exposed coat and concrete, dark in their cavities. This is where the line reaches 2–3 px.
   - **Groove in the height map (w ≥2 mm):** 5–20 mm deep, so the baked normal and AO show it [rG §3.6].
   - **Rust bleed** from corrosion lines, and **efflorescence** at joints and soffits [rG §3.3–3.4].
3. **Missing surface:** stamp the graph's spalls into the existing break machinery (sharp outline, recessed floor, aggregate, bar and rust), which K4 already checks. The K5 area budget is then filled mainly by crack-borne spalls at 0.75 and above.
4. **Close-ups (1 mm/px):** draw the crack core at true width as sub-pixel coverage, chipped lips, and sharp, aggregate-rich spall floors.
5. **Outputs:** the existing albedo, height (`dmg_h`) and masks, plus `crack_graph.json`.

### 5.3 Geometry side (Houdini 22)

**Mapping.** A Python SOP reads the graph. Each point goes to P = origin + u·U + v·V on the plane, and is snapped to the mesh with `xyzdist`/`primuv`. Features are kept by `amount_on` for the chosen state.

**Damage states per modular piece and per building**

| State | Geometry change | How | Budget | Engine use |
|---|---|---|---|---|
| Intact | none | — | as now: a balcony bay with props ≤3,500 triangles | static mesh |
| Damaged (bake from 0.5–0.75 graphs) | spalls and chunks ≥3–5 cm deep at noses, corners and parapet tops; bars in deep spalls; grooves only for cracks ≥3 mm | cutters from the outlines (inset hull or noisy extrusion), Boolean subtract with **unpacked** cutters, UV transfer, cut-face group for a "broken interior" material, swept bars (the skill's workflow, steps 3–9) | ≤1.5× intact [I] | per-bay variants chosen by the graph; texture carries the rest |
| Destroyed (1.0 graph; unique hero or ruin buildings) | pieces split along the long chains; chips near cracks; missing nose runs; bent rails; broken glass | cutting surfaces: each chain ≥1 mm swept through the wall thickness and noised (RBD Interior Detail), then **Boolean Fracture** for pieces and constraints. Secondary RBD Material Fracture (concrete, chipping and edge detail) near the chains. Glass mode for panes; H22 metal for rails. | pieces ≤3× intact triangles; 30–150 leaf pieces per bay wall [I] | static ruin mesh, or a Chaos collection, or a cached collapse |

**Constraint network from the graph** (for destroyed and runtime pieces)
- Glue between pieces on either side of a crack is weakened by its width, e.g. strength × max(0.1, 1 − w/3 mm). The rest keep full strength [I].
- Apply it through Geometry Attribute Transfer, or a float primitive attribute on the constraints that multiplies Strength [S 65, S 67].
- Use RBD Material Fracture's Level Multiplier for chips [S 56].
- Simulate with RBD Bullet Solver, triggered by removing a support or an impulse. Cache with File Cache or RBD I/O [S 68, S 69].

**Modular seams**
- Graph features within the 0.15 m seam margin stay texture-only, unless the cut is made once on the assembled facade.
- Destroyed buildings are unique meshes, so seams do not matter there [I; skill principle 6].

**LODs:** branch damage after the LOD split. Drop cuts under 5 cm for LOD1. Keep silhouette breaks only to the last LOD that shows them (skill traps).

**Validate** with `damage_validate.vfl`: 0 open and 0 non-manifold edges, seams unchanged, UVs on every cut face, triangles within budget. Then check rule K20 (§6).

### 5.4 Engines

- **Unreal 5:**
  - Intact and damaged states are static meshes (Nanite optional).
  - Runtime-breakable elements, such as a stair-tower wall or a balcony slab, become Geometry Collections. Use Houdini Engine with `unreal_gc_piece` = 1 for chain pieces and 2 for chips, and `unreal_gc_cluster` per chain region [S 74]. The alternative is FBX pieces, then Fracture Mode, Generate → New [S 80].
  - Set damage thresholds per level from crack widths: lower for pieces cut by wide cracks [I]. Use a root proxy and remove on sleep [S 81].
  - Set-piece collapses: Chaos Cache Manager (experimental), VAT 3.1 rigid, or Labs RBD to FBX bones [S 82, S 73, S 72].
- **Godot 4:**
  - Intact and damaged states are mesh variants.
  - Breakables are pre-fractured scenes from the glTF ROP, swapped in at break time, as in the Destruction add-on, with Jolt rigid bodies [S 71, S 86, S 89].
  - Canned collapses use the community VAT3 shaders [S 92].
  - Keep active bodies to hundreds; the 10,240 limit is a ceiling, not a budget [S/2 88; I].

### 5.5 What to build first

1. **Crack graph and chain measures** in numpy: the schema of §5.1, the writer, and gate readers for K12–K14 and K18. Test them on saved round-G builds before any rebuild, as round G's lessons advise.
2. **Stress-field tracer** (§3.4) in a copy of the generator. Replace pattern cracks at amounts above 0.35, keep hairlines, add the settlement story. Tune on one front by emulating the sweep (splice the layer at each step).
3. **Crack-coupled spalls:** lip spalls, cover strips, plates, corner chunks and nose runs, inside the K5 budget, with bars from the grid. This answers "no chunks missing" and "surface fallen off".
4. **Visibility for w ≥1 mm:** halo, lips and groove. Then the K19 check, and the change to K10's top band.
5. **Houdini damaged variants** for `bal_front` and the end wall, from the graph's spalls and chunks, validated with the skill's scripts.
6. **One destroyed section** (an end wall with its stair tower): Boolean Fracture along the chains, chips, a weakened glue network, Bullet, cache. Then the round trip to Unreal (Houdini Engine collection plus Cache Manager) and to Godot (glTF pieces plus swap).

---

## 6. Proposed rules (topic E)

### 6.0 Conventions

- Family `damage`; bands at amounts 0.25 / 0.5 / 0.75 / 1.0, linear between, like K5 and K7.
- **Origins:** U = user (review), P = photo measurement, L = literature, C = construction (the rulebook's `about` calls C a craft estimate). Derived values are marked [I].
- **"Chain":** crack segments of width ≥0.2 mm linked end to end through T-junctions, openings and slab lines. The next segment starts within 0.3 m and turns ≤30°. Measured from the generator's crack graph.
- **"Storey":** 2.8 m (h_s).
- **"Webbing":** map or pattern-network cracks, plus hairlines under 0.2 mm that are shorter than 0.5 m.

### 6.1 New rules

| ID | Title | Measure | Pass | Origin |
|---|---|---|---|---|
| K12 | High damage is carried by long cracks | Share of the length of cracks ≥0.2 mm that lies in chains of ≥1 storey, exposed walls pooled | ≥0.20 at 0.5; ≥0.40 at 0.75; ≥0.50 at 1.0; no bound at 0.25 | U ("longer structural cracks"); L (ladders escalate by width and loss, not count [S 2–S 8]); I (bands; the prototype reached 0.21–0.44 on segments before chaining) |
| K13 | Long cracks are long enough, and few | Per front: the longest chain; the 90th-percentile chain; chains of ≥1 storey per 100 m² of wall | Longest ≥0.5 / 1 / 2 / 3 storeys at 0.25 / 0.5 / 0.75 / 1.0. p90 ≥0.5 storey from 0.75. Chains ≥1 storey per 100 m²: ≥0.5 at 0.5, ≥1 at 0.75, ≥2 at 1.0, and ≤8 at any amount. | U; L (lift cracks run the full lift [S 1]; settlement chains cross storeys through openings [S 14]); C (storey 2.8 m, bay 6 m); I (bands) |
| K14 | The webbing stays small | Webbing length ÷ length of chains ≥0.5 storey; map-cracked area share | Ratio ≤2.0 at 0.25, ≤1.0 at 0.5, ≤0.5 at 0.75, ≤0.3 at 1.0, and from 0.5 never above the step below. Map-cracked area ≤3% of the wall at every amount, unless an ASR story tag is set. | U ("less of the cracking webbing"); L (Otaru: map cracking under 3% is the best grade, ≥30% the worst [S 15]); I |
| K15 | Serious cracks shed surface | (a) Share of crack length with missing surface (break coverage ≥0.5, depth ≥5 mm) within 0.1 m, by width class. (b) Share of spalled area within 0.2 m of a chain ≥0.5 mm or a bar-line crack. | (a) <0.5 mm: ≤2%; 0.5–1 mm: ≤10%; 1–2 mm: 5–25%; ≥2 mm: 25–60%. (b) ≥0.5 at amounts ≥0.5; ≥0.6 at 1.0. | U ("some of the surface missing/fallen off"); L (JBDPA III slight spalling, IV marked spalling and bars [S 3, S 4]; quick inspection [S 5]; crack → delamination → spall [S 2]); I (shares) |
| K16 | Missing surface reaches facade scale | Spall patches (coverage ≥0.5) per front: equivalent diameter of the largest; patches ≥0.3 m per 100 m² of wall; share of spalled area in plates (patches ≥0.1 m² bounded by bar-line cracks) | Largest: ≤0.15 m at 0.25; 0.15–0.4 m at 0.5; 0.4–1.0 m at 0.75; 1.0–2.5 m at 1.0. Patches ≥0.3 m per 100 m²: 0 / ≤0.5 / 1–5 / 5–20. Plate share: 0 / ≤0.2 / 0.2–0.5 / 0.3–0.7. | U ("no chunks missing"); L (large spall >150 mm [S 2]; Shime 5–10 cm flakes, 3.7–9.9% [rG-J25]; Otaru's worst grade ≥20% spalled or delaminated [S 15]; plates when bars are close [S 16]); I |
| K17 | Bars show where cover failed | Exposed bar length per m² of wall; share of spalls ≥20 mm deep that show a bar; share of exposed bar where the cover field is under 25 mm; bar geometry | Exposed bar: 0 at ≤0.25; 0.002–0.03 m/m² at 0.5; 0.01–0.18 at 0.75; 0.06–0.6 at 1.0. Deep spalls with a bar ≥50% at 0.5, ≥70% at 1.0. ≥90% where cover is under 25 mm. Bars on the 0.2–0.3 m grid within ±2 cm and ±5°, continuous across the spall. | L (MLIT Level 3 includes exposed bars [rG-J1]; Shime: exposure only under 25 mm cover [rG-J25]; Hashima IV, bars largely exposed [rG-J24]); C (D10–D13 at 200–300 mm); I (rates = rG S8 × K5 bands) |
| K18 | Each step adds structure, not just lines | Between steps of 0.25, from 0.25: (a) Δ(length in chains ≥1 storey) ÷ Δ(total crack length ≥0.05 mm); (b) the widest crack's class (I <0.2, II 0.2–1, III 1–2, IV >2 mm); (c) the count of crack-borne spalls (K15b) | (a) ≥0.5 for 0.25→0.5; ≥0.7 for 0.5→0.75 and 0.75→1.0. (b) I–II at 0.25, II at 0.5, III at 0.75 (IV allowed on story cracks), IV at 1.0. (c) ×≥1.5 per step from 0.5. | U (the review; K2's "each step shows"); L (JBDPA classes [S 3, S 4]); I |
| K19 | Serious cracks read at facade scale | At 20 mm/px: median ΔL* of the crack line, including halo, lips and groove, by class; share of the length of chains ≥1 storey with ΔL* ≥6 | 1–2 mm: ΔL* 10–18. ≥2 mm: 14–28, with a dark core 2–3 px wide where lips are chipped. Chains: ≥60% at 0.75, ≥80% at 1.0. Hairlines stay ≤3 (K10). | U ("Too faint"); L (pixel arithmetic: an open 3 mm crack alone gives about ΔL* 4 at 20 mm/px [rG §3.1]); I |
| K20 | Texture and geometry share one crack graph | On each damaged or destroyed variant mapped to facade space: (a) share of fracture-seam and chunk-outline length within 4 cm (2 px) of a graph crack ≥0.5 mm or a spall outline; (b) share of geometric losses ≥0.2 m on a graph spall site; (c) share of graph spalls ≥30 mm deep at noses and corners that have a geometric counterpart in the variant meant to show them | (a) ≥0.9; (b) 1.0; (c) ≥0.8 | U ("simulate it"; destructible assets); C (one graph drives both); I |
| K21 | Chunks at corners and slab edges | Share of slab-edge and external-corner length with loss ≥30 mm deep and ≥150 mm long; count of chunks ≥0.2 m per 10 bays | Length share 0–0.5% / 0.5–2% / 2–8% / 10–30% at 0.25 / 0.5 / 0.75 / 1.0. Chunks ≥0.2 m: ≥1 per 10 bays at 0.5, ≥5 at 0.75, ≥15 at 1.0. | U ("there's no chunks missing"); L (corner and nose spalls rank first [rG §4.3]; corner spalls with widely spaced bars [S 16]); I (rG S12, never adopted as a K rule) |

### 6.2 Changes proposed to existing rules (the lead decides)

These are driven by new evidence and the art director's direction, not by a build failing. Round G's lesson stands: do not loosen a rule just to make a build pass.

- **K7, crack length.** Keep the 0.25 and 0.5 bands.
  - At 0.75: total length 0.7–1.6 m/m², and 0.2–0.6 m/m² for ≥0.3 mm.
  - At 1.0: total 0.8–2.0 m/m², and 0.3–0.9 m/m² for ≥0.3 mm.
  - Why: real blocks carry 0.5–2.5 m/m², mostly under 0.3 mm [S 12]. Otaru's worst grades sum to about 0.3–0.5 m/m² of ≥0.2 mm cracks [S 15]. The current 1.5–3.5 m/m² is met with webbing, which K14 now limits.
  - The median-width band can stay: long chains at 1–10 mm raise the median.
- **K8, orientation.** With the settlement and corrosion stories on at 1.0, allow vertical 35–60%, diagonal 20–45% and horizontal 10–30% [I].
- **K10, visibility.** Replace the ≥1 mm band (8–20) with K19's classes. Keep the hairline cap of ≤3.
- **K5, spalled area.** Keep the bands, and require from 0.75 that at least half of the area is crack-borne (K15b).
- **K6, spalls start at edges.** Keep it. Cover strips along slab noses and corners count as edge spalls, so K6 and K15 agree.

---

## 7. Not found, and what to search next

| Gap | Status | Next step |
|---|---|---|
| Crack length and type shares on real danchi, by age | No survey found. The Otaru grading and a high-rise survey were the closest. | J-STAGE / AIJ 梗概: 公営住宅 外壁 ひび割れ 長さ 分布; or measure from photos of real danchi (a gate-calibration task, as Glondu et al. did [S/2 44]) |
| Spall sizes at balcony slab noses; exposed bar length per spot | Not found | Repair records: 爆裂 補修 箇所 寸法 バルコニー 先端 |
| Hidden delamination ÷ visible spall | Not re-found (the skill's causes.md quotes 2–3×) | Bridge-deck NDE surveys (Gucunski; FHWA LTBP) |
| FEMA 306 crack widths per component guide; FEMA P-58 wall damage states | The PDF was over the fetch limit | Fetch a smaller copy, or the NIST mirror |
| JBDPA original wording; a separate wall-type table; the 2015 revision | Only via JCI and WCEE papers | JBDPA 被災度区分判定基準 2015 本文 |
| AIJ 2006 shrinkage guideline; JASS 5 inducer-joint wording | Only the 1988 finding via JCI 2018 | AIJ 収縮ひび割れ制御 指針 誘発目地 断面欠損率 |
| Chaos performance budgets (pieces, active bodies) | No Epic numbers found | Unreal Fest talks; profile a test collection |
| Godot official statement on destruction; RigidBody3D performance | Not found | Godot proposals repo; benchmark Jolt with 500–2,000 bodies |
| Müller 2013, Parker & O'Brien 2009, CD-MPM timings | PDFs over the fetch limit or 404 | Author pages |
| Qiao thesis thresholds (S > 6D, C/D < 3) | Snippet only; the repository returned 503 | Retry the Nagoya repository |
| Cracks that link across slab lines on real end walls | No source; inferred from mechanics and photos seen in passing | Photo survey of old end walls |

---

## 8. Sources

✓ = I read the page or PDF in this session. h = read by a helper research pass in this session (it reported link and number). Unmarked = search snippet or another paper's reference list. Numbers S22, S43 and S47 are not used.

**Damage ladders, cracking and spalling**
- S1 ✓ El Khoury, Ridley, Vollum, Forth & Shehzad 2023, Experimental assessment of crack prediction methods in international design codes for edge restrained walls, Structures 55: https://spiral.imperial.ac.uk/handle/10044/1/105494
- S2 ✓ USACE EM 1110-2-2002, Evaluation and Repair of Concrete Structures, ch. 2 (via the CED course copy): https://www.cedengineering.com/userfiles/C05-008%20-%20Evaluation%20and%20Design%20of%20Concrete%20Repairs%20-%20US.pdf
- S3 h Ito, Takahashi & Maeda 2013, residual seismic performance of shear-failing RC members (JBDPA classes), JCI Proc. 35: https://www.data.jci-net.or.jp/data_pdf/35/035-01-2144.pdf
- S4 h Choi & Nakano 2008, 14WCEE, Table 1 (JBDPA 2001 damage classes): https://www.iitk.ac.in/nicee/wcee/article/14_05-04-0005.PDF
- S5 h 応急危険度調査判定マニュアル, RC and SRC chapter (Tottori Prefecture copy): https://www.pref.tottori.lg.jp/secure/281141/02siryou123-29-43-1-6.pdf
- S6 h FEMA 306 (1998), front matter: https://www.atcouncil.org/files/FEMA306.pdf
- S7 h Hanson & Comartin 2000, The repair of earthquake damaged buildings, 12WCEE: https://www.iitk.ac.in/nicee/wcee/article/2596.pdf
- S8 h Grünthal (ed.), European Macroseismic Scale 1998: https://media.gfz.de/gfz/sec26/resources/documents/PDF/EMS-98_Original_englisch.pdf
- S9 h BRE, Assessing cracks in houses (Digest 251 summary): https://bregroup.com/insights/assessing-cracks-in-houses/ · widths (secondary): https://designingbuildings.co.uk/wiki/cracking%20and%20building%20movement
- S10 h Nakamura (BRI), RC building damage in the 2016 Kumamoto earthquake: https://www.kenken.go.jp/japanese/research/lecture/h28/pdf/PT3.pdf
- S11 h UR wall-type rental housing alteration guideline (BRI 建築研究資料 No. 210, appendix 3): https://www.kenken.go.jp/japanese/contents/publications/data/210/f3.pdf
- S12 ✓ (numbers; Japanese labels via helper) Kon, Nagai & Matsui 2015, exterior wall repairs of high-rise apartment blocks, Nihon Univ. P-64: https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.48/pdf/P-64.pdf
- S13 h Hiraiwa & Park 2018, JCI Proc. 40 (cites the AIJ 1988 inducer-joint finding): https://www.data.jci-net.or.jp/data_pdf/40/040-01-1069.pdf
- S14 h Teraoka & Fukuhara 2007, settlement and shrinkage of a 1966 RC school, JCI Proc. 29: https://www.data.jci-net.or.jp/data_pdf/29/029-01-3277.pdf
- S15 ✓ Otaru City, appendix (資料) of a municipal housing plan: deterioration survey procedure and grading sheets for its housing blocks: https://www.city.otaru.lg.jp/docs/2020123000013/file_contents/zentai10.pdf
- S16 ✓ Korec, Jirásek, Wong & Martínez-Pañeda 2023, A phase-field chemo-mechanical model for corrosion-induced cracking in reinforced concrete, arXiv 2306.01903: https://arxiv.org/pdf/2306.01903
- S17 Qiao 2016, Crack patterns of concrete (Nagoya Univ. thesis; snippet only): https://nagoya.repo.nii.ac.jp/record/22925/files/2016-Di_Qiao_Crack_patterns_of_concrete.pdf
- S18 Vu & Stewart 2005, corrosion-induced crack width model up to 1 mm (abstract): https://trid.trb.org/View/794343 · Stewart & Mullard slides (1 mm limit state): https://mrgenci.univ-nantes.fr/medias/fichier/nantes_2016_1477919180951.pdf
- S19 Bjerrum 1963 angular distortion limits, via secondary sources: https://www.koreascience.or.kr/article/JAKO201402757907157.pdf
- S20 Williams 1952 corner singularity; exponent 0.5445 for the L-shaped domain, via arXiv 2101.09828: https://arxiv.org/pdf/2101.09828
- S21 ACI 224R wall joint spacing of 1–3 × height (secondary): https://www.forconstructionpros.com/concrete/equipment-products/repair-rehabilitation-products/article/21952625/how-to-control-concrete-wall-cracks

**Fracture algorithms**
- S23 h O'Brien & Hodgins 1999, Graphical modeling and animation of brittle fracture, SIGGRAPH 99: https://graphics.eecs.berkeley.edu/papers/Obrien-GMA-1999-08/Obrien-GMA-1999-08.pdf
- S24 O'Brien, Bargteil & Hodgins 2002, ductile fracture, ACM TOG 21(3) (DOI not verified): https://doi.org/10.1145/566654.566579
- S25 Rots & Blaauwendraad 1989, Crack models for concrete: discrete or smeared?, HERON 34(1) (no URL verified) · Cervera et al. 2010, crack tracking, Eng. Fract. Mech. 77(13): https://doi.org/10.1016/j.engfracmech.2010.06.013
- S26 Moës, Dolbow & Belytschko 1999, A finite element method for crack growth without remeshing, IJNME 46(1) (from memory; not searched)
- S27 Kaufmann et al. 2009, Enrichment textures for detailed cutting of shells, ACM TOG 28(3) · Koschier et al. 2017, ACM TOG 36(4) (not found) · Chitalu, Miao, Subr & Komura 2020, CGF 39(2): https://doi.org/10.1111/cgf.13953
- S28 Bourdin, Francfort & Marigo 2000, JMPS 48 · Miehe, Welschinger & Hofacker 2010, IJNME 83 · Wu 2017, JMPS 103 (all via reference lists)
- S29 León Baldelli et al. 2014, fracture and debonding of thin films, JMPS 70 (snippet)
- S30 Silling 2000, JMPS 48(1) (not searched) · Levine et al. 2014, SCA · Chen et al. 2018, CGF 37(1): https://doi.org/10.1111/cgf.13236
- S31 de Arcangelis, Redner & Herrmann 1985: https://doi.org/10.1051/jphyslet:019850046013058500 · Schlangen & van Mier 1992, Mater. Struct. 25 · Grassl & Davies 2011: https://arxiv.org/abs/1103.4162
- S32 Hirota, Tanoue & Kaneko 1998: https://doi.org/10.1007/s003710050128 · Hirota et al. 2000, Vis. Comput. 16(7) · Norton et al. 1991, Vis. Comput. 7(4)
- S33 Wolper et al. 2019, CD-MPM, ACM TOG 38(4) · Wolper et al. 2020, AnisoMPM (not verified)
- S34 h Hahn & Wojtan 2016, Fast approximations for boundary element based brittle fracture simulation, ACM TOG 35(4): https://doi.org/10.1145/2897824.2925902 · code: https://github.com/david-hahn/FractureRB · Hahn & Wojtan 2015, ACM TOG 34(4): https://doi.org/10.1145/2766896
- S35 Zhu, Bridson & Greif 2015, Simulating rigid body fracture with surface meshes, ACM TOG 34(4) (DOI not verified)
- S36 Iben & O'Brien 2006, Generating surface crack patterns, SCA · journal version Graphical Models 71(6), 2009: https://doi.org/10.1016/j.gmod.2008.12.005
- S37 h Desbenoit, Galin & Akkouche 2005, Modeling cracks and fractures, The Visual Computer 21: https://perso.liris.cnrs.fr/egalin/Articles/2005-cracks.pdf · Martinet et al. 2004, SMI (snippet)
- S38 Gobron & Chiba 2001, Vis. Comput. 17(5): https://doi.org/10.1007/s003710100099
- S39 Paquette, Poulin & Drettakis 2001, Surface aging by impacts, Graphics Interface: https://profs.etsmtl.ca/epaquette/Research/Papers/Paquette.2001/
- S40 ✓ Paquette, Poulin & Drettakis 2002, The simulation of paint cracking and peeling, Graphics Interface: https://graphicsinterface.org/wp-content/uploads/gi2002-8.pdf
- S41 ✓ Mould 2005, Image-guided fracture, Graphics Interface: https://gigl.scs.carleton.ca/papers/crack.pdf
- S42 Raghavachary 2002, Voronoi fracture on polygonal meshes, SIGGRAPH sketch (no URL)
- S44 Glondu et al. 2012, Example-based fractured appearance, CGF 31(4): https://doi.org/10.1111/j.1467-8659.2012.03151.x
- S45 Federl & Prusinkiewicz 2004, ICCS: https://algorithmicbotany.org/papers/fracture.iccs2004.pdf
- S46 Muguercia, Bosch & Patow 2014, Fracture modeling in computer graphics, Computers & Graphics 45: https://doi.org/10.1016/j.cag.2014.08.006
- S48 h Sellán et al., Breaking Good: Fracture Modes for Realtime Destruction: https://arxiv.org/abs/2111.05249
- S49 h Sellán et al. 2022, Breaking Bad dataset: https://arxiv.org/abs/2210.11463
- S50 Müller, Chentanez & Kim 2013, ACM TOG 32(4): https://doi.org/10.1145/2461912.2461934
- S51 Schvartzman & Otaduy 2014, Fracture animation based on high-dimensional Voronoi diagrams, I3D (DOI not verified)
- S52 Parker & O'Brien 2009, Real-time deformation and fracture in a game environment, SCA: https://doi.org/10.1145/1599470.1599492
- S53 ✓ Su, Schroeder & Fedkiw 2009, Energy stability and fracture for frame rate rigid body simulations, SCA: https://www.cs.ucr.edu/~craigs/papers/2009-energy/paper.pdf
- S54 Bao, Hong, Teran & Fedkiw 2007, Fracturing rigid materials, IEEE TVCG 13(2) (snippet)
- S55 Huang & Kanai, DeepFracture: https://arxiv.org/abs/2310.13344

**Houdini**
- S56 h RBD Material Fracture: https://www.sidefx.com/docs/houdini/nodes/sop/rbdmaterialfracture.html
- S57 h Houdini 22 RBD release notes: https://www.sidefx.com/docs/houdini/news/22/rbd.html
- S58 h Houdini 21 RBD release notes: https://www.sidefx.com/docs/houdini/news/21/rbd.html
- S59 h Houdini 20 and 20.5 RBD release notes: https://www.sidefx.com/docs/houdini/news/20/rbd.html · https://www.sidefx.com/docs/houdini/news/20_5/rbd.html
- S60 h Voronoi Fracture: https://www.sidefx.com/docs/houdini/nodes/sop/voronoifracture.html
- S61 h Boolean Fracture: https://www.sidefx.com/docs/houdini/nodes/sop/booleanfracture.html
- S62 h RBD Interior Detail: https://www.sidefx.com/docs/houdini/nodes/sop/rbdinteriordetail.html
- S63 h Edge Fracture: https://www.sidefx.com/docs/houdini/nodes/sop/edgefracture.html
- S64 h VDB Fracture: https://www.sidefx.com/docs/houdini/nodes/sop/vdbfracture.html
- S65 h RBD Constraint Properties: https://www.sidefx.com/docs/houdini/nodes/sop/rbdconstraintproperties.html
- S66 h Glue Constraint Relationship DOP: https://www.sidefx.com/docs/houdini/nodes/dop/glueconrel.html
- S67 h Constraint Network DOP: https://www.sidefx.com/docs/houdini/nodes/dop/constraintnetwork.html
- S68 h SOP node index (RBD and Labs destruction nodes): https://www.sidefx.com/docs/houdini/nodes/sop/index.html · forum fix for RBD to FBX: https://www.sidefx.com/forum/topic/83494/
- S69 h File Cache: https://www.sidefx.com/docs/houdini/nodes/sop/filecache.html
- S70 h Filmbox FBX ROP (SOP): https://www.sidefx.com/docs/houdini/nodes/sop/rop_fbx.html
- S71 glTF import and export: https://www.sidefx.com/docs/houdini/io/gltf.html
- S72 h Labs RBD to FBX 3.0: https://www.sidefx.com/docs/houdini/nodes/out/labs--rbd_to_fbx-3.0.html
- S73 h Labs Vertex Animation Textures 3.1: https://www.sidefx.com/docs/houdini/nodes/out/labs--vertex_animation_textures-3.1.html
- S74 ✓ Houdini Engine for Unreal, Chaos integration: https://www.sidefx.com/docs/houdini/unreal/chaosintegration.html
- S75 h HoudiniNiagara: https://github.com/sideeffects/HoudiniNiagara
- S76 SideFX tutorials: https://www.sidefx.com/tutorials/realtime-destruction-techniques/ · https://www.sidefx.com/tutorials/destruction-fx-for-realtime/
- S77 Repo: `.claude/skills/procedural-mesh-damage/references/techniques.md` (measured in H22.0.466)

**Unreal Engine**
- S78 h Destruction Overview: https://dev.epicgames.com/documentation/en-us/unreal-engine/destruction-overview
- S79 h Fracturing Geometry Collections: https://dev.epicgames.com/documentation/en-us/unreal-engine/fracturing-geometry-collections-user-guide
- S80 h Destruction Quick Start: https://dev.epicgames.com/documentation/en-us/unreal-engine/destruction-quick-start
- S81 h GeometryCollection Python API (5.7): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/GeometryCollection?application_version=5.7
- S82 h AChaosCacheManager API: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/ChaosCaching/AChaosCacheManager
- S83 Issue UE-252163: https://issues.unrealengine.com/issue/UE-252163
- S84 Community practice (destruction toolkit article): https://80.lv/articles/an-upcoming-destruction-toolkit-made-in-unreal-engine-5

**Godot**
- S85 h Godot 4.4 release: https://godotengine.org/releases/4.4/
- S86 ✓ Godot 4.6 release: https://godotengine.org/releases/4.6/
- S87 h Using Jolt Physics: https://docs.godotengine.org/en/stable/tutorials/physics/using_jolt_physics.html
- S88 h godot-jolt: https://github.com/godot-jolt/godot-jolt · settings (`max_bodies`): https://github.com/godot-jolt/godot-jolt/blob/master/docs/settings.md
- S89 h Jummit, godot-destruction-plugin: https://github.com/Jummit/godot-destruction-plugin
- S90 h VoronoiShatter: https://github.com/robertvaradan/voronoishatter
- S91 ShatterKit: https://indiedevwilliam.itch.io/shatterkit
- S92 h Godot_VAT3: https://github.com/G4ND44/Godot_VAT3
- S93 Carleton University project note (no built-in destruction): https://service.scs.carleton.ca/node/6863

**Games**
- S94 GDC 2024, Engineering Mayhem: environmental destruction in THE FINALS: https://gdcvault.com/play/1034280/Engineering-Mayhem-Technical-Deep-Dive
- S95 GDC 2016, The Art of Destruction in Rainbow Six Siege: https://gdcvault.com/play/1023003/The-Art-of-Destruction-in

Round-G sources cited as rG-Xn are listed in `weathering-cracks-edges-damage.md` §10. They include J1, J3, J8, J10, J15, J24, J25, J29, J30, J35, W3, W5, W7, G6, G7, G9 and G10.
