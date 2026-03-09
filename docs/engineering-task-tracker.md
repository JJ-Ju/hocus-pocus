# HocusPocus Engineering Task Tracker

Status: active

Source architecture: `docs/houdini-mcp-spec.md`

Execution policy:

- code first
- manual/runtime validation while building
- no upfront requirement for a full automated test harness
- add automation only after the server is usable in real Houdini work

Project state:

- greenfield repo
- initial M0-M2 runtime slice implemented
- this document is the execution tracker for delivery

## 1. Completion Definition

The project is considered complete for v1 when all of the following are true:

- Houdini 21.x can load the plugin as a normal package
- a live Houdini GUI session can host the MCP server on localhost
- an external MCP client can connect and perform real scene work
- live scene operations are serialized onto the Houdini main thread
- the server exposes a practical core tool surface for scene, node, parm, cook, and save workflows
- permissions and audit logging exist for destructive and open-world operations
- long-running cooks/renders expose progress and cancellation
- headless `hython` mode exists
- HAPI/HARS worker mode exists for scalable background execution
- the server is usable enough that validation can happen through real work in Houdini

The following are stretch-complete items, not v1 blockers:

- Python Panel chat UI
- embedded terminal for agent CLIs such as Codex
- optional HDK native bridge

## 2. Tracking Rules

- Only mark a task done when code exists in the repo and can be manually exercised.
- Prefer vertical slices over broad scaffolding.
- Do not block implementation on perfect abstractions.
- Keep the live GUI path working at all times once M2 starts.
- Update this document at the end of each implementation session.
- When a task is split during implementation, add the new child task here instead of tracking it elsewhere.

## 3. Milestone Order

Critical path:

1. M0 Foundation and package scaffold
2. M1 MCP server runtime and transport
3. M2 Live execution lane
4. M3 Core scene automation tools
5. M4 Safety, auth, and audit
6. M5 Long-running jobs, progress, and cancellation
7. M6 Headless execution modes
8. M7 Packaging, install flow, and user docs
9. M11 Runtime hardening and dogfooding

Stretch path:

1. M8 Python Panel UI
2. M9 Embedded terminal and agent launcher
3. M10 Optional HDK native bridge

## 4. Milestones

## M0. Foundation and Package Scaffold

Status: implemented, pending Houdini validation

Goal:

- create the repo layout and startup structure for a Houdini-first plugin

Tasks:

- [x] Create the package-oriented source tree for core, live, workers, ui, and native integration points.
- [x] Add a Houdini package file template and config loader.
- [x] Add a version module and centralized build/runtime metadata.
- [x] Add structured logging utilities and a user-pref-directory log location.
- [x] Add settings loading with defaults for host, port, token mode, approved roots, and feature flags.
- [x] Add a startup entry point that can be called from Houdini without auto-starting side effects.
- [x] Add a shelf tool or startup command entry stub for launching the server manually.

Done when:

- Houdini can import the package from a package path without errors.
- There is one clear entry point for starting and stopping the server.
- Config and log paths resolve correctly inside a Houdini session.

Manual smoke:

- Launch Houdini 21.x with the package enabled and confirm the module imports.
- Start the stub entry point and confirm it writes a startup log line.

## M1. MCP Server Runtime and Transport

Status: implemented, pending Houdini validation

Goal:

- expose a real MCP server contract that clients can connect to

Tasks:

- [x] Choose the MCP server implementation approach: official Python SDK wrapper or direct JSON-RPC implementation.
- [x] Implement capability negotiation and server metadata.
- [x] Implement Streamable HTTP on localhost inside Houdini.
- [x] Implement request routing, structured errors, and logging hooks.
- [x] Implement bearer-token auth for HTTP mode.
- [x] Implement a minimal `session.info` tool and a health/status resource.
- [x] Implement a thin stdio bridge executable that can proxy to the live HTTP server.
- [x] Add server lifecycle controls: start, stop, restart, status.

Done when:

- An external MCP client can connect and call `session.info`.
- The server can be started and stopped without restarting Houdini.
- Unauthorized HTTP requests are rejected when auth is enabled.

Manual smoke:

- Start the server in Houdini.
- Connect from an MCP inspector or simple client.
- Call `session.info` and read the health resource.

## M2. Live Execution Lane

Status: implemented, pending Houdini validation

Goal:

- make live-scene automation safe and repeatable by serializing all Houdini mutations

Tasks:

- [x] Implement a live command queue that is the only path for HOM scene mutations.
- [x] Marshal queued work onto the Houdini main/UI thread.
- [x] Add request context objects carrying operation id, caller id, timeouts, and permissions.
- [x] Add undo-group wrapping for scene-editing operations.
- [x] Add cancellation plumbing for queued and running operations.
- [x] Add a scene revision counter and basic event subscriptions for hip, selection, and playbar changes.
- [x] Normalize exception handling into MCP-friendly structured errors.
- [x] Add operation timing and slow-call logging.

Done when:

- Repeated scene edits happen through the queue only.
- Scene-editing requests become one-step undo operations.
- Concurrent incoming requests do not mutate Houdini directly.

Manual smoke:

- Fire repeated `node.create` and `parm.set` requests from an external client.
- Verify the scene remains stable and undo behaves predictably.

## M3. Core Scene Automation Tools

Status: in progress

Goal:

- deliver the first truly useful tool surface for real Houdini work

Tasks:

- [x] Implement scene lifecycle tools: new, open, merge, save, revert, summary.
- [x] Implement node graph tools: list, get, create, delete, rename, connect, disconnect, move, layout, flags.
- [x] Implement parm tools: list, get, set, expression, button press, revert.
- [x] Implement selection tools: get and set.
- [x] Implement playbar/frame tools needed for interactive workflows.
- [x] Implement basic viewport tools: get state and capture still image.
- [ ] Implement resource templates for session info, current hip, selection, node data, parm lists, and recent errors.
- [x] Add consistent structured return payloads and tool annotations.

Done when:

- An agent can build a simple SOP network from scratch.
- An agent can set parms, wire nodes, and save the hip file.
- Resources expose enough state that the client does not need to call tools for every read.

Manual smoke:

- Create a geometry container and a small SOP chain from an MCP client.
- Capture the viewport and confirm the result is returned or materialized as a resource.

## M4. Safety, Auth, and Audit

Status: not started

Goal:

- make the server safe enough to use with real agent clients

Tasks:

- [ ] Implement permission profiles: observe, edit_scene, write_files, run_code, launch_processes, use_network, submit_farm_jobs.
- [ ] Map every tool to the permissions it requires.
- [ ] Implement approved filesystem roots and write restrictions.
- [ ] Implement destructive-operation confirmation hooks.
- [ ] Implement structured JSONL audit logging for all tool calls.
- [ ] Tag tool-created or tool-touched nodes with provenance user data.
- [ ] Add read-only mode and config-based feature gating for risky tools.
- [ ] Hide or disable controlled escape-hatch tools unless explicitly enabled.

Done when:

- Risky tools are blocked unless their permissions are enabled.
- Every tool call produces an audit record.
- Created nodes carry provenance metadata.

Manual smoke:

- Attempt a blocked destructive call and verify rejection.
- Enable the permission and verify the same call succeeds and is logged.

## M5. Long-Running Jobs, Progress, and Cancellation

Status: not started

Goal:

- make cooks, renders, and exports first-class instead of hanging requests

Tasks:

- [ ] Implement a task registry with task ids, state, progress, timestamps, and result links.
- [ ] Implement progress notifications or polling-compatible task resources.
- [ ] Implement `cook.node` and cancellation.
- [ ] Implement `render.rop` and cancellation.
- [ ] Implement recent log resources for job output.
- [ ] Implement timeout policies and cancellation cleanup.
- [ ] Ensure long jobs do not block unrelated read operations more than necessary.

Done when:

- A client can launch a long cook or render and observe progress without blocking.
- A running job can be cancelled cleanly.
- Recent logs and task state are queryable after completion.

Manual smoke:

- Start a long cook or render, watch progress, then cancel one run and let one finish.

## M6. Headless Execution Modes

Status: not started

Goal:

- support non-GUI automation and scalable background execution

Tasks:

- [ ] Implement `hython` server mode with the same core tool contract where applicable.
- [ ] Implement a worker manager abstraction shared by GUI-hosted and headless modes.
- [ ] Implement an HAPI/HARS worker adapter.
- [ ] Implement routing rules for which tools run live vs headless vs HAPI.
- [ ] Implement worker lifecycle, health checks, and reconnect behavior.
- [ ] Implement serialization rules for passing scene/job inputs to headless workers.
- [ ] Implement a first background offload path from GUI-hosted server to a worker.
- [ ] Document limitations where the live GUI path and HAPI semantics differ.

Done when:

- The same client can talk to a `hython` host for non-UI workflows.
- The GUI-hosted server can offload at least one expensive task to a worker.
- HAPI/HARS workers can be started, monitored, and reclaimed reliably.

Manual smoke:

- Run a non-UI scene transform in `hython`.
- Offload one heavy export or cook from the GUI-hosted server to a worker.

## M7. Packaging, Install Flow, and User Docs

Status: not started

Goal:

- make the server installable and usable without code edits

Tasks:

- [ ] Finalize the Houdini package file format and install instructions.
- [ ] Add a clear startup flow for manual start and optional auto-start.
- [ ] Add example MCP client configuration snippets for common clients.
- [ ] Add docs for auth token handling, approved roots, and permissions.
- [ ] Add docs for live GUI mode, `hython` mode, and worker mode.
- [ ] Add troubleshooting notes for missing packages, bad ports, and auth failures.
- [ ] Add version compatibility notes for Houdini 21.x.

Done when:

- A user can install the package, launch Houdini, start the server, and connect a client from the written docs alone.
- The docs cover the minimum operational issues likely to occur during first use.

Manual smoke:

- Follow the written install instructions from a clean Houdini user package location.

## M8. Python Panel UI

Status: not started

Priority: stretch

Goal:

- add a first-class in-Houdini control surface for the server

Tasks:

- [ ] Implement a Python Panel entry and registration.
- [ ] Build a panel shell with connection status, task list, recent logs, and current scene context.
- [ ] Add approval prompts for destructive tool calls.
- [ ] Add links/actions for selection, node paths, and task drill-down.
- [ ] Add panel-driven start/stop/restart controls for the server.

Done when:

- The panel loads reliably inside Houdini.
- The panel shows live server status and active tasks.

Manual smoke:

- Open the panel, start the server, run a few tool calls externally, and confirm they appear in the panel.

## M9. Embedded Terminal and Agent Launcher

Status: not started

Priority: stretch

Goal:

- let a user launch agent CLI tools directly inside Houdini's environment

Tasks:

- [ ] Implement a process manager for child CLI processes.
- [ ] Implement a terminal UI surface in the panel.
- [ ] Ensure launched processes inherit Houdini's environment and selected working directory.
- [ ] Add presets for `codex`, `python`, and `hython`.
- [ ] Add one-click local MCP connection hints for launched agents.
- [ ] Add process output capture, termination, and exit-state reporting.

Done when:

- A user can launch Codex or another CLI from inside Houdini and keep the session visible in the panel.
- The launched process can reach the local MCP server without manual environment surgery.

Manual smoke:

- Launch a CLI process from the panel, keep it running, and verify output/termination handling.

## M10. Optional HDK Native Bridge

Status: not started

Priority: stretch

Goal:

- improve performance and native integration where Python is not enough

Tasks:

- [ ] Create the HDK plugin scaffold and load/unload rules.
- [ ] Add version/ABI compatibility checks.
- [ ] Implement one native helper with clear value, such as PTY support or fast geometry summary extraction.
- [ ] Expose the native helper to the Python layer cleanly.
- [ ] Ensure the server still works when the native module is absent.

Done when:

- The native module can be loaded on supported Houdini 21.x builds.
- At least one feature meaningfully benefits from the native module.
- The Python-only fallback path remains valid.

Manual smoke:

- Start Houdini with and without the native module present and verify graceful behavior in both cases.

## M11. Runtime Hardening and Dogfooding

Status: not started

Goal:

- move from "feature complete" to "usable during real scene work"

Tasks:

- [ ] Use the server on real Houdini scenes and record all failures and friction points.
- [ ] Fix crashers, deadlocks, and incorrect main-thread behavior first.
- [ ] Fix permission and install friction second.
- [ ] Fix tool contract rough edges third.
- [ ] Add missing resource views only where real usage proves they are needed.
- [ ] Capture a short list of supported workflows that now work end to end.
- [ ] Freeze a v1 release checklist and close all blocker issues.

Done when:

- The server is being used for real work without recurring critical failures.
- There are no known blockers preventing normal scene automation from an MCP client.
- The remaining issues are quality-of-life items rather than correctness or stability problems.

Manual smoke:

- Use the server to perform at least one real scene-editing session, one save/reload cycle, and one longer cook/export cycle.

## 5. Backlog That Stays Deferred Until After First Usable Release

These items should not block implementation unless they become necessary during dogfooding.

- automated unit tests for pure utility modules
- automated integration tests for live Houdini sessions
- fixture-heavy HAPI regression tests
- UI snapshot tests
- packaging automation for all platforms
- remote, non-localhost hosting
- multi-user concurrency beyond one active writer

## 6. Immediate Next Actions

Current recommendation:

1. Finish the remaining M3 resource-template gap.
2. Go directly into M4 safety gates before enabling any broader execution escape hatches.
3. Add M5 task/progress support so longer cooks and renders stop blocking request lifetimes.
4. Add M6 headless and worker modes before calling the server v1-complete.

## 7. Session Log

Use this section as the lightweight running journal while implementing.

### 2026-03-09

- Created the initial engineering task tracker from the architecture spec.
- Set the project path to a code-first, runtime-validation-first delivery model.
- Implemented the initial Houdini package scaffold under `package/`, `python3.11libs/`, `scripts/`, and `toolbar/`.
- Implemented a minimal MCP-compatible localhost HTTP runtime with auth, lifecycle controls, resources, and a stdio bridge.
- Implemented the first live execution lane with a serialized dispatcher, request contexts, basic scene callbacks, and undo-wrapped mutation tools.
- Added initial tools beyond `session.info`: `scene.get_summary`, `node.create`, `parm.set`, and `scene.save_hip`.
- Local smoke validation passed outside Houdini for import, startup, auth rejection, MCP initialization, tool listing, resource reads, and stdio bridge proxying.
- Houdini-hosted validation is still pending for package loading, UI-thread dispatch, and live-scene mutations.
- Finished M2 with tracked operation state, cooperative cancellation, cancellation notifications, and non-UI serialized worker execution.
- Expanded M3 substantially with scene lifecycle, node graph, parm, selection, playbar, and viewport tools plus additional session resources.
- Remaining M3 gap is resource templates and Houdini-hosted validation of the broader tool surface.
- Added a build/install PowerShell script that stages an installable Houdini package, runs `compileall`, and can install directly into `houdini21.0/packages`.
- Added a README covering build, deploy, install, startup, token discovery, and first-run troubleshooting.
- Added self-describing Houdini orientation/convention notes to session responses and a dedicated `houdini://session/conventions` resource.
- Added more discoverable snapshot/camera tooling with `snapshot.capture_viewport` and `camera.get_active`.
