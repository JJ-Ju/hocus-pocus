"""parm_get / parm_set and the shared parm engine against real Houdini (BIBLE §4.5, §5)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.compat_1x  # the 1.4 tools (conftest: compat_client)

hou = pytest.importorskip("hou")


@pytest.fixture
def scene():
    hou.hipFile.clear(suppress_save_prompt=True)
    geo = hou.node("/obj").createNode("geo", "geo1")
    box = geo.createNode("box", "box1")
    xform = geo.createNode("xform", "xform1")
    xform.setInput(0, box)
    hou.setFrame(1)
    return {"geo": geo, "box": box, "xform": xform}


def _get(client, path, **kw):
    result = client.ok("parm_get", {"paths": [path], **kw})
    assert len(result["parms"]) == 1
    return result["parms"][0]


def _set(client, item, **kw):
    result = client.ok("parm_set", {"items": [item], **kw})
    assert len(result["results"]) == 1
    return result["results"][0]


# -- resolution: tuple vs component ------------------------------------------------


def test_tuple_path_reads_all_components(client, scene):
    parm = _get(client, "/obj/geo1/box1/size")
    assert parm["kind"] == "tuple"
    assert parm["component_names"] == ["sizex", "sizey", "sizez"]
    assert parm["value"] == [1.0, 1.0, 1.0]
    assert parm["type"] == "float"
    assert parm["is_default"] is True
    assert parm["locked"] is False


def test_component_path_reads_one_component(client, scene):
    parm = _get(client, "/obj/geo1/box1/sizex")
    assert parm["kind"] == "parm"
    assert parm["tuple"] == "size"
    assert parm["name"] == "sizex"
    assert parm["value"] == 1.0
    assert "raw" not in parm  # rawValue() "1" is the value as text


def test_raw_is_left_out_for_plain_numbers(client, scene):
    """Review 13/16: parm_set and parm_get returned "value":1.8,"raw":"1.8"."""
    res = _set(client, {"path": "/obj/geo1/box1/sizex", "value": 1.8})
    assert res["value"] == 1.8 and "raw" not in res, res
    res = _set(client, {"path": "/obj/geo1/t", "value": [430, 300, 430.25]})
    assert res["value"] == [430, 300, 430.25] and "raw" not in res, res
    got = _get(client, "/obj/geo1/t")
    assert "raw" not in got, got
    hou.parm("/obj/geo1/tx").setExpression("$F*2")
    keyed = _get(client, "/obj/geo1/t")
    assert keyed["raw"][0] == "$F*2", keyed


def test_tuple_set_list_and_component_set_scalar(client, scene):
    res = _set(client, {"path": "/obj/geo1/box1/size", "value": [2, 3, 4]})
    assert res["value"] == [2.0, 3.0, 4.0]
    assert res["wrote_keyframe"] is False
    assert res["is_default"] is False
    assert res["errors"] == [] and "warnings" in res
    res = _set(client, {"path": "/obj/geo1/box1/sizey", "value": 5})
    assert res["value"] == 5.0
    assert scene["box"].parmTuple("size").eval() == (2.0, 5.0, 4.0)


def test_tuple_shape_mismatches_are_invalid_value(client, scene):
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/size", "value": 2}]})
    assert err["code"] == "invalid_value"
    assert "sizex" in err["hint"]
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/size", "value": [1, 2]}]})
    assert err["code"] == "invalid_value"
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "value": [1, 2]}]})
    assert err["code"] == "invalid_value"
    assert "tuple path" in err["hint"]


def test_parm_not_found_carries_candidates(client, scene):
    err = client.error("parm_get", {"paths": ["/obj/geo1/xform1/translate"]})
    assert err["code"] == "parm_not_found"
    assert err["candidates"][0] == "t"
    assert "tuple" in err["hint"] and "tx/ty/tz" in err["hint"]
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sise", "value": [1, 1, 1]}]})
    assert err["code"] == "parm_not_found"
    assert "size" in err["candidates"]
    err = client.error("parm_get", {"paths": ["/obj/geo1/box2/sizex"]})
    assert err["code"] == "node_not_found"
    assert "/obj/geo1/box1" in err["candidates"]


# -- expressions and animation -----------------------------------------------------


def test_expression_set_and_read_at_frames(client, scene):
    res = _set(client, {"path": "/obj/geo1/xform1/ty", "expression": "$F*0.1"})
    assert res["expression"] == "$F*0.1"
    assert res["language"] == "hscript"
    assert res["wrote_keyframe"] is False
    at10 = _get(client, "/obj/geo1/xform1/ty", frame=10)
    assert at10["value"] == pytest.approx(1.0)
    assert at10["raw"] == "$F*0.1"
    assert at10["is_default"] is False
    at24 = client.ok("parm_get", {"paths": ["/obj/geo1/xform1/ty"], "frame": 24})
    assert at24["frame"] == 24
    assert at24["parms"][0]["value"] == pytest.approx(2.4)
    assert hou.frame() == 1  # reading at a frame does not move the playbar


def test_python_expression(client, scene):
    res = _set(
        client,
        {"path": "/obj/geo1/xform1/tx", "expression": "hou.frame() * 2", "language": "python"},
    )
    assert res["language"] == "python"
    assert _get(client, "/obj/geo1/xform1/tx", frame=5)["value"] == pytest.approx(10.0)


def test_animation_replace_makes_value_stick(client, scene):
    ty = scene["xform"].parm("ty")
    ty.setExpression("$F*0.1")
    res = _set(client, {"path": "/obj/geo1/xform1/ty", "value": 3})
    assert res["value"] == 3.0
    assert "expression" not in res and "keyed" not in res
    assert res["wrote_keyframe"] is False
    assert len(ty.keyframes()) == 0
    assert ty.evalAtFrame(50) == 3.0


def test_animation_keep_reports_what_houdini_did(client, scene):
    ty = scene["xform"].parm("ty")
    ty.setExpression("$F*0.1")
    res = _set(client, {"path": "/obj/geo1/xform1/ty", "value": 3, "animation": "keep"}, frame=10)
    # Houdini adds a key but the expression still drives the parm.
    assert res["wrote_keyframe"] is True
    assert res["value"] == pytest.approx(1.0)
    assert res["expression"] == "$F*0.1"
    assert any("animation: replace" in note for note in res["notes"])
    assert len(ty.keyframes()) == 2


def test_animation_keep_on_keyed_parm_inserts_key(client, scene):
    tz = scene["xform"].parm("tz")
    for frame, value in ((1, 0.0), (24, 5.0)):
        key = hou.Keyframe()
        key.setFrame(frame)
        key.setValue(value)
        tz.setKeyframe(key)
    res = _set(client, {"path": "/obj/geo1/xform1/tz", "value": 9, "animation": "keep"}, frame=10)
    assert res["wrote_keyframe"] is True
    assert res["value"] == pytest.approx(9.0)
    assert res["keyed"] is True
    assert [k.frame() for k in tz.keyframes()] == [1.0, 10.0, 24.0]


def test_animation_key_and_keyframes(client, scene):
    res = _set(client, {"path": "/obj/geo1/xform1/tx", "value": 5, "animation": "key"}, frame=10)
    assert res["wrote_keyframe"] is True
    res = _set(client, {"path": "/obj/geo1/xform1/tx", "keyframe": {"frame": 20, "value": 9}})
    assert res["wrote_keyframe"] is True
    assert res["keyed"] is True
    got = _get(client, "/obj/geo1/xform1/tx", frame=10, include=["keys"])
    assert got["keyframes"] == {"count": 2, "first": 10.0, "last": 20.0}
    assert got["value"] == pytest.approx(5.0)
    assert _get(client, "/obj/geo1/xform1/tx", frame=20)["value"] == pytest.approx(9.0)
    # keyframes with replace swaps the whole animation
    res = _set(
        client,
        {
            "path": "/obj/geo1/xform1/tx",
            "keyframes": [{"frame": 1, "value": 0}, {"frame": 48, "value": 2}],
        },
    )
    assert res["wrote_keyframe"] is True
    assert [k.frame() for k in scene["xform"].parm("tx").keyframes()] == [1.0, 48.0]
    # key on a tuple path is refused with a component hint
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/xform1/t", "keyframe": {"value": 1}}]}
    )
    assert err["code"] == "invalid_argument"
    assert "/obj/geo1/xform1/tx" in err["hint"]


def test_keyframe_replace_drops_expression(client, scene):
    tx = scene["xform"].parm("tx")
    tx.setExpression("$F")
    res = _set(client, {"path": "/obj/geo1/xform1/tx", "keyframe": {"frame": 10, "value": 3}})
    assert res["wrote_keyframe"] is True
    assert any("Removed the expression" in n for n in res["notes"])
    assert tx.evalAtFrame(10) == pytest.approx(3.0)


def test_channel_ref(client, scene):
    res = _set(client, {"path": "/obj/geo1/xform1/sx", "channel_ref": "/obj/geo1/box1/sizex"})
    assert res["expression"] == 'ch("../box1/sizex")'
    assert res["wrote_keyframe"] is False
    scene["box"].parm("sizex").set(4)
    assert _get(client, "/obj/geo1/xform1/sx")["value"] == pytest.approx(4.0)
    # tuple to tuple
    other = scene["geo"].createNode("xform", "xform2")
    other.parmTuple("t").set((1, 2, 3))
    res = _set(client, {"path": "/obj/geo1/xform1/t", "channel_ref": "/obj/geo1/xform2/t"})
    assert res["value"] == [1.0, 2.0, 3.0]
    assert set(res["expressions"]) == {"tx", "ty", "tz"}
    err = client.error(
        "parm_set",
        {"items": [{"path": "/obj/geo1/xform1/tx", "channel_ref": "/obj/geo1/xform2/t"}]},
    )
    assert err["code"] == "invalid_value"


def test_broken_expression_surfaces_node_errors(client, scene):
    res = _set(client, {"path": "/obj/geo1/box1/sizex", "expression": "foo("})
    assert res["expression"] == "foo("
    assert res["errors"], res
    assert res["cook_state"] == "error"


# -- menus, strings ----------------------------------------------------------------


def test_menu_by_token_label_and_index(client, scene):
    res = _set(client, {"path": "/obj/geo1/xform1/xOrd", "value": "trs"})
    assert res["value"] == "trs" and res["menu_token"] == "trs"
    assert "notes" not in res
    res = _set(client, {"path": "/obj/geo1/xform1/xOrd", "value": "Rot Scale Trans"})
    assert res["value"] == "rst"
    assert "rst" in res["notes"][0]
    res = _set(client, {"path": "/obj/geo1/xform1/xOrd", "value": 0})
    assert res["value"] == "srt"
    assert res["is_default"] is True
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/xform1/xOrd", "value": "zzz"}]})
    assert err["code"] == "invalid_value"
    assert "srt" in err["candidates"]
    assert "Scale Rot Trans" in err["hint"]
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/xform1/xOrd", "value": 99}]})
    assert err["code"] == "invalid_value"
    got = _get(client, "/obj/geo1/xform1/xOrd", include=["menu", "template"])
    assert got["type"] == "menu"
    assert got["menu"]["token"] == "srt" and got["menu"]["label"] == "Scale Rot Trans"
    assert got["menu"]["index"] == 0
    assert {"token": "trs", "label": "Trans Rot Scale"} in got["menu"]["items"]
    assert got["template"]["default"] == "srt"


def test_string_raw_vs_expanded(client, scene):
    file_sop = scene["geo"].createNode("file", "file1")
    res = _set(client, {"path": "/obj/geo1/file1/file", "value": "$HIP/geo/foo.bgeo"})
    assert res["raw"] == "$HIP/geo/foo.bgeo"
    assert "$HIP" not in res["value"]
    assert res["value"] == hou.text.expandString("$HIP/geo/foo.bgeo")
    assert file_sop.parm("file").unexpandedString() == "$HIP/geo/foo.bgeo"
    got = _get(client, "/obj/geo1/file1/file", include=["template"])
    assert got["type"] == "string"
    assert got["template"]["string_type"] == "FileReference"


# -- ramps, multiparms, buttons, defaults ------------------------------------------


def test_ramp(client, scene):
    node = scene["geo"].createNode("attribremap", "remap1")
    res = _set(
        client,
        {
            "path": "/obj/geo1/remap1/remap",
            "ramp": {
                "basis": ["linear", "constant", "linear"],
                "keys": [0, 0.5, 1],
                "values": [0, 1, 0.25],
            },
        },
    )
    assert res["value"]["keys"] == [0.0, 0.5, 1.0]
    assert res["value"]["basis"] == ["linear", "constant", "linear"]
    assert res["is_default"] is False
    assert node.parm("remap").eval().lookup(0.25) == pytest.approx(0.5)
    got = _get(client, "/obj/geo1/remap1/remap", include=["ramp", "multiparm"])
    assert got["type"] == "ramp"
    assert got["ramp"] == {"count": 3}  # the keys are in value, once (review 18)
    assert got["value"]["is_color"] is False
    assert got["multiparm"]["count"] == 3
    err = client.error(
        "parm_set",
        {
            "items": [
                {
                    "path": "/obj/geo1/remap1/remap",
                    "ramp": {"basis": "wobbly", "keys": [0], "values": [1]},
                }
            ]
        },
    )
    assert err["code"] == "invalid_value" and "linear" in err["candidates"]
    scene["geo"].createNode("color", "color1")
    res = _set(
        client,
        {
            "path": "/obj/geo1/color1/ramp",
            "ramp": {"keys": [0, 1], "values": [[1, 0, 0], [0, 0, 1]]},
        },
    )
    assert res["value"]["is_color"] is True
    assert res["value"]["values"] == [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]


def test_multiparm_count(client, scene):
    node = scene["geo"].createNode("attribcreate", "attribcreate1")
    res = _set(client, {"path": "/obj/geo1/attribcreate1/numattr", "multiparm_count": 3})
    assert res["value"] == 3
    got = _get(client, "/obj/geo1/attribcreate1/numattr", include=["multiparm"])
    assert got["type"] == "multiparm"
    assert got["multiparm"]["count"] == 3
    assert len(got["multiparm"]["instances"]) == 3
    assert "name3" in got["multiparm"]["instances"][2]
    assert node.parm("name3") is not None
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "multiparm_count": 2}]}
    )
    assert err["code"] == "invalid_value"


def test_revert_to_default(client, scene):
    box = scene["box"]
    box.parm("sizex").setExpression("$F*3")
    res = _set(client, {"path": "/obj/geo1/box1/sizex", "revert_to_default": True})
    assert res["is_default"] is True and res["value"] == 1.0
    assert len(box.parm("sizex").keyframes()) == 0
    box.parmTuple("t").set((1, 2, 3))
    res = _set(client, {"path": "/obj/geo1/box1/t", "revert_to_default": True})
    assert res["value"] == [0.0, 0.0, 0.0] and res["is_default"] is True


def test_press_button(client, scene):
    scene["geo"].createNode("file", "file1")
    res = _set(client, {"path": "/obj/geo1/file1/reload", "press": True})
    assert res["wrote_keyframe"] is False
    assert res["pressed"] is True and "value" not in res  # a button has no value
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "press": True}]})
    assert err["code"] == "invalid_value"
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/file1/reload", "value": 1}]})
    assert err["code"] == "invalid_value" and "press" in err["hint"]


def test_is_default_behaviour(client, scene):
    assert _get(client, "/obj/geo1/box1/sizex")["is_default"] is True
    _set(client, {"path": "/obj/geo1/box1/sizex", "value": 2})
    assert _get(client, "/obj/geo1/box1/sizex")["is_default"] is False
    assert _get(client, "/obj/geo1/box1/size")["is_default"] is False
    assert _get(client, "/obj/geo1/box1/sizey")["is_default"] is True
    _set(client, {"path": "/obj/geo1/box1/sizex", "value": 1})
    assert _get(client, "/obj/geo1/box1/size")["is_default"] is True
    # an expression is never "at default", even when it evaluates to the default
    _set(client, {"path": "/obj/geo1/box1/sizex", "expression": "1"})
    assert _get(client, "/obj/geo1/box1/sizex")["is_default"] is False


# -- validation ---------------------------------------------------------------------


def test_invalid_value_type_and_strict_range(client, scene):
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "value": "abc"}]})
    assert err["code"] == "invalid_value"
    assert err["detail"]["type"] == "float"
    assert "expression" in err["hint"]
    # divrate has a strict minimum of 1; Houdini would clamp 0 silently
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/box1/divrate", "value": [0, 4, 4]}]}
    )
    assert err["code"] == "invalid_value"
    assert err["detail"]["min"] == 1 and err["detail"]["min_strict"] is True
    assert ">= 1" in err["hint"]
    assert scene["box"].parmTuple("divrate").eval() == (4, 4, 4)
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sizex"}]})
    assert err["code"] == "invalid_argument"
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "value": 1, "expression": "$F"}]}
    )
    assert err["code"] == "invalid_argument"


def test_template_include(client, scene):
    got = _get(client, "/obj/geo1/box1/divrate", include=["template"])
    tmpl = got["template"]
    assert tmpl["type"] == "int" and tmpl["size"] == 3
    assert tmpl["default"] == [4, 4, 4]
    assert tmpl["min"] == 1 and tmpl["min_strict"] is True
    assert tmpl["label"]


def test_locked_hda_internal_parm_is_refused(client, scene, work_dir):
    sub = scene["geo"].createNode("subnet", "asset1")
    sub.createNode("box", "inner")
    hda_path = (work_dir / "hp_parms_test.hda").as_posix()
    asset = sub.createDigitalAsset(
        name="hp_parms_test_asset", hda_file_name=hda_path, description="HP parms test"
    )
    asset.matchCurrentDefinition()
    assert asset.isLockedHDA()
    err = client.error("parm_set", {"items": [{"path": f"{asset.path()}/inner/sizex", "value": 3}]})
    assert err["code"] == "locked"
    assert "node_edit" in err["hint"] and asset.path() in err["hint"]
    assert "PermissionError" in err["hou_exception"]
    assert asset.node("inner").parm("sizex").eval() == 1.0
    got = _get(client, f"{asset.path()}/inner/sizex")
    assert got["hda_locked"] is True and got["locked"] is False  # locked: the parm lock
    scene["box"].parm("sizey").lock(True)
    assert _get(client, "/obj/geo1/box1/sizey")["locked"] is True
    assert _get(client, "/obj/geo1/box1/sizey")["hda_locked"] is False


# -- batches and undo --------------------------------------------------------------


def test_failed_batch_rolls_back_earlier_items(client, scene):
    err = client.error(
        "parm_set",
        {
            "items": [
                {"path": "/obj/geo1/box1/sizex", "value": 7},
                {"path": "/obj/geo1/box1/nope", "value": 1},
            ]
        },
    )
    assert err["code"] == "parm_not_found"
    assert err["detail"] == {"item": 1, "path": "/obj/geo1/box1/nope", "rolled_back": True}
    assert err["message"].startswith("items[1] (/obj/geo1/box1/nope): ")
    assert scene["box"].parm("sizex").eval() == 1.0
    assert not any("parm_set" in label for label in hou.undos.undoLabels()[:1])


def test_partial_batch_keeps_good_items(client, scene):
    result = client.ok(
        "parm_set",
        {
            "items": [
                {"path": "/obj/geo1/box1/sizex", "value": 7},
                {"path": "/obj/geo1/box1/nope", "value": 1},
                {"path": "/obj/geo1/box1/sizez", "value": 3},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 1
    good, bad, good2 = result["results"]
    assert good["value"] == 7.0 and good2["value"] == 3.0
    assert bad["error"]["code"] == "parm_not_found"
    assert bad["wrote_keyframe"] is False
    assert scene["box"].parmTuple("size").eval() == (7.0, 1.0, 3.0)


def test_one_undo_group_per_call(client, scene):
    envelope = client.call(
        "parm_set",
        {
            "items": [
                {"path": "/obj/geo1/box1/sizex", "value": 2},
                {"path": "/obj/geo1/xform1/ty", "expression": "$F"},
            ]
        },
    )
    assert envelope["ok"], envelope
    label = envelope["_meta"]["undo_label"]
    assert label == "HocusPocus: parm_set 2 parms"
    assert hou.undos.undoLabels()[0] == label
    hou.undos.performUndo()
    assert scene["box"].parm("sizex").eval() == 1.0
    assert len(scene["xform"].parm("ty").keyframes()) == 0


def test_parm_get_is_read_only(client, scene):
    envelope = client.call("parm_get", {"paths": ["/obj/geo1/box1/size"]})
    assert envelope["ok"] and envelope["_meta"]["undo_label"] is None


# -- shared helpers (in-process) -----------------------------------------------------


def test_set_parm_items_engine(scene):
    from hocuspocus.host.tools.parms import set_parm_items
    from hocuspocus.tools.errors import ToolError

    box, xform = scene["box"], scene["xform"]
    xform.parm("ry").setExpression("$F")
    results = set_parm_items(
        xform,
        {
            "t": [1, 2, 3],
            "ry": 45,
            "rx": {"expr": "$F*2"},
            "xOrd": "Trans Rot Scale",
            "sx": {"channel_ref": "/obj/geo1/box1/sizex"},
        },
        None,
    )
    assert [r["path"] for r in results] == [
        "/obj/geo1/xform1/t",
        "/obj/geo1/xform1/ry",
        "/obj/geo1/xform1/rx",
        "/obj/geo1/xform1/xOrd",
        "/obj/geo1/xform1/sx",
    ]
    assert xform.parmTuple("t").eval() == (1.0, 2.0, 3.0)
    assert xform.parm("ry").evalAtFrame(99) == 45.0  # replace removed the expression
    assert xform.parm("rx").expression() == "$F*2"
    assert xform.parm("xOrd").evalAsString() == "trs"
    assert results[3]["notes"]
    assert xform.parm("sx").expression() == 'ch("../box1/sizex")'
    with pytest.raises(ToolError) as info:
        set_parm_items(box, {"sizex": 2, "bogus": 1}, None)
    assert info.value.code == "parm_not_found"
    assert info.value.message.startswith("parms.bogus")
    assert info.value.detail == {"parm": "bogus", "node": "/obj/geo1/box1"}
    with pytest.raises(ToolError) as info:
        set_parm_items(box, {"sizex": {"expr": "$F", "language": "python"}}, None)
    assert info.value.code == "invalid_argument"


def test_summarize_parm_compact(scene):
    from hocuspocus.host.tools.parms import summarize_parm

    box, xform = scene["box"], scene["xform"]
    assert summarize_parm(box.parm("sizex")) == {  # raw "1" is the value as text: left out
        "name": "sizex",
        "value": 1.0,
        "is_default": True,
    }
    box.parmTuple("size").set((2, 1, 1))
    xform.parm("ty").setExpression("$F*2")
    compact = summarize_parm(box.parmTuple("size"))
    assert compact == {
        "name": "size",
        "value": [2.0, 1.0, 1.0],
        "is_default": False,
    }
    animated = summarize_parm(xform.parmTuple("t"), frame=5)
    assert animated["value"] == [0.0, 10.0, 0.0]
    assert animated["expressions"] == {"ty": {"expression": "$F*2", "language": "hscript"}}
    menu = summarize_parm(xform.parm("xOrd"))
    assert menu["menu_token"] == "srt" and menu["value"] == "srt"
    single = summarize_parm(box.parmTuple("type"))  # one-component tuple → its parm
    assert single["name"] == "type" and single["menu_token"] == "poly"


def test_messages_and_values_are_tidy(client):
    """Review 07 papercut 10: no repeated path in messages, no float noise in values."""
    geo = hou.node("/obj").createNode("geo", "terrain")
    mountain = geo.createNode("mountain::2.0", "mountain1")
    path = f"{mountain.path()}/height"
    error = client.error("parm_set", {"items": [{"path": path, "value": "tall"}]})
    assert error["message"].count(path) == 1, error["message"]
    error = client.error(
        "parm_set",
        {"items": [{"path": f"{geo.path()}/tx", "value": 1}, {"path": path, "value": "tall"}]},
    )
    assert error["message"].startswith(f"items[1] ({path}): ") and error["message"].count(path) == 1
    client.ok("parm_set", {"items": [{"path": f"{geo.path()}/tx", "expression": "$F*0.1"}]})
    (row,) = client.ok("parm_get", {"paths": [f"{geo.path()}/tx"], "frame": 24})["parms"]
    assert row["value"] == 2.4  # not 2.4000000000000004
    error = client.error("node_create", {"items": [{"parent": geo.path(), "type": "geo"}]})
    assert "is an Object node type" in error["hint"], error


# -- review 10 fixes ---------------------------------------------------------------


def test_any_hou_error_is_invalid_value_not_internal(client, scene, monkeypatch):
    def refuse(parm, *args, **kwargs):
        raise hou.KeyframeValueNotSet()

    monkeypatch.setattr(hou.Parm, "set", refuse)
    err = client.error("parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "value": 2}]})
    assert err["code"] == "invalid_value" and "KeyframeValueNotSet" in err["hou_exception"]


def test_channel_ref_with_trailing_slash(client, scene):
    res = _set(client, {"path": "/obj/geo1/xform1/sx", "channel_ref": "/obj/geo1/box1/sizex/"})
    assert res["expression"] == 'ch("../box1/sizex")'


def test_press_and_revert_need_true(client, scene):
    scene["box"].parm("sizex").set(5)
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/box1/sizex", "revert_to_default": 0}]}
    )
    assert err["code"] == "invalid_argument"
    assert scene["box"].parm("sizex").eval() == 5.0
    res = _set(client, {"path": "/obj/geo1/box1/sizex", "value": 2, "revert_to_default": 0})
    assert res["value"] == 2.0


def test_partial_restores_a_half_applied_item(client, scene):
    box = scene["box"]
    box.parm("sizey").lock(True)
    result = client.ok(
        "parm_set",
        {
            "items": [
                {"path": "/obj/geo1/box1/size", "value": [4, 4, 4]},
                {"path": "/obj/geo1/xform1/tx", "value": 2},
            ],
            "partial": True,
        },
    )
    assert result["failed"] == 1 and result["results"][0]["error"]["code"] == "locked"
    assert box.parmTuple("size").eval() == (1.0, 1.0, 1.0)  # sizex was set, then restored
    assert scene["xform"].parm("tx").eval() == 2.0
    keyed = scene["xform"].parm("ty")
    keyed.setExpression("$F")
    scene["xform"].parm("tz").lock(True)
    result = client.ok(
        "parm_set",
        {"items": [{"path": "/obj/geo1/xform1/t", "value": [1, 1, 1]}], "partial": True},
    )
    assert result["failed"] == 1
    assert keyed.expression() == "$F" and scene["xform"].parm("tx").eval() == 2.0


def test_single_keyframe_replace_keeps_other_keys(client, scene):
    tx = scene["xform"].parm("tx")
    _set(
        client,
        {"path": tx.path(), "keyframes": [{"frame": 1, "value": 0}, {"frame": 10, "value": 5}]},
    )
    _set(client, {"path": tx.path(), "keyframe": {"frame": 5, "value": 9}})
    assert [k.frame() for k in tx.keyframes()] == [1.0, 5.0, 10.0]
    _set(client, {"path": tx.path(), "keyframes": [{"frame": 2, "value": 1}]})
    assert [k.frame() for k in tx.keyframes()] == [2.0]


def test_editable_node_inside_locked_asset_is_not_locked(client, scene, work_dir):
    sub = scene["geo"].createNode("subnet", "asset1")
    sub.createNode("box", "inner")
    sub.createNode("box", "sealed")
    hda_path = (work_dir / "hp_editable_test.hda").as_posix()
    asset = sub.createDigitalAsset(name="hp_editable_test", hda_file_name=hda_path)
    asset.type().definition().addSection("EditableNodes", "inner")
    asset.matchCurrentDefinition()
    assert asset.node("inner").isEditableInsideLockedHDA()
    assert _get(client, f"{asset.path()}/inner/sizex")["hda_locked"] is False
    assert _get(client, f"{asset.path()}/sealed/sizex")["hda_locked"] is True
    assert _get(client, f"{asset.path()}/sealed/sizex")["locked"] is False
    res = _set(client, {"path": f"{asset.path()}/inner/sizex", "value": 3})
    assert res["value"] == 3.0 and "locked" not in res and "hda_locked" not in res


def test_node_create_parms_accept_parm_set_item_forms(client, scene):
    from hocuspocus.tools.catalog import get
    from hocuspocus.tools.docs import validate

    args = {
        "items": [
            {
                "parent": "/obj/geo1",
                "type": "xform",
                "parms": {
                    "tx": {"keyframes": [{"frame": 1, "value": 0}, {"frame": 9, "value": 2}]},
                    "sx": {"channel_ref": "/obj/geo1/box1/sizex"},
                    "ty": {"expression": "$F", "language": "hscript"},
                    "tz": {"expr": "$T"},
                },
            },
            {
                "parent": "/obj/geo1",
                "type": "attribcreate",
                "parms": {"numattr": {"multiparm_count": 2}},
            },
        ]
    }
    validate(args, get("node_create").input_schema)
    created = client.ok("node_create", args)
    xf = hou.node(created["created"][0])
    assert len(xf.parm("tx").keyframes()) == 2
    assert xf.parm("sx").expression() == 'ch("../box1/sizex")'
    assert hou.node(created["created"][1]).parm("numattr").eval() == 2


# -- review 10 §5 gaps -------------------------------------------------------------


def test_expression_with_animation_key_and_keep(client, scene):
    tx = scene["xform"].parm("tx")
    res = _set(client, {"path": tx.path(), "expression": "$F*2", "animation": "key"}, frame=10)
    assert res["wrote_keyframe"] is True
    assert [(k.frame(), k.expression()) for k in tx.keyframes()] == [(10.0, "$F*2")]
    ty = scene["xform"].parm("ty")
    _set(
        client,
        {"path": ty.path(), "keyframes": [{"frame": 1, "value": 0}, {"frame": 10, "value": 5}]},
    )
    res = _set(client, {"path": ty.path(), "expression": "$F*3", "animation": "keep"}, frame=10)
    assert res["wrote_keyframe"] is False  # keep edits the key Houdini already had
    keys = [(k.frame(), k.expression()) for k in ty.keyframes()]
    assert keys[0][0] == 1.0 and keys[-1] == (10.0, "$F*3")
    assert ty.evalAtFrame(10) == pytest.approx(30.0)


def test_channel_ref_relative_python_and_self(client, scene):
    box = scene["box"]
    res = _set(client, {"path": f"{box.path()}/sizex", "channel_ref": "sizey"})
    assert res["expression"] in ('ch("sizey")', 'ch("./sizey")') and res["language"] == "hscript"
    res = _set(
        client,
        {"path": f"{box.path()}/sizez", "channel_ref": "/obj/geo1/xform1/tx", "language": "python"},
    )
    assert res["language"] == "python" and "tx" in res["expression"]
    scene["xform"].parm("tx").set(3)
    assert box.parm("sizez").eval() == pytest.approx(3.0)
    error = client.error(
        "parm_set", {"items": [{"path": f"{box.path()}/sizey", "channel_ref": "sizey"}]}
    )
    assert error["code"] == "invalid_value" and "itself" in error["message"]
    error = client.error(
        "parm_set", {"items": [{"path": f"{box.path()}/sizey", "channel_ref": "nope"}]}
    )
    assert error["code"] == "parm_not_found"


def test_duplicate_keyframe_frames_are_refused(client, scene):
    tx = scene["xform"].parm("tx")
    error = client.error(
        "parm_set",
        {
            "items": [
                {
                    "path": tx.path(),
                    "keyframes": [{"frame": 5, "value": 1}, {"frame": 5, "value": 2}],
                }
            ]
        },
    )
    assert error["code"] == "invalid_argument" and "same frame" in error["message"]
    assert not tx.keyframes()


def _spare(node, template):
    group = node.parmTemplateGroup()
    group.append(template)
    node.setParmTemplateGroup(group)
    return node.parm(template.name())


def test_dynamic_menus_are_evaluated_on_the_live_parm(client, scene):
    """Review 14 papercut 10: a script menu (pdg_cachemode) and a SOP group menu (built
    from the input's groups) are read from the parm and marked dynamic."""
    geo = scene["geo"]
    group = geo.createNode("groupcreate", "grp")
    group.setInput(0, scene["box"])
    group.parm("groupname").set("mygroup")
    blast = geo.createNode("blast", "blast1")
    blast.setInput(0, group)  # never cooked: parm_get cooks it to read the groups
    got = _get(client, f"{blast.path()}/group", include=["menu"])
    assert got["menu"]["dynamic"] is True
    assert {"token": "mygroup", "label": "mygroup"} in got["menu"]["items"]
    lonely = geo.createNode("blast", "no_input")
    got = _get(client, f"{lonely.path()}/group", include=["menu"])
    assert got["menu"]["dynamic"] is True and got["menu"]["items"] == []
    assert got["menu"]["note"]
    assert "dynamic" not in _get(client, f"{blast.path()}/grouptype", include=["menu"])["menu"]

    gen = hou.node("/obj").createNode("topnet", "topnet1").createNode("genericgenerator", "gen")
    got = _get(client, f"{gen.path()}/pdg_cachemode", include=["menu"])
    assert got["menu"]["dynamic"] is True and got["menu"]["token"] == "0"
    assert {"token": "2", "label": "Write Files"} in got["menu"]["items"]


def test_int_menus_free_menus_and_strict_ranges(client, scene):
    null = scene["geo"].createNode("null", "CTRL")
    _spare(
        null,
        hou.IntParmTemplate(
            "quality",
            "Quality",
            1,
            menu_items=("lo", "mid", "hi"),
            menu_labels=("Low", "Medium", "High"),
        ),
    )
    _spare(
        null,
        hou.StringParmTemplate(
            "shader",
            "Shader",
            1,
            menu_items=("glass", "metal"),
            menu_type=hou.menuType.StringReplace,
        ),
    )
    _spare(
        null,
        hou.FloatParmTemplate(
            "mix", "Mix", 1, min=0, max=1, min_is_strict=True, max_is_strict=True
        ),
    )
    quality = f"{null.path()}/quality"
    res = _set(client, {"path": quality, "value": "hi"})
    assert null.parm("quality").eval() == 2
    assert res["value"] == 2 and res["menu_token"] == "hi"
    res = _set(client, {"path": quality, "value": "Medium"})
    assert null.parm("quality").eval() == 1 and res["notes"]
    res = _set(client, {"path": quality, "value": 0})
    assert null.parm("quality").eval() == 0
    error = client.error("parm_set", {"items": [{"path": quality, "value": 7}]})
    assert error["code"] == "invalid_value" and "lo" in error["candidates"]
    # A free (StringReplace) menu takes any text; the menu is only a suggestion.
    res = _set(client, {"path": f"{null.path()}/shader", "value": "plastic"})
    assert res["value"] == "plastic"
    got = _get(client, f"{null.path()}/shader", include=["menu"])
    assert [i["token"] for i in got["menu"]["items"]] == ["glass", "metal"]
    mix = f"{null.path()}/mix"
    for bad, bound in ((1.5, "<= 1"), (-0.1, ">= 0")):
        error = client.error("parm_set", {"items": [{"path": mix, "value": bad}]})
        assert error["code"] == "invalid_value" and bound in error["hint"], error
    assert _set(client, {"path": mix, "value": 1})["value"] == 1.0


# -- long strings (review 12 papercut 1) -------------------------------------------

SNIPPET_400 = ("// tuned\n" + "f@d = rand(@ptnum) * 0.5;\n" * 20)[:400]


def test_long_string_is_elided_in_set_and_get(client, scene):
    wrangle = scene["geo"].createNode("attribwrangle", "tune")
    path = f"{wrangle.path()}/snippet"
    assert len(SNIPPET_400) == 400
    elided = {"elided": 400, "head": SNIPPET_400[:80]}
    res = _set(client, {"path": path, "value": SNIPPET_400})
    assert res["value"] == elided and "raw" not in res, res
    assert wrangle.parm("snippet").eval() == SNIPPET_400
    got = _get(client, path)
    assert got["value"] == elided and "raw" not in got
    whole = _get(client, path, full_strings=True)
    assert whole["value"] == SNIPPET_400 and "raw" not in whole
    short = _set(client, {"path": f"{wrangle.path()}/group", "value": "a"})
    assert short["value"] == "a" and "raw" not in short
    expanded = _set(client, {"path": f"{wrangle.path()}/group", "value": "$OS"})
    assert expanded["value"] == "tune" and expanded["raw"] == "$OS"
    error = client.error("parm_get", {"paths": [path], "full_strings": "yes"})
    assert error["code"] == "invalid_argument"


# -- press on save buttons (review 17 P0-2) and callback menus (review 17 P1-4) ----------


def _file_cache(path: str, frames=(1, 3)):
    geo = hou.node("/obj").createNode("geo", "fx")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    cache = geo.createNode("filecache::2.0", "cache")
    cache.setInput(0, box)
    cache.parm("filemethod").set(1)  # explicit file
    cache.parm("file").set(path)
    for parm, value in zip(("f1", "f2"), frames, strict=True):
        cache.parm(parm).deleteAllKeyframes()
        cache.parm(parm).set(value)
    return cache


def _fwd(path) -> str:
    return str(path).replace("\\", "/")


def test_press_save_button_verifies_the_written_files(client, tmp_path):
    cache = _file_cache(_fwd(tmp_path / "fc.$F4.bgeo.sc"))
    res = _set(client, {"path": f"{cache.path()}/execute", "press": True})
    assert res["pressed"] is True
    assert "value" not in res and "raw" not in res
    summary = res["outputs_summary"]
    assert summary["count"] == 3 and summary["missing_count"] == 0
    assert summary["pattern"] == _fwd(tmp_path / "fc.####.bgeo.sc")
    assert res["side_effects"]["loadfromdisk"] == [0, 1]
    assert len(list(tmp_path.glob("fc.*"))) == 3


def test_press_save_button_that_writes_nothing_fails(client, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so no directory can be created under it")
    cache = _file_cache(_fwd(blocker / "sub" / "fc.$F4.bgeo.sc"))
    error = client.error(
        "parm_set", {"items": [{"path": f"{cache.path()}/execute", "press": True}]}
    )
    assert error["code"] == "cook_failed", error
    assert "0 of 3" in error["message"]
    missing = error["detail"]["missing"]
    assert missing[0] == _fwd(blocker / "sub" / "fc.0001.bgeo.sc") and len(missing) == 3


def test_press_on_a_plain_button_reports_pressed(client, scene):
    geo = scene["geo"]
    cache = geo.createNode("filecache::2.0", "c2")
    res = _set(client, {"path": f"{cache.path()}/reload", "press": True})
    assert res["pressed"] is True
    assert "outputs_summary" not in res


def _pyrosource(scene):
    sphere = scene["geo"].createNode("sphere")
    source = scene["geo"].createNode("pyrosource", "src")
    source.setInput(0, sphere)
    return source


def test_plain_set_of_a_callback_menu_notes_the_skipped_callback(client, scene):
    source = _pyrosource(scene)
    res = _set(client, {"path": f"{source.path()}/initialize", "value": "source"})
    assert source.parm("initialize").evalAsString() == "source"
    assert source.parm("attributes").eval() == 0  # the callback did not run
    (note,) = [n for n in res["notes"] if "callback" in n]
    assert "press: true" in note


def test_press_with_a_value_runs_a_menu_callback(client, scene):
    source = _pyrosource(scene)
    res = _set(client, {"path": f"{source.path()}/initialize", "value": "source", "press": True})
    assert res["pressed"] is True
    # initialize is an action menu: its callback applies the preset and resets it to none.
    assert res["value"] == "none"
    assert res["side_effects"]["initialize"] == ["source", "none"]
    assert source.parm("attributes").eval() == 2  # density and temperature
    assert "attributes" in res["side_effects"], res
    assert not any("callback" in n for n in res.get("notes", []))


def test_press_alone_reruns_a_menu_callback_and_node_create_accepts_it(client, scene):
    source = _pyrosource(scene)
    source.parm("initialize").set("source")
    res = _set(client, {"path": f"{source.path()}/initialize", "press": True})
    assert res["pressed"] is True and source.parm("attributes").eval() == 2
    created = client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": scene["geo"].path(),
                    "type": "pyrosource",
                    "name": "src2",
                    "parms": {"initialize": {"value": "sourcecolor", "press": True}},
                }
            ]
        },
    )
    assert created["results"][0]["path"] == f"{scene['geo'].path()}/src2"
    assert hou.node(f"{scene['geo'].path()}/src2").parm("attributes").eval() >= 2


def test_node_create_parms_are_callback_aware(client, scene):
    """Review 20 N2: node_create parms note a skipped callback as parm_set does, and
    {value, press: true} runs it (after the inputs are wired)."""
    geo = scene["geo"].path()
    sphere = scene["geo"].createNode("sphere")
    plain = client.ok(
        "node_create",
        {"items": [{"parent": geo, "type": "pyrosource", "parms": {"initialize": "source"}}]},
    )["results"][0]
    node = hou.node(plain["path"])
    assert node.parm("attributes").eval() == 0  # the callback did not run
    (note,) = [n for n in plain["notes"] if "callback" in n]
    assert '"initialize": {"value": ..., "press": true}' in note
    pressed = client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": geo,
                    "type": "pyrosource",
                    "inputs": [{"index": 0, "from": sphere.path()}],
                    "parms": {"initialize": {"value": "source", "press": True}},
                }
            ],
            "return": "full",
        },
    )["results"][0]
    node = hou.node(pressed["path"])
    assert node.parm("attributes").eval() == 2  # density and temperature
    assert node.inputs()[0] == sphere
    assert pressed["side_effects"]["initialize"] == ["source", "none"]
    assert "attributes" in pressed["side_effects"]
    assert not any("callback" in n for n in pressed.get("notes", []))


def test_press_on_a_parm_without_callback_is_refused(client, scene):
    err = client.error(
        "parm_set", {"items": [{"path": "/obj/geo1/box1/type", "value": "polymesh", "press": True}]}
    )
    assert err["code"] == "invalid_value"
    assert "callback" in err["message"]
