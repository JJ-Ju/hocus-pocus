"""Host job ids carry the pid of the Houdini that started them (review 19 papercut 3)."""

from __future__ import annotations

import pytest

from hocuspocus.host.jobs import JobManager
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


class InlineExecutor:
    def run(self, fn, timeout_s):
        return fn()


def _done(manager: JobManager) -> str:
    job = manager.start("cook", lambda ctx: {"ok": True})
    job.done_event.wait(5)
    return job.id


def test_job_ids_are_prefixed_with_the_pid():
    manager = JobManager(InlineExecutor(), id_prefix="61900")
    job_id = _done(manager)
    pid, dash, token = job_id.partition("-")
    assert (pid, dash) == ("61900", "-") and len(token) == 12
    assert manager.status(job_id)["job_id"] == job_id
    assert manager.result(job_id)["result"] == {"ok": True}


def test_a_bare_id_still_finds_a_job_of_this_process():
    manager = JobManager(InlineExecutor(), id_prefix="61900")
    job_id = _done(manager)
    assert manager.status(job_id.split("-", 1)[1])["job_id"] == job_id


def test_another_pids_job_says_which_houdini_started_it():
    manager = JobManager(InlineExecutor(), id_prefix="3084")
    with pytest.raises(ToolError) as info:
        manager.status("61900-9c3e6f7ca53e")
    assert info.value.code == "job_not_found"
    assert "pid 61900" in info.value.message and "pid 3084" in info.value.message


def test_unprefixed_manager_keeps_bare_ids_and_counts_running_jobs():
    manager = JobManager(InlineExecutor())
    job_id = _done(manager)
    assert "-" not in job_id
    assert manager.running_count() == 0
    with pytest.raises(ToolError) as info:
        manager.status("nope")
    assert "pid before the '-'" in (info.value.hint or "")
