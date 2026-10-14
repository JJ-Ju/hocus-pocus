"""``edit`` (spec-2.0 §2.4) against real Houdini: every op type, ``$id`` chains, dry runs
that change nothing, rollback of a failing op, ``partial``, ``build`` with ``press``,
``select``, the summary and full echoes, and the review-07 build in one call."""

from __future__ import annotations

import json
from typing import Any

import pytest

hou = pytest.importorskip("hou")


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


REVIEW_07 = [
    {"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "terrain"},
    {"op": "create", "id": "box", "parent": "$geo", "type": "box"},
    {
        "op": "create",
        "id": "mtn",
        "parent": "$geo",
        "type": "mountain",
        "inputs": [{"index": 0, "from": "$box"}],
        "parms": {"height": 0.5},
    },
    {
        "op": "create",
        "id": "sub",
        "parent": "$geo",
        "type": "subdivide",
        "inputs": [{"index": 0, "from": "$mtn"}],
        "parms": {"iterations": 2},
    },
    {
        "op": "create",
        "parent": "$geo",
        "type": "null",
        "name": "OUT",
        "inputs": [{"index": 0, "from": "$sub"}],
        "flags": {"display": True, "render": True},
    },
]


def _undo_labels() -> list[str]:
    return list(hou.undos.undoLabels())


# -- the review-07 build -----------------------------------------------------------------


def test_review_07_build_in_one_call_under_1_kb(v2_client):
    envelope = v2_client.call("edit", {"ops": REVIEW_07})
    assert envelope["ok"], envelope
    result = envelope["result"]
    size = _size(result)
    print(f"\n[edit] review-07 build (geo, box, mountain, subdivide, OUT): {size} bytes")
    assert size < 1024, (size, result)
    assert envelope["_meta"]["undo_label"] == "HocusPocus: edit 5 ops"
    assert [r["op"] for r in result["results"]] == ["create"] * 5
    assert [r.get("id") for r in result["results"]] == ["geo", "box", "mtn", "sub", None]
    paths = [r["path"] for r in result["results"]]
    assert paths == [
        "/obj/terrain",
        "/obj/terrain/box1",
        "/obj/terrain/mountain1",
        "/obj/terrain/subdivide1",
        "/obj/terrain/OUT",
    ]
    assert [n["path"] for n in result["nodes"]] == paths
    for row in result["nodes"]:
        assert set(row) >= {"path", "type", "errors", "warnings", "cook_state"}, row
        assert row["errors"] == [], row
    assert any("cook_ms" in row for row in result["nodes"][1:])
    out = hou.node("/obj/terrain/OUT")
    assert out.isDisplayFlagSet() and out.inputs()[0].path() == "/obj/terrain/subdivide1"
    assert hou.node("/obj/terrain/mountain1").inputs()[0].name() == "box1"
    assert hou.node("/obj/terrain/subdivide1").parm("iterations").eval() == 2
    assert result["dirty"] is True
    # One undo step takes the whole build back.
    v2_client.ok("undo", {"action": "undo"})
    assert hou.node("/obj/terrain") is None


def test_edit_needs_the_v2_profile(client):
    error = client.error("edit", {"ops": [{"op": "select", "paths": []}]})
    assert error["code"] == "invalid_argument" and 'profile = "v2"' in error["hint"]


# -- every op type ----------------------------------------------------------------------


def test_every_op_type_in_one_call(v2_client):
    geo = hou.node("/obj").createNode("geo", "g")
    old = geo.createNode("box", "old")
    keep = geo.createNode("xform", "keep")
    keep.setInput(0, old)
    result = v2_client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "s", "parent": geo.path(), "type": "sphere", "name": "s"},
                {"op": "create", "id": "m", "parent": geo.path(), "type": "merge"},
                {"op": "connect", "from": "$s", "to": "$m", "to_input": "next"},
                {"op": "set", "path": "$s/rad", "value": [2, 2, 2]},
                {"op": "set", "node": "$s", "parms": {"scale": 0.5}},
                {
                    "op": "node",
                    "id": "n",
                    "path": "$m",
                    "name": "combine",
                    "comment": "joined",
                    "color": [1, 0, 0],
                    "spare_parms": {"add": [{"name": "seed", "type": "int", "default": 3}]},
                },
                {"op": "set", "path": "$n/seed", "value": 7},
                {"op": "copy", "id": "c", "paths": ["$s"], "to_parent": geo.path()},
                {"op": "layout", "parent": geo.path()},
                {
                    "op": "build",
                    "parent": geo.path(),
                    "data": {"grid1": {"type": "grid"}},
                    "layout": False,
                },
                {"op": "delete", "path": old.path()},
                {"op": "select", "paths": ["$c"]},
            ]
        },
    )
    rows = result["results"]
    assert [r["op"] for r in rows] == [
        "create", "create", "connect", "set", "set", "node", "set", "copy", "layout", "build",
        "delete", "select",
    ]  # fmt: skip
    combine = hou.node("/obj/g/combine")
    sphere = hou.node("/obj/g/s")
    assert combine is not None and combine.inputs()[0] == sphere
    # Rows name the final paths: merge1 was renamed by a later op.
    assert rows[2] == {"op": "connect", "path": "/obj/g/combine", "input": 0, "from": "/obj/g/s"}
    assert sphere.parmTuple("rad").eval() == (2.0, 2.0, 2.0)
    assert rows[3]["path"] == "/obj/g/s/rad" and rows[3]["value"] == [2.0, 2.0, 2.0]
    assert sphere.parm("scale").eval() == 0.5 and rows[4]["values"] == {"scale": 0.5}
    assert rows[5]["path"] == "/obj/g/combine" and rows[5]["old_path"] == "/obj/g/merge1"
    assert rows[5]["spare_parms"]["added"] == ["/obj/g/combine/seed"]
    assert combine.comment() == "joined" and combine.parm("seed").eval() == 7
    assert rows[6]["path"] == "/obj/g/combine/seed"
    (copy_path,) = rows[7]["paths"]
    assert hou.node(copy_path).type().name() == "sphere"
    assert rows[8]["path"] == "/obj/g" and rows[8]["count"] >= 4
    assert rows[9]["created"] == ["/obj/g/grid1"] and hou.node("/obj/g/grid1") is not None
    assert rows[10]["deleted"] == ["/obj/g/old"] and hou.node("/obj/g/old") is None
    assert rows[11]["selected"] == [copy_path]
    assert [n.path() for n in hou.selectedNodes()] == [copy_path]
    # Each touched node once, the deleted one left out; keep was rewired to nothing.
    touched = [n["path"] for n in result["nodes"]]
    assert len(touched) == len(set(touched)) and "/obj/g/old" not in touched
    assert "/obj/g/combine" in touched and copy_path in touched


def test_id_chain_create_connect_set(v2_client):
    hou.node("/obj").createNode("geo", "g")
    result = v2_client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "a", "parent": "/obj/g", "type": "box"},
                {"op": "create", "id": "b", "parent": "/obj/g", "type": "xform"},
                {"op": "connect", "from": "$a", "to": "$b"},
                {"op": "set", "path": "$b/ty", "expression": "$F * 0.1"},
            ]
        },
    )
    xform = hou.node(result["results"][1]["path"])
    assert xform.inputs()[0].path() == result["results"][0]["path"]
    assert xform.parm("ty").expression() == "$F * 0.1"  # $F is Houdini's, not an id
    assert result["results"][3]["expression"] == "$F * 0.1"


def test_unknown_or_forward_ids_are_refused(v2_client):
    hou.node("/obj").createNode("geo", "g")
    unknown = v2_client.error("edit", {"ops": [{"op": "create", "parent": "$nope", "type": "box"}]})
    assert unknown["code"] == "invalid_argument" and "$nope" in unknown["message"]
    assert unknown["message"].startswith("items[0] ($nope): ")
    forward = v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "connect", "from": "$a", "to": "/obj/g"},
                {"op": "create", "id": "a", "parent": "/obj/g", "type": "box"},
            ]
        },
    )
    assert forward["code"] == "invalid_argument" and "has not produced" in forward["message"]
    assert hou.node("/obj/g").children() == ()


# -- dry run ----------------------------------------------------------------------------


def test_dry_run_changes_nothing_and_returns_resolved_paths(v2_client, host):
    hou.node("/obj").createNode("geo", "terrain")
    hou.node("/obj/terrain").createNode("box", "box1")
    before = _undo_labels()
    envelope = v2_client.call(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "box", "parent": "/obj/terrain", "type": "box"},
                {"op": "create", "id": "x", "parent": "/obj/terrain", "type": "xform"},
                {"op": "connect", "from": "$box", "to": "$x"},
                {"op": "set", "path": "$x/ty", "value": 1},
                {"op": "node", "path": "$x", "name": "lift"},
                {"op": "set", "path": "/obj/terrain/lift/tx", "value": 2},
            ],
            "dry_run": True,
        },
    )
    assert envelope["ok"], envelope
    result = envelope["result"]
    assert envelope["_meta"]["undo_label"] is None
    assert result["dry_run"] is True and result["ops"] == 6
    plan = result["plan"]
    assert plan[0] == {
        "op": "create",
        "id": "box",
        "path": "/obj/terrain/box2",
        "type": "box",
        "predicted": True,
    }
    assert plan[1]["path"] == "/obj/terrain/xform1"
    assert plan[2]["from"] == "/obj/terrain/box2" and plan[2]["to"] == "/obj/terrain/xform1"
    assert plan[3]["path"] == "/obj/terrain/xform1/ty"
    assert plan[4] == {
        "op": "node",
        "path": "/obj/terrain/lift",
        "old_path": "/obj/terrain/xform1",
    }
    assert plan[5]["path"] == "/obj/terrain/lift/tx"
    assert [c.name() for c in hou.node("/obj/terrain").children()] == ["box1"]
    assert _undo_labels() == before
    # The real run produces the paths the dry run predicted.
    real = v2_client.ok(
        "edit", {"ops": [{"op": "create", "parent": "/obj/terrain", "type": "box"}]}
    )
    assert real["results"][0]["path"] == "/obj/terrain/box2"


def test_dry_run_reports_every_problem_without_changing_anything(v2_client):
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("box", "box1")
    error = v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "create", "parent": "/obj/g", "type": "box", "name": "box1"},
                {"op": "create", "id": "m", "parent": "/obj/g", "type": "mountian"},
                {"op": "set", "path": "$m/height", "value": 2},  # depends on the failed op
                {"op": "set", "path": "/obj/g/box1/sizz", "value": 2},
                {"op": "connect", "from": "/obj/g/box1", "to": "/obj/g/box1"},
            ],
            "dry_run": True,
        },
    )
    assert error["code"] == "name_collision"
    assert error["message"].startswith("items[0] (/obj/g/box1): ")
    problems = error["detail"]["problems"]
    assert [p["item"] for p in problems] == [0, 1, 3, 4]
    assert [p["code"] for p in problems] == [
        "name_collision", "node_type_not_found", "parm_not_found", "invalid_input",
    ]  # fmt: skip
    assert [c.name() for c in geo.children()] == ["box1"]


def test_validation_refuses_before_any_change(v2_client):
    """Without dry_run a plan whose fourth op is invalid changes nothing at all."""
    before = _undo_labels()
    error = v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo"},
                {"op": "create", "id": "b", "parent": "$g", "type": "box"},
                {"op": "create", "parent": "$g", "type": "xform", "inputs": [{"from": "$b"}]},
                {"op": "create", "parent": "$g", "type": "sphere", "parms": {"radiu": 1}},
            ]
        },
    )
    assert error["code"] == "parm_not_found" and error["message"].startswith("items[3] ")
    assert "rad" in error["candidates"]
    assert error["detail"]["rolled_back"] is True
    assert hou.node("/obj").children() == () and _undo_labels() == before


def test_dry_run_is_allowed_in_read_only_mode(v2_client, host):
    host.config.read_only = True
    result = v2_client.ok(
        "edit", {"ops": [{"op": "create", "parent": "/obj", "type": "geo"}], "dry_run": True}
    )
    assert result["plan"][0]["path"] == "/obj/geo1"
    error = v2_client.error("edit", {"ops": [{"op": "create", "parent": "/obj", "type": "geo"}]})
    assert error["code"] == "read_only"


# -- rollback and partial -----------------------------------------------------------------


def test_a_failing_op_in_the_middle_rolls_everything_back(v2_client):
    geo = hou.node("/obj").createNode("geo", "g")
    victim = geo.createNode("box", "victim")
    before = _undo_labels()
    error = v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "s", "parent": "/obj/g", "type": "sphere"},
                {"op": "delete", "path": victim.path()},
                {"op": "set", "path": "$s/rad", "value": "big"},  # fails when it runs
                {"op": "create", "parent": "/obj/g", "type": "null"},
            ]
        },
    )
    assert error["code"] == "invalid_value"
    assert error["message"].startswith("items[2] (/obj/g/sphere1/rad): ")
    # A delete cannot be compensated; the undo of the whole step brought it back.
    assert error["detail"]["rolled_back"] is True
    assert [c.name() for c in geo.children()] == ["victim"]
    assert _undo_labels() == before


def test_rollback_without_a_delete_is_compensation(v2_client):
    geo = hou.node("/obj").createNode("geo", "g")
    box = geo.createNode("box", "box1")
    error = v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "set", "path": f"{box.path()}/sizex", "value": 4},
                {"op": "node", "path": box.path(), "comment": "x"},
                {"op": "set", "path": f"{box.path()}/sizey", "value": "x"},
            ]
        },
    )
    detail = error["detail"]
    assert (detail["item"], detail["path"], detail["rolled_back"]) == (
        2,
        f"{box.path()}/sizey",
        True,
    )
    assert box.parm("sizex").eval() == 1.0 and box.comment() == ""


def test_partial_keeps_the_ops_that_worked(v2_client):
    hou.node("/obj").createNode("geo", "g")
    result = v2_client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "a", "parent": "/obj/g", "type": "box"},
                {"op": "create", "id": "bad", "parent": "/obj/g", "type": "nope"},
                {"op": "set", "path": "$a/sizex", "value": 3},
                {"op": "connect", "from": "$a", "to": "$bad"},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 2
    rows = result["results"]
    assert rows[1]["error"]["code"] == "node_type_not_found"
    assert rows[1]["error"]["detail"]["rolled_back"] is True
    assert rows[3]["error"]["code"] == "invalid_argument"
    assert hou.node("/obj/g/box1").parm("sizex").eval() == 3.0
    assert [c.name() for c in hou.node("/obj/g").children()] == ["box1"]


# -- build, select ---------------------------------------------------------------------


def test_build_op_with_press_runs_the_callbacks(v2_client):
    result = v2_client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "parent": "/obj", "type": "geo", "name": "pyro"},
                {
                    "op": "build",
                    "parent": "$g",
                    "data": {
                        "sphere1": {"type": "sphere"},
                        "src": {
                            "type": "pyrosource",
                            "parms": {"initialize": "source"},
                            "inputs": [{"from": "sphere1", "from_index": 0, "to_index": 0}],
                        },
                    },
                    "press": {"src": ["initialize"]},
                },
            ]
        },
    )
    src = hou.node("/obj/pyro/src")
    assert src.parm("initialize").evalAsString() == "none"
    assert src.parm("attributes").eval() == 2
    build = result["results"][1]
    assert build["pressed"] == ["/obj/pyro/src/initialize"]
    assert build["side_effects"]["/obj/pyro/src"]["initialize"] == ["source", "none"]
    assert build["created"] == ["/obj/pyro/sphere1", "/obj/pyro/src"]
    v2_client.ok("undo", {"action": "undo"})
    assert hou.node("/obj/pyro") is None


def test_select_op_sets_the_selection_and_rolls_back(v2_client):
    geo = hou.node("/obj").createNode("geo", "g")
    box = geo.createNode("box", "box1")
    box.setSelected(True, clear_all_selected=True)
    result = v2_client.ok("edit", {"ops": [{"op": "select", "paths": [geo.path()]}]})
    assert result["results"][0]["selected"] == [geo.path()]
    assert hou.selectedNodes() == (geo,)
    v2_client.error(
        "edit",
        {
            "ops": [
                {"op": "select", "paths": [box.path()]},
                {"op": "set", "path": f"{box.path()}/sizex", "value": "x"},
            ]
        },
    )
    assert hou.selectedNodes() == (geo,)


# -- echo ------------------------------------------------------------------------------


def test_summary_and_full_echo(v2_client):
    hou.node("/obj").createNode("geo", "g")
    ops = [
        {"op": "create", "id": "b", "parent": "/obj/g", "type": "box", "parms": {"sizex": 2}},
        {"op": "create", "parent": "/obj/g", "type": "xform", "inputs": [{"from": "$b"}],
         "flags": {"display": True}},
    ]  # fmt: skip
    summary = v2_client.ok("edit", {"ops": ops})
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.node("/obj").createNode("geo", "g")
    full = v2_client.ok("edit", {"ops": ops, "return": "full"})
    assert "flags" not in summary["nodes"][0] and "parms" not in summary["results"][0]
    assert full["nodes"][1]["flags"]["display"] is True
    assert [r["name"] for r in full["results"][0]["parms"]] == ["size"]
    assert set(full["nodes"][0]) >= {"path", "name", "type", "errors", "warnings", "messages"}
    assert _size(full) > _size(summary)


def test_errors_reported_once_in_summary(v2_client):
    hou.node("/obj").createNode("geo", "g")
    result = v2_client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "w", "parent": "/obj/g", "type": "attribwrangle",
                 "parms": {"snippet": "@P.y = ;"}},
                {"op": "create", "parent": "/obj/g", "type": "null", "inputs": [{"from": "$w"}]},
            ]
        },
    )  # fmt: skip
    first, second = result["nodes"]
    assert first["errors"], first
    assert second.get("errors_same_as") == first["path"] or second.get("errors"), second
