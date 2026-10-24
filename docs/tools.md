# HocusPocus tools

<!-- Generated from src/hocuspocus/tools/spec/ by `python -m hocuspocus.tools.docs`. Do not edit by hand. -->

21 tools. The profiles nest: 10 in `minimal`, 18 in `core` (the default), 21 in `full`. Model-visible `tools/list` text: 20,639 bytes. See `docs/BIBLE.md` §4 for the design.

## Contents

- [`houdini_status`](#houdini_status) *(minimal)*
- [`houdini_connect`](#houdini_connect) *(minimal)*
- [`hip_new`](#hip_new)
- [`hip_open`](#hip_open) *(minimal)*
- [`hip_save`](#hip_save) *(minimal)*
- [`hip_merge`](#hip_merge)
- [`inspect`](#inspect) *(minimal)*
- [`search`](#search) *(minimal)*
- [`edit`](#edit) *(minimal)*
- [`node_create`](#node_create) *(minimal)*
- [`parm_set`](#parm_set) *(minimal)*
- [`cook`](#cook)
- [`render`](#render)
- [`look`](#look) *(minimal)*
- [`houdini_python`](#houdini_python)
- [`undo`](#undo)
- [`time`](#time)
- [`job`](#job)
- [`hda`](#hda) *(full)*
- [`pdg`](#pdg) *(full)*
- [`events`](#events) *(full)*

## houdini_status

`read-only` `bridge-local` `headless ok` · profiles `minimal`, `core`, `full`

Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and dirty state, $HIP/$JOB, frame, recent files, scene_generation), every live instance and the bridge settings. Works with no Houdini running (connected: null).

**Notes.** Also reports $HIPNAME, fps, the frame range, and the bridge's profile, read_only and allow_python. An untitled scene's hip carries a note that $HIP is the launch directory until hip_save. Each instances[] row has pid, port, label, houdini, ui, hip, started, launched_by, name (when given), selected (the pinned instance, or the one reads go to), busy (the main thread has been held for over a second) and jobs_running. With several instances and none pinned, tools that change a scene refuse with ambiguous_instance: pin one with houdini_connect {pid}. When the pinned Houdini has exited, connected is null and lost: {pid, label} names it. connected.memory is {rss_mb, peak_mb}: the Houdini process's resident and peak memory (watch it while a sim cache fills). profile is minimal, core or full; a removed profile name in the config (compat_1x, v2) reads as full with a warning in warnings. (2.0, spec-2.0 §2.1) every instances[] row and connected carry role, editor (the default for a GUI Houdini) or worker (headless), as houdini_connect {role} set it; recent lists up to 5 Houdinis the bridge ledger remembers that are no longer running, most recently seen first, each {pid, label, ui, role, hip (its last hip file), started, last_seen, alive: false, name?}. The ledger survives a bridge restart. Defaults and empties are left out (2.0): role when it is the mode's default (editor for a GUI Houdini, worker headless), name when unset, and on instances[] rows selected: false, busy: false and jobs_running: 0; recent when no dead Houdini is remembered; connected.memory unless detail: true (so two reads of an unchanged session match, and houdini://status, shaped the same, keeps its etag). The hip path is printed once, as connected.hip.path: what only repeats it is left out (hip.name, a hip.recent entry equal to it, env.HIP when it is the path's folder, env.JOB when it is that folder too, env.HIPNAME, an empty env, and hip on the connected instance's row and on recent rows).

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `detail` | boolean |  | `false` |  |

### Returns

- `connected` (object | null): `pid`, `port`, `label`, `houdini`, `ui`, `hip`, `time`, `env`, `scene_generation`, `host_version` — always present
- `instances` (array<object>): `pid`, `label`, `houdini`, `ui`, `hip`, `started`, `launched_by`, `role` — always present
- `bridge_version` (string) — always present
- `profile` (`minimal` | `core` | `full`)
- `read_only` (boolean)
- `allow_python` (boolean)
- `recent` (array<object>)

### Examples

```json
{}
```


## houdini_connect

`bridge-local` `headless ok` · profiles `minimal`, `core`, `full`

Choose the Houdini this session drives: pid attaches, launch starts one (gui or headless, optional hip), disconnect drops the selection, quit closes it. A launched Houdini usually closes with this server (launched.outlives_server says); `hocuspocus launch` starts one that outlives it.

**Notes.** pid (or launch) pins that Houdini: the pin holds until the next houdini_connect, and if it exits every call returns instance_lost rather than switching. {} unpins (automatic selection). name labels the Houdini given by pid or launch, shown in houdini_status and in _meta.instance; {name} alone pins the Houdini with that name. A pid that is not running is houdini_offline with the live candidates. launch waits up to wait_s seconds for the new host to register. A launched Houdini starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets the registry entry. To keep one alive across sessions, start it with `hocuspocus launch` and attach by pid. (2.0, spec-2.0 §2.1) role (editor or worker) sets the role of the Houdini given by pid, name or launch (default: editor for a GUI Houdini, worker for a headless one), kept in the bridge ledger across bridge restarts. {role} alone pins the least busy live Houdini with that role (fewest jobs_running, then not busy, then GUI first and newest first); none is houdini_offline with the candidates and their roles. cook, render, job and look take on: pid, name or role to run one call on another Houdini without moving the pin.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `pid` | integer |  |  | Live instance to attach to. |
| `launch` | object |  |  |  |
| `launch.mode` | `gui` \| `headless` | yes |  |  |
| `launch.hip` | string |  |  | Hip file to open. |
| `launch.wait_s` | number |  | `90` | min 1 |
| `name` | string |  |  |  |
| `disconnect` | boolean |  | `false` |  |
| `quit` | boolean |  | `false` |  |
| `on_unsaved` | `fail` \| `save` \| `discard` |  |  |  |
| `role` | `editor` \| `worker` |  |  |  |

### Examples

```json
{"pid": 12345, "name": "worker"}
```

```json
{"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}}
```

```json
{"quit": true, "on_unsaved": "save"}
```


## hip_new

`destructive` `headless ok` · profiles `core`, `full`

Clear to a new untitled scene; bumps scene_generation. on_unsaved protects unsaved work: fail returns unsaved_changes, save saves first (an untitled scene needs hip_save with path instead), discard drops the changes.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `on_unsaved` | `fail` \| `save` \| `discard` |  | `"fail"` |  |

### Returns

- `path` (string) — always present
- `name` (string)
- `dirty` (boolean)
- `is_new` (boolean)
- `saved_first` (boolean) — always present
- `scene_generation` (integer) — always present

### Examples

```json
{}
```

```json
{"on_unsaved": "save"}
```


## hip_open

`destructive` `headless ok` · profiles `minimal`, `core`, `full`

Load a hip file, replacing the current scene; on_unsaved as in hip_new. Load warnings are returned in warnings, not raised, unless ignore_load_warnings is false. hip_merge adds nodes instead.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | Hip file. |
| `on_unsaved` | `fail` \| `save` \| `discard` |  | `"fail"` |  |
| `ignore_load_warnings` | boolean |  | `true` |  |

### Returns

- `path` (string) — always present
- `warnings` (array<string>) — always present
- `scene_generation` (integer) — always present

### Examples

```json
{"path": "C:/work/shot.hip"}
```

```json
{"path": "$JOB/shot_v002.hip", "on_unsaved": "discard"}
```


## hip_save

`headless ok` · profiles `minimal`, `core`, `full`

Save the hip file. path saves as (creating directories; an untitled scene needs it); increment saves to the next version number in the file name; backup keeps a backup copy. Returns the real saved path, dirty after save, and bytes.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string |  |  | Save-as target. |
| `increment` | boolean |  | `false` |  |
| `backup` | boolean |  | `false` |  |

### Returns

- `path` (string) — always present
- `dirty` (boolean) — always present
- `bytes` (integer)

### Examples

```json
{}
```

```json
{"path": "C:/work/shot_v002.hip"}
```

```json
{"increment": true}
```


## hip_merge

`headless ok` · profiles `core`, `full`

Merge the nodes matching node_pattern from another hip file into the current scene. dry_run only reports collisions (no undo step, allowed read-only). Colliding nodes are renamed unless overwrite_on_conflict.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | Hip file to merge. |
| `node_pattern` | string |  | `"*"` |  |
| `overwrite_on_conflict` | boolean |  | `false` |  |
| `dry_run` | boolean |  | `false` |  |

### Returns

- `path` (string)
- `dry_run` (boolean)
- `collisions` (array<string>) — always present
- `merged` (array<string>)
- `scene_generation` (integer)

### Examples

```json
{"path": "C:/lib/rig.hip", "dry_run": true}
```

```json
{"path": "C:/lib/rig.hip", "node_pattern": "/obj/rig*"}
```


## inspect

`read-only` `headless ok` · profiles `minimal`, `core`, `full`

Read the scene in one tool. what: node, parms, network, outline, geo (rows: true for values), image (Cop), stage (USD), problems, type, events or jobs; target is the node, LOP, Cop or node type. Returns an etag and the matching 1.4 read (node_info, parm_get, network_describe, geo_info/geo_read, usd_stage, problems, node_type_info, events, job), compact: defaults and empties left out.

**Notes.** Each what takes its 1.4 tool's arguments; any other option is invalid_argument naming the ones it takes. The result is the 1.4 tool's, without what and target (the caller knows them). node: node_info (target or paths; include, include_defaults, recurse_locked, detail). parms: parm_get (a parm or tuple path as target, or paths; frame, include, full_strings, detail); with a node as target it reads the node's non-default parm tuples (all with include_defaults; those whose name or label match the glob parms, a|b, when given; folders, separators and buttons left out), and parms: [] when there are none. network: network_describe format data (target is root; depth, include_defaults, include_positions, recurse_locked, cursor). outline: network_describe format outline (target default /; depth, recurse_locked, cursor, wiring, detail), without format; a row leaves out name when it is the path's last segment, errors at 0, and inputs unless wiring: true. geo: geo_info (frame, attributes, detail), or with rows: true geo_read (class, attribs, start, count, group, stats, cursor, frame). image: geo_info on a Cop node or COP network (frame); another node is invalid_argument. stage: usd_stage (target is lop_path; prim, depth, include, attribs, summary, time, limit, cursor). problems: problems (target is root, default /; include_warnings, cook_uncooked, recurse_locked, timeout_s, limit, cursor, detail). type: node_type_info (target is type; category, include_parms, include_help, folder, parms, detail). events: events, no target (since, limit; next_since as with events). jobs: job list, or job status with job_id, no target. Defaults are the 1.4 tool's. Compact shapes (detail: compact, the default; detail: full restores the 1.4 shape of node, parms, outline, geo, problems and type; node rows never carry session_id): what is default or empty is omitted. node rows: name omitted when it is the path's last segment; type is Category/name (Sop/box); flags is the list of flags that are on, omitted when none; inputs are positional sources, a path (output 0), {path, output} or null, trailing unconnected ones omitted and inputs omitted when nothing is connected (detail: full gives {index, name, label, from}); outputs (only with include outputs) are positional lists of destinations, a path (input 0) or {path, input}; parms is {name: value}, or {name: {value, ...}} when more than the value matters (expression, expressions {component: text}, language when not hscript, keyed, locked, menu_token unlike the value, raw unlike the value and the expression), omitted when no parm is listed; is_default is not given; errors, warnings and messages omitted when empty, cook_state when cooked, children_count when 0. parms: {path: value or row} in the order read (keyed by tuple name when target is a node; the rows when two share a key), rows as in node plus type when not float, int, string or toggle, hda_locked when true, keyframes when any, and the include sections asked for; is_default, kind, tuple and component_names are not given. geo (summary): attributes per class as {name: type}, the type 'float3', 'float3:color' or 'int[]' (size when not 1, :type_info when set), detail attributes as {name: {type, value}} with an elided dict value as {elided, key_count}, attributes: names as name lists, empty classes omitted; groups per class as {name: count}, omitted when empty; bbox without center (the middle of min and max); volume and vdb columns with one value in every row (resolution, voxel_size, class) said once in volume_common / vdb_common; internal_attribute_count kept, its note omitted (geo_read with attribs reads those attributes); rows: true reads and images unchanged. outline: also children_count omitted when children lists that many. problems: counts omitted when empty, nodes_with_problems when 0. type (detail compact or folders): is_current_version omitted when true, version when empty, the detail: compact echo and its constant hint (detail: full adds menus, ranges, hidden parms and per-parm help), inputs_count unless detail: folders; inputs and outputs are their labels, outputs omitted when there is only the default Output 1; type with detail: full is node_type_info's full result. etag is <pid>:<scene_generation>:<16 hex>, the first 16 hex digits of a BLAKE2b digest of the result's canonical JSON (sorted keys, compact): it moves exactly when the answer does, and the matching houdini:// resource has the same etag, so a read with If-None-Match after a change that left this answer alone (a look, a cook elsewhere) is not_modified.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `what` | `node` \| `parms` \| `network` \| `outline` \| `geo` \| `image` \| `stage` \| `problems` \| `type` \| `events` \| `jobs` | yes |  |  |
| `target` | string |  |  | Node, parm, LOP, Cop or type path. |
| `paths` | array<string> |  |  | node, parms: several paths. (min items 1) |
| `include` | array<string> |  |  |  |
| `include_defaults` | boolean |  |  |  |
| `recurse_locked` | boolean |  |  |  |
| `frame` | number |  |  |  |
| `full_strings` | boolean |  |  |  |
| `parms` | string |  |  | parms, type: name or label glob. |
| `depth` | integer |  |  | min 1 |
| `include_positions` | boolean |  |  |  |
| `wiring` | boolean |  |  |  |
| `cursor` | string |  |  | next_cursor from the previous page. |
| `attributes` | `full` \| `names` |  |  |  |
| `rows` | boolean |  |  |  |
| `class` | `point` \| `prim` \| `vertex` \| `detail` |  |  |  |
| `attribs` | string \| array<string> |  |  |  |
| `start` | integer |  |  | min 0 |
| `count` | integer |  |  | min 1; max 10000 |
| `group` | string |  |  |  |
| `stats` | boolean |  |  |  |
| `prim` | string |  |  |  |
| `summary` | boolean |  |  |  |
| `time` | number |  |  |  |
| `limit` | integer |  |  | min 1; max 1000 |
| `include_warnings` | boolean |  |  |  |
| `cook_uncooked` | boolean |  |  |  |
| `timeout_s` | number |  |  | min 1 |
| `category` | `Chop` \| `ChopNet` \| `Cop` \| `Cop2` \| `CopNet` \| `Data` \| `Director` \| `Dop` \| `Driver` \| `Lop` \| `Manager` \| `Object` \| `Shop` \| `Sop` \| `Top` \| `TopNet` \| `Vop` \| `VopNet` |  |  |  |
| `include_parms` | boolean |  |  |  |
| `include_help` | boolean |  |  |  |
| `folder` | string |  |  |  |
| `detail` | `compact` \| `full` \| `folders` |  |  |  |
| `since` | integer \| string |  |  |  |
| `job_id` | string |  |  |  |

### Examples

```json
{"what": "parms", "target": "/obj/geo1/box1", "parms": "size|t"}
```

```json
{"what": "geo", "target": "/obj/geo1/OUT", "rows": true, "attribs": ["P"], "count": 5}
```

```json
{"what": "type", "target": "Sop/scatter", "parms": "*seed*"}
```


## search

`read-only` `headless ok` · profiles `minimal`, `core`, `full`

Search node types or nodes. kind types: node_type_search (query is a name, label or keyword; 1.4 ranking, synonyms, current_only). kind nodes: node_find under root (query is a type glob; pattern, category, flags, has_errors). Returns the 1.4 tool's result with compact rows, paged by limit and cursor.

**Notes.** Each kind takes its 1.4 tool's arguments; any other is invalid_argument naming the ones it takes. Defaults are the 1.4 tool's (types: limit 20, current_only true; nodes: root /, limit 50). types: query is required; the result is node_type_search's {results, common?, total, hint?, notes?}, plus next_cursor when total counts more matches than this page (node_type_search itself has no paging; a types page reaches the first 1000 matches). nodes: query (optional) is node_find's type glob, pattern its name glob; the result is node_find's {root?, nodes, common?, total, next_cursor?}. Compact (detail: compact, the default; detail: full returns {kind, ...the 1.4 result} unchanged): what is default or empty is omitted and kind is not echoed. nodes: root is omitted when the call named it; a row is {path, type}, plus flags (the list of flags that are on) when any is on, has_errors only when true, child_count and input_count only when above 0; common: {category} holds the category most rows share, and a row in another category names its type as Category/type (Object/geo); next_cursor is the last row's path (cursor takes it, or node_find's after:<path>). types: a row is {name, label, description} with description capped at 80 characters, plus inputs as 'min-max' unless 1-1, deprecated and hidden only when true, other_versions only when non-empty, current and is_current_version: false for an older version; version is not given (a namespaced version is in the name); common hoists category, child_category and typical_parents when every row shares them, and typical_parents (where a type of that category goes) also when only some rows carry it.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `types` \| `nodes` | yes |  |  |
| `query` | string |  |  | types: name or keyword; nodes: type glob. |
| `category` | `Chop` \| `ChopNet` \| `Cop` \| `Cop2` \| `CopNet` \| `Data` \| `Director` \| `Dop` \| `Driver` \| `Lop` \| `Manager` \| `Object` \| `Shop` \| `Sop` \| `Top` \| `TopNet` \| `Vop` \| `VopNet` |  |  |  |
| `root` | string |  |  |  |
| `pattern` | string |  |  | nodes: name glob. |
| `flags` | object |  |  |  |
| `flags.display` | boolean |  |  |  |
| `flags.render` | boolean |  |  |  |
| `flags.bypass` | boolean |  |  |  |
| `flags.template` | boolean |  |  |  |
| `flags.locked` | boolean |  |  |  |
| `has_errors` | boolean |  |  |  |
| `recurse_locked` | boolean |  |  |  |
| `include_hidden` | boolean |  |  |  |
| `current_only` | boolean |  |  |  |
| `limit` | integer |  |  | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |
| `detail` | `compact` \| `full` |  |  |  |

### Examples

```json
{"kind": "types", "query": "scatter"}
```

```json
{"kind": "types", "query": "noise", "category": "Vop", "limit": 5}
```

```json
{"kind": "nodes", "root": "/obj", "query": "*file*", "has_errors": true}
```


## edit

`destructive` `headless ok` · profiles `minimal`, `core`, `full`

Change the scene in one undo step. ops run in order, each {op, id?, ...}: create, delete, connect, set, node (rename, flags, color, comment, position, lock, spare_parms), copy, layout, build (hou.data), select; later ops name an earlier op's node as $id. dry_run validates, returning resolved paths. A failure rolls all back unless partial. Returns per-node rows (problems only) and ids.

**Notes.** Each op takes the fields of the 1.4 tool it replaces. create: parent, type, name, parms, inputs [{index or name, from, output}], flags, position, and per op exact_type, cook (false skips the echo's cook) and layout (good_position | none), as node_create. delete: paths (or path), keep_connections, as node_delete. connect: from (null disconnects), from_output, to, to_input (index, name or next), as node_connect. set: one parm_set item (path plus value, expression, keyframe(s), channel_ref, ramp, multiparm_count, revert_to_default or press; language, animation, frame), or {node, parms: {name: value or item}} for several parms of one node. node: path plus name, flags, bypass, color, comment, position, lock, spare_parms, as node_edit. copy: paths, to_parent, names, with_inputs, position_offset, as node_copy. layout: parent, paths, mode, as node_layout. build: parent, data, on_name_collision, layout (boolean), tag, press, as network_build. select: paths (an empty list clears). An id (letters, digits, _) names the op's node: the created node, the connect target, the set or node op's node, the single copy, the layout or build parent. $id, or $id/child and $id/parm, works in the path fields (parent, path, paths, node, from, to, to_parent, channel_ref, inputs[].from), never in parm values, and resolves to the path the op produced. Every op is validated before anything changes (types, parents and their category, parm names, inputs, free names, locked assets) against the scene as the earlier ops leave it; dry_run returns that plan, with predicted: true on a path Houdini will number. A failing op rolls the whole call back; the error names the op field, ops[i].<field>: ... (ops[i] (path) when none applies; a missing from, to or parent lists the parent's nearest children as candidates), with detail.field and detail.rolled_back as performed (a delete cannot be compensated, so the dispatcher's undo of the step decides). With partial, ops run without the up-front validation and a failing op reverts only itself. Result (return summary): nodes, one row per touched node, each cooked once after every op ran (node ops do not cook): path and type, plus errors and warnings when not empty (a list repeated downstream becomes errors_same_as), cook_state when not cooked, cook_ms from 1 ms, and the ops' results for that node (old_path, paired_with, deprecated, hda, notes, side_effects); ids {id: path} for every op id; deleted, reconnected, selected (context_changed), renamed, replaced when an op did that; failed [{item, op, id, error}] with partial. return ops adds results, one row per op (op, id, path, and what it did: set values, input and from, spare_parms, created, copies); return full gives the 1.4 full shapes (flags and messages on nodes, create parms the call set, strings over 200 characters as {elided, head}) and failed as a count. The undo label is HocusPocus: edit <n> ops.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `ops` | array<object> | yes |  | min items 1 |
| `ops[].op` | `create` \| `delete` \| `connect` \| `set` \| `node` \| `copy` \| `layout` \| `build` \| `select` | yes |  |  |
| `ops[].id` | string |  |  | Name later ops use as $id. |
| `ops[].parent` | string |  |  |  |
| `ops[].type` | string |  |  |  |
| `ops[].name` | string |  |  |  |
| `ops[].parms` | object |  |  |  |
| `ops[].inputs` | array<object> |  |  |  |
| `ops[].flags` | object |  |  |  |
| `ops[].position` | array<number> |  |  | min items 2; max items 2 |
| `ops[].exact_type` | boolean |  |  |  |
| `ops[].cook` | boolean |  |  |  |
| `ops[].layout` | string \| boolean |  |  |  |
| `ops[].path` | string |  |  |  |
| `ops[].paths` | array<string> |  |  |  |
| `ops[].keep_connections` | boolean |  |  |  |
| `ops[].from` | string \| null |  |  |  |
| `ops[].from_output` | integer |  |  | min 0 |
| `ops[].to` | string |  |  |  |
| `ops[].to_input` | integer \| string |  |  |  |
| `ops[].value` | any |  |  |  |
| `ops[].expression` | string |  |  |  |
| `ops[].language` | `hscript` \| `python` |  |  |  |
| `ops[].keyframe` | object |  |  |  |
| `ops[].keyframes` | array |  |  |  |
| `ops[].channel_ref` | string |  |  |  |
| `ops[].ramp` | object |  |  |  |
| `ops[].multiparm_count` | integer |  |  | min 0 |
| `ops[].revert_to_default` | boolean |  |  |  |
| `ops[].press` | boolean \| object |  |  |  |
| `ops[].animation` | `replace` \| `key` \| `keep` |  |  |  |
| `ops[].frame` | number |  |  |  |
| `ops[].node` | string |  |  |  |
| `ops[].color` | array<number> |  |  | min items 3; max items 3 |
| `ops[].comment` | string |  |  |  |
| `ops[].lock` | boolean |  |  |  |
| `ops[].bypass` | boolean |  |  |  |
| `ops[].spare_parms` | object |  |  |  |
| `ops[].to_parent` | string |  |  |  |
| `ops[].names` | array<string> |  |  |  |
| `ops[].with_inputs` | boolean |  |  |  |
| `ops[].position_offset` | array<number> |  |  | min items 2; max items 2 |
| `ops[].mode` | `children` \| `good_position` |  |  |  |
| `ops[].data` | object |  |  |  |
| `ops[].on_name_collision` | `error` \| `rename` \| `replace` |  |  |  |
| `ops[].tag` | string |  |  |  |
| `dry_run` | boolean |  | `false` |  |
| `return` | `summary` \| `ops` \| `full` |  | `"summary"` |  |
| `partial` | boolean |  | `false` | Keep successful items. |

### Examples

```json
{"ops": [{"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"}, {"op": "create", "id": "box", "parent": "$geo", "type": "box"}, {"op": "create", "id": "mtn", "parent": "$geo", "type": "mountain", "inputs": [{"index": 0, "from": "$box"}], "parms": {"height": 0.5}}, {"op": "create", "id": "sub", "parent": "$geo", "type": "subdivide", "inputs": [{"index": 0, "from": "$mtn"}], "parms": {"iterations": 2}}, {"op": "create", "parent": "$geo", "type": "null", "name": "OUT", "inputs": [{"index": 0, "from": "$sub"}], "flags": {"display": true, "render": true}}]}
```

```json
{"ops": [{"op": "set", "path": "/obj/terrain/box1/size", "value": [2, 1, 2]}, {"op": "connect", "from": "/obj/terrain/box1", "to": "/obj/terrain/merge1", "to_input": "next"}, {"op": "node", "path": "/obj/terrain/OUT", "comment": "final"}], "dry_run": true}
```


## node_create

`headless ok` · profiles `minimal`, `core`, `full`

Create nodes in one undo step. type resolves like createNode (box gets the current version; exact_type disables). Items may wire to earlier items; a block_end pairs with its block_begin (paired_with). Returns path, type and problems per node. network_build suits whole graphs.

**Notes.** A parms value is a literal, {expression, language} (short form {expr, lang}), or any parm_set item without path. As in parm_set, a plain set of a menu or toggle with a callback script carries a note that the callback did not run; {value, press: true} runs it once the node's inputs are wired, and the row adds side_effects: {parm: [old, new]}. A type hou.NodeType.deprecated() reports (the OpenGL ROP in 22.0) gets deprecated: true and a note with its reason or replacement (the note once per type per Houdini session). An input is {index or name, from, output (default 0)}. layout good_position places new nodes. return full gives node_info blocks listing only the parms the call set, with strings over 200 characters as {elided, head}; identical error lists after the first become errors_same_as. Each new node is cooked once to report its problems, and its row carries cook_ms (a first cook of an HDA such as mountain can take 200 ms); cook: false skips that cook (cook_state: not_cooked), for batch builders that cook once at the end.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | array<object> | yes |  | min items 1 |
| `items[].parent` | string | yes |  |  |
| `items[].type` | string | yes |  |  |
| `items[].name` | string |  |  |  |
| `items[].parms` | object<string, string \| number \| boolean \| array<string \| number \| boolean> \| object \| object> |  |  | Parm name to a value or a parm_set item without path. |
| `items[].inputs` | array<object> |  |  | each item: exactly one of index, name |
| `items[].inputs[].index` | integer |  |  | min 0 |
| `items[].inputs[].name` | string |  |  | Input name. |
| `items[].inputs[].from` | string | yes |  | Source node. |
| `items[].inputs[].output` | integer |  | `0` | min 0 |
| `items[].flags` | object |  |  |  |
| `items[].flags.display` | boolean |  |  |  |
| `items[].flags.render` | boolean |  |  |  |
| `items[].flags.bypass` | boolean |  |  |  |
| `items[].flags.template` | boolean |  |  |  |
| `items[].position` | array<number> |  |  | [x, y] (min items 2; max items 2) |
| `layout` | `good_position` \| `none` |  | `"good_position"` |  |
| `exact_type` | boolean |  | `false` |  |
| `cook` | boolean |  | `true` |  |
| `partial` | boolean |  | `false` | Keep successful items. |
| `return` | `full` \| `summary` |  | `"summary"` |  |

### Examples

```json
{"items": [{"parent": "/obj", "type": "geo", "name": "terrain"}]}
```

```json
{"items": [{"parent": "/obj/terrain", "type": "grid", "parms": {"size": [10, 10], "rows": 100, "cols": 100}}, {"parent": "/obj/terrain", "type": "mountain", "inputs": [{"index": 0, "from": "/obj/terrain/grid1"}], "parms": {"height": {"expression": "ch('../grid1/sizex') * 0.1"}}, "flags": {"display": true, "render": true}}]}
```


## parm_set

`idempotent` `headless ok` · profiles `minimal`, `core`, `full`

Set parms in one undo step. Each item takes one of value, expression, keyframe(s), channel_ref, ramp, multiparm_count, revert_to_default, press. Tuple paths take lists, component paths scalars; menus take token or label. animation replace clears keys and expressions first; key keys at frame; keep is plain set. Returns value, raw, wrote_keyframe, node errors.

**Notes.** With animation replace a single keyframe only adds or replaces its own key. press clicks a button parm and returns pressed and side_effects ({parm: [old, new]} it changed); on a writer's save button (File Cache Save to Disk, a ROP SOP's Render) the output files over its frame range are checked afterwards: outputs_summary, or cook_failed with detail.missing. press also runs the callback script of a non-button parm (pyrosource initialize), and with value it sets the value first; a plain set of a menu or toggle with a callback notes that the callback did not run. A string menu only the node builds (a Copernicus signature) takes a token or label like any menu. Ramp keys and values come back at 6 significant digits, without raw. raw is left out when it equals value, and long strings are elided as in parm_get. Tuples report per-component expressions and the keyed component names. Type mismatches fail with invalid_value naming the template type and range. On a LOP a USD attribute name (inputs:intensity) sets Houdini's encoded parm (xn__inputsintensity_i0a), here and in node_create parms; path is the resolved one.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | array<object> | yes |  | min items 1 |
| `items[].path` | string | yes |  | Parm, tuple or component path. |
| `items[].value` | string \| number \| boolean \| array<string \| number \| boolean> |  |  |  |
| `items[].expression` | string |  |  |  |
| `items[].language` | `hscript` \| `python` |  | `"hscript"` |  |
| `items[].keyframe` | object |  |  |  |
| `items[].keyframe.frame` | number |  |  |  |
| `items[].keyframe.value` | number | yes |  |  |
| `items[].keyframes` | array<object> |  |  |  |
| `items[].keyframes[].frame` | number |  |  |  |
| `items[].keyframes[].value` | number | yes |  |  |
| `items[].channel_ref` | string |  |  | Parm path to reference. |
| `items[].ramp` | object |  |  |  |
| `items[].ramp.basis` | string \| array<string> |  |  | One basis, or one per key. |
| `items[].ramp.keys` | array<number> | yes |  |  |
| `items[].ramp.values` | array<number \| array<number>> | yes |  |  |
| `items[].multiparm_count` | integer |  |  | min 0 |
| `items[].revert_to_default` | boolean |  |  |  |
| `items[].press` | boolean |  |  |  |
| `items[].animation` | `replace` \| `key` \| `keep` |  | `"replace"` |  |
| `frame` | number |  |  | Default current frame. |
| `partial` | boolean |  | `false` | Keep successful items. |

### Returns

- `results` (array<object>): `path`, `value`, `raw`, `expression`, `language`, `expressions`, `keyed`, `wrote_keyframe`, `is_default`, `errors`, `warnings` — always present

### Examples

```json
{"items": [{"path": "/obj/geo1/box1/size", "value": [2, 1, 2]}]}
```

```json
{"items": [{"path": "/obj/geo1/xform1/ry", "expression": "$F * 3"}]}
```

```json
{"items": [{"path": "/obj/geo1/xform1/ty", "keyframe": {"frame": 1, "value": 0}, "animation": "key"}]}
```


## cook

`idempotent` `headless ok` · profiles `core`, `full`

Cook nodes and report per node ok, errors, warnings, cook_time_ms. Cooking never writes files (render does). profile force-cooks each input chain: chain (top 10), total_ms, attribution; for-each loop bodies show their cost over all iterations (loops). frame_range cooks frame by frame (sims advance); summary bbox adds bbox rows. Past wait_s returns job_id for job.

**Notes.** cook_time_ms is the node's own cook; cached inputs are not recooked. Cooking a ROP or a File Cache writes nothing, and notes say how to write (render, or parm_set press on its execute button). frame_range is [start, end, step] and cannot be combined with profile or frame; the current frame is restored afterwards. Errors left from before a fix are rechecked unless the last cook took over 2 s (hint: force). With profile, results[].cook_time_ms is the named node's profiled cook. attribution is per_node, or perf_monitor when a block_end was cooked under Houdini's performance monitor: each loop body row then has in_loop, cooks, per_iteration_ms and cook_time_ms over all iterations, and loops lists {block_end, block_begin, iterations, total_ms}. loop-level means the monitor was unavailable (another profile was recording) and body rows show one standalone cook. total_ms counts each loop once, at its block_end. In a GUI session the profile stays in the Performance Monitor's list. A profiled node that simulates (a DOP network, or a solver SOP such as pyrosolver with one inside) gets simulation {dopnet, resimulated, frame} and a note: a force-cook reads frames already in the simulation cache instead of re-simulating them. It is cooked under the performance monitor, and resimulated is false when no DOP solve time was recorded (a cache read), current_frame when only the frame the simulation stood on was re-solved (a warm solver whose inputs the profile force-cooked), and true when it simulated frames the cache lacked; simulated_frames [first, last] when known (null, with a note, when the monitor is unavailable and the simulation state cannot tell). summary bbox rows appear only when the counts, bbox or errors change: a row stands for its frame through the frame in through; past 12 such rows only the first 6 and the last 6 are kept, with frames_truncated: true and frames_rows (the count), in the result and in the job's result alike. wait_s is how long the call waits before returning the job (default min(timeout_s, job threshold); 0 returns the job at once). A cancelled cook's job result is the cancelled error with detail {last_status, partial: {frames_cooked, results, frames?}}. (2.0, spec-2.0 §2.5) on runs this call on another Houdini without moving the pin: a pid, a name (houdini_connect {pid, name}) or a role (editor or worker; the least busy live one, by jobs_running then busy). The result's _meta.instance names it and its job is recorded against it. A pid or name the bridge remembers that has exited is instance_lost, one it never knew houdini_offline with the candidates; a role nobody has is houdini_offline. Without on the call goes to the pinned or selected Houdini as always.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> | yes |  | Node paths. (min items 1) |
| `force` | boolean |  | `false` |  |
| `frame` | number |  |  | Default current frame. |
| `timeout_s` | number |  | `30` | min 1 |
| `profile` | boolean |  | `false` |  |
| `frame_range` | array<number> |  |  | min items 2; max items 3 |
| `summary` | `none` \| `bbox` |  | `"none"` |  |
| `wait_s` | number |  |  | min 0 |
| `on` | integer \| string |  |  | Instance to run on: pid, name or role. |

### Returns

- `ok` (boolean)
- `chain` (array<object>)
- `attribution` (string)
- `loops` (array<object>)
- `total_ms` (number)
- `frames` (array<object>)
- `results` (array<object>): `path`, `ok`, `errors`, `warnings`, `messages`, `cook_time_ms`, `hint`
- `job_id` (string)
- `state` (`running` | `done` | `failed` | `cancelled`)

### Examples

```json
{"paths": ["/obj/geo1/OUT"]}
```

```json
{"paths": ["/obj/geo1/OUT"], "profile": true}
```

```json
{"paths": ["/obj/sim/OUT"], "frame_range": [1, 96], "summary": "bbox"}
```


## render

`headless ok` · profiles `core`, `full`

Render any ROP (Karma, Flipbook, USD, ...) or writer SOP (File Cache, rop_geometry) for frames [start, end, inc] (default the ROP's own frame range), optionally overriding output. Waits up to wait_s (default the job threshold): if done, returns outputs, a thumbnail and notes; else job_id to poll with job.

**Notes.** Above 5 outputs the result, inline or from job result, has outputs_summary and outputs_sample (the first 2 and last 2) instead of outputs; missing lists up to 20 paths. Every expected output is checked against approved_roots. look is the quick picture. Headless, a Flipbook or OpenGL ROP renders in a short-lived child hython (a few seconds to start), since a second viewport render can crash the host. notes warn when the scene has no lights, when the thumbnail (as sent, flattened onto grey) is nearly black, and when every pixel is transparent (empty), and say why an image output has no thumbnail (an extension it cannot read). thumbnail.image.attached is true when the image went out as MCP image content. The thumbnail is inline only, flattened onto grey; the ROP's own output files are left as written, alpha included. USD render ROPs (Lop usdrender_rop, Driver usdrender): outputs come from outputimage, else the RenderProduct productName of the render settings the ROP uses (EXR thumbnails too), never lopoutput; output overrides outputimage; a note says when nothing resolves; a husk failure carries the end of its log in detail.log_tail. Without frames a ROP or writer SOP (File Cache, rop_geometry or rop_alembic SOP) renders its own Valid Frame Range, or the current frame when set to Render Current Frame; a note says which. A File Cache renders through the ROP inside it (no output override), then turns on Load from Disk as its Save to Disk button does (side_effects: {parm: [old, new]}). A cancelled render's job result is the cancelled error with detail {last_status, partial: {outputs_summary}} (the files written before the cancel). A Cop node is not a ROP: the error's candidates are the rop_image nodes in its network (look with it as target shows it). A COP image needs no lights, so no lights note. A thumbnail PIL cannot read (a float TIFF) is converted with iconvert; if that fails too, a note says why. A ROP whose output is one file for the range (USD layer, Alembic archive, a path without $F) renders it in one call (a cancel waits for its end) and is read back: a USD layer set or Alembic archive with fewer frames than asked fails with cook_failed; a USD export without time samples gets a static-stage note. outputs lists each file once; a USD export adds layers: [{path, bytes, time_samples, time_codes?}], its root layer, every layer file it composes (a sopimport save path) and USD files the render wrote beside it, at most 20. A layer another USD ROP also writes (the same lopoutput, or a sopimport save path both export) gets shared_with [ROPs] and a note; one whose time samples this render replaced with fewer, or with a range not covering the old one, gets overwrote_samples (the old count) and a first note naming both counts. camera overrides the ROP's camera for this render (restored afterwards): an OBJ camera for its camera parm, a camera prim for a ROP reading a stage (cameraprim) or a USD render ROP (override_camera). A ROP whose camera parm names a missing node fails with node_not_found naming the parm, the scene's cameras as candidates. On a Flipbook or OpenGL ROP a camera that does not fit opsource (a prim or camera LOP at obj, an OBJ camera at lop) is invalid_argument naming opsource; an override adds a note (Rendered through <camera> (<parm> restored).). (2.0, spec-2.0 §2.5) on runs this call on another Houdini without moving the pin: a pid, a name (houdini_connect {pid, name}) or a role (editor or worker; the least busy live one, by jobs_running then busy). The result's _meta.instance names it and its job is recorded against it. A pid or name the bridge remembers that has exited is instance_lost, one it never knew houdini_offline with the candidates; a role nobody has is houdini_offline. Without on the call goes to the pinned or selected Houdini as always.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `rop_path` | string | yes |  |  |
| `frames` | array<number> |  |  | [start, end] or [start, end, inc] (min items 2; max items 3) |
| `output` | string |  |  | Output path override. |
| `camera` | string |  |  |  |
| `wait_s` | number |  |  | min 0 |
| `thumbnail` | boolean |  | `true` |  |
| `on` | integer \| string |  |  | Instance to run on: pid, name or role. |

### Returns

- `job_id` (string) — always present
- `state` (`running` | `done` | `failed` | `cancelled`) — always present
- `rop_path` (string)
- `frames` (array<number>)
- `outputs` (array<string>)
- `outputs_summary` (object)
- `missing` (array<string>)
- `layers` (array<object>)
- `thumbnail` (object): `path`, `width`, `height`, `image`
- `notes` (array<string>)

### Examples

```json
{"rop_path": "/out/karma1"}
```

```json
{"rop_path": "/out/karma1", "frames": [1, 24], "wait_s": 0}
```


## look

`idempotent` `headless ok` · profiles `minimal`, `core`, `full`

Look at the scene: a PNG (long side at most 1024). target: an object, SOP, LOP, Cop node or ROP (default the display). quality draft is a Flipbook ROP (headless too), lit adds the scene's lights (Karma when there are none), final renders Karma. Returns backend_used, chain, scene, context, camera_used, notes. Leaves no nodes, undo step or dirty flag.

**Notes.** Replaces viewport_capture (2.0): the same renderers, chosen by quality. target kinds: omitted, /obj unless it displays nothing and /stage has a display LOP (a note names a stage or COP network it did not show); an object frames it (fit_used target); a SOP frames it, showing it in the render when it lacks the display flag (the flag is moved for the render only); a LOP, a LOP network (its display LOP) or a ROP in a LOP network (the LOP it renders) is a stage (scene stage, lop_path); a Cop node or COP network (its display node) is its own image at its own resolution (scene cop, layer; quality, resolution and fit do not apply); a ROP in /out looks through its camera and lends final its samples. A camera or light as target is invalid_argument: pass it as camera (an OBJ camera, a LOP camera, or a camera prim on the stage). quality draft: the Flipbook ROP, then the OpenGL ROP, then (headless, after a render process crash) a Karma CPU ROP at 2 samples. lit: the same with full lighting and shadows when the scene has lights, else Karma at 2 samples with its default light (a note says so). final: Karma at the target ROP's samples per pixel, else 32 (samples in the result); seconds, not a draft. source viewer (GUI only, draft only, never a stage or COP) grabs the Scene Viewer as the user sees it (context is the viewer's network; the view is put back); headless it is ui_required. chain is the planned order of backends; backend_used the one that drew; notes say why an earlier one did not. fit: all, selected or none (reuse the last automatic framing); without camera an automatic camera frames the target, else everything (camera_used temporary). on picks the Houdini (pid, instance name or role); the bridge routes it, as for cook and render. Headless, the Flipbook and OpenGL ROPs render a snapshot of the scene in a child hython, kept warm between looks (about 0.3 s after a 3 s first start): every node, the asset libraries outside $HFS, $HIP/$JOB, global variables and hou.session; not the current take (a note says so), in-memory simulation caches (the child re-simulates to the frame) or variables set with hou.putenv. Karma and Cop images render the live scene in the host. image.attached is true when the PNG went out as MCP image content. output (2.1) also writes the image to that file, at its rendered size, flattened onto grey: PNG, or JPEG for .jpg/.jpeg; $HIP and ~ expand, parent folders are made, an existing file is replaced, and a path outside approved_roots is path_not_allowed before anything renders. The result's output is the absolute path; the image is still returned inline (path is the copy under the state dir, which keeps only the newest 50).

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | string |  |  | Object, SOP, LOP, Cop node or ROP path. |
| `quality` | `draft` \| `lit` \| `final` |  | `"draft"` |  |
| `camera` | string |  |  |  |
| `frame` | number |  |  | Default current frame. |
| `resolution` | array<integer> |  | `[1024,768]` | min items 2; max items 2 |
| `fit` | `all` \| `selected` \| `none` |  |  |  |
| `source` | `auto` \| `viewer` |  | `"auto"` |  |
| `output` | string |  |  | Also save the image to this .png or .jpg file. |
| `on` | integer \| string |  |  | Instance to run on: pid, name or role. |

### Returns

- `image` (object): `mime_type`, `width`, `height`, `attached`
- `backend_used` (string) — always present
- `chain` (array<string>) — always present
- `quality` (string)
- `target` (string | null)
- `scene` (string) — always present
- `context` (string)
- `camera_used` (string)
- `fit_used` (string)
- `samples` (integer)
- `frame` (number)
- `path` (string) — always present
- `width` (integer) — always present
- `height` (integer) — always present
- `rendered` (array<integer>)
- `output` (string)
- `notes` (array<string>)

### Examples

```json
{}
```

```json
{"target": "/obj/geo1/scatter1", "quality": "lit", "resolution": [640, 480]}
```

```json
{"target": "/out/karma1", "quality": "final", "frame": 24, "output": "$HIP/f24.png"}
```


## houdini_python

`destructive` `headless ok` · profiles `core`, `full`

Run Python (hou bound) or HScript on Houdini's main thread in one undo step, for anything no tool covers. Returns stdout, stderr and result. An uncaught exception fails with python_exception and is rolled back; code still running near timeout_s is stopped (houdini_busy).

**Notes.** result is the value of a trailing expression or a result variable, JSON-serialised (repr fallback). sys.exit counts as an uncaught exception; stdout, stderr and the traceback are in detail. Output is capped at the response budget (truncated). Fails with python_disabled when turned off.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `timeout_s` | number |  | `30` | min 1 |
| `language` | `python` \| `hscript` |  | `"python"` |  |
| `undo_label` | string |  |  |  |

### Examples

```json
{"code": "len(hou.node('/obj').children())"}
```

```json
{"code": "opls /obj", "language": "hscript"}
```


## undo

`headless ok` · profiles `core`, `full`

Undo or redo steps (default 1) and return the labels performed, or list the last 20 undo labels with history. Every HocusPocus mutation is one step labelled "HocusPocus: <tool> ...".

**Notes.** undo and redo stop at the first step whose label does not start with "HocusPocus:" (the user's or Houdini's own) and name it in blocked_by; include_user_steps: true crosses such steps and lists them in user_steps. redo never re-applies a call that failed and was rolled back: it stops and names it in skipped, and history lists it under rolled_back, not redo. history's total and redo_total count every label; hip_open and hip_new clear the history.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `undo` \| `redo` \| `history` | yes |  |  |
| `steps` | integer |  | `1` | min 1 |
| `include_user_steps` | boolean |  | `false` |  |

### Returns

- `performed` (array<string>)
- `history` (array<string>)
- `redo` (array<string>) — history only.
- `enabled` (boolean)
- `next_undo` (string | null)
- `next_redo` (string | null)
- `undo_count` (integer)
- `redo_count` (integer)
- `dirty` (boolean)
- `scene_generation` (integer)
- `note` (string)
- `blocked_by` (string)

### Examples

```json
{"action": "history"}
```

```json
{"action": "undo", "steps": 2}
```


## time

`idempotent` `headless ok` · profiles `core`, `full`

Read or set playbar time. With no arguments returns frame, fps and range. frame sets the current frame, range [start, end] the frame range, fps the frame rate.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `frame` | number |  |  |  |
| `range` | array<number> |  |  | [start, end] (min items 2; max items 2) |
| `fps` | number |  |  | min 1 |

### Returns

- `frame` (number) — always present
- `fps` (number) — always present
- `range` (array<number>) — always present

### Examples

```json
{}
```

```json
{"frame": 24}
```

```json
{"range": [1, 120], "fps": 24}
```


## job

`idempotent` `headless ok` · profiles `core`, `full`

Jobs from render, cook or pdg: status (state, progress, message), result (the tool's result once done), cancel, list.

**Notes.** The bridge sends a job call to the Houdini that started the job, whichever is selected; if that Houdini has exited the answer is instance_lost with the last status the bridge saw (detail.last_status). A bare id means the selected Houdini. list shows the selected Houdini's jobs; all: true lists every live instance's, each row with its pid, plus instances: [{pid, label, jobs, running}]. Jobs do not survive a Houdini restart. A pdg cook job counts the work items of the whole graph in current/total and adds nodes: {name: 'finished/total'}. A frame-by-frame job's message counts the frames done, as current does. cancel adds cancelled: true, or cancelled: false and a note when the job had already finished. A cancelled job's result is the cancelled error, whose detail holds the last status (state cancelled). Job ids are opaque ledger ids such as j7f3a9 (spec-2.0 §2.5, §3): the bridge ledger maps each to its Houdini and job; job also accepts the host's <pid>-<id> form. Jobs are kept in the ledger across bridge restarts: job status after a restart answers from the live Houdini, and for one that has exited instance_lost carries the last status the ledger saw; job result of a finished job whose Houdini has exited returns the result the ledger kept, if it fetched one before (results over 16 KB are stored in <state_dir>/jobs/<id>.json). on (pid, name or role) picks the Houdini for list (and for a bare id); a job id always goes to its own Houdini.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `status` \| `result` \| `cancel` \| `list` | yes |  |  |
| `job_id` | string |  |  | Required except for list. |
| `all` | boolean |  | `false` |  |
| `on` | integer \| string |  |  | Instance to run on: pid, name or role. |

### Returns

- `job_id` (string)
- `tool` (string)
- `state` (`running` | `done` | `failed` | `cancelled`)
- `progress` (number)
- `message` (string)
- `started` (string)
- `elapsed_s` (number)
- `result` (any) — The tool's result (action result, done).
- `jobs` (array<object>)

### Examples

```json
{"action": "status", "job_id": "61900-9c3e6f7ca53e"}
```

```json
{"action": "list", "all": true}
```


## hda

`headless ok` · profiles `full`

Digital assets: create turns subnet path into an HDA; save updates the definition from path, spare parms included; unlock allows editing; match reverts to the definition and locks; install and reload take library_path; list shows loaded libraries or library_path's definitions.

**Notes.** create takes name, label (or description), version, library_path and optional min_inputs/max_inputs. save copies the instance's spare parms into the asset's interface (promoted lists them; promote_spare_parms: false keeps them on the instance). list is paged by limit and cursor; install of a loaded library says already_loaded. node_type_info and node_type_search report the definition's version and, without help, its label as description.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `create` \| `save` \| `unlock` \| `match` \| `install` \| `reload` \| `list` | yes |  |  |
| `path` | string |  |  | Node path. |
| `library_path` | string |  |  | .hda file. |
| `name` | string |  |  | Type name. |
| `label` | string |  |  |  |
| `description` | string |  |  | Same as label. |
| `version` | string |  |  |  |
| `min_inputs` | integer |  |  | min 0; max 9999 |
| `max_inputs` | integer |  |  | min 0; max 9999 |
| `promote_spare_parms` | boolean |  | `true` |  |
| `limit` | integer |  | `50` | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"action": "create", "path": "/obj/geo1/subnet1", "name": "studio::rock", "library_path": "C:/hda/rock.hda"}
```

```json
{"action": "list"}
```


## pdg

`headless ok` · profiles `full`

Drive a TOP node: cook its work items as a job (block waits up to timeout_s, capped at the job threshold), status, workitems (paged; failed items say why), cancel, dirty.

**Notes.** cook, cancel and dirty are refused read-only. A failed work item carries error (the last error lines of its log, at most 400 characters), log_path and exit_code (out-of-process items). A cook result (and job result) has ok: false when any item of the graph failed, and failures lists the first 5 failed items of the target and its upstream TOPs with their error. Out-of-process ROP TOPs (ROP Fetch, ...) load the saved hip, so cook refuses an untitled scene or unsaved changes with unsaved_changes; save: true saves first (approved_roots apply) and the result names the saved path. A cook job's progress counts the work items of the whole graph (the target and its upstream TOPs), with nodes: {name: 'finished/total'}; a cook whose items were cancelled ends cancelled, never done. cancel also cancels the job cooking that graph and returns the status after the cook stopped, with cancelled: true and jobs_cancelled. node_info on a TOP node adds pdg_state: {cooked, failed, total}; problems lists TOP nodes with failed items. workitems rows: id, index, state, output_files (relative to output_root, given once per page), cook_time_s, name only when it is not <node>_<id>, node for a network; attribs: [names] adds each item's attribute values (unknown names left out); state filters: failed, cancelled, success, cache, cooked or a state name. When block returns a running job before timeout_s, notes says the wait was capped.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `cook` \| `status` \| `workitems` \| `cancel` \| `dirty` | yes |  |  |
| `top_path` | string | yes |  |  |
| `block` | boolean |  | `false` |  |
| `save` | boolean |  | `false` |  |
| `attribs` | array<string> |  |  |  |
| `state` | string |  |  |  |
| `timeout_s` | number |  | `30` | min 1 |
| `limit` | integer |  | `50` | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"action": "cook", "top_path": "/tasks/topnet1/ropfetch1"}
```

```json
{"action": "workitems", "top_path": "/tasks/topnet1/ropfetch1", "limit": 20}
```


## events

`read-only` `headless ok` · profiles `full`

What changed since your last call: hip, node (created, renamed, deleted, parms or flags changed on nodes HocusPocus touched or read) and pdg events with seq and origin (agent|houdini|other). Pass next_since back as since.

**Notes.** Watched nodes: those HocusPocus created, edited, read with node_info or listed with network_describe, and nodes created directly under /obj, /stage, /mat, /out and /tasks. ParmTupleChanged has detail.parm and, on a multi-component tuple, components (those whose value or keys changed; a burst within 0.1 s is one event with their union) and keyed (those of them with keyframes now). FlagChanged has detail.flags (flag: new value); a spare parm edit is one SpareParmsChanged; hda create, match and unlock are one hda_contents_rebuilt per asset; kind pdg has detail.event cook_start, work_item_failed (id, index, error) or cook_done (ok, states, cancelled). Each Houdini numbers its own events: next_since is '<pid>:<seq>' (pass it back as since), and a cursor from another Houdini returns reset: true with a note and that Houdini's events from the start. A call that fails and is rolled back records nothing, nor does a node created and deleted within one call, a tool's own set-and-restore, or Houdini's save-time writes on TOP networks. In a call that sets parms (parm_set, node_create parms), the parms it did not set but Houdini wrote (callbacks, a camera's *Converted parms, guide scale) are origin houdini.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `since` | integer \| string |  | `0` |  |
| `limit` | integer |  | `50` | min 1; max 1000 |

### Examples

```json
{}
```

```json
{"since": "3084:42", "limit": 20}
```
