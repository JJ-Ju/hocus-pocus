"""Host lifecycle: registry entry, scene generation, and the headless ``__main__`` process."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

hou = pytest.importorskip("hou")

REPO_SRC = Path(__file__).resolve().parents[2] / "src"


def test_registry_entry_for_session_host(host):
    entry = json.loads(host.registry.path.read_text(encoding="utf-8"))
    assert set(entry) == {
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
        "launched_by",
    }
    # Set from HOCUSPOCUS_LAUNCHED_BY only when a bridge launched this Houdini.
    assert entry["launched_by"] == (
        int(os.environ["HOCUSPOCUS_LAUNCHED_BY"])
        if "HOCUSPOCUS_LAUNCHED_BY" in os.environ
        else None
    )
    assert entry["hp"] == 1
    assert entry["pid"] == os.getpid()
    assert entry["port"] == host.port
    assert entry["token"] == host.token and len(entry["token"]) >= 40
    assert entry["houdini"] == hou.applicationVersionString()
    assert entry["ui"] is False
    assert host.registry.path.name == f"{os.getpid()}.json"


def test_registry_tracks_hip_and_generation(client, work_dir):
    target = (work_dir / "reg.hip").as_posix()
    client.ok("hip_save", {"path": target})
    client.ok("hip_open", {"path": target})
    entry = json.loads(client.host.registry.path.read_text(encoding="utf-8"))
    assert entry["hip"] == target
    assert entry["generation"] == client.host.scene.generation


def test_generation_bumps_on_clear_and_load(client, work_dir):
    target = (work_dir / "gen.hip").as_posix()
    client.ok("hip_save", {"path": target})
    g0 = client.host.scene.generation
    client.ok("hip_new")
    g1 = client.host.scene.generation
    assert g1 == g0 + 1
    client.ok("hip_open", {"path": target})
    assert client.host.scene.generation == g1 + 1  # one bump per load, not per internal clear


def test_second_host_writes_and_removes_its_entry(tmp_path):
    from hocuspocus.host.config import HostConfig
    from hocuspocus.host.runtime import Host

    state = tmp_path / "state2"
    second = Host(HostConfig(state_dir=str(state), label="second"))
    second.start()
    try:
        path = state / "instances" / f"{os.getpid()}.json"
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry["label"] == "second"
        assert entry["port"] == second.port
        with urllib.request.urlopen(f"http://127.0.0.1:{second.port}/hp/v1/health", timeout=5) as r:
            assert json.loads(r.read())["ok"] is True
    finally:
        second.stop()
    assert not path.exists()
    second.stop()  # idempotent


def test_start_is_idempotent(host):
    import hocuspocus.host as hp

    info = hp.start()
    assert info["running"] is True
    assert info["port"] == host.port
    assert "token" not in info


def _read_line(stream, box):
    box["line"] = stream.readline()


def test_headless_main_process(hython, tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    state = tmp_path / "state"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_SRC)
    env["HOUDINI_USER_PREF_DIR"] = (tmp_path / "prefs" / "houdini__HVER__").as_posix()
    env["HOCUSPOCUS_STATE_DIR"] = str(state)
    work = tmp_path / "work"
    env["HOCUSPOCUS_WORK_DIR"] = str(work)
    proc = subprocess.Popen(
        [str(hython), "-m", "hocuspocus.host", "--port", "0"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        box: dict = {}
        reader = threading.Thread(target=_read_line, args=(proc.stdout, box), daemon=True)
        reader.start()
        reader.join(120)
        assert "line" in box, "host did not print its JSON line within 120 s"
        info = json.loads(box["line"])
        assert set(info) == {"pid", "port", "token_file"}
        assert info["pid"] == proc.pid or info["pid"] > 0
        token = json.loads(Path(info["token_file"]).read_text(encoding="utf-8"))["token"]
        base = f"http://127.0.0.1:{info['port']}/hp/v1"

        with urllib.request.urlopen(f"{base}/health", timeout=10) as r:
            health = json.loads(r.read())
        assert health["ok"] is True and health["ui"] is False

        def post(path, body):
            request = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=60) as r:
                return json.loads(r.read())

        status = post("/call", {"tool": "houdini_status", "args": {}})
        assert status["ok"] is True
        assert status["result"]["port"] == info["port"]
        # The untitled scene lives in the work dir, not the launch cwd or the state dir.
        hip = status["result"]["hip"]
        assert hip["path"] == f"{work.as_posix()}/untitled.hip", hip
        assert hip["note"] == "$HIP is the launch directory until you hip_save."
        assert status["result"]["env"]["HIP"] == work.as_posix()
        assert status["result"]["env"]["JOB"] == work.as_posix()

        assert post("/shutdown", {})["ok"] is True
        code = proc.wait(timeout=60)
        assert code == 0, proc.stderr.read()
        assert not Path(info["token_file"]).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()
