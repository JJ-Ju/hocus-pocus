"""Catalogue entry for ``node_copy`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _b, _obj, _paths, _return, _s, _xy

SPEC = ToolSpec(
    name="node_copy",
    profiles=("compat_1x",),
    description=(
        "Copy nodes into to_parent, which may be their own network. names renames the copies in"
        " paths order; with_inputs keeps wiring among copied nodes; position_offset shifts "
        "them. Returns the new paths and per copy path, type and problems."
    ),
    notes=("return full adds flags to each row."),
    input_schema=_obj(
        {
            "paths": _paths(),
            "to_parent": _s(),
            "names": _arr({"type": "string"}),
            "with_inputs": _b(True),
            "position_offset": _xy("[dx, dy]"),
            "return": _return(),
        },
        ("paths", "to_parent"),
    ),
    examples=({"paths": ["/obj/geo1/box1"], "to_parent": "/obj/geo2"},),
)
