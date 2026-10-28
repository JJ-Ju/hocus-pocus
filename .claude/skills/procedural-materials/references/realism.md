# Realism in materials: variation, weathering physics, clustering

Distilled from research for review 31: Adobe's PBR guide, Lagarde's wet-surface and
calibration notes, the PCI weathering guide (DN-29), facade-soiling studies, Mikkelsen's
hex-tiling paper, and artist breakdowns. Numbers marked *(est.)* are estimates or common
practice, not measurements.

## Roughness carries the story

Adobe calls roughness the map that tells a surface's condition. It should come from causes,
not from noise:

| Cause | Albedo | Roughness |
|---|---|---|
| Damp zones: below sills, slab soffits, shaded base, north faces | 10–25 % darker on porous materials (concrete porosity is about 25 %); paint, metal and glass barely darken | 0.05–0.15 lower *(est., scaled from Lagarde)* |
| Dust on upward faces (copings, sills, the tops of AC units) | toward grey-brown | +0.05–0.1 |
| Hand contact: rails, doors at 0.9–1.2 m, handles | grease darker | −0.1–0.3, in a tight band |
| Repaint patches | hue 1–3°, value ±3 % | −0.05–0.1; most of the mismatch is sheen |
| Glass | — | raised along discrete run-off paths at edges and mullions, not evenly |

A facade base sits around 0.80–0.92, moved ±0.05–0.2 by those causes.

## Albedo variation by scale *(est.)*

| Scale | Causes | Value | Hue, saturation |
|---|---|---|---|
| Macro, 5–30 m | washed and unwashed zones, orientation, repaint campaigns | ±6–12 % | ±2–4°, ±5 % |
| Meso, 0.5–3 m | per panel or bay, pours, touch-ups | ±3–6 % | ±1–3° |
| Micro, under 0.5 m | aggregate, spray-tile grain | ±2–4 % | about 0 |

- **Sun bleaching** on the sunny elevation (south in Japan): value up 3–8 %, saturation down
  10–25 %, toward a chalky grey. Organic reds, oranges and yellows fade most; oxide pigments
  hold.
- **Dirt is a colour, not a grey multiply.** Lerp each layer toward its own colour. A neutral
  multiply reads as shadow painted into base colour.
  - **Soot, atmospheric dirt:** warm desaturated grey-brown, about 0.04–0.10 linear at full
    strength.
  - **Run-off soiling:** brown-grey.
  - **Biofilm on humid concrete:** black where sunlit, dark green where shaded. Orange-red
    *Trentepohlia* grows on north faces.
  - **Moss:** only on horizontal ledges that stay damp.
- **Efflorescence:** white salt (0.6–0.8 linear, rough) in thin bands at cracks, joints and the
  ends of run-off; rare.
- **Rust stains:** burnt orange at the source, a 5–30 cm run, then a diluted red-grey fan where
  the flow slows at a ledge. At 20–50 % opacity in the run.

## How facades weather (PCI DN-29 and the soiling literature)

- **Rain first cleans, then soils.** Run-off washes the upper wall, picks up dirt and drops it
  where it slows down or fans out. Uneven washing by driving rain is the main cause of soiling
  patterns on concrete.
- **Corners and tops are washed.** Windward top corners take 20–30× the rain of the face
  centre. Run-off rarely reaches the ground except at corners and projections. So at macro
  scale, corners and the top floors read paler, and the middle and lower floors dirtier.
- **The rain-shadow line.** Where run-off meets wall that the wind keeps dry, it soaks in and
  leaves a jagged horizontal "zigzag dirt line".
- **Two phases.** A new building shows dark "dirt washing" where run-off concentrates. Once the
  wall has darkened overall, the same paths become pale "white washing" streaks. An old
  building shows both.
- **Streams recur at the same spots** every rain:
  - at window-base corners and mullion edges;
  - at both ends of a sill whose drip stops short;
  - wherever horizontal meets vertical, where streaks are "almost always" present;
  - along soffits that lack a drip groove, staining the wall below.
- **Attachments.** Streak length below a fixture grows with its size and projection, so a big AC
  unit gives a longer streak than a vent.
- **Sun.** Sunlit walls dry faster and stay cleaner. Smooth, light finishes such as spray-tile
  paint show the most washed/unwashed contrast.
- **Base splash band:** darker, damp and rougher, to 0.3–0.5 m, with a ragged top *(est.)*.
- **Paint failure:** large peeling areas mean moisture, so they sit around windows, gutters and
  joints. Small flaking means poor adhesion. Peeling clusters at water sources, not along every
  edge.

## Clustering in texture (80/20)

- **Multiply scales, then threshold.**
  `wear = cause × cluster(5–15 m, thresholded to 15–25 % of the area) × meso(0.5–2 m) × micro`.
  Threshold after the multiply, so the small scales shape the cluster edges instead of
  sprinkling everywhere.
- **The cluster scale must be at least the frame.** Thresholded fBm with a smaller lowest octave
  has the same blob density everywhere: patchy up close, uniform at 45 m.
- **Background floor:** each layer stays at 10–20 % of its hotspot strength outside the
  clusters.
- **Target statistics** for a facade, measured by a `statistics` COP or from a render, as value
  deviation from the base *(est.)*:
  - 70–80 % within ±3 %;
  - 15–25 % moderate;
  - 5 % or less heavy.
- **One cause field.** Damp, streak, roughness drop, algae, rust run and peeling all read the
  same source: a leak point, a sill, a primvar from the generator. Correlated layers read as
  physics.
- **Hero spots on purpose:** a few per facade, such as a failed gutter, a rusty rail above a
  stained slab, a repainted bay.

## Anti-tiling and macro variation

- **Hex tiling.** Blend randomly rotated and offset samples of the same texture to break up a
  tile that repeats everywhere. Mikkelsen's method is cheap and suits normal maps. In Houdini
  22.0.466:
  - MaterialX: `mtlxhextiledimage`, `mtlxhextilednormalmap` (`tiling`, `rotationrange`,
    `scalerange`, `offsetrange`, `falloff`, `falloffcontrast`);
  - COP: `hextile` (texture in `textotile`), `triplanarhextile` (`scalerand`, `rotrand`,
    `contrast`).

  The parms were read from the node types; the nodes' output was not tested.
- **World macro mask.** `mtlxposition` → `mtlxfractal3d`, `mtlxworleynoise3d` or
  `mtlxunifiednoise3d` → `mtlxremap` / `mtlxsmoothstep`, at 0.03–0.2 cycles per metre
  (5–30 m wavelength), value ±6–12 %. Unreal practice multiplies one greyscale texture at 2–3
  scales with softened contrast.
- **Per bay or instance tint.** An id primvar → `mtlxrandomfloat` (`seed`, `min`, `max`) →
  `mtlxhsvadjust`. Read it with `mtlxgeompropvalue`; `mtlxprimvarreader` is not in this build.
- **Layers and decals.** A base material plus a dirty variant blended by mask is the common
  engine pattern (HDRP Layered Lit, Unreal material layers, vertex paint). Decals carry the hero
  20 % (one-off leaks, cracks, patches, rust runs); tiling plus macro masks carry the
  background.

## Values to aim for

| Material | Albedo, linear |
|---|---|
| New concrete | 0.51–0.55 |
| White masonry paint | 0.65–0.8, never above 240 sRGB |
| Worn asphalt | about 0.12 |
| Zinc, metal | 0.81–0.86 |
| Aluminium, metal | about 0.92 |

The 240 sRGB ceiling (L\* 94.4) describes albedo, the colour of the paint under a linear,
correctly exposed light. It does not describe a photographic JPEG. A camera's tone curve and the
photographer's exposure put white paint in direct sun at L\* 96–97 in real danchi photos
(`docs/redesign/research/rR-reference-photos.md`). Keep the albedo in this table. Judge a render's
brightness with `frame_critique.py` (`surf_L_warn` 97.5, fail 98.5).

Aged galvanised steel is a dull grey that reads partly dielectric, roughness 0.5–0.7 *(est.)*.

For reference photographs: overcast or occluded light, nothing clipped, a ColorChecker in frame
facing the sky. Compare a wall's value with the chart's grey patches to estimate its albedo.

## Critiques and fixes

| Failure | Fix |
|---|---|
| Even albedo across the facade | a macro wash plus washed/unwashed bands; corners and top paler |
| Flat roughness | drive it from damp, dust, polish and repaint masks |
| One texture repeated | hex tiling, per-bay hsv, the world macro mask |
| Wear spread evenly | cluster threshold and target statistics |
| Grey-multiply dirt | lerp toward warm, green-black or rust colours |
| Uncorrelated layers | one cause field |
| Only dark streaks | pale white-washing streaks on old walls |
| The same streak under every element | streak length by projection size |
| Clean ground line | a damp splash band and a zigzag rain-shadow line |

## Sources

- PCI, Designer's Notebook DN-29: Weathering: https://www.saraschok.com/corporate787/corporateFiles/1834/DN-29Weathering.pdf
- Blocken, Derome & Carmeliet, rainwater run-off from building facades: a review (2013): https://researchportal.hw.ac.uk/en/publications/rainwater-runoff-from-building-facades-a-review/
- Lagarde, physically based wet surfaces: https://seblagarde.wordpress.com/2013/03/19/water-drop-3a-physically-based-wet-surfaces/
- Lagarde, feeding a physically based shading model: https://seblagarde.wordpress.com/2011/08/17/feeding-a-physical-based-lighting-mode/
- Adobe, The PBR Guide part 2: https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2
- Mikkelsen, practical real-time hex-tiling (JCGT 2022): https://jcgt.org/published/0011/03/05/paper.pdf
- SideFX, Hex Tile COP: https://www.sidefx.com/docs/houdini/nodes/cop/hextile.html
- Physically Based database: https://physicallybased.info/
- Unity photogrammetry workflow: https://unity3d.com/files/solutions/photogrammetry/Unity-Photogrammetry-Workflow_2017-07_v2.pdf
- Joshua Lynch, material creation for games: https://80.lv/articles/material-creation-for-games
- Facade biofilms on concrete (Appl. Sci. 2022): https://www.mdpi.com/2076-3417/12/6/2974
- BRANZ, efflorescence: https://www.branz.co.nz/documents/4018/BU593-Efflorescence.pdf
- NPS Preservation Brief 10, paint problems: https://www.nps.gov/orgs/1739/upload/preservation-brief-10-paint-problems-exterior-woodwork.pdf
- Epic, material layers and decals: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-material-layers-in-unreal-engine
- MachineGames, Aged by Adventure (GDC): https://gdcvault.com/play/1036059/Aged-by-Adventure-CraftingtheTime-Worn
