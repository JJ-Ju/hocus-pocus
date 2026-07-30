# HocusPocus Manual

HocusPocus is a Houdini-hosted MCP server for live automation in Houdini 21.x.

## 1. Install

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Installed package locations:

- `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus.<install-id>`
- `%USERPROFILE%\Documents\houdini21.0\packages\hocuspocus.json`

The package manifest switches to a validated versioned candidate atomically;
an interrupted install leaves the prior package active. Reinstalling preserves
the bearer token. Use `-RotateToken` only for an intentional credential
rotation, then restart Houdini and connected clients. Auto-start is enabled by
default.

## 2. Basic Verification

In Houdini's Python shell:

```python
import hocuspocus
print(hocuspocus.server_status())
```

Typical output includes:

- `running`
- `serverVersion`
- `mcpUrl`
- `healthUrl`
- `tokenEnabled`
- `dispatcherMode`
- `policyProfile`
- `effectivePolicy`

The current default MCP endpoint is:

```text
http://127.0.0.1:37219/hocuspocus/mcp
```

The current health endpoint is:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

The bearer token is stored at:

```text
%USERPROFILE%\Documents\houdini21.0\hocuspocus\runtime\token.txt
```

## 3. Connecting an Agent

### Codex on Windows

Use a custom MCP entry with:

- Transport: `Streamable HTTP`
- Name: `houdini`
- URL: `http://127.0.0.1:37219/hocuspocus/mcp`

Auth:

- paste the token directly if the client supports bearer-token input
- otherwise use:
  `Authorization: Bearer <your-token>`

Important validation note:

- these settings are documented for the Codex app
- the implemented validation in this repo has proven the Houdini MCP server over its Streamable HTTP JSON-RPC transport
- it has not proven native Codex runtime tool exposure from inside this agent runtime

## 4. Houdini Conventions

HocusPocus exposes orientation notes so agents do not have to guess:

- `Y` is up
- `XZ` is the ground plane
- `X` is left-right
- `Z` is front-back / depth

These are exposed through:

- `session.info`
- `scene.get_summary`
- `houdini://session/conventions`

## 5. Core MCP Surface

### Read and graph tools

- `scene.get_summary`
- `node.list`
- `node.get`
- `parm.list`
- `parm.get`
- `selection.get`
- `playbar.get_state`
- `viewport.get_state`
- `camera.get_active`

### Mutation tools

- `scene.new`
- `scene.open_hip`
- `scene.merge_hip`
- `scene.save_hip`
- `scene.undo`
- `scene.redo`
- `node.create`
- `node.delete`
- `node.rename`
- `node.connect`
- `node.disconnect`
- `node.move`
- `node.layout`
- `node.set_flags`
- `parm.set`
- `parm.set_expression`
- `parm.press_button`
- `parm.revert_to_default`
- `selection.set`
- `playbar.set_frame`

### Task tools

- `task.list`
- `task.cancel`
- `cook.node`
- `render.rop`
- `export.alembic`
- `export.usd`

### Higher-level tools

- `graph.batch_edit`
- `geometry.get_summary`
- `scene.create_turntable_camera`
- `snapshot.capture_viewport`

## 6. Dynamic Resources

### Node resources

- `houdini://nodes/{path}`
- `houdini://nodes/{path}/parms`
- `houdini://nodes/{path}/geometry-summary`

Accepted path forms:

- slash-separated:
  `houdini://nodes/obj/geo1`
- percent-encoded absolute path:
  `houdini://nodes/%2Fobj%2Fgeo1`

### Task resources

- `houdini://tasks/recent`
- `houdini://tasks/{task_id}`
- `houdini://tasks/{task_id}/log`

These are useful for polling long-running cooks and renders without holding a request open.

## 7. Higher-Level Workflows

### Batch graph edits

`graph.batch_edit` applies a grouped list of operations in one request.

Supported operation types:

- `create_node`
- `connect`
- `set_parm`
- `set_flags`
- `move_node`
- `layout`

Operations can reference earlier results with `$ref:<id>` and `$ref:<id>/suffix`.

Example patterns:

- `$ref:geo`
- `$ref:box/sizex`

### Geometry summaries

`geometry.get_summary` returns:

- point count
- primitive count
- vertex count
- bbox min/max
- groups
- attribute names
- material paths if present

### Turntable camera

`scene.create_turntable_camera` creates:

- a target null
- a rig null
- a camera

It can size the orbit using geometry bounds from a target node.

### Managed snapshots

`snapshot.capture_viewport` can be called with no path. In that case, HocusPocus writes to a managed location under:

```text
%USERPROFILE%\Documents\houdini21.0\hocuspocus\output\snapshots\
```

High-level canned asset macros are intentionally not part of the default tool surface. The current server is meant to help agents build procedural Houdini systems directly from lower-level graph, parm, material, render, Solaris, PDG, packaging, and validation tools.

### HocusScript source workflow

`.hocus` files are ordinary native project files. Select their project directory explicitly in the offline CLI/editor, or opt in to H6 source access from Houdini's **HocusPocus Source Workspaces** Python Panel (also embedded as the **Source Workspaces** tab in the server dialog). The panel lets the host user choose a directory, inspect the project, select an active MCP client, grant source-read/source-write/generated-lock/external-alias access, choose expiry and persistence, review path-free audit events, and revoke access. MCP receives an opaque `projectId`, portable relative paths, and digests—never the physical root.

Startup configuration can register the same authority without editing server code:

```toml
[[source_workspace.projects]]
root = "D:/show/project"
label = "Environment DSL"
grants = ["source_read", "external_read"]
grant_expires_in_seconds = 2592000
external_roots = { studio = "D:/Studio Libraries/Hocus" }
```

Default grants are read-only, session-scoped, and expire after eight hours. Persisted grants default to 30 days unless the host explicitly selects “until revoked.” Source write, generated-lock update, and each external alias remain separate grants. Moving/replacing the root or changing the manifest's authority projection invalidates approval.

An authenticated MCP client initializes a session, discovers only its approved projects through `source.project.describe` or `hocus-source://` resources, then uses the exact seven-operation surface:

- `source.project.describe`
- `source.file.search`
- `source.file.read`
- `source.file.apply_patch`
- `source.file.write_export`
- `source.project.build`
- `source.project.navigate`

Writes are exact-digest guarded and limited to authored `.hocus` files or a non-authority-changing `hocus.project.toml`; raw lock, catalog, bundle, external-root, delete, rename, and arbitrary filesystem writes are denied. `source.project.build` selects one of `format`, `check`, `compile`, or `lock_update`. A lock update requires the generated-lock grant, literal write intent, complete host-retained external mapping, and `expectedLockState = "absent"` for exclusive bootstrap or `"present"` plus the exact current lock digest for replacement.

```powershell
$env:PYTHONPATH = "python3.11libs"
python -m hocuspocus.hocusscript check hocus/asset.hocus --project D:/show/project
python -m hocuspocus.hocusscript format hocus/asset.hocus --project D:/show/project --write
python -m hocuspocus.hocusscript compile hocus/asset.hocus --project D:/show/project -o asset.bundle.json
```

HS7 projects use language `0.4` and keep the same ordinary text-file workflow. The new surface is declarative: it describes graph structure and managed state but never presses buttons, runs callbacks, cooks, or edits HDA definitions.

```hocus
hocus 0.4;

graph Motion {
  target "/obj/motion";
  category Sop;
  ownership "fx";
  mode reconcile;

  node output: "null" {
    spare gain @id("spare.gain") {
      label = "Gain";
      type = "float";
      tuple_size = 1;
      default = [1.0];
      menu_items = [];
    }

    animate gain @id("anim.gain") {
      value_type = "float";
      value = 1.0;
      authored_fps = 24.0;
      display_fps = 24.0;
      extrapolation = ["constant", "linear"];
      keys = [[0.0, 1.0, "linear"], [1.0, 2.0, "bezier"]];
    }
  }

  sticky_note @id("note.output") {
    text = "Managed output";
    position = [6.0, 2.0];
    size = [3.0, 1.5];
    color = [0.2, 0.3, 0.5];
    text_size = 1.0;
    background = true;
    minimized = false;
  }
}
```

Named ports require exact unique catalog names and compile to exact indexes. Typed `tuple`, `quantity`, `raw_path`, `reset`, ramp, multiparm, expression, and channel-reference values similarly require catalog-v2 evidence. Managed spares are instance parameters owned by the graph; artist spares and other ownership namespaces are preserved. Numeric float/int keyframes use seconds and fixed interpolation/extrapolation modes. USD time samples, arbitrary keyframe expressions, callbacks/buttons, locked HDA internals, and HDA-definition edits are rejected before planning. See [the HS7 fidelity matrix](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\hocusscript-hs7-support-matrix.md) for the exact family and construct boundaries.

### HS8 production qualification

HS8 does not replace `.hocus` with a build-specific authoring format. Continue
editing and compiling ordinary `.hocus` files, apply them through the guarded
document pipeline, then run explicit production cooks. The read-only
`production.asset.qualify` operation consumes the resulting contract,
observation, portable provenance, metrics, clean-build comparison, numeric
baseline, visual baseline, and artist-override evidence. It returns exact
packaging and publish decisions without cooking, writing, or mutating Houdini.
The raw gate decisions describe advisory technical eligibility. The public
operation is always `content_only`; `readyForPackaging` and `readyForPublish`
remain false even when the caller has `review_production`. Packaging and
release authority come only from the installed private runner and detached
verifier, never caller-supplied facts.

A packaging pass requires the asset contract, protected artist regions,
provenance, outputs, platform budget, deterministic rebuild, and numeric
baseline to pass. A publish pass additionally requires visual comparison
evidence bound to exact output digests. The corresponding schemas are available
under canonical `hocuspocus://schemas/...` resources and byte-identical
`houdini://production/schema/...` aliases. See the
[HS8 production workflow](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\hocusscript-hs8-production.md)
for the complete evidence and safety model.

For a language-`0.2` project with manifest-declared external libraries, repeat `--module-root ALIAS=ABSOLUTE_PATH` on every mixed-root `lock --update`, `check`, and `compile` invocation. The options must exactly cover all declared aliases, including aliases not reached by the selected entry. Quote the complete `ALIAS=ABSOLUTE_PATH` argument when a path contains spaces:

```powershell
$project = "D:/show/project"
$studio = "studio=D:/Studio Libraries/Hocus"
$materials = "materials=E:/Shared Hocus/Materials"
$lockDigest = "sha256:<exact-current-lock-digest>"

python -m hocuspocus.hocusscript lock hocus/asset.hocus --update --project $project --expected-lock-digest $lockDigest --module-root $studio --module-root $materials
python -m hocuspocus.hocusscript check hocus/asset.hocus --project $project --module-root $studio --module-root $materials
python -m hocuspocus.hocusscript compile hocus/asset.hocus --project $project --module-root $studio --module-root $materials -o asset.bundle.json
```

Mixed lock publication requires one valid existing v3 lock and its exact current digest; it does not bootstrap a missing or structurally invalid lock. Physical module roots are per-call authority only: the CLI does not read them from an environment variable, expand home or environment syntax, infer them from the lock, cache them, or persist them. Omitting all root options preserves same-project resolution. `format` remains lock-independent and does not accept `--module-root`; `write-export` remains a language-`0.1` content handoff and does not accept it either.

External-aware completion and go-to-definition are native Python editor-integration APIs (`complete_mixed_*` and `definition_mixed_*`) whose `module_roots` mapping is mandatory per request. There is no separate HocusScript editor CLI command. The approved H6 `source.project.navigate` operation composes those same native APIs using the server-retained root authority; `document.complete_source` remains content-only and cannot inspect native projects or external roots.

For the live forward path, compile an ordinary approved project `.hocus` file with the `compile` action of `source.project.build`. Pass the returned exact versioned Bundle to `document.preview_bundle`, then `document.plan_bundle`, and finally `document.apply_plan`. Preview is non-mutating. Planning reruns exact-version validation of the authenticated carrier's semantics and provenance pins—including catalog/HDA selections, capabilities, ownership, target, and revisions—before persisting an immutable plan. Apply validates that immutable plan's identity and live session, policy, catalog, capability, revision, ownership, and target drift guards; it does not reread or recompile `.hocus` source. `document.compile_source` remains the structural-only compatibility endpoint for unsaved editor buffers, not the live compile/apply handoff.

For the reverse direction, `document.export_source` accepts only a Houdini `root_path` and optional graph name. One supported flat direct-child SOP, fixed-port material/VOP, LOP, or TOP network returns canonical text and durable provenance. A network-document v2 export uses language `0.4`; ROP/DOP/COP/CHOP, locked HDA contents, direct USD state, nodes outside the selected root's direct-child projection, and dynamic or incomplete connector evidence fail closed with `source = null` and bounded deterministic blockers with exact overflow accounting.

The native publisher currently accepts only a flat language-`0.1` export response. Save such a JSON response and create a project-contained file natively:

```powershell
python -m hocuspocus.hocusscript write-export export-response.json hocus/exported.hocus --project D:/show/project
```

The command refuses to overwrite an existing file unless its exact current digest is supplied with `--expected-digest`. An approved source-write project can perform the same language-`0.1` authenticated handoff through `source.file.write_export`; it validates the handoff, recompiles, and safely publishes rather than treating export text as a generic patch. Language-`0.4` network-document v2 exports are observational output that is structurally recompiled and exact-catalog semantically validated. That validation is not a network-reconstruction guarantee, and these exports are not accepted by either native publication lane yet. `document.format_source` and `document.complete_source` support unsaved editor buffers without filesystem access.

### Managed exports

`export.alembic` and `export.usd` can be called with no explicit `path`. In that case, HocusPocus writes to a managed location under:

```text
%USERPROFILE%\Documents\houdini21.0\hocuspocus\output\exports\
```

`export.alembic` is intended for SOP geometry sources. `export.usd` is intended for LOP nodes under `/stage`.

Some LOP networks can still fail export if they rely on internally generated layer save paths. If that happens, try exporting from a simpler native LOP source or adjust the source network so authored layers resolve to valid output locations.

## 8. Tasks, Cooks, Renders, and Exports

`cook.node`, `render.rop`, `export.alembic`, and `export.usd` return task handles instead of blocking until completion.

Useful task flow:

1. call `cook.node`, `render.rop`, `export.alembic`, or `export.usd`
2. read `houdini://tasks/{task_id}`
3. read `houdini://tasks/{task_id}/log`
4. call `task.cancel` if needed

Task state includes:

- `state`
- `progress`
- `progressMessage`
- `cancelRequested`
- `result`
- `error`
- `outcome`
- `recoveryNotes`

Task `outcome` now makes partial progress easier to reason about. Depending on task type, it may include:

- `expectedOutputPaths`
- `existingOutputPaths`
- `producedOutputPaths`
- `completedFrames`
- `remainingFrames`
- `cancellationSemantics`

Render and export cancellation are cooperative. If cancellation happens mid-run, partial outputs may already exist on disk.

## 9. Safety and Policy

Relevant config in `config/default.toml`:

- `policy_profile = "local-dev"`
- `read_only = true`
- `allow_scene_edit = false`
- `allow_file_write = false`
- `approved_roots = [...]`

Named profiles:

- `safe`
- `local-dev`
- `pipeline`

Effects:

- `read_only` blocks scene mutation and file output
- `allow_scene_edit` blocks edit-capable tools
- `allow_file_write` blocks hip saves, snapshots, and render output validation
- `approved_roots` restricts file output paths to approved directories

Useful status and resource surfaces:

- `server_status()`
- `houdini://session/policy`
- `houdini://session/health`

Error payloads now include stable machine-readable fields:

- `data.errorFamily`
- `data.retryable`

Common families:

- `request`
- `validation`
- `policy`
- `auth`
- `runtime`
- `unsupported`
- `cancelled`

The in-Houdini operator panel remains experimental and is currently hidden from the default UI surface pending a later revisit.

Task, tool, and file activity is also recorded in the runtime audit log.

## 10. Runtime Paths

Common runtime locations:

- logs:
  `%USERPROFILE%\Documents\houdini21.0\hocuspocus\logs\`
- runtime files:
  `%USERPROFILE%\Documents\houdini21.0\hocuspocus\runtime\`
- snapshots:
  `%USERPROFILE%\Documents\houdini21.0\hocuspocus\output\snapshots\`
- exports:
  `%USERPROFILE%\Documents\houdini21.0\hocuspocus\output\exports\`
- render/test outputs:
  `%USERPROFILE%\Documents\houdini21.0\hocuspocus\output\`

## 11. Troubleshooting

If `import hocuspocus` fails in Houdini:

- reinstall with the build script
- restart Houdini

If the server is not running:

- run `import hocuspocus; print(hocuspocus.server_status())`
- verify the installed config at:
  `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus\config\default.toml`

If Codex cannot connect:

- verify Houdini reports `running: True`
- verify the URL is `http://127.0.0.1:37219/hocuspocus/mcp`
- verify the token matches `token.txt`
- if the server responds over HTTP but Codex still does not surface tools, treat that as an app-side MCP wiring issue rather than a Houdini server failure

If a snapshot or render path is rejected:

- check `allow_file_write`
- check `approved_roots`
- verify the requested output path falls under an approved root
