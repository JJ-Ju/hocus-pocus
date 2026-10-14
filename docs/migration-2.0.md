# Migrating from 1.4 to 2.0

HocusPocus 2.0 changes the tool surface. Reads become one tool (`inspect`) plus
`search`, and every read is also a resource with an ETag. Scene changes become one
transaction tool (`edit`). Pictures become one tool (`look`). The default `core` profile
lists 18 tools instead of 31. Scenes, the install commands, the configuration file, the
error codes and the host protocol are unchanged.

You have two ways to upgrade:

- **Keep 1.4 scripts running as they are.** Set `profile = "compat_1x"` (below). The 1.4
  catalogue, schemas and results come back unchanged, running on the 2.0 engines. This
  profile is served for the 2.0.x releases only; **2.1 removes it**.
- **Move to the 2.0 names.** Use the table below. Agents pick them up from the server
  instructions and `hocuspocus://guide` without anything on your side.

The design is in [`BIBLE.md`](BIBLE.md) (2.0) and its Appendix A (the 1.4 tools as
`compat_1x` serves them); the full list of changes is in
[`CHANGELOG.md`](../CHANGELOG.md).

## 1. Every removed tool and its replacement

These 18 tools are not in the 2.0 profiles (`minimal`, `core`, `full`). Called there, each
answers `invalid_argument` with its replacement in `hint` and the `compat_1x` setting that
keeps it. Every other 1.4 tool (`houdini_status`, `houdini_connect`, `hip_*`,
`node_create`, `parm_set`, `cook`, `render`, `houdini_python`, `job`, `undo`, `time`,
`hda`, `pdg`, `events`) keeps its name and arguments.

| 1.4 tool | 2.0 replacement | 1.4 call | 2.0 call |
|---|---|---|---|
| `node_find` | `search kind: nodes` | `node_find {"root": "/obj", "type": "*wrangle*", "has_errors": true}` | `search {"kind": "nodes", "root": "/obj", "query": "*wrangle*", "has_errors": true}` |
| `node_info` | `inspect what: node` | `node_info {"paths": ["/obj/geo1/box1"], "include": ["parms", "errors"]}` | `inspect {"what": "node", "target": "/obj/geo1/box1", "include": ["parms", "errors"]}` |
| `node_delete` | `edit` `delete` op | `node_delete {"paths": ["/obj/geo1/box1"]}` | `edit {"ops": [{"op": "delete", "paths": ["/obj/geo1/box1"]}]}` |
| `node_edit` | `edit` `node` op | `node_edit {"items": [{"path": "/obj/geo1/box1", "name": "base", "flags": {"display": true}}]}` | `edit {"ops": [{"op": "node", "path": "/obj/geo1/box1", "name": "base", "flags": {"display": true}}]}` |
| `node_copy` | `edit` `copy` op | `node_copy {"paths": ["/obj/geo1"], "to_parent": "/obj", "names": ["geo2"]}` | `edit {"ops": [{"op": "copy", "paths": ["/obj/geo1"], "to_parent": "/obj", "names": ["geo2"]}]}` |
| `node_connect` | `edit` `connect` op | `node_connect {"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/xform1", "to_input": 0}]}` | `edit {"ops": [{"op": "connect", "from": "/obj/geo1/box1", "to": "/obj/geo1/xform1", "to_input": 0}]}` |
| `node_layout` | `edit` `layout` op | `node_layout {"parent": "/obj/geo1"}` | `edit {"ops": [{"op": "layout", "parent": "/obj/geo1"}]}` |
| `network_describe` | `inspect what: network` (`format: data`) or `what: outline` | `network_describe {"root": "/obj/geo1"}`; `network_describe {"root": "/", "format": "outline", "depth": 2}` | `inspect {"what": "network", "target": "/obj/geo1"}`; `inspect {"what": "outline", "depth": 2}` |
| `network_build` | `edit` `build` op | `network_build {"parent": "/obj/geo1", "data": {...}, "press": {"src": ["initialize"]}}` | `edit {"ops": [{"op": "build", "parent": "/obj/geo1", "data": {...}, "press": {"src": ["initialize"]}}]}` |
| `parm_get` | `inspect what: parms` | `parm_get {"paths": ["/obj/geo1/box1/size"], "include": ["keys"]}` | `inspect {"what": "parms", "target": "/obj/geo1/box1/size", "include": ["keys"]}` |
| `problems` | `inspect what: problems` | `problems {"root": "/obj"}` | `inspect {"what": "problems", "target": "/obj"}` |
| `geo_info` | `inspect what: geo` (`what: image` on a Cop node) | `geo_info {"path": "/obj/geo1/OUT", "attributes": "names"}` | `inspect {"what": "geo", "target": "/obj/geo1/OUT", "attributes": "names"}` |
| `geo_read` | `inspect what: geo` with `rows: true` | `geo_read {"path": "/obj/geo1/OUT", "class": "point", "attribs": ["P"], "count": 10}` | `inspect {"what": "geo", "target": "/obj/geo1/OUT", "rows": true, "class": "point", "attribs": ["P"], "count": 10}` |
| `viewport_capture` | `look` (§5) | `viewport_capture {"lop_path": "/stage/OUT", "source": "flipbook_rop"}` | `look {"target": "/stage/OUT"}` |
| `node_type_search` | `search kind: types` | `node_type_search {"query": "scatter", "category": "Sop"}` | `search {"kind": "types", "query": "scatter", "category": "Sop"}` |
| `node_type_info` | `inspect what: type` | `node_type_info {"type": "Sop/scatter", "parms": "*density*"}` | `inspect {"what": "type", "target": "Sop/scatter", "parms": "*density*"}` |
| `selection` | `edit` `select` op (to set it) | `selection {"paths": ["/obj/geo1/box1"]}` | `edit {"ops": [{"op": "select", "paths": ["/obj/geo1/box1"]}]}` |
| `usd_stage` | `inspect what: stage` | `usd_stage {"lop_path": "/stage/OUT", "summary": true}` | `inspect {"what": "stage", "target": "/stage/OUT", "summary": true}` |

Notes on the table:

- **Results.** `inspect` returns `{what, target, etag, ...}` followed by exactly the 1.4
  read's result, so code that reads `nodes`, `parms` or `point_count` keeps working after
  stripping the three new keys. `search` adds `kind`. `search kind: types` pages
  (`next_cursor`), which `node_type_search` did not.
- **The path argument is `target`** for every `inspect`: `paths`, `root`, `path`,
  `lop_path` and `type` become `target` (`paths` is still accepted for `node` and
  `parms`). Passing a 1.4 name answers `invalid_argument` with the corrected call in
  `hint`, for example `inspect takes the path as target: inspect {"what": "geo",
  "target": "/obj/geo1/OUT"}`. `node_find`'s `type` glob is `search`'s `query`.
- **`edit` returns one row per op and one summary row per touched node**: `results:
  [{op, id?, path, ...}]` and `nodes: [{path, type, errors, warnings, cook_state,
  cook_ms}]`, not the per-tool shapes of 1.4. The row fields are the 1.4 ones (`deleted`,
  `old_path`, `spare_parms`, `paths`, `created`, `pressed`, `selected`). `return: "full"`
  gives the 1.4 full rows.
- **Several changes are one call.** 1.4 needed a tool per noun; `edit` takes them all, in
  order, as one undo step. An op's `id` is `$id` in later ops' path fields:

  ```json
  {"ops": [{"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
           {"op": "create", "id": "grid", "parent": "$geo", "type": "grid"},
           {"op": "create", "parent": "$geo", "type": "mountain",
            "inputs": [{"index": 0, "from": "$grid"}], "flags": {"display": true}},
           {"op": "set", "path": "$grid/size", "value": [10, 10]}]}
  ```

  `dry_run: true` validates every op against the scene and returns the plan with resolved
  paths, changing nothing. A failing op rolls the whole call back unless `partial: true`.
- **`network_describe {format: "python"}`** has no `inspect` form. Use
  `houdini_python {"code": "hou.node('/obj/geo1').asCode(brief=True)"}`.
- **Reading the selection.** `selection {}` read `hou.selectedNodes()`; in 2.0 use
  `houdini_python {"code": "[n.path() for n in hou.selectedNodes()]"}`.
- **`node_create` and `parm_set` stay** in every profile with their 1.4 arguments and
  results. They now run on the same engine as `edit`.

## 2. Profiles and configuration

| 1.4 `profile` | Tools in 1.4 | 2.0 `profile` | Tools in 2.0 |
|---|---:|---|---:|
| `minimal` | 14 | `minimal` | 10: `houdini_status`, `houdini_connect`, `hip_open`, `hip_save`, `inspect`, `search`, `edit`, `node_create`, `parm_set`, `look` |
| `core` (default) | 31 | `core` (default) | 18: `minimal` plus `hip_new`, `hip_merge`, `cook`, `render`, `houdini_python`, `job`, `undo`, `time` |
| `full` | 35 | `full` | 21: `core` plus `hda`, `pdg`, `events` |
| — | — | `compat_1x` | 35: the 1.4 `full` catalogue, unchanged |

`v2`, the preview profile of the 2.0 development branch, reads as `full` in 2.0.x.

To keep 1.4 client scripts running unchanged, set the profile for **both** processes, the
bridge and the host inside Houdini, then restart Houdini:

```toml
# $HOUDINI_USER_PREF_DIR/hocuspocus.toml (both processes read it)
profile = "compat_1x"
```

or `HOCUSPOCUS_PROFILE=compat_1x` in the environment of the bridge and of Houdini (the
environment wins over the file). For one client only:

```bash
claude mcp add -s user hocuspocus -e HOCUSPOCUS_PROFILE=compat_1x -- hocuspocus-mcp
```

A host and a bridge on different profiles disagree about what exists: the host refuses a
tool outside its own profile with `invalid_argument` naming the profile that serves it.
`hocuspocus doctor` prints which `hocuspocus.toml` the bridge reads.

`compat_1x` serves the 1.4 resources (`houdini://nodetype/...`, `houdini://job/{id}`,
`.../parms`, `.../geo`), the four 1.4 prompts and the 1.4 instructions. It does not
serve the 2.0 additions: `on`, `role`, resource ETags and subscriptions, or ledger job ids.

Everything else in `hocuspocus.toml` is unchanged (`allow_python`, `read_only`,
`approved_roots`, `max_response_bytes`, `default_timeout_s`, `job_threshold_s`, `hfs`,
`result_content`, `autostart`, `log_level`).

## 3. Resources

| 1.4 resource | 2.0 resource |
|---|---|
| `houdini://status` | `houdini://status` (subscribable) |
| `houdini://outline` | `houdini://outline{?root,depth}` |
| `houdini://node/{path}` | `houdini://node/{path}{?include,parms,include_defaults}` (subscribable) |
| `houdini://node/{path}/parms` | `houdini://node/{path}?parms=*` (`inspect what: parms` on the node) |
| `houdini://node/{path}/geo` | `houdini://geo/{path}{?frame,class,attribs,start,count,stats}` |
| `houdini://nodetype/{category}/{name}` | `houdini://type/{category}/{name}{?parms,folder,detail}` |
| `houdini://job/{id}` | `houdini://jobs` (subscribable), or `job {"action": "status", "job_id": ...}` |
| — | `houdini://instances`, `houdini://network/{path}`, `houdini://image/{path}`, `houdini://stage/{lop}`, `houdini://types{?q}`, `houdini://problems{?root}`, `houdini://events{?since,limit}` (subscribable) |

Every 2.0 read returns `_meta.etag`. Send it back as `_meta["If-None-Match"]` and an
unchanged resource answers with no contents and `_meta.not_modified: true`.

## 4. Jobs, instances and events

- **Job ids are opaque.** On the 2.0 profiles a `job_id` is the bridge ledger's id, such
  as `j3f9a1c`, instead of 1.4's `<pid>-<id>`. Treat it as a string. `job` still accepts a
  `<pid>-<id>` id in every profile, and `compat_1x` keeps returning them.
- **Jobs survive a bridge restart.** The ledger (`<state_dir>/ledger.sqlite`) remembers
  every job and where it runs. After a restart, `job` with a ledger id still reaches its
  Houdini, and a finished job's stored result is returned with a note. A job is still
  lost when its Houdini exits: `job status` then answers `instance_lost` with the last
  status.
- **Roles and `on`.** Every Houdini has a role, `editor` (GUI) or `worker` (headless).
  `houdini_connect {"role": "worker"}` pins the least busy worker, and `cook`, `render`,
  `look` and `job` take `on` (a pid, a name or a role) to run on another Houdini without
  moving the pin. In 1.4 the same hand-off needed a re-pin before and after each render.
  `edit` and `hip_*` have no `on`: a scene change always lands on the pinned Houdini.
- **`houdini_status`** adds `role` to every instance and `recent`, the Houdinis that ran
  recently and exited.
- **`events` cursors are unchanged.** `next_since` is still `<pid>:<seq>`; pass it back
  as `since`. `inspect {"what": "events", "since": ...}` and the `houdini://events`
  resource read the same buffer.

## 5. `look` instead of `viewport_capture`

`look` answers "show me" and picks the renderer from `quality`, where `viewport_capture`
asked the agent to pick a source.

| | `viewport_capture` (1.4) | `look` (2.0) |
|---|---|---|
| What to show | `lop_path`, `cop_path`, or nothing for `/obj` | `target`: an object, SOP, LOP, Cop node or ROP; omitted, the display (`/obj`, or the `/stage` display LOP when `/obj` shows nothing) |
| Renderer | `source: auto \| viewer \| flipbook_rop \| opengl_rop` | `quality: draft \| lit \| final`; `source: viewer` only for the GUI's own view |
| Default in a GUI session | the Scene Viewer as the user left it (`source: auto`) | a Flipbook ROP framed on the target (`draft`); the viewer only when asked |
| Lights | the Flipbook ROP's defaults | `lit`: the scene's lights with shadows, or Karma at 2 samples with a note when there are none |
| Karma | only as the last fallback, or through `render` | `final`: Karma at the target ROP's samples, else 32 |
| COP image | `cop_path` | `target` set to the Cop node or COP network |
| Result keys | `source_used` (`viewer`, `flipbook_rop`, `opengl_rop`, `karma`) | `backend_used` (`viewer`, `flipbook`, `opengl`, `karma`, `rop_image`), `chain`, `quality` |

Typical rewrites:

| 1.4 | 2.0 |
|---|---|
| `viewport_capture {}` (GUI: the viewer as it is) | `look {"source": "viewer"}` |
| `viewport_capture {"fit": "all"}` | `look {}` |
| `viewport_capture {"camera": "/obj/cam1", "frame": 24}` | `look {"camera": "/obj/cam1", "frame": 24}` |
| `viewport_capture {"lop_path": "/stage/OUT"}` | `look {"target": "/stage/OUT"}` |
| `viewport_capture {"cop_path": "/img/net/blend1"}` | `look {"target": "/img/net/blend1"}` |
| `render` a temporary Karma ROP for one lit frame | `look {"target": "/stage/OUT", "quality": "final"}` |

A look leaves no nodes, undo step or dirty flag, as `viewport_capture` did. For a sequence
of frames on disk, `render` a Flipbook ROP as before.

## 6. Dirty and unsaved changes

In 1.4 the GUI reported Houdini's own `hasUnsavedChanges()`, which HocusPocus's temporary
nodes set: after a mere capture, `node_type_info` or `render {output}`, `hip_new`,
`hip_open` and `houdini_connect {quit}` with `on_unsaved: "fail"` refused, and `pdg cook`
called the scene unsaved, in the GUI only. 2.0 has one dirty flag in both modes: the
agent's own changes, or a change the user (or Houdini) made outside HocusPocus since the
last save, load or clear. A read or a look never makes the scene dirty.
`houdini_status` reports why under `hip.dirty_source` (`tracked`, `user_event`,
`houdini_flag`), and an `unsaved_changes` error carries it in `detail.dirty_source`. A
script that saved defensively before `hip_open` in the GUI no longer needs to.

## 7. What did not change

- The three install commands, `hocuspocus launch`, `hocuspocus doctor` and the Houdini
  package. Run `hocuspocus install-houdini` after upgrading and restart Houdini, as for
  every release.
- The host protocol is still `hp/v1` for calls, so a 1.4 bridge and a 2.0 host still talk
  to each other for the 1.4 tools.
- Error codes: the set is the same. The new cases (an option `inspect` does not take, a
  `$id` no op produced, a removed tool) are `invalid_argument`.
- Pins (`ambiguous_instance`, `instance_lost`, no silent switch), the response budget,
  cursors, `result_content`, undo labels and every Houdini behaviour in the bible's §5.

## 8. What 2.1 removes

- The `compat_1x` profile and with it the 18 tools of §1 and the 1.4 resources and
  prompts.
- The `v2` profile alias.
- The OpenGL ROP backend of `look`, once Houdini 22.5 is the oldest supported version
  (Houdini 22 deprecates the OpenGL ROP for the Flipbook ROP).

Move scripts to the 2.0 names during 2.0.x. A 2.0 profile names each removed tool's
replacement in the error `hint`, so running a 1.4 script once on `core` lists what to
change.
