"""A long press goes on as a job past its call's wait (BIBLE D70, review 26 P3 friction 1).

A pressed parm's callback is one main-thread call that cannot be split or interrupted. A
call whose work marked such a step (``mark_long_step``) and is still running at
``job_threshold_s`` returns ``{job_id, state: "running"}``; the job's result is the call's
result, its error the call's error. Plain CPython: the main thread is the test's own,
pumped while the call waits on a worker thread.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time

import pytest

from hocuspocus.host.config import HostConfig
from hocuspocus.host.dispatch import AFTER_KEY, Dispatcher
from hocuspocus.host.executor import MainThreadExecutor, Pending, mark_long_step
from hocuspocus.host.jobs import JobManager
from hocuspocus.host.tools.registry import HostContext, HostTool, SceneState
from hocuspocus.host.undo import UndoHistory
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


def _in_thread(fn):
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def _pump(executor, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        executor.pump_once(0.01)
    assert until()


@pytest.fixture
def executor():
    ex = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    ex.start()
    yield ex
    ex.stop()


def _press(seconds, *, fail=False):
    def work():
        mark_long_step("/obj/tower/export_all")
        time.sleep(seconds)
        if fail:
            raise ToolError("cook_failed", "export_all wrote 0 of 4 files.")
        return {"pressed": True}

    return work


# -- the executor ------------------------------------------------------------------------


def test_a_long_step_past_its_wait_is_handed_back_pending(executor):
    thread, box = _in_thread(lambda: executor.run_adoptable(_press(0.5), 5.0, 0.1))
    _pump(executor, lambda: not thread.is_alive())
    pending = box["value"]
    assert isinstance(pending, Pending) and pending.long_step == "/obj/tower/export_all"
    assert pending.wait(5) and pending.outcome() == {"pressed": True}


def test_a_short_press_stays_synchronous(executor):
    thread, box = _in_thread(lambda: executor.run_adoptable(_press(0.01), 5.0, 1.0))
    _pump(executor, lambda: not thread.is_alive())
    assert box["value"] == {"pressed": True}


def test_without_a_long_step_the_timeout_is_still_houdini_busy(executor):
    thread, box = _in_thread(lambda: executor.run_adoptable(lambda: time.sleep(0.4), 0.2, 0.1))
    _pump(executor, lambda: not thread.is_alive())
    assert box["error"].code == "houdini_busy" and box["error"].detail["started"] is True


def test_a_long_step_marked_after_the_first_wait_is_followed_at_the_timeout(executor):
    def late():
        time.sleep(0.25)
        mark_long_step("/obj/tower/bake")
        time.sleep(0.4)
        return 1

    thread, box = _in_thread(lambda: executor.run_adoptable(late, 0.4, 0.1))
    _pump(executor, lambda: not thread.is_alive())
    assert isinstance(box["value"], Pending)
    assert box["value"].wait(5) and box["value"].outcome() == 1


def test_a_call_queued_behind_a_followed_press_names_it(executor):
    first, box = _in_thread(lambda: executor.run_adoptable(_press(0.8), 5.0, 0.05))

    def queued_behind():
        while "value" not in box:
            time.sleep(0.01)
        box["value"].job_id = "4242-abc"  # what the dispatcher does with the Pending
        return executor.run(lambda: "late", 0.2)

    second, other = _in_thread(queued_behind)
    executor.pump_once(1.0)  # the press holds the main thread for 0.8 s
    second.join(3)
    first.join(1)
    executor.pump_once(0)  # the cancelled second call is skipped
    error = other["error"]
    assert error.code == "houdini_busy" and error.detail["started"] is False
    assert error.detail["running"] == "/obj/tower/export_all"
    assert error.detail["job_id"] == "4242-abc" and "job {action: status" in error.hint


def test_mark_long_step_outside_a_queued_call_does_nothing():
    mark_long_step("/obj/nowhere")  # no work executing: no error, nothing marked


# -- the dispatcher ----------------------------------------------------------------------


def _dispatcher(executor, tool_fn, threshold=0.1):
    @contextlib.contextmanager
    def group(label):
        yield

    config = HostConfig()
    config.job_threshold_s = threshold
    ctx = HostContext(
        config=config,
        executor=executor,
        logger=logging.getLogger("test"),
        scene=SceneState(generation=1),
        jobs=JobManager(executor),
        undo=UndoHistory(),
    )
    tool = HostTool("parm_set", tool_fn, read_only=False)
    return Dispatcher(ctx, {"parm_set": tool}.get, undo_group=group), ctx


def _call(executor, dispatcher, args=None):
    thread, box = _in_thread(lambda: dispatcher.call("parm_set", args or {}, timeout_s=30))
    _pump(executor, lambda: not thread.is_alive())
    return box["value"]


def _finish(executor, ctx, job_id):
    job = ctx.jobs.get(job_id)
    _pump(executor, job.done_event.is_set)
    return ctx.jobs.result(job_id)


def test_a_long_press_returns_a_job_whose_result_is_the_calls(executor):
    def tool(args, ctx):
        out = _press(0.5)()

        def after(result, remaining):
            return {**result, "cooked": remaining > 0}

        return {"items": [out], AFTER_KEY: after}

    dispatcher, ctx = _dispatcher(executor, tool)
    envelope = _call(executor, dispatcher)
    assert envelope["ok"], envelope
    result = envelope["result"]
    assert result["state"] == "running" and result["running"] == "/obj/tower/export_all"
    assert "job {action: result, job_id}" in result["message"]
    assert envelope["_meta"]["undo_label"] == "HocusPocus: parm_set"
    status = ctx.jobs.status(result["job_id"])
    assert status["tool"] == "parm_set" and status["label"] == "/obj/tower/export_all"
    done = _finish(executor, ctx, result["job_id"])
    assert done["state"] == "done"
    assert done["result"] == {"items": [{"pressed": True}], "dirty": True, "cooked": True}


def test_a_short_press_answers_in_the_call(executor):
    dispatcher, _ctx = _dispatcher(executor, lambda args, ctx: _press(0.01)(), threshold=5.0)
    envelope = _call(executor, dispatcher)
    assert envelope["result"] == {"pressed": True, "dirty": True}


def test_a_failed_long_press_is_the_jobs_error(executor):
    dispatcher, ctx = _dispatcher(executor, lambda args, ctx: _press(0.4, fail=True)())
    result = _call(executor, dispatcher)["result"]
    done = _finish(executor, ctx, result["job_id"])
    assert done["state"] == "failed" and done["error"]["code"] == "cook_failed"


def test_a_followed_press_cannot_be_cancelled(executor):
    dispatcher, ctx = _dispatcher(executor, lambda args, ctx: _press(0.5)())
    result = _call(executor, dispatcher)["result"]
    answer = ctx.jobs.cancel(result["job_id"])
    assert answer["cancelled"] is False and "cannot be interrupted" in answer["notes"][0]
    assert _finish(executor, ctx, result["job_id"])["state"] == "done"


def test_the_long_work_hint_names_what_each_profile_takes():
    """2.1 (D75): the started-call hint said "raise timeout_s, or use a job" to look, which
    took neither; it now names the tools the profile serves and what each takes."""
    from hocuspocus.host.executor import long_work_hint
    from hocuspocus.tools.migration import using_profile

    with using_profile("core"):
        core = long_work_hint()
    with using_profile("minimal"):
        minimal = long_work_hint()
    assert core.startswith("Inspect the scene before repeating a mutation.")
    assert "cook, render and look run long work as a job (wait_s" in core
    assert "houdini_python takes timeout_s" in core
    assert "cook" not in minimal and "look runs long work as a job" in minimal
