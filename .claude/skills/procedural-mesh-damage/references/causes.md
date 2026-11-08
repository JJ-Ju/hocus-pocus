# Causes: why edges break, how a chip is shaped, where use and industry strike

Research for review 31: NPL and NIST edge-chipping tests, lithic-fracture anatomy, concrete
breakout models, ASTM C216, PCI DN-29, concrete-repair literature, and building codes and
industrial-safety guidance. Numbers marked *(est.)* are estimates. The texture side of the same
causes is in `procedural-materials` (references/weather-and-use.md).

## Edges chip, faces pit

- **The force needed to chip rises linearly with distance from the edge.** Edge-chipping tests
  load an indenter a distance *d* from an arris, and the chipping force grows in proportion to
  *d*. Near the edge, the crack runs out to the free face. On a face, the same blow is confined
  on every side and makes only a small cone or crater.
- **One blow makes one scar across the edge.** The crack starts under the contact and curves out
  through the *other* face, giving a flake that NPL calls "always thickest at the point of
  indentation". The struck face keeps only a small crushed platform; the adjacent face carries
  the shell-shaped scar. Two similar divots either side of one arris are not what a single
  impact produces, and they read wrong.
- **Profile.** The scar is conchoidal: a concave hollow near the arris, then ripples. It ends
  either feathered thin or in a small rounded step (a hinge). The force angle sets the shape;
  acute edges chip more readily than square ones.
- **Breakout angle.** Concrete breaks out at about 35° to the face (a 1:1.5 slope) and reaches
  1.5× the edge distance to either side. A concrete chip of depth *d* therefore runs about 3*d*
  along the edge.
- **Corners beat edges.** ASTM C216 allows brick chips of 1/8 in from an edge but 1/4 in from a
  corner. Corners also round first when weathering.
- **Spalling** comes in two kinds:
  - **Surface spalls** from frost and de-icing salt are under 20 mm deep.
  - **Corrosion spalls** break at the depth of the steel bars, in larger pieces. Corner bars take
    chlorides from two faces and corrode first. Widely spaced bars give corner spalls; closely
    spaced bars join into a delamination plane parallel to the face. The hidden delamination is
    often 2–3× the visible spall.
- **Edge profiles by material:**
  - **Concrete:** a rough scar at about 35°, studded with aggregate, with a flat floor where it
    reaches a bar.
  - **Fine stone or brick:** a smoother shell.
  - **Sandstone:** granular loss and thin flakes about 2 mm thick.
  - **Painted steel:** a dent, with the paint lost along the arris.

## What photographs show

A study of about 75 photographs (review 31) of chipped steps, curbs, planters, slabs,
Jersey barriers and walls:
- **Runs, not single divots.** In 9 of 19 breaks, the damage was a run of overlapping bites,
  each 0.5–3 cm, along 20–60 cm of edge, with long intact stretches between runs. Elements had
  one run, occasionally two.
- **Shell breaks are rarer.** About 6 of 19 had one larger conchoidal break, 10–40 cm long and
  3–8 cm deep, deepest at the arris and feathering into one face.
- **One face loses.** On mid-edge breaks, one face lost most in about 12 of 15. On a horizontal
  top arris, the top lost a 1–3 cm sliver and the vertical face took the taller scoop. Both
  faces lost material only at three-face corners (3 of 19), as one wedge. No photo showed two
  big divots flanking one edge.
- **Where.** At or within 15 cm of a vertex in 7 of 19; at joints in 4 of 19. On vertical
  arrises, damage sat in the 0–1.2 m impact band. Cover spalls over bars were linear, 5–15 cm
  tall along the bar line, often on the soffit just behind a slab edge.
- **Whole-arris wear.** Old curbs and steps have the whole arris rounded by 5–15 mm, with the
  breaks inside that rounding.
- **Colour.** Fresh breaks are paler with rough exposed aggregate. Old breaks are rounded,
  dark and hold dirt. A mortar topping comes off as a flat-backed plate 2–3 cm thick.

## Rules for geometry

1. **Damage budget** *(est.)*: 70–85 % of the damage volume on arrises and corners (inside the
   cluster mask), 10–25 % as small face pits, about 5 % as spalls with a cause.
2. **Two scales on every edge.** A noisy wear radius along the whole arris (3–15 mm on old
   concrete), and inside it 0–2 runs per edge: each run is 20–60 cm of overlapping bites with
   power-law sizes of 0.5–3 cm, with at most one shell break of 10–40 cm. Most hotspots make a
   run, not one large anchor.
3. **One impact, one asymmetric chip, centred on the arris.** This applies to each bite and to
   a shell break.
   - Put the cutter centre within 0.2–0.5 *d* of the edge line. Use one cutter per impact.
   - The platform face loses 0.3–0.6 *d*.
   - The shell face loses 2–3 *d*, measured perpendicular to the edge.
   - The chip runs 2–3 *d* along the edge.
   - Depth tapers to a feather, or ends in a 1–3 mm hinge step about 30 % of the time.
   - On top edges, the shell goes on the vertical face, since knocks come from above *(est.)*.
   - Facets are rough, never planar; a smooth hull reads as carved. Fresh breaks are paler
     and grainy, old ones rounded and grimy.
4. **No mirrored pairs.** Reject a chip on the adjacent face within 2*d* along the edge whose
   size ratio is 0.6–1.6; merge the pair or drop the smaller one.
5. **Corners:** chips 1.5–2× the edge size, at 2–3× the density within 0.1–0.3 m of the corner.
6. **The band:** about 90 % of chips within 40 mm of the arris. PCI keeps drip grooves 38 mm in
   from the edge "to avoid chipping".
7. **Faces get small damage.** Pits are at most 0.3× the size of nearby edge chips, at 1/5–1/10
   of their density, falling off as exp(−distance / 0.1 m) from the edge. No face feature is
   larger than its nearest edge chip unless it is a spall with a cause.
8. **Edge exposure weights** for choosing where damage goes:
   - top outer horizontal edge 1.0;
   - windward vertical 0.8;
   - other vertical 0.5;
   - bottom 0.3, or 0.9 inside the 0–1 m contact band;
   - inside corners 0.1;
   - corner vertices 1.5–2× the edges they join.

   Impact damage, as opposed to weather, is weighted by what the photographs showed:
   vertices ×3, joints ×2, vertical arrises at 0–1.2 m ×3, and above 2.5 m ×0.2. Cover spalls
   at slab edges are the exception.
9. **Corrosion spall:** a strip along the arris over a bar line, 20–50 mm deep with a flat floor
   and 1–2 bars exposed. Its stain halo is 2–3× the spall.
10. **Frost:** SDF `open` (3–6 voxels) on the outer top arrises of copings, sills and steps only.
11. **Every chip is an edge.** Its lowest rim point becomes a streak source. A chip in a top edge
    becomes that edge's low point, where water leaves. Write the chip's id and its lowest rim
    point so the materials can start a streak there.

## Use and industry: where strikes land

Heights come from building codes and from the protection products made for each strike zone.

| Damage | Rule |
|---|---|
| Worn stair tread | erosion depth `dmax · lane(x)^1.5 · nose(z)`. `lane` is a Gaussian centred at 0.45–0.55 of the width (σ 0.2 of the width), shifted toward the rail; `nose` is 1 for the first 25 mm, fading over 60 mm. Round the nosing with r 3–15 mm. `dmax` 1–5 mm for concrete, 10–40 mm for old stone |
| Kick and cart scuffs | under 1 mm deep goes in the normal map. Dents 2–8 mm deep, r 20–60 mm, at 0.1–0.3 m and 0.3–1.0 m, on push-side door and frame corners |
| Forklift strikes | rack uprights bent 3–15 mm over 0.1–0.3 m, mostly below 300 mm. Column-guard and bollard dents r 50–150 mm at 0.1–0.5 m. Wall and kerb corners chipped 20–80 mm at 0–0.5 m. Door tracks bent at 0–0.9 m |
| Roller-shutter dents | r 100–300 mm, 5–30 mm deep, at 0.1–0.6 m and 0.8–1.6 m, crossing slat seams; replaced bottom slats in an odd colour |
| Floor joint arris | spall pockets 10–50 mm wide and 5–20 mm deep along the joint, densest where aisles cross it at 90° |
| Fork gouges | V grooves 2–5 mm wide and 0.3–2 m long, parallel to the aisle, near pick faces |
| Vandalism, the first years of neglect | broken glass and opened panels at 0–3 m |

These are distributed by the same `strike` and `traffic` fields the materials use (see
weather-and-use.md): strikes cluster at pinch points, turns, door jambs and aisle ends.

## Sources

- Morrell et al., NPL Report MAT 76, edge chipping: https://eprintspublications.npl.co.uk/6736/1/MAT76.pdf
- Quinn & Lloyd, edge toughness (NIST): https://www.nist.gov/node/717701
- Quinn & Mohan, edge chips at different force angles (NIST): https://www.nist.gov/node/716156
- Lithic flake anatomy: https://en.wikipedia.org/wiki/Lithic_flake
- IDEA StatiCa, concrete breakout (ACI 318 CCD method): https://www.ideastatica.com/support-center/anchorage
- ASTM C216 chippage limits: https://www.astm.org/c0216-19.html
- PCI, Designer's Notebook DN-29: Weathering: https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf
- Rimkus, concrete spalling: https://rimkus.com/article/all-about-concrete-spalling
- Phase-field corrosion cracking, corner versus delamination: https://arxiv.org/pdf/2306.01903
- USGS, granite corners round first: https://pubs.usgs.gov/of/2004/1007/granite.html
- SafetyStep, stair nosing wear: https://www.slideshare.net/safetystep/understanding-sliponstairs
- Rack damage below 12 in (ProGMA / Damotech): https://og.mhi.org/downloads/industrygroups/progma/casestudies/casestudy-damotech-2.pdf
- Dock door protection: https://www.cisco-eagle.com/blog/2009/11/04/protecting-overhead-dock-doors-from-forklift-impacts
- Floor joints damaged by small hard wheels: https://www.logisticsmatters.co.uk/article/when-floor-joints-go-wrong/
- Door protection plates: https://archtoolbox.com/interior-door-protection
