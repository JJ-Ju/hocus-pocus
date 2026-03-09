# HocusPocus Houdini MCP Server Spec

Status: design spec

Target:
- Houdini 21.x
- MCP protocol revision `2025-11-25`
- Primary host: interactive Houdini GUI session
- Secondary hosts: `hython` and HAPI/HARS workers

## 1. Goal

Build an MCP server that gives AI agents maximum practical control over Houdini while staying:

- fast enough for interactive use
- safe enough to expose to agentic clients
- auditable and undo-friendly
- installable as a normal Houdini plugin
- usable both from external MCP clients and from a self-contained in-Houdini chat panel

The highest-value requirement is full automation of a live Houdini session. The panel/chat/terminal integration is a strong secondary goal, not the architectural center.

## 2. Core Design Decision

The server spine should be **in-process HOM (`hou`) running inside Houdini itself**.

Reason:

- HOM is the only API surface with broad, direct access to the live scene, UI state, playbar, selection, pane tabs, Python panels, node graphs, and most day-to-day Houdini workflows.
- HAPI is excellent for headless cooks, asset workflows, SessionSync, and scalable external execution, but it is not a complete replacement for in-process scene automation.
- HDK should be used selectively for performance, deeper native integration, and capabilities that are awkward or slow in Python.

So the recommended stack is:

1. HOM for live session authority
2. HAPI/HARS for headless and remote execution
3. HDK for native acceleration and missing low-level hooks

## 3. API Role Split

| Layer | Use it for | Do not make it the only layer because |
| --- | --- | --- |
| HOM / `hou` | Live scene edits, node graph control, parms, playbar, selection, UI, Python panel integration, undo, viewport, scene events | It runs in the Houdini process, so you need strict threading and safety controls |
| HAPI / `hapi` / HARS | Headless workers, external batch automation, geometry IO, asset loading, SessionSync-backed attach, scalable cooks | It is not the most complete interface for an interactive Houdini session |
| HDK / C++ | Native plugin pieces, performance-critical inspection, binary streaming, process/PTY helpers, custom pane integrations, bridging to lower-level node internals | ABI-sensitive; higher build and maintenance cost |

### Important HAPI constraint

Do not design the system around SessionSync alone. SideFX documents that SessionSync only synchronizes nodes created by the Houdini Engine client; nodes created or loaded directly in Houdini are not fully synchronized. That makes SessionSync valuable, but not a complete live-scene automation backbone.

## 4. Deployment Modes

The same product should support four modes.

### A. Live GUI mode

Recommended default.

- Runs inside a normal Houdini GUI session
- Hosts the MCP server in-process
- Executes live-scene operations through HOM
- Provides the optional chat panel and terminal

### B. Headless HOM mode

- Runs in `hython`
- Good for CI, offline scene transforms, linting, exports, and render prep
- Uses the same command model as GUI mode, minus UI-specific tools

### C. Headless HAPI/HARS mode

- Runs one or more HARS sessions
- Good for scalable asset cooking, geometry conversion, and farm-style workloads
- Used by the GUI-hosted server as a worker plane for expensive jobs

### D. SessionSync attach mode

- Attaches a HAPI client to a live Houdini instance with SessionSync enabled
- Useful for integrations and mirrored workflows
- Not the primary mode for complete scene control

## 5. Process Architecture

## 5.1 Components

### `hocuspocus_core`

The MCP server core.

- Owns capability negotiation
- Registers tools, resources, prompts, logging, and progress
- Routes requests to execution backends

### `hocuspocus_live`

The live Houdini adapter.

- Executes HOM calls against the current session
- Owns the main-thread command queue
- Owns scene revision tracking and event subscriptions

### `hocuspocus_workers`

The headless execution plane.

- `hython` workers for full HOM batch execution
- HARS/HAPI workers for scalable external engine jobs
- Optional worker pool sizing and queueing

### `hocuspocus_native`

Optional HDK module.

- Fast binary inspection helpers
- Native PTY / process bridge for the terminal panel
- Native event hooks if Python callbacks prove too coarse or expensive
- Optional custom UI/pane helpers

### `hocuspocus_ui`

Optional in-Houdini UX shell.

- Python Panel based on PySide6
- Chat surface
- Task/progress log
- Embedded terminal for agent CLIs

## 5.2 Request flow

1. MCP request arrives over localhost HTTP or stdio bridge.
2. `hocuspocus_core` validates permissions, args, and capability support.
3. Router chooses backend:
   - live HOM
   - headless `hython`
   - HAPI/HARS
   - HDK helper
4. Long-running work gets a task/progress handle.
5. Result returns as structured MCP tool output plus optional linked resources.

## 6. Transport Design

## 6.1 Primary transport: Streamable HTTP on localhost

Preferred server endpoint:

- `POST /mcp`

Why:

- It matches the current MCP recommendation for remote servers
- It works well with the in-Houdini panel, external MCP clients, and local tooling
- It keeps the server self-contained inside Houdini

Implementation recommendation inside Houdini:

- Host the server on Houdini's embedded `hwebserver`
- Implement the MCP endpoint either:
  - directly on `hwebserver.URLHandler` / `AsyncURLHandler`, or
  - by mounting an ASGI app under `hwebserver.registerASGIApp`

`hwebserver.URLHandler` is explicitly documented as suitable for building other RPC systems, including JSON-RPC, which maps well to MCP's JSON-RPC base.

## 6.2 Secondary transport: stdio bridge

Provide a thin launcher:

- `hocuspocus-mcp-stdio`

Behavior:

- Starts fast
- Connects to the live in-process HTTP server if Houdini is already running
- Optionally boots `hython` mode if no GUI server is available

This keeps compatibility with MCP clients that strongly prefer stdio without forcing them to spawn a full GUI host every time.

## 6.3 Internal UI transport

For the chat panel only, allow a private WebSocket channel for:

- streaming logs
- task updates
- terminal output
- progress events

This channel is panel-facing only and is not the public MCP contract.

## 7. Threading and Execution Model

This is a critical part of the design.

### 7.1 Live scene mutations must be serialized

`hwebserver` is multi-threaded, but the live Houdini scene should be treated as a single-writer domain.

Required model:

- network request threads never mutate Houdini directly
- they enqueue commands into a live command queue
- execution is marshaled onto the Houdini main/UI thread

Recommended marshalling tools:

- `hou.ui.postEventCallback()` for one-shot dispatch
- `hou.ui.addEventLoopCallback()` for queue pumping when needed

### 7.2 Undo semantics

All scene-editing tool calls should be wrapped in:

- `hou.undos.group("<operation label>")`

This makes each agent action appear as one user-undoable step.

### 7.3 Long-running jobs

Use:

- `hou.InterruptableOperation` for interactive HOM-side work
- `hapi.interrupt()` for HAPI cooks/loads

All long jobs should expose:

- task id
- progress percentage if known
- state text
- cancellation support

## 8. Capability Surface

The server should expose high-level tools first, low-level escape hatches second.

## 8.1 Tool naming

Use stable dotted names such as:

- `scene.open_hip`
- `node.create`
- `parm.set`
- `pdg.cook`

This fits MCP naming conventions and keeps discovery clean.

## 8.2 Tool groups

### Session and scene lifecycle

- `session.info`
- `scene.new`
- `scene.open_hip`
- `scene.merge_hip`
- `scene.save_hip`
- `scene.revert`
- `scene.undo`
- `scene.redo`
- `scene.get_summary`

### Node graph operations

- `node.list`
- `node.get`
- `node.create`
- `node.delete`
- `node.rename`
- `node.move`
- `node.layout`
- `node.connect`
- `node.disconnect`
- `node.copy`
- `node.paste`
- `node.bypass`
- `node.set_flags`
- `node.as_code`

### Parameters and animation

- `parm.list`
- `parm.get`
- `parm.set`
- `parm.set_expression`
- `parm.keyframe_set`
- `parm.keyframe_delete`
- `parm.press_button`
- `parm.revert_to_default`

### Cooks, simulation, render

- `cook.node`
- `cook.cancel`
- `render.rop`
- `cache.save_geometry`
- `cache.save_hip_debug`
- `sim.reset`
- `sim.playbar_control`

### PDG / TOPs

- `pdg.list_graphs`
- `pdg.cook`
- `pdg.cancel`
- `pdg.get_status`
- `pdg.get_workitems`

### Geometry, USD, and scene inspection

- `geometry.inspect`
- `geometry.export`
- `stage.inspect`
- `material.inspect`
- `errors.list`
- `logs.get_recent`
- `network.diff`

### Viewport, selection, UI context

- `selection.get`
- `selection.set`
- `viewport.get_state`
- `viewport.frame_selection`
- `viewport.capture`
- `camera.get_active`
- `camera.set_active`
- `pane.open`

### Assets and packages

- `hda.list`
- `hda.install_library`
- `hda.reload_all`
- `package.list`
- `package.load`

### Controlled escape hatches

- `exec.python`
- `exec.hscript`
- `exec.native`
- `process.launch`
- `process.read_output`
- `process.terminate`

These are powerful and should be disabled unless explicitly permitted.

## 8.3 Tool behavior rules

Every tool definition should declare MCP annotations where applicable:

- `readOnlyHint`
- `destructiveHint`
- `idempotentHint`
- `openWorldHint`

Examples:

- `node.get` is read-only
- `scene.open_hip` is destructive
- `parm.set` is destructive but not open-world
- `process.launch` is destructive and open-world

## 8.4 Structured outputs

Every tool should return:

- a concise human-readable summary
- structured JSON payload for agents
- optional resource links for large follow-up data

Do not stream giant geometry payloads as normal tool text.

## 9. Resource Model

Resources are how the server should expose durable scene context.

Recommended URIs:

- `houdini://session/info`
- `houdini://session/selection`
- `houdini://session/playbar`
- `houdini://hip/current`
- `houdini://hip/current/errors`
- `houdini://nodes/{path}`
- `houdini://nodes/{path}/parms`
- `houdini://nodes/{path}/geometry-summary`
- `houdini://nodes/{path}/cook-state`
- `houdini://lops/{path}/stage-summary`
- `houdini://pdg/{graph_name}/status`
- `houdini://tasks/{task_id}`
- `houdini://logs/recent`

Rules:

- use pagination for large node/resource lists
- use templates for node-path resources
- keep resources cheap to compute by default
- provide explicit "deep inspect" tools when the expensive path is intentional

## 10. Prompts

Prompts are optional but useful.

Recommended prompts:

- `build_network_from_goal`
- `analyze_selected_network`
- `troubleshoot_failed_cook`
- `refactor_to_hda`
- `optimize_pdg_graph`

Prompts should never be the only way to reach functionality. They are helpers around the tool surface.

## 11. Tasks, Progress, and Notifications

Long operations are common in Houdini, so the server must treat them as first-class.

### 11.1 Task-worthy operations

- cooking large node networks
- PDG graph cooks
- renders
- simulation resets / recooks
- geometry exports
- background process launches

### 11.2 Model

If the client supports MCP tasks, use them.

If not, emulate with:

- normal tool response containing a task id
- `progress` notifications
- pollable task resources under `houdini://tasks/{task_id}`

### 11.3 Event sources inside Houdini

Use Houdini callbacks to keep resources and tasks current:

- `hou.hipFile.addEventCallback`
- `hou.playbar.addEventCallback`
- `hou.ui.addSelectionCallback`
- per-node callbacks via `hou.OpNode.addEventCallback`
- PDG events via `pdg.GraphContext.addEventHandler`
- HDA events via `hou.hda.addEventCallback`

## 12. Scene Revision and Object Identity

Agents need stable references.

### 12.1 Primary identity

For live HOM work, use:

- node path as the public primary identifier

### 12.2 Metadata tags

Stamp tool-created or tool-touched nodes with user data:

- `hpmcp.created_by`
- `hpmcp.operation_id`
- `hpmcp.timestamp`

`hou.Node.setUserData()` stores this with the hip file and includes it in `opscript` / `hou.Node.asCode`, which makes it useful for provenance.

### 12.3 HAPI identity rule

Never treat HAPI node ids as durable across scene reloads. SideFX documents that `hapi.loadHIPFile()` invalidates previously acquired HAPI ids. Re-resolve from path or refresh ids after load/merge boundaries.

## 13. Safety Model

This server can destroy scenes, launch programs, and write data. Default-deny is required.

## 13.1 Default binding

- bind only to `127.0.0.1`
- random bearer token by default for HTTP mode
- no public LAN exposure unless explicitly enabled

## 13.2 Permission profiles

Define server-side capability gates:

- `observe`
- `edit_scene`
- `write_files`
- `run_code`
- `launch_processes`
- `use_network`
- `submit_farm_jobs`

Each tool must declare which gates it requires.

## 13.3 Confirmation policy

Require interactive confirmation for:

- opening or replacing the current hip
- deleting nodes outside the tool-created set
- running arbitrary Python/HScript/native code
- launching external processes
- writing outside approved roots

## 13.4 Audit trail

Persist a structured operation log:

- timestamp
- tool name
- caller id
- arguments hash
- result state
- created/modified node paths
- task id if applicable

Store under the Houdini preferences area and expose a read-only resource for recent operations.

## 13.5 No direct `hrpyc` exposure

Houdini's RPC support is useful as precedent and possibly as a dev-only adapter, but it should not be the main public interface because:

- it has no built-in authentication
- it proxies Python objects directly
- it is less MCP-shaped than a purpose-built server

## 14. Plugin Packaging

Install as a normal Houdini package.

Recommended layout:

```text
HocusPocus/
  package/
    hocuspocus.json
  pythonX.Ylibs/
    hocuspocus/
      core/
      live/
      workers/
      ui/
      native/
      startup.py
  python_panels/
    HocusPocus.pypanel
  scripts/
    python/
      pythonrc.py
      456.py
  toolbar/
    hocuspocus.shelf
  dso/
    hocuspocus_native.dll|so|dylib
  config/
    default.toml
```

Package file should set `HOUDINI_PATH` to the plugin root using Houdini packages.

Startup behavior:

- manual start via shelf tool or Python panel button by default
- optional auto-start from config
- validate Houdini and HDK API versions at load

For native binaries, gate load by Houdini/HDK compatibility. SideFX exposes `hou.hdkAPIVersion()` specifically because ABI changes require plugin recompiles.

## 15. UI Spec: In-Houdini Chat Panel

This is the recommended good-to-have.

## 15.1 Host

Use a Houdini Python Panel.

Why:

- it is a first-class pane tab type
- Houdini ships with PySide6
- it integrates naturally with the existing desktop layout and pane menus

## 15.2 Panel structure

- Chat tab
- Tasks tab
- Scene context tab
- Terminal tab
- Settings tab

### Chat tab

- agent conversation
- tool call timeline
- approval prompts
- links to node paths/resources

### Tasks tab

- current cooks/renders/PDG jobs
- cancel buttons
- progress and logs

### Scene context tab

- current selection
- active node path
- current hip
- frame/range
- error/warning summary

### Terminal tab

- embedded shell/PTY
- can launch `codex`, `claude`, `uv`, `python`, `hython`, etc.
- inherits Houdini's environment
- can auto-connect launched agents to the local MCP endpoint

## 15.3 Terminal implementation

Preferred:

- native PTY helper in `hocuspocus_native`

Fallback:

- `QProcess`-backed line-oriented shell

On Windows, native PTY support should use the platform console API rather than pretending a plain pipe is a full terminal.

## 15.4 Threading constraint

SideFX documents that Python Panel interfaces must be created from the main Houdini application thread. The panel must therefore communicate with background server/process work through signals, queues, or RPC-like message passing, not direct cross-thread UI calls.

## 16. Why HDK Is Worth Having

The HDK should remain optional, but it meaningfully improves the product.

Recommended HDK responsibilities:

- fast geometry/stat extraction without Python bottlenecks
- binary payload generation for screenshots/thumbnails/packed summaries
- stable PTY/process bridge for the terminal tab
- optional custom pane helpers
- optional bridge from HAPI `uniqueHoudiniNodeId` to native `OP_Node` access

That last point is real: SideFX documents that `hapi.NodeInfo.uniqueHoudiniNodeId` can be resolved to `OP_Node` via `OP_Node::lookupNode()` when linked against the HDK.

## 17. Why HAPI Is Still Essential

Even though HOM is the live-scene authority, HAPI should still be a first-class subsystem.

Use HAPI for:

- headless execution workers
- remote attach to HARS
- asset library loading from file or memory
- geometry import/export at engine level
- SessionSync-backed integrations
- scalable background cooks detached from the UI thread

Good design rule:

- HOM owns the interactive truth
- HAPI owns scalable execution

## 18. Recommended Implementation Phases

### Phase 1: live in-process MCP server

Deliver:

- localhost Streamable HTTP endpoint
- core live-scene tools
- resources for scene, nodes, selection, logs
- undo grouping
- permissions and audit log

### Phase 2: deeper Houdini automation surface

Deliver:

- viewport, camera, capture
- PDG tools
- render tools
- scene event subscriptions
- destructive confirmation workflow

### Phase 3: headless worker plane

Deliver:

- `hython` worker mode
- HAPI/HARS worker mode
- task routing between live and headless contexts

### Phase 4: native bridge

Deliver:

- HDK helper module
- PTY/process support
- faster binary/resource extraction

### Phase 5: chat panel and embedded terminal

Deliver:

- Python Panel UI
- task log
- approvals
- embedded agent CLI launcher
- one-click local MCP connection info

## 19. Risks and Constraints

- Live scene access must be serialized or the server will become flaky.
- License usage must be budgeted across GUI, `hython`, and HARS workers.
- SessionSync is useful but not broad enough to be the core automation layer.
- HAPI ids are not durable across hip reload boundaries.
- Python-based whole-scene event watching can become expensive on huge scenes; this is where HDK helpers may become necessary.
- Raw geometry payloads can explode token and bandwidth budgets; default to summaries plus explicit export/fetch tools.
- Native modules must be rebuilt when HDK ABI changes.

## 20. Bottom Line

If the goal is "maximum automation of Houdini", the correct architecture is:

- **in-process HOM server inside Houdini as the source of truth**
- **HAPI/HARS worker plane for headless and scalable execution**
- **optional HDK module for native performance and terminal/process integration**
- **optional Python Panel chat UI that launches agent CLIs inside Houdini's environment**

Anything centered on HAPI alone will leave too much of interactive Houdini unreachable. Anything centered on arbitrary Python execution alone will be powerful but too unsafe and too hard for agents to use reliably. The best system is layered: curated tools first, escape hatches second, with HOM/HAPI/HDK each doing the part they are actually good at.

## Sources

- SideFX API overview: https://www.sidefx.com/docs/houdini/ref/api.html
- HOM / Python scripting: https://www.sidefx.com/docs/houdini/hom/
- Command-line scripting and `hou` import behavior: https://www.sidefx.com/docs/houdini/hom/commandline
- Houdini RPC notes: https://www.sidefx.com/docs/houdini/hom/rpc.html
- `hou.ui` event loop callbacks: https://www.sidefx.com/docs/houdini/hom/hou/ui.html
- Python Panel API: https://www.sidefx.com/docs/houdini/hom/hou/PythonPanel.html
- Python Panel Editor / PySide6 support: https://www.sidefx.com/docs/houdini/ref/windows/pythonpaneleditor.html
- Houdini packages: https://www.sidefx.com/docs/houdini/ref/plugins.html
- `hwebserver`: https://www.sidefx.com/docs/houdini/hwebserver/index.html
- `hwebserver.URLHandler`: https://www.sidefx.com/docs/houdini/hwebserver/URLHandler_class.html
- HAPI Python API: https://www.sidefx.com/docs/houdini/hapi/
- HAPI SessionSync: https://www.sidefx.com/docs/houdini/ref/henginesessionsync.html
- `hapi.NodeInfo`: https://www.sidefx.com/docs/houdini/hapi/NodeInfo.html
- `hapi.loadHIPFile`: https://www.sidefx.com/docs/houdini/hapi/loadHIPFile.html
- `hou.hipFile` callbacks: https://www.sidefx.com/docs/houdini/hom/hou/hipFile.html
- `hou.playbar` callbacks: https://www.sidefx.com/docs/houdini/hom/hou/playbar.html
- `hou.nodeEventType`: https://www.sidefx.com/docs/houdini/hom/hou/nodeEventType.html
- PDG event handling: https://www.sidefx.com/docs/houdini/tops/events.html
- `hou.undos`: https://www.sidefx.com/docs/houdini/hom/hou/undos.html
- `hou.InterruptableOperation`: https://www.sidefx.com/docs/houdini/hom/hou/InterruptableOperation.html
- `hou.Node` user data: https://www.sidefx.com/docs/houdini/hom/hou/Node.html
- HDK intro: https://www.sidefx.com/docs/hdk/_h_d_k__intro.html
- HDK plugin intro: https://www.sidefx.com/docs/hdk/_h_d_k__intro__creating_plugins.html
- Extending `hou` with C++: https://www.sidefx.com/docs/houdini/hom/extendingwithcpp.html
- MCP overview (`2025-11-25`): https://modelcontextprotocol.io/specification/2025-11-25/basic/index
- MCP lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- MCP resources: https://modelcontextprotocol.io/specification/2025-11-25/server/resources
- MCP sampling: https://modelcontextprotocol.io/specification/2025-11-25/client/sampling
- MCP tasks: https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks
