"""``search`` (spec-2.0 §2.3) against real Houdini: ``kind: types`` is ``node_type_search``
and ``kind: nodes`` is ``node_find``, byte for byte plus only ``kind``; types pages by
cursor."""

from __future__ import annotations

import json
from typing import Any

import pytest

hou = pytest.importorskip("hou")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _same(client, kind: str, options: dict[str, Any], tool: str, args: dict[str, Any]) -> dict:
    old = client.ok(tool, args)
    new = client.ok("search", {"kind": kind, **options})
    assert list(new)[0] == "kind" and new["kind"] == kind
    rest = {k: v for k, v in new.items() if k != "kind"}
    assert _bytes(rest) == _bytes(old), (kind, set(rest) ^ set(old))
    return new


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
    first = v2_client.ok("search", {"kind": "types", "query": "noise", "limit": 5})
    rest = {k: v for k, v in first.items() if k not in ("kind", "next_cursor")}
    assert rest == v2_client.ok("node_type_search", {"query": "noise", "limit": 5})
    assert first["next_cursor"] == "t:5"
    names = [row["name"] for row in first["results"]]
    cursor = first["next_cursor"]
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
    assert new["root"] == "/" and new["total"] >= 6
    _same(v2_client, "nodes", {"root": "/obj", "query": "*file*"}, "node_find",
          {"root": "/obj", "type": "*file*"})  # fmt: skip
    options = {"root": "/obj/geo1", "pattern": "*1", "category": "Sop", "flags": {"display": True}}
    found = _same(v2_client, "nodes", options, "node_find", options)
    assert [row["path"] for row in found["nodes"]] == ["/obj/geo1/merge1"]
    _same(v2_client, "nodes", {"root": "/obj", "has_errors": False, "limit": 2}, "node_find",
          {"root": "/obj", "has_errors": False, "limit": 2})  # fmt: skip


def test_nodes_pages_like_node_find(v2_client):
    _scene()
    first = _same(v2_client, "nodes", {"root": "/obj", "limit": 2}, "node_find",
                  {"root": "/obj", "limit": 2})  # fmt: skip
    cursor = first["next_cursor"]
    _same(v2_client, "nodes", {"root": "/obj", "limit": 2, "cursor": cursor}, "node_find",
          {"root": "/obj", "limit": 2, "cursor": cursor})  # fmt: skip


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


def test_a_full_host_refuses_search(client):
    error = client.error("search", {"kind": "types", "query": "box"})
    assert error["code"] == "invalid_argument" and "v2-profile" in error["message"]
