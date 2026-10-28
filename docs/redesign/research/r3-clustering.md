# Clustered, caused wear: how artists distribute damage, dirt and detail

Research for the HocusPocus skills `procedural-mesh-damage`, `procedural-materials` and
`procedural-assets`. Tags: **[S]** sourced (numbered sources at the end), **[I]** my inference
or common practice that I could not tie to a primary source.

## What the danchi-v2 evidence shows (02, 03, 05, 12)

- **Chips.** The end-wall corner in image 12 has 3–5 cm notches at nearly even spacing up the
  arris. There is no dominant break, no dense run and no clean run, and no stain or exposed
  aggregate beside any chip. **[I]**
- **Chamfer.** The 2 cm chamfer is identical on every coping, slab band and corner (02, 03),
  so every edge catches the same highlight. **[I]**
- **Streaks.** They are patchy within a bay (an improvement), but at 45 m (05) every floor and
  bay carries about the same streak density. The clustering stops at bay scale and does not
  reach facade scale. **[I]**
- **Layers.** Chips, streaks and dirt are placed independently, so none of them shows a shared
  cause. **[I]**

## 1. Principles as artists state them

- **Composition before scatter.** Lyubov Vasileva writes "Chaotic scattering without
  composition will not look very attractive", and "dust should not be evenly distributed
  over the surface". [1] **[S]**
- **Erase most of the generated wear.** A Polycount texturing thread advises starting from a
  convexity mask, then "roughly erase 75% of it". The same thread lists "small scale and large
  scale wear and their balance" as a distinct quality. [2] **[S]**
- **Exposure, not all curvature.** Simon Mercuzot subtracts AO from curvature: "the edges
  that are the most exposed" are not the inaccessible ones. Two scratches from the same cause
  "doesn't mean they'll be identical in depth". He also says "A difference in opacity… even in
  a single layer… is very important". [3] **[S]**
- **Critics name uniformity directly.** Polycount reviewers wrote that wear is "applied
  uniformly across pretty much every edge", and asked for "way more variance in intensity". A
  hand-drill critique said its wear "seem[s] very procedural, not relative to function". Other
  critiques flag grunge spread over the whole model and dirt of "uniform size and placement".
  [2][4] **[S]**
- **Focus detail; don't just reduce it.** Josh Rife (LawBreakers) keeps detail to "prominent
  player pathing or near objectives". He says "we don't reduce detail so much as focus it".
  [5] **[S]**
- **Variation lives in the transitions.** Augustas Krivelis (The Yard) puts the detail "not in
  the textures themselves, but rather in the transitions between them". [6] **[S]**
- **Rest areas.** In painting, resting space is "simpler, quieter, and less detailed than your
  focal area". This is the general-art root of the user's 80/20 rule; the 70/30 rule is its
  softer form. [7] **[S, general art]**
- **Cause first.** Harvey Smith and Matthias Worch's GDC talk "What Happened Here?" treats
  every mark as evidence that the player interprets. [8] Mercuzot: "understanding why these
  things happen" makes wear reproducible. [3] **[S]**
- **Pick a subset.** Antoine Déjean chooses which tiles get edge wear with Flood Fill to
  Random Grayscale and a Histogram Scan: "I can increase or decrease the number of tiles with
  the effect". [9] **[S]** That is the 80/20 idea applied per element.

## 2. Numbers and rules

None of these numbers is published as a standard. They follow the sourced principles above
and the existing skill's 1–3 / 5–15 hierarchy. **[I]**

| Scale | Notable clusters | Notes |
|---|---|---|
| Piece (1–3 m) | 0–2 | About 30–50 % of instances get none; a seeded per-piece choice ([9]'s approach) |
| Bay / panel (3–6 m) | 1–3 | One dominant cluster; the rest small |
| Facade (30–60 m) | 3–7 big "stories" | Ground floor, the corners, below 1–2 failed gutters or downpipes, one or two neglected flats |
| Building | Biased by orientation | Weather side and base dirtier; sheltered side cleaner |

**Within a cluster.** One primary mark (the largest chip or spall, or a rust bloom) carries
about half the cluster's visual weight. Add 3–8 secondary marks of 0.3–0.5× its size, then a
tertiary sprinkle. Draw sizes from a power law: `r = rmin·(rmax/rmin)^(u^k)` with k = 2–4.

**Coverage.** Clusters cover about 15–25 % of the area or edge length and hold about 70–85 %
of the notable damage.

**Background.** Fine wear everywhere at 10–30 % of peak intensity, carried only by fine-scale
breakup (roughness and value jitter, micro nicks, a light dirt film). It has no notable
chips. This matches the user's "not pristine swathes".

**Falloff.**
- Smooth, Gaussian-like or `(1−smoothstep(0,r,d))²`, never a hard disc.
- Warp the distance with noise at about r/2 so each cluster has lobes.
- Bias falloff by cause: a streak is anisotropic, long downward (3–10× r) and narrow; dirt
  spreads wider and softer (about 1.5× r) than chips.

**Layer correlation: one cause, several effects.** Each hotspot is a cause, and every layer
reads it with its own radius and offset.
- **Impact corner:** chip, exposed substrate, grime in the chip, lighter polish around it.
- **Leak point:** rust or efflorescence at the source, a streak below, algae where it stays
  wet, a clean wash band beside it. [10][11] **[S mechanism, I recipe]**
- **Painted steel:** rust starts at the chip or edge and creeps under the paint as a blister
  halo, then streaks down. [12] **[S]**

## 3. Edge wear specifics

**Why uniform edge wear reads as CG.**
- Curvature is the same along a straight arris, so a curvature mask gives a constant band.
- Constant chip spacing or a constant bevel adds a repeating highlight.
- Shader-only wear fails in silhouette: "a shaded fake reads as a perfectly sharp edge". [13]
  **[S]**

**How tools and artists vary it along an edge.**
- WearForge documents "The width varies along each edge, with some sections left crisp" and
  "Damage clusters in patches", with handling favouring "edges facing up or outward". [14]
  **[S]**
- Painter's Metal Edge Wear and Designer's Edge Damages take curvature × grunge × AO. They
  expose Wear Level, Wear Contrast, Grunge Amount/Scale, Curvature Weight and AO masking. [15]
  **[S]**
- Painter's Mask Editor adds Position Gradient and World Space Normal layers. Its Global
  Balance and Contrast work after all layers combine. [16] **[S]**
- The cluster structure itself comes from hand-painting over these masks, as in [1], [2] and
  [3]. **[S]**
- **Rule to adopt [I]:**
  `edge_wear = convexity × exposure(AO, up/out facing) × cause(height band, corner proximity,
  hotspots) × run(u)`.
  `run(u)` is a 1D noise along the edge's arclength with a 1–4 m wavelength, thresholded so
  that about half to two thirds of each edge length is clean, with dense runs between.

**How real edges wear.**
- **Painted steel.** Surface tension pulls paint back from sharp edges during cure, so film is
  thinner and edges, welds and cut-outs corrode first. One military spec only requires an
  average of 70 % edge retention. [12] **[S]**
- **Concrete.**
  - Corner spalls come from stress concentration and impact. [17] **[S]**
  - Rebar corrosion products occupy 3–6× the steel's volume and pop the cover. Visible spalls
    understate the spread of corrosion. [18] **[S]**
  - Low cover and carbonation make spalls follow bar lines; corner bars are covered from two
    faces, so arrises spall first. **[I]**
  - Freeze–thaw works where water sits: tops of copings, sills and parapets, and joints. [17]
    **[S]**
  - Formwork stripping leaves occasional early arris chips at random, low density. **[I]**
- **Plaster and drywall.** External corners take impacts from wheeled equipment. Commercial
  corner guards are rated for 0–1000 mm impact height, often in corridors. [19] **[S]** That
  supports the skill's 0.3–1.2 m contact band.

**Bevel width in mid-poly pipelines.**
- Practitioners size the bevel to the intended highlight. Too thin shimmers; too wide reads
  as rounded. [20] **[S]**
- Kits usually keep one or two bevel widths per material class for consistent highlights and
  weighted normals. The variation goes into chips, edge decals or strips and roughness.
  Krivelis uses "floating geometry strips with a separate material ID" for damaged edges. [6]
  **[S strips, I convention]**
- Per-edge widths exist: Blender's Bevel takes width from an attribute. [21] **[S]** Use them
  for hero or unique pieces, at 2–3 width classes chosen by cause, not randomly. **[I]**
- **Recommendation for danchi.** Keep the 2 cm chamfer. Add width-varying edge erosion or
  chips only inside hotspot runs, and vary the edge highlight in roughness. **[I]**

## 4. Implementation recipes (Houdini 22 / Copernicus)

**A. Hotspot field: an inhomogeneous Thomas cluster process.** A Thomas process is a Poisson
process of parent points, each replaced by a Poisson number of offspring with Gaussian
offsets. [22] **[S]** Mapped to Houdini **[I]**:

1. **Cause mask.** Build `cause` as a point float from contact band × corner proximity ×
   exposure × water-exit proximity, using the existing mask stack.
2. **Parents.** Use `scatter` with Density Attribute = `cause` and Force Total Count = 1–3
   per bay or 3–7 per facade, seeded from `seed` and the instance `id`. [23] **[S parms]**
   Give each parent `r` (power law), `amp` (0.5–1) and a cause type (impact, leak, rust).
3. **Field.** In a point wrangle on the target, with parents in input 1:
   `foreach(pt; nearpoints(1, @P, rmax)) hot = max(hot, amp·exp(−d'²/(2(r/2)²)))`,
   where `d' = d + r·0.4·(noise(@P·f) − 0.5)`. For streaks use an anisotropic distance with
   `dy` scaled by 0.2 below the parent and 3 above it. `pcopen` and `pcfilter` also work;
   pcfilter weights by `1−smooth(0, maxd·1.1, d)`. [24] **[S]**
4. **Final mask.** `damage_mask = convexity × exposure × (bg + (1−bg)·hot) × breakup`, with
   bg = 0.1–0.3. Promote `hot` and the cause type to primvars for MaterialX, or rasterize them
   for Copernicus (`rasterizegeo`).
5. **Offspring (chips).** `scatter` on the convex-edge band with Density Attribute =
   `damage_mask`, instead of `chip_points.vfl`'s fixed 0.08 m spacing. Scale chip size by
   `hot`: the largest at the centre.

**B. Edge runs.** Convert convex edges to curves (pre-bevel), `resample`, and use `curveu` ×
the curve length as arclength `s`. Set `run = smoothstep(t−0.1, t+0.1, noise(s/λ + seed))`
with λ = 1–4 m and t chosen so that about 40 % of the length is active, then transfer back.
**[I]**

**C. One field, many layers.** A single `hot` attribute per cause drives everything:
- the chip density;
- the exposed-material ID on the boolean `binsidea` faces;
- a rust halo at about 0.7 r around the chips, steel only;
- a streak from the parent downward;
- dirt at about 1.5 r, softer.

Tiling materials stay in the texture; `hot` lives in the shader, extending the skill's
existing patch-mask approach. **[I]**

**D. Why thresholded fBm still looks uniform.** fBm and Perlin noise are stationary: the
statistics are the same everywhere. A threshold gives the same blob density in every square
metre, with clusters smaller than the noise's lowest octave. At facade scale that reads as an
even sprinkle. Three fixes **[I]**:
- multiply by a very low-frequency, high-contrast mask (wavelength ≥ the object, thresholded
  to 15–25 % coverage);
- use a sparse-point (Worley F1) distance field, which is recipe A in noise form;
- use per-element random selection ([9]): `rand(piece_id + seed) < 0.25` gets heavy damage
  and the rest get background only.

Multiplying noises at several scales helps only when the lowest scale is coarser than the
viewing frame.

**E. Tools.**
- `clusterpoints` is k-means grouping of existing points (`cluster` attribute). It can label
  groups but does not generate clusters. [25] **[S]**
- Labs Edge Damage is driven by curvature, with Mask Attribute and Mask Strength plus a noise
  block (Height, Element Size). Its clustering has to come from your mask, so feed it
  `damage_mask` from recipe A. [26] **[S]**
- Scatter's Relax Iterations makes blue noise, which is the opposite of clustering. Leave it
  off for damage offspring. [23] **[S]**

## 5. Failure modes to check for

1. Evenly spaced chips along every convex edge, with the same size and depth. [2][4]
2. Constant bevel width and highlight on every edge of a kit (the danchi chamfer). **[I]**
3. Grunge tiled on top rather than placed; even coverage; "noise everywhere". [4]
4. Wear on unexposed or concave edges and missing on exposed ones. [2][3]
5. Clustering only at one scale: patchy up close, uniform at 45 m. **[I]**
6. Layers without a shared cause: a chip with no stain, a streak with no source. **[I]**
7. Pristine zones between clusters, the over-correction. The user asked for a low background.
8. Every instance damaged: the 80/20 rule applies across instances as well. **[I]**
9. Shader-only edge wear seen in silhouette. [13]

**Checks.**
- Render `hot` as `Cd` at the facade distance. Expect 3–7 distinct blobs, not a speckle. **[I]**
- Measure the share of convex edge length with chips: about 25–40 %. **[I]**
- Measure the share of chip count inside `hot > 0.5`: about 70 % or more. **[I]**

## Sources

1. Lyubov Vasileva, "Tutorial: Realistic Damage Texturing in Substance 3D Painter," 80.lv, 2024. https://80.lv/articles/breakdown-precision-milling-drilling-machine-made-with-zbrush-substance-3d
2. Polycount threads on edge wear, from search excerpts (the site returns 403 to fetch): https://polycount.com/discussion/comment/2358213 · https://polycount.com/discussion/comment/2357013 · https://polycount.com/discussion/211893/m16a4 · https://polycount.com/discussion/comment/2009283
3. Simon Mercuzot, "SKS: Hard-Surface Texturing in Weapons Art," 80.lv, 2021. https://80.lv/articles/sks-hard-surface-texturing-in-weapons-art
4. Polycount critiques, from search excerpts: https://polycount.com/discussion/comment/2624395/ · https://polycount.com/discussion/238926/wip-fallout-traffic-light-looking-for-feedback · https://polycount.com/discussion/comment/2452426
5. Josh Rife, "Key Factors in Environment Design of LawBreakers," 80.lv. https://80.lv/articles/key-factors-in-environment-design-of-lawbreakers/
6. Augustas Krivelis, "The Yard: 3D Environment Breakdown," 80.lv, 2020. https://80.lv/articles/the-yard-3d-environment-breakdown
7. Milan Art Institute, "Why do my paintings need resting space." https://www.milanartinstitute.com/blog/why-do-my-paintings-need-resting-space
8. Harvey Smith and Matthias Worch, "What Happened Here? Environmental Storytelling," GDC 2010. https://gdcvault.com/play/1012647/What-Happened-Here-Environmental
9. Antoine Déjean, "Broken Tiles," Games Artist. https://gamesartist.co.uk/broken-tiles/
10. PCI Designer's Notebook: Weathering (uneven dirt concentration from runoff, from a search excerpt). https://www.pci.org/PCI_Docs/Publications/Ascent%20Magazine/2013/Summer/Designer's%20Notebook_Weathering.pdf · Heriot-Watt, "Rainwater runoff from building facades: a review." https://researchportal.hw.ac.uk/en/publications/rainwater-runoff-from-building-facades-a-review/
11. Aalto University case study (algae and rust at the bottom corners of windows). https://aaltodoc.aalto.fi/server/api/core/bitstreams/0d446ec8-f9be-4dc7-88fd-7980191dda13/content
12. Corrosionpedia, "Edge failure" and "Edge retention." https://corrosionpedia.com/definition/edge-failure · https://www.corrosionpedia.com/definition/5503/edge-retention
13. Cornelius Dämmrich, geometry-based edge wear plugin, 80.lv. https://80.lv/articles/3d-artist-on-creating-a-geometry-based-plugin-that-makes-realistic-worn-edges
14. WearForge documentation. https://superhivemarket.com/products/wearforge/docs
15. Adobe, Metal Edge Wear (Painter). https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/metal-edge-wear · Edge Damages (Designer). https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/mesh-based-generators/mask-generators/edge-damages.html
16. Adobe, Mask Editor (Painter). https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/mask-editor
17. Mapei, "Spalling concrete: causes…" https://mapei.com/my/en/blog/techical-talk-details/2022/03/16/spalling-concrete-the-causes-and-control-repair-protection-methods
18. Rimkus, "Concrete spalling." https://rimkus.com/article/all-about-concrete-spalling
19. Heavy-duty corner guard data, rated for 0–1000 mm impact height. https://fireprotectiononline.co.uk/heavy-duty-corner-guard · stainless guards for trolley corridors: https://archiexpo.com/prod/inoxsystem-srl/product-131073-1387711.html
20. Weighted-normals and bevel guide. https://www.seeles.ai/features/tools/dcc-weighted-normals-hard-surface-bevel-guide
21. Blender manual, Bevel modifier (width from an attribute). https://docs.blender.org/manual/sr/latest/modeling/modifiers/generate/bevel.html
22. spatstat `rThomas`. https://www.rdocumentation.org/packages/spatstat/versions/1.63-3/topics/rThomas
23. SideFX, Scatter SOP. https://www.sidefx.com/docs/houdini/nodes/sop/scatter.html
24. SideFX, `pcfilter`. https://www.sidefx.com/docs/houdini/vex/functions/pcfilter.html
25. SideFX, Cluster Points SOP. https://www.sidefx.com/docs/houdini/nodes/sop/clusterpoints.html
26. SideFX, Labs Edge Damage 2.0. https://www.sidefx.com/docs/houdini/nodes/sop/labs--edge_damage-2.0.html
27. Adam Kenyon, "Destroyed Beauty in Environment Design," 80.lv (damage concentrated on the most visible element, the staircase). https://80.lv/articles/destroyed-beauty-in-environment-design

**Gaps.** I found no primary source that states "80/20" for texture wear, and no studio
publication (Naughty Dog, Guerrilla, Embark, id, Remedy) that gives cluster counts. The
Guerrilla GDC 2017 placement deck is over 10 MB and was not read.
