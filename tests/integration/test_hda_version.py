"""``hda version`` and ``hda save`` by type name (BIBLE §4.7, D73; review 26 P3 friction
5: 1.0 to 1.1 took copyToHDAFile under a new name, an install and changeNodeType through
``houdini_python``)."""

from __future__ import annotations

import contextlib

import pytest

hou = pytest.importorskip("hou")

EXT = hou.hda.defaultFileExtension()


@pytest.fixture
def tower(client, tmp_path):
    """An asset hptest::vtower::1.0 with a height parm, a locked instance and an unlocked
    one with an added node; the libraries are uninstalled afterwards."""
    geo = hou.node("/obj").createNode("geo", "city")
    sub = geo.createNode("subnet", "tower")
    sub.createNode("box", "inner")
    library = (tmp_path / "otls" / f"vtower{EXT}").as_posix()
    made = client.ok(
        "hda",
        {
            "action": "create",
            "path": sub.path(),
            "name": "hptest::vtower::1.0",
            "library_path": library,
            "label": "Tower",
            "interface": {"add": [{"name": "height", "type": "float", "default": 5}]},
        },
    )
    locked = hou.node(made["path"])
    client.ok("hda", {"action": "save", "path": locked.path(), "lock": True})
    edited = geo.createNode("hptest::vtower::1.0", "edited")
    edited.allowEditingOfContents()
    edited.createNode("sphere", "added")
    yield {"library": library, "locked": locked, "edited": edited, "dir": tmp_path / "otls"}
    hou.hipFile.clear(suppress_save_prompt=True)
    for path in hou.hda.loadedFiles():
        if "vtower" in path:
            with contextlib.suppress(hou.Error):
                hou.hda.uninstallFile(path)


def test_version_copies_the_definition_and_switches_the_instance(client, tower):
    locked = tower["locked"]
    locked.parm("height").set(9)
    out = client.ok(
        "hda", {"action": "version", "path": locked.path(), "version": "1.1", "switch": "path"}
    )
    assert out["type"] == "Sop/hptest::vtower::1.1" and out["from"] == "Sop/hptest::vtower::1.0"
    assert out["label"] == "Tower" and out["version"] == "1.1"
    assert out["library"].endswith(f"vtower{EXT}") and "installed" not in out
    assert out["switched"] == ["/obj/city/tower"] and out["path"] == "/obj/city/tower"
    node = hou.node("/obj/city/tower")
    assert node.type().name() == "hptest::vtower::1.1" and node.isLockedHDA()
    assert node.evalParm("height") == 9  # parm values kept
    new = node.type().definition()
    assert new.version() == "1.1" and new.description() == "Tower"
    assert [p.name() for p in new.parmTemplateGroup().parmTemplates()] == ["height"]
    assert node.geometry() is not None and len(node.geometry().prims()) == 6  # contents
    # The old version stays, with its other instance; the bare name makes the newest.
    assert hou.nodeType(hou.sopNodeTypeCategory(), "hptest::vtower::1.0") is not None
    assert tower["edited"].type().name() == "hptest::vtower::1.0"
    names = sorted(d.nodeTypeName() for d in hou.hda.definitionsInFile(tower["library"]))
    assert names == ["hptest::vtower::1.0", "hptest::vtower::1.1"]
    assert hou.undos.undoLabels()[0].startswith("HocusPocus: hda version")
    bare = hou.node("/obj/city").createNode("hptest::vtower")
    assert bare.type().name() == "hptest::vtower::1.1"


def test_version_into_another_library_switches_every_instance(client, tower):
    library = (tower["dir"] / f"vtower2{EXT}").as_posix()
    out = client.ok(
        "hda",
        {
            "action": "version",
            "name": "Sop/hptest::vtower::1.0",
            "version": "2.0",
            "library_path": library,
            "label": "Tower 2",
            "switch": "all",
        },
    )
    assert out["installed"] is True and out["label"] == "Tower 2"
    assert out["switched"] == ["/obj/city/edited", "/obj/city/tower"]
    edited = hou.node("/obj/city/edited")
    assert edited.type().name() == "hptest::vtower::2.0"
    # The unlocked instance kept its edits for an hda save, and the result says so.
    assert not edited.isLockedHDA() and edited.node("added") is not None
    assert any("hda save" in note for note in out["notes"])
    saved = client.ok("hda", {"action": "save", "path": edited.path(), "lock": True})
    assert saved["saved"] is True
    fresh = hou.node("/obj/city").createNode("hptest::vtower::2.0", "fresh")
    fresh.cook(force=True)
    assert fresh.node("added") is not None  # the 2.0 definition holds the edit


def test_save_by_name_sets_label_version_and_interface(client, tower):
    out = client.ok(
        "hda",
        {
            "action": "save",
            "name": "Sop/hptest::vtower::1.0",
            "label": "Tower (legacy)",
            "version": "1.0.3",
            "interface": {"change": [{"name": "height", "default": 7}]},
            "help": "= Tower =",
        },
    )
    assert out["changed"] == ["label", "version"] and out["interface"] == {"change": ["height"]}
    assert out["label"] == "Tower (legacy)" and out["version"] == "1.0.3"
    definition = hou.nodeType(hou.sopNodeTypeCategory(), "hptest::vtower::1.0").definition()
    assert definition.description() == "Tower (legacy)" and definition.version() == "1.0.3"
    assert definition.parmTemplateGroup().find("height").defaultValue() == (7.0,)
    assert definition.sections()["HelpText"].contents() == "= Tower ="
    # Written to the library: a reload reads the label back.
    hou.hda.reloadFile(tower["library"])
    reread = hou.nodeType(hou.sopNodeTypeCategory(), "hptest::vtower::1.0").definition()
    assert reread.description() == "Tower (legacy)"


def test_version_refusals(client, tower):
    locked = tower["locked"].path()
    error = client.error("hda", {"action": "version", "path": locked})
    assert error["code"] == "invalid_argument" and "'version'" in error["message"]
    error = client.error("hda", {"action": "version", "path": locked, "version": "1.0"})
    assert "already has version 1.0" in error["message"]
    client.ok("hda", {"action": "version", "path": locked, "version": "1.2"})
    error = client.error("hda", {"action": "version", "path": locked, "version": "1.2"})
    assert error["code"] == "name_collision"
    error = client.error(
        "hda", {"action": "version", "name": "Sop/hptest::vtower::1.0", "version": "3.0",
                "switch": "path"},
    )  # fmt: skip
    assert "switch: path needs path" in error["message"]
    error = client.error("hda", {"action": "save", "name": "Sop/hptest::vtower::1.0", "lock": True})
    assert "lock needs an instance" in error["message"]
    error = client.error("hda", {"action": "info", "path": locked, "switch": "all"})
    assert "switch is for hda version" in error["message"]
    wrong = (tower["dir"] / "vtower3.hda").as_posix() if EXT != ".hda" else None
    if wrong:
        error = client.error(
            "hda",
            {"action": "version", "path": locked, "version": "4.0", "library_path": wrong},
        )
        assert error["candidates"] == [wrong[: -len(".hda")] + EXT]
