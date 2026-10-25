# Migrating from 2.0 to 2.1

2.1 keeps the 2.0 tool contract. Most clients need no change. This page lists what a 2.0
client script or prompt can notice, in the order it is most likely to matter. The full
list is in `CHANGELOG.md` under 2.1.0, and the reasons are decisions D45 to D67 in
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
- **`edit` validation** and `dry_run` refuse what the run would: wrong value types,
  menus and ranges, sets inside a locked asset, a `patch` that does not match (D49).
- **`hda create` and `save`** refuse a library whose extension does not match the
  licence: `.hdalc` on Indie, `.hdanc` on Apprentice and Education, `.hda` on
  Commercial. The error names the corrected path.
- **Karma `render` in a GUI session** waits for the image. 2.0 returned `done` with the
  outputs missing.

## 4. New, and worth adopting

- `hda` is in the default `core` profile, with `uninstall`, `info`, `interface`, `help`
  and `lock`. HDA work no longer needs `houdini_python`.
- `edit` `set` takes `patch: [{find, replace}]` and `value_file` for long VEX and Python
  parms. `inspect {full_strings: true}` reads them back whole.
- `path` names the node of every `edit` op. The 2.0 keys still work.
- `look {output}` saves the picture to a file.
- `inspect {what: "guide"}` and `inspect {what: "tool", target}` read the guide and a
  tool's reference without an MCP resource reader.
