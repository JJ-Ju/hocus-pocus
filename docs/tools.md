# HocusPocus tools

<!-- Generated from src/hocuspocus/tools/catalog.py by `python -m hocuspocus.tools.docs`. Do not edit by hand. -->

35 tools: 31 in the `core` profile, 4 more in `full`. Model-visible `tools/list` text: 29,157 bytes. See `docs/BIBLE.md` §4 for the design.

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

Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and dirty state, $HIP/$JOB/$HIPNAME, frame, fps, range, recent files, scene_generation), every live instance, and bridge settings (profile, read_only, allow_python). Works with no Houdini running: connected is null. Use houdini_connect to pick or launch an instance.

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

Choose which Houdini this session drives. Pass one of: pid to attach to a live instance listed by houdini_status; launch to start one (mode gui or headless hython, optional hip, wait up to wait_s, default 90); or disconnect to drop the selection. A launched Houdini usually closes when this server exits (launched.outlives_server says); to keep Houdini alive across sessions, start it with `hocuspocus launch` and attach by pid.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `pid` | integer |  |  | Live instance to attach to. |
| `launch` | object |  |  |  |
| `launch.mode` | `gui` \| `headless` | yes |  |  |
| `launch.hip` | string |  |  | Hip file to open. |
| `launch.wait_s` | number |  | `90` | min 1 |
| `disconnect` | boolean |  | `false` |  |

### Examples

```json
{"pid": 12345}
```

```json
{"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}}
```

```json
{"disconnect": true}
```


## hip_new

`destructive` `headless ok` · profile `core`

Clear to a new untitled scene. on_unsaved (default fail) protects unsaved work: fail returns unsaved_changes; save saves first (fails on an untitled scene, so use hip_save with path); discard drops the changes. Bumps scene_generation.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `on_unsaved` | `fail` \| `save` \| `discard` |  | `"fail"` | Handling of unsaved changes. |

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

Load a hip file, replacing the current scene. on_unsaved as in hip_new (default fail). Load warnings are returned in warnings rather than failing the call unless ignore_load_warnings is false. Use hip_merge to add another file's nodes to the current scene instead.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes |  | Hip file. |
| `on_unsaved` | `fail` \| `save` \| `discard` |  | `"fail"` | Handling of unsaved changes. |
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

Save the hip file. path makes it save-as and creates directories; an untitled scene needs path. increment saves to the next version number in the file name; backup keeps a backup copy. Returns the real saved path, dirty after save, and file bytes.

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

Merge nodes from another hip file into the current scene. node_pattern (default *) selects nodes; dry_run only reports collisions (no undo step, allowed read-only). Colliding nodes are renamed unless overwrite_on_conflict. Use hip_open to replace the scene instead.

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

Search a subtree for nodes. pattern globs names (default *), type globs type names; category, flags and has_errors filter. Rows: path, type, category, flags, input_count, child_count, has_errors. Locked HDAs are not entered unless recurse_locked. Paged by limit and cursor.

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

Read nodes in detail: type, flags, inputs with names and sources, non-default parms (value, raw, expression; long strings elided), errors, warnings, cook state. include picks sections (default parms, inputs, errors, flags); include_defaults adds parms at default. Use parm_get for keyframes, menus and templates; network_describe for a whole network.

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

Create nodes in one undo step. Item: parent, type (resolved like createNode so box gets the current version; exact_type disables), optional name, parms (value or {expression, language}; {expr, lang} also works), inputs (index or name, from, output), flags, position. Items may wire to earlier items; a block_end pairs with its block_begin (paired_with). layout default good_position. Returns path, type and problems per node; return full gives node_info blocks with only the parms the call set. Use network_build for whole graphs.

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

Delete nodes in one undo step. keep_connections (default true) reconnects input 0 to the deleted node's outputs where possible, like deleting in the network editor. Returns deleted paths.

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

Change node properties in one undo step: rename, flags, bypass, color, comment, position, and lock (false allows editing a locked HDA's contents). spare_parms adds {name, type: float|int|string|toggle|menu|button|vector|color, label, default, size, min, max, menu_items [{token, label}], folder, help} or removes spare parms by name; returns their paths. A rename returns old_path and path. Use parm_set for values.

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

Copy nodes into to_parent, which may be their own network. names renames copies in paths order; with_inputs (default true) keeps wiring among copied nodes; position_offset shifts them. Returns the new paths and per copy path, type and problems (return full adds flags).

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

Wire or unwire inputs in one undo step. Each item connects output from_output (default 0) of from into to at to_input: an index (default 0), an input name, or "next" for the next free input of merge-style nodes. from null disconnects. Bad inputs fail with invalid_input listing the input labels.

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

Tidy a network. mode children (default) lays out the children of parent, or only paths; good_position moves each node in paths to a free spot near its inputs.

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

Read a whole network in one call as Houdini's hou.data childrenAsData format: types, non-default parms, expressions, wiring, flags, depth levels deep (default 1; 2 for outline). Locked HDAs appear as {type, hda_locked} unless recurse_locked. Pages stop at the response budget (truncated, next_cursor). format outline is a compact tree (path, name, type, children_count, display, errors, hda_locked for non-Houdini assets); python returns asCode for one node. data feeds network_build.

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

Build or update a whole network under parent from Houdini's hou.data childrenAsData format (what network_describe returns) in one undo step. Types and inputs are validated first; dry_run stops there. Input entries are {from, from_index, to_index}; a missing to_index means the entry's position in the list. on_name_collision: error (default), rename, replace. Returns created paths and per node path, type and problems (return full adds flags). Use node_create for a few nodes.

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

Read parms by parm (.../tx), tuple (.../t: all components) or component path. Each: value at frame (default current), raw if different, expression and language, is_default, locked (parm lock), hda_locked. Strings over 200 chars are {elided, head} unless full_strings. include adds keys, menu, template (label, type, default, range, help), ramp, multiparm. Tuples add per-component expressions and keyed names.

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

Set parms in one undo step. Each item takes one of value, expression, keyframe, keyframes, channel_ref, ramp, multiparm_count, revert_to_default, press (clicks a button). Tuple paths take lists, component paths scalars; menus take token or label. animation: replace (default) clears keys and expressions first, except that one keyframe only adds or replaces its key; key keys at frame; keep is plain set. Returns value, raw if different (long strings elided), tuple expressions and keyed, wrote_keyframe, node errors.

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

Cook nodes and report per node ok, errors, warnings, cook_time_ms (its own cook; cached inputs are not recooked). profile force-cooks each input chain in dependency order: chain (top 10 by cost), total_ms. frame_range [start, end, step] cooks frame by frame (sims advance, frame restored); summary bbox adds per-frame counts and bbox. Errors left from before a fix are rechecked unless the last cook took over 2 s (hint: force). Past the job threshold returns job_id for job.

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

Explain red nodes: walks a subtree listing nodes with errors or warnings, broken channel references, missing files in file parms, unconnected required inputs. Errored nodes changed since their last cook are recooked first. cook_uncooked cooks never-cooked nodes too. Locked HDAs are skipped unless recurse_locked. Paged by limit and cursor; scanning stops after a budget (10 s, or half of timeout_s) with incomplete: true and a next_cursor that continues the walk.

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

Summarise the geometry of a SOP (or an OBJ's display SOP) in about 1 KB: point, prim and vertex counts, bounding box, primitive types, attributes per class with type and size, detail attribute values, groups with counts. Use geo_read for per-element values.

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

Read attribute values like the geometry spreadsheet: count rows (default 50) of one class (default point) from start, with a columns header, for attribs (default all), optionally within group. stats adds min/max/mean and unique strings over the whole class. Page by passing next_cursor as cursor (or its number as start).

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

Look at the scene. Returns a PNG image (long side at most 1024) plus path, width, height, camera_used. source auto (default) uses the GUI viewer when present, else an OpenGL ROP that works headless, framing a temporary camera per fit (default all; none reuses the last framing) unless camera is given. Leaves no nodes, undo step or dirty flag. Use render for final-quality images.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `camera` | string |  |  | Camera path. |
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
- `source_used` (`viewer` | `opengl_rop`)
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

Render any ROP (Karma, Mantra, OpenGL, ...) for frames [start, end, inc] (default current frame), optionally overriding output. Waits up to wait_s (default the job threshold, 10 s): if done, returns state, outputs (above 5 only outputs_summary; job result lists all), thumbnail with the image attached, notes (no lights, nearly black), job_id; else job_id and state to poll with job. Use viewport_capture for a quick look.

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

Run Python (hou bound) or HScript on Houdini's main thread in one undo step, for anything no other tool covers. Returns stdout, stderr and result (a trailing expression or a result variable, JSON-serialised). An uncaught exception (sys.exit included) fails with python_exception (stdout, stderr, traceback in detail) and is rolled back; code still running near timeout_s is stopped (houdini_busy). Output is capped. Fails with python_disabled when turned off.

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

Find node types by name, label, description or keyword across all 18 categories, or one category. Rows: name, label, category, version, description (clipped), input range, deprecated. Current versions only, older ones named in other_versions, unless current_only is false. Exact names rank first; limit defaults to 20. Use node_type_info for one type's parms and help.

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

Describe one node type: label, version, named inputs and outputs, and parms grouped by folder. detail compact (default): rows of name, label, type, default; full lists every parm with size, range, menu and folder; folders lists folder names with parm counts. type is category/name, or a bare name with category. folder limits parms to one folder ((no folder): top level), parms to name or label globs (a|b); include_help adds help text.

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

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `undo` \| `redo` \| `history` | yes |  |  |
| `steps` | integer |  | `1` | min 1 |

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

Manage long work started by render, cook or pdg. status returns state (running, done, failed, cancelled), progress, message, elapsed_s; result returns the original tool's result once done; cancel stops it; list shows all jobs. Jobs do not survive a Houdini restart.

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

Digital asset operations. create turns subnet path into an HDA (name, label, version, library_path, optional min_inputs/max_inputs); save updates the definition from path; unlock allows editing path's contents; match reverts path to its definition and locks it; install and reload take library_path; list shows loaded libraries (or library_path's definitions), paged by limit and cursor.

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

Read the USD stage of a LOP node: prims under prim (default /) to depth (default 1) with path and type; include adds attributes (values at time, arrays summarised), xform, material bindings, layers. Paged by limit and cursor.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `lop_path` | string | yes |  |  |
| `prim` | string |  | `"/"` |  |
| `depth` | integer |  | `1` | min 1 |
| `include` | array<`attributes` \| `xform` \| `bindings` \| `layers`> |  | `[]` |  |
| `time` | number |  |  | Time code; default current frame. |
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

Drive a TOP node. cook cooks its work items as a job (block waits up to timeout_s, default 30, capped at the 10 s job threshold, then returns the job); status reports node state; workitems pages work items with state and output files; cancel stops cooking; dirty dirties the node. cook, cancel and dirty are refused in read-only mode.

### Arguments

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | `cook` \| `status` \| `workitems` \| `cancel` \| `dirty` | yes |  |  |
| `top_path` | string | yes |  |  |
| `block` | boolean |  | `false` |  |
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

What changed since your last call: hip events and node events (created, renamed, deleted, parms changed on nodes HocusPocus touched) with a monotonic seq. Pass the last seq seen as since (default 0).

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
