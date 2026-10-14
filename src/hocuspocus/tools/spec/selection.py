"""Catalogue entry for ``selection`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _list, _obj, _out

SPEC = ToolSpec(
    name="selection",
    profiles=("compat_1x",),
    description=(
        "Read or set the node selection. Omit paths to get the selected node paths; pass paths "
        "to select exactly those (an empty list clears the selection)."
    ),
    input_schema=_obj({"paths": _arr({"type": "string"})}),
    output_schema=_out({"selected": _list()}, ("selected",)),
    idempotent=True,
    examples=({}, {"paths": ["/obj/geo1/box1"]}),
)
