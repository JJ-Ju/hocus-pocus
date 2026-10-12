"""viewport_capture and render against real Houdini (headless hython).

Headless OpenGL renders go through a child hython (see hocuspocus.host.tools.visual), so
these tests also prove the host survives repeated OpenGL renders, which segfault
in-process in 22.0.466.
"""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")
Image = pytest.importorskip("PIL.Image")

from hocuspocus.host.tools.visual import CAPTURE_CAM, CAPTURE_ROP, INTERNAL_KEY  # noqa: E402


def _fwd(path) -> str:
    return str(path).replace("\\", "/")


def _toy_scene():
    geo = hou.node("/obj").createNode("geo", "toy")
    toy = geo.createNode("testgeometry_rubbertoy")
    toy.setDisplayFlag(True)
    return geo


def _decode(image: dict):
    assert image["mime_type"] == "image/png"
    data = base64.b64decode(image["png_base64"])
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(data))


def _not_blank(img) -> bool:
    lo, hi = img.convert("L").getextrema()
    return hi - lo > 40


def _wait_job(client, job_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = client.ok("job", {"action": "status", "job_id": job_id})
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running after {timeout_s}s")


# -- viewport_capture -----------------------------------------------------------------


def test_capture_headless_opengl_twice(client):
    _toy_scene()
    timings = []
    results = []
    for _ in range(2):
        started = time.perf_counter()
        envelope = client.call("viewport_capture", {})
        timings.append(time.perf_counter() - started)
        assert envelope["ok"], envelope
        results.append(envelope["result"])
    print(f"\nviewport_capture headless: first {timings[0]:.2f}s, second {timings[1]:.2f}s")
    for result in results:
        assert result["source_used"] == "opengl_rop"
        assert result["camera_used"] == CAPTURE_CAM
        assert result["fit_used"] == "all"
        assert (result["width"], result["height"]) == (1024, 768)
        assert result["rendered"] == [1024, 768]
        assert Path(result["path"]).is_file()
        assert Path(result["path"]).parent.name == "captures"
        img = _decode(result["image"])
        assert img.size == (1024, 768)
        assert _not_blank(img)
    assert results[0]["path"] != results[1]["path"]
    rop = hou.node(CAPTURE_ROP)
    cam = hou.node(CAPTURE_CAM)
    assert rop.type().name() == "opengl"
    assert cam.type().name() == "cam"
    assert rop.userData(INTERNAL_KEY) == "1"
    assert cam.userData(INTERNAL_KEY) == "1"


def test_capture_frames_the_geometry(client):
    geo = _toy_scene()
    geo.parmTuple("t").set((40, 5, -30))
    result = client.ok("viewport_capture", {"resolution": [320, 240]})
    img = _decode(result["image"]).convert("RGB")
    # The toy fills the frame around the centre, wherever it is in world space.
    centre = img.getpixel((160, 120))
    assert centre != (64, 64, 64), centre
    assert _not_blank(img)


def test_capture_downscales_and_writes_extra_path(client, work_dir):
    _toy_scene()
    extra = work_dir / "shots" / "wide.png"
    result = client.ok(
        "viewport_capture", {"resolution": [1600, 900], "path": _fwd(extra), "frame": 3}
    )
    assert result["rendered"] == [1600, 900]
    assert (result["width"], result["height"]) == (1024, 576)
    assert result["frame"] == 3
    assert result["also_written"] == _fwd(extra)
    with Image.open(extra) as written:
        assert written.size == (1600, 900)


def test_capture_explicit_camera(client):
    _toy_scene()
    cam = hou.node("/obj").createNode("cam", "shotcam")
    cam.parmTuple("t").set((0, 0.5, 5))
    result = client.ok("viewport_capture", {"camera": cam.path(), "resolution": [200, 100]})
    assert result["camera_used"] == "/obj/shotcam"
    assert result["fit_used"] == "none"
    assert (result["width"], result["height"]) == (200, 100)


def test_capture_fit_selected_and_none(client):
    geo = _toy_scene()
    other = hou.node("/obj").createNode("geo", "far")
    other.createNode("box").setDisplayFlag(True)
    other.parmTuple("t").set((100, 0, 0))
    geo.setSelected(True, clear_all_selected=True)
    result = client.ok("viewport_capture", {"fit": "selected", "resolution": [160, 120]})
    assert result["fit_used"] == "selected"
    hou.clearAllSelected()
    result = client.ok("viewport_capture", {"fit": "selected", "resolution": [160, 120]})
    assert result["fit_used"] == "all"  # nothing selected: falls back to everything
    before = hou.node(CAPTURE_CAM).worldTransform()
    result = client.ok("viewport_capture", {"fit": "none", "resolution": [160, 120]})
    assert result["fit_used"] == "none"
    assert hou.node(CAPTURE_CAM).worldTransform().isAlmostEqual(before)


def test_capture_viewer_headless_is_ui_required(client):
    error = client.error("viewport_capture", {"source": "viewer"})
    assert error["code"] == "ui_required"
    assert "opengl_rop" in error["hint"]


def test_capture_bad_camera(client):
    _toy_scene()
    error = client.error("viewport_capture", {"camera": "/obj/nocam"})
    assert error["code"] == "node_not_found"
    error = client.error("viewport_capture", {"camera": "/obj/toy"})
    assert error["code"] == "invalid_argument"
    assert "not a camera" in error["message"]


def test_capture_bad_arguments(client):
    assert client.error("viewport_capture", {"resolution": [10, 10]})["code"] == "invalid_argument"
    assert client.error("viewport_capture", {"fit": "most"})["code"] == "invalid_argument"


def test_capture_path_outside_approved_roots(client, work_dir):
    client.host.config.approved_roots = [str(work_dir / "allowed")]
    error = client.error("viewport_capture", {"path": _fwd(work_dir / "elsewhere" / "x.png")})
    assert error["code"] == "path_not_allowed"


# -- render ---------------------------------------------------------------------------


def _opengl_rop(work_dir: Path, name: str = "gl1"):
    cam = hou.node("/obj").createNode("cam", "rendercam")
    cam.parmTuple("t").set((0, 0.5, 5))
    cam.parm("resx").set(320)
    cam.parm("resy").set(240)
    rop = hou.node("/out").createNode("opengl", name)
    rop.parm("camera").set(cam.path())
    rop.parm("picture").set(_fwd(work_dir / "gl.$F4.png"))
    return rop


def test_render_opengl_frames_with_thumbnail(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)
    started = time.perf_counter()
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 3]})
    print(f"\nrender opengl 3 frames: {time.perf_counter() - started:.2f}s")
    assert result["outputs"] == [_fwd(work_dir / f"gl.000{i}.png") for i in (1, 2, 3)]
    assert result["frames"] == [1.0, 3.0, 1.0]
    thumb = result["thumbnail"]
    assert thumb["path"] == result["outputs"][-1]
    img = _decode(thumb["image"])
    assert max(img.size) <= 512 and img.size == (320, 240)
    assert result["job_id"]


def test_render_as_job_then_result(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)
    started = client.ok("render", {"rop_path": rop.path(), "wait_s": 0, "thumbnail": False})
    assert started["state"] == "running"
    assert started["job_id"]
    status = _wait_job(client, started["job_id"])
    assert status["state"] == "done", status
    final = client.ok("job", {"action": "result", "job_id": started["job_id"]})
    assert final["result"]["outputs"] == [_fwd(work_dir / f"gl.{int(hou.frame()):04d}.png")]
    assert "thumbnail" not in final["result"]


def test_render_output_override_in_process(client, work_dir):
    geo = _toy_scene()
    rop = hou.node("/out").createNode("geometry", "bgeo")
    rop.parm("soppath").set(geo.displayNode().path())
    rop.parm("sopoutput").set("$HIP/geo/original.$F4.bgeo.sc")
    out = _fwd(work_dir / "cache.$F4.bgeo.sc")
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 4, 3], "output": out})
    assert result["outputs"] == [
        _fwd(work_dir / "cache.0001.bgeo.sc"),
        _fwd(work_dir / "cache.0004.bgeo.sc"),
    ]
    assert "thumbnail" not in result  # not an image
    assert rop.parm("sopoutput").unexpandedString() == "$HIP/geo/original.$F4.bgeo.sc"


def test_render_opengl_output_override(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)
    out = _fwd(work_dir / "override.$F.png")
    result = client.ok("render", {"rop_path": rop.path(), "output": out, "frames": [2, 2]})
    assert result["outputs"] == [_fwd(work_dir / "override.2.png")]
    assert rop.parm("picture").unexpandedString() == _fwd(work_dir / "gl.$F4.png")


def test_render_errors(client, work_dir):
    error = client.error("render", {"rop_path": "/out/nope"})
    assert error["code"] == "node_not_found"
    geo = _toy_scene()
    error = client.error("render", {"rop_path": geo.path()})
    assert error["code"] == "invalid_argument"
    rop = hou.node("/out").createNode("opengl", "toscreen")
    rop.parm("picture").set("ip")
    error = client.error("render", {"rop_path": rop.path()})
    assert error["code"] == "invalid_value"
    assert "output" in error["hint"]
    error = client.error("render", {"rop_path": rop.path(), "frames": [5, 1]})
    assert error["code"] == "invalid_argument"


def test_render_karma_starts_as_job_and_cancels(client, work_dir):
    _toy_scene()
    cam = hou.node("/obj").createNode("cam", "kcam")
    cam.parmTuple("t").set((0, 0.5, 5))
    cam.parm("resx").set(64)
    cam.parm("resy").set(48)
    rop = hou.node("/out").createNode("karma", "karma1")
    rop.parm("camera").set(cam.path())
    rop.parm("picture").set(_fwd(work_dir / "karma.$F4.exr"))
    rop.parm("samplesperpixel").set(1)
    started = client.ok("render", {"rop_path": rop.path(), "wait_s": 0, "frames": [1, 50]})
    assert started["state"] == "running"
    assert started["tool"] == "render"
    cancelled = client.ok("job", {"action": "cancel", "job_id": started["job_id"]})
    assert cancelled["job_id"] == started["job_id"]
    final = _wait_job(client, started["job_id"])
    assert final["state"] == "cancelled", final
    rendered = sorted(os.listdir(work_dir)) if work_dir.exists() else []
    assert len([n for n in rendered if n.startswith("karma.")]) < 50
