# Changelog

This project uses [Semantic Versioning](https://semver.org/). The 0.9 compatibility
policy does not apply to 1.0.

## 1.2.1 (2026-10-12)

### Fixes

- **`install-houdini` installs into every pref dir Houdini may use.** On Windows,
  Houdini 22 started from the Start menu (no `HOME` variable) uses
  `%USERPROFILE%\Documents\houdini22.0`, while one started from a shell that sets `HOME`
  (Git Bash, some terminals) uses `%HOME%\houdini22.0`. 1.2.0 wrote the package JSON only
  to the directory hython reported from the shell `install-houdini` ran in, so a Houdini
  started the other way never loaded HocusPocus. `install-houdini` now collects every
  candidate (`--prefs`, `HOUDINI_USER_PREF_DIR`, hython's answer with and without
  `HOME`, the existing `~/houdiniX.Y` and `~/Documents/houdiniX.Y`), deduplicated by
  real path, and writes the package JSON (and, without `--dev`, the copied package) into
  each one that exists. It creates only `--prefs` (or, when no candidate exists, the
  first). It prints each location and records them all in `<state_dir>/install.json` as
  `pref_dirs` (`prefs` stays, holding the first).
- **`uninstall-houdini`** removes the package from every recorded and candidate pref dir.
- **`doctor`** lists each candidate pref dir with whether its package JSON is present and
  current, and warns when they disagree, naming the `install-houdini` command to run.
- **The bridge** reads `hocuspocus.toml` from the first candidate that has one: the
  recorded `pref_dirs` in order, then the default locations. `HOUDINI_USER_PREF_DIR`,
  when set, is still the only place it looks.

## 1.2.0 (2026-10-12)

Before 1.2 the real workloads were all SOP work. In 1.2 the `full` profile (`usd_stage`,
`pdg`, `hda`, `events`) and the GUI-only paths (viewer capture, selection, undo next to
a user) got their first real workloads. These were a Solaris lookdev of the city rendered
with Karma (`docs/redesign/review/13-solaris-lookdev-eval.md`), a PDG wedge driven
through `pdg`, `job` and `events` (`14-pdg-wedge-eval.md`), and a GUI session next to a
user with an HDA round trip (`15-gui-session-eval.md`). This release fixes what they
found, plus the review-12 leftovers (plan in `docs/redesign/plan-1.2.md`). A few results
and defaults change, so read **Upgrading from 1.1** if you have agent prompts or scripts
written against 1.1. Each contract decision is recorded in `docs/BIBLE.md` (decisions
D21 to D24).

### Contract changes

- **Shorter catalogue descriptions.** Each description is at most 60 words and no longer
  repeats defaults and enums that the schema states. Argument-level detail moved to a
  new `notes` field on each tool spec. `docs/tools.md` and the `hocuspocus://guide`
  resource render the notes, and `tools/list` leaves them out. The `full`-profile
  `tools/list` with output schemas declared went from 44.0 KB to under 40,000 B, and a
  unit test keeps it there. No tool or argument was removed.
- **Annotations omit MCP defaults.** Hints equal to the MCP default are no longer sent:
  `readOnlyHint: false`, `idempotentHint: false`, and `destructiveHint` and
  `idempotentHint` on read-only tools. A client reads the missing hints as the same
  values.
- **`events`.** Every event carries `origin: agent|other`. The host holds an agent call's
  events until the call's work ends. A call that fails and is rolled back records
  nothing, and neither does a node created and deleted within one call or a tool's own
  set and restore.
  - New event kinds:
    - `SpareParmsChanged`: one per spare parm edit, instead of a burst of
      `ParmTupleChanged`.
    - `kind: "pdg"`: `cook_start`, `work_item_failed` and `cook_done`.
    - `hda_contents_rebuilt`: one per asset for `hda create`, `match` and `unlock`,
      instead of one event per internal node.
  - `FlagChanged` names the changed flags in `detail.flags`. The empty `FlagChanged`
    that a spare parm edit used to send is dropped.
  - Nodes read with `node_info` or listed by `network_describe` are watched too.
  - Nested nodes created in one batch get their `ChildCreated`.
  - Houdini's save-time writes on TOP networks are dropped.
- **`undo` stops at user steps.** `undo` and `redo` stop at the first step whose label
  does not start with `HocusPocus:`, which is a step by the user or by Houdini. The
  result names that step in `blocked_by` and explains in `note`.
  `include_user_steps: true` crosses such steps and lists them in `user_steps`.
- **`pdg cook` refuses unsaved hips for out-of-process graphs.** ROP Fetch and the other
  out-of-process ROP TOPs load the hip on disk. In 1.1, a cook with unsaved changes
  cooked the old scene without a warning. When the graph has such a node, `cook` now
  refuses an untitled scene or unsaved changes with `unsaved_changes`. `save: true`
  saves first, and `approved_roots` apply. In-process graphs cook as before.
- **`hda save` promotes spare parms.** With `promote_spare_parms` (default true), the
  instance's spare parms become part of the definition's interface, values included,
  and `promoted` lists them. In 1.1 they stayed on the instance, and `node_type_info`
  showed no parms. `promote_spare_parms: false` keeps the 1.1 behaviour.
- **`render` on USD render ROPs.** For `Lop/usdrender_rop` and `Driver/usdrender`, the
  outputs come from `outputimage`. When that is empty, they come from the `productName`
  of each RenderProduct of the render settings the ROP uses, per frame. They are never
  `lopoutput`, which is husk's intermediate file.
  - `output` overrides `outputimage`.
  - A `note` says when no output resolves.
  - A husk failure carries the last lines of its log in `detail.log_tail`.

  In 1.1 these ROPs returned `outputs: []` and no thumbnail.
- **`viewport_capture` leaves the GUI view as it was.** The viewer path saves the view
  and the camera the viewport looked through. It puts both back after looking through
  `camera` or after an explicit `fit`.
  - An explicit `fit` now frames all or selected for the grab. 1.1 ignored `fit` on the
    viewer. `fit_used` says what was done.
  - With a `camera` or a stage, `auto` uses the OpenGL ROP.
  - Every result says `scene: obj|stage`.
  - In the GUI, `context` names the viewer's network, and a note says when that is not
    the captured scene.
  - Lights are refused as cameras, and camera errors list the scene's cameras as
    `candidates`.

### Added

- `viewport_capture` captures LOP stages. `camera` takes a LOP camera node or a camera
  prim path, and the new `lop_path` names the stage. A framed stage gets a temporary
  camera LOP. With neither `camera` nor `lop_path`, the `/stage` display LOP is captured
  when `/obj` displays nothing; otherwise a note names it. Stage captures work both
  headless and in the GUI.
- `usd_stage {summary: true}` returns `{total_prims, counts_by_type, bbox_world}` for the
  whole subtree in a few hundred bytes.
  - `total` is on every page. It comes from a counting walk capped at 100,000 prims,
    which sets `total_capped` when the cap is reached.
  - `attribs` (a name glob, `a|b`) filters attributes.
  - Arrays of up to 4 elements (8 for strings and tokens) are listed whole.
  - `world` is left out when it equals `local`.
- On LOP nodes, `parm_get`, `parm_set` and `node_create` `parms` accept USD attribute
  names such as `inputs:intensity`. The host resolves them to Houdini's encoded parm
  name (`xn__inputsintensity_i0a`), and the result carries the resolved path.
- `pdg workitems` gains three fields:
  - `attribs: [names]` returns each item's attribute values.
  - A `state` filter takes `failed`, `cancelled`, `success`, `cache`, `cooked` or a
    state name.
  - Each item reports `cook_time_s`.

  Output files are relative to one `output_root` per page.
- A failed PDG work item carries `error`, `log_path` and `exit_code`. `error` holds the
  last error lines of the item's log, at most 400 characters. A cook result has
  `ok: false` when any item of the graph failed, and lists the first 5 `failures`.
- `pdg {action: "cook", save: true}` saves the hip before cooking.
- `houdini_connect {quit: true, on_unsaved: fail|save|discard, pid?}` closes a Houdini
  through its host, using the new route `POST /hp/v1/quit`. It returns `{quit, pid,
  exited, saved?}`. In 1.1 the only way to close Houdini was `hou.exit` in
  `houdini_python`, which answered `python_exception`.
- `cook {profile: true}` attributes time inside for-each loops.
  - Each `block_end` is force-cooked under the performance monitor.
  - Body rows get `in_loop`, `cooks`, `per_iteration_ms`, and `cook_time_ms` over all
    iterations.
  - `loops` lists each loop with its `iterations` and `total_ms`.
  - `attribution` is `per_node`, `perf_monitor`, or `loop-level` when the monitor was
    unavailable.
- `network_describe {format: "outline"}` rows carry `inputs` and `flags`. `inputs` is the
  source path per input slot, and `flags` lists the flags that are on. Both are left out
  when empty.
- `node_edit` spare `menu` parms take `value_type: "int"`, which makes an int parm whose
  value is the item index (`ch()`/`chi()`). The default `string` menu's value is the
  token (`chs()`).
- `hocuspocus launch --work-dir DIR` starts Houdini in `DIR`. Without the flag, the
  launched Houdini now starts in the directory the command runs in, so the untitled
  scene's `$HIP` and `$JOB` are that directory, not home. `houdini_connect {launch}`
  keeps the `HOCUSPOCUS_WORK_DIR`/home rule.
- `viewport_capture` writes an opaque PNG, both in the captures dir and at `path`. The
  image is composited onto the same grey as the inline image. In 1.1 the file kept the
  OpenGL ROP's transparent background, which most viewers show as white.
- `node_type_info` with `folder` or `parms` (a parm lookup) returns `inputs_count`
  instead of the input list, and `detail: full` leaves out `folders`. On
  `mtlxstandard_surface`, the inputs had been 2.2 KB of a 3.3 KB answer.
- `node_info` on a TOP node adds `pdg_state: {cooked, failed, total}`.

### Fixed

- **Locked tuple components:** `parm_set` on a tuple failed the whole batch when one
  component was locked and computed by an expression, such as Karma's `resolutiony`
  under `res_mode: autoheight`. The hint suggested unlocking it through
  `houdini_python`. A component that already holds the requested value is now skipped.
  Otherwise the error names the component, its expression and its value, and the hint
  names the components to set instead.
- **`camera` in `/obj`:** `node_create {type: "camera"}` in `/obj` gave a hint that
  pointed at SOPs. The hint now says that Object networks spell it `cam`, and the
  candidates lead with `cam`.
- **HDA reporting:**
  - `node_type_info` and `node_type_search` showed an empty version and description for
    assets made with `hda create`. They now fall back to the definition's version and,
    when the asset has no help, its label. They spell the type `Sop/ns::name`.
  - `hda list` expands Windows 8.3 short paths such as `C:/PROGRA~1/...`.
  - `hda install` of an already loaded library says `already_loaded`.
- **Stale TOP cook state:** after an earlier PDG cook in the same session, a TOP node
  whose items had all cooked could still report `cook_state: "uncooked"`. `cook_state`
  now trusts the work items.
- **`problems` on TOP networks:** `problems` said "No problems" for a TOP network with
  failed work items. It now reports a `failed_work_items` row with the count and the
  first item's error.
- **PDG job progress:** a `pdg` cook job counted only the target's work items, so it read
  0/8 while upstream items were finishing. It now counts the whole graph and adds
  `nodes: {name: "finished/total"}`.
- **`pdg cancel`:** it returned the status from before the cancel, and the job then
  reported `done`.
  - It now also cancels the job cooking that graph.
  - It waits for the cook to stop and returns that status with `cancelled: true`.
  - A cook with cancelled items ends `cancelled`, never `done`.
- **Blocking `pdg cook`:** when it hands back a running job before `timeout_s`, `notes`
  now says that `job_threshold_s` capped the wait.
- **`usd_stage` on a render ROP:** for a render ROP in a LOP network, `usd_stage` said
  "is a Lop node, not a LOP". The error now says that the ROP has no output stage and
  names its input as the candidate.
- **`camera_used` after a viewer `fit`:** after a viewer `fit` from a camera view,
  `camera_used` named that camera, although the grab was of the framed free view. It
  now reads `viewport`.
- **`hou.exit` hint:** the `houdini_python` hint for `hou.exit` names
  `houdini_connect quit`.
- **`node_type_search` docs:** the docs now say that `total` is the real number of
  matching types, not a cap.
- **Headless stage captures crashed (review 16 N1).** A stage of more than a few
  thousand polygons crashed the capture's child hython (exit 139): the OpenGL ROP's LOP
  source updated the meshes in parallel and created the Vulkan device on a worker
  thread. A child that renders a stage now runs single-threaded. If the OpenGL child
  still crashes, `viewport_capture` renders the frame with a temporary Karma CPU ROP
  (2 samples, the same camera and resolution) and reports `source_used: "karma"` with a
  note. A crashed child's log in an error is cut to 600 characters: the fatal error and
  the crashing thread, without the idle thread stacks.
- **Duplicate `ChildCreated` events (review 16 N2).** After `network_describe` of
  `/stage` or `/obj`, the context manager was watched as a node too, and every
  top-level `ChildCreated` and `ChildDeleted` was reported twice. The manager's own node
  callback no longer records its children, and a child event that repeats one on the
  same path within 0.5 s, with nothing on that path in between, is dropped.
- **`usd_stage prim` alternation (review 16 N3).** `prim` now takes `a|b` like `attribs`:
  each alternative is a prim path or glob, and matches come back in stage order. A
  pattern such as `/city/bldg_00*|/city/ground` used to match nothing, silently. An
  alternative that is not a valid prim path is now `invalid_argument` with a hint, and
  so is an exact alternative that names no prim.
- **`render` thumbnails (review 16 N4).** An image output in a format the thumbnail
  cannot read, such as `.xyz`, came back with no thumbnail and no word why. A note now
  says so and lists the extensions the thumbnail reads.
- **Render failures said it three times (review 16 N7).** A failed render repeated
  Houdini's text in `message` and in two `detail.errors` entries. The error lines are
  now deduplicated: `message` carries the first, `detail.errors` only the others, and
  "The attempted operation failed." is dropped.
- **`raw` on numbers.** `parm_get` and `parm_set` returned `raw` as the value in text
  form (`"value": 1.8, "raw": "1.8"`, `"raw": ["430", "300", "430"]`), although the notes
  said it was left out when equal. `raw` is now compared after formatting the value and
  left out when it says nothing more.
- **`doctor` and a literal `houdini__HVER__` folder.** `doctor` now warns when a folder
  literally named `houdini__HVER__` sits next to the resolved pref dir (or is the
  unexpanded `HOUDINI_USER_PREF_DIR`): Houdini expands the token, so nothing in it is
  read. The warning names the folder Houdini does read.
- **`hocuspocus launch --hip` (review 16 N6)** said "$HIP of the untitled scene is
  <cwd>" although it had loaded the hip. It now names the hip it loaded.

### Upgrading from 1.1

An agent prompt or script written for 1.1 may need these changes:

- **`events` consumers:**
  - Expect `origin` on every event, and the new kinds `SpareParmsChanged`,
    `hda_contents_rebuilt` and `kind: "pdg"`.
  - Filter on `origin: "other"` to see only the user's changes.
  - After a spare parm edit you get one `SpareParmsChanged` instead of a burst of
    `ParmTupleChanged`. After `hda create`, `match` or `unlock` you get one
    `hda_contents_rebuilt` instead of one event per internal node.
- **`undo {steps: N}`** now stops before a step that is not HocusPocus's. Check
  `blocked_by`, and pass `include_user_steps: true` when you mean to undo the user's
  steps too.
- **`pdg cook` on an unsaved or untitled scene** fails with `unsaved_changes` when the
  graph has a ROP Fetch or another out-of-process ROP TOP. Call `hip_save` first, or
  pass `save: true`.
- **`tools/list` is smaller.** Argument rules that used to be in descriptions are now in
  `docs/tools.md` and `hocuspocus://guide`. A client that relied on description text
  for them should read the guide resource.
- **`hda save`** now promotes instance spare parms. Pass `promote_spare_parms: false` to
  keep them on the instance.
- **`hocuspocus launch`** starts Houdini in the directory the command runs in. Pass
  `--work-dir` to start it somewhere else.

## 1.1.0 (2026-10-12)

Measured on the review-08 city workload rebuilt headless (`docs/redesign/review/12-city-rebuild-1.1.md`): 58 tool calls instead of 74, 0 `houdini_python` calls instead of 2, `node_create` results about 10x smaller (172 B per node instead of ~1,690 B), `tools/list` 30.6 KB as the model sees it, and a Houdini started with `hocuspocus launch` that outlived every client session.

1.1 acts on the post-1.0 code review and ergonomics review (`docs/redesign/review/10`,
`11`; plan in `docs/redesign/plan-1.1.md`). Results are smaller by default, a few
ambiguous fields and error shapes are settled, long cooks report progress, and
`hocuspocus launch` starts a Houdini that no MCP client owns. Some result shapes change,
so read **Upgrading from 1.0** if you have agent prompts or scripts written against 1.0.
Each contract change is recorded in `docs/BIBLE.md` (decisions D16 to D20).

### Contract changes

- **Summary results by default.** `node_create`, `node_copy` and `network_build` default
  to `return: "summary"`: per node `path`, `type`, `errors`, `warnings` and `cook_state`,
  with a repeated error list shortened to `errors_same_as`. `return: "full"` gives the
  1.0 blocks, but `node_create` now lists only the parms the call set (values a node's
  creation script set, such as a light's ramps, are no longer reported as edits) and
  elides strings over 200 characters as `{elided, head}`.
- **`locked` vs `hda_locked`.** `locked` is always a lock flag: the SOP hard-lock
  (`node_info` flags) or the parm lock (`parm_get`). Being a locked asset or inside one
  is `hda_locked`, in `node_info`, `network_describe` (locked children appear as
  `{type, hda_locked: true}`), `parm_get` and `hda`.
- **Parm rows are leaner** (review 12 papercut 1). `parm_get`, `parm_set` and the
  `node_info` parm rows leave out `raw` when it equals `value`, and show string values
  over 200 characters as `{elided, head}`, as `node_create return: full` does. A
  `snippet` edit no longer echoes the whole VEX twice. `parm_get {full_strings: true}`
  returns long strings whole.
- **`node_type_search current_only`** defaults to true: every version of a type folds
  into its current version's row, which names the rest in `other_versions`.
  Descriptions are clipped to 120 characters. `current_only: false` lists each version.
- **`render` output lists.** Above 5 outputs only `outputs_summary`
  (`{count, first, last, pattern, missing_count}`) is inline; `job result` returns the
  full list. Without `wait_s` the call now waits `job_threshold_s` (default 10 s)
  instead of a fixed 20 s.
- **`houdini_python` exceptions are errors.** An uncaught exception (`SyntaxError` and
  `SystemExit` included) is an `isError` result with the new code `python_exception`:
  the message is `<type>: <text>`, `detail` carries `stdout`, `stderr`, `traceback` and
  `rolled_back`, and the code's scene changes are undone. In 1.0 this was a successful
  result with `ok: false`.
- **Results are sent once, as text.** The bridge setting `result_content` (toml key or
  `HOCUSPOCUS_RESULT_CONTENT`) defaults to `text`: compact JSON in the text block only,
  no `structuredContent`, and no `outputSchema` in `tools/list`. `both` is the 1.0
  shape; `structured` puts the data in `structuredContent` and a one-line summary in the
  text block. Errors follow the same setting; images are image blocks in every mode.
- **The host enforces `profile`.** A host running the `core` profile refuses `hda`,
  `usd_stage`, `pdg` and `events` with `invalid_argument` and a hint to set
  `profile = "full"`. In 1.0 only the bridge's tool listing depended on it.
- **One batch error shape.** `node_create`, `node_edit`, `node_connect` and `parm_set`
  errors (and each failed row's `error` with `partial`) read `items[i] (<path>): ...`
  with `detail: {item, path, rolled_back}`. `rolled_back` is true only when every change
  was actually undone; `parm_set` now restores earlier items itself.

### Added

- `cook {profile: true}` force-cooks the input chain in dependency order, one
  main-thread step per node, and returns the costliest ten as `chain` with
  `chain_total` and `total_ms`. A forced cook under 1 ms on a node with inputs hints at
  `profile`.
- `cook {frame_range: [start, end, step]}` cooks one frame per main-thread step (a sim
  advances, the GUI stays responsive, the current frame is restored) with progress and
  `message: "frame n/N"`; `summary: "bbox"` adds per-frame point and prim counts and
  bounding boxes.
- MCP progress notifications: when a client sends a `progressToken`, the bridge polls the
  jobs the call started (new host route `GET /hp/v1/calls/{request_id}/jobs`) every
  0.5 s and sends `notifications/progress`. Polling never fails the call.
- Job snapshots carry `current`, `total` and `message` next to `progress` (0..1);
  `cook` and `pdg` (finished work items) fill them.
- `node_edit` `spare_parms: {add: [...], remove: [...]}` adds float, int, string,
  toggle, menu, button, vector and color spare parms (label, default, size, range, menu
  items, folder, help) or removes spare parms, with rollback. `parm_not_found` on a
  `null`, `subnet` or `geo` points at it.
- `node_create` pairs a new `block_end` with its `block_begin` (the nearest one upstream,
  else the only unpaired one in the network) as the Tab menu does; the row carries
  `paired_with`.
- `network_describe {format: "outline"}`: a compact tree of path, name, type,
  `children_count` (left out at 0), display node, error count and `hda_locked` (only for
  locked assets not shipped with Houdini, so wrangles are not flagged), two levels deep
  by default and paged at the response budget. The resource `houdini://outline` returns
  it for the whole scene.
- `node_type_info` takes `folder: "(no folder)"` or `""` for a type's top-level parms
  (every name `detail: folders` lists is now accepted), and `parms: "dist|inset"` matches
  either glob (review 12 papercut 2).
- `hocuspocus launch [--headless] [--hip FILE] [--wait N] [--hfs DIR]` starts GUI
  Houdini or a headless hython host, waits for it to register, prints its registry entry
  as JSON (never the token) and exits. That Houdini belongs to no MCP server and outlives
  every client; attach with `houdini_connect {pid}`.
- `houdini_python` has a deadline: a `sys.settrace` hook stops Python code shortly
  before `timeout_s`, reported as `houdini_busy` with `detail.started` and `stopped`
  true, so `while True:` no longer wedges Houdini. A single long C call (a cook,
  `time.sleep`) still cannot be interrupted.
- `render` `notes` warn when the scene has no lights and when the thumbnail is nearly
  black. `node_type_not_found` candidates lead with known other names (`distantlight` is
  `hlight` in /obj).

### Fixed

From the code review (`docs/redesign/review/10-code-review.md`):

- Stale registry entries on pid or port reuse: an entry whose pid is alive but whose
  port refuses, rejects the token or answers `/health` with another pid is deleted, and
  the bridge selects again (`houdini_status`, `houdini_connect`, forwarded calls,
  `doctor`).
- Executor timeout race: work that finishes between the wait timing out and taking the
  lock returns its result instead of "still running".
- Host HTTP: idle connections time out after 60 s, and a non-loopback `Host` header is
  refused with 403 (DNS rebinding).
- Argument validator: `enum` and `const` compare JSON values (`true` is not `1`), and
  integral floats such as `50.0` are coerced to int where the schema says integer.
- Undo: labels are ASCII and at most 100 characters, and `rolled_back` reports whether
  the undo actually ran.
- Install and uninstall: `install-houdini --dev` removes earlier copied installs and
  `doctor` flags leftovers; `uninstall-houdini` reports a locked install instead of a
  traceback; the package JSON and install record are written atomically. A launch
  resolves a relative hip before starting Houdini, and a headless launch accepts only
  its own pid.
- `parm_set` and `parm_get` take an int menu parm's `menu_token` from its menu items
  rather than reporting its index.
- `geo_read` reads a page's rows on their own instead of building whole attribute
  columns (below a quarter of the class, without `stats`).
- `pdg` uses the dispatcher's timeout and the shared read-only refusal.
- Duplicated helpers are shared through `host/tools/_common.py`, the host and bridge
  response truncators are one module (`tools/budget.py`), and dead code is removed.
- Tests: the e2e bridges no longer read the user's real pref dir, and the executor
  timeout test no longer races the pump.

### Upgrading from 1.0

An agent prompt or script written for 1.0 must change:

- Pass `return: "full"` to `node_create`, `node_copy` or `network_build` where it read
  the 1.0 per-node echoes (flags, parms) from the result.
- Read `hda_locked`, not `locked`, to tell whether a node is or is inside a locked
  asset; in `parm_get`, `locked` is now only the parm lock.
- Expect `houdini_python` failures as `isError` results with `code: python_exception`
  (traceback in `detail.traceback`) instead of a successful result with `ok: false`.
- Read `value` where `raw` is missing (it equals `value`), and pass
  `parm_get {full_strings: true}` to read a string over 200 characters whole.
- Pass `current_only: false` to `node_type_search` to get each version as its own row.
- Read `outputs_summary` (or `job result`) from a `render` with more than 5 outputs.
- Set `result_content = "both"` (or `HOCUSPOCUS_RESULT_CONTENT=both`) if a client reads
  `structuredContent` or relies on `outputSchema`.
- Set `profile = "full"` for the host as well as the bridge (in `hocuspocus.toml`, which
  both read, or in Houdini's environment) to use `pdg`, `hda`, `usd_stage` and `events`.
- Start the Houdini a one-shot script drives with `hocuspocus launch` rather than
  `houdini_connect {launch}`, which ends with the script's bridge.

## 1.0.0 (2026-10-12)

Merged to `master` in PR #7 on 2026-10-12 and tagged `v1.0.0` after the post-merge review.

### Summary

- A stdio MCP bridge (`hocuspocus-mcp`, official `mcp` SDK) outside Houdini and a
  stdlib-only host inside Houdini (GUI or `hython`), talking `hp/v1` over loopback HTTP
  with a token per instance.
- 35 tools in Houdini vocabulary, 31 in the default `core` profile, each mutating call
  one undo group, errors with a stable `code`, `hint` and `candidates`.
- Three-command install: `uv tool install -e .` (from a checkout; not on PyPI yet),
  `hocuspocus install-houdini [--dev]`, `claude mcp add -s user hocuspocus --
  hocuspocus-mcp`; `hocuspocus doctor` checks the result.
- Tested in three tiers: unit (system Python), integration (inside hython) and e2e
  (stdio bridge driving a hython host), plus a manual GUI smoke and three agent
  evaluations (`docs/redesign/review/07`–`09`).
- The 0.9 tree is removed and preserved at the git tag **`v0.9-archive`**.

### Post-merge review fixes (included in 1.0.0)

Two code reviews and an ergonomics review (`docs/redesign/review/10`, `11`) ran after the
merge; the fixes landed before tagging:

- `houdini_python` survives `sys.exit()`/`KeyboardInterrupt` and reports them; results carry `ok`.
- `pdg cook` never holds the main thread past its timeout (always a job); `pdg` respects `read_only`.
- `render` checks every output path against `approved_roots`; always returns `state`.
- Headless capture child sets fps before loading, carries hscript globals and `hou.session`.
- `viewport_capture` waits for the child off the main thread; `problems` has a time budget and cursor.
- `geo_info`/`geo_read` refresh stale node errors like `cook` does.
- `node_type_info` reports all outputs of multi-output HDAs, mutes its probe node, adds `parms` filter and `detail: folders`.
- `hip_merge`/`network_build` `dry_run` no longer dirty the scene; `approved_roots` expand `$VAR`/`~` and compare real paths.
- `node_find` refuses a locked-asset root, pages by path cursor; `node_info` lists multiparm counts and `hda_locked`.
- `node_create`/`node_copy`/`network_build` accept `return: summary`; long code strings are truncated in results.
- Launch lifetime is visible: `launched.outlives_server`, `launched_by` in the registry, and a named hint when a launched Houdini is gone.
- Headless launch never puts a site-packages dir on hython's `PYTHONPATH`.
- The bridge sends `max_response_bytes` to the host; paged results keep correct cursors.
- Registry writes retry on Windows share violations; stale pruning only on a provably dead pid.
- CLI snippets use `claude mcp add -s user`; budget test measures the real `tools/list` (44 KB cap).

### Known limitations

- **Launch lifetime.** A Houdini started by `houdini_connect {launch}` exits when the
  bridge that launched it exits (end of a client session, or a one-shot script). Save
  with `hip_save` first, or attach to a Houdini you started yourself.
- **Windows only qualified.** 1.0 is tested on Windows with Houdini 22.0.466. The code
  is not Windows-specific, but Linux and macOS are untested.
- **GUI viewer capture needs a homed view.** `viewport_capture` with `source: viewer`
  (the GUI default) captures the view as it is and ignores `fit`. Home the view first
  or use `source: opengl_rop`.
- **Headless OpenGL capture runs in a child hython**, about 3 s per capture or OpenGL
  render, because a second OpenGL render in one hython process crashes 22.0.466.
- **`node_type_info` is large for big HDAs.** The compact view of RBD and similar
  assets is 10 to 26 KB; filter with `folder`.

### Details

1.0 is a rewrite and a clean break from 0.9. Scenes made with 0.9 are ordinary Houdini
scenes and still open. Any `hpmcp.*` userData that 0.9 left in a scene is ignored. The
complete 0.9 tree is kept at the git tag **`v0.9-archive`**: HocusScript, network
documents, source workspaces, production qualification, and all of its docs and scripts.

### Why

The 0.9 reviews (`docs/redesign/review/01`–`06`) found that agents paid about 25k tokens for 103 listed tools before any work, and that the only listed way to change a parm was a network-document checkout that grew to megabytes.
HocusScript was 57% of the code and nobody used it outside fixtures, no tool was ever tested against a real Houdini, and first use failed on the installed Houdini after about nine manual steps.
1.0 therefore keeps a small surface of tools in Houdini's own vocabulary, runs the official MCP SDK outside Houdini, and tests every tool inside hython.

### Removed, and what replaces it

| Removed in 1.0 | Use instead |
|---|---|
| HocusScript, `.hocus` files, the HocusScript compiler, lock/project/bundle schemas | `network_build` with Houdini's native `hou.data` format (read it back with `network_describe`), or `houdini_python` |
| Network documents (checkout / validate / diff / apply) | Direct primitives: `node_create`, `node_edit`, `node_connect`, `parm_set`, `network_build` |
| Source workspaces, workspace grants, and the "Source Workspaces" Python panel | Nothing. Agents edit files with their own tools. |
| Production qualification: HS8/RC release ceremony, attestation, install manifests, the source-admission import finder | Normal pip/uv integrity plus `hocuspocus doctor` |
| `scripts/build.ps1`, `build_transaction.ps1`, `install_hocuspocus_mcp_client.ps1`, the 676-line governed stdio launcher | `uv tool install`, `hocuspocus install-houdini`, `claude mcp add -s user hocuspocus -- hocuspocus-mcp` |
| Hand-written MCP protocol code inside Houdini, and the fixed port 37219 with a shared token | `hocuspocus-mcp` bridge on the official `mcp` SDK; a stdlib-only host on an ephemeral loopback port with a token per instance |
| Exact pin to Houdini 22.0.368 | Houdini `>= 22.0`; untested builds get a warning, not a refusal |
| 103 listed tools with dotted names (`node.create`, `scene.get_summary`, …) | 31 `core` tools (35 in `full`) with snake_case names; see `docs/tools.md` |
| Result redaction (`"<redacted>"` in place of hip paths, save paths and long strings) | No redaction. Real paths are returned. |
| `python3.11libs/`, `package/`, `config/`, `python_panels/`, `editors/` (TextMate grammar), the old `toolbar/` | `src/hocuspocus/` plus the `houdini/` package payload, including a Status/Start/Stop shelf |
| The 0.9 `unittest` scenario suite and its helper modules, and `docs/schemas/` | pytest in three tiers: `tests/unit`, `tests/integration` (in hython) and `tests/e2e` |
| Roadmaps, trackers, the user manual and the 0.9 specs under `docs/` | `README.md`, `docs/quickstart.md`, the generated `docs/tools.md`, `docs/BIBLE.md`, `docs/CONTRIBUTING.md` |

### Added

- 35 tools in Houdini vocabulary across these areas: session and instances, hip
  lifecycle with safe handling of unsaved work, nodes and networks, parms (tuples,
  expressions, keyframes, menus, ramps), cook and problems, geometry reads with stats,
  viewport capture and render (returning an image), the `houdini_python` escape hatch,
  node type search and info, undo, time, selection, jobs, and in the `full` profile
  HDA, USD stage, PDG and events.
- One labelled undo group for each mutating call.
- Errors as `isError` results with a stable `code`, a `hint` and `candidates`.
- An instance registry. Several Houdinis can run at once, and the bridge can launch GUI
  or headless Houdinis. `tools/list` works with no Houdini running.
- MCP resources (`houdini://…`, `hocuspocus://guide`), prompts, and server
  instructions.
- `hocuspocus` CLI commands: `install-houdini`, `uninstall-houdini`, `doctor`,
  `client-config`, `docs tools`, `version`.
