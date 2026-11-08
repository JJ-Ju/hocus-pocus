# Cracks, edges and damage on aged danchi — research note (round G)

Prepared 2026-10-30 for the weathering and damage generator.

- **Subject:** 1960s–80s reinforced-concrete public housing blocks (JHC/UR and prefectural). Walls are repainted spray-tile (吹付タイル, a multi-layer finish) over concrete. Also covered: balcony fronts and slab edges, steel railings and window frames.
- **Texture scales:** facade space at 50 px/m (20 mm per px), close-ups at 1 mm per px. Both are baked for Unreal and Godot.
- **Geometry:** geometric damage is built separately in Houdini.

**Tags**

| Tag | Meaning |
|---|---|
| **[S]** | A source states it. The source ID links to §10. |
| **[S/2]** | Secondary: a forum, blog, vendor page, search snippet, or a value read off a chart. |
| **[I]** | My inference or estimate. |
| **I←J25** | An estimate anchored on source J25. |

In §10, ✓ marks pages I re-read and checked myself in this session. The rest were read by a delegated research pass that reported the link and the number.

**Coverage**
- Well covered: Japanese standards and repair specifications.
- Not found:
  - surveys of danchi crack density by building age
  - UR's own maintenance specification (its site returned 403)
  - any measurement of arris rounding or chip rate
- The run's shared web-search budget (200 searches) ran out before these gaps closed. §9 lists what a follow-up run should search for.

---

## 1. The numbers that matter most

**Cracks**
- Japanese width thresholds [S J1, J2, J7, J20]:

  | Width | What it marks |
  |---|---|
  | 0.2 mm | Fine-crack limit used for coating repair |
  | 0.3 mm | Hairline limit in condo practice; AIJ outdoor durability limit; MLIT Level 2 starts |
  | 0.5 mm | MLIT Level 3 |
  | 1.0 mm | Where injection repair gives way to U-cut |

  Any crack with rust stain is Level 3.
- Repair stripes that show through repaint [S J10]:
  - U-cut groove: about 10 mm wide × 10–15 mm deep.
  - Injected crack: 30 mm-wide seal with ports every 200–300 mm, inside a 50 mm cleaned band.
  - Elastomeric buffer: 50 mm-wide band, carried ≥50 mm past each crack end.
- Wall joints that cracks are induced to, or follow [S J9, J10]:
  - Vertical joints at column sides and opening edges, plus every 3–4 m.
  - A horizontal joint at every floor.
  - Sealed joints are ≥20 mm wide × ≥10 mm deep.
- Drying-shrinkage cracks run roughly straight, 1.5–6 m apart along long walls. Diagonal cracks start from most re-entrant corners [S W3].
- A 1957 survey of 30+ Japanese RC buildings found [S J29]:
  - cracks under almost all windows
  - a V pattern at the end bays
  - an inverted V near the top, from roof heating
- Crazing cells are ≤40 mm across (12–20 mm in unusual cases) and ≤3 mm deep [S W1].
- Network statistics [S G9, G10, G14, G17]:
  - Junctions are mostly T-shaped; the angle histogram peaks at 90° and 180°.
  - Cells average about 4 corners, against 6 for a Voronoi pattern.
  - Successive crack generations take 0.12 / 0.30 / 0.58 of total length, with widths 1 / 0.8 / 0.6.
  - Direction noise is 9–15° per growth step.

**Spalls and dereliction**
- Spall depth classes:
  - MLIT [S J1]: Level 2 is 5–20 mm deep; Level 3 is ≥20 mm deep or exposes rebar.
  - Bridge inspection [S W7]: the class boundary is 25 mm deep or 150 mm across.
- An unmaintained 75-year-old Japanese RC tower [S J25]:
  - spall flakes 5–10 cm across, averaging 10 cm
  - 3.7–9.9% of each face spalled
  - spalls only where cover was under 25 mm
  - wetter faces worse
- MLIT spall-risk test for old apartment blocks [S J15]:
  - Fails when grade-3 points (delamination along bars, or exposed bars) reach ≥27% of ≥30 dwelling-unit inspection points.
  - Grade-2 points count 0.67 each.
- Cover [S J26, W8]:
  - Legal minimum: 20 mm for slabs and non-bearing walls, 30 mm for bearing walls, columns and beams.
  - A measured comparable (Finnish balconies): 24% of bars under 20 mm, 43% under 25 mm.

**Edges**
- No measurements were found for arris rounding against age, or for chip rates.
- Paint and repaint history [S/2 J33; S J10, J18, J38; I]:
  - The paint system is about 1–2 mm thick.
  - It is repainted every 12–15 years, with extra coats on external corners.
  - A 1960s–70s block therefore carries 4–5 generations of paint at its edges.
- Proposed edge state at amount 0.25 (all [I]):
  - Arris radius: 3–6 mm on weather edges, 5–9 mm on contact edges.
  - Chips: 0.5–1.5 per metre (≥3 mm). Of these, 0.04–0.15 per metre are ≥20 mm, i.e. one facade pixel.
  - A discoloured band 3–8 mm wide.
  - The edge pixel row at facade scale shifts by ΔL* 3–6.

---

## 2. Crack types on aged RC danchi walls (topic 1)

### 2.1 Width classes

| Width w | Meaning | Source |
|---|---|---|
| ≤0.05 mm | JCI 2003: no repair needed for watertightness | [S J3] |
| ≤0.2 mm | JCI: "fine cracks, generally ≤0.2 mm" are the target of the surface-coating repair method | [S J2 ✓] |
| ≤0.2 / 0.2–0.3 / 0.3–0.4 / 0.4–0.5 / >0.5 mm | JCI 2013 Table 4.2.1, corrosion impact over 20 years in ordinary outdoor exposure: small / small / medium / large / large. In salt environments, "large" already from >0.3 mm. | [S J2 ✓] |
| 0.15 / 0.3 / 0.5 mm | AIJ allowable widths: against leakage / outdoor durability / indoor durability. Design targets: 0.1 mm (leakage), 0.2 mm (outdoor). | [S J7, J6] |
| ≤0.3 mm | "Hairline" (ヘアクラック) in condo diagnosis. AIJ-style "light" damage grade: shrinkage cracks under 0.3 mm. | [S J20 ✓, J14 ✓] |
| 0.3 to <0.5 mm through finish and structure | MLIT Level 2: a defect is possible to some degree | [S J1 ✓] |
| ≥0.5 mm, or any rust-stained crack | MLIT Level 3: a defect is likely | [S J1 ✓] |
| corrosion crack <0.5 mm | AIJ-style "medium" grade | [S J14 ✓] |
| corrosion crack ≥0.5 mm, with delamination or exposed bars | AIJ-style "heavy" grade | [S J14 ✓] |
| <0.2 / 0.2–1.0 / >1.0 mm | Repair-method bands: surface seal / low-pressure injection / U-cut and fill. The 2022 JCI chart assigns injection to 0.2–1.0 mm. | [S/2 J11; S J4] |
| 0.2 to <2.0 mm | Gets a 50 mm elastomeric buffer band under waterproof coatings. Cracks ≥0.5 mm get cement filler rubbed in first. | [S J10 ✓] |
| ≥2 mm (roof substrates) | U-cut plus polyurethane sealant | [S J10 ✓] |
| >1.0 mm | Field data on 601 cracks: more than half the bars had section loss. Under 0.2 mm, none did. | [S J12] |
| <0.3 / 0.3–1.3 / >1.3 mm | AASHTO bridge inspection: insignificant / moderate / wide. Crack spacing >0.9 m / 0.3–0.9 m / <0.3 m. | [S W7 ✓] |
| <1.6 / 1.6–3.2 / >3.2 mm | FHWA ASR survey severity classes. Map-cracked area <5% / 5–25% / >25%. | [S W5] |
| 5–10 mm | Severe ASR cracks | [S W4] |
| 0.1 / 1 / 5 / 15 / 25 mm | BRE Digest 251 building-damage category bounds (0–5). From memory, not re-checked this session. | [I] |

For the generator, the classes that matter are:

| Class | Width |
|---|---|
| Hairline | <0.2 mm |
| Fine | 0.2–0.3 mm |
| Notable (MLIT Level 2) | 0.3–0.5 mm |
| Wide (MLIT Level 3) | 0.5–1.0 mm |
| Open | 1–3 mm |
| Structural or derelict | >3 mm |

The classes are set at 0.2 / 0.3 / 0.5 / 1.0 / 3.0 mm because these are the boundaries Japanese practice uses [I←J1, J2, J4].

### 2.2 Crack types and their layout

Each entry gives location, orientation, spacing and length, width, onset, junctions and look.

**A. Drying-shrinkage cracks in restrained walls.** This is the main "hairline" family.
- **Where:**
  - long solid panels: end walls (妻壁), north walls between small windows, balcony back walls between openings
  - balcony and parapet walls
  - the middle of long buildings

  [I←W3, J29]
- **Orientation:**
  - Near-vertical, because floor slabs and foundations restrain the wall horizontally and the tension runs horizontally. Diagonal at re-entrant corners. [S W3 ✓]
  - Cracks under windows start at the sill and run near-vertical in central bays. [S J29 ✓]
- **Spacing:**
  - Roughly straight cracks 1.5–6 m (5–20 ft) apart in long slabs and walls. [S W3 ✓]
  - Upper bound for base-restrained walls with little horizontal steel: about 1.3 × wall height. [S/2 W19]
  - Modern practice induces the cracks into joints every 3–4 m [S J10 ✓]. Many 1960s–70s walls have no inducer joints, so the cracks fall in mid-panel and at openings [I].
- **Length:** usually most or all of the storey height, from slab to slab or from an opening corner to a slab. About 0.5–1.0 × storey height. [I]
- **Width:**
  - The AIJ outdoor target is ≤0.3 mm. [S J7]
  - JCI's worked example shows 0.2–1 mm cracks at 2–5 m spacing. That case is a heat-of-hydration frame, not a housing wall. [S J2 ✓]
  - Estimate for aged walls: typically 0.05–0.3 mm, a few at 0.5 mm. [I]
- **Onset:**
  - Within about 60 days of casting [S W3 ✓]; "tens of days or more" [S J5].
  - Widths then grow for 1–3 years of drying. Cracks breathe seasonally (wider in winter). [I←W3: more cracking observed in winter cold]
- **Junctions:** mostly free ends, or T-junctions into openings, slabs and joints. No network.

**B. Diagonal cracks from opening corners (restraint/structural).**
- **Where:** most re-entrant corners of windows and doors [S W3 ✓]. In the 1957 survey of 30+ Japanese RC buildings [S J29 ✓]:
  - cracks under almost all windows, more conspicuous at lower windows
  - diagonal cracks at the four corners of nearly every floor
  - a V pattern at the end bays of long buildings: cracks run down from the inner corner of the sill and up from the outer corner of the lintel
- **Mechanism:** shrinkage stress concentrates at corners, giving about one crack per corner. Cracks branch and spread as they move away from the opening. Reinforcement spreads them out and narrows them. [S J30]
- **Angle:** about 45°. Engineers place corner bars at 45° for this reason. [S/2 W25] Use 45° ± 15°, turning toward vertical once more than about 0.5–1 opening width from the corner, where the far-field horizontal tension takes over. [I]
- **Length:** 0.3–1.0 × opening width while the building is maintained. At high damage they run to the next free edge (slab, opening or joint). [I]
- **Width:** 0.1–0.5 mm, widest at the corner and tapering away. [I]

**C. Thermal cracks: top floor, parapets, roof edges.**
- **Inverted V near the top of the building**, caused by roof heating (or settlement). On some long, low buildings, X-cracks near the end spans: a V in winter, an inverted V in summer. [S J29 ✓]
- **Danchi translation:** on top-storey end walls, pairs of diagonals rising toward the building ends (the classic ハの字 pattern), plus a horizontal hairline just below the roof slab near the ends. [I←J29]
- **Parapets and balcony walls:**
  - Vertical cracks at fairly regular intervals of about 1–3 × the parapet height, i.e. about 1–3 m. [I]
  - A horizontal crack at the parapet base where the roof's protective concrete expands and pushes outward. The spec's movement joints are designed against exactly this. [S J9 ✓ joint layout; I crack]
- **Width:** 0.1–0.5 mm. These cracks move with the seasons, so their sealant fails first. [I]

**D. Corrosion cracks along bars (often parallel to edges).**
- **Mechanism:** carbonation reaches the bar, a crack forms along it, then corrosion accelerates. [S J14 ✓]
- **Where:**
  - building external corners, with spalls and exposed bars [S J14 ✓, a 1934 Dōjunkai example]
  - below windows [S J14 ✓]
  - tops of balcony handrail walls, and corridors [S/2 J20]
  - balcony and eave slab noses, where the drip groove (水切り) cut into the soffit locally thins the cover [I]
- **Orientation:**
  - Parallel to the nearest bar. At edges this is a line parallel to the arris, about 20–60 mm in from it (cover plus half a bar). [I]
  - On walls, cracks follow the bar grid of D10–D13 bars at about 200–300 mm spacing. [I]
- **Width progression:**

  | Stage | Width | Source |
  |---|---|---|
  | First visible crack | <0.05 mm | [S W10] |
  | After 15–50 µm of steel loss | 0.05–0.1 mm | [S J35] |
  | After 50–200 µm of steel loss | 0.2–0.3 mm | [S J35] |
  | Any width with rust stain | MLIT Level 3 | [S J1 ✓] |
  | Spalling usually begins | about 0.5–1.5 mm | [I←J35, Vidal relation, §4.1] |
  | Hashima exposure specimens (salt-laden, w/c 0.65): about 0.4 mm after 1 year | about 3.7 mm by year 4 | [S/2 J23, read from a figure] |

- **Look:** a rust stain at the crack is the visual signature (§3.4).

**E. Construction joints and cold joints.**
- **Joint layout (spec):** walls are cast storey by storey. Current spec puts a sealed construction joint (打継ぎ目地) at every floor. Vertical joints go at column sides or opening edges, and in between about every 3–4 m [S J10 ✓]. Joints are ≥20 mm wide × ≥10 mm deep [S J9 ✓].
- **Why they crack and stain:** horizontal construction joints carbonated to 20 mm in about 5 years in one study [S J8]. JCI counts construction joints as a high-risk factor when judging repair need [S J3]. So expect lines along floor levels with corrosion cracks, efflorescence and leak stains [I].
- **Cold joints (コールドジョイント):** these are unplanned, from delayed concrete placement.
  - They are irregular lines within a lift, roughly horizontal or inclined 0–30°, and wavy.
  - Honeycombing, leaks and efflorescence often show along them.
  - Use them sparingly, at 0–1 per storey per 10 m of wall. [I]

**F. Wall–slab junctions and balcony slab roots.**
- In the 1957 survey, transverse cracks ran through the middle of buildings across the floor slab and adjacent beams. [S J29 ✓]
- On a facade this reads as [I]:
  - horizontal hairlines on the slab line near the building ends
  - cracks at the root of cantilevered balcony slabs, on the top surface along the wall line
  - vertical cracks in balcony walls where they meet the partition walls

**G. Crazing (cement paste) and paint-film cracking.**
- **Crazing** [S W1 ✓]:
  - "Rarely more than ⅛ inch [3 mm] deep".
  - Irregular hexagonal cells, typically ≤40 mm across, as small as 12–20 mm in unusual cases.
  - Forms within the first week.
  - More visible as a wet surface dries; dirt lodged in the cracks makes them stand out.
  - A pavement manual gives ≤50 mm cells. [S W6]
- **On painted danchi walls:** the spray texture largely hides substrate crazing. The fine networks that do show are cracks in old, brittle paint layers. [I]
- **Cell size by layer:** crack spacing scales with layer thickness, at about 3–5.5 × thickness [S G12, G13]. Expected cells [I]:

  | Layer | Thickness | Cells |
  |---|---|---|
  | Paste skin (crazing) | about 3 mm | 12–40 mm (matches NRMCA) |
  | Main texture coat | 1–2 mm | about 4–10 mm |
  | Stacked top coats | 0.2–0.5 mm | about 1–3 mm |

- **Classification:** paint cracking is graded by ISO 4628-4. From memory: size 0–5, where size 5 is "generally >1 mm wide"; density 0–5; depth a/b/c (top coat only / into lower coats / through the whole system). [I]

**H. Map or pattern cracking (ASR, deep surface shrinkage).**
- **ASR look** [S W4]:
  - random orientation where the member is free
  - aligned with restraint where it is not
  - brownish, damp-looking borders
  - severe cracks 5–10 mm wide
- **Thresholds:**
  - Japanese PC-girder practice: ASR crack density ≥2 m/m² (cracks ≥0.2 mm) triggers a load-capacity check. [S J31 ✓]
  - AASHTO: moderate map cracking at 0.3–0.9 m spacing, heavy at <0.3 m. [S W7 ✓]
- **Relevance:** unusual on danchi walls; Japanese ASR problems were mainly in civil works. Treat it as an optional "story" feature. [I]

**I. Settlement.** Inverted-V patterns, and vertical cracks that taper, wider at the top or the bottom. [S J29 ✓ for the pattern] Optional story feature.

**J. Seismic (optional story).** Diagonal tension, X-cracks in the wall strips between openings and over stacked door openings [S W3 ✓]. In one study of damaged columns, the box-count fractal dimension of the crack map rose from 0.85–1.09 at 0.25% drift to 1.62–1.80 at 4% drift [S W24]. Danchi wall structures (壁式) have high wall density, so expect light, low-storey X-cracks at most [I].

**K. Plastic shrinkage and plastic settlement.**
- Plastic shrinkage is mainly a horizontal-surface defect: balcony slab tops, parapet tops.
- Formed vertical faces show plastic settlement over horizontal bars near the top of each lift instead: short horizontal cracks that mirror the bar grid at about 200–300 mm.
- Rare on finished walls; use only in close-ups.
- [I; ACI 224.1R describes this but was not re-checked this session]

### 2.3 Where cracks go on a typical walk-up block

Ranked by share of crack length on an aged, maintained block [I←J29, W3, J14]:
1. Opening corners and sills: diagonals and V patterns.
2. Long solid panels (end walls, wall between windows): vertical cracks.
3. Top-storey ends: thermal inverted V; roof-edge horizontals.
4. Parapets and balcony walls: regular vertical cracks; base horizontals.
5. Floor-level joint lines: horizontal cracks, efflorescence.
6. Thin-cover edges and corners: corrosion cracks parallel to the edge.

Item 6 grows fastest with neglect.

Floor and face bias:
- Lower floors carry more opening cracks (restraint) [S J29 ✓].
- The top floor carries the thermal patterns [S J29 ✓].
- Wetter faces carry more corrosion and spalling [S J25 ✓].

Storey height for the period was about 2.6–2.9 m [I].

### 2.4 Crack density by condition (m of crack per m² of wall, openings excluded)

No age-resolved survey of Japanese housing walls was found. The bands below are anchored estimates.

| State (amount) | Age and maintenance | All visible, w≥0.05–0.1 | w≥0.3 | w≥0.5 | w≥2 |
|---|---|---|---|---|---|
| New or just repaired (0) | — | 0–0.1 | 0 | 0 | 0 |
| Aged, maintained (0.25) | 8–15 years since last large repair | 0.2–0.6 | 0.03–0.15 | ≤0.03 | 0 |
| Neglected (0.5) | One repair cycle missed (25–30 years) | 0.5–1.2 | 0.15–0.4 | 0.05–0.15 | ≤0.02 |
| Vacant or unsafe (0.75) | Meets the MLIT spall-risk test | 1.0–2.0 | 0.3–0.8 | 0.15–0.4 | 0.02–0.1 |
| Derelict (1.0) | Abandoned 20–50 years | 1.5–3.5 | 0.6–1.5 | 0.3–0.8 | 0.05–0.3 |

Anchors:
- **Sample estimate.** A condo repair estimate gives 55 m of cracks to repair (5 m ≥0.5 mm, 50 m <0.5 mm) and 490 m² of concrete washing. That is about 0.11 m/m² of repair-class cracks, which matches the 0.25 row. [S/2 J19 ✓; I for the ratio, low confidence]
- **One vertical set.** A single full-height set at 1.5–6 m spacing gives 0.17–0.67 m/m². [I←W3]
- **Opening corners.** These add about 0.06–0.2 m/m², assuming one opening per 6–10 m² of facade and 0.6–1.2 m of corner cracks per opening. [I]
- **Upper bound.** ASR-damaged girders lose design performance from 2 m/m² of cracks ≥0.2 mm [S J31 ✓]. That is a sensible ceiling for the derelict w≥0.2–0.3 band. [I]
- **Crazing patches.** Local density is about 2/cell-size, i.e. 50–170 m/m² for 12–40 mm cells. They cover only a small area fraction (§8 C9). [I←W1]

### 2.5 Orientation, junctions, hierarchy

- **Orientation** for wall networks, length-weighted [I←W3, J29]:

  | Direction | Share | Notes |
  |---|---|---|
  | Vertical (±15°) | 40–65% | |
  | Diagonal (30–60°) | 20–40% | Mostly within one opening-width of an opening corner |
  | Horizontal (±15°) | 10–25% | Joint lines, parapet bases, slab noses, bars |

  Isotropic networks (crazing, ASR on free surfaces) have near-uniform orientation. [S G9 ✓]
- **Junctions:**
  - Sequential cracking makes T-junctions: a new crack curves to meet an older one at about 90°. [S G1, G12]
  - The angle histogram of a T-dominated network peaks at 90°, with a second peak at 180° about half as tall. [S G14]
  - Repeated drying cycles drift mud networks toward Y-junctions at 120°. The most common angle settles at 120° by about cycle 100. [S G14]
  - Concrete cracks do not heal and re-form the way mud cracks do, so wall networks stay T-dominated. Crazing, which forms at once over a thin skin, is closer to irregular hexagons, i.e. more Y. [I←W1]
- **Cell topology (Domokos et al.):** mean cells per node n̄ and mean corners per cell v̄ [S G17]:

  | Network | [n̄, v̄] |
  |---|---|
  | Voronoi | [3, 6] |
  | Repeated splitting with T-junctions | tends to [2, 4] |
  | Crossings | [4, 4] |
  | Mud cracks | between [2, 4] and [3, 6] |

- **Hierarchy:**
  - Older cracks are wider. [S G14]
  - A recursive-Voronoi model gives crack length per generation of 0.123 / 0.300 / 0.577, with widths 1 / 0.8 / 0.6 (citing Kumar & Kulkarni). [S G9 ✓, G10 ✓]
  - Late cracks run straight through the middle of a domain, perpendicular to its long side. [S G12]
- **Stress shadow:** no new parallel crack forms within about 1–2 layer thicknesses of an existing one. [S G13]
- **Path shape:**
  - Tortuosity (path length ÷ chord): about 1.15 in one image study. [S/2 W23]
  - Growth-model direction noise: σθ = π/20–π/12 (9–15°) per step. [S G10 ✓]

---

## 3. How cracks read at 20 mm/px and 1 mm/px (topic 2)

### 3.1 Pixel arithmetic: why open cracks are nearly invisible at facade scale

All values in this subsection are [I]. Assumptions:
- Painted wall albedo 0.45 (L* ≈ 73); crack interior about 0.05.
- A pixel's albedo is the area-weighted mix.

| Feature | 20 mm/px | 1 mm/px |
|---|---|---|
| 0.1 mm crack, bare | ΔL* ≈ 0.1 | ΔL* ≈ 2.5 (borderline) |
| 0.3 mm crack, bare | ΔL* ≈ 0.4 | ΔL* ≈ 9 |
| 1 mm crack, bare | ΔL* ≈ 1.3 | 1 px full dark, ΔL* ≈ 30+ |
| 3 mm crack, bare | ΔL* ≈ 4 | 3 px |
| Dirt halo 10 mm total, 20–30% darker | ΔL* ≈ 3–5 | ±2–6 px halo, ΔL* 5–15 |

At 20 mm/px a crack reads through what it carries, not through its opening. That means:
- the dirt and moisture halo
- efflorescence and rust trails
- repair stripes
- chipped crack lips (for w ≥0.5 mm)
- a shadow groove (for w ≥2–3 mm)

At 1 mm/px, hairlines of 0.1 mm or more can be drawn directly as sub-pixel coverage.

Human visibility [I]:
- One arc-minute is 0.29 mm at 1 m and 2.9 mm at 10 m.
- Inspectors measure 0.2 mm cracks at arm's length, which is why bridge codes require close visual inspection.
- From game distances (5–50 m), only the halo and stain proxies carry.

### 3.2 Dirt, moisture and biology along cracks

- Dirt lodged in craze cracks makes them more obvious, and they show most while a wet surface dries. [S W1 ✓]
- Proposed halo [I]:
  - A band 2–6 mm wide each side of cracks ≥0.2 mm, 10–30% darker, with warm grey-brown hue.
  - Wider below horizontal or inclined cracks, where run-off wets the lower lip. Tails of 50–300 mm hang below cracks that collect water.
  - On north faces and in shade, the halo turns green-black from algae and mould.
  - The same halo, weaker (5–10% darker), marks hairlines at 1 mm/px.
- Crack lips [I]:
  - Spray-tile texture breaks along cracks ≥0.5 mm, leaving 1–3 mm chipped lips.
  - At ≥1 mm, the two sides can show a small step (0.2–1 mm out of plane).
  - These are the only features of an open crack that the normal map should carry at facade scale.

### 3.3 Efflorescence and lime runs

- **Inspection definitions:**
  - Japanese condo diagnosis: leaching (漏水・白華) means calcium hydroxide carried out by water through a through-crack, deposited as white crystals. [S J20 ✓]
  - MLIT's spall-risk grading puts efflorescence in grade 1, alongside surface cracks and finish lifting. [S J15 ✓]
  - AASHTO: condition state 2 is "surface white without build-up"; state 3 is heavy build-up with rust staining. [S W7 ✓]
- **Where** [I]:
  - balcony and corridor soffits: through-cracks in slabs; the most common danchi case
  - horizontal joints and cold joints
  - parapet bases
  - under window sills
- **Shape** [I]:
  - White, feathered runs 30–300 mm long below the crack, 5–40 mm wide.
  - On soffits: drip spots, and at the derelict stage small stalactites (つらら) 5–50 mm long.
  - Colour is chalk-white to grey-white (L* 80–92) with high roughness. It is lighter than the paint and mottled.

### 3.4 Rust bleed

- Any rust-stained crack is MLIT Level 3, whatever its width [S J1 ✓]. Rust stains appear from Hashima grade II onward [S J24 ✓].
- Stain geometry [I]:
  - Orange-brown when fresh, dark brown when old.
  - Starts at the crack line, 1–3 × the width of the crack zone (about 10–60 mm).
  - Runs down 50–500 mm, fanning slightly.
  - Heavier on wet faces.
- Railings stain the slab edges below their post sockets and base plates (§4.6).

### 3.5 Repaired cracks seen through repaint (common on repainted danchi)

Dimensions from the MLIT renovation specification:

| Repair | Specified dimensions | Source |
|---|---|---|
| Low-pressure injection | Clean a band about 50 mm wide; ports every 200–300 mm; temporary seal about 30 mm wide × 2 mm thick, ground off afterwards | [S J10 ✓] |
| U-cut and fill | Disc-cut groove about 10 mm wide × 10–15 mm deep, filled with sealant, polymer-cement mortar or flexible epoxy | [S J10 ✓] |
| Surface seal | About 10 mm wide × 2 mm thick | [S J10] |
| Elastomeric buffer (cracks 0.2 to <2.0 mm) | A band about 50 mm wide, ≥50 mm past each crack end, equivalent to a 0.25 mm film, brushed with no step at its edges | [S J10 ✓] |
| Multi-layer finish, patch repair | Base and main coats re-applied locally to match the existing pattern; top coat over the whole wall | [S J10 ✓] |

The patch-repair rule means old repairs differ in texture, not colour [I].

- **Extra coats** (増塗り) go on external and internal corners, joints and around openings. So repainted corners and reveals carry a thicker, smoother film. [S J10 ✓]
- **Roller laps:** in mastic-coat repainting, the lap width is about 800 mm, so faint lap marks can repeat at about that pitch. [S J10 ✓]
- **Contractor experience:** sealant alone stays visible; adding the texture pattern over it hides it almost completely; some silicone sealants repel paint. [S/2 J21]

Proposed look [I]:
- A stripe follows each crack as a straighter polyline, since disc cutters cut 0.1–0.5 m chords.
  - Width: 10–15 mm (U-cut), 30–50 mm (injection), 50 mm (buffer).
  - Port scars: 10–20 mm discs at 200–300 mm pitch.
- **At 20 mm/px:** a 1–3 px line with little colour change (ΔL* ≤3). The texture is flatter, roughness differs by about ±0.05–0.15, and the line is raised or sunk 0.2–1 mm in the height map.
- **Ageing:** sealant plasticiser bleeds into the paint and catches dirt, so stripes over sealant darken with age. Old repairs crack again along their edges, giving two parallel hairlines 10–50 mm apart.

### 3.6 Render recipe by width class and scale

Every value in this table is [I].

| Class | 20 mm/px albedo | 20 mm/px normal/height | 1 mm/px albedo | 1 mm/px normal/height | Roughness |
|---|---|---|---|---|---|
| Hairline <0.2 mm | Only where dirt-highlighted: 1 px, ΔL* ≤3 | none | Core at coverage, ΔL* 2–6; halo optional | none, or 1 px cavity | +0.02 in halo |
| Fine–notable 0.2–0.5 mm | 1 px, ΔL* 3–8 from the halo | none | Core ΔL* 6–15 plus halo 2–4 px each side | Groove depth 2–5 px equivalent | +0.05 in halo |
| Wide 0.5–1 mm | 1 px (2 px with halo), ΔL* 5–10 | Lip chipping only | Core 1 px dark; chipped lips 1–3 px | Groove plus lip breakage | +0.05–0.1 |
| Open 1–3 mm | 1–2 px, ΔL* 8–15 | Groove allowed | 1–3 px dark core, lips 2–5 px | Groove depth 5–20 mm | +0.1 |
| >3 mm | 1–3 px, ΔL* 10–20, shadow | Groove and offset | Full gap with visible depth | Step offset 0–5 mm | — |
| Repair stripe | 1–3 px, ΔL* ≤3 | Height ±0.2–1 mm | Smooth band, texture break | ±0.2–1 mm | ±0.05–0.15 |

---

## 4. Spalling, delamination, chunk loss, and the road to derelict (topic 3)

### 4.1 Mechanism and its numbers

**Cover**
- Legal minimum cover: 20 mm for floors and non-bearing walls, 30 mm for columns, beams and bearing walls. [S J26]
- Measured spread, Finnish balcony slabs [S W8 ✓]:
  - 0.0% under 5 mm, 3.7% at 5–9 mm, 5.8% at 10–14 mm, 14.3% at 15–19 mm, 18.9% at 20–24 mm.
  - Cumulative: 3.7% under 10 mm, 9.5% under 15 mm, 23.8% under 20 mm, 42.7% under 25 mm.
  - That is a mean of about 27 mm with a standard deviation of about 10 mm.
- For 1960s–70s danchi, use mean 22–27 mm, SD 8–10 mm. [I]

**Cover thresholds for spalling**
- Shime tower: exposure from spalling occurred only where cover was under 25 mm. [S J25 ✓]
- Japanese bridges: corrosion spalls only where cover was under 40 mm. Railway structures with cover over 30 mm were mostly safe. [S J34]

**Carbonation**
- Rule of thumb: t = 7.2·X² (t in years, X in cm). Multiply by 0.8 under lithin finish and 0.4 under multi-layer (spray-tile) coating. [S J20 ✓] At 60 years [I]:

  | Surface | Carbonation depth |
  |---|---|
  | Bare concrete | about 29 mm |
  | Lithin finish | 23 mm |
  | Multi-layer coating | 12 mm |

- Measured outdoors over 11 years at w/c 57.5%: mean 1.18 mm/√year, maximum 4.63 mm/√year. [S J8]
- Maintained coatings: 0.5–1.0 mm/√year, against about 3.0 for bare concrete. [S J38]
- Consequence for a maintained danchi [I]:
  - The carbonation front reaches the bars only where cover is under about 10–15 mm.
  - So spalls concentrate on corners, slab noses and parapet tops, where cover is worst.
  - Once coatings fail, the bare rate applies and the 20–25 mm band follows within a few decades.

**From corrosion to cracking**
- JCI: carbonation-caused cracking with cover under 25 mm has a large effect even over a 5-year horizon. [S J2 ✓]
- Crack widths with steel loss [S W10; S J35]:
  - First crack: under 0.05 mm.
  - 15–50 µm steel loss: 0.05–0.1 mm.
  - 50–200 µm steel loss: 0.2–0.3 mm.
- Vidal (2004): w = 0.0575 (ΔAs − ΔAs0), with w in mm and ΔAs the bar-area loss in mm². [S J35]
- Worked example for a D13 bar (126.7 mm²) with ΔAs0 ≈ 1 mm² [I]:

  | Section loss | Crack width |
  |---|---|
  | 3% | about 0.16 mm |
  | 10% | about 0.67 mm |
  | 20% | about 1.4 mm |

  So spalling usually starts somewhere between 0.5 and 1.5 mm.
- Rates:
  - Natural corrosion is about 1 µA/cm², roughly 11.6 µm of steel per year. [S J35, W11]
  - Cracking appears about 1–4 years after corrosion starts.
  - 10% loss of a D13 bar (about 0.33 mm of radius) takes about 10–30 years. [I]
- Field data: when the widest crack exceeds 1.0 mm, most bars show section loss. [S J12]

### 4.2 Spall and chunk geometry

- **Size:**
  - Shime tower flakes [S J25 ✓]:
    - 5–10 cm across, "average size of 10 cm in diameter".
    - About 200 flakes a year from a 47 m tower.
    - They fell within 7 m (0.15 × height).
  - Bridge condition states [S W7 ✓]:
    - State 2 (fair): delaminated, spalls ≤25 mm deep and ≤150 mm across, sound patches.
    - State 3 (poor): spalls deeper or wider than that, unsound patches.
- **Depth:** MLIT Level 2 is 5 to <20 mm deep in the structure; Level 3 is ≥20 mm, or rust-stained, or exposing rebar [S J1 ✓]. In practice spall depth is the cover (10–30 mm). At Hashima grade V the concrete behind the bars is lost too [S J24 ✓].
- **Shape:**
  - Thin cover with wide bar spacing gives corner or wedge spalls bounded by two cracks at about 45°.
  - Thicker cover relative to bar spacing gives a flat delamination along the bar layer.
  - [S/2 W12]
  - Spalls stretch along the bar at about 1.5–4 : 1, with a fractured floor at bar depth. [I]
- **Repair practice** (useful for maintained states):
  - Spalls are filled with polymer-cement mortar in 1–3 layers of about 7 mm.
  - On mortar walls, patches cover spots up to about 0.25 m²; larger areas are re-plastered.
  - [S J9, sub-research]
  - Patches over spalls: 50–300 mm blobs with flatter texture under the top coat. [I]
- **Aggregate and bars:**
  - A Tokyo construction spec lists 20 and 25 mm river gravel and 20–5 mm crushed stone. [S/2 J36]
  - Spall floors should show coarse aggregate 5–25 mm, rounded river gravel on older blocks. [I]
  - Fresh fractures are 5–10 L* lighter than weathered concrete and roughness 0.85–0.95. Rust halos extend 10–40 mm around exposed bars. [I]
  - Wall bars of the period are D10–D13 at 200–300 mm spacing. [I]

### 4.3 Where spalls happen (ranked)

1. External corners of the building, columns and walls [S J14 ✓].
2. Balcony and eave slab noses, especially along the drip groove [I].
3. Handrail-wall tops and corridor parapets [S/2 J20].
4. Below windows [S J14 ✓].
5. Construction-joint lines [S J3, J8].
6. Wall faces with thin cover over bar crossings [I].

Wet faces spall more. At Shime, the west face (78% wet after rain) had 9.91% spalled, against 5.20% on the south face (19% wet) [S J25 ✓].

### 4.4 Condition ladders found in sources

| Ladder | Steps (visual meaning) | Source |
|---|---|---|
| MLIT exterior-wall spall-risk grades (apartment blocks) | 0 none; 1 finish lifting, surface cracks, efflorescence; 2 cracks along bars, rust stains; 3 delamination along bars, exposed bars | [S J15 ✓] |
| AIJ-style damage grades (Noguchi) | sound; light (shrinkage cracks <0.3 mm, no corrosion cracks); medium (corrosion cracks <0.5 mm); heavy (corrosion cracks ≥0.5 mm, delamination, exposed bars, most bars at corrosion grade IV) | [S J14 ✓] |
| JSCE appearance grades (corrosion) | I latent; II propagation; III-1 corrosion cracks appear; III-2 cracks widen and lengthen; IV deterioration. Rust stains and partial spalling come in at III-2; large spalls, section loss and deflection at IV (detail from memory, not re-checked) | [S J31 ✓ names; I details] |
| Hashima member grades (Noguchi) | I: ≤3% bar mass loss, no corrosion cracks. II: 3–10%, cracks, rust stains, partial spalling. III: about 10%, partial spalling or concrete separating from bars. IV: 10–30%, continuous cover spalling, bars largely exposed. V: ≥30% or broken bars, concrete behind the bars damaged | [S J24 ✓] |
| MLIT dispute-resolution levels | Level 1–3 by crack width (0.3 / 0.5 mm) and spall depth (5 / 20 mm), plus rust stain or exposed bar | [S J1 ✓] |
| AASHTO bridge element states | CS1–CS3 by crack width (0.3 / 1.3 mm), spacing (0.9 / 0.3 m), spall size (25 mm / 150 mm), efflorescence build-up | [S W7 ✓] |

### 4.5 Fractions affected: surveys and anchors

- **MLIT exterior-wall survey of old apartment blocks** (10 buildings, 903 inspection points) [S J15 ✓]:
  - Visible-grade shares: grade 0 27.7%, grade 1 43.5%, grade 2 10.6%, grade 3 18.2%.
  - Grade 3 was seen at 12.4% of points where bar corrosion was grade ≤3, and at 63.7% where it was grade ≥4.
  - The spall-risk criterion is the weighted share (n₃ + k·n₂)/N:

    | Inspection points N | Weight k | Threshold |
    |---|---|---|
    | ≥30 | 0.67 | ≥0.27 |
    | 15–29 | 0.71 | ≥0.34 |
    | 8–14 | 0.80 | ≥0.50 |

  - Inspection points correspond to dwelling-unit facade portions, e.g. 4 units × 4 floors or 6 units × 5 floors on a south face.
  - This is the line between "old" and "unsafe".
- **Shime tower** (1943, unmaintained, 75 years old) [S J25 ✓]:
  - Spalled area 3.71% (east), 5.20% (south), 9.35% (north), 9.91% (west).
- **Finnish balconies and facades** (built 1948–1996):
  - First visible corrosion in balcony slabs at an average age of 25 ± 7 years. [S W8 ✓]
  - After about 50 years, 8.4–21.8% of balcony bars sit in carbonated concrete (slab soffits 21.8%). [S W8 ✓]
  - 66% of balconies show visible corrosion (51% local, 15% widespread), and 12–19% need heavy repair. [S/2 W9]
- **Japan, 21 buildings:** in carbonated concrete, about 30% of bars showed no corrosion and about 40% only a few rust spots. [S W8, citing an earlier study]
- **Hong Kong, 1989:** about 50% of Housing Authority blocks had spalling or section-loss defects needing repair. [S W13]
- **Hashima** (abandoned 1974):
  - Building No. 30 (1916) has had a sequence of roof-slab and wall collapses:
    - March 2020: south side
    - June 2020: west side
    - November 2021 – June 2023: south roof slab, a different location
    - October – November 2024: east roof slab

    [S J24 ✓]
  - Building No. 16 retains 73% of its vertical load capacity and 24–30% of its seismic resistance. [S J24 ✓]
  - Windows are shattered or missing; rusted frames remain. [S/2 W26]
  - A 3rd-floor member survey of No. 16 spreads columns and beams across grades I–III. Read off the slide, low confidence. [S/2 J24]
- **Steel windows**, 1915 industrial building, occupied but unmaintained, 415 windows [S W14]:
  - 6% missing, 58% poor or beyond repair, 36% fair.
  - Sills cast into concrete corroded and spalled the surrounding concrete.
  - Decay ran 75–150 mm up the glazing bars.

### 4.6 Non-concrete elements on the way to derelict

- **Steel railings:**
  - Rules: at least 1.1 m high on balconies from the 2nd floor up [S J27]. A Tokyo guideline asks for ≥1,100 mm (1,200 recommended) and balusters within 800 mm of a foothold at ≤110 mm gaps (90 recommended) [S J28]. 1960s–70s railings may predate these rules. [I]
  - Rust area ladder, ISO 4628-3 Ri 0–5: about 0 / 0.05 / 0.5 / 1 / 8 / 40–50% of the surface [S/2 W17]. ASTM D610 grade 5 is 1–3%, grade 0 is >50% [S W16].
  - Corrosion concentrates at base plates and sockets cast into concrete, and inside posts [S/2 sub-research; I].
  - Rust streaks start at post sockets, welds and drain spouts. They are 1–2 × the post width at source, fanning to 2–4 × over 0.3–1 m. [I]
- **Windows:** no data was found on glass-breakage rates against years vacant. Anchors are 6% missing in an occupied, unmaintained factory [S W14] and Hashima, mostly shattered after 50 years [S/2 W26]. Wired glass (網入り), common in danchi stair halls and doors, stays in the frame as spider-cracked panes. [I]
- **Balcony partitions (隔て板):** 4–6 mm calcium-silicate or flexible board (also aluminium, steel, FRP), marked to be broken through in emergencies. [S/2 J37] Older boards may contain asbestos. [I]

### 4.7 Proposed stage ladder: share of elements affected

All values in this table are [I], unless a source is marked.

| Element / measure | 0.25 aged, maintained | 0.5 neglected | 0.75 vacant/unsafe | 1.0 derelict |
|---|---|---|---|---|
| Openings with ≥1 corner crack | 20–40% | 40–70% | 60–90% | 80–100% |
| Balconies with ≥1 spall or exposed bar at the nose | 2–10% | 10–30% | 30–60%, meets the MLIT spall-risk test (≥27% grade-3 points) [S J15] | 60–95% |
| Spalled share of wall area | 0.01–0.1% | 0.1–0.5% | 0.5–3% | 3–10% [S J25: 3.7–9.9% at 75 yrs] |
| Slab-edge and corner length with chunk loss ≥30 mm deep | 0–0.5% | 0.5–2% | 2–8% | 10–30% |
| Railing bays with visible rust | 10–30% (Ri1–2) | 40–70% (Ri3) | 80–100% (Ri4) | 100% (Ri5) |
| Railing bays bent >20 mm | 0% | ≤2% | 5–15% | 15–40% (bows 50–300 mm, posts tilted 5–30°) |
| Missing balusters | 0% | ≤0.5% | 1–5% | 5–30%, clustered at rotted bases |
| Missing railing bays | 0% | 0% | 0–3% | 5–15% |
| Window panes broken or missing | 0–0.5% | 0.5–2% | 10–40% on floors 1–3, 5–15% higher | 70–100% glass gone; 10–40% of sashes missing |
| Balcony partitions broken or missing | 0–1% | 1–3% | 10–30% | 30–70% (frames remain) |
| Crack density w≥0.3 (m/m²) | 0.03–0.15 | 0.15–0.4 | 0.3–0.8 | 0.6–1.5 |

---

## 5. Edges as their own rule set (topic 4)

### 5.1 What evidence exists (thin)

- **Direct data:** none found on arris rounding against age, chips per metre, or chip size distributions, despite searching precast, kerb, stair and column sources.
- **Stair wear** (wood, as an order of magnitude) [S W15]:
  - 17th-century oak treads lost about 10 mm in 100 years from about 1.2 million visitors, i.e. 8×10⁻⁶ mm per visitor. Treads fitted in the 1970s wore at 5×10⁻⁷ mm per visitor.
  - Wear concentrates on the walking line; shoe kicks dent the risers.
  - Paint wears off balusters and posts where people grip them, and hand grime builds up there.
- **Paint build-up** (Japanese waterproof multi-layer system):
  - Applied at ≥0.1 / 0.9 / 1.7 / 0.9 / 0.25 kg/m² for sealer / extra coat / base / pattern / top. [S/2 J33]
  - The MLIT spec gives base 0.1, main coat 0.7 + 0.8 (pattern), top 0.25 × 2 kg/m². [S J10]
  - That is roughly 1–2 mm dry, with texture peaks near 3 mm. [I]
- **Edge-specific painting:**
  - Extra coats (増塗り) go on external and internal corners, joints and opening surrounds, feathered with no step. [S J10 ✓]
  - Coatings thin out over sharp arrises, which is why steelwork specs require "stripe coats" on edges. Edges are therefore the first place a coat wears through. [I; general coatings knowledge, not re-checked]
- **Repaint cycles:**
  - The average across 222 Tokyo condominiums was 12 years (range 9–17). [S J38]
  - National guidance gives 12–15 years for facades. [S J18] Rain-exposed steel is repainted every 5–7 years. [S/2 J18]
  - MLIT's 2021 survey found 1st, 2nd and 3rd large repairs at 15.6, 14.0 and 12.9-year intervals. [S J17]
  - So a 1965 block carries about 4–5 facade coats and 8–12 coats on its steel. [I]
- **Coating durability:** single-layer coatings fall below the adhesion limit after about 17 years; mastic and multi-layer coatings barely degrade. [S J38]

### 5.2 Which edges wear, and why

Multipliers are relative to "weather-only" edges. All values in this table are [I].

| Edge | Mechanism | Height band | Chip multiplier | Band multiplier |
|---|---|---|---|---|
| Stair nosings (階段の段鼻) | Feet, moving furniture | 0 m at every step | ×6 | ×2 |
| Stair-hall wall and column corners, entrance jambs | Shoulders, bags, bikes, prams, removals | 0–1.8 m | ×3 | ×2 |
| Ground-floor external corners (bike parks, paths) | Bikes, carts, mowers | 0–1.2 m | ×3 | ×1.5 |
| Corridor and balcony inner parapet tops (手すり壁天端) | Hands, objects set down, plant pots, rain and freeze–thaw | top face | ×2 | ×2 |
| Balcony slab noses above ground floor | Weather, corrosion, drip groove | out of reach | ×1 | ×1.5 (dirt drip line) |
| Roof parapets, copings, eave edges | Weather, thermal, freeze–thaw | out of reach | ×1 | ×1 |
| Window reveals, sills, heads | Weather, sash removal during renovations | — | ×1 | ×1.5 at sills |
| Sheltered soffit edges | Little | — | ×0.3 | ×0.5 |

Contact heights by cause [I]:

| Contact | Height |
|---|---|
| Shoes | 0–0.3 m |
| Wheels and carts | 0.05–0.45 m |
| Bike baskets and handlebars | 0.8–1.1 m |
| Hands | 0.8–1.05 m |
| Shoulders and bags | 1.0–1.5 m |

Fixed reference heights: stair handrails at 800–850 mm, balcony railings ≥1,100 mm [S J28; S J27].

### 5.3 Layers that wear exposes

Proposed stack, outermost first [I]:

**Concrete walls**
1. Current top coat.
2. Earlier top-coat colours, in bands, one per repaint.
3. White or grey texture main coat (spray-tile 主材).
4. Sealer.
5. Mortar or concrete skin: grey, L* 55–68.
6. Aggregate, if chipped deeper than about 5 mm.

**Steel**
1. Top coat.
2. Older colours.
3. Primer: red-brown, orange or grey.
4. Rust.

**How the layers show**
- On rain-washed top edges, chalking makes the arris lighter (ΔL* +2 to +5).
- Lower and drip edges hold dirt, giving a darker, warmer band (ΔL* −3 to −10, Δb* +1 to +4).
- Hand-polished arrises (jambs, rail tops at 0.8–1.2 m) are darker and smoother, with roughness −0.05 to −0.15. [S W15 for the hand grime; I for the values]

### 5.4 Estimates by age (for when the generator is driven by building age)

All values in this table are [I].

| Years since construction | Maintained (repainted on cycle) | Unmaintained |
|---|---|---|
| 10 | a_E 0.05–0.15 | 0.1–0.2 |
| 25 | 0.15–0.3 | 0.3–0.45 |
| 40 | 0.25–0.4 | 0.45–0.65 |
| 60 | 0.3–0.5 | 0.6–0.85 |
| Abandoned ≥20 years | — | 0.8–1.0 |

Repainting resets the colour band and paints over old chips, but not their geometry. Two options:
- Drive the colour band from years since the last repaint, and drive radius and chips from age.
- Or keep one amount and accept the coupling. The AD's 0.25 reading wants both. [I]

### 5.5 What "small but visible at 0.25" means in numbers

All values in this subsection are [I].

**At 1 mm/px (close-up, normal and height map)**
- Arris radius: median 3–6 mm on weather edges, 5–9 mm on contact edges, 8–15 mm on stair nosings.
- The radius varies along the edge, with a coefficient of variation of 0.3–0.6 in 0.25 m windows.
- Chips ≥3 mm long:
  - 0.5–1.5 per metre (weather edges), 2–5 per metre (contact edges), 4–10 per metre (nosings).
  - Median length 4–8 mm, maximum about 40 mm.
  - Depth 1–5 mm: through the paint into the mortar skin.
  - Chips cluster: count variance over mean ≥1.2 in 0.5 m windows.
- A discoloured band 3–8 mm wide, intermittent: present along 40–70% of weather-edge length and 70–100% of contact-edge length.

**At 20 mm/px (facade)**
- The radius is sub-pixel. Do not widen the bevel in the facade normal map beyond 1 px; it reads as soft plastic.
- Visibility comes from the edge pixel row:
  - Mean |ΔL*| 3–6 against the adjacent face.
  - Band continuity as above.
  - Visible chips (≥20 mm, i.e. ≥1 px): 0.04–0.15 per metre on weather edges, 0.2–0.6 per metre on contact edges.
  - On a 60 m block, 300 m of balcony slab noses gives about 12–45 visible chips.
- Worn-through share of contact-edge length: older paint or texture coat visible along 8–20%, concrete along ≤3% (inside chips only).

---

## 6. Survey and quantity data (topic 5)

**Japan**

- **MLIT exterior-wall spall-risk material:** 10 buildings, 903 points, visible-grade shares, and the weighted threshold rule. See §4.5. [S J15 ✓]
- **Consultant survey** (55 firms, 2019) [S J16]:
  - 81% settle substrate repairs on measured actual quantities; 26 firms set provisional quantities from damage counted per 1 m² of sample area.
  - The largest gaps between provisional and actual quantities are in tile, crack, rusted-rebar and mortar repairs.
  - Contingency is usually about 10%, and 44% say projects usually end up costing more than contracted.
- **Sample estimate** (condo, concrete parts) [S/2 J19 ✓]:

  | Item | Quantity |
  |---|---|
  | U-cut, cracks ≥0.5 mm | 5 m |
  | Filler, cracks <0.5 mm (the article notes the threshold can be 0.3 mm instead) | 50 m |
  | Mortar-delamination injection | 100 holes at 12 per m² |
  | Paint-surface defect repairs | 50 |
  | Exposed-rebar repairs | 50 |
  | Weak coating removal | 15 m² |
  | Concrete washing | 490 m² |
  | Tile repair allowance | 0.5–1% of tile area; one adhesive-tile building needed 10% |

  Taking 490 m² as the concrete area gives [I, low confidence]:
  - about 0.11 m of repair-class crack per m²
  - about 0.1 exposed-rebar spots per m²
  - about 3% of the area with weak coating
- **Repair cycles:** 15.6 / 14.0 / 12.9 years for the 1st / 2nd / 3rd large repair (818 projects, 2021) [S J17]. The guideline cycle changed from 12 to 12–15 years [S J18].
- **Hokkaido prefectural RC housing** (88 buildings surveyed 2017–2021): cracks, coating loss, spalls and exposed rebar all increase with age, but the numbers are only in figures. [S J32 ✓ (no extractable numbers)]
- **Carbonation:** rule and coefficients in §4.1. [S J20 ✓, J8, J38]
- **Not found:** UR or JHC deterioration surveys, crack density by age, measured cover depths in 1960s–70s danchi, or spall frequency per m² from a public housing survey.

**International**
- Finnish balconies [S W8 ✓; S/2 W9]
- Hong Kong [S W13]
- Shime [S J25 ✓]
- AASHTO, FHWA and ISO condition classes [S W7 ✓, W5, S/2 W17]
- Not found: UK Concrete Society, BRE or English Housing Survey grade tables with element percentages (searched, not reached).

---

## 7. Building cracks procedurally (topic 6)

### 7.1 Methods in the literature

| Method | How it lays out cracks | Source |
|---|---|---|
| Hirota et al. 1998/2000 | Spring lattice; a crack is a broken spring. Shows lattice artefacts. | [S G2 via G1] |
| Gobron & Chiba 2001 | Cellular automaton on the surface (10⁵–10⁶ cells), stress relaxation; used for concrete, mud, glaze | [S/2 G2] |
| Paquette, Poulin & Drettakis 2002 | Start in the cell with the highest stress/strength ratio. Tips grow perpendicular to the local maximum stress. Each crack completes before the next starts. Break strength is 1.5× propagation strength. Stress is relaxed out to a distance Dr; width is the accumulated relaxation. A crack nearing another snaps to it, making a T. | [S G1] |
| Federl & Prusinkiewicz 2004 | Two-layer finite-element model; crack starts above a principal-stress threshold and runs perpendicular to it; layer thickness sets the pattern | [S G3] |
| Mould 2005 | Voronoi regions on a pixel graph with noisy edge weights (noise-to-constant ratio about 6), 150–200 sites, 3-level hierarchy by re-weighting. Darkening I·(1−e^(−κd)). | [S G4] |
| Desbenoit, Galin & Akkouche 2005 | Crack as a graph with profile curves at its nodes; tips taper to zero | [S G5] |
| Iben & O'Brien 2006 | Heuristic stress field on a mesh, evolved over time; long vs short propagation set by a parameter; curvature biases starts | [S/2 G6] |
| Valette et al. 2008 | Watershed paths; crack order from the hierarchy | [S/2 G7] |
| Glondu et al. 2012 | Finite-element fracture fitted to statistics measured from a photo; path roughness from 4-octave noise | [S G8] |
| Tarasevich et al. 2025 | Recursive Voronoi (each cell re-split by its own seeds); gives length shares 0.123/0.300/0.577 | [S G9 ✓] |
| Tarasevich et al. 2026 | Growth simulation vs tessellations. Growth reproduces right-angle junctions and narrow 90°/180° peaks; tessellations match side counts better; no method gets everything. σθ = π/20–π/12. | [S G10 ✓] |

### 7.2 Target statistics from physics

- **Cell size vs layer thickness:**
  - Spacing ≈ 3h for bentonite clay. [S G13]
  - √(area/count) ≈ 5.5e for starch layers. [S G12]
  - Polygon area ∝ h^(4/3) for cornstarch films. [S G16]
- **Stress shadow:** relaxation length about 2h (1.2–1.3h for a compliant film on a stiff base). [S G13]
- **Hierarchy:**
  - Late cracks become deterministic when e/√A ≈ 0.13–0.18. [S G12]
  - 25–35% of vertices change formation order per drying cycle. [S G13]
- **T vs Y:** Y appears after many cycles; the 90° vs 120° balance is set by the Griffith length relative to cell size. [S G14; S/2 G19]
- **Topology:**
  - Voronoi sits at [3, 6]; T-splitting networks at [2, 4]. [S G17]
  - Side counts: the recursive model's mode is 5, then 6, 4, 7. [S G9 ✓] The growth model mostly gives 4–7. [S G10 ✓]

### 7.3 Production practice

- **Substance Designer:**
  - No built-in "Cracks" node was found. The library has Voronoi, Voronoi Fractal, Cells and Crystal. [S/2 G20]
  - A common chain: Flood Fill → Flood Fill to Gradient (random grey) → Distance → Edge Detect → warp → two Slope Blurs (the second using inverted cracks, blur about 0.33, strength about 0.02) for tight, deep cracks. Tile Generator instead of Flood Fill for speed. [S G22]
  - Warped Perlin plus flood-fill gradients plus dilation, then a histogram-scan mask for small cracks; slope blur adds chips inside the cracks. [S G23]
  - Forum consensus:
    - Cell-based crack sets look geometric.
    - Add a secondary crack layer masked by the primary.
    - Taper cracks where they meet grout or edges.
    - Width variation matters most.

    [S/2 G21]
- **Painter:** default crack alphas run through Slope Blur and Warp. [S G24]
- **Houdini:** draw crack curves with Find Shortest Path (or VEX branching), give them width, boolean or project them. [S G25] Copernicus builds patterns from SDF shapes, tile patterns and distortion; no crack node was found. [S/2 G26]
- **Engines:**
  - Unreal crack decal packs are normal-only DBuffer decals that overwrite normal and sometimes roughness. [S/2 G28, G21]
  - Godot decals take albedo, normal and ORM (R occlusion, G roughness, B metal); set albedo mix to 0 for normal-only decals. [S/2 G27]
  - Our target is baked textures, so decals are an optional transport, not the method. [I]

### 7.4 Recommended generator structure

All of this subsection is [I], built on the sources above.

1. **Feature layer** (facade space, 20 mm/px): openings, external corners, slab lines, joint lines (vertical 3–4 m, each floor [S J10]), parapets, slab noses, cover-risk zones (edges, drip grooves), wetness by face and orientation (feeds spalls, efflorescence, halos).
2. **Primary cracks by growth, not tessellation:**
   - Seeds:
     - opening corners, with per-corner probability set by floor and bay (lower floors and end bays higher)
     - solid-panel midspans, at 1.5–6 m spacing [S W3]
     - top-storey ends (thermal pairs)
     - parapets at 1–3 m
     - joint and slab lines, for horizontals
   - Direction field:
     - 45° at re-entrant corners, relaxing to vertical away from them
     - parallel to the edge for corrosion cracks
   - Step 20–40 mm with σθ 9–15° [S G10] and persistence.
   - When a tip comes within about 3–5 steps of a crack, opening or joint, turn toward it and stop, making a T.
3. **Secondary cracks:** recursive splitting of large uncracked panels as damage rises, splitting perpendicular to the long side. Gives T-dominated 2nd and 3rd generations at 0.8 and 0.6 relative width. [S G9, G12]
4. **Crazing and paint cracking** (1 mm/px only): use growth or recursive splitting with a Y-bias. Cell size comes from layer thickness (§2.2 G).
5. **Width model:**
   - log-normal per crack
   - taper to 0 over the last 10–25% of length
   - a younger crack is never wider than the older crack it meets
   - corrosion cracks widen with the spall-risk field
6. **Attachments:** dirt and wet halo, efflorescence, rust bleed, repair stripes, chipped lips (§3.6).
7. **Spalls:** sample along thin-cover features. Grow ellipses along the bar direction. Expose bars where depth reaches the cover; add an aggregate floor and rust halo.
8. **Geometry hand-off** to Houdini: chunk losses ≥30 mm deep on edges and corners, bent and missing railing parts, broken glass, missing partitions. Masks for the texture bake.

### 7.5 How to measure (descriptor definitions)

All recipes in this subsection are [I].

- **Crack graph:**
  - Skeletonise the crack mask, or use generator polylines when available.
  - Nodes: degree-1 nodes are ends, degree ≥3 are junctions.
  - Edges carry length, chord, orientation (PCA) and width (2 × the distance transform on the high-res mask, or the generator attribute).
- **Density ρ:** Σ length ÷ wall area excluding openings, per width class.
- **Orientation histogram:** length-weighted over 0–180°, in bins vertical (75–105°), diagonal (30–60° and 120–150°), horizontal (0–15° and 165–180°).
- **Junction class:** measure branch directions at radius R (100–200 mm at 20 mm/px, 5–10 mm at 1 mm/px):

  | Class | Rule |
  |---|---|
  | T | One pair of branches is 160–200° apart, and the third branch is 60–120° from each |
  | Y | All three angles are 100–140° |
  | X | Degree 4 |

- **v̄ and n̄ (Domokos):** cells are the faces of the planar graph closed by openings and borders. A node counts as a corner of a cell only if the boundary turns >30° there. n̄ is the mean number of cells at a node.
- **Tortuosity τ:** path length ÷ chord on segments of 0.2–1.0 m.
- **Taper:** width in the last 10% ÷ median width.
- **Box-count dimension:** over boxes of 0.1–5 m at 20 mm/px.
- **Edges:**
  - Radius: fit a circle to the profile normal to the edge (geometry), or take the curvature width from the height map.
  - Chips: profile deficit ≥2 mm deep and ≥3 mm long along the edge.
  - Band: pixels within 30 mm of the edge where |ΔL*| ≥2 against the face median, measured at 3–10 px from the edge.
- **ΔL*:** convert linear albedo to CIE L*. Report the mean over the feature's pixels against the median of a 5–15 px neighbourhood.

---

## 8. Proposed measurable rules (topic 7)

### 8.0 Conventions

- a_E, a_D ∈ [0,1] are the EDGES and DAMAGE amounts. Bands are given at 0.25 / 0.5 / 0.75 / 1.0. Interpolate linearly; at a = 0, expect zero visible features.
- Zones:
  - W: weather-only edges, out of reach.
  - C: contact edges, 0–2 m above a walking surface.
  - N: stair nosings.
  - S: sheltered edges.
- ρ(≥x): crack length per m² for widths ≥x mm.
- Scales: "F" = facade 20 mm/px; "Z" = close-up 1 mm/px.
- Origin tags: as defined at the top. "I←X" marks an estimate anchored on source X.

### 8.1 EDGES family

| ID | Measure (computed on) | Pass band | Origin |
|---|---|---|---|
| E1 | Median arris radius r over exposed edges, per zone (geometry or Z height) | r(W) = 2 + 12·a_E mm ±30% (0.25 → 3–6.5; 1.0 → 10–18). C ×1.5, N ×2.5, S ×0.6. At a_E = 0, 1–3 mm (paint build-up). | I←J10 (corner extra coats), W15 |
| E2 | Radius variation: coefficient of variation of r in 0.25 m windows along an edge | 0.3–0.6. No run >2 m with CoV <0.15. | I |
| E3 | Chip density λ (chips ≥2 mm deep, ≥3 mm long per m of edge), zone W | 0.25: 0.5–1.5 · 0.5: 1.5–3 · 0.75: 2.5–5 · 1.0: 3–8. C ×3, N ×6, S ×0.3. | I |
| E4 | Chip size: CCDF slope b of chip length (N(>L) ∝ L^−b, L_min 3 mm); median and max | b 1.2–1.6. Median 4–8 mm (0.25) to 10–20 mm (1.0). Max 40 mm (0.25) to 100 mm (1.0); longer goes to DAMAGE S-rules. Depth/length 0.2–0.5; depth ≤6 mm at 0.25. | I |
| E5 | Chip clustering: count variance ÷ mean in 0.5 m windows | ≥1.2 (clustered, not evenly spaced) | I |
| E6 | Visible chips at F: chips ≥20 mm per m of edge | W: 0.25: 0.04–0.15 · 1.0: 0.5–1.5. C ×3–4. | I (from E3 × E4) |
| E7 | Band width at Z: |ΔL*| ≥2 zone measured perpendicular to the arris | 0.25: 3–8 mm · 0.5: 6–15 · 0.75: 8–20 · 1.0: 10–30. Wider by ×1.5–2 on the face that takes run-off or drips. | I←W1 (dirt in cracks), W15 (hand grime) |
| E8 | Band continuity: share of edge length carrying the band | W: 0.25: 40–70% · 1.0: 85–100%. C: 0.25: 70–100%. | I |
| E9 | Edge-row contrast at F: mean |ΔL*| of the 1-px edge row vs the adjacent face | 0.25: 3–6 · 0.5: 4–8 · 0.75: 6–11 · 1.0: 7–14. Top edges lighter (chalk, rain-wash); drip and lower edges darker and warmer (Δb* +1…+4). | I |
| E10 | Layer exposure: share of edge length by deepest visible layer (paint edges) | 0.25 (C): older paint/texture coat 8–20%, concrete ≤3%, chips only. 0.5: 20–35% / 5–12%. 1.0: 30–50% / 25–50%. | I←J18, J38 (repaint history) |
| E11 | Steel edges (rail tops, post corners, frames): ISO 4628-3 rust grade on edge strips | 0.25: Ri1–2 (0.05–0.5%), primer visible on 3–10% of top-rail edge · 0.5: Ri3 · 0.75: Ri4 · 1.0: Ri5 | S/2 W17 (classes); I (mapping) |
| E12 | Zone placement: ratio of chip density in contact bands (0–0.45 m, 0.8–1.5 m) to above-reach edges, same building | 2–4 at all a_E > 0. Stair nosings highest. | I←W15, J27–J28 heights |
| E13 | Roughness at hand-polished edges (jambs, rail tops 0.8–1.2 m) | −0.05 to −0.15 vs face, darker | I←W15 |
| E14 | Facade normal map: bevel width at F | ≤1 px. Visibility must come from albedo and roughness, not a soft wide bevel. | I |
| E15 | Separation from DAMAGE: chips >100 mm long, or deeper than half the cover, are counted by DAMAGE | No E-chip >100 mm; at a_D = 0 with a_E = 1, no spalls and no cracks | I |

### 8.2 DAMAGE family: cracks

| ID | Measure | Pass band | Origin |
|---|---|---|---|
| C1 | ρ(≥0.05–0.1), all visible cracks (Z mask, or generator widths) | 0.25: 0.2–0.6 · 0.5: 0.5–1.2 · 0.75: 1.0–2.0 · 1.0: 1.5–3.5 m/m² | I←W3, J19 |
| C2 | ρ(≥0.3) | 0.25: 0.03–0.15 · 0.5: 0.15–0.4 · 0.75: 0.3–0.8 · 1.0: 0.6–1.5 | I←J19 (0.11 repair-class), J31 (2 m/m² ceiling) |
| C3 | ρ(≥0.5) (MLIT Level 3) and ρ(≥2) | ≥0.5: 0.25: ≤0.03 · 0.5: 0.05–0.15 · 0.75: 0.15–0.4 · 1.0: 0.3–0.8. ≥2: 0 · ≤0.02 · 0.02–0.1 · 0.05–0.3. | I←J1 |
| C4 | Width distribution: median w, and p95/median | Median 0.1–0.2 mm (0.25) rising to 0.3–0.6 mm (1.0). p95/median 2–4. Right-skewed. | I←J2, J7 |
| C5 | Taper: mean width in the last 10% of length ÷ median, at free ends | ≤0.3. No crack with constant width (CoV of width along a crack ≥0.25). | S G5 (tips taper); I |
| C6 | Hierarchy: at each T, width of the terminating crack ≤ width of the through crack | ≥90% of Ts | S G14 (older wider); I |
| C7 | Orientation, length-weighted (excluding crazing and map patches) | Vertical 40–65%, diagonal 20–40%, horizontal 10–25% | I←W3, J29 |
| C8 | Corner coupling: share of diagonal length within 1 opening-width of an opening corner | ≥70% | S W3, J29, J30; I |
| C9 | Corner-crack incidence: openings with ≥1 corner crack | 0.25: 20–40% · 0.5: 40–70% · 0.75: 60–90% · 1.0: 80–100%. Lower floors and end bays ×1.3–1.5 per-corner probability vs top. Angle 45 ± 15°. Length 0.3–1.0 × opening width at ≤0.5. | S J29 (pattern); S/2 W25 (45°); I (rates) |
| C10 | Solid-panel vertical cracks: spacing in opening-free stretches | 1.5–6 m, ≤1.3 × storey height when no joints. Panels >3 m wide: ≥1 crack in 40–70% (0.25) to 90–100% (1.0). | S W3; S/2 W19; I |
| C11 | Thermal set: share of buildings or ends with top-storey inverted-V pairs; parapet vertical spacing | 0.25: 20–40% of building ends; parapet cracks every 1–3 m · 1.0: 70–100% | S J29 (pattern); I |
| C12 | Junction mix (structural network) | T ≥70%, Y ≤15%, X ≤5%. Angle histogram peaks at 90° and 180°. | S G14, G10; I |
| C13 | Topology of closed cells (structural network, a_D ≥0.75) | v̄ 4.0–4.6, n̄ 2.0–2.4. Reject v̄ ≥5.5 with n̄ ≥2.8 (the Voronoi look). | S G17; I |
| C14 | Tortuosity τ on 0.2–1.0 m segments | Structural 1.03–1.15. Crazing and map 1.05–1.25. No pixel-scale zig-zag (τ on 40 mm segments ≤1.05). | S/2 W23; S G10 (σθ 9–15°); I |
| C15 | Box-count dimension, structural network (F, boxes 0.1–5 m) | 1.05–1.3. >1.5 only with an earthquake tag. | S W24; I |
| C16 | Feature coupling: share of crack length within 0.5 m of openings, slab lines, joint lines or external corners | ≥60% at a_D ≤0.5; ≥40% at 1.0. Cracks never cross an opening. | I←J29, J10 |
| C17 | Joint lines: share of horizontal joint length (each floor) carrying a crack, efflorescence or leak line | 0.25: 5–20% · 1.0: 20–60% | S J8, J3 (joints are weak); I (rates) |
| C18 | Crazing and paint-cracking patches (Z only): area share and cell size | Area 0.25: 0–3% · 1.0: 10–30%. Cells: crazing 12–40 mm; texture coat 4–10 mm; top coats 1–3 mm. Y-share 30–60%. At F, ≤3 ΔL* texture change. | S W1; S G12–G13 (cell ∝ thickness); I |
| C19 | Visibility at F (class-wise ΔL* of the 1-px crack line incl. halo) | Hairline ≤3 (only where dirt-highlighted). 0.2–0.5 mm: 3–8. 0.5–1 mm: 5–10. ≥1 mm: 8–20. Flag a "drawn-on" look if hairline ΔL* >5. | I (§3.1) |
| C20 | Halo at Z: width each side and darkening, for w ≥0.2 | 2–6 mm, 10–30% albedo drop. Wider below the crack. Green-black tint allowed on north and shaded faces. | S W1 (dirt makes cracks obvious); I |
| C21 | Efflorescence: share of crack length (w ≥0.2) with a white trail; trail size | 0.25: 3–10% · 1.0: 20–50%. Run 30–300 mm, width 5–40 mm. Located at joints, soffits, parapet bases, sills. | S J20, J15, W7 (definitions); I (rates) |
| C22 | Rust bleed: share of corrosion cracks (parallel to edges and bars) with stain; stain run | 0.25: ≥50% · ≥0.5: 100%. Run 50–500 mm. Any rust-stained crack counts as a Level-3 feature in the stats. | S J1, J24; I |
| C23 | Repairs: share of ≥0.3 mm crack length under a repair stripe; stripe width | 0.25: 50–90% · 0.5: 30–60% · 1.0: 10–40%, aged, many re-cracked at their edges. Width: 10–15 mm U-cut, 30–50 mm injected, 50 mm buffer. Port scars every 200–300 mm. | S J10 (dimensions); I (shares) |

### 8.3 DAMAGE family: spalls, delamination, chunk loss

| ID | Measure | Pass band | Origin |
|---|---|---|---|
| S1 | Spalled area share of wall (missing cover ≥5 mm deep) | 0.25: 0.01–0.1% · 0.5: 0.1–0.5% · 0.75: 0.5–3% · 1.0: 3–10% | S J25 (3.7–9.9% at 75 yrs unmaintained); I |
| S2 | Spall count per 100 m² of facade (≥30 mm across) | 0.25: 0.5–4 · 0.5: 4–15 · 0.75: 15–40 · 1.0: 40–120 | I←J19 (0.1 exposed-bar spots/m² on concrete parts), J25 |
| S3 | Size: equivalent diameter, median / p90 / max | Median 60–120 mm. p90 200–400 mm. Max 300 mm (0.25) to 1–2 m merged runs (1.0). Elongation along bar or edge 1.5–4. | S J25 (5–10 cm, avg 10 cm); S W7 (150 mm class); I |
| S4 | Depth classes: share 5–20 mm vs ≥20 mm or bar-exposing | 0.25: ≥70% in 5–20 mm (MLIT L2) · 1.0: ≥60% bar-exposing, 10–30% behind the bars (Hashima V) | S J1, J24; I |
| S5 | Location: share of spall count within 150 mm of an external edge, corner, slab nose, parapet top or sill | ≥50% at all a_D; slab noses and drip lines 20–40% | S J14 (corners, under windows); S/2 J20 (handrail tops, corridors); I |
| S6 | Cover consistency: spalls exposing bars only where local cover (from the cover field) <25 mm | ≥90% | S J25; I |
| S7 | Wet-face bias: spalled share on the wettest face ÷ driest face | 1.5–2.5 | S J25 (9.9% vs 5.2%) |
| S8 | Bars: exposed bar length per m² of spalled area; visible section loss | 2–6 m/m². Section loss and rust scale at ≥0.75. Bowing outward 5–30 mm at 1.0. | I←J24 (grades) |
| S9 | Spall floor at Z: aggregate visible where depth ≥10 mm; floor roughness; rust halo around bars | Aggregate 5–25 mm (rounded on old blocks). Roughness 0.85–0.95. Fresh floor +5–10 L* vs weathered. Rust halo 10–40 mm. | S/2 J36; I |
| S10 | Delamination (no loss yet), a_D ≥0.5: drummy area outlined by cracks parallel to the edge, bulge | Area 2–5 × spalled area. Outline cracks 0.2–1 mm. Bulge 0.5–3 mm. | I←J15 (grade 3 includes delamination) |
| S11 | Patch repairs (maintained states): share of spall sites carrying a mortar patch; patch size | 0.25: 60–90% patched (50–300 mm, ≤0.25 m²) · 1.0: patches present but 30–60% failed or edged by cracks | S J9 (≤0.25 m² rule); I |
| S12 | Chunk loss (geometry, Houdini): share of slab-edge and corner length with loss ≥30 mm deep and ≥150 mm long; per-bay count of chunks ≥200 mm | 0.25: 0–0.5% · 0.5: 0.5–2% · 0.75: 2–8% · 1.0: 10–30%, 0.5–2 chunks per 10 m² bay. Bars visible in ≥70% of chunks. | I |
| S13 | MLIT spall-risk score on inspection units (dwelling facades): (n₃ + 0.67·n₂)/N | 0.25: <0.10 · 0.5: 0.10–0.27 · 0.75: ≥0.27 (fails MLIT test) · 1.0: ≥0.6 | S J15 (rule and threshold); I (mapping) |
| S14 | Paint flaking (spray tile): ISO 4628-5 area class | 0.25: 0–1 (≤0.1%) · 0.5: 2–3 (0.3–1%) · 0.75: 4 (3%) · 1.0: 5 (≥15%), flakes 3–30+ mm. May belong to the weathering family; included here for the derelict stage. | I (ISO classes from memory, not re-checked) |

### 8.4 DAMAGE family: derelict elements (geometry and material swaps)

| ID | Measure | Pass band | Origin |
|---|---|---|---|
| X1 | Railing rust (ISO Ri) per bay; rust streaks below posts | 0.25: Ri1–2, streaks at 10–30% of posts · 0.5: Ri3, 40–70% · 0.75: Ri4, 80–100% · 1.0: Ri5, 100%. Streak width 1–2 × post at source, 2–4 × after 0.3–1 m. | S/2 W17; S W16; I |
| X2 | Railing bends: share of bays with top-rail deflection >20 mm; magnitude | 0.25: 0 · 0.5: ≤2% · 0.75: 5–15% (20–80 mm) · 1.0: 15–40% (50–300 mm, posts tilted 5–30°) | I (no data found) |
| X3 | Missing infill bars ("slots") and whole bays | Infill 0 · ≤0.5% · 1–5% · 5–30%, clustered at corroded bases. Whole bays 0 · 0 · 0–3% · 5–15%. | I |
| X4 | Glazing: share of panes broken or missing; sashes missing | 0.25: 0–0.5% · 0.5: 0.5–2% · 0.75: 10–40% on floors 1–3, 5–15% above · 1.0: 70–100% glass gone, 10–40% sashes missing. Wired glass stays in place, cracked. | S W14 (6% missing, unmaintained); S/2 W26 (Hashima); I |
| X5 | Window frames: steel frames rusted at sills, swollen, spalling the concrete around cast-in sills | 1.0: ≥50% of steel frames with sill corrosion | S W14; I |
| X6 | Balcony partitions (隔て板) broken or missing | 0 – 1% · 1–3% · 10–30% · 30–70%; frames remain | S/2 J37 (board type); I |
| X7 | Spall debris and cleanliness | Debris at ground within 0.15 × height of the wall, only at ≥0.75 | S J25 (7 m from 47 m) |
| X8 | Roof and slab collapse (story option, 1.0 only) | ≤1 per building, at top-floor roof slabs | S J24 (Hashima No. 30, 2020–2024) |

### 8.5 Amount, condition and age

| a_D | Condition | Typical case | Source anchors |
|---|---|---|---|
| 0 | New, or just through a large repair | All cracks sealed, no open ≥0.2 mm | J10 |
| 0.25 | Aged and maintained, 8–15 years since the last large repair | Most inhabited UR and prefectural stock built 1960s–80s | J1 L1–2, J14 light–medium, J24 I–II |
| 0.5 | Neglected: one cycle missed, 25–30 years since repair | Rust-stained cracks at edges, spalls at slab noses | JSCE III-1/III-2 (J31), J14 medium–heavy |
| 0.75 | Vacant or awaiting demolition | Fails MLIT spall-risk test; windows partly broken | J15 threshold, J24 III–IV |
| 1.0 | Derelict, abandoned 20–50 years | Hashima- or Matsuo-like; 3–10% spalled; glass mostly gone | J24 IV–V, J25 |

To drive amounts from age: use A (years since construction) and R (years since the last large repair) [I]:
- Maintained: a_D ≈ 0.08 + 0.015·R, capped at 0.4.
- Unmaintained since construction: a_D ≈ 0.2 + 0.008·A.
- Abandoned for Y years: a_D ≈ 0.6 + 0.01·Y, capped at 1.

Re-tune these against gate picks.

### 8.6 What the gate should reject

All of these checks are [I], unless a source is marked.

- **Voronoi-looking structural cracks:** Y-dominated, v̄ ≈ 6, hexagonal cells at metre scale (C12, C13).
- **Crack widths:** constant width, untapered tips (C5); hairlines drawn dark at facade scale, ΔL* >5 (C19).
- **Placement:** cracks ignoring openings, slabs and joints, or crossing openings (C16); isotropic orientation on walls, vertical share <30% (C7).
- **Path shape:** ruler-straight cracks (τ <1.02 over 1 m), or pixel zig-zag (C14).
- **Spalls:** spalls scattered mid-wall (S5 <50% near edges); spalls exposing bars where cover is ≥25 mm (S6); spalls without rust halos at ≥0.5.
- **Edges:** uniform bevels (E2), evenly spaced chips (E5), or a continuous outline band at 0.25 (E8 >90% on W).
- **Derelict:** a derelict facade (a_D = 1) with intact glazing and straight railings. All X-rules must move together with the S-rules.

---

## 9. Not found, and what to search next

| Gap | Why unchecked | Next step |
|---|---|---|
| UR (都市再生機構) 保全工事共通仕様書 | Site returned 403 | Try a cached copy, or ask the user |
| Danchi crack density (m/m²) by age | No survey found; §2.4 is anchored estimate | Search J-STAGE / AIJ 梗概 for 公団住宅 or 公営住宅 外壁 ひび割れ 密度 調査 |
| Cover and carbonation in 1960s–70s danchi | Not found; Finnish and Japanese-bridge analogues used | Search 公団住宅 かぶり厚さ 実測 / 中性化 実態調査 |
| Spall (爆裂) count per m² from public-housing repairs | Only one sample estimate | Search 爆裂 箇所 ㎡ 実数精算 団地 |
| Inducer-joint rules (JASS 5: spacing ≈3 m, section loss ≥1/5) | Not verified; the MLIT 3–4 m joint table was verified | Re-search JASS 5 誘発目地 |
| Arris rounding by age, chip rates, chip sizes | No data anywhere; all E-rules are [I] | Could be measured from photos of real danchi at known ages: a good gate-calibration task |
| Glass breakage against years vacant; railing bend magnitudes | No data | Abandoned-building photo surveys (Pripyat, Detroit, Ikeshima, Matsuo) |
| Gunkanjima survey paper (楠・今本・野口・下澤, JCI Proc. 35, pp. 787–792, 2013) | Cited but not retrieved | Fetch from JCI data site |
| ISO 4628-4/-5, ACI 224R Table 4.1, BRE Digest 251 class values | Quoted from memory, tagged [I] | Re-check |
| A numeric T vs Y fraction for real concrete crack networks | Not found | — |

---

## 10. Sources

✓ = I re-read the page or PDF in this session. Others were read by the delegated research pass.

**Japan: standards, specifications, surveys**
- J1 ✓ MLIT, 住宅紛争処理の参考となるべき技術的基準 (Notice 1653 of 2000, amended 2006): https://www.mlit.go.jp/common/001032016.pdf
- J2 ✓ JCI ひび割れ調査・補修・補強指針 2013, overview (BELCA): https://www.belca.or.jp/hibiware.pdf
- J3 JCI 2003 guideline Table 4.1 (Higashikagawa City): https://www.higashikagawa.jp/material/files/group/16/00825069.pdf
- J4 JCI ひび割れ指針 2022 FAQ: https://www.jci-net.or.jp/j/publish/standard/pdf/r-002_FAQ.pdf
- J5 JCI 2013 guideline overview: https://jci-net.or.jp/~hibiware/files/コンクリート工学会指針20140512.pdf
- J6 AIJ crack-control values (Tohoku Univ. paper): https://www.archi.tohoku.ac.jp/labs-pages/PBEE/research/paper/2021RCPD.pdf
- J7 MLIT Kantō (AIJ shrinkage guideline table 3.2.4): https://www.ktr.mlit.go.jp/ktr_content/content/000717240.pdf
- J8 JCI Proc. 35 (carbonation exposure, joints): https://data.jci-net.or.jp/data_pdf/35/035-02-1126.pdf
- J9 公共建築改修工事標準仕様書 (建築工事編) 平成28年版: https://www.mlit.go.jp/gobuild/content/001879403.pdf. ✓ for joint sizes and table 4.5.1.
- J10 同 令和4年版: https://www.mlit.go.jp/gobuild/content/001879363.pdf. ✓ for U-cut, injection, buffer, extra coats, patch matching, table 4.4.2, anchor pins (strips).
- J11 Sika Japan concrete repair brochure: https://jpn.sika.com/dms/getdocument.get/90189343-e4fa-4b57-baca-4a681784cc02/SRK003_Concrete_repair-.pdf
- J12 MAFF, crack width vs corrosion (open channels): https://www.maff.go.jp/j/council/seisaku/nousin/gizyutu/h26_2/pdf/siryou4-2-4.pdf
- J13 Osaka City bridge damage criteria: https://www.city.osaka.lg.jp/kensetsu/cmsfiles/contents/0000011/11173/kyodo1.pdf
- J14 ✓ Noguchi, 既存RC造建築物の調査・診断・余命予測・補修の現状 (MEXT council, 2013): https://www.mext.go.jp/b_menu/shingi/chousa/shisetu/027/shiryo/__icsFiles/afieldfile/2013/06/18/1336196_02.pdf
- J15 ✓ MLIT Housing Bureau, 外壁等剥落 判定式の検討 (10 buildings, 903 points): https://www.mlit.go.jp/jutakukentiku/house/content/001407994.pdf
- J16 Mankan, consultant survey on repair quantity variation (2019): https://www.mankan.or.jp/cms-sys/wp-content/uploads/2019/08/1908_tyousa.pdf
- J17 MLIT, 令和3年度 マンション大規模修繕工事実態調査: https://www.mlit.go.jp/jutakukentiku/house/content/001477900.pdf
- J18 Repair-cycle guidance: Mankan seminar 2023, https://www.mankan.or.jp/cms-sys/wp-content/uploads/2023/03/872980a9db8306c92831be7c274ca21a.pdf, and MLIT press release 2021, https://www.mlit.go.jp/report/press/content/001425184.pdf
- J19 ✓ Sample repair estimate (blog): https://manshion.runkodaira.com/quotation-check2/
- J20 ✓ Kashiwabara sample building diagnosis report: https://www.kashiwabara.co.jp/assets/pdf/building_report_sample.pdf
- J21 Painting contractor article on repairs showing through paint: https://meetsmore.com/services/outdoor-wall-painting/media/88475
- J22 Condo practice pages: https://daikibo.mansion-support.com/ · https://kashiwabaralife.com/mansion/article/shitajihoshukouji · https://shintoa-tosou.jp/blog/substrate-repair-for-large-scale-repairs/
- J23 JCI Proc. 39, 4-year exposure on Gunkanjima: https://data.jci-net.or.jp/data_pdf/39/039-01-1271.pdf
- J24 ✓ Noguchi, Rehabilitation and Preservation of Extremely Damaged World Heritage Concrete Structures (JCI-ACI 2025): https://www.jci-net.or.jp/~7th_jci-aci_joint_seminar/pdf/JCI-ACI2025-15_Noguchi.pdf
- J25 ✓ Su, Imamoto, Noguchi et al., Former Shime Mining Office Vertical Derrick (DBMC 2020): https://www.scipedia.com/wd/images/3/3b/Draft_Content_437235182p986.pdf
- J26 Building Standard Law Enforcement Order, art. 79 (cover): https://laws.e-gov.go.jp/api/1/articles;lawId=325CO0000000338;article=79
- J27 Same order, art. 126 (railing height): https://laws.e-gov.go.jp/api/1/articles;lawId=325CO0000000338;article=126
- J28 Tokyo child-raising housing guideline (railing gaps, handrails): https://www.juutakuseisaku.metro.tokyo.lg.jp/documents/d/juutakuseisaku/child-care-nintei-17_01
- J29 ✓ Yokoo & Tsunoda 1957, structural cracking of RC buildings from shrinkage (Kyoto Univ. DPRI Bulletin 16): https://repository.kulib.kyoto-u.ac.jp/server/api/core/bitstreams/1490d9c2-f808-4ba1-8f89-c7946a454428/content
- J30 JCI Proc. 35, FEM of cracks at wall openings: https://www.data.jci-net.or.jp/data_pdf/35/035-01-1079.pdf
- J31 ✓ Yamamoto 2019, corrosion crack width and ASR crack density (PC lecture): https://jpci.or.jp/downroad/47-tokubetu-kouen/47_oosaka.pdf
- J32 ✓ Hokkaido Research Org., prefectural RC housing deterioration (figures only): https://www.hro.or.jp/upload/51544/R6_seikahoukokukai_siryou.pdf
- J33 Kikusui catalogue (waterproof multi-layer amounts): https://www.kikusui-chem.co.jp/products/catalog/cat_045_ser_k.pdf
- J34 Japanese bridge and railway cover vs spalling (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC8269461
- J35 Hokkaido Univ. keynote, corrosion–cracking (Alonso, Vidal): https://eprints.lib.hokudai.ac.jp/repo/huscap/all/54506/KeynoteLecture_5.pdf
- J36 Tokyo Metropolitan construction spec (aggregate sizes): https://www.kensetsu.metro.tokyo.lg.jp/content/000063093.pdf
- J37 Balcony partition boards: https://lifestyle.assist-all.co.jp/?p=4944 · https://www.chiyoda-ute.co.jp/form_download/download_exe/pdf/catalog_keikaru-sogou.pdf
- J38 DBMC 2020, coatings and repaint cycles of Tokyo condominiums: https://www.scipedia.com/wd/images/2/2b/Draft_Content_395837161p932.pdf
- J39 Univ. of Tokyo feature on Hashima: https://www.u-tokyo.ac.jp/focus/en/features/z0508_00009.html
- J40 J-STAGE コンクリート工学 56(9) (Gunkanjima No. 30): https://www.jstage.jst.go.jp/article/coj/56/9/56_737/_pdf/-char/ja
- J41 Wikipedia (background only): https://ja.wikipedia.org/wiki/端島_(長崎県) · https://ja.wikipedia.org/wiki/松尾鉱山

**International engineering**
- W1 ✓ NRMCA CIP 3, Crazing: https://www.nrmca.org/wp-content/uploads/2021/01/03pr.pdf
- W2 NRMCA CIP 7, Cracks in basement walls: https://www.nrmca.org/wp-content/uploads/2021/01/07pr.pdf
- W3 ✓ FEMA US&R Structures Module 1C: https://www.fema.gov/pdf/emergency/usr/module1c.pdf
- W4 FHWA ASR Field Identification Handbook: https://www.fhwa.dot.gov/pavement/concrete/asr/pubs/hif12022.pdf
- W5 FHWA ASR Surveying and Tracking Guidelines: https://www.fhwa.dot.gov/pavement/concrete/asr/pubs/hif12046.pdf
- W6 FHWA PCC pavement distress, ch. 4: https://www.fhwa.dot.gov/publications/research/infrastructure/pavements/pccp/97146/chaptr04.cfm
- W7 ✓ AASHTO Manual for Bridge Element Inspection, 2nd ed. (via Louisiana DOTD guidance): https://dotd.la.gov/media/xvlnxv1j/snbi_condition_rating_guidance.pdf
- W8 ✓ Lahdensivu 2021, Visible corrosion damage in carbonated RC (Nordic Concrete Research 65): https://reference-global.com/download/article/10.2478/ncr-2021-0015.pdf
- W9 Tampere thesis on balcony corrosion: https://trepo.tuni.fi/handle/10024/114637
- W10 Frontiers in Materials 2020, corrosion-induced cracking: https://www.frontiersin.org/journals/materials/articles/10.3389/fmats.2020.00041/full
- W11 arXiv 2409.05889, time to cracking: https://arxiv.org/html/2409.05889v1
- W12 Qiao 2016, crack patterns of concrete (Nagoya thesis): https://nagoya.repo.nii.ac.jp/record/22925/files/2016-Di_Qiao_Crack_patterns_of_concrete.pdf
- W13 PolyU, corrosion of steel in concrete (Hong Kong): https://research.polyu.edu.hk/en/publications/corrosion-of-steel-in-concrete-a-basic-understanding-and-research/
- W14 NPS Preservation Tech Note, Windows 17 (steel windows): https://www.nps.gov/orgs/1739/upload/tech-note-windows-17-repair-steel-windows.pdf
- W15 Getty Conservation Institute, stair wear case: https://www.getty.edu/conservation/publications_resources/teaching/case/olita/building/stairs.html
- W16 ASTM D610 summary: https://www.micomlab.com/blog/corrosion-testing/astm-d610-test-now-offered-at-micom-laboratories/
- W17 ISO 4628-3 via TCVN 12005-8: https://thuvienphapluat.vn/TCVN/Cong-nghiep/TCVN-12005-8-2017-ISO-4628-3-2016-Son-vec-ni-Danh-gia-su-suy-bien-cua-lop-phu-917594.aspx
- W18 Sika Thorolastic data (elastomeric film thickness): https://usa.sika.com/content/dam/dms/us01/t/sika-thorolastic-750.pdf
- W19 Imperial College, restrained wall cracking (EC2 bound): https://spiral.imperial.ac.uk/handle/10044/1/105494
- W20 Crack width percentiles (PMC): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10449931/
- W21 CRCP crack-width variation (MDPI): https://www.mdpi.com/2076-3417/11/2/785/html
- W22 Tortuosity definition (arXiv 2605.08265): https://arxiv.org/pdf/2605.08265
- W23 Crack path length +14.7% (Erbakan Univ.): https://acikerisim.erbakan.edu.tr/items/690f9d82-e331-4241-8802-0ec08e2a85e9/full
- W24 Fractal dimension of damaged RC columns (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC11643610/
- W25 Eng-Tips thread, 45° corner bars: https://www.eng-tips.com/viewthread.cfm?qid=12115
- W26 Hashima visitor page: https://japanuncharted.com/nagasaki/island/hashima-ghost-island
- W27 Pripyat background: https://wikipedia.classicistranieri.com/en/articles/p/r/y/Prypiat%2C_Ukraine_86bb.html
- W28 Balustrade calcs (deflection limit): https://www.balconette.co.uk/content/uploads/86424449-01b1-42e9-8010-7deceffc3dcd/mlno230820-milano-system-structural-calcs.pdf

**Graphics, physics, production**
- G1 Paquette, Poulin & Drettakis 2002, paint cracking and peeling: https://graphicsinterface.org/wp-content/uploads/gi2002-8.pdf
- G2 Gobron & Chiba 2001: https://infoscience.epfl.ch/record/162173
- G3 Federl & Prusinkiewicz 2004: https://algorithmicbotany.org/papers/fracture.iccs2004.pdf
- G4 Mould 2005, Image-guided fracture: https://gigl.scs.carleton.ca/papers/crack.pdf
- G5 Desbenoit, Galin & Akkouche 2005: https://perso.liris.cnrs.fr/egalin/Articles/2005-cracks.pdf
- G6 Iben & O'Brien 2006, Generating surface crack patterns (link as reported; usual home is Berkeley graphics): https://objf.ai/papers/Iben-GSC-2006-09/
- G7 Valette et al. 2008: https://diglib.eg.org/handle/10.2312/CGF.v27i1pp047-062
- G8 Glondu et al. 2012, image-driven fracture: https://graphics.cs.yale.edu/sites/default/files/imagedrivenfracture-final.pdf
- G9 ✓ Tarasevich, Eserkepov & Vodolazskaya 2025, hierarchical desiccation cracks: https://arxiv.org/html/2501.07882v1
- G10 ✓ Tarasevich, Eserkepov & Burmistrov 2026, algorithms for hierarchical crack networks: https://arxiv.org/html/2603.24171v1
- G11 Bohn, Douady & Couder 2005, PRL: https://link.aps.org/doi/10.1103/PhysRevLett.94.054503
- G12 Bohn et al. 2005, PRE Part II: https://www.phys.ens.fr/~foldingslidingstretchinglab/papers/A22_PhysRevE_71_046215.pdf
- G13 Goehring et al., crack patterns review (arXiv 1211.6762): https://ar5iv.labs.arxiv.org/html/1211.6762
- G14 West 2016, pattern evolution in desiccation cracks (Toronto): https://www.physics.utoronto.ca/~nonlin/preprints/MWest_479_report_2016.pdf
- G15 Physics Today, Cracking mud…: https://physicstoday.aip.org/features/cracking-mud-freezing-dirt-and-breaking-rocks
- G16 Cornstarch film crack scaling: https://arxiv.org/abs/1807.06126
- G17 Domokos et al. 2020, Plato's cube and the natural geometry of fragmentation: https://pmc.ncbi.nlm.nih.gov/articles/PMC7414180
- G18 Goehring et al. 2010, Soft Matter: https://pubs.rsc.org/en/content/articlelanding/2010/sm/b922206e/unauth
- G19 EPL 2010, T vs Y junction selection: https://epljournal.edpsciences.org/10.1209/0295-5075/89/26002
- G20 Adobe Substance 3D Designer node library: https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/substance-graphs/nodes-reference-for-substance-graphs/node-library/node-library
- G21 Polycount threads: https://polycount.com/discussion/comment/2566259 · https://polycount.com/discussion/comment/2732163 · https://polycount.com/discussion/comment/2639266
- G22 80.lv, Kazlachev, improving cracks in Substance: https://80.lv/articles/breakdown-improving-cracks-on-your-3d-materials-in-substance-3d
- G23 80.lv, Swing, concrete and cracks in Substance Designer: https://80.lv/articles/generating-concrete-and-cracks-in-substance-designer
- G24 80.lv, Melin, procedural cracks on 3D surfaces: https://80.lv/articles/this-procedural-setup-lets-you-apply-cracks-to-3d-surfaces/
- G25 SideFX forum, crack curves: https://www.sidefx.com/forum/topic/83631/
- G26 SideFX Copernicus overview: https://sidefx.com/products/whats-new-in-h205/copernicus
- G27 Godot 4.2 decals: https://docs.godotengine.org/en/4.2/tutorials/3d/using_decals.html
- G28 Unreal Marketplace, customizable cracks: https://www.unrealengine.com/marketplace/en-US/product/customizable-cracks
