"""The 2.1 HDA lifecycle against real Houdini (BIBLE §4.7, D47; review 26 P1 friction 1):
create with an interface and help, save with interface changes and lock, uninstall and
install a library, info, and the licence's library extension. No houdini_python."""

from __future__ import annotations

import os

import pytest

hou = pytest.importorskip("hou")

EXT = hou.hda.defaultFileExtension()  # the extension this licence writes


def _subnet(name: str = "tower"):
    geo = hou.node("/obj").createNode("geo", "geo1")
    sub = geo.createNode("subnet", name)
    sub.createNode("box", "inner")
    return sub


INTERFACE = {
    "add": [
        {"type": "folder", "label": "Massing", "folder_type": "tabs"},
        {"name": "floors", "type": "int", "default": 36, "min": 1, "max": 200,
         "min_strict": True, "folder": "Massing"},
        {"name": "interior", "type": "toggle", "default": True, "folder": "Massing",
         "join_next": True},
        {"name": "core_width", "type": "float", "default": 12, "folder": "Massing",
         "disable_when": "{ interior == 0 }", "help": "Width of the core."},
        {"type": "folder", "label": "Look", "folder_type": "collapsible"},
        {"name": "style", "type": "menu", "folder": "Look", "default": "ribbon",
         "menu_items": [{"token": "armour"}, {"token": "ribbon", "label": "Ribbon"}],
         "tags": {"hp_role": "style"}},
    ]
}  # fmt: skip


def _create(client, tmp_path, name="hptest::tower::1.0", **extra):
    sub = _subnet()
    library = (tmp_path / "otls" / f"tower{EXT}").as_posix()
    args = {"action": "create", "path": sub.path(), "name": name, "library_path": library}
    args.update(extra)
    return client.ok("hda", args), library


def test_create_with_interface_and_help_round_trips_through_the_file(client, tmp_path):
    made, library = _create(
        client, tmp_path, interface=INTERFACE, help="= Tower =\nA tower.", label="Tower"
    )
    assert made["promoted"] == ["core_width", "floors", "interior", "style"]
    assert made["interface"] == {"add": ["hp_massing", "floors", "interior", "core_width",
                                         "hp_look", "style"]}  # fmt: skip
    assert made["help"] is True
    node = hou.node(made["path"])
    assert node.spareParms() == ()  # promoted to the definition
    definition = node.type().definition()
    group = definition.parmTemplateGroup()
    floors = group.find("floors")
    assert floors.defaultValue() == (36,) and floors.minIsStrict()
    assert group.find("interior").joinsWithNext()
    assert group.find("core_width").conditionals() == {
        hou.parmCondType.DisableWhen: "{ interior == 0 }"
    }
    assert group.find("core_width").help() == "Width of the core."
    assert group.findFolder("Look").folderType() == hou.folderType.Collapsible
    assert group.find("style").tags()["hp_role"] == "style"
    assert node.parm("style").evalAsString() == "ribbon"

    # From the file, in a clean load: uninstall (the instance falls back), install.
    out = client.ok("hda", {"action": "uninstall", "library_path": library})
    assert out["action"] == "uninstalled"
    assert out["definitions"][0]["type"] == "hptest::tower::1.0"
    assert made["path"] in out["instances"]
    assert (
        hou.nodeType(hou.sopNodeTypeCategory(), "hptest::tower::1.0") is None
        or out["instances"][made["path"]] != library
    )
    again = client.error("hda", {"action": "uninstall", "library_path": library})
    assert again["code"] == "file_not_found"
    client.ok("hda", {"action": "install", "library_path": library})
    loaded = hou.hda.definitionsInFile(library)[0]
    assert loaded.parmTemplateGroup().find("core_width").conditionals()
    assert "Tower" in loaded.sections()["HelpText"].contents()
    assert loaded.description() == "Tower"


def test_save_changes_the_interface_versions_and_locks(client, tmp_path):
    made, _library = _create(client, tmp_path, interface=INTERFACE)
    path = made["path"]
    hou.node(path).createNode("sphere", "added")
    saved = client.ok(
        "hda",
        {
            "action": "save",
            "path": path,
            "interface": {
                "change": [
                    {"name": "floors", "default": 40, "label": "Floor count"},
                    {"name": "Look", "folder_type": "simple"},
                    {"name": "core_width", "hide_when": "{ interior == 0 }", "before": "floors"},
                ],
                "remove": ["style"],
                "add": [{"name": "seed", "type": "int", "default": 1, "after": "interior"}],
            },
            "version": "1.1",
            "help": "= Tower =\nVersion 1.1.",
            "lock": True,
        },
    )
    assert saved["saved"] is True and saved["hda_locked"] is True
    assert saved["interface"] == {
        "add": ["seed"],
        "change": ["floors", "hp_look", "core_width"],
        "remove": ["style"],
    }
    node = hou.node(path)
    assert node.isLockedHDA() and node.node("added") is not None
    definition = node.type().definition()
    group = definition.parmTemplateGroup()
    assert group.find("floors").defaultValue() == (40,)
    assert group.find("floors").label() == "Floor count"
    assert group.find("style") is None and group.find("seed") is not None
    assert group.findFolder("Look").folderType() == hou.folderType.Simple
    massing = [t.name() for t in group.findFolder("Massing").parmTemplates()]
    assert massing == ["core_width", "floors", "interior", "seed"]
    assert definition.version() == "1.1"
    info = client.ok("hda", {"action": "info", "path": path})
    assert info["type"] == "Sop/hptest::tower::1.0"
    assert info["version"] == "1.1"
    assert "HelpText" in info["sections"] and info["help_chars"] > 0
    assert info["instance"] == {"path": path, "hda_locked": True, "matches_definition": True}
    assert info["interface"]["folders"] == ["Massing", "Look"]
    assert info["instances"] == 1
    by_name = client.ok("hda", {"action": "info", "name": "Sop/hptest::tower::1.0"})
    assert by_name["library"] == info["library"] and "instance" not in by_name
    bare = client.ok("hda", {"action": "info", "name": "hptest::tower::1.0"})
    assert bare["type"] == by_name["type"]


def test_licence_extension_is_enforced(client, tmp_path):
    sub = _subnet()
    wrong = ".hda" if EXT != ".hda" else ".hdalc"
    error = client.error(
        "hda",
        {
            "action": "create",
            "path": sub.path(),
            "name": "hptest::lic::1.0",
            "library_path": (tmp_path / f"lic{wrong}").as_posix(),
        },
    )
    assert error["code"] == "invalid_argument"
    assert error["candidates"] == [(tmp_path / f"lic{EXT}").as_posix()]
    assert EXT in error["message"]
    assert hou.node(sub.path()).type().name() == "subnet"  # nothing changed
    assert not (tmp_path / f"lic{wrong}").exists()


def test_bad_interface_changes_nothing(client, tmp_path):
    sub = _subnet()
    bad = {"add": [{"name": "w", "type": "float", "disable_when": "{ interiro == 0 }"}]}
    error = client.error(
        "hda",
        {
            "action": "create",
            "path": sub.path(),
            "name": "hptest::badif::1.0",
            "library_path": (tmp_path / f"badif{EXT}").as_posix(),
            "interface": bad,
        },
    )
    assert error["code"] == "invalid_value"
    assert "interiro" in error["message"] and "interface.add[0]" in error["message"]
    assert hou.node(sub.path()).spareParms() == ()
    assert hou.nodeType(hou.sopNodeTypeCategory(), "hptest::badif::1.0") is None


def test_info_and_arguments_errors(client, tmp_path):
    assert client.error("hda", {"action": "info"})["code"] == "invalid_argument"
    missing = client.error("hda", {"action": "info", "name": "Sop/hptest::nope"})
    assert missing["code"] == "node_type_not_found"
    builtin = client.error("hda", {"action": "info", "name": "Sop/box"})
    assert builtin["code"] == "invalid_argument"
    made, _library = _create(client, tmp_path)
    lock = client.error("hda", {"action": "match", "path": made["path"], "lock": True})
    assert lock["code"] == "invalid_argument" and "save" in lock["message"]


def test_reads_are_allowed_read_only_and_writes_are_not(client, host, tmp_path):
    made, library = _create(client, tmp_path)
    host.config.read_only = True
    envelope = client.call("hda", {"action": "info", "path": made["path"]})
    assert envelope["ok"] is True
    error = client.error("hda", {"action": "uninstall", "library_path": library})
    assert error["code"] == "read_only"
    assert os.path.normcase(os.path.normpath(library)) in {
        os.path.normcase(os.path.normpath(p)) for p in hou.hda.loadedFiles()
    }


def test_uninstall_respects_approved_roots(client, host, tmp_path):
    _made, library = _create(client, tmp_path)
    host.config.approved_roots = [str(tmp_path / "elsewhere")]
    error = client.error("hda", {"action": "uninstall", "library_path": library})
    assert error["code"] == "path_not_allowed"


def test_save_is_one_undo_step(client, tmp_path):
    made, _library = _create(client, tmp_path, interface=INTERFACE)
    saved = client.ok(
        "hda",
        {"action": "save", "path": made["path"], "interface": {"remove": ["style"]}},
    )
    assert saved["undo_label"].startswith("HocusPocus: hda save")
    assert hou.node(made["path"]).type().definition().parmTemplateGroup().find("style") is None
