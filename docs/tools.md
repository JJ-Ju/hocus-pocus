# HocusPocus tools

<!-- Generated from src/hocuspocus/tools/catalog.py by `python -m hocuspocus.tools.docs`. Do not edit by hand. -->

35 tools: 14 in the `minimal` profile, 31 in `core` (minimal included), 4 more in `full`. Model-visible `tools/list` text: 26,919 bytes. See `docs/BIBLE.md` §4 for the design.

## Contents

- [`houdini_status`](#houdini_status) *(minimal)*
- [`houdini_connect`](#houdini_connect) *(minimal)*
- [`hip_new`](#hip_new)
- [`hip_open`](#hip_open) *(minimal)*
- [`hip_save`](#hip_save) *(minimal)*
- [`hip_merge`](#hip_merge)
- [`node_find`](#node_find) *(minimal)*
- [`node_info`](#node_info) *(minimal)*
- [`node_create`](#node_create) *(minimal)*
- [`node_delete`](#node_delete)
- [`node_edit`](#node_edit)
- [`node_copy`](#node_copy)
- [`node_connect`](#node_connect) *(minimal)*
- [`node_layout`](#node_layout)
- [`network_describe`](#network_describe)
- [`network_build`](#network_build)
- [`parm_get`](#parm_get) *(minimal)*
- [`parm_set`](#parm_set) *(minimal)*
- [`cook`](#cook) *(minimal)*
- [`problems`](#problems)
- [`geo_info`](#geo_info) *(minimal)*
- [`geo_read`](#geo_read)
- [`viewport_capture`](#viewport_capture) *(minimal)*
- [`render`](#render)
- [`houdini_python`](#houdini_python) *(minimal)*
- [`node_type_search`](#node_type_search)
- [`node_type_info`](#node_type_info)
- [`undo`](#undo)
- [`time`](#time)
- [`selection`](#selection)
- [`job`](#job)
- [`hda`](#hda) *(full)*
- [`usd_stage`](#usd_stage) *(full)*
- [`pdg`](#pdg) *(full)*
- [`events`](#events) *(full)*

## houdini_status

`read-only` `bridge-local` `headless ok` · profile `minimal`

Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and dirty state, $HIP/$JOB, frame, recent files, scene_generation), every live instance and the bridge settings. Works with no Houdini running (connected: null).

**Notes.** Also reports $HIPNAME, fps, the frame range, and the bridge's profile, read_only and allow_python. An untitled scene's hip carries a note that $HIP is the launch directory until hip_save. Each instances[] row has pid, port, label, houdini, ui, hip, started, launched_by, name (when given), selected (the pinned instance, or the one reads go to), busy (the main thread has been held for over a second) and jobs_running. With several instances and none pinned, tools that change a scene refuse with ambiguous_instance: pin one with houdini_connect {pid}. When the pinned Houdini has exited, connected is null and lost: {pid, label} names it. connected.memory is {rss_mb, peak_mb}: the Houdini process's resident and peak memory (watch it while a sim cache fills).

### Arguments

None.

### Returns

- `connected` (object | null): `pid`, `port`, `label`, `houdini`, `ui`, `hip`, `time`, `env`, `scene_generation`, `host_version` — always present
- `instances` (array<object>): `pid`, `label`, `houdini`, `ui`, `hip`, `started`, `launched_by` — always present
- `bridge_version` (string) — always present
- `profile` (`minimal` | `core` | `full`)
- `read_only` (boolean)
- `allow_python` (boolean)

### Examples

```json
{}
```


## houdini_connect

`bridge-local` `headless ok` · profile `minimal`

Choose the Houdini this session drives: pid attaches, launch starts one (gui or headless, optional hip), disconnect drops the selection, quit closes it. A launched Houdini usually closes with this server (launched.outlives_server says); `hocuspocus launch` starts one that outlives it.

**Notes.** pid (or launch) pins that Houdini: the pin holds until the next houdini_connect, and if it exits every call returns instance_lost rather than switching. {} unpins (automatic selection). name labels the Houdini given by pid or launch, shown in houdini_status and in _meta.instance; {name} alone pins the Houdini with that name. A pid that is not running is houdini_offline with the live candidates. launch waits up to wait_s seconds for the new host to register. A launched Houdini starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets the registry entry. To keep one alive across sessions, start it with `hocuspocus launch` and attach by pid.

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

`destructive` `headless ok` · profile `core`

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

`destructive` `headless ok` · profile `minimal`

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

`headless ok` · profile `minimal`

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

`headless ok` · profile `core`

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


## node_find

`read-only` `headless ok` · profile `minimal`

Search a subtree for nodes (name and type globs, category, flags, has_errors). Rows: path, type, category, flags, input_count, child_count, has_errors. Locked HDAs are not entered unless recurse_locked. Paged by limit and cursor.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `root` | string |  | `"/"` |  |
| `pattern` | string |  | `"*"` | Name glob. |
| `type` | string |  |  | Type name glob. |
| `category` | `Chop` \| `ChopNet` \| `Cop` \| `Cop2` \| `CopNet` \| `Data` \| `Director` \| `Dop` \| `Driver` \| `Lop` \| `Manager` \| `Object` \| `Shop` \| `Sop` \| `Top` \| `TopNet` \| `Vop` \| `VopNet` |  |  |  |
| `flags` | object |  |  |  |
| `flags.display` | boolean |  |  |  |
| `flags.render` | boolean |  |  |  |
| `flags.bypass` | boolean |  |  |  |
| `flags.template` | boolean |  |  |  |
| `flags.locked` | boolean |  |  |  |
| `has_errors` | boolean |  |  |  |
| `recurse_locked` | boolean |  | `false` |  |
| `limit` | integer |  | `50` | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"root": "/obj", "type": "*file*"}
```

```json
{"has_errors": true, "limit": 20}
```


## node_info

`read-only` `headless ok` · profile `minimal`

Read nodes in detail: type, flags, inputs with names and sources, non-default parms (value, raw, expression; long strings elided), errors, warnings, cook state. parm_get reads keyframes, menus and templates; network_describe a whole network.

**Notes.** Default include: parms, inputs, errors, flags. Parm rows are name, value, raw (only when it differs), expression, keyed, locked, menu_token; strings over 200 characters come as {elided, head}. hda_locked is true at or inside a locked asset.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> | yes |  | Node paths. (min items 1) |
| `include` | array<`parms` \| `inputs` \| `outputs` \| `children` \| `errors` \| `flags` \| `hda` \| `comment` \| `position` \| `userdata`> |  | `["parms","inputs","errors","flags"]` |  |
| `include_defaults` | boolean |  | `false` |  |
| `recurse_locked` | boolean |  | `false` |  |

### Returns

- `nodes` (array<object>): `path`, `name`, `session_id`, `type`, `flags`, `inputs`, `outputs`, `parms`, `errors`, `warnings`, `messages`, `cook_state`, `children_count`, `hda_locked`, `hda`, `position`, `comment`, `color` — always present

### Examples

```json
{"paths": ["/obj/geo1/box1"]}
```

```json
{"paths": ["/obj/geo1"], "include": ["children", "flags"]}
```


## node_create

`headless ok` · profile `minimal`

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


## node_delete

`destructive` `headless ok` · profile `core`

Delete nodes in one undo step and return the deleted paths. keep_connections reconnects input 0 to the deleted node's outputs where possible, like deleting in the network editor.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> | yes |  | Node paths. (min items 1) |
| `keep_connections` | boolean |  | `true` |  |

### Examples

```json
{"paths": ["/obj/geo1/box1"]}
```

```json
{"paths": ["/obj/geo1"], "keep_connections": false}
```


## node_edit

`idempotent` `headless ok` · profile `core`

Change node properties in one undo step: rename, flags, bypass, color, comment, position, lock (false allows editing a locked HDA's contents). spare_parms adds {name, type: float|int|string|toggle|menu|button|vector|color, label, default, size, min, max, menu_items [{token, label}], value_type, folder, help} or removes spare parms by name. Menu value_type string (default): chs() gives the token; int: ch() gives the item index.

**Notes.** A rename returns old_path and path; spare_parms returns the added and removed parm paths. Only spare parms can be removed; a name already on the node fails with name_collision; nodes inside a locked asset are refused with locked. A folder label is created when missing. value_type is for menus only: string makes a menu parm whose value is the token (VEX chs(); ch() gives the item index); int makes an int parm with that menu whose value is the item index (ch() or chi(); chs() gives the index as text). A menu default is a token or an item index; a number that is no index but equals a token's text (-1 for token "-1") picks that token.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | array<object> | yes |  | min items 1 |
| `items[].path` | string | yes |  |  |
| `items[].name` | string |  |  | New name. |
| `items[].flags` | object |  |  |  |
| `items[].flags.display` | boolean |  |  |  |
| `items[].flags.render` | boolean |  |  |  |
| `items[].flags.bypass` | boolean |  |  |  |
| `items[].flags.template` | boolean |  |  |  |
| `items[].color` | array<number> |  |  | [r, g, b] 0-1 (min items 3; max items 3) |
| `items[].comment` | string |  |  |  |
| `items[].position` | array<number> |  |  | [x, y] (min items 2; max items 2) |
| `items[].lock` | boolean |  |  |  |
| `items[].bypass` | boolean |  |  |  |
| `items[].spare_parms` | object |  |  |  |
| `items[].spare_parms.add` | array<object> |  |  |  |
| `items[].spare_parms.remove` | array<string> |  |  |  |
| `partial` | boolean |  | `false` | Keep successful items. |

### Examples

```json
{"items": [{"path": "/obj/geo1/box1", "name": "base_box"}]}
```

```json
{"items": [{"path": "/obj/geo1/null1", "color": [1, 0, 0], "comment": "OUT"}]}
```

```json
{"items": [{"path": "/obj/geo1/wrangle1", "spare_parms": {"add": [{"name": "glue", "type": "float", "default": 1, "max": 10}]}}]}
```


## node_copy

`headless ok` · profile `core`

Copy nodes into to_parent, which may be their own network. names renames the copies in paths order; with_inputs keeps wiring among copied nodes; position_offset shifts them. Returns the new paths and per copy path, type and problems.

**Notes.** return full adds flags to each row.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> | yes |  | Node paths. (min items 1) |
| `to_parent` | string | yes |  |  |
| `names` | array<string> |  |  |  |
| `with_inputs` | boolean |  | `true` |  |
| `position_offset` | array<number> |  |  | [dx, dy] (min items 2; max items 2) |
| `return` | `full` \| `summary` |  | `"summary"` |  |

### Examples

```json
{"paths": ["/obj/geo1/box1"], "to_parent": "/obj/geo2"}
```


## node_connect

`idempotent` `headless ok` · profile `minimal`

Wire inputs in one undo step: each item connects output from_output of from into to's to_input (an index, an input name, or "next" for the next free input of merge-style nodes); from null disconnects.

**Notes.** A bad input fails with invalid_input, and the hint lists the node's input labels.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `items` | array<object> | yes |  | min items 1 |
| `items[].from` | string \| null | yes |  | Source node or null. |
| `items[].from_output` | integer |  | `0` | min 0 |
| `items[].to` | string | yes |  |  |
| `items[].to_input` | integer \| string |  | `0` | Index, input name, or "next". |
| `partial` | boolean |  | `false` | Keep successful items. |

### Examples

```json
{"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/merge1", "to_input": "next"}]}
```

```json
{"items": [{"from": null, "to": "/obj/geo1/xform1", "to_input": 0}]}
```


## node_layout

`headless ok` · profile `core`

Tidy a network. mode children lays out the children of parent, or only paths; good_position moves each node in paths to a free spot near its inputs.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `parent` | string | yes |  |  |
| `paths` | array<string> |  |  | Subset of children. |
| `mode` | `children` \| `good_position` |  | `"children"` |  |

### Examples

```json
{"parent": "/obj/geo1"}
```


## network_describe

`read-only` `headless ok` · profile `core`

Read a whole network as Houdini's hou.data childrenAsData (types, non-default parms, expressions, wiring, flags) to depth; data feeds network_build. format outline is a compact tree (type, display node, error count, input sources, flags that are on); python is asCode for one node. Locked HDAs stay closed unless recurse_locked. Pages end at the response budget (next_cursor).

**Notes.** depth defaults to 1, and to 2 for outline. A locked HDA appears as {type, hda_locked}. Outline rows: path, name, type, children_count (left out at 0), display, errors, inputs (source path per input slot, null for an empty slot before a wired one; left out when nothing is wired), flags (only the ones that are on, e.g. ["display", "render"]; left out when none), and hda_locked only for locked assets not shipped with Houdini. Truncated pages carry truncated and next_cursor.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `root` | string | yes |  |  |
| `depth` | integer |  |  | min 1 |
| `include_defaults` | boolean |  | `false` |  |
| `include_positions` | boolean |  | `false` |  |
| `recurse_locked` | boolean |  | `false` |  |
| `format` | `data` \| `python` \| `outline` |  | `"data"` |  |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"root": "/obj/geo1"}
```

```json
{"root": "/obj/geo1", "depth": 2, "include_positions": true}
```

```json
{"root": "/", "format": "outline"}
```


## network_build

`headless ok` · profile `core`

Build or update a network under parent from Houdini's hou.data childrenAsData format (what network_describe returns) in one undo step. Types and inputs are validated first; dry_run stops there. Returns created paths and per node path, type and problems.

**Notes.** Input entries are {from, from_index, to_index}; a missing to_index is the entry's position in the list. return full adds flags. tag is stored as the userData hocuspocus:tag. setChildrenFromData sets parms without running their callback scripts: a menu or toggle with one that data sets gets a note in notes (as on node_create). press: {node: [parm names]} runs those callbacks (menus, toggles, buttons) after the build is wired, in order, inside the same undo step; a node is a path in data relative to parent (geo1/src) or absolute, and must be built by this call. The result adds pressed (parm paths) and side_effects: {node path: {parm: [old, new]}}. A press that fails rolls the whole build back; dry_run validates the node names. data keeps Houdini's hou.data format, so press is an argument, not a key inside an entry.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `parent` | string | yes |  |  |
| `data` | object | yes |  | hou.data childrenAsData dict. |
| `on_name_collision` | `error` \| `rename` \| `replace` |  | `"error"` |  |
| `layout` | boolean |  | `true` |  |
| `dry_run` | boolean |  | `false` |  |
| `tag` | string |  |  | Stored as userData hocuspocus:tag. |
| `press` | object<string, array<string>> |  |  | Callbacks to run after the build: {node: [parm names]}. |
| `return` | `full` \| `summary` |  | `"summary"` |  |

### Examples

```json
{"parent": "/obj/geo1", "data": {"box1": {"type": "box"}, "sphere1": {"type": "sphere"}, "merge1": {"type": "merge", "inputs": [{"from": "box1", "from_index": 0, "to_index": 0}, {"from": "sphere1", "from_index": 0, "to_index": 1}], "flags": {"display": true}}}, "dry_run": true}
```


## parm_get

`read-only` `headless ok` · profile `minimal`

Read parms by parm (.../tx), tuple (.../t: all components) or component path: value at frame, raw if different, expression, is_default, locked (parm lock), hda_locked. Strings over 200 chars are {elided, head} unless full_strings. Tuples add per-component expressions and keyed names.

**Notes.** frame defaults to the current frame. template is {label, type, default, min, max, help}; menu items are capped at 50; a menu Houdini builds on the node (a menu script, or a SOP group or attribute menu) is evaluated on it and marked dynamic: true, with items [] and a note when it is empty even after a cook of the SOP. keys is {count, first, last}. On a LOP a USD attribute name (.../inputs:intensity) reads Houdini's encoded parm (xn__inputsintensity_i0a), named in path and name.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> | yes |  | Parm or tuple paths. (min items 1) |
| `frame` | number |  |  | Default current frame. |
| `include` | array<`keys` \| `menu` \| `template` \| `ramp` \| `multiparm`> |  | `[]` |  |
| `full_strings` | boolean |  | `false` |  |

### Returns

- `parms` (array<object>): `path`, `name`, `tuple`, `component_names`, `type`, `value`, `raw`, `expression`, `language`, `expressions`, `keyed`, `is_default`, `locked`, `hda_locked`, `keyframes`, `menu`, `ramp`, `multiparm`, `template` — always present

### Examples

```json
{"paths": ["/obj/geo1/box1/size"]}
```

```json
{"paths": ["/obj/geo1/xform1/tx"], "frame": 24, "include": ["keys"]}
```


## parm_set

`idempotent` `headless ok` · profile `minimal`

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

`idempotent` `headless ok` · profile `minimal`

Cook nodes and report per node ok, errors, warnings, cook_time_ms. Cooking never writes files (render does). profile force-cooks each input chain: chain (top 10), total_ms, attribution; for-each loop bodies show their cost over all iterations (loops). frame_range cooks frame by frame (sims advance); summary bbox adds bbox rows. Past wait_s returns job_id for job.

**Notes.** cook_time_ms is the node's own cook; cached inputs are not recooked. Cooking a ROP or a File Cache writes nothing, and notes say how to write (render, or parm_set press on its execute button). frame_range is [start, end, step] and cannot be combined with profile or frame; the current frame is restored afterwards. Errors left from before a fix are rechecked unless the last cook took over 2 s (hint: force). With profile, results[].cook_time_ms is the named node's profiled cook. attribution is per_node, or perf_monitor when a block_end was cooked under Houdini's performance monitor: each loop body row then has in_loop, cooks, per_iteration_ms and cook_time_ms over all iterations, and loops lists {block_end, block_begin, iterations, total_ms}. loop-level means the monitor was unavailable (another profile was recording) and body rows show one standalone cook. total_ms counts each loop once, at its block_end. In a GUI session the profile stays in the Performance Monitor's list. A profiled node that simulates (a DOP network, or a solver SOP such as pyrosolver with one inside) gets simulation {dopnet, resimulated, frame} and a note: a force-cook reads frames already in the simulation cache instead of re-simulating them. It is cooked under the performance monitor, and resimulated is whether DOP solve time was recorded (null, with a note, when the monitor is unavailable and the simulation state cannot tell). summary bbox rows appear only when the counts, bbox or errors change: a row stands for its frame through the frame in through. wait_s is how long the call waits before returning the job (default min(timeout_s, job threshold); 0 returns the job at once). A cancelled cook's job result is the cancelled error with detail {last_status, partial: {frames_cooked, results, frames?}}.

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


## problems

`read-only` `headless ok` · profile `core`

Explain red nodes: lists nodes in a subtree with errors or warnings, broken channel references, missing files, unconnected required inputs; errored nodes changed since their last cook are recooked first. cook_uncooked cooks never-cooked nodes too. Paged by limit and cursor.

**Notes.** A TOP node with failed work items is a failed_work_items row with count, work_item {id, index} and the first item's error in message. Locked HDAs are skipped unless recurse_locked. A scan budget (10 s, or half of timeout_s) can end a page early with incomplete: true and a next_cursor that continues the walk without losing rows.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `root` | string |  | `"/"` |  |
| `include_warnings` | boolean |  | `true` |  |
| `cook_uncooked` | boolean |  | `false` |  |
| `recurse_locked` | boolean |  | `false` |  |
| `timeout_s` | number |  | `30` | min 1 |
| `limit` | integer |  | `50` | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"root": "/obj/geo1"}
```

```json
{"include_warnings": false, "cook_uncooked": true}
```


## geo_info

`read-only` `headless ok` · profile `minimal`

Summarise the geometry of a SOP (or an OBJ's display SOP): point, prim and vertex counts, bounding box, primitive types, attributes per class with type and size, detail attribute values, groups with counts. On a Cop node: the image's layer type, resolution and channel min/max/mean.

**Notes.** frame evaluates the geometry at that frame without moving the playbar. intrinsics lists every volume as a row under volume_columns [name, prim, resolution, voxel_size, min, max] and every VDB under vdb_columns [name, prim, class, value_type, active_voxels, voxel_size] (at most 100 each; volume_total or vdb_total then counts them all), and the first packed primitives. Detail attribute values are capped: arrays at 16 items, strings at 200 characters, and a dict longer than 200 characters as {elided, keys}; hou vectors and matrices are lists. geo_read reads per-element values. A Cop node (or a COP network's display node) gives kind: image, output, layer_type (Mono, RGB, RGBA, ...), resolution, data_window, pixel_scale, storage, border, constant?, channels {r: {min, max, mean}, ...} of its first output, and other_outputs [{name, layer_type}]. attributes: names lists only the attribute names per class (no types or detail values). Solver internals (Vellum and DOP bookkeeping such as pprevious, hitnml, dPw, varmap, and names starting with __) are left out and counted in internal_attribute_count with a note; geo_read with attribs reads them.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | SOP or OBJ path. |
| `frame` | number |  |  | Default current frame. |
| `attributes` | `full` \| `names` |  | `"full"` |  |

### Returns

- `path` (string)
- `point_count` (integer)
- `prim_count` (integer)
- `vertex_count` (integer)
- `bbox` (object | null): `min`, `max`, `size`, `center`
- `prim_types` (object<string, integer>)
- `attributes` (object): `point`, `vertex`, `prim`, `detail`
- `groups` (object): `point`, `prim`, `edge`, `vertex`
- `intrinsics` (object)

### Examples

```json
{"path": "/obj/geo1/OUT"}
```

```json
{"path": "/obj/geo1", "frame": 1}
```


## geo_read

`read-only` `headless ok` · profile `core`

Read attribute values like the geometry spreadsheet: count rows of one class from start, optionally within group, at frame. stats adds min/max/mean and unique strings over the whole class. Page by passing next_cursor as cursor.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | SOP or OBJ path. |
| `class` | `point` \| `prim` \| `vertex` \| `detail` |  | `"point"` |  |
| `attribs` | array<string> |  |  |  |
| `start` | integer |  | `0` | min 0 |
| `count` | integer |  | `50` | min 1; max 10000 |
| `group` | string |  |  |  |
| `stats` | boolean |  | `false` |  |
| `cursor` | string |  |  | next_cursor from the previous page. |
| `frame` | number |  |  |  |

### Returns

- `path` (string)
- `class` (string)
- `columns` (array<string>) — always present
- `rows` (array<array>) — always present
- `start` (integer)
- `total` (integer) — always present
- `next_cursor` (string)
- `truncated` (boolean)
- `stats` (object)

### Examples

```json
{"path": "/obj/geo1/OUT", "attribs": ["P", "Cd"], "count": 10}
```

```json
{"path": "/obj/geo1/OUT", "class": "prim", "stats": true}
```


## viewport_capture

`idempotent` `headless ok` · profile `minimal`

Look at /obj, a LOP stage or a COP: a PNG (long side at most 1024), path, size, camera_used, scene. camera: OBJ or LOP camera, or camera prim (lop_path); cop_path: a Cop node's image. auto: the GUI viewer if present and no camera, else a Flipbook ROP (headless too) framed per fit. Leaves no nodes, undo step or dirty flag.

**Notes.** fit has no default: without it the viewer source captures the view as it is and the ROP source frames all; fit none reuses the last framing. With fit the viewer frames all or selected for the grab and puts the view back, as it does after looking through camera; context is the viewer's network, and notes say when that is not the captured scene. Without camera or lop_path the stage's display LOP is captured when /obj displays nothing; otherwise a note names it. A stage renders through the ROP's LOP source (scene: stage, lop_path). The ROP source (flipbook_rop; opengl_rop is its 1.3 name and does the same) tries the Flipbook ROP, then the deprecated OpenGL ROP, then a temporary Karma CPU ROP (2 samples, same camera and resolution): headless, a ROP whose render process crashes hands the frame to the next, a note says why, and later stage captures with source auto skip that ROP. source_used is viewer, flipbook_rop, opengl_rop or karma. Lights are refused as cameras; camera errors list the scene's cameras. path also writes the PNG there. Both files are opaque, on the same grey as the image (the Flipbook and OpenGL ROPs write a transparent background). image.attached is true when the PNG went out as MCP image content. cop_path (a Cop node, or a COP network's display node) renders it through a temporary rop_image in its network (about 0.2 s, deleted afterwards, outside undo): scene cop, layer {layer_type, resolution, data_window}, the image at the COP's own resolution (resolution is ignored). Without camera, lop_path or cop_path a note names the COP networks under /img. lop_path naming a ROP in a LOP network (usdrender_rop, usd_rop: no output stage) captures the LOP it renders (loppath, else its input), with a note.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `camera` | string |  |  |  |
| `lop_path` | string |  |  |  |
| `cop_path` | string |  |  |  |
| `frame` | number |  |  | Default current frame. |
| `resolution` | array<integer> |  | `[1024,768]` | min items 2; max items 2 |
| `fit` | `all` \| `selected` \| `none` |  |  |  |
| `source` | `auto` \| `viewer` \| `flipbook_rop` \| `opengl_rop` |  | `"auto"` |  |
| `path` | string |  |  | Also write the PNG here (must end in .png). |

### Returns

- `image` (object): `mime_type`, `width`, `height`, `attached`
- `path` (string) — always present
- `width` (integer) — always present
- `height` (integer) — always present
- `camera_used` (string)
- `scene` (string)
- `source_used` (string)
- `frame` (number)
- `rendered` (array<integer>)
- `also_written` (string)
- `fit_used` (string)
- `notes` (array<string>)

### Examples

```json
{}
```

```json
{"camera": "/obj/cam1", "frame": 48, "source": "flipbook_rop"}
```


## render

`headless ok` · profile `core`

Render any ROP (Karma, Flipbook, USD, ...) or writer SOP (File Cache, rop_geometry) for frames [start, end, inc] (default the ROP's own frame range), optionally overriding output. Waits up to wait_s (default the job threshold): if done, returns outputs, a thumbnail and notes; else job_id to poll with job.

**Notes.** Above 5 outputs the result, inline or from job result, has outputs_summary and outputs_sample (the first 2 and last 2) instead of outputs; missing lists up to 20 paths. Every expected output is checked against approved_roots. viewport_capture is the quick look. Headless, a Flipbook or OpenGL ROP renders in a short-lived child hython (a few seconds to start), since a second viewport render can crash the host. notes warn when the scene has no lights, when the thumbnail (as sent, flattened onto grey) is nearly black, and when every pixel is transparent (empty), and say why an image output has no thumbnail (an extension it cannot read). thumbnail.image.attached is true when the image went out as MCP image content. The thumbnail is inline only, flattened onto grey; the ROP's own output files are left as written, alpha included. USD render ROPs (Lop usdrender_rop, Driver usdrender): outputs come from outputimage, else the RenderProduct productName of the render settings the ROP uses (EXR thumbnails too), never lopoutput; output overrides outputimage; a note says when nothing resolves; a husk failure carries the end of its log in detail.log_tail. Without frames a ROP or writer SOP (File Cache, rop_geometry or rop_alembic SOP) renders its own Valid Frame Range, or the current frame when set to Render Current Frame; a note says which. A File Cache renders through the ROP inside it (no output override), then turns on Load from Disk as its Save to Disk button does (side_effects: {parm: [old, new]}). A cancelled render's job result is the cancelled error with detail {last_status, partial: {outputs_summary}} (the files written before the cancel). A Cop node is not a ROP: the error's candidates are the rop_image nodes in its network (viewport_capture cop_path looks at it). A COP image needs no lights, so no lights note. A thumbnail PIL cannot read (a float TIFF) is converted with iconvert; if that fails too, a note says why. A ROP whose output is one file for the range (USD layer, Alembic archive, a path without $F) renders it in one call (a cancel waits for its end) and is read back: a USD layer set or Alembic archive with fewer frames than asked fails with cook_failed; a USD export without time samples gets a static-stage note. outputs lists each file once; a USD export adds layers: [{path, bytes, time_samples, time_codes?}], its root layer, every layer file it composes (a sopimport save path) and USD files the render wrote beside it, at most 20. camera overrides the ROP's camera for this render (restored afterwards): an OBJ camera for its camera parm, a camera prim for a ROP reading a stage (cameraprim) or a USD render ROP (override_camera). A ROP whose camera parm names a missing node fails with node_not_found naming the parm, the scene's cameras as candidates.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `rop_path` | string | yes |  |  |
| `frames` | array<number> |  |  | [start, end] or [start, end, inc] (min items 2; max items 3) |
| `output` | string |  |  | Output path override. |
| `camera` | string |  |  |  |
| `wait_s` | number |  |  | min 0 |
| `thumbnail` | boolean |  | `true` |  |

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


## houdini_python

`destructive` `headless ok` · profile `minimal`

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


## node_type_search

`read-only` `headless ok` · profile `core`

Find node types by name, label, description or keyword, in all 18 categories or one. Rows: name, label, category, version, description (clipped), input range, deprecated. Current versions only, older ones named in other_versions, unless current_only is false. Exact names rank first; total counts every match.

**Notes.** total is the real number of matching types, not a cap: a plain-language query also matches on single description words, so broad queries can match hundreds of types. Raise limit (up to 1000) to see them all. Cop types also match the labels of their menus (remap's Threshold, blend's Over), and compositing words name their Cop type (threshold: remap, gradient: ramp, composite or over: blend, text: font, write: rop_image). A network type's row adds child_category and typical_parents (CopNet copnet: /img); when every row shares them they are said once, in common. is_current_version is on rows only with current_only false. Results with legacy Cop2 types carry a note that Copernicus is Cop.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes |  |  |
| `category` | `Chop` \| `ChopNet` \| `Cop` \| `Cop2` \| `CopNet` \| `Data` \| `Director` \| `Dop` \| `Driver` \| `Lop` \| `Manager` \| `Object` \| `Shop` \| `Sop` \| `Top` \| `TopNet` \| `Vop` \| `VopNet` |  |  |  |
| `limit` | integer |  | `20` | min 1; max 1000 |
| `include_hidden` | boolean |  | `false` |  |
| `current_only` | boolean |  | `true` |  |

### Returns

- `results` (array<object>): `name`, `label`, `category`, `version`, `description`, `other_versions` — always present
- `total` (integer)

### Examples

```json
{"query": "scatter"}
```

```json
{"query": "noise", "category": "Vop", "limit": 5}
```


## node_type_info

`read-only` `headless ok` · profile `core`

Describe one node type: label, version, named inputs and outputs, parms by folder. detail compact gives name, label, type, default rows; full adds size, range, menu and folder; folders lists folders with parm counts. folder and parms (globs, a|b) narrow the parms.

**Notes.** folder takes a label, an "A / B" path, or "" / "(no folder)" for the top-level parms. include_help adds the first ~2 KB of the node help. With folder or parms the inputs list becomes inputs_count, and detail full leaves out the folder list. In detail full a script menu (pdg_cachemode) or a menu built from input geometry (a SOP group) is evaluated on a temporary instance: menu {items, dynamic: true}, or items [] with a note when it evaluates empty there; so is a string menu only the node builds (a Copernicus signature). Menu labels lose their ![icon] markup. A compact listing over 8 KB leaves out the parms a menu hides at its default (the per-pattern parms of the other patterns): variants {menu parm: parms left out} and a note; pass parms or detail full to list them. A wildcard parms glob lists the parms it matches at the start of a name or label word first (*pin*: Pin Type); those it matches only inside a word (damping) follow, named in substring_matches with a note and marked matched_by: substring in detail full.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | string | yes |  | Sop/scatter, or scatter with category. |
| `category` | `Chop` \| `ChopNet` \| `Cop` \| `Cop2` \| `CopNet` \| `Data` \| `Director` \| `Dop` \| `Driver` \| `Lop` \| `Manager` \| `Object` \| `Shop` \| `Sop` \| `Top` \| `TopNet` \| `Vop` \| `VopNet` |  |  |  |
| `include_parms` | boolean |  | `true` |  |
| `include_help` | boolean |  | `false` |  |
| `folder` | string |  |  |  |
| `parms` | string |  |  | Name or label glob, e.g. *seed* or dist\|inset. |
| `detail` | `compact` \| `full` \| `folders` |  | `"compact"` |  |

### Examples

```json
{"type": "Sop/scatter"}
```

```json
{"type": "Sop/scatter", "parms": "*seed*"}
```

```json
{"type": "Sop/rbdmaterialfracture", "detail": "folders"}
```


## undo

`headless ok` · profile `core`

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

`idempotent` `headless ok` · profile `core`

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


## selection

`idempotent` `headless ok` · profile `core`

Read or set the node selection. Omit paths to get the selected node paths; pass paths to select exactly those (an empty list clears the selection).

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `paths` | array<string> |  |  |  |

### Returns

- `selected` (array<string>) — always present

### Examples

```json
{}
```

```json
{"paths": ["/obj/geo1/box1"]}
```


## job

`idempotent` `headless ok` · profile `core`

Jobs from render, cook or pdg: status (state, progress, message), result (the tool's result once done), cancel, list.

**Notes.** Job ids are <pid>-<id>: the bridge sends a job call to the Houdini that started the job, whichever is selected; if that Houdini has exited the answer is instance_lost with the last status the bridge saw (detail.last_status). A bare id means the selected Houdini. list shows the selected Houdini's jobs; all: true lists every live instance's, each row with its pid, plus instances: [{pid, label, jobs, running}]. Jobs do not survive a Houdini restart. A pdg cook job counts the work items of the whole graph in current/total and adds nodes: {name: 'finished/total'}. A frame-by-frame job's message counts the frames done, as current does. cancel adds cancelled: true, or cancelled: false and a note when the job had already finished. A cancelled job's result is the cancelled error, whose detail holds the last status (state cancelled).

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `status` \| `result` \| `cancel` \| `list` | yes |  |  |
| `job_id` | string |  |  | Required except for list. |
| `all` | boolean |  | `false` |  |

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

`headless ok` · profile `full`

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


## usd_stage

`read-only` `headless ok` · profile `full`

Read a LOP's USD stage: prims (path, type) under prim (path or glob) to depth; include adds attributes (attribs: name glob), xform, bindings, layers. summary: type counts, world bbox. Paged (limit, cursor).

**Notes.** time is a time code (default the current frame). prim globs: * within a path segment, ** across segments, | between alternatives (each a path or glob, e.g. /lights|/cameras); matches are listed with their subtrees to depth, in stage order. An invalid alternative is invalid_argument, as is an exact one that names no prim. Attribute values are authored values at time; arrays up to 4 elements (8 for strings and tokens) are listed in full, longer ones as {len, first}. xform gives local, and world only when it differs. total is on every page (counted up to 100000, then total_capped). summary returns {total_prims, counts_by_type, bbox_world: {min, max, size}} for the whole subtree (default and render purposes). A ROP in a LOP network (usd_rop, usdrender_rop) has no stage: the LOP it renders (its loppath, else its input) is read, with a note. layers.stack rows are {identifier, save_path?, owner_node?, time_codes?}: where Houdini saves an anonymous layer (a sopimport's save path) or a file layer's path, the LOP that made it, and [start, end] when the layer authors them.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `lop_path` | string | yes |  |  |
| `prim` | string |  | `"/"` |  |
| `depth` | integer |  | `1` | min 1 |
| `include` | array<`attributes` \| `xform` \| `bindings` \| `layers`> |  | `[]` |  |
| `attribs` | string |  |  |  |
| `summary` | boolean |  | `false` |  |
| `time` | number |  |  |  |
| `limit` | integer |  | `50` | min 1; max 1000 |
| `cursor` | string |  |  | next_cursor from the previous page. |

### Examples

```json
{"lop_path": "/stage/OUT"}
```

```json
{"lop_path": "/stage/OUT", "prim": "/geo", "depth": 3, "include": ["attributes"]}
```


## pdg

`headless ok` · profile `full`

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

`read-only` `headless ok` · profile `full`

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
