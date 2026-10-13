"""pdg against real TOP networks (bible §4.7, §7)."""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")

FAIL_SECOND = (
    "if work_item.index == 1:\n"
    "    raise RuntimeError('boom')\n"
    "work_item.addOutputFile('C:/hp-test/out%d.txt' % work_item.index, 'file/text')\n"
)


SLEEP = "import time\ntime.sleep(8)\n"
"""Out-of-process items that sleep: cancelling kills them (in-process Python cannot be
interrupted, so an in-process cook runs its started items to completion)."""


def _graph(script: str = FAIL_SECOND, count: int = 3, cook_type: int = 1):
    """topnet1: genericgenerator (``count`` items) -> pythonscript (1 in-process, 2 out)."""
    net = hou.node("/obj").createNode("topnet", "topnet1")
    gen = net.createNode("genericgenerator", "gen")
    gen.parm("itemcount").set(count)
    script_node = net.createNode("pythonscript", "script")
    script_node.setInput(0, gen)
    script_node.parm("pdg_cooktype").set(cook_type)
    script_node.parm("script").set(script)
    script_node.setDisplayFlag(True)
    return net, gen, script_node


def _rop_graph():
    """/obj/g/box -> /out/geo_out (geometry ROP) <- /obj/topnet1/fetch (ROP Fetch, out of
    process: each work item is a hython that loads the saved hip)."""
    box = hou.node("/obj").createNode("geo", "g").createNode("box", "box")
    rop = hou.node("/out").createNode("geometry", "geo_out")
    rop.parm("soppath").set(box.path())
    rop.parm("sopoutput").set("$HIP/geo/a.bgeo.sc")
    net = hou.node("/obj").createNode("topnet", "topnet1")
    fetch = net.createNode("ropfetch", "fetch")
    fetch.parm("roppath").set(rop.path())
    fetch.setDisplayFlag(True)
    return rop, fetch


def _wait_job(client, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.ok("job", {"action": "status", "job_id": job_id})
        if status["state"] != "running":
            return status
        client.host.executor.pump_once(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def test_cook_blocking_generator(client):
    net, gen, _ = _graph()
    result = client.ok("pdg", {"action": "cook", "top_path": gen.path(), "block": True})
    assert result["path"] == gen.path()
    assert result["ok"] is True
    status = result["status"]
    assert status["total"] == 3
    assert status["cooked"] == 3 and status["failed"] == 0
    assert status["states"] == {"cooked_success": 3}
    assert status["cook_state"] == "cooked"
    assert status["cooking"] is False


def test_cook_blocking_takes_timeout(client):
    _, gen, _ = _graph(count=2)
    args = {"action": "cook", "top_path": gen.path(), "block": True, "timeout_s": 120}
    result = client.ok("pdg", args)
    assert result["ok"] is True and result["status"]["cooked"] == 2


def test_cook_blocking_with_failed_item(client):
    _, _, script = _graph()
    result = client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    assert result["ok"] is False
    status = result["status"]
    assert status["states"] == {"cooked_success": 2, "cooked_fail": 1}
    assert status["failed"] == 1 and status["cooked"] == 2
    assert status["cook_state"] == "failed"
    # Review 14 papercut 1: the result says which item failed and why.
    [failure] = result["failures"]
    assert failure["node"] == script.path() and failure["index"] == 1
    assert "boom" in failure["error"], failure


def test_failed_out_of_process_item_reports_its_log(client):
    _, _, script = _graph(FAIL_SECOND, count=2, cook_type=2)
    started = client.ok("pdg", {"action": "cook", "top_path": script.path()})
    assert _wait_job(client, started["job_id"], timeout=90)["state"] == "done"
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["ok"] is False
    [failure] = result["failures"]
    assert "RuntimeError: boom" in failure["error"], failure
    assert failure["exit_code"] == 1
    page = client.ok("pdg", {"action": "workitems", "top_path": script.path()})
    failed = [r for r in page["work_items"] if r["state"] == "cooked_fail"]
    assert len(failed) == 1
    row = failed[0]
    assert "RuntimeError: boom" in row["error"] and len(row["error"]) <= 400
    assert row["exit_code"] == 1
    assert row["log_path"].endswith(".log")
    with open(row["log_path"], encoding="utf-8", errors="replace") as handle:
        assert "boom" in handle.read()
    ok_rows = [r for r in page["work_items"] if r["state"] == "cooked_success"]
    assert ok_rows and "error" not in ok_rows[0] and "log_path" not in ok_rows[0]


def test_cook_network_uses_display_node(client):
    net, _, script = _graph()
    result = client.ok("pdg", {"action": "cook", "top_path": net.path(), "block": True})
    assert result["path"] == script.path()
    status = client.ok("pdg", {"action": "status", "top_path": net.path()})
    assert status["path"] == net.path()
    assert status["total"] == 6
    assert status["failed"] == 1
    assert {row["path"] for row in status["nodes"]} == {
        f"{net.path()}/gen",
        script.path(),
    }  # the scheduler is not listed


def test_cook_as_job(client):
    _, _, script = _graph()
    started = client.ok("pdg", {"action": "cook", "top_path": script.path()})
    assert started["state"] == "running" and started["job_id"]
    status = _wait_job(client, started["job_id"])
    assert status["state"] == "done", status
    assert status["progress"] == 1.0 and status["current"] == status["total"] == 3, status
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["path"] == script.path()
    assert result["ok"] is False
    assert result["status"]["failed"] == 1 and result["status"]["cooked"] == 2
    assert [f["index"] for f in result["failures"]] == [1]


@pytest.mark.parametrize("where", ["args", "request"])
def test_cook_block_never_holds_the_main_thread_past_the_timeout(client, where):
    _, _, script = _graph(SLEEP, count=2, cook_type=2)
    args = {"action": "cook", "top_path": script.path(), "block": True}
    if where == "args":
        args["timeout_s"] = 2
        envelope = client.call("pdg", args)
    else:
        envelope = client.call("pdg", args, timeout_s=2)
    started = time.monotonic()
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert result["state"] == "running" and result["job_id"], result
    # The main thread is free right away (a blocking cookWorkItems would hold it ~8 s).
    assert client.ok("pdg", {"action": "status", "top_path": script.path()})["path"]
    assert time.monotonic() - started < 4
    client.ok("job", {"action": "cancel", "job_id": result["job_id"]})
    assert _wait_job(client, result["job_id"], timeout=30)["state"] == "cancelled"


def test_cook_block_honours_job_threshold(client):
    """block waits min(timeout_s, job_threshold_s), as cook does (BIBLE §7)."""
    _, _, script = _graph(SLEEP, count=2, cook_type=2)
    saved = client.host.config.job_threshold_s
    client.host.config.job_threshold_s = 0.5
    try:
        started = time.monotonic()
        args = {"action": "cook", "top_path": script.path(), "block": True, "timeout_s": 60}
        result = client.ok("pdg", args)
        elapsed = time.monotonic() - started
    finally:
        client.host.config.job_threshold_s = saved
    assert result["state"] == "running" and result["job_id"], result
    assert elapsed < 4, elapsed
    client.ok("job", {"action": "cancel", "job_id": result["job_id"]})
    assert _wait_job(client, result["job_id"], timeout=30)["state"] == "cancelled"


def test_cook_block_returns_result_within_threshold(client):
    _, gen, _ = _graph(count=2)
    before = len(client.ok("job", {"action": "list"})["jobs"])
    result = client.ok("pdg", {"action": "cook", "top_path": gen.path(), "block": True})
    assert "job_id" not in result
    assert result["ok"] is True and result["status"]["cooked"] == 2
    assert len(client.ok("job", {"action": "list"})["jobs"]) == before  # discarded


def test_read_only_refuses_cook_dirty_cancel(client):
    _, gen, _ = _graph()
    client.host.config.read_only = True
    for action in ("cook", "dirty", "cancel"):
        error = client.error("pdg", {"action": action, "top_path": gen.path()})
        assert error["code"] == "read_only", action
    assert client.ok("pdg", {"action": "status", "top_path": gen.path()})["total"] == 0
    assert client.ok("pdg", {"action": "workitems", "top_path": gen.path()})["total"] == 0


def test_cook_job_waits_for_the_graph_to_start(client):
    """A poll right after cookWorkItems(block=False) can see an idle graph with no items;
    the job must not report that as the finished cook."""
    _, _, script = _graph("import time\ntime.sleep(1)\n", count=2, cook_type=2)
    started = client.ok("pdg", {"action": "cook", "top_path": script.path()})
    assert _wait_job(client, started["job_id"], timeout=60)["state"] == "done"
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["status"]["total"] == 2
    assert result["status"]["cooked"] == 2, result


def test_cook_refuses_an_unsaved_hip_for_out_of_process_items(client, work_dir):
    """Review 14 papercut 2: ROP Fetch work items load the hip on disk, so cooking with
    unsaved changes silently cooks the old scene."""
    rop, fetch = _rop_graph()
    untitled = client.error("pdg", {"action": "cook", "top_path": fetch.path()})
    assert untitled["code"] == "unsaved_changes"
    assert "untitled" in untitled["message"] and "hip_save" in untitled["hint"]
    # save: true has nowhere to save an untitled scene.
    error = client.error("pdg", {"action": "cook", "top_path": fetch.path(), "save": True})
    assert error["code"] == "unsaved_changes" and "path" in error["hint"]

    hip = (work_dir / "wedges.hip").as_posix()
    client.ok("hip_save", {"path": hip})
    client.ok(
        "parm_set", {"items": [{"path": f"{rop.path()}/sopoutput", "value": "$HIP/geo/b.bgeo.sc"}]}
    )
    dirty = client.error("pdg", {"action": "cook", "top_path": fetch.path()})
    assert dirty["code"] == "unsaved_changes"
    assert fetch.path() in dirty["message"] and "save: true" in dirty["hint"]

    client.host.config.approved_roots = [str(work_dir / "elsewhere")]
    refused = client.error("pdg", {"action": "cook", "top_path": fetch.path(), "save": True})
    assert refused["code"] == "path_not_allowed"
    client.host.config.approved_roots = []

    started = client.ok("pdg", {"action": "cook", "top_path": fetch.path(), "save": True})
    assert started["saved"] == hip
    assert _wait_job(client, started["job_id"], timeout=120)["state"] == "done"
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["ok"] is True, result
    # The work item cooked the saved scene: the new output path, not the old one.
    assert (work_dir / "geo" / "b.bgeo.sc").is_file()
    assert not (work_dir / "geo" / "a.bgeo.sc").exists()


def test_in_process_graphs_cook_unsaved(client):
    _, gen, _ = _graph(count=1)
    assert client.ok("pdg", {"action": "cook", "top_path": gen.path(), "block": True})["ok"]


def test_status_before_cook(client):
    _, gen, _ = _graph()
    status = client.ok("pdg", {"action": "status", "top_path": gen.path()})
    assert status["total"] == 0
    assert status["states"] == {}
    assert status["cooking"] is False


def test_workitems_with_failure_and_paging(client):
    _, _, script = _graph()
    client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    page = client.ok("pdg", {"action": "workitems", "top_path": script.path()})
    assert page["total"] == 3
    rows = page["work_items"]
    assert [r["index"] for r in rows] == [0, 1, 2]
    assert [r["state"] for r in rows] == ["cooked_success", "cooked_fail", "cooked_success"]
    assert "boom" in rows[1]["error"] and "exit_code" not in rows[1]  # in-process
    assert rows[0]["output_files"] == ["C:/hp-test/out0.txt"]
    assert rows[1]["output_files"] == []
    assert all(isinstance(r["id"], int) and r["name"].startswith("script_") for r in rows)
    assert "node" not in rows[0]
    first = client.ok("pdg", {"action": "workitems", "top_path": script.path(), "limit": 2})
    assert len(first["work_items"]) == 2 and first["next_cursor"] == "2"
    rest = client.ok(
        "pdg",
        {"action": "workitems", "top_path": script.path(), "limit": 2, "cursor": "2"},
    )
    assert [r["index"] for r in rest["work_items"]] == [2]
    assert "next_cursor" not in rest


def test_workitems_on_network_names_nodes(client):
    net, _, script = _graph()
    client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    page = client.ok("pdg", {"action": "workitems", "top_path": net.path()})
    assert page["total"] == 6
    assert {r["node"] for r in page["work_items"]} == {f"{net.path()}/gen", script.path()}


def test_dirty(client):
    net, gen, script = _graph()
    client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    status = client.ok("pdg", {"action": "dirty", "top_path": script.path()})
    assert status["total"] == 0
    # Dirtying one node leaves its upstream items alone; the network dirties everything.
    assert client.ok("pdg", {"action": "status", "top_path": gen.path()})["total"] == 3
    status = client.ok("pdg", {"action": "dirty", "top_path": net.path()})
    assert status["total"] == 0


def test_cancel_running_cook(client):
    _, _, script = _graph(SLEEP, count=2, cook_type=2)
    started = client.ok("pdg", {"action": "cook", "top_path": script.path()})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.ok("pdg", {"action": "status", "top_path": script.path()})
        if status["states"].get("cooking"):
            break
        client.host.executor.pump_once(0.05)
    assert status["cooking"] is True and status["states"] == {"cooking": 2}
    cancelled = client.ok("pdg", {"action": "cancel", "top_path": script.path()})
    assert cancelled["path"] == script.path()
    final = _wait_job(client, started["job_id"], timeout=30)
    assert final["state"] == "done"
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["status"]["cooking"] is False
    assert result["status"]["cooked"] == 0
    assert result["status"]["states"] == {"cooked_cancel": 2}


def test_cancel_via_job(client):
    _, _, script = _graph(SLEEP, count=2, cook_type=2)
    started = client.ok("pdg", {"action": "cook", "top_path": script.path()})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if client.ok("pdg", {"action": "status", "top_path": script.path()})["states"].get(
            "cooking"
        ):
            break
        client.host.executor.pump_once(0.05)
    client.ok("job", {"action": "cancel", "job_id": started["job_id"]})
    final = _wait_job(client, started["job_id"], timeout=30)
    assert final["state"] == "cancelled"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not client.ok("pdg", {"action": "status", "top_path": script.path()})["cooking"]:
            break
        client.host.executor.pump_once(0.05)
    else:
        raise AssertionError("graph still cooking after the job was cancelled")
    status = client.ok("pdg", {"action": "status", "top_path": script.path()})
    assert status["states"] == {"cooked_cancel": 2}


def test_errors(client):
    _graph()
    geo = hou.node("/obj").createNode("geo", "geo1")
    assert client.error("pdg", {"action": "status", "top_path": geo.path()})["code"] == (
        "invalid_argument"
    )
    assert client.error("pdg", {"action": "status", "top_path": "/obj/nope"})["code"] == (
        "node_not_found"
    )
    assert client.error("pdg", {"action": "bake", "top_path": "/obj/topnet1"})["code"] == (
        "invalid_argument"
    )
