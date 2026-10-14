"""Catalogue entry for ``node_edit`` (BIBLE §4.4)."""

from __future__ import annotations

from ._helpers import ToolSpec, _arr, _flags, _obj, _partial, _s, _t, _xy

SPEC = ToolSpec(
    name="node_edit",
    description=(
        "Change node properties in one undo step: rename, flags, bypass, color, comment, "
        "position, lock (false allows editing a locked HDA's contents). spare_parms adds {name,"
        " type: float|int|string|toggle|menu|button|vector|color, label, default, size, min, "
        "max, menu_items [{token, label}], value_type, folder, help} or removes spare parms by "
        "name. Menu value_type string (default): chs() gives the token; int: ch() gives the "
        "item index."
    ),
    notes=(
        "A rename returns old_path and path; spare_parms returns the added and removed parm "
        "paths. Only spare parms can be removed; a name already on the node fails with "
        "name_collision; nodes inside a locked asset are refused with locked. A folder label is"
        " created when missing. value_type is for menus only: string makes a menu parm whose "
        "value is the token (VEX chs(); ch() gives the item index); int makes an int parm with "
        "that menu whose value is the item index (ch() or chi(); chs() gives the index as "
        "text). A menu default is a token or an item index; a number that is no index but "
        'equals a token\'s text (-1 for token "-1") picks that token.'
    ),
    input_schema=_obj(
        {
            "items": _arr(
                _obj(
                    {
                        "path": _s(),
                        "name": _s("New name."),
                        "flags": _flags(),
                        "color": _arr({"type": "number"}, "[r, g, b] 0-1", minItems=3, maxItems=3),
                        "comment": _s(),
                        "position": _xy("[x, y]"),
                        "lock": {"type": "boolean"},
                        "bypass": {"type": "boolean"},
                        # Review 11 B9; entries are validated by the host (parms.py).
                        "spare_parms": _obj(
                            {"add": _arr(_t("object")), "remove": _arr(_t("string"))}
                        ),
                    },
                    ("path",),
                ),
                minItems=1,
            ),
            "partial": _partial(),
        },
        ("items",),
    ),
    idempotent=True,
    examples=(
        {"items": [{"path": "/obj/geo1/box1", "name": "base_box"}]},
        {"items": [{"path": "/obj/geo1/null1", "color": [1, 0, 0], "comment": "OUT"}]},
        {
            "items": [
                {
                    "path": "/obj/geo1/wrangle1",
                    "spare_parms": {
                        "add": [{"name": "glue", "type": "float", "default": 1, "max": 10}]
                    },
                }
            ]
        },
    ),
)
