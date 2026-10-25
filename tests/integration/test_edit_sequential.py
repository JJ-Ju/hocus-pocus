"""``edit`` 2.1 (review 26 P2): ops checked in order against what the earlier ops left
(BIBLE D56), ``dry_run`` and the run agreeing, ``partial: "stop"`` (D57), the material,
unload and export flags and MaterialX signature menus (D60)."""

from __future__ import annotations

import contextlib

import pytest

hou = pytest.importorskip("hou")


def _children(path: str) -> list[str]:
    return sorted(c.name() for c in hou.node(path).children())


@pytest.fixture
def locked_asset(tmp_path):
    geo = hou.node("/obj").createNode("geo", "a")
    sub = geo.createNode("subnet", "asset")
    sub.createNode("box", "inner")
    library = (tmp_path / f"seq{hou.hda.defaultFileExtension()}").as_posix()
    asset = sub.createDigitalAsset(name="hptest::seq::1.0", hda_file_name=library)
    asset.matchCurrentDefinition()
    assert asset.isLockedHDA()
    yield asset
    with contextlib.suppress(Exception):
        asset.type().definition().destroy()


# -- each op sees what the earlier ops did (P2 friction 1) -------------------------------


def test_unlock_then_create_inside_the_asset(client, locked_asset):
    ops = [
        {"op": "node", "path": locked_asset.path(), "lock": False},
        {"op": "create", "parent": locked_asset.path(), "type": "null", "name": "added"},
    ]
    dry = client.ok("edit", {"ops": ops, "dry_run": True})
    assert dry["plan"][1]["path"] == f"{locked_asset.path()}/added"
    assert locked_asset.isLockedHDA() and locked_asset.node("added") is None  # a dry run
    client.ok("edit", {"ops": ops})
    assert not locked_asset.isLockedHDA() and locked_asset.node("added") is not None


def test_multiparm_count_then_its_instance_parms(client):
    geo = hou.node("/obj").createNode("geo", "g")
    attrib = geo.createNode("attribcreate::2.0", "ac")
    ops = [
        {"op": "set", "path": f"{attrib.path()}/numattr", "multiparm_count": 3},
        {"op": "set", "node": attrib.path(), "parms": {"name3": "seed", "name2": "tier"}},
    ]
    client.ok("edit", {"ops": ops, "dry_run": True})
    assert attrib.parm("numattr").eval() == 1 and attrib.parm("name3") is None
    client.ok("edit", {"ops": ops})
    assert attrib.parm("name3").eval() == "seed"


def test_rename_then_reuse_the_name(client):
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("box", "box1")
    ops = [
        {"op": "node", "path": "/obj/g/box1", "name": "box_old"},
        {"op": "create", "parent": "/obj/g", "type": "sphere", "name": "box1"},
        {"op": "delete", "path": "/obj/g/box_old"},
        {"op": "create", "parent": "/obj/g", "type": "null", "name": "box_old"},
    ]
    dry = client.ok("edit", {"ops": ops, "dry_run": True})
    assert [row["op"] for row in dry["plan"]] == ["node", "create", "delete", "create"]
    assert dry["plan"][2]["paths"] == ["/obj/g/box_old"]
    assert _children("/obj/g") == ["box1"] and geo.node("box1").type().name() == "box"
    client.ok("edit", {"ops": ops})
    assert _children("/obj/g") == ["box1", "box_old"]
    assert geo.node("box1").type().name() == "sphere"


def test_wire_an_output_that_an_earlier_op_made(client):
    """The subnet has a second output only once its second output node exists."""
    geo = hou.node("/obj").createNode("geo", "g")
    ops = [
        {"op": "create", "id": "sub", "parent": "/obj/g", "type": "subnet"},
        {"op": "create", "parent": "$sub", "type": "output", "name": "o0"},
        {
            "op": "create",
            "parent": "$sub",
            "type": "output",
            "name": "o1",
            "parms": {"outputidx": 1},
        },
        {"op": "create", "id": "n", "parent": "/obj/g", "type": "null"},
        {"op": "connect", "from": "$sub", "from_output": 1, "to": "$n"},
    ]
    client.ok("edit", {"ops": ops, "dry_run": True})
    assert geo.children() == ()
    result = client.ok("edit", {"ops": ops})
    null = hou.node(result["ids"]["n"])
    assert null.inputConnections()[0].outputIndex() == 1


def test_dry_run_and_run_agree_on_a_value_only_the_node_knows(client):
    """P1 #4, P2 #20: a dry run passed a token the run refused, and refused one it took."""
    mat = hou.node("/mat")
    ops = [
        {"op": "create", "id": "m", "parent": "/mat", "type": "mtlxmultiply"},
        {"op": "set", "path": "$m/signature", "value": "color3FA"},
    ]
    client.ok("edit", {"ops": ops, "dry_run": True})
    assert mat.children() == ()
    bad = [ops[0], {"op": "set", "path": "$m/signature", "value": "colour3FA"}]
    for dry_run in (True, False):
        error = client.error("edit", {"ops": bad, "dry_run": dry_run})
        assert error["code"] == "invalid_value", error
        assert error["message"].startswith("ops[1].value: ")
        assert "color3FA" in error["candidates"]
    assert mat.children() == ()


def test_a_dry_run_leaves_no_trace(client, host):
    """Check mode: no callback runs, the selection and a deleted node stay, no undo step,
    no dirty flag."""
    geo = hou.node("/obj").createNode("geo", "g")
    keep = geo.createNode("box", "keep")
    other = geo.createNode("null", "other")
    other.setSelected(True, clear_all_selected=True)
    group = other.parmTemplateGroup()
    group.append(
        hou.ButtonParmTemplate(
            "make",
            "Make",
            script_callback="hou.node('/obj').createNode('null', 'pressed')",
            script_callback_language=hou.scriptLanguage.Python,
        )
    )
    other.setParmTemplateGroup(group)
    dirty = host.scene.is_dirty
    before = list(hou.undos.undoLabels())
    result = client.ok(
        "edit",
        {
            "ops": [
                {"op": "delete", "path": keep.path()},
                {"op": "create", "parent": "/obj/g", "type": "sphere", "name": "keep"},
                {"op": "set", "path": f"{other.path()}/make", "press": True},
                {"op": "select", "paths": ["/obj/g/keep"]},
            ],
            "dry_run": True,
        },
    )
    assert [row["op"] for row in result["plan"]] == ["delete", "create", "set", "select"]
    assert hou.node("/obj/pressed") is None
    assert [n.path() for n in hou.selectedNodes()] == [other.path()]
    assert geo.node("keep").type().name() == "box" and keep.name() == "keep"
    assert _children("/obj/g") == ["keep", "other"]
    assert list(hou.undos.undoLabels()) == before
    assert host.scene.is_dirty == dirty


def test_every_problem_is_checked_against_the_earlier_ops(client):
    geo = hou.node("/obj").createNode("geo", "g")
    error = client.error(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "b", "parent": "/obj/g", "type": "box"},
                {"op": "set", "path": "$b/sizex", "value": "big"},
                {"op": "node", "path": "$b", "name": "renamed"},
                {"op": "set", "path": "/obj/g/renamed/sizz", "value": 1},  # sees the rename
                {"op": "create", "parent": "/obj/g", "type": "null", "name": "renamed"},
            ]
        },
    )
    problems = error["detail"]["problems"]
    assert [(p["item"], p["code"]) for p in problems] == [
        (1, "invalid_value"),
        (3, "parm_not_found"),
        (4, "name_collision"),
    ]
    assert error["detail"]["rolled_back"] is True
    assert geo.children() == ()


# -- partial: "stop" (P2 friction 2) -----------------------------------------------------


def test_partial_stop_keeps_the_prefix_and_names_the_failure(client):
    hou.node("/obj").createNode("geo", "g")
    result = client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "a", "parent": "/obj/g", "type": "box"},
                {"op": "create", "id": "b", "parent": "/obj/g", "type": "sphere"},
                {"op": "set", "path": "$b/type", "value": "nope"},
                {"op": "create", "parent": "/obj/g", "type": "null", "name": "never"},
            ],
            "partial": "stop",
        },
    )
    assert result["applied"] == 2
    assert [(f["item"], f["error"]["code"]) for f in result["failed"]] == [(2, "invalid_value")]
    assert result["ids"] == {"a": "/obj/g/box1", "b": "/obj/g/sphere1"}
    assert _children("/obj/g") == ["box1", "sphere1"]


# -- flags and signature menus (P2 friction 7 and 8) ---------------------------------------


def test_material_flag_and_rollback(client):
    result = client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "create",
                    "id": "m",
                    "parent": "/mat",
                    "type": "subnet",
                    "flags": {"material": True},
                },
                {"op": "create", "id": "n", "parent": "/mat", "type": "subnet"},
                {"op": "node", "path": "$n", "flags": {"material": True}},
            ]
        },
    )
    assert hou.node(result["ids"]["m"]).isMaterialFlagSet()
    n = hou.node(result["ids"]["n"])
    assert n.isMaterialFlagSet()
    client.error(
        "edit",
        {
            "ops": [
                {"op": "node", "path": n.path(), "flags": {"material": False}},
                {"op": "set", "path": f"{n.path()}/nope", "value": 1},
            ]
        },
    )
    assert n.isMaterialFlagSet()  # compensated
    geo = hou.node("/obj").createNode("geo", "g")
    box = geo.createNode("box")
    error = client.error(
        "edit", {"ops": [{"op": "node", "path": box.path(), "flags": {"material": True}}]}
    )
    assert error["code"] == "invalid_argument" and "unload" in error["hint"]
    client.ok("edit", {"ops": [{"op": "node", "path": box.path(), "flags": {"unload": True}}]})
    assert box.isUnloadFlagSet()


def test_mtlx_signature_menu_lists_the_definitions_signatures(client):
    node = hou.node("/mat").createNode("mtlxgeompropvalue", "g")
    client.ok(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "vector3"}]}
    )
    assert node.parm("signature").eval() == "vector3"
    client.ok(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "Color 4"}]}
    )
    assert node.parm("signature").eval() == "color4"  # a label resolves to its token
    error = client.error(
        "edit", {"ops": [{"op": "set", "path": f"{node.path()}/signature", "value": "vec3"}]}
    )
    assert error["code"] == "invalid_value"
    assert {"vector3", "boolean", "default"} <= set(error["candidates"])
