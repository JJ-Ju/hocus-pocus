"""hp/v1 transport against the in-process host: health, auth, Origin, envelope, errors."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def test_health_needs_no_auth(client):
    response = client.request("GET", "/hp/v1/health", token=None)
    assert response.status == 200
    body = response.body
    assert body["ok"] is True
    assert body["pid"] == client.host.pid
    assert body["houdini"] == hou.applicationVersionString()
    assert isinstance(body["generation"], int)
    assert body["hp"] == 1


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_call_without_valid_token_is_401(client, token):
    response = client.request(
        "POST", "/hp/v1/call", {"tool": "houdini_status", "args": {}}, token=token
    )
    assert response.status == 401
    assert response.body["ok"] is False


def test_non_loopback_origin_is_403(client):
    response = client.request(
        "POST",
        "/hp/v1/call",
        {"tool": "houdini_status", "args": {}},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status == 403
    health = client.request(
        "GET", "/hp/v1/health", token=None, headers={"Origin": "http://evil.example"}
    )
    assert health.status == 403


def test_loopback_origin_is_allowed(client):
    response = client.request(
        "POST",
        "/hp/v1/call",
        {"tool": "houdini_status", "args": {}},
        headers={"Origin": "http://localhost:6274"},
    )
    assert response.status == 200
    assert response.body["ok"] is True


def test_unknown_tool_is_invalid_argument(client):
    error = client.error("no_such_tool")
    assert error["code"] == "invalid_argument"
    assert "not implemented in this host version" in error["hint"]
    assert error["retryable"] is False


def test_bad_args_shape_is_invalid_argument(client):
    response = client.request("POST", "/hp/v1/call", {"tool": "houdini_status", "args": [1, 2]})
    assert response.status == 200
    assert response.body["error"]["code"] == "invalid_argument"


def test_unknown_route_is_404(client):
    assert client.request("GET", "/hp/v1/nope").status == 404


def test_job_route_reports_job_not_found(client):
    response = client.request("GET", "/hp/v1/jobs/doesnotexist")
    assert response.status == 200
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "job_not_found"


def test_job_tool_list_and_not_found(client):
    assert client.ok("job", {"action": "list"}) == {"jobs": client.host.jobs.list()}
    error = client.error("job", {"action": "status", "job_id": "nope"})
    assert error["code"] == "job_not_found"
    assert "job ids look like" in error["hint"]  # review 25 papercut 5: not the 1.x text
    error = client.error("job", {"action": "status", "job_id": f"{client.host.pid}-nope"})
    assert error["code"] == "job_not_found" and "restart" in error["hint"]


def test_job_runs_hou_through_executor(client):
    import time

    job = client.host.jobs.start("test", lambda ctx: ctx.run_main(lambda: hou.node("/obj").path()))
    deadline = time.monotonic() + 10
    while job.state == "running" and time.monotonic() < deadline:
        client.host.executor.pump_once(0.01)
    result = client.ok("job", {"action": "result", "job_id": job.id})
    assert result["state"] == "done"
    assert result["result"] == "/obj"


def test_houdini_busy_on_slow_call(client):
    envelope = client.call(
        "houdini_python", {"code": "import time\ntime.sleep(1.5)\n'late'"}, timeout_s=0.3
    )
    assert envelope["ok"] is False
    error = envelope["error"]
    assert error["code"] == "houdini_busy"
    assert error["retryable"] is True
    assert error["detail"]["started"] is True
    # The host is usable again afterwards.
    assert client.ok("houdini_python", {"code": "1 + 1"})["result"] == 2


def test_read_only_mode_refuses_mutations(client):
    client.host.config.read_only = True
    error = client.error("houdini_python", {"code": "hou.node('/obj').createNode('geo')"})
    assert error["code"] == "read_only"
    assert hou.node("/obj").children() == ()
    # Read-only tools still work.
    assert client.ok("houdini_status")["read_only"] is True


def test_mutating_call_records_one_undo_group(client):
    envelope = client.call(
        "houdini_python", {"code": "hou.node('/obj').createNode('geo', 'undo_me')"}
    )
    assert envelope["ok"] is True
    label = envelope["_meta"]["undo_label"]
    assert label.startswith("HocusPocus: houdini_python")
    assert hou.undos.undoLabels()[0] == label
    assert client.host.undo.labels()[0] == label
    hou.undos.performUndo()
    assert hou.node("/obj/undo_me") is None


def test_custom_undo_label(client):
    envelope = client.call(
        "houdini_python", {"code": "hou.node('/obj').createNode('geo')", "undo_label": "add a geo"}
    )
    assert envelope["_meta"]["undo_label"] == "HocusPocus: houdini_python add a geo"


def test_read_only_tool_opens_no_undo_group(client):
    envelope = client.call("houdini_status")
    assert envelope["_meta"]["undo_label"] is None


def test_rollback_is_reported_honestly_when_undo_is_disabled(client):
    """Review 10 section 1.7: with undo disabled nothing can be rolled back; say so."""
    code = "hou.node('/obj').createNode('geo', 'kept_geo')\n1/0"
    with hou.undos.disabler():
        error = client.error("houdini_python", {"code": code})
    assert error["code"] == "python_exception"
    assert error["detail"]["rolled_back"] is False
    assert hou.node("/obj/kept_geo") is not None
    error = client.error("houdini_python", {"code": code.replace("kept_geo", "gone_geo")})
    assert error["detail"]["rolled_back"] is True
    assert hou.node("/obj/gone_geo") is None
