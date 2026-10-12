from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

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
