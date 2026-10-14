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
    _partial,
    _return,
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
        "rolls all back unless partial. Returns per-op rows and per-node problems."
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
        "An id (letters, digits, _) names the op's node: the created node, the connect "
        "target, the set or node op's node, the single copy, the layout or build parent. "
        "$id, or $id/child and $id/parm, works in the path fields (parent, path, paths, "
        "node, from, to, to_parent, channel_ref, inputs[].from), never in parm values, and "
        "resolves to the path the op produced. Every op is validated before anything "
        "changes (types, parents and their category, parm names, inputs, free names, locked "
        "assets) against the scene as the earlier ops leave it; dry_run returns that plan, "
        "with predicted: true on a path Houdini will number. A failing op rolls the whole "
        "call back; the error is items[i] (path) with detail.rolled_back as performed (a "
        "delete cannot be compensated, so the dispatcher's undo of the step decides). With "
        "partial, ops run without the up-front validation and a failing op reverts only "
        "itself; its row carries error. Result: results (one row per op: op, id, path, "
        "and what it did: paired_with, notes, deprecated, side_effects, set values, input "
        "and from, old_path, deleted, created, selected), nodes (the summary row per "
        "touched node: path, type, errors, warnings, cook_state, cook_ms, each cooked once "
        "after every op ran; node ops do not cook), failed with partial. return full adds "
        "flags to nodes and the 1.4 full rows to results (create parms the call set, with "
        "strings over 200 characters as {elided, head}). The undo label is HocusPocus: edit "
        "<n> ops."
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
            "return": _return(),
            "partial": _partial(),
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
