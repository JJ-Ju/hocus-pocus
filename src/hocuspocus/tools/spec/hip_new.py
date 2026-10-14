"""Catalogue entry for ``hip_new`` (BIBLE §4.3)."""

from __future__ import annotations

from ._helpers import ToolSpec, _obj, _on_unsaved, _out, _t

SPEC = ToolSpec(
    name="hip_new",
    profiles=("core", "full", "compat_1x"),
    description=(
        "Clear to a new untitled scene; bumps scene_generation. on_unsaved protects unsaved "
        "work: fail returns unsaved_changes, save saves first (an untitled scene needs hip_save"
        " with path instead), discard drops the changes."
    ),
    input_schema=_obj({"on_unsaved": _on_unsaved()}),
    # bible-silent: result shape. Report the new scene and whether unsaved work was saved.
    output_schema=_out(
        {
            "path": _t("string"),
            "name": _t("string"),
            "dirty": _t("boolean"),
            "is_new": _t("boolean"),
            "saved_first": _t("boolean"),
            "scene_generation": _t("integer"),
        },
        ("path", "saved_first", "scene_generation"),
    ),
    destructive=True,
    examples=({}, {"on_unsaved": "save"}),
)
