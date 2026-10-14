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
    __slots__ = ("fn", "done", "lock", "state", "result", "exc", "queued", "started", "finished")

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


def _busy(timeout_s: float, *, started: bool) -> ToolError:
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
            f"Houdini's main thread was busy for {timeout_s:g}s (a modal dialog, a "
            "long cook, or another call); the call was not started."
        )
        hint = "Retry shortly; the call had no effect."
    return ToolError(
        "houdini_busy", message, hint=hint, detail={"started": started, "timeout_s": timeout_s}
    )


class MainThreadExecutor:
    """Marshal callables onto the main thread with a bounded wait."""

    def __init__(
        self,
        backend: Backend = "auto",
        *,
        add_callback: Callable[[Callable[[], None]], Any] | None = None,
        remove_callback: Callable[[Callable[[], None]], Any] | None = None,
        main_thread_ident: int | None = None,
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
        self.work_wrapper: Callable[[Callable[[], Any]], Any] | None = None
        """Runs each queued callable (``wrapper(fn)``) when set: the ``events`` hooks use it
        to tell HocusPocus's own scene changes from the user's."""

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
        if not self._running:
            raise ToolError(
                "houdini_offline",
                "The HocusPocus host is not running.",
                hint="Restart the host (hocuspocus.host.start()) or call houdini_connect.",
            )
        work = _Work(fn)
        meter = current_meter()
        self._queue.put(work)
        if not work.done.wait(timeout_s):
            with work.lock:
                state = work.state
                if state == "pending":
                    work.state = "cancelled"
            if state != "done":
                raise _busy(timeout_s, started=state != "pending")
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
        self._current_started = work.started = time.monotonic()
        try:
            work.result = work.fn() if wrapper is None else wrapper(work.fn)
        except BaseException as exc:  # transported to the caller
            work.exc = exc
            with contextlib.suppress(Exception):  # exceptions that reject attributes
                exc.hp_traceback = traceback.format_exc()  # type: ignore[attr-defined]
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                reraise = exc
        finally:
            work.finished = time.monotonic()
            self._current_started = None
            with work.lock:
                work.state = "done"
            work.done.set()
        if reraise is not None:
            raise reraise
