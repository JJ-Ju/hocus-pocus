"""cook and problems against real Houdini (bible §4.6, §5.3, §7)."""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")


def _geo(name: str = "geo1"):
    return hou.node("/obj").createNode("geo", name)


def _slow_python_sop(parent, seconds: float, name: str = "slow", time_dependent: bool = False):
    """A Python SOP that sleeps ``seconds`` per cook. Not time dependent, a frame range
    cooks it once and reuses the result; ``time_dependent`` (it reads ``hou.frame()``)
    makes every frame sleep."""
    node = parent.createNode("python", name)
    frame = "hou.frame()\n" if time_dependent else ""
    node.parm("python").set(f"import time\n{frame}time.sleep({seconds})")
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


@pytest.mark.slow
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
    # 4 chain steps + 1 check of the named node
    assert status["progress"] == 1.0 and status["current"] == status["total"] == 5
    final = client.ok("job", {"action": "result", "job_id": result["job_id"]})["result"]
    assert final["chain"][0]["path"] == slow.path()


def _for_each_points(geo, points: int, slow_s: float):
    """A for-each-point loop over ``points`` grid points whose body sleeps ``slow_s``."""
    grid = geo.createNode("grid", "pts")
    grid.parm("rows").set(2)
    grid.parm("cols").set(points // 2)
    begin = geo.createNode("block_begin", "each_begin")
    begin.setInput(0, grid)
    begin.parm("method").set(1)  # fetch piece or point
    slow = _slow_python_sop(geo, slow_s, "body_slow")
    slow.setInput(0, begin)
    fast = geo.createNode("null", "body_fast")
    fast.setInput(0, slow)
    end = geo.createNode("block_end", "each_end")
    end.setInput(0, fast)
    end.parm("itermethod").set(1)  # by pieces or points
    end.parm("method").set(1)  # merge each iteration
    end.parm("blockpath").set("../each_begin")
    end.parm("templatepath").set("../each_begin")
    begin.parm("blockpath").set("../each_end")
    out = geo.createNode("null", "OUT")
    out.setInput(0, end)
    return grid, begin, slow, fast, end, out


def test_cook_profile_attributes_loop_bodies(client):
    """Review 12 papercut 5: inside a for-each loop the body nodes carry the loop's real
    per-node cost (Houdini's performance monitor), not one standalone cook."""
    geo = _geo()
    grid, begin, slow, fast, end, out = _for_each_points(geo, 4, 0.03)
    out.cook(force=True)
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    assert result["ok"] is True, result
    assert result["attribution"] == "perf_monitor", result
    (loop,) = result["loops"]
    assert loop["block_end"] == end.path() and loop["block_begin"] == begin.path()
    assert loop["iterations"] == 4
    assert loop["total_ms"] >= 4 * 30 * 0.9
    rows = {row["path"]: row for row in result["chain"]}
    body = rows[slow.path()]
    assert body["in_loop"] == end.path() and body["cooks"] == 4
    assert body["cook_time_ms"] >= 4 * 30 * 0.9  # all iterations, not one cook
    assert 25 <= body["per_iteration_ms"] <= body["cook_time_ms"] / 2
    assert rows[fast.path()]["in_loop"] == end.path()
    assert "in_loop" not in rows[grid.path()] and "in_loop" not in rows[out.path()]
    assert rows[end.path()]["cook_time_ms"] >= body["cook_time_ms"] * 0.9
    # The loop is counted once, at its block_end: body rows are not added on top.
    outside = sum(r["cook_time_ms"] for r in result["chain"] if "in_loop" not in r)
    assert result["total_ms"] <= outside + 1 and result["total_ms"] < 2 * loop["total_ms"] + 50
    # results[] reports the profiled cook of the named node, never a cached 0.0.
    assert result["results"][0]["cook_time_ms"] == rows[out.path()]["cook_time_ms"]


def test_cook_profile_without_loops_says_per_node(client):
    _box, _slow, _sub, out = _chain(_geo(), 0.02)
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    assert result["attribution"] == "per_node" and "loops" not in result
    row = next(r for r in result["chain"] if r["path"] == out.path())
    assert result["results"][0]["cook_time_ms"] == row["cook_time_ms"]


@pytest.mark.parametrize("warm", [False, True], ids=["dirty", "cooked"])
def test_cook_profile_leaves_out_inputs_a_normal_cook_does_not_cook(client, warm):
    """Review 26 P1 #8: a Switch's unselected input, and what feeds a bypassed node, are
    not profiled (profiling force-cooked them, so "interiors off costs nothing" looked
    false); ``inactive`` names them. Switching the input profiles the other branch."""
    geo = _geo()
    shell = geo.createNode("box", "shell")
    interior = _slow_python_sop(geo, 0.2, "interior")
    interior.setInput(0, geo.createNode("grid", "floor"))
    switch = geo.createNode("switch", "interiors")
    switch.setInput(0, shell)
    switch.setInput(1, interior)
    out = geo.createNode("null", "OUT")
    out.setInput(0, switch)
    if warm:
        out.cook(force=True)
    before = interior.cookCount()
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    paths = {row["path"] for row in result["chain"]}
    assert paths == {shell.path(), switch.path(), out.path()}, result
    assert result["chain_total"] == 3 and result["total_ms"] < 150, result
    assert result["inactive"]["count"] == 2, result
    assert set(result["inactive"]["paths"]) == {interior.path(), f"{geo.path()}/floor"}
    assert interior.cookCount() == before  # never cooked by the profile
    switch.parm("input").set(1)
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    assert interior.path() in {row["path"] for row in result["chain"]}
    assert result["inactive"] == {"count": 1, "paths": [shell.path()]}
    assert result["total_ms"] >= 190
    switch.parm("input").set(0)
    switch.bypass(True)  # a bypassed Switch passes input 0 through
    result = client.ok("cook", {"paths": [out.path()], "profile": True})
    assert interior.path() in result["inactive"]["paths"], result


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
    # 24 runs (every frame differs): at most 12 rows, the first six and the last six.
    frames = result["frames"]
    assert [row["frame"] for row in frames] == [*range(1, 7), *range(19, 25)]
    assert result["frames_truncated"] is True and result["frames_rows"] == 24
    assert all(row["point_count"] == 200 for row in frames)
    widths = [row["bbox_max"][0] - row["bbox_min"][0] for row in frames]
    assert widths[-1] > widths[0] + 4, widths
    assert len({round(w, 3) for w in widths}) > 10
    assert result["results"][0]["path"] == scatter.path()

    # An object reads its display SOP; step thins the frames; summary none drops them.
    by_obj = client.ok(
        "cook", {"paths": [geo.path()], "frame_range": [1, 24, 6], "summary": "bbox"}
    )
    assert [row["frame"] for row in by_obj["frames"]] == [1, 7, 13, 19]
    assert "frames_truncated" not in by_obj
    assert by_obj["frames"][3]["bbox_max"] == frames[6]["bbox_max"]  # frame 19
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
        if status["state"] == "running" and "frames done" in status.get("message", ""):
            # Review 20 N7: the message counts the frames done, as current does.
            current = status["current"]
            assert status["message"] == (
                f"{current}/24 frames done, cooking frame {current + 1}"
            ), status
        if status["state"] != "running":
            break
        assert status.get("total") in (None, 24)
        client.host.executor.pump_once(0.02)
    assert status["state"] == "done", status
    assert status["progress"] == 1.0 and status["current"] == 24 and status["total"] == 24
    assert any("frames done, cooking frame" in m for m in messages), messages
    final = client.ok("job", {"action": "result", "job_id": job_id})["result"]
    # The job's result (what a pushed-progress completion returns) is capped the same way.
    assert len(final["frames"]) == 12 and final["frames_rows"] == 24
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


# -- review 10 §5 ------------------------------------------------------------------


def test_problems_cook_uncooked_over_a_dop_network(client):
    dopnet = hou.node("/obj").createNode("dopnet", "sim")
    obj = dopnet.createNode("rbdobject", "rbd")
    obj.parm("soppath").set("/obj/nowhere/OUT")
    solver = dopnet.createNode("rigidbodysolver", "solver")
    solver.setInput(0, obj)
    out = dopnet.createNode("output", "out")
    out.setInput(0, solver)
    out.setDisplayFlag(True)
    quiet = client.ok("problems", {"root": dopnet.path()})
    assert "cooked" not in quiet
    assert out.needsToCook()
    cooked = client.ok("problems", {"root": dopnet.path(), "cook_uncooked": True})
    # Every DOP under the network is cooked; the dopnet object itself is not.
    assert cooked["cooked"] == cooked["nodes_scanned"] - 1 >= 3
    assert cooked["nodes_scanned"] == quiet["nodes_scanned"]
    assert [(r["path"], r["kind"]) for r in cooked["problems"]] == [
        (obj.path(), "broken_reference")
    ]


def test_problems_budget_holds_on_two_thousand_nodes(client):
    geo = _geo()
    nodes = [geo.createNode("box", "source")]
    for i in range(1999):
        node = geo.createNode("xform", f"n{i}")
        if nodes:
            node.setInput(0, nodes[-1])
        if i % 100 == 0:
            node.parm("scale").setExpression('ch("../nope/tx")')
        nodes.append(node)
    started = time.perf_counter()
    whole = client.ok("problems", {"root": geo.path(), "limit": 100})
    full_s = time.perf_counter() - started
    print(f"\nproblems over 2,000 nodes: {full_s:.3f}s, incomplete={whole.get('incomplete')}")
    assert whole.get("incomplete") is not True
    assert whole["nodes_scanned"] == 2001
    assert whole["counts"]["broken_reference"] == 20
    assert full_s < 10

    # A tiny budget (half of timeout_s) stops early, and the cursor finishes the walk.
    started = time.perf_counter()
    first = client.ok("problems", {"root": geo.path(), "timeout_s": 0.05, "limit": 100})
    tiny_s = time.perf_counter() - started
    assert tiny_s < max(1.0, full_s), (tiny_s, full_s)

    def refs(result):
        return sum(1 for row in result["problems"] if row["kind"] == "broken_reference")

    scanned, page, seen = first["nodes_scanned"], first, refs(first)
    while page.get("next_cursor"):
        page = client.ok(
            "problems",
            {"root": geo.path(), "timeout_s": 0.05, "limit": 100, "cursor": page["next_cursor"]},
        )
        if page.get("node_offset") is not None and page["node_offset"] >= scanned:
            scanned += page["nodes_scanned"]
        seen += refs(page)
    assert first.get("incomplete") is True, first
    assert scanned == 2001
    assert seen == 20


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


@pytest.mark.slow
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


@pytest.mark.slow
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


# -- writer SOPs and ROPs (review 17 P0-1, review 18 papercut 8) --------------------------


def _file_cache(work_dir, name: str = "cache", frames=(1, 3)):
    geo = _geo("fx")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    cache = geo.createNode("filecache::2.0", name)
    cache.setInput(0, box)
    cache.parm("filemethod").set(1)  # explicit file
    cache.parm("file").set(str(work_dir / "fc.$F4.bgeo.sc").replace("\\", "/"))
    for parm, value in zip(("f1", "f2"), frames, strict=True):
        cache.parm(parm).deleteAllKeyframes()
        cache.parm(parm).set(value)
    return cache


def test_cook_frame_range_on_a_file_cache_says_it_writes_nothing(client, work_dir):
    cache = _file_cache(work_dir)
    result = client.ok("cook", {"paths": [cache.path()], "frame_range": [1, 3]})
    assert result["ok"] is True
    assert not list(work_dir.glob("fc.*"))
    (note,) = [n for n in result["notes"] if cache.path() in n]
    assert "does not write" in note and "render" in note and "press" in note


def test_cook_on_a_rop_says_cooking_does_not_render(client, work_dir):
    geo = _geo()
    box = geo.createNode("box")
    sop_rop = geo.createNode("rop_geometry", "write")
    sop_rop.setInput(0, box)
    out_rop = hou.node("/out").createNode("geometry", "bgeo")
    out_rop.parm("soppath").set(box.path())
    result = client.ok("cook", {"paths": [sop_rop.path(), out_rop.path(), box.path()]})
    notes = result["notes"]
    assert len(notes) == 2, notes
    assert any(sop_rop.path() in n and "render" in n for n in notes)
    assert any(out_rop.path() in n and "render" in n for n in notes)


# -- review 17: wait_s, summary rows on change, partial results, sims ----------------------


def test_cook_frame_range_summary_emits_rows_only_on_change(client):
    geo = _geo()
    box = geo.createNode("box")
    box.parm("ty").setExpression("floor($F / 4)")
    result = client.ok("cook", {"paths": [box.path()], "frame_range": [1, 10], "summary": "bbox"})
    frames = result["frames"]
    assert [(row["frame"], row.get("through")) for row in frames] == [(1, 3), (4, 7), (8, 10)]
    assert frames[1]["bbox_min"][1] == pytest.approx(0.5)
    still = client.ok("cook", {"paths": [geo.path()], "frame_range": [1, 5], "summary": "bbox"})
    assert [(row["frame"], row.get("through")) for row in still["frames"]] == [(1, 3), (4, 5)]


def test_cook_wait_s_zero_returns_a_job_at_once(client):
    node = _slow_python_sop(_geo(), 0.3)
    result = client.ok("cook", {"paths": [node.path()], "force": True, "wait_s": 0})
    assert result["state"] == "running"
    status = _wait_job(client, result["job_id"])
    assert status["state"] == "done"
    error = client.error("cook", {"paths": [node.path()], "wait_s": -1})
    assert error["code"] == "invalid_argument"


@pytest.mark.slow
def test_cook_cancelled_frame_range_keeps_the_frames_cooked(client):
    geo = _geo()
    box = geo.createNode("box")
    slow = _slow_python_sop(geo, 0.05, time_dependent=True)
    slow.setInput(0, box)
    hou.setFrame(7)
    result = client.ok(
        "cook",
        {"paths": [slow.path()], "frame_range": [1, 200], "summary": "bbox", "wait_s": 0},
    )
    job_id = result["job_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.ok("job", {"action": "status", "job_id": job_id})
        if (status.get("current") or 0) >= 4:
            break
        client.host.executor.pump_once(0.02)
    client.ok("job", {"action": "cancel", "job_id": job_id})
    assert _wait_job(client, job_id)["state"] == "cancelled"
    error = client.error("job", {"action": "result", "job_id": job_id})
    assert error["code"] == "cancelled"
    partial = error["detail"]["partial"]
    assert 4 <= partial["frames_cooked"] < 200
    assert partial["frames"][0]["frame"] == 1
    last = error["detail"]["last_status"]
    assert last["total"] == 200
    # Review 20 N7: the last status says cancelled, and counts what partial counts.
    assert last["state"] == "cancelled", last
    assert last["current"] == partial["frames_cooked"], last
    assert last["message"].startswith(f"{partial['frames_cooked']}/200 frames done"), last
    assert hou.frame() == 7


def test_job_cancel_after_the_job_finished_says_so(client):
    """Review 20: a cancel that arrives after the job finished says nothing was cancelled."""
    box = _geo().createNode("box")
    started = client.ok("cook", {"paths": [box.path()], "frame_range": [1, 2], "wait_s": 0})
    _wait_job(client, started["job_id"])
    late = client.ok("job", {"action": "cancel", "job_id": started["job_id"]})
    assert late["cancelled"] is False and late["state"] == "done", late
    assert "already finished" in late["notes"][0]
    assert client.ok("job", {"action": "result", "job_id": started["job_id"]})["state"] == "done"


def test_cook_profile_on_a_sim_says_whether_it_resimulated(client):
    geo = _geo()
    sphere = geo.createNode("sphere")
    source = geo.createNode("pyrosource")
    source.setInput(0, sphere)
    source.parm("initialize").set("source")
    source.parm("initialize").pressButton()
    raster = geo.createNode("volumerasterizeattributes")
    raster.setInput(0, source)
    raster.parm("attributes").set("density temperature")
    solver = geo.createNode("pyrosolver")
    solver.setInput(0, raster)
    solver.parm("divsize").set(0.25)
    first = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 3})
    row = next(r for r in first["chain"] if r["path"] == solver.path())
    assert row["simulation"]["resimulated"] is True
    assert any("simulat" in n for n in first["notes"])
    # Profiling the same frame again force-cooks the solver's inputs, so Houdini re-solves
    # its newest frame only (review 24 N3), or reads it from the cache.
    again = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 3})
    row = next(r for r in again["chain"] if r["path"] == solver.path())
    assert row["simulation"]["resimulated"] in (False, "current_frame"), row


def _small_pyro():
    geo = _geo()
    sphere = geo.createNode("sphere")
    source = geo.createNode("pyrosource")
    source.setInput(0, sphere)
    source.parm("initialize").set("source")
    source.parm("initialize").pressButton()
    raster = geo.createNode("volumerasterizeattributes")
    raster.setInput(0, source)
    raster.parm("attributes").set("density temperature")
    solver = geo.createNode("pyrosolver")
    solver.setInput(0, raster)
    solver.parm("divsize").set(0.25)
    return solver


def _sim_row(result, solver):
    return next(r for r in result["chain"] if r["path"] == solver.path())["simulation"]


def test_cook_profile_of_a_cached_earlier_frame_did_not_resimulate(client):
    """Review 20 N3: after a sim ran to frame 6, profiling frame 3 reads the cache; the
    simulation's time moves back, which used to read as resimulated."""
    solver = _small_pyro()
    client.ok("cook", {"paths": [solver.path()], "frame_range": [1, 6]})
    earlier = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 3})
    sim = _sim_row(earlier, solver)
    assert sim["resimulated"] is False and sim["frame"] == 3, sim
    assert any("did not re-simulate" in n for n in earlier["notes"])
    later = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 8})
    assert _sim_row(later, solver)["resimulated"] is True


def test_cook_profile_with_a_full_sim_cache_still_tells(client):
    """Review 20 N3: with the memory cache full, a cache read and a step both leave the
    memory size alone; the solve stats still tell them apart."""
    solver = _small_pyro()
    solver.parm("cachemaxsize").set(1)  # MB
    client.ok("cook", {"paths": [solver.path()], "frame_range": [1, 8]})
    cached = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 7})
    assert _sim_row(cached, solver)["resimulated"] is False
    later = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 9})
    assert _sim_row(later, solver)["resimulated"] is True


def test_cook_profile_says_null_when_the_sim_gives_no_signal(client, monkeypatch):
    """Review 20 N3: without the performance monitor's solve stats, a cache read is only a
    time change, which a step with a full cache also is: resimulated is null."""
    from hocuspocus.host.tools import cook as cook_module

    solver = _small_pyro()
    client.ok("cook", {"paths": [solver.path()], "frame_range": [1, 6]})

    def unmonitored(node, solve=False):
        return (*cook_module.timed_cook(node, True), None)

    monkeypatch.setattr(cook_module, "_perf_cook", unmonitored)
    result = client.ok("cook", {"paths": [solver.path()], "profile": True, "frame": 3})
    sim = _sim_row(result, solver)
    assert sim["resimulated"] is None, sim
    assert any("unknown" in n for n in result["notes"])


def _vellum_cloth():
    geo = _geo("cloth")
    grid = geo.createNode("grid")
    grid.parm("rows").set(10)
    grid.parm("cols").set(10)
    grid.parm("ty").set(3)
    cloth = geo.createNode("vellumconstraints")
    cloth.setInput(0, grid)
    solver = geo.createNode("vellumsolver")
    for index in range(3):
        solver.setInput(index, cloth, index)
    solver.setDisplayFlag(True)
    return solver


@pytest.mark.slow
def test_cook_profile_on_vellum_tells_full_runs_current_frame_and_cache_reads(client):
    """Review 24 N3: repeat profiles of a warm Vellum solver said resimulated: true and
    "simulated frames ... up to frame 24", though only frame 24 was re-solved (the
    profile force-cooks the solver's inputs)."""
    solver = _vellum_cloth()

    def profile(frame):
        # A fresh 12-frame solve takes 2 s here and over 10 s on a loaded machine. 10 s is
        # the job threshold, so the call then answered {job_id, state: running} and not the
        # profile. An explicit wait_s is the caller's own threshold (timeout_s the cook's):
        # the test says how long it is willing to wait.
        args = {
            "paths": [solver.path()],
            "profile": True,
            "frame": frame,
            "wait_s": 120,
            "timeout_s": 120,
        }
        result = client.ok("cook", args)
        assert "job_id" not in result, result
        note = next(n for n in result["notes"] if n.startswith(solver.path()))
        return _sim_row(result, solver), note

    fresh, note = profile(12)
    assert fresh["resimulated"] is True and fresh["simulated_frames"] == [1, 12], fresh
    assert "simulated frames 1-12" in note, note
    warm, note = profile(12)
    assert warm["resimulated"] == "current_frame", warm
    assert warm["simulated_frames"] == [12, 12] and warm["frame"] == 12, warm
    assert "re-solved only frame 12" in note and "simulated frames" not in note, note
    cached, note = profile(6)
    assert cached["resimulated"] is False and "simulated_frames" not in cached, cached
    assert "did not re-simulate" in note, note
    solver.parm("resimulate").pressButton()
    reset, note = profile(12)
    assert reset["resimulated"] is True and reset["simulated_frames"] == [1, 12], reset


def test_houdini_status_reports_process_memory(client):
    status = client.ok("houdini_status")
    memory = status["memory"]
    assert memory["rss_mb"] > 50
    assert memory["peak_mb"] >= memory["rss_mb"]
    # detail: false (what the houdini://status resource asks for) leaves them out.
    assert "memory" not in client.ok("houdini_status", {"detail": False})
