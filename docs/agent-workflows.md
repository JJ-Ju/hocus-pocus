# HocusPocus Agent Workflows

This guide describes the intended tool-selection patterns for agents using HocusPocus.

## 1. Inspect a Scene Safely

Use this order:

1. `session.info`
2. `scene.get_summary`
3. `houdini://documents/scene`
4. `houdini://documents/network/{path}` for the network you care about
5. `document.query` only when you need targeted search across the current graph surface
6. `node.get`, `parm.list`, or `geometry.get_summary` only for targeted detail

Preferred pattern:

- start broad with scene and network documents
- avoid many single-node reads when a graph or resource snapshot will answer the question

## 2. Plan Before Mutating

Preferred tools:

- `document.checkout`
- `document.validate`
- `document.diff`
- `document.apply` with `mode = validate_only`

Use these before:

- structural graph changes
- multi-step node authoring
- batch graph updates that are hard to inspect mentally

If the desired result spans multiple changes, prefer:

- document checkout plus document apply

over many independent low-level calls.

## 3. Build Node Networks

Use this order:

1. high-level semantic tool if it exists
2. `document.checkout`
3. edit the network document JSON
4. `document.validate`
5. `document.apply`
6. low-level node and parm tools only when a workflow is not covered yet

Preferred tools by layer:

- semantic:
  - `scene.create_turntable_camera`
  - `model.create_house_blockout`
- document:
  - `document.checkout`
  - `document.validate`
  - `document.diff`
  - `document.apply`
- low-level:
  - `node.create`
  - `node.connect`
  - `parm.set`
  - `node.set_flags`

Placement note:

- new node tiles are automatically placed on the managed integer grid
- agents should not micromanage tile positions unless layout itself matters

### HocusScript structural preview

`document.compile_source` accepts `.hocus` source text and currently performs only offline parsing, structural validation, deterministic formatting, and GraphSpec generation.

Rules for the current preview:

- pass source contents rather than a server-side file path
- keep `strict = true` for checked-in files so `hocus 0.1;` is required
- inspect `diagnostics`, `formattedSource`, and `graphSpec`
- require `readyForDocumentLowering = false` and `readyForApply = false`
- do not treat a valid structural preview as a Houdini-aware or applyable plan

Catalog resolution, network-document lowering, and immutable plan application remain gated by the HocusScript roadmap.

## 4. Handle Long-Running Work

Long-running tools are non-blocking:

- `cook.node`
- `render.rop`
- `export.alembic`
- `export.usd`
- `pdg.cook`

Preferred task loop:

1. call the tool
2. read `houdini://tasks/{task_id}`
3. read `houdini://tasks/{task_id}/log` if needed
4. call `task.cancel` if needed

Do not assume partial outputs are absent after cancellation.

## 5. Use Resources to Save Round Trips

Prefer resources when you want state snapshots:

- `houdini://documents/scene`
- `houdini://documents/network/{path}`
- `houdini://documents/checkouts/{checkout_id}`
- `houdini://documents/diagnostics/{checkout_id}`
- `houdini://nodes/{path}`
- `houdini://nodes/{path}/parms`
- `houdini://nodes/{path}/geometry-summary`
- `houdini://tasks/recent`
- `houdini://scene/events`
- `houdini://usd/stage/{path}`
- `houdini://pdg/graph/{path}`

Preferred pattern:

- read one resource
- only call follow-up tools for mutation or narrow detail

## 6. Validate Before Expensive Work

Use:

- `render.preflight` before `render.rop`
- `scene.validate` for broad scene checks
- `graph.check_errors` for graph-local problems
- `parm.find_broken_refs` when channel references may be stale
- `usd.validate_stage` before export or Solaris handoff

## 7. Packaging and Handoff

Use:

1. `dependency.scan_scene`
2. `package.preview_scene`
3. `package.create_scene_package`

If the goal is exchange rather than full package handoff:

- use `export.alembic` or `export.usd`

## 8. When to Prefer High-Level Domain Tools

Prefer specialized tools when they exist because they encode Houdini intent:

- use `hda.*` for asset-library and definition workflows
- use `usd.*` and `lop.*` for Solaris authoring and inspection
- use `pdg.*` for TOP graph behavior instead of generic node reads
- use `material.*` for material creation and assignment

This reduces graph reconstruction work and gives more stable results.
