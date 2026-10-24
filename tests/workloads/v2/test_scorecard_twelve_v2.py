"""Review 21's scorecard twelve on the 2.0 tools (1.4's budget: ``../budgets.json``).

The same twelve tasks and outcomes. Builds are ``edit`` transactions (task 2's chain and
its layout in one), the build's echo reports the cook (no separate ``cook``), reads are
``inspect``/``search``, the look is ``look``, the deliberate mistakes are ``edit`` ops. Task 8 reads the scene
outline as a resource after the look (no ROP left behind); task 9 revalidates it with its
etag after the refused edits, and ``not_modified`` (no bytes) proves they changed nothing.
Task 12 launches a headless Houdini as a ``worker`` (``houdini_connect {launch, role}``),
kills it, and addresses it with ``cook {on: <pid>}`` (``instance_lost``) before
relaunching; the session host is pinned again afterwards (not recorded).
"""

from __future__ import annotations

import os
import signal
import time

import pytest

pytestmark = pytest.mark.timeout(420)

GEO = "/obj/terrain"
SCENE = "houdini://outline?root=/&depth=2"


def test_scorecard_twelve(workload, wl_host):
    rec = workload

    # -- 0. host up -----------------------------------------------------------------------
    status = rec.ok("houdini_status")
    assert status["connected"]["pid"] == wl_host.pid

    # -- 1. discover ----------------------------------------------------------------------
    roots = rec.ok("search", {"kind": "nodes", "root": "/"})
    assert {"/obj", "/out", "/stage"} <= {row["path"] for row in roots["nodes"]}, roots.data

    # -- 2. build geo -> box -> mountain -> subdivide -> OUT, laid out: one edit ----------
    built = rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
                {"op": "create", "id": "box", "parent": "$geo", "type": "box"},
                {"op": "create", "id": "mtn", "parent": "$geo", "type": "mountain",
                 "name": "mountain1", "inputs": [{"index": 0, "from": "$box"}],
                 "parms": {"height": 0.5, "offsetx": {"expression": "$F*0.1"}}},
                {"op": "create", "id": "sub", "parent": "$geo", "type": "subdivide",
                 "inputs": [{"index": 0, "from": "$mtn"}]},
                {"op": "create", "id": "out", "parent": "$geo", "type": "null", "name": "OUT",
                 "inputs": [{"index": 0, "from": "$sub"}],
                 "flags": {"display": True, "render": True}},
                {"op": "layout", "parent": "$geo"},
            ]
        },
    )  # fmt: skip
    ids = built["ids"]
    assert ids["out"] == f"{GEO}/OUT" and ids["box"] == f"{GEO}/box1", built.data
    # The echo cooked every touched node once: OUT cooked clean (1.4: a separate cook);
    # a clean cooked row carries no errors and no cook_state.
    out_row = next(n for n in built["nodes"] if n["path"] == f"{GEO}/OUT")
    assert "errors" not in out_row and "cook_state" not in out_row, out_row

    # -- 3. read back ---------------------------------------------------------------------
    info = rec.ok("inspect", {"what": "node", "paths": [f"{GEO}/mountain1", f"{GEO}/OUT"]})
    mountain, out = info["nodes"]
    assert mountain["parms"]["height"] == pytest.approx(0.5)  # compact: {name: value}
    assert "errors" not in mountain and "display" in out["flags"]  # no empty errors
    parms = rec.ok(
        "inspect",
        {"what": "parms", "paths": [f"{GEO}/mountain1/offset", f"{GEO}/mountain1/height"]},
    )
    assert isinstance(parms["parms"][f"{GEO}/mountain1/offset"]["value"], list), parms.data
    geo = rec.ok("inspect", {"what": "geo", "target": f"{GEO}/OUT"})
    assert geo["point_count"] > 0 and geo["prim_count"] > 0
    rows = rec.ok(
        "inspect", {"what": "geo", "target": f"{GEO}/OUT", "rows": True, "attribs": ["P"],
                    "count": 5}
    )  # fmt: skip
    assert len(rows["rows"]) == 5 and rows.get("next_cursor")
    described = rec.ok("inspect", {"what": "network", "target": GEO})
    assert "mountain1" in str(described.data)

    # -- 4. frame 24: the expression reads 2.4 ------------------------------------------
    assert rec.ok("time", {"frame": 24})["frame"] == 24
    offsetx_path = f"{GEO}/mountain1/offsetx"
    offsetx = rec.ok("inspect", {"what": "parms", "target": offsetx_path})["parms"][offsetx_path]
    assert offsetx["value"] == 2.4 and offsetx["expression"] == "$F*0.1", offsetx
    later = rec.ok("inspect", {"what": "parms", "target": offsetx_path, "frame": 48})["parms"]
    assert later[offsetx_path]["value"] == 4.8, later
    rec.ok("time", {"frame": 1})

    # -- 5. save and dirty ----------------------------------------------------------------
    hip = rec.path("friction.hip")
    saved = rec.ok("hip_save", {"path": hip})
    assert saved["dirty"] is False and saved["path"] == hip
    changed = rec.ok(
        "edit", {"ops": [{"op": "set", "path": f"{GEO}/mountain1/height", "value": 0.7}]}
    )
    assert [n["path"] for n in changed["nodes"]] == [f"{GEO}/mountain1"], changed.data
    assert not changed["nodes"][0].get("errors"), changed.data
    assert rec.ok("hip_save", {})["dirty"] is False
    after = rec.ok("houdini_status")["connected"]["hip"]
    assert after["dirty"] is False and after["path"] == hip, after

    # -- 6. scatter + copy spheres --------------------------------------------------------
    scatter = rec.ok("search", {"kind": "types", "query": "scatter", "category": "Sop", "limit": 5})
    assert scatter["results"][0]["name"].split("::")[0] == "scatter", scatter.data
    copy = rec.ok(
        "search", {"kind": "types", "query": "copy to points", "category": "Sop", "limit": 5}
    )
    assert copy["results"][0]["name"].split("::")[0] == "copytopoints", copy.data
    rec.ok("inspect", {"what": "type", "target": "Sop/scatter", "parms": "*count*|npts"})
    rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "pts", "parent": GEO, "type": "scatter",
                 "inputs": [{"index": 0, "from": f"{GEO}/OUT"}], "parms": {"npts": 200}},
                {"op": "create", "id": "dot", "parent": GEO, "type": "sphere",
                 "parms": {"scale": 0.05}},
                {"op": "create", "parent": GEO, "type": "copytopoints", "name": "copy1",
                 "inputs": [{"index": 0, "from": "$dot"}, {"index": 1, "from": "$pts"}],
                 "flags": {"display": True, "render": True}},
            ]
        },
    )  # fmt: skip
    copied = rec.ok("inspect", {"what": "geo", "target": f"{GEO}/copy1"})
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
    junk = rec.ok("search", {"kind": "nodes", "root": "/obj", "pattern": "pyjunk*"})
    assert junk["nodes"] == [], junk.data
    history = rec.ok("undo", {"action": "history"})
    assert not any("pyjunk" in label for label in history.get("redo", [])), history.data

    # -- 8. render a Flipbook ROP, and look -----------------------------------------------
    rec.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "parent": "/obj", "type": "cam", "name": "cam1",
                 "parms": {"t": [0, 1.5, 6], "resx": 320, "resy": 240}},
                {"op": "create", "parent": "/out", "type": "flipbook", "name": "fb",
                 "parms": {"camera": "/obj/cam1", "res": [320, 240],
                           "picture": rec.path("render", "fb.$F4.png")}},
            ]
        },
    )  # fmt: skip
    rendered = rec.ok("render", {"rop_path": "/out/fb", "frames": [1, 3]}, timeout=180)
    assert rendered["state"] == "done", rendered.data
    assert len(rendered["outputs"]) == 3 and rendered.images == 1, rendered.data
    look = rec.ok("look", {"resolution": [512, 384]}, timeout=180)
    assert look.images == 1 and look["width"] == 512
    # The scene's top two levels as a resource: /out holds only fb (the look left no ROP).
    scene, _meta = rec.read(SCENE)
    out = next(row for row in scene["nodes"] if row["path"] == "/out")
    assert [row["path"] for row in out.get("children", [])] == ["/out/fb"], out

    # -- 9. deliberate mistakes: each an isError with a code and candidates ---------------
    bad_type = rec.error(
        "edit",
        {"ops": [{"op": "create", "parent": GEO, "type": "mountian"}]},
        code="node_type_not_found",
    )
    assert bad_type["candidates"][0].split("::")[0] == "mountain", bad_type.data
    bad_parm = rec.error(
        "edit",
        {"ops": [{"op": "set", "path": f"{GEO}/box1/sizee", "value": 2}]},
        code="parm_not_found",
    )
    assert any("size" in c for c in bad_parm["candidates"]), bad_parm.data
    bad_input = rec.error(
        "edit",
        {"ops": [{"op": "connect", "from": f"{GEO}/box1", "to": f"{GEO}/OUT", "to_input": 7}]},
        code="invalid_input",
    )
    assert "Input 1" in bad_input.get("hint", ""), bad_input.data
    # Revalidated with the etag: not modified, no bytes. The refused edits changed nothing.
    unchanged, meta = rec.read(SCENE)
    assert unchanged is None and meta.get("not_modified") is True, meta

    # -- 10. the guide --------------------------------------------------------------------
    guide, _meta = rec.read("hocuspocus://guide")
    assert "`edit`" in guide, guide[:500]

    # -- 11. hip_new protects unsaved work ------------------------------------------------
    rec.error("hip_new", {}, code="unsaved_changes")
    assert rec.ok("hip_new", {"on_unsaved": "save"})["saved_first"] is True
    rec.ok("edit", {"ops": [{"op": "create", "parent": "/obj", "type": "geo",
                             "name": "scratchgeo"}]})  # fmt: skip
    refused = rec.error("hip_new", {}, code="unsaved_changes")
    assert "discard" in refused.get("hint", ""), refused.data
    rec.error("hip_new", {"on_unsaved": "save"}, code="unsaved_changes")  # untitled
    rec.ok("hip_new", {"on_unsaved": "discard"})
    assert rec.ok("search", {"kind": "nodes", "root": "/obj"})["nodes"] == []

    # -- 12. a worker: launch, kill, address it, relaunch ---------------------------------
    launch = {"launch": {"mode": "headless", "hip": hip, "wait_s": 150}, "role": "worker"}
    first = rec.ok("houdini_connect", launch, timeout=200)
    pid = first["launched"]["pid"]
    assert pid != wl_host.pid
    os.kill(pid, signal.SIGTERM)  # the hython this workload launched
    from hocuspocus.bridge.instances import pid_alive

    deadline = time.monotonic() + 20
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    lost = rec.error("cook", {"paths": [f"{GEO}/copy1"], "on": pid}, code="instance_lost")
    assert f"pid {pid}" in lost["message"] and lost["retryable"] is False, lost.data
    assert rec.ok("houdini_status")["connected"] is None
    second = rec.ok("houdini_connect", launch, timeout=200)
    assert second["launched"]["pid"] not in (pid, wl_host.pid)
    reopened = rec.ok("inspect", {"what": "geo", "target": f"{GEO}/copy1"})
    assert reopened["point_count"] > 0 and reopened["prim_types"] == {"sphere": 200}
    assert rec.ok("houdini_connect", {"quit": True, "on_unsaved": "discard"})["exited"] is True

    rec.finish()
