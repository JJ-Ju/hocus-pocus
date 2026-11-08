# Vines and creepers on danchi facades: scoping a vine generator

Date: 2026-11-01. Scope: climbing plants on a five-storey 1960s–80s RC danchi in Japan (painted concrete, steel
balcony rails), delivered to Unreal Engine 5 and Godot 4. The AD's round-H review asked for more spread of growth
at Derelict and said vine growth "might be a new asset/generator class". This note scopes that class. It does
not change the algae layer.

## Conventions

- Tags: **[C]** consensus, **[P]** a practitioner's practice, **[M]** measured data, **[I]** my inference. **[n]**
  is a source in §7. "(snippet)" means I saw it only in a search summary.
- Names in `code` are from `scripts/weathering/weather_fields.py` (rulebook 1.5). The web-search budget, shared
  by all agents, ran out part-way. §6 lists what went unchecked.

## 0. Summary

1. Boston ivy and *Hedera* are on 80 % of the 827 greened walls in Suginami, Tokyo [M][30]. Kudzu and wisteria
   twine [C][22][23], so on a danchi they need rails, pipes or fences [I].
2. Boston ivy reaches 8–12 m in 5–10 years [C][18]; kudzu grows up to 0.26 m a day [M][23]. One Boston ivy needs
   6–19 years to reach a 15 m roof [I].
3. Best fit: an arrival-time front in facade space decides *where*, space colonisation or Luft-style walkers draw
   the *stems*, and leaves are instances. It is a new generator class, coupled both ways to weathering [I].
4. Vines buffer the wall: the daily range was 4.3 °C under ivy and 7.9 °C on bare stone [M][33]. Removal leaves
   pad marks and lifted paint [P][21][37], and, I expect, a cleaner ghost [I].

## 1. What grows on these buildings

| Plant (Japanese name) | Climbs by | Leaves | Size and rate | On a danchi |
|---|---|---|---|---|
| Boston ivy, *Parthenocissus tricuspidata* (ツタ, ナツヅタ) | tendrils ending in adhesive discs [C][21][24] | deciduous; red to purple in autumn [C][18][24] | 8–12 m tall, 4–8 m wide in 5–10 yr [C][18] | blank gables, stair cores [I] |
| Japanese ivy, *Hedera rhombea* (キヅタ, フユヅタ) | aerial rootlets [C][20] | evergreen [C][20] | 1.5–2.5 m in 5–10 yr, a UK garden figure [C][20]; *H. helix* 8–12 m in 10–20 yr [C][19] | shaded faces, joints [I] |
| Kudzu, *Pueraria montana* var. *lobata* (クズ) | twining [C][23] | die back in winter [I] | up to 0.26 m/day, 15 m per season [M][23] | fences, rails, poles by waste ground [I]; smothers its hosts [C][23] |
| Japanese wisteria, *Wisteria floribunda* (フジ) | twines clockwise [C][22] | deciduous; spring flowers [C][22] | stems 3–7.6 m or more; needs a sturdy support [C][22] | rails, downpipes, grilles [I] |

**Attachment.**
- Boston ivy pads attach in at least two steps, and young pads held 28 % of the force of old, lignified ones
  [M][26]. A much-quoted 13.7 N per pad comes from a retracted paper [C, snippet][28]. Ivy roots attach in four
  phases: contact, a close fit, chemical adhesion, then a change in the shape of the root hairs [M][27].
- Tokyo's guide: Boston ivy holds strongly on concrete and also holds on wood and glass. *Hedera* and *Ficus
  pumila* hold on wood and concrete but not on glass. Smooth walls colonise poorly, so roughen them or add coir.
  A photo shows *Hedera* following the joints [P][29].
- Twiners need a rough mesh or wires about 30–40 cm apart [P][29]. Wisteria should not climb downpipes, because
  thick shoots can pull a pipe off [P][32]. Kudzu is native in Japan from 30° to 44° N [C][23].

**Rates and years to cover.**
- From the RHS figures, Boston ivy climbs 0.8–2.4 m a year and common ivy 0.4–1.2 m [I][18][19]. Boston ivy can
  green about 1 m² of wall in one summer [C][24]. I found no rate for wisteria.
- Self-clinging climbers are among the slowest ways to green a wall; planter and unit systems are fastest [P][29].
  A German installer expects several years, at least 1–2, to cover the planned area [P][32].
- The danchi is about 15 m to the parapet (2.8 m floors). One Boston ivy reaches it in 6–19 years, and a 60 m
  front needs 8–15 plants to close at 4–8 m spread each [I].
- In a Kyoto trial, Boston ivy grew better on north and west walls than on south and east ones. The gap was
  significant from September for plants set out in April; the authors blame too much sun [M, snippet][31].

**Seasons and life.** In Tokyo, Boston ivy leafs out about April and reddens in October–November [I]. The blade
falls before the petiole [C][24]; bare winter stems show the pad network [I]. Birds eat its 8 mm berries [C][21],
so seedlings appear on ledges and in gutters [I]. *Hedera* stays green [C][20]; kudzu dies back in late autumn
[I]. *Parthenocissus* is a main genus in the re-greening of East Asia's abandoned villages [C][25].

**Who keeps vines.** Suginami's FY2017 survey counted 827 wall-greening sites with 30,511 m²: Boston ivy 347 sites
and 15,544 m², *Hedera* 315 and 11,595 m², wisteria 11 and 213 m². Private houses hold 654 sites, public housing
2 (50 m²). Since 2012 the sites fell by 311 while the area rose by 5,280 m², which the survey credits to growth.
Summer green curtains (goya, morning glory) covered 688 sites and 4,972 m² [M][30]. So vines on a public danchi
read as neglect, and a lived-in preset could carry green curtains on the balconies [I].

## 2. Growth algorithms

**Luft's Ivy Generator** (2007, v1.3, GPL, OBJ in and out):
- One root grows under weighted pulls: its earlier directions, a random vector, adhesion to nearby surfaces, an
  up vector and gravity. The aim was convincing vegetation, not biology; LODs were planned, not released [C][1].
- Blender's port: steps of 0.02 m; weights primary 0.5, random 0.2, adhesion 0.1 (within 1.0 m) and gravity 1.0,
  rising with free length; a branch dies after 0.5 m free; branching 0.05; quad leaves at 0.35 [P][2].
- Fit: good stems and hanging curtains. It casts rays, so it slows on complex scenes [C][1][P][2].

**Space colonisation** (Runions, Lane, Prusinkiewicz 2007):
- Each attraction point pulls its nearest node within the radius of influence d_i. The node steps D along the
  normalised sum of unit vectors to its points. A point is removed once a node comes within the kill distance
  d_k. An added vector gives tropism, and obstacles delete the points beyond them [C][3].
- N = 12,000 at d_k = 2D gives dense crowns, N = 375 at d_k = 20D sparse ones, and a small d_i wiggly branches.
  One tree took seconds to minutes on a 3 GHz CPU [M][3]. Fit: scatter points on the wall by a guide density and
  keep nodes on the plane; competition for space then spaces the stems [I].

**L-systems.** Houdini's L-System SOP rewrites strings for a turtle. It prunes with `in()` against a test
geometry, bends toward −Y and reads images with `pic()`; cost grows exponentially with generations [C][5]. Open
L-systems trade data with the environment: collisions, space and light [C][4]. Fit: twig, leaf and petiole
motifs, not following a wall [I].

**Agents on a guide field.**
- Hädrich et al. model climbers as linked particles that react to light, wind and obstacles [C][6]. They ran 20
  plants with 25k branches in real time [M][6].
- Ours would walk the 2D facade grid. Heading = old heading + up + gradient of a guide field (wet, rough, joints,
  inside corners) + noise. Windows repel, edges stop the climb, and gravity takes over past free edges [I].
- Find Shortest Path SOP does this on a mesh: point or primitive costs, a custom edge cost (cheaper upward),
  turning costs, an "any start to each end" mode [C][7]. The Titan Ivy tool uses it, per a comment [P][8].

**Existing tools.**
- Houdini: no SideFX ivy or vine node, and Houdini 22's What's New has no plant section [C][10]. Labs has tree
  tools (trunk, branch, leaf; thigmotropism) but no ivy node [C, snippet][9], and is not on the test machine [38].
- Project Titan Ivy Tool (2022, Houdini 19), a tutorial HDA, grows ivy from a shape, adds leaves, simulates
  falling branches and runs in Unreal through Houdini Engine [P][8]. Community HDAs on GitHub and Fab barely
  document their method [P][11].
- Blender IvyGen (Luft's method) is an as-is extension, 0.1.5, for Blender 4.2+ [C][12]; it offers nothing
  Houdini lacks [I]. SpeedTree's docs returned 403; from memory, its mesh forces wrap growth onto a mesh [I].
- UE5 PCG: Houdini Engine's PCG plugin runs an HDA as a node in a PCG graph, and needs Houdini 21.0+ and UE 5.5+
  [C][14]. Epic's own PCG docs need JavaScript, so I could not read them.

## 3. Delivery to engines

- **Stems:** sweep only stems 1 cm or thicker, with 5 sides and a ring every 5 cm. Bake thinner ones into the
  facade texture. Merge stems per bay, because instanced segments show joints at bends [I].
- **Leaves:** packed instances of 8–16 variants from one 2048² atlas [I]. Houdini Engine makes them instanced
  static meshes with per-instance custom floats [C][13]; Godot reads such data as `INSTANCE_CUSTOM` [C][15].
- **Wind:** stems stuck to the wall stay still. Leaves flutter about their petiole pivot; curtains sway slower.
  Store pivot, phase and tint per instance, so no engine wind system is needed [I].
- **Nanite (from memory, unverified):** Nanite has taken masked materials and world-position offset since UE 5.1,
  and 5.7 added an experimental Nanite Foliage path. On Nanite, use opaque geometric leaves, not alpha cards [I].
  Avoid hierarchical instancers for Nanite meshes [C][13]. UE 5.8 shipped on 2026-06-17 [C][17].
- **Godot 4.7:** a MultiMesh is culled as a whole, so split it per bay and floor [C][15]. Visibility ranges swap
  LODs, and a visibility parent swaps a group for one mesh; fades force transparency and cost more [C][16].
- **LODs:** LOD0 to 15 m, every leaf. LOD1 to 50 m, one clump card per 0.25 m². LOD2 beyond, a vine layer baked
  into the facade atlas at 50 px/m, plus fringe cards on silhouettes [I].
- **Budget per 100 m² of cover (my estimate):** a Boston ivy leaf, 10–20 cm wide [C][21], is about 0.013 m²; an
  assumed leaf area index of 2.5 gives 190 leaves per m². The 19k leaves cost 38k triangles as single cards, 5–8k
  as clusters of 5–8, or 0.57M as 30-triangle leaves (Nanite only); LOD1 is about 400 cards. Stems at 4 m per m²,
  20 % modelled, cost about 16k. A 60 × 15 m Derelict front at 30 % cover (270 m²) needs 13–100k leaf and 43k
  stem triangles at LOD0 [I]. No studio publishes such budgets [38].

## 4. How vines interact with weathering

**Under live cover.**
- Ivy cut the daily range of wall temperature from 7.9 °C to 4.3 °C. Summer peaks fell 17 % and winter minima
  rose 40 %; freezing events fell 26 %, not significantly [M][33].
- On model buildings, ivy cooled the outer wall by 5.7 °C on summer days. It damped daily humidity swings and did
  not raise humidity enough to cause damp [M][34].
- Tokyo's guide says leaf cover shades concrete from thermal cycling and shields sealants from UV [P][29]. Ivy may
  also shed rain; this was suggested, not measured [I][33].
- Ivy quickly enters existing cracks and holes [M][35]. Old Boston ivy at Lincoln College held moisture, made acid
  by pigeon droppings, and the stone behind it eroded [P][36].
- So under cover: less fading, fewer streaks, less soot film, little algae in the shade; leaf litter and damp at
  the foot and on ledges [I].

**After removal.** Holdfasts are hard to remove and can ruin paint; cutting the stem first lets the pads decay
[P][21]. Japanese firms list pad-mark removal as a separate job [P, snippet][37]. The expected look is a paler,
cleaner patch in the vine's outline, dark lines along the old stems, rows of small brown pad dots, and lifted
paint [I]. I found no measurement of this ghost.

**Fields to reuse** [38]:
- Water: `bio_wetness()` gives W (W0 sunny to W3 wet) and the run-off; `PlaneFields` gives the flow `F.F`, the
  channels `F.chan` and the joint wetness `F.jwet`.
- Exposure: `orient`, `shelter`, `under_top`, `corner_prox`; the cause field `F.C` keeps vines in step with others.
- Supports and no-go zones: `cls` (6 = glass, 7 = metal), `steel`, `_openings`, `edges`, `tops`, `floor_rows`,
  `bay_cols`, `joint_h`, `joint_v`, `foot_rows()`.
- Clocks: `clock(age, upkeep)` gives R, the years since the last repaint: 4.7 at Kept, 5.8 Typical, 10.3 Worn
  and 14.6 Derelict. `bio_years()` gives 7.1 years at Derelict.
- Solvers: `arrival_time()` with its `up` multiplier set below `down`. The captured planes' per-pixel position
  and normal lift the 2D stems into 3D.

## 5. Recommended first design

1. **Class.** A new `vine_fields.py` in facade space at 50 px/m (numpy, seeded), plus an HDA that builds the
   stems and leaves. It is not a weathering layer [I].
2. **Inputs.** The weathering config folder; the species mix; `t_clear`, the years since vines were cleared
   (default R, so 14.6 at Derelict); an upkeep threshold; the season; growing or removed N years ago; a seed [I].
3. **Roots.** Planting strips at `foot_rows()`, beside downpipes and in inside corners. Balcony planters for a
   lived-in look. Bird-sown seedlings on ledges where W ≥ W2 at Derelict [I].
4. **Cost map per species** from W, `orient`, `shelter`, the joints and `cls`. Joints and inside corners are
   cheap [P][29]. Sunny south walls are slow for Boston ivy [M][31]. Glass is open to Boston ivy and closed to
   *Hedera* [P][29]. Twiners stay within 0.3 m of `steel`, grilles or downpipes [I].
5. **Envelope.** Run `arrival_time()` from the roots at each species' speed (Boston ivy 0.8–2.4 m/yr up, 4–8 m
   spread). Cover = {T_vine ≤ t_clear}, so cover is nested in time, as growth already is [I].
6. **Stems.** Space colonisation inside the envelope, with attraction points denser where cover is older. Start
   at d_i = 8D, d_k = 2D, D = 5 cm and an upward tropism [M][3][I]. Laterals run sideways, as in Boston ivy
   [P][29]. Past free slab edges, a Luft-style gravity term hangs curtains up to 0.5 m free [P][2][I].
7. **Leaves.** Points along the stems, denser with cover age. Size by species, facing out within ±30°, tinted by
   season, and absent in winter for deciduous species [I].
8. **Coupling.** Write `vine_cover`, `vine_age`, `stem_map` and `pad_scar`. The weathering composite cuts fading,
   streaks and film under cover by cover age; the removed state draws the ghost [I].
9. **Delivery.** Swept thick stems; leaf instances with pivot, phase and tint; LOD0–2 as in §3; chunks per bay
   and floor; LOD2 baked into the facade atlas [I].
10. **Gate.** Rules V1–V8, checked like the weathering gate: no *Hedera* on glass; twiners only near supports;
    cover within §1's rates; every stem joined to a root; curtains within the free length; windows covered only
    by Boston ivy at Derelict; triangle budgets per LOD. Show only builds the gate accepts [I].

## 6. What I could not find

- A per-year rate on Japanese RC walls for any species (the Kyoto numbers sit in a scanned PDF [31]); any rate for
  wisteria; any measurement of the removal ghost; Boston ivy's leaf area index on walls; kudzu on danchi.
- Epic's docs need JavaScript, so the Nanite Foliage claims are from memory. SpeedTree's docs returned 403, the
  Labs tree-tool pages 404. I read only the index of Houdini 22's What's New.
- Searches on SpeedTree vines, UE PCG ivy samples, removal ghosts and ivy leaf area did not run.

## 7. Sources

- **[1]** Luft, An Ivy Generator — https://graphics.uni-konstanz.de/~luft/ivy_generator/ · **[2]** Blender IvyGen source, a port of Luft — https://raw.githubusercontent.com/blender/blender-addons/main/add_curve_ivygen.py
- **[3]** Runions, Lane, Prusinkiewicz 2007 (PDF read) — https://www.algorithmicbotany.org/papers/colonization.egwnp2007.html · **[4]** Měch & Prusinkiewicz 1996 — https://algorithmicbotany.org/papers/enviro.sig96.html
- **[5]** SideFX, L-System SOP — https://www.sidefx.com/docs/houdini/nodes/sop/lsystem.html · **[6]** Hädrich, Benes, Deussen, Pirk 2017 — https://graphics.uni-konstanz.de/publikationen/Haedrich2017InteractiveModelingAuthoring/index.html
- **[7]** SideFX, Find Shortest Path SOP — https://www.sidefx.com/docs/houdini/nodes/sop/findshortestpath.html · **[8]** SideFX tutorial, Project Titan Ivy Tool — https://www.sidefx.com/tutorials/project-titan-ivy-tool/
- **[9]** Labs Tree Tools (snippet) — https://sidefxlabs.artstation.com/projects/PoLJlo · https://sidefx.com/ja/docs/houdini/nodes/sop/labs--tree_trunk_generator.html (404 when fetched)
- **[10]** SideFX, Houdini 22 What's New — https://www.sidefx.com/docs/houdini/news/22/index.html · **[11]** Community HDAs — https://github.com/bwvanlith/Houdini_Ivy_Tool · https://www.fab.com/listings/6d03d225-099d-4f85-ba12-1c68c0471727 (snippet)
- **[12]** Blender Extensions, IvyGen — https://extensions.blender.org/add-ons/ivygen/
- **[13]** SideFX, Houdini Engine for Unreal instancing — https://www.sidefx.com/docs/houdini/unreal/instancing.html · **[14]** SideFX, Houdini Engine PCG plugin — https://www.sidefx.com/docs/houdini/unreal/pcg.html
- **[15]** Godot 4.7, MultiMesh — https://docs.godotengine.org/en/stable/tutorials/performance/using_multimesh.html · **[16]** Godot 4.7, visibility ranges — https://docs.godotengine.org/en/stable/tutorials/3d/visibility_ranges.html
- **[17]** Wikipedia, Unreal Engine 5 — https://en.wikipedia.org/wiki/Unreal_Engine_5
- **[18]** RHS, *P. tricuspidata* 'Veitchii' — https://www.rhs.org.uk/plants/93819/parthenocissus-tricuspidata-veitchii/details · **[19]** RHS, *Hedera helix* — https://www.rhs.org.uk/plants/43091/hedera-helix/details · **[20]** RHS, *Hedera rhombea* — https://www.rhs.org.uk/plants/27505/hedera-rhombea/details
- **[21]** NC State Extension, *P. tricuspidata* — https://plants.ces.ncsu.edu/plants/parthenocissus-tricuspidata/common-name/japanese-ivy · **[22]** NC State Extension, *Wisteria floribunda* — https://plants.ces.ncsu.edu/plants/wisteria-floribunda/
- **[23]** IUCN Global Invasive Species Database, kudzu — https://www.iucngisd.org/gisd/species.php?sc=81 · **[24]** Kotobank, ツタ (Heibonsha, Nipponica, Britannica JP) — https://kotobank.jp/word/%E3%83%84%E3%82%BF-1369919
- **[25]** Oxford Botanic Garden & Herbaria, *Parthenocissus* — https://herbaria.plants.ox.ac.uk/bol/plants400/Profiles/op/Parthenocissus
- **[26]** Steinbrecher et al. 2009, *Parthenocissus* pads — https://www.iam.kit.edu/zm/english/Mitarbeiter_1736.php · **[27]** Melzer et al. 2010, English ivy attachment — https://www.iam.kit.edu/zm/english/Mitarbeiter_1730.php
- **[28]** IUPAC, retraction of He et al. 2010 (snippet) — https://publications.iupac.org/pac/83/6/1341/index.html
- **[29]** Tokyo Metropolitan Government, 壁面緑化 guide, 2006 (PDF read) — https://www.kankyo.metro.tokyo.lg.jp/documents/d/kankyo/heat_island-regulation-files-wallgreengaiyou
- **[30]** Suginami Ward, みどりの実態調査 FY2017, ch. 8 (PDF read) — https://www.city.suginami.tokyo.jp/documents/6171/midorizittai29-08.pdf
- **[31]** Kyoto University repository, Boston ivy on four aspects (snippet) — https://repository.kulib.kyoto-u.ac.jp/dspace/handle/2433/192080
- **[32]** Fassadengruen — https://www.fassadengruen.de/en/drainpipe-greening.html · https://www.fassadengruen.de/en/partial-house-greening.html
- **[33]** Coombes, Viles, Zhang 2018, *Sci Rep* 8:9834 — https://pmc.ncbi.nlm.nih.gov/articles/PMC6026199/ · **[34]** RHS science, Ivy homes (Blanusa et al.) — https://rhs.org.uk/science/articles/ivy-homes
- **[35]** ScienceDaily 2010, Oxford ivy study — https://www.sciencedaily.com/releases/2010/05/100516124817.htm · **[36]** Lincoln College Oxford, The Green Man — https://lincoln.ox.ac.uk/blog/the-green-man/
- **[37]** Curama, ivy removal (snippet) — https://curama.jp/ivy-removal/SER868395693/
- **[38]** Repo: `scripts/weathering/weather_fields.py`, `examples/danchi/weathering/README.md`, `docs/redesign/research/r5-wear-simulation.md`, `.claude/skills/procedural-assets/references/game-output.md`
