"""cook and problems against real Houdini (bible §4.6, §5.3, §7)."""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")


def _geo(name: str = "geo1"):
    return hou.node("/obj").createNode("geo", name)


def _slow_python_sop(parent, seconds: float, name: str = "slow"):
    node = parent.createNode("python", name)
    node.parm("python").set(f"import time\ntime.sleep({seconds})")
    return node


def _wait_job(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.ok("job", {"action": "status", "job_id": job_id})
        if status["state"] != "running":
            return status
        client.host.executor.pump_once(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


# -- cook --------------------------------------------------------------------------


def test_cook_ok_node(client):
    box = _geo().createNode("box")
    result = client.ok("cook", {"paths": [box.path()]})
    assert result["ok"] is True
    (row,) = result["results"]
    assert row["path"] == box.path()
    assert row["ok"] is True
    assert row["cook_state"] == "cooked"
    assert row["errors"] == [] and row["warnings"] == []
    assert isinstance(row["cook_time_ms"], float)
    assert "job_id" not in result


def test_cook_failure_is_reported_not_raised(client):
    geo = _geo()
    box = geo.createNode("box")
    wrangle = geo.createNode("attribwrangle", "bad")
    wrangle.setInput(0, box)
    wrangle.parm("snippet").set("@P.y = ;")
    result = client.ok("cook", {"paths": [box.path(), wrangle.path()], "force": True})
    assert result["ok"] is False
    ok_row, bad_row = result["results"]
    assert ok_row["ok"] is True
    assert bad_row["ok"] is False
    assert bad_row["cook_state"] == "error"
    assert any("Syntax error" in e for e in bad_row["errors"]), bad_row


def test_cook_broken_expression_reports_warning(client):
    box = _geo().createNode("box")
    box.parm("sizex").setExpression('ch("../nope/tx")')
    result = client.ok("cook", {"paths": [box.path()], "force": True})
    row = result["results"][0]
    assert any("Bad parameter reference" in w and "../nope/tx" in w for w in row["warnings"]), row


def test_cook_at_frame_restores_current_frame(client):
    geo = _geo()
    node = geo.createNode("python", "frame_probe")
    node.parm("python").set("hou.pwd().setCachedUserData('cooked_at', hou.frame())")
    hou.setFrame(3)
    result = client.ok("cook", {"paths": [node.path()], "force": True, "frame": 17})
    assert result["frame"] == 17
    assert result["results"][0]["ok"] is True
    assert node.cachedUserData("cooked_at") == 17
    assert hou.frame() == 3
    hou.setFrame(1)


def test_cook_errors(client):
    _geo().createNode("box", "box1")
    error = client.error("cook", {"paths": ["/obj/geo1/boxx1"]})
    assert error["code"] == "node_not_found"
    assert "/obj/geo1/box1" in error["candidates"]
    assert client.error("cook", {"paths": []})["code"] == "invalid_argument"
    assert client.error("cook", {"paths": ["/obj"], "timeout_s": 0})["code"] == "invalid_argument"
    assert client.error("cook", {"paths": ["obj/geo1"]})["code"] == "invalid_argument"


def test_cook_slow_but_within_threshold_is_synchronous(client):
    node = _slow_python_sop(_geo(), 0.4)
    result = client.ok("cook", {"paths": [node.path()], "force": True})
    assert "job_id" not in result
    assert result["results"][0]["cook_time_ms"] >= 350


def test_cook_becomes_job_after_timeout(client):
    node = _slow_python_sop(_geo(), 2.0)
    started = time.monotonic()
    result = client.ok("cook", {"paths": [node.path()], "force": True, "timeout_s": 0.5})
    assert result["state"] == "running"
    job_id = result["job_id"]
    assert job_id in result["message"]
    status = _wait_job(client, job_id)
    assert status["state"] == "done", status
    assert status["tool"] == "cook"
    final = client.ok("job", {"action": "result", "job_id": job_id})["result"]
    assert final["ok"] is True
    assert final["results"][0]["path"] == node.path()
    assert final["results"][0]["cook_time_ms"] >= 1900
    assert time.monotonic() - started >= 1.9
    assert any(j["job_id"] == job_id for j in client.ok("job", {"action": "list"})["jobs"])


def test_cook_becomes_job_after_job_threshold(client):
    geo = _geo()
    first = _slow_python_sop(geo, 0.6, "slow1")
    second = _slow_python_sop(geo, 0.6, "slow2")
    saved = client.host.config.job_threshold_s
    client.host.config.job_threshold_s = 0.3
    try:
        result = client.ok("cook", {"paths": [first.path(), second.path()], "force": True})
    finally:
        client.host.config.job_threshold_s = saved
    assert result["state"] == "running"
    status = _wait_job(client, result["job_id"])
    assert status["state"] == "done"
    assert status["progress"] == 1.0
    final = client.ok("job", {"action": "result", "job_id": result["job_id"]})["result"]
    assert [r["path"] for r in final["results"]] == [first.path(), second.path()]


# -- problems ------------------------------------------------------------------------


def _kinds(result: dict) -> list[tuple[str, str]]:
    return [(row["kind"], row["path"]) for row in result["problems"]]


def test_problems_clean_scene(client):
    box = _geo().createNode("box")
    box.setDisplayFlag(True)
    result = client.ok("problems", {"root": "/obj", "cook_uncooked": True})
    assert result["problems"] == []
    assert result["total"] == 0
    assert result["nodes_scanned"] == 3  # /obj, geo1, box1
    assert result["cooked"] == 1
    assert "No problems" in result["message"]


def test_problems_broken_expression(client):
    box = _geo().createNode("box")
    box.parm("sizex").setExpression('ch("../nope/tx")')
    result = client.ok("problems", {"root": "/obj/geo1", "cook_uncooked": True})
    refs = [r for r in result["problems"] if r["kind"] == "broken_reference"]
    assert len(refs) == 1
    ref = refs[0]
    assert ref["path"] == box.path() and ref["parm"] == "sizex" and ref["ref"] == "../nope/tx"
    assert box.path() + "/sizex" in ref["message"]
    warnings = [r for r in result["problems"] if r["kind"] == "warning"]
    assert any("Bad parameter reference" in w["message"] for w in warnings)
    no_warn = client.ok("problems", {"root": "/obj/geo1", "include_warnings": False})
    assert all(r["kind"] != "warning" for r in no_warn["problems"])


def test_problems_broken_python_and_node_references(client):
    geo = _geo()
    box = geo.createNode("box")
    box.parm("sizey").setExpression('hou.parm("../gone/ty").eval()', hou.exprLanguage.Python)
    box.parm("sizez").setExpression('ch("../box1/sizex")')  # valid: must not be reported
    merge = geo.createNode("object_merge")
    merge.parm("objpath1").set("/obj/nope/OUT")
    result = client.ok("problems", {"root": "/obj/geo1"})
    refs = {
        (r["path"], r["parm"]): r for r in result["problems"] if r["kind"] == "broken_reference"
    }
    assert set(refs) == {(box.path(), "sizey"), (merge.path(), "objpath1")}
    assert refs[(merge.path(), "objpath1")]["ref"] == "/obj/nope/OUT"


def test_problems_missing_file(client, work_dir):
    geo = _geo()
    missing = geo.createNode("file", "missing")
    missing.parm("file").set("$HIP/nope/missing.bgeo.sc")
    present = geo.createNode("file", "present")
    path = work_dir / "here.bgeo.sc"
    hou.node(geo.path()).createNode("box", "src").geometry().saveToFile(str(path))
    present.parm("file").set(str(path).replace("\\", "/"))
    sequence = geo.createNode("file", "sequence")
    sequence.parm("file").set("$HIP/nope/seq.$F4.bgeo.sc")
    result = client.ok("problems", {"root": geo.path()})
    files = [r for r in result["problems"] if r["kind"] == "missing_file"]
    assert [r["path"] for r in files] == [missing.path()]
    row = files[0]
    assert row["parm"] == "file"
    assert row["file"].endswith("nope/missing.bgeo.sc")
    assert "$HIP/nope/missing.bgeo.sc" in row["message"]
    # Uncooked: no node errors yet; cooking first adds the File SOP's own error.
    assert not [r for r in result["problems"] if r["kind"] == "error"]
    cooked = client.ok("problems", {"root": geo.path(), "cook_uncooked": True})
    errors = [r for r in cooked["problems"] if r["kind"] == "error"]
    assert errors and errors[0]["path"] == missing.path()
    assert "Unable to read file" in errors[0]["message"]
    assert cooked["problems"][0]["kind"] == "error"  # errors sort first


def test_problems_unconnected_required_input(client):
    geo = _geo()
    xform = geo.createNode("xform")
    copy = geo.createNode("copytopoints")
    copy.setInput(0, geo.createNode("sphere"))
    result = client.ok("problems", {"root": geo.path()})
    rows = [r for r in result["problems"] if r["kind"] == "unconnected_input"]
    assert {(r["path"], r["input"]) for r in rows} == {(xform.path(), 0), (copy.path(), 1)}
    copy_row = next(r for r in rows if r["path"] == copy.path())
    assert copy_row["label"] == "Target Points to Copy to"
    assert "input 1" in copy_row["message"] and copy.path() in copy_row["message"]


def test_problems_paging(client):
    geo = _geo()
    for i in range(5):
        geo.createNode("xform", f"x{i}")
    first = client.ok("problems", {"root": geo.path(), "limit": 2})
    assert first["total"] == 5 and len(first["problems"]) == 2
    assert first["next_cursor"] == "2"
    assert first["counts"] == {"unconnected_input": 5}
    second = client.ok("problems", {"root": geo.path(), "limit": 2, "cursor": "4"})
    assert len(second["problems"]) == 1 and "next_cursor" not in second
    paths = [r["path"] for r in first["problems"]]
    assert paths == [f"{geo.path()}/x0", f"{geo.path()}/x1"]
    error = client.error("problems", {"root": geo.path(), "cursor": "nope"})
    assert error["code"] == "invalid_argument"


def test_problems_locked_hda_is_opaque(client):
    geo = _geo()
    geo.createNode("attribnoise::2.0")
    opaque = client.ok("problems", {"root": "/obj"})
    deep = client.ok("problems", {"root": "/obj", "recurse_locked": True})
    assert opaque["nodes_scanned"] == 3  # /obj, geo1, the HDA node
    assert deep["nodes_scanned"] > 10


def test_problems_root_errors(client):
    assert client.error("problems", {"root": "/obj/none"})["code"] == "node_not_found"
    assert client.error("problems", {"limit": 0})["code"] == "invalid_argument"


# -- stale errors after the cause is fixed (review 07, papercut 1) -------------------


def _terrain_chain(client):
    """The evaluator's chain: box1 -> mountain -> scatter; sphere + scatter -> copy1."""
    result = client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "terrain"},
                {"parent": "/obj/terrain", "type": "box", "name": "box1"},
                {
                    "parent": "/obj/terrain",
                    "type": "mountain",
                    "name": "mountain1",
                    "inputs": [{"index": 0, "from": "/obj/terrain/box1"}],
                },
                {
                    "parent": "/obj/terrain",
                    "type": "scatter",
                    "name": "scatter1",
                    "parms": {"npts": 50},
                    "inputs": [{"index": 0, "from": "/obj/terrain/mountain1"}],
                },
                {"parent": "/obj/terrain", "type": "sphere", "name": "sphere1"},
                {
                    "parent": "/obj/terrain",
                    "type": "copytopoints",
                    "name": "copy1",
                    "inputs": [
                        {"index": 0, "from": "/obj/terrain/sphere1"},
                        {"index": 1, "from": "/obj/terrain/scatter1"},
                    ],
                    "flags": {"display": True},
                },
            ]
        },
    )
    assert all(not r["errors"] for r in result["results"]), result
    return "/obj/terrain"


def _problem_keys(result):
    return [(r["path"], r["kind"], r["message"]) for r in result["problems"]]


@pytest.mark.parametrize(
    "fix",
    [
        {"revert_to_default": True},
        {"value": 2.0},
    ],
    ids=["revert_to_default", "value"],
)
def test_fixing_an_expression_clears_errors_downstream(client, fix):
    root = _terrain_chain(client)
    sizex = f"{root}/box1/sizex"
    broken = client.ok("parm_set", {"items": [{"path": sizex, "expression": "$F*("}]})
    assert broken["results"][0]["errors"], broken
    failed = client.ok("cook", {"paths": [f"{root}/copy1"]})
    assert failed["ok"] is False
    before = client.ok("problems", {"root": root})
    keys = _problem_keys(before)
    assert len(keys) == len(set(keys)), keys  # no duplicate rows

    fixed = client.ok("parm_set", {"items": [{"path": sizex, **fix}]})
    row = fixed["results"][0]
    assert row["errors"] == [], row
    assert row["cook_state"] == "cooked"

    cooked = client.ok("cook", {"paths": [f"{root}/copy1"]})
    assert cooked["ok"] is True, cooked
    assert cooked["results"][0]["errors"] == []
    after = client.ok("problems", {"root": root})
    assert after["total"] == 0, after["problems"]


def test_cook_clears_errors_left_by_an_outside_fix(client):
    """A fix made outside HocusPocus (GUI, houdini_python) followed by a plain cook of the
    broken node itself: Houdini keeps the old error on it and fails every downstream cook
    until the node is cooked again. A non-forced ``cook`` downstream must still be right."""
    root = _terrain_chain(client)
    box = hou.node(f"{root}/box1")
    copy1 = hou.node(f"{root}/copy1")
    parm = box.parm("sizex")
    parm.setExpression("$F*(")
    with pytest.raises(hou.OperationFailed):
        copy1.cook()
    parm.deleteAllKeyframes()
    parm.revertToDefaults()
    box.cook()  # succeeds, yet Houdini still reports the bracing error on box1
    assert box.errors()
    cooked = client.ok("cook", {"paths": [copy1.path()]})
    assert cooked["ok"] is True, cooked
    assert client.ok("cook", {"paths": [box.path()]})["results"][0]["errors"] == []
    assert client.ok("problems", {"root": root})["total"] == 0


def test_problems_rechecks_errored_nodes_changed_since_their_cook(client):
    root = _terrain_chain(client)
    sizex = f"{root}/box1/sizex"
    client.ok("parm_set", {"items": [{"path": sizex, "expression": "$F*("}]})
    assert client.ok("cook", {"paths": [f"{root}/copy1"]})["ok"] is False
    broken = client.ok("problems", {"root": root})
    assert {r["path"] for r in broken["problems"] if r["kind"] == "error"} >= {
        f"{root}/box1",
        f"{root}/copy1",
    }
    client.ok("parm_set", {"items": [{"path": sizex, "revert_to_default": True}]})
    # Downstream nodes still hold "Invalid source" from the old cook; problems rechecks them.
    after = client.ok("problems", {"root": root})
    assert after["total"] == 0, after["problems"]
    assert after["cooked"] >= 1


def test_slow_node_with_old_errors_gets_a_force_hint(client):
    from hocuspocus.host.tools import _diag

    geo = _geo()
    box = geo.createNode("box")
    box.parm("sizex").setExpression("$F*(")
    client.ok("cook", {"paths": [box.path()]})
    box.parm("sizex").deleteAllKeyframes()
    box.parm("sizex").set(2.0)
    box.cook()  # Houdini keeps the old error (bible §5.18)
    _diag._last_cook_ms[box.sessionId()] = _diag.SLOW_COOK_MS + 1
    try:
        row = client.ok("cook", {"paths": [box.path()]})["results"][0]
        assert row["errors"] and "force: true" in row["hint"], row
        forced = client.ok("cook", {"paths": [box.path()], "force": True})["results"][0]
        assert forced["errors"] == [] and "hint" not in forced, forced
    finally:
        _diag._last_cook_ms.pop(box.sessionId(), None)
