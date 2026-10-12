"""Node tools against real Houdini (docs/BIBLE.md §4.4, §5)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def ok_or_skip_parms(client, tool, args):
    """Call a tool whose result depends on the parms helpers; skip while they are stubs."""
    envelope = client.call(tool, args)
    if not envelope["ok"] and "NotImplementedError" in envelope["error"].get("message", ""):
        pytest.skip("parms.set_parm_items/summarize_parm are still stubs (M1 parms task)")
    assert envelope["ok"], envelope
    return envelope["result"]


def make_chain():
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box", "box1")
    xform = geo.createNode("xform", "xform1")
    xform.setInput(0, box)
    null = geo.createNode("null", "OUT")
    null.setInput(0, xform)
    null.setDisplayFlag(True)
    null.setRenderFlag(True)
    return geo, box, xform, null


def make_locked_mountain():
    geo = hou.node("/obj").createNode("geo", "terrain")
    grid = geo.createNode("grid", "grid1")
    mountain = geo.createNode("mountain", "mountain1")
    mountain.setInput(0, grid)
    mountain.cook(force=True)  # HDA contents load lazily in hython
    assert mountain.isLockedHDA() and mountain.children()
    return geo, mountain


# -- node_create -------------------------------------------------------------------


def test_create_wires_flags_and_resolves_types(client):
    result = client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "terrain"},
                {"parent": "/obj/terrain", "type": "box"},
                {"parent": "/obj/terrain", "type": "sphere", "position": [4, 2]},
                {
                    "parent": "/obj/terrain",
                    "type": "copytopoints",
                    "inputs": [
                        {"index": 0, "from": "/obj/terrain/box1"},
                        {"name": "input2", "from": "sphere1"},
                    ],
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )
    paths = result["created"]
    assert paths == [
        "/obj/terrain",
        "/obj/terrain/box1",
        "/obj/terrain/sphere1",
        "/obj/terrain/copytopoints1",
    ]
    copy_block = result["results"][3]
    assert copy_block["type"]["name"] == "copytopoints::2.0"  # namespace order, like createNode
    assert copy_block["type"]["version"] == "2.0"
    assert copy_block["flags"]["display"] is True
    assert [(i["index"], i["from"]["path"]) for i in copy_block["inputs"]] == [
        (0, "/obj/terrain/box1"),
        (1, "/obj/terrain/sphere1"),
    ]
    assert copy_block["inputs"][1]["label"]
    for key in ("errors", "warnings", "cook_state", "session_id"):
        assert key in copy_block
    assert copy_block["cook_state"] == "cooked"
    assert list(hou.node("/obj/terrain/sphere1").position()) == [4.0, 2.0]
    # good_position moved the wired node off the origin
    assert list(hou.node("/obj/terrain/copytopoints1").position()) != [0.0, 0.0]


def test_create_exact_type(client):
    hou.node("/obj").createNode("geo", "g")
    result = client.ok(
        "node_create",
        {"items": [{"parent": "/obj/g", "type": "copytopoints"}], "exact_type": True},
    )
    assert result["results"][0]["type"]["name"] == "copytopoints"


def test_create_unknown_type_has_candidates(client):
    hou.node("/obj").createNode("geo", "g")
    error = client.error("node_create", {"items": [{"parent": "/obj/g", "type": "boxx"}]})
    assert error["code"] == "node_type_not_found"
    assert "box" in error["candidates"]
    assert error["hint"]


def test_create_sop_in_obj_hints_the_category(client):
    error = client.error("node_create", {"items": [{"parent": "/obj", "type": "box"}]})
    assert error["code"] == "node_type_not_found"
    assert "Sop" in error["hint"] and "geo" in error["hint"]


def test_create_name_collision(client):
    make_chain()
    error = client.error(
        "node_create", {"items": [{"parent": "/obj/geo1", "type": "box", "name": "box1"}]}
    )
    assert error["code"] == "name_collision"
    assert error["candidates"] and error["candidates"][0] != "box1"
    assert error["hint"]
    assert len(hou.node("/obj/geo1").children()) == 3


def test_create_parent_not_found_has_candidates(client):
    make_chain()
    error = client.error("node_create", {"items": [{"parent": "/obj/geo2", "type": "box"}]})
    assert error["code"] == "node_not_found"
    assert "/obj/geo1" in error["candidates"]
    assert error["hint"]


def test_create_batch_rolls_back_on_failure(client):
    geo, _box, _xform, null = make_chain()
    error = client.error(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "rollback_geo"},
                {"parent": "/obj/rollback_geo", "type": "box"},
                {"parent": "/obj/geo1", "type": "sphere", "flags": {"display": True}},
                {"parent": "/obj/geo1", "type": "no_such_type_xyz"},
            ]
        },
    )
    assert error["code"] == "node_type_not_found"
    assert error["detail"]["item"] == 3 and error["detail"]["rolled_back"] is True
    assert error["message"].startswith("Item 3:")
    assert hou.node("/obj/rollback_geo") is None
    assert [c.name() for c in geo.children()] == ["box1", "xform1", "OUT"]
    assert null.isDisplayFlagSet()  # display flag restored to the original node


def test_create_partial_keeps_successes(client):
    make_chain()
    result = client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj/geo1", "type": "sphere"},
                {"parent": "/obj/geo1", "type": "nope_type"},
                {"parent": "/obj/geo1", "type": "box", "name": "box1"},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 2
    assert result["results"][0]["path"] == "/obj/geo1/sphere1"
    assert result["results"][1]["error"]["code"] == "node_type_not_found"
    assert result["results"][2]["error"]["code"] == "name_collision"
    assert result["created"] == ["/obj/geo1/sphere1"]


def test_create_inside_locked_asset_is_refused(client):
    _geo, mountain = make_locked_mountain()
    error = client.error("node_create", {"items": [{"parent": mountain.path(), "type": "null"}]})
    assert error["code"] == "locked"
    assert "lock: false" in error["hint"]


def test_create_bad_input_lists_labels(client):
    make_chain()
    error = client.error(
        "node_create",
        {
            "items": [
                {
                    "parent": "/obj/geo1",
                    "type": "xform",
                    "inputs": [{"index": 3, "from": "/obj/geo1/box1"}],
                }
            ]
        },
    )
    assert error["code"] == "invalid_input"
    assert "0: input1" in error["hint"]
    assert len(hou.node("/obj/geo1").children()) == 3


def test_create_with_parms(client):
    result = ok_or_skip_parms(
        client,
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "terrain"},
                {
                    "parent": "/obj/terrain",
                    "type": "grid",
                    "parms": {"size": [4, 6], "rows": 20},
                },
                {
                    "parent": "/obj/terrain",
                    "type": "xform",
                    "inputs": [{"index": 0, "from": "/obj/terrain/grid1"}],
                    "parms": {"ty": {"expr": "ch('../grid1/sizex') * 0.1"}},
                },
            ]
        },
    )
    grid = hou.node("/obj/terrain/grid1")
    assert grid.parmTuple("size").eval() == (4.0, 6.0)
    assert hou.node(result["created"][2]).parm("ty").eval() == pytest.approx(0.4)
    names = {p["name"] for p in result["results"][1]["parms"]}
    assert {"size", "rows"} <= names


def test_create_accepts_both_expression_spellings(client):
    """Review 07 papercut 4: {expression, language} (what parm_set takes and the readers
    emit) and the short {expr, lang} both work; a mix is refused naming both."""
    geo = hou.node("/obj").createNode("geo", "terrain")
    result = client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": geo.path(),
                    "type": "box",
                    "parms": {
                        "sizex": {"expression": "$F*2"},
                        "sizey": {"expression": "hou.frame() * 3", "language": "python"},
                        "sizez": {"expr": "$F*4", "lang": "hscript"},
                    },
                }
            ]
        },
    )
    box = hou.node(result["created"][0])
    assert box.parm("sizex").expression() == "$F*2"
    assert box.parm("sizey").expressionLanguage() == hou.exprLanguage.Python
    assert box.parm("sizez").eval() == pytest.approx(4 * hou.frame())
    error = client.error(
        "node_create",
        {
            "items": [
                {
                    "parent": geo.path(),
                    "type": "box",
                    "parms": {"sizex": {"expr": "$F", "language": "python"}},
                }
            ]
        },
    )
    assert error["code"] == "invalid_argument"
    assert "{expression, language}" in error["message"] and "{expr, lang}" in error["message"]
    error = client.error(
        "node_create",
        {"items": [{"parent": geo.path(), "type": "box", "parms": {"sizex": "$F*2"}}]},
    )
    assert error["code"] == "invalid_value"
    assert "{expression, language}" in error["hint"] and "{expr, lang}" in error["hint"]


# -- node_info ---------------------------------------------------------------------


def test_info_sections(client):
    geo, box, xform, null = make_chain()
    box.setComment("base")
    box.setUserData("note", "x")
    result = client.ok(
        "node_info",
        {
            "paths": ["/obj/geo1/xform1", "/obj/geo1"],
            "include": [
                "inputs",
                "outputs",
                "errors",
                "flags",
                "hda",
                "comment",
                "position",
                "userdata",
                "children",
            ],
        },
    )
    xf, g = result["nodes"]
    assert xf["path"] == "/obj/geo1/xform1" and xf["name"] == "xform1"
    assert xf["session_id"] == xform.sessionId()
    assert xf["type"]["name"] == "xform" and xf["type"]["category"] == "Sop"
    assert xf["type"]["help_url"] == "operator:Sop/xform"
    assert xf["inputs"] == [
        {
            "index": 0,
            "name": "input1",
            "label": "Transform geometry",
            "from": {"path": "/obj/geo1/box1", "output": 0},
        }
    ]
    assert xf["outputs"][0]["to"] == [{"path": "/obj/geo1/OUT", "input": 0}]
    assert xf["hda"] is None
    assert "parms" not in xf
    assert g["children"] == ["box1", "xform1", "OUT"] and g["children_count"] == 3
    box_info = client.ok(
        "node_info", {"paths": ["/obj/geo1/box1"], "include": ["comment", "userdata"]}
    )
    assert box_info["nodes"][0]["comment"] == "base"
    assert box_info["nodes"][0]["userdata"] == {"note": "x"}


def test_info_default_includes_parms(client):
    geo, box, xform, null = make_chain()
    xform.parm("tx").set(2)
    result = ok_or_skip_parms(client, "node_info", {"paths": ["/obj/geo1/xform1"]})
    parms = result["nodes"][0]["parms"]
    assert [p["name"] for p in parms] == ["t"]
    everything = ok_or_skip_parms(
        client, "node_info", {"paths": ["/obj/geo1/xform1"], "include_defaults": True}
    )
    assert len(everything["nodes"][0]["parms"]) > 5


def test_info_hda_and_locked_contents(client):
    _geo, mountain = make_locked_mountain()
    result = client.ok("node_info", {"paths": [mountain.path()], "include": ["hda", "children"]})
    block = result["nodes"][0]
    assert block["hda"]["locked"] is True
    assert block["hda"]["definition"] == "mountain::2.0"
    assert block["hda"]["library"].lower().endswith(".hda")
    assert block["children"] == [] and "children_count" not in block
    inner = mountain.children()[0].path()
    error = client.error("node_info", {"paths": [inner], "include": ["flags"]})
    assert error["code"] == "locked" and "recurse_locked" in error["hint"]
    ok = client.ok("node_info", {"paths": [inner], "include": ["flags"], "recurse_locked": True})
    assert ok["nodes"][0]["path"] == inner
    opened = client.ok(
        "node_info", {"paths": [mountain.path()], "include": ["children"], "recurse_locked": True}
    )
    assert opened["nodes"][0]["children"]


def test_info_not_found(client):
    make_chain()
    error = client.error("node_info", {"paths": ["/obj/geo1/xfrom1"]})
    assert error["code"] == "node_not_found"
    assert error["candidates"][0] == "/obj/geo1/xform1"


# -- node_find ---------------------------------------------------------------------


def test_find_filters_and_pages(client):
    geo, box, xform, null = make_chain()
    geo.createNode("box", "box2")
    xform.parm("tx").setExpression("nosuchfn()")
    with pytest.raises(hou.OperationFailed):
        xform.cook(force=True)
    rows = client.ok("node_find", {"root": "/obj", "pattern": "box*"})
    assert [r["path"] for r in rows["nodes"]] == ["/obj/geo1/box1", "/obj/geo1/box2"]
    row = rows["nodes"][0]
    assert set(row) == {
        "path",
        "type",
        "category",
        "flags",
        "input_count",
        "child_count",
        "has_errors",
    }
    by_type = client.ok("node_find", {"root": "/obj", "type": "xfor*"})
    assert [r["path"] for r in by_type["nodes"]] == ["/obj/geo1/xform1"]
    assert by_type["nodes"][0]["has_errors"] is True
    errored = client.ok("node_find", {"has_errors": True})
    assert [r["path"] for r in errored["nodes"]] == ["/obj/geo1/xform1"]
    displayed = client.ok("node_find", {"root": "/obj/geo1", "flags": {"display": True}})
    assert [r["path"] for r in displayed["nodes"]] == ["/obj/geo1/OUT"]
    objs = client.ok("node_find", {"root": "/obj", "category": "Object"})
    assert [r["path"] for r in objs["nodes"]] == ["/obj/geo1"]
    first = client.ok("node_find", {"root": "/obj/geo1", "limit": 2})
    assert first["total"] == 4 and len(first["nodes"]) == 2 and first["next_cursor"] == "2"
    second = client.ok(
        "node_find", {"root": "/obj/geo1", "limit": 2, "cursor": first["next_cursor"]}
    )
    assert len(second["nodes"]) == 2 and "next_cursor" not in second
    bad = client.error("node_find", {"cursor": "abc"})
    assert bad["code"] == "invalid_argument" and bad["hint"]


def test_find_does_not_enter_locked_assets(client):
    _geo, mountain = make_locked_mountain()
    inner = {c.path() for c in mountain.allSubChildren()}
    rows = client.ok("node_find", {"root": "/obj", "limit": 1000})
    paths = {r["path"] for r in rows["nodes"]}
    assert mountain.path() in paths and not (paths & inner)
    deep = client.ok("node_find", {"root": "/obj", "limit": 1000, "recurse_locked": True})
    assert inner <= {r["path"] for r in deep["nodes"]}


def test_find_root_not_found(client):
    error = client.error("node_find", {"root": "/objx"})
    assert error["code"] == "node_not_found" and "/obj" in error["candidates"]


# -- node_delete -------------------------------------------------------------------


def test_delete_keeps_connections(client):
    geo, box, xform, null = make_chain()
    result = client.ok("node_delete", {"paths": ["/obj/geo1/xform1"]})
    assert result["deleted"] == ["/obj/geo1/xform1"]
    assert result["reconnected"] == [{"from": "/obj/geo1/box1", "to": "/obj/geo1/OUT", "input": 0}]
    assert null.inputs()[0].path() == "/obj/geo1/box1"


def test_delete_without_connections_and_missing(client):
    geo, box, xform, null = make_chain()
    client.ok("node_delete", {"paths": ["/obj/geo1/xform1"], "keep_connections": False})
    assert null.inputs() == ()
    error = client.error("node_delete", {"paths": ["/obj/geo1/nope"]})
    assert error["code"] == "node_not_found" and error["hint"]


def test_delete_inside_locked_refused(client):
    _geo, mountain = make_locked_mountain()
    error = client.error("node_delete", {"paths": [mountain.children()[0].path()]})
    assert error["code"] == "locked"


# -- node_edit ---------------------------------------------------------------------


def test_edit_rename_flags_color_comment_position(client):
    geo, box, xform, null = make_chain()
    result = client.ok(
        "node_edit",
        {
            "items": [
                {
                    "path": "/obj/geo1/box1",
                    "name": "base_box",
                    "color": [1, 0, 0],
                    "comment": "OUT",
                    "position": [3, 4],
                    "bypass": True,
                },
                {"path": "/obj/geo1/xform1", "flags": {"display": True, "template": True}},
            ]
        },
    )
    first, second = result["results"]
    assert first["old_path"] == "/obj/geo1/box1" and first["path"] == "/obj/geo1/base_box"
    assert first["flags"]["bypass"] is True and first["color"] == [1.0, 0.0, 0.0]
    assert first["comment"] == "OUT" and first["position"] == [3.0, 4.0]
    assert "old_path" not in second
    assert xform.isDisplayFlagSet() and xform.isTemplateFlagSet()


def test_edit_rename_collision_and_rollback(client):
    geo, box, xform, null = make_chain()
    error = client.error(
        "node_edit",
        {
            "items": [
                {"path": "/obj/geo1/xform1", "name": "moved", "comment": "c"},
                {"path": "/obj/geo1/OUT", "name": "box1"},
            ]
        },
    )
    assert error["code"] == "name_collision" and error["candidates"]
    assert xform.name() == "xform1" and xform.comment() == ""


def test_edit_object_has_no_bypass_flag(client):
    make_chain()
    error = client.error("node_edit", {"items": [{"path": "/obj/geo1", "flags": {"bypass": True}}]})
    assert error["code"] == "invalid_argument" and "display" in error["hint"]


def test_edit_lock_unlock_hda(client):
    _geo, mountain = make_locked_mountain()
    result = client.ok("node_edit", {"items": [{"path": mountain.path(), "lock": False}]})
    assert result["results"][0]["hda"]["locked"] is False
    assert not mountain.isLockedHDA()
    created = client.ok("node_create", {"items": [{"parent": mountain.path(), "type": "null"}]})
    assert created["created"][0].startswith(mountain.path() + "/")
    relocked = client.ok("node_edit", {"items": [{"path": mountain.path(), "lock": True}]})
    assert relocked["results"][0]["hda"]["locked"] is True
    error = client.error("node_edit", {"items": [{"path": "/obj/terrain/grid1", "lock": False}]})
    assert error["code"] == "invalid_argument" and error["hint"]


# -- node_copy ---------------------------------------------------------------------


def test_copy_within_and_across_networks(client):
    geo, box, xform, null = make_chain()
    same = client.ok(
        "node_copy",
        {
            "paths": ["/obj/geo1/box1", "/obj/geo1/xform1"],
            "to_parent": "/obj/geo1",
            "names": ["box_copy"],
        },
    )
    assert same["paths"] == ["/obj/geo1/box_copy", "/obj/geo1/xform2"]
    copied = hou.node("/obj/geo1/xform2")
    assert copied.inputs()[0].path() == "/obj/geo1/box_copy"
    hou.node("/obj").createNode("geo", "other")
    across = client.ok(
        "node_copy",
        {
            "paths": ["/obj/geo1/box1", "/obj/geo1/xform1"],
            "to_parent": "/obj/other",
            "with_inputs": False,
            "position_offset": [5, 1],
        },
    )
    assert across["paths"] == ["/obj/other/box1", "/obj/other/xform1"]
    assert hou.node("/obj/other/xform1").inputs() == ()
    hou.node("/obj").createNode("geo", "plain")
    client.ok(
        "node_copy", {"paths": ["/obj/geo1/box1", "/obj/geo1/xform1"], "to_parent": "/obj/plain"}
    )
    moved = hou.node("/obj/other/xform1").position()
    plain = hou.node("/obj/plain/xform1").position()
    assert (moved[0], moved[1]) == pytest.approx((plain[0] + 5, plain[1] + 1))
    assert across["results"][0]["source"] == "/obj/geo1/box1"


def test_copy_errors(client):
    make_chain()
    error = client.error(
        "node_copy", {"paths": ["/obj/geo1/box1"], "to_parent": "/obj/geo1", "names": ["xform1"]}
    )
    assert error["code"] == "name_collision"
    error = client.error("node_copy", {"paths": ["/obj/geo1/box1"], "to_parent": "/obj"})
    assert error["code"] == "invalid_argument" and error["hint"]


# -- node_connect ------------------------------------------------------------------


def test_connect_index_name_next_and_disconnect(client):
    geo, box, xform, null = make_chain()
    sphere = geo.createNode("sphere", "sphere1")
    merge = geo.createNode("merge", "merge1")
    copy = geo.createNode("copytopoints", "copy1")
    result = client.ok(
        "node_connect",
        {
            "items": [
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/merge1", "to_input": "next"},
                {"from": "/obj/geo1/sphere1", "to": "/obj/geo1/merge1", "to_input": "next"},
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/copy1", "to_input": "input2"},
                {"from": "/obj/geo1/sphere1", "to": "/obj/geo1/copy1", "to_input": 0},
                {"from": None, "to": "/obj/geo1/OUT", "to_input": 0},
            ]
        },
    )
    rows = result["results"]
    assert [r["input"] for r in rows] == [0, 1, 1, 0, 0]
    assert rows[2]["input_name"] == "input2"
    assert [n.name() for n in merge.inputs()] == ["box1", "sphere1"]
    assert [n.name() for n in copy.inputs()] == ["sphere1", "box1"]
    assert null.inputs() == ()
    assert rows[4]["from"] is None and "errors" in rows[4]
    del sphere


def test_connect_invalid_input_lists_labels(client):
    geo, box, xform, null = make_chain()
    geo.createNode("copytopoints", "copy1")
    error = client.error(
        "node_connect",
        {"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/copy1", "to_input": 5}]},
    )
    assert error["code"] == "invalid_input"
    assert "0: input1 (Geometry to Copy)" in error["hint"]
    assert "1: input2 (Target Points to Copy to)" in error["hint"]
    error = client.error(
        "node_connect",
        {"items": [{"from": "/obj/geo1/box1", "to": "/obj/geo1/copy1", "to_input": "target"}]},
    )
    assert error["code"] == "invalid_input" and "input2" in error["candidates"]
    error = client.error(
        "node_connect",
        {"items": [{"from": "/obj/geo1/box1", "from_output": 2, "to": "/obj/geo1/copy1"}]},
    )
    assert error["code"] == "invalid_input" and error["hint"]


def test_connect_batch_rolls_back(client):
    geo, box, xform, null = make_chain()
    error = client.error(
        "node_connect",
        {
            "items": [
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/OUT"},
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/xform1", "to_input": 9},
            ]
        },
    )
    assert error["code"] == "invalid_input" and error["detail"]["item"] == 1
    assert null.inputs()[0].path() == "/obj/geo1/xform1"


def test_connect_partial(client):
    geo, box, xform, null = make_chain()
    result = client.ok(
        "node_connect",
        {
            "items": [
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/OUT"},
                {"from": "/obj/geo1/box1", "to": "/obj/geo1/nope"},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 1
    assert result["results"][1]["error"]["code"] == "node_not_found"
    assert null.inputs()[0].path() == "/obj/geo1/box1"


# -- node_layout -------------------------------------------------------------------


def test_layout_modes(client):
    geo, box, xform, null = make_chain()
    result = client.ok("node_layout", {"parent": "/obj/geo1"})
    assert result["count"] == 3
    ys = [box.position()[1], xform.position()[1], null.position()[1]]
    assert ys[0] > ys[1] > ys[2]
    extra = geo.createNode("null", "loose")
    moved = client.ok(
        "node_layout", {"parent": "/obj/geo1", "paths": ["loose"], "mode": "good_position"}
    )
    assert moved["nodes"][0]["path"] == "/obj/geo1/loose"
    assert list(extra.position()) != [0.0, 0.0]
    error = client.error("node_layout", {"parent": "/obj/geo1", "paths": ["/obj/geo1"]})
    assert error["code"] == "invalid_argument"
