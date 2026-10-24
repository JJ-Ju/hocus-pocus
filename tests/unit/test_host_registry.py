from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from hocuspocus.host import registry as host_registry
from hocuspocus.host.registry import (
    InstanceRegistry,
    list_entries,
    new_token,
    pid_alive,
    prune_stale,
)


def test_token_is_long_and_random():
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 40


def test_write_update_remove(tmp_path):
    registry = InstanceRegistry(tmp_path / "instances", pid=4242)
    path = registry.write(
        {
            "port": 5000,
            "token": "t",
            "houdini": "22.0.466",
            "ui": False,
            "hip": "C:/a.hip",
            "started": "2026-10-12T10:00:00Z",
            "generation": 0,
            "label": "hython",
        }
    )
    assert path == tmp_path / "instances" / "4242.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hp"] == 1 and data["pid"] == 4242 and data["port"] == 5000
    assert list(data) == [
        "hp",
        "pid",
        "port",
        "token",
        "houdini",
        "ui",
        "hip",
        "started",
        "generation",
        "label",
    ]

    registry.update(hip="C:/b.hip", generation=3)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hip"] == "C:/b.hip" and data["generation"] == 3 and data["token"] == "t"
    assert [p.name for p in path.parent.iterdir()] == ["4242.json"]  # no temp files left

    registry.remove()
    assert not path.exists()
    registry.remove()  # idempotent
    registry.update(hip="x")  # no-op after removal
    assert not path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_entry_is_user_private(tmp_path):
    registry = InstanceRegistry(tmp_path / "instances", pid=1)
    path = registry.write({"port": 1})
    assert path.stat().st_mode & 0o077 == 0


def test_pid_alive_for_self_and_dead_child():
    assert pid_alive(os.getpid()) is True
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert pid_alive(child.pid) is False
    assert pid_alive(0) is False
    assert pid_alive(-5) is False


def test_pid_alive_for_running_child_does_not_kill_it():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert pid_alive(child.pid) is True
        assert pid_alive(child.pid) is True
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


@pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(os, "waitid"), reason="POSIX zombies, os.waitid"
)
def test_pid_alive_treats_an_unreaped_child_as_dead():
    """A launched Houdini that exits stays a zombie child of the bridge until reaped;
    kill(pid, 0) still succeeds for it. It is dead, and Popen can still reap it."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
    deadline = time.monotonic() + 10
    while os.waitid(os.P_PID, child.pid, flags) is None and time.monotonic() < deadline:
        time.sleep(0.01)
    os.kill(child.pid, 0)  # the zombie still answers
    assert pid_alive(child.pid) is False
    assert child.wait(5) == 0  # left for Popen: the exit code is not lost


class _Exited:
    """What os.waitid returns for an exited child."""

    si_pid = 4242


def _posix_without_signals(monkeypatch):
    monkeypatch.setattr(host_registry.sys, "platform", "linux")
    monkeypatch.setattr(host_registry.os, "kill", lambda pid, sig: None)
    for name, value in (("P_PID", 1), ("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 0x1000000)):
        monkeypatch.setattr(host_registry.os, name, value, raising=False)


def test_pid_alive_zombie_detection_with_fakes(monkeypatch):
    """The same rule on any platform: our exited child (waitid with WNOWAIT), else the
    state letter in /proc/<pid>/stat."""
    _posix_without_signals(monkeypatch)
    calls = []

    def exited_child(idtype, pid, options):
        calls.append(options)
        return _Exited()

    monkeypatch.setattr(host_registry.os, "waitid", exited_child, raising=False)
    assert pid_alive(4242) is False
    assert calls and calls[0] & 0x1000000  # WNOWAIT: never reaps it

    def not_our_child(idtype, pid, options):
        raise ChildProcessError(10, "No child processes")

    monkeypatch.setattr(host_registry.os, "waitid", not_our_child, raising=False)
    states = {"state": "Z"}
    monkeypatch.setattr(host_registry, "_proc_state", lambda pid: states["state"])
    assert pid_alive(4242) is False
    states["state"] = "S"
    assert pid_alive(4242) is True
    states["state"] = None  # macOS: no /proc
    assert pid_alive(4242) is True

    monkeypatch.delattr(host_registry.os, "waitid", raising=False)  # macOS before 3.13
    states["state"] = "Z"
    assert pid_alive(4242) is False


def test_proc_state_parses_a_command_name_with_spaces_and_parens(tmp_path, monkeypatch):
    stat = tmp_path / "stat"
    stat.write_text("4242 (my (odd) cmd) Z 1 4242 4242 0 -1 4194560\n", encoding="ascii")
    real_path = host_registry.Path

    def fake_path(text):
        return stat if text == "/proc/4242/stat" else real_path(text)

    monkeypatch.setattr(host_registry, "Path", fake_path)
    assert host_registry._proc_state(4242) == "Z"
    assert host_registry._proc_state(4243) is None


def test_prune_stale(tmp_path):
    instances = tmp_path / "instances"
    instances.mkdir()
    live = InstanceRegistry(instances, pid=os.getpid())
    live.write({"port": 1})
    dead_child = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_child.wait()
    (instances / f"{dead_child.pid}.json").write_text(
        json.dumps({"pid": dead_child.pid}), encoding="utf-8"
    )
    (instances / "999999.json").write_text("{corrupt", encoding="utf-8")
    (instances / "notes.json").write_text("{}", encoding="utf-8")

    removed = prune_stale(instances)
    assert sorted(p.name for p in removed) == sorted([f"{dead_child.pid}.json", "999999.json"])
    assert sorted(p.name for p in instances.iterdir()) == sorted(
        [f"{os.getpid()}.json", "notes.json"]
    )
    assert [e["pid"] for e in list_entries(instances) if "pid" in e] == [os.getpid()]


def test_prune_missing_dir(tmp_path):
    assert prune_stale(tmp_path / "nope") == []


def test_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    import hocuspocus.host.registry as reg

    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "being read by the bridge")
        real_replace(src, dst)

    monkeypatch.setattr(reg.os, "replace", flaky)
    monkeypatch.setattr(reg, "REPLACE_DELAY_S", 0.001)
    registry = InstanceRegistry(tmp_path / "instances", pid=4242)
    path = registry.write({"port": 1, "hip": "a"})
    assert len(calls) == 3
    assert json.loads(path.read_text(encoding="utf-8"))["port"] == 1


def test_failed_update_is_rewritten_on_next_update(tmp_path, monkeypatch):
    import hocuspocus.host.registry as reg

    monkeypatch.setattr(reg, "REPLACE_DELAY_S", 0.001)
    registry = InstanceRegistry(tmp_path / "instances", pid=4242)
    path = registry.write({"port": 1, "hip": "a", "generation": 0})
    real_replace = os.replace

    def locked(src, dst):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(reg.os, "replace", locked)
    registry.update(hip="b")  # must not raise; the file is stale for now
    assert json.loads(path.read_text(encoding="utf-8"))["hip"] == "a"
    assert [p.name for p in path.parent.iterdir()] == ["4242.json"]  # temp file cleaned
    monkeypatch.setattr(reg.os, "replace", real_replace)
    registry.update(hip="b")  # nothing new in memory, but the pending write lands
    assert json.loads(path.read_text(encoding="utf-8"))["hip"] == "b"
    registry.update(generation=1)
    assert json.loads(path.read_text(encoding="utf-8"))["generation"] == 1


def test_prune_keeps_unreadable_entry_of_live_pid(tmp_path):
    instances = tmp_path / "instances"
    instances.mkdir()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Half-written (mid-replace) or unparseable for a moment: not proof of death.
        (instances / f"{child.pid}.json").write_text("{corrupt", encoding="utf-8")
        (instances / f"{os.getpid()}.json").write_text("{}", encoding="utf-8")  # no pid key
        assert prune_stale(instances) == []
        assert len(list(instances.iterdir())) == 2
    finally:
        child.kill()
        child.wait()
    removed = prune_stale(instances)
    assert [p.name for p in removed] == [f"{child.pid}.json"]
