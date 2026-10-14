"""Review 21 (scorecard re-run on 1.3) as a workload: the twelve tasks of review 07.

0 host up, 1 discover, 2 build a chain, 3 read it back, 4 frame 24, 5 save and dirty,
6 scatter and copy, 7 Python, 8 look and render, 9 deliberate mistakes, 10 the guide,
11 ``hip_new`` with unsaved changes, 12 kill a Houdini and relaunch it. The assertions are
the outcomes review 21 verified. Task 12 launches its own headless Houdinis through the
bridge (the session host is never killed) and pins the session host again afterwards.
"""

from __future__ import annotations

import os
import signal
import time

import pytest

pytestmark = pytest.mark.timeout(420)

GEO = "/obj/terrain"


def _parm(block: dict, name: str) -> dict:
    return next(row for row in block["parms"] if row["name"] == name)


def test_scorecard_twelve(workload, wl_host):
    rec = workload

    # -- 0. host up -----------------------------------------------------------------------
    status = rec.ok("houdini_status")
    assert status["connected"]["pid"] == wl_host.pid and status["profile"] == "full"

    # -- 1. discover ----------------------------------------------------------------------
    roots = rec.ok("node_find", {"root": "/"})
    assert {"/obj", "/out", "/stage"} <= {row["path"] for row in roots["nodes"]}, roots.data

    # -- 2. build geo -> box -> mountain -> subdivide -> OUT in one call ------------------
    built = rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "terrain"},
                {"parent": GEO, "type": "box"},
                {
                    "parent": GEO,
                    "type": "mountain",
                    "name": "mountain1",
                    "inputs": [{"index": 0, "from": f"{GEO}/box1"}],
                    "parms": {"height": 0.5, "offsetx": {"expression": "$F*0.1"}},
                },
                {
                    "parent": GEO,
                    "type": "subdivide",
                    "inputs": [{"index": 0, "from": f"{GEO}/mountain1"}],
                },
                {
                    "parent": GEO,
                    "type": "null",
                    "name": "OUT",
                    "inputs": [{"index": 0, "from": f"{GEO}/subdivide1"}],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    assert [r["path"] for r in built["results"]][-1] == f"{GEO}/OUT"
    assert built["dirty"] is True
    rec.ok("node_layout", {"parent": GEO})

    # -- 3. read back ---------------------------------------------------------------------
    info = rec.ok("node_info", {"paths": [f"{GEO}/mountain1", f"{GEO}/OUT"]})
    mountain, out = info["nodes"]
    assert _parm(mountain, "height")["value"] == pytest.approx(0.5)
    assert mountain["errors"] == [] and out["flags"]["display"] is True
    parms = rec.ok("parm_get", {"paths": [f"{GEO}/mountain1/offset", f"{GEO}/mountain1/height"]})
    assert parms["parms"][0]["kind"] == "tuple", parms.data
    assert rec.ok("cook", {"paths": [f"{GEO}/OUT"]})["ok"] is True
    geo = rec.ok("geo_info", {"path": f"{GEO}/OUT"})
    assert geo["point_count"] > 0 and geo["prim_count"] > 0
    rows = rec.ok("geo_read", {"path": f"{GEO}/OUT", "attribs": ["P"], "count": 5})
    assert len(rows["rows"]) == 5 and rows.get("next_cursor")
    described = rec.ok("network_describe", {"root": GEO})
    assert "mountain1" in str(described.data)

    # -- 4. frame 24: the expression reads 2.4 ------------------------------------------
    assert rec.ok("time", {"frame": 24})["frame"] == 24
    (offsetx,) = rec.ok("parm_get", {"paths": [f"{GEO}/mountain1/offsetx"]})["parms"]
    assert offsetx["value"] == 2.4 and offsetx["raw"] == "$F*0.1", offsetx
    (later,) = rec.ok("parm_get", {"paths": [f"{GEO}/mountain1/offsetx"], "frame": 48})["parms"]
    assert later["value"] == 4.8, later
    rec.ok("time", {"frame": 1})

    # -- 5. save and dirty ----------------------------------------------------------------
    hip = rec.path("friction.hip")
    saved = rec.ok("hip_save", {"path": hip})
    assert saved["dirty"] is False and saved["path"] == hip
    changed = rec.ok("parm_set", {"items": [{"path": f"{GEO}/mountain1/height", "value": 0.7}]})
    assert changed["dirty"] is True
    assert rec.ok("hip_save", {})["dirty"] is False
    after = rec.ok("houdini_status")["connected"]["hip"]
    assert after["dirty"] is False and after["path"] == hip, after

    # -- 6. scatter + copy spheres --------------------------------------------------------
    scatter = rec.ok("node_type_search", {"query": "scatter", "category": "Sop", "limit": 5})
    assert scatter["results"][0]["name"].split("::")[0] == "scatter", scatter.data
    copy = rec.ok("node_type_search", {"query": "copy to points", "category": "Sop", "limit": 5})
    assert copy["results"][0]["name"].split("::")[0] == "copytopoints", copy.data
    rec.ok("node_type_info", {"type": "Sop/scatter", "parms": "*count*|npts"})
    rec.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": GEO,
                    "type": "scatter",
                    "inputs": [{"index": 0, "from": f"{GEO}/OUT"}],
                    "parms": {"npts": 200},
                },
                {"parent": GEO, "type": "sphere", "parms": {"scale": 0.05}},
                {
                    "parent": GEO,
                    "type": "copytopoints",
                    "name": "copy1",
                    "inputs": [
                        {"index": 0, "from": f"{GEO}/sphere1"},
                        {"index": 1, "from": f"{GEO}/scatter1"},
                    ],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    copied = rec.ok("geo_info", {"path": f"{GEO}/copy1"})
    assert copied["prim_types"] == {"sphere": 200}, copied.data

    # -- 7. Python, and an exception that rolls back --------------------------------------
    ran = rec.ok("houdini_python", {"code": f"len(hou.node('{GEO}/copy1').geometry().points())"})
    assert ran["result"] == 200, ran.data
    rec.ok("houdini_python", {"code": "opls /obj/terrain", "language": "hscript"})
    boom = rec.error(
        "houdini_python",
        {"code": "hou.node('/obj').createNode('geo', 'pyjunk')\n1/0"},
        code="python_exception",
    )
    assert "ZeroDivisionError" in boom["message"]
    junk = rec.ok("node_find", {"root": "/obj", "pattern": "pyjunk*"})
    assert junk["nodes"] == [], junk.data
    history = rec.ok("undo", {"action": "history"})
    assert not any("pyjunk" in label for label in history.get("redo", [])), history.data

    # -- 8. look, and render a Flipbook ROP -----------------------------------------------
    look = rec.ok("viewport_capture", {"resolution": [512, 384]}, timeout=180)
    assert look.images == 1 and look["width"] == 512
    assert rec.ok("node_find", {"root": "/out"})["nodes"] == []  # a capture leaves no ROP
    rec.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "cam", "name": "cam1",
                 "parms": {"t": [0, 1.5, 6], "resx": 320, "resy": 240}},
                {"parent": "/out", "type": "flipbook", "name": "fb",
                 "parms": {"camera": "/obj/cam1", "res": [320, 240],
                           "picture": rec.path("render", "fb.$F4.png")}},
            ]
        },
    )  # fmt: skip
    rendered = rec.ok("render", {"rop_path": "/out/fb", "frames": [1, 3]}, timeout=180)
    assert rendered["state"] == "done", rendered.data
    assert len(rendered["outputs"]) == 3 and rendered.images == 1, rendered.data

    # -- 9. deliberate mistakes: each an isError with a code and candidates ---------------
    bad_type = rec.error(
        "node_create", {"items": [{"parent": GEO, "type": "mountian"}]}, code="node_type_not_found"
    )
    assert bad_type["candidates"][0].split("::")[0] == "mountain", bad_type.data
    bad_parm = rec.error(
        "parm_set", {"items": [{"path": f"{GEO}/box1/sizee", "value": 2}]}, code="parm_not_found"
    )
    assert any("size" in c for c in bad_parm["candidates"]), bad_parm.data
    bad_input = rec.error(
        "node_connect",
        {"items": [{"from": f"{GEO}/box1", "to": f"{GEO}/OUT", "to_input": 7}]},
        code="invalid_input",
    )
    assert "Input 1" in bad_input.get("hint", ""), bad_input.data

    # -- 10. the guide --------------------------------------------------------------------
    guide = rec.read_resource("hocuspocus://guide")
    assert "node_create" in guide

    # -- 11. hip_new protects unsaved work ------------------------------------------------
    rec.error("hip_new", {}, code="unsaved_changes")
    assert rec.ok("hip_new", {"on_unsaved": "save"})["saved_first"] is True
    rec.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "scratchgeo"}]})
    refused = rec.error("hip_new", {}, code="unsaved_changes")
    assert "discard" in refused.get("hint", ""), refused.data
    rec.error("hip_new", {"on_unsaved": "save"}, code="unsaved_changes")  # untitled
    rec.ok("hip_new", {"on_unsaved": "discard"})
    assert rec.ok("node_find", {"root": "/obj"})["nodes"] == []

    # -- 12. kill a Houdini, call, relaunch -----------------------------------------------
    launch = {"launch": {"mode": "headless", "hip": hip, "wait_s": 150}}
    first = rec.ok("houdini_connect", launch, timeout=200)
    pid = first["launched"]["pid"]
    assert pid != wl_host.pid
    os.kill(pid, signal.SIGTERM)  # the hython this workload launched
    from hocuspocus.bridge.instances import pid_alive

    deadline = time.monotonic() + 20
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    lost = rec.error("node_find", {"root": "/obj"}, code="instance_lost")
    assert f"pid {pid}" in lost["message"] and lost["retryable"] is False, lost.data
    assert rec.ok("houdini_status")["connected"] is None
    second = rec.ok("houdini_connect", launch, timeout=200)
    assert second["launched"]["pid"] not in (pid, wl_host.pid)
    reopened = rec.ok("geo_info", {"path": f"{GEO}/copy1"})
    assert reopened["point_count"] > 0 and reopened["prim_types"] == {"sphere": 200}
    assert rec.ok("houdini_connect", {"quit": True, "on_unsaved": "discard"})["exited"] is True

    rec.finish()
