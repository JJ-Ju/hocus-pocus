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

Status: complete

Goal:

- make HDAs and asset libraries first-class automation targets

Tasks:

- [x] Implement HDA definition inspection for node instances and library definitions.
- [x] Implement HDA library listing and active-definition resolution.
- [x] Implement parm-promotion and interface inspection helpers.
- [x] Add install/uninstall or enable/disable library controls where safe.
- [x] Return stable summaries for asset definitions, sections, versions, and instance relationships.

Done when:

- an agent can inspect which HDA definition a node instance is using
- an agent can inspect asset libraries and definition metadata
- asset interface and parm-promotion state is visible through MCP

Manual smoke:

- inspect an HDA instance and its active definition
- inspect at least one installed asset library and promoted parms

## P4-M2. Dependency and Cache Discovery

Status: complete

Goal:

- expose textures, references, caches, and output dependencies as first-class scene data

Tasks:

- [x] Implement a scene dependency scan across file parms, USD references, and render/export nodes.
- [x] Detect missing files and non-approved output/input paths.
- [x] Implement safe dependency repath tools.
- [x] Add cache topology summaries for common file-cache patterns.
- [x] Add dependency resources suitable for whole-scene reporting.

Done when:

- an agent can ask “what files does this scene depend on?” and get a structured answer
- missing and policy-violating paths are visible
- common repath operations can be executed through MCP

Manual smoke:

- scan a scene with known file references
- repath a test dependency and verify the scene updates correctly

## P4-M3. Render Graph and Lookdev Helpers

Status: complete

Goal:

- improve preflight, inspection, and authoring around shot rendering workflows

Tasks:

- [x] Implement render graph inspection for ROP chains and their upstream dependencies.
- [x] Add render output and AOV inspection helpers where node types support it.
- [x] Add camera/light/lookdev helper tools for common shot setup.
- [x] Add render preflight validation that catches output-path and dependency issues before launch.
- [x] Add render resources or summaries that pair well with existing task payloads.

Done when:

- an agent can inspect what a render node depends on and what it will write
- common render setup helpers reduce low-level node churn
- render preflight catches obvious failures before render starts

Manual smoke:

- inspect a simple render graph
- run render preflight on a valid and invalid test setup

## P4-M4. Scene Packaging and Archival

Status: complete

Goal:

- support practical handoff and publish workflows from inside the MCP surface

Tasks:

- [x] Implement scene dependency collection previews.
- [x] Implement package/archive execution to a validated destination.
- [x] Include dry-run mode and collected-file reporting.
- [x] Reuse dependency-scan results instead of re-discovering files ad hoc.

Done when:

- an agent can preview and execute a scene package workflow through MCP
- package results clearly report what was collected and what was skipped

Manual smoke:

- dry-run a package of a scene with external dependencies
- execute a package to a test destination

## P4-M5. Solaris Production Workflows

Status: complete

Goal:

- deepen Solaris inspection and validation beyond the current first-pass authoring tools

Tasks:

- [x] Implement stage or layer-stack summaries.
- [x] Implement prim-query helpers for authored prim paths and references.
- [x] Implement material-binding inspection.
- [x] Add variant/reference diagnostics and save-path validation summaries.
- [x] Add Solaris resources that complement the existing graph resources.

Done when:

- an agent can inspect a Solaris network at the stage/layer/prim level
- binding, variant, and reference issues are visible without manual UI drilling

Manual smoke:

- inspect a Solaris stage with at least one reference and one variant authoring node
- validate save-path and binding diagnostics

## P4-M6. PDG Production Orchestration

Status: complete

Goal:

- make PDG useful for more than simple graph cooking

Tasks:

- [x] Add scheduler inspection and scheduler-aware summaries.
- [x] Add work-item log retrieval where APIs allow it.
- [x] Implement retry or requeue controls where PDG APIs support them safely.
- [x] Add stronger node-level cook/result summaries.
- [x] Add PDG resources for graph state, work items, and logs.

Done when:

- an agent can inspect scheduler and work-item behavior beyond coarse graph state
- common orchestration actions do not require dropping to the Houdini UI

Manual smoke:

- inspect a scheduler and work-item logs on a simple TOP network
- retry or requeue supported work through MCP

## 2. Immediate Next Actions

Phase 4 is complete.

Recommended next implementation order:

1. Merge the phase-four branch and keep the installed package aligned with the committed branch state.
2. Fold the automatic grid-placement refinements into the next public release notes because they materially improve day-to-day agent usability.
3. Plan the next production slice around deeper render or asset-pipeline workflows if more coverage is needed.

## 3. Session Log

### 2026-03-10

- Created the phase-four roadmap around asset, dependency, render, packaging, Solaris, and PDG production workflows.
- Chose HDA workflows and dependency discovery as the highest-value next slice after the completed scene-graph and PDG/Solaris foundations from phase 3.
- Created the phase-four engineering tracker with milestone-level tasks, done criteria, and manual smoke gates.
- Completed `P4-M1` with HDA library inspection, definition/instance/interface reads, library install/reload controls, digital-asset creation from a live node, parm promotion, and definition version updates.
- Fixed the live UI-thread dispatcher path to use `hdefereval.executeInMainThreadWithResult(...)` in graphical Houdini so asset-authoring operations no longer time out behind `postEventCallback` queue stalls.
- Live-validated the HDA flow on a disposable object asset saved to `C:/Users/jujun/Documents/houdini21.0/hocuspocus/output/hdas/p4_hda_test.hda`, including tuple-aware parm promotion and persistent internal channel references after relocking the asset definition.
- Completed `P4-M2` with whole-scene dependency scanning, dependency resources, cache topology summaries, and safe dependency repath tools with dry-run and live apply coverage.
- Completed `P4-M3` with render graph inspection, render output/AOV inspection, render preflight, a render-graph resource, and a three-point light rig helper.
- Live-validated the new dependency and render helpers on a disposable geometry and Geometry ROP setup under `/obj/p4_dep_geo1` and `/out/p4_dep_geo_rop1`, including a blocking preflight failure for a missing SOP path and successful creation of an object-light three-point rig.
- Completed `P4-M4` with scene-package preview and package creation tools, plus a default package-preview resource for whole-scene collection checks.
- Fixed package collection to skip directories explicitly so only real files are copied into archives or package directories.
- Live-validated packaging on a disposable file-SOP dependency under `/obj/p4_pack_geo1`, including preview, dry-run, zip-package creation, and directory-package creation with manifest output.
- Completed `P4-M5` with Solaris production inspection and validation tools, including `usd.stage_summary`, `usd.inspect_prim`, `usd.inspect_material_bindings`, `usd.validate_stage`, and the `houdini://usd/stage/{path}` resource.
- Fixed `usd.inspect_material_bindings` to traverse the composed stage safely and filter by prim-path prefix instead of traversing from a brittle candidate prim handle.
- Live-validated the Solaris production workflow on `/stage/p4_stage_layerbreak1`, including stage summary, prim inspection for `/usd_ref_test`, material-binding inspection under `/p4_stage_cube1`, stage validation, and dynamic resource reads.
- Completed `P4-M6` with PDG production orchestration tools, including scheduler inspection, work-item log retrieval, retry or redirty controls, graph-state inspection, and the `houdini://pdg/graph/{path}` resource.
- Live-validated the PDG production workflow on `/tasks/p4_topnet1`, including scheduler inspection, graph-state reads, empty-log handling on a simple generator, safe retry or dirty behavior, and PDG resource reads.
