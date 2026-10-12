"""HFS detection and launching Houdini with an injected spawner (nothing real is started)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hocuspocus.bridge import launch
from hocuspocus.bridge.config import BridgeConfig
from hocuspocus.bridge.instances import Instance
from hocuspocus.bridge.launch import Launcher, detect_hfs
from hocuspocus.bridge.server import Bridge
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


def fake_hfs(root: Path, gui: bool = True) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "bin" / f"hython{launch.EXE}").write_text("")
    if gui:
        (root / "bin" / f"houdinifx{launch.EXE}").write_text("")
    return root


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUSPOCUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HOCUSPOCUS_WORK_DIR", raising=False)


class FakeProc:
    def __init__(self, pid: int, exit_code: int | None = None) -> None:
        self.pid = pid
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class Harness:
    """A fake spawner plus a fake registry the 'launched' host registers into."""

    def __init__(
        self, pid: int = 9001, register: bool = True, exit_code: int | None = None
    ) -> None:
        self.pid = pid
        self.register = register
        self.exit_code = exit_code
        self.live: list[Instance] = []
        self.spawned: list[tuple[list[str], dict, Path, Path | None]] = []
        self.polls = 0

    def spawner(self, argv, env, cwd, log_path):
        self.spawned.append((argv, env, cwd, log_path))
        return FakeProc(self.pid, self.exit_code)

    def scan(self):
        self.polls += 1
        registered = any(i.pid == self.pid for i in self.live)
        if (
            self.spawned and self.register and self.polls >= 3 and not registered
        ):  # after a few polls
            self.live.append(
                Instance(pid=self.pid, port=52000, token="tk", started="2026-10-12T12:00:00Z")
            )
        return list(self.live)


def make_launcher(
    hfs: Path, harness: Harness, clock_step: float = 1.0, outlives: bool | None = None
) -> Launcher:
    t = [0.0]

    def clock():
        return t[0]

    def sleep(seconds):
        t[0] += clock_step

    extra = {} if outlives is None else {"outlives": lambda proc: outlives}
    return Launcher(
        str(hfs),
        spawner=harness.spawner,
        scan=harness.scan,
        sleep=sleep,
        clock=clock,
        environ={},
        **extra,
    )


def test_detect_hfs_prefers_explicit_then_env(tmp_path):
    a = fake_hfs(tmp_path / "a")
    b = fake_hfs(tmp_path / "b")
    assert detect_hfs(str(a), {"HFS": str(b)}) == a
    assert detect_hfs(None, {"HFS": str(b)}) == b
    assert detect_hfs(str(tmp_path / "missing"), {"HFS": str(b)}) == b


def test_detect_hfs_picks_newest_standard_install(tmp_path, monkeypatch):
    for name in ("Houdini 22.0.368", "Houdini 22.0.466", "Houdini 22.5.10"):
        fake_hfs(tmp_path / name)
    (tmp_path / "Houdini 22.9.1").mkdir()  # no hython: ignored
    monkeypatch.setattr(launch, "_candidate_globs", lambda: [(str(tmp_path / "Houdini 22.*"), "")])
    assert detect_hfs(None, {}) == tmp_path / "Houdini 22.5.10"


def test_detect_hfs_none(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "_candidate_globs", lambda: [(str(tmp_path / "nothing*"), "")])
    assert detect_hfs(None, {}) is None


def test_headless_launch_builds_hython_command_and_waits(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    hip = tmp_path / "shot.hip"
    hip.write_text("")
    harness = Harness()
    result = make_launcher(hfs, harness).launch("headless", str(hip), wait_s=30)
    argv, env, cwd, log_path = harness.spawned[0]
    assert argv == [
        str(hfs / "bin" / f"hython{launch.EXE}"),
        "-m",
        "hocuspocus.host",
        "--hip",
        str(hip),
    ]
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(launch.package_root())
    assert (launch.package_root() / "hocuspocus" / "bridge").is_dir()
    assert log_path is not None and log_path.name.startswith("launch-headless-")
    assert Path(cwd) == Path.home()  # the untitled $HIP: never the state dir or repo
    assert result.instance.pid == 9001 and result.mode == "headless"


def test_launch_work_dir_override(tmp_path, monkeypatch):
    work = tmp_path / "shots" / "work"
    monkeypatch.setenv("HOCUSPOCUS_WORK_DIR", str(work))
    harness = Harness()
    make_launcher(fake_hfs(tmp_path / "hfs"), harness).launch("headless", None, wait_s=30)
    _argv, _env, cwd, _log = harness.spawned[0]
    assert Path(cwd) == work and work.is_dir()


def test_gui_launch_uses_houdinifx(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    harness = Harness()
    make_launcher(hfs, harness).launch("gui", None, wait_s=30)
    argv, _env, _cwd, log_path = harness.spawned[0]
    assert argv == [str(hfs / "bin" / f"houdinifx{launch.EXE}")]
    assert log_path is None


def test_launch_times_out_with_hint(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    harness = Harness(register=False)
    with pytest.raises(ToolError) as info:
        make_launcher(hfs, harness).launch("headless", None, wait_s=5)
    assert info.value.code == "houdini_offline"
    assert "did not register within 5s" in info.value.message


def test_launch_reports_early_exit(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    harness = Harness(register=False, exit_code=3)
    with pytest.raises(ToolError) as info:
        make_launcher(hfs, harness).launch("headless", None, wait_s=30)
    assert "exited with code 3" in info.value.message


def test_launch_missing_hip(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    with pytest.raises(ToolError) as info:
        make_launcher(hfs, Harness()).launch("gui", str(tmp_path / "nope.hip"))
    assert info.value.code == "file_not_found"


def test_launch_without_hfs(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "_candidate_globs", lambda: [])
    launcher = Launcher(None, spawner=Harness().spawner, scan=lambda: [], environ={})
    with pytest.raises(ToolError) as info:
        launcher.launch("headless")
    assert "HOCUSPOCUS_HFS" in (info.value.hint or "")


def test_houdini_connect_launch_path(tmp_path):
    hfs = fake_hfs(tmp_path / "hfs")
    harness = Harness()
    launcher = make_launcher(hfs, harness)

    class Client:
        def health(self, timeout_s=5.0):
            return {"ok": True, "hp": 1, "pid": 9001, "houdini": "22.0.466", "generation": 0}

        def call(self, tool, args, timeout_s, request_id=None):
            return True, {"echo": tool}, {}

    from hocuspocus.tools import catalog

    bridge = Bridge(
        BridgeConfig(),
        tools=catalog.TOOLS or None,
        client_factory=lambda p, t: Client(),
        scan=harness.scan,
        launcher=launcher,
    )
    if bridge._by_name.get("houdini_connect") is None:
        pytest.skip("catalogue has no houdini_connect yet")
    result = bridge.call_tool("houdini_connect", {"launch": {"mode": "headless", "wait_s": 30}})
    assert result.is_error is False, result.structured_content
    out = result.structured_content
    assert out["connected"]["pid"] == 9001
    assert out["launched"]["mode"] == "headless" and out["launched"]["pid"] == 9001
    assert bridge.preferred_pid == 9001
    assert len(harness.spawned) == 1
    launched = out["launched"]
    assert (
        launched["outlives_server"] is False and "closes when the server exits" in launched["note"]
    )


def test_launch_marks_the_child_and_records_who_launched_it(tmp_path):
    from hocuspocus.bridge.instances import LaunchLog
    from hocuspocus.tools import paths

    harness = Harness()
    result = make_launcher(fake_hfs(tmp_path / "hfs"), harness, outlives=True).launch(
        "headless", None, wait_s=30
    )
    _argv, env, _cwd, _log = harness.spawned[0]
    assert env[launch.LAUNCHED_BY_ENV] == str(os.getpid())
    assert result.outlives_server is True
    record = paths.state_dir() / "launches" / "9001.json"
    assert record.is_file()
    (orphan,) = LaunchLog().take_orphans(own_pid=1, alive=lambda pid: False)
    assert orphan["launched_by"] == os.getpid() and orphan["outlives_server"] is True


def test_outlives_probe_failure_means_false(tmp_path):
    def broken(proc):
        raise OSError("no job api")

    harness = Harness()
    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), harness)
    launcher.outlives = broken
    assert launcher.launch("headless", None, wait_s=30).outlives_server is False


def test_child_outlives_server_reads_the_job(monkeypatch):
    class Proc:
        _handle = 1
        hp_breakaway = True

    monkeypatch.setattr(launch.sys, "platform", "win32")
    monkeypatch.setattr(launch, "_process_in_job", lambda handle: False)
    assert launch.child_outlives_server(Proc()) is True
    monkeypatch.setattr(launch, "_process_in_job", lambda handle: True)
    monkeypatch.setattr(launch, "_own_job_kills_on_close", lambda: True)
    assert launch.child_outlives_server(Proc()) is False
    monkeypatch.setattr(launch, "_own_job_kills_on_close", lambda: False)
    assert launch.child_outlives_server(Proc()) is True

    def fails(handle):
        raise OSError("denied")

    monkeypatch.setattr(launch, "_process_in_job", fails)
    assert launch.child_outlives_server(Proc()) is True  # falls back to the breakaway flag
    monkeypatch.setattr(launch.sys, "platform", "linux")
    assert launch.child_outlives_server(object()) is True
