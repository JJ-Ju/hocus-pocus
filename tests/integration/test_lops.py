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
