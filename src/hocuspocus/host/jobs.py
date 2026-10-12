"""Host-side jobs for long operations. Stdlib only. See docs/BIBLE.md §7.

A job is a thread running a sequence of short main-thread steps: it calls ``hou`` only
through :meth:`JobContext.run_main` (the executor), checks :attr:`JobContext.cancelled`
between steps and reports progress. Jobs live in memory and do not survive a restart.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from hocuspocus.tools.errors import ToolError

log = logging.getLogger("hocuspocus.host.jobs")

JOB_NOT_FOUND_HINT = (
    "Jobs live in the Houdini process that started them and do not survive a Houdini "
    "restart; use job with action 'list' to see current jobs."
)


class JobContext:
    """Handed to a job function."""

    def __init__(self, job: Job, executor: Any, default_timeout_s: float) -> None:
        self._job = job
        self._executor = executor
        self._default_timeout_s = default_timeout_s

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise ToolError("cancelled", f"Job {self._job.id} was cancelled.")

    def run_main(self, fn: Callable[[], Any], timeout_s: float | None = None) -> Any:
        self.check_cancelled()
        return self._executor.run(fn, timeout_s or self._default_timeout_s)

    def progress(self, fraction: float | None = None, message: str | None = None) -> None:
        if fraction is not None:
            self._job.progress = max(0.0, min(1.0, float(fraction)))
        if message is not None:
            self._job.message = message


class Job:
    def __init__(self, tool: str, label: str = "") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.tool = tool
        self.label = label
        self.state = "running"  # running | done | failed | cancelled
        self.progress: float | None = None
        self.message: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.result: Any = None
        self.error: dict[str, Any] | None = None
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.done_event = threading.Event()

    def status(self) -> dict[str, Any]:
        end = self.finished or time.time()
        data: dict[str, Any] = {
            "job_id": self.id,
            "tool": self.tool,
            "state": self.state,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started)),
            "elapsed_s": round(end - self.started, 3),
        }
        if self.label:
            data["label"] = self.label
        if self.progress is not None:
            data["progress"] = self.progress
        if self.message:
            data["message"] = self.message
        if self.error is not None:
            data["error"] = self.error
        return data


class JobManager:
    def __init__(self, executor: Any, *, default_timeout_s: float = 30.0, keep: int = 100) -> None:
        self._executor = executor
        self._default_timeout_s = default_timeout_s
        self._keep = keep
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()

    def start(self, tool: str, fn: Callable[[JobContext], Any], *, label: str = "") -> Job:
        job = Job(tool, label)
        ctx = JobContext(job, self._executor, self._default_timeout_s)

        def runner() -> None:
            try:
                result = fn(ctx)
                if job.cancel_event.is_set():
                    job.state = "cancelled"
                else:
                    job.result = result
                    job.state = "done"
            except ToolError as exc:
                job.state = "cancelled" if exc.code == "cancelled" else "failed"
                job.error = exc.to_dict()
            except BaseException as exc:
                job.state = "failed"
                job.error = ToolError(
                    "internal",
                    f"{type(exc).__name__}: {exc}",
                    hou_exception=f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
                    detail={
                        "traceback": getattr(exc, "hp_traceback", None) or traceback.format_exc()
                    },
                ).to_dict()
            finally:
                job.finished = time.time()
                job.done_event.set()

        with self._lock:
            self._jobs[job.id] = job
            self._evict()
        job.thread = threading.Thread(target=runner, name=f"hocuspocus-job-{job.id}", daemon=True)
        job.thread.start()
        return job

    def _evict(self) -> None:
        finished = [jid for jid, j in self._jobs.items() if j.state != "running"]
        while len(self._jobs) > self._keep and finished:
            self._jobs.pop(finished.pop(0), None)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ToolError("job_not_found", f"No job with id {job_id!r}.", hint=JOB_NOT_FOUND_HINT)
        return job

    def status(self, job_id: str) -> dict[str, Any]:
        return self.get(job_id).status()

    def result(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        data = job.status()
        if job.state == "done":
            data["result"] = job.result
        return data

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job.state == "running":
            job.cancel_event.set()
            job.message = "cancellation requested"
        return job.status()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [job.status() for job in reversed(jobs)]

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
