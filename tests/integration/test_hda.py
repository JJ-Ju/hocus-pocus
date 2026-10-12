"""hda against real Houdini (bible §4.7, review 04 §A4 "HDAs")."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def _subnet(name: str = "rock"):
    geo = hou.node("/obj").createNode("geo", "geo1")
    sub = geo.createNode("subnet", name)
    sub.createNode("box")
    return sub


def _create(client, tmp_path, name: str, **extra):
    sub = _subnet()
    library = (
        tmp_path / "otls" / f"{name.split('::')[-2] if '::' in name else name}.hda"
    ).as_posix()
    args = {"action": "create", "path": sub.path(), "name": name, "library_path": library}
    args.update(extra)
    return client.ok("hda", args), library


def test_create_save_match_unlock(client, tmp_path):
    result, library = _create(client, tmp_path, "hptest::rock::1.0", label="Rock")
    path = result["path"]
    assert path == "/obj/geo1/rock"
    assert result["type"] == "hptest::rock::1.0"
    assert result["definition"] == "hptest::rock::1.0"
    assert result["library"] == library
    assert result["label"] == "Rock"
    assert result["locked"] is False
    assert result["undo_label"].startswith("HocusPocus: hda create")
    assert (tmp_path / "otls" / "rock.hda").is_file()
    node = hou.node(path)
    assert node.type().definition() is not None

    # Edit the unlocked contents, save the definition, then lock to it.
    node.createNode("sphere", "added")
    saved = client.ok("hda", {"action": "save", "path": path})
    assert saved["saved"] is True
    matched = client.ok("hda", {"action": "match", "path": path})
    assert matched["locked"] is True
    assert hou.node(path).isLockedHDA()
    assert hou.node(f"{path}/added") is not None  # the save captured it

    unlocked = client.ok("hda", {"action": "unlock", "path": path})
    assert unlocked["locked"] is False
    assert not hou.node(path).isLockedHDA()


def test_create_version_field(client, tmp_path):
    result, _ = _create(client, tmp_path, "hptest::pebble", version="2.0")
    assert result["version"] == "2.0"


def test_create_inputs_and_description(client, tmp_path):
    result, _ = _create(
        client,
        tmp_path,
        "hptest::gravel::1.0",
        description="Gravel",
        min_inputs=1,
        max_inputs=2,
    )
    assert result["label"] == "Gravel"
    assert result["inputs"] == {"min": 1, "max": 2}
    node_type = hou.node(result["path"]).type()
    assert (node_type.minNumInputs(), node_type.maxNumInputs()) == (1, 2)
    assert node_type.description() == "Gravel"
    bad = client.error(
        "hda",
        {
            "action": "create",
            "path": hou.node("/obj/geo1").createNode("subnet", "other").path(),
            "name": "hptest::bad::1.0",
            "library_path": (tmp_path / "bad.hda").as_posix(),
            "min_inputs": 3,
            "max_inputs": 1,
        },
    )
    assert bad["code"] == "invalid_argument"
    clash = client.error(
        "hda",
        {
            "action": "create",
            "path": hou.node("/obj/geo1").createNode("subnet", "third").path(),
            "name": "hptest::bad2::1.0",
            "library_path": (tmp_path / "bad2.hda").as_posix(),
            "label": "A",
            "description": "B",
        },
    )
    assert clash["code"] == "invalid_argument"


def test_create_name_collision(client, tmp_path):
    _create(client, tmp_path, "hptest::dup::1.0")
    other = hou.node("/obj/geo1").createNode("subnet", "other")
    error = client.error(
        "hda",
        {
            "action": "create",
            "path": other.path(),
            "name": "hptest::dup::1.0",
            "library_path": (tmp_path / "dup2.hda").as_posix(),
        },
    )
    assert error["code"] == "name_collision"
    assert error["hint"]


def test_create_requires_fields(client):
    error = client.error("hda", {"action": "create", "path": "/obj"})
    assert error["code"] == "invalid_argument"
    assert "name" in error["message"]
    assert "library_path" in error["hint"]
    error = client.error("hda", {"action": "install"})
    assert error["code"] == "invalid_argument"
    assert "library_path" in error["message"]
    error = client.error("hda", {"action": "publish"})
    assert error["code"] == "invalid_argument"
    assert "create" in error["candidates"]


def test_create_rejects_non_subnet(client, tmp_path):
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box")
    error = client.error(
        "hda",
        {
            "action": "create",
            "path": box.path(),
            "name": "hptest::boxasset",
            "library_path": (tmp_path / "b.hda").as_posix(),
        },
    )
    assert error["code"] == "invalid_argument"
    assert "subnet" in error["hint"]


def test_save_on_plain_node(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    error = client.error("hda", {"action": "save", "path": geo.path()})
    assert error["code"] == "invalid_argument"
    error = client.error("hda", {"action": "unlock", "path": "/obj/nope"})
    assert error["code"] == "node_not_found"


def test_approved_roots(client, host, tmp_path):
    sub = _subnet()
    host.config.approved_roots = [str(tmp_path / "allowed")]
    error = client.error(
        "hda",
        {
            "action": "create",
            "path": sub.path(),
            "name": "hptest::outside",
            "library_path": (tmp_path / "elsewhere" / "x.hda").as_posix(),
        },
    )
    assert error["code"] == "path_not_allowed"
    assert hou.node(sub.path()).type().name() == "subnet"


def test_install_reload_list(client, tmp_path):
    _result, library = _create(client, tmp_path, "hptest::stone::1.0")
    reloaded = client.ok("hda", {"action": "reload", "library_path": library})
    assert reloaded["action"] == "reloaded"
    assert [d["type"] for d in reloaded["definitions"]] == ["hptest::stone::1.0"]
    assert reloaded["definitions"][0]["category"] == "Sop"

    installed = client.ok("hda", {"action": "install", "library_path": library})
    assert installed["action"] == "installed"

    listing = client.ok("hda", {"action": "list", "limit": 1000})
    assert listing["total"] == len(listing["libraries"])
    assert "next_cursor" not in listing
    ours = [row for row in listing["libraries"] if row["path"].lower() == library.lower()]
    assert ours and "hptest::stone::1.0" in ours[0]["types"]
    # User libraries come before Houdini's own.
    flags = [bool(row.get("builtin")) for row in listing["libraries"]]
    assert flags == sorted(flags)
    # Paged by limit and cursor (bible §4.1).
    first = client.ok("hda", {"action": "list", "limit": 1})
    assert len(first["libraries"]) == 1 and first["total"] == listing["total"]
    if listing["total"] > 1:
        assert first["next_cursor"] == "1"
        second = client.ok("hda", {"action": "list", "limit": 1, "cursor": first["next_cursor"]})
        assert second["libraries"][0] == listing["libraries"][1]

    one = client.ok("hda", {"action": "list", "library_path": library})
    assert one["total"] == 1
    assert one["definitions"][0]["type"] == "hptest::stone::1.0"


def test_install_missing_file(client, tmp_path):
    error = client.error(
        "hda", {"action": "install", "library_path": (tmp_path / "no.hda").as_posix()}
    )
    assert error["code"] == "file_not_found"
    error = client.error(
        "hda", {"action": "install", "library_path": (tmp_path / "x.txt").as_posix()}
    )
    assert error["code"] == "invalid_argument"


def test_list_does_not_dirty_or_need_write(client, host):
    host.scene.mark_clean()
    host.config.read_only = True
    envelope = client.call("hda", {"action": "list"})
    assert envelope["ok"] is True
    assert envelope["_meta"]["undo_label"] is None
    assert host.scene.dirty is False
    error = client.error("hda", {"action": "unlock", "path": "/obj"})
    assert error["code"] == "read_only"


def test_create_is_one_undo_step(client, tmp_path):
    result, _ = _create(client, tmp_path, "hptest::undoable::1.0")
    assert hou.node(result["path"]).type().name() == "hptest::undoable::1.0"
    undone = client.ok("undo", {"action": "undo"})
    assert undone["performed"][0].startswith("HocusPocus: hda create")
    assert hou.node("/obj/geo1/rock").type().name() == "subnet"


def test_list_library_path_is_checked(client, host, tmp_path):
    _result, library = _create(client, tmp_path, "hptest::listed::1.0")
    host.config.approved_roots = [str(tmp_path / "allowed")]
    error = client.error("hda", {"action": "list", "library_path": library})
    assert error["code"] == "path_not_allowed"
    host.config.approved_roots = []
    hip = tmp_path / "scene.hip"
    hip.write_text("not an asset", encoding="utf-8")
    error = client.error("hda", {"action": "list", "library_path": hip.as_posix()})
    assert error["code"] == "invalid_argument"
