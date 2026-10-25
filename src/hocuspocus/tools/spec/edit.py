"""Catalogue entry for ``edit`` (spec-2.0 §2.4; BIBLE §4.9)."""

from __future__ import annotations

from ._helpers import (
    ToolSpec,
    _arr,
    _b,
    _enum,
    _i,
    _n,
    _obj,
    _s,
)

OPS = ("create", "delete", "connect", "set", "node", "copy", "layout", "build", "select")

SPEC = ToolSpec(
    name="edit",
    profiles=("minimal", "core", "full"),
    description=(
        "Change the scene in one undo step. ops run in order, each {op, "
        "id?, ...}: create, delete, connect, set, node (rename, flags, color, comment, "
        "position, lock, spare_parms), copy, layout, build (hou.data), select; later ops name "
        "an earlier op's node as $id. dry_run validates, returning resolved paths. A failure "
        "rolls all back unless partial. Returns per-node rows (problems only) and ids."
    ),
    notes=(
        "Each op takes the fields of the 1.4 tool it replaces. create: parent, type, name, "
        "parms, inputs [{index or name, from, output}], flags, position, and per op "
        "exact_type, cook (false skips the echo's cook) and layout (good_position | none), as "
        "node_create. delete: paths (or path), keep_connections, as node_delete. connect: "
        "from (null disconnects), from_output, to, to_input (index, name or next), as "
        "node_connect. set: one parm_set item (path plus value, expression, keyframe(s), "
        "channel_ref, ramp, multiparm_count, revert_to_default or press; language, "
        "animation, frame), or {node, parms: {name: value or item}} for several parms of one "
        "node. node: path plus name, flags, bypass, color, comment, position, lock, "
        "spare_parms, as node_edit. copy: paths, to_parent, names, with_inputs, "
        "position_offset, as node_copy. layout: parent, paths, mode, as node_layout. build: "
        "parent, data, on_name_collision, layout (boolean), tag, press, as network_build. "
        "select: paths (an empty list clears). "
        "flags (create, node): display, render, bypass, template, material (a VOP material "
        "subnet, which a Material Library LOP imports), unload (SOPs, CHOPs) and export "
        "(CHOPs, COPs); a node without one says which it takes. Inside a subnet, from (or "
        "inputs[].from) naming the subnet itself wires its input from_output (output): "
        "the subnet's own input of that index (a VOP subnet has none: wire its subinput). "
        "path (2.1) is every op's name for the node it acts on, next to the 1.4 field: a "
        "create op's path is the new node's (parent plus name), connect's is to, layout's and "
        "build's parent, copy's, select's and delete's paths [path], a set op's with parms "
        "its node, and a node op also takes node; both spellings at once must agree. "
        "set (2.1) also takes patch, [{find, replace, all?}] (one object is a list of one): "
        "edits of a string parm's text in order, each find occurring exactly once (all: true, "
        "at least once), else invalid_value naming the nearest lines as candidates; and "
        "value_file, a UTF-8 text file ($HIP and ~ expand, approved_roots, at most 8 MB) "
        "whose text becomes a string parm's value. Both write plain text (a parm with keys or "
        "an expression is refused), also as {node, parms: {name: {patch}}}; the result row "
        "adds patched_lines or value_file. inspect {what: parms, target, full_strings: true} "
        "reads a long string back whole. "
        "spare_parms: {add: [{name, type: float, int, string, toggle, menu, button, vector, "
        "color, file, folder, separator or label, label, default, size, min, max, "
        "min_strict, max_strict, menu_items [{token, label}] (menus and strings), value_type "
        "(menus: string or int), help, disable_when and hide_when (Houdini conditions such "
        "as { parm == 1 }, naming parms of the node), join_next, tags {}, callback (Python), "
        "hidden, folder_type (folders: tabs, collapsible, simple, radio), folder (a label, "
        "or [labels] for nested folders, made as tabs when missing), before or after (a parm "
        "name)}], change: [{name, the same fields}] (keeps the value; folder, before or after "
        "moves it), remove: [names]}; change and remove touch spare parms only (hda "
        "interface edits an asset's own). "
        "An id (letters, digits, _) names the op's node: the created node, the connect "
        "target, the set or node op's node, the single copy, the layout or build parent. "
        "$id, or $id/child and $id/parm, works in the path fields (parent, path, paths, "
        "node, from, to, to_parent, channel_ref, inputs[].from), never in parm values, and "
        "resolves to the path the op produced. Each op is checked by running it against the "
        "scene the earlier ops left (an unlock, a multiparm count, a rename, a new node's "
        "outputs count for the ops after it). A failing op is reverted and the ops after it "
        "still run in check mode (no press callback, no selection change, a delete or "
        "lock: true held back), then the call is rolled back and the error lists every "
        "problem in detail.problems. dry_run is that check from the first op, rolled back "
        "with no undo step, event or dirty flag: its plan has each op's resolved paths, "
        "predicted: true where Houdini numbered the node, and the run gives the same paths "
        "on the same scene. "
        "The error names the op field, ops[i].<field>: ... (ops[i] (path) when "
        "none applies; a missing from, to or parent lists the parent's nearest children as "
        "candidates), with detail.field and detail.rolled_back as performed (a "
        "delete cannot be compensated, so the dispatcher's undo of the step decides). With "
        "partial: true a failing op reverts only itself and the rest stand; with partial: "
        "stop the ops before the first failing op stand, the rest do not run, and the "
        "result adds applied (how many ops ran) and failed (resend ops[applied:] with ids "
        "replaced by the result's ids). Result (return summary): nodes, one row per touched "
        "node, each cooked once after every op ran (node ops and cook: false creates do not "
        "cook; a cook downstream still cooks them): path and type, plus errors and warnings "
        "when not empty (a list repeated downstream becomes errors_same_as), cook_state "
        "when not cooked, cook_ms from 1 ms, and the ops' results for that node (old_path, "
        "paired_with, deprecated, hda, notes, side_effects); ids {id: path} for every op "
        "id; deleted, reconnected, selected (context_changed), renamed, replaced when an "
        "op did that; failed [{item, op, id, error}] with partial. The cooks run after "
        "the change is made, as a job the call waits on for up to job_threshold_s (10 s): "
        "rows of nodes still cooking then say cook_state cooking, and the result adds "
        "job_id, state running and a message; job {action: result, job_id} returns their "
        "rows. return ops adds "
        "results, one row per op (op, "
        "id, path, and what it did: set values, input and from, spare_parms, created, "
        "copies); return full gives the 1.4 full shapes (flags and messages on nodes, "
        "create parms the call set, strings over 200 characters as {elided, head}) and "
        "failed as a count. The undo label is HocusPocus: edit <n> ops."
    ),
    # Field shapes are the 1.4 tools' (notes); the host checks them, so the schema names the
    # fields and their JSON types only (spec-2.0 principle 13: bytes per tools/list).
    input_schema=_obj(
        {
            "ops": _arr(
                _obj(
                    {
                        "op": _enum(OPS),
                        "id": _s("Name later ops use as $id."),
                        "parent": _s(),
                        "type": _s(),
                        "name": _s(),
                        "parms": {"type": "object"},
                        "inputs": _arr({"type": "object"}),
                        "flags": {"type": "object"},
                        "position": _arr({"type": "number"}, minItems=2, maxItems=2),
                        "exact_type": {"type": "boolean"},
                        "cook": {"type": "boolean"},
                        "layout": {"type": ["string", "boolean"]},
                        "path": _s(),
                        "paths": _arr({"type": "string"}),
                        "keep_connections": {"type": "boolean"},
                        "from": {"type": ["string", "null"]},
                        "from_output": _i(None, minimum=0),
                        "to": _s(),
                        "to_input": {"type": ["integer", "string"]},
                        "value": {},
                        "patch": {"type": ["array", "object"]},
                        "value_file": _s(),
                        "expression": _s(),
                        "language": _enum(("hscript", "python")),
                        "keyframe": {"type": "object"},
                        "keyframes": {"type": "array"},
                        "channel_ref": _s(),
                        "ramp": {"type": "object"},
                        "multiparm_count": _i(None, minimum=0),
                        "revert_to_default": {"type": "boolean"},
                        "press": {"type": ["boolean", "object"]},
                        "animation": _enum(("replace", "key", "keep")),
                        "frame": _n(),
                        "node": _s(),
                        "color": _arr({"type": "number"}, minItems=3, maxItems=3),
                        "comment": _s(),
                        "lock": {"type": "boolean"},
                        "bypass": {"type": "boolean"},
                        "spare_parms": {"type": "object"},
                        "to_parent": _s(),
                        "names": _arr({"type": "string"}),
                        "with_inputs": {"type": "boolean"},
                        "position_offset": _arr({"type": "number"}, minItems=2, maxItems=2),
                        "mode": _enum(("children", "good_position")),
                        "data": {"type": "object"},
                        "on_name_collision": _enum(("error", "rename", "replace")),
                        "tag": _s(),
                    },
                    ("op",),
                ),
                minItems=1,
            ),
            "dry_run": _b(False),
            "return": _enum(("summary", "ops", "full"), "summary"),
            "partial": {
                "type": ["boolean", "string"],
                "enum": [False, True, "stop"],
                "default": False,
                "description": "Keep what worked; stop: the ops before a failure.",
            },
        },
        ("ops",),
    ),
    destructive=True,
    examples=(
        {
            "ops": [
                {"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
                {"op": "create", "id": "box", "parent": "$geo", "type": "box"},
                {
                    "op": "create",
                    "id": "mtn",
                    "parent": "$geo",
                    "type": "mountain",
                    "inputs": [{"index": 0, "from": "$box"}],
                    "parms": {"height": 0.5},
                },
                {
                    "op": "create",
                    "id": "sub",
                    "parent": "$geo",
                    "type": "subdivide",
                    "inputs": [{"index": 0, "from": "$mtn"}],
                    "parms": {"iterations": 2},
                },
                {
                    "op": "create",
                    "parent": "$geo",
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": "$sub"}],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
        {
            "ops": [
                {"op": "set", "path": "/obj/terrain/box1/size", "value": [2, 1, 2]},
                {
                    "op": "connect",
                    "from": "/obj/terrain/box1",
                    "to": "/obj/terrain/merge1",
                    "to_input": "next",
                },
                {"op": "node", "path": "/obj/terrain/OUT", "comment": "final"},
            ],
            "dry_run": True,
        },
    ),
)
