"""Instance registry reading, stale pruning and selection (BIBLE §3.3 rule 3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hocuspocus.bridge import instances as registry
from hocuspocus.bridge.instances import Instance, select

pytestmark = pytest.mark.unit


def _inst(pid: int, started: str, **kw) -> Instance:
    return Instance(pid=pid, port=40000 + pid % 1000, token="t", started=started, **kw)


def _write(directory: Path, pid: int, started: str = "2026-10-12T10:00:00Z", **extra) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "hp": 1,
        "pid": pid,
        "port": 50000 + pid % 1000,
        "token": f"tok{pid}",
        "houdini": "22.0.466",
        "ui": False,
        "hip": "",
        "started": started,
        "generation": 0,
        "label": "hython",
    }
    data.update(extra)
    path = directory / f"{pid}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_select_none():
    sel = select([], None)
    assert sel.instance is None
    assert sel.warnings == ()


def test_select_only_live_instance_no_warning():
    a = _inst(1, "2026-10-12T10:00:00Z")
    sel = select([a], None)
    assert sel.instance == a
    assert sel.warnings == ()
    assert not sel.multiple


def test_select_most_recent_with_warning_when_several():
    old = _inst(1, "2026-10-12T09:00:00Z")
    new = _inst(2, "2026-10-12T10:00:00Z")
    sel = select([old, new], None)
    assert sel.instance == new
    assert sel.multiple
    assert len(sel.warnings) == 1 and "pid 2" in sel.warnings[0] and "1" in sel.warnings[0]


def test_select_explicit_wins_without_warning():
    old = _inst(1, "2026-10-12T09:00:00Z")
    new = _inst(2, "2026-10-12T10:00:00Z")
    sel = select([new, old], preferred_pid=1)
    assert sel.instance == old
    assert sel.warnings == ()


def test_select_explicit_gone_falls_back_with_warning():
    only = _inst(2, "2026-10-12T10:00:00Z")
    sel = select([only], preferred_pid=99)
    assert sel.instance == only
    assert any("99" in w for w in sel.warnings)


def test_scan_prunes_dead_and_keeps_live(tmp_path):
    live = _write(tmp_path, 100, "2026-10-12T10:00:00Z")
    dead = _write(tmp_path, 200, "2026-10-12T11:00:00Z")
    (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")
    found = registry.scan(tmp_path, alive=lambda pid: pid == 100)
    assert [i.pid for i in found] == [100]
    assert live.exists()
    assert not dead.exists()
    assert (tmp_path / "garbage.json").exists()  # may be mid-write; never deleted
    assert found[0].token == "tok100"
    assert "token" not in found[0].public()


def test_scan_without_prune_keeps_files(tmp_path):
    dead = _write(tmp_path, 200)
    assert registry.scan(tmp_path, prune=False, alive=lambda pid: False) == []
    assert dead.exists()


def test_scan_orders_most_recent_first(tmp_path):
    _write(tmp_path, 1, "2026-10-12T09:00:00Z")
    _write(tmp_path, 2, "2026-10-12T11:00:00Z")
    _write(tmp_path, 3, "2026-10-12T10:00:00Z")
    assert [i.pid for i in registry.scan(tmp_path, alive=lambda pid: True)] == [2, 3, 1]


def test_scan_missing_dir_is_empty(tmp_path):
    assert registry.scan(tmp_path / "nope") == []


def test_scan_uses_state_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path))
    _write(tmp_path / "instances", os.getpid())
    assert [i.pid for i in registry.scan()] == [os.getpid()]


def test_pid_alive_real_processes():
    assert registry.pid_alive(os.getpid())
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert not registry.pid_alive(proc.pid)
    assert not registry.pid_alive(0)
    assert not registry.pid_alive(-5)


def test_launched_by_round_trips_and_is_public():
    inst = registry.Instance.from_dict({"pid": 5, "port": 1, "token": "t", "launched_by": 77})
    assert inst.launched_by == 77 and inst.public()["launched_by"] == 77
    plain = registry.Instance.from_dict({"pid": 5, "port": 1, "token": "t"})
    assert plain.launched_by is None and plain.public()["launched_by"] is None
    assert "token" not in plain.public()


def test_launch_log_reports_dead_launches_of_other_bridges_once(tmp_path):
    log = registry.LaunchLog(tmp_path / "launches")
    log.record(
        registry.Instance(pid=101, port=1, token="t", hip="C:/w/a.hip", started="2026-10-12T10"),
        mode="headless",
        outlives_server=False,
    )
    log.record(registry.Instance(pid=102, port=1, token="t"), mode="gui", outlives_server=True)
    me = os.getpid()
    # Recorded by this process: never an orphan of "another" bridge, but pruned once dead.
    assert log.take_orphans(own_pid=me, alive=lambda pid: False) == []
    assert list((tmp_path / "launches").glob("*.json")) == []

    log.record(
        registry.Instance(pid=101, port=1, token="t", hip="C:/w/a.hip"),
        mode="headless",
        outlives_server=False,
    )
    alive = {101: True, me: False}
    assert log.take_orphans(own_pid=999, alive=lambda pid: alive.get(pid, False)) == []
    alive[101] = False
    (orphan,) = log.take_orphans(own_pid=999, alive=lambda pid: alive.get(pid, False))
    assert orphan["pid"] == 101 and orphan["launched_by"] == me
    assert orphan["launcher_alive"] is False and orphan["hip"] == "C:/w/a.hip"
    assert log.take_orphans(own_pid=999, alive=lambda pid: False) == []  # reported once
