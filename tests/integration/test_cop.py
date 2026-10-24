"""Copernicus (Cop) networks through the tools: looking at, inspecting, discovering and
editing image nodes (review 18)."""

from __future__ import annotations

import json
import os
import time

import pytest

hou = pytest.importorskip("hou")

from hocuspocus.host.tools import events as ev  # noqa: E402


def _fwd(path) -> str:
    return str(path).replace("\\", "/")


@pytest.fixture
def copnet():
    net = hou.node("/img").createNode("copnet", "citymap")
    noise = net.createNode("fractalnoise", "noise")
    color = net.createNode("constant", "color")
    color.parm("signature").set("f3")
    color.parmTuple("f3").set((0.2, 0.5, 0.9))
    comp = net.createNode("blend", "comp")
    comp.setNamedInput("bg", color, 0)
    comp.setNamedInput("fg", noise, 0)
    comp.setDisplayFlag(True)
    return net


def _children(net) -> set[str]:
    return {child.name() for child in net.children()}


# -- looking at a COP (review 18 papercut 1) --------------------------------------------


def test_look_at_a_cop_node_returns_the_image_and_leaves_nothing(client, copnet):
    before = _children(copnet)
    undo_before = list(hou.undos.undoLabels())
    since = ev.LOG.last_seq
    result = client.ok("look", {"target": f"{copnet.path()}/color"})
    assert result["scene"] == "cop"
    assert result["cop_path"] == f"{copnet.path()}/color"
    assert result["backend_used"] == "rop_image"
    assert (result["width"], result["height"]) == (1024, 1024)
    assert result["layer"]["layer_type"] == "RGB"
    assert result["layer"]["resolution"] == [1024, 1024]
    assert result["image"]["mime_type"] == "image/png"
    assert os.path.isfile(result["path"])
    assert _children(copnet) == before
    assert list(hou.undos.undoLabels()) == undo_before
    events = client.ok("events", {"since": since})["events"]
    assert not [e for e in events if e["path"].startswith(copnet.path())], events


def test_look_cop_errors_point_at_the_cop_target(client, copnet):
    """A Cop node passed as the camera, or with a camera, names target."""
    comp = f"{copnet.path()}/comp"
    error = client.error("look", {"camera": comp})
    assert error["code"] == "invalid_argument"
    assert "target" in error["hint"], error
    error = client.error("look", {"target": comp, "camera": "/obj/cam1"})
    assert error["code"] == "invalid_argument"


@pytest.mark.slow
def test_look_without_target_names_the_cop_network(client, copnet):
    result = client.ok("look", {"resolution": [64, 48]})
    assert result["scene"] == "obj"
    assert any(copnet.path() in n and "Cop node as target" in n for n in result["notes"])


# -- render and cook on COP nodes (review 18 papercuts 2, 7, 8) --------------------------


def test_render_on_a_cop_node_points_at_rop_image(client, copnet):
    rop = copnet.createNode("rop_image", "out_png")
    error = client.error("render", {"rop_path": f"{copnet.path()}/comp"})
    assert error["code"] == "invalid_argument"
    assert (
        "rop_image" in error["hint"] and f'look {{target: "{copnet.path()}/comp"' in error["hint"]
    )
    assert error["candidates"] == [rop.path()]
    error = client.error("render", {"rop_path": copnet.path()})
    assert error["candidates"] == [rop.path()]


def test_render_rop_image_has_no_lights_note_and_cook_hints_render(client, copnet, work_dir):
    rop = copnet.createNode("rop_image", "out_png")
    rop.parm("coppath").set(f"{copnet.path()}/comp")
    rop.parm("copoutput").set(_fwd(work_dir / "city.$F4.png"))
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    assert result["outputs"] == [_fwd(work_dir / "city.0001.png")]
    assert not any("lights" in n for n in result.get("notes", []))
    assert result["thumbnail"]["image"]["mime_type"] == "image/png"
    cooked = client.ok("cook", {"paths": [rop.path()]})
    assert any("render" in n for n in cooked["notes"])


def test_render_tif_thumbnail_never_raises(client, copnet, work_dir):
    rop = copnet.createNode("rop_image", "out_tif")
    rop.parm("coppath").set(f"{copnet.path()}/comp")
    rop.parm("copoutput").set(_fwd(work_dir / "city.$F4.tif"))
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    assert "thumbnail_error" not in result
    assert "thumbnail" in result or any("thumbnail" in n.lower() for n in result["notes"])


# -- inspecting a COP (review 18 papercut 3) ---------------------------------------------


def test_geo_info_on_a_cop_node_summarises_the_image(client, copnet):
    result = client.ok("geo_info", {"path": f"{copnet.path()}/color"})
    assert result["kind"] == "image"
    assert result["layer_type"] == "RGB"
    assert result["resolution"] == [1024, 1024]
    assert result["data_window"] == [0, 0, 1024, 1024]
    channels = result["channels"]
    assert list(channels) == ["r", "g", "b"]
    assert channels["g"]["min"] == pytest.approx(0.5)
    assert channels["b"]["max"] == pytest.approx(0.9)
    assert len(json.dumps(result)) < 1000
    noise = client.ok("geo_info", {"path": f"{copnet.path()}/noise"})
    assert noise["layer_type"] == "Mono"
    stats = noise["channels"]["mono"]
    assert 0 <= stats["min"] < stats["mean"] < stats["max"] <= 1
    tiles = copnet.createNode("tilepattern", "tiles")
    multi = client.ok("geo_info", {"path": tiles.path()})
    assert [o["name"] for o in multi["other_outputs"]] == ["id", "uv"]


# -- signature and other string menus (review 18 papercut 4) -----------------------------


def test_signature_menu_is_listed_and_validated(client, copnet):
    path = f"{copnet.path()}/noise/signature"
    parm = client.ok("parm_get", {"paths": [path], "include": ["menu"]})["parms"][0]
    tokens = [item["token"] for item in parm["menu"]["items"]]
    assert tokens == ["default", "f2", "f3", "f4"]
    result = client.ok("parm_set", {"items": [{"path": path, "value": "RGB"}]})["results"][0]
    assert result["value"] == "f3"
    assert any("f3" in note for note in result["notes"])
    error = client.error("parm_set", {"items": [{"path": path, "value": "bogus"}]})
    assert error["code"] == "invalid_value"
    info = client.ok(
        "node_type_info", {"type": "Cop/fractalnoise", "detail": "full", "parms": "signature"}
    )
    (row,) = info["parms"]
    assert [item[0] for item in row["menu"]["items"]] == ["default", "f2", "f3", "f4"]


def test_menu_labels_lose_their_icon_markup(client, copnet):
    info = client.ok("node_type_info", {"type": "Cop/blend", "detail": "full", "parms": "mode"})
    labels = [label for _token, label in info["parms"][0]["menu"]["items"]]
    assert "Over" in labels and not any(label.startswith("![") for label in labels)
    parm = client.ok("parm_get", {"paths": [f"{copnet.path()}/comp/mode"], "include": ["menu"]})
    assert all(not item["label"].startswith("![") for item in parm["parms"][0]["menu"]["items"])
    result = client.ok(
        "parm_set", {"items": [{"path": f"{copnet.path()}/comp/mode", "value": "Multiply"}]}
    )["results"][0]
    assert result["value"] == "multiply"


# -- discovery (review 18 papercuts 5, 6) ------------------------------------------------


def _names(client, query: str, **kw) -> list[str]:
    result = client.ok("node_type_search", {"query": query, "category": "Cop", **kw})
    return [row["name"] for row in result["results"]]


def test_search_knows_the_copernicus_vocabulary(client):
    assert "remap" in _names(client, "threshold")[:3]
    assert "ramp" in _names(client, "gradient")[:3]
    assert "blend" in _names(client, "composite")[:3]
    assert "blend" in _names(client, "over")[:3]
    assert _names(client, "text")[0] == "font"


def test_search_notes_legacy_cop2_and_names_container_children(client):
    legacy = client.ok("node_type_search", {"query": "noise", "category": "Cop2"})
    assert any("Cop2" in note and "legacy" in note for note in legacy["notes"])
    copnets = client.ok("node_type_search", {"query": "copnet", "limit": 30})
    rows = {(row["category"], row["name"]): row for row in copnets["results"]}
    top = rows[("CopNet", "copnet")]
    assert top["child_category"] == "Cop"
    assert "/img" in top["typical_parents"]
    assert rows[("Sop", "copnet")]["child_category"] == "Cop"


# -- compact type info and ramps (review 18 papercuts 9, 10) -----------------------------


def test_compact_type_info_collapses_menu_variants(client):
    info = client.ok("node_type_info", {"type": "Cop/tilepattern"})
    size = len(json.dumps(info, separators=(",", ":")))
    assert size < 9000, size  # 14.7 KB in review 18
    assert info["variants"]["patterntype"] > 50
    names = {row[0] for rows in info["parms"].values() for row in rows}
    assert "stackbond_div" in names and "herringbone32_div" not in names
    assert any("patterntype" in note for note in info["notes"])
    small = client.ok("node_type_info", {"type": "Cop/blend"})
    assert "variants" not in small


def test_ramp_values_are_rounded_and_returned_once(client):
    net = hou.node("/img").createNode("copnet", "ramps")
    created = client.ok("node_create", {"items": [{"parent": net.path(), "type": "ramp"}]})
    ramp = hou.node(created["results"][0]["path"])
    since = ev.LOG.last_seq
    item = {
        "path": f"{ramp.path()}/ramp",
        "ramp": {
            "basis": "linear",
            "keys": [0, 0.55, 1],
            "values": [[0.02, 0.05, 0.2], [0.1, 0.4, 0.45], [0.9, 0.8, 0.7]],
        },
    }
    result = client.ok("parm_set", {"items": [item]})["results"][0]
    assert result["value"]["keys"] == [0, 0.55, 1]
    assert result["value"]["values"][0] == [0.02, 0.05, 0.2]
    assert "raw" not in result
    got = client.ok("parm_get", {"paths": [f"{ramp.path()}/ramp"], "include": ["ramp"]})
    parm = got["parms"][0]
    assert parm["ramp"] == {"count": 3} and parm["value"]["keys"] == [0, 0.55, 1]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        client.host.executor.pump_once(0.05)
    events = client.ok("events", {"since": since})["events"]
    ramp_events = [e for e in events if e["kind"] == "ParmTupleChanged"]
    assert len(ramp_events) == 1, ramp_events
    assert ramp_events[0]["detail"]["parm"] == "ramp"


# -- events (review 18 papercut 10) -------------------------------------------------------


def test_hip_save_stage_writes_are_not_the_agents(client, copnet, work_dir):
    client.ok("node_info", {"paths": ["/stage"]})  # watched from now on
    since = ev.LOG.last_seq
    client.ok("hip_save", {"path": _fwd(work_dir / "cop.hip")})
    events = client.ok("events", {"since": since})["events"]
    assert not [e for e in events if e["path"] == "/stage" and e["origin"] == "agent"], events
