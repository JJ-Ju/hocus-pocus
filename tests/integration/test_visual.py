"""look (draft: the Flipbook ROP, its OpenGL ROP fallback) and render against real
Houdini (headless hython). In 1.4 these were viewport_capture's tests.

Headless Flipbook and OpenGL ROP renders go through a child hython (see
hocuspocus.host.tools.visual), so these tests also prove the host survives repeated
viewport renders, which segfault in-process in 22.0.466 (the OpenGL ROP on any second
render, the Flipbook ROP once a ROP that rendered is deleted).
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
    BACKGROUND,
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


# -- look draft (1.4: viewport_capture) -----------------------------------------------


@pytest.mark.slow
def test_capture_headless_twice(client):
    _toy_scene()
    timings = []
    results = []
    for _ in range(2):
        started = time.perf_counter()
        envelope = client.call("look", {})
        timings.append(time.perf_counter() - started)
        assert envelope["ok"], envelope
        results.append(envelope["result"])
    print(f"\nlook headless: first {timings[0]:.2f}s, second {timings[1]:.2f}s")
    for result in results:
        assert result["backend_used"] == "flipbook"
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


@pytest.mark.slow
def test_capture_falls_back_from_the_flipbook_rop_to_the_opengl_rop(client, crash_capture_child):
    """A Flipbook ROP child that crashes hands the frame to the OpenGL ROP, and notes say
    so; still no deprecation note for the temporary OpenGL ROP, and no node left behind."""
    crash_capture_child("flipbook")
    _toy_scene()
    nodes = _all_nodes()
    result = client.ok("look", {"resolution": [160, 120]})
    assert result["backend_used"] == "opengl"
    notes = " ".join(result["notes"])
    assert "Flipbook ROP crashed its render process" in notes, notes
    assert "Rendered with the OpenGL ROP" in notes, notes
    assert "deprecat" not in notes.lower()
    assert _not_blank(_decode(result["image"]))
    assert _all_nodes() == nodes


def _all_nodes() -> list[str]:
    # Locked HDA contents load lazily on first cook, so they are not counted.
    return sorted(n.path() for n in hou.node("/").allSubChildren(recurse_in_locked_nodes=False))


@pytest.mark.slow
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
    client.ok("look", {"resolution": [160, 120]})
    client.ok("look", {"camera": cam.path(), "resolution": [160, 120]})
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
    is restored. Rendering in-process is not exercised here (headless, a Flipbook render
    after a rendered Flipbook ROP was deleted segfaults the hython); the context manager
    is."""
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
        assert rop.type().name() == "flipbook"
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


@pytest.mark.slow
def test_capture_frames_the_geometry(client):
    geo = _toy_scene()
    geo.parmTuple("t").set((40, 5, -30))
    result = client.ok("look", {"resolution": [320, 240]})
    img = _decode(result["image"]).convert("RGB")
    # The toy fills the frame around the centre, wherever it is in world space.
    centre = img.getpixel((160, 120))
    assert centre != (64, 64, 64), centre
    assert _not_blank(img)


@pytest.mark.slow
def test_capture_downscales_the_inline_image(client):
    _toy_scene()
    result = client.ok("look", {"resolution": [1600, 900], "frame": 3})
    assert result["rendered"] == [1600, 900]
    assert (result["width"], result["height"]) == (1024, 576)
    assert result["frame"] == 3
    # Review 12: the file on disk has the inline image's opaque grey, not a transparent
    # background that most viewers show as white.
    with Image.open(result["path"]) as written:
        assert written.size == (1600, 900)
        assert written.mode == "RGB", written.mode
        assert written.getpixel((0, 0)) == BACKGROUND
        assert _not_blank(written)
        inline = _decode(result["image"]).convert("RGB")
        assert inline.getpixel((0, 0)) == written.getpixel((0, 0))


@pytest.mark.slow
def test_capture_explicit_camera(client):
    _toy_scene()
    cam = hou.node("/obj").createNode("cam", "shotcam")
    cam.parmTuple("t").set((0, 0.5, 5))
    result = client.ok("look", {"camera": cam.path(), "resolution": [200, 100]})
    assert result["camera_used"] == "/obj/shotcam"
    assert result["fit_used"] == "none"
    assert (result["width"], result["height"]) == (200, 100)


@pytest.mark.slow
def test_capture_fit_selected_and_none(client):
    geo = _toy_scene()
    other = hou.node("/obj").createNode("geo", "far")
    other.createNode("box").setDisplayFlag(True)
    other.parmTuple("t").set((100, 0, 0))
    geo.setSelected(True, clear_all_selected=True)
    result = client.ok("look", {"fit": "selected", "resolution": [160, 120]})
    assert result["fit_used"] == "selected"
    hou.clearAllSelected()
    result = client.ok("look", {"fit": "selected", "resolution": [160, 120]})
    assert result["fit_used"] == "all"  # nothing selected: falls back to everything
    framed = client.ok("look", {"fit": "all", "resolution": [160, 120]})
    result = client.ok("look", {"fit": "none", "resolution": [160, 120]})
    assert result["fit_used"] == "none"  # reuses the last automatic framing
    with Image.open(framed["path"]) as a, Image.open(result["path"]) as b:
        assert a.convert("L").tobytes() == b.convert("L").tobytes()


def test_capture_bad_camera(client):
    _toy_scene()
    error = client.error("look", {"camera": "/obj/nocam"})
    assert error["code"] == "node_not_found"
    error = client.error("look", {"camera": "/obj/toy"})
    assert error["code"] == "invalid_argument"
    assert "not a camera" in error["message"]
    assert not error.get("candidates")  # the scene has no camera yet
    assert "OBJ camera such as" not in error["hint"]


def test_capture_light_is_not_a_camera_and_errors_list_cameras(client):
    _toy_scene()
    hou.node("/obj").createNode("cam", "shotcam")
    sun = hou.node("/obj").createNode("hlight", "sun")
    error = client.error("look", {"camera": sun.path()})
    assert error["code"] == "invalid_argument"
    assert "is a light" in error["message"]
    assert error["candidates"] == ["/obj/shotcam"]
    error = client.error("look", {"camera": "/obj/toy"})
    assert error["candidates"] == ["/obj/shotcam"]
    assert "/obj/shotcam" in error["hint"]


class _FakeView:
    """A GeometryViewport stand-in: ``view`` is what the viewport shows."""

    def __init__(self, camera=None):
        self._camera = camera
        self.view = f"through {camera.path()}" if camera is not None else "user view"

    def camera(self):
        return self._camera

    def defaultCamera(self):
        view = self

        class _Default:
            def stash(self):
                return view.view if view._camera is None else "user view"

        return _Default()

    def setCamera(self, cam):
        self._camera = cam
        self.view = f"through {cam.path()}"

    def useDefaultCamera(self):
        self._camera = None  # the free view keeps whatever it showed (Houdini does too)

    def setDefaultCamera(self, stashed):
        self.view = stashed

    def frameAll(self):
        assert self._camera is None, "framing must never move a camera node"
        self.view = "framed all"

    def frameSelected(self):
        assert self._camera is None
        self.view = "framed selected"


class _FakeViewer:
    def __init__(self, viewport, pwd):
        self.viewport, self._pwd, self.seen = viewport, pwd, None

    def curViewport(self):
        return self.viewport

    def pwd(self):
        return self._pwd

    def flipbookSettings(self):
        viewer = self

        class _Settings:
            def stash(self):
                return self

            def output(self, path):
                self.path = path

            def __getattr__(self, name):
                return lambda *a, **k: None

        viewer.settings = _Settings()
        return viewer.settings

    def flipbook(self, viewport, settings, open_dialog=False):
        self.seen = (viewport.view, viewport.camera())
        Image.new("RGB", (32, 24), (90, 90, 90)).save(settings.path)


def test_viewer_capture_restores_the_view(client, work_dir):
    from hocuspocus.host.tools.visual import _capture_viewer, capture_target

    geo = _toy_scene()
    shot = hou.node("/obj").createNode("cam", "shotcam")
    user_cam = hou.node("/obj").createNode("cam", "usercam")
    # camera: the grab looks through it; the user's free view comes back.
    viewport = _FakeView()
    viewer = _FakeViewer(viewport, hou.node("/obj"))
    target = capture_target(shot.path(), None)
    info = _capture_viewer(viewer, target, 1.0, (32, 24), str(work_dir / "a.png"))
    assert viewer.seen == ("through /obj/shotcam", shot)
    assert (viewport.view, viewport.camera()) == ("user view", None)
    assert info["camera_used"] == "/obj/shotcam" and info["context"] == "/obj"
    assert "notes" not in info
    # An explicit fit frames the free view, then the camera the user looked through returns.
    viewport = _FakeView(user_cam)
    viewer = _FakeViewer(viewport, geo)
    target = capture_target(None, None)
    info = _capture_viewer(viewer, target, 1.0, (32, 24), str(work_dir / "b.png"), "all")
    assert viewer.seen == ("framed all", None)
    assert viewport.camera() is user_cam and viewport.view == "through /obj/usercam"
    assert info["fit_used"] == "all"
    assert info["camera_used"] == "viewport"  # the framed free view, not usercam
    assert info["context"] == geo.path()
    assert any(geo.path() in note and "flipbook_rop" in note for note in info["notes"])
    # Without fit the view is captured as it is and left alone.
    viewport = _FakeView()
    viewer = _FakeViewer(viewport, hou.node("/obj"))
    info = _capture_viewer(viewer, target, 1.0, (32, 24), str(work_dir / "c.png"))
    assert viewer.seen == ("user view", None) and info["fit_used"] == "none"


def test_capture_bad_arguments(client):
    assert client.error("look", {"resolution": [10, 10]})["code"] == "invalid_argument"
    assert client.error("look", {"fit": "most"})["code"] == "invalid_argument"


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


@pytest.mark.slow
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


def _flipbook_rop(work_dir: Path, name: str = "fb1"):
    cam = hou.node("/obj").createNode("cam", "fbcam")
    cam.parmTuple("t").set((0, 0.5, 5))
    rop = hou.node("/out").createNode("flipbook", name)
    rop.parm("camera").set(cam.path())
    rop.parm("tres").set(1)
    rop.parm("res1").set(320)
    rop.parm("res2").set(240)
    rop.parm("picture").set(_fwd(work_dir / "fb.$F4.png"))
    return rop


@pytest.mark.slow
def test_render_flipbook_rop_twice_headless(client, work_dir):
    """A user's Flipbook ROP renders in a child hython headless, like the OpenGL ROP: a
    render after a rendered Flipbook ROP was deleted would crash the host otherwise."""
    _toy_scene()
    rop = _flipbook_rop(work_dir)
    first = client.ok("render", {"rop_path": rop.path(), "frames": [1, 2]})
    assert first["outputs"] == [_fwd(work_dir / f"fb.000{i}.png") for i in (1, 2)]
    assert _decode(first["thumbnail"]["image"]).size == (320, 240)
    rop.destroy()
    again = _flipbook_rop(work_dir, "fb2")
    out = _fwd(work_dir / "fb_again.$F4.png")
    second = client.ok("render", {"rop_path": again.path(), "frames": [3, 3], "output": out})
    assert second["outputs"] == [_fwd(work_dir / "fb_again.0003.png")]
    assert again.parm("picture").unexpandedString() == _fwd(work_dir / "fb.$F4.png")


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
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


def _bgeo_rop(work_dir: Path, pattern: str = "s.$F4.bgeo.sc"):
    geo = _toy_scene()
    rop = hou.node("/out").createNode("geometry", "bgeo")
    rop.parm("soppath").set(geo.displayNode().path())
    rop.parm("sopoutput").set(_fwd(work_dir / pattern))
    return rop


def test_render_over_five_outputs_returns_a_summary(client, work_dir):
    """Review 11 B6, review 20 N5: a sequence returns outputs_summary and outputs_sample,
    inline and from job result alike, never every path."""
    rop = _bgeo_rop(work_dir)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 8]})
    assert result["state"] == "done"
    assert "outputs" not in result and "hint" not in result
    summary = result["outputs_summary"]
    assert summary["count"] == 8 and summary["missing_count"] == 0
    assert "first" not in summary and "last" not in summary  # the sample's ends (2.1, D67)
    assert summary["pattern"] == _fwd(work_dir / "s.####.bgeo.sc")
    assert result["outputs_sample"] == [_fwd(work_dir / f"s.{i:04d}.bgeo.sc") for i in (1, 2, 7, 8)]
    assert all(isinstance(f, int) for f in result["frames"]), result["frames"]
    job = client.ok("job", {"action": "result", "job_id": result["job_id"]})["result"]
    assert "outputs" not in job
    assert job["outputs_summary"] == summary
    assert job["outputs_sample"] == result["outputs_sample"]
    few = client.ok("render", {"rop_path": rop.path(), "frames": [1, 5]})
    assert len(few["outputs"]) == 5 and "outputs_summary" not in few
    assert "outputs_sample" not in few


def test_render_waits_job_threshold_by_default(client, work_dir):
    rop = _bgeo_rop(work_dir)
    saved = client.host.config.job_threshold_s
    client.host.config.job_threshold_s = 0
    try:
        started = client.ok("render", {"rop_path": rop.path(), "frames": [1, 2]})
        explicit = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1], "wait_s": 30})
    finally:
        client.host.config.job_threshold_s = saved
    assert started["state"] in ("running", "done")
    if started["state"] == "running":
        assert _wait_job(client, started["job_id"])["state"] == "done"
    assert explicit["state"] == "done"


@pytest.mark.slow
def test_render_notes_no_lights_and_an_empty_thumbnail(client, work_dir):
    """Review 11 B10: an unlit, empty OpenGL render says why it shows nothing (review 20
    N1: on its transparent background that is "empty", not "nearly black")."""
    rop = _opengl_rop(work_dir)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    notes = " ".join(result.get("notes", []))
    assert "no lights" in notes, result
    assert "empty" in notes and "nearly black" not in notes, result
    hou.node("/obj").createNode("hlight", "key")
    _toy_scene()
    lit = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    notes = " ".join(lit.get("notes", []))
    assert "no lights" not in notes and "empty" not in notes, lit
    assert "nearly black" not in notes, lit


@pytest.mark.slow
def test_render_sparse_opengl_frame_is_not_nearly_black(client, work_dir):
    """Review 20 N1: a small subject on the OpenGL ROP's transparent background is mostly
    transparent pixels, which the raw RGBA mean counted as black."""
    hou.node("/obj").createNode("hlight", "key")
    geo = _toy_scene()
    geo.parmTuple("s").set((0.15, 0.15, 0.15))
    rop = _opengl_rop(work_dir)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    from PIL import ImageStat

    with Image.open(result["outputs"][0]) as raw:
        alpha = raw.getchannel("A")
        covered = 1 - alpha.histogram()[0] / (alpha.size[0] * alpha.size[1])
        raw_mean = ImageStat.Stat(raw.convert("RGB").convert("L")).mean[0]
    assert 0 < covered < 0.1 and raw_mean < 8  # the frame that used to trigger the note
    notes = " ".join(result.get("notes", []))
    assert "nearly black" not in notes and "empty" not in notes, result


def test_render_rop_own_output_outside_approved_roots_in_process(client, work_dir):
    """Review 10 §5: the ROP's own output parm is checked, here on an in-process ROP."""
    rop = _bgeo_rop(work_dir)
    client.host.config.approved_roots = [_fwd(work_dir / "allowed")]
    error = client.error("render", {"rop_path": rop.path(), "frames": [1, 2]})
    assert error["code"] == "path_not_allowed"
    assert not list(work_dir.glob("s.*.bgeo.sc"))
    allowed = _fwd(work_dir / "allowed" / "s.$F4.bgeo.sc")
    rop.parm("sopoutput").set(allowed)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1]})
    assert result["outputs"] == [_fwd(work_dir / "allowed" / "s.0001.bgeo.sc")]


@pytest.mark.slow
def test_capture_after_an_outside_fix(client):
    """Review 10 §5: a node fixed outside HocusPocus keeps its old error (BIBLE §5.18);
    the capture's framing refreshes it instead of failing or framing nothing."""
    geo = hou.node("/obj").createNode("geo", "stale")
    box = geo.createNode("box", "box1")
    mountain = geo.createNode("mountain", "mountain1")
    mountain.setInput(0, box)
    mountain.setDisplayFlag(True)
    parm = box.parm("sizex")
    parm.setExpression("$F*(")
    with pytest.raises(hou.OperationFailed):
        mountain.cook()
    parm.deleteAllKeyframes()
    parm.revertToDefaults()
    box.cook()
    assert box.errors()  # the stale error is still there
    result = client.ok("look", {"resolution": [320, 240]})
    assert result["camera_used"] == TEMPORARY_CAMERA
    assert _not_blank(_decode(result["image"]))
    assert not box.errors() and not mountain.errors()


@pytest.mark.slow
def test_captures_dir_is_pruned_to_newest_50(client):
    from hocuspocus.host.tools.visual import _captures

    captures = _captures(client.host.ctx)
    for leftover in captures.iterdir():  # earlier tests' captures are newer than old[]
        leftover.unlink()
    old = []
    for i in range(60):
        path = captures / f"capture_old_{i:03d}.png"
        path.write_bytes(b"x")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
        old.append(path)
    _toy_scene()
    result = client.ok("look", {"resolution": [64, 48]})
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
@pytest.mark.slow
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
        live = client.ok("look", {"camera": cam.path(), "frame": frame, "resolution": [160, 120]})
        tx.deleteAllKeyframes()
        tx.set(expected)
        static = client.ok("look", {"camera": cam.path(), "frame": frame, "resolution": [160, 120]})
    finally:
        hou.setFps(24, False, False, True)
        hou.hscript("set -u HP_OFFSET")
        hou.setSessionModuleSource("")
    assert _centroid_x(live["image"]) == pytest.approx(_centroid_x(static["image"]), abs=1.0)


@pytest.mark.slow
def test_headless_capture_does_not_hold_the_main_thread(client):
    import http.client
    import json
    import threading

    from hocuspocus.host.tools import visual

    visual.close_warm_capture()  # a kept child renders in 0.3 s: start a fresh one (3 s)
    _toy_scene()
    box: dict = {}

    def capture() -> None:
        conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=120)
        body = {"tool": "look", "args": {"resolution": [160, 120]}}
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


@pytest.mark.slow
def test_fit_none_does_not_reuse_framing_from_another_scene(client):
    far = hou.node("/obj").createNode("geo", "far")
    far.createNode("box").setDisplayFlag(True)
    far.parmTuple("t").set((100, 0, 0))
    client.ok("look", {"fit": "all", "resolution": [64, 48]})
    client.ok("hip_new", {"on_unsaved": "discard"})
    _toy_scene()
    result = client.ok("look", {"fit": "none", "resolution": [64, 48]})
    assert result["fit_used"] == "all"  # reframed: the old framing was for another scene
    again = client.ok("look", {"fit": "none", "resolution": [64, 48]})
    assert again["fit_used"] == "none"


# -- writer SOPs: File Cache and ROP SOPs (review 17 P0-2, P1-3, P1-6) -------------------


def _file_cache(work_dir: Path, frames=(1, 3), pattern: str = "fc.$F4.bgeo.sc"):
    geo = hou.node("/obj").createNode("geo", "fx")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    cache = geo.createNode("filecache::2.0", "cache")
    cache.setInput(0, box)
    cache.parm("filemethod").set(1)  # explicit file
    cache.parm("file").set(_fwd(work_dir / pattern))
    for parm, value in zip(("f1", "f2"), frames, strict=True):
        cache.parm(parm).deleteAllKeyframes()
        cache.parm(parm).set(value)
    return geo, box, cache


def test_render_a_file_cache_writes_its_frame_range(client, work_dir):
    _geo, _box, cache = _file_cache(work_dir)
    assert cache.parm("loadfromdisk").eval() == 0
    result = client.ok("render", {"rop_path": cache.path()})
    assert result["state"] == "done", result
    assert result["rop_path"] == cache.path()
    assert result["frames"] == [1, 3, 1]
    assert result["outputs"] == [_fwd(work_dir / f"fc.{i:04d}.bgeo.sc") for i in (1, 2, 3)]
    assert "missing" not in result
    assert result["side_effects"] == {"loadfromdisk": [0, 1]}
    assert cache.parm("loadfromdisk").eval() == 1
    assert any("rendered through" in n for n in result["notes"]), result


def test_render_a_file_cache_refuses_an_output_override(client, work_dir):
    _geo, _box, cache = _file_cache(work_dir)
    error = client.error("render", {"rop_path": cache.path(), "output": _fwd(work_dir / "x.bgeo")})
    assert error["code"] == "invalid_argument"
    # Review 20 N4: the hint names the menu token a set takes, not an index.
    assert f'path: "{cache.path()}/filemethod", value: "explicit"' in error["hint"], error
    assert "then set the file parm to the path you want" in error["hint"]
    assert f'path: "{cache.path()}/file"' in error["hint"], error
    assert "file to the path" not in error["hint"]
    assert "explicit" in cache.parm("filemethod").menuItems()


def test_render_a_rop_sop_uses_its_own_frame_range(client, work_dir):
    geo = hou.node("/obj").createNode("geo", "fx")
    box = geo.createNode("box")
    rop = geo.createNode("rop_geometry", "write")
    rop.setInput(0, box)
    rop.parm("sopoutput").set(_fwd(work_dir / "w.$F4.bgeo.sc"))
    rop.parm("trange").set(1)
    rop.parm("f1").deleteAllKeyframes()
    rop.parm("f2").deleteAllKeyframes()
    rop.parm("f1").set(2)
    rop.parm("f2").set(3)
    result = client.ok("render", {"rop_path": rop.path()})
    assert result["frames"] == [2, 3, 1]
    assert result["outputs"] == [_fwd(work_dir / f"w.{i:04d}.bgeo.sc") for i in (2, 3)]


@pytest.mark.slow
def test_render_cancelled_job_result_carries_the_partial_outputs(client, work_dir):
    geo, box, cache = _file_cache(work_dir, frames=(1, 60))
    slow = geo.createNode("python", "slow")
    slow.parm("python").set("import time\ntime.sleep(0.08)")
    slow.setInput(0, box)
    cache.setInput(0, slow)
    started = client.ok("render", {"rop_path": cache.path(), "wait_s": 0})
    job_id = started["job_id"]
    deadline = time.monotonic() + 30
    while len(list(work_dir.glob("fc.*"))) < 3 and time.monotonic() < deadline:
        client.host.executor.pump_once(0.05)
    client.ok("job", {"action": "cancel", "job_id": job_id})
    final = _wait_job(client, job_id)
    assert final["state"] == "cancelled", final
    error = client.error("job", {"action": "result", "job_id": job_id})
    assert error["code"] == "cancelled"
    detail = error["detail"]
    last = detail["last_status"]
    assert last["total"] == 60
    assert last["state"] == "cancelled", last  # review 20 N7
    assert last["message"].startswith(f"{last['current']}/60 frames done, rendering frame "), last
    assert ".0" not in last["message"], last  # frames print as integers
    written = sorted(work_dir.glob("fc.*"))
    partial = detail["partial"]
    summary = partial["outputs_summary"]
    assert summary["count"] == len(written) < 60
    assert summary["last"] == _fwd(written[-1])
    assert summary["missing_count"] == 60 - len(written)
    assert cache.parm("loadfromdisk").eval() == 0  # Save to Disk's side effects need a full save


# -- single-file ROPs (review 23 P0-1) ------------------------------------------------


def _alembic_rop(work_dir: Path, name: str = "anim.abc"):
    geo = hou.node("/obj").createNode("geo", "anim")
    box = geo.createNode("box")
    box.parm("ty").setExpression("$F * 0.1")
    rop = hou.node("/out").createNode("alembic", "abc")
    rop.parm("sop_path").set(box.path())
    rop.parm("filename").set(_fwd(work_dir / name))
    return rop


def _abc_frames(path: Path) -> tuple[float, float] | None:
    import _alembic_hom_extensions as abc

    span = abc.alembicTimeRange(_fwd(path))
    return None if span is None else tuple(round(t * hou.fps(), 3) for t in span)


def test_render_alembic_rop_writes_the_range_in_one_call(client, work_dir):
    rop = _alembic_rop(work_dir)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 12]})
    assert result["state"] == "done", result
    assert result["outputs"] == [_fwd(work_dir / "anim.abc")]
    assert "outputs_sample" not in result and "layers" not in result
    assert _abc_frames(work_dir / "anim.abc") == (1.0, 12.0)


def test_render_fails_when_an_alembic_file_lost_frames(client, work_dir):
    from hocuspocus.host.tools import visual

    rop = _alembic_rop(work_dir)
    for frame in range(1, 13):
        rop.render(frame_range=(frame, frame), verbose=False)
    with pytest.raises(visual.ToolError) as caught:
        visual.check_single_file(
            rop.path(), _fwd(work_dir / "anim.abc"), [float(f) for f in range(1, 13)]
        )
    assert caught.value.code == "cook_failed"
    assert "12 frames" in caught.value.message


# -- the ROP's camera (review 21 papercut 5) ------------------------------------------


def test_render_a_rop_whose_camera_is_missing_names_the_parm(client, work_dir):
    """A fresh OpenGL ROP points at /obj/cam1; when that is missing, render said only
    "No camera specified for render." It now fails before rendering, naming the parm and
    the scene's cameras."""
    _toy_scene()
    rop = hou.node("/out").createNode("opengl", "gl_nocam")
    rop.parm("picture").set(_fwd(work_dir / "nocam.$F4.png"))
    error = client.error("render", {"rop_path": rop.path()})
    assert error["code"] == "node_not_found", error
    assert "camera" in error["message"] and "/obj/cam1" in error["message"], error
    assert not error.get("candidates")
    assert "pass camera" in error["hint"] and "cam" in error["hint"], error
    other = hou.node("/obj").createNode("cam", "shot_cam")
    error = client.error("render", {"rop_path": rop.path()})
    assert error["candidates"] == [other.path()], error
    assert not list(work_dir.glob("nocam.*"))


def test_render_camera_override_is_checked(client, work_dir):
    geo = _toy_scene()
    rop = _opengl_rop(work_dir)
    error = client.error("render", {"rop_path": rop.path(), "camera": geo.path()})
    assert error["code"] == "invalid_argument", error
    assert error["candidates"] == ["/obj/rendercam"], error
    error = client.error("render", {"rop_path": rop.path(), "camera": "/obj/nope"})
    assert error["code"] == "node_not_found", error
    bgeo = _bgeo_rop(work_dir, "c.$F4.bgeo.sc")
    error = client.error("render", {"rop_path": bgeo.path(), "camera": "/obj/rendercam"})
    assert error["code"] == "invalid_argument" and "camera" in error["message"], error


@pytest.mark.slow
def test_render_camera_override_renders_through_it(client, work_dir):
    _toy_scene()
    rop = _opengl_rop(work_dir)
    rop.parm("camera").set("/obj/cam1")  # missing: the override replaces it
    far = hou.node("/obj").createNode("cam", "far")
    far.parmTuple("t").set((0, 0.5, 40))
    far.parm("resx").set(320)
    far.parm("resy").set(240)
    result = client.ok("render", {"rop_path": rop.path(), "frames": [1, 1], "camera": far.path()})
    assert result["outputs"] == [_fwd(work_dir / "gl.0001.png")]
    assert "Rendered through /obj/far (camera restored)." in result["notes"], result
    assert rop.parm("camera").eval() == "/obj/cam1"


# -- kept capture child (review 22 finding 6) -----------------------------------------


@pytest.mark.slow
def test_headless_captures_reuse_a_kept_child(client):
    """A fresh child hython per capture cost about 3 s, 69 % of a soak's tool time. The
    child is now kept: later captures push a fresh scene snapshot to it and re-render its
    Flipbook ROP, /obj and stage alike, and edits between captures show."""
    from hocuspocus.host.tools import visual

    visual.close_warm_capture()
    geo = _toy_scene()
    started = time.perf_counter()
    first = client.ok("look", {"resolution": [160, 120]})
    cold_s = time.perf_counter() - started
    child = visual._warm["child"]
    assert child is not None and child.proc.poll() is None
    pid = child.proc.pid
    imp = hou.node("/stage").createNode("sopimport", "imp")
    imp.parm("soppath").set(geo.path())
    started = time.perf_counter()
    geo.parmTuple("t").set((3, 0, 0))
    moved = client.ok("look", {"resolution": [160, 120], "fit": "none"})
    stage = client.ok("look", {"target": imp.path(), "resolution": [160, 120]})
    warm_s = (time.perf_counter() - started) / 2
    print(f"\ncapture: first (child start) {cold_s:.2f}s, kept child {warm_s:.2f}s per capture")
    assert visual._warm["child"].proc.pid == pid
    assert stage["scene"] == "stage" and first["scene"] == moved["scene"] == "obj"
    for result in (first, stage, moved):
        assert result["backend_used"] == "flipbook", result
        assert _not_blank(_decode(result["image"]))
    assert _centroid_x(moved["image"]) > _centroid_x(first["image"]) + 10
    assert warm_s < cold_s
    child.proc.kill()  # a kept child that went away is replaced
    child.proc.wait(10)
    again = client.ok("look", {"resolution": [160, 120]})
    assert visual._warm["child"].proc.pid != pid
    assert "notes" not in again or not any("kept" in n for n in again["notes"])


@pytest.mark.slow
def test_a_kept_child_that_crashes_falls_back_to_a_fresh_one(client, monkeypatch):
    from hocuspocus.host.tools import visual

    visual.close_warm_capture()
    monkeypatch.setitem(visual._warm, "disabled", None)
    _toy_scene()
    client.ok("look", {"resolution": [96, 72]})
    real_wait = visual.WarmCapture._wait

    def crash_after_first(self, request, offset, timeout_s):
        if self.uses > 1:
            self.proc.kill()
            self.proc.wait(10)
            raise visual.exit_error(139, "Fatal error: Segmentation fault")
        return real_wait(self, request, offset, timeout_s)

    monkeypatch.setattr(visual.WarmCapture, "_wait", crash_after_first)
    result = client.ok("look", {"resolution": [96, 72]})
    assert result["backend_used"] == "flipbook"
    assert visual.WARM_CRASH_NOTE in result["notes"], result
    assert _not_blank(_decode(result["image"]))
    assert visual._warm["disabled"] and visual._warm["child"] is None
    later = client.ok("look", {"resolution": [96, 72]})
    assert visual._warm["child"] is None  # fresh children from now on
    assert visual.WARM_CRASH_NOTE not in later.get("notes", [])
