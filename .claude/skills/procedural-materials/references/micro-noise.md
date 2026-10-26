# Micro detail: non-uniform grain, distributions, patterns by surface

The small scale needs the 80/20 rule as much as the large. Research for review 31: texture
statistics (Portilla–Simoncelli, Gaussian scale mixtures), surface metrology, the DBV concrete
pore classes, corrosion-pit studies, and artist critiques. Numbers marked *(est.)* are estimates
or our own measurements.

## Why even grain reads fake

- **fBm and Perlin noise are stationary Gaussian fields,** fully described by their spectrum.
  Real surface detail is Gaussian noise times a hidden, spatially varying amplitude field:
  where detail is strong, the detail next to it and one scale up is strong too. Real
  histograms have heavy tails.
- **Wear changes the shape of the distribution, not only its contrast.** Worn and honed
  surfaces have flattened peaks (plateaus) with the pits kept: negative skew. A fresh stipple is
  positive-skewed.
- **Measured on the danchi v2 spray-tile height** *(est.)*: 90th/10th percentile of local
  contrast 1.06×, kurtosis 2.4, the same as plain band-limited noise. The same noise times a
  thresholded cluster mask with a 15 % floor measured 4.4× and kurtosis 16.

## Targets *(est.)*

For a micro layer over a surface wider than 0.5 m, measure the local standard deviation of the
grain (high-pass) in a window 4–8× the grain size:

| Measure | Uniform (fails) | Target |
|---|---|---|
| p90 / p10 of local std | about 1.1 | 3–6 |
| Coefficient of variation of local std | under 0.1 | 0.4–0.8 |
| Kurtosis of the grain | about 3 | 5–20 |
| Mean local std, named zone vs another (worn/fresh, top/bottom of a pour lift) | 1× | 2–4× |
| Density of discrete features, zone vs zone | 1× | 3–5×, with a 10–20 % floor |

Fail any micro layer with p90/p10 under 2 or kurtosis under 4.

## Where micro detail clusters (it reads the same causes as the large scale)

- **Bug holes in cast concrete** are more common toward the top of each pour, under leaning
  forms and with oily release agents. Holes under 10 mm are hemispherical; larger ones are
  irregular and show aggregate. DBV pore classes allow 0.3–1.2 % of the area per 0.5 × 0.5 m.
  One wall can span several classes.
- **Washed zones expose aggregate; sheltered zones keep the smooth laitance.** Erosion removes
  paste where water channels.
- **Corrosion pits** cluster on top of a random background. Their depths are lognormal.
- **Wood:** grain relief grows with exposure (earlywood erodes 34–101 µm/yr faster than
  latewood). Sheltered boards stay smooth.
- **Spray-tile paint:** thicker and crisper at bay centres, thinner at edges and overlaps, worn
  and filled with dirt on the windward and lower wall. The common flattened type (押さえ) is
  flat-topped mesas 5–20 mm across with crisp rims and troughs between, not rounded bumps.
  Build its height from thresholded, flattened mesas plus a small rounded noise. Dirt and
  occlusion go in the troughs, and chalk and polish on the plateaus, so streaks read stronger on
  rough texture.
- **Photographs** (review 31): bug holes on a board-formed wall were about 10× denser in the top
  30–40 cm of each pour than lower down, and denser in the upper half of each board band.
  Patches of holes sat next to nearly bare areas, with sizes of 2–20 mm, mostly small. Aim
  for a spread of 5–10× between areas. Soffits are evenly greyer, since no rain cleans them.
- **Polish and dirt fill:** where hands, feet or water wear a surface, the micro relief flattens
  and the pits fill with dirt.

## Distributions for discrete features

- **Poisson (independent random):** only for the background floor.
- **Clustered (Thomas or Matérn):** natural and wear features. Offspring land around sparse
  parents, at a cluster radius of 3–10× the feature size. Use Thomas (Gaussian spread) for pits,
  bug holes, lichen, rust and moss; use Matérn (uniform in a disc) for spatter and dirt specks.
- **Blue noise or a jittered grid:** manufactured features that repel each other, such as
  rivets, one spray pass or spangle grains. In Copernicus, a hex grid with jitter about 0.2.
- **Sizes: a power law or a lognormal, never uniform.**
  - **Exposed aggregate:** N(>d) ∝ d^-1.5, from the Fuller grading curve, truncated at
    0.5–20 mm.
  - **Pits:** lognormal, σ_ln 0.5–0.8.
  - **Bug holes:** 1–15 mm.
- **Couple size with density:** large features only inside the clusters; the background holds
  small ones.

## Patterns by surface

W = Worley or cell noise, SC = `shapescatter` stamps, PS = `phasornoise`.

| Surface | Basis | Real scale | Orientation | Clusters where |
|---|---|---|---|---|
| Cast concrete pores, bug holes | SC hemispherical pits, Thomas, lognormal sizes | 1–15 mm; 0.3–1.2 % of the area | none | top 0.3–0.6 m of each lift, under leaning forms, near form joints |
| Form ties, cold joints | `tilepattern` grid; one horizontal band per lift | ties 25–35 mm on a 0.6–0.9 m grid; lifts 0.3–1.5 m | joints horizontal, slightly wavy | joints darker, with bug holes and sand streaks just above |
| Honeycombing | W cells exposing aggregate, rare | 50–300 mm patches | none | form-joint leaks, the base of lifts |
| Laitance, exposed aggregate | aggregate SC (power-law sizes) revealed by a wear mask | 2–20 mm | none | washed zones and edges |
| Spray tile, textured paint | SC droplet blobs, near blue noise, two size modes; clamp the peaks where head-cut or worn | 1–6 mm blobs | none | see above |
| Orange peel on paint | band-limited fBm at low amplitude | waves 0.6–10 mm and 0.1–0.6 mm | none | stronger near edges and overspray |
| Render, plaster | PS saw profile along a curved direction field; crazing as W borders | strokes 0.1–0.4 m; crazing cells 10–70 mm | arcs | crazing only in damp or sunny zones |
| Brick, mortar | per-brick micro character from the brick id; gritty W mortar | sand 0.5–2 mm | bed joints horizontal | mortar eroded near the base and under copings; soot in upper bands |
| Painted steel | orange peel plus brush PS; chips as SC with an edge-biased density, power-law sizes | chips 1–20 mm | brush strokes along the member | rust area from 0.05 % to about 40 % across ISO 4628 grades; at edges, welds and water traps |
| Rust blooms | W dist1 blobs with domain warp; layered scale as stacked thresholds | blooms 2–40 mm; flakes 5–50 mm | a slight downward run | Thomas clusters at chips and the lowest edges |
| Galvanised steel | W cells (spangle), near regular; white rust as Matérn blotches | spangle 1–20 mm | none | white rust only where stacked or wet |
| Brushed aluminium | PS or strongly stretched noise, plus sparse long scratches | lines 10–100 µm | one direction | scratches cluster in handling zones |
| Asphalt | aggregate SC, N(>d) ∝ d^-1.5; ravelling as holes where binder is lost | stones 2–20 mm | none | ravelling and polish in wheel paths |
| Asphalt cracks | alligator: W borders 0.1–0.3 m; block: W 0.3–3 m; longitudinal: warped lines | — | transverse across the lane | alligator only in wheel paths; block everywhere |
| Glass | dust as low-amplitude fBm; water spots as SC rings (`sdfshape` annulus), lognormal | spots 0.5–5 mm | drip trails vertical | near the bottom of the frame and run-off paths; the middle stays clean |
| Wood | stretched fBm grain; checks as sparse long, thin W borders along the grain | rings 2–10 mm; checks 50–300 mm | along the grain | relief and grey on exposed flat faces |
| Dirt, soot | multifractal (cascade) masks; streaks by `streakblur` of the micro layer | specks 0.2–3 mm, Matérn | down | pores and occlusion first, then plateaus |
| Moss, algae | W or fBm fronts along a damp gradient; Thomas colonies | colonies 5–100 mm | front horizontal | damp ledges, the base, run-off lines |
| Lichen | SC discs with a brighter rim; sizes from age | grows 0.02–2 mm a year | none | exposed stone, colonies merging |
| Cracks | shrinkage: nested W with T-junctions; re-entrant: 30–60° off the bisector from opening corners; settlement: diagonal, stepped through brick joints | crazing 10–70 mm; shrinkage 0.3–1 m | by cause | openings, corners, long walls |

- **Cracks need T-junctions.** A newer crack ends on an older one at about 90°, while a single
  Voronoi border gives 120° Y-junctions. Stack 2–3 Worley sizes, each finer layer gated inside
  the coarser cells.

## Copernicus recipes

The node and input names come from `copernicus.md` and the SideFX docs. Parm tokens marked †
were not read in Houdini, and `phasornoise` output was not tested.

1. **Amplitude envelope.** `env` = `remap`(cause × cluster × meso → 0.15–1). Square it with
   `blend` multiply for a heavy tail. Then grain × env, added to the height. Check p90/p10.
2. **Change the character, not only the contrast.**
   - Fresh: crisp stipple. Worn: the same with `clamp` max at about the 60th percentile
     (plateaus), plus `worleynoise` dist1 pores filled with dirt. `blend` by the wear mask.
   - `fractalnoise` takes per-pixel `roughness` and `octaves` inputs: use fewer octaves where
     polished or filled, and more roughness where weathered.
   - It has no per-pixel element size, so blend two sizes by mask instead.
3. **Clustered features with `shapescatter`.** Its inputs include `density`, `scale`,
   `jitter`, `angle`, `direction`, `stretch`, `color` and `alpha`.
   - Set `stampsx`/`stampsy` to about the feature spacing (64 across 2.4 m is 37 mm).
   - **density** = cause (for example a top-of-lift `ramp` band) × a cluster proxy, plus a 0.1
     floor. Make the proxy from `worleynoise` dist1 at the cluster scale, then `remap`
     threshold, then `blur`.
   - **scale** = white `fractalnoise` through a `remap` ramp shaped like a truncated power
     law, times the cluster mask, so the large features sit in the clusters.
   - For blue noise, set `gridtype` hex with `jitter` about 0.2.
4. **Direction with `phasornoise`.** Its per-pixel inputs are `direction`, `scale` and `bias`;
   the wave type (sine, rectangle, saw) is a parm.
   - **Brushed aluminium:** a constant direction, small size, saw.
   - **Trowel arcs:** the direction from `slopedir` of a large smooth noise.
   - **Formwork grain:** horizontal saw.
5. **Cracks.** `worleynoise` `border` → `remap` threshold → `distort` by fine noise → × cause.
   Repeat at 0.4× the size, gated inside the coarse cells by `feather`, for T-junctions.

## Checking non-uniformity

- **Local variance map.** hp = x − `blur`(x, about 3× the grain size). Then
  locvar = `blur`(hp², 4–8× the grain) − `blur`(hp)².
- **Zone ratio.** A `statistics` COP with an `active` mask gives the zone's average. Compare
  inside and outside the wear mask: locvar should differ 4–16× (2–4× in std).
- **Percentiles.** Use a `histogram` COP, or read the written PNG in Python.

## Sources

- Portilla & Simoncelli, parametric texture model: https://www.cns.nyu.edu/~eero/ABSTRACTS/portilla99-abstract.html
- Wainwright & Simoncelli, scale mixtures of Gaussians: https://www.cns.nyu.edu/~eero/ABSTRACTS/wainwright99b-abstract.html
- Lagae et al., survey of procedural noise functions: https://diglib.eg.org/handle/10.2312/CGF.v29i8pp2579-2600
- Tricard et al., procedural phasor noise: https://history.siggraph.org/?p=100118
- Heidelberg Materials, DBV exposed-concrete classes (porosity P1–P4): https://www.heidelbergmaterials.de/sites/default/files/assets/document/2f/26/sichtbeton_klassen_u_anf_bro_4s_2017_web.pdf
- Bug holes, causes and location: https://precast.org/blog/causes-fixes-scc-bug-holes/
- Spatial distribution of corrosion pits (Aalto): https://aaltodoc.aalto.fi/items/bf8c7c43-ed4c-42e5-af78-ecc097216d2e
- Wood erosion rates (USDA): https://wfs.swst.org/index.php/wfs/article/view/1252
- FHWA LTPP distress identification manual: https://www.fhwa.dot.gov/publications/research/infrastructure/pavements/ltpp/13092/001.cfm
- Hierarchical crack patterns and T-junctions: https://arxiv.org/pdf/2501.07882
- spatstat, Thomas and Matérn cluster processes: https://www.rdocumentation.org/packages/spatstat/versions/1.63-3/topics/rThomas
- SideFX, Fractal Noise, Shape Scatter and Phasor Noise COPs: https://www.sidefx.com/docs/houdini/nodes/cop/fractalnoise.html · https://www.sidefx.com/docs/houdini/nodes/cop/shapescatter.html · https://www.sidefx.com/docs/houdini/nodes/cop/phasornoise.html
- Joshua Lynch, material creation for games: https://80.lv/articles/material-creation-for-games
- Kikusui, spray-tile technical data: https://www.kikusui-chem.co.jp/products/catalog/cat_45_k3.pdf
