"""Catalogue entry for ``houdini_connect`` (BIBLE §4.2)."""

from __future__ import annotations

from ._helpers import ROLES, ToolSpec, _b, _enum, _i, _n, _obj, _s

SPEC = ToolSpec(
    name="houdini_connect",
    profiles=("minimal", "core", "full"),
    description=(
        "Choose the Houdini this session drives: pid attaches, launch starts one (gui or "
        "headless, optional hip), disconnect drops the selection, quit closes it. A launched "
        "Houdini usually closes with this server "
        "(launched.outlives_server says); `hocuspocus launch` starts one that outlives it."
    ),
    notes=(
        "pid (or launch) pins that Houdini: the pin holds until the next houdini_connect, and "
        "if it exits every call returns instance_lost rather than switching. {} unpins "
        "(automatic selection). name labels the Houdini given by pid or launch, shown in "
        "houdini_status and in _meta.instance; {name} alone pins the Houdini with that name. "
        "A pid that is not running is houdini_offline with the live candidates. "
        "An attach or launch returns connected, shaped as houdini_status's (memory only "
        "there, with detail: true); a launch adds launched {pid, outlives_server, note, log}. "
        "launch waits up to wait_s seconds for the new host to register. A launched Houdini "
        "starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled "
        "scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: "
        "with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save "
        "saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets "
        "the registry entry. To keep one alive across sessions, start it with `hocuspocus "
        "launch` and attach by pid. "
        "(2.0, spec-2.0 §2.1) role (editor or worker) sets the role of the Houdini "
        "given by pid, name or launch (default: editor for a GUI Houdini, worker for a "
        "headless one), kept in the bridge ledger across bridge restarts. {role} alone pins "
        "the least busy live Houdini with that role (fewest jobs_running, then not busy, then"
        " GUI first and newest first); none is houdini_offline with the candidates and their "
        "roles. cook, render, job and look take on: pid, name or role to run one call on "
        "another Houdini without moving the pin."
    ),
    input_schema=_obj(
        {
            "pid": _i("Live instance to attach to."),
            "launch": _obj(
                {
                    "mode": _enum(("gui", "headless")),
                    "hip": _s("Hip file to open."),
                    "wait_s": _n(None, minimum=1, default=90),
                },
                ("mode",),
            ),
            "name": _s(),
            "disconnect": _b(False),
            "quit": _b(False),
            "on_unsaved": _enum(("fail", "save", "discard")),
            "role": _enum(ROLES),
        }
    ),
    bridge_local=True,
    examples=(
        {"pid": 12345, "name": "worker"},
        {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}},
        {"quit": True, "on_unsaved": "save"},
    ),
)
