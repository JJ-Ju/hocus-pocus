# HocusPocus Phase 7 Roadmap

Status: draft roadmap

Branch: `codex/phase5`

Scope:

- extend HocusPocus beyond single-asset authoring into full environment, worldbuilding, shot-layout, and publish workflows
- add domain toolkits and templates for urban, interior, industrial, natural, and presentation-oriented scene creation
- build on the procedural asset and critique systems planned for phase 6
- continue the system-first rule: agents should author procedural worldbuilding systems in Houdini rather than directly placing large numbers of final meshes
- treat environment and shot tools as scaffolds for rule systems and scene grammars, not as hardcoded output macros

This phase assumes the current baseline from phases 1 through 6 planning:

- strong platform, graph, task, pipeline, USD, PDG, HDA, render, packaging, and validation coverage
- planned semantic asset generators and critique loops from phase 6

## 1. Goals

Primary goals:

- let agents assemble complete environments and shot-ready scenes, not just individual assets
- support worldbuilding domains that combine many procedural systems into coherent locations
- improve storytelling, presentation, and publish workflows through reusable templates and higher-level scene macros
- keep the resulting scene logic compact, parameterized, and generator-oriented so it remains editable and reusable
- allow agents to author different worldbuilding languages and scene grammars rather than only invoking fixed scene presets

Non-goals for this phase:

- full character creation or rigging as a primary focus
- replacing external DCCs for final editorial, compositing, or animation pipelines
- generalized asset-management backends beyond what is needed for procedural scene assembly

## 2. Priority Order

1. urban, roads, and infrastructure toolkit
2. interiors and modular space toolkit
3. industrial and mechanical environment toolkit
4. natural formations, water, and shoreline toolkit
5. weathering, damage, and set-dressing toolkit
6. shot assembly, review, and publish toolkit

## 3. Phases

## Phase 7A. Urban, Roads, and Infrastructure Toolkit

Problem:

- city and exterior scene assembly needs road, block, and infrastructure logic beyond isolated building generation

Deliver:

- tools such as:
  - `city.generate_block_grid`
  - `road.generate_spline_network`
  - `road.build_intersection`
  - `road.decorate_street`
  - `infrastructure.place_utility_lines`
  - `infrastructure.populate_street_furniture`
- reusable templates for blocks, lanes, curbs, sidewalks, medians, signage, and lighting
- traffic- and pedestrian-oriented spacing and dressing rules
- generator graphs for road, block, and infrastructure repetition rather than direct per-piece scene placement
- urban grammar scaffolds that agents can adapt into different planning and architectural systems rather than a single street-layout preset

Success looks like:

- an agent can generate a believable street block, intersection, or district layout without manually wiring every road and sidewalk network

## Phase 7B. Interiors and Modular Space Toolkit

Problem:

- interior authoring needs room, corridor, and modular assembly logic that is different from exterior massing

Deliver:

- tools such as:
  - `interior.generate_floorplan`
  - `interior.build_corridor_system`
  - `interior.populate_rooms`
  - `interior.place_doors_and_stairs`
  - `interior.decorate_room`
- modular kits for walls, trim, ceilings, fixtures, doors, frames, and props
- layout rules for circulation, spacing, and room-type variation
- modular procedural systems that derive repeated room or corridor structure from rules instead of individual placement
- interior scaffolds that can be pushed toward different typologies such as residential, institutional, or industrial spaces through rule changes

Success looks like:

- an agent can build a coherent interior level, hallway system, or room set with modular consistency and usable variation

## Phase 7C. Industrial and Mechanical Environment Toolkit

Problem:

- industrial spaces need route-based systems, supports, paneling, and kitbash logic that is currently too manual

Deliver:

- tools such as:
  - `industrial.route_pipes`
  - `industrial.build_plant_module`
  - `industrial.place_catwalks`
  - `industrial.add_supports`
  - `mech.generate_greeble_pass`
- templates for pipes, ducts, vents, tanks, ladders, braces, and hard-surface detail passes
- rules for clearance, repetition control, and structural support logic
- route- and rule-driven procedural systems instead of manually placed runs of repeated industrial parts
- mechanical-system scaffolds that let agents define different industrial design languages rather than one canned kitbash look

Success looks like:

- an agent can produce convincing industrial or sci-fi mechanical spaces without hand-authoring every network branch

## Phase 7D. Natural Formations, Water, and Shoreline Toolkit

Problem:

- landscapes need terrain, geology, water, and shoreline tools beyond forest scattering alone

Deliver:

- tools such as:
  - `nature.generate_cliff`
  - `nature.carve_cave_network`
  - `nature.build_river_corridor`
  - `water.generate_river`
  - `water.build_shoreline`
  - `water.scatter_riparian_zone`
- reusable systems for cliffs, caves, rock layers, riverbeds, coastlines, wetlands, and erosion zones
- biome and water-edge integration helpers
- terrain and shoreline systems driven by masks, fields, and attributes instead of direct point-by-point scene dressing
- natural-environment scaffolds that let agents define different ecological or geological rule sets instead of invoking a fixed landscape macro

Success looks like:

- an agent can create a full natural setting with landform logic, water interaction, and believable environmental transitions

## Phase 7E. Weathering, Damage, and Set-Dressing Toolkit

Problem:

- convincing worlds need story and age, not just clean geometry and baseline materials

Deliver:

- tools such as:
  - `aging.apply_weathering`
  - `damage.add_structural_distress`
  - `growth.add_overgrowth_pass`
  - `setdress.populate_encampment`
  - `setdress.decorate_ruin`
  - `setdress.story_clutter_pass`
- reusable detail systems for grime, rust, cracks, leaks, overgrowth, debris, props, and narrative clutter
- controls for damage level, occupancy, neglect, and storytelling density
- layered transformation systems that modify environments procedurally rather than manually decorating each asset instance
- style and storytelling transformation scaffolds rather than hardwired “make it abandoned” output recipes

Success looks like:

- an agent can transform a clean procedural set into a believable lived-in, damaged, abandoned, or story-rich environment

## Phase 7F. Shot Assembly, Review, and Publish Toolkit

Problem:

- building environments is not enough; agents also need to compose, review, and publish them as scenes and presentations

Deliver:

- tools such as:
  - `layout.assemble_establishing_shot`
  - `layout.create_fore_mid_back_layers`
  - `layout.optimize_for_camera`
  - `publish.asset_turntable`
  - `publish.generate_preview_set`
  - `publish.export_scene_bundle`
- camera and layout helpers for composition, focal hierarchy, and visibility zones
- review templates for stills, turntables, contact sheets, and lookdev presentation
- publish templates for preview packages, review bundles, and delivery-ready exports

Success looks like:

- an agent can assemble a shot-ready scene, create presentation outputs, and package deliverables with minimal manual cleanup

## 4. Recommended Sequence

1. urban, roads, and infrastructure toolkit
2. interiors and modular space toolkit
3. industrial and mechanical environment toolkit
4. natural formations, water, and shoreline toolkit
5. weathering, damage, and set-dressing toolkit
6. shot assembly, review, and publish toolkit

## 5. Design Principles

- prefer scene-scale semantic tools over thin wrappers around individual nodes
- keep all generated systems inspectable and editable through the underlying Houdini graph
- favor reusable templates and rule systems over one-off macros
- support storytelling and presentation, not just geometry generation
- make layout, lookdev, and publish outputs part of the authoring loop
- preserve the phase-six system-first philosophy: agents should design procedural scene logic, not directly author large counts of final placements
- treat scene templates as starting grammars that agents can reshape, not fixed environment presets

## 6. Success Criteria

This phase is successful when:

- an agent can assemble a procedural city block, interior set, industrial bay, or natural environment from high-level intent
- environments can be aged, damaged, and dressed with story-aware detail layers
- scenes can be composed for review and packaged for presentation or delivery
- the system feels capable of environment and shot building, not just asset building
- the resulting Houdini graphs remain compact, parameterized, and recognizably procedural rather than sprawling collections of explicit repeated placements
- the same toolkits can be steered toward different worldbuilding aesthetics because the agent is authoring scene rules and grammars rather than invoking rigid hardcoded scene macros
