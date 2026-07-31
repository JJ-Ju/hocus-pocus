# HocusPocus Phase 6 Roadmap

Status: draft roadmap

Branch: `codex/phase6`

Scope:

- add the domain-specific authoring tools and scaffold patterns needed for reliable agent-driven asset creation
- move from "powerful generic Houdini automation" to "strong procedural asset and shot authoring"
- focus on semantic building blocks, reusable procedural kits, and critique loops instead of low-level graph churn
- treat Houdini as the procedural engine and the agent as the designer of rule graphs, not the direct placer of final geometry
- favor generator scaffolds, procedural grammars, and editable system templates over hardcoded one-shot asset macros

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
- ensure semantic tools build compact, parameterized procedural systems that Houdini can evaluate, rather than hundreds of explicit node-level mesh placements
- let agents author stylistically different rule systems, not just call fixed generators for specific asset archetypes

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

- semantic building scaffold tools such as:
  - façade-subdivision scaffold builders
  - floor-repetition scaffold builders
  - rooftop-population scaffold builders
  - building-grammar and module-vocabulary helpers
- reusable façade, trim, window, roof, and rooftop component libraries
- graph templates for skyscraper, tower, industrial, and modular hard-surface patterns
- parameterized style controls for density, repetition, damage, detail level, and silhouette complexity
- generator-style graph patterns where spacing, count, offsets, and module choice are driven by rules and attributes rather than per-piece authoring
- scaffolds for authoring building grammars and module vocabularies so agents can design different architectural systems instead of only instantiating a baked tower recipe

Success looks like:

- an agent can generate a convincing procedural sci-fi tower or city-block building without inventing the graph structure from scratch
- repeated builds are structurally coherent and easier to iterate
- the resulting graphs look like reusable procedural systems, not one-off modeling sessions made from many individually placed meshes or misleading canned macros

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
- parameterized shader systems and assignment logic that can be reused across generated assets
- lookdev system scaffolds that agents can tailor to different visual languages instead of relying on a single hardcoded material recipe

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
- scatter and terrain systems driven by masks, attributes, and rules instead of direct placement of individual assets
- environment-generation scaffolds where the agent defines species behavior, biome logic, and spatial rules rather than invoking a fixed forest preset

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
- solver, fracture, and constraint systems that expose rules and parameters rather than one-off direct graph assembly
- simulation system scaffolds that let the agent define material-specific fracture, constraint, and failure logic instead of selecting a single canned collapse setup

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
- recipe scaffolds that can be customized into new system grammars instead of being treated as immutable finished generators

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
- prefer system-building over direct geometry authoring
- use repetition, copy, scatter, attribute, and rule-driven graph patterns wherever Houdini already offers them
- avoid emitting large counts of explicit mesh nodes when a compact procedural subnetwork can express the same design intent
- think in HDA-style terms even when the output is not yet formalized as a digital asset
- treat example generators as scaffolds for procedural grammar design, not as the final product
- design tools so agents can author distinct stylistic rule sets such as sci-fi, gothic, or vernacular systems through parameterized graphs

## 6. Success Criteria

This phase is successful when:

- an agent can build a credible procedural skyscraper with geometry and lookdev using mostly semantic tools
- an agent can build a bespoke forest with terrain, biome, scatter, and optimization support
- an agent can create a first-pass building collapse setup with fracture, constraints, and cache workflow support
- generated assets can be critiqued and refined through structured review loops instead of only manual visual judgment
- generated graphs are compact, parameterized systems that a Houdini artist would recognize as procedural setups rather than explicit per-part construction
- the same scaffolding can be pushed toward materially different design languages because the agent is authoring rules, not just instantiating canned content
