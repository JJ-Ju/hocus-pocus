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


def test_cook_blocking_with_failed_item(client):
    _, _, script = _graph()
    result = client.ok("pdg", {"action": "cook", "top_path": script.path(), "block": True})
    assert result["ok"] is False
    status = result["status"]
    assert status["states"] == {"cooked_success": 2, "cooked_fail": 1}
    assert status["failed"] == 1 and status["cooked"] == 2
    assert status["cook_state"] == "failed"


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
    result = client.ok("job", {"action": "result", "job_id": started["job_id"]})["result"]
    assert result["path"] == script.path()
    assert result["ok"] is False
    assert result["status"]["failed"] == 1 and result["status"]["cooked"] == 2


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
