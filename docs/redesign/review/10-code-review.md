# 10 — Post-merge code review of HocusPocus 1.0

**Date:** 2026-10-12. **Scope:** `src/hocuspocus/**` (host, bridge, tools, CLI), `houdini/`, `tests/**` at
`master` 8b92569. **Authority:** `docs/BIBLE.md` (§ references below). **Method:** read every
infrastructure module (executor, dispatch, server, jobs, registry, runtime, undo, config, budget,
bridge client/server/instances/launch/validate/budget/config, CLI); three parallel read-only passes
over the tool families (parms/nodes/network; cook/_diag/geo/visual/types;
hip/session/code/state/hda/usd/pdg/events), spot-checked here; targeted experiments in plain
Python. hython was not run, and no real Houdini prefs, port 37219 or user processes were touched.
`ruff check`, `ruff format --check` and `pytest tests/unit` (295 passed, 1 skipped, 9.8 s) are
green.

Severity: **High** means it breaks a BIBLE guarantee or loses data or state in normal use.
**Medium** means it is wrong in a plausible situation, or is a robustness gap. **Low** covers
papercuts, consistency and cleanup. Estimate: **S** is under 2 h, **M** is half a day to a day,
**L** is more. "Verified" means reproduced by an experiment. "Read" means confirmed by reading the
code. "Speculative" means it depends on `hou` behaviour that was not run.

---

## Top 10

| # | Sev | Finding | Where | Est |
|---|---|---|---|---|
| 1 | High | A headless `houdini_connect {launch}` from a normal (non-editable) install puts the bridge venv's whole `site-packages` on hython's `PYTHONPATH`. That shadows SideFX's `attrs`/`click`/`cryptography`, which §3.1 and D13 forbid. | `bridge/launch.py:91-93, 208-210` | S |
| 2 | High | `houdini_python` lets `SystemExit`/`KeyboardInterrupt` escape. `exit()` in agent code stops the headless host (hython exits) and the bridge sees `delivery_unknown`. | `host/tools/code.py:93`, `host/executor.py:237-244` | S |
| 3 | High | When the bridge budget cuts a paged list, it keeps the host's `next_cursor`. Following the cursor silently skips the cut rows (verified: `node_find limit=1000` keeps 96 rows and the cursor says `"1000"`). | `bridge/budget.py:95-125`; `host/tools/nodes.py:882`, `cook.py:474`, `usd.py:355`, `pdg.py:292`, `hda.py:329,352` | S |
| 4 | High | `approved_roots` leaks. `render` without `output` never checks the ROP's own output parm. `hda list` skips the check. Roots are compared lexically (no `realpath`, and roots are not `$VAR`/`~`-expanded). | `host/tools/visual.py:818-836`, `hda.py:322-325`, `hip.py:44-63` | S |
| 5 | High | `pdg` ignores `read_only` (cook/dirty/cancel all run), and `pdg cook block:true` holds the main thread for the whole cook with no job and no cancel. | `host/tools/pdg.py:256-309` | M |
| 6 | High (needs hython confirm) | The child hython for headless OpenGL renders calls `hou.setFps(fps)` with default args *after* loading the snapshot. Keys are retimed for non-24 fps scenes, so headless captures and renders show the wrong animation. | `host/tools/visual.py:190-195` (`_CHILD_SCRIPT`) | S |
| 7 | Medium | Headless `viewport_capture` waits on the child hython on the main thread for up to `CHILD_TIMEOUT_S = 600`. Past `timeout_s` every tool is `houdini_busy` for up to 10 min. | `host/tools/visual.py:65, 354-366, 622, 692` | M |
| 8 | Medium | `dry_run: true` on `network_build` and `hip_merge` goes through the mutating dispatcher path. It marks the scene dirty (headless, the next `hip_new`/`hip_open` then fails with `unsaved_changes`), records an undo label and is refused in read-only mode. | `host/dispatch.py:156-176`; `network.py:543`, `hip.py:277` | S |
| 9 | Medium | On Windows, registry writes fail whenever a bridge is reading the entry (verified: `os.replace` raises `PermissionError` while a reader has the file open). `update()` changes the in-memory entry before writing, so the file stays stale for good. `prune_stale` deletes *live* entries it cannot momentarily read. | `host/registry.py:94-108, 131-149, 175-184` | S |
| 10 | Medium | Whole-scene walks on every page. `node_find` and `problems` walk the full subtree (with `errors()` and a per-parm scan) before applying `limit`/`cursor`. `node_find` also lists a locked HDA's internals when `root` *is* the asset. | `host/tools/nodes.py:806-885`, `cook.py:436-474` | M |

---

## 1. Correctness: infrastructure (host core, bridge, CLI)

### 1.1 High: headless launch exposes the bridge venv to hython (top-10 #1)
`launch.py:91-93` `package_root()` returns `Path(__file__).resolve().parents[2]`. In a checkout that
is `src/`. After `uv tool install hocuspocus` (the documented path, §10.2) it is the tool venv's
**`site-packages`**. `build()` prepends it to `PYTHONPATH` for `hython -m hocuspocus.host`
(`launch.py:208-210`). This repo's `.venv/Lib/site-packages` contains `attrs`, `click`,
`cryptography`, `pydantic_core` (cp312), `PIL`, `jsonschema` and `pywin32`, which are exactly
the packages review 04 showed shadowing SideFX's own. The e2e test that drives the real launcher
(`tests/e2e/test_stdio_roundtrip.py:158`) sets `PYTHONPATH=src` and runs from an editable
install, so it can never catch this.
**Fix:** for headless launch, point `PYTHONPATH` at the copy `install-houdini` made (the
`python_dir` in `<state_dir>/install.json`, written at `cli.py:278-298`). If there is none,
copy `package_dir()` (stdlib-only `hocuspocus/`) into a private dir under the state dir and use
that. Never use `site-packages`. Add a unit test that `build("headless")` never puts a dir
containing `mcp/` or `pydantic/` on `PYTHONPATH`. **S**

### 1.2 High: the bridge budget breaks pagination (top-10 #3)
`bridge/budget.py:95-125` `apply_budget` trims the largest list at item boundaries but leaves
the host's `next_cursor` alone. Every host cursor is `str(offset + limit)` (`nodes.py:124`,
`cook.py:474`, `usd.py:355`, `pdg.py:292`, `hda.py:329,352`), so the agent's next page starts
after rows it never saw. Only `geo_read` budgets itself on the host for this reason (`geo.py:34`).
Verified with 1,000 `node_find`-shaped rows at 16 KB: 96 rows were kept, `next_cursor` stayed
`"1000"`, and 904 rows were silently skipped. `truncated: true` is set, but nothing tells the
agent the cursor is wrong.
**Fix:** budget pages on the host, where `page()` lives. Give `nodes.page()` a
`max_bytes` that stops adding rows when the encoded size would exceed the budget, and emit the
cursor for the first row not returned, as `geo_read` already does. As a backstop in the bridge,
when it cuts the list that sits next to a top-level `next_cursor`, rewrite the cursor to
`int(request cursor or 0) + kept`. **S**

### 1.3 Medium: registry writes on Windows (top-10 #9)
- `registry.py:104` `os.replace(tmp, path)` raises `PermissionError [WinError 5]` while another
  process has `path` open. Verified with a plain-Python reader. The bridge reads every entry on
  every tool call (`instances.py:325-338`), and `_wait_exit` polls every 0.1 s, so collisions
  are realistic. At start-up (`runtime.py:149`) a failure aborts `host.start()`. On hip events
  (`runtime.py:296`) it is logged, but `update()` has already applied the change to
  `self._entry` (`registry.py:182`). The next update compares against the new in-memory values
  and skips the write, so the file keeps the old `hip`/`generation` until something else
  changes.
- `prune_stale` (`registry.py:141`) deletes an entry whose JSON it cannot read. A transient
  sharing violation therefore makes host A delete live host B's entry, and B becomes invisible
  to every bridge.
**Fix:** retry `os.replace` on `PermissionError` (for example 10 × 25 ms back-off). Commit
`_entry` only after a successful write. In `prune_stale`, take the pid from `path.stem`
(already required to be digits) when the body is unreadable, and delete only if that pid is
dead. **S**

### 1.4 Medium: no identity check against pid/port reuse
`Bridge.forward` (`bridge/server.py:176-198`) checks `/health` once per (pid, port, token)
for the `hp` version. It never compares `health["pid"]` with the registry pid. After a crash
(no `BeforeQuit`, entry left behind) the pid can be reused by an unrelated process, so
`pid_alive` is true and the entry survives every prune. The port can then be reused by another
HocusPocus host, which gives 401 → `houdini_offline` "stale" with no prune. The bridge and
`doctor` keep listing a ghost instance.
**Fix:** in `HostClient.health` callers (forward, `connected_block`, `doctor`), treat
`health.pid != inst.pid`, connection refused or 401 on a pid-alive entry as stale: delete the
file and re-select. **S**

### 1.5 Medium: executor timeout race reports a finished call as still running
`executor.py:152-157`: if the work finishes between `done.wait(timeout)` returning False and
the lock being taken, `state` is `"done"`, so `started` is True. The caller gets
`houdini_busy` "the call is still running; its result will be discarded" for a call that
completed. For a mutation that makes the agent inspect or repeat needlessly.
**Fix:** after taking the lock, `if work.done.is_set(): fall through to the result path`. Also
set `work.state = "done"` under `work.lock` in `_execute` (`executor.py:241`). **S**

### 1.6 Medium: `houdini_python` past its timeout wedges Houdini forever
This is the documented contract (`executor.py:133-141`), but nothing bounds it. A `while True:`
from the agent leaves every later call `houdini_busy` until a human kills Houdini, and in the
GUI the user's session is frozen.
**Fix:** in `run_python`, install `sys.settrace` (or `sys.setprofile`) with a deadline check
that raises a `TimeoutError` subclass once `timeout_s` has passed. It costs little for the
short scripts agents write. Report it as `exception` with a hint. **M**

### 1.7 Medium: undo rollback edge cases (`host/undo.py:56-78`)
- With undo disabled (`hou.undos.areEnabled()` false, or inside a `hou.undos.disabler()` the
  user or a shelf tool left active), `undoLabels()` is empty and a failing batch is **not**
  rolled back. The result still says `rolled_back` (nodes/parms add it unconditionally,
  `nodes.py:672-675`).
- `make_label` caps labels at 120 characters with a Unicode `…` (`undo.py:51-53`). If Houdini
  normalises or truncates labels differently, `after[0] == label` fails and the rollback is
  skipped silently. *Speculative*: no test uses a label over 120 characters.
**Fix:** have `hou_undo_group` record whether it rolled back (for example a flag on the
context object) and report that instead of assuming it. Keep labels ASCII and ≤ 100
characters. **S**

### 1.8 Low/Medium: HTTP server
- `_Handler` has no `timeout` (`server.py:93-96`). An idle keep-alive or slowloris connection
  holds a daemon thread for ever. It is local only, but cheap to bound: set `timeout = 60`.
  **S**
- There is no `Host` header check. With DNS rebinding a page can read `/hp/v1/health` (pid,
  version), because same-origin GETs carry no `Origin`. It exposes nothing secret, and every
  other route needs the token, but rejecting non-loopback `Host` values closes the gap for
  free. **S**
- The `/shutdown` body must have `Content-Length` (`server.py:133-137`), which is fine; only
  noted for completeness.

### 1.9 Low: bridge launch details (`bridge/launch.py`)
- A relative `hip` is checked against the **bridge's** cwd (`launch.py:220`) but loaded by a
  child whose cwd is `work_dir()` (`launch.py:190`, `host/__main__.py:218-221`). Resolve to an
  absolute path before both. **S**
- "Fresh registration" accepts *any* new pid (`launch.py:244-246`), so a GUI the user starts
  during the wait is taken as the launched instance. For headless (no hand-off) accept only
  `proc.pid`. **S**
- `launch.hip` bypasses `approved_roots`, because the bridge does not know them. Either say so
  in §3.7, or pass `--hip` through the host's check after start-up. **S**

### 1.10 Low: argument validator vs JSON Schema (`bridge/validate.py`)
- `enum`/`const` use Python equality, so `True` passes `enum: [0, 1]` and `1` passes
  `[true]` (verified). Compare with `_type_of(value) == _type_of(member)` as well. **S**
- `1.0` validates as `integer` (correct JSON Schema), but host checks such as `nodes.page()`
  (`isinstance(limit, int)`) then reject it with a different message. Coerce integral floats to
  `int` in the bridge before forwarding. **S**
- There are two validators with different coverage: `bridge/validate.py` (runtime, lenient,
  ignores unknown keywords) and `tools/docs.py:88` (examples, strict). Examples are validated
  only by the strict one. Add a unit test that runs every catalogue example and default through
  `bridge.validate` too, or keep one validator with a `strict` flag. **S**

### 1.11 Low: CLI pref dir and install
- `cli.platform_default_pref_dir` (`cli.py:119-127`) uses only `Documents\houdini22.0` on
  Windows, while `bridge/config.default_pref_dirs` probes `~\houdini22.0` first. The fallback
  repeats the 0.9 mistake §2 calls out, on this very machine. Probe both, prefer the one that
  exists, and share one function. **S**
- `install --dev` leaves an earlier copied `<prefs>/hocuspocus/<version>/` in place. A later
  non-dev install removes it, but `doctor` does not flag the leftover. **S**
- `uninstall` (`cli.py:321`) uses `shutil.rmtree(install_root)` with no error handling, so a
  file locked by a running Houdini gives a traceback. Catch `OSError`, report it and suggest
  closing Houdini. **S**
- `install` writes the package JSON non-atomically (`cli.py:268`). This is harmless but
  inconsistent with the registry. **S**

---

## 2. Correctness: tool families

### High
- **`houdini_python` and `SystemExit`** (top-10 #2). `code.py:93` catches `Exception` only.
  The executor deliberately re-raises `KeyboardInterrupt | SystemExit` on the main thread
  (`executor.py:237-244`), so headless `pump_forever` unwinds, `finally: stop()` runs and
  hython exits. The HTTP thread re-raises too (`dispatch.py:146-147`), so the bridge gets
  `delivery_unknown`. **Fix:** catch `BaseException` in `run_python` (report `SystemExit` as
  exception data with the hint "use `result =` instead of exit()"). **S**
- **`pdg` and read-only** (top-10 #5). `pdg.py:256` is `scene=False` with no `read_only`
  check, so cook (which writes files), `dirty` and `cancel` all run in read-only mode. Compare
  `visual.py:980` and `hda.py:384`. **Fix:** refuse cook/dirty/cancel when
  `ctx.config.read_only`. **S**
- **`pdg cook block:true`** (top-10 #5). `pdg.py:302-309` runs `cookWorkItems(block=True)`
  inside `executor.run`. After `timeout_s` the caller gets `houdini_busy`, the cook keeps the
  main thread, and `pdg cancel` (which also needs the main thread) cannot run. §4.7/§7 say
  "as a job". **Fix:** always start the non-blocking job and wait on `done_event` for
  `min(timeout_s, job_threshold_s)`, as `cook.py:120-123` does. **M**
- **`approved_roots`** (top-10 #4). `render` checks only an explicit `output`
  (`visual.py:829-830`). With `output` omitted, the ROP's own output parm (settable with
  `parm_set`) is never checked; check every entry of `expected` (`visual.py:833-836`). `hda
  list` with `library_path` (`hda.py:322-325`) skips both the roots check and the extension
  check; use `_library()`. `is_under` (`hip.py:44-50`) is lexical: no `realpath`, so a
  junction inside a root escapes. Roots are only `_norm`ed (`hip.py:54-63`), so
  `approved_roots = ["$JOB"]` or `["~/work"]` never matches anything, and relative roots
  resolve against the process cwd. `hip_save backup` (`hip.py:249`) writes to
  `$HIP/backup`/`HOUDINI_BACKUP_DIR` without a check. **Fix:** expand roots with
  `hou.text.expandString` + `expanduser`, compare `os.path.realpath` of both sides, and check
  every path a tool will write. **S**
- **Child render retimes keys** (top-10 #6; *needs hython confirmation*). `_CHILD_SCRIPT`
  (`visual.py:190-195`) loads the snapshot, then calls `hou.setFps(spec["fps"])`, whose
  default `modify_keyframes=True` retimes keys (§5.17). **Fix:** call
  `hou.setFps(fps, False, False, True)` *before* `loadChildrenFromFile`, as `time` does, and add
  a 30 fps keyed-transform capture test. **S**

### Medium
- **Headless `viewport_capture` blocks the main thread** (top-10 #7). It is registered
  `main_thread=True` (`visual.py:692`) and `render_isolated` waits up to 600 s
  (`visual.py:65, 362`). **Fix:** register `main_thread=False` like `render`, snapshot through
  `ctx.executor.run`, and wait off-thread bounded by `timeout_s`. **M**
- **`dry_run` dirties the scene** (top-10 #8). `network_build` and `hip_merge` are mutating
  tools, so the dispatcher (`dispatch.py:156-176`) opens an undo group, records a label, marks
  the scene dirty and refuses in read-only mode, even for a dry run. Headless, a clean scene
  then fails the next `hip_new`/`hip_open` with `unsaved_changes`. **Fix:** let the dispatcher
  treat `args.get("dry_run") is True` as read-only for tools whose catalogue entry has a
  `dry_run` property (no group, no dirty, allowed in read-only mode). **S**
- **Whole-scene walks** (top-10 #10). `node_find` (`nodes.py:806-885`) walks the whole subtree
  and calls `errors()`, flags, `inputConnections()` and `children()` on every node, every page,
  before `page()`. `problems` (`cook.py:436-474`) does `allSubChildren`, a per-parm
  broken-reference and missing-file scan, and optional cooks, then sorts and slices. On a big
  scene each page costs the whole scan on the main thread and can hit `houdini_busy` while
  the GUI freezes. `usd_stage` (`usd.py:290-313`) has the same shape. **Fix:** compute
  expensive columns only for rows on the returned page (or when filtered on), stop at
  `offset + limit + 1`, and give `problems` a time budget that returns
  `incomplete: true` + cursor. **M**
- **`node_find` on a locked HDA root** (top-10 #10). `_walk` seeds from `root.children()`
  (`nodes.py:807`), and the guard is `inside_locked(root)` (`nodes.py:840`), which is False for
  the asset itself. That breaks the §4.1 opacity rule. **Fix:** also refuse or skip when
  `_is_locked_hda(root) and not recurse_locked`. **S**
- **`geo_info`/`geo_read` bypass §5.18.** `geo.py:129-139` cooks via `sop.geometry()` before
  reading `errors()`, with no upstream refresh. After a fix made outside HocusPocus they report
  `cook_failed` with the stale error. The same applies to capture framing (`visual.py:411`
  `_world_bbox`). **Fix:** run `collect_problems(sop, cook=True)` (or
  `refresh_stale_inputs`) first. **S**
- **The host imports PIL** (`visual.py:107`), against the §3.2 stdlib-only rule. Houdini 22
  happens to bundle Pillow. If it is missing, every capture fails as `internal`, and
  `test_visual.py:19` (`importorskip`) silently skips the whole suite. **Fix:** either record
  Pillow as a known Houdini-bundled dependency in the BIBLE with a clear `internal` hint, or
  downscale with `iconvert`/ROP resolution and write the PNG with `zlib`. **M**
- **`node_type_info` probe nodes are not muted** (`types.py:672-690`). It creates
  `__hocuspocus_type_probe__` with `undos.disabler()` but not `events.muted()` (compare
  `visual.py:584`). As a result `events` logs ChildCreated/Deleted as user changes, the GUI hip
  becomes modified, and all of this happens from a read-only tool, also in read-only mode.
  **Fix:** wrap it in `muted()` + `_mark_internal`. **S**
- **`node_info` drops multiparm counts.** `_VALUELESS_TEMPLATES` contains `Folder`
  (`nodes.py:495, 511`), and a multiparm count *is* a Folder template, so a non-default
  `numattr` never shows. **Fix:** skip Folder only when `_kind(template) != "multiparm"`. **S**
- **`node_edit lock:true` runs first** (`nodes.py:1105-1112`). `matchCurrentDefinition()` runs
  before the name, color and flag validation. With `partial: true`, a later failure only calls
  `allowEditingOfContents()`, so the reverted content edits are lost. **Fix:** validate every
  field first and apply `lock` last. **M**
- **`network_describe depth > 1` is unbounded** (`network.py:179`). It serialises the whole
  subtree before trimming, with no byte or node cap. **Fix:** recurse level by level and stop
  at a budget with `truncated: true`. **M**
- **The child snapshot loses hip-level state** (`visual.py:244`). Only HIP/HIPFILE/HIPNAME/JOB
  are carried. Custom `set -g` variables and `hou.session` code are lost, so file paths
  resolve differently and geometry silently disappears in headless captures. **Fix:** carry
  `hou.hscript("set -s")` and the `hou.session` source, and list what was dropped in `notes`.
  **M**
- **The events ring can go silent** (*speculative*, `events.py:322-331`). `hip_busy` is set on
  BeforeLoad/BeforeMerge and cleared only by the After events. If a load or merge raises
  without an After event, node events are dropped for the rest of the session. **Fix:** reset
  it in a `finally` in `hip_open`/`hip_merge`. **S**
- **`allow_python = false` is not an off switch.** It gates only `houdini_python` and hscript
  (`code.py:121`). `parm_set {expression, language: "python"}`, `node_create` of a Python SOP
  with its `python` parm set, and `network_build` all still run arbitrary Python on the next
  cook. §1.10 promises "an off switch for Python". **Fix:** either refuse
  `language: python` expressions and writes to `PythonScript`-type parms when it is off, or
  (simpler and honest) document in §3.7 that it only disables the escape hatch. **S**

### Low (abridged; full detail in the sub-reviews' notes, line refs verified)
- `parm_set` catches only `(hou.OperationFailed, hou.InvalidSize, TypeError, ValueError)`
  (`parms.py:1153`), so other `hou.Error` subclasses become `internal`. `nodes.to_tool_error`
  (`nodes.py:638-666`) maps only `PermissionError`/`InvalidInput`, so `node.destroy()`,
  `copy.setName` and `matchCurrentDefinition` failures surface as `internal`. Map
  `hou.OperationFailed` to `invalid_argument`/`name_collision`. **S**
- `channel_ref` with a trailing slash can leave `target=None`, which raises AttributeError →
  `internal` (`parms.py:953-956`, *speculative*). **S**
- `press: 0` / `revert_to_default: 0` count as present (`parms.py:977` excludes only
  `is False`). Require `is True`. **S**
- A single `keyframe` with `animation: replace` keeps the existing keys
  (`parms.py:1078-1084`), but the catalogue says replace clears them. **S**
- The catalogue rejects `{ramp}`, `{channel_ref}` and `{keyframes}` inside `node_create.parms`
  (`catalog.py:156-165`), although `set_parm_items` supports them (`parms.py:1260-1266`).
  `node_connect`'s oneOf index/name (`catalog.py:463`) makes the list-position fallback
  (`nodes.py:984`) unreachable through the bridge. **S**
- `network_build replace` collides with NetworkBox and sticky-note names from `allItems()`,
  then calls `outputConnections()` on them → `internal` (`network.py:493-498, 561-605`).
  `from_index` is never validated, and duplicate `to_index` values are not detected
  (`network.py:345-367`). **S**
- `houdini_python` ignores `result` when the code ends in an expression that evaluates to
  `None` (`code.py:92`). A user exception inside the code is a *successful* call, so partial
  changes are kept with no `rolled_back` note. Say so in the result. Redirecting stdout/stderr
  process-wide (`code.py:89`) also captures other threads' prints. **S**
- The `hip_new` output schema declares `saved` but the code returns `saved_first`
  (`catalog.py:352` vs `hip.py:174`). **S**
- `_meta.undo_label` is null for mutating `scene=False` tools (hda, selection) and set for hip
  tools, which cannot be undone. Have the dispatcher take a tool-supplied label. **S**
- The render restore runs `executor.run(restore, 60)` in a `finally` (`visual.py:971`), so a
  busy main thread leaves the ROP output parm overridden outside undo. **S**
- `captures/` grows without bound (`visual.py:731`). Keep the newest N. A `viewport_capture`
  `path` can overwrite any file with PNG bytes when no roots are set (`visual.py:748-750`);
  require `.png`. **S**
- `geo_read` reads whole attribute columns for a 50-row page (`geo.py:509-539`), building GBs
  of temporaries on 10M points. Read per element when `stats` is false. **M**
- Missing-file detection treats any `$T…`/`$F…` substring as a frame token
  (`cook.py:159-171`), so `$TEMP/…` and `$FOO/…` are never checked. Use a regex. **S**
- `usd_stage` with a non-current `time` cooks the LOP at the current frame (`usd.py:114`;
  *speculative*). The `pdg` job can finish with `total 0` if the first poll precedes `cooking`
  (`pdg.py:236`; *speculative*). **S**
- A missing child hython gives `FileNotFoundError` → `internal` with no hint
  (`visual.py:277`). **S**

---

## 3. Robustness scenarios

| Scenario | What happens today | Gap / fix |
|---|---|---|
| Houdini crashes mid-call | The bridge gets `delivery_unknown`, watches 1.5 s for the pid to vanish, then reports `houdini_offline` "exited while running X" (`bridge/server.py:185-193`). The stale entry is pruned on the next scan. | Good. A crashed host leaves its entry if the pid is reused; see §1.4. |
| Two bridges, one host | Calls serialise on the main thread. Each bridge pins its own selection, and undo labels interleave. | Fine. The registry `PermissionError` window doubles (§1.3). |
| GUI modal dialog | `executor.run` returns `houdini_busy` with `started: false`, "the call had no effect" (`executor.py:166-171`). `/health` still answers. | Correct as long as `addEventLoopCallback` does not run during modal loops (not verified in the GUI). If it *does* run, `_draining` stops re-entry, but a tool could then run under a modal; add a GUI smoke item. |
| Very large scenes | `node_find`, `problems`, `usd_stage` and `network_describe depth>1` scan everything per call (§2). | Top-10 #10. |
| Long main-thread work | `houdini_python` loops, `pdg block`, and headless capture/render children keep the main thread past `timeout_s`. | §1.6, #5, #7. |
| Spaces / unicode paths | Paths go through `os.path`/`hou.text.expandString`. JSON uses `ensure_ascii=False` and UTF-8. Node names are ASCII by `NAME_RE`. | No defect found. `_compact_bytes` in nodes uses `ensure_ascii` and overstates the size of non-ASCII content (cosmetic). |
| Non-Windows | `pid_alive` is POSIX-guarded. `ensure_private_dir` uses chmod. Creation flags use `getattr`. Launch and test discovery cover darwin/linux. | `HOUDINI_USER_PREF_DIR` `__HVER__` is hard-coded to `22.0` in the bridge (`bridge/config.py:440`); fine for 1.0. No unguarded Windows-only code found. |

---

## 4. Simplification and dead code

- **Duplicated helpers:**
  - `pid_alive` and `_pid_alive_windows` exist in both `host/registry.py:44-91` and
    `bridge/instances.py:70-111`. The bridge copy lacks the `restype` for
    `GetExitCodeProcess`. The bridge can import the stdlib-only host module.
  - Node lookup exists four times: `nodes.get_node` (`nodes.py:199`, no strip),
    `_diag.require_node` (`_diag.py:217`, strip and candidates), `parms._node_not_found`
    (`parms.py:594`) and `geo._not_found` (`geo.py:68`, a different cutoff).
  - `instanceMessage` extraction exists in seven places (`dispatch.py:39`, `nodes.py:63,73`,
    `parms.py:91,103`, `_diag.py:176`, `hip.py:105`, `code.py:97`, `state.py:104`).
  - `time_block` has two different shapes (`session.py:106` raw, with no `playback_range`;
    `state.py:138` rounded), so `houdini_status` and `time` can report fps differently.
  - `_int_arg` exists three times (`geo.py:615`, `types.py:884`, `events.py:373`).
  - Cursor parsing is in `nodes.page` and inline in `cook.py:422-434`.
  - `hip._bool_arg` duplicates `nodes.arg_bool`.
  - `visual._fwd` duplicates `hip._norm`.
  - `pdg.py:267-274` re-implements `Dispatcher.effective_timeout`.
  - The read-only refusal text is copied into `dispatch.py`, `state.py`, `hda.py:384` and
    `visual.py:980`.
  - Two budget truncators, `host/budget.py` (used only by `code.py:137`) and
    `bridge/budget.py`, implement the same idea with different string handling.

  **Fix:** one `host/tools/_common.py` (node lookup, hou message, arg parsing, read-only
  guard, page with byte budget). **M**
- **Inconsistent error construction:** batch errors use the `"items[i]"` prefix and add
  `rolled_back` only for more than one item in `parm_set` (`parms.py:1350-1356`). Node tools
  use `"Item i:"` and always add `rolled_back` (`nodes.py:672-675`). Pick one. **S**
- **Config keys:** the host's `hfs` (`host/config.py:41`) has no reader on the host. The
  host's `profile` is reported but never enforced, so a `full` bridge can call `pdg` on a
  `core` host. `job_threshold_s` is read only by `cook`, while `pdg` and `render` ignore it
  despite §7. **S**
- **Unused code:** `UndoHistory.entries`/`.last` (`undo.py:114-120`); `.labels` is used only by
  tests. `MainThreadExecutor.busy`/`.pending` (`executor.py:246-251`).
  `events.watched_count` and `_HOOKS.watch_overflow` (written, never read).
  `types.index_stats` and `summarize_parm(detail="full")` are used only by tests. There are
  stale "filled by the parms task" comments at `nodes.py:501, 971`, and an
  `ok_or_skip_parms` stub in `test_nodes.py:10-16`.
- **BIBLE ↔ code:** §7 says the bridge emits progress notifications for jobs when a
  `progressToken` is given; `bridge/server.py` has none. Implement it, or drop the sentence.
  **S/M**

---

## 5. Test gaps

- **Launch in installed mode:** no test runs the launcher from a non-editable install (§1.1).
  Add a unit assertion on `build()`'s `PYTHONPATH`.
- **Budget plus cursor:** no test follows `next_cursor` after a bridge cut (§1.2).
- **Registry concurrency on Windows** (reader open during `update`), `prune_stale` with an
  unreadable live entry, and health pid mismatch.
- **`houdini_python`:** `sys.exit()`, `KeyboardInterrupt`, a timeout with `started: true`, and
  read-only refusal.
- **Read-only mode:** `pdg`, `render`, `hda`, and every `dry_run` path; dirty is unchanged
  after `network_build`/`hip_merge` dry runs.
- **`approved_roots`:** render with the ROP's own output, `hda list library_path`, roots
  containing `$VAR`/`~`, relative roots, junctions, Windows case variants, `hip_save backup`.
- **Headless capture/render** of an animated 30 fps scene; capture after an outside fix (§5.18).
- **`node_find`:** a locked HDA root, a cursor across scene changes, and a large-scene timing
  budget. `problems` with `cook_uncooked` over a DOP network.
- **`node_info`** with a non-default multiparm count. **`node_edit`** with `lock:true` +
  `partial`.
- **`parm_set`:** an expression with `animation: key/keep`, relative/python/self
  `channel_ref`, duplicate keyframe frames, int menus, free (StringReplace) menus, strict
  ranges.
- **`network_build`:** `from_index` out of range, `to_index` by name, `replace` against a
  NetworkBox name.
- **`events`:** a failed load followed by node events.
- **Flaky patterns:**
  - `tests/unit/test_host_executor.py:93-104` assumes the pump picks up work within 0.1 s; on a
    loaded CI runner `started` may be False. Use an Event the work sets instead of the
    timeout race.
  - `tests/integration/test_events.py:66-76` depends on the 0.1 s coalesce window.
  - `test_pdg.py:151, 171` poll for `cooking` inside 10 s.
- **Hygiene:** the unit and e2e tiers isolate `HOCUSPOCUS_STATE_DIR` and the Houdini pref dir
  correctly. The integration `conftest` refuses the real pref dir, and no test uses port 37219.
  One leak: `test_stdio_roundtrip` starts the bridge without `HOUDINI_USER_PREF_DIR`, so
  `BridgeConfig.load` probes the user's real `~/houdini22.0/hocuspocus.toml` (read only), and a
  personal `profile`/`max_response_bytes` changes the test's behaviour. Set the pref dir in
  that env too. **S**

---

## 6. Security posture (§1.10, §3.2)

| Item | Status |
|---|---|
| Loopback bind | `HostHTTPServer(app, "127.0.0.1", port)` (`runtime.py:134`). Nothing listens on a non-loopback address. The bridge client always uses `127.0.0.1`. OK. |
| Token | `secrets.token_urlsafe(32)` per instance, compared with `hmac.compare_digest` (`server.py:50-56`). It is never logged, never returned by any tool (`Instance.public()` drops it), and `status()` gives only the file path. On Windows the file relies on the `%LOCALAPPDATA%` ACL; a `HOCUSPOCUS_STATE_DIR` override to a shared dir would expose it (document this). |
| Origin | Every route rejects a present non-loopback `Origin`, including `null` (`server.py:39-47`). There is no `Host` check (§1.8). |
| Body cap | 4 MB, enforced before reading (`server.py:143-147`). OK. |
| approved_roots | Incomplete (top-10 #4): the render ROP output, `hda list`, backups, lexical compare, unexpanded roots and launch `hip`. |
| houdini_python gating | Enforced host-side and covers hscript (`code.py:121`). Python expressions and Python SOPs remain a bypass (§2 Medium); state that honestly. |
| read_only | The dispatcher covers scene tools. `pdg` is not covered (High). `node_type_info` probes still create nodes. |

---

## 7. What is solid

The executor's two backends with cancel-before-start semantics. The single dispatcher envelope
with rollback-on-failure. Atomic registry writes with private permissions. The never-retry
bridge client with its offline/`delivery_unknown` split and exited-pid diagnosis. `/health`
version gating. Catalogue-driven `tools/list` with a strict example validator. Child-hython
isolation (neutral cwd, `CREATE_NO_WINDOW` guarded, kill+wait, temp dir removed in `finally`).
A three-tier test suite with real hygiene guards. Most findings above are about edges of these
designs, not their shape.
