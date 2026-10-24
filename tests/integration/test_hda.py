"""hda against real Houdini (bible §4.7, review 04 §A4 "HDAs")."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")

# The library extension this licence writes (D47: .hdalc on Indie, .hda on Commercial).
EXT = hou.hda.defaultFileExtension()


def _subnet(name: str = "rock"):
    geo = hou.node("/obj").createNode("geo", "geo1")
    sub = geo.createNode("subnet", name)
    sub.createNode("box")
    return sub


def _create(client, tmp_path, name: str, **extra):
    sub = _subnet()
    library = (
        tmp_path / "otls" / f"{name.split('::')[-2] if '::' in name else name}{EXT}"
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
    assert result["hda_locked"] is False and "locked" not in result
    assert result["undo_label"].startswith("HocusPocus: hda create")
    assert (tmp_path / "otls" / f"rock{EXT}").is_file()
    node = hou.node(path)
    assert node.type().definition() is not None

    # Edit the unlocked contents, save the definition, then lock to it.
    node.createNode("sphere", "added")
    saved = client.ok("hda", {"action": "save", "path": path})
    assert saved["saved"] is True
    matched = client.ok("hda", {"action": "match", "path": path})
    assert matched["hda_locked"] is True
    assert hou.node(path).isLockedHDA()
    assert hou.node(f"{path}/added") is not None  # the save captured it

    unlocked = client.ok("hda", {"action": "unlock", "path": path})
    assert unlocked["hda_locked"] is False
    assert not hou.node(path).isLockedHDA()


def test_create_version_field(client, tmp_path):
    result, _ = _create(client, tmp_path, "hptest::pebble", version="2.0", label="HP Pebble")
    assert result["version"] == "2.0"
    # Review 15 papercut 8: the same version, label and type spelling everywhere.
    info = client.ok("node_type_info", {"type": "Sop/hptest::pebble", "include_parms": False})
    assert info["type"] == "Sop/hptest::pebble"
    assert info["version"] == "2.0"
    assert info["label"] == "HP Pebble" and info["description"] == "HP Pebble"
    found = client.ok("node_type_search", {"query": "hptest::pebble", "category": "Sop"})
    row = next(r for r in found["results"] if r["name"] == "hptest::pebble")
    assert row["version"] == "2.0" and row["description"] == "HP Pebble"
    listed = client.ok("hda", {"action": "list", "library_path": result["library"]})
    assert listed["definitions"][0]["version"] == "2.0"
    assert listed["definitions"][0]["label"] == "HP Pebble"


def test_save_promotes_spare_parms(client, tmp_path):
    """Review 15 papercut 6: a spare parm added to the unlocked instance reaches the
    asset's interface on save."""
    result, _ = _create(client, tmp_path, "hptest::meteors::1.0")
    path = result["path"]
    client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "node",
                    "path": path,
                    "spare_parms": {
                        "add": [{"name": "speed_scale", "type": "float", "default": 1}]
                    },
                }
            ]
        },
    )
    hou.parm(f"{path}/speed_scale").set(2.5)
    saved = client.ok("hda", {"action": "save", "path": path})
    assert saved["promoted"] == ["speed_scale"]
    assert "hda match" in saved["note"]
    node = hou.node(path)
    assert node.spareParms() == ()
    assert node.parm("speed_scale").eval() == 2.5
    info = client.ok("node_type_info", {"type": "Sop/hptest::meteors::1.0"})
    names = [row[0] for rows in info["parms"].values() for row in rows]
    assert "speed_scale" in names
    client.ok("hda", {"action": "match", "path": path})
    assert hou.node(path).parm("speed_scale") is not None


def test_save_can_keep_spare_parms_on_the_instance(client, tmp_path):
    result, _ = _create(client, tmp_path, "hptest::local::1.0")
    node = hou.node(result["path"])
    node.addSpareParmTuple(hou.FloatParmTemplate("local", "Local", 1))
    saved = client.ok("hda", {"action": "save", "path": node.path(), "promote_spare_parms": False})
    assert "promoted" not in saved
    assert [p.name() for p in node.spareParms()] == ["local"]
    assert node.type().definition().parmTemplateGroup().find("local") is None


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
            "library_path": (tmp_path / f"bad{EXT}").as_posix(),
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
            "library_path": (tmp_path / f"bad2{EXT}").as_posix(),
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
            "library_path": (tmp_path / f"dup2{EXT}").as_posix(),
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
            "library_path": (tmp_path / f"b{EXT}").as_posix(),
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
            "library_path": (tmp_path / "elsewhere" / f"x{EXT}").as_posix(),
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
    assert installed["already_loaded"] is True

    listing = client.ok("hda", {"action": "list", "limit": 1000})
    assert listing["total"] == len(listing["libraries"])
    # No 8.3 short names (C:/PROGRA~1/...) for Houdini's own libraries.
    assert not [row["path"] for row in listing["libraries"] if "~" in row["path"]]
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
        "hda", {"action": "install", "library_path": (tmp_path / f"no{EXT}").as_posix()}
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
