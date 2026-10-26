# Believable assets: geometry, construction, clutter, interiors, presentation

For `procedural-assets` after review 30 (danchi v2). It does not repeat what the skill
already has: size classes, 70/30, bevel per kit, interior-mapping basics, weathering that
follows water. Tags: **[S]** sourced (numbered sources at the end), **[I]** inference or a
number derived from a sourced tolerance.

The danchi v2 images show these tells:
- every edge, rail and slab is dead straight;
- every sash is closed at the same depth;
- every pane reflects the same sky;
- the laundry is rectangles;
- the building stands on an empty plane under a high sun.

## 1. Imperfection in geometry

**Real tolerances [S]:**
- Formed concrete: walls within ±6 mm per 3 m and ±12 mm over the full height (a spec citing
  ACI 117) [11]. Joints between precast panels are nominally 12–25 mm, and exist to absorb
  error [10].
- Tempered glass: bow up to 0.3 % of pane length, roller wave about 0.13 mm at a 100–300 mm
  wavelength [7], and the wave direction tilts slightly differently on each pane [8].
- Sheet metal: "oil canning" waviness is inherent to flat cold-rolled metal. It is worse on
  wide, thin panels and shows most in raking light [9].

**Rules [I]:**
- **Real plumb error (about 0.1°) is invisible.** What reads on old buildings is:
  - lippage of 2–5 mm per panel;
  - joint width ±3–5 mm;
  - slab-edge sag of about span/300 (5–10 mm per 3 m bay);
  - handrail droop of 3–8 mm between posts;
  - downpipe kinks of 0.5–1.5°;
  - sashes and doors 0.2–0.5° out of square.

  Exaggerate about 2–5× above the real tolerance, and only where light can reveal it.
- **Glass:** tilt each pane by a seeded 0.05–0.3°, or bow it 2–6 mm. This kills the
  "identical sky in every window" tell.
- **Sashes:** closed 60 %, part-open (0.1–0.6 m) 30 %, open 10 %; the screen on a random
  side. Inner and outer tracks are about 25 mm apart, so a part-open window shows a doubled
  frame and two reflections.
- **Thin metal (AC casings, steel doors, meter boxes, fascia panels):** a bulge of 1–3 mm
  over a 0.3–0.6 m wavelength, plus 1–2 dents seeded by `id`.
- **Edges:** vary the chamfer width ±30 %, and put chips only at contact zones. THE FINALS
  adds edge-softening decals and grout and leak decals where modules meet, rather than more
  geometry [1].
- **Keeping snapping intact:**
  - **(a) Deform after assembly** with world-space fields evaluated on `P`. Neighbours sample
    the same field, so seams stay continuous. THE FINALS stores edits in world space so they
    survive regeneration [1].
  - **(b) Inside a piece,** weight deformation by distance from the footprint boundary: 0 at
    seams, full strength 0.2 m in.
  - **(c) Rigid per-instance offsets** of 1–4 mm normal to the facade behind a recessed joint
    give lippage without gaps. Crytek's modular cloth required identical geometry where pieces
    overlap [20].

## 2. Construction logic and layers of history

- **Studios:**
  - Naughty Dog asked TLOU2 outsourcers for each asset's backstory: owner, how it got there,
    exposure, elapsed time [4].
  - CD Projekt layered four architectural eras into Night City, because real cities show
    several periods at once [2].
- **Rule [I]: every building gets 3–4 timeline events, and each leaves geometry.** For a
  1980s danchi:
  1. **The build:** precast or formed walls, steel rails, the painted gable number, rooftop
     tank and machine room.
  2. **Large-scale repairs (大規模修繕) every 12–15 years:** repaint in a slightly different
     tone, sealant renewed, rails recoated. Leave 1–3 mismatched patches per facade
     (0.5–4 m², ΔL 2–5 %).
  3. **Retrofits:**
     - AC units in only 50–80 % of bays, in 2–3 model generations;
     - refrigerant and drain lines in white duct covers down the wall;
     - BS dishes;
     - replacement aluminium sashes in some flats;
     - surface-run conduit;
     - CCTV and new lamps;
     - external lift towers. UR has documented programmes adding lifts to 1960s–70s
       stair-access blocks [19].
  4. **Decay:** rust bleed at rail bases and anchors, cracked partitions, chalky panels,
     growth at the base.
- **Model, do not texture [I]:**
  - drip grooves under slab edges and copings (about 10–15 mm, 20–30 mm in from the edge);
  - balcony drains and spouts;
  - downpipes with brackets every 1.5–2 m and a shoe at the bottom;
  - recessed sealant joints of 10–20 mm in a different material;
  - rail base plates with bolts;
  - expansion joints every 30–60 m;
  - parapet caps.
- **Danchi balcony details:**
  - Partition boards (隔て板) are emergency break-through panels of 6–10 mm calcium silicate,
    FRP or steel, at least 800 mm high and 600 mm wide, with a gap of at most 150 mm. They age
    by fading, chalking, cracks, warping and rusted screws [18].
  - Floor evacuation hatches sit in a balcony zone at least 1.5 m wide [17].
  - Laundry poles are bought by residents and rest on wall-mounted brackets [16].

## 3. Lived-in clutter and props

- **How much (calibrated from photos) [I]:**
  - 60–80 % of balconies show something: laundry 40–60 % on a sunny day, plants 20–40 %,
    storage boxes 20–30 %, futons 5–15 % (midday), bicycles and strollers 5–10 %.
  - Corridors: umbrellas, a tricycle, pots, nameplates, gas meters.
  - Ground: a bike shelter with 30–80 bikes, notice boards, a netted garbage station, a
    playground.
  - Ishimoto's danchi photographs show dilapidated blocks full of laundry, bicycles,
    discarded toys and greenery [15].
- **Placement:**
  - Cluster it, in asymmetrical fractal groups [3].
  - Phantom Liberty regrouped Night City's detail into clusters with negative space after
    some areas were judged too noisy [2].
  - Drive props from per-flat personas (tidy, family, gardener, vacant) rather than
    independent random draws, and leave quiet bays [I].
- **Soft goods [I]:**
  - **Shirts on hangers:** a 2–4 mm shell, a collar, 3–6 vertical folds, a hem curl, and
    ±5–15° rotation off the pole.
  - **Towels** folded over the pole: two layers, with a 1–2 cm radius at the top.
  - **Pinch-hanger rings (角ハンガー)** of socks: the Japanese signature.
  - **Futons:** 50–80 mm slabs folded over the rail, 40–70 cm hanging outside, a bulge at the
    fold, 2–4 clips.
  - **Vellum:** pin where the real clip or pole is, sim once per garment type, bake 5–10
    variants and instance them with colour swaps. Never sim per instance.
  - Crytek notes that tacking cloth to a pole shortens it locally and creates very specific
    folds [20].
  - **Colour:** mostly white, grey, navy and beige, with about 1 in 10 saturated.

## 4. Interiors behind windows

- **What studios do:** Spider-Man's rooms are interior-mapped, with desks as flat wall
  textures, and they change with viewing corner, which is acceptable at distance [5, 6].
  Commercial UE5 systems add depth-offset foreground layers (blinds, curtains, plants, lamps)
  and pick a room per instance [21, vendor claims].
- **Rules [I]:**
  - **Dark is correct by day; empty is the error.** A room is 3–5 stops below a sunlit
    facade. At 10–50 m the eye reads four things:
    1. a curtain;
    2. a back wall at 3–4 m with window-side falloff;
    3. a ceiling-light shape;
    4. one or two furniture masses.
  - **Layered planes:** drape 5–15 mm behind the glass, lace at 30 mm, a furniture card at
    1–2 m, the back wall at 3–4 m. Seed per flat.
  - **Curtains are the cheapest variation:**
    - lace in 70–90 % of flats;
    - drape closure 0–100 %;
    - 6–10 muted colours;
    - an occasional blind, shoji, or newspaper.

    Vacant flats (2–10 %) get no curtains and a bare, brighter room.
  - **At grazing angles glass is mostly reflection,** so the per-pane tilt in section 1
    matters more than the room on upper floors.

## 5. Scale and detail density

- **Scale comes from familiar human-scale objects** placed near buildings [2]. For the
  danchi: people, bikes, a vending machine, a mailbox bank, 1.1 m rails, 2 m doors, 10–12 m
  utility poles with sagging wires, and estate trees now 8–15 m tall [I].
- **Detail octaves [I]:** each class about 3–5× smaller than the one above: building
  30–100 m, bay 3–6 m, element 0.5–1.5 m, fixing 2–10 cm. A jump of more than 10× (a bare
  slab, then bolts) is why the end walls read as CG. Give the gable a 1–3 m class:
  - panel joints;
  - a pair of downpipes;
  - stain fields;
  - a weathered painted number;
  - vent grilles;
  - or an added lift tower.
- **Roofline at 100–300 m [I]:** water tank on legs, lift and stair penthouses, parapet rails,
  antennas and dishes, a lightning rod. That gives 2–3 height classes.

## 6. Presentation

- **Light:**
  - The midday sun is about 100,000 lux, and auto-exposure reads about EV 14. Key/fill ratios
    are 4:1 for sun, 3:1 at golden hour, 2:1 overcast [12]. UE specifies the sun in lux and
    exposure in EV100 [13].
  - Put the sun at 15–35° elevation and 30–60° off the facade normal, so lippage, sag, oil
    canning and drip grooves rake. A high sun flattens them. Also test overcast, which hides
    nothing [I].
- **Lens [I, with 22]:** eye height 1.5–1.7 m; 24–35 mm full-frame equivalent at street
  level, 50–85 mm for compressed estate shots; verticals kept parallel with a level camera
  or a shift lens [22].
- **Atmosphere:** distance fades toward the sky colour at that screen position, and is never
  paler than the sky behind it. Mid-distance goes bluer, far distance paler [14]. Use the
  atmosphere or height fog, not a single fog colour.
- **Ground contact, the largest tell in v2 [I]:**
  - patched asphalt and painted lines;
  - kerbs and gutters;
  - gravel and planting at the base;
  - a splash band of 0.3–1 m;
  - north-side moss;
  - trees, fences, poles and wires;
  - parked bikes and cars.

  A building shown in a vacuum is a missed opportunity [23].
- **Fakes:** blur changes perceived size, and a high viewpoint with shallow depth of field
  reads as a miniature [24]. The 9-seed aerial sheet on a bare plane already reads like a
  model. Also avoid saturation boosts, bloom, spotless ground and HDR local contrast [I].
- **Imperfection is deliberate.** Bekerman: "in our pursuit of realism, we often find
  ourselves deliberately incorporating imperfections" [25].

## 7. Reviewer critiques and fixes

| Critique | Cause | Fix |
|---|---|---|
| "Too clean / CG" | straight, level, identical geometry; bare plane | §1 world-space deformation and glass tilt; §6 ground |
| "All the same age" | one build event | §2 timeline: patches, retrofit generations, replaced sashes |
| "No story" | props drawn independently | personas, vacant flats, one hero balcony per facade [I] |
| "Uniform bevels / damage" | one chamfer, even chips | ±30 % bevel, contact-zone damage, edge decals [1] |
| "Paper props" | flat cards | thickness, pinned baked sims (§3) |
| "Dead windows" | empty boxes, identical reflections | curtain layers, pane tilt, sash states |
| "Noisy" | detail everywhere | clusters and quiet bays [2, 3] |
| "Scale unclear" | no human-scale objects | bikes, people, poles, trees (§5) |

## Sources

1. SideFX, The procedural buildings of THE FINALS (Embark, 2026): https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
2. 80.lv, Night City built almost entirely by hand: https://80.lv/articles/interview-how-cyberpunk-2077-s-night-city-was-built-almost-entirely-by-hand/
3. Level Design Book, Environment art: https://book.leveldesignbook.com/process/env-art
4. Lemon Sky, The Last of Us Part II: https://www.lemonskystudios.com/case-studies-games/the-last-of-us-part-ii
5. Van Dongen, Interior mapping: https://www.gamedeveloper.com/programming/interior-mapping-rendering-real-rooms-without-geometry
6. Automaton, Spider-Man windows: https://automaton-media.com/en/news/20231201-23558/
7. Agnora, Heat-treated glass distortion: https://agnora.com/distortion-in-heat-treated-glass-understanding-roller-wave-edge-lift-and-bow/
8. Eclat Digital, Tempering distortions: https://eclat-digital.com/?p=3488
9. ATAS and MCA, Oil canning: https://www.atas.com/wp-content/uploads/2019/07/0418-Oil-Canning-Roof-and-Wall-Systems.pdf · https://www.mcelroymetal.com/hubfs/assets/OilCanningTechSheetfromMCA.pdf
10. JVI, Joints in precast (citing PCI MNL-122/135): https://jvi-inc.com/?p=5757
11. Everett specification citing ACI 117: https://lfportal.everettwa.gov/WebLink/0/doc/2090390/Page64.aspx
12. Magnopus, Lighting with photography principles: https://www.magnopus.com/blog/lighting-in-unreal-with-photography-principles
13. Epic, Physical lighting units: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-physical-lighting-units-in-unreal-engine
14. Runevision, Atmospheric perspective (2025): https://blog.runevision.com/2025/06/notes-on-atmospheric-perspective-and.html
15. Ishimoto, *Danchi junrei* (review): https://japaneselit.net/2012/11/23/danchi-junrei/
16. Village House, Balcony laundry: https://blog.villagehouse.jp/en/wp-json/wp/v2/posts/4548
17. Shinjuku City, Balcony evacuation equipment: https://www.city.shinjuku.lg.jp/content/000286330.pdf
18. Assist-All, Partition boards: https://lifestyle.assist-all.co.jp/?p=4944
19. UR lift retrofits: https://www.ur-net.go.jp/west/renaissance/lrmhph000000gbsf-att/02-09.pdf · https://www.UR-net.go.jp/east/press/lrmhph000000by9c-att/ur2015_e0303_tsurukawa.pdf
20. Marvelous Designer, Crytek Hunt: Showdown 1896 (search excerpt; the page body did not load): https://www.marvelousdesigner.com/learn/userspotlight/post/07a44d56d06141cfa8c49190075db904
21. Fab interior shaders (vendor claims): https://www.fab.com/listings/428d45ff-e4e8-456a-84f4-ab7009b9dc7c · https://www.fab.com/listings/a5062af1-de74-4b3b-97ff-67fd4dca53db
22. Shift lens: https://nextlimitsupport.atlassian.net/wiki/spaces/maxwell4/pages/5679360/Shift+Lens · https://blog.nzibs.co.nz/photography/how-to-photograph-tall-buildings/
23. Chaos, 15 tips: https://cgconnect.chaos.com/features/articles/6ae07fc2-photorealistic-architectural-rendering-15-tips-to-follow
24. Held et al., Using blur to affect perceived distance and size (ACM TOG 2010): https://pmc.ncbi.nlm.nih.gov/articles/PMC3088122
25. Bekerman interview: https://www.gandiablasco.com/en/ronen-bekerman-and-artur-tamiola-jury-of-the-international-3d-awards/

**Gaps:** no primary source gives imperfection amplitudes for Spider-Man, Gears, Hitman,
Control or City Sample, and City Sample's window internals are undocumented. The amplitudes
above come from construction tolerances and are marked [I].
