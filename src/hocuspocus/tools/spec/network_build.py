"""Catalogue entry for ``network_build`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _b, _enum, _obj, _return, _s

SPEC = ToolSpec(
    name="network_build",
    description=(
        "Build or update a network under parent from Houdini's hou.data childrenAsData format "
        "(what network_describe returns) in one undo step. Types and inputs are validated "
        "first; dry_run stops there. Returns created paths and per node path, type and "
        "problems."
    ),
    notes=(
        "Input entries are {from, from_index, to_index}; a missing to_index is the entry's "
        "position in the list. return full adds flags. tag is stored as the userData "
        "hocuspocus:tag. setChildrenFromData sets parms without running their callback "
        "scripts: a menu or toggle with one that data sets gets a note in notes (as on "
        "node_create). press: {node: [parm names]} runs those callbacks (menus, toggles, "
        "buttons) after the build is wired, in order, inside the same undo step; a node is "
        "a path in data relative to parent (geo1/src) or absolute, and must be built by "
        "this call. The result adds pressed (parm paths) and side_effects: {node path: "
        "{parm: [old, new]}}. A press that fails rolls the whole build back; dry_run "
        "validates the node names. data keeps Houdini's hou.data format, so press is an "
        "argument, not a key inside an entry."
    ),
    input_schema=_obj(
        {
            "parent": _s(),
            # Inner shape is Houdini's own hou.data format (bible D6); left open on purpose.
            # setChildrenFromData itself puts inputs without to_index on input 0; the host
            # fills to_index from the list position first (bible §5.10).
            "data": {"type": "object", "description": "hou.data childrenAsData dict."},
            "on_name_collision": _enum(("error", "rename", "replace"), "error"),
            "layout": _b(True),
            "dry_run": _b(False),
            # bible §5.14: the only userData HocusPocus may write into a scene.
            "tag": _s("Stored as userData hocuspocus:tag."),
            "press": {
                "type": "object",
                "description": "Callbacks to run after the build: {node: [parm names]}.",
                "additionalProperties": _arr({"type": "string"}, minItems=1),
            },
            "return": _return(),
        },
        ("parent", "data"),
    ),
    examples=(
        {
            "parent": "/obj/geo1",
            "data": {
                "box1": {"type": "box"},
                "sphere1": {"type": "sphere"},
                "merge1": {
                    "type": "merge",
                    "inputs": [
                        {"from": "box1", "from_index": 0, "to_index": 0},
                        {"from": "sphere1", "from_index": 0, "to_index": 1},
                    ],
                    "flags": {"display": True},
                },
            },
            "dry_run": True,
        },
    ),
)
