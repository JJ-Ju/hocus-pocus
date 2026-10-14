"""The bridge ledger (spec-2.0 §3): SQLite CRUD for instances, jobs and launches, the
reconcile with the registry, result spilling, and the bridge hooks that feed it (jobs a
call started, the progress poller, a restarted bridge's ``instance_lost``)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.ledger import (
    LEDGER_FILE,
    SPILL_BYTES,
    Ledger,
    default_role,
    is_ledger_id,
)
from hocuspocus.bridge.server import Bridge

pytestmark = pytest.mark.unit

GUI = Instance(
    pid=3084, port=51000, token="t-gui", ui=True, hip="C:/work/a.hip",
    started="2026-10-12T10:00:00Z", label="houdinifx",
)  # fmt: skip
WORKER = Instance(
    pid=61900, port=51001, token="t-w", ui=False, hip="C:/work/b.hip",
    started="2026-10-12T11:00:00Z", label="hython",
)  # fmt: skip


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))


@pytest.fixture
def ledger(tmp_path):
    led = Ledger.at(tmp_path / "state")
    yield led
    led.close()


def test_file_is_wal_sqlite_in_the_state_dir(tmp_path, ledger):
    assert (tmp_path / "state" / LEDGER_FILE).is_file()
    assert ledger.journal_mode.lower() == "wal"
    memory = Ledger()
    assert memory.path is None and memory.jobs_dir is None


def test_unopenable_file_falls_back_to_memory(tmp_path):
    blocker = tmp_path / "state"
    blocker.write_text("not a directory", encoding="utf-8")
    led = Ledger.at(blocker)
    assert led.path is None
    led.observe([GUI])
    assert led.instance(GUI.pid)["label"] == "houdinifx"


def test_default_roles():
    assert default_role(True) == "editor" and default_role(False) == "worker"


def test_observe_reconcile_and_recent(ledger):
    ledger.observe([GUI, WORKER])
    assert ledger.instance(GUI.pid)["alive"] is True
    assert ledger.role_of(GUI.pid, True) == "editor"
    assert ledger.role_of(WORKER.pid, False) == "worker"
    assert ledger.recent() == []
    ledger.observe([GUI], reconcile=True)  # the worker's registry entry is gone
    (gone,) = ledger.recent()
    assert gone["pid"] == WORKER.pid and gone["hip"] == "C:/work/b.hip"
    assert gone["role"] == "worker" and gone["alive"] is False and gone["last_seen"]
    ledger.observe([GUI, WORKER])  # it is back (same process)
    assert ledger.recent() == []


def test_roles_and_names(ledger):
    ledger.observe([GUI, WORKER])
    ledger.set_role(GUI.pid, "worker")
    assert ledger.role_of(GUI.pid, True) == "worker"
    with pytest.raises(ValueError):
        ledger.set_role(GUI.pid, "boss")
    ledger.set_name(WORKER.pid, "farm")
    assert ledger.find_name("farm")["pid"] == WORKER.pid
    ledger.set_name(GUI.pid, "farm")  # a name moves
    assert ledger.find_name("farm")["pid"] == GUI.pid
    assert "name" not in ledger.instance(WORKER.pid)


def test_reused_pid_forgets_the_old_role(ledger):
    ledger.observe([WORKER])
    ledger.set_role(WORKER.pid, "editor")
    reborn = Instance(pid=WORKER.pid, port=1, token="x", started="2026-10-13T00:00:00Z")
    ledger.observe([reborn])
    assert ledger.role_of(WORKER.pid, False) == "worker"


def test_jobs_map_ids_update_and_survive_reopen(tmp_path):
    led = Ledger.at(tmp_path / "state")
    host_id = f"{WORKER.pid}-9c3e6f7ca53e"
    job_id = led.record_job(WORKER.pid, {"job_id": host_id, "tool": "render", "state": "running"})
    assert is_ledger_id(job_id) and len(job_id) == 6 and job_id.startswith("j")
    assert not is_ledger_id(host_id) and not is_ledger_id("9c3e6f7ca53e")
    assert led.record_job(WORKER.pid, {"job_id": host_id, "state": "running"}) == job_id
    assert led.to_host(job_id) == (WORKER.pid, host_id)
    assert led.to_host(host_id) is None and led.ledger_id(host_id) == job_id
    led.record_job(
        WORKER.pid,
        {"job_id": host_id, "state": "running", "current": 3, "total": 10, "message": "3/10"},
    )
    assert led.running(WORKER.pid) == 1
    led.record_job(WORKER.pid, {"job_id": host_id, "state": "done", "current": 10})
    row = led.job(job_id)
    assert row["state"] == "done" and row["finished"] and row["tool"] == "render"
    assert row["status"]["current"] == 10 and row["status"]["message"] == "3/10"
    led.close()
    again = Ledger.at(tmp_path / "state")  # a restarted bridge
    assert again.to_host(job_id) == (WORKER.pid, host_id)
    assert again.last_status(job_id)["state"] == "done"
    assert again.knows_pid(WORKER.pid) and not again.knows_pid(4242)
    (snap,) = again.jobs_snapshot()
    assert snap["id"] == job_id and snap["pid"] == WORKER.pid and snap["host_id"] == host_id
    assert again.jobs_snapshot(pid=GUI.pid) == []
    assert led.record_job(1, {"state": "running"}) is None  # no id: nothing recorded


def test_small_results_inline_large_ones_spill(tmp_path, ledger):
    small, big = f"{WORKER.pid}-aa", f"{WORKER.pid}-bb"
    ids = {h: ledger.record_job(WORKER.pid, {"job_id": h, "state": "done"}) for h in (small, big)}
    ledger.store_result(small, {"outputs": ["a.exr"]})
    payload = {"outputs": ["x" * 100 for _ in range(SPILL_BYTES // 50)]}
    ledger.store_result(big, payload)
    assert ledger.result(ids[small]) == {"outputs": ["a.exr"]}
    spilled = tmp_path / "state" / "jobs" / f"{ids[big]}.json"
    assert spilled.is_file() and json.loads(spilled.read_text(encoding="utf-8")) == payload
    assert ledger.result(big) == payload and ledger.job(big)["has_result"] is True
    assert not (tmp_path / "state" / "jobs" / f"{ids[small]}.json").exists()


def test_launches(ledger):
    ledger.record_launch(WORKER.pid, ["hython", "-m", "hocuspocus.host"], "C:/w", "headless")
    (row,) = ledger.launches(WORKER.pid)
    assert row["argv"][0] == "hython" and row["work_dir"] == "C:/w" and row["mode"] == "headless"
    assert ledger.knows_pid(WORKER.pid)


# -- the bridge feeds it ---------------------------------------------------------------------


class Host:
    def __init__(self, inst: Instance) -> None:
        self.inst = inst
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.snapshot: dict[str, Any] = {}

    def health(self, timeout_s: float = 5.0) -> dict[str, Any]:
        return {"ok": True, "hp": 1, "pid": self.inst.pid, "jobs_running": 0, "busy": False}

    def call(self, tool, args, timeout_s, request_id=None, max_response_bytes=None):
        self.calls.append((tool, dict(args)))
        host_id = f"{self.inst.pid}-00ab12cd34ef"
        if tool == "render":
            return True, {"job_id": host_id, "state": "running", "tool": "render"}, {}
        if tool == "job" and args.get("action") == "result":
            return True, {"job_id": host_id, "state": "done", "result": {"outputs": ["a"]}}, {}
        if tool == "job":
            return True, {"job_id": args.get("job_id"), "state": "running", "current": 1}, {}
        return True, {}, {}

    def job(self, job_id, timeout_s=10.0):
        return True, dict(self.snapshot, job_id=job_id), {}

    def call_jobs(self, request_id, timeout_s=5.0):
        return [dict(self.snapshot)] if self.snapshot else []


def _bridge(tmp_path, live, profile="compat_1x"):
    hosts = {inst.port: Host(inst) for inst in (GUI, WORKER)}
    bridge = Bridge(
        BridgeConfig(profile=profile),
        client_factory=lambda port, token: hosts[port],
        scan=lambda: list(live),
        ledger=Ledger.at(tmp_path / "state"),
    )
    bridge.exit_grace_s = 0.0
    return bridge, hosts


def test_a_job_a_call_starts_is_recorded_with_its_result(tmp_path):
    live = [WORKER]
    bridge, _hosts = _bridge(tmp_path, live)
    result = bridge.call_tool("render", {"rop_path": "/out/k"})
    host_id = json.loads(result.content[0].text)["job_id"]
    assert host_id == f"{WORKER.pid}-00ab12cd34ef"  # compat_1x: the 1.4 id
    job_id = bridge.ledger.ledger_id(host_id)
    assert bridge.ledger.job(job_id)["tool"] == "render"
    bridge.call_tool("job", {"action": "result", "job_id": host_id})
    assert bridge.ledger.result(job_id) == {"outputs": ["a"]}


def test_progress_poller_feeds_the_ledger(tmp_path):
    live = [WORKER]
    bridge, hosts = _bridge(tmp_path, live)
    host = hosts[WORKER.port]
    host.snapshot = {"job_id": f"{WORKER.pid}-77", "state": "running", "current": 2, "total": 8}
    bridge._inflight["req"] = WORKER
    snap = bridge.progress_snapshot("render", {}, "req")
    assert snap["current"] == 2 and snap["total"] == 8
    assert bridge.ledger.last_status(f"{WORKER.pid}-77")["current"] == 2


def test_restarted_bridge_reports_a_dead_instances_job_from_the_ledger(tmp_path):
    live = [WORKER]
    bridge, hosts = _bridge(tmp_path, live)
    host_id = f"{WORKER.pid}-00ab12cd34ef"
    bridge.call_tool("render", {"rop_path": "/out/k"})
    bridge.call_tool("job", {"action": "status", "job_id": host_id})
    bridge.ledger.close()
    live.clear()  # the worker died while no bridge was running
    fresh, _ = _bridge(tmp_path, live)
    assert fresh.ledger.recent()[0]["pid"] == WORKER.pid  # reconciled on start
    result = fresh.call_tool("job", {"action": "status", "job_id": host_id})
    error = json.loads(result.content[0].text)
    assert result.is_error and error["code"] == "instance_lost"
    assert error["detail"]["last_status"]["current"] == 1
    assert error["detail"]["label"] == "hython"


def test_fake_bridges_keep_the_ledger_in_memory(tmp_path):
    bridge = Bridge(BridgeConfig(profile="full"), scan=lambda: [])
    assert bridge.ledger.path is None
    assert not (tmp_path / "state" / LEDGER_FILE).exists()
