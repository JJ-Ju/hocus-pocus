"""``look`` (spec-2.0 §2.5; host/tools/look.py, host/look/): one picture tool whose
backend follows ``quality``. Headless here: draft through the Flipbook ROP (the kept
child), lit through it with the scene's lights or Karma without lights, final through
Karma; a stage and a Cop node too. The 1.4 viewport_capture tests, converted to look in
2.1 (test_visual, test_lops, test_cop), are the regression suite of the backends."""

from __future__ import annotations

import base64
import io
import os
import time

import pytest

hou = pytest.importorskip("hou")
Image = pytest.importorskip("PIL.Image")

from hocuspocus.host.tools import events as ev  # noqa: E402

RES = [160, 120]


def _decode(image: dict):
    assert image["mime_type"] == "image/png"
    return Image.open(io.BytesIO(base64.b64decode(image["png_base64"])))


def _contrast(result: dict) -> int:
    lo, hi = _decode(result["image"]).convert("L").getextrema()
    return hi - lo


def _centroid_x(result: dict) -> float:
    """Mean x of the pixels that differ from the corner (the background)."""
    img = _decode(result["image"]).convert("L")
    bg = img.getpixel((0, 0))
    xs = [
        x
        for y in range(img.height)
        for x in range(img.width)
        if abs(img.getpixel((x, y)) - bg) > 12
    ]
    return sum(xs) / len(xs) if xs else -1.0


def _obj_scene(light: bool = False):
    geo = hou.node("/obj").createNode("geo", "toy")
    toy = geo.createNode("testgeometry_rubbertoy", "toy")
    box = geo.createNode("box", "box")
    box.parmTuple("t").set((4, 0, 0))
    merge = geo.createNode("merge", "both")
    merge.setInput(0, toy)
    merge.setInput(1, box)
    merge.setDisplayFlag(True)
    merge.setRenderFlag(True)
    if light:
        key = hou.node("/obj").createNode("hlight::2.0", "key")
        key.parmTuple("t").set((3, 4, 5))
    return geo


def _stage_scene(light: bool = True):
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "ball")
    last = sphere
    if light:
        dome = stage.createNode("domelight::3.0", "dome")
        dome.setInput(0, sphere)
        last = dome
    last.setDisplayFlag(True)
    return last


def _nodes() -> dict[str, list[str]]:
    return {m: sorted(c.name() for c in hou.node(m).children()) for m in ("/obj", "/out", "/stage")}


def test_look_arguments_and_kinds_are_checked(v2_client):
    _obj_scene()
    assert v2_client.error("look", {"quality": "best"})["code"] == "invalid_argument"
    assert v2_client.error("look", {"target": "/obj/nope"})["code"] == "node_not_found"
    cam = hou.node("/obj").createNode("cam", "cam1")
    error = v2_client.error("look", {"target": cam.path()})
    assert error["code"] == "invalid_argument" and "camera" in error["hint"]
    error = v2_client.error("look", {"source": "viewer"})
    assert error["code"] == "ui_required"
    chop = hou.node("/ch") or hou.node("/").createNode("chopnet", "ch")
    assert v2_client.error("look", {"target": chop.path()})["code"] == "invalid_argument"


@pytest.mark.slow
def test_look_draft_on_obj_reuses_the_warm_child(v2_client):
    """draft = the Flipbook ROP in the kept child: the second look is under a second, and
    looks leave no nodes, undo steps or events."""
    from hocuspocus.host.tools import visual

    visual.close_warm_capture()
    geo = _obj_scene()
    before = _nodes()
    undo_before = list(hou.undos.undoLabels())
    since = ev.LOG.last_seq
    dirty = v2_client.host.scene.dirty
    started = time.perf_counter()
    first = v2_client.ok("look", {"resolution": RES})
    cold_s = time.perf_counter() - started
    assert first["backend_used"] == "flipbook"
    assert first["chain"] == ["flipbook", "opengl", "karma"]
    assert first["quality"] == "draft" and first["target"] is None
    assert (first["scene"], first["context"]) == ("obj", "/obj")
    assert first["camera_used"] == "temporary" and first["fit_used"] == "all"
    assert first["rendered"] == RES and os.path.isfile(first["path"])
    assert _contrast(first) > 40
    pid = visual._warm["child"].proc.pid
    started = time.perf_counter()
    framed = v2_client.ok("look", {"target": geo.path(), "resolution": RES})
    warm_s = time.perf_counter() - started
    print(f"\nlook draft: first {cold_s:.2f}s (child start), second {warm_s:.2f}s (warm)")
    assert visual._warm["child"].proc.pid == pid
    assert warm_s < 1.0, warm_s
    assert framed["fit_used"] == "target" and framed["target"] == geo.path()
    assert _nodes() == before
    assert list(hou.undos.undoLabels()) == undo_before
    events = v2_client.ok("events", {"since": since})["events"]
    assert not [e for e in events if e.get("path", "").startswith(("/obj", "/out"))], events
    assert v2_client.host.scene.dirty is dirty


@pytest.mark.slow
def test_look_at_a_sop_frames_it_and_shows_it_when_not_displayed(v2_client):
    geo = _obj_scene()
    box = geo.node("box")
    whole = v2_client.ok("look", {"resolution": RES})
    sop = v2_client.ok("look", {"target": box.path(), "resolution": RES})
    assert sop["fit_used"] == "target" and sop["scene"] == "obj"
    assert _contrast(sop) > 40
    # Framed on the box alone, it fills more of the frame than in the whole scene.
    assert sop["image"] != whole["image"]
    assert geo.displayNode().name() == "both" and geo.renderNode().name() == "both"


@pytest.mark.slow
def test_look_lit_and_final_on_obj(v2_client):
    """lit without lights is Karma at 2 samples (a note says so); with a light it is the
    Flipbook ROP; final is Karma at 32 samples, or the target ROP's own."""
    _obj_scene()
    before = _nodes()
    timings = {}
    started = time.perf_counter()
    dark = v2_client.ok("look", {"quality": "lit", "resolution": RES})
    timings["lit (no lights, karma 2)"] = time.perf_counter() - started
    assert dark["backend_used"] == "karma" and dark["chain"] == ["karma"]
    assert dark["samples"] == 2
    assert any("no lights" in n for n in dark["notes"]), dark
    assert _contrast(dark) > 20
    started = time.perf_counter()
    final = v2_client.ok("look", {"quality": "final", "resolution": RES})
    timings["final (karma 32)"] = time.perf_counter() - started
    assert final["backend_used"] == "karma" and final["samples"] == 32
    assert _contrast(final) > 20
    hou.node("/obj").createNode("hlight::2.0", "key").parmTuple("t").set((3, 4, 5))
    started = time.perf_counter()
    lit = v2_client.ok("look", {"quality": "lit", "resolution": RES})
    timings["lit (lights, flipbook)"] = time.perf_counter() - started
    assert lit["backend_used"] == "flipbook" and "samples" not in lit
    assert _contrast(lit) > 40
    cam = hou.node("/obj").createNode("cam", "shot")
    cam.parmTuple("t").set((0, 1, 12))
    karma = hou.node("/out").createNode("karma", "beauty")
    karma.parm("camera").set(cam.path())
    karma.parm("samplesperpixel").set(4)
    rop = v2_client.ok("look", {"target": karma.path(), "quality": "final", "resolution": RES})
    assert rop["samples"] == 4 and rop["camera_used"] == cam.path()
    assert any(cam.path() in n for n in rop["notes"]), rop
    print("\n" + ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    assert _nodes() == {**before, "/obj": sorted([*before["/obj"], "key", "shot"])} | {
        "/out": ["beauty"]
    }


@pytest.mark.slow
def test_look_at_a_stage(v2_client):
    lop = _stage_scene(light=True)
    before = _nodes()
    draft = v2_client.ok("look", {"target": "/stage", "resolution": RES})
    assert draft["scene"] == "stage" and draft["lop_path"] == lop.path()
    assert draft["context"] == "/stage" and draft["backend_used"] == "flipbook"
    assert _contrast(draft) > 40
    lit = v2_client.ok("look", {"target": lop.path(), "quality": "lit", "resolution": RES})
    assert lit["backend_used"] == "flipbook"
    final = v2_client.ok("look", {"target": "/stage", "quality": "final", "resolution": RES})
    assert final["backend_used"] == "karma" and final["samples"] == 32
    assert _contrast(final) > 20
    error = v2_client.error("look", {"target": "/stage", "source": "viewer"})
    assert error["code"] == "ui_required"
    assert _nodes() == before


@pytest.mark.slow
def test_look_without_target_shows_the_stage_when_obj_displays_nothing(v2_client):
    _stage_scene(light=False)
    result = v2_client.ok("look", {"resolution": RES})
    assert result["scene"] == "stage" and result["target"] is None
    assert result["backend_used"] == "flipbook"


def test_look_at_a_cop_node(v2_client):
    net = hou.node("/img").createNode("copnet", "maps")
    color = net.createNode("constant", "color")
    color.parm("signature").set("f3")
    color.parmTuple("f3").set((0.2, 0.5, 0.9))
    color.setDisplayFlag(True)
    before = sorted(c.name() for c in net.children())
    started = time.perf_counter()
    result = v2_client.ok("look", {"target": net.path(), "quality": "final"})
    elapsed = time.perf_counter() - started
    print(f"\nlook cop: {elapsed:.2f}s")
    assert result["backend_used"] == "rop_image" and result["chain"] == ["rop_image"]
    assert result["scene"] == "cop" and result["cop_path"] == color.path()
    assert result["context"] == net.path()
    assert (result["width"], result["height"]) == (1024, 1024)
    assert any("ignored" in n for n in result["notes"]), result
    r, g, b = _decode(result["image"]).convert("RGB").getpixel((10, 10))
    assert b > r
    assert sorted(c.name() for c in net.children()) == before
    error = v2_client.error("look", {"target": color.path(), "camera": "/obj/cam1"})
    assert error["code"] == "invalid_argument"


def test_a_full_host_refuses_viewport_capture_and_names_look(client):
    """2.1: viewport_capture, a removed 1.4 tool, names look."""
    error = client.error("viewport_capture", {})
    assert error["code"] == "invalid_argument" and "1.4 tool" in error["message"]
    assert error["hint"].startswith("Use look ")


# -- output (2.1, review 26 P1 #3) -------------------------------------------------------


def _fwd(path) -> str:
    return os.path.abspath(str(path)).replace("\\", "/")


def _cop_net():
    net = hou.node("/img").createNode("copnet", "maps")
    color = net.createNode("constant", "color")
    color.parm("signature").set("f3")
    color.parmTuple("f3").set((0.2, 0.5, 0.9))
    color.setDisplayFlag(True)
    return net


def test_look_output_saves_the_image_and_still_returns_it(client, tmp_path):
    net = _cop_net()
    target = tmp_path / "evidence" / "maps.png"
    result = client.ok("look", {"target": net.path(), "output": str(target)})
    assert result["output"] == _fwd(target) and target.is_file()
    assert result["image"]["png_base64"]  # still inline
    with Image.open(target) as im:
        assert im.format == "PNG" and im.mode == "RGB"
        assert im.size == tuple(result["rendered"])  # the rendered size, not the inline one
        r, g, b = im.getpixel((10, 10))
        assert b > r
    jpg = tmp_path / "evidence" / "maps.jpg"
    result = client.ok("look", {"target": net.path(), "output": str(jpg)})
    with Image.open(jpg) as im:
        assert im.format == "JPEG"
    assert result["output"] == _fwd(jpg)
    target.write_bytes(b"old")
    client.ok("look", {"target": net.path(), "output": str(target)})
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # an existing file is replaced


def test_look_output_expands_variables(client, tmp_path):
    net = _cop_net()
    hou.putenv("HP_LOOK_OUT", str(tmp_path / "vars"))
    try:
        result = client.ok("look", {"target": net.path(), "output": "$HP_LOOK_OUT/a.png"})
    finally:
        hou.unsetenv("HP_LOOK_OUT")
    assert result["output"] == _fwd(tmp_path / "vars" / "a.png")
    assert (tmp_path / "vars" / "a.png").is_file()


def test_look_output_respects_approved_roots(client, host, tmp_path):
    net = _cop_net()
    host.config.approved_roots = [str(tmp_path / "allowed")]
    outside = tmp_path / "elsewhere" / "a.png"
    error = client.error("look", {"target": net.path(), "output": str(outside)})
    assert error["code"] == "path_not_allowed"
    assert not outside.exists() and not outside.parent.exists()
    inside = tmp_path / "allowed" / "a.png"
    result = client.ok("look", {"target": net.path(), "output": str(inside)})
    assert result["output"] == _fwd(inside) and inside.is_file()


def test_look_output_must_be_png_or_jpg(client):
    error = client.error("look", {"output": "beauty.exr"})
    assert error["code"] == "invalid_argument" and "render" in error["hint"]


@pytest.mark.slow
def test_look_output_on_obj_draft(client, tmp_path):
    """The Flipbook ROP path (headless: the kept child) writes output too."""
    _obj_scene()
    target = tmp_path / "toy.png"
    result = client.ok("look", {"resolution": RES, "output": str(target)})
    assert result["backend_used"] == "flipbook" and result["output"] == _fwd(target)
    with Image.open(target) as im:
        assert list(im.size) == RES
    assert _contrast(result) > 40


# -- a SOP shown alone, and the size asked (2.1, review 26 P1 #3 and #5) ------------------


def _coverage(result: dict) -> float:
    """The share of pixels that differ from the corner (the background)."""
    img = _decode(result["image"]).convert("L")
    bg = img.getpixel((0, 0))
    hits = [
        abs(img.getpixel((x, y)) - bg) > 12 for y in range(img.height) for x in range(img.width)
    ]
    return sum(hits) / len(hits)


def _nested_scene(library: str | None = None):
    """/obj/tower: a subnet (a locked asset saved to ``library`` when given) whose output
    merges a small box with a sphere far away; /obj/wall: a large box right behind the
    small one, which fills the frame unless the look shows the small box alone. (A locked
    asset whose definition is ``Embedded`` draws nothing in the headless child at all: its
    snapshot carries no contents, a gap of the snapshot, not of a SOP look.)"""
    geo = hou.node("/obj").createNode("geo", "tower")
    sub = geo.createNode("subnet", "massing")
    inner = sub.createNode("box", "inner_box")
    inner.parmTuple("size").set((0.5, 0.5, 0.5))
    far = sub.createNode("sphere", "far")
    far.parmTuple("t").set((30, 0, 0))
    merge = sub.createNode("merge", "both")
    merge.setInput(0, inner)
    merge.setInput(1, far)
    out = sub.createNode("output", "output0")
    out.setInput(0, merge)
    sub.setDisplayFlag(True)
    sub.setRenderFlag(True)
    if library:
        asset = sub.createDigitalAsset(
            name="hp_look_test::massing::1.0", hda_file_name=library, description="Massing"
        )
        asset.matchCurrentDefinition()
        assert asset.isLockedHDA()
        sub = asset
    wall = hou.node("/obj").createNode("geo", "wall")
    box = wall.createNode("box", "big")
    box.parmTuple("size").set((40, 40, 40))
    box.parmTuple("t").set((0, 0, -25))
    box.setDisplayFlag(True)
    return geo, sub


@pytest.mark.slow
@pytest.mark.parametrize("lock", [False, True], ids=["subnet", "locked_asset"])
def test_look_at_a_sop_inside_a_subnet_shows_it_alone(v2_client, work_dir, lock):
    """Review 26 P1 #3: a SOP inside a subnet or a locked asset is shown alone (the wall
    behind it and the subnet's other output are not drawn), through the kept child, and
    the scene keeps no trace."""
    from hocuspocus.host.tools import visual

    library = (work_dir / "hp_look_massing.hda").as_posix() if lock else None
    try:
        _look_alone(v2_client, visual, *_nested_scene(library), lock)
    finally:
        if library:
            hou.hipFile.clear(suppress_save_prompt=True)
            hou.hda.uninstallFile(library)


def _look_alone(v2_client, visual, geo, sub, lock):
    inner = f"{sub.path()}/inner_box"
    before = _nodes()
    undo_before = list(hou.undos.undoLabels())
    flags = (geo.displayNode().path(), sub.node("inner_box").isDisplayFlagSet())
    whole = v2_client.ok("look", {"target": geo.path(), "resolution": RES})
    pid = visual._warm["child"].proc.pid
    alone = v2_client.ok("look", {"target": inner, "resolution": RES})
    assert alone["backend_used"] == "flipbook" and alone["fit_used"] == "target"
    assert any("alone" in n for n in alone["notes"]), alone
    assert visual._warm["child"].proc.pid == pid  # the warm child drew it
    # Framed on the small box: alone it leaves background around it; with the wall
    # drawn, the wall fills the frame.
    assert _contrast(alone) > 40
    # The same framing (fit none reuses it) with the wall and the far sphere drawn.
    with_wall = v2_client.ok("look", {"target": geo.path(), "fit": "none", "resolution": RES})
    if os.environ.get("HP_LOOK_DUMP"):
        for name, shot in (("whole", whole), ("alone", alone), ("with_wall", with_wall)):
            _decode(shot["image"]).save(os.path.join(os.environ["HP_LOOK_DUMP"], f"{name}.png"))
    assert _coverage(with_wall) > _coverage(alone) + 0.2, (_coverage(with_wall), _coverage(alone))
    assert whole["image"] != alone["image"]
    final = v2_client.ok("look", {"target": inner, "quality": "final", "resolution": RES})
    assert final["backend_used"] == "karma"
    assert _coverage(final) < _coverage(with_wall) - 0.2, (_coverage(final), _coverage(with_wall))
    assert _nodes() == before
    assert list(hou.undos.undoLabels()) == undo_before
    assert (geo.displayNode().path(), sub.node("inner_box").isDisplayFlagSet()) == flags
    if lock:
        assert sub.isLockedHDA()


@pytest.mark.slow
def test_look_honours_the_resolution_and_names_the_backend(v2_client):
    """Review 26 P1 #5: Karma renders the size asked (22.0's Karma ROP rendered 1280x720
    whatever the override said), a look through a camera without resolution takes the
    camera's aspect, and lit says which renderer drew the scene's lights."""
    _obj_scene()
    cam = hou.node("/obj").createNode("cam", "shot")
    cam.parmTuple("t").set((0, 1, 12))
    cam.parm("resx").set(1920)
    cam.parm("resy").set(1080)
    dark = v2_client.ok("look", {"quality": "lit", "camera": cam.path(), "resolution": RES})
    assert dark["backend_used"] == "karma" and dark["rendered"] == RES
    assert (dark["width"], dark["height"]) == tuple(RES)
    assert any("1920x1080" in n for n in dark["notes"]), dark
    camera_size = v2_client.ok("look", {"quality": "final", "camera": cam.path()})
    assert camera_size["rendered"] == [1024, 576], camera_size
    assert not any("asked" in n for n in camera_size.get("notes", []))
    hou.node("/obj").createNode("hlight::2.0", "key").parmTuple("t").set((3, 4, 5))
    lit = v2_client.ok("look", {"quality": "lit", "resolution": RES})
    assert lit["backend_used"] == "flipbook" and lit["rendered"] == RES
    assert any("Flipbook ROP" in n for n in lit["notes"]), lit
