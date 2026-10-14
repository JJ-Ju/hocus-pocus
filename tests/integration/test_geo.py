"""geo_info and geo_read against real Houdini geometry."""

from __future__ import annotations

import json
import time

import pytest

hou = pytest.importorskip("hou")


def _size(result) -> int:
    return len(json.dumps(result, separators=(",", ":")).encode("utf-8"))


def _box(name: str = "geo1"):
    geo = hou.node("/obj").createNode("geo", name)
    box = geo.createNode("box", "box1")
    box.setDisplayFlag(True)
    return geo, box


def _wrangle(parent, source, snippet: str, name: str = "wrangle1", run_over: int = 2):
    node = parent.createNode("attribwrangle", name)
    node.setFirstInput(source)
    node.parm("class").set(run_over)  # 0 detail, 1 prim, 2 point, 3 vertex
    node.parm("snippet").set(snippet)
    node.setDisplayFlag(True)
    return node


# -- geo_info -------------------------------------------------------------------------


def test_geo_info_box(client):
    _, box = _box()
    result = client.ok("geo_info", {"path": box.path()})
    assert result["path"] == "/obj/geo1/box1"
    assert (result["point_count"], result["prim_count"], result["vertex_count"]) == (8, 6, 24)
    assert result["bbox"] == {
        "min": [-0.5, -0.5, -0.5],
        "max": [0.5, 0.5, 0.5],
        "size": [1.0, 1.0, 1.0],
        "center": [0.0, 0.0, 0.0],
    }
    assert result["prim_types"] == {"polygon": 6}
    assert result["attributes"]["point"] == [
        {"name": "P", "type": "float", "size": 3, "type_info": "position"}
    ]
    assert result["attributes"]["detail"] == []
    assert result["groups"] == {"point": [], "prim": [], "edge": [], "vertex": []}
    assert "intrinsics" not in result
    size = _size(result)
    print(f"\ngeo_info box: {size} bytes")
    assert size < 1200


def test_geo_info_obj_resolves_display_sop(client):
    geo, box = _box()
    xform = geo.createNode("xform", "moved")
    xform.setFirstInput(box)
    xform.parm("ty").set(2)
    xform.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": "/obj/geo1"})
    assert result["path"] == "/obj/geo1/moved"
    assert result["bbox"]["center"] == [0.0, 2.0, 0.0]


def test_geo_info_attributes_groups_and_detail_values(client):
    geo, box = _box()
    node = _wrangle(
        geo,
        box,
        'v@Cd = set(1, 0, 0); i@id = @ptnum; s@name = @ptnum < 4 ? "low" : "high"; '
        'f[]@arr = array(1.0, 2.0); if (@P.y > 0) setpointgroup(0, "top", @ptnum, 1); '
        'setdetailattrib(0, "note", "hello"); setdetailattrib(0, "scale", 2.5); '
        'setdetailattrib(0, "big", {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20}, "set");',
    )
    groups = geo.createNode("groupcreate", "primgrp")
    groups.setFirstInput(node)
    groups.parm("groupname").set("firstprims")
    groups.parm("basegroup").set("0-2")
    groups.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": "/obj/geo1"})
    points = {a["name"]: a for a in result["attributes"]["point"]}
    assert points["Cd"] == {"name": "Cd", "type": "float", "size": 3, "type_info": "color"}
    assert points["id"]["type"] == "int"
    assert points["name"]["type"] == "string"
    assert points["arr"]["type"] == "float[]"
    detail = {a["name"]: a for a in result["attributes"]["detail"]}
    assert detail["note"]["value"] == "hello"
    assert detail["scale"]["value"] == 2.5
    big = detail["big"]["value"]
    assert len(big) == 17 and big[-1] == "… 4 more"
    assert result["groups"]["point"] == [{"name": "top", "count": 4}]
    assert result["groups"]["prim"] == [{"name": "firstprims", "count": 3}]


def test_geo_info_intrinsics_for_packed_volume_vdb(client):
    geo, box = _box()
    pack = geo.createNode("pack")
    pack.setFirstInput(box)
    volume = geo.createNode("volume")
    volume.parm("name").set("density")
    vdb = geo.createNode("vdbfrompolygons")
    vdb.setFirstInput(box)
    merge = geo.createNode("merge")
    for node in (pack, volume, vdb):
        merge.setNextInput(node)
    merge.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": merge.path()})
    assert result["prim_types"] == {"packed": 1, "volume": 1, "vdb": 1}
    intrinsics = result["intrinsics"]
    assert intrinsics["packed"][0]["type"] == "PackedGeometry"
    assert intrinsics["packed"][0]["bounds"] == [-0.5, 0.5, -0.5, 0.5, -0.5, 0.5]
    volumes = dict(zip(intrinsics["volume_columns"], intrinsics["volume"][0], strict=True))
    assert volumes["resolution"] == [10, 10, 10]
    assert volumes["name"] == "density"
    vdbs = dict(zip(intrinsics["vdb_columns"], intrinsics["vdb"][0], strict=True))
    assert vdbs["class"] == "level set"
    assert vdbs["active_voxels"] > 0
    assert _size(result) < 2000


def test_geo_info_frame(client):
    _, box = _box()
    box.parm("sizex").setExpression("$F")
    result = client.ok("geo_info", {"path": box.path(), "frame": 10})
    assert result["frame"] == 10
    assert result["bbox"]["size"][0] == 10.0


def test_geo_info_empty_geometry(client):
    geo = hou.node("/obj").createNode("geo", "empty")
    null = geo.createNode("null")
    null.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": null.path()})
    assert result["point_count"] == 0
    assert result["bbox"] is None
    assert result["prim_types"] == {}


def test_geo_info_cook_failed(client):
    geo, box = _box()
    bad = _wrangle(geo, box, "this is not vex;", name="broken")
    error = client.error("geo_info", {"path": bad.path()})
    assert error["code"] == "cook_failed"
    assert error["detail"]["path"] == bad.path()
    assert error["detail"]["errors"], error


def test_geo_info_error_sop(client):
    geo, box = _box()
    err = geo.createNode("error")
    err.setFirstInput(box)
    err.parm("numerror").set(1)
    err.parm("enable1").set(1)
    err.parm("severity1").set("error")
    err.parm("errormsg1").set("deliberate failure")
    error = client.error("geo_info", {"path": err.path()})
    assert error["code"] == "cook_failed"
    assert any("deliberate failure" in e for e in error["detail"]["errors"])


def test_geo_info_obj_without_display_sop(client):
    hou.node("/obj").createNode("geo", "emptygeo")
    error = client.error("geo_info", {"path": "/obj/emptygeo"})
    assert error["code"] == "invalid_argument"
    assert "no display SOP" in error["message"]
    assert "hint" in error
    subnet = hou.node("/obj").createNode("subnet", "objsubnet")
    error = client.error("geo_info", {"path": subnet.path()})
    assert error["code"] == "invalid_argument"


def test_geo_info_not_a_sop(client):
    hou.node("/out").createNode("null", "outnull")
    error = client.error("geo_info", {"path": "/out/outnull"})
    assert error["code"] == "invalid_argument"
    assert "not a SOP or OBJ" in error["message"]


def test_geo_info_missing_node_has_candidates(client):
    _box()
    error = client.error("geo_info", {"path": "/obj/geo1/boxx1"})
    assert error["code"] == "node_not_found"
    assert "/obj/geo1/box1" in error["candidates"]


# -- geo_read -------------------------------------------------------------------------


def test_geo_read_points_default(client):
    _, box = _box()
    result = client.ok("geo_read", {"path": box.path()})
    assert result["class"] == "point"
    assert result["columns"] == ["ptnum", "P"]
    assert result["total"] == 8
    assert len(result["rows"]) == 8
    assert result["rows"][0] == [0, [-0.5, -0.5, -0.5]]
    assert "next_cursor" not in result


def test_geo_read_paging(client):
    _, box = _box()
    first = client.ok("geo_read", {"path": box.path(), "count": 3})
    assert [r[0] for r in first["rows"]] == [0, 1, 2]
    assert first["next_cursor"] == "3"
    second = client.ok("geo_read", {"path": box.path(), "cursor": first["next_cursor"], "count": 3})
    assert [r[0] for r in second["rows"]] == [3, 4, 5]
    by_start = client.ok("geo_read", {"path": box.path(), "start": 3, "count": 3})
    assert by_start["rows"] == second["rows"]
    bad = client.error("geo_read", {"path": box.path(), "cursor": "x"})
    assert bad["code"] == "invalid_argument"
    last = client.ok("geo_read", {"path": box.path(), "start": 6, "count": 3})
    assert [r[0] for r in last["rows"]] == [6, 7]
    assert "next_cursor" not in last
    beyond = client.ok("geo_read", {"path": box.path(), "start": 100})
    assert beyond["rows"] == []


def test_geo_read_attrib_filter_and_types(client):
    geo, box = _box()
    _wrangle(
        geo,
        box,
        'v@Cd = set(@ptnum, 0, 1); i@id = @ptnum * 10; s@name = sprintf("p%d", @ptnum % 3); '
        "f[]@arr = array(@ptnum, 0.5);",
    )
    result = client.ok(
        "geo_read", {"path": "/obj/geo1", "attribs": ["id", "name", "Cd", "arr"], "count": 4}
    )
    assert result["columns"] == ["ptnum", "id", "name", "Cd", "arr"]
    assert result["rows"][2] == [2, 20, "p2", [2.0, 0.0, 1.0], [2.0, 0.5]]


def test_geo_read_bad_attrib_has_candidates(client):
    geo, box = _box()
    _wrangle(geo, box, "v@Cd = 1; f@pscale = 0.1;")
    error = client.error("geo_read", {"path": "/obj/geo1", "attribs": ["pscal"]})
    assert error["code"] == "invalid_argument"
    assert "pscale" in error["candidates"]
    prim_level = _wrangle(geo, box, "i@primid = @primnum;", name="primattr", run_over=1)
    error = client.error("geo_read", {"path": prim_level.path(), "attribs": ["primid"]})
    assert error["code"] == "invalid_argument"
    assert "class 'prim'" in error["hint"]


def test_geo_read_bad_class(client):
    _, box = _box()
    error = client.error("geo_read", {"path": box.path(), "class": "points"})
    assert error["code"] == "invalid_argument"
    assert "point" in error["candidates"]


def test_geo_read_prims_vertices_detail(client):
    geo, box = _box()
    node = _wrangle(
        geo, box, 'setdetailattrib(0, "label", "boxy"); setdetailattrib(0, "n", 6);', run_over=0
    )
    prims = client.ok("geo_read", {"path": node.path(), "class": "prim"})
    assert prims["columns"] == ["primnum"]
    assert prims["total"] == 6
    vertices = client.ok("geo_read", {"path": node.path(), "class": "vertex", "count": 5})
    assert vertices["columns"] == ["vtxnum", "primnum", "ptnum"]
    assert vertices["total"] == 24
    expected = [
        [i, box.geometry().vertex(i).prim().number(), box.geometry().vertex(i).point().number()]
        for i in range(5)
    ]
    assert vertices["rows"] == expected
    detail = client.ok("geo_read", {"path": node.path(), "class": "detail"})
    assert dict(zip(detail["columns"], detail["rows"][0], strict=True)) == {"label": "boxy", "n": 6}
    assert detail["total"] == 1


def test_geo_read_groups(client):
    geo, box = _box()
    node = _wrangle(geo, box, 'if (@P.y > 0) setpointgroup(0, "top", @ptnum, 1);')
    top = client.ok("geo_read", {"path": node.path(), "group": "top"})
    assert top["total"] == 4
    assert all(row[1][1] == 0.5 for row in top["rows"])
    pattern = client.ok("geo_read", {"path": node.path(), "group": "0-2"})
    assert [r[0] for r in pattern["rows"]] == [0, 1, 2]
    expression = client.ok("geo_read", {"path": node.path(), "group": "@P.x>0", "count": 2})
    assert expression["total"] == 4 and expression["next_cursor"] == "2"
    error = client.error("geo_read", {"path": node.path(), "group": "tpo"})
    assert error["code"] == "invalid_argument"
    assert "top" in error["candidates"]


def test_geo_read_stats(client):
    geo, box = _box()
    node = _wrangle(
        geo, box, 'i@id = @ptnum; s@name = @P.y > 0 ? "up" : "down"; f[]@arr = array(1.0);'
    )
    result = client.ok("geo_read", {"path": node.path(), "count": 1, "stats": True})
    stats = result["stats"]
    assert stats["P"] == {
        "min": [-0.5, -0.5, -0.5],
        "max": [0.5, 0.5, 0.5],
        "mean": [0.0, 0.0, 0.0],
    }
    assert stats["id"] == {"min": 0, "max": 7, "mean": 3.5}
    assert stats["name"] == {"unique": ["down", "up"], "unique_count": 2}
    assert "arr" not in stats  # arrays have no stats
    grouped = client.ok("geo_read", {"path": node.path(), "group": "@P.y>0", "stats": True})
    assert grouped["stats"]["P"]["min"][1] == 0.5


def test_geo_read_large_count_stays_under_budget(client):
    geo, box = _box()
    scatter = geo.createNode("scatter")
    scatter.setFirstInput(box)
    scatter.parm("npts").set(5000)
    scatter.setDisplayFlag(True)
    result = client.ok("geo_read", {"path": scatter.path(), "count": 5000})
    assert result["truncated"] is True
    assert result["next_cursor"] == str(len(result["rows"]))
    assert _size(result) < 16_384


@pytest.mark.slow
def test_one_million_points(client):
    geo, box = _box()
    scatter = geo.createNode("scatter", "scatter1m")
    scatter.setFirstInput(box)
    scatter.parm("npts").set(1_000_000)
    scatter.setDisplayFlag(True)
    scatter.cook(force=True)
    info = client.ok("geo_info", {"path": scatter.path()})
    assert info["point_count"] == 1_000_000
    size = _size(info)
    print(f"\ngeo_info 1M scatter: {size} bytes")
    assert size < 1500

    started = time.perf_counter()
    envelope = client.call("geo_read", {"path": scatter.path(), "attribs": ["P"], "stats": True})
    elapsed = time.perf_counter() - started
    assert envelope["ok"], envelope
    stats = envelope["result"]["stats"]["P"]
    assert all(-0.501 <= v <= -0.49 for v in stats["min"])
    assert all(0.49 <= v <= 0.501 for v in stats["max"])
    print(
        f"geo_read stats P over 1M points: round trip {elapsed:.3f}s, "
        f"host {envelope['_meta']['elapsed_ms']} ms"
    )
    assert elapsed < 2.0

    started = time.perf_counter()
    grouped = client.ok(
        "geo_read", {"path": scatter.path(), "attribs": ["P"], "group": "@P.y>0", "stats": True}
    )
    elapsed = time.perf_counter() - started
    assert 400_000 < grouped["total"] < 600_000
    print(f"geo_read stats P over a 1M-point group expression: {elapsed:.3f}s")
    assert elapsed < 2.0


# -- review 10 §5 ------------------------------------------------------------------


def test_geo_read_vertex_values_follow_linear_vertex_order(client):
    geo, box = _box()
    node = _wrangle(geo, box, "v@uv = set(@vtxnum, @primnum, @ptnum);", run_over=3)
    args = {"path": node.path(), "class": "vertex", "attribs": ["uv"], "count": 24}
    paged = client.ok("geo_read", args)
    bulk = client.ok("geo_read", {**args, "stats": True})
    assert paged["rows"] == bulk["rows"]
    assert len(paged["rows"]) == 24
    for vtxnum, primnum, ptnum, uv in paged["rows"]:
        assert uv == [vtxnum, primnum, ptnum]


def test_geo_read_dict_attributes(client):
    geo, box = _box()
    node = _wrangle(geo, box, 'dict d; d["id"] = @ptnum; d["tag"] = "c"; d@meta = d;')
    result = client.ok("geo_read", {"path": node.path(), "attribs": ["meta"], "count": 3})
    assert result["columns"] == ["ptnum", "meta"]
    assert [row[1] for row in result["rows"]] == [{"id": i, "tag": "c"} for i in range(3)]
    stats = client.ok("geo_read", {"path": node.path(), "attribs": ["meta"], "stats": True})
    assert "meta" not in stats["stats"]  # dicts have no stats
    assert stats["rows"][7] == [7, {"id": 7, "tag": "c"}]


def test_geo_read_page_does_not_load_whole_columns(client, monkeypatch):
    from hocuspocus.host.tools import geo as geo_mod

    geo, box = _box()
    scatter = geo.createNode("scatter")
    scatter.setFirstInput(box)
    scatter.parm("npts").set(2000)
    node = _wrangle(geo, scatter, "s@name = itoa(@ptnum % 3); f[]@w = array(@ptnum);")
    loaded = []
    real = geo_mod._Column.values

    def spy(self):
        loaded.append(self.name)
        return real(self)

    monkeypatch.setattr(geo_mod._Column, "values", spy)
    result = client.ok("geo_read", {"path": node.path(), "start": 10, "count": 3})
    assert loaded == []
    assert result["rows"][0][0] == 10
    assert result["rows"][0][2:] == ["1", [10.0]]
    client.ok("geo_read", {"path": node.path(), "count": 3, "stats": True})
    assert set(loaded) >= {"P", "name"}


@pytest.mark.slow
def test_one_million_points_string_stats_with_a_pattern_group(client):
    geo, box = _box()
    scatter = geo.createNode("scatter", "scatter1m")
    scatter.setFirstInput(box)
    scatter.parm("npts").set(1_000_000)
    node = _wrangle(geo, scatter, 's@side = @P.x > 0 ? "right" : "left";')
    node.cook(force=True)
    started = time.perf_counter()
    result = client.ok(
        "geo_read",
        {"path": node.path(), "group": "@P.y>0", "stats": True, "count": 5},
    )
    elapsed = time.perf_counter() - started
    print(f"\ngeo_read stats P+side over a 1M-point group expression: {elapsed:.3f}s")
    assert 400_000 < result["total"] < 600_000
    assert result["stats"]["side"] == {"unique": ["left", "right"], "unique_count": 2}
    assert result["stats"]["P"]["min"][1] >= 0
    assert len(result["rows"]) == 5 and all(row[1][1] > 0 for row in result["rows"])
    assert elapsed < 5.0
    started = time.perf_counter()
    page = client.ok("geo_read", {"path": node.path(), "start": 999_990, "count": 10})
    elapsed = time.perf_counter() - started
    assert [row[0] for row in page["rows"]] == list(range(999_990, 1_000_000))
    assert elapsed < 1.0, elapsed


def _broken_then_fixed_outside():
    """box1 -> mountain1 -> copy1 with box1 broken, cooked, then fixed outside
    HocusPocus: Houdini keeps the old error on box1 and fails downstream cooks with
    'Invalid source' until box1 is cooked again (bible §5.18)."""
    geo = hou.node("/obj").createNode("geo", "stale")
    box = geo.createNode("box", "box1")
    mountain = geo.createNode("mountain", "mountain1")
    mountain.setInput(0, box)
    sphere = geo.createNode("sphere", "sphere1")
    copy1 = geo.createNode("copytopoints", "copy1")
    copy1.setInput(0, sphere)
    copy1.setInput(1, mountain)
    copy1.setDisplayFlag(True)
    parm = box.parm("sizex")
    parm.setExpression("$F*(")
    with pytest.raises(hou.OperationFailed):
        copy1.cook()
    parm.deleteAllKeyframes()
    parm.revertToDefaults()
    box.cook()
    assert box.errors()  # the stale error is still there
    return geo, copy1


@pytest.mark.parametrize("tool", ["geo_info", "geo_read"])
def test_geo_tools_refresh_errors_left_by_an_outside_fix(client, tool):
    _, copy1 = _broken_then_fixed_outside()
    result = client.ok(tool, {"path": copy1.path()})
    assert result["path"] == copy1.path()


def test_capture_framing_bbox_refreshes_stale_errors(client):
    from hocuspocus.host.tools.visual import _world_bbox

    geo, copy1 = _broken_then_fixed_outside()
    assert _world_bbox(geo, copy1) is not None


# -- review 17: every volume, vectors, dict attributes, geo_read frame -----------------------


def test_geo_info_lists_every_volume_as_a_row(client):
    geo = hou.node("/obj").createNode("geo", "vols")
    merge = geo.createNode("merge")
    for index in range(6):
        volume = geo.createNode("volume", f"v{index}")
        volume.parm("name").set(f"field{index}")
        merge.setNextInput(volume)
    merge.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": merge.path()})
    intrinsics = result["intrinsics"]
    assert intrinsics["volume_columns"] == [
        "name",
        "prim",
        "resolution",
        "voxel_size",
        "min",
        "max",
    ]
    assert [row[0] for row in intrinsics["volume"]] == [f"field{i}" for i in range(6)]
    assert "volume_total" not in intrinsics


def test_geo_info_vectors_as_lists_and_long_dicts_elided(client):
    geo, box = _box()
    py = geo.createNode("python", "detail")
    py.setFirstInput(box)
    py.parm("python").set(
        "geo = hou.pwd().geometry()\n"
        "geo.addAttrib(hou.attribType.Global, 'vis', {})\n"
        "geo.setGlobalAttribValue('vis', {'range': hou.Vector2(0, 1), "
        "'ramp': 'x' * 400, 'mode': 'smoke'})\n"
        "geo.addAttrib(hou.attribType.Global, 'small', {})\n"
        "geo.setGlobalAttribValue('small', {'c': hou.Vector3(1, 2, 3)})\n"
    )
    py.setDisplayFlag(True)
    result = client.ok("geo_info", {"path": py.path()})
    detail = {row["name"]: row["value"] for row in result["attributes"]["detail"]}
    assert detail["small"] == {"c": [1.0, 2.0, 3.0]}
    vis = detail["vis"]
    assert vis["elided"] > 200 and sorted(vis["keys"]) == ["mode", "ramp", "range"]
    assert "<hou." not in json.dumps(result)


def test_geo_read_at_a_frame_leaves_the_playbar(client):
    geo, box = _box()
    box.parm("ty").setExpression("$F")
    hou.setFrame(1)
    result = client.ok("geo_read", {"path": box.path(), "attribs": ["P"], "count": 1, "frame": 12})
    assert result["frame"] == 12
    assert result["rows"][0][1][1] == pytest.approx(11.5)
    assert hou.frame() == 1
    stats = client.ok("geo_read", {"path": box.path(), "class": "detail", "frame": 3})
    assert stats["frame"] == 3


def test_geo_info_missing_node_hint_matches_cook(client):
    """Review 22 finding 8: geo_info said only 'Check the node name.'."""
    for path in ("/obj/soak_missing", "/obj/soak_missing/out"):
        geo = client.error("geo_info", {"path": path})
        cook = client.error("cook", {"paths": [path]})
        assert geo["code"] == cook["code"] == "node_not_found"
        assert geo["hint"] == cook["hint"] and "node_find" in geo["hint"]


def test_geo_info_names_mode_and_internal_attributes(client):
    """Review 23 papercut 8: a Vellum result was mostly solver internals."""
    geo = hou.node("/obj").createNode("geo", "vel")
    box = geo.createNode("box")
    wrangle = geo.createNode("attribwrangle")
    wrangle.setInput(0, box)
    wrangle.parm("snippet").set("v@pprevious = @P; i@__scratch = 1; f@keepme = 2;")
    full = client.ok("geo_info", {"path": wrangle.path()})
    names = [a["name"] for a in full["attributes"]["point"]]
    assert "keepme" in names and "pprevious" not in names and "__scratch" not in names
    assert full["internal_attribute_count"] == 2 and "geo_read" in full["notes"][0]
    short = client.ok("geo_info", {"path": wrangle.path(), "attributes": "names"})
    assert short["attributes"]["point"] == names
    assert len(json.dumps(short)) < len(json.dumps(full))
    assert client.error("geo_info", {"path": wrangle.path(), "attributes": "rows"})
