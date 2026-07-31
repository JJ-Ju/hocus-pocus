# HocusPocus Phase 5.6 Engineering Tracker

Status: active

Source roadmap: `docs/phase5.6roadmap.md`

Branch: `codex/phase5.6`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P5.6-M1 Public tool-surface consolidation
2. P5.6-M2 Generic node discovery and low-level authoring
3. P5.6-M3 Graph-layer promotion
4. P5.6-M4 Relational modeling and assembly validation
5. P5.6-M5 Documentation and migration

## P5.6-M1. Public Tool-Surface Consolidation

Status: not started

Goal:

- reduce fragmentation in the default public tool list and make the canonical workflow easier to understand

Tasks:

- [ ] Audit the current public tool list and classify each tool as keep, merge, hide, or deprecate.
- [ ] Define the canonical public families:
  - session or scene
  - node
  - parm
  - graph
  - material
  - render/export
  - PDG/USD/HDA/dependency/package
  - relational modeling
- [ ] Hide or de-emphasize thin wrappers that do not add enough leverage over the generic authoring flow.
- [ ] Ensure metadata clearly marks any remaining advanced or compatibility tools.

Done when:

- the default public tool count is materially smaller than the current `97`
- the public surface reads like a coherent API rather than a grab bag of helpers

Manual smoke:

- run `tools/list`
- confirm the default public surface is smaller and easier to scan
- verify the major workflows are still possible through the kept tools

## P5.6-M2. Generic Node Discovery and Low-Level Authoring

Status: not started

Goal:

- let agents discover valid node types and author them without guessing

Tasks:

- [ ] Implement `node_types.list`.
- [ ] Implement `node_types.get_info`.
- [ ] Implement `node_types.list_compatible` or equivalent category/task discovery.
- [ ] Implement `parm.set_many`.
- [ ] Implement `parm.set_many_expressions`.
- [ ] Ensure node discovery covers at least:
  - SOP
  - OBJ
  - LOP
  - TOP
  - MAT
  - DOP

Done when:

- an agent can discover, inspect, create, and configure common node types without trial-and-error probing

Manual smoke:

- discover SOP node types
- inspect a wrangle, boolean, and copy-to-points node type
- create one discovered node and set multiple parms in one call

## P5.6-M3. Graph-Layer Promotion

Status: not started

Goal:

- make the graph layer the main structural reasoning surface for the server

Tasks:

- [ ] Audit the current graph tools and resources for missing structural reads.
- [ ] Add any missing graph-backed reads needed for system authoring, such as branch-level geometry/bbox or stronger dependency views.
- [ ] Improve graph metadata and docs so agents naturally reach for the graph layer first.
- [ ] Ensure graph refresh or validity state is easy to inspect.

Done when:

- graph tools and resources are the obvious first choice for structural reasoning
- many one-off structural reads become unnecessary

Manual smoke:

- inspect a procedural branch using graph resources and graph query tools
- confirm the same task would require fewer calls than the older per-node approach

## P5.6-M4. Relational Modeling and Assembly Validation

Status: not started

Goal:

- reduce dependence on raw absolute-value placement for procedural assembly

Tasks:

- [ ] Implement `model.get_bbox`.
- [ ] Implement `model.get_planes`.
- [ ] Implement `model.snap_to_face`.
- [ ] Implement `model.align_to_plane`.
- [ ] Implement `model.create_reference_plane`.
- [ ] Implement `model.validate_contacts`.

Done when:

- agents can place architectural or hard-surface parts relative to shared faces and planes instead of repeated manual offsets
- the toolkit can detect common assembly failures such as gaps, near-misses, floating pieces, and penetrations

Manual smoke:

- assemble a small roof or façade system with face-relative placement
- run contact validation and verify suspicious offsets are reported

## P5.6-M5. Documentation and Migration

Status: not started

Goal:

- make the overhaul understandable and adoptable

Tasks:

- [ ] Update README and user manual for the canonical tool families.
- [ ] Add migration notes for hidden, deprecated, or merged tools.
- [ ] Add examples for:
  - node discovery
  - low-level authoring
  - graph-first reasoning
  - relational modeling

Done when:

- a user can understand the new canonical workflow without reading implementation files

Manual smoke:

- follow the docs to discover a node type, create it, set many parms, connect it, and validate assembly relationships

## 2. Immediate Next Actions

Recommended next implementation order:

1. P5.6-M1 public tool-surface consolidation
2. P5.6-M2 generic node discovery and low-level authoring
3. P5.6-M3 graph-layer promotion
4. P5.6-M4 relational modeling and assembly validation
5. P5.6-M5 documentation and migration

## 3. Session Log

### 2026-03-11

- Created phase 5.6 as the tool-surface and low-level authoring overhaul phase.
- Captured the target direction:
  - fewer fragmented tools
  - stronger node discovery
  - stronger graph-first reasoning
  - relational modeling and assembly validation
  - a smaller, clearer canonical public surface
