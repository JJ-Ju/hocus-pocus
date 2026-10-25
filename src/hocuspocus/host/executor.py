"""Run callables on Houdini's main thread. Stdlib only. See docs/BIBLE.md §3.2.

One class, two backends:

* ``gui``: a ``hou.ui.addEventLoopCallback`` pump drains the queue on idle ticks
  (what ``hdefereval`` is built on, without its missing timeout, main-thread deadlock
  and lost tracebacks).
* ``headless``: the main thread *is* the pump; the owner calls :meth:`pump_forever`
  (``hython -m hocuspocus.host``) or :meth:`pump_once` (tests).

Requests are serialised: the main thread executes one callable at a time.
The scheduling primitive is injectable so both backends are unit-testable without ``hou``.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import logging
import queue
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from typing import Any, Literal

from hocuspocus.tools.errors import ToolError

Backend = Literal["auto", "gui", "headless"]

log = logging.getLogger("hocuspocus.host.executor")

_GUI_DRAIN_BUDGET_S = 0.05


class MainThreadMeter:
    """Main-thread time spent on behalf of one call that runs off the main thread (review
    24 N5: ``render``, ``cook`` and ``job`` reported ``main_thread_ms: 0`` even for a 1.9 s
    profile cook). Every :meth:`MainThreadExecutor.run` made from a thread the meter is
    bound to (:func:`metering`), including the threads of jobs the call starts
    (:class:`~hocuspocus.host.jobs.JobManager`), adds the step's run and queue time while
    the meter is open; the dispatcher closes it when the call returns, so job steps that
    finish later do not count."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = True
        self.main_s = 0.0
        self.queue_s = 0.0
        self.steps = 0

    def add(self, main_s: float, queue_s: float) -> None:
        with self._lock:
            if self._open:
                self.main_s += max(0.0, main_s)
                self.queue_s += max(0.0, queue_s)
                self.steps += 1

    def close(self) -> dict[str, float | int]:
        """Stop counting and return ``{main_s, queue_s, steps}``."""
        with self._lock:
            self._open = False
            return {"main_s": self.main_s, "queue_s": self.queue_s, "steps": self.steps}


_METER = threading.local()


def current_meter() -> MainThreadMeter | None:
    """The meter bound to this thread, if any."""
    return getattr(_METER, "meter", None)


@contextlib.contextmanager
def metering(meter: MainThreadMeter | None) -> Iterator[None]:
    """Bind ``meter`` to this thread for the block (None unbinds)."""
    previous = current_meter()
    _METER.meter = meter
    try:
        yield
    finally:
        _METER.meter = previous


class _Work:
    __slots__ = (
        "fn", "done", "lock", "state", "result", "exc", "queued", "started", "finished",
        "long_step", "job_id",
    )  # fmt: skip

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.started: float | None = None
        self.finished: float | None = None
        self.queued = time.monotonic()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.state = "pending"  # pending | running | done | cancelled
        self.result: Any = None
        self.exc: BaseException | None = None
        self.long_step: str | None = None
        """What the callable said it is running that may outlast its caller's wait (a
        press: the parm path), set from the main thread by :func:`mark_long_step`."""
        self.job_id: str | None = None
        """The job that follows this callable once its caller stopped waiting
        (:class:`Pending`)."""


_EXECUTING = threading.local()
"""The :class:`_Work` the main thread is executing now (``work``), for
:func:`mark_long_step`."""


def mark_long_step(label: str) -> None:
    """Say, from the main thread, that the queued call running now has started a step
    that cannot be split and may outlast its caller's wait: a pressed parm's callback (an
    HDA's export button ran 3-4 min in review 26 P3). A caller that used
    :meth:`MainThreadExecutor.run_adoptable` then gets a :class:`Pending` instead of
    ``houdini_busy`` and follows the call as a job (BIBLE D70). No-op outside a queued
    callable (an inline call on the main thread)."""
    work = getattr(_EXECUTING, "work", None)
    if work is not None:
        work.long_step = label


class Pending:
    """A started main-thread call that marked a long step (:func:`mark_long_step`) and
    outlasted its caller's wait: it still runs, and :meth:`outcome` returns its result
    (or raises its exception) once it is done."""

    def __init__(self, work: _Work) -> None:
        self._work = work

    @property
    def long_step(self) -> str | None:
        return self._work.long_step

    @property
    def job_id(self) -> str | None:
        return self._work.job_id

    @job_id.setter
    def job_id(self, value: str | None) -> None:
        self._work.job_id = value

    def wait(self, timeout_s: float | None = None) -> bool:
        return self._work.done.wait(timeout_s)

    def outcome(self) -> Any:
        self._work.done.wait()
        if self._work.exc is not None:
            raise self._work.exc
        return self._work.result


def _busy(timeout_s: float, *, started: bool, running: _Work | None = None) -> ToolError:
    detail: dict[str, Any] = {"started": started, "timeout_s": timeout_s}
    step = running.long_step if running is not None and not started else None
    if step:
        # The main thread is in a long step another call started (a press) that a job
        # follows: say so, so the agent polls that job instead of retrying blindly.
        detail["running"] = step
        if running is not None and running.job_id:
            detail["job_id"] = running.job_id
        return ToolError(
            "houdini_busy",
            f"Houdini's main thread is busy running {step} for another call; this call was "
            "not started.",
            hint="Retry once it ends: the call had no effect"
            + (
                "; job {action: status, job_id} with detail.job_id says when it is done."
                if detail.get("job_id")
                else "."
            ),
            detail=detail,
        )
    if started:
        message = (
            f"Houdini's main thread did not finish the call within {timeout_s:g}s. "
            "The call is still running; its result will be discarded."
        )
        hint = (
            "Inspect the scene before repeating a mutation. Raise timeout_s for long "
            "operations, or use a job."
        )
    else:
        message = (
            f"Houdini's main thread was busy for {timeout_s:g}s (a dialog open in "
            "Houdini, a long cook, or another call); the call was not started."
        )
        # Measured (docs/parity.md G5): nothing HocusPocus runs while a user's modal
        # dialog is open; HocusPocus refuses dialogs of its own during a call.
        hint = (
            "Retry shortly; the call had no effect. If it keeps happening, ask the user to "
            "close any dialog open in Houdini."
        )
    return ToolError("houdini_busy", message, hint=hint, detail=detail)


class MainThreadExecutor:
    """Marshal callables onto the main thread with a bounded wait."""

    def __init__(
        self,
        backend: Backend = "auto",
        *,
        add_callback: Callable[[Callable[[], None]], Any] | None = None,
        remove_callback: Callable[[Callable[[], None]], Any] | None = None,
        main_thread_ident: int | None = None,
        modal_guard: Callable[[], contextlib.AbstractContextManager[Any]] | None = None,
    ) -> None:
        self._queue: queue.Queue[_Work] = queue.Queue()
        self._add_callback = add_callback
        self._remove_callback = remove_callback
        self._requested_backend = backend
        self.backend: Literal["gui", "headless"] = "headless"
        self.main_thread_ident: int | None = main_thread_ident
        self._running = False
        self._draining = False
        self._current_started: float | None = None
        """When the callable running on the main thread now started (``busy_s``)."""
        self._current_work: _Work | None = None
        """The callable running on the main thread now (its long step, for the
        ``houdini_busy`` of a call that waited behind it)."""
        self.work_wrapper: Callable[[Callable[[], Any]], Any] | None = None
        """Runs each queued callable (``wrapper(fn)``) when set: the ``events`` hooks use it
        to tell HocusPocus's own scene changes from the user's."""
        self.modal_guard = modal_guard
        """Entered around each queued callable when set (``guard()`` is a context
        manager). The GUI backend on a real ``hou`` sets it to the modal ``hou.ui`` stubs
        (:mod:`hocuspocus.host.modal`, docs/parity.md G5)."""

    # -- lifecycle ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Choose the backend and begin accepting work. Idempotent."""
        if self._running:
            return
        if self.main_thread_ident is None:
            # Inside Houdini the interpreter's main thread is Houdini's main thread.
            self.main_thread_ident = threading.main_thread().ident
        self.backend = self._resolve_backend()
        if self.backend == "gui":
            if self._add_callback is None:
                import hou

                self._add_callback = hou.ui.addEventLoopCallback
                self._remove_callback = hou.ui.removeEventLoopCallback
                if self.modal_guard is None:
                    from .modal import ModalStubs

                    self.modal_guard = ModalStubs().active
            self._add_callback(self._on_idle)
        self._running = True
        log.debug("executor started (%s backend)", self.backend)

    def stop(self) -> None:
        """Stop accepting work and fail anything still queued. Idempotent."""
        if not self._running:
            return
        self._running = False
        if self.backend == "gui" and self._remove_callback is not None:
            try:
                self._remove_callback(self._on_idle)
            except Exception:  # pragma: no cover - Houdini may already be tearing down
                log.debug("removeEventLoopCallback failed", exc_info=True)
        while True:
            try:
                work = self._queue.get_nowait()
            except queue.Empty:
                break
            with work.lock:
                if work.state == "pending":
                    work.state = "cancelled"
                    work.exc = ToolError("houdini_offline", "The HocusPocus host stopped.")
                    work.done.set()

    def _resolve_backend(self) -> Literal["gui", "headless"]:
        if self._requested_backend == "gui":
            return "gui"
        if self._requested_backend == "headless":
            return "headless"
        if self._add_callback is not None:
            return "gui"
        try:
            import hou

            return "gui" if hou.isUIAvailable() else "headless"
        except ImportError:
            return "headless"

    def busy_s(self) -> float:
        """Seconds the main thread has been held: by the callable running now, or (a modal
        dialog, a long user cook) the oldest one still waiting. 0.0 when idle."""
        now = time.monotonic()
        ages = []
        started = self._current_started
        if started is not None:
            ages.append(now - started)
        with self._queue.mutex:
            if self._queue.queue:
                ages.append(now - self._queue.queue[0].queued)
        return max(ages, default=0.0)

    # -- submission --------------------------------------------------------------

    def on_main_thread(self) -> bool:
        ident = self.main_thread_ident or threading.main_thread().ident
        return threading.get_ident() == ident

    def run(self, fn: Callable[[], Any], timeout_s: float) -> Any:
        """Execute ``fn`` on the main thread and return its result.

        Runs inline when already on the main thread. Raises ``ToolError("houdini_busy")``
        when the main thread does not finish within ``timeout_s``: work that had not
        started is cancelled; work that had started still completes and its result is
        discarded. Exceptions raised by ``fn`` are re-raised here with the main-thread
        traceback text attached as ``exc.hp_traceback``.
        """
        if self.on_main_thread():
            return fn()
        return self._submit(fn, timeout_s, None)

    def run_adoptable(self, fn: Callable[[], Any], timeout_s: float, adopt_after: float) -> Any:
        """:meth:`run`, except that a started callable that marked a long step
        (:func:`mark_long_step`) and is still running ``adopt_after`` seconds in, or at
        ``timeout_s``, is returned as a :class:`Pending` instead of failing with
        ``houdini_busy``: the dispatcher follows it as a job (BIBLE D70). Without a long
        step the wait and the refusal are :meth:`run`'s."""
        if self.on_main_thread():
            return fn()
        return self._submit(fn, timeout_s, max(0.0, min(adopt_after, timeout_s)))

    def _submit(self, fn: Callable[[], Any], timeout_s: float, adopt_after: float | None) -> Any:
        if not self._running:
            raise ToolError(
                "houdini_offline",
                "The HocusPocus host is not running.",
                hint="Restart the host (hocuspocus.host.start()) or call houdini_connect.",
            )
        # The caller's context (the call's hint profile, hocuspocus.tools.migration) goes
        # with the callable to the main thread.
        work = _Work(functools.partial(contextvars.copy_context().run, fn))
        meter = current_meter()
        self._queue.put(work)
        waits = [timeout_s] if adopt_after is None else [adopt_after, timeout_s - adopt_after]
        finished = False
        for wait in waits:
            if work.done.wait(max(0.0, wait)):
                finished = True
                break
            if adopt_after is not None:
                with work.lock:
                    adopt = work.state == "running" and work.long_step is not None
                if adopt:
                    return Pending(work)
        if not finished:
            with work.lock:
                state = work.state
                if state == "pending":
                    work.state = "cancelled"
            if state != "done":
                raise _busy(timeout_s, started=state != "pending", running=self._current_work)
            # It finished between the wait timing out and the lock (review 10 section 1.5):
            # report its result, not "still running".
            work.done.wait()
        if meter is not None and work.started is not None and work.finished is not None:
            meter.add(work.finished - work.started, work.started - work.queued)
        if work.exc is not None:
            raise work.exc
        return work.result

    def post(self, fn: Callable[[], Any]) -> None:
        """Queue ``fn`` for the main thread without waiting (fire and forget)."""
        self._queue.put(_Work(fn))

    # -- pumping -----------------------------------------------------------------

    def pump_once(self, timeout_s: float = 0.0) -> bool:
        """Execute at most one queued callable. Returns True when one ran.

        Must be called on the main thread (headless backend, or tests).
        """
        try:
            work = self._queue.get(timeout=timeout_s) if timeout_s > 0 else self._queue.get_nowait()
        except queue.Empty:
            return False
        self._execute(work)
        return True

    def pump_forever(self, stop_event: threading.Event, poll_s: float = 0.05) -> None:
        """Headless main loop: drain the queue until ``stop_event`` is set."""
        while not stop_event.is_set():
            self.pump_once(poll_s)
        # Drain whatever arrived before shutdown so no caller waits for its timeout.
        while self.pump_once(0.0):
            pass

    def _on_idle(self) -> None:
        """GUI event-loop callback. Not re-entrant: a nested event loop skips draining."""
        if self._draining:
            return
        self._draining = True
        try:
            deadline = time.monotonic() + _GUI_DRAIN_BUDGET_S
            while time.monotonic() < deadline:
                try:
                    work = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._execute(work)
        finally:
            self._draining = False

    def _execute(self, work: _Work) -> None:
        with work.lock:
            if work.state != "pending":
                return
            work.state = "running"
        reraise: BaseException | None = None
        wrapper = self.work_wrapper
        guard = self.modal_guard
        self._current_started = work.started = time.monotonic()
        self._current_work = work
        previous = getattr(_EXECUTING, "work", None)
        _EXECUTING.work = work
        try:
            with guard() if guard is not None else contextlib.nullcontext():
                work.result = work.fn() if wrapper is None else wrapper(work.fn)
        except BaseException as exc:  # transported to the caller
            work.exc = exc
            with contextlib.suppress(Exception):  # exceptions that reject attributes
                exc.hp_traceback = traceback.format_exc()  # type: ignore[attr-defined]
            # A refused modal dialog (host/modal.py) is a ToolError that is also a
            # SystemExit: transported to the caller like any tool error, never re-raised.
            if isinstance(exc, KeyboardInterrupt | SystemExit) and not isinstance(exc, ToolError):
                reraise = exc
        finally:
            work.finished = time.monotonic()
            _EXECUTING.work = previous
            self._current_started = None
            self._current_work = None
            with work.lock:
                work.state = "done"
            work.done.set()
        if reraise is not None:
            raise reraise
