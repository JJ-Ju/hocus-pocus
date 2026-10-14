"""Catalogue entry for ``node_info`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import (
    _NODE_INFO_SECTIONS,
    ToolSpec,
    _arr,
    _b,
    _enum,
    _list,
    _obj,
    _objs,
    _out,
    _paths,
    _problems,
    _t,
)

SPEC = ToolSpec(
    name="node_info",
    profiles=("compat_1x",),
    description=(
        "Read nodes in detail: type, flags, inputs with names and sources, non-default parms "
        "(value, raw, expression; long strings elided), errors, warnings, cook state. parm_get "
        "reads keyframes, menus and templates; network_describe a whole network."
    ),
    notes=(
        "Default include: parms, inputs, errors, flags. Parm rows are name, value, raw (only "
        "when it differs), expression, keyed, locked, menu_token; strings over 200 characters "
        "come as {elided, head}. hda_locked is true at or inside a locked asset."
    ),
    input_schema=_obj(
        {
            "paths": _paths(),
            "include": _arr(
                _enum(_NODE_INFO_SECTIONS), default=["parms", "inputs", "errors", "flags"]
            ),
            "include_defaults": _b(False),
            # §4.1: node_info does not descend into locked HDAs unless recurse_locked.
            "recurse_locked": _b(False),
        },
        ("paths",),
    ),
    output_schema=_out(
        {
            "nodes": {
                "type": "array",
                "items": _out(
                    {
                        "path": _t("string"),
                        "name": _t("string"),
                        "session_id": _t("integer"),
                        # {name, category, version, description, help_url}
                        "type": _t("object"),
                        "flags": _t("object"),
                        "inputs": _objs(),
                        "outputs": _objs(),
                        "parms": _objs(),
                        **_problems(),
                        "cook_state": _t("string"),
                        "children_count": _t("integer"),
                        "hda_locked": _t("boolean"),
                        "hda": _t(["object", "null"]),
                        "position": _list("number"),
                        "comment": _t("string"),
                        "color": _list("number"),
                    },
                    ("path", "type"),
                ),
            }
        },
        ("nodes",),
    ),
    read_only=True,
    examples=(
        {"paths": ["/obj/geo1/box1"]},
        {"paths": ["/obj/geo1"], "include": ["children", "flags"]},
    ),
)
