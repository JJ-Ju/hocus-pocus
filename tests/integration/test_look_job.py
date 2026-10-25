"""``look`` past ``wait_s`` answers as a job (BIBLE D75; the 2.0-vs-2.1 comparison runs:
a 1024x768 final look answered ``houdini_busy`` at 30 s and its picture was lost, and the
hint named ``timeout_s`` and a job, which look took neither of)."""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")


def _scene():
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("sphere").setDisplayFlag(True)
    light = hou.node("/obj").createNode("hlight::2.0", "key")
    light.parmTuple("t").set((3, 4, 5))


def _result(client, job_id, timeout=120.0):
    deadline = time.time() + timeout
    while True:
        status = client.ok("job", {"action": "result", "job_id": job_id})
        if status["state"] != "running" or time.time() > deadline:
            return status
        time.sleep(0.1)


def test_wait_s_is_checked(client):
    error = client.error("look", {"wait_s": -1})
    assert error["code"] == "invalid_argument" and "wait_s" in error["message"]


@pytest.mark.slow
def test_a_final_look_past_wait_s_is_a_job_whose_result_is_the_picture(client):
    _scene()
    envelope = client.call("look", {"quality": "final", "resolution": [160, 120], "wait_s": 0})
    assert envelope["ok"], envelope
    running = envelope["result"]
    assert running["state"] == "running" and running["tool"] == "look", running
    assert "job {action: 'status' | 'result', job_id}" in running["hint"]
    status = _result(client, running["job_id"])
    assert status["state"] == "done", status
    picture = status["result"]
    assert picture["backend_used"] == "karma" and picture["rendered"] == [160, 120]
    assert picture["image"]["png_base64"]


@pytest.mark.slow
def test_a_look_within_wait_s_answers_in_the_call(client):
    _scene()
    result = client.ok("look", {"quality": "final", "resolution": [64, 48], "wait_s": 120})
    assert "job_id" not in result and result["backend_used"] == "karma"
