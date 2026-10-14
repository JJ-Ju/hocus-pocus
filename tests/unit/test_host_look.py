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


# viewport_capture keeps its 1.4 policy: (kind, source, camera, env) -> chain
CAPTURE_PLANS = [
    ("obj", "auto", None, HEADLESS, ROPS_HEADLESS),
    ("lop", "auto", None, HEADLESS, ROPS_HEADLESS),
    ("obj", "flipbook_rop", None, HEADLESS, ROPS_HEADLESS),
    ("obj", "opengl_rop", None, HEADLESS, ROPS_HEADLESS),
    ("obj", "auto", None, GUI, ("viewer",)),  # 1.4: auto is the viewer in the GUI
    ("obj", "auto", None, GUI_NO_VIEWER, ROPS_GUI),
    ("obj", "auto", "/obj/cam1", GUI, ROPS_GUI),  # with a camera, the ROP
    ("lop", "auto", None, GUI, ROPS_GUI),
    ("obj", "flipbook_rop", None, GUI, ROPS_GUI),
    ("obj", "viewer", None, GUI, ("viewer",)),
]


@pytest.mark.parametrize(("kind", "source", "camera", "env", "chain"), CAPTURE_PLANS)
def test_viewport_capture_plan_is_1_4s(kind, source, camera, env, chain):
    plan = select.capture_plan(_spec(kind, source=source, camera=camera), env)
    assert plan.chain == chain
    assert plan.samples is None and plan.rop_parms == {}


@pytest.mark.parametrize(
    ("kind", "env", "code"),
    [("lop", GUI, "invalid_argument"), ("obj", GUI_NO_VIEWER, "invalid_value")],
)
def test_viewport_capture_viewer_refusals(kind, env, code):
    with pytest.raises(ToolError) as caught:
        select.capture_plan(_spec(kind, source="viewer"), env)
    assert caught.value.code == code


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
