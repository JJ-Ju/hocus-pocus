# HocusPocus Agent Workflows

This guide describes the intended tool-selection patterns for agents using HocusPocus.

Connect through the client-owned `hocuspocus` stdio broker. Treat the localhost
HTTP endpoint as a private host hop: it disappears with Houdini, while the
broker remains connected and discovers the replacement host. If a mutation has
ambiguous delivery, reconcile its operation ID before doing anything else. See
the [durable transport contract](durable-mcp-transport.md).

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

1. use `object.create_geometry` when an empty scene has no SOP network yet
2. use a high-level semantic tool if one exists
3. otherwise call `document.checkout`
4. edit the returned network document JSON
5. call `document.validate`
6. call `document.apply`
7. use low-level node and parm tools only when a workflow is not covered yet

`object.create_geometry` is the narrow OBJ bootstrap boundary. It creates one
Geometry container under `/obj` and returns its resolved root path, checkout
metadata, and exact SOP working document inline when the bounded response fits.
Do not treat `/obj` itself as a writable SOP-shaped document.

If bootstrap delivery fails, HocusPocus normally retires the checkout and graph
admission before removing the object. A checkout-retirement, graph-retirement,
or live-node removal failure instead returns a typed recovery error and retains
the remaining state coherently; use its portable `rootPath`, `checkoutId`, and
`retainedState` for inspection or explicit cleanup.

Preferred tools by layer:

- semantic:
  - `object.create_geometry`
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

Discovery note:

- `node_types.list_compatible` accepts exactly one of `task` or `intent`
- `task` is the canonical enum shown in the tool schema
- `intent` accepts a bounded natural-language phrase and returns the resolved
  task and matched terms; ambiguous phrases return candidates instead of being
  guessed

Checkout note:

- `document.checkout` normally returns the exact working document inline
- `documentDelivery` always reports the document digest, byte length, delivery
  mode, and inline limit
- oversized documents use `documentDelivery.mode = resource` and retain
  `resourceUri`

Mutation note:

- read `grantedCapabilities` from `session.info` before choosing an authored
  code path
- inspect `requiredCapabilities`, `missingCapabilities`, and
  `capabilityReady` from validation or preview before apply
- treat node display/output flags as authored state; checkout `output_flag`
  edges are regenerated observations
- a failed document mutation returns `HOCUS755` only after exact rollback is
  verified; `HOCUS756` means the scope is quarantined for explicit recovery
- retain each returned operation ID; after ambiguous delivery, reconcile it
  through `session.get_operation` before issuing another mutation

HDA note:

- use `hda.promote_parm` with its default `preserve_source_value = true`
- use `hda.set_instance_parms` for public controls on a locked asset
- do not unlock HDA internals merely to edit an artist-facing value

### HocusScript native edit/apply loop

Prefer editing `.hocus` as a normal, Git-visible workspace file. When the host
user has approved the project, use the seven `source.*` tools with its opaque
`projectId`: describe/search/read/patch or export, then check/compile/navigate.
The server never exposes or accepts an ambient absolute project root through
MCP. Source edits do not bypass the document preview/plan/apply mutation lane.

The same files remain available to an IDE and the offline CLI/library:

```powershell
$env:PYTHONPATH = "python3.11libs"
python -m hocuspocus.hocusscript check hocus/asset.hocus --project D:/show/project
python -m hocuspocus.hocusscript format hocus/asset.hocus --project D:/show/project --write
python -m hocuspocus.hocusscript compile hocus/asset.hocus --project D:/show/project -o asset.bundle.json
```

The absolute project path belongs to the native compiler/editor and host-owned
workspace registry. MCP receives an opaque `projectId`, portable paths, source
or Bundle content, and digests; it never receives the physical root.

For a language-`0.2` project with external aliases, pass the complete exact alias/root mapping again to each mixed-root lock, check, or compile request. Repeat `--module-root`; quote the whole value when the absolute path contains spaces:

```powershell
$studio = "studio=D:/Studio Libraries/Hocus"
$materials = "materials=E:/Shared Hocus/Materials"
python -m hocuspocus.hocusscript lock hocus/asset.hocus --update --project D:/show/project --expected-lock-digest "sha256:<exact-current-lock-digest>" --module-root $studio --module-root $materials
python -m hocuspocus.hocusscript check hocus/asset.hocus --project D:/show/project --module-root $studio --module-root $materials
python -m hocuspocus.hocusscript compile hocus/asset.hocus --project D:/show/project --module-root $studio --module-root $materials -o asset.bundle.json
```

Do not infer roots from lock records, create a module-root environment variable,
expand `~` or environment syntax, or persist the mapping. Mixed lock
publication requires a valid existing v3 lock and its exact digest. `format`
and native `write-export` do not accept module roots. External-aware completion
and go-to-definition are also available through `source.project.navigate` when
the host has approved every external alias; the native Python `complete_mixed_*`
and `definition_mixed_*` APIs remain available to editor integrations.

For a supported live SOP network, call `document.export_source` with `root_path`. Save the returned JSON response outside Houdini and let the native CLI validate and create the selected project file:

```powershell
python -m hocuspocus.hocusscript write-export export-response.json hocus/asset.hocus --project D:/show/project
```

Creation is exclusive. To intentionally replace an existing file through the
native CLI, pass its current `sha256:...` digest as `--expected-digest`. Through
MCP, use `source.file.write_export` under an approved source-write grant; it
validates the export handoff and uses the same exact-digest publication model.
Never use a guessed digest.

The complete loop is:

1. edit the `.hocus` file directly or through `source.file.apply_patch`
2. run `check`, `format`, and `compile` through `source.project.build`, or use
   the native CLI against the explicitly selected project
3. send bundle content to `document.preview_bundle` and inspect the diff
4. call `document.plan_bundle`, then `document.apply_plan` with its guarded identity/revisions
5. cook and capture the resulting asset
6. revise the same source file and repeat

For a production build, keep the graph loop unchanged and add one final
`production.asset.qualify` call after the explicit cook. Supply the strict asset
contract, already-cooked observation, baseline and candidate provenance,
platform metrics/budget, numeric and visual comparisons, and artist-override
evidence. Require `readyForPackaging` before packaging and `readyForPublish`
before publication, but obtain those authoritative decisions from the private
installed runner and detached verifier. The public operation always returns
advisory `content_only` output with both readiness flags false, even with
`review_production`; it never cooks, writes, publishes, or mints authority on
the agent's behalf. Read the exact schemas from
`hocuspocus://schemas/...` or their byte-identical
`houdini://production/schema/...` aliases instead of guessing carrier fields.

`document.compile_source`, `document.format_source`, and
`document.complete_source` remain content-only unsaved-buffer conveniences.
Completion is backed by the live catalog; these `document.*` tools do not read
project files or external module roots. For saved projects, H6 exposes exactly
seven separately authorized `source.*` operations over user-approved roots:
describe, search, read, apply patch, write export, build, and navigate. Clients
select projects by opaque `projectId`, never physical path. Exact flat Bundle
`0.2`, module Bundle `0.3`, control Bundle `0.4`, and value Bundle `0.5`
document/live handling remains content-based, so source workspace access does
not change the contract of the existing `document.*` tools or bypass
preview/plan/apply.

Rules for the current preview:

- pass source contents rather than a server-side file path
- keep `strict = true` for checked-in files so `hocus 0.1;` is required
- inspect `diagnostics`, `formattedSource`, and `graphSpec`
- require `readyForDocumentLowering = false` and `readyForApply = false`
- do not treat a valid structural preview as a Houdini-aware or applyable plan

An export with `valid = false` is intentionally all-or-nothing: `source` is null and blockers are deterministically reported up to the fixed limit; `HOCUS819` records the exact overflow count. Do not delete or approximate blockers to force an export or imply network reconstruction.

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
