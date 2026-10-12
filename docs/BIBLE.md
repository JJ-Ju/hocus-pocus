# HocusPocus Design Bible

**Version:** 1.0 shipped 2026-10-12 (master); this document remains the design
authority for 1.x. **Status:** authoritative. When code and this document disagree, one
of them is wrong and the disagreement is a bug to fix, not a fact to live with.

**Implementation notes:** the reviews, evaluation logs and image evidence behind 1.0 are
indexed in [`docs/redesign/README.md`](redesign/README.md).

HocusPocus is an MCP server that lets AI agents drive a live SideFX Houdini session
and manage its scene files. This document describes how HocusPocus **should** be,
not how the 0.9 codebase is. The six review reports under `docs/redesign/review/`
record what was wrong with 0.9 and why; this document records the decisions that
follow from them.

---

## 0. The one-paragraph version

An agent talks MCP over stdio to a thin **bridge** process (standard CPython, official
`mcp` SDK). The bridge finds or launches a Houdini instance and forwards tool calls over
an authenticated loopback HTTP channel to a small stdlib-only **host** running inside
Houdini, which executes every `hou` call on Houdini's main thread inside one named undo
group and returns compact JSON in Houdini's own vocabulary. There are about thirty
tools. They are named after what Houdini users call things: nodes, parms, inputs,
flags, cook, hip file. There is a Python escape hatch. Errors tell the agent what to do
next. Nothing the agent needs is ever redacted, and nothing it doesn't need is ever
sent.

---

## 1. Principles

1. **Houdini's vocabulary is the API.** Node paths, parm names, parm tuples, input
   indices and labels, node type names, flags, cook, hip. If an LLM that has read the
   SideFX docs cannot guess a tool's arguments, the tool is wrong. No invented carriers,
   documents, bundles, checkouts, grids, or revision counters on the agent surface.
2. **Small surface, deep tools.** ~30 tools a model can hold in its head, each doing one
   thing well with a few well-chosen options. Batch inputs where Houdini users batch
   (create several nodes, set several parms). `tools/list` stays under a hard token
   budget (§4.1).
3. **Compact by default, complete on request.** Non-default parms only. Summaries first.
   Cursors for anything that can grow. A default response budget of 16 KB. `detail`
   flags open the firehose only when asked.
4. **Truth over ceremony.** Every mutation reports what Houdini actually did: final
   paths, whether a keyframe was written, the node's errors and warnings after the
   change. No silent success on a broken expression.
5. **Errors are instructions.** A failure is an `isError` tool result with a stable
   `code`, a human `message`, a `hint` for the next action, and `candidates` when a
   name was close. "Internal server error" is never an acceptable answer to a user-level
   mistake.
6. **Safe by default, never silently destructive.** No discarding unsaved work without
   an explicit flag. Every mutating call is exactly one labelled undo group. Destructive
   tools are annotated as such.
7. **Houdini's main thread owns `hou`.** All `hou` calls execute on the main thread with
   a bounded timeout; long work becomes a job the agent polls. Network I/O never touches
   the UI thread.
8. **Houdini-side code is boring.** The host is pure stdlib Python with no third-party
   dependencies, so it cannot fight SideFX's bundled packages or studio pipelines. The
   protocol-heavy, dependency-heavy code lives outside Houdini in the bridge.
9. **The agent may need a Houdini that isn't running yet.** Tools list offline. The
   bridge can list, pick, attach to and launch Houdini instances. A Houdini restart is a
   visible state change, not a broken connection.
10. **Localhost security, honestly scoped.** Loopback bind, per-instance token,
    `Origin` check, an off switch for Python, optional path roots. Nothing more. We do not
    pretend that integrity manifests, bytecode bans or rate limits protect a developer
    machine from the agent that already has a shell on it.
11. **Three commands to first success.** Install the tool, install the Houdini package,
    register with the client. No PowerShell, no config merging, no exact-build pin.
12. **Tests run against real Houdini.** Every tool has an integration test under
    `hython`. Pure logic has fast unit tests. The suite must be green before anything is
    deleted.

---

## 2. What we are replacing, and why

Summary of `docs/redesign/review/01…06`. Read those for evidence; this is the verdict.

| Finding | Consequence for 1.0 |
|---|---|
| 130 registered tools (103 listed, 27 hidden), ~100 KB `tools/list`, ~25k tokens before the first call | ~35 tools, ≤ 12k tokens, generated from one catalogue |
| The only *listed* way to change a parm is a "network document" checkout; a 5-node chain checked out at 1.37 MB; a cooked HDA pushed a read to 2 MB (~520k tokens) | Direct primitives (`node_create`, `parm_set`, …) are the surface. The document model is deleted. |
| The primitives that worked first try (`node.create`, `parm.set`, `node.connect`) were hidden from `tools/list` | They become the core, in Houdini vocabulary |
| HocusScript: 56k LOC (57 % of the package), 61 schemas, 481 diagnostic codes, 25 tools, used by no one outside fixtures | Deleted. Declarative graph build is done with Houdini's native `hou.data` JSON instead (§4.4) |
| Every tool result passed through a redaction filter that replaced hip paths, save paths and long strings with `"<redacted>"` | No redaction. Omit a field or return it. |
| Hip `new`/`open` silently discarded unsaved changes; no save-as, recent files, `$HIP`/`$JOB`, load warnings | Hip lifecycle is first-class and safe (§6) |
| Fixed port 37219 with `SO_REUSEADDR`: a second Houdini silently shares the port; shared token, log, journal, SQLite | Ephemeral port per instance, instance registry, per-instance state (§3.6) |
| Exact pin to Houdini 22.0.368 refused the installed 22.0.466; source-admission checks rejected `__pycache__`, CRLF checkouts and stale manifests | Version range `>= 22.0` with a warning; no admission machinery |
| Node errors/warnings never surfaced; a broken expression was accepted silently; `cook` async-only | `cook` and `problems` are synchronous and honest; every mutation reports errors |
| Geometry read gave attribute *names* only; viewport capture returned a file path; no Python exec; no help lookup; no named inputs; parm tuples not addressable; COP/DOP/VOP/CHOP/ROP discovery rejected | All fixed in the catalogue (§4) |
| Hand-rolled MCP negotiation in two places; `hwebserver` ASGI segfaults in 22.0.466; vendoring the `mcp` SDK into Houdini shadows SideFX packages | Official SDK outside Houdini; stdlib host inside (§3) |
| 43 `unittest` mega-tests behind 35 helper modules; no tool exercised against real Houdini; 50-test and 1,200-line caps | pytest, three tiers, hython integration tier (§11) |
| 9 install steps and ~14 concepts before first success; installer assumed `Documents\houdini22.0` while this machine uses `%USERPROFILE%\houdini22.0` | Three commands; resolve `HOUDINI_USER_PREF_DIR` (§10) |

---

## 3. Architecture

### 3.1 Topology

```
MCP client (Claude Code, Codex, …)
   │  stdio, MCP (official SDK, 2025-11-25 + 2026-07-28)
   ▼
hocuspocus-mcp  ── the BRIDGE ──  standalone CPython ≥ 3.11, installed with uv
   │  owns: MCP protocol, tool catalogue, argument validation, instance registry,
   │        launching Houdini, offline behaviour, response budgeting
   │  loopback HTTP/JSON, bearer token, Origin check, small versioned RPC
   ▼
hocuspocus.host ── the HOST ── runs inside Houdini (GUI or hython), stdlib only
   │  owns: MainThreadExecutor, undo groups, tool implementations, jobs,
   │        instance registry entry, scene generation counter
   ▼
hou
```

Two processes, one direction of dependency: the bridge depends on the host's RPC
contract; the host knows nothing about MCP.

Why two processes (decided, not open): the official MCP SDK brings pydantic-core,
anyio, starlette, uvicorn and pywin32 into whatever interpreter runs it. Inside
Houdini those shadow SideFX's own `attrs`, `cryptography` and `click` (verified in
review 04). Out of process, the SDK can track the MCP spec freely, `tools/list` works
while Houdini is closed, and the bridge can launch Houdini. `hwebserver` is not an
option: its ASGI adapter segfaults 22.0.466 and its handlers run off the main thread.

### 3.2 The host (inside Houdini)

**Package:** `hocuspocus.host`. **Dependencies:** Python stdlib only. **Entry
points:** `hocuspocus.host.start()` / `stop()` / `status()` / `autostart()`; `hython -m
hocuspocus.host [--hip FILE] [--port N] [--state-dir DIR] [--label NAME] [--read-only]
[--no-python] [--work-dir DIR]` for headless.

**MainThreadExecutor.** One class, two backends, chosen by `hou.isUIAvailable()`:

- GUI: a `hou.ui.addEventLoopCallback` pump (what `hdefereval` is built on) that drains
  a `queue.Queue` of `(callable, future)` each idle tick. Not `hdefereval` itself: it has
  no timeout, deadlocks when called from the main thread, and discards tracebacks.
- Headless: the main thread *is* the pump. `hython -m hocuspocus.host` starts the HTTP
  listener on a daemon thread and then loops draining the same queue on the main thread
  until shutdown.

Contract: `run(fn, timeout) -> result` executes `fn` on the main thread, captures the
full traceback, runs inline if already on the main thread, and raises
`HoudiniBusy` after `timeout` seconds (the work still completes; the result is
discarded). Requests are serialised: one `hou` operation at a time.

**Undo.** Every mutating tool call runs inside exactly one
`hou.undos.group("HocusPocus: <tool> <summary>")`. Read-only tools never open a group.
`undo` exposes the label history so users and agents can revert "the last agent action".

**HTTP server.** `http.server.ThreadingHTTPServer` bound to `127.0.0.1` on an
**ephemeral port** (`port=0`), `allow_reuse_address = False`. Routes:

| Route | Method | Purpose |
|---|---|---|
| `/hp/v1/health` | GET | `{ok, pid, houdini, generation}` — no auth, no `hou` call |
| `/hp/v1/call` | POST | `{tool, args, timeout_s}` → tool result (see §3.4) |
| `/hp/v1/jobs/{id}` | GET | job status/result |
| `/hp/v1/shutdown` | POST | stop the host (not Houdini) |

Auth: `Authorization: Bearer <token>`; 401 otherwise. `Origin` header, if present,
must be absent or loopback; 403 otherwise. Request body cap 4 MB.

**Instance registry entry.** On start the host writes
`<state_dir>/instances/<pid>.json`:

```json
{"hp": 1, "pid": 12345, "port": 52311, "token": "…", "houdini": "22.0.466",
 "ui": true, "hip": "C:/work/shot.hip", "started": "2026-10-12T10:00:00Z",
 "generation": 3, "label": "houdinifx"}
```

`<state_dir>` is `%LOCALAPPDATA%\HocusPocus` on Windows, `$XDG_STATE_HOME/hocuspocus`
or `~/.local/state/hocuspocus` elsewhere. The file is user-readable only. It is
rewritten on hip load/save (path changes) and removed on `hou.hipFileEventType.BeforeQuit`
and at interpreter exit. The bridge treats an entry whose pid is dead as stale and
deletes it.

**Dirty tracking.** Verified on 22.0.466: in hython `hou.hipFile.hasUnsavedChanges()` is
always `True`, even right after a load, clear or save. Headless, the host therefore
tracks dirtiness itself: the dispatcher marks the scene dirty after every successful
mutating call, the `scene=False` tools mark it where they change the scene, and save,
load and clear mark it clean. In the GUI the host asks Houdini.

**Scene generation.** A monotonically increasing integer bumped on
`AfterClear`, `AfterLoad`, `AfterMerge`. Returned in every tool result's `_meta` as
`scene_generation`. Agents that cache node paths can detect that the world changed.

**Per-instance state.** Logs at `<state_dir>/logs/host-<pid>.log` (rotating, 5 MB).
No SQLite, no journal, no shared files between instances.

### 3.3 The bridge (outside Houdini)

**Package:** `hocuspocus.bridge`. **Dependencies:** `mcp>=2.3,<3`. **Entry point:**
console script `hocuspocus-mcp` (stdio). Installed with `uv tool install -e .` from a
checkout; `uv tool install hocuspocus` once it is on PyPI.

Responsibilities:

1. **Serve MCP** with `mcp.server.MCPServer`, `instructions` set (§4.8), tools
   registered from the shared catalogue (§3.5) so `tools/list` is complete and
   deterministic **with no Houdini running**.
2. **Validate arguments** against the catalogue's JSON Schema (SDK v2 does not), and
   return schema failures as `isError` results with `code: invalid_argument`.
3. **Resolve the target instance.** Order: explicitly connected instance (via
   `houdini_connect`) → the only live instance → the most recently started live
   instance, with a warning in the result `_meta` when more than one exists. If none:
   `code: houdini_offline` with the hint "call houdini_connect with launch to start one".
4. **Forward** `tools/call` to `POST /hp/v1/call`. One attempt; never retry a mutation.
   On connection failure after the request was sent, return `code: delivery_unknown`
   with the instructions to inspect state before repeating.
5. **Bridge-local tools:** `houdini_status` (merges registry + host `/health` + a cheap
   host `session` call when online) and `houdini_connect` (attach/launch).
6. **Launch Houdini.** `houdini_connect {launch: {mode: "gui"|"headless", hip?, wait_s}}`
   runs `houdinifx.exe`/`houdini.exe` (GUI) or `hython -m hocuspocus.host` (headless) from
   the detected `$HFS` (config, `HFS` env, or the newest `Side Effects Software/Houdini 22.*`),
   then polls the registry until the new pid appears or `wait_s` elapses.
7. **Budget responses.** Enforce `max_response_bytes` (default 16 KB) by truncating list
   payloads at item boundaries and setting `truncated: true` plus `next_cursor` when the
   host supplied one. Images are exempt from the byte cap but downscaled by the host.

The bridge keeps **no durable state**. Restarting it loses nothing.

### 3.4 Host RPC contract (`hp/v1`)

Request:

```json
{"tool": "parm_set", "args": {...}, "timeout_s": 30, "request_id": "uuid"}
```

Response (always HTTP 200 once authenticated; transport errors are 4xx/5xx):

```json
{"ok": true,  "result": {...}, "_meta": {"scene_generation": 3, "undo_label": "HocusPocus: parm_set 2 parms", "elapsed_ms": 12}}
{"ok": false, "error": {"code": "parm_not_found", "message": "...", "hint": "...", "candidates": ["sizex","sizey","sizez"], "hou_exception": "hou.OperationFailed: ..."}, "_meta": {...}}
```

The bridge maps `ok:false` to an MCP `isError: true` result whose text is the error
JSON and whose `structuredContent` is the error object. `_meta` is passed through as
tool-result `_meta`. The protocol version `hp/v1` is in the path; incompatible changes
bump it and the bridge refuses to talk to an older host with `code: version_mismatch`
and the hint "run `hocuspocus install-houdini` and restart Houdini".

### 3.5 The shared catalogue

`hocuspocus/tools/catalog.py` is a stdlib-only module that defines every tool once:
name, description, input JSON Schema, output JSON Schema (where stable), MCP
annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint=false`),
`profile` (`core` or `full`), `headless_ok` (bool), and `bridge_local` (bool). The host
imports it to map names to implementations and to reject unknown tools; the bridge
imports it to register MCP tools; `hocuspocus docs tools` renders `docs/tools.md` from
it; a unit test asserts every catalogue entry has an implementation, a description
under the word cap, and a passing example.

### 3.6 Lifecycle and multiple instances

- **GUI autostart.** The installed Houdini package adds the payload to `HOUDINI_PATH`
  (`hpath`) and the copied package directory (with `--dev`, the checkout's `src/`) to
  `PYTHONPATH`. A `uiready.py` hook (runs once the UI exists) calls
  `hocuspocus.host.start()` unless `autostart = false`. Startup never raises into
  Houdini; failures go to the host log and `hou.ui.setStatusMessage`.
- **Headless.** `hython -m hocuspocus.host --hip file.hip` registers like any instance
  with `"ui": false`. UI-only tools return `code: ui_required` with the headless
  alternative in `hint`.
- **Several Houdinis.** Each has its own port, token and registry entry.
  `houdini_status` lists them with pid, label, hip, ui, version, started. The agent
  selects with `houdini_connect {pid}`. The bridge remembers the selection for its
  lifetime only.
- **Restart.** Houdini closes → registry entry disappears → calls return
  `houdini_offline` → Houdini starts → new entry → bridge auto-selects it when it is the
  only one. No `/mcp reconnect` required.
- **Shutdown.** `BeforeQuit` removes the registry entry and stops the listener.

### 3.7 Configuration

Optional file `$HOUDINI_USER_PREF_DIR/hocuspocus.toml`, env overrides
`HOCUSPOCUS_*`, CLI flags last. Everything has a default; the file is not required.

**One toml serves both processes, and the environment wins.** The host reads every key;
the bridge reads `profile`, `max_response_bytes`, `default_timeout_s` and `hfs` from the
same file and ignores the rest. Inside Houdini the pref dir is
`hou.homeHoudiniDirectory()`. The bridge starts on every client launch and cannot afford
a hython query, so it looks in `HOUDINI_USER_PREF_DIR` (`__HVER__` read as `22.0`), then
the `prefs` that `install-houdini` records in `<state_dir>/install.json`, then the
platform default locations. A `HOCUSPOCUS_<KEY>` variable overrides the file in either
process.

```toml
autostart = true            # GUI sessions start the host on uiready
allow_python = true         # houdini_python / hscript escape hatch
read_only = false           # refuse all mutating tools
approved_roots = []         # if non-empty, file paths for hip/hda/render must be under these ($VAR, ~ expanded; links resolved)
max_response_bytes = 16384
default_timeout_s = 30
job_threshold_s = 10        # cook/render longer than this become jobs
profile = "core"            # core | full (adds usd_stage, pdg, hda, events)
log_level = "INFO"
hfs = ""                    # bridge: explicit Houdini install dir for launch
```

`HOCUSPOCUS_WORK_DIR` (environment only) is where a Houdini that HocusPocus launches
starts, and so the `$HIP` and `$JOB` of its untitled scene; default the user's home
directory, as for a GUI Houdini started from the desktop. Never the state dir (it holds
`instances/` and `logs/`) and never the repo. `hython -m hocuspocus.host` moves there too
after start-up (`--work-dir` overrides; hython's own cwd stays off `HOUDINI_PATH` as long
as it was started from a neutral directory).

---

## 4. The tool surface

### 4.1 Conventions

- **Names:** `snake_case`, `[a-z0-9_]`, no dots (several model APIs reject dots). Verb
  last for actions on a noun (`node_create`, `parm_set`), noun alone for query tools
  that take a mode (`undo`, `time`). The MCP server name (`hocuspocus`) is the namespace.
- **Identity:** Houdini node paths (`/obj/geo1/box1`) and parm paths
  (`/obj/geo1/box1/sizex` or tuple `/obj/geo1/box1/size`). Nothing else. Tools that
  return nodes return their final resolved path.
- **Arguments:** flat, typed, `additionalProperties: false`, enums for closed sets,
  defaults stated in the description. Batch tools take `items: [...]` and return
  `results: [...]` in the same order; one failing item fails the whole call and rolls
  back the undo group unless `partial: true`.
- **Responses:** `structuredContent` **and** the same JSON serialised compactly into the
  text block (clients vary in which they feed the model). `outputSchema` declared where
  the shape is stable. Key casing is `snake_case` in both directions.
- **Budget:** `tools/list` ≤ 12,000 tokens total (CI-tested with a tokenizer
  approximation of 4 chars/token: ≤ 48 KB of model-visible text). Each description ≤ 80
  words. Examples live in `docs/tools.md` and the resource `hocuspocus://guide`, not in
  descriptions. Default result ≤ 16 KB. List tools take `limit` (default 50) and
  `cursor`; results carry `next_cursor` when more exist and `total` when cheap.
- **Non-default only:** parm listings show parms where `isAtDefault()` is false unless
  `include_defaults: true`.
- **Locked HDAs** are opaque by default: `node_find`, `node_info` and
  `network_describe` do not descend into locked assets unless `recurse_locked: true`.
- **Every mutation result** includes, for each touched node: `path`, `type`, `errors`,
  `warnings` (after a non-forced cook of that node if it is cheap, else `cook_state:
  "not_cooked"`; errors left from before the change are rechecked with a forced cook,
  §5.18). The result also carries the scene's `dirty` flag after the call.
- **Annotations:** read tools `readOnlyHint: true`; `node_delete`, `hip_new`,
  `hip_open`, `houdini_python` `destructiveHint: true`; `parm_set`, `node_connect`,
  `node_edit`, `time`, `selection`, `cook`, `job`, `viewport_capture`
  `idempotentHint: true`; all `openWorldHint: false`. A tool whose only side effect is a
  cook, a temporary capture ROP or host-side job state is `readOnlyHint: false`,
  `destructiveHint: false`, `idempotentHint: true`.
- **`scene=False` registration.** By default the dispatcher wraps every tool that is not
  `read_only` in one undo group, refuses it in read-only mode and marks the scene dirty.
  `undo`, `time`, `selection`, `hda`, `cook`, `pdg`, `render`, `job` and
  `viewport_capture` register with `scene=False` and do that work themselves where it applies: `performUndo` raises
  inside an undo group; reads (`time` with no arguments, `hda list`) must not open a
  group or dirty the scene; cooks, work items, renders, captures and jobs are not hip
  state. Their
  annotations still say `readOnlyHint: false`. `host/tools/registry.py` documents the
  convention and a unit test pins the set.
- **Headless:** tools with `headless_ok: false` are listed with "(GUI only)" in the
  description; calling them headless returns `ui_required`.

### 4.2 Session and instances (bridge-local)

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `houdini_status` | — | `connected: {pid, port, houdini, ui, hip: {path, name, dirty, is_new}, time: {frame, fps, range}, env: {HIP, JOB, HIPNAME}, scene_generation, host_version}`, `instances: [...]`, `bridge_version`, `profile`, `read_only`, `allow_python` | Works offline (`connected: null`). Read-only. An untitled scene's `hip` carries `note: "$HIP is the launch directory until you hip_save."` |
| `houdini_connect` | `pid?`, `launch?: {mode: gui\|headless, hip?, wait_s=90}`, `disconnect?: bool` | the new `connected` block | Launch uses `hfs` config or auto-detect. Headless launches `hython -m hocuspocus.host`. Both modes start in `HOCUSPOCUS_WORK_DIR` (default home, §3.7). |

### 4.3 Hip file

| Tool | Args | Behaviour |
|---|---|---|
| `hip_new` | `on_unsaved: fail\|save\|discard = fail` | `hipFile.clear()`. With unsaved changes and `fail` → `code: unsaved_changes`, hint lists the options. `save` saves first (fails if the file is new/untitled: hint "use hip_save with path"). |
| `hip_open` | `path`, `on_unsaved` as above, `ignore_load_warnings = true` | `hipFile.load(...)`. Returns `path`, `warnings: [...]` (load warnings are reported, not thrown), `scene_generation`. Path checked against `approved_roots` if set. |
| `hip_save` | `path?`, `increment = false`, `backup = false` | `save(path)` is save-as when `path` given; `increment` uses `saveAndIncrementFileName()`; `backup` uses `saveAndBackup()`. Returns the real saved `path`, `dirty` after save, `bytes`. Creates directories. |
| `hip_merge` | `path`, `node_pattern = "*"`, `overwrite_on_conflict = false`, `dry_run = false` | `dry_run` returns `collisions` from `collisionNodesIfMerged()` only. |

Recent files (`hip_info` / status): the hip files saved or loaded in this host session
(newest first; hython never writes `file.history`), then
`$HOUDINI_USER_PREF_DIR/file.history` when present, best effort, under `recent: [...]` in
`houdini_status.connected.hip`.

### 4.4 Nodes and networks

| Tool | Args | Behaviour |
|---|---|---|
| `node_find` | `root = "/"`, `pattern = "*"` (glob on name, `hou.Node.glob` semantics), `type?` (glob), `category?` (`Sop\|Object\|Lop\|…`), `flags?: {display, render, bypass, template, locked}`, `has_errors?`, `recurse_locked = false`, `limit`, `cursor` | Compact rows: `path, type, category, flags, input_count, child_count, has_errors`. |
| `node_info` | `paths: [..]`, `include: [parms, inputs, outputs, children, errors, flags, hda, comment, position, userdata]` default `[parms, inputs, errors, flags]`, `include_defaults = false` | Per node: `path, name, type {name, category, version, description, help_url}`, `flags`, `inputs: [{index, name, label, from: {path, output}}]`, `outputs: [{index, name, to: [...]}]`, `parms` (compact: `name, value, raw, expression?, keyed?, locked?, menu_token?`), `errors, warnings, messages, cook_state`, `children_count`, `hda: {locked, definition, library}`, `position`, `comment`, `color`. |
| `node_create` | `items: [{parent, type, name?, parms?: {name: value\|{expression, language}\|{expr, lang}}, inputs?: [{index\|name, from, output=0}], flags?: {display, render, bypass, template}, position?: [x,y]}]`, `layout = "good_position"\|"none"`, `exact_type = false` | One undo group. Type resolved like `createNode` (namespace order; `box` → current version). Unknown type → `code: node_type_not_found` with `candidates` from fuzzy match over the parent's category. Returns per item the `node_info` compact block. `parms` go through the same engine as `parm_set`; an expression is `{expression, language}` as `parm_set` and the readers spell it, and the short `{expr, lang}` is accepted too. |
| `node_delete` | `paths`, `keep_connections = true` (reconnect input 0 to outputs when possible) | Destructive. Returns `deleted: [paths]`. |
| `node_edit` | `items: [{path, name?, flags?, color?: [r,g,b], comment?, position?, lock?: bool (HDA allowEditingOfContents), bypass?}]` | Rename returns `old_path → path`. |
| `node_copy` | `paths`, `to_parent`, `names?`, `with_inputs = true`, `position_offset?` | `copyItems`/`copyNodesTo`. Returns new paths. |
| `node_connect` | `items: [{from: path\|null, from_output = 0, to: path, to_input: int\|name\|"next"}]` | `from: null` disconnects. `name` uses `setNamedInput`/`inputNames()`. `"next"` uses `setNextInput` (merge-style nodes). Out-of-range → `code: invalid_input` with `hint` listing `inputLabels()`. |
| `node_layout` | `parent`, `paths?` (subset), `mode: children\|good_position` | `layoutChildren()` or per-node `moveToGoodPosition()`. |
| `network_describe` | `root`, `depth = 1`, `include_defaults = false`, `include_positions = false`, `recurse_locked = false`, `format: data\|python` | `data`: `root.childrenAsData(inputs=True, flags=True, position=…, default_parmvalues=False)` trimmed and with locked-HDA children replaced by `{"type": ..., "locked": true}`. `python`: `asCode(brief=True)` for a single node only. This is how an agent reads a graph in one call. |
| `network_build` | `parent`, `data` (same shape `network_describe` returns, i.e. Houdini's own `hou.data` format), `on_name_collision: error\|rename\|replace = error`, `layout = true`, `dry_run = false` | `parent.setChildrenFromData(...)` in one undo group after `dry_run`-style validation (type names exist, inputs resolvable). Returns created paths and per-node errors after cook. Input entries are `{from, from_index, to_index}`; a missing `to_index` is the entry's list position (§5.16). This replaces HocusScript and the network document. |

### 4.5 Parms

| Tool | Args | Behaviour |
|---|---|---|
| `parm_get` | `paths: [...]` (parm or tuple paths), `frame?`, `include: [keys, menu, template, ramp, multiparm]` | Per parm/tuple: `path, name, tuple, component_names?, type, value` (evaluated at `frame` or current), `raw` (`unexpandedString`/`rawValue`), `expression?`, `language?`, `is_default`, `locked`, `keyframes?: {count, first, last}`, `menu?: {token, label, items: [...]}` (items capped at 50), `ramp?`, `multiparm?: {count, instances}`, `template?: {label, type, default, min, max, help}`. A tuple path returns components. A component path on a tuple returns that component. `code: parm_not_found` carries `candidates` (nearest names on the node, incl. tuple components). |
| `parm_set` | `items: [{path, value?, expression?, language: hscript\|python = hscript, keyframe?: {frame?, value}, keyframes?: [...], channel_ref?: "/path/to/parm", ramp?: {basis, keys, values}, multiparm_count?: int, revert_to_default?: bool, press?: bool, animation: replace\|key\|keep = replace}]`, `frame?` | Exactly one of the value-ish fields per item. Tuple path + list value sets all components; component path sets one. `animation: replace` deletes keyframes/expression first then `set()` (so the value sticks); `key` sets a keyframe at `frame`; `keep` is plain `set()` (Houdini's own behaviour, which may add a key — reported). Menu values accept token or label (label resolved with a hint). Strings accept `$HIP`-style raw text unexpanded. Returns per item: `path, value, raw, expression?, wrote_keyframe: bool, is_default` and the owning node's `errors/warnings` after a cheap cook. Type mismatch → `code: invalid_value` with the template type and range. Locked HDA → `code: locked` with hint to `node_edit lock:false` or `hda` tool. |

### 4.6 Cook, problems, geometry

| Tool | Args | Behaviour |
|---|---|---|
| `cook` | `paths`, `force = false`, `frame?`, `timeout_s = 30` | `node.cook(force)` on the main thread; catches `OperationFailed` and reports `errors/warnings/messages` per node, `cook_time_ms`, `ok`. Errors left from before a fix, on the node or its inputs, are rechecked (§5.18); `hint` names `force: true` when that was skipped. If the cook exceeds `job_threshold_s` and the client allows, it becomes a job (returns `job_id`). |
| `problems` | `root = "/"`, `include_warnings = true`, `cook_uncooked = false`, `recurse_locked = false`, `limit` | Walks the subtree, reports nodes with errors/warnings, broken channel references, missing file parms (`file`-type templates whose expanded path does not exist), unconnected required inputs. Errored nodes changed since their last cook are recooked first, so a fixed node is never listed. The "why is my node red" tool. |
| `geo_info` | `path` (SOP, or OBJ → its display SOP), `frame?` | ~1 KB: `point_count, prim_count, vertex_count, bbox: {min, max, size, center}, prim_types: {polygon: n, packed: n, volume: n, …}, attributes: {point: [{name, type, size, type_info}], vertex, prim, detail: [{name, type, value}]}, groups: {point: [{name, count}], prim, edge, vertex}, intrinsics?`. Uses intrinsics and bulk accessors, never Python loops over points. |
| `geo_read` | `path`, `class: point\|prim\|vertex\|detail`, `attribs?: [..]` (default all), `start = 0`, `cursor?`, `count = 50`, `group?`, `stats = false` | Spreadsheet rows as arrays with a `columns` header. `stats` adds `min/max/mean` per numeric attribute and `unique` (≤ 20) per string attribute over the **whole** class, computed with numpy bulk accessors. `next_cursor` is the next row offset as a string (pass it as `cursor`). |

### 4.7 Visual feedback, code, types, state, contexts

| Tool | Args | Behaviour |
|---|---|---|
| `viewport_capture` | `camera?` (path), `frame?`, `resolution = [1024, 768]`, `fit = "all"\|"selected"\|"none"`, `source: auto\|viewer\|opengl_rop = auto`, `path?` | Returns MCP **image content** (PNG, downscaled so the longest side ≤ 1024) plus `{path, width, height, camera_used}`. `viewer` uses the GUI SceneViewer flipbook of one frame (captures what the user sees, as it is: `fit` is not applied and `fit_used` is `"none"`, so an unhomed view can show an empty grid; home the view first or use `opengl_rop`). `opengl_rop` renders through an OpenGL ROP and, when `camera` is absent, a camera framed on the bbox (`camera_used: "temporary"`; `fit: none` reuses the last framing); works headless. A look is read-only: headless, camera and ROP exist only in the child hython (§8); in the GUI they are created outside undo and deleted after the render, and `notes` says so if Houdini still marked the hip modified. `auto` prefers `viewer` in GUI. |
| `render` | `rop_path`, `frames?: [start, end, inc]` (default current), `output?`, `wait_s = 20`, `thumbnail = true` | Starts a job that calls `rop.render(...)`. If it finishes within `wait_s` returns `{outputs: [paths], thumbnail: image}`; else `{job_id}` to poll with `job`. Karma/Mantra/OpenGL/any ROP. |
| `houdini_python` | `code`, `timeout_s = 30`, `language: python\|hscript = python`, `undo_label?` | `exec` in a fresh namespace with `hou` bound, stdout/stderr captured, the value of a trailing expression or a `result` variable JSON-serialised (`repr` fallback). Runs on the main thread inside one undo group. Returns `{stdout, stderr, result, exception?: {type, message, traceback}}`. Output capped at the response budget with `truncated`. Disabled → `code: python_disabled`. Destructive. |
| `node_type_search` | `query`, `category?`, `limit = 20`, `include_hidden = false` | Ranks exact name = 100, exact label = 95, name prefix, label prefix, all words in the label; a plain-language query is then scored word by word without stop words, a word naming the type (4) or a whole label word (3) outranking a keyword (1.5) or a description word (1), with a short Houdini synonym table at half weight. Marks `is_current_version`. Row: `name, label, category, version, description, inputs: {min, max}, deprecated`. All 18 categories supported. |
| `node_type_info` | `type` (`category/name` or bare name with `category`), `include_parms = true`, `include_help = false`, `folder?`, `detail: compact\|full = compact` | `compact`: `parms: {folder: [[name, label, type, default, components?]]}` under `parm_columns`, no menus, ranges, hidden parms, per-parm help, `help_url` or `tags` (Sop/scatter: 3.0 KB against 5.7 KB). `full`: `name, label, category, version, description, help_url, inputs: [{index, name, label}], outputs, parms: [{name, label, type, size, default, min, max, menu?, folder, help?, is_hidden}]` grouped by folder, plus `help_text` (first ~2 KB of the node help from `$HFS/houdini/help/nodes.zip`, best effort) when asked. |
| `undo` | `action: undo\|redo\|history`, `steps = 1` | `history` lists the last 20 undo labels (and `redo` labels); `undo`/`redo` returns the labels `performed` plus `next_undo`, `next_redo`, `undo_count`, `redo_count`, `dirty`, `scene_generation`. |
| `time` | `frame?`, `range?: [start, end]`, `fps?` | Omitting all fields reads. Sets with `hou.setFrame`, `hou.playbar.setFrameRange` (works headless), `hou.setFps`. |
| `selection` | `paths?` | Omit to read `hou.selectedNodes()`; provide to `setSelected` exactly. |
| `job` | `action: status\|result\|cancel\|list`, `job_id?` | Jobs are host-side threads for render/pdg/long cook. `status: {state: running\|done\|failed\|cancelled, progress?, message?, started, elapsed_s}`. `result` returns the tool's normal result once done. |
| `hda` *(full profile)* | `action: create\|save\|unlock\|match\|install\|reload\|list`, plus action-specific fields (`path`, `library_path`, `name`, `label` or `description`, `version`, `min_inputs`, `max_inputs`; `limit`/`cursor` for `list`) | Thin wrappers over `createDigitalAsset`, `definition().updateFromNode`, `allowEditingOfContents`, `matchCurrentDefinition`, `hou.hda.installFile/reloadFile/loadedFiles`. |
| `usd_stage` *(full)* | `lop_path`, `prim = "/"`, `depth = 1`, `include: [attributes, xform, bindings, layers]`, `time?`, `limit` | Traverses `lop.stage()` read-only. Attribute values at `time` for primitive types; arrays summarised by length. |
| `pdg` *(full)* | `action: cook\|status\|workitems\|cancel\|dirty`, `top_path`, `block = false`, `timeout_s = 30`, `limit`, `cursor` | `cookWorkItems(block)` as a job; `status` from `getPDGNode()`; `workitems` paged with state and output files. |
| `events` *(full)* | `since = 0`, `limit` | Host-side ring buffer of hip events and node events (`ChildCreated`, `NameChanged`, `ParmTupleChanged` on nodes the agent touched, `BeingDeleted`) with a monotonic sequence. For "what did the user change since my last call". |

Count: 2 session + 4 hip + 10 node/network + 2 parm + 4 cook/geo + 2 visual + 1 code +
2 types + 4 state/job = **31 in `core`**, plus 4 in `full` = 35.

### 4.8 Resources, prompts, instructions

**Resources** (user-attachable context; every critical read is also a tool):

- `houdini://status` (same as `houdini_status`)
- `houdini://node/{path}` (`node_info` default includes)
- `houdini://node/{path}/parms`
- `houdini://node/{path}/geo`
- `houdini://nodetype/{category}/{name}`
- `houdini://job/{id}`
- `hocuspocus://guide` — the operating manual below in full, with examples

**Prompts** (slash commands in Claude Code): `inspect_scene`, `build_sop_chain`,
`debug_red_node`, `turntable_preview`.

**Server `instructions`** (≤ 400 words, shipped in `initialize`; the text lives in
`bridge/instructions.py` and a unit test enforces the cap):

> HocusPocus drives a live Houdini. Identity is Houdini paths. Start with
> `houdini_status`; if nothing is connected, `houdini_connect` can launch Houdini (GUI or
> headless hython) or attach to a running one by pid. Build with `node_create` (batch,
> with parms and inputs) or `network_build` (whole graph from the `network_describe`
> format). Read with `node_info` and `network_describe`. Change values with `parm_set`;
> tuple paths like `.../t` take lists, component paths like `.../tx` take scalars;
> expressions go in `expression`. After building, call `cook` or read `errors` in
> results, then `geo_info` to check counts and bounds, and `viewport_capture` to look at
> it. Every mutating call is one undo step. Hip tools refuse to discard unsaved work
> unless told to. Long cooks and renders return a `job_id`; poll it with `job`. When no
> tool fits, `houdini_python` runs `hou` code. Results are compact: non-default parms
> only, lists paged with `cursor`; `truncated: true` means the response budget cut a
> list, so page or narrow the query. Errors carry `code`, `hint` and `candidates`; read
> them and adjust. `delivery_unknown` means the call may or may not have run: inspect
> state before repeating it. `_meta.scene_generation` changes when the scene is cleared
> or loaded, so cached paths may be stale.

---

## 5. Houdini idioms the implementation must honour

Verified in review 04 against 22.0.466; each is a test case.

1. **Parm vs tuple.** `node.parm("t")` is `None`; `parmTuple("t")` works; `parm("tx")`
   works. Tools accept both and say which they used.
2. **`set()` does not clear animation.** On an expression or keyed parm, `set(v)` adds a
   key or is ignored. `parm_set` defaults to `animation: replace`
   (`deleteAllKeyframes()` first) and reports `wrote_keyframe`.
3. **`cook(force=True)` raises on error.** Catch `hou.OperationFailed`, then read
   `errors()`, `warnings()`, `messages()`. Uncooked nodes report `()`; cook first.
4. **Type names resolve by namespace order.** `copytopoints` → `copytopoints::2.0`.
   Report the resolved type and `is_current_version` in search.
5. **Menus.** `eval()` is the index; `evalAsString()` is the token. Return both; accept
   token or label on set.
6. **Strings.** Return `unexpandedString()` and `evalAsString()` for path-like parms.
7. **Named inputs.** `inputNames()` / `inputLabels()` exist; `setNamedInput` exists;
   `setNextInput` for merge-style. `InvalidInput` on out-of-range → `invalid_input` with
   labels.
8. **Load warnings throw.** `hipFile.load(..., ignore_load_warnings=True)` and report
   them.
9. **`hasUnsavedChanges()` can be stale right after a programmatic save.** Re-read after
   the `AfterSave` event before reporting `dirty`.
10. **`hou.data` is the graph format.** `childrenAsData(inputs=True, flags=True,
    position=True)` ↔ `setChildrenFromData()` round-trips wiring, expressions and flags
    with non-default parms only. Do not invent another.
11. **Headless differences.** No `hou.ui`, no `hdefereval`, no flipbook, `hou.playbar`
    frame range works, OpenGL ROP works (first render ~7 s), `hou.undos` works.
12. **Exit cleanly.** `os._exit` in hython segfaults in PDG teardown; the host must
    stop its listener and let the interpreter exit normally.
13. **Node identity across renames.** Offer `node.sessionId()` in `node_info` as
    `session_id` so agents can re-find renamed nodes within a process; never require it.
14. **Don't write userData into user scenes** except the optional `tag` on
    `network_build` (`hocuspocus:tag`) that the user asked for.
15. **Categories.** `Chop, ChopNet, Cop, Cop2, CopNet, Data, Director, Dop, Driver, Lop,
    Manager, Object, Shop, Sop, Top, TopNet, Vop, VopNet`. Discovery covers all of them.
16. **`setChildrenFromData` is lenient and destructive by default.** It silently skips
    unknown types, unknown parms, unresolvable input sources and out-of-range input
    indices; it defaults to `clear_content=True` (deleting the parent's existing
    children); and it puts every input entry without `to_index` on input 0.
    `network_build` validates first, always passes `clear_content=False`, and fills a
    missing `to_index` from the entry's list position.
17. **`hou.setFps` rescales the frame range.** By default it keeps the range's duration
    in seconds and moves the end frame. `time` calls `hou.setFps(fps, False, False,
    True)` and sets fps before the range.
18. **Errors outlive their cause until `errors()` is read.** After a broken expression
    (`$F*(`) is replaced by a constant (`set`, `revertToDefaults`), the next cook of that
    node succeeds but `errors()` still returns the old message, and every downstream cook
    then fails with "Invalid source" — forced or not — until the node itself is cooked
    again. Reading `errors()` (or `warnings()`) *before* that cook avoids it; a node
    already in that state clears with one more `cook(force=True)`. Replacing the
    expression with another expression is not affected. `_diag.collect_problems` reads
    errors before every cook, force-cooks a node (and errored upstream nodes, in Sop, Lop,
    Cop and Chop networks) whose errors predate a cook that is not pending, and says
    `hint: "...cook with force: true"` when it skipped that because the last cook took
    over 2 s.

---

## 6. Session and project-file management

What "fluent session management" means in practice:

- **Know where you are.** `houdini_status` always answers: which Houdini (pid, label,
  version, GUI or headless), which hip (`path`, `name`, `dirty`, `is_new`), `$HIP`,
  `$JOB`, `$HIPNAME`, frame, fps, range, recent files, scene generation.
- **Open, save, save-as, increment, backup, merge** with the exact semantics of
  `hou.hipFile`, plus safety: nothing discards unsaved work without `on_unsaved:
  discard`. `save` with an untitled scene and no path fails with a hint.
- **Pick or start a Houdini.** `houdini_connect` lists, attaches, and launches (GUI with
  a hip, or headless hython for batch work). A headless worker is a first-class target
  for renders and validation while the user keeps working in the GUI.
- **Survive restarts.** The bridge never dies with Houdini. Calls during the gap return
  `houdini_offline`. The scene generation tells the agent its cached paths may be stale.
- **Paths are never redacted.** Save returns the real path. Status returns the real
  path. If `approved_roots` is set, the error says which roots are allowed.

---

## 7. Long operations: jobs

Cooks, renders, PDG graphs and sims can exceed any sane synchronous timeout. Rule:
synchronous up to `job_threshold_s` (10 s), then the call returns `{job_id, state:
"running"}` and the agent uses `job`. Jobs run on host-side threads **but call `hou`
only through the executor**, so they still respect the main-thread rule; a job is a
sequence of short main-thread steps (e.g. per-frame render) with progress between them.
Progress notifications are emitted by the bridge when the client supplied a
`progressToken`. Jobs are not durable across a Houdini restart; `job status` after a
restart returns `job_not_found` with that explanation.

---

## 8. Visual feedback

The agent must be able to **see**. `viewport_capture` returns an image in the MCP
result, never only a path. Two sources: the GUI SceneViewer flipbook (what the user
sees, including guides) and the OpenGL ROP (deterministic, headless-capable, explicit
camera). `render` covers Karma and other ROPs as jobs with a thumbnail. Images are
PNG, downscaled to ≤ 1024 px on the long side, and also written to
`<state_dir>/captures/` with the path returned. Image bytes count toward the client's
output limit, so one image per call.

**Headless OpenGL renders run in a child hython.** Verified on 22.0.466: in hython the
second `RopNode.render()` of any OpenGL ROP in one process segfaults in the Vulkan
viewport renderer, whatever the node, frame or output; one multi-frame `render()` is
fine. So headless, `viewport_capture` and `render` of OpenGL ROPs snapshot the scene
(`saveChildrenToFile` per manager: no hip save, no event side effects) and render it in a
short-lived child `hython` (about 3 s per call). In the GUI, OpenGL ROPs render
in-process; every other ROP type renders in-process frame by frame through the
executor.

---

## 9. Error model

Every tool failure is an `isError: true` result:

```json
{"code": "parm_not_found", "message": "No parm 'size' on /obj/geo1/box1.",
 "hint": "size is a tuple; use the tuple path to set all components or sizex/sizey/sizez.",
 "candidates": ["sizex", "sizey", "sizez", "scale"], "hou_exception": null}
```

Stable codes (the complete set; adding one is a design change):

| code | when | retryable |
|---|---|---|
| `houdini_offline` | no live instance; names the pid (and hip) the bridge was driving if it exited, and says its unsaved changes are lost | after connect (`retryable: false` when nothing is running) |
| `houdini_busy` | main-thread timeout | yes |
| `delivery_unknown` | request sent, response lost (becomes `houdini_offline` "exited while running <tool>" when the process is gone within 1.5 s) | inspect first |
| `version_mismatch` | host `hp/vN` ≠ bridge | after reinstall |
| `invalid_argument` | schema / shape | no |
| `node_not_found` | path | no |
| `parm_not_found` | parm/tuple | no |
| `node_type_not_found` | type (with candidates) | no |
| `invalid_input` | wiring index/name (with labels) | no |
| `invalid_value` | type/range/menu mismatch | no |
| `name_collision` | create/rename/network_build | no |
| `locked` | locked HDA / permission | after unlock |
| `cook_failed` | cook raised; errors attached | after fix |
| `unsaved_changes` | hip_new/open without consent | with `on_unsaved` |
| `file_not_found` | hip/hda/merge path | no |
| `path_not_allowed` | `approved_roots` | no |
| `ui_required` | GUI-only tool headless | no |
| `python_disabled` / `read_only` | config | no |
| `job_not_found` | job id | no |
| `cancelled` | job cancelled | — |
| `internal` | anything else; **must** carry `hou_exception` and traceback in `detail` | maybe |

Protocol-level JSON-RPC errors are reserved for unknown tools (the message suggests the
nearest names, also in `data.candidates`) and malformed requests.

---

## 10. Packaging, install, repository layout

### 10.1 Layout

```
pyproject.toml                 # name hocuspocus, hatchling, requires-python >=3.11
                               # [project.scripts] hocuspocus = hocuspocus.cli:main
                               #                   hocuspocus-mcp = hocuspocus.bridge.__main__:main
                               # dependencies: mcp>=2.3,<3 ; optional: dev (pytest, pytest-timeout, ruff)
                               # the wheel ships houdini/ as hocuspocus/_houdini
src/hocuspocus/
  __init__.py  version.py
  cli.py                       # install-houdini, uninstall-houdini, doctor, client-config, docs, version
  tools/                       # shared by host and bridge; stdlib only
    catalog.py                 # the single source of truth for the tool surface
    errors.py                  # error codes + ToolError
    docs.py                    # renders docs/tools.md; tools/list size; example validator
    paths.py                   # state dir (instances/, logs/, captures/)
  host/                        # INSIDE Houdini. stdlib only. `import hou` lazily.
    __init__.py                # start(), stop(), status(), autostart()
    __main__.py                # hython -m hocuspocus.host
    config.py executor.py server.py dispatch.py runtime.py registry.py jobs.py budget.py undo.py
    tools/ registry.py _diag.py session.py hip.py code.py nodes.py network.py parms.py
           cook.py types.py geo.py visual.py state.py hda.py usd.py pdg.py events.py
  bridge/                      # OUTSIDE Houdini. mcp SDK.
    __main__.py server.py client.py instances.py launch.py local_tools.py
    validate.py budget.py config.py instructions.py
houdini/                       # Houdini package payload; NOT the repo root
  hocuspocus.json.template     # -> <prefs>/packages/hocuspocus.json
  scripts/python/uiready.py    # GUI autostart (verified location for Houdini 22)
  toolbar/hocuspocus.shelf     # HP Status / HP Start / HP Stop
tests/
  conftest.py  unit/  integration/ (with its own conftest.py)  e2e/
docs/
  BIBLE.md  quickstart.md  tools.md (generated)  CONTRIBUTING.md
  redesign/README.md  redesign/progress.md  redesign/review/*.md  redesign/evidence/
README.md  LICENSE  CHANGELOG.md
.github/workflows/ci.yml  houdini.yml
```

The repo root is **not** on `HOUDINI_PATH`: hython puts `$HIP` (its cwd) on
`HOUDINI_PATH`, so a `scripts/python/pythonrc.py` at the root auto-runs in any hython
started from the repo. The payload lives in `houdini/`.

The Python directory is version-neutral (`src/`) and reaches Houdini via an explicit
`PYTHONPATH` entry in the package JSON. Houdini 22 is Python 3.13; the host code is
written to run on 3.11+ so a 3.11 Houdini build also works.

### 10.2 Install (the three commands)

```bash
uv tool install -e .                  # from a checkout; `uv tool install hocuspocus` once on PyPI
hocuspocus install-houdini            # writes the package JSON, copies host code
claude mcp add -s user hocuspocus -- hocuspocus-mcp
```

`-s user` registers the server for every directory; without it Claude Code registers it
for the current project only.

`install-houdini`:

1. Resolves the pref dir: `--prefs`, else `HOUDINI_USER_PREF_DIR`, else asks hython
   (`hou.homeHoudiniDirectory()`) from the detected HFS, else the platform default.
2. Copies `src/hocuspocus` (all of it; Houdini only imports `host` and `tools`) to
   `<prefs>/hocuspocus/<version>/python/` and the `houdini/` payload to
   `<prefs>/hocuspocus/<version>/houdini/`, and writes `<prefs>/packages/hocuspocus.json`
   pointing at both. `--dev` points at the checkout's `src/` and `houdini/` instead of
   copying.
3. Records the pref dir in `<state_dir>/install.json` so the bridge can find
   `hocuspocus.toml` without asking hython (§3.7).
4. Prints what it did and the restart note. Idempotent; replaces older versions.

`hocuspocus doctor` checks: HFS found, Houdini version, the resolved pref dir, which
`hocuspocus.toml` the bridge reads, package JSON present and pointing at an existing
dir, host/bridge version match, live instances with a `/health` round trip, and prints
the `claude mcp add` / Codex config lines. `hocuspocus version` prints the bridge, RPC,
`mcp` and Python versions. `uninstall-houdini` removes the package JSON, the copied
versions and the `install.json` record.
`hocuspocus client-config codex|claude` prints the snippets. `hocuspocus docs tools`
regenerates `docs/tools.md`.

Houdini version policy: `>= 22.0` supported; builds other than the tested list print a
warning in `doctor` and the host log, never a refusal.

---

## 11. Testing

pytest everywhere. Markers `unit`, `houdini`, `e2e`; `conftest.py` finds hython via
`HOUDINI_HYTHON`, `HFS`, or the newest `Side Effects Software/Houdini 22.*`, and skips
`houdini`/`e2e` when absent so contributors without a licence get green.

| Tier | Runner | Scope | Budget |
|---|---|---|---|
| `tests/unit` | system Python | catalogue integrity (every tool has impl, schema, annotations, ≤ 80-word description, `tools/list` ≤ 48 KB), bridge instance selection and offline behaviour with a fake host, error mapping, budget truncation, config parsing, `cli` path resolution | < 10 s |
| `tests/integration` | `hython -m pytest` | in-process host: one `hou` session per run, `hipFile.clear()` per test, every tool exercised against real nodes; the idioms in §5 each have a test | < 90 s |
| `tests/e2e` | system Python spawning hython | official `mcp` client → `hocuspocus-mcp` stdio → `hython -m hocuspocus.host` on an ephemeral port with an isolated `HOUDINI_USER_PREF_DIR` and a neutral cwd: a stdio round trip, review 06 tasks 2, 3, 4, 6 and 9 as one scripted scenario, and a bridge launch that checks the work dir | < 60 s |
| GUI (manual; no `tests/gui` directory) | checklist | package loads in `houdinifx`, autostart, viewer capture; run before a release and logged in `docs/redesign/progress.md` | — |

Hygiene rules: never write into the repo at test time; never use port 37219; isolated
pref dir per run; clean interpreter exit. CI: GitHub Actions `windows-latest` and
`ubuntu-latest` run `ruff check`, `ruff format --check`, the unit tier and a
`docs/tools.md` freshness check (`ci.yml`); a self-hosted Windows runner labelled
`houdini` runs integration + e2e nightly, on manual dispatch and on PRs labelled
`houdini` (`houdini.yml`).

---

## 12. Documentation set

`README.md` (what, 3-command install, one screenshot-worthy example, link to docs),
`docs/quickstart.md` (5 minutes to a box with a mountain and a screenshot),
`docs/tools.md` (generated from the catalogue with examples), `docs/BIBLE.md` (this),
`docs/CONTRIBUTING.md` (layout, tests, how to add a tool: catalogue entry + host impl +
integration test + regenerate docs, release steps), `CHANGELOG.md`. `docs/redesign/`
holds the historical review and evaluation record, indexed by its `README.md`. Everything else in `docs/` from 0.9
is archived with the tag, not carried forward.

---

## 13. Migration and the cut

1. Tag the current `master` as `v0.9-archive` (HocusScript, documents, source
   workspace, production qualification and all 0.9 docs live on there forever).
2. Build 1.0 on branch `redesign/v1` with the layout in §10. The old tree is deleted in
   the same branch once the integration tier is green: `python3.11libs/`, `scripts/`,
   `python_panels/`, `editors/`, `toolbar/` (replaced), `package/`, `config/`, `tests/`
   (replaced), and every `docs/*.md` except `BIBLE.md` and `redesign/review/`.
3. Scenes authored with 0.9 keep working: they are ordinary Houdini scenes.
   `hpmcp.*` userData left by 0.9 is inert and ignored.
4. `CHANGELOG.md` 1.0.0 states plainly: HocusScript, `.hocus`, network documents, the
   source workspace and production qualification are removed; use `network_build` with
   Houdini's native data format or `houdini_python`.
5. Version is **1.0.0**. The 0.9 compatibility policy is void for 1.0.

---

## 14. Implementation roadmap

Each milestone ends with its integration tests green and a short note in
`docs/redesign/progress.md`. Work is parallel within a milestone where files do not
overlap (one agent per host tool family).

| # | Milestone | Contents | Exit criterion |
|---|---|---|---|
| M0 | Foundations | Tag + branch; `pyproject`; layout; `tools/catalog.py` with **all** entries from §4 (schemas, annotations, descriptions); `tools/errors.py`; host `executor`, `server`, `registry`, `config`, `undo`, `budget`; host tools `session`, `hip`, `code`; bridge with `MCPServer`, catalogue registration, instance selection, launch, `houdini_status`, `houdini_connect`; `cli install-houdini/doctor`; `tests/unit` + `tests/integration` harness | `uv tool install -e . && hocuspocus install-houdini && claude mcp add …` works; `houdini_status`, `hip_*`, `houdini_python` pass integration tests in hython; GUI autostart verified manually |
| M1 | Authoring core | `nodes`, `network`, `parms`, `cook`, `types` families | Review 06 tasks 2, 3, 4, 6, 9 pass as e2e scenario with ≤ 12 calls |
| M2 | Seeing | `geo`, `visual` (capture + render), `jobs` | Task 8 returns an image headless; `geo_read` stats on 1M points < 2 s |
| M3 | State and contexts | `state` (`undo`, `time`, `selection`), `hda`, `usd`, `pdg`, `events`; `full` profile | integration tests per tool |
| M4 | Cut-over and docs | Delete the 0.9 tree; README, quickstart, generated `tools.md`, CONTRIBUTING, CHANGELOG; CI workflows; prompts and resources; `instructions` | fresh clone → three commands → quickstart works; `tools/list` ≤ 48 KB asserted |
| M5 | Hardening | A fresh agent repeats the review-06 friction log against 1.0 and scores it; fix the top papercuts; GUI smoke in `houdinifx`; PR to `master` | Scorecard ≥ 4/5 on every dimension; merged |

---

## 15. Decision log

- **D1** Two processes; stdlib host, SDK bridge. *Dependency isolation and offline tools.*
- **D2** Official `mcp>=2.3` SDK, `MCPServer`, stdio only. *No hand-rolled protocol.*
- **D3** Ephemeral ports + registry files; no fixed port. *Multi-instance correctness.*
- **D4** Tool names `snake_case`, no dots, 35 tools, 31 in `core`. *Client compatibility, model recall.*
- **D5** Direct primitives are the surface; HocusScript and network documents are deleted, not deprecated. *Nobody used them; they cost 60 % of the code.*
- **D6** Declarative graph build uses Houdini's `hou.data` format verbatim. *Native, round-trips, no schema to maintain.*
- **D7** `houdini_python` is on by default with an off switch. *The agent already has a shell; a blocklist is theatre; the undo group and output cap are the real guards.*
- **D8** Failures are `isError` results with a closed code set. *Agents self-correct from results, not protocol errors.*
- **D9** Non-default parms only; 16 KB default budget; cursors. *Token cost was the #1 usability failure.*
- **D10** `parm_set` defaults to replacing animation and says so. *`set()` on a keyed parm silently does nothing useful.*
- **D11** Hip tools refuse to discard unsaved work without consent. *Agent safety.*
- **D12** Houdini `>= 22.0`, warn on untested builds. *Exact pins blocked the installed Houdini.*
- **D13** `install-houdini` copies the package into the pref dir; `--dev` links the checkout. *Houdini must never see the bridge's venv.*
- **D14** pytest with a real-Houdini integration tier; delete nothing until it is green. *0.9 had zero tools tested against Houdini.*
- **D15** Version 1.0.0 on `redesign/v1`; `v0.9-archive` tag. *Clean break, history preserved.*

### Verified deviations (M5 reconciliation)

Facts found while implementing, now reflected above:

- GUI autostart lives at `houdini/scripts/python/uiready.py` (§10.1).
- `hasUnsavedChanges()` is always `True` in hython; the host tracks dirtiness headless (§3.2).
- A second OpenGL ROP render in one hython segfaults; headless OpenGL renders use a child hython (§8).
- `undo`, `time`, `selection`, `hda`, `cook`, `pdg`, `render`, `job`, `viewport_capture` register with `scene=False` (§4.1).
- One `hocuspocus.toml` configures host and bridge; `HOCUSPOCUS_*` env wins (§3.7).
- `setChildrenFromData` skips unknown types and parms silently, defaults `clear_content=True`, and puts inputs without `to_index` on input 0 (§5.16).
- `hou.setFps` rescales the frame range unless told not to (§5.17).
- The surface is 35 tools, 31 in `core` (§4.7, D4).
- All cursors, including `geo_read.next_cursor`, are opaque strings (§4.1).

---

### Known limitation: launch lifetime

A Houdini started by `houdini_connect {launch}` is launched detached (new process group, and breakaway from the job object where Windows allows it), but in the verified setup (review 08) it still exited when the bridge that launched it exited. Treat it as owned by the bridge: it ends when the MCP client stops the bridge (end of a session, or a one-shot script exiting), and its unsaved work is lost. This is acceptable for interactive sessions; agents should `hip_save` before a session ends, or attach to a Houdini the user started.

## 16. Non-goals for 1.0

HocusScript or any custom language; multi-user or remote (non-loopback) access;
Streamable-HTTP direct-to-Houdini transport; APEX graphs; a Houdini UI beyond a status
shelf tool; vendoring the MCP SDK into Houdini; supporting Houdini 21 or earlier;
Linux/macOS **testing** (the code must not be Windows-only, but 1.0 is qualified on
Windows only).
