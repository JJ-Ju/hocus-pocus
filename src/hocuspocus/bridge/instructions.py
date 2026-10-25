"""Server ``instructions`` (shipped in ``initialize``), the ``hocuspocus://guide`` text, the
prompts and the ``hocuspocus://tools`` reference.

2.0 (docs/BIBLE.md §4.8, spec-2.0 §2.8): the instructions, the guide and the seven prompts
name the 2.0 tools (``edit`` first, ``inspect`` and the resources for reads, ``look``,
roles and ``on``); 2.1 removed the 1.4 texts with the ``compat_1x`` profile. The
reference is built by :func:`hocuspocus.tools.docs.tools_reference` (re-exported here as
``tools_text``), the same renderer as ``docs/tools.md``. Keep ``INSTRUCTIONS`` under 400
words, every guide under :data:`GUIDE_MAX_BYTES` and the 2.0 guide under
:data:`GUIDE_2X_MAX_BYTES`; unit tests enforce them.

:data:`PROMPTS` has the shape of the bridge's prompt table (``name -> (description,
[(argument, description, required)], template)``, templates formatted with
:data:`PROMPT_DEFAULTS` and the caller's arguments), so ``bridge/server.py`` can serve it
as is.
"""

from __future__ import annotations

from hocuspocus.tools.docs import tools_reference as tools_text

__all__ = [
    "GUIDE_2X_MAX_BYTES",
    "GUIDE_MAX_BYTES",
    "INSTRUCTIONS",
    "PROMPTS",
    "PROMPT_DEFAULTS",
    "RESOURCES",
    "guide_text",
    "instructions_for",
    "tools_text",
]

GUIDE_MAX_BYTES = 8192
"""``hocuspocus://guide`` is instructions and recipes only (review 19 papercut 10: with the
tool reference appended it was 52 KB); the reference is ``hocuspocus://tools``."""

GUIDE_2X_MAX_BYTES = 6656
"""The 2.0 guide's own cap, 6.5 KB (spec-2.0 §7 M4: the scorecard reads it once, and at
7.7 KB it outgrew 1.4's 7.3 KB guide)."""

INSTRUCTIONS = """\
HocusPocus drives a live Houdini; identity is Houdini paths. Start with `houdini_status`; \
if nothing is connected, `houdini_connect` launches Houdini (GUI or headless) or attaches \
by pid. With several Houdinis, pin one with `houdini_connect {pid}` (or `{name}`, \
`{role}`): until then scene changes refuse with `ambiguous_instance`; if the pinned one \
exits, calls return `instance_lost`. `cook`, `render`, `look` and `job` take `on` (pid, \
name or role) to run elsewhere without moving the pin. Change the scene with `edit`: one \
call, one undo step; ops (`create`, `connect`, `set`, `node`, `delete`, `copy`, `layout`, \
`build`, `select`) run in order and an op's `id` is `$id` in later paths. `dry_run: true` \
validates and resolves paths without changing anything; a failing op rolls the call back. \
The result is a row per touched node (errors and warnings only when present) and `ids`. \
`parm_set {items: [{path, value}]}` and `node_create {items: [...]}` remain for quick \
changes. Tuple paths (`.../t`) take lists, components (`.../tx`) scalars; expressions go \
in `expression`. Read with `inspect {what, target}` (node, parms, network, outline, geo, \
image, stage, problems, type, events, jobs; for FX types pass `parms` globs or \
`detail: "folders"`); find with `search {kind: "types" | "nodes"}`. `look {target}` shows \
it: `quality` `draft` (Flipbook), `lit` or `final` (Karma). Long cooks and renders return \
a `job_id` for `job`. `houdini_python` runs `hou` code when no tool fits. Results are \
compact (non-default parms, lists paged by `cursor`; `truncated: true` means the budget \
cut a list). Errors carry `code`, `hint` and `candidates`: adjust to them. After \
`delivery_unknown`, inspect before repeating. `_meta.scene_generation` changes when the \
scene is cleared or loaded. Hip tools refuse to discard unsaved work unless told to. A \
Houdini from `houdini_connect {launch}` usually closes with this server \
(`launched.outlives_server` says): `hip_save` first, or attach by pid to one started with \
`hocuspocus launch`. Spare parms: `edit` `node` op `spare_parms`. `houdini://outline` is \
the scene as a compact tree. Recipes: `inspect {what: "guide", target?: topic}`; a tool's \
reference: `inspect {what: "tool", target: name}` (also `hocuspocus://guide`, \
`hocuspocus://tools`)."""

RESOURCES = """## Resources

Each is the JSON of a tool call (`inspect`, `search`, `houdini_status`) with
`_meta.etag`: send it back as `_meta["If-None-Match"]` and an unchanged one answers
`_meta.not_modified: true`. Start with `houdini://outline{?root,depth}`; then `status`, `instances`,
`jobs`, `problems`, `events`, and `node/`, `network/`, `geo/`, `image/`, `stage/`,
`type/{category}/{name}`, `types{?q}`. Subscribing to `status`, `jobs`, `events` or
`node/{path}` sends `notifications/resources/updated` when the etag changes.

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

Unsure of a name? Send it with `dry_run: true` first: every problem comes back at once.
Then `inspect {what: "geo", target: "/obj/terrain/mtn"}` and `look {target: "/obj/terrain"}`.

### Two Houdinis: edit in the GUI, render on a worker

Roles: `editor` (GUI), `worker` (headless). With several Houdinis and none pinned,
reads go to the GUI and changes refuse with `ambiguous_instance`:

1. `houdini_connect {role: "editor"}`, edit, `hip_save`.
2. `houdini_connect {role: "worker"}` (with `launch: {mode: "headless"}` to start one),
   `hip_open` the hip, `houdini_connect {role: "editor"}`.
3. `render {rop_path, on: "worker", wait_s: 0}`. `job` finds the job's Houdini whatever
   is pinned, after a server restart too; `{action: list, all: true}` lists all jobs; 1.x
   ids (`<pid>-<id>`) still work.

A pinned Houdini that exits gives `instance_lost` with the live candidates; pin another,
or `houdini_connect {}`. `events` cursors (`<pid>:<seq>`) are per Houdini; another's
answers `reset: true`.

### Copernicus (COP) images

Create a `copnet` in `/img`, then `Cop` nodes in it (`Cop2` is legacy).
`look {target: "/img/net/node"}` shows one in about 0.2 s; `inspect {what: "image"}`
gives resolution and channel stats. To write files, wire `Cop/rop_image` (`copoutput`,
e.g. `$HIP/img/name.$F4.png`) and `render {rop_path: "/img/net/rop_image1"}`; cooking a
ROP writes nothing. SOPs read a COP through `op:/img/net/node` (`attribfrommap`). Over and
multiply are `blend` modes, threshold is `remap`, gradient `ramp`, text `font`.

### Flipbook frames (Flipbook ROP)

`look` is one frame. For a sequence, create `Driver/flipbook` in `/out` (Houdini 22
deprecates the OpenGL ROP) with `camera`, `picture` (e.g. `$HIP/flip/$OS.$F4.png`),
`trange: 1`, `f1`/`f2`, and `tres: 1` with `res1`/`res2` (a stage: `opsource: 1`,
`loppath`, `cameraprim`). `render {rop_path: "/out/flipbook1", wait_s: 0}` returns a job;
its result lists the frames with the last as a thumbnail.

### Add a spare parm (edit node op)

On a null, subnet, geo object or unlocked HDA instance, linked with `ch()` in one call:

```json
{"ops": [{"op": "node", "path": "/obj/geo1/CONTROLS",
          "spare_parms": {"add": [{"name": "glue_strength", "type": "float",
                                   "label": "Glue Strength", "default": 0.5}]}},
         {"op": "set", "path": "/obj/geo1/rbd1/strength",
          "expression": "ch(\\"../CONTROLS/glue_strength\\")"}]}
```

A `ch()` to a missing parm evaluates to 0 silently. A `menu` is a string menu (VEX reads
the token with `chs()`); with `value_type: "int"` its value is the item index (`ch()`).

### GUI sessions: never open a dialog

A modal `hou.ui` call (`displayMessage`, `selectFile`, `readInput`) from
`houdini_python`, a `press`ed callback or a creation script fails the call with
`ui_required`, rolled back (a load script's is a hip_open warning). Pass values as
arguments and print instead. A dialog the user has open holds Houdini: calls return
`houdini_busy`; if they keep doing so with `busy: true` and no job, ask the user to look.
"""

GUIDE_HEADER = """\
# HocusPocus operating guide

## Instructions

"""


def instructions_for() -> str:
    """The server ``instructions`` (BIBLE §4.8)."""
    return INSTRUCTIONS


def guide_sections() -> list[tuple[str, str]]:
    """``(title, text)`` for every ``##`` and ``###`` heading of :func:`guide_text`: a
    section runs to the next heading of its level or above (``inspect {what: "guide",
    target}``, 2.1, D54)."""
    lines = guide_text().splitlines()
    heads = [
        (i, len(line) - len(line.lstrip("#")), line.lstrip("#").strip())
        for i, line in enumerate(lines)
        if line.startswith(("## ", "### "))
    ]
    out = []
    for n, (i, level, title) in enumerate(heads):
        end = next((j for j, lv, _ in heads[n + 1 :] if lv <= level), len(lines))
        out.append((title, "\n".join(lines[i:end]).strip() + "\n"))
    return out


def guide_section(topic: str) -> tuple[str, str] | None:
    """The guide section a topic names: a title equal to it, else the first title that
    contains it, else the first that has every word of it (any case); ``None`` if none."""
    wanted = " ".join(topic.lower().split())
    sections = guide_sections()
    for match in (
        lambda title: title == wanted,
        lambda title: wanted in title,
        lambda title: all(word in title for word in wanted.split()),
    ):
        for title, text in sections:
            if match(title.lower()):
                return title, text
    return None


def guide_text() -> str:
    """The operating manual: instructions, resources and recipes (BIBLE §4.8). The per-tool
    reference is :func:`tools_text` (``hocuspocus://tools``)."""
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
