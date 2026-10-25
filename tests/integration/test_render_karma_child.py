"""Headless, ``render`` of a Karma ROP runs in a child hython (BIBLE D74; review 26 P3
friction 1: 83 Karma renders held the main thread for about 19 min, and every edit sent
meanwhile answered ``houdini_busy``)."""

from __future__ import annotations

import os

import pytest

hou = pytest.importorskip("hou")


def _karma_scene(work_dir, name="beauty"):
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("sphere")
    light = hou.node("/obj").createNode("hlight::2.0", "key")
    light.parmTuple("t").set((3, 4, 5))
    cam = hou.node("/obj").createNode("cam", "cam1")
    cam.parmTuple("t").set((0, 0, 5))
    rop = hou.node("/out").createNode("karma", name)
    rop.parm("camera").set(cam.path())
    rop.parm("resolutionx").set(160)
    rop.parm("resolutiony").set(90)
    rop.parm("samplesperpixel").set(4)
    rop.parm("picture").set((work_dir / "beauty.$F4.exr").as_posix())
    return rop


@pytest.mark.slow
def test_a_karma_render_leaves_the_main_thread_to_other_calls(client, work_dir):
    from hocuspocus.host.tools import visual

    rop = _karma_scene(work_dir)
    assert visual.needs_isolation(rop, client.host.ctx)
    foreground = rop.parm("soho_foreground").eval()
    envelope = client.call("render", {"rop_path": rop.path(), "frames": [1, 2, 1], "wait_s": 300})
    assert envelope["ok"], envelope
    result = envelope["result"]
    assert result["state"] == "done"
    assert result["outputs"] == [(work_dir / f"beauty.000{f}.exr").as_posix() for f in (1, 2)]
    assert all(os.path.getsize(p) > 0 for p in result["outputs"])
    assert result["thumbnail"]["width"] == 160
    timing = envelope["_meta"]["timing"]
    # The snapshot and the parm reads are the main thread's share; husk ran in the child.
    assert timing["main_thread_ms"] < 0.25 * envelope["_meta"]["elapsed_ms"], envelope["_meta"]
    # The ROP in the scene is untouched: the overrides went to the child's copy.
    assert rop.parm("soho_foreground").eval() == foreground
    assert rop.parm("picture").unexpandedString().endswith("beauty.$F4.exr")


@pytest.mark.slow
def test_a_karma_render_in_process_when_switched_off(client, work_dir, monkeypatch):
    from hocuspocus.host.tools import visual

    monkeypatch.setattr(visual, "KARMA_IN_CHILD", False)
    rop = _karma_scene(work_dir, "inproc")
    assert not visual.needs_isolation(rop, client.host.ctx)
    envelope = client.call("render", {"rop_path": rop.path(), "wait_s": 300})
    assert envelope["ok"], envelope
    assert envelope["result"]["outputs"] == [(work_dir / "beauty.0001.exr").as_posix()]
    timing = envelope["_meta"]["timing"]
    assert timing["main_thread_ms"] > 0.5 * envelope["_meta"]["elapsed_ms"]
