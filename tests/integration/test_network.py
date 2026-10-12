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
    assert data["mountain1"]["hda_locked"] is True and "children" not in data["mountain1"]
    assert "locked" not in data["mountain1"]  # locked is the SOP lock flag (BIBLE §4.1)
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
    assert opened["data"]["mountain1"]["hda_locked"] is True
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


# -- review 10 / 11 fixes ----------------------------------------------------------


def test_build_dry_run_changes_nothing_even_read_only(client, host):
    hou.node("/obj").createNode("geo", "g")
    host.scene.mark_clean()
    data = {"box1": {"type": "box"}, "x": {"type": "xform", "inputs": [{"from": "box1"}]}}
    envelope = client.call("network_build", {"parent": "/obj/g", "data": data, "dry_run": True})
    assert envelope["ok"] is True, envelope
    assert envelope["_meta"]["undo_label"] is None
    assert envelope["result"].get("dirty") in (None, False)
    assert "_changed" not in envelope["result"]
    assert host.scene.dirty is False
    host.config.read_only = True
    plan = client.ok("network_build", {"parent": "/obj/g", "data": data, "dry_run": True})
    assert plan["dry_run"] is True and plan["node_count"] == 2
    refused = client.error("network_build", {"parent": "/obj/g", "data": data})
    assert refused["code"] == "read_only"
    assert hou.node("/obj/g").children() == ()


def test_build_validates_from_index_and_duplicate_to_index(client):
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("box", "existing")
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {
                "b": {"type": "box"},
                "x": {"type": "xform", "inputs": [{"from": "b", "from_index": 3}]},
                "y": {"type": "xform", "inputs": [{"from": "existing", "from_index": 1}]},
            },
        },
    )
    assert error["code"] == "invalid_input"
    problems = error["detail"]["problems"]
    assert len(problems) == 2 and all("output" in p["message"] for p in problems)
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {
                "b": {"type": "box"},
                "s": {"type": "sphere"},
                "m": {
                    "type": "merge",
                    "inputs": [{"from": "b", "to_index": 0}, {"from": "s", "to_index": 0}],
                },
            },
        },
    )
    assert error["code"] == "invalid_input" and "to_index 0" in error["message"]
    assert [c.name() for c in geo.children()] == ["existing"]


def test_build_verifies_each_input_source(client):
    from hocuspocus.host.tools import network

    geo = hou.node("/obj").createNode("geo", "g")
    a = geo.createNode("box", "a")
    b = geo.createNode("box", "b")
    x = geo.createNode("xform", "x")
    x.setInput(0, b)
    data = {"x": {"type": "xform", "inputs": [{"from": "a", "from_index": 0, "to_index": 0}]}}
    problems = network._Problems()
    network._verify_level(data, geo, "/obj/g/", problems)
    assert len(problems.items) == 1 and a.path() not in problems.items[0].message
    assert "fed by b" in problems.items[0].message


def test_build_replace_ignores_network_box_names(client):
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNetworkBox("box1")
    geo.createStickyNote("note1")
    old = geo.createNode("null", "keep")
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {"box1": {"type": "box"}, "keep": {"type": "null"}},
            "on_name_collision": "replace",
        },
    )
    assert error["code"] == "name_collision" and "network box" in error["message"]
    assert geo.node("keep") == old
    built = client.ok(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {"keep": {"type": "box"}},
            "on_name_collision": "replace",
        },
    )
    assert built["replaced"] == ["/obj/g/keep"] and geo.node("keep").type().name() == "box"
    renamed = client.ok(
        "network_build",
        {"parent": "/obj/g", "data": {"box1": {"type": "box"}}, "on_name_collision": "rename"},
    )
    assert renamed["renamed"]["/obj/g/box1"] != "/obj/g/box1"


def test_describe_depth_is_budgeted_and_paged(client, host):
    geo = hou.node("/obj").createNode("geo", "geo1")
    for index in range(12):
        sub = geo.createNode("subnet", f"sub{index:02d}")
        for inner in range(6):
            sub.createNode("null", f"inner_with_a_long_name_{inner}")
    full = client.ok("network_describe", {"root": "/obj/geo1", "depth": 3})
    assert full["node_count"] == 12 * 7 and "truncated" not in full
    saved = host.config.max_response_bytes
    host.config.max_response_bytes = 2048
    try:
        first = client.ok("network_describe", {"root": "/obj/geo1", "depth": 3})
        assert first["truncated"] is True and first["next_cursor"]
        assert first["bytes"] <= 2048
        seen = list(first["data"])
        cursor = first["next_cursor"]
        while cursor:
            more = client.ok(
                "network_describe", {"root": "/obj/geo1", "depth": 3, "cursor": cursor}
            )
            seen += list(more["data"])
            cursor = more.get("next_cursor")
    finally:
        host.config.max_response_bytes = saved
    assert seen == [f"sub{i:02d}" for i in range(12)]


# -- outline (review 11 B11) -------------------------------------------------------


def test_describe_outline_is_a_compact_tree(client):
    geo = hou.node("/obj").createNode("geo", "city")
    box = geo.createNode("box", "base")
    out = geo.createNode("null", "OUT")
    out.setInput(0, box)
    out.setDisplayFlag(True)
    broken = geo.createNode("attribwrangle", "broken")
    broken.parm("snippet").set("x(")
    with pytest.raises(hou.OperationFailed):
        broken.cook(force=True)
    terrain = hou.node("/obj").createNode("geo", "terrain")
    mountain = terrain.createNode("mountain", "peaks")
    mountain.setInput(0, terrain.createNode("grid", "grid1"))
    mountain.cook(force=True)
    result = client.ok("network_describe", {"root": "/obj", "format": "outline"})
    assert result["format"] == "outline" and result["root"] == "/obj"
    nodes = {n["name"]: n for n in result["nodes"]}
    city = nodes["city"]
    assert city == {
        "path": "/obj/city",
        "name": "city",
        "type": "geo",
        "children_count": 3,
        "display": "/obj/city/OUT",
        "errors": 0,
        "children": city["children"],
    }
    kids = {n["name"]: n for n in city["children"]}  # depth 2 by default for outline
    assert kids["broken"]["errors"] >= 1
    assert set(kids["base"]) == {"path", "name", "type", "errors"}  # no children_count: 0
    assert "parms" not in kids["base"] and "inputs" not in kids["base"]
    # Houdini's own locked assets (wrangles, mountain) are not flagged (review 12 papercut 4).
    assert "hda_locked" not in kids["broken"]
    peaks = next(n for n in nodes["terrain"]["children"] if n["name"] == "peaks")
    assert "hda_locked" not in peaks and "children" not in peaks
    assert result["node_count"] == 7
    shallow = client.ok("network_describe", {"root": "/obj", "format": "outline", "depth": 1})
    assert all("children" not in n for n in shallow["nodes"])
    whole = client.ok("network_describe", {"root": "/", "format": "outline"})
    assert "/obj" in [n["path"] for n in whole["nodes"]]


def test_describe_outline_flags_user_locked_assets(client, work_dir):
    geo = hou.node("/obj").createNode("geo", "geo1")
    sub = geo.createNode("subnet", "asset1")
    sub.createNode("box", "inner")
    hda_path = (work_dir / "hp_outline_test.hda").as_posix()
    asset = sub.createDigitalAsset(name="hp_outline_test", hda_file_name=hda_path)
    asset.matchCurrentDefinition()  # lock it
    assert asset.isLockedHDA() and asset.children()
    result = client.ok("network_describe", {"root": geo.path(), "format": "outline"})
    row = next(n for n in result["nodes"] if n["path"] == asset.path())
    assert row["hda_locked"] is True and "children" not in row and "children_count" not in row
    opened = client.ok(
        "network_describe", {"root": geo.path(), "format": "outline", "recurse_locked": True}
    )
    row = next(n for n in opened["nodes"] if n["path"] == asset.path())
    assert row["hda_locked"] is True and row["children_count"] == 1


def test_describe_outline_is_budgeted_and_paged(client, host):
    geo = hou.node("/obj").createNode("geo", "geo1")
    for index in range(80):
        geo.createNode("null", f"a_rather_long_node_name_number_{index:03d}")
    saved = host.config.max_response_bytes
    host.config.max_response_bytes = 2048
    try:
        first = client.ok("network_describe", {"root": geo.path(), "format": "outline"})
        assert first["truncated"] is True and first["next_cursor"]
        names = [n["name"] for n in first["nodes"]]
        cursor = first["next_cursor"]
        while cursor:
            page = client.ok(
                "network_describe", {"root": geo.path(), "format": "outline", "cursor": cursor}
            )
            names += [n["name"] for n in page["nodes"]]
            cursor = page.get("next_cursor")
    finally:
        host.config.max_response_bytes = saved
    assert len(names) == 80 == len(set(names))


def test_build_accepts_to_index_by_input_name(client):
    hou.node("/obj").createNode("geo", "g")
    result = client.ok(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {
                "b": {"type": "box"},
                "pts": {"type": "scatter", "inputs": [{"from": "b"}]},
                "copy": {
                    "type": "copytopoints",
                    "inputs": [
                        {"from": "b", "to_index": "input1"},
                        {"from": "pts", "to_index": "input2"},
                    ],
                },
            },
        },
    )
    assert "/obj/g/copy" in result["created"]
    copy = hou.node("/obj/g/copy")
    assert [n.name() for n in copy.inputs()] == ["b", "pts"]
    error = client.error(
        "network_build",
        {
            "parent": "/obj/g",
            "data": {"c2": {"type": "copytopoints", "inputs": [{"from": "b", "to_index": "nope"}]}},
        },
    )
    assert error["code"] == "invalid_input"
