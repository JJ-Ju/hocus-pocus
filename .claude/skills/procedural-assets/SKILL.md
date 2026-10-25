---
name: procedural-assets
description: Build procedural generators and modular game assets in Houdini through the HocusPocus MCP tools the way AAA technical artists do — metrics and a layout plan first, greyboxed kit pieces stress-tested in place, then detail, instancing, trim-sheet surfacing, water-driven weathering, LODs, collision, export and a validated HDA. Use when asked to make a procedural building, city, prop or environment generator, a modular kit, a game-ready HDA tool, or to texture and weather a procedural asset.
---

# Procedural assets the way technical artists build them

This skill is the working method for building a procedural generator or a modular game asset
with HocusPocus. It distils how AAA environment and technical artists work: Bethesda's kit
process, Epic's City Sample, Embark's THE FINALS buildings, Insomniac's trims and
Manhattan, SideFX Labs. It adds the lessons from agents who built skyscraper generators with
these tools.

## The one idea to hold on to

**Professionals do not detail modular pieces first and arrange them later.** They work
coarse to fine:

1. Fix the **metrics**.
2. Generate a **layout plan**.
3. Prove the plan with **grey boxes**.
4. Detail the **most-used pieces**.
5. Surface and weather **last**.

Detailing first means scale and proportion problems surface after the expensive work. Every
studio source treats that as the classic junior mistake.

Studios do spend real effort on module quality. They do it once the grid, footprints and
pivots are locked and the pieces are proven in place.

## Workflow

Work through the phases in order. Each ends with a **gate**: checks you run and look at
before moving on. Save the hip at every gate.

### 0. Brief and reference

- Write down the target in a README: the platform and camera, which sets texel density and
  budgets; the style; and which parts the player enters.
- Gather reference before building: real buildings or concept art for proportion and
  silhouette, plus the signature features that make the style readable at a distance.
- Decide what is a modelled interior and what is faked with interior mapping. Real interiors
  are built only where the player goes.
- De-risk the unknowns before building. Spend a few calls proving anything that would force
  a redesign late:
  - a node or toolset you plan to rely on is installed (`search {kind: "types"}`; SideFX
    Labs often is not);
  - text renders in the script the style needs;
  - materials inside the asset reach the renderer;
  - the export format keeps what the engine needs.
- **Gate:** a README with the brief, budgets (triangles per LOD, texture memory) and 3–6
  signature features per style, plus the de-risk results.

### 1. Metrics

- Work in metres on a coarse grid: 0.5 m minimum snap, 1 m preferred.
- Fix these and write them in the README:
  - floor-to-floor height;
  - bay width;
  - door and window openings;
  - wall and slab thickness;
  - one pivot convention for every piece;
  - the piece names (`wall_mid_01`, `window_bay_01`, `corner_out_01`, …).
- Never change these later without rebuilding everything placed on them.
- **Gate:** a metrics table in the README. See [references/metrics-and-kits.md](references/metrics-and-kits.md).

### 2. Plan (layout before geometry)

- Decompose top-down: footprint, massing volumes or tiers, floors, facade faces, bays, a
  role per bay.
- Emit points that carry the plan: `role`, `name` (the piece), `floor`, `side`, `style`,
  `variant`, an orientation frame, `scale` and a stable `id`.
- Use split-grammar logic: fixed bays, floating fill so spans close exactly, corners placed
  explicitly, ground and top floors as special cases.
- Preview the plan as coloured points or boxes.
- **Gate:** for the default and two extreme parameter sets, roles per floor are right, no
  gaps, nothing outside the footprint. Measure with `inspect {what: "geo", group_by: "role"}`
  and `look`. See [references/generator-architecture.md](references/generator-architecture.md).

### 3. Greybox kit and stress test

- Make every piece as a box at its exact footprint and pivot. Place them with Copy to Points
  from the plan.
- Stress-test the cases where kits break:
  - odd widths, inner and outer corners;
  - setbacks, tall and short volumes;
  - style transitions, minimum and maximum floors.
- Add fill pieces (0.25, 0.5, 0.75 m) rather than patch pieces.
- **Gate:** a contact sheet of 6–9 seeds and extremes as greyboxes. Check that silhouettes
  differ and read as the style at play distance, before any detail exists. This is the
  cheapest point to fix proportion.

### 4. Detail the kit: utility first, hero last

- Detail in order: the most-used pieces (wall-mid, window bay), then corners and trims, then
  variants, then hero pieces.
- Each piece is its own small network, viewable alone. Do not write one monolithic generator
  wrangle.
- Edges catch light. Use one- or two-segment chamfers with weighted normals (mid-poly), or
  plan for 45° bevels in the trim normal map.
- Keep each piece inside its footprint. No nearly coplanar overlaps.
- Generate connective geometry directly: slabs, wall infill, roof planes, cores.
- **Gate:** each piece looked at alone, plus a close-up of a facade corner. Triangles per role
  against the budget (`group_by`).

### 5. Variation system

- Choose from curated options, not raw noise. Pick a style, then a variant within it, with
  weights.
- Keep neighbours coherent: one window style per facade or floor, and coupled rules (a
  balcony implies a door).
- Hash randomness from the stable `id` plus a per-layer seed (silhouette, facade, detail,
  material), never from `@ptnum`.
- Put most variety in the detail and material layer: material swaps, damage variants, decals,
  greebles.
- Expose style presets and a few seeds. Keep the parameter surface small.
- **Gate:** a 9-up variation sheet. Would a player tell these apart at distance? Watch for
  "10,000 bowls of oatmeal": technically unique, perceptually identical.

### 6. Surfacing

- Set the target first: ORM packing, normal Y convention for the engine, texel density.
- UVs:
  - strips (cornices, sills, mullions, bands, frames) into trim-sheet rows of power-of-two
    height;
  - large walls and slabs with world-scale tiling UVs;
  - a second, non-overlapping UV set for lightmaps where the engine needs it.
- Author the trim sheet, tiling materials and atlases (decals, windows, signs) procedurally in
  Copernicus. Keep albedo within 30–240 sRGB and metallic near binary.
- Detail from large to small: macro value and hue shifts first, because they are all that
  survives at distance; then meso, then micro.
- **Gate:**
  - a checker render to prove density and orientation;
  - a lit render at play distance and a grayscale version, to prove the value structure;
  - a close-up.

  See [references/surfacing.md](references/surfacing.md).

### 7. Weathering from geometry

- Weather where water and people put it, not with uniform noise. Compute attributes in SOPs:
  - `up` facing, for deposits;
  - ledge and sill emitters, then streaks down the wall below them and at mullions;
  - height above ground, for the splash band;
  - AO and concave corners, for dirt;
  - sun exposure, for bleaching;
  - metal fixtures, for rust bleed.
- Mask = geometric mask × noise breakup, then levels. Cap each layer around 60% coverage.
- Bake mesh-intrinsic maps (normal, AO, curvature, edge, thickness) with the Bake Geometry
  Textures COP.
- Keep placement-dependent masks as vertex colour or per-instance data, because shared trims
  cannot carry them.
- **Gate:** the facade at play distance shows streaks under sills, a darker base and cleaner
  upper corners. A close-up shows nothing repeating obviously.

### 8. Game outputs

- **LODs:** LOD0, then LOD1 without interiors and small greebles, then LOD2 as a shell or
  impostor. Re-apply weighted normals per LOD. Match albedo and value between LODs: render
  each LOD from the same camera and compare brightness.
- **Collision:** a convex hull per volume, thin masts kept out of the main hull, named
  `UCX_<mesh>_NN`.
- **Night windows:** interior mapping or an emissive atlas, with whole floors or zones lit
  together and an occupancy parameter.
- **Delivery:** instances for kit pieces (packed primitives). Export FBX per LOD and USD with
  LOD variants and material bindings.
- **Gate:** re-import each export into a fresh scene and render it with only its textures.
  Check triangle counts, UV sets, material slots and collision names. See
  [references/game-output.md](references/game-output.md).

### 9. Package the tool

- One HDA per job, plus a thin top-level asset holding the shared parameters. Name it
  `namespace::name::1.0`.
- The interface: a few high-level controls, presets and seeds in tab folders, with
  conditions that disable irrelevant parms, and help text.
- Bump the version when output changes in a way that would surprise existing scenes.
- Provide override inputs that survive regeneration, such as volumes or masks where rules
  change, and hand-placed pieces re-applied after generation.
- **Gate:** a fresh instance from the saved library cooks without errors. A toggled-off branch
  costs nothing (`cook {profile: true}` lists it as `inactive`). The README lists parms,
  attributes, budgets and limits.

### 10. Final review

- Re-run the 9-up sheet with final materials.
- Make a hero shot, a play-distance shot, a close-up, a night shot if relevant, and an
  interior or cut-away if interiors exist. Look at every image yourself.
- Write an honest assessment: what meets the bar, what is placeholder, what a human artist
  should still do.

## Rules

- **Coarse to fine, always.** No detailing before the plan and greybox gates pass.
- **Plan, then instance.** Points with attributes are the interchange format, and pieces are
  placed by Copy to Points. Generate connective geometry outright.
- **Small single-purpose stages.** Edit one stage without re-cooking or rewriting the others.
- **Determinism.** The same seed and parms give the same result. Randomness hashes a stable
  `id`.
- **Designed variation.** Curated styles and weighted variants; variety lives mostly in
  detail and materials.
- **Water-driven weathering**, macro value first, grayscale check before colour.
- **Measure, do not assume.** Budgets per role, cost of toggles, texel density, LOD value
  match.
- **Look often.** A cheap draft `look` after every structural change. Final renders at the
  gates, saved to files at once, read back and judged.
- **Test night and glass early** when windows matter: opaque glass hides interiors and lit
  rooms, and it only shows at night.

## Using HocusPocus for this

[references/hocuspocus-recipes.md](references/hocuspocus-recipes.md) has the concrete calls:
- building whole stages in one `edit` with `$id`, `dry_run` and `partial: "stop"`;
- long VEX through `value_file` and `patch`;
- spare parms with folders and conditions;
- `hda` create, save, version and info;
- `look` at a SOP alone, and final evidence with `output`, `jpeg_quality` and `wait_s`;
- per-role QA with `inspect geo group_by`;
- `cook profile` and `force: "chain"`;
- MaterialX materials with the `material` flag;
- Karma lighting and glass for checks and evidence;
- what is usually installed, and the VEX and Copy to Points traps;
- the traps earlier agents hit.

When an argument shape is uncertain, read `inspect {what: "tool", target: "<tool>"}` rather
than guessing.

## Reference files

| File | Read it for |
|---|---|
| [references/metrics-and-kits.md](references/metrics-and-kits.md) | Order of work, grid and metrics, piece taxonomy, pivots, repetition, edges, texel density, interiors, common mistakes |
| [references/generator-architecture.md](references/generator-architecture.md) | Top-down decomposition, plan-then-instance, grammars vs kits vs WFC, HDA structure, seeds, overrides, performance, validation |
| [references/surfacing.md](references/surfacing.md) | PBR targets, trims and tiling, macro/meso/micro, layer order, weathering physics, baking in Copernicus, windows, stylised anime looks |
| [references/game-output.md](references/game-output.md) | Instances, LODs, impostors, collision naming, lightmap UVs, engine attributes, export and proof |
| [references/hocuspocus-recipes.md](references/hocuspocus-recipes.md) | The tool calls for each phase and the traps |
