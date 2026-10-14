"""Server ``instructions`` (shipped in ``initialize``), the ``hocuspocus://guide`` text, the
prompts and the ``hocuspocus://tools`` reference.

2.0 (docs/BIBLE.md §4.8, spec-2.0 §2.8): the instructions, the guide and the seven prompts
name the 2.0 tools (``edit`` first, ``inspect`` and the resources for reads, ``look``,
roles and ``on``). The ``compat_1x`` profile, which serves the 1.4 catalogue for 2.0.x,
gets the 1.4 texts (``*_1X``) from :func:`instructions_for` and :func:`guide_text`. The
reference is built by :func:`hocuspocus.tools.docs.tools_reference` (re-exported here as
``tools_text``), the same renderer as ``docs/tools.md``. Keep ``INSTRUCTIONS`` under 400
words and every guide under :data:`GUIDE_MAX_BYTES`; unit tests enforce both.

:data:`PROMPTS` has the shape of the bridge's prompt table (``name -> (description,
[(argument, description, required)], template)``, templates formatted with
:data:`PROMPT_DEFAULTS` and the caller's arguments), so ``bridge/server.py`` can serve it
as is.
"""

# TODO(2.0 M3, parity G5): add stream B's modal-dialog paragraph (docs/parity.md) to the
# GUI notes of the guide once it lands there; it was not in docs/parity.md when the 2.0
# guide was written.

from __future__ import annotations

from hocuspocus.tools.docs import tools_reference as tools_text

__all__ = [
    "COMPAT_PROFILE",
    "GUIDE_MAX_BYTES",
    "INSTRUCTIONS",
    "INSTRUCTIONS_1X",
    "PROMPTS",
    "PROMPT_DEFAULTS",
    "RESOURCES",
    "RESOURCES_1X",
    "guide_text",
    "instructions_for",
    "tools_text",
]

GUIDE_MAX_BYTES = 8192
"""``hocuspocus://guide`` is instructions and recipes only (review 19 papercut 10: with the
tool reference appended it was 52 KB); the reference is ``hocuspocus://tools``."""

COMPAT_PROFILE = "compat_1x"
"""The profile that serves the 1.4 catalogue for 2.0.x (spec-2.0 §8) and gets the 1.4
instructions and guide."""

INSTRUCTIONS = """\
HocusPocus drives a live Houdini. Identity is Houdini paths. Start with `houdini_status`; \
if nothing is connected, `houdini_connect` can launch Houdini (GUI or headless hython) or \
attach to a running one by pid. With several Houdinis running, pin one with \
`houdini_connect {pid}` (or `{name}`, or `{role: "editor"}`): until then calls that change a \
scene refuse with `ambiguous_instance`, and if the pinned one exits calls return \
`instance_lost` instead of switching. `cook`, `render`, `look` and `job` take `on` (a pid, a \
name or a role such as `worker`) to run on another Houdini without moving the pin. \
Change the scene with `edit`: one call is one undo step, its ops run in order (`create`, \
`connect`, `set`, `node`, `delete`, `copy`, `layout`, `build`, `select`), and an op's `id` \
is `$id` in later ops' paths. `dry_run: true` validates every op and resolves paths without \
changing anything; a failing op rolls the whole call back. The result's `nodes` rows carry \
each touched node's errors and warnings. For one quick change `parm_set {items: [{path, \
value}]}` and `node_create {items: [...]}` remain. Tuple paths like `.../t` take lists, \
component paths like `.../tx` take scalars; expressions go in `expression`. Read with \
`inspect {what, target}` (`what`: node, parms, network, outline, geo, image, stage, \
problems, type, events, jobs) and find with `search {kind: "types"}` or `{kind: "nodes"}`. \
See the result with `look {target}`: `quality: "draft"` (a Flipbook ROP, headless too) for \
checks, `lit` with the scene's lights, `final` for Karma. Long cooks and renders return a \
`job_id`; poll it with `job`. When no tool fits, `houdini_python` runs `hou` code. Results \
are compact: non-default parms only, lists paged with `cursor`; `truncated: true` means the \
response budget cut a list. Errors carry `code`, `hint` and `candidates`; read them and \
adjust. `delivery_unknown` means the call may or may not have run: inspect state before \
repeating it. `_meta.scene_generation` changes when the scene is cleared or loaded. Hip \
tools refuse to discard unsaved work unless told to. A \
Houdini started with `houdini_connect {launch}` usually closes when this server exits \
(`launched.outlives_server` says): `hip_save` before the session ends, or attach by pid to \
one started with `hocuspocus launch`. `inspect {what: "type"}` is large for FX types: pass \
`parms` globs, or `detail: "folders"` first. Add spare parms with an `edit` `node` op's \
`spare_parms` (recipe in `hocuspocus://guide`). The resource `houdini://outline` is the \
whole scene as a compact tree; `hocuspocus://tools` is the full tool reference."""

RESOURCES = """## Resources

Attach these for context. Each read is also a tool call with the same JSON (`inspect`,
`search`, `houdini_status`) and carries `_meta.etag`: send it back as
`_meta["If-None-Match"]` and an unchanged resource answers `_meta.not_modified: true`.

- `houdini://outline{?root,depth}`: the scene as a compact tree with display nodes, error
  counts, inputs and the flags that are on (`inspect {what: "outline"}`; under
  `compat_1x`, `network_describe {root: "/", format: "outline", depth: 2}`). Start here.
- `houdini://status`, `houdini://instances`, `houdini://jobs`, `houdini://problems{?root}`,
  `houdini://events{?since,limit}`.
- `houdini://node/{path}`, `network/{path}`, `geo/{path}`, `image/{path}`,
  `stage/{lop}`: `inspect` with that `what`. `houdini://type/{category}/{name}` and
  `houdini://types{?q}`: a node type, a type search.
- Subscribe to `status`, `jobs`, `events` or `node/{path}`:
  `notifications/resources/updated` arrives when the etag changes.
- `hocuspocus://tools`: the tool reference. Large: read it for one tool's notes when a
  result surprises you, not up front.

"""

RECIPES = """## Recipes

### Build, check and look in three calls

```json
{"ops": [{"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
         {"op": "create", "id": "grid", "parent": "$geo", "type": "grid",
          "parms": {"size": [10, 10], "rows": 100, "cols": 100}},
         {"op": "create", "parent": "$geo", "type": "mountain", "name": "mtn",
          "inputs": [{"index": 0, "from": "$grid"}], "flags": {"display": true}}]}
```

Unsure of a type or parm name? Send it with `dry_run: true` first: every problem comes back
at once. Then `inspect {what: "geo", target: "/obj/terrain/mtn"}` for counts and bounds,
and `look {target: "/obj/terrain"}`.

### Two Houdinis: edit in the GUI, render on a worker

`houdini_status` lists every instance with `pid`, `role` (`editor` for a GUI, `worker`
headless), `busy`, `jobs_running` and `selected`; `recent` lists those that exited. With
several running and none pinned, reads go to the GUI and calls that change a scene refuse
with `ambiguous_instance`, so pin first:

1. `houdini_connect {role: "editor"}`, edit, then `hip_save`.
2. `houdini_connect {role: "worker"}` (`{launch: {mode: "headless"}, role: "worker"}`
   starts one), `hip_open` the saved hip, then `houdini_connect {role: "editor"}`.
3. `render {rop_path, on: "worker", wait_s: 0}` renders there without moving the pin.
   `job` reaches the job's Houdini whatever is pinned, also after a server restart;
   `job {action: list, all: true}` lists every instance's jobs. 1.x ids (`<pid>-<id>`)
   still work.

If the pinned Houdini exits, every call returns `instance_lost` naming it and the live
candidates; nothing switches on its own. Pin another with `houdini_connect {pid}`, or
`houdini_connect {}` for automatic selection. `events` numbers events per Houdini: pass
`next_since` (`<pid>:<seq>`) back as `since`; a cursor from another Houdini answers
`reset: true`.

### Copernicus (COP) images

Copernicus networks live in `/img`: an `edit` create op with `parent: "/img", type:
"copnet"`, then nodes inside it with category `Cop` (`Cop2` is the legacy compositor).
`look {target: "/img/net/node"}` returns a COP node's image in about 0.2 s;
`inspect {what: "image"}` gives its resolution and per-channel stats. To write files, wire
a `Cop/rop_image` (its `copoutput` parm is the file, e.g. `$HIP/img/name.$F4.png`) and
`render {rop_path: "/img/net/rop_image1"}`, which also returns a thumbnail. Cooking a ROP
writes nothing. SOPs read a COP live through an `op:` path, e.g. `attribfrommap` with
`filename: "op:/img/net/node"`. Compositing verbs: over and multiply are `blend` modes, a
threshold is `remap`, a gradient is `ramp`, text is `font`.

### Flipbook frames (Flipbook ROP)

`look` is one frame. For a sequence, create a `flipbook` ROP in `/out` (`Driver/flipbook`;
Houdini 22 deprecates the OpenGL ROP it replaces) with `camera` (an OBJ camera), `picture`
(e.g. `$HIP/flip/$OS.$F4.png`), `trange: 1` and `f1`/`f2`, plus `tres: 1` with
`res1`/`res2`; for a stage set `opsource: 1`, `loppath` and `cameraprim`. Then
`render {rop_path: "/out/flipbook1", wait_s: 0}` and poll the `job_id`: the result lists
the frames and returns the last one as a thumbnail.

### Add a spare parm (edit node op)

Add a control parm to a null, subnet, geo object or an unlocked HDA instance and link
other parms to it with `ch()`, in one call:

```json
{"ops": [{"op": "node", "path": "/obj/geo1/CONTROLS",
          "spare_parms": {"add": [{"name": "glue_strength", "type": "float",
                                   "label": "Glue Strength", "default": 0.5}]}},
         {"op": "set", "path": "/obj/geo1/rbd1/strength",
          "expression": "ch(\\"../CONTROLS/glue_strength\\")"}]}
```

A `ch()` to a parm that does not exist evaluates to 0 silently. A `menu` is a string menu
by default: VEX reads its token with `chs()`. With `value_type: "int"` it is an int parm
whose value is the item index, read with `ch()` or `chi()`.
"""

GUIDE_HEADER = """\
# HocusPocus operating guide

## Instructions

"""


# -- the 1.4 texts, served to the compat_1x profile (spec-2.0 §8) ------------------------

INSTRUCTIONS_1X = """\
HocusPocus drives a live Houdini. Identity is Houdini paths. Start with `houdini_status`; \
if nothing is connected, `houdini_connect` can launch Houdini (GUI or headless hython) or \
attach to a running one by pid. With several Houdinis running, pin one with \
`houdini_connect {pid}`: until then calls that change a scene refuse with \
`ambiguous_instance`, and if the pinned one exits calls return `instance_lost` instead of \
switching. `_meta.instance` names the Houdini that answered; job ids and `events` cursors \
carry their pid. Build with `node_create` (batch, with parms and inputs) or \
`network_build` (whole graph from the `network_describe` format). Read with `node_info` and \
`network_describe`. Change values with `parm_set {items: [{path, value}]}`; tuple paths like `.../t` take lists, \
component paths like `.../tx` take scalars; expressions go in `expression`. After building, \
call `cook` or read `errors` in results, then `geo_info` to check counts and bounds, and \
`viewport_capture` to look at it. Every mutating call is one undo step. Hip tools refuse to \
discard unsaved work unless told to. Long cooks and renders return a `job_id`; poll it with \
`job`. When no tool fits, `houdini_python` runs `hou` code. Results are compact: non-default \
parms only, lists paged with `cursor`; `truncated: true` means the response budget cut a list, \
so page or narrow the query. Errors carry `code`, `hint` and `candidates`; read them and \
adjust. `delivery_unknown` means the call may or may not have run: inspect state before \
repeating it. `_meta.scene_generation` changes when the scene is cleared or loaded, so cached \
paths may be stale. A Houdini started with `houdini_connect {launch}` usually closes when this \
server exits (`launched.outlives_server` says): `hip_save` before the session ends, keep one \
session open for long jobs, or attach by pid to one started with `hocuspocus launch`. \
`viewport_capture` frames per `fit` on both paths and restores the user's view afterwards; \
without `fit` or `camera` the GUI viewer is captured as it is. `lop_path` captures a stage. \
For a flipbook of many frames, `render` a Flipbook ROP (`Driver/flipbook`, recipe in the \
guide); Houdini 22 deprecates the OpenGL ROP. \
`node_type_info` is large \
for FX types: pass `parms` globs, or `detail: "folders"` first. Add spare parms with \
`node_edit` `spare_parms` (recipe in `hocuspocus://guide`). The resource `houdini://outline` \
is the whole scene as a compact tree; `hocuspocus://tools` is the full tool reference."""

RESOURCES_1X = """## Resources

Attach these to a conversation for context (each is also a tool call):

- `houdini://status`: the connected Houdini, hip file, frame and instances (`houdini_status`).
- `houdini://outline`: the whole scene as a compact tree two levels deep, with display
  nodes, error counts, input sources and the flags that are on (`network_describe {root: "/", format: "outline", depth: 2}`).
  Start here to learn what a hip contains, then `network_describe` one network.
- `houdini://node/{path}`, `.../parms`, `.../geo`: `node_info`, its parms, `geo_info`.
- `houdini://nodetype/{category}/{name}`: `node_type_info` in full.
- `houdini://job/{id}`: a job's status, from the Houdini that runs it.
- `hocuspocus://tools`: the tool reference (every tool's arguments, notes and examples,
  the same text as `docs/tools.md`). It is large: read it for one tool's notes when a
  result surprises you, not up front.

"""

RECIPES_1X = """## Recipes

### Two Houdinis: edit in the GUI, render on a worker

`houdini_status` lists every instance with `pid`, `label`, `ui`, `hip`, `busy`,
`jobs_running` and `selected`. With more than one running and none pinned, reads go to the
GUI (then the newest) and calls that change a scene refuse with `ambiguous_instance`, so pin
first, and name the instances to tell them apart later:

1. `houdini_connect {pid: <gui>, name: "editor"}`, edit, then `hip_save`.
2. `houdini_connect {pid: <worker>, name: "worker"}`, then `hip_open` the saved hip and
   `render {rop_path, frames, wait_s: 0}`. Keep the `job_id`: it is `<pid>-<id>`.
3. `houdini_connect {name: "editor"}` and keep editing. `job {action: status, job_id}` goes
   to the worker whatever is pinned; `job {action: list, all: true}` lists every instance's
   jobs.

If the pinned Houdini exits, every call returns `instance_lost` naming it and the live
candidates; nothing switches on its own. Pin another with `houdini_connect {pid}`, or
`houdini_connect {}` for automatic selection. A job of an exited Houdini is `instance_lost`
with its last status; outputs already written stay on disk. `events` numbers events per
Houdini: pass `next_since` (`<pid>:<seq>`) back as `since`; a cursor from another Houdini
answers `reset: true`.

### Copernicus (COP) images

Copernicus networks live in `/img`: `node_create {items: [{parent: "/img", type: "copnet"}]}`, then
the nodes inside it with category `Cop` (`Cop2` is the legacy compositor). To look at any
COP node: `viewport_capture {cop_path: "/img/net/node"}` returns its image in about 0.2 s;
`geo_info` on a COP node gives resolution and per-channel stats. To write files, wire a
`Cop/rop_image` (its `copoutput` parm is the file, e.g. `$HIP/img/name.$F4.png`) and
`render {rop_path: "/img/net/rop_image1"}`, which also returns a thumbnail. Cooking a ROP
writes nothing. SOPs read a COP live through an `op:` path, e.g. `attribfrommap` with
`filename: "op:/img/net/node"`. Compositing verbs: over and multiply are `blend` modes, a
threshold is `remap` (op threshold), a gradient is `ramp`, text is `font`.

### Flipbook frames (Flipbook ROP)

`viewport_capture` is one frame. For a sequence, create a `flipbook` ROP in `/out` (the
OpenGL ROP it replaces is deprecated in Houdini 22) with `camera` (an OBJ camera), `picture`
(e.g. `$HIP/flip/$OS.$F4.png`), `trange: 1` and `f1`/`f2`, plus `tres: 1` with `res1`/`res2`
to override the camera's resolution; for a stage set `opsource: 1`, `loppath` and
`cameraprim`. Then `render {rop_path: "/out/flipbook1", wait_s: 0}` and poll the `job_id`:
the result lists the frames and returns the last one as a thumbnail. Headless it renders in
a short-lived child hython, a few seconds to start.

### Add a spare parm (node_edit spare_parms)

Add a control parm to a null, subnet, geo object or an unlocked HDA instance with
`node_edit`, then drive other parms from it with `ch()`:

```json
{"items": [{"path": "/obj/geo1/CONTROLS",
            "spare_parms": {"add": [{"name": "glue_strength", "type": "float",
                                     "label": "Glue Strength", "default": 0.5}]}}]}
```

`parm_set {items: [{path: "/obj/geo1/rbd1/strength", expression: 'ch("../CONTROLS/glue_strength")'}]}`
then links to it (batch tools always take `items`). A `ch()` to a parm that does not exist evaluates to 0 silently.

A `menu` is a string menu by default: VEX reads its token with `chs()` (`ch()` gives the
item index). For a menu that VEX reads as a number, pass `value_type: "int"`: the parm is
an int whose value is the item index, read with `ch()` or `chi()`:

```json
{"name": "roof_type", "type": "menu", "value_type": "int", "default": 0,
 "menu_items": [{"token": "flat", "label": "Flat"}, {"token": "pyramid", "label": "Pyramid"}]}
```
"""


def instructions_for(profile: str | None = None) -> str:
    """The server ``instructions`` for ``profile``: the 1.4 text for ``compat_1x``, the 2.0
    text otherwise."""
    return INSTRUCTIONS_1X if profile == COMPAT_PROFILE else INSTRUCTIONS


def guide_text(profile: str | None = None) -> str:
    """The operating manual: instructions, resources and recipes (BIBLE §4.8). The per-tool
    reference is :func:`tools_text` (``hocuspocus://tools``). ``compat_1x`` gets the 1.4
    guide, every other profile the 2.0 one."""
    if profile == COMPAT_PROFILE:
        return "".join([GUIDE_HEADER, INSTRUCTIONS_1X, "\n\n", RESOURCES_1X, RECIPES_1X])
    return "".join([GUIDE_HEADER, INSTRUCTIONS, "\n\n", RESOURCES, RECIPES])


# -- prompts (spec-2.0 §2.8) -------------------------------------------------------------

PROMPTS: dict[str, tuple[str, list[tuple[str, str, bool]], str]] = {
    "inspect_scene": (
        "Summarise the open Houdini scene: hip file, networks, problems.",
        [("root", "Network to start from (default /obj)", False)],
        "Inspect the Houdini scene under {root}. Call houdini_status first (hip file, frame, "
        "instance). If it warns that several Houdinis are running and none is pinned, ask the "
        "user which one to inspect, or pin the GUI session with houdini_connect {{pid}} (or "
        '{{role: "editor"}}), before going on. Read the resource houdini://outline (or call '
        'inspect {{what: "outline", target: "{root}"}}) for the tree, then inspect {{what: '
        '"problems", target: "{root}"}}. Inspect one network (what: "network") only when the '
        "summary needs it. Summarise: what each top-level network builds, the display/render "
        "nodes, and any errors or warnings with the node path and the likely cause. Do not "
        "modify anything.",
    ),
    "build_sop_chain": (
        "Build a SOP network from a plain-language description, then verify it.",
        [
            (
                "description",
                "What to build, e.g. 'a box scattered with 500 points copied spheres'",
                True,
            ),
            ("parent", "Parent network (default: create /obj/<name> geo)", False),
        ],
        "Build this in Houdini: {description}. Parent network: {parent}. Plan the SOP chain "
        "first, then create it with one edit call: create ops with parms and inputs, an id on "
        "each op so later ops wire to $id, and the display flag on the last node. Use search "
        '{{kind: "types", query}} when unsure of a type name, or send the call with dry_run: '
        "true first: it reports every problem at once and changes nothing. The edit result's "
        "nodes rows give each node's errors and cook state: fix any errors with one more edit "
        '(set or connect ops), check inspect {{what: "geo", target}} on the display node '
        '(counts, bbox), and finish with look {{"target": <the geo object>}} so the new '
        "geometry is framed. Report the final node paths.",
    ),
    "debug_red_node": (
        "Find out why a node has errors and fix it.",
        [("path", "Node path, e.g. /obj/geo1/attribwrangle1", True)],
        'The node {path} shows errors. Call inspect {{what: "node", target: "{path}", '
        "include: [errors, parms, inputs]}}. Read the error text, inspect upstream inputs and "
        'any expressions or file paths involved (inspect {{what: "problems"}} on its parent '
        "when the cause may lie upstream), and explain the root cause. Propose the smallest "
        "fix; apply it with one edit call (set or connect ops) only if it is unambiguous: the "
        "result's nodes rows re-cook the node, so its errors confirm the fix. In a wrangle, "
        "ch() of a parm that does not exist is 0 without an error: add the parms it reads "
        "with an edit node op's spare_parms and set them in the same call.",
    ),
    "turntable_preview": (
        "Set up a turntable camera around an object and capture preview frames.",
        [
            ("path", "Object or SOP to orbit, e.g. /obj/geo1", True),
            ("frames", "Frame count for a full turn (default 48)", False),
        ],
        "Create a turntable preview of {path} over {frames} frames. Check houdini_status (ui: "
        "GUI or headless) and the resource houdini://outline: if {path}'s display flag is off, "
        "turn it on with an edit node op (flags: {{display: true}}) and say so. Other "
        "displayed objects can hide it: turn their display flags off for the looks and back "
        "on afterwards, or tell the user which objects block the view. Read inspect {{what: "
        '"geo", target: "{path}"}} for its bounding box, then in one edit call create a null '
        "at the bbox centre with ry keyed 0→360 over frames 1–{frames} (a set op with "
        "keyframes) and a camera parented to it, framed to the bbox, with resx/resy set (e.g. "
        "1280×720). Do not change the playbar range in a GUI session: each look takes frame. "
        'Call look {{target: "{path}", camera, frame, resolution: [resx, resy]}} at the first '
        "frame and at a quarter turn, and show both images.",
    ),
    "cache_sim": (
        "Cache a simulation to disk with a File Cache and check the frames.",
        [
            ("path", "The simulation's output SOP or its File Cache, e.g. /obj/pyro/OUT", True),
            ("range", "Frame range to cache, e.g. '1 48' (default: the node's own)", False),
        ],
        'Cache the simulation at {path}, frame range: {range}. Read inspect {{what: "node", '
        'target: "{path}"}}. Unless {path} is a File Cache or one follows it, add one with an '
        "edit create op (type filecache, input {path}, file parm $HIP/cache/$OS.$F4.bgeo.sc). "
        "If the hip is untitled, ask where to save it and hip_save first, so $HIP is a real "
        "directory. cook never writes files: write the cache with render {{rop_path: <the File "
        "Cache>, wait_s: 0}} (frames only when a range was given) and poll the job_id "
        'with job (progress counts frames; job {{action: "cancel"}} keeps the frames already '
        "written). When it is done, check the outputs summary for missing frames, read "
        'inspect {{what: "geo", target: <the File Cache>, frame}} at the first, middle and '
        "last frame for counts and bounds, and look at the last frame. Report the cache path, "
        "the frame count and any frame whose counts look wrong.",
    ),
    "two_houdinis": (
        "Edit in the GUI Houdini while a headless worker renders.",
        [("rop", "ROP to render on the worker, e.g. /out/karma1", True)],
        "Render {rop} on a headless worker while the GUI Houdini stays free for editing. "
        "Call houdini_status: instances carry pid, role (editor or worker), busy and "
        "jobs_running. If no worker is running, start one with houdini_connect {{launch: "
        '{{mode: "headless"}}, role: "worker"}}. Pin the GUI with houdini_connect {{role: '
        '"editor"}} and hip_save there (ask for a path if the hip is untitled). Pin the '
        'worker with houdini_connect {{role: "worker"}}, hip_open the saved hip, then pin '
        'the editor again. Start the render with render {{rop_path: "{rop}", on: "worker", '
        "wait_s: 0}}: it runs on the worker without moving the pin. Keep the job_id; job "
        '{{action: "status", job_id}} reaches the worker whatever is pinned, and job '
        '{{action: "list", all: true}} lists every instance\'s jobs. If a Houdini exits, '
        "calls return instance_lost naming it: nothing switches on its own, so pin another "
        "explicitly. Report the job's outputs and thumbnail when it is done.",
    ),
    "lookdev_karma": (
        "Light and shade a USD stage for a quick Karma lookdev, then render a preview.",
        [
            ("path", "LOP to look at, e.g. /stage/OUT (default: the /stage display LOP)", False),
        ],
        'Set up a quick lookdev of the stage at {path}. Read inspect {{what: "stage", '
        "target: <that LOP>, summary: true}} for its prims, types and bounds. If the stage "
        "has no lights, add a dome light and a key light after it with one edit call (use "
        'search {{kind: "types", query, category: "Lop"}} for the type names). For materials '
        "use a materiallibrary LOP with MaterialX (mtlxstandard_surface) and assign them with "
        "an assignmaterial LOP; set parms with set ops (USD attribute names such as "
        "inputs:base_color work on LOP parms). Check the look with look {{target: <the last "
        'LOP>, quality: "lit"}} while iterating, then look {{quality: "final"}} (Karma at the '
        "ROP's samples, seconds rather than a draft) when it reads well. To write frames, "
        "render a usdrender_rop with wait_s: 0 and poll the job. Report what you added and "
        "show the final image.",
    ),
}
PROMPT_DEFAULTS = {
    "root": "/obj",
    "parent": "a new geo node under /obj",
    "frames": "48",
    "range": "the node's own",
    "path": "the /stage display LOP",
}
"""Values for optional prompt arguments. ``path`` is required by every prompt except
``lookdev_karma``, so its default only ever fills that one."""
