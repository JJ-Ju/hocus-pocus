"""The ``look`` backend policy (spec-2.0 §2.5; host/look/select.py), without Houdini."""

from __future__ import annotations

import pytest

from hocuspocus.host.look import select
from hocuspocus.host.look.base import Env
from hocuspocus.host.look.spec import LookSpec, parse_look_args
from hocuspocus.tools.errors import ToolError

BOTH = frozenset({"flipbook", "opengl"})
HEADLESS = Env(ui=False, rops=BOTH)
HEADLESS_LIT = Env(ui=False, rops=BOTH, lights=True)
GUI = Env(ui=True, rops=BOTH, viewer=True)
GUI_LIT = Env(ui=True, rops=BOTH, viewer=True, lights=True)
GUI_NO_VIEWER = Env(ui=True, rops=BOTH, viewer=False)

ROPS_HEADLESS = ("flipbook", "opengl", "karma")
ROPS_GUI = ("flipbook", "opengl")


def _spec(kind="obj", quality="draft", source="auto", rop_samples=None, camera=None):
    return LookSpec(
        kind=kind, quality=quality, source=source, rop_samples=rop_samples, camera=camera
    )


# (kind, quality, source, rop_samples, env) -> (chain, samples, lit ROP parms)
PLANS = [
    # draft: the viewport ROPs; Karma only as the crash fallback, headless only
    ("obj", "draft", "auto", None, HEADLESS, ROPS_HEADLESS, None, False),
    ("sop", "draft", "auto", None, HEADLESS, ROPS_HEADLESS, None, False),
    ("lop", "draft", "auto", None, HEADLESS, ROPS_HEADLESS, None, False),
    ("obj", "draft", "auto", None, GUI, ROPS_GUI, None, False),
    ("lop", "draft", "auto", None, GUI, ROPS_GUI, None, False),
    (
        "obj",
        "draft",
        "auto",
        None,
        Env(rops=frozenset({"opengl"})),
        ("opengl", "karma"),
        None,
        False,
    ),
    ("obj", "draft", "auto", None, Env(rops=frozenset()), ("karma",), 2, False),
    # the viewer only when asked for, in the GUI, for /obj
    ("obj", "draft", "viewer", None, GUI, ("viewer",), None, False),
    ("sop", "draft", "viewer", None, GUI, ("viewer",), None, False),
    # lit: the scene's lights through the Flipbook ROP, else Karma at 2 samples
    ("obj", "lit", "auto", None, HEADLESS_LIT, ROPS_HEADLESS, None, True),
    ("lop", "lit", "auto", None, GUI_LIT, ROPS_GUI, None, True),
    ("obj", "lit", "auto", None, HEADLESS, ("karma",), 2, False),
    ("lop", "lit", "auto", None, GUI, ("karma",), 2, False),
    # final: Karma at the target ROP's samples, else 32
    ("obj", "final", "auto", None, HEADLESS, ("karma",), 32, False),
    ("lop", "final", "auto", None, GUI_LIT, ("karma",), 32, False),
    ("obj", "final", "auto", 12, HEADLESS, ("karma",), 12, False),
    # a Cop node is its own image, whatever the quality
    ("cop", "draft", "auto", None, HEADLESS, ("rop_image",), None, False),
    ("cop", "final", "auto", None, GUI, ("rop_image",), None, False),
]


@pytest.mark.parametrize(
    ("kind", "quality", "source", "rop_samples", "env", "chain", "samples", "lit"), PLANS
)
def test_look_plan(kind, quality, source, rop_samples, env, chain, samples, lit):
    plan = select.plan(_spec(kind, quality, source, rop_samples), env)
    assert plan.chain == chain
    assert plan.samples == samples
    assert plan.rop_parms == (select.LIT_ROP_PARMS if lit else {})


# (kind, quality, source, env) -> error code
REFUSED = [
    ("obj", "draft", "viewer", HEADLESS, "ui_required"),
    ("obj", "draft", "viewer", GUI_NO_VIEWER, "invalid_value"),
    ("lop", "draft", "viewer", GUI, "invalid_argument"),  # a stage is never the viewer
    ("cop", "draft", "viewer", GUI, "invalid_argument"),
    ("obj", "lit", "viewer", GUI, "invalid_argument"),  # the viewer is a draft look
    ("obj", "final", "viewer", GUI, "invalid_argument"),
    ("obj", "draft", "auto", Env(ui=True, rops=frozenset()), "internal"),
    ("obj", "best", "auto", HEADLESS, "invalid_argument"),
]


@pytest.mark.parametrize(("kind", "quality", "source", "env", "code"), REFUSED)
def test_look_plan_refusals(kind, quality, source, env, code):
    with pytest.raises(ToolError) as caught:
        select.plan(_spec(kind, quality, source), env)
    assert caught.value.code == code


def test_plan_notes_say_why_lit_used_karma_and_quality_is_ignored_for_a_cop():
    assert "no lights" in select.plan(_spec("obj", "lit"), HEADLESS).notes[0]
    assert select.plan(_spec("obj", "lit"), HEADLESS_LIT).notes == ()
    assert "ignored" in select.plan(_spec("cop", "lit"), HEADLESS).notes[0]
    assert select.plan(_spec("cop", "draft"), HEADLESS).notes == ()


def test_viewport_captures_1_4_policy_is_gone():
    """2.1 removed viewport_capture and its 1.4 chain policy with compat_1x."""
    assert not hasattr(select, "capture_plan") and not hasattr(select, "capture_chain")


@pytest.mark.parametrize(
    ("backend", "kind", "env", "ok"),
    [
        ("viewer", "obj", GUI, True),
        ("viewer", "obj", HEADLESS, False),
        ("viewer", "lop", GUI, False),
        ("viewer", "obj", GUI_NO_VIEWER, False),
        ("flipbook", "obj", HEADLESS, True),
        ("flipbook", "obj", Env(rops=frozenset({"opengl"})), False),
        ("flipbook", "cop", HEADLESS, False),
        ("opengl", "lop", GUI, True),
        ("karma", "lop", HEADLESS, True),
        ("karma", "cop", HEADLESS, False),
        ("rop_image", "cop", HEADLESS, True),
        ("rop_image", "obj", HEADLESS, False),
    ],
)
def test_backends_say_whether_they_can_run(backend, kind, env, ok):
    can, why = select.backends()[backend].can_run(_spec(kind), env)
    assert can is ok
    assert bool(why) is not ok


def test_look_arguments_are_checked_without_houdini():
    spec = parse_look_args({"on": "worker"})  # on is the bridge's: accepted, ignored
    assert (spec.quality, spec.source, spec.fit, spec.fit_given) == ("draft", "auto", "all", False)
    assert spec.res == (1024, 768) and spec.target is None
    spec = parse_look_args({"target": " /obj/geo1 ", "fit": "none", "resolution": [64, 48]})
    assert (spec.target, spec.fit, spec.fit_given, spec.res) == (
        "/obj/geo1",
        "none",
        True,
        (64, 48),
    )
    for bad in (
        {"quality": "best"},
        {"source": "flipbook_rop"},
        {"fit": "target"},
        {"target": ""},
        {"camera": 3},
        {"frame": True},
        {"resolution": [8, 8]},
        {"resolution": [9000, 100]},
    ):
        with pytest.raises(ToolError) as caught:
            parse_look_args(bad)
        assert caught.value.code == "invalid_argument", bad


def test_look_output_is_a_png_or_jpg_path():
    """2.1 (review 26 P1 #3): look saves its image where output says."""
    assert parse_look_args({}).path is None
    for value in (" $HIP/shots/a.png ", "C:/x/b.JPG", "~/c.jpeg"):
        spec = parse_look_args({"output": value})
        assert spec.path == value.strip()
        assert spec.parsed()["path"] == value.strip()  # what capture_targets checks
    for bad in ("", "  ", 7, "a.exr", "a.png.txt", "folder/"):
        with pytest.raises(ToolError) as caught:
            parse_look_args({"output": bad})
        assert caught.value.code == "invalid_argument", bad
    with pytest.raises(ToolError) as caught:
        parse_look_args({"output": "beauty.exr"})
    assert ".png or .jpg" in caught.value.message
    assert "render" in (caught.value.hint or "")


def test_jpeg_quality_needs_a_jpeg_output():
    """D86: 1-100, and only with a .jpg/.jpeg output (anything else would change nothing)."""
    assert parse_look_args({"output": "a.jpg"}).jpeg_quality is None
    assert parse_look_args({"output": "a.JPEG", "jpeg_quality": 40}).jpeg_quality == 40
    for args in (
        {"output": "a.jpg", "jpeg_quality": 0},
        {"output": "a.jpg", "jpeg_quality": 101},
        {"output": "a.jpg", "jpeg_quality": 80.5},
        {"output": "a.jpg", "jpeg_quality": True},
        {"output": "a.png", "jpeg_quality": 80},
        {"jpeg_quality": 80},
    ):
        with pytest.raises(ToolError) as caught:
            parse_look_args(args)
        assert caught.value.code == "invalid_argument", args


def test_look_output_hint_leaves_out_render_where_the_profile_lacks_it(monkeypatch):
    from hocuspocus.tools import migration

    monkeypatch.setattr(migration, "current_profile", lambda: "minimal")
    with pytest.raises(ToolError) as caught:
        parse_look_args({"output": "beauty.exr"})
    assert caught.value.hint is None


def test_finish_capture_writes_output_as_png_or_jpeg(tmp_path):
    """The flattened capture at its rendered size goes to output; the image stays inline."""
    Image = pytest.importorskip("PIL.Image")
    from hocuspocus.host.look.image import BACKGROUND, finish_capture

    capture = tmp_path / "captures" / "capture_1.png"
    capture.parent.mkdir()
    Image.new("RGBA", (1600, 800), (255, 0, 0, 0)).save(capture)
    png = tmp_path / "out" / "deep" / "look.png"
    result = finish_capture(str(capture), (1600, 800), 1.0, {"backend_used": "flipbook"}, str(png))
    assert result["output"] == str(png) and "also_written" not in result
    assert result["image"]["png_base64"] and result["width"] == 1024  # inline: downscaled
    with Image.open(png) as im:
        assert im.size == (1600, 800) and im.mode == "RGB"  # file: rendered size, flat
        assert im.getpixel((0, 0)) == BACKGROUND
    jpg = tmp_path / "out" / "look.jpg"
    result = finish_capture(str(capture), (1600, 800), 1.0, {}, str(jpg))
    with Image.open(jpg) as im:
        assert im.format == "JPEG" and im.size == (1600, 800)


def test_unwritable_output_is_invalid_argument(tmp_path):
    from hocuspocus.host.look.image import write_copy

    capture = tmp_path / "c.png"
    capture.write_bytes(b"not used")
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(ToolError) as caught:
        write_copy(str(capture), str(blocker / "sub" / "look.png"))  # parent is a file
    assert caught.value.code == "invalid_argument"
    assert "Cannot write the image" in caught.value.message


def test_viewport_capture_settings_set_on_visual_reach_the_backends(monkeypatch):
    """Tests and the docs set WARM_CAPTURES, _CHILD_SCRIPT, _stage_crashed and
    capture_with_karma on hocuspocus.host.tools.visual; the look modules own them now."""
    from hocuspocus.host.look import child, flipbook, karma
    from hocuspocus.host.tools import visual

    monkeypatch.setattr(visual, "WARM_CAPTURES", False)
    assert flipbook.WARM_CAPTURES is False
    monkeypatch.setattr(visual, "_CHILD_SCRIPT", "pass\n")
    assert child._CHILD_SCRIPT == "pass\n"
    crashed: dict[str, str] = {}
    monkeypatch.setattr(visual, "_stage_crashed", crashed)
    assert select._stage_crashed is crashed

    def stand_in(*args, **kwargs):
        return None

    monkeypatch.setattr(visual, "capture_with_karma", stand_in)
    assert karma.capture_with_karma is stand_in
    monkeypatch.undo()
    assert flipbook.WARM_CAPTURES is True and child._CHILD_SCRIPT != "pass\n"
    assert karma.capture_with_karma is not stand_in
