# Review 01: Architecture and Transport (current system)

Reviewer scope: `core/*`, `startup.py`, `live/{context,dispatcher,operations,monitor,houdini_undo,graph_*}.py`, launcher and broker scripts, build and install scripts, and the transport, spec and compatibility docs.
Method: code reading, plus read-only experiments with `hython` 22.0.466 (probe host on port 37902; my scratch state was removed afterwards), the broker module against an absent host (port 37950), and Python unit tests run with `-B`.

**Bottom line.** The core execution idea is sound: an in-process HOM host behind a loopback HTTP endpoint, single-writer dispatch to the main thread, and a stdio shim that outlives Houdini. Around that core sits a large amount of supply-chain and durability machinery built against a threat model this product does not have. That machinery is what makes the tool hard to install, upgrade and debug. It also hides one severe usability bug: every tool result passes through a redaction filter that deletes file paths and long strings before the agent sees them. Session and hip management, the thing an agent needs most, is thin.

---

## 1. End-to-end request flow

```
MCP client (Claude/Codex)
  │ stdio, newline JSON (Content-Length framing also accepted)
  ▼
hocuspocus-mcp-stdio.py launcher (scripts/hocuspocus-mcp-stdio.py:568)
  · verifies every governed file against install manifest, copies the tree into a temp dir,
    imports hocuspocus from memory (_TrustedModuleFinder :83, _materialize_snapshot :461)
  ▼
StdioBroker (core/stdio_bridge.py:445) + BrokerWorkers (core/stdio_runtime.py:200)
  · 4 worker threads + 1 control thread, 64-deep queue, "broker_busy" on overflow (:137-158)
  · tools/call gets params._operation_id = "op:<hex>" (core/delivery.py:14-25)
  │ HTTP/1.1 POST http://127.0.0.1:37219/hocuspocus/mcp, Bearer token, one connection per request
  ▼
RuntimeHTTPServer (ThreadingHTTPServer, core/server.py:361) — one OS thread per request
  · Origin check (:762), bearer compare (:495), Content-Length cap 8 MB (:46, :292)
  · host-identity lease (core/host_identity.py:32), session admission (server.py:190)
  · execute_tool_call (core/operation_execution.py:151):
      operation_history.admit → SQLite row + (for every non-readOnly tool) a 16 MB pre-zeroed,
      fsync'd journal slot (operation_history.py:520-526, operation_journal.py:65-84)
      → monitor.begin_tool_operation → tool.handler(...)
  ▼
LiveOperations handler → self._call_live(...) → LiveCommandDispatcher.call (live/dispatcher.py:136)
  ├─ UI mode (hou.isUIAvailable()): spawn a new thread per command (:230-237) that blocks in
  │    hdefereval.executeInMainThreadWithResult(self._execute, cmd) (:250) → runs on Houdini main thread
  └─ hython mode: a single background "HocusPocusLiveWorker" thread drains a Queue (:98-107, :223)
       → hou runs OFF the main thread (verified: dispatcher mode "synchronous" in hython)
  ▼
_execute holds an RLock (:267), wraps the callback in monitor.activate_tool_operation, then hou.*
  ▼
result → history.finish (sanitised) → audit.jsonl → sanitize_terminal_payload → HTTP 200 JSON → broker → stdout
```

**Marshalling.** Graphical sessions use `hdefereval.executeInMainThreadWithResult`. `hou.ui.postEventCallback` appears only in `_schedule_pump`/`_drain_queue` (dispatcher.py:198-221). Those two methods are dead code: the only caller of `_schedule_pump` is `_drain_queue`, and the only caller of `_drain_queue` is `_schedule_pump`. In hython, `hou` runs on a worker thread. That contradicts the spec's "network threads never mutate Houdini directly" (docs/houdini-mcp-spec.md §2.3). It works only because HOM serialises internally.

**Timeouts (mismatched).**

| Layer | Default | Where |
|---|---|---|
| Broker connect / request | 1 s / **10 s** (max 30 s) | stdio_bridge.py:44-48 |
| Client snippet overrides request | 30 s | config/clients/*.example |
| Host dispatcher wait | 30 s (`request_timeout_seconds`); the client can override per request through unbounded `params._timeout_seconds` | config/default.toml, server.py:893-895 |
| Task `run_live` | 600 s | live/tasks.py:90 |

**Failure modes I consider real.**
1. **Timeouts do not stop work.** `dispatcher.call` catches `TimeoutError`, sets a cooperative cancel flag and re-raises (dispatcher.py:139-142). The main-thread callback keeps running, but `execute_tool_call` turns the exception into "Internal server error" (operation_execution.py:168-177). It records `commit_state` from the monitor transaction *at timeout time* (:68-87), so the history entry can say `not_committed` for a mutation that commits a second later.
2. **The default timeouts guarantee false ambiguity.** With no environment override, the broker gives up at 10 s and reports `ambiguous_delivery`, while the host still allows 30 s. Any `scene.open_hip`, cook or save that takes longer than 10 s looks like a delivery failure to the agent.
3. **Unbounded thread growth in UI mode.** Each request costs one HTTP thread plus one hdefereval thread that blocks with no timeout. If the main thread is wedged (modal dialog, long cook), threads pile up.
4. **Re-entrancy risk (unverified).** `_execution_lock` is an RLock taken on the main thread. If a HOM call pumps the Qt event loop (load progress, interrupt dialog), hdefereval can start a second command *nested inside* the first. The RLock permits this, and the monitor's single `_active_operation_id` would be overwritten. A plain non-reentrant guard that rejects nested dispatch would be safer.
5. **No streaming at all.** The host returns 405 for GET (server.py:76-96), declares `listChanged:false` and `logging:{}` (server.py:1162-1166), and never sends progress or log notifications. "Streamable HTTP" is in practice plain JSON request/response.
6. **Tool errors are JSON-RPC errors, not `isError: true` results.** A failed `tools/call` is raised as a protocol error (operation_execution.py:165-177). MCP intends execution failures to come back as results the model can read and react to.

## 2. The "durable broker": is the complexity justified?

**What it buys.** The MCP client can start before Houdini and survive a Houdini restart without a `/mcp reconnect`. A `tools/call` is never blindly replayed. Discovery is cached. Both of these are worth having.

**What it costs.** These are the moving parts on the client-to-host hop:

| # | Part | Lines | Verdict |
|---|---|---|---|
| 1 | Launcher integrity: manifest digest of every governed file (up to 20,000 files / 64 MB), hard-link and reparse checks, temp-dir copy of the tree, in-memory finder, HMAC runtime attestation | 676 | **Accidental** |
| 2 | Dual framing (newline and Content-Length) | ~100 | Accidental (newline only) |
| 3 | Worker pool + control lane + busy rejection | 278 | Over-built (a single reader plus a thread per request is enough) |
| 4 | Credential epoch, authority epoch, 401 refresh with serialised re-resolution from the "verified active package" | ~250 | **Accidental** (re-read one token file on 401) |
| 5 | Offline `initialize` synthesis, discovery cache, host watcher, `list_changed` emission | ~200 | Essential (simplify) |
| 6 | Generation-change recovery, broker session resume header bound to source-workspace sessions | ~200 + host side | Mostly accidental |
| 7 | Host `HostIdentity` generations/leases, session-generation map, checkout-generation tracking (server.py:591-690, 1051-1098) | ~250 | Partly accidental. The generation only advances on an in-process `restart()`, never on hip load, so it does not track the thing that actually invalidates checkouts (a scene change). |
| 8 | Operation history SQLite with cross-process host leases and heartbeat thread, 16 MB journal slots, ctypes directory fsync, file locks | 1,326 | **Over-engineered** (see §5) |

**What fails today in practice.**
- **Cold start yields zero tools.** I ran the broker against an absent host. `initialize` succeeds (with a non-standard `hostOnline:false` field, stdio_bridge.py:396). `tools/list` then returns a `host_offline` *error* (stdio_bridge.py:1005-1012), so an agent started before Houdini sees no tools at all. It depends on the client honouring `notifications/tools/list_changed` later, and there is no tool to launch Houdini.
- **The source-tree launcher refuses to run.** In this checkout it fails with the opaque "failed integrity verification." for three independent reasons:
  - `__pycache__` folders exist (any test run creates them);
  - `core.autocrlf=true` rewrites every file to CRLF, so 330 of 332 digests mismatch;
  - the committed `package/install-manifest-v1.json` is stale, with 41 content mismatches after LF normalisation and 21 undeclared files, including `delivery.py`, `operation_history.py` and `stdio_runtime.py`.

**Recommendation.** Keep a stdio shim, but make it **thin and stateless**:
- Bundle a **static tool catalogue** with the shim, so `tools/list` always works offline.
- Add **shim-local tools**: `houdini.list_instances`, `houdini.launch`, `houdini.attach`. These work without a host.
- Discover hosts through a per-instance registry file written by each Houdini (pid, port, token, hip path, version), not one fixed port.
- Proxy calls; never retry `tools/call`; return `host_unreachable` with the operation id. Remove items 1, 2, 4 and 6 entirely.

An in-process MCP endpoint that clients reach directly (stdlib server or `hwebserver`) is fine as an **optional second transport** for clients with good HTTP reconnect. It should not be the only one, because it cannot list tools or launch Houdini while Houdini is down.

## 3. Session and hip-file management

**What exists** (live/ops/scene.py, session.py, monitor.py):
- `scene.new`, `scene.open_hip`, `scene.merge_hip`, `scene.save_hip`, `scene.get_summary` (hip path and dirty flag), `session.info`.
- Undo/redo with an `expected_label` guard.
- A `hou.hipFile` event callback that only bumps a revision counter (monitor.py:323).

**Gaps and defects:**
1. **Unsaved work is silently discarded.** `scene.new` always calls `hipFile.clear(suppress_save_prompt=True)` (scene.py:67). `open_hip` defaults `suppress_save_prompt=True` (:79). There is no `hipDirty` check or `discard_unsaved` confirmation argument.
2. **Policy is asymmetric.** `open_hip` and `merge_hip` take arbitrary paths with no policy check, although loading a hip runs embedded Python (HDA scripts, callbacks). `save_hip` is path-checked (:104-126). Meanwhile `local-dev` has empty `approved_roots`, so `ensure_path_allowed` allows any path (policy.py:80-81).
3. **Paths are redacted from results.** `hipFile` and `path` come back as `"<redacted>"`, verified live (see §5). The agent cannot learn which file is open or where it just saved.
4. **Missing features:** recent files, `$HIP`/`$JOB` queries, save-as-increment or backup, `hipFile.isNewFile`, load warnings surfaced as structured data, before/after-load events exposed to the agent, scene identity (a hip path plus a load counter) for invalidating checkouts and caches.
5. **Persistent state is not scoped to a scene.** `document_graph.sqlite3` is keyed by `network:/obj/geo1` (document_snapshot.py:395) and stored per user preference directory (graph_store.py:247). Two Houdini instances, or two hip files, share the same document ids. It grew to 12 MB in my probe after two `node.create` calls.
6. **Multiple instances are broken.** The port is fixed at 37219 and `RuntimeHTTPServer.allow_reuse_address = True` (server.py:363). On Windows that sets SO_REUSEADDR, which **lets a second Houdini bind the same port silently** (verified with Python 3.13: the second bind succeeded). Requests then go to either process nondeterministically. The broker's URL is a single environment variable (stdio_bridge.py:1157). All instances also share the token, the log file (rotation conflicts), the audit log, the operation history and the graph store.
7. **Nothing can pick or launch an instance.** There is no "which Houdini" selection, no launch, no hython headless worker (`workers/` is an empty scaffold).
8. **Node callbacks on every node.** The monitor registers 17 event types, including `ParmTupleChanged`, on *every node in the scene* at startup (monitor.py:403-418, :241-262). On large production scenes this has a real cost and should be measured.

## 4. Policy, capabilities, tokens, grants, audit, workspace authority

The threat model is implicit and inconsistent. The tool defends against an attacker who can rewrite files in `Documents\houdini22.0`: bytecode bans, hard-link checks, manifest digests, HMAC attestation, DPAPI-protected token journals. Anyone with that access can already edit `houdini.env`, `456.py` or the client's MCP config, so these checks protect nothing. At the same time, build publishes the bearer token as a plaintext **User environment variable** `HOCUSPOCUS_TOKEN` (build_transaction.ps1:592-625), which every process can read.

| Mechanism | Real value on localhost | Keep? |
|---|---|---|
| Loopback bind + Origin check | High (DNS rebinding, browser CSRF) | **Keep** |
| Bearer token | Medium (other OS users, browser) | Keep: per-instance random token in a user-only registry file. Drop the build-time token, DPAPI journals, environment publication and rotation transactions. |
| Capability profiles (`safe`/`local-dev`/...) | Medium as a *read-only switch* | Keep one `read_only` toggle and one `allow_python` toggle. The 8-capability vocabulary has 3 capabilities that are never enforced (`launch_processes`, `use_network`, `submit_farm_jobs`). |
| `run_code` gate | Low as built: there is **no Python/HOM exec tool at all**, yet `open_hip` runs arbitrary embedded code ungated | Replace with an explicit, first-class `houdini.exec_python` tool behind `allow_python` |
| `approved_roots` | Low (empty, so everything is allowed by default) | Keep as optional, defaulting to `$HIP`/`$JOB`/project |
| Source-workspace authority (sessions, persistent grants, TTLs, per-minute rate limits, SQLite audit) | ~2,800 lines (workspace_* + source_audit). Rate limits such as 20 writes/min actively throttle agents. | Collapse to "project roots configured by the user". Drop grants, TTLs and rate limits. |
| Principal IDs hashed from the bearer | None (one user) | Drop |
| audit.jsonl | Low-medium. Unbounded append (audit.py:53-56), and redaction removes the paths you would audit. | Keep a rotating, *unredacted* local log |
| Install governance (bytecode admission, manifest on every launch) | Negative: it breaks dev and upgrades | Drop |

## 5. Journal, delivery, idempotency, undo

**Keep:**
- A stable `operation_id` per `tools/call` and a `session.get_operation` reconciliation lookup.
- The rule never to replay an ambiguous mutation.
- The `commitState` classification (`committed`/`not_committed`/`partial_or_unknown`) derived from the monitor transaction.
- Undo groups and the `expected_label` guard on undo/redo (houdini_undo.py).

**Fix or drop:**
- **Severe bug: result sanitisation.** `execute_tool_call` returns `sanitize_terminal_payload(result)` (operation_execution.py:198-200). Even the "terminal" copy is sanitised (operation_history.py:922-950). `_sanitize` (operation_history.py:875-897) does three things:
  - replaces any string over 4,096 characters with `<redacted>`;
  - replaces any string matching a drive/UNC/`/Users` path with `<redacted>`;
  - redacts keys `source`, `details`, `content` (when not a container), `hdaFilePath`, `libraryFilePath` and others, and truncates lists at 4,096 items.

  Verified in a live hython host: `scene.get_summary.hipFile == "<redacted>"`, `scene.save_hip.path == "<redacted>"`, and the text block "Saved hip file to C:/..." becomes `"<redacted>"`. Any tool returning source text or a file path is mangled. This alone makes the tool much worse for agents. Redaction belongs only in persisted records, if anywhere.
- **Journal slots.** Every non-readOnly call pre-allocates and fsyncs a **16 MB zero-filled file** before running (≈10–15 ms measured here, plus about 16 GB of SSD writes per 1,000 mutations). Pending operations are capped at 4 (64 MB / 16 MB). This exists to survive a crash *between* commit and SQLite write, an edge case not worth the cost. An in-memory ring of terminal results plus a small SQLite table is sufficient. Drop host leases and heartbeats.
- **Argument-digest collision detection and 24 h retention.** Fine but unnecessary. Keep only "same op id returns the same terminal result".
- **Undo is ad hoc.** There are 28 hand-written `undos.group` sites across ops; some mutating paths have none. Centralise it: the dispatcher wraps *every* non-readOnly call in `hou.undos.group(f"HocusPocus: {tool} [{op_id}]")`. Undo then means "undo agent op X".
- **Hard-coded mutation list.** `_should_bump_graph_revision` (server.py:1111-1135) duplicates tool annotations as a list of name prefixes. Drive it from `readOnlyHint` instead.

## 6. Install, build and update story

**Why `hython -c "import hou"` prints HOCUS998 `invalid_install_root` from the repo root.** In hython, `$HIP` is the current directory, and `hou.houdiniPath()` (observed) contains `C:/Users/jujun/DEV/hocus-pocus` ahead of the user preference directory. Houdini therefore finds the repo's `scripts/python/pythonrc.py` and runs it at HOM startup. The script auto-starts at import (pythonrc.py:265). `_installed_root()` requires `HOCUSPOCUS_ROOT`, which only the installed package JSON sets, and it is unset, so it raises `invalid_install_root` (pythonrc.py:119-121). Even with a correct install, admission would still fail on this machine for two more reasons:
- `startup.py:20` pins `SUPPORTED_HOUDINI_VERSION = "22.0.368"` with an exact match (`:110`), but 22.0.466 is installed, so the result would be `unsupported_houdini`;
- `sys.dont_write_bytecode` is false unless the generated pointer sets `PYTHONDONTWRITEBYTECODE` (the repo's package/hocuspocus.json does not), so the result would be `ungoverned_bytecode`.

Any test run that leaves `__pycache__` in the tree also blocks it (pythonrc.py:159-160).

**Friction and fragility:**
- **About 2,400 lines of PowerShell.** build.ps1 and build_transaction.ps1 (1,767 lines) include inline C# for file IDs, DPAPI, token and output journals, and a base64 exec'd manifest helper. The client installer is another 609 lines. Build runs `compileall` only to delete the bytecode afterwards (build_transaction.ps1:1080-1087).
- **The pointer JSON is matched for exact canonical equality** (hocuspocus-mcp-stdio.py:160-237). Adding a standard package key such as `enable` breaks the launcher.
- **Install location assumes `MyDocuments\houdini22.0`** (build_transaction.ps1:1144-1150). Houdini actually uses `$HOME/houdini22.0` when `HOME` is set: hython launched from Git Bash resolved `C:/Users/jujun/houdini22.0`. Both installers hard-code `Documents\houdini22.0`.
- **No dev mode.** Every source edit requires rebuild and reinstall. The source-tree lane is broken (§2).
- **Broker launch is slow.** Each launch rehashes and copies the whole install to a temp directory.
- **Exact build pin.** A daily-build update makes the tool refuse to start. Use a range (`>=22.0,<22.1`), warn on untested builds, and never block.
- **`python3.11libs` naming.** Houdini 22 runs Python 3.13 and auto-adds only `python3.13libs`, so this directory loads only because the package prepends `PYTHONPATH`. Rename it to a version-neutral `pythonX.Ylibs`-independent location (e.g. `python/` added via the package JSON). Also drop `target-version = "py311"`, or bump it to py313.
- **Errors give no reasons.** Launcher failures are a single string with no reason ("failed integrity verification."). Diagnosis needs code reading.

## 7. Code health

- **Size.** The package is 98k lines of Python: core 8.2k, live 33.5k, hocusscript 55.9k. A 1,200-line lint cap (scripts/lint.ps1:55) has produced files packed to 1,196–1,200 lines and split by size rather than cohesion (`*_helpers.py`, `graph_store_*`, `document_apply_*`).
- **God object.** `LiveOperations` combines 28 mixins (operations.py:50-78), and the runtime injects private attributes into it after construction (server.py:392-395). 103 tools are listed. `tools/list` is about **100 KB** (measured), roughly 25k tokens of agent context before the first call, plus non-standard per-tool fields (`requiredCapabilities`, `outputSummary`, `examples`).
- **Dead code:** `_schedule_pump`/`_drain_queue`; the `workers/` package; config `[feature_flags]` and `enable_stdio_bridge` (no runtime readers); 3 unenforced capabilities.
- **Duplication.** The governed-roots list exists in three languages and files (pythonrc.py:14-22, launcher :30-38, build_transaction.ps1:1073-1076). Token regex and protocol constants are also repeated between broker and host.
- **Tests.** 43 `test_*` methods across about 23k test lines, scenario-style. The broker contract is a chain of `_assert_*` helpers called from inside the node-type-discovery scenario (tests/runtime_node_type_discovery.py:143). One failure masks the rest, and the names do not describe the coverage. There are no tests for UI-mode dispatch, timeouts or re-entrancy, and no CI workflow in the repo. `tests.test_runtime_scenarios` passes (8 tests, 3 s).
- **Error codes.** There are 395 distinct `HOCUSnnn` literals and no central registry. `HOCUS999` alone means host_offline, ambiguous_delivery, broker_busy, host_session_stale, host_generation_changed and operation_* collision; the actual discrimination is done by `data.kind`. The scheme carries no information an agent can use; `kind` plus `retryable` is what matters.
- **Logging.** The host logs every HTTP request at INFO to Houdini's stderr and to a 1 MB rotating file shared by all instances (logging_utils.py:22-37). The broker has no logging. Redaction makes the audit log unusable for debugging.

## 8. Top 10 recommendations (ranked)

1. **Stop sanitising tool results returned to the agent.** Paths and source text are the payload; redaction currently breaks hip, HDA and source workflows outright.
2. **Rebuild the stdio shim as thin and stateless**, with a static tool catalogue, so `tools/list` works without Houdini. Delete the launcher integrity machinery, the credential epochs and the dual framing.
3. **Add an instance registry plus launch/attach tools.** Each Houdini binds an ephemeral port (no `SO_REUSEADDR`), writes `{pid, port, token, version, hipPath}` to `%LOCALAPPDATA%/HocusPocus/instances/`, and the shim lets the agent list, pick and launch instances (GUI or hython). This fixes the silent dual-bind bug and enables multi-instance work.
4. **Make session and hip management first-class and safe.** Refuse `new`/`open` on a dirty scene unless `discard_unsaved` or `save_first` is set. Add save-as, increment, recent files, `$HIP`/`$JOB`, and load warnings. Track scene identity (hip path plus load epoch) to invalidate checkouts and caches.
5. **Unify timeouts and make them honest.** Long work becomes a task. Synchronous calls get one deadline shared by shim and host. On timeout, report `still_running` with the op id instead of "Internal server error", and finalise `commitState` only when the callback actually ends.
6. **Centralise undo grouping and op identity in the dispatcher.** Every mutating call becomes exactly one labelled undo group. Keep `operation_id` plus `get_operation`. Replace the 16 MB journal slots and leases with a small SQLite or in-memory terminal cache.
7. **Replace the policy and workspace-authority stack** (~2.8k lines) with a localhost model: loopback, Origin check, a per-instance token file, `read_only`, an optional `approved_roots` defaulting to the project, and an explicit `allow_python` gate for a new first-class `exec_python` tool.
8. **Make install boring.** One script with a dev mode that links the repo, works with `HOME`- or Documents-based preference directories, uses a version-neutral python directory, admits a Houdini version *range* that warns rather than blocks, and has no manifest, DPAPI, token transactions or environment publication.
9. **Use MCP idioms.** Return tool failures as `isError` results with a typed `kind`/`retryable`/`hint`. Shrink `tools/list` (fewer, composable tools plus Python exec; move examples to resources). Add progress notifications for tasks, or at least a polling resource.
10. **Restructure code and tests for change.** Replace the 28-mixin class with a tool registry of small modules. Drop the line-count cap in favour of cohesion. Write focused unit tests for dispatcher, shim and session ops, including UI-mode re-entrancy and timeout cases. Add CI. Collapse `HOCUSnnn` into a small documented `kind` enum.
