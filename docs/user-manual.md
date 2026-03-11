# HocusPocus Manual

HocusPocus is a Houdini-hosted MCP server for live automation in Houdini 21.x.

## 1. Install

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Clean -Install
```

Installed package locations:

- `%USERPROFILE%\Documents\houdini21.0\packages\HocusPocus`
- `%USERPROFILE%\Documents\houdini21.0\packages\hocuspocus.json`

Auto-start is enabled by default.

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
- `model.create_house_blockout`

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

### House blockout macro

`model.create_house_blockout` is a proof-point high-level modeling macro. It creates a simple house network under `/obj` with a displayable `OUT_house`.

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
