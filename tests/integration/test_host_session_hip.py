"""houdini_status / session_info and the hip_* tools against real Houdini."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")


def _fwd(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _make_dirty(client) -> None:
    client.ok("houdini_python", {"code": "hou.node('/obj').createNode('geo', 'dirty_geo')"})


def _save_scene_with(client, path: Path, node_name: str = "g1") -> str:
    client.ok("houdini_python", {"code": f"hou.node('/obj').createNode('geo', '{node_name}')"})
    return client.ok("hip_save", {"path": _fwd(path)})["path"]


# -- status -----------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["houdini_status", "session_info"])
def test_status_fields(client, tool):
    result = client.ok(tool)
    assert result["pid"] == os.getpid()
    assert result["port"] == client.port
    assert result["houdini"] == hou.applicationVersionString()
    assert result["ui"] is False
    hip = result["hip"]
    assert set(hip) >= {"path", "name", "dirty", "is_new", "recent"}
    assert hip["name"] == "untitled.hip"
    assert hip["is_new"] is True
    assert hip["dirty"] is False
    assert isinstance(hip["recent"], list)
    time_block = result["time"]
    assert time_block["fps"] == hou.fps()
    assert time_block["frame"] == hou.frame()
    assert time_block["range"] == list(hou.playbar.frameRange())
    assert set(result["env"]) == {"HIP", "JOB", "HIPNAME"}
    assert result["env"]["HIPNAME"] == "untitled"
    assert result["scene_generation"] == client.host.scene.generation
    assert result["host_version"]
    assert result["allow_python"] is True and result["read_only"] is False


def test_recent_files_from_file_history(client, hp_dirs):
    history = hp_dirs["prefs"] / "file.history"
    client.host.scene.recent.clear()  # files saved or loaded by earlier tests
    history.write_text("HIP\n{\nC:/a/old.hip\nC:/a/new.hip\n}\nOBJ\n{\nC:/x.obj\n}\n")
    try:
        assert client.ok("houdini_status")["hip"]["recent"] == ["C:/a/new.hip", "C:/a/old.hip"]
    finally:
        history.unlink()


def test_recent_and_dirty_without_houdini_status(client, work_dir):
    """Review 07 papercut 9: mutations report dirty, and recent lists the files saved and
    loaded in this session although hython never writes file.history."""
    first = (work_dir / "first.hip").as_posix()
    second = (work_dir / "second.hip").as_posix()
    client.ok("hip_save", {"path": first})
    created = client.ok("node_create", {"items": [{"parent": "/obj", "type": "geo"}]})
    assert created["dirty"] is True
    client.ok("hip_save", {"path": second})
    assert client.ok("parm_set", {"items": [{"path": "/obj/geo1/tx", "value": 1}]})["dirty"] is True
    client.ok("hip_open", {"path": first, "on_unsaved": "discard"})
    recent = client.ok("houdini_status")["hip"]["recent"]
    assert recent[:2] == [first, second], recent


# -- hip_save -----------------------------------------------------------------------


def test_hip_save_as_returns_real_path_and_clean_state(client, work_dir):
    target = work_dir / "nested" / "dir" / "shot.hip"
    _make_dirty(client)
    assert client.ok("houdini_status")["hip"]["dirty"] is True
    result = client.ok("hip_save", {"path": _fwd(target)})
    assert result["path"] == _fwd(target)
    assert result["name"] == "shot.hip"
    assert result["dirty"] is False
    assert result["is_new"] is False
    assert result["bytes"] == target.stat().st_size > 0
    status = client.ok("houdini_status")["hip"]
    assert status["path"] == _fwd(target)
    assert status["dirty"] is False


def test_hip_save_untitled_without_path_fails_with_hint(client):
    error = client.error("hip_save")
    assert error["code"] == "invalid_argument"
    assert "path" in error["hint"]


def test_hip_save_increment_and_backup(client, work_dir):
    _save_scene_with(client, work_dir / "inc.hip")
    result = client.ok("hip_save", {"increment": True})
    assert result["path"] == _fwd(work_dir / "inc1.hip")
    assert (work_dir / "inc1.hip").is_file()
    result = client.ok("hip_save", {"backup": True})
    assert result["path"] == _fwd(work_dir / "inc1.hip")
    assert Path(result["backup_path"]).is_file()


def test_hip_save_respects_approved_roots(client, work_dir):
    client.host.config.approved_roots = [_fwd(work_dir / "allowed")]
    error = client.error("hip_save", {"path": _fwd(work_dir / "elsewhere" / "x.hip")})
    assert error["code"] == "path_not_allowed"
    assert "allowed" in error["hint"]
    ok = client.ok("hip_save", {"path": _fwd(work_dir / "allowed" / "x.hip")})
    assert ok["path"].endswith("/allowed/x.hip")


# -- hip_new --------------------------------------------------------------------------


def test_hip_new_refuses_unsaved_then_discards(client):
    _make_dirty(client)
    error = client.error("hip_new")
    assert error["code"] == "unsaved_changes"
    assert "discard" in error["hint"]
    assert hou.node("/obj/dirty_geo") is not None
    result = client.ok("hip_new", {"on_unsaved": "discard"})
    assert hou.node("/obj/dirty_geo") is None
    assert result["is_new"] is True
    assert result["dirty"] is False


def test_hip_new_on_clean_scene_succeeds(client):
    assert client.ok("hip_new")["is_new"] is True


def test_hip_new_save_first(client, work_dir):
    path = _save_scene_with(client, work_dir / "keep.hip")
    _make_dirty(client)
    result = client.ok("hip_new", {"on_unsaved": "save"})
    assert result["saved_first"] is True
    client.ok("hip_open", {"path": path})
    assert hou.node("/obj/dirty_geo") is not None


def test_hip_new_save_first_untitled_fails(client):
    _make_dirty(client)
    error = client.error("hip_new", {"on_unsaved": "save"})
    assert error["code"] == "unsaved_changes"
    assert "hip_save" in error["hint"]


# -- hip_open -------------------------------------------------------------------------


def test_hip_open_bumps_generation_and_reports(client, work_dir):
    path = _save_scene_with(client, work_dir / "open_me.hip", "opened_geo")
    client.ok("hip_new", {"on_unsaved": "discard"})
    before = client.host.scene.generation
    envelope = client.call("hip_open", {"path": path})
    assert envelope["ok"] is True, envelope
    result = envelope["result"]
    assert result["path"] == path
    assert result["warnings"] == []
    assert result["dirty"] is False
    assert result["scene_generation"] > before
    assert envelope["_meta"]["scene_generation"] == result["scene_generation"]
    assert hou.node("/obj/opened_geo") is not None


def test_hip_open_reports_load_warnings(client, work_dir):
    path = _save_scene_with(client, work_dir / "good.hip", "warn_geo")
    broken = work_dir / "warn.hip"
    data = Path(path).read_bytes()
    assert b"type = geo" in data
    broken.write_bytes(data.replace(b"type = geo", b"type = zzz"))
    result = client.ok("hip_open", {"path": _fwd(broken), "on_unsaved": "discard"})
    assert result["path"] == _fwd(broken)
    assert any("Bad node type found: zzz" in w for w in result["warnings"]), result["warnings"]


def test_hip_open_strict_warnings_fail_but_scene_is_loaded(client, work_dir):
    path = _save_scene_with(client, work_dir / "good2.hip", "warn_geo")
    broken = work_dir / "warn2.hip"
    broken.write_bytes(Path(path).read_bytes().replace(b"type = geo", b"type = zzz"))
    error = client.error(
        "hip_open", {"path": _fwd(broken), "on_unsaved": "discard", "ignore_load_warnings": False}
    )
    assert error["code"] == "invalid_value"
    assert error["detail"]["warnings"]
    assert hou.hipFile.path() == _fwd(broken)


def test_hip_open_missing_file(client, work_dir):
    (work_dir / "shot_v001.hip").write_bytes(b"")
    error = client.error("hip_open", {"path": _fwd(work_dir / "shot_v01.hip")})
    assert error["code"] == "file_not_found"
    assert _fwd(work_dir / "shot_v001.hip") in error["candidates"]


def test_hip_open_refuses_unsaved(client, work_dir):
    path = _save_scene_with(client, work_dir / "a.hip")
    _make_dirty(client)
    error = client.error("hip_open", {"path": path})
    assert error["code"] == "unsaved_changes"


def test_hip_open_outside_approved_roots(client, work_dir):
    path = _save_scene_with(client, work_dir / "outside.hip")
    client.host.config.approved_roots = [_fwd(work_dir / "only_here")]
    error = client.error("hip_open", {"path": path, "on_unsaved": "discard"})
    assert error["code"] == "path_not_allowed"


# -- hip_merge ------------------------------------------------------------------------


def test_hip_merge_dry_run_and_merge(client, work_dir):
    path = _save_scene_with(client, work_dir / "merge_src.hip", "g1")
    client.ok("hip_new", {"on_unsaved": "discard"})
    client.ok("houdini_python", {"code": "hou.node('/obj').createNode('geo', 'g1')"})
    dry = client.ok("hip_merge", {"path": path, "dry_run": True})
    assert dry["dry_run"] is True
    assert dry["collisions"] == ["/obj/g1"]
    assert [n.path() for n in hou.node("/obj").children()] == ["/obj/g1"]

    before = client.host.scene.generation
    merged = client.ok("hip_merge", {"path": path})
    assert merged["collisions"] == ["/obj/g1"]
    assert merged["merged_count"] == 1
    assert len(hou.node("/obj").children()) == 2
    assert merged["merged"][0] in [n.path() for n in hou.node("/obj").children()]
    assert merged["scene_generation"] > before
