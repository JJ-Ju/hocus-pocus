"""Solaris workloads through the tools (review 13): render on USD render ROPs,
viewport_capture of a stage, USD attribute names for LOP parms, computed tuple
components, and the hints a lookdev session leans on."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")
Image = pytest.importorskip("PIL.Image")


def _fwd(path) -> str:
    return str(path).replace("\\", "/")


def _decode(image: dict):
    return Image.open(io.BytesIO(base64.b64decode(image["png_base64"])))


def _lop_scene(work_dir: Path, picture: str | None = "k.$F4.exr"):
    """sphere -> materiallibrary (MaterialX) -> assignmaterial -> dome light -> camera ->
    karmarendersettings (160x90, 1 sample) -> usdrender_rop. Returns the nodes by name."""
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    lib = stage.createNode("materiallibrary", "matlib")
    lib.setInput(0, sphere)
    lib.createNode("mtlxstandard_surface", "chrome")
    assign = stage.createNode("assignmaterial", "assign")
    assign.setInput(0, lib)
    assign.parm("primpattern1").set("/sphere1")
    assign.parm("matspecpath1").set("/materials/chrome")
    dome = stage.createNode("domelight::3.0", "dome")
    dome.setInput(0, assign)
    cam = stage.createNode("camera", "cam1")
    cam.setInput(0, dome)
    cam.parmTuple("t").set((0, 0, 6))
    rset = stage.createNode("karmarendersettings", "rset")
    rset.setInput(0, cam)
    rset.parm("camera").set("/cameras/cam1")
    rset.parm("resolutionx").set(160)  # res_mode autoheight computes resolutiony = 90
    rset.parm("samplesperpixel").set(1)
    rset.parm("picture").set("" if picture is None else _fwd(work_dir / picture))
    rset.setDisplayFlag(True)
    rop = stage.createNode("usdrender_rop", "rop")
    rop.setInput(0, rset)
    return {"sphere": sphere, "dome": dome, "cam": cam, "rset": rset, "rop": rop}


# -- render on USD render ROPs (papercuts 1 and 2) --------------------------------------


def test_render_usd_rop_reports_the_render_product(client, work_dir):
    nodes = _lop_scene(work_dir)
    result = client.ok("render", {"rop_path": nodes["rop"].path(), "wait_s": 300})
    assert result["state"] == "done"
    expected = _fwd(work_dir / "k.0001.exr")
    assert result["outputs"] == [expected]
    assert "missing" not in result
    assert not any("__render__" in p for p in result["outputs"])
    thumb = result["thumbnail"]  # converted from the EXR with iconvert
    assert thumb["path"] == expected
    assert (thumb["width"], thumb["height"]) == (160, 90)
    lo, hi = _decode(thumb["image"]).convert("L").getextrema()
    assert hi - lo > 20


def test_render_usd_rop_outputimage_wins_and_output_overrides_it(client, work_dir):
    nodes = _lop_scene(work_dir)
    rop = nodes["rop"]
    rop.parm("outputimage").set(_fwd(work_dir / "own.$F4.png"))
    result = client.ok("render", {"rop_path": rop.path(), "wait_s": 300})
    assert result["outputs"] == [_fwd(work_dir / "own.0001.png")]
    override = _fwd(work_dir / "ov.$F4.png")
    result = client.ok("render", {"rop_path": rop.path(), "output": override, "wait_s": 300})
    assert result["outputs"] == [_fwd(work_dir / "ov.0001.png")]
    assert result["thumbnail"]["path"] == _fwd(work_dir / "ov.0001.png")
    # The override went to outputimage, never to husk's intermediate USD file.
    assert rop.parm("outputimage").unexpandedString() == _fwd(work_dir / "own.$F4.png")
    assert rop.parm("lopoutput").unexpandedString() == "__render__.usd"


def test_render_out_usdrender_follows_loppath(client, work_dir):
    nodes = _lop_scene(work_dir, picture="out.$F4.exr")
    rop = hou.node("/out").createNode("usdrender", "karma_out")
    rop.parm("loppath").set(nodes["rset"].path())
    result = client.ok("render", {"rop_path": rop.path(), "wait_s": 300})
    assert result["outputs"] == [_fwd(work_dir / "out.0001.exr")]
    assert "missing" not in result


def test_render_usd_rop_failure_carries_the_husk_log(client, work_dir):
    nodes = _lop_scene(work_dir, picture=None)  # no product name: husk cannot create a file
    rop = nodes["rop"]
    error = client.error("render", {"rop_path": rop.path(), "wait_s": 300})
    assert error["code"] == "cook_failed"
    tail = error["detail"]["log_tail"]
    assert isinstance(tail, list) and 0 < len(tail) <= 20
    assert any("Unable to create file" in line for line in tail), tail
    assert "log_tail" in error["hint"]
    # The temporary log parms are put back.
    assert rop.parm("husk_log").eval() == 0
    assert rop.parm("husk_stderr").unexpandedString() == ""


def test_usd_render_outputs_note_when_nothing_resolves(client):
    from hocuspocus.host.tools.visual import usd_render_outputs

    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "sphere1")
    rop = stage.createNode("usdrender_rop", "rop")
    rop.setInput(0, sphere)
    paths, note = usd_render_outputs(rop, [1.0])
    assert paths == []
    assert "outputimage" in note and "RenderProduct" in note


# -- viewport_capture of a stage (papercut 3) -------------------------------------------


def _center_lit(image: dict) -> bool:
    img = _decode(image).convert("L")
    w, h = img.size
    center = img.getpixel((w // 2, h // 2))
    corner = img.getpixel((2, 2))
    return abs(center - corner) > 20


def test_capture_lop_camera_renders_the_stage(client, work_dir):
    nodes = _lop_scene(work_dir)
    hou.node("/obj").createNode("geo", "unrelated").createNode("box").setDisplayFlag(True)
    result = client.ok("viewport_capture", {"camera": nodes["cam"].path(), "resolution": [160, 90]})
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["rset"].path()  # the displayed LOP
    assert result["camera_used"] == "/cameras/cam1"
    assert result["source_used"] == "opengl_rop"
    assert _center_lit(result["image"])
    assert [c.name() for c in hou.node("/stage").children()] == [
        "sphere1",
        "matlib",
        "assign",
        "dome",
        "cam1",
        "rset",
        "rop",
    ]


def test_capture_camera_prim_with_lop_path(client, work_dir):
    nodes = _lop_scene(work_dir)
    result = client.ok(
        "viewport_capture",
        {"camera": "/cameras/cam1", "lop_path": nodes["cam"].path(), "resolution": [160, 90]},
    )
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["cam"].path()
    assert result["camera_used"] == "/cameras/cam1"


def test_capture_lop_path_frames_the_stage(client, work_dir):
    nodes = _lop_scene(work_dir)
    result = client.ok("viewport_capture", {"lop_path": "/stage", "resolution": [160, 120]})
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["rset"].path()
    assert result["camera_used"] == "temporary"
    assert result["fit_used"] == "all"
    assert _center_lit(result["image"])


def test_capture_without_obj_geometry_uses_the_stage(client, work_dir):
    _lop_scene(work_dir)
    result = client.ok("viewport_capture", {"resolution": [160, 120]})
    assert result["scene"] == "stage"
    assert _center_lit(result["image"])


def test_capture_obj_scene_notes_the_stage(client, work_dir):
    _lop_scene(work_dir)
    hou.node("/obj").createNode("geo", "g").createNode("box").setDisplayFlag(True)
    result = client.ok("viewport_capture", {"resolution": [160, 120]})
    assert result["scene"] == "obj"
    assert any("lop_path" in note and "/stage/rset" in note for note in result["notes"])


def test_capture_bad_lop_camera_lists_cameras(client, work_dir):
    nodes = _lop_scene(work_dir)
    error = client.error("viewport_capture", {"camera": nodes["rset"].path()})
    assert error["code"] == "invalid_argument"
    assert "not a camera" in error["message"]
    assert nodes["cam"].path() in error["candidates"]
    assert "OBJ camera such as" not in error["hint"]
    missing = client.error(
        "viewport_capture", {"camera": "/cameras/nope", "lop_path": nodes["rset"].path()}
    )
    assert missing["code"] == "invalid_argument"
    assert "/cameras/cam1" in missing["candidates"]
    viewer = client.error("viewport_capture", {"lop_path": "/stage", "source": "viewer"})
    assert viewer["code"] in ("ui_required", "invalid_argument")
