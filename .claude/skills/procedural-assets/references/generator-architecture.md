# Generator architecture

How technical artists structure procedural building and city generators, and how that maps
onto Houdini. Sources are at the end.

## Decompose top-down, and keep each stage's output inspectable

Every serious generator refines in stages: coarse layout first, finer detail later.

    city outline → roads → blocks → lots → footprint → massing volumes → floors
    → facade faces → bays → modules → details

- **Shape grammars** (Müller et al., SIGGRAPH 2006; CityEngine CGA) build a volumetric mass
  model, then split facades into floors and floors into tiles, then place windows, doors and
  ornament. The split operator takes absolute sizes, relative sizes and floating sizes, and
  repeats a tile as many times as it fits; floating sizes stretch so a span fills exactly with
  no partial piece. Context rules stop windows from cutting into neighbouring walls.
- **Epic City Sample (Houdini)** chains single-purpose HDAs: layout, zone heights, freeway,
  city processor, lot processor (size, setbacks, sidewalks, style, height). Building
  generation, the most expensive step, runs in parallel through PDG.
- **City Sample (Unreal PCG)** extrudes each footprint between a minimum and maximum height,
  then a shape grammar dresses it in one of 27 curated style codes. Changing an upstream stage
  resets everything downstream, so order stages from most stable to least stable.

## Plan first, then instance

The standard Houdini shape:

1. A **plan** stage emits no final geometry. It writes points (or prims) carrying attributes:
   `floor`, `side`, `bay`, `role` (wall, window, door, corner, trim…), `style`, `variant`,
   the chosen piece's `name`, an `orient` or `N`/`up` frame, `scale` where a piece
   stretches, and a stable `id`.
2. A **build** stage copies kit pieces onto those points with Copy to Points, using its Piece
   Attribute to pick the piece per point and Pack and Instance so copies share geometry.
3. Only **connective geometry** is generated outright: slabs, wall infill between modules,
   roof planes, core walls, collision proxies.

The plan is cheap to cook, easy to validate (count roles per floor, check spacing) and easy
to preview as coloured points. Detail can be swapped without touching layout.

What studios do:

- **Epic** exports Houdini point clouds and maps them to kit pieces with rules in Unreal.
- **Embark (THE FINALS, ARC Raiders)** generates walls, floors and roofs, and copies
  artist-made modules for windows, door frames, cornices, eaves and railings. A module bundles
  visual meshes, boolean cutters for its opening, and sockets that spawn engine actors. Roofs
  are assembled from four artist pieces: plane, ridge, fascia, eaves.
- **Ubisoft (Ghost Recon Wildlands)** enforced door, window and floor measurements in the
  tool and generated UVs and ground dirt strips; artists then hand-placed windows, doors and
  props.
- **SideFX Labs Building Generator** turns low-res blockouts into buildings from a library of
  modules.
- **Insomniac (Spider-Man)** used a Houdini pipeline over existing building kits for
  Manhattan, including impostors.

**When to generate geometry outright instead of instancing:** background buildings,
structural and connective parts, one-off hero shapes, and early prototypes where no kit exists
yet. An agent without an artist kit should still author the kit pieces as separate,
reusable SOP networks and place them through the plan, rather than writing one monolithic
VEX generator; the pieces then get edited, varied and LOD'd one at a time.

## Approaches and when they fit

| Approach | Fits | Examples |
|---|---|---|
| Split or shape grammar | Rectilinear facades, many styles, city scale | CGA, City Sample PCG |
| Attribute plan plus kit instancing | Game buildings held to an artist kit's quality | Epic, Embark, Labs |
| Fully generated geometry | Slabs, walls, roofs, collision, background massing | Embark, Wildlands |
| Wave function collapse | Tile-based adjacency layouts, small dioramas, player-driven building | Townscaper, Bad North, Labs WFC |

WFC chooses which handcrafted modules may sit next to each other; it handles long thin
structures (walls, pipes) poorly and can fail, so it needs a restart or a silent fallback.
Oskar Stålberg's rule of thumb: large shapes predictable, small details varied.

## HDA structure

- **One tool per task.** Ubisoft's lesson from Wildlands: meta-tools that tried to do
  everything were a mistake; clear inputs and outputs let tools feed each other.
- **Embark's template:** an object-level creator holds the shared parameters (wall thickness,
  floor height) and generates nothing. A chain of SOP-level feature nodes (walls, floors,
  roofs, windows, doors) each take and pass on two streams: building geometry, and the
  blockout plus context data. Most features are order-independent; editing one does not
  re-cook the rest. Collision and occluders are generated last. Features are named after real
  architectural elements.
- **Small parameter surface:** footprint, floors, floor height, style, and a few seeds. Put
  the rest in folders or presets. Style presets are curated sets of values, not free random.
- **Naming and versions:** `namespace::name::1.0`. Versions coexist in a scene and old nodes
  are not upgraded automatically; the internal name cannot change later, so pick it first. Bump
  the version when output changes in a way that would surprise an existing scene.

## Seeds, determinism and variation

- Hash randomness from a **stable id** plus a **per-layer seed** (silhouette, facade, detail,
  material), never from `@ptnum` or `@primnum`: those renumber when topology changes and
  reshuffle every result.
- **Two-level choice:** pick a style, then a variant inside it. Keep neighbouring windows in
  the same style; couple rules that belong together (a balcony implies a door).
- **Weights and priorities** decide among candidate modules (Labs Building Generator: weight
  for probability, priority for conflicts, `<A-B>` for modules that repeat to fill a span,
  `[]` for modules placed once).
- **Beat sameness on purpose.** Kate Compton's "10,000 bowls of oatmeal": outputs can be
  technically unique and still look identical. Aim for differences a viewer perceives at
  play distance: silhouette, proportion, value pattern, signature features.
- **Designed, not random.** Ubisoft: "nothing is random" in Wildlands; procedural tools carry
  designed intent.

## Overrides that survive regeneration

Artists need to hand-fix results without the next cook wiping them.

- Override inputs: bounding boxes or volumes where rules change or a hand-made piece is kept
  (Labs), per-floor overrides, painted masks or splines that constrain height (City Sample).
- Store hand edits as data anchored in world space, reapplied after generation (Embark).
- Lock generated data before manual work, or hand-author a region and generate around it
  (Ubisoft).
- Flag items that need an artist's attention after an upstream change instead of silently
  breaking them (Insomniac).

## Performance

- Wrap per-building or per-piece for-each loops in a compiled block, with "multithread when
  compiled" on the outer loop only. No `stamp()`; reference other geometry through spare
  inputs, not node paths. Profile before optimising.
- Cache between the plan and the build so detail edits do not re-run layout.
- Packed primitives are the recommended way to hand instances to an engine.
- Data points: Embark iterates from blockout to a fractured building in 4–6 minutes; City
  Sample rule processing takes 15–60 minutes.

## Validation and testing

- Validate stage outputs, not just final pictures: roles per floor, spacing, gaps between
  modules, pieces outside the plan's bounds, open edges, unexpected attribute values,
  triangles per role against budget.
- Sweep seeds, styles and footprints (a TOPs wedge, or a loop of instances in one scene) and
  review a contact sheet for breakage and sameness. Use the wedge number in output paths so
  results do not overwrite each other.
- Ship a minimal version early and iterate with its users.

## Failure modes

1. Manual edits wiped by regeneration.
2. Upstream edits cascading through everything downstream.
3. Monolithic tools and feature creep.
4. Topology problems: non-watertight pieces, rotated or off-centre modules leaving gaps, a
   stray `N` attribute orienting instances wrongly.
5. Output players cannot navigate.
6. Version brittleness when Labs nodes or Houdini change: pin versions.
7. Slow cooks and non-deterministic results.
8. Sameness.

## Sources

- Müller et al. 2006, procedural modelling of buildings: https://history.siggraph.org/?p=113547
- CGA split: https://doc.arcgis.com/en/cityengine/latest/cga/cga-split.htm
- City Sample with Houdini: https://dev.epicgames.com/documentation/unreal-engine/city-sample-quick-start-for-generating-a-city-and-freeway-using-houdini
- City Sample PCG: https://dev.epicgames.com/documentation/unreal-engine/city-sample-pcg-for-unreal-engine
- Embark, THE FINALS buildings: https://www.sidefx.com/community/making-the-procedural-buildings-of-the-finals-using-houdini/
- Ghost Recon Wildlands: https://80.lv/articles/procedural-technology-in-ghost-recon-wildlands/
- Far Cry 5: https://80.lv/articles/houdini-procedural-world-generation-of-far-cry-5/
- Spider-Man procedural authoring: https://history.siggraph.org/learning/procedural-system-assisted-authoring-of-open-world-content-for-marvels-spider-man-by-santiago/
- Townscaper and Bad North: https://www.gamedeveloper.com/game-platforms/how-townscaper-works-a-story-four-games-in-the-making
- Labs Building Generator: https://www.sidefx.com/docs/houdini/nodes/sop/labs--building_generator-4.0.html and https://www.sidefx.com/docs/houdini/nodes/sop/labs--building_generator_utility-2.0.html
- Building Generator tutorial: https://sidefx.com/tutorials/building-generator
- Copy to Points: https://www.sidefx.com/docs/houdini/nodes/sop/copytopoints.html
- Compiled blocks: https://www.sidefx.com/docs/houdini/model/compile.html
- Asset versioning: https://sidefx.com/docs/houdini/assets/versioning_systems.html
- Practitioner generator (Andrew Guan): https://80.lv/articles/learn-how-to-make-procedural-building-generator-in-houdini/
- PDG in game pipelines: https://80.lv/articles/exploring-houdini-use-of-pdg-in-game-pipelines/
- Kate Compton, generators: https://galaxykate0.tumblr.com/post/139774965871/so-you-want-to-build-a-generator
- Stable ids for randomness: https://www.sidefx.com/forum/topic/17338/
