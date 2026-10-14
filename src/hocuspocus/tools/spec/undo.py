"""Catalogue entry for ``undo`` (BIBLE §4.7)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _enum, _i, _list, _obj, _out, _t

SPEC = ToolSpec(
    name="undo",
    profiles=("core", "full", "compat_1x"),
    description=(
        "Undo or redo steps (default 1) and return the labels performed, or list the last 20 "
        "undo labels with history. Every HocusPocus mutation is one step labelled "
        '"HocusPocus: <tool> ...".'
    ),
    input_schema=_obj(
        {
            "action": _enum(("undo", "redo", "history")),
            "steps": _i(None, minimum=1, default=1),
            "include_user_steps": _b(False),
        },
        ("action",),
    ),
    notes=(
        "undo and redo stop at the first step whose label does not start with "
        "\"HocusPocus:\" (the user's or Houdini's own) and name it in blocked_by; "
        "include_user_steps: true crosses such steps and lists them in user_steps. redo "
        "never re-applies a call that failed and was rolled back: it stops and names it in "
        "skipped, and history lists it under rolled_back, not redo. history's total and "
        "redo_total count every label; hip_open and hip_new clear the history."
    ),
    output_schema=_out(
        {
            "performed": _list(),
            "history": _list(),
            "redo": {"type": "array", "items": _t("string"), "description": "history only."},
            "enabled": _t("boolean"),
            "next_undo": _t(["string", "null"]),
            "next_redo": _t(["string", "null"]),
            "undo_count": _t("integer"),
            "redo_count": _t("integer"),
            "dirty": _t("boolean"),
            "scene_generation": _t("integer"),
            "note": _t("string"),
            "blocked_by": _t("string"),
        }
    ),
    # Registered scene=False (performUndo raises inside an undo group); not idempotent.
    examples=({"action": "history"}, {"action": "undo", "steps": 2}),
)
