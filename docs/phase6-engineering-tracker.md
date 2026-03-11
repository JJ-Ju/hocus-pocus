# HocusPocus Phase 6 Engineering Tracker

Status: active

Source roadmap: `docs/phase6roadmap.md`

Branch: `codex/phase6`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P6-M1 Procedural building and hard-surface toolkit
2. P6-M2 Material and lookdev authoring macros
3. P6-M3 Terrain, forest, and scatter toolkit
4. P6-M4 Simulation setup toolkit
5. P6-M5 Visual critique and iteration loop
6. P6-M6 Reusable recipes and style profiles

## P6-M1. Procedural Building and Hard-Surface Toolkit

Status: in progress

Goal:

- let agents author tower, façade, and hard-surface building forms through system-building primitives and scaffold patterns instead of misleading canned macros
- enforce a system-first approach where tools build reusable procedural generator graphs instead of large counts of explicitly placed mesh nodes
- ensure the resulting surface behaves like generator scaffolds that agents can shape into different architectural styles, not fixed hardcoded outputs

Tasks:

- [x] Define the first semantic building tool slice and wire it into the MCP surface.
- [x] Live-validate a disposable building network in Houdini.
- [ ] Remove misleading canned building macros from the default tool surface.
- [ ] Replace asset-style building macros with scaffold-oriented helpers that support manual low-level graph authoring through the core toolkit.
- [ ] Refactor the building toolkit toward compact procedural graph patterns instead of explicit repeated mesh-node placement.
- [ ] Improve façade articulation beyond simple stacked massing and box detail.
- [ ] Introduce true building assembly systems such as envelope, slab, core, and façade modules that behave like a generator rather than direct geometry placement.
- [ ] Reframe building helpers as editable procedural scaffolds so the same system can be steered toward different architectural languages instead of a single canned tower outcome.

Done when:

- an agent can create a procedural tower blockout through scaffold-oriented tools and the lower-level node toolkit
- the generated network is inspectable and editable with the underlying node tools
- the resulting graph is recognizably a procedural building system rather than a large pile of hand-authored repeated SOP boxes
- the system exposes enough rule structure that an agent could plausibly steer it toward divergent architectural styles rather than only reproducing one fixed look

Manual smoke:

- generate a disposable tower under `/obj`
- add at least one façade or rooftop pass
- verify the display node updates and the network remains editable
- verify repeated style or authoring passes reuse or replace prior generated systems instead of continuously appending more explicit mesh nodes

## P6-M2. Material and Lookdev Authoring Macros

Status: not started

Goal:

- improve shader and material variation authoring beyond basic create or assign primitives

Tasks:

- [ ] Implement higher-level shader macros such as PBR and layered building material helpers.
- [ ] Add grouped or rule-based material assignment helpers.
- [ ] Add procedural breakup controls for wear, dirt, rust, or color variation.
- [ ] Return lookdev summaries that describe the resulting material stack and assignment logic.

Done when:

- an agent can create believable building or prop lookdev through semantic material tools

Manual smoke:

- author at least one layered building material
- apply it to a generated building network and verify the result

## P6-M3. Terrain, Forest, and Scatter Toolkit

Status: not started

Goal:

- expose semantic terrain and vegetation tools for authored-looking natural environments

Tasks:

- [ ] Implement a terrain-generation starting slice.
- [ ] Implement biome or scatter helpers.
- [ ] Add optimization-oriented instance or packed-primitive controls.
- [ ] Return summaries that describe species, density, and terrain masks.

Done when:

- an agent can build a first-pass forest or natural environment with semantic tools

Manual smoke:

- generate a terrain base and at least one vegetation layer

## P6-M4. Simulation Setup Toolkit

Status: not started

Goal:

- expose semantic destruction and simulation setup helpers for first-pass FX workflows

Tasks:

- [ ] Implement RBD prep helpers.
- [ ] Implement fracture or constraint helpers.
- [ ] Implement cache or solver setup helpers.
- [ ] Return summaries that expose the resulting sim graph and caches.

Done when:

- an agent can build a first-pass building collapse setup with less raw DOP graph planning

Manual smoke:

- prepare a simple destructible building and inspect the resulting sim network

## P6-M5. Visual Critique and Iteration Loop

Status: not started

Goal:

- support structured critique and revision loops instead of only first-pass generation

Tasks:

- [ ] Implement at least one structural repetition or density analysis tool.
- [ ] Implement at least one review capture helper.
- [ ] Return structured analysis outputs that can drive follow-up revisions.

Done when:

- an agent can generate, review, and revise a procedural asset in a closed loop

Manual smoke:

- analyze a generated asset and produce a review capture

## P6-M6. Reusable Recipes and Style Profiles

Status: not started

Goal:

- let agents reuse high-level authored patterns instead of rebuilding everything ad hoc

Tasks:

- [ ] Define a recipe registry format.
- [ ] Implement recipe listing and instancing helpers.
- [ ] Implement at least one building-oriented style profile.
- [ ] Return stable recipe and style metadata to clients.

Done when:

- an agent can instantiate a reusable recipe and then refine it with semantic tools

Manual smoke:

- instantiate a recipe and apply a style profile to a generated asset

## 2. Immediate Next Actions

Recommended next implementation order:

1. P6-M1 building massing and façade helpers
2. P6-M2 material and lookdev helpers
3. P6-M3 terrain and scatter helpers

These are the highest-value agent-authoring improvements after the completed platform and pipeline phases.

## 3. Session Log

### 2026-03-10

- Created the phase-six engineering tracker from the semantic asset-authoring roadmap.
- Chose a narrow first `P6-M1` slice: procedural tower massing plus follow-up façade and rooftop helpers.
- Implemented the first semantic building tools:
  - `building.generate_massing`
  - `building.add_structural_bands`
  - `building.add_rooftop_mech`
- Wired the building tools into MCP metadata with output summaries, examples, and failure notes.
- Live-validated the first building slice in Houdini on `/obj/tower_alpha1`, including tower massing, structural bands, rooftop mechanical detail, output geometry summary, and editable SOP-network structure.
- The next `P6-M1` slice should improve façade articulation so generated towers move beyond stacked box forms.
- Clarified the broader phase-six rule: the agent should be building procedural systems in Houdini, not directly generating large counts of explicit mesh nodes. Future slices should therefore favor copy, repeat, scatter, attribute, and parameter-driven graph logic over one-box-per-feature authoring.
- Clarified that even example generators should be treated as generator scaffolds and procedural grammar starting points, not as fixed baked asset rules.
