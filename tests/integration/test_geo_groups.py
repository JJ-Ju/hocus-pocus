"""``inspect {what: "geo", group_by}`` (2.1, D71; review 26 P3 friction 4): stats per
value of an attribute, where the dogfood needed ``houdini_python`` for "the bbox of each
collision hull" and "the streak lengths on spandrels"."""

from __future__ import annotations

import json
import time

import pytest

hou = pytest.importorskip("hou")


def _size(result) -> int:
    return len(json.dumps(result, separators=(",", ":")).encode("utf-8"))


def _wrangle(parent, source, snippet: str, name: str, run_over: int):
    node = parent.createNode("attribwrangle", name)
    node.setFirstInput(source)
    node.parm("class").set(run_over)  # 0 detail, 1 prim, 2 point, 3 vertex
    node.parm("snippet").set(snippet)
    node.setDisplayFlag(True)
    return node


def _tower():
    """A box (6 quads) and a 10 x 10 grid of 4 quads at y 2: glass on the box's first
    four faces, wall on the other two, roof on the grid; a vertex Cd and a point
    weight."""
    geo = hou.node("/obj").createNode("geo", "tower")
    box = geo.createNode("box")
    grid = geo.createNode("grid")
    grid.parm("rows").set(3)
    grid.parm("cols").set(3)
    grid.parmTuple("t").set((0, 2, 0))
    merge = geo.createNode("merge")
    merge.setInput(0, box)
    merge.setInput(1, grid)
    prims = _wrangle(
        geo,
        merge,
        's@surface = @primnum >= 6 ? "roof" : (@primnum < 4 ? "glass" : "wall");'
        " i@mat_id = @primnum >= 6 ? 3 : 1;",
        "prims",
        1,
    )
    verts = _wrangle(geo, prims, "v@Cd = set(@vtxnum * 0.1, 0, 0);", "verts", 3)
    return _wrangle(geo, verts, "f@weight = @P.y;", "OUT", 2)


def _inspect(client, target, **options):
    return client.ok("inspect", {"what": "geo", "target": target, **options})


def test_group_by_a_prim_attribute(client):
    out = _tower()
    result = _inspect(client, out.path(), group_by="surface", attribs=["Cd", "weight"])
    assert result["class"] == "prim" and result["total"] == 3
    assert result["columns"] == [
        "value", "prims", "points", "triangles", "area", "bbox_min", "bbox_max",
        "Cd.min", "Cd.max", "Cd.mean", "weight.min", "weight.max", "weight.mean",
    ]  # fmt: skip
    assert [row[0] for row in result["rows"]] == ["glass", "roof", "wall"]  # largest first
    rows = {row[0]: dict(zip(result["columns"], row, strict=True)) for row in result["rows"]}
    glass, roof, wall = rows["glass"], rows["roof"], rows["wall"]
    assert (glass["prims"], glass["points"], glass["triangles"]) == (4, 8, 8)
    assert (wall["prims"], wall["points"], wall["triangles"]) == (2, 8, 4)
    assert (roof["prims"], roof["points"], roof["triangles"]) == (4, 9, 8)
    assert glass["area"] == pytest.approx(4.0) and roof["area"] == pytest.approx(100.0)
    assert roof["bbox_min"] == [-5.0, 2.0, -5.0] and roof["bbox_max"] == [5.0, 2.0, 5.0]
    assert roof["weight.min"] == roof["weight.max"] == 2.0
    assert (wall["weight.min"], wall["weight.max"]) == (-0.5, 0.5)
    assert glass["Cd.min"][0] == pytest.approx(0.0) and glass["Cd.max"][0] == pytest.approx(1.5)
    assert "next_cursor" not in result and "truncated" not in result


def test_group_by_within_a_group_and_paged(client):
    out = _tower()
    first = _inspect(client, out.path(), group_by="surface", group="@mat_id==1", count=1)
    assert first["group"] == "@mat_id==1" and first["total"] == 2
    assert [row[0] for row in first["rows"]] == ["glass"] and first["next_cursor"] == "1"
    rest = _inspect(client, out.path(), group_by="surface", group="@mat_id==1", cursor="1")
    assert [row[0] for row in rest["rows"]] == ["wall"] and rest["start"] == 1


def test_group_by_an_int_and_a_point_attribute(client):
    out = _tower()
    by_id = _inspect(client, out.path(), group_by="mat_id")
    assert [(row[0], row[1]) for row in by_id["rows"]] == [(1, 6), (3, 4)]
    sides = _wrangle(out.parent(), out, 's@side = @P.y > 1 ? "top" : "bottom";', "sides", 2)
    by_point = _inspect(client, sides.path(), group_by="side", attribs=["weight"])
    assert by_point["class"] == "point"
    assert by_point["columns"][:4] == ["value", "points", "bbox_min", "bbox_max"]
    assert [(row[0], row[1]) for row in by_point["rows"]] == [("top", 9), ("bottom", 8)]


def test_group_by_refusals(client):
    target = _tower().path()
    error = client.error("inspect", {"what": "geo", "target": target, "group_by": "Cd"})
    assert error["code"] == "invalid_argument" and "vertex attribute" in error["message"]
    error = client.error("inspect", {"what": "geo", "target": target, "group_by": "weight"})
    assert "string or int" in error["message"]
    error = client.error("inspect", {"what": "geo", "target": target, "group_by": "surfce"})
    assert "surface" in error["candidates"]
    error = client.error(
        "inspect", {"what": "geo", "target": target, "group_by": "surface", "rows": True}
    )
    assert "not an option of group_by" in error["message"]
    error = client.error(
        "inspect",
        {"what": "geo", "target": target, "group_by": "surface", "attribs": ["surface"]},
    )
    assert "numeric" in error["message"]


def test_group_by_many_values_is_bounded(client):
    geo = hou.node("/obj").createNode("geo", "big")
    grid = geo.createNode("grid")
    grid.parm("rows").set(400)
    grid.parm("cols").set(400)
    out = _wrangle(geo, grid, "i@piece = @primnum % 2000;", "OUT", 1)
    out.cook()
    started = time.perf_counter()
    result = _inspect(client, out.path(), group_by="piece", count=10000)
    elapsed = time.perf_counter() - started
    assert result["total"] == 2000 and result.get("truncated") is True
    assert len(result["rows"]) < 2000 and result["next_cursor"] == str(len(result["rows"]))
    assert _size(result) < 16_000
    print(f"\ngroup_by on 159k prims, 2000 values: {elapsed:.2f} s, {_size(result)} B")
    assert elapsed < 1.5
