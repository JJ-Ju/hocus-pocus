"""``search`` (spec-2.0 §2.3) against real Houdini: ``kind: types`` is ``node_type_search``
and ``kind: nodes`` is ``node_find``; with ``detail: full`` byte for byte plus only ``kind``,
``kind: nodes`` by default compact (spec-2.0 M4 "read shapes": defaults and empties left
out, the shared category in ``common``, no ``kind`` or named ``root`` echo); types pages by
cursor."""

from __future__ import annotations

import json
from typing import Any

import pytest

hou = pytest.importorskip("hou")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _same(client, kind: str, options: dict[str, Any], tool: str, args: dict[str, Any]) -> dict:
    """``detail: full`` is the 1.4 tool's result plus only ``kind``, byte for byte; returns
    the compact result of the same call."""
    old = client.ok(tool, args)
    new = client.ok("search", {"kind": kind, **options, "detail": "full"})
    assert list(new)[0] == "kind" and new["kind"] == kind
    rest = {k: v for k, v in new.items() if k != "kind"}
    assert _bytes(rest) == _bytes(old), (kind, set(rest) ^ set(old))
    compact = client.ok("search", {"kind": kind, **options})
    assert ("kind" in compact) == (kind == "types"), compact  # nodes: compact
    return compact


def _scene():
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box", "box1")
    reader = geo.createNode("file", "read_cache")
    reader.parm("file").set("$HIP/missing_cache.bgeo.sc")
    merge = geo.createNode("merge", "merge1")
    merge.setInput(0, box)
    merge.setInput(1, reader)
    merge.setDisplayFlag(True)
    hou.node("/obj").createNode("geo", "geo2").createNode("sphere", "ball")
    return geo


def test_types_is_node_type_search(v2_client):
    new = _same(v2_client, "types", {"query": "scatter"}, "node_type_search", {"query": "scatter"})
    assert new["results"][0]["name"].startswith("scatter")
    options = {"query": "noise", "category": "Vop", "limit": 500, "current_only": False}
    _same(v2_client, "types", options, "node_type_search", options)
    options = {"query": "copy to points", "include_hidden": True, "limit": 1000}
    _same(v2_client, "types", options, "node_type_search", options)


def test_types_pages_by_cursor(v2_client):
    whole = v2_client.ok("node_type_search", {"query": "noise", "limit": 60})
    assert whole["total"] > 12, whole["total"]
    first = v2_client.ok("search", {"kind": "types", "query": "noise", "limit": 5,
                                    "detail": "full"})  # fmt: skip
    rest = {k: v for k, v in first.items() if k not in ("kind", "next_cursor")}
    assert rest == v2_client.ok("node_type_search", {"query": "noise", "limit": 5})
    assert first["next_cursor"] == "t:5"
    compact = v2_client.ok("search", {"kind": "types", "query": "noise", "limit": 5})
    assert compact["next_cursor"] == "t:5"
    names = [row["name"] for row in compact["results"]]
    cursor = compact["next_cursor"]
    while cursor and len(names) < 12:
        page = v2_client.ok(
            "search", {"kind": "types", "query": "noise", "limit": 5, "cursor": cursor}
        )
        assert page["total"] == whole["total"]
        names += [row["name"] for row in page["results"]]
        cursor = page.get("next_cursor")
    assert names[:12] == [row["name"] for row in whole["results"][:12]]
    last = v2_client.ok(
        "search", {"kind": "types", "query": "scatter", "limit": 1000}
    )  # everything fits: no cursor
    assert "next_cursor" not in last
    error = v2_client.error("search", {"kind": "types", "query": "noise", "cursor": "abc"})
    assert error["code"] == "invalid_argument" and "cursor" in error["message"]
    error = v2_client.error(
        "search", {"kind": "types", "query": "noise", "limit": 500, "cursor": "t:600"}
    )
    assert error["code"] == "invalid_argument" and "1000" in error["message"]


def test_nodes_is_node_find(v2_client):
    _scene()
    new = _same(v2_client, "nodes", {}, "node_find", {})
    assert new["root"] == "/" and new["total"] >= 6  # root not named: echoed
    _same(v2_client, "nodes", {"root": "/obj", "query": "*file*"}, "node_find",
          {"root": "/obj", "type": "*file*"})  # fmt: skip
    options = {"root": "/obj/geo1", "pattern": "*1", "category": "Sop", "flags": {"display": True}}
    found = _same(v2_client, "nodes", options, "node_find", options)
    assert found == {
        "nodes": [
            {
                "path": "/obj/geo1/merge1",
                "type": "Sop/merge",
                "flags": ["display"],
                "input_count": 2,
            }
        ],
        "total": 1,
    }, found  # fmt: skip  (one row: its category is in its type)
    _same(v2_client, "nodes", {"root": "/obj", "has_errors": False, "limit": 2}, "node_find",
          {"root": "/obj", "has_errors": False, "limit": 2})  # fmt: skip


def test_nodes_rows_are_compact(v2_client):
    """spec-2.0 M4: {path, type} plus flags (the list of those on), has_errors only when
    true, child_count and input_count only above 0; the category most rows share in
    common, another category in the type (Object/geo)."""
    _scene()
    v2_client.ok("cook", {"paths": ["/obj/geo1/read_cache"]})
    old = v2_client.ok("node_find", {"root": "/obj"})
    new = v2_client.ok("search", {"kind": "nodes", "root": "/obj"})
    assert "root" not in new and new["total"] == old["total"]
    assert new["common"] == {"category": "Sop"}
    rows = {row["path"]: row for row in new["nodes"]}
    assert [row["path"] for row in new["nodes"]] == [row["path"] for row in old["nodes"]]
    assert rows["/obj/geo1"] == {
        "path": "/obj/geo1", "type": "Object/geo", "flags": ["display"], "child_count": 3,
    }, rows["/obj/geo1"]  # fmt: skip
    assert rows["/obj/geo2/ball"]["type"] == "sphere"  # the common category: no prefix
    full = {row["path"]: row for row in old["nodes"]}
    for path, row in rows.items():
        want = full[path]
        assert row.get("has_errors", False) == want["has_errors"], (row, want)
        assert row.get("child_count", 0) == want["child_count"]
        assert row.get("input_count", 0) == want["input_count"]
        assert row.get("flags", []) == [k for k, v in want["flags"].items() if v]
    assert rows["/obj/geo1/read_cache"]["has_errors"] is True
    assert len(_bytes(new)) <= 0.6 * len(_bytes(old)), (len(_bytes(new)), len(_bytes(old)))


def test_nodes_pages_like_node_find(v2_client):
    _scene()
    first = _same(v2_client, "nodes", {"root": "/obj", "limit": 2}, "node_find",
                  {"root": "/obj", "limit": 2})  # fmt: skip
    old = v2_client.ok("node_find", {"root": "/obj", "limit": 2})
    assert first["next_cursor"] == old["next_cursor"].removeprefix("after:")
    cursor = first["next_cursor"]
    second = _same(v2_client, "nodes", {"root": "/obj", "limit": 2, "cursor": cursor},
                   "node_find", {"root": "/obj", "limit": 2, "cursor": old["next_cursor"]})  # fmt: skip
    legacy = v2_client.ok(
        "search", {"kind": "nodes", "root": "/obj", "limit": 2, "cursor": old["next_cursor"]}
    )
    assert legacy == second


def test_search_errors_name_the_options(v2_client):
    error = v2_client.error("search", {"kind": "types", "query": "box", "root": "/obj"})
    assert error["code"] == "invalid_argument" and "does not take root" in error["message"]
    assert "current_only" in error["hint"]
    error = v2_client.error("search", {"kind": "nodes", "current_only": True})
    assert error["code"] == "invalid_argument" and "does not take current_only" in error["message"]
    error = v2_client.error("search", {"kind": "types"})
    assert error["code"] == "invalid_argument" and "needs query" in error["message"]
    error = v2_client.error("search", {"kind": "parms", "query": "x"})
    assert error["code"] == "invalid_argument" and error["candidates"] == ["types", "nodes"]
    error = v2_client.error("search", {"kind": "nodes", "root": "/obj/nope"})
    assert error["code"] == "node_not_found"
    error = v2_client.error("search", {"kind": "nodes", "detail": "folders"})
    assert error["code"] == "invalid_argument" and "detail" in error["message"]


def test_a_full_host_runs_search_and_refuses_the_1x_finders(client):
    """spec-2.0 §8: node_find and node_type_search name their search kind."""
    assert client.ok("search", {"kind": "types", "query": "box"})["results"]
    error = client.error("node_type_search", {"query": "box"})
    assert error["code"] == "invalid_argument" and "search kind: types" in error["hint"]
    assert "search kind: nodes" in client.error("node_find", {})["hint"]
