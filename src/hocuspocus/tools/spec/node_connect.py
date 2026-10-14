"""Catalogue entry for ``node_connect`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _i, _obj, _partial, _s

SPEC = ToolSpec(
    name="node_connect",
    description=(
        "Wire inputs in one undo step: each item connects output from_output of from into to's "
        'to_input (an index, an input name, or "next" for the next free input of merge-style '
        "nodes); from null disconnects."
    ),
    notes=("A bad input fails with invalid_input, and the hint lists the node's input labels."),
    input_schema=_obj(
        {
            "items": _arr(
                _obj(
                    {
                        "from": {
                            "type": ["string", "null"],
                            "description": "Source node or null.",
                        },
                        "from_output": _i(None, minimum=0, default=0),
                        "to": _s(),
                        # bible-silent: to_input default; 0 is the common case.
                        "to_input": {
                            "type": ["integer", "string"],
                            "default": 0,
                            "description": 'Index, input name, or "next".',
                        },
                    },
                    ("from", "to"),
                ),
                minItems=1,
            ),
            "partial": _partial(),
        },
        ("items",),
    ),
    idempotent=True,
    examples=(
        {"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/merge1", "to_input": "next"}]},
        {"items": [{"from": None, "to": "/obj/geo1/xform1", "to_input": 0}]},
    ),
)
