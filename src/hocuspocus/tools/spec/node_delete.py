"""Catalogue entry for ``node_delete`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _obj, _paths

SPEC = ToolSpec(
    name="node_delete",
    profiles=("compat_1x",),
    description=(
        "Delete nodes in one undo step and return the deleted paths. keep_connections "
        "reconnects input 0 to the deleted node's outputs where possible, like deleting in the "
        "network editor."
    ),
    input_schema=_obj({"paths": _paths(), "keep_connections": _b(True)}, ("paths",)),
    destructive=True,
    examples=(
        {"paths": ["/obj/geo1/box1"]},
        {"paths": ["/obj/geo1"], "keep_connections": False},
    ),
)
