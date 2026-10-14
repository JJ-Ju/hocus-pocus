"""Catalogue entry for ``node_layout`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _enum, _obj, _s

SPEC = ToolSpec(
    name="node_layout",
    description=(
        "Tidy a network. mode children lays out the children of parent, or only paths; "
        "good_position moves each node in paths to a free spot near its inputs."
    ),
    input_schema=_obj(
        {
            "parent": _s(),
            "paths": _arr({"type": "string"}, "Subset of children."),
            "mode": _enum(("children", "good_position"), "children"),
        },
        ("parent",),
    ),
    examples=({"parent": "/obj/geo1"},),
)
