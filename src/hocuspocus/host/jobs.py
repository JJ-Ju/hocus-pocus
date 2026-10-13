"""Host-side jobs for long operations. Stdlib only. See docs/BIBLE.md §7.

A job is a thread running a sequence of short main-thread steps: it calls ``hou`` only
through :meth:`JobContext.run_main` (the executor), checks :attr:`JobContext.cancelled`
between steps and reports progress. Jobs live in memory and do not survive a restart.

Job ids are ``<pid>-<hex>`` (1.3, review 19 papercut 3): the bridge routes ``job`` calls to
the Houdini whose pid prefixes the id, whichever instance is selected. A bare ``<hex>``
still finds a job of this process.
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
    "Jobs live in the Houdini process that started them (the pid before the '-' in the id) "
    "and do not survive a Houdini restart; use job with action 'list' to see this "
    "Houdini's jobs, or {action: 'list', all: true} for every running Houdini's."
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

    def set_progress(self, current: int, total: int, message: str | None = None) -> None:
        """Report step ``current`` of ``total`` (see :meth:`Job.set_progress`)."""
        self._job.set_progress(current, total, message)

    def set_extra(self, key: str, value: Any) -> None:
        """Add a tool-specific field to the job status (``pdg``: ``nodes``)."""
        self._job.extra[key] = value


class Job:
    def __init__(self, tool: str, label: str = "", prefix: str = "") -> None:
        token = uuid.uuid4().hex[:12]
        self.id = f"{prefix}-{token}" if prefix else token
        self.tool = tool
        self.label = label
        self.state = "running"  # running | done | failed | cancelled
        self.progress: float | None = None  # 0..1
        self.current: int | None = None  # steps finished
        self.total: int | None = None  # steps in all
        self.message: str | None = None
        self.extra: dict[str, Any] = {}
        """Tool-specific status fields (never the standard keys)."""
        self.started = time.time()
        self.finished: float | None = None
        self.result: Any = None
        self.error: dict[str, Any] | None = None
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.done_event = threading.Event()

    def set_progress(self, current: int, total: int, message: str | None = None) -> None:
        """Record ``current`` of ``total`` steps finished; ``progress`` is their ratio.

        ``total`` of 0 or less leaves ``progress`` unknown but still records the counts.
        """
        current = max(0, int(current))
        total = int(total)
        self.current = current
        self.total = total
        if total > 0:
            self.progress = max(0.0, min(1.0, current / total))
        if message is not None:
            self.message = message

    def status(self) -> dict[str, Any]:
        """The job snapshot. ``progress`` (0..1), ``current``, ``total`` and ``message``
        appear once the job has reported them."""
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
            data["progress"] = round(self.progress, 4)
        if self.current is not None:
            data["current"] = self.current
        if self.total is not None:
            data["total"] = self.total
        if self.message:
            data["message"] = self.message
        for key, value in self.extra.items():
            data.setdefault(key, value)
        if self.error is not None:
            data["error"] = self.error
        return data


class JobManager:
    def __init__(
        self,
        executor: Any,
        *,
        default_timeout_s: float = 30.0,
        keep: int = 100,
        id_prefix: str = "",
    ) -> None:
        self._executor = executor
        self._prefix = id_prefix
        """Prepended to job ids as ``<prefix>-``: the host's pid (1.3)."""
        self._default_timeout_s = default_timeout_s
        self._keep = keep
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()

    def start(self, tool: str, fn: Callable[[JobContext], Any], *, label: str = "") -> Job:
        job = Job(tool, label, self._prefix)
        ctx = JobContext(job, self._executor, self._default_timeout_s)

        def runner() -> None:
            try:
                result = fn(ctx)
                if job.cancel_event.is_set():
                    job.state = "cancelled"
                    job.message = "cancelled"
                else:
                    job.result = result
                    if job.progress is not None:
                        job.progress = 1.0
                    if job.total is not None and job.total > 0:
                        job.current = job.total
                    job.state = "done"
            except ToolError as exc:
                job.state = "cancelled" if exc.code == "cancelled" else "failed"
                job.error = exc.to_dict()
                if job.state == "cancelled":
                    job.message = "cancelled"
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
            if job is None and self._prefix and "-" not in job_id:
                job = self._jobs.get(f"{self._prefix}-{job_id}")  # a bare id of this process
        if job is None:
            owner, dash, _rest = job_id.partition("-")
            if dash and owner.isdigit() and self._prefix and owner != self._prefix:
                raise ToolError(
                    "job_not_found",
                    f"Job {job_id!r} was started by Houdini pid {owner}; this is pid "
                    f"{self._prefix}.",
                    hint="The bridge sends job calls to the Houdini that started the job; "
                    f"if pid {owner} has exited, its jobs are gone.",
                )
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

    def running_count(self) -> int:
        """How many jobs are still running (``/health`` ``jobs_running``)."""
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.state == "running")

    def discard(self, job_id: str) -> bool:
        """Forget a finished job (e.g. one whose result was returned synchronously).

        Running jobs are kept so they can still be polled or cancelled. Returns whether
        the job was removed.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state == "running":
                return False
            del self._jobs[job_id]
            return True

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [job.status() for job in reversed(jobs)]

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
