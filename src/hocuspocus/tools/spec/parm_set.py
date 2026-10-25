"""Catalogue entry for ``parm_set`` (BIBLE §4.5)."""

from __future__ import annotations

from ._helpers import (
    ToolSpec,
    _arr,
    _enum,
    _frame,
    _i,
    _key,
    _list,
    _literal_value,
    _obj,
    _out,
    _partial,
    _s,
    _t,
    _tuple_animation,
)

SPEC = ToolSpec(
    name="parm_set",
    profiles=("minimal", "core", "full"),
    description=(
        "Set parms in one undo step. Each item takes one of value, expression, keyframe(s), "
        "channel_ref, ramp, multiparm_count, revert_to_default, press. Tuple paths take lists, "
        "component paths scalars; menus take token or label. animation replace clears keys and "
        "expressions first; key keys at frame; keep is plain set. Returns value, raw, "
        "wrote_keyframe, node errors."
    ),
    notes=(
        "With animation replace a single keyframe only adds or replaces its own key. press "
        "clicks a button parm and returns pressed and side_effects ({parm: [old, new]} it "
        "changed); on a writer's save button (File Cache Save to Disk, a ROP SOP's Render) the "
        "output files over its frame range are checked afterwards: outputs_summary, or "
        "cook_failed with detail.missing. press also runs the callback script of a non-button "
        "parm (pyrosource initialize), and with value it sets the value first; a plain set "
        "of a menu or toggle with a callback notes that the callback did not run. A string "
        "menu only the node builds (a Copernicus signature) takes a token or label like any "
        "menu. A press still running after job_threshold_s (10 s) answers {job_id, state: "
        "running, running: <parm path>, message} (2.1, D70); job {action: result} returns "
        "this result when the callback ends, its error if the call failed (a callback "
        "cannot be interrupted, so cancel leaves it running), and calls that need the main "
        "thread meanwhile answer houdini_busy naming it, with detail.job_id. edit set and "
        "create ops and node_create press the same way. Ramp keys and values come back at 6 significant digits, without raw. "
        "raw is left out when it equals value, and long strings are "
        "elided as in inspect parms. Tuples report per-component expressions and the keyed component"
        " names. Type mismatches fail with invalid_value naming the template type and range. "
        "On a LOP a USD attribute name (inputs:intensity) sets Houdini's encoded parm "
        "(xn__inputsintensity_i0a), here and in node_create parms; path is the resolved one."
    ),
    input_schema=_obj(
        {
            "items": _arr(
                _obj(
                    {
                        "path": _s("Parm, tuple or component path."),
                        "value": _literal_value(),
                        "expression": _s(),
                        "language": _enum(("hscript", "python"), "hscript"),
                        "keyframe": _key(),
                        "keyframes": _arr(_key()),
                        "channel_ref": _s("Parm path to reference."),
                        "ramp": _obj(
                            {
                                "basis": {
                                    "type": ["string", "array"],
                                    "items": {"type": "string"},
                                    "description": "One basis, or one per key.",
                                },
                                "keys": _arr({"type": "number"}),
                                "values": _arr(
                                    {"type": ["number", "array"], "items": {"type": "number"}}
                                ),
                            },
                            ("keys", "values"),
                        ),
                        "multiparm_count": _i(None, minimum=0),
                        "revert_to_default": {"type": "boolean"},
                        "press": {"type": "boolean"},
                        "animation": _enum(("replace", "key", "keep"), "replace"),
                    },
                    ("path",),
                ),
                minItems=1,
            ),
            "frame": _frame(),
            "partial": _partial(),
        },
        ("items",),
    ),
    output_schema=_out(
        {
            "results": {
                "type": "array",
                "items": _out(
                    {
                        "path": _t("string"),
                        "value": {},
                        "raw": {},
                        "expression": _t("string"),
                        "language": _t("string"),
                        **_tuple_animation(),
                        "wrote_keyframe": _t("boolean"),
                        "is_default": _t("boolean"),
                        "errors": _list(),
                        "warnings": _list(),
                    },
                    ("path", "wrote_keyframe"),
                ),
            },
            # A press past job_threshold_s answers as a job instead (2.1, D70).
            "job_id": _t("string"),
            "state": _t("string"),
        },
    ),
    idempotent=True,
    examples=(
        {"items": [{"path": "/obj/geo1/box1/size", "value": [2, 1, 2]}]},
        {"items": [{"path": "/obj/geo1/xform1/ry", "expression": "$F * 3"}]},
        {
            "items": [
                {
                    "path": "/obj/geo1/xform1/ty",
                    "keyframe": {"frame": 1, "value": 0},
                    "animation": "key",
                }
            ]
        },
    ),
)
