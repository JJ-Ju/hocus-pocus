# HocusPocus tools

<!-- Generated from src/hocuspocus/tools/catalog.py by `python -m hocuspocus.tools.docs`. Do not edit by hand. -->

35 tools: 31 in the `core` profile, 4 more in `full`. Model-visible `tools/list` text: 26,487 bytes. See `docs/BIBLE.md` §4 for the design.

## Contents

- [`houdini_status`](#houdini_status)
- [`houdini_connect`](#houdini_connect)
- [`hip_new`](#hip_new)
- [`hip_open`](#hip_open)
- [`hip_save`](#hip_save)
- [`hip_merge`](#hip_merge)
- [`node_find`](#node_find)
- [`node_info`](#node_info)
- [`node_create`](#node_create)
- [`node_delete`](#node_delete)
- [`node_edit`](#node_edit)
- [`node_copy`](#node_copy)
- [`node_connect`](#node_connect)
- [`node_layout`](#node_layout)
- [`network_describe`](#network_describe)
- [`network_build`](#network_build)
- [`parm_get`](#parm_get)
- [`parm_set`](#parm_set)
- [`cook`](#cook)
- [`problems`](#problems)
- [`geo_info`](#geo_info)
- [`geo_read`](#geo_read)
- [`viewport_capture`](#viewport_capture)
- [`render`](#render)
- [`houdini_python`](#houdini_python)
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

`read-only` `bridge-local` `headless ok` · profile `core`

Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and dirty state, $HIP/$JOB, frame, recent files, scene_generation), every live instance and the bridge settings. Works with no Houdini running (connected: null).

**Notes.** Also reports $HIPNAME, fps, the frame range, and the bridge's profile, read_only and allow_python. An untitled scene's hip carries a note that $HIP is the launch directory until hip_save.

### Arguments

None.

### Returns

- `connected` (object | null): `pid`, `port`, `label`, `houdini`, `ui`, `hip`, `time`, `env`, `scene_generation`, `host_version` — always present
- `instances` (array<object>): `pid`, `label`, `houdini`, `ui`, `hip`, `started`, `launched_by` — always present
- `bridge_version` (string) — always present
- `profile` (`core` | `full`)
- `read_only` (boolean)
- `allow_python` (boolean)

### Examples

```json
{}
```


## houdini_connect

`bridge-local` `headless ok` · profile `core`

Choose the Houdini this session drives: pid attaches, launch starts one (gui or headless, optional hip), disconnect drops the selection, quit closes it (on_unsaved as hip_new). A launched Houdini usually closes with this server (launched.outlives_server says); `hocuspocus launch` starts one that outlives it.

**Notes.** launch waits up to wait_s seconds for the new host to register. A launched Houdini starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets the registry entry. To keep one alive across sessions, start it with `hocuspocus launch` and attach by pid.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `pid` | integer |  |  | Live instance to attach to. |
| `launch` | object |  |  |  |
| `launch.mode` | `gui` \| `headless` | yes |  |  |
| `launch.hip` | string |  |  | Hip file to open. |
| `launch.wait_s` | number |  | `90` | min 1 |
| `disconnect` | boolean |  | `false` |  |
| `quit` | boolean |  | `false` |  |
| `on_unsaved` | `fail` \| `save` \| `discard` |  |  |  |

### Examples

```json
{"pid": 12345}
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

`destructive` `headless ok` · profile `core`

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

`headless ok` · profile `core`

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

`read-only` `headless ok` · profile `core`

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

`read-only` `headless ok` · profile `core`

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

`headless ok` · profile `core`

Create nodes in one undo step. type resolves like createNode (box gets the current version; exact_type disables). Items may wire to earlier items; a block_end pairs with its block_begin (paired_with). Returns path, type and problems per node. network_build suits whole graphs.

**Notes.** A parms value is a literal, {expression, language} (short form {expr, lang}), or any parm_set item without path. An input is {index or name, from, output (default 0)}. layout good_position places new nodes. return full gives node_info blocks listing only the parms the call set, with strings over 200 characters as {elided, head}; identical error lists after the first become errors_same_as.

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

`idempotent` `headless ok` · profile `core`

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

**Notes.** Input entries are {from, from_index, to_index}; a missing to_index is the entry's position in the list. return full adds flags. tag is stored as the userData hocuspocus:tag.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `parent` | string | yes |  |  |
| `data` | object | yes |  | hou.data childrenAsData dict. |
| `on_name_collision` | `error` \| `rename` \| `replace` |  | `"error"` |  |
| `layout` | boolean |  | `true` |  |
| `dry_run` | boolean |  | `false` |  |
| `tag` | string |  |  | Stored as userData hocuspocus:tag. |
| `return` | `full` \| `summary` |  | `"summary"` |  |

### Examples

```json
{"parent": "/obj/geo1", "data": {"box1": {"type": "box"}, "sphere1": {"type": "sphere"}, "merge1": {"type": "merge", "inputs": [{"from": "box1", "from_index": 0, "to_index": 0}, {"from": "sphere1", "from_index": 0, "to_index": 1}], "flags": {"display": true}}}, "dry_run": true}
```


## parm_get

`read-only` `headless ok` · profile `core`

Read parms by parm (.../tx), tuple (.../t: all components) or component path: value at frame, raw if different, expression, is_default, locked (parm lock), hda_locked. Strings over 200 chars are {elided, head} unless full_strings. Tuples add per-component expressions and keyed names.

**Notes.** frame defaults to the current frame. template is {label, type, default, min, max, help}; menu items are capped at 50; keys is {count, first, last}. On a LOP a USD attribute name (.../inputs:intensity) reads Houdini's encoded parm (xn__inputsintensity_i0a), named in path and name.

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

`idempotent` `headless ok` · profile `core`

Set parms in one undo step. Each item takes one of value, expression, keyframe(s), channel_ref, ramp, multiparm_count, revert_to_default, press. Tuple paths take lists, component paths scalars; menus take token or label. animation replace clears keys and expressions first; key keys at frame; keep is plain set. Returns value, raw, wrote_keyframe, node errors.

**Notes.** With animation replace a single keyframe only adds or replaces its own key. press clicks a button parm. raw is left out when it equals value, and long strings are elided as in parm_get. Tuples report per-component expressions and the keyed component names. Type mismatches fail with invalid_value naming the template type and range. On a LOP a USD attribute name (inputs:intensity) sets Houdini's encoded parm (xn__inputsintensity_i0a), here and in node_create parms; path is the resolved one.

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
| `items[].press` | boolean |  |  | Press a button parm. |
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

`idempotent` `headless ok` · profile `core`

Cook nodes and report per node ok, errors, warnings, cook_time_ms (its own cook; cached inputs are not recooked). profile force-cooks each input chain: chain (top 10 by cost), total_ms, attribution; for-each loop bodies show their cost over all iterations (loops). frame_range cooks frame by frame (sims advance); summary bbox adds per-frame bbox. Past the job threshold returns job_id for job.

**Notes.** frame_range is [start, end, step] and cannot be combined with profile or frame; the current frame is restored afterwards. Errors left from before a fix are rechecked unless the last cook took over 2 s (hint: force). With profile, results[].cook_time_ms is the named node's profiled cook. attribution is per_node, or perf_monitor when a block_end was cooked under Houdini's performance monitor: each loop body row then has in_loop, cooks, per_iteration_ms and cook_time_ms over all iterations, and loops lists {block_end, block_begin, iterations, total_ms}. loop-level means the monitor was unavailable (another profile was recording) and body rows show one standalone cook. total_ms counts each loop once, at its block_end. In a GUI session the profile stays in the Performance Monitor's list.

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

`read-only` `headless ok` · profile `core`

Summarise the geometry of a SOP (or an OBJ's display SOP) in about 1 KB: point, prim and vertex counts, bounding box, primitive types, attributes per class with type and size, detail attribute values, groups with counts. geo_read reads per-element values.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | SOP or OBJ path. |
| `frame` | number |  |  | Default current frame. |

### Returns

- `path` (string)
- `point_count` (integer) — always present
- `prim_count` (integer) — always present
- `vertex_count` (integer) — always present
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

Read attribute values like the geometry spreadsheet: count rows of one class from start, with a columns header, optionally within group. stats adds min/max/mean and unique strings over the whole class. Page by passing next_cursor as cursor.

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

`idempotent` `headless ok` · profile `core`

Look at /obj or a LOP stage: a PNG (long side at most 1024), path, size, camera_used, scene. camera: OBJ or LOP camera, or camera prim (lop_path). auto: the GUI viewer if present and no camera, else an OpenGL ROP (headless too) framed per fit. Leaves no nodes, undo step or dirty flag.

**Notes.** fit none reuses the last framing. The viewer source captures the view as it is unless fit is passed: then it frames all or selected for the grab and puts the view back, as it does after looking through camera; context is the viewer's network, and notes say when that is not the captured scene. Without camera or lop_path the stage's display LOP is captured when /obj displays nothing; otherwise a note names it. A stage renders through the OpenGL ROP's LOP source (scene: stage, lop_path). source_used is viewer, opengl_rop or karma: when a headless OpenGL render process crashes, the frame is rendered with a temporary Karma CPU ROP (2 samples, same camera and resolution) and a note says why; later stage captures then go straight to Karma. Lights are refused as cameras; camera errors list the scene's cameras. path also writes the PNG there. Both files are opaque, on the same grey as the image (the OpenGL ROP itself writes a transparent background). image.attached is true when the PNG went out as MCP image content.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `camera` | string |  |  |  |
| `lop_path` | string |  |  |  |
| `frame` | number |  |  | Default current frame. |
| `resolution` | array<integer> |  | `[1024,768]` | min items 2; max items 2 |
| `fit` | `all` \| `selected` \| `none` |  | `"all"` |  |
| `source` | `auto` \| `viewer` \| `opengl_rop` |  | `"auto"` |  |
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
{"camera": "/obj/cam1", "frame": 48, "source": "opengl_rop"}
```


## render

`headless ok` · profile `core`

Render any ROP (Karma, Mantra, OpenGL, ...) for frames [start, end, inc] (default current frame), optionally overriding output. Waits up to wait_s (default the job threshold): if done, returns outputs, a thumbnail image and notes; else job_id and state to poll with job.

**Notes.** Above 5 outputs only outputs_summary is inline; job result lists them all. Every expected output is checked against approved_roots. viewport_capture is the quick look. notes warn when the scene has no lights and when the thumbnail is nearly black, and say why an image output has no thumbnail (an extension it cannot read). thumbnail.image.attached is true when the image went out as MCP image content. The thumbnail is inline only, flattened onto grey; the ROP's own output files are left as written, alpha included. USD render ROPs (Lop usdrender_rop, Driver usdrender): outputs come from outputimage, else the RenderProduct productName of the render settings the ROP uses (EXR thumbnails too), never lopoutput; output overrides outputimage; a note says when nothing resolves; a husk failure carries the end of its log in detail.log_tail.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `rop_path` | string | yes |  |  |
| `frames` | array<number> |  |  | [start, end] or [start, end, inc] (min items 2; max items 3) |
| `output` | string |  |  | Output path override. |
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
- `thumbnail` (object): `path`, `width`, `height`, `image`
- `thumbnail_error` (string)
- `notes` (array<string>)

### Examples

```json
{"rop_path": "/out/karma1"}
```

```json
{"rop_path": "/out/karma1", "frames": [1, 24], "wait_s": 0}
```


## houdini_python

`destructive` `headless ok` · profile `core`

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

Find node types by name, label, description or keyword, in all 18 categories or one. Rows: name, label, category, version, description (clipped), input range, deprecated. Current versions only, older ones named in other_versions, unless current_only is false. Exact names rank first; total counts every match, weak keyword matches included.

**Notes.** total is the real number of matching types, not a cap: a plain-language query also matches on single description words, so broad queries can match hundreds of types. Raise limit (up to 1000) to see them all.

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

**Notes.** folder takes a label, an "A / B" path, or "" / "(no folder)" for the top-level parms. include_help adds the first ~2 KB of the node help. With folder or parms the inputs list becomes inputs_count, and detail full leaves out the folder list.

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

**Notes.** undo and redo stop at the first step whose label does not start with "HocusPocus:" (the user's or Houdini's own) and name it in blocked_by; include_user_steps: true crosses such steps and lists them in user_steps.

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

Long work from render, cook or pdg: status (state, progress, message, elapsed_s), result (the tool's result once done), cancel, list.

**Notes.** Jobs do not survive a Houdini restart. A pdg cook job counts the work items of the whole graph in current/total and adds nodes: {name: 'finished/total'}. A cancelled job's result is the cancelled error, whose detail holds the last status.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `status` \| `result` \| `cancel` \| `list` | yes |  |  |
| `job_id` | string |  |  | Required except for list. |

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
{"action": "status", "job_id": "j-3f2a"}
```

```json
{"action": "list"}
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

**Notes.** time is a time code (default the current frame). prim globs: * within a path segment, ** across segments, | between alternatives (each a path or glob, e.g. /lights|/cameras); matches are listed with their subtrees to depth, in stage order. An invalid alternative is invalid_argument, as is an exact one that names no prim. Attribute values are authored values at time; arrays up to 4 elements (8 for strings and tokens) are listed in full, longer ones as {len, first}. xform gives local, and world only when it differs. total is on every page (counted up to 100000, then total_capped). summary returns {total_prims, counts_by_type, bbox_world: {min, max, size}} for the whole subtree (default and render purposes). A render ROP in a LOP network has no stage: the error names its input.

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

What changed since your last call: hip, node (created, renamed, deleted, parms or flags changed on nodes HocusPocus touched or read) and pdg events with seq and origin (agent|other). Pass the last seq seen as since.

**Notes.** Watched nodes: those HocusPocus created, edited, read with node_info or listed with network_describe, and nodes created directly under /obj, /stage, /mat, /out and /tasks. FlagChanged has detail.flags (flag: new value); a spare parm edit is one SpareParmsChanged; hda create, match and unlock are one hda_contents_rebuilt per asset; kind pdg has detail.event cook_start, work_item_failed (id, index, error) or cook_done (ok, states, cancelled). A call that fails and is rolled back records nothing, nor does a node created and deleted within one call, a tool's own set-and-restore, or Houdini's save-time writes on TOP networks.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `since` | integer |  | `0` | min 0 |
| `limit` | integer |  | `50` | min 1; max 1000 |

### Examples

```json
{}
```

```json
{"since": 42, "limit": 20}
```
