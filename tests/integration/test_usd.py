"""usd_stage against real Solaris stages (bible §4.7)."""

from __future__ import annotations

import json

import pytest

hou = pytest.importorskip("hou")


def _scene():
    """sphere1 -> materiallibrary (one MaterialX surface) -> assignmaterial -> OUT null."""
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    sphere.parm("ty").set(2.0)
    lib = stage.createNode("materiallibrary", "matlib")
    lib.setInput(0, sphere)
    lib.createNode("mtlxstandard_surface", "chrome")
    assign = stage.createNode("assignmaterial", "assign")
    assign.setInput(0, lib)
    assign.parm("primpattern1").set("/sphere1")
    assign.parm("matspecpath1").set("/materials/chrome")
    out = stage.createNode("null", "OUT")
    out.setInput(0, assign)
    out.setDisplayFlag(True)
    return out


def test_default_lists_root_children(client):
    out = _scene()
    result = client.ok("usd_stage", {"lop_path": out.path()})
    assert result["lop_path"] == out.path()
    paths = [p["path"] for p in result["prims"]]
    assert paths == ["/sphere1", "/materials"]  # /HoudiniLayerInfo is hidden
    assert result["total"] == 2
    sphere = result["prims"][0]
    assert sphere["type"] == "Sphere"
    assert sphere["active"] is True
    assert sphere["children_count"] == 0
    assert "attributes" not in sphere and "xform" not in sphere
    assert result["prims"][1]["children_count"] == 1


def test_lop_network_resolves_to_display_node(client):
    out = _scene()
    result = client.ok("usd_stage", {"lop_path": "/stage"})
    assert result["lop_path"] == out.path()


def test_depth_and_prim(client):
    out = _scene()
    result = client.ok("usd_stage", {"lop_path": out.path(), "prim": "/materials", "depth": 2})
    paths = [p["path"] for p in result["prims"]]
    assert paths[0] == "/materials"
    assert "/materials/chrome" in paths
    assert any(p.startswith("/materials/chrome/") for p in paths)
    shallow = client.ok("usd_stage", {"lop_path": out.path(), "prim": "/materials"})
    assert [p["path"] for p in shallow["prims"]] == ["/materials", "/materials/chrome"]
    material = shallow["prims"][1]
    assert material["type"] == "Material"


def test_attributes_authored_values(client):
    out = _scene()
    result = client.ok(
        "usd_stage",
        {"lop_path": out.path(), "prim": "/sphere1", "include": ["attributes"], "depth": 1},
    )
    (sphere,) = result["prims"]
    attrs = {a["name"]: a for a in sphere["attributes"]}
    assert attrs["radius"] == {"name": "radius", "type": "double", "value": 1}
    assert attrs["xformOp:translate"]["value"] == [0, 2, 0]
    extent = attrs["extent"]
    assert extent["type"] == "float3[]"
    assert extent["value"] == [[-1, -1, -1], [1, 1, 1]]  # short arrays are listed in full
    order = attrs["xformOpOrder"]["value"]
    assert isinstance(order, list) and order and isinstance(order[0], str)
    # Unauthored fallbacks are not listed.
    assert "doubleSided" not in attrs and "visibility" not in attrs


def test_attribute_time_samples(client):
    sphere = hou.node("/stage").createNode("sphere", "sphere1")
    sphere.parm("ty").setExpression("$F")
    result = client.ok(
        "usd_stage",
        {"lop_path": sphere.path(), "prim": "/sphere1", "include": ["attributes"], "time": 1},
    )
    attrs = {a["name"]: a for a in result["prims"][0]["attributes"]}
    assert attrs["xformOp:translate"]["value"][1] == hou.frame()
    assert result["time"] == 1


def test_xform_and_bindings(client):
    out = _scene()
    result = client.ok(
        "usd_stage",
        {"lop_path": out.path(), "include": ["xform", "bindings"]},
    )
    rows = {p["path"]: p for p in result["prims"]}
    sphere = rows["/sphere1"]
    assert sphere["material"] == "/materials/chrome"
    local = sphere["xform"]["local"]
    assert local[3][:3] == [0, 2, 0]
    assert "world" not in sphere["xform"]  # left out when it equals local
    assert "xform" not in rows["/materials"]  # a Scope is not xformable
    assert "material" not in rows["/materials"]


PER_FACE = """
from pxr import Sdf, UsdGeom, UsdShade
stage = hou.pwd().editableStage()
mesh = UsdGeom.Mesh.Define(stage, "/tower")
mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (2, 1, 0)])
mesh.CreateFaceVertexCountsAttr([4, 4])
mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3, 1, 4, 5, 2])
primvars = UsdGeom.PrimvarsAPI(mesh.GetPrim())
primvars.CreatePrimvar("lit", Sdf.ValueTypeNames.FloatArray).Set([0.0, 1.0])
armour = UsdShade.Material.Define(stage, "/materials/armour")
glass = UsdShade.Material.Define(stage, "/materials/glass")
UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(armour)
api = UsdShade.MaterialBindingAPI(mesh.GetPrim())
subset = api.CreateMaterialBindSubset("glass", [1])
UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(glass)
"""


def test_bindings_relationships_and_subsets(client):
    """D84 (r21 friction 6): an attribs read listed primvars but neither material:binding
    nor the GeomSubsets that carry per-face materials."""
    lop = hou.node("/stage").createNode("pythonscript", "per_face")
    lop.parm("python").set(PER_FACE)
    read = client.ok(
        "usd_stage", {"lop_path": lop.path(), "prim": "/tower", "attribs": "primvars:*,material:*"}
    )
    rows = {p["path"]: p for p in read["prims"]}
    row = rows["/tower"]
    assert [a["name"] for a in row["attributes"]] == ["primvars:lit"]
    assert row["relationships"] == [{"name": "material:binding", "targets": ["/materials/armour"]}]
    assert row["subsets"] == [
        {"name": "glass", "faces": 1, "family": "materialBind", "material": "/materials/glass"}
    ]
    subset = rows["/tower/glass"]  # the subset's own row: its binding, no subsets of its own
    assert subset["type"] == "GeomSubset" and "subsets" not in subset
    assert subset["relationships"] == [
        {"name": "material:binding", "targets": ["/materials/glass"]}
    ]
    only_primvars = client.ok(
        "usd_stage", {"lop_path": lop.path(), "prim": "/tower", "attribs": "primvars:*"}
    )["prims"][0]
    assert "relationships" not in only_primvars and only_primvars["subsets"] == row["subsets"]
    bound = client.ok(
        "usd_stage", {"lop_path": lop.path(), "prim": "/tower", "include": ["bindings"]}
    )["prims"][0]
    assert bound["material"] == "/materials/armour" and bound["subsets"] == row["subsets"]
    assert "attributes" not in bound and "relationships" not in bound
    plain = client.ok("usd_stage", {"lop_path": lop.path(), "prim": "/tower"})["prims"][0]
    assert "subsets" not in plain


def test_identity_xform_is_compact(client):
    sphere = hou.node("/stage").createNode("sphere", "sphere1")
    result = client.ok(
        "usd_stage", {"lop_path": sphere.path(), "prim": "/sphere1", "include": ["xform"]}
    )
    assert result["prims"][0]["xform"] == {"local": "identity"}


def test_layers(client):
    out = _scene()
    result = client.ok("usd_stage", {"lop_path": out.path(), "include": ["layers"]})
    layers = result["layers"]
    assert layers["stack"] and all(isinstance(i["identifier"], str) for i in layers["stack"])
    assert isinstance(layers["active"], str) and layers["active"]
    # Session sublayers (viewport state, solo lights, ...) are excluded.
    assert not any("Viewport State" in i["identifier"] for i in layers["stack"])


def test_layer_rows_name_save_path_and_owner(client, work_dir):
    """Review 23 papercut 4: anonymous ids only; nothing said sopimport saves a file."""
    geo = hou.node("/obj").createNode("geo", "g")
    box = geo.createNode("box")
    imp = hou.node("/stage").createNode("sopimport", "collider_import")
    imp.parm("soppath").set(box.path())
    imp.parm("enable_savepath").set(1)
    target = (work_dir / "usd" / "collider_import.usd").as_posix()
    imp.parm("savepath").set(target)
    layer_file = work_dir / "base.usda"
    layer_file.write_text(
        "#usda 1.0\n(\n    startTimeCode = 1\n    endTimeCode = 48\n)\n", encoding="utf-8"
    )
    sub = hou.node("/stage").createNode("sublayer", "base")
    sub.parm("filepath1").set(layer_file.as_posix())
    sub.setInput(0, imp)
    result = client.ok("usd_stage", {"lop_path": sub.path(), "include": ["layers"]})
    rows = result["layers"]["stack"]
    saved = [r for r in rows if r.get("save_path") == target]
    assert saved and saved[0]["owner_node"] == imp.path()
    files = [r for r in rows if r["identifier"].endswith("base.usda")]
    assert files and files[0]["time_codes"] == [1, 48]
    # Review 24 N7: forward slashes, and no save_path repeating the identifier.
    assert files[0]["identifier"] == layer_file.as_posix(), files
    assert "save_path" not in files[0], files
    assert not any("\\" in str(v) for r in rows for v in r.values()), rows
    assert "\\" not in result["layers"].get("active", "")


def test_paging(client):
    stage = hou.node("/stage")
    prev = None
    for i in range(7):
        node = stage.createNode("sphere", f"s{i}")
        node.parm("primpath").set(f"/geo/s{i}")
        if prev is not None:
            node.setInput(0, prev)
        prev = node
    args = {"lop_path": prev.path(), "prim": "/geo", "depth": 1, "limit": 3}
    first = client.ok("usd_stage", args)
    assert first["total"] == 8  # counted without building rows (review 13)
    assert [p["path"] for p in first["prims"]] == ["/geo", "/geo/s0", "/geo/s1"]
    seen = [p["path"] for p in first["prims"]]
    cursor = first["next_cursor"]
    while cursor:
        page = client.ok("usd_stage", {**args, "cursor": cursor})
        seen += [p["path"] for p in page["prims"]]
        cursor = page.get("next_cursor")
    assert page["total"] == 8  # /geo + 7 spheres, known once the walk ends
    assert seen == ["/geo"] + [f"/geo/s{i}" for i in range(7)]
    bad = client.error("usd_stage", {**args, "cursor": "nope"})
    assert bad["code"] == "invalid_argument"


def test_prim_pattern(client):
    stage = hou.node("/stage")
    a = stage.createNode("sphere", "a")
    a.parm("primpath").set("/geo/rock_a")
    b = stage.createNode("cube", "b")
    b.parm("primpath").set("/geo/rock_b")
    b.setInput(0, a)
    c = stage.createNode("cube", "c")
    c.parm("primpath").set("/props/tree")
    c.setInput(0, b)
    result = client.ok("usd_stage", {"lop_path": c.path(), "prim": "/geo/rock_*"})
    assert [p["path"] for p in result["prims"]] == ["/geo/rock_a", "/geo/rock_b"]
    deep = client.ok("usd_stage", {"lop_path": c.path(), "prim": "/**/tree"})
    assert [p["path"] for p in deep["prims"]] == ["/props/tree"]


def test_prim_alternation(client):
    """Review 16 N3: prim takes a|b like attribs, and a bad pattern is an error, not []."""
    stage = hou.node("/stage")
    a = stage.createNode("sphere", "a")
    a.parm("primpath").set("/city/bldg_001")
    b = stage.createNode("cube", "b")
    b.parm("primpath").set("/city/bldg_002")
    b.setInput(0, a)
    c = stage.createNode("cube", "c")
    c.parm("primpath").set("/city/ground")
    c.setInput(0, b)
    d = stage.createNode("cube", "d")
    d.parm("primpath").set("/lights/key")
    d.setInput(0, c)
    lop = d.path()
    both = client.ok("usd_stage", {"lop_path": lop, "prim": "/lights|/city/ground", "depth": 1})
    assert [p["path"] for p in both["prims"]] == ["/city/ground", "/lights"]
    globbed = client.ok("usd_stage", {"lop_path": lop, "prim": "/city/bldg_00*|/city/ground"})
    assert [p["path"] for p in globbed["prims"]] == [
        "/city/bldg_001",
        "/city/bldg_002",
        "/city/ground",
    ]
    assert globbed["total"] == 3
    summary = client.ok(
        "usd_stage", {"lop_path": lop, "prim": "/city/bldg_*|/lights/key", "summary": True}
    )
    assert summary["summary"]["total_prims"] == 3
    for bad in ("/city/bldg_00*|city/ground", "/city/[x]*", "/a||/b"):
        error = client.error("usd_stage", {"lop_path": lop, "prim": bad})
        assert error["code"] == "invalid_argument", bad
        assert "|" in error["hint"]
    missing = client.error("usd_stage", {"lop_path": lop, "prim": "/city/bldg_*|/cameras"})
    assert missing["code"] == "invalid_argument"
    assert "/cameras" in missing["message"]


def test_errors(client):
    out = _scene()
    missing = client.error("usd_stage", {"lop_path": out.path(), "prim": "/sphere2"})
    assert missing["code"] == "invalid_argument"
    assert "/sphere1" in missing["candidates"]
    assert all(c in missing["hint"] for c in missing["candidates"])
    not_lop = client.error("usd_stage", {"lop_path": "/obj"})
    assert not_lop["code"] == "invalid_argument"
    gone = client.error("usd_stage", {"lop_path": "/stage/nope"})
    assert gone["code"] == "node_not_found"
    bad_include = client.error("usd_stage", {"lop_path": out.path(), "include": ["prims"]})
    assert bad_include["code"] == "invalid_argument"


def test_cook_failure(client):
    bad = hou.node("/stage").createNode("pythonscript", "bad")
    bad.parm("python").set("raise RuntimeError('boom')")
    error = client.error("usd_stage", {"lop_path": bad.path()})
    assert error["code"] == "cook_failed"
    assert any("boom" in e for e in error["detail"]["errors"])


def test_result_size_is_compact(client):
    out = _scene()
    everything = client.ok(
        "usd_stage",
        {
            "lop_path": out.path(),
            "depth": 5,
            "include": ["attributes", "xform", "bindings", "layers"],
        },
    )
    plain = client.ok("usd_stage", {"lop_path": out.path(), "depth": 5})
    full_bytes = len(json.dumps(everything, separators=(",", ":")))
    plain_bytes = len(json.dumps(plain, separators=(",", ":")))
    print(f"usd_stage sphere+materiallibrary: plain {plain_bytes} B, all includes {full_bytes} B")
    assert plain_bytes < 2_000
    assert full_bytes < 16_000


def test_depth_is_capped(client):
    out = _scene()
    error = client.error("usd_stage", {"lop_path": out.path(), "depth": 17})
    assert error["code"] == "invalid_argument"
    assert client.ok("usd_stage", {"lop_path": out.path(), "depth": 16})["prims"]


def test_collection_stops_after_the_page(client, monkeypatch):
    from hocuspocus.host.tools import usd

    stage = hou.node("/stage")
    prev = None
    for i in range(20):
        node = stage.createNode("sphere", f"s{i}")
        node.parm("primpath").set(f"/geo/s{i}")
        if prev is not None:
            node.setInput(0, prev)
        prev = node
    rows = []
    real = usd.prim_row

    def counting(*a, **kw):
        rows.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(usd, "prim_row", counting)
    walked = []
    real_walk = usd._walk

    def spy_walk(prim, depth, out, *, include_self, stop=None):
        real_walk(prim, depth, out, include_self=include_self, stop=stop)
        walked.append(len(out))

    monkeypatch.setattr(usd, "_walk", spy_walk)
    result = client.ok("usd_stage", {"lop_path": prev.path(), "prim": "/geo", "limit": 3})
    assert [p["path"] for p in result["prims"]] == ["/geo", "/geo/s0", "/geo/s1"]
    assert result["next_cursor"] == "3"
    assert walked == [4]  # cursor + limit + 1, not all 21 prims
    assert len(rows) == 3  # rows only for the page; total comes from a counting walk
    assert result["total"] == 21
    last = client.ok(
        "usd_stage", {"lop_path": prev.path(), "prim": "/geo", "limit": 50, "cursor": "18"}
    )
    assert [p["path"] for p in last["prims"]] == ["/geo/s17", "/geo/s18", "/geo/s19"]
    assert last["total"] == 21 and "next_cursor" not in last


def test_time_cooks_the_lop_at_that_frame(client):
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    sphere.parm("radius").setExpression("$F")
    sphere.setDisplayFlag(True)
    hou.setFrame(1)
    args = {"lop_path": sphere.path(), "prim": "/sphere1", "include": ["attributes"]}
    now = client.ok("usd_stage", args)["prims"][0]
    later = client.ok("usd_stage", {**args, "time": 5})["prims"][0]
    radius = {a["name"]: a for a in now["attributes"]}["radius"]
    assert radius["value"] == 1
    radius = {a["name"]: a for a in later["attributes"]}["radius"]
    assert radius["value"] == 5
    assert hou.frame() == 1  # the current frame is restored


def _city():
    """/city with three meshes (two buildings and the ground) and a camera."""
    stage = hou.node("/stage")
    prev = None
    for name, t in (("bldg_000", (0, 1, 0)), ("bldg_001", (4, 1, 0)), ("ground", (0, 0, 0))):
        node = stage.createNode("cube", name)
        node.parm("primpath").set(f"/city/{name}")
        node.parmTuple("t").set(t)
        if prev is not None:
            node.setInput(0, prev)
        prev = node
    cam = stage.createNode("camera", "cam")
    cam.setInput(0, prev)
    cam.parmTuple("t").set((0, 2, 10))
    return cam


def test_summary_counts_and_bounds(client):
    out = _city()
    result = client.ok("usd_stage", {"lop_path": out.path(), "prim": "/city", "summary": True})
    assert "prims" not in result
    summary = result["summary"]
    assert summary["total_prims"] == 4  # /city and its three cubes
    assert summary["counts_by_type"]["Cube"] == 3
    box = summary["bbox_world"]
    assert box["min"] == [-1, -1, -1] and box["max"] == [5, 2, 1]
    assert box["size"] == [6, 3, 2]
    whole = client.ok("usd_stage", {"lop_path": out.path(), "summary": True})["summary"]
    assert whole["counts_by_type"]["Camera"] == 1
    assert "HoudiniLayerInfo" not in json.dumps(whole)
    pattern = client.ok(
        "usd_stage", {"lop_path": out.path(), "prim": "/city/bldg_*", "summary": True}
    )["summary"]
    assert pattern["total_prims"] == 2
    assert len(json.dumps(result)) < 400


def test_attribs_glob_filters_attributes(client):
    out = _city()
    result = client.ok(
        "usd_stage",
        {"lop_path": out.path(), "prim": "/cameras/cam", "attribs": "focal*|xformOpOrder"},
    )
    (cam,) = result["prims"]
    names = {a["name"] for a in cam["attributes"]}
    assert "focalLength" in names and "xformOpOrder" in names
    assert all(n.startswith("focal") or n == "xformOpOrder" for n in names)
    order = {a["name"]: a for a in cam["attributes"]}["xformOpOrder"]["value"]
    assert isinstance(order, list)  # shown in full
    commas = client.ok(
        "usd_stage",
        {"lop_path": out.path(), "prim": "/cameras/cam", "attribs": "focal*, xformOpOrder"},
    )
    assert {a["name"] for a in commas["prims"][0]["attributes"]} == names
    bad = client.error("usd_stage", {"lop_path": out.path(), "attribs": ""})
    assert bad["code"] == "invalid_argument"


def test_world_is_kept_when_parents_move(client):
    sphere = hou.node("/stage").createNode("sphere", "sphere1")
    sphere.parm("primpath").set("/grp/ball")
    xform = hou.node("/stage").createNode("xform", "move")
    xform.setInput(0, sphere)
    xform.parm("primpattern").set("/grp")
    xform.parmTuple("t").set((0, 5, 0))
    result = client.ok(
        "usd_stage", {"lop_path": xform.path(), "prim": "/grp/ball", "include": ["xform"]}
    )
    block = result["prims"][0]["xform"]
    assert block["local"] == "identity"
    assert block["world"][3][:3] == [0, 5, 0]
