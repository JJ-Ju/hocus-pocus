"""undo, time, selection and job against real Houdini (bible §4.7, §7)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def _geo(name: str = "geo1"):
    return hou.node("/obj").createNode("geo", name)


# -- undo -------------------------------------------------------------------------------


def test_undo_history_lists_hocuspocus_labels(client):
    _geo()
    client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "box"}]})
    result = client.ok("undo", {"action": "history"})
    assert result["history"][0].startswith("HocusPocus: node_create")
    assert len(result["history"]) <= 20
    assert result["enabled"] is True
    assert isinstance(result["redo"], list)


def test_undo_and_redo_node_create(client):
    _geo()
    created = client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "box"}]})
    path = created["results"][0]["path"]
    assert hou.node(path) is not None

    envelope = client.call("undo", {"action": "undo"})
    assert envelope["ok"] is True, envelope
    # undo is not itself wrapped in an undo group (performUndo refuses inside one).
    assert envelope["_meta"]["undo_label"] is None
    result = envelope["result"]
    assert len(result["performed"]) == 1
    assert result["performed"][0].startswith("HocusPocus: node_create")
    assert result["next_redo"] == result["performed"][0]
    assert result["dirty"] is True
    assert hou.node(path) is None

    redone = client.ok("undo", {"action": "redo"})
    assert redone["performed"] == result["performed"]
    assert hou.node(path) is not None
    assert redone["next_undo"] == result["performed"][0]


def test_undo_multiple_steps_and_empty_stack(client):
    _geo()
    hou.undos.clear()
    client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "box"}]})
    client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "sphere"}]})
    result = client.ok("undo", {"action": "undo", "steps": 5})
    assert len(result["performed"]) == 2
    assert "nothing more to undo" in result["note"]
    assert result["undo_count"] == 0
    assert hou.node("/obj/geo1").children() == ()
    again = client.ok("undo", {"action": "redo", "steps": 2})
    assert len(again["performed"]) == 2
    assert {c.type().name() for c in hou.node("/obj/geo1").children()} == {"box", "sphere"}


def test_undo_parm_set_restores_value(client):
    box = _geo().createNode("box")
    client.ok("parm_set", {"items": [{"path": f"{box.path()}/sizex", "value": 4}]})
    assert box.parm("sizex").eval() == 4
    client.ok("undo", {"action": "undo"})
    assert box.parm("sizex").eval() == 1


def test_undo_argument_errors(client):
    error = client.error("undo", {"action": "rewind"})
    assert error["code"] == "invalid_argument"
    assert error["hint"]
    error = client.error("undo", {"action": "undo", "steps": 0})
    assert error["code"] == "invalid_argument"


def test_undo_read_only(client, host):
    host.config.read_only = True
    assert client.ok("undo", {"action": "history"})["history"] is not None
    error = client.error("undo", {"action": "undo"})
    assert error["code"] == "read_only"
    assert error["hint"]


# -- time -------------------------------------------------------------------------------


def test_time_read(client):
    result = client.ok("time", {})
    assert set(result) >= {"frame", "fps", "range", "playback_range"}
    assert result["frame"] == hou.frame()
    assert result["fps"] == hou.fps()
    assert result["range"] == list(hou.playbar.frameRange())


def test_time_set_frame_range_fps(client, host):
    result = client.ok("time", {"fps": 30, "range": [10, 100], "frame": 24})
    assert result["fps"] == 30
    assert result["range"] == [10, 100]
    assert result["playback_range"] == [10, 100]
    assert result["frame"] == 24
    assert hou.frame() == 24
    assert hou.fps() == 30
    assert host.scene.dirty is True


def test_time_fps_alone_keeps_range_in_frames(client):
    client.ok("time", {"fps": 24, "range": [1, 240]})
    result = client.ok("time", {"fps": 30})
    assert result["fps"] == 30
    assert result["range"] == [1, 240]


def test_time_frame_does_not_dirty_or_record_undo(client, host):
    host.scene.mark_clean()
    before = hou.undos.undoLabels()
    envelope = client.call("time", {"frame": 12})
    assert envelope["ok"] is True
    assert envelope["_meta"]["undo_label"] is None
    assert host.scene.dirty is False
    assert hou.undos.undoLabels() == before
    client.ok("time", {})
    assert host.scene.dirty is False


def test_time_frame_drives_expressions(client):
    box = _geo().createNode("box")
    box.parm("tx").setExpression("$F*0.1")
    client.ok("time", {"frame": 24})
    value = client.ok("parm_get", {"paths": [f"{box.path()}/tx"]})
    assert value["parms"][0]["value"] == pytest.approx(2.4)


def test_time_errors(client, host):
    assert client.error("time", {"range": [100, 1]})["code"] == "invalid_argument"
    assert client.error("time", {"range": [1]})["code"] == "invalid_argument"
    assert client.error("time", {"frame": "ten"})["code"] == "invalid_argument"
    assert client.error("time", {"fps": 0})["code"] == "invalid_argument"
    host.config.read_only = True
    assert client.error("time", {"range": [1, 50]})["code"] == "read_only"
    assert client.ok("time", {"frame": 5})["frame"] == 5


# -- selection --------------------------------------------------------------------------


def test_selection_read_set_clear(client):
    geo = _geo()
    a, b, c = (geo.createNode("box", n) for n in ("a", "b", "c"))
    c.setSelected(True)
    assert client.ok("selection", {})["selected"] == [c.path()]

    result = client.ok("selection", {"paths": [a.path(), b.path()]})
    assert sorted(result["selected"]) == sorted([a.path(), b.path()])
    assert not c.isSelected()
    assert sorted(n.path() for n in hou.selectedNodes()) == sorted([a.path(), b.path()])

    # One call is one undo step.
    assert hou.undos.undoLabels()[0].startswith("HocusPocus: selection")

    assert client.ok("selection", {"paths": []})["selected"] == []
    assert hou.selectedNodes() == ()


def test_selection_bad_path(client):
    geo = _geo()
    box = geo.createNode("box")
    box.setSelected(True)
    error = client.error("selection", {"paths": ["/obj/geo1/boxx"]})
    assert error["code"] == "node_not_found"
    assert "/obj/geo1/box1" in error["candidates"]
    # Nothing changed on failure.
    assert box.isSelected()


def test_selection_allowed_read_only(client, host):
    box = _geo().createNode("box")
    host.config.read_only = True
    assert client.ok("selection", {"paths": [box.path()]})["selected"] == [box.path()]


# -- job ---------------------------------------------------------------------------------


def test_fast_cook_leaves_no_job(client):
    box = _geo().createNode("box")
    before = {j["job_id"] for j in client.ok("job", {"action": "list"})["jobs"]}
    result = client.ok("cook", {"paths": [box.path()]})
    assert "job_id" not in result
    after = {j["job_id"] for j in client.ok("job", {"action": "list"})["jobs"]}
    assert after == before


def test_job_errors(client):
    assert client.error("job", {"action": "status", "job_id": "nope"})["code"] == "job_not_found"
    assert client.error("job", {"action": "status"})["code"] == "invalid_argument"
