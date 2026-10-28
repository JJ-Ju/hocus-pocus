# Simulating wear: where it beats rules, and how

Distilled from research for review 32 (full report: `docs/redesign/research/r5-wear-simulation.md`).
**None of the recipes below has been run in Houdini yet**; treat node names, parms and VEX as
starting points to verify.

## When to simulate

A rule computes a value from the geometry at one point: occlusion, curvature, distance to an
edge, a code height. A simulation also accounts for what happened upstream, what happened before
and what other processes did. Simulate only when one of these matters:

| Property | What rules miss | Evidence |
|---|---|---|
| **Transport** | dirt picked up on a sill and laid down 1 m lower; streaks that merge, split around fixings, follow cracks and stop where the water soaks in; rust carried onto the concrete below | Dorsey et al. 1996: "It is not possible to achieve these effects with simple accessibility." Chen et al. 2005 call it stain-bleeding |
| **History** | rich-get-richer: rusty areas trap more rust, trails draw walkers, a crack relieves stress so the next forms further away | γ-ton feedback; Helbing's trail bundling; stress relaxation sets crack spacing |
| **Interaction** | moss on the ground cuts the dirt splashed onto the wall; washing removes the dust that would feed a streak | Chen: blending separate simulations cannot reproduce this |

Where the field depends only on local shape (AO dirt, curvature edge wear, upward dust,
code-height touch), a simulation gives what the rules already give at 10–1000× the cost. Use the
rules.

## How production uses it

- **Games mostly do not simulate weathering.** They use AO and curvature masks and grunge. The
  exception is Substance Painter's particle brushes, whose users find the masks "almost never good
  enough on their own" and multiply them with grunge. **Simulation supplies where; texture
  supplies the micro look.**
- **Houdini 22's Grunge Drips and Leaking Streaks COPs** are image-space noise with no source
  input, so on their own the streaks start nowhere in particular. Mask them with simulation output
  or with the streak sources.
- **Also in Houdini 22:**
  - VFX wet maps come from solver accumulation;
  - RBD Material Fracture bends and tears metal with soft-constraint plasticity;
  - the RBD Bullet Solver outputs impact points;
  - Vellum handles stiff sheet metal poorly.

## The hybrid to build

1. **Simulate once per kit piece, or coarsely per assembled building, at authoring time.** Store
   point attributes such as `wet_time`, `wash`, `dep`, streak curves, `hits`, `traffic`,
   `touch`, `rust` and `adhesion`. Bake them to UV (`rasterizesetup`/`rasterizegeo`) or to
   vertex colour.
2. **Apply rules at scale.** Instances read the baked fields plus seeded per-instance offsets.
   Never simulate per instance.
3. **Simulation gives the tendency; patterns give the look.** The simulated fields drive the
   cluster mask, the chip points, the streak and micro fields, and the Grunge COPs.
4. **Level of detail.** Simulate on a remeshed proxy (2–5 cm for building pieces, 0.5–1 cm for
   props) and `attribtransfer` the results to the render mesh. At city scale, use exposure rules.
5. **Determinism.** Seed with `set(@id, step, k)`, use fixed iteration counts, cache with
   `filecache`, and avoid GPU solvers while authoring, since their results differ between
   machines.
6. **Art direction.** Paintable source weights; "age" as the iteration count; strength and
   adhesion maps.

## Recipes (unverified)

**(a) Rain run-off: real streak paths, washed and deposit masks.** This is the most valuable
recipe.
- **Graph:** `remesh` (2 cm) → `normal` → an exposure wrangle → `scatter` emitters (density from
  exposure) → a tracer wrangle → a gather wrangle → `attribblur` → rasterise.
- **Exposure:** jittered `intersect()` rays up-wind along −raindir;
  exposure = visible fraction × max(0, N·(−raindir)).
- **Tracer:** one drop per emitter point.
  - Each step, project gravity onto the surface tangent, add roughness jitter, move one step,
    and snap back onto the surface with `xyzdist`/`primuv`.
  - Pick up dirt (solubility × dirt), deposit it (adhesion × load / mass), and lose mass to
    absorption.
  - On an underside, count the distance run. Past a **cling** distance (0 with a drip groove,
    5–20 mm without), the drop detaches, falls with `intersect()` and continues below. The
    drip-groove rule then emerges instead of being placed.
  - Write a polyline per drop with `wash`, `dep` and `flux` on its points.
- **Gather:** over the receiver points, `pcfind` the trail points and sum them.
  dirt_out = dirt × exp(−k·wash) + dep, and wet_time = Σ flux.
- **Events:** 3–10 passes in a feedback loop, updating the dirt each time.
- **Outputs:** trail curves become streak sources with real paths. `dep` → the dark streak mask,
  `wash` → the pale washed mask, and `wet_time` feeds the frost, rust and biology weights.
- **Cost:** 20k drops × 300 steps, about 2–10 s multithreaded on a 50k-triangle proxy.
- **Failure modes:** drops tunnelling through thin parts (keep the step under half the thinnest
  feature); stalling on flat tops (cap the steps); flipped normals.
- **Check:** median streak 0.3–0.5 m, with a 5 % tail of 2–3 m, as in the photo study.

**(b) Dirt from accessibility, with a global term.** Local accessibility is a rule: hemisphere
`intersect()` rays of 5–30 cm, or `maskbyfeature` with AO. For crevices a short ray misses, add a
γ-ton-style global term:
- shoot tons inward from the bounding sphere;
- on each hit, settle with probability 1 − ks, otherwise bounce diffusely, up to 3 bounces;
- count settle points per receiver with `pcfind`.

dust = skyup^a × (1 − access)^b × (1 − washed), with washed from (a).

**(c) Impacts from causes.** Shoot rays along cause distributions:
- **traffic:** from the path curves at bumper heights (feet 0–0.3 m, carts 0.2–1 m, forklifts
  0.3–0.6 m), along the tangent ± 20°;
- **wind grit:** from the prevailing direction, with density ∝ exp(−y / 0.5 m).

Record the first hit; energy = |dir·N| × cause weight × (1 + k·convexity). Keep hits above the
material threshold. **The hits become the hotspot centres for `cluster_mask.vfl` and
`chip_points_edge.vfl`,** so clustering comes from geometry: protruding corners catch more rays.
Simulate against the assembled context, or every corner looks exposed. Under 1 s for 10k rays.

**(d) Foot traffic and touch.**
- Remesh the floor (0.15 m) and run `findshortestpath` from each start to each end, with a point
  cost attribute.
- Run a Helbing feedback loop of 5–10 passes: G ← G + I·use·(1 − G/Gmax) − G/T, then
  cost = 1 − κ·blur(G).
- Small κ keeps the paths direct; large κ bundles them into trunks.
- Paths ending at an interaction point add to its `touch`, and the 80/20 split falls out.
- Take the origin–destination weights from the generator's entrance and core graph.

**(e) Bent rails, cheap and worth it.**
- Run the rail centre curve through `vellumconstraints` (string or hair with plasticity) and
  `vellumsolver`, pinning the posts and hitting it with an animated collider.
- Take one frame and `sweep` it. Kinks localise between posts.
- For sheet metal, keep the procedural dents for props. For hero pieces use RBD Material
  Fracture with metal plasticity; don't use Vellum cloth for stiff steel.

**(f) Corrosion spread.** A `solver` SOP on a uniform remesh:
- each step, rust grows with probability ∝ wet_time × (neighbour rust + seed) × (1 − rust) ×
  (1 + feedback·rust);
- seed it at paint breaks (chips), junctions and upward-facing members;
- use the rust points as dirty sources for (a), so rust runs bleed downward;
- `neighbours()` depends on topology, so remesh uniformly or use `pcfind`.

**(g) Peeling paint (Paquette 2002).** On a UV grid or a remesh:
- fields: stress, crack strength (lowered by wetness, edges and rust), and adhesion;
- grow cracks one at a time, perpendicular to stress, until stress drops or they meet an
  existing crack, then relax stress nearby;
- where shear exceeds adhesion, lift flakes 0.2–0.5 mm with a 15–90° curl.

Growing cracks one at a time gives **T-junctions near 90°**, as in real drying cracks. Voronoi
networks give 120° Y-junctions, which is a tell. Keep Worley for crazing.

**Growth.** Moss and lichen from open diffusion-limited aggregation (DLA) or space-colonisation
walkers, seeded by wet_time × shade from (a).

## When not to simulate

- **Local-only causes:** the rules are as good and about 100× cheaper.
- **Tiling materials and trim sheets:** there is no object context.
- **Single modular pieces out of context:** a per-piece simulation breaks at seams and ignores
  neighbours. Simulate the assembly, or keep the rules.
- **Budget:** simulated masks need unique UVs or dense vertex colour, so use them for hero and
  unique pieces.
- **Control:** "less streak there" is easier as a rule weight. Keep a paintable source map.
- **Agent time:** if a pass takes over about 30 s per piece or needs a GPU solver, use rules.
- **Validation:** check the results against the photo statistics. Wrong inputs (rain direction,
  missing context) give confidently wrong output.

## Sources

- Dorsey, Pedersen & Hanrahan 1996, Flow and Changes in Appearance: https://graphics.cs.yale.edu/sites/default/files/dorsey_flow.pdf
- Chen et al. 2005, Visual Simulation of Weathering by γ-ton Tracing: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/gamma_ton.pdf
- Paquette, Poulin & Drettakis 2001, Surface Aging by Impacts: https://profs.etsmtl.ca/epaquette/Research/Papers/Paquette.2001/
- Paquette, Poulin & Drettakis 2002, The Simulation of Paint Cracking and Peeling: https://graphicsinterface.org/wp-content/uploads/gi2002-8.pdf
- Mérillou & Ghazanfarpour 2008, survey of aging and weathering: https://hal.archives-ouvertes.fr/hal-00333283
- Desbenoit, Galin & Akkouche 2004, lichen growth: https://diglib.eg.org/handle/10.2312/CGF.v23i3pp341-350
- Helbing et al., active walker trail formation: https://ar5iv.labs.arxiv.org/html/cond-mat/9805158
- Runions, Lane & Prusinkiewicz 2007, space colonization: https://www.algorithmicbotany.org/papers/colonization.egwnp2007.html
- Hierarchical desiccation crack patterns: https://arxiv.org/pdf/2501.07882
- Adobe, Painter particle editor: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/presets/creating-particles-presets/overview-of-the-particle-editor
- SideFX, Grunge Leaking Streaks COP: https://www.sidefx.com/docs/houdini/nodes/cop/grunge_leakingstreaks.html
- SideFX, Vellum plasticity; H22 RBD; RBD Bullet Solver; Find Shortest Path: https://www.sidefx.com/docs/houdini/vellum/plasticity.html · https://www.sidefx.com/docs/houdini/news/22/rbd.html · https://www.sidefx.com/docs/houdini/nodes/sop/rbdbulletsolver.html · https://www.sidefx.com/docs/houdini/nodes/sop/findshortestpath.html
