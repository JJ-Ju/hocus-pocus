# Believability: what makes a generated asset read as real

Distilled from research for review 31: environment-art breakdowns, building-science sources on
tolerances and weathering, and critiques of the danchi tests. Numbers marked *(est.)* are
estimates scaled from real tolerances or common practice, not published studio figures.

## 1. Clusters with a background: the 80/20 rule

Real detail is caused, and causes are local, so most of any notable detail sits on a small part
of the surface. Notable wear, damage, dirt, clutter and retrofits each go about 70–85 % into
clusters covering 15–25 % of the area or edge length *(est.)*. Everything else carries a low
background of the same layer, 10–30 % of the hotspot strength, so nothing is pristine.

- **Composition, not scatter.** One artist (Vasileva, 80.lv) warns that "chaotic scattering
  without composition" looks unattractive. A Polycount rule is to generate wear from a convexity
  mask, then erase roughly 75 % of it.
- **Focus, don't just reduce.** Josh Rife (LawBreakers): "we don't reduce detail so much as
  focus it".
- **Clusters at every level**, matching the recursive method:

  | Level | Notable clusters |
  |---|---|
  | Piece, instanced | 0–2; 30–50 % of instances get none (per-instance random subset) |
  | Bay | 1–3, one dominant |
  | Facade | 3–7 "stories": ground floor, a corner, below a failed gutter, one or two neglected flats, a repainted bay |
  | Building | biased by orientation: weather side and base dirtier, sheltered side cleaner |

- **Inside a cluster:** one primary mark carries about half the weight, then 3–8 secondary
  marks at 0.3–0.5× its size, then a sprinkle. Sizes follow a power law
  (`r = rmin·(rmax/rmin)^(u^k)`, k = 2–4). Falloff is soft and noise-warped, never a disc.
- **One cause, several effects.** A hotspot is a cause with a type, and every layer reads it at
  its own radius:
  - **an impact:** chips, then exposed substrate, then grime in the chips;
  - **a leak:** stain at the source, a streak below it, algae where it stays damp, a pale washed
    band beside it;
  - **painted steel:** rust at the chip, a blister halo, then a run.

  Layers placed by independent noises read as procedural, even when each one alone looks right.
- **Why thresholded noise still looks uniform.** fBm has the same statistics everywhere, so it
  gives the same blob density in every square metre. The clusters need a scale at least as big
  as the frame: sparse hotspot points with falloff, a mask whose wavelength is the size of the
  object, or a random subset of elements (`rand(id + seed) < 0.25`).
- **Check it numerically.** Render the cause field as `Cd` at the level's distance and expect a
  handful of distinct blobs, not speckle. Measure the share of the layer inside the hotspots.
  `procedural-mesh-damage` has the cluster-mask script, and `procedural-materials` has the
  texture-side recipe.

## 2. Imperfection in the geometry

Real tolerances are small: formed concrete is within ±6 mm per 3 m (ACI 117), and precast
joints are 12–25 mm wide and exist to absorb error. What reads on old buildings is these, about
2–5× exaggerated and placed where raking light shows them *(est.)*:

| Element | Imperfection |
|---|---|
| Wall panels | lippage 2–5 mm per panel; joint width ±3–5 mm |
| Slab edges, copings | sag about span/300 (5–10 mm per 3 m bay) |
| Rails | droop 3–8 mm between posts |
| Downpipes | kinks 0.5–1.5° |
| Doors and sashes | 0.2–0.5° out of square |
| Glass | each pane tilted by a seeded 0.05–0.3°, or bowed 2–6 mm. Tempered glass really bows up to 0.3 % of its length, which breaks the identical sky reflected in every window |
| Thin sheet metal (AC casings, steel doors, meter boxes, fascias) | oil-canning bulge of 1–3 mm over 0.3–0.6 m, plus 1–2 dents seeded by `id` |
| Sashes | 60 % closed, 30 % part open (0.1–0.6 m), 10 % open. A part-open sash shows a doubled frame and two reflections |

Keep snapping intact:
- **Deform after assembly** with a world-space field evaluated on `P`. Neighbours sample the same
  field, so seams stay closed.
- **Inside a piece,** fade the deformation to 0 at its footprint boundary, reaching full
  strength 0.2 m in.
- **Rigid offsets.** Per-instance offsets of 1–4 mm along the facade normal, behind a recessed
  joint, give lippage without gaps.
- **Edge decals.** Embark's THE FINALS adds edge-softening, grout and leak decals where modules
  meet, instead of more geometry.

## 3. Construction logic and layers of history

- **Backstory per asset.** Naughty Dog briefed TLOU2 outsourcers with each asset's backstory:
  owner, how it got there, exposure, elapsed time. CD Projekt layered four eras into Night City,
  because real cities show several periods at once.
- **Give every building 3–4 timeline events, and make each one leave geometry.** For a 1980s
  danchi:
  1. **Build.** Formed or precast walls, steel rails, the painted gable number, the tank and the
     machine room.
  2. **Large-scale repairs (大規模修繕) every 12–15 years.** Repaint in a slightly different
     tone; leave 1–3 mismatched patches per facade (0.5–4 m², value off by 2–5 %, mostly a sheen
     difference). Sealant renewed, rails recoated.
  3. **Retrofits.**
     - AC units in only 50–80 % of bays, in 2–3 model generations.
     - Refrigerant and drain lines in white duct covers down the wall.
     - BS dishes, replacement aluminium sashes in some flats, surface-run conduit, newer lamps
       and CCTV.
     - External lift towers on older stair-access blocks (UR has such programmes).
  4. **Decay.** Rust bleed at rail bases and anchors, cracked partition boards, chalky panels,
     growth at the base.
- **Model the water and fixing details, don't texture them:**
  - drip grooves under slab edges and copings (10–15 mm wide, 20–30 mm in from the edge);
  - balcony drains and spouts;
  - downpipes with brackets every 1.5–2 m and a shoe at the bottom;
  - recessed sealant joints of 10–20 mm, in a different material;
  - rail base plates with bolts;
  - expansion joints every 30–60 m.
- **Detail octaves.** Each size class is about 3–5× smaller than the one above: building
  30–100 m, bay 3–6 m, element 0.5–1.5 m, fixing 2–10 cm. A jump of more than 10×, such as a
  bare 30 m end wall carrying only a number, reads as CG. Give it a 1–3 m class: panel joints,
  downpipes, stain fields, vents, the number's own weathering, an added lift tower.

## 4. Lived-in clutter and soft goods

- **Personas, not independent draws.** Give each flat a persona: tidy, family, gardener,
  elderly, vacant. The persona picks its props, curtains, AC and laundry together. Then leave
  some bays quiet and give each facade one hero balcony. Cyberpunk's Phantom Liberty regrouped
  noisy areas into clusters with negative space between them.
- **Rough frequencies for a danchi on a sunny day** *(est., from photographs)*:

  | Item | Share of balconies |
  |---|---|
  | Anything at all | 60–80 % |
  | Laundry | 40–60 % |
  | Plants | 20–40 % |
  | Storage boxes | 20–30 % |
  | Futons, at midday | 5–15 % |
  | Bicycles, strollers | 5–10 % |

  Corridors carry umbrellas, a tricycle, pots, nameplates. The ground carries a bike shelter, a
  netted garbage station and a notice board.
- **Soft goods.** Make them as thin shells (2–4 mm) with folds, not cards:
  - **shirts on hangers:** a collar, 3–6 vertical folds, a hem curl, and ±5–15° of rotation off
    the pole;
  - **towels:** two layers folded over the pole, with a 1–2 cm radius at the fold;
  - **sock rings:** the pinch-hanger ring of socks (角ハンガー) is the Japanese signature;
  - **futons:** 50–80 mm slabs folded over the rail, with a bulge at the fold and 2–4 clips.

  For more, simulate each garment type once with Vellum, pinned where the real pole or clip is.
  Bake 5–10 variants and instance them with colour swaps; never simulate per instance. Colours
  are mostly white, grey, navy and beige, with about 1 in 10 saturated.

## 5. Interiors behind glass

- **Dark by day is correct; empty is the error.** A room is 3–5 stops below a sunlit facade. At
  10–50 m the eye reads a curtain, a back wall about 3–4 m deep with falloff from the window, a
  ceiling-light shape, and one or two furniture masses.
- **Layer planes per flat, seeded:** drape 5–15 mm behind the glass, lace at 30 mm, a furniture
  card at 1–2 m, the back wall at 3–4 m. Interior mapping does the same in a shader (Spider-Man's
  rooms).
- **Curtain variation is the cheapest:**
  - lace in 70–90 % of flats;
  - drape closure anywhere from 0 to 100 %;
  - 6–10 muted colours;
  - the occasional blind or newspaper.

  Vacant flats (2–10 %) get no curtains and a bare, brighter room.
- **At grazing angles glass is mostly reflection,** so on upper floors the pane tilt (§2) matters
  more than the room.

## 6. Presentation: the render must not give it away

- **Ground context.** A building on an empty plane is the largest single tell. Add:
  - patched asphalt with painted lines, kerbs and gutters;
  - planting and gravel at the base, a damp splash band of 0.3–1 m, moss on the north side;
  - trees (danchi trees are now 8–15 m tall), fences, utility poles 10–12 m tall with sagging
    wires;
  - bikes, cars, a vending machine, a person or two for scale.
- **Sun.** Put the sun 15–35° high and 30–60° off the facade normal, so lippage, sag, drip
  grooves and oil-canning rake. A high sun flattens all of them. Check an overcast version too:
  it hides nothing.
- **Camera.** Eye height 1.5–1.7 m; 24–35 mm at street level, 50–85 mm for compressed estate
  shots; verticals kept straight with a level camera.
- **Atmosphere.** Distance shifts toward the sky colour behind it: bluer at mid distance, paler
  far away. Use an atmosphere or height fog, not one fog colour.
- **What fakes it.** A high viewpoint with blur or shallow depth of field reads as a miniature, as
  does an aerial over a bare plane. Saturation boosts, heavy bloom and spotless ground all give it
  away too.

## 7. Critiques and fixes

| Critique | Usual cause | Fix |
|---|---|---|
| "Too clean, CG" | straight, level, identical geometry; bare ground | §2 world-space imperfection, glass tilt; §6 ground |
| "Uniform damage or wear" | even spacing, one bevel highlight everywhere | §1 clusters plus background; wear in runs along edges |
| "All the same age" | one build event | §3 timeline: patches, retrofit generations, replaced sashes |
| "No story" | props and wear drawn independently | personas, one cause field for all layers, hero spots |
| "Paper props" | flat cards | §4 shells with folds, baked sims |
| "Dead windows" | empty boxes, identical reflections | §5 layers, pane tilt, sash states |
| "Noisy" | detail everywhere | §1 clusters and quiet bays |
| "Scale unclear" | no human-scale objects | §6 people, bikes, poles, trees |

## Sources

- SideFX, procedural buildings of THE FINALS: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
- 80.lv, Night City built almost entirely by hand: https://80.lv/articles/interview-how-cyberpunk-2077-s-night-city-was-built-almost-entirely-by-hand/
- Lemon Sky, The Last of Us Part II: https://www.lemonskystudios.com/case-studies-games/the-last-of-us-part-ii
- Lyubov Vasileva, realistic damage texturing, 80.lv: https://80.lv/articles/breakdown-precision-milling-drilling-machine-made-with-zbrush-substance-3d
- Josh Rife, environment design of LawBreakers, 80.lv: https://80.lv/articles/key-factors-in-environment-design-of-lawbreakers/
- Smith & Worch, What Happened Here? (GDC 2010): https://gdcvault.com/play/1012647/What-Happened-Here-Environmental
- Antoine Déjean, broken tiles (random subset per element): https://gamesartist.co.uk/broken-tiles/
- Van Dongen, interior mapping: https://www.gamedeveloper.com/programming/interior-mapping-rendering-real-rooms-without-geometry
- Glass bow and roller wave: https://agnora.com/distortion-in-heat-treated-glass-understanding-roller-wave-edge-lift-and-bow/
- Oil canning (MCA): https://www.mcelroymetal.com/hubfs/assets/OilCanningTechSheetfromMCA.pdf
- Precast joints (JVI, citing PCI): https://jvi-inc.com/?p=5757
- Balcony partition boards: https://lifestyle.assist-all.co.jp/?p=4944
- UR lift retrofits: https://www.ur-net.go.jp/west/renaissance/lrmhph000000gbsf-att/02-09.pdf
- Magnopus, lighting with photography principles: https://www.magnopus.com/blog/lighting-in-unreal-with-photography-principles
- Atmospheric perspective: https://blog.runevision.com/2025/06/notes-on-atmospheric-perspective-and.html
- Held et al., blur and perceived size (ACM TOG 2010): https://pmc.ncbi.nlm.nih.gov/articles/PMC3088122
- Level Design Book, environment art: https://book.leveldesignbook.com/process/env-art
