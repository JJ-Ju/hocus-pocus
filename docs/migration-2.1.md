# Migrating from 2.0 to 2.1

2.1 keeps the 2.0 tool contract. Most clients need no change. This page lists what a 2.0
client script or prompt can notice, in the order it is most likely to matter. The full
list is in `CHANGELOG.md` under 2.1.0, and the reasons are decisions D45 to D86 in
`docs/BIBLE.md`.

## 1. Removed: `compat_1x`, the `v2` alias and the 1.4 tools

2.0 served the 1.4 catalogue under `profile = "compat_1x"` for one minor release. 2.1
removes it, as `docs/migration-2.0.md` §8 announced.

- `profile = "compat_1x"` or `"v2"` in `hocuspocus.toml`, or in `HOCUSPOCUS_PROFILE`, is
  read as `full`. The bridge and the host log a warning, and `houdini_status` returns it
  in `warnings`. Nothing refuses to start. Set `profile = "full"` (or remove the line for
  `core`) to silence it.
- Calling one of the 18 1.4 tools answers `invalid_argument` on every profile. The
  `hint` names the 2.0 call and `detail.replacement` the tool. `docs/migration-2.0.md` §1
  maps each one.
- The 1.4 resources `houdini://node/{path}/parms`, `houdini://node/{path}/geo`,
  `houdini://nodetype/{category}/{name}` and `houdini://job/{id}` are gone. Read the same
  through `inspect` (`parms`, `geo`, `type`, `jobs`).
- Read-only mode refuses `edit {ops: [{op: "select"}]}`. 1.4's `selection` tool was
  allowed there.

## 2. Result fields that 2.1 leaves out

Each dropped field was a default, a null, or a copy of a field that stays.

| Tool | Field no longer returned | Read instead |
|---|---|---|
| `houdini_status` | `hip.dirty_source` when null, `hip.is_new` when false | absent means null or false |
| `houdini_status` | `time.playback_range` when equal to `range` | `time.range` |
| `houdini_status` | `host_version` when equal to `bridge_version` | `bridge_version`; a mismatch is still a `version_mismatch` warning |
| `houdini_status` | `read_only: false`, `allow_python: true`, `launched_by: null` | absent means the default |
| `houdini_status` | `hip.recent` past the newest three | `houdini_status {detail: true}` |
| `houdini_status` | the connected row's `port`, `label`, `houdini`, `started`, `generation` in `instances[]` | `connected`; `houdini://instances` keeps whole rows |
| `houdini_connect` | `launched.mode`, `connected.memory` | `connected.ui`; `houdini_status {detail: true}` |
| `hip_new`, `hip_open`, `hip_save` | `name`, and `is_new` when false | the last segment of `path` |
| `render` | `outputs_summary.first` and `.last` over 5 outputs | the first and last entries of `outputs_sample` |

## 3. Behaviour that changed

- **Modal dialogs in a GUI session.** A `hou.ui` dialog opened by `houdini_python` code, a
  pressed parm callback, a creation script or a hip load script answers `ui_required`
  instead of blocking Houdini. Code that relied on a person answering a dialog during a
  call has to take the answer as an argument instead (D45).
- **`look` at a SOP** shows that SOP alone. 2.0 moved the display flag and showed the
  whole object. The user's flags no longer move (D52).
- **`look` resolution** is honoured on Karma, and through an OBJ camera without
  `resolution` the look takes the camera's aspect.
- **`cook {profile: true}`** times only what a normal cook of the target cooks. What it
  skipped is in `inactive` (D53).
- **`inspect` options** that only shape the answer are ignored with a note when a `what`
  does not take them, where 2.0 answered `invalid_argument` (D51).
- **`edit` checks each op by running it** after the earlier ones (D56). An op may now
  depend on what an earlier op of the same call did (an unlock, a multiparm count, a
  rename, a new node's outputs), and `dry_run` refuses exactly what the run would: it runs
  the ops in check mode and takes them back, so its `plan` paths are the names Houdini
  really gives (`transform1`, where 2.0 predicted `xform1`). A dry run of a large build
  now takes tens of milliseconds instead of a few, and in a GUI session it may set
  Houdini's own modified flag (not `dirty`). In a dry run and after a failing op a
  `press` runs no callback, so a callback's effects are not checked.
- **`edit` errors name the key the caller sent** (`ops[0].path` for an op given `path`).
  A misspelt parm on a create hints the new node's own parm (`Did you mean size?`).
- **`edit` cooks after the change** (D58). Rows still carry the errors of each touched
  node, but a cook that outlasts `job_threshold_s` (10 s) no longer holds the call: its
  rows say `cook_state: "cooking"` and the result adds `job_id`, `state: "running"` and a
  `message`; `job {action: result, job_id}` returns those rows. A client that read
  `state` only on `cook` and `render` results should read it on `edit` too.
- **`hda create` and `save`** refuse a library whose extension does not match the
  licence: `.hdalc` on Indie, `.hdanc` on Apprentice and Education, `.hda` on
  Commercial. The error names the corrected path.
- **Karma `render` in a GUI session** waits for the image. 2.0 returned `done` with the
  outputs missing.
- **A press can answer as a job** (D70). A pressed callback still running after
  `job_threshold_s` returns `{job_id, state: "running", running}` from `edit`,
  `parm_set` and `node_create`, without the rows; `job {action: result, job_id}`
  returns them. A client that read `results` or `nodes` unconditionally should check
  `state` first, as on `cook` and `render`. `parm_set`'s output schema no longer
  requires `results`.
- **`look` can answer as a job** (D75). Past `wait_s` (default 10 s, where 2.0 waited
  the call's 30 s and then failed) `look` returns `{job_id, state: "running"}`;
  pass `wait_s: 60` to keep a slow look synchronous. Its output schema no longer
  requires the picture fields.
- **Headless Karma `render`** runs in a child hython (D74): about 1.4 s more per call,
  the scene cooks again there, and a take other than the root or a simulation held
  only in memory is not carried (a note says so). The ROP in the scene is no longer
  touched while it renders.
- **Menu `candidates`** are ranked by similarity to the value and list a menu of up
  to 50 items whole (D72); 2.0 gave the first 20 in menu order.
- **`cook {force: true}` presses the node's Reload button** first when it has one, and the
  row adds `reloaded: true` (D80). A forced cook of a File COP now reads the file again;
  one of an Alembic or agent SOP clears its cache as the button does.
- **`cook`'s `force` schema** is `false | true | "chain"` (D81); a client that builds
  arguments from the schema should not assume a boolean.
- **New keys in reads** a strict client may see: `disable_when` / `hide_when` in `inspect
  parms` and `inspect type` rows with `detail: full`, `interface.conditionals` in `hda
  info` (D82); `relationships` and `subsets` in `inspect stage` rows that list attributes
  or bindings (D84); `hint` on `problems` rows (D81); `notes` on `inspect {what:
  "image"}`; `output_bytes` with `look {output}` (D86). `help_source` of an asset is
  `<library>:HelpText` rather than absent (D83).
- **A comma in a `parms` or stage `attribs` glob** separates alternatives (D85); 2.0 read
  it as part of one name and matched nothing.

## 4. New, and worth adopting

- `hda` is in the default `core` profile, with `uninstall`, `info`, `interface`, `help`
  and `lock`. HDA work no longer needs `houdini_python`.
- `edit` `set` takes `patch: [{find, replace}]` and `value_file` for long VEX and Python
  parms. `inspect {full_strings: true}` reads them back whole.
- `path` names the node of every `edit` op. The 2.0 keys still work.
- `edit {partial: "stop"}` keeps the ops before the first failure and runs none after it;
  the result says `applied` (D57). Resend `ops[applied:]` with their `$id`s replaced by
  the result's `ids`.
- Inside a subnet, `connect {from: <the subnet>, from_output: i}` wires the subnet's own
  input `i` (D59).
- `edit` flags `material` (VOPs: what a Material Library LOP imports), `unload` and
  `export`; a MaterialX VOP's `signature` takes every signature its definition lists
  (D68).
- `look {output}` saves the picture to a file, and `look {wait_s}` keeps a long look
  as a job instead of failing.
- `inspect {what: "geo", group_by: "surface", attribs: "Cd"}` answers per-value QA
  questions (counts, triangles, area, bbox, attribute ranges) in one call (D71).
- `hda {action: "version", path, version: "1.1", switch: "path"}` bumps an asset's
  version without `houdini_python` (D73).
- `inspect {what: "guide"}` and `inspect {what: "tool", target}` read the guide and a
  tool's reference without an MCP resource reader.
- `cook {force: "chain"}` recooks a node's inputs as well (D81), and `look {output:
  "x.jpg", jpeg_quality: 80}` sets the JPEG's size (D86).
