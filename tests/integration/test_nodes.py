"""Node tools against real Houdini (docs/BIBLE.md §4.4, §5)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


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
            ],
            "return": "full",
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
        {
            "items": [{"parent": "/obj/g", "type": "copytopoints"}],
            "exact_type": True,
            "return": "full",
        },
    )
    assert result["results"][0]["type"]["name"] == "copytopoints"


def test_create_unknown_type_has_candidates(client):
    hou.node("/obj").createNode("geo", "g")
    error = client.error("node_create", {"items": [{"parent": "/obj/g", "type": "boxx"}]})
    assert error["code"] == "node_type_not_found"
    assert "box" in error["candidates"]
    assert error["hint"]


def test_unknown_light_type_suggests_hlight(client):
    """Review 11 B10: candidates come from labels and synonyms, not only names."""
    error = client.error("node_create", {"items": [{"parent": "/obj", "type": "distantlight"}]})
    assert error["code"] == "node_type_not_found"
    assert error["candidates"][0] == "hlight"
    assert "light_type" in error["hint"]
    spot = client.error("node_create", {"items": [{"parent": "/obj", "type": "spot_light"}]})
    assert spot["candidates"][0] == "hlight"
    # A label match: "Environment Light" is envlight.
    env = client.error("node_create", {"items": [{"parent": "/obj", "type": "environmentlight"}]})
    assert env["candidates"][0] == "envlight"


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
    assert error["message"].startswith("items[3] (/obj/geo1): ")
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
    result = client.ok(
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
            ],
            "return": "full",
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


LONG_VEX = "// generated\n" + "\n".join(f"float v{i} = {i} * @P.x;" for i in range(30)) + "\nx("


def test_create_full_result_elides_long_snippets(client):
    hou.node("/obj").createNode("geo", "geo1")
    result = client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj/geo1", "type": "attribwrangle", "parms": {"snippet": LONG_VEX}}
            ],
            "return": "full",
        },
    )
    row = next(p for p in result["results"][0]["parms"] if p["name"] == "snippet")
    assert row["value"] == {"elided": len(LONG_VEX), "head": LONG_VEX[:80]}
    assert row["raw"] == {"elided": len(LONG_VEX), "head": LONG_VEX[:80]}
    assert hou.node(result["created"][0]).parm("snippet").eval() == LONG_VEX
    info = client.ok("node_info", {"paths": result["created"]})["nodes"][0]
    assert next(p for p in info["parms"] if p["name"] == "snippet")["value"] == LONG_VEX


def test_create_copy_and_build_summary_results(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    items = [
        {"parent": "/obj/geo1", "type": "attribwrangle", "name": "w0", "parms": {"snippet": "x("}}
    ]
    items += [
        {
            "parent": "/obj/geo1",
            "type": "xform",
            "name": f"x{i}",
            "inputs": [{"index": 0, "from": "w0"}],
        }
        for i in range(2)
    ]
    summary = client.ok("node_create", {"items": items, "return": "summary"})
    rows = summary["results"]
    assert summary["created"] == ["/obj/geo1/w0", "/obj/geo1/x0", "/obj/geo1/x1"]
    assert set(rows[0]) <= {"path", "type", "errors", "warnings", "cook_state", "hint"}
    assert rows[0]["type"] == "attribwrangle" and rows[0]["errors"]
    # Downstream nodes repeat the upstream error verbatim: it is reported once.
    assert rows[1]["errors_same_as"] == "/obj/geo1/w0" and "errors" not in rows[1]
    assert rows[2]["errors_same_as"] == "/obj/geo1/w0"
    full = client.ok(
        "node_create", {"items": [{"parent": "/obj/geo1", "type": "box"}], "return": "full"}
    )
    assert "parms" in full["results"][0] and "flags" in full["results"][0]
    copied = client.ok(
        "node_copy",
        {"paths": ["/obj/geo1/x0", "/obj/geo1/x1"], "to_parent": "/obj/geo1", "return": "summary"},
    )
    keys = {"path", "type", "errors", "warnings", "cook_state", "hint", "source"}
    keys |= {"errors_same_as", "warnings_same_as"}
    assert all(set(row) <= keys for row in copied["results"])
    texts = [tuple(row["errors"]) for row in copied["results"] if row.get("errors")]
    assert len(texts) == len(set(texts))
    built = client.ok(
        "network_build",
        {
            "parent": "/obj/geo1",
            "data": {"b1": {"type": "box"}, "b2": {"type": "box"}},
            "return": "summary",
        },
    )
    assert [n["path"] for n in built["nodes"]] == ["/obj/geo1/b1", "/obj/geo1/b2"]
    assert "flags" not in built["nodes"][0]
    assert geo.node("b2") is not None


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
    result = client.ok("node_info", {"paths": ["/obj/geo1/xform1"]})
    parms = result["nodes"][0]["parms"]
    assert [p["name"] for p in parms] == ["t"]
    everything = client.ok("node_info", {"paths": ["/obj/geo1/xform1"], "include_defaults": True})
    assert len(everything["nodes"][0]["parms"]) > 5


def test_info_lists_non_default_multiparm_counts(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    create = geo.createNode("attribcreate", "ac")
    rows = client.ok("node_info", {"paths": [create.path()]})["nodes"][0]["parms"]
    assert "numattr" not in [p["name"] for p in rows]
    create.parm("numattr").set(3)
    rows = client.ok("node_info", {"paths": [create.path()]})["nodes"][0]["parms"]
    count = next(p for p in rows if p["name"] == "numattr")
    assert count["value"] == 3 and count["is_default"] is False
    plain = geo.createNode("box", "b")
    plain_rows = client.ok("node_info", {"paths": [plain.path()], "include_defaults": True})[
        "nodes"
    ][0]["parms"]
    assert not [p for p in plain_rows if p["value"] is None and p["raw"] in ("", None)]


def test_info_hda_and_locked_contents(client):
    _geo, mountain = make_locked_mountain()
    result = client.ok("node_info", {"paths": [mountain.path()], "include": ["hda", "children"]})
    block = result["nodes"][0]
    assert block["hda"]["hda_locked"] is True and "locked" not in block["hda"]
    assert block["hda_locked"] is True
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


def test_node_not_found_is_one_shape_across_tools(client):
    """Node, network, parm and cook tools share _diag.require_node's error."""
    make_chain()
    missing = "/obj/geo1/xfrom1"
    errors = [
        client.error("node_info", {"paths": [missing]}),
        client.error("network_describe", {"root": missing}),
        client.error("parm_get", {"paths": [f"{missing}/tx"]}),
        client.error("cook", {"paths": [missing]}),
        client.error(
            "node_connect", {"items": [{"from": "xfrom1", "to": "/obj/geo1/OUT", "to_input": 0}]}
        ),
    ]
    assert {e["code"] for e in errors} == {"node_not_found"}
    assert {e["message"] for e in errors[:4]} == {f"No node at {missing}."}
    assert all(e["candidates"][0] == "/obj/geo1/xform1" for e in errors)
    assert "Parm paths are" in errors[2]["hint"]


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
    assert first["total"] == 4 and len(first["nodes"]) == 2 and first["next_cursor"]
    second = client.ok(
        "node_find", {"root": "/obj/geo1", "limit": 2, "cursor": first["next_cursor"]}
    )
    assert len(second["nodes"]) == 2 and "next_cursor" not in second
    bad = client.error("node_find", {"cursor": "abc"})
    assert bad["code"] == "invalid_argument" and bad["hint"]


def test_find_cursor_survives_inserts_and_deletes(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    for name in ("a", "b", "c", "d", "e"):
        geo.createNode("null", name)
    first = client.ok("node_find", {"root": "/obj/geo1", "limit": 2})
    assert [r["path"] for r in first["nodes"]] == ["/obj/geo1/a", "/obj/geo1/b"]
    # Between pages: delete a row already returned (offsets would skip c) and add one
    # that sorts before the cursor (offsets would return b again).
    geo.node("a").destroy()
    geo.createNode("null", "aa")
    second = client.ok(
        "node_find", {"root": "/obj/geo1", "limit": 2, "cursor": first["next_cursor"]}
    )
    assert [r["path"] for r in second["nodes"]] == ["/obj/geo1/c", "/obj/geo1/d"]
    # The node the cursor names may itself be gone: paging continues after its position.
    geo.node("d").destroy()
    third = client.ok(
        "node_find", {"root": "/obj/geo1", "limit": 2, "cursor": second["next_cursor"]}
    )
    assert [r["path"] for r in third["nodes"]] == ["/obj/geo1/e"]
    assert "next_cursor" not in third


def test_find_reads_errors_only_for_returned_rows(client, monkeypatch):
    geo = hou.node("/obj").createNode("geo", "geo1")
    for index in range(30):
        geo.createNode("null", f"n{index:02d}")
    calls = []
    original = hou.Node.errors

    def counting(node):
        calls.append(node.path())
        return original(node)

    monkeypatch.setattr(hou.Node, "errors", counting)
    rows = client.ok("node_find", {"root": "/obj/geo1", "limit": 5})
    assert len(rows["nodes"]) == 5 and rows["total"] == 30
    assert sorted(set(calls)) == [r["path"] for r in rows["nodes"]]
    calls.clear()
    client.ok("node_find", {"root": "/obj/geo1", "limit": 5, "has_errors": False})
    assert len(set(calls)) == 30  # the filter needs every node's errors


def test_find_does_not_enter_locked_assets(client):
    _geo, mountain = make_locked_mountain()
    inner = {c.path() for c in mountain.allSubChildren()}
    rows = client.ok("node_find", {"root": "/obj", "limit": 1000})
    paths = {r["path"] for r in rows["nodes"]}
    assert mountain.path() in paths and not (paths & inner)
    deep = client.ok("node_find", {"root": "/obj", "limit": 1000, "recurse_locked": True})
    assert inner <= {r["path"] for r in deep["nodes"]}


def test_find_refuses_a_locked_asset_root(client):
    _geo, mountain = make_locked_mountain()
    error = client.error("node_find", {"root": mountain.path()})
    assert error["code"] == "locked"
    assert "locked asset" in error["message"] and "recurse_locked" in error["hint"]
    described = client.error("network_describe", {"root": mountain.path()})
    assert error["message"] == described["message"]
    inside = client.ok("node_find", {"root": mountain.path(), "recurse_locked": True})
    assert inside["total"] == len(mountain.allSubChildren())


def test_find_caps_rows_to_the_response_budget(client, host):
    geo = hou.node("/obj").createNode("geo", "geo1")
    for index in range(60):
        geo.createNode("null", f"node_with_a_fairly_long_name_{index:03d}")
    saved = host.config.max_response_bytes
    host.config.max_response_bytes = 2048
    try:
        first = client.ok("node_find", {"root": "/obj/geo1", "limit": 1000})
    finally:
        host.config.max_response_bytes = saved
    import json

    assert len(json.dumps(first, separators=(",", ":"))) <= 2048
    assert 0 < len(first["nodes"]) < 60 and first["total"] == 60
    rest = client.ok(
        "node_find", {"root": "/obj/geo1", "limit": 1000, "cursor": first["next_cursor"]}
    )
    paths = [r["path"] for r in first["nodes"] + rest["nodes"]]
    assert len(paths) == 60 == len(set(paths))
    # The bridge sends its budget in the /hp/v1/call envelope; the host pages by it.
    body = {
        "tool": "node_find",
        "args": {"root": "/obj/geo1", "limit": 1000},
        "max_response_bytes": 2048,
    }
    enveloped = client.request("POST", "/hp/v1/call", body).body["result"]
    assert enveloped["nodes"] == first["nodes"] and enveloped["next_cursor"]


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
    assert result["results"][0]["hda"]["hda_locked"] is False
    assert not mountain.isLockedHDA()
    created = client.ok("node_create", {"items": [{"parent": mountain.path(), "type": "null"}]})
    assert created["created"][0].startswith(mountain.path() + "/")
    relocked = client.ok("node_edit", {"items": [{"path": mountain.path(), "lock": True}]})
    assert relocked["results"][0]["hda"]["hda_locked"] is True
    error = client.error("node_edit", {"items": [{"path": "/obj/terrain/grid1", "lock": False}]})
    assert error["code"] == "invalid_argument" and error["hint"]


def test_edit_validates_everything_before_locking(client):
    _geo, mountain = make_locked_mountain()
    mountain.allowEditingOfContents()
    mountain.createNode("null", "my_edit")  # unsaved work inside the unlocked asset
    for bad in (
        {"name": "bad name!"},
        {"color": [1, 0]},
        {"flags": {"bogus": True}},
        {"comment": 3},
        {"position": [1]},
    ):
        error = client.error(
            "node_edit", {"items": [{"path": mountain.path(), "lock": True, **bad}]}
        )
        assert error["code"] == "invalid_argument", (bad, error)
        assert not mountain.isLockedHDA(), bad
        assert mountain.node("my_edit") is not None, bad
    result = client.ok(
        "node_edit",
        {
            "items": [
                {"path": mountain.path(), "lock": True, "name": "bad name!"},
                {"path": mountain.path(), "comment": "kept"},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 1 and result["results"][0]["error"]["code"] == "invalid_argument"
    assert mountain.node("my_edit") is not None and mountain.comment() == "kept"
    renamed = client.ok(
        "node_edit", {"items": [{"path": mountain.path(), "lock": True, "name": "peaks"}]}
    )
    block = renamed["results"][0]
    assert block["path"].endswith("/peaks") and block["hda"]["hda_locked"] is True


def test_operation_failed_maps_to_a_stable_code(client):
    from hocuspocus.host.tools import nodes

    error = nodes.to_tool_error(hou.OperationFailed("The attempted operation failed."))
    assert error.code == "invalid_argument" and error.hou_exception and error.hint
    renamed = nodes.to_tool_error(hou.OperationFailed("x"), op="rename")
    assert renamed.code == "name_collision" and renamed.hou_exception


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


def test_locked_means_the_sop_lock_flag(client):
    """BIBLE §4.1 (1.1): locked is the hard-lock flag; hda_locked is the asset lock."""
    geo, box, _xform, _null = make_chain()
    box.setHardLocked(True)
    found = client.ok("node_find", {"root": geo.path(), "flags": {"locked": True}})
    assert [row["path"] for row in found["nodes"]] == [box.path()]
    (block,) = client.ok("node_info", {"paths": [box.path()]})["nodes"]
    assert block["flags"]["locked"] is True and "hda_locked" not in block
    data = client.ok("network_describe", {"root": geo.path()})["data"]
    assert "hda_locked" not in data["box1"]


def test_mutation_echo_defaults_to_summary(client):
    """1.1 (review 11 B5): summary is the default echo of node_create, node_copy and
    network_build."""
    geo = hou.node("/obj").createNode("geo", "geo1")
    summary_keys = {"path", "type", "errors", "warnings", "cook_state", "hint", "source"}
    summary_keys |= {"errors_same_as", "warnings_same_as", "paired_with"}
    created = client.ok(
        "node_create", {"items": [{"parent": geo.path(), "type": "box", "name": "b"}]}
    )
    assert set(created["results"][0]) <= summary_keys
    assert created["results"][0]["type"] == "box"
    copied = client.ok("node_copy", {"paths": [f"{geo.path()}/b"], "to_parent": geo.path()})
    assert set(copied["results"][0]) <= summary_keys
    built = client.ok("network_build", {"parent": geo.path(), "data": {"s": {"type": "sphere"}}})
    assert set(built["nodes"][0]) <= summary_keys


def test_full_echo_omits_values_the_creation_script_set(client):
    """A light's creation script sets s, scale, dimmer and ramps; they are not the call's
    edits (review 11 B5). node_info still reports them as non-default."""
    result = client.ok(
        "node_create",
        {
            "items": [{"parent": "/obj", "type": "hlight", "parms": {"light_intensity": 2}}],
            "return": "full",
        },
    )
    rows = result["results"][0]["parms"]
    assert [row["name"] for row in rows] == ["light_intensity"]
    bare = client.ok(
        "node_create", {"items": [{"parent": "/obj", "type": "hlight"}], "return": "full"}
    )
    assert bare["results"][0]["parms"] == []
    info = client.ok("node_info", {"paths": bare["created"]})["nodes"][0]
    assert {"s", "dimmer"} <= {row["name"] for row in info["parms"]}


def test_batch_errors_share_one_shape(client):
    """Review 10 §4: every batch tool prefixes items[i] (<path>) and reports detail
    {item, path, rolled_back} with rolled_back as actually performed."""
    geo, box, xform, null = make_chain()
    cases = [
        (
            "node_create",
            [{"parent": "/obj/geo1", "type": "sphere"}, {"parent": "/obj/geo1", "type": "nope"}],
            "/obj/geo1",
        ),
        (
            "node_edit",
            [{"path": box.path(), "comment": "x"}, {"path": xform.path(), "name": "bad name"}],
            xform.path(),
        ),
        (
            "node_connect",
            [
                {"from": box.path(), "to": null.path()},
                {"from": box.path(), "to": xform.path(), "to_input": 9},
            ],
            xform.path(),
        ),
        (
            "parm_set",
            [
                {"path": f"{box.path()}/sizex", "value": 4},
                {"path": f"{box.path()}/sizey", "value": "x"},
            ],
            f"{box.path()}/sizey",
        ),
    ]
    for tool, items, path in cases:
        error = client.error(tool, {"items": items})
        assert error["message"].startswith(f"items[1] ({path}): "), (tool, error["message"])
        detail = error["detail"]
        assert (detail["item"], detail["path"], detail["rolled_back"]) == (1, path, True), tool
        result = client.ok(tool, {"items": items, "partial": True})
        row = result["results"][1]["error"]
        assert row["message"].startswith(f"items[1] ({path}): "), tool
        assert row["detail"]["item"] == 1 and row["detail"]["path"] == path, tool
        assert row["detail"]["rolled_back"] is True, tool
    assert box.comment() == "x" and null.inputs()[0] == box  # the partial runs kept item 0
    assert box.parm("sizex").eval() == 4.0
    # A one-item call has the same shape.
    error = client.error("node_edit", {"items": [{"path": xform.path(), "name": "bad name"}]})
    assert error["message"].startswith(f"items[0] ({xform.path()}): ")
    assert error["detail"]["item"] == 0 and error["detail"]["rolled_back"] is True


def test_batch_rollback_reports_a_failed_compensation(client, monkeypatch):
    """rolled_back is false when an undo step itself fails (never assumed)."""
    from hocuspocus.host.tools import nodes

    geo, box, xform, null = make_chain()
    original = nodes.Rollback.add

    def add(self, action):
        def broken():
            raise RuntimeError("compensation failed")

        original(self, broken)

    monkeypatch.setattr(nodes.Rollback, "add", add)
    error = client.error(
        "node_edit",
        {"items": [{"path": box.path(), "comment": "x"}, {"path": "/obj/geo1/nope"}]},
    )
    assert error["detail"]["rolled_back"] is False


# -- node_edit spare_parms (review 11 B9) ------------------------------------------


def test_edit_adds_and_removes_spare_parms(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    grid = geo.createNode("grid", "grid1")
    wrangle = geo.createNode("attribwrangle", "w")
    wrangle.setInput(0, grid)
    wrangle.parm("snippet").set('f@glue = chf("glue");\ni@mode = chi("mode");')
    spare = {
        "add": [
            {"name": "glue", "type": "float", "label": "Glue", "default": 2.5, "min": 0,
             "max": 10, "help": "Glue strength.", "folder": "Controls"},
            {"name": "mode", "type": "menu", "menu_items": [
                {"token": "soft", "label": "Soft"}, {"token": "hard", "label": "Hard"}],
             "default": "hard", "folder": "Controls"},
            {"name": "enable", "type": "toggle", "default": True},
            {"name": "offset", "type": "vector", "default": [0, 1, 0]},
            {"name": "tint", "type": "color"},
            {"name": "reset", "type": "button"},
        ]
    }  # fmt: skip
    result = client.ok("node_edit", {"items": [{"path": wrangle.path(), "spare_parms": spare}]})
    added = result["results"][0]["spare_parms"]["added"]
    assert added == [
        f"{wrangle.path()}/{n}" for n in ("glue", "mode", "enable", "offset", "tint", "reset")
    ]
    glue = wrangle.parm("glue")
    assert glue.eval() == 2.5 and glue.isSpare()
    template = glue.parmTemplate()
    assert (template.minValue(), template.maxValue(), template.help()) == (0, 10, "Glue strength.")
    assert wrangle.parm("mode").evalAsString() == "hard"
    assert wrangle.parm("enable").eval() == 1
    assert wrangle.parmTuple("offset").eval() == (0.0, 1.0, 0.0)
    assert len(wrangle.parmTuple("tint")) == 3
    assert wrangle.parmTemplateGroup().findFolder("Controls") is not None
    geometry = wrangle.geometry()
    assert geometry.points()[0].attribValue("glue") == 2.5  # chf("glue") resolves
    assert geometry.points()[0].attribValue("mode") == 1
    got = client.ok("parm_get", {"paths": [f"{wrangle.path()}/glue"], "include": ["template"]})
    assert got["parms"][0]["template"]["max"] == 10
    removed = client.ok(
        "node_edit",
        {"items": [{"path": wrangle.path(), "spare_parms": {"remove": ["glue", "tint"]}}]},
    )
    assert removed["results"][0]["spare_parms"]["removed"] == [
        f"{wrangle.path()}/glue",
        f"{wrangle.path()}/tint",
    ]
    assert wrangle.parm("glue") is None and wrangle.parm("mode") is not None
    undone = client.ok("undo", {"action": "undo"})
    assert undone["performed"] and wrangle.parm("glue") is not None


def test_edit_spare_parms_validation_and_rollback(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    null = geo.createNode("null", "CTRL")
    error = client.error(
        "node_edit",
        {
            "items": [
                {"path": null.path(), "spare_parms": {"add": [{"name": "a", "type": "float"}]}},
                {"path": null.path(), "spare_parms": {"add": [{"name": "b", "type": "ramp"}]}},
            ]
        },
    )
    assert error["code"] == "invalid_argument" and "float" in error["hint"]
    assert error["detail"]["rolled_back"] is True and null.parm("a") is None
    for bad, code in (
        ({"add": [{"name": "1x", "type": "float"}]}, "invalid_argument"),
        ({"add": [{"name": "copyinput", "type": "float"}]}, "name_collision"),
        ({"add": [{"name": "m", "type": "menu"}]}, "invalid_argument"),
        ({"add": [{"name": "f", "type": "float", "min": 2, "max": 1}]}, "invalid_argument"),
        ({"add": [{"name": "f", "type": "float", "default": "x"}]}, "invalid_value"),
        ({"remove": ["copyinput"]}, "invalid_argument"),
        ({"remove": ["nope"]}, "parm_not_found"),
    ):
        error = client.error("node_edit", {"items": [{"path": null.path(), "spare_parms": bad}]})
        assert error["code"] == code, (bad, error)
    _geo, mountain = make_locked_mountain()
    inner = mountain.children()[0].path()
    add = {"add": [{"name": "g", "type": "float"}]}
    error = client.error("node_edit", {"items": [{"path": inner, "spare_parms": add}]})
    assert error["code"] == "locked"


def test_parm_not_found_on_a_null_points_at_spare_parms(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    null = geo.createNode("null", "CTRL")
    error = client.error("parm_set", {"items": [{"path": f"{null.path()}/glue", "value": 1}]})
    assert error["code"] == "parm_not_found" and "spare_parms" in error["hint"]
    error = client.error("parm_get", {"paths": ["/obj/geo1/glue"]})
    assert "spare_parms" in error["hint"]


# -- node_create block pairing (review 11 B12) -------------------------------------


def test_create_pairs_block_end_with_its_begin(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    parent = geo.path()
    result = client.ok(
        "node_create",
        {
            "items": [
                {"parent": parent, "type": "box", "name": "src"},
                {
                    "parent": parent,
                    "type": "block_begin",
                    "name": "loop_begin",
                    "parms": {"method": "input"},
                    "inputs": [{"index": 0, "from": "src"}],
                },
                {
                    "parent": parent,
                    "type": "xform",
                    "name": "shift",
                    "parms": {"tx": 1},
                    "inputs": [{"index": 0, "from": "loop_begin"}],
                },
                {
                    "parent": parent,
                    "type": "block_end",
                    "name": "loop_end",
                    "parms": {"itermethod": "count", "iterations": 4, "method": "merge"},
                    "inputs": [{"index": 0, "from": "shift"}],
                    "flags": {"display": True},
                },
            ]
        },
    )
    end_row = result["results"][3]
    assert end_row["paired_with"] == f"{parent}/loop_begin"
    assert not end_row.get("errors"), end_row
    end = geo.node("loop_end")
    assert end.parm("blockpath").eval() == "../loop_begin"
    assert end.parm("templatepath").eval() == "../loop_begin"
    assert geo.node("loop_begin").parm("blockpath").eval() == "../loop_end"
    assert len(end.geometry().prims()) == 24  # 4 iterations of a 6-face box, merged
    assert "paired_with" not in result["results"][0]


def test_create_pairs_with_the_only_unpaired_begin(client):
    geo = hou.node("/obj").createNode("geo", "geo1")
    begin = geo.createNode("block_begin", "b")
    result = client.ok("node_create", {"items": [{"parent": geo.path(), "type": "block_end"}]})
    assert result["results"][0]["paired_with"] == begin.path()
    explicit = client.ok(
        "node_create",
        {"items": [{"parent": geo.path(), "type": "block_end", "parms": {"blockpath": "../x"}}]},
    )
    assert "paired_with" not in explicit["results"][0]
    assert hou.node(explicit["created"][0]).parm("blockpath").eval() == "../x"
