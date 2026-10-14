"""Catalogue entry for ``houdini_connect`` (BIBLE §4.2)."""

from __future__ import annotations

from ._helpers import ToolSpec, _b, _enum, _i, _n, _obj, _s

SPEC = ToolSpec(
    name="houdini_connect",
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
        "launch waits up to wait_s seconds for the new host to register. A launched Houdini "
        "starts in HOCUSPOCUS_WORK_DIR (default: the home directory), which is the untitled "
        "scene's $HIP and $JOB. quit closes the selected Houdini (or pid) through its host: "
        "with unsaved changes on_unsaved fail (default) refuses with unsaved_changes, save "
        "saves first, discard drops them. It returns {quit, pid, exited, saved?} and forgets "
        "the registry entry. To keep one alive across sessions, start it with `hocuspocus "
        "launch` and attach by pid."
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
        }
    ),
    bridge_local=True,
    examples=(
        {"pid": 12345, "name": "worker"},
        {"launch": {"mode": "headless", "hip": "C:/work/shot.hip"}},
        {"quit": True, "on_unsaved": "save"},
    ),
)
