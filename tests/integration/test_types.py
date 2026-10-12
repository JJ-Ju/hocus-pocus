"""node_type_search and node_type_info against real Houdini (bible §4.7, §5.4, §5.15)."""

from __future__ import annotations

import json
import time

import pytest

hou = pytest.importorskip("hou")


def _names(result: dict) -> list[str]:
    return [f"{row['category']}/{row['name']}" for row in result["results"]]


# -- search -----------------------------------------------------------------------


def test_search_index_is_cached(client):
    from hocuspocus.host.tools import types

    started = time.perf_counter()
    client.ok("node_type_search", {"query": "box"})
    first = time.perf_counter() - started
    builds = types.index_stats()["builds"]
    started = time.perf_counter()
    client.ok("node_type_search", {"query": "sphere"})
    second = time.perf_counter() - started
    assert types.index_stats()["builds"] == builds
    assert types.index_stats()["types"] > 4000
    assert second < 1.0, (first, second)


@pytest.mark.parametrize(
    ("query", "category", "expected"),
    [
        ("scatter", None, "Sop/scatter::2.0"),
        ("scatter", "Sop", "Sop/scatter::2.0"),
        ("copy to points", None, "Sop/copytopoints::2.0"),
        ("copy to points", "Sop", "Sop/copytopoints::2.0"),
        ("polyreduce", None, "Sop/polyreduce::2.0"),
        ("Box", "Sop", "Sop/box"),
    ],
)
def test_search_ranks_exact_current_version_first(client, query, category, expected):
    args = {"query": query, "limit": 5}
    if category:
        args["category"] = category
    result = client.ok("node_type_search", args)
    assert _names(result)[0] == expected, _names(result)
    top = result["results"][0]
    assert top["is_current_version"] is True
    assert top["deprecated"] is False
    assert result["total"] >= len(result["results"])


def test_search_rows_and_older_versions(client):
    result = client.ok("node_type_search", {"query": "scatter", "category": "Sop", "limit": 3})
    first, second = result["results"][:2]
    assert first["name"] == "scatter::2.0"
    assert first["label"] == "Scatter"
    assert first["version"] == "2.0"
    assert first["inputs"] == {"min": 1, "max": 1}
    assert "points" in first["description"].lower()
    assert set(first) >= {"name", "label", "category", "version", "is_current_version",
                          "description", "inputs", "deprecated"}  # fmt: skip
    assert second["name"] == "scatter"
    assert second["is_current_version"] is False
    assert second["current"] == "scatter::2.0"


def test_search_by_label_words_and_category_filter(client):
    result = client.ok("node_type_search", {"query": "noise", "category": "Vop", "limit": 5})
    assert result["results"] and all(r["category"] == "Vop" for r in result["results"])
    lop = client.ok("node_type_search", {"query": "sublayer", "category": "Lop"})
    assert lop["results"][0]["name"] == "sublayer"


def test_search_hidden(client):
    hidden = [
        t
        for t in hou.sopNodeTypeCategory().nodeTypes().values()
        if t.hidden() and not t.nameComponents()[0]
    ]
    target = hidden[0].name()
    default = client.ok("node_type_search", {"query": target, "category": "Sop"})
    assert target not in [r["name"] for r in default["results"]]
    shown = client.ok(
        "node_type_search", {"query": target, "category": "Sop", "include_hidden": True}
    )
    row = next(r for r in shown["results"] if r["name"] == target)
    assert row["hidden"] is True


def test_search_errors_and_empty(client):
    assert client.error("node_type_search", {"query": " "})["code"] == "invalid_argument"
    error = client.error("node_type_search", {"query": "box", "category": "Sops"})
    assert error["code"] == "invalid_argument" and "Sop" in error["candidates"]
    empty = client.ok("node_type_search", {"query": "zzqqxxnothing"})
    assert empty["results"] == [] and empty["total"] == 0 and empty["hint"]


# -- info -------------------------------------------------------------------------


def _assert_no_side_effects(before_children: int, before_undo: tuple) -> None:
    assert len(hou.node("/obj").children()) == before_children
    assert len(hou.node("/img").children()) == 0
    assert hou.undos.undoLabels() == before_undo


def test_info_box(client):
    before = (len(hou.node("/obj").children()), hou.undos.undoLabels())
    info = client.ok("node_type_info", {"type": "Sop/box"})
    _assert_no_side_effects(*before)
    assert info["name"] == "box" and info["category"] == "Sop" and info["label"] == "Box"
    assert info["help_url"] == "operator:Sop/box"
    assert info["description"].startswith("Creates a cube")
    assert info["inputs"] == [{"index": 0, "name": "input1", "label": "Bounding Source"}]
    assert info["outputs"][0]["name"] == "output1"
    assert info["min_inputs"] == 0 and info["max_inputs"] == 1
    parms = {p["name"]: p for p in info["parms"]}
    assert parms["size"]["components"] == ["sizex", "sizey", "sizez"]
    assert parms["size"]["default"] == [1.0, 1.0, 1.0]
    assert parms["t"]["components"] == ["tx", "ty", "tz"]
    assert parms["type"]["menu"]["items"][0] == ["poly", "Polygon"]
    assert parms["type"]["default_token"] == "poly"
    assert parms["scale"]["type"] == "float" and parms["scale"]["max"] == 10.0
    assert "help_text" not in info
    size = len(json.dumps(info, separators=(",", ":")))
    assert size < 5000, size


def test_info_component_names_match_real_parms(client):
    geo = hou.node("/obj").createNode("geo")
    for type_name in ("box", "scatter", "xform", "copytopoints"):
        node = geo.createNode(type_name)
        info = client.ok("node_type_info", {"type": type_name, "category": "Sop"})
        assert info["name"] == node.type().name()
        for parm in info["parms"]:
            if "#" in parm["name"] or parm["type"] == "multiparm":
                continue
            for component in parm.get("components", [parm["name"]]):
                assert node.parm(component) is not None or node.parmTuple(component), (
                    type_name,
                    component,
                )


def test_info_bare_name_resolves_like_create_node(client):
    info = client.ok("node_type_info", {"type": "scatter", "category": "Sop"})
    assert info["name"] == "scatter::2.0"
    assert info["is_current_version"] is True
    assert info["versions"] == ["scatter::2.0", "scatter"]
    assert info["inputs"][0]["label"] == "Geometry to scatter points onto"
    assert "Options" in info["folders"]
    npts = next(p for p in info["parms"] if p["name"] == "npts")
    assert npts["folder"] == "Options" and npts["label"] == "Force Total Count"
    # Unique in one category: no category needed.
    assert client.ok("node_type_info", {"type": "scatter"})["name"] == "scatter::2.0"
    assert client.ok("node_type_info", {"type": "Sop/scatter"})["name"] == "scatter::2.0"
    old = client.ok("node_type_info", {"type": "Sop/scatter::2.0", "include_parms": False})
    assert old["name"] == "scatter::2.0" and "parms" not in old


def test_info_folder_filter(client):
    info = client.ok("node_type_info", {"type": "Sop/scatter", "folder": "Output Attributes"})
    assert info["parms"] and all(p["folder"] == "Output Attributes" for p in info["parms"])
    error = client.error("node_type_info", {"type": "Sop/scatter", "folder": "Nope"})
    assert error["code"] == "invalid_argument" and "Options" in error["candidates"]


def test_info_lop_type(client):
    info = client.ok("node_type_info", {"type": "Lop/sublayer"})
    assert info["category"] == "Lop"
    assert [i["label"] for i in info["inputs"]] == ["Input Stage", "Add As Sublayer"]
    assert len(hou.node("/stage").children()) == 0


def test_info_cop_types(client):
    cop = client.ok("node_type_info", {"type": "blur", "category": "Cop"})
    assert cop["category"] == "Cop"
    assert [i["name"] for i in cop["inputs"]] == ["source", "size"]
    cop2 = client.ok("node_type_info", {"type": "Cop2/blur"})
    assert cop2["inputs"][0]["label"] == "Image to Blur"
    assert len(hou.node("/obj").children()) == 0 and len(hou.node("/img").children()) == 0


def test_info_help_text(client):
    info = client.ok("node_type_info", {"type": "Sop/scatter", "include_help": True})
    assert info["help_source"] == "nodes.zip:sop/scatter.txt"
    text = info["help_text"]
    assert text.startswith("Scatter")
    assert "Scatters new points randomly" in text
    assert "#type:" not in text and "[Node:" not in text
    assert len(text) <= 2100
    assert info["help_truncated"] is True
    npts = next(p for p in info["parms"] if p["name"] == "npts")
    assert npts.get("help")
    box = client.ok("node_type_info", {"type": "Sop/box", "include_help": True})
    assert "Creates a cube" in box["help_text"]


def test_info_errors(client):
    error = client.error("node_type_info", {"type": "Sop/scater"})
    assert error["code"] == "node_type_not_found"
    assert "scatter::2.0" in error["candidates"]
    error = client.error("node_type_info", {"type": "copytopoints"})
    assert error["code"] == "invalid_argument"
    assert error["candidates"] == ["Sop/copytopoints::2.0", "Lop/copytopoints"]
    assert client.error("node_type_info", {"type": ""})["code"] == "invalid_argument"
