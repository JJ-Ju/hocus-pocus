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
    assert len(make_label("t", {"path": "/" + "a" * 500})) <= 120
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
