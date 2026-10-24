"""Catalogue entry for ``node_create`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import (
    ToolSpec,
    _arr,
    _b,
    _enum,
    _flags,
    _input_link,
    _obj,
    _parm_value,
    _partial,
    _return,
    _s,
    _xy,
)

SPEC = ToolSpec(
    name="node_create",
    profiles=("minimal", "core", "full"),
    description=(
        "Create nodes in one undo step. type resolves like createNode (box gets the current "
        "version; exact_type disables). Items may wire to earlier items; a block_end pairs with"
        " its block_begin (paired_with). Returns path, type and problems per node. "
        "network_build suits whole graphs."
    ),
    notes=(
        "A parms value is a literal, {expression, language} (short form {expr, lang}), or any "
        "parm_set item without path. As in parm_set, a plain set of a menu or toggle with a "
        "callback script carries a note that the callback did not run; {value, press: true} "
        "runs it once the node's inputs are wired, and the row adds side_effects: {parm: "
        "[old, new]}. A type hou.NodeType.deprecated() reports (the OpenGL ROP in 22.0) "
        "gets deprecated: true and a note with its reason or replacement (the note once per "
        "type per Houdini session). An input is "
        "{index or name, from, output (default 0)}. "
        "layout good_position places new nodes. return full gives node_info blocks listing only"
        " the parms the call set, with strings over 200 characters as {elided, head}; identical"
        " error lists after the first become errors_same_as. Each new node is cooked once to "
        "report its problems, and its row carries cook_ms (a first cook of an HDA such as "
        "mountain can take 200 ms); cook: false skips that cook (cook_state: not_cooked), for "
        "batch builders that cook once at the end."
    ),
    input_schema=_obj(
        {
            "items": _arr(
                _obj(
                    {
                        "parent": _s(),
                        "type": _s(),
                        "name": _s(),
                        "parms": {
                            "type": "object",
                            "additionalProperties": _parm_value(),
                            "description": (
                                "Parm name to a value or a parm_set item without path."
                            ),
                        },
                        "inputs": _arr(_input_link()),
                        "flags": _flags(),
                        "position": _xy("[x, y]"),
                    },
                    ("parent", "type"),
                ),
                minItems=1,
            ),
            "layout": _enum(("good_position", "none"), "good_position"),
            "exact_type": _b(False),
            "cook": _b(True),
            "partial": _partial(),
            "return": _return(),
        },
        ("items",),
    ),
    examples=(
        {"items": [{"parent": "/obj", "type": "geo", "name": "terrain"}]},
        {
            "items": [
                {
                    "parent": "/obj/terrain",
                    "type": "grid",
                    "parms": {"size": [10, 10], "rows": 100, "cols": 100},
                },
                {
                    "parent": "/obj/terrain",
                    "type": "mountain",
                    "inputs": [{"index": 0, "from": "/obj/terrain/grid1"}],
                    "parms": {"height": {"expression": "ch('../grid1/sizex') * 0.1"}},
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    ),
)
