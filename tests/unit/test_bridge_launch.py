"""HFS detection and launching Houdini with an injected spawner (nothing real is started)."""

from __future__ import annotations

import json
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

    extra: dict = {"python_dir": lambda environ: (hfs.parent / "hostpkg", "test")}
    if outlives is not None:
        extra["outlives"] = lambda proc: outlives
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
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(hfs.parent / "hostpkg")
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


def test_launch_explicit_work_dir_reaches_the_headless_host(tmp_path, monkeypatch):
    """hocuspocus launch passes its directory: the child starts there and the headless
    host is told to stay there instead of moving to HOCUSPOCUS_WORK_DIR or home."""
    monkeypatch.setenv("HOCUSPOCUS_WORK_DIR", str(tmp_path / "not_this"))
    work = tmp_path / "shot"
    work.mkdir()
    harness = Harness()
    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), harness)
    launcher.wait(launcher.spawn("headless", None, work_dir=work), 30)
    argv, _env, cwd, _log = harness.spawned[0]
    assert Path(cwd) == work
    assert argv[-2:] == ["--work-dir", str(work)]
    harness = Harness()
    launcher = make_launcher(fake_hfs(tmp_path / "hfs2"), harness)
    launcher.wait(launcher.spawn("gui", None, work_dir=work), 30)
    argv, _env, cwd, _log = harness.spawned[0]
    assert Path(cwd) == work and "--work-dir" not in argv  # the GUI's $HIP is its cwd


def test_launch_without_work_dir_keeps_the_bridge_rule(tmp_path, monkeypatch):
    work = tmp_path / "configured"
    monkeypatch.setenv("HOCUSPOCUS_WORK_DIR", str(work))
    harness = Harness()
    make_launcher(fake_hfs(tmp_path / "hfs"), harness).launch("headless", None, wait_s=30)
    argv, _env, cwd, _log = harness.spawned[0]
    assert Path(cwd) == work and "--work-dir" not in argv  # the host applies the same rule


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
    out = json.loads(result.content[0].text)
    assert result.is_error is False, out
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


# -- the package a headless hython imports (review 10: never site-packages) -----------


def fake_package(base: Path, version: str = "9.9.9", *, with_bridge: bool = True) -> Path:
    pkg = base / "hocuspocus"
    for sub in ("host", "tools"):
        (pkg / sub).mkdir(parents=True)
        (pkg / sub / "__init__.py").write_text("")
    if with_bridge:
        (pkg / "bridge").mkdir()
        (pkg / "bridge" / "server.py").write_text("import mcp\n")
        (pkg / "cli.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "version.py").write_text(f'__version__ = "{version}"\n')
    return base


def resolve(tmp_path, environ=None, *, root=None):
    return launch.host_python_dir(
        environ if environ is not None else {"HOUDINI_USER_PREF_DIR": str(tmp_path / "prefs")},
        state=tmp_path / "state",
        root=root if root is not None else fake_package(tmp_path / "venv" / "site-packages"),
        version="9.9.9",
    )


def write_package_json(prefs: Path, python_dir: Path) -> None:
    (prefs / "packages").mkdir(parents=True, exist_ok=True)
    data = {"env": [{"PYTHONPATH": {"value": python_dir.as_posix(), "method": "prepend"}}]}
    (prefs / "packages" / "hocuspocus.json").write_text(json.dumps(data))


def test_host_package_prefers_the_install_record(tmp_path):
    installed = fake_package(tmp_path / "prefs" / "hocuspocus" / "9.9.9" / "python")
    write_package_json(tmp_path / "prefs", fake_package(tmp_path / "other"))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "install.json").write_text(json.dumps({"python_dir": str(installed)}))
    assert resolve(tmp_path) == (installed, "install.json")


def test_host_package_then_the_package_json(tmp_path):
    other = fake_package(tmp_path / "other")
    write_package_json(tmp_path / "prefs", other)
    stale = fake_package(tmp_path / "old", version="0.9.0")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "install.json").write_text(json.dumps({"python_dir": str(stale)}))
    assert resolve(tmp_path) == (other, "package json")  # a stale version never qualifies


def test_host_package_then_the_checkout(tmp_path):
    checkout = tmp_path / "repo"
    fake_package(checkout / "src")
    (checkout / "pyproject.toml").write_text("")
    assert resolve(tmp_path, root=checkout / "src") == (checkout / "src", "checkout")


def test_host_package_never_site_packages_copies_host_side_only(tmp_path):
    site = fake_package(tmp_path / "venv" / "Lib" / "site-packages")
    write_package_json(tmp_path / "prefs", site)  # a package json pointing into a venv
    found, source = resolve(tmp_path, root=site)
    assert source == "launch-pkg" and "site-packages" not in found.parts
    assert found == tmp_path / "state" / "launch-pkg" / "9.9.9"
    copied = found / "hocuspocus"
    assert (copied / "host").is_dir() and (copied / "tools").is_dir()
    assert not (copied / "bridge").exists() and not (copied / "cli.py").exists()
    assert resolve(tmp_path, root=site) == (found, "launch-pkg")  # reused, not recopied


def test_headless_launch_pythonpath_never_names_site_packages(tmp_path, monkeypatch):
    site = fake_package(tmp_path / "venv" / "Lib" / "site-packages")
    monkeypatch.setattr(launch, "package_root", lambda: site)
    monkeypatch.setenv("HOUDINI_USER_PREF_DIR", str(tmp_path / "prefs"))
    harness = Harness()
    launcher = Launcher(
        str(fake_hfs(tmp_path / "hfs")),
        spawner=harness.spawner,
        scan=harness.scan,
        sleep=lambda s: None,
        environ={"HOUDINI_USER_PREF_DIR": str(tmp_path / "prefs")},
        python_dir=lambda environ: launch.host_python_dir(environ, version="9.9.9"),
    )
    launcher.launch("headless", None, wait_s=30)
    _argv, env, _cwd, _log = harness.spawned[0]
    assert "site-packages" not in env["PYTHONPATH"]


# -- hocuspocus launch (review 11 B1): a Houdini no server owns ------------------------


def test_unowned_launch_is_not_tagged_or_recorded(tmp_path):
    from hocuspocus.tools import paths

    harness = Harness()
    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), harness)
    launcher.owned = False
    launcher.environ = {launch.LAUNCHED_BY_ENV: "123"}  # inherited from a bridge: dropped
    launcher.launch("headless", None, wait_s=30)
    _argv, env, _cwd, _log = harness.spawned[0]
    assert launch.LAUNCHED_BY_ENV not in env
    assert not (paths.state_dir() / "launches").exists()


def test_headless_launch_waits_for_its_own_pid(tmp_path):
    """Review 10 §1.9: a GUI the user starts during the wait is not the launched hython."""
    harness = Harness()
    stranger = Instance(pid=7777, port=1, token="x", started="2026-10-12T12:00:01Z")
    original = harness.scan

    def scan():
        live = original()
        return [*live, stranger] if harness.spawned else live

    launcher = make_launcher(fake_hfs(tmp_path / "hfs"), harness)
    launcher.scan = scan
    assert launcher.launch("headless", None, wait_s=30).instance.pid == 9001


def test_relative_hip_is_resolved_before_launch(tmp_path, monkeypatch):
    (tmp_path / "shot.hip").write_text("")
    monkeypatch.chdir(tmp_path)
    harness = Harness()
    make_launcher(fake_hfs(tmp_path / "hfs"), harness).launch("headless", "shot.hip", wait_s=30)
    argv = harness.spawned[0][0]
    assert argv[-1] == str((tmp_path / "shot.hip").resolve())
