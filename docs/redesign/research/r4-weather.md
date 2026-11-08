# How environment and weather act on objects: edges first

Extends `believability.md`, `realism.md`, `techniques.md` and r3 (PCI wetting, 20–30×
corners, zigzag line, dirt/white washing, sill ends, rust runs, clusters) without repeating
them. [S] = sourced (number in the list), [I] = inference.

**The user's observation holds.** Impact, water, wind, frost, sun and corrosion each concentrate
at arrises. A divot is itself an edge and inherits every rule below.

## 1. Mechanics: why edges chip and faces pit

- **The force needed falls linearly toward the edge.**
  - Edge-chip tests load an indenter at distance *d* from an arris. The chipping force rises
    linearly with *d*: this "edge toughness" is 90–530 N/mm across ceramics [S3–S5].
  - Near the edge the crack accelerates toward the free face, at a position set "solely by
    geometry" [S3].
  - On a face the same blow is confined on every side, so it makes only a small Hertzian cone
    or crater [S7, I].
- **One blow, one scar across the edge.**
  - The crack starts under the contact and curves out of the *other* face, giving "the classic
    shape of flake which is always thickest at the point of indentation" (NPL) [S3].
  - The struck face keeps a small crushed platform set back *d*; the adjacent face carries the
    shell.
  - Two similar divots either side of one arris is not a single-impact result [I].
- **Profile.** Conchoidal [S8]:
  - a concave negative bulb near the arris, then ripples;
  - a feathered (thin) or hinged (rounded step) termination.

  The force angle alone determines the chip shape [S5]. Off-axis cracks start at about 70° to
  the edge normal, so chips are slightly asymmetric [S3]. Platform depth and edge angle matter
  more than blow strength [S9], so acute edges chip more readily [I].
- **Cone angles.**
  - Glass: the Hertzian cone runs about 22° to the surface [S7].
  - Concrete: breakout is modelled at about 35° (1:1.5) and reaches 1.5× the edge distance on
    either side [S10], so a concrete chip of depth *d* runs about 3*d* along the edge [I].
- **Corners beat edges.** ASTM C216 allows chips of 1/8 in from an edge but 1/4 in from a corner
  [S35]. Corners also round first in weathering [S39].
- **Spalling.**
  - Surface spalls (frost, de-icer) are under 20 mm deep. Corrosion spalls break at bar depth, in
    larger pieces [S12].
  - Corner bars take chlorides from two faces and corrode much earlier [S14].
  - Widely spaced bars give corner spalls; closely spaced bars link into a delamination plane
    parallel to the face [S11].
  - The hidden delamination is often 2–3× the visible spall [S13].
- **Arris profiles** [I]:
  - **Concrete:** a rough scar at about 35° studded with aggregate, with a flat floor at the bar.
  - **Fine stone or brick:** a smoother shell.
  - **Sandstone:** granular loss and thin flakes of about 2 mm [S27].
  - **Painted steel:** a dent plus paint lost on the arris.

**Rules (geometry):**
- **Centre each chip on the arris:** the cutter centre within 0.2–0.5 *d* of it, one cutter per
  impact.
- **Make it asymmetric:**
  - platform-face bite 0.3–0.6 *d*;
  - shell-face length 2–3 *d*;
  - length along the edge 2–3 *d*;
  - depth tapering to a feather, or ending in a 1–3 mm hinge step (30 %).

  For top edges the shell goes on the vertical face, since knocks come from above [I].
- **Corners:** chips 1.5–2× the edge size, at 2–3× the density within 0.1–0.3 m of the corner
  [S35, I].
- **Band:** 90 % of chips within 40 mm of the arris. PCI keeps drips 38 mm in "to avoid chipping"
  [S1].
- **Faces:** pits at most 0.3× the local chip size and 1/5–1/10 of the density. No face feature is
  larger than its nearest edge chip, unless it is a spall with a cause [I].
- **Corrosion spall:** a strip along the arris over a bar line, 20–50 mm deep with a flat floor
  and 1–2 bars exposed. The stain halo is 2–3× the spall [S11–S14, I].

## 2. Water

- **Tops collect, then shed at the edge.**
  - PCI: horizontal planes "collect the most dirt and are the most exposed to rain" [S1].
  - Wall run-off is slow (≤0.9 m/min). It breaks into streams that recur, broaden at ledges and
    follow undersides [S1].
  - Surface tension carries water back along soffits. Projections of 300 mm or more need a drip
    to throw water clear [S1]; the groove sits 5–20 mm back from the front edge [S34].
- **Detachment.** PCI: "Water will leave a drip at its lowest point" [S1]. That point is a sill
  end, a sag in a slab edge, a notch or a chip.
- **Vertical edges** gather run-off by secondary airflow and surface tension: outside corners,
  columns, inside corners of projections, mullions [S1].
- **Streak sources** [S1, I]:
  1. the ends of horizontal elements and their junctions with verticals;
  2. the low points of top edges;
  3. soffits without drips;
  4. the lower lips of recesses, openings and chips;
  5. joints and fixings.

  PCI ties streak length to the volume of water caught above [S1]. Drizzle gives "pronounced,
  random streaking"; heavy rain washes [S1].
- **Frost.**
  - Damage needs more than 75–80 % saturation [S16], and corners and edges are vulnerable to
    wetting [S15].
  - Copings and parapets are the most exposed brickwork [S41].
  - So scaling and arris loss go on the outer top edges of copings, sills and steps [I].
- **Base.**
  - Rising damp stops at a salt tide mark 0.5–1.5 m up, typically about 1 m [S28].
  - Salts crystallise where evaporation concentrates, and spall the surface [S28].
- **Biology.**
  - Growth sits on N and E faces, below sills, at drip points and at leaking gutters [S32].
  - Orange *Xanthoria* marks bird perches [S31].
- **A chip becomes a source** [I, consistent with S1, S37].
  - **On a top arris:** the notch is the edge's low point, so a stream starts there.
  - **On a vertical face:**
    - the divot's upper wall is sheltered, so dirt and crust stay;
    - its floor traps debris;
    - its lower rim drips.

  Gammaton tracing reproduces this "stain-bleeding" downward from defects and along cracks [S37].

**Rules (texture):**
- **Seed streaks** at:
  - local minima along every upward-facing edge;
  - both ends of every horizontal element;
  - the lowest rim point of each chip or recess over 1 cm.

  Use `len = k·sqrt(catchment)`, with k set so a 1 m sill gives a 0.5–1.5 m streak [I].
- **Shape:**
  - the head is the width of the notch and widens 1.2–2× down the streak;
  - opacity follows `1 − t^0.5`;
  - it fans out at the next ledge and restarts from the ledge's ends [S1, I].
- **Soffits:** without a drip, a dirt band on the soffit and a streak below its inner line; with
  one, the soffit stays clean.
- **Tops:** dirt × (1 − slope/0.05), strongest at the back of level ledges [S1, I].
- **Efflorescence** at stream ends and joints; **frost** scaling = top-face convexity × wetness
  [S1, S15].

## 3. Wind

- **Wetting.**
  - Rain sweeps toward vertical and top edges: "Typically, the top corners are most wetted,
    followed by the top and side edges" [S2].
  - Separation at the front top edges raises the catch near roofs [S43].
  - On 1–2 storey buildings, rain reaches the low walls and dirt patterns are rare [S1].
- **Lateral (vertical) edges.** Windward ones are washed pale, with flow concentrated down the
  corner [S1, S2]. Rounded corners reduce the edge wind speed [S1].
- **Shelter.**
  - Black gypsum crusts survive only where rain does not wash: under cornices and cantilevers, in
    the tops of recesses [S27].
  - Sheltered steel can corrode 3–5× faster [S25]. BRANZ found sheltered spots held 3–8× the
    salt, yet did not always corrode faster [S26].
- **Sand.** Most blown sand stays below 0.5 m and almost none rises above 2 m [S29]. It undercuts
    bases and leaves a cap [S29].

**Rules:**
- **One azimuth per site.**
  - Windward vertical edges get a washed band 0.1–0.5 m wide, value +3–8 %.
  - The lee gets dust and soot.
  - Crust or darkening goes under projections and in recess tops [I, S27].
- **Abrasion (dusty or coastal maps):** round and pit windward vertical edges, peaking at
  0.1–0.3 m and fading by 1 m [S29, I].
- **Coastal maps:** rust on sheltered metal at 1.5–3× [S25, S26, I].

## 4. Sun and temperature

- **UV.**
  - Horizontal faces fade fastest [S42, vendor].
  - Wood greys only 0.05–0.5 mm deep and erodes 34–101 µm/yr. Earlywood erodes faster, leaving
    latewood ridges [S30].
- **Paint by element** (NPS Brief 10) [S21]:
  - siding holds; eaves peel; balusters and sills crack and alligator;
  - intercoat cracks let moisture in, and they deepen into a reptile-skin grid.
- **Steel.**
  - Wet paint retracts from sharp edges [S23]. Edges and welds take 50–90 % of corrosion attacks
    [S22].
  - Hot-dip zinc is at least as thick on edges, so galvanised wear is more even [S24, weak].
- **Cracks.**
  - Diagonal cracks start at the re-entrant corners of openings [S18–S20].
  - Crazing forms hexes of ≤40 mm, ≤3 mm deep [S17].
  - Arrises cycle in temperature and moisture from two faces, consistent with corners
    weathering first [S39, I].

**Rules:**
- **Opening cracks:** 1 per 2–4 openings, starting at a corner, 30–60° off the bisector,
  0.3–1.5 m long and tapering. None start mid-face.
- **Crazing:** a Voronoi-edge normal at 15–40 mm cells, on smooth tops only [S17].
- **Peeling:** seeded at water sources and on horizontals, growing inward from the edges with an
  edge-distance × noise mask [S21, I].
- **Fade:** strongest on the sunny elevation and on tops; edges 1.2× the face [I].

## 5. Gravity and accumulation

- Dirt settles on level and gently sloped faces and at the low ends of large slopes [S1].
- Backward-sloping faces get streaky partial flow from above [S1].
- Debris collects in inside corners.
- Droppings and *Xanthoria* sit below perches: rail tops, ledges, sign tops [S31].

**Rules:**
- **Dust:** `N.y² × AO × (1 − washed)`. It peaks at inside corners and the backs of ledges, and is
  cleared within 2–5 cm of rain-exposed outer edges [I].
- **Droppings:** a splat field 0.1–0.5 m below 1 in 5 perches [I].
- **Moss and lichen:** on damp, shaded tops and drip landings only [S32].

## 6. Per material

| Material | Edges | Faces |
|---|---|---|
| Concrete | ~35° chips; corner-bar spalls; frost on top arrises | crazing, popouts, streaks [S1, S10–S17] |
| Brick/mortar | arris chips, corners 2×; face spall at copings and parapets | mortar recession forms a ledge that sheds streaks [S35, S41, I] |
| Render | cracks from opening corners | crazing, damp base band [S20, S28] |
| Painted steel | edges and welds first; rust runs from the arris | blisters at seams [S22, S23] |
| Galvanised | even; white rust in wet laps | dull grey [S24] |
| Aluminium | pitting in sheltered undersides [I] | chalky oxide |
| Glass | flow and streaks at frame and mullion edges | silicate stain from concrete above [S1, S33] |
| Wood | end-grain checks; raised grain | greying, about 0.1 mm/yr erosion [S30] |
| Asphalt | ravelling and cracking at joints and unconfined edges | oxidised pale grey [S40] |
| Stone | rounded corners; crust in shelter | scaling; washed exposed faces [S27, S39] |

## 7. Consolidated procedural rules

**(a) Geometry**
1. **Damage budget:** 70–85 % of the damage volume on arrises and corners (inside the cluster
   mask), 10–25 % as small face pits, about 5 % as caused spalls [I, consistent with S3].
2. **One impact = one asymmetric chip on the arris** (§1 ratios).
   - Reject mirrored pairs: a chip on the adjacent face within 2*d* along the edge, with a size
     ratio of 0.6–1.6.
   - Merge the pair or drop the smaller one [I].
3. **Exposure weight per edge** [I from S1, S2, S35]:

   | Edge | Weight |
   |---|---|
   | Top outer horizontal | 1.0 |
   | Windward vertical | 0.8 |
   | Other vertical | 0.5 |
   | Bottom | 0.3, or 0.9 in the 0–1 m contact band |
   | Inside corners | 0.1 |
   | Corner vertices | 1.5–2× the edges they join |

4. **Face pits:** radius ≤0.3× the local chip, power-law sizes, density ∝ exp(−dist/0.1 m) from
   the edge [I].
5. **Frost:** SDF `open` (3–6 voxels) on the outer top arrises of copings, sills and steps only
   [S15, S16].

**(b) Texture**
1. **Streak sources** (§2), with length ∝ sqrt(catchment). Emit them as a primvar.
2. **Dirt-washing or white-washing** by base cleanliness; both on old assets (r3).
3. **Wind:** washed windward verticals, a dirty lee, crust under projections.
4. **Dust** on tops × AO, cleared at the outer 2–5 cm; moss on damp, shaded tops.
5. **Paint loss** from the arris inward. Rust runs start at the lowest rim of each chip.
6. **One chain per chip:** the chip, then exposed substrate, then a streak from its lowest rim,
   then a damp or biofilm landing on the next ledge. Every layer reads the same chip id.

## Sources

1. PCI, Designer's Notebook DN-29: Weathering — https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf (read in full)
2. Blocken & Carmeliet, review of wind-driven rain research (2004) — https://aecb.net/wp-content/uploads/2024/11/Blocken_Carmeliet_A-review-of-wind-driven-rain-research-in-building-science-2.pdf (read)
3. Morrell et al., NPL Report MAT 76, edge chipping — https://eprintspublications.npl.co.uk/6736/1/MAT76.pdf (read)
4. Quinn & Lloyd, edge toughness (NIST) — https://www.nist.gov/node/717701
5. Quinn & Mohan, edge chips at force angles (NIST, 2008) — https://www.nist.gov/node/716156
6. Hoffman, Quinn & Quinn, indenter angle (AADR 2012) — https://websites.umich.edu/~sbayne/DMG/DMG-Publications/IADR-AADR-Meeting-Program-Books/2012-AADR-Tampa/2012-AADR-Tampa-CD/AADR12/Paper157234.html
7. Sun & Khaleel, Hertzian cone angles (ORNL/PNNL) — https://impact.ornl.gov/en/publications/limit-analyses-for-surface-crack-instantaneous-propagation-angles/
8. Lithic flake anatomy — https://en.wikipedia.org/wiki/Lithic_flake
9. Synthesis of Dibble et al. flaking experiments — https://ro.uow.edu.au/articles/journal_contribution/A_Synthesis_of_the_Dibble_et_al_Controlled_Experiments_into_the_Mechanics_of_Lithic_Production/27809310
10. IDEA StatiCa, CCD method / ACI 318 breakout — https://www.ideastatica.com/support-center/anchorage
11. Phase-field corrosion cracking (arXiv 2306.01903) — https://arxiv.org/pdf/2306.01903
12. Rimkus, concrete spalling — https://rimkus.com/article/all-about-concrete-spalling
13. Projul, delamination 2–3× visible spall (trade) — https://projul.com/blog/construction-structural-concrete-repair-guide
14. AAU, 2-D chloride ingress, corner bars — https://vbn.aau.dk/ws/files/10556578/Stochastic_analysis_of_the_multi-dimensional_effect_of_chloride_ingress_into_reinforced_concrete
15. NRC Canada CBD-116, frost action — https://web.mit.edu/parmstr/Public/NRCan/CanBldgDigests/cbd116_e.html
16. ACI University, 201.2R freezing and thawing — https://concrete.org/portals/0/files/pdf/webinars/aciu_2018_FreezingThawing201-2R16_Janssen.pdf
17. NRMCA CIP 3, crazing — https://www.nrmca.org/wp-content/uploads/2021/01/03pr.pdf
18. PCI Journal 2025, re-entrant corner cracking — https://www.pci.org/PCI_Docs/Publications/PCI%20Journal/2025/May-June/24-0009_Kang_JNL_MJ25.pdf
19. FEMA US&R structures module — https://www.fema.gov/pdf/emergency/usr/module1c.pdf
20. DESOI, plaster cracks — https://www.desoi.de/catalog/en/service/injection-abc/plaster-crack-11658/
21. NPS Preservation Brief 10 — https://www.nps.gov/orgs/1739/upload/preservation-brief-10-paint-problems-exterior-woodwork.pdf (read)
22. SINTEF, root causes of corrosion on painted steel — https://sintef.brage.unit.no/sintef-xmlui/handle/11250/3125983
23. Corrosionpedia, edge failure — https://corrosionpedia.com/definition/edge-failure
24. Galvanizing guidance (AGA-style; unverified attribution) — https://www.scribd.com/document/214100742/Chart ; AGA corners — https://galvanizeit.org/knowledgebase/article/taking-coating-thickness-measurements-on-corners
25. GAA design manual, microclimates — https://designmanual.gaa.com.au/index.php/painting/the-effect-of-microclimates/
26. BRANZ, positional corrosion — https://www.branz.co.nz/documents/1173/BRANZ-RN-Positional-Corrosion-2.pdf
27. USGS, gypsum crusts on sheltered surfaces — https://pubs.usgs.gov/gip/acidrain/5.html ; Fort McHenry sandstone — https://pubs.usgs.gov/of/1992/0541/report.pdf
28. Building Conservation, rising damp — https://buildingconservation.com/articles/risingdamp/risingdamp.htm
29. Aeolian processes; Ventifact — https://en.wikipedia.org/wiki/Aeolian_processes ; https://en.wikipedia.org/wiki/Ventifact
30. Williams et al., erosion rates of weathering wood — https://wfs.swst.org/index.php/wfs/article/view/884
31. British Lichen Society, *Xanthoria parietina* — https://britishlichensociety.org.uk/sites/default/files/files/Guide%20-%20Xanthoria%20parietina%20(2024).pdf
32. Prosoco Tech Note 101, biological growth — https://prosoco.com/app/uploads/2021/03/Tech-Note-101-Removal-of-Biological-Growth.pdf
33. Vitro TD-107, glass staining — https://www.vitroglazings.com/media/12ajakrw/vitro-td-107.pdf
34. Designing Buildings, drip groove — https://designingbuildings.co.uk/wiki/Drip_groove
35. ASTM C216 chippage limits (via search summary) — https://www.astm.org/c0216-19.html
36. Dorsey, Pedersen & Hanrahan, Flow and changes in appearance (1996) — https://graphics.stanford.edu/papers/flow
37. Chen et al., weathering by γ-ton tracing (2005) — https://faculty.cc.gatech.edu/~jarek/graphics/papers/15WeatheringChen.pdf (read)
38. Adobe, Dripping Rust generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dripping-rust
39. USGS, granite corners round first — https://pubs.usgs.gov/of/2004/1007/granite.html
40. Roads & Bridges, asphalt joint cracking and raveling — https://roadsbridges.com/asphalt/article/10581990/asphalt-answers-cracking-and-raveling
41. Canada Brick, weatherproofing masonry — https://canadabrick.com/wp-content/uploads/sites/2/2017/06/weatherproofing.pdf
42. Cabot, horizontal vs vertical wood (vendor) — https://cabotstain.com/en/how-to/prepare/nature-vs-exterior-wood-surfaces
43. Chen & Zhou, Eulerian WDR (Frontiers 2022) — https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2022.917514/full

Sources not marked "read" were taken from abstracts or search summaries.
