"""Catalogue entry for ``houdini_status`` (BIBLE §4.2)."""

from __future__ import annotations

from ._helpers import PROFILES, ROLES, ToolSpec, _connected_block, _obj, _out, _t

SPEC = ToolSpec(
    name="houdini_status",
    profiles=("minimal", "core", "full"),
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
        "profile is minimal, core or full; a removed profile name in the config (compat_1x, "
        "v2) reads as full with a warning in warnings. (2.0, spec-2.0 §2.1) every "
        "instances[] row and connected carry role, editor "
        "(the default for a GUI Houdini) or worker (headless), as houdini_connect {role} set "
        "it; recent lists up to 5 Houdinis the bridge ledger remembers that are no longer "
        "running, most recently seen first, each {pid, label, ui, role, hip (its last hip "
        "file), started, last_seen, alive: false, name?}. The ledger survives a bridge restart. "
        "Defaults and empties are left out (2.0): role when it is the mode's default (editor "
        "for a GUI Houdini, worker headless), name when unset, and on instances[] rows "
        "selected: false, busy: false and jobs_running: 0; recent when no dead Houdini is "
        "remembered; connected.memory unless detail: true (so two reads of an unchanged "
        "session match, and houdini://status, shaped the same, keeps its etag). The hip "
        "path is printed once, as connected.hip.path: what only repeats it is left out "
        "(hip.name, a hip.recent entry equal to it, env.HIP when it is the path's folder, "
        "env.JOB when it is that folder too, env.HIPNAME, an empty env, and hip on the "
        "connected instance's row and on recent rows)."
    ),
    input_schema=_obj({"detail": {"type": "boolean", "default": False}}),
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
                        "role": {"type": "string", "enum": list(ROLES)},
                    }
                ),
            },
            "bridge_version": _t("string"),
            "profile": {"type": "string", "enum": list(PROFILES)},
            "read_only": _t("boolean"),
            "allow_python": _t("boolean"),
            "recent": {"type": "array", "items": {"type": "object"}},
        },
        ("connected", "instances", "bridge_version"),
    ),
    read_only=True,
    bridge_local=True,
    examples=({},),
)
