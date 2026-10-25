# Changelog

This project uses [Semantic Versioning](https://semver.org/). The 0.9 compatibility
policy does not apply to 1.0. 2.0 changes the tool surface; `compat_1x` kept the 1.4
one for the 2.0.x releases, and 2.1 removes it.

## 2.1.0 (unreleased)

### Added

- `look {output}` saves the picture to a `.png` or `.jpg`/`.jpeg` file: the capture at
  its rendered size, flattened onto grey, with `$HIP` and `~` expanded and parent folders
  created. The path is checked against `approved_roots` before anything renders
  (`path_not_allowed`), and the result names it as `output`. The image is still returned
  inline (review 26 P1 #3).
- `hocuspocus doctor` reports the licence state, parsed from `sesictrl diagnostic` (else
  `hserver -l`) next to the Houdini install. It shows ok, info or a warning with the
  sign-in hint, never a failure, and it now names a hython that could not get a licence.
- **HDA lifecycle without Python** (BIBLE §4.7, D47; review 26 P1 friction 1). `hda` is
  in the default `core` profile (19 tools) and gains `uninstall` (instances stay, each
  named with the definition it fell back to), `info` (library, version, sections, current
  or not, inputs, interface, instances, the instance's lock state), `interface` on
  `create` and `save` (the `spare_parms` shape, on `save` applied to any parm of the
  definition), `help` (the `HelpText` section), `lock: true` on `save` (relock after
  saving) and `label`, `version` and input counts on `save`. `list` and `info` only read.
- **Long string parms** (§4.5, D48; friction 2). An `edit` `set` takes `patch: [{find,
  replace, all?}]` to change a snippet in place (each `find` must occur exactly once; a
  miss is `invalid_value` naming the nearest lines) and `value_file` to set a string parm
  from a UTF-8 file (`approved_roots` apply). The result row says `patched_lines` or
  `value_file`.
- **Spare parm interface fields** (§4.5, D50; friction 7). `spare_parms` adds folder
  entries with `folder_type` (tabs, collapsible, simple, radio), nested `folder` lists,
  `before`/`after` placement, `disable_when`/`hide_when` (the parms they name are
  checked), `join_next`, `tags`, `callback`, `hidden`, `min_strict`/`max_strict`, string
  menus, `file`, `separator` and `label` types, and `change` entries that edit an
  existing spare parm in place.
- `path` names the node of every `edit` op (D49; friction 6): `create`'s new node, a
  `set`'s node with `parms`, `connect`'s `to`, `layout`'s and `build`'s `parent`, and
  `copy`'s, `select`'s and `delete`'s `paths`; a `node` op also takes `node`. The 1.4
  field names still work.
- `inspect {what: "guide", target?: topic}` and `inspect {what: "tool", target: name}`
  return the operating guide (or the section a topic names) and one tool's reference, the
  text of `hocuspocus://guide` and `hocuspocus://tools`, for clients without an MCP
  resource reader (Claude Code subagents). The bridge answers them itself, with or without
  a Houdini. The instructions name the route; hints that cite `hocuspocus://tools` now
  name `inspect {what: "tool", target: "<tool>"}` first (review 26 P1 #10, D54).
- `inspect {what: "node" | "geo", full_strings: true}` returns long strings whole: in
  node rows, and in geo detail attribute values (strings, arrays and dicts, otherwise cut
  at 200 characters or 16 items), and `inspect {what: "parms"}` of a node takes `folder` (the parms of one folder,
  defaults included) and `detail: "folders"` (the node's own parm folders, spare parms
  included). `full_strings` reads a 20 KB VEX snippet back in full; a result over the
  response budget comes back whole with `over_budget: true` (review 26 P1 #2, #9).
- `cook {profile: true}` lists the input ancestors it did not profile in
  `inactive: {count, paths}` (review 26 P1 #8, D53).

### Changed

- **A modal `hou.ui` dialog no longer blocks a GUI Houdini** (parity G5, BIBLE §3.2,
  D45). During a call in a GUI session the `display*`, `read*` and `select*` dialogs of
  `hou.ui` are stubs that raise `ui_required` naming the call (`detail.refused`), so
  `houdini_python` code, a pressed parm callback or a creation script that asks for one
  fails at once and is rolled back, where 2.0 answered `houdini_busy` and every later call
  waited until a person clicked. A hip load script's dialog is refused too, and `hip_open`
  reports it in `warnings` (the file is loaded). Houdini's own `hou.ui` is back between
  calls; headless nothing changes. The refusal is also a `SystemExit`, because Houdini
  answers any other exception from a parm callback with a blocking error window of its
  own. `ui_required`'s description says so.
- `houdini_busy` for a call that never started names "a dialog open in Houdini" and asks
  to have it closed if it keeps happening: measured, nothing HocusPocus sends runs while a
  user's modal dialog is open. The guide recipe "GUI sessions: never open a dialog" says
  both (8 bytes shorter).
- `edit` validation, and so `dry_run`, refuses what the run would (D49; friction 6): a
  `set` value of the wrong type, range, menu or tuple size on an existing node, a `set`
  inside a locked asset (`locked`, with the unlock call), a `patch` that does not match
  and a missing or disallowed `value_file`, and malformed `spare_parms` on a node the
  same call creates.
- `hda create` promotes the subnet's spare parms into the new definition at once, and
  `create`/`save` refuse a library whose extension does not match the licence (`.hdalc`
  on Indie, `.hdanc` on Apprentice and Education, `.hda`/`.otl` on Commercial) with the
  corrected path as the candidate; Houdini writes any extension it is given.
- `tools/list` (`text`): `minimal` +67 B, `core` +1,371 B (the `hda` tool), `full`
  +206 B.
- CI: `.github/workflows/unit.yml` runs ruff and the unit tier on Linux, macOS and
  Windows for Python 3.11 to 3.13 (portability audit,
  `docs/redesign/review/27-portability.md`).
- **`look` at a SOP shows that SOP alone** (review 26 P1 #3, D52), wherever it is:
  inside a subnet or a locked asset, in a hidden object, outside `/obj`. The scene that
  renders gets a temporary object whose Object Merge reads the SOP in world space (with
  the owner's object material), and the ROP draws only that object, on the Flipbook and
  OpenGL ROPs (the kept headless child too) and Karma. No flag of the user's moves (2.0
  moved the display flag, which showed nothing inside a subnet), and a note says so.
  `source: viewer` shows the viewer as it is, with a note.
- **`inspect` options are uniform** (review 26 P1 #9, D51): an option that only shapes the
  answer (`include_defaults`, `recurse_locked`, `full_strings`, `detail`,
  `include_positions`, `wiring`) and that the `what` does not take is ignored with a note
  instead of `invalid_argument` (`recurse_locked` on `geo`, `include_defaults` with parm
  paths, `detail: "folders"` on a node read). An option that chooses what is read
  (`frame`, `paths`, `cursor`, `class`, ...) is still an error.
- `cook {profile: true}` times what a normal cook of the target cooks (review 26 P1 #8,
  D53): a target that needs cooking is cooked normally first, and Houdini's record of the
  inputs that cook used decides the chain, so a Switch's other inputs and what feeds a
  bypassed or locked node are neither cooked nor timed. A for-each body stays in; a
  simulating chain or a failed cook profiles every ancestor, as before.
- A `look` through an OBJ camera without `resolution` takes the camera's aspect at 1024 on
  the long side (1920x1080 looks at 1024x576); an explicit `resolution` of another aspect
  is honoured with a note. `look {quality: "lit"}` says in `notes` which renderer drew the
  scene's lights (review 26 P1 #5).
- `inspect`'s description no longer lists the 1.4 read names (tools/list: text -21 B on
  `core` and `full`).

### Removed

- **The `compat_1x` profile and the `v2` alias** (BIBLE D46, `docs/migration-2.0.md` §8).
  With them go the 18 1.4 tools only `compat_1x` listed (`node_find`, `node_info`,
  `node_delete`, `node_edit`, `node_copy`, `node_connect`, `node_layout`,
  `network_describe`, `network_build`, `parm_get`, `problems`, `geo_info`, `geo_read`,
  `viewport_capture`, `node_type_search`, `node_type_info`, `selection`, `usd_stage`):
  their specs, and their host implementations where no 2.0 tool uses them (the read
  engines behind `inspect` and `search` stay as host functions). Also removed: the 1.4
  resources (`houdini://node/{path}/parms`, `houdini://node/{path}/geo`,
  `houdini://nodetype/{category}/{name}`, `houdini://job/{id}`), the four 1.4 prompts, the
  1.4 instructions and guide, the `compat_1x` goldens and its `tools/list` caps (32,000 B
  `text`, 44,000 B `both`; the 2.0 caps are unchanged), `viewport_capture`'s 1.4 source
  names (`flipbook_rop`, `opengl_rop`) and its extra `path`, and the 1.4 workloads tier
  (`--workloads 1x`; its budgets stay in `tests/workloads/budgets.json` as the baseline
  the 2.0 tier is compared with). The OpenGL ROP backend of `look` stays.
- A 1.4 tool name still answers `invalid_argument`, now on every profile and before its
  arguments are read, with its 2.0 replacement in `hint` and `detail: {tool,
  replacement, profile}` (the migration table is kept as data). `profile = "compat_1x"`
  or `"v2"` in `hocuspocus.toml` or `HOCUSPOCUS_PROFILE` is read as `full` with a
  warning, logged by the bridge and the host and returned in `houdini_status.warnings`;
  nothing refuses to start.
- Since the selection is set only through `edit` now, read-only mode refuses setting it
  (`read_only`; a `dry_run` still validates). 1.4's `selection` tool was allowed there.
- `job` results always carry ledger ids (`j` + hex); a host id `<pid>-<id>` is still
  accepted everywhere.

### Fixed

- A launch without a licence now says so, and answers within seconds (review 26 P1 #1).
  `houdini_connect {launch}` and `hocuspocus launch` recognise a licence line in the
  launch log, exit code 3, or, for a GUI, the "Unable to Acquire a License" window or the
  License Administrator (hkey) opening. They answer `houdini_offline` with
  `retryable: false`, a message saying Houdini could not get a licence,
  `detail: {reason: "licence", exit_code, log_excerpt, ...}`, and a hint to sign in with
  hkey or `sesictrl login` and launch again. Before, a GUI launch waited the full
  `wait_s` (90 s) and then hinted at `install-houdini`. A GUI Houdini stuck on that
  dialog is stopped; the License Administrator stays open.
- Linux and macOS: a launched Houdini that exited or crashed stayed a zombie child of the
  bridge and still counted as alive, so a call it dropped answered `delivery_unknown`
  instead of `houdini_offline`, with no `instance_lost`. Zombies now count as dead.
- Linux and macOS: a headless launch also accepts a host that registers under a child pid
  of the `hython` wrapper script, if its registry entry names this bridge as its launcher.
  Before, such a launch timed out.
- The headless host shuts down cleanly on SIGHUP (a closing terminal) as on SIGTERM, and
  removes its registry entry.
- `look {quality: "lit" | "final"}` through Karma rendered 1280x720 whatever
  `resolution` asked (a 640x480 look came back 1024x576): 22.0's Karma ROP renders at its
  own `resolutionx`/`resolutiony`, which the look now sets. `rendered` is the image's real
  size, and a renderer that draws another size gets a note (review 26 P1 #5).
- **A headless draft `look` no longer recooks the scene in its render process** (review
  26 P2 friction 9). The child hython rebuilt the displayed networks from the snapshot
  and cooked them on every look, the kept child too, so the dogfood tower's LOD lineup (a
  37 s lightmap pack) timed out every draft look at 30 s and the agent fell back to Karma
  `render`. The host now ships the geometry it has already cooked for what the look shows
  (`.bgeo.sc` read by a File SOP in the child's copy). Measured on
  `examples/neo_tower/work/neo_tower_p2.hiplc`: 44.2 s and 38.6 s per look before, 5.5 s
  (child start) and 0.9 s after; a test's 4 s chain looks in 0.2 s once cooked. A render
  process that still runs out of time names `cook` and `quality: "final"` in its hint.
- **Karma in a GUI session.** `look {quality: "lit" | "final"}` through Karma answered
  `cook_failed` "Karma did not produce an image: no output file" in every GUI Houdini (2.0
  too), with or without a target, and `render` of a Karma, USD Render or Mantra ROP
  returned `state: done` with every output `missing`. A GUI Houdini starts husk in the
  background unless the ROP's Block Until Render Complete (`soho_foreground`) is on, so
  `render()` returned before the image existed; hython always waits, so headless looks
  passed. Look's temporary Karma ROP has it on, and `render` turns it on for the render
  and restores it. GUI test `test_karma_looks_render_in_the_gui`.
- **A GUI launch that cannot register says why** (D60). `houdini_connect {launch}` and
  `hocuspocus launch` waited the whole `wait_s` (240 s in the GUI tests) and said only that
  Houdini "may still be starting" when its host failed to start, `autostart = false` kept
  it off, the package never loaded, or a startup dialog held Houdini. The host's
  autostart now writes `<state_dir>/startup/<pid>.json` (`uiready.py` too when
  `hocuspocus.host` cannot be imported), and the launcher reads it and the launched
  Houdini's window titles: a failed or disabled start answers at once with the error and
  the host log (`detail.reason: "host_failed"` or `"autostart_disabled"`), a dialog
  shown before the main window answers 15 s later (`"dialog"`, with its title), and a wait
  that runs out names what it saw (`"host_starting"`, `"dialog"`, `"no_autostart"` with
  the `install-houdini` hint). A licensed start shows only its splash and main window, so
  nothing fires on it. Not reproduced here: the stream D2b report of two launches in a row
  that never registered (13 launches in a row through the fixture, `hocuspocus launch`,
  hard kills and two at once all registered in 10-21 s); the next one says which case it
  is.

## 2.0.0 (2026-10-14)

2.0 changes the contract where every evaluation since 1.0 (reviews 07 to 24) said it
matters: calls per task and bytes per call. Scene changes become one transaction tool,
`edit`; reads become one tool, `inspect`, plus `search`, and every read is also a resource
with an ETag; pictures become one tool, `look`, that picks its renderer from a quality
level; and a bridge ledger remembers Houdinis, roles and jobs across restarts. The default
`core` profile lists 18 tools instead of 31. The plan is `docs/redesign/spec-2.0.md`, the
design `docs/BIBLE.md` (rewritten for 2.0; decisions D35 to D44), and
**[`docs/migration-2.0.md`](docs/migration-2.0.md) maps every 1.4 tool to its 2.0
replacement**. `profile = "compat_1x"` keeps 1.4 client scripts running unchanged for the
2.0.x releases.

### Measured

- **Scorecard** (`docs/redesign/review/25-scorecard-2.0.md`): a fresh agent ran review 21's
  twelve tasks on the default `core` profile with only the MCP surface. 111 round trips
  and 435.6 KB on the wire against 1.3's 122 and 458.1 KB; 52.6 KB of tool-result text
  (about 13.2k tokens) against 57.7 KB; `tools/list` 20.5 KB (18 tools) against 30.7 KB
  (35). Every task call succeeded on the first try; the 5-node build with its layout was
  one call (588 B). It scored 2.0 4 / 5 / 5 / 4 / 5 / 5 (1.3: 4 / 5 / 5 / 5 / 5 / 5): error
  quality dropped because the server's own hints named 1.4 tools `core` refuses. This
  release fixes the five papercuts the review asked for before tagging (see **Fixed**), and
  its task 9 is now `tests/e2e/test_error_quality_v2.py`: 20 deliberate mistakes on
  `core`, every message and hint naming only `core` tools.
- **Workloads** (`tests/workloads`, spec-2.0 §7): each 2.0 workload uses fewer calls and
  fewer text bytes than its 1.4 budget, the M4 exit. The cuts against the margins the
  reviews predicted (the 2.1 targets where unmet):

  | Workload | Calls 1.4 → 2.0 | Cut (target) | Text bytes 1.4 → 2.0 | Cut (target) |
  |---|---:|---:|---:|---:|
  | `city_build` | 21 → 15 | 29 % (25 %) | 20,804 → 13,916 | 33 % (20 %) |
  | `fx_cache` | 13 → 11 | 15 % (15 %) | 9,084 → 7,114 | 22 % (15 %) |
  | `scorecard_twelve` | 49 → 48 | 2 % (0 %) | 28,204 → 23,250 | 18 % (20 %, a 2.1 target) |
  | `soak_200` | 200 → 177 | 12 % (0 %) | 100,362 → 68,867 | 31 % (20 %) |
  | `vellum_usd` | 14 → 11 | 21 % (15 %) | 8,292 → 6,063 | 27 % (15 %) |

### Contract changes

- **The default profiles serve the 2.0 surface.** `minimal` (10 tools), `core` (18, the
  default) and `full` (21) list `inspect`, `search`, `edit` and `look` and no longer list
  the 18 per-noun 1.4 tools they replace (see **Removed**). `minimal` is `houdini_status`,
  `houdini_connect`, `hip_open`, `hip_save`, `inspect`, `search`, `edit`, `node_create`,
  `parm_set`, `look`; `core` adds `hip_new`, `hip_merge`, `cook`, `render`,
  `houdini_python`, `job`, `undo`, `time`; `full` adds `hda`, `pdg`, `events`.
- **`compat_1x`** serves the 1.4 `full` catalogue (35 tools) with 1.4 schemas, results,
  annotations, resources, prompts and instructions, running on the 2.0 engines. It is
  served for 2.0.x and removed in 2.1. The `v2` profile of the development branch reads as
  `full`.
- **A removed 1.4 tool names its replacement.** Called on a 2.0 profile, `node_info` (and
  every other removed tool) answers `invalid_argument` with the 2.0 call in `hint` and the
  `compat_1x` setting that keeps it.
- **Every scene change runs on one transaction engine** (`host/tx.py`, D35).
  `node_create`, `parm_set` and the 1.4 mutation tools of `compat_1x` build `edit` plans
  and return their 1.4 results unchanged: one undo policy, one rollback, one echo.
- **Job ids are opaque** on the 2.0 profiles: the bridge ledger's id (`j3f9a1c`) instead of
  `<pid>-<id>`. `job` still accepts host ids in every profile, and `compat_1x` keeps
  returning them. `events` cursors (`next_since`, `<pid>:<seq>`) are unchanged.
- **One dirty flag in both modes** (parity G1). What tools report as `dirty`, and what
  `on_unsaved` and `pdg cook` refuse, is the agent's own changes or a change made outside
  HocusPocus since the last save, load or clear, never Houdini's raw
  `hasUnsavedChanges()`; see **Fixed**.
- **`tools/list` budget** (D44). The 2.0 `full` profile is capped at 24,000 B (`text`) and
  34,000 B (`both`); `compat_1x` keeps the 1.4 caps of 32,000 B and 44,000 B and is
  byte-identical to 1.4's `full`. At the cut-over: 14.8/20.3/22.8 KB `text` and
  17.9/26.6/29.1 KB `both` for minimal/core/full, against 14.4/27.4/30.8 KB `text` at
  1.4.0.

### Added

- **`edit`**: every scene change of a task in one call and one undo step
  (`HocusPocus: edit <n> ops`). Ops `create`, `delete`, `connect`, `set`, `node`, `copy`,
  `layout`, `build` and `select` take the fields of the 1.4 tool each replaces. An op's
  `id` is `$id` (or `$id/child`, `$id/parm`) in later ops' paths. The whole plan is
  validated against the scene before anything changes and every problem is reported at
  once; `dry_run: true` returns the plan with resolved paths and changes nothing. A failing
  op rolls the call back (`partial: true` keeps the others). The result is one row per op
  plus one summary row per touched node, each cooked once at the end. The review-07 build
  is one call of under 1 KB.
- **`inspect`** `{what, target}`: `node`, `parms`, `network`, `outline`, `geo` (rows with
  `rows: true`), `image`, `stage`, `problems`, `type`, `events` and `jobs`, returning the
  matching 1.4 read's result plus an `etag` (without `what` or `target`), projected
  compactly by default (defaults and empties left out; `detail: "full"` for the 1.4
  shape). A node as
  `parms` target reads its non-default parms.
- **`search`** `{kind: types | nodes}`: `node_type_search` (now paged with `next_cursor`)
  and `node_find`.
- **`look`** `{target?, quality: draft | lit | final}`: one picture of an object, SOP, LOP,
  Cop node or ROP (default the display). `draft` is the Flipbook ROP (headless too, with
  the kept child: about 0.4 s after the first), `lit` adds the scene's lights (Karma at 2
  samples when there are none), `final` renders Karma at the ROP's samples (else 32);
  `source: viewer` grabs the GUI Scene Viewer. Returns `backend_used`, `chain` and notes.
  The capture and render backends are one package, `host/look/`.
- **Resources with ETags and subscriptions.** `houdini://instances`, `jobs`,
  `node/{path}`, `outline{?root,depth}`, `network/{path}`, `geo/{path}`, `image/{path}`,
  `stage/{lop}`, `type/{category}/{name}`, `types{?q}`, `problems{?root}` and
  `events{?since,limit}`, each the matching `inspect` or `search` result byte for byte
  (`GET /hp/v2/resource` on the host). Every read returns `_meta.etag`; `If-None-Match`
  with it answers `not_modified` with no contents. `status`, `jobs`, `events` and
  `node/{path}` can be subscribed to (`notifications/resources/updated` when the etag
  changes).
- **The bridge ledger** (`<state_dir>/ledger.sqlite`): instances with names and roles,
  jobs and launches, kept across bridge restarts. `houdini_status` lists `recent`, the
  Houdinis that exited; a job's id reaches its Houdini after a bridge restart, and a
  finished job's stored result is returned with a note.
- **Roles and `on`.** Every Houdini is an `editor` (GUI) or a `worker` (headless);
  `houdini_connect {role}` sets one or pins the least busy Houdini with it. `cook`,
  `render`, `look` and `job` take `on` (a pid, name or role) to run on another Houdini
  without moving the pin.
- **Prompts** `cache_sim`, `two_houdinis` and `lookdev_karma`, and the four 1.4 prompts,
  the server instructions and `hocuspocus://guide` rewritten for the 2.0 tools.
- **`houdini_status`** reports `hip.dirty_source` (`tracked`, `user_event`,
  `houdini_flag`) and Houdini's own flag as the diagnostic `houdini_flag`; an
  `unsaved_changes` error carries `detail.dirty_source`.
- **Spec files** (D41): one module per tool under `tools/spec/`; `docs/tools.md`,
  `hocuspocus://tools` and the new `docs/redesign/budget.md` are generated from them.
- **The workloads tier** (D42): `tests/workloads/` scripts five evaluations (city build,
  scorecard twelve, a 200-call soak, FX cache, Vellum to USD) with call, byte and time
  budgets recorded from 1.4, failing on a 15 % regression; nightly on the Houdini runner.
- **The parity matrix** (D43): `docs/parity.md` lists every tool × GUI/headless as same,
  mode or gap, and `tests/integration/test_parity_gui.py` (`--rungui`) runs the GUI column
  in a scripted `houdinifx` session.
- **`docs/migration-2.0.md`.**

### Fixed

- **Hints name only the active profile's tools** (review 25 papercut 1). On `core` the
  server's own hints sent the agent to `node_find`, `node_type_info`, `node_type_search`,
  "the problems tool" and `viewport_capture`, which `core` refuses. Every hint and message
  that names a tool now goes through `tools/migration.py` `hint_tool`, which renders
  `search {kind: "nodes", root}`, `inspect {what: "type", target}`, `search {kind:
  "types", query}`, `inspect {what: "problems"}`, `look` and the `edit` `set` and
  `create` ops on the 2.0 profiles, keeps the 1.4 names on `compat_1x`, and leaves out a
  clause whose tool the profile lacks. Hints that pointed at `docs/tools.md` point at
  `hocuspocus://tools`. A unit test checks a fixture of errors in every profile.
- **`inspect` steers the 1.4 path arguments to `target`** (papercut 2): `path`,
  `node_path`, `root`, `lop_path`, `type` and `rop_path` answer "2.0 renamed it target"
  before any edit-distance guess, with the corrected call in `hint`; `paths` as one
  string, or on a `what` that takes one path, too. A flat `edit` op, or `ops` given as an
  object, gets the call with the op inside `ops`.
- **`edit` errors are located at the op field** (papercut 3): `ops[0].from: No node at
  /obj/g/nope.` instead of `items[0] (/obj/g/copy1): ...`, with `detail.field`; a missing
  `from`, `to` or `parent` lists the parent's children as the plan leaves them, nearest
  first, never the other end of the wire.
- **Version 2.0.0 everywhere, and `serverInfo` once** (papercut 4): `server_info.version`,
  `bridge_version`, `host_version` and the package said 1.4.0. The MCP `serverInfo` stamp
  (about 200 B) is kept on the handshake (`initialize`, `server/discover`) and dropped from
  every other result's `_meta`, which keeps `instance` and `timing`.
- **`job_not_found` for a ledger-form id describes the ledger** (papercut 5): `jzzzz` got
  the 1.x hint about the pid before the `-` and Houdini restarts. The bridge answers every
  `j...` id the ledger lacks itself; the 1.x hint is for `<pid>-<id>` ids only.
- **No U+FFFD in clipped text** (papercut 8): the help-header read and the log tails cut
  bytes and decoded a split character as U+FFFD; they now cut on a character boundary
  (`tools/budget.py` `utf8_head`, `utf8_tail`, `clip`).
- **`hip_new` on an untitled scene** (papercut 9) leads its hint with `hip_save {path}` or
  `discard`, not `on_unsaved: 'save'`, which has nowhere to save to.
- **`houdini_status` prints the hip path once** (papercut 10): `connected.hip.path` stays;
  `hip.name`, a `hip.recent` entry, `env.HIP`, `env.JOB` and `env.HIPNAME` that only repeat
  it, and `hip` on the connected instance's row and on `recent` rows, are left out
  (`compat_1x` keeps the 1.4 fields).
- **A read no longer dirties the GUI hip** (parity G1). In 1.4 the GUI reported Houdini's
  own `hasUnsavedChanges()`, which HocusPocus's temporary nodes set: after a capture,
  `node_type_info` or `render {output}`, `hip_new`, `hip_open` and `houdini_connect
  {quit}` with `on_unsaved: fail` refused and `pdg cook` called the scene unsaved, in the
  GUI only. The captures' "Houdini marked the hip modified" notes are gone with it.

### Upgrading from 1.4

Read **[`docs/migration-2.0.md`](docs/migration-2.0.md)**. In short:

- Run `hocuspocus install-houdini` and restart Houdini, as for every release.
- Agents need nothing: the instructions, guide and prompts name the 2.0 tools.
- A script that calls 1.4 tools either moves to the 2.0 names (the error `hint` names each
  replacement) or sets `profile = "compat_1x"` for the bridge and Houdini until 2.1.
- Treat `job_id` as an opaque string; `<pid>-<id>` ids are still accepted.
- `viewport_capture`'s GUI default (the viewer as it is) is `look {source: "viewer"}`;
  `look`'s own default renders a Flipbook ROP framed on the target.
- `inspect` results are the 1.4 read's keys plus `etag`, compact by default (`detail:
  "full"` for the 1.4 shape); `edit` returns `results` per op and `nodes` per touched
  node.
- `edit` errors name the op field (`ops[0].from: ...`, `detail.field`); the 1.4 batch
  tools keep `items[i] (<path>): ...`.
- The resources `houdini://nodetype/...`, `houdini://node/{path}/parms`,
  `.../geo` and `houdini://job/{id}` are `houdini://type/...`, `houdini://node/{path}?parms=*`,
  `houdini://geo/{path}` and `houdini://jobs` on the 2.0 profiles.

### Removed (from the default profiles; still in `compat_1x` for 2.0.x)

- `node_find`, `node_info`, `network_describe`, `parm_get`, `problems`, `geo_info`,
  `geo_read`, `node_type_search`, `node_type_info`, `usd_stage`: use `inspect` and `search`.
- `node_delete`, `node_edit`, `node_copy`, `node_connect`, `node_layout`, `network_build`,
  `selection`: use `edit` ops (`selection` is read with `houdini_python`).
- `viewport_capture`: use `look`.
- The 1.4 resources `houdini://nodetype/{category}/{name}`, `houdini://node/{path}/parms`,
  `houdini://node/{path}/geo` and `houdini://job/{id}`.
- 2.1 removes `compat_1x`, the `v2` alias and, once Houdini 22.5 is the floor, the
  OpenGL ROP backend.

## 1.4.0 (2026-10-13)

1.4 put 1.3.0 through three evaluations, each through the MCP tools only:

- the review 07 scorecard re-run by a fresh agent, which scored 1.3.0 4 / 5 / 5 / 5 / 5 / 5
  against 1.0's 4 / 5 / 4 / 4 / 5 / 5 (`docs/redesign/review/21-scorecard-1.3.md`);
- a soak of 1,230 calls (a 614-call pilot and a 616-call run on one session) against a
  headless host, with no unexpected error, no call over 10 s and nothing leaked
  (`22-soak-1.3.md`, latency chart `90_soak_latency.png`);
- a Vellum cloth cached with a File Cache, exported to USD, re-imported with `sublayer`
  and rendered with Karma (`23-vellum-usd-eval.md`, `100_vellum_usd_karma.png`).

This release fixes what they found and the known items of the plan
(`docs/redesign/plan-1.4.md`). Captures move from the OpenGL ROP, which Houdini 22
deprecates, to the Flipbook ROP, and a headless capture after the first takes about
0.4 s instead of 3 s. `render` writes an animated USD layer or Alembic archive in one call
and reads it back, so a frozen export fails instead of reporting success (review 23's
P0). A budget-trimmed `events` page no longer skips events (review 22's P0). Mutation
results and `_meta` say how long Houdini cooked, and the host log has one line per call.
Read **Upgrading from 1.3** if a prompt or script names the `opengl_rop` source, calls
`render` without `frames`, filters `events` by `origin` or relies on `redo`. The contract
decisions are D30 to D34 in `docs/BIBLE.md` §15.

### Contract changes

- **Captures go through the Flipbook ROP.** `viewport_capture`'s ROP source is now
  `source: "flipbook_rop"`; `opengl_rop` stays as an alias of it. It tries the Flipbook
  ROP, then the OpenGL ROP, then a temporary Karma CPU ROP (2 samples, same camera and
  resolution). `source_used` is `viewer`, `flipbook_rop`, `opengl_rop` or `karma`, and
  `notes` say why an earlier ROP did not render. Headless, a ROP whose render process
  crashes hands the frame to the next; in the GUI a ROP that writes no image does, and
  there is no Karma step. The temporary OpenGL ROP gets no deprecation note. A Flipbook
  ROP's stage capture keeps every thread; only the OpenGL ROP's stage child stays
  single-threaded.
- **`render` renders a single-file ROP in one call and reads it back** (review 23 P0-1).
  In 1.3 every ROP rendered one `rop.render()` call per frame, so a `usd_rop`, a
  `usdexport` SOP or an Alembic ROP overwrote its one file on each call: a 48-frame
  export reported 48 outputs and `done` and kept one time sample. A ROP whose output path
  is the same for every frame now renders the range in one call, with per-frame progress
  from its render events (a cancel waits for the call to end). The file is then read
  back: a USD layer set (the root layer and every layer it composes) or an Alembic
  archive with fewer frames than asked fails with `cook_failed`, and a USD export without
  time samples gets a static-stage note.
- **`render` without `frames` renders the ROP's own frame range** (review 23 P1-2). Every
  ROP renders its Valid Frame Range (`f1`-`f3`) unless it is set to Render Current
  Frame, which renders the current frame. A note says which range was used and that
  `frames` renders others. In 1.3 a ROP rendered the current frame, while writer SOPs
  already used their own range.
- **Render outputs are listed once, and USD exports list their layers** (review 23
  P1-3). One file is one output, so a 48-frame USD export counts 1, not 48. A USD export
  adds `layers: [{path, bytes, time_samples, time_codes?}]`: its root layer, every layer
  file it composes (a `sopimport` save path is one) and USD files the render wrote beside
  it, at most 20.
- **A ROP whose camera is missing fails with `node_not_found`** (review 21 papercut 5),
  not a bare `cook_failed` "No camera specified for render.". The error names the
  `camera` parm and its value, lists the scene's OBJ cameras as `candidates`, and hints to
  set the parm, pass `camera` or create one.
- **`node_edit` never cooks** (review 22 finding 3). It reports `cook_state` from
  `needsToCook()` and the errors already on the node; in 1.3 a rename recooked the node
  (about 200 ms for a `mountain`).
- **`node_create {cook: false}` and `cook_ms`** (review 22 finding 2). `node_create`,
  `node_copy` and `network_build` summary rows carry `cook_ms`, the time the diagnostic
  cook took (a first cook of an HDA such as `mountain` takes about 200 ms).
  `node_create {cook: false}` skips that cook (`cook_state: not_cooked`) for batch
  builders that cook once at the end.
- **`_meta.timing` on every host call** (review 22 finding 2): `{main_thread_ms,
  queue_ms}`, the time the tool ran on Houdini's main thread (0 for tools that run off it,
  such as `job` and `events`) and the wait for it before that, success or error.
- **`events` `origin: houdini`** (review 23 papercut 9). In a call that sets parms
  (`parm_set`, `node_create` parms), a `ParmTupleChanged` on a parm the call did not set
  but Houdini wrote (callbacks, a camera's `*Converted` parms, a light's guide scale,
  `labelparm*`) has `origin: "houdini"` instead of `agent`. A call that sets no parms
  explicitly, such as `houdini_python`, keeps every write `agent`. Events of different
  origins no longer coalesce.
- **`redo` stops at a rolled-back call** (review 21 papercut 2). Rolling back a failed
  `houdini_python` or batch left it on Houdini's redo stack, and `undo {action: redo}`
  re-ran it. `redo` now stops before it and names it in `skipped` with a note; `history`
  lists it under `rolled_back`, not `redo`, and `next_redo`/`redo_count` skip it.
- **`tools/list` budget policy** (D30). The full profile's `tools/list` is capped at
  32,000 B with the default `result_content = "text"` (what clients see by default, no
  output schemas) and at 44,000 B with `both`. The 40,000 B target on the `both` shape is
  gone. At 1.4.0 the full profile is 30,825 B (`text`) and 40,415 B (`both`). No tool or
  argument was removed.
- **`usd_stage` layer rows** (review 23 papercuts 4, 10). `layers.stack` rows are
  objects, `{identifier, save_path?, owner_node?, time_codes?}`, instead of identifier
  strings: `save_path` is where Houdini will save an anonymous layer (a `sopimport`'s save
  path) or a file layer's own path, and `owner_node` the LOP that made it. `usd_stage` on a
  `usd_rop` or `usdrender_rop` reads the LOP it renders (its `loppath`, else its input)
  with a note instead of refusing.
- **`node_type_search` rows** (review 23 papercut 6). With `current_only` (the default)
  rows leave out `is_current_version`; `child_category` and `typical_parents` shared by
  every row are said once, in `common`.
- **`geo_info` attributes** (review 23 papercut 8). `attributes: "names"` lists only the
  attribute names per class. Solver internals (Vellum and DOP bookkeeping such as
  `pprevious`, `hitnml`, `dPw`, `varmap`, and names starting with `__`) are left out of
  both modes and counted in `internal_attribute_count` with a note; `geo_read` still reads
  them.

### Added

- **A kept capture child** (review 22 finding 6). Headless, the first Flipbook capture
  starts a child hython that stays up; each later capture sends it a fresh scene snapshot.
  A capture after the first takes about 0.35-0.4 s (0.9 s for a stage) against 2.8-3.6 s
  in 1.3. The child is replaced when the child script, the hython or an installed HDA
  library changes, after 200 captures or 110 s idle, and exits by itself after 120 s idle.
  A crash of a kept child that had already rendered retries the capture in a fresh child
  with a note. In the GUI a capture renders in-process (about 0.3 s).
- **`render {camera}`** overrides the ROP's camera for one render, set and restored like
  `output`: an OBJ camera for the `camera` parm, or a camera prim for a ROP reading a stage
  (`cameraprim`) or a USD render ROP (`override_camera`).
- **`network_build {press}`.** `setChildrenFromData` runs no parm callbacks, so a
  `pyrosource` built from data with `initialize` set applied nothing. `network_build` now
  notes every callback menu or toggle that `data` sets, as `node_create` does, and
  `press: {node: [parm names]}` runs those callbacks after the build is wired, in the same
  undo step; the result adds `pressed` and `side_effects`, and a failed press rolls the
  build back.
- **ROP LOPs as stages** (review 23 papercut 10). `viewport_capture {lop_path}` and
  `usd_stage` on a `usd_rop` or `usdrender_rop` use the LOP the ROP renders (its
  `loppath`, else its input), with a note.
- **One host log line per call** (review 22 finding 4): `call <tool> <elapsed> ms main
  <main_thread_ms> ms ok|<code> pid <pid>` at INFO in `<state_dir>/logs/host-<pid>.log`,
  through the existing rotating handler (5 MB, two backups).
- **`undo {action: history}` counts** (review 22 finding 9). `total` and `redo_total`
  count every label next to the newest 20, and the notes say that `hip_open` and `hip_new`
  clear the history.
- **Output indices in outlines** (review 23 papercut 5). `network_describe {format:
  outline}` and `houdini://outline` write an input whose source output is not 0 as
  `"<path>:<n>"`, so a Vellum constraint output fed in as geometry is visible.
- **The items form for flat batch calls** (review 21 papercut 1). `parm_set {path,
  value}`, `node_connect {from, to}` or any batch tool given one flat item answers
  `invalid_argument` whose hint is the corrected call, the caller's fields wrapped in
  `items`. The instructions and the guide use the items form.
- **`node_type_info` glob ranking** (review 23 papercut 7). A wildcard `parms` glob lists
  the parms it matches at the start of a name or label word first; those matched only
  inside a word follow, named in `substring_matches` and marked `matched_by: "substring"`
  in `full` rows.
- **A Flipbook frames recipe** in `hocuspocus://guide`, and the instructions point a
  many-frame flipbook at the Flipbook ROP.

### Fixed

- **`events` paging under the budget** (review 22 finding 1, P0). A budget-trimmed
  `events` page kept the host's `next_since`, the last seq scanned, so a client following
  the cursor silently lost every event the cut dropped. The bridge now rewrites
  `next_since` to `<pid>:<seq>` of the last kept event with `more: true`, and rewrites
  `node_find`'s `after:<path>`, `network_describe`'s `after:<name>` and integer offsets
  (`geo_read`'s `start` included) the same way; any other page stays whole with
  `over_budget: true`. The host also ends `events` pages at the budget.
- **Malformed job ids** (review 21 papercut 3, review 22 finding 7). `job {status,
  job_id: "999-deadbeef"}` answered `instance_lost` for a Houdini that never existed. A
  pid the bridge never saw live (no registry entry, job, pin or launch record) is now
  `job_not_found` with a hint naming `job {action: list, all: true}`.
- **`node_not_found` hints** (review 21 papercut 4, review 22 finding 8). A missing
  wiring source (`node_connect` `from`, `node_create` `inputs.from`) prefixes the batch
  error with its own path and says what it was to be wired into, takes candidates from
  its parent without the target, and every `node_not_found` hint names `node_find` on the
  parent, or on the nearest existing ancestor when the parent is missing too. `geo_info`,
  `cook` and `node_info` share it.
- **Deprecation notes once per type** (review 22 finding 10). `node_create` gives a
  deprecated type's note once per type per host session; every row keeps
  `deprecated: true`. In the soak the same `mountain` note was sent 37 times.
- **Camera-missing renders** (review 21 papercut 5): see the contract change above.
- **The guide's flat examples.** The spare-parm and Copernicus recipes used flat
  `parm_set` and `node_create` calls that the schema rejects; they now use `items`.
- **Shared USD layers** (review 24 N1, P1): a USD render whose layer replaced another ROP's samples with fewer (48 to 3) says so first in `notes` and sets `layers[].overwrote_samples`; layers another ROP also writes get `shared_with`.
- **`cook profile` on a warm solver** (review 24 N3): a re-solve of the frame the simulation stood on is `resimulated: "current_frame"`, not `true`; cache reads stay `false`, and `simulated_frames` gives the range when known.
- **Exact `parms` alternatives** (review 24 N2): `node_type_info parms: "*pin*|group"` no longer lists `group` in `substring_matches`.
- **`render camera` against `opsource`** (review 24 N4): a camera prim on a viewport ROP reading /obj, or an OBJ camera on one reading a stage, fails naming `opsource`; an override adds a `Rendered through` note.
- **`_meta.timing` off the main thread** (review 24 N5): job-backed tools sum the main-thread steps run for the call, or report `off_main_thread: true`.
- **Layer row paths** (review 24 N7): `usd_stage` layer rows use forward slashes and drop a `save_path` equal to the identifier.

### Upgrading from 1.3

An agent prompt or script written for 1.3 may need these changes:

- **Capture source names.** Use `"source": "flipbook_rop"`; `"opengl_rop"` still works as
  its alias. Expect `source_used: "flipbook_rop"` where 1.3 said `opengl_rop`, and read
  `notes` when it is `opengl_rop` or `karma`.
- **`render` frame defaults.** Without `frames`, a ROP now renders its own frame range,
  not the current frame. Pass `frames: [f, f, 1]` for one frame, or set the ROP to Render
  Current Frame. A USD or Alembic export with fewer frames than asked is now an error, and
  `outputs_summary.count` counts files, not frames.
- **`events` origins.** `origin` is `agent`, `houdini` or `other`. A filter that keeps
  only `agent` now drops the parms Houdini wrote itself during an agent call; keep
  `houdini` too if you need them. Follow `next_since` and `more` rather than counting
  rows, since a trimmed page now ends early.
- **`redo` behaviour.** `redo` no longer re-applies a call that failed and was rolled
  back: it stops before it and lists it in `skipped`. Read `history.rolled_back` for such
  calls.
- **Shapes that changed.** `usd_stage` `layers.stack` rows are objects; `geo_info` leaves
  out Vellum and DOP internals (`geo_read` reads them); `node_type_search` rows may omit
  `is_current_version`, `child_category` and `typical_parents` (read `common`); a missing
  ROP camera is `node_not_found`; `node_edit` reports `cook_state` without cooking.

## 1.3.0 (2026-10-12)

1.3 put three more workloads through the MCP tools, each on 1.2.1:

- an FX sim cached with a File Cache and flipbooked
  (`docs/redesign/review/17-fx-sim-cache-eval.md`);
- a Copernicus image network written to disk and brought back as pixels
  (`18-copernicus-eval.md`);
- a GUI Houdini and a headless worker driven from one session, with the four shipped
  prompts followed as written (`19-two-instances-and-prompts-eval.md`).

This release fixes what they found and the known items of the plan
(`docs/redesign/plan-1.3.md`): dynamic menus, keyed components in `events`, a `minimal`
profile with a 12-word cap on argument descriptions, and a fast/slow split of the
integration tier. Driving several Houdinis is now explicit: the bridge never switches
instance on its own, and job ids and `events` cursors say which Houdini they belong to.
Read **Upgrading from 1.2** if an agent prompt or script runs more than one Houdini,
polls jobs, keeps `events` cursors or presses buttons. The contract decisions are D25 to
D29 in `docs/BIBLE.md` §15.

### Contract changes

- **New error codes `instance_lost` and `ambiguous_instance`; the bridge never switches
  instance on its own.**
  - `houdini_connect {pid}` (or `{launch}`) pins that Houdini. In 1.2, when a pinned
    Houdini exited, the bridge moved to another one silently, so in review 19 a
    `parm_set` meant for a killed worker changed the user's GUI scene. Every call now
    returns `instance_lost`, naming the dead pid and label, with the live instances as
    `candidates: [{pid, label, ui, hip}]` and `retryable: false`. `houdini_status`
    reports `connected: null` and `lost: {pid, label}`. Only an explicit
    `houdini_connect` (`{pid}`, `{name}`, `{launch}`, `{}` or `{disconnect: true}`)
    clears the pin.
  - With several live Houdinis and none pinned, a call that changes a scene refuses with
    `ambiguous_instance`. The error lists the candidates and the `houdini_connect
    {"pid": …}` call for each. In 1.2 the newest instance was picked, so an agent that
    skipped `houdini_status` edited a throwaway worker.
- **Every result names its Houdini.** A result a host answered carries `_meta.instance:
  {pid, label, name?}`, `houdini_status` and `houdini_connect` included. A read sent to a
  guessed instance (several running, none pinned) goes to the GUI session first, then the
  newest, and also carries `_instance: {pid, label, ui, warning}` in the result itself,
  because not every client shows `_meta` to the model. The reading forms of the
  `scene=False` tools count as reads: `time` and `selection` without arguments, `job`
  status/result/list, `undo history`, `hda list` and `pdg` status/workitems. So does
  `viewport_capture`.
- **Job ids are `<pid>-<id>`.** The bridge sends `job` calls (and `houdini://job/{id}`)
  to the Houdini whose pid starts the id, whatever is selected or pinned. When that
  Houdini has exited, the answer is `instance_lost` with the last status the bridge saw in
  `detail.last_status`. A bare `<id>` still finds a job of the selected Houdini.
- **`events` cursors are `<pid>:<seq>`.** Each Houdini numbers its own events from 1, so
  in 1.2 a `since` carried over from the GUI silently skipped a worker's first events.
  `next_since` is now `"<pid>:<seq>"` and `since` takes it back. A cursor from another
  Houdini returns that Houdini's events from the start, with `reset: true` and a note. A
  bare integer still works, and the host keeps plain integers.
- **`ParmTupleChanged` names the changed components.** On a multi-component tuple the
  event carries `components` (those whose value or keys changed; a burst within 0.1 s is
  one event with their union) and `keyed` (those of them with keyframes now) instead of
  `count`.
- **`parm_set press` returns what the press did.** A pressed button returns `pressed`
  and `side_effects: {parm: [old, new]}` instead of `value`, `raw` and `is_default`. On a
  writer's save button (File Cache Save to Disk, a ROP SOP's Render), the output files
  over its frame range are checked afterwards: the result has `outputs_summary`, or the
  call fails with `cook_failed` and `detail.missing` when the press wrote nothing.
- **`render` accepts writer SOPs.** A File Cache, `rop_geometry` or `rop_alembic` SOP
  renders over its own frame range unless `frames` is given, as a job with per-frame
  progress and cancel. A File Cache renders through the ROP inside it (no `output`
  override), then turns on Load from Disk as its Save to Disk button does, and reports
  `side_effects`.
- **`cook` on writers says it wrote nothing.** Cooking a ROP or a File Cache writes no
  files. The result now carries a note naming `render` and `parm_set press` on the
  node's execute button. In review 17, `cook {frame_range}` on a File Cache returned
  `ok: true` and left no cache on disk.
- **`geo_info` on a Cop node returns an image summary**: `kind: image`, `layer_type`,
  `resolution`, `data_window`, `pixel_scale`, `storage`, `border`, per-channel `{min,
  max, mean}` of the first output, and `other_outputs`. The output schema no longer
  requires `point_count`, `prim_count` and `vertex_count`.
- **`viewport_capture` `fit` has no schema default.** The schema said `fit: "all"`, but
  the viewer never applied it: without `fit` the viewer captures the view as it is and
  the OpenGL ROP frames all. The schema now matches that behaviour.
- **`hocuspocus://guide` is split from the tool reference.** The guide is the
  instructions, the resources and recipes (two Houdinis, Copernicus, spare parms), at most
  8 KB. In 1.2 it was 52 KB because the whole tool reference followed it. The reference
  is the new resource `hocuspocus://tools`, with every tool's `notes` and examples for the
  bridge's profile.
- **`minimal` profile.** `profile = "minimal"` lists and allows 14 tools for clients with
  a small context: `houdini_status`, `houdini_connect`, `hip_open`, `hip_save`,
  `node_find`, `node_info`, `node_create`, `node_connect`, `parm_get`, `parm_set`, `cook`,
  `geo_info`, `viewport_capture` and `houdini_python`. The profiles nest (minimal ⊂ core ⊂
  full). `tools/list` is 20.4 KB on `minimal`, 36.6 KB on `core` and 40.0 KB on `full`,
  output schemas declared. Argument descriptions are now at most 12 words, and a unit test
  enforces it. Their detail moved to `notes`, which `docs/tools.md` and
  `hocuspocus://tools` render and `tools/list` leaves out.
- **Ramp values are rounded.** Ramp keys and values come back at 6 significant digits,
  without `raw` (which was the key count), and `parm_get include: [ramp]` no longer
  repeats the whole ramp under both `value` and `ramp`. One ramp edit is one `events`
  entry instead of one per key parm.

### Added

- `viewport_capture {cop_path}` looks at a Cop node, or a COP network's display node. It
  renders through a temporary `rop_image` in its network (about 0.2 s, outside undo and
  `events`, deleted afterwards) and returns the PNG at the COP's own resolution with
  `scene: cop` and `layer: {layer_type, resolution, data_window}`. A capture with no
  `camera`, `lop_path` or `cop_path` names the COP networks under `/img` in a note, and a
  Cop node passed as `camera` or `lop_path` points at `cop_path`.
- `geo_read {frame}` reads at that frame without moving the playbar.
- `cook {wait_s}`, as on `render`: how long the call waits before returning the job;
  `0` returns it at once. With `summary: bbox`, a row appears only when the counts, the
  bbox or the errors change, and its `through` names the last frame it stands for.
- `houdini_status` reports `connected.memory: {rss_mb, peak_mb}`, the Houdini process's
  resident and peak memory from the OS counters, so an agent can watch a sim cache fill.
- `houdini_connect {pid, name}` names a Houdini. The name is stored in its registry
  entry and shown in `houdini_status` and `_meta.instance`; `{name}` alone pins it.
  `houdini_status.instances[]` rows gain `busy` (the main thread has been held for at
  least 1 s) and `jobs_running`, both from each host's `/health`, plus `name` and
  `selected`.
- `job {action: "list", all: true}` lists the jobs of every live Houdini, each row with
  its `pid`, plus `instances: [{pid, label, jobs, running}]`.
- Dynamic menus are evaluated. In `node_type_info detail: full`, a script menu (such as
  `pdg_cachemode`) or a menu built from input geometry (a SOP group menu) is evaluated on
  a muted, undo-free temporary instance and returned as `menu: {items, dynamic: true}`.
  `parm_get include: [menu]` reads the live parm (cooking a SOP first) and marks it
  `dynamic`. A menu that is still empty returns `items: []` with a note.
- String parms whose menu only the node builds, such as the Copernicus `signature`, list
  their menu and are validated like other menus: a token or a label is accepted, and
  anything else is `invalid_value`.
- `node_type_search` knows Copernicus. Cop types match the labels of their menus
  (`remap`'s Threshold, `blend`'s Over), and compositing words name their Cop type
  (threshold: `remap`, gradient: `ramp`, composite or over: `blend`, text: `font`, write:
  `rop_image`). A network type's row adds `child_category` and `typical_parents`
  (`copnet`: `/img`). Results with legacy `Cop2` types carry a note that Copernicus is
  `Cop`.
- A compact `node_type_info` over 8 KB leaves out the parms that a menu hides at its
  default, such as the per-pattern parms of the other `tilepattern` patterns. It lists
  them in `variants: {menu parm: parms left out}` with a note. Pass `parms` or `detail:
  full` to see them.
- `cook {profile: true}` on a node that simulates (a DOP network, or a solver SOP such as
  `pyrosolver`) adds `simulation: {dopnet, resimulated, frame}` and a note on whether the
  force-cook re-simulated or read frames already in the simulation cache.
- `parm_set press` runs the callback script of any parm that has one, menus and toggles
  included (`pyrosource` `initialize`). With `value`, it sets the value first. A plain set
  of a menu or toggle with a callback carries a note that the callback did not run.
- Partial results on cancel. A cancelled `cook` job's result is the `cancelled` error
  with `detail: {last_status, partial: {frames_cooked, results, frames?}}`, and a
  cancelled `render` job's has `detail: {last_status, partial: {outputs_summary}}`, the
  files written before the cancel.
- The integration tier is split into a fast set and a slow set. A default `hython -m
  pytest` run deselects tests marked `slow`: 386 tests in about 50 s, against 4 minutes
  before. `--runslow` adds the 60 slow tests and `-m slow` runs only them. `houdini.yml`
  runs the two sets as separate steps. A new e2e test drives two headless Houdinis
  through one bridge session.

### Fixed

- **Save to Disk failed silently (review 17 P0-2).** A File Cache Save to Disk press
  into a directory that could not be created returned success. The press now checks the
  output files and fails with `cook_failed` listing the missing ones.
- **Callback menus (review 17 P1-4).** Setting `pyrosource` `initialize` stored the token
  and skipped the callback that fills the attribute multiparm, so the sim sourced nothing,
  and `press` refused menus. See `press` above.
- **`geo_info` on sims (review 17 P1-7).** `geo_info` listed only 3 of a pyro sim's 6
  volumes. It now lists every volume and VDB as a compact row under `volume_columns` and
  `vdb_columns` (at most 100 each, with `volume_total` or `vdb_total` beyond that).
  Detail attribute values that are `hou` vectors and matrices come back as lists, and a
  dict over 200 characters as `{elided, keys}`; a pyro sim's `volvis` dict had been about
  1,350 B.
- **`render` on Cop nodes (review 18 papercuts 2, 7).** `render` on a Cop node that is
  not a ROP pointed at Karma. Its error now lists the `rop_image` nodes in the network as
  `candidates`. COP image ROPs no longer get the "Scene has no lights" note.
- **`render` thumbnails of TIFFs (review 18).** A thumbnail PIL cannot read (a float
  TIFF) is converted with `iconvert`. If that fails too, a note says why; the raw
  `thumbnail_error` field is gone.
- **Menu labels with icon markup (review 18 papercut 9).** Copernicus labels such as
  `![BUTTONS_blendmode_over]Over` lose the `![…]` prefix.
- **`/stage` save-time writes (review 18 papercut 10).** `hip_save` no longer records
  Houdini's save-time writes on `/stage` as `origin: agent` events. TOP networks were
  already excluded.
- **`houdini_connect` to a dead pid (review 19 papercut 9).** It answered
  `houdini_offline` with `retryable: true` and bare pid strings. A pid or name that is not
  running is now `retryable: false` with labelled candidates `{pid, label, ui, hip}`.
- **The shipped prompts (review 19 §5).**
  - `inspect_scene` reads `houdini://outline` (or `network_describe format: outline`),
    then `problems`, and asks which Houdini to inspect when several run. In review 19 it
    cost about five times as much.
  - `build_sop_chain` ends with `viewport_capture {"fit": "all"}`.
  - `debug_red_node` drops the mandatory `problems`/`cook` and names wrangle spare parms.
  - `turntable_preview` turns the target's display flag on, hides other displayed
    objects for the captures, captures at the camera's resolution and leaves the playbar
    range alone.
- **"Nearly black" on sparse flipbooks (review 20 N1).** The note is measured on the
  flattened thumbnail the agent receives, not the transparent RGBA file; a fully
  transparent frame says "empty" instead.
- **`node_create` parms skipped callbacks silently (review 20 N2).** A plain set of a
  callback menu or toggle carries `parm_set`'s note, and `{value, press: true}` runs the
  callback once the inputs are wired, with `side_effects`.
- **Render `job result` listed every path (review 20 N5).** Above 5 outputs, the direct
  result and `job result` both return `outputs_summary` and `outputs_sample` (first 2,
  last 2); `missing` keeps up to 20 paths.
- **`cook profile` called a cache read a re-simulation (review 20 N3).** `resimulated`
  comes from the DOP solve stats of `hou.perfMon`, and is `null` with a note when nothing
  reliable says.
- **Job status details (review 20 N7, review 17 mentions).** `message` counts the frames
  done as `current` does, frames print as integers, a cancelled job's `last_status` says
  `cancelled`, a late `job cancel` returns `cancelled: false` with a note, and
  `node_create` flags deprecated types such as the 22.0 OpenGL ROP.
- **File Cache `output` hint (review 20 N4).** It names `filemethod: "explicit"`, the
  token `parm_set` takes, instead of the index 1.
- **Version string (review 20 N6).** The package, `hocuspocus version`, `bridge_version`
  and `host_version` say 1.3.0.

### Upgrading from 1.2

An agent prompt or script written for 1.2 may need these changes:

- **Pin an instance when running several.** Call `houdini_connect {"pid": N}` (or
  `{"pid": N, "name": "worker"}`, then `{"name": "worker"}`) before changing a scene.
  Expect `ambiguous_instance` until you do. After a pinned Houdini exits, expect
  `instance_lost` on every call until you call `houdini_connect` again.
- **Job ids** look like `61900-9c3e6f7ca53e`. Treat them as opaque strings and pass them
  back unchanged. `job {action: "list"}` shows the selected Houdini's jobs; add
  `all: true` for every instance's.
- **`events` cursors** are strings (`"3084:42"`). Pass `next_since` back as `since`
  instead of the last `seq`, and handle `reset: true`. Read `components` and `keyed` on
  `ParmTupleChanged` instead of `count`.
- **Press results.** A pressed button returns `pressed` and `side_effects`, not `value`.
  A save-button press that writes nothing is now an error. To write a cache as a job with
  progress and cancel, `render` the File Cache instead of pressing its button.
- **Small clients** can set `profile = "minimal"` in `hocuspocus.toml` (which the bridge
  and the host both read) to list 14 tools. Argument detail that left `tools/list` is in
  `hocuspocus://tools`.

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
