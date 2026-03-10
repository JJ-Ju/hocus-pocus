# HocusPocus Phase 4 Engineering Tracker

Status: active

Source roadmap: `docs/phase4roadmap.md`

Branch: `codex/phase4`

Tracking rule:

- only mark tasks complete when code exists and the behavior is manually validated

## 1. Milestones

1. P4-M1 HDA and asset workflows
2. P4-M2 Dependency and cache discovery
3. P4-M3 Render graph and lookdev helpers
4. P4-M4 Scene packaging and archival
5. P4-M5 Solaris production workflows
6. P4-M6 PDG production orchestration

## P4-M1. HDA and Asset Workflows

Status: not started

Goal:

- make HDAs and asset libraries first-class automation targets

Tasks:

- [ ] Implement HDA definition inspection for node instances and library definitions.
- [ ] Implement HDA library listing and active-definition resolution.
- [ ] Implement parm-promotion and interface inspection helpers.
- [ ] Add install/uninstall or enable/disable library controls where safe.
- [ ] Return stable summaries for asset definitions, sections, versions, and instance relationships.

Done when:

- an agent can inspect which HDA definition a node instance is using
- an agent can inspect asset libraries and definition metadata
- asset interface and parm-promotion state is visible through MCP

Manual smoke:

- inspect an HDA instance and its active definition
- inspect at least one installed asset library and promoted parms

## P4-M2. Dependency and Cache Discovery

Status: not started

Goal:

- expose textures, references, caches, and output dependencies as first-class scene data

Tasks:

- [ ] Implement a scene dependency scan across file parms, USD references, and render/export nodes.
- [ ] Detect missing files and non-approved output/input paths.
- [ ] Implement safe dependency repath tools.
- [ ] Add cache topology summaries for common file-cache patterns.
- [ ] Add dependency resources suitable for whole-scene reporting.

Done when:

- an agent can ask “what files does this scene depend on?” and get a structured answer
- missing and policy-violating paths are visible
- common repath operations can be executed through MCP

Manual smoke:

- scan a scene with known file references
- repath a test dependency and verify the scene updates correctly

## P4-M3. Render Graph and Lookdev Helpers

Status: not started

Goal:

- improve preflight, inspection, and authoring around shot rendering workflows

Tasks:

- [ ] Implement render graph inspection for ROP chains and their upstream dependencies.
- [ ] Add render output and AOV inspection helpers where node types support it.
- [ ] Add camera/light/lookdev helper tools for common shot setup.
- [ ] Add render preflight validation that catches output-path and dependency issues before launch.
- [ ] Add render resources or summaries that pair well with existing task payloads.

Done when:

- an agent can inspect what a render node depends on and what it will write
- common render setup helpers reduce low-level node churn
- render preflight catches obvious failures before render starts

Manual smoke:

- inspect a simple render graph
- run render preflight on a valid and invalid test setup

## P4-M4. Scene Packaging and Archival

Status: not started

Goal:

- support practical handoff and publish workflows from inside the MCP surface

Tasks:

- [ ] Implement scene dependency collection previews.
- [ ] Implement package/archive execution to a validated destination.
- [ ] Include dry-run mode and collected-file reporting.
- [ ] Reuse dependency-scan results instead of re-discovering files ad hoc.

Done when:

- an agent can preview and execute a scene package workflow through MCP
- package results clearly report what was collected and what was skipped

Manual smoke:

- dry-run a package of a scene with external dependencies
- execute a package to a test destination

## P4-M5. Solaris Production Workflows

Status: not started

Goal:

- deepen Solaris inspection and validation beyond the current first-pass authoring tools

Tasks:

- [ ] Implement stage or layer-stack summaries.
- [ ] Implement prim-query helpers for authored prim paths and references.
- [ ] Implement material-binding inspection.
- [ ] Add variant/reference diagnostics and save-path validation summaries.
- [ ] Add Solaris resources that complement the existing graph resources.

Done when:

- an agent can inspect a Solaris network at the stage/layer/prim level
- binding, variant, and reference issues are visible without manual UI drilling

Manual smoke:

- inspect a Solaris stage with at least one reference and one variant authoring node
- validate save-path and binding diagnostics

## P4-M6. PDG Production Orchestration

Status: not started

Goal:

- make PDG useful for more than simple graph cooking

Tasks:

- [ ] Add scheduler inspection and scheduler-aware summaries.
- [ ] Add work-item log retrieval where APIs allow it.
- [ ] Implement retry or requeue controls where PDG APIs support them safely.
- [ ] Add stronger node-level cook/result summaries.
- [ ] Add PDG resources for graph state, work items, and logs.

Done when:

- an agent can inspect scheduler and work-item behavior beyond coarse graph state
- common orchestration actions do not require dropping to the Houdini UI

Manual smoke:

- inspect a scheduler and work-item logs on a simple TOP network
- retry or requeue supported work through MCP

## 2. Immediate Next Actions

Recommended next implementation order:

1. P4-M1 HDA and asset workflows
2. P4-M2 Dependency and cache discovery
3. P4-M3 Render graph and lookdev helpers

These are the highest-value production workflow gaps after phase 3.

## 3. Session Log

### 2026-03-10

- Created the phase-four roadmap around asset, dependency, render, packaging, Solaris, and PDG production workflows.
- Chose HDA workflows and dependency discovery as the highest-value next slice after the completed scene-graph and PDG/Solaris foundations from phase 3.
- Created the phase-four engineering tracker with milestone-level tasks, done criteria, and manual smoke gates.
