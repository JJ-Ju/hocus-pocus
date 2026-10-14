"""Solaris workloads through the tools (review 13): render on USD render ROPs,
viewport_capture of a stage, USD attribute names for LOP parms, computed tuple
components, and the hints a lookdev session leans on."""

from __future__ import annotations

import base64
import io
import json
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


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_render_unsupported_extension_notes_the_missing_thumbnail(client, work_dir):
    """Review 16 N4: an output the thumbnail cannot read said nothing."""
    nodes = _lop_scene(work_dir)
    output = _fwd(work_dir / "probe.$F4.xyz")
    result = client.ok("render", {"rop_path": nodes["rop"].path(), "output": output, "wait_s": 300})
    assert "thumbnail" not in result
    note = next(n for n in result.get("notes", []) if n.startswith("No thumbnail"))
    assert ".xyz" in note and ".png" in note and ".exr" in note


@pytest.mark.slow
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
    # Review 16 N7: message, detail.errors and the hint say each thing once.
    lines = [error["message"], *error["detail"].get("errors", [])]
    assert "The attempted operation failed" not in error["message"]
    assert all(b not in a for i, a in enumerate(lines) for b in lines[i + 1 :]), lines
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


@pytest.mark.slow
def test_capture_lop_camera_renders_the_stage(client, work_dir):
    nodes = _lop_scene(work_dir)
    hou.node("/obj").createNode("geo", "unrelated").createNode("box").setDisplayFlag(True)
    result = client.ok("viewport_capture", {"camera": nodes["cam"].path(), "resolution": [160, 90]})
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["rset"].path()  # the displayed LOP
    assert result["camera_used"] == "/cameras/cam1"
    assert result["source_used"] == "flipbook_rop"
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


@pytest.mark.slow
def test_capture_camera_prim_with_lop_path(client, work_dir):
    nodes = _lop_scene(work_dir)
    result = client.ok(
        "viewport_capture",
        {"camera": "/cameras/cam1", "lop_path": nodes["cam"].path(), "resolution": [160, 90]},
    )
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["cam"].path()
    assert result["camera_used"] == "/cameras/cam1"


@pytest.mark.slow
def test_capture_lop_path_frames_the_stage(client, work_dir):
    nodes = _lop_scene(work_dir)
    result = client.ok("viewport_capture", {"lop_path": "/stage", "resolution": [160, 120]})
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["rset"].path()
    assert result["camera_used"] == "temporary"
    assert result["fit_used"] == "all"
    assert _center_lit(result["image"])


@pytest.mark.slow
def test_capture_without_obj_geometry_uses_the_stage(client, work_dir):
    _lop_scene(work_dir)
    result = client.ok("viewport_capture", {"resolution": [160, 120]})
    assert result["scene"] == "stage"
    assert _center_lit(result["image"])


@pytest.mark.slow
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


def _city_scene():
    """Review 16's scene shape: a city of ~75k polygons in an /obj network, imported with
    sopimport, two MaterialX materials, assignmaterial, a distant and a dome light, a
    camera LOP and Karma render settings (displayed). Before N1 was fixed, every headless
    OpenGL capture of this stage crashed the child hython (exit 139)."""
    city = hou.node("/obj").createNode("geo", "city_gen")
    grid = city.createNode("grid")
    grid.parm("rows").set(14)
    grid.parm("cols").set(14)
    grid.parmTuple("size").set((400, 400))
    box = city.createNode("box")
    box.parmTuple("size").set((12, 40, 12))
    box.parm("dodivs").set(1)
    box.parmTuple("divrate").set((8, 8, 8))
    copy = city.createNode("copytopoints::2.0")
    copy.setInput(0, box)
    copy.setInput(1, grid)
    name = city.createNode("attribwrangle", "name_bldgs")
    name.setInput(0, copy)
    name.parm("class").set(1)
    name.parm("snippet").set('s@name = sprintf("bldg_%d", @primnum / 384);')
    out = city.createNode("null", "OUT_CITY")
    out.setInput(0, name)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    city.setDisplayFlag(False)  # /obj displays nothing: the stage is what the scene shows
    stage = hou.node("/stage")
    imp = stage.createNode("sopimport", "city")
    imp.parm("soppath").set(out.path())
    imp.parm("pathprefix").set("/city")
    lib = stage.createNode("materiallibrary", "matlib")
    lib.setInput(0, imp)
    lib.createNode("mtlxstandard_surface", "concrete")
    lib.createNode("mtlxstandard_surface", "asphalt")
    assign = stage.createNode("assignmaterial", "assign")
    assign.setInput(0, lib)
    assign.parm("nummaterials").set(2)
    assign.parm("primpattern1").set("/city/bldg_*")
    assign.parm("matspecpath1").set("/materials/concrete")
    assign.parm("primpattern2").set("/city/bldg_0")
    assign.parm("matspecpath2").set("/materials/asphalt")
    key = stage.createNode("distantlight::2.0", "key")
    key.setInput(0, assign)
    key.parmTuple("r").set((-38, -40, 0))
    fill = stage.createNode("domelight::3.0", "fill")
    fill.setInput(0, key)
    fill.parm("xn__inputsintensity_i0a").set(0.6)
    cam = stage.createNode("camera", "cam_main")
    cam.setInput(0, fill)
    cam.parmTuple("t").set((430, 300, 430))
    cam.parmTuple("r").set((-28, 45, 0))
    rset = stage.createNode("karmarenderproperties", "rset")
    rset.setInput(0, cam)
    rset.setDisplayFlag(True)
    return {"cam": cam, "rset": rset}


@pytest.mark.slow
def test_capture_city_stage_headless(client, work_dir):
    """N1: the review-16 scene shape captures through the OpenGL child (single-threaded)."""
    nodes = _city_scene()
    before = [c.name() for c in hou.node("/stage").children()]
    result = client.ok(
        "viewport_capture", {"lop_path": nodes["rset"].path(), "resolution": [320, 180]}
    )
    assert result["scene"] == "stage"
    assert result["source_used"] == "flipbook_rop"
    assert result["camera_used"] == "temporary"
    assert _decode(result["image"]).convert("L").getextrema()[1] > 80
    assert [c.name() for c in hou.node("/stage").children()] == before


@pytest.mark.slow
def test_capture_falls_back_to_karma_when_the_child_crashes(client, work_dir, monkeypatch):
    """N1 fallback: an OpenGL child that crashes is replaced by a temporary Karma ROP in the
    host; the next stage capture skips the OpenGL child. No node is left behind."""
    from hocuspocus.host.tools import visual

    monkeypatch.setattr(visual, "_CHILD_SCRIPT", "import os\nos._exit(139)\n")
    monkeypatch.setattr(visual, "_stage_crashed", {})
    nodes = _city_scene()
    before = {n: [c.name() for c in hou.node(n).children()] for n in ("/stage", "/out", "/obj")}
    result = client.ok("viewport_capture", {"camera": nodes["cam"].path(), "resolution": [160, 90]})
    assert result["source_used"] == "karma"
    assert result["camera_used"] == "/cameras/cam_main"
    assert result["rendered"] == [160, 90]
    assert (result["width"], result["height"]) == (160, 90)
    assert any("Karma" in n and "crashed" in n for n in result["notes"]), result["notes"]
    lo, hi = _decode(result["image"]).convert("L").getextrema()
    assert hi - lo > 20
    assert {n: [c.name() for c in hou.node(n).children()] for n in before} == before
    framed = client.ok("viewport_capture", {"lop_path": "/stage", "resolution": [160, 90]})
    assert framed["source_used"] == "karma"
    assert framed["camera_used"] == "temporary"
    assert any("earlier" in n for n in framed["notes"]), framed["notes"]
    lo, hi = _decode(framed["image"]).convert("L").getextrema()
    assert hi - lo > 20
    assert {n: [c.name() for c in hou.node(n).children()] for n in before} == before


@pytest.mark.slow
def test_stage_capture_falls_back_to_the_opengl_rop(client, work_dir, crash_capture_child):
    """1.4: a stage whose Flipbook ROP child crashes is captured by the OpenGL ROP (its
    child single-threaded); with source auto the next stage capture skips the Flipbook ROP
    and says so. No deprecation note for the temporary OpenGL ROP."""
    crash_capture_child("flipbook")
    nodes = _lop_scene(work_dir)
    before = [c.name() for c in hou.node("/stage").children()]
    result = client.ok("viewport_capture", {"camera": nodes["cam"].path(), "resolution": [160, 90]})
    assert result["scene"] == "stage" and result["source_used"] == "opengl_rop"
    notes = " ".join(result["notes"])
    assert "Flipbook ROP crashed its render process" in notes, notes
    assert "deprecat" not in notes.lower()
    assert _center_lit(result["image"])
    again = client.ok("viewport_capture", {"lop_path": "/stage", "resolution": [160, 90]})
    assert again["source_used"] == "opengl_rop"
    assert any("skipped" in n and "earlier" in n for n in again["notes"]), again["notes"]
    assert [c.name() for c in hou.node("/stage").children()] == before


@pytest.mark.slow
def test_capture_crash_error_is_short(client, work_dir, monkeypatch):
    """N1: when the fallback cannot run either (an /obj capture whose child crashes and
    Karma fails), the error stays short: no 4 KB crash dump."""
    from hocuspocus.host.tools import visual

    dump = "-- TRACEBACK BEGIN --\nCURRENT THREAD 1\n" + "OTHER THREAD 2\n+0x1 [Idle] x.dll\n" * 400
    monkeypatch.setattr(
        visual,
        "_CHILD_SCRIPT",
        f"import os, sys\nsys.stdout.write({dump!r})\nsys.stdout.flush()\nos._exit(139)\n",
    )

    def no_karma(*args, **kwargs):
        raise visual.ToolError("cook_failed", "karma failed too")

    monkeypatch.setattr(visual, "capture_with_karma", no_karma)
    hou.node("/obj").createNode("geo", "g").createNode("box").setDisplayFlag(True)
    error = client.error("viewport_capture", {"resolution": [64, 64]})
    assert error["code"] == "cook_failed"
    assert "crashed" in error["message"] and "karma failed too" in error["message"]
    log = error["detail"]["opengl_log"]
    assert "CURRENT THREAD" in log and "OTHER THREAD" not in log
    assert len(json.dumps(error)) < 1200


# -- LOP parms by USD attribute name (papercut 7) ---------------------------------------


def test_usd_attribute_names_resolve_to_lop_parms(client, work_dir):
    nodes = _lop_scene(work_dir)
    dome = nodes["dome"].path()
    result = client.ok("parm_set", {"items": [{"path": f"{dome}/inputs:intensity", "value": 0.5}]})
    item = result["results"][0]
    assert item["path"] == f"{dome}/xn__inputsintensity_i0a"
    assert nodes["dome"].parm("xn__inputsintensity_i0a").eval() == 0.5
    got = client.ok("parm_get", {"paths": [f"{dome}/inputs:color"]})["parms"][0]
    assert got["name"] == "xn__inputscolor_zta"
    assert got["value"] == [1, 1, 1]
    created = client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": "/stage",
                    "type": "distantlight::2.0",
                    "name": "key",
                    "inputs": [{"index": 0, "from": dome}],
                    "parms": {"inputs:intensity": 2.5, "inputs:color": [1, 0.9, 0.8]},
                }
            ],
        },
    )
    assert created["created"]
    key = hou.node("/stage/key")
    assert key.parm("xn__inputsintensity_i0a").eval() == 2.5
    assert [round(v, 3) for v in key.parmTuple("xn__inputscolor_zta").eval()] == [1, 0.9, 0.8]
    unknown = client.error("parm_set", {"items": [{"path": f"{dome}/inputs:nope", "value": 1}]})
    assert unknown["code"] == "parm_not_found"


# -- computed tuple components (papercut 4) ---------------------------------------------


def test_locked_component_holding_the_value_is_skipped(client):
    cam = hou.node("/stage").createNode("camera", "cam1")
    rset = hou.node("/stage").createNode("karmarendersettings", "rset")
    rset.setInput(0, cam)
    rset.parm("camera").set("/cameras/cam1")
    # res_mode autoheight: resolutiony is locked and computed from resolutionx and the
    # camera, so [640, 360] sets resolutionx and finds resolutiony already at 360.
    result = client.ok(
        "parm_set", {"items": [{"path": f"{rset.path()}/resolution", "value": [640, 360]}]}
    )
    assert result["results"][0]["value"] == [640, 360]
    assert (rset.parm("resolutionx").eval(), rset.parm("resolutiony").eval()) == (640, 360)


def test_locked_component_error_names_it(client):
    cam = hou.node("/stage").createNode("camera", "cam1")
    error = client.error(
        "node_create",
        {
            "items": [
                {
                    "parent": "/stage",
                    "type": "karmarendersettings",
                    "name": "rset",
                    "inputs": [{"index": 0, "from": cam.path()}],
                    "parms": {"resolution": [640, 400]},
                }
            ],
        },
    )
    assert error["code"] == "locked"
    assert "resolutiony" in error["message"]
    assert "expression" in error["message"]
    assert not error["hint"].startswith("Unlock it in Houdini")
    assert "resolutionx" in error["hint"]


# -- viewport_capture of a ROP LOP (review 23 P2-10) ------------------------------------


@pytest.mark.slow
def test_capture_a_rop_lop_captures_the_stage_it_renders(client, work_dir):
    """A ROP inside a LOP network has no output stage; viewport_capture now captures the
    LOP it renders (its input, or loppath) and says so, instead of refusing."""
    nodes = _lop_scene(work_dir)
    result = client.ok(
        "viewport_capture",
        {"lop_path": nodes["rop"].path(), "camera": "/cameras/cam1", "resolution": [160, 90]},
    )
    assert result["scene"] == "stage"
    assert result["lop_path"] == nodes["rset"].path()
    note = f"Captured {nodes['rset'].path()}, the LOP {nodes['rop'].path()} renders"
    assert any(n.startswith(note) for n in result["notes"]), result["notes"]
    assert _center_lit(result["image"])


def test_capture_a_rop_lop_without_input_is_refused(client):
    rop = hou.node("/stage").createNode("usd_rop", "lonely")
    error = client.error("viewport_capture", {"lop_path": rop.path()})
    assert error["code"] == "invalid_argument"
    assert "no output stage" in error["message"]


# -- usd_stage on a ROP LOP (papercut 10) -----------------------------------------------


def test_usd_stage_on_a_render_rop_reads_its_input(client, work_dir):
    """Review 23 papercut 10: the tool knew the right node and still refused (1.4)."""
    nodes = _lop_scene(work_dir)
    result = client.ok("usd_stage", {"lop_path": nodes["rop"].path()})
    assert result["lop_path"] == nodes["rset"].path()
    assert nodes["rop"].path() in result["note"] and result["prims"]
    lonely = hou.node("/stage").createNode("usd_rop", "lonely_stage")
    error = client.error("usd_stage", {"lop_path": lonely.path()})
    assert error["code"] == "invalid_argument" and "no output stage" in error["message"]


# -- single-file USD exports (review 23 P0-1) -------------------------------------------


def _usd_export(work_dir: Path, frames=(1, 12)):
    """An animated box -> sopimport (its save path under work_dir/usd) -> usd_rop writing
    work_dir/usd/anim.usd over ``frames`` (trange normal). Returns the ROP."""
    geo = hou.node("/obj").createNode("geo", "anim")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    box.setDisplayFlag(True)
    imp = hou.node("/stage").createNode("sopimport", "anim_import")
    imp.parm("soppath").set(box.path())
    imp.parm("savepath").set(_fwd(work_dir / "usd" / "$OS.usd"))
    rop = hou.node("/stage").createNode("usd_rop", "export_usd")
    rop.setInput(0, imp)
    rop.parm("lopoutput").set(_fwd(work_dir / "usd" / "anim.usd"))
    rop.parm("trange").set(1)
    for name, value in zip(("f1", "f2"), frames, strict=True):
        rop.parm(name).deleteAllKeyframes()
        rop.parm(name).set(value)
    return rop


def _samples(path: Path) -> list[float]:
    from pxr import Sdf

    return list(Sdf.Layer.OpenAsAnonymous(_fwd(path)).ListAllTimeSamples())


def test_render_usd_rop_writes_every_frame_in_one_call(client, work_dir):
    """Review 23 P0-1: frame by frame, every render() call overwrote the one layer and
    left frame 12's sample only. One render() call over the range writes all 12."""
    rop = _usd_export(work_dir)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 12]})
    assert result["state"] == "done", result
    assert result["frames"] == [1, 12, 1]
    # Review 23 P1-3: one file is one output, and the layers that hold the data are listed.
    assert result["outputs"] == [_fwd(work_dir / "usd" / "anim.usd")]
    assert "outputs_sample" not in result and "outputs_summary" not in result
    layers = {Path(row["path"]).name: row for row in result["layers"]}
    assert set(layers) == {"anim.usd", "anim_import.usd"}, result["layers"]
    assert layers["anim_import.usd"]["time_samples"] == 12
    assert layers["anim_import.usd"]["time_codes"] == [1, 12]
    assert layers["anim.usd"]["time_samples"] == 0 and "time_codes" not in layers["anim.usd"]
    assert all(row["bytes"] == Path(row["path"]).stat().st_size for row in result["layers"])
    samples = _samples(work_dir / "usd" / "anim_import.usd")
    assert samples == [float(f) for f in range(1, 13)], samples
    status = client.ok("job", {"action": "status", "job_id": result["job_id"]})
    assert status["current"] == status["total"] == 12, status


def test_render_fails_when_a_usd_layer_lost_frames(client, work_dir):
    """The read-back that guards P0-1: a layer written frame by frame holds one sample for
    12 frames, which is cook_failed naming the layer."""
    from hocuspocus.host.tools import visual

    rop = _usd_export(work_dir)
    for frame in range(1, 13):
        rop.render(frame_range=(frame, frame), verbose=False)
    assert len(_samples(work_dir / "usd" / "anim_import.usd")) == 1
    with pytest.raises(visual.ToolError) as caught:
        visual.check_single_file(
            rop.path(), _fwd(work_dir / "usd" / "anim.usd"), [float(f) for f in range(1, 13)]
        )
    assert caught.value.code == "cook_failed"
    assert "1 time sample" in caught.value.message and "12 frames" in caught.value.message


def test_render_usdexport_sop_writes_every_frame(client, work_dir):
    geo = hou.node("/obj").createNode("geo", "anim")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    export = geo.createNode("usdexport", "usd_out")
    export.setInput(0, box)
    export.parm("lopoutput").set(_fwd(work_dir / "sop.usd"))
    result = client.ok("render", {"rop_path": export.path(), "frames": [1, 6]})
    assert result["state"] == "done", result
    assert result["outputs"] == [_fwd(work_dir / "sop.usd")]
    assert [row["time_samples"] for row in result["layers"]] == [6], result["layers"]
    assert len(_samples(work_dir / "sop.usd")) == 6


def test_render_without_frames_uses_the_rops_frame_range(client, work_dir):
    """Review 23 P1-2: render without frames used the current frame even on a ROP set to
    a frame range. It now renders the ROP's own range, and a ROP set to Render Current
    Frame renders that frame; a note says which."""
    rop = _usd_export(work_dir, frames=(1, 6))
    result = client.ok("render", {"rop_path": rop.path()})
    assert result["frames"] == [1, 6, 1], result
    assert any("own frame range 1-6" in n for n in result["notes"]), result
    assert len(_samples(work_dir / "usd" / "anim_import.usd")) == 6
    rop.parm("trange").set(0)
    rop.parm("lopoutput").set(_fwd(work_dir / "usd" / "still.usd"))
    hou.setFrame(3)
    current = client.ok("render", {"rop_path": rop.path()})
    assert current["frames"] == [3, 3, 1], current
    assert any("current frame (3) only" in n for n in current["notes"]), current
    # One frame of a USD export lists its layers too (no time samples to check).
    assert current["outputs"] == [_fwd(work_dir / "usd" / "still.usd")]
    assert Path(current["layers"][0]["path"]).name == "still.usd", current["layers"]
    given = client.ok("render", {"rop_path": rop.path(), "frames": [2, 4]})
    assert not any("frame range" in n or "current frame" in n for n in given.get("notes", []))


# -- node_type_info filters (papercut 8) ------------------------------------------------


def test_node_type_info_filters_drop_inputs_and_folders(client):
    full = client.ok("node_type_info", {"type": "Vop/mtlxstandard_surface"})
    assert len(full["inputs"]) > 20
    narrowed = client.ok(
        "node_type_info", {"type": "Vop/mtlxstandard_surface", "parms": "base*|specular"}
    )
    assert "inputs" not in narrowed
    assert narrowed["inputs_count"] == len(full["inputs"])
    assert len(json.dumps(narrowed)) < len(json.dumps(full)) / 2
    detailed = client.ok(
        "node_type_info", {"type": "Lop/karmarendersettings", "parms": "res*", "detail": "full"}
    )
    assert "folders" not in detailed and "inputs" not in detailed
    assert detailed["parms"]


# -- hints (review 15 papercut 10) ------------------------------------------------------


def test_node_create_camera_in_obj_suggests_cam(client):
    error = client.error("node_create", {"items": [{"parent": "/obj", "type": "camera"}]})
    assert error["code"] == "node_type_not_found"
    assert "cam" in error["candidates"]
    assert "as cam" in error["hint"]
    assert "geo object" not in error["hint"]
