# HocusPocus Design Bible

**Version:** 2.0 design, 2026-10-14; the 1.4 bible is at git tag `v1.4.0`.
This document is the design authority for 2.0 (branch `release/2.0`). It was rewritten at
milestone M3 from [`redesign/spec-2.0.md`](redesign/spec-2.0.md), which planned the work.
Rows and sentences marked (1.1) to (1.4) changed in that 1.x release and still hold in 2.0;
(2.0) marks what 2.0 changed. The 2.0 contract decisions are D35 to D44 (§15). The 1.4
tools that 2.0 serves only in the `compat_1x` profile are described in Appendix A;
[`migration-2.0.md`](migration-2.0.md) maps each of them to its 2.0 replacement.
**Status:** authoritative. When code and this document disagree, one of them is wrong
and the disagreement is a bug to fix, not a fact to live with.

**Implementation notes:** the reviews, evaluation logs and image evidence behind 1.0 to
2.0 are indexed in [`docs/redesign/README.md`](redesign/README.md); the GUI/headless
differences in [`docs/parity.md`](parity.md); the `tools/list` sizes per release in
[`docs/redesign/budget.md`](redesign/budget.md).

HocusPocus is an MCP server that lets AI agents drive a live SideFX Houdini session
and manage its scene files. This document describes how HocusPocus **should** be. The six
review reports under `docs/redesign/review/` 01 to 06 record what was wrong with 0.9; the
evaluations 07 to 24 measured 1.x and are the evidence for 2.0.

---

## 0. The one-paragraph version

An agent talks MCP over stdio to a thin **bridge** process (standard CPython, official
`mcp` SDK). The bridge finds or launches a Houdini instance, remembers instances, roles and
jobs in a small **ledger**, and forwards tool calls and resource reads over an
authenticated loopback HTTP channel to a small stdlib-only **host** running inside Houdini.
The host executes every `hou` call on Houdini's main thread, runs every scene change
through one **transaction engine** as one named undo group, and returns compact JSON in
Houdini's own vocabulary. The default profile has 18 tools: `edit` changes the scene in one
transaction, `inspect` and `search` read it (and every read is also a resource with an
ETag), `look` returns a picture from the cheapest renderer that answers the question, and
session, hip, cook, render, job, undo, time and a Python escape hatch cover the rest. Errors
tell the agent what to do next. Nothing the agent needs is ever redacted, and nothing it
doesn't need is ever sent.

---

## 1. Principles

1. **Houdini's vocabulary is the API.** Node paths, parm names, parm tuples, input
   indices and labels, node type names, flags, cook, hip. If an LLM that has read the
   SideFX docs cannot guess a tool's arguments, the tool is wrong. No invented carriers,
   documents, bundles, checkouts, grids, or revision counters on the agent surface.
2. **Small surface, deep tools.** 18 tools by default (2.0), few enough to hold in one's
   head, each doing one thing well with a few well-chosen options. Batch inputs where Houdini users batch
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
13. **Measure what agents pay.** (2.0) Every tool and resource has a recorded byte budget
    per workload, enforced by the workloads tier (§11). A change that raises bytes or
    calls per task must say why.
14. **One way to change the scene.** (2.0) All mutations go through the transaction engine
    (§3.9), whether the agent called `edit` or a convenience tool. There is one undo
    policy, one rollback and one echo shape.

---

## 2. What we are replacing, and why

### 2.1 From 1.x to 2.0

Every evaluation since 1.0 (reviews 07 to 24) measured the same two numbers: calls per task
and bytes per call. 1.x drove both down by trimming descriptions, moving detail into
`notes`, adding filters and summary modes, and chasing a `tools/list` cap. Those are the
limits of the 1.x contract. 2.0 changes the contract where the evidence says it matters
and leaves the rest alone.

| Finding (1.x) | Consequence for 2.0 |
|---|---|
| One tool per noun: a build is a chain of `node_create`, `node_connect`, `parm_set` and `node_edit` calls, each its own round trip, undo step and echo (the city build workload: 21 calls; the scorecard twelve: 49) | `edit`: every scene change of a task in one call, `$id` references between ops, a dry run, one undo group, one echo (§4.5, §3.9). `node_create` and `parm_set` stay as conveniences on the same engine |
| Eleven read tools with eleven schemas, every read a tool call; the full profile's `tools/list` reached 30.8 KB of a 32 KB cap (1.4.0) | `inspect` and `search` (§4.4), and every read a resource with an ETag and subscriptions (§3.10). 18 tools by default; `tools/list` caps cut to 24 KB / 34 KB (§4.1) |
| Jobs bound to the process that started them, addressed as `<pid>-<id>`; a bridge restart forgot every Houdini that had exited and every job (review 19) | The bridge ledger (§3.8): durable instances with names and roles, opaque job ids, `on` to run a cook, render or look on another Houdini without moving the pin (§3.6) |
| Four capture sources behind one argument (`viewer`, `flipbook_rop`, `opengl_rop`, `cop_path`), and Karma only through `render` (reviews 13, 17, 18, 22) | `look` (§4.6, §8): one picture tool whose `quality` chooses the backend |
| The catalogue, `docs/tools.md`, the guide and the budget numbers maintained by hand side by side | One spec module per tool; everything else generated (§3.5) |
| Evaluations run by hand, once per release | The workloads tier: scripted evaluations with byte and call budgets, nightly (§11) |
| GUI/headless differences found by accident (a read dirtied the GUI hip; selection moved the user's panes) | The parity matrix, tested in CI (§11, `docs/parity.md`) |

### 2.2 From 0.9 to 1.0

Summary of `docs/redesign/review/01…06`. Read those for evidence; this is the verdict.

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
   │  owns: MCP protocol (tools, resources and subscriptions, prompts), tool catalogue,
   │        argument validation, instance registry and ledger, routing (pins, roles, on),
   │        launching Houdini, offline behaviour, response budgeting
   │  loopback HTTP/JSON, bearer token, Origin check, small versioned RPC
   ▼
hocuspocus.host ── the HOST ── runs inside Houdini (GUI or hython), stdlib only
   │  owns: MainThreadExecutor, transaction engine and undo groups, tool implementations,
   │        resource reads with ETags, look backends, jobs, instance registry entry,
   │        scene generation, the dirty flag, the event ring buffer
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
`hou.undos.group("HocusPocus: <tool> <summary>")` (ASCII, at most 100 characters); an
`edit` call is labelled `HocusPocus: edit <n> ops`. Every scene change in it is an op of the
transaction engine (§3.9). Read-only tools never open a group. `undo` exposes the label
history so users and agents can revert "the last agent action". A call that fails is
rolled back, by compensation inside the group or by undoing the group after it closes
(§3.9); the result reports whether that happened (false when undo is disabled or the undo
failed), and a tool error whose `detail.rolled_back` is `null` gets that value.

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
| `/hp/v2/resource?uri=…` | GET | (2.0) a resource template read (§3.10) with its etag; `If-None-Match` with the current etag answers `not_modified` |

Auth: `Authorization: Bearer <token>`; 401 otherwise. `Origin` and `Host` headers, if
present, must name a loopback host; 403 otherwise (the `Host` check stops DNS rebinding
from reading `/health`). Request body cap 4 MB; idle connections time out after 60 s.
The host runs only the tools of its own `profile` (§3.7). A tool another profile lists is
refused with `invalid_argument` and a hint naming that profile (`profile = "full"` for
`hda`, `pdg`, `events`). (2.0) A 1.4 tool that 2.0 removed is refused on a 2.0 profile
with its replacement in the hint (`tools/migration.py`, the table of
`docs/migration-2.0.md`) and the `profile = "compat_1x"` setting that keeps it.

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

**Dirty tracking** (2.0, parity G1). One dirty flag, the same in both modes, decides what
every tool reports as `dirty` and what `on_unsaved` (`hip_new`, `hip_open`,
`houdini_connect {quit}`) and `pdg cook` refuse: the host's tracked flag, set by the
transaction engine after every successful mutation and by the `scene=False` tools where
they change the scene, OR a change made outside HocusPocus since the last save, load or
clear (an `origin: other` node event from the ring buffer, or in the GUI Houdini's own flag
set between two HocusPocus calls, `host/runtime.py`). Save, load and clear mark it clean.
`houdini_status` says which (`hip.dirty_source`: `tracked`, `user_event` or
`houdini_flag`), `unsaved_changes` carries it in `detail.dirty_source`, and Houdini's
`hou.hipFile.hasUnsavedChanges()` is reported apart as the diagnostic `houdini_flag`. That
flag alone is never the answer: verified on
22.0.466, in hython it is always `True`, even right after a load, clear or save, and in the
GUI it is set by HocusPocus's own temporary nodes (a `look` camera and ROP, an
`inspect what: type` probe instance, `render`'s output override), so in 1.x a mere read
made a later `on_unsaved: fail` refuse in the GUI only.

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
   deterministic **with no Houdini running**, and (2.0) the resources, resource templates,
   subscriptions and prompts of §3.10 and §4.8.
2. **Validate arguments** against the catalogue's JSON Schema (SDK v2 does not), and
   return schema failures as `isError` results with `code: invalid_argument`.
3. **Resolve the target instance.** Order: explicitly connected instance (via
   `houdini_connect`; never another one in its place, §3.6) → the only live instance →
   with several live and none pinned (1.3, review 19 papercut 2), calls that change a
   scene refuse with `ambiguous_instance` (the candidates, and the `houdini_connect
   {"pid": …}` call for each), and reads go to the preferred instance (a GUI session
   first, then the most recently started) with the warning in `_meta.warnings` and in the
   result as `_instance: {pid, label, ui, warning}`. "Changes a scene" is every tool not
   `read_only` except the reading forms of the `scene=False` tools (`time` without
   arguments, `job` status/result/list, `undo history`, `hda list`, `pdg`
   status/workitems; in `compat_1x` also `selection` without arguments and
   `viewport_capture`) and `look`; an `edit` with `dry_run: true` changes nothing but is
   routed as a change, so it validates against the scene it would change. Every result a
   host answered (ok or error, `houdini_status` and `houdini_connect` included) carries
   `_meta.instance: {pid, label, name?, role?}`. If none: `code: houdini_offline` with the
   hint "call houdini_connect with launch to start one".
4. **Route `on`** (2.0). `cook`, `render`, `look` and `job` go to the Houdini their `on`
   names, whatever is pinned (§3.6).
5. **Forward** `tools/call` to `POST /hp/v1/call`. One attempt; never retry a mutation.
   On connection failure after the request was sent, return `code: delivery_unknown`
   with the instructions to inspect state before repeating.
6. **Bridge-local tools:** `houdini_status` (merges registry + ledger + host `/health` + a
   cheap host `session` call when online) and `houdini_connect` (attach, launch, pin by
   pid, name or role, quit).
7. **Launch Houdini.** `houdini_connect {launch: {mode: "gui"|"headless", hip?, wait_s}}`
   runs `houdinifx.exe`/`houdini.exe` (GUI) or `hython -m hocuspocus.host` (headless) from
   the detected `$HFS` (config, `HFS` env, or the newest `Side Effects Software/Houdini 22.*`),
   then polls the registry until the new pid appears or `wait_s` elapses.
8. **Budget responses.** Enforce `max_response_bytes` (default 16 KB) by truncating list
   payloads at item boundaries and setting `truncated: true` plus `next_cursor` when the
   host supplied one (§4.1). Images are exempt from the byte cap but downscaled by the host.
9. **Keep the ledger** (2.0, §3.8) and poll job progress (§7).

The bridge keeps **no durable state it needs to work**: deleting the ledger loses
memory (roles, exited instances, finished jobs), never a live Houdini or a running job. The
registry stays the authority on what is live; the ledger remembers what the registry
forgets.

### 3.4 Host RPC contract (`hp/v1` calls, `hp/v2` resources)

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
or error: `main_thread_ms` is the time the tool ran on Houdini's main thread and `queue_ms`
the wait for the main thread before that, so latency drift can be split between the bridge,
the queue and Houdini. For a tool that runs off the main thread (`render`, `cook`, `pdg`,
`look`, `events`, `job`; `viewport_capture` in `compat_1x`), both are the sums over the main-thread steps run on the
call's behalf: its own executor calls and the steps of jobs it started that finished while it
waited (review 24 N5: a 1.9 s `cook {profile}` said `0`); a step finishing after the call
returned is not counted. A call that ran no main-thread step reports
`{"main_thread_ms": 0, "off_main_thread": true}`.
The protocol version `hp/v1` is in the path; incompatible changes
bump it and the bridge refuses to talk to an older host with `code: version_mismatch`
and the hint "run `hocuspocus install-houdini` and restart Houdini".

(2.0) The call protocol is unchanged in shape: `POST /hp/v1/call` serves every tool of
every profile, so a 1.4 bridge and a 2.0 host (or the reverse) still agree on the 1.4
tools. 2.0 adds `GET /hp/v2/resource` (§3.10). spec-2.0 §4 also planned a
`POST /hp/v2/call` with `hp/v1` kept as an alias for one minor release, and server-sent
progress on `/hp/v2/jobs`; neither exists, because nothing in the call shape changed and
the bridge's 0.5 s poll (§7) serves progress. A future incompatible call change takes
`hp/v2/call` and keeps `hp/v1` for one minor release.

### 3.5 The shared catalogue: spec files

(2.0, spec-2.0 §5.1, D41) Every tool is one module, `src/hocuspocus/tools/spec/<tool>.py`,
named after the tool and exporting `SPEC = ToolSpec(...)`: name, description (≤ 60 words),
input JSON Schema built with the helpers in `spec/_helpers.py`, output JSON Schema (where
stable), `notes` (argument-level detail), `examples`, MCP annotations (`readOnlyHint`,
`destructiveHint`, `idempotentHint`, `openWorldHint=false`), `profiles` (the profiles that
list it), `headless_ok` and `bridge_local`. `spec/__init__.py` loads them in its explicit
`ORDER` (never directory order) and `tools/catalog.py` is the stdlib-only loader both
processes import: the host to map names to implementations and to refuse tools outside its
profile, the bridge to register MCP tools. `tools/profiles.py` names the profiles and
`tools/migration.py` the removed 1.4 tools and their replacements. Every `/hp/v1/call`
carries the bridge's profile: a host runs the 1.4 tools for a `compat_1x` bridge whatever
its own profile, and a 2.0 profile (bridge or host) answers a removed 1.4 tool with
`invalid_argument` and the migration hint. From the same objects
`hocuspocus docs tools` renders `docs/tools.md`, the bridge serves `hocuspocus://tools`, and
`python -m hocuspocus.tools.docs --budget` measures every profile's `tools/list` and appends
a dated row to `docs/redesign/budget.md`. Unit tests assert that `ORDER` names every module
and nothing else, that every spec has an implementation, a description under the word cap,
argument descriptions of at most 12 words and passing examples, that `docs/tools.md` is
fresh, and the budget caps (§4.1). A 1.4 tool that gained 2.0 arguments (`on`, `role`) or
result fields (`role`, `recent`) declares them as `v2_extra`, a partial input and output
schema the 2.0 profiles deep-merge into its spec (dicts key by key, new keys last); the
`compat_1x` listing leaves them out, so its `tools/list` bytes stay those of 1.4 (the
goldens under `tests/unit/goldens/`).

### 3.6 Lifecycle and multiple instances

- **GUI autostart.** The installed Houdini package adds the payload to `HOUDINI_PATH`
  (`hpath`) and the copied package directory (with `--dev`, the checkout's `src/`) to
  `PYTHONPATH`. A `uiready.py` hook (runs once the UI exists) calls
  `hocuspocus.host.start()` unless `autostart = false`. Startup never raises into
  Houdini; failures go to the host log and `hou.ui.setStatusMessage`.
- **Headless.** `hython -m hocuspocus.host --hip file.hip` registers like any instance
  with `"ui": false`. GUI-only argument forms (`look {source: "viewer"}`) return
  `code: ui_required` with the headless alternative in `hint`; no whole tool is GUI-only
  (parity G6: the catalogue's `headless_ok: false` and the "(GUI only)" suffix are unused).
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
- **Roles** (2.0). Every Houdini has a role, stored in the ledger: `editor` (the default
  for a GUI Houdini) or `worker` (headless). `houdini_connect {pid|name|launch, role}` sets
  it; `{role}` alone pins the least busy live Houdini with that role (fewest
  `jobs_running`, then not `busy`, both from `/health`, then GUI first and newest first);
  none is `houdini_offline` with the candidates and their roles. `houdini_status` rows and
  `connected` carry `role`, `_meta.instance` too.
- **`on`** (2.0). `cook`, `render`, `job` and `look` take `on: pid | name | role`
  (`bridge/routing.py`; an integer or digit string is a pid, `editor`/`worker` a role,
  any other string a name). The bridge sends that call to the Houdini it names whatever
  is pinned or selected, without moving the pin and without the ambiguity refusal (the
  target is explicit), tags `_meta.instance` with it and records the job against it. A
  role picks the least busy live Houdini with it; a pid or name the ledger remembers that
  has exited is `instance_lost` (never run elsewhere), one it never knew `houdini_offline`
  with the candidates. A job id always goes to its own Houdini, so `on` matters to `job`
  only for `list`. `edit`, `hip_*` and every other tool have no `on` and use the pinned or
  selected instance: a scene change always lands where the agent pinned.

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
profile = "core"            # minimal | core | full | compat_1x (§4.1); the host refuses tools outside its profile
log_level = "INFO"
hfs = ""                    # bridge: explicit Houdini install dir for launch
result_content = "text"     # bridge: text | both | structured (§4.1)
```

`profile` accepts `v2`, the M1–M2 preview of the 2.0 surface, as `full` for 2.0.x.

`HOCUSPOCUS_WORK_DIR` (environment only) is where a Houdini that `houdini_connect {launch}`
starts (`hocuspocus launch` uses its own cwd or `--work-dir`, §10.2), and so the `$HIP` and `$JOB` of its untitled scene; default the user's home
directory, as for a GUI Houdini started from the desktop. Never the state dir (it holds
`instances/` and `logs/`) and never the repo. `hython -m hocuspocus.host` moves there too
after start-up (`--work-dir` overrides; hython's own cwd stays off `HOUDINI_PATH` as long
as it was started from a neutral directory).

### 3.8 The bridge ledger

(2.0, spec-2.0 §3, D37) The bridge keeps `<state_dir>/ledger.sqlite` (`bridge/ledger.py`;
SQLite in WAL mode, one connection per bridge; bridges on one machine coordinate through
the registry files, each has its own ledger rows). Every profile writes it; the 2.0
profiles show it. Tables: `instances(pid, name, role, label, ui, hip, started, last_seen,
launched_by, houdini, alive)`, `jobs(id, host_id, instance_pid, tool, state, progress,
message, started, finished, result_path, result, status, updated)` and `launches(pid, argv,
work_dir, time, mode)`; `host_id` (the host's `<pid>-<id>`), `status` (the last host
snapshot), `result` (inline) and `alive` are additions to the spec's columns. On first use
the bridge reconciles it with the registry (instances not live are marked dead) and every
scan keeps it current; a reused pid with a new `started` starts a new row. Jobs are recorded
when a call returns a `job_id`, from `job status`/`list`/`result` answers and from the
progress poller; `job result` stores the result, spilled to `<state_dir>/jobs/<id>.json`
over 16 KB; finished rows beyond 500 are pruned. A file that cannot be opened falls back to
memory, a bridge built with a fake `scan` (tests) uses memory, and a ledger error is logged
and never fails a call. `houdini://jobs` reads `ledger.jobs_snapshot()`.

- **Instances.** `houdini_status` lists the live ones and, under `recent`, up to five dead
  instances the ledger remembers (`{pid, label, ui, role, hip, started, last_seen, alive:
  false, name?}`, newest first), `houdini_connect {quit}` included.
- **Job ids.** On the 2.0 profiles a result's `job_id` (and each `jobs[]` row's, and an
  error's `detail.job_id`/`detail.last_status.job_id`) is the ledger's opaque id, `j` and
  five hex digits (more on a collision). `job` accepts a ledger id or a host id
  (`<pid>-<id>`) in every profile, and `compat_1x` keeps returning host ids. A ledger id
  the ledger does not have is `job_not_found`. After a bridge restart a ledger id still
  reaches its Houdini; when that Houdini has exited, `job status` is `instance_lost` with
  the ledger's last status, and `job result` of a finished job returns the stored result
  with a note.
- **Progress.** The poller (§7) writes each snapshot to the ledger and reports progress
  from the ledger's row, so a `job` call with a ledger id is polled through its host id.

### 3.9 The transaction engine

(2.0, spec-2.0 §2.4, principle 14, D35) `host/tx.py`. Every scene mutation is a `Plan` of
`Op` steps. `edit` builds a plan from its `ops`; `node_create`, `parm_set` and the 1.4
mutation tools of `compat_1x` (`node_connect`, `node_delete`, `node_edit`, `node_copy`,
`node_layout`, `network_build`, `selection` set) build one from their 1.4 arguments and
shape the result back into their 1.4 result, which is unchanged. So there is one undo
policy, one rollback and one echo engine.

- **Ops:** `create`, `delete`, `connect`, `set`, `node` (rename, flags, color, comment,
  position, lock, spare parms, bypass), `copy`, `layout`, `build` (`hou.data` with
  `press`) and `select` (§4.5).
- **References.** An op may carry an `id` (letters, digits, `_`); a later op names its node
  as `$id` (or `$id/child`, `$id/parm`) in its path fields, and the reference resolves to
  the path the op actually produced when the later op runs (after Houdini numbered or
  renamed it).
- **Validation.** `validate` checks a plan without changing the scene, against the scene
  as the earlier ops leave it: types resolve in the parent's category, parents exist and
  are networks, parm and tuple names exist on the node or its type or are spare parms an
  earlier op adds, inputs exist by index, name, `next` or `$id` in the same network, names
  are free, locked assets are refused. It returns the plan with resolved paths
  (`predicted: true` where Houdini will number the node) and every problem; an op that
  depends on a failed op is not reported again. A dry run is that.
- **Execution.** `execute` runs the plan on the main thread inside the one undo group the
  dispatcher opened. Houdini refuses `performUndo` inside an open group, so a failing op is
  reverted by compensation (`Rollback`), newest first; with `partial` only that op's own
  changes are reverted and the rest stand. `rolled_back` is what really happened: a delete
  cannot be compensated, so after one the dispatcher undoes the whole group once it closes
  and reports that outcome.
- **Echo.** By default one compact row per touched node (`path, type`, then only what is
  notable), each node cooked once after every op ran, with the ops' results folded in and
  an `ids` map; `return: ops` adds one row per op; `return: full` gives the 1.4 full
  shapes (spec-2.0 §7 M4: the per-op rows repeated every created node's path).

### 3.10 Resources

(2.0, spec-2.0 §2.7, D36) The bridge lists `houdini://status`, `houdini://instances`,
`houdini://jobs`, `houdini://outline`, `houdini://problems`, `houdini://events`,
`hocuspocus://guide` and `hocuspocus://tools`, and the RFC 6570 templates
`houdini://node/{path}{?include,parms,include_defaults}`, `outline{?root,depth}`,
`network/{path}{?depth,format}`, `geo/{path}{?frame,class,attribs,start,count,stats}`,
`image/{path}`, `stage/{lop}{?prim,include,time,summary}`,
`type/{category}/{name}{?parms,folder,detail}`, `types{?q,category,limit,cursor}`,
`problems{?root}` and `events{?since,limit}` (`compat_1x` keeps the 1.4 list, Appendix A).

- **One answer, two doors.** The host's `GET /hp/v2/resource?uri=` (`host/resources.py`)
  parses a URI into its `inspect` call (`types`: `search kind: types`; `status`: the host's
  `houdini_status`) and runs it through the dispatcher, so a resource's body is the
  matching tool result byte for byte and its etag is that result's `etag`. The bridge
  serves `status` and `instances` itself (etag `bridge:<16 hex>` of the body).
- **ETags.** `<pid>:<scene_generation>:<16 hex>`, the first 16 hex digits of a BLAKE2b
  digest of the canonical JSON of the body (sorted keys, compact separators, an `inspect`
  body without its own `etag`), for every resource and `inspect` (2.0 M4: the earlier
  digest of cook counts gave byte-identical bodies a new etag after any recook, so the
  soak never revalidated). The host builds the body anyway; a change that leaves the
  answer alone (a `look`, a cook elsewhere) keeps the etag. The bridge
  forwards the client's `_meta["If-None-Match"]` (or `_meta.etag`), returns `_meta.etag` and
  `_meta.cache_control` (`no-cache` for `houdini://`: keep it, but revalidate;
  `max-age=86400` for the static `hocuspocus://` texts), and answers a match with no
  contents and `_meta.not_modified: true`.
- **Subscriptions** (`resources/subscribe` on 2025 sessions, `subscriptions/listen` on
  2026-07-28 ones) cover `status`, `jobs`, `events` and `node/{path}`. While any exists the
  bridge polls every 0.5 s (a `houdini://jobs` read is the heartbeat; nodes and events are
  re-read when the events seq or the scene generation moved, and every 5 s regardless) and
  sends `notifications/resources/updated` when an etag changes.

---

## 4. The tool surface

### 4.1 Conventions

- **Names:** `snake_case`, `[a-z0-9_]`, no dots (several model APIs reject dots). Verb
  last for actions on a noun (`node_create`, `parm_set`), noun alone for query tools
  that take a mode (`inspect`, `search`, `undo`, `time`), a verb alone for the two whole-
  scene tools (`edit`, `look`). The MCP server name (`hocuspocus`) is the namespace.
- **Identity:** Houdini node paths (`/obj/geo1/box1`) and parm paths
  (`/obj/geo1/box1/sizex` or tuple `/obj/geo1/box1/size`). Nothing else. Tools that
  return nodes return their final resolved path. Within one `edit` call an op's `id` is
  `$id` (§3.9).
- **Arguments:** flat, typed, `additionalProperties: false`, enums for closed sets,
  defaults stated in the schema's `default` (1.2: not repeated in the description). Batch
  tools take `items: [...]` (`edit`: `ops: [...]`) and return `results: [...]` in the same
  order; one failing item fails the whole call and rolls back the undo group unless
  `partial: true`. Every batch error (and each failed row's `error` with `partial`) has one
  shape: the message starts `items[i] (<path>): ` and `detail` carries `{item, path,
  rolled_back}`, where `rolled_back` is true only when every change the call (or, with
  `partial`, the item) had made was actually undone.
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
- **Budget** (2.0, D44). CI-tested (`test_tools_list_budget`) on the serialised
  `tools/list` result in the two shapes a client can receive: the default
  `result_content = "text"` (names, descriptions, input schemas, annotations; no output
  schemas) and `both` (output schemas declared too). The 2.0 caps are on the `full`
  profile: `text` ≤ 24,000 B, `both` ≤ 34,000 B. `compat_1x` keeps the 1.4 caps, `text` ≤
  32,000 B and `both` ≤ 44,000 B (D30), and its bytes are the 1.4 goldens. The test prints
  every profile × mode, and `docs/redesign/budget.md` keeps the history (1.4.0:
  14.4/27.4/30.8 KB `text` for minimal/core/full; at the M3 cut-over the 2.0 profiles
  measured 14.8/20.3/22.8 KB `text` and 17.9/26.6/29.1 KB `both`, `compat_1x` 30.8/40.4 KB). Each description ≤ 60 words: what the
  tool does and what the model must know to pick it. Argument-level detail (shapes the
  schema cannot state, edge cases, defaults the schema already declares) lives in the
  spec's `notes`, which `docs/tools.md` and `hocuspocus://tools` render and `tools/list`
  leaves out; examples live there too. 1.3: an argument's schema `description` is at most
  12 words (`test_argument_detail_lives_in_notes`), so a new argument costs its name and
  type, not its explanation. Annotations go out without hints equal to the MCP defaults
  (`readOnlyHint: false`, `idempotentHint: false`, and `destructiveHint`/`idempotentHint`
  on read-only tools), which a client reads as the same values. Default result ≤ 16 KB.
  List reads take `limit` (default 50) and `cursor`; results carry `next_cursor` when more
  exist and `total` when cheap. A budget cut never loses rows: the bridge sends
  `max_response_bytes` in the `/hp/v1/call` envelope, list reads end a page at that budget
  with `next_cursor` at the first row not returned, and the bridge trims a still-oversized
  page only when it can rewrite the cursor to resume after the last row kept: an integer
  offset (`next_cursor` = offset + rows kept), `search kind: nodes`' `after:<path>`,
  `inspect what: network`'s `after:<name>`, or `events`' `next_since` (`<pid>:<seq>` of the
  last kept event, with `more: true`; 1.4, review 22 finding 1). Any other page is returned
  whole with `over_budget: true`. `events` also ends its pages at the budget.
- **Profiles** (2.0, D39, D40). `minimal ⊂ core ⊂ full`, set by `profile` (§3.7); the
  bridge lists and the host allows only the profile's tools.
  - `minimal` (10), for clients with a small context: `houdini_status`, `houdini_connect`,
    `hip_open`, `hip_save`, `inspect`, `search`, `edit`, `node_create`, `parm_set`, `look`.
  - `core` (18, the default): `minimal` plus `hip_new`, `hip_merge`, `cook`, `render`,
    `houdini_python`, `job`, `undo`, `time`.
  - `full` (21): `core` plus `hda`, `pdg`, `events`.
  - `compat_1x` (35): the 1.4 `full` catalogue with 1.4 schemas and results, mapped onto
    the 2.0 engines (Appendix A), for a 1.x client script. Served for the 2.0.x releases;
    2.1 removes it (D39). It lists no 2.0 tool and none of the 2.0 extras (`on`, `role`,
    resources, ledger job ids).
- **Non-default only:** parm listings show parms where `isAtDefault()` is false unless
  `include_defaults: true`.
- **Locked HDAs** are opaque by default: `search kind: nodes` and `inspect` `node`,
  `network` and `outline` do not descend into locked assets unless `recurse_locked: true`.
- **`locked` vs `hda_locked`** (1.1): `locked` always means a lock flag, the SOP hard-lock
  (`isHardLocked`, `flags.locked`) or a parm lock; `hda_locked` means the node is a locked
  asset or inside one (`inspect` `node`, `network`, `parms`; `hda`).
- **Every mutation result** includes, for each touched node: `path`, `type`, `errors`,
  `warnings` (after a non-forced cook of that node if it is cheap, else `cook_state:
  "not_cooked"`; errors left from before the change are rechecked with a forced cook,
  §5.18). The result also carries the scene's `dirty` flag after the call (§3.2). 1.4
  (review 22 findings 2, 3): summary rows carry `cook_ms`, the time that cook took
  (Houdini's first cook of an HDA such as `mountain` is ~200 ms); a `create` with `cook:
  false` skips it; and a `node` op never cooks (a rename recooked a mountain), reporting
  `cook_state` from `needsToCook()` and the errors already on the node.
- **Annotations:** read tools (`houdini_status`, `inspect`, `search`) `readOnlyHint:
  true`; `edit`, `hip_new`, `hip_open`, `houdini_python` `destructiveHint: true`;
  `parm_set`, `time`, `cook`, `job`, `look` `idempotentHint: true`; all `openWorldHint:
  false`. A tool whose only side effect is a cook, a temporary capture ROP or host-side
  job state is `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`.
  `compat_1x` keeps the 1.4 annotations (Appendix A).
- **`scene=False` registration.** By default the dispatcher wraps every tool that is not
  `read_only` in one undo group, refuses it in read-only mode and marks the scene dirty.
  `undo`, `time`, `hda`, `cook`, `pdg`, `render`, `job` and `look` (and in `compat_1x`
  `selection` and `viewport_capture`) register with `scene=False` and do that work
  themselves where it applies: `performUndo` raises inside an undo group; reads (`time`
  with no arguments, `hda list`) must not open a group or dirty the scene; cooks, work
  items, renders, looks and jobs are not hip state. Their annotations still say
  `readOnlyHint: false`. `host/tools/registry.py` documents the convention and a unit test
  pins the set.
- **GUI-only forms** (2.0, parity G6) are arguments, not tools: `look {source: "viewer"}`
  is the only one, refused headless with `ui_required`; the spec's `notes` say so.

### 4.2 Session and instances (bridge-local)

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `houdini_status` | — | `connected: {pid, port, houdini, ui, hip: {path, name, dirty, is_new}, time: {frame, fps, range}, env: {HIP, JOB, HIPNAME}, scene_generation, host_version, memory: {rss_mb, peak_mb}}`, `instances: [{pid, port, label, houdini, ui, hip, started, launched_by, name?, selected, busy, jobs_running, host_version}]`, `lost?: {pid, label}`, `bridge_version`, `profile`, `read_only`, `allow_python` | Works offline (`connected: null`). Read-only. 1.3 (review 19 papercuts 4, 9): `selected` marks the pinned instance or the one reads go to; `busy` and `jobs_running` come from each host's `/health` (busy: its main thread has been held, by a call or a waiting one, for at least 1 s); `name` is set with `houdini_connect {pid, name}` and stored in the registry entry, which the host keeps on rewrites; `lost` names a pinned Houdini that has exited (§3.6); `connected.memory` is the Houdini process's resident and peak memory in MB from the OS counters, no psutil (review 17 P2-9). An untitled scene's `hip` carries `note: "$HIP is the launch directory until you hip_save."` | (2.0) Rows and `connected` carry `role`; `recent` lists the dead instances the ledger remembers (§3.8); `connected.hip.dirty_source` says why the scene is dirty (§3.2). M4: defaults and empties are left out (`role` when it is the mode's default, editor for GUI and worker headless; `name` when unset; per row `selected: false`, `busy: false`, `jobs_running: 0`; `recent` when empty) and `connected.memory` unless `detail: true`, so two reads of an unchanged session are byte-identical and `houdini://status` (shaped the same; the host's resource route asks `houdini_status {detail: false}`) keeps its etag. |
| `houdini_connect` | `pid?`, `name?`, `launch?: {mode: gui\|headless, hip?, wait_s=90}`, `disconnect?: bool`, `quit?: bool`, `on_unsaved: fail\|save\|discard = fail` | the new `connected` block; `quit` returns `{quit, pid, exited, saved?}` | Launch uses `hfs` config or auto-detect. 2.0 (parity G7): an attach or launch compares the host's `host_version` (`/health`) with the bridge's and adds a `version_mismatch: ...` warning when they differ (a GUI Houdini runs the host its package points at; the hint names `install-houdini`); a different `hp` RPC version stays the `version_mismatch` error. Headless launches `hython -m hocuspocus.host`. Both modes start in `HOCUSPOCUS_WORK_DIR` (default home, §3.7); `hocuspocus launch` starts in its own cwd or `--work-dir` instead (§10.2). A launched Houdini usually ends with the bridge that launched it (`launched.outlives_server` says; §15, launch lifetime); to keep one across sessions, start it with `hocuspocus launch` (§10.2, 1.1) and attach by `pid`. `quit` (1.2) closes the selected Houdini (or `pid`) through `POST /hp/v1/quit` after the `on_unsaved` check and forgets its registry entry. 1.3: `pid` or `launch` pins (§3.6), `{}` unpins; `name` labels the Houdini given by `pid` or `launch` (moved from any other instance that had it), and `{name}` alone pins the one with that name; a pid or name that is not running is `houdini_offline` with `retryable: false` and the live `candidates` as `{pid, label, ui, hip}`. | (2.0) `role?: editor\|worker` sets the role of the Houdini given by `pid`, `name` or `launch`; `{role}` alone pins the least busy live Houdini with that role (§3.6). |

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

### 4.4 Reads: `inspect` and `search`

(2.0, spec-2.0 §2.3, D36) Two read tools for every client, including those that never
read resources. Both run the registered host implementation of the 1.4 read they stand
for, looked up at call time, so the 1.4 code is never duplicated, and return that read's
result projected for 2.0 (spec-2.0 M4 "read shapes": what is default or empty is left out,
a plain value is said as a value, what every row shares is said once in `common`), or
with `detail: full` the 1.4 result unchanged plus a few keys; the matching resource
(§3.10) runs the same call and returns the same bytes.
Both are read-only and idempotent. The 1.4 reads' arguments and result shapes are in
Appendix A (`node_info`, `parm_get`, `network_describe`, `geo_info`, `geo_read`,
`usd_stage`, `problems`, `node_type_info`, `node_find`, `node_type_search`); `events` and
`job` are in §4.6 and §4.7.

**`inspect`** `{what, target?, ...}`: one flat schema, the union of the 1.4 reads'
argument names; per-`what` options in `notes`. An option the `what` does not take is
`invalid_argument` naming those it takes. Defaults are the 1.4 read's.

| `what` | `target` | Runs (1.4) | Options | Notes |
|---|---|---|---|---|
| `node` | a node path, or `paths` for several | `node_info` | `include`, `include_defaults`, `recurse_locked`, `detail` | Per node: path, type, flags, inputs, non-default parms, errors, warnings, cook state (Appendix A). Compact: `name` only when it is not the path's last segment; `type: "Sop/box"`; `flags` the list of those on; `inputs` positional sources (a path for output 0, `{path, output}`, `null`; trailing empty slots left out); `outputs` (when included) positional lists of destinations; `parms: {name: value}`, or `{name: {value, expression \| expressions, language?, keyed?, locked?, menu_token?, raw?}}` when more than the value matters; no `is_default`, empty `errors`/`warnings`/`messages`, `cook_state: cooked`, `children_count: 0`. |
| `parms` | a parm or tuple path, `paths`, or a node | `parm_get` | `frame`, `include`, `full_strings`, `detail`; with a node: `parms` (glob on name or label, `a\|b`), `include_defaults` | A node target reads its non-default parm tuples (all with `include_defaults`, those the glob matches with `parms`; folders, separators and buttons left out), and `parms: []` when there are none. Compact: `parms: {path: value or row}` (by tuple name for a node target), rows as in `node` plus `type` when not float/int/string/toggle, `hda_locked` when true, `keyframes` when any and the `include` sections; no `kind`, `tuple`, `component_names`, `is_default`. |
| `network` | the root network | `network_describe` `format: data` | `depth`, `include_defaults`, `include_positions`, `recurse_locked`, `cursor` | Houdini's `hou.data` of the children, locked-HDA children replaced by `{type, hda_locked}`; the format `edit`'s `build` op takes. |
| `outline` | the root (default `/`) | `network_describe` `format: outline` | `depth`, `recurse_locked`, `cursor`, `wiring`, `detail` | The scene as a compact tree: display nodes, error counts, flags that are on, no parms; input sources with `wiring: true`. How an agent reads a graph in one call. Compact: also no `children_count` where `children` lists that many. |
| `geo` | a SOP, or an OBJ (its display SOP) | `geo_info`; with `rows: true` `geo_read` | `frame`, `attributes`, `detail`; rows: `class`, `attribs`, `start`, `count`, `group`, `stats`, `cursor` | Counts, bbox, prim types, attributes, groups, volumes; rows as arrays under `columns`, `stats` over the whole class. Compact summary: attributes per class `{name: "float3:color"}` (type, size when not 1, `:type_info`; detail `{name: {type, value}}`, an elided dict `{elided, key_count}`), groups `{name: count}`, empty classes and empty `groups` left out, `bbox` without `center`, volume/VDB columns equal in every row said once in `volume_common`/`vdb_common`, `internal_attribute_count` without its note. Rows and images unchanged. |
| `image` | a Cop node or COP network (its display node) | `geo_info` on a COP | `frame` | `kind: image`, resolution, data window, per-channel min/max/mean; another node is `invalid_argument`. The picture is `look`'s. |
| `stage` | a LOP (or a ROP in a LOP network: the LOP it renders) | `usd_stage` | `prim`, `depth`, `include`, `attribs`, `summary`, `time`, `limit`, `cursor` | Prim rows, attributes, xforms, bindings, layer stack; `summary` gives counts by type and the world bbox. |
| `problems` | the root (default `/`) | `problems` | `include_warnings`, `cook_uncooked`, `recurse_locked`, `timeout_s`, `limit`, `cursor`, `detail` | The "why is my node red" read: errors and warnings, broken references, missing files, unconnected required inputs, failed TOP work items. Compact: no empty `counts`, no `nodes_with_problems: 0`. |
| `type` | `category/name`, or a bare name with `category` | `node_type_info` | `category`, `include_parms`, `include_help`, `folder`, `parms`, `detail` | `compact` parm rows by folder by default; `detail: folders` first for large FX types. Compact and folders: no `is_current_version: true`, empty `version`, `detail: compact` echo or its constant hint, `inputs_count` (kept with `folders`); inputs and outputs as their labels, the lone default output left out. `detail: full` is `node_type_info`'s full result. |
| `events` | — | `events` | `since`, `limit` | The ring buffer since a cursor (§4.7 `events`); `next_since` is `<pid>:<seq>`. |
| `jobs` | — | `job list`, or `job status` with `job_id` | `job_id` | The jobs of the Houdini (ledger ids on the 2.0 profiles, §3.8). |

Returns `{etag, ...the 1.4 result}`; `what` and `target` are not echoed (the caller knows
them). Every 2.0 read leaves out what the caller knows: `node` rows leave out `session_id`,
and `outline` leaves out `format` and, per row, `name` when it is the path's last segment,
`errors` at 0, and `inputs` unless `wiring: true`. `node`, `parms`, `outline`, `geo`,
`problems` and `type` are compact by default (the Notes column: defaults and empties
omitted) and take `detail: compact | full` (`type` also `folders`); `detail: full` restores
the 1.4 shape with only the trims above (the integration tests compare it with the 1.4
reads under `compat_1x`, whose own shapes never change). `etag` is §3.10's (the digest of the
canonical body), so an unchanged etag is an unchanged answer and the matching resource has
the same etag. The bridge
routes `what: events` and `what: jobs` as it routes `events` and `job` (pid-tagged
`next_since`, job ids sent to their Houdini). spec-2.0 §2.6 also lists `what: pdg` for
`pdg workitems`; it is not built, and `pdg {action: "workitems"}` (full) is the read.

**`search`** `{kind, query?, category?, limit, cursor, detail, ...}`.

| `kind` | Runs (1.4) | `query` | Other options | Result |
|---|---|---|---|---|
| `types` | `node_type_search` | required: a name, label or keyword (1.4 ranking, Houdini synonyms, Cop compositing words) | `category`, `include_hidden`, `current_only` (default true) | `{results, common?, total, hint?, notes?, next_cursor?}`; rows `{name, label, description}` (description capped at 80 characters), plus `inputs: "min-max"` unless 1-1, `deprecated`/`hidden` only when true, `other_versions` when non-empty (folded into the current version's row), `child_category`; no `version`; `common` hoists `category`, and `child_category`/`typical_parents` the rows share. |
| `nodes` | `node_find` | optional: a type glob | `root` (default `/`), `pattern` (name glob, `hou.Node.glob`), `flags`, `has_errors`, `recurse_locked` | `{root?, nodes, common?, total, next_cursor?}` (`root` only when the call did not name it); rows `{path, type}` plus `flags` (the list of those on) when any is on, `has_errors` only when true, `child_count`/`input_count` only above 0; `common: {category}` is the category most rows share, a row in another one names its type `Object/geo`; `next_cursor` is the last row's path. |

Compact by default (spec-2.0 M4 "read shapes"; `kind` is not echoed); `detail: full`
returns `{kind, ...the 1.4 result}` byte for byte.

`node_type_search` has no paging, so `kind: types` pages it: page n asks for the first
offset + limit matches and keeps the last `limit`, adding `next_cursor` (`t:<offset>`)
while `total` counts more, up to the first 1000 matches. `total` is the real number of
matching types, never a cap. Unknown types elsewhere (`edit` create ops, `inspect what:
type`) get their `candidates` from the same ranking.

### 4.5 Mutations: `edit`, `node_create`, `parm_set`

**`edit`** `{ops: [{op, id?, ...}], dry_run = false, return: summary|full = summary,
partial = false}` (2.0, spec-2.0 §2.4, D35). The front end of the transaction engine
(§3.9). Ops run in order in one undo group labelled `HocusPocus: edit <n> ops`. Each op
takes the fields of the 1.4 tool it replaces, with that tool's semantics (§4.5 below for
`create` and `set`, Appendix A for the others):

| `op` | Fields (1.4 source) | `id` names | Result row adds |
|---|---|---|---|
| `create` | `parent`, `type`, `name`, `parms` (`{name: value \| {expression, language} \| item}`), `inputs: [{index \| name, from, output}]`, `flags`, `position`; per op `exact_type`, `cook` (false: no echo cook) and `layout` (`good_position` \| `none`) (a `node_create` item) | the created node | `paired_with` (a `block_end`), `deprecated`, `notes` (callbacks that did not run), `side_effects` (with `press`) |
| `delete` | `paths` (or `path`), `keep_connections = true` (`node_delete`) | — | `deleted`, `reconnected` |
| `connect` | `from` (`null` disconnects), `from_output = 0`, `to`, `to_input` (index, name or `next`) (a `node_connect` item) | the `to` node | `input`, `from` |
| `set` | one `parm_set` item (`path` plus `value`, `expression`, `keyframe(s)`, `channel_ref`, `ramp`, `multiparm_count`, `revert_to_default` or `press`; `language`, `animation`, `frame`), or `{node, parms: {name: value \| item}}` for several parms of one node | the node | `value` or `values`, `wrote_keyframe`, `pressed`, `side_effects`, `outputs_summary` (a writer's save button) |
| `node` | `path` plus `name`, `flags`, `bypass`, `color`, `comment`, `position`, `lock`, `spare_parms: {add, remove}` (a `node_edit` item) | the node | `old_path`, `spare_parms: {added, removed}` |
| `copy` | `paths`, `to_parent`, `names`, `with_inputs = true`, `position_offset` (`node_copy`) | the copy, when there is one | `paths` |
| `layout` | `parent`, `paths`, `mode: children \| good_position` (`node_layout`) | the parent | — |
| `build` | `parent`, `data` (Houdini's `hou.data`, as `inspect what: network` returns it), `on_name_collision: error \| rename \| replace`, `layout = true`, `tag`, `press: {node: [parms]}` (`network_build`) | the parent | `created`, `pressed`, `side_effects` |
| `select` | `paths` (an empty list clears) (`selection` set) | — | `selected`; in the GUI `context_changed` and a note when the selection takes the unpinned Scene Viewer and Network Editor into its network (parity G3: Houdini couples the two, so putting the panes back would change the selection) |

- **References.** An op's `id` names its node (the table's third column); a later op writes
  `$id`, `$id/child` or `$id/parm` in its path fields (`parent`, `path`, `paths`, `node`,
  `from`, `to`, `to_parent`, `channel_ref`, `inputs[].from`; never in parm values, where
  `$F` is Houdini's), resolved to the path the op produced. A `$name` no op declares, or one
  whose op has not produced a node, is `invalid_argument`.
- **Validation and `dry_run`.** Before anything changes the whole plan is validated against
  the scene as the earlier ops leave it (§3.9); every problem is listed in
  `detail.problems` of the first one's error, so one call reports every mistake. `dry_run`
  returns that plan, `{dry_run, ops, plan: [{op, id?, path, ...}]}` with resolved paths and
  `predicted: true` where Houdini will number the node, and changes nothing (`_changed:
  false`: no undo step, no dirty flag, allowed in read-only mode).
- **Failure.** A failing op rolls the call back by compensation and raises the §4.1 batch
  error (`items[i] (<path>): ...`, `detail: {item, path, rolled_back}`); after a delete,
  `rolled_back` is what undoing the whole group did. `partial` skips the up-front
  validation, reverts only a failing op and keeps the rest; the result's `failed` lists
  `{item, op, id?, error}` per failed op.
- **Result** (`return: summary | ops | full = summary`; 2.0 M4, review of the workload
  bytes). `summary`: `nodes`, one row per touched node, each cooked once after every op
  ran (nodes only a `node` op touched, and `cook: false` creates, are not cooked): `path`,
  `type`, and only what is notable: `errors`/`warnings` when not empty (identical lists
  after the first become `errors_same_as`), `cook_state` when not `cooked`, `cook_ms` from
  1 ms, `hint`, and the ops' results for that node (`old_path`, `paired_with`,
  `deprecated`, `hda`, `notes`, `side_effects`); `ids` (`{id: path}`, the path after later
  renames) for every op id; `deleted`, `reconnected`, `selected` (`context_changed`),
  `renamed`, `replaced` when an op did that. What the caller sent (set values, wiring,
  spare parm names) is not echoed. `ops` adds `results`, one row per op (`op`, `id?`,
  `path` (final, after later renames) and what it did, the table's last column). `full`
  gives `results` with the 1.4 full rows (a create's `parms` lists only the parms the call
  set, strings over 200 characters as `{elided, head}`; a set's whole `parm_set` row) and
  `nodes` with `name`, `flags` and `messages`, and `failed` as a count. The review-07
  build (geo, box, mountain, subdivide, OUT) is one call of under 1 KB.
- Destructive (`delete`), not idempotent.

**`node_create`** and **`parm_set`** stay in every profile as conveniences: an `edit` plan
of `create` or `set` ops built from their 1.4 arguments, with their 1.4 results (D35).

| Tool | Args | Behaviour |
|---|---|---|
| `node_create` | `items: [{parent, type, name?, parms?: {name: value\|{expression, language}\|{expr, lang}}, inputs?: [{index\|name, from, output=0}], flags?: {display, render, bypass, template}, position?: [x,y]}]`, `layout = "good_position"\|"none"`, `exact_type = false`, `cook = true` (1.4), `partial = false`, `return: summary\|full = summary` | One undo group. Type resolved like `createNode` (namespace order; `box` → current version). Unknown type → `code: node_type_not_found` with `candidates` from fuzzy match over the parent's category. Returns per item `{path, type, errors, warnings, cook_state}` (`return: summary`, the 1.1 default; identical error lists after the first become `errors_same_as: <path>`); `return: full` gives the `node_info` compact block, whose `parms` list only the parms the call set (values a creation script set, such as a light's ramps, are not the call's edits; `node_info` still reports them as non-default) and string values over 200 characters as `{elided: <chars>, head: <first 80>}`. `parms` go through the same engine as `parm_set`; an expression is `{expression, language}` as `parm_set` and the readers spell it, and the short `{expr, lang}` is accepted too. 1.3 (review 20 N2): as in `parm_set`, a plain set of a menu or toggle with a callback script adds a note to the row that the callback did not run, and `{value, press: true}` runs it after the plain values are set and the inputs are wired; the row then carries `side_effects: {parm: [old, new]}`. A type that `hou.NodeType.deprecated()` reports (the OpenGL ROP in 22.0) adds `deprecated: true` and a note with `deprecationInfo()`'s reason or replacement (1.4, review 22 finding 10: the note once per type per host session; later rows carry only `deprecated: true`). A `block_end` whose `blockpath` is unset is paired as the Tab menu does (1.1, review 11 B12): with the nearest `block_begin` upstream through its inputs, else the only unpaired `block_begin` in the same network; the end's `blockpath` and `templatepath` and the begin's `blockpath` are set (where unset) to relative paths before anything cooks, and the row carries `paired_with`. |
| `parm_set` | `items: [{path, value?, expression?, language: hscript\|python = hscript, keyframe?: {frame?, value}, keyframes?: [...], channel_ref?: "/path/to/parm", ramp?: {basis, keys, values}, multiparm_count?: int, revert_to_default?: bool, press?: bool, animation: replace\|key\|keep = replace}]`, `frame?`, `partial = false` | Exactly one of the value-ish fields per item. Tuple path + list value sets all components; component path sets one. `animation: replace` deletes keyframes/expression first then `set()` (so the value sticks), except that a single `keyframe` only adds or replaces its own key; `key` sets a keyframe at `frame`; `keep` is plain `set()` (Houdini's own behaviour, which may add a key — reported). Menu values accept token or label (label resolved with a hint), string menus only the node builds included (1.3). `press` (1.3, review 17 P0-2 and P1-4) clicks a button or runs the callback script of any parm that has one (menus and toggles too, through `hou.Parm.pressButton`); with `value` it sets the value first. A pressed item returns `pressed` and `side_effects: {parm: [old, new]}` (menus as tokens, multiparms as counts) instead of `value`/`raw`/`is_default`; on a writer's save button (File Cache Save to Disk, a ROP SOP's Render) the output files over its frame range are checked afterwards and the item adds `outputs_summary`, or the call fails with `cook_failed` and `detail.missing`. A plain set of a menu or toggle with a callback carries a note that the callback did not run. Strings accept `$HIP`-style raw text unexpanded. Returns per item: `path, value, raw?, expression?, wrote_keyframe: bool, is_default` (`raw` and long strings as in `parm_get`, which has the only `full_strings`) (a tuple adds per-component `expressions` and the `keyed` component names) and the owning node's `errors/warnings` after a cheap cook. Type mismatch → `code: invalid_value` with the template type and range. Locked HDA → `code: locked` with hint to `node_edit lock:false` or `hda` tool. A locked tuple component computed by an expression (`resolutiony` under `res_mode: autoheight`) that already holds the requested value is skipped; otherwise `locked` names the component, its expression and current value, and the hint names the components to set instead (1.2, review 13). |

The 1.4 hints that named a removed tool now name its op (`edit` `node` op with `lock:
false` for a locked HDA; `node_edit` in `compat_1x`).

### 4.6 Execution: `cook`, `render`, `look`, `houdini_python`, `job`

| Tool | Args | Behaviour |
|---|---|---|
| `cook` | `paths`, `force = false`, `frame?`, `timeout_s = 30`, `profile = false`, `frame_range?: [start, end, step = 1]`, `summary: none\|bbox = none`, `wait_s?` (1.3) | `node.cook(force)` on the main thread; catches `OperationFailed` and reports `errors/warnings/messages` per node, `cook_time_ms` (that node's own cook; inputs already cooked are not recooked, and a forced cook under 1 ms on a node with inputs carries a `hint` naming `profile`), `ok`. Errors left from before a fix, on the node or its inputs, are rechecked (§5.18) unless the last cook took over 2 s, and then `hint` names `force: true`. `profile` force-cooks `inputAncestors()` in dependency order and then the node, one main-thread step each, and returns `chain: [{path, type, cook_time_ms, error?}]` sorted by cost (top 10), `chain_total`, `total_ms` and `attribution`, and the named nodes' `results[].cook_time_ms` is their profiled cook, not the cached re-check (1.2). Inside a for-each loop (1.2, review 12 papercut 5) a node's own step cooks it once, outside the loop, so each `block_end` is force-cooked under `hou.perfMon` (cook stats only, unless another profile is already recording): the body rows (the `block_begin` and every input ancestor of the end downstream of it) get `in_loop`, `cooks`, `per_iteration_ms` and `cook_time_ms` over all iterations, from the monitor's per-node `Cook` (which includes an HDA's contents but not its inputs), and `loops: [{block_end, block_begin, iterations, total_ms, attribution}]` lists each loop (`iterations` is the `block_begin`'s `cookCount()` delta). `attribution` is `per_node` without loops, `perf_monitor` when every loop was measured, and `loop-level` when the monitor could not be used: body rows then keep their one standalone cook. `total_ms` counts each loop once, at its `block_end`. A stopped `hou.PerfMonProfile` cannot be deleted, so in the GUI the profile stays in the Performance Monitor's list. `frame_range` (not with `profile` or `frame`) cooks one frame per main-thread step, so a sim advances incrementally and the GUI stays responsive, with `progress` and `message: "36/96 frames done, cooking frame 37"` (1.3, review 20 N7: the count is `current`, the frames finished); it returns `frame_range`, `frames_cooked`, `total_ms`, and with `summary: bbox` `frames: [{frame, point_count, prim_count, bbox_min, bbox_max}]` from the node's geometry (an OBJ's display SOP; null for other contexts); the current frame is restored afterwards. 2.0 (parity G4): in a GUI session each frame is a visible playbar step, so the start frame is put back only when the user did not move the playbar during the job (a scrub before the last step is put back after it; one after it is left alone), with a note either way; headless it is always restored, without a note. Every mode runs as a job: the call waits `min(timeout_s, job_threshold_s)` (1.3: or `wait_s`, as on `render`; `0` returns the job at once) and returns the result, or `{job_id, state: "running"}` for `job`. 1.3 (review 17): cooking never writes files, so a cooked ROP or File Cache carries a note naming `render` and `parm_set press` on its execute button (P0-1, review 18 papercut 8); `summary: bbox` emits a row only when the counts, bbox or errors change, `through` naming the last frame the row stands for (P2-8), and past 12 rows keeps the first and last six with `frames_truncated: true` and `frames_rows` (2.0 M4; the job's result, which a pushed-progress completion returns, alike); a cancelled cook's job result is the `cancelled` error with `detail: {last_status, partial: {frames_cooked, results, frames?}}` (P1-6); a profiled node that simulates (a DOP network, or a solver SOP with one inside) gets `simulation: {dopnet, resimulated, frame}` and a note that a force-cook reads frames already in the simulation cache (P2-10). 1.3 (review 20 N3): such a node is cooked under `hou.perfMon` with solve stats only, and `resimulated` is whether any DOP solve time was recorded; the simulation's time moves on a cache read too, so without the monitor `resimulated` is true only when the simulation's memory changed, false when neither its time nor its memory did, and otherwise `null` with a note. 1.4 (review 24 N3): the monitor books solve time on the frame being evaluated however many frames were stepped, and a profile force-cooks a warm solver's inputs, which makes Houdini re-solve the frame the simulation stands on (77 ms on a warm Vellum solver read as a full re-run). So `resimulated` is `false` with no solve time (a cache read), `"current_frame"` when solve time was recorded and the simulation's time did not move on a simulation that already held frames, and `true` otherwise; without the monitor a memory change at an unchanged time is also `"current_frame"`. `simulation.simulated_frames: [first, last]` is added when the state tells: `[frame, frame]` for `current_frame`, from the network's `startframe` for an empty or reset simulation, from the frame after the one it stood on when it moved forward. The note says `re-solved only frame N`, or `simulated frames A-B`. (2.0) `on` runs it on another Houdini (§3.6). |
| `render` | `rop_path` (a ROP, or 1.3 a writer SOP), `frames?: [start, end, inc]` (1.4: default the ROP's own frame range, else the current frame), `output?`, `camera?` (1.4), `wait_s?` (default `job_threshold_s`), `thumbnail = true` | Always starts a job that calls `rop.render(...)` (frame by frame in-process, or in a child hython for a headless Flipbook or OpenGL ROP, §8). An explicit `wait_s` is the caller's own threshold; without it the call waits `job_threshold_s` (§7). If it finishes in time returns `{state: "done", job_id, outputs: [paths], thumbnail: image, notes?}`; above 5 outputs `outputs_summary: {count, first, last, pattern, missing_count}` and `outputs_sample` (the first 2 and last 2 paths) replace `outputs`, in the direct result and in `job result` alike (1.3, review 20 N5: a 48-frame `job result` was 8 KB of paths), and `missing` lists at most 20 paths. `notes` warns when the scene has no light objects or LOP lights (image outputs) and when the thumbnail's mean luminance is under 8/255, measured on the flattened thumbnail the agent receives; a thumbnail whose every pixel is transparent gets an "empty" note instead (1.3, review 20 N1). Otherwise `{job_id, state: "running"}` to poll with `job`. Every expected output file, the ROP's own parm included, is checked against `approved_roots`. Karma/Mantra/Flipbook/OpenGL/any ROP. On USD render ROPs (`Lop/usdrender_rop`, `Driver/usdrender`) the outputs are `outputimage`, else the `productName` of each RenderProduct of the render settings prim the ROP uses (its `rendersettings`, the stage's, or the first under `/Render`), per frame; never `lopoutput` (husk's intermediate file). `output` overrides `outputimage`; a `note` says when nothing resolves; a husk failure carries the last 20 lines of its log in `detail.log_tail` (1.2, review 13). The thumbnail is inline only (flattened onto grey); the ROP's output files are never rewritten, so their alpha stays. 1.3 (review 17 P1-3, P1-6): a writer SOP (File Cache, `rop_geometry` or `rop_alembic` SOP) renders its own frame range unless `frames` is given, as a job with per-frame progress and cancel; a File Cache renders through the ROP inside it (no `output` override) and then turns on Load from Disk as its Save to Disk button does, reported as `side_effects: {parm: [old, new]}`. Writing a cache is `render`'s job, never `cook`'s (D27). A cancelled render's job result is the `cancelled` error with `detail: {last_status, partial: {outputs_summary}}`, the files written before the cancel. 1.3 (review 18 papercuts 2, 7): a Cop node that is not a ROP is refused with the `rop_image` nodes of its network as `candidates`; a COP image ROP gets no lights note; a thumbnail PIL cannot read (a float TIFF) goes through `iconvert`, and if that fails a note says why (the `thumbnail_error` field is gone). 1.4 (review 23 P0-1): a ROP whose output is one file for the whole range (a USD layer from `usd_rop`, `Driver/usd` or a `usdexport` SOP, an Alembic archive, any output path without `$F`) renders the range in one `rop.render(frame_range=(start, end, inc))` call, since frame by frame each call overwrote the file and only the last frame survived; progress comes from its per-frame render events, and a cancel sent during the call takes effect after it. The file is then read back: for USD the root layer and every layer it composes (sublayers, references, payloads, such as a `sopimport` save path), and the render fails with `cook_failed` when the layer with the most time samples has fewer than the frames asked (no samples at all is a static stage: a note); an Alembic archive's time range must cover the frames. 1.4 (review 23 P1-2): without `frames` every ROP renders its own Valid Frame Range (`trange` not off: `f1`-`f3`), as writer SOPs did since 1.3, with the note `Rendered <rop>'s own frame range 1-48; pass frames to render others.`; a ROP set to Render Current Frame renders the current frame with a note saying so and that `frames` renders a range. 1.4 (review 23 P1-3): `outputs` lists each file once (a 48-frame USD export is one output, not 48), and a USD export adds `layers: [{path, bytes, time_samples, time_codes?}]`: the root layer, every layer file it composes (sublayers, references, payloads, followed through each layer: a `sopimport` save path holds the data under a stub root layer) and USD files in the root layer's directory that the render wrote, at most 20, each opened as an anonymous copy so no cached layer is reloaded. 1.4 (review 24 N1): before a USD export renders, the layer files it will write (its root layer and the save paths of the LOPs it exports, such as a `sopimport`'s `$HIP/usd/$OS.usd`) are read, and the other USD writer ROPs in the scene (`usd_rop`, `Driver/usd`, `usdexport`) are checked for the same `lopoutput` or save path. A layer row another ROP also writes gets `shared_with: [rop paths]` and a note; a row whose time samples the render replaced with fewer, or with time codes that no longer cover the old range, gets `overwrote_samples` (the old count) and the first note, such as `Overwrote collider_import.usd, which had 48 samples (1-48), with 3 samples (1-3); two ROPs share this layer path: /stage/export_usd also writes it (the save path of /stage/collider_import); re-render that ROP to restore its samples.` (a second `usd_rop` wired to the same `sopimport` silently left a downstream reader with 3 frames). 1.4 (review 21 papercut 5): a ROP whose `camera` parm names a node that does not exist (a fresh OpenGL or Flipbook ROP points at `/obj/cam1`) fails before rendering with `node_not_found` naming the parm and its value, the scene's OBJ cameras as `candidates` and a hint to set the parm, pass `camera` or create a camera; `camera` overrides the ROP's camera for this render, set and restored like `output`: an OBJ camera (checked as for `look`) for its `camera` parm, a camera prim path for a viewport ROP reading a stage (`cameraprim`) or a USD render ROP (`override_camera`); a ROP without such a parm refuses it. 1.4 (review 24 N4): on a viewport ROP with `opsource` and `cameraprim`, a `camera` that does not fit its source fails with `invalid_argument` naming `opsource` before rendering: at `obj`, a camera LOP node or a path that is no node and is a prim on the `loppath` stage (or, with no `loppath`, whose parent is no node either), such as `/out/fb reads /obj (opsource: obj), and /cameras/cam is not a node; set opsource to lop to render the camera prim /cameras/cam from /stage/rset.` with a `parm_set` hint; at `lop`, an OBJ camera. A missing `/obj` node is still `node_not_found`. A rendered override adds the note `Rendered through /cameras/cam (cameraprim restored).` (2.0) `on` runs it on another Houdini (§3.6). |
| `look` | `target?`, `quality: draft\|lit\|final = draft`, `camera?`, `frame?`, `resolution = [1024, 768]`, `fit?: all\|selected\|none`, `source: auto\|viewer = auto`, `on?` | (2.0, D38) One picture of the scene: MCP **image content** (PNG, long side ≤ 1024) plus `{backend_used, chain, quality, target, scene, context, camera_used, fit_used, samples?, frame, path, width, height, rendered, lop_path?, cop_path?, layer?, notes?}`; replaces `viewport_capture` (Appendix A). `target` decides the kind: omitted, the display (`/obj`, or the `/stage` display LOP when `/obj` displays nothing; a note names a stage or COP network it did not show); an object frames it (`fit_used: target`); a SOP frames it, and a SOP without the display flag is shown in the copy that renders (flags moved and put back, outside undo); a LOP, LOP network or ROP in a LOP network is a stage (`scene: stage`, `lop_path`); a Cop node or COP network is its own image through `rop_image` at its own resolution (`scene: cop`, `layer`; `quality`, `resolution` and `fit` ignored, a note); a ROP in `/out` lends its camera and, for `final`, its `samplesperpixel`. A camera or light as `target` is `invalid_argument`: pass it as `camera` (an OBJ camera, a LOP camera node, or a camera prim on the stage). `quality` chooses the backend (§8): `draft` the Flipbook ROP, `lit` the scene's lights, `final` Karma; `source: viewer` grabs the GUI Scene Viewer as the user sees it (draft only, never a stage or COP; `ui_required` headless). `chain` is the planned order of backends, `backend_used` the one that drew, `notes` say why an earlier one did not. `fit`: `all`, `selected` or `none` (reuse the last automatic framing); without `camera` an automatic camera frames the target, else everything (`camera_used: "temporary"`). A look leaves no nodes, undo step or dirty flag: headless, camera and ROP exist only in the child hython (§8); in the GUI they are created outside undo and deleted after the render. `on` runs it on another Houdini (§3.6). Registered `scene=False`, off the main thread; the bridge counts it as a read. |
| `houdini_python` | `code`, `timeout_s = 30`, `language: python\|hscript = python`, `undo_label?` | `exec` in a fresh namespace with `hou` bound, stdout/stderr captured, the value of a trailing expression or a `result` variable JSON-serialised (`repr` fallback). Runs on the main thread inside one undo group. Returns `{stdout, stderr, result}`. An uncaught exception (`sys.exit()` included) fails with `code: python_exception` (stdout, stderr, traceback in `detail`) and rolls the call back. A `sys.settrace` deadline stops Python code shortly before `timeout_s` (`houdini_busy`, `detail.started` and `stopped` true, rolled back), so a runaway loop cannot wedge Houdini. Output capped at the response budget with `truncated`. Disabled → `code: python_disabled`. Destructive. |
| `job` | `action: status\|result\|cancel\|list`, `job_id?`, `all = false` (1.3) | Jobs are host-side threads for render/pdg/long cook. `status: {state: running\|done\|failed\|cancelled, progress?, current?, total?, message?, started, elapsed_s}` (`progress` is 0..1, `current` of `total` steps; 1.0 once done). `result` returns the tool's normal result once done. A `pdg` cook job counts the work items of the whole graph and adds `nodes: {name: "finished/total"}` (1.2). 1.3: job ids are `<pid>-<id>` and the bridge routes `job` to that pid; `{action: list, all: true}` lists every live instance's jobs (§7). A cancelled `cook` or `render` job keeps its partial work in `detail.partial` (§4.6, `render`), next to `detail.last_status` with `state: cancelled`. 1.3 (review 20): a frame-by-frame job's `message` counts the frames done, as `current` does, and prints whole frames as integers (`frame 90`, not `90.0`); `cancel` adds `cancelled: true`, or `cancelled: false` and a note when the job had already finished (its `state` stays `done`, `failed` or `cancelled`). (2.0) On the 2.0 profiles `job_id` is the ledger's opaque id and reaches its Houdini after a bridge restart (§3.8); `on` picks the Houdini for `list`; progress also arrives as MCP progress notifications (§7) and through `inspect {what: "jobs"}` and the `houdini://jobs` subscription. |

### 4.7 State and contexts

| Tool | Args | Behaviour |
|---|---|---|
| `undo` | `action: undo\|redo\|history`, `steps = 1`, `include_user_steps = false` | `history` lists the last 20 undo labels (and `redo` labels), with `total` and `redo_total` counting them all (1.4, review 22 finding 9; `hip_open` and `hip_new` clear the history); `undo`/`redo` returns the labels `performed` plus `next_undo`, `next_redo`, `undo_count`, `redo_count`, `dirty`, `scene_generation`. They stop at the first step not labelled `HocusPocus:` (the user's or Houdini's) and name it in `blocked_by`; `include_user_steps` crosses such steps and lists them in `user_steps` (1.2). 1.4 (review 21 papercut 2): a call that failed and was rolled back stays on Houdini's redo stack, which cannot drop one entry; the host remembers the redo stack right after each rollback, `redo` stops before such an entry and names it in `skipped` with a note, and `history` leaves it out of `redo` and lists it under `rolled_back` (`next_redo` and `redo_count` skip it too). |
| `time` | `frame?`, `range?: [start, end]`, `fps?` | Omitting all fields reads. Sets with `hou.setFrame`, `hou.playbar.setFrameRange` (works headless), `hou.setFps`. 2.0 (parity G2, a mode): in a GUI session the Scene Viewer recooks the displayed nodes at the new frame on Houdini's next idle tick, outside the call (a displayed simulation steps there), and it cooks displayed nodes between calls, so `cook_state` can read `cooked` without a cook call; headless nothing cooks until asked. The first frame change and the first `node_info`/`inspect` `cook_state` of a GUI session each carry a note saying so (once per session; `hou.isUIAvailable()`). |
| `hda` *(full profile)* | `action: create\|save\|unlock\|match\|install\|reload\|list`, plus action-specific fields (`path`, `library_path`, `name`, `label` or `description`, `version`, `min_inputs`, `max_inputs`; `promote_spare_parms = true` for `save`; `limit`/`cursor` for `list`) | Thin wrappers over `createDigitalAsset`, `definition().updateFromNode`, `allowEditingOfContents`, `matchCurrentDefinition`, `hou.hda.installFile/reloadFile/loadedFiles`. `save` also copies the instance's spare parms into the definition's parm template group (`promote_spare_parms = true`, 1.2). `list` shows long paths, not 8.3 short names; `inspect what: type`/`search kind: types` report the definition's version, its label as `description` when there is no help, and types as `Sop/ns::name` (1.2). |
| `pdg` *(full)* | `action: cook\|status\|workitems\|cancel\|dirty`, `top_path`, `block = false`, `save = false`, `timeout_s = 30`, `attribs?`, `state?`, `limit`, `cursor` | `cookWorkItems(block=False)` as a job polled in short main-thread steps, with `progress`/`current`/`total` counting finished work items; `block` waits `min(timeout_s, job_threshold_s)` for the result, then returns `{job_id, state: "running"}` (§7); `status` from `getPDGNode()`; `workitems` paged with state and output files. A failed item carries `error` (its log's last error lines), `log_path` and `exit_code`; a cook result lists the first 5 `failures` of the graph (1.2). Out-of-process ROP TOPs load the saved hip, so `cook` refuses an untitled or dirty scene with `unsaved_changes`; `save: true` saves first (1.2). A cook whose items were cancelled ends `cancelled`, never `done`; `cancel` also cancels the job cooking the graph and returns the status after the cook stopped (1.2). `inspect what: node` on a TOP node adds `pdg_state: {cooked, failed, total}` (1.2). `workitems` takes `attribs: [names]` (per-item values) and a `state` filter, reports `cook_time_s`, and gives output files relative to one `output_root` (1.2). |
| `events` *(full)* | `since = 0`, `limit` | Host-side ring buffer of hip events and node events (`ChildCreated`, `NameChanged`, `ParmTupleChanged` on nodes the agent touched, `BeingDeleted`) with a monotonic sequence. For "what did the user change since my last call". 1.2: every event has `origin: agent\|other` (1.4, review 23 papercut 9: or `houdini` for a parm Houdini wrote itself inside a call that set parms explicitly, such as a camera's `*Converted` parms, a light's guide scale, `labelparm*` or a callback's writes; only the parms `parm_set` or `node_create` set are `agent` then, and a call that sets none, such as `houdini_python`, keeps every write `agent`) (agent = inside a HocusPocus call: the host holds a call's events and publishes them when its main-thread work ends, none if it was rolled back, without nodes created and deleted within it, and without changes made while undo is disabled, such as `render`'s output-parm set and restore); nodes read with `inspect what: node` or listed by `what: network` (`node_info`, `network_describe` in `compat_1x`) are watched too; nested nodes created in one batch get their `ChildCreated`; `FlagChanged` names the flags; 1.3 (review 16 papercut 9): `ParmTupleChanged` on a multi-component tuple names the `components` whose value or keys changed instead of a `count` (a burst within 0.1 s is one event with their union) and lists in `keyed` those of them with keyframes now, from a per-tuple snapshot taken when the node is watched; spare parm edits are one `SpareParmsChanged`; `hda create/match/unlock` are one `hda_contents_rebuilt`; the `pdg` tool records `kind: "pdg"` events (`cook_start`, `work_item_failed`, `cook_done`); Houdini's save-time writes on TOP networks (1.3: and on `/stage`) are dropped; 1.3 (review 18 papercut 10): one ramp edit is one `ParmTupleChanged` on the ramp parm, not one per key parm. 1.3 (review 19 papercut 8): seq restarts in every Houdini, so the bridge returns `next_since` as `<pid>:<seq>` and takes it back as `since` (a bare seq still works); a cursor from another Houdini is read from the start with `reset: true` and a `note`. The host keeps plain integers. |

Count (2.0): 2 session + 4 hip + 3 read and mutation (`inspect`, `search`, `edit`) + 2
conveniences (`node_create`, `parm_set`) + 5 execution (`cook`, `render`, `look`,
`houdini_python`, `job`) + 2 state (`undo`, `time`) = **18 in `core`**, plus 3 in `full`
(`hda`, `pdg`, `events`) = 21. `minimal` is 10 of the core tools (§4.1). `compat_1x` lists
the 35 tools of 1.4 (Appendix A). `usd_stage` and `selection` have no 2.0 tool of their own:
`inspect what: stage` and the `edit` `select` op replace them (a selection is read with
`houdini_python`).

### 4.8 Resources, prompts, instructions

**Resources** (user-attachable context; every resource is also a tool call, §3.10):

- `houdini://status`, `houdini://instances`, `houdini://jobs` (subscribable: `status`,
  `jobs`)
- `houdini://outline{?root,depth}`: the scene as a compact tree (`inspect what: outline`)
- `houdini://node/{path}{?include,parms,include_defaults}` (subscribable),
  `houdini://network/{path}{?depth,format}`,
  `houdini://geo/{path}{?frame,class,attribs,start,count,stats}`, `houdini://image/{path}`,
  `houdini://stage/{lop}{?prim,include,time,summary}`: `inspect` with that `what`
- `houdini://type/{category}/{name}{?parms,folder,detail}`,
  `houdini://types{?q,category,limit,cursor}`: `inspect what: type`, `search kind: types`
- `houdini://problems{?root}`, `houdini://events{?since,limit}` (subscribable)
- `hocuspocus://guide` — the operating manual: the instructions below, the resources and
  recipes (build and check with `edit`, two Houdinis with roles and `on`, Copernicus,
  Flipbook frames, spare parms, no dialogs in a GUI session); at most 8 KB, the 2.0 guide
  at most 6.5 KB (M4), unit tests enforce both (1.3, review 19 papercut 10: with the tool
  reference appended it was 52 KB)
- `hocuspocus://tools` — the tool reference rendered from the spec files for the bridge's
  profile (the text of `docs/tools.md`, every tool's `notes` and examples, and the
  resource templates)

**Prompts** (slash commands in Claude Code; spec-2.0 §2.8; the texts live in
`bridge/instructions.py` as `PROMPTS`):

| Prompt | Arguments | What it asks for |
|---|---|---|
| `inspect_scene` | `root = /obj` | `houdini_status`; when several Houdinis run and none is pinned, ask which or pin the GUI; read `houdini://outline` (or `inspect what: outline`), then `inspect what: problems`; summarise without modifying anything. |
| `build_sop_chain` | `description`, `parent?` | Plan the chain, build it in one `edit` with `$id` wiring and the display flag on the last node (a `dry_run` or `search kind: types` when unsure), fix errors the `nodes` rows show with one more `edit`, check `inspect what: geo`, end with `look` on the object. |
| `debug_red_node` | `path` | `inspect what: node` with errors, parms and inputs; upstream and `what: problems` when needed; the smallest fix in one `edit` only if unambiguous; a wrangle's missing `ch()` parms added with a `node` op's `spare_parms`. |
| `turntable_preview` | `path`, `frames = 48` | Display flag on (and say so), say what blocks the view, a null keyed 0→360 and a parented camera in one `edit`, never change the playbar range in a GUI session, `look` with `camera`, `frame` and the camera's resolution at two frames. |
| `cache_sim` | `path`, `range?` | (2.0) A File Cache after the sim (an `edit` create op) if there is none, `hip_save` an untitled hip first, `render` the File Cache with `wait_s: 0` and poll the job (`cook` never writes files), then `inspect what: geo` at the first, middle and last frame and `look` at the last. |
| `two_houdinis` | `rop` | (2.0) Find or launch a `worker`, save in the `editor`, `hip_open` on the worker, pin the editor again, `render {on: "worker", wait_s: 0}`, follow the job by id whatever is pinned; `instance_lost` never switches. |
| `lookdev_karma` | `path?` (a LOP) | (2.0) `inspect what: stage {summary: true}`, add a dome and a key light and MaterialX materials in one `edit` when missing, iterate with `look {quality: "lit"}`, finish with `look {quality: "final"}`, frames through a `usdrender_rop` job. |

`compat_1x` keeps the four 1.4 prompts (Appendix A).

**Server `instructions`** (≤ 400 words, shipped in `initialize`; the text lives in
`bridge/instructions.py`, a unit test enforces the cap, and `compat_1x` gets the 1.4 text):

> HocusPocus drives a live Houdini. Identity is Houdini paths. Start with
> `houdini_status`; if nothing is connected, `houdini_connect` can launch Houdini (GUI
> or headless hython) or attach to a running one by pid. With several Houdinis running,
> pin one with `houdini_connect {pid}` (or `{name}`, or `{role: "editor"}`): until then
> calls that change a scene refuse with `ambiguous_instance`, and if the pinned one
> exits calls return `instance_lost` instead of switching. `cook`, `render`, `look` and
> `job` take `on` (a pid, a name or a role such as `worker`) to run on another Houdini
> without moving the pin. Change the scene with `edit`: one call is one undo step, its
> ops run in order (`create`, `connect`, `set`, `node`, `delete`, `copy`, `layout`,
> `build`, `select`), and an op's `id` is `$id` in later ops' paths. `dry_run: true`
> validates every op and resolves paths without changing anything; a failing op rolls
> the whole call back. The result's `nodes` rows carry each touched node's errors and
> warnings. For one quick change `parm_set {items: [{path, value}]}` and `node_create
> {items: [...]}` remain. Tuple paths like `.../t` take lists, component paths like
> `.../tx` take scalars; expressions go in `expression`. Read with `inspect {what,
> target}` (`what`: node, parms, network, outline, geo, image, stage, problems, type,
> events, jobs) and find with `search {kind: "types"}` or `{kind: "nodes"}`. See the
> result with `look {target}`: `quality: "draft"` (a Flipbook ROP, headless too) for
> checks, `lit` with the scene's lights, `final` for Karma. Long cooks and renders
> return a `job_id`; poll it with `job`. When no tool fits, `houdini_python` runs `hou`
> code. Results are compact: non-default parms only, lists paged with `cursor`;
> `truncated: true` means the response budget cut a list. Errors carry `code`, `hint`
> and `candidates`; read them and adjust. `delivery_unknown` means the call may or may
> not have run: inspect state before repeating it. `_meta.scene_generation` changes when
> the scene is cleared or loaded. Hip tools refuse to discard unsaved work unless told
> to. A Houdini started with `houdini_connect {launch}` usually closes when this server
> exits (`launched.outlives_server` says): `hip_save` before the session ends, or attach
> by pid to one started with `hocuspocus launch`. `inspect {what: "type"}` is large for
> FX types: pass `parms` globs, or `detail: "folders"` first. Add spare parms with an
> `edit` `node` op's `spare_parms` (recipe in `hocuspocus://guide`). The resource
> `houdini://outline` is the whole scene as a compact tree; `hocuspocus://tools` is the
> full tool reference.

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
  role, version, GUI or headless), which hip (`path`, `name`, `dirty` and why, `is_new`),
  `$HIP`, `$JOB`, `$HIPNAME`, frame, fps, range, recent files, scene generation, and the
  Houdinis that ran recently and exited.
- **Open, save, save-as, increment, backup, merge** with the exact semantics of
  `hou.hipFile`, plus safety: nothing discards unsaved work without `on_unsaved:
  discard`, and "unsaved" means the same in the GUI and headless (§3.2). `save` with an
  untitled scene and no path fails with a hint.
- **Pick or start a Houdini.** `houdini_connect` lists, attaches, launches (GUI with a
  hip, or headless hython for batch work) and pins by pid, name or role. A headless
  `worker` is a first-class target for renders, cooks and looks (`on: "worker"`) while
  the user keeps working in the `editor`.
- **Survive restarts.** The bridge never dies with Houdini. Calls during the gap return
  `houdini_offline`. The scene generation tells the agent its cached paths may be stale.
  A bridge restart keeps roles, the exited instances and the jobs in the ledger (§3.8).
- **Paths are never redacted.** Save returns the real path. Status returns the real
  path. If `approved_roots` is set, the error says which roots are allowed.

---

## 7. Long operations: jobs

Cooks, renders, PDG graphs and sims can exceed any sane synchronous timeout. Rule:
synchronous up to `job_threshold_s` (10 s), then the call returns `{job_id, state:
"running"}` and the agent uses `job`. Jobs run on host-side threads **but call `hou`
only through the executor**, so they still respect the main-thread rule; a job is a
sequence of short main-thread steps (e.g. per-frame render) with progress between them
(1.4: a single-file ROP renders its range in one main-thread call, §4.6 `render`).
Progress notifications are emitted by the bridge when the client supplied a
`progressToken`: the host files every job under the `request_id` of the `/hp/v1/call`
that started it, and while that call is in flight the bridge polls
`/hp/v1/calls/{request_id}/jobs` (for `job` with a `job_id`, `/hp/v1/jobs/{id}`) every
0.5 s and sends `notifications/progress` from the newest snapshot: `progress`/`total`
from the job's `current`/`total` steps (else its 0..1 `progress` over `total: 1`) and its
`message`, only when `progress` increases. Polling is best effort and never fails the
call. Jobs are not durable across a Houdini restart; `job status` after a Jobs are not durable across a Houdini restart (a job runs in its Houdini's
process); the ledger keeps their last status and stored results (§3.8), so after a restart
`job status` answers `instance_lost` with that status, and a ledger id the ledger never had
is `job_not_found`.

**Jobs and several instances** (1.3, review 19 papercut 3; 2.0). A job belongs to the
Houdini that runs it, and `job` reaches that Houdini whatever is selected or pinned. On the
2.0 profiles job ids are the ledger's opaque ids (`j` and five hex digits, §3.8) and `on`
starts a cook or render on another Houdini (§3.6); the host's own id is `<pid>-<id>` (a bare
`<id>` still finds a job of that process), which `compat_1x` returns and every profile
accepts. When the job's Houdini has exited the answer is `instance_lost` with the last
status in `detail.last_status`, also after a bridge restart. `job {action: list}` lists
the selected Houdini's jobs (or `on`'s); `{action: list, all: true}` asks every live
instance and adds `pid` to each row and `instances: [{pid, label, jobs, running}]`. A host
asked for another pid's job answers `job_not_found` naming both pids.

---

## 8. Visual feedback

The agent must be able to **see**. (2.0, D38) `look` is the one picture tool: it returns
an image in the MCP result, never only a path, and chooses the renderer from what the
question needs. `render` covers writing frames to disk (any ROP, as jobs with a thumbnail).
Images are PNG, downscaled to ≤ 1024 px on the long side, and also written to
`<state_dir>/captures/` with the path returned. Image bytes count toward the client's
output limit, so one image per call.

**The quality policy** (`host/look/select.py`):

| Request | Backend chain | GUI | Headless |
|---|---|---|---|
| a Cop node or COP network (any quality) | `rop_image` | a temporary `rop_image` in the live COP network (about 0.2 s, outside undo and `events`) | the same, in the host |
| `source: viewer` | `viewer` | the Scene Viewer's flipbook of one frame, as the user sees it (HUD included; `context` is the viewer's network, a note when it is not the scene's); a `camera` or an explicit `fit` changes the view only for the grab, and the view is put back | `ui_required` |
| `draft` | `flipbook` → `opengl` (the types this Houdini has), then `karma` after a crash, headless only | in-process (about 0.3 s); a ROP that writes no image hands over to the next; no Karma step (a crash there would take Houdini down) | a snapshot rendered in the kept child hython (below); a crashed child hands over to the next ROP, Karma at 2 samples last |
| `lit`, scene has lights | as `draft`, the Flipbook ROP's Lighting at "High Quality Lighting with Shadows" | as `draft` | as `draft` |
| `lit`, no lights | `karma` at 2 samples with its default light, a note | Karma in the host, the live scene | the same |
| `final` | `karma` at the target ROP's `samplesperpixel`, else 32 (`samples` in the result) | Karma in the host; seconds, not a draft | the same |

A stage is never sent to the viewer. The spec's `lit` and `final` render the live scene;
only the viewport ROPs (Flipbook, OpenGL) render a headless snapshot. The OpenGL ROP backend
is removed once Houdini 22.5 is the floor.

**Captures go through the Flipbook ROP** (1.4). Houdini 22 deprecates the OpenGL ROP
(`Driver/opengl`, `deprecationInfo()`: "Replaced by the Flipbook ROP.", 22.0) for the
Flipbook ROP (`Driver/flipbook`), which has the same `picture`, `trange`, `tres`/`res1`/
`res2`, `camera` and LOP-source parms (`opsource`, `loppath`, `cameraprim`) plus its own
lighting and quality parms. After a stage look's child crashed, later stage looks skip
that ROP in this process. The temporary ROPs are HocusPocus's own: no deprecation note is
added for a temporary OpenGL ROP (an `edit` create of `Driver/opengl` keeps its note).

**Headless viewport renders run in a child hython.** Verified on 22.0.466: in hython the
second `RopNode.render()` of any OpenGL ROP in one process segfaults in the Vulkan
viewport renderer, whatever the node, frame or output; one multi-frame `render()` is
fine. The Flipbook ROP renders the same ROP again in-process (other frames, cameras,
resolutions and geometry; review 16's city stage three times), but once a Flipbook ROP that
has rendered is deleted (`destroy()`, or `hipFile.clear()`), the next Flipbook render in that
hython segfaults at the same place (`RV_ShaderVariableSet::create`). A look's temporary
ROP is always deleted, and users delete theirs, so headless, `look` and
`render` of Flipbook and OpenGL ROPs snapshot the scene (`saveChildrenToFile` per manager:
no hip save, no event side effects) and render it in a short-lived child `hython` (about
3 s per call). In the GUI both render in-process (a temporary Flipbook ROP created,
rendered and deleted four times, OBJ and stage, then again after `hipFile.clear()`, ran
in houdinifx 22.0.466; a GUI capture takes about 0.3 s); every other ROP type renders
in-process frame by frame through the executor.

**Headless captures keep their Flipbook child** (1.4, review 22 finding 6: a fresh child
per capture took 2.9-3.7 s, 69 % of a soak's tool time). The first headless Flipbook
capture starts a child hython that stays up; each later capture pushes a fresh snapshot to
it over stdin, and the child deletes every node of its previous scene except its own
Flipbook ROP (never `hipFile.clear()`), loads the snapshot, builds the capture camera and
renders that same ROP again, which the Flipbook ROP survives (verified on 22.0.466: /obj
and stage scenes alternated eight times in one hython, 0.15-0.19 s per render after the
first). Measured through the tools on a rubber toy at 640x480: 2.8-3.6 s per capture before,
3.3 s for the first and 0.35-0.4 s (0.9 s for a stage) for each later one after. The kept
child is replaced when the child script, the hython or an installed HDA library (its mtime)
changes, when it exited, after 200 captures, or after 110 s idle; it exits by itself after
120 s idle (it holds a licence) or when the host goes away (stdin EOF). A capture while it
is busy, an OpenGL or Karma step of the chain, and `render` of a user's ROP still use a
fresh child. A crash of a kept child that had already rendered retries that capture in a
fresh child with a note, and later captures in that Houdini use fresh children; a crash of
a new kept child is a crash as before (§8 chain). There is no setting for it: the module
constant `hocuspocus.host.tools.visual.WARM_CAPTURES = False`, set inside the host process,
sends every capture to a fresh child, and `close_warm_capture()` stops the kept one (the
integration tests do that before timing a cold capture).

**An OpenGL ROP child that renders a stage runs single-threaded** (`HOUDINI_MAXTHREADS=1`,
review 16 N1): its LOP source creates the Vulkan device on a TBB worker and crashes for a
stage of more than a few thousand polygons. The Flipbook ROP does not (review 16's city
stage rendered multi-threaded in 5 of 5 fresh hythons), so its children keep every thread.

**`host/look/`** (2.0, spec-2.0 §4). The capture and render backends are one package:
`viewer.py`, `flipbook.py` (with the kept child above), `opengl.py`, `karma.py` and
`cop.py` (`rop_image`), each a `Backend` with `can_run(spec, env)` and `render(spec,
ctx)`; `select.py` is the policy, `run.py` the orchestration (one main-thread step in the
GUI; headless a short main-thread prepare, then the chain off the main thread), `child.py`
the snapshot and child hython. `render` of a Flipbook or OpenGL ROP headless uses
`child.ChildRender`; `compat_1x`'s `viewport_capture` runs the same backends with its 1.4
policy (Appendix A). The settings named above stay settable on
`hocuspocus.host.tools.visual`, which forwards them to the look module that owns them.
What a headless snapshot carries is the contract in `host/look/base.py` and `look`'s notes:
every node (`saveChildrenToFile` per manager, which also carries the definitions of
`Embedded` assets: the child renders them), the asset libraries outside `$HFS`,
`$HIP`/`$JOB`, global variables and `hou.session`; not the current take (a note says so),
in-memory simulation caches (the child re-simulates to the frame; a note names every DOP
network that stands past its start frame) or variables set with `hou.putenv` (parity G8). The temporary nodes a GUI look makes set only Houdini's own flag,
inside the call, which the dirty flag of §3.2 ignores: a look never dirties the scene.

---

## 9. Error model

Every tool failure is an `isError: true` result:

```json
{"code": "parm_not_found", "message": "No parm 'size' on /obj/geo1/box1.",
 "hint": "size is a tuple; use the tuple path to set all components or sizex/sizey/sizez.",
 "candidates": ["sizex", "sizey", "sizez", "scale"], "hou_exception": null}
```

A `hint` or `message` that names a tool names one the call's profile serves (2.0, review
25 papercut 1): every such text is built with `tools/migration.py` `hint_tool(name)`, which
renders the 2.0 call on the 2.0 profiles (`search {kind: "nodes", root}`,
`inspect {what: "type", target}`, `search {kind: "types", query}`,
`inspect {what: "problems"}`, `look`, an `edit` `set` or `create` op) and keeps the 1.4
name on `compat_1x`, and leaves out a clause whose tool the profile lacks (`cook` on
`minimal`). The host reads the profile from the request envelope (the bridge's), else its
own. `tests/unit/test_hint_profiles.py` checks a fixture of errors in every profile.

Stable codes (the complete set; adding one is a design change):

| code | when | retryable |
| `houdini_offline` | no live instance; names the pid (and hip) the bridge was driving if it exited, and says its unsaved changes are lost | after connect (`retryable: false` when nothing is running) |
| `ambiguous_instance` | several live instances, none pinned, and the call changes a scene (1.3, §3.3 rule 3); `candidates` as for `instance_lost`, `hint` names the `houdini_connect {"pid": …}` call for each | no; after `houdini_connect {pid}` |
| `instance_lost` | the pinned Houdini exited (1.3), or the one an `on` or a job id names (2.0, §3.6, §3.8); names its pid and label, `candidates` are the live instances as `{pid, label, ui, hip}`; the bridge does not switch on its own (§3.6) | no; after an explicit `houdini_connect` |
| `houdini_busy` | main-thread timeout | yes |
| `delivery_unknown` | request sent, response lost (becomes `houdini_offline` "exited while running <tool>" when the process is gone within 1.5 s) | inspect first |
| `version_mismatch` | host `hp/vN` ≠ bridge | after reinstall |
| `invalid_argument` | schema / shape; 1.4 (review 21 papercut 1): a batch tool given one flat item (`parm_set {path, value}`) gets the corrected call as `hint`, its own fields wrapped in `items`; 2.0: an `inspect`/`search` option its `what`/`kind` does not take (naming those it does), a `$id` no earlier op produced, a 1.4 tool the profile does not serve (its replacement in `hint`, §3.2); 2.0 (review 25 papercut 2): a 1.4 path argument on `inspect` (`path`, `node_path`, `root`, `lop_path`, `type`, `rop_path`, `cop_path`; `paths` as one string, or on a `what` that takes one path) says it is `target` now, before any edit-distance guess, and `hint` is the corrected call (`bridge/validate.py` `ARG_RENAMES`) | no |
| `node_not_found` | path; 1.4 (review 21 papercut 4, review 22 finding 8): `candidates` are near-miss children of the missing node's parent (never the node being wired), the hint names `search {kind: "nodes"}` on that parent or on the nearest existing ancestor, and a missing wiring source prefixes a batch error with its own path; a render ROP whose `camera` parm names a missing node (§4.6 `render`) | no |
| `parm_not_found` | parm/tuple | no |
| `node_type_not_found` | type (with candidates) | no |
| `invalid_input` | wiring index/name (with labels) | no |
| `invalid_value` | type/range/menu mismatch | no |
| `name_collision` | create/rename/`build` | no |
| `locked` | locked HDA / permission | after unlock |
| `cook_failed` | cook raised; errors attached | after fix |
| `unsaved_changes` | hip_new/open without consent | with `on_unsaved` |
| `file_not_found` | hip/hda/merge path | no |
| `path_not_allowed` | `approved_roots` | no |
| `ui_required` | a GUI-only argument form headless (`look {source: "viewer"}`) | no |
| `python_disabled` / `read_only` | config | no |
| `job_not_found` | job id; 1.4 (review 21 papercut 3): also a `<pid>-<id>` whose pid this bridge never knew (never live in the registry, no job of it seen, no launch record), which 1.3 reported as `instance_lost` for a Houdini that had never run; 2.0: a ledger id the bridge ledger does not have | no |
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
    spec/                      # one module per tool exporting SPEC, and ORDER (§3.5)
    catalog.py                 # loads the specs; profile membership
    profiles.py                # the profile names (minimal, core, full, compat_1x)
    migration.py               # removed 1.4 tool -> its 2.0 replacement
    errors.py                  # error codes + ToolError
    docs.py                    # renders docs/tools.md and docs/redesign/budget.md; example validator
    paths.py                   # state dir (instances/, logs/, captures/, jobs/, ledger.sqlite)
    budget.py                  # the response truncator (host and bridge)
  host/                        # INSIDE Houdini. stdlib only. `import hou` lazily.
    __init__.py                # start(), stop(), status(), autostart()
    __main__.py                # hython -m hocuspocus.host
    config.py executor.py server.py dispatch.py runtime.py registry.py jobs.py undo.py
    tx.py                      # the transaction engine every mutation runs on (§3.9)
    resources.py               # the hp/v2 resource templates and etags (§3.10)
    look/                      # look's backends, policy and snapshot (§8)
    tools/ registry.py _diag.py session.py hip.py code.py nodes.py network.py parms.py
           cook.py types.py geo.py visual.py state.py hda.py usd.py pdg.py events.py
           inspect.py search.py edit.py look.py
  bridge/                      # OUTSIDE Houdini. mcp SDK.
    __main__.py server.py client.py instances.py launch.py local_tools.py
    validate.py budget.py config.py instructions.py
    ledger.py                  # the SQLite ledger (§3.8)
    routing.py                 # on and roles (§3.6)
    resources.py               # resources, etags, subscriptions (§3.10)
houdini/                       # Houdini package payload; NOT the repo root
  hocuspocus.json.template     # -> <prefs>/packages/hocuspocus.json
  scripts/python/uiready.py    # GUI autostart (verified location for Houdini 22)
  toolbar/hocuspocus.shelf     # HP Status / HP Start / HP Stop
tests/
  conftest.py  unit/  integration/ (with its own conftest.py)  e2e/  workloads/
docs/
  BIBLE.md  quickstart.md  tools.md (generated)  CONTRIBUTING.md  parity.md  migration-2.0.md
  redesign/README.md  redesign/progress.md  redesign/spec-2.0.md  redesign/budget.md (generated)
  redesign/review/*.md  redesign/evidence/
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
| `tests/unit` | system Python | catalogue integrity (every spec has an impl, schema, annotations, ≤ 60-word description, ≤ 12-word argument descriptions, passing examples; `tools/list` within the §4.1 caps per profile and mode; `compat_1x` byte-identical to the 1.4 goldens), bridge instance selection, routing and ledger with a fake host, resources and etags, offline behaviour, error mapping, budget truncation, config parsing, the guide size, `cli` path resolution | < 10 s |
| `tests/integration` | `hython -m pytest` | in-process host: one `hou` session per run, `hipFile.clear()` per test, every tool exercised against real nodes; the idioms in §5 each have a test; the transaction engine, `inspect`/`search` byte identity with the 1.4 reads (`detail: full`) and their compact projections, the look backends | fast (default) < 90 s; `slow` about 3 min |
| `tests/e2e` | system Python spawning hython | official `mcp` client → `hocuspocus-mcp` stdio → `hython -m hocuspocus.host` on an ephemeral port with an isolated `HOUDINI_USER_PREF_DIR` and a neutral cwd: a stdio round trip, review 06 tasks 2, 3, 4, 6 and 9 as one scripted scenario, a bridge launch that checks the work dir, two Houdinis | < 60 s |
| `tests/workloads` (2.0) | system Python spawning hython (`--runworkloads`) | the evaluation workloads as scripts, each against its budget (below) | about 1 min; budget 12 min |
| `tests/integration/test_parity_gui.py` (2.0, `gui`, `--rungui`) | system Python launching `houdinifx` with isolated prefs | the GUI column of the parity matrix (below) | about 30 s |
| GUI (manual) | checklist | package loads in `houdinifx`, autostart, viewer look; run before a release and logged in `docs/redesign/progress.md` | — |

**The workloads tier** (2.0, spec-2.0 §5.2, D42). `tests/workloads/` scripts the
evaluations that measured 1.x: the city build (review 12), the scorecard twelve (review
21), a 200-call soak (review 22), the FX cache (review 20) and the Vellum-to-USD round trip
(review 24). One headless host and one official `mcp` client session to the stdio bridge
serve all five. A `Recorder` wraps `call_tool` and records per call the tool, argument
bytes, text bytes (the JSON the model reads; images counted apart), time and `isError`;
per workload the calls, text bytes, largest call, wall time and time to the first image.
`tests/workloads/budgets.json` holds `calls`, `text_bytes`, `max_call_bytes` and `wall_s`
per workload, recorded from 1.4 (city build 21 calls and 20.8 KB; scorecard twelve 49
calls and 28.2 KB; soak 200 calls and 100.4 KB; FX cache 13 calls; Vellum USD 14 calls). A
workload fails when any total is more than 15 % over its budget, or on any error it did not
expect. A change that raises bytes or calls per workload says why in its commit (principle
13) and records the new budget with `--update-budgets`. The tier runs on the Houdini
runner nightly and before every tag; M4's exit is every workload below its 1.4 budget by
the margins the reviews predicted.

**The parity matrix** (2.0, spec-2.0 §5.3, D43). [`docs/parity.md`](parity.md) lists every
tool and resource × (GUI, headless) as **same**, **mode** (a deliberate, documented
difference) or **gap**, with the code that makes it so. M3 closed the gaps, each with
its status in the matrix: G1 (a read dirtied the GUI hip) is the one dirty source of
§3.2; G2 (the GUI viewport cooks between calls) a once-per-session note (§4.7 `time`);
G3 (a selection moves the user's panes) `context_changed` on `edit` `select` (§4.5); G4
(`cook {frame_range}` walks the playbar) a restore only when the user did not move it
(§4.6); G5 (modal dialogs block the GUI) guidance for the guide; G6 (no whole tool is
GUI-only) §3.6; G7 (a stale GUI package) the `version_mismatch` warning (§4.2); G8
(headless looks render a snapshot) §8's contract and its notes.
`tests/integration/test_parity_gui.py` executes the GUI column in a scripted `houdinifx`
session; the headless column is the integration tier (with
`tests/integration/test_parity_headless.py` for G8).

Hygiene rules: never write into the repo at test time; never use port 37219; isolated
pref dir per run; clean interpreter exit. CI: GitHub Actions `windows-latest` and
`ubuntu-latest` run `ruff check`, `ruff format --check`, the unit tier and a
`docs/tools.md` freshness check (`ci.yml`); a self-hosted Windows runner labelled
`houdini` runs integration (the fast set, then `-m slow`) + e2e nightly, on manual dispatch and on PRs labelled
`houdini` (`houdini.yml`). The workloads tier is a step of `houdini.yml`, and its measurements are
uploaded as an artifact (`tests/workloads/last_run.json`).

---

## 12. Documentation set

`README.md` (what, 3-command install, a first session with `edit`, `inspect` and `look`,
profiles, link to docs), `docs/quickstart.md` (5 minutes to a box on a mountain and a
picture), `docs/tools.md` (generated from the spec files with notes and examples),
`docs/BIBLE.md` (this), `docs/migration-2.0.md` (1.4 → 2.0: every removed tool and its
replacement, profiles, job ids, dirty semantics), `docs/parity.md` (the GUI/headless
matrix), `docs/CONTRIBUTING.md` (layout, tests, how to add a tool: spec file + host impl +
integration test + regenerate docs and the budget report, release steps), `CHANGELOG.md`.
`docs/redesign/` holds the historical review and evaluation record and the planning specs
(`spec-2.0.md`, the 1.x plans), indexed by its `README.md`, plus the generated
`budget.md`. Everything else in `docs/` from 0.9 is archived with the `v0.9-archive` tag.

---

## 13. Migration and the cut

**1.4 → 2.0** (spec-2.0 §8; the user's version is
[`docs/migration-2.0.md`](migration-2.0.md)):

1. The default profiles (`minimal`, `core`, `full`) serve the 2.0 surface. The 18 1.4
   tools without a 2.0 profile (Appendix A) answer `invalid_argument` there, with the
   replacement in the hint (`tools/migration.py`).
2. `profile = "compat_1x"` serves the 1.4 catalogue (35 tools, 1.4 schemas, results,
   prompts, instructions and resources) on the 2.0 engines, so a 1.4 client script runs
   unchanged (M3 exit). It is served for the 2.0.x releases; 2.1 removes it, together with
   the `v2` profile alias and, once Houdini 22.5 is the floor, the OpenGL ROP backend.
3. Job ids are opaque ledger ids on the 2.0 profiles; `<pid>-<id>` ids are still accepted
   everywhere. `events` cursors (`next_since`, `<pid>:<seq>`) are unchanged.
4. The call protocol stays `hp/v1` (§3.4): a 1.4 bridge and a 2.0 host still talk.
5. Scenes are ordinary Houdini scenes; nothing in a hip changes. `hocuspocus:tag`
   userData (`build`'s `tag`) is unchanged.
6. Version is **2.0.0**, tagged `v2.0.0` at the end of M4; `CHANGELOG.md` lists the
   contract changes and links the migration doc.

**0.9 → 1.0** (history). `master` was tagged `v0.9-archive` (HocusScript, documents,
source workspace, production qualification and all 0.9 docs live on there); 1.0 was built
on `redesign/v1` and the old tree deleted once the integration tier was green. Scenes
authored with 0.9 keep working; `hpmcp.*` userData left by 0.9 is inert. The 0.9
compatibility policy is void since 1.0.

---

## 14. Implementation roadmap

2.0 (spec-2.0 §7). Each milestone ends with its tiers green and a line in
`docs/redesign/progress.md`. Work is parallel within a milestone where files do not
overlap.

| # | Milestone | Contents | Exit | State |
|---|---|---|---|---|
| M0 | Foundation | Spec files + generated catalogue and budget report; workloads tier with 1.4 budgets recorded; parity matrix doc and GUI column | All tiers green; workloads tier runs on 1.4 and records budgets | done |
| M1 | Transaction and reads | `host/tx.py` and `edit`; `inspect`, `search`; 1.4 mutation tools reimplemented on the engine; a `v2` profile with the new names alongside the old | Scorecard twelve pass through `edit`/`inspect` only; bytes and calls ≤ 1.4 budgets | done |
| M2 | Resources, look, ledger | Resource templates with ETags and subscriptions; `look` with backends; bridge ledger, roles, `on`, ledger job ids and progress | Workloads pass with resources enabled; two-instance tasks via roles | done |
| M3 | Cut-over | Default profiles switch to the 2.0 names; `compat_1x`; parity gap fixes; docs, guide, prompts, this bible | A 1.4 client script runs unchanged under `compat_1x` | in progress |
| M4 | Evaluate and ship | Fresh-agent scorecard and all workloads on 2.0; fix pass; tag `v2.0.0` | Scorecard ≥ 1.4's; every workload uses fewer calls and fewer bytes than 1.4; the predicted margins are 2.1 targets where unmet (spec-2.0 §7) | — |

The 1.0 roadmap (M0 Foundations to M5 Hardening, 2026-10-12) and the 1.1 to 1.4 plans
are in `docs/redesign/` and `progress.md`.

---

## 15. Decision log

D1 to D34 are carried over from 1.x unchanged; their section references are to the 1.4
bible (tag `v1.4.0`). D35 to D44 are the 2.0 decisions.

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
- **D32** (1.4) `render` renders a ROP whose output is one file for the whole range (USD, Alembic, a path without `$F`) in one `rop.render()` call and verifies it by reading the file back: fewer time samples (or a shorter archive range) than frames asked is `cook_failed`; outputs are listed once, with a USD export's `layers` (§4.7, §7). *In review 23 a 48-frame `usd_rop` render, one call per frame, overwrote its layer each time, kept frame 48's sample and reported 48 outputs and `done`; only a read-back can tell a frozen export from an animated one.*
- **D33** (1.4) Headless Flipbook captures reuse one kept child hython, keyed on the hython, the child script and the installed HDA libraries' mtimes, replaced after 200 captures or 110 s idle and gone after 120 s idle; a crash of a kept child falls back to fresh children for the session (§8). *Fresh children cost 2.9-3.7 s per capture, 69 % of review 22's tool time; the Flipbook ROP survives re-rendering the same ROP in one hython, so a kept child that never deletes it renders a later capture in about 0.4 s.*
- **D34** (1.4) When the bridge trims a page to the budget it rewrites the cursor to resume after the last row kept (`events` `next_since` `<pid>:<seq>` with `more: true`, `after:<path>`, `after:<name>`, integer offsets), and a page whose cursor it cannot rewrite is sent whole with `over_budget: true` (§4.1). *In review 22 a trimmed `events` page kept the host's cursor, the last seq scanned, so a client following it silently skipped every dropped event; a budget cut must never lose rows.*
- **D35** (2.0) One transaction tool, `edit`, for every scene change; `node_create` and `parm_set` stay as conveniences and every mutation, 1.4 tools included, runs on one engine (§3.9, §4.5). *A build was a chain of per-noun calls, each a round trip, an undo step and an echo; one engine gives one undo policy, one rollback and one echo.*
- **D36** (2.0) Reads are resources with ETags and subscriptions, and `inspect`/`search` return the same bytes for clients that never read resources (§3.10, §4.4). *Eleven read schemas cost `tools/list` bytes on every session; an etag lets a client skip unchanged reads.*
- **D37** (2.0) A bridge ledger (SQLite) remembers instances with names and roles, jobs with opaque ids and launches across bridge restarts; the registry stays the authority on what is live (§3.8). *Jobs and exited Houdinis were forgotten on every bridge restart, and pid-tagged ids leaked the routing into the agent's vocabulary.*
- **D38** (2.0) One picture tool, `look`, chooses the backend from `quality` (draft, lit, final) and `target`; `viewport_capture` stays only in `compat_1x` (§8). *Four capture sources behind one argument made the agent pick a renderer instead of asking a question.*
- **D39** (2.0) `compat_1x` serves the 1.4 catalogue on the 2.0 engines for one minor release (2.0.x); 2.1 removes it (§13). *1.x client scripts keep running through the cut-over without keeping two engines.*
- **D40** (2.0) The default profile is `core` with 18 tools; `minimal` is 10 and `full` 21 (§4.1). *The 1.4 default listed 31 tools for the work the 2.0 core does with 18.*
- **D41** (2.0) The catalogue is one spec module per tool; `docs/tools.md`, `hocuspocus://tools` and the budget report are generated from it (§3.5). *Hand-kept copies drifted; one object per tool makes the docs and the budget a build step.*
- **D42** (2.0) The evaluation workloads are a test tier with recorded budgets, failing on a 15 % regression (§11). *Every review measured calls and bytes per task by hand once per release; a regression is now a red build.*
- **D43** (2.0) GUI/headless behaviour is a documented matrix with a tested GUI column; a gap is resolved as same or as a documented mode (§11, `docs/parity.md`). *Differences such as a read dirtying the GUI hip were found by accident.*
- **D44** (2.0) Budget policy: the 2.0 `full` profile's `tools/list` is capped at 24,000 B (`text`) and 34,000 B (`both`); `compat_1x` keeps the 1.4 caps of 32,000 B and 44,000 B (§4.1). *The 2.0 surface fits in less, and a cap set at the new size keeps it there; the 1.4 catalogue cannot shrink without breaking the scripts it exists for.*

### Verified deviations (M5 reconciliation, 1.0; still true)

Facts found while implementing, now reflected above:

- GUI autostart lives at `houdini/scripts/python/uiready.py` (§10.1).
- `hasUnsavedChanges()` is always `True` in hython; the host tracks dirtiness headless (§3.2).
- A second OpenGL ROP render in one hython segfaults, and so does a Flipbook ROP render after a Flipbook ROP that rendered was deleted; headless, both render in a child hython (§8).
- `undo`, `time`, `selection`, `hda`, `cook`, `pdg`, `render`, `job`, `viewport_capture` register with `scene=False` (§4.1).
- One `hocuspocus.toml` configures host and bridge; `HOCUSPOCUS_*` env wins (§3.7).
- `setChildrenFromData` skips unknown types and parms silently, defaults `clear_content=True`, and puts inputs without `to_index` on input 0 (§5.16).
- `hou.setFps` rescales the frame range unless told not to (§5.17).
- (1.x) The surface was 35 tools, 31 in `core` (Appendix A, D4).
- All cursors, including `geo_read.next_cursor`, are opaque strings (§4.1).
- (2.0) No `/hp/v2/call` or `/hp/v2/jobs` route was needed: the call shape did not change and the bridge polls progress (§3.4, §7).
- (2.0) The surface is 18 tools in `core`, 21 in `full`, 10 in `minimal`, and the 35 1.4 tools in `compat_1x` (§4.7, D40).

---

### Known limitation: launch lifetime

A Houdini started by `houdini_connect {launch}` is launched detached (new process group, and breakaway from the job object where Windows allows it), but in the verified setup (review 08) it still exited when the bridge that launched it exited. Treat it as owned by the bridge: it ends when the MCP client stops the bridge (end of a session, or a one-shot script exiting), and its unsaved work is lost. This is acceptable for interactive sessions; agents should `hip_save` before a session ends, or attach to a Houdini the user started. Since 1.1 `hocuspocus launch` is that "start it yourself" path from a terminal or script.

Since 1.0.1 this is visible rather than discovered: `houdini_connect {launch}` returns `launched.outlives_server` (false when the child shares the bridge's kill-on-close job object, i.e. breakaway was refused; the bridge cannot see a client that kills its whole process tree, so true means "should"); the launcher sets `HOCUSPOCUS_LAUNCHED_BY=<bridge pid>`, the host writes it into its registry entry as `launched_by`, and `houdini_status.instances[]` shows it; the bridge also records each launch in `<state_dir>/launches/<pid>.json`, so a later bridge that finds no live instance answers `houdini_offline` naming the dead Houdini and the server that launched it, with the keep-a-session-open / attach-by-pid hint. No new process-isolation mechanism was added.

## 16. Non-goals for 2.0

HocusScript or any custom language; APEX graphs; multi-user or remote (non-loopback)
access (the ledger's `role` prepares for remote workers, 2.0 does not ship them);
Streamable-HTTP direct-to-Houdini transport; a Houdini UI beyond a status shelf tool;
vendoring the MCP SDK into Houdini; supporting Houdini 21 or earlier. Linux and macOS:
the code must not be Windows-only and path handling is guarded by unit tests with fakes,
but 2.0 is qualified on Windows.

---

## Appendix A. 1.x surface (`compat_1x`)

The `compat_1x` profile (D39) serves the 1.4 `full` catalogue: 35 tools with their 1.4
schemas, annotations and results, run on the 2.0 engines (the mutations as transaction
plans, §3.9; `viewport_capture` on the look backends, §8). It is served for the 2.0.x
releases and removed in 2.1. [`docs/migration-2.0.md`](migration-2.0.md) maps every tool
below to its 2.0 replacement with a before/after example. This appendix keeps the 1.4
contract of the tools 2.0 does not list, because the 2.0 tools reference it: `inspect`
returns these reads' results byte for byte, and `edit`'s ops take these tools' fields.
The 1.4 bible is at git tag `v1.4.0`.

**Profiles (1.3/1.4).** `minimal ⊂ core ⊂ full`: `core` 31 tools, `full` 35 (adds `hda`,
`usd_stage`, `pdg`, `events`), `minimal` 14 (`houdini_status`, `houdini_connect`,
`hip_open`, `hip_save`, `node_find`, `node_info`, `node_create`, `node_connect`,
`parm_get`, `parm_set`, `cook`, `geo_info`, `viewport_capture`, `houdini_python`).
`tools/list` at 1.4.0: 14.4/27.4/30.8 KB in `text` and 20.6/37.0/40.4 KB in `both`
(minimal/core/full); `compat_1x` is 1.4's `full`. Annotations: `node_delete`, `hip_new`,
`hip_open`, `houdini_python` destructive; `parm_set`, `node_connect`, `node_edit`, `time`,
`selection`, `cook`, `job`, `viewport_capture` idempotent. `scene=False`: `undo`, `time`,
`selection`, `hda`, `cook`, `pdg`, `render`, `job`, `viewport_capture`. Job ids are the
host's `<pid>-<id>`, routed by pid (D26).

### A.1 Nodes, networks, parms, geometry, types (1.4)

| Tool | 2.0 replacement | Args | Behaviour |
|---|---|---|---|
| `node_find` | `search kind: nodes` | `root = "/"`, `pattern = "*"` (glob on name, `hou.Node.glob` semantics), `type?` (glob), `category?` (`Sop\|Object\|Lop\|…`), `flags?: {display, render, bypass, template, locked}`, `has_errors?`, `recurse_locked = false`, `limit`, `cursor` | Compact rows: `path, type, category, flags, input_count, child_count, has_errors`. |
| `node_info` | `inspect what: node` | `paths: [..]`, `include: [parms, inputs, outputs, children, errors, flags, hda, comment, position, userdata]` default `[parms, inputs, errors, flags]`, `include_defaults = false`, `recurse_locked = false` | Per node: `path, name, type {name, category, version, description, help_url}`, `flags`, `inputs: [{index, name, label, from: {path, output}}]`, `outputs: [{index, name, to: [...]}]`, `parms` (compact: `name, value, raw?, expression?, keyed?, locked?, menu_token?`; `raw` only when it differs from `value`, strings over 200 characters as `{elided, head}` as in `parm_get`), `errors, warnings, messages, cook_state`, `children_count`, `hda_locked?` (true at or inside a locked asset), `hda: {hda_locked, definition, library, matches_definition}`, `position`, `comment`, `color`. |
| `node_delete` | `edit` `delete` op | `paths`, `keep_connections = true` (reconnect input 0 to outputs when possible) | Destructive. Returns `deleted: [paths]`. |
| `node_edit` | `edit` `node` op | `items: [{path, name?, flags?, color?: [r,g,b], comment?, position?, lock?: bool (HDA allowEditingOfContents), bypass?, spare_parms?: {add?: [{name, type: float\|int\|string\|toggle\|menu\|button\|vector\|color, label?, default?, size?, min?, max?, menu_items?: [{token, label}], value_type?: string\|int, folder?, help?}], remove?: [names]}}]`, `partial = false` | Rename returns `old_path → path`. `spare_parms` (1.1, review 11 B9) builds `hou.*ParmTemplate`s and applies them with `parmTemplateGroup()` + `setParmTemplateGroup()` (a `folder` label is created when missing); it returns `spare_parms: {added: [parm paths], removed: [parm paths]}`. A `menu`'s `value_type` (1.2, review 12 papercut 3) is `string` by default, a `hou.MenuParmTemplate` whose value is the token (VEX `chs()`; `ch()` gives the item index), or `int`, a `hou.IntParmTemplate` with the menu whose value is the item index (`ch()`/`chi()`; `chs()` gives the index as text). A menu `default` is a token or an item index; a number that is no index but equals a token's text (`-1` for token `"-1"`) picks that token. Only spare parms can be removed; a name already on the node is `name_collision`; nodes inside a locked asset are refused with `locked` (a locked asset's own instance takes spare parms, like the wrangle's "Create spare parameters" button). Rollback restores the old template group and the removed parms' values. `parm_not_found` on a `null`, `subnet` or `geo` points here. |
| `node_copy` | `edit` `copy` op | `paths`, `to_parent`, `names?`, `with_inputs = true`, `position_offset?`, `return: summary\|full = summary` | `copyItems`/`copyNodesTo`. Returns new paths and the summary rows of `node_create` (`full` adds flags). |
| `node_connect` | `edit` `connect` op | `items: [{from: path\|null, from_output = 0, to: path, to_input: int\|name\|"next"}]`, `partial = false` | `from: null` disconnects. `name` uses `setNamedInput`/`inputNames()`. `"next"` uses `setNextInput` (merge-style nodes). Out-of-range → `code: invalid_input` with `hint` listing `inputLabels()`. |
| `node_layout` | `edit` `layout` op | `parent`, `paths?` (subset), `mode: children\|good_position` | `layoutChildren()` or per-node `moveToGoodPosition()`. |
| `network_describe` | `inspect what: network` / `outline` | `root`, `depth = 1` (2 for `outline`), `include_defaults = false`, `include_positions = false`, `recurse_locked = false`, `format: data\|python\|outline`, `cursor` | `data`: `root.childrenAsData(inputs=True, flags=True, position=…, default_parmvalues=False)` trimmed and with locked-HDA children replaced by `{"type": ..., "hda_locked": true}`. `python`: `asCode(brief=True)` for a single node only. `outline` (1.1, review 11 B11): `nodes: [{path, name, type, children_count?, display?, errors, inputs?, flags?, hda_locked?, children?}]` to `depth`, where `display` is a network's display node and `errors` a count; `inputs` (1.2, review 12 papercut 4) is the source path per input slot (`path:n` when the source's output `n` is not 0; 1.4, review 23 papercut 5) (`null` for an empty slot before a wired one) and `flags` the flags that are on (`["display", "render"]`), each left out when empty; `children_count` is left out at 0, and `hda_locked` marks only locked assets whose library is not under `$HFS` (Houdini's own `attribwrangle`, `mountain` and so on are locked assets too, with contents once cooked, and flagged every wrangle in review 12; `node_info` still reports `hda_locked` for them); no parms, paged at the response budget like `data` (`truncated`, `next_cursor`). The bridge resource `houdini://outline` is `{root: "/", format: "outline"}`. This is how an agent reads a graph in one call. |
| `network_build` | `edit` `build` op | `parent`, `data` (same shape `network_describe` returns, i.e. Houdini's own `hou.data` format), `on_name_collision: error\|rename\|replace = error`, `layout = true`, `dry_run = false`, `tag?` (stored as userData `hocuspocus:tag`), `press?: {node: [parm names]}` (1.4), `return: summary\|full = summary` | `parent.setChildrenFromData(...)` in one undo group after `dry_run`-style validation (type names exist, inputs resolvable). Returns created paths and per-node summary rows after cook (`full` adds flags). Input entries are `{from, from_index, to_index}`; a missing `to_index` is the entry's list position (§5.16). This replaces HocusScript and the network document. 1.4 (review 20 N2, as `node_create`): `setChildrenFromData` runs no parm callback scripts, so a menu or toggle with one that `data` sets adds a note to the result's `notes` naming `press`; `press` maps a node this call builds (a path relative to `parent` such as `geo1/src`, or absolute) to parm names whose callbacks (or buttons) run through `parm_set`'s press after the build is wired and before replaced nodes are deleted, in the same undo step, returning `pressed` (parm paths) and `side_effects: {node path: {parm: [old, new]}}`; a failed press rolls the whole build back, and `dry_run` validates the node names. `press` is an argument rather than a key in `data` so that `data` stays Houdini's own `hou.data` format. |
| `parm_get` | `inspect what: parms` | `paths: [...]` (parm or tuple paths), `frame?`, `include: [keys, menu, template, ramp, multiparm]`, `full_strings = false` | Per parm/tuple: `path, name, tuple, component_names?, type, value` (evaluated at `frame` or current), `raw?` (`unexpandedString`/`rawValue`, left out when it equals `value`; 1.1, review 12), string `value`/`raw` over 200 characters as `{elided: <chars>, head: <first 80>}` unless `full_strings`, `expression?`, `language?`, `is_default`, `locked` (the parm lock), `hda_locked` (inside a locked asset), `keyframes?: {count, first, last}`, `menu?: {token, label, items: [...]}` (items capped at 50; a menu Houdini builds on the node, from a menu script or the input's groups and attributes, is evaluated on the parm and adds `dynamic: true`, with `items: []` and a `note` when it is empty even after a cook of the SOP; 1.3, review 14 papercut 10), `ramp?` (1.3: with `include: [ramp]` the ramp is said once, as `value`, and `ramp` is `{count}`), `multiparm?: {count, instances}`, `template?: {label, type, default, min, max, help}`. A tuple path returns components. A component path on a tuple returns that component. `code: parm_not_found` carries `candidates` (nearest names on the node, incl. tuple components). On a LOP a USD attribute name (`.../inputs:intensity`) resolves to the parm `hou.text.encodeParm` makes of it (`xn__inputsintensity_i0a`), for `parm_get`, `parm_set` and `node_create` `parms`; results carry the resolved path (1.2, review 13). 1.3 (review 18 papercuts 4, 9, 10): a string parm whose menu only the node builds (the Copernicus `signature`: no template items, no script) lists its `menu` and is validated like any menu; menu labels lose a leading `![icon]` reference; ramp keys and values are rounded to 6 significant digits, without `raw`. |
| `problems` | `inspect what: problems` | `root = "/"`, `include_warnings = true`, `cook_uncooked = false`, `recurse_locked = false`, `timeout_s = 30`, `limit`, `cursor` | Walks the subtree, reports nodes with errors/warnings, broken channel references, missing file parms (`file`-type templates whose expanded path does not exist), unconnected required inputs. Errored nodes changed since their last cook are recooked first, so a fixed node is never listed. `cook_uncooked` cooks never-cooked nodes too. The scan stops after a budget (10 s, or half of `timeout_s`) with `incomplete: true` and a `next_cursor` that continues the walk without losing rows. A TOP node with failed work items is a `failed_work_items` row with `count`, the first item and its error (1.2). The "why is my node red" tool. |
| `geo_info` | `inspect what: geo` (`image` on a COP) | `path` (SOP, or OBJ → its display SOP), `frame?`, `attributes: full\|names = full` (1.4) | ~1 KB: `point_count, prim_count, vertex_count, bbox: {min, max, size, center}, prim_types: {polygon: n, packed: n, volume: n, …}, attributes: {point: [{name, type, size, type_info}], vertex, prim, detail: [{name, type, value}]}, groups: {point: [{name, count}], prim, edge, vertex}, intrinsics?`. Uses intrinsics and bulk accessors, never Python loops over points. 1.3 (review 17 P1-7): `intrinsics` lists every volume under `volume_columns: [name, prim, resolution, voxel_size, min, max]` and every VDB under `vdb_columns: [name, prim, class, value_type, active_voxels, voxel_size]` (100 each, then `volume_total`/`vdb_total`); detail values that are `hou` vectors and matrices are lists, and a dict over 200 characters is `{elided, keys}`. 1.4 (review 23 papercut 8): `attributes: names` lists only names per class; solver internals (Vellum and DOP bookkeeping such as `pprevious`, `hitnml`, `dPw`, `varmap`, and `__*`) are left out of both modes and counted in `internal_attribute_count` with a note (`geo_read` reads them). 1.3 (review 18 papercut 3): on a Cop node (or a COP network's display node) it returns the image instead, from `CopNode.layer()`: `kind: image, output, layer_type, resolution, data_window, pixel_scale, storage, border, constant?, channels: {r: {min, max, mean}, …}, other_outputs: [{name, layer_type}]`; the output schema no longer requires the point counts. |
| `geo_read` | `inspect what: geo, rows: true` | `path`, `class: point\|prim\|vertex\|detail`, `attribs?: [..]` (default all), `start = 0`, `cursor?`, `count = 50`, `group?`, `stats = false`, `frame?` (1.3) | Spreadsheet rows as arrays with a `columns` header. `stats` adds `min/max/mean` per numeric attribute and `unique` (≤ 20) per string attribute over the **whole** class, computed with numpy bulk accessors. `next_cursor` is the next row offset as a string (pass it as `cursor`). `frame` reads `geometryAtFrame` without moving the playbar (1.3, review 17 P1-5). |
| `node_type_search` | `search kind: types` | `query`, `category?`, `limit = 20`, `include_hidden = false`, `current_only = true` | Ranks exact name = 100, exact label = 95, name prefix, label prefix, all words in the label; a plain-language query is then scored word by word without stop words, a word naming the type (4) or a whole label word (3) outranking a keyword (1.5) or a description word (1), with a short Houdini synonym table at half weight. Marks `is_current_version`. Row: `name, label, category, version, description` (clipped to 120 chars), `inputs: {min, max}, deprecated`. `total` is the real number of matching types, never a cap: word-by-word scoring lets a broad query match hundreds (1.2, review 12). With `current_only` (1.1 default) every version of a type folds into its current version's row, ranked by its best-scoring version, and that row carries `other_versions: [...]`; `false` lists each version as its own row (`current` names the head). All 18 categories supported. `node_type_not_found` candidates come from the same ranking, led by known other names (`distantlight` is `hlight` and `camera` is `cam` in /obj). 1.3 (review 18 papercuts 5, 6): Cop types also match the labels of their top-level menus (`remap`'s Threshold, `blend`'s Over); a Cop synonym table maps compositing words to types (threshold: `remap`, gradient: `ramp`, composite or over: `blend`, text: `font`, write: `rop_image`); a network type's row adds `child_category` and `typical_parents` (`copnet`: `/img`); results with legacy `Cop2` types carry a note that Copernicus is `Cop`. 1.4 (review 23 papercut 6): with `current_only` rows leave out `is_current_version` (every row is current), and `child_category`/`typical_parents` shared by every row are said once in `common`. |
| `node_type_info` | `inspect what: type` | `type` (`category/name` or bare name with `category`), `include_parms = true`, `include_help = false`, `folder?` (a label, an `A / B` path, or `""` / `(no folder)` for the top-level parms), `parms?` (glob on name or label; `a\|b` matches either), `detail: compact\|full\|folders = compact` | `folders`: `[{folder, parms}]` (visible parm count per folder), no parm rows; every name it lists is accepted by `folder`. `compact`: `parms: {folder: [[name, label, type, default, components?]]}` under `parm_columns`, no menus, ranges, hidden parms, per-parm help, `help_url` or `tags` (Sop/scatter: 3.0 KB against 5.7 KB). `full`: `name, label, category, version, description, help_url, inputs: [{index, name, label}], outputs, parms: [{name, label, type, size, default, min, max, menu?, folder, help?, is_hidden}]` grouped by folder (1.3: a script menu such as `pdg_cachemode`, or a menu built from input geometry such as a SOP `group`, is evaluated on a temporary instance as `menu: {items, dynamic: true}`, or `items: []` with a `note` when it evaluates empty there, never a bare `default`), plus `help_text` (first ~2 KB of the node help from `$HFS/houdini/help/nodes.zip`, best effort) when asked. With `folder` or `parms` (a parm lookup) `inputs` becomes `inputs_count` and `full` leaves out `folders` (1.2, review 13: 2.2 KB of 3.3 KB on `mtlxstandard_surface` was its 42 inputs). 1.3 (review 18 papercuts 4, 9): `full` also evaluates a string menu only the node builds (a Copernicus `signature`); menu labels lose a leading `![icon]` reference; a `compact` listing over 8 KB leaves out the parms a menu hides at its default (the per-pattern parms of the other `tilepattern` patterns) and lists them as `variants: {menu parm: parms left out}` with a note (`parms` or `detail: full` list them). 1.4 (review 23 papercut 7): a wildcard `parms` glob lists the parms whose name or label has a word starting with the glob's text first (`*pin*`: Pin Type); those matched only inside a word (`dampingratio`) follow, named in `substring_matches` with a note and marked `matched_by: "substring"` in `full` rows. 1.4 (review 24 N2): an alternative without wildcards is an exact match and ranks with the word-start matches, so `*pin*|group` never lists `group` in `substring_matches`, and the note counts only the wildcard alternatives' inside-word hits. |
| `selection` | `edit` `select` op (read: `houdini_python`) | `paths?` | Omit to read `hou.selectedNodes()`; provide to `setSelected` exactly. |
| `usd_stage` *(full)* | `inspect what: stage` | `lop_path`, `prim = "/"` (a path or a glob: `*` within a segment, `**` across), `depth = 1`, `include: [attributes, xform, bindings, layers]`, `attribs?` (name glob, `a\|b`; implies attributes), `summary = false`, `time?`, `limit`, `cursor` | Traverses `lop.stage()` read-only, paged by `limit` and `cursor`; `total` is on every page (a counting walk that builds no rows, capped at 100,000 with `total_capped`). Attribute values at `time` for primitive types; arrays of up to 4 elements (8 for strings and tokens) in full, longer ones as `{len, first}`. `xform` gives `local`, and `world` only when it differs. `summary` returns `{total_prims, counts_by_type, bbox_world: {min, max, size}}` for the whole subtree (UsdGeom.BBoxCache, default and render purposes) instead of rows. A ROP inside a LOP network (`usdrender_rop`, `usd_rop`) has no stage: 1.2 refused it naming its input; 1.4 (review 23 papercut 10) reads the LOP it renders (its `loppath`, else its input) with a `note`, and refuses only a ROP with neither. 1.4 (review 23 papercut 4): `layers.stack` rows are `{identifier, save_path?, owner_node?, time_codes?}`: `save_path` from the layer's HoudiniLayerInfo (where a `sopimport` with `enable_savepath` writes its data) or a file layer's own path, `owner_node` the LOP that made the layer, `time_codes` `[start, end]` when authored. 1.4 (review 24 N7): identifiers and `save_path` use forward slashes, and a file layer whose own path equals its identifier has no `save_path` (it repeated the identifier with backslashes). |

### A.2 `viewport_capture` (1.4; 2.0: `look`)

| Tool | 2.0 replacement | Args | Behaviour |
|---|---|---|---|
| `viewport_capture` | `look` (`source: viewer`; `quality`) | `camera?` (OBJ camera, LOP camera node, or camera prim path), `lop_path?`, `cop_path?` (1.3), `frame?`, `resolution = [1024, 768]`, `fit?: all\|selected\|none` (1.3: no schema default), `source: auto\|viewer\|flipbook_rop\|opengl_rop = auto` (1.4: `opengl_rop` is the 1.3 name of `flipbook_rop`), `path?` | Returns MCP **image content** (PNG, downscaled so the longest side ≤ 1024) plus `{path, width, height, camera_used, scene: obj\|stage, lop_path?}`. `viewer` uses the GUI SceneViewer flipbook of one frame (captures what the user sees, as it is, `fit_used: "none"`, unless `fit` is passed explicitly: then it frames all or selected for the grab; with `camera` it looks through it; either way the view, and the camera the viewport looked through, is saved and put back afterwards (1.2, review 15). `context` is the viewer's network and `notes` say when it is not the captured scene's, since other objects then draw ghosted). `flipbook_rop` (1.4) renders through a Flipbook ROP, falling back to the OpenGL ROP and then a temporary Karma ROP (§8; `source_used` names the one that ran and `notes` why), and, when `camera` is absent, through a camera framed on the bbox (`camera_used: "temporary"`; `fit: none` reuses the last framing); works headless. A LOP camera node, a camera prim (on `lop_path`'s stage, or the /stage display LOP's) or `lop_path` captures the stage through the ROP's LOP source (a framed stage gets a temporary camera LOP after the LOP; the network's display LOP is used for a LOP camera when its stage has the camera); without `camera` or `lop_path`, the /stage display LOP is captured when /obj displays nothing, and otherwise a note names it (1.2, review 13). Lights are refused as cameras; camera errors list the scene's cameras as `candidates`. A look is read-only: headless, camera and ROP exist only in the child hython (§8); in the GUI they are created outside undo and deleted after the render, and `notes` says so if Houdini still marked the hip modified. `auto` prefers `viewer` in GUI unless a `camera` or a stage is captured. The capture file and the copy at `path` are written opaque, composited onto the inline image's grey (1.2, review 12): the OpenGL ROP has no background-colour parm (checked on 22.0.466; nor has the Flipbook ROP, which only takes a background image) and leaves the background transparent, which most viewers show as white. 1.3 (review 19 papercut 7): `fit` has no default in the schema, which had said `all` although the viewer never applied it; without `fit` the viewer captures the view as it is and the ROP source frames all. 1.3 (review 18 papercut 1): `cop_path` (a Cop node, or a COP network's display node) renders it through a temporary `rop_image` in its network (about 0.2 s, outside undo and `events`, deleted afterwards) and returns the PNG at the COP's own resolution (`resolution` is ignored) with `scene: cop` and `layer: {layer_type, resolution, data_window}`; it cannot be combined with `camera`, `lop_path` or `source: viewer`. A Cop node passed as `camera` or `lop_path` is refused with a hint naming `cop_path`, and a capture without `camera`, `lop_path` or `cop_path` names the COP networks under `/img` in a note. 1.4 (review 23 P2-10): `lop_path` naming a ROP inside a LOP network (`usdrender_rop`, `usd_rop`), which has no output stage, captures the LOP the ROP renders (its `loppath`, else its input) with the note `Captured /stage/rset, the LOP /stage/karma_rop renders: a ROP has no output stage.`; a ROP LOP with neither is refused as before. |

Sources (1.4, D31): `auto` prefers `viewer` in a GUI session unless a `camera` or a stage
is captured; `flipbook_rop` (alias `opengl_rop`, its 1.3 name) tries the Flipbook ROP, the
OpenGL ROP (each only where this Houdini has the type) and a temporary Karma CPU ROP in the
host; headless a ROP whose render process crashes hands the frame to the next, in the GUI a
ROP that writes no image does and there is no Karma step. `source_used` names the one that
ran (`viewer`, `flipbook_rop`, `opengl_rop` or `karma`). In `compat_1x` it runs on the
look backends with exactly this policy (`host/look/select.py` `capture_plan`).

### A.3 Resources, prompts and instructions (1.4)

`compat_1x` lists the 1.4 resources: `houdini://status`, `houdini://outline`
(`network_describe {root: "/", format: "outline", depth: 2}`), `houdini://node/{path}`,
`houdini://node/{path}/parms`, `houdini://node/{path}/geo`,
`houdini://nodetype/{category}/{name}`, `houdini://job/{id}` (routed to the Houdini in the
job id), `hocuspocus://guide` and `hocuspocus://tools`; no etags or subscriptions. Its
prompts are the four 1.4 ones, `inspect_scene`, `build_sop_chain` (ends with
`viewport_capture {"fit": "all"}`), `debug_red_node` and `turntable_preview`; its
instructions and guide are the 1.4 texts (`INSTRUCTIONS_1X`, `RESOURCES_1X` and
`RECIPES_1X` in `bridge/instructions.py`).
