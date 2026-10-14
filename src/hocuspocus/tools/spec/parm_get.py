"""Catalogue entry for ``parm_get`` (BIBLE §4.5)."""

from __future__ import annotations

from ._helpers import (
    ToolSpec,
    _arr,
    _b,
    _enum,
    _frame,
    _list,
    _obj,
    _out,
    _paths,
    _t,
    _tuple_animation,
)

SPEC = ToolSpec(
    name="parm_get",
    profiles=("compat_1x",),
    description=(
        "Read parms by parm (.../tx), tuple (.../t: all components) or component path: value at"
        " frame, raw if different, expression, is_default, locked (parm lock), hda_locked. "
        "Strings over 200 chars are {elided, head} unless full_strings. Tuples add "
        "per-component expressions and keyed names."
    ),
    notes=(
        "frame defaults to the current frame. template is {label, type, default, min, max, "
        "help}; menu items are capped at 50; a menu Houdini builds on the node (a menu "
        "script, or a SOP group or attribute menu) is evaluated on it and marked dynamic: "
        "true, with items [] and a note when it is empty even after a cook of the SOP. keys "
        "is {count, first, last}. On a LOP a USD "
        "attribute name (.../inputs:intensity) reads Houdini's encoded parm "
        "(xn__inputsintensity_i0a), named in path and name."
    ),
    input_schema=_obj(
        {
            "paths": _paths("Parm or tuple paths."),
            "frame": _frame(),
            "include": _arr(_enum(("keys", "menu", "template", "ramp", "multiparm")), default=[]),
            "full_strings": _b(False),
        },
        ("paths",),
    ),
    output_schema=_out(
        {
            "parms": {
                "type": "array",
                "items": _out(
                    {
                        "path": _t("string"),
                        "name": _t("string"),
                        "tuple": _t("string"),
                        "component_names": _list(),
                        "type": _t("string"),
                        "value": {},
                        "raw": {},
                        "expression": _t("string"),
                        "language": _t("string"),
                        **_tuple_animation(),
                        "is_default": _t("boolean"),
                        "locked": _t("boolean"),
                        "hda_locked": _t("boolean"),
                        # {count, first, last}; per component for a tuple.
                        "keyframes": _t("object"),
                        "menu": _t("object"),
                        "ramp": _t("object"),
                        "multiparm": _t("object"),
                        "template": _t("object"),
                    },
                    ("path", "name", "value"),
                ),
            }
        },
        ("parms",),
    ),
    read_only=True,
    examples=(
        {"paths": ["/obj/geo1/box1/size"]},
        {"paths": ["/obj/geo1/xform1/tx"], "frame": 24, "include": ["keys"]},
    ),
)
