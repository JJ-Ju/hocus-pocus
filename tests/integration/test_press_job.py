"""A long press goes on as a job (BIBLE D70; review 26 P3 friction 1: an HDA's export
button ran 3-4 min and every ``parm_set press`` answered ``houdini_busy``).

In process the test's thread pumps Houdini's main thread, so the client reads the answer
once the callback returns; the host's ``elapsed_ms`` says when it answered.
"""

from __future__ import annotations

import time

import pytest

hou = pytest.importorskip("hou")

SLOW_CALLBACK = (
    "import time; time.sleep(0.8); hou.pwd().parm('count').set(hou.pwd().evalParm('count') + 1)"
)


@pytest.fixture
def button():
    node = hou.node("/obj").createNode("null", "exporter")
    group = node.parmTemplateGroup()
    group.append(hou.IntParmTemplate("count", "Count", 1))
    group.append(
        hou.ButtonParmTemplate(
            "export_all",
            "Export All",
            script_callback=SLOW_CALLBACK,
            script_callback_language=hou.scriptLanguage.Python,
        )
    )
    group.append(
        hou.ButtonParmTemplate(
            "quick",
            "Quick",
            script_callback="hou.pwd().parm('count').set(7)",
            script_callback_language=hou.scriptLanguage.Python,
        )
    )
    node.setParmTemplateGroup(group)
    return node


@pytest.fixture
def short_threshold(host):
    host.config.job_threshold_s, saved = 0.2, host.config.job_threshold_s
    yield
    host.config.job_threshold_s = saved


def _result(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while True:
        status = client.ok("job", {"action": "result", "job_id": job_id})
        if status["state"] != "running" or time.time() > deadline:
            return status
        time.sleep(0.05)


def test_a_long_parm_set_press_returns_a_job(client, button, short_threshold):
    envelope = client.call(
        "parm_set", {"items": [{"path": "/obj/exporter/export_all", "press": True}]}
    )
    assert envelope["ok"], envelope
    result = envelope["result"]
    assert result["state"] == "running" and result["running"] == "/obj/exporter/export_all"
    assert envelope["_meta"]["elapsed_ms"] < 700  # answered at the threshold, not the end
    status = _result(client, result["job_id"])
    assert status["state"] == "done", status
    (row,) = status["result"]["results"]
    assert row["pressed"] is True and row["side_effects"] == {"count": [0, 1]}
    assert button.evalParm("count") == 1
    assert status["result"]["dirty"] is True


def test_a_long_press_in_edit_keeps_the_later_ops(client, button, short_threshold):
    envelope = client.call(
        "edit",
        {
            "ops": [
                {"op": "set", "path": "/obj/exporter/export_all", "press": True},
                {"op": "create", "id": "n", "parent": "/obj", "type": "null", "name": "after"},
            ]
        },
    )
    assert envelope["ok"], envelope
    result = envelope["result"]
    assert result["state"] == "running" and result["job_id"]
    status = _result(client, result["job_id"])
    assert status["state"] == "done", status
    assert status["result"]["ids"] == {"n": "/obj/after"}
    assert hou.node("/obj/after") is not None
    # One undo step for the whole call, as for a call that answered in time.
    assert hou.undos.undoLabels()[0].startswith("HocusPocus: edit")


def test_a_short_press_answers_in_the_call(client, button, short_threshold):
    result = client.ok("parm_set", {"items": [{"path": "/obj/exporter/quick", "press": True}]})
    assert "job_id" not in result
    assert result["results"][0]["side_effects"] == {"count": [0, 7]}


def test_a_callback_that_raises_ends_its_job_done(client, short_threshold):
    """Measured on 22.0.466: pressButton prints a Python callback's exception and returns,
    so the job ends ``done`` as the call would have (a writer's save button that wrote
    nothing is ``cook_failed`` from its file check, unit-tested)."""
    node = hou.node("/obj").createNode("null", "broken")
    group = node.parmTemplateGroup()
    group.append(
        hou.ButtonParmTemplate(
            "go",
            "Go",
            script_callback="import time; time.sleep(0.6); raise RuntimeError('export failed')",
            script_callback_language=hou.scriptLanguage.Python,
        )
    )
    node.setParmTemplateGroup(group)
    result = client.ok("parm_set", {"items": [{"path": "/obj/broken/go", "press": True}]})
    status = _result(client, result["job_id"])
    assert status["state"] == "done", status
    assert status["result"]["results"][0]["pressed"] is True
