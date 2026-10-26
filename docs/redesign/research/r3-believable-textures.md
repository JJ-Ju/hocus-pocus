# Believable textures: what reads as real, not procedural

Research for `procedural-materials`, after review 30 (danchi v2). It does not repeat the skill
(height large to small, derived maps, PBR ranges, story layer, primvar story in the shader).
**[S]** = sourced (numbered refs). **[I]** = inference or common practice, not a measurement.

**The diagnosis for danchi v2.** The weathering is cause-driven only in the streaks. Everything
else is one value, one roughness and one spray-tile texture repeated. Real facades are
**differentially** soiled: rain cleans some zones and soils others, so the variation that sells
realism is large, banded and correlated with geometry, not noise [S1, S2].

## 1. Roughness carries the story

- Adobe's PBR guide calls roughness "the most creative map", one that can "tell a story
  about the condition of a surface" [S6]. Joshua Lynch: push contrast "in the color or the
  roughness" [S11].
- **Wetness and damp** change albedo and roughness together. Lagarde's model darkens diffuse
  `lerp(1, 0.2, porosity)` at full wetness and raises gloss through the same factor; concrete
  porosity is about 25 %. Painted, metal and glass surfaces barely darken [S7].
  - Rule: zones that stay damp (below sills, at balcony slab soffits, the shaded base, north
    faces) are **darker by 10–25 % and 0.05–0.15 less rough** than dry wall [I, scaled from S7].
- **Dust settles faster on upward faces and coarse texture** [S1]. On the tops of copings,
  sills and AC units, raise roughness 0.05–0.1 and move albedo toward grey-brown dust [I].
- **Hand contact** (railings, doors at 0.9–1.2 m, handles): roughness drops 0.1–0.3 in a tight
  band [I]. Grease is dark and glossy; old baked-on grime is matte [S24].
- **Glass:** water runs in "discrete streams", heaviest at edges and mullions [S1]. Raise
  roughness along those paths, not uniformly.
- **Range:** real roughness varies within a narrow band [S25]. Use a facade base of 0.80–0.92,
  moved ±0.05–0.2 by stains, damp and polish. Roughness repetition rarely shows unless contrast
  is high [S16].

## 2. Albedo variation

**Scales and amounts** [I; restraint per S11: hue and value variation "present but not
dominate"]:

| Scale | What causes it | Value | Hue / saturation |
|---|---|---|---|
| Macro, 5–30 m | washed and unwashed zones, orientation, repaint campaigns | ±6–12 % (about ±10–20 sRGB at 180) | ±2–4° hue, ±5 % saturation |
| Meso, 0.5–3 m | per panel or bay, pours, touch-ups | ±3–6 % | ±1–3° |
| Micro, < 0.5 m | aggregate, spray-tile grain | ±2–4 % | ~0 |

One Polycount critique asks for "5 or 6 uniform colours" inside one concrete material [S23].

- **Sun bleaching.** Fading is UV degradation of pigments; organic yellows, oranges and reds
  fade most, and oxide pigments hold [S20]. It shows on the sunny elevation (south in Japan).
  - Lift value 3–8 %, cut saturation 10–25 %, shift slightly toward grey or white chalk [I].
- **Repaint patches.** Touch-ups show because old paint has dulled and fresh paint is
  glossier [S21].
  - Patches are rectangles aligned to joints or a bay.
  - Hue offset 1–3°, value ±3 %, **roughness 0.05–0.1 lower** than the aged paint around
    them [I]. Most of the mismatch is sheen, so put it in roughness.
- **Dirt colours** [S1, S17, S18, I]:
  - Atmospheric dirt and soot: warm, desaturated grey-brown, about 0.04–0.10 linear at full
    strength.
  - Run-off soiling: brown-grey, laid down where flow slows or fans out.
  - Biofilm: on humid subtropical concrete, **black where sunlit and dark green where
    shaded** [S17]. Red-orange *Trentepohlia* grows on north-facing concrete [S17], and
    shaded north faces colonise first [S18].
  - Moss: only on horizontal, permanently damp ledges.
- **Efflorescence:** white crystalline salt at cracks, joints and run-off ends [S26]. It
  is lighter than the base (0.6–0.8 linear) and rougher, sits in thin bands, and is rare [I].
- **Rust staining:** true rust stain is "burned red" orange; broad stains are red-grey
  mixes [S19]. Stains sit below anchor bolts, joints and places that are hard to paint [S19].
  Use the skill's rust colour, diluted to 20–50 % opacity in the run [I].
- **Avoid a grey multiply.** Each layer is a **hue-shifted lerp toward its own colour**, with
  a darker value and lower saturation. Never a neutral-grey multiply, which reads as shadow
  painted into albedo [I; S6 keeps lighting out of base colour].

## 3. Macro variation and anti-tiling

- **World-space macro masks.** UE practice multiplies one greyscale texture at 2–3 scales,
  with softened contrast, to break up tiling [S27].
  - On a building, use world-position noise at 0.03–0.2 cycles/m (5–30 m wavelength),
    amplitude ±6–12 % value [I].
  - Also add a per-panel or per-bay random term through an instance or piece id.
- **Hex-tiling and texture bombing** break repetition by blending randomly rotated and offset
  samples [S13, S12].
  - Mikkelsen's method is cheap. It drops histogram preservation and applies a contrast
    function to the blend weights.
  - It is well suited to normal maps [S13].
  - The spray-tile normal and height are the textures most in need of it.
- **Layering:** Unity HDRP Layered Lit stacks up to four materials blended by height or vertex
  colour [S14]. Unreal Material Layers give each layer a mask-driven blend asset [S15]. The
  common pattern is **a base material plus a dirty variant, vertex-painted** [S22].
- **Decals** project base colour, roughness and normal; a receiver can take roughness only, and
  mesh decals wrap edges [S15]. Use them for the hero 20 % (one-off leaks, cracks, patches, rust
  runs) and leave the background to tiling plus macro masks.

## 4. Wear physics on facades

All from PCI DN-29 [S1] unless noted.

- **Rain first cleans, then soils.** Run-off washes the top of the building, picks up dirt, and
  deposits it "when water flow velocity is decreased", for example where it fans out.
  Uneven washing by driving rain is the main cause of soiling patterns on concrete [S2].
- **Where rain hits:** the windward top corners are wettest, then the top and side edges.
  Corners take **20–30×** the rain of the face centre, and run-off rarely reaches the ground
  except at corners and projections. **Macro rule:** corners and top floors washed paler;
  the mid-face and lower floors dirtier.
- **Rain-shadow line.** Where run-off meets the wall sheltered by the wind vortex, it is
  absorbed and leaves a **"zigzag dirt line"**, a jagged horizontal soiling band.
- **Two phases.** A new building shows dark "dirt washing" at concentrated run-off. Later, once
  the wall has darkened, the same paths become **"white washing"**, lighter streaks. Old
  danchi should therefore show both dark streaks and pale washed streaks [S1].
- **Flow:** the run-off film is 0.25 mm thick and moves vertically at no more than 0.9 m/min.
  On smooth surfaces it splits into streams that **recur at the same spots** every rain. Without
  a drip groove, water runs along soffits and stains the wall below; older danchi often lack
  drips [I].
- **Concentrations:** at window base corners and mullion edges; at the ends of sills (a drip
  stopped 50 mm short gives one streak at each end); on inside corners and columns. Where
  horizontal meets vertical there are "almost always" dirt streaks.
- **Sun and texture:** sunlit walls dry faster and attract less dirt. Light, smooth finishes
  such as spray-tile paint accentuate the washed/unwashed contrast. Facades with no capillary
  buffering stain strongly under projections [S4].
- **Base splash zone.** Splash and run-off meet at the base [S28]. A common rule of thumb is
  about 150 mm of raindrop bounce, with soil splash plus damp to 0.3–0.5 m [I, weakly
  sourced]. Use a darker, damp, rougher band with a ragged top.
- **Attachments.** Japanese studies of 雨筋よごれ (rain-streak soiling) find that streaks
  below fixtures depend on the attachment angle, its size and how far it projects from the
  wall [S29]. Large, projecting AC units and vents give longer streaks.
- **Paint failure.** Large peeling sections point to moisture, around windows, doors and
  gutters; small flaking points to adhesion [S30]. Peeling clusters near water sources and
  joints; it is not spread by edge curvature alone [I].
- **Rust progression** [I, consistent with S19]:
  1. a pinpoint orange bloom at the fixing;
  2. a thin run of 5–30 cm along the flow path;
  3. a fanned, diluted stain spreading where the flow slows at ledges;
  4. eventually spalling over corroding bar.

## 5. Clustering wear (80/20)

- **Multiply scales, then threshold** [I]:
  `wear = cause × cluster(5–15 m, thresholded to 15–25 % of area) × meso(0.5–2 m) × micro`.
  Threshold **after** the multiply, so the small scales shape the edges of the large clusters
  instead of sprinkling everywhere.
- **Background floor.** Outside the clusters, keep each layer at 10–20 % of its hotspot
  strength, never zero, so the wall still reads aged [I].
- **Target statistics**, checked with `statistics` on value deviation from the base [I]:
  - about 70–80 % of the facade within ±3 % of the base value;
  - 15–25 % moderate;
  - 5 % or less heavy.
- **One cause, many layers.** Drive the streak, damp darkening, roughness drop, algae, rust run
  and peeling from the **same** cause field: a leak source id, a sill, or a `stop`/`wexp`
  primvar. Correlated layers read as physics; independent noises read as procedural [I;
  MachineGames' GDC talk frames weathering as reinforcing the surface's story, S31].
- **Pick hero spots deliberately**, a few per facade: a failed gutter, a rusty balcony rail
  above a stained slab, a repainted bay. Everything else stays quiet [I].

## 6. Reference capture and value targets

- **Capture** [S8, S9]: overcast light or an occluder; exposure mid-histogram with nothing
  clipped; an X-Rite ColorChecker in frame facing the sky; white balance in 32-bit (divide by
  the second grey patch, multiply by 0.6); cross-polarisation for pure diffuse albedo.
- **Value check:** compare the wall with a chart patch in the same light to estimate linear
  albedo, then match the material's mean to it [I].
- **Targets:** new concrete 0.51–0.55 linear [S8, S10]; worn asphalt 0.12 [S8]; zinc 0.81–0.86
  and aluminium 0.92, metal [S10]; aged galvanised steel a dull, partly dielectric grey at
  roughness 0.5–0.7 [I]; white masonry paint 0.65–0.8 linear, capped at 240 sRGB [I, S6].
  Megascans calibration against a ColorChecker is second-hand, and I found no published
  concrete numbers: **unverified**.

## 7. Implementation in Copernicus and MaterialX

Node names were checked on the live Houdini 22.0.466 node-type list. Parms marked † were read
from parm templates; the node behaviour was not tested.

| Need | Node (verified) | Notes |
|---|---|---|
| Spray tile identical everywhere | `mtlxhextiledimage`†, `mtlxhextilednormalmap` | parms `tiling`, `rotationrange`, `scalerange`, `offsetrange`, `falloff`, `falloffcontrast` |
| Bake a bigger non-repeating tile | COP `hextile` (input `textotile`), `triplanarhextile`† (`scalerand`, `rotrand`, `contrast`) | |
| World macro masks | `mtlxposition` → `mtlxfractal3d` / `mtlxworleynoise3d` / `mtlxunifiednoise3d` → `mtlxremap` / `mtlxsmoothstep` | 0.03–0.2 cycles/m |
| Per bay or instance tint | `mtlxgeompropvalue` (an id primvar) → `mtlxrandomfloat`† (`seed`, `min`, `max`) → `mtlxhsvadjust` | `mtlxprimvarreader` is not in this build |
| Layer mixing | `mtlxmix`; COP `maskcombine`† (`post_contrast`, `post_gamma`, `post_ramp`) | |
| Damp and algae masks | `grunge_moisture`, `grunge_moldspots` × the cause mask | |
| Flow on unique gables | `rasterizesetup`/`rasterizegeo`; `adjacency_distort`† (`dir`, `streak`), `geotoadjacency` | seam-aware flow is untested |

Not found: a `texturebomb` COP, or a `paint3d` type by that name (there is a `paint`); both are
unverified.

**Shader recipe for the danchi wall** [I]:
- albedo = base × hsv(per-bay random) × macro value wash × washed/unwashed band (a function
  of height, corner distance and `wexp`), then lerps toward dirt, algae and rust colours by
  correlated masks;
- roughness = base + dust on top faces − damp − repaint sheen + stains.

## 8. Critique failure modes and fixes

| Failure | Fix |
|---|---|
| Even albedo across the facade | a macro wash plus washed/unwashed bands; corners and top paler [S1] |
| Flat roughness | drive it from the damp, dust, polish and repaint masks (sec. 1) |
| One texture repeated | hex-tile it, plus per-bay hsv and the world macro [S13] |
| Wear spread evenly | cluster threshold and target statistics (sec. 5) |
| Grey multiply dirt | lerp toward warm or green-black dirt colours |
| Layers uncorrelated | one cause field drives every layer |
| Only dark streaks | add pale "white washing" streaks on old buildings [S1] |
| Same streaks under every element | vary length by projection size and angle [S29] |
| Damage random, not placed | concentrate on lower facades and corners (Polycount critique, [S23]) |
| Clean ground line | add a damp splash band and a zigzag rain-shadow line [S1] |

## Sources

1. PCI, *Designer's Notebook DN-29: Weathering* (Ascent 2013) — https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf
2. Beijer & Johansson, driving rain against concrete walls (1976) — https://trid.trb.org/View/48399
3. Blocken, Derome & Carmeliet, rainwater run-off from building facades: a review (2013) — https://researchportal.hw.ac.uk/en/publications/rainwater-runoff-from-building-facades-a-review/
4. Corrao, Blocken et al., soiling of facades, CFD (2006) — https://iris.unipa.it/handle/10447/24593
5. Etyemezian et al., NPS/NCPTT soiling and erosion CFD (2000) — https://www.nps.gov/subjects/ncptt/upload/2000-12.pdf
6. Adobe, The PBR Guide part 2 — https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2
7. Lagarde, Water drop 3a and 3b, physically based wet surfaces — https://seblagarde.wordpress.com/2013/03/19/water-drop-3a-physically-based-wet-surfaces/ ; https://seblagarde.wordpress.com/2013/04/14/water-drop-3b-physically-based-wet-surfaces/
8. Lagarde, Feeding a physically based shading model — https://seblagarde.wordpress.com/2011/08/17/feeding-a-physical-based-lighting-mode/
9. Unity Photogrammetry Workflow (Lachambre, 2017) — https://unity3d.com/files/solutions/photogrammetry/Unity-Photogrammetry-Workflow_2017-07_v2.pdf
10. Physically Based database — https://physicallybased.info/
11. Joshua Lynch, Material creation for games, 80.lv — https://80.lv/articles/material-creation-for-games
12. SideFX, Hex Tile COP; What's new in H22 Copernicus — https://www.sidefx.com/docs/houdini/nodes/cop/hextile.html ; https://www.sidefx.com/docs/houdini/news/22/copernicus.html
13. Mikkelsen, Practical real-time hex-tiling, JCGT 2022 — https://jcgt.org/published/0011/03/05/paper.pdf
14. Unity HDRP Layered Lit — https://docs.unity3d.com/Packages/hdrp/manual/Layered-Lit-Shader.html
15. Epic, Material Layers; Decal Materials; Mesh Decals — https://dev.epicgames.com/documentation/en-us/unreal-engine/using-material-layers-in-unreal-engine ; https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine ; https://dev.epicgames.com/documentation/en-us/unreal-engine/using-mesh-decals-in-unreal-engine
16. Unreal forum, Texture Bombing — https://forums.unrealengine.com/t/texture-bombing/65652
17. Lime concrete facade biofilms, Wuhan, Appl. Sci. 12(6) 2974; *Trentepohlia umbrina* on concrete (Ann. Microbiol. 2019) — https://www.mdpi.com/2076-3417/12/6/2974 ; https://www.doi.org/10.1007/S13213-019-01472-9
18. Piontek, biodeterioration of facades (CEER 2018) — https://yadda.icm.edu.pl/baztech/element/bwmeta1.element.baztech-5e2173cb-115b-4e36-a7fc-214a5c84857c/c/ceer2018_3_piontek_biodeterioration.pdf
19. TRB 1975, rust staining from weathering steel — https://onlinepubs.trb.org/Onlinepubs/trr/1975/547/547-007.pdf
20. Rodda Paint and Resene, fading and colour retention — https://www.roddapaint.com/problem-solver/fading-poor-color-retention/ ; https://m.resene.co.nz/archspec/cpd_earn_points/pdfs/CPD_decoratingwithcolourandstyle.pdf
21. CertaPro, touch-up mismatch; Sherwin-Williams, flashing — https://certapro.com/blog/residential/why-touch-up-paint-doesnt-match/ ; https://www.sherwin-williams.com/en-us/project-center/maintenance-repair/paint-flashing
22. Michael Andreula, environment texturing, 80.lv — https://80.lv/articles/understanding-texturing-for-environment-design
23. Polycount critiques: concrete wall colour; city vertex-paint material — https://polycount.com/discussion/comment/2636775 ; https://polycount.com/discussion/comment/1482912
24. 80.lv, rusted stove texturing (grease and baked-grime roughness) — https://80.lv/articles/how-to-texture-an-authentic-old-stove-with-substance-3d-painter
25. Chaos V-Ray tip, realistic roughness maps — https://novedge.com/blogs/design-news/v-ray-tip-building-realistic-roughness-maps-in-v-ray
26. BRANZ BU593, Efflorescence — https://www.branz.co.nz/documents/4018/BU593-Efflorescence.pdf
27. Versluis, macro variation for UE materials — https://www.versluis.com/2023/05/how-to-use-macro-variations-for-unreal-engine-landscape-materials/
28. Remmers, plinth restoration (splash zone) — https://en.remmers.com/en/building-floor-protection/refurbishment/plinth-refurbishment/c/c33154
29. Nihon University CST, 雨筋よごれ studies (read through a search summary; the PDFs returned 503) — https://www.cit.nihon-u.ac.jp/laboratorydata/kenkyu/kouennkai/reference/No.46/pdf/4-50.pdf
30. NPS Preservation Brief 10, exterior paint problems — https://www.nps.gov/orgs/1739/upload/preservation-brief-10-paint-problems-exterior-woodwork.pdf
31. MachineGames, Aged by Adventure (GDC) — https://gdcvault.com/play/1036059/Aged-by-Adventure-CraftingtheTime-Worn

Notes on the sources:
- S4, S5, S17, S18, S20, S23, S29 and S30 were read through search abstracts or snippets, not
  in full.
- S1, S7, S8, S9, S11 and S12 were read directly.
