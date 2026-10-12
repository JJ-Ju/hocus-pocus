"""network_describe / network_build against real Houdini (docs/BIBLE.md §4.4, §5.10)."""

from __future__ import annotations

import json

import pytest

hou = pytest.importorskip("hou")


def make_five_chain(name: str = "geo1"):
    """box -> xform (expression) -> mountain (locked HDA) -> merge <- sphere, OUT null."""
    geo = hou.node("/obj").createNode("geo", name)
    box = geo.createNode("box", "box1")
    xform = geo.createNode("xform", "xform1")
    xform.setInput(0, box)
    xform.parm("ty").setExpression("$F*0.1")
    xform.parm("sx").set(2)
    mountain = geo.createNode("mountain", "mountain1")
    mountain.setInput(0, xform)
    sphere = geo.createNode("sphere", "sphere1")
    merge = geo.createNode("merge", "merge1")
    merge.setInput(0, mountain)
    merge.setInput(1, sphere)
    merge.setDisplayFlag(True)
    merge.setRenderFlag(True)
    geo.layoutChildren()
    mountain.cook(force=True)  # loads the locked asset's contents
    return geo


def strip_positions(data):
    out = {}
    for name, entry in data.items():
        entry = {k: v for k, v in entry.items() if k != "position"}
        if isinstance(entry.get("children"), dict):
            entry["children"] = strip_positions(entry["children"])
        out[name] = entry
    return out


# -- network_describe --------------------------------------------------------------


def test_describe_chain_is_compact(client, capsys):
    make_five_chain()
    result = client.ok("network_describe", {"root": "/obj/geo1"})
    data = result["data"]
    assert result["format"] == "data" and result["node_count"] == 5
    assert list(data) == ["box1", "xform1", "mountain1", "sphere1", "merge1"]
    assert all("position" not in entry for entry in data.values())
    assert data["xform1"]["parms"]["t"][1] == {"expression": "$F*0.1"}
    assert data["xform1"]["inputs"] == [{"from": "box1", "from_index": 0, "to_index": 0}]
    assert data["merge1"]["flags"] == {"display": True, "render": True}
    assert data["mountain1"]["locked"] is True and "children" not in data["mountain1"]
    size = len(json.dumps(data, separators=(",", ":")))
    assert result["bytes"] == size
    assert size < 2000, size
    with capsys.disabled():
        print(f"\n[network_describe] 5-node chain: {size} bytes (data, compact JSON)")


def test_describe_positions_depth_and_locked(client):
    geo = make_five_chain()
    subnet = geo.createNode("subnet", "sub1")
    subnet.createNode("null", "inner")
    shallow = client.ok("network_describe", {"root": "/obj/geo1"})
    assert "children" not in shallow["data"]["sub1"]
    deep = client.ok(
        "network_describe", {"root": "/obj/geo1", "depth": 2, "include_positions": True}
    )
    assert "inner" in deep["data"]["sub1"]["children"]
    assert "position" in deep["data"]["box1"]
    assert "children" not in deep["data"]["mountain1"]
    opened = client.ok(
        "network_describe", {"root": "/obj/geo1", "depth": 2, "recurse_locked": True}
    )
    assert opened["data"]["mountain1"]["children"]
    assert opened["data"]["mountain1"]["locked"] is True
    error = client.error("network_describe", {"root": "/obj/geo1/mountain1"})
    assert error["code"] == "locked" and "recurse_locked" in error["hint"]


def test_describe_python_and_defaults(client):
    make_five_chain()
    code = client.ok("network_describe", {"root": "/obj/geo1/xform1", "format": "python"})
    assert code["format"] == "python" and 'createNode("xform"' in code["code"]
    full = client.ok("network_describe", {"root": "/obj/geo1", "include_defaults": True})
    assert len(full["data"]["box1"].get("parms", {})) > 3


def test_describe_object_level_trims_render_properties(client):
    make_five_chain()
    hou.node("/obj/geo1").parm("vm_rendersubd").set(1)
    result = client.ok("network_describe", {"root": "/obj"})
    entry = result["data"]["geo1"]
    text = json.dumps(entry)
    assert "vm_rendersubd" in text  # kept: it has a non-default value
    assert "vm_osd_quality" not in text  # trimmed: default render property
    assert result["bytes"] < 4000, result["bytes"]


def test_describe_not_found(client):
    error = client.error("network_describe", {"root": "/obj/nope"})
    assert error["code"] == "node_not_found" and error["hint"]


# -- network_build -----------------------------------------------------------------


def test_build_round_trip(client):
    make_five_chain()
    before = client.ok("network_describe", {"root": "/obj/geo1"})
    hou.node("/obj").createNode("geo", "copy")
    built = client.ok("network_build", {"parent": "/obj/copy", "data": before["data"]})
    assert built["created"] == [f"/obj/copy/{n}" for n in before["data"]]
    assert all("errors" in block for block in built["nodes"])
    after = client.ok("network_describe", {"root": "/obj/copy"})
    assert strip_positions(after["data"]) == strip_positions(before["data"])
    assert hou.node("/obj/copy/xform1").parm("ty").expression() == "$F*0.1"


def test_build_dry_run_and_tag(client):
    hou.node("/obj").createNode("geo", "g")
    data = {
        "box1": {"type": "box"},
        "copy1": {"type": "copytopoints", "inputs": [{"from": "box1"}]},
        "merge1": {
            "type": "merge",
            "inputs": [{"from": "box1"}, {"from": "copy1"}],
            "flags": {"display": True},
        },
    }
    plan = client.ok("network_build", {"parent": "/obj/g", "data": data, "dry_run": True})
    assert plan["dry_run"] is True
    # hou.data type names are exact (an old-version node round-trips as itself).
    assert [p["type"] for p in plan["plan"]] == ["box", "copytopoints", "merge"]
    assert hou.node("/obj/g").children() == ()
    built = client.ok("network_build", {"parent": "/obj/g", "data": data, "tag": "t1"})
    merge = hou.node("/obj/g/merge1")
    assert [n.name() for n in merge.inputs()] == ["box1", "copy1"]  # to_index filled by position
    assert hou.node("/obj/g/copy1").type().name() == "copytopoints"
    assert merge.isDisplayFlagSet()
    assert merge.userData("hocuspocus:tag") == "t1"
    assert built["created_count"] == 3


def test_build_validation_errors(client):
    hou.node("/obj").createNode("geo", "g")
    error = client.error("network_build", {"parent": "/obj/g", "data": {"a": {"type": "boxx"}}})
    assert error["code"] == "node_type_not_found" and "box" in error["candidates"]
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {"a": {"type": "xform", "inputs": [{"from": "bx"}]}, "bx1": {"type": "box"}},
        },
    )
    assert error["code"] == "node_not_found" and "bx1" in error["candidates"]
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {
                "b": {"type": "box"},
                "x": {"type": "xform", "inputs": [{"from": "b", "to_index": 4}]},
                "y": {"type": "nope"},
            },
        },
    )
    assert error["code"] == "invalid_input" and error["hint"]
    assert len(error["detail"]["problems"]) == 2
    error = client.error(
        "network_build", {"parent": "/obj/g", "data": {"bad name": {"type": "box"}}}
    )
    assert error["code"] == "invalid_argument"
    assert hou.node("/obj/g").children() == ()


def test_build_unknown_parm_rolls_back(client):
    hou.node("/obj").createNode("geo", "g")
    keep = hou.node("/obj/g").createNode("null", "keep")
    keep.setDisplayFlag(True)
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {
                "b": {"type": "box", "parms": {"sizze": [1, 2, 3]}, "flags": {"display": True}}
            },
        },
    )
    assert error["code"] == "parm_not_found" and "size" in error["candidates"]
    assert [c.name() for c in hou.node("/obj/g").children()] == ["keep"]
    assert keep.isDisplayFlagSet()


def test_build_name_collisions(client):
    geo = hou.node("/obj").createNode("geo", "g")
    old_box = geo.createNode("box", "box1")
    consumer = geo.createNode("null", "OUT")
    consumer.setInput(0, old_box)
    data = {"box1": {"type": "sphere"}, "x": {"type": "xform", "inputs": [{"from": "box1"}]}}
    error = client.error("network_build", {"parent": "/obj/g", "data": data})
    assert error["code"] == "name_collision" and error["candidates"] and error["hint"]
    assert [c.name() for c in geo.children()] == ["box1", "OUT"]

    renamed = client.ok(
        "network_build", {"parent": "/obj/g", "data": data, "on_name_collision": "rename"}
    )
    new_name = renamed["renamed"]["/obj/g/box1"]
    assert hou.node(new_name).type().name() == "sphere"
    assert hou.node("/obj/g/x").inputs()[0].path() == new_name
    assert hou.node("/obj/g/box1").type().name() == "box"

    replaced = client.ok(
        "network_build",
        {"parent": "/obj/g", "data": {"box1": {"type": "torus"}}, "on_name_collision": "replace"},
    )
    assert replaced["replaced"] == ["/obj/g/box1"]
    assert hou.node("/obj/g/box1").type().name() == "torus"
    assert consumer.inputs()[0].path() == "/obj/g/box1"  # downstream wire moved to the new node
    assert not [c for c in geo.children() if "hp_replaced" in c.name()]


def test_build_refuses_locked_parent(client):
    geo = make_five_chain()
    error = client.error(
        "network_build", {"parent": "/obj/geo1/mountain1", "data": {"n": {"type": "null"}}}
    )
    assert error["code"] == "locked" and error["hint"]
    assert hou.node("/obj/geo1/mountain1").isLockedHDA()
    assert geo.node("mountain1").children()


def test_build_ignores_locked_children_from_recurse_locked(client):
    make_five_chain()
    described = client.ok(
        "network_describe", {"root": "/obj/geo1", "depth": 2, "recurse_locked": True}
    )
    hou.node("/obj").createNode("geo", "copy")
    built = client.ok("network_build", {"parent": "/obj/copy", "data": described["data"]})
    assert any("mountain1" in w for w in built["warnings"])
    assert hou.node("/obj/copy/mountain1").isLockedHDA()


def test_build_subnet_children(client):
    hou.node("/obj").createNode("geo", "g")
    data = {"sub": {"type": "subnet", "children": {"a": {"type": "box"}, "b": {"type": "nope"}}}}
    error = client.error("network_build", {"parent": "/obj/g", "data": data})
    assert error["code"] == "node_type_not_found" and error["detail"]["problems"][0]["at"].endswith(
        "sub/b"
    )
    data["sub"]["children"]["b"] = {"type": "xform", "inputs": [{"from": "a"}]}
    built = client.ok("network_build", {"parent": "/obj/g", "data": data})
    assert built["created_count"] == 3
    assert hou.node("/obj/g/sub/b").inputs()[0].path() == "/obj/g/sub/a"
