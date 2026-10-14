"""Catalogue entry for ``houdini_status`` (BIBLE §4.2)."""

from __future__ import annotations

from ._helpers import PROFILES_2X, ROLES, ToolSpec, _connected_block, _obj, _out, _t

SPEC = ToolSpec(
    name="houdini_status",
    profiles=("minimal", "core", "full", "compat_1x"),
    description=(
        "Start here. Reports the connected Houdini (pid, version, GUI or headless, hip path and"
        " dirty state, $HIP/$JOB, frame, recent files, scene_generation), every live instance "
        "and the bridge settings. Works with no Houdini running (connected: null)."
    ),
    notes=(
        "Also reports $HIPNAME, fps, the frame range, and the bridge's profile, read_only and "
        "allow_python. An untitled scene's hip carries a note that $HIP is the launch directory"
        " until hip_save. Each instances[] row has pid, port, label, houdini, ui, hip, "
        "started, launched_by, name (when given), selected (the pinned instance, or the one "
        "reads go to), busy (the main thread has been held for over a second) and "
        "jobs_running. With several instances and none pinned, tools that change a scene "
        "refuse with ambiguous_instance: pin one with houdini_connect {pid}. When the pinned "
        "Houdini has exited, connected is null and lost: {pid, label} names it. "
        "connected.memory is {rss_mb, peak_mb}: the Houdini process's resident and peak "
        "memory (watch it while a sim cache fills). "
        "profile is minimal, core or full; under compat_1x it reads full (the 1.4 "
        "catalogue) with compat_1x: true. Not in compat_1x (spec-2.0 §2.1): every "
        "instances[] row and connected carry role, editor "
        "(the default for a GUI Houdini) or worker (headless), as houdini_connect {role} set "
        "it; recent lists up to 5 Houdinis the bridge ledger remembers that are no longer "
        "running, most recently seen first, each {pid, label, ui, role, hip (its last hip "
        "file), started, last_seen, alive: false, name?}. The ledger survives a bridge restart. "
        "Defaults and empties are left out (2.0): role when it is the mode's default (editor "
        "for a GUI Houdini, worker headless), name when unset, and on instances[] rows "
        "selected: false, busy: false and jobs_running: 0; recent when no dead Houdini is "
        "remembered; connected.memory unless detail: true (so two reads of an unchanged "
        "session match, and houdini://status, shaped the same, keeps its etag)."
    ),
    input_schema=_obj({}),
    output_schema=_out(
        {
            "connected": {"anyOf": [_connected_block(), _t("null")]},
            "instances": {
                "type": "array",
                "items": _out(
                    {
                        "pid": _t("integer"),
                        "label": _t("string"),
                        "houdini": _t("string"),
                        "ui": _t("boolean"),
                        "hip": _t("string"),
                        "started": _t("string"),
                        "launched_by": _t(["integer", "null"]),
                    }
                ),
            },
            "bridge_version": _t("string"),
            "profile": {"type": "string", "enum": list(PROFILES_2X)},
            "read_only": _t("boolean"),
            "allow_python": _t("boolean"),
        },
        ("connected", "instances", "bridge_version"),
    ),
    read_only=True,
    bridge_local=True,
    examples=({},),
    v2_extra={
        "input": {"properties": {"detail": {"type": "boolean", "default": False}}},
        "output": {
            "properties": {
                "instances": {
                    "items": {"properties": {"role": {"type": "string", "enum": list(ROLES)}}}
                },
                "recent": {"type": "array", "items": {"type": "object"}},
            }
        },
    },
)
