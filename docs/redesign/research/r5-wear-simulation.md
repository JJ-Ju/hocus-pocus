# Simulating wear and tear: where it beats rules, and how to do it in Houdini 22

Research round 5. [S] = stated by a cited source; [I] = inference or estimate. Nothing was run
in Houdini; every parm and VEX line is unverified.
The existing skills (`procedural-mesh-damage`, `weather-and-use.md`, `realism.md`, r3/r4
research) already turn causes into **local** masks: N.y, occlusion, curvature, distance to an
edge, code heights. This report covers what changes when the cause is **simulated**.

## 1. The core finding

Rules compute a value from the geometry *at a point*. A simulation also accounts for **what
happened upstream, what happened before, and what other processes did**. It is worth running
only when one of these three matters:

| Property | What rules miss | Evidence |
|---|---|---|
| **Transport** | Dirt picked up on a sill and laid down 1 m lower. Streaks that merge, split around fixings, follow cracks and stop where the water soaks in. Rust carried onto the concrete under a chain | Dorsey 1996: "It is not possible to achieve these effects with simple accessibility" [1][S]. Chen 2005 calls this stain-bleeding [5][S] |
| **History** | Rich-get-richer: rusty areas trap more rust, trails draw walkers, a crack relieves stress so the next one forms further away | γ-tons model rust feedback [5][S]; Helbing trails bundle only through feedback [25][S]; stress relaxation sets crack spacing [7][S] |
| **Interaction** | Moss on the ground cuts the dirt splashed onto the wall; washing removes the dust that would feed a streak | Chen: blending separate simulations cannot reproduce this [5][S] |

Where the field depends only on local shape (AO, crevice dirt, edge wear, upward dust), a
simulation gives what rules already give, at 10–1000× the cost [I]. Miller's accessibility and
Wong's tendency maps are those rules [10][12][S].

## 2. Research literature: what each simulates

| Work | Simulates | Inputs → outputs | Cost (as published) | What it gets right |
|---|---|---|---|---|
| **Dorsey, Pedersen & Hanrahan 1996, Flow and changes in appearance** [1] | Surface water drops under gravity, friction, repulsion and diffusion. Rate equations for absorption, solubility and adhesion | Rain exposure map, roughness and displacement, initial deposits → saturation and deposit textures | Facade (450 polygons): about 3 h in 1996 [S] | Rough surfaces disperse the flow; smooth ones streak. Water collects in cavities and runs along cracks. Drops detach past a critical angle, fall and continue below. Low absorption gives long streaks. Folds are clean on top, dirty below [S] |
| **Dorsey et al. 1999, stone** [2] | Moisture and mineral transport in surface-aligned voxel slabs (32³ each) | → crusts, erosion | 3–24 h [S] | Sub-surface crusts. Overkill for games [I] |
| **Dorsey & Hanrahan 1996, patinas** [3][4] | Layer operators (coat, erode, polish); Kubelka–Munk optics | → layered BRDF | Cheap | Matches our layered materials [I] |
| **Chen et al. 2005, γ-ton tracing** [5] | Aging particles traced like photons: straight, parabolic or flowing. Probabilities (ks, kp, kf) decay at each hit; the rest is the chance to settle. Transport `a ← a + b·k`; 30 iterations | Sources, γ-reflectance → surfel map → texture blend or displacement | 15k tons on 100k surfels: about 1 min per iteration (2005) [S] | Stain-bleeding, interacting processes, geometry change. Half the tons settle after one bounce, so crevices trap them: accessibility for free [S] |
| **Paquette et al. 2001, surface aging by impacts** [6] | Tools hit along linear paths drawn from distributions; the mesh is adaptively refined and compacted | → dented mesh plus a replayable session file | Hundreds of impacts in seconds [S] | Compaction on stairs, frames and trunk corners that noise cannot give [S] |
| **Paquette et al. 2002, paint cracking and peeling** [7] | A grid of stress σ, strengths Sb ≈ 1.5·Sc, relaxation distance Dr and adhesion Sa. Cracks grow perpendicular to stress, then relax it; shear above Sa detaches paint, which curls | Textures → crack polylines, peel geometry | Interactive for about 30 cracks [S] | Crack spacing from stress relief; peels lifting from crack edges [S] |
| **Gobron & Chiba 2001** [13]; **Iben & O'Brien 2006** [14] | Stress-field cracks on a 3D-surface cellular automaton or a triangle mesh | → crack network on any mesh | Gobron: 20 min to hours [7][S] | Cracks on curved surfaces [S] |
| **Mérillou et al. 2001** [15]; **Wojtan et al. 2007** [16] | Corrosion as a random walk with atmospheric classes [15]; level-set corrosion and erosion [16] | → colour, bump, reshaped solid | Interactive-capable [16][S] | Pits that grow and coalesce [I] |
| **Desbenoit et al. 2004** [9] | Lichen by open diffusion-limited aggregation on environment fields | → colonies, rendered from an atlas | Fast [S] | Colony clustering [S] |
| **Hsu & Wong 1995** [11]; **Wong et al. 1997** [10]; **Miller 1994** [12] | Not simulations: dust from inclination and stickiness; a tendency map, then a pattern; accessibility | → masks | Cheap | The ancestors of our rules [S] |
| **Fearing 2000** [21] | Snow: particles shot upward toward the sky, then small avalanches for stability | → depth | Slow [S] | Material slides off unstable ledges; also applies to sand and dust [S] |
| **Beardall et al. 2007** [22]; **Skorkovská et al. 2015** [27] | Spheroidal weathering on voxels; hydraulic erosion on a mesh | → eroded shape | Near interactive [S] | Undercuts that heightfields cannot make [S] |
| **Lu et al. 2007** [17]; **Georghiades et al. 2005** [18]; **Bosch et al. 2011** [19] | Capture, not simulation: measured time-lapse plus context, transferred to new shapes | → textures | — | They call first-principles weathering "either extraordinarily time consuming or impossible" [18][S] |
| **Muñoz-Pandiella et al. 2017** [23] | Screen-space sun exposure | city → exposure | Real time [S] | Fading and drying at city scale [S] |

The surveys [8][20] split the field into physical simulation, empirical rules and capture. For
production the useful middle is *empirical simulation*, physically motivated and tuned for
control, as in Paquette and Chen [5][6][7].

## 3. Production practice

- **Games mostly do not simulate weathering.** I found no GDC or SIGGRAPH talk on simulated
  weathering bakes for game environments; practice is AO and curvature in vertex colour, smart
  masks and grunge [I]. The exception is Substance Painter's **particle brushes**: PopcornFX
  `.pkfx` emitter and receiver presets whose `OnCollide` paints the mesh [28][29][S]. Users
  report direction bugs on meshes without normals or tangents. They find the masks "almost
  never good enough on their own" and multiply them with streaky grunge [30][S].
  **Lesson: simulation supplies where; texture supplies the micro look.**
- **Houdini VFX:**
  - solver-accumulated wet maps [45];
  - Pyro Source Spread for infection and decay [47]; Wargaming's decay-spread talk [48];
  - Project Titan ivy [46] and space colonisation [24];
  - the Wood Worm sample: Copernicus Flow and reaction–diffusion on 3D surfaces, fed back to
    SOPs. Flow needs a DOP licence, not Core [36][37][S].
- **Houdini 22 rules, not simulations:**
  - **Grunge Drips** and **Grunge Leaking Streaks** COPs are image-space noise with only a
    `size_ref` input, so streaks start nowhere in particular [33][34][S]. Mask them with
    simulation output [I].
  - Labs Physical AO has a Dirt Buildup mode [31]; Labs is not installed on the test machine.
  - The Dirt Mask VOP has a bias direction [32].
- **Houdini 22 destruction:**
  - RBD Material Fracture bends and tears metal, with soft-constraint plasticity and RBD Deform
    Pieces [39][40][S].
  - Vellum handles stiff sheet metal poorly [38][S].
  - The RBD Bullet Solver outputs impact points (`OUT_IMPACT_POINTS`) [41][S].

## 4. Hybrid approach (what to build)

1. **Simulate once per kit piece** (or per building, coarsely) at authoring time. Store point
   attributes `wet_time`, `wash`, `dep`, streak curves, `hits`, `traffic`, `touch`, `rust` and
   `adhesion`. Bake with `rasterizesetup`/`rasterizegeo` or into vertex colour [I].
2. **Rules at scale:** instances read the baked fields plus seeded per-instance offsets. Never
   simulate per instance, as `believability.md` already says for Vellum garments [I].
3. **Simulation gives tendency; patterns give look** (Wong's two steps [10]). Simulated fields
   drive the Grunge COPs and the existing clustered chip and micro fields.
4. **Levels of detail:** simulate on a remeshed proxy (2–5 cm per building piece, 0.5–1 cm per
   prop) and `attribtransfer` to the render mesh; at city scale use exposure rules [I].
5. **Determinism:**
   - seed with `set(@id, step, k)` and use fixed iteration counts;
   - run per-drop work in parallel wrangles over frozen inputs and accumulate in a second pass;
   - cache with `filecache`;
   - avoid GPU solvers when authoring, since MPM results differ between CPU, GPU and
     machines [49][S].
6. **Art direction:**
   - paintable source weights;
   - "age" = iteration count [5];
   - strength and adhesion textures, which Paquette uses to steer cracks [7];
   - replayable session files [6].

## 5. Houdini 22 recipes (all unverified)

### (a) Rain runoff on a facade: streak, wash and wet masks

**Nodes:** `remesh` (2 cm) → `normal` → exposure wrangle → `scatter` emitters (density =
exposure) → tracer wrangle → gather wrangle → `attribblur` → rasterize.

1. **Exposure** (Dorsey's rain sources [1]): for each surface point, cast `intersect()` rays
   up-wind along `-raindir`, jittered with `sample_direction_cone(axis, angle, u)`. Then
   `exposure = visible_fraction × max(0, dot(N, -raindir))`.
2. **Tracer** (one point per drop; forces from Dorsey [1], projection from the forum [44]):

```c
// over emitter points; input 1 = surface with N, dirt, absorb
int prim; vector uv, p = @P; float m = 1, s = 0, under = 0;
xyzdist(1, p, prim, uv); int pr = addprim(0, "polyline");
for (int i = 0; i < chi("steps") && m > 0.05; i++) {
  vector n = normalize(primuv(1, "N", prim, uv)), g = {0,-1,0};
  under = n.y < 0 ? under + chf("h") : 0;
  if (under > chf("cling")) {                 // drip edge: fall, land, continue
    vector hp, huv; int hit = intersect(1, p + n*1e-3, g*50, hp, huv);
    if (hit < 0) break; p = hp; prim = hit; uv = huv; under = 0; continue; }
  vector t = g - dot(g, n)*n;
  if (length(t) < 1e-3) t = sample_direction_uniform(rand(set(@id, i, 1)));  // pooling
  t += chf("rough") * (vector(rand(set(@id, i, 2))) - 0.5);                  // Dorsey roughness
  p += normalize(t - dot(t, n)*n) * chf("h");
  xyzdist(1, p, prim, uv); p = primuv(1, "P", prim, uv);
  float D = primuv(1, "dirt", prim, uv), ka = primuv(1, "absorb", prim, uv);
  float pick = chf("solub")*D*chf("h"), dep = chf("adhes")*s*chf("h")/max(m, 0.05);
  s += pick - dep; m -= ka*chf("h");
  int pt = addpoint(0, p); addvertex(0, pr, pt);
  setpointattrib(0, "wash", pt, pick); setpointattrib(0, "dep", pt, dep);
  setpointattrib(0, "flux", pt, m);
}
removepoint(0, @ptnum);
```

   `cling` is the underside run before detaching. Set it to 0 for a drip groove and 5–20 mm
   without one. This is the existing soffit rule, now emergent [I].
3. **Gather** (over the receiver points; input 1 = the trails):
   - `pcfind(1, "P", @P, r, 64)` and sum `wash`, `dep` and `flux`;
   - `dirt_out = dirt × exp(−k·wash) + dep`;
   - `wet_time = Σflux`.
4. **Iterate rain events** for interaction: a `block_begin`/`block_end` feedback loop of 3–10
   passes, updating `dirt` each pass [I]. Chen used 30 iterations [5].

- **Outputs:**
  - trail curves become **streak sources with real paths**, in place of rule-placed sill ends;
  - `dep` → dark streak mask; `wash` → pale washed mask;
  - `wet_time` → frost, rust and biology `damage_mask` weights.
- **Cost** [I]: 20k drops × 300 steps = 6M `xyzdist` calls, about 2–10 s multithreaded on a
  50k-triangle proxy.
- **Failure modes:**
  - drops tunnel through thin parts (keep `h` under half the thinnest feature);
  - drops stall on flat tops (cap the steps);
  - missing or flipped N (the Painter bug [30]);
  - aliasing on a coarse remesh.
- **Check:** median streak 0.3–0.5 m with a 5 % tail of 2–3 m (r4 photos).

### (b) Dirt from accessibility, exposure and γ-ton settling

- **Local:** cosine-sample a hemisphere with `intersect()` rays of max length d (5–30 cm):
  `access = 1 − hits/N` and `skyup = Σ max(d.y, 0)` over misses. Or use `maskbyfeature`
  (`enableao`) [I].
- **Global (γ-ton style)** [5], which picks up crevices that a short AO ray misses:
  - shoot M tons inward from the bounding sphere;
  - on a hit, settle with probability `1 − ks` and lower `ks` by the surface reflectance;
    otherwise bounce diffusely (up to 3 bounces);
  - write settle points and count them per receiver point with `pcfind`.
- **Rule:** `dust = skyup^a × (1 − access)^b × (1 − washed)`. The `washed` term comes from (a).
- **Cost:** 64 rays × 100k points, about 1–3 s [I]. Use simulation only for the global term.

### (c) Impacts: chips and dents from causes

Shoot "tools" along cause distributions, as in Paquette's linear tool paths with statistical
spreads [6]:
- **traffic:** origins along the path curves at bumper heights (feet 0–0.3 m, carts 0.2–1 m,
  forklifts 0.3–0.6 m), directions along the tangent ± a 20° cone;
- **wind grit:** from the prevailing direction, density ∝ exp(−y/0.5 m).

Record the first hit with `intersect()`. Then
`energy = |dot(dir, N_hit)| × w_cause × (1 + k·max(curv, 0))`.
Keep a hit if energy is above the material threshold; edge proximity raises the odds, per the
NIST edge-chipping result in `causes.md`. The hits become the *centres* fed to
`chip_points_clustered.vfl` in place of seeded sampling. Clustering then comes from geometry:
protruding corners intercept more rays [I]. For dents, accumulate radial compaction along −N
per hit. For realistic ricochets, use real RBD and `OUT_IMPACT_POINTS` [41]; the attribute names
are unverified.
- **Cost:** under 1 s for 10k rays [I].
- **Failure:** without occlusion from neighbouring kit pieces, every corner looks exposed, so
  simulate against the assembled context.

### (d) Foot traffic and touch counts

**Nodes:**
- floor `remesh` (0.15 m);
- `findshortestpath` with Output Paths "From each start to each end", Custom Edge Cost and a
  Point Cost Attribute [42];
- count path usage per point (paths group plus an `attribtransfer` or `pcfind` count).

**Helbing loop** (`block_begin` feedback, 5–10 passes) [25]:
- `G ← G + I·use·(1 − G/Gmax) − G/T`;
- point cost = `1 − κ·blur(G, σ)`.

Small κ gives direct shortest paths; large κ bundles them into shared trunks [S]. That replaces
the existing `traffic^2–3` rule with emergent bundling.

For touch, each path ending at an interaction point adds its weight to that point's `touch`. The
80/20 split falls out of network centrality [I].
- **Cost:** 50 origin–destination pairs × 10 passes, a few seconds [I].
- **Failure:** origin–destination weights decide everything. Take them from the generator's
  entrance and core graph, not uniformly.

### (e) Bent rails and dented sheet

- **Rails** (cheap, worth simulating):
  - run the rail centre curve through `vellumconstraints` (hair or string; turn on plasticity:
    Threshold, Rate) and `vellumsolver`;
  - pin the post points and hit it with an animated collider;
  - take frame N, then `sweep`.

  Kinks localise between posts, which is hard to place by rule [I]. Under 1 s.
- **Sheet:**
  - procedural radial dents (existing) for props;
  - for hero pieces, `rbdmaterialfracture` metal + Bullet soft-constraint plasticity +
    `rbddeformpieces` [39][40]: minutes.
  - Avoid Vellum cloth for stiff steel [38].

### (f) Corrosion spread

Run a `solver` SOP on a uniform remesh (or Pyro Source Spread [47]):

```c
int nb[] = neighbours(0, @ptnum); float a = 0;
foreach (int q; nb) a += point(0, "rust", q); a /= max(len(nb), 1);
float p = chf("k") * f@wet_time * (a + f@seed) * (1 - f@rust) * (1 + chf("fb")*f@rust);
if (rand(set(@ptnum, chi("iter"), 7)) < p) f@rust = min(1, f@rust + chf("step"));
```

- **Seeds:** paint breaks (the chips from (c)), junctions and upward-facing members, as in
  the existing painted-steel rules.
- **Feedback:** the `fb` term gives pits that coalesce [5][15].
- **Blister halo:** run a sub-film channel slightly ahead of the visible rust.
- **Rust runs:** use the rust points as *dirty sources* in (a) to get stain-bleeding [5].
- **Texture-space alternative:** the COP reaction–diffusion block (Gray-Scott feed and kill)
  [35] with the H22 Geometry to Adjacency COP for seams [33].
- **Cost:** 100k points × 100 iterations, about 2 s [I].
- **Failure:** `neighbours()` depends on topology, so remesh uniformly or use `pcfind`.

### (g) Peeling paint

Paquette's loop on a 256² UV grid or a surface remesh [7]:
- **fields:**
  - stress σ (thickness and age noise);
  - Sb, lowered by `wet_time`, edges and `rust`;
  - Sc = Sb/1.5;
  - Sa, lowered by moisture.
- **Crack loop** (detail wrangle, sequential):
  1. Start at the max σ/Sb cell.
  2. Step both ends 0.5–1 cell perpendicular to stress until σ < Sc or an existing crack's
     cell ID is reached.
  3. Relax σ within Dr.
  4. Repeat.
- **Peel:** cells where shear > Sa are flakes. Extrude flake polygons 0.2–0.5 mm and lift them
  with a spiral curl of 15–90° (Paquette's profile) [7].

Sequential cracking gives **T-junctions near 90°**, as in real drying cracks [26]. A Voronoi or
Worley network gives 120° Y-junctions, which is a tell [I]. Use the simulation for the alligator
and peel hero pieces; use Worley for crazing.
- **Cost:** seconds per piece [I].
- **Failure:** cracks run parallel to UV seams, so do it per UV island with margins.

### Growth (bonus)

- **Moss and lichen:** open-DLA or space-colonisation walkers seeded by `wet_time × shade`
  from (a) [9][24].
- **Ivy:** the Project Titan approach [46].

## 6. When not to simulate

- **Local-only causes** (AO dirt, curvature wear, upward dust, code-height touch): rules are
  equal and about 100× cheaper [I].
- **Tiling materials and trim sheets:** there is no object context. Use the Grunge COPs.
- **Modular kits:** a per-piece simulation breaks at seams and ignores neighbours. Simulate the
  assembly, or keep rules [I].
- **Budget:** simulated masks need unique UVs or dense vertex colour. Use them for hero and
  unique pieces [I].
- **Control:** a small note like "less streak there" is easier as a rule weight. Keep a
  paintable source map so edits stay local.
- **Wrong inputs** (rain direction, missing context) give confidently wrong results. Validate
  against the r4 photo statistics.
- **Agent ceiling:** if a pass takes over about 30 s per piece or needs a GPU solver, use
  rules [I].

## Sources

1. Dorsey, Pedersen & Hanrahan 1996, Flow and Changes in Appearance — https://graphics.cs.yale.edu/sites/default/files/dorsey_flow.pdf
2. Dorsey et al. 1999, Modeling and Rendering of Weathered Stone — https://graphics.cs.yale.edu/sites/default/files/p225-dorsey.pdf
3. Dorsey & Hanrahan 1996, Metallic Patinas — https://graphics.stanford.edu/papers/patina/
4. Dorsey & Hanrahan 2000, Digital Materials and Virtual Weathering (Sci. Am.) — https://graphics.cs.yale.edu/sites/default/files/virtual_weathering.pdf
5. Chen et al. 2005, Visual Simulation of Weathering by γ-ton Tracing — https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/gamma_ton.pdf
6. Paquette, Poulin & Drettakis 2001, Surface Aging by Impacts — https://profs.etsmtl.ca/epaquette/Research/Papers/Paquette.2001/
7. Paquette, Poulin & Drettakis 2002, The Simulation of Paint Cracking and Peeling — https://graphicsinterface.org/wp-content/uploads/gi2002-8.pdf
8. Mérillou & Ghazanfarpour 2008, survey of aging and weathering — https://hal.archives-ouvertes.fr/hal-00333283
9. Desbenoit, Galin & Akkouche 2004, lichen growth — https://diglib.eg.org/handle/10.2312/CGF.v23i3pp341-350
10. Wong, Ng & Heng 1997, geometry-dependent texture framework — https://dblp1.uni-trier.de/rec/conf/rt/WongNH97.html
11. Hsu & Wong 1995, Simulating Dust Accumulation — https://webarchive.lib.cuhk.edu.hk/20210324161456mp_/http://www.cse.cuhk.edu.hk/~ttwong/papers/dust/dust.html
12. Miller 1994, accessibility shading — https://history.siggraph.org/?p=119714
13. Gobron & Chiba 2001, crack patterns on 3D surface CA — https://infoscience.epfl.ch/record/162173
14. Iben & O'Brien 2006, Generating Surface Crack Patterns — https://diglib.eg.org/handle/10.2312/SCA.SCA06.177-185
15. Mérillou, Dischler & Ghazanfarpour 2001, Corrosion — https://graphicsinterface.org/wp-content/uploads/gi2001-20.pdf
16. Wojtan et al. 2007, Animating Corrosion and Erosion — https://pub.ista.ac.at/~wojtan/projects/acid/acid.html
17. Lu et al. 2007, Context-Aware Textures — https://graphics.cs.yale.edu/sites/default/files/p1-lu.pdf
18. Georghiades et al. 2005, Observing and Transferring Material Histories — https://engineering.yale.edu/download_file/view/0eb076b4-980e-4a63-ab13-fc1ae16a5303/431
19. Bosch et al. 2011, Image-Guided Weathering — https://graphics.cs.yale.edu/sites/default/files/a20-bosch.pdf
20. Dorsey, Rushmeier & Sillion 2008, Digital Modeling of Material Appearance — https://shop.elsevier.com/books/digital-modeling-of-material-appearance/dorsey/978-0-12-221181-2
21. Fearing 2000, Computer Modelling of Fallen Snow — https://history.siggraph.org/?p=118252
22. Beardall et al. 2007, Goblins by Spheroidal Weathering — https://diglib.eg.org/items/3426bc81-df55-4ff3-8088-5d904ef0bc1e
23. Muñoz-Pandiella et al. 2017, real-time solar exposure in cities — https://www.academia.edu/52636713/Real_Time_Solar_Exposure_Simulation_in_Complex_Cities
24. Runions, Lane & Prusinkiewicz 2007, space colonization — https://www.algorithmicbotany.org/papers/colonization.egwnp2007.html
25. Helbing et al., active walker trail formation — https://ar5iv.labs.arxiv.org/html/cond-mat/9805158
26. Hierarchical desiccation crack patterns (T-junctions near 90°) — https://arxiv.org/pdf/2501.07882
27. Skorkovská et al. 2015, hydraulic erosion on a triangular mesh — https://www.cs.purdue.edu/cgvlab/www/resources/papers/Skorkovska-2015-Hydraulic_Erosion_Modeling_on_a_Triangular_Mesh.pdf
28. Adobe, Substance 3D Painter particle editor (PopcornFX emitter/receiver) — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/presets/creating-particles-presets/overview-of-the-particle-editor
29. GDC 2014, Particle Based Brushes, Material Layers — https://gdcvault.com/play/1020743/Particle-Based-Brushes-Material-Layers
30. Polycount, particle-brush masks — https://polycount.com/discussion/comment/2793898
31. SideFX, Labs Physical Ambient Occlusion — https://www.sidefx.com/docs/houdini/nodes/sop/labs--physical_ambient_occlusion-1.1.html
32. SideFX, Dirt Mask VOP — https://www.sidefx.com/docs/houdini/nodes/vop/dirtmask.html
33. SideFX, Houdini 22 Copernicus news — https://www.sidefx.com/docs/houdini/news/22/copernicus.html
34. SideFX, Grunge Leaking Streaks COP — https://www.sidefx.com/docs/houdini/nodes/cop/grunge_leakingstreaks.html
35. SideFX, Copernicus reaction–diffusion — https://www.sidefx.com/docs/houdini/copernicus/reaction_diffusion.html
36. SideFX content library, Wood Worm — https://www.sidefx.com/contentlibrary/wood-worm/
37. SideFX, Copernicus Flow — https://www.sidefx.com/docs/houdini/copernicus/flow.html
38. SideFX, Vellum plasticity — https://www.sidefx.com/docs/houdini/vellum/plasticity.html
39. SideFX, Houdini 22 RBD news — https://www.sidefx.com/docs/houdini/news/22/rbd.html
40. SideFX tutorial, How to Destroy Metal (H22) — https://www.sidefx.com/tutorials/how-to-destroy-metal/
41. SideFX, RBD Bullet Solver SOP — https://www.sidefx.com/docs/houdini/nodes/sop/rbdbulletsolver.html
42. SideFX, Find Shortest Path SOP — https://www.sidefx.com/docs/houdini/nodes/sop/findshortestpath.html
43. SideFX, POP Attract (Surface Points goal) — https://www.sidefx.com/docs/houdini/nodes/dop/popattract.html
44. SideFX forum, particles on surface via xyzdist — https://www.sidefx.com/forum/topic/99524
45. SideFX tutorial, wetmap attribute with VOP and solver — https://sidefx.com/tutorials/how-to-create-a-wetmap-attribute-using-vop-and-solver
46. SideFX tutorial, Project Titan ivy tool — https://sidefx.com/tutorials/project-titan-ivy-tool
47. SideFX, Pyro Source Spread SOP — https://www.sidefx.com/docs/houdini/nodes/sop/pyrosourcespread.html
48. 80.lv, Houdini for game cinematics (Wargaming decay spread) — https://80.lv/articles/houdini-for-game-cinematics
49. SideFX forum, non-deterministic MPM results CPU vs GPU — https://www.sidefx.com/forum/post/436492/
50. SideFX, Labs Dirt Skirt — https://www.sidefx.com/docs/houdini/nodes/sop/labs--dirtskirt.html
