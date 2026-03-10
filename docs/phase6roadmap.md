# HocusPocus Phase 6 Roadmap

Status: draft roadmap

Branch: `codex/phase5`

Scope:

- add the domain-specific authoring tools and macros needed for reliable agent-driven asset creation
- move from "powerful generic Houdini automation" to "strong procedural asset and shot authoring"
- focus on semantic building blocks, reusable procedural kits, and critique loops instead of low-level graph churn

This phase assumes the current baseline from phases 1 through 5 planning:

- strong live node, parm, task, graph, USD, PDG, HDA, dependency, render, and packaging support
- higher-level graph planning and patching
- growing operator and platform maturity work in phase 5

## 1. Goals

Primary goals:

- let agents build substantial assets from scratch using semantic authoring tools
- reduce the number of low-level Houdini decisions required for common asset workflows
- improve not just generation, but refinement, consistency, and art-direction control
- support procedural modeling, lookdev, scattering, and simulation setup as first-class workflows

Non-goals for this phase:

- replacing artist taste or fully automating subjective art direction
- building a fully general DCC abstraction across non-Houdini tools
- cloud/farm orchestration as the primary focus

## 2. Priority Order

1. procedural building and hard-surface toolkit
2. material and lookdev macros
3. terrain, forest, and scatter toolkit
4. simulation setup toolkit
5. visual critique and iteration loop
6. reusable recipe and style-profile system

## 3. Phases

## Phase 6A. Procedural Building and Hard-Surface Toolkit

Problem:

- the current MCP can build building networks, but it still requires too much low-level node planning for dependable architectural or sci-fi asset generation

Deliver:

- semantic building generators such as:
  - `building.generate_massing`
  - `building.subdivide_facade`
  - `building.add_window_grid`
  - `building.add_structural_bands`
  - `building.add_rooftop_mech`
  - `building.apply_style_profile`
- reusable façade, trim, window, roof, and rooftop component libraries
- graph templates for skyscraper, tower, industrial, and modular hard-surface patterns
- parameterized style controls for density, repetition, damage, detail level, and silhouette complexity

Success looks like:

- an agent can generate a convincing procedural sci-fi tower or city-block building without inventing the network structure from scratch
- repeated builds are structurally coherent and easier to iterate

## Phase 6B. Material and Lookdev Authoring Macros

Problem:

- current material tools are good for assignment and basic authoring, but not yet strong enough for believable finished assets

Deliver:

- higher-level shader tools such as:
  - `shader.create_pbr_material`
  - `shader.create_triplanar_stack`
  - `shader.create_layered_building_material`
  - `shader.randomize_variants`
  - `shader.assign_by_group`
- mask and procedural breakup helpers for dirt, rust, wear, edge damage, leaks, and surface variation
- lookdev helpers for material balancing and variant generation across repeated modules
- hooks for texture-set conventions and grouped assignment patterns

Success looks like:

- an agent can produce assets with believable material variation and not just flat default shaders
- building façades, props, and environment assets can be shaded consistently through reusable macros

## Phase 6C. Terrain, Forest, and Scatter Toolkit

Problem:

- forests and environments are possible with raw node tools, but reliable, art-directable biome construction needs higher-level scatter semantics

Deliver:

- environment tools such as:
  - `terrain.generate_base`
  - `terrain.erode`
  - `terrain.mask_by_slope`
  - `scatter.create_biomes`
  - `scatter.populate_species`
  - `scatter.add_understory`
  - `scatter.add_deadfall_and_debris`
  - `scatter.optimize_instances`
- species templates and scatter presets for canopy, understory, ground cover, and debris layers
- controls for biome logic, spacing, clustering, altitude, slope response, and density variation
- instance, packed-primitive, and LOD optimization helpers

Success looks like:

- an agent can build a bespoke forest or natural environment that reads as authored rather than uniformly scattered
- generated environments can be varied and optimized without manual node surgery

## Phase 6D. Simulation Setup Toolkit

Problem:

- building a collapse sim or destruction setup through generic node authoring is possible, but too fragile and slow for dependable results

Deliver:

- simulation helpers such as:
  - `sim.prepare_rbd_asset`
  - `sim.fracture_concrete`
  - `sim.fracture_glass`
  - `sim.generate_constraints`
  - `sim.add_ground_and_impactors`
  - `sim.configure_solver`
  - `sim.cache_sim_layers`
- sim validation and diagnostics tools such as:
  - `sim.check_unstable_constraints`
  - `sim.inspect_broken_pieces`
  - `sim.validate_cache_chain`
- reusable templates for common destruction and debris workflows

Success looks like:

- an agent can take an input building and produce a credible first-pass collapse or destruction setup with less low-level guesswork
- caching and debug flows are exposed clearly enough to iterate on sim behavior

## Phase 6E. Visual Critique and Iteration Loop

Problem:

- generation alone does not create strong assets; the system also needs ways to critique repetition, silhouette, density, and readability

Deliver:

- analysis tools such as:
  - `asset.analyze_repetition`
  - `asset.analyze_silhouette`
  - `scene.analyze_visual_density`
  - `lookdev.analyze_material_balance`
- review helpers such as:
  - `review.capture_asset_sheet`
  - `review.generate_turntable_preview`
  - `review.compare_versions`
- structured feedback outputs that help an agent revise its own work

Success looks like:

- an agent can generate, review, revise, and compare assets in a closed loop instead of only emitting first-pass results
- repeated procedural results become less uniform and more art-directed over time

## Phase 6F. Reusable Recipes and Style Profiles

Problem:

- even with better macros, agents need reusable authored patterns and style controls to build consistently across projects

Deliver:

- recipe registry and instancing workflows such as:
  - `asset.list_recipes`
  - `asset.instantiate_recipe`
  - `asset.configure_recipe`
- style profiles such as:
  - `brutalist_sci_fi`
  - `corporate_futurist`
  - `temperate_forest_realistic`
  - `storm-damaged industrial`
- rule-based controls for variation budgets, damage level, density, clutter, and repetition tolerance

Success looks like:

- agents can build assets from stable high-level recipes rather than reconstructing everything ad hoc
- style direction becomes explicit and reusable

## 4. Recommended Sequence

1. procedural building and hard-surface toolkit
2. material and lookdev macros
3. terrain, forest, and scatter toolkit
4. simulation setup toolkit
5. visual critique and iteration loop
6. reusable recipe and style-profile system

## 5. Design Principles

- prefer semantic authoring tools over large numbers of thin low-level wrappers
- keep Houdini nodes as the source of truth; recipes and macros should generate auditable graph structures
- return rich post-operation summaries so agents can keep iterating without extra inspection calls
- preserve escape hatches: every macro should still be inspectable and editable with the underlying node tools
- optimize for iterative refinement, not one-shot generation

## 6. Success Criteria

This phase is successful when:

- an agent can build a credible procedural skyscraper with geometry and lookdev using mostly semantic tools
- an agent can build a bespoke forest with terrain, biome, scatter, and optimization support
- an agent can create a first-pass building collapse setup with fracture, constraints, and cache workflow support
- generated assets can be critiqued and refined through structured review loops instead of only manual visual judgment
