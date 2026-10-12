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


# -- cook profile (review 11 B7) ----------------------------------------------------


def _chain(geo, slow_s: float = 0.15):
    box = geo.createNode("box")
    slow = _slow_python_sop(geo, slow_s)
    slow.setInput(0, box)
    sub = geo.createNode("subdivide")
    sub.setInput(0, slow)
    out = geo.createNode("null", "OUT")
    out.setInput(0, sub)
    return box, slow, sub, out


def test_cook_warm_cache_hint_points_at_profile(client):
    _box, _slow, _sub, out = _chain(_geo(), 0.05)
    out.cook(force=True)  # upstream now cached, as after node_create
    row = client.ok("cook", {"paths": [out.path()], "force": True})["results"][0]
    assert row["cook_time_ms"] < 1, row
    assert "profile: true" in row["hint"], row


def test_cook_profile_times_the_input_chain(client):
    box, slow, sub, out = _chain(_geo())
    out.cook(force=True)  # a warm cache must not hide the slow node
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    assert result["ok"] is True
    assert result["chain_total"] == 4
    chain = result["chain"]
    assert {row["path"] for row in chain} == {box.path(), slow.path(), sub.path(), out.path()}
    assert chain[0]["path"] == slow.path(), chain
    assert chain[0]["type"] == "python"
    assert chain[0]["cook_time_ms"] >= 140
    times = [row["cook_time_ms"] for row in chain]
    assert times == sorted(times, reverse=True)
    assert result["total_ms"] >= chain[0]["cook_time_ms"]
    assert result["results"][0]["path"] == out.path()
    assert "hint" not in result["results"][0]


def test_cook_profile_caps_the_chain_at_ten(client):
    geo = _geo()
    node = geo.createNode("box")
    for _ in range(12):
        nxt = geo.createNode("null")
        nxt.setInput(0, node)
        node = nxt
    result = client.ok("cook", {"paths": [node.path()], "profile": True})
    assert result["chain_total"] == 13
    assert len(result["chain"]) == 10


def test_cook_profile_as_a_job_reports_progress(client):
    _box, slow, _sub, out = _chain(_geo(), 0.4)
    saved = client.host.config.job_threshold_s
    client.host.config.job_threshold_s = 0.1
    try:
        result = client.ok("cook", {"paths": [out.path()], "profile": True})
    finally:
        client.host.config.job_threshold_s = saved
    assert result["state"] == "running"
    status = _wait_job(client, result["job_id"])
    assert status["state"] == "done"
    assert status["progress"] == 1.0 and status["current"] == status["total"] == 5  # 4 chain steps + 1 check
    final = client.ok("job", {"action": "result", "job_id": result["job_id"]})["result"]
    assert final["chain"][0]["path"] == slow.path()


def test_cook_profile_and_frame_range_errors(client):
    box = _geo().createNode("box")
    path = box.path()
    for args in (
        {"profile": True, "frame_range": [1, 3]},
        {"frame": 2, "frame_range": [1, 3]},
        {"frame_range": [5, 1]},
        {"frame_range": [1, 3, 0]},
        {"frame_range": [1]},
        {"frame_range": [1, 3], "summary": "boxes"},
    ):
        error = client.error("cook", {"paths": [path], **args})
        assert error["code"] == "invalid_argument", (args, error)


# -- cook frame_range (review 11 B8) ---------------------------------------------------


def _animated_scatter(geo):
    grid = geo.createNode("grid")
    grid.parm("sizex").setExpression("1 + $F * 0.25")
    scatter = geo.createNode("scatter")
    scatter.setInput(0, grid)
    scatter.parm("npts").set(200)
    scatter.setDisplayFlag(True)
    return scatter


def test_cook_frame_range_bbox_summary(client):
    geo = _geo()
    scatter = _animated_scatter(geo)
    hou.setFrame(5)
    try:
        result = client.ok(
            "cook", {"paths": [scatter.path()], "frame_range": [1, 24], "summary": "bbox"}
        )
        assert hou.frame() == 5
    finally:
        hou.setFrame(1)
    assert result["ok"] is True
    assert result["frame_range"] == [1, 24, 1]
    frames = result["frames"]
    assert [row["frame"] for row in frames] == list(range(1, 25))
    assert all(row["point_count"] == 200 for row in frames)
    widths = [row["bbox_max"][0] - row["bbox_min"][0] for row in frames]
    assert widths[-1] > widths[0] + 4, widths
    assert len({round(w, 3) for w in widths}) > 20
    assert result["results"][0]["path"] == scatter.path()

    # An object reads its display SOP; step thins the frames; summary none drops them.
    by_obj = client.ok(
        "cook", {"paths": [geo.path()], "frame_range": [1, 24, 6], "summary": "bbox"}
    )
    assert [row["frame"] for row in by_obj["frames"]] == [1, 7, 13, 19]
    assert by_obj["frames"][1]["bbox_max"] == frames[6]["bbox_max"]
    plain = client.ok("cook", {"paths": [scatter.path()], "frame_range": [1, 4]})
    assert "frames" not in plain and plain["frames_cooked"] == 4


def test_cook_frame_range_as_a_job_reports_frame_progress(client):
    geo = _geo()
    scatter = _animated_scatter(geo)
    slow = _slow_python_sop(geo, 0.03)
    slow.setInput(0, scatter)
    saved = client.host.config.job_threshold_s
    client.host.config.job_threshold_s = 0.1
    try:
        result = client.ok(
            "cook", {"paths": [slow.path()], "frame_range": [1, 24], "summary": "bbox"}
        )
    finally:
        client.host.config.job_threshold_s = saved
    assert result["state"] == "running"
    job_id = result["job_id"]
    messages = set()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.ok("job", {"action": "status", "job_id": job_id})
        if status.get("message"):
            messages.add(status["message"])
        if status["state"] != "running":
            break
        assert status.get("total") in (None, 24)
        client.host.executor.pump_once(0.02)
    assert status["state"] == "done", status
    assert status["progress"] == 1.0 and status["current"] == 24 and status["total"] == 24
    assert any(m.startswith("frame ") and m.endswith("/24") for m in messages), messages
    final = client.ok("job", {"action": "result", "job_id": job_id})["result"]
    assert len(final["frames"]) == 24
    assert final["frames"][0]["bbox_min"] != final["frames"][-1]["bbox_min"]
    assert hou.frame() == 1


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


# -- problems: budget, locked assets, defaults, dedupe, $TEMP (review 10) -------------


def test_problems_time_budget_returns_incomplete_with_node_cursor(client, monkeypatch):
    from hocuspocus.host.tools import cook as cook_module

    geo = _geo()
    for i in range(30):
        geo.createNode("xform", f"x{i:02d}")
    full = client.ok("problems", {"root": geo.path(), "limit": 1000})
    assert full["total"] == 30 and "incomplete" not in full

    real = cook_module.node_problems

    def slow(node, **kw):
        time.sleep(0.05)
        return real(node, **kw)

    monkeypatch.setattr(cook_module, "node_problems", slow)
    seen = []
    cursor = None
    calls = 0
    while True:
        args = {"root": geo.path(), "limit": 1000, "timeout_s": 1}
        if cursor:
            args["cursor"] = cursor
        page = client.ok("problems", args)
        calls += 1
        seen.extend((r["path"], r["kind"]) for r in page["problems"])
        cursor = page.get("next_cursor")
        if not page.get("incomplete"):
            assert cursor is None
            break
        assert cursor and page["nodes_scanned"] >= 1
        assert calls < 20
    assert calls > 1
    assert sorted(seen) == sorted((r["path"], r["kind"]) for r in full["problems"])


def test_problems_budget_pages_rows_inside_a_partial_scan(client, monkeypatch):
    from hocuspocus.host.tools import cook as cook_module

    geo = _geo()
    for i in range(12):
        geo.createNode("xform", f"x{i:02d}")
    real = cook_module.node_problems

    def slow(node, **kw):
        time.sleep(0.1)
        return real(node, **kw)

    monkeypatch.setattr(cook_module, "node_problems", slow)
    seen = []
    cursor = None
    for _ in range(40):
        args = {"root": geo.path(), "limit": 2, "timeout_s": 1}
        if cursor:
            args["cursor"] = cursor
        page = client.ok("problems", args)
        assert len(page["problems"]) <= 2
        seen.extend(r["path"] for r in page["problems"])
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    assert sorted(seen) == sorted(f"{geo.path()}/x{i:02d}" for i in range(12))


def test_problems_skips_parms_inside_locked_assets(client):
    from hocuspocus.host.tools import cook as cook_module

    geo = _geo()
    geo.createNode("attribnoise::2.0")
    scanned = []
    real = cook_module._broken_references

    def spy(node, parm):
        scanned.append(node.path())
        return real(node, parm)

    cook_module._broken_references = spy
    try:
        client.ok("problems", {"root": "/obj", "recurse_locked": True})
    finally:
        cook_module._broken_references = real
    inside = [p for p in scanned if p.startswith(f"{geo.path()}/attribnoise") and p.count("/") > 3]
    assert inside == []


def test_problems_skips_parms_at_default(client):
    from hocuspocus.host.tools import cook as cook_module

    box = _geo().createNode("box")
    box.parm("sizex").set(2)
    checked = []
    real = cook_module._missing_file

    def spy(node, parm):
        checked.append(parm.name())
        return real(node, parm)

    cook_module._missing_file = spy
    try:
        client.ok("problems", {"root": box.path()})
    finally:
        cook_module._missing_file = real
    assert checked == ["sizex"]


def test_problems_dedupes_identical_rows(client):
    geo = _geo()
    box = geo.createNode("box")
    box.setDisplayFlag(True)
    box.parm("sizex").setExpression("$F*(")
    result = client.ok("problems", {"root": "/obj", "cook_uncooked": True})
    keys = [(r["path"], r["kind"], r["message"]) for r in result["problems"]]
    assert len(keys) == len(set(keys)), keys
    texts = [r["message"].split(": ", 1)[1] for r in result["problems"] if r["kind"] == "error"]
    assert len(texts) == len(set(texts)), result["problems"]  # the object mirror is dropped


def test_problems_checks_paths_under_temp_variables(client):
    geo = _geo()
    reader = geo.createNode("file", "tmpread")
    reader.parm("file").set("$TEMP/hp_definitely_missing_9f2c.bgeo.sc")
    sequence = geo.createNode("file", "seq")
    sequence.parm("file").set("$TEMP/hp_seq.$F4.bgeo.sc")
    padded = geo.createNode("file", "fseq")
    padded.parm("file").set("$TEMP/hp_seq.${F}.bgeo.sc")
    result = client.ok("problems", {"root": geo.path()})
    files = [r["path"] for r in result["problems"] if r["kind"] == "missing_file"]
    assert files == [reader.path()]
