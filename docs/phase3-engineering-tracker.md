# HocusPocus Phase 3 Engineering Tracker

Status: active

Source roadmap: `docs/phase3roadmap.md`

Branch: `codex/phase3`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P3-M1 Live scene graph index
2. P3-M2 Query tools and graph views
3. P3-M3 Graph resources and snapshots
4. P3-M4 Diff and patch planning
5. P3-M5 PDG/TOPs automation
6. P3-M6 LOP/USD authoring
7. P3-M7 Event streaming and validation

## P3-M1. Live Scene Graph Index

Status: complete

Goal:

- build a fast, correct scene-structure cache that agents can query without reconstructing the graph themselves

Tasks:

- [x] Define the internal graph model for nodes, parms, edges, flags, materials, and output relationships.
- [x] Build an index keyed by node path, node type, category, and revision.
- [x] Track graph edges for inputs, outputs, display nodes, render nodes, and object ownership.
- [x] Add invalidation and refresh behavior tied to scene monitor revisions.
- [x] Expose server-side stats for cache size, revision, and refresh timing.

Done when:

- the server can materialize a scene graph snapshot from the live session
- refreshes are revision-aware instead of rebuilding blindly on every read
- cache state is inspectable for debugging

Manual smoke:

- create and delete nodes in Houdini and verify the indexed graph refreshes correctly
- modify connections, display nodes, and materials and verify the cache reflects them

## P3-M2. Query Tools and Graph Views

Status: complete

Goal:

- let agents ask direct structural questions instead of stitching low-level reads together

Tasks:

- [x] Implement `graph.query` with basic filters on path, type, category, and flags.
- [x] Implement `graph.find_upstream`.
- [x] Implement `graph.find_downstream`.
- [x] Implement `graph.find_by_type`.
- [x] Implement `graph.find_by_flag`.
- [x] Return stable structured graph entities and traversal edges.

Done when:

- agents can answer common graph questions through dedicated tools
- graph-query results are easier to consume than raw node listings

Manual smoke:

- query a SOP chain and verify upstream/downstream traversal
- query by node type and display or render flags

## P3-M3. Graph Resources and Snapshots

Status: complete

Goal:

- expose whole-scene and whole-subgraph state as durable resources

Tasks:

- [x] Add a full-scene graph snapshot resource.
- [x] Add a subgraph snapshot resource rooted at a node path.
- [x] Add dependency-edge resources.
- [x] Add expression and parameter-reference resources.
- [x] Add material-assignment and render/export topology resources.

Done when:

- an agent can load a high-signal scene snapshot with a single resource read
- graph resources cover both structure and the most important dependency relationships

Manual smoke:

- read a whole-scene snapshot on a non-trivial scene
- read a subgraph snapshot and verify edge and parm-reference data

## P3-M4. Diff and Patch Planning

Status: complete

Goal:

- let agents preview and compare structural edits before mutating the scene

Tasks:

- [x] Implement `scene.diff`.
- [x] Implement `graph.diff_subgraph`.
- [x] Implement `graph.plan_edit`.
- [x] Implement `graph.apply_patch`.
- [x] Return created, removed, rewired, and changed entities in a normalized diff format.
- [x] Support dry-run mode for patch application.

Done when:

- agents can compare intended graph changes to the current graph before mutation
- patch payloads can be previewed and then applied through the same format

Manual smoke:

- diff two versions of a SOP graph and verify rewires and parm changes are captured
- apply a dry-run patch and then the real patch and compare the resulting graph

## P3-M5. PDG/TOPs Automation

Status: complete

Goal:

- add first-class automation coverage for Houdini’s task-graph and orchestration workflows

Tasks:

- [x] Implement `pdg.list_graphs`.
- [x] Implement `pdg.cook`.
- [x] Implement `pdg.get_workitems`.
- [x] Implement `pdg.cancel`.
- [x] Implement `pdg.get_results`.
- [x] Represent PDG status and outputs in task-friendly payloads.

Done when:

- an agent can discover, cook, inspect, and cancel PDG networks through MCP
- work-item and result data are inspectable without manual UI drilling

Manual smoke:

- cook a simple TOP network
- inspect work items and cancel a running cook

## P3-M6. LOP/USD Authoring

Status: complete

Goal:

- move beyond USD export into real Solaris authoring workflows

Tasks:

- [x] Implement `lop.create_node`.
- [x] Implement `usd.assign_material`.
- [x] Implement `usd.set_variant`.
- [x] Implement `usd.add_reference`.
- [x] Implement `usd.create_layer_break`.
- [x] Add USD-aware summaries for authored nodes and affected prim paths.

Done when:

- an agent can build and modify useful Solaris graphs without dropping to raw node surgery
- USD authoring results are inspectable through MCP reads and graph resources

Manual smoke:

- build a simple Solaris chain and assign a material
- add a reference and switch a variant set through MCP

## P3-M7. Event Streaming and Validation

Status: complete

Goal:

- reduce polling and catch common graph issues before they turn into failed work

Tasks:

- [x] Add event/subscription support where transport and runtime make it feasible.
- [x] Implement `scene.validate`.
- [x] Implement `graph.check_errors`.
- [x] Implement `parm.find_broken_refs`.
- [x] Add validation notes for render, export, and USD graph readiness.

Done when:

- clients can observe scene changes with less polling
- agents can ask for graph-health diagnostics before mutating or rendering

Manual smoke:

- observe scene change events during live edits
- run validation against intentionally broken parm refs or graph wiring

## 2. Immediate Next Actions

Recommended next implementation order:

Phase 3 is complete.

The next work should be organized as a new phase.

## 3. Session Log

### 2026-03-10

- Created the phase-three roadmap focused on scene visibility, graph queries, diff-first workflows, PDG, and Solaris authoring.
- Chose a live in-memory indexed scene graph as the initial direction instead of starting with a persistent graph database.
- Created the phase-three engineering tracker with concrete milestones, done criteria, and manual smoke gates.
- Implemented and live-validated P3-M1 against Houdini 21.0:
  - added a revision-aware in-memory scene graph cache with node, parm, edge, material, and parameter-reference indexing
  - added explicit graph invalidation for graph-affecting MCP mutation tools plus a short freshness fallback for direct Houdini edits
  - exposed cache stats through `houdini://graph/index` and session/health payloads
- Implemented and live-validated P3-M2 against Houdini 21.0:
  - `graph.query`, `graph.find_upstream`, `graph.find_downstream`, `graph.find_by_type`, and `graph.find_by_flag` work against the indexed scene graph
  - traversal responses return stable node payloads and structural edges
- Implemented and live-validated P3-M3 against Houdini 21.0:
  - added `houdini://graph/scene`
  - added `houdini://graph/subgraph/{path}`
  - added `houdini://graph/dependencies/{path}`
  - added `houdini://graph/references/{path}`
  - graph payloads were hardened to remain JSON-safe in live Houdini sessions
- Implemented and live-validated P3-M4 against Houdini 21.0:
  - `scene.diff` and `graph.diff_subgraph` report created nodes, changed nodes, changed parms, and structural edge deltas
  - `graph.plan_edit` simulates batch-style graph edits without mutation
  - `graph.apply_patch` supports `dry_run = true` and transactional execution through the live batch-edit path
- Implemented and live-validated P3-M5 against Houdini 21.0:
  - `pdg.list_graphs` discovers TOP networks
  - `pdg.cook` runs as a non-blocking task with task outcome and work-item state history
  - `pdg.get_workitems` and `pdg.get_results` expose work-item state and result-data payloads
  - a simple `genericgenerator` TOP graph cooked to `CookedSuccess` work items through MCP
- Implemented and live-validated P3-M6 against Houdini 21.0:
  - `lop.create_node` created a Solaris cube node under `/stage`
  - `usd.assign_material`, `usd.set_variant`, `usd.add_reference`, and `usd.create_layer_break` each authored the expected Solaris nodes and parameters
  - authored node summaries expose the key prim, material, reference, and layer-save parameters
- Implemented and live-validated P3-M7 against Houdini 21.0:
  - `scene.events_recent` and `houdini://scene/events` provide a lightweight event feed over the current HTTP transport
  - `parm.find_broken_refs` detects missing absolute parameter references
  - `graph.check_errors` surfaces graph-local broken references
  - `scene.validate` summarizes broken references, USD save-path issues, and output-path policy issues
