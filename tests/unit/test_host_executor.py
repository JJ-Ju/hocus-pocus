"""MainThreadExecutor with both backends, without hou: the scheduling primitive is faked."""

from __future__ import annotations

import threading
import time

import pytest

from hocuspocus.host.executor import MainThreadExecutor
from hocuspocus.tools.errors import ToolError


def _in_thread(fn):
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def _pump_until(executor, thread, timeout=5.0):
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        executor.pump_once(0.01)
    thread.join(0.1)
    assert not thread.is_alive()


@pytest.fixture
def headless():
    executor = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    executor.start()
    yield executor
    executor.stop()


def test_runs_inline_on_main_thread(headless):
    assert headless.on_main_thread()
    assert headless.run(lambda: threading.get_ident(), 1) == threading.get_ident()


def test_marshals_worker_calls_to_main_thread(headless):
    main = threading.get_ident()
    thread, box = _in_thread(lambda: headless.run(threading.get_ident, 5))
    _pump_until(headless, thread)
    assert box["value"] == main


def test_calls_are_serialised_in_order(headless):
    seen = []
    threads = []
    for i in range(5):
        t, _ = _in_thread(lambda i=i: headless.run(lambda: seen.append(i), 5))
        t.join(0.05)  # let each enqueue before the next
        threads.append(t)
    for t in threads:
        _pump_until(headless, t)
    assert seen == [0, 1, 2, 3, 4]


def test_exception_carries_main_thread_traceback(headless):
    def boom():
        raise ValueError("nope")

    thread, box = _in_thread(lambda: headless.run(boom, 5))
    _pump_until(headless, thread)
    exc = box["error"]
    assert isinstance(exc, ValueError)
    assert "boom" in exc.hp_traceback
    assert "ValueError: nope" in exc.hp_traceback


def test_timeout_before_start_cancels(headless):
    ran = []
    thread, box = _in_thread(lambda: headless.run(lambda: ran.append(1), 0.1))
    thread.join(2)  # nobody pumps
    error = box["error"]
    assert isinstance(error, ToolError) and error.code == "houdini_busy"
    assert error.detail["started"] is False
    assert error.to_dict()["retryable"] is True
    while headless.pump_once(0):
        pass
    assert ran == []  # cancelled work never runs


def test_timeout_after_start_still_completes(headless):
    """No timing race (review 10 section 5): the pump is already waiting when the work is
    queued, and the work holds the main thread until the caller has given up."""
    gave_up = threading.Event()
    done = []

    def slow():
        assert gave_up.wait(10)
        done.append(1)
        return "late"

    def caller():
        try:
            return headless.run(slow, 0.5)
        finally:
            gave_up.set()

    thread, box = _in_thread(caller)
    assert headless.pump_once(10) is True  # blocks until queued, then runs slow()
    thread.join(5)
    assert box["error"].code == "houdini_busy"
    assert box["error"].detail["started"] is True
    assert done == [1]


def test_work_finishing_at_the_timeout_returns_its_result(headless, monkeypatch):
    """Review 10 section 1.5: done between the wait timing out and the lock is a result."""
    from hocuspocus.host import executor as module

    class LateEvent(threading.Event):
        def wait(self, timeout=None):
            if timeout is None:
                return super().wait()
            super().wait()  # the work finishes ...
            return False  # ... but the caller's wait still reports a timeout

    original = module._Work.__init__

    def init(self, fn):
        original(self, fn)
        self.done = LateEvent()

    monkeypatch.setattr(module._Work, "__init__", init)
    thread, box = _in_thread(lambda: headless.run(lambda: "value", 0.1))
    assert headless.pump_once(10) is True
    thread.join(5)
    assert box == {"value": "value"}


def test_stopped_executor_reports_offline():
    executor = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    thread, box = _in_thread(lambda: executor.run(lambda: 1, 1))
    thread.join(2)
    assert box["error"].code == "houdini_offline"


def test_stop_fails_pending_work(headless):
    thread, box = _in_thread(lambda: headless.run(lambda: 1, 5))
    time.sleep(0.1)
    headless.stop()
    thread.join(2)
    assert box["error"].code == "houdini_offline"


def test_pump_forever_until_stop(headless):
    stop = threading.Event()
    thread, box = _in_thread(lambda: headless.run(lambda: "ok", 5))

    def stopper():
        thread.join(5)
        stop.set()

    threading.Thread(target=stopper, daemon=True).start()
    headless.pump_forever(stop, poll_s=0.01)
    assert box["value"] == "ok"


def test_post_is_fire_and_forget(headless):
    seen = []
    headless.post(lambda: seen.append("x"))
    assert headless.pump_once(0) is True
    assert seen == ["x"]


class FakeEventLoop:
    """Stands in for hou.ui.add/removeEventLoopCallback."""

    def __init__(self):
        self.callbacks = []

    def add(self, cb):
        self.callbacks.append(cb)

    def remove(self, cb):
        self.callbacks.remove(cb)

    def tick(self):
        for cb in list(self.callbacks):
            cb()


def test_gui_backend_drains_on_idle_ticks():
    loop = FakeEventLoop()
    executor = MainThreadExecutor(
        add_callback=loop.add, remove_callback=loop.remove, main_thread_ident=threading.get_ident()
    )
    executor.start()
    assert executor.backend == "gui"
    assert len(loop.callbacks) == 1
    main = threading.get_ident()
    thread, box = _in_thread(lambda: executor.run(threading.get_ident, 5))
    deadline = time.monotonic() + 5
    while thread.is_alive() and time.monotonic() < deadline:
        loop.tick()
        time.sleep(0.005)
    assert box["value"] == main
    executor.stop()
    assert loop.callbacks == []


def test_gui_callback_is_not_reentrant():
    loop = FakeEventLoop()
    executor = MainThreadExecutor(
        "gui",
        add_callback=loop.add,
        remove_callback=loop.remove,
        main_thread_ident=threading.get_ident(),
    )
    executor.start()
    order = []

    def outer():
        order.append("outer-start")
        loop.tick()  # a HOM call pumping the event loop must not start the next item
        order.append("outer-end")

    executor.post(outer)
    executor.post(lambda: order.append("inner"))
    loop.tick()
    assert order[:2] == ["outer-start", "outer-end"]
    assert order == ["outer-start", "outer-end", "inner"]
    executor.stop()


def test_gui_timeout_when_loop_is_blocked():
    loop = FakeEventLoop()
    executor = MainThreadExecutor(
        add_callback=loop.add, remove_callback=loop.remove, main_thread_ident=threading.get_ident()
    )
    executor.start()
    thread, box = _in_thread(lambda: executor.run(lambda: 1, 0.1))
    thread.join(2)  # no ticks: a modal dialog, say
    assert box["error"].code == "houdini_busy"
    executor.stop()


def test_auto_backend_without_hou_is_headless():
    executor = MainThreadExecutor(main_thread_ident=threading.get_ident())
    executor.start()
    assert executor.backend == "headless"
    executor.stop()
