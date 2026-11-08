# A Decayed level past Derelict: evaluation

Date: 2026-11-08. Rulebook 1.7 (89 rules, 40a9963). An evaluation only: nothing here is adopted, and every action
at the end is parked. The user's words [U]: "Looks good, but now that I think about it we could use a more advanced
option, like decayed. With the wear, tear, chipping, rust being the majority of the surfaces. But that might require
more careful authoring with destruction and damage, which we've been putting off. Evaluate the idea but don't commit
to it yet."

## Conventions

- Tags: **[S n]** a source states it (standards and building physics are the rulebook's L); **[M]** measured here,
  from the repo's code or files; **[I]** my inference or arithmetic; **[C]** a craft estimate, to calibrate with
  photos and picks; **[P]** photos or visitor accounts; **[U]** the user's words. **n** is a source in §7.
- Source marks in §7: ✓ read in this session; h read by a helper pass in this session, which reported the link and
  the numbers; s seen only in a search summary.
- rG is `weathering-cracks-edges-damage.md` (round G), rH is `weathering-structural-damage.md` (round H).
- Derelict's numbers are the rulebook's bands at Derelict's own amounts. A standalone copy of the tables in
  `weather_fields.py` gives, for age 45 at upkeep 0.12: 14.6 years since the repaint, E 19.77; rust 0.614, damage
  0.761, cracks 0.491, edges 0.553, peeling 0.57 (4.1 % of the painted wall flaked), growth 0.718 (9.3 years) [M 2].
- Names: rG and rH call their damage ladders' 1.0 row "Derelict, abandoned 20-50 years"; our Derelict preset sits at
  damage 0.76, rG's "vacant or awaiting demolition". Decayed is the ladders' 1.0 row [M 3, 4].

## 0. Summary

1. **Recommendation: a layered control, not a sixth preset.** Add *years vacant* (0-40), a clock that runs on top of
   any preset at upkeep 0, and name Derelict + 25 years "Decayed". Geometric damage states (intact, damaged, ruined)
   follow the clock by default and can be set per building or per bay (§4) [I].
2. **Real decay is mostly surface.** After 40-47 years vacant, Hashima's finishes are about 25 % defective [S 21];
   walls lose 3-10 % of their concrete (Shime 3.7-9.9 % per face at 75 years [S 26]), the worst members 10-30 %
   [I, from 17, 18]; corroded bars show on 16-43 % of members, 72-100 % only beside the seawall [S 16-19]. So the
   user's "majority" [U] should come from paint, rust, dirt and growth, with concrete loss a minority [I].
3. **The standards stop below Decayed.** ISO 4628-5 flaking ends at class 5 (15 %) [S 5] and ISO 4628-3 at Ri5
   (40-50 %); only ASTM D610 grade 0 and ISO 4628-3:2024 have a ">50 %" class [S 11, 12]. Decayed's paint and rust
   bands are craft numbers until they are measured on dated photos.
4. **Key targets** (§1.4), Derelict → Decayed: paint flaked 3-15 → 25-50 %; railing steel rusted ~14 → ≥50 %; wall
   spalled 0.6-3.3 → 3-10 %; exposed bar 0 → 0.06-0.6 m/m²; cracks 0.49-1.18 m/m² with webbing → 0.8-2.0, half in
   storey-long chains; chunks on 10-30 % of slab edges and corners; 5-15 % of rail bays gone; 20-100 % of panes broken.
5. **Extends naturally:** dirt (its E 27.1 anchor is already in the tables), paint, rust, wall growth, edges. **New
   authoring:** rH's crack tracer and graph (the prerequisite), damage geometry, rail and glass swaps, 3D plants,
   debris, deformation (§2).
6. **Engine** (§3): a few shared damage variants keep instancing; damage unique to each bay breaks it and Godot's
   budget. Missing rails and walls change collision and navigation; a breach exposes the card interiors [M 9].
7. **Plan** (§5): rounds D1-D5; a texture-only first look after one round, the full level in 6-9 rounds (about 3-5
   weeks at the pace of rounds G-J) [C]. Main risks: craft bands past the standards, the heavy end's known failures
   (R7c, growth's upper steps, LOD1 decals), and scope creep into interiors and gameplay.

## 1. What Decayed looks like, in numbers

### 1.1 The ladders at their worst classes

| Ladder | Worst class | For Decayed | Source |
|---|---|---|---|
| ISO 4628-3, rust | Ri5 = 40/50 % rusted (tables of 1982-2016); the 2024 edition adds a percentage method whose top band is >50 % | Derelict's R1 target (13.7 %) is about Ri4 (8 %); Decayed is past Ri5 | [S 11] s |
| ASTM D610, rust | grade 1 = 33-50 %, grade 0 >50 % | the only "majority" classes in the standards | [S 12] s |
| ISO 4628-5:2022, flaking | class 5 = 15 % of the area, flakes >30 mm; type b reaches the substrate | P1 puts Derelict at classes 4-5; no class above 15 % | [S 5] |
| ISO 4628-4:2016, cracking | quantity 5 "dense pattern", size 5 >1 mm, depth c through the system | coat cracking is full by Derelict; past it the coat is gone | [S 5] |
| JSCE maintenance, corrosion | incubation (grade I), propagation (II), acceleration early (III-1: corrosion cracks) and late (III-2: wider, longer cracks; bar section and bond loss; spalls), deterioration (IV: safety and serviceability badly impaired) | Derelict is about III-1 to III-2 at noses and corners; Decayed is III-2 over most exposed members, IV locally | [S 13] s; rG J31 |
| BRI bar corrosion | IV: flaking rust bonded to the concrete, section loss ≤20 %; V: thick layered rust, loss >20 % | a bar in a Decayed spall is grade IV-V: scaled, dark, thinned | [S 14] ✓ |
| Hashima member grades | III: corroded bar exposed; IV: cover spalled continuously, about a third of the member; V: bar rotted to a trace, core lost, about half | the measure the real ruins give: the share of members at each grade | [S 16, 18, 23] |
| JBDPA, quick inspection | IV: cracks >2 mm, marked spalling, bars exposed; V: bars buckled, core out | rH's a_D 1.0 | [S 3] |

### 1.2 Documented ruins

- **Hashima** (closed 1974; surveys 39-47 years after closure; marine, 1,871 mm of rain a year) [S 16-20, h]:
  - members with exposed corroded bars (grade III or worse): 16 % in No. 3 (1959), 23 % in No. 65 South (1958),
    40-43 % in No. 65 North and East (1945-49; 15-23 % at IV or worse, 7-9 % at V), and 72-100 % of the corridor
    ceilings, slabs and beams of No. 48 beside the seawall (42 % of its corridor ceilings at V);
  - spalled area, my arithmetic from those counts (IV about 1/3 of a member, V about 1/2, III 5-10 %): about 8-10 %
    of member area in No. 65 North and East, about 30 % on No. 48's corridor ceilings [I];
  - cover and water decide: bars behind 68 mm of cover lost section, behind 95 mm they did not rust; wetness, not
    cover, ranked No. 65 North's members; outward faces were worse in 21 of 26 buildings [S 16];
  - once spalling starts it spreads: 31 % of 531 members changed visibly in 2018-20 (3 % of those at grade I, 52-70 %
    of those at III-V), and 9 of 65 beams in No. 48 went up a grade in 1.5 years [S 17, 18];
  - finishes about 25 % defective on average, peeling and separating on most buildings [S 21]; No. 30 (1916) first
    partly collapsed in 2005, 31 years after closure, more in 2020-24; no other slab was holed by 2016 [S 20, 22, 23];
  - No. 48 had lost many ground-floor steel frames while many upper panes stayed (2016) [S 20]; frames fell out of the
    seaward blocks [P 24]; almost no plants while inhabited, greenery and trees across the island by 2019-25 [P 25].
- **Shime vertical derrick** (1943, unmaintained for 75 years): 3.7-9.9 % of each face spalled, the wet west face
  most; bars exposed only under 25 mm of cover; debris up to 7 m from a 47 m tower [S 26].
- **Matsuo, Midorigaoka** (11 four-storey RC blocks from 1951, vacant from about 1969-72, 900-1,000 m up, deep snow):
  roof-edge concrete fallen through by 2009, roofs worn to the bar and one partly collapsed by 2014; entry banned as the
  shells collapse [S 27; P 28].
- **Pripyat** (blocks of 1970-86, vacant since 1986): a school wing partly collapsed at 19 years [P 32]; trees inside
  some buildings and the stairs called critical at 26 [S 29]; small trees on roofs at 31 [P 31]; at 40 the blocks
  stand, their large windows broken by people, not time [S 30]; forest plots mostly seedlings, up to 8,980 Norway
  maples a hectare [S 33]. **Michigan Central Station** (vacant 1988-2018), the urban vandalism case: every window
  broken or stolen, the basement flooded, parts of the roof lost [S 34].

### 1.3 Stages and years without upkeep

| Stage | What shows | Years | Basis |
|---|---|---|---|
| Coat, stages 1-3 | 1: soiling, fading, chalking; 2: the film cracks, blisters and flakes; 3: the substrate shows (cracks, spalls, efflorescence, rust stains) | 1: 2-5; 2: from 10-15 without a repaint; 3: after about 20 | [S 5] |
| Incubation (JSCE) | nothing: the carbonation front moves toward the bars | outdoor fair-faced (recycled-aggregate) concrete reached 20-29 mm at 25 years (k 4.0-5.8 mm/√y): 20 mm of cover in 12-25 years, 30 mm in 27-56; slower under intact paint | [S 14] ✓; [I] |
| Propagation | nothing yet: the bar corrodes | 1-5 µm a year; the cover cracks at about 100 µm, so decades where dry and much sooner where water stays | [S 15] s; [I] |
| Acceleration (III-1, III-2) | corrosion cracks, rust bleed, delamination, spalls, section loss | spreads within a few years once started | [S 18] |
| Deterioration (IV) | section loss, sag, local collapse | Hashima 31-50 years vacant (marine), Matsuo about 45 (snow), Pripyat's school wing 19 | [S 22, 23; P 28, 32] |
| Railings | the paint breaks at edges and welds; rust at feet, joints and the top rail | Ri4 at Derelict; past Ri5 after decades unpainted; the feet and sockets fail first | [S 1] R3; [I] |
| Glass | broken by people and storms, not by age | any time after vacancy | [S 20, 30] |
| Plants | algae in wet zones; herbs and moss where soil collects; saplings in gutters and corners | 1-3; 5-15; 20-30 | [S 1] M7; [S 35, 36]; [P 31]; [I] |

### 1.4 Targets: Decayed beside Derelict

The Decayed column is for Derelict plus 25 years vacant. Every band in it is a proposal.

| Failure class | Measure (rule) | Derelict now | Decayed | Basis |
|---|---|---|---|---|
| Dirt and marks | A0 tone; A1 T3+ and T5+ | E 19.8: tone 0.22-0.42; T3+ 0.28-0.55; T5+ 0.03-0.10 | the E 27.1 column already in the tables: tone 0.30-0.56; T3+ 0.55-0.86; T5+ 0.12-0.35 | [M 1]; round F's "Neglected" anchor, which the user called 'about right' [U, via 1] |
| Paint gone | P1: share flaked, and the share of that reaching concrete (type b) | 3-15 % (4.1 % nominal); type b 30-60 % | 25-50 %; type b 50-75 %; 60-90 % at tops, soffits and crack margins | past ISO class 5 [S 5]; Hashima [S 21]; [C] |
| Rust on railing steel | R1, dE ≥8 | 13.7 % (band 6.9-27 %), about Ri4 | ≥50 %; 80-100 % on the top and bottom rails and the feet | [S 11, 12]; [C] |
| Rust runs | R8 | below 59 % of rusted joints; median 0.10-0.26 m; 6-17 % of upright length | R8's 1.0 band: ≥85 %; 0.3-0.9 m; 25-60 % | [M 1] |
| Steel section | R10 (new) | none | scale and visible thinning at ≥30 % of post feet; 5-15 % perforated or broken | BRI IV-V [S 14]; [C] |
| Spalled concrete | K5, area share | 0.6-3.3 % | 3-10 % of the wall (K5's 1.0 band); 10-30 % of the worst members (soffits, noses, corridor ceilings) | [S 26]; [I, from 17, 18] |
| Exposed bar | K17 (rH, proposed) | not measured; the texture draws bars in some breaks | 0.06-0.6 m per m² of wall; bars in ≥70 % of spalls ≥20 mm deep; 15-45 % of members | [S 3]; [S 16-19] |
| Cracks | K7; chains (K12-K14, rH) | 0.49-1.18 m/m², 0.15-0.39 at ≥0.3 mm, median 0.16-0.33 mm; webbing allowed | 0.8-2.0 m/m², 0.3-0.9 at ≥0.3 mm; ≥50 % of it in chains of a storey or more, 2-6 of them per 100 m²; widest 3-10 mm | rH §2.5, §6 [S 3] |
| Chunks at corners and noses | K21 (rH) | texture only; `bal_front` has 4 chip variants | 10-30 % of slab-edge and corner length lost ≥30 mm deep; ≥15 chunks ≥0.2 m per 10 bays; nose runs of 0.3-2 m with bars hanging | [S 3, 4]; [I] |
| Railings | X2, X3 (rG, never adopted) | intact, rust only | 15-40 % of bays bent by 50-300 mm; 5-30 % of balusters gone, clustered at rotted feet; 5-15 % of bays gone | [S 4]; [I], no survey found |
| Glass and sashes | X4 | intact | weather only: 20-50 % of panes, more on the weather side; with vandalism: 70-100 % on floors 1-2 and 30-60 % above; 5-20 % of sashes gone | [S 20, 30, 34]; [I]: aluminium sashes do not rust out like Hashima's steel frames |
| Balcony partitions | X6 | intact | 30-70 % broken, frames left | [S 4]; [I] |
| Growth on walls | M7, by wetness class | 9.3 years: W3 ≥50 %, W2 ≥30 %, W1 ≥3 % | the control's top (22 years): W2-W3 at their 0.90-0.95 ceilings, W1 and W0 toward 0.60 and 0.30 | [M 1, 2] |
| Plants in 3D | V9-V12 (new) | none | flat roof 30-70 % herbs and moss, saplings in corners and gutters; plants on 20-50 % of balcony slabs, saplings on 2-10 %; the foot strip along 50-90 % of the base; on wall faces only in cracks and spalls, ≤2 % | tops colonised once soil collects, faces only at crevices [S 35]; roof plants in gutters and silted corners, fewer higher up [S 36]; most species low on walls [S 37]; [S 29]; [P 31]; [C] |
| Debris | X7 | none | spall debris at the foot within 0.15 × the wall's height; soil, litter and fallen rail or partition parts on the slabs | [S 26]; [S 4] |
| Deformation | X8 | none | a story option: at most one local collapse per building (the top roof slab, or a corridor or balcony slab end) | [S 22, 23]; [P 28]; wall-type blocks rarely suffer in earthquakes [S 3] |

### 1.5 What "majority" can mean

Paint, rust and dirt can be the majority. T3+ at the E 27.1 anchor already covers 0.55-0.86 of the wall; with 25-50 %
of the paint flaked and growth near its ceilings, 70-95 % of the painted wall shows decay, and over half of the
railing steel is rust [I]. Concrete cannot, if it is to read as decay: no surveyed ruin passes about 10 % spalled per
face on average, and the 30 % above is one class of member beside a seawall [S 16-18, 26]. More reads as war or
demolition and breaks the user's rule that damage fits its story and radiates from a cause [U, via 8]. Rule Y3 (§5)
holds both: decay on ≥60 % of the painted wall, and spalls ≤10 %.

## 2. What extends and what needs new authoring

Age alone runs out of road: on today's tables, age 60 at upkeep 0 gives damage 1.0, rust 0.975 (R1 37 %), cracks 0.78,
edges 0.91 and 6 % flaked (15 % after 30 years unpainted), and E clamps at the last anchor, 27.1 [M 2]. The 1.0 anchors
are the standards' worst classes, so Decayed needs new top bands for paint and rust [C]; spalls stay in K5's 1.0 band.

| Part | Extends or new | What pros do | What it costs us |
|---|---|---|---|
| Dirt, streaks, stains, ground band | extends: the E 27.1 anchor is in A0, A1 and the AUTO tables | masks and material layers | one anchor; one pipeline (about 18 min and 1 GB a build) [M] |
| Paint failure | extends past ISO class 5 (PEEL_AREA stops at 15 %) | masks; trims at tops; decals for big sheets | small: peel is already left out of D_local [M 1] |
| Rust on steel | extends to 1.0 and past it | baked masks, run decals | medium: R7c's rims still fail at rust 1.0, and railing members are 1-2 px wide at 50 px/m [M 1], so majority rust needs member-scale texturing [I] |
| Growth on walls | extends to the control's top (22 years) | masks | medium: the upper sweep steps were held back in round J on G5, M3 and E1 [M] |
| Cracks and their spalls (texture) | **new**: rH's tracer and crack graph. Today's top end is webbing, which the user rejected | crack and spall-halo decals from one atlas | 1-2 rounds; the prototype ran 0.8-1.2 s per front [S 3] |
| Spalls, chunks, exposed bar (geometry) | **new** | Fallout 4: damage pieces over intact prefabs, walls and floors with holes [S 38], secondary. Frostbite: remove the piece, add detail meshes and a mask that projects broken detail [S 39]. THE FINALS: pre-fractured in Houdini, with collision and occluders generated [S 41] | 3-6 variants per piece type, cut from the graph: Boolean cutters, cut-face material, swept bars, the skill's validators [S 8] |
| Railings | **new**: bend or lattice before the sweep; missing balusters and bays | variants plus debris pieces | small per variant, plus a collision decision (§3) |
| Glass, sashes, partitions | **new**: part swaps (intact, cracked wired glass, broken, empty frame) | swaps | small; empty frames expose the card interiors [M 9] |
| Plants in 3D | **new**: scatter on soil traps; vines (the parked generator [S 6]) | Naughty Dog: hand placement and painted blends [S 42]. Assassin's Creed Shadows: a Houdini ivy tool run in the editor [S 51]. UE: PCG (production-ready in 5.7), Nanite Foliage (experimental) [S 45, 48] | 1-2 rounds; instances split per bay and floor, since a Godot MultiMesh culls as one [S 49] |
| Debris | **new**: piles from the graph's spall volumes, plus litter | level-designed debris piles, culled by priority (Battlefield 6) [S 40] | small; adds nav obstacles |
| Deformation, collapse | **new**, a story option | static ruin meshes, or pre-fractured and cached (Chaos cache, VAT) [S 3] | 1-2 rounds; room shells behind each breach |

## 3. Engine and gameplay consequences

- **Collision.** The export holds six convex hulls for the whole building [M 9]. Decayed needs collision per bay
  where the outline changes: noses with gaps, no rail where a bay is gone, simple shapes on large debris and none on
  small. UE: simple collision is primitives and convex hulls, and a body that uses complex collision as simple cannot
  simulate [S 47]. Godot: trimesh shapes are the slowest and static only; `-colonly` and `-convcolonly` make
  collision on import [S 49].
- **Falls.** A missing rail is either a hazard or an invisible wall, and that is a design choice. The Last of Us Part
  II leaves edges lethal and offers Ledge Guard as an accessibility option [S 43]. Proposal: export a `rail_blocker`
  per broken bay, off by default, for the game to switch [C].
- **Navigation.** Static ruins bake once. UE: Static by default; Dynamic rebuilds tiles and is costly; NavArea_Null
  removes navmesh, NavArea_Obstacle raises the cost, Nav Link Proxies make one-way drops [S 47]. Godot bakes in the
  editor or on a thread, best from physics shapes; NavigationObstacle3D changes the mesh only when baked;
  NavigationLink3D spans gaps [S 49]. A missing wall opens paths into rooms that are cards today [M 9].
- **Per-instance masks.** Variants that share a mesh still need their own dirt and moss. UE 5.5's Texture Color
  painting stores per-instance paint as virtual textures on Nanite meshes, which cannot take per-instance vertex paint;
  ISMs drop per-instance vertex colours [S 46]. Godot's MultiMesh carries `INSTANCE_CUSTOM` per instance [S 49].
- **Instancing and LOD.** A few shared damage variants instance like any kit piece; damage unique to each bay does
  not. Nanite stores about 14.4 bytes per input triangle [S 44]: twenty shared 10k-triangle variants cost about 3 MB,
  and a unique 10-20k-triangle mesh for each of a 60 m block's ~100 bays (two sides, five floors) costs 14-29 MB per
  building that has its own [I]. Nanite Assemblies build one mesh from instanced parts (one level of nesting, each
  assembly keeping its own copy of the parts) [S 45]: a way to make a ruined bay from shared chunks, bars and rubble
  [I]. Nanite tessellation and displacement, which could crumble edges from a height map, are still experimental [S 44].
  Godot has no Nanite, and its LOD0 must stay inside the 700k building budget (486k measured at age 60, upkeep 0.1)
  [M 9], so small damage goes into normal maps there. Damage branches off after the LOD split, but silhouette damage
  (missing bays, a lost corner, roof saplings) must reach LOD1, LOD2 and the HLOD [S 8, 48].
- **Texture memory.** A unique 4K set (BC7 colour, BC5 normal, BC1 mask, with mips) is about 53 MiB [S 50; I]; Epic
  cut one from 49.7 to 27.8 MB by trading a unique normal for a shared tiling one [S 44]. So variants share tiling
  broken-concrete, bar and rust materials and the facade masks (28-31 MB per building, budget 40 MB) [M 10].
- **Decals.** LOD1 already holds 99,946 of its 100k triangles at age 60 and upkeep 0.1, because its decals grow with
  weathering [M 9]; Decayed needs a cap, such as raising the README's 1.5 m² threshold. UE mesh decals wrap edges with
  fewer draw calls than big projected ones, but write no depth and cast no shadows [S 46]. Godot allows 512 clustered
  elements in view on Forward+, 8 decals per mesh on Mobile, and none on Compatibility [S 49; 7].

## 4. A preset or a layered control

**Recommendation: the layered control.** *Years vacant* (0-40) runs on top of any preset at upkeep 0 and moves every
age-driven layer on: the coat's years since repaint, rust, cracks, damage and growth. "Decayed" is Derelict + 25
years, a named entry. The geometric damage state follows the clock by default, after rG's abandoned-years rule
(a_D ≈ 0.6 + 0.01 per year vacant, capped at 1 [S 4]) started from the preset's own amount [I], and can be set per
building or per bay.

1. **The costs differ.** Surface decay is texture; geometric decay changes collision, navigation, instancing, LOD and
   interiors (§3). A preset would make every Decayed building pay both.
2. **Level design needs the choice per building and per bay**: one ruined block in an estate of Derelict ones, one
   lost corner. Games ship damage as swappable variants and pieces (§2) [S 38-41].
3. **The rulebook already works this way.** Presets drive the clocks, controls override amounts, the K bands go by
   damage amount, not preset [M 1]. The five presets, tuned on four rounds of picks, stay untouched; a sixth rung
   would reopen A4, A6, L5 and I5.
4. **A vacancy clock is physical.** An empty building's coat keeps ageing and nothing resets it [S 5]; Typical + 10
   years (emptied, glass broken, paint sound) is as valid a story as Derelict + 25 [I].
5. **Story fit stays checkable.** Y2 refuses geometric damage without its surface cause; event damage (fire,
   earthquake, impact) is a story tag allowed on any preset [I; U, via 8].
6. **Against it:** more combinations to gate, and geometry that changes with a slider means rebuilt variants; both
   cost less than a preset that cannot vary [I].

## 5. Staged plan (proposal)

| Round | Delivers | Rules added or changed | Needs | Effort [C] |
|---|---|---|---|---|
| D1 Surface decay | the vacancy control, texture only, damage held at Derelict's 0.76; a review page with Derelict and Decayed at player views | Y1 (the age layers move together with vacancy); Y3 (decay on ≥60 % of the painted wall, spalls ≤10 %); Decayed bands for A0/A1 (E 27.1), P1, R1, R8, M7; P4 (coat islands, 0.1-0.5 m sheets at tops and soffits); R10; R7c restated around paint islands | nothing new | 1 round |
| D2 Cracks that shed surface | rH's tracer, crack graph and crack-coupled spalls; damage 1.0 without webbing | K12-K19; rH's changes to K5, K7, K8, K10 | rH's scratchpad prototype | 1-2 rounds |
| D3 Damage geometry | Houdini variants from the graph (`bal_front` nose runs with hanging bars and corner chunks, `cor_front`, end-wall chunks); railings bent and missing; glass and partition swaps; collision per bay | K17, K20, K21; X1-X6 (rG); Y2; a damaged variant ≤1.5× intact triangles; a balcony bay ≤5,250 | D2; the first engine round trip | 2 rounds |
| D4 Plants and debris | scatter on soil traps, debris from spall volumes; navigation, LOD and HLOD in both engines | V9 (plants only on soil traps), V10 (cover per surface class), V11 (size by years: saplings from 15-20, trees over 2 m only from 25), V12 (instance budgets); X7; `asset_check` items for collision, navigation and LOD | D3 | 1-2 rounds |
| D5 Story option | sagging slab ends; one collapsed roof or corridor bay; room shells behind breaches | X8; rH's settlement chains | D3 and the user's go-ahead | 1-2 rounds |

**Prerequisites.** rH's crack tracer and graph (rH §5.5, steps 1-4; parked since round H; D2 is that work). The first
engine round trip, pro-asset-pipeline actions 3, 6b and 10 (the golden crop in Godot 4.7, both builds,
`handoff_test`): geometry damage has to be judged in the engine, and nothing has yet been tested there [S 7]. A dated
photo set of decayed RC blocks (Hashima, Matsuo, Pripyat), measured like `rR-reference-photos.md`, to turn the C bands
into P bands before they are adopted.

**Effort** [C]. D1 gives a first look in one round; D1-D5 take 6-9 rounds. Rounds G-J took eight days for four rounds
(commits e5decd9 to 40a9963) [M]; geometry and engine rounds have no precedent here, so at 1.5-2× that pace about 3-5
weeks. Reused: rH's prototype, the mesh-damage scripts and validators, `bal_front`'s four damage variants [S 3, 8].

**Risks**
1. Past the standards the bands are craft numbers (ISO stops at 15 % flaking and Ri5, ASTM at ">50 %"); "majority"
   put into concrete reads as war damage, so Y3 caps spalls at 10 %.
2. The heavy end's known failures: R7c at rust 1.0, growth's upper steps, LOD1 decals. Derelict's A1 T6+ overflow was
   solved by leaving peel out of D_local; Decayed adds exposed concrete and dark growth again. Fix by evidence, never
   by loosening a rule (round G's lesson).
3. Damage leaves the shared kit: the 0.15 m seam margin keeps cuts off bay ends, so cuts across bays are made on the
   assembled facade as unique meshes [S 3, 8]; and the builds drift (UE takes dense damage through Nanite, Godot
   needs it in normal maps).
4. Scope creep: breaches need interiors, missing rails a gameplay decision, a collapse a simulation and a cache.
5. The first export may fail for reasons unrelated to decay: units, normal Y, vertex-colour sRGB [S 7].

## 6. Not found

A survey of coat loss on abandoned *painted* RC housing (Hashima's 25 % covers finishes whose types I did not read);
glass loss against years vacant; railing and balcony failure rates; plant cover against years on roofs and slabs; a
condition survey of Pripyat or an engineering survey of Matsuo; the JSCE stage text and the MLIT bridge grades for
exposed bars (the PDFs would not parse, so the stages come from search summaries); published budgets for ruined or
overgrown game scenes, and damage-variant counts beyond Fallout 4's fan transcript.

## 7. Sources

1. ✓ `scripts/weathering/weather_rules.json` 1.7, rendered as `.claude/skills/procedural-materials/references/weathering-rules.md` (bands; the round-F A1 record; the R7 record)
2. ✓ `scripts/weathering/weather_fields.py` (`AUTO`, `AUTO_A`, `clock`, `PEEL_*`, `BIO_STEPS`); §0, §1.4 and §2 use a standalone copy of these tables
3. ✓ `docs/redesign/research/weathering-structural-damage.md` (rH: ladders, K12-K21, the tracer, damage states)
4. ✓ `docs/redesign/research/weathering-cracks-edges-damage.md` (rG: §4.4-4.7, X1-X8, S12, amount and age)
5. ✓ `docs/redesign/research/coatings-concrete-corrosion.md` (ISO 4628-2/-4/-5 read there; NILIM coat stages)
6. ✓ `docs/redesign/research/vine-growth-generators.md`
7. ✓ `docs/redesign/research/pro-asset-pipeline.md` (parked engine actions; Godot renderer matrix; handoff traps)
8. ✓ `.claude/skills/procedural-mesh-damage/SKILL.md` (principles 3, 5 and 6; LOD traps)
9. ✓ `examples/danchi/README.md` (budgets, measured triangles, decals, UCX hulls, card interiors)
10. ✓ `.claude/skills/large-scale-texturing/SKILL.md` and `references/texturing-at-scale.md` (mask sizes, 40 MB budget)
11. s ISO 4628-3, 1982 table: https://cdn.standards.iteh.ai/samples/10580/b5d367ccc80c4507982278c4289c1b13/ISO-4628-3-1982.pdf · 2024 edition: https://standards.iteh.ai/catalog/standards/iso/23b73de1-ea20-4c20-abb9-11ebfde8b7ac/iso-4628-3-2024
12. s ASTM D610 grades (rG W16): https://www.micomlab.com/blog/corrosion-testing/astm-d610-test-now-offered-at-micom-laboratories/
13. s JSCE maintenance stages and grades, via search summaries of an MLIT road-asset document and a Kyoto University lecture: https://www.mlit.go.jp/road/ir/sisan/9pdf/22.pdf · https://www.nims.go.jp/SIP-infrastructure/pdf/11_kyoto.pdf
14. ✓ Nakada, Matsuzawa, Kage, BRI annual report R6, 4-2 (bar grades I-V; a 1975 five-storey block; carbonation at 25 years): https://www.kenken.go.jp/japanese/contents/publications/annual/reiwa/r6-pdf/part1/4-2.pdf
15. s Sánchez-Montero et al. 2024, *Materials* 17(1):101 (403 when fetched): https://www.mdpi.com/1996-1944/17/1/101
16. h Kusunoki, Imamoto, Noguchi, Shimozawa 2013, JCI Proc. 35(2): https://www.data.jci-net.or.jp/data_pdf/35/035-02-1127.pdf · Fukuyama et al. 2013 (cover): https://www.data.jci-net.or.jp/data_pdf/35/035-01-1311.pdf · Shinohara et al. 2018: https://data.jci-net.or.jp/data_pdf/40/040-01-1261.pdf
17. h Toyoshima, Akisada, Morio, Kishimoto 2019, JCI Proc. 41(2), No. 48: https://www.data.jci-net.or.jp/data_pdf/41/041-02-2228.pdf
18. h Toyoshima, Kamikashiwa, Horimoto, Kishimoto 2021, JCI Proc. 43, No. 65: https://www.data.jci-net.or.jp/data_pdf/43/043-01-2142.pdf
19. h Nakahara, Kabayama 2019 (No. 65 South): https://www.data.jci-net.or.jp/data_pdf/41/041-01-2165.pdf · Sonoyama, Kabayama 2018 (No. 3): https://data.jci-net.or.jp/data_pdf/40/040-01-2170.pdf
20. h Morio, Kishimoto 2017, JCI Proc. 39(2) (slabs, windows): https://www.data.jci-net.or.jp/data_pdf/39/039-02-2206.pdf
21. ✓ Hayano, Yamamoto, Imamoto, Noguchi 2016, AIJ J. Technol. Des. 22(52) (abstract): https://doi.org/10.3130/aijt.22.867
22. h Goto, Goto 2020, JSCE Western branch (No. 30 in 2005): https://committees.jsce.or.jp/seibu_s01/system/files/10th_30.pdf
23. Noguchi, JCI-ACI 2025 (rG J24, ✓ in round G): https://www.jci-net.or.jp/~7th_jci-aci_joint_seminar/pdf/JCI-ACI2025-15_Noguchi.pdf
24. h Fukuyama 2023, slides with a photo series 2011-22: https://r-dmuch.jp/wp/wp-content/uploads/2023/12/23.12.02Disaster_Mitigation_Technology_for_Historic_Cultural_Cities.pdf
25. h Hashima visitor accounts, 2019 and 2025: https://trafficnews.jp/post/84834/3 · https://staradvertiser.com/2025/03/27/news/the-abandoned-island/
26. Su, Imamoto, Noguchi et al., DBMC 2020, Shime (rG J25, ✓ in round G): https://www.scipedia.com/wd/images/3/3b/Draft_Content_437235182p986.pdf
27. h Japan Tourism Agency, 松尾鉱山, 2022: https://www.mlit.go.jp/tagengo-db/common/001554119.pdf
28. h Matsuo visitor accounts, 2009 and 2014: https://www.michaeljohngrist.com/the-mist-wreathed-apartments-of-matsuo-mine/ · https://abandonedkansai.com/2014/05/27/matsuo-mine-apartment-buildings/
29. h Interfax-Ukraine, 2012-09-06: https://en.interfax.com.ua/news/general/116615.html
30. h Ukrinform, 2026-04-22: https://www.ukrinform.net/amp/rubric-emergencies/4115464-chornobyl-40-years-later-a-look-inside-the-exclusion-zone-today.html
31. h AP photo essay, 2017: https://www.durangoherald.com/?p=253351 · G. Ludwig, Pripyat photos, 2005: https://www.gerdludwig.com/long-shadow-pripyat-photos
32. h Abandoned Kansai, Pripyat school, 2011: https://abandonedkansai.com/2011/02/03/zone-of-alienation-pripyat-middle-school-no-3
33. h Laćan, McBride, De Witt 2015, Urban For. Urban Green. 14(4) (abstract): https://agris.fao.org/search/en/records/65de2e5c63b8185d9ca77757
34. h ICC, Michigan Central, 2024: https://iccsafe.org/?p=568912
35. h Duchoslav 2002, stony walls in East Bohemia, *Preslia* 74: https://preslia.cz/article/pdf?id=413
36. h McKinney, Sisco 2018, roof spontaneous vegetation, *Urban Naturalist*: https://www.eaglehill.us/URNAonline/articles/URNA-sp1/15-McKinney.shtml
37. h Chen et al. 2020, walls and urban biodiversity, *Sci. Rep.* 10:9905: https://pmc.ncbi.nlm.nih.gov/articles/PMC7303168/
38. h Burgess, Purkeypile, Fallout 4 modular level design, GDC 2016, via a fan transcript (secondary): https://dtf.ru/gamedev/3788796-modulnyi-dizain-fallout-4
39. h Kihl, Destruction masking in Frostbite 2, SIGGRAPH 2010: https://www.advances.realtimerendering.com/s2010/Kihl-Destruction%20in%20Frostbite(SIGGRAPH%202010%20Advanced%20RealTime%20Rendering%20Course).pdf
40. h EA, How Battlefield 6 redefined destruction, 2025: https://www.ea.com/en/news/how-battlefield-6-redefined-destruction
41. h Björkerud (Embark), procedural buildings of THE FINALS, SideFX 2026: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
42. h 80.lv, The Last of Us Part II, 2020: https://80.lv/articles/how-naughty-dog-created-the-immersive-world-of-the-last-of-us-part-ii · Uncharted: The Lost Legacy, 2017: https://80.lv/articles/building-environments-for-uncharted-the-lost-legacy/
43. h Naughty Dog, The Last of Us Part II accessibility, 2020: https://naughtydog.com/blog/THE_LAST_OF_US_PART_II_ACCESSIBILITY_FEATURES_DETAILED
44. h Epic, Nanite (5.8; the 5.0 page gives 14.4 bytes per triangle and the texture example): https://dev.epicgames.com/documentation/unreal-engine/nanite-virtualized-geometry-in-unreal-engine · https://dev.epicgames.com/documentation/unreal-engine/working-with-naniteenabled-content
45. ✓ Epic, Nanite Assemblies: https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-assemblies · h Nanite Foliage: https://dev.epicgames.com/documentation/unreal-engine/nanite-foliage
46. h Epic, mesh decals: https://dev.epicgames.com/documentation/en-us/unreal-engine/using-mesh-decals-in-unreal-engine · mesh texture colour painting (5.5): https://dev.epicgames.com/documentation/unreal-engine/getting-started-with-mesh-texture-color-painting-in-unreal-engine · ISM vertex colours: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MeshInstancingSettings
47. h Epic, collision and navigation: https://dev.epicgames.com/documentation/unreal-engine/simple-versus-complex-collision-in-unreal-engine · https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/NavigationSystem/ERuntimeGenerationType · https://dev.epicgames.com/documentation/unreal-engine/overview-of-how-to-modify-the-navigation-mesh-in-unreal-engine
48. h Epic, HLOD, level instancing, UE 5.7 release notes: https://dev.epicgames.com/documentation/unreal-engine/world-partition---hierarchical-level-of-detail-in-unreal-engine · https://dev.epicgames.com/documentation/en-us/unreal-engine/level-instancing-in-unreal-engine · https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-7-release-notes?application_version=5.7
49. h Godot 4.7: https://docs.godotengine.org/en/stable/tutorials/3d/using_decals.html · …/tutorials/performance/using_multimesh.html · …/tutorials/navigation/navigation_using_navigationmeshes.html · …/classes/class_navigationobstacle3d.html · …/tutorials/physics/collision_shapes_3d.html · …/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html
50. h Microsoft, block compression in Direct3D 11: https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11
51. h 80.lv, a Houdini ivy-scattering tool (Assassin's Creed Shadows), 2026: https://80.lv/articles/check-out-this-ivy-scattering-tool-created-with-houdini

## 8. Actions

| # | Action | Status |
|---|---|---|
| 1 | No sixth preset. Add a *years vacant* control (0-40) over any preset, with "Decayed" = Derelict + 25 years as a named entry, and geometry states that follow it but can be set per building and per bay (§4) | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 2 | Keep concrete loss a minority (≤10 % of a wall) and carry "majority" in paint, rust, dirt and growth; rule Y3 (§1.5) | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 3 | D1: the surface-only Decayed (Y1, Y3; Decayed bands for A0/A1, P1, R1, R8, M7; P4, R10; R7c restated), shown beside Derelict at player views before any geometry | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 4 | D2: rH's crack tracer, graph and crack-coupled spalls (K12-K19, rH's K5/K7/K8/K10 changes) as the prerequisite for damage 1.0 | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 5 | Run the first engine round trip (pro-asset-pipeline actions 3, 6b, 10) before any geometry damage | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 6 | D3: damage variants from the graph (K17, K20, K21; X1-X6; Y2), at most 1.5× intact triangles, collision per bay | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 7 | Export a switchable `rail_blocker` per broken bay and bake static navigation with ledge links (§3) | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 8 | Share tiling broken-concrete, bar and rust materials across variants, with no unique texture sets, and cap LOD1 decals (§3) | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 9 | D4: plants on soil traps and debris from spall volumes (V9-V12, X7), with navigation, LOD and HLOD in both engines | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 10 | D5: deformation and breached bays with room shells (X8), as a story option only | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
| 11 | Measure a dated photo set of decayed RC blocks (Hashima, Matsuo, Pripyat) to turn the C bands into P bands before adopting them | parked (the user asked for an evaluation, not a commitment; revisit when the user approves a Decayed level) |
