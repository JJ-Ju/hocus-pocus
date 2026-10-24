"""hip_* fixes from review 10: dry runs that change nothing, approved_roots expansion,
backup targets checked before writing, hip_new's declared result."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")


def _fwd(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _saved_scene(client, path: Path, node_name: str = "g1") -> str:
    client.ok("houdini_python", {"code": f"hou.node('/obj').createNode('geo', '{node_name}')"})
    return client.ok("hip_save", {"path": _fwd(path)})["path"]


def test_hip_merge_dry_run_changes_nothing(client, work_dir):
    source = _saved_scene(client, work_dir / "src.hip")
    target = client.ok("hip_save", {"path": _fwd(work_dir / "target.hip")})
    assert target["dirty"] is False
    labels = list(client.host.undo.labels())
    envelope = client.call("hip_merge", {"path": source, "dry_run": True})
    assert envelope["ok"] is True, envelope
    assert envelope["result"]["collisions"] == ["/obj/g1"]
    assert "_changed" not in envelope["result"]
    assert envelope["result"]["dirty"] is False
    assert envelope["_meta"]["undo_label"] is None
    assert client.host.undo.labels() == labels
    assert client.ok("houdini_status")["hip"]["dirty"] is False


def test_hip_merge_dry_run_allowed_in_read_only(client, work_dir):
    source = _saved_scene(client, work_dir / "src.hip")
    client.host.config.read_only = True
    assert client.ok("hip_merge", {"path": source, "dry_run": True})["dry_run"] is True
    assert client.error("hip_merge", {"path": source})["code"] == "read_only"


def test_hip_new_output_schema_matches_result(client):
    from hocuspocus.tools.catalog import get

    schema = get("hip_new").output_schema
    result = client.ok("hip_new")
    assert set(result) <= set(schema["properties"]), set(result) - set(schema["properties"])
    assert schema["properties"]["saved_first"] == {"type": "boolean"}
    assert result["saved_first"] is False


def test_approved_roots_expand_variables_and_home(client, work_dir, monkeypatch):
    allowed = work_dir / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("HP_TEST_ROOT", str(allowed))
    client.host.config.approved_roots = ["$HP_TEST_ROOT"]
    assert client.ok("hip_save", {"path": _fwd(allowed / "a.hip")})["path"].endswith("/a.hip")
    assert client.error("hip_save", {"path": _fwd(work_dir / "b.hip")})["code"] == (
        "path_not_allowed"
    )
    home = Path(os.path.expanduser("~"))
    try:
        rel = allowed.relative_to(home)
    except ValueError:
        pytest.skip("work dir is not under the home directory")
    client.host.config.approved_roots = ["~/" + _fwd(rel)]
    assert client.ok("hip_save", {"path": _fwd(allowed / "c.hip")})["path"].endswith("/c.hip")


def test_approved_roots_compare_real_paths(client, work_dir):
    real = work_dir / "real"
    real.mkdir()
    link = work_dir / "link"
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(real), str(link))
        else:
            os.symlink(real, link)
    except OSError as exc:
        pytest.skip(f"cannot create a link: {exc}")
    # A path through the link resolves into the approved root ...
    client.host.config.approved_roots = [_fwd(real)]
    assert client.ok("hip_save", {"path": _fwd(link / "a.hip")})
    # ... and a root given through the link approves the real location.
    client.host.config.approved_roots = [_fwd(link)]
    assert client.ok("hip_save", {"path": _fwd(real / "b.hip")})
    # A link inside the root that points outside it does not widen the root.
    outside = work_dir / "outside"
    outside.mkdir()
    escape = real / "escape"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(escape))
    else:
        os.symlink(outside, escape)
    client.host.config.approved_roots = [_fwd(real)]
    error = client.error("hip_save", {"path": _fwd(escape / "c.hip")})
    assert error["code"] == "path_not_allowed"


def test_backup_target_checked_before_writing(client, work_dir):
    root = work_dir / "root"
    root.mkdir()
    elsewhere = work_dir / "elsewhere"
    _saved_scene(client, root / "a.hip")
    client.host.config.approved_roots = [_fwd(root)]
    hou.putenv("HOUDINI_BACKUP_DIR", _fwd(elsewhere))
    try:
        error = client.error("hip_save", {"backup": True})
        assert error["code"] == "path_not_allowed"
        assert not elsewhere.exists()
    finally:
        hou.putenv("HOUDINI_BACKUP_DIR", "")
    assert Path(client.ok("hip_save", {"backup": True})["backup_path"]).is_file()


# -- one dirty source in both modes (docs/parity.md G1) ---------------------------------


def _hip_state(client) -> dict:
    hip = client.ok("houdini_status")["hip"]
    return {"dirty": hip["dirty"], "dirty_source": hip["dirty_source"]}


def test_agent_mutation_is_the_tracked_source(client, work_dir):
    client.ok("hip_save", {"path": _fwd(work_dir / "tracked.hip")})
    assert _hip_state(client) == {"dirty": False, "dirty_source": None}
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "null", "name": "n"}]})
    assert _hip_state(client) == {"dirty": True, "dirty_source": "tracked"}
    error = client.error("hip_new", {"on_unsaved": "fail"})
    assert error["code"] == "unsaved_changes"
    assert error["detail"]["dirty_source"] == "tracked"


def test_untitled_scene_hint_leads_with_hip_save(client):
    """Review 25 papercut 9: on an untitled scene on_unsaved: 'save' has nowhere to save,
    so the refusal offers hip_save {path} and discard, not save."""
    assert hou.hipFile.isNewFile()
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "null"}]})
    refused = client.error("hip_new", {})
    assert refused["code"] == "unsaved_changes"
    assert refused["hint"].startswith("The scene is untitled: hip_save {path} saves it")
    assert "on_unsaved: 'save'" not in refused["hint"] and "'discard'" in refused["hint"]
    cannot = client.error("hip_new", {"on_unsaved": "save"})
    assert "nowhere to save" in cannot["message"] and cannot["hint"] == refused["hint"]


def test_user_edit_outside_hocuspocus_dirties_the_scene(client, work_dir):
    """An edit made outside a HocusPocus call (here: on the test's main thread, between
    calls) arrives as an ``origin: other`` event and dirties the scene: hip_new and
    hip_open with on_unsaved: fail refuse, as they do in the GUI."""
    saved = client.ok("hip_save", {"path": _fwd(work_dir / "user.hip")})["path"]
    hou.node("/obj").createNode("null", "made_by_user")
    assert _hip_state(client) == {"dirty": True, "dirty_source": "user_event"}
    for tool, args in (("hip_new", {}), ("hip_open", {"path": saved})):
        error = client.error(tool, {**args, "on_unsaved": "fail"})
        assert error["code"] == "unsaved_changes", tool
        assert error["detail"]["dirty_source"] == "user_event"
        assert "outside HocusPocus" in error["message"]
    assert client.ok("hip_save")["dirty"] is False
    assert _hip_state(client) == {"dirty": False, "dirty_source": None}
    assert client.ok("hip_new", {"on_unsaved": "fail"})["dirty"] is False


def test_reads_and_temporary_nodes_leave_the_scene_clean(client, work_dir):
    """Reads, and the type probe's temporary node, are HocusPocus's own: none of them
    dirties a saved scene (G1)."""
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "g"},
                {"parent": "/obj/g", "type": "box", "flags": {"display": True}},
            ]
        },
    )
    client.ok("hip_save", {"path": _fwd(work_dir / "reads.hip")})
    client.ok("node_type_info", {"type": "Sop/copytopoints", "detail": "full"})
    client.ok("node_find", {"root": "/obj"})
    client.ok("houdini_status")
    assert _hip_state(client) == {"dirty": False, "dirty_source": None}
    assert client.ok("hip_new", {"on_unsaved": "fail"})["saved_first"] is False
