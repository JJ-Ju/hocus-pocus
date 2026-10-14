# HocusPocus Design Bible

**Version:** 1.3 (2026-10-12, branch `release/1.3`; 1.0, 1.1 and 1.2 shipped the same
day). This document remains the design authority for 1.x. Rows and sentences marked
(1.1), (1.2) or (1.3) changed in that release. The contract decisions are D16 to D20 for
1.1, D21 to D24 for 1.2 and D25 to D29 for 1.3 (§15).
**Status:** authoritative. When code and this document disagree, one of them is wrong
and the disagreement is a bug to fix, not a fact to live with.

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
`hou.undos.group("HocusPocus: <tool> <summary>")` (ASCII, at most 100 characters).
Read-only tools never open a group. `undo` exposes the label history so users and agents
can revert "the last agent action". A call that fails is rolled back by undoing its group
after it closes; the group reports whether that happened (false when undo is disabled or
the undo failed), and a tool error whose `detail.rolled_back` is `null` gets that value.

**HTTP server.** `http.server.ThreadingHTTPServer` bound to `127.0.0.1` on an
**ephemeral port** (`port=0`), `allow_reuse_address = False`. Routes:

| Route | Method | Purpose |
|---|---|---|
| `/hp/v1/health` | GET | `{ok, pid, houdini, generation}` — no auth, no `hou` call |
| `/hp/v1/call` | POST | `{tool, args, timeout_s}` → tool result (see §3.4) |
| `/hp/v1/jobs/{id}` | GET | job status/result |
| `/hp/v1/calls/{request_id}/jobs` | GET | snapshots of the jobs started by the call with that `request_id` (progress, 1.1) |
| `/hp/v1/shutdown` | POST | stop the host (not Houdini) |
| `/hp/v1/quit` | POST | `{on_unsaved}` → quit Houdini after the unsaved check (`hou.exit(suppress_save_prompt=True)` in the GUI; headless, the hython main loop ends) (1.2) |

Auth: `Authorization: Bearer <token>`; 401 otherwise. `Origin` and `Host` headers, if
present, must name a loopback host; 403 otherwise (the `Host` check stops DNS rebinding
from reading `/health`). Request body cap 4 MB; idle connections time out after 60 s.
The host runs only the tools of its own `profile` (§3.7): a `core` host answers a
full-profile tool with `invalid_argument` and the hint to set `profile = "full"`.

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
deletes it. Since a pid can be reused after a crash, the bridge (and `doctor`) also
deletes an entry whose pid is alive but whose port refuses connections, rejects its token
(401), or answers `/health` with another pid, and selects again.

**Dirty tracking.** Verified on 22.0.466: in hython `hou.hipFile.hasUnsavedChanges()` is
always `True`, even right after a load, clear or save. Headless, the host therefore
tracks dirtiness itself: the dispatcher marks the scene dirty after every successful
mutating call, the `scene=False` tools mark it where they change the scene, and save,
load and clear mark it clean. In the GUI the host asks Houdini.

**Scene generation.** A monotonically increasing integer bumped on
`AfterClear`, `AfterLoad`, `AfterMerge`. Returned in every tool result's `_meta` as
`scene_generation`. Agents that cache node paths can detect that the world changed.

**Per-instance state.** Logs at `<state_dir>/logs/host-<pid>.log` (rotating, 5 MB, two
backups). 1.4 (review 22 finding 4): every call writes one INFO line, `<timestamp> INFO
<logger>: call <tool> <elapsed> ms main <main_thread_ms> ms ok|<error code> pid
<pid>` (~110 B), so a session or an incident can be reconstructed host-side.
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
   `houdini_connect`; never another one in its place, §3.6) → the only live instance →
   with several live and none pinned (1.3, review 19 papercut 2), calls that change a
   scene refuse with `ambiguous_instance` (the candidates, and the `houdini_connect
   {"pid": …}` call for each), and reads go to the preferred instance (a GUI session
   first, then the most recently started) with the warning in `_meta.warnings` and in the
   result as `_instance: {pid, label, ui, warning}`. "Changes a scene" is every tool not
   `read_only` except the reading forms of the `scene=False` tools (`time` and
   `selection` without arguments, `job` status/result/list, `undo history`, `hda list`,
   `pdg` status/workitems) and `viewport_capture`. Every result a host answered (ok or
   error, `houdini_status` and `houdini_connect` included) carries `_meta.instance:
   {pid, label, name?}`. If none: `code: houdini_offline` with the hint "call
   houdini_connect with launch to start one".
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
{"ok": true,  "result": {...}, "_meta": {"scene_generation": 3, "undo_label": "HocusPocus: parm_set 2 parms", "elapsed_ms": 12, "timing": {"main_thread_ms": 9.6, "queue_ms": 0.2}}}
{"ok": false, "error": {"code": "parm_not_found", "message": "...", "hint": "...", "candidates": ["sizex","sizey","sizez"], "hou_exception": "hou.OperationFailed: ..."}, "_meta": {...}}
```

The bridge maps `ok:false` to an MCP `isError: true` result whose text is the error
JSON (and whose `structuredContent` is the error object when `result_content` is `both`
or `structured`, §4.1). `_meta` is passed through as
tool-result `_meta`. 1.4 (review 22 finding 2): `_meta.timing` is on every call, success
or error: `main_thread_ms` is the time the tool ran on Houdini's main thread (0 for a tool
that runs off it, such as `job` or `events`) and `queue_ms` the wait for the main thread
before that, so latency drift can be split between the bridge, the queue and Houdini.
The protocol version `hp/v1` is in the path; incompatible changes
bump it and the bridge refuses to talk to an older host with `code: version_mismatch`
and the hint "run `hocuspocus install-houdini` and restart Houdini".

### 3.5 The shared catalogue

`hocuspocus/tools/catalog.py` is a stdlib-only module that defines every tool once:
name, description, input JSON Schema, output JSON Schema (where stable), MCP
annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint=false`),
`profile` (`core` or `full`; 1.3: `MINIMAL_TOOLS` names the 14 core tools of the
`minimal` profile, listed in §4.1, and the three profiles nest, minimal ⊂ core ⊂ full),
`headless_ok`
(bool), and `bridge_local` (bool). The host
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
  lifetime only. A pin is sticky (1.3, review 19 papercut 1): when the pinned Houdini
  exits, every call returns `instance_lost` (naming the dead pid and label and the live
  candidates as `{pid, label, ui, hip}`) and `houdini_status` reports `connected: null`
  with `lost: {pid, label}`; the bridge never moves the pin to another instance. Only an
  explicit `houdini_connect` (`{pid}`, `{launch}`, `{}` for automatic selection, or
  `{disconnect: true}`) clears it.
- **Restart.** Houdini closes → registry entry disappears → calls return
  `houdini_offline` → Houdini starts → new entry → bridge auto-selects it when it is the
  only one. No `/mcp reconnect` required.
- **Shutdown.** `BeforeQuit` removes the registry entry and stops the listener.

### 3.7 Configuration

Optional file `$HOUDINI_USER_PREF_DIR/hocuspocus.toml`, env overrides
`HOCUSPOCUS_*`, CLI flags last. Everything has a default; the file is not required.

**One toml serves both processes, and the environment wins.** The host reads every key;
the bridge reads `profile`, `max_response_bytes`, `default_timeout_s`, `hfs` and
`result_content` from the same file and ignores the rest (the host skips the
bridge-only `hfs` and `result_content` without a warning). Inside Houdini the pref dir is
`hou.homeHoudiniDirectory()`. The bridge starts on every client launch and cannot afford
a hython query, so it looks in `HOUDINI_USER_PREF_DIR` (`__HVER__` read as `22.0`) when
it is set; otherwise it reads the toml from the first candidate that has one: the
`pref_dirs` that `install-houdini` records in `<state_dir>/install.json`, in order, then
the platform default locations (1.2.1: on Windows Houdini uses `%HOME%\houdini22.0` when
started with `HOME` set and `Documents\houdini22.0` without, so several may be in use).
A `HOCUSPOCUS_<KEY>` variable overrides the file in either
process.

```toml
autostart = true            # GUI sessions start the host on uiready
allow_python = true         # houdini_python / hscript escape hatch
read_only = false           # refuse all mutating tools
approved_roots = []         # if non-empty, file paths for hip/hda/render must be under these ($VAR, ~ expanded; links resolved)
max_response_bytes = 16384
default_timeout_s = 30
job_threshold_s = 10        # cook/render longer than this become jobs
profile = "core"            # minimal | core | full: minimal is 14 tools (§4.1), full adds usd_stage, pdg, hda, events; the host refuses tools outside its profile
log_level = "INFO"
hfs = ""                    # bridge: explicit Houdini install dir for launch
result_content = "text"     # bridge: text | both | structured (§4.1)
```

`HOCUSPOCUS_WORK_DIR` (environment only) is where a Houdini that `houdini_connect {launch}`
starts (`hocuspocus launch` uses its own cwd or `--work-dir`, §10.2), and so the `$HIP` and `$JOB` of its untitled scene; default the user's home
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
  defaults stated in the schema's `default` (1.2: not repeated in the description). Batch tools take `items: [...]` and return
  `results: [...]` in the same order; one failing item fails the whole call and rolls
  back the undo group unless `partial: true`. Every batch error (and each failed row's
  `error` with `partial`) has one shape: the message starts `items[i] (<path>): ` and
  `detail` carries `{item, path, rolled_back}`, where `rolled_back` is true only when every
  change the call (or, with `partial`, the item) had made was actually undone.
- **Responses:** compact JSON in the text block. 1.0 also sent the same JSON as
  `structuredContent` because clients vary in which they feed the model; measured for 1.1,
  Claude Code feeds the model only the text block, so the structured copy doubled every
  result on the wire for nothing. The bridge setting `result_content` (§3.7) now decides:
  `text` (default) sends no `structuredContent` and therefore declares no `outputSchema`
  (the spec requires structured results whenever one is declared); `both` is the 1.0
  shape, with `outputSchema` declared where the shape is stable; `structured` keeps the
  data in `structuredContent` and puts a one-line summary in the text block
  (`<tool>: ok`, or `<code>: <message>` for an error). Error results follow the same rule;
  images are image blocks in every mode. Key casing is `snake_case` in both directions.
- **Budget** (1.4): CI-tested (`test_tools_list_budget`) on the serialised `tools/list`
  result of the full profile, in the two shapes a client can receive: with the default
  `result_content = "text"`, what clients see by default (names, descriptions, input
  schemas, annotations; no output schemas), it is ≤ 32,000 bytes; with `both` (output
  schemas declared too) ≤ 44,000 bytes. Names, descriptions and input schemas alone stay
  ≤ 48 KB. The test prints all six sizes (three profiles × two modes); at 1.4.0 they were
  14.2/27.1/30.5 KB (`text`, minimal/core/full) and 20.4/36.6/40.0 KB (`both`). Until 1.3
  the cap was on `both` alone, with a 40,000 B headroom target that every new argument
  fought although default clients never received the output schemas it counted. Each
  description ≤ 60 words: what the tool does and what the model must know to pick it.
  Argument-level detail (shapes the schema cannot state, edge cases, defaults the schema
  already declares) lives in the spec's `notes`, which `docs/tools.md` and the resource
  `hocuspocus://tools` render and `tools/list` leaves out; examples live there too.
  1.3: an argument's schema `description` is at most 12 words (a unit test,
  `test_argument_detail_lives_in_notes`); anything longer goes in `notes`, so a new
  argument costs its name and type, not its explanation.
  Annotations go out without hints equal to the MCP defaults (`readOnlyHint: false`,
  `idempotentHint: false`, and `destructiveHint`/`idempotentHint` on read-only tools), which
  a client reads as the same values. Default result ≤ 16 KB. List tools take `limit` (default 50) and
  `cursor`; results carry `next_cursor` when more exist and `total` when cheap. A budget
  cut never loses rows: the bridge sends `max_response_bytes` in the `/hp/v1/call`
  envelope, list tools end a page at that budget with `next_cursor` at the first row not
  returned, and the bridge trims a still-oversized page only when it can rewrite the cursor
  to resume after the last row kept: an integer offset (`next_cursor` = offset + rows kept),
  `node_find`'s `after:<path>`, `network_describe`'s `after:<name>`, or `events`'
  `next_since` (`<pid>:<seq>` of the last kept event, with `more: true`; 1.4, review 22
  finding 1: the host's cursor skipped every event the cut dropped). Any other page is
  returned whole with `over_budget: true`. `events` also ends its pages at the budget.
- **Profiles** (1.3): `minimal ⊂ core ⊂ full`, set by `profile` (§3.7); the bridge lists
  and the host allows only the profile's tools. `minimal`, for clients with a small
  context, is `houdini_status`, `houdini_connect`, `hip_open`, `hip_save`, `node_find`,
  `node_info`, `node_create`, `node_connect`, `parm_get`, `parm_set`, `cook`, `geo_info`,
  `viewport_capture` and `houdini_python` (14; 14.2 KB of `tools/list` against 27.1 KB
  for `core` and 30.5 KB for `full` in the default `text` mode). `houdini_python` covers
  what the others leave out.
- **Non-default only:** parm listings show parms where `isAtDefault()` is false unless
  `include_defaults: true`.
- **Locked HDAs** are opaque by default: `node_find`, `node_info` and
  `network_describe` do not descend into locked assets unless `recurse_locked: true`.
- **`locked` vs `hda_locked`** (1.1): `locked` always means a lock flag, the SOP hard-lock
  (`isHardLocked`, `flags.locked`) or a parm lock; `hda_locked` means the node is a locked
  asset or inside one (`node_info`, `network_describe`, `parm_get`, `hda`).
- **Every mutation result** includes, for each touched node: `path`, `type`, `errors`,
  `warnings` (after a non-forced cook of that node if it is cheap, else `cook_state:
  "not_cooked"`; errors left from before the change are rechecked with a forced cook,
  §5.18). The result also carries the scene's `dirty` flag after the call. 1.4 (review 22
  findings 2, 3): summary rows carry `cook_ms`, the time that cook took (Houdini's first
  cook of an HDA such as `mountain` is ~200 ms); `node_create {cook: false}` skips it; and
  `node_edit` never cooks (a rename recooked a mountain), reporting `cook_state` from
  `needsToCook()` and the errors already on the node.
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
| `houdini_status` | — | `connected: {pid, port, houdini, ui, hip: {path, name, dirty, is_new}, time: {frame, fps, range}, env: {HIP, JOB, HIPNAME}, scene_generation, host_version, memory: {rss_mb, peak_mb}}`, `instances: [{pid, port, label, houdini, ui, hip, started, launched_by, name?, selected, busy, jobs_running}]`, `lost?: {pid, label}`, `bridge_version`, `profile`, `read_only`, `allow_python` | Works offline (`connected: null`). Read-only. 1.3 (review 19 papercuts 4, 9): `selected` marks the pinned instance or the one reads go to; `busy` and `jobs_running` come from each host's `/health` (busy: its main thread has been held, by a call or a waiting one, for at least 1 s); `name` is set with `houdini_connect {pid, name}` and stored in the registry entry, which the host keeps on rewrites; `lost` names a pinned Houdini that has exited (§3.6); `connected.memory` is the Houdini process's resident and peak memory in MB from the OS counters, no psutil (review 17 P2-9). An untitled scene's `hip` carries `note: "$HIP is the launch directory until you hip_save."` |
| `houdini_connect` | `pid?`, `name?`, `launch?: {mode: gui\|headless, hip?, wait_s=90}`, `disconnect?: bool`, `quit?: bool`, `on_unsaved: fail\|save\|discard = fail` | the new `connected` block; `quit` returns `{quit, pid, exited, saved?}` | Launch uses `hfs` config or auto-detect. Headless launches `hython -m hocuspocus.host`. Both modes start in `HOCUSPOCUS_WORK_DIR` (default home, §3.7); `hocuspocus launch` starts in its own cwd or `--work-dir` instead (§10.2). A launched Houdini usually ends with the bridge that launched it (`launched.outlives_server` says; §15, launch lifetime); to keep one across sessions, start it with `hocuspocus launch` (§10.2, 1.1) and attach by `pid`. `quit` (1.2) closes the selected Houdini (or `pid`) through `POST /hp/v1/quit` after the `on_unsaved` check and forgets its registry entry. 1.3: `pid` or `launch` pins (§3.6), `{}` unpins; `name` labels the Houdini given by `pid` or `launch` (moved from any other instance that had it), and `{name}` alone pins the one with that name; a pid or name that is not running is `houdini_offline` with `retryable: false` and the live `candidates` as `{pid, label, ui, hip}`. |

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
| `node_info` | `paths: [..]`, `include: [parms, inputs, outputs, children, errors, flags, hda, comment, position, userdata]` default `[parms, inputs, errors, flags]`, `include_defaults = false`, `recurse_locked = false` | Per node: `path, name, type {name, category, version, description, help_url}`, `flags`, `inputs: [{index, name, label, from: {path, output}}]`, `outputs: [{index, name, to: [...]}]`, `parms` (compact: `name, value, raw?, expression?, keyed?, locked?, menu_token?`; `raw` only when it differs from `value`, strings over 200 characters as `{elided, head}` as in `parm_get`), `errors, warnings, messages, cook_state`, `children_count`, `hda_locked?` (true at or inside a locked asset), `hda: {hda_locked, definition, library, matches_definition}`, `position`, `comment`, `color`. |
| `node_create` | `items: [{parent, type, name?, parms?: {name: value\|{expression, language}\|{expr, lang}}, inputs?: [{index\|name, from, output=0}], flags?: {display, render, bypass, template}, position?: [x,y]}]`, `layout = "good_position"\|"none"`, `exact_type = false`, `cook = true` (1.4), `partial = false`, `return: summary\|full = summary` | One undo group. Type resolved like `createNode` (namespace order; `box` → current version). Unknown type → `code: node_type_not_found` with `candidates` from fuzzy match over the parent's category. Returns per item `{path, type, errors, warnings, cook_state}` (`return: summary`, the 1.1 default; identical error lists after the first become `errors_same_as: <path>`); `return: full` gives the `node_info` compact block, whose `parms` list only the parms the call set (values a creation script set, such as a light's ramps, are not the call's edits; `node_info` still reports them as non-default) and string values over 200 characters as `{elided: <chars>, head: <first 80>}`. `parms` go through the same engine as `parm_set`; an expression is `{expression, language}` as `parm_set` and the readers spell it, and the short `{expr, lang}` is accepted too. 1.3 (review 20 N2): as in `parm_set`, a plain set of a menu or toggle with a callback script adds a note to the row that the callback did not run, and `{value, press: true}` runs it after the plain values are set and the inputs are wired; the row then carries `side_effects: {parm: [old, new]}`. A type that `hou.NodeType.deprecated()` reports (the OpenGL ROP in 22.0) adds `deprecated: true` and a note with `deprecationInfo()`'s reason or replacement. A `block_end` whose `blockpath` is unset is paired as the Tab menu does (1.1, review 11 B12): with the nearest `block_begin` upstream through its inputs, else the only unpaired `block_begin` in the same network; the end's `blockpath` and `templatepath` and the begin's `blockpath` are set (where unset) to relative paths before anything cooks, and the row carries `paired_with`. |
| `node_delete` | `paths`, `keep_connections = true` (reconnect input 0 to outputs when possible) | Destructive. Returns `deleted: [paths]`. |
| `node_edit` | `items: [{path, name?, flags?, color?: [r,g,b], comment?, position?, lock?: bool (HDA allowEditingOfContents), bypass?, spare_parms?: {add?: [{name, type: float\|int\|string\|toggle\|menu\|button\|vector\|color, label?, default?, size?, min?, max?, menu_items?: [{token, label}], value_type?: string\|int, folder?, help?}], remove?: [names]}}]`, `partial = false` | Rename returns `old_path → path`. `spare_parms` (1.1, review 11 B9) builds `hou.*ParmTemplate`s and applies them with `parmTemplateGroup()` + `setParmTemplateGroup()` (a `folder` label is created when missing); it returns `spare_parms: {added: [parm paths], removed: [parm paths]}`. A `menu`'s `value_type` (1.2, review 12 papercut 3) is `string` by default, a `hou.MenuParmTemplate` whose value is the token (VEX `chs()`; `ch()` gives the item index), or `int`, a `hou.IntParmTemplate` with the menu whose value is the item index (`ch()`/`chi()`; `chs()` gives the index as text). A menu `default` is a token or an item index; a number that is no index but equals a token's text (`-1` for token `"-1"`) picks that token. Only spare parms can be removed; a name already on the node is `name_collision`; nodes inside a locked asset are refused with `locked` (a locked asset's own instance takes spare parms, like the wrangle's "Create spare parameters" button). Rollback restores the old template group and the removed parms' values. `parm_not_found` on a `null`, `subnet` or `geo` points here. |
| `node_copy` | `paths`, `to_parent`, `names?`, `with_inputs = true`, `position_offset?`, `return: summary\|full = summary` | `copyItems`/`copyNodesTo`. Returns new paths and the summary rows of `node_create` (`full` adds flags). |
| `node_connect` | `items: [{from: path\|null, from_output = 0, to: path, to_input: int\|name\|"next"}]`, `partial = false` | `from: null` disconnects. `name` uses `setNamedInput`/`inputNames()`. `"next"` uses `setNextInput` (merge-style nodes). Out-of-range → `code: invalid_input` with `hint` listing `inputLabels()`. |
| `node_layout` | `parent`, `paths?` (subset), `mode: children\|good_position` | `layoutChildren()` or per-node `moveToGoodPosition()`. |
| `network_describe` | `root`, `depth = 1` (2 for `outline`), `include_defaults = false`, `include_positions = false`, `recurse_locked = false`, `format: data\|python\|outline`, `cursor` | `data`: `root.childrenAsData(inputs=True, flags=True, position=…, default_parmvalues=False)` trimmed and with locked-HDA children replaced by `{"type": ..., "hda_locked": true}`. `python`: `asCode(brief=True)` for a single node only. `outline` (1.1, review 11 B11): `nodes: [{path, name, type, children_count?, display?, errors, inputs?, flags?, hda_locked?, children?}]` to `depth`, where `display` is a network's display node and `errors` a count; `inputs` (1.2, review 12 papercut 4) is the source path per input slot (`null` for an empty slot before a wired one) and `flags` the flags that are on (`["display", "render"]`), each left out when empty; `children_count` is left out at 0, and `hda_locked` marks only locked assets whose library is not under `$HFS` (Houdini's own `attribwrangle`, `mountain` and so on are locked assets too, with contents once cooked, and flagged every wrangle in review 12; `node_info` still reports `hda_locked` for them); no parms, paged at the response budget like `data` (`truncated`, `next_cursor`). The bridge resource `houdini://outline` is `{root: "/", format: "outline"}`. This is how an agent reads a graph in one call. |
| `network_build` | `parent`, `data` (same shape `network_describe` returns, i.e. Houdini's own `hou.data` format), `on_name_collision: error\|rename\|replace = error`, `layout = true`, `dry_run = false`, `tag?` (stored as userData `hocuspocus:tag`), `press?: {node: [parm names]}` (1.4), `return: summary\|full = summary` | `parent.setChildrenFromData(...)` in one undo group after `dry_run`-style validation (type names exist, inputs resolvable). Returns created paths and per-node summary rows after cook (`full` adds flags). Input entries are `{from, from_index, to_index}`; a missing `to_index` is the entry's list position (§5.16). This replaces HocusScript and the network document. 1.4 (review 20 N2, as `node_create`): `setChildrenFromData` runs no parm callback scripts, so a menu or toggle with one that `data` sets adds a note to the result's `notes` naming `press`; `press` maps a node this call builds (a path relative to `parent` such as `geo1/src`, or absolute) to parm names whose callbacks (or buttons) run through `parm_set`'s press after the build is wired and before replaced nodes are deleted, in the same undo step, returning `pressed` (parm paths) and `side_effects: {node path: {parm: [old, new]}}`; a failed press rolls the whole build back, and `dry_run` validates the node names. `press` is an argument rather than a key in `data` so that `data` stays Houdini's own `hou.data` format. |

### 4.5 Parms

| Tool | Args | Behaviour |
|---|---|---|
| `parm_get` | `paths: [...]` (parm or tuple paths), `frame?`, `include: [keys, menu, template, ramp, multiparm]`, `full_strings = false` | Per parm/tuple: `path, name, tuple, component_names?, type, value` (evaluated at `frame` or current), `raw?` (`unexpandedString`/`rawValue`, left out when it equals `value`; 1.1, review 12), string `value`/`raw` over 200 characters as `{elided: <chars>, head: <first 80>}` unless `full_strings`, `expression?`, `language?`, `is_default`, `locked` (the parm lock), `hda_locked` (inside a locked asset), `keyframes?: {count, first, last}`, `menu?: {token, label, items: [...]}` (items capped at 50; a menu Houdini builds on the node, from a menu script or the input's groups and attributes, is evaluated on the parm and adds `dynamic: true`, with `items: []` and a `note` when it is empty even after a cook of the SOP; 1.3, review 14 papercut 10), `ramp?` (1.3: with `include: [ramp]` the ramp is said once, as `value`, and `ramp` is `{count}`), `multiparm?: {count, instances}`, `template?: {label, type, default, min, max, help}`. A tuple path returns components. A component path on a tuple returns that component. `code: parm_not_found` carries `candidates` (nearest names on the node, incl. tuple components). On a LOP a USD attribute name (`.../inputs:intensity`) resolves to the parm `hou.text.encodeParm` makes of it (`xn__inputsintensity_i0a`), for `parm_get`, `parm_set` and `node_create` `parms`; results carry the resolved path (1.2, review 13). 1.3 (review 18 papercuts 4, 9, 10): a string parm whose menu only the node builds (the Copernicus `signature`: no template items, no script) lists its `menu` and is validated like any menu; menu labels lose a leading `![icon]` reference; ramp keys and values are rounded to 6 significant digits, without `raw`. |
| `parm_set` | `items: [{path, value?, expression?, language: hscript\|python = hscript, keyframe?: {frame?, value}, keyframes?: [...], channel_ref?: "/path/to/parm", ramp?: {basis, keys, values}, multiparm_count?: int, revert_to_default?: bool, press?: bool, animation: replace\|key\|keep = replace}]`, `frame?`, `partial = false` | Exactly one of the value-ish fields per item. Tuple path + list value sets all components; component path sets one. `animation: replace` deletes keyframes/expression first then `set()` (so the value sticks), except that a single `keyframe` only adds or replaces its own key; `key` sets a keyframe at `frame`; `keep` is plain `set()` (Houdini's own behaviour, which may add a key — reported). Menu values accept token or label (label resolved with a hint), string menus only the node builds included (1.3). `press` (1.3, review 17 P0-2 and P1-4) clicks a button or runs the callback script of any parm that has one (menus and toggles too, through `hou.Parm.pressButton`); with `value` it sets the value first. A pressed item returns `pressed` and `side_effects: {parm: [old, new]}` (menus as tokens, multiparms as counts) instead of `value`/`raw`/`is_default`; on a writer's save button (File Cache Save to Disk, a ROP SOP's Render) the output files over its frame range are checked afterwards and the item adds `outputs_summary`, or the call fails with `cook_failed` and `detail.missing`. A plain set of a menu or toggle with a callback carries a note that the callback did not run. Strings accept `$HIP`-style raw text unexpanded. Returns per item: `path, value, raw?, expression?, wrote_keyframe: bool, is_default` (`raw` and long strings as in `parm_get`, which has the only `full_strings`) (a tuple adds per-component `expressions` and the `keyed` component names) and the owning node's `errors/warnings` after a cheap cook. Type mismatch → `code: invalid_value` with the template type and range. Locked HDA → `code: locked` with hint to `node_edit lock:false` or `hda` tool. A locked tuple component computed by an expression (`resolutiony` under `res_mode: autoheight`) that already holds the requested value is skipped; otherwise `locked` names the component, its expression and current value, and the hint names the components to set instead (1.2, review 13). |

### 4.6 Cook, problems, geometry

| Tool | Args | Behaviour |
|---|---|---|
| `cook` | `paths`, `force = false`, `frame?`, `timeout_s = 30`, `profile = false`, `frame_range?: [start, end, step = 1]`, `summary: none\|bbox = none`, `wait_s?` (1.3) | `node.cook(force)` on the main thread; catches `OperationFailed` and reports `errors/warnings/messages` per node, `cook_time_ms` (that node's own cook; inputs already cooked are not recooked, and a forced cook under 1 ms on a node with inputs carries a `hint` naming `profile`), `ok`. Errors left from before a fix, on the node or its inputs, are rechecked (§5.18) unless the last cook took over 2 s, and then `hint` names `force: true`. `profile` force-cooks `inputAncestors()` in dependency order and then the node, one main-thread step each, and returns `chain: [{path, type, cook_time_ms, error?}]` sorted by cost (top 10), `chain_total`, `total_ms` and `attribution`, and the named nodes' `results[].cook_time_ms` is their profiled cook, not the cached re-check (1.2). Inside a for-each loop (1.2, review 12 papercut 5) a node's own step cooks it once, outside the loop, so each `block_end` is force-cooked under `hou.perfMon` (cook stats only, unless another profile is already recording): the body rows (the `block_begin` and every input ancestor of the end downstream of it) get `in_loop`, `cooks`, `per_iteration_ms` and `cook_time_ms` over all iterations, from the monitor's per-node `Cook` (which includes an HDA's contents but not its inputs), and `loops: [{block_end, block_begin, iterations, total_ms, attribution}]` lists each loop (`iterations` is the `block_begin`'s `cookCount()` delta). `attribution` is `per_node` without loops, `perf_monitor` when every loop was measured, and `loop-level` when the monitor could not be used: body rows then keep their one standalone cook. `total_ms` counts each loop once, at its `block_end`. A stopped `hou.PerfMonProfile` cannot be deleted, so in the GUI the profile stays in the Performance Monitor's list. `frame_range` (not with `profile` or `frame`) cooks one frame per main-thread step, so a sim advances incrementally and the GUI stays responsive, with `progress` and `message: "36/96 frames done, cooking frame 37"` (1.3, review 20 N7: the count is `current`, the frames finished); it returns `frame_range`, `frames_cooked`, `total_ms`, and with `summary: bbox` `frames: [{frame, point_count, prim_count, bbox_min, bbox_max}]` from the node's geometry (an OBJ's display SOP; null for other contexts); the current frame is restored afterwards. Every mode runs as a job: the call waits `min(timeout_s, job_threshold_s)` (1.3: or `wait_s`, as on `render`; `0` returns the job at once) and returns the result, or `{job_id, state: "running"}` for `job`. 1.3 (review 17): cooking never writes files, so a cooked ROP or File Cache carries a note naming `render` and `parm_set press` on its execute button (P0-1, review 18 papercut 8); `summary: bbox` emits a row only when the counts, bbox or errors change, `through` naming the last frame the row stands for (P2-8); a cancelled cook's job result is the `cancelled` error with `detail: {last_status, partial: {frames_cooked, results, frames?}}` (P1-6); a profiled node that simulates (a DOP network, or a solver SOP with one inside) gets `simulation: {dopnet, resimulated, frame}` and a note that a force-cook reads frames already in the simulation cache (P2-10). 1.3 (review 20 N3): such a node is cooked under `hou.perfMon` with solve stats only, and `resimulated` is whether any DOP solve time was recorded; the simulation's time moves on a cache read too, so without the monitor `resimulated` is true only when the simulation's memory changed, false when neither its time nor its memory did, and otherwise `null` with a note. |
| `problems` | `root = "/"`, `include_warnings = true`, `cook_uncooked = false`, `recurse_locked = false`, `timeout_s = 30`, `limit`, `cursor` | Walks the subtree, reports nodes with errors/warnings, broken channel references, missing file parms (`file`-type templates whose expanded path does not exist), unconnected required inputs. Errored nodes changed since their last cook are recooked first, so a fixed node is never listed. `cook_uncooked` cooks never-cooked nodes too. The scan stops after a budget (10 s, or half of `timeout_s`) with `incomplete: true` and a `next_cursor` that continues the walk without losing rows. A TOP node with failed work items is a `failed_work_items` row with `count`, the first item and its error (1.2). The "why is my node red" tool. |
| `geo_info` | `path` (SOP, or OBJ → its display SOP), `frame?` | ~1 KB: `point_count, prim_count, vertex_count, bbox: {min, max, size, center}, prim_types: {polygon: n, packed: n, volume: n, …}, attributes: {point: [{name, type, size, type_info}], vertex, prim, detail: [{name, type, value}]}, groups: {point: [{name, count}], prim, edge, vertex}, intrinsics?`. Uses intrinsics and bulk accessors, never Python loops over points. 1.3 (review 17 P1-7): `intrinsics` lists every volume under `volume_columns: [name, prim, resolution, voxel_size, min, max]` and every VDB under `vdb_columns: [name, prim, class, value_type, active_voxels, voxel_size]` (100 each, then `volume_total`/`vdb_total`); detail values that are `hou` vectors and matrices are lists, and a dict over 200 characters is `{elided, keys}`. 1.3 (review 18 papercut 3): on a Cop node (or a COP network's display node) it returns the image instead, from `CopNode.layer()`: `kind: image, output, layer_type, resolution, data_window, pixel_scale, storage, border, constant?, channels: {r: {min, max, mean}, …}, other_outputs: [{name, layer_type}]`; the output schema no longer requires the point counts. |
| `geo_read` | `path`, `class: point\|prim\|vertex\|detail`, `attribs?: [..]` (default all), `start = 0`, `cursor?`, `count = 50`, `group?`, `stats = false`, `frame?` (1.3) | Spreadsheet rows as arrays with a `columns` header. `stats` adds `min/max/mean` per numeric attribute and `unique` (≤ 20) per string attribute over the **whole** class, computed with numpy bulk accessors. `next_cursor` is the next row offset as a string (pass it as `cursor`). `frame` reads `geometryAtFrame` without moving the playbar (1.3, review 17 P1-5). |

### 4.7 Visual feedback, code, types, state, contexts

| Tool | Args | Behaviour |
|---|---|---|
| `viewport_capture` | `camera?` (OBJ camera, LOP camera node, or camera prim path), `lop_path?`, `cop_path?` (1.3), `frame?`, `resolution = [1024, 768]`, `fit?: all\|selected\|none` (1.3: no schema default), `source: auto\|viewer\|flipbook_rop\|opengl_rop = auto` (1.4: `opengl_rop` is the 1.3 name of `flipbook_rop`), `path?` | Returns MCP **image content** (PNG, downscaled so the longest side ≤ 1024) plus `{path, width, height, camera_used, scene: obj\|stage, lop_path?}`. `viewer` uses the GUI SceneViewer flipbook of one frame (captures what the user sees, as it is, `fit_used: "none"`, unless `fit` is passed explicitly: then it frames all or selected for the grab; with `camera` it looks through it; either way the view, and the camera the viewport looked through, is saved and put back afterwards (1.2, review 15). `context` is the viewer's network and `notes` say when it is not the captured scene's, since other objects then draw ghosted). `flipbook_rop` (1.4) renders through a Flipbook ROP, falling back to the OpenGL ROP and then a temporary Karma ROP (§8; `source_used` names the one that ran and `notes` why), and, when `camera` is absent, through a camera framed on the bbox (`camera_used: "temporary"`; `fit: none` reuses the last framing); works headless. A LOP camera node, a camera prim (on `lop_path`'s stage, or the /stage display LOP's) or `lop_path` captures the stage through the ROP's LOP source (a framed stage gets a temporary camera LOP after the LOP; the network's display LOP is used for a LOP camera when its stage has the camera); without `camera` or `lop_path`, the /stage display LOP is captured when /obj displays nothing, and otherwise a note names it (1.2, review 13). Lights are refused as cameras; camera errors list the scene's cameras as `candidates`. A look is read-only: headless, camera and ROP exist only in the child hython (§8); in the GUI they are created outside undo and deleted after the render, and `notes` says so if Houdini still marked the hip modified. `auto` prefers `viewer` in GUI unless a `camera` or a stage is captured. The capture file and the copy at `path` are written opaque, composited onto the inline image's grey (1.2, review 12): the OpenGL ROP has no background-colour parm (checked on 22.0.466; nor has the Flipbook ROP, which only takes a background image) and leaves the background transparent, which most viewers show as white. 1.3 (review 19 papercut 7): `fit` has no default in the schema, which had said `all` although the viewer never applied it; without `fit` the viewer captures the view as it is and the ROP source frames all. 1.3 (review 18 papercut 1): `cop_path` (a Cop node, or a COP network's display node) renders it through a temporary `rop_image` in its network (about 0.2 s, outside undo and `events`, deleted afterwards) and returns the PNG at the COP's own resolution (`resolution` is ignored) with `scene: cop` and `layer: {layer_type, resolution, data_window}`; it cannot be combined with `camera`, `lop_path` or `source: viewer`. A Cop node passed as `camera` or `lop_path` is refused with a hint naming `cop_path`, and a capture without `camera`, `lop_path` or `cop_path` names the COP networks under `/img` in a note. |
| `render` | `rop_path` (a ROP, or 1.3 a writer SOP), `frames?: [start, end, inc]` (1.4: default the ROP's own frame range, else the current frame), `output?`, `wait_s?` (default `job_threshold_s`), `thumbnail = true` | Always starts a job that calls `rop.render(...)` (frame by frame in-process, or in a child hython for a headless Flipbook or OpenGL ROP, §8). An explicit `wait_s` is the caller's own threshold; without it the call waits `job_threshold_s` (§7). If it finishes in time returns `{state: "done", job_id, outputs: [paths], thumbnail: image, notes?}`; above 5 outputs `outputs_summary: {count, first, last, pattern, missing_count}` and `outputs_sample` (the first 2 and last 2 paths) replace `outputs`, in the direct result and in `job result` alike (1.3, review 20 N5: a 48-frame `job result` was 8 KB of paths), and `missing` lists at most 20 paths. `notes` warns when the scene has no light objects or LOP lights (image outputs) and when the thumbnail's mean luminance is under 8/255, measured on the flattened thumbnail the agent receives; a thumbnail whose every pixel is transparent gets an "empty" note instead (1.3, review 20 N1). Otherwise `{job_id, state: "running"}` to poll with `job`. Every expected output file, the ROP's own parm included, is checked against `approved_roots`. Karma/Mantra/Flipbook/OpenGL/any ROP. On USD render ROPs (`Lop/usdrender_rop`, `Driver/usdrender`) the outputs are `outputimage`, else the `productName` of each RenderProduct of the render settings prim the ROP uses (its `rendersettings`, the stage's, or the first under `/Render`), per frame; never `lopoutput` (husk's intermediate file). `output` overrides `outputimage`; a `note` says when nothing resolves; a husk failure carries the last 20 lines of its log in `detail.log_tail` (1.2, review 13). The thumbnail is inline only (flattened onto grey); the ROP's output files are never rewritten, so their alpha stays. 1.3 (review 17 P1-3, P1-6): a writer SOP (File Cache, `rop_geometry` or `rop_alembic` SOP) renders its own frame range unless `frames` is given, as a job with per-frame progress and cancel; a File Cache renders through the ROP inside it (no `output` override) and then turns on Load from Disk as its Save to Disk button does, reported as `side_effects: {parm: [old, new]}`. Writing a cache is `render`'s job, never `cook`'s (D27). A cancelled render's job result is the `cancelled` error with `detail: {last_status, partial: {outputs_summary}}`, the files written before the cancel. 1.3 (review 18 papercuts 2, 7): a Cop node that is not a ROP is refused with the `rop_image` nodes of its network as `candidates`; a COP image ROP gets no lights note; a thumbnail PIL cannot read (a float TIFF) goes through `iconvert`, and if that fails a note says why (the `thumbnail_error` field is gone). 1.4 (review 23 P0-1): a ROP whose output is one file for the whole range (a USD layer from `usd_rop`, `Driver/usd` or a `usdexport` SOP, an Alembic archive, any output path without `$F`) renders the range in one `rop.render(frame_range=(start, end, inc))` call, since frame by frame each call overwrote the file and only the last frame survived; progress comes from its per-frame render events, and a cancel sent during the call takes effect after it. The file is then read back: for USD the root layer and every layer it composes (sublayers, references, payloads, such as a `sopimport` save path), and the render fails with `cook_failed` when the layer with the most time samples has fewer than the frames asked (no samples at all is a static stage: a note); an Alembic archive's time range must cover the frames. 1.4 (review 23 P1-2): without `frames` every ROP renders its own Valid Frame Range (`trange` not off: `f1`-`f3`), as writer SOPs did since 1.3, with the note `Rendered <rop>'s own frame range 1-48; pass frames to render others.`; a ROP set to Render Current Frame renders the current frame with a note saying so and that `frames` renders a range. 1.4 (review 23 P1-3): `outputs` lists each file once (a 48-frame USD export is one output, not 48), and a USD export adds `layers: [{path, bytes, time_samples, time_codes?}]`: the root layer, every layer file it composes (sublayers, references, payloads, followed through each layer: a `sopimport` save path holds the data under a stub root layer) and USD files in the root layer's directory that the render wrote, at most 20, each opened as an anonymous copy so no cached layer is reloaded. |
| `houdini_python` | `code`, `timeout_s = 30`, `language: python\|hscript = python`, `undo_label?` | `exec` in a fresh namespace with `hou` bound, stdout/stderr captured, the value of a trailing expression or a `result` variable JSON-serialised (`repr` fallback). Runs on the main thread inside one undo group. Returns `{stdout, stderr, result}`. An uncaught exception (`sys.exit()` included) fails with `code: python_exception` (stdout, stderr, traceback in `detail`) and rolls the call back. A `sys.settrace` deadline stops Python code shortly before `timeout_s` (`houdini_busy`, `detail.started` and `stopped` true, rolled back), so a runaway loop cannot wedge Houdini. Output capped at the response budget with `truncated`. Disabled → `code: python_disabled`. Destructive. |
| `node_type_search` | `query`, `category?`, `limit = 20`, `include_hidden = false`, `current_only = true` | Ranks exact name = 100, exact label = 95, name prefix, label prefix, all words in the label; a plain-language query is then scored word by word without stop words, a word naming the type (4) or a whole label word (3) outranking a keyword (1.5) or a description word (1), with a short Houdini synonym table at half weight. Marks `is_current_version`. Row: `name, label, category, version, description` (clipped to 120 chars), `inputs: {min, max}, deprecated`. `total` is the real number of matching types, never a cap: word-by-word scoring lets a broad query match hundreds (1.2, review 12). With `current_only` (1.1 default) every version of a type folds into its current version's row, ranked by its best-scoring version, and that row carries `other_versions: [...]`; `false` lists each version as its own row (`current` names the head). All 18 categories supported. `node_type_not_found` candidates come from the same ranking, led by known other names (`distantlight` is `hlight` and `camera` is `cam` in /obj). 1.3 (review 18 papercuts 5, 6): Cop types also match the labels of their top-level menus (`remap`'s Threshold, `blend`'s Over); a Cop synonym table maps compositing words to types (threshold: `remap`, gradient: `ramp`, composite or over: `blend`, text: `font`, write: `rop_image`); a network type's row adds `child_category` and `typical_parents` (`copnet`: `/img`); results with legacy `Cop2` types carry a note that Copernicus is `Cop`. |
| `node_type_info` | `type` (`category/name` or bare name with `category`), `include_parms = true`, `include_help = false`, `folder?` (a label, an `A / B` path, or `""` / `(no folder)` for the top-level parms), `parms?` (glob on name or label; `a\|b` matches either), `detail: compact\|full\|folders = compact` | `folders`: `[{folder, parms}]` (visible parm count per folder), no parm rows; every name it lists is accepted by `folder`. `compact`: `parms: {folder: [[name, label, type, default, components?]]}` under `parm_columns`, no menus, ranges, hidden parms, per-parm help, `help_url` or `tags` (Sop/scatter: 3.0 KB against 5.7 KB). `full`: `name, label, category, version, description, help_url, inputs: [{index, name, label}], outputs, parms: [{name, label, type, size, default, min, max, menu?, folder, help?, is_hidden}]` grouped by folder (1.3: a script menu such as `pdg_cachemode`, or a menu built from input geometry such as a SOP `group`, is evaluated on a temporary instance as `menu: {items, dynamic: true}`, or `items: []` with a `note` when it evaluates empty there, never a bare `default`), plus `help_text` (first ~2 KB of the node help from `$HFS/houdini/help/nodes.zip`, best effort) when asked. With `folder` or `parms` (a parm lookup) `inputs` becomes `inputs_count` and `full` leaves out `folders` (1.2, review 13: 2.2 KB of 3.3 KB on `mtlxstandard_surface` was its 42 inputs). 1.3 (review 18 papercuts 4, 9): `full` also evaluates a string menu only the node builds (a Copernicus `signature`); menu labels lose a leading `![icon]` reference; a `compact` listing over 8 KB leaves out the parms a menu hides at its default (the per-pattern parms of the other `tilepattern` patterns) and lists them as `variants: {menu parm: parms left out}` with a note (`parms` or `detail: full` list them). |
| `undo` | `action: undo\|redo\|history`, `steps = 1`, `include_user_steps = false` | `history` lists the last 20 undo labels (and `redo` labels); `undo`/`redo` returns the labels `performed` plus `next_undo`, `next_redo`, `undo_count`, `redo_count`, `dirty`, `scene_generation`. They stop at the first step not labelled `HocusPocus:` (the user's or Houdini's) and name it in `blocked_by`; `include_user_steps` crosses such steps and lists them in `user_steps` (1.2). 1.4 (review 21 papercut 2): a call that failed and was rolled back stays on Houdini's redo stack, which cannot drop one entry; the host remembers the redo stack right after each rollback, `redo` stops before such an entry and names it in `skipped` with a note, and `history` leaves it out of `redo` and lists it under `rolled_back` (`next_redo` and `redo_count` skip it too). |
| `time` | `frame?`, `range?: [start, end]`, `fps?` | Omitting all fields reads. Sets with `hou.setFrame`, `hou.playbar.setFrameRange` (works headless), `hou.setFps`. |
| `selection` | `paths?` | Omit to read `hou.selectedNodes()`; provide to `setSelected` exactly. |
| `job` | `action: status\|result\|cancel\|list`, `job_id?`, `all = false` (1.3) | Jobs are host-side threads for render/pdg/long cook. `status: {state: running\|done\|failed\|cancelled, progress?, current?, total?, message?, started, elapsed_s}` (`progress` is 0..1, `current` of `total` steps; 1.0 once done). `result` returns the tool's normal result once done. A `pdg` cook job counts the work items of the whole graph and adds `nodes: {name: "finished/total"}` (1.2). 1.3: job ids are `<pid>-<id>` and the bridge routes `job` to that pid; `{action: list, all: true}` lists every live instance's jobs (§7). A cancelled `cook` or `render` job keeps its partial work in `detail.partial` (§4.6, `render`), next to `detail.last_status` with `state: cancelled`. 1.3 (review 20): a frame-by-frame job's `message` counts the frames done, as `current` does, and prints whole frames as integers (`frame 90`, not `90.0`); `cancel` adds `cancelled: true`, or `cancelled: false` and a note when the job had already finished (its `state` stays `done`, `failed` or `cancelled`). |
| `hda` *(full profile)* | `action: create\|save\|unlock\|match\|install\|reload\|list`, plus action-specific fields (`path`, `library_path`, `name`, `label` or `description`, `version`, `min_inputs`, `max_inputs`; `promote_spare_parms = true` for `save`; `limit`/`cursor` for `list`) | Thin wrappers over `createDigitalAsset`, `definition().updateFromNode`, `allowEditingOfContents`, `matchCurrentDefinition`, `hou.hda.installFile/reloadFile/loadedFiles`. `save` also copies the instance's spare parms into the definition's parm template group (`promote_spare_parms = true`, 1.2). `list` shows long paths, not 8.3 short names; `node_type_info`/`node_type_search` report the definition's version, its label as `description` when there is no help, and types as `Sop/ns::name` (1.2). |
| `usd_stage` *(full)* | `lop_path`, `prim = "/"` (a path or a glob: `*` within a segment, `**` across), `depth = 1`, `include: [attributes, xform, bindings, layers]`, `attribs?` (name glob, `a\|b`; implies attributes), `summary = false`, `time?`, `limit`, `cursor` | Traverses `lop.stage()` read-only, paged by `limit` and `cursor`; `total` is on every page (a counting walk that builds no rows, capped at 100,000 with `total_capped`). Attribute values at `time` for primitive types; arrays of up to 4 elements (8 for strings and tokens) in full, longer ones as `{len, first}`. `xform` gives `local`, and `world` only when it differs. `summary` returns `{total_prims, counts_by_type, bbox_world: {min, max, size}}` for the whole subtree (UsdGeom.BBoxCache, default and render purposes) instead of rows. A render ROP inside a LOP network (`usdrender_rop`) has no stage: `invalid_argument` names its input as the candidate (1.2, review 13). |
| `pdg` *(full)* | `action: cook\|status\|workitems\|cancel\|dirty`, `top_path`, `block = false`, `save = false`, `timeout_s = 30`, `attribs?`, `state?`, `limit`, `cursor` | `cookWorkItems(block=False)` as a job polled in short main-thread steps, with `progress`/`current`/`total` counting finished work items; `block` waits `min(timeout_s, job_threshold_s)` for the result, then returns `{job_id, state: "running"}` (§7); `status` from `getPDGNode()`; `workitems` paged with state and output files. A failed item carries `error` (its log's last error lines), `log_path` and `exit_code`; a cook result lists the first 5 `failures` of the graph (1.2). Out-of-process ROP TOPs load the saved hip, so `cook` refuses an untitled or dirty scene with `unsaved_changes`; `save: true` saves first (1.2). A cook whose items were cancelled ends `cancelled`, never `done`; `cancel` also cancels the job cooking the graph and returns the status after the cook stopped (1.2). `node_info` on a TOP node adds `pdg_state: {cooked, failed, total}` (1.2). `workitems` takes `attribs: [names]` (per-item values) and a `state` filter, reports `cook_time_s`, and gives output files relative to one `output_root` (1.2). |
| `events` *(full)* | `since = 0`, `limit` | Host-side ring buffer of hip events and node events (`ChildCreated`, `NameChanged`, `ParmTupleChanged` on nodes the agent touched, `BeingDeleted`) with a monotonic sequence. For "what did the user change since my last call". 1.2: every event has `origin: agent\|other` (agent = inside a HocusPocus call: the host holds a call's events and publishes them when its main-thread work ends, none if it was rolled back, without nodes created and deleted within it, and without changes made while undo is disabled, such as `render`'s output-parm set and restore); nodes read with `node_info` or listed by `network_describe` are watched too; nested nodes created in one batch get their `ChildCreated`; `FlagChanged` names the flags; 1.3 (review 16 papercut 9): `ParmTupleChanged` on a multi-component tuple names the `components` whose value or keys changed instead of a `count` (a burst within 0.1 s is one event with their union) and lists in `keyed` those of them with keyframes now, from a per-tuple snapshot taken when the node is watched; spare parm edits are one `SpareParmsChanged`; `hda create/match/unlock` are one `hda_contents_rebuilt`; the `pdg` tool records `kind: "pdg"` events (`cook_start`, `work_item_failed`, `cook_done`); Houdini's save-time writes on TOP networks (1.3: and on `/stage`) are dropped; 1.3 (review 18 papercut 10): one ramp edit is one `ParmTupleChanged` on the ramp parm, not one per key parm. 1.3 (review 19 papercut 8): seq restarts in every Houdini, so the bridge returns `next_since` as `<pid>:<seq>` and takes it back as `since` (a bare seq still works); a cursor from another Houdini is read from the start with `reset: true` and a `note`. The host keeps plain integers. |

Count: 2 session + 4 hip + 10 node/network + 2 parm + 4 cook/geo + 2 visual + 1 code +
2 types + 4 state/job = **31 in `core`**, plus 4 in `full` = 35. `minimal` is 14 of the
core tools (§4.1).

### 4.8 Resources, prompts, instructions

**Resources** (user-attachable context; every critical read is also a tool):

- `houdini://status` (same as `houdini_status`)
- `houdini://outline` (`network_describe {root: "/", format: "outline", depth: 2}`; 1.1)
- `houdini://node/{path}` (`node_info` default includes)
- `houdini://node/{path}/parms`
- `houdini://node/{path}/geo`
- `houdini://nodetype/{category}/{name}`
- `houdini://job/{id}` (routed to the Houdini in the job id, §7)
- `hocuspocus://guide` — the operating manual: the instructions below, the resources and
  recipes (two Houdinis, Copernicus, Flipbook frames (1.4), spare parms); at most 8 KB, a unit test enforces it
  (1.3, review 19 papercut 10: with the tool reference appended it was 52 KB)
- `hocuspocus://tools` — the tool reference rendered from the catalogue for the bridge's
  profile (the text of `docs/tools.md`, every tool's `notes` and examples; 1.3)

**Prompts** (slash commands in Claude Code): `inspect_scene`, `build_sop_chain`,
`debug_red_node`, `turntable_preview`. 1.3 (review 19 §5): `inspect_scene` reads
`houdini://outline` (or `network_describe format: outline`), then `problems`, and asks
which Houdini to inspect (or pins the GUI) when status warns of several; `build_sop_chain`
reads the errors `node_create` returns instead of a separate cook and ends with
`viewport_capture {"fit": "all"}`; `debug_red_node` drops the mandatory `problems`/`cook`
and names wrangle spare parms; `turntable_preview` turns the target's display flag on,
hides other displayed objects for the captures (or says what blocks the view), captures at
the camera's resolution and never changes the playbar range in a GUI session (each
capture takes `frame`).

**Server `instructions`** (≤ 400 words, shipped in `initialize`; the text lives in
`bridge/instructions.py` and a unit test enforces the cap):

> HocusPocus drives a live Houdini. Identity is Houdini paths. Start with
> `houdini_status`; if nothing is connected, `houdini_connect` can launch Houdini (GUI
> or headless hython) or attach to a running one by pid. With several Houdinis running,
> pin one with `houdini_connect {pid}`: until then calls that change a scene refuse with
> `ambiguous_instance`, and if the pinned one exits calls return `instance_lost` instead
> of switching. `_meta.instance` names the Houdini that answered; job ids and `events`
> cursors carry their pid. Build with `node_create`
> (batch, with parms and inputs) or `network_build` (whole graph from the
> `network_describe` format). Read with `node_info` and `network_describe`. Change
> values with `parm_set {items: [{path, value}]}`; tuple paths like `.../t` take lists, component paths like
> `.../tx` take scalars; expressions go in `expression`. After building, call `cook` or
> read `errors` in results, then `geo_info` to check counts and bounds, and
> `viewport_capture` to look at it. Every mutating call is one undo step. Hip tools
> refuse to discard unsaved work unless told to. Long cooks and renders return a
> `job_id`; poll it with `job`. When no tool fits, `houdini_python` runs `hou` code.
> Results are compact: non-default parms only, lists paged with `cursor`; `truncated:
> true` means the response budget cut a list, so page or narrow the query. Errors carry
> `code`, `hint` and `candidates`; read them and adjust. `delivery_unknown` means the
> call may or may not have run: inspect state before repeating it.
> `_meta.scene_generation` changes when the scene is cleared or loaded, so cached paths
> may be stale. A Houdini started with `houdini_connect {launch}` usually closes when
> this server exits (`launched.outlives_server` says): `hip_save` before the session
> ends, keep one session open for long jobs, or attach by pid to one started with
> `hocuspocus launch`. `viewport_capture` frames per `fit` on both paths and restores the
> user's view afterwards; without `fit` or `camera` the GUI viewer is captured as it is.
> `lop_path` captures a stage. For a flipbook of many frames, `render` a Flipbook ROP
> (`Driver/flipbook`, recipe in the guide); Houdini 22 deprecates the OpenGL ROP.
> `node_type_info` is large for FX types: pass `parms` globs, or `detail:
> "folders"` first. Add spare parms with `node_edit` `spare_parms` (recipe in
> `hocuspocus://guide`). The resource `houdini://outline` is the whole scene as a
> compact tree; `hocuspocus://tools` is the full tool reference.

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
    frame range works, the Flipbook and OpenGL ROPs work (first render ~2 s; a later
    render can crash, §8), `hou.undos` works.
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
sequence of short main-thread steps (e.g. per-frame render) with progress between them
(1.4: a single-file ROP renders its range in one main-thread call, §4.7 `render`).
Progress notifications are emitted by the bridge when the client supplied a
`progressToken`: the host files every job under the `request_id` of the `/hp/v1/call`
that started it, and while that call is in flight the bridge polls
`/hp/v1/calls/{request_id}/jobs` (for `job` with a `job_id`, `/hp/v1/jobs/{id}`) every
0.5 s and sends `notifications/progress` from the newest snapshot: `progress`/`total`
from the job's `current`/`total` steps (else its 0..1 `progress` over `total: 1`) and its
`message`, only when `progress` increases. Polling is best effort and never fails the
call. Jobs are not durable across a Houdini restart; `job status` after a
restart returns `job_not_found` with that explanation.

**Jobs and several instances** (1.3, review 19 papercut 3). A job id is `<pid>-<id>`,
the pid of the Houdini that runs it (a bare `<id>` still finds a job of that process).
The bridge sends `job` (and `houdini://job/{id}`) to the instance the pid names, whatever
is selected or pinned; when that Houdini has exited the answer is `instance_lost` with the
last status the bridge saw for the job in `detail.last_status`. `job {action: list}` lists
the selected Houdini's jobs; `{action: list, all: true}` asks every live instance and adds
`pid` to each row and `instances: [{pid, label, jobs, running}]`. A host asked for another
pid's job answers `job_not_found` naming both pids.

---

## 8. Visual feedback

The agent must be able to **see**. `viewport_capture` returns an image in the MCP
result, never only a path. Two sources: the GUI SceneViewer flipbook (what the user
sees, including guides) and a viewport ROP (deterministic, headless-capable, explicit
camera). `render` covers Karma and other ROPs as jobs with a thumbnail. Images are
PNG, downscaled to ≤ 1024 px on the long side, and also written to
`<state_dir>/captures/` with the path returned. Image bytes count toward the client's
output limit, so one image per call.

**Captures go through the Flipbook ROP** (1.4). Houdini 22 deprecates the OpenGL ROP
(`Driver/opengl`, `deprecationInfo()`: "Replaced by the Flipbook ROP.", 22.0) for the
Flipbook ROP (`Driver/flipbook`), which has the same `picture`, `trange`, `tres`/`res1`/
`res2`, `camera` and LOP-source parms (`opsource`, `loppath`, `cameraprim`) plus its own
lighting and quality parms. The ROP source (`flipbook_rop`, or its 1.3 name
`opengl_rop`) tries, in order, the Flipbook ROP, the OpenGL ROP (each only where this
Houdini has the type) and a temporary Karma CPU ROP in the host. Headless, a ROP whose
render process crashes hands the frame to the next; in the GUI a ROP that writes no
image does (a crash there would take Houdini down, so the GUI has no Karma step).
`notes` say which ROP did not render and why, `source_used` names the one that ran
(`flipbook_rop`, `opengl_rop` or `karma`), and after a stage capture's child crashed, later
stage captures with `source: auto` skip that ROP in this process. The temporary ROPs are
HocusPocus's own: no deprecation note is added for a temporary OpenGL ROP (`node_create`
of `Driver/opengl` keeps its note).

**Headless viewport renders run in a child hython.** Verified on 22.0.466: in hython the
second `RopNode.render()` of any OpenGL ROP in one process segfaults in the Vulkan
viewport renderer, whatever the node, frame or output; one multi-frame `render()` is
fine. The Flipbook ROP renders the same ROP again in-process (other frames, cameras,
resolutions and geometry; review 16's city stage three times), but once a Flipbook ROP that
has rendered is deleted (`destroy()`, or `hipFile.clear()`), the next Flipbook render in that
hython segfaults at the same place (`RV_ShaderVariableSet::create`). A capture's temporary
ROP is always deleted, and users delete theirs, so headless, `viewport_capture` and
`render` of Flipbook and OpenGL ROPs snapshot the scene (`saveChildrenToFile` per manager:
no hip save, no event side effects) and render it in a short-lived child `hython` (about
3 s per call). In the GUI both render in-process (a temporary Flipbook ROP created,
rendered and deleted four times, OBJ and stage, then again after `hipFile.clear()`, ran
in houdinifx 22.0.466; a GUI capture takes about 0.3 s); every other ROP type renders
in-process frame by frame through the executor.

**An OpenGL ROP child that renders a stage runs single-threaded** (`HOUDINI_MAXTHREADS=1`,
review 16 N1): its LOP source creates the Vulkan device on a TBB worker and crashes for a
stage of more than a few thousand polygons. The Flipbook ROP does not (review 16's city
stage rendered multi-threaded in 5 of 5 fresh hythons), so its children keep every thread.

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
| `ambiguous_instance` | several live instances, none pinned, and the call changes a scene (1.3, §3.3 rule 3); `candidates` as for `instance_lost`, `hint` names the `houdini_connect {"pid": …}` call for each | no; after `houdini_connect {pid}` |
| `instance_lost` | the pinned Houdini exited (1.3); names its pid and label, `candidates` are the live instances as `{pid, label, ui, hip}`; the bridge does not switch on its own (§3.6) | no; after an explicit `houdini_connect` |
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
| `job_not_found` | job id; 1.4 (review 21 papercut 3): also a `<pid>-<id>` whose pid this bridge never knew (never live in the registry, no job of it seen, no launch record), which 1.3 reported as `instance_lost` for a Houdini that had never run | no |
| `cancelled` | job cancelled | — |
| `python_exception` | `houdini_python` code raised (`SyntaxError` and `SystemExit` included): `message` is `<type>: <text>`, `detail` carries `stdout`, `stderr`, `traceback` and `rolled_back`, and the code's scene changes are undone (1.1; in 1.0 a successful result with `ok: false`) | after fixing the code |
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
  cli.py                       # install-houdini, uninstall-houdini, launch, doctor, client-config, docs, version
  tools/                       # shared by host and bridge; stdlib only
    catalog.py                 # the single source of truth for the tool surface
    errors.py                  # error codes + ToolError
    docs.py                    # renders docs/tools.md; tools/list size; example validator
    paths.py                   # state dir (instances/, logs/, captures/)
    budget.py                  # the response truncator (host and bridge)
  host/                        # INSIDE Houdini. stdlib only. `import hou` lazily.
    __init__.py                # start(), stop(), status(), autostart()
    __main__.py                # hython -m hocuspocus.host
    config.py executor.py server.py dispatch.py runtime.py registry.py jobs.py undo.py
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

1. Resolves every candidate pref dir, deduplicated by real path (1.2.1): `--prefs`,
   `HOUDINI_USER_PREF_DIR`, what hython (`hou.homeHoudiniDirectory()`) from the detected
   HFS reports, what it reports with `HOME` removed (Windows; a Houdini started from the
   Start menu has no `HOME`), and the existing `<home>/houdiniX.Y` and
   `<home>/Documents/houdiniX.Y`. It installs into `--prefs` (created if missing) and
   every candidate that exists; if none exists, it creates the first.
2. Copies `src/hocuspocus` (all of it; Houdini only imports `host` and `tools`) to
   `<prefs>/hocuspocus/<version>/python/` and the `houdini/` payload to
   `<prefs>/hocuspocus/<version>/houdini/`, and writes `<prefs>/packages/hocuspocus.json`
   pointing at both. `--dev` points at the checkout's `src/` and `houdini/` instead of
   copying.
3. Records the pref dirs in `<state_dir>/install.json` (`pref_dirs`, and `prefs` = the
   first, for older readers) so the bridge can find
   `hocuspocus.toml` without asking hython (§3.7).
4. Prints what it did and the restart note. Idempotent; replaces older versions.

`hocuspocus doctor` checks: HFS found, Houdini version, every candidate pref dir with
whether its package JSON is present and current (warning, with the command to run, when
one has it and another does not), which
`hocuspocus.toml` the bridge reads, package JSON present and pointing at an existing
dir, host/bridge version match, live instances with a `/health` round trip, and prints
the `claude mcp add` / Codex config lines. `hocuspocus version` prints the bridge, RPC,
`mcp` and Python versions. `uninstall-houdini` removes the package JSON and the copied
versions from every candidate and recorded pref dir, then the `install.json` record.
`hocuspocus client-config codex|claude` prints the snippets. `hocuspocus docs tools`
regenerates `docs/tools.md`. `hocuspocus launch [--headless] [--hip FILE] [--wait N]
[--work-dir DIR]` starts GUI Houdini (or `hython -m hocuspocus.host`) with the same
detection and package path rules as `houdini_connect {launch}`, waits for its registry
entry, prints it as JSON (no token) and exits: that Houdini belongs to no MCP server (no
`launched_by`, no launch record), so it outlives every client (1.1, review 11 B1). It
starts in the directory the command runs in, or `--work-dir` (1.2, review 12): the
untitled scene's `$HIP` and `$JOB` are where the user ran it, as when running `houdini`
there; a headless host gets `--work-dir` too, because the host otherwise moves to
`HOCUSPOCUS_WORK_DIR`/home at start. `houdini_connect {launch}` keeps that
`HOCUSPOCUS_WORK_DIR`/home rule (§4.2): an MCP server's cwd is wherever the client
started it.

Houdini version policy: `>= 22.0` supported; builds other than the tested list print a
warning in `doctor` and the host log, never a refusal.

---

## 11. Testing

pytest everywhere. Markers `unit`, `houdini`, `e2e`, and (1.3) `slow` for integration tests
over about 1.5 s (visual child renders, stage captures, Karma, PDG cooks, 1M-point geometry,
deliberate timeouts). A default run deselects `slow`; `--runslow` adds it and `-m slow` runs
only it. `conftest.py` finds hython via
`HOUDINI_HYTHON`, `HFS`, or the newest `Side Effects Software/Houdini 22.*`, and skips
`houdini`/`e2e` when absent so contributors without a licence get green.

| Tier | Runner | Scope | Budget |
|---|---|---|---|
| `tests/unit` | system Python | catalogue integrity (every tool has impl, schema, annotations, ≤ 60-word description, serialised full-profile `tools/list` ≤ 32,000 B in the default `text` mode and ≤ 44,000 B in `both`), bridge instance selection and offline behaviour with a fake host, error mapping, budget truncation, config parsing, `cli` path resolution | < 10 s |
| `tests/integration` | `hython -m pytest` | in-process host: one `hou` session per run, `hipFile.clear()` per test, every tool exercised against real nodes; the idioms in §5 each have a test | fast (default) < 90 s; `slow` about 3 min |
| `tests/e2e` | system Python spawning hython | official `mcp` client → `hocuspocus-mcp` stdio → `hython -m hocuspocus.host` on an ephemeral port with an isolated `HOUDINI_USER_PREF_DIR` and a neutral cwd: a stdio round trip, review 06 tasks 2, 3, 4, 6 and 9 as one scripted scenario, and a bridge launch that checks the work dir | < 60 s |
| GUI (manual; no `tests/gui` directory) | checklist | package loads in `houdinifx`, autostart, viewer capture; run before a release and logged in `docs/redesign/progress.md` | — |

Hygiene rules: never write into the repo at test time; never use port 37219; isolated
pref dir per run; clean interpreter exit. CI: GitHub Actions `windows-latest` and
`ubuntu-latest` run `ruff check`, `ruff format --check`, the unit tier and a
`docs/tools.md` freshness check (`ci.yml`); a self-hosted Windows runner labelled
`houdini` runs integration (the fast set, then `-m slow`) + e2e nightly, on manual dispatch and on PRs labelled
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
- **D16** (1.1) Results go to the model once, as text; `result_content` (`text` | `both` | `structured`) keeps the other shapes available. *Measured: Claude Code shows the model only the text block, so `structuredContent` doubled every result for nothing.*
- **D17** (1.1) `node_create`, `node_copy` and `network_build` return summary rows by default; `return: full` echoes. *In review 08 the full echoes averaged 8.1 KB per build call against about 0.9 KB as summaries, and the agent used only paths and errors (review 11 B5).*
- **D18** (1.1) An uncaught `houdini_python` exception is an `isError` result with `code: python_exception`, rolled back. *A failure returned as a success was easy to miss (review 07), and its half-applied scene changes stayed behind.*
- **D19** (1.1) `node_type_search` defaults to `current_only`, with `other_versions` on the row. *Older versions about doubled search results (review 09) without helping the agent choose a type.*
- **D20** (1.1) A Houdini that outlives its clients comes from the `hocuspocus launch` CLI, not from new process-ownership tricks in the bridge. *Detaching from a client's process tree is not reliable on Windows (review 08); a Houdini the client never started is not in its process tree.*
- **D21** (1.2) Argument-level detail lives in a tool spec's `notes`, which `docs/tools.md` and `hocuspocus://guide` (1.3: `hocuspocus://tools`) render and `tools/list` leaves out; `tools/list` stays ≤ 40,000 bytes (§4.1; 1.4: D30 replaces that target). *At 43,999 B against the 44,000 B cap no fix could add a word; the model needs the description to pick a tool and the detail only when it uses an argument.*
- **D22** (1.2) Every `events` entry carries `origin: agent|other`, and the host holds a call's events until its work ends, publishing none for a rolled-back call (§4.7). *Next to a user, the agent could not tell its own edits from the user's (review 15), and a rolled-back call's events would describe changes that no longer exist.*
- **D23** (1.2) `undo`/`redo` stop at the first step not labelled `HocusPocus:` unless `include_user_steps: true` (§4.7). *In review 15 `undo {steps: 2}` silently undid the user's own edit; crossing a user step needs explicit consent, as discarding unsaved work does (D11).*
- **D24** (1.2) `pdg cook` refuses an untitled or unsaved scene when the graph has out-of-process ROP TOPs; `save: true` saves first (§4.7). *Those work items load the hip on disk, so in review 14 a dirty scene cooked the old parms and reported success.*
- **D25** (1.3) The bridge never switches Houdini on its own. A pin holds until the next `houdini_connect`; a pinned Houdini that exits gives `instance_lost`, and with several live instances and no pin, calls that change a scene give `ambiguous_instance` (§3.3, §3.6, §9). *In review 19 a dead pin fell over silently to the user's GUI, and a `parm_set` meant for a killed worker changed the user's scene; an unpinned session edited whichever instance had started last.*
- **D26** (1.3) Jobs and `events` cursors are addressed by pid: job ids are `<pid>-<id>` and the bridge routes `job` to that Houdini whatever is selected; `next_since` is `<pid>:<seq>` (§4.7, §7). *Ids and sequence numbers are per process: in review 19 a worker's job read as `job_not_found` from the GUI, and a GUI cursor silently skipped a worker's first events.*
- **D27** (1.3) Writers write through `render`; `cook` never writes files. `render` takes File Cache and ROP SOPs as jobs with progress and cancel, `cook` on a writer says it wrote nothing, and a save-button `press` checks its files (§4.5, §4.6, §4.7). *In review 17 `cook {frame_range}` on a File Cache reported success with no cache on disk, and the Save button reported success writing to a drive that did not exist.*
- **D28** (1.3) A `minimal` profile of 14 tools for clients with a small context, and argument descriptions of at most 12 words with the detail in `notes` (§3.5, §4.1). *Every new argument fought the 40,000 B `tools/list` cap; the cap now pays for an argument's name and type, not its explanation, and a small client gets 20.4 KB.*
- **D29** (1.3) Integration tests over about 1.5 s are marked `slow` and run only with `--runslow` or `-m slow`; CI runs both sets (§11). *The tier had grown to about 4 minutes; the fast set, run before every host commit, is about 50 s.*
- **D30** (1.4) The `tools/list` budget caps what clients see by default: the full profile with `result_content = "text"` ≤ 32,000 B, and `both` ≤ 44,000 B; the 40,000 B target on `both` is gone (§4.1). *The old target measured output schemas that the default `text` mode never sends, so it spent the headroom of the shape nobody received; no tool or argument was removed.*
- **D31** (1.4) `viewport_capture`'s ROP source renders through the Flipbook ROP, then the OpenGL ROP, then Karma; `flipbook_rop` is the source's name and `opengl_rop` stays as an alias, and headless Flipbook renders keep the child hython (§8). *Houdini 22 deprecates the OpenGL ROP; the Flipbook ROP has no second-render or large-stage crash of its own, but a render after a deleted Flipbook ROP still segfaults hython, so only the single-thread workaround could go.*

### Verified deviations (M5 reconciliation)

Facts found while implementing, now reflected above:

- GUI autostart lives at `houdini/scripts/python/uiready.py` (§10.1).
- `hasUnsavedChanges()` is always `True` in hython; the host tracks dirtiness headless (§3.2).
- A second OpenGL ROP render in one hython segfaults, and so does a Flipbook ROP render after a Flipbook ROP that rendered was deleted; headless, both render in a child hython (§8).
- `undo`, `time`, `selection`, `hda`, `cook`, `pdg`, `render`, `job`, `viewport_capture` register with `scene=False` (§4.1).
- One `hocuspocus.toml` configures host and bridge; `HOCUSPOCUS_*` env wins (§3.7).
- `setChildrenFromData` skips unknown types and parms silently, defaults `clear_content=True`, and puts inputs without `to_index` on input 0 (§5.16).
- `hou.setFps` rescales the frame range unless told not to (§5.17).
- The surface is 35 tools, 31 in `core` (§4.7, D4).
- All cursors, including `geo_read.next_cursor`, are opaque strings (§4.1).

---

### Known limitation: launch lifetime

A Houdini started by `houdini_connect {launch}` is launched detached (new process group, and breakaway from the job object where Windows allows it), but in the verified setup (review 08) it still exited when the bridge that launched it exited. Treat it as owned by the bridge: it ends when the MCP client stops the bridge (end of a session, or a one-shot script exiting), and its unsaved work is lost. This is acceptable for interactive sessions; agents should `hip_save` before a session ends, or attach to a Houdini the user started. Since 1.1 `hocuspocus launch` is that "start it yourself" path from a terminal or script.

Since 1.0.1 this is visible rather than discovered: `houdini_connect {launch}` returns `launched.outlives_server` (false when the child shares the bridge's kill-on-close job object, i.e. breakaway was refused; the bridge cannot see a client that kills its whole process tree, so true means "should"); the launcher sets `HOCUSPOCUS_LAUNCHED_BY=<bridge pid>`, the host writes it into its registry entry as `launched_by`, and `houdini_status.instances[]` shows it; the bridge also records each launch in `<state_dir>/launches/<pid>.json`, so a later bridge that finds no live instance answers `houdini_offline` naming the dead Houdini and the server that launched it, with the keep-a-session-open / attach-by-pid hint. No new process-isolation mechanism was added.

## 16. Non-goals for 1.0

HocusScript or any custom language; multi-user or remote (non-loopback) access;
Streamable-HTTP direct-to-Houdini transport; APEX graphs; a Houdini UI beyond a status
shelf tool; vendoring the MCP SDK into Houdini; supporting Houdini 21 or earlier;
Linux/macOS **testing** (the code must not be Windows-only, but 1.0 is qualified on
Windows only).
