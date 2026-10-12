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

from hocuspocus.host.tools.visual import (  # noqa: E402
    INTERNAL_KEY,
    TEMPORARY_CAMERA,
    temporary_capture_nodes,
)


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
        assert result["camera_used"] == TEMPORARY_CAMERA
        assert result["fit_used"] == "all"
        assert (result["width"], result["height"]) == (1024, 768)
        assert result["rendered"] == [1024, 768]
        assert Path(result["path"]).is_file()
        assert Path(result["path"]).parent.name == "captures"
        img = _decode(result["image"])
        assert img.size == (1024, 768)
        assert _not_blank(img)
    assert results[0]["path"] != results[1]["path"]


def _all_nodes() -> list[str]:
    # Locked HDA contents load lazily on first cook, so they are not counted.
    return sorted(n.path() for n in hou.node("/").allSubChildren(recurse_in_locked_nodes=False))


def test_capture_leaves_the_scene_untouched(client, work_dir):
    """Review 07 papercut 2: a look is read-only. Headless, the camera and ROP exist only
    in the child hython; the live scene gains no nodes, no undo entry and no dirty flag."""
    _toy_scene()
    cam = hou.node("/obj").createNode("cam", "shotcam")
    cam.parmTuple("t").set((0, 0.5, 5))
    hip = work_dir / "look.hip"
    client.ok("hip_save", {"path": _fwd(hip)})
    nodes = _all_nodes()
    history = client.ok("undo", {"action": "history"})
    assert client.host.scene.dirty is False
    client.ok("viewport_capture", {"resolution": [160, 120]})
    client.ok("viewport_capture", {"camera": cam.path(), "resolution": [160, 120]})
    after = _all_nodes()
    assert after == nodes, (set(after) - set(nodes), set(nodes) - set(after))
    assert client.ok("undo", {"action": "history"}) == history
    assert client.host.scene.dirty is False
    assert client.ok("hip_new", {})["saved_first"] is False  # nothing unsaved to refuse
    # The user camera was used as-is.
    assert hou.node("/obj/shotcam") is None  # hip_new cleared the scene
    hou.hipFile.load(_fwd(hip), suppress_save_prompt=True)
    assert _all_nodes() == nodes
    assert tuple(hou.node("/obj/shotcam").parmTuple("t").eval()) == (0, 0.5, 5)


def test_temporary_capture_nodes_are_removed_outside_undo(client):
    """The in-process (GUI) path: nodes exist only during the render, and the selection
    is restored. Rendering in-process is not exercised here (a second OpenGL render in
    one hython segfaults); the context manager is."""
    from hocuspocus.host.tools import events

    geo = _toy_scene()
    geo.setSelected(True, clear_all_selected=True)
    nodes = _all_nodes()
    undo_before = hou.undos.undoLabels()
    client.ok("events", {})  # installs the hooks
    since = events.LOG.last_seq
    spec = {
        "camera": None,
        "camera_xform": list(hou.hmath.buildTranslate(0, 0, 5).asTuple()),
        "camera_parms": {"resx": 64, "resy": 48},
        "rop_parms": {"res1": 64, "res2": 48},
    }
    with temporary_capture_nodes(spec) as rop:
        assert rop.type().name() == "opengl"
        cam = hou.node(rop.parm("camera").eval())
        assert cam.type().name() == "cam"
        assert cam.userData(INTERNAL_KEY) == "1"
        assert cam.worldTransform().extractTranslates()[2] == pytest.approx(5)
        assert {rop.path(), cam.path()} <= set(_all_nodes())
    assert _all_nodes() == nodes
    assert hou.undos.undoLabels() == undo_before
    recorded = client.ok("events", {"since": since})["events"]
    assert not [e for e in recorded if e["kind"] in ("ChildCreated", "ChildDeleted")], recorded
    assert [n.path() for n in hou.selectedNodes()] == [geo.path()]


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
    framed = client.ok("viewport_capture", {"fit": "all", "resolution": [160, 120]})
    result = client.ok("viewport_capture", {"fit": "none", "resolution": [160, 120]})
    assert result["fit_used"] == "none"  # reuses the last automatic framing
    with Image.open(framed["path"]) as a, Image.open(result["path"]) as b:
        assert a.convert("L").tobytes() == b.convert("L").tobytes()


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


# -- review 10 fixes ------------------------------------------------------------------


def test_render_checks_every_expected_output_against_approved_roots(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)  # picture under work_dir, no output override
    client.host.config.approved_roots = [_fwd(work_dir / "allowed")]
    error = client.error("render", {"rop_path": rop.path()})
    assert error["code"] == "path_not_allowed"
    assert not list(work_dir.glob("gl.*.png"))


def test_render_result_always_has_state(client, work_dir):
    geo = _toy_scene()
    rop = hou.node("/out").createNode("geometry", "bgeo")
    rop.parm("soppath").set(geo.displayNode().path())
    rop.parm("sopoutput").set(_fwd(work_dir / "s.$F4.bgeo.sc"))
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    assert result["state"] == "done"
    assert result["job_id"]


def test_render_isolated_override_replaces_keyed_output(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)
    original = _fwd(work_dir / "keyed.$F4.png")
    rop.parm("picture").setExpression(f"'{original}'", hou.exprLanguage.Python)
    out = _fwd(work_dir / "over.$F4.png")
    result = client.ok("render", {"rop_path": rop.path(), "output": out, "frames": [1, 1]})
    assert result["outputs"] == [_fwd(work_dir / "over.0001.png")]
    assert not list(work_dir.glob("keyed.*"))
    assert rop.parm("picture").expression() == f"'{original}'"


def test_capture_path_must_be_png(client, work_dir):
    error = client.error("viewport_capture", {"path": _fwd(work_dir / "x.jpg")})
    assert error["code"] == "invalid_argument"
    assert ".png" in error["message"]


def test_captures_dir_is_pruned_to_newest_50(client):
    from hocuspocus.host.tools.visual import _captures

    captures = _captures(client.host.ctx)
    old = []
    for i in range(60):
        path = captures / f"capture_old_{i:03d}.png"
        path.write_bytes(b"x")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
        old.append(path)
    _toy_scene()
    result = client.ok("viewport_capture", {"resolution": [64, 48]})
    remaining = sorted(captures.iterdir())
    assert len(remaining) == 50
    assert Path(result["path"]) in remaining
    assert not old[0].exists() and old[-1].exists()


def _centroid_x(image: dict) -> float:
    img = _decode(image).convert("L")
    width, height = img.size
    bg = img.getpixel((0, 0))
    xs = [x for y in range(height) for x in range(width) if abs(img.getpixel((x, y)) - bg) > 20]
    assert xs, "nothing rendered"
    return sum(xs) / len(xs)


def _sliding_box(name: str = "slide"):
    geo = hou.node("/obj").createNode("geo", name)
    geo.createNode("box").setDisplayFlag(True)
    cam = hou.node("/obj").createNode("cam", "fixedcam")
    cam.parmTuple("t").set((0, 0, 20))
    return geo, cam


@pytest.mark.parametrize("driver", ["keys_at_30fps", "hscript_global", "hou_session"])
def test_headless_capture_matches_the_live_scene(client, driver):
    """The child hython must evaluate the scene as the live session does: keys at the
    scene's fps (not retimed by setFps), global hscript variables and hou.session."""
    geo, cam = _sliding_box()
    hou.setFps(30, False, False, True)
    hou.playbar.setFrameRange(1, 60)
    frame = 46
    tx = geo.parm("tx")
    if driver == "keys_at_30fps":
        for f, value in ((1, -6.0), (61, 6.0)):
            key = hou.Keyframe()
            key.setFrame(f)
            key.setValue(value)
            key.setExpression("linear()")
            tx.setKeyframe(key)
    elif driver == "hscript_global":
        hou.hscript("set -g HP_OFFSET = 4.5")
        tx.setExpression("$HP_OFFSET")
    else:
        hou.setSessionModuleSource("HP_OFFSET = -3.5\n")
        tx.setExpression("hou.session.HP_OFFSET", hou.exprLanguage.Python)
    expected = tx.evalAtFrame(frame)
    assert abs(expected) > 1  # the object is visibly off-centre
    try:
        live = client.ok(
            "viewport_capture", {"camera": cam.path(), "frame": frame, "resolution": [160, 120]}
        )
        tx.deleteAllKeyframes()
        tx.set(expected)
        static = client.ok(
            "viewport_capture", {"camera": cam.path(), "frame": frame, "resolution": [160, 120]}
        )
    finally:
        hou.setFps(24, False, False, True)
        hou.hscript("set -u HP_OFFSET")
        hou.setSessionModuleSource("")
    assert _centroid_x(live["image"]) == pytest.approx(_centroid_x(static["image"]), abs=1.0)


def test_headless_capture_does_not_hold_the_main_thread(client):
    import http.client
    import json
    import threading

    _toy_scene()
    box: dict = {}

    def capture() -> None:
        conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=120)
        body = {"tool": "viewport_capture", "args": {"resolution": [160, 120]}}
        conn.request(
            "POST",
            "/hp/v1/call",
            json.dumps(body),
            {"Authorization": f"Bearer {client.token}", "Content-Type": "application/json"},
        )
        box["body"] = json.loads(conn.getresponse().read())
        conn.close()

    thread = threading.Thread(target=capture, daemon=True)
    thread.start()
    deadline = time.monotonic() + 0.7  # let the snapshot step run on the main thread
    while time.monotonic() < deadline:
        client.host.executor.pump_once(0.01)
    assert thread.is_alive()
    assert client.ok("houdini_python", {"code": "2 + 2"})["result"] == 4
    assert thread.is_alive(), "the call above only completed after the capture"
    while thread.is_alive():
        client.host.executor.pump_once(0.01)
    assert box["body"]["ok"] is True, box["body"]


def test_fit_none_does_not_reuse_framing_from_another_scene(client):
    far = hou.node("/obj").createNode("geo", "far")
    far.createNode("box").setDisplayFlag(True)
    far.parmTuple("t").set((100, 0, 0))
    client.ok("viewport_capture", {"fit": "all", "resolution": [64, 48]})
    client.ok("hip_new", {"on_unsaved": "discard"})
    _toy_scene()
    result = client.ok("viewport_capture", {"fit": "none", "resolution": [64, 48]})
    assert result["fit_used"] == "all"  # reframed: the old framing was for another scene
    again = client.ok("viewport_capture", {"fit": "none", "resolution": [64, 48]})
    assert again["fit_used"] == "none"
