"""Server ``instructions`` (shipped in ``initialize``), the ``hocuspocus://guide`` text and
the ``hocuspocus://tools`` reference.

See docs/BIBLE.md §4.8. Keep ``INSTRUCTIONS`` under 400 words and the guide under
:data:`GUIDE_MAX_BYTES`; unit tests enforce both.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hocuspocus.tools.catalog import ToolSpec

GUIDE_MAX_BYTES = 8192
"""``hocuspocus://guide`` is instructions and recipes only (review 19 papercut 10: with the
tool reference appended it was 52 KB); the reference is ``hocuspocus://tools``."""

INSTRUCTIONS = """\
HocusPocus drives a live Houdini. Identity is Houdini paths. Start with `houdini_status`; \
if nothing is connected, `houdini_connect` can launch Houdini (GUI or headless hython) or \
attach to a running one by pid. With several Houdinis running, pin one with \
`houdini_connect {pid}`: until then calls that change a scene refuse with \
`ambiguous_instance`, and if the pinned one exits calls return `instance_lost` instead of \
switching. `_meta.instance` names the Houdini that answered; job ids and `events` cursors \
carry their pid. Build with `node_create` (batch, with parms and inputs) or \
`network_build` (whole graph from the `network_describe` format). Read with `node_info` and \
`network_describe`. Change values with `parm_set`; tuple paths like `.../t` take lists, \
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
`node_type_info` is large \
for FX types: pass `parms` globs, or `detail: "folders"` first. Add spare parms with \
`node_edit` `spare_parms` (recipe in `hocuspocus://guide`). The resource `houdini://outline` \
is the whole scene as a compact tree; `hocuspocus://tools` is the full tool reference."""

RESOURCES = """## Resources

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

RECIPES = """## Recipes

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

Copernicus networks live in `/img`: `node_create {parent: "/img", type: "copnet"}`, then
the nodes inside it with category `Cop` (`Cop2` is the legacy compositor). To look at any
COP node: `viewport_capture {cop_path: "/img/net/node"}` returns its image in about 0.2 s;
`geo_info` on a COP node gives resolution and per-channel stats. To write files, wire a
`Cop/rop_image` (its `copoutput` parm is the file, e.g. `$HIP/img/name.$F4.png`) and
`render {rop_path: "/img/net/rop_image1"}`, which also returns a thumbnail. Cooking a ROP
writes nothing. SOPs read a COP live through an `op:` path, e.g. `attribfrommap` with
`filename: "op:/img/net/node"`. Compositing verbs: over and multiply are `blend` modes, a
threshold is `remap` (op threshold), a gradient is `ramp`, text is `font`.

### Add a spare parm (node_edit spare_parms)

Add a control parm to a null, subnet, geo object or an unlocked HDA instance with
`node_edit`, then drive other parms from it with `ch()`:

```json
{"items": [{"path": "/obj/geo1/CONTROLS",
            "spare_parms": {"add": [{"name": "glue_strength", "type": "float",
                                     "label": "Glue Strength", "default": 0.5}]}}]}
```

`parm_set {path: "/obj/geo1/rbd1/strength", expression: 'ch("../CONTROLS/glue_strength")'}`
then links to it. A `ch()` to a parm that does not exist evaluates to 0 silently.

A `menu` is a string menu by default: VEX reads its token with `chs()` (`ch()` gives the
item index). For a menu that VEX reads as a number, pass `value_type: "int"`: the parm is
an int whose value is the item index, read with `ch()` or `chi()`:

```json
{"name": "roof_type", "type": "menu", "value_type": "int", "default": 0,
 "menu_items": [{"token": "flat", "label": "Flat"}, {"token": "pyramid", "label": "Pyramid"}]}
```
"""

GUIDE_HEADER = """\
# HocusPocus operating guide

## Instructions

"""


def guide_text() -> str:
    """The operating manual: instructions, resources and recipes (BIBLE §4.8). The per-tool
    reference is :func:`tools_text` (``hocuspocus://tools``)."""
    return "".join([GUIDE_HEADER, INSTRUCTIONS, "\n\n", RESOURCES, RECIPES])


def tools_text(tools: Sequence[ToolSpec] | None = None) -> str:
    """``hocuspocus://tools``: the per-tool reference rendered from the catalogue (the same
    text as ``docs/tools.md``, including each tool's ``notes``, which ``tools/list`` leaves
    out; BIBLE §4.1). ``tools`` defaults to the whole catalogue."""
    from hocuspocus.tools.catalog import TOOLS
    from hocuspocus.tools.docs import render_tools_markdown

    return render_tools_markdown(tuple(tools) if tools is not None else TOOLS)
