"""Pure helpers behind host tools, the tool registry and the job manager (no hou)."""

from __future__ import annotations

import logging
import threading

import pytest

from hocuspocus.host.jobs import JobManager
from hocuspocus.host.tools import registry
from hocuspocus.host.tools.code import _compile, to_jsonable
from hocuspocus.host.tools.hip import is_under, parse_load_warnings
from hocuspocus.host.tools.session import parse_file_history
from hocuspocus.host.undo import make_label, summarize
from hocuspocus.tools import catalog
from hocuspocus.tools.errors import ToolError


class InlineExecutor:
    def run(self, fn, timeout_s):
        return fn()


def test_parse_file_history_newest_first_and_deduped():
    text = "HIP\n{\nC:/a.hip\nC:/b.hip\nC:/a.hip\n}\nOBJ\n{\nC:/x.obj\n}\n"
    assert parse_file_history(text) == ["C:/a.hip", "C:/b.hip"]
    assert parse_file_history(text, "OBJ") == ["C:/x.obj"]
    assert parse_file_history("") == []


def test_parse_load_warnings():
    text = (
        "Error loading: C:/x/warn.hip\nWarning:     Bad node type found: zzz in /obj.\n             \n\n"
        '/obj/g2:\n\n             Skipping unrecognized parameter "vport_onionskin".\n'
    )
    assert parse_load_warnings(text) == [
        "Bad node type found: zzz in /obj.",
        '/obj/g2: Skipping unrecognized parameter "vport_onionskin".',
    ]


def test_is_under(tmp_path):
    assert is_under(str(tmp_path / "a" / "b.hip"), str(tmp_path))
    assert not is_under(str(tmp_path.parent / "other.hip"), str(tmp_path))
    assert not is_under(str(tmp_path) + "x/b.hip", str(tmp_path))


def test_compile_splits_trailing_expression():
    body, tail = _compile("x = 1\nx + 1")
    ns = {}
    exec(body, ns)
    assert eval(tail, ns) == 2
    _, tail = _compile("x = 1")
    assert tail is None


def test_to_jsonable():
    assert to_jsonable({"a": (1, 2), 3: {4}}) == {"a": [1, 2], "3": [4]}
    assert to_jsonable(float("nan")) == "nan"
    assert to_jsonable(object()).startswith("<object object")


def test_undo_labels():
    assert make_label("parm_set", {"items": [1, 2]}) == "HocusPocus: parm_set 2 parms"
    assert make_label("node_delete", {"paths": ["/obj/a"]}) == "HocusPocus: node_delete /obj/a"
    assert make_label("hip_new", {}) == "HocusPocus: hip_new"
    assert (
        make_label("houdini_python", {"code": "\n\nprint(1)\nx"})
        == "HocusPocus: houdini_python print(1)"
    )
    assert (
        make_label("houdini_python", {"code": "x", "undo_label": "build rig"})
        == "HocusPocus: houdini_python build rig"
    )
    assert len(make_label("t", {"path": "/" + "a" * 500})) <= 100
    assert summarize("x", None) == ""


def test_registered_host_tools_exist_in_catalogue():
    tools = registry.load_all()
    for name in (
        "session_info",
        "houdini_status",
        "hip_new",
        "hip_open",
        "hip_save",
        "hip_merge",
        "houdini_python",
        "job",
    ):
        assert name in tools
    result = registry.validate(logging.getLogger("test"))
    assert result["unknown"] == []
    if catalog.TOOLS:
        assert "hip_open" not in result["missing"]
        assert tools["hip_open"].mutating is True
        assert tools["houdini_status"].mutating is False
        assert tools["job"].mutating is False  # host-state only


SCENE_FALSE = {
    "undo",
    "time",
    "selection",
    "hda",
    "cook",
    "pdg",
    "render",
    "job",
    "viewport_capture",
}
"""Tools the dispatcher must not wrap in an undo group (registry.py docstring, BIBLE §4.1)."""


def test_registry_matches_catalogue_exactly():
    """BIBLE §3.5/§11: every non-bridge-local catalogue tool has a host implementation,
    and the host implements nothing the catalogue does not list (bar INTERNAL_TOOLS)."""
    registry.load_all()
    result = registry.validate(logging.getLogger("test"))
    assert result == {"unknown": [], "missing": []}


def test_host_tool_modules_import_hou_lazily():
    """Host tool modules must import on plain CPython: ``hou`` only inside functions."""
    import importlib
    import sys

    assert "hou" not in sys.modules
    for module in registry.TOOL_MODULES:
        importlib.import_module(f"hocuspocus.host.tools.{module}")
    assert "hou" not in sys.modules
    assert "pxr" not in sys.modules and "pdg" not in sys.modules


def test_scene_false_convention():
    tools = registry.load_all()
    assert {name for name, t in tools.items() if not t.scene} == SCENE_FALSE
    for name in SCENE_FALSE:
        spec = catalog.get(name)
        assert spec is not None
        # They can change something, so the agent must not see them as pure reads.
        assert spec.read_only is False, name
        assert spec.destructive is False, name
    for name in ("time", "selection", "cook", "job"):
        assert catalog.get(name).idempotent is True, name


def test_job_manager_lifecycle():
    jobs = JobManager(InlineExecutor())
    gate = threading.Event()

    def work(ctx):
        ctx.progress(0.5, "halfway")
        gate.wait(5)
        ctx.check_cancelled()
        return ctx.run_main(lambda: {"ok": 1})

    job = jobs.start("cook", work)
    status = jobs.status(job.id)
    assert status["state"] == "running"
    gate.set()
    job.done_event.wait(5)
    assert jobs.result(job.id)["result"] == {"ok": 1}
    assert jobs.list()[0]["job_id"] == job.id

    gate2 = threading.Event()
    job2 = jobs.start("render", lambda ctx: (gate2.wait(5), ctx.check_cancelled()))
    jobs.cancel(job2.id)
    gate2.set()
    job2.done_event.wait(5)
    assert jobs.status(job2.id)["state"] == "cancelled"
    # Review 20: a cancel after the job finished cancels nothing and says so.
    late = jobs.cancel(job.id)
    assert late["cancelled"] is False and late["state"] == "done"
    assert "already finished (done)" in late["notes"][0]
    assert jobs.cancel(job2.id)["cancelled"] is False

    job3 = jobs.start("bad", lambda ctx: 1 / 0)
    job3.done_event.wait(5)
    status = jobs.status(job3.id)
    assert status["state"] == "failed" and status["error"]["code"] == "internal"

    with pytest.raises(ToolError) as info:
        jobs.status("missing")
    assert info.value.code == "job_not_found"


def test_job_set_progress_snapshot():
    jobs = JobManager(InlineExecutor())
    gate = threading.Event()
    seen = threading.Event()

    def work(ctx):
        ctx.set_progress(37, 96, "frame 37/96")
        seen.set()
        gate.wait(5)
        return {"ok": 1}

    job = jobs.start("cook", work)
    seen.wait(5)
    status = jobs.status(job.id)
    assert status["current"] == 37 and status["total"] == 96
    assert status["progress"] == round(37 / 96, 4)
    assert status["message"] == "frame 37/96"
    gate.set()
    job.done_event.wait(5)
    status = jobs.status(job.id)
    assert status["state"] == "done"
    assert status["progress"] == 1.0 and status["current"] == 96

    job.set_progress(3, 0)
    assert job.status()["total"] == 0 and job.status()["progress"] == 1.0


def test_run_with_fallback_queues_a_retry_and_never_raises():
    from hocuspocus.host.tools.visual import run_with_fallback

    class Busy:
        def __init__(self, post_fails=False):
            self.posted = []
            self.post_fails = post_fails

        def run(self, fn, timeout_s):
            raise ToolError("houdini_busy", "busy")

        def post(self, fn):
            if self.post_fails:
                raise RuntimeError("stopped")
            self.posted.append(fn)

    calls = []
    assert run_with_fallback(InlineExecutor(), lambda: calls.append(1), 1.0) is None
    assert calls == [1]
    busy = Busy()
    note = run_with_fallback(busy, lambda: None, 1.0)
    assert "busy" in note and "retry was queued" in note
    assert len(busy.posted) == 1
    note = run_with_fallback(Busy(post_fails=True), lambda: None, 1.0)
    assert "also failed" in note


def test_capture_fallback_chain_is_ordered():
    """1.4: the ROP source tries the Flipbook ROP, then the OpenGL ROP (each when Houdini
    has it), then Karma; a crashed child moves on, any other error stops the chain, and
    the note names every ROP that did not render."""
    from hocuspocus.host.tools.visual import capture_chain, run_capture_chain

    assert capture_chain({"opengl", "flipbook"}) == ["flipbook", "opengl", "karma"]
    assert capture_chain(["opengl"]) == ["opengl", "karma"]
    assert capture_chain([]) == ["karma"]

    def crashed(code=139):
        return ToolError(
            "internal",
            f"The render process exited with code {code}.",
            hint="See detail.log for the render process output.",
            hou_exception=f"render process exit {code}",
            detail={"log": "Segmentation fault"},
        )

    def attempt(fail: set[str], tried: list[str]):
        def render_rop(rop_type):
            tried.append(rop_type)
            if rop_type in fail:
                raise crashed()
            return {"errors": [], "notes": []}

        return render_rop

    chain = ["flipbook", "opengl", "karma"]
    tried: list[str] = []
    used, _, notes = run_capture_chain(
        chain, stage=False, source="auto", render_rop=attempt(set(), tried), render_karma=None
    )
    assert (used, tried, notes) == ("flipbook", ["flipbook"], [])

    tried = []
    used, _, notes = run_capture_chain(
        chain,
        stage=False,
        source="auto",
        render_rop=attempt({"flipbook"}, tried),
        render_karma=None,
    )
    assert (used, tried) == ("opengl", ["flipbook", "opengl"])
    assert notes[0].startswith("Rendered with the OpenGL ROP because the Flipbook ROP crashed")

    tried, karma = [], []
    used, _, notes = run_capture_chain(
        chain,
        stage=False,
        source="auto",
        render_rop=attempt({"flipbook", "opengl"}, tried),
        render_karma=lambda: karma.append(1),
    )
    assert (used, tried, karma) == ("karma", ["flipbook", "opengl"], [1])
    assert "Karma" in notes[0] and "Flipbook ROP" in notes[0] and "OpenGL ROP" in notes[0]

    def refused(rop_type):
        raise ToolError("cook_failed", "The Flipbook ROP did not produce an image: x")

    with pytest.raises(ToolError) as err:
        run_capture_chain(chain, stage=False, source="auto", render_rop=refused, render_karma=None)
    assert err.value.code == "cook_failed"


def test_prune_captures_keeps_the_newest(tmp_path):
    import os

    from hocuspocus.host.tools.visual import prune_captures

    for i in range(7):
        path = tmp_path / f"c{i}.png"
        path.write_bytes(b"x")
        os.utime(path, (1000 + i, 1000 + i))
    assert prune_captures(tmp_path, keep=3) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c4.png", "c5.png", "c6.png"]


def test_crash_summary_keeps_the_crashing_thread_only():
    """Review 16 N1: a crashed child's 4 KB tail of idle thread stacks becomes the fatal
    error and the crashing thread's symbols, at most 600 characters."""
    from hocuspocus.host.tools.visual import CRASH_LOG_CHARS, crash_summary

    idle = "OTHER THREAD 7\n+0x7ffc [NtWaitForSingleObject] C:\\WINDOWS\\SYSTEM32\\ntdll.dll\n"
    log = (
        "36892: Fatal error: Segmentation fault\n-- TRACEBACK BEGIN --\n"
        "Traceback from hython 22.0.466\nCURRENT THREAD 62892\n"
        "+0x7ffc4fbd C:\\WINDOWS\\System32\\DriverStore\\nvoglv64.dll\n"
        "+0x989696e4 [RV_Instance::initializeDevice] C:\\PROGRA~1\\SIDEEF~1\\bin\\libRV.dll\n"
        + idle * 60
        + "-- TRACEBACK END --\n"
    )
    summary = crash_summary(log)
    assert summary.splitlines()[:4] == [
        "36892: Fatal error: Segmentation fault",
        "CURRENT THREAD 62892",
        "nvoglv64.dll",
        "RV_Instance::initializeDevice (libRV.dll)",
    ]
    assert "OTHER THREAD" not in summary and "NtWait" not in summary
    long = log.replace("CURRENT THREAD 62892\n", "CURRENT THREAD 1\n" + "+0x1 [f] a.dll\n" * 500)
    assert len(crash_summary(long)) == CRASH_LOG_CHARS
    assert crash_summary("x" * 5000) == "x" * CRASH_LOG_CHARS


def test_render_errors_say_each_line_once():
    """Review 16 N7: hou.OperationFailed and node.errors() repeat each other."""
    from hocuspocus.host.tools.visual import failure

    errors = [
        "The attempted operation failed.\nError:       Command Exit Code: 139\n"
        "             Failed to complete render: exit code 139\n"
        "Use a Log Viewer with External Render Processes enabled for more information.",
        "Command Exit Code: 139",
        "Failed to complete render: exit code 139\n"
        "Use a Log Viewer with External Render Processes enabled for more information.",
    ]
    message, detail = failure("/stage/rop failed to render frame 1", errors)
    assert message == "/stage/rop failed to render frame 1: Command Exit Code: 139"
    assert detail == {
        "errors": [
            "Failed to complete render: exit code 139",
            "Use a Log Viewer with External Render Processes enabled for more information.",
        ]
    }
    assert failure("x", ["The attempted operation failed."]) == (
        "x: The attempted operation failed.",
        {},
    )
    assert failure("x", []) == ("x: no output file", {})


def test_last_cook_memory_is_bounded(monkeypatch):
    from hocuspocus.host.tools import _diag

    monkeypatch.setattr(_diag, "_last_cook_ms", type(_diag._last_cook_ms)())
    for i in range(_diag.COOK_MEMORY + 50):
        _diag.remember_cook(i, float(i))
    assert len(_diag._last_cook_ms) == _diag.COOK_MEMORY
    assert 0 not in _diag._last_cook_ms and _diag.COOK_MEMORY + 49 in _diag._last_cook_ms
    _diag.remember_cook(60, 1.0)  # recooked: becomes the most recent
    assert next(reversed(_diag._last_cook_ms)) == 60


def test_thumbnail_luminance_is_measured_on_the_flattened_image(tmp_path):
    """Review 20 N1: a sparse subject on a transparent background is not nearly black; an
    empty frame says empty, and an opaque black frame is still nearly black."""
    Image = pytest.importorskip("PIL.Image")
    from hocuspocus.host.tools.visual import encode_png, thumbnail_note

    def measure(im) -> tuple[float | None, float | None]:
        path = tmp_path / "t.png"
        im.save(path)
        out = encode_png(str(path), 512, measure=True)
        return out.get("mean_luma"), out.get("coverage")

    sparse = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    sparse.paste((200, 200, 200, 255), (90, 40, 110, 60))  # a 2 % puff
    mean, coverage = measure(sparse)
    assert mean > 60 and coverage == pytest.approx(0.02)
    assert thumbnail_note(mean, coverage) is None

    empty = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    mean, coverage = measure(empty)
    assert coverage == 0.0
    assert "empty" in thumbnail_note(mean, coverage)

    black = Image.new("RGB", (200, 100), (2, 2, 2))
    mean, coverage = measure(black)
    assert coverage is None and mean < 8
    assert "nearly black" in thumbnail_note(mean, coverage)

    dark_opaque = Image.new("RGBA", (200, 100), (1, 1, 1, 255))
    assert "nearly black" in thumbnail_note(*measure(dark_opaque))


def test_render_outputs_listing_samples_long_sequences():
    """Review 20 N5: at most 5 outputs are listed; above that a summary, the first and
    last two, and at most 20 missing paths."""
    from hocuspocus.host.tools.visual import outputs_listing

    paths = [f"C:/r/s.{i:04d}.exr" for i in range(1, 49)]
    assert outputs_listing(paths[:5], []) == {"outputs": paths[:5]}
    many = outputs_listing(paths[:40], paths[40:])
    assert "outputs" not in many
    assert many["outputs_sample"] == [paths[0], paths[1], paths[38], paths[39]]
    assert many["outputs_summary"]["count"] == 40
    assert many["outputs_summary"]["missing_count"] == 8
    assert many["missing"] == paths[40:]
    none = outputs_listing([], paths)
    assert none["outputs"] == [] and len(none["missing"]) == 20


def test_resimulated_trusts_the_solve_stats_then_the_simulation_state():
    """Review 20 N3: a force-cook that reads a cached frame records no DOP solve time;
    without the performance monitor, the simulation's time moves on a cache read too, so
    only a memory change or no change at all is a reliable answer."""
    from hocuspocus.host.tools.cook import resimulated, solve_ms

    def state(time, memory):
        return {"time": time, "memory": memory}

    stepped = {"stats": {"0": {"3": {"Time": 106.5, "Solve": 106.5}}}}
    read = {"name": "Total Statistics", "stats": {}}
    assert resimulated(state(0.5, 9), state(0.1, 9), solve_ms(stepped)) is True
    assert resimulated(state(0.5, 9), state(0.1, 9), solve_ms(read)) is False
    assert resimulated(state(0.0, 1), state(0.5, 9), None) is True  # memory grew
    assert resimulated(state(0.2, 9), state(0.3, 8), None) is True  # stepped and evicted
    assert resimulated(state(0.5, 9), state(0.5, 9), None) is False  # nothing happened
    assert resimulated(state(0.5, 9), state(0.1, 9), None) is None  # cache read or step
    assert resimulated(None, state(0.1, 9), None) is None


def test_frames_print_as_integers_when_whole():
    from hocuspocus.host.tools.geo import frame_num

    assert frame_num(90.0) == 90 and isinstance(frame_num(90.0), int)
    assert frame_num(12.5) == 12.5
    assert f"frame {frame_num(1.0)}" == "frame 1"
    assert frame_num(float("nan")) == "nan"


def test_a_layer_whose_samples_shrank_or_moved_is_an_overwrite():
    """Review 24 N1: a second usd_rop rewrote a shared sopimport layer, 48 samples to 3."""
    from hocuspocus.host.tools.visual import overwrote_samples

    def row(n, codes=None):
        return {"time_samples": n, **({"time_codes": codes} if codes else {})}

    assert overwrote_samples(row(48, [1, 48]), row(3, [1, 3]))
    assert overwrote_samples(row(48, [1, 48]), row(48, [49, 96]))  # moved
    assert not overwrote_samples(row(48, [1, 48]), row(48, [1, 48]))  # the same render again
    assert not overwrote_samples(row(48, [1, 48]), row(96, [1, 96]))  # covers the old range
    assert not overwrote_samples(row(0), row(3, [1, 3]))  # nothing to lose


def test_layer_overwrites_mark_rows_and_name_the_other_rop():
    from hocuspocus.host.tools.visual import layer_overwrites

    shared = "C:/w/usd/collider_import.usd"
    layers = [
        {"path": "C:/w/usd/probe.usd", "bytes": 700, "time_samples": 0},
        {"path": shared, "bytes": 1838, "time_samples": 3, "time_codes": [1, 3]},
    ]
    before = {
        __import__("os").path.normcase(shared): {
            "path": shared,
            "time_samples": 48,
            "time_codes": [1, 48],
        }
    }
    notes = layer_overwrites(
        layers,
        before,
        {shared: ["/stage/export_usd"]},
        {shared: "/stage/collider_import"},
    )
    assert layers[1]["overwrote_samples"] == 48
    assert layers[1]["shared_with"] == ["/stage/export_usd"]
    assert "overwrote_samples" not in layers[0] and "shared_with" not in layers[0]
    assert notes == [
        "Overwrote collider_import.usd, which had 48 samples (1-48), with 3 samples (1-3); "
        "two ROPs share this layer path: /stage/export_usd also writes it (the save path of "
        "/stage/collider_import); re-render that ROP to restore its samples."
    ]
    # Shared but nothing lost yet (the first render): a warning, no overwrite mark.
    fresh = [dict(layers[1])]
    fresh[0].pop("overwrote_samples")
    warned = layer_overwrites(fresh, {}, {shared: ["/stage/export_usd"]}, {})
    assert "overwrote_samples" not in fresh[0]
    assert warned == [
        "/stage/export_usd also writes collider_import.usd: rendering either ROP replaces the "
        "other's time samples in it."
    ]
