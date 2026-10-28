# Micro noise: non-stationary detail, distributions, per-surface patterns (research r4)

[S] = sourced (numbered, list at end). [I] = inference or my own measurement. This adds to
`realism.md` (which covers macro/meso clustering) and covers the small scale only.

## 0. Diagnosis: the micro layer is stationary

I measured the high-pass band (grain only) of the danchi spray-tile height (`14_texture_maps`,
top left), looking at local standard deviation in an 8 px window [I]:

| Signal | CV of local std | p90/p10 local std | Kurtosis |
|---|---|---|---|
| danchi spray-tile height map | 0.02 | 1.06 | 2.4 |
| danchi close-up render (coping band) | 0.17 | 1.29 | 3.5 |
| synthetic stationary band noise | 0.04 | 1.09 | 3.0 |
| same × lognormal envelope, σ = 0.5 / 1.0 | 0.33 / 0.70 | 2.3 / 5.4 | 5 / 20 |
| same × thresholded cluster mask, 15 % floor | 0.73 | 4.4 | 16 |

The map is plain Gaussian noise: one contrast everywhere, no tails. Scripts:
`research-r4/scripts/locvar.py`, `measure.py <img> x0 y0 x1 y1`.

## 1. Why uniform micro noise reads fake

- **fBm/Perlin is a Gaussian, stationary field, fully described by its power spectrum**
  [S1, S3]. A spectrum match alone cannot give realism [I].
- **Real textures carry more than a spectrum.** Portilla–Simoncelli model texture from
  coefficient pairs "at adjacent spatial locations, orientations, and scales" [S5]. Above
  all they use correlated *magnitudes*: where detail is strong, the detail nearby and one
  scale up is strong too [S6]. Real marginals "have extended heavy tails" [S7]. The Gaussian
  scale mixture model is Gaussian noise × a hidden positive multiplier [S7]. **That
  multiplier is the micro amplitude driven by the meso/macro state.**
- **Multiplicative cascades** (Musgrave multifractals) give roughness that "varies with
  location"; additive fBm cannot [S8].
- **Wear changes the distribution's shape.** Worn and honed surfaces are negatively skewed
  (Rsk < 0): truncated peaks form plateaus and the valleys survive. Rku ≈ 3 is Gaussian
  [S9]. A fresh stipple is positive-skewed, a worn one is plateaus with pits [I].
- **Weathering is a spatially varying degree.** Appearance manifolds drive synthesis from a
  degree map [S11]. Context-aware textures tie rust, cracking and mould to geometry [S12].
  Stationary synthesis fails on such exemplars [S10].

## 2. 80/20 at small scale: how real micro detail clusters

The causes are physical, so the micro layer must read the same cause masks as the meso layer:

- **Bug holes:** "more prevalent towards the top of concrete placement" [S13, S14]; more
  under leaning forms [S15] and with oily release agent [S14]. Holes under 10 mm are
  hemispherical; larger ones are irregular and expose aggregate [S13].
- **Zone contrast:** DBV porosity classes per 500 × 500 mm, pores 2–15 mm: P1 1.2 %,
  P2 0.9 %, P3 0.6 %, P4 0.3 % area [S16], which ACI 347.3R adopts [S17]. Its sampling can
  put one wall in any category [S18], so density varies a lot within a wall.
- **Steel pits:** clusters "superimposed on a randomly distributed background" [S19], i.e.
  80/20 with a floor; pit depths are lognormal [S20].
- **Wood:** earlywood erodes faster than latewood (34–101 µm/yr), most in the first
  7 years [S21]. Grain relief grows with exposure; sheltered boards stay smooth [I].
- **Concrete:** erosion removes paste unevenly where water channels [S22]. Washed zones
  expose aggregate; sheltered zones keep laitance [I].
- **Artists:** "a unified noisiness across the edges" reads flat; too much detail "can
  become noisy and distracting" (Josh Lynch) [S23]. Polycount's tell: "nearly every edge
  has the same amount of wear" [S24].

**Targets [I]** (section 0 and DBV ratios): micro-band local-std **p90/p10 3–6** in a
4–8× grain window (stationary ≈ 1.1); CV 0.4–0.8; kurtosis 5–20. Between named zones
(fresh/worn, top/bottom of lift) mean local std differs **2–4×** and discrete-feature
density 3–5×, with a 10–20 % floor.

## 3. Distributions for discrete features

- **Poisson (uniform random):** only as the background floor.
- **Clustered (Neyman–Scott):** for natural and wear features. Thomas: offspring
  Gaussian-displaced from Poisson parents; Matérn: uniform in a disc [S25]. Use Thomas for
  pits, bug holes, lichen, rust and moss, Matérn for spatter and dirt specks, with a
  cluster radius 3–10× the feature size [I].
- **Blue noise / jittered grid:** for manufactured, mutually repelling features: rivets,
  one spray pass, spangle grains [I]. Pair-correlation synthesis spans clustered to blue
  [S26]; in Copernicus, a hex grid with small jitter.
- **Sizes: power law or lognormal, never uniform.** Fuller grading P = (d/D)^n,
  n ≈ 0.45–0.5 [S27], implies on a cut or worn plane **N(>d) ∝ d^-1.5** [I, derived]. Pits
  are lognormal (σ_ln about 0.5–0.8 [I]) [S20]. Truncate: aggregate 0.5–20 mm, bug holes
  1–15 mm [S16].
- **Couple size and density:** large features only inside clusters; the background holds
  small ones [I].

## 4. Per-surface catalogue

Scales are real-world sizes. Basis abbreviations: W = Worley/cells, PS = phasornoise,
SC = shapescatter.

| Surface | Basis | Scale | Orientation | Clusters where |
|---|---|---|---|---|
| Cast concrete: pores, bug holes | SC of hemispherical pits, Thomas, lognormal sizes | 1–15 mm; 0.3–1.2 % area [S16] | none | top 0.3–0.6 m of each lift, under leaning forms, near form joints [S13–15] |
| Form-tie holes, cold joints | `tilepattern` grid; a horizontal band per lift | ties 25–35 mm on a 0.6–0.9 m grid [I]; lift 0.3–1.5 m [I] | joints horizontal and slightly wavy | joints darker, with bug holes and sand streaks just above |
| Honeycombing | W cells exposing aggregate, rare | 50–300 mm patches [I] | none | at form-joint leaks, the base of lifts, congested rebar [S28] |
| Laitance / exposed aggregate | aggregate SC with power-law sizes, revealed by a wear mask | 2–20 mm | none | washed zones and edges; laitance stays where sheltered [S22] |
| Spray-tile, textured paint | SC of droplet blobs, blue-ish, two size modes; head-cut gives plateaus | 1–6 mm blobs [I] | none | thicker and crisper at bay centres; thinner at edges and overlaps; worn and dirt-filled on the windward and lower wall |
| Orange peel on paint | band-limited fBm, low amplitude | long wave 0.6–10 mm, short 0.1–0.6 mm [S29] | none | stronger near overspray and edges [I] |
| Render, plaster | PS (saw profile) along a curved direction field; crazing as W borders | trowel strokes 0.1–0.4 m; crazing cells 10–70 mm [S13] | arcs | crazing only in damp/sun zones, shows most after wetting [S13] |
| Brick, mortar | per-brick micro character set by id; mortar W grit | sand grain 0.5–2 mm | bed joints horizontal | eroded mortar near the base and under copings; soot in the upper bands |
| Painted steel | orange peel + brush PS; chips as SC with an edge-biased density | chips 1–20 mm, power law | brush strokes along the member | ISO 4628 rust grades Ri1 0.05 % to Ri5 about 40 % area [S30]; at edges, welds, water traps |
| Rust blooms | W dist1 blobs + domain warp; layered scale as stacked thresholds | 2–40 mm blooms; scale flakes 5–50 mm | slight downward run | Thomas clusters at chips, scribes and the lowest edges; pits lognormal [S19, S20] |
| Galvanised steel | W cells (spangle), blue/regular; white rust as Matérn blotches | spangle 1–20 mm [I] | none | white rust where stacked or wet [S31] |
| Brushed aluminium | PS / strongly stretched noise, plus sparse longer scratches | 10–100 µm lines [I] | single direction [S32] | scratches cluster in handling zones |
| Asphalt | aggregate SC with N(>d) ∝ d^-1.5; ravelling = holes where binder is lost | 2–20 mm stones | none | ravelling and polish in wheel paths [S33] |
| Asphalt cracks | alligator: W borders 0.1–0.3 m; block: W 0.3–3 m; longitudinal: warped lines | [S33] | alligator along wheel paths; transverse across the lane | alligator only in wheel paths; block everywhere [S33] |
| Glass | dust = low-amp fBm; water spots = SC rings (`sdfshape` annulus), lognormal | spots 0.5–5 mm [I] | drip trails vertical | near the frame bottom and run-off paths; clean in the middle |
| Wood | stretched fBm grain; checks = sparse long thin W borders along grain | ring spacing 2–10 mm; checks 50–300 mm long [I] | along the grain | relief and grey on exposed and flat faces [S21] |
| Dirt, soot | multifractal (cascade) masks; streaks = `streakblur` of the micro | specks 0.2–3 mm, Matérn | down | fills pores and AO first, then plateaus [I] |
| Moss, algae | W/fBm fronts along a damp gradient; Thomas colonies | colonies 5–100 mm | front horizontal | damp ledges, the base, run-off lines (realism.md) |
| Lichen | growth (DLA) or SC discs with ring rims; sizes from age | radial growth about 0.02–2 mm/yr [S34] | none | exposed stone; colonies merge [S35] |
| Cracks by cause | shrinkage: hierarchical W with T-junctions; re-entrant corners: 45° from openings; settlement: diagonal, stepped through brick joints | crazing 10–70 mm; shrinkage ~0.3–1 m [S36] | by cause [S37] | at openings, corners, long walls |

- **Cracks:** newer cracks end on older ones at about 90° (T-junctions) [S38]; one Voronoi
  border gives only 120° Y-junctions. Stack 2–3 Worley sizes, each finer one gated inside
  the coarser cells [I].
- **Spray-tile:** a base coat plus a pattern coat, optionally head-cut (凸部処理) [S39]:
  droplet stamps, then `clamp` the peaks where head-cut or worn [I].

## 5. Copernicus recipes

Node names are from `copernicus.md` and the SideFX docs. Input names were checked on the
SideFX doc pages; internal parm tokens marked † were not read in Houdini.

1. **Amplitude envelope (Gaussian scale mixture).** `env` = `remap`(cause × cluster ×
   meso → 0.15–1), squared with `blend` multiply for a heavy tail; micro × env, then add to
   height. Target p90/p10 3–6.
2. **Change the character, not only the contrast.**
   - Fresh: crisp stipple, positive skew. Worn: the same with `clamp` max at about the
     60th percentile (plateaus), plus `worleynoise` dist1 pores filled with dirt. Combine
     with `blend` (mask = wear).
   - **`fractalnoise` takes per-pixel `roughness` and `octaves` inputs** [S40]: fewer
     octaves where polished or filled, more roughness where weathered.
   - There is no per-pixel element size [S40]: blend two sizes by mask rather than warping
     `pos` [I].
3. **Clustered features with `shapescatter`.**
   - Inputs `density`, `scale`, `jitter`, `angle`, `direction`, `stretch`, `color`,
     `alpha`; density drives rejection sampling via Density Layer Mask† [S41].
   - `stampsx`/`stampsy` set the cell to about the feature spacing (64 on 2.4 m = 37 mm).
   - **density** = cause (top-of-lift `ramp` band) × Thomas proxy (`worleynoise` dist1 at
     the cluster scale → `remap` threshold → `blur`) + 0.1 floor.
   - **scale** = white `fractalnoise` → `remap` with a `ramp` approximating a truncated
     Pareto, s = s_min·(1 − u(1 − (s_min/s_max)^b))^(−1/b), b ≈ 1.5; Scale Mode† Min/Max.
     Multiply by the cluster mask so the large features sit in the clusters.
   - Blue noise: `gridtype` hex, `jitter` about 0.2.
4. **Anisotropy with `phasornoise`.** Per-pixel inputs `direction`, `scale`, `bias`; parms
   Element Size, Kernels, Type Phasor Wave (Sine, Rectangle, Saw), Rotate Pattern [S42, S4].
   - Brushed aluminium: constant direction, small size, Saw.
   - Trowel arcs: `direction` from `slopedir` of a large smooth noise.
   - Formwork grain: horizontal Saw.
   - Untested: check its output range with `statistics`.
5. **Cracks.** `worleynoise` `border` (exact SDF) → `remap` threshold → `distort` by fine
   noise → × cause. Repeat at 0.4× size, gated by `feather` inside the coarse cells, for
   T-junctions [I].
6. **Lichen/moss.** `shapescatter` of `sdfshape` discs with a brighter rim (`sdftomono` +
   ramp) over Thomas density × damp. No DLA COP [S35]; warp the discs with `distort` [I].

## 6. Checks for non-uniformity

- **Local variance:** hp = x − `blur`(x, ~3× grain); locvar = `blur`(hp², 4–8× grain) −
  `blur`(hp)², with `blur` `units` pixels and `blend` multiply/subtract [S43].
- **Zone ratio:** `statistics` with an `active` mask (> 0.5) outputs average, minimum,
  maximum [S44]. Average locvar inside the wear mask over outside: 4–16× (2–4× in std).
- **Percentiles:** use the `histogram` COP [S44] or `measure.py` on the PNG.
- **Fail** if p90/p10 < 2 or kurtosis < 4 on any micro layer over 0.5 m of real size.

## 7. Failure modes

| Failure | Fix |
|---|---|
| Sandpaper stipple everywhere (danchi) | envelope (5.1) + character switch (5.2) |
| Uniform pit density (`worleynoise` pits) | `shapescatter`, Thomas density, Pareto sizes |
| Same wear on every edge [S24] | cause × cluster, then threshold |
| Voronoi-looking cracks | hierarchy with T-junctions [S38] |
| Tiling grain | hex-tile; low micro contrast in floor zones |
| Contrast-only variation, even sizes | skew change, octave input, power-law sizes |

## Sources

1. Lagae et al., A Survey of Procedural Noise Functions (CGF 2010): https://diglib.eg.org/handle/10.2312/CGF.v29i8pp2579-2600
2. Lagae et al., Procedural noise using sparse Gabor convolution: https://www.academia.edu/2854650/Procedural_noise_using_sparse_Gabor_convolution
3. Galerne et al., Gabor noise by example: https://hal-univ-tlse3.archives-ouvertes.fr/INRIA/hal-00695670
4. Tricard et al., Procedural phasor noise (SIGGRAPH 2019): https://history.siggraph.org/?p=100118
5. Portilla & Simoncelli, parametric texture model: https://www.cns.nyu.edu/~eero/ABSTRACTS/portilla99-abstract.html
6. Simoncelli, joint statistics of wavelet magnitudes: https://www.cns.nyu.edu/~eero/ABSTRACTS/simoncelli98b-abstract.html
7. Wainwright & Simoncelli, scale mixtures of Gaussians: https://www.cns.nyu.edu/~eero/ABSTRACTS/wainwright99b-abstract.html
8. Blender manual, Musgrave texture (multifractal types): https://docs.blender.org/manual/en/3.2/modeling/geometry_nodes/texture/musgrave.html
9. Rsk/Rku of honed surfaces: https://real.mtak.hu/193052/1/2538_publish.pdf ; https://ocw.snu.ac.kr/sites/default/files/NOTE/Precision%20Metrology%20Week14%20-%20Surface%20Engineering%20and%20Surface%20Roughness.pdf
10. Zhou et al., Non-stationary texture synthesis by adversarial expansion: https://arxiv.org/abs/1805.04487
11. Wang et al., Appearance manifolds (SIGGRAPH 2006): https://www.microsoft.com/en-us/research/?p=152023
12. Lu et al., Context-aware textures (TOG 2007): https://graphics.cs.yale.edu/publications/context-aware-textures
13. KTU, distribution analysis of concrete surface air pores: https://sace.ktu.lt/index.php/DAS/article/view/2789/2570
14. Bug holes, causes and location: https://precast.org/blog/causes-fixes-scc-bug-holes/ ; https://gcpat.com/en/about/news/blog/how-reduce-bug-holes-concrete
15. Yoshitake et al., bugholes on tunnel lining (form angle): https://doaj.org/article/04743696d2164394adf7b20b216d180c
16. Heidelberg Materials, Sichtbetonklassen (DBV porosity P1–P4): https://www.heidelbergmaterials.de/sites/default/files/assets/document/2f/26/sichtbeton_klassen_u_anf_bro_4s_2017_web.pdf
17. ACI 347.3R-13 preview: https://www.concrete.org/Portals/0/Files/PDF/Previews/347.3R-13_PREVIEW.pdf
18. ASCC/CIM evaluation of ACI 347.3R: https://concreteproducts.com/index.php/2017/07/26/contractors-cim-formed-surface-research-mockups-best-aci-347-criteria/
19. Abass et al., spatial distribution of corrosion pits: https://aaltodoc.aalto.fi/items/bf8c7c43-ed4c-42e5-af78-ecc097216d2e
20. Lognormal pit depth, prestressing strands: https://air.unipr.it/handle/11381/2932651
21. Williams et al., erosion rates of wood (USDA): https://wfs.swst.org/index.php/wfs/article/view/1252 ; https://wfs.swst.org/index.php/wfs/article/view/769
22. NPS Preservation Brief 15, concrete: https://scvhistory.com/scvhistory/files/doi_preservationbrief15/files/basic-html/page6.html
23. Joshua Lynch, material creation for games: https://80.lv/articles/material-creation-for-games
24. Polycount critiques: https://polycount.com/discussion/comment/2716897/ ; https://polycount.com/discussion/211893/m16a4
25. spatstat rThomas / rMatClust: https://www.rdocumentation.org/packages/spatstat/versions/1.63-3/topics/rThomas
26. Öztireli & Gross, point distributions by pair correlation: https://history.siggraph.org/?p=207998
27. Pavement Interactive, gradation (Fuller 0.45/0.5): https://pavementinteractive.org/reference-desk/testing/aggregate-tests/gradation-test/
28. ACI 309.2R-15 preview (honeycomb, voids): https://www.concrete.org/Portals/0/Files/PDF/Previews/309_2R_15_preview.pdf
29. Orange peel wave bands: https://www.worldoftest.com/orange-peel-meter-wave-scan/ ; https://pcimag.com/articles/82800-measure-orange-peel-and-doi
30. ISO 4628-3 (degree of rusting): https://www.iso.org/standard/83324.html
31. AGA, wet storage stain: https://galvanizeit.org/uploads/publications/Wet_Storage_Stain_On_Galvanized_Steel.pdf
32. Anisotropy needs aligned scratches: https://forum.maxwellrender.com/viewtopic.php?p=156274
33. FHWA LTPP distress identification manual: https://www.fhwa.dot.gov/publications/research/infrastructure/pavements/ltpp/13092/001.cfm
34. Lichen growth rates (Armstrong): https://publications.aston.ac.uk/id/eprint/26531/1/Growth_rates_and_implications_for_lichenometry.pdf
35. Desbenoit et al., simulating lichen growth (open DLA): https://perso.liris.cnrs.fr/egalin/Articles/2004-lichen.pdf
36. Plastic shrinkage cracks: https://www.forconstructionpros.com/11487540
37. FEMA, crack patterns at re-entrant corners: https://www.fema.gov/pdf/emergency/usr/module1c.pdf ; https://www.isurv.com/directory_record/2788/cracking
38. Hierarchical crack patterns, T-junctions: https://arxiv.org/pdf/2501.07882 ; https://www.phys.ens.fr/~foldingslidingstretchinglab/papers/A22_PhysRevE_71_046215.pdf
39. Kikusui, spray-tile technical data: https://www.kikusui-chem.co.jp/products/catalog/cat_45_k3.pdf
40. SideFX, Fractal Noise COP: https://www.sidefx.com/docs/houdini/nodes/cop/fractalnoise.html
41. SideFX, Shape Scatter COP: https://www.sidefx.com/docs/houdini/nodes/cop/shapescatter.html
42. SideFX, Phasor Noise COP: https://www.sidefx.com/docs/houdini/nodes/cop/phasornoise.html
43. SideFX, Blur COP: https://www.sidefx.com/docs/houdini/nodes/cop/blur.html
44. SideFX, Statistics COP: https://www.sidefx.com/docs/houdini/nodes/cop/statistics.html
