# HocusPocus Manual

HocusPocus provides a durable agent connection to live automation in Houdini
22.0.368. The client-facing stdio broker remains alive while the embedded
Houdini execution host is replaced across restarts.

Houdini `22.0.368` is the sole supported and release-qualifying live runtime
for V1. Other builds, including Houdini `21.x`, are unsupported. Historical H21
receipts describe migration evidence, not a currently available runtime.

## 1. Install

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Installed package locations:

- `%USERPROFILE%\Documents\houdini22.0\packages\HocusPocus.<install-id>`
- `%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus.json`

The package manifest switches to a validated versioned candidate atomically;
an interrupted install leaves the prior package active. Reinstalling preserves
the bearer token. Use `-RotateToken` only for an intentional credential
rotation, then restart Houdini. A running durable broker refreshes the
credential without a client reconnect. Restart the MCP client once only when
the installed broker program itself changes. Auto-start is enabled by default.

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

The embedded host's private MCP endpoint is:

```text
http://127.0.0.1:37219/hocuspocus/mcp
```

The current health endpoint is:

```text
http://127.0.0.1:37219/hocuspocus/healthz
```

The installed package owns the bearer credential in its active versioned
configuration:

```text
%USERPROFILE%\Documents\houdini22.0\packages\HocusPocus.<install-id>\config\default.toml
```

Use the installer and `-RotateToken` workflow to manage it. Do not copy the
token into an MCP client configuration.

## 3. Connecting an Agent

### Codex or Claude Code on Windows

Install the stable broker launcher after installing the Houdini package:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_hocuspocus_mcp_client.ps1
```

The installer discovers a standalone Python 3.11-or-newer runtime, copies a
stable governed launcher beside the active Houdini package pointer, and writes
ready-to-copy Codex and Claude configuration. Use:

- transport: `stdio`
- name: `hocuspocus`
- command and arguments: the exact values returned by the installer

The verified stable launcher resolves the credential directly from the active
installed package. It does not require Codex or Claude to inherit
`HOCUSPOCUS_TOKEN`, and it never writes the secret into their MCP configuration.
An explicit source-tree development launch may still provide the variable. The
generated client snippets are written beside the package pointer as
`hocuspocus-codex.toml` and `hocuspocus-claude.json`; copy their command,
arguments, and environment exactly.

The broker owns the stable MCP session. When Houdini stops, reads return a
typed retryable `HOCUS999 host_offline` result. After Houdini restarts, the
next request initializes a fresh host session and resumes unexpired
session-scoped workspace grants without reconnecting the client. Live
checkouts are generation-scoped and must be recreated. A `tools/call` whose
delivery became ambiguous is reported as `ambiguous_delivery` and is never
silently replayed.

Each call exposes a stable operation ID. After a timeout, disconnect, or host
replacement, call `session.get_operation` with that ID before attempting
another mutation. A terminal result is returned without re-execution. An
old-host pending record is reported as `partial_or_unknown`; inspect live state
instead of retrying blindly.

The direct HTTP endpoint remains useful for health checks and transport
diagnostics. It is not the normal Codex or Claude transport, and direct clients
disconnect with the Houdini process. See the
[durable transport contract](durable-mcp-transport.md) for restart and
ambiguous-delivery behavior.

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
- `object.create_geometry`
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
- `hda.set_instance_parms`

Use `hda.set_instance_parms` for artist-facing parameters on a locked digital
asset. It never unlocks or structurally edits the asset. When promoting an
internal parameter, `hda.promote_parm` preserves the current source value unless
you explicitly choose another `default_value` or `initial_value`.

Before authoring VEX or another code blob, read `grantedCapabilities` from
`session.info` and the required/missing capability projection from document
validation or preview. Trusted local procedural work must explicitly select the
`procedural-authoring` policy profile; `local-dev` intentionally does not grant
`run_code`.

### Task tools

- `task.list`
- `task.cancel`
- `cook.node`
- `render.rop`
- `export.alembic`
- `export.usd`

### Higher-level tools

- `graph.batch_edit`
- `document.checkout`
- `document.validate`
- `document.diff`
- `document.apply`
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

### Bootstrap an empty OBJ scene

Use `object.create_geometry` when no Geometry container exists. The operation is
deliberately narrower than a generally writable `/obj` document: it creates an
exact `geo` object under `/obj`, then returns the resolved SOP root and a working
document checkout for document-centric authoring.

Ordinary bootstrap failure retires the checkout and graph admission before
removing the Geometry object. If checkout retirement, graph retirement, or
live-node removal fails, the operation returns a typed recovery error and
retains coherent recoverable state identified by portable `rootPath`,
`checkoutId`, and `retainedState` fields.

Small checkout documents are returned inline. Every response includes
`documentDelivery.mode`, `contentDigest`, `byteLength`, and the inline limit.
When the complete response would exceed that limit, retrieve the same working
document through the retained checkout `resourceUri`.

For node-type discovery, `node_types.list_compatible` exposes its canonical
tasks as an enum. Call it with either one exact `task` or one bounded `intent`;
intent resolution reports `resolvedTask`, `resolutionKind`, and matched terms,
and rejects ambiguous descriptions with deterministic candidates.

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
%USERPROFILE%\Documents\houdini22.0\hocuspocus\output\snapshots\
```

High-level canned asset macros are intentionally not part of the default tool surface. The current server is meant to help agents build procedural Houdini systems directly from lower-level graph, parm, material, render, Solaris, PDG, packaging, and validation tools.

### HocusScript source workflow

`.hocus` files are ordinary, Git-visible project files. For an MCP agent, the
preferred saved-project surface is H6 source workspace access. Approve the
project directory from Houdini's **HocusPocus Source Workspaces** Python Panel,
also embedded as the **Source Workspaces** tab in the server dialog. The panel
lets the host user choose a directory, inspect the project, select an active MCP
client, grant source-read/source-write/generated-lock/external-alias access,
choose expiry and persistence, review path-free audit events, and revoke
access. MCP receives an opaque `projectId`, portable relative paths, and
digests—never the physical root.

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

The same files remain directly editable by the user, an IDE, Git, or the native
CLI. From a source checkout, the equivalent offline loop is:

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

Named ports require exact unique catalog names and compile to exact indexes. Typed `tuple`, `quantity`, `raw_path`, `reset`, ramp, multiparm, expression, and channel-reference values similarly require catalog-v2 evidence. Managed spares are instance parameters owned by the graph; artist spares and other ownership namespaces are preserved. Numeric float/int keyframes use seconds and fixed interpolation/extrapolation modes. USD time samples, arbitrary keyframe expressions, callbacks/buttons, locked HDA internals, and HDA-definition edits are rejected before planning. See [the HS7 fidelity matrix](hocusscript-hs7-support-matrix.md) for the exact family and construct boundaries.

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
[HS8 production workflow](hocusscript-hs8-production.md)
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
%USERPROFILE%\Documents\houdini22.0\hocuspocus\output\exports\
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
- `procedural-authoring`
- `pipeline`

`procedural-authoring` is the only shipped profile that grants `run_code` for
trusted authored code. Source workspace grants remain separate from these live
scene capabilities.

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
  `%USERPROFILE%\Documents\houdini22.0\hocuspocus\logs\`
- runtime files:
  `%USERPROFILE%\Documents\houdini22.0\hocuspocus\runtime\`
- Python bytecode caching is disabled for the governed installed payload; no
  runtime bytecode cache is part of the supported execution path.
- snapshots:
  `%USERPROFILE%\Documents\houdini22.0\hocuspocus\output\snapshots\`
- exports:
  `%USERPROFILE%\Documents\houdini22.0\hocuspocus\output\exports\`
- render/test outputs:
  `%USERPROFILE%\Documents\houdini22.0\hocuspocus\output\`

## 11. Troubleshooting

If `import hocuspocus` fails in Houdini:

- reinstall with the build script
- restart Houdini

If the server is not running:

- run `import hocuspocus; print(hocuspocus.server_status())`
- inspect `%USERPROFILE%\Documents\houdini22.0\packages\hocuspocus.json` and
  verify its selected versioned directory contains `config\default.toml`

If Codex cannot connect:

- verify Codex uses the `hocuspocus` stdio entry generated by
  `scripts\install_hocuspocus_mcp_client.ps1`, not the private HTTP URL
- rerun that installer if the stable launcher is missing or differs from the
  active package, then reload the MCP client once
- if startup reports `Unauthorized`, remove client-side bearer-token settings;
  the governed launcher resolves the credential from the active package
- if calls report `host_offline`, start Houdini and retry on the same MCP
  connection
- after intentional token rotation, restart Houdini; the broker refreshes from
  the active package without a client reconnect
- verify the private host URL only as a secondary diagnostic:
  `http://127.0.0.1:37219/hocuspocus/mcp`
- if the host responds but Codex does not surface tools, treat that as an
  app-side stdio configuration/reload issue rather than a Houdini server failure

If a snapshot or render path is rejected:

- check `allow_file_write`
- check `approved_roots`
- verify the requested output path falls under an approved root
