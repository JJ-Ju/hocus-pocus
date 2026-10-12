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
    assert extent["value"]["len"] == 2
    assert extent["value"]["first"][0] == [-1, -1, -1]
    order = attrs["xformOpOrder"]["value"]
    assert order["len"] >= 1 and isinstance(order["first"][0], str)
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
    world = sphere["xform"]["world"]
    assert world[3][:3] == [0, 2, 0]
    assert sphere["xform"]["local"] == world
    assert "xform" not in rows["/materials"]  # a Scope is not xformable
    assert "material" not in rows["/materials"]


def test_identity_xform_is_compact(client):
    sphere = hou.node("/stage").createNode("sphere", "sphere1")
    result = client.ok(
        "usd_stage", {"lop_path": sphere.path(), "prim": "/sphere1", "include": ["xform"]}
    )
    assert result["prims"][0]["xform"] == {"local": "identity", "world": "identity"}


def test_layers(client):
    out = _scene()
    result = client.ok("usd_stage", {"lop_path": out.path(), "include": ["layers"]})
    layers = result["layers"]
    assert layers["stack"] and all(isinstance(i, str) for i in layers["stack"])
    assert isinstance(layers["active"], str) and layers["active"]
    # Session sublayers (viewport state, solo lights, ...) are excluded.
    assert not any("Viewport State" in i for i in layers["stack"])


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
    assert first["total"] == 8  # /geo + 7 spheres
    assert [p["path"] for p in first["prims"]] == ["/geo", "/geo/s0", "/geo/s1"]
    seen = [p["path"] for p in first["prims"]]
    cursor = first["next_cursor"]
    while cursor:
        page = client.ok("usd_stage", {**args, "cursor": cursor})
        seen += [p["path"] for p in page["prims"]]
        cursor = page.get("next_cursor")
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


def test_errors(client):
    out = _scene()
    missing = client.error("usd_stage", {"lop_path": out.path(), "prim": "/sphere2"})
    assert missing["code"] == "invalid_argument"
    assert "/sphere1" in missing["candidates"]
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
