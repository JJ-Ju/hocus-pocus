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


def test_last_cook_memory_is_bounded(monkeypatch):
    from hocuspocus.host.tools import _diag

    monkeypatch.setattr(_diag, "_last_cook_ms", type(_diag._last_cook_ms)())
    for i in range(_diag.COOK_MEMORY + 50):
        _diag.remember_cook(i, float(i))
    assert len(_diag._last_cook_ms) == _diag.COOK_MEMORY
    assert 0 not in _diag._last_cook_ms and _diag.COOK_MEMORY + 49 in _diag._last_cook_ms
    _diag.remember_cook(60, 1.0)  # recooked: becomes the most recent
    assert next(reversed(_diag._last_cook_ms)) == 60
