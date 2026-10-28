---
name: procedural-assets
description: Build procedural generators and modular game assets in Houdini through the HocusPocus MCP tools the way AAA kit and technical artists do — a fixed metrics contract, a quick functional skeleton, then quality built recursively from the smallest pieces up (golden piece, golden bay, then floor, facade, building, block), each level taken through its own blockout, refine and detail pass and judged at its own viewing distance, with instancing, surfacing, damage, LODs, collision, export and a validated HDA. Use when asked to make a procedural building, city, prop or environment generator, a modular kit, or a game-ready HDA tool.
---

# Procedural assets the way kit and technical artists build them

The working method for a procedural generator or a modular kit, built with HocusPocus. It
distils how AAA environment and technical artists work (Bethesda's kits, Epic's City Sample,
Embark's THE FINALS buildings, Insomniac's trims, SideFX Labs, visual targets and beauty
corners) and what agents learned building skyscraper and housing-block generators with these
tools.

Two companion skills do the deep work at piece level:
- **`procedural-mesh-damage`:** edge wear, chips, cracks and breaks in the geometry.
- **`procedural-materials`:** detailed materials, trim sheets, atlases and textures.

**Load both companion skills with the Skill tool, and read these files before the phase that
needs them.** Most of the realism guidance lives in their references, not in their SKILL.md
files. In the review-31 test, an agent that read only the SKILL.md files skipped the mesh
damage and repeated the uniform streak fringe the references warn against.

| Before | Read |
|---|---|
| Phase 0, brief | `references/believability.md` and `references/art-direction.md` (this skill) |
| Phase 3, golden piece: damage | `procedural-mesh-damage/SKILL.md`, its `references/causes.md`, and its scripts (`cluster_mask`, `chip_points_edge`, `cutter_shape`, `damage_measure`) |
| Phase 3, golden piece: materials | `procedural-materials/references/realism.md`, `micro-noise.md` and `layering.md` |
| Phase 4, golden bay; Phase 6, facade | `procedural-materials/references/weather-and-use.md`, plus the streak scripts (`streak_sources`, `streak_mask`, `micro_fields`) in `procedural-mesh-damage` |
| Unique or hero pieces whose wear depends on flow or history | `procedural-mesh-damage/references/wear-simulation.md` (recipes not yet tested) |

## The idea: quality is built recursively, from the smallest piece up

A building is a hierarchy of levels. A generator's quality is the quality of each level, and a
level cannot be better than the pieces it is made of.

| Level | Example | Judged at |
|---|---|---|
| L1 piece | window frame, wall panel, sill, railing, AC unit | arm's length |
| L2 module, bay | one window bay: panel + window + sill + trims + props | street level, 5–15 m |
| L3 floor, facade | a facade face: bays, corners, bands, transitions | across the street, 30–60 m |
| L4 building | massing, base, crown, silhouette | a block away, 100–300 m |
| L5 block, city | many buildings, variation, skyline | skyline distance |

Every level gets the same three passes before you move up:

1. **Blockout.** Proportion and arrangement with simple shapes.
2. **Refine.** Forms, joins, transitions, the edge treatment.
3. **Detail.** The breakup that belongs to that scale, then surface and review at that
   level's distance.

Start at L1 with the most-used piece and take it to final quality. Assemble finished pieces
into one finished bay, and take the bay through its own three passes. Then go up a level.

Two things come before that, and both are short:

- **The contract.** Metrics, grid, pivots, openings and joins. These are what let pieces made
  one at a time fit together. They are interfaces, not a reason to delay quality.
- **A functional skeleton.** Boxes at every level, placed by the generator, to prove the
  contract works. Keep it to an hour of work; it is a test, not a phase to polish.

Studios work this way:
- **Bethesda** finishes one piece completely before its variants.
- **Teams build a beauty corner or visual target early**, a small fully finished section that
  sets the bar.
- **Every level gets its own breakup pass:** piece variants, bay dressing, facade rhythm,
  building silhouette, block variety.

The failure this avoids: detailing late and shallowly, so every level is "fine" and nothing is
good.

## Distributing detail: clusters with a background

Real detail is caused, and causes are local. Put about 80 % of each notable detail on about
20 % of the surface: wear, damage, dirt, clutter, retrofits. Keep a low background of the same
layer everywhere else, so nothing is pristine. Even spreading is the most common reason
generated assets read as CG; reviewers call it "applied uniformly", "noise everywhere" or "no
story".

- **Clusters at every level:** 0–2 on a piece, with many instances getting none; 1–3 on a
  bay, one of them dominant; 3–7 "stories" on a facade; and a bias by orientation for the
  building.
- **One cause field drives every layer.** Hotspots carry a cause type (impact, leak, rust,
  neglect), and chips, stains, streaks, damp, rust and dirt all read the same field at their
  own radius. Independent noises per layer read as procedural even when each looks right.
  In a generator, make the causes a stage of the plan. For each facade, write points carrying
  a cause type, a radius and a strength, seeded from the building. Damage, materials (as
  primvars) and dressing all read those points.
- **Causes come from the environment and from use.**
  - **Environment:** edges take the most weather. Horizontal tops collect water and dirt and
    shed streaks from their low points and ends. Windward vertical edges are washed, and
    sheltered undersides keep crust.
  - **Use:** each piece carries `interaction` points at code heights (grip, push, press,
    slot, foot, strike). The building carries a `traffic` field from paths between
    entrances, cores and units. Touch and strike wear cluster at the few busiest points.

  See weather-and-use.md in `procedural-materials` and causes.md in `procedural-mesh-damage`.
- **Plain thresholded noise is not clustering.** It has the same density everywhere. Use
  sparse hotspot points with falloff, a mask at least as large as the frame, or a random
  subset of elements.
- **Measure it.** Show the cause field as colour at the level's distance; it should be a
  handful of blobs, not speckle. Check the share of the layer inside the hotspots.

[references/believability.md](references/believability.md) has the numbers, and the rest of
what makes an asset read as real: imperfection that keeps snapping, layers of history,
clutter personas, interiors, and presentation.

## Workflow

Each phase ends with a **gate**: checks you run and images you look at before moving on. Save
the hip and the gate images at every gate.

### 0. Brief, reference, de-risk

- Write the brief in a README:
  - platform and camera, which set texel density and budgets;
  - the style;
  - which parts the player enters;
  - 3–6 signature features per style that make it readable at a distance.
- Gather reference for every level: close-ups of real details (frames, joints, fixings, wear)
  as well as whole buildings.
- **Study the photographs; don't just collect them.** Look at 20 or more per subject, using a
  browser tool if one is available, and count what recurs. For example: where streaks start in
  17 of 17 photos, how often a break takes one face or both, how much denser the pores are at
  the top of a pour. Write the counts in the README as rules. Text research says what can
  happen; photographs say how often and where. Later, compare renders with these photos side by
  side, and list the mismatches ranked by how much they give the CG away.
- De-risk the unknowns that would force a redesign:
  - nodes you plan to rely on are installed (`search {kind: "types"}`; SideFX Labs often is
    not);
  - text renders in the script you need;
  - materials inside an asset reach the renderer;
  - the export keeps what the engine needs.
- **Gate:** README with brief, budgets (triangles per piece and per LOD, texture memory),
  signature features, de-risk results.

### 1. The contract

- Metres on a coarse grid: 0.5 m snap, 1 m preferred.
- Fix and write down:
  - floor-to-floor height, bay width, door and window openings, wall and slab thickness;
  - one pivot convention, and the footprint each piece must stay inside;
  - joins: how pieces meet (butt, overlap behind a trim, a connector piece) and which faces
    are seams that must stay clean;
  - piece names (`wall_mid_01`, `window_bay_01`, `corner_out_01`, …) and the level each piece
    belongs to.
- **Gate:** a metrics table and a piece list by level. See
  [references/metrics-and-kits.md](references/metrics-and-kits.md).

### 2. Functional skeleton (short)

- The plan stage of the generator: footprint, then tiers, floors, facade faces, bays. Points
  carry `role`, `name`, `floor`, `side`, `style`, `variant`, an orientation frame, `scale` and
  a stable `id`. See [references/generator-architecture.md](references/generator-architecture.md).
- Every L1 piece as a box at its exact footprint and pivot, placed by Copy to Points.
- Stress-test the cases where kits break: odd widths, inner and outer corners, setbacks,
  minimum and maximum floors, style transitions. Add fill pieces rather than patch pieces.
- **Gate:** a contact sheet of the default and the extremes. Pieces meet with no gaps and no
  overlaps, and roles per floor are right (`inspect geo group_by: "name"`). Then move on.

### 3. Golden piece (L1, most-used piece, to final quality)

Take the piece players see most, such as the window bay's frame and panel, all the way:

1. **Blockout:** its silhouette and proportion against reference.
2. **Forms:** primary (the outline), secondary (frames, recesses, sills), tertiary (seams,
   fixings, drip edges, bolts). Use at least three distinct size classes, and keep about 70%
   of the surface quiet so the 30% detail reads.
3. **Edges:** one strategy per kit, applied the same way everywhere:
   - chamfers with weighted normals (mid-poly);
   - a baked bevel from a high poly;
   - trim strips with 45° normal bevels.

   Bevel width is a fixed world size per kit, for example 1 cm, and should be visible at the
   piece's judging distance. A constant bevel is the convention. Its sameness is broken
   by what the edge carries: wear in runs along the edge, about half to two thirds of each
   edge clean, and a roughness difference where the edge is worn.
4. **Damage and wear:** where the piece really gets hit, clustered (above). Use the
   `procedural-mesh-damage` skill: geometry for silhouette breaks, the bake for small nicks,
   seams kept clean, seeded per instance, and a share of instances left with background wear
   only.
5. **Imperfection:** the real tolerances, exaggerated a little: lippage, sag, a tilted pane,
   a door out of square, a bulge in thin sheet metal. Apply it in world space after assembly,
   or fade it to zero at the piece's seams, so snapping survives (see believability.md §2).
6. **UVs and texture:** trim-sheet rows or tiling at the target texel density. Make its
   materials with the `procedural-materials` skill.
7. **Review in context:** next to its neighbours in the skeleton, lit, at arm's length and at
   bay distance. Not alone in a void.

- **Gate:**
  - a close-up that would pass in a portfolio crop;
  - triangle count against budget;
  - the piece validated: closed, UVs complete, seams unchanged.

  If it does not hold up at arm's length, nothing above it will.

### 4. Golden bay (L2, the beauty corner)

- Bring the other pieces of one bay to the golden piece's standard: panel, window, sill,
  trims, railing, the bay's props.
- **Blockout** the bay arrangement. **Refine** the joins: overlaps tucked behind trims,
  connector pieces, no seams catching light. **Detail** at bay scale: cables, pipes, signage,
  edge decals at corners, a prop cluster, and the bay's own wear story (streaks under its sill,
  grime at its base).
- Props pass the same three-size-class rule as the pieces. Soft goods (laundry, futons,
  awnings, tarps) need sag, folds and thickness; flat cards read as paper at any distance.
  Keep prop colours as muted as the reference: candy colours look like a toy.
- Drive a unit's props, curtains, fixtures and states from one persona per unit (tidy, family,
  gardener, elderly, vacant), not from independent draws. Interiors behind glass get layers
  (curtain, lace, a furniture shape, a back wall 3–4 m deep); dark by day is right, empty is
  wrong.
- Light it as the final scenes will be lit. This bay is the quality bar for everything else.
- **Gate:** a lit render of the bay at street distance next to reference, and a grayscale
  version for value structure. Write down what makes it good, and use it as the checklist for
  every other bay.

### 5. Build-out (the rest of the kit)

- Take the remaining L1 pieces to the golden standard, most-used first: corners, ends, ground
  floor, roof pieces, then hero pieces.
- Make variants as material swaps, damage seeds and combinable states, not new geometry.
- Each new piece passes the golden-piece gate on its own.
- **Connective and unique geometry is a piece too.** End walls, plinths, roof slabs and
  cores are generated once per building rather than instanced, so they are easy to leave as
  plain boxes. They are often the largest surfaces in the hero views. Give each the
  golden-piece pass: forms in three sizes, joints, fixings, its own wear story.
- **Gate:** a kit sheet with every piece lit and laid out, each at the same quality.

### 6. Up the levels: facade, building, block

At each level run the three passes and review at that level's distance.

- **L3 floor and facade:**
  - *Blockout:* the facade rules, i.e. bay rhythm, floating fill, ground and top floors.
  - *Refine:* corners, bands, setback transitions, style transitions.
  - *Detail at facade scale:* macro value and hue variation per bay or floor; weathering
    placed by the facade's geometry (streaks below ledges, darker base, washed corners);
    decals; per-flat variation such as curtains, lit windows and AC units.
  - *History:* 3–4 timeline events that each leave geometry or material. For example: the
    build, a repaint with mismatched patches, retrofits in 2–3 generations (AC units, ducts,
    dishes, replaced sashes, an added lift), and decay.
  - *Stories:* 3–7 notable clusters per facade, from the shared cause field. Check that
    the clustering survives at this distance, not only up close.

  Review across the street.
- **L4 building:**
  - *Blockout:* massing and tiers.
  - *Refine:* base, crown, roofline, silhouette features.
  - *Detail:* rooftop clutter, signage, landmarks.

  Review from a block away, and squint: the silhouette alone should name the style.
- **L5 block and city:**
  - *Blockout:* placement and height zones.
  - *Refine:* variety across buildings (curated styles, weighted variants, two-level choice).
  - *Detail:* street-level dressing if in scope.

  Review a 9-up variation sheet at skyline distance. Watch for "10,000 bowls of oatmeal":
  outputs that are technically unique but look the same.
- Randomness hashes the stable `id` plus a per-level seed, never `@ptnum`.
- **Gate per level:** the level reads correctly at its distance, compared with the golden bay
  for quality and with reference for style.

### 7. Game outputs

- LOD0, then LOD1 (no interiors, no small greebles, damage above a size cutoff only), then
  LOD2 (a shell or impostor). Match value across LODs: render each from one camera and compare
  mean facade brightness, within about 3 %. A flat shell whose recesses are painted in is
  lit by the sun where the real recess is in shadow; darken it until the numbers match.
- Detail that belongs to LOD0 only (damage, props, small fixings) branches off after the LOD
  split, so LOD1 is built from undamaged sources. Otherwise it leaks into the lower LODs
  without notice.
- Collision: convex hulls per volume, with thin masts kept separate, named `UCX_<mesh>_NN`.
- Delivery: instances for kit pieces, FBX per LOD, USD with LOD variants and material
  bindings.
- **Gate:** re-import into a fresh scene and render with only its own textures. Check
  triangle counts, UV sets, material slots and collision names. See
  [references/game-output.md](references/game-output.md).

### 8. Package

- One HDA per job, plus a thin top-level asset with the shared parameters.
- **One generator per architectural family.** A slab danchi or mid-rise apartment generator
  and a skyscraper or cyberpunk tower generator share kit conventions and metrics, but they
  are separate HDAs. Each one specialises in its own typology, massing rules and dressing.
  Don't grow one asset into a do-everything building tool.
- **Weathering is an interface, not a bake-in.** Expose macro controls (age in years, upkeep,
  urban grime, exposure direction, seed) that drive every wear layer: edge damage, edge wear,
  streaks, stain fields, grime, rust, repaint patches, growth. Give each layer an "auto"
  value with an override, and add presets (new, well kept, typical, neglected). Show them at
  several values: a preset strip and per-control sweeps at fixed cameras.
- Name: `namespace::name::1.0`.
- Interface: a few high-level controls, style presets and seeds in tab folders, with
  conditions and help.
- Bump the version when output changes.
- Provide override inputs that survive regeneration.
- **Gate:** a fresh instance from the saved library cooks with no errors, toggled-off branches
  cost nothing, and the README lists parms, attributes, budgets and limits.

### 9. Final review

- A close-up of the golden bay, a street view, a building view, the 9-up sheet, night if
  windows matter, and a cut-away if interiors exist. Look at every image.
- Present it the way a photographer would, or the render gives it away:
  - ground context (paving, kerbs, planting, poles and wires, bikes, people for scale);
  - a sun 15–35° high, raking the facade;
  - eye-height cameras at 24–35 mm with straight verticals;
  - atmospheric perspective.

  An aerial over a bare plane reads as a miniature.
- An honest assessment by level: which levels meet the bar, which are placeholder, and what a
  human artist should still do.

## Rules

- **Contract first, then quality from the bottom up.** Pieces made one at a time fit because
  the contract fixed how they meet.
- **Every level gets blockout, refine and detail**, and is judged at its own distance before
  the next level starts.
- **The golden bay is the bar.** Every other bay and level is compared with it.
- **Plan, then instance.** Points with attributes are the plan, and pieces are placed by Copy
  to Points. Generate only the connective geometry outright.
- **Small single-purpose stages.** Each piece is its own network; no monolithic generator
  wrangle.
- **Determinism and designed variation.** Seeded by stable ids; curated styles and weighted
  variants; most variety in materials, damage and dressing.
- **Clustered, caused detail.** About 80 % of each notable detail on about 20 % of the
  surface, over a low background; one cause field for every layer.
- **Measure, do not assume.** Triangles per piece and per level, validation numbers, texel
  density, LOD value match.
- **Look often and in context.** A draft `look` after each structural change. Final renders
  at the gates, saved to files at once, read back and judged against reference.
- **Critique the picture, not only the parts.** At every lit or final look run
  `scripts/frame_critique.py`; act on its binding tests, and treat `info` results as
  notes. At each level gate run the full set, plus `--pair` against the previous gate at the
  same camera, then the A/B questions in `references/critique_questions.md`. Fix the fails
  first. The baseline is realistic; a painterly profile is optional, built as a switchable
  layer (`procedural-materials/references/stylisation-anime.md`) and judged with
  `--profile painterly`. See `references/art-direction.md`.
- **Test night and glass early** when windows matter.

## Using HocusPocus for this

[references/hocuspocus-recipes.md](references/hocuspocus-recipes.md) has the concrete calls:
- whole stages in one `edit` with `$id`, `dry_run` and `partial: "stop"`;
- long VEX through `value_file` and `patch`;
- spare parms with folders and conditions, and `hda` create, save, version and info;
- `look` at a SOP alone, and final evidence with `output`, `jpeg_quality` and `wait_s`;
- per-role QA with `inspect geo group_by`, and `cook profile` and `force: "chain"`;
- MaterialX materials with the `material` flag, and Karma lighting and glass;
- what is usually installed, plus the VEX and Copy to Points traps.

When an argument shape is uncertain, read `inspect {what: "tool", target: "<tool>"}`.

## Reference files

| File | Read it for |
|---|---|
| [references/metrics-and-kits.md](references/metrics-and-kits.md) | Contract, grid, taxonomy, pivots, joins, repetition, edges, texel density, beauty corners, quality targets, mistakes |
| [references/generator-architecture.md](references/generator-architecture.md) | Decomposition, plan-then-instance, grammars vs kits vs WFC, HDA structure, seeds, overrides, performance, validation |
| [references/art-direction.md](references/art-direction.md) | Picture-level judgement: value structure, saturation budget, composition, detail budget, read at distance, seed spread; running `scripts/frame_critique.py` at each gate; failures and fixes |
| [references/believability.md](references/believability.md) | Clusters with a background (80/20) and the cause field, imperfection that keeps snapping, layers of history, clutter personas and soft goods, interiors, presentation, critiques |
| [references/surfacing.md](references/surfacing.md) | Asset-level surfacing strategy: trims vs tiling, macro value, where weathering goes, windows, stylised looks |
| [references/game-output.md](references/game-output.md) | Instances, LODs, impostors, collision naming, lightmap UVs, engine attributes, export |
| [references/hocuspocus-recipes.md](references/hocuspocus-recipes.md) | Tool calls for each phase, and the traps |
