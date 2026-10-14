"""undo, time, selection and job against real Houdini (bible §4.7, §7)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")

REPO_SRC = Path(__file__).resolve().parents[2] / "src"


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


def test_redo_never_reapplies_a_rolled_back_houdini_python(client):
    """Review 21 papercut 2: the failed call's rollback left it on the redo stack, and
    redo re-created /obj/pyjunk2 from code that had raised."""
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo", "name": "keep"}]})
    code = 'hou.node("/obj").createNode("geo", "pyjunk2")\n1/0'
    error = client.error("houdini_python", {"code": code})
    assert error["code"] == "python_exception" and error["detail"]["rolled_back"] is True
    assert hou.node("/obj/pyjunk2") is None
    history = client.ok("undo", {"action": "history"})
    assert history["redo"] == [] and history["rolled_back"][0].startswith(
        "HocusPocus: houdini_python"
    )
    redo = client.ok("undo", {"action": "redo"})
    assert redo["performed"] == [] and redo["skipped"] == history["rolled_back"]
    assert "rolled back" in redo["note"] and redo["next_redo"] is None
    assert redo["redo_count"] == 0
    assert hou.node("/obj/pyjunk2") is None
    # Undo of the create puts it above the failed call: redo applies it, then stops.
    client.ok("undo", {"action": "undo"})
    assert hou.node("/obj/keep") is None
    again = client.ok("undo", {"action": "redo", "steps": 2})
    assert len(again["performed"]) == 1 and again["performed"][0].startswith(
        "HocusPocus: node_create"
    )
    assert again["skipped"] and hou.node("/obj/keep") is not None
    assert hou.node("/obj/pyjunk2") is None


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


def test_undo_stops_at_a_user_step(client):
    """Review 15 papercut 4: undo {steps} must not undo the user's own work silently."""
    geo = _geo()
    hou.undos.clear()
    client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "box", "name": "a"}]})
    with hou.undos.group("user tweak"):
        geo.parm("tx").set(3)
    client.ok("node_create", {"items": [{"parent": "/obj/geo1", "type": "box", "name": "b"}]})

    result = client.ok("undo", {"action": "undo", "steps": 3})
    assert len(result["performed"]) == 1
    assert result["performed"][0].startswith("HocusPocus: node_create")
    assert result["blocked_by"] == "user tweak"
    assert "include_user_steps" in result["note"]
    assert hou.node("/obj/geo1/b") is None and hou.node("/obj/geo1/a") is not None
    assert geo.parm("tx").eval() == 3
    assert result["next_undo"] == "user tweak"

    # Nothing to do when the newest step is the user's.
    again = client.ok("undo", {"action": "undo"})
    assert again["performed"] == [] and again["blocked_by"] == "user tweak"

    crossed = client.ok("undo", {"action": "undo", "steps": 2, "include_user_steps": True})
    assert crossed["performed"][0] == "user tweak"
    assert crossed["performed"][1].startswith("HocusPocus: node_create")
    assert crossed["user_steps"] == ["user tweak"]
    assert "blocked_by" not in crossed
    assert geo.parm("tx").eval() == 0 and hou.node("/obj/geo1/a") is None

    # Redo is guarded the same way.
    redo = client.ok("undo", {"action": "redo", "steps": 2})
    assert len(redo["performed"]) == 1 and redo["blocked_by"] == "user tweak"


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


# -- quit (houdini_connect {quit}, POST /hp/v1/quit) -----------------------------------------


def _read_line(stream, box):
    box["line"] = stream.readline()


def test_quit_route_checks_unsaved_changes_then_quits(hython, tmp_path):
    """Review 15 papercut 9: a typed quit. A headless host ends its hython."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_SRC)
    env["HOUDINI_USER_PREF_DIR"] = (tmp_path / "prefs" / "houdini__HVER__").as_posix()
    env["HOCUSPOCUS_STATE_DIR"] = str(tmp_path / "state")
    env["HOCUSPOCUS_WORK_DIR"] = str(tmp_path / "work")
    proc = subprocess.Popen(
        [str(hython), "-m", "hocuspocus.host", "--port", "0"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        box: dict = {}
        reader = threading.Thread(target=_read_line, args=(proc.stdout, box), daemon=True)
        reader.start()
        reader.join(120)
        assert "line" in box, "host did not print its JSON line within 120 s"
        info = json.loads(box["line"])
        token = json.loads(Path(info["token_file"]).read_text(encoding="utf-8"))["token"]
        base = f"http://127.0.0.1:{info['port']}/hp/v1"

        def post(path, body):
            request = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=60) as r:
                return json.loads(r.read())

        made = post(
            "/call", {"tool": "node_create", "args": {"items": [{"parent": "/obj", "type": "geo"}]}}
        )
        assert made["ok"] is True
        refused = post("/quit", {})  # on_unsaved defaults to fail
        assert refused["ok"] is False and refused["error"]["code"] == "unsaved_changes"
        assert proc.poll() is None
        bad = post("/quit", {"on_unsaved": "keep"})
        assert bad["ok"] is False and bad["error"]["code"] == "invalid_argument"

        quitting = post("/quit", {"on_unsaved": "discard"})
        assert quitting["ok"] is True, quitting
        assert quitting["result"]["quitting"] is True
        assert quitting["result"]["pid"] == info["pid"]
        assert quitting["result"]["saved"] is False
        code = proc.wait(timeout=60)
        assert code == 0, proc.stderr.read()
        assert not Path(info["token_file"]).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()
